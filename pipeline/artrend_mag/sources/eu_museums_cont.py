"""Continental European museum sources: public HTML listings and RSS feeds."""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from ..http import FetchError
from ._common import clean_text, jsonld_objects, parse_date_range, parse_feed
from . import eu_common as C

PARSER_VERSION = "eu_museums_cont-2"

SOURCES = [
    dict(source_id="pompidou_program", blueprint_data_id="D15", blueprint_org_id="O29", name="Centre Pompidou — Programme",
         owner_group="Centre Pompidou", source_kind="museum", region_scope="EUROPE", country_codes="FR", access_method="html",
         base_url="https://www.centrepompidou.fr", entry_url="https://www.centrepompidou.fr/en/program/calendar",
         terms_url="https://www.centrepompidou.fr/en/legal-notices", text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(html listings; detail JSON-LD exists but details trigger bot challenge)",
         st_collection_terms="terms page not readable (legal-notices returned a bot-challenge page to our UA, 2026-10-27)",
         st_image_terms="terms page not readable; images treated as © lenders/artists", max_requests=120),
    dict(source_id="maxxi_events", blueprint_data_id=None, blueprint_org_id=None, name="MAXXI — Events feed",
         owner_group="MAXXI", source_kind="museum", region_scope="EUROPE", country_codes="IT", access_method="rss",
         base_url="https://www.maxxi.art", entry_url="https://www.maxxi.art/en/eventi/feed/",
         terms_url=None, text_storage_policy="raw_internal", priority="P1", st_official_doc="ok(public RSS)",
         st_collection_terms="terms page not located", st_image_terms="terms page not located", max_requests=10),
    dict(source_id="macba_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="MACBA — Exhibitions feed",
         owner_group="MACBA", source_kind="museum", region_scope="EUROPE", country_codes="ES", access_method="rss",
         base_url="https://www.macba.cat", entry_url="https://www.macba.cat/en/exhibitions/feed/",
         terms_url=None, text_storage_policy="raw_internal", priority="P1", st_official_doc="ok(public RSS, WordPress)",
         st_collection_terms="terms page not located", st_image_terms="image captions carry © artist / MACBA Collection",
         max_requests=80),
    dict(source_id="stedelijk_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Stedelijk Museum Amsterdam — Exhibitions", owner_group="Stedelijk Museum",
         source_kind="museum", region_scope="EUROPE", country_codes="NL", access_method="html", base_url="https://www.stedelijk.nl",
         entry_url="https://www.stedelijk.nl/en/whats-on", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML; detail page returned AWS WAF JavaScript challenge)",
         st_collection_terms="terms not located; robots.txt allows public listing, sets 10s crawl-delay, and disallows date-query paths",
         st_image_terms="terms not located; images treated as copyrighted, no open licence stated", max_requests=60),
    dict(source_id="moderna_museet_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Moderna Museet — Exhibitions", owner_group="Moderna Museet",
         source_kind="museum", region_scope="EUROPE", country_codes="SE", access_method="html", base_url="https://www.modernamuseet.se",
         entry_url="https://www.modernamuseet.se/en/stockholm/exhibitions/", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML; yearly archive pages)",
         st_collection_terms="privacy notice opened; no general automated-collection terms located; archive pages publicly accessible",
         st_image_terms="image credits are stated per work; no blanket open licence found", max_requests=40),
    dict(source_id="kunsthalle_wien_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Kunsthalle Wien — Exhibitions", owner_group="Kunsthalle Wien",
         source_kind="museum", region_scope="EUROPE", country_codes="AT", access_method="html", base_url="https://kunsthallewien.at",
         entry_url="https://kunsthallewien.at/en/exhibitions/", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
         st_collection_terms="terms not located; robots.txt permits general user agents (search permitted; AI training disallowed)",
         st_image_terms="terms not located; images treated as copyrighted, no open licence stated", max_requests=20),
    dict(source_id="hamburger_bahnhof_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Hamburger Bahnhof — Exhibitions", owner_group="Staatliche Museen zu Berlin",
         source_kind="museum", region_scope="EUROPE", country_codes="DE", access_method="html", base_url="https://www.smb.museum",
         entry_url="https://www.smb.museum/en/museums-institutions/hamburger-bahnhof/exhibitions/current/", terms_url="https://www.smb.museum/en/legal-notice/", text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML listing; detail paths disallowed by robots.txt)",
         st_collection_terms="site text is CC BY-NC-SA 3.0 DE; other content follows individual copyright notices; robots.txt disallows exhibition detail URLs",
         st_image_terms="images are individually credited; reuse only where the page shows an applicable CC mark", max_requests=10),
    dict(source_id="muzeum_sztuki_exhibitions", blueprint_data_id=None, blueprint_org_id=None, name="Muzeum Sztuki w Łodzi — Exhibitions", owner_group="Muzeum Sztuki",
         source_kind="museum", region_scope="EUROPE", country_codes="PL", access_method="html", base_url="https://msl.org.pl",
         entry_url="https://msl.org.pl/en/exhibitions", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public Drupal HTML listings)",
         st_collection_terms="terms not located; current/upcoming/archive listing pages are public",
         st_image_terms="terms not located; images treated as copyrighted, no open licence stated", max_requests=12),
    dict(source_id="pinault_collection", blueprint_data_id="D55", blueprint_org_id="O36", name="Pinault Collection — Exhibitions", owner_group="Pinault Collection",
         source_kind="museum", region_scope="EUROPE", country_codes="FR,IT", access_method="html", base_url="https://www.pinaultcollection.com",
         entry_url="https://www.pinaultcollection.com/en/boursedecommerce", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public Bourse de Commerce and Palazzo Grassi HTML)",
         st_collection_terms="terms not located; venue archive and exhibition detail pages are public; robots.txt disallows administrative/search paths only",
         st_image_terms="images carry artist/photographer credits; no open licence stated", max_requests=100),
    dict(source_id="reina_sofia", blueprint_data_id=None, blueprint_org_id="O30", name="Museo Reina Sofía — Exhibitions", owner_group="Museo Nacional Centro de Arte Reina Sofía",
         source_kind="museum", region_scope="EUROPE", country_codes="ES", access_method="html", base_url="https://www.museoreinasofia.es",
         entry_url="https://www.museoreinasofia.es/en/exhibitions", terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a",
         st_collection_terms="not checked", st_image_terms="not checked", disabled="robots.txt returns HTTP 403 (fetcher refuses to crawl; checked 2026-10-27)", operational_state="blocked_access", robots_status="robots_http_403", st_live_response="blocked(403)"),
]



