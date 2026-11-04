"""Americas sourcebook additions: Artadia awardees, BOMB interview metadata, and Jack Shainman artists."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from urllib.parse import urljoin

from .. import db
from ._common import clean_text, soup

PARSER_VERSION = "sourcebook-am-1"
ARTADIA = "https://artadia.org"
BOMB = "https://bombmagazine.org"
JSG = "https://jackshainman.com"
HISTORY_FLOOR = "2025-04-01"

SOURCES = [
    dict(source_id="artadia_awards", blueprint_data_id=None, blueprint_org_id=None,
         name="Artadia — official awardee archive", owner_group="Artadia", source_kind="foundation",
         region_scope="AMERICAS", country_codes="US", access_method="html",
         base_url=ARTADIA, entry_url=f"{ARTADIA}/artist/", terms_url="http://artadia.org/terms-privacy/",
         text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(html; All Awardees directory with official award-year and award-city tags)",
         st_collection_terms="Terms & Privacy page opened (last updated 2022); page content is a privacy policy, no automated-access or content-reuse clause located; collect only awardee names and year/city tags",
         st_image_terms="No images are downloaded or stored; no open image licence stated",
         max_requests=30),
    dict(source_id="bomb_interviews", blueprint_data_id=None, blueprint_org_id=None,
         name="BOMB Magazine — interview listing metadata", owner_group="BOMB Magazine",
         source_kind="media", region_scope="AMERICAS", country_codes="US", access_method="html",
         base_url=BOMB, entry_url=f"{BOMB}/interview/", terms_url=None,
         text_storage_policy="metadata_only", priority="P1",
         st_official_doc="n/a(html; official Interviews listing)",
         st_collection_terms="No content-use terms located; linked privacy policy addresses personal data, not content reuse; listing metadata only, no article pages/bodies or excerpts collected",
         st_image_terms="No images are downloaded or stored; no open image licence stated",
         max_requests=40),
    dict(source_id="jackshainman_artists", blueprint_data_id=None, blueprint_org_id=None,
         name="Jack Shainman Gallery — Artists roster", owner_group="Jack Shainman Gallery",
         source_kind="gallery", region_scope="AMERICAS", country_codes="US", access_method="html",
         base_url=JSG, entry_url=f"{JSG}/artists", terms_url=None,
         text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(html; official Artists directory)",
         st_collection_terms="No content-use or automated-access terms located; linked privacy policy addresses personal data, not content reuse; artist directory metadata only",
         st_image_terms="No images are downloaded or stored; no open image licence stated",
         max_requests=20),
]


def collect(ctx):
    handlers = {
        "artadia_awards": _collect_artadia,
        "bomb_interviews": _collect_bomb,
        "jackshainman_artists": _collect_jackshainman,
    }
    handler = handlers.get(ctx.source_id)
    if handler is None:
        raise ValueError(f"unsupported source id: {ctx.source_id}")
    handler(ctx)


def _artadia_awardees(html: str, page_url: str) -> list[dict]:
    """Parse only the official All Awardees cards and their explicit year/city taxonomies."""
    page = soup(html)
    found = []
    seen = set()
    for card in page.select("li.grid-item"):
        artist_link = card.select_one('a[href*="/artist/"]')
        if artist_link is None:
            continue
        artist_url = urljoin(page_url, artist_link.get("href", ""))
        path = urllib.parse.urlsplit(artist_url).path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) != 2 or parts[0] != "artist":
            continue
        name_node = artist_link.select_one(".font-medium")
        name = clean_text(name_node.get_text(" ") if name_node else artist_link.get_text(" "))
        year = city = year_url = city_url = city_slug = None
        for tag in card.select('a[rel~="tag"][href]'):
            tag_url = urljoin(page_url, tag["href"])
            tag_path = urllib.parse.urlsplit(tag_url).path.rstrip("/")
            match = re.fullmatch(r"/award-year/(20\d{2}|19\d{2})", tag_path)
            if match:
                year, year_url = match.group(1), tag_url
                continue
            match = re.fullmatch(r"/award-city/([^/]+)", tag_path)
            if match:
                city, city_url, city_slug = clean_text(tag.get_text(" ")), tag_url, match.group(1)
        key = (parts[1], year, city_slug)
        if not name or not year or not city or not city_slug or key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "artist_slug": parts[1], "artist_url": artist_url,
                      "year": year, "year_url": year_url, "city": city, "city_slug": city_slug,
                      "city_url": city_url})
    return found


def _artadia_next(html: str, page_url: str) -> str | None:
    page = soup(html)
    for anchor in page.select(".pagination a[href], nav.pagination a[href], a[rel~='next']"):
        rel = anchor.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()
        label = clean_text(anchor.get_text(" ")).casefold()
        if "next" in [item.casefold() for item in rel] or label in {"next", "next page", "older"}:
            url = urljoin(page_url, anchor["href"])
            if urllib.parse.urlsplit(url).netloc == "artadia.org":
                return url
    return None


def _org(ctx, entity_type: str, name: str, key: str, url: str) -> str:
    return db.ensure_entity(ctx.con, entity_type=entity_type, name=name,
                            namespace=f"src:{ctx.source_id}", id_value=key,
                            source_id=ctx.source_id, official_url=url)


def _award_event(ctx, organizer: str, response, card: dict, artists: list[dict], seen_events: set[str]) -> None:
    year = card["year"]
    city = card["city"]
    key = f"{card['city_slug']}:{year}"
    excerpt = f"Artadia All Awardees: {city}, {year}"
    evidence = ctx.evidence(response, locator=f"li.grid-item award-city={card['city_slug']} award-year={year}",
                            excerpt=excerpt)
    event_url = card["year_url"] or card["city_url"]
    event_id = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="award",
        title=f"Artadia Award — {city} {year}", title_lang="en", organizer_entity_id=organizer,
        start_date=year, start_precision="year", date_text=year, url=event_url,
        description_excerpt="Official award-year and award-city tags identify the award cohort; ceremony venue is not stated.",
        evidence_id=evidence, parser_version=PARSER_VERSION)
    if key not in seen_events:
        ctx.count("parsed")
        seen_events.add(key)
    db.add_review(ctx.con, "region", "events", event_id, "venue country unknown",
                  detail="The award-city taxonomy identifies the cohort, not the ceremony venue.")
    for artist in artists:
        entity_type = "group" if re.search(r"\b(collective|duo)\b", artist["name"], re.I) else "person"
        entity = _org(ctx, entity_type, artist["name"], artist["artist_slug"], artist["artist_url"])
        db.add_participant(ctx.con, event_id, entity, "winner", artist["name"], evidence,
                           "list_markup", "high")
        ctx.count("awardees")


def _collect_artadia(ctx):
    organizer = _org(ctx, "foundation", "Artadia", "artadia", ARTADIA + "/")
    page_limit = 25 if ctx.mode == "initial" else 1
    next_url = ctx.meta["entry_url"]
    seen_urls = set()
    seen_events = set()
    oldest = None
    pages = 0
    while next_url and pages < page_limit and next_url not in seen_urls:
        seen_urls.add(next_url)
        response = ctx.fetch(next_url, accept="text/html")
        pages += 1
        cards = _artadia_awardees(response.text, response.url)
        ctx.count("fetched", len(cards))
        grouped = {}
        page_newest = None
        for card in cards:
            oldest = min(oldest, card["year"]) if oldest else card["year"]
            page_newest = max(page_newest, card["year"]) if page_newest else card["year"]
            grouped.setdefault((card["city_slug"], card["year"]), []).append(card)
        for group in grouped.values():
            _award_event(ctx, organizer, response, group[0], group, seen_events)
        ctx.con.commit()
        following = _artadia_next(response.text, response.url)
        if ctx.mode == "initial" and page_newest and page_newest < HISTORY_FLOOR[:4]:
            next_url = None
            break
        next_url = following
    ctx.note(f"Artadia All Awardees: {pages} listing page(s), oldest explicit award year {oldest or 'unknown'}; "
             f"{len(seen_events)} city/year cohorts; award-city is not treated as a ceremony venue")
    if ctx.mode == "incremental":
        ctx.note("Incremental mode reads only the first All Awardees listing page; no artist detail pages or images fetched")
    elif pages >= page_limit and next_url:
        ctx.note(f"Initial history stopped at the {page_limit}-page request budget")


def _bomb_articles(html: str, page_url: str) -> list[dict]:
    """Parse interview listing titles/URLs/date-in-URL; never read detail-page bodies or listing excerpts."""
    page = soup(html)
    found = []
    seen = set()
    for heading in page.select("h3"):
        anchor = heading.find("a", href=True)
        if anchor is None:
            continue
        url = urljoin(page_url, anchor["href"])
        parts = urllib.parse.urlsplit(url)
        if parts.netloc.lower() not in {"bombmagazine.org", "www.bombmagazine.org"}:
            continue
        match = re.match(r"^/articles/(20\d{2})/(\d{2})/(\d{2})/[^/]+/?$", parts.path)
        if not match:
            continue
        try:
            published = dt.date(*(int(value) for value in match.groups())).isoformat()
        except ValueError:
            continue
        title = clean_text(anchor.get_text(" "))
        canonical = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        if not title or canonical in seen:
            continue
        seen.add(canonical)
        byline = re.match(r"^.+\s+by\s+(.+)$", title, re.I)
        found.append({"title": title, "url": canonical, "published_at": published,
                      "author": clean_text(byline.group(1)) if byline else None,
                      "article_type": "interview", "type_basis": "official_interview_listing"})
    return found


def _listing_next(html: str, page_url: str) -> str | None:
    page = soup(html)
    for anchor in page.select("a[rel~='next'], .pagination a[href], nav a[href]"):
        rel = anchor.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()
        label = clean_text(anchor.get_text(" ")).casefold()
        if "next" not in [item.casefold() for item in rel] and label not in {"next", "next page", "older", "older posts"}:
            continue
        url = urljoin(page_url, anchor["href"])
        if urllib.parse.urlsplit(url).netloc.lower() in {"bombmagazine.org", "www.bombmagazine.org"}:
            return url
    return None


def _collect_bomb(ctx):
    since = dt.date.fromisoformat(HISTORY_FLOOR)
    page_limit = 35 if ctx.mode == "initial" else 1
    next_url = ctx.meta["entry_url"]
    seen_urls = set()
    oldest = None
    pages = 0
    while next_url and pages < page_limit and next_url not in seen_urls:
        seen_urls.add(next_url)
        response = ctx.fetch(next_url, accept="text/html")
        pages += 1
        articles = _bomb_articles(response.text, response.url)
        ctx.count("fetched", len(articles))
        for article in articles:
            published = dt.date.fromisoformat(article["published_at"])
            oldest = min(oldest, published) if oldest else published
            if published < since:
                continue
            db.upsert_article(
                ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=article["url"],
                title=article["title"], published_at=article["published_at"], author_text=article["author"],
                publisher="BOMB Magazine", owner_group="BOMB Magazine", article_type=article["article_type"],
                type_basis=article["type_basis"], lang="en", categories="interview", excerpt=None)
            ctx.count("parsed")
        ctx.con.commit()
        following = _listing_next(response.text, response.url)
        if ctx.mode == "initial" and oldest and oldest < since:
            next_url = None
            break
        next_url = following
    ctx.note(f"BOMB Interviews listing only: {pages} page(s); oldest observed URL date "
             f"{oldest.isoformat() if oldest else 'unknown'}; titles, URL, by-title author pattern and date-in-URL only")
    ctx.note("No article detail pages, article bodies, or excerpts were fetched or stored")
    if ctx.mode == "incremental":
        ctx.note("Incremental mode reads only the first Interviews listing page")
    elif pages >= page_limit and next_url:
        ctx.note(f"Initial history stopped at the {page_limit}-page request budget")


def _jack_artist_roster(html: str, page_url: str) -> list[dict]:
    page = soup(html)
    found = []
    seen = set()
    for anchor in page.select(".artist_link_container a.artist_link[href]"):
        url = urljoin(page_url, anchor["href"])
        parts = urllib.parse.urlsplit(url)
        match = re.fullmatch(r"/artists/([^/]+)/?", parts.path)
        if parts.netloc.lower() not in {"jackshainman.com", "www.jackshainman.com"} or not match:
            continue
        slug = urllib.parse.unquote(match.group(1))
        name_node = anchor.select_one(".artist_name")
        name = clean_text(name_node.get_text(" ") if name_node else anchor.get_text(" "))
        if not name or slug in seen:
            continue
        seen.add(slug)
        found.append({"name": name, "slug": slug, "url": url})
    return found


def _collect_jackshainman(ctx):
    response = ctx.fetch(ctx.meta["entry_url"], accept="text/html")
    artists = _jack_artist_roster(response.text, response.url)
    ctx.count("fetched", len(artists))
    evidence = ctx.evidence(response, locator="main .artist_link_container a.artist_link",
                            excerpt=f"Official Artists roster: {len(artists)} listed artists")
    gallery = _org(ctx, "gallery", "Jack Shainman Gallery", "jack_shainman", JSG + "/")
    for artist in artists:
        entity_type = "group" if re.search(r"\b(collective|duo)\b", artist["name"], re.I) else "person"
        entity = _org(ctx, entity_type, artist["name"], artist["slug"], artist["url"])
        rel_id = db.sid("rel", gallery, entity, "listed_artist", ctx.source_id)
        known = ctx.con.execute("SELECT 1 FROM relationships WHERE rel_id=?", (rel_id,)).fetchone()
        ctx.count("parsed")
        ctx.count("unchanged" if known else "inserted")
        db.upsert_relationship(ctx.con, subject_entity_id=gallery, object_entity_id=entity,
                               rel_type="listed_artist", source_id=ctx.source_id,
                               evidence_id=evidence, status="source_asserted")
        ctx.count("roster")
    ctx.con.commit()
    ctx.note(f"Jack Shainman: {len(artists)} names from the official /artists directory; relationship is listed_artist, "
             "not represents; no artist detail pages or images fetched")
