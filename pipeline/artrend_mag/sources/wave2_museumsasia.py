"""Wave-2 Korean/Japanese museum listings (sourcebook 일본-03-003/004/005/009/012, 한국-03-003..009).

One module, one parser per site. Every parser was written against markup observed on 2026-10-28 through the
project Fetcher (robots honoured, >=3 s/host). Only public listing/detail HTML is read; no images, PDFs, article
bodies or POST-only forms. Korean/Japanese originals are stored verbatim (title_lang ko/ja).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from urllib.parse import urljoin

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import clean_text, parse_date_range, soup

PARSER_VERSION = "wave2_museumsasia-1"
HISTORY_FLOOR = "2023-01-01"

_NO_AUTOMATION = "no automated-access clause located"


def _row(source_id, name, owner, region, country, base, entry, terms_url, collection_terms, image_terms, notes,
         max_requests=200, **extra):
    row = dict(source_id=source_id, blueprint_data_id=None, blueprint_org_id=None, name=name, owner_group=owner,
               source_kind="museum", region_scope=region, country_codes=country, access_method="html",
               base_url=base, entry_url=entry, terms_url=terms_url, text_storage_policy="raw_internal",
               priority="P2", st_official_doc="n/a(public HTML listings)", st_collection_terms=collection_terms,
               st_image_terms=image_terms, notes=notes, max_requests=max_requests)
    row.update(extra)
    return row


NMWA = "https://www.nmwa.go.jp"
MOMAK = "https://www.momak.go.jp"
NMAO = "https://www.nmao.go.jp"
YOKOBI = "https://yokohama.art.museum"
BENESSE = "https://benesse-artsite.jp"
BUSAN = "https://art.busan.go.kr"
DAEGU = "https://daeguartmuseum.or.kr"
GMOMA = "https://gmoma.ggcf.kr"
NJP = "https://njp.ggcf.kr"

SOURCES = [
    _row("wave2_nmwa_exhibitions", "国立西洋美術館 — 展覧会 (current/upcoming/past)", "国立西洋美術館 (NMWA)", "JP", "JP",
         NMWA, f"{NMWA}/jp/exhibitions/current.html", f"{NMWA}/jp/information/privacy.html",
         "robots.txt parsed (Disallow /qrcode/ and /wp-admin/ only; checked 2026-10-28). Site policy (プライバシーポリシー・"
         "サイトポリシー page) reserves copyright of text/images to the museum or right holders and asks that content not be used "
         "beyond private/educational use without permission; no automated-access clause. Event metadata + internal evidence only.",
         "Poster thumbnails visible in listings are not downloaded; museum/right-holder copyright, image use needs permission.",
         "Sourcebook 일본-03-003. Listing-level collection (title, subtitle, category badge, displayed period). Past list = "
         "decade 2020- page filtered to 2023+; no curator/artist fields exposed on listings (detail pages not fetched)."),
    _row("wave2_momak_exhibitions", "京都国立近代美術館 — 展覧会・コレクション展", "京都国立近代美術館 (MoMAK)", "JP", "JP",
         MOMAK, f"{MOMAK}/Japanese/exhibitionArchive/", f"{MOMAK}/Japanese/sitepolicy.html",
         "No robots.txt file (HTML fallback returned; fetcher treats as allow; checked 2026-10-28). サイトポリシー §3: intellectual "
         "property of text/images belongs to the museum and information providers; reproduction/reuse beyond private use or "
         "quotation is not permitted without permission; no automated-access clause. Metadata + internal evidence only.",
         "Flyer images visible in listings are not downloaded; museum/provider copyright (画像利用申請 page exists).",
         "Sourcebook 일본-03-004. Current/upcoming blocks, per-fiscal-year past exhibitions and collection-gallery lists; "
         "current items use the detail page 会期 line. Curatorial Studies archive not collected (no dates on its list)."),
    _row("wave2_nmao_exhibitions", "国立国際美術館 — 開催中・今後・過去の展覧会", "国立国際美術館 (NMAO)", "JP", "JP",
         NMAO, f"{NMAO}/exhibition/current_exhibition/", f"{NMAO}/sitepolicy/",
         "robots.txt parsed (Disallow /wp-admin/ only; checked 2026-10-28). サイトポリシー: copyright in all text/images belongs to "
         "the museum and providers; use beyond private use prohibited; links to the top page encouraged; no automated-access clause. "
         "Metadata + internal evidence only.",
         "Poster images not downloaded; copyright reserved by museum/providers.",
         "Sourcebook 일본-03-005. Current/upcoming list plus the single past-exhibition table (fiscal years back to 1977; "
         "filtered to 2023+). Listing-level fields only; artists are not inferred from titles."),
    _row("wave2_yokohama_museum_exhibitions", "横浜美術館 — 開催中・これまでの展覧会", "横浜美術館 (横浜市芸術文化振興財団)", "JP", "JP",
         YOKOBI, f"{YOKOBI}/exhibition/", f"{YOKOBI}/sitepolicy/",
         "robots.txt parsed (User-agent * with empty Disallow; checked 2026-10-28). サイトポリシー §1: text/images/materials are "
         "for on-screen viewing by individuals; republication in other media and use beyond private use is not allowed; no "
         "automated-access clause. Metadata + internal evidence only.",
         "Images not downloaded; copyright held by museum, photographers and artists.",
         "Sourcebook 일본-03-009. The museum's own exhibitions only (its 'その他の展覧会等' label is stored as the site category, "
         "not reclassified; Yokohama Triennale is a separate source). Past page covers 1989+, filtered to 2023+."),
    _row("wave2_benesse_artsite_news", "ベネッセアートサイト直島 — ニュース/お知らせ", "ベネッセアートサイト直島 (Benesse Holdings / 福武財団)", "JP", "JP",
         BENESSE, f"{BENESSE}/news/", "https://www.benesse.co.jp/about/utility/term.html",
         "robots.txt parsed (Disallow /mt/ only; checked 2026-10-28). Benesse corporate 'サイトのご利用にあたって' (linked from "
         "the art-site footer): content for private use; reproduction/transmission/distribution beyond the Copyright Act needs "
         "prior written consent; no automated-access clause. Announcement metadata only, no body text.",
         "No images collected; Benesse/artist rights apply.",
         "Sourcebook 일본-03-012. Announcement index (title, displayed date, island/category labels) per year 2023-2026; "
         "NOT an exhibition archive — items whose titles carry dates are not converted into events."),
    _row("wave2_busan_moa_exhibitions", "부산시립미술관 — 현재/예정/과거 전시", "부산시립미술관 (Busan Museum of Art)", "KR", "KR,CN",
         BUSAN, f"{BUSAN}/tblTsite07Display/listNowClient.nm", f"{BUSAN}/index.nm?menuCd=43",
         "robots.txt parsed (Disallow /uploadfiles/, /mng/, /cms/ ...; checked 2026-10-28). 저작권안내: museum-held works may be "
         "used free of separate permission under Copyright Act §24-2 but not commercially; third-party/co-owned material "
         "excluded; no automated-access clause. Metadata + internal evidence only.",
         "Images under /uploadfiles/ are robots-disallowed and never fetched; museum copyright guidance applies.",
         "Sourcebook 한국-03-003. Country from the detail page 전시부문/전시장소 (overseas shows keep their actual venue country). "
         "Past list = 53 pages, paged until a whole page ends before 2023 (initial)."),
    _row("wave2_busan_moca", "부산현대미술관 — 전시", "부산현대미술관 (Busan Museum of Contemporary Art)", "KR", "KR",
         "https://www.busan.go.kr", "https://www.busan.go.kr/moca/", None, "not reviewed (site unreachable to the crawler)",
         "not reviewed", "Sourcebook 한국-03-004. disabled: robots fetch fails (ConnectionError) and direct GET returns HTTP 401; "
         "no bypass attempted.",
         max_requests=50, disabled="robots.txt unreachable (ConnectionError -> fetcher refuses) and /moca/ returns HTTP 401 (checked 2026-10-28)",
         operational_state="blocked_access", robots_status="robots_error(ConnectionError)", st_live_response="blocked(HTTP 401)"),
    _row("wave2_daegu_art_museum", "대구미술관 — 현재/예정/지난전시", "대구미술관 (Daegu Art Museum)", "KR", "KR",
         DAEGU, f"{DAEGU}/index.do?menu_id=00000729", f"{DAEGU}/index.do?menu_id=00000821",
         "No robots.txt (404 -> allow; checked 2026-10-28). 이용약관 covers membership/board conduct and states nothing on automated "
         "collection or reuse of exhibition data. Detail pages are POST-only forms and are NOT fetched; listing GET pages only.",
         "Posters (/icms/file/getImage.do) not downloaded; no licence stated.",
         "Sourcebook 한국-03-005. List-level fields only (title, period, 장소, 진행중/예정/지난전시 status); url is the listing page "
         "with the EHI id as fragment because the detail view needs a POST."),
    _row("wave2_gwangju_museum_of_art", "광주시립미술관 — 전시", "광주시립미술관 (Gwangju Museum of Art)", "KR", "KR",
         "https://artmuse.gwangju.go.kr", "https://artmuse.gwangju.go.kr/", None, "not reviewed (WAF blocks non-browser clients)",
         "not reviewed", "Sourcebook 한국-03-006. disabled: robots.txt and the site return an HTTP 400 'Request Blocked' page to "
         "the identified client; no bypass attempted.",
         max_requests=50, disabled="robots.txt/site return HTTP 400 'Request Blocked' to the identified fetcher (checked 2026-10-28)",
         operational_state="blocked_access", robots_status="robots_http_400(not_crawled)", st_live_response="blocked(HTTP 400)"),
    _row("wave2_gmoma_exhibitions", "경기도미술관 — 전시 (현재/예정/과거)", "경기문화재단 경기도미술관 (Gyeonggi Museum of Modern Art)", "KR", "KR",
         GMOMA, f"{GMOMA}/exhibitions", f"{GMOMA}/exhibitions/207",
         "robots.txt parsed (Disallow /attachment/, /storage/upload/, /wp-content/uploads/; checked 2026-10-28). Site terms of "
         "service §17: service copyright/IP belongs to the foundation; no automated-access clause. Metadata + internal evidence.",
         "Images under /storage/upload/ are robots-disallowed and never fetched; copyright reserved by the foundation.",
         "Sourcebook 한국-03-007. Detail pages expose schema.org dates and 장소/참여작가/기획/주최·주관 definition lists. "
         "Past list uses the page's own 더보기 link (/exhibitions/more?progress=ago&page=N, HTML fragment, no key)."),
    _row("wave2_njp_exhibitions", "백남준아트센터 — 전시 (현재/예정/지난)", "경기문화재단 백남준아트센터 (Nam June Paik Art Center)", "KR", "KR",
         NJP, f"{NJP}/exhibitions", f"{NJP}/exhibitions/244",
         "robots.txt parsed (Disallow /attachment/, /storage/upload/, /wp-content/uploads/; checked 2026-10-28). Same Gyeonggi "
         "Cultural Foundation CMS and terms as gmoma (§17 IP to the foundation); no automated-access clause. Metadata only.",
         "Images under /storage/upload/ are robots-disallowed and never fetched.",
         "Sourcebook 한국-03-008. Current/upcoming on /exhibitions, past years via the page's own year dropdown "
         "(/exhibitions/more?year=YYYY, 2023-2026); detail pages give 장소/기획/참여작가/주최주관."),
    _row("wave2_acc_exhibitions", "국립아시아문화전당 (ACC) — 전시", "국립아시아문화전당 (Asia Culture Center)", "KR", "KR",
         "https://www.acc.go.kr", "https://www.acc.go.kr/", None, "not reviewed (robots disallows)", "not reviewed",
         "Sourcebook 한국-03-009. disabled: robots.txt is 'User-agent: * / Disallow: /' (named search-engine bots only are allowed).",
         max_requests=50, disabled="robots.txt Disallow: / for User-agent * (checked 2026-10-28)",
         operational_state="blocked_permission", robots_status="parsed(Disallow: / for *)", st_live_response="not requested"),
]


# ---------------------------------------------------------------------------------------------------- helpers
_BRACKET = re.compile(r"[\(（\[［][^\)）\]］]{1,8}[\)）\]］]")


def parse_range(text):
    """(start, start_precision, end, end_precision) from a displayed period. Never invents a day; an end date
    without a year inherits the start year (+1 when it would otherwise precede the start)."""
    if not text:
        return None, None, None, None
    t = _BRACKET.sub("", unicodedata.normalize("NFKC", text))  # NMAO prints 月/日 as CJK-radical lookalikes
    t = re.sub(r"(\d)\.\s+(?=\d)", r"\1.", t)
    start, sp, end, ep = parse_date_range(t)
    if start and end and sp == ep == "day" and end < start and len(set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", t))) == 1:
        bumped = f"{int(end[:4]) + 1}{end[4:]}"
        if bumped >= start:
            end = bumped
    if start and not end:
        m = re.search(r"((?:19|20)\d{2})年\s*(\d{1,2})月\s*(?:上旬|中旬|下旬)", t)
        if m and f"{int(m.group(1)):04d}-{int(m.group(2)):02d}" >= start[:7]:
            end, ep = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", "month"
    if end and end[:4] >= "2099":  # CMS "no end" sentinel
        end = ep = None
    return start, sp, end, ep


def _lines(node):
    for br in node.find_all("br"):
        br.replace_with("\n")
    return [clean_text(x) for x in node.get_text().split("\n") if clean_text(x)]


def _slug(url):
    return [p for p in url.split("?")[0].split("/") if p][-1].rsplit(".", 1)[0]


def _in_scope(ctx, start, end, today):
    if end is None:  # open-ended / unparsed period: treat as ongoing rather than guess a close date
        return True
    ref = end
    if ctx.mode == "initial":
        return ref[:4] >= HISTORY_FLOOR[:4]
    cutoff = (today - dt.timedelta(days=30)).isoformat()
    return ref >= cutoff[:len(ref)]


def _cap(ctx):
    return ctx.stats.get("http_requests", 0) >= ctx.meta.get("max_requests", 200)


def _org(ctx, name, slug, url, lang):
    eid = db.ensure_entity(ctx.con, entity_type="institution", name=name, namespace=f"src:{ctx.source_id}",
                           id_value=slug, lang=lang, source_id=ctx.source_id, official_url=url)
    ctx.con.commit()
    return eid


def _subtype(title, label=None):
    text = f"{title or ''} {label or ''}"
    if any(k in text for k in ("コレクション", "常設", "所蔵", "소장품", "상설")):
        return "collection_display"
    return "unknown"


def _store_event(ctx, org, response, *, key, title, lang, date_text, url, locator, city, country, subtype="unknown",
                 excerpt=None, status=None, image=None, review_detail=None):
    start, sp, end, ep = parse_range(date_text)
    evidence = ctx.evidence(response, locator=locator, excerpt=date_text or title)
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition", subtype=subtype,
        title=title, title_lang=lang, organizer_entity_id=org, city=city, country_code=country,
        start_date=start, start_precision=sp, end_date=end, end_precision=ep, date_text=date_text,
        announced_status=status, url=url, description_excerpt=excerpt, evidence_id=evidence,
        parser_version=PARSER_VERSION)
    if country is None:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=review_detail)
    if image:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown", basis=ctx.meta.get("st_image_terms"),
                            page_url=url, image_url=image, event_id=event_id)
    ctx.count("parsed")
    return event_id, start, end


def _fetch_or_note(ctx, url, what, **kw):
    try:
        return ctx.fetch(url, **kw)
    except FetchError as error:
        ctx.count("detail_errors")
        ctx.note(f"{what}: {error}")
        return None


def _needs_detail(ctx, key, today):
    if ctx.mode == "initial":
        return True
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
    cutoff = (today - dt.timedelta(days=30)).isoformat()
    return row is None or not row[0] or row[0] >= cutoff[:len(row[0])]


# ---------------------------------------------------------------------------------------------------- NMWA (JP)
def parse_nmwa(html, base):
    page = soup(html)
    items = []
    for li in page.select("li[data-nmwa-exhibition-item], li[data-nmwa-row-card]"):
        link = next((a for a in li.select("a[href]") if "/exhibitions/" in a["href"] and a["href"].endswith(".html")
                     and "exhibit.jp" not in a["href"]), None)
        title_node, term = li.select_one(".nmwa-ui-card-title"), li.select_one(".nmwa-ui-card-term")
        if link is None or title_node is None:
            continue
        sub, cat = li.select_one(".nmwa-ui-card-sub"), li.select_one(".nmwa-ui-badge.is-category")
        image = li.select_one("img[src]")
        url = urljoin(base, link["href"])
        items.append(dict(key=_slug(url), url=url, title=clean_text(title_node.get_text(" ")),
                          sub=clean_text(sub.get_text(" ")) if sub else None,
                          category=clean_text(cat.get_text(" ")) if cat else None,
                          term=clean_text(term.get_text(" ")) if term else None,
                          upcoming=li.select_one(".nmwa-ui-badge.is-next") is not None,
                          image=urljoin(base, image["src"]) if image and "noimage" not in image["src"] else None))
    return items


def _collect_nmwa(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "国立西洋美術館", "nmwa", NMWA + "/", "ja"), set()
    pages = [f"{NMWA}/jp/exhibitions/current.html", f"{NMWA}/jp/exhibitions/upcoming.html",
             f"{NMWA}/jp/exhibitions/past/index.html"]
    for url in pages:
        response = ctx.fetch(url)
        items = parse_nmwa(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            if item["key"] in seen:
                continue
            start, _, end, _ = parse_range(item["term"])
            if not _in_scope(ctx, start, end, today):
                continue
            seen.add(item["key"])
            excerpt = "; ".join(x for x in (f"区分: {item['category']}" if item["category"] else None,
                                            f"副題: {item['sub']}" if item["sub"] else None) if x) or None
            _store_event(ctx, org, response, key=item["key"], title=item["title"], lang="ja", date_text=item["term"],
                         url=item["url"], locator="li[data-nmwa-exhibition-item] / .nmwa-exhibition-row",
                         city="Tokyo", country="JP", subtype=_subtype(item["title"], item["category"]), excerpt=excerpt,
                         status="scheduled" if item["upcoming"] else None, image=item["image"])
        ctx.con.commit()
    ctx.note("NMWA: current + upcoming + past decade-2020 page (listing shows 2020 onward; stored from 2023 in initial). "
             "Permanent-display ('常設展') cards are stored as collection_display; detail pages and artist/curator fields not fetched.")


# ---------------------------------------------------------------------------------------------------- MoMAK (JP)
def parse_momak_current(html, base):
    page = soup(html)
    out = []
    for section in page.select("section.layout-2col-01"):
        heading = section.find_previous("h2")
        h3, em, link = section.select_one("h3"), section.select_one("em"), section.select_one("a.btn-default")
        if h3 is None or link is None:
            continue
        out.append(dict(title=clean_text(h3.get_text(" ")), date_text=clean_text(em.get_text(" ")) if em else None,
                        url=urljoin(base, link["href"]), upcoming=bool(heading and "これから" in heading.get_text()),
                        collection=bool(page.select_one("main#sigCollectionGallery"))))
    return out


def parse_momak_year(html, base):
    out = []
    for section in soup(html).select("div.content section"):
        no, name, date = section.select_one(".no"), section.select_one(".name a"), section.select_one(".date")
        if no is None or name is None:
            continue
        lines = _lines(name)
        number = re.search(r"\d+", no.get_text())
        if not lines or not number:
            continue
        out.append(dict(key=f"no-{number.group(0)}", title=lines[-1], prefix=" ".join(lines[:-1]) or None,
                        date_text=clean_text(date.get_text(" ")) if date else None, url=urljoin(base, name["href"])))
    return out


def parse_momak_collection_past(html, base):
    out = []
    for p in soup(html).select(".list-type-01 p"):
        link, period = p.select_one("a"), p.select_one("span.period")
        if link is None or period is None:
            continue
        out.append(dict(title=clean_text(link.get_text(" ")), date_text=clean_text(period.get_text(" ")),
                        url=urljoin(base, link["href"])))
    return out


def parse_momak_detail(html):
    page = soup(html)
    canonical = page.select_one('link[rel="canonical"]')
    href = canonical["href"] if canonical else None
    number = re.search(r"/exhibitionarchive/\d{4}/(\d+)\.html", href or "", re.I)
    text = clean_text(page.get_text(" "))
    period = re.search(r"会期\s*((?:19|20)\d{2}年\s*\d{1,2}月\s*\d{1,2}日[^～〜~]{0,12}[～〜~]\s*(?:(?:19|20)\d{2}年\s*)?\d{1,2}月\s*\d{1,2}日)", text)
    return dict(number=number.group(1) if number else None, canonical=href,
                date_text=clean_text(period.group(1)) if period else None)


def _collect_momak(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "京都国立近代美術館", "momak", MOMAK + "/Japanese/", "ja"), set()
    years = [today.year, today.year - 1, today.year - 2, today.year - 3] if ctx.mode == "initial" else [today.year]
    # --- current/upcoming exhibitions and collection galleries (detail pages give 会期 and the stable number)
    for url, collection in ((f"{MOMAK}/Japanese/exhibitionArchive/", False), (f"{MOMAK}/Japanese/collectionGalleryArchive/", True)):
        response = ctx.fetch(url)
        items = parse_momak_current(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            detail = _fetch_or_note(ctx, item["url"], f"momak {item['url']}")
            info = parse_momak_detail(detail.text) if detail else {}
            date_text = info.get("date_text") or item["date_text"]
            if item["date_text"] and not info.get("date_text") and re.match(r"\d{4}\.\d", item["date_text"]):
                date_text = re.sub(r"\s*(mon|tue|wed|thu|fri|sat|sun)\.", "", item["date_text"], flags=re.I)
            key = f"cg-{item['title']}" if collection else (f"no-{info['number']}" if info.get("number")
                                                            else f"p-{item['url'].rsplit('=', 1)[-1]}")
            if key in seen:
                continue
            seen.add(key)
            _store_event(ctx, org, detail or response, key=key, title=item["title"], lang="ja", date_text=date_text,
                         url=(info.get("canonical") or item["url"]), locator="main section.layout-2col-01 / 詳細 会期",
                         city="Kyoto", country="JP", subtype="collection_display" if collection else "unknown",
                         status="scheduled" if item["upcoming"] else None)
        ctx.con.commit()
    # --- past: per-fiscal-year exhibition archive + collection-gallery archive
    for year in years:
        if _cap(ctx):
            ctx.note("MoMAK: request budget reached before all archive years were read")
            break
        response = ctx.fetch(f"{MOMAK}/Japanese/exhibitionArchive/{year}/")
        items = parse_momak_year(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            start, _, end, _ = parse_range(item["date_text"])
            if item["key"] in seen or not _in_scope(ctx, start, end, today):
                continue
            seen.add(item["key"])
            _store_event(ctx, org, response, key=item["key"], title=item["title"], lang="ja", date_text=item["date_text"],
                         url=item["url"], locator="#scPastExhibitions .content section", city="Kyoto", country="JP",
                         excerpt=f"冠: {item['prefix']}" if item["prefix"] else None)
        ctx.con.commit()
        response = ctx.fetch(f"{MOMAK}/Japanese/collectionGalleryArchive/", params={"sy": year})
        items = parse_momak_collection_past(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            start, _, end, _ = parse_range(item["date_text"])
            key = f"cg-{item['title']}"
            if key in seen or not _in_scope(ctx, start, end, today):
                continue
            seen.add(key)
            _store_event(ctx, org, response, key=key, title=item["title"], lang="ja", date_text=item["date_text"],
                         url=item["url"], locator="#scPastExhibitions .list-type-01 p", city="Kyoto", country="JP",
                         subtype="collection_display")
        ctx.con.commit()
    ctx.note(f"MoMAK: current/upcoming + fiscal-year archives {years[-1]}-{years[0]} (archive index links back to 1998 "
             "exhibitions and 2006 collection galleries); curatorial-studies list has no dates and is not collected.")


# ---------------------------------------------------------------------------------------------------- NMAO (JP)
def parse_nmao_current(html, base):
    out = []
    for card in soup(html).select(".ex_poster"):
        link = card.select_one("h2 a")
        if link is None:
            continue
        lines = _lines(link)
        paragraphs = [p for p in card.select(".txts p")]
        date = next((clean_text(p.get_text(" ")) for p in paragraphs if "pt5" not in (p.get("class") or [])), None)
        venue = next((clean_text(p.get_text(" ")) for p in paragraphs if "pt5" in (p.get("class") or [])), None)
        status, floor = card.select_one(".status"), card.select_one(".floor")
        url = urljoin(base, link["href"])
        out.append(dict(key=_slug(url), url=url, title=lines[-1] if lines else "", prefix=" ".join(lines[:-1]) or None,
                        date_text=date, venue=venue.replace("会場：", "").strip() if venue else None,
                        category=clean_text(floor.get_text(" ")) if floor else None,
                        upcoming=bool(status and "開催予定" in status.get_text())))
    return [x for x in out if x["title"]]


def parse_nmao_past(html, base):
    out = []
    for row in soup(html).select("table.extbl tr"):
        cells = row.select("td")
        link = cells[0].select_one("a") if cells else None
        if link is None or len(cells) < 2:
            continue
        url = urljoin(base, link["href"])
        out.append(dict(key=_slug(url), url=url, title=clean_text(link.get_text(" ")), date_text=clean_text(cells[1].get_text(" "))))
    return out


def _collect_nmao(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "国立国際美術館", "nmao", NMAO + "/", "ja"), set()
    response = ctx.fetch(f"{NMAO}/exhibition/current_exhibition/")
    items = parse_nmao_current(response.text, response.url)
    ctx.count("fetched", len(items))
    for item in items:
        seen.add(item["key"])
        parts = [f"区分: {item['category']}" if item["category"] else None, f"冠: {item['prefix']}" if item["prefix"] else None,
                 f"会場: {item['venue']}" if item["venue"] else None]
        _store_event(ctx, org, response, key=item["key"], title=item["title"], lang="ja", date_text=item["date_text"],
                     url=item["url"], locator=".ex_poster .txts", city="Osaka", country="JP",
                     subtype=_subtype(item["title"], item["category"]), excerpt="; ".join(p for p in parts if p) or None,
                     status="scheduled" if item["upcoming"] else None)
    ctx.con.commit()
    response = ctx.fetch(f"{NMAO}/exhibition/past_exhibition/")
    items = parse_nmao_past(response.text, response.url)
    ctx.count("fetched", len(items))
    for item in items:
        start, _, end, _ = parse_range(item["date_text"])
        if item["key"] in seen or not _in_scope(ctx, start, end, today):
            continue
        seen.add(item["key"])
        _store_event(ctx, org, response, key=item["key"], title=item["title"], lang="ja", date_text=item["date_text"],
                     url=item["url"], locator="table.extbl tr", city="Osaka", country="JP", subtype=_subtype(item["title"]))
    ctx.con.commit()
    ctx.note("NMAO: past-exhibition table lists fiscal years back to 1977; stored from 2023 in initial. Venue overrides "
             "(e.g. 大阪中之島美術館 satellite) are kept in the excerpt; all venues shown are in Osaka. Titles only, no artist inference.")


# ---------------------------------------------------------------------------------------------------- Yokohama (JP)
def _yokobi_title(node):
    lines = [x for x in _lines(node) if not re.match(r"^\d{4}年\d{1,2}月", x)]
    return " ".join(lines)


def parse_yokobi_current(html, base):
    out = []
    for block in soup(html).select(".exhibitionMain__set, .exhibitionSub__set"):
        link, date = block.select_one("h3 a"), block.select_one(".dateTxt")
        if link is None:
            continue
        url = urljoin(base, link["href"])
        label = block.select_one("span.label")
        image = block.select_one("figure img[src]")
        out.append(dict(key=_slug(url), url=url, title=_yokobi_title(link), date_text=clean_text(date.get_text(" ")) if date else None,
                        label=clean_text(label.get_text(" ")) if label else None,
                        image=urljoin(base, image["src"]) if image else None))
    return out


def _collect_yokobi(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "横浜美術館", "yokohama-museum-of-art", YOKOBI + "/", "ja"), set()
    for url, locator in ((f"{YOKOBI}/exhibition/", ".exhibitionMain__set"), (f"{YOKOBI}/exhibition-past/", ".exhibitionSub__set")):
        response = ctx.fetch(url)
        items = parse_yokobi_current(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            start, _, end, _ = parse_range(item["date_text"])
            if item["key"] in seen or not _in_scope(ctx, start, end, today):
                continue
            seen.add(item["key"])
            _store_event(ctx, org, response, key=item["key"], title=item["title"], lang="ja", date_text=item["date_text"],
                         url=item["url"], locator=locator, city="Yokohama", country="JP",
                         subtype=_subtype(item["title"], item["label"]),
                         excerpt=f"区分: {item['label']}" if item["label"] else None, image=item["image"])
        ctx.con.commit()
    ctx.note("Yokohama Museum of Art: /exhibition/ (開催中・予告) + /exhibition-past/ (single page back to 1989; stored from 2023 "
             "in initial). Site category label kept verbatim in the excerpt; 年間スケジュール page not collected.")


# ---------------------------------------------------------------------------------------------------- Benesse (JP)
def parse_benesse_news(html, base):
    out = []
    for dl in soup(html).select("dl.entry-list"):
        day, link = dl.select_one(".news-ind-day"), dl.select_one("dd a")
        if day is None or link is None:
            continue
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", clean_text(day.get_text()))
        if not m:
            continue
        labels = [clean_text(x.get_text(" ")) for x in dl.select(".gl-category") if clean_text(x.get_text(" "))]
        out.append(dict(url=urljoin(base, link["href"]), title=clean_text(link.get_text(" ")),
                        published_at=f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", categories="; ".join(labels) or None))
    return out


def _collect_benesse(ctx):
    today = now_kst().date()
    urls = [f"{BENESSE}/news/"] + ([f"{BENESSE}/news/{y}/" for y in range(today.year - 1, 2022, -1)] if ctx.mode == "initial" else [])
    for url in urls:
        response = ctx.fetch(url)
        items = parse_benesse_news(response.text, response.url)
        ctx.count("fetched", len(items))
        for item in items:
            db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=item["url"], title=item["title"],
                              published_at=item["published_at"], publisher="ベネッセアートサイト直島",
                              owner_group=ctx.meta["owner_group"], article_type="announcement",
                              type_basis="official art-site news index (公式お知らせ)", lang="ja",
                              categories=item["categories"], excerpt=None)
            ctx.count("parsed")
        ctx.con.commit()
    ctx.note("Benesse Art Site: yearly news index pages (current year + 2023-2025 in initial); announcement metadata only "
             "(title/date/island labels). No article bodies; titles with dates are not turned into exhibition events.")


# ---------------------------------------------------------------------------------------------------- Busan MoA (KR)
_COUNTRY_WORDS = {"중국": "CN", "일본": "JP", "미국": "US", "프랑스": "FR", "독일": "DE", "영국": "GB", "이탈리아": "IT",
                  "스페인": "ES", "대만": "TW"}


def parse_busan_list(html, base, past=False):
    out = []
    page = soup(html)
    if past:
        for a in page.select(".listTypeC a[attr-kval]"):
            m = re.search(r"id=(\d+)", a["attr-kval"])
            tit, date = a.select_one(".tit"), a.select_one(".date")
            if m and tit:
                out.append(dict(id=m.group(1), title=clean_text(tit.get_text(" ")), date_text=clean_text(date.get_text(" ")) if date else None,
                                url=f"{BUSAN}/tblTsite07Display/viewPastClient.nm?id={m.group(1)}"))
        return out
    for li in page.select(".listTypeG li"):
        a, date = li.select_one(".tit a[href]"), li.select_one(".date")
        m = re.search(r"id=(\d+)", a["href"]) if a else None
        if m:
            out.append(dict(id=m.group(1), title=clean_text(a.get_text(" ")), date_text=clean_text(date.get_text(" ")) if date else None,
                            url=urljoin(base, a["href"])))
    return out


def parse_busan_detail(html):
    page = soup(html)
    title, date = page.select_one(".viewTypeD .exh_img h2"), page.select_one(".viewTypeD .exh_img .date")
    fields = {}
    for dt_ in page.select(".viewTypeD .exh_box .infor dl dt"):
        dd = dt_.find_next_sibling("dd")
        if dd:
            fields[clean_text(dt_.get_text(" "))] = clean_text(dd.get_text(" "))
    return dict(title=clean_text(title.get_text(" ")) if title else None, date_text=clean_text(date.get_text(" ")) if date else None,
                section=fields.get("전시부문"), venue=fields.get("전시장소"))


def busan_venue(section, venue):
    """Country from a named foreign country at the start of 전시장소; otherwise the museum's own rooms (Busan)."""
    for word, code in _COUNTRY_WORDS.items():
        if venue and venue.startswith(word):
            return None, code
    if section != "해외" and venue and any(m in venue for m in ("미술관", "전시실", "갤러리", "로비", "지하", "야외")):
        return "Busan", "KR"
    return None, None


