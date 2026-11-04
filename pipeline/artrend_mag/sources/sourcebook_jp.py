"""Additional Japanese sourcebook collectors: galleries, exhibitions, awards and criticism metadata."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from .. import db
from ._common import classify_subtype, clean_text, parse_date_range, soup

PARSER_VERSION = "sourcebook_jp-1"

SOURCES = [
    dict(source_id="mizuma_gallery", blueprint_data_id=None, blueprint_org_id=None,
         name="MIZUMA ART GALLERY — exhibitions and artist roster", owner_group="MIZUMA ART GALLERY",
         source_kind="gallery", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://mizuma-art.co.jp", entry_url="https://mizuma-art.co.jp/ja/exhibitions/",
         terms_url="https://mizuma-art.co.jp/site_policy", text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(public HTML)",
         st_collection_terms="Site Policy opened: texts, images and documents are protected by copyright; reuse beyond statutory private use requires rights-holder permission. No explicit automated-access permission located.",
         st_image_terms="No image licence located; do not reuse images; record unknown rights only.", max_requests=30),
    dict(source_id="shugoarts_gallery", blueprint_data_id=None, blueprint_org_id=None,
         name="ShugoArts — exhibitions and artist roster", owner_group="ShugoArts",
         source_kind="gallery", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://shugoarts.com", entry_url="https://shugoarts.com/exhibitions/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(public HTML)",
         st_collection_terms="No terms page located on site navigation; no explicit automated-access permission observed.",
         st_image_terms="No image licence located; do not reuse images; record unknown rights only.", max_requests=20),
    dict(source_id="take_ninagawa_gallery", blueprint_data_id=None, blueprint_org_id=None,
         name="Take Ninagawa — exhibitions and artist roster", owner_group="Take Ninagawa",
         source_kind="gallery", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.takeninagawa.com", entry_url="https://www.takeninagawa.com/exhibitions/",
         terms_url=None, text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(public HTML)",
         st_collection_terms="No terms page located on site navigation; no explicit automated-access permission observed.",
         st_image_terms="No image licence located; do not reuse images; record unknown rights only.", max_requests=15),
    dict(source_id="kotaro_nukaga_gallery", blueprint_data_id=None, blueprint_org_id=None,
         name="KOTARO NUKAGA — exhibitions and artist roster", owner_group="KOTARO NUKAGA",
         source_kind="gallery", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://kotaronukaga.com", entry_url="https://kotaronukaga.com/exhibition/",
         terms_url=None, text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(public HTML)",
         st_collection_terms="No terms page located on site navigation; no explicit automated-access permission observed.",
         st_image_terms="No image licence located; do not reuse images; record unknown rights only.", max_requests=20),
    dict(source_id="tobikan_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Tokyo Metropolitan Art Museum — exhibitions", owner_group="Tokyo Metropolitan Art Museum",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.tobikan.jp", entry_url="https://www.tobikan.jp/exhibition/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(public HTML)",
         st_collection_terms="No terms page located from the public navigation; no explicit automated-access permission observed.",
         st_image_terms="Poster/artwork images are not reused; no open image licence observed.", max_requests=10),
    dict(source_id="faam_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Fukuoka Asian Art Museum — exhibitions", owner_group="Fukuoka Asian Art Museum",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://faam.city.fukuoka.lg.jp", entry_url="https://faam.city.fukuoka.lg.jp/exhibition/",
         terms_url="https://faam.city.fukuoka.lg.jp/policy/", text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(public HTML)",
         st_collection_terms="Site Policy opened: texts and other content belong to the museum/information providers; use beyond private use is restricted. No explicit automated-access permission located.",
         st_image_terms="Images are not reused; rights remain with the museum or named creators.", max_requests=15),
    dict(source_id="voca_award", blueprint_data_id=None, blueprint_org_id=None,
         name="VOCA Exhibition — award winners", owner_group="The Ueno Royal Museum",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.ueno-mori.org", entry_url="https://www.ueno-mori.org/exhibitions/voca/",
         terms_url="https://www.ueno-mori.org/other/sitepolicy.html", text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(public HTML)",
         st_collection_terms="Site Policy opened: text, artwork images and materials belong to authors, museum or information providers; reuse without permission is prohibited.",
         st_image_terms="Images are not reused; no open image licence observed.", max_requests=10),
    dict(source_id="artscape_reviews", blueprint_data_id=None, blueprint_org_id=None,
         name="artscape — review article metadata", owner_group="DAI NIPPON PRINTING Co., Ltd.",
         source_kind="media", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://artscape.jp", entry_url="https://artscape.jp/category/review/",
         terms_url="https://artscape.jp/term/", text_storage_policy="metadata_only", priority="P1",
         st_official_doc="n/a(public HTML listing; no feed used)",
         st_collection_terms="Terms opened: DAI NIPPON PRINTING operates artscape; unauthorized reuse of images/content is prohibited. Metadata only, no article-body fetch or storage; no explicit automated-access permission located.",
         st_image_terms="Editorial images are not reused; no licence inferred.", max_requests=30),
    dict(source_id="aica_critique", blueprint_data_id=None, blueprint_org_id=None,
         name="美術評論＋ — exhibition-criticism metadata", owner_group="美術評論家連盟 (AICA Japan)",
         source_kind="media", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://critique.aicajapan.com",
         entry_url="https://critique.aicajapan.com/category/form/exhibition-review/",
         terms_url="https://critique.aicajapan.com/site-policy", text_storage_policy="metadata_only", priority="P1",
         st_official_doc="n/a(public HTML listing; no feed/API used)",
         st_collection_terms="Site Policy/Terms opened: submitted writing remains with its author/member; third-party images require permission and credit. Metadata only, no article-body fetch or storage; no explicit automated-access permission located.",
         st_image_terms="Editorial images are not reused; no licence inferred.", max_requests=80),
]

_GALLERIES = {
    "mizuma_gallery": ("MIZUMA ART GALLERY", "https://mizuma-art.co.jp", "/ja/artists/"),
    "shugoarts_gallery": ("ShugoArts", "https://shugoarts.com", "/artists/"),
    "take_ninagawa_gallery": ("Take Ninagawa", "https://www.takeninagawa.com", "/artists"),
    "kotaro_nukaga_gallery": ("KOTARO NUKAGA", "https://kotaronukaga.com", "/artist"),
}

_JAPANESE_DATE = re.compile(
    r"(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?"
    r"|(?:19|20)\d{2}[./]\s*\d{1,2}[./]\s*\d{1,2}"
)


def collect(ctx):
    if ctx.source_id in _GALLERIES:
        return _gallery(ctx)
    if ctx.source_id == "tobikan_exhibitions":
        return _tobikan(ctx)
    if ctx.source_id == "faam_exhibitions":
        return _faam(ctx)
    if ctx.source_id == "voca_award":
        return _voca(ctx)
    if ctx.source_id == "artscape_reviews":
        return _artscape(ctx)
    if ctx.source_id == "aica_critique":
        return _aica(ctx)
    raise ValueError(f"unsupported sourcebook source: {ctx.source_id}")


def _org(ctx, name, entity_type):
    return db.ensure_entity(ctx.con, entity_type=entity_type, name=name, namespace=f"src:{ctx.source_id}",
                            id_value="organization", lang="en", source_id=ctx.source_id)


def _identity_from_url(url):
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or url


def _roster(ctx, org, base, path):
    r = ctx.fetch(urllib.parse.urljoin(base, path))
    evidence = ctx.evidence(r, locator="artist roster links")
    s = soup(r.text)
    prefix = "/artist/" if path.rstrip("/").endswith("/artist") else "/artists/"
    seen = set()
    for a in s.select("a[href]"):
        href = urllib.parse.urljoin(r.final_url, a.get("href", ""))
        p = urllib.parse.urlsplit(href).path.rstrip("/")
        if not p.startswith(prefix):
            continue
        slug = p[len(prefix):].split("/", 1)[0]
        name = clean_text(a.get_text(" "))
        if not slug or not name or slug.casefold() in {"artist", "artists", "index"}:
            continue
        key = (slug, name)
        if key in seen:
            continue
        seen.add(key)
        artist = db.ensure_entity(ctx.con, entity_type="person", name=name,
                                  namespace=f"{ctx.source_id}_artist", id_value=slug,
                                  lang="ja", source_id=ctx.source_id, evidence_id=evidence, official_url=href)
        db.upsert_relationship(ctx.con, subject_entity_id=org, object_entity_id=artist,
                               rel_type="listed_artist", source_id=ctx.source_id,
                               evidence_id=evidence, status="source_asserted")
        image = _image_url(a, r.final_url)
        if image:
            db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown",
                                basis=ctx.meta.get("st_image_terms", "no image reuse licence observed"),
                                page_url=href, image_url=image, entity_id=artist)
    ctx.count("fetched", len(seen))
    ctx.con.commit()


def _jp_dates(text):
    """Parse visible Japanese/dotted periods, including ShugoArts' year-once dotted markup."""
    value = clean_text(text)
    parsed = parse_date_range(value)
    if parsed[0] and parsed[2]:
        return parsed
    start = re.search(r"((?:19|20)\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", value)
    if not start:
        return parsed
    try:
        first = dt.date(int(start.group(1)), int(start.group(2)), int(start.group(3))).isoformat()
    except ValueError:
        return parsed
    tail = value[start.end():]
    full_end = re.search(r"((?:19|20)\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", tail)
    if full_end:
        try:
            last = dt.date(int(full_end.group(1)), int(full_end.group(2)), int(full_end.group(3))).isoformat()
            return first, "day", last, "day"
        except ValueError:
            return first, "day", None, None
    partial = re.search(r"(?:^|\s)(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)", tail)
    if not partial:
        return first, "day", None, None
    year, month, day = int(start.group(1)), int(partial.group(1)), int(partial.group(2))
    if month < int(start.group(2)):
        year += 1
    try:
        last = dt.date(year, month, day).isoformat()
    except ValueError:
        last = None
    return first, "day", last, "day" if last else None


