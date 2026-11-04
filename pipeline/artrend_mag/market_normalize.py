"""Normalize the legacy auction lots into an isolated, provenance-preserving stage."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import ARTRENDATA, WORK_ROOT, iso_now

SOURCE_TABLE = "lots"
SOURCE_PRIMARY_KEY = "id"
FX_SOURCE_ID = "ecb_fx"
FX_MAX_PRIOR_DAYS = 7
DEFAULT_BATCH_SIZE = 1000

_STATUS_MAP = {
    "sold": "sold",
    "unsold": "unsold",
    "bi": "bought_in",
    "boughtin": "bought_in",
    "returntoowner": "withdrawn",
    "withdrawn": "withdrawn",
    "wd": "withdrawn",
    "livenotopen": "not_open",
    "complete": "complete",
    "incomplete": "incomplete",
    "open": "open",
    "new": "new",
    "notshown": "not_shown",
    "ongoing": "ongoing",
    "reofferforsale": "reoffered",
}
_BASIS_MAP = {
    "hammer": "hammer",
    "hammer+premium": "hammer_plus_premium",
    "hammerpluspremium": "hammer_plus_premium",
    "hammer_plus_premium": "hammer_plus_premium",
    "hammer plus premium": "hammer_plus_premium",
}
_CURRENCY_ALIAS = {"RMB": "CNY"}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _read_only_immutable(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _read_only(path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite database while honoring active WAL contents."""
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _table_columns(con: sqlite3.Connection, table: str) -> List[Tuple[Any, ...]]:
    return con.execute("PRAGMA table_info({})".format(_quote(table))).fetchall()


def _normalize_date(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing_date"
    if not isinstance(value, str):
        return None, "invalid_date_type"
    text = value.strip()
    if text == "1970-01-01":
        return None, "placeholder_1970_01_01"
    if not _DATE_PATTERN.fullmatch(text):
        return None, "invalid_date_format"
    try:
        return dt.date.fromisoformat(text).isoformat(), None
    except ValueError:
        return None, "invalid_calendar_date"


def _status_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s_-]+", "", value.strip().casefold())


def _normalize_status(value: Any) -> Tuple[str, Optional[str]]:
    token = _status_token(value)
    if not token:
        return "unknown", "missing_status"
    normalized = _STATUS_MAP.get(token)
    if normalized is None:
        return "unknown", "unmapped_status"
    return normalized, None


