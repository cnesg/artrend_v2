"""Korean commercial galleries: exhibition programs + artist rosters (Blueprint D-gallery rows, O04-O07).

Each gallery has its own small parser; `collect` branches on ctx.source_id. Rosters are stored as
`listed_artist` (none of these roster pages uses the words represent/전속 on the list itself).
"""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import classify_subtype, clean_text, parse_date_range, soup

PARSER_VERSION = "kr_galleries-2"
FLOOR = "2025-01-01"   # initial-mode history target (contract asks >= 2025-04-01)

KUKJE = "https://www.kukjegallery.com"
ARARIO = "https://www.arariogallery.com"
PKM = "https://www.pkmgallery.com"
GH = "https://www.galleryhyundai.com"

SOURCES = [
    dict(source_id="kukje_gallery", blueprint_data_id=None, blueprint_org_id="O04", name="Kukje Gallery — Exhibitions & Artists",
         owner_group="Kukje Gallery", source_kind="gallery", region_scope="KR", country_codes="KR",
         access_method="html", base_url=KUKJE, entry_url=f"{KUKJE}/exhibitions", terms_url=None,
         text_storage_policy="raw_internal", priority="P0", max_requests=200,
         st_official_doc="n/a(html)", st_collection_terms="terms page not located (footer: '© KUKJE GALLERY. All Rights Reserved.'; robots.txt Allow: /)",
         st_image_terms="© KUKJE GALLERY. All Rights Reserved. (no open licence)"),
    dict(source_id="arario_gallery", blueprint_data_id=None, blueprint_org_id="O06", name="Arario Gallery — Exhibitions & Artists",
         owner_group="Arario Gallery", source_kind="gallery", region_scope="KR", country_codes="KR,CN",
         access_method="html", base_url=ARARIO, entry_url=f"{ARARIO}/exhibitions/", terms_url=None,
         text_storage_policy="raw_internal", priority="P0", max_requests=150,
         st_official_doc="n/a(html, Artlogic CMS)",
         st_collection_terms="terms page not located; robots.txt (Artlogic) disallows /admin/ /embed/ /get/ /api/ /media/ + injection patterns, allows the rest",
         st_image_terms="image captions read 'courtesy of Arario Gallery'; no open licence"),
    dict(source_id="pkm_gallery", blueprint_data_id=None, blueprint_org_id="O07", name="PKM Gallery — Exhibitions",
         owner_group="PKM Gallery", source_kind="gallery", region_scope="KR", country_codes="KR",
         access_method="html", base_url=PKM, entry_url=f"{PKM}/exhibitions", terms_url=None,
         text_storage_policy="raw_internal", priority="P0", max_requests=20,
         st_official_doc="n/a(html, Artlogic/Exhibit-E CMS)",
         st_collection_terms="terms page not located (/about-us and /artists intermittently return a bot-challenge page to our UA; not bypassed)",
         st_image_terms="no licence stated; treat as all rights reserved"),
    dict(source_id="gallery_hyundai", blueprint_data_id=None, blueprint_org_id="O05", name="Gallery Hyundai — Exhibitions & Artists",
         owner_group="Gallery Hyundai", source_kind="gallery", region_scope="KR", country_codes="KR",
         access_method="html+jsonld", base_url=GH, entry_url=f"{GH}/exhibition/onview", terms_url=None,
         text_storage_policy="raw_internal", priority="P0", max_requests=120,
         st_official_doc="n/a(html; schema.org ExhibitionEvent JSON-LD on detail pages; public sitemap.xml)",
         st_collection_terms="terms page not located; robots.txt allows / except /search, /download/, /inc/ and publishes sitemap.xml",
         st_image_terms="no licence stated; treat as all rights reserved"),
]


def collect(ctx):
    if ctx.source_id == "kukje_gallery":
        return _kukje(ctx)
    if ctx.source_id == "arario_gallery":
        return _arario(ctx)
    if ctx.source_id == "pkm_gallery":
        return _pkm(ctx)
    if ctx.source_id == "gallery_hyundai":
        return _gh(ctx)
    raise ValueError(ctx.source_id)


