from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest

from artrend_mag import db
from artrend_mag.sources import wave2_galleries as w

FIXTURES = Path(__file__).parent / "fixtures" / "wave2_galleries"


class ParserTests(unittest.TestCase):
    def test_roster_markup_creates_only_source_listed_names(self):
        html = (FIXTURES / "artist_roster.html").read_text(encoding="utf-8")
        names = w.parse_roster(html, "wave2_gallery_baton", "https://www.gallerybaton.com/artists/")
        self.assertEqual(names, [{"name": "Liam Gillick", "url": "https://www.gallerybaton.com/artists/35-liam-gillick/"}])

    def test_omr_exhibited_artists_are_not_marked_as_represented(self):
        html = (FIXTURES / "omr_roster.html").read_text(encoding="utf-8")
        names = w.parse_roster(html, "wave2_omr", "https://omr.art/artists")
        self.assertEqual([item["name"] for item in names], ["Atelier Van Lieshout", "Pia Camil"])

    def test_exhibition_card_retains_printed_dates_and_explicit_branch_city(self):
        html = (FIXTURES / "exhibition_card.html").read_text(encoding="utf-8")
        items = w.parse_exhibition_cards(html, "wave2_gallery_baton", "https://www.gallerybaton.com/exhibitions/")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Yuichi Hirako: POSTFOREST")
        self.assertEqual(items[0]["start_date"], "2026-10-22")
        self.assertEqual(items[0]["end_date"], "2026-12-05")
        self.assertEqual((items[0]["city"], items[0]["country_code"]), ("Seoul", "KR"))

    def test_omr_card_separates_artist_title_and_unverified_venue_city(self):
        html = (FIXTURES / "omr_exhibition.html").read_text(encoding="utf-8")
        items = w.parse_exhibition_cards(html, "wave2_omr", "https://omr.art/exhibitions")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "The Pressure of Time")
        self.assertEqual(items[0]["artists"], ["Leonel Salguero"])
        self.assertEqual(items[0]["start_date"], "2026-10-22")
        self.assertEqual(items[0]["end_date"], "2026-12-18")
        self.assertIsNone(items[0]["country_code"])

    def test_leeahn_archive_rows_without_detail_links_remain_on_listing_url(self):
        html = (FIXTURES / "leeahn_list.html").read_text(encoding="utf-8")
        items = w.parse_exhibition_cards(html, "wave2_leeahn", "https://www.leeahngallery.com/exhibitions/list")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.leeahngallery.com/exhibitions/list")
        self.assertEqual(items[0]["title"], "Sean Scully")
        self.assertEqual(items[0]["start_date"], "2026-11-12")
        self.assertEqual(items[0]["city"], "Daegu")

    def test_ropac_news_card_extracts_headline_category_and_published_date(self):
        html = '''<div class="content_header"><a href="/news/3017-sample/">
          <div class="prelude">Featured in The New Yorker<div class="prelude_dates">20 July 2026</div></div>
          <div class="h1_heading">Florentina Holzinger’s Naked Ambition</div>
          <div class="h1_subtitle">Onward and Upward with the Arts</div></a></div>'''
        items = w.parse_gallery_articles(html, "wave2_ropac_news_publications", "https://ropac.net/news/", "news")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Florentina Holzinger’s Naked Ambition: Onward and Upward with the Arts")
        self.assertEqual(items[0]["published_at"], "2026-07-20")
        self.assertEqual(items[0]["categories"], "Featured in The New Yorker")

    def test_ropac_exhibition_card_date_is_not_a_publication_date(self):
        html = '''<div class="content_header"><a href="/news/3100-sample/">
          <div class="prelude">Solo museum exhibition Serpentine, London, UK<div class="prelude_dates">8 October 2027</div></div>
          <div class="h1_heading">Sample Artist</div></a></div>'''
        items = w.parse_gallery_articles(html, "wave2_ropac_news_publications", "https://ropac.net/news/", "news")
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["published_at"])
        self.assertEqual(items[0]["date_text"], "8 October 2027")

    def test_ropac_publication_card_uses_year_precision(self):
        html = '''<div class="item"><a href="/publications/284-jordan-casteel-winter-sun/">
          <div class="list_content_header"><h3>Jordan Casteel</h3></div>
          <div class="title">Jordan Casteel: Winter Sun</div><span>2026</span></a></div>'''
        items = w.parse_ropac_publications(html, "https://ropac.net/publications/")
        self.assertEqual(items, [{"url": "https://ropac.net/publications/284-jordan-casteel-winter-sun/",
                                  "title": "Jordan Casteel: Winter Sun", "artist": "Jordan Casteel", "year": "2026"}])

    def test_lisson_journal_and_news_cards_extract_only_visible_metadata(self):
        html = '''<a href="/journal/listen-again"><article><p>podcast</p><p>Listen again to the Lisson ON AIR podcast series</p></article></a>
          <a href="/news/opening-soon"><article><p>Museum Exhibition</p><p>Opening soon at Neue Nationalgalerie: Ulay, Ulay &amp; Abramović</p><p>27 October 2026</p></article></a>'''
        journal = w.parse_gallery_articles(html, "wave2_lisson_news_journal", "https://lisson.com/journal", "journal")
        news = w.parse_gallery_articles(html, "wave2_lisson_news_journal", "https://lisson.com/news", "news")
        self.assertEqual((journal[0]["title"], journal[0]["categories"]),
                         ("Listen again to the Lisson ON AIR podcast series", "podcast"))
        self.assertEqual((news[0]["published_at"], news[0]["categories"]), ("2026-10-27", "Museum Exhibition"))

    def test_david_zwirner_press_room_keeps_press_dates_out_of_article_published_at(self):
        html = '''<div class="group"><a href="/exhibitions/2026/roy-decarava/press-release">
          <p data-testid="card-content-info-title">Roy DeCarava: the sound i saw</p>
          <p data-testid="card-content-info-secondary-title">Los Angeles: 606 N Western Avenue</p>
          <p data-testid="card-content-info-secondary-subtitle">September 19—October 31, 2026</p></a></div>'''
        items = w.parse_gallery_articles(html, "wave2_david_zwirner_press_books", "https://www.davidzwirner.com/press", "press")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Roy DeCarava: the sound i saw")
        self.assertEqual(items[0]["categories"], "press release")
        self.assertIsNone(items[0]["published_at"])

    def test_david_zwirner_books_catalogue_excludes_merchandise(self):
        html = '''<div class="group"><a href="/collect/stan-douglas-parallax-book">
          <p data-testid="heading">Stan Douglas: Parallax</p><p>JBE Books</p><p>$50</p></a></div>
          <div class="group"><a href="/collect/dzb-x-noah-davis-tote-merch">
          <p data-testid="heading">DZB x Noah Davis Tote</p></a></div>'''
        items = w.parse_david_zwirner_publications(html, "https://www.davidzwirner.com/collect/books")
        self.assertEqual(items, [{"url": "https://www.davidzwirner.com/collect/stan-douglas-parallax-book",
                                  "title": "Stan Douglas: Parallax", "artist": None, "year": None}])


