from __future__ import annotations

import hashlib
import sqlite3
import unittest

from artrend_mag import db, runner
from artrend_mag.sources import wave2_critics as w

AICA_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://www.rssboard.org/media-rss" version="2.0"><channel><title>AGORA - AICA International</title><link>https://aicainternational.news/agora/</link><item><title>Open Call for Webinar Proposals </title><dc:creator>AICA International</dc:creator><pubDate>Fri, 23 Oct 2026 16:44:57 +0000</pubDate><link>https://aicainternational.news/agora/2026/10/23/open-call-for-webinar-proposals</link><guid isPermaLink="false">58d3ea4f:6adb889c</guid><description>&lt;p&gt;Dear Members, body text must not be stored&lt;/p&gt;</description></item><item><title>AICA E-MAG NO. 20 IS HERE!  </title><dc:creator>AICA International</dc:creator><pubDate>Wed, 18 Mar 2026 20:22:28 +0000</pubDate><link>https://aicainternational.news/agora/2026/3/18/aica-e-mag-no-20</link><guid isPermaLink="false">x</guid></item></channel></rss>"""

AICA_FEED_OLD = AICA_FEED.replace("2026 16:44:57", "2022 16:44:57").replace("Mar 2026", "Mar 2022").replace("/2026/", "/2022/")

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.afterall.org/wp-sitemap-posts-page-1.xml</loc></sitemap><sitemap><loc>https://www.afterall.org/wp-sitemap-posts-article-1.xml</loc></sitemap><sitemap><loc>https://www.afterall.org/wp-sitemap-posts-event-1.xml</loc></sitemap></sitemapindex>"""
SITEMAP_ARTICLES = """<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://www.afterall.org/articles/foreword-afterall-journal-issue-53/</loc><lastmod>2023-07-11T16:59:16+01:00</lastmod></url><url><loc>https://www.afterall.org/articles/unboxing-gaza/</loc><lastmod>2025-06-14T15:06:50+01:00</lastmod></url><url><loc>https://www.afterall.org/articles/reading-list-audible-matter/</loc><lastmod>2026-09-14T12:02:33+01:00</lastmod></url></urlset>"""

def _page(title, metadata):
    return f"""<html><body><main><div class="row"><div class="wrapper"><div class="hero-article"><div class="columns-50-50__column"><div class="hero-article__title-wrapper">
<h1 class="type-a hero-article__title">
\t\t\t\t\t\t\t{title}
\t\t\t\t\t\t</h1></div></div></div></div></div><div class="row"><div class="metadata"><div class="wrapper"><div class="metadata__content">{metadata}</div></div></div></div>
<div class="intro-block type-o">Body text must not be stored.</div></main></body></html>"""

PAGE_ESSAY = _page("Unboxing Gaza", """<div class="metadata__column"><p class="type-n">
<a href="/articles/?article-type=essay">Essay</a>
<span class="u-block">
\tPublish date:
\t<span>24 sep 2024</span>
</span></p></div><div class="metadata__column"><p class="type-n">
\tWritten by Kegham Djeghalian
</p></div><div class="metadata__column"><p class="type-n">This article is part of <a href="/publications/issue-57/">Afterall Issue 57</a></p></div>""")
PAGE_REVIEW = _page("‘Lethal Love’ at Cubitt Gallery", """<div class="metadata__column"><p class="type-n">
<a href="/articles/?article-type=exhibition">Exhibition</a><span>, </span><a href="/articles/?article-type=review">Review</a>
<span class="u-block">Publish date: <span>14 apr 2008</span></span></p></div><div class="metadata__column"><p class="type-n">
Written by Andrew Bonacina.
</p></div>""")
PAGE_NO_AUTHOR = _page("Reading List: Audible Matter", """<div class="metadata__column"><p class="type-n">
<a href="/articles/?article-type=reading-list">Reading List</a>
<span class="u-block">Publish date: <span>18 jul 2025</span></span></p></div>""")


class Resp:
    def __init__(self, url, body):
        self.url = self.final_url = url
        self.status = 200
        self.content = body.encode("utf-8")
        self.text = body
        self.fetched_at = "2026-10-28T09:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None


class Ctx:
    def __init__(self, con, source_id, pages, mode="initial"):
        self.con, self.source_id, self.mode, self.pages = con, source_id, mode, pages
        self.meta = next(r for r in w.SOURCES if r["source_id"] == source_id)
        self.parser_version = w.PARSER_VERSION
        self.stats, self.notes, self.calls = {}, [], []

    def fetch(self, url, params=None, **kw):
        full = url if not params else url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        self.calls.append(full)
        if full not in self.pages:
            raise AssertionError(f"unexpected fetch {full}")
        return Resp(full, self.pages[full])

    def evidence(self, *a, **k):
        return None

    def note(self, m):
        self.notes.append(m)

    def count(self, k, n=1):
        self.stats[k] = self.stats.get(k, 0) + n


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    for r in w.SOURCES:
        meta = {k: v for k, v in r.items() if k != "source_id" and k in db.SOURCE_FIELDS + db.STATUS_FIELDS}
        db.upsert_source(con, r["source_id"], **meta)
    con.commit()
    return con


