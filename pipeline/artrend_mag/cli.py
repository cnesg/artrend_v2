"""Command line entry point.

  python -m artrend_mag.cli init
  python -m artrend_mag.cli list-sources
  python -m artrend_mag.cli collect --mode initial      [--sources a,b] [--region KR]
  python -m artrend_mag.cli collect --mode incremental  [--sources a,b] [--region KR]
  python -m artrend_mag.cli import-legacy
  python -m artrend_mag.cli derive
  python -m artrend_mag.cli validate
  python -m artrend_mag.cli export
  python -m artrend_mag.cli vault  [--asof YYYY-MM-DD] [--days 7] [--out DIR]
  python -m artrend_mag.cli web    [--asof YYYY-MM-DD] [--days 7] [--out DIR]   (JSON for the web front)
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import warnings

from . import db
from .config import CODE_VERSION, DB_PATH, SCHEMA_VERSION, WORK_ROOT, iso_now, configure_local_temporary_files

warnings.filterwarnings("ignore", message=".*OpenSSL.*")


def cmd_init(_):
    con = db.connect()
    db.init_schema(con)
    from . import runner

    runner.register_all(con, runner.discover())
    print(f"initialised {DB_PATH}")


def cmd_list(_):
    from . import runner

    for sid_, (mod, row) in sorted(runner.discover().items()):
        print(f"{sid_:32s} {row.get('region_scope',''):9s} {row.get('access_method',''):8s} {row.get('priority',''):3s} {row['name']}  [{mod.__name__.split('.')[-1]}]")


def cmd_collect(a):
    from . import runner

    con = db.connect()
    db.init_schema(con)
    reg = runner.discover()
    runner.register_all(con, reg)
    wanted = [s for s in (a.sources.split(",") if a.sources else reg) if s]
    if a.region:
        wanted = [s for s in wanted if reg[s][1].get("region_scope") == a.region]
    missing = [s for s in wanted if s not in reg]
    if missing:
        sys.exit(f"unknown source ids: {missing}")
    run_id = runner.new_run_id(a.mode)
    started = iso_now()
    results = []
    for s in wanted:
        mod, meta = reg[s]
        if meta.get("disabled"):
            results.append({"source_id": s, "state": "skipped", "error": meta.get("disabled")})
            continue
        print(f"[{iso_now()}] {s} ...", flush=True)
        res = runner.run_source(con, run_id, a.mode, s, mod, meta)
        print(f"   -> {res['state']} parsed={res.get('parsed',0)} ins={res.get('inserted',0)} upd={res.get('updated',0)}"
              f" same={res.get('unchanged',0)} req={res.get('http_requests',0)} {(res.get('error') or '')[:160]}", flush=True)
        results.append(res)
    manifest = {
        "run_id": run_id, "mode": a.mode, "started_at": started, "finished_at": iso_now(),
        "code_version": CODE_VERSION, "schema_version": SCHEMA_VERSION, "python": platform.python_version(),
        "inputs": "live HTTP sources listed in results", "outputs": {"db": str(DB_PATH.relative_to(WORK_ROOT)), "raw": f"raw/<source_id>/{run_id}/"},
        "results": results,
        "counts": {k: con.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0] for k in
                   ("sources", "entities", "aliases", "events", "event_participants", "articles", "works", "evidence", "relationships", "review_queue")},
    }
    print(runner.write_manifest(run_id, manifest))


IDENTITY_SOURCES = ("wikidata_ids", "wikimedia_pageviews")  # depend on events collected first


def cmd_update(a):
    """collect (all event/article sources) -> derive -> identity/attention APIs -> derive -> validate -> export."""
    from . import runner

    if a.translate:
        from . import translation
        availability = translation.model_availability()
        if not availability["available"]:
            raise SystemExit("Local Korean model unavailable: " + str(availability.get("reason")))
    reg = runner.discover()
    first = [s for s in reg if s not in IDENTITY_SOURCES]
    if a.region:
        first = [s for s in first if reg[s][1].get("region_scope") == a.region]
    cmd_collect(argparse.Namespace(mode=a.mode, sources=",".join(first), region=None))
    cmd_derive(a)
    cmd_collect(argparse.Namespace(mode=a.mode, sources=",".join(IDENTITY_SOURCES), region=None))
    cmd_derive(a)
    try:
        if a.translate:
            translation.main(["--batch-size", "128"])
        cmd_validate(a)
    finally:
        cmd_export(a)


def cmd_import_legacy(_):
    from . import legacy_import

    legacy_import.main()


def cmd_derive(_):
    from . import derive

    derive.main()


def cmd_validate(_):
    from . import validate

    validate.main()


def cmd_export(_):
    from . import export_workbook

    export_workbook.main()


def cmd_vault(a):
    from . import obsidian_vault

    obsidian_vault.main(a.asof, a.days, a.out)


def cmd_web(a):
    from . import web_export
    web_export.main(a.asof, a.days, a.out)


def cmd_brief(a):
    import datetime as dt
    import json

    from . import editorial

    asof = dt.date.fromisoformat(a.asof) if a.asof else dt.date.today()
    if a.check_names:
        print(json.dumps(editorial.check_names(asof), ensure_ascii=False))
    else:
        print(json.dumps(editorial.build(asof, fetch=not a.offline), ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="artrend_mag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(f=cmd_init)
    sub.add_parser("list-sources").set_defaults(f=cmd_list)
    c = sub.add_parser("collect")
    c.add_argument("--mode", choices=["initial", "incremental"], required=True)
    c.add_argument("--sources", default="")
    c.add_argument("--region", choices=["KR", "JP", "AMERICAS", "EUROPE", "GLOBAL", "OTHER"])
    c.set_defaults(f=cmd_collect)
    u = sub.add_parser("update")
    u.add_argument("--mode", choices=["initial", "incremental"], default="incremental")
    u.add_argument("--region", choices=["KR", "JP", "AMERICAS", "EUROPE", "GLOBAL", "OTHER"])
    u.add_argument("--translate", action="store_true", help="translate new/changed metadata with installed local Korean models")
    u.set_defaults(f=cmd_update)
    sub.add_parser("import-legacy").set_defaults(f=cmd_import_legacy)
    sub.add_parser("derive").set_defaults(f=cmd_derive)
    sub.add_parser("validate").set_defaults(f=cmd_validate)
    sub.add_parser("export").set_defaults(f=cmd_export)
    v = sub.add_parser("vault", help="build the Obsidian vault view (outputs/ARTREND_Obsidian_Vault)")
    v.add_argument("--asof", help="daily-insight date (default: today)")
    v.add_argument("--days", type=int, default=7, help="number of daily-insight dates ending at --asof")
    v.add_argument("--out")
    v.set_defaults(f=cmd_vault)
    w = sub.add_parser("web", help="JSON feed for the web front (outputs/web_data)")
    w.add_argument("--asof", help="last date (default: today)")
    w.add_argument("--days", type=int, default=7)
    w.add_argument("--out")
    w.set_defaults(f=cmd_web)
    b = sub.add_parser("brief", help="editorial packets: read top/award articles, score importance, check Rookie rules")
    b.add_argument("--asof", help="snapshot date (default: today)")
    b.add_argument("--offline", action="store_true", help="no article reading or name search")
    b.add_argument("--check-names", action="store_true", help="after notes_<D>.json: Rookie checks for confirmed winners")
    b.set_defaults(f=cmd_brief)
    a = ap.parse_args(argv)
    configure_local_temporary_files()
    a.f(a)


if __name__ == "__main__":
    main()
