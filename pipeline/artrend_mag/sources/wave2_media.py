"""Wave 2 media metadata from public feeds and a public article index.

Only bibliographic metadata is stored; feed summaries, article bodies, and images are
never persisted. A feed's published date/author/category are used only when the feed
states them. HTML listing pages are parsed without fetching article details.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime

from lxml import etree

from .. import db
from ..http import FetchError
from ._common import clean_text, parse_feed, soup

PARSER_VERSION = "wave2_media-2"
INITIAL_CUTOFF = "2025-04-01"
MAX_INITIAL_FEED_PAGES = 40


def _row(source_id, name, owner_group, region, country, base_url, entry_url, access_method,
         terms_url, collection_terms, fields, notes, *, feed_paging=False, max_requests=80):
    return dict(
        source_id=source_id,
        blueprint_data_id=None,
        blueprint_org_id=None,
        name=name,
        owner_group=owner_group,
        publisher=owner_group,
        source_kind="media",
        region_scope=region,
        country_codes=country,
        access_method=access_method,
        base_url=base_url,
        entry_url=entry_url,
        terms_url=terms_url,
        text_storage_policy="metadata_only",
        priority="P1",
        st_official_doc="n/a(official public feed/list)",
        st_collection_terms=collection_terms,
        st_image_terms="No images fetched or stored; image reuse rights not assessed.",
        st_fields_extracted=fields,
        st_history="Public feed/list only; not a complete source archive.",
        st_incremental="Public feed/list metadata only; rerunnable upserts; no article detail fetches.",
        notes=notes,
        feed_paging=feed_paging,
        max_requests=max_requests,
    )


SOURCES = [
    _row(
        "art21_articles", "Art21 — RSS article metadata", "Art21", "AMERICAS", "US",
        "https://art21.org", "https://art21.org/feed/", "rss",
        "https://art21.org/terms-of-use/",
        "Terms of Use reserves rights and limits use of materials to personal/nonprofit/noncommercial/educational fair use; other uses require written permission. Robots disallows admin/form-upload paths and sets Crawl-delay: 10. Store only bibliographic RSS metadata; no reuse permission is inferred.",
        "Title, canonical URL, feed creator, publication timestamp, categories, feed language; excerpt/body omitted.",
        "Wave2 media sourcebook 미주-01-007. Saved probe: public RSS pages 1-3 and page 40; robots and terms were saved in prior24-W2Media.",
        feed_paging=True,
    ),
    _row(
        "artishock_articles", "Artishock Revista — RSS article metadata", "Artishock Revista", "AMERICAS", "CL",
        "https://artishockrevista.com", "https://artishockrevista.com/feed/", "rss",
        "https://artishockrevista.com/terminos-legales/",
        "Legal terms §4 allow reasonable cited fragments with attribution and an original link, while prohibiting full/substantial republication; robots has no disallow and Crawl-delay: 20. Collector stores metadata only, not quoted text or feed descriptions.",
        "Title, canonical URL, named feed creator, publication timestamp, categories, feed language; excerpt/body omitted.",
        "Wave2 media sourcebook 미주-01-010. Saved probe: official RSS pages 1-3; terms and robots were saved in prior24-W2Media.",
        feed_paging=True,
    ),
    _row(
        "adesk_articles", "A*DESK — RSS article metadata", "A*DESK", "EUROPE", "ES",
        "https://a-desk.org", "https://a-desk.org/feed/", "rss", None,
        "Saved robots.txt has User-agent * with an empty Disallow and a public sitemap. No general reuse terms were located in the saved probe; metadata only, no reuse permission inferred.",
        "Title, canonical URL, feed creator when present, publication timestamp, categories, feed language; excerpt/body omitted.",
        "Wave2 media sourcebook 유럽-01-011. Saved probe: official RSS pages 1-3 and robots.txt in prior24-W2Media.",
        feed_paging=True,
    ),
    _row(
        "artit_articles", "ART iT — RSS article metadata", "ART iT", "ASIA", "JP",
        "https://www.art-it.asia", "https://www.art-it.asia/feed/", "rss",
        "https://www.art-it.asia/admin_policy/",
        "Saved robots.txt disallows search/query routes but not /feed/; the opened admin_policy page is a privacy policy, not content-reuse permission, and notes copyrighted images. Only RSS metadata is stored; no bodies or images.",
        "Title, canonical URL, feed creator, publication timestamp, categories, feed language; article/ad type only when an explicit feed category supports it; excerpt/body omitted.",
        "Wave2 media sourcebook 일본-01-004. Saved probe: official RSS pages 1-3, robots, and privacy-policy page in prior24-W2Media.",
        feed_paging=True,
    ),
    _row(
        "artchosun_articles", "Art Chosun — RSS article metadata", "Chosun Media", "ASIA", "KR",
        "https://art.chosun.com", "https://art.chosun.com/site/data/rss/rss.xml", "rss", None,
        "Saved robots.txt explicitly allows / and lists this RSS as its sitemap; /sv* is disallowed. No terms/reuse page was opened in the saved probes; metadata only and no permission inferred.",
        "Title, canonical URL, feed creator, publication timestamp, categories, feed language; excerpt/body omitted.",
        "Wave2 media sourcebook 한국-01-008. Saved probe: official RSS and robots.txt in prior24-W2Media.",
        feed_paging=False,
    ),
    _row(
        "artmonthly_recent", "Art Monthly — recent-articles index", "Art Monthly", "EUROPE", "GB",
        "https://www.artmonthly.co.uk", "https://www.artmonthly.co.uk/magazine/site/article/recent-articles", "html",
        None,
        "Saved robots.txt disallows /?URL=* and two gallery-map paths; the observed clean recent-articles path is not disallowed. No general terms/reuse page was located in the saved probe. The index synopsis, bodies, and images are not stored.",
        "Article title and canonical URL from list markup; author and publication date are not shown in the index and remain unknown.",
        "Wave2 media sourcebook 유럽-01-006. Saved probe: public recent-articles index contains cards from 2018–2026, robots.txt, and one article page in prior24-W2Media; this collector does not fetch article pages.",
        feed_paging=False,
        max_requests=20,
    ),
    _row(
        "cmagazine_articles", "C Magazine — homepage article metadata", "C Magazine", "AMERICAS", "CA",
        "https://cmagazine.com", "https://cmagazine.com/", "html",
        "https://cmagazine.com/privacy-policy",
        "Saved robots.txt allows / but disallows the API sitemap route. The opened privacy policy is not content-reuse permission; parse only public homepage card labels and bibliographic metadata. Do not call the robots-disallowed API sitemap.",
        "Homepage card title, URL, explicit byline and explicit category when present; date not shown; no detail fetches or article text.",
        "Wave2 media sourcebook 미주-01-011. Saved probes show homepage cards, public issue/article markup, and robots-disallowed sitemap API route.",
        feed_paging=False,
        max_requests=20,
    ),
    _row(
        "mousse_articles", "Mousse Magazine — RSS article metadata", "Mousse Magazine", "EUROPE", "IT",
        "https://www.moussemagazine.it", "https://www.moussemagazine.it/feed/", "rss",
        "https://www.moussemagazine.it/terms/",
        "Saved robots.txt disallows /wp-admin/ only; public RSS is allowed. The opened terms page contains only its title, so reuse/automated-access terms remain unknown. Store RSS bibliographic metadata only; do not infer permission.",
        "Title, URL, creator, publication timestamp, categories, and language; no excerpt/body/images.",
        "Wave2 media sourcebook 유럽-01-004. Prior24-W2Media saved official RSS pages 1-3, robots.txt, and the terms page.",
        feed_paging=True,
    ),
    _row(
        "monopol_articles", "Monopol — RSS article metadata", "Monopol", "EUROPE", "DE",
        "https://www.monopol-magazin.de", "https://www.monopol-magazin.de/rss.xml", "rss",
        "https://www.monopol-magazin.de/agbs",
        "Saved robots.txt allows public article routes and disallows technical/admin/search paths. Opened AGB covers subscriptions/products and does not establish content reuse or automated extraction permission; store RSS metadata only.",
        "Title, URL, RSS creator, publication timestamp and language; no categories or excerpt/body/images unless explicitly present in feed metadata.",
        "Wave2 media sourcebook 유럽-01-008. Saved official RSS exposes 13 items with named creators/dates; page is a latest-feed sample, not full archive.",
        feed_paging=False,
    ),
    dict(
        **_row(
            "canadianart_article_lists", "Canadian Art — public section article lists", "Canadian Art", "AMERICAS", "CA",
            "https://canadianart.ca", "https://canadianart.ca/news/", "html",
            "https://canadianart.ca/privacy/",
            "Fetcher reports robots.txt not_found(allow); opened page is a privacy policy, not content-reuse permission. Collector reads only public News/Essays/Reviews list markup and stores explicit title, URL, visible date, and list category; no detail pages or article text are fetched.",
            "List title, canonical URL, visible full date when present, and section category; author and article/ad type are not shown in the list evidence.",
            "Wave2 media sourcebook 미주-01-012. Saved public News, Essays, and Reviews listings and sitemaps; history is partial and detail pages are never fetched.",
            feed_paging=False,
            max_requests=20,
        ),
        section_urls=(
            "https://canadianart.ca/news/",
            "https://canadianart.ca/essays/",
            "https://canadianart.ca/reviews/",
        ),
    ),
    _row(
        "beauxarts_news_sitemap", "Beaux Arts — news sitemap metadata", "Beaux Arts & Cie", "EUROPE", "FR",
        "https://www.beauxarts.com", "https://www.beauxarts.com/sitemap-news.xml", "sitemap",
        "https://www.beauxarts.com/mentions-legales/",
        "robots.txt Content-Signal: search=yes and ai-train=no; the legal notice identifies site materials as protected. The news sitemap is the public search metadata surface; store title/URL/date/keywords only and never use for AI training.",
        "News sitemap title, canonical URL, publication timestamp, modified timestamp, language, and explicit keywords; author and article/ad label are not in this feed.",
        "Wave2 media sourcebook 유럽-01-009. Saved Fetcher probes verified the public news sitemap and general sitemap; the terms page and robots policy were saved in prior24-W2Media.",
        feed_paging=False,
        max_requests=20,
    ),
]

_FEED_SOURCE_IDS = {r["source_id"] for r in SOURCES if r["access_method"] == "rss"}
_TYPE_RULES = (
    ("review", ("review", "reviews", "reseña", "reseñas", "crítica de arte", "評論", "レビュー", "리뷰")),
    ("interview", ("interview", "entrevista", "entrevistas", "インタビュー", "대담", "인터뷰")),
    ("criticism", ("criticism", "essay", "essays", "ensayo", "ensayos", "비평", "批評")),
    ("news", ("news", "noticias", "ニュース", "news article", "뉴스")),
    ("announcement", ("announcement", "announcements", "anuncio", "anuncios", "공고")),
    ("sponsored", ("sponsored", "advertorial", "advertisement", "paid content", "partner content", "광고", "pr")),
)


def _canonical_url(url, base_url):
    if not url:
        return None
    absolute = urllib.parse.urljoin(base_url, url.strip())
    parts = urllib.parse.urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def _same_source(url, base_url):
    source_host = urllib.parse.urlsplit(base_url).hostname or ""
    item_host = urllib.parse.urlsplit(url).hostname or ""
    return item_host.lower().removeprefix("www.") == source_host.lower().removeprefix("www.")


def _feed_language(content):
    match = re.search(rb"<language>\s*([A-Za-z-]{2,10})\s*</language>", content[:5000], re.I)
    return match.group(1).decode("ascii").lower().split("-", 1)[0] if match else None


def _classify(categories, basis="feed_category"):
    for category in categories:
        label = clean_text(category).casefold()
        for article_type, labels in _TYPE_RULES:
            if label in labels:
                return article_type, basis + ":" + category
    return "unknown", None


def _store_article(ctx, *, url, title, author=None, published=None, categories=None, lang=None,
                   article_type=None, type_basis=None, modified=None):
    if not url or not title:
        ctx.count("skipped_incomplete")
        return False
    canonical = _canonical_url(url, ctx.meta["base_url"])
    if not canonical or not _same_source(canonical, ctx.meta["base_url"]):
        ctx.count("skipped_external")
        return False
    categories = [clean_text(c) for c in (categories or []) if clean_text(c)]
    if article_type is None:
        article_type, type_basis = _classify(categories)
    db.upsert_article(
        ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=canonical, title=clean_text(title),
        published_at=published, author_text=clean_text(author) or None,
        publisher=ctx.meta["publisher"], owner_group=ctx.meta["owner_group"],
        article_type=article_type, type_basis=type_basis, lang=lang,
        modified_at=modified, categories="; ".join(categories) if categories else None, excerpt=None,
    )
    ctx.count("parsed")
    return True


def collect(ctx):
    if ctx.source_id == "artmonthly_recent":
        return _collect_artmonthly(ctx)
    if ctx.source_id == "cmagazine_articles":
        return _collect_cmagazine(ctx)
    if ctx.source_id == "beauxarts_news_sitemap":
        return _collect_beauxarts(ctx)
    if ctx.source_id == "canadianart_article_lists":
        return _collect_canadianart(ctx)
    if ctx.source_id in _FEED_SOURCE_IDS:
        return _collect_feed(ctx)
    raise ValueError("unsupported wave2 media source: " + ctx.source_id)


def _collect_feed(ctx):
    paged = bool(ctx.meta.get("feed_paging"))
    max_pages = MAX_INITIAL_FEED_PAGES if ctx.mode == "initial" else (2 if paged else 1)
    oldest_on_page = None
    pages_read = 0
    total_items = 0
    page = 1
    while page <= max_pages:
        try:
            response = ctx.fetch(
                ctx.meta["entry_url"],
                params={"paged": page} if page > 1 else None,
                accept="application/rss+xml, application/xml, text/xml",
            )
        except FetchError as exc:
            if page == 1:
                raise
            ctx.note("RSS paging stopped at page {}: {}".format(page, exc))
            break
        items = parse_feed(response.content)
        pages_read += 1
        total_items += len(items)
        ctx.count("fetched", len(items))
        language = _feed_language(response.content)
        published_dates = []
        for item in items:
            published = item.get("published") or item.get("updated")
            if published:
                published_dates.append(published[:10])
            _store_article(
                ctx,
                url=item.get("link"),
                title=item.get("title"),
                author=item.get("author"),
                published=published,
                categories=item.get("categories"),
                lang=language,
            )
        oldest_on_page = min(published_dates) if published_dates else None
        ctx.con.commit()
        if not items or not paged:
            break
        if ctx.mode == "initial" and oldest_on_page and oldest_on_page <= INITIAL_CUTOFF:
            break
        page += 1
    ctx.note("Official RSS pages read: {}; items observed: {}; oldest date on last page: {}. Feed history is not complete beyond its published pages.".format(
        pages_read, total_items, oldest_on_page or "unknown"))
    ctx.con.commit()


def parse_artmonthly_listing(html, base_url="https://www.artmonthly.co.uk"):
    """Parse titles and links from the site's recent-articles card list, not its synopses."""
    root = soup(html)
    entries = []
    seen = set()
    for card in root.select("#articles .content-item > .grid_1.margin-bottom.alpha"):
        link = card.find("a", href=True)
        details = card.find_next_sibling(
            "div", class_=lambda classes: classes and "grid_4" in classes
        )
        heading = details.find("h3") if details else None
        if not link or not heading:
            continue
        url = _canonical_url(link.get("href"), base_url)
        title = clean_text(heading.get_text(" ", strip=True))
        if not url or not title or not urllib.parse.urlsplit(url).path.startswith("/magazine/site/article/"):
            continue
        if url in seen:
            continue
        seen.add(url)
        entries.append({"title": title, "url": url})
    return entries