# -- shared helpers ------------------------------------------------------------------------------
def _today():
    return now_kst().date()


def _seen_end(ctx, key):
    """None if the key is unseen; else the stored end_date ('' when unknown)."""
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
    return None if row is None else (row[0] or "")


def _needs_detail(ctx, key):
    if ctx.mode == "initial":
        return True
    end = _seen_end(ctx, key)
    return end is None or end == "" or end >= (_today() - dt.timedelta(days=30)).isoformat()


def _org(ctx, name, gid, url, etype="gallery"):
    eid = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"src:{ctx.source_id}", id_value=gid,
                           lang="en", source_id=ctx.source_id, official_url=url)
    ctx.con.commit()  # several collectors may share one scratch DB; never hold the write lock across fetches
    return eid


def _store(ctx, org, *, key, title, date_text, url, ev, city, cc, artists, lang="en", img=None, img_basis=None,
           subtype=None, desc=None, title_lang=None):
    """artists: list of (name, namespace, id_value|None, extraction_method, confidence)."""
    con = ctx.con
    start, sp, end, ep = parse_date_range(date_text) if date_text else (None, None, None, None)
    st = subtype or classify_subtype(title, len(artists) or None)
    eid = db.upsert_event(con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
                          subtype=st, title=title, title_lang=title_lang or lang, organizer_entity_id=org, city=city,
                          country_code=cc, start_date=start, start_precision=sp, end_date=end, end_precision=ep,
                          date_text=date_text, url=url, parser_version=PARSER_VERSION, evidence_id=ev,
                          description_excerpt=desc)
    ctx.count("parsed")
    if cc is None:
        db.add_review(con, "region", "events", eid, "venue country unknown", detail=city)
    for name, ns, idv, method, conf in artists:
        ent = db.ensure_entity(con, entity_type="person", name=name, namespace=ns, id_value=idv, source_id=ctx.source_id,
                               evidence_id=ev)
        db.add_participant(con, eid, ent, "artist", name, ev, method, conf)
    if img:
        db.add_image_rights(con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=img,
                            usage_status="unknown", basis=img_basis or "no open licence stated")
    return eid, start


def _lines(el):
    if el is None:
        return []
    return [clean_text(x) for x in el.get_text("\n").split("\n") if clean_text(x)]


# -- Kukje ---------------------------------------------------------------------------------------
KUKJE_BRANCH = {"seoul": ("Seoul", "KR"), "busan": ("Busan", "KR")}


def _kukje(ctx):
    con = ctx.con
    org = _org(ctx, "Kukje Gallery", "kukje", KUKJE)
    seqs = set()
    for path in ("/exhibitions", "/exhibitions/upcoming", "/exhibitions/past"):
        r = ctx.fetch(KUKJE + path)
        found = {int(m) for m in re.findall(r'/exhibitions/view\?seq=(\d+)', r.text)}
        ctx.count("fetched", len(found))
        seqs |= found
    ctx.note("Kukje listings expose current/upcoming + the 10 latest past shows (year filter is client-side); "
             "initial mode walks /exhibitions/view?seq=N downward from the newest seq")
    todo = sorted(seqs, reverse=True)
    if ctx.mode == "initial" and seqs:
        todo = list(range(max(seqs), 0, -1))
    old_streak = 0
    for seq in todo:
        key = str(seq)
        if not _needs_detail(ctx, key):
            continue
        try:
            r = ctx.fetch(f"{KUKJE}/exhibitions/view", params={"seq": seq})
        except FetchError as e:
            ctx.count("detail_errors")
            ctx.note(f"seq {seq}: {e}")
            old_streak += 1 if seq not in seqs else 0
            continue
        start = _kukje_detail(ctx, org, seq, r)
        if ctx.mode == "initial" and seq not in seqs:
            old_streak = old_streak + 1 if (start is None or start < FLOOR) else 0
            if old_streak >= 6:
                ctx.note(f"Kukje seq walk stopped at seq={seq} (6 consecutive pages before {FLOOR} or empty)")
                break
        con.commit()
    _kukje_roster(ctx, org)
    con.commit()


