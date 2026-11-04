"""Verified public European museum exhibitions and documented Rijksmuseum data."""
from __future__ import annotations

import base64
import datetime as dt
import re
import urllib.parse

from bs4 import BeautifulSoup
from lxml import etree

from .. import db
from ..config import now_kst
from . import eu_common as C
from ._common import clean_text, parse_date_range

PARSER_VERSION = "wave2_museumseu-1"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XML = "http://www.w3.org/XML/1998/namespace"
OAI_BASE = "https://data.rijksmuseum.nl/oai"
EDM = "http://www.europeana.eu/schemas/edm/"
OAI_EARLIEST = "2024-08-15T13:51:17Z"
OAI_PAGE_LIMIT = 250
OAI_CURSOR_PREFIX = "rijksmuseum_oai_cursor="
TATE_COLLECTION_URL = "https://www.tate.org.uk/collection"
TATE_PAGE_LIMIT = 249
TATE_CURSOR_PREFIX = "tate_collection_page="
SINCE = "2023-01-01"

SOURCES = [
    dict(source_id="national_gallery_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="National Gallery, London — Exhibitions", owner_group="National Gallery, London",
         source_kind="museum", region_scope="EUROPE", country_codes="GB", access_method="html",
         base_url="https://www.nationalgallery.org.uk", entry_url="https://www.nationalgallery.org.uk/exhibitions",
         terms_url="https://www.nationalgallery.org.uk/terms-of-use", text_storage_policy="raw_internal",
         priority="P2", notes="Saved official current/upcoming and past exhibition HTML; terms text not captured; record-level image rights not inferred.",
         max_requests=80),
    dict(source_id="palaisdetokyo_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Palais de Tokyo — Exhibitions", owner_group="Palais de Tokyo", source_kind="museum",
         region_scope="EUROPE", country_codes="FR", access_method="html", base_url="https://palaisdetokyo.com",
         entry_url="https://palaisdetokyo.com/en/agenda-palais-de-tokyo/",
         terms_url="https://palaisdetokyo.com/en/terms/", text_storage_policy="raw_internal", priority="P2",
         notes="Saved official exhibition detail pages link to the public What's On agenda; terms and robots text not captured; image rights are not inferred.",
         max_requests=160),
    dict(source_id="warsaw_modern_art_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Museum of Modern Art in Warsaw — Exhibitions", owner_group="Museum of Modern Art in Warsaw",
         source_kind="museum", region_scope="EUROPE", country_codes="PL", access_method="html",
         base_url="https://artmuseum.pl", entry_url="https://artmuseum.pl/en/wystawy-1", terms_url=None,
         text_storage_policy="raw_internal", priority="P2",
         notes="Official saved exhibition detail pages link to current and past exhibition pages; terms, robots, and record-level image rights not verified.",
         max_requests=120),
    dict(source_id="rijksmuseum_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Rijksmuseum — Exhibitions", owner_group="Rijksmuseum", source_kind="museum",
         region_scope="EUROPE", country_codes="NL", access_method="html", base_url="https://www.rijksmuseum.nl",
         entry_url="https://www.rijksmuseum.nl/en/whats-on/exhibitions/now-on-view",
         terms_url="https://www.rijksmuseum.nl/en/footer/terms-and-conditions", text_storage_policy="raw_internal",
         priority="P2", notes="Saved official current/upcoming and past listing pages; image rights are not inferred from the general terms.",
         max_requests=10),
    dict(source_id="rijksmuseum_collection_oai_pmh", blueprint_data_id=None, blueprint_org_id=None,
         name="Rijksmuseum — Collection OAI-PMH (EDM)", owner_group="Rijksmuseum", source_kind="museum",
         region_scope="EUROPE", country_codes="NL", access_method="api", base_url=OAI_BASE,
         entry_url=OAI_BASE, terms_url="https://data.rijksmuseum.nl/en/policy", text_storage_policy="raw_internal",
         priority="P1", notes="Official OAI-PMH documentation says no API key is needed and lists EDM metadata; policy and item-level rights remain separate.",
         min_interval=3, max_requests=OAI_PAGE_LIMIT + 1),
    dict(source_id="tate_collection_html", blueprint_data_id=None, blueprint_org_id=None,
         name="Tate — Collection catalogue listings", owner_group="Tate", source_kind="museum",
         region_scope="EUROPE", country_codes="GB", access_method="html", base_url="https://www.tate.org.uk",
         entry_url=TATE_COLLECTION_URL,
         terms_url="https://www.tate.org.uk/about-us/policies-and-procedures/website-terms-use",
         text_storage_policy="metadata_only", priority="P1",
         disabled="Current Tate collection-listing collection is disabled pending explicit permission: the website terms found in the existing Tate registry summary permit only personal non-commercial use and specified exceptions, while project commercial/non-commercial status is unestablished; no metadata/database-specific grant was found. This is not a robots restriction.",
         notes="Official collection search HTML and explicit pagers expose artwork accession URL, title, creator label and date; no item detail pages, long descriptions, images or raw HTML are stored. Current web listing collection remains disabled pending permission: existing terms evidence does not establish a metadata/database-specific licence or applicability of the personal non-commercial exception; third-party image rights remain item-specific.",
         robots_status="parsed(allowed collection listing)", operational_state="blocked_permission",
         st_live_response="Fetcher verified collection index and explicit page=2 returned HTTP 200 on 2026-10-28; index reported 66,768 results.",
         st_collection_terms="Existing Tate terms summary limits site content to personal non-commercial use and specified research/private-study/criticism/review exceptions; project commercial status and any metadata/database-specific permission are unestablished, so this collector is disabled pending permission.",
         st_image_terms="Item-level third-party artwork rights not verified; no image URLs or image assets collected.",
         min_interval=3, max_requests=TATE_PAGE_LIMIT + 1),
    dict(source_id="musee_orsay_entry", blueprint_data_id=None, blueprint_org_id=None,
         name="Musée d'Orsay — official entry route", owner_group="Musée d'Orsay", source_kind="museum",
         region_scope="EUROPE", country_codes="FR", access_method="html", base_url="https://www.musee-orsay.fr",
         entry_url="https://www.musee-orsay.fr/", terms_url=None, text_storage_policy="metadata_only",
         priority="P2", disabled="Identified Fetcher received HTTP 403 from this exact official entry URL after robots allowed it (checked 2026-10-28); no bypass attempted; alternate official routes unverified.",
         operational_state="blocked_access", robots_status="parsed(allow entry path)",
         st_live_response="blocked(HTTP 403 on entry URL)",
         notes="Only the official homepage route was checked; no institution-wide access conclusion is implied."),
    dict(source_id="museo_del_prado_entry", blueprint_data_id=None, blueprint_org_id=None,
         name="Museo del Prado — official entry route", owner_group="Museo del Prado", source_kind="museum",
         region_scope="EUROPE", country_codes="ES", access_method="html", base_url="https://www.museodelprado.es",
         entry_url="https://www.museodelprado.es/", terms_url=None, text_storage_policy="metadata_only",
         priority="P2", disabled="Identified Fetcher's robots lookup returned HTTP 403 (checked 2026-10-28); target page was not requested and no bypass attempted.",
         operational_state="blocked_access", robots_status="robots_http_403(not_crawled)",
         st_live_response="not_requested(robots unavailable)",
         notes="Only the official host's robots check was attempted; site content and other official routes remain unverified."),
    dict(source_id="kiasma_web_entry", blueprint_data_id=None, blueprint_org_id=None,
         name="Kiasma — official website route", owner_group="Finnish National Gallery", source_kind="museum",
         region_scope="EUROPE", country_codes="FI", access_method="html", base_url="https://kiasma.fi",
         entry_url="https://kiasma.fi/", terms_url=None, text_storage_policy="metadata_only",
         priority="P2", disabled="The parsed kiasma.fi robots rules contain User-agent: * / Disallow: / (checked 2026-10-28); no bypass attempted.",
         operational_state="blocked_permission", robots_status="parsed(Disallow: / for *)",
         st_live_response="not_requested(robots disallow)",
         notes="Robots restriction applies to kiasma.fi routes; no claim is made about other Finnish National Gallery hosts."),
    dict(source_id="louisiana_entry", blueprint_data_id=None, blueprint_org_id=None,
         name="Louisiana Museum — official entry route", owner_group="Louisiana Museum of Modern Art",
         source_kind="museum", region_scope="EUROPE", country_codes="DK", access_method="html",
         base_url="https://louisiana.dk", entry_url="https://louisiana.dk/", terms_url=None,
         text_storage_policy="metadata_only", priority="P2",
         disabled="Identified Fetcher's robots lookup returned HTTP 403 (checked 2026-10-28); target page was not requested and no bypass attempted.",
         operational_state="blocked_access", robots_status="robots_http_403(not_crawled)",
         st_live_response="not_requested(robots unavailable)",
         notes="Only the official host's robots check was attempted; site content and other official routes remain unverified."),
]


