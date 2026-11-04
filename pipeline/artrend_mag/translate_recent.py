"""Translate the recent window first: new articles/events and records made by an older pipeline version.

The daily run calls this before the bounded catch-up pass so today's titles never wait behind old backlog.
Usage: python -m artrend_mag.translate_recent [YYYY-MM-DD]  (default: 7 days ago)
"""
import datetime as dt
import sqlite3
import sys
import time

from . import translation as T
from .config import DB_PATH

since = sys.argv[1] if len(sys.argv) > 1 else (dt.date.today() - dt.timedelta(days=7)).isoformat()
con = sqlite3.connect(str(DB_PATH))
con.row_factory = sqlite3.Row
backend = T.LocalTranslationBackend()
rows = con.execute("""
    SELECT 'articles' AS source_table, a.article_id AS source_key, f.field AS source_field,
           CASE f.field WHEN 'title' THEN a.title ELSE a.excerpt END AS original_text, a.lang AS source_lang
      FROM articles a CROSS JOIN (SELECT 'title' AS field UNION ALL SELECT 'excerpt') f
      LEFT JOIN metadata_translations t ON t.source_table='articles' AND t.source_key=a.article_id AND t.source_field=f.field
     WHERE a.published_at >= ? AND (CASE f.field WHEN 'title' THEN a.title ELSE a.excerpt END) IS NOT NULL
       AND (t.source_key IS NULL OR (t.source_lang NOT IN ('en','ko') AND t.model_version NOT LIKE ?))
    UNION ALL
    SELECT 'events', e.event_id, 'title', e.title, NULL
      FROM events e LEFT JOIN metadata_translations t ON t.source_table='events' AND t.source_key=e.event_id AND t.source_field='title'
     WHERE COALESCE(e.end_date, e.start_date) >= ? AND e.title IS NOT NULL
       AND (t.source_key IS NULL OR (t.source_lang NOT IN ('en','ko') AND t.model_version NOT LIKE ?))
""", (since, "%" + T.PIVOT_PREP_VERSION, since, "%" + T.PIVOT_PREP_VERSION)).fetchall()
print("candidates", len(rows), flush=True)
t0, stats, cache = time.time(), {}, {}
for i in range(0, len(rows), 64):
    batch = [r for r in rows[i:i + 64] if r["original_text"]]
    cands = [T.Candidate(source_table=r["source_table"], source_key=str(r["source_key"]), source_field=r["source_field"],
                         original_text=r["original_text"], source_lang=r["source_lang"]) for r in batch]
    decs = [T.detect_language(r["original_text"], r["source_lang"]) for r in batch]
    for o in T._process_candidates(con, cands, backend, None, decs, cache):
        stats[o] = stats.get(o, 0) + 1
    con.commit()
print(stats, f"{time.time() - t0:.0f}s", flush=True)
