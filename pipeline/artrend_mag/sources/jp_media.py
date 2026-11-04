"""Japanese art media / portals: Bijutsu Techo (article metadata), plus registry-only rows for Art Platform Japan,
Tokyo Art Beat and MOMAT.

Bijutsu Techo offers no RSS/Atom feed (/rss, /feed -> 404) and its sitemap has no titles/dates, so metadata
(title, URL, date, section, PREMIUM flag) is read from the public section listing pages. No article bodies are
fetched (PREMIUM or otherwise); text_storage_policy=metadata_only.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import db
from ._common import clean_text, soup

PARSER_VERSION = "jp_media-1"
BT = "https://bijutsutecho.com"

SOURCES = [
    dict(source_id="bijutsutecho", blueprint_data_id="D35", blueprint_org_id=None,
         name="Bijutsu Techo (美術手帖) — review / insight / interview metadata", owner_group="Bijutsu Shuppan-sha",
         source_kind="media", region_scope="JP", country_codes="JP", access_method="html",
         base_url=BT, entry_url=f"{BT}/magazine/review", terms_url=f"{BT}/terms",
         text_storage_policy="metadata_only", priority="P1",
         st_official_doc="n/a(no RSS/Atom feed: /rss and /feed 404; sitemap.xml lists URLs only)",
         st_collection_terms="利用規約: content copyright Bijutsu Shuppan-sha or third parties; use, reproduction, "
                             "reposting beyond private use without permission prohibited; links allowed with source "
                             "attribution. Only titles/URLs/dates stored (no bodies)",
         st_image_terms="images copyright publisher/third parties; not collected", max_requests=60),
    dict(source_id="art_platform_japan", blueprint_data_id="D07", blueprint_org_id=None,
         name="Art Platform Japan (APJ, Agency for Cultural Affairs)", owner_group="Agency for Cultural Affairs, Japan",
         source_kind="identifier", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://artplatform.go.jp", entry_url="https://artplatform.go.jp/",
         terms_url="https://artplatform.go.jp/terms-of-use", text_storage_policy="metadata_only", priority="P2",
         st_official_doc="no documented bulk/API access (User Guide describes search UI only)",
         st_collection_terms="Terms of Use: content usable with attribution ('Source: Art Platform Japan ...'), but "
                             "reproducing the website or its database in its entirety is prohibited; third-party rights apply",
         st_image_terms="third-party copyright on many images; follow per-item guidance",
         disabled="search portal only; no documented bulk access; terms prohibit reproducing the database in its entirety "
                  "(checked 2026-10-27)",
         operational_state="not_attempted", robots_status="not_checked", st_live_response="not_requested"),
    dict(source_id="tokyo_art_beat", blueprint_data_id=None, blueprint_org_id=None,
         name="Tokyo Art Beat — article metadata", owner_group="Tokyo Art Beat", source_kind="media",
         region_scope="JP", country_codes="JP", access_method="html", base_url="https://www.tokyoartbeat.com",
         entry_url="https://www.tokyoartbeat.com/", terms_url="https://www.tokyoartbeat.com/termsOfUse",
         text_storage_policy="metadata_only", priority="P2", st_official_doc="no public feed/API located",
         st_collection_terms="利用規約 (termsOfUse): content copyright TAB/third parties; use beyond private use "
                             "prohibited. Decision: its event database is a third-party aggregation and is not "
                             "harvested; article metadata not implemented (no feed offered)",
         st_image_terms="all rights reserved",
         disabled="not implemented: no feed offered; event DB deliberately not harvested per terms (decision 2026-10-27)",
         operational_state="not_attempted", robots_status="not_checked", st_live_response="not_requested"),
    dict(source_id="momat_exhibitions", blueprint_data_id="D11", blueprint_org_id="O11",
         name="National Museum of Modern Art, Tokyo (MOMAT) — Exhibitions", owner_group="National Museum of Art",
         source_kind="museum", region_scope="JP", country_codes="JP", access_method="html",
         base_url="https://www.momat.go.jp", entry_url="https://www.momat.go.jp/exhibitions", terms_url=None,
         text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html)",
         st_collection_terms="terms page not reachable (HTTP 403)", st_image_terms="not checked (HTTP 403)",
         disabled="HTTP 403 to the project crawler UA (blocked_access, recorded in previous probe; not retried)",
         operational_state="blocked_access", robots_status="not_checked(403)", st_live_response="http_403"),
]

_SECTIONS = {"review": "review", "insight": "criticism", "interview": "interview"}


def collect(ctx):
    if ctx.source_id == "bijutsutecho":
        return _bt(ctx)
    raise ValueError(f"{ctx.source_id} is registry-only")


def _bt(ctx):
    cutoff = "2025-04-01"
    for sec, atype in _SECTIONS.items():
        page = 1
        while True:
            url = f"{BT}/magazine/{sec}" + (f"?page={page}" if page > 1 else "")
            r = ctx.fetch(url)
            items = soup(r.text).select("article.MagazinePageListItem")
            ctx.count("fetched", len(items))
            oldest = None
            for it in items:
                a = it.select_one("h2.title a[href]")
                if a is None:
                    continue
                link = urllib.parse.urljoin(BT, a["href"])
                tm = it.select_one("time[datetime]")
                pub = tm["datetime"] if tm else None
                cats = [clean_text(c.get_text(" ")) for c in it.select("p.category a")]
                if it.select_one(".premium-label"):
                    cats.append("PREMIUM")
                sponsored = "/promotion/" in link or "PROMOTION" in cats
                db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=link,
                                  title=clean_text(a.get_text(" ")), published_at=pub, author_text=None,
                                  publisher="美術手帖 (Bijutsu Techo)", owner_group="Bijutsu Shuppan-sha",
                                  article_type="sponsored" if sponsored else atype,
                                  type_basis="url path /promotion/ or PROMOTION label" if sponsored else f"url section /magazine/{sec}",
                                  lang="ja",
                                  categories="; ".join(c for c in cats if c) or None, excerpt=None)
                ctx.count("parsed")
                if pub:
                    oldest = pub if oldest is None or pub < oldest else oldest
            ctx.con.commit()
            if ctx.mode != "initial" or not items or (oldest and oldest < cutoff) or page >= 15:
                break
            page += 1
    ctx.note("Bijutsu Techo: no feed; metadata from /magazine/{review,insight,interview} listing pages "
             "(paginated ?page=N back to 2025-04 in initial mode, page 1 in incremental); no article bodies fetched; "
             "author not shown on listings")