def _kukje_detail(ctx, org, seq, r):
    s = soup(r.text)
    head = s.select_one("header.page-main-list__text-container") or s.select_one(".page-main-list__text-container")
    if head is None:
        ctx.count("detail_errors")
        return None
    t = head.select_one(".page-main-list-artist__exhibition")
    tl = _lines(t)
    title = tl[0] if tl else ""
    tm = head.select_one(".page-main-list-time")
    date_text = clean_text(tm.get_text(" ")) if tm else None
    area = head.select_one(".page-main-list-area__title")
    area_txt = clean_text(area.get_text(" ")).replace("\xa0", " ").strip() if area else ""
    area_txt = re.sub(r"\s+", " ", area_txt)
    city, cc = KUKJE_BRANCH.get((area_txt.split(" ")[0] if area_txt else "").lower(), (None, None))
    if not title:
        return None
    artists = []
    for a in head.select(".page-main-list-artist__name-text"):
        links = a.find_all("a", href=re.compile(r"/artists/view\?seq=\d+"))
        for link in links:
            name = clean_text(link.get_text(" "))
            if name:
                artists.append((name, "kukje_artist", re.search(r"seq=(\d+)", link["href"]).group(1), "structured_field", "high"))
        if not links:
            for name in re.split(r"\s*,\s*", clean_text(a.get_text(" "))):
                if name:
                    artists.append((name, f"src:{ctx.source_id}", None, "list_markup", "medium"))
    url = f"{KUKJE}/exhibitions/view?seq={seq}"
    ev = ctx.evidence(r, locator=f"exhibition seq={seq}", excerpt=date_text)
    img = s.select_one(".page-main-list-figure__image[src], img[src*='/upload/exhibitions/']")
    _, start = _store(ctx, org, key=str(seq), title=title, date_text=date_text, url=url, ev=ev, city=city, cc=cc,
                      artists=artists, img=(KUKJE + img["src"]) if img and img["src"].startswith("/") else None,
                      img_basis="© KUKJE GALLERY. All Rights Reserved.",
                      desc=(f"location: {area_txt}; ko title: {tl[1]}" if len(tl) > 1 else (f"location: {area_txt}" if area_txt else None)))
    return start


def _kukje_roster(ctx, org):
    r = ctx.fetch(f"{KUKJE}/artists")
    ev = ctx.evidence(r, locator="artists roster")
    n = 0
    for a in soup(r.text).select("a.artists-main-list__button[href*='seq=']"):
        nm = a.select_one(".artists-main-list__name")
        if nm is None:
            continue
        hidden = nm.find("span")
        ko = clean_text(hidden.get_text(" ")) if hidden else None
        if hidden:
            hidden.extract()
        name = clean_text(nm.get_text(" "))
        seq = re.search(r"seq=(\d+)", a["href"]).group(1)
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace="kukje_artist", id_value=seq, lang="en",
                               source_id=ctx.source_id, evidence_id=ev, official_url=f"{KUKJE}/artists/view?seq={seq}")
        if ko:
            db.add_alias(ctx.con, ent, ko, "ko", "name", "", ctx.source_id, ev)
        db.upsert_relationship(ctx.con, subject_entity_id=ent, object_entity_id=org, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=ev)
        n += 1
    ctx.count("roster_artists", n)


# -- Artlogic-CMS galleries (Arario) --------------------------------------------------------------
ARARIO_BRANCH = {"seoul": ("Seoul", "KR"), "cheonan": ("Cheonan", "KR"), "shanghai": ("Shanghai", "CN")}
ARTLOGIC_SUBTYPE = {"solo exhibition": "solo", "group exhibition": "group", "duo exhibition": "two_person",
                    "arario collection": "collection_display"}


