"""Korean non-profit art centres, museums, biennials and fairs (one parser per source; branch on ctx.source_id).

Doosan Art Center (D27 / O09): only the 전시 (exhibition) section is read — 공연 (performing arts) and 교육 are
excluded by construction. Past shows are paginated by the site's own HTML fragment endpoint
`/ko/exhibit/ajax/past?currentPage=N` (plain GET, no key; the same request the "more" button makes).
"""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import classify_subtype, clean_text, parse_date_range, soup

PARSER_VERSION = "kr_institutions-1"
FLOOR = "2025-01-01"
DOOSAN = "https://www.doosanartcenter.com"
GB = "https://www.gwangjubiennale.org"
ASJ = "https://artsonje.org"

SOURCES = [
    dict(source_id="doosan_gallery", blueprint_data_id="D27", blueprint_org_id="O09",
         name="Doosan Art Center — 전시 (Doosan Gallery / Doosan Art Lab)", owner_group="Doosan Yonkang Foundation",
         source_kind="foundation", region_scope="KR", country_codes="KR", access_method="html", base_url=DOOSAN,
         entry_url=f"{DOOSAN}/ko/exhibit/main", terms_url=None, text_storage_policy="raw_internal", priority="P1",
         max_requests=60, st_official_doc="n/a(html)",
         st_collection_terms="terms page not located; robots.txt absent (404 => allow)",
         st_image_terms="no licence stated; treat as all rights reserved"),
    dict(source_id="gwangju_biennale", blueprint_data_id="D17", blueprint_org_id=None,
         name="Gwangju Biennale — current edition (main exhibition + participating artists)",
         owner_group="Gwangju Biennale Foundation", source_kind="biennial", region_scope="KR", country_codes="KR",
         access_method="html", base_url=GB, entry_url=f"{GB}/gb/exhibition/biennale/mainexhibition.do?subPage=overview",
         terms_url=f"{GB}/gb/member/terms.do", text_storage_policy="raw_internal", priority="P0", max_requests=20,
         st_official_doc="n/a(html; participating-artist tab is JS-rendered, artists read from the edition's official guide site youmustchangeyourlife.kr linked from the foundation site)",
         st_collection_terms="footer: 'COPYRIGHT (C) GWANGJU BIENNALE FOUNDATION. ALL RIGHTS RESERVED.' + 이메일 무단수집 거부; robots.txt allows all but /gb/newsCH/",
         st_image_terms="guide captions credit artists / (재)광주비엔날레 per image; no open licence"),
    dict(source_id="art_sonje", blueprint_data_id=None, blueprint_org_id=None, name="Art Sonje Center — 전시",
         owner_group="Art Sonje Center (Daewoo Foundation)", source_kind="museum", region_scope="KR", country_codes="KR",
         access_method="html", base_url=ASJ, entry_url=f"{ASJ}/exhibition-program/exhibition/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", max_requests=90, st_official_doc="n/a(html, WordPress/FacetWP)",
         st_collection_terms="terms page not located; footer '© Art Sonje Center. All Rights reserved.'; robots.txt (Yoast) allows all",
         st_image_terms="© Art Sonje Center. All Rights reserved.; captions credit designers/photographers"),
]


def collect(ctx):
    if ctx.source_id == "doosan_gallery":
        return _doosan(ctx)
    if ctx.source_id == "gwangju_biennale":
        return _gwangju(ctx)
    if ctx.source_id == "art_sonje":
        return _artsonje(ctx)
    raise ValueError(ctx.source_id)


def _today():
    return now_kst().date()


def _needs_detail(ctx, key):
    if ctx.mode == "initial":
        return True
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
    return row is None or not row[0] or row[0] >= (_today() - dt.timedelta(days=30)).isoformat()


def _org(ctx, etype, name, oid, url, lang="ko"):
    eid = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"src:{ctx.source_id}", id_value=oid,
                           lang=lang, source_id=ctx.source_id, official_url=url)
    ctx.con.commit()
    return eid


# -- Doosan ----------------------------------------------------------------------------------------
_PROGRAM_LABEL = re.compile(r"기획전|전시|워크숍|공모|두산|프로그램|퍼블릭|DCW")


