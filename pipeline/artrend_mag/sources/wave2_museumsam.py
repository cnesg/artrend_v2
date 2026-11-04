"""Public museum exhibition listings and Whitney's CC0 Open Access CSV dataset."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import urllib.parse

from .. import db, region
from ..config import now_kst
from ..http import Blocked, FetchError
from ._common import classify_subtype, clean_text, parse_date_range, split_title_artist, soup

PARSER_VERSION = "wave2_museumsam-1"
HISTORY_FLOOR = "2025-04-01"
SAAM = "https://americanart.si.edu"
MNBA = "https://www.mnba.gob.cl"
WHITNEY_ARTISTS_CSV = "https://raw.githubusercontent.com/whitneymuseum/open-access/main/artists.csv"
WHITNEY_ARTWORKS_CSV = "https://raw.githubusercontent.com/whitneymuseum/open-access/main/artworks.csv"
WHITNEY_LICENSE = "https://github.com/whitneymuseum/open-access/blob/main/LICENSE"
MAX_CSV_BYTES = 50_000_000

SOURCES = [
    dict(
        source_id="wave2_saam_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
        name="Smithsonian American Art Museum — Exhibitions", owner_group="Smithsonian American Art Museum",
        source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="html",
        base_url=SAAM, entry_url=f"{SAAM}/exhibitions", terms_url=None, text_storage_policy="raw_internal",
        priority="P1", notes="Current/upcoming and paginated past exhibition listings; detail pages supply dates and explicit participants.",
        max_requests=200,
    ),
    dict(
        source_id="wave2_mnba_chile_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
        name="Museo Nacional de Bellas Artes (Chile) — Exposiciones temporales",
        owner_group="Museo Nacional de Bellas Artes, Chile", source_kind="museum", region_scope="AMERICAS",
        country_codes="CL", access_method="html", base_url=MNBA, entry_url=f"{MNBA}/exposiciones-temporales",
        terms_url=None, text_storage_policy="raw_internal", priority="P1",
        notes="Listing shows publication dates, not exhibition periods; dates and participants are read from each exhibition detail page.",
        max_requests=80,
    ),
    dict(
        source_id="wave2_whitney_open_access", blueprint_data_id=None, blueprint_org_id=None,
        name="Whitney Museum — Open Access collection CSV", owner_group="Whitney Museum of American Art",
        source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="download",
        base_url="https://github.com/whitneymuseum/open-access", entry_url=WHITNEY_ARTWORKS_CSV,
        terms_url=WHITNEY_LICENSE, text_storage_policy="raw_internal", priority="P1",
        notes="Official CC0 metadata CSVs only; images are not included or fetched, and CC0 data does not establish image rights.",
        max_requests=6,
    ),
]


def parse_saam_listing(html: str, base_url: str = SAAM, *, past: bool = False) -> list[dict]:
    """Parse actual SAAM current/upcoming cards or the past archive's teaser rows."""
    page = soup(html)
    main = page.select_one("main") or page
    selector = "div.azalea-teaser" if past else "div.azalea-card[href]"
    out, seen = [], set()
    for card in main.select(selector):
        anchor = card.select_one('header a[href^="/exhibit"]')
        if not anchor:
            continue
        href = anchor.get("href", "")
        path = urllib.parse.urlsplit(href).path
        if not path.startswith(("/exhibitions/", "/exhibition/")):
            continue
        key = path.rstrip("/").rsplit("/", 1)[-1]
        title = clean_text(anchor.get_text(" "))
        if not key or not title or key in seen:
            continue
        seen.add(key)
        date_node = card.select_one(".azalea-heading-level-5" if past else ".azalea-heading-level-4")
        venue_node = card.select_one(".azalea-heading-level-6")
        out.append({
            "key": key,
            "title": title,
            "date_text": clean_text(date_node.get_text(" ")) if date_node else "",
            "venue": clean_text(venue_node.get_text(" ")) if venue_node else None,
            "url": urllib.parse.urljoin(base_url, href),
        })
    return out


