"""Global art media: criticism/news article METADATA from official RSS feeds and public sitemaps (Blueprint D32-D37).

metadata_only: title, canonical URL, author, published_at, categories, lang, article_type (+type_basis).
No article bodies or excerpts are stored. Only feed page 1 is polled for enabled feeds.
Explicit anti-crawler terms block collection pending permission, including RSS.
History therefore accumulates from repeated incremental runs.
e-flux has no RSS feed: its public sitemaps list criticism/announcement URLs and each detail page carries
JSON-LD (Review / Event) with the metadata; detail fetches are capped per run.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from lxml import etree

from .. import db
from ..config import iso_now
from ..http import FetchError
from ._common import clean_text, jsonld_objects, parse_feed

PARSER_VERSION = "gl_media-1"
SINCE = "2025-04-01"
MAX_FEED_PAGES = 60

_PMC_TERMS = ("RESTRICTIVE: restrictive ToS (anti-crawler clause: PMC terms forbid spiders/crawlers 'to access, acquire, copy, "
              "monitor, scrape or aggregate', search engines excepted; personal non-commercial use only); "
              "collection disabled pending explicit permission; RSS is not a permission exception")


def _row(source_id, name, publisher, owner_group, entry_url, base_url, terms_url, coll, img, data_id="D32",
         org_id=None, country="", region="GLOBAL", access="rss", max_requests=80, **kw):
    r = dict(source_id=source_id, blueprint_data_id=data_id, blueprint_org_id=org_id, name=name, owner_group=owner_group,
             source_kind="media", region_scope=region, country_codes=country, access_method=access, base_url=base_url,
             entry_url=entry_url, terms_url=terms_url, text_storage_policy="metadata_only", priority="P1",
             st_official_doc="n/a(official RSS feed)" if access == "rss" else "n/a(public sitemap + JSON-LD)",
             st_collection_terms=coll, st_image_terms=img, max_requests=max_requests, publisher=publisher)
    r.update(kw)
    if source_id in {"artnews_feed", "art_in_america_feed", "artforum_feed", "artasiapacific_rss"}:
        r.update(disabled="Explicit anti-crawler/extraction terms; permission required even for RSS",
                 operational_state="blocked_permission")
    return r


SOURCES = [
    _row("hyperallergic_feed", "Hyperallergic — RSS", "Hyperallergic", "Hyperallergic Media", "https://hyperallergic.com/feed/",
         "https://hyperallergic.com", "https://hyperallergic.com/terms-of-use/", country="US",
         coll="terms of use: copying, redistribution, use or publication of any portion of the website strictly prohibited; "
             "no explicit crawler clause; only official feed polled, metadata only",
         img="images not collected (terms prohibit copying)"),
    _row("artnews_feed", "ARTnews — RSS", "ARTnews", "Penske Media", "https://www.artnews.com/feed/", "https://www.artnews.com",
         "https://www.artnews.com/terms-of-use/", country="US", coll=_PMC_TERMS, img="images not collected (PMC terms reserve rights)"),
    _row("art_in_america_feed", "Art in America — RSS", "Art in America", "Penske Media",
         "https://www.artnews.com/c/art-in-america/feed/", "https://www.artnews.com", "https://www.artnews.com/terms-of-use/",
         country="US", coll=_PMC_TERMS, img="images not collected (PMC terms reserve rights)"),
    _row("artforum_feed", "Artforum — RSS", "Artforum", "Penske Media", "https://www.artforum.com/feed/",
         "https://www.artforum.com", "https://pmc.com/terms-of-use/", data_id="D33", country="US", coll=_PMC_TERMS,
         img="images not collected (PMC terms reserve rights)"),
    _row("theartnewspaper_rss", "The Art Newspaper — RSS", "The Art Newspaper", "Umberto Allemandi / The Art Newspaper",
         "https://www.theartnewspaper.com/rss.xml", "https://www.theartnewspaper.com",
         "https://www.theartnewspaper.com/information/terms-and-conditions", country="GB",
         coll="terms and conditions: all rights reserved; copies for personal use only; no robot/crawler clause; "
              "official feed polled, metadata only", img="images not collected (terms: no separate use of illustrations)"),
    _row("artasiapacific_rss", "ArtAsiaPacific — RSS", "ArtAsiaPacific", "ArtAsiaPacific", "https://www.artasiapacific.com/rss/",
         "https://www.artasiapacific.com", "https://www.artasiapacific.com/legal/", country="HK",
         coll="RESTRICTIVE: terms of use forbid 'scripts designed to scrape or extract data from the Service' and "
              "mirroring/reproduction; collection disabled pending permission",
         img="images not collected"),
    _row("artreview_rss", "ArtReview — RSS", "ArtReview", "ArtReview", "https://artreview.com/rss.xml", "https://artreview.com",
         None, country="GB", coll="terms page not located (/feed/ 404; official /rss.xml used)", img="images not collected"),
    _row("eflux_criticism", "e-flux Criticism — sitemap + JSON-LD", "e-flux", "e-flux", "https://www.e-flux.com/sitemaps/criticism.xml",
         "https://www.e-flux.com", "https://www.e-flux.com/privacy", access="sitemap", country="US", max_requests=80,
         coll="privacy page only; no reuse terms located; only JSON-LD metadata (headline/author/date/keywords) kept",
         img="images not collected"),
    _row("eflux_announcements", "e-flux Announcements — sitemap + JSON-LD", "e-flux", "e-flux",
         "https://www.e-flux.com/sitemaps/announcements-1.xml", "https://www.e-flux.com", "https://www.e-flux.com/privacy",
         access="sitemap", country="US", max_requests=80,
         coll="privacy page only; announcements are paid institutional press releases; metadata only kept",
         img="images not collected"),
    _row("frieze_feed", "frieze — RSS", "frieze", "Frieze", "https://www.frieze.com/rss.xml", "https://www.frieze.com", None,
         country="GB", coll="not reachable (HTTP 403)", img="not reachable",
         disabled="HTTP 403 to the project crawler on frieze.com (checked 2026-10-27); not bypassed",
         operational_state="blocked_access", robots_status="not_checked(site returns 403)", st_live_response="blocked(403)"),
]

_TYPE_RULES = [  # (regex on category / url section, article_type)
    (r"^(art )?reviews?$|^aia-reviews$|^exhibition reviews?$|^critics'? picks?$|^book reviews?$", "review"),
    (r"^interviews?$|^conversations?$|^artist interview$|^author q&a$", "interview"),
    (r"^(opinion|op-?eds?|essays?|criticism|columns?|comment)$", "criticism"),  # "Feature(s)" stays unknown
    (r"^(news|obituar(y|ies)|market|art market|museums & heritage|morning links|news roundup)$", "news"),
    (r"^(sponsored|partner content|paid content|brandedcontent)$", "sponsored"),
    (r"^announcements?$", "announcement"),
]


def _classify(categories, url):
    for c in categories:
        k = (c or "").strip().lower()
        for rx, t in _TYPE_RULES:
            if re.search(rx, k):
                return t, f"feed_category:{c}"
    segs = [s for s in urllib.parse.urlsplit(url).path.split("/") if s]
    if "artreview.com" in url and segs:  # flat URLs; reviews end in "-review-<critic>", interviews start "the-interview-"
        if segs[-1].startswith("the-interview-"):
            return "interview", "url_slug:the-interview-"
        if re.search(r"-review-[a-z]+(-[a-z]+)*$", segs[-1]):
            return "review", "url_slug:-review-<critic>"
    for s in segs[:-1]:
        for rx, t in _TYPE_RULES:
            if re.search(rx, s.replace("-", " ").lower()) or re.search(rx, s.lower()):
                return t, f"url_section:/{s}/"
    return "unknown", None


def _canon(url):
    p = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def _feed_lang(content: bytes):
    m = re.search(rb"<language>\s*([A-Za-z-]{2,10})\s*</language>", content[:5000])
    return m.group(1).decode().lower() if m else None


def collect(ctx):
    if ctx.source_id.startswith("eflux_"):
        return _collect_eflux(ctx)
    return _collect_feed(ctx)


def _store(ctx, *, url, title, published, author, categories, lang, article_type=None, type_basis=None, modified=None):
    if not url or not title:
        ctx.count("skipped_incomplete")
        return False
    if article_type is None:
        article_type, type_basis = _classify(categories, url)
    db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=_canon(url), title=title,
                      published_at=published, author_text=author or None, publisher=ctx.meta["publisher"],
                      owner_group=ctx.meta["owner_group"], article_type=article_type, type_basis=type_basis, lang=lang,
                      modified_at=modified, categories="; ".join(categories) if categories else None, excerpt=None)
    ctx.count("parsed")
    return True


def _known(ctx, url):
    return ctx.con.execute("SELECT 1 FROM articles WHERE article_id=?", (db.sid("art", _canon(url)),)).fetchone() is not None


def _collect_feed(ctx):
    entry = ctx.meta["entry_url"]
    # Restricted publishers are disabled in the registry, including their feeds.
    paged = ctx.meta.get("feed_paging", False)
    max_pages = (MAX_FEED_PAGES if ctx.mode == "initial" else 5) if paged else 1
    oldest, page = None, 1
    while page <= max_pages:
        try:
            r = ctx.fetch(entry, params={"paged": page} if page > 1 else None, accept="application/rss+xml, application/xml")
        except FetchError as e:
            if page > 1:  # past the last WordPress page
                ctx.note(f"paging stopped at page {page}: {e}")
                break
            raise
        items = parse_feed(r.content)
        lang = _feed_lang(r.content) or "en"
        ctx.count("fetched", len(items))
        if not items:
            break
        all_known = True
        for it in items:
            url = it["link"] or it["guid"]
            if not _known(ctx, url):
                all_known = False
            _store(ctx, url=url, title=it["title"], published=it["published"] or it["updated"], author=it["author"],
                   categories=[c for c in it["categories"] if c], lang=lang.split("-")[0], modified=it["updated"])
            if it["published"] and (oldest is None or it["published"] < oldest):
                oldest = it["published"]
        ctx.con.commit()
        if not paged or (oldest and oldest[:10] < SINCE):
            break
        if ctx.mode != "initial" and all_known:
            break
        page += 1
    if paged:
        ctx.note(f"WordPress feed paged to page {min(page, max_pages)}; oldest item {oldest}")
    else:
        ctx.note(f"feed exposes latest items only (no paging); oldest item {oldest}")
    ctx.con.commit()


# -- e-flux --------------------------------------------------------------------------------------------------------
EFLUX_DETAIL_CAP = {"initial": 60, "incremental": 30}


def _collect_eflux(ctx):
    r = ctx.fetch(ctx.meta["entry_url"], accept="application/xml")
    root = etree.fromstring(r.content, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for u in root.findall("s:url", ns):
        loc = (u.findtext("s:loc", namespaces=ns) or "").strip()
        m = re.search(r"/(?:criticism|announcements)/(\d+)/", loc)
        if m:
            urls.append((int(m.group(1)), loc))
    urls.sort(reverse=True)  # e-flux numeric ids grow with publication
    ctx.count("fetched", len(urls))
    is_ann = ctx.source_id == "eflux_announcements"
    cap = EFLUX_DETAIL_CAP[ctx.mode]
    done = known_run = 0
    known_limit = 60
    for _id, loc in urls:
        if done >= cap:
            break
        if _known(ctx, loc):
            # still listed in the official sitemap: refresh last_seen only (metadata unchanged, no refetch)
            ctx.con.execute("UPDATE articles SET last_seen_at=? WHERE article_id=?", (iso_now(), db.sid("art", _canon(loc))))
            ctx.count("parsed")
            ctx.count("unchanged")
            known_run += 1
            if ctx.mode == "incremental" and known_run >= known_limit:
                break  # Incremental checks the newest window; initial continues archive backfill.
            continue
        known_run = 0
        try:
            d = ctx.fetch(loc)
        except FetchError as e:
            ctx.note(f"detail {loc}: {e}")
            ctx.count("detail_errors")
            continue
        done += 1
        objs = [o for o in jsonld_objects(d.text) if o.get("@type") in ("Review", "Article", "Event", "NewsArticle")]
        o = objs[0] if objs else {}
        # announcements: JSON-LD Event name drops the "Artist: Title" colon, og:title keeps the page title
        title = (_og_title(d.text) if is_ann else None) or clean_text(o.get("headline") or o.get("name")) or _og_title(d.text)
        authors = o.get("author") or []
        if isinstance(authors, dict):
            authors = [authors]
        author = "; ".join(a.get("name") for a in authors if isinstance(a, dict) and a.get("name")) or None
        published = o.get("datePublished")
        if not published and is_ann:
            published = _ann_date(d.text)
        kws = o.get("keywords") or []
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",")]
        if is_ann:
            atype, basis = "announcement", "url_section:/announcements/"
        else:
            atype, basis = ("review", "jsonld:@type=Review") if o.get("@type") == "Review" else ("criticism", "url_section:/criticism/")
        _store(ctx, url=loc, title=title, published=published, author=author, categories=[k for k in kws if k],
               lang="en", article_type=atype, type_basis=basis, modified=o.get("dateModified"))
        if done % 20 == 0:
            ctx.con.commit()
    ctx.note(f"sitemap lists {len(urls)} URLs; fetched {done} unseen details (cap {cap}/run, newest first)")
    ctx.con.commit()


def _og_title(html):
    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if not m:
        return None
    return clean_text(re.sub(r"\s+-\s+(Announcements|Criticism)\s+-\s+e-flux$", "", m.group(1)))


def _ann_date(html):
    # announcement pages show the publication date as <div class="announcement__date">October 27, 2026</div>
    m = re.search(r'class="announcement__date">([A-Z][a-z]+ \d{1,2}, \d{4})<', html)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None
