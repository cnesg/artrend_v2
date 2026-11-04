from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from artrend_mag import db, runner
from artrend_mag.sources import gl_media, wave2_media as w


ARTISHOCK_FEED = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Artishock Revista</title><language>es</language>
<item><title>BOCAS DE AGUA</title><link>https://artishockrevista.com/2026/10/27/bocas-de-agua/</link>
<dc:creator><![CDATA[Alejandra Villasmil]]></dc:creator><pubDate>Tue, 27 Oct 2026 19:37:50 +0000</pubDate>
<category><![CDATA[Artículos]]></category><category><![CDATA[Intersecciones]]></category>
<guid isPermaLink="false">https://artishockrevista.com/?p=129443</guid>
<description><![CDATA[Description text must not be stored.]]></description>
<content:encoded><![CDATA[Article body must not be stored.]]></content:encoded></item>
</channel></rss>'''.encode("utf-8")

ARTISHOCK_OLD_FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Artishock Revista</title><language>es</language>
<item><title>Archivo anterior</title><link>https://artishockrevista.com/2025/03/01/archivo-anterior/</link>
<dc:creator><![CDATA[Artishock Revista]]></dc:creator><pubDate>Sat, 01 Mar 2025 09:00:00 +0000</pubDate>
<category><![CDATA[Noticias]]></category><description><![CDATA[Not stored.]]></description></item>
</channel></rss>'''

ARTMONTHLY_LISTING = '''<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><body id="articles">
<div class="content-item">
  <div class="grid_1 margin-bottom alpha">
    <a href="https://www.artmonthly.co.uk/magazine/site/article/deep-cuts-by-isobel-harbison-october-2026" class="image-link box-shadow"><img alt="Art Monthly 500 October 2026" /></a>
  </div>
  <div class="grid_4 margin-bottom omega"><h3>Deep Cuts</h3><p class="tight">Synopsis must not be stored.</p></div>
  <div class="clear"></div>
  <div class="grid_1 margin-bottom alpha">
    <a href="https://www.artmonthly.co.uk/magazine/site/article/ana-mendieta-by-bryony-white-september-2026" class="image-link box-shadow"><img alt="Art Monthly 499 September 2026" /></a>
  </div>
  <div class="grid_4 margin-bottom omega"><h3>Ana Mendieta</h3><p class="tight">Synopsis must not be stored.</p></div>
</div></body></html>'''

MOUSSE_FEED = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Mousse Magazine</title><language>en-US</language>
<item><title>“Outlaws” at Istituto Svizzero, Rome</title>
<link>https://www.moussemagazine.it/magazine/outlaws-istituto-svizzero-rome-2026</link>
<dc:creator>Mousse Magazine</dc:creator><pubDate>Tue, 27 Oct 2026 13:39:13 +0000</pubDate>
<category>Exhibitions</category><description>Feed summary is not stored.</description></item>
</channel></rss>'''.encode("utf-8")

MONOPOL_FEED = '''<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel><title>Monopol - Magazin für Kunst und Leben</title><language>de</language>
<item><title>Is Gen Z in the tent with us right now?</title>
<link>https://www.monopol-magazin.de/en/gen-z-tent-us-right-now</link>
<description>&lt;span&gt;Embedded creation markup must not become stored article metadata.&lt;/span&gt;
&lt;time datetime="2026-10-21T15:23:00+02:00"&gt;Wed, 10/21/2026 - 15:23&lt;/time&gt;</description>
<pubDate>Mon, 19 Oct 2026 06:56:19 +0000</pubDate><dc:creator>Kate Brown</dc:creator>
<guid isPermaLink="false">37408 at https://www.monopol-magazin.de</guid></item>
</channel></rss>'''.encode("utf-8")

CMAGAZINE_HOME = '''<!doctype html><html lang="en"><body>
<div class="MuiBox-root css-1r3oyis">
  <div class="MuiBox-root css-153aal4"><p>Review</p></div>
  <a href="/articles/starmirror-holly-herndon-and-mat-dryhurst?utm_source=home">
    <div><h3>“Starmirror” — Holly Herndon and Mat Dryhurst</h3>
      <div><span>by</span><span>Jayne Wilkinson</span></div>
    </div>
  </a>
  <p>Card synopsis must not persist.</p>
