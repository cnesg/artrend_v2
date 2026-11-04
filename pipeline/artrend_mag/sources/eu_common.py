"""Private helpers shared by the eu_* source modules (no SOURCES rows here)."""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import classify_subtype, clean_text, parse_date_range, split_title_artist

SINCE = "2025-04-01"
# programme labels that precede the real "Artist: Title" part ("Hyundai Commission: Tarek Atoui", "Art Now: X")
PREFIX = re.compile(r"^(?:[^:]{0,40}\bCommission\b[^:]{0,10}|ARTIST ROOMS|Art Now|Display|Exhibition|Project|Spotlight|Focus)\s*:\s*", re.I)


def today() -> dt.date:
    return now_kst().date()


def org(ctx, name, etype="institution", url=None):
    return db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=f"src:{ctx.source_id}", id_value=name_key(name),
                            source_id=ctx.source_id, official_url=url)


def name_key(name):
    return db.name_key(name)


def known(ctx, key):
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?", (ctx.source_id, key)).fetchone()
    return row


def needs_detail(ctx, key) -> bool:
    """initial: always; incremental: unseen keys or events still running / ended within 30 days."""
    if ctx.mode == "initial":
        return True
    row = known(ctx, key)
    if row is None or not row["end_date"]:
        return True
    return row["end_date"] >= (today() - dt.timedelta(days=30)).isoformat()


def try_fetch(ctx, url, **kw):
    try:
        return ctx.fetch(url, **kw)
    except FetchError as e:
        ctx.note(f"detail error {url}: {str(e)[:80]}")
        ctx.count("detail_errors")
        return None


def dates(text, default_year=None):
    return parse_date_range(clean_text(text) if text else None, default_year)


def store_exhibition(ctx, *, key, title, url, ev, organizer, city=None, country=None, date_text=None, dates_tuple=None,
                     artists=None, artist_method="list_markup", subtype=None, desc=None, image=None, image_basis=None,
                     event_type="exhibition", status=None, lang="en", person_title_fallback=True, curators=None, parent=None):
    title = clean_text(title)
    s, sp, e, ep = dates_tuple if dates_tuple else dates(date_text)
    artists = [a for a in (artists or []) if a]
    method, conf = artist_method, "high"
    if not artists and person_title_fallback:
        t2 = PREFIX.sub("", title)
        nm = split_title_artist(t2) or (split_title_artist(t2 + ": x") if t2 != title else None)
        if nm:
            artists, method, conf = [nm], "title_pattern", "medium"
    if subtype is None and event_type == "exhibition":
        subtype = classify_subtype(title, len(artists) if artists and method != "title_pattern" else (1 if artists else None))
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type=event_type, subtype=subtype,
        title=title, title_lang=lang, organizer_entity_id=organizer, city=city, country_code=country,
        start_date=s, start_precision=sp, end_date=e, end_precision=ep, date_text=clean_text(date_text) if date_text else None,
        announced_status=status, parent_event_id=parent, url=url, description_excerpt=clean_text(desc) if desc else None,
        parser_version=ctx.parser_version, evidence_id=ev)
    ctx.count("parsed")
    if not country:
        db.add_review(ctx.con, "region", "events", eid, "venue country unknown")
    for a in artists:
        etype = "group" if re.search(r"\b(collective|group|studio|assembl|architecture|projects?|sound system|sections)\b", a, re.I) else "person"
        ent = db.ensure_entity(ctx.con, entity_type=etype, name=a, namespace=f"src:{ctx.source_id}", source_id=ctx.source_id,
                               evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "artist", a, ev, method, conf)
    for c in curators or []:
        ent = db.ensure_entity(ctx.con, entity_type="person", name=c, namespace=f"src:{ctx.source_id}", source_id=ctx.source_id,
                               evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "curator", c, ev, "list_markup")
    if image:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=image,
                            usage_status="unknown", basis=image_basis or "promotional image; no open licence stated")
    return eid


def og(html, prop):
    m = re.search(r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\']([^"\']*)' % prop, html)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:%s["\']' % prop, html)
    return clean_text(m.group(1)) if m else None


def range_dates(t):
    """parse_date_range with day-only start expansion ('23 — 27 January 2024', '12 – 15 November 2026')
    and ordinal stripping ('1st November', '1 er novembre')."""
    t = re.sub(r"(\d+)\s*(st|nd|rd|th|er)\b", r"\1", t or "")
    t = re.sub(r"\b(\d{1,2})\s*[–—-]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", r"\1 \3 \4 – \2 \3 \4", t)
    m = re.search(r"\d{1,2}(\s+[A-Za-z]+)?(\s+\d{4})?\s*[–—-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}", t)
    return parse_date_range((m.group(0) if m else t).replace("—", "–"))
