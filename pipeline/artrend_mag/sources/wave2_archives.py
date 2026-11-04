"""Collection metadata from verified public API evidence for Wave 2 archives."""
from __future__ import annotations

from .. import db
from ..http import FetchError
from ._common import clean_text

PARSER_VERSION = "wave2-archives-1"
AIC_SOURCE_ID = "aic_collection_api"
EUROPEANA_SOURCE_ID = "wave2_europeana_api"
ARTUK_SOURCE_ID = "wave2_artuk_collection"
RKD_SOURCE_ID = "wave2_rkd_research"
AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"
AIC_DOCS = "https://api.artic.edu/docs/"
AIC_FIELDS = ",".join((
    "id", "title", "artist_id", "artist_title", "date_start", "date_end", "date_display",
    "medium_display", "dimensions", "classification_title", "artwork_type_title", "department_title",
    "place_of_origin", "main_reference_number", "api_link", "is_public_domain", "credit_line",
    "copyright_notice",
))
# A robots lookup uses one request, leaving at most 249 API pages under the 250-request cap.
MAX_PAGES = 249

SOURCES = [
    dict(
        source_id=AIC_SOURCE_ID, blueprint_data_id=None, blueprint_org_id=None,
        name="Art Institute of Chicago — collection artworks API",
        owner_group="Art Institute of Chicago", source_kind="museum", region_scope="AMERICAS",
        country_codes="US", access_method="api", base_url="https://api.artic.edu",
        entry_url=AIC_SEARCH, terms_url="https://api.artic.edu/docs/#terms",
        text_storage_policy="raw_internal", priority="P1", api_policy_url=AIC_DOCS,
        extra_headers={"AIC-User-Agent": "ARTREND art magazine research"},
        min_interval=3, max_requests=250,
        notes=("Sourcebook 미주-09-002. Bounded to works with date_start >= 2015 as in the saved public probe; "
               "this is not a complete historical collection export. Stable artist IDs are used only when supplied "
               "with the artist title on the official artwork record; no images are fetched."),
    ),
    dict(
        source_id=EUROPEANA_SOURCE_ID, blueprint_data_id=None, blueprint_org_id=None,
        name="Europeana — collection API (key required)", owner_group="Europeana Foundation",
        source_kind="api", region_scope="EUROPE", access_method="api",
        base_url="https://api.europeana.eu", entry_url="https://api.europeana.eu/en",
        terms_url=None, text_storage_policy="metadata_only", priority="P2", max_requests=0,
        notes=("Sourcebook 유럽-09-001. Saved official API landing page says a free API key is requested and requires "
               "a free Europeana account; no API endpoint was called."),
        disabled=("Official API page requires a requested API key and a free Europeana account; no credentials "
                  "available (verified from saved project evidence 2026-10-28)."),
        operational_state="blocked_credentials",
        robots_status=("not evaluated: saved /robots.txt request redirected to the official API landing page, "
                       "not machine-readable robots rules"),
        st_official_doc="ok(saved official Europeana APIs landing page; free key and account stated)",
        st_live_response="ok(API information page only; collection API not requested)",
        st_collection_terms="not assessed (key required; no collection API request)",
        st_image_terms="not assessed (no images fetched)",
    ),
    dict(
        source_id=ARTUK_SOURCE_ID, blueprint_data_id=None, blueprint_org_id=None,
        name="Art UK collection search", owner_group="Art UK",
        source_kind="museum", region_scope="EUROPE", access_method="html",
        base_url="https://artuk.org", entry_url="https://artuk.org/", terms_url=None,
        text_storage_policy="metadata_only", priority="P2", max_requests=0,
        notes=("Sourcebook 유럽-09-002. Fetcher received HTTP 403 from robots.txt and refused the homepage; "
               "no retry, bypass, or page request was made (2026-10-28)."),
        disabled="robots.txt returned HTTP 403 to the project Fetcher; robots permission could not be established (checked 2026-10-28)",
        operational_state="blocked_access", robots_status="robots_http_403(not_crawled)",
        st_official_doc="not reached (robots HTTP 403)",
        st_live_response="not_requested(robots HTTP 403)",
        st_collection_terms="not reached (robots HTTP 403)",
        st_image_terms="not assessed (no image request)",
    ),
    dict(
        source_id=RKD_SOURCE_ID, blueprint_data_id=None, blueprint_org_id=None,
        name="RKD Research — linked visual-documentation portal",
        owner_group="RKD — Netherlands Institute for Art History", source_kind="museum",
        region_scope="EUROPE", access_method="html", base_url="https://research.rkd.nl",
        entry_url="https://research.rkd.nl/", terms_url="https://www.rkd.nl/en/copyright",
        text_storage_policy="metadata_only", priority="P2", max_requests=0,
        notes=("Sourcebook 유럽-09-003. Official RKD visual-documentation page links to RKD Research as its "
               "search portal; Fetcher could not evaluate research.rkd.nl robots.txt (HTTP 403), so the portal "
               "homepage was not requested (2026-10-28). No retry or bypass."),
        disabled=("Officially linked research.rkd.nl returned HTTP 403 for robots.txt; robots permission could not "
                  "be established, so no research portal request was made (checked 2026-10-28)."),
        operational_state="blocked_access", robots_status="robots_http_403(not_crawled)",
        st_official_doc="ok(link from public RKD visual-documentation page; no API documentation verified)",
        st_live_response="not_requested(robots HTTP 403)",
        st_collection_terms=("RKD copyright page states republication/distribution requires prior consent and "
                             "commercial TDM copies of protected works are prohibited"),
        st_image_terms="permission required for republication of protected artwork images",
    ),
]