def _date_line(text):
    value = clean_text(text)
    m = _JAPANESE_DATE.search(value)
    if not m:
        return value if parse_date_range(value)[0] else None
    tail = value[m.start():]
    if re.search(r"(?:-|–|—|〜|～|から|至|〜)\s*(?:(?:19|20)\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}", tail):
        end = re.search(r"(?:-|–|—|〜|～|から|至)\s*", tail)
        if end:
            return tail[:min(len(tail), end.start() + 80)]
    return tail[:80]


def _image_url(node, base):
    if node is None:
        return None
    candidates = [node, *node.select("img, [data-bg], [data-src], [data-lazy-src], [data-original]")]
    for candidate in candidates:
        src = (candidate.get("data-src") or candidate.get("data-lazy-src") or candidate.get("data-original")
               or candidate.get("data-bg") or candidate.get("src"))
        if not src:
            match = re.search(r"background-image\s*:\s*url\(['\"]?([^)'\"]+)", candidate.get("style", ""), re.I)
            src = match.group(1) if match else None
        if src and not src.startswith("data:"):
            return urllib.parse.urljoin(base, src)
    return None


def _save_event(ctx, org, *, key, title, date_text, url, resp, locator, city, event_type="exhibition",
                subtype=None, artists=(), image_url=None):
    title = clean_text(title)
    if not title or not url:
        return None
    start, sp, end, ep = _jp_dates(date_text or "")
    evidence = ctx.evidence(resp, locator=locator, excerpt=date_text)
    event_id = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key,
                               event_type=event_type, subtype=subtype, title=title, title_lang="ja",
                               organizer_entity_id=org, city=city, country_code="JP",
                               start_date=start, start_precision=sp, end_date=end, end_precision=ep,
                               date_text=date_text, url=url, evidence_id=evidence,
                               parser_version=PARSER_VERSION)
    for name in artists:
        name = clean_text(name)
        if not name:
            continue
        entity = db.ensure_entity(ctx.con, entity_type="person", name=name,
                                  namespace=f"src:{ctx.source_id}:artists", id_value=db.name_key(name),
                                  lang="ja", source_id=ctx.source_id, evidence_id=evidence)
        db.add_participant(ctx.con, event_id, entity, "artist", name, evidence, "list_markup")
    if image_url:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown",
                            basis=ctx.meta.get("st_image_terms", "no image reuse licence observed"),
                            page_url=url, image_url=image_url, event_id=event_id)
    ctx.count("parsed")
    return event_id