def _doosan_cards(html):
    out = []
    for box in soup(html).select("div.list div.inner"):
        a = box.select_one("strong a[href*='/exhibit/']")
        m = re.search(r"/exhibit/(\d+)", a["href"]) if a else None
        if not m:
            continue
        em = box.select_one(".txt em")
        place = box.select_one(".place")
        venue = clean_text(place.span.get_text(" ")) if place and place.span else None
        if place and place.span:
            place.span.extract()
        out.append(dict(id=m.group(1), title=clean_text(a.get_text(" ")), label=clean_text(em.get_text(" ")) if em else "",
                        date=clean_text(place.get_text(" ")) if place else None, venue=venue))
    return out


def _doosan(ctx):
    org = _org(ctx, "foundation", "두산아트센터", "doosanartcenter", DOOSAN)
    cards = []
    r = ctx.fetch(f"{DOOSAN}/ko/exhibit/main")
    cards += _doosan_cards(r.text)
    r = ctx.fetch(f"{DOOSAN}/ko/exhibit/past")
    cards += _doosan_cards(r.text)
    page, maxpage = 2, (8 if ctx.mode == "initial" else 1)
    while page <= maxpage:
        r = ctx.fetch(f"{DOOSAN}/ko/exhibit/ajax/past", params={"currentPage": page})
        got = _doosan_cards(r.text)
        if not got:
            break
        cards += got
        starts = [parse_date_range(c["date"])[0] for c in got if c["date"]]
        if starts and max(s or "" for s in starts) < FLOOR:
            break
        page += 1
    ctx.note(f"Doosan exhibitions: main + past + ajax/past pages up to {page}; archive continues further back")
    seen = set()
    for c in cards:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        ctx.count("fetched")
        start = parse_date_range(c["date"])[0] if c["date"] else None
        if start and start < FLOOR:
            continue
        if not _needs_detail(ctx, c["id"]):
            continue
        url = f"{DOOSAN}/ko/exhibit/{c['id']}"
        try:
            dr = ctx.fetch(url)
        except FetchError as e:
            ctx.count("detail_errors")
            ctx.note(f"{url}: {e}")
            continue
        ds = soup(dr.text)
        names = []
        for strong in ds.find_all("strong", string=re.compile("참여작가")):
            sp = strong.find_next_sibling("span")
            if sp:
                names += [clean_text(a.get_text(" ")) for a in sp.find_all("a") if clean_text(a.get_text(" "))]
        method = "list_markup"
        if not names and c["label"] and not _PROGRAM_LABEL.search(c["label"]):
            toks = c["label"].split()
            names = toks if all(re.fullmatch(r"[가-힣]{2,4}", t) for t in toks) and len(toks) > 1 else [c["label"]]
            method = "list_markup"
        place_m = re.search(r"장소\s*[:：]\s*([^\n]+)", ds.get_text("\n"))
        place = clean_text(place_m.group(1)) if place_m else (c["venue"] or "")
        if "뉴욕" in place or "New York" in place:
            city, cc = "New York", "US"
        elif "서울" in place or "두산갤러리" in place or "두산아트센터" in place:
            city, cc = "Seoul", "KR"
        else:
            city, cc = None, None
        ev = ctx.evidence(dr, locator=f"exhibit {c['id']}", excerpt=c["date"])
        start, sp, end, ep = parse_date_range(c["date"]) if c["date"] else (None, None, None, None)
        title = c["title"]
        eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=c["id"], event_type="exhibition",
                              subtype=classify_subtype(title, len(names) or None), title=title, title_lang="ko",
                              organizer_entity_id=org, city=city, country_code=cc, start_date=start, start_precision=sp,
                              end_date=end, end_precision=ep, date_text=c["date"], url=url, parser_version=PARSER_VERSION,
                              evidence_id=ev, description_excerpt=f"venue: {place}" + (f"; program: {c['label']}" if c["label"] and _PROGRAM_LABEL.search(c["label"]) else ""))
        ctx.count("parsed")
        if cc is None:
            db.add_review(ctx.con, "region", "events", eid, "venue country unknown", detail=place or None)
        for n in names:
            role = "artist"
            cm = re.match(r"^(?:공동)?기획\s*[:：]\s*(.+)$", n)
            if cm:  # '공동기획: 박수정' inside the artist list is a curator credit
                role, n = "curator", cm.group(1).strip()
            ent = db.ensure_entity(ctx.con, entity_type="person", name=n, namespace=f"src:{ctx.source_id}", lang="ko",
                                   source_id=ctx.source_id, evidence_id=ev)
            db.add_participant(ctx.con, eid, ent, role, n, ev, method, "high")
        ctx.con.commit()


# -- Gwangju Biennale --------------------------------------------------------------------------------
GB_GUIDE = "https://youmustchangeyourlife.kr/"


