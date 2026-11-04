"""Latin American museum exhibition collectors (Americas region): MASP (BR), MUAC (MX), MALBA (AR), Pinacoteca (BR)."""
from __future__ import annotations

import re

from .. import db
from ..config import iso_now, now_kst
from ._common import classify_subtype, clean_text, parse_date_range, soup, split_title_artist

PARSER_VERSION = "am_museums_latam-1"

_NO_TERMS = "terms page not located"
SOURCES = [
    dict(source_id="masp_exposicoes", blueprint_data_id=None, blueprint_org_id="O22",
         name="MASP — Exposições", owner_group="MASP – Museu de Arte de São Paulo Assis Chateaubriand",
         source_kind="museum", region_scope="AMERICAS", country_codes="BR", access_method="html",
         base_url="https://masp.org.br", entry_url="https://masp.org.br/exposicoes", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms=_NO_TERMS, st_image_terms="images credited per work on the page; no open licence stated",
         max_requests=60),
    dict(source_id="muac_exposiciones", blueprint_data_id=None, blueprint_org_id="O23",
         name="MUAC UNAM — Exposiciones", owner_group="Universidad Nacional Autónoma de México",
         source_kind="museum", region_scope="AMERICAS", country_codes="MX", access_method="html",
         base_url="https://muac.unam.mx", entry_url="https://muac.unam.mx/exposiciones", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms=_NO_TERMS, st_image_terms="no open licence stated", max_requests=40),
    dict(source_id="malba_exposiciones", blueprint_data_id=None, blueprint_org_id=None,
         name="MALBA — Exposiciones", owner_group="Fundación Costantini (MALBA)", source_kind="museum",
         region_scope="AMERICAS", country_codes="AR", access_method="html",
         base_url="https://malba.org.ar", entry_url="https://malba.org.ar/eventos/de/exposiciones/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html; year-filtered listing)",
         st_collection_terms=_NO_TERMS, st_image_terms="no open licence stated", max_requests=60),
    dict(source_id="pinacoteca_exposicoes", blueprint_data_id=None, blueprint_org_id=None,
         name="Pinacoteca de São Paulo — Exposições", owner_group="Pinacoteca do Estado de São Paulo",
         source_kind="museum", region_scope="AMERICAS", country_codes="BR", access_method="html",
         base_url="https://pinacoteca.org.br",
         entry_url="https://pinacoteca.org.br/programacao/status/exposicoes/em-cartaz-exposicoes/", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms=_NO_TERMS, st_image_terms="no open licence stated", max_requests=60),
]


def _org(ctx, name, key, url):
    return db.ensure_entity(ctx.con, entity_type="institution", name=name, namespace=f"src:{ctx.source_id}",
                            id_value=key, source_id=ctx.source_id, official_url=url)


def _store(ctx, *, key, title, lang, org, city, cc, date_text, url, ev, default_year=None, desc=None,
           img=None, img_basis=None, dates=None):
    sd, sp, ed, ep = dates or parse_date_range(date_text, default_year=default_year)
    if date_text and re.search(r"^\s*(desde|since)\b", date_text, re.I):
        ed, ep = None, None
    artist = split_title_artist(title)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key, event_type="exhibition",
        subtype=classify_subtype(title), title=title, title_lang=lang, organizer_entity_id=org, city=city,
        country_code=cc, start_date=sd, start_precision=sp, end_date=ed, end_precision=ep,
        date_text=date_text or None, url=url, description_excerpt=desc, parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    if artist:
        etype = "group" if re.search(r"\s(&|and|y|e)\s|colectivo|coletivo", artist, re.I) else "person"
        ent = db.ensure_entity(ctx.con, entity_type=etype, name=artist, namespace=f"src:{ctx.source_id}",
                               source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "artist", artist, ev, "title_pattern", "medium")
    if img:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=url, image_url=img,
                            usage_status="unknown", basis=img_basis or "no open licence stated")
    return eid


# ---------------------------------------------------------------------------------------------- MUAC
MUAC = "https://muac.unam.mx"