def _artlogic_listing(html, base):
    out = {}
    for a in soup(html).select("div.records_list li > a[href*='/exhibitions/']"):
        m = re.search(r"/exhibitions/(\d+)-", a["href"])
        h2 = a.select_one(".content h2")
        if not m or h2 is None:
            continue
        def t(sel):
            el = a.select_one(sel)
            return clean_text(el.get_text(" ")) if el else None
        out.setdefault(m.group(1), dict(id=m.group(1), url=base + a["href"], title=clean_text(h2.get_text(" ")),
                                        subtitle=t(".subtitle"), date=t(".date"), location=t(".location")))
    return list(out.values())


def _artlogic_related_artists(html):
    out = []
    sec = soup(html).select_one("section#related_artists")
    if sec is None:
        return out
    for a in sec.select("a[href*='/artists/']"):
        m = re.search(r"/artists/(\d+)-", a["href"])
        h2 = a.select_one("h2")
        if m and h2:
            out.append((clean_text(h2.get_text(" ")), m.group(1)))
    return out


def _arario(ctx):
    org = _org(ctx, "Arario Gallery", "arario", ARARIO)
    r = ctx.fetch(f"{ARARIO}/exhibitions/")
    items = _artlogic_listing(r.text, ARARIO)
    ctx.count("fetched", len(items))
    lev = ctx.evidence(r, locator="exhibitions listing")
    years = sorted({(parse_date_range(i["date"])[0] or "")[:4] for i in items if i["date"]} - {""})
    ctx.note(f"Arario /exhibitions/ lists all shows {years[0] if years else '?'}-{years[-1] if years else '?'} on one page "
             "(older in /exhibitions/archive/, not crawled)")
    for it in items:
        start = parse_date_range(it["date"])[0] if it["date"] else None
        if start and start < "2023-01-01":
            continue  # same window in both modes (listing goes back to 2020; older shows are not collected)
        if ctx.mode == "incremental" and _seen_end(ctx, it["id"]) is not None and not _needs_detail(ctx, it["id"]):
            continue
        city, cc = ARARIO_BRANCH.get((it["location"] or "").lower(), (None, None))
        sub = ARTLOGIC_SUBTYPE.get((it["subtitle"] or "").lower())
        ev, related = lev, []
        url = it["url"]
        if start is None or start >= FLOOR:
            try:
                dr = ctx.fetch(url)
                ev = ctx.evidence(dr, locator=f"exhibition {it['id']}", excerpt=it["date"])
                related = _artlogic_related_artists(dr.text)
            except FetchError as e:
                ctx.count("detail_errors")
                ctx.note(f"{url}: {e}")
        artists = [(n, "arario_artist", aid, "list_markup", "high" if sub == "solo" else "medium") for n, aid in related]
        if not artists and sub == "solo":
            from ._common import split_title_artist
            n = split_title_artist(it["title"])
            if n:
                artists = [(n, f"src:{ctx.source_id}", None, "title_pattern", "medium")]
        _store(ctx, org, key=it["id"], title=it["title"], date_text=it["date"], url=url, ev=ev, city=city, cc=cc,
               artists=artists, subtype=sub, desc=f"{it['subtitle'] or ''} | {it['location'] or ''}".strip(" |") or None)
        ctx.con.commit()
    _artlogic_roster(ctx, org, f"{ARARIO}/artists/", "arario_artist", ARARIO)


def _artlogic_roster(ctx, org, url, ns, base):
    r = ctx.fetch(url)
    ev = ctx.evidence(r, locator="artists roster")
    seen = set()
    for a in soup(r.text).select("a[href*='/artists/']"):
        m = re.search(r"^/artists/(\d+)-", a["href"])
        h2 = a.select_one("h2")
        if not m or h2 is None or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        name = clean_text(h2.get_text(" "))
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=ns, id_value=m.group(1),
                               source_id=ctx.source_id, evidence_id=ev, official_url=base + a["href"])
        db.upsert_relationship(ctx.con, subject_entity_id=ent, object_entity_id=org, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=ev)
    ctx.count("roster_artists", len(seen))
    ctx.con.commit()


