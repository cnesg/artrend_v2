"""UK institutions: Tate (What's on + Turner Prize), Whitechapel Gallery, Serpentine Galleries."""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from .. import db
from ._common import clean_text, jsonld_objects, parse_date_range
from . import eu_common as C

PARSER_VERSION = "eu_museums_uk-2"

TATE_TERMS = "https://www.tate.org.uk/about-us/policies-and-procedures/website-terms-use"
SOURCES = [
    dict(source_id="tate_whatson", blueprint_data_id="D14", blueprint_org_id="O28", name="Tate — What's on (exhibitions)",
         owner_group="Tate", source_kind="museum", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url="https://www.tate.org.uk", entry_url="https://www.tate.org.uk/whats-on", terms_url=TATE_TERMS,
         text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html)",
         st_collection_terms="Tate terms: content only for personal non-commercial use; Tate-copyright content may be reproduced for non-commercial research/private study/criticism & review; robots allows / except /search",
         st_image_terms="images credited per item (© artist/lender/Tate); no open licence on exhibition imagery",
         max_requests=150),
    dict(source_id="tate_turner_prize", blueprint_data_id="D30", blueprint_org_id="O28", name="Tate — Turner Prize",
         owner_group="Tate", source_kind="award", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url="https://www.tate.org.uk", entry_url="https://www.tate.org.uk/art/turner-prize", terms_url=TATE_TERMS,
         text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html)",
         st_collection_terms="Tate terms: content only for personal non-commercial use; Tate-copyright content may be reproduced for non-commercial research/private study/criticism & review; robots allows / except /search",
         st_image_terms="images credited per item; no open licence", max_requests=40),
    dict(source_id="whitechapel_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Whitechapel Gallery — Exhibitions",
         owner_group="Whitechapel Gallery", source_kind="museum", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url="https://www.whitechapelgallery.org", entry_url="https://www.whitechapelgallery.org/exhibitions/",
         terms_url="https://www.whitechapelgallery.org/terms-conditions/", text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML; exhibitions feed returned 404)",
         st_collection_terms="opened terms cover ticket sales and artwork sale; no general automated-collection permission or reuse licence found; robots.txt allows public paths",
         st_image_terms="images individually credited; no blanket open licence stated", max_requests=160),
    dict(source_id="serpentine_whatson", blueprint_data_id=None, blueprint_org_id=None, name="Serpentine Galleries — What's on",
         owner_group="Serpentine", source_kind="museum", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url="https://www.serpentinegalleries.org", entry_url="https://www.serpentinegalleries.org/whats-on/",
         terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML; exhibition archive exposed)",
         st_collection_terms="terms not located; robots.txt allows public programme and archive paths",
         st_image_terms="images individually credited; no blanket open licence stated", max_requests=40),
]

TATE_VENUES = {
    "tate-modern": ("Tate Modern", "London"), "tate-britain": ("Tate Britain", "London"),
    "tate-liverpool": ("Tate Liverpool", "Liverpool"), "tate-liverpool--riba-north": ("Tate Liverpool + RIBA North", "Liverpool"),
    "tate-st-ives": ("Tate St Ives", "St Ives"), "towner-eastbourne": ("Towner Eastbourne", "Eastbourne"),
    "bradford": ("Cartwright Hall Art Gallery", "Bradford"), "bankside": ("Bankside", "London"),
    "oriel-y-parc": ("Oriel y Parc", "St Davids"), "perth-museum": ("Perth Museum", "Perth"),
    "atkinson-southport": ("The Atkinson", "Southport"),
}
UK_NO_CITY = {"national-tour"}  # ARTIST ROOMS / Grenfell national tours: UK-wide, city varies
TATE_IMG = "Tate image credits per item (© artist / lender / Tate Photography); no open licence stated"