def _muac(ctx):
    org = _org(ctx, "Museo Universitario Arte Contemporáneo (MUAC), UNAM", "muac", MUAC + "/")
    # /exposiciones/pasadas is a single page listing every past show back to 2008 -> cheap in both modes
    pages = [f"{MUAC}/exposiciones", f"{MUAC}/exposiciones/pasadas"]
    seen = set()
    for page in pages:
        r = ctx.fetch(page)
        s = soup(r.text)
        cards = s.select("a.info-square--grid-exhibition[href]")
        ctx.count("fetched", len(cards))
        for a in cards:
            href = a["href"]
            m = re.match(r"^(?:https://muac\.unam\.mx)?/exposicion/([^/?#]+)", href)
            if not m or m.group(1) in seen:
                continue
            slug = m.group(1)
            seen.add(slug)
            t = a.select_one("h4.info-square__title")
            if not t:
                continue
            title = clean_text(t.get_text(" "))
            dfrom = clean_text((a.select_one(".info-square__date-from") or t).get_text()) if a.select_one(".info-square__date-from") else ""
            duntil = clean_text(a.select_one(".info-square__date-until").get_text()) if a.select_one(".info-square__date-until") else ""
            label = clean_text(a.select_one(".info-square__label").get_text()) if a.select_one(".info-square__label") else ""
            date_text = " – ".join(x for x in (dfrom, duntil) if x)
            s0 = parse_date_range(dfrom)
            e0 = parse_date_range(duntil)
            dates = (s0[0], s0[1], e0[0], e0[1])
            ev = ctx.evidence(r, locator=f"a.info-square[href=/exposicion/{slug}]", excerpt=date_text or None)
            _store(ctx, key=slug, title=title, lang="es", org=org, city="Ciudad de México", cc="MX",
                   date_text=date_text, url=f"{MUAC}/exposicion/{slug}", ev=ev, dates=dates,
                   desc=(f"sala: {label}" if label else None))
        ctx.con.commit()
    ctx.note("muac: /exposiciones (current+upcoming) and /exposiciones/pasadas (single page, back to 2008)")


# ---------------------------------------------------------------------------------------------- MASP
MASP = "https://masp.org.br"


def _masp(ctx):
    org = _org(ctx, "MASP – Museu de Arte de São Paulo Assis Chateaubriand", "masp", MASP + "/")
    r = ctx.fetch(f"{MASP}/exposicoes")
    s = soup(r.text)
    boxes = s.select(".box-image-text-toggle")
    ctx.count("fetched", len(boxes))
    seen = set()
    for b in boxes:
        a = b.find("a", href=re.compile(r"/exposicoes/[^/#?]+$"))
        t = b.select_one(".title")
        if not a or not t:
            continue
        slug = a["href"].rstrip("/").rsplit("/", 1)[1]
        if slug in seen:
            continue
        seen.add(slug)
        title = clean_text(t.get_text(" "))
        sub = b.select_one(".sub-title")
        date_text = clean_text(sub.get_text(" ")) if sub else ""
        img = None
        bg = b.select_one(".box-image[style]")
        if bg:
            m = re.search(r"url\(([^)]+)\)", bg["style"])
            img = m.group(1).strip("'\"") if m else None
        ev = ctx.evidence(r, locator=f".box-image-text-toggle a[href$=/exposicoes/{slug}]", excerpt=date_text or None)
        _store(ctx, key=slug, title=title, lang="pt", org=org, city="São Paulo", cc="BR", date_text=date_text,
               url=f"{MASP}/exposicoes/{slug}", ev=ev, img=img,
               img_basis="MASP exhibition image; credits per work; no open licence stated")
    ctx.con.commit()
    ctx.note("masp: listing shows current+upcoming; past-years accordion is loaded by JavaScript (not collected)")


# ---------------------------------------------------------------------------------------------- MALBA
MALBA = "https://malba.org.ar"


def _malba_title(raw):
    # MALBA uses "__" / "_" as typographic line breaks in titles ("Margarita Paksa__Ideas correspondientes")
    t = clean_text(raw)
    t = re.sub(r"\s*__\s*", ": ", t)
    return clean_text(t.replace("_", " "))


_ES_MON = r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"


def _malba_date_line(node):
    for t in node.find_all(string=True):
        tx = clean_text(t)
        if re.fullmatch(rf"\d{{1,2}} de {_ES_MON},? \d{{4}}", tx, re.I):
            continue  # WordPress post date ("22 de agosto, 2024"), not the exhibition date
        if 4 <= len(tx) <= 90 and re.search(r"^(del?|desde|hasta|a partir|\d)", tx, re.I) and \
                (re.search(r"^\d{4}\s*[—–-]\s*\d{4}$", tx) or re.search(rf"\bde {_ES_MON}\b", tx, re.I)):
            return tx
    return ""


_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\s*[—–-]+\s*_?\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?![\d/])")


