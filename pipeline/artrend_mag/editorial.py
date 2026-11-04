"""Editorial layer for the home mock-up: judge news instead of listing it.

`cli brief --asof D` (network, run once a day after `collect`):
  1. picks this week's major stories per edition and every award/selection story of the last 30 days,
  2. reads the article page where robots.txt allows it and keeps only key sentences (<=300 characters per article;
     the body itself is never stored, only its SHA-256),
  3. scores each major story on named, checkable criteria (Blueprint EV14: fact -> signal -> interpretation),
  4. extracts award facts (edition, prize, support, target) and the named winners,
  5. checks each winner against Blueprint 10 Rookie rules R01-R06 using the DB and a Naver News API name search
     (title-level history, so every 'confirmed' here is 'reported', HL09 level T/B),
  6. writes `work/editorial/packets_<D>.json` and merges winners into the persistent `editorial/rookie_watchlist.json`.

The editor (a person or the session agent) then writes `editorial/notes_<D>.json` — summary, why, so-what per story and
per candidate, each citing packet URLs. `cli vault` renders notes when present and the machine facts otherwise.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from . import news_digest
from .config import WORK_ROOT
from .http import Blocked, Fetcher, FetchError

EDITORIAL_DIR = WORK_ROOT / "editorial"
PACKET_DIR = WORK_ROOT / "work" / "editorial"
WATCHLIST = EDITORIAL_DIR / "rookie_watchlist.json"
MAX_SENTENCES_CHARS = 300
MAJOR_PER_EDITION = 6
NAVER_NEWS = "https://openapi.naver.com/v1/search/news.json"
NAVER_POLICY = "https://developers.naver.com/docs/serviceapi/search/news/news.md"

# ---------------------------------------------------------------- objective importance criteria (shown on the page)
CRITERIA = [
    ("public", "공공·국가 주체", re.compile(r"국립|시립|도립|군립|구립|문체부|문화체육관광부|국가유산청|문화재청|정부|국회|지자체|광역시|"
                                         r"national|ministry|government|federal|state museum|city of|ministère|gouvernement|ministerium|bundes|ministerio|"
                                         r"monuments? historiques?|国立|県立|都立|市立|文化庁|政府", re.I)),
    ("structure", "제도·조직 변화", re.compile(r"개관|폐관|휴관|취소|철회|무산|이전|임명|선임|사임|해임|관장|개편|제도|조례|법안|예산|평가인증|인증|규제|세제|"
                                            r"감정|구조조정|파산|인수|합병|appoint|director|resign|step down|clos(e|ure)|cancel|reopen|"
                                            r"policy|budget|law|tax|layoff|acqui|merger|bankrupt|présiden(?!tiel)|directeur|directrice|nommé|démission|fermeture|réouverture|"
                                            r"liquidation|mort annoncée|rachat|director[ae]? |cierre|nombramiento|Direktor|Schließung|"
                                            r"就任|館長|閉館|開館|中止|休館|予算", re.I)),
    ("scale", "규모(금액·수량)", re.compile(news_digest.MONEY.pattern + r"|\d{2,}\s*(명|점|개국|곳|개관)|\d{2,}\s*(artists|works|countries)", re.I)),
    ("first", "최초·기록", re.compile(r"최초|처음|첫\s|사상|역대|신설|record|first[- ]ever|for the first time|inaugural|初の|史上", re.I)),
    ("award", "공식 선정·수상", re.compile(news_digest.AWARD.pattern + r"|prix |lauréat|premio|Preis\b", re.I)),
]
FUTURE_DATE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
EDITION_NO = re.compile(r"제?\s*(\d{1,3})\s*회")
PRIZE = re.compile(r"(상금|창작지원금|지원금|부상)[^.。]{0,20}?(\d[\d,]*\s*(만\s*원|억\s*원|천만\s*원|억))|"
                   r"(\d[\d,]*\s*(만\s*원|억\s*원|천만\s*원))[^.。]{0,12}?(상금|지원금|창작지원)")
SUPPORT = re.compile(r"(개인전|초대전|수상자전|기념전|레지던시|입주|발간|도록|해외 연수|창작지원|전시 지원|후속 전시)")
YOUTH = re.compile(r"청년|신진|젊은|청년작가|emerging|young|新進|若手")
SENIOR = re.compile(r"본상|원로|공로|화백|평생|작고|lifetime|功労")
GENRE = re.compile(r"\((조각|회화|평면회화|평면|설치|사진|미디어|영상|한국화|서양화|공예|판화|드로잉|퍼포먼스)\)")

# ---------------------------------------------------------------- winner names (proposals; the editor confirms)
NAME = r"[가-힣]{2,4}"
NAME_LIST = re.compile(rf"((?:{NAME}(?:\s*\([^)]{{1,8}}\))?\s*(?:,|·|ㆍ|및|와|과|、)\s*)*{NAME}(?:\s*\([^)]{{1,8}}\))?)\s*(?:작가|화가|조각가|사진가|씨|미술가)")
NAME_AFTER = re.compile(rf"(?:수상자(?:로|에|는)?|수상작가(?:로|에)?|대상(?:에|은)?|선정작가(?:로|에)?|최종 수상자(?:로|에)?)\s*[‘'\"]?({NAME})")
STOP = set("올해의 최종 청년 지역 미술 작가 공동 선정 수상 대상 본상 신진 젊은 우수 특별 올해 국내 해외 한국 전북 전주 서울 부산 대구 광주 대전 "
           "제주 미술상 작가상 조각 회화 평면 설치 사진 미디어 영상 시상 수상자 이번 함께 소속 원로 중견 여성 남성 문화 재단 기념 총 명의 "
           "모두 각각 선정된 수상한 영예 차세대 대표 출신 참여 초대 박사 교수 화백 관장 대표작 심사 심사위원 위원 위원장 국제 세계 신예 그룹".split())
JOSA = re.compile(r"(은|는|이|가|을|를|의|에|와|과|도|로|으로|씨)$")


def winner_names(texts: List[str]) -> List[str]:
    found = collections.Counter()
    for t in texts:
        t = t or ""
        for m in NAME_LIST.finditer(t):
            for part in re.split(r"\s*(?:,|·|ㆍ|및|와|과|、)\s*", m.group(1)):
                n = re.sub(r"\s*\(.*", "", part).strip()
                if n and n not in STOP and not n.endswith(("상", "전", "관", "회", "단", "청", "원")):
                    found[n] += 1
        for m in NAME_AFTER.finditer(t):
            n = JOSA.sub("", m.group(1)) if len(m.group(1)) > 3 else m.group(1)
            if n not in STOP and 2 <= len(n) <= 4:
                found[n] += 1
    return [n for n, _ in found.most_common()]


# ---------------------------------------------------------------- article reading
BODY_SELECTORS = ["[itemprop=articleBody]", "#article-view-content-div", "#articleBody", "#articeBody", "#newsct_article",
                  "#article_body", "#articletxt", ".article_body", ".article-body", ".article_txt", ".news_body", ".view_con",
                  ".news-article-body", ".story-news", "#textBody", "article"]
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+")
KEY_ROOKIE = re.compile(r"심사|평가|선정 이유|높이|주목|작업|작품 세계|작품세계|상금|지원금|개인전|수상자전|레지던시|활동|졸업|첫 |년부터|시상식|이 상은|상은")
KEY_MAJOR = re.compile(r"\d|예정|밝혔|따르면|발표|결정|처음|최초|계획|이번|올해|announced|said|will|plans|according")


def body_text(html: bytes) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "figure", "iframe"]):
        tag.decompose()
    node = None
    for sel in BODY_SELECTORS:
        cand = soup.select_one(sel)
        if cand and len(cand.get_text(" ", strip=True)) > 200:
            node = cand
            break
    if node is None:
        best, size = None, 0
        for div in soup.find_all(["div", "section"]):
            n = sum(len(p.get_text(" ", strip=True)) for p in div.find_all("p", recursive=False))
            if n > size:
                best, size = div, n
        node = best if size > 200 else None
    if node is None:
        return None
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


def key_sentences(text: str, title: str, purpose: str, limit: int = MAX_SENTENCES_CHARS) -> List[str]:
    rx = KEY_ROOKIE if purpose == "rookie" else KEY_MAJOR
    sents = [s.strip() for s in SENTENCE_SPLIT.split(text) if 25 <= len(s.strip()) <= 260]
    sents = [s for s in sents if "@" not in s and "기자" not in s[-12:] and "무단" not in s and "Copyright" not in s]
    scored = sorted(enumerate(sents), key=lambda x: (-len(rx.findall(x[1])), x[0]))
    out, used = [], 0
    for i, s in sorted(scored[:6], key=lambda x: x[0]):
        if used + len(s) > limit:
            continue
        out.append(s)
        used += len(s)
    return out


class Reader:
    def __init__(self, run_stamp: str, cap: int = 160):
        self.stats: Dict[str, int] = {}
        self.f = Fetcher("editorial_article_body", run_stamp, store_raw=False, stats=self.stats, max_requests=cap)
        self.log: List[dict] = []

    def read(self, url: str, title: str, purpose: str) -> dict:
        rec = dict(url=url, fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        try:
            r = self.f.get(url, conditional=False, store=False)
            text = body_text(r.content)
            rec.update(status=r.status, sha256=r.sha256, robots=self.f.robots_state(url))
            if text:
                rec["key_sentences"] = key_sentences(text, title, purpose)
                rec["body_chars"] = len(text)
            else:
                rec["note"] = "본문 영역을 찾지 못함"
        except Blocked as e:
            rec.update(status="blocked", note=str(e)[:160])
        except FetchError as e:
            rec.update(status="error", note=str(e)[:160])
        self.log.append({k: rec.get(k) for k in ("url", "status", "note")})
        return rec


# ---------------------------------------------------------------- Naver name history (title level)
EVENT_KINDS = [("solo", re.compile(r"개인전|초대전|기획 초대|個展|solo")), ("award", re.compile(r"수상|대상|우수상|미술상|작가상|선정|당선")),
               ("residency", re.compile(r"레지던시|입주")), ("group", re.compile(r"단체전|기획전|그룹전|참여|展|전시"))]
EVENT_KEY = re.compile(r"《[^》]{2,30}》|「[^」]{2,30}」|‘[^’]{2,30}’|'[^']{2,30}'|\"[^\"]{2,30}\"|제\s?\d+회\s?\S{2,12}(상|전|제)|\S{2,10}(미술상|작가상|청년작가상)")


class NameHistory:
    def __init__(self, reader: Reader):
        from .sources.kr_naver_news import clean, item_record, load_keys
        self.clean, self.item_record = clean, item_record
        keys = load_keys()
        self.f = None
        if keys:
            self.stats: Dict[str, int] = {}
            self.f = Fetcher("editorial_name_history", reader.f.run_stamp, store_raw=False, stats=self.stats, max_requests=80,
                             api_policy_url=NAVER_POLICY,
                             extra_headers={"X-Naver-Client-Id": keys[0], "X-Naver-Client-Secret": keys[1]}, min_interval=0.3)

    def search(self, name: str) -> Optional[List[dict]]:
        if not self.f:
            return None
        out = []
        for sort in ("date", "sim"):
            try:
                r = self.f.get(NAVER_NEWS, params={"query": f"\"{name}\" 작가", "display": 100, "start": 1, "sort": sort},
                               accept="application/json", conditional=False, store=False)
            except (Blocked, FetchError):
                return None
            for item in json.loads(r.content).get("items", []):
                rec = self.item_record(item)
                if rec and name in rec["title"] and rec["url"] not in {x["url"] for x in out}:
                    kinds = [k for k, rx in EVENT_KINDS if rx.search(rec["title"])]
                    keym = EVENT_KEY.search(rec["title"])
                    out.append(dict(date=(rec["published"] or "")[:10], title=rec["title"], url=rec["url"], publisher=rec["publisher"],
                                    kinds=kinds, event_key=keym.group(0).strip("《》「」‘’'\" ") if keym else None))
        return sorted(out, key=lambda x: x["date"], reverse=True)


ART_CONTEXT = re.compile(r"작가|화가|조각|미술|전시|개인전|초대전|갤러리|미술관|展|레지던시|아트|비엔날레|사진전|회화|설치|작품")
NOT_ART = re.compile(r"배우|드라마|영화|출연|役|예능|아이돌|가수|밴드|전속계약|유퀴즈|웹툰|소설가|아나운서|화보|SNS|커플|주연|개봉|기자의|"
                     r"디자이너|패션|축구|야구|선수|감독|정치|의원|후보|교사|학생")
ORDINAL = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
SOLO_COUNT = re.compile(r"(첫|두|세|네|다섯|여섯|일곱|여덟|아홉|열|\d{1,2})\s*(?:번째|회째|회)?\s*개인전")


def art_history(hist: List[dict]) -> tuple:
    keep = [h for h in hist if ART_CONTEXT.search(h["title"]) and not NOT_ART.search(h["title"])]
    return keep, (1 - len(keep) / len(hist)) if hist else 0.0


def distinct_events(items: List[dict]) -> List[dict]:
    """One row per reported event: same quoted title/award name, or similar headline within 10 days."""
    out: List[dict] = []
    for h in sorted(items, key=lambda x: x["date"]):
        g = news_digest.grams(h["title"], "ko")
        for o in out:
            near = abs((dt.date.fromisoformat(h["date"]) - dt.date.fromisoformat(o["date"])).days) <= 10
            if (h["event_key"] and h["event_key"] == o["event_key"]) or (near and news_digest.jaccard(g, o["_g"]) >= 0.3):
                o["n"] += 1
                o["kinds"] = sorted(set(o["kinds"]) | set(h["kinds"]))
                break
        else:
            out.append(dict(h, n=1, _g=g))
    for o in out:
        o.pop("_g", None)
    return out


def assess(name: str, award: dict, history: Optional[List[dict]], db_events: List[dict], asof: dt.date,
           career: Optional[str] = None) -> dict:
    """Blueprint 10 R01-R06 on what is observable. Never a Rookie verdict: the output is a review status."""
    year_ago = (asof - dt.timedelta(days=365)).isoformat()
    raw = history or []
    hist, foreign_share = art_history(raw)
    events = distinct_events([h for h in hist if h["date"]])
    award_day = award.get("date") or asof.isoformat()
    lo = (dt.date.fromisoformat(award_day[:10]) - dt.timedelta(days=12)).isoformat()
    core = re.sub(r"\W|제?\d+회|\d{4}|선정|수상|부문|미술부문|특별상|대상", "", award.get("title") or "")[:4]
    same = lambda e: bool(core) and core in re.sub(r"\W", "", e["title"])  # earlier shortlist/announcement of the same award
    this_award = [e for e in events if (e["date"] >= lo and "award" in e["kinds"]) or same(e)]
    others = [e for e in events if e["date"] >= year_ago and e not in this_award and e["kinds"]]
    kinds = {"award"} | {k for e in others for k in e["kinds"]}
    kinds |= {e["event_type"] for e in db_events if (e.get("start_date") or "") >= year_ago}
    solos = [e for e in events if "solo" in e["kinds"]]
    counts = []
    for e in events:
        m = SOLO_COUNT.search(e["title"])
        if m:
            k = m.group(1)
            counts.append((ORDINAL.get(k) or int(k), e["date"][:4]))
    checks = [("R01 공식 선정", True, f"{award.get('title')} — 보도 {award.get('n_outlets', 1)}곳")]
    early = None
    if career:
        early, detail = True, f"편집 확인: {career}"
    elif counts and max(counts)[0] >= 5:
        n, y = max(counts)
        early, detail = False, f"{y}년 보도에 '{n}번째 개인전' — 첫 개인전이 10년 넘었을 가능성(재발견·중견 확인 필요)"
    elif solos:
        first = solos[0]["date"][:4]
        early = asof.year - int(first) <= 10
        detail = (f"보도로 확인된 가장 이른 개인전 {first}년" + ("" if early else " — 10년 넘음(재발견·중견 가능성)")
                  + " · 최근 기사 위주 검색이라 더 이른 이력이 있을 수 있음")
    else:
        detail = "개인전 보도 없음 — 경력 미확인(생년으로 대체하지 않음)"
    checks.append(("R02 초기 경력", early, detail))
    ok3 = len(others) >= 1 and len(kinds) >= 2
    if history is None:
        d3 = "이름 검색을 하지 않음(한국어 뉴스 검색만 지원) — 편집자 확인 필요"
    else:
        d3 = (f"이번 수상 외 최근 12개월 미술 관련 보도 사건 {len(others)}건"
              + (" (" + "; ".join(f"{e['date']} {e['title'][:30]}" for e in others[:3]) + ")" if others else "")
              + f" · 유형 {', '.join(sorted(kinds))}")
    homonym = foreign_share >= 0.3
    if homonym and ok3:
        d3 += " — 동명이인 기사가 많아 같은 사람인지 편집자 확인 전에는 통과로 보지 않음"
    checks.append(("R03 독립 확인", (ok3 and not homonym) or (None if ok3 else False) if history is not None else None, d3))
    support = award.get("support") or []
    checks.append(("R05 지속성(후속 지원)", bool(support) or None, "상에 딸린 후속 지원: " + (", ".join(support) if support else "보도에 없음")))
    if SENIOR.search(award.get("title") or "") or early is False:
        status = "재발견·중견 확인 필요"
    elif ok3 and not homonym and early:
        status = "편집 검토 후보"
    elif ok3 and not homonym:
        status = "편집 검토 후보(경력 확인 필요)"
    elif ok3:
        status = "관찰 후보(동명이인 확인 필요)"
    else:
        status = "관찰 후보"
    return dict(status=status, checks=[dict(rule=a, ok=b, detail=c) for a, b, c in checks],
                history=events[:20], db_events=db_events[:10], homonym_risk=homonym,
                homonym_note=f"이름 검색 결과 {len(raw)}건 중 미술과 무관해 보이는 기사 {len(raw) - len(hist)}건 제외" if raw else None)


# ---------------------------------------------------------------- packets
def award_facts(texts: List[str], title: str) -> dict:
    blob = " ".join(texts)
    no = EDITION_NO.search(title) or EDITION_NO.search(blob)
    prize = PRIZE.search(blob)
    return dict(title=title, edition_no=int(no.group(1)) if no else None,
                prize=re.sub(r"\s+", " ", prize.group(0)) if prize else None,
                support=sorted(set(SUPPORT.findall(blob))), youth=bool(YOUTH.search(blob)), senior=bool(SENIOR.search(title)),
                public=bool(CRITERIA[0][2].search(blob)), genres=sorted(set(GENRE.findall(blob))))


def criteria_of(texts: List[str], asof: dt.date, outlets: int, matched: List[tuple]) -> List[dict]:
    blob = " ".join(t for t in texts if t)
    out = []
    for cid, label, rx in CRITERIA:
        m = rx.search(blob)
        if m:
            lo = max(0, m.start() - 25)
            out.append(dict(id=cid, label=label, evidence="…" + blob[lo:m.end() + 25].strip() + "…"))
    for m in FUTURE_DATE.finditer(blob):
        try:
            d = dt.date(asof.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if asof <= d <= asof + dt.timedelta(days=120):
            out.append(dict(id="next", label="후속 일정", evidence=f"{d.isoformat()} (본문·요약 언급)"))
            break
    if matched:
        out.append(dict(id="observed", label="ARTREND 관찰 대상", evidence=", ".join(n for n, _ in matched[:3])))
    if outlets >= 3:
        out.append(dict(id="reach", label="독립 보도 확산", evidence=f"{outlets}개 매체(소유그룹 미확인 상한값)"))
    return out


WEIGHT = {"public": 2, "structure": 2, "scale": 1, "first": 1, "award": 1, "next": 1, "observed": 1, "reach": 1}


def story_packet(st: dict, reader: Optional[Reader], purpose: str, asof: dt.date) -> dict:
    lead = st["lead"]
    members = sorted(st["members"], key=lambda a: (a["source_id"] == "kr_naver_news_api", -len(a.get("excerpt") or "")))
    bodies = []
    if reader:
        for a in members[:2]:
            bodies.append(dict(reader.read(a["canonical_url"], a["title"], purpose), outlet=a.get("publisher") or a["source_id"]))
    texts = [m["title"] for m in st["members"][:6]] + [m.get("excerpt") or "" for m in st["members"][:6]]
    texts += [s for b in bodies for s in b.get("key_sentences", [])]
    crit = criteria_of(texts, asof, len(st["outlets"]), st["names"])
    return dict(key=lead["article_id"], title=lead["title"], url=lead["canonical_url"], date=(lead["published_at"] or "")[:10],
                lang=lead.get("lang"), outlets=sorted(st["outlets"]), topic=st["topic_label"],
                snippets=[dict(outlet=m.get("publisher") or m["source_id"], text=(m.get("excerpt") or "")[:300], url=m["canonical_url"])
                          for m in st["members"][:4] if m.get("excerpt")],
                bodies=bodies, criteria=crit, importance=sum(WEIGHT.get(c["id"], 0) for c in crit),
                members=[dict(title=m["title"], url=m["canonical_url"], outlet=m.get("publisher") or m["source_id"],
                              date=(m["published_at"] or "")[:10]) for m in st["members"][:8]],
                _texts=texts)


def build(asof: dt.date, fetch: bool = True) -> dict:
    import sqlite3
    from . import frontpage
    from .config import DB_PATH
    from .obsidian_vault import VaultBuilder
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    vb = VaultBuilder(con, PACKET_DIR / "_unused", asof, 7)
    vb.load()
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    reader = Reader(stamp) if fetch else None
    names = NameHistory(reader) if fetch else None
    out = dict(asof=asof.isoformat(), built_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"), editions={})
    for region in frontpage.FRONT_EDITIONS:
        fp = frontpage.FrontPage(vb, region, asof)
        fp.articles = fp.load_articles(35)
        week = [a for a in fp.articles if a["_ts"] >= fp.T - dt.timedelta(days=7)]
        stories = news_digest.build_stories(week, vb.is_specialist, fp.matcher, fp.d.isoformat())
        stories = [s for s in stories if not frontpage.LUXURY.search(s["lead"]["title"] or "")]
        # major: rank by the explainable importance criteria first (titles + snippets), read only the top ones
        pre = []
        for s in stories[:80]:
            texts = [m["title"] for m in s["members"][:6]] + [m.get("excerpt") or "" for m in s["members"][:6]]
            crit = criteria_of(texts, asof, len(s["outlets"]), s["names"])
            pre.append((sum(WEIGHT.get(c["id"], 0) for c in crit) + min(len(s["outlets"]), 4) * 0.5 + s["score"] * 0.25, s))
        pre.sort(key=lambda x: -x[0])
        major = [story_packet(s, reader, "major", asof) for _, s in pre[:MAJOR_PER_EDITION]]
        major.sort(key=lambda p: (-p["importance"], -len(p["outlets"])))
        # rookie track: every award/selection story of the last 30 days
        month = [a for a in fp.articles if a["_ts"] >= fp.T - dt.timedelta(days=30) and news_digest.AWARD.search(a["title"] or "")]
        aw_stories = news_digest.build_stories(month, vb.is_specialist, fp.matcher, fp.d.isoformat())
        rookie = []
        for s in aw_stories[:40]:
            text = " ".join(m["title"] for m in s["members"])
            if news_digest.PR_KO.search(s["lead"]["title"]) and not re.search(r"미술|작가|art", text, re.I):
                continue
            if not re.search(r"미술|작가|화가|조각|사진|회화|설치|art|artist|prize|award|美術|作家|アート", text, re.I):
                continue
            p = story_packet(s, reader if region == "KR" or len(rookie) < 12 else None, "rookie", asof)
            p["award"] = award_facts(p["_texts"], s["lead"]["title"])
            p["award"]["n_outlets"] = len(s["outlets"])
            p["names"] = winner_names(p["_texts"]) if region == "KR" else []
            rookie.append(p)
        for p in major + rookie:
            p.pop("_texts", None)
        out["editions"][region] = dict(major=major, rookie=rookie)
    out["candidates"] = {}  # filled by check_names() for names the editor confirmed in notes_<D>.json
    out["fetch_log"] = reader.log if reader else []
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    path = PACKET_DIR / f"packets_{asof.isoformat()}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return dict(path=str(path), major=sum(len(e["major"]) for e in out["editions"].values()),
                rookie_stories=sum(len(e["rookie"]) for e in out["editions"].values()),
                pages_read=sum(1 for x in out["fetch_log"] if x["status"] == 200))


ORGANIZER_POINTS = {"국공립 미술관·지자체": 2, "국가기관": 2, "공공재단": 2, "민간 재단·기업": 1, "언론사·재단": 1, "갤러리": 1,
                    "국제 기관": 2, "상업 공모전·방송사": 0}


FOREIGN_PRIZE_MIN = 7000  # £/€/$ amount treated as ≥ 1천만원; no live FX lookup


def award_weight(award: dict, asof: dt.date) -> dict:
    """How much an award says, from editor-recorded facts. Points are named so the page can show why."""
    pts, why = 0, []
    org = award.get("organizer_type")
    p = ORGANIZER_POINTS.get(org, 0)
    pts += p
    why.append(f"주최 {award.get('organizer', '?')}({org or '유형 미확인'}) +{p}")
    since = award.get("since")
    if since and asof.year - int(since) >= 10:
        pts += 1
        why.append(f"{since}년부터 운영({asof.year - int(since)}년) +1")
    sel = award.get("selection") or ""
    if re.search(r"심사|추천위원|공모|전문가", sel):
        pts += 1
        why.append("전문가 심사·공모 절차 공개 +1")
    if re.search(r"국제|해외|international|Tate|테이트|KW", sel, re.I):
        pts += 1
        why.append("국제 심사위원 +1")
    rewards = " ".join(award.get("rewards") or [])
    if re.search(r"개인전|초대전|수상자전|기념전|전시", rewards):
        pts += 1
        why.append("후속 전시 지원 +1")
    if re.search(r"매입|소장", rewards):
        pts += 1
        why.append("작품 매입·소장 +1")
    money = re.search(r"(\d[\d,]*)\s*(천만|만|억)\s*원", rewards)
    if money:
        value = int(money.group(1).replace(",", "")) * {"만": 1, "천만": 1000, "억": 10000}[money.group(2)]
        if value >= 1000:
            pts += 1
            why.append(f"상금·지원금 {money.group(0)} +1")
    if not money:
        fx = re.search(r"([£€$])\s?(\d[\d,]*)", rewards)
        if fx and int(fx.group(2).replace(",", "")) >= FOREIGN_PRIZE_MIN:
            pts += 1
            why.append(f"상금 {fx.group(0)}(1천만원 이상으로 봄) +1")
    level = "높음" if pts >= 6 else ("보통" if pts >= 3 else "낮음")
    if org == "상업 공모전·방송사":
        level = "제외"
    return dict(points=pts, level=level, reasons=why)


def check_names(asof: dt.date) -> dict:
    """Run Rookie rule checks for winners the editor confirmed, then refresh the persistent watchlist."""
    import sqlite3
    from .config import DB_PATH
    packets, notes = load_packets(asof), load_notes(asof)
    if not packets or not notes:
        raise SystemExit("packets and notes are both required (run `cli brief`, then write editorial/notes_<D>.json)")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    alias = collections.defaultdict(set)
    for eid, name in con.execute("SELECT entity_id, name FROM aliases"):
        alias[name].add(eid)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    names = NameHistory(Reader(stamp, cap=1))
    cands = {}
    for key, aw in notes.get("awards", {}).items():
        weight = award_weight(aw, asof)
        for w in aw.get("winners", []):
            n = w["name"]
            evs = []
            for eid in alias.get(n, ()):
                for ev_id, title, etype, start in con.execute(
                        "SELECT e.event_id, e.title, e.event_type, e.start_date FROM event_participants p JOIN events e USING(event_id) "
                        "WHERE p.entity_id=?", (eid,)):
                    evs.append(dict(event_id=ev_id, title=title, event_type=etype, start_date=start))
            hist = names.search(n) if aw.get("edition_region", "KR") == "KR" else None
            story = next((p for e in packets["editions"].values() for p in e["rookie"] if p["key"] == key), None)
            facts = dict(title=aw.get("award"), n_outlets=aw.get("n_outlets", 1), support=aw.get("rewards") or [],
                         date=story["date"] if story else aw.get("date"))
            c = assess(n, facts, hist, evs, asof, career=w.get("career"))
            if w.get("track", aw.get("track")) == "established":
                c["status"] = "기성·재발견(루키 트랙 아님)"
            elif aw.get("track") == "excluded":
                c["status"] = "제외(공식 선정으로 보기 어려움)"
            elif aw.get("track") == "shortlist":
                c["status"] = "후보 단계(최종 발표 전)"
            cands[n] = dict(name=n, story=key, award=aw.get("award"), track=aw.get("track"), weight=weight,
                            genre=w.get("genre"), why=w.get("why"), edition=aw.get("edition_region", "KR"), **c)
    packets["candidates"] = cands
    (PACKET_DIR / f"packets_{asof.isoformat()}.json").write_text(json.dumps(packets, ensure_ascii=False, indent=1, default=str),
                                                                 encoding="utf-8")
    EDITORIAL_DIR.mkdir(parents=True, exist_ok=True)
    data = load_watchlist()
    for n, c in cands.items():
        if c["track"] == "excluded":
            continue
        row = data.setdefault(n, dict(name=n, first_seen=asof.isoformat(), awards=[]))
        if c["award"] not in row["awards"]:
            row["awards"].append(c["award"])
        row.update(last_checked=asof.isoformat(), edition=c["edition"], track=c["track"], genre=c["genre"],
                   machine_status=c["status"], award_level=c["weight"]["level"], why=c["why"],
                   checks=c["checks"], homonym_risk=c["homonym_risk"], homonym_note=c["homonym_note"])
    WATCHLIST.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(candidates=len(cands), watchlist=len(data), searched=sum(1 for c in cands.values() if c["history"]))


def load_notes(asof: dt.date) -> dict:
    p = EDITORIAL_DIR / f"notes_{asof.isoformat()}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_packets(asof: dt.date) -> dict:
    p = PACKET_DIR / f"packets_{asof.isoformat()}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_watchlist() -> dict:
    return json.loads(WATCHLIST.read_text(encoding="utf-8")) if WATCHLIST.exists() else {}


# ---------------------------------------------------------------- automatic judgement (every story, every day)
# Used wherever the editor has not written a note. Same objective criteria as the packets; sentences are rule-made,
# so the page labels them '자동 판단'. Never feeds cards, signals or `publishable`.
AUTO_LEVEL = [(5, "주요"), (3, "참고할 만함"), (0, "참고")]
TOPIC_SO_WHAT = {
    "market": "시장 참고 소식이다. 금액·판매는 예술적 가치 판단에 쓰지 않고 MARKET CONTEXT에서 같은 작가·장르 흐름과만 비교한다.",
    "people": "인물·수상 소식이다. 수상자가 신진이면 ROOKIE RADAR에서 상의 무게와 루키 조건을 판단하고, 기성이면 작가 포커스 후보로 본다.",
    "policy": "기관·제도 소식이다. 해당 기관 노트에 변화를 기록하고 시행·개관·임기 시작 날짜를 다음 확인 대상으로 둔다.",
    "criticism": "비평·인터뷰 글이다. 사건이 아니라 해석이므로 같은 전시·작가에 다른 관점의 글이 2개 이상 모이면 '비평의 관점'으로 묶는다.",
    "exhibition": "전시·프로그램 소식이다. 전시 캘린더에 반영하고, 관찰 기관·작가의 전시인지와 기간을 확인한다.",
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    for a, b in (("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&apos;", "'")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip(" .…")


def auto_summary(story: dict, limit: int = 180) -> Optional[str]:
    """Excerpt sentences that restate the headline (title overlap + concrete facts), near-duplicates dropped."""
    title = story["lead"].get("title") or ""
    lang = story["lead"].get("lang")
    tg = news_digest.grams(title, lang)
    sents = []
    for a in story["members"]:
        for i, s in enumerate(SENTENCE_SPLIT.split(_clean(a.get("excerpt") or ""))):
            s = s.strip()
            if len(s) < 20:
                continue
            sim = news_digest.jaccard(tg, news_digest.grams(s, lang))
            if sim < 0.08:  # off-topic sentence from a mis-clustered member
                continue
            fact = bool(re.search(r"\d", s)) + bool(re.search(r"밝혔|개최|열린다|연다|선정|발표|고시|announced|opens|wins", s))
            sents.append((sim + 0.15 * fact - 0.01 * i, s))
    out, used = [], 0
    for _, s in sorted(sents, key=lambda x: -x[0]):
        g = news_digest.grams(s, lang)
        if any(news_digest.jaccard(g, news_digest.grams(o, lang)) > 0.35 for o in out):
            continue
        if out and used + len(s) > limit:
            continue
        out.append(s)
        used += len(s)
        if used >= limit * 0.55:
            break
    if not out:
        return None
    text = " ".join(x if x.endswith((".", "다", "。", "!", "?")) else x + "…" for x in out)
    return (text[:limit].rstrip() + "…") if len(text) > limit else text


CRITERIA_TEXT = {"public": "국가·공공 주체의 결정", "structure": "기관·제도·인사 변화", "scale": "금액·수량이 명시됨",
                 "first": "최초·신설", "award": "공식 선정·수상", "next": "다음 일정이 명시됨", "observed": "ARTREND 관찰 대상"}


READER_SO_WHAT = {
    "public": "공공 결정이라 현장에 그대로 적용된다 — 언제부터, 누구에게 적용되는지가 관건.",
    "structure": "사람·제도가 바뀌면 그 기관의 다음 전시와 소장 방향도 바뀐다.",
    "award": "수상 뒤 개인전·후원이 이어지는지가 진짜 신호다.",
    "first": "첫 사례라 선례가 된다 — 다른 도시·기관이 따라올지 주목.",
    "scale": "",
    "market": "가격은 시장의 온도일 뿐 작품의 가치가 아니다.",
    "criticism": "사건이 아니라 해석을 담은 글 — 같은 전시의 다른 리뷰와 함께 읽으면 관점이 보인다.",
    "exhibition": "지금 가 볼 수 있는 전시다.",
    "people": "이 이름이 다음 전시·수상으로 이어질지 주목.",
    None: "큰 사건은 아니지만 이번 주 흐름을 보여 주는 소식이다.",
}
HARD_ORDER = ["public", "award", "first", "structure", "scale"]
DECISION = re.compile(r"고시|지정|확정|결정|발표|시행|개정|의결|승인|선정|인증|도입|체결|위촉|임명|신설|폐지|announce|decid|approv|appoint|"
                      r"designat|décid|nomm|inscrit|classé|決定|指定", re.I)
FIRST_WORD = re.compile(r"최초|처음|첫\s|신설|first[- ]ever|for the first time|inaugural|初の", re.I)


def reader_so_what(story: dict, hard: set, topic: Optional[str]) -> str:
    """'So what' for a reader: the story's own hook first (first appearance, crowd, record), then its strongest criterion."""
    from . import buzz
    people = {nm: eid for nm, eid in story.get("names") or [] if eid}
    a = buzz.analyse(story, people, [])
    if a and (set(a["slots"]) & {"first", "heat", "record"}):
        k = "first" if "first" in a["slots"] else "heat" if "heat" in a["slots"] else "record"
        if k == "first":
            wide = a["stature"] or a["desc"] or a["slots"]["first"].split()[0] in buzz.WIDE_SCOPE
            return buzz.READ["first_known"] if wide else buzz.READ["first"]
        return buzz.READ[k]
    text = " ".join([m.get("title") or "" for m in [story["lead"]] + story["members"][:6]] + list(story.get("ko_titles") or []))
    for k in HARD_ORDER:
        if k in hard:
            if k == "public" and (topic == "exhibition" or not DECISION.search(text)):
                continue  # a national museum hosting something is not a public decision
            if k == "first" and not FIRST_WORD.search(text):
                return "기록 경신 — 숫자는 관심의 온도이지 작품의 가치가 아니다."
            return READER_SO_WHAT[k]
    return READER_SO_WHAT.get(topic, READER_SO_WHAT[None])


