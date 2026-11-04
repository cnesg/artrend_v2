import collections
import sqlite3
import unittest
from types import SimpleNamespace

from artrend_mag import db
from artrend_mag.sources import kr_news

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><language>ko</language>
<item><title>국립현대미술관, 내년 대규모 회고전 개최</title><link>https://news.test/a1?utm_source=rss</link>
<pubDate>Wed, 29 Oct 2026 09:00:00 +0900</pubDate><category>문화</category></item>
<item><title>아이돌 그룹 새 앨범 발매</title><link>https://news.test/a2</link>
<pubDate>Wed, 29 Oct 2026 08:00:00 +0900</pubDate><category>가요</category></item>
<item><title>김민지 《빛의 층위》</title><link>https://news.test/a3</link>
<pubDate>Tue, 28 Oct 2026 10:00:00 +0900</pubDate></item>
</channel></rss>""".encode("utf-8")


class FakeCtx:
    def __init__(self, con, art_filter):
        self.con = con
        self.stats = collections.Counter()
        self.counts = collections.Counter()
        self.source_id = "kr_test_rss"
        self.mode = "incremental"
        self.meta = dict(entry_url="https://news.test/rss", publisher="테스트일보", owner_group="테스트일보", art_filter=art_filter)
        self.notes = []

    def fetch(self, url, **_):
        return SimpleNamespace(content=FEED)

    def count(self, key, n=1):
        self.counts[key] += n

    def note(self, text):
        self.notes.append(text)


class KoreanArtNewsTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        db.init_schema(self.con)
        db.upsert_source(self.con, "kr_test_rss", name="t", source_kind="media", access_method="rss")

    def test_general_culture_feed_keeps_only_art_items_with_matched_keyword(self):
        ctx = FakeCtx(self.con, art_filter=True)
        kr_news.collect(ctx)
        rows = self.con.execute("SELECT title, type_basis, canonical_url, lang, excerpt FROM articles ORDER BY title").fetchall()
        self.assertEqual([r[0] for r in rows], ["국립현대미술관, 내년 대규모 회고전 개최", "김민지 《빛의 층위》"])
        self.assertEqual(rows[0][1], "art_keyword:미술")
        self.assertEqual(rows[1][1], "art_keyword:《")
        self.assertEqual(rows[0][2], "https://news.test/a1")       # tracking parameters dropped
        self.assertEqual({r[3] for r in rows}, {"ko"})
        self.assertEqual({r[4] for r in rows}, {None})             # metadata only, never an excerpt
        self.assertEqual(ctx.counts["skipped_not_art"], 1)

    def test_ambiguous_words_alone_do_not_admit_an_item(self):
        self.assertIsNone(kr_news.art_match("부안군, 30일부터 '가을애 국화전시회' 개최", []))
        self.assertIsNone(kr_news.art_match("'대한민국 게임박물관' 만든다", []))
        self.assertIsNone(kr_news.art_match("갤러리 스마트폰 신제품", []))
        self.assertEqual(kr_news.art_match("박물관 특별 전시 개막", []), "박물관+전시")
        self.assertEqual(kr_news.art_match("서울 갤러리 개인전 개막", []), "개인전")

    def test_art_specialist_outlet_keeps_every_item(self):
        kr_news.collect(FakeCtx(self.con, art_filter=False))
        self.assertEqual(self.con.execute("SELECT count(*) FROM articles").fetchone()[0], 3)

    def test_registry_rows_are_metadata_only_korean_feeds(self):
        for row in kr_news.SOURCES:
            self.assertEqual((row["region_scope"], row["text_storage_policy"], row["access_method"]), ("KR", "metadata_only", "rss"))
        self.assertNotIn("news.google.com", " ".join(r["entry_url"] for r in kr_news.SOURCES))


if __name__ == "__main__":
    unittest.main()
