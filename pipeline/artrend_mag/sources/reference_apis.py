"""Documented public reference APIs.

ecb_fx (D58): ECB euro foreign exchange reference rates (Data Portal SDMX API). Free reuse with source
    attribution per ECB copyright notice. Stored in fx_rates; used only for P2 market context.
wikimedia_pageviews (D38): Wikimedia Pageviews REST API (documented; identifying UA required). Monthly user
    views of the English/Korean/Japanese Wikipedia articles for artists that already carry a Wikidata QID
    in our store. This is an attention proxy (E axis input), never a popularity ranking; months without data
    are left absent (not 0).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import urllib.parse

from .. import db
from ..config import now_kst
from ..http import FetchError

PARSER_VERSION = "refapi-1"

SOURCES = [
    dict(source_id="ecb_fx", blueprint_data_id="D58", name="ECB euro reference exchange rates (Data Portal API)", owner_group="European Central Bank",
         source_kind="reference", region_scope="GLOBAL", access_method="api", base_url="https://data-api.ecb.europa.eu",
         entry_url="https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+KRW+GBP+CNY+HKD.EUR.SP00.A",
         terms_url="https://www.ecb.europa.eu/services/disclaimer/html/index.en.html", text_storage_policy="raw_internal", priority="P2",
         api_policy_url="https://data.ecb.europa.eu/help/api/overview", st_official_doc="ok(ECB Data Portal API docs)",
         st_collection_terms="reuse permitted with source attribution (ECB copyright notice)", st_image_terms="n/a", max_requests=5),
    dict(source_id="wikimedia_pageviews", blueprint_data_id="D38", name="Wikimedia Pageviews API (monthly, user agent)", owner_group="Wikimedia Foundation",
         source_kind="attention", region_scope="GLOBAL", access_method="api", base_url="https://wikimedia.org/api/rest_v1",
         entry_url="https://wikimedia.org/api/rest_v1/metrics/pageviews/", terms_url="https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines",
         text_storage_policy="metadata_only", priority="P1", api_policy_url="https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/",
         st_official_doc="ok(AQS analytics API docs)", st_collection_terms="ok(CC0 pageview data; identifying UA)", st_image_terms="n/a",
         max_requests=420, min_interval=1.0),
]


def collect(ctx):
    if ctx.source_id == "ecb_fx":
        return _ecb(ctx)
    return _pageviews(ctx)


def _ecb(ctx):
    start = "2023-01-01" if ctx.mode == "initial" else (now_kst().date() - dt.timedelta(days=45)).isoformat()
    r = ctx.fetch(ctx.meta["entry_url"], params={"format": "csvdata", "startPeriod": start})
    ctx.evidence(r, locator=f"EXR from {start}")
    for row in csv.DictReader(io.StringIO(r.text)):
        if not row.get("OBS_VALUE"):
            continue
        ctx.count("fetched")
        key = (row["TIME_PERIOD"], "EUR", row["CURRENCY"])
        old = ctx.con.execute("SELECT rate FROM fx_rates WHERE rate_date=? AND base=? AND quote=?", key).fetchone()
        val = float(row["OBS_VALUE"])
        if old is None:
            ctx.count("inserted")
        elif old[0] != val:
            ctx.count("updated")
        else:
            ctx.count("unchanged")
        ctx.con.execute("INSERT INTO fx_rates VALUES(?,?,?,?,?) ON CONFLICT(rate_date, base, quote) DO UPDATE SET rate=excluded.rate", (*key, val, ctx.source_id))
        ctx.count("parsed")
    ctx.con.commit()


WDQS = "https://query.wikidata.org/sparql"


def _pageviews(ctx):
    con = ctx.con
    # artists with QIDs that appear in a collected (non-legacy) event since 2025
    rows = con.execute(
        "SELECT DISTINCT a.external_id qid FROM aliases a JOIN entity_clusters c ON c.entity_id=a.entity_id"
        " JOIN entity_clusters c2 ON c2.cluster_candidate=c.cluster_candidate JOIN event_participants p ON p.entity_id=c2.entity_id"
        " JOIN events e ON e.event_id=p.event_id WHERE a.namespace='wikidata' AND e.source_id NOT LIKE 'legacy_%' AND e.event_type<>'acquisition'"
        " AND COALESCE(e.start_date,'')>='2025-04-01' LIMIT 400").fetchall()
    qids = [r["qid"] for r in rows]
    ctx.note(f"qids={len(qids)}")
    if not qids:
        return
    # resolve sitelinks via WDQS (documented API; separate host-level politeness)
    titles = {}
    for i in range(0, len(qids), 150):
        vals = " ".join(f"wd:{q}" for q in qids[i:i + 150])
        q = ("SELECT ?item ?site ?title WHERE { VALUES ?item { " + vals + " } ?a schema:about ?item ; schema:isPartOf ?site ; schema:name ?title ."
             " VALUES ?site { <https://en.wikipedia.org/> <https://ko.wikipedia.org/> <https://ja.wikipedia.org/> } }")
        r = ctx.fetch(WDQS, params={"query": q, "format": "json"}, accept="application/sparql-results+json")
        for b in r.json()["results"]["bindings"]:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            proj = b["site"]["value"].split("//")[1].split(".")[0] + ".wikipedia"
            titles.setdefault(qid, {})[proj] = b["title"]["value"]
    asof = now_kst().date()
    end = asof.replace(day=1) - dt.timedelta(days=1)
    start = (end.replace(day=1) - dt.timedelta(days=365)).replace(day=1)
    for qid, projs in titles.items():
        ent = con.execute("SELECT entity_id FROM entities WHERE id_namespace='wikidata' AND id_value=?", (qid,)).fetchone()
        ent = ent[0] if ent else db.sid("ent", "wikidata", qid)
        for proj, title in projs.items():
            url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
                   f"{proj}/all-access/user/{urllib.parse.quote(title.replace(' ', '_'), safe='')}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00")
            try:
                r = ctx.fetch(url, accept="application/json")
            except FetchError as e:
                ctx.count("detail_errors")
                if "404" not in str(e):
                    ctx.note(f"{qid} {proj}: {e}")
                continue
            items = r.json().get("items", [])
            ctx.count("fetched", len(items))
            for it in items:
                month = f"{it['timestamp'][:4]}-{it['timestamp'][4:6]}"
                sid_ = db.sid("sig", "pv", qid, proj, month)
                old = con.execute("SELECT value FROM signals WHERE signal_id=?", (sid_,)).fetchone()
                con.execute("INSERT OR REPLACE INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sid_, "entity(wikidata)", ent, "GLOBAL", month, f"E_obs_wikipedia_pageviews_monthly:{proj}", "1m", it["views"],
                             f"user-agent views of {proj} article '{title}'", "pageviews-raw", json.dumps([url]), 0,
                             "attention proxy only; language-edition bias; not a popularity ranking"))
                ctx.count("unchanged" if old and old[0] == it["views"] else ("updated" if old else "inserted"))
                ctx.count("parsed")
        con.commit()
