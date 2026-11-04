"""Per-edition front-page snapshot following Blueprint v1.2 sheets 16/17 (H00–H09, FP01–FP10) and 24–27 (HL01–HL16).

Numbers are computed here by code; card sentences are fixed templates filled with those numbers (the Blueprint's AG18
writer is not run — no language model writes claims). Every card keeps its metrics, thresholds, failed conditions and
evidence links, so the page shows *why* something is on it and *what is missing* when a section stays empty.

Deviations forced by the data, stated on the page:
- Articles are title-level (HL09 level T): a story cluster stands in for an origin family and independence is not
  confirmed, so press counts are upper bounds.
- Comparison panel (HL03): scheduled sources with articles in the 4 baseline weeks; coverage = observed source-weeks /
  expected source-weeks (an empty week counts as unobserved because per-day success logs do not exist for backfills).
  One-off legacy imports are never in the panel. History collected retrospectively (Naver API, archives) is labelled so.
- Publisher group = the article's owner group when known, else its publisher/domain (an upper bound of groups).
- Nothing here is approved or publishable; the snapshot mirrors the OP03 contract shape for the future website.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, Iterable, List, Optional

from . import news_digest

KST = dt.timezone(dt.timedelta(hours=9))
FRONT_EDITIONS = ("KR", "JP", "AMERICAS", "EUROPE")
MODEL_VERSION = "frontpage-1"

# Thresholds: Blueprint initial values (HL07/HL08/FP04/FP06/FP08). All are unvalidated editorial assumptions (HL16).
MIN_ORIGINS, MIN_GROUPS, MIN_PANEL, MIN_COVERAGE = 3, 2, 20, 0.80
MIN_DELTA_PP, MIN_RATIO, MAX_TOP_GROUP_SHARE = 0.02, 1.5, 0.5
FOCUS_EVENTS, FOCUS_GROUPS, FOCUS_AXES = 3, 2, 2
PATTERN_EVENTS, PATTERN_ORGS = 20, 3

TOPICS = {
    "섬유·텍스타일": r"섬유|텍스타일|직조|태피스트리|textile|tapestr|weav|fiber|fibre|テキスタイル|織物",
    # Korean headlines use '사진' / '영상' for the accompanying photo/video ('[사진]', '사진=…'), so only art compounds count.
    "사진": r"사진전|사진가|사진작가|사진 작가|사진 작품|사진미술|사진展|photograph|写真展|写真家",
    "미디어·영상": r"미디어\s?아트|뉴미디어|영상 작품|영상 설치|비디오\s?아트|media art|video art|moving image|映像作品|メディアアート",
    "회화": r"회화|페인팅|painting|painter|peinture|peintre|絵画|日本画|洋画",
    "조각·설치": r"조각|설치미술|설치 작품|sculpt|installation|彫刻|インスタレーション",
    "공예·도자": r"공예|도자|도예|ceramic|craft|pottery|工芸|陶芸",
    "퍼포먼스": r"퍼포먼스|performance|パフォーマンス",
    "AI·디지털": r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|디지털|NFT|digital|technolog|人工知能|デジタル",
    "생태·기후": r"생태|기후|환경|ecolog|climate|environment|生態|気候|環境",
    "여성·젠더": r"여성|페미니|젠더|women|feminis|gender|女性|ジェンダー",
    "아카이브·근대": r"아카이브|근대|archive|modernis|アーカイブ|近代",
    "고미술·문화유산": r"고미술|문화유산|국보|보물|고서화|민화|antiquit|heritage|old master|古美術|文化財|国宝",
    "비엔날레·트리엔날레": r"비엔날레|트리엔날레|biennale|biennial|triennial|ビエンナーレ|トリエンナーレ|芸術祭",
    "아트페어": r"아트페어|키아프|kiaf|프리즈|frieze|art basel|아트바젤|art fair|foire|アートフェア",
    "경매·시장": r"경매|옥션|낙찰|auction|sotheby|christie|phillips|enchère|オークション|落札",
    "미술관 정책·제도": r"평가인증|문체부|정책|예산|제도|감정서|표준 서식|policy|funding|budget|文化庁|予算",
    "수상·선정": news_digest.AWARD.pattern,
    "신진·청년": r"신진|청년 작가|젊은 작가|emerging|young artist|新進|若手",
    "개관·이전": r"개관|재개관|분관|건립|reopen|new museum|new wing|開館|新館",
}
TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}
EVENT_TYPE_TOPIC = {"biennial_edition": "비엔날레·트리엔날레", "fair_edition": "아트페어", "award": "수상·선정",
                    "open_call_selection": "수상·선정", "residency": "레지던시", "acquisition": "소장품 수집"}
LUXURY = re.compile(r"위스키|와인|시계|핸드백|보석|주얼리|스니커|whisk|wine|watch|handbag|jewel|sneaker|ウイスキー|時計", re.I)
GALLERY_TYPES = {"gallery", "fair"}
SHOWING = {"exhibition", "biennial_edition", "fair_edition", "program"}
ROOKIE = {"award", "open_call_selection", "residency"}
AUCTION_REGION = (("KR", r"seoul|korea|\bkr\b|서울|부산|홍콩 \(서울\)"), ("JP", r"tokyo|japan|\bjp\b|東京"),
                  ("AMERICAS", r"new york|los angeles|chicago|toronto|\bus\b|usa|united states|canada|mexico|são paulo|brazil"),
                  ("EUROPE", r"london|paris|geneva|zurich|cologne|milan|vienna|amsterdam|monaco|\bmc\b|\bgb\b|france|germany|italy|"
                             r"switzerland|stockholm|munich|brussels|madrid|edinburgh|scotland|spain|austria"))
REGION_GEO = {"KR": ("Korea", "South Korea"), "JP": ("Japan",), "AMERICAS": ("United States", "Canada", "Americas"),
              "EUROPE": ("Europe", "United Kingdom", "France", "Germany")}


def ts(value: Optional[str]) -> Optional[dt.datetime]:
    """Article time; a date without a clock is placed at 12:00 KST of that day."""
    if not value:
        return None
    v = value.strip()
    try:
        if len(v) == 10:
            return dt.datetime.fromisoformat(v).replace(hour=12, tzinfo=KST)
        t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=KST)
    except ValueError:
        return None


def day(value: Optional[str]) -> Optional[dt.date]:
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def topics_of(text: str) -> List[str]:
    return [k for k, rx in TOPIC_RE.items() if rx.search(text or "")]


def group_of(a: dict) -> str:
    return (a.get("owner_group") or a.get("publisher") or a.get("source_id") or "?").strip().lower()


def pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


class FrontPage:
    """One edition's snapshot at T = asof 07:00 KST (HL02). Windows are half-open [start, T)."""

    def __init__(self, vb, edition: str, asof: dt.date):
        self.vb, self.R, self.asof = vb, edition, asof
        self.T = dt.datetime.combine(asof, dt.time(7, 0), KST)
        self.d = asof - dt.timedelta(days=1)  # last complete event day
        self.matcher = vb.name_matcher(edition)
        self.audit: List[dict] = []  # D67 selection_audit rows
        self.gaps: List[dict] = []

    # ------------------------------------------------------------------ inputs
    def week(self, k: int):
        return self.T - dt.timedelta(days=7 * (k + 1)), self.T - dt.timedelta(days=7 * k)

    def load_articles(self, days: int = 35) -> List[dict]:
        start = (self.T - dt.timedelta(days=days)).date()
        rows = []
        for a in self.vb.reading(self.R, start, self.T.date()):
            a = dict(a, _ts=ts(a["published_at"]), _via="local")
            rows.append(a)
        # HL05: a GLOBAL outlet's article belongs to this edition when it names an entity observed here.
        home = self.vb.home_editions()
        for a in self.vb.reading("GLOBAL", start, self.T.date()):
            # only entities whose programme is mostly in this edition (a Tokyo branch does not make Pace a JP story)
            hits = [h for h in self.matcher.find(a["title"]) if home.get(h[1]) == self.R]
            if hits:
                rows.append(dict(a, _ts=ts(a["published_at"]), _via="global", _hits=hits))
        return [a for a in rows if a["_ts"] and self.T - dt.timedelta(days=days) <= a["_ts"] < self.T]

    def scheduled(self, source_id: str) -> bool:
        return (self.vb.sources.get(source_id) or {}).get("source_kind") != "legacy_local"

    def events(self) -> List[dict]:
        out = []
        for ev in self.vb._events_for(self.R):
            when = day(ev["start_date"]) if ev["start_precision"] == "day" else None
            if ev["event_type"] in ROOKIE and not when:
                when = day(ev["announced_date"])
            if when:
                out.append(dict(ev, _day=when))
        return out

    def org_group(self, ev: dict) -> Optional[str]:
        org = ev["organizer_entity_id"] or (self.vb.venues.get(ev["venue_id"]) or {}).get("owner_entity_id")
        if not org:
            return ev["source_id"]
        ent = self.vb.entities.get(org) or {}
        return ent.get("parent_entity_id") or org

    def org_kind(self, ev: dict) -> str:
        org = ev["organizer_entity_id"] or (self.vb.venues.get(ev["venue_id"]) or {}).get("owner_entity_id")
        etype = (self.vb.entities.get(org) or {}).get("entity_type")
        return "G" if etype in GALLERY_TYPES or ev["event_type"] == "fair_edition" else "I"

    def event_topics(self, ev: dict) -> List[str]:
        keys = topics_of(ev["title"] or "")
        if ev["event_type"] in EVENT_TYPE_TOPIC:
            keys.append(EVENT_TYPE_TOPIC[ev["event_type"]])
        return sorted(set(keys))

    # ------------------------------------------------------------------ press (HL03/04/07)
    def press(self) -> dict:
        arts = self.articles
        windows = [self.week(k) for k in range(5)]
        in_win = [[a for a in arts if s <= a["_ts"] < e] for s, e in windows]
        base_sources = {a["source_id"] for w in in_win[1:] for a in w if self.scheduled(a["source_id"])}
        observed = {sid: sum(any(a["source_id"] == sid for a in w) for w in in_win) for sid in base_sources}
        coverage = (sum(observed.values()) / (5 * len(observed))) if observed else None
        stories = []
        for k, w in enumerate(in_win):
            panel_rows = [a for a in w if a["source_id"] in base_sources]
            stories.append(news_digest.cluster(panel_rows))
        n = [len(s) for s in stories]
        tagged = collections.defaultdict(lambda: [[] for _ in range(5)])
        for k, window in enumerate(stories):
            for members in window:
                text = " ".join(m["title"] or "" for m in members[:4])
                keys = set(topics_of(text))
                for m in members[:4]:
                    keys |= {f"entity:{eid}" for _, eid in self.matcher.find(m["title"])}
                if LUXURY.search(text):
                    keys.discard("경매·시장")
                for key in keys:
                    tagged[key][k].append(members)
        rows = []
        for key, per in tagged.items():
            a_cur = len(per[0])
            if not a_cur:
                continue
            members = [m for st in per[0] for m in st]
            groups = collections.Counter(group_of(m) for m in members)
            shares = [len(per[k]) / n[k] if n[k] else None for k in range(5)]
            base = [s for s in shares[1:] if s is not None]
            base_mean = sum(base) / len(base) if len(base) == 4 else None
            new24 = any(m["_ts"] >= self.T - dt.timedelta(hours=24) for m in members)
            fails = []
            if a_cur < MIN_ORIGINS: fails.append(f"독립 원전 {a_cur}<{MIN_ORIGINS}")
            if len(groups) < MIN_GROUPS: fails.append(f"매체그룹 {len(groups)}<{MIN_GROUPS}")
            if min(n) < MIN_PANEL: fails.append(f"주별 패널 소식 최소 {min(n)}<{MIN_PANEL}")
            if coverage is None or coverage < MIN_COVERAGE: fails.append(f"coverage {pct(coverage)}<80%")
            if not new24: fails.append("최근 24시간 새 원전 없음")
            top_share = max(groups.values()) / len(members)
            if top_share > MAX_TOP_GROUP_SHARE: fails.append(f"한 매체그룹 비중 {top_share:.0%}>50%(HL11)")
            delta = ratio = None
            if base_mean is not None and shares[0] is not None:
                delta = shares[0] - base_mean
                ratio = shares[0] / base_mean if base_mean else None
                if base_mean == 0: fails.append("기준 비중 0(신규 관찰)")
                else:
                    if delta < MIN_DELTA_PP: fails.append(f"비중 변화 {delta * 100:+.1f}%p<+2%p")
                    if ratio < MIN_RATIO: fails.append(f"비중 배수 {ratio:.2f}<1.5")
            rows.append(dict(key=key, label=self.topic_label(key), a=a_cur, groups=len(groups), top_group_share=top_share,
                             share=shares[0], base_share=base_mean, delta=delta, ratio=ratio, new24=new24, fails=fails,
                             stories=sorted(per[0], key=lambda st: -len(st)), base_counts=[len(per[k]) for k in range(1, 5)]))
        rows.sort(key=lambda r: (-(r["delta"] or 0), -r["a"], r["key"]))
        return dict(n=n, coverage=coverage, panel=sorted(base_sources), observed=observed, topics=rows,
                    all_stories=stories[0])

    def topic_label(self, key: str) -> str:
        if key.startswith("entity:"):
            ent = self.vb.entities.get(key[7:]) or {}
            return ent.get("canonical_name") or key[7:]
        return key

    # ------------------------------------------------------------------ activity (HL08)
    def activity(self) -> dict:
        evs = [e for e in self.ev_all if e["event_type"] in SHOWING | ROOKIE | {"acquisition"}]

        def win(k, size):
            end = self.d - dt.timedelta(days=size * k)
            return end - dt.timedelta(days=size - 1), end

        out = {}
        for size in (7, 28):
            wins = [win(k, size) for k in range(5)]
            per = [[e for e in evs if s <= e["_day"] <= t] for s, t in wins]
            base_sources = {e["source_id"] for w in per[1:] for e in w}
            observed = {sid: sum(any(e["source_id"] == sid for e in w) for w in per) for sid in base_sources}
            coverage = sum(observed.values()) / (5 * len(observed)) if observed else None
            n = [sum(e["source_id"] in base_sources for e in w) for w in per]
            topics = collections.defaultdict(lambda: [[] for _ in range(5)])
            for k, w in enumerate(per):
                for e in w:
                    if e["source_id"] in base_sources or k == 0:
                        for key in self.event_topics(e):
                            topics[key][k].append(e)
            rows = []
            for key, lists in topics.items():
                cur = lists[0]
                if not cur:
                    continue
                orgs = {self.org_group(e) for e in cur}
                shares = [len(lists[k]) / n[k] if n[k] else None for k in range(5)]
                base = [s for s in shares[1:] if s is not None]
                base_mean = sum(base) / 4 if len(base) == 4 else None
                fails = []
                if len(cur) < 3: fails.append(f"공식 사건 {len(cur)}<3")
                if len(orgs) < 2: fails.append(f"독립 실행기관 {len(orgs)}<2")
                if min(n) < MIN_PANEL: fails.append(f"{size}일 창 동종 사건 최소 {min(n)}<{MIN_PANEL}")
                if coverage is None or coverage < MIN_COVERAGE: fails.append(f"coverage {pct(coverage)}<80%")
                delta = ratio = None
                if base_mean is not None and shares[0] is not None:
                    delta = shares[0] - base_mean
                    ratio = shares[0] / base_mean if base_mean else None
                    if base_mean == 0: fails.append("기준 비중 0(신규 관찰)")
                    else:
                        if delta < MIN_DELTA_PP: fails.append(f"비중 변화 {delta * 100:+.1f}%p<+2%p")
                        if ratio < MIN_RATIO: fails.append(f"비중 배수 {ratio:.2f}<1.5")
                rows.append(dict(key=key, label=key, e=len(cur), orgs=len(orgs), share=shares[0], base_share=base_mean,
                                 delta=delta, ratio=ratio, fails=fails, events=sorted(cur, key=lambda e: e["_day"], reverse=True),
                                 window=size))
            out[size] = dict(n=n, coverage=coverage, topics=rows, windows=wins)
        # artists picked up by two or more independent organisers within 28 days
        start = self.d - dt.timedelta(days=27)
        by_artist = collections.defaultdict(list)
        for e in evs:
            if start <= e["_day"] <= self.d:
                for p in self.vb.participants.get(e["event_id"], []):
                    if p["role"] in ("artist", "exhibitor") and p["entity_id"] in self.vb.noted_entities:
                        by_artist[p["entity_id"]].append(e)
        out["artists"] = [dict(entity_id=eid, events=es, orgs=len({self.org_group(e) for e in es}))
                          for eid, es in by_artist.items() if len({self.org_group(e) for e in es}) >= 2]
        return out

    # ------------------------------------------------------------------ H01 (HL12/HL13)
    def headline(self) -> List[dict]:
        cands = []
        for size in (7, 28):
            for t in self.act[size]["topics"]:
                rising = t["delta"] is None or t["base_share"] == 0 or t["delta"] > 0
                kind = "활동 확산" if not t["fails"] else (
                    "새로운 징후" if t["e"] >= 2 and t["orgs"] >= 2 and size == 28 and rising else None)
                self.audit.append(dict(section="H01", candidate=f"활동·{size}일·{t['key']}", passed=not t["fails"], reasons=t["fails"]))
                if kind:
                    cands.append(dict(kind=kind, basis="activity", topic=t["key"], metric=t, strength=min(t["orgs"], 5),
                                      newest=t["events"][0]["_day"].isoformat()))
        for t in self.prs["topics"]:
            if not t["fails"]:
                kind = "보도 집중"
            elif (t["a"] >= MIN_ORIGINS and t["groups"] >= MIN_GROUPS and t["new24"] and t["base_share"] == 0
                  and (self.prs["coverage"] or 0) >= MIN_COVERAGE and min(self.prs["n"]) >= MIN_PANEL):
                # a zero baseline means 'new' only when the panel was actually observed; otherwise it is a collection gap
                kind = "새로운 징후"
            else:
                kind = None
            self.audit.append(dict(section="H01", candidate=f"보도·7일·{t['label']}", passed=not t["fails"], reasons=t["fails"]))
            if kind:
                newest = max(m["_ts"] for st in t["stories"] for m in st).isoformat()
                cands.append(dict(kind=kind, basis="press", topic=t["label"], metric=t, strength=min(t["groups"], 5), newest=newest))
        for a in self.act["artists"]:
            name = self.vb.entities[a["entity_id"]]["canonical_name"]
            cands.append(dict(kind="새로운 징후", basis="artist", topic=name, metric=a, strength=min(a["orgs"], 5),
                              newest=max(e["_day"] for e in a["events"]).isoformat(), entity_id=a["entity_id"]))
        today = [s for s in self.digest if s["lead"]["_ts"] >= self.T - dt.timedelta(hours=24)
                 and not LUXURY.search(s["lead"]["title"] or "")]
        if today:
            cands.append(dict(kind="주요 소식", basis="story", topic=today[0]["lead"]["title"], metric=today[0], strength=0,
                              newest=today[0]["lead"]["_ts"].isoformat()))
        rank = {"활동 확산": 0, "보도 집중": 1, "새로운 징후": 2, "주요 소식": 3}
        cands.sort(key=lambda c: c["newest"], reverse=True)
        cands.sort(key=lambda c: (rank[c["kind"]], -c["strength"]))
        picked, topics, market = [], set(), 0
        for c in cands:
            key = c["topic"].casefold()
            if key in topics:
                continue
            is_market = c["topic"] in ("경매·시장", "아트페어") or (c["basis"] == "story" and c["metric"]["topic"] == "market")
            if is_market and (market or not picked):
                if not picked and c["kind"] in ("활동 확산", "보도 집중"):
                    pass  # HL13: auction cards are not hero by default
                continue
            picked.append(c)
            topics.add(key)
            market += is_market
            if len(picked) == 3:
                break
        return picked

    # ------------------------------------------------------------------ H02 (FP04)
    def artists_in_focus(self) -> dict:
        d = self.d
        r0, r1 = d - dt.timedelta(days=89), d
        p0, p1 = d - dt.timedelta(days=179), d - dt.timedelta(days=90)
        art_since = self.T - dt.timedelta(days=180)
        e_counts = collections.defaultdict(lambda: [0, 0])
        e_ok = self.e_axis_observed
        for a in self.articles_180:
            for _, eid in self.matcher.find(a["title"]):
                if a["_ts"] >= self.T - dt.timedelta(days=90):
                    e_counts[eid][0] += 1
                elif a["_ts"] >= art_since:
                    e_counts[eid][1] += 1
        rows = []
        per_artist = collections.defaultdict(list)
        for e in self.ev_all:
            if p0 <= e["_day"] <= r1 and e["event_type"] in SHOWING | ROOKIE:
                for p in self.vb.participants.get(e["event_id"], []):
                    if p["role"] in ("artist", "exhibitor") and p["entity_id"] in self.vb.noted_entities:
                        per_artist[p["entity_id"]].append(e)
        for eid, evs in per_artist.items():
            recent = [e for e in evs if r0 <= e["_day"] <= r1]
            prev = [e for e in evs if p0 <= e["_day"] <= p1]
            if not recent:
                continue
            groups = {self.org_group(e) for e in recent}
            axes = {"I": (sum(self.org_kind(e) == "I" for e in recent), sum(self.org_kind(e) == "I" for e in prev)),
                    "G": (sum(self.org_kind(e) == "G" for e in recent), sum(self.org_kind(e) == "G" for e in prev))}
            if e_ok:
                axes["E"] = tuple(e_counts[eid])
            up = [k for k, (c, p) in axes.items() if c > p]
            trigger = [e for e in recent if e["_day"] >= d - dt.timedelta(days=29)]
            fails = []
            if len(recent) < FOCUS_EVENTS: fails.append(f"90일 사건 {len(recent)}<{FOCUS_EVENTS}")
            if len(groups) < FOCUS_GROUPS: fails.append(f"독립 주체 {len(groups)}<{FOCUS_GROUPS}")
            if len(up) < FOCUS_AXES: fails.append(f"증가 축 {len(up)}<{FOCUS_AXES}" + ("" if e_ok else " (E축 미관측)"))
            if not trigger: fails.append("최근 30일 새 계기 없음")
            rows.append(dict(entity_id=eid, recent=len(recent), prev=len(prev), groups=len(groups), axes=axes, up=up,
                             trigger=sorted(trigger, key=lambda e: e["_day"], reverse=True), fails=fails))
        for r in rows:
            self.audit.append(dict(section="H02", candidate=self.vb.entities[r["entity_id"]]["canonical_name"],
                                   passed=not r["fails"], reasons=r["fails"]))
        ok = [r for r in rows if not r["fails"]]
        ok.sort(key=lambda r: (-len(r["up"]), -(r["trigger"][0]["_day"].toordinal()), r["entity_id"]))
        near = sorted((r for r in rows if r["fails"]), key=lambda r: (len(r["fails"]), -r["recent"], -r["groups"], r["entity_id"]))
        return dict(selected=ok[:6], near=near[:8], evaluated=len(rows))

    # ------------------------------------------------------------------ H03 (FP05)
    def trend_news(self, hero_topics: Iterable[str]) -> dict:
        hero = {t.casefold() for t in hero_topics}
        since = self.T - dt.timedelta(days=14)
        stories = [s for s in self.digest if s["lead"]["_ts"] >= since and not LUXURY.search(s["lead"]["title"] or "")]
        event_entities = {p["entity_id"] for e in self.ev_all if abs((e["_day"] - self.d).days) <= 30
                          for p in self.vb.participants.get(e["event_id"], [])}
        event_entities |= {e["organizer_entity_id"] for e in self.ev_all if abs((e["_day"] - self.d).days) <= 30}
        rows = []
        for s in stories:
            text = " ".join(m["title"] or "" for m in s["members"][:4])
            keys = {k.casefold() for k in topics_of(text)} | {n.casefold() for n, _ in s["names"]}
            relation = "direct_evidence" if keys & hero else ("contextual" if s["names"] else "mention")
            has_event = any(eid in event_entities for _, eid in s["names"])
            rows.append(dict(story=s, relation=relation, has_event=has_event))
        order = {"direct_evidence": 0, "contextual": 1, "mention": 2}
        rows.sort(key=lambda r: (r["story"]["lead"]["published_at"] or "", r["story"]["lead"]["article_id"]), reverse=True)
        rows = [r for r in rows if id(r["story"]) not in self.hero_story_ids]
        rows.sort(key=lambda r: (order[r["relation"]] if r["relation"] == "direct_evidence" else 1, -r["story"]["score"], not r["has_event"]))
        shown = [r for r in rows if r["relation"] != "mention"][:4] or rows[:4]
        crit = collections.defaultdict(list)
        for s in stories:
            if s["topic"] == "criticism":
                for _, eid in s["names"]:
                    crit[eid].append(s)
        views = [(eid, ss) for eid, ss in crit.items() if len({news_digest.outlet_of(x["lead"]) for x in ss}) >= 2]
        return dict(cards=shown, views=views[:1], total=len(stories))

    # ------------------------------------------------------------------ H04 (FP06)
    def exhibitions(self, hero_topics, focus_ids) -> dict:
        d = self.d
        news_hits = collections.Counter(eid for s in self.digest if s["lead"]["_ts"] >= self.T - dt.timedelta(days=14)
                                        for _, eid in s["names"])
        hero = {t.casefold() for t in hero_topics}
        rows = []
        open_now = 0
        for ev in self.vb._events_for(self.R):
            if ev["event_type"] not in SHOWING:
                continue
            s, e = day(ev["start_date"]), day(ev["end_date"])
            if not s:
                continue
            current = bool(e and s <= d <= e)
            open_now += current
            if not (current or d < s <= d + dt.timedelta(days=60)):
                continue
            ids = {p["entity_id"] for p in self.vb.participants.get(ev["event_id"], [])}
            org = ev["organizer_entity_id"] or (self.vb.venues.get(ev["venue_id"]) or {}).get("owner_entity_id")
            why = []
            linked = {i for i in ids | {org} if i and news_hits.get(i)}
            if linked:
                why.append("최근 14일 보도 " + ", ".join(f"{self.vb.entities[i]['canonical_name']} {news_hits[i]}건" for i in list(linked)[:2]))
            focus = ids & set(focus_ids)
            if focus:
                why.append("ARTISTS IN FOCUS 작가 참여")
            tk = {k.casefold() for k in self.event_topics(ev)} & hero
            if tk:
                why.append("오늘의 인사이트 주제와 같음: " + ", ".join(sorted(tk)))
            independent = self.org_kind(ev) == "I" and not ev["tour_id"]
            rows.append(dict(event=ev, current=current, start=s, end=e, why=why, independent=independent,
                             linked=len(linked) + len(focus)))
        eligible = [r for r in rows if r["why"]]
        for r in rows:
            self.audit.append(dict(section="H04", candidate=r["event"]["title"], passed=bool(r["why"]),
                                   reasons=[] if r["why"] else ["직접 연결 근거 없음(보도·인사이트·주목 작가)"]))
        eligible.sort(key=lambda r: (not r["current"], not r["independent"], -r["linked"], abs((r["start"] - d).days), r["event"]["event_id"]))
        cities = collections.Counter(r["event"]["city"] for r in rows if r["current"] and r["event"]["city"])
        return dict(cards=eligible[:3], candidates=len(rows), eligible=len(eligible), open_now=open_now, cities=cities.most_common(5))

    # ------------------------------------------------------------------ H05 (FP07)
    def gallery_moves(self) -> dict:
        d = self.d
        inst_by_artist = collections.defaultdict(list)
        for ev in self.vb.events.values():
            if (self.vb.entities.get(ev["organizer_entity_id"]) or {}).get("entity_type") in ("institution", "museum", "biennial", "foundation"):
                when = day(ev["start_date"])
                if when and abs((when - d).days) <= 365:
                    for p in self.vb.participants.get(ev["event_id"], []):
                        inst_by_artist[p["entity_id"]].append(ev)
        rows = []
        for ev in self.ev_all:
            if self.org_kind(ev) != "G" or ev["event_type"] not in SHOWING or not (d - dt.timedelta(days=29) <= ev["_day"] <= d):
                continue
            artists = [p for p in self.vb.participants.get(ev["event_id"], []) if p["role"] in ("artist", "exhibitor")]
            follow = [(p, inst_by_artist[p["entity_id"]][0]) for p in artists if inst_by_artist.get(p["entity_id"])]
            rows.append(dict(event=ev, artists=artists, follow=follow, group=self.org_group(ev)))
        rows.sort(key=lambda r: r["event"]["_day"], reverse=True)
        rows.sort(key=lambda r: not r["follow"])
        seen, cards = set(), []
        for r in rows:
            if r["group"] in seen:
                continue
            seen.add(r["group"])
            cards.append(r)
            if len(cards) == 2:
                break
        roster = [x for x in self.vb.relationships_all if x["rel_type"] in ("represents", "listed_artist")
                  and (self.vb.entities.get(x["object_entity_id"]) or {}).get("entity_type") == "gallery"]
        return dict(cards=cards, candidates=len(rows), roster=len(roster))

    # ------------------------------------------------------------------ H06 (FP08)
    def patterns(self) -> dict:
        d = self.d
        cur = [e for e in self.ev_all if e["event_type"] in SHOWING and d - dt.timedelta(days=89) <= e["_day"] <= d]
        prev = [e for e in self.ev_all if e["event_type"] in SHOWING and d - dt.timedelta(days=179) <= e["_day"] <= d - dt.timedelta(days=90)]
        oc, op = len({self.org_group(e) for e in cur}), len({self.org_group(e) for e in prev})
        fails = []
        if len(cur) < PATTERN_EVENTS or len(prev) < PATTERN_EVENTS: fails.append(f"구간별 사건 {len(cur)}/{len(prev)} (각 {PATTERN_EVENTS} 필요)")
        if oc < PATTERN_ORGS or op < PATTERN_ORGS: fails.append(f"구간별 기관 {oc}/{op} (각 {PATTERN_ORGS} 필요)")
        rows = []
        if not fails:
            tc = collections.Counter(k for e in cur for k in self.event_topics(e))
            tp = collections.Counter(k for e in prev for k in self.event_topics(e))
            for k in set(tc) | set(tp):
                s1, s0 = tc[k] / len(cur), tp[k] / len(prev)
                rows.append(dict(topic=k, cur=tc[k], prev=tp[k], s1=s1, s0=s0, delta=s1 - s0,
                                 examples=[e for e in cur if k in self.event_topics(e)][:2]))
            rows.sort(key=lambda r: (-r["delta"], r["topic"]))
        spread = [c for c in self.vb.cards() if c["edition_region"] == self.R and c["section"] == "H06" and c["card_kind"] != "gap_notice"]
        # a topic card needs at least 3 events from 2 organisers now (one Kiaf is not a pattern)
        shown = [r for r in rows if r["delta"] > 0 and r["cur"] >= 3 and len({self.org_group(e) for e in cur if r["topic"] in self.event_topics(e)}) >= 2]
        return dict(fails=fails, n_cur=len(cur), n_prev=len(prev), topics=shown[:2],
                    all_topics=rows, spread=spread[:2])

    # ------------------------------------------------------------------ H07 (FP09)
    def rookie(self) -> dict:
        d = self.d
        by = collections.defaultdict(list)
        for e in self.ev_all:
            if e["event_type"] in ROOKIE and d - dt.timedelta(days=364) <= e["_day"] <= d + dt.timedelta(days=120):
                for p in self.vb.participants.get(e["event_id"], []):
                    by[p["entity_id"]].append(e)
        rows = []
        for eid, evs in by.items():
            orgs = {self.org_group(e) for e in evs}
            types = {e["event_type"] for e in evs}
            fails = []
            if len(orgs) < 2: fails.append(f"선정·지원 주체 {len(orgs)}<2")
            if len(types) < 2: fails.append(f"사건 유형 {len(types)}<2")
            fails.append("초기 경력(첫 개인전 10년 이내) 미확인")
            rows.append(dict(entity_id=eid, events=sorted(evs, key=lambda e: e["_day"], reverse=True), orgs=len(orgs),
                             types=sorted(types), fails=fails))
        ready = [r for r in rows if len(r["fails"]) == 1]  # only the career check is missing
        return dict(observed=rows, ready=ready[:2], candidates=len(rows))

    # ------------------------------------------------------------------ H08 (FP10)
    def market(self) -> dict:
        out = dict(auction=None, report=None)
        con = self.vb.auction
        if con is not None:
            pat = dict(AUCTION_REGION)[self.R]
            rx = re.compile(pat, re.I)
            latest = con.execute("SELECT max(sale_date) FROM normalized_lots").fetchone()[0]
            if latest:
                end = dt.date.fromisoformat(latest[:10])
                start = end - dt.timedelta(days=182)
                prev_start, prev_end = start - dt.timedelta(days=365), end - dt.timedelta(days=365)
                stats = []
                for s, e in ((start, end), (prev_start, prev_end)):
                    rows = con.execute("SELECT location, house, status, price_usd, comparison_group FROM normalized_lots "
                                       "WHERE sale_date BETWEEN ? AND ?", (s.isoformat(), e.isoformat())).fetchall()
                    rows = [r for r in rows if rx.search(f"{r[0] or ''} {r[1] or ''}")]
                    sold = [r for r in rows if r[2] == "sold"]
                    offered = [r for r in rows if r[2] in ("sold", "bought_in", "unsold")]
                    comp = sorted(r[3] for r in sold if r[4] == "hammer_plus_premium:USD" and r[3])
                    stats.append(dict(start=s.isoformat(), end=e.isoformat(), offered=len(offered), sold=len(sold),
                                      sell_through=(len(sold) / len(offered)) if offered else None,
                                      median=comp[len(comp) // 2] if comp else None, n_price=len(comp),
                                      houses=collections.Counter(r[1] for r in rows).most_common(3)))
                if stats[0]["offered"] >= 10:
                    out["auction"] = dict(latest=latest[:10], cur=stats[0], prev=stats[1])
        geo = REGION_GEO.get(self.R, ())
        reps = [r for r in self.vb.reports_all if (r["geo_scope"] or "") in geo]
        if reps:
            reps.sort(key=lambda r: r["published_date"] or "", reverse=True)
            out["report"] = reps[0]
        return out

    # ------------------------------------------------------------------ assemble
    def build(self) -> dict:
        self.articles = self.load_articles(35)
        self.articles_180 = self.load_articles(180)
        self.ev_all = self.events()
        self.prs = self.press()
        self.e_axis_observed = (self.prs["coverage"] or 0) >= MIN_COVERAGE
        self.act = self.activity()
        recent14 = [a for a in self.articles if a["_ts"] >= self.T - dt.timedelta(days=14)]
        self.digest = news_digest.build_stories(recent14, self.vb.is_specialist, self.matcher, self.d.isoformat())
        for s in self.digest:
            s["lead"]["_ts"] = s["lead"].get("_ts") or ts(s["lead"]["published_at"])
        cards = self.headline()
        self.hero_story_ids = {id(c["metric"]) for c in cards if c["basis"] == "story"}
        hero_topics = [c["topic"] for c in cards if c["basis"] != "story"]
        focus = self.artists_in_focus()
        snap = dict(region=self.R, asof=self.asof.isoformat(), T=self.T.isoformat(), model_version=MODEL_VERSION,
                    headline=cards, press=self.prs, activity=self.act, focus=focus,
                    news=self.trend_news(hero_topics),
                    exhibitions=self.exhibitions(hero_topics, [r["entity_id"] for r in focus["selected"]]),
                    galleries=self.gallery_moves(), patterns=self.patterns(), rookie=self.rookie(), market=self.market(),
                    audit=self.audit)
        snap["weekly"] = self.weekly()
        snap["gaps"] = self.diagnose(snap)
        return snap

    def weekly(self) -> dict:
        """'숫자로 본 한 주' (한장요약 W42 1쪽 구조, HD10/HD11): panel stories now vs the 4 previous weeks."""
        n = self.prs["n"]
        base = sum(n[1:]) / 4 if len(n) == 5 else None
        topics = [t for t in self.prs["topics"] if not t["key"].startswith("entity:")]
        top = max(topics, key=lambda t: t["a"], default=None)
        market = next((t for t in topics if t["key"] == "경매·시장"), None)
        seasonal = sorted({e["title"] for e in self.ev_all if e["event_type"] in ("fair_edition", "biennial_edition")
                           and (day(e["end_date"]) or e["_day"]) >= self.d - dt.timedelta(days=6) and e["_day"] <= self.d})
        return dict(stories=n[0], base=base, top=top, market=market, seasonal=seasonal[:3],
                    upcoming=sorted((e for e in self.ev_all if e["event_type"] in SHOWING and self.d < e["_day"] <= self.d + dt.timedelta(days=14)),
                                    key=lambda e: e["_day"])[:6])

    def diagnose(self, snap: dict) -> List[dict]:
        """Per-section data sufficiency (what the logic needs vs what exists) — the '부족한 것' list."""
        g = []
        p, a28 = snap["press"], snap["activity"][28]

        def add(section, status, detail, need, action):
            g.append(dict(section=section, status=status, detail=detail, need=need, action=action))

        add("H01 보도 집중", "충족" if any(c["kind"] == "보도 집중" for c in snap["headline"]) else
            ("부분" if p["coverage"] and p["coverage"] >= MIN_COVERAGE and min(p["n"]) >= MIN_PANEL else "불충족"),
            f"패널 출처 {len(p['panel'])}곳 · coverage {pct(p['coverage'])} · 주별 소식 {p['n']}",
            "D32~37 기사(35일 이상 연속), D72 원전·매체그룹(owner_group), 본문(B) 또는 공식자료(P)",
            "출처를 35일 연속 수집해 패널 편입. 매체 소유그룹 매핑 추가. 현재 제목만(T) 확보")
        add("H01 활동 확산", "충족" if any(c["kind"] == "활동 확산" for c in snap["headline"]) else
            ("부분" if a28["coverage"] and a28["coverage"] >= MIN_COVERAGE else "불충족"),
            f"28일 창 동종 사건 {a28['n']} · coverage {pct(a28['coverage'])}",
            "D08~31 공식 사건(일 단위 날짜), D70 회차·역할, 140일 이력",
            "관찰기관 추가와 일일 수집으로 28일 창 사건 20건 이상 확보")
        f = snap["focus"]
        add("H02 작가 포커스", "충족" if f["selected"] else "불충족",
            f"평가 작가 {f['evaluated']}명 · 자격 통과 {len(f['selected'])}명 · E축 {'관측' if self.e_axis_observed else '미관측'}",
            "D59 작가 ID, D61 작가 스토리, I/G/E 3축(비평 D69/D71), coverage 80%",
            "작가별 전시 이력 180일 확보, 비평 기사-작가 연결(article_mentions) 갱신")
        nw = snap["news"]
        add("H03 트렌드 뉴스", "충족" if nw["cards"] else "불충족", f"14일 소식 {nw['total']}개 · 비평의 관점 {len(nw['views'])}",
            "D32~37 원발행일·실질수정일, 원전 계보(origin_family)", "재전재 묶음은 제목 유사도 근사. 원전 계보 필드 수집 필요")
        ex = snap["exhibitions"]
        add("H04 전시", "충족" if ex["cards"] else "불충족", f"후보 {ex['candidates']} · 직접 연결 {ex['eligible']}",
            "D08~20 전시, D31 관찰기관, D59 연결", "전시 참여 작가 명단 추출 범위 확대")
        gm = snap["galleries"]
        add("H05 갤러리 무브", "부분" if gm["cards"] else "불충족",
            f"30일 갤러리 개막 {gm['candidates']} · 소속 명단 {gm['roster']}건(첫 관측)",
            "D21~25 소속 관계의 두 번째 비교 관측, D56", "갤러리 소속 명단을 주 1회 재관측해 신규·이탈 비교(첫 관측은 새 관계 아님)")
        pt = snap["patterns"]
        add("H06 패턴", "충족" if pt["topics"] else "불충족", "; ".join(pt["fails"]) or f"90일 사건 {pt['n_cur']}/{pt['n_prev']}",
            "D59/D60 주제 태그, 공통 기관 패널, tour_id", "주제 태그는 제목 키워드 사전(버전 frontpage-1). 전시 서문 기반 태그 필요")
        rk = snap["rookie"]
        add("H07 Rookie", "부분" if rk["ready"] else "불충족", f"관찰 후보 {rk['candidates']}명 · 2주체·2유형 {len(rk['ready'])}명",
            "D26~31 공식 선정·레지던시, 첫 개인전 연도(경력 확인)", "작가 경력(첫 개인전) 공식 약력 수집")
        mk = snap["market"]
        add("H08 시장", "부분" if mk["auction"] or mk["report"] else "불충족",
            (f"경매 최신 관측 {mk['auction']['latest']}" if mk["auction"] else "지역 경매 비교 표본 없음")
            + (f" · 보고서 {mk['report']['title'][:30]}" if mk["report"] else ""),
            "D40~44 보고서, D48~52 경매 결과(가을 시즌)", "2026 가을 경매 결과는 경매사 권한·robots 제한으로 미수집")
        return g


def build_all(vb, asof: dt.date) -> Dict[str, dict]:
    return {r: FrontPage(vb, r, asof).build() for r in FRONT_EDITIONS}