def auto_judgement(story: dict, day: dt.date) -> dict:
    """Rule-made summary / why / so-what for a story without an editor note (labelled '자동 판단' on the page)."""
    summary = auto_summary(story)
    titles = [_clean(m.get("title")) for m in [story["lead"]] + story["members"] if m.get("title")] + list(story.get("ko_titles") or [])
    crit = criteria_of(titles[:6] + ([summary] if summary else []), day + dt.timedelta(days=1),
                       len(story.get("outlets") or []), story.get("names") or [])
    if not DECISION.search(" ".join(titles + ([summary] if summary else []))):
        crit = [c for c in crit if c["id"] != "public"]  # a national museum hosting something is not a public decision
    pts = sum(WEIGHT[c["id"]] for c in crit)
    level = next(lab for lo, lab in AUTO_LEVEL if pts >= lo)
    keyword = lambda c: re.sub(r"^…|…$", "", c["evidence"])
    why = []
    for c in crit:
        if c["id"] in ("reach",):
            continue
        if c["id"] in CRITERIA and c["id"] != "observed" or c["id"] in ("public", "structure", "scale", "first", "award"):
            m = dict((cid, rx) for cid, _, rx in CRITERIA)[c["id"]].search(keyword(c))
            why.append(f"{CRITERIA_TEXT[c['id']]}('{m.group(0) if m else ''}')")
        elif c["id"] == "next":
            why.append(f"{CRITERIA_TEXT['next']}({c['evidence'].split(' ')[0]})")
        elif c["id"] == "observed":
            why.append(f"{CRITERIA_TEXT['observed']}({c['evidence']})")
    reach = next((c for c in crit if c["id"] == "reach"), None)
    hard = {c["id"] for c in crit} & {"public", "structure", "scale", "first", "award"}
    topic = story.get("topic")
    if topic not in TOPIC_SO_WHAT:
        topic = "policy" if hard & {"public", "structure"} else ("people" if "award" in hard else None)
    so = reader_so_what(story, hard, topic)
    nxt = next((c for c in crit if c["id"] == "next"), None)
    if nxt:
        d_ = nxt["evidence"].split(" ")[0]
        try:
            nd = dt.date.fromisoformat(d_)
            so += f" 다음 날짜: {nd.month}월 {nd.day}일."
        except ValueError:
            pass
    reason = " · ".join(why) if why else "공공 결정·제도 변화·규모·최초·수상 같은 객관적 사실은 없음"
    if reach:
        reason += f" · {reach['evidence'].split('(')[0]} 보도" + ("" if hard else "(보도량만으로는 주요 소식으로 보지 않음)")
    if not hard:
        level = "짧은 소식"
    return dict(summary=summary, why=[reason], so_what=so, level=level, points=pts, hard=sorted(hard))


def load_notes_upto(day: dt.date) -> dict:
    """Editor notes of every snapshot up to `day`, merged (later files win). 'glance' is kept only for `day` itself."""
    merged = {"major": {}, "daily": {}, "awards": {}}
    for p in sorted(EDITORIAL_DIR.glob("notes_*.json")):
        d = p.stem.split("_", 1)[1]
        if d > (day + dt.timedelta(days=7)).isoformat():
            continue
        n = json.loads(p.read_text(encoding="utf-8"))
        for k in merged:
            merged[k].update(n.get(k) or {})
        if d == day.isoformat():
            merged["glance"], merged["editor"] = n.get("glance") or {}, n.get("editor")
    return merged


def load_packets_upto(day: dt.date) -> List[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PACKET_DIR.glob("packets_*.json"))
            if p.stem.split("_", 1)[1] <= (day + dt.timedelta(days=7)).isoformat()]
