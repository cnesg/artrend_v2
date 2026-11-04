"""Walk ARTRENData (excluding this work directory) and build the asset inventory.

Automated (observed) columns: relative path, format, size, sha256 (files <= 300 MB), mtime (NOT data freshness),
row/record counts for CSV/JSON/JSONL/SQLite. Judgment columns (unit, region, period, URL/ID presence, rights,
Blueprint mapping, reuse verdict) come from ANNOTATIONS, written from the audits in work/audit/*.json; the
longest matching path prefix wins. Bulk directories are summarised as one group row each.
Writes work/audit/inventory.json.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from .config import ARTRENDATA, AUDIT_ROOT, WORK_ROOT, iso_now, ro_sqlite_uri

csv.field_size_limit(sys.maxsize)

BULK_DIRS = ["아트랜드v2v/crawlers/raw/naver_news", "아트랜드v2v/crawlers/raw/google_news_rss", "아트랜드v2v/crawlers/raw/dart",
             "아트랜드v2v/crawlers/raw/media_feeds", "아트랜드v2v/crawlers/raw/sheet_global", "아트랜드v2v/crawlers/raw/tan_rss",
             "아트랜드v2v/.git", "report/node_modules", "아트랜드v2v/ART-Global-Wiki", "vault_curated/artists", "vault_curated/artworks",
             "vault_curated/collectors", "vault_curated/museums", "vault_curated/auction_houses", "vault_curated/galleries",
             "vault_curated/collections", "vault_curated/.obsidian", "아트랜드v2v/data/queue", "report/preview"]

# (unit, region/lang, observed period, latest event / collected, key fields, source URL?, unique id?, dup risk, rights, blueprint D, logic L, verdict, reason)
A = dict
ANNOTATIONS = {
    "data/art_market.db": A(unit="auction lot / artist", region="global auctions (CN 25%, FR/GB/US/HK/CH)", period="sale_date 2013-2026 (+50,547 Poly rows with 1970-01-01 placeholder)",
        latest="sale 2026-08-20; built 2026-08-25", fields="house, price_basis, sale_date, artist_raw/key, title, lot_number, status, est_low/high, price, amount_usd, lot_url",
        url="lot_url 74%", uid="id (row); no natural key; 38 dup (house,sale,date,lot)", dup="same lots also in data/*/*.csv and global CSVs", rights="auction-house website data; redistribution not cleared",
        bp="D48,D49,D50,D51,D52", lg="L13", verdict="reference_only (P2)", reason="mixed price bases, 22 status spellings, 38% lots without artist_key, sold-without-price 23,988; usable for market context after normalisation, never for trend scores"),
    "data/global": A(unit="auction lot", region="global", period="2013-2026", latest="2026-08", fields="house, saleDate, artist, title, price, currency, lotUrl", url="lotUrl 75-100%",
        uid="lotUrl", dup="superset/duplicate of per-house CSVs and art_market.db", rights="not cleared", bp="D48-D50,D58", lg="L13", verdict="duplicate_of_art_market_db", reason="merged copies of per-house CSVs; fx_rates.json / cpi_us.json usable for P2 conversions with stated dates"),
    "data/christies": A(unit="auction lot / sale", region="global", period="2021-01..2026-07", latest="2026-07-07", fields="saleDate, lot, artist, estimate, price (hammer+premium)", url="lotUrl 100%",
        uid="lotUrl", dup="in art_market.db", rights="not cleared", bp="D49", lg="L13", verdict="reference_only (P2)", reason="raw + _normalized pairs; normalized is derived"),
    "data/bonhams": A(unit="auction lot / sale", region="global", period="2021-01..2026-08", latest="2026-08-14", fields="saleDate, artist, price (hammer)", url="lotUrl 100%", uid="lotUrl",
        dup="in art_market.db", rights="not cleared", bp="(not in Blueprint list)", lg="L13", verdict="reference_only (P2)", reason="house not in Blueprint D48-52; keep as extra market context"),
    "data/phillips": A(unit="auction lot / sale", region="global", period="2013-02..2026-07", latest="2026-07-16", fields="saleDate, artist, price", url="detailLink 100%", uid="detailLink",
        dup="in art_market.db", rights="not cleared", bp="D50", lg="L13", verdict="reference_only (P2)", reason="mixed hammer / hammer+premium rows in DB"),
    "data/poly_auction": A(unit="auction lot / sale", region="CN", period="sale dates missing (1970-01-01 placeholder in DB)", latest="2026-08-20 (some)", fields="lot, artist, startPrice, price CNY",
        url="none", uid="none", dup="in art_market.db", rights="not cleared", bp="(not in Blueprint)", lg="L13", verdict="do_not_use_for_time_series", reason="no reliable sale dates"),
    "data/artcurial": A(unit="auction lot", region="FR/MC", period="2020-12..2026-07", latest="2026-07-31", fields="saleDate, artist, price", url="lotUrl 100%", uid="lotUrl", dup="in art_market.db",
        rights="not cleared", bp="(not in Blueprint)", lg="L13", verdict="reference_only (P2)", reason="artist death year up to 6373 -> parser errors in birth/death columns"),
    "data/seoul_auction": A(unit="auction lot", region="KR", period="2026-06..07 (recent 10 sales)", latest="2026-07", fields="lot, artist, estimate, hammer", url="none", uid="sale+lot", dup="combined file duplicates by_auction files",
        rights="not cleared", bp="D51", lg="L13", verdict="reference_only (P2)", reason="only 10 recent sales; no history"),
    "data/k_auction": A(unit="auction lot", region="KR", period="2026-05..07", latest="2026-07", fields="lot, artist, estimate, price", url="none", uid="sale+lot", dup="combined = sum of by_auction",
        rights="not cleared", bp="D52", lg="L13", verdict="reference_only (P2)", reason="10 sales only"),
    "data/i_auction": A(unit="auction lot", region="KR", period="recent 10 sales", latest="2026", fields="lot, artist, price", url="none", uid="sale+lot", dup="combined = sum of by_auction",
        rights="not cleared", bp="(not in Blueprint)", lg="L13", verdict="reference_only (P2)", reason="no dates in rows"),
    "data/artnet_sothebys_london": A(unit="auction lot", region="GB", period="2024-06..2026-07", latest="2026-07", fields="artist, title, price", url="none", uid="none", dup="in art_market.db",
        rights="Artnet subscription capture; redistribution prohibited", bp="D48", lg="L13", verdict="do_not_ingest", reason="subscription-derived"),
    "data/artist_metadata": A(unit="artist", region="global", period="birth 1471-2000", latest="2026-08", fields="dbpediaUri, birth/death, nationality", url="dbpediaUri 100%", uid="dbpediaUri",
        dup="= art_market.db artists", rights="DBpedia CC BY-SA", bp="D01 (alternative)", lg="L01", verdict="reference_only", reason="nationality 90% empty; DBpedia not in Blueprint; prefer Wikidata/ULAN"),
    "data/auction_lots.jsonl": A(unit="auction lot (KR)", region="KR", period="see rows", latest="2026-08-24", fields="date, artist, artist_ko, title, hammer, sold, house", url="none", uid="key", dup="overlaps KR CSVs",
        rights="not cleared", bp="D51,D52", lg="L13", verdict="reference_only (P2)", reason="24,440 KR lots; dates present"),
    "아트랜드v2v/data/artnews.db": A(unit="news article metadata (+entities, themes, signals)", region="ko 39% / en 38% / ja 23%", period="published 2025-05..2026-10 (dense); sparse back to 2013",
        latest="published 2026-10-20; loaded 2026-10-12..20", fields="url, original_url, title, press, lang, published_at, crawl_site, flags", url="74% Google News redirect; original_url 29%",
        uid="url UNIQUE; dedupe_key (207 dup groups)", dup="same title across 1,234 multi-domain groups (syndication)", rights="titles/snippets from Google News RSS & Naver API; full text not stored; publisher rights apply",
        bp="D37 (+partial D32-D36)", lg="L05,L15,L16,L17", verdict="reuse_partially (imported 39,149 unflagged rows as legacy_v2v_artnews metadata)", reason="search-index sample, not complete media coverage; article_type (review vs news) absent; market-heavy query set"),
    "아트랜드v2v/data/artists_wikidata.json": A(unit="artist", region="global", period="n/a", latest="2026-10-19", fields="qid, birth/death, citizenship, works", url="QID", uid="QID", dup="-",
        rights="Wikidata CC0", bp="D01", lg="L01,L16", verdict="reused (legacy_v2v_wiki_artists)", reason="273 QIDs usable as identity seeds"),
    "아트랜드v2v/crawlers/raw": A(unit="raw API/RSS responses", region="ko/en/ja", period="2025-10..2026-10", latest="2026-10-20", fields="search results", url="yes", uid="per item link",
        dup="loaded into artnews.db", rights="Naver API / Google News RSS terms; internal only", bp="D37", lg="L05", verdict="archive_only", reason="already reflected in artnews.db"),
    "아트랜드v2v/ART-Global-Wiki": A(unit="Obsidian notes (artists, weekly briefs, topics)", region="global/KR", period="2025-W40..2026-W42", latest="2026-10-20", fields="frontmatter qid/birth/mentions",
        url="news.google redirects", uid="qid 86% for 2-작가", dup="generated from artnews.db", rights="internal", bp="D01 (QID seed)", lg="L15", verdict="derived_do_not_treat_as_fact", reason="auto-generated briefs/metrics; QIDs reusable"),
    "아트랜드v2v_20261020.zip": A(unit="archive", region="-", period="snapshot 2026-10-20", latest="-", fields="-", url="-", uid="-", dup="56,571/56,571 members identical to extracted folder",
        rights="-", bp="-", lg="-", verdict="duplicate_backup", reason="not counted as separate data"),
    "vault_curated.zip": A(unit="archive", region="-", period="2026-09-15", latest="-", fields="-", url="-", uid="-", dup="5,128/5,129 identical to vault_curated/", rights="-", bp="-", lg="-",
        verdict="duplicate_backup", reason="not counted separately"),
    "artrend-server_인수인계 (1).zip": A(unit="archive", region="-", period="2026-10-20", latest="-", fields="-", url="-", uid="-", dup="27/27 identical to artrend-server/", rights="-", bp="-", lg="-",
        verdict="duplicate_backup", reason="contains nested admin zip (not opened) and .env.example template"),
    "vault_curated": A(unit="Obsidian notes (artists, artworks, galleries, museums, collectors, collections)", region="global (auction-weighted)", period="2026-09-15 build", latest="2026-09-15",
        fields="frontmatter names/ids/metrics", url="0% in artist notes", uid="internal hash8", dup="spelling variants, attribution labels as artists", rights="internal",
        bp="D31 (seed names only)", lg="-", verdict="derived_do_not_treat_as_fact", reason="template notes from aggregates without provenance; collections/ (22) usable as URL seed"),
    "museums/data/moma_exhibition_history.csv": A(unit="exhibition", region="US (New York) + online", period="1929-11..2027-03", latest="collected 2026-08-25", fields="id, url, kind, title, dates, venue",
        url="100%", uid="MoMA calendar id", dup="-", rights="MoMA website content; facts only", bp="D12", lg="L03,L08,L17", verdict="reused (legacy_moma_calendar_202608)", reason="live moma.org blocked for our UA; snapshot is the only MoMA exhibition source"),
    "museums/data/moma_opendata": A(unit="artwork / artist", region="MoMA collection", period="accessions to 2026-08", latest="2026-08", fields="ObjectID, ConstituentID, QID, ULAN", url="URL partial", uid="ObjectID",
        dup="superseded by fresh GitHub download 2026-10-27", rights="CC0", bp="D03", lg="L08,L09", verdict="superseded", reason="moma_collection_github re-downloaded"),
    "museums/data/whitney_exhibition_history.csv": A(unit="exhibition", region="US", period="free-text dates to 2027", latest="2026-08-25", fields="slug, url, year, title, date_raw", url="100%", uid="slug",
        dup="overlaps live Whitney collector", rights="facts only", bp="D13", lg="L03", verdict="reused (legacy_whitney_history_202608)", reason="dates free text; parsed with precision flags"),
    "museums/data/moma_exhibition_people.csv": A(unit="exhibition x person (1929-1989)", region="US", period="1929-1989", latest="-", fields="ExhibitionID, DisplayName, role", url="partial", uid="ExhibitionID+ConstituentID",
        dup="= MoMAExhibitions1929to1989.csv", rights="CC0 (MoMA exhibitions repo)", bp="D12", lg="L08", verdict="reference_only", reason="historic only; not needed for 2025-26 cards"),
    "museums/data/museum_issues.csv": A(unit="commentary", region="KR text", period="to 2027-09", latest="2026-08", fields="issue text", url="partial", uid="-", dup="-", rights="internal",
        bp="-", lg="-", verdict="derived_do_not_treat_as_fact", reason="editorial commentary"),
    "biennale": A(unit="biennial x artist / award / edition", region="IT, KR, BR, US, JP, ...", period="2022-2025", latest="2026-09-15", fields="biennial, edition, year, artist, birth, section, link",
        url="artists: universes.art aggregator 100%; awards/editions none", uid="none", dup="-", rights="aggregator facts", bp="D16,D17,D19,D20", lg="L03,L10,L11",
        verdict="reused_with_flags (legacy_biennale_universes / legacy_biennale_awards)", reason="aggregator not official; interpretive memo columns excluded"),
    "news/data": A(unit="gallery news/exhibition items + enrichment", region="KR galleries + global mega-galleries", period="items dated 2025..2026-11", latest="snapshots 2026-08-21..25",
        fields="url, date, category, headline, text", url="100%", uid="url", dup="*_cache/_push/_enrichment are derived copies", rights="gallery website content; facts+links only",
        bp="D31,D56", lg="L04,L12", verdict="reused (legacy_gallery_news_202608, metadata only)", reason="date semantics vary; enrichment files are LLM/derived and not imported"),
    "events/data": A(unit="gallery events", region="global", period="2026-08-24 snapshot", latest="2026-08-24", fields="title, dates, url", url="H&W 11%", uid="-", dup="-", rights="-", bp="D31", lg="L04",
        verdict="stale_reference", reason="one-day snapshot"),
    "collections": A(unit="collection x artist / Leeum works", region="mixed", period="2026-09-15", latest="2026-09-15", fields="collection, artist, link", url="100% (per-artist)", uid="-", dup="-", rights="facts",
        bp="D53,D54,D55", lg="L08", verdict="context_only", reason="names not normalised; holdings lists without dates"),
    "knowledge": A(unit="report summaries / notes", region="global", period="2025-2026 reports", latest="2026-08-25", fields="markdown", url="none", uid="-", dup="summaries of Market Report PDFs", rights="internal; one file contains a personal email",
        bp="D41,D44", lg="L14", verdict="context_only", reason="cite the PDFs, not the summaries"),
    "Market Report": A(unit="market report PDF", region="global / US", period="FY2024-2025", latest="published 2025-2026", fields="PDF", url="not printed", uid="sha256", dup="AMR2026 identical to official download",
        rights="copyrighted; quote with attribution", bp="D41,D44", lg="L14", verdict="reused (legacy_local_reports)", reason="registered with hashes and page counts"),
    "Market Data(price)": A(unit="subscription screenshot PDF", region="US", period="2026-08-19 capture", latest="-", fields="lot rows", url="-", uid="-", dup="-", rights="Artnet subscription; contains account email",
        bp="D48", lg="L13", verdict="do_not_ingest", reason="licence + PII"),
    "report": A(unit="interim report deliverables", region="-", period="2026-09-15", latest="-", fields="docx/pptx/html/web_data.json", url="-", uid="-", dup="Korean-named copies identical", rights="internal",
        bp="-", lg="-", verdict="context_only", reason="web_data.json holds derived rankings; not facts"),
    "아트랜드v2v": A(unit="code / pipeline / docs", region="-", period="2026-10-12..20 runs", latest="run_log 2026-10-20 09:11", fields="python, ps1", url="-", uid="-", dup="zip snapshot", rights="internal",
        bp="D37", lg="L05,L15,L16", verdict="see code_audit", reason="Windows Task Scheduler scripts not executed"),
    "artrend-server": A(unit="Node server / collectors", region="-", period="2026-10-20..22", latest="-", fields="js, sql", url="-", uid="-", dup="zip", rights="internal", bp="-", lg="-",
        verdict="see code_audit", reason="not executed"),
    "scripts": A(unit="harvest/normalise scripts", region="-", period="2026-08..09", latest="-", fields="python", url="-", uid="-", dup="-", rights="internal", bp="D48-D52", lg="L13",
        verdict="see code_audit", reason="not executed"),
    "ARTREND_Logic_Data_Agent_Blueprint_v1_1.xlsx": A(unit="design workbook", region="-", period="v1.1 2026-10-27", latest="-", fields="24 sheets", url="official URLs per D", uid="D01-D71, L01-L17",
        dup="-", rights="internal", bp="all", lg="all", verdict="design_basis", reason="weights/thresholds are hypotheses"),
    "ARTREND_Data_Readiness_and_Crawl_Plan_v1.xlsx": A(unit="preliminary plan", region="-", period="2026-10-27", latest="-", fields="7 sheets", url="-", uid="-", dup="-", rights="internal", bp="partial", lg="-",
        verdict="superseded_by_this_audit", reason="counts-only asset review; 'usable' labels not verified"),
    "ARTREND_자문_체크리스트_v5_최신기준.xlsx": A(unit="advisory checklist", region="-", period="v5", latest="-", fields="9 sheets", url="source list", uid="-", dup="-", rights="internal", bp="partial", lg="-",
        verdict="context_only", reason="Kunstkompass 2022 sheet is a past baseline, not a current ranking"),
    "artist_signals.csv": A(unit="artist derived signals", region="global", period="2026-09-15", latest="-", fields="scores", url="-", uid="-", dup="-", rights="internal", bp="-", lg="-",
        verdict="derived_do_not_treat_as_fact", reason="built from a DB not present; unverifiable"),
    "collection_source_registry.csv": A(unit="source list", region="mixed", period="-", latest="2026-09-15", fields="name, url, tier", url="100%", uid="-", dup="= vault collections", rights="-", bp="D53-D55",
        lg="-", verdict="reuse_as_seed", reason="URL seeds"),
    "scout_source_registry.csv": A(unit="source list", region="-", period="-", latest="2026-09-15", fields="name, url", url="yes", uid="-", dup="-", rights="-", bp="D22,D31", lg="-", verdict="reuse_as_seed", reason="URL seeds"),
    "museums": A(unit="NYC museum project files", region="US (New York)", period="2026", latest="2026-08-25", fields="md/html/py", url="-", uid="-", dup="-", rights="internal",
        bp="D12,D13", lg="L03", verdict="context_only", reason="README/knowledge/content are narrative; scripts not executed"),
    "museums/raw": A(unit="raw scrape + LLM enrichment JSON (MoMA, Whitney, Guggenheim, New Museum)", region="US", period="2026 programmes", latest="2026-08-25",
        fields="exhibition/press items; enrich_* = derived", url="yes (raw)", uid="url", dup="feeds moma_exhibition_history.csv", rights="museum web content; internal",
        bp="D12,D13,D29", lg="L03", verdict="raw: reference_only; enrich_*: derived_do_not_treat_as_fact", reason="superseded by live collectors where available"),
    "museums/registry.csv": A(unit="museum source list", region="US (NYC)", period="-", latest="2026-08-25", fields="name, url, status", url="100%", uid="-", dup="-", rights="-",
        bp="D12,D13", lg="L02", verdict="reuse_as_seed", reason="26 NYC rows only"),
    "news": A(unit="gallery-news collector project", region="KR + global galleries", period="2026-08", latest="2026-08-25", fields="README, scripts, Apps Script", url="-", uid="-", dup="-",
        rights="internal", bp="D31", lg="L04", verdict="see code_audit", reason="Apps Script pushes to Google Sheets; not executed"),
    "scout_galleries_frieze_focus_2026.csv": A(unit="gallery (Frieze Seoul Focus 2026)", region="KR fair", period="2026", latest="2026-09-15", fields="gallery, city, url, founded", url="62.5%", uid="-", dup="-",
        rights="facts", bp="D22", lg="L11", verdict="reuse_as_seed", reason="Frieze site blocked live; seed list needs re-verification"),
}


def _fmt(p: Path) -> str:
    return (p.suffix.lower().lstrip(".") or "none")


def _records(p: Path):
    ext = p.suffix.lower()
    try:
        if ext in (".csv", ".tsv"):
            with p.open(encoding="utf-8", errors="replace", newline="") as f:
                return max(sum(1 for _ in csv.reader(f, delimiter="\t" if ext == ".tsv" else ",")) - 1, 0)
        if ext == ".jsonl":
            with p.open(encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        if ext == ".json" and p.stat().st_size < 50_000_000:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            return len(d) if isinstance(d, (list, dict)) else 1
        if ext in (".db", ".sqlite") and not p.name.endswith(("-wal", "-shm")):
            con = sqlite3.connect(ro_sqlite_uri(p), uri=True)
            return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if ext == ".zip":
            with zipfile.ZipFile(p) as z:
                return f"{len(z.infolist())} members"
    except Exception as e:  # unreadable files are reported, not hidden
        return f"unreadable: {type(e).__name__}"
    return None


def _sha(p: Path):
    if p.stat().st_size > 300_000_000:
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _annot(rel: str):
    best = None
    for k in ANNOTATIONS:
        if rel == k or rel.startswith(k + "/"):
            if best is None or len(k) > len(best):
                best = k
    return (best, ANNOTATIONS[best]) if best else (None, {})


def main():
    rows, groups = [], {}
    nfc_bulk = [unicodedata.normalize("NFC", b) for b in BULK_DIRS]
    for dirpath, dirnames, filenames in os.walk(ARTRENDATA):
        d = Path(dirpath)
        if d == WORK_ROOT or WORK_ROOT in d.parents:
            dirnames[:] = []
            continue
        for fn in filenames:
            p = d / fn
            rel = unicodedata.normalize("NFC", str(p.relative_to(ARTRENDATA)))
            if fn == ".DS_Store":
                continue
            st = p.stat()
            bulk = next((b for b in nfc_bulk if rel.startswith(b + "/")), None)
            if bulk:
                g = groups.setdefault(bulk, {"files": 0, "bytes": 0, "formats": Counter(), "mtime_min": st.st_mtime, "mtime_max": st.st_mtime})
                g["files"] += 1
                g["bytes"] += st.st_size
                g["formats"][_fmt(p)] += 1
                g["mtime_min"], g["mtime_max"] = min(g["mtime_min"], st.st_mtime), max(g["mtime_max"], st.st_mtime)
                continue
            key, ann = _annot(rel)
            rows.append({"path": rel, "level": "file", "format": _fmt(p), "bytes": st.st_size,
                         "mtime(not freshness)": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                         "sha256": _sha(p), "records": _records(p), "annotation_key": key, **ann})
    for b, g in groups.items():
        key, ann = _annot(b)
        rows.append({"path": b + "/", "level": f"group({g['files']} files)", "format": dict(g["formats"].most_common(4)), "bytes": g["bytes"],
                     "mtime(not freshness)": f"{dt.datetime.fromtimestamp(g['mtime_min']).date()}..{dt.datetime.fromtimestamp(g['mtime_max']).date()}",
                     "sha256": None, "records": g["files"], "annotation_key": key, **ann})
    rows.sort(key=lambda r: r["path"])
    out = AUDIT_ROOT / "inventory.json"
    out.write_text(json.dumps({"generated_at": iso_now(), "root": str(ARTRENDATA), "rows": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(out, len(rows), "rows")


if __name__ == "__main__":
    main()