CROUSEL_EXHIBITIONS = """<html><body class="exhibitions"><section><div class="col-container exhibs">
<figure class="col-50 solo"><a class="cover" href="/en/exhibition/nick-mauss-2026/"><img alt="" src="/media/a.jpg"/></a><br/>
<figcaption><h2><a href="/en/exhibition/nick-mauss-2026/">Nick Mauss</a></h2><h3><a href="/en/exhibition/nick-mauss-2026/">In This Time</a></h3>
<p> October 19<sup>th</sup> — November 21<sup>st</sup>, 2026 </p></figcaption></figure>
<figure class="col-50 solo"><a class="cover" href="/en/exhibition/the-harlequins-dog/"><img alt="" src="/media/b.jpg"/></a><br/>
<figcaption><h2><a href="/en/exhibition/the-harlequins-dog/">Amy Sillman, Clément Rodzielski</a></h2><h3><a href="/en/exhibition/the-harlequins-dog/">The Harlequin's Dog</a></h3>
<p> June 6<sup>th</sup> — July 22<sup>nd</sup>, 2026 </p></figcaption></figure>
<figure class="col-50 solo"><a class="cover" href="/en/exhibition/pharmakon/"><img alt="" src="/media/c.jpg"/></a><br/>
<figcaption><h2><a href="/en/exhibition/pharmakon/">Group exhibition</a></h2><h3><a href="/en/exhibition/pharmakon/">Pharmakon</a></h3>
<p> January 30<sup>th</sup> — March 7<sup>th</sup>, 2026 </p></figcaption></figure>
</div></section></body></html>"""


class PrintedPeriodTests(unittest.TestCase):
    def test_opening_reception_prose_does_not_replace_the_printed_range(self):
        # Observed Ota Fine Arts card shape (2026-10-28): printed range followed by an event paragraph.
        html = ("<div><a href='/exhibitions/takao-minami'><h3>Takao Minami: Medi</h3></a><p>25 Sep - 5 Nov 2016</p>"
                "<p>Opening Reception in the presence of the artist: 23 September 2016, 7pm (Coinciding with "
                "Gillman Barracks 4th Anniversary event) Artist Tour: 24 September 2016, 4pm</p></div>")
        node = w._soup(html).div
        self.assertEqual(w._date_lines(node), "25 Sep - 5 Nov 2016")

    def test_two_short_lines_still_form_one_period(self):
        node = w._soup("<div><p>September 18, 2026</p><p>March 16, 2027</p></div>").div
        self.assertEqual(w._date_lines(node), "September 18, 2026 – March 16, 2027")


class CrouselObservedMarkupTests(unittest.TestCase):
    def test_figure_cards_split_artist_line_title_and_superscript_dates(self):
        records = w.parse_exhibition_cards(CROUSEL_EXHIBITIONS, "wave2_crousel", "https://www.crousel.com/en/exhibitions/")
        got = [(r["title"], r["start_date"], r["end_date"], r.get("artists")) for r in records]
        self.assertEqual(got, [
            ("In This Time", "2026-10-19", "2026-11-21", ["Nick Mauss"]),
            ("The Harlequin's Dog", "2026-06-06", "2026-07-22", ["Amy Sillman", "Clément Rodzielski"]),
            ("Pharmakon", "2026-01-30", "2026-03-07", None),
        ])


