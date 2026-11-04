"""Scratch-contract tests for the Met Open Access snapshot importer."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sqlite3
import unittest
from types import SimpleNamespace

from artrend_mag import db
from artrend_mag.http import FetchError
from artrend_mag.sources import met_collection


FIELDS = [
    "Object ID", "Is Public Domain", "Title", "Object Name", "Object Date", "Medium", "Classification",
    "Link Resource", "AccessionYear", "Credit Line", "Rights and Reproduction", "Constituent ID",
    "Artist Display Name", "Artist Nationality", "Artist Gender", "Artist Begin Date", "Artist End Date",
    "Artist ULAN URL", "Artist Wikidata URL", "Country",
]
OLD_SEEN = "2000-01-01T00:00:00+09:00"


class FakeResponse:
    def __init__(self, url, content):
        self.url = url
        self.final_url = url
        self.status = 200
        self.content = content
        self.fetched_at = "2026-10-28T09:00:00+09:00"
        self.sha256 = hashlib.sha256(content).hexdigest()
        self.raw_path = None

    def json(self):
        return json.loads(self.content)


class FakeContext:
    def __init__(self, con, metadata, dataset=None, mode="initial"):
        self.con = con
        self.source_id = met_collection.SOURCES[0]["source_id"]
        self.mode = mode
        self.parser_version = met_collection.PARSER_VERSION
        self.fetcher = SimpleNamespace(api_policy_url=met_collection.API_POLICY_URL)
        self.metadata = metadata
        self.dataset = dataset
        self.calls = []
        self.stats = {}
        self.notes = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == met_collection.API_URL:
            if self.fetcher.api_policy_url != met_collection.API_POLICY_URL:
                raise AssertionError("GitHub API fetch did not use its documented policy exception")
            return self.metadata
        if url == met_collection.CSV_URL:
            if self.fetcher.api_policy_url is not None:
                raise AssertionError("CSV download incorrectly bypassed its host robots policy")
            if self.dataset is None:
                raise AssertionError("unexpected full CSV download")
            return self.dataset
        raise AssertionError(f"unexpected URL {url}")

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


def _row(object_id="42", title="A Met work", object_date="ca. 1901–1903", medium="Oil on canvas",
         classification="Paintings", link="https://www.metmuseum.org/art/collection/search/42",
         is_public_domain="True", constituent_id="123", artist_name="Jane Artist", nationality="French",
         ulan="http://vocab.getty.edu/page/ulan/500012345", wikidata="https://www.wikidata.org/wiki/Q123",
         accession_year="2000", credit="Gift of a donor", rights="Rights note"):
    return {
        "Object ID": object_id,
        "Is Public Domain": is_public_domain,
        "Title": title,
        "Object Name": "Vase",
        "Object Date": object_date,
        "Medium": medium,
        "Classification": classification,
        "Link Resource": link,
        "AccessionYear": accession_year,
        "Credit Line": credit,
        "Rights and Reproduction": rights,
        "Constituent ID": constituent_id,
        "Artist Display Name": artist_name,
        "Artist Nationality": nationality,
        "Artist Gender": "Female",
        "Artist Begin Date": "1900",
        "Artist End Date": "1970",
        "Artist ULAN URL": ulan,
        "Artist Wikidata URL": wikidata,
        "Country": "United States",
    }


def _csv_response(*rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return FakeResponse(met_collection.CSV_URL, buffer.getvalue().encode("utf-8"))


def _metadata_response(dataset, declared_size=None):
    digest = hashlib.sha256(dataset.content).hexdigest()
    size = len(dataset.content) if declared_size is None else declared_size
    pointer = ("version https://git-lfs.github.com/spec/v1\n"
               f"oid sha256:{digest}\nsize {size}\n").encode("ascii")
    payload = {
        "name": "MetObjects.csv",
        "path": "MetObjects.csv",
        "size": size,
        "download_url": met_collection.CSV_URL,
        "encoding": "base64",
        "content": base64.b64encode(pointer).decode("ascii"),
    }
    return FakeResponse(met_collection.API_URL + "?ref=master", json.dumps(payload).encode("utf-8"))


def _connection():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db.init_schema(con)
    source = met_collection.SOURCES[0]
    fields = set(db.SOURCE_FIELDS + db.STATUS_FIELDS)
    db.upsert_source(con, source["source_id"], **{k: v for k, v in source.items() if k in fields})
    con.commit()
    return con


class MetCollectionTests(unittest.TestCase):
    def setUp(self):
        self.con = _connection()

    def tearDown(self):
        self.con.close()

    def test_initial_import_preserves_met_fields_and_only_direct_artist_ids(self):
        dataset = _csv_response(
            _row(),
            _row(object_id="43", constituent_id="124", artist_name="Jane Artist", nationality="Japanese",
                 ulan="", wikidata="", is_public_domain="False", rights=""),
            _row(object_id="44", constituent_id="125", artist_name="Jane Artist|Second Artist"),
        )
        ctx = FakeContext(self.con, _metadata_response(dataset), dataset)

        met_collection.collect(ctx)

        work = self.con.execute("SELECT * FROM works WHERE id_namespace='met' AND id_value='42'").fetchone()
        self.assertEqual(work["title"], "A Met work")
        self.assertEqual(work["date_text"], "ca. 1901–1903")
        self.assertEqual(work["medium"], "Oil on canvas")
        self.assertEqual(work["classification"], "Paintings")
        self.assertEqual(work["url"], "https://www.metmuseum.org/art/collection/search/42")
        self.assertEqual(work["is_public_domain"], 1)
        self.assertIn("AccessionYear=2000", work["acquisition_text"])
        self.assertIn("Credit Line=Gift of a donor", work["acquisition_text"])
        self.assertIn("Rights and Reproduction=Rights note", work["acquisition_text"])

        artist = self.con.execute(
            "SELECT * FROM entities WHERE id_namespace='met_artist' AND id_value='123'"
        ).fetchone()
        self.assertEqual(artist["canonical_name"], "Jane Artist")
        self.assertEqual(artist["nationality_text"], "French")
        aliases = self.con.execute(
            "SELECT namespace,external_id FROM aliases WHERE entity_id=? ORDER BY namespace", (artist["entity_id"],)
        ).fetchall()
        self.assertIn(("ulan", "500012345"), [(row["namespace"], row["external_id"]) for row in aliases])
        self.assertIn(("wikidata", "Q123"), [(row["namespace"], row["external_id"]) for row in aliases])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM entities WHERE id_namespace='met_artist' AND canonical_name='Jane Artist'"
        ).fetchone()[0], 2, "same display name with distinct Met constituent IDs must not merge")

        second = self.con.execute("SELECT is_public_domain FROM works WHERE id_namespace='met' AND id_value='43'").fetchone()
        self.assertEqual(second["is_public_domain"], 0)
        second_artist = self.con.execute("SELECT artist_entity_id FROM works WHERE id_namespace='met' AND id_value='43'").fetchone()
        self.assertIsNotNone(second_artist["artist_entity_id"])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM aliases WHERE entity_id=? AND namespace IN ('ulan','wikidata')",
            (self.con.execute("SELECT entity_id FROM entities WHERE id_namespace='met_artist' AND id_value='124'").fetchone()[0],),
        ).fetchone()[0], 0, "external IDs absent from the record must not be added")
        ambiguous = self.con.execute("SELECT artist_entity_id FROM works WHERE id_namespace='met' AND id_value='44'").fetchone()
        self.assertIsNone(ambiguous["artist_entity_id"], "ambiguous ID/name alignment must not create an artist")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM image_rights").fetchone()[0], 0)
        self.assertTrue(any("sha256=" in note for note in ctx.notes))
        self.assertTrue(any(call[0] == met_collection.CSV_URL for call in ctx.calls))
        self.assertIsNone(ctx.fetcher.api_policy_url)

    def test_same_completed_hash_skips_csv_and_refreshes_observation_times(self):
        dataset = _csv_response(_row())
        met_collection.collect(FakeContext(self.con, _metadata_response(dataset), dataset))
        self.con.execute("UPDATE works SET last_seen_at=?", (OLD_SEEN,))
        self.con.execute("UPDATE entities SET last_seen_at=?", (OLD_SEEN,))
        self.con.commit()

        ctx = FakeContext(self.con, _metadata_response(dataset), mode="incremental")
        met_collection.collect(ctx)

        self.assertEqual([call[0] for call in ctx.calls], [met_collection.API_URL])
        self.assertGreater(self.con.execute("SELECT last_seen_at FROM works").fetchone()[0], OLD_SEEN)
        self.assertGreater(self.con.execute(
            "SELECT last_seen_at FROM entities WHERE id_namespace='met_artist' LIMIT 1"
        ).fetchone()[0], OLD_SEEN)
        self.assertEqual(ctx.stats["parsed"], 1)
        self.assertTrue(any("without downloading CSV" in note for note in ctx.notes))

    def test_changed_snapshot_downloads_and_refreshes_fields_not_updated_by_shared_upsert(self):
        original = _csv_response(_row())
        met_collection.collect(FakeContext(self.con, _metadata_response(original), original))
        changed = _csv_response(_row(title="Updated title", object_date="1910", medium="Bronze",
                                     classification="Sculpture", link="https://www.metmuseum.org/art/collection/search/42/new",
                                     is_public_domain="False", artist_name="Jane Artist Revised",
                                     nationality="German"))
        ctx = FakeContext(self.con, _metadata_response(changed), changed, mode="incremental")

        met_collection.collect(ctx)

        work = self.con.execute("SELECT * FROM works WHERE id_namespace='met' AND id_value='42'").fetchone()
        self.assertEqual(work["title"], "Updated title")
        self.assertEqual(work["date_text"], "1910")
        self.assertEqual(work["medium"], "Bronze")
        self.assertEqual(work["classification"], "Sculpture")
        self.assertEqual(work["url"], "https://www.metmuseum.org/art/collection/search/42/new")
        self.assertEqual(work["is_public_domain"], 0)
        artist = self.con.execute(
            "SELECT canonical_name,nationality_text FROM entities WHERE id_namespace='met_artist' AND id_value='123'"
        ).fetchone()
        self.assertEqual(artist["canonical_name"], "Jane Artist Revised")
        self.assertEqual(artist["nationality_text"], "German")
        self.assertIn(met_collection.CSV_URL, [call[0] for call in ctx.calls])

    def test_declared_size_over_limit_stops_before_csv_download(self):
        small_dataset = _csv_response(_row())
        metadata = _metadata_response(small_dataset, declared_size=met_collection.MAX_CSV_BYTES + 1)
        ctx = FakeContext(self.con, metadata)

        with self.assertRaises(FetchError):
            met_collection.collect(ctx)

        self.assertNotIn(met_collection.CSV_URL, [call[0] for call in ctx.calls])


if __name__ == "__main__":
    unittest.main()