</div>
<div class="MuiBox-root css-1r3oyis">
  <div class="MuiBox-root css-153aal4"><p>Feature</p></div>
  <a href="/articles/open-hearing-dreaming-in-dark-times-dispatch-iii">
    <div><h3>Open Hearing: Dreaming in Dark Times, Dispatch III</h3><div></div></div>
  </a>
</div>
</body></html>'''

CANADIAN_ART_NEWS = '''<!doctype html><html lang="en-US"><body>
<div class="copy-container copy-left">
  <div class="article-meta"><p>October 4, 2021</p></div>
  <h3><a href="https://canadianart.ca/news/statement-from-the-canadian-art-foundation-board-of-directors/?utm_source=listing">Statement from the Canadian Art Foundation Board of Directors</a></h3>
  <p class="synopsis">News synopsis must not persist.</p>
</div>
<div class="copy-container copy-left">
  <h3><a href="https://canadianart.ca/news/new-report/">OCAD U Accountability Examined in New Report</a></h3>
  <p class="synopsis">Unknown-date synopsis must not persist.</p>
</div>
<div class="copy-container copy-left"><h3><a href="https://outside.example/news/foreign/">External card</a></h3></div>
</body></html>'''

CANADIAN_ART_ESSAYS = '''<!doctype html><html lang="en-US"><body>
<div class="copy-container copy-left">
  <div class="article-meta"><p>March 30, 2021</p></div>
  <h3><a href="https://canadianart.ca/essays/dancemakers/">On the Life and Death (and Life) of Dancemakers</a></h3>
</div>
</body></html>'''

CANADIAN_ART_REVIEWS = '''<!doctype html><html lang="en-US"><body>
<div class="copy-container copy-left">
  <div class="article-meta"><p>March 11, 2021</p></div>
  <h3><a href="https://canadianart.ca/reviews/charles-campbell/">On Charles Campbell and the Underrepresentation of Caribbean Art in Canada</a></h3>
</div>
</body></html>'''

BEAUXARTS_NEWS_SITEMAP = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
 xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url><loc>https://www.beauxarts.com/expos/gustave-fayet-mary-cassatt-paris/</loc>
    <lastmod>2026-10-28T06:05:04+01:00</lastmod>
    <news:news><news:publication><news:name>Beaux Arts</news:name><news:language>fr</news:language></news:publication>
      <news:publication_date>2026-10-28T06:00:17+01:00</news:publication_date>
      <news:title>Gustave Fayet, Mary Cassatt, Warhol, Tintoret… Que valent les grandes expos du moment à Paris ?</news:title>
      <news:keywords>Art moderne, Musée de Montmartre</news:keywords>
    </news:news>
    <image:image><image:loc>https://media.beauxarts.com/uploads/2026/10/not-to-download.jpg</image:loc></image:image>
  </url>
  <url><loc>https://www.beauxarts.com/grand-format/army-of-terracotta/</loc>
    <lastmod>2026-10-27T14:49:00+01:00</lastmod>
    <news:news><news:publication><news:name>Beaux Arts</news:name><news:language>fr</news:language></news:publication>
      <news:title>L’armée de terre cuite de Xi’an</news:title><news:keywords></news:keywords>
    </news:news>
  </url>
  <url><loc>https://www.beauxarts.com/not-news/ignored/</loc><lastmod>2026-10-27T00:00:00+01:00</lastmod></url>
</urlset>'''.encode("utf-8")


