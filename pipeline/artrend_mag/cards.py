"""Draft evidence cards built only from collected rows. Every card separates facts / comparison /
interpretation / counter-evidence / limitations and lists source URLs. Nothing here is published;
status is always draft_unreviewed. Sections without qualifying evidence get a gap_notice card instead
of filler.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from . import db

REGIONS = ["KR", "JP", "AMERICAS", "EUROPE"]
REGION_KO = {"KR": "한국", "JP": "일본", "AMERICAS": "미주", "EUROPE": "유럽"}
I_KINDS = ("museum", "biennial", "award", "residency", "collection")


def _card(con, asof, region, section, kind, title, facts, limitations, urls, event_ids=None, comparison=None,
          interpretation=None, counter=None, n_indep=None):
    cid = db.sid("card", region, section, title)
    con.execute("INSERT OR REPLACE INTO evidence_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, region, section, kind, title, facts, comparison, interpretation, counter, limitations,
                 json.dumps(event_ids or [], ensure_ascii=False), json.dumps(urls, ensure_ascii=False), n_indep,
                 "draft_unreviewed", asof.isoformat()))
    return 1


def _fmt_event(r):
    d = r["start_date"] or "?"
    if r["end_date"]:
        d += f"~{r['end_date']}"
    where = ", ".join(x for x in (r["org"], r["city"], r["country_code"]) if x)
    return f"{d} | {r['title']} | {where} | 출처 {r['source_id']} | {r['lifecycle']}"


def _live_events(con, where, params):
    return con.execute(
        "SELECT e.*, s.owner_group, s.source_kind, st.lifecycle, o.canonical_name org FROM events e JOIN sources s USING(source_id)"
        " JOIN event_status st USING(event_id) LEFT JOIN entities o ON o.entity_id=e.organizer_entity_id"
        " WHERE e.event_id NOT IN (SELECT event_id FROM event_links WHERE link_type='duplicate_report') AND " + where, params).fetchall()


def build(con, asof: dt.date) -> int:
    con.execute("DELETE FROM evidence_cards")
    a = asof.isoformat()
    d90, d180, d365 = [(asof - dt.timedelta(days=n)).isoformat() for n in (90, 180, 365)]
    p60 = (asof + dt.timedelta(days=60)).isoformat()
    n = 0
    cov = {r["source_id"]: r["mn"] for r in con.execute("SELECT source_id, MIN(earliest_date) mn FROM coverage WHERE record_kind='event' GROUP BY 1")}
    for reg in REGIONS:
        rk = REGION_KO[reg]
        # ---------- H04 exhibitions to watch (fact cards) ----------
        evs = _live_events(con, "e.edition_region=? AND s.source_kind IN ('museum','biennial','collection') AND e.event_type IN ('exhibition','biennial_edition')"
                                " AND s.source_id NOT LIKE 'legacy_%' AND ((st.lifecycle='ongoing') OR (st.lifecycle='upcoming' AND e.start_date<=?))"
                                " ORDER BY (st.lifecycle='ongoing') DESC, e.start_date DESC", (reg, p60))
        picked, seen_owner = [], defaultdict(int)
        for r in evs:
            if seen_owner[r["owner_group"]] >= 2:
                continue
            seen_owner[r["owner_group"]] += 1
            picked.append(r)
            if len(picked) >= 6:
                break
        if picked:
            n += _card(con, asof, reg, "H04", "fact_card", f"[{rk}] 지금 열려 있거나 60일 내 개막하는 기관 전시 {len(picked)}건 (관찰 기관 범위)",
                       "\n".join(_fmt_event(r) for r in picked),
                       "개막 예정 전시는 개최 실적에 합산하지 않음. 관찰 기관 목록 밖 전시는 포함되지 않음. 전시 선정 이유(‘왜 지금’)는 편집자가 원문 확인 후 작성해야 함.",
                       [r["url"] for r in picked if r["url"]], [r["event_id"] for r in picked],
                       interpretation=None, n_indep=len({r['owner_group'] for r in picked}))
        else:
            n += _card(con, asof, reg, "H04", "gap_notice", f"[{rk}] 전시 섹션: 현재/60일 내 기관 전시 근거 없음",
                       "수집된 공식 기관 출처에서 진행 중이거나 60일 내 개막하는 전시가 확인되지 않음.",
                       "수집 실패·차단 출처는 미관측이며 0건을 의미하지 않음.", [])
        # ---------- H01/H02 artists with multiple independent institutional events ----------
        rows = con.execute(
            "SELECT c.cluster_candidate cl, p.name_as_listed nm, e.event_id, e.title, e.start_date, e.end_date, e.city, e.country_code, e.url, e.source_id,"
            " s.owner_group, st.lifecycle, o.canonical_name org, p.extraction_method"
            " FROM event_participants p JOIN events e USING(event_id) JOIN sources s ON s.source_id=e.source_id JOIN event_status st USING(event_id)"
            " JOIN entity_clusters c ON c.entity_id=p.entity_id LEFT JOIN entities o ON o.entity_id=e.organizer_entity_id"
            " WHERE p.role IN ('artist','winner','nominee','finalist','resident') AND e.edition_region=? AND s.source_kind IN (%s)"
            " AND e.start_precision='day' AND e.start_date BETWEEN ? AND ? AND st.lifecycle NOT IN ('cancelled','postponed','upcoming')"
            " AND e.event_type<>'acquisition' AND e.event_id NOT IN (SELECT event_id FROM event_links WHERE link_type IN ('duplicate_report','tour_candidate'))"
            % ",".join("?" * len(I_KINDS)), (reg, *I_KINDS, d180, a)).fetchall()
        by = defaultdict(list)
        for r in rows:
            by[r["cl"]].append(r)
        cands = []
        for cl, items in by.items():
            groups = {i["owner_group"] or i["source_id"] for i in items}
            evset = {i["event_id"] for i in items}
            if len(groups) >= 2 and len(evset) >= 2:
                cands.append((len(groups), max(i["start_date"] for i in items), cl, items))
        cands.sort(key=lambda x: (-x[0], x[1]), reverse=False)
        cands.sort(key=lambda x: (-min(x[0], 5), x[1] and -int(x[1].replace("-", ""))))
        for ng, last, cl, items in cands[:5]:
            names = sorted({i["nm"] for i in items})
            uniq = {i["event_id"]: i for i in items}.values()
            recent = [i for i in uniq if i["start_date"] >= d90]
            prev = [i for i in uniq if i["start_date"] < d90]
            comparable = all((cov.get(i["source_id"]) or "9999") <= d180 for i in uniq)
            comp = (f"최근 90일 {len(recent)}건 vs 직전 90일 {len(prev)}건 (같은 출처 범위)" if comparable else
                    f"최근 90일 {len(recent)}건 / 직전 90일 {len(prev)}건 — 일부 출처의 과거 자료가 직전 구간을 덮지 못해 증감 비교 불가")
            weak = any(i["extraction_method"] == "title_pattern" for i in uniq)
            n += _card(con, asof, reg, "H02", "observation_card",
                       f"[{rk}] {names[0]}: 최근 180일 {ng}개 독립 기관 계열에서 {len(uniq)}건의 기관 사건 관찰",
                       "\n".join(_fmt_event(i) for i in sorted(uniq, key=lambda x: x["start_date"])),
                       "이름 일치 기반 연결(동명이인 가능)" + ("; 일부 참여자는 전시 제목 패턴에서 추출(신뢰도 중)" if weak else "") +
                       "; 그룹전 참여와 개인전을 같은 무게로 보지 않음; 관찰 기관 밖 사건 미포함.",
                       [i["url"] for i in uniq if i["url"]], [i["event_id"] for i in uniq], comparison=comp,
                       interpretation="서로 다른 소유 그룹의 기관 선택이 반복 관찰됨(가설). ‘주목 증가’ 판단에는 같은 패널의 기준선과 비교군 분포가 필요함.",
                       counter="같은 재단·순회전이 아닌지, 소장품전 재배치인지 원문 확인 필요.", n_indep=ng)
        if not cands:
            n += _card(con, asof, reg, "H02", "gap_notice", f"[{rk}] 작가 포커스: 독립 기관 2곳 이상 근거를 가진 작가 없음",
                       "최근 180일 수집 범위에서 2개 이상 독립 기관 계열의 사건을 가진 작가가 확인되지 않음.",
                       "출처 수가 적거나 참여작가 필드가 없는 출처가 많아 생기는 결과일 수 있음(미관측≠부재).", [])
        # ---------- H07 rookie watch ----------
        rk_rows = con.execute(
            "SELECT c.cluster_candidate cl, p.name_as_listed nm, p.role, e.event_id, e.title, e.event_type, e.start_date, e.end_date, e.url, e.source_id, s.owner_group,"
            " st.lifecycle, o.canonical_name org, e.city, e.country_code FROM event_participants p JOIN events e USING(event_id) JOIN sources s ON s.source_id=e.source_id"
            " JOIN event_status st USING(event_id) JOIN entity_clusters c ON c.entity_id=p.entity_id LEFT JOIN entities o ON o.entity_id=e.organizer_entity_id"
            " WHERE e.edition_region=? AND (e.event_type IN ('residency','open_call_selection','award') OR (s.source_kind IN ('residency','award') ))"
            " AND p.role IN ('artist','winner','nominee','finalist','resident','selected') AND COALESCE(e.start_date, e.announced_date, '') >= ?"
            " AND s.source_id NOT LIKE 'legacy_%'", (reg, d365)).fetchall()
        rk_by = defaultdict(list)
        for r in rk_rows:
            rk_by[r["cl"]].append(r)
        shown = 0
        for cl, items in sorted(rk_by.items(), key=lambda kv: max((i["start_date"] or "") for i in kv[1]), reverse=True):
            other = con.execute(
                "SELECT DISTINCT e.event_id, e.title, e.start_date, e.event_type, s.owner_group, e.edition_region, e.url FROM event_participants p"
                " JOIN entity_clusters c ON c.entity_id=p.entity_id JOIN events e USING(event_id) JOIN sources s ON s.source_id=e.source_id"
                " WHERE c.cluster_candidate=? AND e.start_date>=?", (cl, d365)).fetchall()
            groups = {o["owner_group"] for o in other}
            types = {o["event_type"] for o in other}
            stage = "편집 검토 가능(12개월 내 독립 주체 2+·사건유형 2+)" if len(groups) >= 2 and len(types) >= 2 else "관찰 후보(단일 주체 선정)"
            i0 = items[0]
            n += _card(con, asof, reg, "H07", "rookie_watch", f"[{rk}] Rookie 관찰: {i0['nm']} — {i0['org'] or i0['source_id']}의 {i0['event_type']} ({(i0['start_date'] or '날짜미상')[:10]})",
                       "\n".join(f"{(o['start_date'] or '?')[:10]} | {o['title']} | {o['event_type']} | {o['owner_group']} | {o['edition_region']}" for o in other),
                       "경력 단계는 확인하지 않음(최초 개인전 이력 미수집) → ‘경력 미확인’. 나이·경매 부재로 신진 여부를 판단하지 않음. 선정 사실 1건은 관찰 후보일 뿐 Rookie 확정이 아님.",
                       sorted({o["url"] for o in other if o["url"]}), [o["event_id"] for o in other], comparison=f"판정: {stage}",
                       counter="중견 재발견(Rediscovery)일 가능성 확인 필요.", n_indep=len(groups))
            shown += 1
            if shown >= 4:
                break
        if not shown:
            n += _card(con, asof, reg, "H07", "gap_notice", f"[{rk}] Rookie: 최근 12개월 공식 선정·레지던시·수상 근거 없음",
                       "수집된 공식 프로그램 출처에서 최근 12개월 선정/레지던시/수상 사건이 확인되지 않음.",
                       "송은(robots 전면 차단) 등 핵심 신진지원 출처가 미수집이면 이 결과는 부재가 아니라 미관측임.", [])
        # ---------- H05 gallery moves ----------
        g = _live_events(con, "e.edition_region=? AND s.source_kind='gallery' AND s.source_id NOT LIKE 'legacy_%' AND e.start_date BETWEEN ? AND ?"
                              " ORDER BY e.start_date DESC", (reg, (asof - dt.timedelta(days=30)).isoformat(), a))
        rel = con.execute("SELECT COUNT(*) FROM relationships r JOIN sources s USING(source_id) WHERE s.region_scope IN (?, 'GLOBAL')", (reg,)).fetchone()[0]
        if g:
            n += _card(con, asof, reg, "H05", "fact_card", f"[{rk}] 최근 30일 관찰 갤러리의 개막 전시 {len(g)}건",
                       "\n".join(_fmt_event(r) for r in g[:8]),
                       "신규 대표관계는 판단 불가: 갤러리 작가 명단은 이번 수집이 첫 관측이라 ‘새로 추가됨’과 ‘기존부터 있었음’을 구분할 수 없음(첫 관측≠신규 대표). 같은 갤러리 그룹의 여러 지점은 1개 주체.",
                       [r["url"] for r in g[:8] if r["url"]], [r["event_id"] for r in g[:8]],
                       comparison=f"작가 명단 관계 {rel}건은 기준선(스냅샷 1회)으로만 저장됨", n_indep=len({r['owner_group'] for r in g}))
        else:
            n += _card(con, asof, reg, "H05", "gap_notice", f"[{rk}] 갤러리 무브: 최근 30일 근거 부족",
                       "최근 30일 관찰 갤러리의 개막 전시 또는 공식 대표 발표가 수집되지 않음.",
                       "대표관계 변화는 최소 2회 이상의 명단 스냅샷 또는 공식 발표문이 있어야 판단 가능.", [])
    # ---------- H06 cross-region (one global set, attached to each region involved) ----------
    rows = con.execute(
        "SELECT c.cluster_candidate cl, p.name_as_listed nm, e.event_id, e.title, e.start_date, e.end_date, e.city, e.country_code, e.edition_region reg,"
        " e.url, e.source_id, s.owner_group, st.lifecycle, o.canonical_name org FROM event_participants p JOIN events e USING(event_id)"
        " JOIN sources s ON s.source_id=e.source_id JOIN event_status st USING(event_id) JOIN entity_clusters c ON c.entity_id=p.entity_id"
        " LEFT JOIN entities o ON o.entity_id=e.organizer_entity_id WHERE p.role IN ('artist','winner','resident','nominee') AND e.start_precision='day'"
        " AND e.start_date BETWEEN ? AND ? AND e.edition_region IN ('KR','JP','AMERICAS','EUROPE') AND st.lifecycle NOT IN ('cancelled','postponed','upcoming')"
        " AND s.source_kind IN ('museum','biennial','award','residency','collection') AND e.event_type<>'acquisition'"
        " AND e.event_id NOT IN (SELECT event_id FROM event_links WHERE link_type IN ('duplicate_report','tour_candidate'))", (d365, a)).fetchall()
    by = defaultdict(list)
    for r in rows:
        by[r["cl"]].append(r)
    flows = []
    for cl, items in by.items():
        regs = {i["reg"] for i in items}
        groups = {i["owner_group"] for i in items}
        if len(regs) >= 2 and len(groups) >= 2:
            flows.append((len(regs), len(groups), cl, items))
    flows.sort(key=lambda x: (-x[0], -x[1]))
    for nr, ng, cl, items in flows[:6]:
        items = sorted({i["event_id"]: i for i in items}.values(), key=lambda x: x["start_date"])
        nm = items[0]["nm"]
        regs = sorted({i["reg"] for i in items})
        for reg in regs:
            n += _card(con, asof, reg, "H06", "observation_card",
                       f"[{REGION_KO[reg]}] 지역 간 흐름: {nm} — 12개월 내 {nr}개 지역({', '.join(REGION_KO[x] for x in regs)}) {ng}개 독립 기관 계열",
                       "\n".join(f"{i['start_date']} | {i['reg']} | {i['title']} | {i['org'] or i['source_id']} | {i['city'] or ''}" for i in items),
                       "시간 순서는 관찰 순서일 뿐 영향·인과를 의미하지 않음. 순회전 후보(같은 제목)는 제외했으나 공동기획 여부는 원문 확인 필요. 이름 일치 기반 연결.",
                       [i["url"] for i in items if i["url"]], [i["event_id"] for i in items],
                       comparison="직전 12개월과의 비교는 대부분 출처의 과거 자료 부족으로 불가", counter="각 기관이 같은 갤러리·재단 네트워크를 통해 연결됐을 가능성.",
                       n_indep=ng)
    # ---------- H08 market context ----------
    rep = con.execute("SELECT report_id, title, observation_period, pages, official_url FROM reports WHERE access_status='downloaded'").fetchall()
    for reg, rids in (("JP", ("JAM2025_en",)), ("KR", ()), ("AMERICAS", ("AMR2026",)), ("EUROPE", ("AMR2026",))):
        mets = con.execute("SELECT report_id, page, excerpt FROM report_metrics WHERE report_id IN (%s) ORDER BY report_id, CAST(page AS INT) LIMIT 4"
                           % ",".join("?" * len(rids)), rids).fetchall() if rids else []
        if mets:
            n += _card(con, asof, reg, "H08", "fact_card", f"[{REGION_KO[reg]}] 시장 참고: 공개 보고서 헤드라인(관측연도 명시)",
                       "\n".join(f"{m['report_id']} p.{m['page']}: {m['excerpt']}" for m in mets),
                       "보고서 수치는 조사 정의(딜러+경매 / 경매만, 수수료 포함 여부, 표본)가 서로 달라 단순 비교 불가. 작가 트렌드 점수에 합산하지 않음. 자동 추출 문장이므로 원문 쪽수 대조 후 인용.",
                       [r["official_url"] for r in rep if r["report_id"] in rids])
        else:
            n += _card(con, asof, reg, "H08", "gap_notice", f"[{REGION_KO[reg]}] 시장 참고: 자동 수집된 최신 공식 보고서 수치 없음",
                       "예술경영지원센터 「2026 미술시장조사」(2025년 기준)는 목록만 확인(상세 다운로드가 POST 양식이라 자동화하지 않음).",
                       "수동 내려받기 후 표·쪽수 단위로 입력 필요.", ["https://k-artmarket.kr/member/board/Analysis_BoardList.do"])
    return n