def collect(ctx):
    handlers = {
        "national_gallery_exhibitions": _national_gallery,
        "palaisdetokyo_exhibitions": _palaisdetokyo,
        "warsaw_modern_art_exhibitions": _warsaw,
        "rijksmuseum_exhibitions": _rijksmuseum_exhibitions,
        "rijksmuseum_collection_oai_pmh": _rijksmuseum_collection,
        "tate_collection_html": _tate_collection,
    }
    try:
        handler = handlers[ctx.source_id]
    except KeyError:
        raise ValueError(ctx.source_id)
    handler(ctx)


def _org(ctx, name, url):
    return C.org(ctx, name, url=url)


def _parse_dates(text, month_first=False):
    if month_first:
        m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:to|[-–—])\s*(\d{1,2})/(\d{1,2})/(\d{4})", text, re.I)
        if m:
            m1, d1, y1, m2, d2, y2 = map(int, m.groups())
            if 1 <= m1 <= 12 and 1 <= m2 <= 12 and 1 <= d1 <= 31 and 1 <= d2 <= 31:
                try:
                    normalized = (f"{dt.date(y1, m1, d1).strftime('%B')} {d1} {y1} – "
                                  f"{dt.date(y2, m2, d2).strftime('%B')} {d2} {y2}")
                except ValueError:
                    return None, None, None, None
                return parse_date_range(normalized)
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.?(?:\s*(\d{4}))?\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.?(?:\s*(\d{4}))?", text)
        if m:
            d1, m1, y1, d2, m2, y2 = m.groups()
            if y1 or y2:
                d1, m1, d2, m2 = map(int, (d1, m1, d2, m2))
                y1, y2 = int(y1 or y2), int(y2 or y1)
                if not m.group(3) and m1 > m2:
                    y1 -= 1
                elif not m.group(6) and m2 < m1:
                    y2 += 1
                try:
                    start = dt.date(y1, m1, d1).isoformat()
                    end = dt.date(y2, m2, d2).isoformat()
                except ValueError:
                    return None, None, None, None
                return start, "day", end, "day"
    return parse_date_range(text)