def _collect_artmonthly(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], accept="text/html")
    entries = parse_artmonthly_listing(response.text, ctx.meta["base_url"])
    ctx.count("fetched", len(entries))
    for entry in entries:
        _store_article(ctx, url=entry["url"], title=entry["title"], lang="en")
    ctx.note("Single recent-articles index exposes title and URL only; author and publication date are not shown. Article details and synopsis text were not fetched or stored.")
    ctx.con.commit()


def parse_cmagazine_listing(html, base_url="https://cmagazine.com"):
    """Extract article cards from the homepage, never following their detail links."""
    root = soup(html)
    entries = []
    seen = set()
    for link in root.select('a[href*="/articles/"]'):
        heading = link.find("h3")
        if not heading:
            continue
        url = _canonical_url(link.get("href"), base_url)
        title = clean_text(heading.get_text(" ", strip=True))
        if not url or not title or url in seen:
            continue
        card = None
        category = None
        for ancestor in link.parents:
            if ancestor.name != "div":
                continue
            article_links = ancestor.select('a[href*="/articles/"]')
            article_urls = {
                _canonical_url(candidate.get("href"), base_url)
                for candidate in article_links
            }
            article_urls.discard(None)
            if not ancestor.find("h3") or article_urls != {url}:
                continue
            if card is None:
                card = ancestor
            for label in ancestor.find_all("p"):
                value = clean_text(label.get_text(" ", strip=True))
                if value.casefold() in {"review", "feature", "artist project", "interview", "essay", "sponsored"}:
                    card = ancestor
                    category = value
                    break
            if category:
                break
        if card is None:
            continue
        byline = heading.find_next_sibling("div")
        author = None
        if byline:
            spans = [clean_text(span.get_text(" ", strip=True)) for span in byline.find_all("span")]
            spans = [span for span in spans if span]
            if len(spans) > 1 and spans[0].casefold() == "by":
                author = " ".join(spans[1:])
        categories = [category] if category else []
        article_type, type_basis = _classify(categories)
        if category and category.casefold() == "sponsored":
            article_type, type_basis = "sponsored", "homepage_card_label:Sponsored"
        entries.append({
            "title": title,
            "url": url,
            "author": author,
            "categories": categories,
            "article_type": article_type,
            "type_basis": type_basis,
        })
        seen.add(url)
    return entries