def _collect_busan(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "부산시립미술관", "busan-museum-of-art", BUSAN + "/", "ko"), set()
    cards = []
    for url, past in ((f"{BUSAN}/tblTsite07Display/listNowClient.nm", False), (f"{BUSAN}/tblTsite07Display/listFutureClient.nm", False)):
        response = ctx.fetch(url)
        found = parse_busan_list(response.text, response.url)
        ctx.count("fetched", len(found))
        cards += found
        if not found:
            ctx.note(f"Busan MoA {url.rsplit('/', 1)[-1]}: no exhibitions listed on {today.isoformat()}")
    page_cap = 15 if ctx.mode == "initial" else 1
    for number in range(1, page_cap + 1):
        response = ctx.fetch(f"{BUSAN}/tblTsite07Display/listPastClient.nm", params={"page_no": number} if number > 1 else None)
        found = parse_busan_list(response.text, response.url, past=True)
        ctx.count("fetched", len(found))
        cards += found
        ends = [parse_range(x["date_text"])[2] or parse_range(x["date_text"])[0] for x in found]
        if not found or (ctx.mode == "initial" and all(e and e[:4] < HISTORY_FLOOR[:4] for e in ends)):
            break
    else:
        ctx.note(f"Busan MoA past list stopped at the {page_cap}-page cap")
    for card in cards:
        key = f"exhibition-{card['id']}"
        start, _, end, _ = parse_range(card["date_text"])
        if key in seen or not _in_scope(ctx, start, end, today) or not _needs_detail(ctx, key, today):
            continue
        if _cap(ctx):
            ctx.note("Busan MoA details stopped at the request budget")
            break
        seen.add(key)
        detail = _fetch_or_note(ctx, card["url"], f"busan {card['id']}")
        if detail is None:
            continue
        info = parse_busan_detail(detail.text)
        city, country = busan_venue(info["section"], info["venue"])
        excerpt = "; ".join(x for x in (f"전시부문: {info['section']}" if info["section"] else None,
                                        f"전시장소: {info['venue']}" if info["venue"] else None) if x) or None
        _store_event(ctx, org, detail, key=key, title=info["title"] or card["title"], lang="ko",
                     date_text=info["date_text"] or card["date_text"], url=detail.url, locator=".viewTypeD .exh_img / .exh_box dl",
                     city=city, country=country, subtype=_subtype(card["title"]), excerpt=excerpt,
                     review_detail=info["venue"])
        ctx.con.commit()
    ctx.note("Busan MoA: now/future lists + past list (53 pages; initial pages until one page is entirely pre-2023). "
             "A 2099-12-31 end date used by the CMS for open-ended displays is stored as no end date.")


