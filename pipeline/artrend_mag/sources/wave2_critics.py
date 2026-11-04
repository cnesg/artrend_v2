"""Wave 2 critics/criticism platforms: author-attributed article METADATA only (sourcebook rows 미주-07-002, 유럽-07-001/002/004/006,
일본-07-003/006, 한국-07-005/006, 한국-09-002).

Collected (metadata_only; no bodies, excerpts, claims, quotations or identity confirmation; author_text kept verbatim as printed):
  * aica_agora_feed   AICA International AGORA news feed (Squarespace RSS, ``?format=rss`` + ``offset`` paging). The feed byline is
                      the organisation ("AICA International"), not an individual critic.
  * afterall_articles Afterall (WordPress) article sitemaps -> detail page metadata block (title, "Publish date", "Written by",
                      article-type labels). Sitemap only carries <lastmod>, so details are fetched newest-lastmod first,
                      unseen only, capped per run; the archive therefore accumulates over repeated runs.
All other rows are disabled registry entries recording a verified block (robots / terms / HTTP 403).
"""
from __future__ import annotations

import datetime as dt
import re

from lxml import etree

from .. import db
from ..http import FetchError
from ._common import MONTHS, clean_text, parse_feed, soup

PARSER_VERSION = "wave2_critics-1"
FEED_SINCE = "2023-01-01"
AICA_MAX_PAGES = {"initial": 40, "incremental": 1}
AFTERALL_DETAIL_CAP = {"initial": 200, "incremental": 30}
AFTERALL_SITEMAP_INDEX = "https://www.afterall.org/wp-sitemap.xml"

_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_AFTERALL_TYPES = {"review": "review", "interview": "interview", "conversation": "interview", "essay": "criticism"}


def _live(source_id, name, publisher, owner, country, region, entry, base, terms, coll, access, note, max_requests, lang):
    return dict(source_id=source_id, blueprint_data_id=None, blueprint_org_id=None, name=name, owner_group=owner,
                source_kind="media", region_scope=region, country_codes=country, access_method=access, base_url=base,
                entry_url=entry, terms_url=terms, text_storage_policy="metadata_only", priority="P2",
                st_official_doc="n/a(" + access + ")", st_collection_terms=coll, st_image_terms="images not collected",
                max_requests=max_requests, notes=note, publisher=publisher, lang=lang)


def _blocked(source_id, name, owner, country, region, entry, base, terms, coll, state, robots, live, note):
    return dict(source_id=source_id, blueprint_data_id=None, blueprint_org_id=None, name=name, owner_group=owner,
                source_kind="media", region_scope=region, country_codes=country, access_method="html", base_url=base,
                entry_url=entry, terms_url=terms, text_storage_policy="metadata_only", priority="P2",
                st_official_doc="n/a(html)", st_collection_terms=coll, st_image_terms="images not collected",
                max_requests=0, notes=note, disabled=coll, operational_state=state, robots_status=robots, st_live_response=live)


_GUARDIAN_TERMS = ("Guardian terms of service s.3 forbid any robot/bot/spider/scraper/crawler or other automated data-gathering "
                   "tool on the site or content without written approval, state robots.txt is not permission; checked 2026-10-28")