def collect(ctx):
    {"pompidou_program": _pompidou, "maxxi_events": _maxxi, "macba_exhibitions": _macba,
     "stedelijk_exhibitions": _stedelijk, "moderna_museet_exhibitions": _moderna,
     "kunsthalle_wien_exhibitions": _kunsthalle, "hamburger_bahnhof_exhibitions": _hamburger_bahnhof,
     "muzeum_sztuki_exhibitions": _muzeum_sztuki, "pinault_collection": _pinault}[ctx.source_id](ctx)


_DMY_RANGE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.?(?:\s*(\d{4}))?\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.?(?:\s*(\d{4}))?")


def _card(a, date_re):
    node = a
    for _ in range(8):
        text = clean_text(node.get_text(" ")) if hasattr(node, "get_text") else ""
        if date_re.search(text) or re.search(r"\buntil further notice\b", text, re.I):
            return node, text
        node = getattr(node, "parent", None)
        if node is None:
            break
    return a, clean_text(a.get_text(" "))


def _img(card, base):
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


def _dmy_range(text):
    """Expand abbreviated day-first date ranges only when a year is printed in the range."""
    m = _DMY_RANGE.search(text or "")
    if not m:
        return None, (None, None, None, None)
    d1, m1, y1, d2, m2, y2 = m.groups()
    year = y1 or y2
    if not year:
        return m.group(0), (None, None, None, None)
    y1, y2 = y1 or year, y2 or year
    normalized = f"{d1}.{m1}.{y1} – {d2}.{m2}.{y2}"
    return m.group(0), parse_date_range(normalized)


