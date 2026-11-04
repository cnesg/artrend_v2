from __future__ import annotations

import hashlib
import sqlite3
import unittest
from unittest.mock import patch

from artrend_mag import db
from artrend_mag.sources import gl_foundations


class FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.final_url = url
        self.status = 200
        self.text = text
        self.content = text.encode("utf-8")
        self.fetched_at = "2026-10-28T09:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None


class FakeContext:
    def __init__(self, con, pages, mode="incremental"):
        self.con = con
        self.source_id = "broad_public"
        self.mode = mode
        self.parser_version = gl_foundations.PARSER_VERSION
        self.pages = pages
        self.calls = []
        self.stats = {}
        self.notes = []
        self.fetch_errors = set()

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url in self.fetch_errors:
            raise gl_foundations.FetchError("fixture fetch failure")
        if url not in self.pages:
            raise AssertionError(f"unexpected public page fetch: {url}")
        return FakeResponse(url, self.pages[url])

    def evidence(self, response, locator=None, excerpt=None):
        return db.add_evidence(
            self.con, source_id=self.source_id, url=response.url, fetched_at=response.fetched_at,
            http_status=response.status, raw_path=response.raw_path, raw_sha256=response.sha256,
            locator=locator, excerpt=excerpt, parser_version=self.parser_version,
        )

    def note(self, message):
        self.notes.append(message)

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n


def _connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    source = next(row for row in gl_foundations.SOURCES if row["source_id"] == "broad_public")
    fields = set(db.SOURCE_FIELDS + db.STATUS_FIELDS)
    db.upsert_source(con, source["source_id"], **{key: value for key, value in source.items() if key in fields})
    con.commit()
    return con


