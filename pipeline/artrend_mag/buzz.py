"""Why a story is trending, read from the press: who (and how the press describes them), where, and the hook —
a first appearance, an audience rush, a record price, a prize. Hooks are parsed into slots (scope, count, amount,
prize name) and rebuilt into an ARTREND headline with a one-line reading, so no outlet headline is copied.
Rule-made; crowds and prices are interest and market temperature, never artistic value.
"""
from __future__ import annotations

import collections
import math
import re
from typing import Callable, Dict, List, Optional

ART = re.compile(r"전시|展|미술|작가|갤러리|화랑|비엔날레|아트페어|경매|작품|개인전|회고전|museum|gallery|exhibition|artist|"
                 r"biennal|auction|美術|展覧|個展|画家", re.I)
SCOPE_EN = {"korea": "국내", "asia": "아시아", "japan": "일본", "the us": "미국", "the u.s.": "미국", "america": "미국",
            "europe": "유럽", "the uk": "영국", "britain": "영국", "france": "프랑스", "germany": "독일"}
ABROAD = {"상하이", "베이징", "홍콩", "타이베이", "싱가포르", "뉴욕", "파리", "런던", "베를린", "도쿄", "LA", "해외", "미국", "유럽", "일본"}
FIRST_KO = re.compile(r"(국내|한국|아시아|서울|부산|대구|광주|일본|미국|유럽|해외|상하이|베이징|홍콩|타이베이|싱가포르|뉴욕|파리|런던|베를린|도쿄|LA)?\s?(?:에서\s?)?(?:첫|최초의?)\s?(미술관\s|대규모\s|단독\s)?"
                      r"(개인전|회고전|내한|소장품전|전시)")
FIRST_EN = re.compile(r"first (major |large-scale )?(museum )?(solo )?(exhibition|show|retrospective|survey)"
                      r"(?: in (Korea|Asia|Japan|the U\.?S\.?|America|Europe|the UK|Britain|France|Germany))?", re.I)
FIRST_JA = re.compile(r"(日本初|初個展|初来日|初の大規模(?:個展|回顧展))")
CROWD = re.compile(r"([\d.]+\s?만\s?[\d,]*)\s?명")
TICKETS = re.compile(r"(?:입장권|티켓)\s?([\d.]+\s?만\s?[\d,]*)|([\d.]+\s?만\s?[\d,]*)\s?(?:장|티켓)")
NAME_KO = [re.compile(r"([가-힣]{1,5}(?:\s[가-힣]{1,5}){0,2})['’\"”]?\s(?:국내|아시아|한국|일본|국내외)?\s?첫\s?(?:개인전|회고전|내한|미술관\s?개인전|대규모\s?(?:개인전|회고전|전시)|미술관\s?전시)"),
           re.compile(r"['‘\"“]([가-힣]{1,5}(?:\s[가-힣]{1,5}){0,2})['’\"”]\s?(?:국내|아시아|한국)?\s?(?:첫\s)?(?:개인전|회고전|展|특별전)"),
           re.compile(r"(?:^|[\s'‘\"“,…·(])([가-힣]{2,4})\s?(?:작가|화백|화가|조각가|사진작가|개인전|회고전|展|특별전|초대전)"),
           re.compile(r"(?:작가|화백|화가)\s([가-힣]{2,4})(?=$|[\s,'’…·의은는이가])"),
           re.compile(r"(?:에|로)\s([가-힣]{2,4})(?:\s작가)?\s?$")]