def _collect_cmagazine(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], accept="text/html")
    entries = parse_cmagazine_listing(response.text, ctx.meta["base_url"])
    ctx.count("fetched", len(entries))
    for entry in entries:
        _store_article(
            ctx, url=entry["url"], title=entry["title"], author=entry["author"],
            categories=entry["categories"], lang="en", article_type=entry["article_type"],
            type_basis=entry["type_basis"],
        )
    ctx.note("Homepage article cards only; author/category are stored only when explicitly displayed. No publication date is shown; no issue API, article details, or body text fetched.")
    ctx.con.commit()


def _xml_root(content):
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    return etree.fromstring(content, parser=parser)


def parse_beauxarts_news_sitemap(content):
    """Read explicit News sitemap fields; ignore image URLs and all article content."""
    root = _xml_root(content)
    ns = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "n": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    items = []
    for node in root.findall("s:url", ns):
        loc = clean_text(node.findtext("s:loc", namespaces=ns))
        news = node.find("n:news", ns)
        if not loc or news is None:
            continue
        publication = news.find("n:publication", ns)
        language = publication.findtext("n:language", namespaces=ns) if publication is not None else None
        title = clean_text(news.findtext("n:title", namespaces=ns))
        published = clean_text(news.findtext("n:publication_date", namespaces=ns))
        keywords = clean_text(news.findtext("n:keywords", namespaces=ns))
        modified = clean_text(node.findtext("s:lastmod", namespaces=ns))
        items.append({
            "url": loc,
            "title": title,
            "published": published or None,
            "modified": modified or None,
            "lang": clean_text(language).lower() or None,
            "categories": [part.strip() for part in keywords.split(",") if part.strip()],
        })
    return items


