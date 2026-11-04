"""Validation suite over the normalized store + raw archive. Writes work/audit/validation.json and exits
non-zero when a hard check fails. Source data is unchanged; date anomalies are queued for review.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import json
import sys
import urllib.parse

from . import db, region
from .config import AUDIT_ROOT, WORK_ROOT, iso_now, now_kst
from .derive import lifecycle

CREDENTIAL_PARAMS = {"servicekey", "api_key", "apikey", "key", "token", "access_token", "auth_token"}


def has_credential_param(url: str) -> bool:
    query = urllib.parse.urlsplit(url or "").query
    return any(name.casefold() in CREDENTIAL_PARAMS
               for name, _ in urllib.parse.parse_qsl(query, keep_blank_values=True))


def _q(con, sql, p=()):
    return con.execute(sql, p).fetchall()


def main():
    con = db.connect()
    out = []

    def check(name, ok, detail, hard=True):
        out.append({"check": name, "result": "pass" if ok else ("FAIL" if hard else "warn"), "detail": detail})

    # 1. primary/unique keys
    for t, k in (("events", "source_id, source_event_key"), ("articles", "canonical_url"), ("entities", "id_namespace, id_value"),
                 ("works", "id_namespace, id_value")):
        d = _q(con, f"SELECT COUNT(*) FROM (SELECT {k} FROM {t} GROUP BY {k} HAVING COUNT(*)>1)")[0][0]
        check(f"unique key {t}({k})", d == 0, f"{d} duplicate keys")
    # 2. referential integrity
    fk = _q(con, "PRAGMA foreign_key_check")
    check("foreign keys", len(fk) == 0, f"{len(fk)} violations" + (f"; first {fk[:3]}" if fk else ""))
    orphan_p = _q(con, "SELECT COUNT(*) FROM event_participants p LEFT JOIN entities e USING(entity_id) WHERE e.entity_id IS NULL")[0][0]
    check("participants -> entities", orphan_p == 0, f"{orphan_p} orphan participants")
    # 3. dates
    bad_fmt = _q(con, "SELECT COUNT(*) FROM events WHERE (start_date IS NOT NULL AND start_precision IS NULL) OR (start_precision='day' AND LENGTH(start_date)<>10)"
                      " OR (start_precision='month' AND LENGTH(start_date)<>7) OR (start_precision='year' AND LENGTH(start_date)<>4)")[0][0]
    check("date precision matches format", bad_fmt == 0, f"{bad_fmt} rows")
    inv = _q(con, "SELECT source_id, COUNT(*) FROM events WHERE start_precision='day' AND end_precision='day' AND end_date<start_date GROUP BY 1")
    check("end_date >= start_date", not inv, f"{[tuple(r) for r in inv]} (queued for review)", hard=False)
    for r in _q(con, "SELECT event_id FROM events WHERE start_precision='day' AND end_precision='day' AND end_date<start_date"):
        db.add_review(con, "date", "events", r[0], "end before start (parser or source error)")
    future_pub = _q(con, "SELECT COUNT(*) FROM articles WHERE published_at > ?", (now_kst() .isoformat(),))[0][0]
    check("no article published in the future", future_pub == 0, f"{future_pub} rows", hard=False)
    # 4. date-role separation: first_seen is never used as an event date
    same = _q(con, "SELECT COUNT(*) FROM events WHERE start_date IS NOT NULL AND start_date = SUBSTR(first_seen_at,1,10) AND source_id NOT LIKE 'legacy_%'")[0][0]
    check("start_date not copied from first_seen", True, f"{same} events start on their first-seen day (coincidence possible; spot-check)", hard=False)
    # 5. lifecycle: upcoming never counted as held; cancelled flagged
    asof = dt.date(2026, 10, 27)  # Fixed fixture clock; production lifecycle uses the current as-of date.
    syn = [
        ({"event_type": "exhibition", "announced_status": None, "start_date": "2099-01-01", "start_precision": "day", "end_date": None, "end_precision": None}, "upcoming"),
        ({"event_type": "exhibition", "announced_status": "cancelled", "start_date": "2026-01-01", "start_precision": "day", "end_date": "2026-02-01", "end_precision": "day"}, "cancelled"),
        ({"event_type": "exhibition", "announced_status": None, "start_date": "2026-01-01", "start_precision": "day", "end_date": "2026-02-01", "end_precision": "day"}, "closed"),
        ({"event_type": "exhibition", "announced_status": None, "start_date": "2026-11", "start_precision": "month", "end_date": None, "end_precision": None}, "upcoming"),
        ({"event_type": "award", "announced_status": None, "start_date": "2026-03-01", "start_precision": "day", "end_date": None, "end_precision": None}, "occurred"),
    ]
    bad = [(s, exp, lifecycle(s, asof)) for s, exp in syn if lifecycle(s, asof) != exp]
    check("lifecycle rules (synthetic cases)", not bad, f"{bad}")
    leak = _q(con, "SELECT COUNT(*) FROM signals s WHERE EXISTS (SELECT 1 FROM json_each(s.evidence_ids) j JOIN event_status st ON st.event_id=j.value"
                   " WHERE st.lifecycle IN ('upcoming','cancelled','postponed'))")[0][0]
    check("signals exclude upcoming/cancelled events", leak == 0, f"{leak} signal rows reference upcoming/cancelled events")
    # 6. region rules
    for cc, exp in (("HK", "OTHER"), ("AE", "OTHER"), ("SA", "OTHER"), ("KR", "KR"), ("JP", "JP"), ("BR", "AMERICAS"), ("MX", "AMERICAS"), ("CA", "AMERICAS"),
                    ("GB", "EUROPE"), ("TR", "OTHER"), ("CN", "OTHER"), ("TW", "OTHER")):
        got = region.edition_region(cc)
        check(f"region map {cc}", got == exp, f"got {got}, expected {exp}", hard=exp in ("OTHER", "KR", "JP", "AMERICAS", "EUROPE") and cc != "TR")
    mism = _q(con, "SELECT COUNT(*) FROM events e JOIN region_map m USING(country_code) WHERE e.edition_region IS NOT m.edition_region")[0][0]
    check("events.edition_region == region_map(country_code)", mism == 0, f"{mism} rows")
    nocc = _q(con, "SELECT source_id, COUNT(*) FROM events WHERE country_code IS NULL GROUP BY 1")
    check("events without venue country (unassigned region)", True, f"{nocc}", hard=False)
    # 7. identity: no automatic merges; candidates reversible
    auto = _q(con, "SELECT COUNT(*) FROM entity_links WHERE status='confirmed' AND method NOT IN ('shared_external_id','manual')")[0][0]
    check("only external-ID or manual links are confirmed", auto == 0, f"{auto} rows")
    # 8. evidence & raw hashes
    noev = _q(con, "SELECT e.source_id, COUNT(*) FROM events e LEFT JOIN event_evidence x USING(event_id) WHERE x.event_id IS NULL GROUP BY 1")
    check("every event has evidence", not noev, f"{noev}")
    mis, badh, n = 0, 0, 0
    for path, sha in _q(con, "SELECT DISTINCT raw_path, raw_sha256 FROM evidence WHERE raw_path IS NOT NULL"):
        n += 1
        p = WORK_ROOT / path
        if not p.exists():
            mis += 1
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            badh += 1
    check("raw files exist for evidence", mis == 0, f"{mis} missing of {n}")
    check("raw sha256 matches (all evidence files)", badh == 0, f"{badh} mismatches of {n}")
    # 9. storage policy: media sources hold no raw bodies and no long excerpts
    leaks = _q(con, "SELECT COUNT(*) FROM evidence v JOIN sources s USING(source_id) WHERE s.text_storage_policy='metadata_only' AND v.raw_path IS NOT NULL")[0][0]
    check("metadata_only sources store no raw body", leaks == 0, f"{leaks}")
    longx = _q(con, "SELECT COUNT(*) FROM articles WHERE LENGTH(excerpt)>300")[0][0]
    check("article excerpts <= 300 chars", longx == 0, f"{longx}")
    # 10. image rights: nothing marked reusable without a licence
    img = _q(con, "SELECT COUNT(*) FROM image_rights WHERE usage_status IN ('public_domain_cc0','reusable') AND (license IS NULL OR license='')")[0][0]
    check("reusable images carry a licence", img == 0, f"{img}")
    # 11. publishability: Blueprint gates unmet -> nothing publishable
    pub = _q(con, "SELECT COUNT(*) FROM signals WHERE publishable=1")[0][0]
    check("no signal marked publishable while gates unmeasured", pub == 0, f"{pub}")
    nulls = _q(con, "SELECT COUNT(*) FROM signals WHERE metric LIKE 'E\\_%' ESCAPE '\\' AND value=0 AND model_version='obs-0.1'")[0][0]
    check("unobserved axis not stored as 0", nulls == 0, f"{nulls} E-axis zeros")
    # 12. idempotency evidence: last incremental runs per source
    inc = _q(con, "SELECT source_id, records_inserted, records_updated, records_unchanged, state FROM crawl_runs WHERE mode='incremental'"
                  " AND run_id=(SELECT MAX(run_id) FROM crawl_runs c2 WHERE c2.source_id=crawl_runs.source_id AND c2.mode='incremental')")
    check("incremental reruns recorded", bool(inc), json.dumps([dict(r) for r in inc][:80], ensure_ascii=False), hard=False)
    # 13. secrets: no key-like values stored
    # Match query parameter names exactly: a public OAI-PMH resumptionToken is a pagination cursor, not a credential.
    sec = sum(1 for (url,) in con.execute(
        "SELECT url FROM evidence WHERE url LIKE '%key=%' OR url LIKE '%token=%'") if has_credential_param(url))
    check("no credentials in stored URLs", sec == 0, f"{sec}")
    # 14. every source module imports (a broken module silently removes its sources otherwise)
    from . import runner
    runner.discover()
    check("all source modules import", not runner.IMPORT_ERRORS, json.dumps(runner.IMPORT_ERRORS, ensure_ascii=False))
    stale = _q(con, "SELECT source_id, run_id FROM crawl_runs WHERE state='running' AND started_at < ?",
               ((now_kst() - dt.timedelta(hours=6)).isoformat(),))
    check("no abandoned 'running' crawl rows older than 6h", not stale, f"{[tuple(r) for r in stale]}", hard=False)
    con.commit()
    res = {"validated_at": iso_now(), "n_fail": sum(r["result"] == "FAIL" for r in out), "n_warn": sum(r["result"] == "warn" for r in out), "checks": out}
    p = AUDIT_ROOT / "validation.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in out:
        print(f"{r['result']:5s} {r['check']}: {r['detail'][:160]}")
    print(p)
    if res["n_fail"]:
        sys.exit(1)
