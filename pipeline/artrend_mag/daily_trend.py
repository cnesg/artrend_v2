"""Daily trend across every collected axis, not only press articles.

Axes follow the Blueprint letters: E exhibitions/programs, G galleries, I institutions, A artists, C criticism,
R awards·open calls·residencies, M market (fairs and policy), N press. Each observation is a measured fact
(count, comparison with the previous four weeks, named items) plus a rule-made reading, and every number states
its window. Unobserved means 'not collected', never zero activity. Not used for cards, signals or `publishable`.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, List, Optional

GALLERY, MUSEUM = "gallery", "museum"
KIND_OF = {"gallery": GALLERY, "museum": MUSEUM, "institution": MUSEUM, "foundation": MUSEUM, "biennial": "biennial",
           "fair": "fair", "residency": "residency", "award": "award"}
MIN_BASE = 4.0  # weekly mean below this is too thin to call a change
SEASON_SHARE = 0.4  # one organizer opening this share of the week is the story, not the city
ROOKIE_TYPES = {"award", "open_call_selection", "residency"}
SHOW_TYPES = {"exhibition", "program", "biennial_edition", "fair_edition"}
EDITION_HINT = {
    "KR": re.compile(r"Seoul|Korea|Busan|서울|한국|Hankyoreh|Gwangju", re.I),
    "JP": re.compile(r"Tokyo|Kyoto|Osaka|Japan|東京|京都|日本", re.I),
    "AMERICAS": re.compile(r"New York|Los Angeles|Miami|Chicago|São Paulo|Mexico|Toronto|\bUSA?\b", re.I),
    "EUROPE": re.compile(r"London|Paris|Berlin|Salzburg|Milan|Venice|Vienna|Madrid|Basel|Brussels|Amsterdam", re.I),
}


AWARD_SHOW = re.compile(r"award|prize|prix|preis|賞|수상|신진|新人|emerging|young artists?|first solo|첫 개인전|debut", re.I)

# Theme lexicon: (key, label, headline claim, why it matters, keywords). Keyword hits are a rule-made reading, never a verdict.
THEMES = [
    ("colonial", "식민과 원주민의 기억", "식민의 기억을 다시 쓰는 전시가 잇따른다",
     "변방의 역사를 기관이 직접 꺼내 드는 흐름은 소장·연구 방향이 바뀌고 있다는 신호다.",
     ["colonial", "colonia", "colônia", "indigenous", "indígena", "decolonial", "maya", "식민", "원주민", "植民", "先住民"]),
    ("body", "몸", "몸이 다시 미술의 질문이 됐다",
     "몸을 다루는 전시가 겹치는 시기는 돌봄·노동·정체성 같은 사회적 질문이 미술로 넘어올 때가 많다.",
     ["body", "bodies", "corps", "körper", "flesh", "몸", "신체", "身体"]),
    ("ecology", "기후와 자연", "기후와 자연이 이번 주 전시의 화두다",
     "생태를 다루는 전시가 동시에 늘면 전시장의 주제 선택이 사회적 의제를 따라가고 있다는 뜻이다.",
     ["climate", "ecolog", "glacier", "nature", "forest", "ocean", "plant", "soil", "기후", "생태", "자연", "숲", "바다", "빙하", "環境", "自然", "森"]),
    ("archive", "기록과 기억", "전시장이 기록과 기억을 꺼내 들었다",
     "아카이브를 앞세운 전시가 겹치면 '새 작품'보다 '다시 읽기'가 시즌의 방향이라는 뜻이다.",
     ["archive", "memory", "memories", "diary", "chronicle", "crônicas", "기억", "아카이브", "증언", "記憶", "記録"]),
    ("tech", "AI와 기술", "AI와 기술을 묻는 자리가 늘었다",
     "기술을 다루는 자리가 전시·보도에 함께 늘면 장비가 아니라 '저자'와 '노동'의 문제로 논의가 옮겨가는 중이다.",
     ["ai", "artificial intelligence", "algorithm", "digital", "virtual", "robot", "인공지능", "디지털", "알고리즘", "미디어아트", "テクノロジー"]),
    ("popular", "만화와 대중문화", "만화와 대중문화가 미술관 안으로 들어왔다",
     "대중문화가 공립 기관의 전시실로 들어오면 관객층과 '미술'의 경계가 함께 넓어진다.",
     ["manga", "comic", "anime", "cartoon", "shojo", "만화", "웹툰", "애니메이션", "漫画", "マンガ", "アニメ", "少女"]),
    ("women", "여성 작가", "여성 작가를 다시 읽는 전시가 이어진다",
     "여성 작가를 다시 꺼내는 기획이 겹치면 미술사 서술을 고쳐 쓰는 작업이 기관 단위로 진행 중이라는 뜻이다.",
     ["women", "woman", "feminis", "female", "femme", "frauen", "여성", "페미", "女性"]),
    ("craft", "재료와 손", "재료와 손의 감각이 전시장으로 돌아왔다",
     "공예·재료를 앞세운 전시가 늘면 시장과 기관이 '만드는 과정'을 다시 가치로 보고 있다는 신호다.",
     ["craft", "ceramic", "textile", "clay", "weaving", "fiber", "fibre", "공예", "도자", "섬유", "직조", "工芸", "陶"]),
    ("photo", "사진", "사진이 이번 주 전시의 중심에 섰다",
     "사진 전시가 몰리면 기록 매체로서의 사진이 다시 질문받는 시기다.",
     ["photograph", "photo", "fotografia", "사진", "写真"]),
    ("moving", "영상", "영상과 무빙이미지가 전시장을 채웠다",
     "영상 작업이 기관 프로그램에 고정 자리를 얻는 흐름은 소장·상영 방식의 변화로 이어진다.",
     ["video", "film", "cinema", "moving image", "영상", "영화", "씨네", "映像"]),
    ("sound", "소리", "소리를 듣는 전시가 늘었다",
     "보는 전시에서 듣는 전시로 감각이 옮겨가는 기획이 겹치고 있다.",
     ["sound", "sonic", "music", "listen", "소리", "사운드", "음악"]),
    ("migration", "이주와 경계", "이주와 경계가 이번 주의 화두다",
     "이주를 다루는 전시가 동시에 열리면 미술이 국경과 정체성 문제에 응답하는 시기다.",
     ["migra", "diaspora", "border", "exile", "refugee", "이주", "디아스포라", "난민", "移民", "越境"]),
    ("retro", "회고전", "기관들이 거장의 생애를 다시 펼쳤다",
     "회고전이 겹치면 기관이 새 이름보다 검증된 이름으로 시즌을 여는 것이다 — 신진 쪽 기회는 그만큼 좁다.",
     ["retrospective", "lifetime", "centenary", "회고전", "회고", "100주년", "작고", "回顧"]),
    ("power", "전쟁과 권력", "전쟁과 권력을 묻는 미술이 겹친다",
     "정치를 정면으로 다루는 작업이 상과 전시에서 함께 주목받는 것은 미술계의 관심이 형식보다 발언으로 기울었다는 뜻이다.",
     ["war", "violence", "conflict", "politic", "전쟁", "권력", "정치", "분단", "폭력", "戦争", "権力"]),
]


def _kw_re(words):
    parts = []
    for w in words:
        if re.fullmatch(r"[a-z ]+", w):  # Latin words: no letter before; short ones also none after (Hangul may follow)
            parts.append(r"(?<![A-Za-z])" + re.escape(w) + (r"(?![A-Za-z])" if len(w) <= 3 else ""))
        else:
            parts.append(re.escape(w))
    return re.compile("|".join(parts), re.I)


THEME_RX = {k: _kw_re(words) for k, *_rest, words in THEMES}
THEME_INFO = {k: (label, claim, why) for k, label, claim, why, _ in THEMES}

# Tie-break among equal signal strength: interpretive axes before counting axes.
AXIS_ORDER = ["화제", "작가", "주제", "교차", "전시", "신진 경로", "비평", "기관", "갤러리", "수상·루키", "페어·비엔날레", "보도"]


def ranked(obs: List[dict]) -> List[dict]:
    """Strongest first, interpretive axes first on ties; one headline per subject (organizer, artist, theme)."""
    obs = sorted(obs, key=lambda o: (-o["power"], AXIS_ORDER.index(o["axis"]) if o["axis"] in AXIS_ORDER else 99))
    out, used = [], set()
    for o in obs:
        keys = set(o.get("keys") or [])
        if keys & used:
            continue
        used |= keys
        out.append(o)
    return out


FRESH_DAYS = 1      # evidence dated today or yesterday counts as a new development
PRIOR_DAYS = 2      # a subject that led the last two issues steps aside unless something new happened
PRIOR_TOP = 3       # 'led' = among the first three headlines
OLD_DAYS = 3        # evidence older than this is last week's news, even if the 7-day window still holds it


def subject_keys(o: dict) -> set:
    """What a headline is about: its axis keys plus the exhibitions it rests on, so the same show cannot
    lead again under another axis (yesterday's award-show bridge returning today as a buzz item)."""
    return (set(o.get("keys") or []) or {f"{o['axis']}:{o['title']}"}) | set(o.get("ev_keys") or [])


def freshen(obs: List[dict], shown: Dict[str, int], d: dt.date, slot: Optional[Dict[str, float]] = None) -> List[dict]:
    """Every issue opens on something new: a subject that already led recent issues, with no new evidence since,
    loses one step of signal strength per issue it led (it stays on the page, lower down, and in the story lists)."""
    for o in obs:
        latest = day(o.get("latest"))
        fresh = latest is not None and latest >= d - dt.timedelta(days=FRESH_DAYS)
        o["repeat"] = 0 if fresh else max((shown.get(k, 0) for k in subject_keys(o)), default=0)
        old = latest is not None and latest < d - dt.timedelta(days=OLD_DAYS)
        eff = o["power"] - o["repeat"] - (1 if old else 0)
        # a real story that has had its turn still outranks the 'quiet week' fillers (power 1)
        o["effective"] = max(eff, 1.5) if o["power"] >= 2 else eff
    order = {id(o): i for i, o in enumerate(obs)}
    slot = slot or {}
    # among subjects that have all had their turn, the one that led most recently moves furthest down: the lead rotates
    o_slot = lambda o: 0 if not o["repeat"] else max((slot.get(k, 0) for k in subject_keys(o)), default=0)
    return sorted(obs, key=lambda o: (-o["effective"], o_slot(o), order[id(o)]))


HISTORY_DEPTH = 6   # how far back the 'already led' memory is rebuilt when no earlier issue is cached


def headlines(vb, edition: str, d: dt.date, stories: Optional[List[dict]] = None, tr: Optional["Trend"] = None,
              _depth: int = HISTORY_DEPTH) -> List[dict]:
    """Ranked headlines for one issue; what led the previous issues (as actually shown) steps aside unless renewed."""
    shown_cache = vb.__dict__.setdefault("_shown_top", {})
    obs = ranked((tr or Trend(vb, edition, d)).all(stories))
    shown: Dict[str, int] = collections.Counter()
    slot: Dict[str, float] = collections.Counter()
    if _depth > 0:
        for k in range(1, PRIOR_DAYS + 1):
            pd = d - dt.timedelta(days=k)
            if (edition, pd) not in shown_cache:
                pst = vb.stories(edition, pd - dt.timedelta(days=6), pd, pd)
                prev = headlines(vb, edition, pd, pst, _depth=_depth - 1)
                shown_cache[(edition, pd)] = [subject_keys(o) for o in prev[:PRIOR_TOP]]
            for pos, keys in enumerate(shown_cache[(edition, pd)]):
                for key in keys:
                    shown[key] += 1
                    slot[key] += (PRIOR_TOP - pos) / k  # yesterday's lead weighs most
    out = freshen(obs, shown, d, slot)
    prev_lead = shown_cache.get((edition, d - dt.timedelta(days=1)), [set()])[:1]
    if out and prev_lead and subject_keys(out[0]) & prev_lead[0] and out[0].get("latest") != d.isoformat():
        # the cover changes every day: yesterday's lead returns to the top only with evidence dated today
        alt = next((i for i, o in enumerate(out[1:], 1) if o["effective"] >= 1.5 and not subject_keys(o) & prev_lead[0]), None)
        if alt is not None:
            out.insert(0, out.pop(alt))
    if _depth == HISTORY_DEPTH:
        shown_cache[(edition, d)] = [subject_keys(o) for o in out[:PRIOR_TOP]]
    return out


def city_ko(city: Optional[str]) -> str:
    c = city or ""
    for k, v in CITY_KO.items():
        if k in c:
            return v
    return c.split(",")[-1].strip() or c


CITY_KO = {"Seoul": "서울", "Busan": "부산", "Incheon": "인천", "Daegu": "대구", "Gwangju": "광주", "Tokyo": "도쿄", "Kyoto": "교토",
           "Osaka": "오사카", "New York": "뉴욕", "Los Angeles": "LA", "São Paulo": "상파울루", "London": "런던", "Paris": "파리",
           "Berlin": "베를린", "Torino": "토리노", "Venice": "베네치아"}


def josa(word: str, pair: str = "이가") -> str:
    """Korean subject particle by the last syllable's final consonant; non-Hangul words get the '이(가)' form."""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return word + (pair[0] if (ord(ch) - 0xAC00) % 28 else pair[1])
    return f"{word}{pair[0]}({pair[1]})"


def ida(word: str) -> str:
    """Copula '이다/다' by the last syllable; non-Hangul endings get '(이)다'."""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return word + ("이다" if (ord(ch) - 0xAC00) % 28 else "다")
    return word + "(이)다"


def short(title: Optional[str], n: int = 24) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    t = re.sub(r"^(?:News\s+)?Featured in .*?\b\d{4}\s+", "", t)  # gallery press-feed prefix ('Featured in Frieze 20 October 2026 ')
    t = re.split(r"\s*[《「(]|:\s", t)[0].strip() or t
    return t if len(t) <= n else t[:n].rstrip() + "…"


def day(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def pct(cur: float, base: float) -> str:
    if base <= 0:
        return "비교 기준 없음"
    ch = (cur - base) / base * 100
    return f"{'+' if ch >= 0 else ''}{ch:.0f}%"


SHORT_WHY = {
    "colonial": "식민의 기억을 다시 묻는 기획이 겹쳤다.", "body": "몸과 감각이 다시 전시의 언어가 됐다.",
    "ecology": "기후 위기가 전시장의 의제가 됐다.", "archive": "새 작품보다 '다시 읽기'가 시즌의 방향.",
    "tech": "논점은 장비가 아니라 저자와 노동.", "popular": "대중문화가 미술관 문턱을 넘었다.",
    "women": "미술사를 여성 작가 중심으로 고쳐 쓰는 중.", "craft": "'만드는 손'이 다시 가치가 됐다.",
    "photo": "기록 매체로서의 사진이 다시 질문받는다.", "moving": "영상이 전시실에 고정석을 얻고 있다.",
    "sound": "보는 전시에서 듣는 전시로.", "migration": "국경과 정체성에 미술이 응답한다.",
    "retro": "기관들이 새 이름보다 검증된 이름을 택했다.", "power": "형식보다 발언 — 정치를 정면으로 다룬다.",
}


def short_org(org: str) -> str:
    """'MAXXI Museo nazionale delle arti del XXI secolo' -> 'MAXXI'; 'The Museum of Modern Art' -> 'MoMA'."""
    known = {"The Museum of Modern Art": "MoMA", "Museum of Modern Art": "MoMA", "Mori Art Museum": "모리미술관",
             "Art Institute of Chicago": "시카고미술관", "Solomon R. Guggenheim Museum": "구겐하임"}
    if org in known:
        return known[org]
    m = re.match(r"^([A-Z0-9]{3,})\b\s+(?:Museo|Museum|Musée|Fondazione|Fondation|–|-)", org)
    if m:
        return m.group(1)
    return org.split(" – ")[0] if len(org) > 26 else org


def award_and_artist(title: str, arts: List[str]) -> tuple:
    """'제26회 이인성미술상 수상자전 《이명미: …》' -> ('이인성미술상', '이명미'); 'Mori Art Award 2026 Grand Prize Exhibition' -> ('Mori Art Award', None)."""
    head = re.split(r"[《「“\"]", title)[0]
    award = re.sub(r"^\s*(?:제\s*)?\d+\s*회\s*|^\s*\d{4}\s*", "", head)
    award = re.sub(r"\s*(?:수상(?:작가)?(?:자)?전|Grand Prize Exhibition|Exhibition|展)\b.*$|\s*\d{4}\s*$", "", award).strip(" :-–")
    award = re.sub(r"\s*\d{4}\s*$", "", award).strip()
    m = re.search(r"[《「“\"]\s*([^:：》」”\"]{2,20})\s*[:：]", title)
    who = m.group(1).strip() if m else (arts[0] if len(arts) == 1 else None)
    return (award or None), who


CHECK_NOTE = re.compile(r"\s*[—-]\s*본문 확인\.?")


FEED_PREFIX = re.compile(r"^(?:(?:News\s+)?Featured in .+? \d{1,2} \w+ \d{4}|\d{4}년 \d{1,2}월 \d{1,2}일 .{1,20}?에 소개됨)\s+")
COUNT_OUTLETS = re.compile(r"\s*(?:이번 주|이틀 사이)?\s*\d+\s*개?\s*(?:매체|곳)(?:가|이|에서)?\s*(?:다뤘다|전했다|보도했다)\.?")


def same_story(st: dict) -> List[dict]:
    """The lead and the members that tell the same story (clusters can glue neighbouring press releases together)."""
    lead = st.get("lead") or {}
    words = lambda t: {w for w in re.findall(r"[가-힣A-Za-z]{2,}", t or "")}
    lw = words(lead.get("title"))
    out = [lead] + [m for m in st.get("members") or [] if m is not lead and m.get("canonical_url") != lead.get("canonical_url")
                    and len(lw & words(m.get("title"))) >= max(3, len(lw) // 2)]
    return out


NATION_KO = {
    "Germany": "독일", "German": "독일", "France": "프랑스", "French": "프랑스", "United States": "미국", "American": "미국",
    "United States of America": "미국", "Japan": "일본", "Japanese": "일본", "United Kingdom": "영국", "British": "영국",
    "Italy": "이탈리아", "Italian": "이탈리아", "Spain": "스페인", "Spanish": "스페인", "Brazil": "브라질", "Brazilian": "브라질",
    "Mexico": "멕시코", "Mexican": "멕시코", "South Korea": "한국", "Korean": "한국", "China": "중국", "Chinese": "중국",
    "Canada": "캐나다", "Canadian": "캐나다", "Netherlands": "네덜란드", "Dutch": "네덜란드", "Switzerland": "스위스", "Swiss": "스위스",
    "Austria": "오스트리아", "Austrian": "오스트리아", "Belgium": "벨기에", "Belgian": "벨기에", "Ghana": "가나", "Ghanaian": "가나",
    "Nigeria": "나이지리아", "Nigerian": "나이지리아", "India": "인도", "Indian": "인도", "Argentina": "아르헨티나", "Colombia": "콜롬비아",
    "Colombian": "콜롬비아", "Guatemala": "과테말라", "Guatemalan": "과테말라", "Vietnam": "베트남", "Thailand": "태국", "Thai": "태국",
    "Denmark": "덴마크", "Danish": "덴마크", "Sweden": "스웨덴", "Swedish": "스웨덴", "Norway": "노르웨이", "Poland": "폴란드",
    "Australia": "호주", "Australian": "호주", "South Africa": "남아프리카공화국", "Ireland": "아일랜드", "Portugal": "포르투갈",
}


class Trend:
    def __init__(self, vb, edition: str, d: dt.date):
        self.vb, self.E, self.d = vb, edition, d
        self.week = (d - dt.timedelta(days=6), d)
        self.events = [ev for ev in vb.events.values() if ev["edition_region"] == edition]

    # -- helpers
    def kind(self, ev: dict) -> str:
        src = self.vb.sources.get(ev["source_id"]) or {}
        k = KIND_OF.get(src.get("source_kind"))
        if k:
            return k
        return MUSEUM if re.search(r"moma|museum|mmca|sema", ev["source_id"]) else "other"

    def org(self, ev: dict) -> str:
        eid = ev.get("organizer_entity_id")
        if eid and eid in self.vb.entities:
            return self.vb.entities[eid]["canonical_name"]
        return (self.vb.sources.get(ev["source_id"]) or {}).get("name") or ev["source_id"]

    def opened(self, lo: dt.date, hi: dt.date, kinds=None) -> List[dict]:
        out = [ev for ev in self.events if ev["event_type"] in SHOW_TYPES and ev.get("start_precision") in (None, "day")
               and (s := day(ev["start_date"])) and lo <= s <= hi]
        return [ev for ev in out if kinds is None or self.kind(ev) in kinds]

    def baseline(self, kinds=None) -> float:
        """Mean weekly openings over the four weeks before this week."""
        n = len(self.opened(self.d - dt.timedelta(days=34), self.d - dt.timedelta(days=7), kinds))
        return n / 4

    def artists(self, ev: dict) -> List[tuple]:
        return [(p["entity_id"], p["name_as_listed"]) for p in self.vb.participants.get(ev["event_id"], [])
                if p["role"] in ("artist", "exhibitor")]

    @staticmethod
    def route(title: str) -> str:
        """Edition of a gallery-feed item: an explicit non-European place wins; otherwise the feeds' home, EUROPE."""
        for e in ("KR", "JP", "AMERICAS"):
            if EDITION_HINT[e].search(title):
                return e
        return "EUROPE"

    def find_names(self, title: Optional[str]) -> List[tuple]:
        m = getattr(self.vb, "name_matcher", None)
        return m(self.E).find(title) if m and title else []

    def press_names(self) -> set:
        return {eid for st in getattr(self, "_stories", []) for _, eid in st.get("names") or [] if eid}

    def link(self, ev: dict) -> str:
        return self.vb.event_link(ev["event_id"])

    def ko_title(self, a: dict) -> str:
        ko = self.vb.ko_of("articles", a["article_id"], "title", a["title"]) if hasattr(self.vb, "ko_of") else None
        return ko if ko and "⁇" not in ko else (a.get("title") or "")

    def head(self, ev: dict) -> str:
        """Short human handle of a show: its artist when it is a solo/small show, else the title cut at a word."""
        arts = [nm for _, nm in self.artists(ev)]
        if 0 < len(arts) <= 3:
            return short(arts[0], 26)
        t = short(ev["title"], 60)
        if len(t) > 28:
            t = t[:28].rsplit(" ", 1)[0] + "…"
        return t

    def ev_title(self, ev: dict) -> str:
        ko = self.vb.ko_of("events", ev["event_id"], "title", ev["title"]) if hasattr(self.vb, "ko_of") else None
        cut = lambda x, n: x if len(x) <= n else x[:n].rsplit(" ", 1)[0] + "…"
        orig = re.sub(r"\s+", " ", ev["title"] or "").strip()
        return f"{cut(ko, 60)}({cut(orig, 50)})" if ko else cut(orig, 80)

    def when(self, ev: dict) -> str:
        s, e = day(ev["start_date"]), day(ev["end_date"])
        if not s:
            return ""
        if e and e != s:
            return f"{s.month}월 {s.day}일–{'' if e.year == s.year else str(e.year) + '년 '}{e.month}월 {e.day}일"
        return f"{s.month}월 {s.day}일"

    def ev_line(self, ev: dict) -> str:
        """One concrete line a reader can act on: what, where, when, who, and what it is about."""
        place = self.org(ev) + (f"({city_ko(ev['city'])})" if ev.get("city") and city_ko(ev["city"]) not in self.org(ev) else "")
        arts = [nm for _, nm in self.artists(ev)]
        line = f"《{self.ev_title(ev)}》 — {place}, {self.when(ev)}"
        if 0 < len(arts) <= 4 and not any(a in ev["title"] for a in arts[:1]):
            line += f" · 작가 {', '.join(arts)}"
        elif len(arts) > 4:
            line += f" · 작가 {', '.join(arts[:3])} 외 {len(arts) - 3}명"
        desc = ev.get("description_excerpt")
        ko = self.vb.ko_of("events", ev["event_id"], "description_excerpt", desc) if desc and hasattr(self.vb, "ko_of") else None
        about = ko or (desc if desc and re.search(r"[가-힣]", desc) else None)
        if about:
            first = re.split(r"(?<=[.다])\s", about.strip())[0]
            if len(first) >= 25 and not first.startswith(("장소", "Venue", "위치")) and not re.search(r"요일|\d\s\d+월|│|\|", first):
                line += f". {short(first, 110)}"
        return line

    def art_line(self, a: dict) -> str:
        outlet = self.vb.source_label(a, bare=True) if hasattr(self.vb, "source_label") else (a.get("publisher") or "")
        date = (a.get("published_at") or "")[:10]
        d = day(date)
        ko = self.ko_title(a)
        raw = ko == (a.get("title") or "") and re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ko) and not re.search(r"[가-힣]", ko)
        return f"{outlet}{f' {d.month}/{d.day}' if d else ''}: ‘{short(ko, 90)}’" + (" (원문 — 자동 번역이 부정확해 싣지 않음)" if raw else "")

    def who(self, eid: Optional[str]) -> str:
        e = self.vb.entities.get(eid) if eid else None
        if not e:
            return ""
        if not hasattr(self.vb, "_facts_by_name"):  # one person is often several records; use a fact only when they agree
            idx: Dict[str, dict] = collections.defaultdict(lambda: dict(nat=set(), born=set()))
            for x in self.vb.entities.values():
                if x.get("entity_type") in ("person", "artist"):
                    f = idx[x["canonical_name"]]
                    if x.get("nationality_text"):
                        f["nat"].add(NATION_KO.get(x["nationality_text"].strip(), x["nationality_text"].strip()))
                    if x.get("birth_year"):
                        f["born"].add(x["birth_year"])
            self.vb._facts_by_name = idx
        f = self.vb._facts_by_name.get(e["canonical_name"]) or dict(nat=set(), born=set())
        nat = next(iter(f["nat"])) if len(f["nat"]) == 1 else ""
        born = next(iter(f["born"])) if len(f["born"]) == 1 else None
        bits = [f"{nat} 출신" if nat and not re.search(r"[;,/]", nat) and len(nat) <= 20 else "",
                f"{born}년생" if born else ""]
        return ", ".join(b for b in bits if b)

    def fair_soon(self, days: int = 14) -> Optional[dict]:
        soon = [ev for ev in self.events if ev["event_type"] == "fair_edition" and (s := day(ev["start_date"])) and self.d < s <= self.d + dt.timedelta(days=days)]
        return min(soon, key=lambda ev: ev["start_date"]) if soon else None

    def so_what(self, story: Optional[dict]) -> str:
        """Editor note first, rule judgement second; first sentence only, and only when it says something specific."""
        if not story:
            return ""
        if not hasattr(self, "_notes"):
            from . import editorial
            notes, self._notes = editorial.load_notes_upto(self.d), {}
            for pk in editorial.load_packets_upto(self.d):
                for e in (pk.get("editions") or {}).values():
                    for st in e.get("major", []) + e.get("rookie", []):
                        nv = notes["major"].get(st["key"])
                        if nv and not nv.get("exclude"):
                            self._notes.update({m["url"]: nv for m in st["members"]})
            for nv in notes["major"].values():
                if not nv.get("exclude"):
                    self._notes.update({x["url"]: nv for x in nv.get("sources", [])})
            self._notes.update(notes.get("daily") or {})
        sw = ""
        for m in [story.get("lead") or {}] + list(story.get("members") or []):
            n = self._notes.get(m.get("canonical_url") or "")
            if n and n.get("so_what"):
                sw = n["so_what"]
                break
        if not sw:
            try:
                from . import editorial
                j = editorial.auto_judgement(story, self.d) or {}
                sw = j.get("so_what") or "" if j.get("points", 0) >= 3 else ""
            except Exception:
                sw = ""
        sw = re.split(r"(?<=[.다])\s", sw.strip())[0] if sw else ""
        sw = re.sub(r"\s?\([A-Z]{1,2}\d{2}\)", "", sw)  # internal Blueprint codes are for editors, not readers
        return sw if len(sw) >= 25 else ""

    # -- axes
    def exhibitions(self) -> Optional[dict]:
        lo, hi = self.week
        week = self.opened(lo, hi)
        base = self.baseline()
        nxt = self.opened(self.d + dt.timedelta(days=1), self.d + dt.timedelta(days=14))
        if not week and not nxt and base == 0:
            return None
        g = sum(self.kind(ev) == GALLERY for ev in week)
        m = sum(self.kind(ev) == MUSEUM for ev in week)
        cities = collections.Counter(ev["city"] for ev in week if ev["city"])
        cmp = (f"직전 4주 주평균 {base:.1f}건, {pct(len(week), base)}" if base >= MIN_BASE
               else f"직전 4주 수집 {base * 4:.0f}건뿐이라 증감 비교 보류")
        fact = (f"지난 7일 개막 {len(week)}건({cmp}) — 갤러리 {g} · 미술관·기관 {m}"
                + (f" · 도시 {', '.join(f'{c} {k}' for c, k in cities.most_common(2))}" if cities else "")
                + f". 앞으로 2주 개막 예정 {len(nxt)}건.")
        if base < MIN_BASE:
            read = "이 에디션은 일 단위 전시 수집이 최근에야 쌓이기 시작해 '평소'를 아직 말할 수 없다 — 숫자는 이번 주 현황으로만 읽는다."
        elif len(week) >= base * 1.3:
            read = "개막이 평소보다 몰린 주다 — 시즌 개막(가을 시즌·아트페어 전후) 효과인지 다음 주 수치로 확인한다."
        elif len(week) <= base * 0.7:
            read = "개막이 평소보다 적은 주다 — 수집 공백인지 실제 소강인지 출처별 수집 상태로 먼저 확인한다."
        else:
            read = "개막 수는 평소 범위다."
        if g and m and g > m * 2:
            read += " 이번 주 흐름은 갤러리 쪽이 주도한다."
        elif m > g * 2 and m >= 2:
            read += " 이번 주 흐름은 미술관·기관 쪽이 주도한다."
        talked = self.press_names()
        picks = sorted(week, key=lambda ev: (-sum(eid in talked for eid, _ in self.artists(ev)), self.kind(ev) != MUSEUM, ev["start_date"]))[:3]
        city = cities.most_common(1)[0][0] if cities else None
        where = f"{CITY_KO.get(city, city)}" if city else "이 지역"
        leader = "미술관" if m > g else ("갤러리" if g > m else "미술관·갤러리")
        hot = [ev for ev in picks if any(eid in talked for eid, _ in self.artists(ev))]
        names = " · ".join(short(ev["title"]) for ev in (hot or picks)[:2])
        shows = " · ".join(f"《{short(ev['title'], 30)}》" for ev in (hot or picks)[:2])
        by_org = collections.Counter(self.org(ev) for ev in week)
        top_org, top_k = by_org.most_common(1)[0] if by_org else (None, 0)
        keys = []
        if top_k >= 3 and top_k / len(week) >= SEASON_SHARE:
            evs = [ev for ev in week if self.org(ev) == top_org]
            title, dek = self.season(top_org, evs)
            kind_ko = "미술관" if self.kind(evs[0]) == MUSEUM else "갤러리"
            dek = f"이번 주 {where} 새 전시 {len(week)}개 중 {top_k}개가 여기서 나왔다."
            points = [f"도시가 붐빈 게 아니다 — {kind_ko} 한 곳이 시즌 판을 새로 짰다."]
            power = 3 if base >= MIN_BASE and len(week) >= base * 1.3 else 2
            keys = [f"org:{top_org}"]
            prize = [ev for ev in evs if AWARD_SHOW.search(ev["title"] or "")]
            if prize:
                aw_name = award_and_artist(prize[0]["title"] or "", [])[0]
                points.append(f"{aw_name} 수상전도 함께 열렸다 — 상이 곧장 전시로.")
                keys.append("bridge")
            kind = "미술관" if self.kind(evs[0]) == MUSEUM else "갤러리"
            dates = sorted({self.when(dict(ev, end_date=None)) for ev in evs})
            about = (f"{top_org}({where}의 {kind})에서 {dates[0] if len(dates) == 1 else dates[0] + '부터'} 새 전시 {len(evs)}개가 한꺼번에 문을 열었다. "
                     f"이번 주 {where}에서 문을 연 전시 {len(week)}개 가운데 {top_k}개가 이곳 것이라, 이 도시의 '이번 주 전시'는 사실상 이 {kind}의 시즌 개편이다.")
            return dict(axis="전시", title=title, dek=dek, power=power, fact=fact, read=read, items=[self.link(ev) for ev in evs[:3]], keys=keys,
                        about=about, evs=evs[:5], points=points)
        if base >= MIN_BASE and len(week) >= base * 1.3 and len(by_org) >= 3:
            r = len(week) / base
            size = "두 배 이상" if r >= 2 else ("두 배 가까이" if r >= 1.7 else "1.5배")
            title, power = f"{where} 전시장 붐빈다 — 새 전시 평소의 {size}", 3
            dek = f"이번 주 새 전시 {len(week)}개, 흐름은 {leader} 쪽이 이끈다."
        elif base >= MIN_BASE and len(week) <= base * 0.7:
            fair = self.fair_soon()
            if fair:
                title, power = f"{short(fair['title'], 30)} 앞두고 개막 '일시정지'", 2
                dek = f"이번 주 개막 {len(week)}개 → 2주 안에 {len(nxt)}개 대기. 페어 주간에 맞춰 전시를 미뤄 둔 모양새다."
                keys = ["fair"]
            else:
                title, power = "전시 개막, 잠시 숨 고르기", 1
                dek = f"대신 2주 안에 새 전시 {len(nxt)}개가 문을 연다."
        else:
            title, power = f"이번 주 {where} 전시, {josa(leader)} 판을 이끈다" if leader != "미술관·갤러리" else f"이번 주 {where}에 새 전시 {len(week)}개", 1 + bool(hot)
            dek = f"새로 문을 연 전시 {len(week)}개."
        points = [(f"주목: {shows} — 작가가 뉴스에도 함께 오른다." if hot else f"눈여겨볼 전시: {shows}")] if shows else []
        return dict(axis="전시", title=title, dek=dek, power=power, fact=fact, read=read, items=[self.link(ev) for ev in picks], keys=keys,
                    about=f"이번 주 {where}에서 문을 연 전시:", evs=picks, points=points)

    def season(self, org: str, evs: List[dict]) -> tuple:
        """Headline for one organizer opening several shows: name what it opened, not how many."""
        heads = []
        series = re.compile(r"\b(screen|project|collection|room|sala|focus|display)\b|\d{3}", re.I)
        for ev in sorted(evs, key=lambda e: (bool(AWARD_SHOW.search(e["title"] or "")), bool(series.search(e["title"] or "")),
                                             self.head(e).endswith("…"), e["start_date"], e["title"] or "")):
            h = self.head(ev)
            if h and h not in heads:
                heads.append(h)
        same_day = len({ev["start_date"] for ev in evs}) == 1
        clean = [h for h in heads if not h.endswith("…") and len(h) <= 24]
        title = (f"{short_org(org)}, {'하루에' if same_day else '한꺼번에'} 전시 {len(evs)}개 오픈 — {clean[0]}·{clean[1]}" if len(clean) >= 2
                 else f"{short_org(org)}, {'하루에' if same_day else '2주 새'} 전시 {len(evs)}개 연속 오픈")
        dek = "같은 날 한꺼번에 문을 열었다." if same_day else "2주 사이 연달아 문을 열었다."
        return title, dek

    def galleries(self) -> Optional[dict]:
        lo, hi = self.week
        week = self.opened(lo - dt.timedelta(days=7), hi, {GALLERY})
        news = [a for sc in ("KR", "JP", "AMERICAS", "EUROPE", "GLOBAL") for a in self.vb.reading(sc, lo, hi)
                if (self.vb.sources.get(a["source_id"]) or {}).get("source_kind") == GALLERY]
        news = [a for a in news if self.route(a["title"] or "") == self.E]
        if not week and not news:
            return None
        orgs = collections.Counter(self.org(ev) for ev in week)
        keys = []
        fact = f"갤러리 개막 {len(week)}건(최근 14일)"
        if orgs:
            fact += " — " + ", ".join(f"{o} {k}" for o, k in orgs.most_common(4))
        if news:
            fact += f". 갤러리 공식 소식 {len(news)}건(최근 7일)"
        kinds = collections.Counter()
        for a in news:
            t = a["title"] or ""
            kinds["언론 소개"] += bool(re.search(r"Featured in|Press|Interview|인터뷰", t))
            kinds["기관 전시"] += bool(re.search(r"museum|Museum|Kunsthalle|Biennale|retrospective|미술관", t))
            kinds["수상·서훈"] += bool(re.search(r"award|prize|Officier|Ordre", t, re.I))
            kinds["페어"] += bool(re.search(r"fair|Frieze|Art Basel|Artissima|Kiaf", t, re.I))
        top = [k for k, v in kinds.most_common() if v]
        read = ("갤러리가 스스로 알리는 소식은 " + "·".join(f"{k} {kinds[k]}" for k in top[:3]) + " 순 — 소속 작가의 미술관 전시·수상을 홍보하는 흐름이면 "
                "갤러리 사건이 아니라 작가 사건(A축)으로 옮겨 본다.") if top else "갤러리 공식 소식은 전시 공지 위주다."
        if orgs and orgs.most_common(1)[0][1] >= 3:
            read += f" {orgs.most_common(1)[0][0]}의 개막이 몰려 있다(같은 갤러리 다지점 동시 개막인지 확인)."
        items = [self.link(ev) for ev in week[:2]] + [f"[{(a['title'] or '')[:60]}]({a['canonical_url']})" for a in news[:3]]
        promoted = []
        for a in news:
            for nm, eid in self.find_names(a["title"]):
                if (self.vb.entities.get(eid) or {}).get("entity_type") in ("person", "artist", "group") and nm not in promoted:
                    promoted.append(nm)
        who = ", ".join(promoted[:2])
        if orgs and orgs.most_common(1)[0][1] >= 3:
            o, k = orgs.most_common(1)[0]
            title, dek = self.season(o, [ev for ev in week if self.org(ev) == o])
            power = 2
            points = [f"공식 발표는 {who}의 미술관 전시·수상 소식을 앞세웠다." if promoted
                      else "한 갤러리의 연속 개막 — 페어·시즌을 앞둔 공세다."]
            keys = [f"org:{o}"]
            about = f"갤러리 {o}에서 최근 2주 사이 전시 {k}개가 잇달아 열렸다:"
        elif promoted:
            title, power = f"갤러리들이 밀어주는 이름: {who}", 2
            dek = "소속 작가의 미술관 전시·수상·언론 소개를 앞세운 발표가 잇따랐다."
            points = ["갤러리 홍보가 '우리 전시'에서 '우리 작가의 바깥 성과'로 옮겨갔다."]
            about = "갤러리들이 직접 낸 공식 소식 가운데 소속 작가의 바깥 성과(미술관 전시·수상·언론 소개)를 알린 글:"
        elif (fair := self.fair_soon()):
            n_days = (day(fair["start_date"]) - self.d).days
            title, power = f"{short(fair['title'], 30)} D-{n_days}, 갤러리는 숨 고르기", 2
            dek = f"최근 2주 갤러리 개막은 {len(week)}개뿐 — 힘은 페어 부스 준비로 쏠렸다."
            points = ["관전 포인트: 누가 어떤 작가를 부스에 거느냐."]
            keys = ["fair"]
            host = self.org(fair) if self.org(fair) not in fair["title"] else ""
            place = " ".join(x for x in (city_ko(fair.get("city")) if fair.get("city") else "", host) if x) or "현지"
            about = (f"{fair['title']}는 {place}에서 {self.when(fair)} 열리는 아트페어다. 페어가 코앞이라 갤러리 자체 전시는 최근 2주 {len(week)}개만 새로 열렸다:")
        else:
            title, power = "갤러리, 조용한 한 주", 1
            dek = f"최근 2주 새 갤러리 전시는 {len(week)}개."
            points = []
            about = "최근 2주 새로 문을 연 갤러리 전시:"
        lead = [ev for ev in week if orgs and self.org(ev) == orgs.most_common(1)[0][0]] if keys and keys[0].startswith("org:") else week
        return dict(axis="갤러리", title=title, dek=dek, power=power, fact=fact, read=read, items=items, keys=keys,
                    about=about, evs=lead[:4], arts=news[:3] if promoted else [], points=points)

    def institutions(self) -> Optional[dict]:
        lo, hi = self.d - dt.timedelta(days=30), self.d
        acq = [ev for ev in self.events if ev["event_type"] == "acquisition" and (s := day(ev["announced_date"] or ev["start_date"])) and lo <= s <= hi]
        week = self.opened(*self.week, {MUSEUM})
        if not acq and not week:
            return None
        parts = []
        if week:
            parts.append(f"미술관·기관 개막 {len(week)}건(최근 7일) — " + ", ".join(sorted({self.org(ev) for ev in week})[:4]))
        read = ""
        if acq:
            holders = collections.Counter(self.org(ev) for ev in acq)
            n_works = sum(int(m.group(1)) for ev in acq if (m := re.search(r"\((\d+) works?\)", ev["title"] or "")))
            parts.append(f"소장품 신규 등록 {len(acq)}건(최근 30일, 작품 {n_works or '?'}점) — " + ", ".join(f"{h} {k}" for h, k in holders.most_common(2)))
            names = collections.Counter(re.sub(r"^.*accession:\s*|\s*\(\d+ works?\)$", "", ev["title"] or "") for ev in acq)
            read = ("소장품 등록은 공개 데이터 갱신일 기준이라 실제 매입일과 다를 수 있다. 이번 묶음 작가: "
                    + ", ".join(n for n, _ in names.most_common(4)) + " — 같은 작가의 전시가 따라오는지 본다.")
        else:
            read = "기관 쪽은 전시 개막 외에 소장·인사 변화가 데이터로 잡히지 않았다(뉴스 축에서 확인)."
        if acq:
            holder = holders.most_common(1)[0][0]
            who = ", ".join(n for n, _ in names.most_common(2))
            title, power = f"{short_org(holder)}가 새로 사들인 작가: {who}", 2
            dek = f"최근 30일 소장품 {n_works or len(acq)}점 추가(공개 데이터 기준)."
            points = ["무엇을 사는지는 무엇을 거는지보다 오래 남는다.", "다음 신호: 같은 작가의 전시가 뒤따르는지."]
            about = (f"{holder}의 공개 소장품 데이터에 최근 30일 사이 작가 {len(names)}명의 작품 {n_works or len(acq)}점이 새로 등록됐다. "
                     f"새로 들어온 작가: {', '.join(n for n, _ in names.most_common(6))}. 실제 매입일이 아니라 데이터 공개일 기준이다.")
        else:
            orgs = sorted({self.org(ev) for ev in week})
            keys = [f"org:{o}" for o in orgs]
            title, power = "미술관들, 새 시즌 개막", 1
            dek = f"{', '.join(orgs[:2])}" + (f" 등 {len(orgs)}곳" if len(orgs) > 2 else "") + f"에서 새 전시 {len(week)}개."
            points = []
            about = "이번 주 미술관·기관에서 새로 시작한 전시:"
        return dict(axis="기관", title=title, dek=dek, power=power, fact=". ".join(parts) + ".", read=read,
                    items=[self.link(ev) for ev in (week + acq)[:3]], keys=keys if not acq else [f"acq:{holder}"],
                    about=about, evs=[] if acq else week[:4], points=points)

    def artists_axis(self, stories: Optional[List[dict]] = None) -> Optional[dict]:
        """Artists seen through two or more independent channels in the window: different exhibition sources and/or press stories."""
        lo, hi = self.d - dt.timedelta(days=30), self.d + dt.timedelta(days=30)
        seen: Dict[str, set] = collections.defaultdict(set)
        names = {}
        for ev in self.events:
            s, e = day(ev["start_date"]), day(ev["end_date"]) or day(ev["start_date"])
            if not s or e < lo or s > hi:
                continue
            for eid, nm in self.artists(ev):
                seen[eid].add(("전시", ev["source_id"]))
                names[eid] = nm
        best_story: Dict[str, dict] = {}
        for st in stories or []:
            for nm, eid in st.get("names") or []:
                if eid and (self.vb.entities.get(eid) or {}).get("entity_type") in ("person", "artist", "group"):
                    for o in st["outlets"]:
                        seen[eid].add(("보도", o))
                    names.setdefault(eid, nm)
                    if len(st["outlets"]) > len((best_story.get(eid) or {}).get("outlets", [])):
                        best_story[eid] = st
        from . import editorial
        winners = {w["name"] for a in (editorial.load_notes_upto(self.d).get("awards") or {}).values()
                   if a.get("edition_region") == self.E and a.get("track") != "excluded" for w in a.get("winners", [])}
        for st in stories or []:
            text = " ".join(m.get("title") or "" for m in st["members"])
            for nm in winners:
                if len(nm) >= 3 and nm in text:
                    eid = (self.vb.find_entity(nm) if hasattr(self.vb, "find_entity") else None) or f"name:{nm}"
                    if any(e == eid for _, e in st.get("names") or []):
                        continue
                    for o in st["outlets"]:
                        seen[eid].add(("보도", o))
                    names.setdefault(eid, nm)
                    if len(st["outlets"]) > len((best_story.get(eid) or {}).get("outlets", [])):
                        best_story[eid] = st
        self._top_artist = None
        multi = [(eid, ch) for eid, ch in seen.items() if len(ch) >= 2 or sum(k == "보도" for k, _ in ch) >= 2]
        if not multi:
            return None
        both = [x for x in multi if {k for k, _ in x[1]} == {"전시", "보도"}]
        multi.sort(key=lambda x: -(len(x[1]) + 5 * (x in both)))
        def label(eid, ch):
            k = collections.Counter(a for a, _ in ch)
            return (names[eid] if eid.startswith("name:") else self.vb.entity_link(eid, names[eid])) + "(" + " · ".join(f"{a} {n}" for a, n in k.items()) + ")"
        fact = (f"서로 다른 경로 2곳 이상에서 동시에 보이는 작가 {len(multi)}명(전시 ±30일·보도 7일) — 전시와 보도에 함께 나온 작가 {len(both)}명. "
                + ", ".join(label(eid, ch) for eid, ch in multi[:5]))
        read = ("한 작가가 여러 기관·매체에서 동시에 보이는 것은 Blueprint A축 '다른 주체 확인' 신호다 — 전시와 보도에 함께 나온 작가부터 작가 포커스(H02) 후보로 본다."
                if both else "여러 기관이 같은 작가를 동시에 전시한다 — 순회전·단체전 중복인지 확인한 뒤 작가 포커스(H02) 후보로 본다.")
        self.people = [dict(entity_id=None if eid.startswith("name:") else eid, name=names[eid],
                            press=sum(c == "보도" for c, _ in ch), shows=sum(c == "전시" for c, _ in ch),
                            story=(best_story.get(eid) or {}).get("lead", {}).get("title"),
                            story_url=(best_story.get(eid) or {}).get("lead", {}).get("canonical_url"))
                       for eid, ch in multi[:12]]
        top_eid, top_ch = multi[0]
        self._top_artist, self._names = top_eid, names
        k = collections.Counter(a for a, _ in top_ch)
        nm = names[top_eid]
        st = best_story.get(top_eid)
        shows = [ev for ev in self.events if any(e == top_eid for e, _ in self.artists(ev))
                 and (day(ev["end_date"]) or day(ev["start_date"]) or dt.date.min) >= self.d]
        if k["보도"] >= 10 or (top_eid in [e for e, _ in both] and k["보도"] >= 3):
            title, power = f"{nm}, 이번 주 가장 많이 불린 이름", 3
        else:
            title, power = f"{nm}, 전시장과 뉴스에 동시 등장" if k["보도"] and k["전시"] else f"{nm}, 여러 무대에 동시 등장", 2
        points = []
        if st:
            kt = FEED_PREFIX.sub("", self.ko_title(st["lead"]))
            dek = ("화제의 기사: ‘" + short(kt, 44) + "’." if re.search(r"[가-힣]", kt)
                   else (("지금 전시 중이고, 해외 매체도 주목했다." if k["전시"] == 1 else f"{k['전시']}곳에서 전시 중이고, 해외 매체도 주목했다.") if k["전시"] else "해외 매체가 연이어 다뤘다."))
        else:
            dek = f"서로 다른 기관 {k['전시']}곳에서 동시에 전시 중."
        if shows:
            ev = shows[0]
            end = day(ev["end_date"])
            points.append(f"지금 볼 수 있는 곳: {self.org(ev)} 《{short(ev['title'], 30)}》" + (f", {end.month}월 {end.day}일까지" if end else ""))
        sw = self.so_what(st)
        if sw:
            points.append(sw)
        others = [names[e] for e, _ in multi[1:4]]
        if others and not sw:
            points.append(f"함께 오른 이름: {', '.join(others)}")
        desc = self.who(None if top_eid.startswith("name:") else top_eid)
        about = f"{nm}" + (f"({desc})" if desc else "") + " — 관련 전시와 기사:"
        arts = [m for m in (st or {}).get("members", [])[:2]] if st else []
        recent = [ev for ev in self.events if any(e == top_eid for e, _ in self.artists(ev))
                  and (day(ev["end_date"]) or day(ev["start_date"]) or dt.date.min) >= self.d - dt.timedelta(days=30)]
        shows = shows or sorted(recent, key=lambda ev: ev["start_date"] or "", reverse=True)
        return dict(axis="작가", title=title, dek=dek, power=power, fact=fact + ".", read=read, items=[],
                    about=about, evs=shows[:2], arts=arts, points=points)

    def criticism(self) -> Optional[dict]:
        lo, hi = self.week
        rows = [a for a in self.vb.reading(self.E, lo, hi) + (self.vb.reading("GLOBAL", lo, hi) if self.E in ("AMERICAS", "EUROPE") else [])
                if a.get("article_type") in ("review", "criticism", "interview")]
        if not rows:
            return None
        kinds = collections.Counter(a["article_type"] for a in rows)
        outlets = collections.Counter(self.vb.source_label(a, bare=True) for a in rows)
        fact = (f"비평·리뷰·인터뷰 {len(rows)}건(최근 7일) — " + ", ".join(f"{k} {v}" for k, v in kinds.most_common())
                + " · 매체 " + ", ".join(f"{o} {k}" for o, k in outlets.most_common(3)))
        read = "같은 전시·작가에 서로 다른 매체의 글이 2개 이상 모이면 '비평의 관점'으로 묶는다. 이번 주 글 목록은 4장 '글로벌 비평'."
        items = [f"[{(a['title'] or '')[:60]}]({a['canonical_url']})" for a in rows[:3]]
        subj = collections.Counter(nm for a in rows for nm, eid in self.find_names(a["title"])
                                   if (self.vb.entities.get(eid) or {}).get("entity_type") in ("person", "artist", "group"))
        top, n = (subj.most_common(1)[0] if subj else (None, 0))
        lead_outlet, lead_n = outlets.most_common(1)[0]
        if top and n >= 2:
            title, power = f"비평가들, 일제히 {josa(top, '을를')} 봤다", 3
            dek = f"이번 주 리뷰·비평 {n}편이 같은 작가를 다뤘다."
        else:
            named = [nm for nm, _ in subj.most_common(3)]
            if named:
                title, power = f"이번 주 비평이 꺼낸 이름: {', '.join(named[:2])}", 1
            else:
                title, power = f"비평 {len(rows)}편, 한 전시로 모이지 않았다", 1
            dek = f"리뷰·비평 {len(rows)}편, 한 전시로 모이진 않았다 — 관심이 흩어진 주." if named else "관심이 흩어진 주 — 먼저 읽을 글은 '자세히'에."
        return dict(axis="비평", title=title, dek=dek, power=power, fact=fact + ".", read=read, items=items,
                    about="먼저 읽을 글:", arts=rows[:4], points=[])

    def rookie(self) -> Optional[dict]:
        lo, hi = self.d - dt.timedelta(days=30), self.d + dt.timedelta(days=60)
        evs = [ev for ev in self.events if ev["event_type"] in ROOKIE_TYPES
               and (s := day(ev["announced_date"] or ev["start_date"])) and lo <= s <= hi]
        from . import editorial
        aw = [a for a in (editorial.load_notes_upto(self.d).get("awards") or {}).values() if a.get("edition_region") == self.E]
        if not evs and not aw:
            return None
        parts = []
        if aw:
            tracks = collections.Counter(a.get("track") for a in aw)
            parts.append(f"판단한 수상·선정 {len(aw)}건(최근 30일) — 신진 대상 {tracks['rookie']} · 경력 무관 {tracks['open']} · 기성 {tracks['established']}"
                         + (f" · 후보 단계 {tracks['shortlist']}" if tracks["shortlist"] else ""))
        if evs:
            parts.append(f"기관 공식 공모·레지던시 선정 {len(evs)}건 — " + ", ".join(sorted({self.org(ev) for ev in evs})[:3]))
        read = "신진 발굴 경로가 어디서 열리는지 본다 — 상세 판단은 홈의 ROOKIE RADAR."
        rk = [a for a in aw if a.get("track") == "rookie"]
        firsts = [(a["award"], w["name"]) for a in sorted(rk, key=lambda a: a.get("date") or "", reverse=True) for w in a.get("winners", [])[:1]]
        if len(rk) >= 3 and len(firsts) >= 2:
            title, power = f"신진상 시즌 개막 — 첫 수상자는 {firsts[0][1]}·{firsts[1][1]}", 2
            dek = f"한 달 새 신진 대상 상 {len(rk)}개가 수상자를 냈다."
            points = ["상보다 중요한 건 다음 무대(개인전·레지던시)를 누가 얻느냐."]
        elif len(rk) >= 3:
            title, power = "신진 작가상 시즌 시작", 2
            dek = f"한 달 새 신진 대상 상 {len(rk)}개가 수상자를 냈다."
            points = ["누가, 왜 받았는지는 아래 ROOKIE RADAR에."]
        elif rk or evs:
            hosts = [a["award"] for a in rk[:2]] + [short_org(self.org(ev)) for ev in evs[:1]]
            title, power = f"{hosts[0]}, 신진 작가 선정 진행 중", 1
            dek = "누가 뽑히는지, 그 다음 무대는 어디인지 — ROOKIE RADAR에서 이어서 본다."
            points = []
        else:
            title, power = "이번 달 상은 기성 작가 몫", 1
            dek = "신진 작가 대상 수상 소식은 없었다."
            points = []
        lines = [f"{a['award']} — {', '.join(w['name'] for w in a.get('winners', [])[:3])}"
                 + (": " + short(CHECK_NOTE.sub("", a["winners"][0]["why"]), 90) if a.get("winners") and a["winners"][0].get("why") else "")
                 for a in sorted(rk, key=lambda a: a.get("date") or "", reverse=True)[:4] if a.get("winners")]
        return dict(axis="수상·루키", title=title, dek=dek, power=power, fact=". ".join(parts) + ".", read=read, items=[self.link(ev) for ev in evs[:2]],
                    about="최근 한 달 신진 대상 상과 수상자:" if lines else "", lines=lines, evs=[] if lines else evs[:2], points=points)

    def market(self) -> Optional[dict]:
        lo, hi = self.d - dt.timedelta(days=3), self.d + dt.timedelta(days=21)
        fairs = [ev for ev in self.events if ev["event_type"] in ("fair_edition", "biennial_edition")
                 and (s := day(ev["start_date"])) and (e := day(ev["end_date"]) or s) and e >= lo and s <= hi]
        if not fairs:
            return None
        now = [ev for ev in fairs if day(ev["start_date"]) <= self.d <= (day(ev["end_date"]) or day(ev["start_date"]))]
        soon = [ev for ev in fairs if day(ev["start_date"]) > self.d]
        fact = ("진행 중 " + (", ".join(f"{self.link(ev)}(~{ev['end_date'][5:]})" for ev in now) or "없음")
                + " · 3주 안 개막 " + (", ".join(f"{self.link(ev)}({ev['start_date'][5:]})" for ev in soon) or "없음"))
        read = "아트페어·비엔날레 주간에는 갤러리 개막·신진상·판매 보도가 같이 늘어난다 — 판매 보도는 가격을 예술적 가치로 쓰지 않는다(Blueprint)."
        if soon:
            ev = soon[0]
            n_days = (day(ev["start_date"]) - self.d).days
            title, power = f"{short(ev['title'], 30)}, 개막 D-{n_days}", 2
            dek = f"{self.when(ev)}" + (f", {city_ko(ev['city'])}" if ev.get("city") else "") + "."
            points = ["페어 주간엔 갤러리 발표·신진상 소식이 몰린다."]
        else:
            ev = min(now, key=lambda e: day(e["end_date"]) or self.d)
            left = ((day(ev["end_date"]) or self.d) - self.d).days
            if left <= 21:
                title, power = f"{short(ev['title'], 30)}, 폐막 D-{left}", 2
                dek = "막바지 관람·리뷰가 몰리는 구간."
                points = []
            else:
                title, power = f"{short(ev['title'], 30)}, {day(ev['end_date']).month}월 {day(ev['end_date']).day}일까지", 1
                dek = "진행 중인 대형 행사 — 관련 전시·리뷰가 이어진다."
                points = []
        return dict(axis="페어·비엔날레", title=title, dek=dek, power=power, fact=fact + ".", read=read, items=[],
                    keys=["fair"] if soon else [], about="진행 중이거나 3주 안에 열리는 페어·비엔날레:", evs=(now + soon)[:4], points=points)

    def press(self, stories: List[dict]) -> Optional[dict]:
        if not stories:
            return None
        n_art = sum(len(s["members"]) for s in stories)
        topics = collections.Counter(s["topic_label"] for s in stories)
        fact = (f"기사 {n_art:,}건 → 같은 소식 묶음 {len(stories):,}개(최근 7일) — "
                + ", ".join(f"{k} {v}" for k, v in topics.most_common(3)))
        used = getattr(self, "_top_artist", None)
        used_name = (self._names.get(used) if used else None) or ""
        pool = [s for s in stories if not any(eid == used for _, eid in s.get("names") or [])
                and not (used_name and any(used_name in (m.get("title") or "") for m in s["members"]))] or stories
        recent = [s for s in pool if (day(s["lead"].get("published_at")) or dt.date.min) >= self.d - dt.timedelta(days=1)]
        reach = lambda s: len({self.vb.source_label(m, bare=True) for m in same_story(s)}) if hasattr(self.vb, "source_label") else len(s["outlets"])
        hot = max(recent or pool, key=reach)
        n_out = reach(hot)  # outlets that told this story, not the neighbouring releases the cluster glued on
        power = 3 if n_out >= 10 else 2 if n_out >= 4 else 1
        if n_out >= 3:
            title = short(self.ko_title(hot["lead"]), 60)
            sw = self.so_what(hot)
            dek = sw or f"{'이틀 사이' if recent else '이번 주'} 가장 넓게 퍼진 {hot.get('topic_label') or ''} 소식."
        else:
            title = "이번 주, 크게 터진 뉴스는 없었다"
            dek = "대신 전시·수상 쪽 흐름을 위에서 짚었다."
        return dict(axis="보도", title=title, dek=dek, power=power, fact=fact + ".", keys=[f"story:{hot['lead'].get('article_id')}"],
                    read="화제성(보도 확산)은 중요도와 다르다 — 중요도는 아래 '주요 소식'의 기준 판정을 본다.", items=[],
                    about="관련 기사:", arts=same_story(hot)[:3], points=[])

    def note_of(self, story: Optional[dict]) -> dict:
        if not hasattr(self, "_notes"):
            self.so_what({"lead": {}, "members": []})  # builds the URL -> note map
        for m in [(story or {}).get("lead") or {}] + list((story or {}).get("members") or []):
            n = self._notes.get(m.get("canonical_url") or "")
            if n:
                return n
        return {}

    def period_of(self, name: str) -> str:
        """Where and until when the subject is on view in this edition, from collected events."""
        best = None
        for ev in self.events:
            if ev["event_type"] not in SHOW_TYPES:
                continue
            end = day(ev["end_date"])
            if not end or end < self.d or (end - (day(ev["start_date"]) or end)).days > 400:
                continue
            if name in (ev["title"] or "") or any(nm == name for _, nm in self.artists(ev)):
                if best is None or end < day(best["end_date"]):
                    best = ev
        if not best:
            return ""
        end = day(best["end_date"])
        return f"{self.org(best)}에서 {end.month}월 {end.day}일까지 열린다."

    def buzz(self, stories: Optional[List[dict]] = None) -> List[dict]:
        """What people are talking about and why: a first appearance, a crowd, a record, a prize — named, placed, read."""
        from . import buzz as bz
        vb = self.vb
        titles = lambda st: [m.get("title") or "" for m in st["members"]]
        hangul = lambda st: len(re.findall(r"[가-힣]", " ".join(titles(st)))) > 5
        own = list(stories or []) if self.E == "KR" else [st for st in stories or [] if not hangul(st)]
        pool = [st for st in own if (bz.route(titles(st)) or self.E) == self.E]
        if self.E != "KR" and hasattr(vb, "stories"):  # Korean press on shows abroad belongs to the venue's edition
            cache = vb.__dict__.setdefault("_kr_week", {})
            key = (self.week[0], self.d)
            if key not in cache:
                cache[key] = vb.stories("KR", self.week[0], self.d, self.d)
            pool += [st for st in cache[key] if bz.route(titles(st)) == self.E]
        if not pool:
            return []
        if not hasattr(vb, "_venue_names"):
            vb._venue_names = [e["canonical_name"] for e in vb.entities.values()
                               if e.get("entity_type") in ("museum", "institution", "gallery", "foundation", "venue")]
        person = lambda eid: (vb.entities.get(eid) or {}).get("entity_type") in ("person", "artist", "group")
        out = []
        for x in bz.rank(pool, person, vb._venue_names, (self.d - dt.timedelta(days=1)).isoformat(), 3):
            a, st = x["a"], x["story"]
            nv = self.note_of(st)
            c = bz.compose(a, x["outlets"], period=self.period_of(a["name"]), note=(nv.get("brief") or "") if nv else "")
            wide = "first" in a["slots"] and (a["stature"] or a["desc"] or a["slots"]["first"].split()[0] in bz.WIDE_SCOPE)
            strong = {"heat", "record"} & set(a["slots"]) or wide
            if x["outlets"] >= 3 and (strong or x["outlets"] >= 10) or (strong and a["stature"]):
                power = 3
            elif strong or x["outlets"] >= 3:
                power = 2
            else:
                power = 1  # a regional first or a one-outlet prize: kept, but below the measured headlines
            lead = st["lead"]
            fact = (f"보도 {x['outlets']}곳(최근 7일) — 근거 헤드라인: ‘{bz.clean(lead.get('title'))[:70]}’"
                    + (f"({lead.get('publisher')})" if lead.get("publisher") else ""))
            keys = [f"name:{a['name']}", f"story:{lead.get('article_id')}"] + ([f"artist:{a['eid']}"] if a["eid"] else [])
            desc = self.who(a["eid"])
            about = f"{a['name']}" + (f"({desc})" if desc else "") + " — 관련 기사:"
            show = [ev for ev in self.events if ev["event_type"] in SHOW_TYPES and (day(ev["end_date"]) or dt.date.min) >= self.d
                    and (a["name"] in (ev["title"] or "") or any(nm == a["name"] for _, nm in self.artists(ev)))][:1]
            pub = sorted(((m.get("published_at") or "")[:10] for m in st["members"]), reverse=True)
            latest = pub[1] if len(pub) >= 2 else (pub[0] if pub else None)  # one late rewrite is not a new development
            out.append(dict(axis="화제", title=c["title"], dek=c["dek"], power=power, fact=fact + ".", keys=keys, latest=latest, points=c["points"],
                            about=about, arts=same_story(st)[:3], evs=show,
                            items=[f"[{bz.clean(lead.get('title'))[:60]}]({lead.get('canonical_url')})"] if lead.get("canonical_url") else [],
                            read="보도 제목에서 '첫 공개·관객·기록·수상' 단서를 읽어 다시 쓴 헤드라인이다 — 관객 수와 가격은 관심과 시장의 온도이지 예술적 가치가 아니다."))
        return out

    def critic_rows(self) -> List[dict]:
        lo, hi = self.week
        return [a for a in self.vb.reading(self.E, lo, hi) + (self.vb.reading("GLOBAL", lo, hi) if self.E in ("AMERICAS", "EUROPE") else [])
                if a.get("article_type") in ("review", "criticism", "interview")]

    def themes(self, stories: Optional[List[dict]] = None) -> List[dict]:
        """What the week is about: one subject surfacing across shows, press and criticism from different carriers."""
        hits: Dict[str, dict] = collections.defaultdict(lambda: dict(items=[], who=set(), axes=collections.Counter(), links=[], order=[], evs=[]))

        def feed(axis, text, who, label, link=None, ev=None):
            for key, rx in THEME_RX.items():
                if rx.search(text or ""):
                    h = hits[key]
                    if label in (x for _, x in h["items"]):
                        continue
                    h["items"].append((axis, label))
                    h["order"].append(who)
                    h["who"].add(who)
                    h["axes"][axis] += 1
                    if link:
                        h["links"].append(link)
                    if ev is not None:
                        h["evs"].append(ev)

        for ev in self.opened(self.week[0], self.d + dt.timedelta(days=14)):
            feed("전시", f"{ev['title']} {ev.get('description_excerpt') or ''}", self.org(ev),
                 f"《{short(ev['title'], 28)}》({self.org(ev)})", self.link(ev), ev)
        for st in stories or []:
            if len(st.get("outlets") or []) < 2:  # a single-outlet item is not a shared subject
                continue
            text = " ".join(m.get("title") or "" for m in st["members"][:5])
            feed("보도", text, "story:" + str(st["lead"].get("article_id") or st["lead"].get("title")), f"‘{short(st['lead'].get('title'), 28)}’")
        for a in self.critic_rows():
            feed("비평", a.get("title"), "critic:" + str(a.get("source_id")), f"‘{short(a.get('title'), 28)}’")
        def shows(h):
            return {w for (ax, _), w in zip(h["items"], h["order"]) if ax == "전시"}

        good = []
        for k, h in hits.items():
            n_show, n_crit = len(shows(h)), h["axes"]["비평"]
            if n_show >= 2:
                good.append((k, h))
        good.sort(key=lambda kh: (-len(shows(kh[1])), -len(kh[1]["axes"]), -len(kh[1]["who"])))
        out = []
        for key, h in good[:2]:
            label, claim, why = THEME_INFO[key]
            picks, seen_axes = [], set()
            for ax, lab in h["items"]:  # one example per axis first, then fill
                if ax not in seen_axes:
                    picks.append(lab)
                    seen_axes.add(ax)
            picks += [lab for _, lab in h["items"] if lab not in picks]
            n_axes = len(h["axes"])
            ax = h["axes"]
            count = " · ".join(x for x in (f"전시 {len(shows(h))}곳" if ax["전시"] else "", f"비평 {ax['비평']}편" if ax["비평"] else "",
                                           f"보도 {ax['보도']}건" if ax["보도"] else "") if x)
            dek = f"{', '.join(picks[:2])} — 같은 주, {count}이 같은 주제를 꺼냈다."
            claim = f"이번 주 전시 키워드: {label}"
            fact = (f"주제 '{label}' — " + " · ".join(f"{a} {n}" for a, n in h["axes"].items())
                    + f"건, 서로 다른 기관·소식 {len(h['who'])}곳(전시: 이번 주~2주 뒤 개막, 보도·비평: 최근 7일)")
            power = 3 if len(shows(h)) >= 3 or (len(shows(h)) >= 2 and n_axes >= 2) else 2
            kw = sorted({m.group(0) for ev in h["evs"] for m in [THEME_RX[key].search(f"{ev['title']} {ev.get('description_excerpt') or ''}")] if m})
            about = (f"같은 주에 서로 다른 전시장 {len(shows(h))}곳이 '{label}' 주제를 다루는 전시를 열었다"
                     + (f"(전시 제목·소개에 나온 말: {', '.join(kw[:4])})" if kw else "") + ". 어떤 전시인지:")
            out.append(dict(axis="주제", title=claim, dek=dek, power=power, fact=fact + ".", items=h["links"][:3], keys=[f"theme:{key}"],
                            about="어떤 전시인지:", evs=h["evs"][:4], points=[SHORT_WHY.get(key, why)],
                            read="키워드 기준 자동 판단이다 — 같은 단어가 다른 뜻으로 쓰였을 수 있으니 원문을 확인한 뒤 기사화한다."))
        return out

    def bridge(self) -> Optional[dict]:
        """An award or newcomer show on an institution's wall: the follow-up support step (Blueprint R05)."""
        evs = [ev for ev in self.opened(self.week[0], self.d + dt.timedelta(days=14)) if AWARD_SHOW.search(ev["title"] or "")]
        if not evs:
            return None
        evs.sort(key=lambda ev: (self.kind(ev) != MUSEUM, ev["start_date"]))
        ev = evs[0]
        arts = [nm for _, nm in self.artists(ev)]
        museum = self.kind(ev) == MUSEUM
        s = day(ev["start_date"])
        award, who = award_and_artist(ev["title"] or "", arts)
        org = short_org(self.org(ev))
        is_award = bool(re.search(r"award|prize|prix|preis|賞|상", award or "", re.I)) and not re.search(r"신진|new ?media|emerging", ev["title"] or "", re.I)
        opened = s <= self.d
        if is_award and who:
            title = f"{award} 받은 {who}, {org}서 개인전 " + ("개막" if opened else f"{s.month}월 {s.day}일 개막")
        elif is_award:
            title = f"{award} 수상작, {org}에 걸린다" + ("" if opened else f" — {s.month}월 {s.day}일")
        else:
            title = f"{org}, 신진 작가에게 첫 무대" + (f" — {'·'.join(arts[:2])}" if arts else "")
        show = f" · 《{short(ev['title'], 40)}》" if not is_award else ""
        dek = f"{self.when(ev)}{show}. " + ("상금보다 큰 보상, 미술관이라는 다음 무대." if is_award else "")
        dek = dek.strip()
        points = [] if is_award else ["기관이 직접 고른 신진 — 다음 행보는 아래 ROOKIE RADAR에서."]
        fact = "수상·신진 전시 " + ", ".join(f"{self.link(e)}({e['start_date'][5:]})" for e in evs[:4]) + "(이번 주~2주 뒤 개막)"
        about = (f"{self.org(ev)}" + (f"({city_ko(ev['city'])})" if ev.get("city") and city_ko(ev["city"]) not in self.org(ev) else "")
                 + f"에서 상·신진 작가 전시 《{short(ev['title'], 50)}》가 " + ("문을 열었다." if s <= self.d else f"{s.month}월 {s.day}일 문을 연다.") + (f" 참여 작가: {', '.join(arts[:6])}." if arts else " 참여 작가 명단은 기관 공지에서 확인한다."))
        return dict(axis="신진 경로", title=title, dek=dek, power=2, fact=fact + ".", items=[self.link(e) for e in evs[:3]], about=about, evs=evs[:3],
                    points=points,
                    keys=["bridge", f"org:{self.org(ev)}"],
                    read="제목에 상·신진 표기가 있는 전시만 잡는다 — 수상과 전시의 연결은 기관 공지로 확인한다.")

    def echo(self) -> Optional[dict]:
        """The same artist on view in another edition at the same time: two continents looking at one name."""
        lo, hi = self.d - dt.timedelta(days=7), self.d + dt.timedelta(days=30)
        where: Dict[str, dict] = collections.defaultdict(dict)
        orgs_of: Dict[str, set] = collections.defaultdict(set)
        names = {}
        for ev in self.vb.events.values():
            if ev["event_type"] not in SHOW_TYPES:
                continue
            s, e = day(ev["start_date"]), day(ev["end_date"]) or day(ev["start_date"])
            if not s or not e or e < lo or s > hi or (e - s).days > 400:
                continue
            arts = self.artists(ev)
            if not 0 < len(arts) <= 5:
                continue
            for eid, nm in arts:
                if (self.vb.entities.get(eid) or {}).get("entity_type") not in ("person", "artist"):
                    continue
                where[eid].setdefault(ev["edition_region"], ev)
                orgs_of[eid].add(self.org(ev))
                names[eid] = nm
        talked = self.press_names()
        cand = [(eid, eds) for eid, eds in where.items() if self.E in eds and len([e for e in eds if e != "OTHER"]) >= 2
                and len(orgs_of[eid]) >= 2]  # one gallery's branches are a gallery story, not two continents
        if not cand:
            return None
        cand.sort(key=lambda x: (-len(x[1]), x[0] not in talked, names[x[0]]))
        eid, eds = cand[0]
        home = eds[self.E]
        away = [ev for e, ev in eds.items() if e != self.E]
        city = lambda ev: city_ko(ev["city"]) or ev["edition_region"]
        cities = [city(home)] + [city(ev) for ev in away]
        title = f"{names[eid]}, {'·'.join(cities[:3])} 동시 전시"
        dek = "서로 다른 대륙이 같은 시기에 같은 작가를 본다."
        points = ["한쪽의 반응이 다른 쪽 수요로 번지는지 주목."]
        fact = (f"다른 에디션에서도 같은 시기에 전시 중인 작가 {len(cand)}명(지난 7일~30일 뒤, 참여 작가 5명 이하 전시) — "
                + ", ".join(f"{names[e]}({'·'.join(sorted(x))})" for e, x in cand[:5]))
        return dict(axis="교차", title=title, dek=dek, power=3 if len(eds) >= 3 else 2, fact=fact + ".",
                    items=[self.link(ev) for ev in [home] + away[:2]], keys=[f"artist:{eid}"], evs=[home] + away[:2], points=points,
                    about=f"{names[eid]}" + (f"({self.who(eid)})" if self.who(eid) else "") + "의 전시가 같은 시기에 여러 대륙에서 열리고 있다:",
                    read="같은 작가 표기로만 묶는다 — 동명이인과 순회전 여부를 확인한다.")

    def all(self, stories: Optional[List[dict]] = None) -> List[dict]:
        self._stories = stories or []
        artist = self.artists_axis(stories)  # first: the press headline skips the artist it already covers
        if artist and self._top_artist:
            artist["keys"] = [f"artist:{self._top_artist}", f"name:{self._names.get(self._top_artist)}"]
        talk = self.buzz(stories)
        if artist:  # the same person told by its hook replaces the 'most-named' line, at the stronger signal
            for b in talk:
                if set(b["keys"]) & set(artist.get("keys") or []):
                    b["power"] = max(b["power"], artist["power"])
        out = talk + [self.exhibitions(), self.galleries(), self.institutions(), artist, self.rookie(), self.bridge(),
                                    self.echo(), self.criticism(), self.market(), self.press(stories or [])] + self.themes(stories)
        out = [o for o in out if o]
        for o in out:
            dates = [(a.get("published_at") or "")[:10] for a in o.get("arts") or []] + \
                    [ev.get("start_date") or ev.get("announced_date") or "" for ev in o.get("evs") or []]
            dates = [x for x in dates if x and x <= self.d.isoformat()]
            o["latest"] = o.get("latest") or (max(dates) if dates else None)
            o.setdefault("points", [])
            o["points"] = [p for p in o["points"] if p and not COUNT_OUTLETS.search(p)]
            o["dek"] = COUNT_OUTLETS.sub("", o["dek"]).strip()
            o["ev_keys"] = [f"ev:{ev['event_id']}" for ev in o.get("evs") or [] if ev.get("event_id")][:2]
            o["what"] = (o.pop("lines", None) or []) + [self.ev_line(ev) for ev in o.pop("evs", None) or []] \
                + [self.art_line(a) for a in o.pop("arts", None) or []]
            if not o.get("about"):
                o["about"] = "관련 전시·기사:" if o["what"] else ""
        return out


TOP_HEADLINES = 5
POWER_LABEL = {3: "강한 신호", 2: "눈에 띄는 신호", 1: "참고"}


def trend_lines(vb, edition: str, d: dt.date, stories: Optional[List[dict]] = None) -> List[str]:
    """Magazine-style headlines (title + one-line dek), strongest signal first; numbers stay in a small evidence line."""
    tr = Trend(vb, edition, d)
    obs = headlines(vb, edition, d, stories, tr)
    if not obs:
        return ["> [!empty] 이 날짜에 수집된 데이터가 없습니다", "> 수집 공백이며 활동이 없다는 뜻이 아닙니다.", ""]
    from . import keywords
    kws = keywords.hot(vb, edition, d, getattr(tr, "people", []))
    if kws:
        lines = ["**이번 주 키워드** " + " ".join("#" + k["label"].replace(" ", "").replace("·", "_") for k in kws), "",
                 "> [!abstract]- 키워드 근거 (지난 4주 대비 이번 주에 뚜렷이 늘어난 미술 주제·행사·작가)"]
        for k in kws:
            ex = "; ".join(f"[{x['title'].replace('[', '(').replace(']', ')')}]({x['url']})" if x.get("url") else x["title"]
                           for x in k["examples"][:2])
            lines.append(f"> - **{k['label']}** ({k['kind']}) — {k['note']}" + (f" · {ex}" if ex else ""))
        lines.append("")
    else:
        lines = ["<small>이번 주 뚜렷하게 늘어난 키워드는 없습니다(수집량이 적거나 지난 4주와 비슷함).</small>", ""]
    for o in obs[:TOP_HEADLINES]:
        what = ([f"> {o['about']}"] if o.get("about") else []) + [f"> - {w}" for w in o.get("what") or []]
        pts = [f"- {p}" for p in o.get("points") or []]
        lines += [f"### {o['title']}", o["dek"], ""] + (pts + [""] if pts else []) + (["> [!info]- 무슨 일인가"] + what + [""] if what else []) + [
                  f"<small>{POWER_LABEL[o['power']]} · {o['axis']} · {o['fact']}" + (" · " + " · ".join(o["items"]) if o["items"] else "") + "</small>", ""]
    rest = obs[TOP_HEADLINES:]
    if rest:
        body = []
        for o in rest:
            body += [f"**{o['title']}** — {o['dek']}", f"<small>{o['axis']} · {o['fact']}</small>", ""]
        lines += ["> [!note]- 그 밖의 흐름"] + [f"> {x}" if x else ">" for x in body] + [""]
    lines.append("<small>헤드라인은 수집한 전시·갤러리·기관·작가·수상·비평·페어·보도 데이터를 규칙으로 읽은 자동 판단입니다. "
                 "신호 세기는 숫자 기준이며 예술적 가치 판단이 아닙니다. 각 줄 아래 작은 글씨가 근거입니다.</small>")
    return lines + [""]
