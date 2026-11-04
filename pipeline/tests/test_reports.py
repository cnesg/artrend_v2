import unittest
from types import SimpleNamespace

from artrend_mag.http import Blocked
from artrend_mag.sources.reports import (
    DELOITTE_PUBLIC_PDFS,
    TEFAF_REPORTS,
    _deloitte_public_pdfs,
    _deloitte_registration_url,
    _kartmarket_attachment_links,
    _kartmarket_detail,
    _kartmarket_detail_url,
    _kartmarket_entries,
    _kartmarket_rights,
    _observation_period,
    collect,
)


class ReportSourceTests(unittest.TestCase):
    def test_kartmarket_listing_entries_are_unique_and_keep_title(self):
        html = """
        <div class="list-name">
          <a href="javascript:fnView('BRD_ID0002366');">「2026 미술시장조사」 (2025년도 기준)</a>
        </div>
        <div class="list-name">
          <a href="javascript:fnView('BRD_ID0002366');">duplicate</a>
        </div>
        <div class="list-name"><a href="javascript:fnView('BRD_ID0002317');">2025 미술시장조사</a></div>
        """
        self.assertEqual(
            _kartmarket_entries(html),
            [("BRD_ID0002366", "「2026 미술시장조사」 (2025년도 기준)"),
             ("BRD_ID0002317", "2025 미술시장조사")],
        )

    def test_detail_url_uses_public_get_query_and_validates_board_id(self):
        self.assertEqual(
            _kartmarket_detail_url("https://k-artmarket.kr/member/board/Analysis_BoardList.do", "BRD_ID0002366"),
            "https://k-artmarket.kr/member/board/Analysis_BoardView.do?boardId=BRD_ID0002366",
        )
        with self.assertRaises(ValueError):
            _kartmarket_detail_url("https://k-artmarket.kr/member/board/Analysis_BoardList.do", "../private")

    def test_observation_period_requires_explicit_basis(self):
        self.assertEqual(_observation_period("「2026 미술시장조사」 (2025년도 기준)"), "2025")
        self.assertIsNone(_observation_period("2025 미술시장조사"))

    def test_detail_requires_matching_record_and_extracts_rights_text(self):
        html = """
        <input id="boardId" value="BRD_ID0002366">
        <div class="view-title-box"><div class="view-img-tit"><div class="cont">
          <div class="tit">「2026 미술시장조사」 (2025년도 기준)</div>
        </div></div></div>
        <p>저작물은 공공누리 출처표시 조건에 따라 이용 할 수 있습니다.</p>
        <p>승인 없이 상업적인 목적으로 사용하거나 판매할 수 없습니다.</p>
        <p>무단 복제나 도용은 저작권법에 의해 금지되어 있습니다.</p>
        """
        detail = _kartmarket_detail(html, "BRD_ID0002366", "fallback")
        self.assertEqual(detail["title"], "「2026 미술시장조사」 (2025년도 기준)")
        self.assertEqual(_observation_period(detail["text"]), "2025")
        self.assertIn("공공누리 출처표시", _kartmarket_rights(detail["text"]))
        self.assertIn("상업적 이용·판매 금지", _kartmarket_rights(detail["text"]))
        self.assertIsNone(_kartmarket_detail(html, "BRD_ID0002317", "fallback"))

    def test_only_explicit_official_file_anchors_are_attachment_candidates(self):
        html = """
        <img src="/common/attachFile/getAttachFileDownLoad.do?fileId=THUMBNAIL">
        <a href="/common/attachFile/getAttachFileDownLoad.do?fileId=REPORT">보고서 PDF</a>
        <a href="https://www.gokams.or.kr/files/report.pdf">official report</a>
        <a href="https://mirror.example/report.pdf">mirror</a>
        <a href="https://forms.gle/example">print request</a>
        """
        self.assertEqual(
            _kartmarket_attachment_links(html, "https://k-artmarket.kr/member/board/Analysis_BoardView.do"),
            ["https://www.gokams.or.kr/files/report.pdf",
             "https://k-artmarket.kr/common/attachFile/getAttachFileDownLoad.do?fileId=REPORT"],
        )

    def test_deloitte_discovery_accepts_only_public_official_pdf_links(self):
        html = """
        <a href="/content/dam/assets-zone2/lu/en/report.pdf?download=1">download report</a>
        <a href="https://form.deloitte.lu/assets/gated.pdf">form asset</a>
        <a href="https://mirror.example/report.pdf">mirror</a>
        """
        self.assertEqual(
            _deloitte_public_pdfs(html, "https://www.deloitte.com/lu/en/report-page.html"),
            {"/content/dam/assets-zone2/lu/en/report.pdf":
             "https://www.deloitte.com/content/dam/assets-zone2/lu/en/report.pdf?download=1"},
        )

    def test_deloitte_registration_link_is_recorded_without_form_submission(self):
        html = '<a href="https://form.deloitte.lu/art-and-finance-2025-report.html?source=page">2025 edition</a>'
        self.assertEqual(
            _deloitte_registration_url(html, "https://www.deloitte.com/lu/en/report-page.html"),
            "https://form.deloitte.lu/art-and-finance-2025-report.html?source=page",
        )
        self.assertIsNone(_deloitte_registration_url(
            '<a href="https://form.deloitte.lu/other.html">Other form</a>',
            "https://www.deloitte.com/lu/en/report-page.html",
        ))

    def test_new_sources_use_stable_report_ids_and_do_not_infer_periods(self):
        self.assertEqual([row[0] for row in DELOITTE_PUBLIC_PDFS],
                         ["DAF2023", "DAF2021", "DAF2019", "DAF2017", "DAF2016", "DAF2014", "DAF2013", "DAF2011"])
        self.assertEqual(DELOITTE_PUBLIC_PDFS[0][3], "July 2023 (expert survey); market data includes 2022")
        self.assertIsNone(DELOITTE_PUBLIC_PDFS[1][3])
        self.assertEqual(DELOITTE_PUBLIC_PDFS[2][3], "April–June 2019 (research and survey)")
        self.assertEqual(len({row[0] for row in TEFAF_REPORTS}), len(TEFAF_REPORTS))
        self.assertTrue(all(row[2].startswith("https://static.tefaf.com/") for row in TEFAF_REPORTS))

    def test_tefaf_terms_and_robots_block_before_any_fetch(self):
        ctx = SimpleNamespace(
            source_id="rpt_tefaf_market_reports",
            meta={"entry_url": "https://www.tefaf.com/foundation/art-market-report"},
        )
        with self.assertRaises(Blocked) as raised:
            collect(ctx)
        self.assertEqual((raised.exception.kind, raised.exception.status), ("robots_disallow", 403))
        self.assertIn("without express written consent", raised.exception.detail)
        self.assertIn("TEFAF2020_ART_PATRONAGE", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
