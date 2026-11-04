from __future__ import annotations

import json
import sqlite3
import unittest

from artrend_mag import db
from artrend_mag.sources import wave2_reports as w


NEA_CARD = """
<article class="teaser"><a class="teaser__link" href="/impact/research/publications/arts-participation-2022-technical-summary-report">
<div class="teaser__row"><div class="teaser__content"><div class="teaser__meta"><div class="teaser__tag">Publication</div><div class="teaser__date">2025</div></div>
<div class="teaser__title"><span>Arts Participation in 2022: A Technical Summary Report</span></div>
<div class="teaser__summary">This report provides detailed analysis of survey data.</div></div></div></a></article>
"""

CANADA_INDEX = """
<a href="/en/canadian-heritage/corporate/publications/general-publications/about-survey-heritage-institutions/2021-report.html">Government of Canada Survey of Heritage Institutions: 2021 Report</a>
<a href="/en/canadian-heritage/corporate/publications/general-publications/about-survey-heritage-institutions/2017-report.html">Government of Canada Survey of Heritage Institutions: 2017 Report</a>
"""

CANADA_DETAIL = """
<meta name="dcterms.title" content="Government of Canada Survey of Heritage Institutions: 2021">
<meta name="dcterms.issued" content="2023-07-17"><h1 id="wb-cont">Government of Canada Survey of Heritage Institutions: 2021</h1>
<a class="gc-dwnld-lnk" download="" href="/content/dam/pch/documents/corporate/publications/general-publications/about-survey-heritage-institutions/2021-GCSHI-Final-Report-eng.pdf">PDF version</a>
"""

IMLS_CARD = """
<div class="grid-row image_left"><div class="field field--name-field-title-image-content">National Museum Survey (NMS)</div>
<div class="field field--name-field-body-image-content"><p>This national survey includes art museums.</p></div>
<div class="field field--name-field-link-image-content"><a href="/research-evaluation/surveys/national-museum-survey-nms">View Survey</a></div></div>
"""

IBERMUSEOS_DETAIL = """
<h1>Panorama de los museos en Iberoamérica. Edición 2020</h1>
<div class="side-col-item"><h5 class="heading">Fecha</h5><p>Noviembre de 2023</p></div>
<div class="side-col-item"><h5 class="heading">Número de Páginas</h5><p>124</p></div>
<a href="https://www.ibermuseos.org/wp-content/uploads/2021/03/panorama-de-museus-2020.pdf">Versión en Español</a>
"""

NCAR_INDEX = """
<main><div class="ncar-buttons"><a href="/reports/20260520.html"><span class="ncar-buttons__label">2025年度「美術館に関する意識調査」調査結果</span></a>
<a href="/reports/20250630.html"><span class="ncar-buttons__label">2024年度「美術館に関する意識調査」調査結果</span></a>
<a href="/reports/?category=awareness-surveys">すべての活動レポート</a></div></main>
"""

BUNKA_LISTING = """
<ul><li><a href="pdf/r1393019_02.pdf">国家ブランドに関する指標調査</a></li>
<li><a href="pdf/h29_kinokyoka_hokokusho.pdf">文化庁の機能強化に向けた海外事例調査報告書</a></li>
<li><a href="/tokei_hakusho_shuppan/hakusho_nenjihokokusho/index.html">白書・年次報告等</a></li></ul>
"""

ARKO_LISTING = """
<a href="/board/view/5034?bid=&amp;page=&amp;cid=1806859">2022년도 한국문화예술위원회 연차보고서(국문, ENG, 점자파일)</a>
<a href="/board/list/5034">연차보고서</a>
"""

KIAF_REPORT = """
<div class="row section"><div class="col-md-6"><p>After the closing of Kiaf SEOUL 2021, Kiaf Operating Committee conducted a survey. Kiaf REPORT 2021 is a study.</p>
<a href="https://static-edge.kiaf.org/web/2021/12/19002451/Kiaf-Report-kor.pdf" class="btn-link">DOWNLOAD Kiaf REPORT (KOR)</a>
<a href="https://static-edge.kiaf.org/web/2021/12/19001632/Kiaf-Report-Eng.pdf" class="btn-link">DOWNLOAD Kiaf REPORT (ENG)</a></div></div>
"""

STATCAN_CUBES = [
    {"productId": 10100159, "cubeTitleEn": "Federal government expenditures on culture, by culture activity",
     "cubeTitleFr": "Dépenses fédérales au titre de la culture", "cubeStartDate": "1998-01-01T05:00:00Z",
     "cubeEndDate": "2002-01-01T05:00:00Z", "issueDate": "2017-02-21T05:00:00Z"},
    {"productId": 10100002, "cubeTitleEn": "Central government debt", "cubeStartDate": "2009-04-01T04:00:00Z",
     "cubeEndDate": "2026-07-01T04:00:00Z", "issueDate": "2026-10-05T04:00:00Z"},
]