def _normalize_currency(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing_currency"
    if not isinstance(value, str):
        return None, "invalid_currency_type"
    code = value.strip().upper()
    code = _CURRENCY_ALIAS.get(code, code)
    if not re.fullmatch(r"[A-Z]{3}", code):
        return None, "invalid_currency_code"
    return code, None


def _normalize_basis(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing_basis"
    if not isinstance(value, str):
        return None, "invalid_basis_type"
    token = value.strip().casefold()
    normalized = _BASIS_MAP.get(token)
    if normalized is None:
        return None, "unrecognized_basis"
    return normalized, None


def _normalize_price(value: Any) -> Tuple[Optional[Any], Optional[str]]:
    if value is None:
        return None, "missing_price"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "invalid_price_type"
    try:
        numeric = float(value)
    except OverflowError:
        return None, "non_finite_price"
    if not math.isfinite(numeric):
        return None, "non_finite_price"
    if numeric < 0:
        return None, "negative_price"
    # Keep the original SQLite numeric type (including an explicitly supplied zero).
    return value, None


def _registered_ecb_fx_rates(path: Optional[Path]) -> Tuple[Dict[str, Dict[str, Tuple[float, str]]], Dict[str, Any]]:
    info: Dict[str, Any] = {
        "path": str(path.resolve()) if path is not None else None,
        "source_id": FX_SOURCE_ID,
        "verification": "registered_reference_source",
        "loaded_rate_count": 0,
        "status": "unavailable",
    }
    rates: Dict[str, Dict[str, Tuple[float, str]]] = defaultdict(dict)
    if path is None or not path.is_file():
        info["status"] = "database_missing"
        return rates, info

    con = _read_only(path)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "sources" not in tables or "fx_rates" not in tables:
            info["status"] = "required_tables_missing"
            return rates, info
        source_columns = {row[1] for row in _table_columns(con, "sources")}
        rate_columns = {row[1] for row in _table_columns(con, "fx_rates")}
        if not {"source_id", "source_kind"}.issubset(source_columns) or not {
            "rate_date", "base", "quote", "rate", "source_id"
        }.issubset(rate_columns):
            info["status"] = "required_columns_missing"
            return rates, info
        source = con.execute(
            "SELECT source_kind FROM sources WHERE source_id=?", (FX_SOURCE_ID,)
        ).fetchone()
        if source is None or source[0] != "reference":
            info["status"] = "unverified_source"
            return rates, info

        for rate_date, base, quote, rate, source_id in con.execute(
            "SELECT rate_date, base, quote, rate, source_id FROM fx_rates "
            "WHERE base='EUR' AND source_id=?",
            (FX_SOURCE_ID,),
        ):
            if source_id != FX_SOURCE_ID or not isinstance(quote, str):
                continue
            code = quote.strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", code) or not isinstance(rate_date, str):
                continue
            try:
                parsed_date = dt.date.fromisoformat(rate_date)
                parsed_rate = float(rate)
            except (TypeError, ValueError):
                continue
            if parsed_date.isoformat() != rate_date or not math.isfinite(parsed_rate) or parsed_rate <= 0:
                continue
            if parsed_date.weekday() >= 5:
                continue
            rates[rate_date][code] = (parsed_rate, source_id)
        info["loaded_rate_count"] = sum(len(by_currency) for by_currency in rates.values())
        info["status"] = "loaded" if info["loaded_rate_count"] else "no_verified_rates"
        return rates, info
    finally:
        con.close()


def _usd_conversion(
    amount: Any,
    currency: Optional[str],
    sale_date: Optional[str],
    price_basis: Optional[str],
    fx_rates: Dict[str, Dict[str, Tuple[float, str]]],
) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[float], Optional[float], str]:
    if amount is None:
        return None, None, None, None, None, "no_price"
    if price_basis is None:
        return None, None, None, None, None, "unknown_price_basis"
    if currency is None:
        return None, None, None, None, None, "unknown_currency"
    if currency == "USD":
        return float(amount), None, "identity:USD", None, None, "identity_usd"
    if sale_date is None:
        return None, None, None, None, None, "unknown_sale_date"

    sale_day = dt.date.fromisoformat(sale_date)
    for offset in range(FX_MAX_PRIOR_DAYS + 1):
        rate_day = sale_day - dt.timedelta(days=offset)
        if rate_day.weekday() >= 5:
            continue
        day_key = rate_day.isoformat()
        day_rates = fx_rates.get(day_key, {})
        usd_rate = day_rates.get("USD")
        native_rate = (1.0, FX_SOURCE_ID) if currency == "EUR" else day_rates.get(currency)
        if usd_rate is None or native_rate is None or usd_rate[1] != native_rate[1]:
            continue
        try:
            converted = float(amount) / native_rate[0] * usd_rate[0]
        except (OverflowError, ZeroDivisionError, ValueError):
            return None, None, None, None, None, "invalid_conversion"
        if not math.isfinite(converted):
            return None, None, None, None, None, "invalid_conversion"
        return converted, day_key, usd_rate[1], native_rate[0], usd_rate[0], "converted"
    return None, None, None, None, None, "no_rate_within_7_days"


def _raw_table_ddl(columns: Sequence[Tuple[Any, ...]]) -> str:
    definitions = []
    primary_key = []
    for _, name, declared_type, not_null, _default, pk_order in columns:
        part = _quote(name)
        if declared_type:
            part += " " + declared_type
        if not_null:
            part += " NOT NULL"
        definitions.append(part)
        if pk_order:
            primary_key.append((pk_order, name))
    if primary_key:
        keys = ", ".join(_quote(name) for _, name in sorted(primary_key))
        definitions.append("PRIMARY KEY (" + keys + ")")
    return "CREATE TABLE raw_lots (" + ", ".join(definitions) + ")"


def _create_normalized_table(con: sqlite3.Connection, source_id_type: str) -> None:
    source_id_decl = source_id_type or ""
    con.execute(
        "CREATE TABLE normalized_lots ("
        "normalized_id TEXT PRIMARY KEY, "
        "source_lot_id " + source_id_decl + " NOT NULL UNIQUE, "
        "source_db_sha256 TEXT NOT NULL, "
        "house TEXT, artist_raw TEXT, artist_key TEXT, sale_name TEXT, location TEXT, "
        "title TEXT, lot_number TEXT, sale_date TEXT, sale_date_reason TEXT, "
        "currency TEXT, currency_reason TEXT, status TEXT NOT NULL, status_reason TEXT, "
        "price_basis TEXT, price_basis_reason TEXT, price_native NUMERIC, price_reason TEXT, "
        "price_usd REAL, fx_rate_date TEXT, fx_rate_source TEXT, "
        "fx_rate_native_per_eur REAL, fx_rate_usd_per_eur REAL, "
        "price_comparability TEXT NOT NULL, comparison_group TEXT, "
        "FOREIGN KEY(source_lot_id) REFERENCES raw_lots(" + _quote(SOURCE_PRIMARY_KEY) + ")"
        ")"
    )


def _normalized_id(source_lot_id: Any) -> str:
    key = "art_market.db:lots:{}".format(str(source_lot_id))
    return "auction_lot_" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _serialize_counter(counter: Counter) -> Dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _validate_output_paths(
    source_path: Path,
    output_path: Path,
    manifest_path: Path,
    fx_path: Optional[Path],
) -> None:
    if output_path in {source_path, fx_path}:
        raise ValueError("output database must be separate from source and FX databases")
    if manifest_path in {source_path, output_path, fx_path}:
        raise ValueError("manifest path must be separate from source, output, and FX databases")
    for output in (output_path, manifest_path):
        if _is_under(output, ARTRENDATA) and not _is_under(output, WORK_ROOT):
            raise ValueError("outputs inside ARTRENData must remain within the project workspace")


def normalize_auction_database(
    source_path: Path,
    output_path: Path,
    manifest_path: Path,
    fx_path: Optional[Path] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, Any]:
    """Stream lots from an immutable source into an isolated staging SQLite database."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    fx_path = Path(fx_path).resolve() if fx_path is not None else None
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not source_path.is_file():
        raise FileNotFoundError("source auction database not found: {}".format(source_path))
    _validate_output_paths(source_path, output_path, manifest_path, fx_path)

    source_fingerprint = _sha256_file(source_path)
    comparison_as_of = dt.date.today()
    source = _read_only_immutable(source_path)
    target = None
    try:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if SOURCE_TABLE not in tables:
            raise ValueError("source database does not contain the required lots table")
        columns = _table_columns(source, SOURCE_TABLE)
        column_names = [row[1] for row in columns]
        required = {SOURCE_PRIMARY_KEY, "house", "price_basis", "sale_date", "currency", "status", "price"}
        missing = sorted(required - set(column_names))
        if missing:
            raise ValueError("lots table is missing required columns: {}".format(", ".join(missing)))
        primary_key = [row[1] for row in columns if row[5]]
        if primary_key != [SOURCE_PRIMARY_KEY]:
            raise ValueError("lots table primary key must be the audited id column")
        fx_rates, fx_info = _registered_ecb_fx_rates(fx_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(output_path))
        target.execute("PRAGMA foreign_keys=ON")
        target.execute("BEGIN IMMEDIATE")
        target.execute("DROP TABLE IF EXISTS normalized_lots")
        target.execute("DROP TABLE IF EXISTS raw_lots")
        target.execute(
            "CREATE TABLE IF NOT EXISTS auction_import ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
            "source_path TEXT NOT NULL, source_table TEXT NOT NULL, source_primary_key TEXT NOT NULL, "
            "source_db_sha256 TEXT NOT NULL, imported_rows INTEGER NOT NULL, imported_at TEXT NOT NULL)"
        )
        target.execute("DELETE FROM auction_import")
        target.execute(_raw_table_ddl(columns))
        source_id_type = next(row[2] or "" for row in columns if row[1] == SOURCE_PRIMARY_KEY)
        _create_normalized_table(target, source_id_type)

        raw_insert_sql = "INSERT INTO raw_lots ({}) VALUES ({})".format(
            ", ".join(_quote(name) for name in column_names),
            ", ".join("?" for _ in column_names),
        )
        normalized_fields = (
            "normalized_id", "source_lot_id", "source_db_sha256", "house", "artist_raw", "artist_key",
            "sale_name", "location", "title", "lot_number", "sale_date", "sale_date_reason",
            "currency", "currency_reason", "status", "status_reason", "price_basis", "price_basis_reason",
            "price_native", "price_reason", "price_usd", "fx_rate_date", "fx_rate_source",
            "fx_rate_native_per_eur", "fx_rate_usd_per_eur", "price_comparability", "comparison_group",
        )
        normalized_insert_sql = "INSERT INTO normalized_lots ({}) VALUES ({})".format(
            ", ".join(_quote(name) for name in normalized_fields),
            ", ".join("?" for _ in normalized_fields),
        )

        stats: Dict[str, Any] = {
            "source_rows": 0,
            "date_valid": 0,
            "date_future": 0,
            "date_unknown_by_reason": Counter(),
            "currency_counts": Counter(),
            "currency_unknown_by_reason": Counter(),
            "status_counts": Counter(),
            "status_raw_counts": Counter(),
            "status_unknown_by_reason": Counter(),
            "price_basis_counts": Counter(),
            "price_basis_unknown_by_reason": Counter(),
            "price_counts": Counter(),
            "fx_outcome_counts": Counter(),
            "comparability_counts": Counter(),
        }
        select_sql = "SELECT {} FROM {} ORDER BY {}".format(
            ", ".join(_quote(name) for name in column_names),
            _quote(SOURCE_TABLE),
            _quote(SOURCE_PRIMARY_KEY),
        )
        cursor = source.execute(select_sql)
        while True:
            raw_batch = cursor.fetchmany(batch_size)
            if not raw_batch:
                break
            normalized_batch = []
            for raw_row in raw_batch:
                values = dict(zip(column_names, raw_row))
                source_lot_id = values[SOURCE_PRIMARY_KEY]
                sale_date, sale_date_reason = _normalize_date(values.get("sale_date"))
                currency, currency_reason = _normalize_currency(values.get("currency"))
                status, status_reason = _normalize_status(values.get("status"))
                price_basis, basis_reason = _normalize_basis(values.get("price_basis"))
                price, price_reason = _normalize_price(values.get("price"))
                price_usd, rate_date, rate_source, native_rate, usd_rate, fx_outcome = _usd_conversion(
                    price, currency, sale_date, price_basis, fx_rates
                )
                sale_date_future = (
                    sale_date is not None and dt.date.fromisoformat(sale_date) > comparison_as_of
                )
                valid_fx = (
                    currency == "USD" and fx_outcome == "identity_usd" and rate_source == "identity:USD"
                ) or (
                    fx_outcome == "converted" and rate_date is not None and rate_source == FX_SOURCE_ID
                )
                if status == "unknown":
                    comparability = "non_comparable_unknown_status"
                    comparison_group = None
                elif status != "sold":
                    comparability = "non_comparable_not_sold"
                    comparison_group = None
                elif sale_date is None:
                    comparability = "non_comparable_unknown_date"
                    comparison_group = None
                elif sale_date_future:
                    comparability = "non_comparable_future_date"
                    comparison_group = None
                elif price is None:
                    comparability = "non_comparable_missing_price"
                    comparison_group = None
                elif float(price) <= 0:
                    comparability = "non_comparable_nonpositive_price"
                    comparison_group = None
                elif price_basis is None:
                    comparability = "non_comparable_unknown_basis"
                    comparison_group = None
                elif not valid_fx:
                    comparability = "non_comparable_missing_fx"
                    comparison_group = None
                else:
                    comparability = "comparable_within_basis"
                    comparison_group = price_basis + ":USD"

                stats["source_rows"] += 1
                if sale_date is None:
                    stats["date_unknown_by_reason"][sale_date_reason] += 1
                else:
                    stats["date_valid"] += 1
                    if sale_date_future:
                        stats["date_future"] += 1
                if currency is None:
                    stats["currency_unknown_by_reason"][currency_reason] += 1
                    stats["currency_counts"]["<UNKNOWN>"] += 1
                else:
                    stats["currency_counts"][currency] += 1
                stats["status_counts"][status] += 1
                status_raw = values.get("status")
                status_raw_label = "<NULL>" if status_raw is None else (
                    "<BLANK>" if isinstance(status_raw, str) and not status_raw.strip() else str(status_raw)
                )
                stats["status_raw_counts"][status_raw_label] += 1
                if status_reason:
                    stats["status_unknown_by_reason"][status_reason] += 1
                if price_basis is None:
                    stats["price_basis_counts"]["<UNKNOWN>"] += 1
                    stats["price_basis_unknown_by_reason"][basis_reason] += 1
                else:
                    stats["price_basis_counts"][price_basis] += 1
                stats["price_counts"]["present" if price is not None else price_reason] += 1
                stats["fx_outcome_counts"][fx_outcome] += 1
                stats["comparability_counts"][comparability] += 1

                normalized_batch.append((
                    _normalized_id(source_lot_id), source_lot_id, source_fingerprint,
                    values.get("house"), values.get("artist_raw"), values.get("artist_key"),
                    values.get("sale_name"), values.get("location"), values.get("title"),
                    values.get("lot_number"), sale_date, sale_date_reason, currency, currency_reason,
                    status, status_reason, price_basis, basis_reason, price, price_reason,
                    price_usd, rate_date, rate_source, native_rate, usd_rate, comparability, comparison_group,
                ))
            target.executemany(raw_insert_sql, raw_batch)
            target.executemany(normalized_insert_sql, normalized_batch)

        if _sha256_file(source_path) != source_fingerprint:
            raise RuntimeError("source auction database changed during normalization")
        target.execute(
            "INSERT INTO auction_import VALUES(1, ?, ?, ?, ?, ?, ?)",
            (str(source_path), SOURCE_TABLE, SOURCE_PRIMARY_KEY, source_fingerprint,
             stats["source_rows"], iso_now()),
        )
        target.commit()
    except Exception:
        if target is not None:
            target.rollback()
        raise
    finally:
        source.close()
        if target is not None:
            target.close()

    output = {
        "manifest_version": 1,
        "generated_at": iso_now(),
        "comparison_as_of_date": comparison_as_of.isoformat(),
        "source": {
            "path": str(source_path),
            "table": SOURCE_TABLE,
            "primary_key": SOURCE_PRIMARY_KEY,
            "sha256": source_fingerprint,
            "read_mode": "read-only immutable",
            "raw_table": "raw_lots",
        },
        "output_database": str(output_path),
        "schema": {
            "normalized_table": "normalized_lots",
            "import_metadata_table": "auction_import",
            "raw_values": "raw_lots mirrors every source lots column and primary key value",
            "normalized_id": "SHA-256 of stable logical source/table/origin primary key",
            "artist_identity": "artist_raw and original artist_key retained; no name matching or merging",
            "price_basis": "only explicit hammer and hammer_plus_premium are recognized; unknown stays NULL",
            "price_comparability": "comparable_within_basis requires sold status, a valid nonfuture sale date, positive price, known explicit basis, and valid USD conversion; comparison_group is separate per basis",
            "fx_conversion": "ECB EUR-base rates from registered reference source ecb_fx; exact rate date or prior weekday within 7 calendar days; same rate date for native currency and USD; active FX database is read-only and honors WAL",
        },
        "fx": dict(fx_info, max_prior_calendar_days=FX_MAX_PRIOR_DAYS),
        "quality_counts": {
            "source_rows": stats["source_rows"],
            "raw_rows": stats["source_rows"],
            "normalized_rows": stats["source_rows"],
            "sale_dates": {
                "valid": stats["date_valid"],
                "future": stats["date_future"],
                "unknown_by_reason": _serialize_counter(stats["date_unknown_by_reason"]),
            },
            "currencies": {
                "normalized_code_counts": _serialize_counter(stats["currency_counts"]),
                "unknown_by_reason": _serialize_counter(stats["currency_unknown_by_reason"]),
            },
            "statuses": {
                "normalized_counts": _serialize_counter(stats["status_counts"]),
                "raw_value_counts": _serialize_counter(stats["status_raw_counts"]),
                "unknown_by_reason": _serialize_counter(stats["status_unknown_by_reason"]),
            },
            "price_bases": {
                "normalized_counts": _serialize_counter(stats["price_basis_counts"]),
                "unknown_by_reason": _serialize_counter(stats["price_basis_unknown_by_reason"]),
            },
            "prices": _serialize_counter(stats["price_counts"]),
            "fx_outcomes": _serialize_counter(stats["fx_outcome_counts"]),
            "comparability": _serialize_counter(stats["comparability_counts"]),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(temporary_manifest), str(manifest_path))
    return output


def _default_paths() -> Tuple[Path, Path, Path, Path]:
    scratch = os.environ.get("ARTREND_SCRATCH")
    base = WORK_ROOT / "work" / "dev" / scratch if scratch else WORK_ROOT
    return (
        ARTRENDATA / "data" / "art_market.db",
        base / "db" / "auction_normalized.sqlite",
        base / "outputs" / "auction_normalize_manifest.json",
        WORK_ROOT / "db" / "artrend_magazine.sqlite",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    source_default, output_default, manifest_default, fx_default = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=source_default,
                        help="legacy art_market.db input (read-only immutable)")
    parser.add_argument("--output-db", type=Path, default=output_default,
                        help="separate auction staging SQLite output")
    parser.add_argument("--manifest", type=Path, default=manifest_default,
                        help="machine-readable JSON quality manifest output")
    parser.add_argument("--fx-db", type=Path, default=fx_default,
                        help="local database containing registered ecb_fx rates")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="streaming lot batch size (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        result = normalize_auction_database(
            args.source_db, args.output_db, args.manifest, args.fx_db, args.batch_size
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print("market normalization failed: {}".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
