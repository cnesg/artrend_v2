"""Every exhibition in Korea, small venues included: 문화포털 '한눈에 보는 문화정보' (culture.go.kr, 한국문화정보원).

Public institutions and local governments register their exhibitions here; it covers district galleries,
creation centres, municipal halls and private venues in all 17 regions (서울·부산·대구·인천·광주·대전·울산·세종·도).
Access: the public listing filtered to genre 06 (전시), every page, robots.txt allows /portal/cltInfo
(only /portal/search is disallowed). Stored per card: title, region, venue, dates, detail URL, listing image URL.
"""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from .. import db
from ._common import classify_subtype, clean_text

BASE = "https://www.culture.go.kr"
LIST = BASE + "/portal/cltInfo/oneCltInfo/list.do"
PARSER_VERSION = "kr-culture-portal-2"
MAX_PAGES = 150

SOURCES = [dict(
    source_id="kr_culture_portal", blueprint_data_id=None, blueprint_org_id=None,
    name="문화포털 — 한눈에 보는 문화정보(전시)", owner_group="한국문화정보원", source_kind="institution", region_scope="KR",
    country_codes="KR", access_method="html", base_url=BASE, entry_url=LIST + "?menuNo=200010&genreCds=06",
    terms_url=BASE + "/portal/main/contents.do?menuNo=200130", text_storage_policy="raw_internal", priority="P0",
    st_official_doc="n/a(public listing)", st_collection_terms="robots.txt allows the listing (only /portal/search disallowed); listing metadata only",
    st_image_terms="listing image URL recorded for internal preview; not downloaded",
    max_requests=MAX_PAGES + 5, notes="nationwide exhibition registry incl. small and district venues; work/dev/KRNational",
)]

CITY = {"서울": "Seoul", "부산": "Busan", "대구": "Daegu", "인천": "Incheon", "광주": "Gwangju", "대전": "Daejeon",
        "울산": "Ulsan", "세종": "Sejong", "전남광주통합": "Gwangju"}
REGIONS = r"서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|전남광주통합"
CARD = re.compile(r"전시\s+(?:(?:무료|유료|할인|,)\s*)*(" + REGIONS + r")\S*\s+(.*?)\s+장소\s+(.*?)\s+기간\s+(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
IMG_BASIS = "문화포털 listing image (registrant-supplied); rights not cleared — internal preview only"


def parse_cards(html: str, page_url: str) -> list:
    page = BeautifulSoup(html, "lxml")
    out = []
    for li in page.select("li"):
        a = li.select_one("a[href*=oneCltInfoView]")
        if not a:
            continue
        m = CARD.search(clean_text(li.get_text(" ")))
        if not m:
            continue
        region, title, venue, start, end = m.groups()
        url = urllib.parse.urljoin(page_url, a["href"])
        key = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("pblprfrSn", [url])[0]
        url = f"{BASE}/portal/cltInfo/oneCltInfo/oneCltInfoView.do?pblprfrSn={key}&menuNo=200010"
        img = li.select_one("img")
        src = urllib.parse.urljoin(page_url, img["src"]) if img and img.get("src") and "noimg" not in img["src"] else None
        out.append(dict(key=key, region=region, title=title.strip(), venue=venue.strip(), start=start, end=end, url=url, img=src))
    return out


def collect(ctx):
    seen = set()
    for n in range(1, MAX_PAGES + 1):
        resp = ctx.fetch(LIST, params=dict(menuNo="200010", genreCds="06", pageIndex=str(n)))
        cards = [c for c in parse_cards(resp.text, resp.url) if c["key"] not in seen]
        ctx.count("fetched", len(cards))
        if not cards:
            break
        for c in cards:
            seen.add(c["key"])
            ev = ctx.evidence(resp, locator=f"culture portal card {c['key']}", excerpt=f"{c['region']} {c['venue']} {c['start']}~{c['end']}")
            org = db.ensure_entity(ctx.con, entity_type="institution", name=c["venue"], namespace="src:kr_culture_portal",
                                   lang="ko", source_id=ctx.source_id, evidence_id=ev)
            eid = db.upsert_event(
                ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=c["key"], event_type="exhibition",
                subtype=classify_subtype(c["title"]) if "개인전" not in c["title"] else "solo", title=c["title"], title_lang="ko",
                organizer_entity_id=org, city=CITY.get(c["region"], c["region"]), country_code="KR",
                start_date=c["start"], start_precision="day", end_date=c["end"], end_precision="day",
                date_text=f"{c['start']} ~ {c['end']}", url=c["url"], parser_version=PARSER_VERSION, evidence_id=ev,
                description_excerpt=f"venue: {c['venue']} ({c['region']})")
            if c["img"]:
                db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=c["url"], image_url=c["img"],
                                    usage_status="unknown", basis=IMG_BASIS)
            ctx.count("parsed")
        ctx.con.commit()
    ctx.note(f"walked {n} page(s), {len(seen)} exhibitions (genre 06, all regions)")
