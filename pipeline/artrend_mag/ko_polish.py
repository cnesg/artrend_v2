"""Reader-facing handling of machine translations: prepare titles for the pivot, polish Korean, reject broken output.

The local models drop clauses after the first sentence, mangle katakana names and Japanese art terms, and answer in
the polite '합니다' register. Titles are therefore split into segments before translation, known art terms and names
are put in English for the pivot, and Korean output is normalized to headline style. A translation that lost the
original's numbers, Latin names or most of its length is not shown; the reader gets the original title instead.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

# -- pivot preparation (Japanese/European titles -> segments the models translate whole)

JA_TERMS = [  # longest first; English the pivot keeps, Korean the reader expects
    ("アートウィーク東京", "Art Week Tokyo"), ("アートコラボレーション京都", "Art Collaboration Kyoto"),
    ("釜山ビエンナーレ", "Busan Biennale"), ("光州ビエンナーレ", "Gwangju Biennale"), ("ヴェネチア・ビエンナーレ", "Venice Biennale"),
    ("ヴェネツィア・ビエンナーレ", "Venice Biennale"), ("ビエンナーレ", " Biennale"), ("トリエンナーレ", " Triennale"),
    ("アートフェア", "art fair"), ("アートフェスティバル", "art festival"), ("芸術祭", "art festival"),
    ("回顧展", "retrospective"), ("個展", "solo exhibition"), ("二科展", "Nika Exhibition"), ("美術手帖", "Bijutsu Techo"),
    ("森美術館", "Mori Art Museum"), ("国立新美術館", "The National Art Center, Tokyo"), ("東京都現代美術館", "Museum of Contemporary Art Tokyo"),
    ("金沢21世紀美術館", "21st Century Museum of Contemporary Art, Kanazawa"), ("国立西洋美術館", "National Museum of Western Art"),
    ("東京国立近代美術館", "National Museum of Modern Art, Tokyo"), ("東京国立博物館", "Tokyo National Museum"),
    ("アーティゾン美術館", "Artizon Museum"), ("国際芸術祭", "international art festival"), ("現代美術", "contemporary art"),
]

KANA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o", "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so", "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no", "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo", "ヤ": "ya", "ユ": "yu", "ヨ": "yo", "ラ": "ra", "リ": "ri",
    "ル": "ru", "レ": "re", "ロ": "ro", "ワ": "wa", "ヲ": "o", "ン": "n", "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge",
    "ゴ": "go", "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo", "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de",
    "ド": "do", "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo", "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe",
    "ポ": "po", "ヴ": "vu",
}
SMALL = {"ャ": "ya", "ュ": "yu", "ョ": "yo", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}
NAME_KANA = re.compile(r"[ァ-ヴー]+(?:[・=＝][ァ-ヴー]+)+")


def romanize_kana(s: str) -> str:
    """Katakana to Hepburn-like Latin, enough for the pivot to keep a foreign name as a name."""
    out, i = "", 0
    while i < len(s):
        ch, nx = s[i], s[i + 1] if i + 1 < len(s) else ""
        if ch == "ッ":
            nxt = KANA.get(nx, "")
            out += nxt[:1] if nxt else ""
        elif ch == "ー":
            pass
        elif nx in SMALL and ch in KANA:  # キャ kya, シャ sha, ティ ti, ファ fa, ウィ wi, トゥ tu
            base = KANA[ch]
            stem = "w" if ch == "ウ" else ("ts" if ch == "ツ" else base[:-1])
            if nx in "ャュョ" and base not in ("shi", "chi", "ji"):
                stem += "y"
            out += stem + SMALL[nx][-1]
            i += 1
        elif ch in KANA:
            out += KANA[ch]
        elif ch in SMALL:
            out += SMALL[ch]
        i += 1
    return out


def _name_to_latin(m: re.Match) -> str:
    return " ".join(romanize_kana(p).capitalize() for p in re.split(r"[・=＝]", m.group(0)) if p)


SEG_SPLIT = re.compile(r"(。|！|？|──|—|―|｜|\||\s:\s|\s;\s|;\s|：|…|\s-\s|\s–\s)")
QUOTE = re.compile(r"[「『“]([^」』”]{2,60})[」』”]")
JOIN = {"。": ". ", "！": "! ", "？": "? ", "──": " — ", "—": " — ", "―": " — ", "｜": " | ", "|": " | ", " : ": ": ", "：": ": ",
        " ; ": "; ", "; ": "; ", "…": "… ", " - ": " — ", " – ": " — "}


def prepare(text: str, lang: str) -> List[Tuple[str, str]]:
    """Split a title into (segment, joiner) pairs; Japanese art terms and katakana names are given to the pivot in English."""
    t = unicodedata.normalize("NFKC", text).strip()
    if lang == "ja":
        for ja, en in JA_TERMS:
            t = t.replace(unicodedata.normalize("NFKC", ja), en)
        t = NAME_KANA.sub(_name_to_latin, t)
        t = re.sub(r"([A-Za-z])(\d)", r"\1 \2", t)
        t = t.replace("×", " and ")
        t = QUOTE.sub(lambda m: "“" + m.group(1) + "”", t)
    parts = SEG_SPLIT.split(t)
    out: List[Tuple[str, str]] = []
    for i in range(0, len(parts), 2):
        seg = parts[i].strip()
        joiner = JOIN.get(parts[i + 1], " ") if i + 1 < len(parts) else ""
        if seg:
            out.append((seg, joiner))
        elif out and joiner:
            out[-1] = (out[-1][0], joiner)
    return out or [(t, "")]


def reassemble(pieces: List[str], joiners: List[str]) -> str:
    s = "".join(p.strip().rstrip(".") + j for p, j in zip(pieces, joiners)).strip()
    return re.sub(r"\s{2,}", " ", s).strip(" |—")


# -- Korean polish (headline register, spacing of numbers and units)

END = r"(?=[.!?…;:,\s]|$)"


def _b_final(m: re.Match) -> str:
    """줍니다 -> 준다, 합니다 -> 한다: a syllable closed by ㅂ before 니다 takes ㄴ in the plain register."""
    code = ord(m.group(1)) - 0xAC00
    return chr(0xAC00 + code - 17 + 4) + "다"  # final ㅂ (17) -> ㄴ (4)


ENDINGS = [
    (r"입니다", "이다"), (r"십시오", "라"), (r"습니다", "다"),
]
# common spacing slips of the MT models: '엽니 다', '볼 수있는', '머리를위한'
MT_SPACING = [
    (r"([가-힣])니 다(?=[.!?…\s]|$)", r"\1니다"),
    (r"(?<=[가-힣]) 수(있|없)", r" 수 \1"),
    (r"([을를])(위한|위해|통해|향한)", r"\1 \2"),
]
UNIT = r"(?:가지|편|월|일|년|개월|주|시|분|점|명|곳|개|회|번째|만|억|조|원|엔|달러|유로|파운드|위안|세|층|%)"


def polish(ko: Optional[str]) -> Optional[str]:
    if not ko:
        return ko
    t = ko
    for a, b in MT_SPACING:
        t = re.sub(a, b, t)
    for a, b in ENDINGS:
        t = re.sub(a + END, b, t)
    t = re.sub(r"([가-힣])니다" + END, lambda m: _b_final(m) if (ord(m.group(1)) - 0xAC00) % 28 == 17 else m.group(0), t)
    t = re.sub(r"(\d)\s+(?=" + UNIT + r")", r"\1", t)
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", t)
    t = re.sub(r"([A-Za-z0-9)])\s+(와|과|의|은|는|이|가|을|를|에서|에게|로|으로|도)(?=[\s,.]|$)", r"\1\2", t)
    t = re.sub(r"([A-Za-z])(\d{4})", r"\1 \2", t)
    t = re.sub(r"\s+([,.!?:;)])", r"\1", t)
    t = re.sub(r"([(])\s+", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


# -- plausibility gate

CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
DIGITS = re.compile(r"\d+")
LATIN_NAME = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")
LEVEL_NUM = {"万": 10 ** 4, "億": 10 ** 8, "兆": 10 ** 12}


def _cjk_len(s: str) -> int:
    return sum(1 for ch in s if not ch.isspace() and unicodedata.category(ch)[0] in "LN")


def plausible(original: str, ko: str, lang: Optional[str] = None) -> bool:
    """Reject output that dropped the original's numbers, its Latin names, or most of its content."""
    o = unicodedata.normalize("NFKC", original)
    if not ko or "⁇" in ko:
        return False
    k = ko.replace(",", "")
    nums_o = {n for n in DIGITS.findall(o.replace(",", "")) if len(n) >= 2}
    nums_k = set(DIGITS.findall(k))
    if nums_o - nums_k:
        # 500億円 → '500억 엔' keeps 500; '50억 엔' lost it. Units in words are fine only when the digits survived.
        return False
    if lang in ("ja", "zh", "zt"):
        names = {w for w in LATIN_NAME.findall(o) if w.lower() not in ("the", "and")}
        if names and sum(w.lower() in k.lower() for w in names) < max(1, len(names) // 2):
            return False
        if _cjk_len(k) < 0.45 * _cjk_len(o):
            return False
    else:
        if len(k) < 0.25 * len(o):
            return False
    if re.search(r"(\b\S{2,}\b)(?:\s+\1){2,}", k):  # stuttering output
        return False
    return True


def name_like(original: str) -> bool:
    """A short Latin title made of names ('Louis Eisner by Addis Goldman', 'Izumi KATO') reads better untranslated."""
    words = re.findall(r"[A-Za-zÀ-ÿ][\w'’.-]*", original)
    if not words or len(words) > 9 or CJK.search(original):
        return False
    lower = [w for w in words if w[0].islower() and w.lower() not in ("by", "and", "of", "the", "de", "et", "la", "le", "in", "at", "for", "with", "x")]
    return len(lower) < 2


def reader_ko(original: Optional[str], ko: Optional[str], lang: Optional[str] = None) -> Optional[str]:
    if not original or not ko or name_like(original):
        return None
    p = polish(ko)
    return p if plausible(original, p, lang) else None
