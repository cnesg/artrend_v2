"""Daily news digest: group headlines that report the same story, sort stories by an explainable score, file them by topic.

Adapted from the original v2v pipeline (`pipeline/importance.py`, read-only copy in work/tmp/v2v_src): stories are
title-similarity clusters, and the score is a sum of named reasons so the page can say why a story is on top. It is a
reading order for editors, not a judgement of importance, and it never feeds cards, signals or `publishable`.

Score (higher first), every point carries a reason label:
  + 2 per additional outlet that ran the same story (max 4 outlets counted)
  + 2 art-specialist outlet or official institution feed (general-news feeds and search results get 0)
  + 2 headline names an observed institution or an artist in this edition's current programme
  + 2 award, prize or selection news
  + 2 price or auction-result words in the headline, + 1 record words
  + 1 published on the report date
  - 1 Korean press-release-type headline (체험·축제·공모·협약·후원 …) with no observed name
"""
from __future__ import annotations

import collections
import re
from typing import Dict, Iterable, List, Optional, Sequence

_STRIP = re.compile(r"[^0-9a-z가-힣぀-ヿ一-鿿]+")
_EN_STOP = {"the", "a", "an", "of", "and", "to", "in", "at", "for", "on", "with", "by", "is", "as", "from", "its", "his",
            "her", "le", "la", "les", "de", "des", "du", "et", "un", "une", "à", "en", "au"}
LATIN_LANGS = {"en", "fr", "de", "es", "it", "pt", "nl"}

MONEY = re.compile(r"\d[\d,.]*\s*(억|만\s*(달러|파운드|유로|원)|조\s*원)|(?:US|HK)?[$£€]\s?\d[\d,.]*|"
                   r"\d+(\.\d+)?\s*(million|billion|mn|bn)\b|億円|万円", re.I)
RESULTS = re.compile(r"낙찰|sold for|sells for|fetche[sd]|hammer|auction results|sale total|realiz|realis|落札", re.I)
RECORD = re.compile(r"최고가|신기록|기록 경신|역대 최고|record|most expensive|priciest|最高額|史上最高", re.I)
AWARD = re.compile(r"수상|미술상|작가상|선정|수상자|award|prize|winner|shortlist|laureate|fellowship|受賞|大賞", re.I)
PR_KO = re.compile(r"체험|축제|공모|협약|위촉|기부|후원|봉사|꿈나무|어린이|교구|캠프|강좌|모집")

# Topic buckets, first match wins. Order matters: an auction story that mentions an exhibition is market news.
TOPICS = (
    ("market", "시장·경매·아트페어", re.compile(
        r"경매|옥션|낙찰|아트페어|키아프|kiaf|프리즈|컬렉터|미술시장|미술품 (감정|거래|시장)|auction|sotheby|christie|phillips|"
        r"art fair|frieze|art basel|collector|art market|sale|dealer|オークション|落札|アートフェア|コレクター|美術市場", re.I)),
    ("people", "수상·인물", re.compile(
        r"수상|미술상|작가상|선정|별세|타계|임명|취임|관장|감독|인터뷰|award|prize|winner|shortlist|dies|died|obituary|"
        r"appointed|named director|interview|est mort|meurt|décès|gestorben|murió|falleció|artiste|künstler|"
        r"受賞|大賞|死去|館長|就任|インタビュー", re.I)),
    ("policy", "기관·정책·제도", re.compile(
        r"문체부|정책|예산|법안|제도|인증|평가|표준|감정서|위작|반환|소송|노조|개관|재개관|휴관|이전|건립|"
        r"policy|funding|budget|lawsuit|restitution|repatriat|union|layoff|closes|reopen|new museum|opens|"
        r"文化庁|予算|開館|休館|返還|訴訟", re.I)),
    ("criticism", "비평·리뷰", re.compile(r"리뷰|비평|평론|review|critic|essay|in conversation|レビュー|批評|評論", re.I)),
    ("exhibition", "전시·프로그램", re.compile(
        r"전시|개인전|기획전|초대전|단체전|특별전|展|비엔날레|트리엔날레|개막|회고전|exhibition|show|retrospective|biennale|biennial|"
        r"triennial|survey|on view|installation|expo|exposition|ausstellung|exposición|muestra|mostra|展覧会|個展|企画展|芸術祭|回顧展", re.I)),
    # last resort: programme news of a museum/gallery with no stronger word ('아트 프로그램', '씨네토크')
    ("exhibition", "전시·프로그램", re.compile(r"미술관|갤러리|아트센터|museum|musée|museo|gallery|galerie|galería|美術館|ギャラリー|博物館", re.I)),
)
OTHER_TOPIC = ("other", "그 밖의 소식")
# Display order on the daily page.
TOPICS_ORDERED = tuple((k, l) for k, l, _ in (TOPICS[4], TOPICS[1], TOPICS[0], TOPICS[2], TOPICS[3])) + (OTHER_TOPIC,)
CRITICISM_TYPES = {"criticism", "review", "interview"}


def grams(title: Optional[str], lang: Optional[str]) -> set:
    """English-like titles: words + word bigrams; Korean/Japanese/other: character bigrams of letters only."""
    t = (title or "").lower()
    if (lang or "") in LATIN_LANGS:
        words = [w for w in re.findall(r"[0-9a-zà-ÿ']+", t) if w not in _EN_STOP]
        return set(words) | {f"{a}_{b}" for a, b in zip(words, words[1:])}
    s = _STRIP.sub("", t)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / max(len(a | b), 1)