def _modern_range(text):
    m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\s+(\d{4}))?\s*[–—-]\s*(\d{1,2})\.(\d{1,2})(?:\s+(\d{4}))?", text or "")
    if not m:
        return None, (None, None, None, None)
    d1, m1, y1, d2, m2, y2 = m.groups()
    year = y1 or y2
    if not year:
        return m.group(0), (None, None, None, None)
    y1, y2 = y1 or year, y2 or year
    normalized = f"{d1}.{m1}.{y1} – {d2}.{m2}.{y2}"
    return m.group(0), parse_date_range(normalized)


def _store_listing(ctx, resp, *, url, title, date_text, dates, organizer, city, country, locator, card, image_basis):
    ev = ctx.evidence(resp, locator=locator, excerpt=(date_text or title)[:300])
    return C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=organizer, city=city,
                              country=country, date_text=date_text, dates_tuple=dates, image=_img(card, resp.url),
                              image_basis=image_basis)


def _stedelijk(ctx):
    base = "https://www.stedelijk.nl"
    org = C.org(ctx, "Stedelijk Museum Amsterdam", url=base)
    r = ctx.fetch(base + "/en/whats-on")
    s = BeautifulSoup(r.text, "lxml")
    events = {}
    for section in s.find_all(["h2", "h3"]):
        label = clean_text(section.get_text(" ")).lower()
        if label not in ("current exhibitions", "upcoming exhibitions"):
            continue
        for a in section.find_all_next("a", href=True):
            nxt = a.find_previous(["h2", "h3"])
            if nxt is not None and nxt is not section:
                break
            href = urllib.parse.urljoin(base, a["href"])
            if "/en/exhibitions/" not in urllib.parse.urlsplit(href).path:
                continue
            title = clean_text(a.get_text(" "))
            if title:
                events[href] = (title, label, a)
    ctx.count("fetched", len(events))
    for url, (title, section, a) in events.items():
        _store_listing(ctx, r, url=url, title=title, date_text=None, dates=(None, None, None, None),
                       organizer=org, city="Amsterdam", country="NL", locator=f"{section} listing {url}",
                       card=a, image_basis="Stedelijk exhibition imagery; terms not located, no open licence stated")
    ctx.note("listing contains current and upcoming exhibition titles but no dates; exhibition detail returned an AWS WAF JavaScript verification challenge, so no detail was retried. Robots.txt sets a 10-second crawl delay and disallows date-query paths. No public archive listing identified.")
    ctx.con.commit()


def _moderna(ctx):
    base = "https://www.modernamuseet.se"
    org = C.org(ctx, "Moderna Museet", url=base)
    years = [2026, 2025, 2024, 2023] if ctx.mode == "initial" else [2026]
    pages = [(base + "/en/stockholm/exhibitions/", "current/upcoming")]
    pages.extend((f"{base}/en/stockholm/exhibitions/year/{year}/", f"archive {year}") for year in years)
    records = {}
    for page_url, label in pages:
        r = ctx.fetch(page_url)
        s = BeautifulSoup(r.text, "lxml")
        for a in s.select('a[href*="/en/stockholm/exhibitions/"]'):
            url = urllib.parse.urljoin(base, a["href"])
            if "/year/" in url or url.rstrip("/") == (base + "/en/stockholm/exhibitions").rstrip("/"):
                continue
            card, text = _card(a, re.compile(r"\d{1,2}\.\d{1,2}.*[–—-].*\d{1,2}\.\d{1,2}"))
            date_text, dates = _modern_range(text)
            title = clean_text(a.get_text(" ")) or clean_text((card.find(["h2", "h3", "h4"]) or a).get_text(" "))
            if title:
                records[url] = (r, title, date_text, dates, card, label)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (r, title, date_text, dates, card, label) in records.items():
        _store_listing(ctx, r, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                       city="Stockholm", country="SE", locator=f"{label} exhibition card {url}", card=card,
                       image_basis="Moderna Museet exhibition image; visible credit on site, no blanket open licence")
    ctx.note(f"stockholm current/upcoming page plus public archive years {', '.join(map(str, years))}; dates retained only where the listing publishes a day-level range")
    ctx.con.commit()


