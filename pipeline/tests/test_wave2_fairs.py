from __future__ import annotations

import sqlite3
import unittest

from artrend_mag import db

from artrend_mag.sources import wave2_fairs as fairs


ZSONAMACO_HOME = """<main class="site-main">
<h2>PRÓXIMA EDICIÓN DE ZⓈONAMACO</h2><h3>3 – 7 de Febrero 2027</h3>
<h2>PRÓXIMAS EDICIONES</h2><p>2027 3 – 7 DE FEBRERO 2028 9 – 13 DE FEBRERO 2029 7 – 11 DE FEBRERO</p>
</main>"""
ZSONAMACO_TICKETS = """<main class="site-main">
<h2>HORARIOS</h2><p>3 AL 7 DE FEBRERO I 2027</p>
<h2>UBICACIÓN</h2><p>CENTRO BANAMEX</p>
<p>AVENIDA DEL CONSCRIPTO 311, LOMAS DE SOTELO, 11200 MIGUEL HIDALGO, CDMX</p>
</main>"""

SP_ARTE_ROTAS = """<html><head><title>Histórico Rotas 2026 - SP-Arte</title></head><body>
<main><h1>SP-Arte Rotas 2026</h1>
<p>Realizada entre 26 e 30 de agosto, na ARCA, em São Paulo, a feira reuniu 78 expositores.</p>
</main></body></html>"""

ARTISSIMA_HOME = """<html><head><title>Artissima 2026 | Fiera d'Arte Contemporanea, Torino</title></head><body>
<h1>Artissima 2026 | Fiera d'Arte Contemporanea, Torino</h1>
<p>30.10 – 1.11.2026</p><p>Artissima 2026 Oval Lingotto Fiere</p>
</body></html>"""
ARTISSIMA_EXHIBITORS = """<html><head><title>Elenco Espositori Artissima 2026</title></head><body>
<table class="tablepress tablepress-id-181"><tbody>
<tr><th class="column-1">SECTION</th><th class="column-2">ORDER</th><th class="column-3">GALLERY NAME</th><th class="column-4">GALLERY</th><th class="column-5">URL</th><th class="column-6">CITY</th><th class="column-7">STATE</th></tr>
<tr><td class="column-1">Main Section</td><td class="column-2">1/9unosunove</td><td class="column-3">1/9unosunove</td><td class="column-4"><a href="https://www.artissima.art/galleries/unosunove/">1/9UNOSUNOVE, Roma</a></td><td class="column-5">https://www.artissima.art/galleries/unosunove/</td><td class="column-6">Roma</td><td class="column-7">ITA</td></tr>
</tbody></table></body></html>"""

ACK_VISITOR = """<main class="l-main">
<h2>開催日程</h2><p>2026年11月7日（土）−9日（月）</p>
<h2>会場</h2><p>国立京都国際会館</p><p>606-0001 京都市左京区宝ヶ池</p>
</main>"""
ACK_EXHIBITORS = """<main class="l-main"><a href="https://art-ap.passes.jp/user/e/ack2026/">Tickets</a>
<div class="exhibitors-gallery-item _gallery-collaborations">
<a class="exhibitors-gallery-item_link" href="https://a-c-k.jp/exhibitors/anomaly-rolandross/">
<div class="exhibitors-gallery"><p class="exhibitors-gallery_heading">Host</p><div class="exhibitors-gallery_title"><p class="exhibitors-gallery_name">ANOMALY</p><p class="exhibitors-gallery_site">（東京）</p></div></div>
<div class="exhibitors-gallery"><p class="exhibitors-gallery_heading">Guest</p><div class="exhibitors-gallery_title"><p class="exhibitors-gallery_name">Roland Ross</p><p class="exhibitors-gallery_site">（マーゲート）</p></div></div>
</a></div></main>"""