class _StoreContext:
    def __init__(self, con, source_id):
        self.con = con
        self.source_id = source_id
        self.stats = {}

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n


class _Resp:
    def __init__(self, url, text):
        self.url, self.text = url, text
        self.status, self.fetched_at, self.raw_path, self.sha256 = 200, "2026-10-28T09:00:00+09:00", None, "0" * 64


class _FetchContext:
    def __init__(self, con, source_id, pages, mode):
        self.con, self.source_id, self.pages, self.mode = con, source_id, pages, mode
        self.stats, self.notes, self.calls = {}, [], []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        return _Resp(url, self.pages[url])

    def evidence(self, resp, locator=None, excerpt=None):
        return db.add_evidence(self.con, source_id=self.source_id, url=resp.url, fetched_at=resp.fetched_at,
                               http_status=200, raw_path=None, raw_sha256=resp.sha256, locator=locator,
                               excerpt=excerpt, parser_version=w.PARSER_VERSION)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def note(self, message):
        self.notes.append(message)


def _gallery_con(source_id):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    con.execute("PRAGMA foreign_keys=ON")
    row = next(r for r in w.SOURCES if r["source_id"] == source_id)
    db.upsert_source(con, source_id, **{k: v for k, v in row.items() if k in db.SOURCE_FIELDS + db.STATUS_FIELDS})
    return con


UQAM_LIST = """<main><article><a href="/expositions/une-assemblee-pour-le-cosmos/"><h2>Une assemblée pour le cosmos</h2></a></article>
<a href="/statut/archives/">Archives</a></main>"""
UQAM_DETAIL = """<html><body><figure><figcaption>Vue de l'exposition Une assemblée pour le cosmos, 2026</figcaption></figure>
<main><h1>Une assemblée pour le cosmos</h1><p class="date">4 septembre 2026 - 17 octobre 2026</p>
<div class="date">10 octobre 2026</div></main></body></html>"""


class UqamDetailDateTests(unittest.TestCase):
    def test_undated_listing_cards_read_printed_dates_from_bounded_detail_pages(self):
        source_id = "wave2_galerie_uqam"
        con = _gallery_con(source_id)
        base = "https://galerie.uqam.ca"
        pages = {base + "/statut/en-cours/": UQAM_LIST, base + "/statut/a-venir/": "<main></main>",
                 base + "/statut/archives/": UQAM_LIST,
                 base + "/expositions/une-assemblee-pour-le-cosmos/": UQAM_DETAIL}
        ctx = _FetchContext(con, source_id, pages, "initial")
        org = db.ensure_entity(con, entity_type="gallery", name="Galerie de l’UQAM", namespace="src:" + source_id,
                               id_value="org", source_id=source_id)
        w._collect_listings(ctx, org, w._GALLERIES[source_id])
        rows = con.execute("SELECT title,start_date,end_date,date_text FROM events").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Une assemblée pour le cosmos", "2026-09-04", "2026-10-17",
                                                     "4 septembre 2026 - 17 octobre 2026")])
        self.assertEqual(ctx.calls.count(base + "/expositions/une-assemblee-pour-le-cosmos/"), 1)
        # A second initial run does not refetch details already stored.
        ctx.calls.clear()
        w._collect_listings(ctx, org, w._GALLERIES[source_id])
        self.assertNotIn(base + "/expositions/une-assemblee-pour-le-cosmos/", ctx.calls)


class GalleryEventStorageTests(unittest.TestCase):
    def test_listed_artists_are_stored_as_participants(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        con.execute("PRAGMA foreign_keys=ON")
        source_id = "wave2_johyun"
        row = next(r for r in w.SOURCES if r["source_id"] == source_id)
        db.upsert_source(con, source_id, **{k: v for k, v in row.items() if k in db.SOURCE_FIELDS + db.STATUS_FIELDS})
        ctx = _StoreContext(con, source_id)
        evidence = db.add_evidence(con, source_id=source_id, url="https://www.johyungallery.com/exhibitions",
                                   fetched_at="2026-10-28T09:00:00+09:00", http_status=200, raw_path=None,
                                   raw_sha256="0" * 64, locator="card", excerpt="2026.09.01 - 2026.10.01",
                                   parser_version=w.PARSER_VERSION)
        org = db.ensure_entity(con, entity_type="gallery", name="Johyun Gallery", namespace="src:" + source_id,
                               id_value="organizer", source_id=source_id)
        item = {"title": "Solo show", "url": "https://www.johyungallery.com/exhibitions/1",
                "artists": ["Lee Bae", "Lee Bae"], "date_text": "2026.09.01 - 2026.10.01",
                "start_date": "2026-09-01", "start_precision": "day",
                "end_date": "2026-10-01", "end_precision": "day"}
        w._store_event(ctx, org, item, evidence)
        rows = con.execute("SELECT name_as_listed, role, extraction_method FROM event_participants").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Lee Bae", "artist", "list_markup")])
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
