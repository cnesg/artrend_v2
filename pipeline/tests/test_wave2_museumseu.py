from __future__ import annotations

import hashlib
import sqlite3
import unittest
from unittest.mock import patch
import urllib.parse

from artrend_mag import db
from artrend_mag.sources import wave2_museumseu as w


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.final_url = url
        self.status = 200
        self.text = body.decode("utf-8") if isinstance(body, bytes) else body
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.fetched_at = "2026-10-28T15:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None


class FakeContext:
    mode = "initial"
    parser_version = w.PARSER_VERSION

    def __init__(self, con, source_id, pages, run_id=None):
        self.con = con
        self.source_id = source_id
        self.pages = pages
        self.run_id = run_id
        self.meta = next(row for row in w.SOURCES if row["source_id"] == source_id)
        self.stats = {}
        self.notes = []
        self.calls = []

    def fetch(self, url, params=None, **kwargs):
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError("unexpected fetch: " + url)
        return FakeResponse(url, self.pages[url])

    def evidence(self, response, locator=None, excerpt=None):
        return db.add_evidence(self.con, source_id=self.source_id, url=response.url,
                               fetched_at=response.fetched_at, http_status=response.status,
                               raw_path=response.raw_path, raw_sha256=response.sha256,
                               locator=locator, excerpt=excerpt, parser_version=self.parser_version)

    def note(self, message):
        self.notes.append(message)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n


def _con(source_id):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    source = next(row for row in w.SOURCES if row["source_id"] == source_id)
    db.upsert_source(con, source_id,
                     **{key: value for key, value in source.items()
                        if key in db.SOURCE_FIELDS + db.STATUS_FIELDS})
    con.commit()
    return con


NG_CURRENT = """<main><article><a href="/exhibitions/van-eyck-the-portraits"><img src="/images/van-eyck.jpg"><h2>Van Eyck: The Portraits</h2><p class="date">21 November 2026 – 11 April 2027</p></a></article></main>"""
NG_PAST = """<main><article><a href="/exhibitions/past/monet-and-renoir"><h2>Monet and Renoir: Painting Side by Side</h2><p class="date">27 July – 22 September 2026</p></a></article></main>"""

PALAIS_AGENDA = """<main><article><a href="/en/exposition/symbiosis-26-27"><h2>Symbiosis 26-27</h2></a></article></main>"""
PALAIS_DETAIL = """<html><head><meta property="og:image" content="https://admin.palaisdetokyo.com/image.jpg"></head><body><h1>Symbiosis 26-27</h1><div class="date">from 10/22/2026 to 06/30/2027</div></body></html>"""

RIJKSMUSEUM_LIST = """<main><article class="activity-link"><a href="/en/whats-on/exhibitions/willem-de-kooning-at-work"><img src="/image.jpg"><h3>Willem de Kooning at work</h3><span class="text-normal">till 17 January 2027</span></a></article></main>"""
RIJKSMUSEUM_PAST = """<a href="/en/whats-on/exhibitions/past/carel-visser" class="block-link">
  <div class="block-content grid-row">
    <div class="grid-column fit-width-content block-content-ordered">
      <h2 class="heading-2"><span class="inline-link inline-link-inverse">Carel Visser</span></h2>
      <p class="block-content-subtitle">In the Rijksmuseum Gardens</p>
      <span class="label">5 June - 26 Oct 2026</span>
    </div>
  </div>
</a>"""
WARSAW_CURRENT = """<main><article><a href="/en/wystawa/valie-export-doppelgangerin"><h2>VALIE EXPORT. DIE DOPPELGÄNGERIN</h2><p class="date">18.09.2026–16.03.2027</p><img src="/image.jpg"></a></article></main>"""
WARSAW_PAST = """<main><article><a href="/en/wystawa/neighbours"><h2>Neighbours</h2><p class="date">13.10–11.11.2024</p></a></article></main>"""

