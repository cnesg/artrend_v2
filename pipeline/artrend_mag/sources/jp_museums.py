"""Japanese museums / public art centres: Mori Art Museum, MOT, TOKAS, Kanazawa 21st Century Museum, NACT.

All sources are public HTML listing pages (no API). Raw HTML is kept internally as evidence only.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from .. import db
from ..config import now_kst
from ._common import classify_subtype, clean_text, soup, split_title_artist

PARSER_VERSION = "jp_museums-1"

_MAM_TERMS = ("Roppongi Hills Museum/Observatory terms: all content copyright Mori Building or right holders; "
              "reproduction/transmission beyond private use under the Copyright Act prohibited without written consent")

SOURCES = [
    dict(source_id="mam_exhibitions", blueprint_data_id="D10", blueprint_org_id="O10", name="Mori Art Museum — Exhibitions",
         owner_group="Mori Building", source_kind="museum", region_scope="JP", country_codes="JP",
         access_method="html", base_url="https://www.mori.art.museum", entry_url="https://www.mori.art.museum/en/exhibitions/",
         terms_url="https://art-view.roppongihills.com/en/conditions/", text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(html)", st_collection_terms=_MAM_TERMS + "; no clause on automated access",
         st_image_terms="images copyright Mori Building/right holders; no reuse beyond private use", max_requests=150),
    dict(source_id="mot_exhibitions", blueprint_data_id=None, blueprint_org_id="O12",
         name="Museum of Contemporary Art Tokyo (MOT) — Exhibitions", owner_group="Tokyo Metropolitan Foundation for History and Culture",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="json",
         base_url="https://www.mot-art-museum.jp", entry_url="https://www.mot-art-museum.jp/en/json/exhibitions/exhibitions.json",
         terms_url="https://www.mot-art-museum.jp/en/privacy/", text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(static JSON file loaded by the public exhibitions page; no key)",
         st_collection_terms="terms page not located (site links only a Privacy Policy, which says nothing on reuse/automated access)",
         st_image_terms="no image licence stated; treat as all rights reserved", max_requests=20),
    dict(source_id="kanazawa21", blueprint_data_id=None, blueprint_org_id=None,
         name="21st Century Museum of Contemporary Art, Kanazawa — Exhibitions", owner_group="Kanazawa Art Promotion and Development Foundation",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.kanazawa21.jp", entry_url="https://www.kanazawa21.jp/en/exhibition/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located", st_image_terms="no image licence stated; all rights reserved by default",
         max_requests=20),
    dict(source_id="nact_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="The National Art Center, Tokyo — Special Exhibitions", owner_group="Independent Administrative Institution National Museum of Art",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.nact.jp", entry_url="https://www.nact.jp/english/exhibition_special/", terms_url=None,
         text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located", st_image_terms="no image licence stated; credits per image (e.g. GrandPalaisRmn)",
         max_requests=10),
]


# --------------------------------------------------------------------------------------------- helpers
def _known(ctx, key):
    """(exists, end_date) of an already stored event for this source."""
    r = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                        (ctx.source_id, key)).fetchone()
    return (r is not None), (r[0] if r is not None else None)


def _needs_detail(ctx, key):
    """initial: always; incremental: unseen keys or events ending within the last 30 days / later / undated."""
    if ctx.mode == "initial":
        return True
    seen, end = _known(ctx, key)
    if not seen:
        return True
    cutoff = (now_kst().date() - dt.timedelta(days=30)).isoformat()
    return end is None or end[:10] >= cutoff


_DOT = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\s*\[[^\]]*\]|\s*\([^)]*\))?\s*[-–~〜−－—]\s*"
                  r"(?:(\d{4})\.)?(\d{1,2})\.(\d{1,2})")
_DOT1 = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")


def _dotted_range(text):
    """'2026.10.31 [Sat] - 2027.3.28 [Sun]' / '2027.4.29 [Thu] - 9.23 [Thu]' -> (start, end) ISO days.
    The end year, when omitted, is the start year (the page states the year once)."""
    m = _DOT.search(text or "")
    if m:
        y1, m1, d1, y2, m2, d2 = m.groups()
        s = _mk(y1, m1, d1)
        e = _mk(y2 or y1, m2, d2)
        return s, e
    m = _DOT1.search(text or "")
    if m:
        return _mk(*m.groups()), None
    return None, None


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return None


_NOUNISH = re.compile(r"(tion|sion|ism|ity|ness|ment|ies|ics)$", re.I)


def _artist_from_title(title):
    """split_title_artist plus: '―'/'—' as separator, and reject prefixes made of abstract nouns
    ('Synchronic Constellation: ...')."""
    dash = bool(re.search(r"[―—]", title or "")) and not re.search(r"[:：]", title or "")
    t = re.sub(r"\s*[―—]\s*", ": ", title or "", count=1)
    name = split_title_artist(t)
    if not name or any(_NOUNISH.search(w) or (len(w) >= 7 and w.lower().endswith("ing")) for w in name.split()):
        return None
    if (name.isupper() and " " in name) or re.search(r"[\[\]【】]", name) or (dash and len(name.split()) < 2):
        return None
    return name


def _person(ctx, name, ev, eid, method="title_pattern", conf="medium", role="artist"):
    name = clean_text(name)
    if not name:
        return
    etype = "group" if re.search(r"\b(collective|group|studio|lab|team)\b", name, re.I) else "person"
    ent = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"src:{ctx.source_id}",
                           source_id=ctx.source_id, evidence_id=ev)
    db.add_participant(ctx.con, eid, ent, role, name, ev, method, conf)


def collect(ctx):
    if ctx.source_id == "mam_exhibitions":
        return _mam(ctx)
    if ctx.source_id == "mot_exhibitions":
        return _mot(ctx)
    if ctx.source_id == "kanazawa21":
        return _k21(ctx)
    if ctx.source_id == "nact_exhibitions":
        return _nact(ctx)
    raise ValueError(ctx.source_id)


# --------------------------------------------------------------------------------------------- Mori Art Museum
_MAM_CAT = {"exhibitions-category_project": ("MAM Project", "project"), "exhibitions-category_screen": ("MAM Screen", "project"),
            "exhibitions-category_research": ("MAM Research", "project"),
            "exhibitions-category_collection": ("MAM Collection", "collection_display")}


def _split_names(s):
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", s)
    return [clean_text(p) for p in parts if clean_text(p)]


def _mam_subject_names(subj):
    """'Brie Ruais' -> [..]; 'Viewpoint - A, B, C' -> [A, B, C]; 'Nancy Holt and Robert Smithson' -> 2 names.
    Thematic subjects (digits, parentheses, a dash without a following name list) give []."""
    if " - " in subj:
        tail = subj.split(" - ", 1)[1]
        if not re.search(r",|\band\b", tail):
            return []
        subj = tail
    if re.search(r"[\d()]", subj):
        return []
    if re.search(r"\b(collective|group|studio)\b", subj, re.I):
        return [subj]
    return _split_names(subj)


def _mam(ctx):
    con = ctx.con
    org = db.ensure_entity(con, entity_type="institution", name="Mori Art Museum", namespace=f"src:{ctx.source_id}",
                           id_value="mori_art_museum", lang="en", source_id=ctx.source_id,
                           official_url="https://www.mori.art.museum/en/")
    listings = ["https://www.mori.art.museum/en/exhibitions/", "https://www.mori.art.museum/en/exhibitions/past/"]
    items = {}
    for lu in listings:
        r = ctx.fetch(lu)
        s = soup(r.text)
        for a in s.select(".exhibitionsList a[href]"):
            url = urllib.parse.urljoin(r.final_url, a["href"])
            m = re.search(r"/en/exhibitions/([^/]+)/", url)
            if not m or m.group(1) in ("past", "tours"):
                continue
            key = m.group(1)
            if key in items:
                continue
            h = a.select_one("h2")
            cat_span = h.select_one(".exhibitions-category") if h else None
            series = clean_text(cat_span.get_text(" ")).rstrip(": ") if cat_span else None
            title = clean_text(h.get_text(" ")) if h else ""
            title = re.sub(r"\s+:", ":", title)
            subj = None
            if cat_span is not None:
                cat_span.extract()
                subj = clean_text(h.get_text(" "))
            cat = None
            pc = a.select_one("p.category-name")
            if pc:
                for c in pc.get("class", []):
                    if c in _MAM_CAT:
                        cat = c
            d = a.select_one(".exhibitions-date")
            img = a.select_one("img")
            img_url = None
            if img is not None:
                src = img.get("data-pcimg") or img.get("src")
                if src and "_blank" not in src:
                    img_url = urllib.parse.urljoin(r.final_url, src)
            items[key] = dict(url=url, title=title, series=series, subj=subj, cat=cat,
                              date_text=clean_text(d.get_text(" ")) if d else None, resp=r, img=img_url)
        ctx.count("fetched", len(s.select(".exhibitionsList a[href]")))
    ctx.note("MAM: current/upcoming listing + past 'All' listing (shows 2022 onward; per-year archive back to 2003 "
             "not crawled); sub-programme (MAM Project/Screen/Collection/Research) dates read from detail pages")
    for key, it in items.items():
        resp, locator, date_text = it["resp"], f"listing a[href*={key}]", it["date_text"]
        if not date_text:
            if not _needs_detail(ctx, key):
                continue
            try:
                resp = ctx.fetch(it["url"])
            except Exception as e:  # FetchError on one detail page
                from ..http import Blocked
                if isinstance(e, Blocked):
                    raise
                ctx.note(f"detail error {it['url']}: {e}")
                ctx.count("detail_errors")
                continue
            ds = soup(resp.text)
            d = ds.select_one(".mainVisual-text_date")
            date_text = clean_text(d.get_text(" ")) if d else None
            locator = ".mainVisual-text_date"
        start, end = _dotted_range(date_text)
        ev = ctx.evidence(resp, locator=locator, excerpt=date_text)
        cat_label, subtype = _MAM_CAT.get(it["cat"], (None, None))
        artists, method = [], "title_pattern"
        if it["cat"] in ("exhibitions-category_project", "exhibitions-category_screen",
                         "exhibitions-category_collection") and it["subj"]:
            artists = _mam_subject_names(it["subj"])
        elif it["cat"] is None:
            m = re.search(r"(?:Prize|Award) Exhibition:\s*(.+)$", it["title"])
            a = m.group(1) if m else _artist_from_title(it["title"])
            if a:
                artists = [a]
        if subtype is None:
            subtype = classify_subtype(it["title"], len(artists) or None)
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition", subtype=subtype,
            title=it["title"], title_lang="en", organizer_entity_id=org, city="Tokyo", country_code="JP",
            start_date=start, start_precision="day" if start else None, end_date=end, end_precision="day" if end else None,
            date_text=date_text, url=it["url"], description_excerpt=cat_label, parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        for a in artists:
            _person(ctx, a, ev, eid, method, "medium")
        if it["img"]:
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=it["url"], image_url=it["img"],
                                usage_status="unknown", basis=_MAM_TERMS)
    ctx.con.commit()


# --------------------------------------------------------------------------------------------- MOT
def _html_title(s):
    s = re.sub(r"<br\s*/?>", " / ", s or "", flags=re.I)
    return clean_text(re.sub(r"<[^>]+>", "", s)).strip(" /")


def _ymd(v):
    v = (v or "").strip()
    return _mk(v[:4], v[4:6], v[6:8]) if re.fullmatch(r"\d{8}", v) else None


def _mot(ctx):
    base = "https://www.mot-art-museum.jp"
    org = db.ensure_entity(ctx.con, entity_type="institution", name="Museum of Contemporary Art Tokyo",
                           namespace=f"src:{ctx.source_id}", id_value="mot", lang="en", source_id=ctx.source_id,
                           official_url=f"{base}/en/")
    r = ctx.fetch(ctx.meta["entry_url"], accept="application/json")
    data = r.json()
    ctx.count("fetched", len(data))
    starts = sorted(x.get("start") or "" for x in data if x.get("start"))
    ctx.note(f"MOT: exhibitions.json (used by the public /en/exhibitions/ page) lists {len(data)} exhibitions, "
             f"{starts[0] if starts else '?'}..{starts[-1] if starts else '?'}; full history stored")
    for x in data:
        if not x.get("permalink") or not x.get("title"):
            continue
        title = _html_title(x["title"])
        crown = _html_title(x.get("crownName"))
        sub = _html_title(x.get("subTitle"))
        start, end = _ymd(x.get("start")), _ymd(x.get("end"))
        date_text = clean_text(x.get("anotherDate")) or f"{x.get('start')}-{x.get('end')}"
        url = urllib.parse.urljoin(base, x["permalink"])
        key = str(x.get("id") or x["permalink"])
        ev = ctx.evidence(r, locator=f"$[id={x.get('id')}]", excerpt=date_text)
        is_coll = x.get("type") == "collections" or bool(x.get("collectionsDisplay"))
        etype = "program" if re.search(r"art book fair", title, re.I) else "exhibition"
        artist = None if is_coll or etype != "exhibition" else _artist_from_title(title)
        subtype = None
        if etype == "exhibition":
            subtype = "collection_display" if is_coll else classify_subtype(title, 1 if artist else None)
            if crown and re.search(r"MOT Plus", crown) and subtype == "unknown":
                subtype = "project"
        excerpt = " | ".join(p for p in (crown, sub) if p) or None
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type=etype, subtype=subtype,
            title=title, title_lang="en", organizer_entity_id=org, city="Tokyo", country_code="JP",
            start_date=start, start_precision="day" if start else None, end_date=end, end_precision="day" if end else None,
            date_text=date_text, url=url, description_excerpt=excerpt, parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        if artist:
            _person(ctx, artist, ev, eid)
        img = x.get("imagePc")
        if img and "no_image" not in img:
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url,
                                image_url=urllib.parse.urljoin(base, img), usage_status="unknown",
                                basis="MOT site states no image licence; all rights reserved by default")
    ctx.con.commit()


# --------------------------------------------------------------------------------------------- Kanazawa 21
K21 = "https://www.kanazawa21.jp"


def _k21(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="21st Century Museum of Contemporary Art, Kanazawa",
                           namespace=f"src:{ctx.source_id}", id_value="kanazawa21", lang="en", source_id=ctx.source_id,
                           official_url=f"{K21}/en/")
    year = now_kst().year
    urls = [f"{K21}/en/exhibition/"]
    for y in (range(year, 2022, -1) if ctx.mode == "initial" else [year]):
        urls.append(f"{K21}/data_list.php?g=89&sn[]=day_from&st[]=4&sc[]={y},99,99,99,99&sn[]=day_to&st[]=5&sc[]={y}")
    seen = set()
    for u in urls:
        r = ctx.fetch(u)
        panels = soup(r.text).select("a.panel__link[href]")
        ctx.count("fetched", len(panels))
        for a in panels:
            m = re.search(r"[?&]d=(\d+)", a["href"])
            if not m or m.group(1) in seen:
                continue
            key = m.group(1)
            seen.add(key)
            t = a.select_one(".panel__ttl")
            title = clean_text(t.get_text(" ")) if t else ""
            st = a.select_one(".panel__subttl")
            series = clean_text(st.get_text(" ")) if st else None
            d = a.select_one(".panel__date")
            date_text = clean_text(d.get_text(" ")) if d else None
            start, end = _dotted_range(date_text)
            labels = [clean_text(x.get_text(" ")) for x in a.select(".panel__label .label")]
            url = urllib.parse.urljoin(r.final_url, a["href"])
            name = _artist_from_title(title)
            artists = [] if not name else ([name] if re.search(r"collective|group", name, re.I) else _split_names(name))
            ev = ctx.evidence(r, locator=f"a.panel__link[href*='d={key}'] .panel__date", excerpt=date_text)
            eid = db.upsert_event(
                ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
                subtype=classify_subtype(title, len(artists) or None), title=title, title_lang="en",
                organizer_entity_id=org, city="Kanazawa", country_code="JP", start_date=start,
                start_precision="day" if start else None, end_date=end, end_precision="day" if end else None,
                date_text=date_text, announced_status="cancelled" if re.search(r"Cancel", title, re.I) else None,
                url=url, description_excerpt=" | ".join(x for x in [series] + labels[1:] if x) or None,
                parser_version=PARSER_VERSION, evidence_id=ev)
            ctx.count("parsed")
            for n in artists:
                _person(ctx, n, ev, eid)
            img = a.select_one(".panel__img img[src]")
            if img is not None:
                db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=img["src"],
                                    usage_status="unknown", basis="no image licence on site; all rights reserved by default")
        ctx.con.commit()
    ctx.note("Kanazawa 21: /en/exhibition/ (current/upcoming) + per-year 'Past Exhibition' query pages "
             "(2023..current in initial; current year in incremental)")


# --------------------------------------------------------------------------------------------- NACT
NACT = "https://www.nact.jp"


def _nact(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="The National Art Center, Tokyo",
                           namespace=f"src:{ctx.source_id}", id_value="nact", lang="en", source_id=ctx.source_id,
                           official_url=f"{NACT}/english/")
    from .jp_galleries import _any_range
    r = ctx.fetch(f"{NACT}/english/exhibition_special/")
    items = soup(r.text).select("ul.exhi > li > a[href]")
    ctx.count("fetched", len(items))
    for a in items:
        url = urllib.parse.urljoin(r.final_url, a["href"])
        m = re.search(r"/exhibition_special/(\d{4}/[^/]+)/", url)
        key = m.group(1) if m else url
        h = a.select_one("h2")
        title = clean_text(h.get_text(" ")) if h else key
        d = a.select_one(".ex_date")
        date_text = clean_text(d.get_text(" ")) if d else None
        start, sp, end, ep = _any_range(date_text)
        cats = [clean_text(x.get_text(" ")) for x in a.select(".ex_cate li")]
        name = _artist_from_title(title)
        ev = ctx.evidence(r, locator=f"ul.exhi a[href='{a['href']}'] .ex_date", excerpt=date_text)
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
            subtype=classify_subtype(title, 1 if name else None), title=title, title_lang="en", organizer_entity_id=org,
            city="Tokyo", country_code="JP", start_date=start, start_precision=sp, end_date=end, end_precision=ep,
            date_text=date_text, url=url, description_excerpt=" | ".join(cats[1:]) or None,
            parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        if name:
            _person(ctx, name, ev, eid)
        img = a.select_one("img[src]")
        if img is not None:
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url,
                                image_url=urllib.parse.urljoin(r.final_url, img["src"]), usage_status="unknown",
                                basis="no image licence on site; all rights reserved by default")
    ctx.con.commit()
    ctx.note("NACT: English special-exhibitions listing exposes current+upcoming only in HTML (past filter is "
             "client-side JS); no archive collected")