def _date_values(node, month_first=False):
    if node is None:
        return None, (None, None, None, None)
    times = node.select("time") if hasattr(node, "select") else []
    if times:
        values = [clean_text(t.get("datetime") or t.get_text(" ")) for t in times]
        values = [v for v in values if v]
        if values:
            text = " – ".join(values)
            return text, _parse_dates(text, month_first)
    for el in node.select('[class*="date"], [class*="Date"], [class*="term"], [class*="Term"]'):
        text = clean_text(el.get("datetime") or el.get_text(" "))
        dates = _parse_dates(text, month_first)
        if any(dates):
            return text, dates
    for line in node.get_text("\n").splitlines():
        text = clean_text(line)
        if not text or not re.search(r"\b(?:19|20)\d{2}\b", text):
            continue
        dates = _parse_dates(text, month_first)
        if any(dates) and (dates[0] or dates[2]):
            return text, dates
    return None, (None, None, None, None)


def _card_for(a):
    node = a
    fallback = a
    for _ in range(9):
        if node is None:
            break
        text = clean_text(node.get_text(" "))
        if len(text) <= 900:
            fallback = node
        date_text, _ = _date_values(node)
        if date_text:
            return node
        if node.name in ("article", "li") and len(text) <= 900:
            fallback = node
        node = node.parent
    return fallback


def _title(a, card):
    for heading in card.find_all(["h1", "h2", "h3", "h4"]):
        value = clean_text(heading.get_text(" "))
        if value and value.casefold() not in {"exhibitions", "exhibition", "past exhibitions", "current exhibitions"}:
            return value
    for line in card.get_text("\n").splitlines():
        value = clean_text(line)
        if not value or value.casefold() in {"exhibitions", "exhibition", "past exhibition", "free", "find out more"}:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", value) or parse_date_range(value)[0] or parse_date_range(value)[2]:
            continue
        value = re.sub(r"^(?:£\s*)?(?:free\s+)?(?:past\s+)?exhibition\s+", "", value, flags=re.I).strip()
        if value and value.casefold() not in {"exhibitions", "exhibition"}:
            return value
    return clean_text(a.get("aria-label") or a.get_text(" "))


def _image(card, base):
    img = card.find("img") if hasattr(card, "find") else None
    if img is None:
        return None
    src = img.get("src") or img.get("data-src")
    if not src and img.get("srcset"):
        src = img.get("srcset").split(",", 1)[0].strip().split(" ", 1)[0]
    if not src or src.startswith("data:"):
        return None
    return urllib.parse.urljoin(base, src)


def _valid_since(dates):
    last = dates[2] or dates[0]
    return not last or last >= SINCE


def _listing_records(response, base, path_prefix, excluded_paths=()):
    soup = BeautifulSoup(response.text, "lxml")
    base_host = urllib.parse.urlsplit(base).hostname
    records = {}
    for a in soup.select("a[href]"):
        url = urllib.parse.urljoin(base, a["href"])
        parsed_url = urllib.parse.urlsplit(url)
        path = parsed_url.path.rstrip("/")
        if parsed_url.scheme != "https" or parsed_url.hostname != base_host:
            continue
        if not path.startswith(path_prefix) or path in excluded_paths:
            continue
        card = _card_for(a)
        title = _title(a, card)
        if not title or title.casefold() in {"exhibitions", "exhibition", "past exhibitions"}:
            continue
        date_text, dates = _date_values(card)
        if not _valid_since(dates):
            continue
        previous = records.get(url)
        if previous is None or (not previous[1] and date_text):
            records[url] = (title, date_text, dates, card)
    return records


