"""Public exhibitions, programs, and collection metadata for KADIST and The Broad."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from pathlib import Path

from .. import db, region
from ..config import WORK_ROOT, now_kst
from ..http import FetchError
from ._common import clean_text, parse_date_range, soup

PARSER_VERSION = "gl_foundations-6"

KADIST_BASE = "https://kadist.org"
BROAD_BASE = "https://www.thebroad.org"
HISTORY_FLOOR = "2023-01-01"
MAX_ARCHIVE_PAGES = 12
MAX_ARCHIVE_DETAILS = 120
MAX_COLLECTION_PAGES = 16
MAX_WORK_DETAILS = 25
MAX_ARTIST_PAGES = 12
REQUEST_RESERVE = 6

COLLECTION_LISTINGS = (
    ("/art/browse", "New On View", "collection browse; The Broad describes this as over 2,000 works"),
    ("/art/on-view/browse", "Browse the Collection", "on-view display sample; The Broad explicitly describes it as a sample"),
)

_MONTH = (r"January|February|March|April|May|June|July|August|September|October|November|December|"
         r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
_EXPLICIT_DATE = re.compile(
    rf"\b(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b.*\b(?:19|20)\d{{2}}\b|"
    rf"\b\d{{1,2}}\s+(?:{_MONTH})\.?\s+(?:19|20)\d{{2}}\b",
    re.I,
)
_WORK_DATE = re.compile(r"^(.*),\s*((?:ca\.?\s*)?(?:19|20)\d{2}(?:\s*[/–—-]\s*(?:(?:19|20)\d{2}|\d{2}))?)$")
_YEAR_LINE = re.compile(r"^(?:ca\.?\s*)?(?:19|20)\d{2}(?:\s*[/–—-]\s*(?:(?:19|20)\d{2}|\d{2}))?$", re.I)
_DIMENSION_LINE = re.compile(r"(?:\d\s*(?:1/\d+)?\s*(?:x|×)|\b(?:cm|mm|inches|in\.)\b)", re.I)
_LEGACY_EXHIBITION_LABEL = re.compile(r"\b(Collection Exhibition|Special Exhibition|Featured Installation)\b", re.I)
_EXCLUDED_ART_SLUGS = {
    "browse", "exhibitions", "featured-artworks", "featured-installations", "on-view",
    "special-exhibitions", "collection-exhibitions", "free-accesss", "artists",
}

SOURCES = [
    dict(source_id="kadist_public", blueprint_data_id="D53", blueprint_org_id=None,
         name="KADIST — public exhibitions and collection metadata", owner_group="KADIST",
         source_kind="foundation", region_scope="GLOBAL", country_codes="US,FR", access_method="html",
         base_url=KADIST_BASE, entry_url=f"{KADIST_BASE}/exhibitions/",
         terms_url=f"{KADIST_BASE}/terms-of-use/", text_storage_policy="raw_internal", priority="P2",
         st_official_doc="n/a(html)",
         st_collection_terms="terms page returned HTTP 403; public page unavailable (checked 2026-10-28)",
         st_image_terms="not reached (public page returned HTTP 403; checked 2026-10-28)", max_requests=40,
         disabled="HTTP 403 on homepage, exhibition/collection pages, terms page, and public WordPress sitemap "
                  "(checked 2026-10-28); not bypassed",
         notes="Public robots.txt allows general paths and disallows /wp-admin/; public sitemap and content pages "
               "returned HTTP 403. KADIST San Francisco (US) and Paris (FR) venue countries must be taken from "
               "each page if access becomes available.",
         operational_state="blocked_access", robots_status="parsed(allow; Disallow /wp-admin/)",
         st_live_response="blocked(HTTP 403: /, /exhibitions/, /collection/, /terms-of-use/, /wp-sitemap.xml; checked 2026-10-28)"),
    dict(source_id="broad_public", blueprint_data_id="D54", blueprint_org_id=None,
         name="The Broad — exhibitions, public programs, and collection works", owner_group="The Broad",
         source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="html",
         base_url=BROAD_BASE, entry_url=f"{BROAD_BASE}/art/exhibitions/past",
         terms_url=f"{BROAD_BASE}/terms-use", text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(server-rendered HTML exhibitions, events, /art/browse, /art/on-view/browse, linked artist pages)",
         st_collection_terms="Terms of Use permit personal/noncommercial and fair-use research; prohibit other copying "
                             "and commercial downloads without permission; last updated 2021-04-27",
         st_image_terms="images are copyrighted/third-party; retain visible URLs as unknown rights metadata only; request permission for reuse; no assets fetched",
         max_requests=250),
]


def collect(ctx):
    if ctx.source_id == "kadist_public":
        raise RuntimeError("KADIST is registry-only after observed HTTP 403 responses")
    if ctx.source_id != "broad_public":
        raise RuntimeError(f"no collector for {ctx.source_id}")
    return _collect_broad(ctx)


def _collect_broad(ctx):
    organizer = db.ensure_entity(
        ctx.con, entity_type="institution", name="The Broad", namespace=f"src:{ctx.source_id}",
        id_value="the-broad", source_id=ctx.source_id, official_url=BROAD_BASE,
    )
    handled_events = {}
    art_response = _fetch(ctx, f"{BROAD_BASE}/art")
    _consume_event_page(ctx, art_response, organizer, handled_events)

    event_response = _fetch(ctx, f"{BROAD_BASE}/events")
    _consume_event_page(ctx, event_response, organizer, handled_events)

    archive_pages = 1
    archive_details = 0
    archive_dates = []
    archive_page_limit = MAX_ARCHIVE_PAGES if ctx.mode == "initial" else 1
    archive_history_floor_reached = False
    archive_url = SOURCES[1]["entry_url"]
    for page_index in range(archive_page_limit):
        if page_index:
            if archive_details >= MAX_ARCHIVE_DETAILS:
                break
            archive_url = _next_page_url(response.text, response.url, f"{BROAD_BASE}/art/exhibitions/past")
            if not archive_url:
                break
        response = _fetch(ctx, archive_url)
        archive_pages = page_index + 1
        details, starts = _consume_event_page(
            ctx, response, organizer, handled_events, detail_limit=MAX_ARCHIVE_DETAILS - archive_details,
        )
        archive_details += details
        archive_dates.extend(starts)
        if not details and not _event_links(response.text, response.url):
            break
        if ctx.mode != "initial":
            break
        # The official archive is newest-first; stop once a fully dated page is older than the optional floor.
        if starts and all(value < HISTORY_FLOOR for value in starts):
            archive_history_floor_reached = True
            break

    archive_next = _next_page_url(response.text, response.url, f"{BROAD_BASE}/art/exhibitions/past")
    archive_stop_reason = None
    if ctx.mode != "initial":
        archive_stop_reason = "incremental first-page policy"
    elif archive_pages >= archive_page_limit:
        archive_stop_reason = f"{archive_page_limit}-page initial cap"
    elif archive_details >= MAX_ARCHIVE_DETAILS:
        archive_stop_reason = f"{MAX_ARCHIVE_DETAILS}-detail initial cap"
    elif archive_history_floor_reached:
        archive_stop_reason = f"configured {HISTORY_FLOOR} history floor"
    archive_has_more = bool(archive_next and archive_stop_reason)
    (work_pages, work_count, work_details, artist_pages, artist_work_count,
     detail_remaining, artist_remaining, listing_stats) = _collect_works(ctx, organizer)
    if archive_dates:
        ctx.note("past exhibitions archive exposed {} page(s); fetched {} detail(s); oldest fetched start date {}".format(
            archive_pages, archive_details, min(archive_dates),
        ))
        if min(archive_dates) > HISTORY_FLOOR:
            ctx.note("archive did not expose 2023-01-01; the oldest dated fetched exhibition is later")
    else:
        ctx.note(f"past exhibitions archive exposed {archive_pages} page(s) but no parseable dated details")
    if archive_has_more:
        ctx.note(f"past exhibitions archive has another public pager page; stopped at {archive_stop_reason}; "
                 "archive remains partial")
    if archive_details >= MAX_ARCHIVE_DETAILS:
        ctx.note(f"past exhibition detail parsing reached the {MAX_ARCHIVE_DETAILS}-record cap; additional cards may remain on the last listing page")
    ctx.note(f"Collection-route refreshes plus persisted Broad work records contain {work_count} distinct work record(s); "
             f"fetched {work_details} public artwork detail page(s) and {artist_pages} linked artist collection page(s); "
             "these are listing snapshots, not a complete holdings inventory; exhausting a pager frontier does not "
             "establish complete holdings coverage")
    if artist_work_count:
        ctx.note(f"linked artist pages added {artist_work_count} additional distinct work record(s)")
    for route, label, scope, pages, records, frontier_state in listing_stats:
        ctx.note(f"{label} route {route}: {scope}; exposed {records} card(s) on {pages} page(s); "
                 f"listing frontier {frontier_state}")
    if work_details:
        ctx.note("dimensions and accession fields are retained only in internal page evidence because the works schema has no dedicated columns")
    if detail_remaining:
        ctx.note(f"{detail_remaining} publicly linked artwork detail page(s) remain without successful detail evidence; "
                 "later initial/incremental runs prioritize these before already documented pages")
    if work_details >= (MAX_WORK_DETAILS if ctx.mode == "initial" else 10):
        ctx.note(f"artwork-detail sampling reached the {MAX_WORK_DETAILS if ctx.mode == 'initial' else 10}-page mode cap")
    if artist_remaining:
        ctx.note(f"{artist_remaining} publicly linked artist collection page(s) remain without successful listing evidence; "
                 "later initial/incremental runs prioritize these before already documented pages")
    ctx.con.commit()


def _fetch(ctx, url):
    return ctx.fetch(url, accept="text/html")


def _main(html):
    document = soup(html)
    return document.select_one("main, [role='main'], #main-content:not(a)") or document


def _canonical_page_url(url):
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _path(url):
    return urllib.parse.urlsplit(url).path.rstrip("/") or "/"


def _event_links(html, page_url):
    main = _main(html)
    current_section = ""
    rows = []
    seen = set()
    for node in main.find_all(["h1", "h2", "a"]):
        if node.name in ("h1", "h2"):
            current_section = clean_text(node.get_text(" ")).casefold()
            continue
        if not node.get("href"):
            continue
        absolute = urllib.parse.urljoin(page_url, node.get("href", ""))
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.netloc not in ("www.thebroad.org", "thebroad.org"):
            continue
        path = parsed.path.rstrip("/")
        segments = path.strip("/").split("/")
        is_program = len(segments) == 2 and segments[0] == "events"
        is_exhibition = (len(segments) == 3 and segments[:2] in (
            ["art", "special-exhibitions"], ["art", "collection-exhibitions"],
            ["art", "featured-installations"],
        ))
        event_subtype = None
        if not is_exhibition and len(segments) == 1:
            card_text = _event_card_text(node, path)
            match = _LEGACY_EXHIBITION_LABEL.search(card_text)
            if match:
                is_exhibition = True
                label = match.group(1).casefold()
                event_subtype = {"collection exhibition": "collection_display",
                                 "featured installation": "project"}.get(label, "unknown")
        if not (is_program or is_exhibition) or path in seen:
            continue
        seen.add(path)
        rows.append({
            "url": _canonical_page_url(absolute),
            "key": path,
            "title": clean_text(node.get_text(" ")),
            "event_type": "program" if is_program else "exhibition",
            "subtype": event_subtype,
            "upcoming": "upcoming" in current_section,
        })
    return rows


def _event_card_text(anchor, path):
    for ancestor in anchor.parents:
        if ancestor.name in ("main", "body", "html"):
            break
        paths = {_path(item.get("href", "")) for item in ancestor.find_all("a", href=True)
                 if urllib.parse.urlsplit(urllib.parse.urljoin(BROAD_BASE, item.get("href", ""))).netloc in
                 ("www.thebroad.org", "thebroad.org")}
        if paths == {path}:
            text = clean_text(ancestor.get_text(" "))
            if _LEGACY_EXHIBITION_LABEL.search(text):
                return text
    return clean_text(anchor.get_text(" "))


def _consume_event_page(ctx, response, organizer, handled, detail_limit=None):
    links = _event_links(response.text, response.url)
    ctx.count("fetched", len(links))
    parsed = 0
    starts = []
    for link in links:
        if link["key"] in handled:
            continue
        if not _needs_event_detail(ctx, link["key"]):
            handled[link["key"]] = None
            continue
        if detail_limit is not None and parsed >= detail_limit:
            break
        try:
            detail = _fetch(ctx, link["url"])
        except FetchError as error:
            ctx.note(f"detail error {link['url']}: {error}")
            ctx.count("detail_errors")
            handled[link["key"]] = None
            continue
        event, start = _store_event(ctx, detail, link, organizer)
        handled[link["key"]] = event
        parsed += 1
        if start:
            starts.append(start)
    ctx.con.commit()
    return parsed, starts


def _needs_event_detail(ctx, key):
    if ctx.mode == "initial":
        return True
    row = ctx.con.execute(
        "SELECT end_date FROM events WHERE source_id=? AND source_event_key=?", (ctx.source_id, key),
    ).fetchone()
    if row is None or not row[0]:
        return True
    cutoff = (now_kst().date() - dt.timedelta(days=30)).isoformat()
    return row[0] >= cutoff


def _date_info(main):
    candidates = []
    for tag in main.find_all(["time", "p", "li", "dd", "div", "span"]):
        text = clean_text(tag.get_text(" "))
        if not text or len(text) > 180 or not _EXPLICIT_DATE.search(text):
            continue
        parsed = parse_date_range(text)
        if parsed[0] or parsed[2]:
            candidates.append((text, parsed))
    if not candidates:
        for tag in main.select("time[datetime]"):
            value = tag.get("datetime", "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                text = clean_text(tag.get_text(" ")) or value
                parsed = parse_date_range(value)
                candidates.append((text, parsed))
    if not candidates:
        return None, (None, None, None, None)
    # Prefer the smallest visible range containing both dates, then the shortest single date.
    ranges = [item for item in candidates if item[1][0] and item[1][2]]
    chosen = min(ranges or candidates, key=lambda item: len(item[0]))
    return chosen


def _store_event(ctx, response, listing, organizer):
    main = _main(response.text)
    heading = main.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else listing["title"]
    date_text, dates = _date_info(main)
    start, start_precision, end, end_precision = dates
    venue_name, city, country_code = _venue_info(main)
    venue_id = _store_venue(ctx, venue_name, city, country_code) if venue_name else None
    path = listing["key"]
    if listing.get("subtype"):
        subtype = listing["subtype"]
    elif path.startswith("/art/collection-exhibitions/"):
        subtype = "collection_display"
    elif path.startswith("/art/featured-installations/"):
        subtype = "project"
    else:
        subtype = None if listing["event_type"] == "program" else "unknown"
    evidence = ctx.evidence(response, locator="#main-content h1", excerpt=date_text or title)
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=listing["key"],
        event_type=listing["event_type"], subtype=subtype, title=title, title_lang="en",
        organizer_entity_id=organizer, venue_id=venue_id, city=city, country_code=country_code,
        start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
        date_text=date_text, announced_status="scheduled" if listing["upcoming"] else None,
        parser_version=PARSER_VERSION, url=response.url, evidence_id=evidence,
    )
    if country_code is None:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown")
    _record_event_images(ctx, event_id, response.url, main)
    _add_event_participants(ctx, event_id, main, listing, evidence)
    ctx.count("parsed")
    return event_id, start


def _venue_info(main):
    for anchor in main.find_all("a", href=True):
        parsed = urllib.parse.urlsplit(anchor["href"])
        if parsed.hostname not in ("maps.google.com", "www.google.com", "maps.app.goo.gl"):
            continue
        address = " ".join(urllib.parse.parse_qs(parsed.query).get("q", []))
        city = "Los Angeles" if re.search(r"\bLos Angeles(?:,\s*|\s+)(?:CA|California)\b", address, re.I) else None
        country_code = "US" if city and re.search(r"\b(?:CA|California)\b", address, re.I) else None
        return clean_text(anchor.get_text(" ")), city, country_code
    return None, None, None


def _store_venue(ctx, name, city, country_code):
    venue_id = db.sid("ven", ctx.source_id, clean_text(name).casefold())
    edition_region = region.edition_region(country_code) if country_code else None
    ctx.con.execute(
        "INSERT INTO venues(venue_id,name,city,country_code,edition_region,source_id) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(venue_id) DO UPDATE SET city=COALESCE(excluded.city,venues.city), "
        "country_code=COALESCE(excluded.country_code,venues.country_code), "
        "edition_region=COALESCE(excluded.edition_region,venues.edition_region)",
        (venue_id, clean_text(name), city, country_code, edition_region, ctx.source_id),
    )
    return venue_id


def _is_work_path(path):
    parts = path.strip("/").split("/")
    return (len(parts) == 3 and parts[0] == "art" and parts[1] not in _EXCLUDED_ART_SLUGS
            and parts[2] not in _EXCLUDED_ART_SLUGS)


def _work_card(anchor):
    path = _path(anchor.get("href", ""))
    if not _is_work_path(path):
        return None
    segments = path.strip("/").split("/")
    heading = anchor.find_parent(re.compile(r"^h[1-6]$"))
    if heading is None:
        for ancestor in anchor.parents:
            if ancestor.name in ("main", "body", "html"):
                break
            paths = {_path(item.get("href", "")) for item in ancestor.find_all("a", href=True)
                     if _is_work_path(_path(item.get("href", "")))}
            if paths == {path}:
                heading = ancestor.find(re.compile(r"^h[1-6]$"))
                if heading:
                    break
    title = clean_text(anchor.get_text(" ")) or (clean_text(heading.get_text(" ")) if heading else "")
    if not title:
        return None
    card = None
    for ancestor in (heading or anchor).parents:
        if ancestor.name in ("main", "body", "html"):
            break
        links = {_path(a.get("href", "")) for a in ancestor.find_all("a", href=True) if _is_work_path(_path(a.get("href", "")))}
        if links == {path} and len(clean_text(ancestor.get_text(" "))) <= 800:
            lines = [clean_text(line) for line in ancestor.stripped_strings]
            if title in lines and lines.index(title) > 0:
                card = ancestor
                break
    if card is None:
        card = heading.parent if heading and heading.parent else anchor.parent
    lines = [clean_text(line) for line in card.stripped_strings]
    title_index = next((index for index, line in enumerate(lines) if line == title), None)
    if title_index is None and heading is not None:
        heading_text = clean_text(heading.get_text(" "))
        title_index = next((index for index, line in enumerate(lines) if line == heading_text), None)
    prior = lines[:title_index] if title_index is not None else lines[:-1]
    prior = [line for line in prior if line and line != title]
    artist = None
    date_text = None
    if prior:
        match = _WORK_DATE.match(prior[-1])
        if match:
            artist, date_text = clean_text(match.group(1)), clean_text(match.group(2))
        elif len(prior) >= 2 and re.fullmatch(r"(?:ca\.?\s*)?(?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?", prior[-1], re.I):
            artist, date_text = prior[-2], prior[-1]
        elif prior[-1].casefold() not in ("on view", "not on view"):
            artist = prior[-1]
    alt_artist, alt_date, medium = _alt_work_metadata(card, title)
    artist = artist or alt_artist
    date_text = date_text or alt_date
    artist_url = None
    for item in card.find_all("a", href=True):
        candidate = urllib.parse.urljoin(BROAD_BASE, item["href"])
        parts = _path(candidate).strip("/").split("/")
        if (len(parts) == 2 and parts[0] == "art" and parts[1] not in _EXCLUDED_ART_SLUGS
                and _validated_artist_url(parts[1], candidate)):
            artist_url = candidate
            break
    image_urls = []
    for image in card.find_all("img"):
        for attr in ("src", "data-src"):
            value = image.get(attr)
            if value and not value.startswith("data:"):
                image_url = urllib.parse.urljoin(BROAD_BASE, value)
                if image_url not in image_urls:
                    image_urls.append(image_url)
    return {"path": path, "artist_slug": segments[1], "title": title, "date_text": date_text,
            "artist": artist, "medium": medium, "artist_url": artist_url, "image_urls": image_urls,
            "url": urllib.parse.urljoin(BROAD_BASE, path)}


def _alt_work_metadata(card, title):
    for image in card.find_all("img", alt=True):
        alt = clean_text(image.get("alt", ""))
        if " - " not in alt:
            continue
        artist, description = alt.split(" - ", 1)
        if not description.startswith(title):
            continue
        suffix = description[len(title):].strip()
        if suffix.startswith(","):
            suffix = suffix[1:].strip()
        if not suffix:
            return clean_text(artist), None, None
        parts = [clean_text(part) for part in suffix.split(",")]
        date_index = next((index for index, part in enumerate(parts)
                           if _YEAR_LINE.fullmatch(part) or part.casefold() == "unknown"), None)
        if date_index is not None:
            medium = ", ".join(parts[date_index + 1:]) or None
            return clean_text(artist), parts[date_index], medium
        return clean_text(artist), None, ", ".join(parts)
    return None, None, None


def _collection_records(html, page_url):
    main = _main(html)
    records = []
    seen = set()
    for anchor in main.find_all("a", href=True):
        absolute = urllib.parse.urljoin(page_url, anchor.get("href", ""))
        if urllib.parse.urlsplit(absolute).netloc not in ("www.thebroad.org", "thebroad.org"):
            continue
        record = _work_card(anchor)
        if record and record["path"] not in seen:
            seen.add(record["path"])
            records.append(record)
    return records


def _unseen_page_batch(ctx, urls, locator, limit, refresh=False):
    """Prioritize unseen pages; rotate known pages into unused incremental slots."""
    unique_urls = list(dict.fromkeys(urls))
    successful = {row[0] for row in ctx.con.execute(
        "SELECT DISTINCT url FROM evidence WHERE source_id=? AND locator=?", (ctx.source_id, locator),
    )}
    unseen = [url for url in unique_urls if url not in successful]
    selected = unseen[:limit]
    known = [url for url in unique_urls if url in successful]
    slots = limit - len(selected)
    if refresh and slots > 0 and known:
        runs = ctx.con.execute(
            "SELECT COUNT(*) FROM crawl_runs WHERE source_id=? AND state IN ('success','no_change','partial')",
            (ctx.source_id,),
        ).fetchone()[0]
        offset = (runs * slots) % len(known)
        selected.extend((known[offset:] + known[:offset])[:slots])
    return selected, max(0, len(unseen) - limit)


def _collection_listing_ledger(ctx, locator):
    """Return successful listing URLs and their last persisted, publicly observed next links."""
    successful = set()
    next_by_url = {}
    rows = ctx.con.execute(
        "SELECT url,excerpt FROM evidence WHERE source_id=? AND locator=? ORDER BY rowid",
        (ctx.source_id, locator),
    )
    for url, excerpt in rows:
        successful.add(url)
        next_url = _listing_next_from_excerpt(excerpt)
        if next_url:
            next_by_url[url] = next_url
        else:
            next_by_url.pop(url, None)
    return successful, next_by_url


def _listing_next_from_excerpt(excerpt):
    marker = "listing-next="
    if not excerpt or not excerpt.startswith(marker):
        return None
    value = excerpt[len(marker):].split("\n", 1)[0].strip()
    if not value.startswith(("https://www.thebroad.org/", "https://thebroad.org/")):
        return None
    return value


def _request_budget(ctx):
    max_requests = ctx.meta.get("max_requests", 250) if hasattr(ctx, "meta") else 250
    return max(0, max_requests - ctx.stats.get("http_requests", 0))


def _artist_entity(ctx, name, slug, evidence, observed_url=None):
    name = clean_text(name)
    if not name:
        return None
    entity_type = "group" if re.search(r"\b(and|collective)\b|&", name, re.I) else "person"
    namespace = "broad_artist" if slug else f"src:{ctx.source_id}"
    return db.ensure_entity(
        ctx.con, entity_type=entity_type, name=name, namespace=namespace, id_value=slug,
        source_id=ctx.source_id, evidence_id=evidence,
        official_url=_validated_artist_url(slug, observed_url),
    )


def _validated_artist_url(slug, url):
    if not slug or not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme == "https" and parsed.netloc in ("www.thebroad.org", "thebroad.org")
            and _path(url) == f"/art/{slug}"):
        return url
    return None


def _listed_participant(ctx, name, slug, evidence):
    name = clean_text(name)
    if not name:
        return None
    namespace = "broad_program_participant" if slug else f"src:{ctx.source_id}"
    return db.ensure_entity(
        ctx.con, entity_type="unknown", name=name, namespace=namespace, id_value=slug,
        source_id=ctx.source_id, evidence_id=evidence,
        official_url=urllib.parse.urljoin(BROAD_BASE, f"/art/{slug}") if slug else None,
    )


def _collect_works(ctx, organizer):
    page_count = 0
    work_details = 0
    work_detail_attempts = 0
    artist_page_count = 0
    artist_work_count = 0
    listing_stats = []
    all_records = []
    seen_records = set()
    record_index_by_path = {}
    discovered_artists = {}
    discovered_artist_evidence = {}
    seen_pages = set()
    max_pages = MAX_COLLECTION_PAGES if ctx.mode == "initial" else 1
    detail_limit = MAX_WORK_DETAILS if ctx.mode == "initial" else 10

    for record in _persisted_work_records(ctx):
        record_index_by_path[record["path"]] = len(all_records)
        all_records.append(record)
        seen_records.add(record["path"])
        if record["artist_url"]:
            discovered_artists.setdefault(record["artist_url"], record["artist"])
            if record.get("artist_link_evidence"):
                discovered_artist_evidence[record["artist_url"]] = record["artist_link_evidence"]

    def record_listing_page(response, locator, scope, base_url):
        records = _collection_records(response.text, response.url)
        if not _collection_page_parsed(response.text, records):
            return False, None, 0
        next_url = _next_page_url(response.text, response.url, base_url)
        evidence = ctx.evidence(
            response, locator=locator,
            excerpt=_collection_listing_excerpt(scope, records, next_url),
        )
        for record in records:
            record["listing_evidence"] = evidence
            record["listing_scope"] = scope
            record["image_sources"] = [(response.url, image_url) for image_url in record["image_urls"]]
            if record["artist_url"]:
                record["artist_link_evidence"] = _observed_artist_link_evidence(
                    ctx, response, record["artist_url"],
                )
                discovered_artists.setdefault(record["artist_url"], record["artist"])
                if record["artist_link_evidence"]:
                    discovered_artist_evidence[record["artist_url"]] = record["artist_link_evidence"]
            existing_index = record_index_by_path.get(record["path"])
            if existing_index is None:
                seen_records.add(record["path"])
                record_index_by_path[record["path"]] = len(all_records)
                all_records.append(record)
            else:
                existing = all_records[existing_index]
                for field in ("artist", "date_text", "medium", "artist_url"):
                    if not existing[field] and record[field]:
                        existing[field] = record[field]
                existing["listing_evidence"] = evidence
                if record.get("artist_link_evidence"):
                    existing["artist_link_evidence"] = record["artist_link_evidence"]
                existing["image_urls"].extend(image for image in record["image_urls"]
                                               if image not in existing["image_urls"])
                existing["image_sources"].extend(
                    source for source in record["image_sources"] if source not in existing["image_sources"]
                )
        ctx.count("fetched", len(records))
        ctx.con.commit()
        return True, next_url, len(records)

    for route_path, route_label, scope in COLLECTION_LISTINGS:
        _listing_base_url = f"{BROAD_BASE}{route_path}"
        locator = f"#main-content collection listing {route_path}"
        successful, next_by_url = _collection_listing_ledger(ctx, locator)
        route_pages = 0
        route_attempts = 0
        route_records = 0
        frontier_state = "unknown (no parseable refresh)"
        next_url = next_by_url.get(_listing_base_url)
        if _request_budget(ctx) > REQUEST_RESERVE:
            seen_pages.add(_listing_base_url)
            route_attempts += 1
            try:
                response = _fetch(ctx, _listing_base_url)
            except FetchError as error:
                ctx.note(f"collection listing fetch error {_listing_base_url}: {error}")
                ctx.count("listing_errors")
            else:
                page_count += 1
                parsed, parsed_next, record_count = record_listing_page(
                    response, locator, scope, _listing_base_url,
                )
                if not parsed:
                    ctx.note(f"collection listing parser did not recognize {_listing_base_url}; page remains retryable")
                    ctx.count("listing_parse_errors")
                else:
                    route_pages += 1
                    route_records += record_count
                    successful.add(response.url)
                    if parsed_next:
                        next_by_url[response.url] = parsed_next
                    else:
                        next_by_url.pop(response.url, None)
                    next_url = parsed_next
                    frontier_state = "bounded to current-page refresh" if ctx.mode != "initial" else "pending"

        if ctx.mode == "initial" and (route_pages or next_url):
            traversed = {_listing_base_url}
            while next_url:
                candidate = next_url
                parsed_candidate = urllib.parse.urlsplit(candidate)
                if (parsed_candidate.scheme != "https" or _path(candidate) != _path(_listing_base_url)
                        or parsed_candidate.netloc not in ("www.thebroad.org", "thebroad.org")):
                    frontier_state = "unknown (stored pager link is outside this route)"
                    break
                if candidate in traversed:
                    frontier_state = "unknown (pager cycle detected)"
                    break
                traversed.add(candidate)
                if candidate in successful:
                    next_url = next_by_url.get(candidate)
                    continue
                if route_attempts >= max_pages or _request_budget(ctx) <= REQUEST_RESERVE:
                    frontier_state = "pending (run/request cap)"
                    break
                if candidate in seen_pages:
                    frontier_state = "unknown (page already visited in this run)"
                    break
                seen_pages.add(candidate)
                route_attempts += 1
                try:
                    response = _fetch(ctx, candidate)
                except FetchError as error:
                    ctx.note(f"collection listing fetch error {candidate}: {error}")
                    ctx.count("listing_errors")
                    frontier_state = "pending (failed page remains retryable)"
                    break
                page_count += 1
                parsed, parsed_next, record_count = record_listing_page(
                    response, locator, scope, _listing_base_url,
                )
                if not parsed:
                    ctx.note(f"collection listing parser did not recognize {candidate}; page remains retryable")
                    ctx.count("listing_parse_errors")
                    frontier_state = "pending (unparsed page remains retryable)"
                    break
                route_pages += 1
                route_records += record_count
                successful.add(response.url)
                if parsed_next:
                    next_by_url[response.url] = parsed_next
                else:
                    next_by_url.pop(response.url, None)
                next_url = parsed_next
                frontier_state = "exhausted (no further public pager link)"
            if not next_url and frontier_state == "pending":
                frontier_state = "exhausted (no further public pager link)"
        elif ctx.mode != "initial" and route_pages:
            frontier_state = ("bounded to current-page refresh; public pager not drained in incremental mode"
                              if next_url else "exhausted (current page exposes no further public pager link)")
        elif (ctx.mode == "initial" and not route_pages and next_url
              and frontier_state.startswith("unknown")):
            frontier_state = "pending (current-page refresh unavailable; stored public frontier retained)"
        elif ctx.mode == "initial" and route_pages and not next_url:
            frontier_state = "exhausted (no further public pager link)"
        listing_stats.append((route_path, route_label, scope, route_pages, route_records, frontier_state))

    detail_locator = "#main-content artwork metadata"
    detail_limit = MAX_WORK_DETAILS if ctx.mode == "initial" else 10
    selected_detail_urls, _ = _unseen_page_batch(
        ctx, [record["url"] for record in all_records], detail_locator, detail_limit,
        refresh=ctx.mode == "incremental",
    )
    selected_detail_urls = set(selected_detail_urls)
    for record in all_records:
        detail = None
        detail_evidence = None
        facts = {}
        if (record["url"] in selected_detail_urls and work_detail_attempts < detail_limit
                and _request_budget(ctx) > REQUEST_RESERVE):
            work_detail_attempts += 1
            try:
                detail = _fetch(ctx, record["url"])
            except FetchError as error:
                ctx.note(f"artwork detail error {record['url']}: {error}")
                ctx.count("detail_errors")
            else:
                facts = _work_detail_facts(detail.text, record)
                if any(facts.get(field) for field in ("title", "artist", "date_text", "medium")):
                    detail_evidence = ctx.evidence(
                        detail, locator=detail_locator,
                        excerpt=_work_evidence_excerpt(detail.text, record),
                    )
                    work_details += 1
                    if facts.get("artist_url"):
                        record["artist_link_evidence"] = _observed_artist_link_evidence(
                            ctx, detail, facts["artist_url"],
                        )
                        discovered_artists.setdefault(facts["artist_url"], facts.get("artist"))
                        if record["artist_link_evidence"]:
                            discovered_artist_evidence[facts["artist_url"]] = record["artist_link_evidence"]
                else:
                    ctx.note(f"artwork detail page yielded no recognized metadata: {record['url']}")
                    ctx.count("detail_parse_errors")
        self_evidence = detail_evidence or record["listing_evidence"]
        old = _existing_work(ctx, record["path"])
        artist_name = facts.get("artist") or record["artist"]
        artist_url = facts.get("artist_url") or record.get("artist_url")
        artist_evidence = record.get("artist_link_evidence") or self_evidence
        title = facts.get("title") or record["title"] or (old["title"] if old else None)
        date_text = facts.get("date_text") or record["date_text"] or (old["date_text"] if old else None)
        medium = facts.get("medium") or record["medium"] or (old["medium"] if old else None)
        artist_id = (_artist_entity(ctx, artist_name, record["artist_slug"], artist_evidence,
                                    observed_url=artist_url)
                     if artist_name else (old["artist_entity_id"] if old else None))
        work_id = db.upsert_work(
            ctx.con, ctx.stats, id_namespace="broad_work", id_value=record["path"],
            source_id=ctx.source_id, artist_entity_id=artist_id, title=title,
            date_text=date_text, medium=medium,
            classification=old["classification"] if old else None,
            holding_entity_id=organizer,
            url=record["url"], acquisition_text=old["acquisition_text"] if old else None,
            is_public_domain=old["is_public_domain"] if old else None,
        )
        for listing_url, image_url in record["image_sources"]:
            _record_work_images(ctx, work_id, listing_url, [image_url])
        _record_work_images(ctx, work_id, record["url"], facts.get("image_urls", []))
        ctx.count("parsed")
    ctx.con.commit()

    artist_limit = MAX_ARTIST_PAGES if ctx.mode == "initial" else 4
    artist_locator = "#main-content By artist in the Collection"
    selected_artist_urls, _ = _unseen_page_batch(
        ctx, list(discovered_artists), artist_locator, artist_limit,
        refresh=ctx.mode == "incremental",
    )
    for artist_url in selected_artist_urls:
        if _request_budget(ctx) <= REQUEST_RESERVE or artist_url in seen_pages:
            break
        seen_pages.add(artist_url)
        artist_name = discovered_artists[artist_url]
        try:
            response = _fetch(ctx, artist_url)
        except FetchError as error:
            ctx.note(f"artist listing error {artist_url}: {error}")
            ctx.count("detail_errors")
            continue
        artist_page_count += 1
        records = _collection_records(response.text, response.url)
        evidence = ctx.evidence(response, locator=artist_locator,
                                excerpt=_collection_excerpt("linked artist collection listing", records))
        ctx.count("fetched", len(records))
        artist_heading = _artist_page_name(response.text) or artist_name
        for record in records:
            if record["path"] not in seen_records:
                seen_records.add(record["path"])
                artist_work_count += 1
            old = _existing_work(ctx, record["path"])
            name = record["artist"] or artist_heading or (old["artist_name"] if old else None)
            artist_url = record.get("artist_url")
            link_evidence = None
            if artist_url:
                link_evidence = _observed_artist_link_evidence(ctx, response, artist_url)
            else:
                artist_url = next((url for url in discovered_artists
                                   if _path(url) == f"/art/{record['artist_slug']}"), None)
                if artist_url:
                    link_evidence = discovered_artist_evidence.get(artist_url)
            artist_id = (_artist_entity(ctx, name, record["artist_slug"], link_evidence or evidence,
                                        observed_url=artist_url if link_evidence else None)
                         if name else (old["artist_entity_id"] if old else None))
            work_id = db.upsert_work(
                ctx.con, ctx.stats, id_namespace="broad_work", id_value=record["path"],
                source_id=ctx.source_id, artist_entity_id=artist_id,
                title=record["title"] or (old["title"] if old else None),
                date_text=record["date_text"] or (old["date_text"] if old else None),
                medium=record["medium"] or (old["medium"] if old else None),
                classification=old["classification"] if old else None,
                holding_entity_id=organizer, acquisition_text=old["acquisition_text"] if old else None,
                url=record["url"], is_public_domain=old["is_public_domain"] if old else None,
            )
            _record_work_images(ctx, work_id, response.url, record["image_urls"])
            ctx.count("parsed")
        ctx.con.commit()

    _, detail_remaining = _unseen_page_batch(
        ctx, [record["url"] for record in all_records], detail_locator, 0,
    )
    _, artist_remaining = _unseen_page_batch(
        ctx, list(discovered_artists), artist_locator, 0,
    )
    return (page_count, len(all_records), work_details, artist_page_count, artist_work_count,
            detail_remaining, artist_remaining, listing_stats)


def _existing_work(ctx, path):
    row = ctx.con.execute(
        "SELECT w.artist_entity_id,w.title,w.date_text,w.medium,w.classification,w.acquisition_text,"
        "w.is_public_domain,e.canonical_name AS artist_name FROM works w LEFT JOIN entities e "
        "ON e.entity_id=w.artist_entity_id WHERE w.source_id=? AND w.id_namespace=? AND w.id_value=?",
        (ctx.source_id, "broad_work", path),
    ).fetchone()
    return row


def _artist_link_locator(url):
    return f"#main-content observed artist link {url}"


def _observed_artist_link_evidence(ctx, response, url):
    return ctx.evidence(
        response, locator=_artist_link_locator(url), excerpt="explicit artist anchor observed in public HTML",
    )


def _persisted_artist_link_evidence(ctx, entity_id, url):
    if not entity_id or not url:
        return None
    expected_locator = _artist_link_locator(url)
    observed = ctx.con.execute(
        "SELECT v.evidence_id FROM evidence v JOIN entities e ON e.entity_id=? AND e.official_url=? "
        "WHERE v.source_id=? AND v.locator=? ORDER BY v.fetched_at DESC LIMIT 1",
        (entity_id, url, ctx.source_id, expected_locator),
    ).fetchone()
    if observed:
        return observed[0]
    rows = ctx.con.execute(
        "SELECT a.evidence_id,v.locator,v.url,v.raw_path FROM aliases a JOIN evidence v "
        "ON v.evidence_id=a.evidence_id WHERE a.entity_id=? AND v.source_id=? ORDER BY v.fetched_at DESC",
        (entity_id, ctx.source_id),
    ).fetchall()
    for evidence_id, locator, evidence_url, raw_path in rows:
        if locator == expected_locator:
            return evidence_id
        if not raw_path:
            continue
        saved_path = (WORK_ROOT / raw_path).resolve()
        try:
            saved_path.relative_to(WORK_ROOT)
        except ValueError:
            continue
        if not saved_path.is_file():
            continue
        try:
            document = soup(saved_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for anchor in document.find_all("a", href=True):
            observed = urllib.parse.urljoin(evidence_url, anchor.get("href", ""))
            parsed = urllib.parse.urlsplit(observed)
            target = urllib.parse.urlsplit(url)
            if (parsed.scheme == "https" and parsed.netloc in ("www.thebroad.org", "thebroad.org")
                    and parsed.netloc == target.netloc and _path(observed) == _path(url)):
                return evidence_id
    return None


def _persisted_work_records(ctx):
    """Rebuild prior work and artist candidates from the durable Broad work records."""
    rows = ctx.con.execute(
        "SELECT w.work_id,w.id_value,w.url,w.artist_entity_id,w.title,w.date_text,w.medium,"
        "e.canonical_name,e.official_url FROM works w LEFT JOIN entities e "
        "ON e.entity_id=w.artist_entity_id WHERE w.source_id=? AND w.id_namespace=? ORDER BY w.id_value",
        (ctx.source_id, "broad_work"),
    ).fetchall()
    records = []
    images_by_work = {}
    for work_id, page_url, image_url in ctx.con.execute(
            "SELECT work_id,page_url,image_url FROM image_rights WHERE source_id=? AND image_url IS NOT NULL",
            (ctx.source_id,)):
        images_by_work.setdefault(work_id, []).append((page_url, image_url))
    artist_link_cache = {}
    for row in rows:
        path = row["id_value"]
        segments = path.strip("/").split("/")
        if len(segments) < 3 or segments[0] != "art":
            continue
        images = images_by_work.get(row["work_id"], [])
        image_urls = list(dict.fromkeys(image_url for _, image_url in images))
        artist_url = row["official_url"]
        artist_link_evidence = None
        if artist_url:
            parsed_artist_url = urllib.parse.urlsplit(artist_url)
            if (parsed_artist_url.scheme != "https" or parsed_artist_url.netloc not in
                    ("www.thebroad.org", "thebroad.org") or _path(artist_url) != f"/art/{segments[1]}"):
                artist_url = None
            else:
                cache_key = (row["artist_entity_id"], artist_url)
                if cache_key not in artist_link_cache:
                    artist_link_cache[cache_key] = _persisted_artist_link_evidence(
                        ctx, row["artist_entity_id"], artist_url,
                    )
                artist_link_evidence = artist_link_cache[cache_key]
                if artist_link_evidence is None:
                    artist_url = None
        records.append({
            "path": path,
            "artist_slug": segments[1],
            "title": row["title"],
            "date_text": row["date_text"],
            "artist": row["canonical_name"],
            "medium": row["medium"],
            "artist_url": artist_url,
            "image_urls": image_urls,
            "url": row["url"] or urllib.parse.urljoin(BROAD_BASE, path),
            "listing_evidence": None,
            "artist_link_evidence": artist_link_evidence,
            "listing_scope": "persisted Broad work record",
            "image_sources": [(page_url, image_url) for page_url, image_url in images if page_url],
        })
    return records


def _artist_page_name(html):
    main = _main(html)
    heading = main.find("h1")
    if not heading:
        return None
    name = clean_text(heading.get_text(" "))
    return re.sub(r"\s+-\s+Bio$", "", name, flags=re.I)


def _collection_excerpt(scope, records):
    cards = [" / ".join(value for value in (record.get("artist"), record.get("title"),
                                             record.get("date_text"), record.get("medium")) if value)
             for record in records[:3]]
    return "; ".join([scope, *cards])


def _collection_listing_excerpt(scope, records, next_url):
    summary = _collection_excerpt(scope, records)
    return f"listing-next={next_url}\n{summary}" if next_url else summary


def _collection_page_parsed(html, records):
    if records:
        return True
    document = soup(html)
    main = document.select_one("main, [role='main'], #main-content:not(a)")
    if main is None:
        return False
    heading = main.find(["h1", "h2"])
    heading_text = clean_text(heading.get_text(" ")).casefold() if heading else ""
    return any(marker in heading_text for marker in ("browse", "collection", "on view"))


def _record_work_images(ctx, work_id, page_url, image_urls):
    basis = "The Broad terms restrict reuse; images are copyrighted or third-party; URL retained only, asset not fetched."
    for image_url in set(image_urls):
        db.add_image_rights(
            ctx.con, source_id=ctx.source_id, work_id=work_id, page_url=page_url,
            image_url=image_url, usage_status="unknown", basis=basis,
        )


def _record_event_images(ctx, event_id, page_url, main):
    basis = "The Broad terms restrict reuse; images are copyrighted or third-party; URL retained only, asset not fetched."
    for image in main.find_all("img"):
        for attr in ("src", "data-src"):
            value = image.get(attr)
            if value and not value.startswith("data:"):
                db.add_image_rights(
                    ctx.con, source_id=ctx.source_id, event_id=event_id, page_url=page_url,
                    image_url=urllib.parse.urljoin(BROAD_BASE, value), usage_status="unknown", basis=basis,
                )


def _work_detail_facts(html, record):
    main = _main(html)
    heading = main.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else None
    artist = None
    artist_url = None
    for anchor in main.find_all("a", href=True):
        absolute = urllib.parse.urljoin(BROAD_BASE, anchor["href"])
        parts = _path(absolute).strip("/").split("/")
        if (len(parts) == 2 and parts[0] == "art" and parts[1] == record["artist_slug"]
                and _validated_artist_url(parts[1], absolute)):
            artist = clean_text(anchor.get_text(" ")) or None
            artist_url = absolute
            break
    lines = [clean_text(value) for value in main.stripped_strings]
    lines = [value for value in lines if value]
    date_index = next((index for index, value in enumerate(lines) if _YEAR_LINE.fullmatch(value)), None)
    date_text = lines[date_index] if date_index is not None else None
    medium = None
    if date_index is not None and date_index + 1 < len(lines):
        candidate = lines[date_index + 1]
        if (not _YEAR_LINE.fullmatch(candidate) and not _DIMENSION_LINE.search(candidate)
                and candidate.casefold() not in ("on view", "not on view")):
            medium = candidate
    image_urls = []
    for image in main.find_all("img"):
        for attr in ("src", "data-src"):
            value = image.get(attr)
            if value and not value.startswith("data:"):
                image_url = urllib.parse.urljoin(BROAD_BASE, value)
                if image_url not in image_urls:
                    image_urls.append(image_url)
    return {"title": title, "artist": artist, "artist_url": artist_url,
            "date_text": date_text, "medium": medium, "image_urls": image_urls}


def _work_evidence_excerpt(html, record):
    facts = _work_detail_facts(html, record)
    main = _main(html)
    lines = [clean_text(value) for value in main.stripped_strings]
    metadata = [facts.get("date_text"), facts.get("medium")]
    for index, line in enumerate(lines):
        if line.casefold() in ("accession date:", "accession number:") and index + 1 < len(lines):
            metadata.append(f"{line} {lines[index + 1]}")
        if _DIMENSION_LINE.search(line):
            metadata.append(line)
    return "; ".join(value for value in metadata if value) or record["title"]


def _add_event_participants(ctx, event_id, main, listing, evidence):
    headings = main.find_all(["h2", "h3"])
    collecting_featured = False
    collected = set()
    for heading in headings:
        heading_text = clean_text(heading.get_text(" ")).casefold()
        if heading.name == "h2":
            if collecting_featured:
                break
            collecting_featured = heading_text in ("featured artworks", "featured artwork")
        if not collecting_featured:
            continue
        for anchor in heading.find_all_next("a", href=True):
            next_heading = anchor.find_previous(["h2"])
            if next_heading is not None and next_heading is not heading:
                break
            record = _work_card(anchor)
            if not record or not record["artist"]:
                continue
            artist_key = record["artist_slug"]
            if artist_key in collected:
                continue
            collected.add(artist_key)
            entity = _artist_entity(ctx, record["artist"], artist_key, evidence,
                                    observed_url=record.get("artist_url"))
            db.add_participant(ctx.con, event_id, entity, "artist", record["artist"], evidence,
                               "list_markup", "high")

    if listing["event_type"] == "program":
        # Only use explicit artist/performer/bio lists; prose mentions do not establish participation.
        for heading in main.find_all(["h2", "h3"]):
            section = clean_text(heading.get_text(" ")).casefold()
            if section not in ("performers", "artists", "bios", "biographies", "speakers", "presenters"):
                continue
            for name_heading in heading.find_all_next(["h2", "h3"]):
                if name_heading.name == "h2":
                    break
                name = clean_text(name_heading.get_text(" "))
                if not name:
                    continue
                link = name_heading.find("a", href=True)
                slug = None
                artist_url = None
                if link:
                    artist_url = urllib.parse.urljoin(BROAD_BASE, link["href"])
                    path_parts = _path(artist_url).strip("/").split("/")
                    if (len(path_parts) == 2 and path_parts[0] == "art"
                            and _validated_artist_url(path_parts[1], artist_url)):
                        slug = path_parts[1]
                is_artist = section == "artists"
                entity = (_artist_entity(ctx, name, slug, evidence,
                                         observed_url=artist_url)
                          if is_artist
                          else _listed_participant(ctx, name, slug, evidence))
                db.add_participant(ctx.con, event_id, entity, "artist" if is_artist else "participant", name, evidence,
                                   "list_markup", "high")


def _next_page_url(html, current_url, base_url):
    document = soup(html)
    base_path = _path(base_url)
    links = document.select("a[rel~='next'], li.pager__item--next a, .pager__item--next a")
    for link in links:
        candidate = urllib.parse.urljoin(current_url, link.get("href", ""))
        parsed = urllib.parse.urlsplit(candidate)
        if (parsed.netloc in ("www.thebroad.org", "thebroad.org") and _path(candidate) == base_path
                and candidate != current_url):
            return candidate
    return None

