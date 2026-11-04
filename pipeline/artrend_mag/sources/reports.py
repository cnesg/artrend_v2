"""Public market reports (Blueprint D40-D45, L14). Free official PDFs only; nothing is purchased.

PDFs are archived under raw/<source_id>/<run>/ for internal verification (copyrighted: quote with
attribution, do not republish tables/figures). Headline sentences are stored as report_metrics with the
page number they were found on; numeric values are parsed only from that exact sentence.
"""
from __future__ import annotations

import re
import urllib.parse

import fitz  # PyMuPDF

from .. import db
from ..config import WORK_ROOT
from ..http import Blocked, FetchError
from ._common import clean_text, soup

PARSER_VERSION = "reports-3"

SOURCES = [
    dict(source_id="rpt_artbasel_ubs", blueprint_data_id="D41,D42", name="Art Basel & UBS reports (Arts Economics)",
         owner_group="Art Basel (MCH Group) / UBS", source_kind="report", region_scope="GLOBAL", access_method="pdf",
         base_url="https://theartmarket.artbasel.com", entry_url="https://theartmarket.artbasel.com/previous-reports",
         terms_url="https://theartmarket.artbasel.com/", text_storage_policy="raw_internal", priority="P0",
         st_collection_terms="public download; report states all rights reserved -> quote with attribution only",
         st_image_terms="charts not reusable", max_requests=20),
    dict(source_id="rpt_bunka_japan_art_market", blueprint_data_id="D43", name="Agency for Cultural Affairs — The Japanese Art Market",
         owner_group="Agency for Cultural Affairs, Government of Japan", source_kind="report", region_scope="JP",
         country_codes="JP", access_method="pdf", base_url="https://www.bunka.go.jp",
         entry_url="https://www.bunka.go.jp/seisaku/bunka_gyosei/artecosystem/94149601.html",
         terms_url="https://www.bunka.go.jp/chosakuken/index.html", text_storage_policy="raw_internal", priority="P0",
         st_collection_terms="government publication; reuse per site terms (attribution)", st_image_terms="not checked",
         max_requests=12),
    dict(source_id="rpt_kartmarket", blueprint_data_id="D40", name="K-ARTMARKET 미술시장조사 (예술경영지원센터)",
         owner_group="예술경영지원센터 (KAMS)", source_kind="report", region_scope="KR", country_codes="KR",
         access_method="pdf", base_url="https://k-artmarket.kr",
         entry_url="https://k-artmarket.kr/member/board/Analysis_BoardList.do",
         terms_url="https://www.gokams.or.kr/01_news/notice_view.aspx?Idx=3969", text_storage_policy="raw_internal",
         priority="P0", st_collection_terms=("public list and server-rendered detail GET pages; reviewed 2024–2026 details "
                                             "expose no public PDF; the 2026 entry offers a print-copy request form; "
                                             "download only official PDF attachments exposed by detail pages; "
                                             "public attribution and copyright terms apply"),
         max_requests=50),
    dict(source_id="rpt_deloitte_art_finance", blueprint_data_id="D44",
         name="Deloitte Private and ArtTactic Art & Finance reports",
         owner_group="Deloitte Luxembourg / ArtTactic", source_kind="report", region_scope="GLOBAL",
         access_method="pdf", base_url="https://www.deloitte.com",
         entry_url="https://www.deloitte.com/lu/en/services/consulting-financial/research/art-finance-report.html",
         terms_url="https://www.deloitte.com/lu/en/legal/terms-use.html", text_storage_policy="raw_internal",
         priority="P1", st_collection_terms=("Deloitte robots.txt allows the observed public report paths; public terms permit "
                                              "unmodified copying for informational, noncommercial use where report content "
                                              "does not prohibit it, with attribution; direct public PDFs only; 2025 edition "
                                              "requires registration form and email delivery, not submitted"),
         max_requests=12),
    dict(source_id="rpt_tefaf_market_reports", blueprint_data_id="D45",
         name="TEFAF Art Market & Cultural Impact Reports", owner_group="The European Fine Art Foundation (TEFAF)",
         source_kind="report", region_scope="GLOBAL", access_method="pdf", base_url="https://www.tefaf.com",
         entry_url="https://www.tefaf.com/foundation/art-market-report",
         terms_url="https://www.tefaf.com/terms-and-conditions", text_storage_policy="metadata_only",
         priority="P1", st_collection_terms=("blocked_permission: TEFAF website terms prohibit systematic or automated data "
                                              "collection without express written consent; official static.tefaf.com robots.txt "
                                              "returned HTTP 403; official archive URLs are logged in the blocked run detail, "
                                              "not fetched or inserted as report records"),
         max_requests=0),
]