def collect(ctx):
    if ctx.source_id == "tate_whatson":
        return _tate(ctx)
    if ctx.source_id == "tate_turner_prize":
        return _turner(ctx)
    if ctx.source_id == "whitechapel_exhibitions":
        return _whitechapel(ctx)
    if ctx.source_id == "serpentine_whatson":
        return _serpentine(ctx)
    raise ValueError(ctx.source_id)


def _card_for_date(a, date_re):
    node = a
    for _ in range(8):
        text = clean_text(node.get_text(" ")) if hasattr(node, "get_text") else ""
        if date_re.search(text):
            return node, text
        node = getattr(node, "parent", None)
        if node is None:
            break
    return a, clean_text(a.get_text(" "))


def _img_url(card, base):
    node = card
    img = None
    for _ in range(5):
        img = node.find("img") if hasattr(node, "find") else None
        if img is not None:
            break
        node = getattr(node, "parent", None)
        if node is None:
            break
    src = (img.get("src") or img.get("data-src")) if img else None
    return urllib.parse.urljoin(base, src) if src and not src.startswith("data:") else None


def _store_uk_exhibition(ctx, resp, *, url, title, date_text, dates, org, card, locator, img_basis,
                         artists=None):
    ev = ctx.evidence(resp, locator=locator, excerpt=(date_text or title)[:300])
    return C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=org, city="London",
                              country="GB", date_text=date_text, dates_tuple=dates, artists=artists,
                              image=_img_url(card, resp.url), image_basis=img_basis)


def _whitechapel(ctx):
    base = "https://www.whitechapelgallery.org"
    org = C.org(ctx, "Whitechapel Gallery", url=base)
    records = {}
    page = 1
    max_page = 40 if ctx.mode == "initial" else 2
    while page <= max_page:
        r = ctx.fetch(base + "/exhibitions/", params=None if page == 1 else {"past": page})
        s = BeautifulSoup(r.text, "lxml")
        new = 0
        for a in s.select('a[href*="/exhibitions/"]'):
            url = urllib.parse.urljoin(base, a["href"])
            if url.rstrip("/") == base + "/exhibitions" or "?past=" in url:
                continue
            card, text = _card_for_date(a, re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,2}\s+[A-Za-z]+\s*[-–]", re.I))
            heading = card.find(["h2", "h3", "h4"])
            title = clean_text(heading.get_text(" ") if heading else a.get_text(" "))
            if not title or title.lower() in ("exhibitions", "more"):
                continue
            date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]+\s+(?:\d{4}\s*)?[-–]\s*(?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4}\b|\b(?:19|20)\d{2}\b", text, re.I)
            date_text = clean_text(date_match.group(0)) if date_match else None
            dates = C.range_dates(date_text) if date_text and re.search(r"[-–]", date_text) else parse_date_range(date_text)
            records[url] = (r, title, date_text, dates, card)
            new += 1
        ctx.con.commit()
        if not s.select_one('a[href*="past="]') or ctx.mode != "initial":
            break
        oldest = min((m.group(0) for m in re.finditer(r"\b(?:19|20)\d{2}\b", clean_text(s.get_text(" ")))), default="9999")
        if oldest < "2023" or not new:
            break
        page += 1
    ctx.count("fetched", len(records))
    for url, (r, title, date_text, dates, card) in records.items():
        if not C.needs_detail(ctx, url):
            continue
        # Archive cards show only the calendar year; detail pages add the full exhibition dates.
        if date_text and re.fullmatch(r"(?:19|20)\d{2}", date_text):
            detail = C.try_fetch(ctx, url)
            if detail is not None:
                s_detail = BeautifulSoup(detail.text, "lxml")
                h1 = s_detail.find("h1")
                title = clean_text(h1.get_text(" ")) if h1 else title
                date_re = re.compile(r"\b\d{1,2}\s+[A-Za-z]+\s+(?:\d{4}\s*)?[-–]\s*(?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4}\b", re.I)
                match = next((date_re.search(clean_text(str(node))) for node in s_detail.find_all(string=True)
                              if date_re.search(clean_text(str(node)))), None)
                if match:
                    date_text = clean_text(match.group(0))
                    dates = C.range_dates(date_text)
                ev = ctx.evidence(detail, locator="exhibition detail date line", excerpt=(date_text or title)[:300])
                C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=org, city="London", country="GB",
                                   date_text=date_text, dates_tuple=dates, image=C.og(detail.text, "image") or _img_url(card, detail.url),
                                   image_basis="Whitechapel exhibition image; individual copyright applies, no open licence stated")
                ctx.con.commit()
                continue
        _store_uk_exhibition(ctx, r, url=url, title=title, date_text=date_text, dates=dates, org=org, card=card,
                             locator=f"exhibitions listing {url}", img_basis="Whitechapel exhibition image; individual copyright applies, no open licence stated")
        ctx.con.commit()
    ctx.note(f"public exhibition listing/archive fetched {page} page(s); card dates are day-precision when printed; year-only archive cards trigger permitted detail lookups. Initial mode walks archive pagination through 2023 where the listings expose years; there is no feed.")
    ctx.con.commit()


