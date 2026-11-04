import collections
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from artrend_mag import db
from artrend_mag.http import Blocked
from artrend_mag.sources import kr_naver_news as nv

# Real item shape from the original project's raw store (아트랜드v2v crawlers/raw/naver_news, 2026-03-13).
REAL_ITEM = {
    "title": "왕관에서 자산으로, 보석을 바라보는 시선",
    "originallink": "https://magazine.hankyung.com/money/article/202602240862c",
    "link": "https://magazine.hankyung.com/money/article/202602240862c",
    "description": "2011년 <b>크리스티</b> 뉴욕 <b>경매</b>에서 리처드 버턴이 엘리자베스 테일러의 40번째 생일에 선물한 까르띠에 &quot;타지마할&quot; 목걸이",
    "pubDate": "Fri, 13 Mar 2026 06:02:00 +0900",
}


class FakeCtx:
    def __init__(self, con, pages, mode="incremental"):
        self.con, self.mode, self.source_id = con, mode, "kr_naver_news_api"
        self.stats, self.notes, self.calls = collections.Counter(), [], []
        self.fetcher = SimpleNamespace(s=SimpleNamespace(headers={}))
        self.pages = pages

    def fetch(self, url, params=None, **_):
        self.calls.append(dict(params))
        items = self.pages.get((params["query"], params["start"]), [])
        return SimpleNamespace(content=json.dumps({"items": items}).encode())

    def count(self, key, n=1):
        self.stats[key] += n

    def note(self, text):
        self.notes.append(text)


class NaverNewsTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        db.init_schema(self.con)
        db.upsert_source(self.con, "kr_naver_news_api", name="t", source_kind="media", access_method="api")

    def test_real_item_keeps_publisher_link_clean_title_and_short_snippet(self):
        rec = nv.item_record(REAL_ITEM)
        self.assertEqual(rec["url"], "https://magazine.hankyung.com/money/article/202602240862c")
        self.assertEqual(rec["publisher"], "magazine.hankyung.com")
        self.assertEqual(rec["published"], "2026-03-13T06:02:00+09:00")
        self.assertIn("크리스티 뉴욕 경매", rec["snippet"])
        self.assertIn('"타지마할"', rec["snippet"])
        self.assertLessEqual(len(nv.item_record(dict(REAL_ITEM, description="가" * 500))["snippet"]), 300)

    def test_missing_keys_block_as_credentials_before_any_request(self):
        ctx = FakeCtx(self.con, {})
        with tempfile.TemporaryDirectory() as tmp, patch.object(nv, "load_keys", return_value=None):
            with self.assertRaises(Blocked) as err:
                nv.collect(ctx)
        self.assertEqual(err.exception.kind, "credentials_missing")
        self.assertEqual(ctx.calls, [])

    def test_keys_are_read_from_project_dotenv_without_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text('NAVER_CLIENT_ID="abc"\nNAVER_CLIENT_SECRET=xyz\n', encoding="utf-8")
            self.assertEqual(nv.load_keys(env={}, dotenv_path=p), ("abc", "xyz"))
            self.assertIsNone(nv.load_keys(env={}, dotenv_path=Path(tmp) / "missing"))

    def test_broad_queries_keep_only_art_items_and_entity_queries_keep_all(self):
        off_topic = dict(REAL_ITEM, title="갤러리 스마트폰 신제품", description="카메라 기능", originallink="https://n.test/phone")
        art = dict(REAL_ITEM, title="서울 갤러리 개인전 개막", description="", originallink="https://n.test/art")
        pages = {("갤러리 개인전", 1): [off_topic, art], ("크리스티 경매", 1): [REAL_ITEM]}
        ctx = FakeCtx(self.con, pages)
        with patch.object(nv, "load_keys", return_value=("i", "s")), \
             patch.object(nv, "queries", return_value=[("크리스티 경매", "date", "Christies"), ("갤러리 개인전", "date", nv.BROAD)]):
            nv.collect(ctx)
        titles = {r[0] for r in self.con.execute("SELECT title FROM articles")}
        self.assertEqual(titles, {"왕관에서 자산으로, 보석을 바라보는 시선", "서울 갤러리 개인전 개막"})
        self.assertEqual(ctx.fetcher.s.headers["X-Naver-Client-Id"], "i")
        stored = " ".join(str(v) for row in self.con.execute("SELECT * FROM articles") for v in row)
        self.assertNotIn("X-Naver", stored)

    def test_items_outside_the_window_are_dropped_in_every_mode(self):
        old = dict(REAL_ITEM, originallink="https://n.test/old", pubDate="Fri, 05 Oct 1990 06:02:00 +0900")
        undated = dict(REAL_ITEM, originallink="https://n.test/undated", pubDate="")
        for mode in ("initial", "incremental"):
            ctx = FakeCtx(self.con, {("크리스티 경매", 1): [old, undated, REAL_ITEM]}, mode=mode)
            with patch.object(nv, "load_keys", return_value=("i", "s")), \
                 patch.object(nv, "queries", return_value=[("크리스티 경매", "sim", "Christies")]):
                nv.collect(ctx)
        self.assertEqual([r[0] for r in self.con.execute("SELECT canonical_url FROM articles")], [REAL_ITEM["originallink"]])

    def test_same_article_from_two_queries_is_not_rewritten(self):
        pages = {("크리스티 경매", 1): [REAL_ITEM], ("크리스티 경매 낙찰", 1): [REAL_ITEM]}
        ctx = FakeCtx(self.con, pages)
        with patch.object(nv, "load_keys", return_value=("i", "s")), \
             patch.object(nv, "queries", return_value=[("크리스티 경매", "date", "Christies"), ("크리스티 경매 낙찰", "date", "Christies")]):
            nv.collect(ctx)
        self.assertEqual((ctx.stats["inserted"], ctx.stats.get("updated", 0), ctx.stats["unchanged"]), (1, 0, 1))
        # a broad query returning the same article must not rewrite its tier either
        ctx = FakeCtx(self.con, {("미술 전시", 1): [dict(REAL_ITEM, description="다른 검색어 주변 문장 미술 전시")]})
        with patch.object(nv, "load_keys", return_value=("i", "s")), \
             patch.object(nv, "queries", return_value=[("미술 전시", "date", nv.BROAD)]):
            nv.collect(ctx)
        self.assertEqual(ctx.stats.get("updated", 0), 0)

    def test_relevance_tiers_follow_the_original_about_rule_and_title_words(self):
        spec = nv.specs()
        self.assertEqual(nv.relevance("KAuction", "케이옥션 가을 경매 낙찰총액", "", spec), "alias")
        self.assertIsNone(nv.relevance("KAuction", "SK옥션 중고차 케이옥션 비교", "", spec))          # exclude keyword
        # observed off-topic hits (2026-10-29)
        self.assertIsNone(nv.relevance("_market", "주진우, 李대통령 부부 '황제 골프' 고발", "", spec))
        self.assertIsNone(nv.relevance(nv.BROAD, "우리은행, 국방부 유해발굴감식단에 위문금 전달", "본점에서 '유품·사진전'", spec))
        self.assertIsNone(nv.relevance(nv.BROAD, "김태희 '기품 넘치는 걸음'", "서울옥션 강남센터에서 주얼리 행사", spec))
        self.assertEqual(nv.relevance(nv.BROAD, "'올해의 작가상 2026' 24일 개막", "", spec), "title")
        self.assertEqual(nv.relevance(nv.BROAD, "홍라희 관장 훈장", "미술품과 문화재 2만3000여 점을 국가에 기증", spec), "snippet")

    def test_initial_mode_adds_original_backfill_queries(self):
        incremental, initial = nv.queries("incremental"), nv.queries("initial")
        self.assertIn(("서울옥션", "date", "SeoulAuction"), incremental)
        self.assertNotIn(("서울옥션", "sim", "SeoulAuction"), incremental)
        self.assertIn(("서울옥션", "sim", "SeoulAuction"), initial)
        self.assertEqual(len(initial), len(set((q, s) for q, s, _ in initial)))


if __name__ == "__main__":
    unittest.main()