def _gwangju(ctx):
    """Latest edition only. Overview page: title + dates; planner page: artistic director (curator role);
    participating artists: the edition guide (one <article class="project"> per artist/collective)."""
    org = _org(ctx, "biennial", "광주비엔날레", "gwangju_biennale", GB)
    r = ctx.fetch(f"{GB}/gb/exhibition/biennale/mainexhibition.do", params={"subPage": "overview"})
    s = soup(r.text)
    box = s.select_one(".ctt_box")
    title = clean_text(box.h3.get_text(" ")) if box and box.h3 else None
    date_text = clean_text(box.select_one("p.date").get_text(" ")) if box and box.select_one("p.date") else None
    m = re.search(r"제\s*(\d+)\s*회\s*광주비엔날레", s.get_text(" "))
    if not title or not m:
        ctx.note("overview page layout changed: no edition title/number found")
        return
    edition = m.group(1)
    ev = ctx.evidence(r, locator="main exhibition overview .ctt_box", excerpt=date_text)
    start, sp, end, ep = parse_date_range(date_text) if date_text else (None, None, None, None)
    ctx.count("fetched")
    eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=f"edition-{edition}",
                          event_type="biennial_edition", subtype=None, title=f"제{edition}회 광주비엔날레 {title}",
                          title_lang="ko", organizer_entity_id=org, city="Gwangju", country_code="KR",
                          start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
                          url=r.url, parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    ctx.con.commit()
    pr = ctx.fetch(f"{GB}/gb/exhibition/biennale/mainexhibition.do", params={"subPage": "planner"})
    pev = ctx.evidence(pr, locator="planner page h3 예술감독")
    for h3 in soup(pr.text).select("h3"):
        t = clean_text(h3.get_text(" "))
        if t.startswith("예술감독") and h3.span:
            name = clean_text(h3.span.get_text(" "))
            ent = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=pev)
            db.add_participant(ctx.con, eid, ent, "curator", name, pev, "list_markup")
    ctx.con.commit()
    gr = ctx.fetch(GB_GUIDE)
    gev = ctx.evidence(gr, locator="edition guide article.project", excerpt=title)
    gs = soup(gr.text)
    seen = set()
    for art in gs.select("article.project"):
        origin = art.select_one(".artist-origin")
        if origin is None or not clean_text(origin.get_text(" ")):
            continue  # object/specimen entries (e.g. 'Volcanoes of Jeju') carry no artist origin line
        en = art.select_one(".project-title .title[lang=en]")
        ko = art.select_one(".project-title .title[lang=ko]")
        if en is None:
            continue
        en_name = clean_text(en.get_text(" "))
        if en_name in seen:
            continue  # several works by one artist -> one participant
        seen.add(en_name)
        parts = [clean_text(x.get_text(" ")) for x in en.select(".nowrap")] or [en_name]
        if " and " not in en_name:
            parts = [en_name]  # single person or collective: keep the full listed name
        ko_name = clean_text(ko.get_text(" ")) if ko else None
        for nm in parts:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=nm, namespace=f"src:{ctx.source_id}", lang="en",
                                   source_id=ctx.source_id, evidence_id=gev,
                                   nationality_text=clean_text(origin.select_one("[lang=en]").get_text(" ")) if origin.select_one("[lang=en]") else None)
            if ko_name and len(parts) == 1:
                db.add_alias(ctx.con, ent, ko_name, "ko", "name", "", ctx.source_id, gev)
            db.add_participant(ctx.con, eid, ent, "artist", nm, gev, "list_markup")
    ctx.count("artists", len(seen))
    ctx.note(f"Gwangju Biennale: edition {edition} only; {len(seen)} artist entries from the edition guide; "
             "past editions (/gb/exhibition/past/N.do) not parsed")
    ctx.con.commit()


# -- Art Sonje Center --------------------------------------------------------------------------------
_ASJ_DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*[–~\-]\s*(?:(\d{4})\.\s*)?(\d{1,2})\.\s*(\d{1,2})")


def asj_dates(text):
    m = _ASJ_DATE.search(text or "")
    if not m:
        return parse_date_range(text)
    y1, m1, d1, y2, m2, d2 = m.groups()
    y2 = y2 or (str(int(y1) + 1) if int(m2) < int(m1) else y1)
    try:
        return (dt.date(int(y1), int(m1), int(d1)).isoformat(), "day", dt.date(int(y2), int(m2), int(d2)).isoformat(), "day")
    except ValueError:
        return None, None, None, None