# ---------------------------------------------------------------------------------------------------- Daegu (KR)
def parse_daegu_list(html):
    out = []
    for item in soup(html).select(".c_exh_lst .item"):
        anchor = item.select_one("a[href*='fnView']")
        m = re.search(r"fnView\('(EHI_\d+)'\)", anchor["href"]) if anchor else None
        title, step = item.select_one(".item_tit"), item.select_one(".step")
        if not m or title is None:
            continue
        info = {}
        for block in item.select(".info"):
            label = block.select_one(".info_tit")
            value = block.select_one(".info_date") or (label.find_next_sibling("span") if label else None)
            if label and value:
                info[clean_text(label.get_text())] = clean_text(value.get_text(" "))
        out.append(dict(id=m.group(1), title=clean_text(title.get_text(" ")), status=clean_text(step.get_text()) if step else None,
                        date_text=info.get("기간"), venue=info.get("장소")))
    return out


def _collect_daegu(ctx):
    today, org, seen = now_kst().date(), _org(ctx, "대구미술관", "daegu-art-museum", DAEGU + "/", "ko"), set()
    plan = [("00000729", 1), ("00000731", 1)]
    plan.append(("00000730", 4 if ctx.mode == "initial" else 1))
    for menu, pages in plan:
        for number in range(1, pages + 1):
            params = {"menu_id": menu, "pageUnitF": 24}
            if number > 1:
                params["pageIndex"] = number
            response = ctx.fetch(f"{DAEGU}/index.do", params=params)
            items = parse_daegu_list(response.text)
            ctx.count("fetched", len(items))
            ends = []
            for item in items:
                start, _, end, _ = parse_range(item["date_text"])
                ends.append(end or start)
                if item["id"] in seen or not _in_scope(ctx, start, end, today):
                    continue
                seen.add(item["id"])
                daegu = bool(item["venue"] and "대구미술관" in item["venue"])
                _store_event(ctx, org, response, key=item["id"], title=item["title"], lang="ko", date_text=item["date_text"],
                             url=f"{response.url}#{item['id']}", locator=".c_exh_lst .item .info",
                             city="Daegu" if daegu else None, country="KR" if daegu else None, subtype=_subtype(item["title"]),
                             excerpt="; ".join(x for x in (f"장소: {item['venue']}" if item["venue"] else None,
                                                           f"상태: {item['status']}" if item["status"] else None) if x) or None,
                             review_detail=item["venue"])
            ctx.con.commit()
            if menu == "00000730" and (not items or all(e and e[:4] < HISTORY_FLOOR[:4] for e in ends)):
                break
    ctx.note("Daegu Art Museum: 현재/예정/지난전시 GET lists (24 per page; past list reaches 2020 on page 2). Detail views are "
             "POST-only and are not requested; poster images are not fetched.")


