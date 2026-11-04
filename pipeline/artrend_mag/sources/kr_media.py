"""Korean art media — article metadata only (Blueprint D36).

월간미술 (monthlyart.com): the WordPress feed `/feed/` stopped in 2020-07 and the kboard RSS
(`/wp-content/plugins/kboard/rss.php`) holds 4 items from 2017, so neither reflects current publishing. Current
articles are the `portfolio-item` posts on the home page, each an <article> with schema.org microdata
(`headline`, `datePublished`). Only title / URL / published date / byline are kept (metadata_only, no body).
"""
from __future__ import annotations

import re
import urllib.parse

from .. import db
from ._common import clean_text, soup

PARSER_VERSION = "kr_media-1"
MA = "https://monthlyart.com"

SOURCES = [dict(
    source_id="monthlyart_web", blueprint_data_id="D36", blueprint_org_id=None, name="월간미술 Monthly Art — latest articles",
    owner_group="월간미술", publisher="월간미술", source_kind="media", region_scope="KR", country_codes="KR",
    access_method="html(microdata)", base_url=MA, entry_url=f"{MA}/", terms_url=None,
    text_storage_policy="metadata_only", priority="P1", max_requests=10,
    st_official_doc="n/a(html; /feed/ stale since 2020-07, kboard rss.php stale since 2017)",
    st_collection_terms="terms page not located (footer links: 독자 불만 처리, 언론윤리강령, 청소년 보호 정책); robots.txt Allow: /",
    st_image_terms="images not collected (metadata_only)",
)]

_BYLINE = re.compile(r"(기자|편집장|부편집장|평론가|큐레이터|디렉터|작가|교수|에디터)(\s|$)")


def collect(ctx):
    r = ctx.fetch(f"{MA}/")
    arts = soup(r.text).select("article")
    ctx.count("fetched", len(arts))
    ctx.note("monthlyart.com home page exposes the ~24 latest portfolio-item articles; no paginated archive used")
    for a in arts:
        link = a.select_one("a[href*='/portfolio-item/']")
        head = a.select_one("[itemprop=headline]") or a.select_one(".entry-title")
        if link is None or head is None:
            ctx.count("skipped_incomplete")
            continue
        url = urllib.parse.urljoin(MA, link["href"])
        title = clean_text(head.get_text(" "))
        # the <time itemprop=datePublished datetime=...> belongs to the post; a later <span itemprop=datePublished>
        # in the same <article> carries the page's own date and is ignored
        pub = a.select_one("time[itemprop=datePublished][datetime]")
        published = pub["datetime"] if pub is not None else None
        author = None
        for p in a.select("p.port-num_view, p.port-cate_view, p.port-cont_view"):
            t = clean_text(p.get_text(" "))
            if t and len(t) <= 40 and _BYLINE.search(t):
                author = t
                break
        if not title:
            continue
        db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=url, title=title,
                          published_at=published, author_text=author, publisher=ctx.meta["publisher"],
                          owner_group=ctx.meta["owner_group"], article_type="unknown", type_basis=None, lang="ko",
                          categories=None, excerpt=None)
        ctx.count("parsed")
    ctx.con.commit()
