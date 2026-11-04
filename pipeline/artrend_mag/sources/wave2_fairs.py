"""Wave-2 fair and biennial editions grounded in the saved official public probes."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import db, region
from ..http import Blocked, FetchError
from ._common import clean_text, parse_date_range, soup

PARSER_VERSION = "wave2_fairs-2"


_NO_OPEN_IMAGE_LICENCE = "Images are not collected; no open image licence was observed."
def _row(source_id, name, owner, region, countries, base, entry, terms_url, terms, notes,
         source_kind="fair", **extra):
    row = dict(
        source_id=source_id,
        blueprint_data_id=None,
        blueprint_org_id=None,
        name=name,
        owner_group=owner,
        source_kind=source_kind,
        region_scope=region,
        country_codes=countries,
        access_method="html",
        base_url=base,
        entry_url=entry,
        terms_url=terms_url,
        text_storage_policy="raw_internal",
        priority="P2",
        st_official_doc="n/a(public HTML)",
        st_collection_terms=terms,
        st_image_terms=_NO_OPEN_IMAGE_LICENCE,
        notes=notes,
        max_requests=10,
    )
    row.update(extra)
    return row


def _disabled(source_id, name, owner, region, countries, base, entry, terms_url, terms, notes, reason,
              robots_status="not_checked_in_saved_probe_set", live="saved official page observed; not collected",
              source_kind="fair"):
    return _row(
        source_id, name, owner, region, countries, base, entry, terms_url, terms, notes,
        source_kind=source_kind,
        disabled=reason,
        operational_state="blocked_permission",
        robots_status=robots_status,
        st_live_response=live,
    )


SOURCES = [
    _row(
        "wave2_arcomadrid_fair", "ARCOmadrid — editions", "IFEMA MADRID", "EUROPE", "ES",
        "https://www.ifema.es", "https://www.ifema.es/arco/madrid", "https://www.ifema.es/en/legal-notice",
        "The official legal notice limits users to means made available by the website and restricts protected-content reuse. This source reads only ordinary public HTML at the official event URL and stores factual edition metadata; it does not use alternative interfaces, copy page prose, or collect assets.",
        "Sourcebook 유럽-04-005. Official ARCOmadrid 2027 page publicly states 3–7 March 2027 at IFEMA MADRID; no exhibitors or artists are inferred.",
        max_requests=3,
    ),
    _row(
        "wave2_zsonamaco_fair", "ZⓈONAMACO — editions", "ZⓈONAMACO", "AMERICAS", "MX",
        "https://zsonamaco.com", "https://zsonamaco.com/", None,
        "Saved privacy notice is not a collection licence; no terms of use or robots.txt response was present in the saved probe set. Metadata only.",
        "Sourcebook 미주-04-005. Saved homepage and tickets page explicitly display 3–7 February 2027 and Centro Banamex, Mexico City; homepage separately announces 2028 and 2029 date ranges without venues.",
        max_requests=5,
    ),
    _row(
        "wave2_sp_arte_fair", "SP-Arte — Rotas editions", "SP-Arte", "AMERICAS", "BR",
        "https://www.sp-arte.com", "https://www.sp-arte.com/historico-rotas-2026", "https://www.sp-arte.com/termos-de-uso",
        "Saved SP-Arte Terms of Use page reviewed; it describes site and privacy use but contains no observed crawler/text-mining clause. This is not an express content reuse licence; factual metadata only.",
        "Sourcebook 미주-04-006. The saved official Rotas 2026 history page explicitly associates the fifth edition, 26–30 August, ARCA and São Paulo. The exhibitor route probe only said 'Carregando participantes' and is not used.",
        max_requests=5,
    ),
    _row(
        "wave2_artissima_fair", "Artissima — editions", "Artissima", "EUROPE", "IT",
        "https://www.artissima.art", "https://www.artissima.art/", None,
        "Only the official privacy policy was saved; no collection terms or robots.txt response was present in the saved probe set. No reuse permission is inferred; metadata only.",
        "Sourcebook 유럽-04-006. Saved homepage explicitly lists 30 October–1 November 2026 at Oval Lingotto Fiere, Torino; the 2026 exhibitor page has a year-labelled roster table.",
        max_requests=5,
    ),
    _row(
        "wave2_ack_fair", "Art Collaboration Kyoto — editions", "Art Collaboration Kyoto", "ASIA", "JP",
        "https://a-c-k.jp", "https://a-c-k.jp/visitor-information/", None,
        "The saved sourcebook Fetcher note reports robots parsed; the official privacy policy is not a collection licence, and no reuse permission is inferred. Metadata only.",
        "Sourcebook 일본-04-002. Saved 2026 visitor information gives 7–9 November 2026 and Kyoto International Conference Center; the exhibitor page links to ACK 2026 tickets and explicitly labels gallery collaborators/guests.",
        max_requests=5,
    ),
    _row(
        "wave2_tokyogendai_fair", "Tokyo Gendai — editions", "Tokyo Gendai", "ASIA", "JP",
        "https://tokyogendai.com", "https://tokyogendai.com/2026-highlights/", None,
        "The saved sourcebook Fetcher note reports robots parsed; the saved privacy policy is not a collection licence, and no reuse permission is inferred. Metadata only.",
        "Sourcebook 일본-04-003. Saved 2023–2026 highlights pages explicitly state each edition's dates and PACIFICO Yokohama; edition-labelled gallery lists are saved for 2024–2026.",
        max_requests=10,
    ),
    _row(
        "wave2_art_week_tokyo", "Art Week Tokyo — editions and program", "Art Week Tokyo", "ASIA", "JP",
        "https://www.artweektokyo.com", "https://www.artweektokyo.com/events/", None,
        "The saved sourcebook Fetcher note reports robots parsed; the saved legal notice concerns consumer ticket sales, not data collection. No reuse permission is inferred; metadata only.",
        "Sourcebook 일본-04-004. The saved official 2026 event schedule states 4–8 November and programs at locations across Tokyo. It is modeled as one city-wide program edition, not one event per card.",
        max_requests=5,
    ),
    _row(
        "wave2_artbusan_fair", "ART BUSAN — editions", "ART BUSAN", "ASIA", "KR",
        "https://artbusan.com", "https://artbusan.com/about", None,
        "No collection terms or robots.txt response was present in the saved public probe set. No reuse permission is inferred; metadata only.",
        "Sourcebook 한국-04-003. Saved official About page gives ART BUSAN 2027 dates and BEXCO 1st Exhibition Hall, Busan. The galleries page has no explicit 2027 association and is not joined to this edition.",
        max_requests=5,
    ),
    _disabled(
        "wave2_bienal_sp_edition", "Fundação Bienal de São Paulo — edition expansion", "Fundação Bienal de São Paulo",
        "AMERICAS", "BR", "https://bienal.org.br", "https://bienal.org.br/equipe-curatorial-37-bienal/",
        "https://bienal.org.br/termosdeuso/",
        "Official Terms of Use §2: ‘Entretanto, é vedado ao usuário distribuir, modificar, transmitir, reutilizar, reincluir ou utilizar o conteúdo do Portal para fins comerciais, incluindo o texto, imagens, áudio e vídeo sem a autorização expressa da Fundação Bienal de São Paulo.’ Requested editorial reuse may be commercial; no permission was found. Robots parsed allow; this is not a robots restriction.",
        "Sourcebook 미주-04-007. Existing source bienal_sp already covers its 36th-edition announcement; the 37th-edition expansion remains disabled under the explicit commercial-use restriction.",
        "disabled: official Terms of Use require express authorization for commercial reuse of portal content; permission not established (checked against saved 2026-10-28 probe)",
        robots_status="parsed(allow; saved robots page)",
        live="saved public page observed; not collected under Terms of Use",
        source_kind="biennial",
    ),
    _row(
        "wave2_documenta_editions", "documenta — editions", "documenta und Museum Fridericianum gGmbH",
        "EUROPE", "DE", "https://documenta.de", "https://documenta.de/en/news/documenta-16-nimmt-gestalt-an",
        "https://documenta.de/en/haftungsausschluss",
        "The official disclaimer requires prior written consent for use of copyrighted page material. It does not expressly restrict automated access or factual title/date/city fields; this collector stores only those facts, not page prose or images. Publication/reproduction restriction remains noted.",
        "Sourcebook 유럽-04-008. The saved official D16 announcement explicitly states 12 June–19 September 2027 and Kassel; edition history/participant rosters are outside this narrow collector.",
        source_kind="biennial",
        max_requests=3,
    ),
    _row(
        "wave2_manifesta_editions", "Manifesta — editions", "International Foundation Manifesta", "EUROPE", "DE",
        "https://manifesta.org", "https://manifesta.org/editions/manifesta-ruhr/about",
        "https://manifesta.org/legal",
        "The official legal page restricts making public or reproducing any part of the website without express written permission. It does not state an automated-access ban; this collector stores factual edition/location fields and explicitly listed participant names, not descriptions or images. Publication/reproduction restriction remains noted.",
        "Sourcebook 유럽-04-009. Saved Manifesta 16 Ruhr About page states 21 June–4 October 2026 across Duisburg, Essen, Gelsenkirchen and Bochum; its edition-labelled Participants page lists names.",
        source_kind="biennial",
        max_requests=4,
    ),
    _row(
        "wave2_mediacity_seoul_biennale", "Seoul Mediacity Biennale — editions", "Seoul Museum of Art", "ASIA", "KR",
        "https://mediacityseoul.kr", "https://mediacityseoul.kr/ko/today", None,
        "The project Fetcher could not evaluate robots.txt: its request failed with ConnectionError, so the public entry was not requested. No retry or bypass; no collection permission is inferred.",
        "Sourcebook 한국-04-006. SeMA's official site links the SMB system to this .kr host; the unrelated .org review site is rejected.",
        source_kind="biennial",
        disabled="robots.txt request failed with ConnectionError; Fetcher refused the page request as robots_unavailable (checked 2026-10-28)",
        operational_state="blocked_access",
        robots_status="robots_error(ConnectionError)",
        st_live_response="not_requested(Blocked robots_unavailable; robots.txt ConnectionError)",
        max_requests=0,
    ),
]


def _page_text(html):
    return clean_text(soup(html).get_text(" ", strip=True))


def _dates(text, default_year=None):
    """Parse displayed ranges, including fair-site Italian and Portuguese date forms."""
    if not text:
        return None, None, None, None
    value = clean_text(text)
    value = re.sub(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:[（(][^）)]*[）)])?\s*[−–—-]\s*(\d{1,2})日(?:[（(][^）)]*[）)])?",
        r"\1年\2月\3日 – \1年\2月\4日", value,
    )
    value = re.sub(
        r"(?i)from\s+the\s+(\d{1,2})(?:st|nd|rd|th)\s+of\s+([a-zÀ-ÿ]+)\s+until\s+the\s+(\d{1,2})(?:st|nd|rd|th)\s+of\s+([a-zÀ-ÿ]+)\s+(\d{4})",
        r"\1 \2 \5 – \3 \4 \5", value,
    )
    italian = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", value)
    if italian:
        d1, m1, d2, m2, year = (int(x) for x in italian.groups())
        try:
            start = dt.date(year, m1, d1).isoformat()
            end = dt.date(year + (m2 < m1), m2, d2).isoformat()
        except ValueError:
            return None, None, None, None
        return start, "day", end, "day"

    value = re.sub(
        r"(?i)\bfrom\s+(\d{1,2})\s+to\s+(\d{1,2})\s+([a-zÀ-ÿ]+)\s+(\d{4})",
        r"\1 \3 \4 – \2 \3 \4", value,
    )
    value = re.sub(
        r"(?i)\b(\d{1,2})\s+to\s+(\d{1,2})\s+([a-zÀ-ÿ]+),?\s+(\d{4})",
        r"\1 \3 \4 – \2 \3 \4", value,
    )
    value = re.sub(
        r"(?i)\b(20\d{2})\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+de\s+([a-zÀ-ÿ]+)",
        r"\2 \4 \1 – \3 \4 \1", value,
    )
    value = re.sub(
        r"(?i)\b(?:(?:between|entre)\s+)?(\d{1,2})\s+(?:and|a|al|e)\s+(\d{1,2})\s+de\s+([a-zÀ-ÿ]+)",
        r"\1 \3 – \2 \3", value,
    )
    value = re.sub(
        r"(?i)\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+de\s+([a-zÀ-ÿ]+)",
        r"\1 \3 – \2 \3", value,
    )
    value = re.sub(
        r"(?i)\b([a-zÀ-ÿ]+)\s+(\d{1,2})\s*\([^)]*\)\s*[-–—]\s*(\d{1,2})\s*\([^)]*\),?\s*(\d{4})",
        r"\1 \2, \4 – \1 \3, \4", value,
    )
    return parse_date_range(value, default_year=default_year)


def _event_dates(record):
    return _dates(record["date_text"], default_year=record.get("default_year"))


def _skip_stale_incremental(ctx, key):
    if ctx.mode != "incremental":
        return False
    row = ctx.con.execute(
        "SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
        (ctx.source_id, key),
    ).fetchone()
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    return bool(row and row[0] and row[0] < cutoff)


def _first_match(pattern, text, flags=re.I):
    match = re.search(pattern, text, flags)
    return clean_text(match.group(0)) if match else None


def _parse_zsonamaco(home_html, tickets_html):
    home_text = _page_text(home_html)
    ticket_text = _page_text(tickets_html)
    date_text = _first_match(r"\d{1,2}\s*[–—-]\s*\d{1,2}\s+de\s+febrero\s+2027", home_text)
    ticket_date = _first_match(r"\d{1,2}\s+AL\s+\d{1,2}\s+DE\s+FEBRERO\s+I\s+2027", ticket_text)
    if not date_text or not ticket_date:
        return None
    venue = "Centro Banamex" if re.search(r"CENTRO\s+BANAMEX", ticket_text, re.I) else None
    if not venue:
        return None
    return dict(
        title="ZⓈONAMACO 2027",
        date_text=date_text,
        ticket_date=ticket_date,
        city="Mexico City",
        country_code="MX",
        venue=venue,
        venue_excerpt="CENTRO BANAMEX",
        location_excerpt=_first_match(r"11200\s+MIGUEL HIDALGO, CDMX", ticket_text),
        location_locator="tickets page UBICACIÓN DIRECCIÓN",
        event_type="fair_edition",
        title_lang="es",
        announced_status="scheduled",
        locator="homepage next-edition date",
        venue_locator="tickets page UBICACIÓN",
    )


def _parse_zsonamaco_future_editions(home_html):
    text = _page_text(home_html)
    start = text.find("PRÓXIMAS EDICIONES")
    if start < 0:
        return []
    section = text[start:].split("VIP+", 1)[0]
    records = []
    for match in re.finditer(r"(20\d{2})\s+(\d{1,2}\s*[–—-]\s*\d{1,2}\s+DE\s+FEBRERO)", section, re.I):
        year = int(match.group(1))
        if year <= 2027:
            continue
        records.append(dict(
            title=f"ZⓈONAMACO {year}",
            year=year,
            date_text=clean_text(match.group(0)),
            city=None,
            country_code=None,
            venue=None,
            event_type="fair_edition",
            title_lang="es",
            announced_status="scheduled",
            locator="homepage PRÓXIMAS EDICIONES section",
        ))
    return records


def _parse_sp_arte(html):
    page = soup(html)
    text = _page_text(html)
    title_text = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    if not re.search(r"Rotas\s+2026", title_text, re.I):
        return None
    match = re.search(r"entre\s+(\d{1,2})\s+e\s+(\d{1,2})\s+de\s+([a-zÀ-ÿ]+)[^.!]{0,100}?na\s+ARCA[^.!]{0,80}?em\s+São Paulo", text, re.I)
    if not match:
        return None
    date_text = clean_text(match.group(0))
    return dict(
        title="SP-Arte Rotas 2026",
        date_text=date_text,
        default_year=2026,
        city="São Paulo",
        country_code="BR",
        venue="ARCA",
        event_type="fair_edition",
        title_lang="pt",
        announced_status=None,
        locator="article text: 5th edition / period / ARCA venue",
    )


def _parse_artissima(html):
    page = soup(html)
    text = _page_text(html)
    date_text = _first_match(r"\d{1,2}\.\d{2}\s*[–—-]\s*\d{1,2}\.\d{2}\.2026", text)
    title = "Artissima 2026" if date_text else None
    venue = "Oval Lingotto Fiere" if re.search(r"Artissima\s+2026\s+Oval Lingotto Fiere", text) else None
    if not title or not venue:
        return None
    heading = page.find("h1")
    city = "Torino" if heading and "Torino" in clean_text(heading.get_text(" ")) else None
    return dict(
        title=title,
        date_text=date_text,
        city=city,
        country_code="IT" if city else None,
        venue=venue,
        location_excerpt=clean_text(heading.get_text(" ")) if heading and city else None,
        location_locator="homepage h1 city",
        event_type="fair_edition",
        title_lang="it",
        announced_status="scheduled",
        locator="homepage edition date and agenda venue",
    )


def _parse_artissima_exhibitors(html):
    page = soup(html)
    title = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    if "2026" not in title:
        return []
    table = page.select_one("table.tablepress-id-181")
    if table is None:
        return []
    out = []
    for row in table.select("tr"):
        name_cell = row.select_one("td.column-3")
        display_cell = row.select_one("td.column-4")
        city_cell = row.select_one("td.column-6")
        link = display_cell.find("a", href=True) if display_cell else None
        if not name_cell or not link:
            continue
        name = clean_text(name_cell.get_text(" ", strip=True))
        display = clean_text(link.get_text(" ", strip=True))
        city = clean_text(city_cell.get_text(" ", strip=True)) if city_cell else ""
        suffix = ", " + city if city else ""
        if suffix and display.casefold().endswith(suffix.casefold()):
            display = display[:-len(suffix)].strip()
        name = display or name
        if name:
            out.append((name, link["href"]))
    return out


def _parse_ack(html):
    text = _page_text(html)
    date_text = _first_match(
        r"2026年\d{1,2}月\d{1,2}日[（(][^）)]*[）)]\s*[−–—-]\s*\d{1,2}日[（(][^）)]*[）)]",
        text,
    )
    venue = "国立京都国際会館" if "国立京都国際会館" in text else None
    if not date_text or not venue:
        return None
    return dict(
        title="Art Collaboration Kyoto 2026",
        date_text=date_text,
        city="Kyoto",
        country_code="JP",
        venue=venue,
        location_excerpt=_first_match(r"606-0001\s+京都市左京区宝ヶ池", text),
        location_locator="Visitor Information: venue postal address",
        event_type="fair_edition",
        title_lang="en",
        announced_status="scheduled",
        locator="Visitor Information: 開催日程 and 会場",
    )


def _parse_ack_exhibitors(html):
    page = soup(html)
    if not any("ack2026" in link.get("href", "") for link in page.find_all("a", href=True)):
        return []
    out = []
    for card in page.select(".exhibitors-gallery-item"):
        link = card.select_one("a.exhibitors-gallery-item_link[href]")
        if not link:
            continue
        for name_node in card.select(".exhibitors-gallery_name"):
            name = clean_text(name_node.get_text(" ", strip=True))
            if name:
                out.append((name, link["href"]))
    return out


def _parse_tokyogendai(html):
    text = _page_text(html)
    match = re.search(
        r"The (?:inaugural|second|third|fourth) edition of Tokyo Gendai (?:was held|took place) from\s+(\d{1,2}\s*(?:to|[–—-])\s*\d{1,2}\s+[A-Za-z]+,?\s+\d{4}).{0,180}?\bat\s+(PACIFICO Yokohama)",
        text,
    )
    if not match:
        return None
    date_text = match.group(1)
    year_match = re.search(r"20\d{2}", date_text)
    if not year_match:
        return None
    year = int(year_match.group(0))
    return dict(
        title=f"Tokyo Gendai {year}",
        year=year,
        date_text=date_text,
        city="Yokohama",
        country_code="JP",
        venue=match.group(2),
        event_type="fair_edition",
        title_lang="en",
        announced_status=None,
        locator="Fair Overview: edition dates and venue",
    )


def _parse_tokyogendai_exhibitors(html, year):
    page = soup(html)
    if not re.search(rf"{year} Exhibiting Galleries", _page_text(html), re.I):
        return []
    section = page.select_one("section.section-gallery[sector='galleries']")
    if section is None:
        return []
    out = []
    for card in section.select("ul.list-gallery > li.item"):
        name_node = card.select_one(".box-text .title")
        link = card.find("a", href=True)
        name = clean_text(name_node.get_text(" ", strip=True)) if name_node else ""
        if name and link:
            out.append((name, link["href"]))
    return out


def _parse_art_week(html):
    page = soup(html)
    title_text = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    date_text = _first_match(r"NOVEMBER\s+4\s*[–—-]\s*8,\s*2026", title_text)
    if not date_text:
        return None
    text = _page_text(html)
    if "東京各地" not in text and "Tokyo" not in text:
        return None
    return dict(
        title="Art Week Tokyo 2026",
        date_text=date_text,
        city="Tokyo",
        country_code="JP",
        venue=None,
        location_excerpt=_first_match(r"会期中は東京各地で多彩なプログラムが連日開催されます", text),
        location_locator="introductory city-wide program description",
        event_type="program",
        title_lang="en",
        announced_status="scheduled",
        locator="page title and introductory program text",
    )


def _parse_artbusan(html):
    text = _page_text(html)
    date_text = _first_match(r"April\s+23\s*\(Fri\)\s*[-–—]\s*25\s*\(Sun\),\s*2027", text)
    venue = "BEXCO 1st Exhibition Hall" if "BEXCO 1st Exhibition Hall" in text else None
    if not date_text or not venue:
        return None
    return dict(
        title="ART BUSAN 2027",
        date_text=date_text,
        city="Busan",
        country_code="KR",
        venue=venue,
        location_excerpt=_first_match(r"BEXCO 1st Exhibition Hall \(55, APEC-ro, Haeundae-gu, Busan\)", text),
        location_locator="About: venue and address",
        event_type="fair_edition",
        title_lang="en",
        announced_status="scheduled",
        locator="About: ART BUSAN 2027 Opening Hours and Venue",
    )


def _parse_arcomadrid(html):
    page = soup(html)
    title_text = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    if not re.search(r"ARCO\s+MADRID\s+2027", title_text, re.I):
        return None
    text = _page_text(html)
    match = re.search(
        r"(ARCOmadrid\s+se\s+celebrará\s+(del\s+\d{1,2}\s+al\s+\d{1,2}\s+de\s+marzo\s+de\s+2027)\s+en\s+(IFEMA\s+MADRID))",
        text,
        re.I,
    )
    if not match:
        return None
    return dict(
        title="ARCOmadrid 2027",
        date_text=match.group(2),
        city="Madrid",
        country_code="ES",
        venue="IFEMA MADRID",
        location_excerpt=clean_text(match.group(1)),
        location_locator="official FAQ: ARCOmadrid 2027 dates and venue",
        venue_excerpt=match.group(3),
        event_type="fair_edition",
        title_lang="es",
        announced_status="scheduled",
        locator="official FAQ: ¿Cuándo se celebra ARCOmadrid 2027?",
    )


def _parse_documenta(html):
    page = soup(html)
    text = _page_text(html)
    title = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    date_text = _first_match(r"From June 12 to September 19, 2027", text)
    if "DOCUMENTA SIXTEEN" not in title.upper() or not date_text or "take place in Kassel" not in text:
        return None
    return dict(
        title="documenta 16",
        date_text=date_text,
        city="Kassel",
        country_code="DE",
        venue=None,
        event_type="biennial_edition",
        title_lang="en",
        announced_status="scheduled",
        locator="D16 news announcement: displayed event dates",
        location_locator="D16 news announcement: edition city",
        location_excerpt="take place in Kassel",
    )


def _parse_manifesta(html):
    page = soup(html)
    title = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    text = _page_text(html)
    date_text = _first_match(
        r"from the \d{1,2}(?:st|nd|rd|th) of June until the \d{1,2}(?:st|nd|rd|th) of October 2026",
        text,
    )
    location = _first_match(
        r"across four cities in Germany[’']s Ruhr Area: Duisburg, Essen, Gelsenkirchen and Bochum",
        text,
    )
    if "Manifesta 16 Ruhr" not in title or not date_text or not location:
        return None
    return dict(
        title="Manifesta 16 Ruhr",
        date_text=date_text,
        city=None,
        country_code="DE",
        venue=None,
        event_type="biennial_edition",
        title_lang="en",
        announced_status=None,
        locator="Manifesta 16 Ruhr About: displayed dates",
        location_locator="Manifesta 16 Ruhr About: four host cities",
        location_excerpt=location,
        description_excerpt=location,
        city_review="event spans four named cities; the event schema has a single city field",
    )


def _parse_manifesta_participants(html):
    page = soup(html)
    title = clean_text(page.title.get_text(" ", strip=True)) if page.title else ""
    if "Manifesta 16 Ruhr" not in title or "Participants" not in _page_text(html):
        return []
    listing = page.select_one("ul[class*='participants-list']")
    if listing is None:
        return []
    rows = []
    for link in listing.select("a[href]"):
        href = link["href"]
        if not re.search(r"^/editions/manifesta-ruhr/participants/\d+/?$", href):
            continue
        label = clean_text(link.get_text(" ", strip=True))
        name = re.sub(r",\s*[A-Z]{2,3}(?:/[A-Z]{2,3})*$", "", label)
        if name:
            rows.append((name, urljoin("https://manifesta.org", href)))
    return rows


def _organizer(ctx, name, entity_type="fair", official_url=None, lang="en"):
    return db.ensure_entity(
        ctx.con,
        entity_type=entity_type,
        name=name,
        namespace=f"src:{ctx.source_id}",
        id_value="organizer",
        lang=lang,
        source_id=ctx.source_id,
        official_url=official_url,
    )


def _attach_evidence(con, event_id, evidence_id):
    con.execute(
        "INSERT INTO event_evidence(event_id,evidence_id) VALUES(?,?) ON CONFLICT DO NOTHING",
        (event_id, evidence_id),
    )


def _store_venue(ctx, owner_entity_id, name, city, country_code):
    """events.venue_id references venues, not entities."""
    venue_id = db.sid("ven", ctx.source_id, clean_text(name).casefold())
    edition_region = region.edition_region(country_code) if country_code else None
    ctx.con.execute(
        "INSERT INTO venues(venue_id,owner_entity_id,name,city,country_code,edition_region,source_id) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(venue_id) DO UPDATE SET "
        "owner_entity_id=COALESCE(venues.owner_entity_id,excluded.owner_entity_id), "
        "city=COALESCE(excluded.city,venues.city), "
        "country_code=COALESCE(excluded.country_code,venues.country_code), "
        "edition_region=COALESCE(excluded.edition_region,venues.edition_region)",
        (venue_id, owner_entity_id, clean_text(name), city, country_code, edition_region, ctx.source_id),
    )
    return venue_id


def _store_event(ctx, organizer, response, record, *, key, url=None, extra_responses=(), venue_response=None,
                 location_response=None):
    start, start_precision, end, end_precision = _event_dates(record)
    evidence_id = ctx.evidence(response, locator=record["locator"], excerpt=record["date_text"])
    venue_id = None
    if record.get("venue"):
        venue_response = venue_response or response
        venue_evidence_id = ctx.evidence(
            venue_response,
            locator=record.get("venue_locator", "displayed venue"),
            excerpt=record.get("venue_excerpt", record["venue"]),
        )
        venue_entity_id = db.ensure_entity(
            ctx.con,
            entity_type="venue",
            name=record["venue"],
            namespace=f"src:{ctx.source_id}",
            source_id=ctx.source_id,
            evidence_id=venue_evidence_id,
        )
        venue_id = _store_venue(ctx, venue_entity_id, record["venue"], record.get("city"), record.get("country_code"))
    event_id = db.upsert_event(
        ctx.con,
        ctx.stats,
        source_id=ctx.source_id,
        source_event_key=key,
        event_type=record["event_type"],
        title=record["title"],
        parser_version=PARSER_VERSION,
        title_lang=record["title_lang"],
        organizer_entity_id=organizer,
        venue_id=venue_id,
        city=record.get("city"),
        country_code=record.get("country_code"),
        start_date=start,
        start_precision=start_precision,
        end_date=end,
        end_precision=end_precision,
        date_text=record["date_text"],
        announced_status=record.get("announced_status"),
        url=url or response.url,
        description_excerpt=record.get("description_excerpt") or (("venue: " + record["venue"]) if record.get("venue") else record.get("location_excerpt")),
        evidence_id=evidence_id,
    )
    for detail_response, locator, excerpt in extra_responses:
        extra_evidence = ctx.evidence(detail_response, locator=locator, excerpt=excerpt)
        _attach_evidence(ctx.con, event_id, extra_evidence)
    if record.get("location_excerpt"):
        location_response = location_response or response
        location_evidence_id = ctx.evidence(
            location_response,
            locator=record.get("location_locator", "displayed location"),
            excerpt=record["location_excerpt"],
        )
        _attach_evidence(ctx.con, event_id, location_evidence_id)
    if record.get("venue"):
        _attach_evidence(ctx.con, event_id, venue_evidence_id)
    if not record.get("country_code"):
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=record.get("venue"))
    if record.get("city_review"):
        db.add_review(ctx.con, "region", "events", event_id, record["city_review"], detail=record.get("description_excerpt"))
    ctx.count("fetched")
    ctx.count("parsed")
    return event_id, evidence_id


def _store_exhibitors(ctx, event_id, response, rows):
    if not rows:
        return 0
    names = []
    seen = set()
    for name, official_url in rows:
        name = clean_text(name)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append((name, official_url))
    if not names:
        return 0
    excerpt = "; ".join(name for name, _ in names)
    evidence_id = ctx.evidence(response, locator="edition-labelled exhibitor list markup", excerpt=excerpt)
    for name, official_url in names:
        gallery = db.ensure_entity(
            ctx.con,
            entity_type="gallery",
            name=name,
            namespace=f"src:{ctx.source_id}",
            source_id=ctx.source_id,
            evidence_id=evidence_id,
            official_url=official_url,
        )
        db.add_participant(ctx.con, event_id, gallery, "exhibitor", name, evidence_id, "list_markup")
    _attach_evidence(ctx.con, event_id, evidence_id)
    ctx.count("fetched", len(names))
    return len(names)


def _store_participants(ctx, event_id, response, rows):
    names = []
    seen = set()
    for name, official_url in rows:
        name = clean_text(name)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append((name, official_url))
    if not names:
        return 0
    excerpt = "; ".join(name for name, _ in names)
    evidence_id = ctx.evidence(response, locator="edition-labelled Participants list", excerpt=excerpt)
    for name, official_url in names:
        participant = db.ensure_entity(
            ctx.con,
            entity_type="artist",
            name=name,
            namespace=f"src:{ctx.source_id}",
            source_id=ctx.source_id,
            evidence_id=evidence_id,
            official_url=official_url,
        )
        db.add_participant(ctx.con, event_id, participant, "participant", name, evidence_id, "list_markup")
    _attach_evidence(ctx.con, event_id, evidence_id)
    ctx.count("fetched", len(names))
    return len(names)


def _fetch_roster(ctx, event_id, url, parser, listing_label):
    try:
        response = ctx.fetch(url)
    except Blocked:
        raise
    except FetchError as exc:
        ctx.note(f"{listing_label} unavailable: {exc}")
        ctx.count("detail_errors")
        return
    rows = parser(response.text)
    count = _store_exhibitors(ctx, event_id, response, rows)
    ctx.note(f"{listing_label}: {count} explicitly listed exhibitors")


def _fetch_participants(ctx, event_id, url, parser, listing_label):
    try:
        response = ctx.fetch(url)
    except Blocked:
        raise
    except FetchError as exc:
        ctx.note(f"{listing_label} unavailable: {exc}")
        ctx.count("detail_errors")
        return
    rows = parser(response.text)
    count = _store_participants(ctx, event_id, response, rows)
    ctx.note(f"{listing_label}: {count} explicitly listed participants")


def _collect_zsonamaco(ctx):
    home = ctx.fetch("https://zsonamaco.com/")
    ticket = ctx.fetch("https://zsonamaco.com/boletos/")
    record = _parse_zsonamaco(home.text, ticket.text)
    if not record:
        ctx.note("no edition with both a displayed 2027 date and actual venue was parsed")
        return
    organizer = _organizer(ctx, "ZⓈONAMACO", official_url="https://zsonamaco.com/", lang="es")
    ticket_evidence_excerpt = record["ticket_date"]
    _store_event(
        ctx, organizer, home, record, key="2027", url="https://zsonamaco.com/",
        extra_responses=((ticket, "HORARIOS: displayed 2027 dates", ticket_evidence_excerpt),),
        venue_response=ticket, location_response=ticket,
    )
    for future in _parse_zsonamaco_future_editions(home.text):
        _store_event(ctx, organizer, home, future, key=str(future["year"]))
    ctx.note("2026 participant list is not associated with the 2027 event")
    ctx.note("2028 and 2029 have homepage dates only; no venue or city is inferred")


def _collect_sp_arte(ctx):
    if _skip_stale_incremental(ctx, "rotas-2026"):
        ctx.note("SP-Arte Rotas 2026 is already stored and ended more than 30 days ago; incremental detail fetch skipped")
        return
    response = ctx.fetch("https://www.sp-arte.com/historico-rotas-2026")
    record = _parse_sp_arte(response.text)
    if not record:
        ctx.note("no edition with explicit Rotas 2026 dates and ARCA venue was parsed")
        return
    organizer = _organizer(ctx, "SP-Arte", official_url="https://www.sp-arte.com/", lang="pt")
    _store_event(ctx, organizer, response, record, key="rotas-2026")


def _collect_artissima(ctx):
    response = ctx.fetch("https://www.artissima.art/")
    record = _parse_artissima(response.text)
    if not record:
        ctx.note("no edition with displayed dates and Oval Lingotto Fiere venue was parsed")
        return
    organizer = _organizer(ctx, "Artissima", official_url="https://www.artissima.art/", lang="it")
    event_id, _ = _store_event(ctx, organizer, response, record, key="2026")
    _fetch_roster(ctx, event_id, "https://www.artissima.art/elenco-espositori/", _parse_artissima_exhibitors,
                  "Artissima 2026 exhibitor list")


def _collect_ack(ctx):
    response = ctx.fetch("https://a-c-k.jp/visitor-information/")
    record = _parse_ack(response.text)
    if not record:
        ctx.note("no edition with displayed date and actual venue was parsed")
        return
    organizer = _organizer(ctx, "Art Collaboration Kyoto", official_url="https://a-c-k.jp/", lang="en")
    event_id, _ = _store_event(ctx, organizer, response, record, key="2026")
    _fetch_roster(ctx, event_id, "https://a-c-k.jp/exhibitors/", _parse_ack_exhibitors, "ACK 2026 exhibitor list")


def _collect_tokyogendai(ctx):
    organizer = _organizer(ctx, "Tokyo Gendai", official_url="https://tokyogendai.com/")
    years = (2026,) if ctx.mode == "incremental" else (2023, 2024, 2025, 2026)
    roster_urls = {
        2024: "https://tokyogendai.com/galleries-2024/",
        2025: "https://tokyogendai.com/galleries-2025/",
        2026: "https://tokyogendai.com/galleries-2026-2/",
    }
    parsed_years = []
    for year in years:
        if _skip_stale_incremental(ctx, str(year)):
            ctx.note(f"Tokyo Gendai {year} is already stored and ended more than 30 days ago; incremental detail fetch skipped")
            continue
        url = f"https://tokyogendai.com/{year}-highlights/"
        try:
            response = ctx.fetch(url)
        except Blocked:
            raise
        except FetchError as exc:
            ctx.note(f"Tokyo Gendai {year} edition page unavailable: {exc}")
            ctx.count("detail_errors")
            continue
        record = _parse_tokyogendai(response.text)
        if not record or record["year"] != year:
            ctx.note(f"Tokyo Gendai {year} page did not expose a matching dated edition and venue")
            continue
        event_id, _ = _store_event(ctx, organizer, response, record, key=str(year))
        parsed_years.append(year)
        if year in roster_urls:
            _fetch_roster(
                ctx, event_id, roster_urls[year],
                lambda html, event_year=year: _parse_tokyogendai_exhibitors(html, event_year),
                f"Tokyo Gendai {year} exhibitor list",
            )
    if ctx.mode == "initial":
        ctx.note(f"Tokyo Gendai edition history parsed from saved year pages: {parsed_years}; no 2023 roster page was saved")
    else:
        ctx.note(f"Tokyo Gendai incremental edition page checked: {parsed_years}; older years are archive scope")


def _collect_art_week(ctx):
    response = ctx.fetch("https://www.artweektokyo.com/events/")
    record = _parse_art_week(response.text)
    if not record:
        ctx.note("no dated Art Week Tokyo edition was parsed")
        return
    organizer = _organizer(ctx, "Art Week Tokyo", official_url="https://www.artweektokyo.com/")
    _store_event(ctx, organizer, response, record, key="2026")
    ctx.note("city-wide program listing stored as one edition; individual program events are outside this collector")


def _collect_artbusan(ctx):
    response = ctx.fetch("https://artbusan.com/about")
    record = _parse_artbusan(response.text)
    if not record:
        ctx.note("no edition with displayed dates and actual BEXCO venue was parsed")
        return
    organizer = _organizer(ctx, "ART BUSAN", official_url="https://artbusan.com/")
    _store_event(ctx, organizer, response, record, key="2027")
    ctx.note("the unversioned gallery directory is not associated with the 2027 edition")


def _collect_arcomadrid(ctx):
    if _skip_stale_incremental(ctx, "2027"):
        ctx.note("ARCOmadrid 2027 is already stored and ended more than 30 days ago; incremental detail fetch skipped")
        return
    response = ctx.fetch("https://www.ifema.es/arco/madrid")
    record = _parse_arcomadrid(response.text)
    if not record:
        ctx.note("official ARCOmadrid page did not expose matching 2027 dates and IFEMA MADRID venue")
        return
    organizer = _organizer(ctx, "ARCOmadrid", official_url="https://www.ifema.es/arco/madrid", lang="es")
    _store_event(ctx, organizer, response, record, key="2027")
    ctx.note("only official public 2027 date/venue metadata is stored; no gallery or artist roster is inferred")


def _collect_documenta(ctx):
    response = ctx.fetch("https://documenta.de/en/news/documenta-16-nimmt-gestalt-an")
    record = _parse_documenta(response.text)
    if not record:
        ctx.note("the official announcement did not expose a matching documenta 16 date and city")
        return
    organizer = _organizer(
        ctx, "documenta", entity_type="biennial", official_url="https://documenta.de/", lang="en",
    )
    _store_event(ctx, organizer, response, record, key="documenta-16")
    ctx.note("only explicit factual title/date/city metadata is stored; no page prose or images are copied")


def _collect_manifesta(ctx):
    if _skip_stale_incremental(ctx, "manifesta-16-ruhr"):
        ctx.note("Manifesta 16 Ruhr is already stored and ended more than 30 days ago; incremental detail fetch skipped")
        return
    response = ctx.fetch("https://manifesta.org/editions/manifesta-ruhr/about")
    record = _parse_manifesta(response.text)
    if not record:
        ctx.note("Manifesta 16 About page did not expose a matching date range and host-city list")
        return
    organizer = _organizer(
        ctx, "Manifesta", entity_type="biennial", official_url="https://manifesta.org/", lang="en",
    )
    event_id, _ = _store_event(ctx, organizer, response, record, key="manifesta-16-ruhr")
    _fetch_participants(
        ctx, event_id, "https://manifesta.org/editions/manifesta-ruhr/participants",
        _parse_manifesta_participants, "Manifesta 16 Ruhr participants",
    )
    ctx.note("publication/reproduction restriction is recorded; participant names are stored as factual list entries only")


def collect(ctx):
    collectors = {
        "wave2_arcomadrid_fair": _collect_arcomadrid,
        "wave2_zsonamaco_fair": _collect_zsonamaco,
        "wave2_sp_arte_fair": _collect_sp_arte,
        "wave2_artissima_fair": _collect_artissima,
        "wave2_ack_fair": _collect_ack,
        "wave2_tokyogendai_fair": _collect_tokyogendai,
        "wave2_art_week_tokyo": _collect_art_week,
        "wave2_artbusan_fair": _collect_artbusan,
        "wave2_documenta_editions": _collect_documenta,
        "wave2_manifesta_editions": _collect_manifesta,
    }
    collector = collectors.get(ctx.source_id)
    if collector is None:
        raise RuntimeError(f"no enabled collector for {ctx.source_id}")
    collector(ctx)
    ctx.con.commit()
