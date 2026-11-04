"""Wikidata identifier candidates for recently active artists (Blueprint D01, L01/L16).

Access: Wikidata Query Service, a documented public API (CC0 data). query.wikidata.org/robots.txt disallows
/sparql for *crawlers*; programmatic use is governed by the Wikimedia API usage guidelines (identifying UA,
low volume, serial requests), which this module follows. Results are identity CANDIDATES only:
exact label match + human + art occupation, unique hit. Multiple hits go to the review queue.
"""
from __future__ import annotations

import re
import datetime as dt

from .. import db
from ..config import iso_now, now_kst

PARSER_VERSION = "wd-2"
WDQS = "https://query.wikidata.org/sparql"
OCCUPATIONS = "wd:Q483501 wd:Q1028181 wd:Q1281618 wd:Q33231 wd:Q3391743 wd:Q18074503 wd:Q1925963 wd:Q15296811 wd:Q42973 wd:Q10862983 wd:Q329439 wd:Q2309784 wd:Q11569986 wd:Q21550646"
BATCH = 15  # longer GET URLs hit HTTP 431
MAX_NAMES = 1600

SOURCES = [dict(
    source_id="wikidata_ids", blueprint_data_id="D01", name="Wikidata Query Service (identifier candidates)", owner_group="Wikimedia Foundation",
    source_kind="identifier", region_scope="GLOBAL", access_method="api", base_url="https://query.wikidata.org", entry_url=WDQS,
    terms_url="https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines", text_storage_policy="raw_internal",
    priority="P0", api_policy_url="https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits",
    st_official_doc="ok(WDQS user manual; API usage guidelines)", st_collection_terms="ok(CC0 structured data)",
    st_image_terms="n/a (no images collected)", max_requests=60, min_interval=3,
)]


def _lits(name: str):
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    if re.search(r"[\uac00-\ud7af]", name):
        langs = ("ko",)
    elif re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", name):
        langs = ("ja", "zh")
    else:
        langs = ("en", "mul", "fr", "es", "pt", "de")
    return " ".join(f'"{esc}"@{l}' for l in langs)


def _query_key(row):
    return db.sid("wdprobe", row["nm"], *sorted(row["ents"].split(",")))


def _pending_names(con, source_id, rows, cutoff, limit):
    recent = {r[0] for r in con.execute(
        "SELECT query_key FROM identifier_queries WHERE source_id=? AND checked_at>=?", (source_id, cutoff))}
    pending = [row for row in rows if _query_key(row) not in recent]
    return pending[:limit], len(rows) - len(pending)


def collect(ctx):
    con = ctx.con
    names = con.execute(
        "SELECT p.name_as_listed nm, GROUP_CONCAT(DISTINCT p.entity_id) ents FROM event_participants p JOIN events e USING(event_id)"
        " JOIN entities en ON en.entity_id=p.entity_id WHERE en.entity_type IN ('person','unknown') AND e.source_id NOT LIKE 'legacy_%'"
        " AND e.event_type<>'acquisition' AND COALESCE(e.start_date,'9999')>='2025-01-01' AND p.role IN ('artist','winner','nominee','finalist','resident')"
        " AND LENGTH(p.name_as_listed) BETWEEN 4 AND 60 AND p.entity_id NOT IN (SELECT entity_id FROM aliases WHERE namespace='wikidata')"
        " AND (? = 'initial' OR p.entity_id NOT IN (SELECT entity_id_a FROM entity_links WHERE method='wikidata_label_unique_art_occupation'"
        " UNION SELECT entity_id_b FROM entity_links WHERE method='wikidata_label_unique_art_occupation'))"
        " GROUP BY 1 ORDER BY MAX(e.start_date) DESC", (ctx.mode,)).fetchall()
    names, cached = _pending_names(con, ctx.source_id, names,
                                   (now_kst() - dt.timedelta(days=30)).isoformat(), MAX_NAMES)
    ctx.count("parsed", cached)
    ctx.count("unchanged", cached)
    ctx.note(f"recent lookup results reused={cached}; cache includes ambiguous/no-match results, expires in 30 days")
    ctx.note(f"names queued={len(names)}")
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        values = " ".join(_lits(r["nm"]) for r in chunk)
        q = ("SELECT ?label ?item ?birth WHERE { VALUES ?label { " + values + " } ?item rdfs:label ?label ; wdt:P31 wd:Q5 ; wdt:P106 ?occ ."
             " VALUES ?occ { " + OCCUPATIONS + " } OPTIONAL { ?item wdt:P569 ?birth } }")
        r = ctx.fetch(WDQS, params={"query": q, "format": "json"}, accept="application/sparql-results+json")
        ev = ctx.evidence(r, locator=f"batch {i // BATCH}")
        hits: dict[str, dict[str, int | None]] = {}
        for b in r.json()["results"]["bindings"]:
            lab = b["label"]["value"]
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            m = re.match(r"^\+?(\d{4})-", b["birth"]["value"]) if "birth" in b else None
            by = int(m.group(1)) if m else None
            hits.setdefault(db.name_key(lab), {})[qid] = by
        for row in chunk:
            ctx.count("fetched")
            found = hits.get(db.name_key(row["nm"]), {})
            ents = row["ents"].split(",")
            ctx.count("parsed")
            if len(found) == 1:
                qid, by = next(iter(found.items()))
                wd = db.ensure_entity(con, entity_type="person", name=row["nm"], namespace="wikidata", id_value=qid,
                                      source_id=ctx.source_id, evidence_id=ev, birth_year=by)
                new = 0
                for e in ents:
                    new += con.execute("INSERT OR IGNORE INTO entity_links VALUES(?,?,?,?,?,?,?,NULL)",
                                (min(e, wd), max(e, wd), "same_as", "candidate", "wikidata_label_unique_art_occupation",
                                 f"label='{row['nm']}' -> {qid}; evidence {ev}", iso_now())).rowcount
                ctx.count("inserted" if new else "unchanged")
            elif len(found) > 1:
                for e in ents:
                    db.add_review(con, "identity", "entities", e, "multiple Wikidata artists share this label",
                                  ", ".join(sorted(found)))
                ctx.count("ambiguous")
            else:
                ctx.count("no_match")
            con.execute(
                "INSERT OR REPLACE INTO identifier_queries VALUES(?,?,?,?,?,?)",
                (ctx.source_id, _query_key(row), row["nm"], iso_now(),
                 "unique_candidate" if len(found) == 1 else "ambiguous" if found else "no_match", ev))
        con.commit()
    ctx.note(f"unique matches={ctx.stats.get('inserted', 0)} ambiguous={ctx.stats.get('ambiguous', 0)}")