# ---------------------------------------------------------------------------------------------------- GMoMA / NJP (KR, Gyeonggi CMS)
def _split_names(value):
    names, depth, current = [], 0, ""
    for ch in value or "":
        if ch in "([（":
            depth += 1
        elif ch in ")]）":
            depth = max(0, depth - 1)
        if ch in ",、，" and depth == 0:
            names.append(current)
            current = ""
        else:
            current += ch
    names.append(current)
    return [n for n in (clean_text(x) for x in names) if n and n not in ("-", "–")]


def _person_name(listed):
    name = re.sub(r"\s*[\(（].*?[\)）]", "", listed)
    return clean_text(re.sub(r"\s*(학예연구사|학예연구관|학예사|큐레이터|관장)$", "", name))


def parse_ggcf_list(html, base):
    out = []
    for a in soup(html).select("a[href]"):
        m = re.search(r"(?:^|/)exhibitions/(\d+)$", a["href"])
        if not m:
            continue
        title = next((p for p in a.select("p") if "date" not in (p.get("class") or [])), None)
        date = a.select_one("p.date")
        if title is None or not clean_text(title.get_text(" ")):
            continue
        image = a.select_one("img[src]")
        out.append(dict(id=m.group(1), title=clean_text(title.get_text(" ")),
                        date_text=clean_text(date.get_text(" ")) if date else None, url=urljoin(base, a["href"]),
                        image=urljoin(base, image["src"]) if image else None))
    seen, unique = set(), []
    for item in out:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return unique


