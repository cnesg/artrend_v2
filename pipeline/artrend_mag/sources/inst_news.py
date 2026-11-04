"""Official news, press and notice listings of museums, galleries, foundations, biennials and residencies.

The institutions' own announcements (new acquisitions, appointments, prizes, programmes, openings) are the
primary record ARTREND reads; press coverage only corroborates them. One source per institution listing,
discovered from the institution's own site (`work/dev/InstNews/discover.py`) and kept in `inst_news_sites.json`.

Access: the institution's public listing page or its RSS/Atom feed, robots.txt enforced by Fetcher, one
listing page per run (incremental) or up to 5 (initial). Stored: title, URL, date, and for feeds the
publisher's own summary cut to 300 characters. No article bodies are fetched.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup

from .. import db
from ._common import clean_text, parse_feed

SITES = Path(__file__).with_name("inst_news_sites.json")
PARSER_VERSION = "inst-news-1"

MONTHS = {m: i for i, names in enumerate([
    (), ("jan", "january", "janvier", "enero", "gennaio", "januar", "janeiro"), ("feb", "february", "février", "fevrier", "febrero", "febbraio", "februar", "fevereiro"),
    ("mar", "march", "mars", "marzo", "märz", "marz", "março", "marco"), ("apr", "april", "avril", "abril", "aprile"),
    ("may", "mai", "mayo", "maggio", "maio"), ("jun", "june", "juin", "junio", "giugno", "juni", "junho"),
    ("jul", "july", "juillet", "julio", "luglio", "juli", "julho"), ("aug", "august", "août", "aout", "agosto"),
    ("sep", "sept", "september", "septembre", "septiembre", "setiembre", "settembre", "setembro"),
    ("oct", "october", "octobre", "octubre", "ottobre", "oktober", "outubro"), ("nov", "november", "novembre", "noviembre", "novembro"),
    ("dec", "december", "décembre", "decembre", "diciembre", "dicembre", "dezember", "dezembro"),
]) for m in names}
_MON = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DATE_PATTERNS = [
    (re.compile(r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"(20\d{2})\s*[年년]\s*(\d{1,2})\s*[月월]\s*(\d{1,2})\s*[日일]"), ("y", "m", "d")),
    (re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})", re.I), ("M", "d", "y")),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|er)?\.?\s+(?:de\s+)?({_MON})\.?,?\s+(?:de\s+)?(20\d{{2}})", re.I), ("d", "M", "y")),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b"), ("d", "m", "y")),
]
NEWS_WORD = re.compile(r"news|press|notice|announcement|journal|stories|updates|actualit|presse|notizie|noticias|novit|nachrichten|"
                       r"소식|공지|보도|알림|뉴스|プレス|ニュース|お知らせ|新着|トピックス|topics", re.I)
NAV_TEXT = re.compile(r"^(?:news|press|more|read more|view all|see all|next|previous|prev|older|newer|back|home|menu|search|"
                      r"더보기|목록|이전|다음|もっと見る|一覧|詳しく|一覧へ|more info|learn more|subscribe|newsletter|\d+)$", re.I)


def parse_date(text: str):
    t = clean_text(text or "")
    for rx, order in DATE_PATTERNS:
        m = rx.search(t)
        if not m:
            continue
        parts = dict(zip(order, m.groups()))
        try:
            mon = int(parts["m"]) if "m" in parts else MONTHS.get(parts["M"].lower().rstrip("."))
            day = dt.date(int(parts["y"]), mon, int(parts["d"]))
        except (TypeError, ValueError, KeyError):
            continue
        if dt.date(2000, 1, 1) <= day <= dt.date.today() + dt.timedelta(days=400):
            return day, m.group(0)
    return None, None


def _title_of(a, date_text: str | None) -> str:
    for sel in ("h1", "h2", "h3", "h4", "h5", "[class*=title]", "[class*=tit]", "strong", "p"):
        el = a.select_one(sel)
        if el:
            t = clean_text(el.get_text(" "))
            if len(t) >= 6:
                return t[:220]
    t = clean_text(a.get_text(" ") or a.get("title") or "")
    if date_text:
        t = clean_text(t.replace(date_text, " "))
    return t[:220]


def extract_listing(html: str, page_url: str) -> list:
    """Cards on an institution's news/press listing: same-site links with a title and a date nearby."""
    page = BeautifulSoup(html, "lxml")
    for junk in page.select("header, nav, footer, script, style, noscript, form, [role=navigation]"):
        junk.decompose()
    base = urllib.parse.urlsplit(page_url)
    host = base.netloc.lower().removeprefix("www.")
    items, seen = [], set()
    for a in page.select("a[href]"):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urllib.parse.urljoin(page_url, href).split("#")[0]
        parts = urllib.parse.urlsplit(url)
        if parts.netloc.lower().removeprefix("www.") != host or url.rstrip("/") == page_url.rstrip("/"):
            continue
        if parts.path.rstrip("/") in ("", base.path.rstrip("/")) and not parts.query:
            continue
        if re.search(r"\.(?:pdf|jpe?g|png|zip|docx?)$", parts.path, re.I) or re.search(r"[?&](?:page|paged|p|pg)=\d+$", url):
            continue
        raw = clean_text(a.get_text(" "))
        if NAV_TEXT.match(raw) or len(raw) < 6:
            continue
        date, date_text = None, None
        t = a.find("time")
        if t and t.get("datetime"):
            date, date_text = parse_date(t["datetime"])[0], clean_text(t.get_text(" "))
        if not date:
            date, date_text = parse_date(raw)
        node = a
        for _ in range(4):
            if date or node.parent is None:
                break
            node = node.parent
            txt = clean_text(node.get_text(" "))
            if len(txt) > 600:
                break
            tm = node.find("time")
            if tm and tm.get("datetime"):
                date = parse_date(tm["datetime"])[0]
            if not date:
                date, date_text = parse_date(txt)
        title = _title_of(a, date_text)
        if len(title) < 6 or NAV_TEXT.match(title) or url in seen:
            continue
        seen.add(url)
        items.append(dict(title=title, url=url, date=date.isoformat() if date else None))
    return items