def _event_url(row, resp):
    a = row.select_one("a[href]")
    if a is None:
        a = row.find_parent("a", href=True)
    return urllib.parse.urljoin(resp.final_url, a["href"]) if a else resp.final_url


def _event_key(url, title, date_text):
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    if path.rsplit("/", 1)[-1] in {"exhibitions", "exhibition"}:
        return db.sid("jp", title, date_text)
    return _identity_from_url(url) if url else db.sid("jp", title, date_text)


def _title_before_date(text):
    value = clean_text(text)
    match = _JAPANESE_DATE.search(value)
    if match:
        value = value[:match.start()]
    value = re.sub(r"\s*\((?:TOKYO|東京)\)\s*$", "", value, flags=re.I)
    return clean_text(value).strip("｜| —–-")


def _gallery(ctx):
    name, base, roster_path = _GALLERIES[ctx.source_id]
    org = _org(ctx, name, "gallery")
    root = ctx.fetch(ctx.meta["entry_url"])
    pages = [(root, "exhibition listing")]
    if ctx.source_id == "mizuma_gallery":
        archive_links = {}
        for a in soup(root.text).select("a[href]"):
            m = re.search(r"/exhibitions-archive/(\d{4})/", a.get("href", ""))
            if m:
                archive_links[int(m.group(1))] = urllib.parse.urljoin(root.final_url, a["href"])
        years = sorted(archive_links, reverse=True)
        if ctx.mode == "initial":
            years = [year for year in years if year >= 2023][:4]
        else:
            years = years[:1]
        for year in years:
            if archive_links[year] == root.final_url:
                continue
            pages.append((ctx.fetch(archive_links[year]), f"exhibitions archive {year}"))
    seen = set()
    for resp, section in pages:
        s = soup(resp.text)
        if ctx.source_id == "mizuma_gallery":
            rows = s.select("li.exh-list")
        elif ctx.source_id == "shugoarts_gallery":
            rows = s.select(".exhibition-box")
        elif ctx.source_id == "take_ninagawa_gallery":
            rows = s.select("article section.sec ul.list-text-figure li")
        else:
            rows = s.select(".card-wrap")
        ctx.count("fetched", len(rows))
        for row in rows:
            text = clean_text(row.get_text(" "))
            if ctx.source_id == "mizuma_gallery" and re.search(r"Singapore|シンガポール", text, re.I):
                continue
            if ctx.source_id == "shugoarts_gallery":
                title_el = row.select_one(".info__title")
                title = clean_text(title_el.get_text(" ")) if title_el else ""
                date_el = row.select_one(".info__date")
                date_text = clean_text(date_el.get_text(" ")) if date_el else None
                artists_el = row.select_one(".left__artist .artist__main")
                names = re.split(r"[、,，]", clean_text(artists_el.get_text(" "))) if artists_el else []
                names = [n for n in names if n and n not in {"ほか", "他"}]
            elif ctx.source_id == "take_ninagawa_gallery":
                title_el = row.select_one(".title-box-title")
                title = clean_text(title_el.get_text(" ")) if title_el else ""
                date_el = next((el for el in row.select(".title-box-info") if _JAPANESE_DATE.search(el.get_text(" "))), None)
                date_text = clean_text(date_el.get_text(" ")) if date_el else None
                names = []
            elif ctx.source_id == "kotaro_nukaga_gallery":
                title_el = row.select_one("h1, h2, h3, h4, .title")
                title = clean_text(title_el.get_text(" ")) if title_el else _title_before_date(text)
                date_text = _date_line(text)
                names = []
            else:
                title_el = row.select_one("h1, h2, h3, h4, .title")
                title = clean_text(title_el.get_text(" ")) if title_el else _title_before_date(text)
                date_text = _date_line(text)
                names = []
            url = _event_url(row, resp)
            if ctx.source_id == "mizuma_gallery" and not re.search(r"\bTOKYO\b|東京", text, re.I):
                continue
            key = _event_key(url, title, date_text)
            if key in seen:
                continue
            seen.add(key)
            _save_event(ctx, org, key=key, title=title, date_text=date_text, url=url, resp=resp,
                        locator=f"{section}: {row.name}.{'.'.join(row.get('class', []))}", city="Tokyo",
                        subtype=classify_subtype(title, len(names)), artists=names,
                        image_url=_image_url(row, resp.final_url))
        ctx.con.commit()
    _roster(ctx, org, base, roster_path)
    ctx.note(f"{name}: official exhibition listing and linked artist roster only; no detail pages or article text fetched. "
             f"History is limited to the visible listing{'; MIZUMA year links >=2023 in initial mode' if ctx.source_id == 'mizuma_gallery' else ''}.")
    ctx.con.commit()


