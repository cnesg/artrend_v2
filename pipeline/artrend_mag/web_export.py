"""JSON feed for the ARTREND web front (Next.js on Vercel).

Same data and logic as the Obsidian vault (trend headlines, editor notes, automatic judgements, Rookie checks),
written as plain JSON per edition and day:

    <out>/site.json                      asof, dates, editions, policy
    <out>/<date>/<edition>.json          one front page
    <out>/rookie_watchlist.json          cumulative watchlist
    <out>/logic.json                     criteria and weights shown on the method page

Text policy is the vault's: titles, links, short summaries (<= 300 chars) and rule-made sentences only; no article
bodies or images; everything stays `publishable: false` until an editor approves it.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from . import daily_trend, early, editorial, keywords, news_digest
from .config import DB_PATH, WORK_ROOT
from .obsidian_vault import EDITION_KO, TOP_STORIES, VaultBuilder, day, useful_ko

EDITIONS = ("KR", "JP", "AMERICAS", "EUROPE")
EDITION_EN = {"KR": "Korea", "JP": "Japan", "AMERICAS": "Americas", "EUROPE": "Europe"}
SLUG = {"KR": "kr", "JP": "jp", "AMERICAS": "americas", "EUROPE": "europe"}
DEFAULT_OUT = WORK_ROOT / "outputs" / "web_data"
WIKI = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")
SMALL = re.compile(r"</?small>")


INTERNAL = re.compile(r"\b(?:[HRE]V?\d{2}|D\d{2})\b|Blueprint|ROOKIE RADAR 판단|Rookie|루키 트랙|캘린더용|관찰 대상|작가 포커스|기록용|판단 근거|"
                      r"\([A-Z]\)\s?축|축을 볼 때|독립 보도|다음 확인|EXHIBITIONS TO WATCH|전시 캘린더|트렌드 판단|비평 자료|분류됐|"
                      r"(?:확인|추적|기록|보관|분류)한다[.)]?$")


def reader_text(text: Optional[str]) -> Optional[str]:
    """Editor notes are written for editors; drop sentences carrying internal codes or workflow words before readers see them."""
    if not text:
        return text
    sents = re.split(r"(?<=[.다])\s+", text.strip())
    kept = [s for s in sents if not INTERNAL.search(s)]
    out = " ".join(kept).strip()
    return out or None


FIRST_SENT = re.compile(r"(?<=[.다])\s")

# How many outlets carried a story is shown once, as the clickable source count; it is not a reason the story matters.
COVERAGE = re.compile(r"\d+\s*(?:개|곳)\s*(?:이상의?\s*)?(?:매체|언론)|\d+곳 이상|각자 보도|따로 보도|보도 확산|매체 보도|독립 보도|기사 근거|보도했다|일제히 보도")
EDITOR_TASK = re.compile(r"넣는다|넣어야|찾아 |확보하지 못|원문을|CONTEXT|후보로 본다|후보다\.?$|기록해 둔다|정리한다")
GENERIC_SO_WHAT = {editorial.READER_SO_WHAT[None]}


ARTIST_CATS = [
    ("수상", r"상\b|수상|award|prize|prix|preis|賞"), ("첫 공개", r"첫|처음|최초|내한|first|debut|初"),
    ("관객 화제", r"관람|관객|명이|매진|티켓|visitors|crowd"), ("경매·시장", r"경매|낙찰|억|auction|sold|record|落札"),
    ("회고전", r"회고|retrospective|回顧"), ("소장", r"소장|기증|acqui|collection|収蔵"), ("부고", r"별세|타계|작고|died|obituary|死去"),
    ("작품", r"작품|신작|work|painting|sculpture|作品"), ("개인전", r"개인전|solo|個展"),
]


def artist_cats(story: str, shows: Optional[int], press: Optional[int]) -> List[str]:
    cats = [c for c, rx in ARTIST_CATS if re.search(rx, story or "", re.I)][:2]
    if shows and "개인전" not in cats and "회고전" not in cats:
        cats.append("전시 중")
    if press and not cats:
        cats.append("뉴스")
    return cats[:3]


def clean_why(items: List[str]) -> List[str]:
    out = []
    for w in items or []:
        parts = [p for p in re.split(r"\s·\s", w) if p.strip() and not COVERAGE.search(p) and not p.startswith("ARTREND 관찰 대상")]
        if parts:
            out.append(" · ".join(parts))
    return out


def reader_point(so_what: Optional[str]) -> str:
    """The 'so what' rewritten as the closing sentence of the lead: what to watch, in a reader's voice."""
    t = reader_text(so_what) or ""
    if not t or t in GENERIC_SO_WHAT:
        return ""
    sents = [x for x in re.split(r"(?<=[.다])\s+", t) if x and not EDITOR_TASK.search(x) and not COVERAGE.search(x)]
    out = []
    for x in sents:
        x = re.sub(r"는지 (?:다시 )?본다\.?$", "는지가 다음 관전 포인트다.", x)
        x = re.sub(r"(?<![는])\s?본다\.?$", " 지켜볼 대목이다.", x)
        out.append(x if x.endswith((".", "다", "?")) else x + ".")
    return " ".join(out)