def _serpentine(ctx):
    base = "https://www.serpentinegalleries.org"
    org = C.org(ctx, "Serpentine Galleries", url=base)
    pages = [base + "/whats-on/"]
    if ctx.mode == "initial":
        pages.append(base + "/whats-on/archive/year/2026-2020")
    records = {}
    for page_url in pages:
        r = ctx.fetch(page_url)
        s = BeautifulSoup(r.text, "lxml")
        for a in s.select('a[href*="/whats-on/"]'):
            url = urllib.parse.urljoin(base, a["href"])
            if (url.rstrip("/") == (base + "/whats-on").rstrip("/") or "/whats-on/archive" in url
                    or urllib.parse.urlsplit(url).query):
                continue
            card, text = _card_for_date(a, re.compile(r"\b\d{1,2}\s+[A-Za-z]+\b.*(?:[-–]|to).*\b\d{4}\b", re.I))
            if not re.search(r"\b\d{1,2}\s+[A-Za-z]+\b.*(?:[-–]|to).*\b\d{4}\b", text, re.I):
                continue
            if not any(clean_text(tag.get_text(" ")).lower() == "exhibitions" for tag in card.select('a[href*="type=exhibitions"]')):
                continue
            heading = card.find(["h2", "h3", "h4"])
            title = clean_text(heading.get_text(" ") if heading else a.get_text(" "))
            if not title:
                continue
            date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]+\s+(?:\d{4}\s*)?[-–]\s*(?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4}\b", text, re.I)
            if not date_match:
                continue
            date_text = clean_text(date_match.group(0))
            dates = parse_date_range(date_text)
            if page_url.endswith("/whats-on/archive/year/2026-2020") and dates[0] and dates[0] < "2023-01-01":
                continue
            records[url] = (r, title, date_text, dates, card)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (r, title, date_text, dates, card) in records.items():
        _store_uk_exhibition(ctx, r, url=url, title=title, date_text=date_text, dates=dates, org=org, card=card,
                             locator=f"What's On exhibition card {url}",
                             img_basis="Serpentine exhibition image; individual credits apply, no open licence stated")
        ctx.con.commit()
    ctx.note("What's On page supplies current/upcoming programme and the public 2026–2020 archive page; the archive is limited to events starting in 2023 onward. Only cards tagged Exhibitions and carrying an exhibition date range are retained (talks and single-day events are excluded). Dates retain day precision when shown.")
    ctx.con.commit()


def _main_text(soup):
    for sc in soup(["script", "style", "nav", "footer"]):
        sc.decompose()
    return " ".join((soup.find("main") or soup.body).get_text(" ").split())


def _tate_dates(soup):
    for h in soup.find_all("h2"):
        if h.get_text(strip=True) == "Dates":
            return clean_text(h.parent.get_text(" ").replace("Dates", "", 1))
    return None