def _malba_slash_dates(text):
    """Detail pages of older shows give 'DD/MM/YY — DD/MM/YY' or 'DD/MM—DD/MM/YY'."""
    m = _SLASH.search(text)
    if not m:
        return "", None
    d1, m1, y1, d2, m2, y2 = m.groups()
    yy = lambda y: int(y) + 2000 if len(y) == 2 else int(y)
    ey = yy(y2)
    sy = yy(y1) if y1 else (ey - 1 if int(m1) > int(m2) else ey)
    try:
        import datetime as dt
        sd, ed = dt.date(sy, int(m1), int(d1)).isoformat(), dt.date(ey, int(m2), int(d2)).isoformat()
    except ValueError:
        return "", None
    return clean_text(m.group(0)), (sd, "day", ed, "day")


def _malba_needs_detail(ctx, slug):
    if ctx.mode == "initial":
        return True
    row = ctx.con.execute("SELECT 1 FROM events WHERE source_id=? AND source_event_key=?", (ctx.source_id, slug)).fetchone()
    return row is None


def _malba(ctx):
    org = _org(ctx, "Museo de Arte Latinoamericano de Buenos Aires (MALBA)", "malba", MALBA + "/")
    this_year = now_kst().year
    years = list(range(this_year + 1, 2022, -1)) if ctx.mode == "initial" else [this_year + 1, this_year]
    pages = [(f"{MALBA}/eventos/de/exposiciones/", None)]
    pages += [(f"{MALBA}/eventos/de/exposiciones/?event_start_after={y}-01-01&event_start_before={y}-12-31", y)
              for y in years]
    seen = set()
    for url, year in pages:
        r = ctx.fetch(url)
        s = soup(r.text)
        items = s.select(".e-loop-item")
        ctx.count("fetched", len(items))
        for it in items:
            a = it.find("a", href=re.compile(r"^https://(?:www\.)?malba\.org\.ar/evento/[^/]+/?$"))
            h = it.select_one("h2, h3")
            if not a or not h:
                continue
            slug = a["href"].rstrip("/").rsplit("/", 1)[1]
            if slug in seen:
                continue
            seen.add(slug)
            title = _malba_title(h.get_text(" "))
            date_text = _malba_date_line(it)
            # the year filter is overlap-based (a 2022-2026 show appears under 2025), so it does not state a year
            ev = ctx.evidence(r, locator=f".e-loop-item a[href*=/evento/{slug}/]" + (f" (year filter {year})" if year else ""),
                              excerpt=date_text or None)
            dates, dy, ev_d = None, None, ev
            if re.fullmatch(r"(19|20)\d{2}\s*[—–-]\s*(19|20)\d{2}", date_text or ""):
                y1, y2 = re.findall(r"\d{4}", date_text)
                dates = (y1, "year", y2, "year")
            elif not re.search(r"\d{4}", date_text or "") and _malba_needs_detail(ctx, slug):
                # listing omits the year: the detail page shows "Exposiciones → YYYY" (page-stated year)
                try:
                    dr = ctx.fetch(f"{MALBA}/evento/{slug}/")
                except Exception as e:
                    if type(e).__name__ != "FetchError":
                        raise
                    ctx.note(f"detail error {slug}: {e}")
                    ctx.count("detail_errors")
                    dr = None
                if dr is not None:
                    ds = soup(dr.text)
                    m = re.search(r"Exposiciones\s*→\s*((?:19|20)\d{2})", clean_text(ds.get_text(" ")))
                    dy = int(m.group(1)) if m else None
                    date_text = date_text or _malba_date_line(ds.find("main") or ds)
                    if not date_text:
                        date_text, dates = _malba_slash_dates(clean_text(ds.get_text(" ")))
                    if dy and not date_text:
                        dates = (str(dy), "year", None, None)
                    ev_d = ctx.evidence(dr, locator="detail: 'Exposiciones → YYYY' + date line",
                                        excerpt=clean_text(f"→ {dy} {date_text}") or None)
            elif not re.search(r"\d{4}", date_text or ""):
                # incremental: already stored from its detail page; nothing new on the listing
                ctx.con.execute("UPDATE events SET last_seen_at=? WHERE source_id=? AND source_event_key=?",
                                (iso_now(), ctx.source_id, slug))
                ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
                ctx.count("parsed")
                continue
            _store(ctx, key=slug, title=title, lang="es", org=org, city="Buenos Aires", cc="AR", date_text=date_text,
                   url=f"{MALBA}/evento/{slug}/", ev=ev_d, dates=dates, default_year=dy)
            if not dates and not dy and date_text and not re.search(r"\d{4}", date_text):
                db.add_review(ctx.con, "date", "events", db.sid("evt", ctx.source_id, slug), "year not shown on listing",
                              date_text)
        ctx.con.commit()
    ctx.note(f"malba: year-filtered listing pages walked {years[-1]}..{years[0]} (site offers per-year filter)")


