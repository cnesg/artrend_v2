"""Bounded European sourcebook additions; media feeds are metadata-only."""
from __future__ import annotations

import urllib.parse

from .. import db
from ._common import clean_text, parse_feed

PARSER_VERSION = "sourcebook_eu-1"

FLASH_ART_FEED = "https://flash---art.com/feed/"

SOURCES = [
    dict(
        source_id="flash_art_rss",
        blueprint_data_id=None,
        blueprint_org_id=None,
        name="Flash Art — official RSS metadata",
        owner_group="Flash Art",
        source_kind="media",
        region_scope="EUROPE",
        country_codes="IT",
        access_method="rss",
        base_url="https://flash---art.com",
        entry_url=FLASH_ART_FEED,
        terms_url="https://flash---art.com/terms-and-conditions/",
        text_storage_policy="metadata_only",
        priority="P1",
        st_official_doc="n/a(official RSS feed)",
        st_collection_terms=(
            "Official subscription terms reviewed 2026-10-28; they govern print subscriptions and do not state a "
            "site-wide automated-extraction permission or prohibition. RSS metadata only; no article body or excerpt stored."
        ),
        st_image_terms="Images not collected; feed exposes no reuse licence; rights remain with respective holders.",
        max_requests=4,
        publisher="Flash Art",
    ),
]


def collect(ctx):
    if ctx.source_id != "flash_art_rss":
        raise ValueError(ctx.source_id)
    response = ctx.fetch(FLASH_ART_FEED, accept="application/rss+xml, application/xml")
    items = _metadata_items(response.content)
    ctx.count("fetched", len(items))
    dates = []
    for item in items:
        if not item["url"] or not item["title"]:
            ctx.count("skipped_incomplete")
            continue
        article_type, type_basis = _article_type(item["categories"])
        db.upsert_article(
            ctx.con,
            ctx.stats,
            source_id=ctx.source_id,
            canonical_url=item["url"],
            title=item["title"],
            published_at=item["published"],
            author_text=item["author"],
            publisher=ctx.meta["publisher"],
            owner_group=ctx.meta["owner_group"],
            article_type=article_type,
            type_basis=type_basis,
            lang=None,
            modified_at=item["updated"],
            categories="; ".join(item["categories"]) or None,
            excerpt=None,
        )
        ctx.count("parsed")
        if item["published"]:
            dates.append(item["published"])
    oldest = min(dates) if dates else "unknown"
    newest = max(dates) if dates else "unknown"
    ctx.note(
        f"Official RSS page exposed {len(items)} items; published_at range {oldest}–{newest}. "
        "The rolling feed has no date search or verified archive pagination; repeated runs only accumulate "
        "items while they remain in the feed. Feed author is stored verbatim (currently generic publisher label); "
        "artist/exhibition IDs, update dates, and paid-content status are not inferred."
    )
    ctx.con.commit()


def _metadata_items(content: bytes) -> list[dict]:
    """Keep only RSS metadata; parse_feed summaries are deliberately discarded."""
    items = []
    for item in parse_feed(content):
        raw_url = item["link"] or item["guid"]
        url = _canonical_url(raw_url)
        items.append(
            {
                "title": clean_text(item["title"]),
                "url": url,
                "published": item["published"],
                "updated": item["updated"],
                "author": clean_text(item["author"]) or None,
                "categories": [clean_text(category) for category in item["categories"] if clean_text(category)],
            }
        )
    return items


def _canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"flash---art.com", "www.flash---art.com"}:
        return None
    query = [(key, val) for key, val in urllib.parse.parse_qsl(parsed.query) if not key.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


def _article_type(categories: list[str]) -> tuple[str, str | None]:
    types = {
        "review": "review",
        "reviews": "review",
        "interview": "interview",
        "interviews": "interview",
        "news": "news",
        "announcement": "announcement",
        "announcements": "announcement",
        "sponsored": "sponsored",
        "paid content": "sponsored",
    }
    for category in categories:
        article_type = types.get(category.casefold())
        if article_type:
            return article_type, f"official RSS category: {category}"
    return "unknown", None