OAI_PAGE = b'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:edm="http://www.europeana.eu/schemas/edm/" xmlns:ore="http://www.openarchives.org/ore/terms/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:skos="http://www.w3.org/2004/02/skos/core#">
  <ListRecords><record><header><identifier>oai:rijksmuseum.nl:200107928</identifier><datestamp>2026-06-11T10:20:00Z</datestamp></header><metadata><rdf:RDF>
    <ore:Aggregation><edm:aggregatedCHO><edm:ProvidedCHO rdf:about="https://id.rijksmuseum.nl/200107928">
      <dc:creator rdf:resource="https://id.rijksmuseum.nl/2103429"/><dc:identifier>SK-C-5</dc:identifier>
      <dc:title xml:lang="en">The Night Watch</dc:title><dcterms:created xml:lang="en">1642</dcterms:created>
      <dcterms:medium xml:lang="en">Oil on canvas</dcterms:medium><dcterms:extent>453.5cm x 379.5cm</dcterms:extent>
    </edm:ProvidedCHO></edm:aggregatedCHO><edm:rights rdf:resource="http://creativecommons.org/publicdomain/mark/1.0/"/>
      <edm:isShownAt><edm:WebResource rdf:about="https://www.rijksmuseum.nl/en/collection/SK-C-5"/></edm:isShownAt>
      <edm:isShownBy rdf:resource="https://images.rijksmuseum.nl/image/SK-C-5.jpg"/>
    </ore:Aggregation><rdf:Description rdf:about="https://id.rijksmuseum.nl/2103429"><skos:prefLabel xml:lang="en">Rembrandt van Rijn</skos:prefLabel></rdf:Description>
  </rdf:RDF></metadata></record></ListRecords>