def _rss_page(title, url, published=None):
    pub_date = "<pubDate>{}</pubDate>".format(published) if published else ""
    return ('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Fixture arts feed</title><language>en</language>
<item><title>{}</title><link>{}</link>{}</item></channel></rss>'''.format(
        title, url, pub_date,
    )).encode("utf-8")


class Response:
    def __init__(self, url, content):
        self.url = self.final_url = url
        self.status = 200
        self.content = content
        self.text = content.decode("utf-8")
        self.fetched_at = "2026-10-28T09:00:00+09:00"
        self.sha256 = hashlib.sha256(content).hexdigest()
        self.raw_path = None


class OfflineFetcher:
    def __init__(self, source_id, run_stamp, store_raw, stats, pages, **kwargs):
        self.source_id = source_id
        self.store_raw = store_raw
        self.stats = stats
        self.pages = pages
        self.calls = []
        self._robots_state = {"fixture.invalid": "offline_fixture"}

    def get(self, url, params=None, **kwargs):
        if params:
            url += "?" + urlencode(params)
        self.calls.append((url, kwargs))
        if url not in self.pages:
            raise AssertionError("unexpected offline fetch: " + url)
        self.stats["http_requests"] = self.stats.get("http_requests", 0) + 1
        self.stats["last_http_status"] = 200
        return Response(url, self.pages[url])


class Context:
    def __init__(self, con, source_id, pages, mode="initial"):
        self.con = con
        self.source_id = source_id
        self.mode = mode
        self.meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
        self.pages = pages
        self.stats = {}
        self.notes = []
        self.calls = []

    def fetch(self, url, params=None, **kwargs):
        if params:
            from urllib.parse import urlencode
            url = url + "?" + urlencode(params)
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError("unexpected fetch: " + url)
        return Response(url, self.pages[url])

    def note(self, message):
        self.notes.append(message)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    for row in w.SOURCES:
        meta = {key: value for key, value in row.items()
                if key in db.SOURCE_FIELDS + db.STATUS_FIELDS}
        db.upsert_source(con, row["source_id"], **meta)
    con.commit()
    return con


def _run_offline(con, source_id, pages, *, mode="initial", run_suffix="first"):
    meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
    fetchers = []

    def factory(fetcher_source_id, run_stamp, store_raw, stats, **kwargs):
        fetcher = OfflineFetcher(fetcher_source_id, run_stamp, store_raw, stats, pages, **kwargs)
        fetchers.append(fetcher)
        return fetcher

    run_id = "offline_{}_{}_{}".format(source_id, mode, run_suffix)
    with patch.object(runner, "Fetcher", side_effect=factory):
        result = runner.run_source(con, run_id, mode, source_id, w, meta)
    return result, fetchers[0]


class RegistryTest(unittest.TestCase):
    def test_source_ids_are_unique_and_register_to_this_module(self):
        ids = [row["source_id"] for row in w.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        found = runner.discover()
        for row in w.SOURCES:
            self.assertIs(found[row["source_id"]][0], w)
            self.assertIsNone(row["blueprint_data_id"])
            self.assertEqual(row["text_storage_policy"], "metadata_only")
        self.assertFalse(any(source_id.startswith("eflux_") for source_id in ids))

    def test_penske_and_artasia_pacific_permission_disables_remain(self):
        by_id = {row["source_id"]: row for row in gl_media.SOURCES}
        for source_id in ("artnews_feed", "art_in_america_feed", "artforum_feed", "artasiapacific_rss"):
            self.assertIn(source_id, by_id)
            self.assertTrue(by_id[source_id].get("disabled"))
            self.assertEqual(by_id[source_id].get("operational_state"), "blocked_permission")


class AssessmentTest(unittest.TestCase):
    def test_assessment_covers_each_sourcebook_with_explicit_observations(self):
        root = Path(__file__).resolve().parents[1]
        input_rows = json.loads((root / "work/audit/wave2/Media.json").read_text(encoding="utf-8"))
        assessments = json.loads((root / "work/audit/wave2/Media_assessment.json").read_text(encoding="utf-8"))
        required = {
            "sourcebook_id", "source_ids", "disposition", "requested_vs_observed_fields",
            "official_entry_url", "terms_robots_evidence", "limitations", "implementation_source_ids",
        }
        ids = [row["sourcebook_id"] for row in assessments]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {row["sourcebook_id"] for row in input_rows})
        for row in assessments:
            self.assertTrue(required.issubset(row))
            self.assertIsInstance(row["source_ids"], list)
            self.assertTrue(row["requested_vs_observed_fields"]["observed"])


class FeedParserTest(unittest.TestCase):
    def test_real_artishock_rss_markup_fields_and_language(self):
        items = w.parse_feed(ARTISHOCK_FEED)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["title"], "BOCAS DE AGUA")
        self.assertEqual(item["link"], "https://artishockrevista.com/2026/10/27/bocas-de-agua/")
        self.assertEqual(item["author"], "Alejandra Villasmil")
        self.assertEqual(item["published"], "2026-10-27T19:37:50+00:00")
        self.assertEqual(item["categories"], ["Artículos", "Intersecciones"])
        self.assertEqual(w._feed_language(ARTISHOCK_FEED), "es")

    def test_real_artmonthly_listing_markup_only_extracts_title_and_url(self):
        items = w.parse_artmonthly_listing(ARTMONTHLY_LISTING)
        self.assertEqual(items, [
            {"title": "Deep Cuts", "url": "https://www.artmonthly.co.uk/magazine/site/article/deep-cuts-by-isobel-harbison-october-2026"},
            {"title": "Ana Mendieta", "url": "https://www.artmonthly.co.uk/magazine/site/article/ana-mendieta-by-bryony-white-september-2026"},
        ])

    def test_mousse_feed_markup_keeps_generic_publisher_creator_and_exhibition_category(self):
        items = w.parse_feed(MOUSSE_FEED)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "“Outlaws” at Istituto Svizzero, Rome")
        self.assertEqual(items[0]["link"], "https://www.moussemagazine.it/magazine/outlaws-istituto-svizzero-rome-2026")
        self.assertEqual(items[0]["author"], "Mousse Magazine")
        self.assertEqual(items[0]["published"], "2026-10-27T13:39:13+00:00")
        self.assertEqual(items[0]["categories"], ["Exhibitions"])
        self.assertEqual(w._feed_language(MOUSSE_FEED), "en")

    def test_monopol_rss_uses_dc_creator_and_pubdate_not_escaped_description_metadata(self):
        items = w.parse_feed(MONOPOL_FEED)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Is Gen Z in the tent with us right now?")
        self.assertEqual(items[0]["link"], "https://www.monopol-magazin.de/en/gen-z-tent-us-right-now")
        self.assertEqual(items[0]["author"], "Kate Brown")
        self.assertEqual(items[0]["published"], "2026-10-19T06:56:19+00:00")
        self.assertIn("Embedded creation markup", items[0]["summary"])
        self.assertEqual(w._feed_language(MONOPOL_FEED), "de")

    def test_cmagazine_homepage_cards_extract_only_explicit_metadata(self):
        entries = w.parse_cmagazine_listing(CMAGAZINE_HOME)
        self.assertEqual(entries, [
            {
                "title": "“Starmirror” — Holly Herndon and Mat Dryhurst",
                "url": "https://cmagazine.com/articles/starmirror-holly-herndon-and-mat-dryhurst",
                "author": "Jayne Wilkinson",
                "categories": ["Review"],
                "article_type": "review",
                "type_basis": "feed_category:Review",
            },
            {
                "title": "Open Hearing: Dreaming in Dark Times, Dispatch III",
                "url": "https://cmagazine.com/articles/open-hearing-dreaming-in-dark-times-dispatch-iii",
                "author": None,
                "categories": ["Feature"],
                "article_type": "unknown",
                "type_basis": None,
            },
        ])

    def test_canadianart_saved_section_cards_keep_visible_dates_only(self):
        entries = w.parse_canadianart_listing(CANADIAN_ART_NEWS, "news")
        self.assertEqual(entries, [
            {
                "title": "Statement from the Canadian Art Foundation Board of Directors",
                "url": "https://canadianart.ca/news/statement-from-the-canadian-art-foundation-board-of-directors/",
                "published": "2021-10-04",
                "categories": ["news"],
                "article_type": "news",
                "type_basis": "public_list_section:news",
            },
            {
                "title": "OCAD U Accountability Examined in New Report",
                "url": "https://canadianart.ca/news/new-report/",
                "published": None,
                "categories": ["news"],
                "article_type": "news",
                "type_basis": "public_list_section:news",
            },
        ])
        self.assertEqual(len(w.parse_canadianart_listing(CANADIAN_ART_ESSAYS, "essays")), 1)
        self.assertEqual(len(w.parse_canadianart_listing(CANADIAN_ART_REVIEWS, "reviews")), 1)

    def test_beauxarts_news_sitemap_keeps_news_metadata_not_image_or_empty_date(self):
        entries = w.parse_beauxarts_news_sitemap(BEAUXARTS_NEWS_SITEMAP)
        self.assertEqual(entries, [
            {
                "url": "https://www.beauxarts.com/expos/gustave-fayet-mary-cassatt-paris/",
                "title": "Gustave Fayet, Mary Cassatt, Warhol, Tintoret… Que valent les grandes expos du moment à Paris ?",
                "published": "2026-10-28T06:00:17+01:00",
                "modified": "2026-10-28T06:05:04+01:00",
                "lang": "fr",
                "categories": ["Art moderne", "Musée de Montmartre"],
            },
            {
                "url": "https://www.beauxarts.com/grand-format/army-of-terracotta/",
                "title": "L’armée de terre cuite de Xi’an",
                "published": None,
                "modified": "2026-10-27T14:49:00+01:00",
                "lang": "fr",
                "categories": [],
            },
        ])


class CollectTest(unittest.TestCase):
    def test_feed_collection_is_paged_metadata_only_and_idempotent(self):
        con = _con()
        entry = "https://artishockrevista.com/feed/"
        pages = {entry: ARTISHOCK_FEED, entry + "?paged=2": ARTISHOCK_OLD_FEED}
        ctx = Context(con, "artishock_articles", pages)
        w.collect(ctx)
        self.assertEqual(ctx.calls, [entry, entry + "?paged=2"])
        rows = con.execute(
            "SELECT title, canonical_url, author_text, published_at, categories, excerpt, lang FROM articles "
            "WHERE source_id='artishock_articles' ORDER BY published_at"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        newest = rows[-1]
        self.assertEqual(newest["title"], "BOCAS DE AGUA")
        self.assertEqual(newest["author_text"], "Alejandra Villasmil")
        self.assertEqual(newest["published_at"], "2026-10-27T19:37:50+00:00")
        self.assertEqual(newest["categories"], "Artículos; Intersecciones")
        self.assertEqual(newest["lang"], "es")
        self.assertIsNone(newest["excerpt"])
        self.assertEqual(ctx.stats["inserted"], 2)

        rerun = Context(con, "artishock_articles", pages)
        w.collect(rerun)
        self.assertEqual(rerun.stats.get("inserted", 0), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles WHERE source_id='artishock_articles'").fetchone()[0], 2)

    def test_artmonthly_collection_does_not_store_list_synopses_or_infer_byline(self):
        con = _con()
        entry = "https://www.artmonthly.co.uk/magazine/site/article/recent-articles"
        ctx = Context(con, "artmonthly_recent", {entry: ARTMONTHLY_LISTING.encode("utf-8")}, mode="incremental")
        w.collect(ctx)
        rows = con.execute(
            "SELECT title, author_text, published_at, categories, excerpt FROM articles "
            "WHERE source_id='artmonthly_recent' ORDER BY title"
        ).fetchall()
        self.assertEqual([row["title"] for row in rows], ["Ana Mendieta", "Deep Cuts"])
        for row in rows:
            self.assertIsNone(row["author_text"])
            self.assertIsNone(row["published_at"])
            self.assertIsNone(row["categories"])
            self.assertIsNone(row["excerpt"])
        self.assertEqual(ctx.calls, [entry])

    def test_cmagazine_collection_is_metadata_only_and_idempotent(self):
        con = _con()
        entry = "https://cmagazine.com/"
        result, fetcher = _run_offline(
            con, "cmagazine_articles", {entry: CMAGAZINE_HOME.encode("utf-8")},
        )
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], [entry])
        rows = con.execute(
            "SELECT title, canonical_url, author_text, published_at, categories, article_type, excerpt "
            "FROM articles WHERE source_id='cmagazine_articles' ORDER BY title"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        review = next(row for row in rows if row["author_text"])
        self.assertEqual(review["title"], "“Starmirror” — Holly Herndon and Mat Dryhurst")
        self.assertEqual(review["canonical_url"], "https://cmagazine.com/articles/starmirror-holly-herndon-and-mat-dryhurst")
        self.assertEqual(review["author_text"], "Jayne Wilkinson")
        self.assertIsNone(review["published_at"])
        self.assertEqual(review["categories"], "Review")
        self.assertEqual(review["article_type"], "review")
        feature = next(row for row in rows if row["author_text"] is None)
        self.assertEqual(feature["title"], "Open Hearing: Dreaming in Dark Times, Dispatch III")
        self.assertIsNone(feature["published_at"])
        self.assertEqual(feature["categories"], "Feature")
        self.assertTrue(all(row["excerpt"] is None for row in rows))
        self.assertNotIn("Card synopsis must not persist", repr([tuple(row) for row in rows]))
        self.assertEqual(con.execute("SELECT count(*) FROM image_rights WHERE source_id='cmagazine_articles'").fetchone()[0], 0)

        rerun, rerun_fetcher = _run_offline(
            con, "cmagazine_articles", {entry: CMAGAZINE_HOME.encode("utf-8")}, run_suffix="rerun",
        )
        self.assertFalse(rerun_fetcher.store_raw)
        self.assertEqual(rerun["state"], "no_change")
        self.assertEqual(rerun.get("inserted", 0), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles WHERE source_id='cmagazine_articles'").fetchone()[0], 2)

    def test_canadianart_section_collector_keeps_unknown_dates_null_and_is_idempotent(self):
        con = _con()
        pages = {
            "https://canadianart.ca/news/": CANADIAN_ART_NEWS.encode("utf-8"),
            "https://canadianart.ca/essays/": CANADIAN_ART_ESSAYS.encode("utf-8"),
            "https://canadianart.ca/reviews/": CANADIAN_ART_REVIEWS.encode("utf-8"),
        }
        result, fetcher = _run_offline(con, "canadianart_article_lists", pages)
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], list(pages))
        rows = con.execute(
            "SELECT title, canonical_url, published_at, categories, excerpt "
            "FROM articles WHERE source_id='canadianart_article_lists' ORDER BY canonical_url"
        ).fetchall()
        self.assertEqual(len(rows), 4)
        dated = next(row for row in rows if row["canonical_url"].endswith("statement-from-the-canadian-art-foundation-board-of-directors/"))
        self.assertEqual(dated["title"], "Statement from the Canadian Art Foundation Board of Directors")
        self.assertEqual(dated["published_at"], "2021-10-04")
        unknown = next(row for row in rows if row["canonical_url"].endswith("/news/new-report/"))
        self.assertEqual(unknown["title"], "OCAD U Accountability Examined in New Report")
        self.assertIsNone(unknown["published_at"])
        self.assertEqual(unknown["categories"], "news")
        self.assertTrue(all(row["excerpt"] is None for row in rows))
        self.assertNotIn("synopsis must not persist", repr([tuple(row) for row in rows]))
        self.assertFalse(any("outside.example" in row["canonical_url"] for row in rows))
        self.assertEqual(con.execute("SELECT count(*) FROM image_rights WHERE source_id='canadianart_article_lists'").fetchone()[0], 0)

        rerun, rerun_fetcher = _run_offline(
            con, "canadianart_article_lists", pages, run_suffix="rerun",
        )
        self.assertFalse(rerun_fetcher.store_raw)
        self.assertEqual(rerun["state"], "no_change")
        self.assertEqual(rerun.get("inserted", 0), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles WHERE source_id='canadianart_article_lists'").fetchone()[0], 4)

    def test_beauxarts_news_sitemap_collection_is_metadata_only_and_idempotent(self):
        con = _con()
        entry = "https://www.beauxarts.com/sitemap-news.xml"
        pages = {entry: BEAUXARTS_NEWS_SITEMAP}
        result, fetcher = _run_offline(con, "beauxarts_news_sitemap", pages)
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], [entry])
        rows = con.execute(
            "SELECT title, canonical_url, published_at, modified_at, categories, lang, excerpt "
            "FROM articles WHERE source_id='beauxarts_news_sitemap' ORDER BY canonical_url"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        dated = next(row for row in rows if "/expos/" in row["canonical_url"])
        self.assertEqual(dated["title"], "Gustave Fayet, Mary Cassatt, Warhol, Tintoret… Que valent les grandes expos du moment à Paris ?")
        self.assertEqual(dated["canonical_url"], "https://www.beauxarts.com/expos/gustave-fayet-mary-cassatt-paris/")
        self.assertEqual(dated["published_at"], "2026-10-28T06:00:17+01:00")
        self.assertEqual(dated["modified_at"], "2026-10-28T06:05:04+01:00")
        self.assertEqual(dated["categories"], "Art moderne; Musée de Montmartre")
        self.assertEqual(dated["lang"], "fr")
        unknown = next(row for row in rows if "/grand-format/" in row["canonical_url"])
        self.assertEqual(unknown["title"], "L’armée de terre cuite de Xi’an")
        self.assertIsNone(unknown["published_at"])
        self.assertEqual(unknown["modified_at"], "2026-10-27T14:49:00+01:00")
        self.assertTrue(all(row["excerpt"] is None for row in rows))
        self.assertNotIn("not-to-download.jpg", repr([tuple(row) for row in rows]))
        self.assertEqual(con.execute("SELECT count(*) FROM image_rights WHERE source_id='beauxarts_news_sitemap'").fetchone()[0], 0)

        rerun, rerun_fetcher = _run_offline(con, "beauxarts_news_sitemap", pages, run_suffix="rerun")
        self.assertFalse(rerun_fetcher.store_raw)
        self.assertEqual(rerun["state"], "no_change")
        self.assertEqual(rerun.get("inserted", 0), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles WHERE source_id='beauxarts_news_sitemap'").fetchone()[0], 2)

    def test_monopol_collection_ignores_escaped_description_and_is_idempotent(self):
        con = _con()
        entry = "https://www.monopol-magazin.de/rss.xml"
        pages = {entry: MONOPOL_FEED}
        result, fetcher = _run_offline(con, "monopol_articles", pages)
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], [entry])
        row = con.execute(
            "SELECT title, canonical_url, author_text, published_at, lang, excerpt "
            "FROM articles WHERE source_id='monopol_articles'"
        ).fetchone()
        self.assertEqual(row["title"], "Is Gen Z in the tent with us right now?")
        self.assertEqual(row["canonical_url"], "https://www.monopol-magazin.de/en/gen-z-tent-us-right-now")
        self.assertEqual(row["author_text"], "Kate Brown")
        self.assertEqual(row["published_at"], "2026-10-19T06:56:19+00:00")
        self.assertEqual(row["lang"], "de")
        self.assertIsNone(row["excerpt"])
        self.assertNotIn("Embedded creation markup", repr(tuple(row)))

        rerun, rerun_fetcher = _run_offline(con, "monopol_articles", pages, run_suffix="rerun")
        self.assertFalse(rerun_fetcher.store_raw)
        self.assertEqual(rerun["state"], "no_change")
        self.assertEqual(rerun.get("inserted", 0), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles WHERE source_id='monopol_articles'").fetchone()[0], 1)

    def test_initial_feed_stops_inclusively_at_cutoff_date(self):
        entry = "https://artishockrevista.com/feed/"
        before_cutoff = "Sat, 02 Apr 2025 09:00:00 +0000"
        on_cutoff = "Tue, 01 Apr 2025 09:00:00 +0000"
        pages = {
            entry: _rss_page("After cutoff", "https://artishockrevista.com/after-cutoff/", before_cutoff),
            entry + "?paged=2": _rss_page("Cutoff day", "https://artishockrevista.com/cutoff-day/", on_cutoff),
        }
        con = _con()
        result, fetcher = _run_offline(con, "artishock_articles", pages)
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], [entry, entry + "?paged=2"])
        rows = con.execute(
            "SELECT title, published_at, excerpt FROM articles WHERE source_id='artishock_articles' ORDER BY published_at"
        ).fetchall()
        self.assertEqual([(row["title"], row["published_at"]) for row in rows], [
            ("Cutoff day", "2025-04-01T09:00:00+00:00"),
            ("After cutoff", "2025-04-02T09:00:00+00:00"),
        ])
        self.assertTrue(all(row["excerpt"] is None for row in rows))

    def test_initial_feed_unknown_dates_continue_until_request_cap(self):
        entry = "https://artishockrevista.com/feed/"
        pages = {
            entry: _rss_page("Undated first page", "https://artishockrevista.com/undated-first/"),
            entry + "?paged=2": _rss_page("Undated second page", "https://artishockrevista.com/undated-second/"),
        }
        con = _con()
        with patch.object(w, "MAX_INITIAL_FEED_PAGES", 2):
            result, fetcher = _run_offline(con, "artishock_articles", pages)
        self.assertEqual(result["state"], "success")
        self.assertFalse(fetcher.store_raw)
        self.assertEqual([call[0] for call in fetcher.calls], [entry, entry + "?paged=2"])
        self.assertTrue(any("Official RSS pages read: 2" in note and "oldest date on last page: unknown" in note for note in result["notes"]))
        rows = con.execute(
            "SELECT title, published_at, excerpt FROM articles WHERE source_id='artishock_articles' ORDER BY title"
        ).fetchall()
        self.assertEqual([row["title"] for row in rows], ["Undated first page", "Undated second page"])
        self.assertTrue(all(row["published_at"] is None and row["excerpt"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