SOURCES = [
    _live("aica_agora_feed", "AICA International — AGORA news feed", "AICA International", "AICA International", "", "GLOBAL",
          "https://aicainternational.news/agora", "https://aicainternational.news", "https://aicainternational.news/robots.txt",
          "no terms page located on the site; robots.txt (Squarespace default) does not disallow ?format=rss; official RSS only, "
          "metadata only", "rss",
          "sourcebook 유럽-07-004 (AICA International). SAMPLE of association news/announcements from the AGORA RSS (20 items "
          "per page, offset paging back to 2023-01-01 in initial mode); bylines are the organisation, not critics; "
          "no author archive, claims or quotations collected.", 60, "en"),
    _live("afterall_articles", "Afterall — articles (sitemap + detail metadata)", "Afterall", "Afterall, University of the Arts London",
          "GB", "EUROPE", "https://www.afterall.org/wp-sitemap.xml", "https://www.afterall.org",
          "https://www.afterall.org/terms-and-conditions/",
          "terms: texts from 2011 (issue 26) onwards are CC BY-NC-ND 3.0 (attribution, non-commercial, no derivatives), older texts "
          "all rights reserved; no robot clause; robots.txt allows (Crawl-delay 2); only title/date/byline/type labels kept", "sitemap",
          "sourcebook 유럽-07-006 (Afterall). Articles only (event/publication/video sitemaps not read). Details fetched newest "
          "<lastmod> first, unseen only, 200/run initial and 30/run incremental, so the archive is a growing SAMPLE not a full "
          "mirror; <lastmod> reflects edits, not publication date. author_text is the 'Written by' line verbatim.", 250, "en"),
    _blocked("nymag_saltz_author", "New York Magazine — Jerry Saltz author page", "Vox Media", "US", "AMERICAS",
             "https://nymag.com/author/jerry-saltz/", "https://nymag.com",
             "https://nymag.com/robots.txt", "HTTP 403 (http_block) to the project crawler on the author page, checked 2026-10-28; not bypassed",
             "blocked_access", "allowed(robots.txt parsed; page returns 403)", "blocked(403)",
             "sourcebook 미주-07-002 (Jerry Saltz). Author page returns 403 to the identified crawler; no alternate public feed verified."),
    _blocked("guardian_judah_profile", "The Guardian — Hettie Judah profile", "Guardian Media Group", "GB", "EUROPE",
             "https://www.theguardian.com/profile/hettie-judah", "https://www.theguardian.com",
             "https://www.theguardian.com/help/terms-of-service", _GUARDIAN_TERMS, "blocked_permission",
             "parsed(allows /profile); terms prohibit automated collection", "not_requested(terms)",
             "sourcebook 유럽-07-001 (Hettie Judah). Profile and per-author RSS exist publicly but Guardian terms forbid automated "
             "collection irrespective of robots.txt."),
    _blocked("guardian_searle_profile", "The Guardian — Adrian Searle profile", "Guardian Media Group", "GB", "EUROPE",
             "https://www.theguardian.com/profile/adriansearle", "https://www.theguardian.com",
             "https://www.theguardian.com/help/terms-of-service", _GUARDIAN_TERMS, "blocked_permission",
             "parsed(allows /profile); terms prohibit automated collection", "not_requested(terms)",
             "sourcebook 유럽-07-002 (Adrian Searle). Same Guardian terms block as guardian_judah_profile."),
    _blocked("webgenron_kurose_author", "webゲンロン — 黒瀬陽平 author page", "Genron", "JP", "JP",
             "https://www.webgenron.com/authors/kurose", "https://www.webgenron.com", "https://www.webgenron.com/kiyaku",
             "webゲンロン 会員規約 art.10 prohibits accessing the service with automated means (robots, botnets, scrapers) and "
             "copying content beyond copyright law; checked 2026-10-28", "blocked_permission",
             "not_found(allow)", "not_requested(terms)",
             "sourcebook 일본-07-003 (黒瀬陽平 Yohei Kurose). Public author page lists article titles but terms forbid automated access."),
    _blocked("webgenron_articles", "webゲンロン — article index", "Genron", "JP", "JP",
             "https://www.webgenron.com/articles", "https://www.webgenron.com", "https://www.webgenron.com/kiyaku",
             "webゲンロン 会員規約 art.10 prohibits automated access (robots, botnets, scrapers); checked 2026-10-28",
             "blocked_permission", "not_found(allow)", "not_requested(terms)",
             "sourcebook 일본-07-006 (webゲンロン). Same terms block as webgenron_kurose_author."),
    _blocked("kci_art_theory_field", "KCI — 미술이론과현장 search", "Korea Citation Index (NRF)", "KR", "KR",
             "https://www.kci.go.kr/", "https://www.kci.go.kr", None,
             "robots.txt Disallow all for the project user agent (checked 2026-10-28); KCI Open API requires an authorisation key",
             "blocked_permission", "disallow(all)", "not_requested(robots)",
             "sourcebook 한국-07-005 (미술이론과현장 — KCI 검색). Web search blocked by robots; keyed OpenAPI is out of scope (no credentials)."),
    _blocked("sema_research_publications", "SeMA — 연구·출판", "Seoul Museum of Art", "KR", "KR",
             "https://sema.seoul.go.kr/", "https://sema.seoul.go.kr", None,
             "robots.txt Disallow / except /kr/whatson, /en/whatson, /kr/bbs (checked 2026-10-28); research/publication menus lie outside the allowlist",
             "blocked_permission", "disallow(/ except whatson,bbs)", "not_requested(robots)",
             "sourcebook 한국-07-006 (SeMA 연구·출판). Publication/research routes disallowed by robots.txt."),
    _blocked("sema_collection_works", "SeMA — 소장품", "Seoul Museum of Art", "KR", "KR",
             "https://sema.seoul.go.kr/", "https://sema.seoul.go.kr", None,
             "robots.txt Disallow / except /kr/whatson, /en/whatson, /kr/bbs (checked 2026-10-28); collection routes are disallowed",
             "blocked_permission", "disallow(/ except whatson,bbs)", "not_requested(robots)",
             "sourcebook 한국-09-002 (서울시립미술관 소장품). Collection routes disallowed by robots.txt; no works collected."),
]


# -- shared ---------------------------------------------------------------------------------------------------------
def _store(ctx, *, url, title, published, author, categories, article_type="unknown", type_basis=None, modified=None):
    if not url or not title:
        ctx.count("skipped_incomplete")
        return False
    db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=url, title=title, published_at=published,
                      author_text=author or None, publisher=ctx.meta["publisher"], owner_group=ctx.meta["owner_group"],
                      article_type=article_type, type_basis=type_basis, lang=ctx.meta.get("lang"), modified_at=modified,
                      categories="; ".join(categories) if categories else None, excerpt=None)
    ctx.count("parsed")
    return True


def _known(ctx, url):
    return ctx.con.execute("SELECT 1 FROM articles WHERE article_id=?", (db.sid("art", url),)).fetchone() is not None