def _kunsthalle(ctx):
    base = "https://kunsthallewien.at"
    org = C.org(ctx, "Kunsthalle Wien", url=base)
    pages = [base + "/en/exhibitions/"]
    if ctx.mode == "initial":
        pages.append(base + "/en/exhibitions/archive")
    records = {}
    for page_url in pages:
        r = ctx.fetch(page_url)
        s = BeautifulSoup(r.text, "lxml")
        for a in s.select('a[href*="/en/exhibition/"]'):
            url = urllib.parse.urljoin(base, a["href"])
            card, text = _card(a, _DMY_RANGE)
            date_text, dates = _dmy_range(text)
            title = clean_text((a.find(["h2", "h3", "h4"]) or a).get_text(" "))
            if not title:
                continue
            records[url] = (r, title, date_text, dates, card)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (r, title, date_text, dates, card) in records.items():
        _store_listing(ctx, r, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                       city="Vienna", country="AT", locator=f"exhibition listing {url}", card=card,
                       image_basis="Kunsthalle Wien exhibition image; terms not located, no open licence stated")
    ctx.note("current/forthcoming page plus public exhibition archive; archive HTML is unpaginated and displays years back through 2022. Dates use day precision when a full date range is printed; abbreviated ranges inherit the explicitly printed range year.")
    ctx.con.commit()


def _hamburger_bahnhof(ctx):
    base = "https://www.smb.museum"
    org = C.org(ctx, "Hamburger Bahnhof – Nationalgalerie der Gegenwart", url=base)
    url = base + "/en/museums-institutions/hamburger-bahnhof/exhibitions/current/"
    r = ctx.fetch(url)
    s = BeautifulSoup(r.text, "lxml")
    records = {}
    for a in s.select('a[href*="/hamburger-bahnhof/exhibitions/detail/"]'):
        link = urllib.parse.urljoin(base, a["href"])
        card, text = _card(a, re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}|until further notice", re.I))
        date_match = re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4}\s*(?:(?:to|[-–—])\s*\d{1,2}\.\d{1,2}\.\d{4}|until further notice)\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b|\buntil further notice\b", text, re.I)
        date_text = clean_text(date_match.group(0)) if date_match else None
        title = clean_text(a.get("title") or a.get_text(" "))
        if title:
            records[link] = (title, date_text, card)
    ctx.count("fetched", len(records))
    for link, (title, date_text, card) in records.items():
        dates = parse_date_range(re.sub(r"\s+until further notice\b", "", date_text, flags=re.I) if date_text else None)
        _store_listing(ctx, r, url=link, title=title, date_text=date_text, dates=dates, organizer=org,
                       city="Berlin", country="DE", locator=f"current exhibitions card {link}", card=card,
                       image_basis="Staatliche Museen zu Berlin listing image; individual copyright/CC credit governs reuse")
    ctx.note("current-exhibitions listing only; its links to /exhibitions/detail/ are disallowed by robots.txt and were not fetched. Listing includes day dates where stated and several long-running displays only as 'until further notice'; no past archive was exposed on the permitted listing.")
    ctx.con.commit()