TOKYOGENDAI_HIGHLIGHTS = """<html><body><h2>Fair Overview</h2>
<p>The fourth edition of Tokyo Gendai took place from 11 to 13 September 2026
(VIP Preview and Vernissage on 10 September 2026) at PACIFICO Yokohama.</p>
</body></html>"""
TOKYOGENDAI_2023 = """<p>The inaugural edition of Tokyo Gendai was held from 7 – 9 July 2023 at PACIFICO Yokohama.</p>"""
TOKYOGENDAI_2024 = """<p>The second edition of Tokyo Gendai was held from 5 – 7 July, 2024
(VIP Preview and Vernissage on 4 July) at PACIFICO Yokohama.</p>"""
TOKYOGENDAI_2025 = """<p>The third edition of Tokyo Gendai was held from 12 – 14 September, 2025
(VIP Preview and Vernissage on 11 September) at PACIFICO Yokohama.</p>"""
TOKYOGENDAI_GALLERIES = """<html><body><h1>2026 Exhibiting Galleries</h1>
<article class="gallery-main"><section class="section-gallery" sector="galleries"><h2>Galleries</h2>
<ul class="list-gallery"><li class="item" data-id="68798"><a href="https://lighthouse-kanata.com/en">
<div class="box-text"><p class="title text-en-body-2">A Lighthouse called Kanata</p><p class="location text-en-note">Tokyo</p><p class="sector text-en-note" sector="Galleries">Galleries</p></div>
</a></li></ul></section></article></body></html>"""

ART_WEEK_TOKYO_EVENTS = """<html><head><title>EVENTS | アートウィーク東京 | ART WEEK TOKYO | NOVEMBER 4–8, 2026</title></head>
<body><main class="l-main"><p>会期中は東京各地で多彩なプログラムが連日開催されます。</p></main></body></html>"""

ART_BUSAN_ABOUT = """<main><h2>ART BUSAN 2027 Opening Hours</h2>
<p>April 23 (Fri) - 25 (Sun), 2027</p><h2>Venue</h2>
<p>BEXCO 1st Exhibition Hall (55, APEC-ro, Haeundae-gu, Busan)</p></main>"""

ARCO_MADRID_HOME = """<html><head><title>ARCO MADRID 2027 | Feria de arte contemporáneo en Madrid</title></head>
<body><p>ARCOmadrid se celebrará del 3 al 7 de marzo de 2027 en IFEMA MADRID.</p></body></html>"""

DOCUMENTA_16_NEWS = """<html><head><title>DOCUMENTA SIXTEEN takes shape | documenta</title></head><body>
<p>From June 12 to September 19, 2027, the 16th edition of documenta (D16) will take place in Kassel under the Artistic Direction of Naomi Beckwith.</p>
</body></html>"""
MANIFESTA_16_ABOUT = """<html><head><title>Manifesta 16 Ruhr – Manifesta</title></head><body>
<h2>About Manifesta 16 Ruhr</h2>
<p>This is not a church takes place from the 21st of June until the 4th of October 2026 across four cities in Germany’s Ruhr Area: Duisburg, Essen, Gelsenkirchen and Bochum.</p>
</body></html>"""
MANIFESTA_16_PARTICIPANTS = """<html><head><title>Manifesta 16 Ruhr – Manifesta</title></head><body><h1>Participants</h1>
<ul class="app-components-pages-editions-slug-participants-list--root---Iged">
<li><ul><li><a href="/editions/manifesta-ruhr/participants/2462">Mehmet Aksoy, TR</a></li>
<li><a href="/editions/manifesta-ruhr/participants/2468">Begzada Alatović, BA</a></li></ul></li></ul></body></html>"""