def _store_event(ctx, response, *, url, title, date_text, dates, organizer, city, country, image, image_basis, locator):
    evidence = ctx.evidence(response, locator=locator, excerpt=(date_text or title)[:300])
    C.store_exhibition(ctx, key=url, title=title, url=url, ev=evidence, organizer=organizer,
                       city=city, country=country, date_text=date_text, dates_tuple=dates,
                       image=image, image_basis=image_basis)


def _next_page(soup, current_url):
    for a in soup.select('a[rel~="next"], .pagination a, nav[aria-label*="pagination" i] a'):
        label = clean_text(" ".join((a.get("aria-label", ""), a.get("title", ""), a.get_text(" ")))).casefold()
        if a.get("rel") == "next" or re.search(r"\b(next|older|more)\b", label):
            href = a.get("href")
            if href:
                return urllib.parse.urljoin(current_url, href)
    return None


def _national_gallery(ctx):
    base = "https://www.nationalgallery.org.uk"
    org = _org(ctx, "The National Gallery, London", base)
    pages = [(base + "/exhibitions", "current/upcoming")]
    if ctx.mode == "initial":
        pages.append((base + "/exhibitions/past", "past archive"))
    records = {}
    for first_url, label in pages:
        page_url = first_url
        max_pages = 20 if ctx.mode == "initial" and label == "past archive" else 1
        for page_no in range(max_pages):
            response = ctx.fetch(page_url)
            page_records = _listing_records(response, base, "/exhibitions/",
                                            excluded_paths={"/exhibitions", "/exhibitions/past", "/exhibitions/across-the-uk"})
            for url, value in page_records.items():
                records[url] = (response, *value, label)
            ctx.con.commit()
            next_url = _next_page(BeautifulSoup(response.text, "lxml"), response.url)
            if not next_url or next_url == page_url:
                break
            page_url = next_url
    ctx.count("fetched", len(records))
    for url, (response, title, date_text, dates, card, label) in records.items():
        image = _image(card, response.url)
        _store_event(ctx, response, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                     city="London", country="GB", image=image,
                     image_basis="National Gallery exhibition image; record-level credit governs, no open licence inferred",
                     locator=f"{label} exhibition card {url}")
        ctx.con.commit()
    ctx.note("Current/upcoming listing plus the public past-exhibitions page in initial mode; follows only explicit pagination links (up to 20 pages). Listings provide date text when printed; no collection, press, or annual-report coverage is implied.")
    ctx.con.commit()


def _palais_detail(response):
    soup = BeautifulSoup(response.text, "lxml")
    heading = soup.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else None
    date_node = soup.select_one(".date") or soup.select_one('[class*="date"]')
    date_text, dates = _date_values(date_node or soup, month_first=True)
    image = None
    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and meta.get("content"):
        image = urllib.parse.urljoin(response.url, meta["content"])
    if not image:
        image = _image(soup, response.url)
    return title, date_text, dates, image


def _palaisdetokyo(ctx):
    base = "https://palaisdetokyo.com"
    org = _org(ctx, "Palais de Tokyo", base)
    response = ctx.fetch(base + "/en/agenda-palais-de-tokyo/")
    records = _listing_records(response, base, "/en/exposition/")
    ctx.count("fetched", len(records))
    for url, (title, date_text, dates, card) in records.items():
        detail = response
        detail_title, detail_date, detail_dates, image = None, None, (None, None, None, None), None
        if C.needs_detail(ctx, url):
            detail = ctx.fetch(url)
            detail_title, detail_date, detail_dates, image = _palais_detail(detail)
        title = detail_title or title
        date_text = detail_date or date_text
        if any(detail_dates):
            dates = detail_dates
        image = image or _image(card, response.url)
        _store_event(ctx, detail, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                     city="Paris", country="FR", image=image,
                     image_basis="Palais de Tokyo exhibition image; no item-level open licence verified",
                     locator=f"exhibition detail title/date {url}" if detail is not response else f"agenda card {url}")
        ctx.con.commit()
    ctx.note("Official What's On agenda and exhibition detail pages only; detail lookups are limited to records needing an initial/current update. Saved probes establish public detail pages but not an archive depth; no historical completeness is claimed.")
    ctx.con.commit()


