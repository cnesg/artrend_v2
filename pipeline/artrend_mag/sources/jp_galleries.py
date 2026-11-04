"""Japanese commercial galleries: Taka Ishii Gallery, Tomio Koyama Gallery, ANOMALY, SCAI THE BATHHOUSE.

Public HTML listing pages / WordPress feeds. Raw HTML kept internally as evidence only.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import db
from ..http import Blocked, FetchError
from ._common import classify_subtype, clean_text, parse_date_range, soup
from .jp_museums import _artist_from_title, _needs_detail

PARSER_VERSION = "jp_galleries-1"
TIG = "https://www.takaishiigallery.com"
TKG = "https://www.tomiokoyamagallery.com"
ANO = "https://anomalytokyo.com"

SOURCES = [
    dict(source_id="taka_ishii_gallery", blueprint_data_id=None, blueprint_org_id="O13", name="Taka Ishii Gallery — Exhibitions & Artists",
         owner_group="Taka Ishii Gallery", source_kind="gallery", region_scope="JP", country_codes="JP,US,HK,FR",
         access_method="html", base_url=TIG, entry_url=f"{TIG}/en/exhibitions/tokyo/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located (no terms/copyright page linked from site)",
         st_image_terms="no licence stated; artworks/photos copyright artists/gallery", max_requests=120),
    dict(source_id="tomio_koyama_gallery", blueprint_data_id=None, blueprint_org_id="O15", name="Tomio Koyama Gallery — Exhibitions",
         owner_group="Tomio Koyama Gallery", source_kind="gallery", region_scope="JP", country_codes="JP",
         access_method="html", base_url=TKG, entry_url=f"{TKG}/en/exhibitions/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located; footer: '(c) TOMIO KOYAMA GALLERY INC. All Rights Reserved.'",
         st_image_terms="all rights reserved (footer notice); no image licence", max_requests=60),
    dict(source_id="anomaly_tokyo", blueprint_data_id=None, blueprint_org_id="O16", name="ANOMALY — Exhibitions",
         owner_group="ANOMALY", source_kind="gallery", region_scope="JP", country_codes="JP",
         access_method="html", base_url=ANO, entry_url=f"{ANO}/en/past-exhibitions/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html; RSS /exhibition/feed/ exists but carries no dates)",
         st_collection_terms="terms page not located; footer: 'Copyright (c) ANOMALY, All rights reserved.'",
         st_image_terms="all rights reserved (footer notice); artwork credits per image", max_requests=30),
    dict(source_id="scai_the_bathhouse", blueprint_data_id=None, blueprint_org_id="O14", name="SCAI THE BATHHOUSE — Exhibitions",
         owner_group="SCAI THE BATHHOUSE", source_kind="gallery", region_scope="JP", country_codes="JP",
         access_method="html", base_url="https://www.scaithebathhouse.com",
         entry_url="https://www.scaithebathhouse.com/en/exhibitions/past/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located", st_image_terms="no image licence stated; all rights reserved by default",
         max_requests=30),
]

# listing category slug -> (city, country) as named by the gallery's own branch label
_TIG_BRANCH = {
    "tokyo": ("Tokyo", "JP"), "kyobashi": ("Tokyo", "JP"), "photography-film": ("Tokyo", "JP"),
    "tennozu": ("Tokyo", "JP"), "kitasando": ("Tokyo", "JP"), "modern": ("Tokyo", "JP"),
    "kyoto": ("Kyoto", "JP"), "kyoto-yada-cho": ("Kyoto", "JP"), "maebashi": ("Maebashi", "JP"),
    "new-york": ("New York", "US"), "hongkong": ("Hong Kong", "HK"), "photography-paris": ("Paris", "FR"),
}

_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"


def en_range(text):
    """'Oct 3 – 31, 2026' -> 'Oct 3 – Oct 31, 2026' then parse_date_range (which inherits the end year)."""
    t = clean_text(text)
    t = re.sub(r"\*", "", t)
    t = re.sub(rf"\b({_MON})\s+(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}}),\s*(\d{{4}})", r"\1 \2 – \1 \3, \4", t)
    return parse_date_range(t)


def collect(ctx):
    if ctx.source_id == "taka_ishii_gallery":
        return _tig(ctx)
    if ctx.source_id == "tomio_koyama_gallery":
        return _tkg(ctx)
    if ctx.source_id == "anomaly_tokyo":
        return _anomaly(ctx)
    if ctx.source_id == "scai_the_bathhouse":
        return _scai(ctx)
    raise ValueError(ctx.source_id)


def _fetch_detail(ctx, url):
    try:
        return ctx.fetch(url)
    except Blocked:
        raise
    except FetchError as e:
        ctx.note(f"detail error {url}: {e}")
        ctx.count("detail_errors")
        return None


# --------------------------------------------------------------------------------------------- Taka Ishii
def _tig(ctx):
    con = ctx.con
    org = db.ensure_entity(con, entity_type="gallery", name="Taka Ishii Gallery", namespace=f"src:{ctx.source_id}",
                           id_value="taka_ishii_gallery", lang="en", source_id=ctx.source_id, official_url=f"{TIG}/en/")
    # roster
    roster = {}
    for path in ("/en/artists/artists-tokyo/", "/en/artists/artists-photography-film/"):
        r = ctx.fetch(TIG + path)
        rev = ctx.evidence(r, locator="ul.list01 a")
        links = soup(r.text).select("ul.list01 a[href*='/en/archives/']")
        ctx.count("fetched", len(links))
        for a in links:
            m = re.search(r"/archives/(\d+)/", a["href"])
            name = clean_text(a.get_text(" "))
            if not m or not name:
                continue
            ent = db.ensure_entity(con, entity_type="group" if name.isupper() and " " not in name and len(name) < 8 else "person",
                                   name=name, namespace="takaishii_artist", id_value=m.group(1), source_id=ctx.source_id,
                                   evidence_id=rev, official_url=a["href"])
            db.upsert_relationship(con, subject_entity_id=org, object_entity_id=ent, rel_type="listed_artist",
                                   source_id=ctx.source_id, evidence_id=rev, scope=path.rsplit("/", 2)[-2],
                                   status="source_asserted")
            roster[name.casefold()] = ent
    con.commit()
    seen = set()
    for slug, (city, cc) in _TIG_BRANCH.items():
        url = f"{TIG}/en/exhibitions/{slug}/"
        page = 1
        while url:
            try:
                r = ctx.fetch(url)
            except Blocked:
                raise
            except FetchError as e:
                ctx.note(f"listing {slug} p{page}: {e}")
                break
            if slug != "tokyo" and r.final_url.rstrip("/").endswith("/exhibitions/tokyo"):
                break  # category redirected to default listing
            s = soup(r.text)
            secs = s.select("section.wrap01")
            ctx.count("fetched", len(secs))
            oldest = None
            for sec in secs:
                start = _tig_item(ctx, org, roster, sec, r, city, cc, seen)
                if start:
                    oldest = start if oldest is None or start < oldest else oldest
            con.commit()
            nxt = s.find("a", string=re.compile(r"Next"))
            if ctx.mode != "initial" or not nxt or (oldest and oldest < "2023-01-01"):
                break
            url, page = urllib.parse.urljoin(r.final_url, nxt["href"]), page + 1
    ctx.note("Taka Ishii: per-branch listings (Tokyo/Kyobashi/Photography-Film/Tennozu/Kitasando/Modern/Kyoto/Maebashi/"
             "New York/Hong Kong/Paris), paginated until shows start before 2023-01-01; roster from artists pages "
             "(listed_artist; pages do not say 'represents')")


def _tig_item(ctx, org, roster, sec, r, city, cc, seen):
    a = sec.select_one("h2 a[href]")
    if not a:
        return None
    url = a["href"]
    m = re.search(r"/archives/(\d+)/", url)
    key = m.group(1) if m else url
    title = clean_text(a.get_text(" "))
    p = sec.select_one(".col5 > p:not(.upcoming)")
    info = p.get_text("\n") if p else ""
    dm = re.search(r"Dates:\s*([^\n\[]+)", info)
    resp, locator = r, f"section.wrap01 a[href$='{key}/']"
    if key in seen:
        return None
    if not dm:
        if not _needs_detail(ctx, key):
            return None
        d = _fetch_detail(ctx, url)
        if d is None:
            return None
        dp = soup(d.text).select_one("#main02 p")
        info = dp.get_text("\n") if dp else ""
        dm = re.search(r"Dates:\s*([^\n\[]+)", info)
        resp, locator = d, "#main02 p:first"
    seen.add(key)
    lm = re.search(r"Location:\s*([^\n]+)", info)
    location = clean_text(lm.group(1)) if lm else None
    date_text = clean_text(dm.group(1)) if dm else None
    start, sp, end, ep = en_range(date_text) if date_text else (None, None, None, None)
    status = "postponed" if re.search(r"postponed", info, re.I) else ("cancelled" if re.search(r"cancel", info, re.I) else None)
    # artists: explicit "Participating artists:" list, else 'Name “Title”' title pattern
    artists, method = [], "title_pattern"
    pm = re.search(r"Participating artists?:\s*(.+?)(?:\n\s*\n|$)", info, re.S | re.I)
    if pm:
        artists = [clean_text(x) for x in re.split(r"\n|,", pm.group(1)) if clean_text(x) and clean_text(x) != ","]
        method = "list_markup"
    else:
        qm = re.match(r"^([^“\"]{2,60}?)\s*[“\"]", title)
        name = clean_text(qm.group(1)) if qm else None
        if not name and "“" not in title and title.casefold() in roster:
            name = title
        if name and (re.search(r"[:\d]|exhibition|collaboration|group|selected", name, re.I)):
            name = None
        if not name:
            name = _artist_from_title(title)
        if name:
            artists = [name] if name.casefold() in roster else [clean_text(x) for x in re.split(r"\s+&\s+|,\s*", name)]
    subtype = classify_subtype(title, len(artists) or None)
    ev = ctx.evidence(resp, locator=locator, excerpt=date_text)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition", subtype=subtype,
        title=title, title_lang="en", organizer_entity_id=org, city=city, country_code=cc,
        start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
        announced_status=status, url=url, description_excerpt=f"Location: {location}" if location else None,
        parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    for name in artists:
        ent = roster.get(name.casefold())
        if ent is None:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "artist", name, ev, method, "high" if method == "list_markup" else "medium")
    img = sec.select_one("img[src]")
    if img is not None:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url,
                            image_url=urllib.parse.urljoin(TIG, img["src"]), usage_status="unknown",
                            basis="no licence stated on site; all rights reserved by default")
    return start


# --------------------------------------------------------------------------------------------- shared row helpers
_MDY = re.compile(r"(\d{1,2})\.(\d{1,2})\s*(?:\([^)]*\))?\s*[-–~〜−－—]\s*(\d{1,2})\.(\d{1,2})\s*(?:\([^)]*\))?,\s*(\d{4})")
_WEEKDAY = re.compile(r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s*", re.I)


def _any_range(text):
    """Dotted ('2026.10.10 (Sat) - 11.8 (Sun)'), 'm.d (w) - m.d (w), YYYY', or English month names.
    Returns (start, start_precision, end, end_precision)."""
    from .jp_museums import _dotted_range, _mk
    t = (text or "").replace("（", "(").replace("）", ")")
    s, e = _dotted_range(t)
    if s:
        return s, "day", e, ("day" if e else None)
    m = _MDY.search(t)
    if m:
        m1, d1, m2, d2, y = m.groups()
        y1 = int(y) - 1 if int(m1) > int(m2) else int(y)
        s, e = _mk(y1, m1, d1), _mk(y, m2, d2)
        return s, ("day" if s else None), e, ("day" if e else None)
    t = re.split(r"\s/\s|\*", t)[0]
    t = _WEEKDAY.sub("", re.sub(r"\([^)]*\)", "", t))
    return en_range(re.sub(r"\s+,", ",", t))


def _store_row(ctx, org, *, key, title, artists, date_text, url, resp, locator, city, cc, location, img=None,
               img_basis="no licence stated on site; all rights reserved by default", method="list_markup", lang="en",
               year_hint=None):
    start, sp, end, ep = _any_range(date_text)
    if year_hint and re.fullmatch(r"\d{4}", year_hint) and re.match(r"\s*\d{1,2}\.\d{1,2}\s*\(", date_text or ""):
        # year stated once in the listing's year header; rows give 'm.d(w) - m.d(w)' or 'm.d(w) - d(w)'
        m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s*(?:\([^)]*\))?\s*[-–~〜−－—]\s*(?:(\d{4})\.)?(?:(\d{1,2})\.)?(\d{1,2})\b",
                     (date_text or "").replace("（", "(").replace("）", ")"))
        if m:
            from .jp_museums import _mk
            m1, d1, ye, m2, d2 = m.groups()
            m2 = m2 or m1
            if ye:  # end year printed: start year is the same or the previous one
                y2 = int(ye)
                y1 = y2 - 1 if int(m1) > int(m2) else y2
            else:
                y1 = int(year_hint)
                y2 = y1 + (1 if int(m2) < int(m1) else 0)
            start, end = _mk(y1, m1, d1), _mk(y2, m2, d2)
            sp, ep = ("day" if start else None), ("day" if end else None)
    subtype = classify_subtype(title, len(artists) or None)
    ev = ctx.evidence(resp, locator=locator, excerpt=date_text)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition", subtype=subtype,
        title=title, title_lang=lang, organizer_entity_id=org, city=city, country_code=cc,
        start_date=start, start_precision=sp, end_date=end, end_precision=ep,
        date_text=date_text, url=url, description_excerpt=f"Location: {location}" if location else None,
        parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    if cc is None:
        db.add_review(ctx.con, "region", "events", eid, "venue country unknown", f"location: {location}")
    for name in artists:
        etype = "group" if re.search(r"group|collective|studio|↑|&|DOMMUNE", name, re.I) else "person"
        ent = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"src:{ctx.source_id}",
                               source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "artist", name, ev, method)
    if img:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=img,
                            usage_status="unknown", basis=img_basis)
    return start


# --------------------------------------------------------------------------------------------- Tomio Koyama
TKG = "https://www.tomiokoyamagallery.com"


def _tkg_place(location):
    loc = (location or "").upper()
    if re.search(r"ROPPONGI|TENNOZ|KYOBASHI|六本木|天王洲|京橋|TOKYO|東京", loc):
        return "Tokyo", "JP"
    if re.search(r"MAEBASHI|前橋", loc):
        return "Maebashi", "JP"
    if re.search(r"KYOTO|京都", loc):
        return "Kyoto", "JP"
    return None, None


def _tkg(ctx):
    org = db.ensure_entity(ctx.con, entity_type="gallery", name="Tomio Koyama Gallery", namespace=f"src:{ctx.source_id}",
                           id_value="tomio_koyama_gallery", lang="en", source_id=ctx.source_id, official_url=f"{TKG}/en/")
    seen = set()
    _tkg_page(ctx, org, ctx.fetch(f"{TKG}/en/exhibitions/"), seen)  # overview: current gallery + other exhibitions
    url, page = f"{TKG}/en/exhibitions/gallery/", 1
    while url:
        r = ctx.fetch(url)
        s, oldest = _tkg_page(ctx, org, r, seen)
        nxt = s.select_one("a[rel=next]")
        if ctx.mode != "initial" or nxt is None or (oldest and oldest < "2023-01-01") or page >= 15:
            break
        url, page = urllib.parse.urljoin(r.final_url, nxt["href"]), page + 1
    ctx.note("Tomio Koyama: /en/exhibitions/ overview + /en/exhibitions/gallery/ archive (artist/date/title/location "
             "rows), paginated back to 2023-01-01 in initial mode (archive reaches ~9 pages)")


def _tkg_page(ctx, org, r, seen):
    s = soup(r.text)
    arts = [a for a in s.select("article")
            if not re.search(r"OTHER", (a.find_previous(class_="section-title") or a).get_text(" "), re.I)]
    ctx.count("fetched", len(arts))
    oldest = None
    for art in arts:
        a = art.select_one("a.anchor-block[href]")
        if not a:
            continue
        href = a["href"]
        key = href.rstrip("/").rsplit("/", 1)[-1]
        if key in seen:
            continue
        seen.add(key)
        sa = a.select_one(".exhibition-artist")
        artists = [clean_text(x) for x in sa.get_text("\n").split("\n") if clean_text(x)] if sa else []
        st = a.select_one(".exhibition-title")
        title = clean_text(st.get_text(" ")) if st else ""
        title = title.strip("“”\"") if title.count("“") <= 1 else title
        if not title:
            title = ", ".join(artists) or key
        sd = a.select_one(".exhibition-date")
        sl = a.select_one(".exhibition-location")
        location = clean_text(sl.get_text(" ")) if sl else None
        city, cc = _tkg_place(location)
        start = _store_row(ctx, org, key=key, title=title, artists=artists,
                           date_text=clean_text(sd.get_text(" ")) if sd else None, url=href, resp=r,
                           locator=f"article#{art.get('id')}", city=city, cc=cc, location=location)
        if start:
            oldest = start if oldest is None or start < oldest else oldest
    ctx.con.commit()
    return s, oldest


# --------------------------------------------------------------------------------------------- ANOMALY
ANO = "https://anomalytokyo.com"


def _anomaly(ctx):
    org = db.ensure_entity(ctx.con, entity_type="gallery", name="ANOMALY", namespace=f"src:{ctx.source_id}",
                           id_value="anomaly", lang="en", source_id=ctx.source_id, official_url=f"{ANO}/en/")
    pages = [f"{ANO}/en/current-exhibition/", f"{ANO}/en/upcoming-exhibition/", f"{ANO}/en/past-exhibitions/"]
    seen = set()
    for pu in pages:
        r = ctx.fetch(pu)
        s = soup(r.text)
        dates = s.select("p.exhibition-date")
        ctx.count("fetched", len(dates))
        for pd in dates:
            a = pd.find_parent("a", href=True)
            box = a if a is not None else pd.parent
            href = a["href"] if a is not None else None
            if href is None:
                l2 = box.find("a", href=re.compile(r"/exhibition/"))
                href = l2["href"] if l2 else pu
            key = href.rstrip("/").rsplit("/", 1)[-1] if "/exhibition/" in href else None
            if not key or key in seen:
                continue
            seen.add(key)
            heads = [clean_text(h.get_text(" ")) for h in box.select("h4")]  # [artist, category, title]
            artist_h = box.select_one(".exhibition-artistname")
            if artist_h is not None:
                artist_line = clean_text(artist_h.get_text(" "))
                t = box.select_one(".ex-title")
                title = clean_text(t.get_text(" ")) if t else ""
            else:
                artist_line = heads[0] if heads else ""  # listing rows: [artist, category, title]
                title = heads[-1] if len(heads) > 1 else ""
            if re.search(r"exhibition|screening|\d{4}", artist_line, re.I):
                artist_line = ""  # heading slot holds a show title, not a name
            artists = [x for x in (clean_text(p) for p in re.split(r",\s*|、|\s/\s", artist_line)) if x]
            if not title:
                title = artist_line or key
            img = box.select_one("img[src]")
            _store_row(ctx, org, key=key, title=title, artists=artists, date_text=clean_text(pd.get_text(" ")),
                       url=href, resp=r, locator=f"a[href*='/exhibition/{key}/'] p.exhibition-date",
                       city="Tokyo", cc="JP", location=None,
                       img=img["src"] if img is not None else None)
        ctx.con.commit()
    ctx.note("ANOMALY: current/upcoming/past listing pages (past page lists all archive items on one page); "
             "single venue in Tokyo")


# --------------------------------------------------------------------------------------------- SCAI THE BATHHOUSE
SCAI = "https://www.scaithebathhouse.com"
_SCAI_LISTS = {"past": "SCAI THE BATHHOUSE", "piramide": "SCAI PIRAMIDE", "park": "SCAI PARK"}


def _scai_title(el):
    """'Artist<br/>"Title"' -> (display title, [artists])."""
    lines = [clean_text(x) for x in el.get_text("\n").split("\n") if clean_text(x)]
    if not lines:
        return "", []
    if len(lines) >= 2:
        artist_line, title = lines[0], " ".join(lines[1:])
        names = [clean_text(x) for x in re.split(r"\s+&\s+|,\s*|\s+and\s+", artist_line) if clean_text(x)]
        return f"{artist_line} {title}", names
    t = lines[0]
    m = re.match(r"^(.+?)\s+Solo Exhibition\b", t, re.I)
    return t, ([clean_text(m.group(1))] if m else [])


def _scai(ctx):
    org = db.ensure_entity(ctx.con, entity_type="gallery", name="SCAI THE BATHHOUSE", namespace=f"src:{ctx.source_id}",
                           id_value="scai_the_bathhouse", lang="en", source_id=ctx.source_id, official_url=f"{SCAI}/en/")
    seen = set()
    current = []
    for slug, space in _SCAI_LISTS.items():
        r = ctx.fetch(f"{SCAI}/en/exhibitions/{slug}/")
        s = soup(r.text)
        if not current:
            for a in s.select("ul.dropdown-menu a[href*='/en/exhibitions/20']"):
                lab = clean_text(a.get_text(" "))
                if lab in ("Current", "Upcoming"):
                    space_el = a.find_parent("li", class_="dropdown-submenu")
                    sp = clean_text(space_el.a.get_text(" ")) if space_el and space_el.a else None
                    current.append((urllib.parse.urljoin(r.final_url, a["href"]), sp, lab))
        durs = s.select(".list-duration")
        ctx.count("fetched", len(durs))
        for d in durs:
            t = d.find_next_sibling(class_="list-title")
            a = t.select_one("a[href]") if t else None
            if a is None:
                continue
            url = urllib.parse.urljoin(r.final_url, a["href"])
            m = re.search(r"/en/exhibitions/(\d{4}/\d{2}/[^/]+)/", url)
            key = m.group(1) if m else url
            if key in seen:
                continue
            seen.add(key)
            title, artists = _scai_title(a)
            date_text = clean_text(d.get_text(" "))
            ly = d.find_previous(class_="list-year")
            _store_row(ctx, org, key=key, title=title, artists=artists, date_text=date_text,
                       year_hint=clean_text(ly.get_text(" ")) if ly else None,
                       url=url, resp=r, locator=f".list-title a[href*='{key}']", city="Tokyo", cc="JP",
                       location=space, method="title_pattern")
        ctx.con.commit()
    for url, space, lab in current:
        m = re.search(r"/en/exhibitions/(\d{4}/\d{2}/[^/]+)/", url)
        key = m.group(1) if m else url
        if key in seen or not _needs_detail(ctx, key):
            continue
        d = _fetch_detail(ctx, url)
        if d is None:
            continue
        s = soup(d.text)
        h1 = s.select_one(".title_info h1")
        dur = s.select_one(".title_info .duration")
        if h1 is None:
            continue
        seen.add(key)
        title, artists = _scai_title(h1)
        img = s.select_one(".eyecatch img[src]")
        _store_row(ctx, org, key=key, title=title, artists=artists,
                   date_text=clean_text(dur.get_text(" ")) if dur else None, url=url, resp=d,
                   locator=".title_info .duration", city="Tokyo", cc="JP", location=space, method="title_pattern",
                   img=img["src"] if img is not None else None)
    ctx.con.commit()
    ctx.note("SCAI: past listings for SCAI THE BATHHOUSE / PIRAMIDE / PARK (single page each, full history) + "
             "current/upcoming detail pages from the site menu; all three spaces are in Tokyo")