class Wave2FairObservedMarkupTests(unittest.TestCase):
    def test_source_ids_are_unique_and_have_no_blueprint_data_guess(self):
        source_ids = [source["source_id"] for source in fairs.SOURCES]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertTrue(all(source["blueprint_data_id"] is None for source in fairs.SOURCES))

    def test_arcomadrid_uses_only_explicit_2027_dates_and_venue(self):
        record = fairs._parse_arcomadrid(ARCO_MADRID_HOME)
        self.assertEqual(record["title"], "ARCOmadrid 2027")
        self.assertEqual(record["venue"], "IFEMA MADRID")
        self.assertEqual(fairs._event_dates(record), ("2027-03-03", "day", "2027-03-07", "day"))

    def test_mediacity_stays_disabled_when_fetcher_cannot_evaluate_robots(self):
        source = next(source for source in fairs.SOURCES if source["source_id"] == "wave2_mediacity_seoul_biennale")
        self.assertEqual(source["operational_state"], "blocked_access")
        self.assertEqual(source["robots_status"], "robots_error(ConnectionError)")
        self.assertEqual(source["blueprint_data_id"], None)

    def test_zsonamaco_uses_next_edition_date_and_its_actual_venue(self):
        record = fairs._parse_zsonamaco(ZSONAMACO_HOME, ZSONAMACO_TICKETS)
        self.assertEqual(record["title"], "ZⓈONAMACO 2027")
        self.assertEqual(record["venue"], "Centro Banamex")
        self.assertEqual(record["location_excerpt"], "11200 MIGUEL HIDALGO, CDMX")
        self.assertEqual(fairs._event_dates(record), ("2027-02-03", "day", "2027-02-07", "day"))

    def test_zsonamaco_future_years_keep_dates_without_inferred_venues(self):
        records = fairs._parse_zsonamaco_future_editions(ZSONAMACO_HOME)
        self.assertEqual([record["year"] for record in records], [2028, 2029])
        self.assertEqual(records[0]["venue"], None)
        self.assertEqual(fairs._event_dates(records[0]), ("2028-02-09", "day", "2028-02-13", "day"))
        self.assertEqual(fairs._event_dates(records[1]), ("2029-02-07", "day", "2029-02-11", "day"))

    def test_sp_arte_rotas_uses_displayed_period_and_title_year(self):
        record = fairs._parse_sp_arte(SP_ARTE_ROTAS)
        self.assertEqual(record["venue"], "ARCA")
        self.assertEqual(fairs._event_dates(record), ("2026-08-26", "day", "2026-08-30", "day"))

    def test_artissima_edition_and_exhibitor_are_year_linked(self):
        record = fairs._parse_artissima(ARTISSIMA_HOME)
        rows = fairs._parse_artissima_exhibitors(ARTISSIMA_EXHIBITORS)
        self.assertEqual(fairs._event_dates(record), ("2026-10-30", "day", "2026-11-01", "day"))
        self.assertIn("Torino", record["location_excerpt"])
        self.assertEqual(rows, [("1/9UNOSUNOVE", "https://www.artissima.art/galleries/unosunove/")])

    def test_ack_japanese_range_and_collaboration_gallery_names(self):
        record = fairs._parse_ack(ACK_VISITOR)
        rows = fairs._parse_ack_exhibitors(ACK_EXHIBITORS)
        self.assertEqual(fairs._event_dates(record), ("2026-11-07", "day", "2026-11-09", "day"))
        self.assertEqual(record["location_excerpt"], "606-0001 京都市左京区宝ヶ池")
        self.assertEqual([name for name, _ in rows], ["ANOMALY", "Roland Ross"])

    def test_tokyo_gendai_has_explicit_venue_and_edition_roster(self):
        record = fairs._parse_tokyogendai(TOKYOGENDAI_HIGHLIGHTS)
        rows = fairs._parse_tokyogendai_exhibitors(TOKYOGENDAI_GALLERIES, 2026)
        self.assertEqual(record["venue"], "PACIFICO Yokohama")
        self.assertEqual(fairs._event_dates(record), ("2026-09-11", "day", "2026-09-13", "day"))
        self.assertEqual([name for name, _ in rows], ["A Lighthouse called Kanata"])

    def test_tokyo_gendai_confirmed_archive_editions_keep_their_own_years(self):
        records = [fairs._parse_tokyogendai(page) for page in
                   (TOKYOGENDAI_2023, TOKYOGENDAI_2024, TOKYOGENDAI_2025)]
        self.assertEqual([record["year"] for record in records], [2023, 2024, 2025])
        self.assertEqual(fairs._event_dates(records[0]), ("2023-07-07", "day", "2023-07-09", "day"))
        self.assertEqual(fairs._event_dates(records[1]), ("2024-07-05", "day", "2024-07-07", "day"))
        self.assertEqual(fairs._event_dates(records[2]), ("2025-09-12", "day", "2025-09-14", "day"))

    def test_art_week_is_one_city_wide_edition_with_displayed_dates(self):
        record = fairs._parse_art_week(ART_WEEK_TOKYO_EVENTS)
        self.assertEqual(record["event_type"], "program")
        self.assertIsNone(record["venue"])
        self.assertIn("東京各地", record["location_excerpt"])
        self.assertEqual(fairs._event_dates(record), ("2026-11-04", "day", "2026-11-08", "day"))

    def test_art_busan_uses_the_displayed_venue_and_period(self):
        record = fairs._parse_artbusan(ART_BUSAN_ABOUT)
        self.assertEqual(record["venue"], "BEXCO 1st Exhibition Hall")
        self.assertIn("Busan", record["location_excerpt"])
        self.assertEqual(fairs._event_dates(record), ("2027-04-23", "day", "2027-04-25", "day"))

    def test_documenta_16_stores_confirmed_date_and_actual_host_city(self):
        record = fairs._parse_documenta(DOCUMENTA_16_NEWS)
        self.assertEqual(record["title"], "documenta 16")
        self.assertEqual(record["city"], "Kassel")
        self.assertIsNone(record["venue"])
        self.assertEqual(record["location_excerpt"], "take place in Kassel")
        self.assertEqual(fairs._event_dates(record), ("2027-06-12", "day", "2027-09-19", "day"))

    def test_manifesta_16_keeps_multi_city_location_and_explicit_participants(self):
        record = fairs._parse_manifesta(MANIFESTA_16_ABOUT)
        rows = fairs._parse_manifesta_participants(MANIFESTA_16_PARTICIPANTS)
        self.assertIsNone(record["city"])
        self.assertEqual(record["country_code"], "DE")
        self.assertEqual(record["location_excerpt"], "across four cities in Germany’s Ruhr Area: Duisburg, Essen, Gelsenkirchen and Bochum")
        self.assertEqual(fairs._event_dates(record), ("2026-06-21", "day", "2026-10-04", "day"))
        self.assertEqual([name for name, _ in rows], ["Mehmet Aksoy", "Begzada Alatović"])


