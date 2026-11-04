"""Art Institute of Chicago public API (Blueprint D05 / O20).

Official, documented API (https://api.artic.edu/docs/). robots.txt on api.artic.edu is served behind a
Cloudflare 403, so access is governed by the API documentation, which asks clients to send an
AIC-User-Agent header and keep request volume low. Data is CC0 per the API docs; images are only
public-domain when is_public_domain is true.
"""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from ..config import now_kst
from ._common import clean_text, split_title_artist

PARSER_VERSION = "aic-1"
API = "https://api.artic.edu/api/v1"
FIELDS = "id,title,status,aic_start_at,aic_end_at,artist_ids,artwork_ids,gallery_title,web_url,short_description,is_featured,image_id"

SOURCES = [dict(
    source_id="aic_api", blueprint_data_id="D05", blueprint_org_id="O20", name="Art Institute of Chicago API",
    owner_group="Art Institute of Chicago", source_kind="museum", region_scope="AMERICAS", country_codes="US",
    access_method="api", base_url="https://api.artic.edu", entry_url=f"{API}/exhibitions",
    terms_url="https://api.artic.edu/docs/#terms", text_storage_policy="raw_internal", priority="P0",
    api_policy_url="https://api.artic.edu/docs/", extra_headers={"AIC-User-Agent": "ARTREND art magazine research"},
    min_interval=3, max_requests=300,
    st_official_doc="ok(api docs; AIC-User-Agent header requested)", st_collection_terms="ok(CC0 data per API docs)",
    st_image_terms="per-record(is_public_domain flag)",
)]


def collect(ctx):
    since = "2016-01-01" if ctx.mode == "initial" else (now_kst().date() - dt.timedelta(days=400)).isoformat()
    aic = db.ensure_entity(ctx.con, entity_type="institution", name="Art Institute of Chicago", namespace="wikidata",
                           id_value="Q239303", lang="en", source_id=ctx.source_id, official_url="https://www.artic.edu/")
    page, artist_ids = 1, set()
    rows = []
    while True:
        r = ctx.fetch(f"{API}/exhibitions/search", params={
            "query[range][aic_start_at][gte]": since, "sort": "aic_start_at", "limit": 100, "page": page, "fields": FIELDS})
        data = r.json()
        ev = ctx.evidence(r, locator=f"exhibitions/search page={page}")
        ctx.count("fetched", len(data["data"]))
        for x in data["data"]:
            rows.append((x, ev))
            artist_ids.update(x.get("artist_ids") or [])
        if page >= data["pagination"]["total_pages"]:
            break
        page += 1
    agents = {}
    ids = sorted(artist_ids)
    for i in range(0, len(ids), 100):
        r = ctx.fetch(f"{API}/agents", params={"ids": ",".join(map(str, ids[i:i + 100])), "limit": 100,
                                                 "fields": "id,title,birth_date,death_date,is_artist"})
        aev = ctx.evidence(r, locator="agents batch")
        for a in r.json()["data"]:
            agents[a["id"]] = (a, aev)
    stats = ctx.stats
    for x, ev in rows:
        title = clean_text(x["title"])
        start, end = _d(x.get("aic_start_at")), _d(x.get("aic_end_at"))
        status = (x.get("status") or "").lower()
        eid = db.upsert_event(
            ctx.con, stats, source_id=ctx.source_id, source_event_key=str(x["id"]), event_type="exhibition",
            subtype=None, title=title, title_lang="en", organizer_entity_id=aic, city="Chicago", country_code="US",
            start_date=start, start_precision="day" if start else None, end_date=end, end_precision="day" if end else None,
            date_text=f"{x.get('aic_start_at')} / {x.get('aic_end_at')}",
            announced_status="cancelled" if "cancel" in status else ("scheduled" if status == "confirmed" else status or None),
            url=x.get("web_url"), description_excerpt=clean_text(re.sub("<[^>]+>", " ", x.get("short_description") or "")),
            parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        linked = False
        for aid in x.get("artist_ids") or []:
            if aid in agents:
                a, aev = agents[aid]
                ent = db.ensure_entity(ctx.con, entity_type="person", name=a["title"], namespace="aic", id_value=str(aid),
                                       source_id=ctx.source_id, evidence_id=aev,
                                       birth_year=a.get("birth_date"), death_year=a.get("death_date"))
                db.add_participant(ctx.con, eid, ent, "artist", a["title"], ev, "structured_field")
                linked = True
        if not linked:
            name = split_title_artist(title)
            if name:
                ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=f"src:{ctx.source_id}",
                                       source_id=ctx.source_id, evidence_id=ev)
                db.add_participant(ctx.con, eid, ent, "artist", name, ev, "title_pattern", "medium")
        if x.get("image_id"):
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=x.get("web_url"),
                                image_url=f"https://www.artic.edu/iiif/2/{x['image_id']}/full/843,/0/default.jpg",
                                usage_status="unknown", basis="exhibition image; AIC images are reusable only when the "
                                "linked artwork is_public_domain=true; exhibition promo images are not covered")
    ctx.con.commit()


def _d(v):
    return v[:10] if v else None
