"""Korean art news METADATA from publishers' own public RSS feeds (Blueprint D32, KR edition).

The original v2v project (아트랜드v2v_20261020.zip) gathered Korean art news through the Naver search API (key +
non-commercial terms) and Google News RSS; its 14k Korean items up to 2026-10-19 are already imported as
`legacy_v2v_artnews`. Here the newest items are taken directly from publishers that expose RSS and whose robots.txt
allows the feed (checked 2026-10-29). Google News RSS is not used: news.google.com robots.txt disallows /rss/search.

metadata_only: title, canonical URL, author, published_at, categories. No bodies, excerpts or images.
General newspapers publish one culture feed (film, music, books, ...); only items whose title or category carries an
art keyword are kept, and the matched keyword is recorded as `type_basis`. Art-specialist outlets are kept whole.
RSS exposes the latest items only, so history accumulates from repeated incremental runs.
"""
from __future__ import annotations

import re
import urllib.parse

from .gl_media import _canon, _feed_lang, _known
from .. import db
from ._common import parse_feed

PARSER_VERSION = "kr_news-1"

ART_KEYWORDS = re.compile(
    r"미술|전시|갤러리|화랑|화가|조각|회화|판화|드로잉|설치미술|미디어아트|사진전|개인전|단체전|기획전|초대전|회고전|"
    r"비엔날레|트리엔날레|아트페어|키아프|프리즈|아트부산|아트\s?바젤|미술관|박물관|큐레이터|레지던시|경매|옥션|소더비|크리스티|"
    r"작가상|올해의 작가|팝아트|작가展|展\b|《|아트센터|아트스페이스|공예|도예|서예|단색화|민화|문화재|국가유산")

_TERMS = ("terms not reviewed for reuse; only the publisher's official RSS feed is polled (robots allows it) and only "
          "title/link/date/author/category are kept for internal discovery; no body, excerpt or image")


def _row(source_id, name, publisher, entry_url, base_url, terms_url=None, art_filter=True, max_requests=6):
    return dict(source_id=source_id, blueprint_data_id="D32", blueprint_org_id=None, name=name, owner_group=publisher,
                source_kind="media", region_scope="KR", country_codes="KR", access_method="rss", base_url=base_url,
                entry_url=entry_url, terms_url=terms_url, text_storage_policy="metadata_only", priority="P1",
                st_official_doc="n/a(official RSS feed)", st_collection_terms=_TERMS,
                st_image_terms="images not collected", max_requests=max_requests, publisher=publisher,
                art_filter=art_filter,
                notes=("culture-section feed filtered by art keywords" if art_filter else "art-specialist outlet; all items kept"))


SOURCES = [
    _row("kr_yna_culture_rss", "연합뉴스 문화 — RSS", "연합뉴스", "https://www.yna.co.kr/rss/culture.xml", "https://www.yna.co.kr",
         "https://www.yna.co.kr/rss/index"),
    _row("kr_newsis_culture_rss", "뉴시스 문화 — RSS", "뉴시스", "https://newsis.com/RSS/culture.xml", "https://newsis.com"),
    _row("kr_khan_culture_rss", "경향신문 문화 — RSS", "경향신문", "https://www.khan.co.kr/rss/rssdata/culture_news.xml",
         "https://www.khan.co.kr"),
    _row("kr_donga_culture_rss", "동아일보 문화 — RSS", "동아일보", "https://rss.donga.com/culture.xml", "https://www.donga.com"),
    _row("kr_chosun_culture_rss", "조선일보 문화·라이프 — RSS", "조선일보",
         "https://www.chosun.com/arc/outboundfeeds/rss/category/culture-life/?outputType=xml", "https://www.chosun.com"),
    _row("kr_segye_culture_rss", "세계일보 문화 — RSS", "세계일보", "https://www.segye.com/Articles/RSSList/segye_culture.xml",
         "https://www.segye.com"),
    _row("kr_sctoday_rss", "서울문화투데이 — RSS", "서울문화투데이", "https://www.sctoday.co.kr/rss/allArticle.xml",
         "https://www.sctoday.co.kr"),
    _row("kr_artkoreatv_rss", "아트코리아방송 — RSS", "아트코리아방송", "https://www.artkoreatv.com/rss/allArticle.xml",
         "https://www.artkoreatv.com", art_filter=False),
    _row("kr_dart_rss", "D-ART 디아트 — RSS", "D-ART", "https://www.d-art.co.kr/rss/allArticle.xml", "https://www.d-art.co.kr",
         art_filter=False),
]


# Words that also name phone galleries, flower shows, game museums or car/real-estate auctions: they admit an item
# only together with another art word (observed 2026-10-29: '가을애 국화전시회', '대한민국 게임박물관').
AMBIGUOUS = {"갤러리", "전시", "박물관", "경매", "옥션"}


def art_match(title: str, categories) -> str | None:
    """Return the art keyword(s) that admit an item, or None."""
    found = []
    for text in [title or ""] + [c or "" for c in categories]:
        for m in ART_KEYWORDS.finditer(text):
            word = m.group(0)
            if word not in AMBIGUOUS:
                return word
            if word not in found:
                found.append(word)
    return "+".join(found) if len(found) >= 2 else None


def absolute_link(url, base_url):
    """Some publisher feeds emit site-relative links, one with a literal 'null' host (Sankei, observed 2026-10-29:
    'null/article/20261029-.../'); resolve them against the outlet's base URL."""
    if not url or url.startswith(("http://", "https://")):
        return url
    if url.startswith("null/"):
        url = url[4:]
    return urllib.parse.urljoin((base_url or "").rstrip("/") + "/", url) if base_url else None


def collect(ctx):
    return collect_feed(ctx, art_match, default_lang="ko")


def collect_feed(ctx, matcher, default_lang):
    """One official feed page; general feeds keep only items `matcher(title, categories)` admits."""
    r = ctx.fetch(ctx.meta["entry_url"], accept="application/rss+xml, application/xml")
    items = parse_feed(r.content)
    lang = (ctx.meta.get("lang") or _feed_lang(r.content) or default_lang).split("-")[0]
    ctx.count("fetched", len(items))
    oldest = None
    for it in items:
        url = absolute_link(it["link"] or it["guid"], ctx.meta.get("base_url"))
        categories = [c for c in it["categories"] if c]
        if not url or not it["title"]:
            ctx.count("skipped_incomplete")
            continue
        if ctx.meta.get("art_filter"):
            keyword = matcher(it["title"], categories)
            if keyword is None:
                ctx.count("skipped_not_art")
                continue
            basis = f"art_keyword:{keyword}"
        else:
            basis = "art_specialist_outlet"
        if _known(ctx, url):
            ctx.count("already_known")
        db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=_canon(url), title=it["title"],
                          published_at=it["published"] or it["updated"], author_text=it["author"] or None,
                          publisher=ctx.meta["publisher"], owner_group=ctx.meta["owner_group"], article_type="news",
                          type_basis=basis, lang=lang, modified_at=it["updated"],
                          categories="; ".join(categories) if categories else None, excerpt=None)
        ctx.count("parsed")
        published = it["published"] or it["updated"]
        if published and (oldest is None or published < oldest):
            oldest = published
    ctx.con.commit()
    ctx.note(f"feed exposes latest {len(items)} items only (no paging); oldest kept item {oldest}")