def _dl_fields(dl_nodes):
    fields = {}
    for dl in dl_nodes:
        for dt_ in dl.select("dt"):
            dd = dt_.find_next_sibling("dd")
            if dd:
                fields.setdefault(clean_text(dt_.get_text(" ")), clean_text(dd.get_text(" ")))
    return fields


def parse_gmoma_detail(html):
    page = soup(html)
    meta = {m.get("property"): (m.get("datetime") or m.get("content")) for m in page.select(".event-shcema meta[property]")}
    fields = _dl_fields(page.select(".view-content-area dl.meta"))
    title = page.select_one(".view-title h2")
    series = page.select_one(".view-title h3")
    return dict(title=clean_text(title.get_text(" ")) if title else meta.get("name"),
                series=clean_text(series.get_text(" ")) if series and clean_text(series.get_text(" ")) else None,
                start=meta.get("startDate"), end=meta.get("endDate"), venue=fields.get("장소") or meta.get("location"),
                artists=_split_names(fields.get("참여작가") or ""), curators=_split_names(fields.get("기획") or ""),
                organizers=fields.get("주최·주관"))


def parse_njp_list(html, base):
    out = []
    for li in soup(html).select("li"):
        title, date = li.select_one("a.title[href]"), li.select_one(".date")
        m = re.search(r"/exhibitions/(\d+)$", title["href"]) if title else None
        if not m:
            continue
        thumb = li.select_one(".thumb[style]")
        image = re.search(r"url\('?([^')]+)", thumb["style"]) if thumb else None
        out.append(dict(id=m.group(1), title=clean_text(title.get_text(" ")), date_text=clean_text(date.get_text(" ")) if date else None,
                        url=urljoin(base, title["href"]), image=urljoin(base, image.group(1)) if image else None))
    return out


