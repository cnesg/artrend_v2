"""EARLY SIGNAL — what to see before everyone else does.

A news report that '45만 명이 찾았다' arrives after the show closed. This agent reads the same data forward:
every exhibition, biennale and fair that is open now or opens in the next three weeks is scored on the signals
that come *before* the crowd, and the reader gets the list while there is still time to go.

Signals (all from collected data, each one written out as a reason):
  buzz      distinct outlets that wrote about the show (title or artist + venue) in the last 7 days
  rising    more outlets this week than the week before
  name      the artist's weight: other shows and press about the same name in the last 90 days, an award
  venue     a national/municipal museum, a biennale or fair, or an institution already on the week's headlines
  first     '첫'·'국내 첫'·'최초'·'아시아 첫' in the title or press
  window    opens within 7 days (get in early) or closes within 10 days (last chance)
  free      free admission (from the registry)
Shows that already ended are never on the list; reports about them ('폐막', 'n만 명 찾아') only count as evidence
that this kind of show draws people.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, List, Optional

AHEAD_DAYS = 21
LAST_CHANCE = 10
EARLY_DAYS = 7
MAX_ITEMS = 12

BIG_VENUE = re.compile(r"국립|시립|도립|구립|군립|미술관|박물관|아트센터|문화재단|비엔날레|트리엔날레|아트페어|museum|biennale|triennale|art fair|"
                       r"kunsthalle|fondation|foundation|美術館|芸術祭", re.I)
EVENT_SCALE = re.compile(r"비엔날레|트리엔날레|아트페어|페스티벌|축제|biennale|biennial|triennale|art fair|芸術祭|アートフェア", re.I)
FIRST = re.compile(r"국내 첫|한국 첫|아시아 첫|첫 개인전|최초|첫 회고전|first (?:solo|retrospective|exhibition)|初個展|初の")
AFTER = re.compile(r"폐막|막을? 내려|막내려|마무리|성료|끝났|끝내|대장정|다녀갔|[\d,.]+만?\s?(?:천\s?)?(?:여\s?)?명(?:이|의 관람객이)?\s?(?:찾|방문|관람|다녀|몰)|"
                   r"관람객 [\d,.]+만?\s?명|closes? with|drew [\d,]+ visitors|record attendance", re.I)
QUOTE = re.compile(r"[《〈「『‘'\"“](.+?)[》〉」』’'\"”]")
STOP = {"개인전", "기획전", "특별전", "초대전", "전시", "展", "solo", "exhibition", "the", "and"}


def _day(v) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def title_keys(title: str) -> List[str]:
    """Distinctive phrases of a show title that a news headline would repeat."""
    t = (title or "").strip()
    keys = [q.strip() for q in QUOTE.findall(t) if len(q.strip()) >= 3]
    core = re.sub(r"^\s*(?:제\s?\d+회|\d{4}|第\d+回)\s*", "", QUOTE.sub(" ", t))
    core = re.sub(r"\s{2,}", " ", core).strip(" :-–—·")
    if len(core) >= 5 and core.lower() not in STOP:
        keys.append(core)
    return [k for k in dict.fromkeys(keys) if k.lower() not in STOP]


class Early:
    def __init__(self, vb, edition: str, d: dt.date, tr=None, images: Optional[Dict[str, str]] = None, headline_orgs=()):
        self.vb, self.E, self.d = vb, edition, d
        self.tr = tr
        self.images = images or {}
        self.headline_orgs = set(headline_orgs)

    def articles(self):
        lo = self.d - dt.timedelta(days=90)
        rows = list(self.vb.reading(self.E, lo, self.d))
        if self.E in ("AMERICAS", "EUROPE"):
            rows += list(self.vb.reading("GLOBAL", lo, self.d))
        out = []
        for a in rows:
            ko = self.vb.ko_of("articles", a["article_id"], "title", a["title"]) or ""
            out.append(dict(text=f"{a['title'] or ''} {ko}", outlet=self.vb.source_label(a, bare=True),
                            day=_day(a["published_at"]), url=a["canonical_url"], title=ko or a["title"]))
        return out

    def org(self, ev):
        return self.tr.org(ev) if self.tr else ev["source_id"]

    def artists(self, ev):
        return [p["name_as_listed"] for p in self.vb.participants.get(ev["event_id"], []) if p["role"] in ("artist", "exhibitor")]

    def candidates(self):
        hi = self.d + dt.timedelta(days=AHEAD_DAYS)
        out = []
        for ev in self.vb.events.values():
            if ev["edition_region"] != self.E or ev["event_type"] not in ("exhibition", "biennial", "fair", "festival", "program"):
                continue
            s, e = _day(ev.get("start_date")), _day(ev.get("end_date"))
            if not s or s > hi:
                continue
            if e and e < self.d:
                continue  # already over: too late to go
            if not e and s < self.d - dt.timedelta(days=60):
                continue
            out.append(ev)
        return out

    def score(self, ev, arts: List[dict]) -> Optional[dict]:
        s, e = _day(ev.get("start_date")), _day(ev.get("end_date"))
        venue = self.org(ev)
        names = [n for n in self.artists(ev) if len(n) >= 3][:4]
        keys = title_keys(ev["title"])
        week_lo, prev_lo = self.d - dt.timedelta(days=6), self.d - dt.timedelta(days=13)
        venue_key = re.sub(r"\s*[—(].*$", "", venue)[:12]

        def about(a):
            if any(k in a["text"] for k in keys):
                return True
            return any(n in a["text"] for n in names) and (venue_key and venue_key in a["text"])

        hits = [a for a in arts if a["day"] and about(a)]
        now = {a["outlet"] for a in hits if a["day"] >= week_lo}
        before = {a["outlet"] for a in hits if prev_lo <= a["day"] < week_lo}
        name_press = collections.Counter()
        for n in names[:2]:
            name_press[n] = len({a["outlet"] for a in arts if n in a["text"]})
        reasons, pts = [], 0.0
        if now:
            pts += min(len(now), 8) * 1.2
            reasons.append(f"이번 주 {len(now)}개 매체가 다뤘다" if len(now) > 1 else "이번 주 보도가 나오기 시작했다")
        if len(now) >= 2 and len(now) > len(before):
            pts += 2
            reasons.append("지난주보다 보도가 늘고 있다")
        star = max(name_press.items(), key=lambda x: x[1], default=(None, 0))
        if star[0] and star[1] >= 3:
            pts += min(star[1], 10) * 0.4
            reasons.append(f"{star[0]} — 최근 석 달 {star[1]}개 매체에 오른 이름")
        text = ev["title"] + " " + " ".join(a["text"] for a in hits[:6])
        if FIRST.search(text):
            pts += 2
            reasons.append("'첫'·'최초' — 처음 보는 기회")
        scale = EVENT_SCALE.search(ev["title"]) or ev["event_type"] in ("biennial", "fair")
        if scale:
            pts += 2.5
            reasons.append("비엔날레·페어급 대형 행사")
        elif BIG_VENUE.search(venue):
            pts += 1.2
        if venue in self.headline_orgs:
            pts += 1.5
            reasons.append("오늘 헤드라인에 오른 기관")
        if "무료" in (ev.get("description_excerpt") or "") or "무료" in ev["title"]:
            pts += 0.3
        status = None
        if s > self.d:
            n = (s - self.d).days
            status = f"개막 D-{n}"
            if n <= EARLY_DAYS:
                pts += 1.5
                reasons.append(f"{s.month}월 {s.day}일 개막 — 첫 주에 가면 붐비기 전")
        else:
            n = (self.d - s).days
            status = "오늘 개막" if n == 0 else f"개막 {n + 1}일째"
            if e and (e - self.d).days <= LAST_CHANCE:
                pts += 1.5
                status = f"종료 D-{(e - self.d).days}"
                reasons.append(f"{e.month}월 {e.day}일 종료 — 마지막 기회")
        if pts < 2.5 or not reasons:
            return None
        museum = self.tr is not None and self.tr.kind(ev) == "museum"
        fresh = (s > self.d and (s - self.d).days <= EARLY_DAYS) or (s <= self.d and (self.d - s).days <= EARLY_DAYS)
        if not now and not scale and not (star[1] >= 3) and not (museum and fresh and names):
            return None  # nothing but a date: not a trend yet
        if museum and fresh and names and not now:
            reasons.append("미술관이 막 연 작가전 — 보도가 붙기 전")
        level = "뜨는 중" if len(now) >= 3 else ("주목" if pts >= 5 else "체크")
        return dict(title=ev["title"], venue=venue, city=ev.get("city"), start=ev.get("start_date"), end=ev.get("end_date"),
                    status=status, level=level, score=round(pts, 2), reasons=reasons[:3], url=ev.get("url"),
                    image=self.images.get(ev["event_id"]), event_id=ev["event_id"], artists=names[:3],
                    press=[dict(title=a["title"], url=a["url"], outlet=a["outlet"]) for a in
                           sorted(hits, key=lambda a: a["day"], reverse=True)[:3]])

    def run(self) -> List[dict]:
        arts = self.articles()
        out, seen = [], set()
        for ev in self.candidates():
            r = self.score(ev, arts)
            if not r:
                continue
            k = re.sub(r"\W+", "", (title_keys(r["title"]) or [r["title"]])[0].lower())[:30]
            if k in seen:
                continue  # one show listed by two sources
            seen.add(k)
            out.append(r)
        out.sort(key=lambda r: -r["score"])
        picked, names = [], set()
        for r in out:
            lead = (r.get("artists") or [None])[0]
            if lead and lead in names:
                continue  # one artist, two rooms: the stronger show speaks for both
            names.add(lead)
            picked.append(r)
        return picked[:MAX_ITEMS]


def is_after_the_fact(title: str) -> bool:
    """'경기도자비엔날레 45일간 32만 명 찾아' — a report on something already over."""
    return bool(AFTER.search(title or ""))
