from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

from artrend_mag import db
from artrend_mag.sources import wave2_residencies as w


STUDIO_2026 = """<html><head><title>Studio Museum Announces Turiya Adkins, Timothy Yanick Hunter, and Clifford Prince King as 2026–27 Artists in Residence | Studio Museum in Harlem</title></head>
<body><h1>Studio Museum Announces Turiya Adkins, Timothy Yanick Hunter, and Clifford Prince King as 2026–27 Artists in Residence</h1></body></html>"""

PIVO_2019 = """<html><head><title>Resultado da convocatória da Bolsa Residência - Pivô Pesquisa 2019</title>
<meta property="article:published_time" content="2023-10-17T17:26:33+00:00"></head><body>
<h1>Resultado da convocatória da Bolsa Residência – Pivô Pesquisa 2019</h1>
<p>O Pivô tem o prazer de anunciar que <b>Alice Yura</b> e <b>Mariana Portela Echeverri</b> são as artistas selecionadas para as bolsas-residências do terceiro ciclo do programa Pivô Pesquisa 2019.</p>
<p><b>Nicanor Aráoz</b> é o artista contemplado na modalidade bolsa-convite pelo Pivô.</p>
</body></html>"""

PIVO_2022 = """<html><head><title>Pivô Pesquisa 2022: boas vindas aos artistas residentes do Ciclo III</title>
<meta property="article:published_time" content="2023-10-17T17:26:33+00:00"></head><body>
<h1>Pivô Pesquisa 2022: boas vindas aos artistas residentes do Ciclo III</h1>
<p>O Pivô dá as boas vindas aos artistas participantes do Ciclo III do programa de residências Pivô Pesquisa 2022
<a href="/residencias/participantes/felipe-rezende/">Felipe Rezende</a>,
<a href="/residencias/participantes/amador-e-jr-seguranca/">Amador e Jr Segurança Patrimonial LTDA</a>,
<a href="/residencias/participantes/moara-tupinamba/">Moara Tupinambá</a> e o curador Tiago Sant’ana, responsável pelo acompanhamento do ciclo.</p>
</body></html>"""

ADIAF_OVERVIEW = """<main><p>Each year, the prize distinguishes one laureate among four artists.</p>
<p>Exhibition of the four nominated artists at Musée d’Art moderne de Paris.</p></main>"""

ADIAF_ARTICLE = """<html><body><h1>Prix Marcel Duchamp 2024 à Art Genève</h1><section id="fade">
<div class="position-relative"><a href="/artistes/abdelkader-benchamma/"></a><p>Abdelkader Benchamma</p></div>
<div class="position-relative"><a href="/artistes/gaelle-choisne/"></a><p>Gaëlle CHOISNE</p></div>
<div class="position-relative"><a href="/artistes/angela-detanico-et-rafael-lain/"></a><p>Angela DETANICO et Rafael LAIN</p></div>
<div class="position-relative"><a href="/artistes/noemie-goudal/"></a><p>Noémie GOUDAL</p></div>
<div class="arts"><p>Les oeuvres des quatre artistes du Prix Marcel Duchamp 2024 sont visibles du 30 janvier au 2 février 2025 à Art Genève.</p></div>
</section></body></html>"""

ADIAF_ROSTER_2024 = """<html><body><ul><li data-sf-field-name="_sfm_date_nomination"><select>
<option value="2024" selected="selected">2024</option></select></li></ul>
<div class="position-relative"><a href="/artistes/abdelkader-benchamma/"></a><p>Abdelkader BENCHAMMA<br>2024</p></div>
<div class="position-relative"><a href="/artistes/gaelle-choisne/"></a><p>Gaëlle CHOISNE<br>Laureate<br>2024</p></div>
<div class="position-relative"><a href="/artistes/angela-detanico-et-rafael-lain/"></a><p>Angela DETANICO et Rafael LAIN<br>2024</p></div>
<div class="position-relative"><a href="/artistes/noemie-goudal/"></a><p>Noémie GOUDAL<br>2024</p></div></body></html>"""

