import tempfile
import unittest
from pathlib import Path

from artrend_mag import db
from artrend_mag.config import WORK_ROOT
from artrend_mag.sources import sourcebook_eu


FLASH_ART_RSS_ITEM = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Flash Art</title>
    <item>
      <title><![CDATA[Oscar Murillo “Unfinished thinking: Paintings and Social Maps” David Zwirner / Paris]]></title>
      <link>https://flash---art.com/2026/10/oscar-murillo/</link>
      <guid isPermaLink="false">https://flash---art.com/2026/10/oscar-murillo/</guid>
      <pubDate>Mon, 26 Oct 2026 08:00:00 +0000</pubDate>
      <dc:creator><![CDATA[Flash Art Admin]]></dc:creator>
      <category><![CDATA[Reviews]]></category>
      <category><![CDATA[David Zwirner]]></category>
      <category><![CDATA[Lydia Korndoerfer]]></category>
      <category><![CDATA[Oscar Murillo]]></category>
      <category><![CDATA[Paris]]></category>
    </item>
  </channel>
</rss>'''.encode("utf-8")


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeContext:
    source_id = "flash_art_rss"
    mode = "initial"
    meta = {"publisher": "Flash Art", "owner_group": "Flash Art"}

    def __init__(self, con):
        self.con = con
        self.stats = {}
        self.notes = []
        self.counts = {}

    def fetch(self, url, **kwargs):
        self.fetch_url = url
        self.fetch_kwargs = kwargs
        return FakeResponse(FLASH_ART_RSS_ITEM)

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def note(self, message):
        self.notes.append(message)


class SourcebookEuropeTests(unittest.TestCase):
    def test_real_flash_art_rss_markup_extracts_only_article_metadata(self):
        items = sourcebook_eu._metadata_items(FLASH_ART_RSS_ITEM)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Oscar Murillo “Unfinished thinking: Paintings and Social Maps” David Zwirner / Paris")
        self.assertEqual(items[0]["url"], "https://flash---art.com/2026/10/oscar-murillo/")
        self.assertEqual(items[0]["published"], "2026-10-26T08:00:00+00:00")
        self.assertEqual(items[0]["author"], "Flash Art Admin")
        self.assertEqual(items[0]["categories"], ["Reviews", "David Zwirner", "Lydia Korndoerfer", "Oscar Murillo", "Paris"])
        self.assertEqual(set(items[0]), {"title", "url", "published", "updated", "author", "categories"})

    def test_collect_stores_review_metadata_without_excerpt_or_body(self):
        with tempfile.TemporaryDirectory(dir=WORK_ROOT / "work" / "dev") as directory:
            con = db.connect(Path(directory) / "scratch.sqlite")
            db.init_schema(con)
            source = sourcebook_eu.SOURCES[0]
            db.upsert_source(con, source["source_id"], **{k: v for k, v in source.items() if k != "source_id"})
            ctx = FakeContext(con)
            sourcebook_eu.collect(ctx)
            row = con.execute("SELECT title, published_at, author_text, article_type, categories, excerpt FROM articles").fetchone()
            self.assertEqual(row["article_type"], "review")
            self.assertEqual(row["categories"], "Reviews; David Zwirner; Lydia Korndoerfer; Oscar Murillo; Paris")
            self.assertIsNone(row["excerpt"])
            self.assertEqual(ctx.counts["parsed"], 1)
            self.assertEqual(ctx.fetch_url, sourcebook_eu.FLASH_ART_FEED)
            con.close()

    def test_feed_urls_are_limited_to_flash_art_and_tracking_is_removed(self):
        self.assertEqual(
            sourcebook_eu._canonical_url("https://flash---art.com/2026/10/oscar-murillo/?utm_source=test#review"),
            "https://flash---art.com/2026/10/oscar-murillo/",
        )
        self.assertIsNone(sourcebook_eu._canonical_url("https://example.org/article"))


if __name__ == "__main__":
    unittest.main()