def parse_mnba_listing(html: str, base_url: str = MNBA) -> list[dict]:
    """Parse MNBA exhibition cards without treating their publication dates as event dates."""
    page = soup(html)
    main = page.select_one("main") or page
    out, seen = [], set()
    for card in main.select(".masonry-item.views-row"):
        anchor = card.select_one('h2.destacado__title a[href^="/exposiciones-temporales/"]')
        if not anchor:
            continue
        href = anchor.get("href", "")
        path = urllib.parse.urlsplit(href).path
        key = path.rstrip("/").rsplit("/", 1)[-1]
        title = clean_text(anchor.get_text(" "))
        if not key or not title or key in seen:
            continue
        seen.add(key)
        published = card.select_one(".date-custom-published time[datetime]")
        out.append({
            "key": key,
            "title": title,
            "url": urllib.parse.urljoin(base_url, href),
            "published_at": (published.get("datetime") or "")[:10] or None if published else None,
        })
    return out


def parse_mnba_detail(html: str) -> dict:
    page = soup(html)
    main = page.select_one("main") or page
    heading = main.select_one("h1")
    date_node = main.select_one(".exposicion-date-items > .field-item")
    date_text = clean_text(date_node.get_text(" ")) if date_node else ""
    venue_node = main.select_one(".field--name-field-lugar .field-item")
    venue = clean_text(venue_node.get_text(" ")) if venue_node else None

    artists = []
    for section_heading in main.select(".text-long h3"):
        label = clean_text(section_heading.get_text(" ")).casefold()
        if label not in ("sobre el artista", "sobre la artista", "sobre los artistas", "sobre las artistas"):
            continue
        paragraph = section_heading.find_next_sibling("p")
        if paragraph:
            artists = _unique(clean_text(node.get_text(" ")) for node in paragraph.select("strong"))
        break

    curators = []
    for paragraph in main.select(".text-long p"):
        text = clean_text(paragraph.get_text(" "))
        match = re.search(r"\bCuradur[ií]a\s*:\s*(.+)", text, re.I)
        if match:
            name = re.sub(r"\s*[\(（][^\)）]*[\)）]", "", match.group(1)).strip(" .;:")
            if name:
                curators.append(clean_text(name))
    dates = parse_date_range(date_text)
    return {
        "title": clean_text(heading.get_text(" ")) if heading else "",
        "date_text": date_text,
        "dates": dates,
        "venue": venue,
        "artists": _unique(artists),
        "curators": _unique(curators),
    }


def _unique(values) -> list[str]:
    out, seen = [], set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _event_subtype(title: str) -> str:
    if re.search(r"\b(galleries for|collection|colecci[oó]n)\b", title, re.I):
        return "collection_display"
    return classify_subtype(title)


def _saam_period(text: str):
    value = clean_text(text)
    if not value or value.casefold() in ("ongoing", "closed temporarily"):
        return None, None, None, None
    start, start_precision, end, end_precision = parse_date_range(value)
    if re.match(r"^(?:through|until)\b", value, re.I):
        return None, None, end, end_precision
    if re.match(r"^opens?\b", value, re.I):
        return start, start_precision, None, None
    return start, start_precision, end, end_precision


def _merge_dates(primary, fallback):
    start = primary[0] or fallback[0]
    start_precision = primary[1] if primary[0] else fallback[1]
    end = primary[2] or fallback[2]
    end_precision = primary[3] if primary[2] else fallback[3]
    return start, start_precision, end, end_precision


def _saam_past_last_page(html: str) -> int:
    page = soup(html)
    values = []
    for anchor in page.select('a[href*="page="]'):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(anchor.get("href", "")).query)
        for value in query.get("page", []):
            if value.isdigit():
                values.append(int(value))
    return max(values, default=0)


def _venue(ctx, name: str | None, city: str | None, country_code: str | None):
    if not name:
        return None
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


def _org(ctx, name: str, key: str, url: str) -> str:
    return db.ensure_entity(ctx.con, entity_type="institution", name=name, namespace=f"src:{ctx.source_id}",
                            id_value=key, source_id=ctx.source_id, official_url=url)


