"""Americas programs: Bienal de São Paulo (feed + edition participants), NADA fairs, public rendered Guggenheim
New York exhibitions, and blocked/not-attempted registry rows."""
from __future__ import annotations

import re
import urllib.parse
from urllib.parse import urljoin

from .. import db
from ..config import now_kst
from ..http import FetchError
from ._common import clean_text, parse_date_range, parse_feed, soup
from ..render_public import RenderUnavailable, render_public

PARSER_VERSION = "am_programs-2"

SOURCES = [
    dict(source_id="bienal_sp", blueprint_data_id="D20", blueprint_org_id=None,
         name="Fundação Bienal de São Paulo — news feed + edition participants",
         owner_group="Fundação Bienal de São Paulo", source_kind="biennial", region_scope="AMERICAS",
         country_codes="BR", access_method="rss+html", base_url="https://bienal.org.br",
         entry_url="https://bienal.org.br/feed/", terms_url=None, text_storage_policy="raw_internal", priority="P0",
         st_official_doc="n/a(WordPress RSS feed)", st_collection_terms="terms page not located",
         st_image_terms="image credits shown per photo (© photographer / Fundação Bienal); no open licence stated",
         max_requests=40),
    dict(source_id="nada_fairs", blueprint_data_id="D25", blueprint_org_id=None,
         name="NADA (New Art Dealers Alliance) — fairs", owner_group="New Art Dealers Alliance", source_kind="fair",
         region_scope="AMERICAS", country_codes="US", access_method="html", base_url="https://www.newartdealers.org",
         entry_url="https://www.newartdealers.org/fairs", terms_url=None, text_storage_policy="raw_internal",
         priority="P1", st_official_doc="n/a(html; exhibitor list is rendered client-side and not collected)",
         st_collection_terms="terms page not located", st_image_terms="no open licence stated", max_requests=30),
    dict(source_id="ngc_canada", blueprint_data_id=None, blueprint_org_id="O24",
         name="National Gallery of Canada — exhibitions", owner_group="National Gallery of Canada",
         source_kind="museum", region_scope="AMERICAS", country_codes="CA", access_method="html",
         base_url="https://www.gallery.ca", entry_url="https://www.gallery.ca/whats-on/exhibitions-and-galleries",
         terms_url=None, text_storage_policy="raw_internal", priority="P2", st_official_doc="n/a(html)",
         st_collection_terms="not reviewed (site blocked)", st_image_terms="not reviewed (site blocked)",
         disabled="HTTP 403 for non-browser clients (checked 2026-10-27)",
         notes="disabled: HTTP 403 (checked 2026-10-27)",
         operational_state="blocked_access", robots_status="unknown(blocked)", st_live_response="blocked(HTTP 403)"),
    dict(source_id="guggenheim_exhibitions", blueprint_data_id=None, blueprint_org_id=None,
         name="Solomon R. Guggenheim Museum — exhibitions", owner_group="Solomon R. Guggenheim Foundation",
         source_kind="museum", region_scope="AMERICAS", country_codes="US", access_method="html+playwright",
         base_url="https://www.guggenheim.org", entry_url="https://www.guggenheim.org/exhibitions",
         terms_url="https://www.guggenheim.org/terms-conditions", text_storage_policy="raw_internal", priority="P2",
         st_official_doc="n/a(html)",
         st_collection_terms="Terms allow personal non-commercial/fair-use and limited press use; publication/reuse beyond those "
                             "limits requires permission; no crawler clause observed",
         st_image_terms="images are not collected; permission/licensing required for reuse",
         notes="Public listing rendered with ordinary Chromium and project USER_AGENT; public past page traversed once; "
               "only Guggenheim New York listing/events are collected; publication permission may be required",
         max_requests=140),
]

_PT_ABBR = {"jan": "janeiro", "fev": "fevereiro", "mar": "março", "abr": "abril", "mai": "maio", "jun": "junho",
            "jul": "julho", "ago": "agosto", "set": "setembro", "out": "outubro", "nov": "novembro", "dez": "dezembro"}


