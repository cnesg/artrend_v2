import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from artrend_mag.market_normalize import (
    ARTRENDATA,
    WORK_ROOT,
    _normalize_basis,
    _normalize_currency,
    _normalize_date,
    _normalize_status,
    _validate_output_paths,
    _usd_conversion,
    normalize_auction_database,
)


class MarketNormalizeTests(unittest.TestCase):
    def test_date_currency_status_and_basis_edges(self):
        self.assertEqual(_normalize_date("1970-01-01"), (None, "placeholder_1970_01_01"))
        self.assertEqual(_normalize_date("2024-02-30"), (None, "invalid_calendar_date"))
        self.assertEqual(_normalize_date("2024-02-29"), ("2024-02-29", None))
        self.assertEqual(_normalize_date(None), (None, "missing_date"))
        self.assertEqual(_normalize_currency(" rmb "), ("CNY", None))
        self.assertEqual(_normalize_currency(""), (None, "missing_currency"))
        self.assertEqual(_normalize_currency("US"), (None, "invalid_currency_code"))
        self.assertEqual(_normalize_status("Bought In"), ("bought_in", None))
        self.assertEqual(_normalize_status("ReturnToOwner"), ("withdrawn", None))
        self.assertEqual(_normalize_status("CS"), ("unknown", "unmapped_status"))
        self.assertEqual(_normalize_basis("hammer"), ("hammer", None))
        self.assertEqual(_normalize_basis("hammer_plus_premium"), ("hammer_plus_premium", None))
        self.assertEqual(_normalize_basis("premium"), (None, "unrecognized_basis"))

    def test_fx_requires_same_verified_day_and_is_limited_to_seven_days(self):
        split_day_rates = {
            "2024-01-02": {"CNY": (7.0, "ecb_fx")},
            "2024-01-03": {"USD": (1.4, "ecb_fx")},
        }
        self.assertEqual(
            _usd_conversion(700, "CNY", "2024-01-03", "hammer", split_day_rates)[-1],
            "no_rate_within_7_days",
        )
        old_rates = {
            "2024-01-02": {
                "CNY": (7.0, "ecb_fx"),
                "USD": (1.4, "ecb_fx"),
            }
        }
        self.assertEqual(
            _usd_conversion(700, "CNY", "2024-01-10", "hammer", old_rates)[-1],
            "no_rate_within_7_days",
        )
        converted = _usd_conversion(700, "CNY", "2024-01-03", "hammer", old_rates)
        self.assertEqual(converted[0], 140.0)
        self.assertEqual(converted[1:3], ("2024-01-02", "ecb_fx"))

    def test_workspace_nested_output_allowed_original_tree_outside_workspace_rejected(self):
        source = Path("/tmp/synthetic-art-market.db").resolve()
        fx = Path("/tmp/synthetic-project.sqlite").resolve()
        _validate_output_paths(
            source,
            WORK_ROOT / "db" / "auction_normalized.sqlite",
            WORK_ROOT / "outputs" / "auction_normalize_manifest.json",
            fx,
        )
        with self.assertRaisesRegex(ValueError, "within the project workspace"):
            _validate_output_paths(
                source,
                ARTRENDATA / "data" / "not-allowed.sqlite",
                WORK_ROOT / "outputs" / "manifest.json",
                fx,
            )

    @staticmethod
    def _make_source(path):
        con = sqlite3.connect(str(path))
        con.execute(
            "CREATE TABLE lots ("
            "id INTEGER PRIMARY KEY, house TEXT, price_basis TEXT, sale_date TEXT, sale_year INTEGER, "
            "sale_name TEXT, location TEXT, currency TEXT, artist_raw TEXT, artist_key TEXT, title TEXT, "
            "lot_number TEXT, status TEXT, est_low REAL, est_high REAL, price REAL, amount_usd REAL, "
            "amount_usd_real2024 REAL, lot_url TEXT, extra_raw TEXT)"
        )
        rows = [
            (1, "House A", "hammer", "2024-01-03", 2024, "Sale", "Paris", "CNY", "Raw Artist", "artist-key-1",
             "Work A", "1", "SOLD", 100.0, 200.0, 700.0, 99.0, 80.0, "https://example.test/1", "keep raw"),
            (2, "House B", "hammer_plus_premium", "1970-01-01", 1970, "Old Sale", "CN", "CNY", "Artist B", None,
             "Work B", "2", "BI", None, None, 25.0, None, None, None, "placeholder date"),
            (3, "House C", "unknown basis", "2024-02-30", None, "Sale C", "", "", None, None,
             "Work C", "3", "SOLD", None, None, None, None, None, None, "must not become zero"),
            (4, "House D", "hammer", "2024-01-15", 2024, "Sale D", "London", "CNY", "Same Name", "artist-key-2",
             "Work D", "4", "UNSOLD", None, None, 50.0, None, None, None, "too-old FX"),
            (5, "House E", "hammer", "2024-01-03", 2024, "Sale E", "New York", "USD", "Same Name", "artist-key-3",
             "Work E", "5", "Withdrawn", None, None, 0.0, None, None, None, "explicit zero"),
            (6, "House F", "hammer_plus_premium", "2024-01-03", 2024, "Sale F", "New York", "USD", "Same Name",
             "artist-key-4", "Work F", "6", "SOLD", None, None, 100.0, None, None, None, "premium basis"),
            (7, "House G", "hammer", "2024-01-03", 2024, "Sale G", "New York", "USD", "Artist G", None,
             "Work G", "7", "CS", None, None, 100.0, None, None, None, "unknown status"),
            (8, "House H", "hammer", None, None, "Sale H", "New York", "USD", "Artist H", None,
             "Work H", "8", "SOLD", None, None, 100.0, None, None, None, "unknown date"),
            (9, "House I", "hammer", (dt.date.today() + dt.timedelta(days=1)).isoformat(), None,
             "Sale I", "New York", "USD", "Artist I", None, "Work I", "9", "SOLD", None, None,
             100.0, None, None, None, "future date"),
            (10, "House J", "hammer", "2024-01-03", 2024, "Sale J", "New York", "USD", "Artist J", None,
             "Work J", "10", "SOLD", None, None, 0.0, None, None, None, "sold at zero"),
            (11, "House K", "unknown basis", "2024-01-03", 2024, "Sale K", "New York", "USD", "Artist K", None,
             "Work K", "11", "SOLD", None, None, 100.0, None, None, None, "unknown basis"),
            (12, "House L", "hammer", "2024-01-15", 2024, "Sale L", "Paris", "CNY", "Artist L", None,
             "Work L", "12", "SOLD", None, None, 100.0, None, None, None, "missing FX"),
        ]
        con.executemany("INSERT INTO lots VALUES (" + ",".join("?" for _ in rows[0]) + ")", rows)
        con.commit()
        con.close()

    @staticmethod
    def _make_fx_database(path):
        con = sqlite3.connect(str(path))
        con.execute("CREATE TABLE sources (source_id TEXT PRIMARY KEY, source_kind TEXT NOT NULL)")
        con.execute("INSERT INTO sources VALUES ('ecb_fx', 'reference')")
        con.execute("INSERT INTO sources VALUES ('unverified', 'reference')")
        con.execute(
            "CREATE TABLE fx_rates (rate_date TEXT, base TEXT, quote TEXT, rate REAL, source_id TEXT)"
        )
        con.executemany(
            "INSERT INTO fx_rates VALUES (?, 'EUR', ?, ?, ?)",
            [
                ("2024-01-02", "CNY", 7.0, "ecb_fx"),
                ("2024-01-02", "USD", 1.4, "ecb_fx"),
                ("2024-01-03", "CNY", 9.0, "unverified"),
            ],
        )
        con.commit()
        con.close()

    def test_streamed_import_preserves_raw_data_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "art_market.db"
            output_path = root / "auction_normalized.sqlite"
            manifest_path = root / "outputs" / "manifest.json"
            fx_path = root / "project.sqlite"
            self._make_source(source_path)
            self._make_fx_database(fx_path)
            # Keep a WAL writer open: immutable reads ignore these committed-but-uncheckpointed rates.
            fx_writer = sqlite3.connect(str(fx_path))
            fx_writer.execute("PRAGMA journal_mode=WAL")
            fx_writer.executemany(
                "INSERT INTO fx_rates VALUES (?, 'EUR', ?, ?, 'ecb_fx')",
                [("2024-01-03", "CNY", 8.0), ("2024-01-03", "USD", 1.5)],
            )
            fx_writer.commit()
            source_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

            try:
                first = normalize_auction_database(source_path, output_path, manifest_path, fx_path, batch_size=2)
            except Exception:
                fx_writer.close()
                raise
            source_after = hashlib.sha256(source_path.read_bytes()).hexdigest()
            self.assertEqual(source_before, source_after)
            self.assertEqual(first["quality_counts"]["source_rows"], 12)
            self.assertEqual(first["quality_counts"]["raw_rows"], 12)
            self.assertEqual(first["quality_counts"]["normalized_rows"], 12)
            self.assertEqual(first["quality_counts"]["sale_dates"]["unknown_by_reason"]["placeholder_1970_01_01"], 1)
            self.assertEqual(first["quality_counts"]["sale_dates"]["unknown_by_reason"]["invalid_calendar_date"], 1)
            self.assertEqual(first["quality_counts"]["fx_outcomes"]["converted"], 1)
            self.assertEqual(first["quality_counts"]["fx_outcomes"]["no_rate_within_7_days"], 2)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["source"]["sha256"], source_before)

            con = sqlite3.connect(str(output_path))
            try:
                raw = con.execute("SELECT extra_raw, price FROM raw_lots WHERE id=1").fetchone()
                self.assertEqual(raw, ("keep raw", 700.0))
                valid = con.execute(
                    "SELECT source_lot_id, sale_date, currency, status, price_basis, price_native, "
                    "price_usd, fx_rate_date, fx_rate_source, comparison_group, artist_key "
                    "FROM normalized_lots WHERE source_lot_id=1"
                ).fetchone()
                self.assertEqual(valid, (1, "2024-01-03", "CNY", "sold", "hammer", 700.0,
                                         131.25, "2024-01-03", "ecb_fx", "hammer:USD", "artist-key-1"))
                placeholder = con.execute(
                    "SELECT sale_date, sale_date_reason, price_usd, price_basis, comparison_group "
                    "FROM normalized_lots WHERE source_lot_id=2"
                ).fetchone()
                self.assertEqual(placeholder, (None, "placeholder_1970_01_01", None,
                                                "hammer_plus_premium", None))
                missing = con.execute(
                    "SELECT price_native, price_usd, price_reason, price_comparability "
                    "FROM normalized_lots WHERE source_lot_id=3"
                ).fetchone()
                self.assertEqual(missing, (None, None, "missing_price", "non_comparable_unknown_date"))
                zero = con.execute(
                    "SELECT price_native, price_usd, fx_rate_source, price_comparability, comparison_group "
                    "FROM normalized_lots WHERE source_lot_id=10"
                ).fetchone()
                self.assertEqual(zero, (0.0, 0.0, "identity:USD", "non_comparable_nonpositive_price", None))
                exclusions = con.execute(
                    "SELECT source_lot_id, price_comparability, comparison_group FROM normalized_lots "
                    "WHERE source_lot_id IN (4, 5, 7, 8, 9, 11, 12) ORDER BY source_lot_id"
                ).fetchall()
                self.assertEqual(exclusions, [
                    (4, "non_comparable_not_sold", None),
                    (5, "non_comparable_not_sold", None),
                    (7, "non_comparable_unknown_status", None),
                    (8, "non_comparable_unknown_date", None),
                    (9, "non_comparable_future_date", None),
                    (11, "non_comparable_unknown_basis", None),
                    (12, "non_comparable_missing_fx", None),
                ])
                premium_group = con.execute(
                    "SELECT price_usd, comparison_group FROM normalized_lots WHERE source_lot_id=6"
                ).fetchone()
                self.assertEqual(premium_group, (100.0, "hammer_plus_premium:USD"))
                imported = con.execute("SELECT imported_rows, source_db_sha256 FROM auction_import").fetchone()
                self.assertEqual(imported, (12, source_before))
            finally:
                con.close()

            con = sqlite3.connect(str(output_path))
            try:
                first_ids = [row[0] for row in con.execute(
                    "SELECT normalized_id FROM normalized_lots ORDER BY source_lot_id"
                )]
            finally:
                con.close()
            second = normalize_auction_database(source_path, output_path, manifest_path, fx_path, batch_size=3)
            con = sqlite3.connect(str(output_path))
            try:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM normalized_lots").fetchone()[0], 12)
                second_ids = [row[0] for row in con.execute(
                    "SELECT normalized_id FROM normalized_lots ORDER BY source_lot_id"
                )]
            finally:
                con.close()
            self.assertEqual(first_ids, second_ids)
            self.assertEqual(second["source"]["sha256"], source_before)
            fx_writer.close()


if __name__ == "__main__":
    unittest.main()