def _add_person(ctx, event_id: str, evidence_id: str, name: str, role: str, *, method: str,
                namespace: str | None = None, id_value: str | None = None, confidence: str = "high"):
    name = clean_text(name)
    if not name:
        return
    kind = "group" if re.search(r"\s(&|and|y|e)\s|collective|colectivo|coletivo", name, re.I) else "person"
    entity = db.ensure_entity(ctx.con, entity_type=kind, name=name,
                              namespace=namespace or f"src:{ctx.source_id}", id_value=id_value,
                              source_id=ctx.source_id, evidence_id=evidence_id)
    db.add_participant(ctx.con, event_id, entity, role, name, evidence_id, method, confidence)


def _saam_detail(html: str) -> dict:
    page = soup(html)
    main = page.select_one("main") or page
    heading = main.select_one("h1")
    date_text, venue = "", None
    for label in main.select("h3.azalea-heading-section"):
        if clean_text(label.get_text(" ")).casefold() != "visiting information":
            continue
        block = label.find_parent("div", class_="azalea-text-md")
        if not block:
            continue
        info = block.select_one("div.flex.flex-col.space-y-1")
        if info:
            venue_link = info.select_one('a[href^="/visit/"]')
            venue = clean_text(venue_link.get_text(" ")) if venue_link else None
            spans = info.select("span.whitespace-nowrap")
            if len(spans) >= 2:
                date_text = " – ".join(clean_text(node.get_text(" ")) for node in spans[:2])
            break

    artists, artist_ids = [], {}
    artist_section = main.select_one("section#artists")
    if artist_section:
        for card in artist_section.select('div.azalea-card[href^="/artist/"]'):
            anchor = card.select_one('header a[href^="/artist/"]')
            if not anchor:
                continue
            href = urllib.parse.urlsplit(anchor.get("href", "")).path.rstrip("/")
            artist_key = href.rsplit("/", 1)[-1]
            name = clean_text(anchor.get_text(" "))
            if name:
                artists.append(name)
                artist_ids[name] = artist_key

    text = clean_text(main.get_text(" "))
    curators = []
    for match in re.finditer(r"\b(?:curated|organized)\s+by\s+([^,.;]+),\s*([^.;]{0,140})", text, re.I):
        if re.search(r"\bcurator\b", match.group(2), re.I):
            curators.append(clean_text(match.group(1)))
    return {
        "title": clean_text(heading.get_text(" ")) if heading else "",
        "date_text": date_text,
        "dates": parse_date_range(date_text),
        "venue": venue,
        "artists": _unique(artists),
        "artist_ids": artist_ids,
        "curators": _unique(curators),
    }


def _known_end(ctx, key: str):
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
    return (row[0] if row else None), row is not None


def _needs_detail(ctx, key: str, listing_end: str | None = None, *, scheduled: bool = False) -> bool:
    if ctx.mode == "initial" or scheduled:
        return True
    known_end, seen = _known_end(ctx, key)
    if not seen:
        return True
    end = known_end or listing_end
    if not end:
        return True
    cutoff = (now_kst().date() - dt.timedelta(days=30)).isoformat()
    return end[:10] >= cutoff


def _in_scope(ctx, end: str | None) -> bool:
    if not end:
        return True
    floor = HISTORY_FLOOR if ctx.mode == "initial" else (now_kst().date() - dt.timedelta(days=30)).isoformat()
    return end[:10] >= floor


