"""Registry-only Korean sources: blocked or not (yet) implemented. Rows are disabled with truthful static status
keys so the source registry reflects what was checked on 2026-10-27; `collect` is never invoked for them."""
from __future__ import annotations

PARSER_VERSION = "kr_registry-1"
_CHK = "checked 2026-10-27"

SOURCES = [
    dict(source_id="mmca_web", blueprint_data_id="D08", blueprint_org_id="O01", name="MMCA 국립현대미술관 — website",
         owner_group="National Museum of Modern and Contemporary Art, Korea", source_kind="museum", region_scope="KR",
         country_codes="KR", access_method="html", base_url="https://www.mmca.go.kr",
         entry_url="https://www.mmca.go.kr/exhibitions/progressList.do", terms_url=None, text_storage_policy="raw_internal",
         priority="P0", st_official_doc="n/a(html)", st_collection_terms="not reached (blocked)", st_image_terms="not reached (blocked)",
         disabled=f"HTTP 400 'Request Blocked' served to the project User-Agent ({_CHK}); not bypassed",
         operational_state="blocked_access", robots_status="robots_http_400(not_crawled)", st_live_response="blocked(HTTP 400 Request Blocked)"),
    dict(source_id="mmca_datagokr_api", blueprint_data_id="D08", blueprint_org_id="O01",
         name="MMCA exhibitions via data.go.kr open API (15058313)", owner_group="National Museum of Modern and Contemporary Art, Korea",
         source_kind="museum", region_scope="KR", country_codes="KR", access_method="api", base_url="https://www.data.go.kr",
         entry_url="https://www.data.go.kr/data/15058313/openapi.do", terms_url="https://www.data.go.kr/data/15058313/openapi.do",
         text_storage_policy="raw_internal", priority="P0", st_official_doc="ok(data.go.kr open API page)",
         st_collection_terms="data.go.kr open API; requires a personal service key", st_image_terms="n/a",
         notes="apply at data.go.kr 15058313, env DATA_GO_KR_SERVICE_KEY",
         disabled=f"needs a data.go.kr service key (apply at data.go.kr 15058313, env DATA_GO_KR_SERVICE_KEY; {_CHK})",
         operational_state="blocked_credentials", robots_status="n/a(api)", st_live_response="not_requested(no service key)"),
    dict(source_id="songeun", blueprint_data_id="D26", blueprint_org_id="O08", name="SONGEUN 송은 — exhibitions",
         owner_group="SONGEUN Art and Cultural Foundation", source_kind="foundation", region_scope="KR", country_codes="KR",
         access_method="html", base_url="https://www.songeun.or.kr", entry_url="https://www.songeun.or.kr", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="robots.txt Disallow: / for all agents", st_image_terms="not reached",
         disabled=f"robots.txt Disallow: / ({_CHK})", operational_state="blocked_permission",
         robots_status="parsed(Disallow: /)", st_live_response="not_requested(robots)"),
    dict(source_id="busan_biennale", blueprint_data_id="D18", blueprint_org_id=None, name="Busan Biennale",
         owner_group="Busan Biennale Organizing Committee", source_kind="biennial", region_scope="KR", country_codes="KR",
         access_method="html", base_url="https://www.busanbiennale.org", entry_url="https://www.busanbiennale.org",
         terms_url=None, text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="not reached", st_image_terms="not reached",
         disabled=f"robots.txt fetch fails with SSLError, so robots cannot be evaluated and the site is not crawled ({_CHK})",
         operational_state="blocked_access", robots_status="robots_error(SSLError)", st_live_response="not_requested(robots unreadable)"),
    dict(source_id="frieze_seoul", blueprint_data_id="D22", blueprint_org_id=None, name="Frieze Seoul",
         owner_group="Frieze", source_kind="fair", region_scope="KR", country_codes="KR", access_method="html",
         base_url="https://www.frieze.com", entry_url="https://www.frieze.com/fairs/frieze-seoul", terms_url=None,
         text_storage_policy="raw_internal", priority="P1", st_official_doc="n/a(html)",
         st_collection_terms="not reached (HTTP 403)", st_image_terms="not reached",
         disabled=f"HTTP 403 to the project User-Agent ({_CHK})", operational_state="blocked_access",
         robots_status="parsed", st_live_response="blocked(HTTP 403)"),
    dict(source_id="neolook", blueprint_data_id=None, blueprint_org_id=None, name="neolook 네오룩 — exhibition listings",
         owner_group="neolook", source_kind="media", region_scope="KR", country_codes="KR", access_method="html",
         base_url="https://neolook.com", entry_url="https://neolook.com", terms_url=None, text_storage_policy="metadata_only",
         priority="P2", st_official_doc="n/a(html)", st_collection_terms="not reached", st_image_terms="not reached",
         disabled=f"robots.txt answers HTTP 403, so robots cannot be evaluated and the site is not crawled ({_CHK})",
         operational_state="blocked_access", robots_status="robots_http_403(not_crawled)", st_live_response="not_requested(robots 403)"),
    dict(source_id="leeum_exhibitions", blueprint_data_id=None, blueprint_org_id="O03", name="Leeum Museum of Art — exhibitions",
         owner_group="Samsung Foundation of Culture", source_kind="museum", region_scope="KR", country_codes="KR",
         access_method="html", base_url="https://www.leeumhoam.org", entry_url="https://www.leeumhoam.org/leeum/exhibition",
         terms_url=None, text_storage_policy="raw_internal", priority="P0", st_official_doc="n/a(html)",
         st_collection_terms="terms page not located; robots.txt 404 (allow)", st_image_terms="not evaluated",
         disabled="not implemented: exhibition cards are rendered client-side from a POST JSON call (/leeum/exhibition/list); "
                  "no server-rendered listing, sitemap (404) or feed found, and detail ids are not discoverable without that call",
         operational_state="not_attempted", robots_status="not_found(allow)", st_live_response="ok(listing shell HTML 200)"),


]


def collect(ctx):  # pragma: no cover - all rows are disabled
    raise RuntimeError(f"{ctx.source_id} is registry-only")

for _row in SOURCES:  # surface the disable reason in the registry's notes column as well
    _row.setdefault("notes", _row["disabled"])
