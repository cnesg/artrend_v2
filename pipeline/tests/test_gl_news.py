import unittest

from artrend_mag.sources import gl_news
from artrend_mag.sources._common import parse_feed

# RSS 1.0 (RDF) shape served by asahi.com/rss/asahi/culture.rdf (observed 2026-10-29).
RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
 <channel rdf:about="https://www.asahi.com/"><title>朝日新聞</title></channel>
 <item rdf:about="https://www.asahi.com/articles/A1.html?ref=rss"><title>東京都美術館で回顧展</title>
  <link>https://www.asahi.com/articles/A1.html?ref=rss</link><dc:subject>文化</dc:subject>
  <dc:date>2026-10-29T15:19:59+09:00</dc:date></item>
</rdf:RDF>""".encode("utf-8")


class WorldArtNewsTests(unittest.TestCase):
    def test_rss1_items_are_parsed(self):
        items = parse_feed(RDF)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "東京都美術館で回顧展")
        self.assertEqual(items[0]["link"], "https://www.asahi.com/articles/A1.html?ref=rss")
        self.assertEqual(items[0]["published"], "2026-10-29T15:19:59+09:00")
        self.assertEqual(items[0]["categories"], ["文化"])

    def test_art_words_in_japanese_english_and_french(self):
        self.assertEqual(gl_news.art_match_world("東京都美術館で回顧展", []), "美術")
        self.assertEqual(gl_news.art_match_world("Louvre heist: museum director resigns", []), "museum")
        self.assertEqual(gl_news.art_match_world("Une rétrospective Matisse", []), "rétrospective")
        # observed off-topic items in general feeds
        self.assertIsNone(gl_news.art_match_world("ピアニスト反田恭平氏に執行猶予判決", ["文化"]))
        self.assertIsNone(gl_news.art_match_world("State-of-the-art stadium opens", []))
        self.assertIsNone(gl_news.art_match_world("Strictly Come Dancing results", ["Entertainment & Arts"]))
        self.assertEqual(gl_news.art_match_world("Untitled", ["Arts"]), "category:Arts")

    def test_relative_and_null_host_feed_links_resolve_to_the_outlet(self):
        from artrend_mag.sources.kr_news import absolute_link
        base = "https://www.sankei.com"
        self.assertEqual(absolute_link("null/article/20261029-5PO6/", base), "https://www.sankei.com/article/20261029-5PO6/")
        self.assertEqual(absolute_link("/article/x/", base), "https://www.sankei.com/article/x/")
        self.assertEqual(absolute_link("https://a.test/x", base), "https://a.test/x")
        self.assertIsNone(absolute_link("/x", None))

    def test_restrictive_publishers_are_disabled_and_rows_are_metadata_only(self):
        disabled = {r["source_id"] for r in gl_news.SOURCES if r.get("operational_state") == "blocked_permission"}
        self.assertEqual(disabled, {"gl_guardian_art_rss", "gl_nyt_art_rss", "gl_scmp_arts_rss"})
        self.assertEqual({r["text_storage_policy"] for r in gl_news.SOURCES}, {"metadata_only"})
        self.assertNotIn("news.google.com", " ".join(r["entry_url"] for r in gl_news.SOURCES))


if __name__ == "__main__":
    unittest.main()