def _pages():
    return {
        "https://www.thebroad.org/art": """
            <main id="main-content"><h1>Now on View</h1><h2>Upcoming Exhibitions</h2>
            <article><a href="/art/collection-exhibitions/future-show">Has the myth been shattered</a></article></main>
        """,
        "https://www.thebroad.org/events": """
            <main id="main-content"><h1>Events</h1><h2>Upcoming Events</h2>
            <article><a href="/events/public-talk">Public Talk</a></article></main>
        """,
        "https://www.thebroad.org/art/exhibitions/past": """
            <main id="main-content"><h1>Past Exhibitions</h1><h2>Past Exhibitions</h2>
            <article><a href="/art/special-exhibitions/past-show">Past Show</a></article>
            <article><a href="/invisiblesun">Collection Exhibition Invisible Sun</a></article>
            <ul class="pager"><li class="pager__item--next"><a rel="next" href="?page=1">Next</a></li></ul></main>
        """,
        "https://www.thebroad.org/art/browse": """
            <main id="main-content"><h1>Browse the Collection</h1>
            <article><p>Jane Artist, 2001</p><h3><a href="/art/jane-artist/work-one">Work One</a></h3><p>On View</p></article>
            <article><p>Co-artist and Second Artist, 1998–1999</p><h3><a href="/art/co-artist-and-second-artist/work-two">Work Two</a></h3><p>On View</p></article></main>
        """,
        "https://www.thebroad.org/art/on-view/browse": """
            <div role="main"><a id="main-content"></a><h1>Browse the Collection</h1>
            <article><img alt="Jane Artist - Work One, 2001, Acrylic on canvas">
            <p>Jane Artist, 2001</p><h3><a href="/art/jane-artist/work-one">Work One</a></h3></article>
            <article><img src="/sites/default/files/sample.jpg" alt="Sample Artist - Sample Work, 1999, Oil on board">
            <p>Sample Artist, 1999</p><h3><a href="/art/sample-artist/sample-work">Sample Work</a></h3></article></div>
        """,
        "https://www.thebroad.org/art/collection-exhibitions/future-show": """
            <main id="main-content"><span>Collection Exhibition</span><h1>Has the myth been shattered</h1>
            <p class="exhibition-date">November 21, 2026 - April 4, 2027</p><h2>Featured Artworks</h2>
            <article><p>Jane Artist, 2001</p><h3><a href="/art/jane-artist/work-one">Work One</a></h3></article>
            <article><p>Co-artist and Second Artist, 1998–1999</p><h3>Work Two</h3>
            <a href="/art/co-artist-and-second-artist/work-two"></a></article>
            <h2>Credits</h2></main>
        """,
        "https://www.thebroad.org/events/public-talk": """
            <main id="main-content"><h1>Public Talk</h1><time datetime="2026-11-10">November 10, 2026 | 6:00 pm</time>
            <a href="https://maps.google.com/?q=REDCAT,+631+W+2nd+St,+Los+Angeles+CA,+90012">REDCAT</a>
            <h2>Bios</h2><h3><a href="/art/jane-artist">Jane Artist</a></h3></main>
        """,
        "https://www.thebroad.org/art/special-exhibitions/past-show": """
            <main id="main-content"><h1>Past Show</h1><p>January 10, 2025 – April 10, 2025</p></main>
        """,
        "https://www.thebroad.org/invisiblesun": """
            <main id="main-content"><h1>Invisible Sun</h1><p>October 3, 2020 – April 4, 2021</p></main>
        """,
        "https://www.thebroad.org/art/jane-artist/work-one": """
            <main id="main-content"><h1>Work One</h1><a href="/art/jane-artist">Jane Artist</a>
            <div>Accession Date:</div><div>05/24/18</div><div>Accession Number:</div><div>F-JANE-2018.001</div>
            <div>2001</div><div>Acrylic on canvas</div><div>25 x 30 cm</div></main>
        """,
        "https://www.thebroad.org/art/co-artist-and-second-artist/work-two": """
            <main id="main-content"><h1>Work Two</h1><a href="/art/co-artist-and-second-artist">Co-artist and Second Artist</a>
            <div>Accession Date:</div><div>05/24/18</div><div>Accession Number:</div><div>F-GROUP-2018.001</div>
            <div>1998–1999</div><div>Mixed media</div><div>40 x 50 cm</div></main>
        """,
        "https://www.thebroad.org/art/sample-artist/sample-work": """
            <main id="main-content"><h1>Sample Work</h1>
            <div>1999</div><div>Oil on board</div><div>20 x 20 cm</div></main>
        """,
        "https://www.thebroad.org/art/jane-artist": """
            <div role="main"><a id="main-content"></a><h1>Jane Artist</h1><h2>By Jane Artist in the Collection</h2>
            <article><img alt="Jane Artist - Work One, 2001, Acrylic on canvas"><p>Jane Artist, 2001</p>
            <h3><a href="/art/jane-artist/work-one">Work One</a></h3></article>
            <article><img alt="Jane Artist - Artist Page Work, 1997, Bronze"><p>Jane Artist, 1997</p>
            <h3><a href="/art/jane-artist/artist-page-work">Artist Page Work</a></h3></article></div>
        """,
        "https://www.thebroad.org/art/co-artist-and-second-artist": """
            <main id="main-content"><h1>Co-artist and Second Artist</h1><h2>By Artist in the Collection</h2>
            <article><p>Co-artist and Second Artist, 1998–1999</p>
            <h3><a href="/art/co-artist-and-second-artist/work-two">Work Two</a></h3></article></main>
        """,
        "https://www.thebroad.org/art/jane-artist/artist-page-work": """
            <main id="main-content"><h1>Artist Page Work</h1><a href="/art/jane-artist">Jane Artist</a>
            <div>1997</div><div>Bronze</div></main>
        """,
    }


def _collection_listing_pages(route_path, page_count):
    base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
    pages = {}
    for index in range(page_count):
        url = base_url if index == 0 else f"{base_url}?page={index}"
        next_link = f'<a rel="next" href="?page={index + 1}">Next</a>' if index + 1 < page_count else ""
        pages[url] = (f"<main id='main-content'><h1>Browse collection {route_path}</h1>"
                      f"{next_link}</main>")
    return pages


