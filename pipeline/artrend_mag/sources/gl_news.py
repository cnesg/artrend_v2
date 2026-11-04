"""Japanese and international art news METADATA from publishers' own public RSS feeds (Blueprint D32).

Replaces the Japanese/English part of the original v2v Google News RSS channel (imported up to 2026-10-19 as
`legacy_v2v_artnews`), which cannot be continued: news.google.com robots.txt disallows every /rss path.
Candidates were probed on 2026-10-29 (robots + one feed request) and their terms scanned for crawler clauses.

metadata_only: title, canonical URL, author, published_at, categories. No bodies, excerpts or images.
General news/culture feeds keep only items whose title or category carries an art word (`type_basis` records it);
art-specialist feeds are kept whole. RSS shows the latest items only, so history accumulates from incremental runs.

Registered but disabled (permission): The Guardian (terms forbid crawlers/scrapers and other automated data
gathering), The New York Times (terms forbid text-and-data mining and ignoring exclusion protocols), South China
Morning Post (terms forbid any automated system). Guardian and NYT offer official APIs that need a key.
Not registered: artnet, Artsy, Smithsonian (terms pages return 403 to the project crawler, so terms could not be read).
"""
from __future__ import annotations

import re

from .kr_news import collect_feed

PARSER_VERSION = "gl_news-1"

# Japanese: kanji/kana words; Latin: word-bounded English/French art words.
_JA = re.compile(r"美術|展覧会|個展|企画展|回顧展|写真展|アート|ギャラリー|画家|彫刻|絵画|版画|現代美術|ビエンナーレ|トリエンナーレ|"
                 r"芸術祭|美術館|キュレーター|学芸員|オークション|工芸|陶芸|浮世絵|日本画|洋画")
_LATIN = re.compile(r"\b(art|arts|artist|artists|artwork|artworks|exhibition|exhibitions|exhibit|museum|museums|gallery|galleries|"
                    r"painting|paintings|painter|sculpture|sculptor|biennale|biennial|triennial|retrospective|curator|auction|"
                    r"photography|installation|drawing|drawings|art fair|frieze|art basel|exposition|musée|peintre|peinture|"
                    r"artiste|sculpteur|galerie|rétrospective)\b", re.I)
# "art" alone also names film/music/'state-of-the-art' stories; it admits an item only with a second art word.
_WEAK = {"art", "arts", "drawing", "exhibit", "installation", "photography"}
# Section labels that mark a whole category as art (Le Monde 'Arts', BBC 'Entertainment & Arts' is NOT enough).
_ART_CATEGORY = re.compile(r"^(art|arts|art and design|artanddesign|美術|アート)$", re.I)


def art_match_world(title: str, categories) -> str | None:
    text = title or ""
    m = _JA.search(text)
    if m:
        return m.group(0)
    words = [w.group(0).lower() for w in _LATIN.finditer(text)]
    strong = [w for w in words if w not in _WEAK]
    if strong:
        return strong[0]
    if len(set(words)) >= 2:
        return "+".join(sorted(set(words)))
    for c in categories:
        if _ART_CATEGORY.match((c or "").strip()):
            return f"category:{c.strip()}"
    return None


def _row(source_id, name, publisher, entry_url, base_url, terms_url, region, country, lang, art_filter=True,
         terms_note="terms scanned 2026-10-29: no crawler/scraper clause found; only the official RSS feed is polled "
                    "(robots allows it) and title/link/date/author/category are kept for internal discovery",
         **kw):
    row = dict(source_id=source_id, blueprint_data_id="D32", blueprint_org_id=None, name=name, owner_group=publisher,
               source_kind="media", region_scope=region, country_codes=country, access_method="rss", base_url=base_url,
               entry_url=entry_url, terms_url=terms_url, text_storage_policy="metadata_only", priority="P1",
               st_official_doc="n/a(official RSS feed)", st_collection_terms=terms_note,
               st_image_terms="images not collected", max_requests=6, publisher=publisher, art_filter=art_filter,
               lang=lang, notes=("general feed filtered by art words" if art_filter else "art-specialist outlet; all items kept"))
    row.update(kw)
    return row


_DISABLED = dict(disabled="Terms forbid automated collection; permission (or the official keyed API) required",
                 operational_state="blocked_permission")