def _pt_dates(text):
    t = re.sub(r"\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\b\.?", lambda m: _PT_ABBR[m.group(1).lower()],
               text, flags=re.I)
    return parse_date_range(t)


# ---------------------------------------------------------------------------------------------- Bienal de São Paulo
BSP = "https://bienal.org.br"
# Editions whose official participant-announcement page is known (one request each).
BSP_EDITIONS = [
    dict(key="36", url=f"{BSP}/conheca-os-artistas-participantes-da-36a-bienal-de-sao-paulo/",
         list_intro=r"Os artistas participantes da 36ª Bienal de São Paulo são:"),
]


def _bienal(ctx):
    org = db.ensure_entity(ctx.con, entity_type="biennial", name="Fundação Bienal de São Paulo",
                           namespace=f"src:{ctx.source_id}", id_value="fundacao_bienal", lang="pt",
                           source_id=ctx.source_id, official_url=BSP + "/")
    # 1) news feed -> articles (WordPress feed pagination via ?paged=N)
    max_pages = 8 if ctx.mode == "initial" else 1
    oldest = None
    for page in range(1, max_pages + 1):
        try:
            r = ctx.fetch(f"{BSP}/feed/", params={"paged": page} if page > 1 else None)
        except Exception as e:
            if type(e).__name__ != "FetchError":
                raise
            break  # past the last feed page (404)
        items = parse_feed(r.content)
        ctx.count("fetched", len(items))
        if not items:
            break
        for it in items:
            cats = [c for c in it["categories"] if c]
            low = " ".join(cats).lower()
            atype = "interview" if "entrevista" in low else "announcement"
            db.upsert_article(ctx.con, ctx.stats, source_id=ctx.source_id, canonical_url=it["link"], title=it["title"],
                              published_at=it["published"], author_text=it["author"] or None,
                              publisher="Fundação Bienal de São Paulo", owner_group="Fundação Bienal de São Paulo",
                              article_type=atype, type_basis=f"feed category ({'; '.join(cats) or 'none'})"
                              if cats else "institutional news feed", lang="pt",
                              categories="; ".join(cats) or None, excerpt=it["summary"] or None)
            ctx.count("parsed")
            if it["published"]:
                oldest = min(oldest or it["published"], it["published"])
        ctx.con.commit()
        if oldest and oldest[:10] < "2023-01-01":
            break
    ctx.note(f"bienal feed walked back to {oldest[:10] if oldest else '?'}")
    # 2) edition participant announcement pages -> biennial_edition + participants
    for ed in BSP_EDITIONS:
        seen = ctx.con.execute("SELECT 1 FROM events WHERE source_id=? AND source_event_key=?",
                               (ctx.source_id, ed["key"])).fetchone()
        if seen and ctx.mode == "incremental":
            continue  # participant list pages are static announcements
        _bienal_edition(ctx, org, ed)
    ctx.con.commit()