def _tate(ctx):
    tate = C.org(ctx, "Tate", url="https://www.tate.org.uk")
    base = "https://www.tate.org.uk/whats-on?date_range=from_now&event_type=display&event_type=exhibition"
    cards, page = {}, 1
    while page <= 10:
        r = ctx.fetch(base + (f"&page={page}" if page > 1 else ""))
        s = BeautifulSoup(r.text, "lxml")
        ev = ctx.evidence(r, locator=f"whats-on exhibitions page={page}")
        new = 0
        for c in s.select("div.card"):
            a = c.find("a", href=True)
            if not a or not re.match(r"^/whats-on/[^/]+/[^/]+$", a["href"]):
                continue
            tag = clean_text((c.select_one(".card-tags") or c).get_text(" "))
            if tag and not re.search(r"exhibition|display", tag, re.I):
                continue
            href = a["href"]
            if href in cards:
                continue
            cards[href] = dict(
                title=clean_text((c.select_one(".card__title") or a).get_text(" ")),
                venue=clean_text((c.select_one(".event-info__venue") or c).get_text(" ")),
                date=clean_text((c.select_one(".event-info__date") or c).get_text(" ")),
                desc=clean_text((c.select_one(".card__description") or c).get_text(" ")), ev=ev)
            new += 1
        ctx.count("fetched", new)
        nxt = [x["href"] for x in s.select('a[href*="page="]') if f"page={page + 1}" in x["href"]]
        if not nxt or new == 0:
            break
        page += 1
    ctx.note("listing shows current+upcoming only (date_range=past filter returns the same list); no archive")
    for href, c in cards.items():
        url = urllib.parse.urljoin("https://www.tate.org.uk", href)
        slug_venue = href.split("/")[2]
        venue, city = TATE_VENUES.get(slug_venue, (c["venue"], None))
        if city is None and slug_venue not in UK_NO_CITY:
            ctx.note(f"unknown venue {c['venue']} for {href}")
        date_text, ev, img = c["date"], c["ev"], None
        if C.needs_detail(ctx, href):
            r = C.try_fetch(ctx, url)
            if r is not None:
                ds = _tate_dates(BeautifulSoup(r.text, "lxml"))
                if ds:
                    date_text = ds
                ev = ctx.evidence(r, locator="detail Dates", excerpt=date_text)
                img = C.og(r.text, "image")
        elif C.known(ctx, href) is not None:
            row = ctx.con.execute("SELECT date_text FROM events WHERE source_id=? AND source_event_key=?",
                                  (ctx.source_id, href)).fetchone()
            date_text = row["date_text"] or date_text
        title = c["title"]
        C.store_exhibition(ctx, key=href, title=title, url=url, ev=ev, organizer=tate, city=city,
                           country="GB" if city or slug_venue in UK_NO_CITY else None, date_text=date_text,
                           dates_tuple=None if not re.search(r"daily|ongoing", date_text or "", re.I) else _loose(date_text),
                           desc=c["desc"], image=img, image_basis=TATE_IMG,
                           artists=None, person_title_fallback=True)
        ctx.con.commit()
    ctx.con.commit()


def _loose(t):
    if re.search(r"ongoing", t or "", re.I):
        return None, None, None, None
    return parse_date_range(t)


