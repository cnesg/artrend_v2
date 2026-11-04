"""Obsidian mock-up of the ARTREND home per edition (Blueprint H00–H09) from a `frontpage.FrontPage` snapshot.

Layout follows the Blueprint section order with the reading devices of the 한장요약 W42 one-pager (사실 → 그래서? →
숫자로 본 한 주 → 다가오는 일정 → 낯선 말). Cards are Obsidian callouts; `artrend-home.css` (written to the vault's
snippets) turns them into a magazine grid, and without the snippet they still read as plain callouts.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional

from .frontpage import FRONT_EDITIONS, MIN_COVERAGE, pct

EDITION_KO = {"KR": "한국", "JP": "일본", "AMERICAS": "미주", "EUROPE": "유럽"}
EDITION_EN = {"KR": "KOREA", "JP": "JAPAN", "AMERICAS": "AMERICAS", "EUROPE": "EUROPE"}
WEEKDAY = "월화수목금토일"
MEANING = {
    "활동 확산": "관찰 범위에서는 서로 다른 기관·갤러리가 같은 방향의 선택을 한 것으로 읽힙니다. 원인이나 시장 영향은 이 숫자만으로 알 수 없습니다.",
    "보도 집중": "관찰 범위에서는 이 주제에 대한 보도 관심이 평소보다 커진 것으로 읽힙니다. 기사량은 시장 규모나 판매와 다른 지표입니다.",
    "새로운 징후": "추세라고 부를 비교 근거는 아직 부족합니다. 같은 움직임이 다음 창에서도 이어지는지 확인합니다.",
    "주요 소식": "단일 소식입니다. 서로 다른 사건이나 비교 가능한 추세 근거가 확인되기 전까지 트렌드로 부르지 않습니다.",
}
GLOSSARY = {
    "활동 확산": "서로 다른 기관·갤러리의 공식 사건(전시·선정 등)에서 같은 주제가 늘어난 경우(HL08). 사건 3건·실행 주체 2곳·비교 패널 20건·coverage 80%·비중 +2%p·1.5배 이상.",
    "보도 집중": "같은 주제를 다룬 독립 원전이 관찰 매체 패널 안에서 평소보다 많아진 경우(HL07). 한 사건을 50곳이 보도해도 활동 50건이 아닙니다.",
    "새로운 징후": "사건·주체가 2곳 이상 보이지만 비교 이력이나 표본이 부족해 추세로 판정하지 않은 관찰.",
    "주요 소식": "중요해 보이지만 여러 사건·추세 근거가 없는 단일 소식.",
    "원전": "같은 글의 재전재·번역을 하나로 묶은 기사 묶음. 지금은 제목 유사도로 근사하며 본문으로 확인하지 않았습니다.",
    "매체그룹": "기사를 낸 매체의 소유 그룹. 그룹 정보가 없으면 매체(도메인) 자체를 그룹으로 셉니다(실제보다 많게 셀 수 있음).",
    "coverage": "비교 기간 동안 관찰 패널 출처가 실제로 관측된 비율. 80% 미만이면 숫자 비교를 보류합니다.",
    "평소": "직전 4주(4개의 겹치지 않는 7일 창)의 평균.",
    "%p": "비율끼리의 차이. 10%→12%는 +2%p(20% 증가와 다름).",
    "I·G·E 축": "I=기관 전시·선정, G=갤러리 전시·페어, E=독립 비평·보도 언급. 관측이 안 된 축은 증가로 세지 않습니다.",
}


def q(lines: List[str], depth: int = 1) -> List[str]:
    p = "> " * depth
    return [f"{p}{x}" if x else p.rstrip() for x in lines]


def callout(kind: str, title: str, body: List[str], fold: str = "", depth: int = 1) -> List[str]:
    return q([f"[!{kind}]{fold} {title}"] + body, depth)


def grid(cards: List[List[str]], kind: str = "grid") -> List[str]:
    """Nested callouts inside one grid callout (blank quoted line between children)."""
    out = [f"> [!{kind}]"]
    for i, c in enumerate(cards):
        if i:
            out.append(">")
        out += q(c, 1)
    return out


def bar(x: float, width: int = 20) -> str:
    n = max(0, min(width, round(x * width)))
    return "█" * n + "░" * (width - n)


class Renderer:
    def __init__(self, vb, snap: dict):
        self.vb, self.s = vb, snap
        self.R = snap["region"]
        self.label = EDITION_KO[self.R]

    # -- small helpers
    def ev(self, ev: dict) -> str:
        return self.vb.event_link(ev["event_id"])

    def venue(self, ev: dict) -> str:
        return self.vb.venue_text(ev)

    def ent(self, eid: str) -> str:
        return self.vb.entity_link(eid)

    def art(self, a: dict, limit: int = 90) -> str:
        return self.vb.story_title(a, limit)

    def src(self, a: dict) -> str:
        return self.vb.source_label(a)

    def ko(self, a: dict) -> str:
        from .obsidian_vault import useful_ko
        k = useful_ko(self.vb.ko_of("articles", a["article_id"], "title", a["title"]))
        return f" — _{k}_ (자동번역·검수 전)" if k else ""

    # -- sections
    def masthead(self) -> List[str]:
        T = dt.datetime.fromisoformat(self.s["T"])
        tabs = " · ".join(f"**{EDITION_KO[e]}**" if e == self.R else f"[[ARTREND {EDITION_KO[e]} 홈|{EDITION_KO[e]}]]" for e in FRONT_EDITIONS)
        menu = " · ".join(f"[[#{h}|{h}]]" for h in ("한눈에", "핵심 정리 — 이번 주 주요 소식", "TODAY'S INSIGHT", "ARTISTS IN FOCUS", "TREND NEWS", "EXHIBITIONS TO WATCH",
                                                     "GALLERY MOVES", "EMERGING PATTERNS", "ROOKIE RADAR", "MARKET CONTEXT"))
        return callout("masthead", f"ARTREND · {EDITION_EN[self.R]}", [
            f"{T:%Y.%m.%d} ({WEEKDAY[T.weekday()]}) 07:00 KST 집계 · 지역판 {tabs}",
            "",
            menu,
        ]) + ["", "> [!draft] 내부 목업 · 자동 계산 초안 · `publishable=0` — 문장은 계산값을 넣은 고정 문형이며 편집 승인 전입니다.", ""]

    def headline(self) -> List[str]:
        out = ["## TODAY'S INSIGHT", ""]
        cards = self.s["headline"]
        if not cards:
            return out + callout("empty", "오늘의 인사이트 없음", [
                "자격을 통과한 변화도, 최근 24시간의 주요 소식도 없습니다. 빈칸을 채우려고 문장을 만들지 않습니다(QA05)."]) + [""]
        hero, subs = cards[0], cards[1:]
        out += self.headline_card(hero, "hero") + [""]
        if subs:
            out += grid([self.headline_card(c, "card", nested=True) for c in subs]) + [""]
        return out

    def headline_card(self, c: dict, kind: str, nested: bool = False) -> List[str]:
        m, R = c["metric"], self.label
        if c["basis"] == "activity":
            w = m["window"]
            title = (f"{R} 기관·갤러리에서 '{c['topic']}' 실행 사례 확산" if c["kind"] == "활동 확산"
                     else f"'{c['topic']}' — 최근 {w}일 {m['orgs']}개 주체에서 새로 관찰")
            fact = (f"최근 {w}일 관찰 기관의 공식 사건 {m['e']}건(실행 주체 {m['orgs']}곳)이 '{c['topic']}'에 해당합니다. "
                    f"동종 사건 중 비중 {pct(m['share'])}, 직전 4개 창 평균 {pct(m['base_share'])}.")
            nums = [("사건", f"{m['e']}건"), ("실행 주체", f"{m['orgs']}곳")]
            ev = [f"- {e['_day']} · {self.ev(e)} — {self.venue(e)}" for e in m["events"][:4]]
            caveat = "판정 보류 조건: " + "; ".join(m["fails"]) if m["fails"] else "주제 태그는 제목 키워드 사전 기준입니다."
        elif c["basis"] == "press":
            title = (f"{R} 미술 보도에서 '{c['topic']}' 비중 확대" if c["kind"] == "보도 집중"
                     else f"'{c['topic']}' 보도가 새로 등장")
            fact = (f"최근 7일 관찰 패널 소식 {self.s['press']['n'][0]}개 중 {m['a']}개(매체그룹 {m['groups']}곳)가 "
                    f"'{c['topic']}'을 다뤘습니다. 비중 {pct(m['base_share'])} → {pct(m['share'])}.")
            nums = [("이번 주 비중", pct(m["share"])), ("평소", pct(m["base_share"]))]
            ev = []
            for st in m["stories"][:4]:
                lead = max(st, key=lambda a: len(a["title"] or ""))
                ev.append(f"- {lead['published_at'][:10]} · {self.art(lead)} — {self.src(lead)}" + (f" 외 {len(st) - 1}건" if len(st) > 1 else ""))
            caveat = ("제목만 확보(T)해 같은 보도자료의 재전재일 수 있습니다. 원전·매체그룹 수는 상한값입니다."
                      + (" 판정 보류 조건: " + "; ".join(m["fails"]) if m["fails"] else ""))
        elif c["basis"] == "artist":
            title = f"{self.vb.entities[c['entity_id']]['canonical_name']} — 28일 동안 {m['orgs']}개 기관·갤러리에서 소개"
            fact = f"최근 28일 공식 사건 {len(m['events'])}건, 서로 다른 실행 주체 {m['orgs']}곳에서 이름이 확인됩니다."
            nums = [("사건", f"{len(m['events'])}건"), ("주체", f"{m['orgs']}곳")]
            ev = [f"- {e['_day']} · {self.ev(e)} — {self.venue(e)}" for e in sorted(m["events"], key=lambda e: e["_day"], reverse=True)[:4]]
            caveat = "이름이 같다는 사실만으로 동일인을 확정하지 않았습니다. 순회전·같은 그룹 지점인지 확인이 필요합니다."
        else:
            lead = m["lead"]
            title = (lead["title"] or "")[:70]
            n_out = len(m["outlets"])
            fact = (f"{lead['published_at'][:10]} · {self.src(lead)}" + (f" 등 {n_out}개 매체 보도" if n_out > 1 else " 단독 보도")
                    + f" · {m['topic_label']}")
            nums = [("매체", f"{len(m['outlets'])}곳")]
            ev = [f"- {self.art(a)} — {self.src(a)}" for a in m["members"][:4]]
            caveat = "제목·날짜만 확보했습니다. 본문 사실(금액·날짜)은 원문으로 확인합니다."
        head = f"{c['kind']} · {'공식 사건' if c['basis'] in ('activity', 'artist') else '보도'} · 07:00 집계"
        body = [f"### {title}", "", f"**사실** {fact}", "", f"**그래서?** {MEANING[c['kind']]}", ""]
        body += [" · ".join(f"**{v}** {k}" for k, v in nums[:2]), "", f"<small>한계: {caveat}</small>", ""]
        body += callout("evidence", f"근거 보기 ({len(ev)})", ev, fold="-", depth=1)
        return callout(kind, head, body)

    def weekly(self) -> List[str]:
        w, p = self.s["weekly"], self.s["press"]
        out = ["### 숫자로 본 한 주", ""]

        def change(cur, base):
            if base in (None, 0):
                return "평소 비교 불가"
            return f"평소 {base:,.0f} · {((cur - base) / base) * 100:+.0f}%"

        stats = [callout("stat", "이번 주 소식(같은 기사 묶음)", [f"## {w['stories']:,}", change(w["stories"], w["base"])])]
        if w["top"]:
            t = w["top"]
            base = sum(t["base_counts"]) / 4
            stats.append(callout("stat", "가장 많이 다룬 주제", [f"## {t['label']}", f"{t['a']}개 소식 · {change(t['a'], base)}"]))
        if w["market"]:
            t = w["market"]
            stats.append(callout("stat", "경매·시장 소식", [f"## {t['a']}", change(t["a"], sum(t["base_counts"]) / 4)]))
        out += grid(stats) + [""]
        notes = [f"관찰 패널 {len(p['panel'])}곳 · coverage {pct(p['coverage'])}"
                 + (" — 80% 미만이라 평소 대비 숫자는 참고만 합니다" if (p["coverage"] or 0) < MIN_COVERAGE else "")]
        if w["seasonal"]:
            notes.append("시즌 행사와 겹침(HL11): " + ", ".join(w["seasonal"]) + " — 행사 주간에는 기사가 몰립니다")
        notes.append("기사량 증가는 시장이 커졌다는 뜻이 아닙니다. 위스키·시계 등 비미술 경매는 뺐습니다")
        return out + [f"<small>숫자 주의: {' · '.join(notes)}.</small>", ""]

    def topics(self) -> List[str]:
        rows = [t for t in self.s["press"]["topics"] if not t["key"].startswith("entity:")]
        rows.sort(key=lambda t: -t["a"])
        if not rows:
            return []
        chips = []
        for t in rows[:12]:
            base = sum(t["base_counts"]) / 4
            arrow = "▲" if t["a"] > base * 1.25 else ("▼" if t["a"] < base * 0.75 else "")
            chips.append(f"`{t['label']} {t['a']}{arrow}`")
        return ["### TRENDING TOPICS", "", " ".join(chips), "", "<small>최근 7일 관찰 패널 소식 수 · ▲▼ 평소보다 25% 이상 많음/적음 · 제목 키워드 기준</small>", ""]

    def focus(self) -> List[str]:
        f = self.s["focus"]
        out = ["## ARTISTS IN FOCUS", ""]
        if f["selected"]:
            cards = []
            for r in f["selected"]:
                ax = " · ".join(f"{k} {c}(직전 {p})" for k, (c, p) in r["axes"].items())
                trig = r["trigger"][0]
                cards.append(callout("artist", self.vb.entities[r["entity_id"]]["canonical_name"], [
                    self.ent(r["entity_id"]), "", f"90일 {ax}", "", f"계기: {trig['_day']} {self.ev(trig)}"]))
            out += grid(cards, "grid3") + [""]
        else:
            out += callout("empty", "자격을 통과한 작가 없음", [
                f"평가한 작가 {f['evaluated']}명 중 FP04 조건(90일 사건 3·독립 주체 2·관측된 축 2개 증가·30일 새 계기·coverage 80%)을 모두 충족한 작가가 없습니다.",
                "근거 없는 작가로 칸을 채우지 않습니다. 아래 후보 큐는 무엇이 모자란지 보여 줍니다."]) + [""]
        if f["near"]:
            body = ["| 작가 | 90일 사건 | 독립 주체 | 축(현재/직전) | 모자란 조건 |", "|---|---:|---:|---|---|"]
            for r in f["near"]:
                ax = ", ".join(f"{k} {c}/{p}" for k, (c, p) in r["axes"].items())
                body.append(f"| {self.vb.entity_link(r['entity_id'], in_table=True)} | {r['recent']} | {r['groups']} | {ax} | {'; '.join(r['fails'])} |")
            out += callout("queue", f"후보 큐 — 조건에 가까운 작가 {len(f['near'])}명", body, fold="-") + [""]
        return out

    def news(self) -> List[str]:
        n = self.s["news"]
        out = ["## TREND NEWS", ""]
        if not n["cards"]:
            return out + callout("empty", "최근 14일 트렌드 관련 뉴스 없음", ["최신 공지를 트렌드로 바꿔 올리지 않습니다(FP05)."]) + [""]
        label = {"direct_evidence": "인사이트 직접 근거", "contextual": "관찰 대상 관련", "mention": "기타"}
        first, rest = n["cards"][0], n["cards"][1:]
        s = first["story"]
        lead = s["lead"]
        out += callout("lead", f"{label[first['relation']]} · {s['topic_label']}", [
            f"### {self.art(lead, 110)}", f"{lead['published_at'][:10]} · {self.src(lead)}" + (f" 외 {len(s['outlets']) - 1}곳" if len(s["outlets"]) > 1 else "") + self.ko(lead),
            "", "왜: " + (" · ".join(s["reasons"]) or "최신순")]) + [""]
        if rest:
            cards = []
            for r in rest:
                st = r["story"]
                cards.append(callout("news", f"{label[r['relation']]} · {st['topic_label']}", [
                    f"**{self.art(st['lead'], 80)}**", f"{st['lead']['published_at'][:10]} · {self.src(st['lead'])}" + (f" 외 {len(st['outlets']) - 1}곳" if len(st["outlets"]) > 1 else "")]))
            out += grid(cards, "grid3") + [""]
        for eid, stories in n["views"]:
            body = [f"- {self.art(x['lead'])} — {self.src(x['lead'])}" for x in stories[:3]]
            out += callout("view", f"비평의 관점 — {self.vb.entities[eid]['canonical_name']}", body + ["", "논지 차이는 원문을 읽고 편집자가 정리합니다."]) + [""]
        return out

    def exhibitions(self) -> List[str]:
        x = self.s["exhibitions"]
        d = dt.date.fromisoformat(self.s["asof"]) - dt.timedelta(days=1)
        out = ["## EXHIBITIONS TO WATCH", ""]
        if x["cards"]:
            cards = []
            for r in x["cards"]:
                ev = r["event"]
                if r["current"]:
                    status = f"진행 중 · 종료 D-{(r['end'] - d).days}" if r["end"] else "진행 중"
                else:
                    status = f"개막 예정 · D-{(r['start'] - d).days}"
                cards.append(callout("expo", status, [f"**{self.ev(ev)}**", self.venue(ev),
                                                     f"{ev['start_date']} ~ {ev['end_date'] or '?'}", "", "왜 지금: " + " · ".join(r["why"])]))
            out += grid(cards, "grid3") + [""]
        else:
            out += callout("empty", "직접 연결 근거가 있는 전시 없음", [f"진행 중·60일 내 개막 후보 {x['candidates']}건 중 보도·인사이트·주목 작가와 연결된 전시가 없습니다."]) + [""]
        cities = " · ".join(f"{c} {k}" for c, k in x["cities"])
        out += [f"**오늘 열린 전시 {x['open_now']}건** (관찰 기관·갤러리, 일 단위 기간 확인분)" + (f" — {cities}" if cities else ""), ""]
        return out

    def galleries(self) -> List[str]:
        g = self.s["galleries"]
        out = ["## GALLERY MOVES", ""]
        if g["cards"]:
            cards = []
            for r in g["cards"]:
                ev = r["event"]
                who = ", ".join(self.ent(p["entity_id"]) for p in r["artists"][:3]) or "참여 작가 미추출"
                body = [f"**{self.ev(ev)}**", f"{self.venue(ev)} · {ev['_day']} 개막", "", f"작가: {who}"]
                if r["follow"]:
                    p, inst = r["follow"][0]
                    body.append(f"외부 기관 연결: {self.ent(p['entity_id'])} — {self.vb.event_link(inst['event_id'])}")
                cards.append(callout("gallery", "새 개인전·프로그램", body))
            out += grid(cards, "grid2") + [""]
        else:
            out += callout("empty", "최근 30일 갤러리 변화 없음", ["관찰 갤러리의 새 전시가 확인되지 않았습니다."]) + [""]
        out += [f"<small>소속 명단 {g['roster']:,}건은 2026-10-27~28 첫 관측입니다. 첫 관측은 새 대표 관계의 증거가 아니라서 '신규 소속' 카드는 다음 비교 관측 뒤에 나옵니다(FP07).</small>", ""]
        return out

    def patterns(self) -> List[str]:
        p = self.s["patterns"]
        out = ["## EMERGING PATTERNS", ""]
        if p["fails"]:
            out += callout("empty", "비교 표본 부족 — 섹션 숨김 대상", ["; ".join(p["fails"])]) + [""]
        elif p["topics"]:
            cards = []
            for t in p["topics"]:
                ex = [f"- {e['_day']} · {self.ev(e)}" for e in t["examples"]]
                cards.append(callout("pattern", f"{t['topic']} {t['delta'] * 100:+.1f}%p", [
                    f"`{bar(t['s0'])}` 직전 90일 {pct(t['s0'])} ({t['prev']}건)",
                    f"`{bar(t['s1'])}` 최근 90일 {pct(t['s1'])} ({t['cur']}건)", ""] + ex))
            out += grid(cards, "grid2") + [""]
            out += [f"<small>전시 사건 {p['n_cur']}건/{p['n_prev']}건 기준 점유율. 한 전시가 여러 주제에 속할 수 있어 합계가 100%를 넘을 수 있습니다.</small>", ""]
        else:
            up = [t for t in p["all_topics"] if t["delta"] > 0][:3]
            out += callout("empty", "주제 패턴 카드 없음", [
                f"최근/직전 90일 전시 {p['n_cur']}/{p['n_prev']}건에서 점유율이 늘고 3건·2기관 이상인 주제가 없습니다."
                + (" 늘어난 주제(표본 부족): " + ", ".join(f"{t['topic']} {t['prev']}→{t['cur']}건" for t in up) if up else "")]) + [""]
        for c in p["spread"]:
            out += callout("spread", "지역 간 흐름", [self.vb.card_link(c)] + [f"- {x}" for x in (c.get("facts") or "").splitlines()[:3]], fold="-") + [""]
        return out

    def rookie(self) -> List[str]:
        r = self.s["rookie"]
        out = ["## ROOKIE RADAR", ""]
        if r["ready"]:
            cards = []
            for x in r["ready"]:
                ev = x["events"][:3]
                cards.append(callout("rookie", self.vb.entities[x["entity_id"]]["canonical_name"], [
                    self.ent(x["entity_id"]), "", f"선정·지원 주체 {x['orgs']}곳 · 유형 {', '.join(x['types'])}"] +
                    [f"- {e['_day']} · {self.ev(e)}" for e in ev] + ["", "<small>첫 개인전 연도 미확인 — 편집 검토 대상</small>"]))
            out += grid(cards, "grid2") + [""]
        else:
            out += callout("empty", "Rookie 검토 조건 충족 작가 없음", [
                f"최근 12개월 공식 선정·레지던시·시상 관찰 후보 {r['candidates']}명. 12개월 내 2주체·2유형 조건을 채운 작가가 없어 홈에 올리지 않습니다(FP09)."]) + [""]
        return out

    def market(self) -> List[str]:
        m = self.s["market"]
        out = ["## MARKET CONTEXT", ""]
        if not (m["auction"] or m["report"]):
            return out + callout("empty", "비교 가능한 시장 자료 없음 — 섹션 숨김 대상", ["새 보고서도, 이 지역의 비교 가능한 경매 표본도 없습니다."]) + [""]
        body = []
        if m["auction"]:
            a = m["auction"]
            c, p = a["cur"], a["prev"]
            body += [f"**공개 경매 결과(보조 지표)** — 최신 관측 {a['latest']}", "",
                     "| 구간 | 출품 | 낙찰 | 낙찰률 | 수수료 포함 중앙값(USD) |", "|---|---:|---:|---:|---:|"]
            for lab, s in (("최근 6개월", c), ("1년 전 같은 기간", p)):
                med = f"{s['median']:,.0f} (n={s['n_price']})" if s["median"] else "—"
                body.append(f"| {lab} {s['start']}~{s['end']} | {s['offered']:,} | {s['sold']:,} | {pct(s['sell_through'])} | {med} |")
            body += ["", "<small>경매사 공개 결과만 · 해머가와 수수료 포함가는 섞지 않음 · 가을 시즌 결과 미수집 · 가격을 예술적 가치나 투자 신호로 읽지 않습니다.</small>"]
        if m["report"]:
            r = m["report"]
            body += ["", f"**보고서** {self.vb.report_link(r)} — 발행 {r['published_date'] or '?'} · 관측기간 {r['observation_period'] or '미기재'}"]
        return out + callout("market", "시장 참고 · 위 트렌드 점수에 합산하지 않음", body) + [""]

    def upcoming(self) -> List[str]:
        up = self.s["weekly"]["upcoming"]
        if not up:
            return []
        return ["## 다가오는 일정", "", "<small>관찰 기관·갤러리 공식 일정 기준 — 바뀔 수 있으니 원문을 확인하세요.</small>", ""] + [
            f"- **{e['_day'].month}월 {e['_day'].day}일({WEEKDAY[e['_day'].weekday()]})** {self.ev(e)} — {self.venue(e)}" for e in up] + [""]

    def method(self) -> List[str]:
        p, a = self.s["press"], self.s["activity"]
        audit = self.s["audit"]
        passed = sum(x["passed"] for x in audit)
        lines = ["## 방법과 관찰 범위", "",
                 f"- 집계 마감 {self.s['T']} · 오늘 유입 = 직전 24시간 · 추세 = 7일 · 평소 = 직전 4주(겹치지 않는 7일 창). 사건은 28일 창도 함께 봅니다(HL02·HL08).",
                 f"- 보도 패널: 4주 기준 구간에 기사가 있는 정기 수집 출처 {len(p['panel'])}곳 · coverage {pct(p['coverage'])} · 주별 소식 {p['n'][::-1]} (오래된 주 → 이번 주). 원본 일괄 가져오기(legacy)는 패널에서 뺐습니다.",
                 f"- 사건 패널: 28일 창 동종 사건 {a[28]['n'][::-1]} · coverage {pct(a[28]['coverage'])}.",
                 "- 에디션은 개최지 기준. 해외 매체 기사는 이 지역 관찰 대상의 이름이 제목에 있을 때만 붙입니다(HL05).",
                 f"- 후보 판정 {len(audit):,}건 중 통과 {passed:,}건 — 탈락 사유 전체: [[선발 기록 ({self.label})]].",
                 "- 문턱값은 모두 검증 전 초기 가정입니다(HL16). 같은 입력이면 같은 결과가 나옵니다(QA05).", ""]
        lines += ["### 이 지역판에 부족한 것", "", "| 섹션 | 상태 | 지금 상태 | 필요한 데이터 | 채우는 방법 |", "|---|---|---|---|---|"]
        for g in self.s["gaps"]:
            lines.append(f"| {g['section']} | {g['status']} | {g['detail']} | {g['need']} | {g['action']} |")
        return lines + ["", "전체 지역 비교와 외부 조치가 필요한 항목은 [[데이터 부족 점검]]에 있습니다.", ""]

    def glossary(self) -> List[str]:
        return ["## 낯선 말", ""] + [f"- **{k}** — {v}" for k, v in GLOSSARY.items()] + [""]

    def page(self) -> str:
        fm = ["---", "cssclasses: [artrend-home]", "type: frontpage_mockup", f"edition: {self.R}", f"asof: {self.s['asof']}",
              f"model_version: {self.s['model_version']}", "publishable: false", "---", ""]
        ed = getattr(self, "editorial", None)
        has = bool(ed and ed.available())
        from .daily_trend import trend_lines
        T = self.vb.asof
        trend = trend_lines(self.vb, self.R, T, self.vb.stories(self.R, T - dt.timedelta(days=6), T, T))
        glance = glance_lines(self.vb.editorial_notes if has else {}, self.R, heading="## 한눈에", trend=trend)
        body = (self.masthead() + glance + self.headline() + (ed.core() if has else []) + self.weekly() + self.topics() + self.focus() + self.news()
                + self.exhibitions() + self.galleries() + self.patterns() + (ed.rookie() if has else self.rookie()) + self.market()
                + self.upcoming() + self.glossary() + self.method())
        return "\n".join(fm + body)

    def audit_page(self) -> str:
        lines = ["---", "type: selection_audit", f"edition: {self.R}", f"asof: {self.s['asof']}", "---", "",
                 f"# 선발 기록 ({self.label})", "", f"[[ARTREND {self.label} 홈]]의 후보 판정 전체(D67 selection_audit). 통과 = 홈 노출 자격.", ""]
        by = {}
        for x in self.s["audit"]:
            by.setdefault(x["section"], []).append(x)
        for sec, rows in by.items():
            rows.sort(key=lambda x: (not x["passed"], len(x["reasons"]), x["candidate"]))
            lines += [f"## {sec} · {len(rows):,}건 (통과 {sum(r['passed'] for r in rows):,})", "", "| 후보 | 통과 | 사유 |", "|---|---|---|"]
            for r in rows[:300]:
                lines.append(f"| {str(r['candidate'])[:80].replace('|', '/')} | {'예' if r['passed'] else '아니오'} | {'; '.join(r['reasons']).replace('|', '/')} |")
            if len(rows) > 300:
                lines.append(f"\n{len(rows) - 300:,}건 생략.")
            lines.append("")
        return "\n".join(lines)


CSS = """/* ARTREND home mock-up — written by artrend_mag (cli vault). Enable in Settings → Appearance → CSS snippets. */
.artrend-home { --ar-red: #c8341f; --ar-ink: #151515; --ar-paper: #f7f4ee; }
.artrend-home .callout { border-radius: 2px; border: 1px solid #ddd6ca; background: var(--background-primary); box-shadow: none; }
.artrend-home .callout[data-callout="masthead"] { border: none; border-bottom: 3px solid var(--ar-ink); background: transparent; }
.artrend-home .callout[data-callout="masthead"] .callout-title { font-size: 2.4em; font-weight: 900; letter-spacing: .02em; color: var(--ar-ink); }
.artrend-home .callout[data-callout="masthead"] .callout-icon { display: none; }
.artrend-home .callout[data-callout="draft"] { border-left: 4px solid var(--ar-red); background: #fbeee9; font-size: .85em; }
.artrend-home .callout[data-callout="hero"] { border-top: 6px solid var(--ar-red); background: var(--ar-paper); padding: 1.2em 1.4em; }
.artrend-home .callout[data-callout="hero"] h3 { font-size: 1.9em; line-height: 1.25; margin: .2em 0 .5em; }
.artrend-home .callout[data-callout="hero"] .callout-title, .artrend-home .callout[data-callout="card"] .callout-title,
.artrend-home .callout[data-callout="lead"] .callout-title { color: var(--ar-red); text-transform: uppercase; font-size: .75em; letter-spacing: .08em; }
.artrend-home .callout[data-callout^="grid"] { border: none; background: transparent; padding: 0; }
.artrend-home .callout[data-callout^="grid"] > .callout-title { display: none; }
.artrend-home .callout[data-callout^="grid"] > .callout-content { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.artrend-home .callout[data-callout="grid2"] > .callout-content { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.artrend-home .callout[data-callout="grid3"] > .callout-content { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.artrend-home .callout[data-callout="stat"] h2 { font-size: 2.2em; color: var(--ar-red); margin: .1em 0; border: none; }
.artrend-home .callout[data-callout="artist"] .callout-title { font-weight: 800; }
.artrend-home .callout[data-callout="expo"] .callout-title, .artrend-home .callout[data-callout="gallery"] .callout-title,
.artrend-home .callout[data-callout="rookie"] .callout-title { font-size: .75em; letter-spacing: .06em; color: var(--ar-red); }
.artrend-home .callout[data-callout="empty"] { border-style: dashed; color: var(--text-muted); }
.artrend-home .callout[data-callout="queue"], .artrend-home .callout[data-callout="evidence"] { font-size: .85em; }
.artrend-home h2 { border-top: 2px solid var(--ar-ink); padding-top: .4em; letter-spacing: .04em; font-weight: 900; }
.artrend-home code { background: transparent; border: 1px solid var(--ar-ink); border-radius: 999px; padding: .1em .7em; margin: 0 .2em .4em 0; display: inline-block; }
"""


STATUS_MARK = {"충족": "● 충족", "부분": "◐ 부분", "불충족": "○ 불충족"}

# User-side actions found while checking the plan (dated observations, not assumptions).
EXTERNAL_ACTIONS = [
    ("검색·관심 지표(Popular)", "Naver DataLab 검색어트렌드 API", "2026-10-30 요청 결과 HTTP 401 'Scope Status Invalid' — 지금 키의 애플리케이션에 '데이터랩(검색어트렌드)' 사용 API가 추가되지 않음",
     "네이버 개발자센터 → 내 애플리케이션 → API 설정에서 '데이터랩(검색어트렌드)' 추가(키는 그대로)"),
    ("한국 국립 기관 전시(MMCA)", "data.go.kr 15058313", "공공데이터포털 인증키 필요(blocked_credentials)", "data.go.kr 활용신청 후 키를 `.env`에 추가"),
    ("해외 일반지 미술 기사", "Guardian Open Platform · NYT Developer API", "RSS는 약관상 자동수집 금지로 꺼 둠(blocked_permission)", "각 개발자 키 발급 시 공식 API로 수집 가능"),
    ("2026 가을 경매 결과", "Christie's·Sotheby's·Phillips·서울옥션·케이옥션", "robots·약관·권한 제한, 보유 경매 데이터는 2026-07까지", "경매사 데이터 제공 동의 또는 유료 데이터 계약"),
    ("일본 작가·소장 식별(APJ)", "Art Platform Japan", "약관이 DB 전체 복제를 금지, 대량 접근 문서 없음(not_attempted)", "기관에 이용 허가 문의 또는 작가별 수작업 확인"),
    ("MOMAT 전시", "momat.go.jp", "HTTP 403(blocked_access)", "기관 문의 또는 공개 보도자료 경유"),
    ("이미지", "기관 open access·press kit", "이미지 미수집 정책. image_rights에 권리 메타데이터만 있음", "카드별 권리 확인 후 승인본만 사용(Blueprint 19)"),
]


def readiness_rows(vb) -> list:
    """Data Readiness plan sheet 03 (결손과수집) against what the DB holds now."""
    c = vb.con
    one = lambda sql: c.execute(sql).fetchone()[0]
    ev = dict(c.execute("SELECT edition_region, count(*) FROM events WHERE start_precision='day' AND start_date>='2025-10-01' "
                        "GROUP BY 1").fetchall())
    n_crit = one("SELECT count(*) FROM articles WHERE article_type IN ('criticism','review','interview')")
    n_wd = one("SELECT count(*) FROM aliases WHERE namespace='wikidata'")
    n_ulan = one("SELECT count(*) FROM aliases WHERE namespace='ulan'")
    n_cc0 = one("SELECT count(*) FROM image_rights WHERE usage_status='public_domain_cc0'")
    n_rel, n_links, n_works = one("SELECT count(*) FROM relationships"), one("SELECT count(*) FROM entity_links WHERE reversed_at IS NULL"), one("SELECT count(*) FROM works")
    n_rep, n_met, n_img = one("SELECT count(*) FROM reports"), one("SELECT count(*) FROM report_metrics"), one("SELECT count(*) FROM image_rights")
    return [
        ("공식 전시/프로그램 사건", "P0", "4지역 확보: " + ", ".join(f"{EDITION_KO.get(k, k)} {ev.get(k, 0):,}" for k in FRONT_EDITIONS) + " (2025-10 이후 일 단위)",
         "부분", "MMCA(키)·MOMAT(403) 미확보, 28일 창 사건 20건 미만 지역은 관찰기관 추가 필요"),
        ("갤러리 관계·프로그램", "P0", f"소속 관계 {n_rel:,}건(첫 관측 10/27~28) · 갤러리 전시 포함",
         "부분", "주 1회 재관측으로 신규·이탈 비교. 첫 관측은 신규 아님"),
        ("독립 비평·담론", "P0", f"비평·리뷰·인터뷰 {n_crit:,}건 · 필자 텍스트 보유",
         "부분", "제목·메타데이터만(본문 없음). 독립성·논지 판정(D71)은 편집 검수 필요"),
        ("공통 엔터티 식별", "P0", f"Wikidata {n_wd:,} · ULAN {n_ulan:,} · 동일인 후보 연결 {n_links:,}",
         "부분", "APJ(일본) 미확보. 이름만으로 병합하지 않음"),
        ("작품/시리즈/주제", "P1", f"작품 {n_works:,}건(기관 open access)", "부분",
         "주제 태그는 제목 키워드 사전(frontpage-1). 전시 서문 기반 태그 없음"),
        ("검색/관심 지표", "P1", "없음", "불충족", "Naver DataLab 스코프 추가 필요(위 외부 조치). Google Trends는 공식 API 없음"),
        ("시장/보고서", "P2", f"경매 로트 591,834(~2026-07) · 보고서 {n_rep:,} · 지표 {n_met:,}",
         "부분", "가을 경매 결과 권한 필요"),
        ("이미지/권리", "P0", f"권리 메타데이터 {n_img:,}건(CC0 {n_cc0:,}) · 이미지 파일 0",
         "부분", "이미지 미수집 정책 유지. 게시용은 권리 승인본만"),
    ]


def gap_overview(vb, snaps: dict) -> str:
    sections = [g["section"] for g in next(iter(snaps.values()))["gaps"]]
    lines = ["---", "type: gap_report", f"asof: {vb.asof.isoformat()}", "---", "", "# 데이터 부족 점검", "",
             "Blueprint v1.2 로직(H00–H09, FP·HL 규칙)을 실제 DB에 돌려 본 결과입니다. '불충족'은 로직이 요구하는 입력이 없거나 문턱에 못 미친다는 뜻이며 "
             "'미술계에 그런 일이 없다'는 뜻이 아닙니다.", "",
             "## 지역판별 섹션 상태", "", "| 섹션 | " + " | ".join(f"[[ARTREND {EDITION_KO[r]} 홈|{EDITION_KO[r]}]]" for r in snaps) + " |",
             "|---|" + "---|" * len(snaps)]
    for i, sec in enumerate(sections):
        lines.append(f"| {sec} | " + " | ".join(f"{STATUS_MARK[s['gaps'][i]['status']]}<br><small>{s['gaps'][i]['detail']}</small>" for s in snaps.values()) + " |")
    lines += ["", "## 크롤링 플랜(Data Readiness v1) 대조", "", "`ARTREND_Data_Readiness_and_Crawl_Plan_v1.xlsx` 03_결손과수집 기준.", "",
              "| 필요 데이터 | 우선 | 지금 DB | 상태 | 남은 일 |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {STATUS_MARK[d]} | {e} |" for a, b, c, d, e in readiness_rows(vb)]
    lines += ["", "## 사용자 조치가 필요한 것", "", "| 데이터 | 경로 | 확인 결과 | 하면 되는 일 |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in EXTERNAL_ACTIONS]
    lines += ["", "## 시간이 지나야 채워지는 것", "",
              "- 2026-10-29 추가한 언론사 RSS(일본·해외 8곳)와 국내 RSS 9곳은 35일 연속 수집 뒤(2026-12-03 이후) 보도 비교 패널에 들어갑니다(HL03).",
              "- 갤러리 소속 명단은 다음 비교 관측(주 1회 권장)부터 신규·이탈을 판정합니다.",
              "- 사건 28일 창 비교는 140일 이력이 필요합니다. 새 관찰기관은 그만큼 쌓인 뒤 비교에 들어갑니다.",
              "", "## 로직상 일부러 비워 두는 것", "",
              "- 작가 숫자 순위(L07): 전 축 관측·비교군 30명 조건 전에는 근거형 소개만.",
              "- 대표 헤드라인의 경매 카드, 위스키·시계 등 비미술 경매(HL11·HL13).",
              "- 근거가 없는 섹션은 빈 상태로 둡니다(QA05).", ""]
    return "\n".join(lines)


def logic_note(asof) -> str:
    rows = [
        ("H00 헤더", "지역판 4개 탭, 집계 시각", "지역판마다 별도 스냅샷(FRONT_EDITIONS). 기타(OTHER)는 강제 배정하지 않음"),
        ("H01 TODAY'S INSIGHT", "HL02 시간창 · HL03 패널 · HL04 묶기 · HL07 보도 집중 · HL08 활동 확산 · HL11 시즌/집중 · HL12–13 편성",
         "보도: 7일 vs 직전 4주, 원전≥3·매체그룹≥2·주별 패널≥20·coverage≥80%·+2%p·1.5배·24h 새 원전·한 그룹≤50%. "
         "활동: 7일 또는 28일 창, 사건≥3·주체≥2 + 같은 비교 조건. 미달이지만 사건·주체 2곳 이상이면 '새로운 징후', 24h 최고 점수 소식은 '주요 소식'. "
         "활동 확산 → 보도 집중 → 새로운 징후 → 주요 소식 순, 최대 3장, 한 주제 1장, 경매 카드 1장 이하·대표 제외"),
        ("숫자로 본 한 주", "한장요약 W42 1쪽 · HD10/HD11", "패널 소식 수·최다 주제·경매/시장 소식을 평소(직전 4주 평균)와 비교. coverage·시즌 주의 문구 자동"),
        ("H02 ARTISTS IN FOCUS", "FP04", "90일 사건≥3·독립 주체≥2·관측된 축(I/G/E) 2개 이상 증가·30일 새 계기. E축은 보도 패널 coverage≥80%일 때만 관측. 증가 축 수→새 계기 날짜 순, 최대 6"),
        ("H03 TREND NEWS", "FP05 · HL04", "14일 소식 묶음. 인사이트 직접 근거 → 관찰 대상 관련 → 사건 연결 → 점수 순. 비평 2곳 이상이면 '비평의 관점'"),
        ("H04 EXHIBITIONS", "FP06", "진행 중 또는 60일 내 개막 + 직접 연결(14일 보도·인사이트 주제·주목 작가). 진행 중 → 독립 기획 → 연결 수 → 개막 근접"),
        ("H05 GALLERY MOVES", "FP07", "30일 갤러리 개막. 참여 작가의 12개월 기관 전시가 있으면 우선. 같은 그룹 1장. 첫 관측 소속 명단은 새 관계로 안 셈"),
        ("H06 EMERGING PATTERNS", "FP08", "최근/직전 90일 전시 주제 점유율 %p. 구간별 사건 20·기관 3 미만이면 숨김. 지역 간 흐름 카드 연결"),
        ("H07 ROOKIE RADAR", "FP09 · L11", "12개월 내 선정·지원 주체 2곳·유형 2개. 첫 개인전 연도 미확인은 표시"),
        ("H08 MARKET CONTEXT", "FP10 · L13/L14", "지역 경매 최근 6개월 vs 1년 전 같은 기간(낙찰률·수수료 포함 중앙값), 지역 보고서. 트렌드 점수에 합산 안 함"),
        ("H09 방법", "L16 · D67", "패널·coverage·창·판정 수, 지역별 부족 데이터, 선발 기록(통과/탈락 사유)"),
    ]
    lines = ["---", "type: logic", f"asof: {asof.isoformat()}", "---", "", "# 프런트페이지 로직", "",
             "`ARTREND_Logic_Data_Agent_Blueprint_v1_2.xlsx`(16 프런트페이지 · 17 홈선발규칙 · 24–27 헤드라인)을 코드로 옮긴 범위입니다. "
             "구현: `artrend_mag/frontpage.py`(계산) · `frontpage_render.py`(화면) · `news_digest.py`(기사 묶기).", "",
             "| 섹션 | 블루프린트 규칙 | 구현한 판정 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    from .editorial import CRITERIA, WEIGHT
    lines += ["", "## 주요 소식 판정 기준", "",
              "'여러 곳이 보도했다'만으로 고르지 않습니다. `cli brief`가 이번 주 소식 묶음마다 아래 기준을 제목·요약·본문 핵심문장에서 찾아 점수를 매기고, "
              "상위 소식의 본문을 robots가 허용하는 범위에서 읽습니다(핵심 문장 300자 이하만 보관). 그다음 편집 메모가 사실 요약·왜·그래서?를 씁니다.", "",
              "| 기준 | 점수 | 뜻 |", "|---|---:|---|"]
    meaning = {"public": "국가·공공 주체의 결정", "structure": "개관·폐관·인사·제도·예산처럼 구조가 바뀜", "scale": "금액·수량이 명시됨",
               "first": "최초·기록", "award": "공식 선정·수상"}
    lines += [f"| {label} | {WEIGHT[cid]} | {meaning[cid]} |" for cid, label, _ in CRITERIA]
    lines += ["| 후속 일정 | 1 | 120일 안의 다음 일정이 명시됨 |", "| ARTREND 관찰 대상 | 1 | 관찰 기관·작가가 제목에 있음 |",
              "| 독립 보도 확산 | 1 | 3개 매체 이상(소유그룹 미확인 상한값) |", "",
              "## 루키 판단 순서", "",
              "1. 최근 30일 수상·선정 기사를 모아 같은 상의 발표·시상·기념전을 1건으로 묶습니다(EV09).",
              "2. 상을 먼저 평가합니다 — 주최(국공립·국가·국제 2, 민간 재단·언론 1, 상업 공모전·방송사 0), 10년 이상 운영 +1, 전문가 심사 공개 +1, 국제 심사 +1, 후속 전시 +1, 매입 +1, 상금 1천만원 이상 +1. 6점 이상 높음·3점 이상 보통.",
              "3. 트랙을 가릅니다 — 신진 대상 상 / 경력 제한 없는 상 / 기성 작가 상 / 제외(판매형 미술제·방송사 시상 등).",
              "4. 수상자마다 R01 공식 선정, R02 첫 개인전 10년 이내('N번째 개인전' 보도도 씀), R03 이번 상 외 12개월 내 다른 미술 사건·유형, R05 후속 지원을 확인합니다. 이력은 네이버 뉴스 제목 검색으로 보고 미술과 무관한 동명이인 기사는 뺍니다.",
              "5. 모두 통과하면 '편집 검토 후보', 일부만이면 '관찰 후보', 경력 10년 이상이면 '재발견·중견 확인 필요'. 나이·판매·경매 실적은 쓰지 않습니다.", ""]
    lines += ["", "## 블루프린트와 다른 점", "",
              "- **문장 작성(AG18)**: 언어모델 대신 계산값을 넣은 고정 문형. 사실·그래서?·한계 구조는 HD02를 따릅니다.",
              "- **원전·독립성(HL04/HL09)**: 본문이 없어 제목 유사도 묶음을 원전으로 근사합니다(T 수준). 원전·매체그룹 수는 상한값입니다.",
              "- **coverage(HL03)**: 출처별 일일 성공 기록이 없어 '기준 4주에 기사가 있는 출처가 각 주에 관측된 비율'로 근사합니다. 소급 수집한 이력(Naver API·아카이브)도 발행 시점 기준으로 씁니다.",
              "- **주제 묶기(HL06)**: 제목 키워드 사전(19개 주제)과 관찰 대상 이름. 논지 단위 주제 가설은 편집자 몫입니다.",
              "- **편집 승인(FP01)**: 승인 단계가 없어 모든 카드가 `publishable=0` 초안입니다.",
              "- **스냅샷(D64/OP03)**: `outputs/frontpage/` JSON이 웹사이트 응답 형태(region, as_of, cards[...], coverage_note)를 따릅니다.", ""]
    return "\n".join(lines)


def snapshot_json(vb, snap: dict) -> dict:
    """OP03-shaped payload (GET headline?region=…) plus the other home sections, ids only for linking."""
    r = Renderer(vb, snap)
    cards = []
    for c in snap["headline"]:
        md = r.headline_card(c, "card")
        title = next((x[6:] for x in md if x.startswith("> ### ")), c["topic"])
        fact = next((x[8:] for x in md if x.startswith("> **사실** ")), "")
        cards.append(dict(type=c["kind"], basis=c["basis"], title=title, fact=fact, meaning=MEANING[c["kind"]], topic=c["topic"]))
    p = snap["press"]
    return dict(region=snap["region"], as_of=snap["T"], model_version=snap["model_version"], window_label="7일 vs 직전 4주 · 사건 28일",
                cards=cards, stale=False, publishable=False,
                coverage_note=f"보도 패널 {len(p['panel'])}곳 coverage {pct(p['coverage'])}",
                sections=dict(
                    artists=[x["entity_id"] for x in snap["focus"]["selected"]],
                    news=[x["story"]["lead"]["article_id"] for x in snap["news"]["cards"]],
                    exhibitions=[x["event"]["event_id"] for x in snap["exhibitions"]["cards"]],
                    galleries=[x["event"]["event_id"] for x in snap["galleries"]["cards"]],
                    patterns=[x["topic"] for x in snap["patterns"]["topics"]],
                    rookie=[x["entity_id"] for x in snap["rookie"]["ready"]]),
                gaps=[{k: g[k] for k in ("section", "status", "detail")} for g in snap["gaps"]])


# ---------------------------------------------------------------- editorial layer (cli brief + editorial/notes_<D>.json)
OK_MARK = {True: "✅", False: "❌", None: "❔"}
TRACK_LABEL = {"rookie": "신진 대상 상", "open": "경력 제한 없는 상·선정", "established": "기성 작가 상",
               "shortlist": "후보 명단(최종 아님)", "excluded": "제외"}
STATUS_ORDER = ["편집 검토 후보", "편집 검토 후보(경력 확인 필요)", "관찰 후보", "관찰 후보(동명이인 확인 필요)", "재발견·중견 확인 필요",
                "후보 단계(최종 발표 전)", "기성·재발견(루키 트랙 아님)", "제외(공식 선정으로 보기 어려움)"]


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?。])(\s|$)", text or "")
    return (m.group(1) if m else (text or ""))


def glance_lines(notes: dict, region: str, anchor_page: str = "", heading: str = "## 한눈에", trend: Optional[List[str]] = None) -> List[str]:
    """W42 '한눈에': observed cross-story insights first, then each main story as summary → so-what in one line."""
    major = sorted(((k, v) for k, v in (notes.get("major") or {}).items() if v.get("edition") == region and not v.get("exclude")),
                   key=lambda kv: kv[1].get("rank", 99))
    insights = (notes.get("glance") or {}).get(region, [])
    if not major and not insights and not trend:
        return []
    out = [heading, ""] + list(trend or [])
    body = []
    if insights:
        body += ["**편집자가 본 이번 주 흐름**"] + [f"{i}. {t}" for i, t in enumerate(insights, 1)] + [""]
    if major:
        body.append("**주요 소식 — 무슨 일이고, 그래서?**")
        for i, (_, v) in enumerate(major, 1):
            target = f"[[{anchor_page}#{i}. {v['headline']}|{v['headline']}]]" if anchor_page else f"**{v['headline']}**"
            body.append(f"{i}. {target} — {v.get('brief') or first_sentence(v['summary'])}")
            body.append(f"    - → {first_sentence(v['so_what'])}")
    if not major and not insights:
        return out
    body += ["", f"<small>판단: {notes.get('editor', '편집 메모')} · 기준은 [[프런트페이지 로직#주요 소식 판정 기준|주요 소식 판정 기준]]</small>"]
    return out + callout("glance", "편집자 브리핑 — 이번 주 흐름과 주요 소식", body) + [""]


class EditorialRenderer:
    """Sections that judge rather than list. Machine facts come from packets; sentences from the editor's notes."""

    def __init__(self, vb, region: str, packets: dict, notes: dict, watchlist: dict):
        self.vb, self.R = vb, region
        self.ed = (packets.get("editions") or {}).get(region, {})
        self.packets, self.notes, self.watch = packets, notes, watchlist
        self.major = {p["key"]: p for e in (packets.get("editions") or {}).values() for p in e["major"] + e["rookie"]}

    def available(self) -> bool:
        return bool(self.ed)

    def _related(self, names) -> str:
        out = []
        for n in names or []:
            eid = self.vb.find_entity(n)
            out.append(self.vb.entity_link(eid) if eid else f"`{n}`")
        return " · ".join(out)

    def core(self) -> List[str]:
        """한장요약 W42 '핵심 정리': 사실 요약 → 왜 주요 소식인가(기준·근거) → 그래서? → 관련."""
        notes = {k: v for k, v in (self.notes.get("major") or {}).items() if v.get("edition") == self.R and not v.get("exclude")}
        out = ["## 핵심 정리 — 이번 주 주요 소식", ""]
        if not notes:
            cand = self.ed.get("major", [])
            out += callout("empty", "편집 메모 없음", [f"자동 후보 {len(cand)}건은 있지만 요약·판단(editorial/notes)이 아직 없습니다. 후보 목록은 아래 TREND NEWS를 보세요."]) + [""]
            return out
        for i, (key, n) in enumerate(sorted(notes.items(), key=lambda kv: kv[1].get("rank", 99)), 1):
            p = self.major.get(key, {})
            crit = [c for c in p.get("criteria", []) if c["id"] != "next"]
            body = [f"### {i}. {n['headline']}", "", n["summary"], "", "**왜 주요 소식인가**"]
            body += [f"- {w}" for w in n.get("why", [])]
            if crit:
                body.append("- 자동 판정 기준: " + " · ".join(f"`{c['label']}`" for c in crit)
                            + f" (중요도 {p.get('importance', 0)}점 — [[프런트페이지 로직#주요 소식 판정 기준|기준]])")
            body += ["", f"**→ 그래서?** {n['so_what']}", ""]
            members = p.get("members") or n.get("sources") or []
            src = [f"[{m['outlet']}]({m['url']}) {m['date']}" for m in sorted(members, key=lambda m: m["date"], reverse=True)[:4]]
            read = [b for b in p.get("bodies", []) if b.get("key_sentences")]
            body.append(f"<small>출처 {len(p.get('outlets') or members)}곳: " + " · ".join(src)
                        + (f" · 본문 확인 {len(read)}건(핵심 문장만 보관)" if read else " · 본문 미확인(요약 기준)") + "</small>")
            if n.get("related"):
                body.append(f"<small>관련: {self._related(n['related'])}</small>")
            date = p.get("date") or max((m["date"] for m in members), default="")
            out += callout("core", f"{p.get('topic') or '편집 추가'} · {date}", body) + [""]
        dropped = [v for v in (self.notes.get("major") or {}).values() if v.get("edition") == self.R and v.get("exclude")]
        if dropped:
            out += [f"<small>자동 후보 중 {len(dropped)}건은 편집 판단으로 뺐습니다(비평·인터뷰·작가 소개 등 사건이 아닌 글). 사유는 [[선발 기록 ({EDITION_KO[self.R]})]].</small>", ""]
        return out

    def rookie(self) -> List[str]:
        awards = {k: v for k, v in (self.notes.get("awards") or {}).items() if v.get("edition_region") == self.R}
        cands = {n: c for n, c in (self.packets.get("candidates") or {}).items() if c.get("edition") == self.R}
        out = ["## ROOKIE RADAR", ""]
        if not awards:
            stories = self.ed.get("rookie", [])
            out += callout("empty", "이번 달 편집 판단한 수상·선정 없음 — 자동으로 찾은 수상·선정 기사", [
                f"- [{p['title']}]({p['url']}) · {p['date']}" for p in stories[:8]] or ["최근 30일 수상·선정 기사가 수집되지 않았습니다(수집 공백 — '없다'는 뜻이 아님)."]) + [""]
            return out
        out += ["<small>최근 30일 수상·선정 기사를 읽고 ① 상이 무엇을 보증하는지(주최·심사·후속 지원) ② 수상자가 루키 조건(Blueprint 10 R01~R05)을 채우는지 따로 판단했습니다. "
                "루키 확정이 아니라 '계속 지켜볼 이유'의 정리입니다.</small>", ""]
        track_rank = {"rookie": 0, "open": 1, "established": 2, "excluded": 3}
        known = lambda c: sum(x["ok"] is True for x in c["checks"])
        ranked = sorted(cands.values(), key=lambda c: (STATUS_ORDER.index(c["status"]) if c["status"] in STATUS_ORDER else 9,
                                                      track_rank.get(c.get("track"), 4), -known(c), -c["weight"]["points"], c["name"]))
        watch = [c for c in ranked if c["status"].startswith(("편집 검토", "관찰 후보"))]
        # The radar is never empty: when few winners pass, the nearest non-excluded winners are shown as 'reference' cards.
        near = [c for c in ranked if c not in watch and c.get("track") != "excluded"]
        shown = watch[:6] + near[:max(0, 4 - len(watch[:6]))]
        cards = []
        for c in shown:
            aw = awards.get(c["story"], {})
            checks = " ".join(f"{OK_MARK[x['ok']]}{x['rule'][:3]}" for x in c["checks"])
            body = [f"**{c['award']}** · {c.get('genre') or '장르 미상'}", f"상의 무게: **{c['weight']['level']}** ({c['weight']['points']}점) · {TRACK_LABEL.get(c.get('track'), '')}",
                    "", f"왜 받았나: {c.get('why') or '보도에 선정 사유 없음'}", "", f"루키 조건 {checks}",
                    f"<small>{c['checks'][1]['detail']}</small>", f"<small>{c['checks'][2]['detail']}</small>"]
            if c.get("homonym_note"):
                body.append(f"<small>{c['homonym_note']}</small>")
            label = c["status"] if c in watch else f"참고 · {c['status']}"
            cards.append(callout("rookie", f"{label} · {c['name']}", body))
        if shown and not watch:
            out += ["<small>이번 달에는 루키 조건을 채운 수상자가 없어서, 판단한 수상자 중 가장 가까운 사람을 '참고'로 보여 줍니다.</small>", ""]
        no_names = [aw for aw in awards.values() if not aw.get("winners")]
        if cards:
            out += grid(cards, "grid2") + [""]
        if no_names:
            out += ["<small>수상자 이름을 아직 못 읽은 상: " + "; ".join(f"[{aw['award']}]({aw['url']})" if aw.get("url") else aw["award"] for aw in no_names)
                    + " — 원문 확인 뒤 명단에 넣습니다.</small>", ""]
        # award-level judgement table
        rows = ["| 상·선정 | 주최 | 무게 | 근거 | 대상·트랙 | 수상자 | 판단 |", "|---|---|---|---|---|---|---|"]
        for key, aw in sorted(awards.items(), key=lambda kv: -next((c["weight"]["points"] for c in cands.values() if c["story"] == kv[0]), 0)):
            from .editorial import award_weight
            w = award_weight(aw, dt.date.fromisoformat(self.packets["asof"]))
            p = self.major.get(key, {})
            names = ", ".join(x["name"] for x in aw.get("winners", [])) or "명단 미확인"
            url = p.get("url") or aw.get("url")
            link = f"[기사]({url})" if url else ""
            rows.append(f"| {aw['award']} {link} | {aw.get('organizer', '')} | {w['level']} {w['points']} | {'; '.join(r for r in w['reasons'])} | "
                        f"{TRACK_LABEL.get(aw.get('track'), '')} | {names} | {aw.get('track_reason', '')} |")
        out += callout("queue", f"이번 달 판단한 수상·선정 {len(awards)}건 — 상의 무게와 트랙", rows, fold="-") + [""]
        rest = [c for c in ranked if c not in watch[:6]]
        if rest:
            t = ["| 이름 | 상 | 판단 | 루키 조건 | 메모 |", "|---|---|---|---|---|"]
            for c in rest:
                t.append(f"| {c['name']} | {c['award']} | {c['status']} | {' '.join(OK_MARK[x['ok']] + x['rule'][:3] for x in c['checks'])} | "
                         f"{c['checks'][1]['detail'][:60]} |")
            out += callout("queue", f"나머지 수상자 {len(rest)}명 (관찰·기성·제외)", t, fold="-") + [""]
        total = len(self.watch)
        out += [f"<small>누적 관찰 명단 {total}명은 [[루키 관찰 명단]]. 판단 근거: Blueprint 10 루키발굴(R01 공식 선정 · R02 첫 개인전 10년 이내 · R03 12개월 내 다른 주체·다른 유형 · R05 후속 지원), "
                "22 EV09(최종 수상만 인정, 같은 상의 발표·시상·기념전은 1건). 이력은 네이버 뉴스 제목 검색 기준이라 '보도된 이력'이며 동명이인 기사는 걸러냈습니다.</small>", ""]
        return out


def watchlist_page(vb, watch: dict, asof) -> str:
    lines = ["---", "type: rookie_watchlist", f"asof: {asof.isoformat()}", "publishable: false", "---", "", "# 루키 관찰 명단", "",
             "`cli brief` → 편집 메모(`editorial/notes_<날짜>.json`) → `cli brief --check-names`로 쌓이는 누적 명단입니다. "
             "원본은 `editorial/rookie_watchlist.json` — `editor_status`·`note`를 직접 적으면 다음 빌드에 보입니다.", "",
             "| 이름 | 에디션 | 처음 본 날 | 상·선정 | 상의 무게 | 판단 | 조건 | 왜 | 편집 메모 |", "|---|---|---|---|---|---|---|---|---|"]
    order = {s: i for i, s in enumerate(STATUS_ORDER)}
    for n, r in sorted(watch.items(), key=lambda kv: (order.get(kv[1].get("machine_status"), 9), kv[0])):
        checks = " ".join(OK_MARK[x["ok"]] + x["rule"][:3] for x in r.get("checks", []))
        eid = vb.find_entity(n)
        name = vb.entity_link(eid, in_table=True) if eid else n
        lines.append(f"| {name} | {EDITION_KO.get(r.get('edition'), r.get('edition', ''))} | {r.get('first_seen')} | {' / '.join(r.get('awards', []))} | "
                     f"{r.get('award_level', '')} | {r.get('editor_status') or r.get('machine_status')} | {checks} | {(r.get('why') or '')[:80]} | {r.get('note', '')} |")
    return "\n".join(lines)
