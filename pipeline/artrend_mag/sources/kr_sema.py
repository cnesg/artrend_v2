"""Seoul Museum of Art (SeMA) — exhibitions across all branches (Blueprint D09 / O02).

robots.txt: `Disallow: /` with `Allow: /kr/whatson`, `/en/whatson`, `/kr/bbs` (RFC 9309 longest match lets the
what's-on listing and exhibition detail pages through). `/kr/whatson/exhibition/list` returns HTTP 500; the real
listing is `/kr/whatson/landing?whatsonMenuDivList=EX&whenType=FROM_TODAY|PLAN_DAY|PAST_DAY&currentPage=N`
(12 cards per page). Exhibition detail pages (`/kr/whatson/exhibition/detail?exNo=`) carry structured
`전시장소 / 전시기간 / 전시장르 / 참여작가` blocks. Support-program (신진미술인) selection pages live under
`/kr/support`, which robots.txt disallows, so open-call selections are not collected here.
"""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import classify_subtype, clean_text, parse_date_range, soup

PARSER_VERSION = "kr_sema-1"
BASE = "https://sema.seoul.go.kr"
LANDING = f"{BASE}/kr/whatson/landing"
DETAIL = f"{BASE}/kr/whatson/exhibition/detail"

SOURCES = [dict(
    source_id="sema_whatson", blueprint_data_id="D09", blueprint_org_id="O02", name="Seoul Museum of Art (SeMA) — 전시",
    owner_group="Seoul Museum of Art", source_kind="museum", region_scope="KR", country_codes="KR",
    access_method="html", base_url=BASE,
    entry_url=f"{LANDING}?whatsonMenuDivList=EX&whatChoice2=N&whatChoice3=N&whatChoice4=N&whatChoice5=N&whenType=FROM_TODAY",
    terms_url=None, text_storage_policy="raw_internal", priority="P0", max_requests=250,
    st_official_doc="n/a(html)",
    st_collection_terms="terms page not located (robots.txt allows only /kr/whatson, /en/whatson, /kr/bbs; site policy pages are outside the allowed paths)",
    st_image_terms="no licence stated on exhibition pages; treat images as all rights reserved",
)]

BRANCH_HINTS = ("서울시립", "SeMA", "세마", "난지", "백남준을 기억하는 집", "서울")
ABROAD = {"캐나다": "CA", "워싱턴": "US", "뉴욕": "US", "로스앤젤레스": "US", "LA": "US", "영국": "GB", "프랑스": "FR",
          "독일": "DE", "일본": "JP", "오사카": "JP", "중국": "CN", "상하이": "CN", "홍콩": "HK", "호주": "AU",
          "스페인": "ES", "이탈리아": "IT", "벨기에": "BE", "브라질": "BR", "멕시코": "MX", "아르헨티나": "AR",
          "러시아": "RU", "인도": "IN", "싱가포르": "SG", "베트남": "VN", "태국": "TH", "인도네시아": "ID",
          "필리핀": "PH", "튀르키예": "TR", "터키": "TR", "아랍에미리트": "AE", "UAE": "AE", "헝가리": "HU",
          "폴란드": "PL", "카자흐스탄": "KZ", "우즈베키스탄": "UZ", "몽골": "MN", "나이지리아": "NG", "이집트": "EG",
          "남아공": "ZA", "아르헨": "AR"}
KR_CITIES = ("부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남",
             "경북", "경남", "제주", "수원", "천안")
IMG_BASIS = "SeMA exhibition image; no open licence stated on the page (all rights reserved by default)"


def venue_country(venue: str):
    """(city, country_code) from the venue string as printed on SeMA. Unknown -> (None, None)."""
    v = venue or ""
    if not v.strip(" ,"):
        return None, None
    if v.startswith("주") or "한국문화원" in v:
        for k, cc in ABROAD.items():
            if k in v:
                return None, cc
        return None, None
    if any(h in v for h in BRANCH_HINTS):
        return "Seoul", "KR"
    for k in KR_CITIES:
        if k in v:
            return None, "KR"
    return None, None


def collect(ctx):
    con = ctx.con
    org = db.ensure_entity(con, entity_type="institution", name="서울시립미술관", namespace=f"src:{ctx.source_id}",
                           id_value="sema", lang="ko", source_id=ctx.source_id, official_url=BASE)
    con.commit()
    today = now_kst().date()
    floor = "2025-01-01"
    whens = [("FROM_TODAY", 10), ("PLAN_DAY", 5), ("PAST_DAY", 40 if ctx.mode == "initial" else 1)]
    cards = {}
    for when, maxpage in whens:
        page = 1
        while page <= maxpage:
            params = dict(whatsonMenuDivList="EX", whatChoice2="N", whatChoice3="N", whatChoice4="N", whatChoice5="N",
                          whenType=when)
            if page > 1:
                params["currentPage"] = page
            r = ctx.fetch(LANDING, params=params)
            html = r.text
            items = _parse_listing(html)
            ctx.count("fetched", len(items))
            for it in items:
                it["resp"], it["page_url"] = r, r.url
                cards.setdefault(it["idx"], it)
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*페이지", soup(html).get_text(" "))
            total = int(m.group(2)) if m else 1
            if when == "PAST_DAY":
                starts = [it["start"] for it in items if it["start"]]
                if ctx.mode == "initial" and page == maxpage:
                    ctx.note(f"SeMA past listing: {total} pages exist; stopped at page {page}")
                if starts and max(starts) < floor:
                    ctx.note(f"SeMA past listing paginated to page {page}/{total} (reached {max(starts)})")
                    break
            if page >= total or not items:
                break
            page += 1
        con.commit()

    cutoff = (today - dt.timedelta(days=30)).isoformat()
    for idx, it in cards.items():
        if it["start"] and it["start"] < floor and (it["end"] or "") < floor:
            continue  # beyond collection window (listing-only cards from the last archive page)
        key = idx
        row = con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
        need_detail = it["menu"] == "EXM01" and (ctx.mode == "initial" or row is None or (row[0] or "9999") >= cutoff)
        if row is not None and ctx.mode == "incremental" and not need_detail:
            # unchanged closed event: refresh last_seen only via identical upsert below is not possible without
            # detail fields, so skip it entirely (it was stored by an earlier run).
            continue
        det, dresp = {}, None
        if need_detail:
            try:
                dresp = ctx.fetch(DETAIL, params={"exNo": idx})
                det = _parse_detail(dresp.text)
            except FetchError as e:
                ctx.note(f"detail {idx}: {e}")
                ctx.count("detail_errors")
        _store(ctx, org, it, det, dresp)
        con.commit()