def parse_njp_detail(html):
    page = soup(html)
    root = page.select_one(".exhibition-show .meta-info")
    if root is None:
        return {}
    title, date = root.select_one(".title"), root.select_one(".date")
    fields = _dl_fields(root.select("dl.meta"))
    return dict(title=clean_text(title.get_text(" ")) if title else None, date_text=clean_text(date.get_text(" ")) if date else None,
                venue=fields.get("장소"), artists=_split_names(fields.get("참여작가") or ""),
                curators=_split_names(fields.get("기획") or ""), organizers=fields.get("주최주관"))


_GG_VENUES = {"wave2_gmoma_exhibitions": ("Ansan", ("경기도미술관", "B1", "야외 전시장", "미술관 ")),
              "wave2_njp_exhibitions": ("Yongin", ("백남준아트센터", "용인"))}


def _gg_city(ctx, venue):
    """City/country only when the displayed venue names the institution's own premises (or Yongin for NJP's
    off-site Yongin programmes); partner venues elsewhere (e.g. a co-organiser's museum) stay unknown."""
    city, markers = _GG_VENUES[ctx.source_id]
    if venue and "성남" in venue:
        return None, "KR"  # venue line names both the Yongin centre and a Seongnam lobby; country is KR either way
    if venue and any(venue.startswith(m) or m in venue for m in markers) and "상파울루" not in venue:
        return city, "KR"
    return None, None