def _tobikan(ctx):
    resp = ctx.fetch(ctx.meta["entry_url"])
    org = _org(ctx, "Tokyo Metropolitan Art Museum", "institution")
    rows = _tobikan_rows(resp.text, resp.final_url)
    ctx.count("fetched", len(rows))
    for row in rows:
        _save_event(ctx, org, key=_event_key(row["url"], row["title"], row["date_text"]),
                    title=row["title"], date_text=row["date_text"], url=row["url"], resp=resp,
                    locator="ul.exhibition-list a.exhibition-item", city="Tokyo",
                    subtype=row["subtype"], image_url=row["image_url"])
    ctx.con.commit()
    ctx.note("東京都美術館: the public exhibition page exposes visible current/future and archived annual lists; "
             "one listing fetch only, no detail pages or images downloaded.")


def _tobikan_rows(html, final_url):
    parsed = []
    for row in soup(html).select("ul.exhibition-list a.exhibition-item"):
        title_el = row.select_one(".-title")
        date_el = row.select_one(".-period")
        category_el = row.select_one(".-category")
        title = clean_text(title_el.get_text(" ")) if title_el else ""
        date_text = clean_text(date_el.get_text(" ")) if date_el else None
        category = clean_text(category_el.get_text(" ")) if category_el else ""
        if not title:
            continue
        parsed.append({"title": title, "date_text": date_text,
                       "url": urllib.parse.urljoin(final_url, row.get("href", "")),
                       "subtype": "collection_display" if "コレクション" in category else classify_subtype(title),
                       "image_url": _image_url(row, final_url)})
    return parsed