class GlobalFoundationsTests(unittest.TestCase):
    def test_new_observed_link_survives_older_alias_evidence(self):
        con = _connection()
        try:
            ctx = FakeContext(con, {})
            url = "https://www.thebroad.org/art/shared-artist"
            old = ctx.evidence(FakeResponse(url + "/work", "<main>Shared Artist</main>"),
                               locator="old listing")
            artist = gl_foundations._artist_entity(ctx, "Shared Artist", "shared-artist", old)
            self.assertIsNone(gl_foundations._persisted_artist_link_evidence(ctx, artist, url))
            response = FakeResponse(url + "/work", '<main><a href="/art/shared-artist">Shared Artist</a></main>')
            observed = gl_foundations._observed_artist_link_evidence(ctx, response, url)
            same_artist = gl_foundations._artist_entity(ctx, "Shared Artist", "shared-artist",
                                                        observed, observed_url=url)
            self.assertEqual(artist, same_artist)
            self.assertEqual(gl_foundations._persisted_artist_link_evidence(ctx, artist, url), observed)
            self.assertIsNone(gl_foundations._persisted_artist_link_evidence(ctx, "other-entity", url))
        finally:
            con.close()

    def test_persisted_artist_provenance_is_checked_once_per_shared_artist(self):
        con = _connection()
        try:
            url = "https://www.thebroad.org/art/shared-artist"
            artist = db.ensure_entity(
                con, entity_type="person", name="Shared Artist", namespace="broad_artist",
                id_value="shared-artist", source_id="broad_public", official_url=url,
            )
            for title in ("first-work", "second-work"):
                path = "/art/shared-artist/" + title
                db.upsert_work(
                    con, {}, id_namespace="broad_work", id_value=path, source_id="broad_public",
                    artist_entity_id=artist, title=title, url="https://www.thebroad.org" + path,
                )
            ctx = FakeContext(con, {})
            for evidence in ("observed-link", None):
                with self.subTest(evidence=evidence), patch.object(
                        gl_foundations, "_persisted_artist_link_evidence", return_value=evidence) as lookup:
                    records = gl_foundations._persisted_work_records(ctx)
                    lookup.assert_called_once_with(ctx, artist, url)
                    self.assertEqual(len(records), 2)
                    self.assertTrue(all(row["artist_url"] == (url if evidence else None) for row in records))
        finally:
            con.close()

    def test_drupal_skip_anchor_does_not_hide_actual_main_content(self):
        html = """<div role="main"><a id="main-content"></a><h2>Past Exhibitions</h2>
        <a href="/art/special-exhibitions/yoko-ono-music-mind">Yoko Ono: Music of the Mind</a></div>"""
        rows = gl_foundations._event_links(html, "https://www.thebroad.org/art/exhibitions/past")
        self.assertEqual(len(rows), 1)

    def test_source_rows_include_the_observed_kadist_block_and_broad_public_pages(self):
        rows = {row["source_id"]: row for row in gl_foundations.SOURCES}

        self.assertEqual(set(rows), {"kadist_public", "broad_public"})
        self.assertEqual(rows["kadist_public"]["operational_state"], "blocked_access")
        self.assertIn("HTTP 403", rows["kadist_public"]["disabled"])
        self.assertIn("2026-10-28", rows["kadist_public"]["st_live_response"])
        self.assertEqual(rows["kadist_public"]["country_codes"], "US,FR")
        self.assertNotIn("disabled", rows["broad_public"])
        self.assertEqual(rows["broad_public"]["country_codes"], "US")
        self.assertEqual(rows["broad_public"]["terms_url"], "https://www.thebroad.org/terms-use")

    def test_date_and_collection_card_parsers_preserve_published_values(self):
        html = """
            <main id="main-content"><h1>Exhibition</h1>
            <p>November 21, 2026 - April 4, 2027</p>
            <article><p>Jane Artist, 2001</p><h3><a href="/art/jane-artist/work-one">Work One</a></h3>
            <p>On View</p></article></main>
        """

        date_text, dates = gl_foundations._date_info(gl_foundations._main(html))
        works = gl_foundations._collection_records(html, "https://www.thebroad.org/art/browse")
        sample_html = """
            <div role="main"><a id="main-content"></a><article>
            <img alt="Jane Artist - Untitled #461, 2007/2008, dye sublimation metal print">
            <p>Jane Artist, 2007/2008</p><h3><a href="/art/jane-artist/untitled-461">Untitled #461</a></h3>
            <a href="/art/jane-artist">Jane Artist</a></article></div>
        """
        sample = gl_foundations._collection_records(
            sample_html, "https://www.thebroad.org/art/on-view/browse",
        )

        self.assertEqual(date_text, "November 21, 2026 - April 4, 2027")
        self.assertEqual(dates, ("2026-11-21", "day", "2027-04-04", "day"))
        self.assertEqual(works, [{
            "path": "/art/jane-artist/work-one", "artist_slug": "jane-artist", "title": "Work One",
            "date_text": "2001", "artist": "Jane Artist", "medium": None, "artist_url": None,
            "image_urls": [],
            "url": "https://www.thebroad.org/art/jane-artist/work-one",
        }])
        self.assertEqual(sample[0]["artist"], "Jane Artist")
        self.assertEqual(sample[0]["date_text"], "2007/2008")
        self.assertEqual(sample[0]["medium"], "dye sublimation metal print")
        self.assertEqual(sample[0]["artist_url"], "https://www.thebroad.org/art/jane-artist")

    def test_successful_pages_advance_beyond_each_run_cap(self):
        con = _connection()
        try:
            ctx = FakeContext(con, {}, mode="initial")
            detail_locator = "#main-content artwork metadata"
            detail_urls = [f"https://www.thebroad.org/art/artist/work-{index}" for index in range(30)]

            first_details, remaining = gl_foundations._unseen_page_batch(
                ctx, detail_urls, detail_locator, gl_foundations.MAX_WORK_DETAILS,
            )
            self.assertEqual(first_details, detail_urls[:gl_foundations.MAX_WORK_DETAILS])
            self.assertEqual(remaining, 5)
            for url in first_details:
                ctx.evidence(FakeResponse(url, "<div role='main'><h1>Work</h1></div>"),
                             locator=detail_locator, excerpt="parsed artwork detail")

            second_details, remaining = gl_foundations._unseen_page_batch(
                ctx, detail_urls, detail_locator, gl_foundations.MAX_WORK_DETAILS,
            )
            self.assertEqual(second_details, detail_urls[gl_foundations.MAX_WORK_DETAILS:])
            self.assertEqual(remaining, 0)

            artist_locator = "#main-content By artist in the Collection"
            artist_urls = [f"https://www.thebroad.org/art/artist-{index}" for index in range(15)]
            first_artists, remaining = gl_foundations._unseen_page_batch(
                ctx, artist_urls, artist_locator, gl_foundations.MAX_ARTIST_PAGES,
            )
            self.assertEqual(first_artists, artist_urls[:gl_foundations.MAX_ARTIST_PAGES])
            self.assertEqual(remaining, 3)
            for url in first_artists:
                ctx.evidence(FakeResponse(url, "<div role='main'><h1>Artist</h1></div>"),
                             locator=artist_locator, excerpt="parsed artist collection listing")
            next_artists, remaining = gl_foundations._unseen_page_batch(
                ctx, artist_urls, artist_locator, gl_foundations.MAX_ARTIST_PAGES,
            )
            self.assertEqual(next_artists, artist_urls[gl_foundations.MAX_ARTIST_PAGES:])
            self.assertEqual(remaining, 0)
        finally:
            con.close()

    def test_incremental_refresh_rotates_known_pages_after_unseen_pages(self):
        con = _connection()
        try:
            ctx = FakeContext(con, {}, mode="incremental")
            locator = "#main-content artwork metadata"
            known = [f"https://www.thebroad.org/art/artist/work-{index}" for index in range(4)]
            for url in known:
                ctx.evidence(FakeResponse(url, "<h1>Work</h1>"), locator=locator, excerpt="metadata")
            unseen = "https://www.thebroad.org/art/artist/new-work"
            first, remaining = gl_foundations._unseen_page_batch(
                ctx, known + [unseen], locator, 3, refresh=True,
            )
            self.assertEqual(first, [unseen] + known[:2])
            self.assertEqual(remaining, 0)
            con.execute(
                "INSERT INTO crawl_runs(run_id,source_id,mode,started_at,state) VALUES(?,?,?,?,?)",
                ("refresh-1", ctx.source_id, "incremental", "2026-10-28T00:00:00", "success"),
            )
            second, _ = gl_foundations._unseen_page_batch(
                ctx, known + [unseen], locator, 3, refresh=True,
            )
            self.assertEqual(second, [unseen] + known[2:])
        finally:
            con.close()

    def test_failed_page_without_success_evidence_remains_first_for_retry(self):
        con = _connection()
        try:
            ctx = FakeContext(con, {}, mode="initial")
            locator = "#main-content artwork metadata"
            urls = [f"https://www.thebroad.org/art/artist/work-{index}" for index in range(4)]
            first_batch, _ = gl_foundations._unseen_page_batch(ctx, urls, locator, 2)
            self.assertEqual(first_batch, urls[:2])
            # The first page succeeded; the second page failed and therefore has no success-ledger row.
            ctx.evidence(FakeResponse(first_batch[0], "<div role='main'><h1>Work</h1></div>"),
                         locator=locator, excerpt="parsed artwork detail")

            retry_batch, remaining = gl_foundations._unseen_page_batch(ctx, urls, locator, 2)

            self.assertEqual(retry_batch, [urls[1], urls[2]])
            self.assertEqual(remaining, 1)

            artist_locator = "#main-content By artist in the Collection"
            artist_urls = [f"https://www.thebroad.org/art/artist-{index}" for index in range(3)]
            first_artists, _ = gl_foundations._unseen_page_batch(ctx, artist_urls, artist_locator, 2)
            ctx.evidence(FakeResponse(first_artists[0], "<div role='main'><h1>Artist</h1></div>"),
                         locator=artist_locator, excerpt="parsed artist collection listing")
            retry_artists, remaining = gl_foundations._unseen_page_batch(ctx, artist_urls, artist_locator, 2)
            self.assertEqual(retry_artists, artist_urls[1:])
            self.assertEqual(remaining, 0)
        finally:
            con.close()

    def test_collection_listings_resume_beyond_cap_with_separate_route_ledgers(self):
        con = _connection()
        try:
            page_count = gl_foundations.MAX_COLLECTION_PAGES + 2
            pages = {}
            for route_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                pages.update(_collection_listing_pages(route_path, page_count))

            first = FakeContext(con, pages, mode="initial")
            gl_foundations._collect_works(first, None)

            for route_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
                locator = f"#main-content collection listing {route_path}"
                first_urls = {row[0] for row in con.execute(
                    "SELECT url FROM evidence WHERE source_id=? AND locator=?", (first.source_id, locator),
                )}
                expected_first_urls = {base_url} | {
                    f"{base_url}?page={index}" for index in range(1, gl_foundations.MAX_COLLECTION_PAGES)
                }
                self.assertEqual(first_urls, expected_first_urls)

            second = FakeContext(con, pages, mode="initial")
            second_result = gl_foundations._collect_works(second, None)

            for route_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
                locator = f"#main-content collection listing {route_path}"
                successful = {row[0] for row in con.execute(
                    "SELECT url FROM evidence WHERE source_id=? AND locator=?", (second.source_id, locator),
                )}
                expected_urls = {base_url} | {f"{base_url}?page={index}" for index in range(1, page_count)}
                self.assertEqual(successful, expected_urls)
                self.assertIn(base_url, [url for url, _ in second.calls])
                self.assertIn(f"{base_url}?page={gl_foundations.MAX_COLLECTION_PAGES}",
                              [url for url, _ in second.calls])
            self.assertTrue(all("exhausted" in route[-1] for route in second_result[-1]))
        finally:
            con.close()

    def test_collection_listing_failures_remain_retryable(self):
        con = _connection()
        try:
            route_path = "/art/browse"
            base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
            next_url = f"{base_url}?page=1"
            locator = f"#main-content collection listing {route_path}"
            pages = {}
            for listing_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                pages.update(_collection_listing_pages(listing_path, 2))

            failed_fetch = FakeContext(con, pages, mode="initial")
            failed_fetch.fetch_errors.add(next_url)
            gl_foundations._collect_works(failed_fetch, None)
            self.assertEqual(con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=? AND url=?",
                (failed_fetch.source_id, locator, next_url),
            ).fetchone()[0], 0)

            retry_fetch = FakeContext(con, pages, mode="initial")
            gl_foundations._collect_works(retry_fetch, None)
            self.assertIn(next_url, [url for url, _ in retry_fetch.calls])
            self.assertEqual(con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=? AND url=?",
                (retry_fetch.source_id, locator, next_url),
            ).fetchone()[0], 1)

        finally:
            con.close()

        parser_con = _connection()
        try:
            route_path = "/art/on-view/browse"
            base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
            next_url = f"{base_url}?page=1"
            locator = f"#main-content collection listing {route_path}"
            parser_pages = {}
            for listing_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                parser_pages.update(_collection_listing_pages(listing_path, 2))
            parser_pages[next_url] = "<main><h1>Access denied</h1><p>unrecognized response</p></main>"
            failed_parser = FakeContext(parser_con, parser_pages, mode="initial")
            gl_foundations._collect_works(failed_parser, None)
            self.assertEqual(parser_con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=? AND url=?",
                (failed_parser.source_id, locator, next_url),
            ).fetchone()[0], 0)

            retry_parser = FakeContext(parser_con, parser_pages, mode="initial")
            retry_parser.pages[next_url] = _collection_listing_pages(route_path, 2)[next_url]
            gl_foundations._collect_works(retry_parser, None)
            self.assertIn(next_url, [url for url, _ in retry_parser.calls])
            self.assertEqual(parser_con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=? AND url=?",
                (retry_parser.source_id, locator, next_url),
            ).fetchone()[0], 1)
        finally:
            parser_con.close()

    def test_incremental_collection_listing_refresh_does_not_follow_pager(self):
        con = _connection()
        try:
            pages = {}
            base_urls = []
            for route_path, _, _ in gl_foundations.COLLECTION_LISTINGS:
                base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
                base_urls.append(base_url)
                pages.update(_collection_listing_pages(route_path, 4))
            ctx = FakeContext(con, pages, mode="incremental")

            result = gl_foundations._collect_works(ctx, None)

            self.assertEqual([url for url, _ in ctx.calls], base_urls)
            self.assertTrue(all("public pager not drained in incremental mode" in route[-1]
                                for route in result[-1]))
        finally:
            con.close()

    def test_persisted_listing_records_keep_detail_and_artist_queues_alive(self):
        con = _connection()
        old_page_cap = gl_foundations.MAX_COLLECTION_PAGES
        old_detail_cap = gl_foundations.MAX_WORK_DETAILS
        old_artist_cap = gl_foundations.MAX_ARTIST_PAGES
        try:
            gl_foundations.MAX_COLLECTION_PAGES = 2
            gl_foundations.MAX_WORK_DETAILS = 2
            gl_foundations.MAX_ARTIST_PAGES = 1
            pages = {}
            total_cards = 7
            for route_path, page_count, first_index in (("/art/browse", 3, 0),
                                                        ("/art/on-view/browse", 1, 6)):
                base_url = f"{gl_foundations.BROAD_BASE}{route_path}"
                for page_index in range(page_count):
                    current_url = base_url if page_index == 0 else f"{base_url}?page={page_index}"
                    cards = []
                    for offset in range(2):
                        card_index = first_index + page_index * 2 + offset
                        if card_index >= total_cards:
                            continue
                        artist = f"Artist {card_index}"
                        slug = f"artist-{card_index}"
                        work_slug = f"work-{card_index}"
                        cards.append(
                            f"<article><p>{artist}, 2001</p><h3><a href='/art/{slug}/{work_slug}'>"
                            f"Work {card_index}</a></h3><a href='/art/{slug}'>{artist}</a></article>"
                        )
                        pages[f"{gl_foundations.BROAD_BASE}/art/{slug}/{work_slug}"] = (
                            f"<main><h1>Work {card_index}</h1><a href='/art/{slug}'>{artist}</a>"
                            "<div>2001</div><div>Oil on canvas</div></main>"
                        )
                        pages[f"{gl_foundations.BROAD_BASE}/art/{slug}"] = (
                            f"<main><h1>{artist}</h1><h2>By {artist} in the Collection</h2></main>"
                        )
                    next_link = (f'<a rel="next" href="?page={page_index + 1}">Next</a>'
                                 if page_index + 1 < page_count else "")
                    pages[current_url] = (f"<main id='main-content'><h1>Browse the Collection</h1>"
                                          f"{''.join(cards)}{next_link}</main>")

            first = FakeContext(con, pages, mode="initial")
            first_result = gl_foundations._collect_works(first, None)
            self.assertEqual(first_result[1], 5)
            self.assertEqual(first_result[5], 3)
            self.assertEqual(first_result[6], 4)

            second = FakeContext(con, pages, mode="initial")
            second_result = gl_foundations._collect_works(second, None)
            self.assertEqual(second_result[1], total_cards)
            self.assertEqual(second_result[5], 3)
            self.assertGreater(second_result[6], 0)
            self.assertIn("https://www.thebroad.org/art/browse?page=2", [url for url, _ in second.calls])
            self.assertTrue(all("exhausted" in route[-1] for route in second_result[-1]))

            result = second_result
            for _ in range(total_cards + 1):
                if result[5] == 0 and result[6] == 0:
                    break
                later = FakeContext(con, pages, mode="initial")
                result = gl_foundations._collect_works(later, None)
            self.assertEqual((result[5], result[6]), (0, 0))
            self.assertEqual(con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=?",
                (first.source_id, "#main-content artwork metadata"),
            ).fetchone()[0], total_cards)
            self.assertEqual(con.execute(
                "SELECT count(*) FROM evidence WHERE source_id=? AND locator=?",
                (first.source_id, "#main-content By artist in the Collection"),
            ).fetchone()[0], total_cards)
            self.assertEqual(con.execute(
                "SELECT count(*) FROM works WHERE source_id=? AND id_namespace='broad_work'",
                (first.source_id,),
            ).fetchone()[0], total_cards)
            self.assertEqual(con.execute(
                "SELECT count(*) FROM works WHERE source_id=? AND id_namespace='broad_work' "
                "AND date_text='2001' AND medium='Oil on canvas'",
                (first.source_id,),
            ).fetchone()[0], total_cards)
        finally:
            gl_foundations.MAX_COLLECTION_PAGES = old_page_cap
            gl_foundations.MAX_WORK_DETAILS = old_detail_cap
            gl_foundations.MAX_ARTIST_PAGES = old_artist_cap
            con.close()

    def test_broad_collects_public_exhibitions_programs_and_works_without_acquisition_claims(self):
        con = _connection()
        try:
            ctx = FakeContext(con, _pages())
            gl_foundations.collect(ctx)

            events = con.execute("SELECT * FROM events ORDER BY source_event_key").fetchall()
            self.assertEqual(len(events), 4)
            by_key = {row["source_event_key"]: row for row in events}
            future = by_key["/art/collection-exhibitions/future-show"]
            self.assertEqual(future["title"], "Has the myth been shattered")
            self.assertEqual((future["start_date"], future["start_precision"]), ("2026-11-21", "day"))
            self.assertEqual((future["end_date"], future["end_precision"]), ("2027-04-04", "day"))
            self.assertEqual(future["date_text"], "November 21, 2026 - April 4, 2027")
            self.assertEqual((future["city"], future["country_code"]), (None, None))
            self.assertEqual(future["subtype"], "collection_display")
            self.assertEqual(future["announced_status"], "scheduled")

            participants = con.execute(
                "SELECT p.role,p.extraction_method,e.canonical_name FROM event_participants p "
                "JOIN entities e USING(entity_id) WHERE p.event_id=?", (future["event_id"],),
            ).fetchall()
            self.assertEqual({(row["role"], row["extraction_method"], row["canonical_name"]) for row in participants},
                             {("artist", "list_markup", "Jane Artist"),
                              ("artist", "list_markup", "Co-artist and Second Artist")})

            program = by_key["/events/public-talk"]
            self.assertEqual(program["event_type"], "program")
            self.assertEqual(program["start_date"], "2026-11-10")
            self.assertEqual(program["announced_status"], "scheduled")
            self.assertEqual((program["city"], program["country_code"]), ("Los Angeles", "US"))
            self.assertIsNotNone(program["venue_id"])
            program_participants = con.execute(
                "SELECT p.role,p.extraction_method,e.canonical_name FROM event_participants p "
                "JOIN entities e USING(entity_id) WHERE p.event_id=?", (program["event_id"],),
            ).fetchall()
            self.assertEqual([(row["role"], row["extraction_method"], row["canonical_name"])
                              for row in program_participants], [("participant", "list_markup", "Jane Artist")])
            self.assertEqual(by_key["/art/special-exhibitions/past-show"]["announced_status"], None)
            self.assertEqual(by_key["/invisiblesun"]["subtype"], "collection_display")
            self.assertEqual(con.execute(
                "SELECT count(*) FROM review_queue WHERE item_type='region' AND issue='venue country unknown'"
            ).fetchone()[0], 3)

            works = con.execute("SELECT * FROM works ORDER BY title").fetchall()
            self.assertEqual([row["title"] for row in works],
                             ["Artist Page Work", "Sample Work", "Work One", "Work Two"])
            work_one = next(row for row in works if row["title"] == "Work One")
            self.assertEqual(work_one["date_text"], "2001")
            self.assertEqual(work_one["medium"], "Acrylic on canvas")
            self.assertIsNotNone(work_one["artist_entity_id"])
            self.assertIsNone(work_one["acquisition_text"])
            sample_work = next(row for row in works if row["title"] == "Sample Work")
            self.assertEqual((sample_work["date_text"], sample_work["medium"]), ("1999", "Oil on board"))
            image_right = con.execute(
                "SELECT usage_status,image_url FROM image_rights WHERE work_id=?", (sample_work["work_id"],),
            ).fetchone()
            self.assertEqual((image_right["usage_status"], image_right["image_url"]),
                             ("unknown", "https://www.thebroad.org/sites/default/files/sample.jpg"))
            excerpt = con.execute(
                "SELECT excerpt FROM evidence WHERE url='https://www.thebroad.org/art/jane-artist/work-one'"
            ).fetchone()[0]
            self.assertIn("05/24/18", excerpt)
            self.assertIn("25 x 30 cm", excerpt)
            artist_types = con.execute(
                "SELECT canonical_name,entity_type FROM entities WHERE id_namespace='broad_artist' "
                "ORDER BY canonical_name"
            ).fetchall()
            self.assertIn(("Co-artist and Second Artist", "group"), [(row["canonical_name"], row["entity_type"]) for row in artist_types])
            self.assertFalse(any("sites/default/files" in url for url, _ in ctx.calls))
            self.assertNotIn("https://www.thebroad.org/art/sample-artist", [url for url, _ in ctx.calls])

            organizer = db.ensure_entity(
                con, entity_type="institution", name="The Broad", namespace="src:broad_public",
                id_value="the-broad", source_id="broad_public", official_url=gl_foundations.BROAD_BASE,
            )
            con.execute(
                "UPDATE entities SET official_url=? WHERE entity_id=(SELECT artist_entity_id FROM works "
                "WHERE source_id=? AND id_value=?)",
                ("https://www.thebroad.org/art/sample-artist", "broad_public",
                 "/art/sample-artist/sample-work"),
            )
            original_sample_artist = con.execute(
                "SELECT e.entity_id,e.id_namespace,e.id_value FROM works w JOIN entities e "
                "ON e.entity_id=w.artist_entity_id WHERE w.source_id=? AND w.id_value=?",
                ("broad_public", "/art/sample-artist/sample-work"),
            ).fetchone()
            self.assertEqual((original_sample_artist["id_namespace"], original_sample_artist["id_value"]),
                             ("broad_artist", "sample-artist"))
            incremental = FakeContext(con, _pages(), mode="incremental")
            gl_foundations._collect_works(incremental, organizer)
            self.assertNotIn("https://www.thebroad.org/art/sample-artist",
                             [url for url, _ in incremental.calls])
            refreshed_sample_artist = con.execute(
                "SELECT e.entity_id,e.id_namespace,e.id_value FROM works w JOIN entities e "
                "ON e.entity_id=w.artist_entity_id WHERE w.source_id=? AND w.id_value=?",
                ("broad_public", "/art/sample-artist/sample-work"),
            ).fetchone()
            self.assertEqual(tuple(refreshed_sample_artist), tuple(original_sample_artist))
            preserved = con.execute(
                "SELECT title,date_text,medium,artist_entity_id FROM works WHERE id_value=?",
                ("/art/co-artist-and-second-artist/work-two",),
            ).fetchone()
            self.assertEqual((preserved["title"], preserved["date_text"], preserved["medium"]),
                             ("Work Two", "1998–1999", "Mixed media"))
            self.assertIsNotNone(preserved["artist_entity_id"])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