NAME_LATIN = re.compile(r"\b([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+){1,2}|[A-Z]{2,}\s[A-Z]{2,})\b")
NAME_KANA = re.compile(r"([ァ-ヴー]{2,}・[ァ-ヴー]{2,})")
NOT_NAME = {"국내", "신진", "청년", "기획", "소장품", "특별", "미술", "현대", "대규모", "단독", "초대", "기념", "연말", "사진", "올해", "작품",
            "첫", "최초", "아시아", "한국", "세계", "원로", "중견", "여성", "지역", "작가", "미술관", "갤러리", "회고", "대표", "국립", "시립",
            "개관", "기획전", "특별전", "단체", "작고", "미디어", "인공지능", "디지털", "유망", "전업", "젊은", "공모", "수상", "선정",
            "프랑스", "미국", "영국", "독일", "일본", "중국", "이탈리아", "스페인", "베를린", "파리", "뉴욕", "런던", "도쿄", "청년 화가", "개최"}
ROLE = re.compile(r"^(?:\S*작가|\S*화가|\S*미술가|\S*아티스트|청년|원로|중견|美|佛|英|獨|베를린|파리|뉴욕|런던|도쿄|프랑스|미국|영국|독일|일본)$")
NOT_LATIN = re.compile(r"Featured|October|November|September|December|Museum|Gallery|Art |Arts|Biennale|Fair|Exhibition|Foundation|The ", re.I)
SOLD = re.compile(r"매진(?!\s?\()|완판|sold.?out|完売", re.I)
OPENRUN = re.compile(r"오픈런|장사진|인산인해|긴\s?줄|long queues?|行列", re.I)
MOST = re.compile(r"역대\s?최다|record (attendance|crowds?|visitors)", re.I)
RECORD = re.compile(r"(?:(프랑스|국내|한국|아시아|세계|작가|생존 작가)\s?(?:미술품\s?)?(?:경매\s?)?)?최고가|record (price|sale)|最高額", re.I)
AMOUNT = re.compile(r"([\d,.]+\s?억\s?(?:원)?|[\d,.]+\s?만\s?(?:달러|유로|파운드)|\$[\d.,]+\s?(?:million|m)\b)", re.I)
PRIZE = re.compile(r"['‘\"“《「]([^'’\"”》」]{2,20}(?:상|어워드|Award|Prize|작가))['’\"”》」]\s?(?:최종\s?)?(?:수상|수상자|에|대상)")
AWARD_SHOW_TITLE = re.compile(r"수상(?:자|작가)?\s?(?:전|기념전|작품전)|Prize Exhibition|Award Exhibition|受賞(?:記念)?展", re.I)
AWARD_WORD = re.compile(r"최종\s?수상|수상자|대상\s?수상|wins?\b|winner|awarded|受賞|大賞", re.I)
STATURE = re.compile(r"세계적|거장|원로|전설|대가|선구자|대모|대부|슈퍼스타|아이콘|world.?renowned|legendary|pioneer|巨匠|世界的", re.I)
DESC_TOKEN = re.compile(
    r"^(세계적인?|글로벌|원로|거장|전설|대가|선구자|슈퍼스타|현대미술가|미술가|화가|사진작가|사진가|조각가|"
    r"\S*아티스트|\S*미술가|\S*화가|美|佛|英|獨|日|中|伊|미국|프랑스|영국|독일|일본|중국|이탈리아|스페인|덴마크|"
    r"아이슬란드|브라질|멕시코|노르웨이|스위스|벨기에|네덜란드|대만|태국|인도)$")
