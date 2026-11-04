"""Derived layers recomputed from the normalized store (idempotent; safe to rerun).

1. event_status   lifecycle at ASOF (upcoming / ongoing / closed / cancelled / unknown...) — never stored on events.
2. event_links    duplicate reports of the same exhibition inside one owner group; cross-group same-title => tour candidate.
3. entity_links   confirmed (shared Wikidata/ULAN id) and candidate (exact normalized name) identity links; clusters.
4. coverage       per source x region x country: counts, date span, 90/90 windows, history depth.
5. signals        I/G/E observation counts per artist cluster x region (model 'obs-0.1'); publishable=0 unless gates pass.
6. evidence_cards draft cards per region/section from real rows (status draft_unreviewed).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict

from . import db
from .config import iso_now, now_kst

MODEL_VERSION = "obs-0.1"
I_KINDS = {"museum", "biennial", "award", "residency", "collection"}
G_KINDS = {"gallery", "fair"}
I_EVENT_TYPES = {"exhibition", "biennial_edition", "award", "residency", "open_call_selection", "acquisition", "program"}
ROOKIE_TYPES = {"residency", "open_call_selection", "award"}
POINT_TYPES = {"acquisition", "award", "open_call_selection", "publication", "representation"}


def _asof():
    return now_kst().date()


def lifecycle(row, asof: dt.date) -> str:
    st = (row["announced_status"] or "").lower()
    if st in ("cancelled", "canceled"):
        return "cancelled"
    if st == "postponed":
        return "postponed"
    a = asof.isoformat()
    s, sp, e, ep = row["start_date"], row["start_precision"], row["end_date"], row["end_precision"]
    if s and sp == "day":
        if s > a:
            return "upcoming"
        if row["event_type"] in POINT_TYPES and not e:
            return "occurred"
        if e and ep == "day":
            return "ongoing" if e >= a else "closed"
        return "started_end_unknown"
    if s and sp in ("month", "year"):
        cut = a[: len(s)]
        if s > cut:
            return "upcoming"
        if e and ep == "day" and e < a:
            return "closed"
        if s < cut and (not e):
            return "past_or_ongoing(imprecise)"
        return "unknown_precision"
    if not s and e and ep == "day":
        return "closed" if e < a else "ongoing_or_upcoming(start_unknown)"
    return "unknown"


def build_event_status(con, asof):
    con.execute("CREATE TABLE IF NOT EXISTS event_status(event_id TEXT PRIMARY KEY REFERENCES events(event_id), asof TEXT NOT NULL, lifecycle TEXT NOT NULL)")
    con.execute("DELETE FROM event_status")
    rows = con.execute("SELECT event_id, event_type, announced_status, start_date, start_precision, end_date, end_precision FROM events").fetchall()
    con.executemany("INSERT INTO event_status VALUES(?,?,?)", [(r["event_id"], asof.isoformat(), lifecycle(r, asof)) for r in rows])


def _title_key(t):
    t = db.name_key(t or "")
    return re.sub(r"[^\w\s]", "", t)[:80]


def build_event_links(con):
    con.execute("CREATE TABLE IF NOT EXISTS event_links(event_id TEXT NOT NULL, canonical_event_id TEXT NOT NULL, link_type TEXT NOT NULL,"
                " reason TEXT, PRIMARY KEY(event_id, link_type))")
    con.execute("DELETE FROM event_links")
    rows = con.execute(
        "SELECT e.event_id, e.title, e.start_date, e.source_id, e.event_type, s.owner_group, s.source_kind, e.edition_region, e.country_code"
        " FROM events e JOIN sources s USING(source_id) WHERE e.event_type IN ('exhibition','biennial_edition') AND e.start_date IS NOT NULL").fetchall()
    by_key = defaultdict(list)
    for r in rows:
        by_key[(_title_key(r["title"]), (r["start_date"] or "")[:7])].append(r)
    dup = 0
    for (_, _), group in by_key.items():
        if len(group) < 2:
            continue
        by_owner = defaultdict(list)
        for r in group:
            by_owner[r["owner_group"] or r["source_id"]].append(r)
        for owner, items in by_owner.items():
            if len(items) > 1:  # same owner, same title, same month -> one exhibition reported twice (prefer live over legacy)
                items.sort(key=lambda r: (r["source_id"].startswith("legacy_"), r["source_id"]))
                for r in items[1:]:
                    con.execute("INSERT OR REPLACE INTO event_links VALUES(?,?,?,?)", (r["event_id"], items[0]["event_id"], "duplicate_report",
                                                                                     f"same owner_group={owner}, title, start month"))
                    dup += 1
    # tour candidates: same normalized title in different owner groups within ~18 months
    by_title = defaultdict(list)
    for r in rows:
        k = _title_key(r["title"])
        if len(k) >= 12:
            by_title[k].append(r)
    tours = 0
    for k, items in by_title.items():
        owners = {i["owner_group"] or i["source_id"] for i in items}
        if len(owners) > 1:
            items.sort(key=lambda r: r["start_date"])
            span = (dt.date.fromisoformat(items[-1]["start_date"][:10] if len(items[-1]["start_date"]) >= 10 else items[-1]["start_date"][:4] + "-01-01")
                    - dt.date.fromisoformat(items[0]["start_date"][:10] if len(items[0]["start_date"]) >= 10 else items[0]["start_date"][:4] + "-01-01")).days
            if span <= 550:
                tour_id = db.sid("tour", k)
                for r in items:
                    con.execute("INSERT OR REPLACE INTO event_links VALUES(?,?,?,?)", (r["event_id"], tour_id, "tour_candidate",
                                                                                     f"same title across {len(owners)} owner groups within {span} days"))
                    db.add_review(con, "classification", "events", r["event_id"], "possible touring exhibition / co-production",
                                  f"title key '{k}' at {len(owners)} owner groups")
                tours += 1
    return dup, tours


def build_entity_links(con):
    now = iso_now()
    con.execute("DELETE FROM entity_links WHERE method IN ('shared_external_id','exact_normalized_name')")
    # confirmed: shared external ID (wikidata / ulan)
    ext = con.execute("SELECT namespace, external_id, GROUP_CONCAT(DISTINCT entity_id) ids FROM aliases WHERE namespace IN ('wikidata','ulan') AND external_id<>''"
                      " GROUP BY 1,2 HAVING COUNT(DISTINCT entity_id)>1").fetchall()
    n_conf = 0
    for r in ext:
        ids = sorted(r["ids"].split(","))
        for b in ids[1:]:
            con.execute("INSERT OR IGNORE INTO entity_links VALUES(?,?,?,?,?,?,?,NULL)", (ids[0], b, "same_as", "confirmed", "shared_external_id",
                                                                                     f"{r['namespace']}:{r['external_id']}", now))
            n_conf += 1
    # candidate: exact normalized name among people/groups, different namespaces; reject on birth-year conflict
    rows = con.execute("SELECT entity_id, canonical_name, id_namespace, birth_year FROM entities WHERE entity_type IN ('person','group','unknown')").fetchall()
    by = defaultdict(list)
    for r in rows:
        k = db.name_key(r["canonical_name"])
        if (len(k.split()) >= 2) or (re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", k) and len(k) >= 2):
            by[k].append(r)
    n_cand = n_rej = 0
    for k, items in by.items():
        if len(items) < 2 or len(items) > 12:
            if len(items) > 12:
                db.add_review(con, "identity", "entities", k, "very common name; not linked automatically", f"{len(items)} entities")
            continue
        items.sort(key=lambda r: r["entity_id"])
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a["id_namespace"] == b["id_namespace"]:
                    continue
                conflict = a["birth_year"] and b["birth_year"] and abs(a["birth_year"] - b["birth_year"]) > 1
                status = "rejected" if conflict else "candidate"
                con.execute("INSERT OR IGNORE INTO entity_links VALUES(?,?,?,?,?,?,?,NULL)",
                            (a["entity_id"], b["entity_id"], "same_as", status, "exact_normalized_name",
                             f"name='{k}' birth {a['birth_year']} vs {b['birth_year']}", now))
                n_rej += bool(conflict)
                n_cand += not conflict
    # clusters (union-find): confirmed-only and confirmed+candidate
    con.execute("CREATE TABLE IF NOT EXISTS entity_clusters(entity_id TEXT PRIMARY KEY, cluster_confirmed TEXT NOT NULL, cluster_candidate TEXT NOT NULL)")
    con.execute("DELETE FROM entity_clusters")
    ids = [r[0] for r in con.execute("SELECT entity_id FROM entities")]

    def uf(statuses):
        parent = {i: i for i in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        q = "SELECT entity_id_a, entity_id_b FROM entity_links WHERE status IN (%s) AND reversed_at IS NULL" % ",".join("?" * len(statuses))
        for a, b in con.execute(q, statuses):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        return {i: find(i) for i in ids}
    c1, c2 = uf(["confirmed"]), uf(["confirmed", "candidate"])
    con.executemany("INSERT INTO entity_clusters VALUES(?,?,?)", [(i, c1[i], c2[i]) for i in ids])
    return n_conf, n_cand, n_rej


def build_coverage(con, asof):
    a = asof.isoformat()
    d90, d180 = (asof - dt.timedelta(days=90)).isoformat(), (asof - dt.timedelta(days=180)).isoformat()
    con.execute("DELETE FROM coverage WHERE asof=?", (a,))
    notes = {r[0]: r[1] for r in con.execute(
        "SELECT source_id, error FROM crawl_runs c WHERE finished_at=(SELECT MAX(finished_at) FROM crawl_runs c2 WHERE c2.source_id=c.source_id)")}
    rows = con.execute(
        "SELECT e.source_id, COALESCE(e.edition_region,'UNMAPPED') reg, COALESCE(e.country_code,'') cc, COUNT(*) n, MIN(e.start_date) mn, MAX(e.start_date) mx,"
        " SUM(e.start_date>=? AND e.start_date<=? AND e.start_precision='day') l90,"
        " SUM(e.start_date>=? AND e.start_date<? AND e.start_precision='day') p90,"
        " SUM(st.lifecycle='upcoming') up"
        " FROM events e JOIN event_status st USING(event_id) WHERE e.event_id NOT IN (SELECT event_id FROM event_links WHERE link_type='duplicate_report')"
        " GROUP BY 1,2,3", (d90, a, d180, d90)).fetchall()
    for r in rows:
        hist = "history reaches prior 90-day window" if (r["mn"] or "9999") <= d180 else "NO data before prior window -> no 90/90 comparison"
        con.execute("INSERT INTO coverage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["source_id"], a, r["reg"], r["cc"], "event", r["n"], r["mn"], r["mx"], r["l90"], r["p90"], r["up"],
                     f"{hist}; crawler note: {(notes.get(r['source_id']) or '')[:200]}",
                     "legacy_snapshot" if r["source_id"].startswith("legacy_") else "listing_as_published(unverified completeness)"))
    for r in con.execute("SELECT source_id, COUNT(*) n, MIN(published_at) mn, MAX(published_at) mx, SUM(published_at>=? AND published_at<=?) l90,"
                         " SUM(published_at>=? AND published_at<?) p90 FROM articles GROUP BY 1", (d90, a + "T99", d180, d90)).fetchall():
        con.execute("INSERT INTO coverage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["source_id"], a, "GLOBAL(media)", "", "article", r["n"], r["mn"], r["mx"], r["l90"], r["p90"], None,
                     "articles are not region-assigned; feed depth limits history", "feed_window(partial)"))


def _independent_key(r):
    return r["owner_group"] or r["source_id"]


def build_signals(con, asof):
    """Observation counts only. Blueprint weights (I50/G25/E25, 60/40) are NOT applied: gates are unmet."""
    a = asof.isoformat()
    d90, d180 = (asof - dt.timedelta(days=90)).isoformat(), (asof - dt.timedelta(days=180)).isoformat()
    con.execute("DELETE FROM signals WHERE model_version=?", (MODEL_VERSION,))
    rows = con.execute(
        "SELECT c.cluster_candidate cl, e.event_id, e.edition_region reg, e.start_date, e.event_type, s.source_kind, s.owner_group, s.source_id, st.lifecycle"
        " FROM event_participants p JOIN events e USING(event_id) JOIN sources s ON s.source_id=e.source_id JOIN event_status st USING(event_id)"
        " JOIN entity_clusters c ON c.entity_id=p.entity_id"
        " WHERE p.role IN ('artist','winner','nominee','finalist','resident') AND e.start_precision='day' AND e.start_date>=? AND e.start_date<=?"
        " AND e.edition_region IS NOT NULL AND e.event_id NOT IN (SELECT event_id FROM event_links WHERE link_type='duplicate_report')"
        " AND st.lifecycle NOT IN ('cancelled','postponed')", (d180, a)).fetchall()
    agg = defaultdict(lambda: {"I_recent": set(), "I_prev": set(), "G_recent": set(), "G_prev": set(), "I_groups": set(), "ev": []})
    for r in rows:
        axis = "I" if r["source_kind"] in I_KINDS or r["source_kind"] == "legacy_local" and r["event_type"] in I_EVENT_TYPES else ("G" if r["source_kind"] in G_KINDS else None)
        if not axis:
            continue
        win = "recent" if r["start_date"] >= d90 else "prev"
        k = (r["cl"], r["reg"])
        agg[k][f"{axis}_{win}"].add(r["event_id"])
        if axis == "I" and win == "recent":
            agg[k]["I_groups"].add(_independent_key(r))
        agg[k]["ev"].append(r["event_id"])
    n = 0
    for (cl, reg), v in agg.items():
        for metric, val in (("I_events_recent90", len(v["I_recent"])), ("I_events_prev90", len(v["I_prev"])),
                            ("I_independent_owner_groups_recent90", len(v["I_groups"])),
                            ("G_events_recent90", len(v["G_recent"])), ("G_events_prev90", len(v["G_prev"]))):
            con.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (db.sid("sig", cl, reg, a, metric, MODEL_VERSION), "entity_cluster(candidate)", cl, reg, a, metric, "90d", val,
                         "events observed in collected sources only (not all events in region)", MODEL_VERSION,
                         json.dumps(sorted(set(v["ev"]))[:20]), 0,
                         "not publishable: coverage/completeness of panel unmeasured (<80% gate unverifiable); E axis unobserved; comparator N<30 per career group unknown"))
            n += 1
    return n


def main():
    con = db.connect()
    db.init_schema(con)
    asof = _asof()
    build_event_status(con, asof)
    dup, tours = build_event_links(con)
    conf, cand, rej = build_entity_links(con)
    build_coverage(con, asof)
    sig = build_signals(con, asof)
    con.commit()
    from . import cards

    ncards = cards.build(con, asof)
    con.commit()
    print(json.dumps({"asof": asof.isoformat(), "duplicate_reports": dup, "tour_candidates": tours, "links_confirmed": conf,
                      "links_candidate": cand, "links_rejected": rej, "signal_rows": sig, "cards": ncards}, ensure_ascii=False))
