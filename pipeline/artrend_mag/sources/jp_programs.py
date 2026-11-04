"""Japanese public programmes: Tokyo Arts and Space (TOKAS) exhibitions, open-call selections and residencies.

Public HTML archive pages (per-year index pages + detail pages). Raw HTML kept internally as evidence only.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import db
from ..config import now_kst
from ..http import Blocked, FetchError
from ._common import classify_subtype, clean_text, parse_date_range, soup
from .jp_museums import _mk, _needs_detail

PARSER_VERSION = "jp_programs-1"
TOKAS = "https://www.tokyoartsandspace.jp"
_TOKAS_TERMS = ("TOKAS Site Policy: copyright in site content belongs to TOKAS or information providers; use beyond "
                "private use and reproduction/publication/transmission without permission prohibited")

SOURCES = [
    dict(source_id="tokas", blueprint_data_id="D28", blueprint_org_id="O17",
         name="Tokyo Arts and Space (TOKAS) — exhibitions, open calls, residencies",
         owner_group="Tokyo Metropolitan Foundation for History and Culture", source_kind="residency",
         region_scope="JP", country_codes="JP", access_method="html", base_url=TOKAS,
         entry_url=f"{TOKAS}/en/exhibition/index/index.html", terms_url=f"{TOKAS}/en/policy.html",
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms=_TOKAS_TERMS + "; no clause on automated access",
         st_image_terms="images copyright TOKAS/artists; no reuse without permission", max_requests=220),
    dict(source_id="yokohama_triennale", blueprint_data_id="D19", blueprint_org_id=None, name="Yokohama Triennale — edition artists",
         owner_group="Organizing Committee for Yokohama Triennale", source_kind="biennial", region_scope="JP",
         country_codes="JP", access_method="html", base_url="https://www.yokohamatriennale.jp",
         entry_url="https://www.yokohamatriennale.jp/", terms_url="https://www.yokohamatriennale.jp/terms/",
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="Terms (利用規約): copyright in site text/images belongs to the committee or licensors; use "
                             "(reproduction, alteration, distribution) beyond legally permitted private use prohibited",
         st_image_terms="images copyright committee/rights holders; no reuse beyond private use", max_requests=10),
    dict(source_id="art_fair_tokyo", blueprint_data_id="D24", blueprint_org_id=None, name="Art Fair Tokyo — editions & exhibitors",
         owner_group="aTOKYO Co., Ltd.", source_kind="fair", region_scope="JP", country_codes="JP",
         access_method="html", base_url="https://artfairtokyo.com", entry_url="https://artfairtokyo.com/exhibitors",
         terms_url="https://artfairtokyo.com/ (Terms of Use modal, last updated 2016-02-17)",
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="Terms of Use (2016) cover account/service use; no explicit clause on automated access; "
                             "site footer: COPYRIGHT aTOKYO Co., Ltd. ALL RIGHTS RESERVED",
         st_image_terms="all rights reserved (footer); artwork images copyright artists/galleries", max_requests=10),
]

_WD = re.compile(r"\s*\((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^)]*\)", re.I)


def collect(ctx):
    if ctx.source_id == "tokas":
        return _tokas(ctx)
    if ctx.source_id == "yokohama_triennale":
        return _yokohama(ctx)
    if ctx.source_id == "art_fair_tokyo":
        return _aft(ctx)
    raise ValueError(ctx.source_id)


def _years(ctx):
    y = now_kst().year
    return list(range(y, 2022, -1)) if ctx.mode == "initial" else [y]


def _tokas(ctx):
    con = ctx.con
    org = db.ensure_entity(con, entity_type="institution", name="Tokyo Arts and Space", namespace=f"src:{ctx.source_id}",
                           id_value="tokas", lang="en", source_id=ctx.source_id, official_url=f"{TOKAS}/en/")
    # ---- exhibitions / performances: current+upcoming listing and per-year archive indexes
    items = {}
    r = ctx.fetch(f"{TOKAS}/en/exhibition/index/index.html")
    for box in soup(r.text).select(".exhibition-block-box"):
        a = box.select_one("p.link a[href]")
        if not a:
            continue
        url = urllib.parse.urljoin(r.final_url, a["href"])
        dd = box.find("dt", string=re.compile("Date"))
        items.setdefault(url, dict(title=clean_text(box.h4.get_text(" ")) if box.h4 else None,
                                   date_text=clean_text(dd.find_next("dd").get_text(" ")) if dd else None))
    ctx.count("fetched", len(items))
    for y in _years(ctx):
        try:
            r = ctx.fetch(f"{TOKAS}/en/archive/exhibition/{y}/index.html")
        except FetchError as e:
            ctx.note(f"archive {y}: {e}")
            continue
        links = soup(r.text).select("#contentsR a.archive-thumblist[href]")
        ctx.count("fetched", len(links))
        for a in links:
            url = urllib.parse.urljoin(r.final_url, a["href"])
            p = a.select_one("dd p")
            items.setdefault(url, dict(title=clean_text(a.h4.get_text(" ")) if a.h4 else None,
                                       date_text=clean_text(p.get_text(" ")) if p else None))
    ctx.note("TOKAS: per-year archive indexes exist back to 2001; initial mode reads 2023..current year + "
             "current/upcoming listing; residency archive same years")
    for url, it in items.items():
        key = re.search(r"-(\d+)\.html$", url)
        key = f"ex-{key.group(1)}" if key else url
        if not _needs_detail(ctx, key):
            continue
        try:
            d = ctx.fetch(url)
        except Blocked:
            raise
        except FetchError as e:
            ctx.note(f"detail error {url}: {e}")
            ctx.count("detail_errors")
            continue
        _tokas_exhibition(ctx, org, key, url, it, d)
    con.commit()
    # ---- residency archive
    for y in _years(ctx):
        try:
            r = ctx.fetch(f"{TOKAS}/en/archive/residence/{y}/index.html")
        except FetchError as e:
            ctx.note(f"residence archive {y}: {e}")
            continue
        _tokas_residency_index(ctx, org, r)
    con.commit()


def _tokas_exhibition(ctx, org, key, url, it, d):
    s = soup(d.text)
    box = s.select_one(".container-box") or s
    labels = [clean_text(x.get_text(" ")) for x in box.select("div.label")]
    h2 = box.select_one(".h2-block h2")
    title = clean_text(h2.get_text(" ")) if h2 else it["title"]
    sub = box.select_one(".h2-block p")
    series = clean_text(sub.get_text(" ")) if sub else ""
    rows = {clean_text(th.get_text(" ")): td for th, td in
            ((tr.find("th"), tr.find("td")) for tr in box.select("table tr")) if th and td}
    date_text = clean_text(rows["Period"].get_text(" ")) if "Period" in rows else it["date_text"]
    venue = clean_text(rows["Venue"].get_text(" ")) if "Venue" in rows else None
    start, sp, end, ep = parse_date_range(_WD.sub("", date_text or ""))
    if start is None and it.get("date_text"):
        date_text = it["date_text"]
        start, sp, end, ep = parse_date_range(_WD.sub("", date_text))
    creators = []
    hc = box.find(id="creator")
    if hc is not None:
        p = hc.find_next_sibling("p")
        if p is not None:
            creators = [(clean_text(a.get_text(" ")), a["href"]) for a in p.select("a[href*='/creator/']")]
    blob = " ".join(labels + [title or "", series])
    if re.search(r"OPEN SITE|TOKAS[- ]Emerging", blob, re.I):
        etype, subtype = "open_call_selection", None
    elif re.search(r"Open Studio", blob, re.I):
        etype, subtype = "program", None
    else:
        etype = "exhibition"
        subtype = classify_subtype(title, len(creators) or None)
    on_site = bool(venue and re.search(r"Tokyo Arts and Space|TOKAS", venue))
    city, cc = ("Tokyo", "JP") if (on_site or venue is None) else (None, None)
    ev = ctx.evidence(d, locator="table th=Period", excerpt=date_text)
    excerpt = " | ".join(x for x in (", ".join(labels), series, f"Venue: {venue}" if venue else "") if x) or None
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type=etype, subtype=subtype,
        title=title, title_lang="en", organizer_entity_id=org, city=city, country_code=cc,
        start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text, url=url,
        description_excerpt=excerpt, parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    if cc is None:
        db.add_review(ctx.con, "region", "events", eid, "venue country unknown", f"venue: {venue}")
    role = "resident" if etype == "program" else "artist"  # open-call winners exhibit as artists
    for name, href in creators:
        m = re.search(r"/creator/index/[^/]+/(\d+)\.html", href)
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name,
                               namespace="tokas_creator" if m else f"src:{ctx.source_id}",
                               id_value=m.group(1) if m else None, source_id=ctx.source_id, evidence_id=ev,
                               official_url=urllib.parse.urljoin(TOKAS, href))
        db.add_participant(ctx.con, eid, ent, role, name, ev, "list_markup")
    img = box.select_one(".item-image img[src]")
    if img is not None:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url,
                            image_url=urllib.parse.urljoin(TOKAS, img["src"]), usage_status="unknown", basis=_TOKAS_TERMS)


_PERIOD = re.compile(r"(\d{4})\.(\d{1,2})(?:\.(\d{1,2}))?\s*[-–~]\s*(?:(\d{4})\.)?(\d{1,2})(?:\.(\d{1,2}))?")


def _month_range(text):
    m = _PERIOD.search(text or "")
    if not m:
        return None, None, None, None
    y1, m1, d1, y2, m2, d2 = m.groups()
    y2 = y2 or y1

    def fmt(y, mo, d):
        if d:
            v = _mk(y, mo, d)
            return v, ("day" if v else None)
        return f"{int(y):04d}-{int(mo):02d}", "month"
    s, sp = fmt(y1, m1, d1)
    e, ep = fmt(y2, m2, d2)
    return s, sp, e, ep


def _tokas_residency_index(ctx, org, r):
    s = soup(r.text)
    root = s.select_one("#contentsR")
    if root is None:
        return
    program = None
    n = 0
    for el in root.find_all(["h3", "a"], recursive=False):
        if el.name == "h3":
            program = clean_text(el.get_text(" "))
            continue
        if "archive-thumblist" not in (el.get("class") or []):
            continue
        n += 1
        url = urllib.parse.urljoin(r.final_url, el["href"])
        m = re.search(r"-(\d+)\.html$", url)
        key = f"res-{m.group(1)}" if m else url
        name = clean_text(el.h4.get_text(" ")) if el.h4 else None
        if not name:
            continue
        p = el.select_one("dd p")
        txt = clean_text(p.get_text(" ")) if p else ""
        pm = re.search(r"Period[：:]\s*(.*?)(?:City[：:]|$)", txt)
        cm = re.search(r"City[：:]\s*(.*)$", txt)
        period = clean_text(pm.group(1)) if pm else None
        city = clean_text(cm.group(1)) if cm else None
        start, sp, end, ep = _month_range(period)
        cc = "JP" if city and re.fullmatch(r"Tokyo", city, re.I) else None
        ev = ctx.evidence(r, locator=f"#contentsR a[href$='{url.rsplit('/', 1)[-1]}']", excerpt=txt)
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="residency", subtype=None,
            title=f"{program}: {name}" if program else name, title_lang="en", organizer_entity_id=org,
            city=city, country_code=cc, start_date=start, start_precision=sp, end_date=end, end_precision=ep,
            date_text=period, url=url, description_excerpt=program, parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        if cc is None:
            db.add_review(ctx.con, "region", "events", eid, "venue country unknown", f"residency city: {city}")
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=f"src:{ctx.source_id}",
                               source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "resident", name, ev, "list_markup")
    ctx.count("fetched", n)


# --------------------------------------------------------------------------------------------- Yokohama Triennale
YT = "https://www.yokohamatriennale.jp"


def _yokohama(ctx):
    org = db.ensure_entity(ctx.con, entity_type="biennial", name="Yokohama Triennale", namespace=f"src:{ctx.source_id}",
                           id_value="yokohama_triennale", lang="en", source_id=ctx.source_id, official_url=f"{YT}/")
    home = ctx.fetch(f"{YT}/")
    # newest edition = newest entry in the homepage's edition archive menu (/archive/YYYY/); its site lives at /YYYY/
    years = sorted({int(y) for y in re.findall(r'href="(?:https://www\.yokohamatriennale\.jp)?/(?:archive/)?(20\d\d)/',
                                                home.text)}, reverse=True)
    if not years:
        ctx.note("no edition site link found on homepage")
        return
    year = years[0]
    r = ctx.fetch(f"{YT}/{year}/en/artists")
    s = soup(r.text)
    tag = s.select_one("p.tagline")
    date_text = clean_text(tag.get_text(" ")) if tag else None
    start, sp, end, ep = parse_date_range(_WD.sub("", re.sub(r"[（(][^)）]*[)）]", "", date_text or "")))
    h = s.select_one("a.brand[title]")
    title = clean_text(h["title"]) if h else f"Yokohama Triennale {year}"
    ev = ctx.evidence(r, locator="p.tagline", excerpt=date_text)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=str(year), event_type="biennial_edition",
        subtype=None, title=title, title_lang="en", organizer_entity_id=org, city="Yokohama", country_code="JP",
        start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
        url=f"{YT}/{year}/en/", parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    rows = s.select("details.list-details summary")
    ctx.count("fetched", len(rows))
    for sm in rows:
        a = sm.select_one("a[href]")
        name = clean_text(sm.get_text(" "))
        if not name:
            continue
        slug = a["href"].rstrip("/").rsplit("/", 1)[-1] if a else None
        etype = "group" if re.search(r"group|collective|project|＆|&|studio|lab\b", name, re.I) else "person"
        ent = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"yokohama_triennale_{year}_artist",
                               id_value=slug, source_id=ctx.source_id, evidence_id=ev,
                               official_url=urllib.parse.urljoin(r.final_url, a["href"]) if a else None)
        db.add_participant(ctx.con, eid, ent, "artist", name, ev, "list_markup")
    ctx.con.commit()
    ctx.note(f"Yokohama Triennale: latest edition with an artist list = {year} (newest edition site linked from "
             f"homepage); {len(rows)} artists from /{year}/en/artists; earlier editions not collected")


# --------------------------------------------------------------------------------------------- Art Fair Tokyo
AFT = "https://artfairtokyo.com"


def _aft(ctx):
    org = db.ensure_entity(ctx.con, entity_type="fair", name="Art Fair Tokyo", namespace=f"src:{ctx.source_id}",
                           id_value="art_fair_tokyo", lang="en", source_id=ctx.source_id, official_url=f"{AFT}/")
    home = ctx.fetch(f"{AFT}/")
    ht = clean_text(soup(home.text).get_text(" "))
    # upcoming edition headline, e.g. 'ART FAIR TOKYO 21 March 12th Fri – 14th Sun, 2027'
    m = re.search(r"ART FAIR TOKYO (\d{2})\s+((?:January|February|March|April|May|June|July|August|September|October|"
                  r"November|December)\s+\d{1,2}\w*\s+\w+\s*[–-]\s*\d{1,2}\w*\s+\w+,\s*\d{4})", ht)
    if m:
        n, date_text = m.group(1), m.group(2)
        norm = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", date_text)
        norm = re.sub(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\b", "", norm)
        norm = re.sub(r"^(\w+)\s+(\d+)\s*[–-]\s*(\d+)", r"\1 \2 – \1 \3", norm.strip())
        start, sp, end, ep = parse_date_range(re.sub(r"\s+,", ",", norm))
        ev = ctx.evidence(home, locator="header edition headline", excerpt=f"ART FAIR TOKYO {n} {date_text}")
        db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"aft{n}", event_type="fair_edition",
                        title=f"ART FAIR TOKYO {n}", title_lang="en", organizer_entity_id=org, city="Tokyo",
                        country_code="JP", start_date=start, start_precision=sp, end_date=end, end_precision=ep,
                        date_text=date_text, url=f"{AFT}/", parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
    # exhibitor list; the page itself does not name the edition, so it is attached to edition N only when the
    # site's own 'ART FAIR TOKYO N Results' block states the same exhibitor count
    r = ctx.fetch(f"{AFT}/exhibitors")
    s = soup(r.text)
    rows = s.select("span.exhibitor-name a[href]")
    ctx.count("fetched", len(rows))
    about = None
    res = re.search(r"ART FAIR TOKYO (\d{2}) Results\s+(\d+)\s+Exhibitors", ht)
    if not res:
        try:
            about = ctx.fetch(f"{AFT}/about")
            res = re.search(r"ART FAIR TOKYO (\d{2}) Results\s+(\d+)\s+Exhibitors", clean_text(soup(about.text).get_text(" ")))
        except FetchError as e:
            ctx.note(f"about page: {e}")
    if not res or int(res.group(2)) != len(rows):
        ctx.note(f"exhibitor list ({len(rows)}) could not be matched to an edition; not stored")
        ctx.con.commit()
        return
    n = res.group(1)
    rev = ctx.evidence(about or home, locator="section.about-stats", excerpt=f"ART FAIR TOKYO {n} Results {res.group(2)} Exhibitors")
    ev = ctx.evidence(r, locator="span.exhibitor-name a", excerpt=f"{len(rows)} exhibitors")
    eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"aft{n}", event_type="fair_edition",
                          title=f"ART FAIR TOKYO {n}", title_lang="en", organizer_entity_id=org, city="Tokyo",
                          country_code="JP", url=f"{AFT}/exhibitors", parser_version=PARSER_VERSION, evidence_id=rev)
    ctx.count("parsed")
    for a in rows:
        name = clean_text(a.get_text(" "))
        mm = re.search(r"/exhibitors/(\d+)", a["href"])
        cat = a.find_parent("span").find_next_sibling("span", class_="category-name")
        ent = db.ensure_entity(ctx.con, entity_type="gallery", name=name, namespace="artfairtokyo_exhibitor",
                               id_value=mm.group(1) if mm else None, source_id=ctx.source_id, evidence_id=ev,
                               official_url=urllib.parse.urljoin(AFT, a["href"]))
        db.add_participant(ctx.con, eid, ent, "exhibitor", f"{name} ({clean_text(cat.get_text())})" if cat else name,
                           ev, "list_markup")
    ctx.con.commit()
    ctx.note(f"Art Fair Tokyo: upcoming edition headline from homepage; {len(rows)} exhibitors from /exhibitors "
             f"attached to ART FAIR TOKYO {n} (count matches the site's 'Results' block); edition dates for past "
             "editions are not stated on these pages")
