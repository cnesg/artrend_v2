"""Korean art news METADATA from the official Naver News Search API (Blueprint D32, KR edition).

This is how the original v2v project (아트랜드v2v_20261020.zip, crawlers/naver_news.py) obtained articles from
outlets whose own sites refuse crawlers (매일경제, 한국경제, 헤럴드, 서울신문, ...): the API returns each outlet's
article title, original link, a short snippet and the publication time. Nothing is fetched from the outlets.

Queries
- `v2v_entity_aliases.json` is a verbatim copy of the original pipeline/entity_aliases.json (sha256 555bf562…8f04):
  its 43 `naver_queries` (auction houses + art market) are kept whole, as the original did; its `naver_deep_queries`
  run only in `initial` mode (backfill).
- BROAD_QUERIES widen the scope to all domestic art news (museums, galleries, exhibitions, artists, criticism).
Relevance (see `relevance`): search hits are not on-topic by themselves (observed 2026-10-29: '경매 최고가' returns real-estate and golf
stories). An entity query keeps an item only under the original's own 'about' rule (entity_aliases.json `_doc`): an
alias in title/snippet (Latin: word boundary, case-insensitive; Korean/Japanese: substring), one of its
required_keywords when it has any, and none of its exclude_keywords. Specs without aliases (`_market`, `_artists`, …)
use their required_keywords, else the art-keyword rule; broad queries use the art-keyword rule.

Keys: NAVER_CLIENT_ID / NAVER_CLIENT_SECRET from the environment or the project `.env` (never stored in the DB,
URLs or raw files). Without keys the source is recorded as blocked_credentials.
Terms: Naver Developers terms; the original project recorded "비상업적 활용". The account owner decided to use their
own key (2026-10-29); editorial reuse still needs a terms review. Snippets are kept <= 300 characters.
Pacing: the API allows 25,000 calls/day; one query reads at most 1,000 newest items (10 pages of 100).
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from .. import db
from ..config import WORK_ROOT
from ..http import Blocked
from .gl_media import _canon
from .kr_news import AMBIGUOUS, ART_KEYWORDS, art_match

PARSER_VERSION = "kr_naver_news-1"
API_URL = "https://openapi.naver.com/v1/search/news.json"
PAGE_SIZE = 100
MAX_START = 1000
# Same window as the original BACKFILL_START, in both modes (sort=sim also returns decades-old items).
SINCE = "2025-10-01"
ALIASES = Path(__file__).with_name("v2v_entity_aliases.json")
BROAD_QUERIES = (
    "미술 전시", "미술관 전시", "갤러리 개인전", "개인전 작가", "단체전 미술", "현대미술", "미술관", "국립현대미술관",
    "서울시립미술관", "리움미술관", "아트선재센터", "비엔날레", "광주비엔날레", "부산비엔날레", "미술 작가", "화가 전시",
    "조각가", "사진전", "미디어아트 전시", "레지던시 작가", "미술상 수상", "올해의 작가상", "미술 평론", "큐레이터",
    "미술품", "화랑", "프리즈 서울", "키아프 서울", "아트부산", "단색화",
)
_TAG = re.compile(r"<[^>]+>")


def _row():
    return dict(source_id="kr_naver_news_api", blueprint_data_id="D32", blueprint_org_id=None,
                name="Naver 뉴스 검색 API — 국내 미술 기사", owner_group="NAVER", source_kind="media", region_scope="KR",
                country_codes="KR", access_method="api", base_url="https://openapi.naver.com", entry_url=API_URL,
                terms_url="https://developers.naver.com/products/terms/", api_policy_url="https://developers.naver.com/docs/serviceapi/search/news/news.md",
                text_storage_policy="metadata_only", priority="P1", st_official_doc="https://developers.naver.com/docs/serviceapi/search/news/news.md",
                st_collection_terms="official API with the account owner's key; Naver Developers terms (original project noted "
                                    "non-commercial use) need review before editorial reuse; title/link/date/<=300-char snippet only",
                st_image_terms="images not collected", max_requests=2500, min_interval=0.25, publisher=None,
                notes="original v2v channel for Korean art news; queries copied from v2v pipeline/entity_aliases.json + broad art queries")


SOURCES = [_row()]


def load_keys(env=os.environ, dotenv_path: Path = WORK_ROOT / ".env"):
    cid, secret = env.get("NAVER_CLIENT_ID"), env.get("NAVER_CLIENT_SECRET")
    if (not cid or not secret) and dotenv_path.exists():
        values = {}
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
        cid, secret = cid or values.get("NAVER_CLIENT_ID"), secret or values.get("NAVER_CLIENT_SECRET")
    return (cid, secret) if cid and secret else None


BROAD = "_broad"


def specs() -> dict:
    data = json.loads(ALIASES.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_doc") and isinstance(v, dict)}


def queries(mode: str):
    """(query, sort, relevance_key) in a stable order, without duplicates; the key is the spec id or BROAD."""
    out, seen = [], set()

    def add(q, sort, key):
        if (q, sort) not in seen:
            seen.add((q, sort))
            out.append((q, sort, key))

    for eid, s in specs().items():
        for q in s.get("naver_queries", []):
            add(q, "date", eid)
        if mode == "initial":
            for d in s.get("naver_deep_queries", []):
                d = {"q": d} if isinstance(d, str) else d
                for sort in d.get("sorts", ["date", "sim"]):
                    add(d["q"], sort, eid)
    for q in BROAD_QUERIES:
        add(q, "date", BROAD)
    return out


def _has(term: str, text: str) -> bool:
    if re.fullmatch(r"[\x00-\x7f]+", term):
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.IGNORECASE) is not None
    return term in text


def _about(s: dict, text: str) -> bool:
    """The original 'about' rule for one entity spec (alias + required keyword, no exclude keyword)."""
    if any(_has(x, text) for x in s.get("exclude_keywords", [])):
        return False
    aliases = s.get("aliases", []) + s.get("aliases_no_context", [])
    required = s.get("required_keywords", [])
    return any(_has(a, text) for a in aliases) and (not required or any(_has(r, text) for r in required))


def _strong_words(text: str) -> set:
    return {m.group(0) for m in ART_KEYWORDS.finditer(text)} - AMBIGUOUS


def relevance(key: str, title: str, snippet: str, spec_map: dict) -> Optional[str]:
    """'alias' | 'title' | 'snippet' | None.

    Measured on the first 26,379 stored items (2026-10-29): an art word in the TITLE was on-topic in samples; a match
    only in the snippet was about half off-topic (bank, golf, apartment stories mentioning a museum), so 'snippet'
    items need two distinct non-ambiguous art words and are kept for reference, not for the reading list."""
    text = f"{title} {snippet}"
    s = spec_map.get(key)
    if s and any(_has(x, text) for x in s.get("exclude_keywords", [])):
        return None
    # An alias only in the snippet counts when the spec also demands a context word (Christie's: 경매/낙찰/...);
    # a bare venue name in a snippet ('서울옥션 강남센터에서 주얼리 행사') does not make the story about the entity.
    alias_in_title = s and any(_has(a, title) for a in s.get("aliases", []) + s.get("aliases_no_context", []))
    if s and _about(s, text) and (alias_in_title or s.get("required_keywords")):
        return "alias"
    if art_match(title, []) is not None:
        return "title"
    if len(_strong_words(snippet)) >= 2:
        return "snippet"
    return None


_RANK = {"alias": 0, "title": 1, "snippet": 2}


def best_tier(title: str, snippet: str, spec_map: dict) -> Optional[str]:
    found = [t for t in (relevance(k, title, snippet, spec_map) for k in [*spec_map, BROAD]) if t]
    return min(found, key=_RANK.get) if found else None


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text or ""))).strip()


def item_record(item: dict):
    """Normalise one API item; None when it has no usable link or title."""
    url = item.get("originallink") or item.get("link")
    title = clean(item.get("title"))
    if not url or not url.startswith("http") or not title:
        return None
    try:
        published = parsedate_to_datetime(item.get("pubDate", "")).isoformat()
    except (TypeError, ValueError):
        published = None
    snippet = clean(item.get("description"))[:300] or None
    host = urllib.parse.urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return dict(url=_canon(url), title=title, published=published, snippet=snippet, publisher=host,
                naver_link=item.get("link"))


def collect(ctx):
    keys = load_keys()
    if keys is None:
        raise Blocked("credentials_missing", API_URL, None, "set NAVER_CLIENT_ID/NAVER_CLIENT_SECRET in the environment or project .env")
    ctx.fetcher.s.headers.update({"X-Naver-Client-Id": keys[0], "X-Naver-Client-Secret": keys[1]})
    since = SINCE
    per_query = []
    spec_map = specs()
    for q, sort, key in queries(ctx.mode):
        scanned = kept = 0
        for start in range(1, MAX_START, PAGE_SIZE):
            r = ctx.fetch(API_URL, params={"query": q, "display": PAGE_SIZE, "start": start, "sort": sort},
                          accept="application/json", conditional=False, store=False)
            items = json.loads(r.content).get("items", [])
            ctx.count("fetched", len(items))
            if not items:
                break
            in_window = fresh = False
            for item in items:
                rec = item_record(item)
                scanned += 1
                if rec is None:
                    ctx.count("skipped_incomplete")
                    continue
                if not rec["published"] or rec["published"][:10] < since:
                    continue
                in_window = True
                if relevance(key, rec["title"], rec["snippet"] or "", spec_map) is None:
                    ctx.count("skipped_not_relevant")
                    continue
                # Naver's snippet is the passage around the *query* term, so it differs per query (observed 2026-10-29: 104 of
                # 300 re-seen items). Keep the first stored snippet and its tier; repeat hits only refresh last_seen_at.
                known = ctx.con.execute("SELECT excerpt, type_basis FROM articles WHERE article_id=? AND source_id=?",
                                        (db.sid("art", rec["url"]), ctx.source_id)).fetchone()
                fresh = fresh or known is None
                if known is not None:
                    rec["snippet"], basis = known[0], known[1]
                else:
                    basis = f"naver_search_api:{best_tier(rec['title'], rec['snippet'] or '', spec_map)}"
                db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=rec["url"], title=rec["title"],
                                  published_at=rec["published"], author_text=None, publisher=rec["publisher"],
                                  owner_group=rec["publisher"], article_type="news",
                                  type_basis=basis,
                                  lang="ko", modified_at=None, categories=None, excerpt=rec["snippet"])
                ctx.count("parsed")
                kept += 1
            ctx.con.commit()
            if len(items) < PAGE_SIZE:
                break
            if sort == "date" and not in_window:      # newest-first: the rest is older than the window
                break
            if ctx.mode == "incremental" and sort == "date" and not fresh:  # caught up with stored items
                break
        per_query.append(f"{q}[{sort}] {kept}/{scanned}")
    ctx.note("kept/scanned per query: " + "; ".join(per_query))