class RegistryTest(unittest.TestCase):
    def test_unique_ids_and_disabled_rows_are_truthful(self):
        ids = [r["source_id"] for r in w.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        for r in w.SOURCES:
            self.assertIsNone(r["blueprint_data_id"])
            self.assertEqual(r["text_storage_policy"], "metadata_only")
            if r.get("disabled"):
                for k in ("operational_state", "robots_status", "st_live_response"):
                    self.assertTrue(r.get(k), (r["source_id"], k))
        self.assertEqual({r["source_id"] for r in w.SOURCES if not r.get("disabled")}, {"aica_agora_feed", "afterall_articles"})

    def test_no_duplicate_ids_in_discovered_registry(self):
        found = runner.discover()
        for r in w.SOURCES:
            self.assertIs(found[r["source_id"]][0], w)


class ParserTest(unittest.TestCase):
    def test_aica_feed(self):
        items = w.parse_aica_feed(AICA_FEED.encode())
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Open Call for Webinar Proposals")
        self.assertEqual(items[0]["author"], "AICA International")
        self.assertTrue(items[0]["published"].startswith("2026-10-23T16:44:57"))

    def test_afterall_dates(self):
        self.assertEqual(w.parse_afterall_date("13 apr 2022"), "2022-04-13")
        self.assertEqual(w.parse_afterall_date("2022"), None)
        self.assertEqual(w.parse_afterall_date("31 xyz 2022"), None)

    def test_afterall_article_variants(self):
        p = w.parse_afterall_article(PAGE_ESSAY)
        self.assertEqual((p["title"], p["published"], p["author"], p["categories"]),
                         ("Unboxing Gaza", "2024-09-24", "Kegham Djeghalian", ["Essay"]))
        p = w.parse_afterall_article(PAGE_REVIEW)
        self.assertEqual(p["author"], "Andrew Bonacina.")  # verbatim, trailing period kept
        self.assertEqual(p["categories"], ["Exhibition", "Review"])
        self.assertEqual(p["published"], "2008-04-14")
        p = w.parse_afterall_article(PAGE_NO_AUTHOR)
        self.assertIsNone(p["author"])
        self.assertEqual(p["published"], "2025-07-18")

    def test_afterall_type(self):
        self.assertEqual(w.afterall_type(["Exhibition", "Review"])[0], "review")
        self.assertEqual(w.afterall_type(["Essay"])[0], "criticism")
        self.assertEqual(w.afterall_type(["Reading List"]), ("unknown", None))

    def test_sitemap(self):
        self.assertEqual(len(w.parse_sitemap(SITEMAP_INDEX.encode())), 3)
        self.assertEqual(w.parse_sitemap(SITEMAP_ARTICLES.encode())[1],
                         ("https://www.afterall.org/articles/unboxing-gaza/", "2025-06-14T15:06:50+01:00"))


class CollectTest(unittest.TestCase):
    def test_aica_collect_and_rerun(self):
        con = _con()
        entry = "https://aicainternational.news/agora"
        pages = {entry + "?format=rss": AICA_FEED}
        # oldest 2026-03-18T20:22:28Z -> epoch ms
        pages[entry + "?format=rss&offset=1773865348000"] = AICA_FEED_OLD
        ctx = Ctx(con, "aica_agora_feed", pages)
        w.collect(ctx)
        self.assertEqual(ctx.stats["parsed"], 4)
        self.assertEqual(ctx.stats["inserted"], 4)
        rows = con.execute("SELECT * FROM articles WHERE source_id='aica_agora_feed'").fetchall()
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertIsNone(r["excerpt"])
            self.assertEqual(r["author_text"], "AICA International")
        ctx2 = Ctx(con, "aica_agora_feed", pages, mode="incremental")
        w.collect(ctx2)
        self.assertEqual(ctx2.stats.get("inserted", 0), 0)
        self.assertEqual(ctx2.stats["unchanged"], 2)
        self.assertEqual(len(ctx2.calls), 1)

    def test_afterall_collect(self):
        con = _con()
        base = "https://www.afterall.org/"
        pages = {
            base + "wp-sitemap.xml": SITEMAP_INDEX,
            base + "wp-sitemap-posts-article-1.xml": SITEMAP_ARTICLES,
            base + "articles/unboxing-gaza/": PAGE_ESSAY,
            base + "articles/foreword-afterall-journal-issue-53/": PAGE_REVIEW,
            base + "articles/reading-list-audible-matter/": PAGE_NO_AUTHOR,
        }
        ctx = Ctx(con, "afterall_articles", pages)
        w.collect(ctx)
        self.assertEqual(ctx.stats["parsed"], 3)
        self.assertEqual(ctx.stats["fetched"], 3)
        self.assertNotIn(base + "wp-sitemap-posts-event-1.xml", ctx.calls)
        r = con.execute("SELECT * FROM articles WHERE canonical_url=?", (base + "articles/unboxing-gaza/",)).fetchone()
        self.assertEqual((r["title"], r["author_text"], r["published_at"], r["article_type"], r["categories"]),
                         ("Unboxing Gaza", "Kegham Djeghalian", "2024-09-24", "criticism", "Essay"))
        self.assertEqual(r["modified_at"], "2025-06-14T15:06:50+01:00")
        self.assertIsNone(r["excerpt"])
        n = len(ctx.calls)
        ctx2 = Ctx(con, "afterall_articles", pages, mode="incremental")
        w.collect(ctx2)
        self.assertEqual(ctx2.stats.get("parsed", 0), 0)  # all known: only sitemaps re-read
        self.assertEqual(len(ctx2.calls), 2)
        self.assertEqual(n, 5)


if __name__ == "__main__":
    unittest.main()