def _faam(ctx):
    urls = [ctx.meta["entry_url"]]
    if ctx.mode == "initial":
        urls.extend(("https://faam.city.fukuoka.lg.jp/exhibition/schedule/",
                     "https://faam.city.fukuoka.lg.jp/exhibition/archive/"))
    org = _org(ctx, "Fukuoka Asian Art Museum", "institution")
    seen = set()
    for url in urls:
        resp = ctx.fetch(url)
        rows = _faam_rows(resp.text, resp.final_url)
        ctx.count("fetched", len(rows))
        for row in rows:
            title = row["title"]
            date_text = row["date_text"]
            item_url = row["url"]
            key = _event_key(item_url, title, date_text)
            if key in seen:
                continue
            seen.add(key)
            _save_event(ctx, org, key=key, title=title, date_text=date_text, url=item_url, resp=resp,
                        locator=".c-list-exhibition-item", city="Fukuoka",
                        subtype=classify_subtype(title), image_url=row["image_url"])
        ctx.con.commit()
    ctx.note("福岡アジア美術館: current exhibition list in incremental mode; initial also reads the official schedule "
             "and first archive listing. Archive pagination is not traversed; no detail pages fetched.")


def _faam_rows(html, final_url):
    parsed = []
    for row in soup(html).select(".c-list-exhibition-item"):
        title_el = row.select_one(".c-list-exhibition-item__title")
        date_el = row.select_one(".c-list-exhibition-item__date")
        link = row.select_one("a[href]")
        title = clean_text(title_el.get_text(" ")) if title_el else ""
        if not title:
            continue
        parsed.append({"title": title,
                       "date_text": clean_text(date_el.get_text(" ")) if date_el else None,
                       "url": urllib.parse.urljoin(final_url, link["href"]) if link else final_url,
                       "image_url": _image_url(row, final_url)})
    return parsed