def _muzeum_sztuki(ctx):
    base = "https://msl.org.pl"
    org = C.org(ctx, "Muzeum Sztuki w Łodzi", url=base)
    pages = ["/en/current-exhibitions", "/en/upcoming-exhibitions-0"]
    if ctx.mode == "initial":
        pages.append("/en/archive-exhibitions")
    records = {}
    for path in pages:
        r = ctx.fetch(base + path)
        s = BeautifulSoup(r.text, "lxml")
        for a in s.select('a[href^="/en/"]'):
            if a.find_parent("nav") or a.find_parent("header") or a.find_parent("footer"):
                continue
            url = urllib.parse.urljoin(base, a["href"])
            path_url = urllib.parse.urlsplit(url).path.rstrip("/")
            if path_url == "/en" or url.rstrip("/") in {base + p for p in ("/en/exhibitions", "/en/current-exhibitions", "/en/upcoming-exhibitions-0", "/en/archive-exhibitions")}:
                continue
            card, text = _card(a, _DMY_RANGE)
            date_text, dates = _dmy_range(text)
            title_node = card.find(["h2", "h3", "h4"])
            title = clean_text(title_node.get_text(" ") if title_node else a.get_text(" "))
            if date_text and date_text in title:
                title = title.split(date_text, 1)[0]
            title = re.sub(r"\s+(?:Place\s*:|ms[¹²12]?|The Herbst Palace Museum)\s*,?.*$", "", title, flags=re.I).strip()
            if not title or not (date_text or path.endswith(("current-exhibitions", "upcoming-exhibitions-0"))):
                continue
            records[url] = (r, title, date_text, dates, card, path)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (r, title, date_text, dates, card, path) in records.items():
        _store_listing(ctx, r, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                       city="Łódź", country="PL", locator=f"{path} listing {url}", card=card,
                       image_basis="Muzeum Sztuki exhibition image; terms not located, no open licence stated")
    ctx.note("current and upcoming exhibition listings; initial mode also reads the archive listing. Listing dates are day-precision ranges when supplied; dates absent from a card remain unknown. Venue branches listed are all in Łódź, Poland.")
    ctx.con.commit()


def _pinault_sections(soup, prefix):
    links = []
    headings = soup.find_all(["h2", "h3"])
    for heading in headings:
        if clean_text(heading.get_text(" ")).lower() != "exhibitions":
            continue
        level = int(heading.name[1])
        for node in heading.find_all_next():
            if node.name in ("h1", "h2", "h3", "h4") and int(node.name[1]) <= level:
                break
            if node.name == "a":
                parsed = urllib.parse.urlsplit(urllib.parse.urljoin("https://www.pinaultcollection.com", node.get("href", "")))
                if parsed.path.startswith(prefix):
                    href = urllib.parse.urlunsplit(parsed)
                    if href not in links:
                        links.append(href)
    return links