# ---------------------------------------------------------------------------------------------- Pinacoteca
PINA = "https://pinacoteca.org.br"
_EXP = r"Exposi(?:[cç][aã]o|[cç][oõ]es)"
_PINA_DATES = re.compile(rf"Data In[ií]cio {_EXP}\s+(.{{6,40}}?\d{{4}})\s*-\s*Data T[eé]rmino {_EXP}\s+(.{{6,40}}?\d{{4}})")
_PINA_DATA = re.compile(r"Data:\s*\|?\s*(de .{4,70}?\d{4})")


def _pina_dates(text):
    m = _PINA_DATES.search(clean_text(text))
    if not m:
        return "", (None, None, None, None)
    a, b = parse_date_range(m.group(1)), parse_date_range(m.group(2))
    return clean_text(f"{m.group(1)} - {m.group(2)}"), (a[0], a[1], b[0], b[1])


def _pinacoteca(ctx):
    org = _org(ctx, "Pinacoteca de São Paulo", "pinacoteca", PINA + "/")
    pages = [("em-cartaz-exposicoes", False), ("futuras-exposicoes", False), ("passadas-exposicoes", True)]
    seen = set()
    for status, past in pages:
        r = ctx.fetch(f"{PINA}/programacao/status/exposicoes/{status}/")
        s = soup(r.text)
        cards = s.select("div.card-programacao, div.card-programacao-passadas")
        ctx.count("fetched", len(cards))
        for c in cards:
            a = c.find("a", href=re.compile(r"/programacao/exposicoes/[^/]+/?$"))
            if not a:
                continue
            slug = a["href"].rstrip("/").rsplit("/", 1)[1]
            if slug in seen:
                continue
            seen.add(slug)
            ctext = c.get_text(" | ")
            m = re.search(r"Exposição:\s*\|\s*([^|]+)", clean_text(ctext))
            title = clean_text(m.group(1)) if m else clean_text(a.get_text(" "))
            lm = re.search(r"Local:\s*\|\s*([^|]+)", clean_text(ctext))
            local = clean_text(lm.group(1)) if lm else None
            date_text, dates = _pina_dates(c.get_text(" "))
            url = f"{PINA}/programacao/exposicoes/{slug}/"
            ev = ctx.evidence(r, locator=f"{status} card a[href*=/exposicoes/{slug}/]", excerpt=date_text or None)
            if not date_text and past:
                seen_row = ctx.con.execute("SELECT 1 FROM events WHERE source_id=? AND source_event_key=?",
                                           (ctx.source_id, slug)).fetchone()
                if seen_row and ctx.mode == "incremental":
                    ctx.con.execute("UPDATE events SET last_seen_at=? WHERE source_id=? AND source_event_key=?",
                                    (iso_now(), ctx.source_id, slug))
                    ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
                    ctx.count("parsed")
                    continue
                try:
                    dr = ctx.fetch(url)
                    dtext = clean_text(soup(dr.text).get_text(" | "))
                    dm = _PINA_DATA.search(dtext)
                    if dm:
                        date_text = clean_text(dm.group(1))
                        dates = parse_date_range(date_text)
                    else:
                        date_text, dates = _pina_dates(dtext.replace(" | ", " "))
                    ev = ctx.evidence(dr, locator="detail 'Data Início Exposição … Data Término Exposição …'",
                                      excerpt=date_text or None)
                except Exception as e:
                    if type(e).__name__ != "FetchError":
                        raise
                    ctx.note(f"detail error {slug}: {e}")
                    ctx.count("detail_errors")
            itinerant = bool(local and re.search(r"itiner", local, re.I))
            eid = _store(ctx, key=slug, title=title, lang="pt", org=org, city=None if itinerant else "São Paulo",
                         cc=None if itinerant else "BR", date_text=date_text, url=url, ev=ev, dates=dates,
                         desc=(f"local: {local}" if local else None))
            if itinerant:
                db.add_review(ctx.con, "region", "events", eid, "venue country unknown", "Pinacoteca itinerância")
        ctx.con.commit()
    ctx.note("pinacoteca: em cartaz + futuras + first page of passadas (further past items load via JavaScript)")


def collect(ctx):
    fn = {"muac_exposiciones": _muac, "masp_exposicoes": _masp, "malba_exposiciones": _malba,
          "pinacoteca_exposicoes": _pinacoteca}.get(ctx.source_id)
    if fn is None:
        raise RuntimeError(f"no collector for {ctx.source_id}")
    fn(ctx)