# -- PKM -------------------------------------------------------------------------------------------
PKM_SPACES = {"pkm-gallery": ("PKM Gallery", "Seoul", "KR"),
              "p-k-m-gallery-bartleby-bickle-meursault": ("P K M Gallery | Bartleby Bickle & Meursault", "Seoul", "KR")}
# /exhibitions/past/p-k-m-gallery-temporary-exhibition-space answered with a bot-challenge page on 2026-10-27
# (twice); it is no longer requested. Shows only listed there keep venue/country unknown (review queue).


def _pkm_cards(html):
    out = []
    for a in soup(html).select("a[href^='/exhibitions/']"):
        t, d, st = a.select_one(".title"), a.select_one(".date"), a.select_one(".subtitle")
        if not (t and d) or a["href"].startswith("/exhibitions/past"):
            continue
        out.append(dict(slug=a["href"].rsplit("/", 1)[-1], head=clean_text(t.get_text(" ")),
                        sub=clean_text(st.get_text(" ")) if st else "", date=clean_text(d.get_text(" "))))
    return out


def _pkm(ctx):
    """One listing page holds the full archive (2001-). The per-space archive pages map each show to a PKM space
    (all three spaces are in Seoul per the site footer/space names). Detail and roster pages are not fetched:
    /artists and some space pages intermittently answer with a bot-challenge page (we stop instead of bypassing)."""
    from ..http import Blocked
    org = _org(ctx, "PKM Gallery", "pkm", PKM)
    r = ctx.fetch(f"{PKM}/exhibitions")
    cards = _pkm_cards(r.text)
    ctx.count("fetched", len(cards))
    lev = ctx.evidence(r, locator="exhibitions listing (full archive)")
    ctx.note("PKM /exhibitions lists the full archive 2001-present on one page")
    space_of, blocked = {}, None
    for slug, (venue, city, cc) in PKM_SPACES.items():
        try:
            sr = ctx.fetch(f"{PKM}/exhibitions/past/{slug}")
        except Blocked as b:
            blocked = b
            break
        sev = ctx.evidence(sr, locator=f"space archive {slug}")
        for c in _pkm_cards(sr.text):
            space_of.setdefault(c["slug"], (venue, city, cc, sev))
    floor = "2023-01-01" if ctx.mode == "initial" else (_today() - dt.timedelta(days=400)).isoformat()
    for c in cards:
        start = parse_date_range(c["date"])[0]
        if not start or start < floor or not re.search(r"\d", c["date"]) or "forthcoming" in c["slug"] or "upcoming" in c["slug"]:
            continue
        venue, city, cc, ev = space_of.get(c["slug"], (None, None, None, lev))
        if c["sub"]:
            title, names = c["sub"], [c["head"]]
        else:
            title, names = c["head"], []
        artists = [(n, f"src:{ctx.source_id}", None, "structured_field", "medium") for n in names]
        _store(ctx, org, key=c["slug"], title=title, date_text=c["date"], url=f"{PKM}/exhibitions/{c['slug']}", ev=ev,
               city=city, cc=cc, artists=artists, desc=f"venue: {venue}" if venue else None)
    ctx.con.commit()
    if blocked is not None:
        ctx.note("space archive page answered with a challenge page; venue left unknown for unmapped shows")
        raise blocked


