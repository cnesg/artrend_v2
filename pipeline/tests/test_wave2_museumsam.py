from __future__ import annotations

import hashlib
import sqlite3
import unittest

from artrend_mag import db
from artrend_mag.sources import wave2_museumsam as w


class FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.final_url = url
        self.status = 200
        self.text = text
        self.content = text.encode("utf-8")
        self.fetched_at = "2026-10-28T16:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None


class FakeContext:
    parser_version = w.PARSER_VERSION
    mode = "incremental"

    def __init__(self, con, source_id, pages):
        self.con, self.source_id, self.pages = con, source_id, pages
        self.meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
        self.stats, self.notes, self.calls = {}, [], []

    def fetch(self, url, params=None, **kwargs):
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode(params)
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected fetch {url}")
        return FakeResponse(url, self.pages[url])

    def evidence(self, response, locator=None, excerpt=None):
        return db.add_evidence(self.con, source_id=self.source_id, url=response.url, fetched_at=response.fetched_at,
                               http_status=200, raw_path=None, raw_sha256=response.sha256, locator=locator,
                               excerpt=excerpt, parser_version=self.parser_version)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def note(self, message):
        self.notes.append(message)


def _con(source_id):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    row = next(row for row in w.SOURCES if row["source_id"] == source_id)
    db.upsert_source(con, source_id, **{key: value for key, value in row.items()
                                       if key in db.SOURCE_FIELDS + db.STATUS_FIELDS})
    con.commit()
    return con


SAAM_CURRENT = """<main><div class="azalea-card @container flex flex-col overflow-hidden rounded-sm w-full" href="/exhibitions/nick-cave" rel="bookmark">
<header><a class="azalea-heading-level-3 text-black" href="/exhibitions/nick-cave" rel="bookmark">Nick Cave: Mammoth</a></header>
<div class="azalea-heading-level-4"><span class="whitespace-nowrap">Through </span><span class="whitespace-nowrap">January 3, 2027</span></div>
<div class="flex items-center azalea-heading-level-6"><a href="/visit/saam">Smithsonian American Art Museum</a></div></div></main>"""

SAAM_PAST = """<main><div class="azalea-teaser grid grid-cols-1 lg:grid-cols-10 gap-4 w-full px-0 lg:px-6 py-4">
<div><a aria-label="Grandma Moses: A Good Day's Work" href="/exhibitions/grandma-moses"></a></div>
<header><a class="azalea-heading-level-3 text-black" href="/exhibitions/grandma-moses" rel="bookmark">Grandma Moses: A Good Day’s Work</a></header>
<div class="azalea-heading-level-5"><span class="whitespace-nowrap">November 25, 2025</span><span>–</span><span class="whitespace-nowrap">July 12, 2026</span></div></div></main>"""

SAAM_DETAIL = """<main><h1>Nick Cave: Mammoth</h1>
<section><div class="azalea-text-md"><header><h3 class="azalea-heading-section">Visiting Information</h3></header>
<div class="flex flex-col space-y-1"><div><a href="/visit/saam">Smithsonian American Art Museum</a></div>
<div><span class="whitespace-nowrap">February 13, 2026</span><span>–</span><span class="whitespace-nowrap">January 3, 2027</span></div></div></div></section>
<section id="artists"><header><h3 class="azalea-heading-section">Artists</h3></header>
<div class="azalea-card @container" href="/artist/nick-cave-29902"><header><a href="/artist/nick-cave-29902">Nick Cave</a></header></div></section>
<p>The exhibition is organized by Sarah Newman, the James Dicke Curator of Contemporary Art, with support by Anne Hyland, curatorial associate.</p></main>"""

