"""Kiaf Seoul fair edition from its verified public Info page."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import db
from ._common import clean_text, parse_date_range

PARSER_VERSION = "kr_kiaf-2"
KIAF = "https://kiaf.org"
INFO_URL = f"{KIAF}/info"
EXHIBITORS_URL = f"{KIAF}/exhibitors-index"

SOURCES = [
    dict(source_id="kiaf_seoul", blueprint_data_id="D23", blueprint_org_id=None,
         name="Kiaf SEOUL — verified fair edition information", owner_group="Korea Galleries Association",
         source_kind="fair", region_scope="KR", country_codes="KR", access_method="html",
         base_url=KIAF, entry_url=INFO_URL, terms_url=f"{KIAF}/terms-conditions",
         text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html)",
         st_collection_terms="Terms & Conditions reserve site content copyright to Kiaf and exhibitors and prohibit reuse on other sites "
                             "without permission; no crawler clause observed",
         st_image_terms="exhibitor/gallery content may be third-party copyrighted; images are not collected",
         notes="Fair dates and venue are read from the public Info page. Exhibitors unresolved: identified public rendering "
               "timed out after a bounded 120-second attempt despite HTTP 200 responses (2026-10-28); no direct Vue endpoint calls "
               "or further automatic rendering retries. This is a technical extraction limit, not an access-permission block. "
               "No galleries or artists inferred; publication/reuse requires permission.",
         max_requests=5),
]


def collect(ctx):
    organizer = db.ensure_entity(
        ctx.con, entity_type="fair", name="Kiaf SEOUL", namespace=f"src:{ctx.source_id}",
        id_value="kiaf-seoul", source_id=ctx.source_id, official_url=KIAF + "/")
    info = ctx.fetch(INFO_URL, accept="text/html")
    editions = _parse_editions(info.text, info.url)
    if not editions:
        ctx.note("Public Info page has no edition with explicit year, full date range, and venue; no fair edition stored")
        ctx.con.commit()
        return

    ctx.count("fetched", len(editions))
    for edition in editions:
        evidence = ctx.evidence(info, locator=f"Kiaf SEOUL {edition['year']} / public date and venue",
                                excerpt=f"{edition['date_text']} | {edition['venue']}")
        event_id = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"kiaf-seoul-{edition['year']}",
            event_type="fair_edition", title=edition["title"], title_lang="en", organizer_entity_id=organizer,
            city=edition["city"], country_code=edition["country_code"],
            start_date=edition["start"], start_precision=edition["start_precision"],
            end_date=edition["end"], end_precision=edition["end_precision"],
            date_text=edition["date_text"], url=info.url, evidence_id=evidence,
            description_excerpt=edition["venue"], parser_version=PARSER_VERSION)
        if not edition["country_code"]:
            db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", edition["venue"])
        ctx.count("parsed")
    ctx.con.commit()

    ctx.note(f"Fair-edition metadata only. Exhibitors unresolved at {EXHIBITORS_URL} after bounded public rendering; no further retries or direct internal API calls.")


def _parse_editions(html, page_url):
    page = BeautifulSoup(html, "lxml")
    editions = []
    seen_years = set()
    for title_node in page.select(".row.section .title"):
        match = re.fullmatch(r"Kiaf\s+SEOUL\s+(20\d{2})", clean_text(title_node.get_text(" ")), re.I)
        if not match:
            continue
        year = int(match.group(1))
        if year in seen_years:
            continue
        container = title_node.find_parent(class_="col-12") or title_node.parent
        details = container.select_one(".title-desc") if container else None
        if not details:
            continue
        detail_text = clean_text(details.get_text(" "))
        date_match = re.search(
            r"(?P<start>20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})\s*[-–—~]\s*"
            r"(?P<end>(?:20\d{2}\s*[./-]\s*)?\d{1,2}\s*[./-]\s*\d{1,2})", detail_text)
        if not date_match:
            continue
        date_text = clean_text(date_match.group(0))
        start_text, end_text = date_match.group("start"), date_match.group("end")
        end_has_year = bool(re.match(r"20\d{2}\s*[./-]", end_text))
        normalized_end = end_text if end_has_year else f"{year}.{end_text}"
        normalized = f"{start_text} – {normalized_end}"
        start, start_precision, end, end_precision = parse_date_range(normalized)
        if not start or not end:
            continue
        venue = clean_text(detail_text[:date_match.start()].strip(" ,|"))
        if not venue:
            continue
        is_seoul_coex = bool(re.search(r"서울|Seoul", venue, re.I) and re.search(r"COEX", venue, re.I))
        editions.append({
            "year": year, "title": f"Kiaf SEOUL {year}", "date_text": date_text,
            "start": start, "start_precision": start_precision,
            "end": end, "end_precision": end_precision,
            "venue": venue, "city": "Seoul" if is_seoul_coex else None,
            "country_code": "KR" if is_seoul_coex else None,
            "url": page_url,
        })
        seen_years.add(year)
    return editions


