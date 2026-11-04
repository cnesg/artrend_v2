"""Wave 2 gallery rosters, exhibitions and bounded public press/publication metadata."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .. import db
from ._common import classify_subtype, clean_text, parse_date_range, split_title_artist

PARSER_VERSION = "wave2_galleries-2"

# Route choices come from the saved official pages in work/dev/26-W2Galleries.
_GALLERIES = {
    "wave2_marian_goodman": dict(name="Marian Goodman Gallery", base="https://www.mariangoodman.com",
        region="AMERICAS", countries="US,FR,GB", roster="/artists/", entry="/exhibitions/",
        terms="/terms-and-conditions/", current=["/exhibitions/", "/exhibitions/all/forthcoming/"],
        initial=["/exhibitions/all/past/2025/"],
        history="current/forthcoming plus a 2025 archive page"),
    "wave2_mendes_wood_dm": dict(name="Mendes Wood DM", base="https://mendeswooddm.com",
        region="AMERICAS", countries="BR", roster="/artists/", entry="/exhibitions/", terms=None,
        current=["/exhibitions/"], initial=["/exhibitions/year/2026", "/exhibitions/year/2025"],
        history="current listing and year archives (2026 and 2025 captured)"),
    "wave2_galeria_vermelho": dict(name="Galeria Vermelho", base="https://galeriavermelho.com.br",
        region="AMERICAS", countries="BR", roster="/artistas/", entry="/exposicoes/", terms=None,
        current=["/exposicoes/"], initial=["/arquivo-exposicoes/2026"],
        history="current exhibition page and a 2026 archive route"),
    "wave2_kurimanzutto": dict(name="kurimanzutto", base="https://www.kurimanzutto.com",
        region="AMERICAS", countries="MX,US", roster="/artists", entry="/exhibitions", terms=None,
        current=["/exhibitions"], initial=["/exhibitions/past/mexico", "/exhibitions/past/new-york"],
        history="current listing and official city-filtered past exhibition links"),
    "wave2_omr": dict(name="OMR", base="https://omr.art", region="AMERICAS", countries="MX",
        roster="/artists", entry="/exhibitions", terms=None, current=["/exhibitions", "/upcoming-exhibitions"],
        initial=["/past-exhibitions"], history="current/upcoming plus past exhibition listings"),
    "wave2_galerie_uqam": dict(name="Galerie de l’UQAM", base="https://galerie.uqam.ca",
        region="AMERICAS", countries="CA", roster=None, entry="/expositions/", terms=None,
        current=["/statut/en-cours/", "/statut/a-venir/"], initial=["/statut/archives/"],
        detail_date_selector="p.date", detail_limit={"initial": 40, "incremental": 10},
        history="status pages list undated cards; printed dates read from bounded official detail pages "
                "(observed p.date, 2026-10-28); separate artist roster not evidenced"),
    "wave2_esther_schipper": dict(name="Esther Schipper", base="https://www.estherschipper.com",
        region="EUROPE", countries="DE,FR,GB,KR", roster="/artists/", entry="/exhibitions/",
        terms=None, current=["/exhibitions/", "/exhibitions/upcoming/"],
        initial=["/exhibitions/search/?filter=1&years=2025"], history="current/upcoming plus a 2025 archive/search page"),
    "wave2_sprueth_magers": dict(name="Sprüth Magers", base="https://spruethmagers.com",
        region="EUROPE", countries="DE,GB,US", roster="/artists/", entry="/exhibitions/",
        terms=None, current=["/exhibitions/", "/exhibitions/upcoming/"], initial=["/exhibitions/past/"],
        history="current/upcoming/past pages and an official sitemap"),
    "wave2_crousel": dict(name="Galerie Chantal Crousel", base="https://www.crousel.com",
        region="EUROPE", countries="FR", roster="/en/artists/", entry="/en/exhibitions/",
        terms="/en/legal-notices/", current=["/en/exhibitions/"], initial=[],
        history="English exhibitions listing; captured archive route returned only a minimal page"),
    "wave2_ota_fine_arts": dict(name="Ota Fine Arts", base="https://www.otafinearts.com",
        region="JP", countries="JP,SG,CN", roster="/artists/list/", entry="/exhibitions/",
        terms="/privacy-policy/", current=["/exhibitions/", "/exhibitions/location/1/", "/exhibitions/location/2/",
                                             "/exhibitions/location/3/", "/exhibitions/location/4/"],
        initial=["/exhibitions/year/2026/", "/exhibitions/year/2025/"],
        history="current listing plus official year archives; 2025/2026 pages captured"),
    "wave2_misako_rosen": dict(name="MISAKO & ROSEN", base="https://misakoandrosen.jp",
        region="JP", countries="JP", roster="/en/", entry="/wp-sitemap-posts-exhibitions-en-1.xml",
        terms=None, current=[], initial=[], sitemap=True,
        history="WordPress exhibition sitemap exposes dated exhibition detail URLs"),
    "wave2_leeahn": dict(name="LEEAHN Gallery", base="https://www.leeahngallery.com",
        region="KR", countries="KR", roster="/artists/list", entry="/exhibitions/list",
        terms="/doc/policy", current=["/exhibitions/list"], initial=[],
        history="one official exhibition list includes current, upcoming and past year groups"),
    "wave2_johyun": dict(name="Johyun Gallery", base="https://www.johyungallery.com",
        region="KR", countries="KR", roster="/artists/", entry="/exhibitions/",
        terms=None, current=["/exhibitions/"], initial=["/exhibitions/archive/"],
        history="current listing with venue filters and a past archive page"),
    "wave2_gallery_baton": dict(name="Gallery Baton", base="https://www.gallerybaton.com",
        region="KR", countries="KR", roster="/artists/", entry="/exhibitions/",
        terms=None, current=["/exhibitions/"], initial=["/exhibitions/archive/"],
        history="current and archive listings; archive contains 2025 onward records"),
    "wave2_primary_practice": dict(name="Primary Practice", base="https://primarypractice.kr",
        region="KR", countries="KR", roster="/collaborators", entry="/en/exhibitions",
        terms=None, current=["/en/exhibitions"], initial=[],
        history="English exhibition listing includes 2025–2026 records; collaborators page is a listing, not representation evidence"),
    "wave2_ropac_roster": dict(name="Thaddaeus Ropac", base="https://ropac.net",
        region="EUROPE", countries="AT,FR,GB,KR,IT", roster="/artists/", entry="/artists/",
        terms=None, current=[], initial=[], history="official /artists page; exhibition records remain in ropac_exhibitions"),
    "wave2_lisson_roster": dict(name="Lisson Gallery", base="https://lisson.com",
        region="EUROPE", countries="GB,US,CN,IT,FR,ES,DE,AE", roster="/artists", entry="/artists",
        terms="/legal/terms-and-conditions", current=[], initial=[],
        history="official alphabetical /artists page; exhibition records remain in lisson_exhibitions"),
    "wave2_ropac_news_publications": dict(name="Thaddaeus Ropac", base="https://ropac.net",
        region="EUROPE", countries="AT,FR,GB,KR,IT", roster=None, entry="/news/", terms=None,
        current=[], initial=[], article_routes=[("/news/", "news")], publication_route="/publications/",
        history="official News & Events page and paginated new-release/publications list"),
    "wave2_lisson_news_journal": dict(name="Lisson Gallery", base="https://lisson.com",
        region="EUROPE", countries="GB,US,CN,IT,FR,ES,DE,AE", roster=None, entry="/news",
        terms="/legal/terms-and-conditions", current=[], initial=[],
        article_routes=[("/news", "news"), ("/journal", "journal")],
        history="official News and Journal listing cards; current listing metadata only"),
    "wave2_david_zwirner_press_books": dict(name="David Zwirner", base="https://www.davidzwirner.com",
        region="AMERICAS", countries="US,GB,FR,HK", roster=None, entry="/press",
        terms="/terms-and-conditions", current=[], initial=[], article_routes=[("/press", "press")],
        publication_route="/collect/books",
        history="official Press Room release cards and All Books catalogue listing; metadata only"),
}

_NO_TERMS = "terms not located in saved evidence; raw HTML remains internal and Fetcher enforces robots"
SOURCES = []
for _source_id, _spec in _GALLERIES.items():
    _terms_url = urllib.parse.urljoin(_spec["base"] + "/", _spec["terms"]) if _spec["terms"] else None
    _collection_terms = _NO_TERMS
    if _source_id == "wave2_marian_goodman":
        _collection_terms = ("Reviewed terms prohibit commercial/promotional distribution, publication or exploitation absent written permission; "
                             "no robot clause recorded in saved excerpt. No images; content retained internally only.")
    elif _source_id == "wave2_crousel":
        _collection_terms = "Saved legal notice restricts reproduction/circulation of site elements; no robot clause recorded; only internal event/roster metadata is parsed."
    elif _source_id == "wave2_ota_fine_arts":
        _collection_terms = "Saved privacy-policy page reserves copyright and restricts secondary use; no separate crawler terms reviewed; no images or descriptive copy are collected."
    elif _source_id in {"wave2_lisson_roster", "wave2_lisson_news_journal"}:
        _collection_terms = "Existing lisson_exhibitions source records reviewed terms with no robot/text-mining clause."
    elif _source_id == "wave2_david_zwirner_press_books":
        _collection_terms = ("Existing davidzwirner_exhibitions row records personal/non-commercial use only and prohibits copying, distributing or exploiting website content; "
                             "only listing metadata is collected and raw HTML remains internal.")
    if _source_id in {"wave2_ropac_roster", "wave2_lisson_roster"}:
        _source_name = f"{_spec['name']} — artist roster"
    elif _source_id == "wave2_ropac_news_publications":
        _source_name = f"{_spec['name']} — News & publications"
    elif _source_id == "wave2_lisson_news_journal":
        _source_name = f"{_spec['name']} — News & Journal"
    elif _source_id == "wave2_david_zwirner_press_books":
        _source_name = f"{_spec['name']} — Press & books"
    else:
        _source_name = f"{_spec['name']} — artists and exhibitions"
    SOURCES.append(dict(
        source_id=_source_id, blueprint_data_id=None, blueprint_org_id=None,
        name=_source_name, owner_group=_spec["name"],
        source_kind="gallery", region_scope=_spec["region"], country_codes=_spec["countries"],
        access_method="html", base_url=_spec["base"],
        entry_url=urllib.parse.urljoin(_spec["base"] + "/", _spec["entry"]),
        terms_url=_terms_url, text_storage_policy="raw_internal", priority="P1",
        st_official_doc="n/a(public HTML)", st_collection_terms=_collection_terms,
        st_image_terms="No open image licence established; images are not collected.",
        max_requests=150 if _spec.get("sitemap") else (100 if _spec.get("article_routes") else 240),
        notes=f"Saved markup source: work/dev/26-W2Galleries; history: {_spec['history']}"))

_DATE = re.compile(
    r"(?:\b20\d{2}[./-]\d{1,2}(?:[./-]\d{1,2})?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|"
    r"novembre|décembre|decembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"setiembre|septiembre|outubro|janeiro|fevereiro|março|marco|setembro|ottobre|gennaio)"
    r"\.?\s+\d{1,2}[^\n]{0,45}20\d{2}\b|"
    r"\b\d{1,2}\s+(?:de\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|"
    r"novembre|décembre|decembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"setiembre|septiembre|outubro|janeiro|fevereiro|março|marco|setembro|ottobre|gennaio)"
    r"[^\n]{0,45}20\d{2}\b|\b20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"\b20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)", re.I)

_CITY_CODES = {
    "são paulo": ("São Paulo", "BR"), "sao paulo": ("São Paulo", "BR"), "rio de janeiro": ("Rio de Janeiro", "BR"),
    "mexico city": ("Mexico City", "MX"), "ciudad de méxico": ("Mexico City", "MX"), "new york": ("New York", "US"),
    "los angeles": ("Los Angeles", "US"), "hudson": ("Hudson", "US"), "paris": ("Paris", "FR"),
    "london": ("London", "GB"), "berlin": ("Berlin", "DE"), "brussels": ("Brussels", "BE"),
    "bruges": ("Bruges", "BE"), "seoul": ("Seoul", "KR"), "busan": ("Busan", "KR"),
    "daegu": ("Daegu", "KR"), "tokyo": ("Tokyo", "JP"), "singapore": ("Singapore", "SG"),
    "shanghai": ("Shanghai", "CN"), "hong kong": ("Hong Kong", "HK"), "charlottetown": ("Charlottetown", "CA"),
    "vienna": ("Vienna", "AT"), "salzburg": ("Salzburg", "AT"), "pantin": ("Pantin", "FR"),
    "milan": ("Milan", "IT"), "milano": ("Milan", "IT"), "copenhagen": ("Copenhagen", "DK"),
    "new delhi": ("New Delhi", "IN"), "rome": ("Rome", "IT"), "lisbon": ("Lisbon", "PT"),
}


def _soup(html):
    return BeautifulSoup(html or "", "lxml")


def _has_dated_line(text):
    return bool(_DATE.search(clean_text(text)))


def _date_lines(node):
    lines = []
    for raw in node.stripped_strings:
        line = clean_text(raw)
        if not line:
            continue
        # <sup>th</sup> and similar markup split one printed date into fragments: 'October 19', 'th', '— November 21'.
        if lines and (re.fullmatch(r"(?:st|nd|rd|th|er)\b.*", line) or line[0] in ",—–-"):
            lines[-1] = lines[-1] + " " + line
        else:
            lines.append(line)
    found = []
    for line in lines:
        # Prose paragraphs mention other dates (openings, past venues); they are not the printed period.
        if len(line) > 120 or not _has_dated_line(line) or line in found:
            continue
        found.append(line)
        if len(found) == 1 and parse_date_range(line)[2]:
            break  # the first printed line is already a complete range
        if len(found) == 2:
            break
    return " – ".join(found) if found else None


def _detail_url(source_id, url):
    path = urllib.parse.urlsplit(url).path.rstrip("/").lower()
    parts = [x for x in path.split("/") if x]
    if source_id == "wave2_galeria_vermelho":
        return len(parts) == 2 and parts[0] == "exposicoes" and parts[1] not in {"arquivo", "all"}
    if source_id == "wave2_omr":
        return len(parts) == 2 and parts[0] == "exhibitions-gallery"
    if source_id == "wave2_crousel":
        return len(parts) == 3 and parts[:2] == ["en", "exhibition"]
    if source_id == "wave2_misako_rosen":
        return len(parts) >= 2 and parts[0] == "exhibitions-en"
    if source_id == "wave2_leeahn":
        return False
    if source_id == "wave2_primary_practice":
        return len(parts) >= 3 and parts[-2] == "exhibitions"
    if "exhibitions" not in parts and "expositions" not in parts:
        return False
    index = max((parts.index(x) for x in ("exhibitions", "expositions") if x in parts), default=-1)
    if index < 0 or index + 1 >= len(parts):
        return False
    slug = parts[index + 1]
    if slug in {"all", "current", "upcoming", "past", "archive", "archives", "year", "location", "category", "search", "new-york", "paris", "online", "london", "los-angeles"}:
        return False
    if slug.isdigit() or re.fullmatch(r"20\d{2}", slug):
        return False
    return True


def _event_card(anchor, source_id):
    for node in [anchor, *anchor.parents]:
        if getattr(node, "name", None) not in {"a", "li", "article", "section", "div", "figure"}:
            continue
        if node.find_parent(["nav", "header", "footer"]):
            continue
        text = clean_text(node.get_text(" "))
        if len(text) > 1600 or not _has_dated_line(text):
            continue
        links = {urllib.parse.urljoin("https://example.invalid", a.get("href", "")) for a in node.select("a[href]")
                 if _detail_url(source_id, urllib.parse.urljoin("https://example.invalid", a["href"]))}
        if len(links) <= 2:
            return node
    return None


def _title_from_card(node, anchor):
    title_node = node.select_one(".page-title.ital")
    if title_node and not title_node.find_parent(class_="w-condition-invisible"):
        title = clean_text(title_node.get_text(" "))
        if title:
            return title
    for heading in node.select("h1, h2, h3, h4"):
        title = clean_text(heading.get_text(" "))
        if title and not _has_dated_line(title) and len(title) < 180:
            return title
    strong = node.find(["strong", "b"])
    if strong:
        title = clean_text(strong.get_text(" "))
        if title and len(title) < 180:
            return title
    text = clean_text(anchor.get_text(" "))
    if text:
        return text[:180]
    return None


def _card_artists(node, source_id):
    if source_id != "wave2_omr":
        return []
    names = []
    for artist in node.select(".page-title.ingrid:not(.ital):not(.subtitle)"):
        name = clean_text(artist.get_text(" "))
        if name and name not in names:
            names.append(name)
    for artist in node.select(".collective-artists-ingrid .w-dyn-item"):
        name = clean_text(artist.get_text(" "))
        if name and name.casefold() != "no items found" and name not in names:
            names.append(name)
    return names


def _venue(node, title, date_text):
    title_key = clean_text(title).casefold()
    for raw in node.stripped_strings:
        line = clean_text(raw)
        if not line or line == date_text or line.casefold() == title_key or len(line) > 100 or _has_dated_line(line):
            continue
        for segment in re.split(r"[|·]", line.casefold()):
            segment = segment.strip()
            for key in sorted(_CITY_CODES, key=len, reverse=True):
                location_shape = (r"^(?:[^,|]{1,50},\s*){0,2}" + re.escape(key) +
                                  r"(?:,\s*[^,|]{1,50}){0,2}$")
                if re.fullmatch(location_shape, segment, re.I):
                    city, cc = _CITY_CODES[key]
                    return city, cc
    return None, None


def _visible_images(node, page_url):
    urls = set()
    for image in node.select("img, source"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "srcset"):
            value = image.get(attr)
            if not value:
                continue
            for candidate in value.split(",") if attr == "srcset" else [value]:
                candidate = candidate.strip().split()[0] if candidate.strip() else ""
                if candidate and not candidate.startswith("data:"):
                    urls.add(urllib.parse.urljoin(page_url, candidate))
    return sorted(urls)


def parse_exhibition_cards(html, source_id, page_url):
    """Read exhibition cards only when the official markup supplies a title and a dated line."""
    page = _soup(html)
    found = {}
    for anchor in page.select("a[href]"):
        href = urllib.parse.urljoin(page_url, anchor.get("href", ""))
        if not _detail_url(source_id, href):
            continue
        base_host = urllib.parse.urlsplit(_GALLERIES[source_id]["base"]).netloc.lower().removeprefix("www.")
        link_host = urllib.parse.urlsplit(href).netloc.lower().removeprefix("www.")
        if link_host != base_host:
            continue
        card = _event_card(anchor, source_id)
        if card is None:
            continue
        title = _title_from_card(card, anchor)
        date_text = _date_lines(card)
        if not title or not date_text:
            continue
        start, start_precision, end, end_precision = parse_date_range(date_text)
        city, country_code = _venue(card, title, date_text)
        record = dict(url=href, page_url=page_url, title=title, date_text=date_text, start_date=start,
                      start_precision=start_precision, end_date=end, end_precision=end_precision,
                      city=city, country_code=country_code)
        artists = _card_artists(card, source_id)
        if source_id == "wave2_crousel" and card.select_one("figcaption h3"):
            # Crousel cards print the artist line in h2 and the exhibition title in h3.
            title = clean_text(card.select_one("figcaption h3").get_text(" ")) or title
            heading = card.select_one("figcaption h2")
            line = clean_text(heading.get_text(" ")) if heading else ""
            if line and line.casefold() not in {"group exhibition", "group show"}:
                artists = [name for name in (clean_text(x) for x in line.split(",")) if name]
            record["title"] = title
        if artists:
            record["artists"] = artists
        images = _visible_images(card, page_url)
        if images:
            record["images"] = images
        found[href] = record

    # Some official lists (notably Leeahn) render dated rows without a per-event URL.
    if source_id == "wave2_leeahn":
        for row in page.select("li.w25"):
            date_text = _date_lines(row)
            if not date_text:
                continue
            title = _title_from_card(row, row)
            if not title:
                info = row.select_one(".info")
                title = clean_text(info.strong.get_text(" ")) if info and info.strong else None
            if not title:
                continue
            start, start_precision, end, end_precision = parse_date_range(date_text)
            city, country_code = _venue(row, title, date_text)
            key = f"{page_url}#{title}|{date_text}"
            record = dict(url=page_url, page_url=page_url, title=title, date_text=date_text, start_date=start,
                          start_precision=start_precision, end_date=end, end_precision=end_precision,
                          city=city, country_code=country_code)
            images = _visible_images(row, page_url)
            if images:
                record["images"] = images
            found[key] = record
    return list(found.values())


def parse_roster(html, source_id, page_url):
    """Return only names explicitly listed in the official artist/collaborator roster markup."""
    page = _soup(html)
    names = {}
    if source_id == "wave2_omr":
        anchors = []
        for node in page.select(".artist-item .artist-name-ingrid"):
            name = clean_text(node.get_text(" "))
            if name:
                item = {"name": name, "url": None}
                card = node.find_parent(class_="artist-item") or node
                images = _visible_images(card, page_url)
                if images:
                    item["images"] = images
                names[name] = item
    elif source_id == "wave2_leeahn":
        anchors = page.select(".artists-wrap ul.list a")
        for anchor in anchors:
            name = clean_text(anchor.get_text(" "))
            if name and len(name) <= 120:
                card = anchor.find_parent("li") or anchor
                item = {"name": name, "url": None}
                images = _visible_images(card, page_url)
                if images:
                    item["images"] = images
                names[name] = item
        return list(names.values())
    else:
        anchors = page.select("a[href]")

    for anchor in anchors:
        name = clean_text(anchor.get_text(" "))
        if not name or len(name) > 120 or name.casefold() in {"artists", "artist", "list", "thumbnails", "english", "en", "ko", "fr", "ja"}:
            continue
        if source_id != "wave2_omr":
            href = urllib.parse.urljoin(page_url, anchor.get("href", ""))
            parts = [p for p in urllib.parse.urlsplit(href).path.rstrip("/").lower().split("/") if p]
            marker = next((i for i, part in enumerate(parts) if part in {"artist", "artists", "artists-en", "artist-en", "artista", "artistas", "artiste", "artistes", "collaborators"}), None)
            if marker is None or marker + 1 >= len(parts):
                continue
            link_host = urllib.parse.urlsplit(href).netloc.lower().removeprefix("www.")
            page_host = urllib.parse.urlsplit(page_url).netloc.lower().removeprefix("www.")
            if link_host not in {"", page_host}:
                continue
            card = anchor
            for parent in anchor.parents:
                if parent.name in {"li", "article", "section", "div"} and len(clean_text(parent.get_text(" "))) < 350:
                    card = parent
                    break
            item = {"name": name, "url": href}
            images = _visible_images(card, page_url)
            if images:
                item["images"] = images
            names[name] = item
    return list(names.values())


def _artist_entity(ctx, name, url, evidence_id):
    group = bool(re.search(r"\b(collective|duo|trio)\b|\s&\s|\band\b", name, re.I))
    namespace = f"src:{ctx.source_id}"
    id_value = None
    if url:
        parts = [part for part in urllib.parse.urlsplit(url).path.rstrip("/").lower().split("/") if part]
        marker = next((i for i, part in enumerate(parts)
                       if part in {"artist", "artists", "artist-en", "artists-en", "artista", "artistas", "artiste", "artistes", "collaborators"}), None)
        if marker is not None and marker + 1 < len(parts):
            namespace = f"{ctx.source_id}_artist"
            id_value = parts[marker + 1]
    else:
        existing = ctx.con.execute("SELECT entity_id FROM entities WHERE id_namespace=? AND canonical_name=? LIMIT 1",
                                   (f"{ctx.source_id}_artist", name)).fetchone()
        if existing:
            return existing[0]
    return db.ensure_entity(ctx.con, entity_type="group" if group else "person", name=name,
                            namespace=namespace, id_value=id_value, source_id=ctx.source_id,
                            evidence_id=evidence_id, official_url=url)


def _collect_roster(ctx, org, spec):
    if not spec.get("roster"):
        return 0
    url = urllib.parse.urljoin(spec["base"] + "/", spec["roster"])
    resp = ctx.fetch(url)
    roster = parse_roster(resp.text, ctx.source_id, resp.url)
    evidence_id = ctx.evidence(resp, locator="official artist/collaborator listing")
    for item in roster:
        artist_id = _artist_entity(ctx, item["name"], item["url"], evidence_id)
        db.upsert_relationship(ctx.con, subject_entity_id=org, object_entity_id=artist_id,
                               rel_type="listed_artist", source_id=ctx.source_id,
                               evidence_id=evidence_id, status="source_asserted")
        for image_url in item.get("images", []):
            db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown",
                                basis="No open image licence established; URL recorded from roster markup only; not downloaded.",
                                page_url=resp.url, image_url=image_url, entity_id=artist_id)
        ctx.count("roster")
    ctx.note(f"official roster page listed {len(roster)} names; recorded as listed_artist, not representation")
    ctx.con.commit()
    return len(roster)


def _store_event(ctx, org, item, evidence_id):
    title = clean_text(item["title"])
    key = item.get("key") or item["url"]
    event_id = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key,
        event_type="exhibition", subtype=classify_subtype(title), title=title, parser_version=PARSER_VERSION,
        organizer_entity_id=org, city=item.get("city"), country_code=item.get("country_code"),
        start_date=item.get("start_date"), start_precision=item.get("start_precision"),
        end_date=item.get("end_date"), end_precision=item.get("end_precision"), date_text=item.get("date_text"),
        url=item["url"], evidence_id=evidence_id)
    artists = item.get("artists")
    if not artists:
        title_artist = split_title_artist(title)
        artists = [title_artist] if title_artist else []
    for artist_name in dict.fromkeys(artists):
        artist_id = _artist_entity(ctx, artist_name, None, evidence_id)
        db.add_participant(ctx.con, event_id, artist_id, role="artist", name_as_listed=artist_name,
                           evidence_id=evidence_id,
                           extraction_method="list_markup" if item.get("artists") else "title_pattern",
                           confidence="high" if item.get("artists") else "medium")
    if not item.get("country_code"):
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown",
                      detail=f"No explicit actual venue country in listing: {item['url']}")
    for image_url in item.get("images", []):
        db.add_image_rights(ctx.con, source_id=ctx.source_id, usage_status="unknown",
                            basis="No open image licence established; URL recorded from exhibition markup only; not downloaded.",
                            page_url=item.get("page_url", item["url"]), image_url=image_url, event_id=event_id)
    ctx.count("parsed")


def _routes(spec, mode):
    return list(spec["current"]) + (list(spec["initial"]) if mode == "initial" else [])


def _undated_detail_links(html, source_id, page_url, base):
    host = urllib.parse.urlsplit(base).netloc.lower().removeprefix("www.")
    links = []
    for anchor in _soup(html).select("a[href]"):
        href = urllib.parse.urljoin(page_url, anchor.get("href", "")).split("#", 1)[0]
        if urllib.parse.urlsplit(href).netloc.lower().removeprefix("www.") != host:
            continue
        if _detail_url(source_id, href) and href not in links:
            links.append(href)
    return links


def _collect_listings(ctx, org, spec):
    seen = set()
    rows = 0
    detail_queue = []
    for route in _routes(spec, ctx.mode):
        url = urllib.parse.urljoin(spec["base"] + "/", route)
        resp = ctx.fetch(url)
        items = parse_exhibition_cards(resp.text, ctx.source_id, resp.url)
        if not items and spec.get("detail_date_selector"):
            detail_queue.extend(u for u in _undated_detail_links(resp.text, ctx.source_id, resp.url, spec["base"])
                                if u not in detail_queue)
            continue
        ctx.count("fetched", len(items))
        for item in items:
            key = item["url"]
            if key in seen:
                continue
            seen.add(key)
            evidence_id = ctx.evidence(resp, locator=f"exhibition listing card: {item['title']}", excerpt=item["date_text"])
            item["key"] = item["url"]
            _store_event(ctx, org, item, evidence_id)
            rows += 1
        ctx.con.commit()
        if not items:
            ctx.note(f"no dated exhibition cards parsed from {url}")
    if detail_queue:
        rows += _collect_detail_dates(ctx, org, spec, detail_queue)
    ctx.note(f"history exposed by saved official markup: {spec['history']}; parsed {rows} exhibition records")


def _collect_detail_dates(ctx, org, spec, urls):
    """Fetch listed detail pages (bounded) when the official listing cards print no dates."""
    limit = spec["detail_limit"][ctx.mode]
    pending = [u for u in urls if ctx.mode == "incremental" or ctx.con.execute(
        "SELECT 1 FROM events WHERE event_id=?", (db.sid("evt", ctx.source_id, u),)).fetchone() is None]
    rows = 0
    for url in pending[:limit]:
        resp = ctx.fetch(url)
        ctx.count("fetched")
        item = _detail_record(resp.text, resp.url, date_selector=spec["detail_date_selector"])
        if item is None:
            ctx.note(f"detail page has no printed title/date in {spec['detail_date_selector']}; skipped {url}")
            continue
        evidence_id = ctx.evidence(resp, locator=f"exhibition title and {spec['detail_date_selector']}",
                                   excerpt=item["date_text"])
        _store_event(ctx, org, item, evidence_id)
        ctx.con.commit()
        rows += 1
    ctx.note(f"listing cards were undated; {len(urls)} listed detail URLs, {len(pending)} pending, "
             f"read {min(len(pending), limit)} (cap {limit}/{ctx.mode} run); remaining details are not exhausted"
             if len(pending) > limit else
             f"listing cards were undated; read {len(pending)} of {len(urls)} listed detail URLs")
    return rows


def _sitemap_urls(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    return [clean_text(node.text) for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "loc" and clean_text(node.text)]


def _detail_record(html, url, date_selector=None):
    page = _soup(html)
    title = None
    for node in page.select("h1"):
        candidate = clean_text(node.get_text(" "))
        if candidate and candidate.casefold() not in {"exhibitions", "expositions"}:
            title = candidate
            break
    if not title:
        title_node = page.select_one('meta[property="og:title"]')
        title = clean_text(title_node.get("content")) if title_node else None
    if date_selector:
        node = page.select_one(date_selector)
        date_text = clean_text(node.get_text(" ")) if node else None
    else:
        date_text = _date_lines(page)
    if not title or not date_text:
        return None
    start, start_precision, end, end_precision = parse_date_range(date_text)
    city, country_code = _venue(page, title, date_text)
    item = dict(url=url, page_url=url, title=title, date_text=date_text, start_date=start,
                start_precision=start_precision, end_date=end, end_precision=end_precision,
                city=city, country_code=country_code, key=url)
    images = _visible_images(page, url)
    if images:
        item["images"] = images
    return item


def _collect_misako_sitemap(ctx, org, spec):
    sitemap_url = urllib.parse.urljoin(spec["base"] + "/", spec["entry"])
    sitemap = ctx.fetch(sitemap_url, accept="application/xml")
    urls = [u for u in _sitemap_urls(sitemap.content) if "/exhibitions-en/" in urllib.parse.urlsplit(u).path]
    if ctx.mode == "initial":
        urls = [u for u in urls if re.search(r"/25/(?:0[4-9]|1[0-2])(?:/|$)|/26/|/2025/|/2026/", urllib.parse.urlsplit(u).path)]
        limit = 115
    else:
        urls = [u for u in urls if re.search(r"/26/|/2026/", urllib.parse.urlsplit(u).path)]
        limit = 32
    urls = list(dict.fromkeys(urls))[:limit]
    ctx.count("fetched", len(urls))
    today_cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    for url in urls:
        event_id = db.sid("evt", ctx.source_id, url)
        row = ctx.con.execute("SELECT end_date FROM events WHERE event_id=?", (event_id,)).fetchone()
        if ctx.mode == "incremental" and row and row[0] and row[0] < today_cutoff:
            continue
        resp = ctx.fetch(url)
        item = _detail_record(resp.text, resp.url)
        if item is None:
            ctx.note(f"detail page has no extractable title/date; skipped {url}")
            continue
        evidence_id = ctx.evidence(resp, locator="exhibition title and printed date", excerpt=item["date_text"])
        _store_event(ctx, org, item, evidence_id)
        ctx.con.commit()
    ctx.note("WordPress exhibition sitemap exposed dated details; initial pass bounded to 2025-04 onward, incremental to 2026 URLs")


_LISSON_CARD_CATEGORIES = {
    "event", "exhibition", "fair", "gallery exhibition", "museum exhibition", "podcast", "studio",
}


def _published_date(text):
    start, precision, _, _ = parse_date_range(text)
    return start if precision == "day" else None


def _lisson_article(anchor, page_url, menu):
    parts = list(dict.fromkeys(clean_text(text) for text in anchor.stripped_strings if clean_text(text)))
    if not parts:
        image = anchor.find("img")
        alt = clean_text(image.get("alt")) if image else ""
        if alt:
            parts = [alt]
    if not parts:
        return None
    date_text = next((part for part in parts if _has_dated_line(part)), None)
    category = next((part for part in parts if part.casefold() in _LISSON_CARD_CATEGORIES), None)
    title_parts = [part for part in parts if part != date_text and part != category]
    title = clean_text(" ".join(title_parts))
    if not title:
        return None
    url = urllib.parse.urljoin(page_url, anchor.get("href", ""))
    return dict(url=url, title=title, date_text=date_text, published_at=_published_date(date_text),
                categories=category or menu, article_type="news" if menu == "news" else "unknown",
                type_basis=f"official Lisson {menu} listing card")


def parse_gallery_articles(html, source_id, page_url, menu):
    """Read official gallery press/news/journal metadata without opening linked bodies."""
    page = _soup(html)
    records = {}
    if source_id == "wave2_ropac_news_publications":
        anchors = page.select('a[href^="/news/"]') if menu == "news" else []
        for anchor in anchors:
            if not re.match(r"^/news/\d+-", anchor.get("href", "")):
                continue
            card = anchor.find_parent(class_="content_header") or anchor
            prelude = card.select_one(".prelude")
            date_node = card.select_one(".prelude_dates")
            date_text = clean_text(date_node.get_text(" ")) if date_node else None
            category = clean_text(prelude.get_text(" ")) if prelude else None
            if date_text and category:
                category = clean_text(category.replace(date_text, " "))
            heading = card.select_one(".h1_heading")
            subtitle = card.select_one(".h1_subtitle")
            title = clean_text(heading.get_text(" ")) if heading else clean_text(anchor.get_text(" "))
            if subtitle:
                title = f"{title}: {clean_text(subtitle.get_text(' '))}"
            if not title:
                continue
            url = urllib.parse.urljoin(page_url, anchor["href"])
            # Press features and artist news print a publication date; exhibition/event/biennale/project cards
            # print the event period (observed future dates, 2026-10-28), which is not a publication date.
            label = (category or "").casefold()
            dated_publication = label.startswith("featured in") or "news" in label
            published = _published_date(date_text) if dated_publication else None
            # 'Artists' News' cards can also print an upcoming event day (observed 2026-10-30: '5 November 2026');
            # a date after the listing was read cannot be when the item was published.
            if published and published[:10] > dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat():
                published = None
            records[url] = dict(url=url, title=title, date_text=date_text, published_at=published,
                                categories=category or "news & events",
                                article_type="news", type_basis="official Ropac News & Events listing card")
    elif source_id == "wave2_david_zwirner_press_books":
        base_host = urllib.parse.urlsplit(page_url).netloc.lower()
        for anchor in page.select("a[href]"):
            url = urllib.parse.urljoin(page_url, anchor.get("href", ""))
            parsed = urllib.parse.urlsplit(url)
            path = parsed.path.lower()
            is_press_release = path.endswith("/press-release")
            is_news = path.startswith("/news/")
            if not (is_press_release or is_news) or parsed.netloc.lower() != base_host:
                continue
            card = anchor.find_parent("div", class_="group") or anchor
            title_node = card.select_one('[data-testid="card-content-info-title"]')
            title = clean_text(title_node.get_text(" ")) if title_node else ""
            if not title:
                continue
            records[url] = dict(url=url, title=title, date_text=None, published_at=None,
                                categories="press release" if is_press_release else "news",
                                article_type="announcement" if is_press_release else "news",
                                type_basis="official David Zwirner Press Room listing card")
    else:
        expected = "/news/" if menu == "news" else "/journal/"
        base_host = urllib.parse.urlsplit(page_url).netloc.lower().removeprefix("www.")
        for anchor in page.select("a[href]"):
            url = urllib.parse.urljoin(page_url, anchor.get("href", ""))
            parsed = urllib.parse.urlsplit(url)
            path = parsed.path.lower()
            if not path.startswith(expected) or path.rstrip("/") == expected.rstrip("/"):
                continue
            if parsed.netloc.lower().removeprefix("www.") != base_host:
                continue
            item = _lisson_article(anchor, page_url, menu)
            if not item:
                continue
            old = records.get(item["url"])
            if old is None or (not old.get("published_at") and item.get("published_at")):
                records[item["url"]] = item
    return list(records.values())


def parse_ropac_publications(html, page_url):
    """Return dated/year-only public catalogue entries; prices and image markup are ignored."""
    page = _soup(html)
    found = {}
    for anchor in page.select('a[href^="/publications/"]'):
        href = anchor.get("href", "")
        if not re.search(r"/publications/\d+-[^/?#]+/?(?:\?|$)", href):
            continue
        card = anchor.find_parent("div", class_="item") or anchor
        title_node = card.select_one(".title")
        title = clean_text(title_node.get_text(" ")) if title_node else clean_text(anchor.get_text(" "))
        if not title:
            continue
        artist_node = card.select_one("h3")
        artist = clean_text(artist_node.get_text(" ")) if artist_node else None
        year = next((value for value in (clean_text(part) for part in card.stripped_strings)
                     if re.fullmatch(r"20\d{2}", value)), None)
        url = urllib.parse.urljoin(page_url, href)
        found[url] = dict(url=url, title=title, artist=artist, year=year)
    return list(found.values())


def parse_david_zwirner_publications(html, page_url):
    """Return linked book titles from the public catalogue; ignore prices and merchandise."""
    page = _soup(html)
    found = {}
    for anchor in page.select('a[href^="/collect/"]'):
        href = anchor.get("href", "")
        path = urllib.parse.urlsplit(href).path
        if not path.endswith("-book"):
            continue
        card = anchor.find_parent("div", class_="group") or anchor
        title_node = card.select_one('p[data-testid="heading"]')
        title = clean_text(title_node.get_text(" ")) if title_node else ""
        if not title:
            continue
        url = urllib.parse.urljoin(page_url, href)
        found[url] = dict(url=url, title=title, artist=None, year=None)
    return list(found.values())


def _next_listing_page(html, current_url):
    page = _soup(html)
    for anchor in page.select('a[rel="next"], a[href]'):
        label = clean_text(anchor.get_text(" ") or anchor.get("aria-label", "")).casefold()
        rel = " ".join(anchor.get("rel", [])).casefold() if isinstance(anchor.get("rel"), list) else str(anchor.get("rel", "")).casefold()
        if "next" not in rel and label not in {"next", "next page", "older", "older posts"}:
            continue
        url = urllib.parse.urljoin(current_url, anchor.get("href", ""))
        if urllib.parse.urlsplit(url).netloc.lower() == urllib.parse.urlsplit(current_url).netloc.lower():
            return url
    return None


def _collect_gallery_articles(ctx, spec):
    for route, menu in spec.get("article_routes", []):
        url = urllib.parse.urljoin(spec["base"] + "/", route)
        max_pages = 1 if ctx.mode == "incremental" else 10
        visited = set()
        for page_number in range(max_pages):
            if url in visited:
                break
            visited.add(url)
            resp = ctx.fetch(url)
            items = parse_gallery_articles(resp.text, ctx.source_id, resp.url, menu)
            ctx.count("fetched", len(items))
            for item in items:
                evidence = ctx.evidence(resp, locator=f"official {menu} listing card: {item['title']}",
                                        excerpt=item.get("date_text"))
                db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id,
                    canonical_url=item["url"], title=item["title"], published_at=item.get("published_at"),
                    publisher=spec["name"], owner_group=spec["name"], article_type=item["article_type"],
                    type_basis=item["type_basis"], categories=item["categories"], excerpt=None)
                ctx.count("parsed")
            ctx.con.commit()
            next_url = _next_listing_page(resp.text, resp.url)
            if ctx.mode != "initial" or not next_url:
                break
            url = next_url
        ctx.note(f"{menu}: walked {page_number + 1} page(s); listing metadata only, no article bodies fetched")


def _collect_ropac_publications(ctx, org, spec):
    url = urllib.parse.urljoin(spec["base"] + "/", spec["publication_route"])
    max_pages = 1 if ctx.mode == "incremental" else 15
    visited = set()
    oldest = None
    for page_number in range(max_pages):
        if url in visited:
            break
        visited.add(url)
        resp = ctx.fetch(url)
        items = parse_ropac_publications(resp.text, resp.url)
        ctx.count("fetched", len(items))
        for item in items:
            year = item["year"]
            if year:
                oldest = min(oldest or year, year)
            evidence = ctx.evidence(resp, locator=f"publication listing card: {item['title']}",
                                    excerpt=year or item["title"])
            event_id = db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id,
                source_event_key=item["url"], event_type="publication", title=item["title"],
                parser_version=PARSER_VERSION, organizer_entity_id=org,
                start_date=year, start_precision="year" if year else None,
                date_text=year, url=item["url"], evidence_id=evidence)
            if item.get("artist"):
                artist_id = _artist_entity(ctx, item["artist"], None, evidence)
                db.add_participant(ctx.con, event_id, artist_id, role="artist", name_as_listed=item["artist"],
                                   evidence_id=evidence, extraction_method="list_markup")
            ctx.count("parsed")
        ctx.con.commit()
        next_url = _next_listing_page(resp.text, resp.url)
        if ctx.mode != "initial" or not next_url or (oldest and oldest < "2023"):
            break
        url = next_url
    ctx.note(f"publications: walked {page_number + 1} page(s); oldest listed publication year {oldest or 'unknown'}")


def _collect_david_zwirner_publications(ctx, org, spec):
    url = urllib.parse.urljoin(spec["base"] + "/", spec["publication_route"])
    max_pages = 1 if ctx.mode == "incremental" else 10
    visited = set()
    for page_number in range(max_pages):
        if url in visited:
            break
        visited.add(url)
        resp = ctx.fetch(url)
        items = parse_david_zwirner_publications(resp.text, resp.url)
        ctx.count("fetched", len(items))
        for item in items:
            evidence = ctx.evidence(resp, locator=f"book listing card: {item['title']}", excerpt=item["title"])
            db.upsert_event(ctx.con, ctx.stats, source_id=ctx.source_id,
                source_event_key=item["url"], event_type="publication", title=item["title"],
                parser_version=PARSER_VERSION, organizer_entity_id=org, url=item["url"], evidence_id=evidence)
            ctx.count("parsed")
        ctx.con.commit()
        next_url = _next_listing_page(resp.text, resp.url)
        if ctx.mode != "initial" or not next_url:
            break
        url = next_url
    ctx.note(f"books: walked {page_number + 1} page(s); titles and listing URLs only; no product detail or image fetched")


def collect(ctx):
    spec = _GALLERIES.get(ctx.source_id)
    if spec is None:
        raise ValueError(f"wave2_galleries cannot collect {ctx.source_id}")
    org = db.ensure_entity(ctx.con, entity_type="gallery", name=spec["name"], namespace=f"src:{ctx.source_id}",
                           id_value="org", source_id=ctx.source_id,
                           official_url=spec["base"] + "/")
    if spec.get("article_routes"):
        _collect_gallery_articles(ctx, spec)
        if spec.get("publication_route"):
            if ctx.source_id == "wave2_ropac_news_publications":
                _collect_ropac_publications(ctx, org, spec)
            else:
                _collect_david_zwirner_publications(ctx, org, spec)
        ctx.con.commit()
        return
    _collect_roster(ctx, org, spec)
    if spec.get("sitemap"):
        _collect_misako_sitemap(ctx, org, spec)
    elif spec["current"]:
        _collect_listings(ctx, org, spec)
    else:
        ctx.note(f"official roster only; exhibition data remains in the existing source: {spec['history']}")
    ctx.con.commit()