</OAI-PMH>'''

TATE_COLLECTION_PAGE1 = """<main>
  <span class="results-count__text">Showing 66,768 results</span>
  <div class="card-list">
    <div class="card"><a href="/art/artworks/kuo-sung-yin-and-yang-no-2-t16542">
      <h2 class="card__title">Yin and Yang No.2</h2>
      <span class="card__title--artwork-artist">Liu Kuo-sung</span>
      <span class="card__when--artwork-date">1973</span>
    </a></div>
    <div class="card"><a href="/art/artworks/dunkley-untitled-t16540">
      <h2 class="card__title">Untitled</h2>
      <span class="card__title--artwork-artist">Sue Dunkley</span>
      <span class="card__when--artwork-date">c.1970</span>
    </a></div>
  </div>
  <ul class="pager"><li><a data-gtm-name="pager_link_next" href="/collection?tab=collection&amp;page=2">Next page</a></li></ul>
</main>"""
TATE_COLLECTION_PAGE2 = """<main><div class="card-list">
  <div class="card"><a href="/art/artworks/el-salahi-behind-the-mask-august-t16504">
    <h2 class="card__title">Behind the Mask August</h2>
    <span class="card__title--artwork-artist">Ibrahim El-Salahi</span>
    <span class="card__when--artwork-date">2021</span>
  </a></div>
</div></main>"""


class ParserTests(unittest.TestCase):
    def test_source_ids_are_stable_unique_and_unmapped(self):
        source_ids = [row["source_id"] for row in w.SOURCES]
        self.assertEqual(source_ids, [
            "national_gallery_exhibitions", "palaisdetokyo_exhibitions",
            "warsaw_modern_art_exhibitions", "rijksmuseum_exhibitions",
            "rijksmuseum_collection_oai_pmh", "tate_collection_html",
            "musee_orsay_entry", "museo_del_prado_entry", "kiasma_web_entry", "louisiana_entry",
        ])
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertTrue(all(row["blueprint_data_id"] is None for row in w.SOURCES))
        self.assertTrue(all(row["blueprint_org_id"] is None for row in w.SOURCES))
        by_id = {row["source_id"]: row for row in w.SOURCES}
        self.assertEqual(by_id["musee_orsay_entry"]["operational_state"], "blocked_access")
        self.assertEqual(by_id["museo_del_prado_entry"]["robots_status"], "robots_http_403(not_crawled)")
        self.assertEqual(by_id["kiasma_web_entry"]["operational_state"], "blocked_permission")
        self.assertEqual(by_id["louisiana_entry"]["st_live_response"], "not_requested(robots unavailable)")
        self.assertEqual(by_id["tate_collection_html"]["operational_state"], "blocked_permission")
        self.assertIn("not a robots restriction", by_id["tate_collection_html"]["disabled"])
        self.assertEqual(by_id["tate_collection_html"]["robots_status"], "parsed(allowed collection listing)")

    def test_listing_events_keep_stable_page_keys_and_date_precision(self):
        source_id = "national_gallery_exhibitions"
        con = _con(source_id)
        pages = {
            "https://www.nationalgallery.org.uk/exhibitions": NG_CURRENT,
            "https://www.nationalgallery.org.uk/exhibitions/past": NG_PAST,
        }
        ctx = FakeContext(con, source_id, pages)
        w.collect(ctx)
        rows = con.execute("SELECT source_event_key,start_date,start_precision,end_date,end_precision FROM events WHERE source_id=? ORDER BY source_event_key", (source_id,)).fetchall()
        self.assertEqual(len(rows), 2)
        current = next(row for row in rows if row["source_event_key"].endswith("van-eyck-the-portraits"))
        self.assertEqual((current["start_date"], current["start_precision"], current["end_date"], current["end_precision"]),
                         ("2026-11-21", "day", "2027-04-11", "day"))
        event_id = con.execute("SELECT event_id FROM events WHERE source_event_key LIKE '%van-eyck-the-portraits'").fetchone()[0]
        w.collect(FakeContext(con, source_id, pages))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM events WHERE source_id=?", (source_id,)).fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT event_id FROM events WHERE source_event_key LIKE '%van-eyck-the-portraits'").fetchone()[0], event_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM image_rights WHERE source_id=?", (source_id,)).fetchone()[0], 1)

    def test_palais_detail_parses_month_first_date_range(self):
        self.assertEqual(w._parse_dates("from 10/22/2026 to 06/30/2027", month_first=True),
                         ("2026-10-22", "day", "2027-06-30", "day"))
        source_id = "palaisdetokyo_exhibitions"
        con = _con(source_id)
        pages = {
            "https://palaisdetokyo.com/en/agenda-palais-de-tokyo/": PALAIS_AGENDA,
            "https://palaisdetokyo.com/en/exposition/symbiosis-26-27": PALAIS_DETAIL,
        }
        w.collect(FakeContext(con, source_id, pages))
        row = con.execute("SELECT title,start_date,end_date FROM events WHERE source_id=?", (source_id,)).fetchone()
        self.assertEqual((row["title"], row["start_date"], row["end_date"]),
                         ("Symbiosis 26-27", "2026-10-22", "2027-06-30"))
        self.assertEqual(con.execute("SELECT usage_status FROM image_rights WHERE source_id=?", (source_id,)).fetchone()[0], "unknown")

    def test_warsaw_current_and_past_listing_fixture(self):
        source_id = "warsaw_modern_art_exhibitions"
        con = _con(source_id)
        pages = {
            "https://artmuseum.pl/en/wystawy-1": WARSAW_CURRENT,
            "https://artmuseum.pl/en/wystawy-przeszle-1": WARSAW_PAST,
        }
        w.collect(FakeContext(con, source_id, pages))
        rows = con.execute("SELECT title,country_code,start_date,end_date FROM events WHERE source_id=? ORDER BY title", (source_id,)).fetchall()
        self.assertEqual([(row["title"], row["country_code"]) for row in rows],
                         [("Neighbours", None), ("VALIE EXPORT. DIE DOPPELGÄNGERIN", None)])
        self.assertEqual(rows[0]["start_date"], "2024-10-13")
        self.assertEqual(rows[1]["end_date"], "2027-03-16")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM review_queue WHERE issue='venue country unknown'").fetchone()[0], 2)

    def test_warsaw_observed_2026_exhibitions_path_is_parsed(self):
        # Observed 2026-10-28: detail links moved from /en/wystawa/... to /en/exhibitions/...
        source_id = "warsaw_modern_art_exhibitions"
        con = _con(source_id)
        card = ('<a class="block shadow-hover" href="/en/exhibitions/ways-of-the-black-spread-over-the-white-land">'
                '<div class="w-full"><figure><img alt="" src="https://api-sf.artmuseum.pl/uploads/thumbs/x.jpg"/></figure></div>'
                '<div class="text-center mb-l"><h3 class="font-serif"><span class="pseudo-link-2">'
                'WAYS OF THE BLACK SPREAD OVER THE WHITE LAND<!-- --> </span></h3>'
                '<div class="w-full"><p class="text-center allcaps text-1">26.06.2026–10.01.2027</p></div></div></a>')
        nav = '<a href="/en/wystawy-przeszle-1">Past exhibitions</a><a href="/en/wystawy-1">Exhibitions</a>'
        pages = {
            "https://artmuseum.pl/en/wystawy-1": "<main>" + nav + card + "</main>",
            "https://artmuseum.pl/en/wystawy-przeszle-1": "<main>" + nav + "</main>",
        }
        w.collect(FakeContext(con, source_id, pages))
        rows = con.execute("SELECT title,url,start_date,end_date FROM events WHERE source_id=?", (source_id,)).fetchall()
        self.assertEqual([(r["title"], r["start_date"], r["end_date"]) for r in rows],
                         [("WAYS OF THE BLACK SPREAD OVER THE WHITE LAND", "2026-06-26", "2027-01-10")])
        self.assertEqual(rows[0]["url"], "https://artmuseum.pl/en/exhibitions/ways-of-the-black-spread-over-the-white-land")

    def test_rijksmuseum_listing_and_oai_record_level_rights(self):
        event_source = "rijksmuseum_exhibitions"
        event_con = _con(event_source)
        pages = {
            "https://www.rijksmuseum.nl/en/whats-on/exhibitions/now-on-view": RIJKSMUSEUM_LIST,
            "https://www.rijksmuseum.nl/en/whats-on/exhibitions/past": RIJKSMUSEUM_PAST,
        }
        w.collect(FakeContext(event_con, event_source, pages))
        self.assertEqual(event_con.execute("SELECT COUNT(*) FROM events WHERE source_id=?", (event_source,)).fetchone()[0], 2)
        event = event_con.execute("SELECT title,end_date,end_precision FROM events WHERE source_id=? AND title=?",
                                  (event_source, "Willem de Kooning at work")).fetchone()
        self.assertEqual((event["title"], event["end_date"], event["end_precision"]),
                         ("Willem de Kooning at work", "2027-01-17", "day"))
        past = event_con.execute("SELECT title,start_date,end_date FROM events WHERE source_id=? AND source_event_key LIKE '%/past/carel-visser'",
                                 (event_source,)).fetchone()
        self.assertEqual((past["title"], past["start_date"], past["end_date"]),
                         ("Carel Visser", "2026-06-05", "2026-10-26"))

        work_source = "rijksmuseum_collection_oai_pmh"
        work_con = _con(work_source)
        ctx = FakeContext(work_con, work_source, {"https://data.rijksmuseum.nl/oai?verb=ListRecords&metadataPrefix=edm&from=2024-08-15T13%3A51%3A17Z": OAI_PAGE})
        w.collect(ctx)
        work = work_con.execute("SELECT title,date_text,medium,id_value FROM works WHERE source_id=?", (work_source,)).fetchone()
        self.assertEqual((work["title"], work["date_text"], work["medium"], work["id_value"]),
                         ("The Night Watch", "1642", "Oil on canvas", "SK-C-5"))
        rights = work_con.execute("SELECT usage_status,license,image_url FROM image_rights WHERE source_id=?", (work_source,)).fetchone()
        self.assertEqual((rights["usage_status"], rights["license"], rights["image_url"]),
                         ("public_domain_cc0", "http://creativecommons.org/publicdomain/mark/1.0/",
                          "https://images.rijksmuseum.nl/image/SK-C-5.jpg"))
        self.assertEqual(work_con.execute("SELECT COUNT(*) FROM works WHERE source_id=?", (work_source,)).fetchone()[0], 1)

    def test_rijksmuseum_initial_cursor_resume(self):
        work_source = "rijksmuseum_collection_oai_pmh"
        work_con = _con(work_source)
        work_con.execute("INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state,error) VALUES(?,?,?,?,?,?)",
                         ("prior-initial", work_source, "initial", "2026-10-27T12:00:00+09:00", "partial",
                          w._oai_cursor_note("saved-cursor")))
        work_con.execute("INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state) VALUES(?,?,?,?,?)",
                         ("current-initial", work_source, "initial", "2026-10-28T12:00:00+09:00", "running"))
        resume_url = "https://data.rijksmuseum.nl/oai?verb=ListRecords&resumptionToken=saved-cursor"
        ctx = FakeContext(work_con, work_source, {resume_url: OAI_PAGE}, run_id="current-initial")
        w.collect(ctx)
        self.assertEqual(ctx.calls, [resume_url])
        saved = work_con.execute("SELECT error FROM crawl_runs WHERE run_id='current-initial'").fetchone()[0]
        self.assertEqual(saved, w._oai_cursor_note(None))

    def test_tate_collection_explicit_pagination_and_listing_metadata(self):
        source_id = "tate_collection_html"
        con = _con(source_id)
        pages = {
            "https://www.tate.org.uk/collection": TATE_COLLECTION_PAGE1,
            "https://www.tate.org.uk/collection?tab=collection&page=2": TATE_COLLECTION_PAGE2,
        }
        ctx = FakeContext(con, source_id, pages)
        w.collect(ctx)
        self.assertEqual(ctx.calls, list(pages))
        rows = con.execute(
            "SELECT w.id_value,w.title,w.date_text,e.canonical_name "
            "FROM works w LEFT JOIN entities e ON e.entity_id=w.artist_entity_id "
            "WHERE w.source_id=? ORDER BY w.id_value",
            (source_id,),
        ).fetchall()
        self.assertEqual([(row["id_value"], row["title"], row["date_text"], row["canonical_name"]) for row in rows], [
            ("T16504", "Behind the Mask August", "2021", "Ibrahim El-Salahi"),
            ("T16540", "Untitled", "c.1970", "Sue Dunkley"),
            ("T16542", "Yin and Yang No.2", "1973", "Liu Kuo-sung"),
        ])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM image_rights WHERE source_id=?", (source_id,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM works WHERE source_id=? AND is_public_domain IS NOT NULL", (source_id,)).fetchone()[0], 0)
        self.assertIn("medium, dimensions", " ".join(ctx.notes))
        w.collect(FakeContext(con, source_id, pages))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM works WHERE source_id=?", (source_id,)).fetchone()[0], 3)

    def test_tate_collection_capped_initial_run_persists_next_page(self):
        source_id = "tate_collection_html"
        con = _con(source_id)
        con.execute("INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state) VALUES(?,?,?,?,?)",
                    ("capped-tate-initial", source_id, "initial", "2026-10-28T12:00:00+09:00", "running"))
        ctx = FakeContext(con, source_id, {"https://www.tate.org.uk/collection": TATE_COLLECTION_PAGE1},
                          run_id="capped-tate-initial")
        with patch.object(w, "TATE_PAGE_LIMIT", 1):
            w.collect(ctx)
        saved = con.execute("SELECT error FROM crawl_runs WHERE run_id='capped-tate-initial'").fetchone()[0]
        self.assertEqual(saved, w._tate_cursor_note(2))
        self.assertIn("partial coverage", " ".join(ctx.notes))

    def test_tate_collection_initial_cursor_resumes_from_saved_page(self):
        source_id = "tate_collection_html"
        con = _con(source_id)
        con.execute("INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state,error) VALUES(?,?,?,?,?,?)",
                    ("prior-tate-initial", source_id, "initial", "2026-10-27T12:00:00+09:00", "partial",
                     w._tate_cursor_note(2)))
        con.execute("INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state) VALUES(?,?,?,?,?)",
                    ("current-tate-initial", source_id, "initial", "2026-10-28T12:00:00+09:00", "running"))
        resume_url = "https://www.tate.org.uk/collection?tab=collection&page=2"
        ctx = FakeContext(con, source_id, {resume_url: TATE_COLLECTION_PAGE2}, run_id="current-tate-initial")
        w.collect(ctx)
        self.assertEqual(ctx.calls, [resume_url])
        saved = con.execute("SELECT error FROM crawl_runs WHERE run_id='current-tate-initial'").fetchone()[0]
        self.assertEqual(saved, w._tate_cursor_note(None))


if __name__ == "__main__":
    unittest.main()