def _warsaw(ctx):
    base = "https://artmuseum.pl"
    org = _org(ctx, "Museum of Modern Art in Warsaw", base)
    pages = [(base + "/en/wystawy-1", "current/upcoming")]
    if ctx.mode == "initial":
        pages.append((base + "/en/wystawy-przeszle-1", "past exhibitions"))
    records = {}
    for page_url, label in pages:
        response = ctx.fetch(page_url)
        # Detail links were /en/wystawa/... and, as observed on 2026-10-28, /en/exhibitions/...
        page_records = _listing_records(response, base, ("/en/wystaw", "/en/exhibitions/"))
        for url, value in page_records.items():
            path = urllib.parse.urlsplit(url).path.rstrip("/")
            if path in {"/en/wystawy-1", "/en/wystawy-przeszle-1"}:
                continue
            records[url] = (response, *value, label)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (response, title, date_text, dates, card, label) in records.items():
        _store_event(ctx, response, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                     city=None, country=None, image=_image(card, response.url),
                     image_basis="Museum of Modern Art in Warsaw exhibition image; record-level rights not verified",
                     locator=f"{label} exhibition card {url}")
        ctx.con.commit()
    ctx.note("Official current exhibition page; initial mode also reads the past-exhibitions page linked from official exhibition detail navigation. Listing fields are stored only when displayed; no complete archive claim.")
    ctx.con.commit()


def _rijksmuseum_exhibitions(ctx):
    base = "https://www.rijksmuseum.nl"
    org = _org(ctx, "Rijksmuseum", base)
    pages = [(base + "/en/whats-on/exhibitions/now-on-view", "current/upcoming")]
    if ctx.mode == "initial":
        pages.append((base + "/en/whats-on/exhibitions/past", "past exhibitions"))
    records = {}
    for page_url, label in pages:
        response = ctx.fetch(page_url)
        for url, value in _listing_records(
                response, base, "/en/whats-on/exhibitions/",
                excluded_paths={"/en/whats-on/exhibitions/past", "/en/whats-on/exhibitions/now-on-view"}).items():
            if url.rstrip("/") in {page.rstrip("/") for page, _ in pages}:
                continue
            records[url] = (response, *value, label)
        ctx.con.commit()
    ctx.count("fetched", len(records))
    for url, (response, title, date_text, dates, card, label) in records.items():
        _store_event(ctx, response, url=url, title=title, date_text=date_text, dates=dates, organizer=org,
                     city="Amsterdam", country="NL", image=_image(card, response.url),
                     image_basis="Rijksmuseum exhibition image; item-level rights not inferred from general data policy",
                     locator=f"{label} exhibition card {url}")
        ctx.con.commit()
    ctx.note("Current/upcoming official exhibition listing; initial mode reads the public past-exhibitions page. Its page text says the overview extends back to 1883; this is not a claim that every historical record was parsed. Only printed dates are stored.")
    ctx.con.commit()


def _tate_collection_page_url(page):
    if page == 1:
        return TATE_COLLECTION_URL
    return TATE_COLLECTION_URL + "?tab=collection&page=" + str(page)


def _tate_next_page(response, current_page):
    soup = BeautifulSoup(response.text, "lxml")
    for anchor in soup.select('a[data-gtm-name="pager_link_next"][href]'):
        target = urllib.parse.urljoin(response.url, anchor["href"])
        parsed = urllib.parse.urlsplit(target)
        query = urllib.parse.parse_qs(parsed.query)
        page_values = query.get("page", [])
        if (parsed.scheme != "https" or parsed.netloc != "www.tate.org.uk" or parsed.path != "/collection"
                or query.get("tab") != ["collection"] or len(page_values) != 1):
            continue
        try:
            page = int(page_values[0])
        except ValueError:
            continue
        if page > current_page:
            return page
    return None


def _tate_cursor_note(page):
    return TATE_CURSOR_PREFIX + ("done" if page is None else str(page))


def _saved_tate_page(ctx):
    current_run = getattr(ctx, "run_id", None)
    if current_run:
        row = ctx.con.execute(
            "SELECT error FROM crawl_runs WHERE source_id=? AND mode='initial' AND run_id<>? "
            "ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (ctx.source_id, current_run),
        ).fetchone()
    else:
        row = ctx.con.execute(
            "SELECT error FROM crawl_runs WHERE source_id=? AND mode='initial' "
            "ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (ctx.source_id,),
        ).fetchone()
    if row is None or not row["error"]:
        return 1
    markers = re.findall(re.escape(TATE_CURSOR_PREFIX) + r"([^;\s]+)", row["error"])
    if not markers or markers[-1] == "done":
        return 1
    try:
        page = int(markers[-1])
    except ValueError as exc:
        raise ValueError("saved Tate collection page cursor is corrupt") from exc
    if page < 1:
        raise ValueError("saved Tate collection page cursor is invalid")
    return page


def _persist_tate_page(ctx, page):
    run_id = getattr(ctx, "run_id", None)
    if run_id:
        ctx.con.execute("UPDATE crawl_runs SET error=? WHERE run_id=? AND source_id=?",
                        (_tate_cursor_note(page), run_id, ctx.source_id))
        ctx.con.commit()


def _tate_accession(url):
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    match = re.search(r"(?:^|-)([a-z]\d{3,})$", slug, re.I)
    return match.group(1).upper() if match else path