WILLING_WINNER_2024 = """<html><body><h1>박노완, 종근당 예술지상 2024</h1>
<p>박노완 작가가 '종근당 예술지상 2024' 올해의 작가로 선정되었습니다.</p></body></html>"""
WILLING_NOMINEES_2025 = """<html><body><h1>박노완, Kiaf Highlights 최종 3인 선정</h1>
<p>2025년 키아프의 하이라이트 작가 10인에 선정된 박노완 작가가 이동훈, 박그림 작가와 함께 최종 3인의 작가에 선정되었습니다!</p></body></html>"""

BEMIS_AYDO_PROFILE = """<html><head><link rel="canonical" href="https://www.bemiscenter.org/residents/aydo"></head>
<body><main><h1>AYDO</h1><p>Artist-in-Residence</p><p>Artist-in-Residence Fall 2026</p>
<p>AYDO was founded in 2020 by artists A young Yu and Nicholas Oh. The duo combines their expertise.</p></main></body></html>"""

FONDERIE_2026 = """<html><body><div id="main"><div class="archives container">
<a class="archiveSeperator">2026</a>
<div class="archiveElement"><div class="title"><h1><a href="Broydé-Laurence">Laurence Broydé</a></h1></div><div class="text"><h3>Résidence Accès Libre</h3></div></div>
<div class="archiveElement"><div class="title"><h1><a href="Simard-Lhasa">Lhasa Simard</a></h1></div><div class="text"><h3>Résidences Québec-Acadie</h3></div></div>
<a class="archiveSeperator">2025</a>
<div class="archiveElement"><div class="title"><h1><a href="Eybert-Baptiste">Baptiste Eybert</a></h1></div><div class="text"><h3>Résidences Transatlantiques</h3></div></div>
</div></div></body></html>"""

DE_ATELIERS_PEOPLE = """<html><body><main><div class="grid">
<div><div><span>participants</span><span>2026–2028</span></div><ul><li><a href="/en/people/maud-van-baar-de-knegt">Maud van Baar de Knegt</a></li><li><a href="/en/people/mik-bakker">Mik Bakker</a></li></ul></div>
<div><div><span>participants</span><span>2025–2027</span></div><ul><li><a href="/en/people/taiyo-shimizu-larenas">Taiyo Shimizu Larenas</a></li></ul></div>
<div><div><span>staff</span><span>current</span></div><ul><li><a href="/en/people/staff-person">Staff Person</a></li></ul></div>
</div></main></body></html>"""

GASWORKS_ARCHIVE = """<html><body><article class="list-item"><h3>Residency</h3><h2 class="date">6 Jan – 24 Mar 27</h2><h1><a href="/residencies/pedro-neves/">Pedro Neves</a></h1></article>
<article class="list-item"><h3>Residency</h3><h2 class="date">30 Sep – 15 Dec 26</h2><h1><a href="/residencies/river-claure/">River Claure</a></h1></article>
<article class="list-item"><h3>Exhibition</h3><h2 class="date">4 Jan – 28 Feb 27</h2><h1>Not a resident</h1></article></body></html>"""

DELFINA_RESIDENCIES = """<html><body><h1>Current Residencies</h1>
<div class="panel_item"><a class="panel_link" href="https://www.delfinafoundation.com/in-residence/debashree-mukherjee/"></a><div class="panel_content"><h2>Debashree Mukherjee</h2>London: 19/10/2026 — 15/11/2026</div><div class="panel_type post_type_in-residence"></div></div>
<div class="panel_item"><a class="panel_link" href="https://www.delfinafoundation.com/in-residence/haevan-lee/"></a><div class="panel_content"><h2>Haevan Lee</h2>London: 21/09/2026 — 13/12/2026</div><div class="panel_type post_type_in-residence"></div></div>
</body></html>"""

BANKART_EXPLOT = """<html><body><div class="entry-content"><p>会場：ExPLOT Studio（〒220-0012 神奈川県横浜市西区みなとみらい4-3-1）</p>
<h3>ExPLOT Studio 2026 [2026年6月〜2027年3月]<br/>入居作家</h3>
<p>淺井裕介、足立篤史、飯嶋桃代</p></div></body></html>"""

RIJKS_FARREN = """<html><head><meta property="og:title" content="Farren Linhares, 2026–2027"></head><body>
<h1>Farren Linhares</h1><span>resident</span><span>2026 – 2027</span></body></html>"""