TAG_SHORT = {"국가·공공 주체의 결정": "공공 결정", "기관·제도·인사 변화": "제도·인사", "금액·수량이 명시됨": "규모",
             "최초·신설": "최초", "공식 선정·수상": "수상"}


def tags_of(why: List[str]) -> List[str]:
    """Auto criteria ('기관·제도·인사 변화('개관') · 최초·신설('첫 ')') become short chips; sentences stay out."""
    out = []
    for w in why or []:
        for p in re.split(r"\s·\s", w):
            label = re.sub(r"\(.*?\)$", "", p).strip()
            if label in TAG_SHORT and TAG_SHORT[label] not in out:
                out.append(TAG_SHORT[label])
    return out


def bullets_of(summary: Optional[str], so_what: Optional[str], title: str = "") -> List[str]:
    """Two or three short lines a phone reader can scan: what happened (complete sentences only), then the point."""
    from . import ko_polish
    out = []
    text = re.sub(r"\s*\(제목 기준·자동번역\)", "", summary or "").strip()
    nxt = re.search(r"다음 날짜:\s*([^.]+)", text)
    text = re.sub(r"\s*다음 날짜:[^.]+\.?", "", text)
    for sent in re.split(r"(?<=[.다])\s+", text):
        sent = ko_polish.polish(sent.strip()) or ""
        if not sent or sent.endswith(("…", "...")) or not re.search(r"[다.]$", sent) or len(sent) < 12:
            continue
        if title and sent.rstrip(".") in title:
            continue
        sent = re.sub(r"\s*[가-힣]+\s?기자\s*=\s*", "", sent)
        sent = re.sub(r"^\[[^\]]+\]\s*|^\([^)]{2,20}\)\s*", "", sent)
        if len(sent) > 120:
            cut = sent[:118].rsplit(" ", 1)[0]
            sent = cut.rstrip(",·") + "…"
        out.append(sent)
        if len(out) == 2:
            break
    nxt = nxt or re.search(r"다음 날짜:\s*([^.]+)", so_what or "")
    point = reader_point(re.sub(r"\s*다음 날짜:[^.]+\.?", "", so_what or ""))
    if point:
        out.append("→ " + re.sub(r"\s—\s", ". ", point, count=1))
    if nxt:
        out.append(f"일정: {nxt.group(1).strip()}")
    return out


def merge_lead(text: Optional[str], so_what: Optional[str]) -> str:
    """One paragraph: what happened, then why it matters to the reader (formerly a separate '그래서?' line)."""
    base = (text or "").strip()
    point = reader_point(so_what)
    if base and not base.endswith((".", "다", "?", "!", ")", "’", "'", "…")):
        base += "."
    if point and point[:20] not in base:
        return f"{base} {point}".strip()
    return base or point


def reader_status(status: str) -> str:
    s = status or ""
    if s.startswith("편집 검토"):
        return "주목할 신진" + ("(경력 확인 중)" if "경력" in s else "")
    if s.startswith("관찰 후보"):
        return "지켜볼 신진"
    if s.startswith("기성"):
        return "기성 작가"
    if s.startswith("후보 단계"):
        return "최종 후보"
    return s.split("(")[0]


def reader_why(why: Optional[str]) -> Optional[str]:
    if not why:
        return why
    t = re.sub(r"\s*[—-]\s*본문 확인\.?|\(제목 기준\)|\s*\(Rookie 아님\)|Rookie 아님|ARTREND DB에서 처음 관찰된\s*", "", why)
    t = re.sub(r"선정 사유는 원문 미확인\.?", "", t).strip(" .")
    return (t + ".") if t and not t.endswith((".", "다")) else (t or None)


def plain(text: Optional[str]) -> str:
    """Obsidian wiki links -> their label; markdown links are kept for the web renderer."""
    if not text:
        return ""
    text = WIKI.sub(lambda m: m.group(2) or m.group(3), text)
    return SMALL.sub("", text).replace("\\[", "[").replace("\\]", "]").replace("\\|", "|").strip()


class WebView(VaultBuilder):
    """VaultBuilder that never writes files and renders links as plain labels."""

    def write(self, rel: str, text: str) -> None:  # pragma: no cover - never called by the exporter
        raise RuntimeError("web export does not write vault files")

    def entity_link(self, eid, fallback=None, in_table=False):
        if eid and eid in self.entities:
            return self.entities[eid]["canonical_name"]
        return fallback or "—"

    def event_link(self, eid, in_table=False):
        return self.events[eid]["title"] or "제목 없음"

    def source_link(self, sid, in_table=False):
        return (self.sources.get(sid) or {}).get("name") or sid or "—"


