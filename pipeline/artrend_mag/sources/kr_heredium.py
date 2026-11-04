"""Heredium (헤레디움, Daejeon) — exhibitions, programmes, notices and press from the museum's own site.

heredium.art is a Nuxt app; its pages load the same public JSON the browser reads (`/api/user/...`):
`common/home` (current and upcoming exhibitions/programmes with thumbnails, latest notices) and `press`.
robots.txt is absent (404 = allow). Stored: titles, dates, page URLs, thumbnail URLs; no notice bodies.
"""
from __future__ import annotations

from .. import db

SITE = "https://heredium.art"
API = SITE + "/api/user"
IMG = "https://kr.object.fin-ncloudstorage.com/heredium-bucket/"
PARSER_VERSION = "heredium-1"

SOURCES = [dict(
    source_id="kr_heredium", blueprint_data_id=None, blueprint_org_id=None, name="헤레디움 — 전시·프로그램·공지·보도",
    owner_group="헤레디움(씨엔씨티마음에너지재단)", source_kind="museum", region_scope="KR", country_codes="KR",
    access_method="api", base_url=SITE, entry_url=API + "/common/home", terms_url=SITE + "/policies",
    text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(site's own public JSON)",
    st_collection_terms="ARTREND's own institution; public JSON used by the site itself; robots.txt absent",
    st_image_terms="own institution's thumbnails, internal preview", max_requests=20,
    notes="work/dev/KRNational (Heredium API discovered from the site's Nuxt bundle)",
)]


def _thumb(t):
    if not t:
        return None
    r = t.get("resizeImage") or {}
    f = r.get("medium") or r.get("large") or t.get("savedFileName")
    return IMG + f if f else None


def collect(ctx):
    home = ctx.fetch(API + "/common/home", accept="application/json")
    data = home.json()
    org = db.ensure_entity(ctx.con, entity_type="institution", name="헤레디움", namespace="src:kr_heredium", lang="ko",
                           source_id=ctx.source_id, official_url=SITE)
    for p in data.get("projects") or []:
        kind = "program" if p.get("kind") == "PROGRAM" else "exhibition"
        url = f"{SITE}/{'program' if kind == 'program' else 'exhibition'}/{p['id']}"
        ev = ctx.evidence(home, locator=f"home project {p['id']}", excerpt=p.get("title"))
        eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"{kind}:{p['id']}", event_type=kind,
                              title=p["title"], title_lang="ko", organizer_entity_id=org, city="Daejeon", country_code="KR",
                              start_date=(p.get("startDate") or "")[:10] or None, start_precision="day",
                              end_date=(p.get("endDate") or "")[:10] or None, end_precision="day", url=url,
                              parser_version=PARSER_VERSION, evidence_id=ev, description_excerpt="venue: 헤레디움 (대전)")
        img = _thumb(p.get("thumbnail"))
        if img:
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=img,
                                usage_status="unknown", basis="Heredium's own thumbnail; internal preview")
        ctx.count("parsed")
    for n in data.get("notices") or []:
        db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=f"{SITE}/community/notice/{n['id']}",
                          title=n["title"], published_at=(n.get("postDate") or "")[:10] or None, publisher="헤레디움",
                          owner_group="헤레디움", article_type="announcement", type_basis="official notice", lang="ko")
        ctx.count("parsed")
    press = ctx.fetch(API + "/press", params=dict(page="0", size="20"), accept="application/json")
    for n in (press.json() or {}).get("content") or []:
        db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=f"{SITE}/community/press/{n['id']}",
                          title=n["title"], published_at=(n.get("postDate") or "")[:10] or None, publisher="헤레디움",
                          owner_group="헤레디움", article_type="announcement", type_basis="official press list", lang="ko")
        ctx.count("parsed")
    ctx.con.commit()
    ctx.note("home projects + notices + press list (public JSON)")