def _collect_saam(ctx):
    org = _org(ctx, "Smithsonian American Art Museum", "saam", SAAM + "/")
    listings = []
    for url, section in ((SAAM + "/exhibitions", "current"), (SAAM + "/exhibitions/upcoming", "upcoming")):
        response = ctx.fetch(url)
        items = parse_saam_listing(response.text, SAAM)
        ctx.count("fetched", len(items))
        for item in items:
            item.update(list_response=response, section=section, scheduled=section == "upcoming")
            listings.append(item)

    page = 0
    last_page = 0
    pages_walked = 0
    oldest_year = None
    page_cap = 12 if ctx.mode == "initial" else 1
    while page <= last_page and page < page_cap:
        url = SAAM + "/exhibitions/past"
        response = ctx.fetch(url, params={"page": page} if page else None)
        pages_walked = page + 1
        items = parse_saam_listing(response.text, SAAM, past=True)
        ctx.count("fetched", len(items))
        years = []
        for item in items:
            dates = _saam_period(item["date_text"])
            years.extend(int(value[:4]) for value in (dates[0], dates[2]) if value)
            item.update(list_response=response, section="past", scheduled=False)
            listings.append(item)
        if years:
            oldest_year = min(years) if oldest_year is None else min(oldest_year, min(years))
        last_page = max(last_page, _saam_past_last_page(response.text))
        if ctx.mode == "initial" and page > 0 and years and max(years) < 2023:
            ctx.note(f"saam: stopped archive at page {page}; all displayed periods were before 2023")
            break
        if page >= last_page:
            break
        page += 1

    seen = set()
    for item in listings:
        key = item["key"]
        if key in seen:
            continue
        seen.add(key)
        listing_dates = _saam_period(item["date_text"])
        listing_end = listing_dates[2]
        if ctx.mode == "initial" and item["section"] == "past" and listing_end and listing_end < HISTORY_FLOOR:
            continue
        detail_response = None
        detail = {}
        if _needs_detail(ctx, key, listing_end, scheduled=item["scheduled"]):
            try:
                detail_response = ctx.fetch(item["url"])
                detail = _saam_detail(detail_response.text)
            except Blocked:
                raise
            except FetchError as exc:
                ctx.note(f"SAAM detail {key}: {exc}")
                ctx.count("detail_errors")
        detail_dates = detail.get("dates") or (None, None, None, None)
        dates = _merge_dates(detail_dates, listing_dates)
        start, start_precision, end, end_precision = dates
        if not _in_scope(ctx, end):
            continue
        title = detail.get("title") or item["title"]
        date_text = detail.get("date_text") or item["date_text"] or None
        venue_name = detail.get("venue") or item.get("venue")
        city = "Washington" if venue_name in ("Smithsonian American Art Museum", "Renwick Gallery") else None
        country_code = "US" if city else None
        venue_id = _venue(ctx, venue_name, city, country_code)
        response = detail_response or item["list_response"]
        locator = "main h1 / Visiting Information / Artists" if detail_response else f"exhibition listing {key}"
        evidence_id = ctx.evidence(response, locator=locator, excerpt=date_text)
        event_id = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
            subtype=_event_subtype(title), title=title, title_lang="en", organizer_entity_id=org,
            venue_id=venue_id, city=city, country_code=country_code, start_date=start,
            start_precision=start_precision, end_date=end, end_precision=end_precision, date_text=date_text,
            announced_status="scheduled" if item["scheduled"] else None, parser_version=PARSER_VERSION,
            url=item["url"], evidence_id=evidence_id,
        )
        if detail_response:
            listing_evidence_id = ctx.evidence(item["list_response"], locator=f"exhibition listing {key}",
                                               excerpt=item["date_text"])
            ctx.con.execute("INSERT INTO event_evidence(event_id,evidence_id) VALUES(?,?) ON CONFLICT DO NOTHING",
                            (event_id, listing_evidence_id))
        if not country_code:
            db.add_review(ctx.con, "region", "events", event_id, "venue country unknown")
        artists = detail.get("artists") or []
        artist_ids = detail.get("artist_ids", {})
        if artists:
            for name in artists:
                _add_person(ctx, event_id, evidence_id, name, "artist", method="structured_field",
                            namespace="saam_artist", id_value=artist_ids.get(name))
        else:
            name = split_title_artist(title)
            if name:
                _add_person(ctx, event_id, evidence_id, name, "artist", method="title_pattern", confidence="medium")
        for curator in detail.get("curators", []):
            _add_person(ctx, event_id, evidence_id, curator, "curator", method="list_markup")
        ctx.count("parsed")
    ctx.note(f"saam: current/upcoming plus {pages_walked} past archive page(s); displayed oldest year={oldest_year or 'unknown'}")


