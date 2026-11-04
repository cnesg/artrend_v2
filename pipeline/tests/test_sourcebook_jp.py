import unittest.mock
import unittest

from artrend_mag.sources.sourcebook_jp import (
    SOURCES,
    _faam_rows,
    _jp_dates,
    _tobikan_rows,
    _voca_awards,
)


class JapaneseSourcebookMarkupTests(unittest.TestCase):
    def test_tobikan_japanese_exhibition_card_keeps_original_title_and_day_precision(self):
        html = '''
        <ul class="exhibition-list row"><li>
          <a class="exhibition-item col" data-term="8" href="2026_orsay.html">
            <p class="-category fs11 s-fs10"><span class="-special">特別展</span></p>
            <p class="-title s-fs12">東京都美術館開館100周年記念<br/>オルセー美術館所蔵 いまを生きる歓び</p>
            <p class="-period fs11 s-fs10">2026年11月14日(土)～2027年3月28日(日)</p>
          </a>
        </li></ul>
        '''

        rows = _tobikan_rows(html, "https://www.tobikan.jp/exhibition/")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "東京都美術館開館100周年記念 オルセー美術館所蔵 いまを生きる歓び")
        self.assertEqual(rows[0]["url"], "https://www.tobikan.jp/exhibition/2026_orsay.html")
        self.assertEqual(_jp_dates(rows[0]["date_text"]),
                         ("2026-11-14", "day", "2027-03-28", "day"))

    def test_faam_japanese_exhibition_card_parses_visible_period_without_detail_fetch(self):
        html = '''
        <div class="c-list-exhibition-item">
          <a class="c-list-exhibition-item__inner" href="https://faam.city.fukuoka.lg.jp/exhibition/26076/">
            <div class="c-list-exhibition-item__body">
              <span class="c-list-exhibition-item__label">特別展</span>
              <h3 class="c-list-exhibition-item__title">アジア美術の歩き方 南アジア特別編 対立の先へ―光の水脈をめぐる旅</h3>
              <div class="c-list-exhibition-item__meta"><span class="c-list-exhibition-item__date">2026.9.19 (土） 〜 2027.1.11 (月）</span></div>
            </div>
          </a>
        </div>
        '''

        rows = _faam_rows(html, "https://faam.city.fukuoka.lg.jp/exhibition/")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "アジア美術の歩き方 南アジア特別編 対立の先へ―光の水脈をめぐる旅")
        self.assertEqual(rows[0]["url"], "https://faam.city.fukuoka.lg.jp/exhibition/26076/")
        self.assertEqual(_jp_dates(rows[0]["date_text"]),
                         ("2026-09-19", "day", "2027-01-11", "day"))

    def test_shugoarts_dotted_japanese_listing_inherits_explicit_start_year(self):
        html = '''<div class="info__date"><span class="start date-box">2026. 10. 16 <span class="d">Fri</span></span>
          <span class="date-slash"></span><span class="end date-box">11. 28 <span class="d">Sat</span></span></div>'''

        from bs4 import BeautifulSoup
        date_text = BeautifulSoup(html, "lxml").select_one(".info__date").get_text(" ")

        self.assertEqual(_jp_dates(date_text), ("2026-10-16", "day", "2026-11-28", "day"))

    def test_voca_official_japanese_winner_list_preserves_award_roles_and_names(self):
        html = '''<section><h2>受賞作品</h2><ul>
          <li>VOCA賞 戸田 沙也加</li>
          <li>VOCA奨励賞 ソー・ソウエン</li>
          <li>VOCA奨励賞 寺田 健人</li>
          <li>VOCA佳作賞 加藤 千晶</li>
          <li>VOCA佳作賞 倉敷 安耶</li>
        </ul></section>'''

        self.assertEqual(_voca_awards(html), {
            "VOCA賞": ["戸田 沙也加"],
            "VOCA奨励賞": ["ソー・ソウエン", "寺田 健人"],
            "VOCA佳作賞": ["加藤 千晶", "倉敷 安耶"],
        })

    def test_new_source_ids_are_unique_and_have_no_blueprint_guess(self):
        ids = [source["source_id"] for source in SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(source["blueprint_data_id"] is None for source in SOURCES))


class ArtscapeCardTests(unittest.TestCase):
    def test_image_link_without_text_does_not_hide_title_link(self):
        from unittest.mock import MagicMock
        from artrend_mag.sources import sourcebook_jp
        html = """<article class="item-article"><figure class="item-img"><a href="https://artscape.jp/article/80355/"><img alt=""/></a></figure>
        <div class="item-txt"><em class="article-datetime">2026.10.28</em><a class="article-category category-review" href="/category/review/">レビュー</a>
        <a href="https://artscape.jp/article/80355/"><span>松房子｜路上、お邪魔ですか？</span></a></div></article>"""
        ctx = MagicMock()
        ctx.mode = "incremental"
        ctx.meta = {"entry_url": "https://artscape.jp/category/review/"}
        ctx.fetch.return_value = MagicMock(text=html, final_url="https://artscape.jp/category/review/")
        stored = []
        with unittest.mock.patch.object(sourcebook_jp.db, "upsert_article", side_effect=lambda *a, **k: stored.append(k)):
            sourcebook_jp._artscape(ctx)
        self.assertEqual(stored[0]["title"], "松房子｜路上、お邪魔ですか？")
        self.assertEqual(stored[0]["published_at"], "2026-10-28")
        self.assertEqual(stored[0]["author_text"], "松房子")
        self.assertIsNone(stored[0]["excerpt"])


if __name__ == "__main__":
    unittest.main()