def _turner(ctx):
    tate = C.org(ctx, "Tate", url="https://www.tate.org.uk")
    prize = db.ensure_entity(ctx.con, entity_type="foundation", name="Turner Prize", namespace=f"src:{ctx.source_id}",
                             source_id=ctx.source_id, official_url="https://www.tate.org.uk/art/turner-prize")
    r = ctx.fetch("https://www.tate.org.uk/art/turner-prize")
    hub_ev = ctx.evidence(r, locator="turner-prize hub")
    links = set(re.findall(r'href="((?:https://www\.tate\.org\.uk)?/whats-on/[a-z0-9-]+/turner-prize-(20\d\d))"', r.text))
    found = {y: urllib.parse.urljoin("https://www.tate.org.uk", h) for h, y in links}
    # Edition pages for years not linked from the (stale) hub follow the same /whats-on/<venue>/turner-prize-<year> pattern.
    defaults = {"2023": "towner-eastbourne", "2024": "tate-britain", "2025": "bradford", "2026": "tate-britain"}
    for y, v in defaults.items():
        found.setdefault(y, f"https://www.tate.org.uk/whats-on/{v}/turner-prize-{y}")
    years = sorted(y for y in found if y >= ("2023" if ctx.mode == "initial" else "2025"))
    ctx.count("fetched", len(years))
    ctx.note("hub page full list ends at 2022; editions 2023+ read from edition pages")
    for y in years:
        url = found[y]
        rr = C.try_fetch(ctx, url)
        if rr is None:
            ctx.note(f"Turner Prize {y}: edition page not found")
            continue
        s = BeautifulSoup(rr.text, "lxml")
        date_text = _tate_dates(s)
        venue_slug = url.rstrip("/").split("/")[-2]
        venue, city = TATE_VENUES.get(venue_slug, (None, None))
        text = _main_text(BeautifulSoup(rr.text, "lxml"))
        nominees = _shortlist(s, text)
        winner = None
        m = re.search(r"(?:announced[^.]{0,40}that\s+)?([A-Z][\w'’\- ]{2,60}?) (?:was|has been) (?:announced as )?the winner of the "
                      r"Turner Prize " + y, text)
        if m:
            winner = m.group(1).strip()
            winner = re.sub(r"^.*\bthat\s+", "", winner)
        ev = rr and ctx.evidence(rr, locator=f"Turner Prize {y} edition page", excerpt=date_text)
        eid = C.store_exhibition(ctx, key=f"turner-prize-{y}", title=f"Turner Prize {y}", url=url, ev=ev, organizer=tate,
                                 city=city, country="GB" if city else None, date_text=date_text, event_type="award",
                                 subtype=None, person_title_fallback=False, image=C.og(rr.text, "image"), image_basis=TATE_IMG)
        for n in nominees:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=n, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=ev)
            db.add_participant(ctx.con, eid, ent, "nominee", n, ev, "list_markup")
        if winner:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=winner, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=ev)
            db.add_participant(ctx.con, eid, ent, "winner", winner, ev, "list_markup")
            db.upsert_relationship(ctx.con, subject_entity_id=ent, object_entity_id=prize, rel_type="award_winner",
                                   source_id=ctx.source_id, evidence_id=ev, scope=y)
        else:
            ctx.note(f"Turner Prize {y}: winner not stated on edition page")
        ctx.con.commit()
    ctx.con.commit()
    _ = hub_ev


def _shortlist(soup, text):
    # 1) "The four shortlisted artists for the Turner Prize YYYY are:" followed by <ul>
    for p in soup.find_all(["p", "h2", "h3"]):
        t = p.get_text(" ", strip=True)
        if re.search(r"shortlisted artists", t, re.I):
            if p.name == "p":
                ul = p.find_next_sibling("ul")
                if ul:
                    return [clean_text(li.get_text(" ")) for li in ul.find_all("li")]
            else:
                names, n = [], p.find_next()
                while n is not None and n.name != "h2":
                    if n.name == "h4":
                        names.append(clean_text(n.get_text(" ")))
                    n = n.find_next()
                if names:
                    return names
    m = re.search(r"((?:[A-Z][\w'’\-]+ ?){1,4}(?:, (?:[A-Z][\w'’\-]+ ?){1,4})+ and (?:[A-Z][\w'’\-]+ ?){1,4}) are the four artists shortlisted", text)
    if m:
        return [x.strip() for x in re.split(r", | and ", m.group(1))]
    return []