def _collect_mnba(ctx):
    org = _org(ctx, "Museo Nacional de Bellas Artes", "mnba-chile", MNBA + "/")
    response = ctx.fetch(MNBA + "/exposiciones-temporales")
    items = parse_mnba_listing(response.text, MNBA)
    ctx.count("fetched", len(items))
    seen = set()
    for item in items:
        key = item["key"]
        if key in seen:
            continue
        seen.add(key)
        if not _needs_detail(ctx, key):
            continue
        try:
            detail_response = ctx.fetch(item["url"])
        except Blocked:
            raise
        except FetchError as exc:
            ctx.note(f"MNBA detail {key}: {exc}")
            ctx.count("detail_errors")
            continue
        detail = parse_mnba_detail(detail_response.text)
        start, start_precision, end, end_precision = detail["dates"]
        if not _in_scope(ctx, end):
            continue
        title = detail["title"] or item["title"]
        date_text = detail["date_text"] or None
        venue_name = ("Museo Nacional de Bellas Artes — " + detail["venue"]) if detail["venue"] else None
        venue_id = _venue(ctx, venue_name, "Santiago" if venue_name else None, "CL" if venue_name else None)
        evidence_id = ctx.evidence(detail_response, locator="main .exposicion-date-items / .field--name-field-lugar / .text-long",
                                   excerpt=date_text)
        event_id = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
            subtype=_event_subtype(title), title=title, title_lang="es", organizer_entity_id=org,
            venue_id=venue_id, city="Santiago" if venue_name else None, country_code="CL" if venue_name else None,
            start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
            date_text=date_text, parser_version=PARSER_VERSION, url=item["url"], evidence_id=evidence_id,
        )
        if not venue_name:
            db.add_review(ctx.con, "region", "events", event_id, "venue country unknown")
        for artist in detail["artists"]:
            _add_person(ctx, event_id, evidence_id, artist, "artist", method="structured_field")
        for curator in detail["curators"]:
            _add_person(ctx, event_id, evidence_id, curator, "curator", method="structured_field")
        ctx.count("parsed")
    ctx.note("MNBA: first temporary-exhibitions listing page; its displayed dates are publication timestamps, while event periods/venue/participants come from details.")


