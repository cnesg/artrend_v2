from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest

from artrend_mag import db
from artrend_mag.http import FetchError
from artrend_mag.sources import wave2_archives as w


class FakeResponse:
    def __init__(self, url, payload):
        self.url = url
        self.final_url = url
        self.status = 200
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.fetched_at = "2026-10-28T09:00:00+09:00"
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.raw_path = None

    def json(self):
        return json.loads(self.content)


class FakeContext:
    def __init__(self, con, responses):
        self.con = con
        self.source_id = w.AIC_SOURCE_ID
        self.mode = "initial"
        self.parser_version = w.PARSER_VERSION
        self.responses = list(responses)
        self.calls = []
        self.stats = {}
        self.notes = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url != w.AIC_SEARCH or not self.responses:
            raise AssertionError(f"unexpected fetch: {url}")
        return self.responses.pop(0)

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


def _page(current, total, records):
    return FakeResponse(w.AIC_SEARCH, {
        "pagination": {"current_page": current, "total_pages": total},
        "data": records,
    })


def _work(object_id, artist_id=72, artist_title="Artist Example", **overrides):
    record = {
        "id": object_id,
        "title": "A Chicago artwork",
        "artist_id": artist_id,
        "artist_title": artist_title,
        "date_display": "2020",
        "medium_display": "Oil on canvas",
        "classification_title": "painting",
        "artwork_type_title": "Painting",
        "dimensions": "50 × 60 cm",
        "main_reference_number": "2020.1",
        "api_link": f"https://api.artic.edu/api/v1/artworks/{object_id}",
        "is_public_domain": True,
        "credit_line": "Gift of a donor",
        "copyright_notice": None,
    }
    record.update(overrides)
    return record


def _connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    fields = set(db.SOURCE_FIELDS + db.STATUS_FIELDS)
    for source in w.SOURCES:
        db.upsert_source(con, source["source_id"], **{key: value for key, value in source.items() if key in fields})
    con.commit()
    return con


class AICCollectionTests(unittest.TestCase):
    def setUp(self):
        self.con = _connection()

    def tearDown(self):
        self.con.close()

    def test_collects_offline_pages_and_uses_record_ids_for_artists(self):
        first = _page(1, 2, [_work(501), _work(502)])
        second = _page(2, 2, [_work(503, copyright_notice="© AIC", is_public_domain=False)])
        ctx = FakeContext(self.con, [first, second])

        w.collect(ctx)

        self.assertEqual([call[1]["params"]["page"] for call in ctx.calls], [1, 2])
        for _, kwargs in ctx.calls:
            self.assertEqual(kwargs["params"]["query[range][date_start][gte]"], "2015")
            self.assertEqual(kwargs["params"]["limit"], 100)
            self.assertEqual(kwargs["params"]["fields"], w.AIC_FIELDS)
        works = self.con.execute("SELECT * FROM works ORDER BY id_value").fetchall()
        self.assertEqual(len(works), 3)
        self.assertEqual(works[0]["id_namespace"], "aic")
        self.assertEqual(works[0]["id_value"], "501")
        self.assertEqual(works[0]["title"], "A Chicago artwork")
        self.assertEqual(works[0]["medium"], "Oil on canvas")
        self.assertEqual(works[0]["date_text"], "2020")
        self.assertIn("Main reference number=2020.1", works[0]["acquisition_text"])
        self.assertEqual(works[0]["is_public_domain"], 1)
        self.assertEqual(works[2]["is_public_domain"], 0)
        artists = self.con.execute(
            "SELECT * FROM entities WHERE id_namespace='aic' AND id_value='72'"
        ).fetchall()
        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0]["canonical_name"], "Artist Example")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM image_rights").fetchone()[0], 0)
        self.assertEqual(ctx.stats["parsed"], 3)
        self.assertTrue(any("older or undated works are outside scope" in note for note in ctx.notes))

    def test_name_without_a_record_artist_id_does_not_create_identity(self):
        ctx = FakeContext(self.con, [_page(1, 1, [_work(601, artist_id=None)])])

        w.collect(ctx)

        work = self.con.execute("SELECT artist_entity_id FROM works WHERE id_value='601'").fetchone()
        self.assertIsNone(work["artist_entity_id"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM entities WHERE entity_type='person'").fetchone()[0], 0)

    def test_request_budget_rejects_unbounded_result_before_writes(self):
        ctx = FakeContext(self.con, [_page(1, w.MAX_PAGES + 1, [_work(701)])])

        with self.assertRaises(FetchError):
            w.collect(ctx)

        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM works").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM entities").fetchone()[0], 0)

    def test_documented_blocks_are_explicit_and_source_ids_are_unique(self):
        ids = [source["source_id"] for source in w.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        europeana = next(source for source in w.SOURCES if source["source_id"] == w.EUROPEANA_SOURCE_ID)
        self.assertEqual(europeana["operational_state"], "blocked_credentials")
        self.assertIn("free Europeana account", europeana["disabled"])
        self.assertIsNone(europeana["blueprint_data_id"])

        artuk = next(source for source in w.SOURCES if source["source_id"] == w.ARTUK_SOURCE_ID)
        self.assertEqual(artuk["operational_state"], "blocked_access")
        self.assertEqual(artuk["robots_status"], "robots_http_403(not_crawled)")
        self.assertEqual(artuk["st_live_response"], "not_requested(robots HTTP 403)")

        rkd = next(source for source in w.SOURCES if source["source_id"] == w.RKD_SOURCE_ID)
        self.assertEqual(rkd["operational_state"], "blocked_access")
        self.assertEqual(rkd["robots_status"], "robots_http_403(not_crawled)")
        self.assertIsNone(rkd["blueprint_data_id"])


if __name__ == "__main__":
    unittest.main()
