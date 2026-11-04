"""Wave-2 public report catalogues with bounded metadata-only extraction.

Report bodies and images are never fetched or parsed. Canadian Heritage is the sole
source allowed to store explicitly linked official PDFs internally, without extracting text.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import db
from ..http import Blocked, FetchError
from ._common import clean_text, soup

PARSER_VERSION = "wave2_reports-2"


def _row(source_id, name, owner, region, country, base, entry, terms, collection_terms, notes,
         max_requests=20, access_method="html", storage_policy="metadata_only"):
    return dict(source_id=source_id, blueprint_data_id=None, blueprint_org_id=None, name=name,
                owner_group=owner, source_kind="report", region_scope=region, country_codes=country,
                access_method=access_method, base_url=base, entry_url=entry, terms_url=terms,
                text_storage_policy=storage_policy, priority="P2", st_official_doc="n/a(public metadata)",
                st_collection_terms=collection_terms, st_image_terms="Images are not fetched; file handling is described per source; image rights are not inferred.",
                max_requests=max_requests, notes=notes)


SOURCES = [
    _row("wave2_reports_nea", "National Endowment for the Arts — Research Publications", "National Endowment for the Arts",
         "AMERICAS", "US", "https://www.arts.gov", "https://www.arts.gov/impact/research/publications", None,
         "Only title, displayed publication year and official listing URL are retained. No report body or PDF is fetched; a terms page was not present in the saved evidence.",
         "Sourcebook 미주-06-002. First public publications-list page only; this is a bounded sample, not a complete archive.", 5),
    _row("wave2_reports_statcan", "Statistics Canada — WDS catalogue", "Statistics Canada", "AMERICAS", "CA",
         "https://www.statcan.gc.ca", "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite",
         "https://www.statcan.gc.ca/en/terms-conditions",
         "The opened Statistics Canada terms state the Open Licence permits use and redistribution of most data products; third-party materials may be restricted. Only WDS catalogue metadata is retained; no table data is fetched.",
         "Sourcebook 미주-06-003. Documented public WDS getAllCubesListLite; catalogued art/culture/heritage titles only, not a full cultural-statistics inventory.", 3, "api"),
    _row("wave2_reports_canada_heritage", "Canadian Heritage — Survey of Heritage Institutions", "Department of Canadian Heritage",
         "AMERICAS", "CA", "https://www.canada.ca",
         "https://www.canada.ca/en/canadian-heritage/corporate/publications/general-publications/about-survey-heritage-institutions.html",
         "https://www.canada.ca/en/transparency/terms.html",
         "Canada.ca terms permit non-commercial reproduction with attribution and identify third-party rights exceptions. Listing/detail HTML is not archived; only explicitly linked official PDF files may be stored internally, without text extraction.",
         "Sourcebook 미주-06-004. Initial mode follows report landing pages from 2017 onward; incremental mode checks only the newest listed edition.", 20, storage_policy="raw_internal"),
    _row("wave2_reports_ibermuseos", "Ibermuseos — sampled public publications", "Ibermuseos", "GLOBAL", "",
         "https://www.ibermuseos.org", "https://www.ibermuseos.org/recursos/publicaciones/", None,
         "Only public landing-page metadata and explicitly linked official PDF URLs are retained. A terms page was not present in the saved evidence; no document body or file is fetched.",
         "Sourcebook 미주-06-005. Two publication detail pages recovered from saved evidence; this is a sample, not a complete publications archive.", 5),
    _row("wave2_reports_imls", "Institute of Museum and Library Services — data and surveys", "Institute of Museum and Library Services",
         "AMERICAS", "US", "https://www.imls.gov", "https://www.imls.gov/research-evaluation/data",
         "https://www.imls.gov/about/privacy-terms",
         "The opened IMLS policy page says works prepared by IMLS officers/employees in scope of employment are public domain, while third-party works may remain protected. Only public catalogue labels and official links are retained.",
         "Sourcebook 미주-06-006. Data and survey index cards only; historical data files and their methodologies are not downloaded or parsed.", 5),
    _row("wave2_reports_ncar", "National Center for Art Research — awareness survey reports", "National Center for Art Research, Japan",
         "JP", "JP", "https://ncar.artmuseums.go.jp", "https://ncar.artmuseums.go.jp/research/awareness-surveys.html",
         "https://ncar.artmuseums.go.jp/sitepolicy.html",
         "The opened site policy reserves content copyright to NCAR and information providers and limits reuse beyond private use. Collector stores catalogue metadata only; no report body or PDF is fetched.",
         "Sourcebook 日本-06-002. Awareness-survey index only, including the visible historical links; not all NCAR publications.", 12),
    _row("wave2_reports_bunka", "Agency for Cultural Affairs — statistics and white papers", "Agency for Cultural Affairs, Government of Japan",
         "JP", "JP", "https://www.bunka.go.jp", "https://www.bunka.go.jp/tokei_hakusho_shuppan/",
         "https://www.bunka.go.jp/chosakuken/index.html",
         "The existing Bunka report source records government-publication reuse per site terms with attribution. This collector stores listing titles/URLs only and does not fetch documents.",
         "Sourcebook 日本-06-006. One statistics/research listing and one white-paper/annual-report listing; no claim of complete cultural-policy coverage.", 6),
    _row("wave2_reports_arko", "Arts Council Korea — research and annual-report indexes", "Arts Council Korea",
         "KR", "KR", "https://www.arko.or.kr", "https://www.arko.or.kr/board/list/4009",
         "https://www.arko.or.kr/common/guide/copyright",
         "The opened copyright policy says site materials are protected and free use applies only to works marked KOGL Type 1; this collector keeps listing metadata and official page URLs only, with no report files fetched.",
         "Sourcebook 한국-06-005. Bounded to policy research, current-status and annual-report indexes; no grant-selection inference.", 8),
    _row("wave2_reports_kiaf", "Kiaf SEOUL — Kiaf Report", "Galleries Association of Korea / Kiaf SEOUL",
         "KR", "KR", "https://kiaf.org", "https://kiaf.org/en/about-report", "https://kiaf.org/terms-conditions",
         "The saved sourcebook evidence says report content is reserved to Kiaf/exhibitors and reuse requires permission. A bounded Fetcher probe of the linked Terms page returned HTTP 200 with robots parsed, but the main page exposed no readable terms text. Keep metadata and direct public PDF links only; do not fetch the PDFs.",
         "Sourcebook 한국-06-006. The public About-report page exposes a 2021 report and language links; survey sample/method details are not collected.", 4),
    _row("wave2_reports_eurostat", "Eurostat — Culture data-domain catalogue", "Eurostat / European Commission",
         "EUROPE", "", "https://ec.europa.eu", "https://ec.europa.eu/eurostat/web/culture/database/data-domain",
         "https://ec.europa.eu/eurostat/help/copyright-notice",
         "The copyright notice permits reuse of editorial content under CC BY 4.0 and reuse of statistical data/metadata/publications with source acknowledgement, subject to third-party notices. The collector records only visible catalogue titles and official dataset/publication URLs; no values or files are fetched.",
         "Sourcebook 유럽-06-006. Public Eurostat Culture data-domain page exposes official dataset bookmarks and publication/file links; one rendered catalogue page only, no data values.", 3),
    _row("wave2_reports_gokams", "GOKAMS — public research and publication catalogue", "예술경영지원센터 (KAMS / GOKAMS)",
         "KR", "KR", "https://www.gokams.or.kr", "https://www.gokams.or.kr/05_know/data_list.aspx",
         "https://www.gokams.or.kr/01_news/notice_view.aspx?Idx=3969",
         "The public publication-list route returned HTTP 200 with robots parsed. The linked policy/notice route is disallowed by robots and was not fetched; no reuse terms are inferred. Store report-title, displayed issue-month and detail-link metadata only; do not fetch details, attachments or files.",
         "Sourcebook 한국-06-001. First public listing page; filter explicit report/research/statistics titles; the existing K-ARTMARKET source remains separate.", 3),
]


_NEA_YEAR = re.compile(r"^20\d{2}$")
_STATCAN_TERMS = re.compile(r"\b(?:art|arts|museum|museums|gallery|galleries|culture|cultural|heritage)\b", re.I)
_CANADA_REPORT_PATH = re.compile(r"/(20\d{2})-report\.html$", re.I)
_ES_MONTHS = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
    "julio": "07", "agosto": "08", "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}
_KIAF_HOST = "static-edge.kiaf.org"
_IBERMUSEOS_PAGES = (
    "https://www.ibermuseos.org/recursos/publicaciones/panorama-de-los-museos-en-iberoamerica-edicion-2020/",
    "https://www.ibermuseos.org/recursos/publicaciones/informe-anual-2024/",
)
_BUNKA_LISTS = (
    "https://www.bunka.go.jp/tokei_hakusho_shuppan/tokeichosa/index.html",
    "https://www.bunka.go.jp/tokei_hakusho_shuppan/hakusho_nenjihokokusho/index.html",
)
_ARKO_LISTS = (
    "https://www.arko.or.kr/board/list/4009",
    "https://www.arko.or.kr/board/list/5476",
    "https://www.arko.or.kr/board/list/5034",
)
_IMLS_LISTS = (
    "https://www.imls.gov/research-evaluation/data",
    "https://www.imls.gov/research-evaluation/surveys",
)
_GOKAMS_REPORT_TITLE = re.compile(r"(?:보고서|연구|조사|통계|백서|연감|report|study|survey|statistics)", re.I)
_GOKAMS_MONTH = re.compile(r"\b(20\d{2})[.\-/]\s*(0?[1-9]|1[0-2])\b")


def _official_url(base_url, href, extra_hosts=()):
    url = urllib.parse.urljoin(base_url, (href or "").strip())
    parts = urllib.parse.urlsplit(url)
    base_host = (urllib.parse.urlsplit(base_url).hostname or "").lower()
    host = (parts.hostname or "").lower()
    allowed = host == base_host or host.endswith("." + base_host) or host in extra_hosts
    if parts.scheme != "https" or not allowed:
        return None
    return url


def _record(ctx, *, key, title, publisher, geo_scope, official_url, access_status, rights_note,
            published_date=None, observation_period=None, methodology=None, sample=None, pages=None,
            local_path=None, sha256=None, notes=None):
    report_id = db.sid("rpt", ctx.source_id, key)
    old = ctx.con.execute("SELECT title, official_url, access_status, local_path, sha256 FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if old is None:
        ctx.count("inserted")
    elif tuple(old) == (title, official_url, access_status, local_path, sha256):
        ctx.count("unchanged")
    else:
        ctx.count("updated")
    ctx.con.execute(
        "INSERT INTO reports(report_id,title,publisher,published_date,observation_period,geo_scope,methodology,sample,"
        "official_url,local_path,sha256,pages,rights_note,access_status,next_check,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(report_id) DO UPDATE SET title=excluded.title,publisher=excluded.publisher,"
        "published_date=COALESCE(excluded.published_date,reports.published_date),"
        "observation_period=COALESCE(excluded.observation_period,reports.observation_period),"
        "geo_scope=COALESCE(excluded.geo_scope,reports.geo_scope),"
        "methodology=COALESCE(excluded.methodology,reports.methodology),sample=COALESCE(excluded.sample,reports.sample),"
        "official_url=excluded.official_url,local_path=COALESCE(excluded.local_path,reports.local_path),"
        "sha256=COALESCE(excluded.sha256,reports.sha256),pages=COALESCE(excluded.pages,reports.pages),rights_note=excluded.rights_note,"
        "access_status=excluded.access_status,next_check=excluded.next_check,notes=excluded.notes",
        (report_id, title, publisher, published_date, observation_period, geo_scope, methodology, sample,
         official_url, local_path, sha256, pages, rights_note, access_status, "check on next source run", notes))
    ctx.count("parsed")
    ctx.con.commit()
    return report_id


def _store_listing_record(ctx, response, record, *, locator, publisher, geo_scope, rights_note, sourcebook_id):
    ev = ctx.evidence(response, locator=f"{locator}: {record['key']}", excerpt=record["title"])
    _record(ctx, key=record["key"], title=record["title"], publisher=publisher, geo_scope=geo_scope,
            published_date=record.get("published_date"), observation_period=record.get("observation_period"),
            official_url=record["official_url"], pages=record.get("pages"),
            local_path=record.get("local_path"), sha256=record.get("sha256"),
            access_status=record.get("access_status", "link_only(public metadata; report file not fetched)"),
            rights_note=rights_note,
            notes=f"Sourcebook {sourcebook_id}; metadata-only listing evidence {ev}; {record.get('notes', '')}".strip())


def parse_nea_publications(html, base_url):
    """Parse the public NEA teaser cards, deliberately ignoring their descriptive body copy."""
    out, seen = [], set()
    for card in soup(html).select("article.teaser"):
        link = card.select_one("a.teaser__link[href]")
        year_node = card.select_one(".teaser__date")
        title_node = card.select_one(".teaser__title")
        year = clean_text(year_node.get_text(" ")) if year_node else ""
        title = clean_text(title_node.get_text(" ")) if title_node else ""
        url = _official_url(base_url, link.get("href")) if link else None
        if not title or not url or not _NEA_YEAR.fullmatch(year) or url in seen:
            continue
        seen.add(url)
        out.append({"key": url, "title": title, "published_date": year, "official_url": url,
                    "access_status": "link_only(public listing metadata; report page and file not fetched)"})
    return out


def parse_statcan_cubes(payload):
    """Filter the documented WDS cube catalogue to directly relevant culture-sector titles."""
    if not isinstance(payload, list):
        return []
    out, seen = [], set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        product_id = item.get("productId")
        title = clean_text(item.get("cubeTitleEn") or item.get("cubeTitleFr"))
        if not title or not str(product_id).isdigit() or not _STATCAN_TERMS.search(title):
            continue
        product_id = str(product_id)
        if product_id in seen:
            continue
        seen.add(product_id)
        start = (item.get("cubeStartDate") or "")[:10]
        end = (item.get("cubeEndDate") or "")[:10]
        period = f"{start} to {end}" if start and end else None
        issue = (item.get("issueDate") or "")[:10] or None
        out.append({"key": product_id, "title": title, "published_date": issue,
                    "observation_period": period,
                    "official_url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={product_id}",
                    "access_status": "link_only(WDS catalogue metadata; table values not fetched)"})
    return out


def parse_canada_heritage_index(html, base_url):
    out, seen = [], set()
    for link in soup(html).find_all("a", href=True):
        url = _official_url(base_url, link["href"])
        match = _CANADA_REPORT_PATH.search(urllib.parse.urlsplit(url or "").path)
        if not url or not match or url in seen:
            continue
        title = clean_text(link.get_text(" "))
        if not title:
            continue
        seen.add(url)
        out.append({"year": int(match.group(1)), "title": title, "url": url})
    return sorted(out, key=lambda item: item["year"], reverse=True)


def parse_canada_heritage_report(html, page_url):
    page = soup(html)
    title_meta = page.select_one('meta[name="dcterms.title"]')
    issued_meta = page.select_one('meta[name="dcterms.issued"]')
    h1 = page.select_one("h1#wb-cont")
    title = clean_text((title_meta.get("content") if title_meta else None) or
                       (h1.get_text(" ") if h1 else ""))
    if not title:
        return None
    published = (issued_meta.get("content") if issued_meta else None) or None
    pdf_url = None
    for link in page.select("a.gc-dwnld-lnk[href]"):
        candidate = _official_url(page_url, link.get("href"))
        if candidate and urllib.parse.urlsplit(candidate).path.lower().endswith(".pdf"):
            pdf_url = candidate
            break
    return {"title": title, "published_date": published, "pdf_url": pdf_url}


def _download_public_pdf(ctx, url):
    """Persist an explicitly linked, permitted PDF without parsing its contents."""
    if not url:
        return {}
    try:
        response = ctx.fetch(url, accept="application/pdf", store=True)
    except FetchError as exc:
        return {"access_status": "not_downloaded", "notes": f"Direct PDF request failed: {exc}"}
    if "pdf" not in response.content_type.lower() and not response.content.startswith(b"%PDF-"):
        return {"access_status": "not_pdf", "notes": f"Direct file URL returned {response.content_type}, not PDF; body not parsed."}
    if not response.raw_path:
        return {"access_status": "not_stored", "notes": "Fetcher returned PDF bytes without a project-local stored path."}
    ctx.count("fetched")
    evidence = ctx.evidence(response, locator="direct official PDF; signature checked; contents not parsed")
    return {"local_path": response.raw_path, "sha256": response.sha256,
            "access_status": "downloaded(public official PDF; no text extraction)",
            "notes": f"Direct PDF download evidence {evidence}; bytes stored under project raw path, contents not parsed."}


def parse_imls_cards(html, base_url):
    out, seen = [], set()
    for card in soup(html).select(".grid-row.image_left"):
        title_node = card.select_one(".field--name-field-title-image-content")
        link = card.select_one(".field--name-field-link-image-content a[href]")
        title = clean_text(title_node.get_text(" ")) if title_node else ""
        url = _official_url(base_url, link.get("href")) if link else None
        if not title or not url or url in seen:
            continue
        seen.add(url)
        out.append({"key": url, "title": title, "official_url": url,
                    "access_status": "link_only(public IMLS catalogue card; destination not fetched)"})
    return out


def _spanish_month_date(text):
    match = re.search(r"\bFecha\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+de\s+(20\d{2})\b", text or "", re.I)
    if not match:
        return None
    month = _ES_MONTHS.get(match.group(1).casefold())
    return f"{match.group(2)}-{month}" if month else None


def parse_ibermuseos_publication(html, page_url):
    page = soup(html)
    h1 = page.find("h1")
    title = clean_text(h1.get_text(" ")) if h1 else ""
    if not title:
        return None
    text = clean_text(" ".join(x.get_text(" ") for x in page.select(".side-col-item")))
    date = _spanish_month_date(text)
    pages_match = re.search(r"Número de Páginas\s+(\d+)", text, re.I)
    pdfs = []
    for link in page.find_all("a", href=True):
        url = _official_url(page_url, link.get("href"))
        if url and (urllib.parse.urlsplit(url).path.lower().endswith(".pdf")):
            pdfs.append((clean_text(link.get_text(" ")).casefold(), url))
    pdf_url = next((url for label, url in pdfs if "español" in label), None)
    if pdf_url is None and pdfs:
        pdf_url = pdfs[0][1]
    return {"title": title, "published_date": date, "pdf_url": pdf_url,
            "pages": int(pages_match.group(1)) if pages_match else None}


def parse_ncar_awareness_index(html, base_url):
    out, seen = [], set()
    for link in soup(html).select('main a[href^="/reports/"]'):
        title = clean_text(link.get_text(" "))
        url = _official_url(base_url, link.get("href"))
        if not title or not url or "調査" not in title or url in seen or "すべての活動レポート" in title:
            continue
        seen.add(url)
        year = re.search(r"(20\d{2})年度", title)
        out.append({"key": url, "title": title, "official_url": url,
                    "observation_period": f"{year.group(1)}年度 (as titled)" if year else None,
                    "access_status": "link_only(public awareness-survey index; report page and file not fetched)"})
    return out


def parse_bunka_listing(html, base_url):
    out, seen = [], set()
    for link in soup(html).find_all("a", href=True):
        title = clean_text(link.get_text(" "))
        url = _official_url(base_url, link.get("href"))
        if not title or not url or url in seen:
            continue
        path = urllib.parse.urlsplit(url).path.lower()
        is_pdf = path.endswith(".pdf")
        if title in {"統計・白書・出版物", "統計・調査研究等", "白書・年次報告等", "出版物・パンフレット等"}:
            continue
        if path.endswith("/index.html") and not is_pdf:
            continue
        is_report = any(word in title for word in ("調査", "報告書", "白書", "年次報告", "統計"))
        if not is_pdf and not is_report:
            continue
        seen.add(url)
        out.append({"key": url, "title": title, "official_url": url,
                    "access_status": "link_only(public official listing/file URL; file not fetched)"})
    return out


def parse_eurostat_culture_domain(html, base_url):
    """Parse visible Eurostat culture dataset/publication links, never their data values."""
    out, seen = [], set()
    for link in soup(html).find_all("a", href=True):
        title = clean_text(link.get_text(" "))
        url = _official_url(base_url, link.get("href"))
        if not title or not url or url in seen:
            continue
        path = urllib.parse.urlsplit(url).path.lower()
        is_dataset = "/databrowser/bookmark/" in path or "/databrowser/view/" in path
        is_publication = "/eurostat/documents/" in path or path.endswith((".pdf", ".xlsx"))
        if not is_dataset and not is_publication:
            continue
        seen.add(url)
        period_match = re.search(r"\b(20\d{2})\s*[-–—]\s*(20\d{2})\b", title)
        period = f"{period_match.group(1)}-{period_match.group(2)}" if period_match else None
        out.append({"key": url, "title": title, "official_url": url, "observation_period": period,
                    "access_status": "link_only(public Eurostat catalogue metadata; data values and files not fetched)"})
    return out


def parse_arko_listing(html, base_url):
    out, seen = [], set()
    for link in soup(html).find_all("a", href=True):
        url = _official_url(base_url, link.get("href"))
        title = clean_text(link.get_text(" "))
        if not url or not title or url in seen:
            continue
        path = urllib.parse.urlsplit(url).path
        if not re.search(r"/board/view/\d+", path):
            continue
        seen.add(url)
        out.append({"key": url, "title": title, "official_url": url,
                    "access_status": "link_only(public ARKO listing detail; report page and file not fetched)"})
    return out


def parse_gokams_listing(html, base_url):
    """Parse first-page GOKAMS research/report rows; do not follow detail or attachment links."""
    out, seen = [], set()
    for row in soup(html).select("table.boardList tr"):
        link = row.select_one('a[href*="data_view.aspx"]')
        title = clean_text(link.get_text(" ")) if link else ""
        url = _official_url(base_url, link.get("href")) if link else None
        if not title or not url or not _GOKAMS_REPORT_TITLE.search(title) or url in seen:
            continue
        seen.add(url)
        cells = row.find_all("td")
        raw_date = clean_text(cells[3].get_text(" ")) if len(cells) > 3 else ""
        date_match = _GOKAMS_MONTH.search(raw_date)
        published = f"{date_match.group(1)}-{int(date_match.group(2)):02d}" if date_match else None
        item_id = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("Idx", [url])[0]
        out.append({"key": item_id, "title": title, "official_url": url, "published_date": published,
                    "access_status": "link_only(public GOKAMS catalogue entry; detail and attachments not fetched)"})
    return out


def parse_kiaf_reports(html, base_url):
    out, seen = [], set()
    page = soup(html)
    for section in page.select(".row.section"):
        text = clean_text(section.get_text(" "))
        match = re.search(r"Kiaf\s+REPORT\s+(20\d{2})", text, re.I)
        if not match:
            continue
        year = match.group(1)
        for link in section.find_all("a", href=True):
            label = clean_text(link.get_text(" "))
            url = _official_url(base_url, link.get("href"), extra_hosts=(_KIAF_HOST,))
            if not url or not urllib.parse.urlsplit(url).path.lower().endswith(".pdf") or url in seen:
                continue
            seen.add(url)
            language = "Korean" if "kor" in url.casefold() or "kor" in label.casefold() else "English"
            out.append({"key": url, "title": f"Kiaf REPORT {year} ({language})", "official_url": url,
                        "access_status": "link_only(public PDF link observed; file not fetched)",
                        "notes": "Official page labels a Kiaf report and offers a direct language-specific file link."})
    return out


def _collect_nea(ctx):
    response = ctx.fetch(ctx.meta["entry_url"])
    records = parse_nea_publications(response.text, response.url)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator="article.teaser publication listing",
                              publisher="National Endowment for the Arts", geo_scope="United States",
                              rights_note="Catalogue metadata only; report text and PDF not fetched; reuse terms for individual works not established.",
                              sourcebook_id="미주-06-002")
    ctx.note(f"NEA public publications list: {len(records)} first-page metadata entries; no detail pages, bodies, or PDFs fetched.")


def _collect_statcan(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], accept="application/json")
    try:
        payload = response.json()
    except ValueError as exc:
        raise FetchError(f"Statistics Canada WDS returned invalid JSON at {response.url}") from exc
    records = parse_statcan_cubes(payload)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator="WDS getAllCubesListLite catalogue record",
                              publisher="Statistics Canada", geo_scope=None,
                              rights_note="Statistics Canada Open Licence applies to most data products; check record-level third-party notices. Catalogue metadata only; cube values not fetched.",
                              sourcebook_id="미주-06-003")
    ctx.note(f"WDS catalogue contained {len(payload) if isinstance(payload, list) else 0} entries; stored {len(records)} titles matching explicit art/culture/museum/gallery/heritage terms only.")


def _collect_eurostat(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], store=False)
    records = parse_eurostat_culture_domain(response.text, response.url)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator="Culture data-domain dataset/publication anchor",
                              publisher="Eurostat", geo_scope="European Union",
                              rights_note="Eurostat reuse notice permits statistical data/metadata/publications with source acknowledgement, subject to third-party notices. Catalogue metadata only; no values/files fetched.",
                              sourcebook_id="유럽-06-006")
    ctx.note(f"Eurostat Culture data-domain page exposed {len(records)} official dataset/publication links; one listing page only, data values and files not fetched.")


def _collect_gokams(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], store=False)
    records = parse_gokams_listing(response.text, response.url)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator="table.boardList report/research row",
                              publisher="예술경영지원센터 (KAMS / GOKAMS)", geo_scope="Korea",
                              rights_note="The linked GOKAMS policy/notice path is disallowed by robots and was not fetched; no reuse terms are inferred. Public catalogue metadata only; details and attachments not fetched.",
                              sourcebook_id="한국-06-001")
    ctx.note(f"GOKAMS first publication listing page exposed {len(records)} title-filtered report/research rows; no detail or file URLs followed.")


def _collect_canada_heritage(ctx):
    index = ctx.fetch(ctx.meta["entry_url"], store=False)
    reports = parse_canada_heritage_index(index.text, index.url)
    ctx.count("fetched", len(reports))
    if not reports:
        ctx.note(f"No report-year links parsed from {index.url}")
        return
    if ctx.mode == "incremental":
        reports = reports[:1]
    else:
        reports = [report for report in reports if report["year"] >= 2017]
    for listed in reports:
        try:
            response = ctx.fetch(listed["url"], store=False)
        except FetchError as exc:
            ctx.note(f"Canadian Heritage report page {listed['url']}: {exc}")
            ctx.count("detail_errors")
            continue
        detail = parse_canada_heritage_report(response.text, response.url)
        if detail is None:
            ctx.note(f"No report title metadata parsed from {response.url}")
            ctx.count("detail_errors")
            continue
        ev = ctx.evidence(response, locator="h1#wb-cont, dcterms.title/issued, a.gc-dwnld-lnk",
                          excerpt=detail["title"])
        try:
            download = _download_public_pdf(ctx, detail["pdf_url"]) if detail["pdf_url"] else {}
        except Blocked as exc:
            state = {"robots_disallow": "blocked_permission", "login_redirect": "blocked_credentials"}.get(exc.kind, "blocked_access")
            _record(ctx, key=listed["url"], title=detail["title"], publisher="Department of Canadian Heritage",
                    published_date=detail["published_date"], geo_scope="Canada", official_url=detail["pdf_url"] or response.url,
                    access_status=f"{state}({exc.kind})", rights_note="Canada.ca permits non-commercial reproduction with attribution unless otherwise specified; third-party content may have separate rights. No report content copied.",
                    notes=f"Sourcebook 미주-06-004; index evidence URL {index.url}; detail evidence {ev}; Fetcher stopped the direct PDF request; no retry or bypass.")
            raise
        access_status = download.get("access_status") or (
            "link_only(public PDF link observed; file and report body not fetched)" if detail["pdf_url"] else
            "link_only(public report metadata page)")
        _record(ctx, key=listed["url"], title=detail["title"], publisher="Department of Canadian Heritage",
                published_date=detail["published_date"], geo_scope="Canada",
                official_url=detail["pdf_url"] or response.url,
                local_path=download.get("local_path"), sha256=download.get("sha256"),
                access_status=access_status,
                rights_note="Canada.ca permits non-commercial reproduction with attribution unless otherwise specified; third-party content may have separate rights. No report content copied.",
                notes=f"Sourcebook 미주-06-004; index evidence URL {index.url}; detail evidence {ev}; {download.get('notes', '')}; observation period, methods and sample size are not inferred from edition year.")
    ctx.note(f"Canadian Heritage report archive shows {len(reports)} selected edition page(s); initial floor 2017; incremental checks newest only.")


def _collect_ibermuseos(ctx):
    for url in _IBERMUSEOS_PAGES:
        try:
            response = ctx.fetch(url)
        except FetchError as exc:
            ctx.note(f"Ibermuseos publication {url}: {exc}")
            ctx.count("detail_errors")
            continue
        detail = parse_ibermuseos_publication(response.text, response.url)
        if detail is None:
            ctx.note(f"Ibermuseos page has no publication h1: {response.url}")
            ctx.count("detail_errors")
            continue
        record = {"key": url, "title": detail["title"], "published_date": detail["published_date"],
                  "pages": detail["pages"], "official_url": detail["pdf_url"] or response.url,
                  "access_status": "link_only(public PDF link observed; file and publication body not fetched)"}
        ctx.count("fetched")
        _store_listing_record(ctx, response, record, locator="h1, publication side metadata and official PDF anchor",
                              publisher="Ibermuseos", geo_scope="Ibero-America",
                              rights_note="Publication metadata and official file URL only; site terms and publication-specific reuse terms were not established.",
                              sourcebook_id="미주-06-005")
    ctx.note("Ibermuseos: two saved-evidence publication pages only; no attempt to infer a complete archive.")


def _collect_imls(ctx):
    for url in _IMLS_LISTS:
        try:
            response = ctx.fetch(url)
        except FetchError as exc:
            ctx.note(f"IMLS index {url}: {exc}")
            ctx.count("detail_errors")
            continue
        records = parse_imls_cards(response.text, response.url)
        ctx.count("fetched", len(records))
        for record in records:
            _store_listing_record(ctx, response, record, locator=".grid-row.image_left catalogue card",
                                  publisher="Institute of Museum and Library Services", geo_scope="United States",
                                  rights_note="IMLS says eligible agency-authored works are public domain; third-party works may be protected. Index metadata only; no dataset or report files fetched.",
                                  sourcebook_id="미주-06-006")
    ctx.note("IMLS data and survey indexes only; history and report methodology are not represented as complete.")


def _collect_ncar(ctx):
    response = ctx.fetch(ctx.meta["entry_url"])
    records = parse_ncar_awareness_index(response.text, response.url)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator='main a[href^="/reports/"]',
                              publisher="National Center for Art Research", geo_scope="Japan",
                              rights_note="NCAR site policy reserves content to NCAR/right holders and requires permission beyond private use; only catalogue metadata retained.",
                              sourcebook_id="日本-06-002")
    ctx.note(f"NCAR awareness-survey index lists {len(records)} linked result pages; no detail pages or report files fetched.")


def _collect_bunka(ctx):
    for url in _BUNKA_LISTS:
        try:
            response = ctx.fetch(url)
        except FetchError as exc:
            ctx.note(f"Bunka index {url}: {exc}")
            ctx.count("detail_errors")
            continue
        records = parse_bunka_listing(response.text, response.url)
        ctx.count("fetched", len(records))
        for record in records:
            _store_listing_record(ctx, response, record, locator="official statistics/white-paper listing anchor",
                                  publisher="Agency for Cultural Affairs, Government of Japan", geo_scope="Japan",
                                  rights_note="Official page-level catalogue metadata and public links only; no document body/PDF fetched; follow individual reuse notices.",
                                  sourcebook_id="日本-06-006")
    ctx.note("Bunka covers the two observed statistics/research and white-paper listings only; no document downloads or full-archive claim.")


def _collect_arko(ctx):
    for url in _ARKO_LISTS:
        try:
            response = ctx.fetch(url)
        except FetchError as exc:
            ctx.note(f"ARKO index {url}: {exc}")
            ctx.count("detail_errors")
            continue
        records = parse_arko_listing(response.text, response.url)
        ctx.count("fetched", len(records))
        for record in records:
            _store_listing_record(ctx, response, record, locator="/board/view/ entry in official list",
                                  publisher="Arts Council Korea", geo_scope="Korea",
                                  rights_note="ARKO copyright policy reserves site content; only each work marked KOGL Type 1 is reusable under that licence. Catalogue metadata only; no report files fetched.",
                                  sourcebook_id="한국-06-005")
    ctx.note("ARKO covers bounded research/current-status/annual-report indexes; no grants are interpreted as policy-report evidence.")


def _collect_kiaf(ctx):
    response = ctx.fetch(ctx.meta["entry_url"])
    records = parse_kiaf_reports(response.text, response.url)
    ctx.count("fetched", len(records))
    for record in records:
        _store_listing_record(ctx, response, record, locator=".row.section report label and direct language file link",
                              publisher="Galleries Association of Korea / Kiaf SEOUL", geo_scope="Korea",
                              rights_note="Sourcebook evidence states report content is reserved and reuse requires permission; public file links are recorded but not fetched.",
                              sourcebook_id="한국-06-006")
    ctx.note(f"Kiaf public About-report page exposed {len(records)} language-specific 2021 file link(s); files not fetched.")


def collect(ctx):
    handlers = {
        "wave2_reports_nea": _collect_nea,
        "wave2_reports_statcan": _collect_statcan,
        "wave2_reports_eurostat": _collect_eurostat,
        "wave2_reports_gokams": _collect_gokams,
        "wave2_reports_canada_heritage": _collect_canada_heritage,
        "wave2_reports_ibermuseos": _collect_ibermuseos,
        "wave2_reports_imls": _collect_imls,
        "wave2_reports_ncar": _collect_ncar,
        "wave2_reports_bunka": _collect_bunka,
        "wave2_reports_arko": _collect_arko,
        "wave2_reports_kiaf": _collect_kiaf,
    }
    handler = handlers.get(ctx.source_id)
    if handler is None:
        raise ValueError(f"wave2_reports cannot collect {ctx.source_id}")
    handler(ctx)
    ctx.con.commit()