def _csv_reader(response, required_fields: set[str]):
    if len(response.content) > MAX_CSV_BYTES:
        raise FetchError(f"Whitney Open Access CSV exceeds {MAX_CSV_BYTES} bytes: {response.url}")
    try:
        text = response.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FetchError(f"Whitney Open Access CSV is not UTF-8: {response.url}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = required_fields - set(reader.fieldnames or ())
    if missing:
        raise FetchError(f"Whitney Open Access CSV missing fields: {', '.join(sorted(missing))}")
    return reader


def _whitney_artists(ctx, response, evidence_id) -> dict[str, str]:
    required = {"id", "display_name", "getty_ulan_id", "wikidata_id", "begin_date", "end_date"}
    reader = _csv_reader(response, required)
    artists = {}
    for row in reader:
        artist_id = clean_text(row.get("id"))
        name = clean_text(row.get("display_name"))
        if not artist_id or not name:
            continue
        birth = _year(row.get("begin_date"))
        death = _year(row.get("end_date"))
        entity = db.ensure_entity(
            ctx.con, entity_type="person" if birth or death else "unknown", name=name,
            namespace="whitney_artist", id_value=artist_id, source_id=ctx.source_id,
            evidence_id=evidence_id, birth_year=birth, death_year=death,
        )
        ulan = clean_text(row.get("getty_ulan_id"))
        qid = clean_text(row.get("wikidata_id"))
        if ulan and ulan != "0":
            db.add_alias(ctx.con, entity, name, None, "ulan", ulan, ctx.source_id, evidence_id)
        if qid and qid != "0":
            db.add_alias(ctx.con, entity, name, None, "wikidata", qid, ctx.source_id, evidence_id)
        artists[artist_id] = entity
        ctx.count("fetched")
    return artists


def _csv_ids(value: str | None) -> list[str]:
    return _unique((part.strip() for part in (value or "").split(",")))


def _whitney_works(ctx, response, evidence_id, artists: dict[str, str], holding_id: str) -> int:
    required = {"id", "title", "display_date", "classification", "medium", "accession_number", "credit_line",
                "credit_line_repro", "artists", "artist_ids"}
    reader = _csv_reader(response, required)
    count = 0
    for row in reader:
        work_id = clean_text(row.get("id"))
        if not work_id:
            continue
        artist_ids = _csv_ids(row.get("artist_ids"))
        artist_name = clean_text(row.get("artists"))
        artist_entity = artists.get(artist_ids[0]) if artist_ids else None
        if len(artist_ids) == 1 and not artist_entity and artist_name:
            artist_entity = db.ensure_entity(
                ctx.con, entity_type="unknown", name=artist_name, namespace="whitney_artist",
                id_value=artist_ids[0], source_id=ctx.source_id, evidence_id=evidence_id,
            )
            artists[artist_ids[0]] = artist_entity
        work_meta = []
        for label, column in (("accession_number", "accession_number"), ("credit_line", "credit_line"),
                              ("reproduction_credit", "credit_line_repro")):
            value = clean_text(row.get(column))
            if value:
                work_meta.append(f"{label}={value}")
        db.upsert_work(
            ctx.con, ctx.stats, id_namespace="whitney", id_value=work_id, source_id=ctx.source_id,
            artist_entity_id=artist_entity, title=clean_text(row.get("title")) or None,
            date_text=clean_text(row.get("display_date")) or None,
            medium=clean_text(row.get("medium")) or None,
            classification=clean_text(row.get("classification")) or None,
            holding_entity_id=holding_id, acquisition_text=" | ".join(work_meta) or None,
            url=None, is_public_domain=None,
        )
        ctx.count("fetched")
        ctx.count("parsed")
        count += 1
        if count % 5_000 == 0:
            ctx.con.commit()
    return count


def _year(value: str | None) -> int | None:
    text = clean_text(value)
    return int(text) if text.isdigit() and int(text) > 0 else None


def _fetch_whitney_csv(ctx, url: str, locator: str):
    response = ctx.fetch(url, accept="text/csv")
    if urllib.parse.urlsplit(response.final_url).hostname != "raw.githubusercontent.com":
        raise FetchError(f"unexpected Whitney CSV host: {response.final_url}")
    if len(response.content) > MAX_CSV_BYTES:
        raise FetchError(f"Whitney Open Access CSV exceeds {MAX_CSV_BYTES} bytes: {url}")
    evidence_id = ctx.evidence(response, locator=locator)
    return response, evidence_id


def _collect_whitney_open_access(ctx):
    organization = _org(ctx, "Whitney Museum of American Art", "whitney", "https://whitney.org/")
    artists_response, artists_evidence = _fetch_whitney_csv(ctx, WHITNEY_ARTISTS_CSV, "artists.csv (CC0 metadata)")
    artworks_response, artworks_evidence = _fetch_whitney_csv(ctx, WHITNEY_ARTWORKS_CSV, "artworks.csv (CC0 metadata)")
    artists = _whitney_artists(ctx, artists_response, artists_evidence)
    ctx.con.commit()
    works = _whitney_works(ctx, artworks_response, artworks_evidence, artists, organization)
    ctx.con.commit()
    ctx.note(f"Whitney Open Access CSV: artists={len(artists)}, works={works}; only the first listed artist is linked in the current works schema.")
    ctx.note("The repository README dedicates dataset metadata to CC0 and says images are not included; no image URLs or API endpoints are fetched.")


def collect(ctx):
    handlers = {
        "wave2_saam_exhibitions": _collect_saam,
        "wave2_mnba_chile_exhibitions": _collect_mnba,
        "wave2_whitney_open_access": _collect_whitney_open_access,
    }
    handler = handlers.get(ctx.source_id)
    if handler is None:
        raise ValueError(f"unsupported museums-am source_id: {ctx.source_id}")
    handler(ctx)
    ctx.con.commit()
