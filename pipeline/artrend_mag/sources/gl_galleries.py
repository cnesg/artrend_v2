"""Global mega-gallery programs: exhibitions per location + artist rosters (listed_artist).

David Zwirner: public __NEXT_DATA__ on /exhibitions (current+upcoming) and /exhibitions/past-exhibitions/year/<Y>/page/<n>
(structured artists + location address). Roster from /artists (__NEXT_DATA__ artistPages).
Pace: server-rendered listing /exhibitions/ (on view + upcoming) and /exhibitions/status/archive/?page=N
(heading / subheading / location / date line). Roster from /artists/. DISABLED: Pace terms forbid robots/automatic
access; parser kept (verified in scratch) pending legal review/permission.
Perrotin: Inertia.js page props (data-page JSON) on /exhibitions/current and /en/history/<year>; roster from /en/artists
("Represented" list -> represents, exhibited list -> listed_artist).
Thaddaeus Ropac: server-rendered /exhibitions/ (current+forthcoming) and /exhibitions/all/past/?skip=N.
Lisson: server-rendered current/upcoming/past exhibition cards, with ExhibitionEvent JSON-LD on detail pages.
Registry-only rows: White Cube (ToS bans text/data mining), Hauser & Wirth, Gagosian, Art Basel, Ocula (blocked).
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import timedelta

from bs4 import BeautifulSoup

from .. import db, region
from ..config import now_kst
from ..http import FetchError
from ._common import classify_subtype, clean_text, jsonld_objects, next_data, parse_date_range, split_title_artist

PARSER_VERSION = "gl_galleries-2"
HISTORY_FLOOR = "2023-01-01"

_CITY_EXTRA = {  # gallery branch cities missing from region._NAME_MAP
    "palm beach": "US", "east hampton": "US", "palo alto": "US", "menlo park": "US", "aspen": "US", "hamptons": "US",
    "the hamptons": "US", "southampton": "US", "beverly hills": "US", "chelsea": "US", "tribeca": "US",
    "salzburg": "AT", "pantin": "FR", "piraeus": "GR", "milano": "IT", "rome": "IT", "athens": "GR", "gstaad": "CH", "st. moritz": "CH",
    "st moritz": "CH", "minorca": "ES", "menorca": "ES", "mallorca": "ES", "somerset": "GB", "bermondsey": "GB",
    "mason's yard": "GB", "mayfair": "GB", "west palm beach": "US", "seoul": "KR", "tokyo": "JP",
}


def _country(text):
    if not text:
        return None
    t = region.norm(text)
    return region.country_from_text(text) or _CITY_EXTRA.get(t) or _CITY_EXTRA.get(t.split(",")[-1].strip())


def _row(source_id, name, org_id, entry, base, terms_url, coll, img, **kw):
    r = dict(source_id=source_id, blueprint_data_id="D29", blueprint_org_id=org_id, name=name, owner_group=name.split(" —")[0],
             source_kind="gallery", region_scope="GLOBAL", country_codes="", access_method="html", base_url=base,
             entry_url=entry, terms_url=terms_url, text_storage_policy="raw_internal", priority="P1",
             st_official_doc="n/a(html)", st_collection_terms=coll, st_image_terms=img, max_requests=120)
    r.update(kw)
    return r


def _blocked(source_id, name, org_id, base, reason, robots, **kw):
    return _row(source_id, name, org_id, base, base, None, "not reachable", "not reachable", disabled=reason,
                operational_state="blocked_access", robots_status=robots, st_live_response="blocked", **kw)


SOURCES = [
    _row("davidzwirner_exhibitions", "David Zwirner — exhibitions", "O26", "https://www.davidzwirner.com/exhibitions",
         "https://www.davidzwirner.com", "https://www.davidzwirner.com/terms-and-conditions",
         coll="restrictive: terms allow personal non-commercial use only; prohibit copying/distributing/exploiting "
              "'Website Proprietary Contents'; no robot/crawler clause; listing metadata only (raw kept internal)", img="artwork images (c) artists/estates; not collected", country_codes="US,GB,FR,HK"),
    _row("pace_exhibitions", "Pace Gallery — exhibitions", None, "https://www.pacegallery.com/exhibitions/",
         "https://www.pacegallery.com", "https://www.pacegallery.com/terms/",
         coll="RESTRICTIVE: terms of use prohibit 'any robot, spider, or other automatic device, process, or means to "
              "access the Website for any purpose, including monitoring or copying'; personal non-commercial use only",
         img="artwork images (c) artists; not collected", country_codes="US,GB,DE,KR,JP,HK,CH",
         disabled="Pace terms of use prohibit robots/spiders/automatic access (checked 2026-10-27); parser verified in "
                  "scratch only, kept pending legal review/permission",
         operational_state="blocked_permission", robots_status="parsed(allow)", st_live_response="ok(200; not collected: ToS)"),
    _row("perrotin_exhibitions", "Perrotin — exhibitions", None, "https://www.perrotin.com/exhibitions/current",
         "https://www.perrotin.com", "https://www.perrotin.com/en/legal",
         coll="restrictive: legal notice allows only personal, private, non-commercial use; downloading/reproduction "
              "for other purposes prohibited; no robot/crawler clause; listing metadata only (raw kept internal)",
         img="images (c) artists/Perrotin; not collected", country_codes="FR,US,HK,KR,JP,CN,GB,AE"),
    _row("ropac_exhibitions", "Thaddaeus Ropac — exhibitions", None, "https://ropac.net/exhibitions/", "https://ropac.net",
         None, coll="terms page not located", img="images (c) artists/gallery; not collected", country_codes="AT,FR,GB,KR,IT"),
    _row("whitecube_exhibitions", "White Cube — exhibitions", "O33", "https://www.whitecube.com/exhibitions",
         "https://www.whitecube.com", "https://www.whitecube.com/terms-of-use",
         coll="RESTRICTIVE: terms of use forbid 'unauthorised text/data mining of Website content and metadata' and "
              "'substantial or repeated extraction and/or storage of Website content'; needs permission/legal review",
         img="images (c) artists/White Cube; not collected", country_codes="GB,US,FR,HK,KR",
         disabled="not implemented: White Cube terms prohibit unauthorised text/data mining (checked 2026-10-27)",
         operational_state="blocked_permission", robots_status="parsed(allow)", st_live_response="ok(200; not collected: ToS)"),
    _row("lisson_exhibitions", "Lisson Gallery — exhibitions", None, "https://lisson.com/exhibitions",
         "https://lisson.com", "https://lisson.com/legal/terms-and-conditions",
         coll="Terms & Conditions reviewed: no robot/crawler or text-mining clause found; exhibition HTML retained internally",
         img="no open image licence stated; images are not collected", country_codes="GB,US,CN,IT,FR,ES,DE,AE",
         access_method="html+jsonld", max_requests=100),
    _blocked("hauserwirth_exhibitions", "Hauser & Wirth — exhibitions", "O32", "https://www.hauserwirth.com",
             "robots.txt request answered HTTP 429 (checked 2026-10-27); not crawled", "robots_http_429(not_crawled)"),
    _blocked("gagosian_exhibitions", "Gagosian — exhibitions", "O25", "https://gagosian.com",
             "HTTP 403 to the project crawler (checked 2026-10-27); not bypassed", "unknown(403)"),
    _blocked("artbasel_shows", "Art Basel — shows & galleries", None, "https://www.artbasel.com",
             "robots.txt request answered HTTP 403 (checked 2026-10-27); not crawled", "robots_http_403(not_crawled)",
             blueprint_data_id="D21", source_kind="fair"),
    _blocked("ocula_listings", "Ocula — gallery exhibitions directory", None, "https://ocula.com",
             "robots.txt request answered HTTP 403 (checked 2026-10-27); not crawled", "robots_http_403(not_crawled)",
             source_kind="media"),
]

ORG = {
    "davidzwirner_exhibitions": ("David Zwirner", "https://www.davidzwirner.com/"),
    "pace_exhibitions": ("Pace Gallery", "https://www.pacegallery.com/"),
    "perrotin_exhibitions": ("Perrotin", "https://www.perrotin.com/"),
    "ropac_exhibitions": ("Thaddaeus Ropac", "https://ropac.net/"),
    "lisson_exhibitions": ("Lisson Gallery", "https://lisson.com/"),
}


def collect(ctx):
    name, url = ORG[ctx.source_id]
    org = db.ensure_entity(ctx.con, entity_type="gallery", name=name, namespace=f"src:{ctx.source_id}", id_value="org",
                           source_id=ctx.source_id, official_url=url)
    {"davidzwirner_exhibitions": _dz, "pace_exhibitions": _pace, "perrotin_exhibitions": _perrotin,
     "ropac_exhibitions": _ropac, "lisson_exhibitions": _lisson}[ctx.source_id](ctx, org)
    ctx.con.commit()


def _artist(ctx, ev_id, name, ev, method, confidence="high", ns=None, slug=None):
    name = clean_text(name)
    if not name or name.lower() in ("various artists", "group exhibition", "group show", "including", "and", "with"):
        return None
    ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=ns or f"src:{ctx.source_id}",
                           id_value=slug, source_id=ctx.source_id, evidence_id=ev)
    if ev_id:
        db.add_participant(ctx.con, ev_id, ent, "artist", name, ev, method, confidence)
    return ent


_SAME_MONTH = re.compile(r"^([A-Z][a-z]{2,8})\.? (\d{1,2})\s*[–—-]\s*(\d{1,2}),? (\d{4})$")


def _dates(text):
    """parse_date_range plus the same-month form 'Feb 4 – 21, 2021' (the shared helper returns nothing for it)."""
    res = parse_date_range(text)
    if res[0] or res[2] or not text:
        return res
    m = _SAME_MONTH.match(text.strip())
    if m:
        a = parse_date_range(f"{m.group(1)} {m.group(2)}, {m.group(4)}")
        b = parse_date_range(f"{m.group(1)} {m.group(3)}, {m.group(4)}")
        return a[0], a[1], b[0], b[1]
    return res


def _review_region(ctx, eid, cc, loc):
    if not cc:
        db.add_review(ctx.con, "region", "events", eid, "venue country unknown", detail=loc)


# -- David Zwirner -------------------------------------------------------------------------------------------------
DZ = "https://www.davidzwirner.com"


def _dz(ctx, org):
    r = ctx.fetch(f"{DZ}/exhibitions")
    data = next_data(r.text)["props"]["pageProps"]["data"]
    n = 0
    for key in ("nowOpen", "upcoming"):
        for x in data.get(key) or []:
            if x.get("_type") == "exhibitionPage":
                n += _dz_event(ctx, org, r, x, f"exhibitions landing .{key}")
    years = [now_kst().year] if ctx.mode == "incremental" else list(range(now_kst().year, int(HISTORY_FLOOR[:4]) - 1, -1))
    for y in years:
        page = 1
        while True:
            u = f"{DZ}/exhibitions/past-exhibitions/year/{y}" + (f"/page/{page}" if page > 1 else "")
            try:
                rp = ctx.fetch(u)
            except FetchError as e:
                ctx.note(f"{u}: {e}")
                break
            d = next_data(rp.text)["props"]["pageProps"]["data"]
            items = d.get("pastExhibitions") or []
            for x in items:
                n += _dz_event(ctx, org, rp, x, f"past year={y} page={page}")
            ctx.con.commit()
            total = d.get("totalPastExhibitions") or 0
            if ctx.mode == "incremental" or not items or page * 24 >= total:
                break
            page += 1
    ctx.note(f"DZ: landing current+upcoming; past-exhibitions by year ({years[-1]}-{years[0]}); archive goes back to 1993")
    _dz_roster(ctx, org)


def _dz_event(ctx, org, resp, x, locator):
    ctx.count("fetched")
    slug = (x.get("slug") or {}).get("current")
    if not slug or not x.get("title"):
        return 0
    title = clean_text(x["title"]) + (f": {clean_text(x['subtitle'])}" if x.get("subtitle") else "")
    locs = x.get("locations") or []
    loc = locs[0] if locs else {}
    addr = loc.get("address") or {}
    city = addr.get("city") or (loc.get("name") or "").split(":")[0].strip() or None
    cc = _country(addr.get("country")) or _country(city)
    artists = x.get("artists") or []
    date_text = f"{x.get('startDate')} – {x.get('endDate')}" + (f" | {x['displayDate']}" if x.get("displayDate") else "")
    ev = ctx.evidence(resp, locator=f"{locator} {slug}", excerpt=date_text)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug, event_type="exhibition",
        subtype=classify_subtype(title, len(artists) or None), title=title, title_lang="en", organizer_entity_id=org,
        city=city, country_code=cc, start_date=x.get("startDate"), start_precision="day" if x.get("startDate") else None,
        end_date=x.get("endDate"), end_precision="day" if x.get("endDate") else None, date_text=date_text,
        url=DZ + slug, evidence_id=ev, parser_version=PARSER_VERSION,
        description_excerpt="; ".join(l.get("name") or "" for l in locs) or None)
    for a in artists:
        aslug = ((a.get("artistPage") or {}).get("slug") or {}).get("current")
        _artist(ctx, eid, a.get("fullName"), ev, "structured_field", ns="davidzwirner_artist" if aslug else None,
                slug=aslug.rsplit("/", 1)[-1] if aslug else None)
    if not artists and x.get("subtitle") and not re.search(r"[/&,]| and ", x["title"]):
        # landing cards omit the artists array; DZ solo cards put the artist in `title` and the show title in `subtitle`
        _artist(ctx, eid, x["title"], ev, "title_pattern", "medium")
    _review_region(ctx, eid, cc, loc.get("name"))
    ctx.count("parsed")
    return 1


def _dz_roster(ctx, org):
    try:
        r = ctx.fetch(f"{DZ}/artists")
    except FetchError as e:
        ctx.note(f"roster: {e}")
        return
    pages = next_data(r.text)["props"]["pageProps"]["data"].get("artistPages") or []
    ev = ctx.evidence(r, locator="/artists artistPages", excerpt=f"{len(pages)} artists listed")
    for p in pages:
        slug = (p.get("slug") or {}).get("current")
        nm = (p.get("artist") or {}).get("fullName")
        if not slug or not nm:
            continue
        ent = _artist(ctx, None, nm, ev, None, ns="davidzwirner_artist", slug=slug.rsplit("/", 1)[-1])
        db.upsert_relationship(ctx.con, subject_entity_id=org, object_entity_id=ent, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=ev, status="source_asserted")
        ctx.count("roster")


# -- Pace ------------------------------------------------------------------------------------------------------------
PACE = "https://www.pacegallery.com"


def _pace(ctx, org):
    r = ctx.fetch(f"{PACE}/exhibitions/")
    s = BeautifulSoup(r.text, "lxml")
    for a in s.select("a.index-grid__link"):
        href = a.get("href") or ""
        if not re.match(r"^/exhibitions/[^/]+/$", href) or "/status/" in href:
            continue
        parts = [clean_text(t) for t in a.stripped_strings]
        parts = [p for p in parts if p]
        # e.g. [heading, status, (subheading), date, location]
        date_i = next((i for i, p in enumerate(parts) if re.search(r"\b(19|20)\d{2}\b", p)), None)
        if date_i is None:
            continue
        heading = parts[0]
        sub = " ".join(p for p in parts[1:date_i] if p not in ("On View", "Upcoming", "Closed")) or None
        loc = parts[date_i + 1] if len(parts) > date_i + 1 else None
        _pace_event(ctx, org, r, href, heading, sub, loc, parts[date_i], "on-view/upcoming grid")
    ctx.con.commit()
    page, max_pages = 1, (40 if ctx.mode == "initial" else 1)
    while page <= max_pages:
        u = f"{PACE}/exhibitions/status/archive/" + (f"?page={page}" if page > 1 else "")
        try:
            rp = ctx.fetch(u)
        except FetchError as e:
            ctx.note(f"{u}: {e}")
            break
        sp = BeautifulSoup(rp.text, "lxml")
        oldest, n = None, 0
        for a in sp.find_all("a", href=True):
            dnode = a.select_one(".archive-list__date")
            if not dnode:
                continue
            g = lambda c: clean_text(a.select_one(f".archive-list__{c}").get_text(" ")) if a.select_one(f".archive-list__{c}") else None
            st = _pace_event(ctx, org, rp, a["href"], g("heading"), g("subheading"), g("location"), g("date"),
                             f"archive page={page}")
            n += 1
            if st and (oldest is None or st < oldest):
                oldest = st
        ctx.con.commit()
        if not n or (oldest and oldest < HISTORY_FLOOR):
            break
        page += 1
    ctx.note(f"Pace: on-view/upcoming grid + archive paged to page {page} (archive reaches back to 2000s)")
    _pace_roster(ctx, org)


def _pace_event(ctx, org, resp, href, heading, sub, loc, date_line, locator):
    ctx.count("fetched")
    if not heading or not href:
        return None
    url = urllib.parse.urljoin(PACE, href)
    key = urllib.parse.urlsplit(url).path
    title = heading + (f": {sub}" if sub else "")
    start, sp, end, ep = _dates(date_line)
    cc = _country(loc) if loc and loc.lower() != "special projects" else None
    # Listing heading is the artist name for solo shows (heading + subheading); a bare heading may be either a
    # show title or an artist name, and names joined by '/', '&', ',' are not split.
    solo = bool(sub) and not re.search(r"[/&,]| and ", heading)
    ev = ctx.evidence(resp, locator=f"{locator} {key}", excerpt=date_line)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
        subtype=classify_subtype(title, 1 if solo else None), title=title, title_lang="en", organizer_entity_id=org,
        city=loc, country_code=cc, start_date=start, start_precision=sp, end_date=end, end_precision=ep,
        date_text=date_line, url=url, evidence_id=ev, parser_version=PARSER_VERSION)
    if solo:
        _artist(ctx, eid, heading, ev, "list_markup", "medium")
    _review_region(ctx, eid, cc, loc)
    ctx.count("parsed")
    return start


def _pace_roster(ctx, org):
    try:
        r = ctx.fetch(f"{PACE}/artists/")
    except FetchError as e:
        ctx.note(f"roster: {e}")
        return
    s = BeautifulSoup(r.text, "lxml")
    seen = set()
    links = [a for a in s.find_all("a", href=True) if re.match(r"^(https://www\.pacegallery\.com)?/artists/[^/]+/$", a["href"])]
    ev = ctx.evidence(r, locator="/artists/ links", excerpt=f"{len(links)} artist links")
    for a in links:
        slug = a["href"].rstrip("/").rsplit("/", 1)[-1]
        nm = clean_text(a.get_text(" "))
        if not nm or slug in seen:
            continue
        seen.add(slug)
        ent = _artist(ctx, None, nm, ev, None, ns="pace_artist", slug=slug)
        db.upsert_relationship(ctx.con, subject_entity_id=org, object_entity_id=ent, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=ev, status="source_asserted")
        ctx.count("roster")


# -- Perrotin --------------------------------------------------------------------------------------------------------
PERROTIN = "https://www.perrotin.com"


def _inertia(html):
    import html as _h
    import json

    m = re.search(r'data-page="([^"]+)"', html)
    return json.loads(_h.unescape(m.group(1)))["props"] if m else {}


def _perrotin(ctx, org):
    r = ctx.fetch(f"{PERROTIN}/exhibitions/current")
    p = _inertia(r.text)
    for x in p.get("currentExhibitions") or []:
        _perrotin_event(ctx, org, r, x, "exhibitions/current currentExhibitions")
    ctx.con.commit()
    latest = int(p.get("latestHistorySlug") or now_kst().year)
    years = [latest] if ctx.mode == "incremental" else list(range(latest, int(HISTORY_FLOOR[:4]) - 1, -1))
    for y in years:
        try:
            rh = ctx.fetch(f"{PERROTIN}/en/history/{y}")
        except FetchError as e:
            ctx.note(f"history {y}: {e}")
            continue
        for x in _inertia(rh.text).get("exhibitions") or []:
            _perrotin_event(ctx, org, rh, x, f"history/{y} exhibitions")
        ctx.con.commit()
    ctx.note(f"Perrotin: current page + yearly history pages {years[-1]}-{years[0]} (gallery exhibitions only; "
             "fairs/offsite museum loans not stored); history pages go back to 1990")
    _perrotin_roster(ctx, org)


def _perrotin_event(ctx, org, resp, x, locator):
    ctx.count("fetched")
    if x.get("type") != "exhibition" or not x.get("slug"):
        return
    title = clean_text(x.get("original_title") or x.get("title"))
    loc = (x.get("location") or {}).get("full_string") or ", ".join(v for v in (x.get("city"), x.get("country")) if v)
    cc = _country(loc)
    city = clean_text(x.get("city")).title() if x.get("city") else None
    sd, ed = (x.get("start_date") or "")[:10] or None, (x.get("end_date") or "")[:10] or None
    names = [clean_text(n) for n in (x.get("artist") or "").split(",") if clean_text(n)]
    show = x.get("show_type") or ""
    subtype = {"solo": "solo", "group_show": "group"}.get(show) or classify_subtype(title, len(names) or None)
    url = f"{PERROTIN}/en/events/{x['slug']}"
    ev = ctx.evidence(resp, locator=f"{locator} id={x.get('id')}", excerpt=f"{sd} – {ed} {loc}")
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=str(x.get("id") or x["slug"]), event_type="exhibition",
        subtype=subtype, title=title, title_lang=None, organizer_entity_id=org, city=city, country_code=cc,
        start_date=sd, start_precision="day" if sd else None, end_date=ed, end_precision="day" if ed else None,
        date_text=f"{x.get('start_date')} / {x.get('end_date')}", url=url, evidence_id=ev, parser_version=PARSER_VERSION,
        description_excerpt=x.get("venue") or None)
    for n in names:
        _artist(ctx, eid, n, ev, "structured_field")
    _review_region(ctx, eid, cc, loc)
    ctx.count("parsed")


def _perrotin_roster(ctx, org):
    try:
        r = ctx.fetch(f"{PERROTIN}/en/artists")
    except FetchError as e:
        ctx.note(f"roster: {e}")
        return
    p = _inertia(r.text)
    # the page renders "representedArtists" under the heading "Represented" -> represents; other lists -> listed_artist
    lists = [("representedArtists", "represents"), ("exhibitedArtists", "listed_artist")]
    if not any(p.get(k) for k, _ in lists):
        ctx.note("roster: artist lists not found in page props")
        return
    for key, rel in lists:
        arts = p.get(key) or []
        ev = ctx.evidence(r, locator=f"/en/artists props.{key}", excerpt=f"{len(arts)} artists ({key})")
        for a in arts:
            nm = clean_text(a.get("name"))
            if not nm or not a.get("slug"):
                continue
            ent = _artist(ctx, None, nm, ev, None, ns="perrotin_artist", slug=str(a["slug"]))
            if ent:
                db.upsert_relationship(ctx.con, subject_entity_id=org, object_entity_id=ent, rel_type=rel,
                                       source_id=ctx.source_id, evidence_id=ev, status="source_asserted")
                ctx.count("roster")


# -- Thaddaeus Ropac ---------------------------------------------------------------------------------------------------
ROPAC = "https://ropac.net"
_ROPAC_CITY = {"paris": "FR", "pantin": "FR", "marais": "FR", "london": "GB", "ely house": "GB", "salzburg": "AT",
               "villa kast": "AT", "seoul": "KR", "fort hill": "KR", "milan": "IT", "milano": "IT"}


def _ropac_country(loc):
    t = (loc or "").lower()
    for k, cc in _ROPAC_CITY.items():
        if k in t:
            return cc
    return _country(loc)


def _ropac(ctx, org):
    pages = [(f"{ROPAC}/exhibitions/", "exhibitions landing")]
    for u, loc in pages:
        r = ctx.fetch(u)
        _ropac_list(ctx, org, r, loc)
    skip, cap = 0, (20 if ctx.mode == "initial" else 1)
    for i in range(cap):
        u = f"{ROPAC}/exhibitions/all/past/" + (f"?skip={skip}" if skip else "")
        try:
            r = ctx.fetch(u)
        except FetchError as e:
            ctx.note(f"{u}: {e}")
            break
        n, oldest = _ropac_list(ctx, org, r, f"past skip={skip}")
        if not n or (oldest and oldest < HISTORY_FLOOR):
            break
        skip += 30
    ctx.note(f"Ropac: landing (current+forthcoming) + past list paged to skip={skip} (archive goes back further)")


def _ropac_list(ctx, org, resp, locator):
    s = BeautifulSoup(resp.text, "lxml")
    n, oldest, seen = 0, None, set()
    for a in s.find_all("a", href=re.compile(r"^/exhibitions/\d+-")):
        head = a.select_one(".heading_title")
        subn = a.select_one(".subtitle")
        dnode = a.select_one(".dates_inner")
        if not (head or subn) or not dnode or a["href"] in seen:
            continue
        seen.add(a["href"])
        ctx.count("fetched")
        # solo cards: heading_title = artist, subtitle = show title; group cards carry only the subtitle (show title)
        heading = clean_text((head or subn).get_text(" "))
        sub = clean_text(subn.get_text(" ")) if (head and subn) else None
        loc = clean_text(a.select_one(".location").get_text(" ")) if a.select_one(".location") else None
        # the date block may append an opening line ("... 2026 Opening Wednesday 21 October, 6:30—8:30pm")
        date_line = re.split(r"\s+Opening\b", clean_text(dnode.get_text(" ")))[0]
        start, sp, end, ep = _dates(date_line)
        cc = _ropac_country(loc)
        url = urllib.parse.urljoin(ROPAC, a["href"])
        key = re.match(r"^/exhibitions/(\d+)-", a["href"]).group(1)
        title = heading + (f": {sub}" if sub else "")
        solo = bool(sub) and not re.search(r"[/&,]| and ", heading)
        ev = ctx.evidence(resp, locator=f"{locator} {a['href']}", excerpt=f"{date_line} | {loc}")
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
            subtype=classify_subtype(title, 1 if solo else None), title=title, title_lang=None, organizer_entity_id=org,
            city=loc, country_code=cc, start_date=start, start_precision=sp, end_date=end, end_precision=ep,
            date_text=date_line, url=url, evidence_id=ev, parser_version=PARSER_VERSION)
        if solo:
            _artist(ctx, eid, heading, ev, "list_markup", "medium")
        _review_region(ctx, eid, cc, loc)
        ctx.count("parsed")
        n += 1
        if start and (oldest is None or start < oldest):
            oldest = start
    ctx.con.commit()
    return n, oldest


# -- Lisson Gallery -----------------------------------------------------------------------------------------------
LISSON = "https://lisson.com"
_LISSON_CITY = {
    "london": ("London", "GB"), "new york": ("New York", "US"), "los angeles": ("Los Angeles", "US"),
    "shanghai": ("Shanghai", "CN"), "venice": ("Venice", "IT"), "manchester": ("Manchester", "GB"),
    "menerbes": ("Ménerbes", "FR"),
}


def _lisson(ctx, org):
    listing = ctx.fetch(f"{LISSON}/exhibitions")
    page = BeautifulSoup(listing.text, "lxml")
    seen, oldest, past_count = set(), None, 0
    cutoff = (now_kst().date() - timedelta(days=30)).isoformat()
    for article in page.find_all("article"):
        link = next((a for a in article.find_all("a", href=True)
                     if re.fullmatch(r"/exhibitions/[^/]+", a["href"])), None)
        if not link:
            continue
        href = link["href"]
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        ctx.count("fetched")
        section = article.find_parent("section")
        section_heading = clean_text(section.find(["h2", "h3"]).get_text(" ")) if section and section.find(["h2", "h3"]) else ""
        is_past = section_heading.casefold() == "past exhibitions"
        if is_past:
            past_count += 1
        if ctx.mode == "incremental":
            existing = ctx.con.execute(
                "SELECT end_date FROM events WHERE source_id=? AND source_event_key=?", (ctx.source_id, slug)
            ).fetchone()
            end_date = existing["end_date"] if existing else None
            if end_date and len(end_date) >= 10 and end_date[:10] < cutoff:
                continue
        card_title_node = article.find("h3")
        card_title = clean_text(card_title_node.get_text(" ")) if card_title_node else None
        card_date_node = article.find("time")
        card_date = clean_text(card_date_node.get_text(" ")) if card_date_node else None
        paragraphs = [clean_text(p.get_text(" ")) for p in article.find_all("p")]
        loc = None
        for node in article.find_all("div"):
            classes = node.get("class") or []
            if any(value.startswith("w-col-2") for value in classes):
                loc = clean_text(node.get_text(" "))
                if loc:
                    break
        if not loc and is_past:
            if any(value.casefold() == "museum" for value in paragraphs):
                loc = card_title if _lisson_place(card_title) else None
            else:
                place = next((value for value in paragraphs if re.search(r"\b20\d{2}\b", value)), None)
                if place:
                    loc = re.sub(r"\s*,?\s*20\d{2}\b.*$", "", place).strip(" ,")
        if not loc:
            loc = next((value for value in paragraphs if _lisson_place(value)), None)
        loc = clean_text(loc) or None

        try:
            detail = ctx.fetch(urllib.parse.urljoin(LISSON, href))
        except FetchError as e:
            ctx.note(f"detail {slug}: {e}")
            ctx.count("detail_errors")
            continue
        detail_soup = BeautifulSoup(detail.text, "lxml")
        main = detail_soup.find("main") or detail_soup
        event_data = {}
        for obj in jsonld_objects(detail.text):
            types = obj.get("@type") or []
            if isinstance(types, str):
                types = [types]
            if "ExhibitionEvent" in types:
                event_data = obj
                break
        h1 = main.find("h1")
        title = clean_text(event_data.get("name"))
        if not title and h1:
            title = clean_text(h1.get_text(" "))
        title = title or card_title
        if not title:
            continue
        data_start, data_end = event_data.get("startDate"), event_data.get("endDate")
        start, sp = _lisson_iso_date(data_start)
        end, ep = _lisson_iso_date(data_end)
        if not start and not end:
            start, sp, end, ep = _dates(card_date)
        if not start and not end:
            year_match = next((re.search(r"\b20\d{2}\b", value) for value in paragraphs
                               if re.search(r"\b20\d{2}\b", value)), None)
            year = year_match.group(0) if year_match else None
            if year:
                start = end = year
                sp = ep = "year"
        date_text = card_date if card_date and re.search(r"\b20\d{2}\b", card_date) else (
            " – ".join(value for value in (data_start, data_end) if value) or card_date)
        if not loc:
            candidate_loc = _lisson_json_location(event_data.get("location"))
            if candidate_loc and candidate_loc.casefold() != "lisson gallery":
                loc = candidate_loc
        cc = _lisson_country(loc, title, href)
        city = _lisson_city(loc, title, href)
        artists = _lisson_detail_artists(main)
        artist_method = "list_markup"
        if not artists:
            ignored = {"explore", "gallery", "museum"}
            artists = [value for value in paragraphs if value.casefold() not in ignored
                       and not re.search(r"\b20\d{2}\b", value) and not _lisson_place(value)
                       and value.casefold() != (card_title or "").casefold()]
            artist_method = "list_markup"
        if not artists:
            prefix = split_title_artist(title)
            if prefix:
                artists, artist_method = [prefix], "title_pattern"
        artists = list(dict.fromkeys(name for name in (clean_text(x) for x in artists) if name))
        ev = ctx.evidence(detail, locator="JSON-LD ExhibitionEvent / exhibition detail", excerpt=date_text)
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug, event_type="exhibition",
            subtype=classify_subtype(title, len(artists) or None), title=title, title_lang=None,
            organizer_entity_id=org, city=city, country_code=cc,
            start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
            url=detail.url, evidence_id=ev, parser_version=PARSER_VERSION, description_excerpt=loc)
        for name in artists:
            _artist(ctx, eid, name, ev, artist_method, "medium" if artist_method == "title_pattern" else "high")
        _lisson_record_image_rights(ctx, detail, detail_soup, eid)
        _review_region(ctx, eid, cc, loc)
        ctx.count("parsed")
        if start and (oldest is None or start < oldest):
            oldest = start
    ctx.con.commit()
    ctx.note(f"Lisson: current/upcoming listings and {past_count} Past Exhibitions cards; no archive pagination "
             f"present, oldest parsed start={oldest or 'unknown'}")


def _lisson_iso_date(value):
    if not value:
        return None, None
    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", str(value))
    if not match:
        return None, None
    year, month, day = match.groups()
    precision = "day" if day else "month" if month else "year"
    return "-".join(part for part in (year, month, day) if part), precision


def _lisson_place(value):
    text = clean_text(value).lower()
    return any(city in text for city in _LISSON_CITY) or bool(_country(text))


def _lisson_json_location(location):
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return clean_text(location) or None
    address = location.get("address") or {}
    if isinstance(address, dict):
        parts = [address.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
        if any(parts):
            return clean_text(", ".join(str(part) for part in parts if part))
    return clean_text(location.get("name")) or None


def _lisson_country(loc, title, href):
    cc = _country(loc)
    if cc:
        return cc
    text = (loc or "").lower()
    for city, (_, code) in _LISSON_CITY.items():
        if city in text:
            return code
    cc = _country(title)
    if cc:
        return cc
    if re.search(r"\bin\s+venice(?:\s+20\d{2})?\b", title or "", re.I):
        return "IT"
    path = urllib.parse.urlsplit(href or "").path.lower()
    for city, (_, code) in _LISSON_CITY.items():
        slug = city.replace(" ", "-")
        if re.search(rf"(?:^|/|-)\b{re.escape(slug)}\b(?:-|/|$)", path):
            return code
    return None


def _lisson_city(loc, title, href):
    for value in (loc, title):
        text = (value or "").lower()
        for city, (name, _) in _LISSON_CITY.items():
            if city in text:
                return name
    path = urllib.parse.urlsplit(href or "").path.lower()
    for city, (name, _) in _LISSON_CITY.items():
        slug = city.replace(" ", "-")
        if re.search(rf"(?:^|/|-)\b{re.escape(slug)}\b(?:-|/|$)", path):
            return name
    return None


def _lisson_detail_artists(main):
    for heading in main.find_all(["h2", "h3"]):
        if clean_text(heading.get_text(" ")).casefold() != "exhibition artists":
            continue
        result = []
        for node in heading.find_all_next(["h2", "h3"]):
            if node.name == "h2":
                break
            name = clean_text(node.get_text(" "))
            if name:
                result.append(name)
        return result
    return []


def _lisson_record_image_rights(ctx, resp, page, event_id):
    for image in page.find_all("img"):
        source = image.get("data-src") or image.get("src") or image.get("data-lazy-src") or image.get("data-srcset") or image.get("srcset")
        if not source or source.startswith("data:"):
            continue
        if "," in source:
            source = source.split(",", 1)[0].split()[0]
        else:
            source = source.split()[0]
        db.add_image_rights(
            ctx.con, source_id=ctx.source_id, usage_status="unknown",
            basis="Lisson page states no open image licence; URL recorded from HTML only, image not downloaded",
            page_url=resp.url, image_url=urllib.parse.urljoin(resp.url, source), event_id=event_id)