def _tate_artist(ctx, name, evidence):
    if re.search(r"\b(with|and)\b|&", name, re.I):
        entity_type = "unknown"
    elif re.search(r"\b(arts trust|collective|group|studio|workshop|atelier|company)\b", name, re.I):
        entity_type = "group"
    else:
        entity_type = "person"
    return db.ensure_entity(ctx.con, entity_type=entity_type, name=name,
                            namespace=f"src:{ctx.source_id}", source_id=ctx.source_id,
                            evidence_id=evidence)


def _tate_collection_records(response):
    soup = BeautifulSoup(response.text, "lxml")
    count_node = soup.select_one(".results-count__text")
    result_count = clean_text(count_node.get_text(" ")) if count_node else None
    records = {}
    for anchor in soup.select('a[href*="/art/artworks/"]'):
        url = urllib.parse.urljoin(response.url, anchor.get("href", ""))
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "www.tate.org.uk" or not parsed.path.startswith("/art/artworks/"):
            continue
        card = anchor.find_parent(class_="card")
        if card is None:
            continue
        title_node = card.select_one(".card__title")
        title = clean_text(title_node.get_text(" ")) if title_node else None
        if not title:
            continue
        artists = [clean_text(node.get_text(" ")) for node in card.select(".card__title--artwork-artist")]
        artists = [name for name in artists if name]
        date_node = card.select_one(".card__when--artwork-date")
        date_text = clean_text(date_node.get_text(" ")) if date_node else None
        object_id = _tate_accession(url)
        records[object_id] = (url, title, artists[0] if len(artists) == 1 else None, date_text)
    return records, result_count


def _tate_collection(ctx):
    holding = _org(ctx, "Tate", "https://www.tate.org.uk/about-us/collection")
    page = _saved_tate_page(ctx) if ctx.mode == "initial" else 1
    page_limit = TATE_PAGE_LIMIT if ctx.mode == "initial" else 1
    count_text = None
    pages_read = 0
    total = 0
    next_page = page
    try:
        while pages_read < page_limit:
            if ctx.mode == "initial":
                _persist_tate_page(ctx, page)
            response = ctx.fetch(_tate_collection_page_url(page), store=False)
            records, result_count = _tate_collection_records(response)
            count_text = count_text or result_count
            ctx.count("fetched", len(records))
            for object_id, (url, title, artist_name, date_text) in records.items():
                evidence = ctx.evidence(response, locator=f"collection result card {url}", excerpt=title)
                artist = _tate_artist(ctx, artist_name, evidence) if artist_name else None
                db.upsert_work(ctx.con, ctx.stats, id_namespace=ctx.source_id, id_value=object_id,
                               source_id=ctx.source_id, artist_entity_id=artist, title=title,
                               date_text=date_text, holding_entity_id=holding, url=url,
                               is_public_domain=None)
                ctx.count("parsed")
            ctx.con.commit()
            pages_read += 1
            total += len(records)
            next_page = _tate_next_page(response, page) if ctx.mode == "initial" else None
            if ctx.mode == "initial":
                _persist_tate_page(ctx, next_page)
            if next_page is None:
                break
            page = next_page
    except Exception:
        if ctx.mode == "initial":
            ctx.note(_tate_cursor_note(page))
        raise
    capped = ctx.mode == "initial" and bool(next_page) and pages_read >= page_limit
    if ctx.mode == "initial":
        ctx.note(_tate_cursor_note(next_page))
    ctx.note(f"Official Tate collection HTML listing; {total} work cards parsed across {pages_read} page(s); listing count text: {count_text or 'not present'}. Fields are only accession ID from official work URL, visible title, a single visible artist label, and printed date text. No artwork detail pages, long descriptions, image URLs, image assets, or raw page bodies are stored; medium, dimensions, acquisition details, and image rights remain unknown.")
    if ctx.mode == "initial":
        ctx.note(f"Initial mode follows only the official HTML next-page link and resumes from the stored page cursor, capped at {page_limit} pages per run.")
    else:
        ctx.note("Incremental mode reads only the first official collection results page.")
    if capped:
        ctx.note(f"The initial collection harvest stopped at its {page_limit}-page cap with a durable next-page cursor; this is partial coverage, not the end of the collection.")
    ctx.con.commit()


def _local(element):
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _namespace(element):
    return etree.QName(element).namespace if isinstance(element.tag, str) else None


def _element_text(el):
    return clean_text(" ".join(el.itertext())) if el is not None else ""