EUROSTAT_DOMAIN = """
<nav><a href="/eurostat/web/culture/database">Database</a></nav>
<main><a href="https://ec.europa.eu/eurostat/databrowser/bookmark/2069ef72-1a3d-40f7-b8ef-3ab4bfed8aa6?lang=en">Sound recording and music publishing activities (NACE code 59.2)</a>
<a href="https://ec.europa.eu/eurostat/databrowser/bookmark/d3d22a8d-f9bb-40a3-a47f-968844174e67?lang=en">Employment in libraries, archives, museums and other cultural activities</a>
<a href="/eurostat/documents/341465/12708832/LFS_Table1_2024_NACE_581.xlsx">Publishing of books, periodicals and other publishing activities</a></main>
"""

GOKAMS_LISTING = """
<table class="boardList"><tbody>
<tr><td>780</td><td><img alt="연구" class="middle" src="../images/icon/ico_data03.gif"></td>
<td class="left"><a href="data_view.aspx?Idx=1276&amp;flag=0&amp;page=2&amp;txtKeyword=&amp;ddlKeyfield=T">국외미술관 한국 현대미술 작품 소장 현황 및 확대 방안 연구 (영국, 프랑스)</a></td>
<td>2025.12</td><td><a href="javascript:" onclick="fnFiledown('/artnews_upload/','report.pdf','1276')">PDF</a></td><td>1519</td></tr>
<tr><td>779</td><td></td><td class="left"><a href="data_view.aspx?Idx=1250">웹진 최근 소식</a></td><td>2025.12</td><td></td><td>0</td></tr>
</tbody></table>
"""


class ParserTests(unittest.TestCase):
    def test_nea_teaser_extracts_publication_metadata_not_summary(self):
        records = w.parse_nea_publications(NEA_CARD, "https://www.arts.gov/impact/research/publications")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Arts Participation in 2022: A Technical Summary Report")
        self.assertEqual(records[0]["published_date"], "2025")
        self.assertNotIn("survey data", str(records[0]))

    def test_canada_index_and_page_preserve_year_and_direct_link_without_fetching_pdf(self):
        base = "https://www.canada.ca/en/canadian-heritage/corporate/publications/general-publications/about-survey-heritage-institutions.html"
        entries = w.parse_canada_heritage_index(CANADA_INDEX, base)
        self.assertEqual([item["year"] for item in entries], [2021, 2017])
        detail = w.parse_canada_heritage_report(CANADA_DETAIL, entries[0]["url"])
        self.assertEqual(detail["published_date"], "2023-07-17")
        self.assertTrue(detail["pdf_url"].endswith("2021-GCSHI-Final-Report-eng.pdf"))

    def test_statcan_filters_catalog_to_named_cultural_products(self):
        records = w.parse_statcan_cubes(STATCAN_CUBES)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["key"], "10100159")
        self.assertEqual(records[0]["observation_period"], "1998-01-01 to 2002-01-01")
        self.assertEqual(records[0]["published_date"], "2017-02-21")

    def test_eurostat_culture_domain_records_catalogue_links_only(self):
        records = w.parse_eurostat_culture_domain(EUROSTAT_DOMAIN, "https://ec.europa.eu/eurostat/web/culture/database/data-domain")
        self.assertEqual(len(records), 3)
        self.assertEqual(records[1]["title"], "Employment in libraries, archives, museums and other cultural activities")
        self.assertEqual(records[2]["official_url"], "https://ec.europa.eu/eurostat/documents/341465/12708832/LFS_Table1_2024_NACE_581.xlsx")
        self.assertIsNone(records[0]["observation_period"])

    def test_gokams_publication_listing_keeps_report_metadata_and_ignores_js_download(self):
        records = w.parse_gokams_listing(GOKAMS_LISTING, "https://www.gokams.or.kr/05_know/data_list.aspx")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["key"], "1276")
        self.assertEqual(records[0]["published_date"], "2025-12")
        self.assertIn("data_view.aspx?Idx=1276", records[0]["official_url"])
        self.assertNotIn("javascript:", records[0]["official_url"])

    def test_imls_cards_capture_only_card_title_and_url(self):
        records = w.parse_imls_cards(IMLS_CARD, "https://www.imls.gov/research-evaluation/surveys")
        self.assertEqual(records, [{
            "key": "https://www.imls.gov/research-evaluation/surveys/national-museum-survey-nms",
            "title": "National Museum Survey (NMS)",
            "official_url": "https://www.imls.gov/research-evaluation/surveys/national-museum-survey-nms",
            "access_status": "link_only(public IMLS catalogue card; destination not fetched)",
        }])

    def test_ibermuseos_publication_side_metadata_and_pdf_anchor(self):
        detail = w.parse_ibermuseos_publication(
            IBERMUSEOS_DETAIL, "https://www.ibermuseos.org/recursos/publicaciones/panorama-de-los-museos-en-iberoamerica-edicion-2020/"
        )
        self.assertEqual(detail["title"], "Panorama de los museos en Iberoamérica. Edición 2020")
        self.assertEqual(detail["published_date"], "2023-11")
        self.assertEqual(detail["pages"], 124)
        self.assertTrue(detail["pdf_url"].endswith("panorama-de-museus-2020.pdf"))

    def test_ncar_annual_survey_index(self):
        records = w.parse_ncar_awareness_index(NCAR_INDEX, "https://ncar.artmuseums.go.jp/research/awareness-surveys.html")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["observation_period"], "2025年度 (as titled)")

    def test_bunka_and_arko_only_accept_official_report_entry_links(self):
        bunka = w.parse_bunka_listing(BUNKA_LISTING, "https://www.bunka.go.jp/tokei_hakusho_shuppan/tokeichosa/index.html")
        self.assertEqual(len(bunka), 2)
        self.assertTrue(all(item["official_url"].startswith("https://www.bunka.go.jp/") for item in bunka))
        arko = w.parse_arko_listing(ARKO_LISTING, "https://www.arko.or.kr/board/list/5034")
        self.assertEqual(len(arko), 1)
        self.assertIn("2022년도", arko[0]["title"])

    def test_kiaf_only_records_official_linked_language_variants(self):
        records = w.parse_kiaf_reports(KIAF_REPORT, "https://kiaf.org/en/about-report")
        self.assertEqual([record["title"] for record in records], ["Kiaf REPORT 2021 (Korean)", "Kiaf REPORT 2021 (English)"])
        self.assertTrue(all(record["official_url"].startswith("https://static-edge.kiaf.org/") for record in records))