def _bienal_edition(ctx, org, ed):
    r = ctx.fetch(ed["url"])
    s = soup(r.text)
    body = s.select_one(".entry-content, .post-content, article") or s
    lines = [clean_text(x) for x in body.get_text("\n").split("\n") if clean_text(x)]
    full = "\n".join(lines)
    # Serviço block: "36ª Bienal de São Paulo –" / subtitle / curators / "6 set 2025 – 11 jan 2026" / venue
    title, date_line, curators_line, venue = None, None, None, None
    if "Serviço" in lines:
        i = lines.index("Serviço")
        blk = lines[i + 1:i + 8]
        title = clean_text(" ".join(blk[:2]).rstrip("–").strip())
        for x in blk:
            if re.search(r"curador", x, re.I) and not curators_line:
                curators_line = x
            elif re.search(r"\d{4}", x) and re.search(r"[–-]", x) and not date_line:
                date_line = x
            elif x.lower().startswith("pavilhão") and not venue:
                venue = x
    title = title or clean_text((s.find("h1") or s.title).get_text())
    sd, sp, edd, ep = _pt_dates(date_line or "")
    ev = ctx.evidence(r, locator="Serviço block + participant list paragraph", excerpt=date_line)
    eid = db.upsert_event(
        ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=ed["key"], event_type="biennial_edition",
        title=title, title_lang="pt", organizer_entity_id=org, city="São Paulo", country_code="BR",
        start_date=sd, start_precision=sp, end_date=edd, end_precision=ep, date_text=date_line, url=ed["url"],
        description_excerpt=(f"venue: {venue}" if venue else None), parser_version=PARSER_VERSION, evidence_id=ev)
    ctx.count("parsed")
    names = []
    m = re.search(re.escape(ed["list_intro"]) + r"\n(.+)", full)
    if m:
        names += [n for n in m.group(1).split(";")]
    m2 = re.search(r"Outros \w+ participantes integram.*?:\s*([^\n]+)", full, re.S)
    if m2:
        names += m2.group(1).split(";")
    n_art = 0
    for n in dict.fromkeys(clean_text(x).rstrip(".") for x in names):
        if not n or len(n) > 80:
            continue
        etype = "group" if (n.isupper() and len(n) > 3) or re.search(r"\b(coletivo|collective|instituto|boxe)\b|\s(&|e)\s", n, re.I) else "person"
        ent = db.ensure_entity(ctx.con, entity_type=etype, name=n, namespace=f"src:{ctx.source_id}",
                               source_id=ctx.source_id, evidence_id=ev)
        db.add_participant(ctx.con, eid, ent, "artist", n, ev, "list_markup")
        n_art += 1
    if curators_line:
        for part in curators_line.split("/"):
            if ":" not in part:
                continue
            label, who = part.split(":", 1)
            if not re.search(r"curador", label, re.I):
                continue  # e.g. communication consultant: not a curator
            for n in re.split(r",| e ", who):
                n = clean_text(n)
                if n:
                    ent = db.ensure_entity(ctx.con, entity_type="person", name=n, namespace=f"src:{ctx.source_id}",
                                           source_id=ctx.source_id, evidence_id=ev)
                    db.add_participant(ctx.con, eid, ent, "curator", n, ev, "list_markup")
    ctx.note(f"bienal edition {ed['key']}: {n_art} artists from announcement page")


# ---------------------------------------------------------------------------------------------- NADA
NADA = "https://www.newartdealers.org"


def _nada(ctx):
    org = db.ensure_entity(ctx.con, entity_type="fair", name="New Art Dealers Alliance (NADA)",
                           namespace=f"src:{ctx.source_id}", id_value="nada", lang="en", source_id=ctx.source_id,
                           official_url=NADA + "/")
    r = ctx.fetch(f"{NADA}/fairs")
    slugs = list(dict.fromkeys(re.findall(r'href="(?:https://www\.newartdealers\.org)?/fairs/([a-z0-9-]+-(\d{4}))"', r.text)))
    min_year = 2023 if ctx.mode == "initial" else now_kst().year - 1
    slugs = [sl for sl, y in slugs if int(y) >= min_year]
    ctx.count("fetched", len(slugs))
    ctx.note(f"nada /fairs lists {len(slugs)} fair pages since {min_year}")
    for slug in slugs:
        try:
            dr = ctx.fetch(f"{NADA}/fairs/{slug}")
        except Exception as e:
            if type(e).__name__ != "FetchError":
                raise
            ctx.note(f"detail error {slug}: {e}")
            ctx.count("detail_errors")
            continue
        s = soup(dr.text)
        h1 = s.find("h1")
        title = clean_text((h1 or s.title).get_text(" ")).replace(" – New Art Dealers Alliance", "")
        text = clean_text(s.get_text(" "))
        m = re.search(r"to take place\s+(.{4,60}?\d{4})\s+at\s+(.{3,80}?)\s*\.", text)
        date_text, venue = (clean_text(m.group(1)), clean_text(m.group(2))) if m else (None, None)
        if not date_text:
            m = re.search(rf"{re.escape(title)}\s+((?:[A-Z][a-z]+\s+\d{{1,2}}\s*[–-]\s*(?:[A-Z][a-z]+\s+)?\d{{1,2}},\s*\d{{4}}))", text)
            date_text = clean_text(m.group(1)) if m else None
        # "December 1–5, 2026" (same-month range) -> "December 1, 2026 – December 5, 2026" for the shared parser
        dnorm = re.sub(r"^([A-Za-z]+)\s+(\d{1,2})\s*[–-]\s*(\d{1,2}),\s*(\d{4})$", r"\1 \2, \4 – \1 \3, \4",
                       date_text or "")
        sd, sp, ed, ep = parse_date_range(dnorm)
        low = slug.lower()
        city, cc = ({"miami": ("Miami", "US"), "new-york": ("New York", "US"),
                     "foreland": ("Catskill", "US"), "mexico": ("Mexico City", "MX"), "paris": ("Paris", "FR")}
                    .get(next((k for k in ("miami", "new-york", "foreland", "mexico", "paris") if k in low), ""), (None, None)))
        ev = ctx.evidence(dr, locator="intro paragraph 'to take place <dates> at <venue>'", excerpt=date_text)
        eid = db.upsert_event(
            ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=slug, event_type="fair_edition",
            title=title, title_lang="en", organizer_entity_id=org, city=city, country_code=cc,
            start_date=sd, start_precision=sp, end_date=ed, end_precision=ep, date_text=date_text,
            url=f"{NADA}/fairs/{slug}", description_excerpt=(f"venue: {venue}" if venue else None),
            parser_version=PARSER_VERSION, evidence_id=ev)
        ctx.count("parsed")
        if cc is None:
            db.add_review(ctx.con, "region", "events", eid, "venue country unknown", slug)
    ctx.con.commit()