def _record_payload(record):
    if record.find(".//{%s}header" % "http://www.openarchives.org/OAI/2.0/") is None:
        return None
    header = record.find(".//{%s}header" % "http://www.openarchives.org/OAI/2.0/")
    if header.get("status") == "deleted":
        return None
    identifier = _element_text(next((el for el in header if _local(el) == "identifier"), None))
    cho = next((el for el in record.iter() if _local(el) == "ProvidedCHO"), None)
    if cho is None:
        return None
    labels = {}
    for el in record.iter():
        about = el.get("{%s}about" % RDF)
        if not about:
            continue
        for child in el:
            if _local(child) in {"prefLabel", "name", "label"} and _element_text(child):
                labels[about] = _element_text(child)
                break
    def vals(names):
        out = []
        for el in cho.iter():
            if _local(el) in names:
                value = _element_text(el) or el.get("{%s}resource" % RDF)
                if value:
                    out.append((value, el.get("{%s}lang" % XML)))
        return out
    titles = vals({"title"})
    title = next((v for v, lang in titles if lang and lang.lower().startswith("en")), None)
    title = title or (titles[0][0] if titles else None)
    if not title:
        return None
    object_ids = vals({"identifier"})
    object_id = object_ids[0][0] if object_ids else cho.get("{%s}about" % RDF) or identifier
    creators = []
    for el in cho.iter():
        if _local(el) != "creator":
            continue
        value = el.get("{%s}resource" % RDF) or _element_text(el)
        if value:
            creators.append((value, labels.get(value), el.get("{%s}lang" % XML)))
    dates = vals({"created"})
    date_text = next((v for v, lang in dates if lang and lang.lower().startswith("en")), None)
    date_text = date_text or (dates[0][0] if dates else None)
    mediums = vals({"medium", "format"})
    medium = next((v for v, lang in mediums if lang and lang.lower().startswith("en")), None)
    medium = medium or (mediums[0][0] if mediums else None)
    types = vals({"type"})
    classification = next((labels.get(v, v) for v, _ in types if v), None)
    provenance = vals({"provenance"})
    acquisition = provenance[0][0] if provenance else None
    shown_at = None
    for el in record.iter():
        if _local(el) != "isShownAt" or _namespace(el) != EDM:
            continue
        shown_at = el.get("{%s}resource" % RDF)
        if not shown_at:
            shown_at = next((child.get("{%s}about" % RDF) for child in el.iter()
                             if _local(child) == "WebResource" and child.get("{%s}about" % RDF)), None)
        if shown_at:
            break
    rights = [el.get("{%s}resource" % RDF) or _element_text(el) for el in record.iter()
              if _local(el) == "rights" and _namespace(el) == EDM
              and (el.get("{%s}resource" % RDF) or _element_text(el))]
    image = None
    for el in record.iter():
        if _local(el) not in {"isShownBy", "preview"} or _namespace(el) != EDM:
            continue
        image = el.get("{%s}about" % RDF) or el.get("{%s}resource" % RDF)
        if not image:
            image = next((child.get("{%s}about" % RDF) or child.get("{%s}resource" % RDF)
                          for child in el.iter() if _local(child) == "WebResource"
                          and (child.get("{%s}about" % RDF) or child.get("{%s}resource" % RDF))), None)
        if image:
            break
    return dict(identifier=identifier, object_id=object_id, title=title, creators=creators,
                date_text=date_text, medium=medium, classification=classification,
                acquisition=acquisition, url=shown_at, rights=rights[0] if rights else None, image=image)


def _parse_oai_page(content):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(content, parser=parser)
    records = [payload for record in root.iter() if _local(record) == "record"
               for payload in [_record_payload(record)] if payload]
    token = next((_element_text(el) for el in root.iter() if _local(el) == "resumptionToken"), None)
    errors = [(el.get("code"), _element_text(el)) for el in root.iter() if _local(el) == "error"]
    return records, token or None, errors


def _oai_cursor_note(token):
    encoded = "done" if token is None else base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")
    return OAI_CURSOR_PREFIX + encoded


def _saved_oai_cursor(ctx):
    current_run = getattr(ctx, "run_id", None)
    if current_run:
        row = ctx.con.execute(
            "SELECT error FROM crawl_runs WHERE source_id=? AND mode='initial' AND run_id<>? "
            "ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (ctx.source_id, current_run),
        ).fetchone()
    else:
        row = ctx.con.execute(
            "SELECT error FROM crawl_runs WHERE source_id=? AND mode='initial' "
            "ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (ctx.source_id,),
        ).fetchone()
    if row is None or not row["error"]:
        return None
    markers = re.findall(re.escape(OAI_CURSOR_PREFIX) + r"([^;\s]+)", row["error"])
    if not markers or markers[-1] == "done":
        return None
    encoded = markers[-1]
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("saved Rijksmuseum OAI-PMH continuation cursor is corrupt") from exc


def _persist_oai_cursor(ctx, token):
    run_id = getattr(ctx, "run_id", None)
    if run_id:
        ctx.con.execute("UPDATE crawl_runs SET error=? WHERE run_id=? AND source_id=?",
                        (_oai_cursor_note(token), run_id, ctx.source_id))
        ctx.con.commit()


def _rights_usage(rights):
    if not rights:
        return "unknown", None
    value = rights.strip()
    lower = value.casefold()
    if "publicdomain/mark" in lower or "publicdomain/zero" in lower or "cc0" in lower:
        return "public_domain_cc0", value
    if "incopyright" in lower or "copyright" in lower or "rightsstatements.org/vocab/in" in lower:
        return "restricted", value
    return "unknown", value