def _pinault(ctx):
    base = "https://www.pinaultcollection.com"
    org = C.org(ctx, "Pinault Collection", url=base)
    venues = [
        ("FR", "Paris", "/en/boursedecommerce", "/en/boursedecommerce/archives"),
        ("IT", "Venice", "/palazzograssi/en/home", "/palazzograssi/en/archives"),
    ]
    years = [2026, 2025, 2024, 2023] if ctx.mode == "initial" else [2026]
    details = {}
    for country, city, home_path, archive_path in venues:
        home = ctx.fetch(base + home_path)
        home_soup = BeautifulSoup(home.text, "lxml")
        prefix = "/en/boursedecommerce/" if country == "FR" else "/palazzograssi/en/"
        # The venue landing pages expose their current/upcoming exhibition cards.
        for a in home_soup.select(f'a[href^="{prefix}"]'):
            href = urllib.parse.urljoin(base, a["href"])
            card, text = _card(a, re.compile(r"\b(?:from|until)\b|\d{1,2}\.\d{2}\.\d{2}", re.I))
            if a.find_parent("nav") or a.find_parent("footer") or href.endswith(("/home", "/boursedecommerce")):
                continue
            if len(text) > 1600:
                continue
            if re.search(r"\b(?:from|until)\b|\d{1,2}\.\d{2}\.\d{2}", text, re.I):
                details[href] = (country, city, home, a.get("title") or clean_text(a.get_text(" ")))
        archive_urls = [archive_path]
        if ctx.mode == "initial":
            archive_urls.extend(f"{archive_path}/{year}" for year in years if year != 2026)
        for archive_url in archive_urls:
            ar = ctx.fetch(base + archive_url)
            ar_soup = BeautifulSoup(ar.text, "lxml")
            for href in _pinault_sections(ar_soup, prefix):
                details[href] = (country, city, ar, None)
            ctx.con.commit()
    ctx.count("fetched", len(details))
    for url, (country, city, listing, listed_title) in details.items():
        if not C.needs_detail(ctx, url):
            continue
        detail = C.try_fetch(ctx, url)
        if detail is None:
            continue
        soup_detail = BeautifulSoup(detail.text, "lxml")
        title = clean_text((soup_detail.find("h1") or soup_detail.find("h2")).get_text(" ")) if soup_detail.find(["h1", "h2"]) else clean_text(listed_title)
        if not title:
            continue
        text = clean_text(soup_detail.get_text(" "))
        date_text, dates = _dmy_range(text)
        if not date_text:
            date_text, dates = _pinault_short_range(text)
        if not date_text:
            date_text = next((clean_text(p.get_text(" ")) for p in soup_detail.find_all(["p", "strong", "div"])
                              if re.search(r"\b(?:from|until)\b", p.get_text(" "), re.I)
                              and re.search(r"\b(?:19|20)\d{2}\b", p.get_text(" "))), None)
            dates = parse_date_range(date_text)
        ev = ctx.evidence(detail, locator="exhibition detail header/date", excerpt=(date_text or title)[:300])
        C.store_exhibition(ctx, key=url, title=title, url=url, ev=ev, organizer=org, city=city, country=country,
                           date_text=date_text, dates_tuple=dates, image=C.og(detail.text, "image"),
                           image_basis="Pinault Collection exhibition image with artist/photographer credits; no open licence stated")
        ctx.con.commit()
    ctx.note(f"Bourse de Commerce (Paris, FR) and Palazzo Grassi/Punta della Dogana (Venice, IT); initial mode reads 2023–2026 public year archives plus venue pages, incremental reads current archive plus venue pages. Detail pages supply dates where published; 'until' notices may state an end date only.")
    ctx.con.commit()


def _pinault_short_range(text):
    m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text or "")
    if not m:
        return None, (None, None, None, None)
    d1, m1, y1, d2, m2, y2 = m.groups()
    y1 = f"20{y1}" if len(y1) == 2 else y1
    y2 = f"20{y2}" if len(y2) == 2 else y2
    normalized = f"{d1}.{m1}.{y1} – {d2}.{m2}.{y2}"
    return m.group(0), parse_date_range(normalized)