EPITHET = re.compile(r"((?:[가-힣A-Za-z]+\s)?[가-힣A-Za-z]+의\s(?:선구자|거장|대가|아이콘|전설|대모|대부))\s?['‘\"“]?$")
SHOW_AFTER = re.compile(r"^\s?['’\"”]?\s?(회고전|개인전|특별전|기획전|展)")
VENUE_KO = re.compile(r"((?:[가-힣A-Za-z0-9]{2,}\s)?[가-힣A-Za-z0-9]{2,}(?:미술관|박물관|아트센터|뮤지엄|갤러리))(?=\s|$|[,…'’에서의은는이가])")
QUOTED = re.compile(r"['‘\"“《「〈]([^'’\"”》」〉]{2,24})['’\"”》」〉]")
PLACE = {
    "KR": re.compile(r"(?<![가-힣])서울|(?<![가-힣])부산|(?<![가-힣])대구|(?<![가-힣])광주|(?<![가-힣])인천|(?<![가-힣])대전|(?<![가-힣])울산|(?<![가-힣])제주|(?<![가-힣])경기|(?<![가-힣])수원|(?<![가-힣])강릉|(?<![가-힣])양주|(?<![가-힣])국내|(?<![가-힣])한국|국립현대|리움|간송|아시아 첫|내한|Seoul|Korea"),
    "JP": re.compile(r"(?<![가-힣])도쿄|(?<![가-힣])교토|(?<![가-힣])오사카|가나자와|나오시마|(?<![가-힣])일본|日本|東京|京都|Tokyo|Kyoto|Japan"),
    "AMERICAS": re.compile(r"(?<![가-힣])뉴욕|샌프란시스코|로스앤젤레스|시카고|마이애미|(?<![가-힣])미국|美\s|(?<![가-힣])멕시코|상파울루|(?<![가-힣])브라질|(?<![가-힣])캐나다|토론토|MoMA|SFMOMA|"
                           r"New York|San Francisco|Los Angeles|Chicago"),
    "EUROPE": re.compile(r"(?<![가-힣])파리|(?<![가-힣])런던|(?<![가-힣])베를린|베네치아|베니스|밀라노|(?<![가-힣])프랑스|(?<![가-힣])영국|(?<![가-힣])독일|(?<![가-힣])이탈리아|(?<![가-힣])스페인|(?<![가-힣])네덜란드|(?<![가-힣])스위스|바젤|(?<![가-힣])유럽|佛|英|獨|"
                         r"Paris|London|Berlin|Venice|Milan"),
}
WIDE_SCOPE = {"국내", "한국", "아시아", "일본", "미국", "유럽", "영국", "프랑스", "독일"} | ABROAD
HOOK_WEIGHT = {"first": 3, "heat": 3, "record": 3, "award": 2}


def clean(title: Optional[str]) -> str:
    t = re.sub(r"^\s*(\[[^\]]{1,12}\]|【[^】]{1,12}】)\s*", "", title or "")
    t = re.sub(r"(\.\.\.|…)\s*$", "", re.sub(r"\s+", " ", t)).strip()
    return t


def unquote(s: str) -> str:
    return re.sub(r"['‘’\"“”《》「」〈〉]", "", s).strip()


def route(texts: List[str]) -> Optional[str]:
    """Edition by where it happens: foreign place words win only when no Korean place outnumbers them."""
    hits = collections.Counter()
    for t in texts:
        for e, rx in PLACE.items():
            if rx.search(t or ""):
                hits[e] += 1
    if not hits:
        return None
    foreign = [(n, e) for e, n in hits.items() if e != "KR"]
    if foreign and max(foreign)[0] > hits["KR"]:
        return max(foreign)[1]
    return "KR" if hits["KR"] else None


def _most(values) -> str:
    c = collections.Counter(v for v in values if v)
    return c.most_common(1)[0][0] if c else ""


def first_slot(t: str) -> str:
    m = FIRST_KO.search(t)
    if m:
        scope, mod, kind = m.group(1) or "", (m.group(2) or "").strip(), m.group(3)
        kind = "내한전" if kind == "내한" else kind
        return " ".join(x for x in (scope, "첫", mod, kind) if x)
    m = FIRST_EN.search(t)
    if m:
        scope = SCOPE_EN.get((m.group(5) or "").lower().replace(".", "").replace("the us", "the us"), "")
        kind = "회고전" if m.group(4).lower() in ("retrospective", "survey") else ("개인전" if m.group(3) or m.group(2) else "전시")
        return " ".join(x for x in (scope, "첫", "미술관" if m.group(2) else "", kind) if x)
    m = FIRST_JA.search(t)
    if m:
        return {"日本初": "일본 첫 전시", "初個展": "첫 개인전", "初来日": "첫 일본 전시"}.get(m.group(1), "일본 첫 대규모 개인전")
    return ""


