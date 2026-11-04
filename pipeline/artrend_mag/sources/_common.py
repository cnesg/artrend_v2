"""Shared parsing helpers for source modules (dates, text, JSON-LD, RSS, title patterns)."""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import unicodedata
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from lxml import etree

MONTHS = {
    # en
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # fr
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # es / pt / it / nl / de (common forms)
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5, "junho": 6, "julho": 7,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "settembre": 9,
    "ottobre": 10, "dicembre": 12,
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "juni": 6, "juli": 7, "augustus": 8, "oktober": 10,
    "januar": 1, "februar": 2, "märz": 3, "dezember": 12,
    # pt abbreviations (bienal.org.br, pinacoteca: '6 set 2025 – 11 jan 2026')
    "fev": 2, "abr": 4, "ago": 8, "set": 9, "out": 10, "dez": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = htmllib.unescape(s)
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _mk(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def _tokens(text: str):
    """Yield (pos, y|None, m|None, d|None) date tokens in reading order."""
    t = clean_text(text).lower()
    # Ordinals may be split from the day by markup such as <sup>th</sup>: '19 th', '21 st ,'.
    t = re.sub(r"(\d) ?(st|nd|rd|th|er)\b\s*(,?)", r"\1\3 ", t)
    # same-month ranges: 'december 1–5, 2026' -> 'december 1 – december 5, 2026'; '4–21 february' -> '4 february – 21 february'
    t = re.sub(rf"\b({_MON})\b\.?\s+(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})(?![\d.:/])", r"\1 \2 – \1 \3", t)
    t = re.sub(rf"(?<![\d./])(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})\s+(?:de\s+)?({_MON})\b", r"\1 \3 – \2 \3", t)
    pats = [
        (r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "ymd"),
        (r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", "ymd"),
        (r"(?<![\d])(\d{1,2})\s*月\s*(\d{1,2})\s*日", "md"),
        (r"(?<![\d])(\d{1,2})\s*월\s*(\d{1,2})\s*일", "md"),
        (r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", "ymd"),
        (r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})", "dmy"),
        (r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?![\d./])", "md_dot"),
        (rf"(?<!\d)(\d{{1,2}})\s*(?:de\s+)?({_MON})\b\.?,?(?:\s+(?:de\s+)?(\d{{4}}))?", "d_mon_y"),
        (rf"\b({_MON})\b\.?\s+(\d{{1,2}})(?!\d)(?:,?\s*(\d{{4}}))?", "mon_d_y"),
        (rf"\b({_MON})\b\.?\s+(\d{{4}})", "mon_y"),
    ]
    taken = []
    out = []
    for pat, kind in pats:
        for m in re.finditer(pat, t):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            g = m.groups()
            y = mo = d = None
            if kind == "ymd":
                y, mo, d = g
            elif kind == "md":
                mo, d = g
            elif kind == "dmy":
                d, mo, y = g
            elif kind == "md_dot":
                # ambiguous (US m.d vs EU d.m); only used when nothing else matches
                continue
            elif kind == "d_mon_y":
                d, mo, y = g[0], MONTHS[g[1]], g[2]
            elif kind == "mon_d_y":
                mo, d, y = MONTHS[g[0]], g[1], g[2]
            elif kind == "mon_y":
                mo, y = MONTHS[g[0]], g[1]
            taken.append((m.start(), m.end()))
            out.append((m.start(), int(y) if y else None, int(mo) if mo else None, int(d) if d else None))
    # bare year tokens that follow a day-month token ("1 October – 10 January 2027")
    return sorted(out)


def parse_date_range(text: str | None, default_year: int | None = None):
    """Return (start, start_precision, end, end_precision). Missing years are inherited from the other end
    (end year, rolled back one year if the start month is later than the end month). Never invents days."""
    if not text:
        return None, None, None, None
    toks = _tokens(text)
    if not toks:
        years = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
        if years:
            return f"{years[0]}", "year", (f"{years[-1]}" if len(years) > 1 else None), ("year" if len(years) > 1 else None)
        return None, None, None, None
    s = toks[0]
    e = toks[-1] if len(toks) > 1 else None
    if e is None and re.search(r"\b(through|thru|until|till|bis|jusqu|hasta|até|fino al)\b|까지|まで", text.lower()):
        ey, em, ed = s[1:]
        end = _fmt(ey or default_year, em, ed)
        return None, None, end[0], end[1]
    sy, sm, sd = s[1:]
    if e:
        ey, em, ed = e[1:]
        if ey is None:
            ey = sy or default_year
        if sy is None and ey is not None:
            sy = ey - 1 if (sm and em and sm > em) else ey
    else:
        ey = em = ed = None
    if sy is None:
        sy = default_year
    start = _fmt(sy, sm, sd)
    end = _fmt(ey, em, ed) if e else None
    return start[0], start[1], (end[0] if end else None), (end[1] if end else None)


def _fmt(y, m, d):
    if y and m and d:
        v = _mk(y, m, d)
        return (v, "day") if v else (None, None)
    if y and m:
        return f"{int(y):04d}-{int(m):02d}", "month"
    if y:
        return f"{int(y):04d}", "year"
    return None, None


def iso_from_rfc822(s: str | None):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).isoformat()
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None


def jsonld_objects(html: str):
    """All JSON-LD objects (flattening @graph and lists)."""
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                if "@graph" in x:
                    stack.append(x["@graph"])
    return out


def next_data(html: str):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def parse_feed(content: bytes):
    """RSS 2.0 / RSS 1.0 (RDF) / Atom -> list of dict(title, link, published, updated, author, categories, summary)."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser=parser)
    if root is None:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}
    items = []
    for it in root.iter("item"):
        items.append(dict(
            title=clean_text(it.findtext("title")),
            link=(it.findtext("link") or "").strip(),
            guid=(it.findtext("guid") or "").strip(),
            published=iso_from_rfc822(it.findtext("pubDate") or it.findtext("dc:date", namespaces=ns)),
            updated=None,
            author=clean_text(it.findtext("dc:creator", namespaces=ns) or it.findtext("author")),
            categories=[clean_text(c.text) for c in it.findall("category") if c.text],
            summary=clean_text(BeautifulSoup(it.findtext("description") or "", "lxml").get_text(" ")),
        ))
    rss1 = {"r": "http://purl.org/rss/1.0/", "dc": ns["dc"]}  # RSS 1.0: namespaced <item> siblings of <channel>
    for it in root.iter("{http://purl.org/rss/1.0/}item"):
        items.append(dict(
            title=clean_text(it.findtext("r:title", namespaces=rss1)),
            link=(it.findtext("r:link", namespaces=rss1) or "").strip(),
            guid=(it.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "").strip(),
            published=iso_from_rfc822(it.findtext("dc:date", namespaces=rss1)),
            updated=None,
            author=clean_text(it.findtext("dc:creator", namespaces=rss1)),
            categories=[clean_text(c.text) for c in it.findall("dc:subject", rss1) if c.text],
            summary=clean_text(BeautifulSoup(it.findtext("r:description", namespaces=rss1) or "", "lxml").get_text(" ")),
        ))
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = it.find("atom:link[@rel='alternate']", ns) or it.find("atom:link", ns)
        items.append(dict(
            title=clean_text(it.findtext("atom:title", namespaces=ns)),
            link=link.get("href") if link is not None else "",
            guid=(it.findtext("atom:id", namespaces=ns) or "").strip(),
            published=iso_from_rfc822(it.findtext("atom:published", namespaces=ns)),
            updated=iso_from_rfc822(it.findtext("atom:updated", namespaces=ns)),
            author=clean_text(it.findtext("atom:author/atom:name", namespaces=ns)),
            categories=[c.get("term") for c in it.findall("atom:category", ns) if c.get("term")],
            summary=clean_text(BeautifulSoup(it.findtext("atom:summary", namespaces=ns) or "", "lxml").get_text(" ")),
        ))
    return items


_TITLE_SPLIT = re.compile(r"^\s*([^:：|–—]{2,60}?)\s*[:：]\s+\S")


def split_title_artist(title: str) -> str | None:
    """'Beatriz González: In Series and Full Color' -> 'Beatriz González'. Returns None when the prefix
    does not look like a personal name (contains digits, generic words, or >5 tokens)."""
    m = _TITLE_SPLIT.match(title or "")
    if not m:
        return None
    name = m.group(1).strip()
    bad = re.compile(r"\d|\b(the|of|and|in|on|art|arts|collection|exhibition|gallery|museum|biennial|triennial|"
                     r"prize|award|project|series|focus|now|new|room|works|photography|painting|drawing|"
                     r"contemporary|modern|history|selections?|from|with|for)\b", re.I)
    if bad.search(name) or len(name.split()) > 5:
        return None
    return name


def classify_subtype(title: str, n_artists: int | None = None) -> str:
    t = (title or "").lower()
    if any(k in t for k in ("collection", "소장품", "所蔵", "コレクション", "colección", "coleção", "collezione")):
        return "collection_display"
    if n_artists == 1:
        return "solo"
    if n_artists and n_artists > 1:
        return "group" if n_artists > 2 else "two_person"
    return "unknown"
