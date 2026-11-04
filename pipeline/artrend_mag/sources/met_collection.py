"""The Met Open Access collection CSV (Blueprint D04).

The Met's official openaccess repository dedicates the CSV dataset to CC0 and
stores MetObjects.csv as Git LFS. The repository README says the dataset has
more than 470,000 artworks and excludes images. GitHub's documented Contents
API exposes the LFS snapshot pointer; its documented unauthenticated public-data
limit is 60 requests/hour. We use that API only for snapshot metadata, then the
repository's published media download URL for the CSV (never github.com/raw/).

The API policy exception is scoped to the metadata request; the CSV download
uses the normal robots check for media.githubusercontent.com. The CSV is
checked against a 400,000,000-byte limit, parsed row-by-row, and archived internally with its SHA-256.
No object/acquisition dates are treated as exhibition events.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import unicodedata
from urllib.parse import urlsplit

from .. import db
from ..config import iso_now
from ..http import FetchError
from ._common import clean_text

PARSER_VERSION = "met-openaccess-1"
API_URL = "https://api.github.com/repos/metmuseum/openaccess/contents/MetObjects.csv"
API_POLICY_URL = "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api"
CSV_URL = "https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv"
MAX_CSV_BYTES = 400_000_000
COMMIT_EVERY = 5_000

SOURCES = [dict(
    source_id="met_collection_github", blueprint_data_id="D04", blueprint_org_id=None,
    name="The Met Open Access collection (GitHub CSV)", owner_group="The Metropolitan Museum of Art",
    source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="download",
    base_url="https://github.com/metmuseum/openaccess",
    entry_url=f"{API_URL}?ref=master",
    terms_url="https://github.com/metmuseum/openaccess/blob/master/README.md",
    text_storage_policy="raw_internal", priority="P1",
    api_policy_url=API_POLICY_URL,
    extra_headers={"X-GitHub-Api-Version": "2022-11-28"},
    min_interval=3, max_requests=6,
    st_official_doc="ok(Met Open Access README; official GitHub Contents API/LFS pointer)",
    st_collection_terms="ok(CC0 dataset per Met README/LICENSE; records may describe copyrighted works)",
    st_image_terms="images excluded from CSV; image rights remain separate",
)]


def collect(ctx):
    con = ctx.con
    metadata = _fetch_snapshot_metadata(ctx)
    snapshot_sha, snapshot_size, download_url = _snapshot_info(metadata)
    marker = _completion_locator(snapshot_sha, snapshot_size)
    ctx.note(f"MetObjects.csv snapshot sha256={snapshot_sha} size={snapshot_size} bytes")

    # Keep an observation for each run even when the API response is byte-identical.
    metadata_locator = (f"GitHub Contents API snapshot sha256={snapshot_sha} "
                        f"size={snapshot_size} observed={metadata.fetched_at}")
    ctx.evidence(metadata, locator=metadata_locator)

    complete = con.execute(
        "SELECT 1 FROM evidence WHERE source_id=? AND raw_sha256=? AND locator=? LIMIT 1",
        (ctx.source_id, snapshot_sha, marker),
    ).fetchone()
    if complete:
        _holding_entity(ctx)
        _refresh_observations(con, ctx.source_id)
        count = con.execute("SELECT COUNT(*) FROM works WHERE source_id=?", (ctx.source_id,)).fetchone()[0]
        ctx.count("fetched", count)
        ctx.count("parsed", count)
        ctx.count("unchanged", count)
        ctx.note(f"unchanged completed snapshot; refreshed observations for {count} works without downloading CSV")
        con.commit()
        return

    ctx.note(f"{ctx.mode} mode has no completed marker for this snapshot; downloading and parsing the full CSV")
    response = ctx.fetch(download_url, accept="text/csv")
    if urlsplit(response.final_url).hostname != "media.githubusercontent.com":
        raise FetchError(f"unexpected Met CSV redirect host: {response.final_url}")
    if len(response.content) > MAX_CSV_BYTES:
        raise FetchError(f"Met CSV response exceeds {MAX_CSV_BYTES}-byte download limit")
    if len(response.content) != snapshot_size:
        raise FetchError(f"Met CSV size mismatch: expected {snapshot_size}, received {len(response.content)}")
    actual_sha = hashlib.sha256(response.content).hexdigest()
    if actual_sha != snapshot_sha:
        raise FetchError(f"Met CSV SHA-256 mismatch: expected {snapshot_sha}, received {actual_sha}")

    data_evidence = ctx.evidence(response, locator=f"MetObjects.csv payload sha256={snapshot_sha}")
    holding = _holding_entity(ctx, data_evidence)
    n_rows, n_works, n_missing_ids = _import_rows(ctx, response.content, holding, data_evidence)
    if not n_works:
        raise FetchError("Met CSV contained no rows with Object ID; snapshot was not marked complete")

    # This durable marker is added only after all rows were parsed. A partial run
    # can therefore safely retry even though batches already committed.
    ctx.evidence(response, locator=marker)
    ctx.note(f"completed MetObjects.csv snapshot: rows={n_rows}, works={n_works}, "
             f"missing_object_ids={n_missing_ids}, sha256={snapshot_sha}")
    ctx.note("Object Date, AccessionYear, and Credit Line are work metadata; no exhibition events are created.")
    con.commit()


def _fetch_snapshot_metadata(ctx):
    fetcher = ctx.fetcher
    if fetcher.api_policy_url != API_POLICY_URL:
        raise FetchError("documented GitHub API policy exception is not configured for Met snapshot metadata")
    try:
        return ctx.fetch(API_URL, params={"ref": "master"}, accept="application/vnd.github+json")
    finally:
        # The exception applies only to the documented GitHub API. The LFS CSV
        # host is subject to its own robots.txt and is not treated as an API.
        fetcher.api_policy_url = None


def _snapshot_info(response):
    try:
        metadata = response.json()
        size = int(metadata["size"])
        encoded_pointer = metadata["content"]
        encoding = metadata["encoding"]
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"GitHub did not return usable MetObjects.csv snapshot metadata: {exc}") from exc

    if metadata.get("name") != "MetObjects.csv" or metadata.get("path") != "MetObjects.csv":
        raise FetchError("GitHub Contents API returned a different file than MetObjects.csv")
    if encoding != "base64" or not isinstance(encoded_pointer, str):
        raise FetchError("GitHub Contents API did not return the documented base64 LFS pointer")
    if not 0 < size <= MAX_CSV_BYTES:
        raise FetchError(f"Met CSV declared size {size} is outside the 1..{MAX_CSV_BYTES} byte limit")
    if size != metadata.get("size") or metadata.get("download_url") != CSV_URL:
        raise FetchError("GitHub Contents API returned unexpected Met CSV size or download URL")

    try:
        pointer = base64.b64decode(encoded_pointer).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise FetchError(f"invalid Git LFS pointer for MetObjects.csv: {exc}") from exc
    values = {}
    for line in pointer.splitlines():
        key, separator, value = line.partition(" ")
        if separator:
            values[key] = value.strip()
    match = re.fullmatch(r"sha256:([0-9a-f]{64})", values.get("oid", ""))
    try:
        pointer_size = int(values.get("size", ""))
    except ValueError as exc:
        raise FetchError("Git LFS pointer has an invalid file size") from exc
    if values.get("version") != "https://git-lfs.github.com/spec/v1" or not match:
        raise FetchError("GitHub Contents API response is not a valid MetObjects.csv LFS pointer")
    if pointer_size != size:
        raise FetchError(f"Met CSV metadata size {size} differs from LFS pointer size {pointer_size}")
    return match.group(1), size, CSV_URL


def _completion_locator(snapshot_sha, snapshot_size):
    return (f"MetObjects.csv complete sha256={snapshot_sha} size={snapshot_size} "
            f"parser={PARSER_VERSION}")


def _holding_entity(ctx, evidence_id=None):
    return db.ensure_entity(
        ctx.con, entity_type="institution", name="The Metropolitan Museum of Art",
        namespace=f"src:{ctx.source_id}", id_value="met", lang="en", source_id=ctx.source_id,
        evidence_id=evidence_id, official_url="https://www.metmuseum.org/",
    )


def _refresh_observations(con, source_id):
    observed_at = iso_now()
    con.execute("UPDATE works SET last_seen_at=? WHERE source_id=?", (observed_at, source_id))
    con.execute(
        "UPDATE entities SET last_seen_at=? WHERE entity_id IN "
        "(SELECT entity_id FROM aliases WHERE source_id=?)",
        (observed_at, source_id),
    )


def _import_rows(ctx, content, holding_entity_id, evidence_id):
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline=""))
    required = {
        "Object ID", "Title", "Object Name", "Object Date", "Medium", "Classification", "Link Resource",
        "Is Public Domain", "Constituent ID", "Artist Display Name", "Artist Nationality", "Artist Gender",
        "Artist Begin Date", "Artist End Date", "Artist ULAN URL", "Artist Wikidata URL", "AccessionYear",
        "Credit Line", "Rights and Reproduction",
    }
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise FetchError(f"Met CSV is missing expected fields: {', '.join(sorted(missing))}")

    rows = works = missing_ids = 0
    try:
        for row in reader:
            rows += 1
            ctx.count("fetched")
            object_id = _text(row, "Object ID")
            if not object_id:
                missing_ids += 1
                continue

            artist_entity_id = _artists_for_row(ctx, row, evidence_id)
            title = clean_text(_text(row, "Title") or _text(row, "Object Name")) or None
            date_text = _text(row, "Object Date") or None
            medium = clean_text(_text(row, "Medium")) or None
            classification = clean_text(_text(row, "Classification")) or None
            url = _text(row, "Link Resource") or None
            acquisition_text = _acquisition_text(row)
            is_public_domain = _boolean(row.get("Is Public Domain"))
            db.upsert_work(
                ctx.con, ctx.stats, id_namespace="met", id_value=object_id, source_id=ctx.source_id,
                artist_entity_id=artist_entity_id, title=title, date_text=date_text, medium=medium,
                classification=classification, holding_entity_id=holding_entity_id,
                acquisition_text=acquisition_text, url=url, is_public_domain=is_public_domain,
            )
            works += 1
            ctx.count("parsed")
            if rows % COMMIT_EVERY == 0:
                ctx.con.commit()
    except (csv.Error, UnicodeDecodeError) as exc:
        raise FetchError(f"could not parse Met CSV: {exc}") from exc
    return rows, works, missing_ids


def _artists_for_row(ctx, row, evidence_id):
    ids = _values(row.get("Constituent ID"))
    names = _values(row.get("Artist Display Name"))
    if len(ids) == 1 and sum(bool(name) for name in names) > 1:
        # A single ID beside multiple names is ambiguous; do not attach the ID
        # to a guessed artist or create a name-based identity.
        return None
    nationalities = _values(row.get("Artist Nationality"))
    genders = _values(row.get("Artist Gender"))
    births = _values(row.get("Artist Begin Date"))
    deaths = _values(row.get("Artist End Date"))
    ulans = _values(row.get("Artist ULAN URL"))
    wikidata = _values(row.get("Artist Wikidata URL"))
    first_entity_id = None
    seen_ids = set()

    for index, constituent_id in enumerate(ids):
        if not constituent_id.isdigit() or constituent_id in seen_ids:
            continue
        name = clean_text(_at(names, index))
        if not name:
            continue
        seen_ids.add(constituent_id)
        birth_year = _year(_at(births, index))
        death_year = _year(_at(deaths, index))
        nationality = _at(nationalities, index) or None
        entity_type = "person" if (_at(genders, index) or birth_year or death_year) else "unknown"
        entity_id = db.ensure_entity(
            ctx.con, entity_type=entity_type,
            name=name, namespace="met_artist", id_value=constituent_id, source_id=ctx.source_id,
            evidence_id=evidence_id, nationality_text=nationality,
            birth_year=birth_year, death_year=death_year,
        )
        canonical_name = unicodedata.normalize("NFC", name)
        ctx.con.execute(
            "UPDATE entities SET entity_type=?, canonical_name=?, nationality_text=?, birth_year=?, death_year=? "
            "WHERE entity_id=? AND (entity_type IS NOT ? OR canonical_name IS NOT ? OR nationality_text IS NOT ? "
            "OR birth_year IS NOT ? OR death_year IS NOT ?)",
            (entity_type, canonical_name, nationality, birth_year, death_year, entity_id,
             entity_type, canonical_name, nationality, birth_year, death_year),
        )
        ulan_id = _external_id(_at(ulans, index), "ulan")
        if ulan_id:
            db.add_alias(ctx.con, entity_id, name, None, "ulan", ulan_id, ctx.source_id, evidence_id)
        wikidata_id = _external_id(_at(wikidata, index), "wikidata")
        if wikidata_id:
            db.add_alias(ctx.con, entity_id, name, None, "wikidata", wikidata_id, ctx.source_id, evidence_id)
        if first_entity_id is None:
            first_entity_id = entity_id
    return first_entity_id


def _text(row, field):
    return (row.get(field) or "").strip()


def _values(value):
    return [part.strip() for part in (value or "").split("|")]


def _at(values, index):
    return values[index] if index < len(values) else ""


def _year(value):
    value = (value or "").strip()
    return int(value) if re.fullmatch(r"\d{1,4}", value) and int(value) > 0 else None


def _boolean(value):
    normalized = (value or "").strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _acquisition_text(row):
    fields = (
        ("AccessionYear", "AccessionYear"),
        ("Credit Line", "Credit Line"),
        ("Rights and Reproduction", "Rights and Reproduction"),
    )
    values = [f"{label}={_text(row, field)}" for label, field in fields if _text(row, field)]
    return " | ".join(values) or None


def _external_id(value, namespace):
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or parsed.query or parsed.fragment:
        return None
    if namespace == "ulan" and parsed.hostname == "vocab.getty.edu":
        match = re.fullmatch(r"/page/ulan/(\d+)/?", parsed.path)
        return match.group(1) if match else None
    if namespace == "wikidata" and parsed.hostname in ("www.wikidata.org", "wikidata.org"):
        match = re.fullmatch(r"/(?:wiki|entity)/(Q[1-9]\d*)/?", parsed.path)
        return match.group(1) if match else None
    return None