def heat_slot(titles: List[str]) -> str:
    crowd = _most(re.sub(r"\s", "", m.group(1)).rstrip(",") for t in titles for m in CROWD.finditer(t))
    tickets = _most(re.sub(r"\s", "", m.group(1) or m.group(2)) for t in titles for m in TICKETS.finditer(t))
    most = any(MOST.search(t) for t in titles)
    fmt = lambda n: re.sub(r"만(?=\d)", "만 ", n)
    unit = lambda n: f"{fmt(n)} 명" if n.endswith("만") else f"{fmt(n)}명"
    if crowd:
        s = f"{unit(crowd)}이 찾았다"
    elif tickets:
        s = f"입장권 {fmt(tickets)}장이 팔렸다"
    elif any(SOLD.search(t) for t in titles):
        s = "표가 동났다" if any(re.search(r"입장권|이용권|티켓|관람권|예매", t) for t in titles) else "작품이 모두 팔렸다"
    elif any(OPENRUN.search(t) for t in titles):
        s = "오픈런이 이어졌다"
    else:
        return ""
    return s + (" — 역대 최다" if most else "")


def record_slot(titles: List[str]) -> str:
    if not any(RECORD.search(t) for t in titles):
        return ""
    amount = _most(re.sub(r"\s", "", m.group(1)) for t in titles if RECORD.search(t) for m in AMOUNT.finditer(t))
    scope = _most((m.group(1) or "") for t in titles for m in RECORD.finditer(t))
    tail = f"{scope} 경매 최고가" if scope else "경매 최고가"
    return f"{amount}에 낙찰, {tail}" if amount else f"{tail} 기록"


def award_slot(titles: List[str]) -> str:
    prize = _most(m.group(1) for t in titles for m in PRIZE.finditer(t))
    if prize:
        return f"‘{prize}’ 품었다"
    # '…상 수상자전' is an exhibition of an earlier award, not a new win
    wins = [t for t in titles if AWARD_WORD.search(t) and not AWARD_SHOW_TITLE.search(t)]
    return "수상" if wins else ""


def descriptor(titles: List[str], name: str) -> str:
    """How the press describes `name` right before it: an epithet ('미디어 아트의 선구자') or descriptor tokens ('美 원로 화가')."""
    out = []
    for t in titles:
        t = clean(t)
        i = t.find(name)
        if i <= 0:
            continue
        before = t[:i]
        m = EPITHET.search(before)
        if m:
            out.append(m.group(1))
            continue
        toks, kept = unquote(before).split(), []
        for tok in reversed(toks[-3:]):
            if DESC_TOKEN.match(tok.rstrip(",")):
                kept.insert(0, tok.rstrip(","))
            else:
                break
        if kept and not all(re.fullmatch(r"작가|화가|미술가|아티스트", k) for k in kept):
            out.append(" ".join(kept))
    return _most(out)


def name_candidates(titles: List[str]) -> List[str]:
    """Person-like names the headlines themselves mark (Korean name + 작가/개인전, Latin full names, katakana names)."""
    out = []
    for t in titles:
        for rx in NAME_KO:
            for m in rx.finditer(t):
                toks = m.group(1).split()
                while len(toks) > 1 and toks[-1] in ("국내", "아시아", "한국", "일본", "국내외"):
                    toks = toks[:-1]
                while len(toks) > 1 and ROLE.match(toks[0]):  # '베를린 청년 화가 에밀 우르바넥' -> '에밀 우르바넥'
                    toks = toks[1:]
                nm = " ".join(toks)
                if nm not in NOT_NAME and not ROLE.match(nm):
                    out.append(nm)
        quoted = " ".join(m.group(1) for m in QUOTED.finditer(t))
        out += [m.group(1) for m in NAME_LATIN.finditer(t) if not NOT_LATIN.search(m.group(1)) and m.group(1) not in quoted]
        out += [m.group(1) for m in NAME_KANA.finditer(t)]
    return out