class Exporter:
    def __init__(self, vb: WebView, asof: dt.date, days: int):
        self.vb, self.asof, self.days = vb, asof, days
        self.watch = editorial.load_watchlist()
        # internal preview: the institutions' own listing images, shown by URL (never downloaded)
        self.images = {}
        for eid, url in vb.con.execute("SELECT event_id, image_url FROM image_rights WHERE event_id IS NOT NULL AND image_url LIKE 'http%' "
                                       "ORDER BY checked_at"):
            self.images[eid] = url

    # -- pieces
    def event_row(self, ev: dict, tr: daily_trend.Trend) -> dict:
        ev_url = next((e["url"] for e in self.vb.event_evidence.get(ev["event_id"], []) if e.get("url")), None)
        return dict(id=ev["event_id"], title=ev["title"] or "제목 없음", kind=tr.kind(ev), type=ev["event_type"],
                    venue=tr.org(ev), city=ev["city"], country=ev["country_code"], start=ev["start_date"], end=ev["end_date"],
                    artists=[n for _, n in tr.artists(ev)][:6], url=ev.get("url") or ev_url, image=self.images.get(ev["event_id"]))

    def exhibitions(self, tr: daily_trend.Trend, d: dt.date) -> dict:
        showing = [ev for ev in tr.events if ev["event_type"] in daily_trend.SHOW_TYPES]
        open_now, opened, upcoming, closing = [], [], [], []
        for ev in showing:
            s, e = day(ev["start_date"]), day(ev["end_date"])
            if s and e and s <= d <= e:
                open_now.append(ev)
                if (e - d).days <= 7:
                    closing.append(ev)
            if s and d - dt.timedelta(days=6) <= s <= d:
                opened.append(ev)
            if s and d < s <= d + dt.timedelta(days=14):
                upcoming.append(ev)
        key = lambda ev: (ev["start_date"] or "", ev["event_id"])
        talked = tr.press_names()
        shows = [ev for ev in opened + upcoming if ev["event_type"] in ("exhibition", "program")]

        def why(ev):
            arts = tr.artists(ev)
            title = ev["title"] or ""
            if any(eid in talked for eid, _ in arts):
                return "작가가 이번 주 보도에도 함께 오르내린다"
            if daily_trend.AWARD_SHOW.search(title):
                return "수상·신진 작가의 후속 전시"
            if re.search(r"retrospective|회고|survey|回顧", title, re.I):
                return "작가 생애를 다시 펼치는 회고전"
            if tr.kind(ev) == "museum" and 0 < len(arts) <= 2:
                return "미술관이 한 작가에게 내준 개인전"
            if tr.kind(ev) == "museum":
                return "미술관 기획전"
            if 0 < len(arts) <= 2:
                return "갤러리 개인전"
            return ""

        feat = sorted(shows, key=lambda ev: (-sum(eid in talked for eid, _ in tr.artists(ev)), not daily_trend.AWARD_SHOW.search(ev["title"] or ""),
                                             tr.kind(ev) != "museum", not 0 < len(tr.artists(ev)) <= 2, key(ev)))
        return dict(open_count=len(open_now), featured=[dict(self.event_row(ev, tr), why=why(ev)) for ev in feat[:6]],
                    opened=[self.event_row(ev, tr) for ev in sorted(opened, key=key, reverse=True)[:12]],
                    upcoming=[self.event_row(ev, tr) for ev in sorted(upcoming, key=key)[:12]],
                    closing=[self.event_row(ev, tr) for ev in sorted(closing, key=lambda ev: ev["end_date"] or "")[:8]],
                    cities=[dict(city=c, count=k) for c, k in collections.Counter(ev["city"] for ev in open_now if ev["city"]).most_common(6)])

    def story_rows(self, stories: List[dict], d: dt.date, notes_by_url: Dict[str, dict]) -> List[dict]:
        """Importance first: editor notes, then objective criteria and trending hooks, then reach; recency breaks ties.
        Stories without any objective fact are kept as '짧은 소식' (one line each), never presented as main news."""
        from . import buzz
        pool = [s for s in stories if (day(s["lead"]["published_at"]) or dt.date.min) >= d - dt.timedelta(days=3)] or stories
        scored = []
        for s in pool[:TOP_STORIES * 4]:
            a = s["lead"]
            lead_g = news_digest.grams(a["title"] or "", a.get("lang"))
            note = next((notes_by_url[m["canonical_url"]] for m in s["members"] if m["canonical_url"] in notes_by_url
                         and (m["canonical_url"] == a["canonical_url"]
                              or news_digest.jaccard(lead_g, news_digest.grams(m.get("title") or "", a.get("lang"))) >= 0.3)), None)
            ko = useful_ko(self.vb.ko_of("articles", a["article_id"], "title", a["title"]))
            s["ko_titles"] = [useful_ko(self.vb.ko_of("articles", m["article_id"], "title", m["title"])) or "" for m in s["members"][:6]]
            j = editorial.auto_judgement(s, day(a["published_at"]) or self.asof)
            if note:
                judged = dict(judged_by="editor", summary=reader_text(note.get("brief") or note.get("summary")),
                              why=[x for x in (reader_text(y) for y in note.get("why", [])) if x],
                              so_what=reader_text(note.get("so_what")) or j["so_what"], level="편집 판단", points=None)
                weight = (100 if note.get("headline") else 8) + 2 * j["points"]
            else:
                hook = buzz.analyse(s, {nm: e for nm, e in s.get("names") or [] if e}, [])
                hot = bool(hook and set(hook["slots"]) & {"first", "heat", "record"})
                if hot and j["level"] == "짧은 소식":
                    j["level"] = "화제"
                summary = j["summary"] or (f"{ko} (제목 기준·자동번역)" if ko else None)
                judged = dict(judged_by="auto", summary=summary, why=j["why"], so_what=j["so_what"], level=j["level"], points=j["points"],
                              lead=merge_lead(j["summary"], j["so_what"]))  # a title-only summary would repeat the headline
                weight = 2 * j["points"] + 6 * hot
            recent = (day(a["published_at"]) or dt.date.min) >= d - dt.timedelta(days=1)
            weight += 2 * math.log2(1 + len(s["outlets"])) + (1.5 if recent else 0)
            art_text = " ".join([m.get("title") or "" for m in s["members"][:6]] + s["ko_titles"] + [a.get("excerpt") or ""])
            if judged["judged_by"] == "auto" and not buzz.ART.search(art_text):
                judged["level"] = "짧은 소식"  # matched a search keyword, but nothing about art in it
            if judged["judged_by"] == "auto" and early.is_after_the_fact(f"{a['title']} {ko or ''}"):
                judged["level"] = "짧은 소식"  # the show is over: a report, not something the reader can still act on
            scored.append((weight, s, ko, judged))
        scored.sort(key=lambda x: -x[0])
        rows = []
        for w_, s, ko, judged in scored:
            a = s["lead"]
            srcs, seen = [], set()
            for m in [a] + list(s["members"]):
                o = self.vb.source_label(m, bare=True)
                if o in seen or not m.get("canonical_url"):
                    continue
                seen.add(o)
                srcs.append(dict(outlet=o, url=m["canonical_url"], date=(m.get("published_at") or "")[:10], title=m.get("title")))
            judged = dict(judged, why=clean_why(judged["why"]), lead=judged.get("lead") or merge_lead(judged["summary"], judged["so_what"]))
            judged["bullets"] = bullets_of(judged["summary"], judged["so_what"], ko or a["title"] or "")
            judged["tags"] = tags_of(judged["why"]) if judged["judged_by"] == "auto" else []
            judged["why"] = judged["why"] if judged["judged_by"] == "editor" else []
            rows.append(dict(title=a["title"], title_ko=ko, url=a["canonical_url"], outlet=self.vb.source_label(a, bare=True),
                             date=(a["published_at"] or "")[:10], n_outlets=len(s["outlets"]),
                             outlets=sorted({self.vb.source_label(m, bare=True) for m in s["members"]})[:8], sources=srcs[:12],
                             topic=s["topic_label"], score=round(w_, 1), short=judged["level"] == "짧은 소식", **judged))
        for r in rows:  # a main story needs at least one readable line under its title
            if not r["short"] and not r["bullets"] and r["judged_by"] == "auto":
                r["short"] = True
        main = [r for r in rows if not r["short"]][:TOP_STORIES]
        short = [r for r in rows if r["short"]][:TOP_STORIES * 2]
        for i, r in enumerate(main + short, 1):
            r["rank"] = i
        return main + short

    def briefing(self, region: str, d: dt.date, obs: Optional[List[dict]] = None, rows: Optional[List[dict]] = None) -> Optional[dict]:
        notes = editorial.load_notes(d)
        exact = bool(notes.get("major") or notes.get("glance"))
        if not exact:  # this week's editor notes still hold: the same stories are on the page
            notes = editorial.load_notes_upto(d)
            notes["editor"] = None
        major = sorted(((k, v) for k, v in (notes.get("major") or {}).items() if v.get("edition") == region and not v.get("exclude")),
                       key=lambda kv: kv[1].get("rank", 99))
        insights = [x for x in (reader_text(t) for t in (notes.get("glance") or {}).get(region, []) if exact) if x]
        if not insights and obs:
            insights = [o["title"] + " → " + re.split(r"\s—\s", FIRST_SENT.split(o["dek"])[0])[0].rstrip(".") + "." for o in obs[:4]]
        packets = {}
        for p_ in editorial.load_packets_upto(d):
            for e in (p_.get("editions") or {}).values():
                for p in e["major"] + e["rookie"]:
                    packets[p["key"]] = p
        pk = packets
        out = []
        for key, v in major:
            p = pk.get(key, {})
            members = p.get("members") or v.get("sources") or []
            newest = max((m.get("date") or "" for m in members), default="")
            if newest and newest < (d - dt.timedelta(days=7)).isoformat():
                continue  # an older week's story
            so = reader_text(v["so_what"]) or editorial.READER_SO_WHAT.get(p.get("topic") if p.get("topic") in editorial.READER_SO_WHAT else None)
            out.append(dict(rank=v.get("rank"), headline=v["headline"], brief=reader_text(v.get("brief")), summary=reader_text(v["summary"]),
                            lead=merge_lead(reader_text(v.get("brief")) or reader_text(v["summary"]), so),
                            why=clean_why([x for x in (reader_text(y) for y in v.get("why", [])) if x]),
                            so_what=reader_text(v["so_what"]) or editorial.READER_SO_WHAT.get(p.get("topic") if p.get("topic") in editorial.READER_SO_WHAT else None),
                            related=v.get("related", []), topic=p.get("topic"),
                            date=p.get("date") or max((m["date"] for m in members), default=None),
                            criteria=[dict(label=c["label"], evidence=c["evidence"]) for c in p.get("criteria", []) if c["id"] not in ("next", "reach")],
                            importance=p.get("importance"),
                            sources=sorted(members, key=lambda m: m["date"], reverse=True)[:12], n_sources=len(p.get("outlets") or members)))
        if not out and rows:
            for r in [r for r in rows if not r["short"]][:3]:
                out.append(dict(rank=r["rank"], headline=r["title_ko"] or r["title"], brief=None, summary=r["summary"] or "", lead=r["lead"],
                                why=r["why"], so_what=r["so_what"], related=[], topic=r["topic"], date=r["date"], criteria=[],
                                importance=None, sources=r["sources"], n_sources=r["n_outlets"]))
        if not out and not insights:
            return None
        return dict(editor=notes.get("editor"), insights=insights, major=out[:5], judged_by="editor" if exact else "auto")

    def rookie(self, region: str, d: dt.date) -> dict:
        notes = editorial.load_notes_upto(d)
        cands = {}
        for pk in editorial.load_packets_upto(d):
            cands.update({n: c for n, c in (pk.get("candidates") or {}).items() if c.get("edition") == region})
        from .frontpage_render import STATUS_ORDER, TRACK_LABEL
        track_rank = {"rookie": 0, "open": 1, "shortlist": 2, "established": 3, "excluded": 4}
        ranked = sorted(cands.values(), key=lambda c: (STATUS_ORDER.index(c["status"]) if c["status"] in STATUS_ORDER else 9,
                                                      track_rank.get(c.get("track"), 5), -sum(x["ok"] is True for x in c["checks"]),
                                                      -c["weight"]["points"], c["name"]))
        people = [dict(name=c["name"], status=reader_status(c["status"]), watch=c["status"].startswith(("편집 검토", "관찰 후보")), award=c["award"],
                       track=TRACK_LABEL.get(c.get("track"), ""), genre=c.get("genre"), why=reader_why(c.get("why")),
                       weight=c["weight"], checks=c["checks"], homonym_note=c.get("homonym_note"))
                  for c in ranked if c.get("track") != "excluded"]
        awards = []
        for key, aw in (notes.get("awards") or {}).items():
            if aw.get("edition_region") != region:
                continue
            w = editorial.award_weight(aw, d)
            awards.append(dict(award=aw["award"], organizer=aw.get("organizer"), weight=w, track=TRACK_LABEL.get(aw.get("track"), ""),
                               track_reason=aw.get("track_reason"), winners=[x["name"] for x in aw.get("winners", [])],
                               url=aw.get("url"), date=aw.get("date")))
        awards.sort(key=lambda a: -a["weight"]["points"])
        return dict(people=people, awards=awards)

    def galleries(self, tr: daily_trend.Trend, d: dt.date) -> dict:
        lo = d - dt.timedelta(days=13)
        openings = tr.opened(lo, d, {daily_trend.GALLERY})
        news = [a for sc in ("KR", "JP", "AMERICAS", "EUROPE", "GLOBAL") for a in self.vb.reading(sc, d - dt.timedelta(days=6), d)
                if (self.vb.sources.get(a["source_id"]) or {}).get("source_kind") == "gallery" and tr.route(a["title"] or "") == tr.E]
        return dict(openings=[self.event_row(ev, tr) for ev in sorted(openings, key=lambda ev: ev["start_date"], reverse=True)[:8]],
                    news=[dict(title=re.sub(r"^News\s+", "", re.sub(r"^(?:News\s+)?Featured in (.+?) \d{1,2} \w+ \d{4}\s+", r"[\1] ", a["title"] or "")),
                               url=a["canonical_url"], date=(a["published_at"] or "")[:10],
                               source=self.vb.source_label(a, bare=True)) for a in news[:8]])

    def criticism(self, region: str, d: dt.date) -> List[dict]:
        lo = d - dt.timedelta(days=6)
        rows = self.vb.reading(region, lo, d) + (self.vb.reading("GLOBAL", lo, d) if region in ("AMERICAS", "EUROPE") else [])
        rows = [a for a in rows if a.get("article_type") in ("review", "criticism", "interview")]
        rows.sort(key=lambda a: a["published_at"] or "", reverse=True)
        return [dict(title=a["title"], url=a["canonical_url"], date=(a["published_at"] or "")[:10], type=a["article_type"],
                     outlet=self.vb.source_label(a, bare=True),
                     title_ko=useful_ko(self.vb.ko_of("articles", a["article_id"], "title", a["title"]))) for a in rows[:10]]

    def fairs(self, tr: daily_trend.Trend, d: dt.date) -> List[dict]:
        out = []
        for ev in tr.events:
            if ev["event_type"] not in ("fair_edition", "biennial_edition"):
                continue
            s, e = day(ev["start_date"]), day(ev["end_date"]) or day(ev["start_date"])
            if not s or e < d - dt.timedelta(days=3) or s > d + dt.timedelta(days=60):
                continue
            status = "진행 중" if s <= d <= e else ("개막 예정" if s > d else "종료")
            out.append(dict(self.event_row(ev, tr), status=status, d_day=(s - d).days if s > d else (e - d).days))
        return sorted(out, key=lambda x: x["start"] or "")

    def artists(self, tr: daily_trend.Trend, ex: dict) -> List[dict]:
        """Seen across several channels first; when none, the artists the week's solo shows put on the wall."""
        people = [dict(p, story=daily_trend.short(p.get("story"), 60) if p.get("story") else None) for p in getattr(tr, "people", [])]
        for p in people:
            p["cats"] = artist_cats(p.get("story") or "", p.get("shows"), p.get("press"))
        seen = {p["name"] for p in people}
        for e in ex["featured"] + ex["opened"] + ex["upcoming"]:
            if len(people) >= 9:
                break
            if not 0 < len(e["artists"]) <= 2:
                continue
            nm = e["artists"][0]
            if nm in seen or len(nm) < 2 or re.search(r"sala|room|screen|project|collection", nm, re.I) or re.fullmatch(r"[A-Z]+", nm):
                continue
            seen.add(nm)
            people.append(dict(entity_id=None, name=nm, press=0, shows=1, story=f"{e['venue']} 《{daily_trend.short(e['title'], 40)}》",
                               story_url=e.get("url"), cats=["개인전"], where=e["venue"]))
        for p in people:
            p.pop("story", None)  # the card shows why the name is up (categories), not a news line
        return people

    OFFICIAL_WEIGHT = re.compile(r"acqui|appoint|named|director|curator|prize|award|winner|shortlist|residen|commission|partnership|alliance|"
                                 r"announce|open call|reopen|new (?:space|gallery|museum)|represent|joins|donat|gift|"
                                 r"소장|수집|임명|선임|관장|수상|선정|공모|레지던시|입주|개관|재개관|협약|기증|후원|발표|"
                                 r"収蔵|就任|受賞|公募|レジデンス|開館", re.I)
    OFFICIAL_NOISE = re.compile(r"모집 공고|봉사단|채용|recruit|vacanc|job|휴관 안내|closed on|holiday|newsletter|ticket|티켓|주차|parking|"
                                r"privacy|개인정보|이벤트 당첨|survey|설문", re.I)

    def official(self, region: str, d: dt.date) -> List[dict]:
        """The institutions' own announcements this fortnight, before any press: acquisitions, appointments,
        prizes, open calls, openings. Housekeeping notices (jobs, closures, tickets) are left out."""
        rows = [a for a in self.vb.reading(region, d - dt.timedelta(days=13), d)
                if (a["source_id"].startswith("news_") or a["source_id"] == "kr_heredium" or a.get("article_type") == "announcement")
                and a["source_id"] not in ("naver_news",)]
        if region in ("AMERICAS", "EUROPE"):
            rows += [a for a in self.vb.reading("GLOBAL", d - dt.timedelta(days=13), d) if a["source_id"].startswith("news_")]
        out, seen = [], set()
        for a in rows:
            title = re.sub(r"\s+", " ", a["title"] or "").strip()
            ko = useful_ko(self.vb.ko_of("articles", a["article_id"], "title", a["title"]))
            if not title or self.OFFICIAL_NOISE.search(title) or a["canonical_url"] in seen:
                continue
            seen.add(a["canonical_url"])
            weight = 2 if self.OFFICIAL_WEIGHT.search(f"{title} {ko or ''}") else 1
            out.append(dict(title=title, title_ko=ko, url=a["canonical_url"], date=(a["published_at"] or "")[:10],
                            org=a.get("publisher") or self.vb.source_label(a, bare=True), weight=weight))
        out.sort(key=lambda r: (-r["weight"], r["date"]), reverse=False)
        out.sort(key=lambda r: (r["weight"], r["date"]), reverse=True)
        return out[:14]

    # -- the first screen: trending now, side cards
    ROOKIE_AXES = ("수상·루키", "신진 경로")

    @staticmethod
    def ago(date: Optional[str], d: dt.date) -> str:
        day_ = day(date)
        if not day_:
            return ""
        n = (d - day_).days
        return "오늘" if n <= 0 else "어제" if n == 1 else f"{n}일 전"

    def top(self, region: str, heads: List[dict], rows: List[dict], rookie: dict, galleries: dict, d: dt.date, ex: Optional[dict] = None,
            signal: Optional[List[dict]] = None) -> dict:
        """TRENDING NOW: the three most important readable stories (Korean titles only; a garbled machine
        translation never goes on the first line). Side cards: the rookie and gallery reads of the day."""
        hangul = re.compile(r"[가-힣]{2}")
        # TRENDING NOW looks forward: shows gathering momentum that are still open or about to open
        trending = [dict(title=f"{daily_trend.short_org(e['venue'])} 《{daily_trend.short(re.sub(r'[《》]', ' ', e['title']), 36)}》", url=e.get("url"),
                         date=e.get("start"), ago=e["status"], topic=e["level"], image=e.get("image"), reason=e["reasons"][0])
                    for e in (signal or [])[:3]]
        # Korean press is read in Korean; for the other editions only stories the desk judged major — machine
        # titles of minor foreign items are too often garbled — and otherwise the week's newest openings
        pool = rows if region == "KR" else [r for r in rows if not r["short"]]
        for r in sorted(pool, key=lambda r: (r["short"], r["rank"])):
            t = daily_trend.FEED_PREFIX.sub("", r.get("title_ko") or r["title"] or "")
            if not hangul.search(t) or len(trending) >= 3 or early.is_after_the_fact(t):
                continue
            trending.append(dict(title=t, url=r["url"], date=r["date"], ago=self.ago(r["date"], d), topic=r["topic"]))
        if len(trending) < 3 and ex:
            venues, titles = set(), set()
            for e in (ex.get("featured") or []) + sorted(ex.get("opened") or [], key=lambda e: e.get("start") or "", reverse=True):
                if len(trending) >= 3:
                    break
                if e["venue"] in venues or e["title"] in titles or not day(e.get("start")) or day(e.get("start")) > d:
                    continue
                venues.add(e["venue"])
                titles.add(e["title"])
                trending.append(dict(title=f"{daily_trend.short_org(e['venue'])}, 《{daily_trend.short(re.sub(r'[《》]', ' ', e['title']), 36)}》", url=e.get("url"), date=e.get("start"),
                                     ago=self.ago(e.get("start"), d), topic="새 전시"))
        rk = next((h for h in heads if h["axis"] in self.ROOKIE_AXES and "신진" in h["title"] and h["power"] >= 2), None)
        if rk:
            rookie_card = dict(title=rk["title"], dek=rk["dek"], label="Rookie Radar")
        elif rookie.get("people"):
            p = rookie["people"][0]
            rookie_card = dict(title=f"{p.get('name')}, {p.get('status')}", dek=reader_why(p.get("why")) or p.get("award") or "", label="Rookie Radar")
        else:
            rk = next((h for h in heads if h["axis"] in self.ROOKIE_AXES), None)
            rookie_card = dict(title=rk["title"], dek=rk["dek"], label="Rookie Radar") if rk else None
        gh = next((h for h in heads if h["axis"] == "갤러리" and (h["power"] >= 2 or not galleries.get("openings"))), None)
        if gh:
            gallery_card = dict(title=gh["title"], dek=gh["dek"], label="Gallery Moves")
        elif galleries.get("openings"):
            g = galleries["openings"][0]
            gallery_card = dict(title=f"{daily_trend.short_org(g.get('venue') or '')}, 《{daily_trend.short(g.get('title') or '', 30)}》", dek=(lambda s_: f"{s_.month}월 {s_.day}일 개막" if s_ else "")(day(g.get("start"))),
                                label="Gallery Moves", url=g.get("url"))
        else:
            gallery_card = None
        used = {c["title"] for c in (rookie_card, gallery_card) if c}
        hero = [i for i, h in enumerate(heads) if h["title"] not in used][:6]
        return dict(trending=trending, rookie=rookie_card, gallery=gallery_card, hero=hero)

    # -- page
    def page(self, region: str, d: dt.date) -> dict:
        week = self.vb.stories(region, d - dt.timedelta(days=6), d, d)
        tr = daily_trend.Trend(self.vb, region, d)
        obs = daily_trend.headlines(self.vb, region, d, week, tr)
        notes_by_url = self.vb.notes_by_url(d)
        topics = collections.Counter(s["topic_label"] for s in week)
        rows = self.story_rows(week, d, notes_by_url)
        ex = self.exhibitions(tr, d)
        kws = keywords.hot(self.vb, region, d, getattr(tr, "people", []))
        heads = [dict(title=o["title"], dek=o["dek"], power=o["power"], power_label=daily_trend.POWER_LABEL[o["power"]],
                      axis=o["axis"], points=[plain(p) for p in (reader_text(x) or "" for x in o.get("points") or []) if p],
                      about=reader_text(plain(o.get("about") or "")) or plain(o.get("about") or ""),
                      what=[plain(x) for x in o.get("what") or []],
                      evidence=plain(o["fact"]), read=reader_text(plain(o["read"])) or "", items=[plain(x) for x in o["items"]])
                 for o in obs]
        for h in heads:
            h["tags"] = keywords.tags_for(" ".join([h["title"], h["dek"]] + h["what"]), kws) or [h["axis"]]
        for h, o in zip(heads, obs):
            h["image"] = next((self.images[k[3:]] for k in o.get("ev_keys") or [] if k[3:] in self.images), None)
            h["after"] = early.is_after_the_fact(h["title"])
        heads = [h for h in heads if not h["after"]] + [h for h in heads if h["after"]]  # a finished show never leads
        rookie = self.rookie(region, d)
        galleries = self.galleries(tr, d)
        orgs = {a.get("venue") for a in ex["featured"]}
        signal = early.Early(self.vb, region, d, tr, self.images, headline_orgs=orgs).run()
        official = self.official(region, d)
        return dict(
            date=d.isoformat(), edition=region, edition_ko=EDITION_KO[region], edition_en=EDITION_EN[region], slug=SLUG[region],
            publishable=False,
            headlines=heads,
            keywords=kws,
            top=self.top(region, heads, rows, rookie, galleries, d, ex, signal),
            early=signal,
            official=official,
            briefing=self.briefing(region, d, obs, rows),
            artists=self.artists(tr, ex),
            stories=rows,
            topics=[dict(label=k, count=v) for k, v in topics.most_common(8)],
            exhibitions=ex,
            galleries=galleries,
            rookie=rookie,
            criticism=self.criticism(region, d),
            fairs=self.fairs(tr, d),
            stats=dict(articles_7d=sum(len(s["members"]) for s in week), stories_7d=len(week)),
        )

    def logic(self) -> dict:
        from .editorial import CRITERIA, ORGANIZER_POINTS, WEIGHT
        return dict(
            importance=[dict(id=c, label=l, weight=WEIGHT[c]) for c, l, _ in CRITERIA]
            + [dict(id="next", label="후속 일정", weight=WEIGHT["next"]), dict(id="observed", label="ARTREND 관찰 대상", weight=WEIGHT["observed"]),
               dict(id="reach", label="독립 보도 확산(3곳 이상)", weight=WEIGHT["reach"])],
            auto_levels=[dict(min=lo, label=lab) for lo, lab in editorial.AUTO_LEVEL],
            organizer_points=ORGANIZER_POINTS,
            rookie_rules=["R01 공식 선정(최종 수상만, 같은 상의 발표·시상·기념전은 1건 — EV09)", "R02 첫 개인전 10년 이내('N번째 개인전' 보도 반영)",
                          "R03 이번 상 외 12개월 안에 다른 주체·다른 유형의 미술 사건", "R05 후속 지원(개인전·레지던시·매입)",
                          "나이·판매·경매 실적은 쓰지 않음, 동명이인 기사는 걸러냄"],
            keyword_rules=[
                f"후보는 미술 개념 사전({len(keywords.CONCEPTS)}개: 매체·주제·형식), 이름 붙은 행사(비엔날레·아트페어·미술상), 보도와 전시에 함께 오른 작가뿐 — 임의의 단어는 나오지 않음",
                f"이번 주 서로 다른 소식 {keywords.MIN_DOCS}건 이상, 서로 다른 매체·기관 {keywords.MIN_SOURCES}곳 이상(같은 보도자료의 복제 기사는 1건). 수집량이 적은 판은 2건",
                f"지난 4주 대비 비중이 {keywords.MIN_LIFT}배 이상 늘어야 함(수집량이 적은 판은 {keywords.MIN_LIFT_THIN}배) — 늘 나오는 말은 트렌드가 아님",
                "기사 제목 기준으로 판단(본문에 스쳐 지나간 단어는 세지 않음), '사진=OO' 같은 출처 표기와 스포츠·행정 소식은 제외",
                "작가 이름은 성과 이름이 모두 있는 경우만(두 글자 이름·한 단어 이름은 일반 단어와 헷갈려 제외)",
            ],
            trend_signals=["강한 신호: 10개 매체 이상, 평소의 1.3배 이상 개막, 전시+보도(3곳 이상) 동시 등장, 같은 이름 비평 2편 이상",
                           "눈에 띄는 신호: 4개 매체 이상, 갤러리 2주 3개 이상 개막, 신진상 3개 이상, 페어·비엔날레 3주 이내",
                           "참고: 그 밖의 현황", "직전 4주 주평균 2건 미만이면 증감 비교를 하지 않음"],
            policy=["게시 전 내부 초안(publishable=false)", "기사 본문·이미지 저장 없음, 요약 300자 이하", "가격·조회수는 예술적 가치로 쓰지 않음",
                    "수집 실패는 '없음'이 아니라 '관찰 안 됨'"],
        )