DAAD_LINA = """<html><body><nav>Fellows &gt; Award Fellows &gt; Lina Lapelytė</nav><a>→ BKP Award Fellows Overview</a><h1>Lina Lapelytė</h1>
<p>Lithuania, Music &amp; Sound, 2026, in Berlin</p></body></html>"""
DAAD_JAVIER = """<html><body><nav>Fellows &gt; Award Fellows &gt; Javier Areal Vélez</nav><a>→ BKP Award Fellows Overview</a><h1>Javier Areal Vélez</h1>
<p>Argentina, Music &amp; Sound, 2026, in Berlin</p></body></html>"""


class FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.final_url = url
        self.text = text
        self.status_code = 200
        self.fetched_at = "2026-10-28T00:00:00+00:00"
        self.raw_path = None
        self.raw_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeContext:
    mode = "initial"

    def __init__(self, source_id, responses):
        self.source_id = source_id
        self.meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        db.init_schema(self.con)
        source_fields = {key: value for key, value in self.meta.items() if key != "source_id"}
        db.upsert_source(self.con, source_id, **source_fields)
        self.con.commit()
        self.responses = responses
        self.stats = {}
        self.notes = []

    def fetch(self, url, params=None, accept=None):
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        return FakeResponse(url, self.responses[url])

    def evidence(self, response, locator=None, excerpt=None):
        return db.add_evidence(
            self.con, source_id=self.source_id, url=response.final_url,
            fetched_at=response.fetched_at, http_status=response.status_code,
            raw_path=response.raw_path, raw_sha256=response.raw_sha256,
            locator=locator, excerpt=excerpt, parser_version=w.PARSER_VERSION,
        )

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def note(self, message):
        self.notes.append(message)


class ObservedMarkupParserTests(unittest.TestCase):
    def test_studio_residents_and_year_range_keep_year_precision(self):
        row = w.parse_studio_museum(STUDIO_2026)
        self.assertEqual(row["residents"], ["Turiya Adkins", "Timothy Yanick Hunter", "Clifford Prince King"])
        self.assertEqual((row["start"], row["end"], row["date_text"]), ("2026", "2027", "2026–27"))

    def test_pivo_selection_year_is_not_the_later_article_publication_date(self):
        row = w.parse_pivo_announcement(PIVO_2019)
        self.assertEqual(row["year"], "2019")
        self.assertEqual(row["residents"], ["Alice Yura", "Mariana Portela Echeverri"])
        self.assertEqual(row["invite_winner"], "Nicanor Aráoz")

    def test_pivo_resident_markup_excludes_named_curator_from_resident_roles(self):
        row = w.parse_pivo_announcement(PIVO_2022)
        self.assertEqual(row["year"], "2022")
        self.assertEqual(row["residents"], ["Felipe Rezende", "Amador e Jr Segurança Patrimonial LTDA", "Moara Tupinambá"])
        self.assertEqual(row["curator"], "Tiago Sant’ana")

    def test_adiaf_winner_and_nominees_use_2024_award_year_not_2025_exhibition_dates(self):
        article = w.parse_adiaf_article(ADIAF_ARTICLE)
        roster = w.parse_adiaf_roster(ADIAF_ROSTER_2024, "2024")
        self.assertEqual(article["year"], "2024")
        self.assertEqual(len(article["artists"]), 4)
        roles = {row["name"].casefold(): row["role"] for row in roster}
        self.assertEqual(roles["gaëlle choisne"], "winner")
        self.assertEqual(roles["abdelkader benchamma"], "nominee")
        self.assertTrue(w.parse_adiaf_overview(ADIAF_OVERVIEW))

    def test_willing_posts_distinguish_awardee_and_finalists(self):
        winner = w.parse_willing_award(WILLING_WINNER_2024)
        finalists = w.parse_willing_award(WILLING_NOMINEES_2025)
        self.assertEqual((winner["year"], winner["names"], winner["role"]), ("2024", ["박노완"], "winner"))
        self.assertEqual((finalists["year"], finalists["names"], finalists["role"]),
                         ("2025", ["박노완", "이동훈", "박그림"], "nominee"))

    def test_additional_saved_residency_pages_keep_only_explicit_names_and_periods(self):
        bemis = w.parse_bemis_profile(BEMIS_AYDO_PROFILE)
        self.assertEqual((bemis["name"], bemis["year"], bemis["date_text"], bemis["entity_type"]),
                         ("AYDO", "2026", "Fall 2026", "group"))

        fonderie = w.parse_fonderie_by_year(FONDERIE_2026)
        self.assertEqual([(item["name"], item["program"]) for item in fonderie], [
            ("Laurence Broydé", "Résidence Accès Libre"),
            ("Lhasa Simard", "Résidences Québec-Acadie"),
        ])

        ateliers = w.parse_de_ateliers_people(DE_ATELIERS_PEOPLE)
        self.assertEqual([(item["start"], item["end"]) for item in ateliers], [("2026", "2028"), ("2025", "2027")])
        self.assertEqual(sum(len(item["people"]) for item in ateliers), 3)

        gasworks = w.parse_gasworks_archive(GASWORKS_ARCHIVE)
        self.assertEqual([(item["start"], item["end"]) for item in gasworks], [
            ("2027-01-06", "2027-03-24"), ("2026-09-30", "2026-12-15")
        ])

        delfina = w.parse_delfina_residencies(DELFINA_RESIDENCIES)
        self.assertEqual([(item["start"], item["end"]) for item in delfina], [
            ("2026-10-19", "2026-11-15"), ("2026-09-21", "2026-12-13")
        ])

        bankart = w.parse_bankart_explot(BANKART_EXPLOT)
        self.assertEqual((bankart["start"], bankart["end"], bankart["city"], bankart["residents"]),
                         ("2026-06", "2027-03", "Yokohama", ["淺井裕介", "足立篤史", "飯嶋桃代"]))

        rijks = w.parse_rijks_profile(RIJKS_FARREN)
        self.assertEqual((rijks["name"], rijks["start"], rijks["end"]), ("Farren Linhares", "2026", "2027"))

        daad = w.parse_daad_fellow_profile(DAAD_LINA)
        self.assertEqual((daad["name"], daad["year"], daad["excerpt"]),
                         ("Lina Lapelytė", "2026", "Music & Sound, 2026, in Berlin"))