SOURCES = [
    # Japan
    _row("jp_asahi_culture_rss", "朝日新聞 文化 — RSS", "朝日新聞", "https://www.asahi.com/rss/asahi/culture.rdf",
         "https://www.asahi.com", "https://www.asahi.com/policy/", "JP", "JP", "ja"),
    _row("jp_sankei_life_rss", "産経新聞 ライフ — RSS", "産経新聞",
         "https://www.sankei.com/arc/outboundfeeds/rss/category/life/?outputType=xml", "https://www.sankei.com", None,
         "JP", "JP", "ja", terms_note="terms page not located (/policy/ 404); official RSS only, metadata only"),
    _row("jp_thisisgallery_rss", "This is Gallery Media — RSS", "This is Gallery",
         "https://media.thisisgallery.com/feed", "https://media.thisisgallery.com", None, "JP", "JP", "ja", art_filter=False,
         terms_note="terms page not located; gallery-guide media, official RSS only, metadata only"),
    _row("jp_spoon_tamago_rss", "Spoon & Tamago — RSS", "Spoon & Tamago", "https://www.spoon-tamago.com/feed/",
         "https://www.spoon-tamago.com", None, "JP", "JP", "en",
         terms_note="terms page not located; English-language Japanese art/design blog, official RSS only, metadata only"),
    # International
    _row("gl_observer_arts_rss", "Observer Arts — RSS", "Observer", "https://observer.com/arts/feed/", "https://observer.com",
         "https://observer.com/terms-of-service/", "GLOBAL", "US", "en", art_filter=False),
    _row("gl_colossal_rss", "Colossal — RSS", "Colossal", "https://www.thisiscolossal.com/feed/", "https://www.thisiscolossal.com",
         "https://www.thisiscolossal.com/terms-of-service/", "GLOBAL", "US", "en", art_filter=False),
    _row("gl_bbc_arts_rss", "BBC Entertainment & Arts — RSS", "BBC", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
         "https://www.bbc.co.uk", "https://www.bbc.co.uk/usingthebbc/terms", "GLOBAL", "GB", "en"),
    _row("eu_lemonde_arts_rss", "Le Monde Arts — RSS", "Le Monde", "https://www.lemonde.fr/arts/rss_full.xml",
         "https://www.lemonde.fr", "https://www.lemonde.fr/cgv", "EUROPE", "FR", "fr", art_filter=False,
         terms_note="CGV page scanned (short page, no crawler clause found); official arts RSS only, metadata only"),
    # Disabled: explicit anti-crawler / anti-TDM terms (kept in the registry so the decision is visible)
    _row("gl_guardian_art_rss", "The Guardian Art & design — RSS", "The Guardian", "https://www.theguardian.com/artanddesign/rss",
         "https://www.theguardian.com", "https://www.theguardian.com/help/terms-of-service", "GLOBAL", "GB", "en",
         terms_note="RESTRICTIVE: terms forbid 'spider', 'crawler' or other automated device for data gathering, scraping or "
                    "extraction on the Guardian Site; use the keyed Guardian Open Platform API instead", **_DISABLED),
    _row("gl_nyt_art_rss", "The New York Times Art & Design — RSS", "The New York Times",
         "https://rss.nytimes.com/services/xml/rss/nyt/ArtandDesign.xml", "https://www.nytimes.com",
         "https://help.nytimes.com/hc/en-us/articles/115014893428-Terms-of-Service", "GLOBAL", "US", "en",
         terms_note="RESTRICTIVE: terms forbid text and data mining and failing to abide by the Robots Exclusion Protocol; "
                    "use the keyed NYT developer API instead", **_DISABLED),
    _row("gl_scmp_arts_rss", "South China Morning Post Arts — RSS", "SCMP", "https://www.scmp.com/rss/322296/feed",
         "https://www.scmp.com", "https://www.scmp.com/terms-conditions", "ASIA", "HK", "en",
         terms_note="RESTRICTIVE: terms prohibit 'any automated system (including web crawlers, spiders, or scrapers) to "
                    "access, extract, or index SCMP Content for any purpose'", **_DISABLED),
]


def collect(ctx):
    return collect_feed(ctx, art_match_world, default_lang="en")
