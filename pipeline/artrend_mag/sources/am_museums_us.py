"""US museum exhibition collectors (Americas region): Whitney, New Museum, SFMOMA, Hammer, Guggenheim.

Registry-only rows: moma_web (Cloudflare 403) — MoMA is collected via moma_github elsewhere.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from .. import db
from ..config import iso_now, now_kst
from ._common import classify_subtype, clean_text, jsonld_objects, next_data, parse_date_range, soup, split_title_artist

PARSER_VERSION = "am_museums_us-1"

SOURCES = [
    dict(source_id="whitney_exhibitions", blueprint_data_id="D13", blueprint_org_id="O19",
         name="Whitney Museum of American Art — Exhibitions", owner_group="Whitney Museum of American Art",
         source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="html+jsonld",
         base_url="https://whitney.org", entry_url="https://whitney.org/exhibitions/archive",
         terms_url="https://whitney.org/terms-of-use", text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(html; ExhibitionEvent JSON-LD on detail pages)",
         st_collection_terms="terms page not located",
         st_image_terms="images © artists/Whitney; no open licence stated on exhibition pages",
         max_requests=250),
    dict(source_id="newmuseum_exhibitions", blueprint_data_id="D29", blueprint_org_id="O21",
         name="New Museum — Exhibitions", owner_group="New Museum", source_kind="museum", region_scope="AMERICAS",
         country_codes="US", access_method="sitemap+next_data", base_url="https://www.newmuseum.org",
         entry_url="https://www.newmuseum.org/exhibition-sitemap.xml", terms_url="https://www.newmuseum.org/terms-of-use/",
         text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(html; public sitemap + __NEXT_DATA__ Apollo state)",
         st_collection_terms="terms page not located",
         st_image_terms="images © artists/New Museum; no open licence stated", max_requests=250),
    dict(source_id="sfmoma_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="SFMOMA — Exhibitions", owner_group="San Francisco Museum of Modern Art", source_kind="museum",
         region_scope="AMERICAS", country_codes="US", access_method="html", base_url="https://www.sfmoma.org",
         entry_url="https://www.sfmoma.org/exhibitions/", terms_url=None, text_storage_policy="raw_internal",
         priority="P1", st_official_doc="n/a(html listing, paginated past exhibitions)",
         st_collection_terms="terms page not located", st_image_terms="no open licence stated", max_requests=60),
    dict(source_id="hammer_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Hammer Museum (UCLA) — Exhibitions", owner_group="University of California, Los Angeles",
         source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="html",
         base_url="https://hammer.ucla.edu", entry_url="https://hammer.ucla.edu/exhibitions/all", terms_url=None,
         text_storage_policy="raw_internal", priority="P1",
         st_official_doc="n/a(html; <time datetime> in listing teasers)",
         st_collection_terms="terms page not located", st_image_terms="no open licence stated", max_requests=60),
    dict(source_id="moma_web", blueprint_data_id="D12", blueprint_org_id="O18",
         name="MoMA — website exhibitions", owner_group="The Museum of Modern Art", source_kind="museum",
         region_scope="AMERICAS", country_codes="US", access_method="html", base_url="https://www.moma.org",
         entry_url="https://www.moma.org/calendar/exhibitions", terms_url="https://www.moma.org/about/about-this-site",
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="not reviewed (site blocked)", st_image_terms="not reviewed (site blocked)",
         disabled="Cloudflare challenge / HTTP 403 for non-browser clients (checked 2026-10-27); MoMA exhibition "
                  "history is covered by moma_github",
         notes="disabled: Cloudflare 403 (checked 2026-10-27); covered by moma_github",
         operational_state="blocked_access", robots_status="unknown(blocked before robots)",
         st_live_response="blocked(HTTP 403 Cloudflare)"),
]

# ---------------------------------------------------------------------------------------------- helpers
def _known(ctx, key):
    row = ctx.con.execute("SELECT end_date FROM events WHERE source_id=? AND source_event_key=?",
                          (ctx.source_id, key)).fetchone()
    return (row is not None), (row["end_date"] if row else None)


def _needs_detail(ctx, key, listing_end=None):
    """initial: always; incremental: unseen keys or events not closed more than 30 days ago."""
    if ctx.mode == "initial":
        return True
    seen, end = _known(ctx, key)
    if not seen:
        return True
    end = end or listing_end
    if not end:
        return True
    cutoff = (now_kst().date() - dt.timedelta(days=30)).isoformat()
    return end[:10] >= cutoff[: len(end[:10])]


def _iso(v):
    return v[:10] if v and re.match(r"\d{4}-\d{2}-\d{2}", v) else None


def _add_artist(ctx, eid, name, ev, method, confidence="high", namespace=None, id_value=None, role="artist"):
    name = clean_text(name)
    if not name:
        return
    etype = "group" if re.search(r"\s(&|and|y|e)\s|collective|collectif|colectivo|coletivo", name, re.I) else "person"
    ent = db.ensure_entity(ctx.con, entity_type=etype, name=name, namespace=namespace or f"src:{ctx.source_id}",
                           id_value=id_value, source_id=ctx.source_id, evidence_id=ev)
    db.add_participant(ctx.con, eid, ent, role, name, ev, method, confidence)


def _title_artist(ctx, eid, title, ev):
    name = split_title_artist(title)
    if name:
        _add_artist(ctx, eid, name, ev, "title_pattern", "medium")
    return 1 if name else None


def _image(ctx, eid, page_url, image_url, basis):
    if image_url:
        db.add_image_rights(ctx.con, source_id=ctx.source_id, event_id=eid, page_url=page_url, image_url=image_url,
                            usage_status="unknown", basis=basis)


# ---------------------------------------------------------------------------------------------- Whitney
WH = "https://whitney.org"
WH_SKIP = {"archive", "the-biennial", "performance"}
WH_IMG = "Whitney exhibition image; rights held by artists/lenders/Whitney; no open licence stated"

SEASON = re.compile(r"\b(spring|summer|fall|autumn|winter)\b", re.I)


def _placeholder(d):
    """Whitney JSON-LD carries internal placeholder dates for unannounced sides (1st of month, far future)."""
    return (not d) or d[8:10] == "01" or d[5:10] == "12-31" or int(d[:4]) > now_kst().year + 2


def _merge_dates(text, ld_s, ld_e):
    """Visible date line wins; JSON-LD day dates fill a side the visible line does not show, unless they look like
    placeholders. Seasons ("Opens Fall 2027", "Through Spring 2027") are stored with year precision."""
    text = text or ""
    if SEASON.search(text) and not re.search(r"\d{1,2},", text):
        y = re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)
        ls = lsp = le = lep = None
        if y and text.lower().startswith("through"):
            le, lep = y[-1], "year"
        elif y:
            ls, lsp = y[0], "year"
    else:
        ls, lsp, le, lep = parse_date_range(text)

    def pick(lv, lp, ld):
        if lp == "day" or (lp == "year" and SEASON.search(text)):
            return lv, lp
        if ld and not _placeholder(ld) and (lv is None or ld.startswith(lv)):
            return ld, "day"
        return lv, lp
    sd, sp = pick(ls, lsp, ld_s)
    ed, ep = pick(le, lep, ld_e)
    return sd, sp, ed, ep


def _whitney(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="Whitney Museum of American Art",
                           namespace=f"src:{ctx.source_id}", id_value="whitney", lang="en", source_id=ctx.source_id,
                           official_url=WH + "/")
    max_pages = 12 if ctx.mode == "initial" else 1
    page, last_page = 1, 1
    items = []
    while page <= max_pages:
        r = ctx.fetch(f"{WH}/exhibitions/archive", params={"page": page} if page > 1 else None)
        s = soup(r.text)
        m = re.findall(r'href="/exhibitions/archive\?page=(\d+)"', r.text)
        last_page = max([int(x) for x in m] + [page])
        n_old = n = 0
        for a in s.select('li.list-item a[href^="/exhibitions/"]'):
            slug = a["href"].split("/exhibitions/")[1].split("?")[0].strip("/")
            if not slug or "/" in slug or slug in WH_SKIP:
                continue
            t = a.select_one(".list-item__title")
            sub = a.select_one(".list-item__subtitle")
            if not t:
                continue
            n += 1
            title = clean_text(t.get_text(" "))
            date_text = clean_text(sub.get_text(" ")) if sub else ""
            items.append((slug, title, date_text, r, page))
            sd, sp, ed, ep = parse_date_range(date_text)
            ys = [int(x) for x in re.findall(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", date_text)]
            if ys and max(ys) < 2023:
                n_old += 1
        ctx.count("fetched", n)
        if n == 0 or (n_old and n_old >= n * 0.5) or page >= last_page:
            break
        page += 1
    ctx.note(f"whitney archive: walked {page}/{last_page} pages (archive goes back to 1931; stopped at <2023)")
    seen = set()
    for slug, title, date_text, r, pg in items:
        if slug in seen:
            continue
        seen.add(slug)
        url = f"{WH}/exhibitions/{slug}"
        ev = ctx.evidence(r, locator=f"archive page={pg} a[href=/exhibitions/{slug}]", excerpt=date_text or None)
        sd, sp, ed, ep = _merge_dates(date_text, None, None)
        city, cc, desc, img = "New York", "US", None, None
        ys = [int(x) for x in re.findall(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", date_text)]
        recent = not ys or max(ys) >= 2025
        if recent and _needs_detail(ctx, slug, ed):
            try:
                dr = ctx.fetch(url)
            except Exception as e:  # FetchError on a single detail
                if type(e).__name__ != "FetchError":
                    raise
                ctx.note(f"detail error {url}: {e}")
                ctx.count("detail_errors")
                dr = None
            if dr is not None:
                for o in jsonld_objects(dr.text):
                    if o.get("@type") == "ExhibitionEvent":
                        sd, sp, ed, ep = _merge_dates(date_text, _iso(o.get("startDate")), _iso(o.get("endDate")))
                        addr = (o.get("location") or {}).get("address") or {}
                        city = addr.get("addressLocality") or city
                        cc = addr.get("addressCountry") or cc
                        desc = clean_text(o.get("description"))[:300] or None
                        img = o.get("image") if isinstance(o.get("image"), str) else None
                        ev = ctx.evidence(dr, locator="ld+json ExhibitionEvent",
                                          excerpt=f"{o.get('startDate')} / {o.get('endDate')}")
                        break
        elif ctx.mode == "incremental":
            # keep stored detail-level data: do not overwrite with listing-only values
            seen_, _ = _known(ctx, slug)
            if seen_:
                ctx.con.execute("UPDATE events SET last_seen_at=? WHERE source_id=? AND source_event_key=?",
                                (iso_now(), ctx.source_id, slug))
                ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
                ctx.count("parsed")
                continue
        is_bien = bool(re.match(r"\d{4}-biennial$", slug))
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug,
            event_type="biennial_edition" if is_bien else "exhibition",
            subtype=None if is_bien else classify_subtype(title),
            title=title, title_lang="en", organizer_entity_id=org, city=city, country_code=cc,
            start_date=sd, start_precision=sp, end_date=ed, end_precision=ep, date_text=date_text or None,
            url=url, description_excerpt=desc, parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        if is_bien:
            _whitney_biennial_artists(ctx, eid, slug)
        else:
            _title_artist(ctx, eid, title, ev)
        _image(ctx, eid, url, img, WH_IMG)
    ctx.con.commit()


def _whitney_biennial_artists(ctx, eid, slug):
    try:
        r = ctx.fetch(f"{WH}/exhibitions/{slug}/art")
    except Exception as e:
        if type(e).__name__ != "FetchError":
            raise
        ctx.note(f"biennial artists page missing for {slug}")
        return
    s = soup(r.text)
    names = [clean_text(h.get_text(" ")) for h in s.select("h3.feature-section__title")]
    ev = ctx.evidence(r, locator="h3.feature-section__title (Exhibition artists)", excerpt=f"{len(names)} artists")
    for n in dict.fromkeys(names):
        _add_artist(ctx, eid, n, ev, "list_markup")
    ctx.note(f"{slug}: {len(names)} biennial artists from /art page")


# ---------------------------------------------------------------------------------------------- New Museum
NM = "https://www.newmuseum.org"
NM_IMG = "New Museum exhibition image; rights held by artists/New Museum; no open licence stated"


def _blocks(blocks):
    for b in blocks or []:
        yield b
        yield from _blocks(b.get("innerBlocks"))


def _newmuseum(ctx):
    import json
    from lxml import etree
    org = db.ensure_entity(ctx.con, entity_type="institution", name="New Museum", namespace=f"src:{ctx.source_id}",
                           id_value="newmuseum", lang="en", source_id=ctx.source_id, official_url=NM + "/")
    r = ctx.fetch(f"{NM}/exhibition-sitemap.xml")
    root = etree.fromstring(r.content, parser=etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [u.findtext("s:loc", namespaces=ns) for u in root.findall("s:url", ns)]
    urls = [u for u in urls if u and re.search(r"/exhibition/[^/]+/?$", u)]
    ctx.count("fetched", len(urls))
    ctx.note(f"newmuseum exhibition sitemap lists {len(urls)} exhibition pages (relaunched site; older shows absent)")
    for i, url in enumerate(urls):
        slug = url.rstrip("/").rsplit("/", 1)[1]
        if not _needs_detail(ctx, slug):
            ctx.con.execute("UPDATE events SET last_seen_at=? WHERE source_id=? AND source_event_key=?",
                            (iso_now(), ctx.source_id, slug))
            ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
            ctx.count("parsed")
            continue
        try:
            dr = ctx.fetch(url)
        except Exception as e:
            if type(e).__name__ != "FetchError":
                raise
            ctx.note(f"detail error {url}: {e}")
            ctx.count("detail_errors")
            continue
        nd = next_data(dr.text) or {}
        ap = ((nd.get("props") or {}).get("pageProps") or {}).get("__APOLLO_STATE__") or {}
        x = next((v for k, v in ap.items() if k.startswith("Exhibition:") and v.get("slug") == slug), None)
        if not x:
            ctx.note(f"no Exhibition node in __NEXT_DATA__: {url}")
            ctx.count("detail_errors")
            continue
        title = clean_text(x.get("title"))
        sd, ed = _iso(x.get("startDate")), _iso(x.get("endDate"))
        override = clean_text(x.get("dateTextOverride"))
        date_text = clean_text(f"{x.get('datePrefix') or ''} {x.get('startDate')} / {x.get('endDate')}")
        sp, ep = ("day" if sd else None), ("day" if ed else None)
        if override:
            date_text = override
            o = parse_date_range(override)
            if o[0]:
                sd, sp = o[0], o[1]
            if o[2]:
                ed, ep = o[2], o[3]
            elif re.search(r"ongoing|continuous|\b(spring|summer|fall|autumn|winter)\b", override, re.I):
                ed, ep = None, None
        ev = ctx.evidence(dr, locator=f"__NEXT_DATA__ Exhibition slug={slug}", excerpt=date_text)
        cards = []
        for b in _blocks(x.get("blocks")):
            if b.get("name") == "new-museum-blocks/artist-card":
                try:
                    a = json.loads(b.get("attributesJSON") or "{}")
                except ValueError:
                    continue
                n = clean_text(a.get("artistName"))
                if n:
                    cards.append((n, clean_text(re.sub("<[^>]+>", " ", a.get("byline") or ""))))
        is_tri = "triennial" in slug and "triennial" in title.lower()
        img = (((x.get("featuredImage") or {}).get("node")) or {}).get("sourceUrl")
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug,
            event_type="biennial_edition" if is_tri else "exhibition",
            subtype=None if is_tri else classify_subtype(title, len(cards) or None),
            title=title, title_lang="en", organizer_entity_id=org, city="New York", country_code="US",
            start_date=sd, start_precision=sp, end_date=ed, end_precision=ep, date_text=date_text,
            url=url, description_excerpt=clean_text(x.get("exhibitionIntro")) or None,
            parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        for n, byline in cards:
            etype = "group" if re.match(r"\(?\s*(founded|est\.|established)", byline, re.I) else "person"
            ent = db.ensure_entity(ctx.con, entity_type=etype, name=n, namespace=f"src:{ctx.source_id}",
                                   source_id=ctx.source_id, evidence_id=ev)
            db.add_participant(ctx.con, eid, ent, "artist", n, ev, "structured_field")
        if not cards:
            _title_artist(ctx, eid, title, ev)
        _image(ctx, eid, url, img, NM_IMG)
        if i % 20 == 0:
            ctx.con.commit()
    ctx.con.commit()


# ---------------------------------------------------------------------------------------------- SFMOMA
SF = "https://www.sfmoma.org"


def _sfmoma(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="San Francisco Museum of Modern Art",
                           namespace=f"src:{ctx.source_id}", id_value="sfmoma", lang="en", source_id=ctx.source_id,
                           official_url=SF + "/")
    max_pg = 15 if ctx.mode == "initial" else 1
    seen, pg, last = set(), 1, 1
    while True:
        r = ctx.fetch(f"{SF}/exhibitions/", params={"pg-exhibitions-past": pg} if pg > 1 else None)
        last = max([int(x) for x in re.findall(r"pg-exhibitions-past=(\d+)", r.text)] + [pg])
        s = soup(r.text)
        items = s.select("a.exhibitionsgrid-wrapper-grid-item[href]")
        ctx.count("fetched", len(items))
        years = []
        for a in items:
            m = re.search(r"/exhibition/([^/?#]+)/?", a["href"])
            t = a.select_one(".exhibitionsgrid-wrapper-grid-item-text-title")
            if not m or not t:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            title = clean_text(t.get_text(" "))
            dnode = a.select_one(".exhibitionsgrid-wrapper-grid-item-text-date")
            date_text = clean_text(dnode.get_text(" ")) if dnode else ""
            loc = a.select_one(".exhibitionsgrid-wrapper-grid-item-location")
            loc = clean_text(loc.get_text(" ")) if loc else None
            sd, sp, ed, ep = parse_date_range(date_text)
            if sd:
                years.append(int(sd[:4]))
            img = a.select_one("img[src]")
            ev = ctx.evidence(r, locator=f"a.exhibitionsgrid-wrapper-grid-item[href*=/exhibition/{slug}/] pg={pg}",
                              excerpt=date_text or None)
            url = f"{SF}/exhibition/{slug}/"
            eid = db.upsert_event(
                ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug, event_type="exhibition",
                subtype=classify_subtype(title), title=title, title_lang="en", organizer_entity_id=org,
                city="San Francisco", country_code="US", start_date=sd, start_precision=sp, end_date=ed,
                end_precision=ep, date_text=date_text or None, url=url,
                description_excerpt=(f"location: {loc}" if loc else None), parser_version=PARSER_VERSION, evidence_id=ev)
            ctx.count("parsed")
            _title_artist(ctx, eid, title, ev)
            _image(ctx, eid, url, img["src"] if img else None,
                   "SFMOMA exhibition image; rights held by artists/SFMOMA; no open licence stated")
        ctx.con.commit()
        if pg >= min(max_pg, last) or (years and max(years) < 2023):
            break
        pg += 1
    ctx.note(f"sfmoma: walked past-exhibitions pagination {pg}/{last}")


# ---------------------------------------------------------------------------------------------- Hammer
HM = "https://hammer.ucla.edu"


def _hammer(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="Hammer Museum", namespace=f"src:{ctx.source_id}",
                           id_value="hammer", lang="en", source_id=ctx.source_id, official_url=HM + "/")
    max_pg = 10 if ctx.mode == "initial" else 1
    pages = [(f"{HM}/exhibitions/on-view", None), (f"{HM}/exhibitions/upcoming", None)]
    pages += [(f"{HM}/exhibitions/all", {"page": i}) for i in range(max_pg)]
    seen = set()
    for url, params in pages:
        try:
            r = ctx.fetch(url, params=params)
        except Exception as e:
            if type(e).__name__ != "FetchError":
                raise
            ctx.note(f"listing error {url} {params}: {e}")
            break
        s = soup(r.text)
        arts = s.select("article.node--type-exhibition[about]")
        ctx.count("fetched", len(arts))
        years = []
        for art in arts:
            key = art["about"].strip("/")
            if not key.startswith("exhibitions/") or key in seen:
                continue
            seen.add(key)
            t = art.select_one(".result-item__title") or art.select_one(".field--name-title") or art.find(["h2", "h3", "h4"])
            if not t:
                continue
            title = clean_text(t.get_text(" "))
            times = [x.get("datetime") for x in art.select(".field--name-field-recurring-date time[datetime]")][:2]
            dline = art.select_one(".occurrence")
            date_text = clean_text(re.sub(r"This is a past exhibition", "", dline.get_text(" "))) if dline else ""
            sd = _iso(times[0]) if times else None
            ed = _iso(times[1]) if len(times) > 1 else None
            if sd:
                years.append(int(sd[:4]))
            cat = art.select_one(".category")
            cat = clean_text(cat.get_text(" ")) if cat else ""
            is_bien = bool(re.match(r"made in l\.a\. \d{4}\b", title, re.I))
            ev = ctx.evidence(r, locator=f"article[about=/{key}] time[datetime]", excerpt=date_text or None)
            page_url = f"{HM}/{key}"
            eid = db.upsert_event(
                ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=key,
                event_type="biennial_edition" if is_bien else "exhibition",
                subtype=None if is_bien else ("collection_display" if "collection" in cat.lower() else classify_subtype(title)),
                title=title, title_lang="en", organizer_entity_id=org, city="Los Angeles", country_code="US",
                start_date=sd, start_precision="day" if sd else None, end_date=ed, end_precision="day" if ed else None,
                date_text=date_text or None, url=page_url, description_excerpt=(f"category: {cat}" if cat else None),
                parser_version=PARSER_VERSION, evidence_id=ev)
            ctx.count("parsed")
            if not is_bien:
                _title_artist(ctx, eid, re.sub(r"^Hammer Projects:\s*", "", title), ev)
        ctx.con.commit()
        if params and years and max(years) < 2023:
            break
    ctx.note("hammer: on-view + upcoming + /exhibitions/all pagination (stops before 2023)")


# ---------------------------------------------------------------------------------------------- dispatch
def collect(ctx):
    fn = {"whitney_exhibitions": _whitney, "newmuseum_exhibitions": _newmuseum, "sfmoma_exhibitions": _sfmoma, "hammer_exhibitions": _hammer}.get(ctx.source_id)
    if fn is None:
        raise RuntimeError(f"no collector for {ctx.source_id}")
    fn(ctx)