def _voca(ctx):
    index = ctx.fetch(ctx.meta["entry_url"])
    years = {}
    for a in soup(index.text).select("a[href]"):
        url = urllib.parse.urljoin(index.final_url, a["href"])
        m = re.search(r"/exhibitions/voca/(\d{4})/?$", urllib.parse.urlsplit(url).path)
        if m:
            years[int(m.group(1))] = url
    selected = sorted(years, reverse=True)
    selected = [y for y in selected if y >= 2025][:2] if ctx.mode == "initial" else selected[:1]
    org = _org(ctx, "The Ueno Royal Museum", "institution")
    for year in selected:
        resp = ctx.fetch(years[year])
        grouped = _voca_awards(resp.text)
        ctx.count("fetched", sum(len(names) for names in grouped.values()))
        for award, winners in grouped.items():
            title = f"VOCA展{year} {award}"
            date_text = str(year)
            evidence = ctx.evidence(resp, locator="受賞作品: li", excerpt=date_text)
            event_id = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id,
                                       source_event_key=f"{year}-{award}", event_type="award", title=title,
                                       title_lang="ja", organizer_entity_id=org, city="Tokyo", country_code="JP",
                                       start_date=str(year), start_precision="year", date_text=date_text,
                                       url=resp.url, evidence_id=evidence, parser_version=PARSER_VERSION)
            for name in winners:
                ent = db.ensure_entity(ctx.con, entity_type="person", name=name,
                                       namespace=f"src:{ctx.source_id}:artists", id_value=db.name_key(name),
                                       lang="ja", source_id=ctx.source_id, evidence_id=evidence)
                db.add_participant(ctx.con, event_id, ent, "winner", name, evidence, "list_markup")
            ctx.count("parsed")
        ctx.con.commit()
    ctx.note("VOCA: official annual award winners and award categories from visible ‘受賞作品’ lists; "
             "year precision only; year pages linked from the public VOCA index; no article/video bodies fetched.")


def _voca_awards(html):
    grouped = {}
    for li in soup(html).select("li"):
        text = clean_text(li.get_text(" "))
        match = re.match(r"(VOCA賞|VOCA奨励賞|VOCA佳作賞)\s+(.+)$", text)
        if match:
            grouped.setdefault(match.group(1), []).append(clean_text(match.group(2)))
    return grouped