def _artsonje(ctx):
    """Listing (FacetWP, 12 cards/page, ?_paged=N) has titles only; dates/venue/artists/curators come from the
    detail page's 기간 / 장소 / 참여작가 / 기획 fields."""
    org = _org(ctx, "institution", "아트선재센터", "artsonje", ASJ)
    maxpage = 8 if ctx.mode == "initial" else 1
    page, last_page = 1, None
    while page <= maxpage:
        r = ctx.fetch(f"{ASJ}/exhibition-program/exhibition/", params={"_paged": page} if page > 1 else None)
        if last_page is None:
            pm = re.findall(r'data-page=\\?"(\d+)\\?"', r.text)
            last_page = max(map(int, pm)) if pm else 1
        cards = []
        for res in soup(r.text).select(".facetwp-template .fwpl-result"):
            a = res.select_one("a[href*='/exhibition/']")
            if a:
                cards.append(a["href"])
        ctx.count("fetched", len(cards))
        starts = []
        for url in dict.fromkeys(cards):
            key = re.sub(r"^https?://[^/]+", "", url).strip("/")
            if not _needs_detail(ctx, key):
                continue
            try:
                dr = ctx.fetch(url)
            except FetchError as e:
                ctx.count("detail_errors")
                ctx.note(f"{url}: {e}")
                continue
            st = _artsonje_detail(ctx, org, key, dr)
            if st:
                starts.append(st)
        if page >= last_page or (starts and max(starts) < FLOOR):
            break
        page += 1
    ctx.note(f"Art Sonje listing: {last_page} pages exist; read {page}")


def _artsonje_detail(ctx, org, key, dr):
    ds = soup(dr.text)
    terms = {}
    for t in ds.select(".myTerm"):
        lab, val = t.select_one(".termLabel"), t.select_one(".termValue")
        if lab and val:
            terms.setdefault(clean_text(lab.get_text(" ")), val)
    tn = ds.select_one("p.title-name")
    title = clean_text(tn.get_text(" ")) if tn else None
    if not title:
        ctx.count("detail_errors")
        return None
    date_el = terms.get("기간") or ds.select_one("p.title-time")
    date_text = clean_text(date_el.get_text(" ")) if date_el else None
    place_el = terms.get("장소") or ds.select_one("p.title-place")
    place = clean_text(place_el.get_text(" ")) if place_el else ""
    start, sp, end, ep = asj_dates(date_text) if date_text else (None, None, None, None)
    if "아트선재" in place or "Art Sonje" in place:
        city, cc = "Seoul", "KR"
    else:
        city, cc = None, None
    def names(label):
        el = terms.get(label)
        if el is None:
            return []
        raw = clean_text(el.get_text(", "))
        out = []
        for part in re.split(r"\s*[,，、]\s*(?![^()]*\))", raw):
            part = re.sub(r"\s*(외|등)\s*\d*\s*(명|인|팀)?$", "", part.strip())
            if 1 < len(part) <= 60:
                out.append(part)
        return list(dict.fromkeys(out))
    artists = names("참여작가")
    method = "structured_field"
    if not artists:
        from ._common import split_title_artist
        guess = split_title_artist(title)
        if guess:
            artists, method = [guess], "title_pattern"
    curators = [re.sub(r"\s*\([^)]*\)$", "", c) for c in names("기획")]
    url = dr.url
    ev = ctx.evidence(dr, locator="detail .myTerm 기간/장소/참여작가/기획", excerpt=date_text)
    eid = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
                          subtype=classify_subtype(title, len(artists) or None), title=title, title_lang="ko",
                          organizer_entity_id=org, city=city, country_code=cc, start_date=start, start_precision=sp,
                          end_date=end, end_precision=ep, date_text=date_text, url=url, parser_version=PARSER_VERSION,
                          evidence_id=ev, description_excerpt=f"venue: {place}" if place else None)
    ctx.count("parsed")
    if cc is None:
        db.add_review(ctx.con, "region", "events", eid, "venue country unknown", detail=place or None)
    for role, lst in (("artist", artists), ("curator", curators)):
        for n in lst:
            ent = db.ensure_entity(ctx.con, entity_type="person", name=n, namespace=f"src:{ctx.source_id}", lang="ko",
                                   source_id=ctx.source_id, evidence_id=ev)
            m_ = method if role == "artist" else "structured_field"
            db.add_participant(ctx.con, eid, ent, role, n, ev, m_, "medium" if m_ == "title_pattern" else "high")
    ctx.con.commit()
    return start