# -- AICA AGORA ------------------------------------------------------------------------------------------------------
def parse_aica_feed(content: bytes):
    """Squarespace RSS -> [{url,title,published,author}]; byline is the organisation as printed."""
    return [dict(url=it["link"] or None, title=it["title"], published=it["published"], author=it["author"] or None)
            for it in parse_feed(content)]


def _epoch_ms(iso):
    d = dt.datetime.fromisoformat(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def _collect_aica(ctx):
    entry = ctx.meta["entry_url"]
    oldest, offset, pages = None, None, 0
    while pages < AICA_MAX_PAGES[ctx.mode]:
        params = {"format": "rss"}
        if offset:
            params["offset"] = offset
        r = ctx.fetch(entry, params=params, accept="application/rss+xml, application/xml")
        items = parse_aica_feed(r.content)
        pages += 1
        ctx.count("fetched", len(items))
        dated = [i["published"] for i in items if i["published"]]
        if not items or not dated:
            break
        for it in items:
            _store(ctx, url=it["url"], title=it["title"], published=it["published"], author=it["author"], categories=[])
        ctx.con.commit()
        oldest = min(dated)
        if oldest[:10] < FEED_SINCE:
            break
        new_offset = _epoch_ms(oldest)
        if new_offset == offset:
            break
        offset = new_offset
    ctx.note(f"AGORA RSS paged {pages} page(s) via ?format=rss&offset=<epoch ms>; oldest item {oldest}; "
             "organisation byline only; no article bodies")
    ctx.con.commit()


# -- Afterall -------------------------------------------------------------------------------------------------------
def parse_sitemap(content: bytes):
    root = etree.fromstring(content, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    out = []
    if root is None:
        return out
    for u in root.findall("s:url", _NS):
        loc = (u.findtext("s:loc", namespaces=_NS) or "").strip()
        if loc:
            out.append((loc, (u.findtext("s:lastmod", namespaces=_NS) or "").strip() or None))
    for sm in root.findall("s:sitemap", _NS):
        loc = (sm.findtext("s:loc", namespaces=_NS) or "").strip()
        if loc:
            out.append((loc, None))
    return out


def parse_afterall_date(text):
    """'13 apr 2022' -> '2022-04-13' (day precision as printed). Anything else -> None."""
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", clean_text(text))
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return dt.date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_afterall_article(html: str):
    s = soup(html)
    h1 = s.select_one("h1.hero-article__title")
    meta = s.select_one("div.metadata")
    out = dict(title=clean_text(h1.get_text(" ")) if h1 else None, published=None, author=None, categories=[])
    if meta is None:
        return out
    for a in meta.select('a[href*="article-type="]'):
        label = clean_text(a.get_text(" "))
        if label:
            out["categories"].append(label)
    for span in meta.select("span.u-block"):
        txt = clean_text(span.get_text(" "))
        if txt.lower().startswith("publish date"):
            inner = span.find("span")
            out["published"] = parse_afterall_date(inner.get_text(" ") if inner else txt.split(":", 1)[-1])
    for p in meta.select("p"):
        txt = clean_text(p.get_text(" "))
        if txt.startswith("Written by "):
            out["author"] = txt[len("Written by "):].strip() or None
    return out


def afterall_type(categories):
    for c in categories:
        t = _AFTERALL_TYPES.get(c.strip().lower())
        if t:
            return t, f"afterall_article_type:{c}"
    return "unknown", None


def _collect_afterall(ctx):
    idx = parse_sitemap(ctx.fetch(AFTERALL_SITEMAP_INDEX, accept="application/xml").content)
    article_maps = [loc for loc, _ in idx if re.search(r"wp-sitemap-posts-article-\d+\.xml$", loc)]
    urls = []
    for loc in article_maps:
        urls.extend(parse_sitemap(ctx.fetch(loc, accept="application/xml").content))
    urls.sort(key=lambda t: t[1] or "", reverse=True)
    ctx.count("fetched", len(urls))
    cap, done = AFTERALL_DETAIL_CAP[ctx.mode], 0
    for loc, lastmod in urls:
        if done >= cap:
            break
        if _known(ctx, loc):
            continue
        try:
            d = ctx.fetch(loc)
        except FetchError as e:
            ctx.note(f"detail {loc}: {e}")
            ctx.count("detail_errors")
            continue
        done += 1
        p = parse_afterall_article(d.text)
        atype, basis = afterall_type(p["categories"])
        _store(ctx, url=loc, title=p["title"], published=p["published"], author=p["author"], categories=p["categories"],
               article_type=atype, type_basis=basis, modified=lastmod)
        if done % 20 == 0:
            ctx.con.commit()
    ctx.note(f"{len(article_maps)} article sitemaps list {len(urls)} URLs; fetched {done} unseen details (cap {cap}/run, "
             "newest <lastmod> first); partial archive sample")
    ctx.con.commit()


def collect(ctx):
    if ctx.source_id == "aica_agora_feed":
        _collect_aica(ctx)
    elif ctx.source_id == "afterall_articles":
        _collect_afterall(ctx)
    else:
        raise ValueError(f"wave2_critics cannot collect {ctx.source_id}")