def export(asof: dt.date, days: int = 7, out: Path = DEFAULT_OUT, db_path: Path = DB_PATH) -> dict:
    out = Path(out)
    staging = out.with_name(out.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        vb = WebView(con, staging, asof, days)
        vb.load()
        ex = Exporter(vb, asof, days)
        dates = [asof - dt.timedelta(days=i) for i in range(days)]
        for d in dates:
            (staging / d.isoformat()).mkdir()
            for region in EDITIONS:
                (staging / d.isoformat() / f"{region}.json").write_text(
                    json.dumps(ex.page(region, d), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (staging / "logic.json").write_text(json.dumps(ex.logic(), ensure_ascii=False, indent=1), encoding="utf-8")
        watch = [dict(name=n, edition=r.get("edition"), first_seen=r.get("first_seen"), awards=r.get("awards", []),
                      level=r.get("award_level"), status=reader_status(r.get("editor_status") or r.get("machine_status") or ""), why=reader_why(r.get("why")),
                      checks=r.get("checks", []), note=r.get("note")) for n, r in sorted(ex.watch.items())]
        (staging / "rookie_watchlist.json").write_text(json.dumps(watch, ensure_ascii=False, indent=1), encoding="utf-8")
        site = dict(asof=asof.isoformat(), dates=[d.isoformat() for d in dates], editions=[dict(code=e, slug=SLUG[e], ko=EDITION_KO[e],
                    en=EDITION_EN[e]) for e in EDITIONS], generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    update_schedule="매일 08:30 KST", publishable=False)
        (staging / "site.json").write_text(json.dumps(site, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        con.close()
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return dict(out=str(out), dates=len(dates), pages=len(dates) * len(EDITIONS))


def main(asof: Optional[str], days: int, out: Optional[str]) -> None:
    d = dt.date.fromisoformat(asof) if asof else dt.date.today()
    print(json.dumps(export(d, days, Path(out) if out else DEFAULT_OUT), ensure_ascii=False))
