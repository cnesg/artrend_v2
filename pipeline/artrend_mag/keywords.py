"""HOT TRENDS: the handful of words that actually rose this week.

A keyword is shown only when it passes all of:
  1. it is a known art concept (medium, theme, format, institutional move), a named art event (biennale, fair,
     prize) or an artist the week's press and walls both carry — never a raw n-gram, so nothing meaningless
     ('개최', '오늘', a place name) can surface;
  2. support: at least MIN_DOCS distinct reports or shows this week, from at least MIN_SOURCES different outlets
     or venues (one press release echoed by its syndicates is one voice);
  3. rise: its share of this week's coverage beats its share of the previous four weeks by MIN_LIFT
     (a word that is always there — '개인전' — is not a trend).
Each keyword carries its evidence (count, rise, three example titles) so the reader can check it.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import re
from typing import Dict, List, Optional, Tuple

from .daily_trend import FEED_PREFIX

WEEK = 7
BASE_DAYS = 28
MIN_DOCS = 3
THIN_WEEK, MIN_DOCS_THIN = 150, 2   # editions with little collected press: two independent voices are already a signal
MIN_SOURCES = 2
MIN_LIFT = 1.4
MIN_LIFT_THIN = 2.0
MAX_CONCEPTS, MAX_EVENTS, MAX_PEOPLE, MAX_TOTAL = 5, 2, 2, 8

# label, kind, pattern (Korean / English / French-Italian-Spanish stems / Japanese)
CONCEPTS: List[Tuple[str, str, str]] = [
    # medium
    ("섬유·직조", "매체", r"섬유|텍스타일|직조|태피스트리|textile|tapestr|weaving|woven|tessil|テキスタイル|染織|織物"),
    ("도자·공예", "매체", r"도자|도예|공예|ceramic|pottery|porcelain|craft|céramique|ceramica|陶芸|陶磁|工芸"),
    ("사진", "매체", r"사진전|사진가|사진 작가|사진작가|사진 작업|photograph|fotograf|photo exhibition|写真"),
    ("회화", "매체", r"회화|페인팅|painting|peinture|pittura|pintura|絵画"),
    ("조각", "매체", r"조각|sculpt|scultur|彫刻"),
    ("설치", "매체", r"설치미술|설치 작업|설치작|대형 설치|installation|インスタレーション"),
    ("미디어아트", "매체", r"미디어\s?아트|미디어\s?파사드|media art|digital art|immersive|몰입형|メディアアート"),
    ("영상", "매체", r"영상 작업|영상 작품|비디오 아트|무빙 이미지|video art|video installation|moving image|film install|映像作品|映像インスタレーション"),
    ("AI", "매체", r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|생성형|artificial intelligence|生成AI"),
    ("퍼포먼스", "매체", r"퍼포먼스|performance art|live performance|パフォーマンス"),
    ("사운드", "매체", r"사운드 아트|사운드 설치|소리 작업|sound art|sound install|サウンドアート"),
    ("판화", "매체", r"판화|printmak|木版|版画"),
    ("드로잉", "매체", r"드로잉|drawings?\b|dessin|disegn|ドローイング"),
    ("수묵·한국화", "매체", r"수묵|한국화|동양화|ink painting|水墨|日本画"),
    ("단색화", "매체", r"단색화|dansaekhwa|monochrome painting"),
    ("추상", "매체", r"추상|abstract|abstrait|astratt|抽象"),
    ("건축", "매체", r"건축|architect|建築"),
    ("공공미술", "매체", r"공공미술|공공 미술|public art|パブリックアート"),
    # theme
    ("기후·생태", "주제", r"기후|생태|탄소|climate|ecolog|environmental|écolog|ecologi|気候|生態|環境"),
    ("여성 작가", "주제", r"여성 작가|여성 미술|여성작가|페미니|women artists?|female artists?|feminis|女性作家|女性アーティスト"),
    ("아카이브", "주제", r"아카이브|archive|archivio|archivo|アーカイブ"),
    ("탈식민·디아스포라", "주제", r"식민|디아스포라|colonial|diaspora|décolonial|植民|ディアスポラ"),
    ("이주·난민", "주제", r"이주민|이민자|난민|migrant|migration|refugee|移民|難民"),
    ("전쟁·분쟁", "주제", r"전쟁|분쟁|가자|우크라이나|(?<![a-z])war(?![a-z])|warfare|Gaza|Ukraine|戦争"),
    ("노동", "주제", r"노동|labou?r(?![a-z])|労働"),
    ("기억·역사", "주제", r"기억|역사 속|memory|memoria|mémoire|記憶"),
    ("신체", "주제", r"신체|the body|bodies|corps|身体"),
    ("장애·접근성", "주제", r"장애|배리어프리|접근성|disabilit|accessib|障害|バリアフリー"),
    ("퀴어", "주제", r"퀴어|queer|LGBT|クィア"),
    ("가족·돌봄", "주제", r"가족|돌봄|어머니|모성|family|mother|care work|家族"),
    # format and market
    ("회고전", "형식", r"회고전|retrospective|rétrospective|retrospettiva|回顧展"),
    ("소장품", "형식", r"소장품|신규 소장|컬렉션 전|acquisition|acquires|acquired|collection display|収蔵"),
    ("기증", "형식", r"기증|donat|bequest|寄贈"),
    ("경매", "형식", r"경매|낙찰|auction|enchères|asta|オークション|落札"),
    ("아트페어", "형식", r"아트페어|아트 페어|art fair|foire|fiera|アートフェア"),
    ("비엔날레", "형식", r"비엔날레|트리엔날레|biennale|biennial|triennale|triennial|bienal|ビエンナーレ|トリエンナーレ|芸術祭"),
    ("레지던시", "형식", r"레지던시|입주 작가|입주작가|residency|in residence|résidence d.artiste|レジデンス|レジデンシー"),
    ("신진", "형식", r"신진|청년 작가|청년작가|젊은 작가|emerging artist|young artist|jeunes? artiste|若手|新進"),
    ("전속 계약", "형식", r"전속|now represents|joins the gallery|representation of|新たに取り扱い"),
    ("신규 개관", "형식", r"(?<!재)개관(?!\s?\d+\s?주년)|new museum|opens? its doors|inaugurat|開館"),
    ("휴관·폐관", "형식", r"휴관|폐관|문 닫|closes? (?:its doors|permanently)|closure|閉館|休館"),
    ("기관장 인사", "형식", r"관장|임명|선임|appointed|named (?:director|curator)|new director|nommé|館長"),
    ("예산·지원", "형식", r"(?<![가-힣])예산|예산 삭감|지원금|arts? budget|funding cut|arts? funding|予算|助成"),
    ("공모", "형식", r"공모|open call|appel à candidatures|公募"),
    ("무료 관람", "형식", r"무료 관람|무료 개방|무료 입장|free admission|free entry|入場無料|観覧無料"),
]
CONCEPT_RE = [(label, kind, re.compile(p, re.I)) for label, kind, p in CONCEPTS]

# '사진=연합뉴스', '(사진 제공)', 'Photo: …' are bylines, not photography
NOISE = re.compile(r"[\[(（]?\s*(?:사진|영상|그래픽|자료)\s*[=:]\s*[^\])）]*[\])）]?|(?:사진|영상)\s*제공|photo(?:graph)?\s*(?:by|:|courtesy)[^.]*|courtesy of[^.]*", re.I)

# named art events: '광주비엔날레', '이인성미술상', 'Mori Art Award', 'Frieze London'
EVENT = re.compile(
    r"((?:[가-힣]{1,12}(?<![는은한된던을를의에와과로며고서])\s)?[가-힣]{0,10}(?:비엔날레|트리엔날레|아트페어|미술상|작가상|사진상|조각상))"
    r"|((?:[A-Z][\w'&.-]*\s){1,4}(?:Biennale|Biennial|Triennale|Triennial|Art Fair|Prize|Award))"
    r"|((?:Frieze|Art Basel|Kiaf|KIAF|TEFAF|Art Collaboration Kyoto|Tokyo Gendai|Art Week Tokyo|Artissima|Paris\+|Art Düsseldorf)(?:\s(?:London|Seoul|Paris|Miami Beach|Hong Kong|New York|Los Angeles|Masters))?)"
)
EVENT_JUNK = re.compile(r"^(?:올해의|이번|제|국제|세계|대한민국|한국|국립|시립|도립|the|this|a|an)\s?(?:비엔날레|미술상|작가상|아트페어|Prize|Award|Biennale)?$", re.I)


def _norm_event(raw: str) -> Optional[str]:
    t = re.sub(r"^(?:제\s?\d+\s?회|\d{4}|第\d+回)\s*", "", raw.strip())
    t = re.sub(r"\s{2,}", " ", t).strip(" '\"‘’“”")
    if len(t) < 4 or EVENT_JUNK.match(t):
        return None
    return t


# a story counts only when it is about art: '파크골프대회 개인전 우승' and '다문화가족센터 나들이' are not
ART_CONTEXT = re.compile(r"전시|展|미술|화가|조각가|갤러리|화랑|비엔날레|트리엔날레|아트페어|경매|회고전|작가|큐레이터|"
                         r"museum|gallery|galerie|exhibition|artist|curator|biennal|biennial|auction|art fair|"
                         r"美術|展覧|個展|画家|アート|ギャラリー", re.I)
NOT_ART = re.compile(r"\[[^\]]{0,8}소식\]|대회|우승|선수|골프|축구|야구|배구|농구|체전|게임즈|e스포츠|올림픽|tournament|championship", re.I)


class Doc:
    __slots__ = ("text", "source", "day", "title", "url", "kind")

    def __init__(self, text, source, day, title, url, kind):
        self.text, self.source, self.day, self.title, self.url, self.kind = text, source, day, title, url, kind


def _day(v) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def _clusters(vb, edition: str, d: dt.date) -> List[dict]:
    """Story clusters over the whole span any page of this export can look at, built once per edition:
    one press release and its syndicated copies are one voice, not ten."""
    cache = vb.__dict__.setdefault("_kw_clusters", {})
    if edition not in cache:
        hi = max(d, getattr(vb, "asof", d))
        lo = hi - dt.timedelta(days=WEEK + BASE_DAYS + 7)
        cache[edition] = vb.stories(edition, lo, hi, hi)
    return cache[edition]


def corpus(vb, edition: str, d: dt.date) -> List[Doc]:
    """This week's and the four previous weeks' stories and shows for one edition. Concepts are read from
    headlines (titles and their Korean translation), not excerpts: what a story is about, not what it mentions."""
    lo = d - dt.timedelta(days=WEEK + BASE_DAYS - 1)
    ko_of = getattr(vb, "ko_of", None)
    docs = []
    for st in _clusters(vb, edition, d):
        a = st["lead"]
        day = _day(a["published_at"])
        if not day or not lo <= day <= d:
            continue
        titles = []
        for m in [a] + [m for m in st["members"] if m is not a][:4]:
            titles.append(m["title"] or "")
            if ko_of:
                titles.append(ko_of("articles", m["article_id"], "title", m["title"]) or "")
        ko = ko_of("articles", a["article_id"], "title", a["title"]) if ko_of else None
        text = NOISE.sub(" ", " ".join(t for t in titles if t))
        if NOT_ART.search(text) or not (vb.is_specialist(a) or ART_CONTEXT.search(text)):
            continue
        docs.append(Doc(text, frozenset(st["outlets"]) or frozenset([vb.source_label(a, bare=True)]), day,
                        ko or a["title"], a["canonical_url"], "article"))
    for ev in vb.events.values():
        if ev["edition_region"] != edition:
            continue
        s = _day(ev.get("start_date") or ev.get("announced_date"))
        if not s or not lo <= s <= d:
            continue
        ko = ko_of("events", ev["event_id"], "title", ev["title"]) if ko_of else None
        text = NOISE.sub(" ", " ".join(x for x in (ev["title"], ko) if x))
        org = ev.get("venue_id") or ev.get("organizer_entity_id") or ev.get("source_id") or ""
        docs.append(Doc(text, frozenset([org]), s, ko or ev["title"], ev.get("url"), "show"))
    return docs


def _rise(n_w: int, n_b: int, N_w: int, N_b: int) -> float:
    """Share this week over (smoothed) share in the baseline weeks."""
    return (n_w / max(N_w, 1)) / ((n_b + 1) / (N_b + 1))


def _evidence(label: str, kind: str, hits: List[Doc], n_b: int, N_w: int, N_b: int, base_ok: bool) -> Optional[dict]:
    srcs = set().union(*[h.source for h in hits]) if hits else set()
    if len(hits) < (MIN_DOCS if N_w >= THIN_WEEK else MIN_DOCS_THIN) or len(srcs) < MIN_SOURCES:
        return None
    lift = _rise(len(hits), n_b, N_w, N_b) if base_ok else None
    if base_ok and lift < (MIN_LIFT if N_w >= THIN_WEEK else MIN_LIFT_THIN):
        return None
    hits = sorted(hits, key=lambda h: (h.day or dt.date.min, h.kind == "article"), reverse=True)
    ex, seen = [], set()
    for h in hits:
        if h.title and h.title not in seen:
            seen.add(h.title)
            ex.append(dict(title=FEED_PREFIX.sub("", h.title), url=h.url, date=h.day.isoformat() if h.day else None))
        if len(ex) >= 3:
            break
    new = base_ok and n_b == 0
    rise = "새로 등장" if new else (f"평소의 {lift:.1f}배" if lift else "이번 주 집중")
    score = (math.log(min(lift, 8.0)) if lift else 0.4) * math.log(1 + len(hits)) * (1 + 0.1 * min(len(srcs), 6))
    return dict(label=label, kind=kind, n=len(hits), sources=len(srcs), rise=rise, lift=round(lift, 2) if lift else None,
                score=round(score, 3), note=f"이번 주 {len(hits)}건 · {rise}", examples=ex)


def hot(vb, edition: str, d: dt.date, people: Optional[List[dict]] = None) -> List[dict]:
    docs = corpus(vb, edition, d)
    w_lo = d - dt.timedelta(days=WEEK - 1)
    week = [x for x in docs if x.day and x.day >= w_lo]
    base = [x for x in docs if x.day and x.day < w_lo]
    N_w, N_b = len(week), len(base)
    base_ok = N_b >= 4 * max(30, N_w // 4)  # a real baseline: the earlier weeks were actually collected
    concepts, events = [], []
    for label, kind, rx in CONCEPT_RE:
        hits = [x for x in week if rx.search(x.text)]
        n_b = sum(1 for x in base if rx.search(x.text))
        e = _evidence(label, kind, hits, n_b, N_w, N_b, base_ok)
        if e:
            concepts.append(e)
    ev_week: Dict[str, List[Doc]] = collections.defaultdict(list)
    ev_base: Dict[str, int] = collections.Counter()
    for bucket, x in [("w", x) for x in week] + [("b", x) for x in base]:
        names = {n for m in EVENT.finditer(x.text) if (n := _norm_event(next(g for g in m.groups() if g)))}
        for n in names:
            if bucket == "w":
                ev_week[n].append(x)
            else:
                ev_base[n] += 1
    for n, hits in ev_week.items():
        e = _evidence(n, "행사", hits, ev_base[n], N_w, N_b, base_ok)
        if e:
            events.append(e)
    # one event under two spellings ('광주비엔날레' / '광주 비엔날레'): keep the better-supported one
    events.sort(key=lambda e: -e["score"])
    uniq = []
    for e in events:
        k = re.sub(r"\s", "", e["label"]).lower()
        if all(k not in re.sub(r"\s", "", u["label"]).lower() and re.sub(r"\s", "", u["label"]).lower() not in k for u in uniq):
            uniq.append(e)
    names = []
    for p in people or []:
        nm = p.get("name") or ""
        latin_ok = re.fullmatch(r"[A-Za-zÀ-ÿ'.-]+(?:\s[A-Za-zÀ-ÿ'.&-]+)+", nm)
        hangul_ok = re.fullmatch(r"[가-힣]{3,4}", nm)
        if not (latin_ok or hangul_ok):
            continue  # one-word or two-syllable names are too easily ordinary words
        if (p.get("press") or 0) >= 2 or ((p.get("press") or 0) >= 1 and (p.get("shows") or 0) >= 1):
            names.append(dict(label=nm, kind="작가", n=(p.get("press") or 0) + (p.get("shows") or 0), sources=None, rise="이번 주 화제",
                              lift=None, score=0, note=f"보도 {p.get('press') or 0} · 전시 {p.get('shows') or 0}",
                              examples=[dict(title=FEED_PREFIX.sub("", p["story"]), url=p.get("story_url"), date=None)] if p.get("story") else []))
    concepts.sort(key=lambda e: -e["score"])
    out = concepts[:MAX_CONCEPTS] + uniq[:MAX_EVENTS] + names[:MAX_PEOPLE]
    out.sort(key=lambda e: (e["kind"] == "작가", -e["score"]))
    return out[:MAX_TOTAL]


def tags_for(text: str, keywords: List[dict], limit: int = 3) -> List[str]:
    """The week's keywords a headline is about (for the hero's #tags)."""
    out = []
    for k in keywords:
        rx = next((r for lab, _, r in CONCEPT_RE if lab == k["label"]), None)
        hit = rx.search(text) if rx else k["label"].lower() in text.lower()
        if hit:
            out.append(k["label"])
        if len(out) >= limit:
            break
    return out