def _media_article(ctx, *, resp, node, title_el, article_type, category, publisher, author_selector=None):
    title = clean_text(title_el.get_text(" ")) if title_el else ""
    link = title_el if title_el and title_el.name == "a" else title_el.select_one("a[href]") if title_el else None
    if not title or link is None:
        return
    url = urllib.parse.urljoin(resp.final_url, link.get("href", ""))
    text = clean_text(node.get_text(" "))
    date_match = re.search(r"((?:19|20)\d{2})[./年]\s*(\d{1,2})[./月]\s*(\d{1,2})日?", text)
    published = None
    if date_match:
        try:
            published = dt.date(*map(int, date_match.groups())).isoformat()
        except ValueError:
            pass
    author_el = node.select_one(author_selector) if author_selector else None
    author = clean_text(author_el.get_text(" ")) if author_el else None
    if not author:
        split = re.match(r"^(.+?)\s*[｜|]\s*.+$", title)
        author = clean_text(split.group(1)) if split else None
    db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=url, title=title,
                      published_at=published, author_text=author or None, publisher=publisher,
                      owner_group=publisher, article_type=article_type, type_basis=category,
                      lang="ja", categories=category, excerpt=None)
    image = _image_url(node, resp.final_url)
    if image:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown",
                            basis=ctx.meta.get("st_image_terms", "no reuse licence observed"),
                            page_url=url, image_url=image)
    ctx.count("parsed")


def _artscape(ctx):
    url = ctx.meta["entry_url"]
    cutoff = "2025-04-01"
    pages = 0
    while url and pages < (20 if ctx.mode == "initial" else 1):
        resp = ctx.fetch(url)
        s = soup(resp.text)
        rows = s.select("article.item-article")
        ctx.count("fetched", len(rows))
        oldest = None
        for row in rows:
            title = next((a for a in row.select("a[href*='/article/']") if clean_text(a.get_text(" "))), None)
            _media_article(ctx, resp=resp, node=row, title_el=title, article_type="review",
                           category="レビュー", publisher="artscape",
                           author_selector=".author, .item-article-author")
            text = clean_text(row.get_text(" "))
            m = re.search(r"(?:19|20)\d{2}[.]\d{1,2}[.]\d{1,2}", text)
            if m:
                pub = _jp_dates(m.group(0))[0]
                if pub and (oldest is None or pub < oldest):
                    oldest = pub
        ctx.con.commit()
        pages += 1
        if ctx.mode != "initial" or not rows or (oldest and oldest < cutoff):
            break
        nxt = s.select_one("a.next, a.next.page-numbers, a[rel='next']")
        url = urllib.parse.urljoin(resp.final_url, nxt["href"]) if nxt else None
    ctx.note("artscape: review listing metadata only (title, URL, visible publication date/category/author when present); "
             "no article body fetched; initial follows visible next-page links until 2025-04 or request cap.")


def _aica(ctx):
    base = ctx.meta["entry_url"].rstrip("/")
    cutoff = "2025-04-01"
    page = 1
    while page <= (40 if ctx.mode == "initial" else 1):
        url = base if page == 1 else f"{base}/page/{page}"
        resp = ctx.fetch(url)
        s = soup(resp.text)
        rows = s.select(".post-entry-content-wrapper")
        ctx.count("fetched", len(rows))
        oldest = None
        for row in rows:
            title = row.select_one("h3.image-post-title a[href]")
            _media_article(ctx, resp=resp, node=row, title_el=title, article_type="review",
                           category="展覧会評", publisher="美術評論＋",
                           author_selector=".jl_post_meta a")
            m = re.search(r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日", clean_text(row.get_text(" ")))
            if m:
                pub = _jp_dates(m.group(0))[0]
                if pub and (oldest is None or pub < oldest):
                    oldest = pub
        ctx.con.commit()
        if ctx.mode != "initial" or not rows or (oldest and oldest < cutoff):
            break
        if not s.select_one(".jellywp_pagination a.next.page-numbers"):
            break
        page += 1
    ctx.note("美術評論＋: official exhibition-review category listing only; metadata retained, article bodies not fetched; "
             "initial pagination stops at 2025-04, incremental reads page 1.")
