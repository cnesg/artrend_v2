"""Biennials / programmes: La Biennale di Venezia — Biennale Arte 2026 (artists + national participations)."""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from .. import db
from ._common import clean_text, parse_date_range
from . import eu_common as C

PARSER_VERSION = "eu_programs-1"
BASE = "https://www.labiennale.org"

SOURCES = [
    dict(source_id="labiennale_arte", blueprint_data_id="D16", blueprint_org_id=None, name="La Biennale di Venezia — Biennale Arte",
         owner_group="La Biennale di Venezia", source_kind="biennial", region_scope="EUROPE", country_codes="IT",
         access_method="html", base_url=BASE, entry_url=f"{BASE}/en/art/2026", terms_url=f"{BASE}/en/legal-notes",
         text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html; /en/rss.xml is news only)",
         st_collection_terms="see run notes", st_image_terms="artist/pavilion photos © photographers; no open licence stated",
         max_requests=40),
]

EDITION = "2026"


def collect(ctx):
    biennale = db.ensure_entity(ctx.con, entity_type="biennial", name="La Biennale di Venezia", namespace=f"src:{ctx.source_id}",
                                source_id=ctx.source_id, official_url=BASE)
    r = ctx.fetch(f"{BASE}/en/art/{EDITION}")
    s = BeautifulSoup(r.text, "lxml")
    for sc in s(["script", "style", "nav", "footer", "header"]):
        sc.decompose()
    text = " ".join((s.find("main") or s.body).get_text(" ").split())
    m = re.search(r"The (\d+)(?:st|nd|rd|th) International Art Exhibition of La Biennale di Venezia\s*[–-]\s*titled (.+?) by ([^–-]+?)\s*[–-]\s*runs from (.+?\d{4})", text)
    if not m:
        raise ValueError("edition intro sentence not found on homepage")
    ordinal, theme, curator, dtext = m.group(1), clean_text(m.group(2)), clean_text(m.group(3)), clean_text(m.group(4))
    dates = parse_date_range(dtext)
    ev = ctx.evidence(r, locator="edition intro", excerpt=m.group(0)[:300])
    title = f"Biennale Arte {EDITION}: {theme} ({ordinal}th International Art Exhibition)"
    edition_id = C.store_exhibition(ctx, key=f"arte-{EDITION}", title=title, url=f"{BASE}/en/art/{EDITION}", ev=ev,
                                    organizer=biennale, city="Venice", country="IT", date_text=dtext, dates_tuple=dates,
                                    event_type="biennial_edition", subtype=None, person_title_fallback=False,
                                    curators=[curator], desc=m.group(0))
    ctx.con.commit()
    _artists(ctx, edition_id)
    _pavilions(ctx, edition_id, biennale, dates, dtext)
    ctx.con.commit()


def _artists(ctx, edition_id):
    n, page = 0, 0
    last = 30 if ctx.mode == "initial" else 0  # incremental: first page only (robots Crawl-delay ~60 s)
    while page <= last:
        r = ctx.fetch(f"{BASE}/en/art/{EDITION}/artists", params={"page": page} if page else None)
        s = BeautifulSoup(r.text, "lxml")
        arts = s.select("article.node-partecipante")
        if not arts:
            break
        ev = ctx.evidence(r, locator=f"artists page={page}")
        for a in arts:
            link = a.find("a", href=True)
            name = clean_text((a.select_one(".lb-item-title") or a).get_text(" "))
            if not link or not name:
                continue
            slug = link["href"].rstrip("/").split("/")[-1]
            exc = clean_text((a.select_one(".lb-excerpt") or a).get_text(" ")) if a.select_one(".lb-excerpt") else ""
            by = re.match(r"(1[89]\d\d|20\d\d)(?:\s*[-–]\s*(1[89]\d\d|20\d\d))?,", exc)
            etype = "person" if by else "group"
            ent = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace="labiennale_participant", id_value=slug,
                                   source_id=ctx.source_id, evidence_id=ev, official_url=urllib.parse.urljoin(BASE, link["href"]),
                                   nationality_text=exc or None, birth_year=int(by.group(1)) if by else None,
                                   death_year=int(by.group(2)) if by and by.group(2) else None)
            db.add_participant(ctx.con, edition_id, ent, "artist", name, ev, "list_markup")
            n += 1
        ctx.count("fetched", len(arts))
        if not s.select(f'a[href*="page={page + 1}"]'):
            break
        page += 1
    ctx.note(f"{n} participating artists of the main exhibition")
    ctx.con.commit()


def _pavilions(ctx, edition_id, biennale, dates, dtext):
    rows, page = {}, 0
    last = 30 if ctx.mode == "initial" else 0
    while page <= last:
        r = ctx.fetch(f"{BASE}/en/art/{EDITION}/national-participations", params={"page": page} if page else None)
        s = BeautifulSoup(r.text, "lxml")
        arts = s.select("article")
        new = 0
        lev = ctx.evidence(r, locator=f"national-participations page={page}")
        for a in arts:
            link = a.find("a", href=True)
            if not link or not link["href"].startswith(f"/en/art/{EDITION}/"):
                continue
            ttl = a.select_one(".lb-item-title")
            if not ttl:
                continue
            key = link["href"].rstrip("/").split("/")[-1]
            if key in rows:
                continue
            rows[key] = dict(country=clean_text(ttl.get_text(" ")),
                             theme=clean_text(a.select_one(".lb-excerpt").get_text(" ")) if a.select_one(".lb-excerpt") else None,
                             venue=clean_text(a.select_one(".lb-date").get_text(" ")) if a.select_one(".lb-date") else None,
                             url=urllib.parse.urljoin(BASE, link["href"]), ev=lev)
            new += 1
        ctx.count("fetched", new)
        if not new or not s.select(f'a[href*="page={page + 1}"]'):
            break
        page += 1
    # Pavilion detail pages (commissioner/curator/exhibitor credits) are not fetched: robots.txt Crawl-delay makes
    # ~100 extra requests impractical (~1 request/min). Listing gives country, pavilion title and venue.
    for key, p in rows.items():
        title = f"{p['country']} — {p['theme']}" if p["theme"] else p["country"]
        C.store_exhibition(ctx, key=key, title=title, url=p["url"], ev=p["ev"], organizer=biennale, city="Venice", country="IT",
                           date_text=f"edition dates: {dtext}; venue: {p['venue']}", dates_tuple=dates, subtype="project",
                           person_title_fallback=False, parent=edition_id)
    ctx.con.commit()
    ctx.note(f"{len(rows)} national participations (Venice; pavilion venue in date_text); edition dates applied")