def load_sites() -> list:
    if not SITES.exists():
        return []
    return json.loads(SITES.read_text(encoding="utf-8"))


_SITES = {s["source_id"]: s for s in load_sites()}
SOURCES = [dict(
    source_id=s["source_id"], blueprint_data_id=None, blueprint_org_id=None,
    name=f"{s['name']} — official news", owner_group=s["name"], source_kind=s["kind"], region_scope=s["region"],
    country_codes=s.get("countries"), access_method="rss" if s["method"] == "feed" else "html", base_url=s["base"],
    entry_url=s["url"], terms_url=s.get("terms"), text_storage_policy="raw_internal", priority="P1",
    st_official_doc="n/a(official public listing)",
    st_collection_terms="institution's own public news/press listing; listing metadata only (title, date, URL), robots enforced",
    st_image_terms="images not stored; listing images are not collected",
    max_requests=30, notes=f"discovered from {s.get('parent')} ({s.get('found_via')}); work/dev/InstNews",
) for s in _SITES.values()]


def collect(ctx):
    site = _SITES[ctx.source_id]
    url, pages = site["url"], 1 if ctx.mode == "incremental" else 5
    for n in range(pages):
        resp = ctx.fetch(url)
        if site["method"] == "feed":
            items = [dict(title=i["title"], url=i["link"], date=(i.get("published") or i.get("updated") or "")[:10] or None,
                          excerpt=(i.get("summary") or "")[:300] or None) for i in parse_feed(resp.content) if i.get("title") and i.get("link")]
        else:
            items = [dict(it, excerpt=None) for it in extract_listing(resp.text, resp.url)]
            items = [it for it in items if it["date"]] if sum(1 for it in items if it["date"]) >= 3 else items
        ctx.count("fetched", len(items))
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        for it in items:
            if it["date"] and it["date"] > tomorrow:
                it["date"] = None  # a future date on a listing card is a show's closing date, not when it was posted
            ev = ctx.evidence(resp, locator=f"official news listing: {it['title'][:120]}", excerpt=it["date"])
            db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=it["url"], title=it["title"],
                              published_at=it["date"], publisher=site["name"], owner_group=site["name"],
                              article_type="announcement", type_basis=f"official {site['method']} listing", lang=site.get("lang"),
                              excerpt=it.get("excerpt"))
            ctx.count("parsed")
        ctx.con.commit()
        if site["method"] == "feed" or ctx.mode == "incremental":
            break
        nxt = BeautifulSoup(resp.text, "lxml").select_one('a[rel="next"], link[rel="next"]')
        if not nxt or not nxt.get("href"):
            break
        url = urllib.parse.urljoin(resp.url, nxt["href"])
    ctx.note(f"official {site['method']} listing {site['url']}; metadata only")