# ---------------------------------------------------------------- Centre Pompidou
def _pompidou(ctx):
    """Listing-only: the exhibitions page carries title/date range/venue per exhibition and the calendar page
    carries type/venue/'Until' per programme item. Detail pages are NOT fetched: the site serves a bot-challenge
    page to our UA after a few detail requests (observed 2026-10-27), so we stay on the two listing pages."""
    org = C.org(ctx, "Centre Pompidou", url="https://www.centrepompidou.fr")
    base = "https://www.centrepompidou.fr"
    items = {}
    r = ctx.fetch(base + "/en/program/exhibitions")
    s = BeautifulSoup(r.text, "lxml")
    for blk in s.select(".textpic-text"):
        h3, h4 = blk.find("h3"), blk.find("h4")
        if not h3 or not h4:
            continue
        a = blk.select_one('a[href*="/program/calendar/event/"]')
        lieu = blk.select_one('a[href*="/lieu/"]')
        title = clean_text(h3.get_text(" "))
        url = urllib.parse.urljoin(base, a["href"]) if a else base + "/en/program/exhibitions"
        key = url.rstrip("/").split("/")[-1] if a else "exh:" + C.name_key(title)
        items[key] = dict(title=title, date=clean_text(h4.get_text(" ")), venue=clean_text(lieu.get_text(" ")) if lieu else None,
                          url=url, desc=clean_text(" ".join(p.get_text(" ") for p in blk.find_all("p")[1:3])),
                          ev=ctx.evidence(r, locator=f"exhibitions page block '{title[:60]}'", excerpt=clean_text(h4.get_text(" "))))
    n_exh = len(items)
    r = ctx.fetch(base + "/en/program/calendar")
    s = BeautifulSoup(r.text, "lxml")
    for a in s.select('a[href*="/program/calendar/event/"]'):
        typ = clean_text(a.select_one(".event-type").get_text(" ")) if a.select_one(".event-type") else ""
        if "exhibition" not in typ.lower() or typ.lower().startswith("online"):
            continue
        url = urllib.parse.urljoin(base, a["href"])
        key = url.rstrip("/").split("/")[-1]
        if key in items:
            continue
        date = " ".join(clean_text(x.get_text(" ")) for x in a.select(".dateEvenement"))
        title = clean_text((a.select_one(".event-title") or a).get_text(" "))
        if any(C.name_key(x["title"]).startswith(C.name_key(title)) for x in items.values()):
            continue  # same exhibition already listed on the exhibitions page
        items[key] = dict(title=title, date=date, url=url,
                          venue=clean_text(a.select_one(".event-place").get_text(" ")) if a.select_one(".event-place") else None,
                          desc=clean_text(a.select_one(".event-subtitle").get_text(" ")) if a.select_one(".event-subtitle") else None,
                          ev=ctx.evidence(r, locator=f"calendar card {key}", excerpt=date))
    ctx.count("fetched", len(items))
    ctx.note(f"{n_exh} from exhibitions page + {len(items) - n_exh} from today's calendar; current/upcoming only, no public archive listing")
    for key, it in items.items():
        venue = (it["venue"] or "").lower()
        hit = next((k for k in CITY_CC if k in venue), None)
        city, country = CITY_CC[hit] if hit else (None, None)
        if not hit:
            ctx.note(f"venue city unknown: {it['venue']}")
        C.store_exhibition(ctx, key=key, title=it["title"], url=it["url"], ev=it["ev"], organizer=org, city=city, country=country,
                           date_text=f"{it['date']} @ {it['venue'] or '?'}", dates_tuple=_pdates(it["date"]),
                           desc=it["desc"], lang="en")
    ctx.con.commit()


def _pdates(t):
    return C.range_dates(t)


CITY_CC = {"paris": ("Paris", "FR"), "metz": ("Metz", "FR"), "málaga": ("Málaga", "ES"), "malaga": ("Málaga", "ES"),
           "brussels": ("Brussels", "BE"), "bruxelles": ("Brussels", "BE"), "shanghai": ("Shanghai", "CN"),
           "séoul": ("Seoul", "KR"), "seoul": ("Seoul", "KR"), "amsterdam": ("Amsterdam", "NL"), "auxerre": ("Auxerre", "FR"),
           "flaine": ("Flaine", "FR"), "centre-val de loire": (None, "FR"), "mexico": ("Mexico City", "MX"),
           "hambourg": ("Hamburg", "DE"), "hamburg": ("Hamburg", "DE"), "toulon": ("Toulon", "FR"), "riga": ("Riga", "LV"),
           "izmir": ("Izmir", "TR"), "aix-en-provence": ("Aix-en-Provence", "FR"), "lyon": ("Lyon", "FR"),
           "jersey city": ("Jersey City", "US")}