def _creator_entity(ctx, creator):
    value, label, lang = creator
    has_uri_scheme = bool(urllib.parse.urlsplit(value).scheme) or value.startswith("_:")
    name = label or (value if not has_uri_scheme else None)
    if not name:
        return None
    entity_type = "group" if re.search(r"\b(collective|group|studio|workshop|atelier|company)\b", name, re.I) else "person"
    if has_uri_scheme:
        return db.ensure_entity(ctx.con, entity_type=entity_type, name=name,
                                namespace=f"{ctx.source_id}:agent", id_value=value,
                                lang=lang, source_id=ctx.source_id)
    return db.ensure_entity(ctx.con, entity_type=entity_type, name=name, namespace=f"src:{ctx.source_id}",
                            lang=lang, source_id=ctx.source_id)


def _store_work(ctx, response, payload, holding):
    object_key = payload["object_id"] or payload["identifier"]
    if not object_key:
        return
    evidence = ctx.evidence(response, locator=f"OAI-PMH record {payload['identifier'] or object_key}",
                            excerpt=payload["title"])
    creator = _creator_entity(ctx, payload["creators"][0]) if payload["creators"] else None
    usage, license_uri = _rights_usage(payload["rights"])
    work_id = db.upsert_work(ctx.con, ctx.stats, id_namespace=ctx.source_id, id_value=object_key,
                             source_id=ctx.source_id, artist_entity_id=creator, title=payload["title"],
                             date_text=payload["date_text"], medium=payload["medium"],
                             classification=payload["classification"], holding_entity_id=holding,
                             acquisition_text=payload["acquisition"], url=payload["url"],
                             is_public_domain=None)
    if payload["image"]:
        basis = ("Per-record EDM rights value: " + license_uri) if license_uri else \
                "No record-level EDM rights value supplied; image reuse unknown. Image not downloaded."
        db.add_image_rights(ctx.con, source_id=ctx.source_id, work_id=work_id, page_url=payload["url"],
                            image_url=payload["image"], usage_status=usage, basis=basis,
                            license=license_uri)
    ctx.count("parsed")


def _rijksmuseum_collection(ctx):
    org = _org(ctx, "Rijksmuseum", "https://www.rijksmuseum.nl")
    if ctx.mode == "initial":
        cursor = _saved_oai_cursor(ctx)
        if cursor:
            params = {"verb": "ListRecords", "resumptionToken": cursor}
            ctx.note(_oai_cursor_note(cursor))
        else:
            params = {"verb": "ListRecords", "metadataPrefix": "edm", "from": OAI_EARLIEST}
        since = OAI_EARLIEST
    else:
        since = (now_kst().date() - dt.timedelta(days=2)).isoformat() + "T00:00:00Z"
        cursor = None
        params = {"verb": "ListRecords", "metadataPrefix": "edm", "from": since}
    page_count = 0
    total = 0
    try:
        while page_count < OAI_PAGE_LIMIT:
            response = ctx.fetch(OAI_BASE, params=params, accept="application/xml")
            records, next_cursor, errors = _parse_oai_page(response.content)
            if errors:
                if any(code == "noRecordsMatch" for code, _ in errors):
                    cursor = None
                    if ctx.mode == "initial":
                        _persist_oai_cursor(ctx, None)
                    ctx.note("OAI-PMH returned no records for the requested datestamp window.")
                    break
                raise ValueError("Rijksmuseum OAI-PMH error: " + "; ".join(message for _, message in errors))
            ctx.count("fetched", len(records))
            for record in records:
                _store_work(ctx, response, record, org)
            ctx.con.commit()
            page_count += 1
            total += len(records)
            cursor = next_cursor
            if ctx.mode == "initial":
                _persist_oai_cursor(ctx, cursor)
            if not cursor:
                break
            params = {"verb": "ListRecords", "resumptionToken": cursor}
    except Exception:
        if ctx.mode == "initial" and cursor:
            ctx.note(_oai_cursor_note(cursor))
        raise
    capped = bool(cursor and page_count >= OAI_PAGE_LIMIT)
    if ctx.mode == "initial":
        ctx.note(_oai_cursor_note(cursor))
    ctx.note(f"Documented keyless OAI-PMH ListRecords (EDM); {total} collection records parsed in {page_count} page(s), filtered by datestamp from {since}. Initial mode starts at the documented earliest datestamp and resumes from its durable OAI continuation token; incremental mode uses a two-day catch-up window. Library/archive records are outside this API, and image rights remain per record.")
    if capped:
        ctx.note(f"OAI-PMH initial harvest stopped at the {OAI_PAGE_LIMIT}-page cap with a durable continuation token; the archive harvest is partial and the next initial run will resume at that token.")
    ctx.note("EDM extent/dimension text is not persisted because the current works schema has no dimensions field; absent work fields remain unknown.")
    ctx.con.commit()