class _StoreResponse:
    url = "https://www.ifema.es/en/arco-madrid"
    fetched_at = "2026-10-28T09:00:00+09:00"
    status = 200
    raw_path = None
    sha256 = "0" * 64


class _StoreContext:
    def __init__(self, con, source_id):
        self.con = con
        self.source_id = source_id
        self.stats = {}
        self.parser_version = fairs.PARSER_VERSION

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def evidence(self, resp, locator=None, excerpt=None):
        return db.add_evidence(self.con, source_id=self.source_id, url=resp.url, fetched_at=resp.fetched_at,
                               http_status=resp.status, raw_path=resp.raw_path, raw_sha256=resp.sha256,
                               locator=locator, excerpt=excerpt, parser_version=self.parser_version)


class Wave2FairStorageTests(unittest.TestCase):
    def test_displayed_venue_is_stored_as_a_venue_row_under_foreign_keys(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        con.execute("PRAGMA foreign_keys=ON")
        source_id = "wave2_arcomadrid_fair"
        row = next(r for r in fairs.SOURCES if r["source_id"] == source_id)
        db.upsert_source(con, source_id, **{k: v for k, v in row.items() if k in db.SOURCE_FIELDS + db.STATUS_FIELDS})
        ctx = _StoreContext(con, source_id)
        record = fairs._parse_arcomadrid(ARCO_MADRID_HOME)
        record.setdefault("locator", "fixture")
        organizer = db.ensure_entity(con, entity_type="organization", name="IFEMA", namespace="src:" + source_id,
                                     id_value="organizer", source_id=source_id)
        event_id, _ = fairs._store_event(ctx, organizer, _StoreResponse(), record, key="2027")
        venue = con.execute("SELECT v.name, v.owner_entity_id, e.entity_type FROM events ev "
                            "JOIN venues v ON v.venue_id=ev.venue_id "
                            "JOIN entities e ON e.entity_id=v.owner_entity_id WHERE ev.event_id=?",
                            (event_id,)).fetchone()
        self.assertEqual((venue["name"], venue["entity_type"]), ("IFEMA MADRID", "venue"))
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        fairs._store_event(ctx, organizer, _StoreResponse(), record, key="2027")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM venues").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
