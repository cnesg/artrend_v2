"""European galleries: Sadie Coles HQ (London) exhibitions + artist roster; kamel mennour registered only."""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from .. import db
from ._common import clean_text, parse_date_range
from . import eu_common as C

PARSER_VERSION = "eu_galleries-2"
SC = "https://www.sadiecoles.com"

SOURCES = [
    dict(source_id="sadie_coles", blueprint_data_id=None, blueprint_org_id="O34", name="Sadie Coles HQ — Exhibitions & artists",
         owner_group="Sadie Coles HQ", source_kind="gallery", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url=SC, entry_url=f"{SC}/exhibitions", terms_url=None, text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(html)", st_collection_terms="terms page not located (robots.txt allows /, blocks GPTBot/Google-Extended/PerplexityBot only)",
         st_image_terms="terms page not located; installation views © artist / Sadie Coles HQ", max_requests=40),
    dict(source_id="kamel_mennour", blueprint_data_id=None, blueprint_org_id="O35", name="kamel mennour — Exhibitions & artists",
         owner_group="kamel mennour", source_kind="gallery", region_scope="EUROPE", country_codes="FR", access_method="html",
         base_url="https://mennour.com", entry_url="https://mennour.com/exhibitions/current", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(public HTML; current and archive listings)",
         st_collection_terms="terms not located; robots.txt permits public exhibition and archive paths",
         st_image_terms="images credited per exhibition; no open licence stated", max_requests=250),
]

LONDON = re.compile(r"\b(W1[A-Z]?|SW1[A-Z]?|London|Kingly Street|Bury Street|Savile Row|Davies Street|Regent Street)\b")
CITIES = {"kyoto": ("Kyoto", "JP"), "amsterdam": ("Amsterdam", "NL"), "athens": ("Athens", "GR"),
          "39 walker": ("New York", "US"), "new york": ("New York", "US"), "paris": ("Paris", "FR"),
          "los angeles": ("Los Angeles", "US"), "basel": ("Basel", "CH"), "miami": ("Miami", "US"), "hong kong": ("Hong Kong", "HK")}


def collect(ctx):
    if ctx.source_id == "kamel_mennour":
        return _mennour(ctx)
    if ctx.source_id != "sadie_coles":
        raise ValueError(ctx.source_id)
    gal = C.org(ctx, "Sadie Coles HQ", etype="gallery", url=SC)
    _roster(ctx, gal)
    page, oldest = 1, "9999"
    last = 12 if ctx.mode == "initial" else 1
    while page <= last:
        r = ctx.fetch(f"{SC}/exhibitions" + (f"/p{page}" if page > 1 else ""))
        s = BeautifulSoup(r.text, "lxml")
        cards = [a for a in s.select('a[href^="https://www.sadiecoles.com/exhibitions/"][aria-label]')
                 if not re.search(r"/exhibitions/p\d+$", a["href"])]
        ctx.count("fetched", len(cards))
        for a in cards:
            strings = [clean_text(x) for x in a.stripped_strings if clean_text(x)]
            di = next((i for i, x in enumerate(strings) if re.search(r"\b(19|20)\d\d\b", x) and re.search(r"[A-Z][a-z]+", x)
                       and re.search(r"\d{1,2} [A-Z][a-z]+", x)), None)
            if di is None or di < 1:
                ctx.note(f"card without date: {a['href']}")
                continue
            date_text = strings[di]
            head, venue = strings[:di], " ".join(strings[di + 1:]) or None
            artist_line = head[0] if len(head) > 1 else None
            title = head[-1] if len(head) > 1 else head[0]
            curators = []
            if artist_line and re.match(r"curated by\s+", artist_line, re.I):
                curators = [x.strip() for x in re.split(r",\s*|\s+and\s+", artist_line[11:]) if x.strip()]
                artists = []
            elif artist_line and (artist_line.lower().startswith(("group exhibition", "condo", "hosting")) or ":" in artist_line):
                artists = []
            elif artist_line:
                artists = [x.strip() for x in re.split(r",\s*|\s+and\s+|\s*&\s*", artist_line) if x.strip()]
            else:
                artists = []
            city, cc = _city(venue)
            d = C.range_dates(date_text)
            oldest = min(oldest, d[0] or d[2] or "9999")
            ev = ctx.evidence(r, locator=f"listing card {a['href']}", excerpt=f"{date_text} | {venue}")
            full_title = f"{artist_line}: {title}" if artist_line and artist_line != title and artists else title
            C.store_exhibition(ctx, key=a["href"], title=full_title, url=a["href"], ev=ev, organizer=gal, city=city,
                               country=cc, date_text=f"{date_text} @ {venue}", dates_tuple=d, artists=artists,
                               subtype=("group" if artist_line and artist_line.lower().startswith("group") else None),
                               person_title_fallback=False, curators=curators)
        ctx.con.commit()
        if not s.select(f'a[href="{SC}/exhibitions/p{page + 1}"]') or oldest < "2023-01-01":
            break
        page += 1
    ctx.note(f"archive paginated (/exhibitions/pN); crawled {page} page(s), oldest start {oldest}")
    ctx.con.commit()


_MENNOUR_RANGE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}\s*[-–]\s*"
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+)?\d{1,2},?\s+\d{4}\b", re.I)


def _mennour_card(a):
    node = a
    for _ in range(8):
        text = clean_text(node.get_text(" ")) if hasattr(node, "get_text") else ""
        if re.search(r"\bMennour\s*,", text, re.I):
            return node, text
        node = getattr(node, "parent", None)
        if node is None:
            break
    return a, clean_text(a.get_text(" "))