# ---------------------------------------------------------------- MAXXI
def _maxxi(ctx):
    org = C.org(ctx, "MAXXI Museo nazionale delle arti del XXI secolo", url="https://www.maxxi.art")
    r = ctx.fetch("https://www.maxxi.art/en/eventi/feed/")
    items = parse_feed(r.content)
    ctx.count("fetched", len(items))
    ctx.note("RSS lists current+upcoming events only (~45 items); multi-day 'All day' ranges kept as exhibitions, single-date talks/workshops skipped")
    raw = {}
    for blk in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        m = re.search(r"<link>([^<]+)</link>.*?<description><!\[CDATA\[(.*?)\]\]>", blk, re.S)
        if m:
            raw[m.group(1).strip()] = m.group(2)
    for it in items:
        if " > " not in it["summary"]:
            continue  # single-day programme items (talks, workshops)
        parts = [clean_text(p) for p in re.split(r"<br\s*/?>", raw.get(it["link"], "")) if clean_text(p)]
        date_line = re.sub(r"\s*-\s*(All day|\d{1,2}:\d{2})\s*$", "", parts[0] if parts else it["summary"])
        venue = parts[1] if len(parts) > 1 else None
        city = parts[-1] if len(parts) > 2 else None
        city = {"Roma": "Rome"}.get(city, city)
        s, sp, e, ep = parse_date_range(date_line.replace(" > ", " – "))
        ev = ctx.evidence(r, locator=f"rss item {it['link']}", excerpt=f"{date_line} | {venue}")
        C.store_exhibition(ctx, key=it["link"], title=it["title"], url=it["link"], ev=ev, organizer=org, city=city,
                           country="IT" if city else None, date_text=date_line, dates_tuple=(s, sp, e, ep), lang="en")
    ctx.con.commit()


# ---------------------------------------------------------------- MACBA
def _macba(ctx):
    org = C.org(ctx, "MACBA Museu d'Art Contemporani de Barcelona", url="https://www.macba.cat")
    pages = 6 if ctx.mode == "initial" else 1
    items = []
    for p in range(1, pages + 1):
        try:
            r = ctx.fetch("https://www.macba.cat/en/exhibitions/feed/", params={"paged": p} if p > 1 else None)
        except FetchError:
            break  # WordPress returns 404 past the last page
        got = parse_feed(r.content)
        if not got:
            break
        items.extend(got)
    ctx.count("fetched", len(items))
    ctx.note(f"RSS feed paginated ({len(items)} items over <= {pages} pages, ordered by post date)")
    seen = set()
    for it in items:
        url = it["link"]
        if url in seen:
            continue
        seen.add(url)
        if not C.needs_detail(ctx, url):
            continue
        r = C.try_fetch(ctx, url)
        if r is None:
            continue
        s = BeautifulSoup(r.text, "lxml")
        date_text, curators = None, []
        for cd in s.select(".card-data"):
            lab = clean_text((cd.select_one(".macba-type") or cd).get_text(" ")).lower()
            val = clean_text((cd.select_one(".card-meta-information") or cd).get_text(" "))
            if lab == "dates" and not date_text:
                date_text = val
            elif lab.startswith("curat") and not curators:
                curators = [clean_text(x) for x in re.split(r",| and | y | i ", val) if clean_text(x)]
        if not date_text and s.select_one(".macba-type-content"):
            date_text = clean_text(s.select_one(".macba-type-content").get_text(" "))
        ev = ctx.evidence(r, locator="detail card-data dates", excerpt=date_text)
        C.store_exhibition(ctx, key=url, title=it["title"], url=url, ev=ev, organizer=org, city="Barcelona", country="ES",
                           date_text=date_text, desc=it["summary"], curators=curators, image=C.og(r.text, "image"),
                           image_basis="MACBA image captions carry © artist / MACBA Collection; no open licence")
        ctx.con.commit()
    ctx.con.commit()