def collect(ctx):
    if ctx.source_id != AIC_SOURCE_ID:
        raise ValueError(f"{ctx.source_id}: disabled or unknown source")

    params = {
        "query[range][date_start][gte]": "2015",
        "limit": 100,
        "page": 1,
        "fields": AIC_FIELDS,
    }
    response = ctx.fetch(AIC_SEARCH, params=params, accept="application/json")
    evidence_id = ctx.evidence(response, locator="artworks/search date_start>=2015 page=1")
    records, total_pages = _page(response, 1)
    if total_pages > MAX_PAGES:
        raise FetchError(
            f"AIC artwork query returned {total_pages} pages; configured request budget allows at most {MAX_PAGES}"
        )

    holding = db.ensure_entity(
        ctx.con, entity_type="institution", name="Art Institute of Chicago", namespace="wikidata",
        id_value="Q239303", lang="en", source_id=ctx.source_id, official_url="https://www.artic.edu/",
    )
    seen_ids = set()
    _store_page(ctx, 1, records, seen_ids, holding, evidence_id)
    ctx.con.commit()

    for page in range(2, total_pages + 1):
        response = ctx.fetch(AIC_SEARCH, params={**params, "page": page}, accept="application/json")
        evidence_id = ctx.evidence(response, locator=f"artworks/search date_start>=2015 page={page}")
        records, _ = _page(response, page, expected_pages=total_pages)
        _store_page(ctx, page, records, seen_ids, holding, evidence_id)
        ctx.con.commit()

    ctx.note(
        f"Collected all pages in the verified AIC query scope date_start >= 2015 ({len(seen_ids)} unique artworks); "
        "older or undated works are outside scope. Dimensions and other fields without normalized DB columns remain "
        "in page evidence; no images or exhibition activity were collected."
    )
    ctx.con.commit()


def _page(response, expected_page, expected_pages=None):
    try:
        payload = response.json()
        data = payload["data"]
        pagination = payload["pagination"]
        current_page = pagination["current_page"]
        total_pages = pagination["total_pages"]
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"invalid AIC artwork search response for page {expected_page}: {exc}") from exc

    if not isinstance(data, list) or not isinstance(current_page, int) or not isinstance(total_pages, int):
        raise FetchError(f"invalid AIC artwork pagination values for page {expected_page}")
    if current_page != expected_page or total_pages < 0:
        raise FetchError(f"unexpected AIC artwork pagination page={current_page}, total={total_pages}")
    if expected_pages is not None and total_pages != expected_pages:
        raise FetchError("AIC artwork pagination changed during collection")
    return data, total_pages


def _store_page(ctx, page, records, seen_ids, holding_entity_id, evidence_id):
    ctx.count("fetched", len(records))
    for record in records:
        if not isinstance(record, dict):
            raise FetchError(f"AIC artwork page {page} contains a non-record value")
        object_id = _numeric_id(record.get("id"), f"AIC artwork page {page} record ID")
        if object_id in seen_ids:
            continue
        seen_ids.add(object_id)
        artist_entity_id = _artist_entity(ctx, record, evidence_id)
        acquisition = _acquisition_text(record)
        db.upsert_work(
            ctx.con, ctx.stats, id_namespace="aic", id_value=object_id, source_id=ctx.source_id,
            artist_entity_id=artist_entity_id, title=clean_text(record.get("title") or "") or None,
            date_text=clean_text(record.get("date_display") or "") or None,
            medium=clean_text(record.get("medium_display") or "") or None,
            classification=(clean_text(record.get("classification_title") or "")
                            or clean_text(record.get("artwork_type_title") or "") or None),
            holding_entity_id=holding_entity_id, acquisition_text=acquisition,
            url=record.get("api_link") or None, is_public_domain=_public_domain(record.get("is_public_domain")),
        )
        ctx.count("parsed")


def _artist_entity(ctx, record, evidence_id):
    artist_id = record.get("artist_id")
    artist_name = clean_text(record.get("artist_title") or "")
    if artist_id is None or not artist_name:
        return None
    artist_id = _numeric_id(artist_id, "AIC artist ID")
    return db.ensure_entity(
        ctx.con, entity_type="person", name=artist_name, namespace="aic", id_value=artist_id,
        lang="en", source_id=ctx.source_id, evidence_id=evidence_id,
    )


def _numeric_id(value, label):
    if isinstance(value, bool):
        raise FetchError(f"{label} is not a positive numeric identifier")
    text = str(value)
    if not text.isdigit() or int(text) <= 0:
        raise FetchError(f"{label} is not a positive numeric identifier")
    return text


def _public_domain(value):
    return value if isinstance(value, bool) else None


def _acquisition_text(record):
    fields = (
        ("Main reference number", "main_reference_number"),
        ("Credit line", "credit_line"),
        ("Copyright notice", "copyright_notice"),
    )
    values = [f"{label}={clean_text(record.get(key) or '')}" for label, key in fields if record.get(key)]
    return " | ".join(values) or None