def _mennour_title(card, a):
    heads = [clean_text(h.get_text(" ")) for h in card.find_all(["h2", "h3", "h4"]) if clean_text(h.get_text(" "))]
    if len(heads) > 1:
        return heads[0], heads[1]
    strings = [clean_text(x) for x in a.stripped_strings if clean_text(x)]
    date_index = next((i for i, value in enumerate(strings) if _MENNOUR_RANGE.search(value)), None)
    if date_index is not None and date_index:
        before_date = strings[:date_index]
        if len(before_date) > 1:
            return before_date[0], " ".join(before_date[1:])
        return None, before_date[0]
    venue_index = next((i for i, value in enumerate(strings) if re.search(r"\bMennour\s*,", value, re.I)), None)
    if venue_index is not None and venue_index:
        before_venue = strings[:venue_index]
        if len(before_venue) > 1:
            return before_venue[0], " ".join(before_venue[1:])
        return None, before_venue[0]
    if heads:
        return None, heads[0]
    raw = clean_text(a.get_text(" "))
    m = _MENNOUR_RANGE.search(raw)
    prefix = clean_text(raw[:m.start()]) if m else raw
    prefix = re.sub(r"\bMennour\s*,.*$", "", prefix, flags=re.I).strip()
    return None, prefix


def _mennour_image(card, base):
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


def _mennour(ctx):
    base = "https://mennour.com"
    gallery = C.org(ctx, "kamel mennour", etype="gallery", url=base)
    listings = [base + "/exhibitions/current", base + "/exhibitions/archive"]
    records = {}
    for listing_url in listings:
        r = ctx.fetch(listing_url)
        s = BeautifulSoup(r.text, "lxml")
        for a in s.select('a[href^="/exhibition/"]'):
            url = urllib.parse.urljoin(base, a["href"])
            card, text = _mennour_card(a)
            # The archive mixes the gallery's own shows with institutional shows by represented artists.
            if not re.search(r"\bMennour\s*,", text, re.I):
                continue
            year = None
            year_label = a.find_previous(string=re.compile(r"^\s*20\d{2}\s*$"))
            if year_label:
                year = int(clean_text(str(year_label)))
            if listing_url.endswith("/archive"):
                if year is not None and year < (2023 if ctx.mode == "initial" else 2025):
                    continue
                if year is None:
                    continue
            artist, show_title = _mennour_title(card, a)
            title = f"{artist}: {show_title}" if artist and show_title and artist != show_title else show_title or artist
            date_match = _MENNOUR_RANGE.search(text)
            date_text = clean_text(date_match.group(0)) if date_match else (str(year) if year else None)
            if not title:
                continue
            records[url] = (r, title, artist, date_text, card)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (listing, title, artist, date_text, card) in records.items():
        if not C.needs_detail(ctx, url):
            continue
        detail = C.try_fetch(ctx, url)
        if detail is None:
            dates = parse_date_range(date_text)
            ev = ctx.evidence(listing, locator=f"gallery exhibition listing {url}", excerpt=(date_text or title)[:300])
            C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=gallery, city="Paris", country="FR",
                               date_text=date_text, dates_tuple=dates, artists=[artist] if artist else [],
                               person_title_fallback=False, image=_mennour_image(card, base),
                               image_basis="Mennour listing image; credits per exhibition, no open licence stated")
            ctx.con.commit()
            continue
        s_detail = BeautifulSoup(detail.text, "lxml")
        body = clean_text(s_detail.get_text(" "))
        date_match = _MENNOUR_RANGE.search(body)
        detail_date = clean_text(date_match.group(0)) if date_match else date_text
        dates = parse_date_range(detail_date)
        ev = ctx.evidence(detail, locator="exhibition detail title/date/venue", excerpt=(detail_date or title)[:300])
        C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=gallery,
                           city="Paris", country="FR", date_text=detail_date, dates_tuple=dates,
                           artists=[artist] if artist else [],
                           person_title_fallback=False, image=C.og(detail.text, "image"),
                           image_basis="Mennour exhibition image; credits on page, no open licence stated")
        ctx.con.commit()
    ctx.note("Current gallery exhibitions plus archive cards dated by year heading. Only entries explicitly located at Mennour (Paris) are retained; artist institutional/off-site shows are excluded. Detail pages supply month/day dates; archive heading year is retained at year precision if a detail date is absent. Initial archive walk includes 2023 onward; incremental includes 2025 onward.")
    ctx.con.commit()


def _city(venue):
    v = (venue or "").lower()
    for k, val in CITIES.items():
        if k in v:
            return val
    if LONDON.search(venue or ""):
        return "London", "GB"
    return None, None


def _roster(ctx, gal):
    r = ctx.fetch(f"{SC}/artists")
    s = BeautifulSoup(r.text, "lxml")
    ev = ctx.evidence(r, locator="artists list")
    n = 0
    for a in s.select('a[href^="https://www.sadiecoles.com/artists/"]'):
        slug = a["href"].rstrip("/").split("/")[-1]
        name = clean_text(a.get_text(" "))
        if slug in ("grid", "list") or not name:
            continue
        ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace="sadiecoles_artist", id_value=slug,
                               source_id=ctx.source_id, evidence_id=ev, official_url=a["href"])
        db.upsert_relationship(ctx.con, subject_entity_id=gal, object_entity_id=ent, rel_type="listed_artist",
                               source_id=ctx.source_id, evidence_id=ev, status="source_asserted")
        n += 1
    ctx.note(f"roster: {n} listed artists (page does not say 'represents')")
    ctx.con.commit()