def _participants(ctx, event_id, evidence, names, role, namespace):
    for listed in names:
        name = _person_name(listed)
        if not name or name in ("경기도미술관", "백남준아트센터"):
            continue
        entity = db.ensure_entity(ctx.con, entity_type="person", name=name, namespace=namespace, lang="ko", source_id=ctx.source_id,
                                  evidence_id=evidence)
        db.add_participant(ctx.con, event_id, entity, role, listed, evidence, "list_markup", "high")
        ctx.count("participants")


def _collect_gg(ctx):
    gmoma = ctx.source_id == "wave2_gmoma_exhibitions"
    base = GMOMA if gmoma else NJP
    today = now_kst().date()
    org = _org(ctx, "경기도미술관" if gmoma else "백남준아트센터", "gmoma" if gmoma else "njp", base + "/", "ko")
    namespace = f"src:{ctx.source_id}"
    cards = []
    if gmoma:
        for progress in ("now", "ago"):
            response = ctx.fetch(f"{base}/exhibitions", params={"progress": progress})
            cards += parse_ggcf_list(response.text, response.url)
        last = max([int(x) for x in re.findall(r'data-last-page="(\d+)"', response.text)] or [1])
        page_cap = min(last, 8 if ctx.mode == "initial" else 1)
        for number in range(2, page_cap + 1):
            fragment = ctx.fetch(f"{base}/exhibitions/more", params={"progress": "ago", "page": number})
            found = parse_ggcf_list(fragment.text, fragment.url)
            cards += found
            ends = [parse_range(x["date_text"])[2] or parse_range(x["date_text"])[0] for x in found]
            if not found or all(e and e[:4] < HISTORY_FLOOR[:4] for e in ends):
                break
    else:
        response = ctx.fetch(f"{base}/exhibitions")
        cards += parse_njp_list(response.text, response.url)
        years = range(today.year, 2022, -1) if ctx.mode == "initial" else [today.year]
        for year in years:
            fragment = ctx.fetch(f"{base}/exhibitions/more", params={"year": year})
            cards += parse_njp_list(fragment.text, fragment.url)
    ctx.count("fetched", len(cards))
    seen = set()
    for card in cards:
        key = f"exhibition-{card['id']}"
        start, _, end, _ = parse_range(card["date_text"])
        if key in seen or not _in_scope(ctx, start, end, today) or not _needs_detail(ctx, key, today):
            continue
        if _cap(ctx):
            ctx.note("details stopped at the request budget")
            break
        seen.add(key)
        detail = _fetch_or_note(ctx, card["url"], f"exhibition {card['id']}")
        if detail is None:
            continue
        info = parse_gmoma_detail(detail.text) if gmoma else parse_njp_detail(detail.text)
        if gmoma:
            date_text = card["date_text"]
            if info.get("start"):
                date_text = f"{info['start']} ~ {info['end']}" if info.get("end") else f"{info['start']} ~"
        else:
            date_text = info.get("date_text") or card["date_text"]
        city, country = _gg_city(ctx, info.get("venue"))
        excerpt = "; ".join(x for x in (f"장소: {info['venue']}" if info.get("venue") else None,
                                        f"주최: {info['organizers']}" if info.get("organizers") else None) if x) or None
        event_id, _, _ = _store_event(ctx, org, detail, key=key, title=info.get("title") or card["title"], lang="ko",
                                      date_text=date_text, url=detail.url,
                                      locator="schema.org event meta + dl.meta" if gmoma else ".exhibition-show .meta-info dl.meta",
                                      city=city, country=country, subtype=_subtype(card["title"]), excerpt=excerpt,
                                      image=card.get("image"), review_detail=info.get("venue"))
        evidence = ctx.evidence(detail, locator="dl.meta 참여작가/기획", excerpt=", ".join(info.get("artists", [])[:8]) or None)
        _participants(ctx, event_id, evidence, info.get("artists", []), "artist", namespace)
        _participants(ctx, event_id, evidence, info.get("curators", []), "curator", namespace)
        ctx.con.commit()
    ctx.note(("GMoMA" if gmoma else "NJP") + ": current/upcoming + past archive (initial: back to 2023); artists/curators are "
             "taken only from the detail page 참여작가/기획 lists; an institution named as 기획 is not stored as a curator person.")


# ---------------------------------------------------------------------------------------------------- dispatch
def collect(ctx):
    handlers = {
        "wave2_nmwa_exhibitions": _collect_nmwa, "wave2_momak_exhibitions": _collect_momak,
        "wave2_nmao_exhibitions": _collect_nmao, "wave2_yokohama_museum_exhibitions": _collect_yokobi,
        "wave2_benesse_artsite_news": _collect_benesse, "wave2_busan_moa_exhibitions": _collect_busan,
        "wave2_daegu_art_museum": _collect_daegu, "wave2_gmoma_exhibitions": _collect_gg,
        "wave2_njp_exhibitions": _collect_gg,
    }
    if ctx.source_id not in handlers:
        raise ValueError(f"{ctx.source_id}: disabled or unknown source")
    handlers[ctx.source_id](ctx)
    ctx.con.commit()
