"""SQLite store helpers. All writes are idempotent upserts keyed by deterministic IDs."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from . import region
from .config import DB_PATH, SCHEMA_VERSION, iso_now

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def sid(prefix: str, *parts) -> str:
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def name_key(name: str) -> str:
    """Search/identity key: NFKC, casefold, collapse whitespace, strip punctuation. Display names are kept as-is."""
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = re.sub(r"[\u2018\u2019'`\".,()\[\]]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    con.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SCHEMA_VERSION,))
    con.executemany(
        "INSERT INTO region_map(country_code,country_name,m49_region,edition_region,version) VALUES(?,?,?,?,?) "
        "ON CONFLICT(country_code) DO UPDATE SET country_name=excluded.country_name, m49_region=excluded.m49_region, "
        "edition_region=excluded.edition_region, version=excluded.version",
        list(region.all_rows()),
    )
    con.commit()


SOURCE_FIELDS = (
    "blueprint_data_id", "blueprint_org_id", "name", "owner_group", "source_kind", "region_scope", "country_codes",
    "access_method", "base_url", "entry_url", "terms_url", "text_storage_policy", "priority", "notes",
)
STATUS_FIELDS = (
    "st_local_file", "st_official_doc", "st_live_response", "st_fields_extracted", "st_history", "st_incremental",
    "st_collection_terms", "st_image_terms", "robots_status", "operational_state",
)


def upsert_source(con, source_id: str, **kw) -> None:
    cols = ["source_id", *[k for k in SOURCE_FIELDS + STATUS_FIELDS if k in kw], "updated_at"]
    vals = [source_id, *[kw[k] for k in cols[1:-1]], iso_now()]
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
    con.execute(
        f"INSERT INTO sources({','.join(cols)}) VALUES({','.join('?' * len(cols))}) ON CONFLICT(source_id) DO UPDATE SET {upd}",
        vals,
    )


def set_source_status(con, source_id: str, **status) -> None:
    bad = set(status) - set(STATUS_FIELDS) - {"notes"}
    if bad:
        raise ValueError(f"unknown status fields {bad}")
    sets = ", ".join(f"{k}=?" for k in status)
    con.execute(f"UPDATE sources SET {sets}, updated_at=? WHERE source_id=?", [*status.values(), iso_now(), source_id])


def ensure_entity(con, *, entity_type: str, name: str, namespace: str, id_value: str | None = None,
                  lang: str | None = None, source_id: str | None = None, evidence_id: str | None = None,
                  official_url: str | None = None, nationality_text: str | None = None,
                  birth_year: int | None = None, death_year: int | None = None,
                  verification_status: str = "source_asserted", parent_entity_id: str | None = None) -> str:
    """Create/refresh an entity identified by (namespace, id_value). Source-local namespaces use the
    normalized name as id_value, so the same name in two sources yields two entities (linked later as candidates)."""
    name = unicodedata.normalize("NFC", name.strip())
    id_value = id_value if id_value not in (None, "") else name_key(name)
    eid = sid("ent", namespace, id_value)
    now = iso_now()
    con.execute(
        "INSERT INTO entities(entity_id, entity_type, canonical_name, name_lang, id_namespace, id_value, parent_entity_id,"
        " nationality_text, birth_year, death_year, official_url, verification_status, first_seen_at, last_seen_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,"
        " nationality_text=COALESCE(excluded.nationality_text, entities.nationality_text),"
        " birth_year=COALESCE(excluded.birth_year, entities.birth_year), death_year=COALESCE(excluded.death_year, entities.death_year),"
        " official_url=COALESCE(excluded.official_url, entities.official_url),"
        " parent_entity_id=COALESCE(excluded.parent_entity_id, entities.parent_entity_id)",
        (eid, entity_type, name, lang, namespace, id_value, parent_entity_id, nationality_text, birth_year, death_year,
         official_url, verification_status, now, now),
    )
    add_alias(con, eid, name, lang, "name", "", source_id, evidence_id)
    if not namespace.startswith("src:"):
        add_alias(con, eid, name, lang, namespace, id_value, source_id, evidence_id)
    return eid


def add_alias(con, entity_id, name, lang, namespace, external_id, source_id, evidence_id, match_status="source_asserted"):
    con.execute(
        "INSERT INTO aliases(entity_id,name,lang,namespace,external_id,source_id,evidence_id,match_status) VALUES(?,?,?,?,?,?,?,?)"
        " ON CONFLICT DO NOTHING",
        (entity_id, name, lang, namespace, external_id or "", source_id, evidence_id, match_status),
    )


def add_evidence(con, *, source_id: str, url: str, fetched_at: str, http_status: int | None, raw_path: str | None,
                 raw_sha256: str | None, locator: str | None = None, excerpt: str | None = None,
                 parser_version: str | None = None) -> str:
    """Evidence identity = (source, url, raw hash, locator). Re-fetching identical content reuses the row."""
    eid = sid("evd", source_id, url, raw_sha256 or "", locator or "")
    con.execute(
        "INSERT INTO evidence(evidence_id,source_id,url,fetched_at,http_status,raw_path,raw_sha256,locator,excerpt,parser_version)"
        " VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(evidence_id) DO NOTHING",
        (eid, source_id, url, fetched_at, http_status, raw_path, raw_sha256, locator, (excerpt or "")[:300] or None, parser_version),
    )
    return eid


def upsert_event(con, stats: dict, *, source_id: str, source_event_key: str, event_type: str, title: str,
                 parser_version: str, subtype=None, title_lang=None, organizer_entity_id=None, venue_id=None,
                 city=None, country_code=None, start_date=None, start_precision=None, end_date=None,
                 end_precision=None, announced_date=None, date_text=None, announced_status=None, tour_id=None,
                 parent_event_id=None, url=None, description_excerpt=None, evidence_id=None) -> str:
    """Insert or update one event. stats counts inserted/updated/unchanged based on a content hash of the
    substantive fields (first_seen_at is never moved; last_seen_at always refreshed)."""
    event_id = sid("evt", source_id, source_event_key)
    edition = region.edition_region(country_code)
    payload = dict(event_type=event_type, subtype=subtype, title=title, title_lang=title_lang,
                   organizer_entity_id=organizer_entity_id, venue_id=venue_id, city=city, country_code=country_code,
                   edition_region=edition, start_date=start_date, start_precision=start_precision, end_date=end_date,
                   end_precision=end_precision, announced_date=announced_date, date_text=date_text,
                   announced_status=announced_status, tour_id=tour_id, parent_event_id=parent_event_id, url=url,
                   description_excerpt=(description_excerpt or "")[:300] or None)
    h = content_hash(payload)
    now = iso_now()
    row = con.execute("SELECT content_hash FROM events WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        cols = ["event_id", "source_id", "source_event_key", *payload, "first_seen_at", "last_seen_at", "content_hash", "parser_version"]
        con.execute(f"INSERT INTO events({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [event_id, source_id, source_event_key, *payload.values(), now, now, h, parser_version])
        stats["inserted"] = stats.get("inserted", 0) + 1
    elif row["content_hash"] != h:
        sets = ", ".join(f"{k}=?" for k in payload)
        con.execute(f"UPDATE events SET {sets}, last_seen_at=?, content_hash=?, parser_version=? WHERE event_id=?",
                    [*payload.values(), now, h, parser_version, event_id])
        stats["updated"] = stats.get("updated", 0) + 1
    else:
        con.execute("UPDATE events SET last_seen_at=? WHERE event_id=?", (now, event_id))
        stats["unchanged"] = stats.get("unchanged", 0) + 1
    if evidence_id:
        con.execute("INSERT INTO event_evidence(event_id,evidence_id) VALUES(?,?) ON CONFLICT DO NOTHING", (event_id, evidence_id))
    return event_id


def add_participant(con, event_id, entity_id, role, name_as_listed, evidence_id, extraction_method, confidence="high"):
    con.execute(
        "INSERT INTO event_participants(event_id,entity_id,role,name_as_listed,evidence_id,extraction_method,confidence)"
        " VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id,entity_id,role) DO UPDATE SET evidence_id=excluded.evidence_id",
        (event_id, entity_id, role, name_as_listed, evidence_id, extraction_method, confidence),
    )


def upsert_relationship(con, *, subject_entity_id, object_entity_id, rel_type, source_id, evidence_id=None,
                        scope=None, valid_from=None, valid_to=None, announced_date=None, status="source_asserted") -> str:
    rel_id = sid("rel", subject_entity_id, object_entity_id, rel_type, source_id)
    now = iso_now()
    con.execute(
        "INSERT INTO relationships(rel_id,subject_entity_id,object_entity_id,rel_type,scope,valid_from,valid_to,announced_date,"
        " first_seen_at,last_seen_at,source_id,evidence_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(rel_id) DO UPDATE SET last_seen_at=excluded.last_seen_at, evidence_id=COALESCE(excluded.evidence_id, relationships.evidence_id),"
        " announced_date=COALESCE(excluded.announced_date, relationships.announced_date)",
        (rel_id, subject_entity_id, object_entity_id, rel_type, scope, valid_from, valid_to, announced_date, now, now,
         source_id, evidence_id, status),
    )
    return rel_id


def upsert_article(con, stats: dict, *, source_id: str, canonical_url: str, title: str, published_at=None,
                   author_text=None, publisher=None, owner_group=None, article_type="unknown", type_basis=None,
                   lang=None, modified_at=None, categories=None, excerpt=None) -> str:
    article_id = sid("art", canonical_url)
    group_key = name_key(re.sub(r"\s[-|–—]\s[^-|–—]+$", "", title))[:120]
    payload = dict(source_id=source_id, title=title, author_text=author_text, publisher=publisher, owner_group=owner_group,
                   article_type=article_type, type_basis=type_basis, lang=lang, published_at=published_at,
                   modified_at=modified_at, categories=categories, excerpt=(excerpt or "")[:300] or None,
                   origin_group_key=group_key)
    h = content_hash(payload)
    now = iso_now()
    row = con.execute("SELECT content_hash, source_id FROM articles WHERE article_id=?", (article_id,)).fetchone()
    if row is not None and row["source_id"] != source_id:
        # same URL already owned by another source: first writer keeps the row (no ping-pong between sources)
        con.execute("UPDATE articles SET last_seen_at=? WHERE article_id=?", (now, article_id))
        stats["seen_in_other_source"] = stats.get("seen_in_other_source", 0) + 1
        return article_id
    if row is None:
        cols = ["article_id", "canonical_url", *payload, "first_seen_at", "last_seen_at", "content_hash"]
        con.execute(f"INSERT INTO articles({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [article_id, canonical_url, *payload.values(), now, now, h])
        stats["inserted"] = stats.get("inserted", 0) + 1
    elif row["content_hash"] != h:
        sets = ", ".join(f"{k}=?" for k in payload)
        con.execute(f"UPDATE articles SET {sets}, last_seen_at=?, content_hash=? WHERE article_id=?", [*payload.values(), now, h, article_id])
        stats["updated"] = stats.get("updated", 0) + 1
    else:
        con.execute("UPDATE articles SET last_seen_at=? WHERE article_id=?", (now, article_id))
        stats["unchanged"] = stats.get("unchanged", 0) + 1
    return article_id


def upsert_work(con, stats: dict, *, id_namespace, id_value, source_id, artist_entity_id=None, title=None, date_text=None,
                medium=None, classification=None, holding_entity_id=None, acquisition_text=None, url=None,
                is_public_domain=None) -> str:
    work_id = sid("wrk", id_namespace, id_value)
    now = iso_now()
    fields = ("artist_entity_id", "title", "date_text", "medium", "classification", "holding_entity_id",
              "acquisition_text", "url", "is_public_domain", "source_id")
    values = (artist_entity_id, title, date_text, medium, classification, holding_entity_id,
              acquisition_text, url, is_public_domain, source_id)
    old = con.execute("SELECT " + ",".join(fields) + " FROM works WHERE work_id=?", (work_id,)).fetchone()
    if old is None:
        con.execute(
            "INSERT INTO works(work_id,id_namespace,id_value," + ",".join(fields)
            + ",first_seen_at,last_seen_at) VALUES(" + ",".join("?" for _ in range(15)) + ")",
            (work_id, id_namespace, str(id_value), *values, now, now))
        outcome = "inserted"
    elif tuple(old) != values:
        con.execute("UPDATE works SET " + ",".join(field + "=?" for field in fields)
                    + ",last_seen_at=? WHERE work_id=?", (*values, now, work_id))
        outcome = "updated"
    else:
        con.execute("UPDATE works SET last_seen_at=? WHERE work_id=?", (now, work_id))
        outcome = "unchanged"
    stats[outcome] = stats.get(outcome, 0) + 1
    stats["works"] = stats.get("works", 0) + 1
    return work_id


def add_review(con, item_type, ref_table, ref_id, issue, detail=None, suggested_action=None):
    item_id = sid("rvw", item_type, ref_table, ref_id, issue)
    con.execute(
        "INSERT INTO review_queue(item_id,item_type,ref_table,ref_id,issue,detail,suggested_action,status,created_at)"
        " VALUES(?,?,?,?,?,?,?,'open',?) ON CONFLICT(item_id) DO UPDATE SET detail=excluded.detail",
        (item_id, item_type, ref_table, ref_id, issue, detail, suggested_action, iso_now()),
    )


def add_image_rights(con, *, source_id, usage_status, basis, page_url=None, image_url=None, entity_id=None,
                     event_id=None, work_id=None, rights_holder=None, license=None, credit=None) -> str:
    asset_id = sid("img", source_id, image_url or page_url, event_id or work_id or entity_id)
    con.execute(
        "INSERT INTO image_rights(asset_id,source_id,entity_id,event_id,work_id,page_url,image_url,rights_holder,license,credit,"
        " usage_status,basis,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET"
        " usage_status=excluded.usage_status, basis=excluded.basis, checked_at=excluded.checked_at, credit=excluded.credit",
        (asset_id, source_id, entity_id, event_id, work_id, page_url, image_url, rights_holder, license, credit,
         usage_status, basis, iso_now()),
    )
    return asset_id
