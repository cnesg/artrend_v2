"""MoMA collection open data (Blueprint D03 / O18) — official CC0 download from GitHub (Git LFS media URL).

Artists.csv gives ConstituentID with Wikidata QID and ULAN IDs (external identifiers, D01/D02 bridge).
Artworks.csv gives ObjectID, title, medium, DateAcquired, CreditLine. DateAcquired is MoMA's accession date;
it is NOT the date the record first appeared online, and the data set does not represent everything on view.
Acquisition events are aggregated per (artist, DateAcquired) and only from 2016 onward.
"""
from __future__ import annotations

import csv
import io

from .. import db
from ._common import clean_text

PARSER_VERSION = "moma-gh-1"
BASE = "https://media.githubusercontent.com/media/MuseumofModernArt/collection/main"
ACQ_FROM = "2016-01-01"

SOURCES = [dict(
    source_id="moma_collection_github", blueprint_data_id="D03,D01,D02", blueprint_org_id="O18",
    name="MoMA Collection open data (GitHub)", owner_group="The Museum of Modern Art", source_kind="museum",
    region_scope="AMERICAS", country_codes="US", access_method="download",
    base_url="https://github.com/MuseumofModernArt/collection", entry_url=f"{BASE}/Artworks.csv",
    terms_url="https://github.com/MuseumofModernArt/collection/blob/main/LICENSE.md", text_storage_policy="raw_internal",
    priority="P0", st_official_doc="ok(README: weekly automatic update, CC0)",
    st_collection_terms="ok(CC0 public domain dedication for the data)",
    st_image_terms="not included(data only; image rights separate)", min_interval=3, max_requests=10,
)]


def collect(ctx):
    con = ctx.con
    moma = db.ensure_entity(con, entity_type="institution", name="The Museum of Modern Art", namespace="wikidata",
                            id_value="Q188740", lang="en", source_id=ctx.source_id, official_url="https://www.moma.org/")
    ra = ctx.fetch(f"{BASE}/Artists.csv")
    ev_a = ctx.evidence(ra, locator="Artists.csv")
    artists = {}
    for row in csv.DictReader(io.StringIO(ra.content.decode("utf-8-sig"))):
        cid = row["ConstituentID"].strip()
        name = clean_text(row["DisplayName"])
        if not cid or not name:
            continue
        ctx.count("fetched")
        by, dy = _int(row.get("BeginDate")), _int(row.get("EndDate"))
        ent = db.ensure_entity(con, entity_type="person" if (row.get("Gender") or by) else "unknown", name=name,
                               namespace="moma", id_value=cid, source_id=ctx.source_id, evidence_id=ev_a,
                               nationality_text=row.get("Nationality") or None, birth_year=by, death_year=dy)
        qid = (row.get("Wiki QID") or "").strip()
        ulan = (row.get("ULAN") or "").strip()
        if qid:
            db.add_alias(con, ent, name, None, "wikidata", qid, ctx.source_id, ev_a)
        if ulan:
            db.add_alias(con, ent, name, None, "ulan", ulan, ctx.source_id, ev_a)
        artists[cid] = ent
    con.commit()
    rw = ctx.fetch(f"{BASE}/Artworks.csv")
    ev_w = ctx.evidence(rw, locator="Artworks.csv")
    stats = ctx.stats
    acq: dict[tuple[str, str], list[str]] = {}
    n = 0
    for row in csv.DictReader(io.StringIO(rw.content.decode("utf-8-sig"))):
        oid = row["ObjectID"].strip()
        if not oid:
            continue
        cids = [c.strip() for c in (row.get("ConstituentID") or "").split(",") if c.strip()]
        artist_ent = artists.get(cids[0]) if cids else None
        db.upsert_work(con, stats, id_namespace="moma", id_value=oid, source_id=ctx.source_id,
                       artist_entity_id=artist_ent, title=clean_text(row.get("Title")) or None,
                       date_text=row.get("Date") or None, medium=clean_text(row.get("Medium")) or None,
                       classification=row.get("Classification") or None, holding_entity_id=moma,
                       acquisition_text=f"{row.get('DateAcquired') or ''} | {row.get('CreditLine') or ''}".strip(" |") or None,
                       url=row.get("URL") or None)
        d = (row.get("DateAcquired") or "").strip()
        if d >= ACQ_FROM and len(d) == 10:
            for c in cids:
                if c in artists:
                    acq.setdefault((c, d), []).append(oid)
        n += 1
        if n % 20000 == 0:
            con.commit()
    ctx.note(f"artworks rows={n}; acquisition groups since {ACQ_FROM}={len(acq)}")
    for (cid, d), oids in acq.items():
        ent = artists[cid]
        name = con.execute("SELECT canonical_name FROM entities WHERE entity_id=?", (ent,)).fetchone()[0]
        eid = db.upsert_event(con, stats, source_id=ctx.source_id, source_event_key=f"acq:{cid}:{d}", event_type="acquisition",
                              subtype=None, title=f"MoMA accession: {name} ({len(oids)} work{'s' if len(oids) > 1 else ''})",
                              title_lang="en", organizer_entity_id=moma, city="New York", country_code="US",
                              start_date=d, start_precision="day", date_text=f"DateAcquired={d}",
                              url=f"https://www.moma.org/artists/{cid}", parser_version=PARSER_VERSION, evidence_id=ev_w,
                              description_excerpt=f"ObjectIDs: {', '.join(oids[:12])}{' …' if len(oids) > 12 else ''}")
        db.add_participant(con, eid, ent, "artist", name, ev_w, "structured_field")
        ctx.count("parsed")
    con.commit()


def _int(v):
    try:
        v = int(str(v).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
