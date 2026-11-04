"""APMA exhibition-level records derived from its public exhibition article pages."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import db
from ..http import FetchError
from ._common import classify_subtype, clean_text, parse_date_range, split_title_artist

PARSER_VERSION = "kr_apma-2"

APMA = "https://apma.amorepacific.com"
ENTRY = f"{APMA}/contents/exhibition/index.do"
_DATE = r"20\d{2}\s*[./-]\s*\d{1,2}(?:\s*[./-]\s*\d{1,2}\.?)*"
_DATE_RANGE = re.compile(rf"({_DATE}(?:\s*\([^)]*\))?)\s*[-–—~]\s*({_DATE}(?:\s*\([^)]*\))?)")

SOURCES = [
    dict(source_id="apma_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Amorepacific Museum of Art (APMA) — exhibitions", owner_group="Amorepacific",
         source_kind="museum", region_scope="KR", country_codes="KR", access_method="html",
         base_url=APMA, entry_url=ENTRY, terms_url="https://www.beautypoint.co.kr/agreement",
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="site links to Beauty Point user agreement; no source-specific automated-access terms located; "
                             "footer © 2018 Amorepacific",
         st_image_terms="detail pages show artist/APMA credits; images are not collected", max_requests=40),
]


def collect(ctx):
    organizer = db.ensure_entity(
        ctx.con, entity_type="museum", name="Amorepacific Museum of Art (APMA)",
        namespace=f"src:{ctx.source_id}", id_value="apma", source_id=ctx.source_id,
        official_url=f"{APMA}/")
    listing = ctx.fetch(ENTRY)
    page = BeautifulSoup(listing.text, "lxml")
    links = []
    for link in page.find_all("a", href=True):
        if re.fullmatch(r"/contents/exhibition/\d+/view\.do", link["href"]):
            links.append(link)
    ctx.count("fetched", len(links))

    oldest = None
    for link in links:
        article_id = re.search(r"/exhibition/(\d+)/view\.do", link["href"]).group(1)
        article_title = clean_text(link.get_text(" "))
        url = urljoin(APMA, link["href"])
        try:
            detail = ctx.fetch(url)
        except FetchError as e:
            ctx.note(f"detail {article_id}: {e}")
            ctx.count("detail_errors")
            continue

        detail_page = BeautifulSoup(detail.text, "lxml")
        content = detail_page.select_one("#contents") or detail_page.find("main") or detail_page
        heading = next((node for node in content.find_all(["h2", "h3", "h4"])
                        if re.match(r"\s*\[", clean_text(node.get_text(" ")))), None)
        raw_title = clean_text(heading.get_text(" ")) if heading else article_title
        title = _exhibition_title(raw_title)
        if not title:
            ctx.note(f"detail {article_id}: exhibition title not found")
            continue
        date_line, location = _date_and_location(content)
        if not date_line:
            ctx.note(f"detail {article_id}: no exhibition date range in public detail HTML")
            continue
        start, start_precision, end, end_precision = _parse_date_range(date_line)
        if not start and not end:
            ctx.note(f"detail {article_id}: unparsed date range {date_line!r}")
            continue

        explicit_venue = bool(location and re.search(r"(?:APMA|아모레퍼시픽미술관|미술관\s*(?:1F|B1))", location, re.I))
        city, country_code = ("Seoul", "KR") if explicit_venue else (None, None)
        event_key = _event_key(title, start, start_precision, end, end_precision, location, article_id)
        existing = ctx.con.execute(
            "SELECT title,url FROM events WHERE source_id=? AND source_event_key=?", (ctx.source_id, event_key)
        ).fetchone()
        # Exact duplicate content articles may share an event key. Keep the first event title and URL while attaching
        # evidence from every detail page; case-only title variants are not separate exhibition records.
        event_title = existing["title"] if existing else title
        event_url = existing["url"] if existing and existing["url"] else detail.url

        evidence = ctx.evidence(detail, locator=f"exhibition article {article_id} / schedule line",
                                excerpt=date_line)
        artist = split_title_artist(title)
        subtype = classify_subtype(title, 1 if artist else None)
        event_id = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=event_key,
            event_type="exhibition", subtype=subtype, title=event_title, title_lang=None,
            organizer_entity_id=organizer, city=city, country_code=country_code,
            start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
            date_text=date_line, url=event_url, evidence_id=evidence, parser_version=PARSER_VERSION,
            description_excerpt=location)
        if artist:
            artist_entity = db.ensure_entity(ctx.con, entity_type="person", name=artist,
                                             namespace=f"src:{ctx.source_id}", source_id=ctx.source_id,
                                             evidence_id=evidence)
            db.add_participant(ctx.con, event_id, artist_entity, "artist", artist, evidence,
                               "title_pattern", "medium")
        _record_image_rights(ctx, detail, content, event_id)
        if not country_code:
            db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=location)
        ctx.count("parsed")
        if start and (oldest is None or start < oldest):
            oldest = start

    ctx.con.commit()
    ctx.note(f"APMA index exposes {len(links)} exhibition-content articles; no public HTML pagination is present "
             f"(its robots file disallows Ajax URLs). Oldest parsed exhibition start={oldest or 'unknown'}")


def _exhibition_title(text):
    match = re.match(r"\s*\[([^\]]+)\]", text or "")
    return clean_text(match.group(1)) if match else clean_text(text)


def _date_and_location(content):
    for line in content.get_text("\n").splitlines():
        line = clean_text(line)
        if not line:
            continue
        match = _DATE_RANGE.search(line)
        if not match:
            continue
        date_line = line.split("|", 1)[0].strip()
        location = line.split("|", 1)[1].strip() if "|" in line else None
        return clean_text(date_line), clean_text(location) or None
    text = clean_text(content.get_text(" "))
    match = _DATE_RANGE.search(text)
    return (clean_text(match.group(0)), None) if match else (None, None)


def _parse_date_range(date_text):
    """Parse APMA's dotted schedule dates, including spaces and weekday labels, without changing evidence text."""
    normalized = re.sub(r"\s*\([가-힣]{1,3}\)", "", date_text or "")
    normalized = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", normalized)
    return parse_date_range(normalized)


def _event_key(title, start, start_precision, end, end_precision, location, article_id):
    if location and start and end:
        return db.sid("apma_event", db.name_key(title), start, start_precision, end, end_precision,
                      db.name_key(location))
    # Without title/date/venue evidence, keep article records separate instead of guessing duplicates.
    return f"article-{article_id}"


def _record_image_rights(ctx, resp, content, event_id):
    text = content.get_text("\n")
    credit = next((clean_text(line) for line in text.splitlines() if "©" in line), None)
    for image in content.find_all("img"):
        source = image.get("data-src") or image.get("data-original") or image.get("src")
        if not source or source.startswith("data:"):
            continue
        db.add_image_rights(
            ctx.con, source_id=ctx.source_id, usage_status="unknown",
            basis="APMA detail page credits/copyright where shown; no open licence stated; image URL recorded only, not downloaded",
            page_url=resp.url, image_url=urljoin(resp.url, source), event_id=event_id, credit=credit)
