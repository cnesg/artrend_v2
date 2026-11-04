"""Source discovery and per-source run bookkeeping.

Each module in artrend_mag/sources/ exposes:
    SOURCES: list[dict]   registry rows (source_id, name, ... see db.SOURCE_FIELDS)
    collect(ctx)          collects ONE source (ctx.source_id) in ctx.mode ('initial' | 'incremental')
A module may serve several source_ids (e.g. one parser for several galleries).
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import traceback
from dataclasses import dataclass, field

from . import db
from .config import RUNS_ROOT, iso_now, now_kst
from .http import Blocked, Fetcher, FetchError


IMPORT_ERRORS: dict[str, str] = {}


def discover() -> dict[str, tuple[object, dict]]:
    """Import every source module. A module that fails to import is reported in IMPORT_ERRORS
    (and on stderr) instead of stopping collection for every other source."""
    import sys

    from . import sources as pkg

    found: dict[str, tuple[object, dict]] = {}
    IMPORT_ERRORS.clear()
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{pkg.__name__}.{m.name}")
        except Exception as exc:  # broken module: its sources are unavailable, others still run
            IMPORT_ERRORS[m.name] = f"{type(exc).__name__}: {exc}"
            print(f"[source import error] {m.name}: {IMPORT_ERRORS[m.name]}", file=sys.stderr)
            continue
        for row in getattr(mod, "SOURCES", []):
            if row["source_id"] in found:
                raise ValueError(f"duplicate source_id {row['source_id']}")
            found[row["source_id"]] = (mod, row)
    return found


@dataclass
class RunContext:
    con: object
    run_id: str
    source_id: str
    mode: str
    meta: dict
    fetcher: Fetcher
    stats: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    parser_version: str = "1"

    def fetch(self, url, **kw):
        return self.fetcher.get(url, **kw)

    def evidence(self, resp, locator=None, excerpt=None) -> str:
        return db.add_evidence(self.con, source_id=self.source_id, url=resp.url, fetched_at=resp.fetched_at,
                               http_status=resp.status, raw_path=resp.raw_path, raw_sha256=resp.sha256,
                               locator=locator, excerpt=excerpt, parser_version=self.parser_version)

    def note(self, msg: str):
        self.notes.append(msg)

    def count(self, key: str, n: int = 1):
        self.stats[key] = self.stats.get(key, 0) + n


def register_all(con, registry) -> None:
    for sid_, (_, row) in registry.items():
        meta = {k: v for k, v in row.items() if k != "source_id" and k in db.SOURCE_FIELDS + db.STATUS_FIELDS}
        db.upsert_source(con, sid_, **meta)
    con.commit()


def run_source(con, run_id: str, mode: str, source_id: str, mod, meta: dict) -> dict:
    stats: dict = {}
    store_raw = meta.get("text_storage_policy", "metadata_only") == "raw_internal"
    fetcher = Fetcher(source_id, run_id, store_raw, stats, max_requests=meta.get("max_requests", 400),
                      api_policy_url=meta.get("api_policy_url"), extra_headers=meta.get("extra_headers"),
                      min_interval=meta.get("min_interval"))
    ctx = RunContext(con, run_id, source_id, mode, meta, fetcher, stats, parser_version=getattr(mod, "PARSER_VERSION", "1"))
    started = iso_now()
    con.execute("INSERT OR REPLACE INTO crawl_runs(run_id,source_id,mode,started_at,state,parser_version) VALUES(?,?,?,?,?,?)",
                (run_id, source_id, mode, started, "running", ctx.parser_version))
    con.commit()
    state, error = "success", None
    try:
        mod.collect(ctx)
        if stats.get("parsed", 0) == 0:
            state = "partial" if stats.get("fetched", 0) else "no_records"
        elif stats.get("inserted", 0) == 0 and stats.get("updated", 0) == 0:
            state = "no_change"
        con.commit()
    except Blocked as b:
        con.commit()  # keep anything parsed before the block
        state, error = "blocked", f"{b.kind} status={b.status} url={b.url} {b.detail}"
        kind = {"robots_disallow": "blocked_permission", "login_redirect": "blocked_credentials",
                "credentials_missing": "blocked_credentials"}.get(b.kind, "blocked_access")
        db.set_source_status(con, source_id, operational_state=kind if not stats.get("parsed") else "partial",
                             st_live_response="blocked" if b.status else "not_requested(robots)",
                             robots_status=fetcher._robots_state.get(_host(b.url), "unknown"))
    except FetchError as e:
        con.commit()
        state, error = ("partial" if stats.get("parsed") else "error"), str(e)
    except Exception as e:  # parser bug: record, never crash the whole run
        con.rollback()
        state, error = "error", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}"
    finished = iso_now()
    con.execute(
        "UPDATE crawl_runs SET finished_at=?, state=?, http_requests=?, http_not_modified=?, http_errors=?, last_http_status=?,"
        " records_fetched=?, records_parsed=?, records_inserted=?, records_updated=?, records_unchanged=?, error=? WHERE run_id=? AND source_id=?",
        (finished, state, stats.get("http_requests", 0), stats.get("http_not_modified", 0), stats.get("http_errors", 0),
         stats.get("last_http_status"), stats.get("fetched", 0), stats.get("parsed", 0), stats.get("inserted", 0),
         stats.get("updated", 0), stats.get("unchanged", 0), ("; ".join(ctx.notes) + ("\n" + error if error else "")) or None,
         run_id, source_id),
    )
    if state in ("success", "no_change", "partial"):
        host_state = fetcher._robots_state.get(_host(meta.get("entry_url") or meta.get("base_url") or ""), None)
        upd = dict(st_live_response="ok", operational_state="active" if state != "partial" else "partial")
        if stats.get("parsed"):
            upd["st_fields_extracted"] = "ok"
        if host_state:
            upd["robots_status"] = host_state
        db.set_source_status(con, source_id, **upd)
    elif state == "error":
        db.set_source_status(con, source_id, operational_state="error")
    elif state == "no_records":
        db.set_source_status(con, source_id, operational_state="error", st_fields_extracted="failed(0 records)")
    con.commit()
    return {"source_id": source_id, "state": state, "error": error, "notes": ctx.notes, **stats}


def _host(url: str) -> str:
    import urllib.parse

    return urllib.parse.urlsplit(url).netloc


def new_run_id(mode: str) -> str:
    return f"{now_kst().strftime('%Y%m%dT%H%M%S')}_{mode}"


def write_manifest(run_id: str, payload: dict) -> str:
    d = RUNS_ROOT / run_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "manifest.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return str(p)