def hook_pos(t: str) -> int:
    for rx in (FIRST_KO, FIRST_EN, FIRST_JA, CROWD, TICKETS, SOLD, OPENRUN, RECORD, PRIZE, AWARD_WORD):
        m = rx.search(t)
        if m:
            return m.start()
    return -1


def analyse(story: dict, people: Dict[str, str], venues: List[str]) -> Optional[dict]:
    titles = [clean(m.get("title")) for m in story["members"]][:30]
    if not ART.search(" ".join(QUOTED.sub(" ", t) for t in titles)):
        return None
    slots = {}
    first = _most(first_slot(t) for t in titles)
    if first:
        slots["first"] = first
    if (h := heat_slot(titles)):
        slots["heat"] = h
    if (r := record_slot(titles)):
        slots["record"] = r
    if (a := award_slot(titles)):
        slots["award"] = a
    if not slots:
        return None
    cands = set(people) | {c for c in name_candidates(titles) if not c.endswith("의")}
    near = []
    for t in titles:  # the name closest before the hook in the same headline
        p = hook_pos(t)
        found = [(t.find(c), c) for c in cands if c in t]
        before = [x for x in found if 0 <= x[0] <= max(p, 0) + 40]
        if any(c in people for _, c in before):  # a matched person entity beats a headline-shaped guess
            before = [x for x in before if x[1] in people]
        if before:
            near.append(max(before)[1] if p >= 0 and any(i <= p for i, _ in before) else min(before)[1])
    name = _most(near) or _most(nm for t in titles for nm in cands if nm in t)
    eid = people.get(name)
    if name and not eid:
        longer = [unquote(m.group(1)) for t in titles for m in QUOTED.finditer(t) if name in m.group(1) and len(m.group(1)) > len(name)
                  and len(m.group(1).split()) <= 3]
        if longer:
            name = _most(longer)
    show = ""
    if name:
        show = _most(m.group(1) for t in titles for i in [t.find(name)] if i >= 0 for m in [SHOW_AFTER.search(t[i + len(name):])] if m)
        subject = f"{name} {show}".replace(" 展", "展") if show else name
    else:
        q = _most(unquote(m.group(1)) for t in titles for m in QUOTED.finditer(t))
        if not q:
            return None
        name = subject = q
        show = _most(m.group(1) for t in titles for i in [t.find(q)] if i >= 0 for m in [SHOW_AFTER.search(t[i + len(q):])] if m)
        if show:
            subject = f"‘{q}’ {show}"
        else:
            subject = f"‘{q}’"
    venue = (_most(v for t in titles for v in venues if len(v) >= 3 and v in t and v != name)
             or _most(m.group(1) for t in titles for m in VENUE_KO.finditer(t) if m.group(1) not in name))
    person = bool(eid) or (name in cands and not name.startswith("‘"))
    desc = descriptor(titles, name) if person else ""
    if "first" in slots and not person and slots["first"].split()[0] == "첫":
        del slots["first"]  # a venue's 'first show' is not a first appearance
    if not person:
        slots.pop("award", None)  # a prize without a named winner is not a person trending
    if not slots:
        return None
    stature = bool(desc and STATURE.search(desc)) or any(STATURE.search(t) and name in t for t in titles)
    return dict(slots=slots, name=name, subject=subject, eid=eid, desc=desc, venue=venue, stature=stature, titles=titles, person=person)


READ = {
    "first_known": "해외에서 이름난 작가를 이곳 관객이 처음 직접 만난다.",
    "abroad": "국내보다 해외 기관이 먼저 알아봤다.",
    "first": "작가 경력의 첫 장면 — 다음 무대로 이어질지 주목.",
    "heat": "관객이 먼저 움직였다. 숫자는 작품값이 아니라 관심의 온도다.",
    "record": "시장의 온도를 보여주는 기록 — 같은 작가 작품값이 따라 오를지 주목.",
    "award": "수상 뒤 전시·후원이 이어지는지가 진짜 신호다.",
}