def _parse_listing(html: str):
    s = soup(html)
    out = []
    for d in s.select("div.viewLink[data-idx]"):
        if d.get("data-whatson-menu-div") != "EX":
            continue
        t = d.select_one(".s_title")
        title = clean_text(t.get_text(" ")) if t else ""
        place = d.select_one(".epEcPlaceNm")
        venue = clean_text(place.get_text(" ")).strip(" ,") if place else ""
        txt = clean_text(d.get_text(" "))
        m = re.search(r"(\d{4}/\d{2}/\d{2})\s*~\s*(\d{4}/\d{2}/\d{2})", txt)
        date_text = m.group(0) if m else None
        start = end = None
        if m:
            start, _, end, _ = parse_date_range(m.group(0).replace("/", "-").replace("~", " ~ "))
        img = d.select_one("img[src]")
        out.append(dict(idx=str(d["data-idx"]), menu=d.get("data-ex-menu-div") or "", title=title, venue=venue,
                        date_text=date_text, start=start, end=end,
                        img=(BASE + img["src"]) if img and img["src"].startswith("/common/") else None))
    return out


def _parse_detail(html: str):
    s = soup(html)
    out = {}
    for lab in s.select("div.o_h1"):
        k = clean_text(lab.get_text(" "))
        p = lab.find_next_sibling()
        if p is None or p.name != "p" or k in out:
            continue
        out[k] = clean_text(p.get_text(" | "))
    return out


def _artists(raw: str):
    if not raw:
        return []
    raw = re.sub(r"\s*(외|등)\s*\d*\s*(명|인|팀)?\s*$", "", raw)
    names = []
    # split on separators outside parentheses so collectives like '깃발옆차기(성의석, 주한별)' stay one entry
    for part in re.split(r"\s*[,，、/|]\s*(?![^()]*\))", raw):
        part = clean_text(part).strip(" .")
        if not re.search(r"\([^)]*[,，][^)]*\)", part):
            part = re.sub(r"\s*\([^)]*\)$", "", part).strip()
        if 1 < len(part) <= 40 and not re.search(r"\d+\s*(명|인|팀)|작가\s*\d", part):
            names.append(part)
    return list(dict.fromkeys(names))


def _store(ctx, org, it, det, dresp):
    con = ctx.con
    title = it["title"]
    venue = it["venue"]
    if det.get("전시장소"):
        venue = venue or next((x.strip() for x in det["전시장소"].split("|") if x.strip()), "")
    city, cc = venue_country(venue or det.get("전시장소", ""))
    date_text = det.get("전시기간") or it["date_text"]
    start, sp, end, ep = (parse_date_range(date_text.replace("~", " ~ ")) if date_text else (None, None, None, None))
    if dresp is not None:
        url = dresp.url
        ev = ctx.evidence(dresp, locator=f"exhibition detail exNo={it['idx']}", excerpt=date_text)
    else:
        url = f"{it['page_url']}#dv_{it['idx']}"
        ev = ctx.evidence(it["resp"], locator=f"listing card dv_{it['idx']}", excerpt=date_text)
    artists = _artists(det.get("참여작가", ""))
    subtype = classify_subtype(title, len(artists) or None)
    if subtype == "unknown" and "개인전" in title:
        subtype = "solo"
    eid = db.upsert_event(
        con, ctx.stats, source_id=ctx.source_id, source_event_key=it["idx"], event_type="exhibition", subtype=subtype,
        title=title, title_lang="ko", organizer_entity_id=org, city=city, country_code=cc,
        start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
        url=url, parser_version=PARSER_VERSION, evidence_id=ev,
        description_excerpt=(f"venue: {venue}" if venue else None))
    ctx.count("parsed")
    if cc is None:
        db.add_review(con, "region", "events", eid, "venue country unknown", detail=venue or None)
    for name in artists:
        ent = db.ensure_entity(con, entity_type="person", name=name, namespace=f"src:{ctx.source_id}", lang="ko",
                               source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(con, eid, ent, "artist", name, ev, "structured_field")
    if it.get("img"):
        db.add_image_rights(con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=it["img"],
                            usage_status="unknown", basis=IMG_BASIS)
