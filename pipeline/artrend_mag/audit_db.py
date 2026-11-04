"""Read-only quality audit of legacy SQLite databases and large CSV/JSONL assets.

Writes work/audit/db_audit.json. Every statistic here is computed over the full
population unless the key name contains "sample".
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from .config import ARTRENDATA, AUDIT_ROOT, iso_now, ro_sqlite_uri, v2v_root

csv.field_size_limit(sys.maxsize)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def q(con, sql, *args):
    return con.execute(sql, args).fetchall()


def table_profile(con, table):
    cols = [r[1] for r in q(con, f'PRAGMA table_info("{table}")')]
    n = q(con, f'SELECT COUNT(*) FROM "{table}"')[0][0]
    nulls = {}
    for c in cols:
        empty = q(con, f'SELECT COUNT(*) FROM "{table}" WHERE "{c}" IS NULL OR TRIM(CAST("{c}" AS TEXT))=\'\'')[0][0]
        nulls[c] = round(empty / n, 4) if n else None
    pk = [r[1] for r in q(con, f'PRAGMA table_info("{table}")') if r[5]]
    return {"rows": n, "columns": cols, "primary_key": pk, "null_or_empty_rate": nulls}


def audit_art_market(path: Path):
    con = sqlite3.connect(ro_sqlite_uri(path), uri=True)
    out = {"path": str(path.relative_to(ARTRENDATA)), "tables": {}}
    for t in ("artists", "lots"):
        out["tables"][t] = table_profile(con, t)
    c = {}
    c["lots_by_house_basis"] = q(con, "SELECT house, price_basis, COUNT(*), MIN(sale_date), MAX(sale_date) FROM lots GROUP BY 1,2 ORDER BY 3 DESC")
    c["lots_status_values"] = q(con, "SELECT status, COUNT(*) FROM lots GROUP BY 1 ORDER BY 2 DESC")
    c["lots_currency_values"] = q(con, "SELECT currency, COUNT(*) FROM lots GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
    c["lots_location_top"] = q(con, "SELECT location, COUNT(*) FROM lots GROUP BY 1 ORDER BY 2 DESC LIMIT 25")
    c["lots_sale_year"] = q(con, "SELECT sale_year, COUNT(*) FROM lots GROUP BY 1 ORDER BY 1")
    c["lots_bad_dates"] = q(con, "SELECT COUNT(*) FROM lots WHERE sale_date IS NULL OR sale_date NOT GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]*' OR sale_date > '2026-10-27'")[0][0]
    c["lots_future_dated"] = q(con, "SELECT COUNT(*) FROM lots WHERE sale_date > '2026-10-27'")[0][0]
    c["lots_url_rate"] = q(con, "SELECT ROUND(AVG(lot_url LIKE 'http%'),4) FROM lots")[0][0]
    c["lots_dup_house_url"] = q(con, "SELECT COUNT(*) FROM (SELECT lot_url FROM lots WHERE lot_url LIKE 'http%' GROUP BY lot_url HAVING COUNT(*)>1)")[0][0]
    c["lots_dup_house_sale_lot"] = q(con, "SELECT COUNT(*) FROM (SELECT house, sale_name, sale_date, lot_number FROM lots GROUP BY 1,2,3,4 HAVING COUNT(*)>1)")[0][0]
    c["lots_artist_key_rate"] = q(con, "SELECT ROUND(AVG(artist_key IS NOT NULL AND artist_key<>''),4) FROM lots")[0][0]
    c["lots_artist_key_in_artists"] = q(con, "SELECT ROUND(AVG(a.artist_key IS NOT NULL),4) FROM lots l LEFT JOIN artists a ON a.artist_key=l.artist_key WHERE l.artist_key IS NOT NULL AND l.artist_key<>''")[0][0]
    c["lots_price_null_when_sold"] = q(con, "SELECT COUNT(*) FROM lots WHERE LOWER(status) IN ('sold') AND price IS NULL")[0][0]
    c["artists_nationality_top"] = q(con, "SELECT nationality, COUNT(*) FROM artists GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
    c["artists_birth_year_range"] = q(con, "SELECT MIN(birth_year), MAX(birth_year), SUM(birth_year IS NULL) FROM artists")
    c["artists_dbpedia_rate"] = q(con, "SELECT ROUND(AVG(dbpedia_uri LIKE 'http%'),4) FROM artists")[0][0]
    c["sample_lots"] = q(con, "SELECT house, price_basis, sale_date, sale_name, location, currency, artist_raw, artist_key, title, lot_number, status, est_low, est_high, price, lot_url FROM lots ORDER BY RANDOM() LIMIT 5")
    c["sample_artists"] = q(con, "SELECT * FROM artists ORDER BY RANDOM() LIMIT 5")
    out["checks"] = c
    return out


def audit_artnews(path: Path):
    con = sqlite3.connect(ro_sqlite_uri(path), uri=True)
    tables = [r[0] for r in q(con, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    out = {"path": "아트랜드v2v/data/artnews.db", "tables": {t: table_profile(con, t) for t in tables}}
    c = {}
    c["articles_by_crawl_site"] = q(con, "SELECT crawl_site, COUNT(*), MIN(published_date), MAX(published_date), MIN(first_seen), MAX(first_seen) FROM articles GROUP BY 1 ORDER BY 2 DESC")
    c["articles_by_lang"] = q(con, "SELECT lang, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC")
    c["articles_by_year"] = q(con, "SELECT SUBSTR(published_date,1,4), COUNT(*) FROM articles GROUP BY 1 ORDER BY 1")
    c["articles_last_180d_by_month"] = q(con, "SELECT SUBSTR(published_date,1,7), COUNT(*) FROM articles WHERE published_date >= '2026-04-30' GROUP BY 1 ORDER BY 1")
    c["articles_future_dated"] = q(con, "SELECT COUNT(*) FROM articles WHERE published_date > '2026-10-27'")[0][0]
    c["articles_url_google_redirect"] = q(con, "SELECT COUNT(*) FROM articles WHERE url LIKE 'https://news.google.com/%'")[0][0]
    c["articles_original_url_present"] = q(con, "SELECT COUNT(*) FROM articles WHERE original_url LIKE 'http%'")[0][0]
    c["articles_publisher_url_resolvable"] = q(con, "SELECT COUNT(*) FROM articles WHERE (url NOT LIKE 'https://news.google.com/%') OR original_url LIKE 'http%'")[0][0]
    c["articles_noise_flags"] = q(con, "SELECT is_noise, flagged_mismatch, keep_manual, COUNT(*) FROM articles GROUP BY 1,2,3")
    c["articles_flag_reason_top"] = q(con, "SELECT flag_reason, COUNT(*) FROM articles WHERE flagged_mismatch=1 GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
    c["articles_dedupe_key_dups"] = q(con, "SELECT COUNT(*), SUM(n) FROM (SELECT dedupe_key, COUNT(*) n FROM articles WHERE dedupe_key IS NOT NULL GROUP BY 1 HAVING n>1)")[0]
    c["articles_title_press_date_dups"] = q(con, "SELECT COUNT(*), SUM(n) FROM (SELECT LOWER(TRIM(title)) t, press_domain, published_date, COUNT(*) n FROM articles GROUP BY 1,2,3 HAVING n>1)")[0]
    c["articles_same_title_multi_domain"] = q(con, "SELECT COUNT(*) FROM (SELECT LOWER(TRIM(title)) t, COUNT(DISTINCT press_domain) d FROM articles GROUP BY 1 HAVING d>1)")[0][0]
    c["articles_press_domain_top"] = q(con, "SELECT press_domain, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC LIMIT 40")
    c["articles_distinct_press_domain"] = q(con, "SELECT COUNT(DISTINCT press_domain) FROM articles")[0][0]
    c["articles_summary_rate"] = q(con, "SELECT ROUND(AVG(summary IS NOT NULL AND LENGTH(summary)>20),4) FROM articles")[0][0]
    c["articles_query_entity_top"] = q(con, "SELECT query_entity, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC LIMIT 25")
    c["entities_by_role"] = q(con, "SELECT role, COUNT(*), COUNT(DISTINCT entity_id) FROM article_entities GROUP BY 1")
    c["entities_top"] = q(con, "SELECT entity_id, role, COUNT(*) FROM article_entities GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40")
    c["entities_orphan_article"] = q(con, "SELECT COUNT(*) FROM article_entities ae LEFT JOIN articles a ON a.id=ae.article_id WHERE a.id IS NULL")[0][0]
    c["themes_dist"] = q(con, "SELECT theme_id, COUNT(*) FROM article_themes GROUP BY 1 ORDER BY 2 DESC")
    c["themes_orphan_article"] = q(con, "SELECT COUNT(*) FROM article_themes t LEFT JOIN articles a ON a.id=t.article_id WHERE a.id IS NULL")[0][0]
    c["signals"] = q(con, "SELECT category, COUNT(*), MIN(signal_date), MAX(signal_date), SUM(demoted), ROUND(AVG(url LIKE 'http%'),2) FROM signals GROUP BY 1")
    c["signals_sample"] = q(con, "SELECT entity_id, signal_date, category, headline, url FROM signals ORDER BY RANDOM() LIMIT 5")
    c["run_log_last_by_stage"] = q(con, "SELECT stage, MAX(started_at), SUM(ok=1), SUM(ok=0) FROM run_log GROUP BY 1 ORDER BY 2 DESC")
    c["run_log_failures_recent"] = q(con, "SELECT stage, started_at, SUBSTR(note,1,160) FROM run_log WHERE ok=0 ORDER BY started_at DESC LIMIT 10")
    c["disclosures_range"] = q(con, "SELECT COUNT(*), MIN(rcept_dt), MAX(rcept_dt), COUNT(DISTINCT entity_id) FROM disclosures")[0]
    c["ext_summaries_sources"] = q(con, "SELECT source, COUNT(*), MIN(sheet_published), MAX(sheet_published) FROM ext_summaries GROUP BY 1")
    c["sample_articles"] = q(con, "SELECT id, url, original_url, title, press, press_domain, lang, published_at, first_seen, crawl_site, query_entity, flagged_mismatch, flag_reason FROM articles WHERE published_date>='2026-07-01' ORDER BY RANDOM() LIMIT 8")
    out["checks"] = c
    return out


def profile_csv(path: Path, date_cols_hint=("date", "sale_date", "start", "end", "published", "year")):
    n = 0
    header = None
    url_cnt = Counter()
    nonempty = Counter()
    date_min, date_max = {}, {}
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        header = next(r, [])
        dcols = [i for i, h in enumerate(header) if any(k in h.lower() for k in date_cols_hint)]
        for row in r:
            n += 1
            for i, v in enumerate(row[: len(header)]):
                if v.strip():
                    nonempty[header[i]] += 1
                    if v.startswith("http"):
                        url_cnt[header[i]] += 1
            for i in dcols:
                if i < len(row):
                    m = DATE_RE.match(row[i].strip()) or (re.match(r"^(\d{4})$", row[i].strip()))
                    if m:
                        v = row[i].strip()[:10]
                        h = header[i]
                        date_min[h] = min(date_min.get(h, v), v)
                        date_max[h] = max(date_max.get(h, v), v)
    return {
        "path": str(path.relative_to(ARTRENDATA)),
        "rows": n,
        "columns": header,
        "fill_rate": {h: round(nonempty[h] / n, 4) if n else None for h in header},
        "url_columns": {h: round(url_cnt[h] / n, 4) for h in url_cnt},
        "date_range": {h: [date_min[h], date_max[h]] for h in date_min},
    }


def main():
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    result = {"generated_at": iso_now(), "scope": "full population unless key contains 'sample'"}
    result["art_market_db"] = audit_art_market(ARTRENDATA / "data" / "art_market.db")
    result["artnews_db"] = audit_artnews(v2v_root() / "data" / "artnews.db")
    csvs = sorted((ARTRENDATA / "data").rglob("*.csv"))
    result["data_csvs"] = [profile_csv(p) for p in csvs]
    jl = ARTRENDATA / "data" / "auction_lots.jsonl"
    if jl.exists():
        n, keys = 0, Counter()
        with jl.open(encoding="utf-8") as f:
            for line in f:
                n += 1
                try:
                    keys.update(json.loads(line).keys())
                except json.JSONDecodeError:
                    keys["__bad_json__"] += 1
        result["auction_lots_jsonl"] = {"rows": n, "key_counts": dict(keys)}
    out = AUDIT_ROOT / "db_audit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