# -- Gallery Hyundai ---------------------------------------------------------------------------------
def _gh(ctx):
    """/exhibition (old path) is 404. Current shows: /exhibition/onview; history: the public sitemap.xml lists
    exhibition detail URLs, each carrying a schema.org ExhibitionEvent (dates, performer, location, address country)."""
    from ._common import jsonld_objects
    org = _org(ctx, "Gallery Hyundai", "galleryhyundai", GH)
    ids = []
    r = ctx.fetch(f"{GH}/exhibition/onview")
    ids += re.findall(r"/exhibition/view/(\d+)", r.text)
    sm = ctx.fetch(f"{GH}/sitemap.xml", accept="application/xml")
    ids += re.findall(r"/exhibition/view/(\d+)<", sm.text)
    ids = list(dict.fromkeys(ids))
    ctx.count("fetched", len(ids))
    ctx.note(f"Gallery Hyundai: onview + sitemap.xml expose {len(ids)} exhibition pages (sitemap is not exhaustive)")
    for xid in ids:
        if not _needs_detail(ctx, xid):
            continue
        url = f"{GH}/exhibition/view/{xid}"
        try:
            dr = ctx.fetch(url)
        except FetchError as e:
            ctx.count("detail_errors")
            ctx.note(f"{url}: {e}")
            continue
        ev_obj = next((o for o in jsonld_objects(dr.text) if o.get("@type") == "ExhibitionEvent"), None)
        if ev_obj is None:
            ctx.count("detail_errors")
            continue
        sd, ed = ev_obj.get("startDate"), ev_obj.get("endDate")
        date_text = f"{sd} / {ed}"
        loc = ev_obj.get("location") or {}
        addr = loc.get("address") or {} if isinstance(loc, dict) else {}
        city, cc = addr.get("addressLocality"), addr.get("addressCountry")
        perf = ev_obj.get("performer") or []
        perf = perf if isinstance(perf, list) else [perf]
        names = [clean_text(p.get("name")) for p in perf if isinstance(p, dict) and p.get("name")]
        if not names:
            names = [clean_text(x.get_text(" ")) for x in soup(dr.text).select(".exd-title__artist") if clean_text(x.get_text(" "))]
            method = "list_markup"
        else:
            method = "structured_field"
        ev = ctx.evidence(dr, locator=f"ExhibitionEvent JSON-LD view/{xid}", excerpt=date_text)
        title = clean_text(ev_obj.get("name"))
        start, sp, end, ep = (sd[:10] if sd else None), ("day" if sd else None), (ed[:10] if ed else None), ("day" if ed else None)
        eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=xid, event_type="exhibition",
                              subtype=classify_subtype(title, len(names) or None), title=title, title_lang=None,
                              organizer_entity_id=org, city=city, country_code=cc, start_date=start, start_precision=sp,
                              end_date=end, end_precision=ep, date_text=date_text, url=url, parser_version=PARSER_VERSION,
                              evidence_id=ev, description_excerpt=f"venue: {loc.get('name')}" if isinstance(loc, dict) and loc.get("name") else None)
        ctx.count("parsed")
        if not cc:
            db.add_review(ctx.con, "region", "events", eid, "venue country unknown")
        for n in names:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=n, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=ev)
            db.add_participant(ctx.con, eid, ent, "artist", n, ev, method)
        if ev_obj.get("image"):
            db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=ev_obj["image"],
                                usage_status="unknown", basis="no licence stated on Gallery Hyundai pages")
        ctx.con.commit()
    ar = ctx.fetch(f"{GH}/artist/list")
    aev = ctx.evidence(ar, locator="artist list")
    n = 0
    for a in soup(ar.text).select("a[href*='/artist/view/']"):
        name = clean_text(a.get_text(" "))
        aid = re.search(r"/artist/view/(\d+)", a["href"]).group(1)
        if not name:
            continue
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace="galleryhyundai_artist", id_value=aid,
                               source_id=ctx.source_id, evidence_id=aev, official_url=f"{GH}/artist/view/{aid}")
        db.upsert_relationship(ctx.con, subject_entity_id=ent, object_entity_id=org, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=aev)
        n += 1
    ctx.count("roster_artists", n)
    ctx.con.commit()