def _collect_beauxarts(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], accept="application/xml, text/xml")
    items = parse_beauxarts_news_sitemap(response.content)
    ctx.count("fetched", len(items))
    for item in items:
        _store_article(
            ctx, url=item["url"], title=item["title"], published=item["published"],
            modified=item["modified"], categories=item["categories"], lang=item["lang"],
        )
    ctx.note("Public News sitemap only; it exposes a short recent-news window, not the full archive. Search is permitted by the saved content signal; AI training is expressly disallowed. No article pages, images, or bodies fetched.")
    ctx.con.commit()


def parse_canadianart_listing(html, section, base_url="https://canadianart.ca"):
    """Extract only title, URL, and visible dates from public section-list cards."""
    root = soup(html)
    entries = []
    seen = set()
    for card in root.select(".copy-container"):
        link = card.select_one("h3 a[href]")
        if not link:
            continue
        url = _canonical_url(link.get("href"), base_url)
        title = clean_text(link.get_text(" ", strip=True))
        if not url or not title or not _same_source(url, base_url) or url in seen:
            continue
        date_node = card.select_one(".article-meta p")
        published = None
        if date_node:
            date_text = clean_text(date_node.get_text(" ", strip=True))
            try:
                published = datetime.strptime(date_text, "%B %d, %Y").date().isoformat()
            except ValueError:
                published = None
        categories = [section]
        article_type, type_basis = _classify(categories, basis="public_list_section")
        entries.append({
            "title": title,
            "url": url,
            "published": published,
            "categories": categories,
            "article_type": article_type,
            "type_basis": type_basis,
        })
        seen.add(url)
    return entries


def _collect_canadianart(ctx):
    total = 0
    for section_url in ctx.meta["section_urls"]:
        section = urllib.parse.urlsplit(section_url).path.strip("/").split("/")[0]
        try:
            response = ctx.fetch(section_url, accept="text/html")
        except FetchError as exc:
            if total == 0:
                raise
            ctx.note("Section list skipped {}: {}".format(section_url, exc))
            continue
        entries = parse_canadianart_listing(response.text, section, ctx.meta["base_url"])
        total += len(entries)
        ctx.count("fetched", len(entries))
        for entry in entries:
            _store_article(
                ctx, url=entry["url"], title=entry["title"], published=entry["published"],
                categories=entry["categories"], lang="en", article_type=entry["article_type"],
                type_basis=entry["type_basis"],
            )
        ctx.con.commit()
    ctx.note("Read the public News, Essays, and Reviews section lists only; {} entries observed. These first exposed lists are partial; no article detail pages, text, authors, or images were fetched/stored.".format(total))
    ctx.con.commit()