def compose(a: dict, outlets: int, period: str = "", note: str = "") -> dict:
    s, who = a["slots"], (f"{a['desc']} {a['name']}" if a["desc"] else a["name"])
    at = f"{a['venue']}에서 " if a["venue"] else ""
    if "first" in s:
        title = f"{who}, {at}{s['first']}" + (f" — {s['heat']}" if "heat" in s else "")
        read = READ["abroad"] if s["first"].split()[0] in ABROAD and re.search(r"[가-힣]", a["name"]) else READ["first_known"] if (a["stature"] or a["desc"] or s["first"].split()[0] in WIDE_SCOPE) else READ["first"]
        lead = ""
    elif "heat" in s:
        subj = a["subject"] if a["subject"] != a["name"] or not a.get("person") else f"{a['name']} 전시"
        place = f"{a['venue']}에서 " if a["venue"] and a["venue"] not in subj else ""
        title = f"{subj}, {place}{s['heat']}"
        read, lead = READ["heat"], ""
    elif "record" in s:
        title = f"{a['subject']}, {s['record']}"
        read, lead = READ["record"], ""
    else:
        title = f"{who}, {a['venue'] + ' ' if a['venue'] and a['venue'] not in s['award'] else ''}{s['award']}"
        read, lead = READ["award"], ""
    dek = note or read
    points = ([read] if note and read not in note else []) + ([period] if period else [])
    return dict(title=title.replace("  ", " "), dek=dek, points=points)


def rank(stories: List[dict], person_of: Callable[[str], bool], venues: List[str], recent_iso: str, limit: int = 3) -> List[dict]:
    """Stories with a hook, merged per subject across story clusters (outlets united, hooks combined), strongest first.
    A subject seen by a single outlet needs a crowd/record hook, or a scoped first ('국내 첫') / a described name."""
    merged: Dict[str, dict] = {}
    for st in stories:
        people = {nm: eid for nm, eid in st.get("names") or [] if eid and person_of(eid) and len(nm) >= 2}
        a = analyse(st, people, venues)
        if not a:
            continue
        key = a["eid"] or a["name"]
        m = merged.get(key)
        if not m:
            merged[key] = dict(a=a, story=st, outlet_set=set(st.get("outlets") or []), best=len(st.get("outlets") or []))
            continue
        m["outlet_set"] |= set(st.get("outlets") or [])
        for k, v in a["slots"].items():
            m["a"]["slots"].setdefault(k, v)
        for f in ("desc", "venue"):
            m["a"][f] = m["a"][f] or a[f]
        m["a"]["stature"] = m["a"]["stature"] or a["stature"]
        m["a"]["titles"] += a["titles"]
        if len(st.get("outlets") or []) > m["best"]:
            m["story"], m["best"] = st, len(st.get("outlets") or [])
    for m in merged.values():  # every story naming the subject counts toward how widely it is talked about
        nm = m["a"]["name"]
        for st in stories:
            if any(nm in (x.get("title") or "") for x in st["members"]):
                m["outlet_set"] |= set(st.get("outlets") or [])
    out = []
    for m in merged.values():
        a, n_out = m["a"], len(m["outlet_set"])
        strong = {"heat", "record"} & set(a["slots"]) or ("first" in a["slots"] and (a["stature"] or a["desc"] or a["slots"]["first"].split()[0] in WIDE_SCOPE))
        if n_out < 2 and not strong:
            continue
        score = sum(HOOK_WEIGHT[k] for k in a["slots"]) + 2 * a["stature"] + 2 * math.log2(1 + n_out)
        score += 1 if (m["story"]["lead"].get("published_at") or "")[:10] >= recent_iso else 0
        out.append(dict(a=a, story=m["story"], outlets=n_out, score=score))
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
