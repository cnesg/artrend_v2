"""Bounded residency and award selections verified in the Wave-2 public-page evidence.

The collectors intentionally cover only named cohorts/award editions represented by saved official HTML.
They do not infer a selection year from application deadlines, pagination, names, or biography dates.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from .. import db
from ._common import clean_text, soup

PARSER_VERSION = "wave2_residencies-1"

STUDIO = "https://www.studiomuseum.org"
STUDIO_2026_PRESS = f"{STUDIO}/press/studio-museum-announces-2026-27-artists-in-residence"
PIVO = "https://pivo.org.br"
PIVO_2019 = f"{PIVO}/noticias/resultado-da-convocatoria-da-bolsa-residencia-pivo-pesquisa-2019/"
PIVO_2022 = f"{PIVO}/noticias/pivo-pesquisa-2022-boas-vindas-aos-artistas-residentes-do-ciclo-iii/"
ADIAF = "https://www.adiaf.com"
ADIAF_2024_ARTICLE = f"{ADIAF}/prix-marcel-duchamp-2024-a-art-geneve/"
ADIAF_PRIZE_OVERVIEW = f"{ADIAF}/en/the-prix-marcel-duchamp/"
ADIAF_ARTISTS = f"{ADIAF}/en/artists/"
WILLING = "https://www.willingndealing.org"
WILLING_CHONG_KUN_DANG_2024 = f"{WILLING}/n357"
WILLING_KIAF_2025 = f"{WILLING}/n378"
BEMIS = "https://www.bemiscenter.org"
BEMIS_AYDO = f"{BEMIS}/residents/aydo"
FONDERIE = "https://fonderiedarling.org"
FONDERIE_BY_YEAR = f"{FONDERIE}/residencesparannee"
RIJKSAKADEMIE = "https://rijksakademie.nl"
RIJKS_FARREN = f"{RIJKSAKADEMIE}/en/residents-advisors-team/farren-linhares"
DE_ATELIERS = "https://de-ateliers.nl"
DE_ATELIERS_PEOPLE = f"{DE_ATELIERS}/en/people"
GASWORKS = "https://www.gasworks.org.uk"
GASWORKS_ARCHIVE = f"{GASWORKS}/residencies/archive/"
DELFINA = "https://www.delfinafoundation.com"
DELFINA_RESIDENCIES = f"{DELFINA}/in-residence/"
BANKART = "https://bankart1929.com"
BANKART_EXPLOT = f"{BANKART}/project/explotstudio/"
DAAD = "https://www.berliner-kuenstlerprogramm.de"
DAAD_AWARD_FELLOWS = f"{DAAD}/de/bkp-fellows/"
DAAD_2026_PROFILES = (
    f"{DAAD}/en/artist/lina-lapelyte/",
    f"{DAAD}/en/artist/javier-areal-velez/",
)

SOURCES = [
    dict(
        source_id="wave2_studio_museum_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Studio Museum in Harlem — artists in residence", owner_group="Studio Museum in Harlem",
        source_kind="residency", region_scope="AMERICAS", country_codes="US", access_method="html",
        base_url=STUDIO, entry_url=STUDIO_2026_PRESS,
        terms_url=f"{STUDIO}/terms-of-use", text_storage_policy="raw_internal", priority="P2",
        st_official_doc="n/a(public HTML)",
        st_collection_terms=("Saved Terms of Use: content is limited to personal noncommercial/fair use; commercial use or "
                             "republication requires permission. No automated-access clause observed. Metadata and internal "
                             "evidence only; this is not a reuse licence."),
        st_image_terms="Images are not fetched; terms reserve rights to the Museum and other rightsholders.",
        notes="Sourcebook 미주-08-001. Bounded to the saved 2026–27 official announcement; not a complete cohort history.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_pivo_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Pivô — verified residency selections", owner_group="Pivô",
        source_kind="residency", region_scope="AMERICAS", country_codes="BR", access_method="html",
        base_url=PIVO, entry_url=PIVO_2022, terms_url=None, text_storage_policy="raw_internal", priority="P2",
        st_official_doc="n/a(public HTML)",
        st_collection_terms="No terms page is identified in the saved evidence; no reuse permission is inferred. Metadata and internal evidence only.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 미주-08-007. Only saved 2019 and 2022 cohort announcements; application publication dates are not event dates.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_adiaf_prize", blueprint_data_id=None, blueprint_org_id=None,
        name="ADIAF — Prix Marcel Duchamp selections", owner_group="ADIAF",
        source_kind="award", region_scope="EUROPE", country_codes="FR", access_method="html",
        base_url=ADIAF, entry_url=ADIAF_2024_ARTICLE, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms=("Saved official overview distinguishes one laureate among four nominated artists; no general "
                             "reuse/automated-access terms were located in the evidence. Metadata and internal evidence only."),
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes=("Sourcebook 유럽-08-008. Bounded to the evidenced 2024 award edition. The public artists filter is fetched "
               "with an ordinary GET query; no POST/AJAX endpoint is used."),
        max_requests=10,
    ),
    dict(
        source_id="wave2_willingndealing_awards", blueprint_data_id=None, blueprint_org_id=None,
        name="Willing N Dealing — reported artist award selections", owner_group="Willing N Dealing",
        source_kind="gallery", region_scope="KR", country_codes="KR", access_method="html",
        base_url=WILLING, entry_url=WILLING_CHONG_KUN_DANG_2024, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms=("No terms/reuse permission is identified in the saved evidence. These are gallery-posted "
                             "reports of named awards, not organizer records; metadata and internal evidence only."),
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes=("Sourcebook 한국-08-005. Bounded to two saved gallery posts; reported third-party awards are not attributed "
               "to the gallery as organizer."),
        max_requests=10,
    ),
    dict(
        source_id="wave2_bemis_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Bemis Center for Contemporary Arts — artist in residence", owner_group="Bemis Center for Contemporary Arts",
        source_kind="residency", region_scope="AMERICAS", country_codes="US", access_method="html",
        base_url=BEMIS, entry_url=BEMIS_AYDO, terms_url=None, text_storage_policy="raw_internal", priority="P2",
        st_official_doc="n/a(public HTML)",
        st_collection_terms="No terms/reuse permission was identified in saved evidence; no reuse permission is inferred. Robots returned 404/not_found(allow) in the saved Fetcher probe.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 미주-08-005. One explicitly labeled Fall 2026 resident profile only; not a complete cohort.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_fonderie_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Fonderie Darling — year-indexed residencies", owner_group="Fonderie Darling",
        source_kind="residency", region_scope="AMERICAS", country_codes="CA", access_method="html",
        base_url=FONDERIE, entry_url=FONDERIE_BY_YEAR, terms_url=None, text_storage_policy="raw_internal", priority="P2",
        st_official_doc="n/a(public HTML)",
        st_collection_terms="Terms and robots were not audited in the saved evidence; the saved privacy page is not a reuse licence. No reuse permission inferred.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 미주-08-006. Only named entries in the saved 2026 year section are collected.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_rijksakademie_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Rijksakademie — verified resident profile", owner_group="Rijksakademie",
        source_kind="residency", region_scope="EUROPE", country_codes="NL", access_method="html",
        base_url=RIJKSAKADEMIE, entry_url=RIJKS_FARREN, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="No general terms/reuse policy was observed. Saved robots evidence disallows named AI crawlers; the project Fetcher must enforce its own live robots result. No reuse permission inferred.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 유럽-08-001. One saved profile explicitly labels a resident for 2026–27; no cohort completeness claimed.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_daad_fellows_2026", blueprint_data_id=None, blueprint_org_id=None,
        name="Berliner Künstlerprogramm des DAAD — year-tagged award fellows", owner_group="Berliner Künstlerprogramm des DAAD",
        source_kind="award", region_scope="EUROPE", country_codes="DE", access_method="html",
        base_url=DAAD, entry_url=DAAD_AWARD_FELLOWS, terms_url=f"{DAAD}/de/impressum/",
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="Saved imprint does not grant data reuse or automated-access permission; no reuse permission is inferred. Saved robots rules are empty for the project user agent on tested pages; runtime Fetcher must enforce its current result.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 유럽-08-006. Only two saved 2026 Award Fellows profiles are collected; no full-cohort completeness claimed.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_de_ateliers_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="De Ateliers — participant cohorts", owner_group="De Ateliers",
        source_kind="residency", region_scope="EUROPE", country_codes="NL", access_method="html",
        base_url=DE_ATELIERS, entry_url=DE_ATELIERS_PEOPLE, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="Terms and robots were not audited in the saved evidence; no reuse permission is inferred.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 유럽-08-002. Only the two year-labeled participant cohorts shown in the saved public people page are collected.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_gasworks_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Gasworks — dated residency archive", owner_group="Gasworks",
        source_kind="residency", region_scope="EUROPE", country_codes="GB", access_method="html",
        base_url=GASWORKS, entry_url=GASWORKS_ARCHIVE, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="Terms and robots were not audited in the saved evidence; no reuse permission is inferred.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 유럽-08-004. Only the 2026 and 2027 dated residency cycles visible in the saved archive page are collected.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_delfina_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="Delfina Foundation — dated residencies", owner_group="Delfina Foundation",
        source_kind="residency", region_scope="EUROPE", country_codes="GB", access_method="html",
        base_url=DELFINA, entry_url=DELFINA_RESIDENCIES, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="Terms and robots were not audited in the saved evidence; no reuse permission is inferred.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 유럽-08-005. Only the 2026 entries displayed in the saved current/future/past residency listing are collected.",
        max_requests=10,
    ),
    dict(
        source_id="wave2_bankart_residencies", blueprint_data_id=None, blueprint_org_id=None,
        name="BankART1929 — ExPLOT Studio residents", owner_group="BankART1929",
        source_kind="residency", region_scope="JP", country_codes="JP", access_method="html",
        base_url=BANKART, entry_url=BANKART_EXPLOT, terms_url=None,
        text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(public HTML)",
        st_collection_terms="Saved Fetcher probe parsed robots; no reuse terms or automated-access permission was observed. The privacy page is not a reuse licence.",
        st_image_terms="Images are not fetched; no image reuse licence is recorded.",
        notes="Sourcebook 일본-08-002. The saved ExPLOT Studio 2026 page explicitly names residents and a June 2026–March 2027 period.",
        max_requests=10,
    ),
]


_SOURCE_BY_ID = {row["source_id"]: row for row in SOURCES}


def _year_range(text):
    """Return displayed (start, end, source text) years without adding month/day precision."""
    value = clean_text(text)
    match = re.search(r"(?<!\d)(20\d{2})\s*([–—-])\s*(\d{2}|20\d{2})(?!\d)", value)
    if match:
        start = int(match.group(1))
        end_token = match.group(3)
        end = int(end_token) if len(end_token) == 4 else (start // 100) * 100 + int(end_token)
        if end < start:
            return None, None, None
        return str(start), str(end), match.group(0)
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", value)
    if match:
        return match.group(1), None, match.group(1)
    return None, None, None


def parse_studio_museum(html):
    page = soup(html)
    heading = page.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else (page.title and clean_text(page.title.get_text(" ")))
    if not title:
        return None
    match = re.search(
        r"Studio Museum Announces\s+(.+?)\s+as\s+(20\d{2}\s*[–—-]\s*(?:\d{2}|20\d{2}))\s+Artists in Residence",
        title, re.I,
    )
    if not match:
        return None
    start, end, displayed = _year_range(match.group(2))
    if not start:
        return None
    names = [clean_text(name) for name in re.split(r",\s*|\s+and\s+", match.group(1))]
    names = [re.sub(r"^and\s+", "", name).strip() for name in names if name.strip()]
    if not names:
        return None
    return {"title": title, "start": start, "end": end, "date_text": displayed, "residents": names}


def parse_pivo_announcement(html):
    page = soup(html)
    heading = page.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else ""
    year_match = re.search(r"Piv[oô]\s+Pesquisa\s+(20\d{2})", title, re.I)
    if not year_match:
        return None
    year = year_match.group(1)
    paragraphs = [p for p in page.find_all("p") if clean_text(p.get_text(" "))]
    if year == "2022":
        announcement = next((p for p in paragraphs if "artistas participantes" in clean_text(p.get_text(" ")).lower()
                             and "Ciclo III" in clean_text(p.get_text(" "))), None)
        if announcement is None:
            return None
        residents = []
        for anchor in announcement.select('a[href*="/residencias/participantes/"]'):
            name = clean_text(anchor.get_text(" "))
            if name and name not in residents:
                residents.append(name)
        if not residents:
            return None
        return {"year": year, "title": title, "date_text": title, "residents": residents,
                "resident_urls": {clean_text(a.get_text(" ")): a.get("href") for a in announcement.select(
                    'a[href*="/residencias/participantes/"]') if clean_text(a.get_text(" "))},
                "curator": _pivo_curator(clean_text(announcement.get_text(" ")))}
    if year == "2019":
        selection = next((p for p in paragraphs if "artistas selecionadas" in clean_text(p.get_text(" ")).lower()
                         and "bolsas-residências" in clean_text(p.get_text(" ")).lower()), None)
        invite = next((p for p in paragraphs if "modalidade bolsa-convite" in clean_text(p.get_text(" ")).lower()
                       and "contemplado" in clean_text(p.get_text(" ")).lower()), None)
        if selection is None:
            return None
        residents = [clean_text(node.get_text(" ")) for node in selection.find_all(["b", "strong"])]
        residents = [name for name in residents if name]
        winner = None
        if invite:
            marked = [clean_text(node.get_text(" ")) for node in invite.find_all(["b", "strong"])]
            winner = marked[0] if marked else None
        if not residents:
            return None
        return {"year": year, "title": title, "date_text": title, "residents": residents,
                "resident_urls": {}, "invite_winner": winner}
    return None


def _pivo_curator(text):
    match = re.search(r"\be o curador\s+(.+?)\s*,\s*responsável", text, re.I)
    return clean_text(match.group(1)) if match else None


def parse_adiaf_article(html):
    page = soup(html)
    heading = page.find("h1")
    title = clean_text(heading.get_text(" ")) if heading else (page.title and clean_text(page.title.get_text(" ")))
    year = re.search(r"Prix Marcel Duchamp\s+(20\d{2})", title or "", re.I)
    section = page.select_one("#fade")
    if not year or section is None:
        return None
    artists = []
    for card in section.select(".position-relative"):
        anchor = card.select_one('a[href*="/artistes/"]')
        label = card.find("p")
        name = clean_text(label.get_text(" ")) if label else ""
        if anchor and name:
            artists.append({"name": name, "url": anchor.get("href")})
    if not artists:
        return None
    return {"year": year.group(1), "title": title, "artists": artists}


def parse_adiaf_roster(html, year):
    page = soup(html)
    # The public list exposes a nomination-year filter and marks the laureate in each card.
    filter_select = page.select_one('li[data-sf-field-name="_sfm_date_nomination"] select')
    selected_year = clean_text(filter_select.select_one("option[selected]").get_text(" ")) if filter_select and filter_select.select_one("option[selected]") else None
    if selected_year and selected_year != year:
        return []
    cards = []
    for card in page.select(".position-relative"):
        anchor = card.select_one('a[href*="/artistes/"]')
        label = card.find("p")
        if not anchor or not label:
            continue
        lines = [clean_text(line) for line in label.get_text("\n").splitlines() if clean_text(line)]
        card_year = next((line for line in lines if re.fullmatch(r"20\d{2}", line)), None)
        if card_year != year or not lines:
            continue
        name = lines[0]
        role = "winner" if any(re.search(r"\b(?:laureate|laur[ée]at)\b", line, re.I) for line in lines[1:]) else "nominee"
        cards.append({"name": name, "role": role, "url": anchor.get("href")})
    return cards


def parse_adiaf_overview(html):
    text = clean_text(soup(html).get_text(" ")).casefold()
    return "four nominated artists" in text and "one laureate" in text


def parse_willing_award(html):
    page = soup(html)
    text = clean_text(page.get_text(" "))
    # Use the displayed award edition/year in the announcement, never the post/update date.
    winner = re.search(
        r"(?P<name>[가-힣A-Za-z· ]+?)\s*작가가\s*['‘\"]?종근당\s*예술지상\s*(?P<year>20\d{2})['’\"]?\s*올해의\s*작가로\s*선정",
        text,
    )
    if winner:
        name = clean_text(winner.group("name"))
        return {"year": winner.group("year"), "title": f"종근당 예술지상 {winner.group('year')}",
                "event_type": "award", "role": "winner", "names": [name], "excerpt": winner.group(0)}
    finalist = re.search(
        r"(?P<year>20\d{2})년\s*키아프의\s*하이라이트\s*작가\s*10인에\s*선정된\s*"
        r"(?P<first>[가-힣A-Za-z· ]+?)\s*작가가\s*(?P<others>.+?)\s*작가와\s*함께\s*최종\s*3인의",
        text,
    )
    if finalist:
        others = [clean_text(name) for name in re.split(r"[,，、]", finalist.group("others")) if clean_text(name)]
        names = [clean_text(finalist.group("first")), *others]
        return {"year": finalist.group("year"), "title": f"Kiaf Highlights {finalist.group('year')}",
                "event_type": "open_call_selection", "role": "nominee", "names": names,
                "excerpt": finalist.group(0)}
    return None


def parse_bemis_profile(html):
    page = soup(html)
    heading = page.find("h1")
    name = clean_text(heading.get_text(" ")) if heading else ""
    text = clean_text(page.get_text(" "))
    season = re.search(r"Artist-in-Residence\s+(Fall|Winter|Spring|Summer)\s+(20\d{2})", text, re.I)
    if not name or not season:
        return None
    return {"name": name, "year": season.group(2), "date_text": f"{season.group(1)} {season.group(2)}",
            "entity_type": "group" if re.search(r"\bduo\b", text, re.I) else "person"}


def parse_fonderie_by_year(html, year="2026"):
    page = soup(html)
    archive = page.select_one("#main .archives")
    if archive is None:
        return []
    current_year = None
    entries = []
    for node in archive.find_all(["a", "div"], recursive=False):
        classes = node.get("class") or []
        if "archiveSeperator" in classes:
            current_year = clean_text(node.get_text(" "))
            continue
        if "archiveElement" not in classes or current_year != year:
            continue
        name_node = node.select_one(".title h1 a")
        program_node = node.select_one(".text h3")
        if not name_node or not program_node:
            continue
        name = clean_text(name_node.get_text(" "))
        program = clean_text(program_node.get_text(" "))
        if name and program:
            entries.append({"name": name, "program": program, "url": name_node.get("href"), "year": year})
    return entries


def parse_de_ateliers_people(html):
    page = soup(html)
    grid = page.select_one("main .grid")
    if grid is None:
        return []
    cohorts = []
    for group in grid.find_all("div", recursive=False):
        heading = group.find("div", recursive=False)
        heading_text = clean_text(heading.get_text(" ")) if heading else ""
        if not re.match(r"participants\b", heading_text, re.I):
            continue
        start, end, date_text = _year_range(heading_text)
        if not start or not end:
            continue
        people = [{"name": clean_text(anchor.get_text(" ")), "url": anchor.get("href")}
                  for anchor in group.select("ul a[href]") if clean_text(anchor.get_text(" "))]
        if people:
            cohorts.append({"start": start, "end": end, "date_text": date_text, "people": people})
    return cohorts


def _gasworks_dates(text):
    value = clean_text(text)
    match = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s*[–—-]\s*(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{2}|20\d{2})", value)
    if not match:
        return None
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    start_month = months.get(match.group(2))
    end_month = months.get(match.group(4))
    if not start_month or not end_month or start_month > end_month:
        return None
    end_year = int(match.group(5))
    if end_year < 100:
        end_year += 2000
    start = datetime(end_year, start_month, int(match.group(1))).date().isoformat()
    end = datetime(end_year, end_month, int(match.group(3))).date().isoformat()
    return start, end, match.group(0)


def parse_gasworks_archive(html):
    page = soup(html)
    entries = []
    for article in page.select("article.list-item"):
        category = article.select_one("h3")
        heading = article.select_one("h1 a[href]")
        date_heading = article.select_one("h2.date")
        if not category or clean_text(category.get_text(" ")).casefold() != "residency" or not heading or not date_heading:
            continue
        dates = _gasworks_dates(date_heading.get_text(" "))
        name = clean_text(heading.get_text(" "))
        if not dates or not name or dates[0][:4] < "2026":
            continue
        entries.append({"name": name, "url": heading.get("href"), "start": dates[0], "end": dates[1],
                        "date_text": clean_text(date_heading.get_text(" "))})
    return entries


def parse_delfina_residencies(html):
    page = soup(html)
    entries = []
    for panel in page.select(".panel_item"):
        heading = panel.select_one(".panel_content h2")
        link = panel.select_one("a.panel_link[href]")
        content = panel.select_one(".panel_content")
        text = clean_text(content.get_text(" ")) if content else ""
        dates = re.search(r"London:\s*(\d{1,2}/\d{1,2}/20\d{2})\s*[–—-]\s*(\d{1,2}/\d{1,2}/20\d{2})", text)
        if not heading or not link or not dates:
            continue
        start = datetime.strptime(dates.group(1), "%d/%m/%Y").date().isoformat()
        end = datetime.strptime(dates.group(2), "%d/%m/%Y").date().isoformat()
        entries.append({"name": clean_text(heading.get_text(" ")), "url": link.get("href"),
                        "start": start, "end": end, "date_text": dates.group(0)})
    return entries


def parse_bankart_explot(html):
    page = soup(html)
    heading = next((node for node in page.find_all("h3") if "入居作家" in clean_text(node.get_text(" "))), None)
    if heading is None:
        return None
    title = clean_text(heading.get_text(" "))
    period = re.search(r"\[(20\d{2})年(\d{1,2})月\s*[〜～–—-]\s*(20\d{2})年(\d{1,2})月\]", title)
    residents_node = heading.find_next_sibling("p")
    if not period or residents_node is None:
        return None
    names = [clean_text(name) for name in re.split(r"[、,，]", clean_text(residents_node.get_text(" "))) if clean_text(name)]
    if not names:
        return None
    location = next((clean_text(p.get_text(" ")) for p in heading.parent.select("p")
                     if "Yokohama" in p.get_text(" ") or "横浜市" in p.get_text(" ")), None)
    return {"title": "ExPLOT Studio 2026", "date_text": title,
            "start": f"{period.group(1)}-{int(period.group(2)):02d}",
            "end": f"{period.group(3)}-{int(period.group(4)):02d}",
            "residents": names, "city": "Yokohama" if location else None, "country_code": "JP" if location else None}


def parse_rijks_profile(html):
    page = soup(html)
    heading = page.find("h1")
    name = clean_text(heading.get_text(" ")) if heading else ""
    title = page.find("meta", attrs={"property": "og:title"})
    if not title or not name:
        return None
    text = clean_text(page.get_text(" "))
    date_text = clean_text(title.get("content", "").split(",", 1)[-1])
    start, end, displayed = _year_range(date_text)
    if not re.search(r"\bresident\b", text, re.I) or not start or not end:
        return None
    return {"name": name, "start": start, "end": end, "date_text": displayed}


def parse_daad_fellow_profile(html):
    page = soup(html)
    heading = page.find("h1")
    name = clean_text(heading.get_text(" ")) if heading else ""
    text = clean_text(page.get_text(" "))
    year_tag = re.search(r"Music\s*&\s*Sound\s*,\s*(20\d{2})\s*,\s*in Berlin", text)
    if not name or "Award Fellows Overview" not in text or not year_tag:
        return None
    return {"name": name, "year": year_tag.group(1), "date_text": year_tag.group(1),
            "excerpt": year_tag.group(0)}


def _event(ctx, organizer, *, key, event_type, title, title_lang, date_text, start, end=None,
           url, evidence, venue=None, city=None, country_code=None, start_precision="year", end_precision=None):
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type=event_type,
        title=title, title_lang=title_lang, organizer_entity_id=organizer,
        city=city, country_code=country_code, start_date=start, start_precision=start_precision if start else None,
        end_date=end, end_precision=(end_precision or start_precision) if end else None, date_text=date_text, url=url,
        parser_version=PARSER_VERSION, evidence_id=evidence,
    )
    if venue:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown", detail=venue)
    elif not country_code:
        db.add_review(ctx.con, "region", "events", event_id, "venue country unknown",
                      detail="Saved selection/award markup does not identify an event venue and country.")
    ctx.count("parsed")
    return event_id


def _participant(ctx, event_id, evidence, name, role, *, lang, url=None, entity_type="person", use_url_id=False):
    namespace = f"src:{ctx.source_id}"
    id_value = None
    if use_url_id and url:
        namespace = f"{ctx.source_id}_artist"
        id_value = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    entity = db.ensure_entity(
        ctx.con, entity_type=entity_type, name=name, namespace=namespace, id_value=id_value, lang=lang,
        source_id=ctx.source_id, evidence_id=evidence, official_url=urljoin(_SOURCE_BY_ID[ctx.source_id]["base_url"], url) if url else None,
    )
    db.add_participant(ctx.con, event_id, entity, role, name, evidence, "list_markup", "high")
    ctx.count("participants")


def _organizer(ctx, name, entity_type, url):
    return db.ensure_entity(ctx.con, entity_type=entity_type, name=name, namespace=f"src:{ctx.source_id}",
                            source_id=ctx.source_id, official_url=url)


def _collect_studio(ctx):
    response = ctx.fetch(STUDIO_2026_PRESS)
    record = parse_studio_museum(response.text)
    if not record:
        ctx.note("Studio Museum 2026–27 announcement markup did not expose the verified resident roster; no event stored.")
        return
    evidence = ctx.evidence(response, locator="h1: 2026–27 Artists in Residence", excerpt=record["date_text"])
    organizer = _organizer(ctx, "Studio Museum in Harlem", "institution", STUDIO)
    event = _event(ctx, organizer, key="residency-2026-2027", event_type="residency",
                   title="Studio Museum Artists in Residence 2026–27", title_lang="en",
                   date_text=record["date_text"], start=record["start"], end=record["end"],
                   url=response.final_url, evidence=evidence)
    for name in record["residents"]:
        _participant(ctx, event, evidence, name, "resident", lang="en")
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 미주-08-001: only the saved 2026–27 named residency announcement is covered; no cohort completeness claimed.")


def _collect_pivo(ctx):
    organizer = _organizer(ctx, "Pivô", "institution", PIVO)
    for url in (PIVO_2019, PIVO_2022):
        response = ctx.fetch(url)
        record = parse_pivo_announcement(response.text)
        if not record:
            ctx.note(f"Pivô saved cohort page no longer matches its observed year-bearing selection markup: {url}")
            continue
        names = record["residents"]
        excerpt = f"{record['year']} residents: {', '.join(names)}"
        evidence = ctx.evidence(response, locator="article heading and named resident selection paragraph", excerpt=excerpt)
        if record["year"] == "2019":
            event = _event(ctx, organizer, key="residency-2019-selected", event_type="residency",
                           title="Pivô Pesquisa 2019 — Bolsa Residência", title_lang="pt",
                           date_text=record["date_text"], start=record["year"], url=response.final_url, evidence=evidence)
            for name in names:
                _participant(ctx, event, evidence, name, "resident", lang="pt")
            invite = record.get("invite_winner")
            if invite:
                award = _event(ctx, organizer, key="bolsa-convite-2019", event_type="award",
                              title="Pivô Pesquisa 2019 — bolsa-convite", title_lang="pt",
                              date_text=record["date_text"], start=record["year"], url=response.final_url, evidence=evidence)
                _participant(ctx, award, evidence, invite, "winner", lang="pt")
        else:
            event = _event(ctx, organizer, key=f"residency-{record['year']}-cycle-iii", event_type="residency",
                           title=record["title"], title_lang="pt", date_text=record["date_text"],
                           start=record["year"], url=response.final_url, evidence=evidence)
            for name in names:
                entity_type = "group" if name == "Amador e Jr Segurança Patrimonial LTDA" else "person"
                profile = record.get("resident_urls", {}).get(name)
                _participant(ctx, event, evidence, name, "resident", lang="pt", url=profile,
                             entity_type=entity_type, use_url_id=bool(profile))
            curator = record.get("curator")
            if curator:
                _participant(ctx, event, evidence, curator, "curator", lang="pt")
        ctx.count("fetched", 1)
    ctx.note("Sourcebook 미주-08-007: only the saved 2019 and 2022 result/cohort announcements are covered; no history completeness claimed.")


def _collect_adiaf(ctx):
    overview_response = ctx.fetch(ADIAF_PRIZE_OVERVIEW)
    if not parse_adiaf_overview(overview_response.text):
        ctx.note("ADIAF overview did not expose the saved four-nominee/one-laureate award rule; no 2024 roles stored.")
        return
    article_response = ctx.fetch(ADIAF_2024_ARTICLE)
    article = parse_adiaf_article(article_response.text)
    if not article or article["year"] != "2024":
        ctx.note("ADIAF 2024 award article did not expose the expected year and named artists; no event stored.")
        return
    roster_response = ctx.fetch(ADIAF_ARTISTS, params={"_sfm_date_nomination": "2024"})
    roster = parse_adiaf_roster(roster_response.text, "2024")
    if not roster:
        ctx.note("ADIAF public 2024 nomination-year filter exposed no artist cards; no 2024 award roles stored.")
        return
    article_by_key = {db.name_key(item["name"]): item for item in article["artists"]}
    roster_by_key = {db.name_key(item["name"]): item for item in roster}
    matched = [(article_by_key[key], roster_by_key[key]) for key in sorted(article_by_key.keys() & roster_by_key.keys())]
    if not matched or not any(row[1]["role"] == "winner" for row in matched):
        ctx.note("ADIAF 2024 article and filtered artists roster did not yield a matching named laureate; no event stored.")
        return
    overview_evidence = ctx.evidence(overview_response, locator="award selection overview", excerpt="one laureate among four nominated artists")
    article_evidence = ctx.evidence(article_response, locator="#fade artist cards and 2024 prize heading",
                                    excerpt="Prix Marcel Duchamp 2024: four named artists")
    roster_evidence = ctx.evidence(roster_response, locator="nomination-year filter and artist cards for 2024",
                                   excerpt="2024 nomination cards; laureate label preserved")
    organizer = _organizer(ctx, "ADIAF", "foundation", ADIAF)
    event = _event(ctx, organizer, key="prix-marcel-duchamp-2024", event_type="award",
                   title="Prix Marcel Duchamp 2024", title_lang="fr", date_text="2024", start="2024",
                   url=article_response.final_url, evidence=article_evidence,
                   venue="2024 award page separately documents a 2025 Art Genève exhibition; no award venue asserted")
    for evidence in (overview_evidence, roster_evidence):
        ctx.con.execute("INSERT INTO event_evidence(event_id,evidence_id) VALUES(?,?) ON CONFLICT DO NOTHING", (event, evidence))
    for item, result in matched:
        role = result["role"]
        participant_evidence = roster_evidence if role == "winner" else article_evidence
        if item["name"] == "Angela DETANICO et Rafael LAIN":
            entity_type = "group"
        else:
            entity_type = "person"
        _participant(ctx, event, participant_evidence, item["name"], role, lang="fr", url=result["url"],
                     entity_type=entity_type, use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 유럽-08-008: the 2024 award edition only; award year is distinct from the 2025 Art Genève exhibition dates.")


def _collect_willing(ctx):
    for url in (WILLING_CHONG_KUN_DANG_2024, WILLING_KIAF_2025):
        response = ctx.fetch(url)
        record = parse_willing_award(response.text)
        if not record:
            ctx.note(f"Willing N Dealing saved award post no longer matches its observed explicit selection text: {url}")
            continue
        evidence = ctx.evidence(response, locator="award-selection announcement text", excerpt=record["excerpt"])
        event = _event(ctx, None, key=f"{record['event_type']}-{record['year']}-{db.name_key(record['title'])}",
                       event_type=record["event_type"], title=record["title"], title_lang="ko",
                       date_text=record["title"], start=record["year"], url=response.final_url, evidence=evidence)
        for name in record["names"]:
            _participant(ctx, event, evidence, name, record["role"], lang="ko")
        ctx.count("fetched", 1)
    ctx.note("Sourcebook 한국-08-005: two gallery-posted award reports only; award organizers and unobserved years are not inferred.")


def _collect_bemis(ctx):
    response = ctx.fetch(BEMIS_AYDO)
    record = parse_bemis_profile(response.text)
    if not record:
        ctx.note("Bemis AYDO profile did not expose an explicit artist-in-residence season; no event stored.")
        return
    evidence = ctx.evidence(response, locator="artist name and Artist-in-Residence season", excerpt=record["date_text"])
    organizer = _organizer(ctx, "Bemis Center for Contemporary Arts", "institution", BEMIS)
    event = _event(ctx, organizer, key="residency-fall-2026-aydo", event_type="residency",
                   title=f"Bemis Center Artist-in-Residence {record['date_text']}", title_lang="en",
                   date_text=record["date_text"], start=record["year"], url=response.final_url, evidence=evidence)
    _participant(ctx, event, evidence, record["name"], "resident", lang="en", url=response.final_url,
                 entity_type=record["entity_type"], use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 미주-08-005: one explicitly labeled Fall 2026 profile only; cohort completeness is not claimed.")


def _collect_fonderie(ctx):
    response = ctx.fetch(FONDERIE_BY_YEAR)
    entries = parse_fonderie_by_year(response.text)
    if not entries:
        ctx.note("Fonderie by-year archive exposed no named entries under its 2026 separator; no event stored.")
        return
    grouped = {}
    for item in entries:
        grouped.setdefault(item["program"], []).append(item)
    evidence = ctx.evidence(response, locator="2026 separator and year-indexed residence cards",
                            excerpt=f"2026 archive entries: {', '.join(item['name'] for item in entries)}")
    organizer = _organizer(ctx, "Fonderie Darling", "institution", FONDERIE)
    for program, people in grouped.items():
        event = _event(ctx, organizer, key=f"residency-2026-{db.name_key(program)}", event_type="residency",
                       title=f"{program} — Fonderie Darling 2026", title_lang="fr", date_text="2026", start="2026",
                       url=response.final_url, evidence=evidence)
        for item in people:
            profile = urljoin(response.final_url, item["url"])
            _participant(ctx, event, evidence, item["name"], "resident", lang="fr", url=profile, use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 미주-08-006: only the 2026 entries grouped by program on the saved by-year page are collected.")


def _collect_rijks(ctx):
    response = ctx.fetch(RIJKS_FARREN)
    record = parse_rijks_profile(response.text)
    if not record:
        ctx.note("Rijksakademie profile did not expose a named resident and explicit year range; no event stored.")
        return
    evidence = ctx.evidence(response, locator="profile name, resident label, and displayed year range",
                            excerpt=record["date_text"])
    organizer = _organizer(ctx, "Rijksakademie", "institution", RIJKSAKADEMIE)
    event = _event(ctx, organizer, key="residency-2026-2027-farren-linhares", event_type="residency",
                   title="Rijksakademie Residency 2026–2027", title_lang="en", date_text=record["date_text"],
                   start=record["start"], end=record["end"], url=response.final_url, evidence=evidence)
    _participant(ctx, event, evidence, record["name"], "resident", lang="en", url=response.final_url, use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 유럽-08-001: one saved 2026–27 resident profile only; cohort completeness is not claimed.")


def _collect_daad(ctx):
    profiles = []
    for url in DAAD_2026_PROFILES:
        response = ctx.fetch(url)
        ctx.count("fetched", 1)
        record = parse_daad_fellow_profile(response.text)
        if not record:
            ctx.note(f"DAAD profile did not expose the Award Fellows breadcrumb and year-tagged Music & Sound status: {url}")
            continue
        evidence = ctx.evidence(response, locator="Award Fellows breadcrumb and Music & Sound year/location label",
                                excerpt=record["excerpt"])
        profiles.append((response, record, evidence))
    if not profiles:
        return
    organizer = _organizer(ctx, "Berliner Künstlerprogramm des DAAD", "institution", DAAD)
    first_evidence = profiles[0][2]
    event = _event(ctx, organizer, key="award-2026-award-fellows", event_type="award",
                   title="Berliner Künstlerprogramm 2026 Award Fellows", title_lang="en",
                   date_text="2026", start="2026", url=DAAD_AWARD_FELLOWS, evidence=first_evidence,
                   city="Berlin", country_code="DE")
    for response, record, evidence in profiles:
        if evidence != first_evidence:
            ctx.con.execute("INSERT INTO event_evidence(event_id,evidence_id) VALUES(?,?) ON CONFLICT DO NOTHING",
                            (event, evidence))
        _participant(ctx, event, evidence, record["name"], "winner", lang="en", url=response.final_url,
                     use_url_id=True)
    ctx.note("Sourcebook 유럽-08-006: only two saved 2026 Music & Sound Award Fellows profiles are collected; full-cohort completeness is not claimed.")


def _collect_de_ateliers(ctx):
    response = ctx.fetch(DE_ATELIERS_PEOPLE)
    cohorts = parse_de_ateliers_people(response.text)
    if not cohorts:
        ctx.note("De Ateliers people page exposed no year-labeled participant cohort; no event stored.")
        return
    evidence = ctx.evidence(response, locator="participants section and displayed cohort year ranges",
                            excerpt="; ".join(f"{cohort['date_text']}: {', '.join(person['name'] for person in cohort['people'])}"
                                              for cohort in cohorts))
    organizer = _organizer(ctx, "De Ateliers", "institution", DE_ATELIERS)
    for cohort in cohorts:
        event = _event(ctx, organizer, key=f"residency-{cohort['start']}-{cohort['end']}", event_type="residency",
                       title=f"De Ateliers Participants {cohort['date_text']}", title_lang="en",
                       date_text=cohort["date_text"], start=cohort["start"], end=cohort["end"],
                       url=response.final_url, evidence=evidence)
        for person in cohort["people"]:
            _participant(ctx, event, evidence, person["name"], "resident", lang="en", url=person["url"], use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 유럽-08-002: only the 2025–27 and 2026–28 participant cohorts shown in the saved people page are collected.")


def _collect_gasworks(ctx):
    response = ctx.fetch(GASWORKS_ARCHIVE)
    entries = parse_gasworks_archive(response.text)
    if not entries:
        ctx.note("Gasworks archive exposed no dated 2026/2027 residency cards; no event stored.")
        return
    grouped = {}
    for item in entries:
        grouped.setdefault((item["start"], item["end"], item["date_text"]), []).append(item)
    evidence = ctx.evidence(response, locator="dated 2026/2027 residency archive cards",
                            excerpt=f"2026/2027 dated archive entries: {', '.join(item['name'] for item in entries)}")
    organizer = _organizer(ctx, "Gasworks", "institution", GASWORKS)
    for (start, end, date_text), people in grouped.items():
        event = _event(ctx, organizer, key=f"residency-{start}-{end}", event_type="residency",
                       title=f"Gasworks Residency {date_text}", title_lang="en", date_text=date_text,
                       start=start, end=end, start_precision="day", end_precision="day",
                       url=response.final_url, evidence=evidence)
        for person in people:
            _participant(ctx, event, evidence, person["name"], "resident", lang="en", url=person["url"],
                         use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 유럽-08-004: only the 2026/2027 dated residency cycles visible in the saved archive page are collected.")


def _collect_delfina(ctx):
    response = ctx.fetch(DELFINA_RESIDENCIES)
    entries = parse_delfina_residencies(response.text)
    if not entries:
        ctx.note("Delfina in-residence page exposed no named people with displayed residency dates; no event stored.")
        return
    grouped = {}
    for item in entries:
        grouped.setdefault((item["start"], item["end"], item["date_text"]), []).append(item)
    evidence = ctx.evidence(response, locator="2026 current/future/past resident cards and displayed stay dates",
                            excerpt=f"2026 residency cards: {', '.join(item['name'] for item in entries)}")
    organizer = _organizer(ctx, "Delfina Foundation", "foundation", DELFINA)
    for (start, end, date_text), people in grouped.items():
        event = _event(ctx, organizer, key=f"residency-{start}-{end}", event_type="residency",
                       title=f"Delfina Foundation Residency {start} — {end}", title_lang="en",
                       date_text=date_text, start=start, end=end, start_precision="day", end_precision="day",
                       url=response.final_url, evidence=evidence, city="London", country_code="GB")
        for person in people:
            _participant(ctx, event, evidence, person["name"], "resident", lang="en", url=person["url"],
                         use_url_id=True)
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 유럽-08-005: only dated 2026 resident cards in the saved listing are collected.")


def _collect_bankart(ctx):
    response = ctx.fetch(BANKART_EXPLOT)
    record = parse_bankart_explot(response.text)
    if not record:
        ctx.note("BankART ExPLOT page did not expose the 2026 resident list and month range; no event stored.")
        return
    evidence = ctx.evidence(response, locator="ExPLOT Studio 2026 period, resident names, and venue address",
                            excerpt=f"{record['date_text']}: {', '.join(record['residents'])}")
    organizer = _organizer(ctx, "BankART1929", "institution", BANKART)
    event = _event(ctx, organizer, key="explot-studio-residency-2026", event_type="residency",
                   title=record["title"], title_lang="en", date_text=record["date_text"],
                   start=record["start"], end=record["end"], start_precision="month", end_precision="month",
                   url=response.final_url, evidence=evidence, city=record["city"], country_code=record["country_code"])
    for name in record["residents"]:
        _participant(ctx, event, evidence, name, "resident", lang="ja")
    ctx.count("fetched", 1)
    ctx.note("Sourcebook 일본-08-002: only the saved ExPLOT Studio 2026 resident cohort and displayed June–March period are collected.")


def collect(ctx):
    handlers = {
        "wave2_studio_museum_residencies": _collect_studio,
        "wave2_pivo_residencies": _collect_pivo,
        "wave2_adiaf_prize": _collect_adiaf,
        "wave2_willingndealing_awards": _collect_willing,
        "wave2_bemis_residencies": _collect_bemis,
        "wave2_fonderie_residencies": _collect_fonderie,
        "wave2_rijksakademie_residencies": _collect_rijks,
        "wave2_daad_fellows_2026": _collect_daad,
        "wave2_de_ateliers_residencies": _collect_de_ateliers,
        "wave2_gasworks_residencies": _collect_gasworks,
        "wave2_delfina_residencies": _collect_delfina,
        "wave2_bankart_residencies": _collect_bankart,
    }
    handler = handlers.get(ctx.source_id)
    if handler is None:
        raise ValueError(f"Unknown source_id: {ctx.source_id}")
    handler(ctx)
    ctx.con.commit()
