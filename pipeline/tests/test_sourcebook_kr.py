import unittest

from artrend_mag.sources.sourcebook_kr import (
    _artinculture_metadata,
    _exhibition_detail_fields,
    _ilmin_cards,
    _ilmin_detail_fields,
    _ilmin_venue,
    _notice_cards,
    _program_cards,
    _residency_roster,
    _selection_names,
)


class KoreanSourcebookObservedMarkupTests(unittest.TestCase):
    def test_iap_program_card_preserves_korean_title_and_visible_date(self):
        html = """<section id="board_exhibitNow"><ul class="gallery_list gallery_list2 grid3">
        <li><a href="/program/view?no=1365"><div class="txt_box">
        <strong>[레지던시 전시] 2026 인천아트플랫폼 국제교류(대만) 교환 작가 쉬신츠(SHIU Jui-tsz) 개인전 《막간》</strong>
        <span class="date">2026-10-29(Thu) ~ 2026-11-15(Sun)</span></div></a></li>
        </ul></section>"""
        cards = _program_cards(html, "https://www.inartplatform.kr/program/list?category=B&time=now")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["id"], "1365")
        self.assertIn("쉬신츠", cards[0]["title"])
        self.assertEqual(cards[0]["start"], "2026-10-29")
        self.assertEqual(cards[0]["end"], "2026-11-15")

    def test_iap_detail_uses_published_period_and_actual_venue(self):
        html = """<section id="exhibitNow_view"><div class="board_view_container">
        <div class="view_top"><h4 class="sub_tit02">2026 인천아트플랫폼 국제교류(대만) 교환 작가 쉬신츠 개인전 《막간》</h4></div>
        <ul><li><b>기간</b><p>2026-10-29(Thu) ~ 2026-11-15(Sun)</p></li>
        <li><b>장소</b><p>인천아트플랫폼 프로젝트 스페이스 (E2)</p></li></ul>
        </div></section>"""
        title, dates, venue = _exhibition_detail_fields(html)
        self.assertIn("쉬신츠", title)
        self.assertEqual(dates, "2026-10-29(Thu) ~ 2026-11-15(Sun)")
        self.assertEqual(venue, "인천아트플랫폼 프로젝트 스페이스 (E2)")

    def test_iap_resident_roster_uses_official_year_tab_and_artist_links(self):
        html = """<section id="board_artists"><h4 class="sub_tit03">2025 인천 청년예술가 스튜디오 지원</h4>
        <ul class="gallery_list grid3">
        <li><a href="/residency/view?residency=479&category=2025">강지웅 작가</a></li>
        <li><a href="/residency/view?residency=489&category=2025">HSU ShengKai (쉬셩카이) 작가</a></li>
        </ul></section>"""
        year, program, residents = _residency_roster(html, "https://www.inartplatform.kr/residency/list?category=2025")
        self.assertEqual(year, "2025")
        self.assertEqual(program, "2025 인천 청년예술가 스튜디오 지원")
        self.assertEqual([row[0] for row in residents], ["강지웅", "HSU ShengKai (쉬셩카이)"])
        self.assertEqual(residents[0][1], "479")

    def test_iap_notice_listing_and_selection_keep_public_korean_name(self):
        listing = """<section id="board_notice"><table>
        <tr class="list_body"><td>577</td><td><a href="/notice/view?no=618">[공고 제2026-129호] 인천문화재단 인천아트플랫폼 &lt;2026 인천미술 올해의 작가(청년)&gt; 선정 공고</a></td><td>2026-07-03</td></tr>
        </table></section>"""
        rows = _notice_cards(listing, "https://www.inartplatform.kr/notice/list")
        self.assertEqual(rows[0]["id"], "618")
        self.assertEqual(rows[0]["date"], "2026-07-03")
        self.assertTrue(_selection_names(["<2026 인천미술 올해의 작가(청년)> 선정자 : 황 문 정"]))
        self.assertEqual(_selection_names(["선정자 : 황 문 정"]), ["황 문 정"])

    def test_art_in_culture_page_keeps_title_author_and_month_without_day(self):
        html = """<html><head><meta name="description" content="아트인컬처 다시 읽기 2022년 1월호 「비평의 비명, 이것이 문제다!」"></head>
        <body><h1>비평의 비명, 이것이 문제다!</h1><a href="/webzine?author=moonhejin">문혜진</a></body></html>"""
        fields = _artinculture_metadata(html)
        self.assertEqual(fields["title"], "비평의 비명, 이것이 문제다!")
        self.assertEqual(fields["author"], "문혜진")
        self.assertEqual(fields["published_at"], "2022-01")

    def test_ilmin_past_card_and_detail_keep_original_title_dates_and_verified_seoul_venue(self):
        listing = """<div class="et_pb_section exhibition-loop-item">
        <div class="et_pb_module et_pb_text exhibition_title"><div class="et_pb_text_inner">
        <a href="https://ilmin.org/exhibition/2026_vibe-era/">《바이브 에라》</a></div></div>
        <div class="et_pb_module et_pb_code exhibition_date"><div class="et_pb_code_inner">
        2026.8.26.(Wed) — 2026.10.25.(Sun)</div></div></div>"""
        cards = _ilmin_cards(listing, "https://ilmin.org/exhibitions/past/")
        self.assertEqual(cards[0]["title"], "《바이브 에라》")
        self.assertEqual(cards[0]["start"], "2026-08-26")
        self.assertEqual(cards[0]["end"], "2026-10-25")

        detail = """<meta property="og:title" content="《바이브 에라》 - 일민미술관">
        <div class="summury-box">
        <div class="exhibition-summury"><div class="et_pb_text_inner">2026.8.26.(Wed) — 2026.10.25.(Sun)</div></div>
        <div class="exhibition-summury"><div class="et_pb_text_inner">Exhibition Hall 2, 3 and Project Room</div></div>
        </div>"""
        title, dates, venue = _ilmin_detail_fields(detail)
        self.assertEqual(title, "《바이브 에라》")
        self.assertEqual(dates, "2026.8.26.(Wed) — 2026.10.25.(Sun)")
        self.assertEqual(_ilmin_venue(venue), ("Seoul", "KR"))
        self.assertEqual(_ilmin_venue("unspecified exhibition venue"), (None, None))


if __name__ == "__main__":
    unittest.main()