ARTBASEL_PDFS = [
    ("AMR2026", "The Art Basel and UBS Art Market Report 2026", "2025", "/download/The-Art-Basel-and-UBS-Art-Market-Report-2026-by-Arts-Economics.pdf"),
    ("SGC2026", "The Art Basel and UBS Survey of Global Collecting in 2026", "2026 survey", "/download/The-Art-Basel-and-UBS-Survey-of-Global-Collecting-in-2026-by-Arts-Economics.pdf"),
    ("AMR2025", "The Art Basel and UBS Art Market Report 2025", "2024", "/download/The-Art-Basel-and-UBS-Art-Market-Report-2025.pdf"),
]
DELOITTE_PUBLIC_PDFS = [
    ("DAF2023", "Deloitte Private and ArtTactic Art & Finance Report 2023",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/art-finance-report-2023.pdf",
     "July 2023 (expert survey); market data includes 2022"),
    ("DAF2021", "Deloitte Art & Finance Report 2021",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-art-finance-report-2021.pdf", None),
    ("DAF2019", "Art & Finance Report 2019",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-art-and-finance-report-2019.pdf",
     "April–June 2019 (research and survey)"),
    ("DAF2017", "Art & Finance Report 2017",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-art-finance-report.pdf",
     "2017 (survey; market outlook through 2018)"),
    ("DAF2016", "Art & Finance Report 2016",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-en-artandfinancereport-21042016.pdf", None),
    ("DAF2014", "Art & Finance Report 2014",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-en-artandfinancereport-08092014.pdf", None),
    ("DAF2013", "Art & Finance Report 2013",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-en-artandfinancereport-15032013.pdf", None),
    ("DAF2011", "Art & Finance Report 2011",
     "/content/dam/assets-zone2/lu/en/docs/services/financial-advisory/2023/lu-en-artandfinancereport-110112.pdf", None),
]
TEFAF_REPORTS = [
    ("TEFAF2026_ECONOMIC_IMPACT", "The Economic Impact of TEFAF on Maastricht",
     "https://static.tefaf.com/assets/Art-Market-Reports/2026_The-Economic-Impact-of-TEFAF-on-Maastricht_Report.pdf?v=1773646837"),
    ("TEFAF2020_ART_PATRONAGE", "Art Patronage in the 21st Century",
     "https://static.tefaf.com/assets/Art-Market-Reports/TEFAF_Art_Market_Report_2020.pdf?v=1772641848"),
    ("TEFAF2019_CHINESE_MARKET", "The Chinese Art Market Report 2019",
     "https://static.tefaf.com/assets/Art-Market-Reports/TEFAF-Chinese-Art-Market-Report-2019.pdf?v=1774340803"),
    ("TEFAF2018_ART_DEALER_FINANCE", "Art Dealer Finance 2018",
     "https://static.tefaf.com/assets/Art-Market-Reports/Art-Dealer-Finance-2018-Report.pdf?v=1772641832"),
]
HEADLINE = re.compile(r"[^.]*?(?:\$|US\$|USD|¥|円|억\s*원|조\s*원)\s?[\d,.]+\s?(?:billion|million|bn|億円|兆円|억|조)?[^.]*\.", re.I)
DELOITTE_RIGHTS = ("Deloitte Luxembourg website terms allow unmodified informational, noncommercial copying with attribution "
                   "unless the content says otherwise; retain each report copyright notice; internal archive only, no table/figure republication")


def collect(ctx):
    if ctx.source_id == "rpt_artbasel_ubs":
        for rid, title, period, path in ARTBASEL_PDFS:
            _pdf(ctx, rid, title, "Arts Economics (Clare McAndrew) for Art Basel & UBS", period, "Global",
                 urllib.parse.urljoin("https://theartmarket.artbasel.com", path), sponsor="UBS")
    elif ctx.source_id == "rpt_bunka_japan_art_market":
        r = ctx.fetch(ctx.meta["entry_url"])
        s = soup(r.text)
        for a in s.find_all("a", href=True):
            t = clean_text(a.get_text(" "))
            m = re.search(r"The Japanese Art Market (20\d\d)", t)
            if m and a["href"].endswith(".pdf"):
                lang = "en" if "English" in t or "英語" in t else "ja"
                year = m.group(1)
                _pdf(ctx, f"JAM{year}_{lang}", f"The Japanese Art Market {year} ({lang})",
                     "Agency for Cultural Affairs (commissioned research)", f"{int(year) - 1} (per report title convention; verify in PDF)",
                     "Japan", urllib.parse.urljoin(r.url, a["href"]), landing=r.url)
    elif ctx.source_id == "rpt_deloitte_art_finance":
        r = ctx.fetch(ctx.meta["entry_url"])
        page_ev = ctx.evidence(r, locator="official report page")
        public_pdfs = _deloitte_public_pdfs(r.text, r.url)
        for rid, title, path, period in DELOITTE_PUBLIC_PDFS:
            url = public_pdfs.get(path)
            if not url:
                ctx.note(f"{rid}: expected official public PDF link is absent from {r.url}")
                continue
            _pdf(ctx, rid, title, "Deloitte Luxembourg / ArtTactic", period, "Global", url,
                 landing=r.url, rights_note=DELOITTE_RIGHTS)

        form_url = _deloitte_registration_url(r.text, r.url)
        if form_url:
            _upsert_report(ctx, "DAF2025", title="9th Deloitte Private and ArtTactic Art & Finance Report 2025",
                           publisher="Deloitte Private / ArtTactic", observation_period=None, geo_scope="Global",
                           official_url=form_url, local_path=None, sha=None, pages=None,
                           access_status="not_extractable(registration form required; report delivered by email)",
                           rights_note="Report-specific reuse terms not established; no registered download was attempted.",
                           notes=f"Official landing page {r.url} links the 2025 edition to a Deloitte form; "
                                 "the form states to fill it out to download and that an email link will follow; "
                                 f"no personal data was submitted; landing evidence {page_ev}")
            ctx.count("parsed")
            ctx.note("DAF2025: registration form and email delivery gate observed; no form submission attempted")
    elif ctx.source_id == "rpt_tefaf_market_reports":
        links = "; ".join(f"{rid} {title}: {url}" for rid, title, url in TEFAF_REPORTS)
        raise Blocked("robots_disallow", "https://static.tefaf.com/robots.txt", 403,
                      "TEFAF Website Terms & Conditions Article 2 prohibits systematic or automated data collection "
                      "without express written consent; static asset robots.txt returned HTTP 403; no archive or PDF "
                      f"request made. Official links manually observed at {ctx.meta['entry_url']}: {links}")
    elif ctx.source_id == "rpt_kartmarket":
        r = ctx.fetch(ctx.meta["entry_url"])
        list_ev = ctx.evidence(r, locator="public board list")
        reports = _kartmarket_entries(r.text)
        if not reports:
            ctx.note(f"No K-ARTMARKET report rows parsed from public list {r.url}")
            return
        for bid, listed_title in reports:
            rid = f"KAM_{bid}"
            detail_url = _kartmarket_detail_url(r.url, bid)
            try:
                detail = ctx.fetch(detail_url)
            except FetchError as e:
                _upsert_report(ctx, rid, title=listed_title, publisher="예술경영지원센터 (KAMS)",
                               observation_period=_observation_period(listed_title), geo_scope="Korea",
                               official_url=detail_url, local_path=None, sha=None, pages=None,
                               access_status=f"detail_unavailable({e})",
                               notes=f"board id {bid}; listed on {r.url}; list evidence {list_ev}; public GET detail failed")
                ctx.count("parsed")
                continue

            detail_ev = ctx.evidence(detail, locator="public GET detail page")
            detail_data = _kartmarket_detail(detail.text, bid, listed_title)
            if detail_data is None:
                _upsert_report(ctx, rid, title=listed_title, publisher="예술경영지원센터 (KAMS)",
                               observation_period=_observation_period(listed_title), geo_scope="Korea",
                               official_url=detail.final_url, local_path=None, sha=None, pages=None,
                               access_status="link_only(public GET returned no matching detail record)",
                               notes=f"board id {bid}; listed on {r.url}; detail {detail.final_url}; "
                                     f"list evidence {list_ev}; detail evidence {detail_ev}")
                ctx.count("parsed")
                continue

            title = detail_data["title"] or listed_title
            period = _observation_period(title) or _observation_period(detail_data["text"])
            rights = _kartmarket_rights(detail_data["text"])
            links = _kartmarket_attachment_links(detail.text, detail.final_url)
            downloaded = False
            for attachment_url in links:
                if _pdf(ctx, rid, title, "예술경영지원센터 (KAMS)", period, "Korea", attachment_url,
                        landing=detail.final_url, rights_note=rights):
                    downloaded = True
                    break
            if not downloaded and not links:
                print_request = "보고서 인쇄본이 필요하신 분" in detail_data["text"]
                access_note = "the page offers a print-copy request form, not a public PDF" if print_request else "no public PDF attachment is exposed"
                _upsert_report(ctx, rid, title=title, publisher="예술경영지원센터 (KAMS)",
                               observation_period=period, geo_scope="Korea", official_url=detail.final_url,
                               local_path=None, sha=None, pages=None,
                               access_status="link_only(no official PDF attachment link on public detail page)",
                               rights_note=rights,
                               notes=f"board id {bid}; public GET detail has no downloadable report attachment; "
                                     f"list evidence {list_ev}; detail evidence {detail_ev}; {access_note}")
                ctx.count("parsed")
                ctx.note(f"{rid}: public GET detail {detail.final_url}; no official PDF attachment; "
                         f"{access_note}")
            elif not downloaded:
                ctx.count("parsed")
                ctx.note(f"{rid}: official attachment link(s) were present but none returned a valid PDF; "
                         f"detail {detail.final_url}")


def _pdf(ctx, rid, title, publisher, period, geo, url, sponsor=None, landing=None, rights_note=None):
    try:
        r = ctx.fetch(url, conditional=False)
    except Blocked as e:
        if e.kind == "robots_disallow":
            status = "blocked_permission"
        elif e.kind == "login_redirect":
            status = "blocked_credentials"
        else:
            status = "blocked_access"
        _upsert_report(ctx, rid, title=title, publisher=publisher, observation_period=period, geo_scope=geo,
                       official_url=url, local_path=None, sha=None, pages=None,
                       access_status=f"{status}({e.kind} status={e.status})", rights_note=rights_note,
                       notes=f"landing: {landing or url}; PDF request stopped by Fetcher policy")
        ctx.note(f"{rid}: PDF request blocked by Fetcher policy: {e.kind} status={e.status}")
        return False
    except FetchError as e:
        ctx.note(f"{rid}: {e}")
        _upsert_report(ctx, rid, title=title, publisher=publisher, observation_period=period, geo_scope=geo,
                       official_url=url, local_path=None, sha=None, pages=None, access_status=f"not_downloaded({e})",
                       rights_note=rights_note)
        return False
    ctx.count("fetched")
    if "pdf" not in r.content_type.lower() and not r.content[:5] == b"%PDF-":
        _upsert_report(ctx, rid, title=title, publisher=publisher, observation_period=period, geo_scope=geo,
                       official_url=url, local_path=None, sha=None, pages=None,
                       access_status=f"not_pdf(content-type {r.content_type}; response has no PDF signature)",
                       rights_note=rights_note)
        return False
    doc = fitz.open(stream=r.content, filetype="pdf")
    meta_title = clean_text((doc.metadata or {}).get("title")) or title
    _upsert_report(ctx, rid, title=title, publisher=publisher, observation_period=period, geo_scope=geo,
                   official_url=url, local_path=r.raw_path, sha=r.sha256, pages=doc.page_count,
                   access_status="downloaded", sponsor=sponsor,
                   rights_note=rights_note,
                   notes=f"landing: {landing or url}; embedded PDF metadata title: {meta_title!r}")
    ev = ctx.evidence(r, locator="pdf")
    n = 0
    for pno in range(min(doc.page_count, 30)):
        text = clean_text(doc[pno].get_text())
        for m in HEADLINE.finditer(text):
            sent = clean_text(m.group(0))
            if 40 <= len(sent) <= 320 and n < 25:
                mid = db.sid("met", rid, pno + 1, sent)
                ctx.con.execute(
                    "INSERT INTO report_metrics(metric_id,report_id,metric_name,value,value_text,unit,geography,period,page,table_ref,excerpt,comparability_note)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(metric_id) DO NOTHING",
                    (mid, rid, "headline_sentence(unreviewed)", None, None, None, geo, period, str(pno + 1), None, sent[:300],
                     "auto-extracted sentence; verify definition (dealer+auction vs auction-only, premium vs hammer, survey sample) before citing"))
                n += 1
    ctx.count("parsed")
    ctx.note(f"{rid}: pages={doc.page_count} headline_sentences={n} evidence={ev}")
    return True


def _upsert_report(ctx, rid, *, title, publisher, observation_period, geo_scope, official_url, local_path, sha, pages,
                   access_status, sponsor=None, notes=None, rights_note=None):
    old = ctx.con.execute("SELECT sha256, access_status FROM reports WHERE report_id=?", (rid,)).fetchone()
    if old is None:
        ctx.count("inserted")
    elif (old[0], old[1]) != (sha or old[0], access_status):
        ctx.count("updated")
    else:
        ctx.count("unchanged")
    ctx.con.execute(
        "INSERT INTO reports(report_id,title,publisher,sponsor,observation_period,geo_scope,official_url,local_path,sha256,pages,"
        "access_status,rights_note,next_check,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET "
        "title=excluded.title, observation_period=COALESCE(excluded.observation_period, reports.observation_period),"
        " official_url=excluded.official_url, rights_note=excluded.rights_note,"
        " local_path=COALESCE(excluded.local_path, reports.local_path), sha256=COALESCE(excluded.sha256, reports.sha256),"
        " pages=COALESCE(excluded.pages, reports.pages), access_status=excluded.access_status, notes=excluded.notes",
        (rid, title, publisher, sponsor, observation_period, geo_scope, official_url, local_path, sha, pages, access_status,
         rights_note or "copyrighted publication: cite with attribution, no table/figure republication",
         "check monthly; new edition annually", notes))
    ctx.con.commit()


def _deloitte_public_pdfs(html, base_url):
    """Return explicit Deloitte-hosted PDF anchors from its public report page."""
    out = {}
    for a in soup(html).find_all("a", href=True):
        url = urllib.parse.urljoin(base_url, a["href"].strip())
        parts = urllib.parse.urlsplit(url)
        if ((parts.hostname or "").lower() in {"deloitte.com", "www.deloitte.com"} and
                parts.path.lower().endswith(".pdf")):
            out.setdefault(parts.path, url)
    return out


def _deloitte_registration_url(html, base_url):
    """Return the official 2025 form link without opening or submitting the form."""
    for a in soup(html).find_all("a", href=True):
        url = urllib.parse.urljoin(base_url, a["href"].strip())
        parts = urllib.parse.urlsplit(url)
        if ((parts.hostname or "").lower() == "form.deloitte.lu" and
                parts.path.rstrip("/").endswith("/art-and-finance-2025-report.html")):
            return url
    return None


def _kartmarket_entries(html):
    """Report IDs and titles from the public K-ARTMARKET listing page."""
    out = []
    seen = set()
    for a in soup(html).select(".list-name a[href]"):
        m = re.search(r"fnView\(\s*['\"](BRD_ID\d+)['\"]\s*\)", a["href"])
        title = clean_text(a.get_text(" "))
        if m and title and m.group(1) not in seen:
            out.append((m.group(1), title))
            seen.add(m.group(1))
    return out


def _kartmarket_detail_url(list_url, board_id):
    if not re.fullmatch(r"BRD_ID\d+", board_id):
        raise ValueError(f"invalid K-ARTMARKET board id: {board_id}")
    return urllib.parse.urljoin(
        list_url, "/member/board/Analysis_BoardView.do?" + urllib.parse.urlencode({"boardId": board_id})
    )


def _observation_period(text):
    """Return only an explicitly stated YYYY년(도) 기준 period; never infer from a publication year."""
    m = re.search(r"(?<!\d)(20\d{2})\s*년(?:도)?\s*기준", text or "")
    return m.group(1) if m else None


def _kartmarket_detail(html, board_id, listed_title):
    page = soup(html)
    id_field = page.select_one("#boardId")
    if not id_field or id_field.get("value") != board_id:
        return None
    title_node = page.select_one(".view-title-box .view-img-tit .cont .tit")
    text = clean_text(page.get_text(" "))
    return {"title": clean_text(title_node.get_text(" ")) if title_node else listed_title, "text": text}


def _kartmarket_official_host(url):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme in {"http", "https"} and
            (host == "k-artmarket.kr" or host.endswith(".k-artmarket.kr") or
             host == "gokams.or.kr" or host.endswith(".gokams.or.kr")))


def _kartmarket_attachment_links(html, base_url):
    """Find explicit official file links only; thumbnail img src values are not downloads."""
    links = []
    seen = set()
    for a in soup(html).find_all("a", href=True):
        url = urllib.parse.urljoin(base_url, a["href"].strip())
        parts = urllib.parse.urlsplit(url)
        target = (parts.path + "?" + parts.query).lower()
        file_link = (".pdf" in target or any(marker in parts.path.lower() for marker in
                                              ("attachfile", "download", "filedown", "file-download")))
        if file_link and _kartmarket_official_host(url) and url not in seen:
            links.append(url)
            seen.add(url)
    return sorted(links, key=lambda url: 0 if ".pdf" in url.lower() else 1)


def _kartmarket_rights(text):
    terms = []
    if "공공누리" in text and "출처표시" in text:
        terms.append("공공누리 출처표시 조건으로 이용 가능")
    if "상업적인 목적으로 사용하거나 판매할 수 없습니다" in text:
        terms.append("문화체육관광부 및 예술경영지원센터 승인 없이 상업적 이용·판매 금지")
    if "무단 복제나 도용은 저작권법에 의해 금지" in text:
        terms.append("무단 복제·도용 금지")
    if not terms:
        return "K-ARTMARKET detail page did not expose report-specific reuse terms; verify before reuse"
    return "K-ARTMARKET detail: " + "; ".join(terms)