MNBA_LISTING = """<main><div class="masonry-item views-row">
<div class="views-field views-field-field-media"><div class="field-content"><a href="/exposiciones-temporales/te-creo-paisaje-enrique-ramirez" hreflang="es"><img alt="Fotografía de un hombre con traje anaranjado lanzándose al agua" src="/sites/www.mnba.gob.cl/files/styles/ancho_x_auto/public/2026-10/enriqueramirez_web_0.jpg"/></a></div></div>
<h2 class="destacado__title"><span><a href="/exposiciones-temporales/te-creo-paisaje-enrique-ramirez" hreflang="es">Te creo paisaje. Enrique Ramírez</a></span></h2>
<div class="date-custom-published"><span><time datetime="2026-10-08T14:50:58-03:00">Publicado el 08/10/2026</time></span></div>
<div class="views-field views-field-view-group"><span class="field-content node-readmore"><a href="/exposiciones-temporales/te-creo-paisaje-enrique-ramirez" hreflang="es">Ve más</a></span></div></div></main>"""

MNBA_DETAIL = """<main><h1>Te creo paisaje. Enrique Ramírez</h1><div class="group group--temporary-expositions">
<div class="text-long"><p>La muestra se realiza en el marco de la línea curatorial del MNBA de artistas chilenos residentes en el extranjero.</p>
<p><strong>Curaduría: </strong>Jacopo Crivelli Visconti (Italia, 1973).</p>
<h3><strong>Sobre el artista</strong></h3>
<p dir="ltr"><span>Nacido en Santiago de Chile en 1979, </span><strong>Enrique Ramírez</strong><span> estudió cine en Chile.</span></p></div>
<div class="exposicion-date-items"><div class="field-item"><strong>Inicio:</strong> 08/10/2026 - 17:00 <strong>Término:</strong> 28/02/2027 - 18:30</div>
<div class="field field--inline field--type-string field--name-field-lugar"><div class="field-label">Lugar</div><div class="field-item">Ala sur, primer piso</div></div></div>
</div></main>"""

WHITNEY_ARTISTS = """id,getty_ulan_id,wikidata_id,display_name,begin_date,end_date
4780,500071341,Q12012352,John Ahearn,1951,0
"""
WHITNEY_ARTWORKS = """id,wikidata_id,title,display_date,classification,medium,accession_number,dimensions,publication_info,edition,credit_line,credit_line_repro,artists,artist_ids
11239,,The Usual Suspects,1996,Prints,Screenprint,97.27,"Sheet: 40 × 26 in. (101.6 × 66 cm)
Image: 30 1/4 × 18 3/8 in. (76.8 × 46.7 cm)",Printed by Nenad Bozie; published by Avanti Editions,"24/100 | 10 APs, 4 PPs",Gift of Marc Schwartz,"Courtesy of The Estate of Martin Wong and P.P.O.W. Gallery, New York, NY","John Ahearn, Andrew Castrucci, Crash, Daze, Jane Dickson, Jenny Holzer, Gary Simmons, Martin Wong","4780, 4781, 4855, 4856, 4631, 615, 3913, 4782"
"""


class ParserTests(unittest.TestCase):
    def test_saam_current_and_archive_markup_and_end_only_period(self):
        current = w.parse_saam_listing(SAAM_CURRENT)
        self.assertEqual(len(current), 1)
        self.assertEqual((current[0]["key"], current[0]["venue"]),
                         ("nick-cave", "Smithsonian American Art Museum"))
        self.assertEqual(w._saam_period(current[0]["date_text"]),
                         (None, None, "2027-01-03", "day"))
        past = w.parse_saam_listing(SAAM_PAST, past=True)
        self.assertEqual((past[0]["key"], past[0]["title"]),
                         ("grandma-moses", "Grandma Moses: A Good Day’s Work"))
        self.assertEqual(w._saam_period(past[0]["date_text"]),
                         ("2025-11-25", "day", "2026-07-12", "day"))

    def test_mnba_listing_publication_timestamp_is_not_event_period(self):
        items = w.parse_mnba_listing(MNBA_LISTING)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], "2026-10-08")
        self.assertNotIn("date_text", items[0])
        detail = w.parse_mnba_detail(MNBA_DETAIL)
        self.assertEqual(detail["dates"], ("2026-10-08", "day", "2027-02-28", "day"))
        self.assertEqual(detail["venue"], "Ala sur, primer piso")
        self.assertEqual(detail["artists"], ["Enrique Ramírez"])
        self.assertEqual(detail["curators"], ["Jacopo Crivelli Visconti"])