def cluster(articles: Sequence[dict], threshold_latin: float = 0.34, threshold_cjk: float = 0.42) -> List[List[dict]]:
    """Single-link clustering within one language: an article joins the story whose closest member title is at least
    `threshold` similar. Inverted index on grams keeps it near-linear."""
    stories: List[List[dict]] = []
    member_grams: List[List[set]] = []
    index: Dict[tuple, set] = collections.defaultdict(set)
    for a in sorted(articles, key=lambda x: (x.get("published_at") or "", x.get("article_id") or "")):
        lang = a.get("lang") or ""
        g = grams(a.get("title"), lang)
        if not g:
            stories.append([a]); member_grams.append([g])
            continue
        thr = threshold_latin if lang in LATIN_LANGS else threshold_cjk
        candidates = set()
        for x in g:
            candidates |= index.get((lang, x), set())
        best, best_score = None, 0.0
        for ci in candidates:
            for h in member_grams[ci]:
                s = jaccard(g, h)
                if s > best_score:
                    best, best_score = ci, s
        if best is not None and best_score >= thr:
            ci = best
            stories[ci].append(a); member_grams[ci].append(g)
        else:
            ci = len(stories)
            stories.append([a]); member_grams.append([g])
        for x in g:
            index[(lang, x)].add(ci)
    return stories


def outlet_of(a: dict) -> str:
    return (a.get("publisher") or a.get("source_id") or "?").strip().lower()


def topic_of(a: dict) -> tuple:
    if (a.get("article_type") or "") in CRITICISM_TYPES:
        return TOPICS[3][:2]
    text = f"{a.get('title') or ''} {a.get('categories') or ''}"
    for key, label, pattern in TOPICS:
        if pattern.search(text):
            return key, label
    return OTHER_TOPIC


class NameMatcher:
    """Finds observed names in headlines. Hangul/kana/kanji names (>= 3 chars) match as substrings; Latin names
    (>= 6 chars, at least two words or one long word) match on word boundaries, case-insensitive."""

    def __init__(self, names: Dict[str, str]):
        self.cjk: Dict[str, str] = {}
        latin: Dict[str, str] = {}
        for name, eid in names.items():
            n = (name or "").strip()
            if re.search(r"[가-힣぀-ヿ一-鿿]", n):
                if len(n) >= 3:
                    self.cjk[n] = eid
            elif len(n) >= 6 and (" " in n or len(n) >= 8):
                latin[n.lower()] = eid
        self.latin = latin
        self.latin_re = (re.compile(r"(?<![\w])(" + "|".join(re.escape(x) for x in sorted(latin, key=len, reverse=True)) + r")(?![\w])", re.I)
                         if latin else None)

    def find(self, title: Optional[str]) -> List[tuple]:
        t = title or ""
        out, seen = [], set()
        for name, eid in self.cjk.items():
            if name in t and eid not in seen:
                out.append((name, eid)); seen.add(eid)
        if self.latin_re:
            for m in self.latin_re.finditer(t):
                eid = self.latin[m.group(1).lower()]
                if eid not in seen:
                    out.append((m.group(1), eid)); seen.add(eid)
        return out


def score(a: dict, n_outlets: int, specialist: bool, names: Sequence[tuple], report_day: str) -> tuple:
    title = a.get("title") or ""
    reasons, points = [], 0
    if n_outlets > 1:
        extra = min(n_outlets, 4) - 1
        points += 2 * extra
        reasons.append(f"{n_outlets}개 매체 보도")
    if specialist:
        points += 2
        reasons.append("미술 전문 매체·기관")
    if names:
        points += 2
        reasons.append("관찰 대상 언급: " + ", ".join(n for n, _ in names[:2]))
    if AWARD.search(title):
        points += 2
        reasons.append("수상·선정")
    if MONEY.search(title) or RESULTS.search(title):
        points += 2
        reasons.append("가격·경매 결과")
    if RECORD.search(title):
        points += 1
        reasons.append("기록")
    if (a.get("published_at") or "")[:10] == report_day:
        points += 1
        reasons.append("당일 기사")
    if (a.get("lang") == "ko") and not names and PR_KO.search(title):
        points -= 1
        reasons.append("보도자료성(−1)")
    return points, reasons


def build_stories(articles: Iterable[dict], is_specialist, matcher: Optional[NameMatcher], report_day: str) -> List[dict]:
    """-> stories sorted by (score, outlets, newest). Each story: lead article, members, outlets, score, reasons, topic."""
    out = []
    for members in cluster(list(articles)):
        outlets = sorted({outlet_of(a) for a in members})
        best = None
        for a in members:
            names = matcher.find(a.get("title")) if matcher else []
            pts, why = score(a, len(outlets), is_specialist(a), names, report_day)
            key = (pts, is_specialist(a), not (a.get("title") or "").rstrip().endswith(("...", "…")), a.get("published_at") or "")
            if best is None or key > best[0]:
                best = (key, pts, why, a, names)
        _, pts, why, lead, names = best
        key, label = topic_of(lead)
        out.append(dict(lead=lead, members=members, outlets=outlets, score=pts, reasons=why, names=names,
                        topic=key, topic_label=label))
    out.sort(key=lambda s: (s["lead"].get("published_at") or "", s["lead"].get("article_id") or ""), reverse=True)
    out.sort(key=lambda s: (-s["score"], -len(s["outlets"])))
    return out
