"""Import reusable LOCAL legacy assets into the normalized store (read-only on originals).

Every legacy row keeps its own source_id (prefixed legacy_) so it is never confused with live official
collection; evidence points at the local file with its sha256. Derived/interpretive columns (memos,
'선행신호', rankings, LLM summaries) are deliberately NOT imported.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import sqlite3
from pathlib import Path

from . import db
from .config import ARTRENDATA, iso_now, ro_sqlite_uri, v2v_root
from .sources._common import clean_text, parse_date_range, split_title_artist

PV = "legacy-1"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ev(con, source_id, p: Path, locator=None, excerpt=None):
    rel = p.relative_to(ARTRENDATA)
    return db.add_evidence(con, source_id=source_id, url=f"file://ARTRENData/{rel}", fetched_at=iso_now(), http_status=None,
                           raw_path=None, raw_sha256=_sha(p), locator=locator, excerpt=excerpt, parser_version=PV)


def _run(con, run_id, source_id, fn):
    stats: dict = {}
    started = iso_now()
    try:
        fn(con, source_id, stats)
        state, err = "success", None
        con.commit()
    except Exception as e:  # record and continue with the next legacy asset
        con.rollback()
        state, err = "error", f"{type(e).__name__}: {e}"
    con.execute("INSERT OR REPLACE INTO crawl_runs(run_id,source_id,mode,started_at,finished_at,state,records_parsed,records_inserted,"
                "records_updated,records_unchanged,error,parser_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, source_id, "legacy_import", started, iso_now(), state, stats.get("parsed", 0), stats.get("inserted", 0),
                 stats.get("updated", 0), stats.get("unchanged", 0), err, PV))
    db.set_source_status(con, source_id, operational_state="local_only" if state == "success" else "error",
                         st_local_file="ok", st_live_response="n/a(local)")
    con.commit()
    print(f"{source_id}: {state} {stats} {err or ''}")


LEGACY_SOURCES = {
    "legacy_v2v_artnews": dict(name="v2v artnews.db (Google News RSS / Naver / feeds metadata, 2026-10-12..20 load)", source_kind="legacy_local",
                               region_scope="GLOBAL", access_method="local", blueprint_data_id="D37,D32-D36(partial)", priority="P0",
                               text_storage_policy="metadata_only",
                               notes="74% of URLs are news.google.com redirects (publisher URL unresolved); 45% rows flagged mismatch by v2v filters; only rows with is_noise=0 and (flagged_mismatch=0 or keep_manual=1) imported"),
    "legacy_moma_calendar_202608": dict(name="MoMA calendar scrape (museums/data/moma_exhibition_history.csv, 2026-08-25)", source_kind="legacy_local",
                                        region_scope="AMERICAS", country_codes="US", access_method="local", blueprint_data_id="D12", blueprint_org_id="O18",
                                        priority="P0", notes="earlier crawl; live moma.org is Cloudflare-blocked for our honest UA on 2026-10-27, so this snapshot is not refreshed"),
    "legacy_whitney_history_202608": dict(name="Whitney exhibition history scrape (museums/data/whitney_exhibition_history.csv, 2026-08-25)",
                                          source_kind="legacy_local", region_scope="AMERICAS", country_codes="US", access_method="local",
                                          blueprint_data_id="D13", blueprint_org_id="O19", priority="P1"),
    "legacy_biennale_universes": dict(name="Biennial artist lists via universes.art aggregator (biennale/biennale_artists.csv)", source_kind="legacy_local",
                                      region_scope="GLOBAL", access_method="local", blueprint_data_id="D16,D17,D19,D20", priority="P1",
                                      notes="aggregator, not the official biennial site; confidence medium; Korean editorial memo columns not imported"),
    "legacy_biennale_awards": dict(name="Biennial awards table (biennale/biennale_awards.csv, hand-compiled)", source_kind="legacy_local",
                                   region_scope="GLOBAL", access_method="local", blueprint_data_id="D16", priority="P1",
                                   notes="no source URL per row; '선행신호'/memo interpretive columns excluded"),
    "legacy_gallery_news_202608": dict(name="Gallery news/exhibition item snapshots (news/data/*_all.json, *_items.json, 2026-08-21..25)",
                                       source_kind="legacy_local", region_scope="GLOBAL", access_method="local", blueprint_data_id="D31,D56",
                                       priority="P0", text_storage_policy="metadata_only",
                                       notes="'date' field semantics vary by gallery (event date vs post date); stored as legacy_date in categories, not as published_at"),
    "legacy_v2v_wiki_artists": dict(name="v2v artists_wikidata.json (273 artists with Wikidata QIDs)", source_kind="legacy_local", region_scope="GLOBAL",
                                    access_method="local", blueprint_data_id="D01", priority="P0"),
    "legacy_art_market_db": dict(name="data/art_market.db auction lots (6 houses) + data/*.csv", source_kind="legacy_local", region_scope="GLOBAL",
                                 access_method="local", blueprint_data_id="D48-D52", priority="P2",
                                 notes="reference only; not imported. Mixed price bases (hammer vs hammer+premium), 50,547 Poly rows dated 1970-01-01 placeholder, heterogeneous status labels"),
    "legacy_local_reports": dict(name="Market Report/*.pdf local copies", source_kind="legacy_local", region_scope="GLOBAL", access_method="local",
                                 blueprint_data_id="D41,D44", priority="P0"),
}


def imp_artnews(con, sid_, stats):
    path = v2v_root() / "data" / "artnews.db"
    src = sqlite3.connect(ro_sqlite_uri(path), uri=True)
    src.row_factory = sqlite3.Row
    ev = _ev(con, sid_, path, locator="articles")
    wd = json.loads((v2v_root() / "data" / "artists_wikidata.json").read_text(encoding="utf-8"))
    themes: dict[int, list[str]] = {}
    for r in src.execute("SELECT article_id, theme_id FROM article_themes"):
        themes.setdefault(r[0], []).append(r[1])
    ents: dict[int, list[str]] = {}
    for r in src.execute("SELECT article_id, entity_id FROM article_entities WHERE role='artist'"):
        ents.setdefault(r[0], []).append(r[1])
    rows = src.execute("SELECT * FROM articles WHERE is_noise=0 AND (flagged_mismatch=0 OR keep_manual=1) ORDER BY id").fetchall()
    seen = set()
    for r in rows:
        url = r["original_url"] if (r["original_url"] or "").startswith("http") else r["url"]
        if url in seen:  # several v2v rows resolve to one publisher URL: keep the first (lowest id)
            stats["skipped_same_url"] = stats.get("skipped_same_url", 0) + 1
            continue
        seen.add(url)
        aid = db.upsert_article(con, stats, source_id=sid_, canonical_url=url, title=r["title"], published_at=r["published_at"],
                                publisher=r["press"] or r["press_domain"], lang=r["lang"],
                                categories=";".join(sorted(themes.get(r["id"], []))) or None,
                                type_basis=f"v2v crawl_site={r['crawl_site']}; publisher_url_resolved={'yes' if url != r['url'] or not r['url'].startswith('https://news.google.com') else 'no'}")
        for e in ents.get(r["id"], []):
            q = wd.get(e, {}).get("qid")
            if q:
                ent = db.ensure_entity(con, entity_type="person", name=e, namespace="wikidata", id_value=q, source_id=sid_)
                con.execute("INSERT INTO article_mentions(article_id,entity_id,mention_type,evidence_text,status) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                            (aid, ent, "v2v_alias_match", None, "candidate"))
        stats["parsed"] = stats.get("parsed", 0) + 1
    con.execute("UPDATE sources SET notes=COALESCE(notes,'')||? WHERE source_id=?", (f" | evidence {ev}", sid_))


def imp_wiki_artists(con, sid_, stats):
    p = v2v_root() / "data" / "artists_wikidata.json"
    ev = _ev(con, sid_, p)
    for key, v in json.loads(p.read_text(encoding="utf-8")).items():
        if not v.get("qid"):
            continue
        existed = con.execute("SELECT 1 FROM entities WHERE id_namespace='wikidata' AND id_value=?", (v["qid"],)).fetchone() is not None
        db.ensure_entity(con, entity_type="person", name=key, namespace="wikidata", id_value=v["qid"], source_id=sid_, evidence_id=ev,
                         birth_year=v.get("birth_year"), death_year=v.get("death_year"))
        stats["parsed"] = stats.get("parsed", 0) + 1
        k = "unchanged" if existed else "inserted"
        stats[k] = stats.get(k, 0) + 1


def imp_moma_calendar(con, sid_, stats):
    p = ARTRENDATA / "museums" / "data" / "moma_exhibition_history.csv"
    ev = _ev(con, sid_, p)
    moma = db.ensure_entity(con, entity_type="institution", name="The Museum of Modern Art", namespace="wikidata", id_value="Q188740")
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            online = (r.get("venue") or "").lower() == "online"
            s, e = r.get("start_date") or None, r.get("end_date") or None
            if e and "ongoing" in (r.get("date_raw") or "").lower():
                e = None  # 'Mar 8, 2025–ongoing': the CSV wrote a bare year into end_date
            sp, ep = _prec(s), _prec(e)
            eid = db.upsert_event(con, stats, source_id=sid_, source_event_key=r["id"], event_type="exhibition",
                                  subtype="collection_display" if r.get("kind") == "galleries" else None, title=clean_text(r["title"]),
                                  title_lang="en", organizer_entity_id=moma, city=None if online else "New York",
                                  country_code=None if online else "US", start_date=s, start_precision=sp, end_date=e, end_precision=ep,
                                  date_text=r.get("date_raw"), url=r.get("url"), parser_version=PV, evidence_id=ev)
            if online:
                db.add_review(con, "region", "events", eid, "online-only program; no physical venue", r.get("url"))
            name = split_title_artist(r["title"])
            if name:
                ent = db.ensure_entity(con, entity_type="person", name=name, namespace=f"src:{sid_}", source_id=sid_, evidence_id=ev)
                db.add_participant(con, eid, ent, "artist", name, ev, "title_pattern", "medium")
            stats["parsed"] = stats.get("parsed", 0) + 1


def imp_whitney(con, sid_, stats):
    p = ARTRENDATA / "museums" / "data" / "whitney_exhibition_history.csv"
    ev = _ev(con, sid_, p)
    wh = db.ensure_entity(con, entity_type="institution", name="Whitney Museum of American Art", namespace="wikidata", id_value="Q639791")
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            yr = int(r["year"]) if (r.get("year") or "").isdigit() else None
            s, sp, e, ep = parse_date_range(r.get("date_raw"), default_year=yr)
            eid = db.upsert_event(con, stats, source_id=sid_, source_event_key=r["slug"], event_type="exhibition", title=clean_text(r["title"]),
                                  title_lang="en", organizer_entity_id=wh, city="New York", country_code="US", start_date=s,
                                  start_precision=sp, end_date=e, end_precision=ep, date_text=r.get("date_raw"), url=r.get("url"),
                                  parser_version=PV, evidence_id=ev)
            name = split_title_artist(r["title"])
            if name:
                ent = db.ensure_entity(con, entity_type="person", name=name, namespace=f"src:{sid_}", source_id=sid_, evidence_id=ev)
                db.add_participant(con, eid, ent, "artist", name, ev, "title_pattern", "medium")
            stats["parsed"] = stats.get("parsed", 0) + 1


BIENNALE_PLACE = {"베네치아": ("Venice", "IT", "La Biennale di Venezia"), "광주": ("Gwangju", "KR", "Gwangju Biennale"),
                  "상파울루": ("São Paulo", "BR", "Bienal de São Paulo"), "휘트니": ("New York", "US", "Whitney Biennial"),
                  "요코하마": ("Yokohama", "JP", "Yokohama Triennale"), "부산": ("Busan", "KR", "Busan Biennale"),
                  "도큐멘타": ("Kassel", "DE", "documenta"), "카셀": ("Kassel", "DE", "documenta"), "시드니": ("Sydney", "AU", "Biennale of Sydney"),
                  "이스탄불": ("Istanbul", "TR", "Istanbul Biennial"), "샤르자": ("Sharjah", "AE", "Sharjah Biennial"),
                  "리버풀": ("Liverpool", "GB", "Liverpool Biennial"), "베를린": ("Berlin", "DE", "Berlin Biennale"),
                  "아이치": ("Aichi", "JP", "Aichi Triennale"), "타이베이": ("Taipei", "TW", "Taipei Biennial"), "상하이": ("Shanghai", "CN", "Shanghai Biennale"),
                  "마니페스타": (None, None, "Manifesta"), "휘트니 비엔날레": ("New York", "US", "Whitney Biennial")}


def imp_biennale(con, sid_, stats):
    p = ARTRENDATA / "biennale" / "biennale_artists.csv"
    ev = _ev(con, sid_, p)
    with p.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    first_url = {}
    for r in rows:
        first_url.setdefault(f"{r['비엔날레']}|{r['회차']}|{r['연도']}", r.get("원문링크"))
    if True:
        for r in rows:
            city, cc, official = BIENNALE_PLACE.get(r["비엔날레"], (None, None, r["비엔날레"]))
            key = f"{r['비엔날레']}|{r['회차']}|{r['연도']}"
            org = db.ensure_entity(con, entity_type="biennial", name=official, namespace=f"src:{sid_}", source_id=sid_)
            eid = db.upsert_event(con, stats, source_id=sid_, source_event_key=key, event_type="biennial_edition",
                                  title=f"{official} {r['연도']} ({r['회차']})", organizer_entity_id=org, city=city, country_code=cc,
                                  start_date=r["연도"], start_precision="year", date_text=r["연도"], url=first_url[key],
                                  parser_version=PV, evidence_id=ev)
            if cc is None:
                db.add_review(con, "region", "events", eid, "biennial host city not mapped", r["비엔날레"])
            name = clean_text(r["작가"])
            ent = db.ensure_entity(con, entity_type="person", name=name, namespace=f"src:{sid_}", source_id=sid_, evidence_id=ev,
                                   birth_year=int(r["생년"]) if (r.get("생년") or "").isdigit() else None)
            db.add_participant(con, eid, ent, "artist", name, ev, "structured_field", "medium")
            stats["parsed"] = stats.get("parsed", 0) + 1


def imp_awards(con, sid_, stats):
    p = ARTRENDATA / "biennale" / "biennale_awards.csv"
    ev = _ev(con, sid_, p)
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            city, cc, official = BIENNALE_PLACE.get(r["비엔날레"], (None, None, r["비엔날레"]))
            org = db.ensure_entity(con, entity_type="biennial", name=official, namespace=f"src:{sid_}", source_id=sid_)
            eid = db.upsert_event(con, stats, source_id=sid_, source_event_key=f"{r['비엔날레']}|{r['연도']}|{r['상']}|{r['수상자']}",
                                  event_type="award", title=f"{official} {r['연도']}: {clean_text(r['상'])}", organizer_entity_id=org,
                                  city=city, country_code=cc, start_date=r["연도"], start_precision="year", date_text=r["연도"],
                                  parser_version=PV, evidence_id=ev)
            name = clean_text(r["수상자"])
            ent = db.ensure_entity(con, entity_type="person", name=name, namespace=f"src:{sid_}", source_id=sid_, evidence_id=ev)
            db.add_participant(con, eid, ent, "winner", name, ev, "structured_field", "medium")
            db.add_review(con, "classification", "events", eid, "legacy award row without source URL; verify on official site", r["비엔날레"])
            stats["parsed"] = stats.get("parsed", 0) + 1


GALLERY_FILES = {"kukje_items": "Kukje Gallery", "galleryhyundai_items": "Gallery Hyundai", "arario_items": "Arario Gallery",
                 "pkm_items": "PKM Gallery", "leeahn_items": "Leeahn Gallery", "soheon_items": "Soheon Gallery",
                 "hakgojae_items": "Hakgojae Gallery (press mentions)", "ropac_all": "Thaddaeus Ropac", "wc_all": "White Cube",
                 "pc_all": "Pace Gallery", "ls_all": "Lisson Gallery", "gc_all": "Gagosian", "perrotin_all": "Perrotin", "ar_all": "Almine Rech"}


def imp_gallery_news(con, sid_, stats):
    d = ARTRENDATA / "news" / "data"
    seen = set()
    for stem, gallery in GALLERY_FILES.items():
        p = d / f"{stem}.json"
        if not p.exists():
            continue
        ev = _ev(con, sid_, p)
        items = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = list(items.values())
        for it in items:
            if not isinstance(it, dict) or not it.get("url") or not (it.get("headline") or it.get("title")):
                continue
            if it["url"] in seen:
                stats["skipped_same_url"] = stats.get("skipped_same_url", 0) + 1
                continue
            seen.add(it["url"])
            cats = [f"gallery={gallery}", f"legacy_date={it.get('date')}"]
            if it.get("category"):
                cats.append(f"category={it['category']}")
            if it.get("location"):
                cats.append(f"location={it['location']}")
            if it.get("dates_raw") or it.get("run"):
                cats.append(f"dates_raw={it.get('dates_raw') or it.get('run')}")
            db.upsert_article(con, stats, source_id=sid_, canonical_url=it["url"], title=clean_text(it.get("headline") or it.get("title")),
                              publisher=gallery, owner_group=gallery, article_type="gallery_announcement",
                              type_basis=f"legacy snapshot {p.name}; evidence {ev}", categories="; ".join(cats))
            stats["parsed"] = stats.get("parsed", 0) + 1


def imp_reports(con, sid_, stats):
    meta = {}
    audit = ARTRENDATA / "ARTREND_magazine_data" / "work" / "audit" / "docs_vault_audit.json"
    if audit.exists():
        for r in json.loads(audit.read_text(encoding="utf-8")).get("reports", []):
            if isinstance(r, dict) and r.get("path"):
                meta[r["path"]] = r
    for p in sorted(glob.glob(str(ARTRENDATA / "Market Report" / "*.pdf"))) + sorted(glob.glob(str(ARTRENDATA / "Market Data(price)" / "*"))):
        p = Path(p)
        rel = str(p.relative_to(ARTRENDATA))
        m = meta.get(rel, {})
        sha = _sha(p)
        dup = con.execute("SELECT report_id FROM reports WHERE sha256=? AND local_path NOT LIKE 'ARTRENData/%'", (sha,)).fetchone()
        rid = db.sid("rpt", rel)
        existed = con.execute("SELECT 1 FROM reports WHERE report_id=? AND sha256=?", (rid, sha)).fetchone() is not None
        paid = "Price Database" in rel
        con.execute(
            "INSERT INTO reports(report_id,title,publisher,authors,sponsor,published_date,observation_period,geo_scope,methodology,sample,price_basis,"
            "official_url,local_path,sha256,pages,rights_note,access_status,next_check,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(report_id) DO UPDATE SET sha256=excluded.sha256, notes=excluded.notes",
            (rid, m.get("title") or p.stem, m.get("publisher"), m.get("authors"), m.get("sponsor"), m.get("publication_date"),
             m.get("observation_period"), m.get("geographic_market_scope"), m.get("methodology_sample"), None,
             m.get("currency_price_basis"), m.get("official_source_url"), f"ARTRENData/{rel}", sha, _int(m.get("page_count")),
             m.get("rights_usage_statement") or ("subscription screenshot: internal reference only, do not ingest/redistribute" if paid else None),
             "local(subscription capture)" if paid else "local", "monthly", f"identical to downloaded {dup[0]}" if dup else None))
        stats["parsed"] = stats.get("parsed", 0) + 1
        stats["unchanged" if existed else "inserted"] = stats.get("unchanged" if existed else "inserted", 0) + 1


def _prec(v):
    """Precision from the stored string itself ('2019-09' from 'Fall 2019' is month precision, not day)."""
    return {10: "day", 7: "month", 4: "year"}.get(len(v)) if v else None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main():
    con = db.connect()
    db.init_schema(con)
    for sid_, meta in LEGACY_SOURCES.items():
        db.upsert_source(con, sid_, st_local_file="ok", **meta)
    con.commit()
    run_id = f"{iso_now()[:19].replace('-', '').replace(':', '')}_legacy"
    _run(con, run_id, "legacy_v2v_wiki_artists", imp_wiki_artists)
    _run(con, run_id, "legacy_v2v_artnews", imp_artnews)
    _run(con, run_id, "legacy_moma_calendar_202608", imp_moma_calendar)
    _run(con, run_id, "legacy_whitney_history_202608", imp_whitney)
    _run(con, run_id, "legacy_biennale_universes", imp_biennale)
    _run(con, run_id, "legacy_biennale_awards", imp_awards)
    _run(con, run_id, "legacy_gallery_news_202608", imp_gallery_news)
    _run(con, run_id, "legacy_local_reports", imp_reports)
    db.set_source_status(con, "legacy_art_market_db", operational_state="local_only(reference, not imported)", st_local_file="ok")
    con.commit()