def collect(ctx):
    fn = {"bienal_sp": _bienal, "nada_fairs": _nada,
          "guggenheim_exhibitions": _guggenheim}.get(ctx.source_id)
    if fn is None:
        raise RuntimeError(f"no collector for {ctx.source_id}")
    fn(ctx)


GUGGENHEIM = "https://www.guggenheim.org"
GUGGENHEIM_LISTING = f"{GUGGENHEIM}/exhibitions"


def _guggenheim(ctx):
    org = db.ensure_entity(ctx.con, entity_type="institution", name="Solomon R. Guggenheim Museum",
                           namespace=f"src:{ctx.source_id}", id_value="solomon-r-guggenheim-museum",
                           source_id=ctx.source_id, official_url=f"{GUGGENHEIM}/")
    try:
        rendered = render_public(ctx, GUGGENHEIM_LISTING, ready_selector="#exhibitions-on-view",
                                 max_subrequests=50)
    except RenderUnavailable as exc:
        ctx.note(f"optional public renderer unavailable: {exc}")
        raise FetchError(str(exc)) from exc

    pages = [(rendered, "listing")]
    listing_soup = soup(rendered.text)
    past_url = _guggenheim_past_url(listing_soup, rendered.url)
    if past_url and past_url != rendered.url:
        try:
            archive = render_public(ctx, past_url, ready_selector="main", max_subrequests=50)
            pages.append((archive, "public past page (first page only)"))
        except FetchError as exc:
            ctx.note(f"public past page unavailable: {exc}")

    seen = set()
    oldest = None
    observed_past = False
    for response, page_label in pages:
        records, venue = _guggenheim_events(response.text, response.url)
        observed_past = observed_past or any(item["section"] == "Past Exhibitions" for item in records)
        ctx.count("fetched", len(records))
        for item in records:
            if item["slug"] in seen:
                continue
            seen.add(item["slug"])
            date_text = item["date_text"]
            start, start_precision, end, end_precision = parse_date_range(date_text)
            if date_text and date_text.casefold() == "ongoing":
                start = start_precision = end = end_precision = None
            evidence_excerpt = f"{date_text or 'date not stated'} | {venue or 'venue country unknown'}"
            evidence = ctx.evidence(
                response,
                locator=f"rendered {page_label} section={item['section']} card={item['slug']}; footer address",
                excerpt=evidence_excerpt)
            event_id = db.upsert_event(
                ctx.con, ctx.stats, source_id=ctx.source_id, source_event_key=item["slug"],
                event_type="exhibition", title=item["title"], title_lang="en", organizer_entity_id=org,
                city="New York" if venue else None, country_code="US" if venue else None,
                start_date=start, start_precision=start_precision, end_date=end, end_precision=end_precision,
                date_text=date_text, url=item["url"], evidence_id=evidence, parser_version=PARSER_VERSION)
            if item["image_url"]:
                db.add_image_rights(
                    ctx.con, source_id=ctx.source_id, event_id=event_id, page_url=response.url,
                    image_url=item["image_url"], usage_status="unknown",
                    basis="Guggenheim page image; no open licence stated and publication permission may be required; not downloaded")
            if not venue:
                db.add_review(ctx.con, "region", "events", event_id,
                              "venue country unknown", "rendered event listing lacks the New York museum address")
            ctx.count("parsed")
            if start and (oldest is None or start < oldest):
                oldest = start
        ctx.con.commit()

    history = "public past page first page captured" if len(pages) > 1 else "no separately linked public past page captured"
    ctx.note(f"Guggenheim New York: {len(seen)} unique public exhibition cards; {history}; "
             f"Past Exhibitions section observed={observed_past}; oldest parsed start={oldest or 'unknown'}. "
             "No mixed-city sitemap or private/custom endpoint traversed.")


