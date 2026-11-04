"""Verified Korean sourcebook additions: IAP programs, Ilmin exhibitions, and one criticism metadata sample."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin, urlsplit

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import clean_text, parse_date_range, soup

PARSER_VERSION = "sourcebook_kr-1"
IAP = "https://www.inartplatform.kr"
IAP_EXHIBITIONS = f"{IAP}/program/list"
IAP_RESIDENTS = f"{IAP}/residency/list"
IAP_NOTICES = f"{IAP}/notice/list"
ARTINCULTURE_ARTICLE = "https://artinculture.kr/webzine/rereading-13"
ILMIN = "https://ilmin.org"
ILMIN_CURRENT = f"{ILMIN}/exhibitions/current/"
ILMIN_PAST = f"{ILMIN}/exhibitions/past/"
HISTORY_FLOOR = "2025-04-01"

SOURCES = [
    dict(source_id="incheon_artplatform", blueprint_data_id=None, blueprint_org_id=None,
         name="Incheon Art Platform — exhibitions, resident rosters, public selections",
         owner_group="Incheon Art Platform / Incheon Foundation for Arts and Culture",
         source_kind="institution", region_scope="KR", country_codes="KR", access_method="html",
         base_url=IAP, entry_url=f"{IAP_EXHIBITIONS}?category=B&time=now", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", max_requests=200,
         st_official_doc="n/a(public HTML; official exhibition, resident and notice menus)",
         st_collection_terms=("robots.txt permits all paths (User-agent: * / Disallow: empty; checked 2026-10-28); "
                             "footer links privacy only and states Copyright @ Incheon Art Platform. All Rights Reserved. "
                             "No reuse licence or automated-access permission located; store only event/resident/selection "
                             "metadata and page evidence internally."),
         st_image_terms="No image downloads or reuse; footer reserves copyright; image licensing not stated.",
         notes="Sourcebook 한국-08-001; scope verified on public program, residency and notice pages."),
    dict(source_id="artinculture_criticism", blueprint_data_id=None, blueprint_org_id=None,
         name="Art In Culture — sourcebook criticism-page metadata", owner_group="Art In Culture",
         publisher="아트인컬처", source_kind="media", region_scope="KR", country_codes="KR", access_method="html(metadata)",
         base_url="https://artinculture.kr", entry_url=ARTINCULTURE_ARTICLE,
         terms_url="https://artinculture.kr/terms-of-use", text_storage_policy="metadata_only", priority="P1",
         max_requests=6, st_official_doc="n/a(public HTML; explicit author link and issue-month description)",
         st_collection_terms=("Terms of Use §22 assigns site-work copyright to the publisher and bars commercial "
                              "reproduction/transmission/publication/distribution without prior approval; robots allows "
                              "the verified article path. Store only title, author, issue month, URL and type metadata; "
                              "do not store body, summary or excerpt."),
         st_image_terms="No images collected; no reuse licence located.",
         notes="Sourcebook 한국-07-001 only; this does not cover the magazine archive or 한국-07-004."),
    dict(source_id="ilmin_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Ilmin Museum of Art — current and archived exhibitions", owner_group="Ilmin Cultural Foundation",
         source_kind="museum", region_scope="KR", country_codes="KR", access_method="html",
         base_url=ILMIN, entry_url=ILMIN_CURRENT, terms_url=f"{ILMIN}/terms-of-service/",
         text_storage_policy="raw_internal", priority="P1", max_requests=100,
         st_official_doc="n/a(public HTML; current/past exhibition pages and official detail pages)",
         st_collection_terms=("Terms of Service §21 assigns site-work copyright to Ilmin Museum and prohibits "
                              "commercial reproduction/transmission/publication/distribution without prior approval; "
                              "robots parsed and the current/past/detail/terms paths were allowed. Official Visit page "
                              "places the museum at 152 Sejong-daero, Jongno-gu, Seoul; no automated-access permission "
                              "located; metadata and internal page evidence only."),
         st_image_terms="No images downloaded or reused; site copyright applies; no open image licence located.",
         notes="Sourcebook 한국-03-012; archive listing exposes 12 pages; no curator/artist roster inferred."),
]


def collect(ctx):
    if ctx.source_id == "incheon_artplatform":
        return _collect_incheon(ctx)
    if ctx.source_id == "artinculture_criticism":
        return _collect_artinculture_criticism(ctx)
    if ctx.source_id == "ilmin_exhibitions":
        return _collect_ilmin(ctx)
    raise ValueError(ctx.source_id)


def _org(ctx):
    entity_id = db.ensure_entity(
        ctx.con, entity_type="institution", name="인천아트플랫폼", namespace=f"src:{ctx.source_id}",
        id_value="incheon-art-platform", lang="ko", source_id=ctx.source_id, official_url=IAP + "/")
    ctx.con.commit()
    return entity_id


def _collect_incheon(ctx):
    organizer = _org(ctx)
    today = now_kst().date()
    cards = {}
    list_limit = 10 if ctx.mode == "initial" else 1
    for period in ("now", "past"):
        page = 1
        while page <= list_limit:
            params = {"category": "B", "time": period}
            if page > 1:
                params["p"] = page
            listing = ctx.fetch(IAP_EXHIBITIONS, params=params)
            items = _program_cards(listing.text, listing.url)
            ctx.count("fetched", len(items))
            for item in items:
                cards.setdefault(item["id"], item)
            if page == 1:
                max_page = _page_count(listing.text, "/program/list")
            dates = [item["start"] for item in items if item["start"]]
            if (ctx.mode == "initial" and period == "past" and dates
                    and max(dates) < HISTORY_FLOOR):
                ctx.note(f"IAP exhibition archive reached {max(dates)} on page {page}; stopped at history floor")
                break
            if page >= max_page or not items:
                break
            page += 1
        if page >= list_limit and ctx.mode == "initial" and period == "past":
            ctx.note(f"IAP past exhibition listing stopped at page cap {list_limit}")

    detail_limit = 70 if ctx.mode == "initial" else 35
    ordered_cards = sorted(cards.values(), key=lambda item: (item["start"] or "", item["id"]), reverse=True)
    parsed_details = 0
    for item in ordered_cards:
        if ctx.mode == "initial" and item["end"] and item["end"] < HISTORY_FLOOR:
            continue
        if not _needs_detail(ctx, item["id"], today):
            continue
        if parsed_details >= detail_limit or _request_cap_reached(ctx):
            ctx.note(f"IAP exhibition details stopped at the bounded {detail_limit}-record/request budget")
            break
        try:
            detail = ctx.fetch(item["url"])
        except FetchError as error:
            ctx.count("detail_errors")
            ctx.note(f"exhibition {item['id']}: {error}")
            continue
        _store_exhibition(ctx, organizer, item, detail)
        parsed_details += 1
        ctx.con.commit()

    _collect_residencies(ctx, organizer)
    _collect_selection_notices(ctx, organizer, today)
    ctx.con.commit()
    ctx.note("IAP history uses the public program listing's current and past pages, resident year tabs, and notice archive; "
             "no images or notice attachments are fetched. No body text is stored in article records.")


def _program_cards(html, page_url):
    page = soup(html)
    section = page.select_one("#board_exhibitNow")
    if section is None:
        return []
    cards = []
    for li in section.select(".gallery_list li"):
        anchor = li.select_one('a[href*="/program/view?no="]')
        if anchor is None:
            continue
        match = re.search(r"(?:\?|&)no=(\d+)", anchor.get("href", ""))
        if not match:
            continue
        date_node = li.select_one(".date")
        date_text = clean_text(date_node.get_text(" ")) if date_node else None
        if date_node:
            date_node.extract()
        title = clean_text(anchor.get_text(" "))
        if not title:
            continue
        start, _, end, _ = _parse_range(date_text)
        cards.append({"id": match.group(1), "title": title, "date_text": date_text,
                      "start": start, "end": end, "url": urljoin(page_url, anchor["href"])})
    return cards


def _parse_range(text):
    normalized = re.sub(r"\s*\([A-Za-z가-힣]{1,8}\)", "", text or "")
    return parse_date_range(normalized)


def _page_count(html, path):
    pages = []
    for anchor in soup(html).select('a[href*="p="]'):
        parsed = urlsplit(anchor.get("href", ""))
        if parsed.path.rstrip("/") != path.rstrip("/"):
            continue
        match = re.search(r"(?:\?|&)p=(\d+)", anchor["href"])
        if match:
            pages.append(int(match.group(1)))
    return max(pages or [1])


def _needs_detail(ctx, key, today):
    if ctx.mode == "initial":
        return True
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, f"exhibition-{key}")).fetchone()
    cutoff = (today - dt.timedelta(days=30)).isoformat()
    return row is None or not row[0] or row[0] >= cutoff


def _request_cap_reached(ctx):
    return ctx.stats.get("http_requests", 0) >= ctx.fetcher.max_requests


def _store_exhibition(ctx, organizer, item, response):
    title, date_text, venue = _exhibition_detail_fields(response.text, item["title"], item["date_text"])
    start, start_precision, end, end_precision = _parse_range(date_text)
    city, country = _venue(venue)
    evidence = ctx.evidence(response, locator="#exhibitNow_view .view_top / 기간 / 장소",
                            excerpt=date_text or title)
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"exhibition-{item['id']}",
        event_type="exhibition", subtype=_subtype(title), title=title, title_lang="ko",
        organizer_entity_id=organizer, city=city, country_code=country,
        start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
        date_text=date_text, url=response.url, evidence_id=evidence, parser_version=PARSER_VERSION)
    if country is None:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=venue or None)
    ctx.count("parsed")


def _exhibition_detail_fields(html, fallback_title=None, fallback_date=None):
    page = soup(html)
    root = page.select_one("#exhibitNow_view")
    top = root.select_one(".view_top") if root else None
    heading = top.select_one("h4") if top else None
    title = clean_text(heading.get_text(" ")) if heading else fallback_title
    values = {}
    if root:
        for li in root.select("li"):
            label, value = li.select_one("b"), li.select_one("p")
            if label and value:
                values.setdefault(clean_text(label.get_text(" ")), clean_text(value.get_text(" ")))
    return title, values.get("기간") or fallback_date, values.get("장소")


def _subtype(title):
    if "개인전" in title:
        return "solo"
    if "2인전" in title or "2인" in title:
        return "two_person"
    if "단체전" in title:
        return "group"
    return "unknown"


def _venue(value):
    if value and "인천아트플랫폼" in value:
        return "Incheon", "KR"
    return None, None


def _collect_ilmin(ctx):
    organizer = db.ensure_entity(ctx.con, entity_type="museum", name="일민미술관",
                                 namespace=f"src:{ctx.source_id}", id_value="ilmin-museum",
                                 lang="ko", source_id=ctx.source_id, official_url=ILMIN + "/")
    ctx.con.commit()
    cards = {}
    current = ctx.fetch(ILMIN_CURRENT)
    current_cards = _ilmin_cards(current.text, current.url)
    ctx.count("fetched", len(current_cards))
    for item in current_cards:
        cards.setdefault(item["id"], item)

    page_limit = 12 if ctx.mode == "initial" else 1
    page = 1
    max_page = 1
    oldest_start = None
    while page <= page_limit:
        listing = ctx.fetch(ILMIN_PAST if page == 1 else f"{ILMIN_PAST}page/{page}/?et_loop_archive")
        items = _ilmin_cards(listing.text, listing.url)
        ctx.count("fetched", len(items))
        for item in items:
            cards.setdefault(item["id"], item)
        if page == 1:
            max_page = _ilmin_page_count(listing.text)
        starts = [item["start"] for item in items if item["start"]]
        if starts:
            page_oldest = min(starts)
            oldest_start = min(oldest_start, page_oldest) if oldest_start else page_oldest
            if ctx.mode == "initial" and max(starts) < HISTORY_FLOOR:
                ctx.note(f"Ilmin past archive reached {max(starts)} on page {page}; stopped at history floor")
                break
        if page >= max_page or not items:
            break
        page += 1
    if page >= page_limit and ctx.mode == "initial" and page < max_page:
        ctx.note(f"Ilmin archive stopped at the {page_limit}-page cap; oldest listing start={oldest_start or 'unknown'}")

    today = now_kst().date()
    detail_limit = 70 if ctx.mode == "initial" else 25
    ordered = sorted(cards.values(), key=lambda item: (item["start"] or "", item["id"]), reverse=True)
    parsed = 0
    for item in ordered:
        if ctx.mode == "initial" and item["end"] and item["end"] < HISTORY_FLOOR:
            continue
        if not _needs_detail(ctx, item["id"], today):
            continue
        if parsed >= detail_limit or _request_cap_reached(ctx):
            ctx.note(f"Ilmin detail pages stopped at the bounded {detail_limit}-record/request budget")
            break
        try:
            detail = ctx.fetch(item["url"])
        except FetchError as error:
            ctx.count("detail_errors")
            ctx.note(f"exhibition {item['id']}: {error}")
            continue
        _store_ilmin_exhibition(ctx, organizer, item, detail)
        parsed += 1
        ctx.con.commit()
    ctx.note(f"Ilmin current/past listings: {len(cards)} distinct exhibition cards; {parsed} detail page(s) parsed; "
             f"archive page {page}/{max_page}; source venue strings without a verified geography are left unknown.")


def _ilmin_cards(html, page_url):
    output = []
    for card in soup(html).select(".exhibition-loop-item"):
        title_node = card.select_one(".exhibition_title")
        title = clean_text(title_node.get_text(" ")) if title_node else ""
        anchor = title_node.select_one('a[href*="/exhibition/"]') if title_node else None
        if anchor is None:
            anchor = card.select_one('a[href*="/exhibition/"]')
        if anchor is None:
            continue
        url = urljoin(page_url, anchor.get("href", ""))
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        date_node = card.select_one(".exhibition_date")
        date_text = clean_text(date_node.get_text(" ")) if date_node else None
        if not title:
            title = clean_text(anchor.get_text(" "))
        if not slug or not title:
            continue
        start, _, end, _ = _parse_range(date_text)
        output.append({"id": slug, "title": title, "date_text": date_text,
                       "start": start, "end": end, "url": url})
    return output


def _ilmin_page_count(html):
    pages = [1]
    for anchor in soup(html).select('a[href*="/exhibitions/past/page/"]'):
        match = re.search(r"/exhibitions/past/page/(\d+)", anchor.get("href", ""))
        if match:
            pages.append(int(match.group(1)))
    return max(pages)


def _ilmin_detail_fields(html, fallback_title=None, fallback_date=None):
    page = soup(html)
    title_meta = page.select_one('meta[property="og:title"]')
    title = clean_text(title_meta.get("content")) if title_meta else fallback_title
    title = re.sub(r"\s*[-–—]\s*일민미술관$", "", title or "").strip() or fallback_title
    date_text = venue = None
    for node in page.select(".summury-box .exhibition-summury"):
        value = clean_text(node.get_text(" "))
        if not value:
            continue
        if _parse_range(value)[0]:
            date_text = date_text or value
        elif not venue:
            venue = value
    return title, date_text or fallback_date, venue


def _ilmin_venue(value):
    text = (value or "").casefold()
    if "seoul" in text or "서울" in text or "exhibition hall" in text or "project room" in text:
        return "Seoul", "KR"
    if "belgium" in text or "brussels" in text or "ghent" in text:
        return None, "BE"
    if "united kingdom" in text or "london" in text or re.search(r"\buk\b", text):
        return None, "GB"
    if "japan" in text or "tokyo" in text or "osaka" in text:
        return None, "JP"
    return None, None


def _store_ilmin_exhibition(ctx, organizer, item, response):
    title, date_text, venue = _ilmin_detail_fields(response.text, item["title"], item["date_text"])
    start, start_precision, end, end_precision = _parse_range(date_text)
    city, country = _ilmin_venue(venue)
    evidence = ctx.evidence(response, locator=".summury-box exhibition title/period/venue",
                            excerpt=date_text or title)
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"exhibition-{item['id']}",
        event_type="exhibition", subtype=_subtype(title), title=title, title_lang="ko",
        organizer_entity_id=organizer, city=city, country_code=country,
        start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
        date_text=date_text, url=response.url, evidence_id=evidence, parser_version=PARSER_VERSION)
    if country is None:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=venue or None)
    ctx.count("parsed")


def _collect_residencies(ctx, organizer):
    first = ctx.fetch(IAP_RESIDENTS, params={"sub_category": 0})
    default_year, _, _ = _residency_roster(first.text, first.url)
    if not default_year:
        ctx.note("IAP resident listing did not expose a year; no residency event inferred")
        return
    years = [default_year]
    if ctx.mode == "initial":
        options = _residency_years(first.text)
        years = sorted({year for year in options if HISTORY_FLOOR[:4] <= year <= default_year}, reverse=True)
        years = years[:2]
        if default_year not in years:
            years.insert(0, default_year)
    for year in years:
        if _request_cap_reached(ctx):
            ctx.note("IAP resident roster history stopped at the request budget")
            break
        response = first if year == default_year else ctx.fetch(
            IAP_RESIDENTS, params={"category": year, "sub_category": 0})
        _, program, residents = _residency_roster(response.text, response.url)
        if not residents:
            ctx.note(f"IAP residency year {year}: public roster has no artist links")
            continue
        evidence = ctx.evidence(response, locator="#board_artists .gallery_list .residency/view",
                                excerpt=f"{program or year}: {', '.join(name for name, _, _ in residents)}")
        event_id = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"residency-{year}",
            event_type="residency", title=program or f"인천아트플랫폼 {year} 입주작가", title_lang="ko",
            organizer_entity_id=organizer, start_date=str(year), start_precision="year",
            date_text=year, url=response.url, evidence_id=evidence, parser_version=PARSER_VERSION)
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown",
                      detail="Resident-year listing does not state a specific venue.")
        for name, resident_id, artist_url in residents:
            entity = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace="incheon_resident",
                                      id_value=resident_id, lang="ko", source_id=ctx.source_id,
                                      evidence_id=evidence, official_url=artist_url)
            db.add_participant(ctx.con, event_id, entity, "resident", name, evidence, "list_markup", "high")
        ctx.count("fetched", len(residents))
        ctx.count("parsed")
        ctx.con.commit()
    if ctx.mode == "initial":
        ctx.note("IAP resident roster: annual tabs exposed 2025 and 2026; older tabs were not crawled")
    else:
        ctx.note(f"IAP resident roster: current public tab {default_year} only")


def _residency_years(html):
    years = set()
    for anchor in soup(html).select('a[href*="/residency/list?category="]'):
        match = re.search(r"[?&]category=(20\d{2})", anchor.get("href", ""))
        if match:
            years.add(match.group(1))
    for option in soup(html).select("#board_artists option[value]"):
        if re.fullmatch(r"20\d{2}", option.get("value", "")):
            years.add(option["value"])
    return years


def _residency_roster(html, page_url):
    section = soup(html).select_one("#board_artists")
    if section is None:
        return None, None, []
    heading = section.select_one("h4.sub_tit03")
    program = clean_text(heading.get_text(" ")) if heading else None
    year_match = re.search(r"20\d{2}", program or "")
    year = year_match.group(0) if year_match else None
    residents = []
    for anchor in section.select('.gallery_list a[href*="/residency/view?residency="]'):
        match = re.search(r"(?:\?|&)residency=(\d+)", anchor.get("href", ""))
        name = clean_text(anchor.get_text(" "))
        name = re.sub(r"\s*작가\s*$", "", name).strip()
        if match and name:
            residents.append((name, match.group(1), urljoin(page_url, anchor["href"])))
    return year, program, residents


def _collect_selection_notices(ctx, organizer, today):
    page_limit = 9 if ctx.mode == "initial" else 1
    page = 1
    cards = {}
    max_page = 1
    while page <= page_limit and not _request_cap_reached(ctx):
        params = {"p": page} if page > 1 else None
        response = ctx.fetch(IAP_NOTICES, params=params)
        entries = _notice_cards(response.text, response.url)
        ctx.count("fetched", len(entries))
        for item in entries:
            cards.setdefault(item["id"], item)
        if page == 1:
            max_page = _page_count(response.text, "/notice/list")
        dated = [item["date"] for item in entries if item["date"]]
        if ctx.mode == "initial" and dated and max(dated) < HISTORY_FLOOR:
            ctx.note(f"IAP notice archive reached {max(dated)} on page {page}; stopped at history floor")
            break
        if page >= max_page or not entries:
            break
        page += 1
    candidates = [item for item in cards.values() if _is_selection_notice(item["title"])]
    candidates.sort(key=lambda item: (item["date"] or "", item["id"]), reverse=True)
    detail_limit = 50 if ctx.mode == "initial" else 20
    parsed = 0
    for item in candidates:
        if ctx.mode == "initial" and item["date"] and item["date"] < HISTORY_FLOOR:
            continue
        if not ctx.mode == "initial" and item["date"] and item["date"] < (today - dt.timedelta(days=365)).isoformat():
            continue
        if parsed >= detail_limit or _request_cap_reached(ctx):
            ctx.note(f"IAP selection notices stopped at the bounded {detail_limit}-detail/request budget")
            break
        try:
            detail = ctx.fetch(item["url"])
        except FetchError as error:
            ctx.count("detail_errors")
            ctx.note(f"notice {item['id']}: {error}")
            continue
        if _store_selection_notice(ctx, organizer, item, detail):
            parsed += 1
        ctx.con.commit()
    ctx.note(f"IAP notice archive: {len(cards)} notice rows, {len(candidates)} selection/result titles; "
             f"parsed {parsed} public detail page(s) without downloading attachments")


def _notice_cards(html, page_url):
    section = soup(html).select_one("#board_notice")
    if section is None:
        return []
    output = []
    for row in section.select("tr.list_body"):
        anchor = row.select_one('a[href*="/notice/view?no="]')
        cells = row.find_all("td", recursive=False)
        match = re.search(r"(?:\?|&)no=(\d+)", anchor.get("href", "")) if anchor else None
        if not match or len(cells) < 3:
            continue
        title = clean_text(anchor.get_text(" "))
        date = clean_text(cells[-1].get_text(" "))
        date = date if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date) else None
        output.append({"id": match.group(1), "title": title, "date": date,
                       "url": urljoin(page_url, anchor["href"])})
    return output


def _is_selection_notice(title):
    return bool(re.search(r"선정\s*(?:결과|공고|자)|선발\s*(?:결과|자)|최종\s*(?:심의\s*)?결과|수상자|당선자", title or ""))


def _store_selection_notice(ctx, organizer, item, response):
    page = soup(response.text)
    section = page.select_one("#notice_view")
    if section is None:
        ctx.count("detail_errors")
        ctx.note(f"notice {item['id']}: public detail has no #notice_view section")
        return False
    heading = section.select_one(".view_title")
    title = clean_text(heading.get_text(" ")) if heading else item["title"]
    posted = item["date"]
    if not posted:
        info = section.select_one(".view_info")
        date_match = re.search(r"20\d{2}-\d{2}-\d{2}", clean_text(info.get_text(" ")) if info else "")
        posted = date_match.group(0) if date_match else None
    explicit_lines = [clean_text(node.get_text(" ")) for node in section.select("p")]
    selected = _selection_names(explicit_lines)
    is_award = bool(re.search(r"수상|어워드|미술상", title))
    event_type = "award" if is_award else "open_call_selection"
    excerpt = next((line for line in explicit_lines if _selection_names([line])), title)
    evidence = ctx.evidence(response, locator="#notice_view .view_title / explicit selection line",
                            excerpt=excerpt)
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"selection-{item['id']}",
        event_type=event_type, title=title, title_lang="ko", organizer_entity_id=organizer,
        announced_date=posted, date_text=posted, url=response.url, evidence_id=evidence,
        parser_version=PARSER_VERSION)
    if selected:
        role = "winner" if is_award else (
            "resident" if re.search(r"입주|레지던시|창작스튜디오", title) else "selected")
        for name in selected:
            entity_type = "group" if re.search(r"팀|단체|그룹", name) else "person"
            entity = db.ensure_entity(ctx.con, entity_type=entity_type, name=name,
                                      namespace=f"src:{ctx.source_id}", source_id=ctx.source_id,
                                      evidence_id=evidence)
            db.add_participant(ctx.con, event_id, entity, role, name, evidence, "structured_field", "high")
    db.add_review(ctx.con, "region", "events", event_id, "venue country unknown",
                  detail="Public selection notice has no event venue; announcement location is not inferred.")
    ctx.count("parsed")
    return True


def _selection_names(lines):
    names = []
    pattern = re.compile(r"(?:선정자|선정\s*작가|수상자|당선자|최종\s*선정(?:자|작가)?)\s*[:：]\s*(.+)")
    for line in lines:
        match = pattern.search(line or "")
        if not match:
            continue
        name = clean_text(match.group(1)).strip(" .·,，;；:：<>[]()『』〈〉")
        if name and len(name) <= 100 and name not in names:
            names.append(name)
    return names


def _collect_artinculture_criticism(ctx):
    response = ctx.fetch(ARTINCULTURE_ARTICLE)
    metadata = _artinculture_metadata(response.text)
    title, author, published_at = metadata["title"], metadata["author"], metadata["published_at"]
    if not title or not author:
        ctx.count("fetched")
        ctx.count("skipped_incomplete")
        ctx.note("Art In Culture criticism page lacks a visible title or explicit author link; no article stored")
        return
    db.upsert_article(
        ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=response.url, title=title,
        published_at=published_at, author_text=author, publisher=ctx.meta["publisher"],
        owner_group=ctx.meta["owner_group"], article_type="criticism",
        type_basis="sourcebook 한국-07-001 identifies the official page as a criticism contribution",
        lang="ko", categories="webzine; issue month only" if published_at else "webzine",
        excerpt=None)
    ctx.count("fetched")
    ctx.count("parsed")
    ctx.note("Sourcebook 한국-07-001 sample only; issue month is stored as YYYY-MM without inventing a day. "
             "No article text, excerpt, or image is stored; no general archive crawl is performed.")
    ctx.con.commit()


def _artinculture_metadata(html):
    page = soup(html)
    heading = page.select_one("h1")
    title = clean_text(heading.get_text(" ")) if heading else None
    author = next((clean_text(anchor.get_text(" ")) for anchor in page.select('a[href*="author="]')
                   if clean_text(anchor.get_text(" "))), None)
    description = next((clean_text(meta.get("content")) for meta in page.select(
        'meta[name="description"], meta[property="og:description"]') if meta.get("content")), "")
    month = re.search(r"(20\d{2})년\s*(\d{1,2})월호", description)
    published_at = f"{month.group(1)}-{int(month.group(2)):02d}" if month else None
    return {"title": title, "author": author, "published_at": published_at}