class CollectTests(unittest.TestCase):
    def test_saam_collect_stores_visible_dates_venue_and_explicit_people(self):
        sid = "wave2_saam_exhibitions"
        pages = {
            f"{w.SAAM}/exhibitions": SAAM_CURRENT,
            f"{w.SAAM}/exhibitions/upcoming": "<main></main>",
            f"{w.SAAM}/exhibitions/past": "<main></main>",
            f"{w.SAAM}/exhibitions/nick-cave": SAAM_DETAIL,
        }
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        w.collect(ctx)
        event = con.execute("SELECT * FROM events WHERE source_id=?", (sid,)).fetchone()
        self.assertEqual((event["title"], event["start_date"], event["end_date"], event["country_code"]),
                         ("Nick Cave: Mammoth", "2026-02-13", "2027-01-03", "US"))
        roles = {row["role"]: row["name_as_listed"] for row in con.execute(
            "SELECT role,name_as_listed FROM event_participants WHERE event_id=?", (event["event_id"],))}
        self.assertEqual(roles, {"artist": "Nick Cave", "curator": "Sarah Newman"})
        venue = con.execute("SELECT name,city FROM venues WHERE venue_id=?", (event["venue_id"],)).fetchone()
        self.assertEqual(tuple(venue), ("Smithsonian American Art Museum", "Washington"))

    def test_mnba_collect_uses_detail_dates_and_explicit_participants(self):
        sid = "wave2_mnba_chile_exhibitions"
        pages = {
            f"{w.MNBA}/exposiciones-temporales": MNBA_LISTING,
            f"{w.MNBA}/exposiciones-temporales/te-creo-paisaje-enrique-ramirez": MNBA_DETAIL,
        }
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        w.collect(ctx)
        event = con.execute("SELECT * FROM events WHERE source_id=?", (sid,)).fetchone()
        self.assertEqual((event["start_date"], event["end_date"], event["country_code"], event["city"]),
                         ("2026-10-08", "2027-02-28", "CL", "Santiago"))
        roles = {row["role"]: row["name_as_listed"] for row in con.execute(
            "SELECT role,name_as_listed FROM event_participants WHERE event_id=?", (event["event_id"],))}
        self.assertEqual(roles, {"artist": "Enrique Ramírez", "curator": "Jacopo Crivelli Visconti"})

    def test_whitney_cc0_csv_import_does_not_claim_image_rights(self):
        sid = "wave2_whitney_open_access"
        pages = {w.WHITNEY_ARTISTS_CSV: WHITNEY_ARTISTS, w.WHITNEY_ARTWORKS_CSV: WHITNEY_ARTWORKS}
        con = _con(sid)
        ctx = FakeContext(con, sid, pages)
        w.collect(ctx)
        work = con.execute("SELECT * FROM works WHERE source_id=?", (sid,)).fetchone()
        self.assertEqual((work["id_value"], work["title"], work["artist_entity_id"], work["is_public_domain"]),
                         ("11239", "The Usual Suspects", db.sid("ent", "whitney_artist", "4780"), None))
        self.assertIn("reproduction_credit=Courtesy of The Estate of Martin Wong", work["acquisition_text"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM image_rights WHERE source_id=?", (sid,)).fetchone()[0], 0)
        artist = con.execute("SELECT canonical_name,birth_year FROM entities WHERE entity_id=?",
                             (work["artist_entity_id"],)).fetchone()
        self.assertEqual(tuple(artist), ("John Ahearn", 1951))


if __name__ == "__main__":
    unittest.main()