class Response:
    def __init__(self, url, body):
        self.url = self.final_url = url
        self.status = 200
        self.content = body.encode("utf-8")
        self.text = body
        self.content_type = "application/json"
        self.fetched_at = "2026-10-28T00:00:00+00:00"
        self.sha256 = "fixture-sha"
        self.raw_path = None

    def json(self):
        return json.loads(self.content)


class Context:
    def __init__(self, con, source_id, pages):
        self.con, self.source_id, self.pages = con, source_id, pages
        self.meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
        self.mode = "initial"
        self.stats, self.notes, self.calls = {}, [], []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected fetch {url}")
        return Response(url, self.pages[url])

    def evidence(self, *args, **kwargs):
        return "fixture-evidence"

    def count(self, key, count=1):
        self.stats[key] = self.stats.get(key, 0) + count

    def note(self, message):
        self.notes.append(message)


class StoredPDFContext(Context):
    def fetch(self, url, **kwargs):
        response = super().fetch(url, **kwargs)
        self.fetch_kwargs = kwargs
        response.content = b"%PDF-1.7 fixture"
        response.content_type = "application/pdf"
        response.raw_path = "raw/wave2_reports_canada_heritage/fixture.pdf"
        return response


class CollectTests(unittest.TestCase):
    def test_registry_ids_and_source_policy(self):
        ids = [row["source_id"] for row in w.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(row["blueprint_data_id"] is None for row in w.SOURCES))
        policies = {row["source_id"]: row["text_storage_policy"] for row in w.SOURCES}
        self.assertEqual(policies["wave2_reports_canada_heritage"], "raw_internal")
        self.assertTrue(all(policy == "metadata_only" for source_id, policy in policies.items()
                            if source_id != "wave2_reports_canada_heritage"))

    def test_statcan_collect_stores_filtered_metadata_and_never_requests_cube_values(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        url = "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite"
        ctx = Context(con, "wave2_reports_statcan", {url: json.dumps(STATCAN_CUBES)})
        w.collect(ctx)
        rows = con.execute("SELECT title, official_url, observation_period, access_status FROM reports").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Federal government expenditures on culture, by culture activity")
        self.assertIn("pid=10100159", rows[0]["official_url"])
        self.assertIn("table values not fetched", rows[0]["access_status"])
        self.assertEqual(ctx.calls, [url])
        self.assertEqual(ctx.stats["parsed"], 1)
        con.close()

    def test_permitted_direct_pdf_download_stores_signature_and_never_parses_body(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        url = "https://www.canada.ca/report.pdf"
        ctx = StoredPDFContext(con, "wave2_reports_canada_heritage", {url: "unused"})
        result = w._download_public_pdf(ctx, url)
        self.assertEqual(result["access_status"], "downloaded(public official PDF; no text extraction)")
        self.assertEqual(result["local_path"], "raw/wave2_reports_canada_heritage/fixture.pdf")
        self.assertEqual(ctx.fetch_kwargs, {"accept": "application/pdf", "store": True})
        self.assertEqual(ctx.stats["fetched"], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()
