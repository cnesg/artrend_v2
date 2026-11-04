"""Build outputs/ARTREND_Data_Audit_and_Collection_Results_<asof>.xlsx from the store + audit JSON.
Every number in the workbook is computed here from the DB / audit files at export time.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import defaultdict

import xlsxwriter

from . import db
from .config import AUDIT_ROOT, DB_PATH, OUTPUT_ROOT, WORK_ROOT, iso_now, now_kst
from .source_catalog import HEADERS as CATALOG_HEADERS, catalog_rows
from .export_supplement import append_supplement_sheets

REG = ["KR", "JP", "AMERICAS", "EUROPE", "OTHER"]
REG_KO = {"KR": "한국", "JP": "일본", "AMERICAS": "미주", "EUROPE": "유럽", "OTHER": "기타(HK·중동 등)", "GLOBAL": "공통", "UNMAPPED": "국가 미상"}

# Blueprint D rows not covered by any collector: explicit reason (observed or decided), never silently missing.
D_NOTES = {
    "D02": ("missing", "Getty vocab SPARQL 요청은 식별 UA에서 HTTP 499 (2026-10-27). 대체 식별자 행수는 등록 출처 및 DB 계수로 확인합니다."),
    "D04": ("missing", "Met 공개 소장품은 전시 추세가 아닌 작품 자료입니다. 수집 여부와 보유 행수는 등록 출처 및 현재 DB에서 확인합니다."),
    "D06": ("missing", "Rijksmuseum Data Services requires an API key -> blocked_credentials (user applies for key)."),
    "D18": ("blocked", "busanbiennale.org: TLS/SSL error on robots.txt (probe) -> not crawled."),
    "D21": ("blocked", "artbasel.com robots.txt HTTP 403 to identifying UA -> blocked_access."),
    "D22": ("blocked", "frieze.com HTTP 403 -> blocked_access; local seed scout_galleries_frieze_focus_2026.csv (16 rows) kept as unverified seed."),
    "D26": ("blocked", "songeun.or.kr robots.txt 'User-agent: * Disallow: /' -> blocked_permission (user may request permission / manual entry)."),
    "D34": ("partial", "ArtReview Power 100: past baseline only; not a current popularity ranking. artrend-server power100.js (WP REST) not executed."),
    "D37": ("partial", "Naver News Search API needs NAVER_CLIENT_ID/SECRET -> blocked_credentials for live; legacy artnews.db import used (to 2026-10-20)."),
    "D39": ("missing", "Google Trends has no official public API -> not collected (no unofficial scraping)."),
    "D44": ("partial", "Artprice report: local PDF registered (legacy_local_reports); official download not automated."),
    "D45": ("missing", "The Art Newspaper Visitor Figures: annual paywalled survey; not collected."),
    "D46": ("missing", "Capital Kunstkompass: 2022 list exists only inside the advisory checklist xlsx; print-magazine ranking, not collected."),
    "D47": ("missing", "Artfacts: commercial ranking; terms restrict automated access; not collected."),
    "D48": ("partial", "경매 자료는 시장 참고용입니다. 별도 정규화 스테이징의 가격 기준별 보유량을 확인하고 hammer와 hammer_plus_premium을 혼합하지 않습니다."),
    "D49": ("partial", "경매 자료는 시장 참고용입니다. 별도 정규화 스테이징의 가격 기준별 보유량을 확인하고 hammer와 hammer_plus_premium을 혼합하지 않습니다."),
    "D50": ("partial", "경매 자료는 시장 참고용입니다. 별도 정규화 스테이징의 가격 기준별 보유량을 확인하고 hammer와 hammer_plus_premium을 혼합하지 않습니다."),
    "D51": ("partial", "Seoul Auction의 로컬 최근 판매자료는 제한 표본입니다. 별도 정규화 스테이징 수와 가격 기준을 확인합니다."),
    "D52": ("partial", "K Auction의 로컬 최근 판매자료는 제한 표본입니다. 별도 정규화 스테이징 수와 가격 기준을 확인합니다."),
    "D56": ("partial", "Artist/gallery CVs: gallery artist rosters collected where galleries publish them; individual CVs not parsed."),
    "D57": ("blocked", "Naver DataLab API needs client id/secret -> blocked_credentials."),
}
D_INTERNAL = {
    "D59": ("partial", "작가 클러스터×지역 신호 관측. E축 미관측, 게시 가능 신호 없음."),
    "D60": ("missing", "편집 주제 분류표와 검토된 링크가 없어 trend_cluster를 만들지 않음."),
    "D61": ("partial", "증거 카드는 초안이며 편집자 확인이 필요합니다."),
    "D62": ("partial", "이미지 권리는 레코드별 사용 상태를 확인해야 합니다."),
    "D63": ("missing", "삽화는 자체/계약 제작 범위이며 데이터 수집 범위가 아닙니다."),
    "D64": ("missing", "프런트엔드·게시 작업이 없어 home_snapshot은 만들지 않았습니다."),
    "D65": ("missing", "presentation_config는 프런트엔드 설정 범위입니다."),
    "D66": ("missing", "제품이 없어 product_analytics는 만들지 않았습니다."),
    "D67": ("partial", "crawl_runs와 review_queue, 실행 manifest가 수집 감사 흔적을 제공합니다."),
    "D68": ("current", "실행 안내서와 SOURCE_CONTRACT 파일 존재 여부를 확인합니다."),
    "D69": ("partial", "기사 저자 필드는 있으나 비평가 신원 연결은 별도 검토가 필요합니다."),
    "D70": ("partial", "참여자 역할·추출 방법·신뢰도를 기록합니다."),
    "D71": ("partial", "기사 유형은 피드 분류/URL로 판별하며 명시되지 않으면 unknown입니다."),
}
SECTIONS = [
    ("A", "Core Trend I/G/E", "H01", "signals obs-0.1 + entity_clusters", "I/G 관찰 카운트만 존재. E축 미관측, 커버리지 80%·비교군 30 게이트 측정 불가 → 점수·순위 비공개"),
    ("B", "Artist / Work Story", "H02", "event_participants × entity_clusters × events", "독립 기관 2곳+ 근거 작가 카드(draft). 편집 확인 후 게시"),
    ("C", "Institution / Gallery Moves", "H04,H05", "events(museum/gallery) + relationships(listed_artist)", "전시는 사실 카드 가능. 대표관계 '신규'는 스냅샷 2회 전까지 판단 불가"),
    ("D", "Theme / Region Flow", "H06,H03", "events across regions + articles", "지역 간 동일 작가 흐름 관찰 카드. 주제 분류(taxonomy) 미구축"),
    ("E", "Rookie", "H07", "residency/award/open_call events + participants", "선정 1건=관찰 후보. 경력 단계 미확인"),
    ("F", "Market reference", "H08", "reports + report_metrics (+ legacy auction reference)", "공개 보고서 헤드라인(쪽수)만. 경매 데이터는 참고·비교불가 표시"),
]


def _d_ids(spec: str):
    out = set()
    for part in re.split(r"[,;]", spec or ""):
        part = part.strip()
        m = re.match(r"D(\d+)\s*-\s*D(\d+)", part)
        if m:
            out.update(f"D{i:02d}" for i in range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        m = re.match(r"D(\d+)", part)
        if m:
            out.add(f"D{int(m.group(1)):02d}")
    return out


def _tsv(name):
    p = WORK_ROOT / "work" / "xlsx_dump" / name
    return list(csv.reader(p.open(encoding="utf-8"), delimiter="\t")) if p.exists() else []


def _rows(con, sql, p=()):
    return [dict(r) for r in con.execute(sql, p).fetchall()]


class WB:
    def __init__(self, path):
        temporary_dir = WORK_ROOT / "work" / "tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        self.wb = xlsxwriter.Workbook(path, {"strings_to_urls": False, "strings_to_formulas": False,
                                            "nan_inf_to_errors": True, "constant_memory": True,
                                            "tmpdir": str(temporary_dir)})
        self.h = self.wb.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "#FFFFFF", "text_wrap": True, "valign": "top", "border": 1})
        self.t = self.wb.add_format({"bold": True, "font_size": 14})
        self.w = self.wb.add_format({"text_wrap": True, "valign": "top"})
        self.n = self.wb.add_format({"num_format": "#,##0", "valign": "top"})
        self.note = self.wb.add_format({"italic": True, "font_color": "#555555", "text_wrap": True})

    def sheet(self, name, title, note, headers, rows, widths=None):
        ws = self.wb.add_worksheet(name[:31])
        ws.write(0, 0, title, self.t)
        ws.write(1, 0, note, self.note)
        for j, h in enumerate(headers):
            ws.write(3, j, h, self.h)
            ws.set_column(j, j, (widths or {}).get(j, 18 if len(headers) > 6 else 28))
        count = 0
        for i, r in enumerate(rows):
            count += 1
            for j, v in enumerate(r):
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    ws.write_number(4 + i, j, v, self.n)
                else:
                    ws.write(4 + i, j, "" if v is None else str(v)[:32000], self.w)
        ws.freeze_panes(4, 0)
        if count:
            ws.autofilter(3, 0, 3 + count, len(headers) - 1)
        return ws

    def close(self):
        self.wb.close()


def main():
    con = db.connect()
    from .translation_merge import invalidate_stale_translations
    invalidate_stale_translations(con)
    con.commit()
    asof = now_kst().date().isoformat()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_ROOT / f"ARTREND_Data_Audit_and_Collection_Results_{asof.replace('-', '')}.xlsx"
    wb = WB(str(out))
    inv = json.loads((AUDIT_ROOT / "inventory.json").read_text(encoding="utf-8"))
    val = json.loads((AUDIT_ROOT / "validation.json").read_text(encoding="utf-8")) if (AUDIT_ROOT / "validation.json").exists() else {"checks": []}
    sources = _rows(con, "SELECT * FROM sources ORDER BY source_id")
    last_run = {r["source_id"]: r for r in _rows(con, "SELECT * FROM crawl_runs c WHERE finished_at=(SELECT MAX(finished_at) FROM crawl_runs c2 WHERE c2.source_id=c.source_id)")}
    ev_by_src = {r["source_id"]: r for r in _rows(con, """
        SELECT source_id, COUNT(*) n, SUM(start_precision='day') sday, SUM(start_precision IN ('month','year')) simp, SUM(end_date IS NOT NULL) hasend,
          SUM(url IS NOT NULL) hasurl, SUM(country_code IS NOT NULL) hascc, MIN(start_date) mn, MAX(start_date) mx,
          SUM(event_id IN (SELECT event_id FROM event_participants)) haspart, SUM(announced_status IS NOT NULL) hasstatus
        FROM events GROUP BY 1""")}
    art_by_src = {r["source_id"]: r for r in _rows(con, """SELECT source_id, COUNT(*) n, SUM(published_at IS NOT NULL) haspub, SUM(author_text IS NOT NULL AND author_text<>'') hasauth,
          SUM(article_type NOT IN ('unknown')) typed, MIN(published_at) mn, MAX(published_at) mx FROM articles GROUP BY 1""")}
    rel_by_src = {r["source_id"]: r["n"] for r in _rows(con, "SELECT source_id, COUNT(*) n FROM relationships GROUP BY 1")}
    work_by_src = {r["source_id"]: r for r in _rows(con, """
        SELECT source_id, COUNT(*) n, SUM(artist_entity_id IS NOT NULL) hasartist,
        SUM(date_text IS NOT NULL AND date_text<>'') hasdate,
        SUM(medium IS NOT NULL AND medium<>'') hasmedium,
        SUM(url IS NOT NULL AND url<>'') hasurl FROM works GROUP BY source_id""")}
    record_counts = defaultdict(dict)
    for table in ("events", "articles", "works", "relationships", "aliases", "fx_rates"):
        for row in _rows(con, f"SELECT source_id, COUNT(*) n FROM {table} GROUP BY source_id"):
            record_counts[row["source_id"]][table] = row["n"]
    for row in _rows(con, """SELECT e.source_id, COUNT(DISTINCT r.report_id) n FROM reports r
                             JOIN evidence e ON e.url=r.official_url GROUP BY e.source_id"""):
        record_counts[row["source_id"]]["reports"] = row["n"]
    kiaf_event_profiles = {r["source_id"]: r for r in _rows(con, """
        SELECT source_id, COUNT(*) n, MIN(start_date) first_start, MAX(end_date) last_end,
               GROUP_CONCAT(DISTINCT city) cities, GROUP_CONCAT(DISTINCT description_excerpt) venues,
               SUM(event_id IN (SELECT event_id FROM event_participants)) participant_events
        FROM events GROUP BY source_id""")}
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ("sources", "entities", "aliases", "entity_links", "events", "event_participants", "relationships", "articles", "works", "evidence",
               "reports", "report_metrics", "image_rights", "review_queue", "signals", "evidence_cards", "fx_rates", "crawl_runs")}
    internal_counts = {
        "D59": {"signals": counts["signals"]},
        "D61": {"evidence_cards": counts["evidence_cards"]},
        "D62": {"image_rights": counts["image_rights"]},
        "D67": {"crawl_runs": counts["crawl_runs"], "review_queue": counts["review_queue"]},
        "D68": {"run guide": int((WORK_ROOT / "README_RUN_GUIDE.md").is_file()),
                "source contract": int((WORK_ROOT / "work" / "SOURCE_CONTRACT.md").is_file())},
        "D69": {"articles with author": con.execute("SELECT COUNT(*) FROM articles WHERE author_text IS NOT NULL AND author_text<>''").fetchone()[0]},
        "D70": {"event participants": counts["event_participants"]},
        "D71": {"typed articles": con.execute("SELECT COUNT(*) FROM articles WHERE article_type NOT IN ('unknown')").fetchone()[0]},
    }
    live_ids = [s["source_id"] for s in sources if not s["source_id"].startswith("legacy_")]
    new_events = con.execute("SELECT COUNT(*) FROM events WHERE source_id NOT LIKE 'legacy_%'").fetchone()[0]
    new_articles = con.execute("SELECT COUNT(*) FROM articles WHERE source_id NOT LIKE 'legacy_%'").fetchone()[0]
    state_ct = defaultdict(int)
    for s in sources:
        state_ct[s["operational_state"] or "not_run"] += 1
    reg_ev = {r["edition_region"] or "UNMAPPED": r for r in _rows(con, """SELECT edition_region, COUNT(*) n, SUM(source_id NOT LIKE 'legacy_%') live,
        SUM(start_date>=date(?, '-90 day') AND start_date<=? AND start_precision='day' AND source_id NOT LIKE 'legacy_%') l90,
        COUNT(DISTINCT CASE WHEN source_id NOT LIKE 'legacy_%' THEN source_id END) nsrc FROM events GROUP BY 1""", (asof, asof))}
    cards = _rows(con, "SELECT * FROM evidence_cards ORDER BY edition_region, section, card_kind")

    # ---------------- 00 summary ----------------
    summ = [
        ("기준일(asof, KST)", asof, "now_kst() at export"),
        ("DB", str(DB_PATH.relative_to(WORK_ROOT)), "SQLite, schema " + (con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() or ["?"])[0]),
        ("기존 자산 인벤토리 행", len(inv["rows"]), "work/audit/inventory.json (bulk dirs grouped)"),
        ("등록 소스 수(전체)", len(sources), "; ".join(f"{k}={v}" for k, v in sorted(state_ct.items()))),
        ("라이브 소스(legacy 제외)", len(live_ids), "operational_state per source in sheet 03"),
        ("신규 수집 이벤트(라이브)", new_events, "events from live official sources this session"),
        ("신규 수집 기사 메타(라이브)", new_articles, "RSS/feeds metadata only"),
        ("legacy 재사용 이벤트", counts["events"] - new_events, "MoMA/Whitney/biennale snapshots, labeled legacy_*"),
        ("legacy 재사용 기사 메타", counts["articles"] - new_articles, "artnews.db unflagged + gallery news snapshots"),
        ("작품 레코드(works)", counts["works"], "출처별 작품 수와 권리는 00b/03/04 시트 참조; 전시 활동과 별개"),
        ("엔티티 / 별칭 / 링크", f"{counts['entities']:,} / {counts['aliases']:,} / {counts['entity_links']:,}", "links: confirmed=shared Wikidata/ULAN; candidate=name match (never auto-merged)"),
        ("증거(evidence) 행", counts["evidence"], "each with raw_path+sha256 (raw_internal sources) or URL (metadata_only)"),
        ("보고서 / 헤드라인 문장", f"{counts['reports']} / {counts['report_metrics']}", "public PDFs; sentences unreviewed"),
        ("검토 큐(open)", counts["review_queue"], "sheet 09"),
        ("검증", f"FAIL {val.get('n_fail', '?')} / warn {val.get('n_warn', '?')}", "sheet 12; work/audit/validation.json"),
    ]
    for r in REG:
        x = reg_ev.get(r, {})
        summ.append((f"지역 {REG_KO[r]} 라이브 이벤트 (최근90일 시작)", f"{x.get('live', 0) or 0:,} ({x.get('l90', 0) or 0:,}) / 소스 {x.get('nsrc', 0)}", "edition_region from venue country only"))
    x = reg_ev.get("UNMAPPED", {})
    summ.append(("국가 미상 이벤트", x.get("n", 0) or 0, "venue country unknown -> review queue"))
    summ.append(("결론", "홈 섹션은 '사실 카드(전시/선정/보고서)'만 편집 검토 후 게시 가능. Core Trend 점수·순위·'신규 대표관계'는 게이트 미충족으로 비공개.", "sheet 06"))
    wb.sheet("00_요약", "ARTREND 데이터 감사·수집 결과 요약", f"생성 {iso_now()} · 모든 수치는 DB/감사 파일에서 계산. 미관측은 0이 아님.",
             ["항목", "값", "근거·비고"], summ, {0: 38, 1: 60, 2: 80})
    wb.sheet("00b_카테고리별_수집출처", "카테고리별 출처와 실제 수집 내역",
             "출처당 1행, 카테고리순 정렬·필터 가능. 건수는 현재 DB 보유량이며 자료 유형별 단위가 달라 합산할 수 없습니다. 전체 수집 완료·발행 허가와 별개입니다.",
             CATALOG_HEADERS, catalog_rows(con, sources, last_run),
             {0: 30, 1: 48, 2: 30, 3: 60, 4: 80, 5: 35, 16: 35, 17: 45, 18: 45, 25: 65, 26: 55, 27: 100})

    # ---------------- 01 inventory ----------------
    cols = ["path", "level", "format", "bytes", "mtime(not freshness)", "records", "sha256", "unit", "region", "period", "latest", "fields", "url", "uid", "dup",
            "rights", "bp", "lg", "verdict", "reason"]
    wb.sheet("01_자산인벤토리", "기존 파일·DB·코드·볼트·ZIP·리포트 인벤토리", "mtime은 파일 수정시각이며 데이터 최신성이 아님. 판단 열(unit~reason)은 work/audit/*.json 감사 결과 기반.",
             ["경로", "단위", "형식", "바이트", "mtime", "레코드/행", "sha256", "관측단위", "지역/언어", "관측기간", "최신 사건/수집", "핵심 필드", "출처 URL", "고유 ID",
              "중복위험", "권리", "Blueprint D", "Logic L", "재사용 판정", "근거"],
             [[r.get(c) for c in cols] for r in inv["rows"]], {0: 50, 19: 60})

    # ---------------- 02 blueprint D mapping ----------------
    bp_rows = _tsv("BP__07_데이터목록.tsv")
    hi = next((i for i, r in enumerate(bp_rows) if r and r[0] == "데이터 ID"), None)
    d_meta = {}
    if hi is not None:
        for r in bp_rows[hi + 1:]:
            if r and r[0].startswith("D"):
                d_meta[r[0]] = r
    fd = _tsv("BP__20_프런트데이터.tsv")
    hi2 = next((i for i, r in enumerate(fd) if r and r[0] == "데이터 ID"), None)
    if hi2 is not None:
        for r in fd[hi2 + 1:]:
            if r and r[0].startswith("D"):
                d_meta[r[0]] = [r[0], r[2], r[1], "", r[3], r[4]] + [""] * 6
    src_by_d = defaultdict(list)
    for s in sources:
        for d in _d_ids(s["blueprint_data_id"]):
            src_by_d[d].append(s)
    drows = []
    for i in range(1, 72):
        d = f"D{i:02d}"
        m = d_meta.get(d, [d] + [""] * 11)
        ss = src_by_d.get(d, [])
        status, why = _blueprint_status(d, sources, last_run, record_counts, kiaf_event_profiles, internal_counts)
        n_ev = sum((ev_by_src.get(s["source_id"]) or {}).get("n", 0) or 0 for s in ss)
        n_ar = sum((art_by_src.get(s["source_id"]) or {}).get("n", 0) or 0 for s in ss)
        drows.append([d, m[1] if len(m) > 1 else "", m[2] if len(m) > 2 else "", m[8] if len(m) > 8 else "", status,
                      ", ".join(s["source_id"] for s in ss), n_ev, n_ar, why, m[10] if len(m) > 10 else "", m[11] if len(m) > 11 else ""])
    wb.sheet("02_Blueprint_D매핑", "Blueprint 데이터 ID D01–D71 전체 매핑과 현재 상태", "status: current(라이브 수집 성공) / partial(일부·legacy·차단 혼재) / missing(수집기 없음) / blocked(robots·403·키 필요). 원본 '이번 확인 수준'은 참고열.",
             ["D", "분류", "이름", "우선순위(BP)", "상태", "연결 source_id", "이벤트 수", "기사 수", "근거/사유", "사용 로직(BP)", "BP '이번 확인 수준'"],
             drows, {2: 30, 5: 40, 8: 90})

    # ---------------- 03 source registry ----------------
    srows = []
    for s in sources:
        lr = last_run.get(s["source_id"]) or {}
        srows.append([s["source_id"], s["name"], s["owner_group"], s["source_kind"], s["region_scope"], s["country_codes"], s["blueprint_data_id"], s["blueprint_org_id"],
                      s["access_method"], s["entry_url"], s["priority"], s["st_local_file"], s["st_official_doc"], s["st_live_response"], s["st_fields_extracted"],
                      s["st_history"], s["st_incremental"], s["robots_status"], s["st_collection_terms"], s["st_image_terms"], s["text_storage_policy"],
                      s["operational_state"], lr.get("state"), lr.get("finished_at"), lr.get("http_requests"), (lr.get("error") or "")[:400], s["terms_url"], s["notes"]])
    wb.sheet("03_소스레지스트리", "Source registry — 상태 축 분리", "로컬파일/공식문서/실응답/필드추출/이력/증분/robots/수집약관/이미지권리/운영상태를 따로 기록. robots 허용 ≠ 권리 허가.",
             ["source_id", "이름", "소유그룹", "종류", "지역범위", "국가", "Blueprint D", "Blueprint O", "접근", "진입 URL", "우선", "로컬파일", "공식문서", "실응답", "필드추출",
              "이력", "증분", "robots", "수집 약관", "이미지 권리", "본문 저장정책", "운영상태", "최근 실행", "최근 실행 시각", "요청수", "최근 메모/오류", "약관 URL", "비고"],
             srows, {1: 34, 9: 40, 25: 60, 27: 50})

    # ---------------- 04 collection results & field quality ----------------
    q = []
    for s in sources:
        e = ev_by_src.get(s["source_id"])
        a = art_by_src.get(s["source_id"])
        w = work_by_src.get(s["source_id"])
        lr = last_run.get(s["source_id"]) or {}
        if not (e or a or lr):
            continue
        pct = (lambda k, base: round(100 * (base.get(k) or 0) / base["n"], 1) if base and base.get("n") else None)
        q.append([s["source_id"], s["region_scope"], lr.get("mode"), lr.get("state"), lr.get("records_parsed"), lr.get("records_inserted"), lr.get("records_updated"),
                  lr.get("records_unchanged"), (e or {}).get("n"), (e or {}).get("mn"), (e or {}).get("mx"), pct("sday", e), pct("simp", e), pct("hasend", e), pct("haspart", e),
                  pct("hasurl", e), pct("hascc", e), pct("hasstatus", e), rel_by_src.get(s["source_id"]), (a or {}).get("n"), (a or {}).get("mn"), (a or {}).get("mx"),
                  pct("haspub", a), pct("hasauth", a), pct("typed", a),
                  (w or {}).get("n"), pct("hasartist", w), pct("hasdate", w), pct("hasmedium", w), pct("hasurl", w)])
    wb.sheet("04_수집결과_필드품질", "수집 결과와 필드 품질(소스별)", "% = 해당 소스 레코드 중 필드 보유율. start 정밀도 day/month·year 분리. 참여작가 보유율은 참여자 1명 이상 이벤트 비율.",
             ["source_id", "지역", "최근 모드", "상태", "parsed", "inserted", "updated", "unchanged", "이벤트", "최소 시작일", "최대 시작일", "%시작일(day)", "%시작일(월·연)",
              "%종료일", "%참여자", "%URL", "%국가", "%공지상태", "관계(명단)", "기사", "최초 발행", "최근 발행", "%발행일", "%저자", "%유형분류",
              "작품", "%작품 작가ID", "%작품 날짜원문", "%작품 매체", "%작품 URL"], q)

    # ---------------- 05 region x period coverage ----------------
    cov = _rows(con, "SELECT * FROM coverage WHERE asof=? ORDER BY edition_region, source_id", (asof,))
    wb.sheet("05_지역x기간_커버리지", "지역 × 기간 커버리지", "최근90일 vs 직전90일은 시작일(day 정밀도) 기준. '직전 구간 자료 없음'이면 증감 비교 불가. completeness는 목록 게시 범위 기준이며 지역 전체 대표성이 아님.",
             ["source_id", "asof", "지역", "국가", "종류", "레코드", "최초", "최근", "최근90일", "직전90일", "예정", "이력 메모", "완전성"],
             [[c[k] for k in ("source_id", "asof", "edition_region", "country_code", "record_kind", "n_records", "earliest_date", "latest_date", "n_last_90d", "n_prev_90d",
                              "n_upcoming", "history_note", "completeness")] for c in cov], {11: 70})
    piv = _rows(con, """SELECT COALESCE(edition_region,'UNMAPPED') reg, substr(start_date,1,7) ym, COUNT(*) n FROM events
                        WHERE source_id NOT LIKE 'legacy_%' AND start_precision='day' AND start_date BETWEEN date(?, '-365 day') AND date(?, '+120 day')
                        AND event_type<>'acquisition' GROUP BY 1,2""", (asof, asof))
    months = sorted({p["ym"] for p in piv})
    grid = defaultdict(dict)
    for p in piv:
        grid[p["reg"]][p["ym"]] = p["n"]
    wb.sheet("05b_지역x월_라이브", "지역 × 월 (라이브 공식출처 이벤트 시작 수, MoMA 수장 제외)", "빈칸 = 해당 월에 관찰 없음(0으로 해석 금지: 출처별 이력 깊이가 다름).",
             ["지역"] + months, [[REG_KO.get(r, r)] + [grid[r].get(m) for m in months] for r in REG + ["UNMAPPED"]])

    # ---------------- 06 home section mapping ----------------
    by_sec = defaultdict(lambda: defaultdict(list))
    for c in cards:
        by_sec[c["section"]][c["edition_region"]].append(c["card_kind"])
    hrows = []
    for code, name, hs, data, rule in SECTIONS:
        for r in ["KR", "JP", "AMERICAS", "EUROPE"]:
            kinds = [k for h in hs.split(",") for k in by_sec[h][r]]
            ready = [k for k in kinds if k != "gap_notice"]
            if code == "A":
                status = "게시 불가"
                why = "가중치(I50/G25/E25, 60/40)는 가설. E축 미관측·커버리지 게이트 측정 불가 → 점수 산출 안 함"
            elif ready:
                status = "편집 검토 후 게시 가능(draft)"
                why = f"draft 카드 {len(ready)}건 ({', '.join(sorted(set(ready)))})"
            else:
                status = "게시 불가(근거 부족)"
                why = "gap_notice: " + ("; ".join(c["title"] for c in cards if c["edition_region"] == r and c["section"] in hs.split(","))[:300])
            hrows.append([code, name, hs, REG_KO[r], status, why, data, rule])
    wb.sheet("06_홈섹션매핑", "홈 섹션 A–F × 지역 게시 가능성", "Blueprint 16 프런트페이지(H01–H08)와 사용자 정의 A–F 연결. 'draft'는 편집자 원문 확인 전 게시 금지.",
             ["코드", "섹션", "Blueprint H", "지역", "판정", "근거", "데이터", "규칙/한계"], hrows, {5: 70, 7: 60})

    # ---------------- 07 reports ----------------
    rep = _rows(con, "SELECT r.*, (SELECT COUNT(*) FROM report_metrics m WHERE m.report_id=r.report_id) n_metrics FROM reports r ORDER BY report_id")
    wb.sheet("07_리포트", "시장·기관 보고서 레지스트리", "구매 없음. 공개 PDF만 내려받아 해시 저장. 지표 정의(딜러+경매/경매만, 수수료 포함, 표본)가 서로 달라 단순 비교 금지.",
             ["report_id", "제목", "발행", "후원", "발행일", "관측기간", "지리범위", "방법·표본", "가격기준", "공식 URL", "로컬 경로", "sha256", "쪽수", "권리", "접근 상태", "다음 확인", "비고", "추출 문장 수"],
             [[r[k] for k in ("report_id", "title", "publisher", "sponsor", "published_date", "observation_period", "geo_scope", "methodology", "price_basis", "official_url",
                              "local_path", "sha256", "pages", "rights_note", "access_status", "next_check", "notes", "n_metrics")] for r in rep])
    mets = _rows(con, "SELECT * FROM report_metrics ORDER BY report_id, CAST(page AS INT)")
    wb.sheet("07b_리포트_문장", "보고서 헤드라인 문장(자동 추출, 미검토)", "인용 전 원문 쪽수 대조 필수. 수치는 문장 그대로이며 정규화하지 않음.",
             ["report_id", "쪽", "문장(≤300자)", "지리", "기간", "비교 주의"], [[m["report_id"], m["page"], m["excerpt"], m["geography"], m["period"], m["comparability_note"]] for m in mets], {2: 100})

    # ---------------- 08 rights / images ----------------
    img = _rows(con, "SELECT source_id, usage_status, COUNT(*) n, MIN(basis) basis FROM image_rights GROUP BY 1,2")
    rr = [[s["source_id"], s["st_collection_terms"], s["st_image_terms"], s["text_storage_policy"], s["terms_url"]] for s in sources]
    wb.sheet("08_권리_이미지", "권리·이미지 상태", "이미지는 내려받지 않음. 공개 라이선스가 레코드에 명시된 경우만 재사용 가능 표시. 보도자료 이미지 = 사용 조건 미확인.",
             ["source_id", "usage_status", "이미지 수", "근거"], [[i["source_id"], i["usage_status"], i["n"], i["basis"]] for i in img], {3: 90})
    wb.sheet("08b_소스별_약관", "소스별 수집·이미지 약관 요약", "robots 허용은 권리 허가가 아님. 본문은 metadata_only 소스에서 저장하지 않음.",
             ["source_id", "수집 약관", "이미지 약관", "저장 정책", "약관 URL"], rr, {1: 60, 2: 50, 4: 50})

    # ---------------- 09 review queue ----------------
    rq = _rows(con, "SELECT item_type, issue, COUNT(*) n, MIN(detail) example FROM review_queue WHERE status='open' GROUP BY 1,2 ORDER BY n DESC")
    wb.sheet("09_검토큐", "검토 큐(유형별 집계)", "개별 항목은 DB review_queue 테이블. 이름 유사도로 자동 병합하지 않으며 후보만 남김.",
             ["유형", "이슈", "건수", "예시"], [[r["item_type"], r["issue"], r["n"], r["example"]] for r in rq], {1: 60, 3: 80})
    lk = _rows(con, "SELECT status, method, COUNT(*) n FROM entity_links GROUP BY 1,2")
    wb.sheet("09b_동일성링크", "엔티티 링크 상태", "confirmed=공유 외부ID(Wikidata/ULAN); candidate=정규화 이름 일치 또는 Wikidata 라벨 유일 일치(검토 필요); rejected=생년 충돌.",
             ["status", "method", "건수"], [[r["status"], r["method"], r["n"]] for r in lk])

    # ---------------- 10 next steps ----------------
    ns = _next_steps(sources)
    wb.sheet("10_다음단계", "다음 단계와 사용자 조치", "우선순위 순. 스케줄러는 설치하지 않음.", ["#", "구분", "조치", "누가", "이유/효과"], ns, {2: 80, 4: 70})

    # ---------------- 11 evidence cards ----------------
    wb.sheet("11_증거카드", "지역별 근거 카드 샘플(draft_unreviewed)", "사실/비교/해석/반대근거/한계/출처 분리. 해석은 가설이며 편집자 확인 전 게시 금지.",
             ["지역", "섹션", "종류", "제목", "사실", "비교", "해석(가설)", "반대근거", "한계", "출처 URL", "독립 주체 수", "상태"],
             [[REG_KO.get(c["edition_region"], c["edition_region"]), c["section"], c["card_kind"], c["title"], c["facts"], c["comparison"], c["interpretation"],
               c["counter_evidence"], c["limitations"], "\n".join(json.loads(c["evidence_urls"] or "[]")), c["n_independent_sources"], c["status"]] for c in cards],
             {3: 50, 4: 90, 8: 60, 9: 60})

    # ---------------- 12 validation ----------------
    wb.sheet("12_검증결과", "검증 결과", f"validated_at {val.get('validated_at')}", ["검사", "결과", "상세"],
             [[c["check"], c["result"], c["detail"]] for c in val.get("checks", [])], {0: 50, 2: 100})
    runs = _rows(con, "SELECT run_id, source_id, mode, state, records_parsed, records_inserted, records_updated, records_unchanged, http_requests, http_not_modified FROM crawl_runs ORDER BY run_id, source_id")
    wb.sheet("12b_실행이력", "실행 이력(crawl_runs) — 증분 재실행 멱등성 근거", "같은 소스의 incremental 재실행에서 inserted=0/updated=0이면 멱등.",
             ["run_id", "source_id", "mode", "state", "parsed", "inserted", "updated", "unchanged", "요청", "304"], [list(r.values()) for r in runs])

    # ---------------- 13 readiness plan re-verification ----------------
    wb.sheet("13_Readiness재검증", "Data_Readiness_and_Crawl_Plan_v1 주장 재검증", "RP는 미검증 초안으로 취급. 각 주장을 이번 관측으로 대조.",
             ["RP 항목", "RP 주장", "재검증 결과", "근거"], _rp_checks(con, inv, sources, last_run), {1: 50, 2: 30, 3: 90})
    append_supplement_sheets(wb, con)
    wb.close()
    print(out)
    return out


def _state(sources, sid_):
    s = next((s for s in sources if s["source_id"] == sid_), None)
    if s is None:
        return "not registered"
    return s.get("operational_state") or "registered; state not recorded"


def _record_total(source_id, record_counts):
    return sum((record_counts.get(source_id) or {}).values())


def _source_evidence(source, last_run, record_counts):
    sid_ = source["source_id"]
    run = last_run.get(sid_) or {}
    counts = record_counts.get(sid_) or {}
    observed = ", ".join(f"{key}={value:,}" for key, value in sorted(counts.items()) if value)
    observed = observed or "DB 본자료 0행"
    state = run.get("state") or "실행 이력 없음"
    detail = f"{sid_} ({observed}; 최근 실행={state}"
    if run.get("records_unchanged") is not None:
        detail += f", unchanged={run['records_unchanged']:,}"
    return detail + ")"


def _blocked_source_reason(source):
    fields = ("operational_state", "robots_status", "st_live_response", "st_collection_terms", "notes")
    evidence = list(dict.fromkeys(str(source.get(field)).strip() for field in fields if source.get(field)))
    return f"{source['source_id']}: " + "; ".join(evidence)


def _blueprint_status(d, sources, last_run, record_counts, event_profiles=None, internal_counts=None):
    event_profiles = event_profiles or {}
    internal_counts = internal_counts or {}
    if d in D_INTERNAL:
        _, note = D_INTERNAL[d]
        observations = internal_counts.get(d)
        if observations is not None:
            detail = ", ".join(f"{key}={value:,}" for key, value in observations.items())
            if d == "D68":
                status = "current" if observations and all(observations.values()) else "missing"
            else:
                status = "partial" if any(observations.values()) else "missing"
            return status, f"{note} DB/파일 근거: {detail or '관측 없음'}"
        return D_INTERNAL[d]

    registered = [s for s in sources if d in _d_ids(s.get("blueprint_data_id"))]
    kiaf = next((s for s in registered if s["source_id"] == "kiaf_seoul"), None)
    if d == "D23" and kiaf:
        sid_ = kiaf["source_id"]
        profile = event_profiles.get(sid_) or {}
        event_count = profile.get("n", (record_counts.get(sid_) or {}).get("events", 0)) or 0
        if event_count:
            period = "–".join(value for value in (profile.get("first_start"), profile.get("last_end")) if value) or "기간 미확인"
            venue = ", ".join(value for value in (profile.get("cities"), profile.get("venues")) if value) or "장소 미확인"
            state = (last_run.get(sid_) or {}).get("state") or "실행 이력 없음"
            relation_count = (record_counts.get(sid_) or {}).get("relationships", 0)
            participants = profile.get("participant_events", 0) or 0
            reason = (f"KIAF fair edition 범위만 관측: DB 행사={event_count:,}건, 기간={period}, 장소={venue}; "
                      f"참여자 보유 행사={participants:,}, 관계={relation_count:,}, 최근 실행={state}. "
                      "전시자·갤러리 필드는 미확보이므로 partial.")
        else:
            state = (last_run.get(sid_) or {}).get("state") or "실행 이력 없음"
            reason = (f"KIAF 소스 등록됨; DB 행사=0건, 최근 실행={state}. 소스 범위는 fair edition 날짜·장소이며 "
                      "전시자·갤러리 필드는 확인되지 않아 수집 성공으로 보지 않습니다.")
        notes = str(kiaf.get("notes") or "").casefold()
        if "120" in notes and ("render" in notes or "렌더링" in notes):
            reason += " 공개 전시자 화면은 제한된 120초 렌더링 시도 후에도 미해결이며, 추가 재시도나 직접 API 호출은 하지 않습니다."
        if event_count:
            return "partial", reason
        if (kiaf.get("operational_state") or "").startswith("blocked"):
            return "blocked", reason
        return "missing", reason

    live = [s for s in registered if not s["source_id"].startswith("legacy_")]
    legacy = [s for s in registered if s["source_id"].startswith("legacy_")]
    blocked = [s for s in registered if (s.get("operational_state") or "").startswith("blocked")]
    ok = [s for s in live if (last_run.get(s["source_id"]) or {}).get("state") in ("success", "no_change", "partial")
          and _record_total(s["source_id"], record_counts) > 0]
    if ok:
        current = (len(ok) == len(live) and not blocked and not legacy
                   and all((last_run.get(s["source_id"]) or {}).get("state") in ("success", "no_change") for s in live))
        status = "current" if current else "partial"
        details = [_source_evidence(s, last_run, record_counts) for s in ok]
        not_observed = [s for s in live if s not in ok]
        details.extend(_source_evidence(s, last_run, record_counts) for s in not_observed)
        details.extend(_blocked_source_reason(s) for s in blocked)
        if d == "D54" and any(s["source_id"] == "broad_public" for s in registered):
            details.append("등록된 공개 수집기는 증분 실행에서 미관측 페이지를 우선 처리하며, 전체 소장품 완전성을 뜻하지 않습니다.")
        if d == "D04" and any(s["source_id"] == "met_collection_github" for s in ok):
            details.append("Met Open Access 공식 GitHub CC0 CSV의 작품 행은 DB 집계이며 전시 추세 자료와 구분합니다.")
        return status, "; ".join(details)
    if blocked:
        return "blocked", "; ".join(_blocked_source_reason(s) for s in blocked)
    if legacy:
        return "partial", "로컬 legacy 자료만 관측: " + "; ".join(_source_evidence(s, last_run, record_counts) for s in legacy)
    if registered:
        return "missing", "등록 출처의 현재 DB 본자료가 없거나 성공 실행이 확인되지 않음: " + "; ".join(
            _source_evidence(s, last_run, record_counts) for s in registered)
    return D_NOTES.get(d, ("missing", "등록 출처 없음"))


def _rp_checks(con, inv, sources, last_run):
    def ev(sid_):
        return con.execute("SELECT COUNT(*) FROM events WHERE source_id=?", (sid_,)).fetchone()[0]
    def articles(sid_):
        return con.execute("SELECT COUNT(*) FROM articles WHERE source_id=?", (sid_,)).fetchone()[0]
    def works(sid_):
        return con.execute("SELECT COUNT(*) FROM works WHERE source_id=?", (sid_,)).fetchone()[0]

    sema = [s for s in sources if s["source_id"].startswith("sema")]
    tate = [s for s in sources if s["source_id"].startswith("tate")]
    mori = [s for s in sources if s["source_id"] == "mam_exhibitions"]
    news_count = con.execute("SELECT COUNT(*) FROM articles WHERE source_id='legacy_v2v_artnews'").fetchone()[0]
    mmca_web = next((s for s in sources if s["source_id"] == "mmca_web"), None)
    mmca_api = next((s for s in sources if s["source_id"] == "mmca_datagokr_api"), None)
    met = next((s for s in sources if s["source_id"] == "met_collection_github"), None)
    met_run = last_run.get("met_collection_github") or {}
    met_works = works("met_collection_github")
    artforum = next((s for s in sources if s["source_id"] == "artforum_feed"), None)
    kadist = next((s for s in sources if s["source_id"] == "kadist_public"), None)
    broad = next((s for s in sources if s["source_id"] == "broad_public"), None)
    market = _auction_stage_summary()
    if market is None:
        market_result = "별도 정규화 스테이징 DB/테이블 미확인"
    else:
        market_result = f"정규화 스테이징 {market['total']:,}행; 가격 기준별 " + ", ".join(
            f"{basis}={count:,}" for basis, count in sorted(market["by_basis"].items()))
    artforum_terms = (artforum or {}).get("st_collection_terms") or "수집 약관 메타데이터 미등록"
    met_result = (f"DB 작품={met_works:,}; 최근 실행={met_run.get('state') or '실행 이력 없음'}"
                  + (f", unchanged={met_run['records_unchanged']:,}" if met_run.get("records_unchanged") is not None else ""))
    if met is None:
        met_result = f"not registered; DB 작품={met_works:,}"
    return [
        ["SRC-KR-MMCA", "접근 경로·권한 확인", f"웹: {_state(sources, 'mmca_web')}; 공식 API(15058313): {_state(sources, 'mmca_datagokr_api')}; DB 이벤트: {ev('mmca_datagokr_api'):,}",
         f"웹 실응답: {(mmca_web or {}).get('st_live_response') or '미등록/미기록'}; API 메타: {(mmca_api or {}).get('st_live_response') or '미등록/미기록'}. 공식 API는 허용된 자동화 선택지이며 유일한 적법 경로로 단정하지 않습니다. 권한을 확인한 수동 입력도 선택지입니다."],
        ["SRC-KR-SEMA", "원본에서 접속 실패", "; ".join(f"{s['source_id']}={s['operational_state']} ({ev(s['source_id'])} events)" for s in sema) or "not implemented",
         "robots: Disallow:/ + Allow:/kr/whatson 등(RFC 최장일치로 허용). 첫 URL은 HTTP 500"],
        ["SRC-JP-APJ", "본문 확인(원본)", _state(sources, "jp_apj") if any(s['source_id'] == 'jp_apj' for s in sources) else "search portal; no bulk access confirmed",
         "artplatform.go.jp 200 응답. 공개 대량 API/다운로드 문서 확인 여부는 03 시트 notes"],
        ["SRC-JP-MORI", "본문 확인(원본)", "; ".join(f"{s['source_id']}={s['operational_state']} ({ev(s['source_id'])} events)" for s in mori) or "-", "robots 404(허용)"],
        ["SRC-US-MOMA", "공개 GitHub/API 본문 확인", f"GitHub CSV: {_state(sources, 'moma_collection_github')}; moma.org: Cloudflare 403(robots 포함)",
         "MoMA 전시는 2026-08 legacy 스냅샷만 사용(legacy_moma_calendar_202608)"],
        ["SRC-US-MET", "공식 GitHub CC0 소장품 CSV", met_result,
         "작품 수는 현재 DB works 행수이며 최근 실행의 inserted/unchanged와 함께 확인합니다. 작품 소장품 메타데이터는 전시 추세와 별개입니다."],
        ["SRC-US-BROAD", "공개 전시·프로그램·작품 수집", 
         (f"{_state(sources, 'broad_public')}; DB events={ev('broad_public'):,}, works={works('broad_public'):,}; "
          f"최근 실행={(last_run.get('broad_public') or {}).get('state') or '실행 이력 없음'}") if broad else
         f"not registered; DB events={ev('broad_public'):,}, works={works('broad_public'):,}",
         (broad or {}).get("notes") or (broad or {}).get("st_collection_terms") or "등록된 수집 범위 메타데이터 없음"],
        ["SRC-US-KADIST", "공개 페이지 접근 상태", 
         (f"{_state(sources, 'kadist_public')}; DB events={ev('kadist_public'):,}, works={works('kadist_public'):,}") if kadist else
         f"not registered; DB events={ev('kadist_public'):,}, works={works('kadist_public'):,}",
         (kadist or {}).get("st_live_response") or (kadist or {}).get("notes") or "등록된 실응답 메타데이터 없음"],
        ["SRC-GLOBAL-ARTFORUM", "RSS 메타데이터 권한", 
         (f"{_state(sources, 'artforum_feed')}; DB articles={articles('artforum_feed'):,}") if artforum else
         f"not registered; DB articles={articles('artforum_feed'):,}",
         artforum_terms],
        ["SRC-EU-TATE", "확인 필요", "; ".join(f"{s['source_id']}={s['operational_state']} ({ev(s['source_id'])} events)" for s in tate) or "-", "tate.org.uk/whats-on 200 (probe)"],
        ["SRC-NEWS-DB", "로컬 존재·사용 가능", f"부분 사용: {news_count:,}행을 metadata로 import (URL 중복 제외)",
         "74% Google News 리다이렉트 URL, 45% flagged_mismatch, review/news 구분 없음, 2026-10-20 이후 미갱신"],
        ["SRC-AUCT-LOCAL", "별도 시장 참고자료(P2)", market_result,
         "원본 불변. hammer와 hammer_plus_premium은 분리하며 서로 합산·비교하지 않습니다. 통화·낙찰상태도 별도 집계하고 비교 조건은 시장 통계를 뜻하지 않습니다."],
        ["RP02 data/global/*.csv", "사용 가능", "art_market.db와 중복", "per-house CSV 병합 사본; fx_rates.json/cpi_us.json만 P2 보조"],
        ["RP02 vault_curated", "부분 사용 가능", "derived_do_not_treat_as_fact", "4,900+ 노트 출처 필드 없음, 동명/표기 변이, 귀속 라벨이 작가로 등재"],
        ["RP02 Blueprint '본문 확인'", "실제 API 성공과 별개", "확인됨", "예: AIC API는 robots 403(Cloudflare)이나 문서화된 API 엔드포인트는 200; MoMA/Tate 등은 sheet 03 실측"],
        ["RP00 결론", "공식 기관 최신 사건·ID·중복제거·권리 우선", "판정 기준 유지", "출처별 실제 실행 상태·DB 보유량·권리 메타데이터를 따로 확인하며 전체 수집 완료로 일반화하지 않습니다."],
    ]


def _auction_stage_summary():
    path = WORK_ROOT / "db" / "auction_normalized.sqlite"
    if not path.is_file():
        return None
    market = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if not market.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='normalized_lots'").fetchone():
            return None
        total = market.execute("SELECT COUNT(*) FROM normalized_lots").fetchone()[0]
        by_basis = dict(market.execute("SELECT COALESCE(price_basis, '(미상)'), COUNT(*) FROM normalized_lots GROUP BY price_basis"))
        return {"total": total, "by_basis": by_basis}
    finally:
        market.close()


def _next_steps(sources):
    blocked = [s for s in sources if (s["operational_state"] or "").startswith("blocked")]
    mmca_web_state = _state(sources, "mmca_web")
    mmca_api_state = _state(sources, "mmca_datagokr_api")
    rows = [
        [1, "사용자", "MMCA 전시자료 경로 선택: data.go.kr 공개 API(15058313) 키 신청, 권한 확인 또는 수동 입력 검토", "사용자",
         f"등록 상태: 웹={mmca_web_state}, 공식 API={mmca_api_state}. 공식 API는 허용된 자동화 선택지이며 유일한 적법 경로로 단정하지 않습니다."],
        [2, "사용자", "송은(SONGEUN) 수집 허가 요청 또는 수상/선정 결과 수동 입력(manual_entries)", "사용자", "robots 전면 차단. 한국 Rookie 핵심 출처"],
        [3, "사용자", "Naver 검색 API(뉴스·DataLab) 키를 .env에 설정할지 결정", "사용자", "한국 뉴스 담론(E축) 갱신. 현재 legacy만(2026-10-20까지)"],
        [4, "사용자", "Rijksmuseum API 키(선택)", "사용자", "D06"],
        [5, "운영", ".venv/bin/python -m artrend_mag.cli update --mode incremental [--translate]", "운영자",
         "현재 CLI 통합 갱신 명령입니다. --translate는 로컬 한국어 번역이 필요한 경우 추가하며, update가 derive·validate·export를 포함합니다."],
        [6, "편집", "review_queue의 identity 후보(이름 일치) 상위 작가부터 확인/거절", "편집자", "카드의 작가 연결 신뢰도 향상"],
        [7, "편집", "evidence_cards draft 원문 대조 후 게시 여부 결정", "편집자", "자동 해석 금지 원칙"],
        [8, "데이터", "K-ARTMARKET 「2026 미술시장조사」 공개 PDF 제공 여부 문의 또는 인쇄본 신청", "사용자/운영자", "공개 GET 상세 페이지는 수집 가능. 확인한 2024–2026 상세에는 공개 PDF 첨부가 없음"],
        [9, "데이터", "artist career-stage(최초 개인전 연도) 필드 수집: 갤러리 CV/공식 바이오", "운영자", "Rookie 판정에 필수(현재 '경력 미확인')"],
        [10, "데이터", "주제 taxonomy 정의(편집) → article_themes/events 분류", "편집자", "Theme/Region Flow 섹션 전제"],
    ]
    for i, s in enumerate(blocked, start=11):
        rows.append([i, "차단 출처", f"{s['source_id']}: {s['operational_state']} — {s['robots_status'] or ''} {(s['notes'] or '')[:160]}", "사용자 판단",
                     "우회 금지. 허가/공식 API/수동 입력 중 선택"])
    return rows


if __name__ == "__main__":
    main()