def _guggenheim_events(html, page_url):
    page = soup(html)
    venue = _guggenheim_venue(page)
    records, seen = [], set()
    for section in page.find_all("section"):
        section_id = section.get("id") or ""
        heading = section.find(["h2", "h3"])
        heading_text = clean_text(heading.get_text(" ")) if heading else ""
        if section_id == "exhibitions-on-view" or heading_text.casefold() == "exhibitions on view":
            section_name = "Exhibitions On View"
        elif section_id == "upcoming-exhibitions" or heading_text.casefold() == "upcoming exhibitions":
            section_name = "Upcoming Exhibitions"
        elif section_id == "past-exhibitions" or heading_text.casefold() == "past exhibitions":
            section_name = "Past Exhibitions"
        else:
            continue
        for card in section.find_all("article"):
            link = next((anchor for anchor in card.find_all("a", href=True)
                         if re.fullmatch(r"/exhibition/[^/?#]+/?", urllib.parse.urlsplit(anchor["href"]).path)), None)
            if not link:
                continue
            path = urllib.parse.urlsplit(link["href"]).path.rstrip("/")
            slug = path.rsplit("/", 1)[-1]
            if not slug or slug in seen:
                continue
            heading_node = card.find(["h2", "h3", "h4"])
            title = clean_text(heading_node.get_text(" ")) if heading_node else clean_text(link.get_text(" "))
            date_node = card.find("time")
            date_text = clean_text(date_node.get_text(" ")) if date_node else None
            if not date_text:
                ongoing = next((node for node in card.find_all(["span", "p"])
                                if clean_text(node.get_text(" ")).casefold() == "ongoing"), None)
                date_text = clean_text(ongoing.get_text(" ")) if ongoing else None
            image = card.find("img")
            image_url = None
            if image:
                source = image.get("src") or image.get("data-src") or image.get("srcset")
                if source and source.startswith("data:"):
                    source = image.get("srcset") or image.get("data-src")
                if source:
                    source = source.split(",", 1)[0].split()[0]
                    if not source.startswith("data:"):
                        image_url = urljoin(page_url, source)
            if not title:
                continue
            seen.add(slug)
            records.append({
                "slug": slug, "title": title, "date_text": date_text,
                "section": section_name, "image_url": image_url,
                "url": urljoin(page_url, link["href"]),
            })
    return records, venue


def _guggenheim_venue(page):
    footer = page.find("footer")
    text = clean_text(footer.get_text(" ")) if footer else ""
    if "1071 Fifth Avenue" in text and re.search(r"New York,\s*NY\s*10128", text, re.I):
        return "1071 Fifth Avenue, New York, NY 10128"
    return None


def _guggenheim_past_url(page, page_url):
    for link in page.find_all("a", href=True):
        path = urllib.parse.urlsplit(link["href"]).path.rstrip("/")
        if path == "/exhibitions/past":
            return urljoin(page_url, link["href"])
    return None