class CollectorTests(unittest.TestCase):
    def test_bemis_collect_stores_group_as_a_fall_2026_resident(self):
        ctx = FakeContext("wave2_bemis_residencies", {w.BEMIS_AYDO: BEMIS_AYDO_PROFILE})
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT event_type,start_date,start_precision FROM events WHERE source_id=?", (ctx.source_id,),
        ).fetchone()
        self.assertEqual(tuple(event), ("residency", "2026", "year"))
        participant = ctx.con.execute(
            "SELECT e.entity_type,p.name_as_listed,p.role FROM event_participants p "
            "JOIN entities e USING(entity_id)"
        ).fetchone()
        self.assertEqual(tuple(participant), ("group", "AYDO", "resident"))

    def test_fonderie_collect_keeps_programs_separate_with_source_profile_ids(self):
        ctx = FakeContext("wave2_fonderie_residencies", {w.FONDERIE_BY_YEAR: FONDERIE_2026})
        w.collect(ctx)
        events = ctx.con.execute("SELECT title,start_date,start_precision FROM events").fetchall()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(row["start_date"] == "2026" and row["start_precision"] == "year" for row in events))
        roles = ctx.con.execute("SELECT name_as_listed,role FROM event_participants").fetchall()
        self.assertEqual({(row["name_as_listed"], row["role"]) for row in roles}, {
            ("Laurence Broydé", "resident"), ("Lhasa Simard", "resident")
        })

    def test_rijks_collect_uses_explicit_profile_range(self):
        ctx = FakeContext("wave2_rijksakademie_residencies", {w.RIJKS_FARREN: RIJKS_FARREN})
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT start_date,start_precision,end_date,end_precision FROM events"
        ).fetchone()
        self.assertEqual(tuple(event), ("2026", "year", "2027", "year"))
        participant = ctx.con.execute("SELECT name_as_listed,role FROM event_participants").fetchone()
        self.assertEqual(tuple(participant), ("Farren Linhares", "resident"))

    def test_daad_collect_stores_only_year_tagged_award_fellows(self):
        ctx = FakeContext("wave2_daad_fellows_2026", {
            w.DAAD_2026_PROFILES[0]: DAAD_LINA,
            w.DAAD_2026_PROFILES[1]: DAAD_JAVIER,
        })
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT event_type,start_date,start_precision,city,country_code FROM events"
        ).fetchone()
        self.assertEqual(tuple(event), ("award", "2026", "year", "Berlin", "DE"))
        participants = ctx.con.execute("SELECT name_as_listed,role FROM event_participants").fetchall()
        self.assertEqual({tuple(row) for row in participants}, {
            ("Lina Lapelytė", "winner"), ("Javier Areal Vélez", "winner")
        })

    def test_de_ateliers_collect_stores_only_participant_cohorts(self):
        ctx = FakeContext("wave2_de_ateliers_residencies", {w.DE_ATELIERS_PEOPLE: DE_ATELIERS_PEOPLE})
        w.collect(ctx)
        events = ctx.con.execute("SELECT start_date,end_date FROM events").fetchall()
        self.assertEqual({(row["start_date"], row["end_date"]) for row in events}, {
            ("2026", "2028"), ("2025", "2027")
        })
        self.assertEqual(ctx.con.execute("SELECT COUNT(*) FROM event_participants").fetchone()[0], 3)

    def test_gasworks_collect_preserves_full_date_precision_for_archive_cycles(self):
        ctx = FakeContext("wave2_gasworks_residencies", {w.GASWORKS_ARCHIVE: GASWORKS_ARCHIVE})
        w.collect(ctx)
        events = ctx.con.execute(
            "SELECT start_date,start_precision,end_date,end_precision FROM events"
        ).fetchall()
        self.assertEqual({tuple(row) for row in events}, {
            ("2027-01-06", "day", "2027-03-24", "day"),
            ("2026-09-30", "day", "2026-12-15", "day"),
        })
        self.assertEqual(ctx.con.execute("SELECT COUNT(*) FROM event_participants").fetchone()[0], 2)

    def test_delfina_collect_records_displayed_dates_and_london_venue(self):
        ctx = FakeContext("wave2_delfina_residencies", {w.DELFINA_RESIDENCIES: DELFINA_RESIDENCIES})
        w.collect(ctx)
        events = ctx.con.execute(
            "SELECT start_date,end_date,city,country_code FROM events"
        ).fetchall()
        self.assertEqual({tuple(row) for row in events}, {
            ("2026-10-19", "2026-11-15", "London", "GB"),
            ("2026-09-21", "2026-12-13", "London", "GB"),
        })
        self.assertEqual(ctx.con.execute("SELECT COUNT(*) FROM event_participants").fetchone()[0], 2)

    def test_bankart_collect_keeps_month_precision_and_explicit_venue(self):
        ctx = FakeContext("wave2_bankart_residencies", {w.BANKART_EXPLOT: BANKART_EXPLOT})
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT start_date,start_precision,end_date,end_precision,city,country_code FROM events"
        ).fetchone()
        self.assertEqual(tuple(event), ("2026-06", "month", "2027-03", "month", "Yokohama", "JP"))
        roles = ctx.con.execute("SELECT name_as_listed,role FROM event_participants").fetchall()
        self.assertEqual({(row["name_as_listed"], row["role"]) for row in roles}, {
            ("淺井裕介", "resident"), ("足立篤史", "resident"), ("飯嶋桃代", "resident")
        })

    def test_studio_collect_stores_only_residents_and_year_range(self):
        ctx = FakeContext("wave2_studio_museum_residencies", {w.STUDIO_2026_PRESS: STUDIO_2026})
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT event_type,start_date,start_precision,end_date,end_precision FROM events WHERE source_id=?",
            (ctx.source_id,),
        ).fetchone()
        self.assertEqual(tuple(event), ("residency", "2026", "year", "2027", "year"))
        roles = ctx.con.execute(
            "SELECT role,name_as_listed FROM event_participants ORDER BY name_as_listed"
        ).fetchall()
        self.assertEqual([(row["role"], row["name_as_listed"]) for row in roles], [
            ("resident", "Clifford Prince King"),
            ("resident", "Timothy Yanick Hunter"),
            ("resident", "Turiya Adkins"),
        ])

    def test_pivo_collect_distinguishes_residents_invited_awardee_and_curator(self):
        ctx = FakeContext("wave2_pivo_residencies", {
            w.PIVO_2019: PIVO_2019,
            w.PIVO_2022: PIVO_2022,
        })
        w.collect(ctx)
        events = ctx.con.execute(
            "SELECT event_type,start_date,start_precision FROM events WHERE source_id=?",
            (ctx.source_id,),
        ).fetchall()
        self.assertEqual(len(events), 3)
        self.assertTrue(all(row["start_precision"] == "year" for row in events))
        roles = ctx.con.execute(
            "SELECT p.name_as_listed,p.role FROM event_participants p JOIN events e USING(event_id) "
            "WHERE e.source_id=?", (ctx.source_id,),
        ).fetchall()
        self.assertEqual({(row["name_as_listed"], row["role"]) for row in roles}, {
            ("Alice Yura", "resident"), ("Mariana Portela Echeverri", "resident"),
            ("Nicanor Aráoz", "winner"), ("Felipe Rezende", "resident"),
            ("Amador e Jr Segurança Patrimonial LTDA", "resident"), ("Moara Tupinambá", "resident"),
            ("Tiago Sant’ana", "curator"),
        })

    def test_adiaf_collect_stores_year_matched_winner_and_nominees(self):
        from urllib.parse import urlencode
        roster_url = f"{w.ADIAF_ARTISTS}?{urlencode({'_sfm_date_nomination': '2024'})}"
        ctx = FakeContext("wave2_adiaf_prize", {
            w.ADIAF_PRIZE_OVERVIEW: ADIAF_OVERVIEW,
            w.ADIAF_2024_ARTICLE: ADIAF_ARTICLE,
            roster_url: ADIAF_ROSTER_2024,
        })
        w.collect(ctx)
        event = ctx.con.execute(
            "SELECT event_type,start_date,start_precision FROM events WHERE source_id=?",
            (ctx.source_id,),
        ).fetchone()
        self.assertEqual(tuple(event), ("award", "2024", "year"))
        roles = ctx.con.execute(
            "SELECT name_as_listed,role FROM event_participants p JOIN events e USING(event_id) "
            "WHERE e.source_id=?", (ctx.source_id,),
        ).fetchall()
        self.assertEqual({row["role"] for row in roles}, {"winner", "nominee"})
        self.assertEqual(len(roles), 4)

    def test_willing_collect_stores_year_precision_and_explicit_roles(self):
        ctx = FakeContext("wave2_willingndealing_awards", {
            w.WILLING_CHONG_KUN_DANG_2024: WILLING_WINNER_2024,
            w.WILLING_KIAF_2025: WILLING_NOMINEES_2025,
        })
        w.collect(ctx)
        events = ctx.con.execute(
            "SELECT event_id,title,event_type,start_date,start_precision FROM events WHERE source_id=? ORDER BY title",
            (ctx.source_id,),
        ).fetchall()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(row["start_precision"] == "year" for row in events))
        self.assertEqual({row["event_type"] for row in events}, {"award", "open_call_selection"})
        roles = ctx.con.execute(
            "SELECT e.title,p.name_as_listed,p.role FROM event_participants p JOIN events e USING(event_id) "
            "WHERE e.source_id=? ORDER BY e.title,p.name_as_listed", (ctx.source_id,),
        ).fetchall()
        self.assertEqual({(r["name_as_listed"], r["role"]) for r in roles}, {
            ("박노완", "nominee"), ("박그림", "nominee"), ("이동훈", "nominee"), ("박노완", "winner")
        })

    def test_assessment_covers_every_sourcebook_entry_and_only_declares_registered_implementations(self):
        root = Path(__file__).resolve().parents[1]
        sourcebook = json.loads((root / "work/audit/wave2/Residencies.json").read_text(encoding="utf-8"))
        assessment = json.loads((root / "work/audit/wave2/Residencies_assessment.json").read_text(encoding="utf-8"))
        self.assertEqual({row["sourcebook_id"] for row in assessment}, {row["sourcebook_id"] for row in sourcebook})
        required = {"sourcebook_id", "source_ids", "disposition", "requested_vs_observed_fields",
                    "official_entry_url", "terms_robots_evidence", "limitations", "implementation_source_ids"}
        self.assertTrue(all(required <= row.keys() for row in assessment))
        implemented = {source_id for row in assessment for source_id in row["implementation_source_ids"]}
        self.assertEqual(implemented, {row["source_id"] for row in w.SOURCES})


if __name__ == "__main__":
    unittest.main()
