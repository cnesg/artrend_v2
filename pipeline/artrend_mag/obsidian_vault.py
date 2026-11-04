"""Build an Obsidian vault (plain Markdown + YAML front matter + wikilinks) from the collected DB.

  python -m artrend_mag.cli vault [--asof 2026-10-29] [--days 7] [--out outputs/ARTREND_Obsidian_Vault]

The vault is a read-only *view* of db/artrend_magazine.sqlite and db/auction_normalized.sqlite. It never
fetches anything, never embeds images, keeps originals next to every automatic Korean translation, and marks
every daily-insight page and evidence card as an unreviewed internal draft (publishable=0).
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import shutil
import sqlite3
import statistics
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import ko_polish, news_digest
from .config import DB_PATH, WORK_ROOT

EDITIONS = ("KR", "JP", "AMERICAS", "EUROPE", "OTHER")
EDITION_KO = {"KR": "한국", "JP": "일본", "AMERICAS": "미주", "EUROPE": "유럽", "OTHER": "기타", None: "미지정"}
# Article sources are mapped to an edition by the source's declared region scope; GLOBAL criticism is shown on
# every edition page as its own block, never attributed to a region.
ARTICLE_SCOPE_EDITION = {"KR": "KR", "JP": "JP", "AMERICAS": "AMERICAS", "EUROPE": "EUROPE", "ASIA": "OTHER"}
PERSON_TYPES = {"person", "artist", "group"}
ORG_FOLDER = {"gallery": "갤러리", "institution": "기관", "museum": "기관", "foundation": "재단", "fair": "아트페어",
              "biennial": "비엔날레", "venue": "공간", "unknown": "미분류"}
EVENT_TYPE_KO = {"exhibition": "전시", "acquisition": "소장품 수집", "award": "시상", "biennial_edition": "비엔날레",
                 "fair_edition": "아트페어", "open_call_selection": "공모 선정", "program": "프로그램",
                 "publication": "출판", "residency": "레지던시"}
SHOWING_TYPES = {"exhibition", "biennial_edition", "fair_edition", "program"}
ROOKIE_TYPES = {"award", "open_call_selection", "residency"}
# Kept across rebuilds: Obsidian settings/plugins and the reader's own notes.
USER_OWNED = (".obsidian", "99_내메모")
# Never surfaced as reading material: undated legacy gallery news (permission-restricted feeds are excluded by state).
READING_EXCLUDED_SOURCES = {"legacy_gallery_news_202608"}
# The original v2v news DB (Naver/Google News metadata up to 2026-10-19) mixes regions; its language decides the block.
LEGACY_NEWS_SOURCE = "legacy_v2v_artnews"
LEGACY_NEWS_LANG_SCOPE = {"ko": "KR", "ja": "JP"}
NAVER_SOURCE = "kr_naver_news_api"
WEEKDAY_KO = "월화수목금토일"
TOP_STORIES = 8
PER_TOPIC = 5
TOPIC_ORDER = news_digest.TOPICS_ORDERED
TOPIC_LABEL = dict(TOPIC_ORDER)
SCORE_RULES = [
    "같은 소식을 다룬 기사(제목 유사도)를 하나로 묶고, 묶음마다 대표 기사 1건을 점수순으로 보여 줍니다. 최근 2일 소식이 먼저입니다.",
    "",
    "- +2 × (같은 소식을 다룬 매체 수 − 1, 최대 4곳까지)",
    "- +2 미술 전문 매체·기관 공식 채널 (일반지 RSS·Naver 검색·원본 수집 기사는 0)",
    "- +2 제목에 관찰 중인 기관·갤러리, 또는 이 에디션 최근 12개월 전시 참여 작가 이름",
    "- +2 수상·선정 · +2 가격·경매 결과 · +1 기록",
    "- +1 기준일 당일 기사 · −1 관찰 대상이 없는 국내 보도자료성 제목(체험·축제·공모·협약·후원 등)",
    "",
    "점수는 읽는 순서를 정하는 규칙일 뿐 중요도 판단이 아닙니다. 이름이 같아도 같은 사람·기관으로 확정하지 않습니다.",
]
DRAFT_CALLOUT = ("> [!warning] 내부 샘플 · 자동 생성 초안 · `publishable=0`\n"
                 "> 수집 데이터로 만든 열람용 페이지입니다. 사실·권리·신원·번역을 편집자가 원문으로 확인하기 전에는 게시하지 않습니다.\n")
TRANSLATION_NOTE = "자동번역·검수 전"

_BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')


# ----------------------------------------------------------------------------------------------- text helpers
def clean_name(text: Optional[str], limit: int = 80) -> str:
    base = re.sub(r"\s+", " ", _BAD_NAME.sub(" ", text or "")).strip().rstrip(". ")
    return base[:limit].rstrip(". ") or "제목 없음"


def esc(value) -> str:
    """Source text never forms wikilinks or embeds (some titles contain literal [[...]] or ![[...]])."""
    return str(value).replace("[[", "\\[\\[").replace("]]", "\\]\\]")


def cell(value) -> str:
    """Markdown table cell: one line, pipes and wikilink brackets escaped."""
    if value is None or value == "":
        return "—"
    return esc(re.sub(r"\s+", " ", str(value)).replace("|", "\\|").strip())


def md_link(text, url: Optional[str]) -> str:
    """External Markdown link whose label cannot open a wikilink; table-safe."""
    label = cell(text).replace("\\[", "(").replace("\\]", ")").replace("[", "(").replace("]", ")")
    return f"[{label}]({url.replace(' ', '%20').replace(')', '%29')})" if url else cell(text)


def short_source(name: str) -> str:
    return name.split(" — ")[0].split(" (")[0].strip() or name


def link(name: str, display: Optional[str] = None) -> str:
    if display is None:
        return f"[[{name}]]"
    shown = re.sub(r"\s+", " ", display).replace("|", "/").replace("[", "(").replace("]", ")").strip()
    return f"[[{name}|{shown}]]"


def flat(text: str) -> str:
    """Collapse whitespace of already table-safe Markdown (e.g. text holding escaped wikilinks)."""
    return re.sub(r"\s+", " ", text).strip() or "—"


def table_link(name: str, display: Optional[str] = None) -> str:
    """Wikilink usable inside a Markdown table (the alias pipe must be escaped)."""
    return link(name, display).replace("|", "\\|")


def yaml_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(yaml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def front_matter(fields: Dict[str, object]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {yaml_value(value)}")
    lines.append("---\n")
    return "\n".join(lines)


def _hangul_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum("\uac00" <= ch <= "\ud7a3" for ch in letters) / len(letters)


def useful_ko(ko: Optional[str]) -> Optional[str]:
    """Hide machine translations that carry no content (e.g. '_ 한국어', '물놀이' for a 3-word title is kept)."""
    core = re.sub(r"[\W_]+", "", ko or "")
    if not core or core == "한국어" or "⁇" in (ko or ""):  # '⁇' marks tokens the model could not render
        return None
    return ko


def callout(kind: str, title: str, body: List[str], folded: bool = False) -> List[str]:
    """Obsidian callout; `folded` renders it collapsed. Body lines are quoted verbatim (tables and lists work inside)."""
    return [f"> [!{kind}]{'-' if folded else ''} {title}"] + [f"> {x}" if x else ">" for x in body]


def interleave_by_source(articles: List[dict]) -> List[dict]:
    """Newest-first per outlet, then one item per outlet in turn, so a single busy feed cannot fill the list."""
    queues = collections.OrderedDict()
    for a in articles:  # already newest-first
        queues.setdefault(a.get("publisher") or a["source_id"], collections.deque()).append(a)
    out = []
    while queues:
        for key in list(queues):
            out.append(queues[key].popleft())
            if not queues[key]:
                del queues[key]
    return out


def day(value: Optional[str]) -> Optional[dt.date]:
    if not value or len(value) < 10:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def period(start: Optional[str], end: Optional[str]) -> str:
    if not start and not end:
        return "기간 미상"
    return f"{start or '?'} ~ {end or '?'}"


# ----------------------------------------------------------------------------------------------- builder
class VaultBuilder:
    def __init__(self, con: sqlite3.Connection, out: Path, asof: dt.date, days: int,
                 auction: Optional[sqlite3.Connection] = None, manifest: Optional[dict] = None):
        self.con = con
        self.out = out
        self.asof = asof
        self.days = days
        self.auction = auction
        self.manifest = manifest or {}
        self.files = 0
        self.names: Dict[Tuple[str, str], str] = {}
        self._used = set()
        con.row_factory = sqlite3.Row

    # -- io
    def write(self, rel: str, text: str) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        self.files += 1

    def name_for(self, kind: str, key: str, title: Optional[str]) -> str:
        found = self.names.get((kind, key))
        if found:
            return found
        tail = key.split("_")[-1][:8] if key else "x"
        candidate = f"{clean_name(title)} · {tail}"
        if candidate.casefold() in self._used:
            candidate = f"{clean_name(title)} · {clean_name(key, 60)}"
        self._used.add(candidate.casefold())
        self.names[(kind, key)] = candidate
        return candidate

    # -- translations
    def load_translations(self) -> None:
        self.ko: Dict[Tuple[str, str, str], Tuple[str, Optional[str]]] = {}
        for r in self.derived("metadata_translations",
                "SELECT source_table, source_key, source_field, translation_ko, source_lang FROM metadata_translations "
                "WHERE status='translated' AND translation_ko IS NOT NULL AND source_table IN "
                "('events','articles','reports','report_metrics','works')"):
            self.ko[(r[0], r[1], r[2])] = (r[3], r[4])

    def ko_of(self, table: str, key: str, field: str, original: Optional[str]) -> Optional[str]:
        if not original or _hangul_share(original) >= 0.5:
            return None
        got = self.ko.get((table, key, field))
        if not got:
            return None
        return ko_polish.reader_ko(original, got[0], got[1])  # broken machine output falls back to the original

    def bilingual(self, table: str, key: str, field: str, original: Optional[str]) -> str:
        """Inline display: Korean first when a translation exists, original always preserved."""
        if not original:
            return "—"
        ko = self.ko_of(table, key, field, original)
        if ko:
            return f"{ko} ⟨원문: {original}⟩"
        return original

    # -- load
    def derived(self, table: str, sql: str):
        """Rows from a table written by `derive`/`translate`; empty before those steps have run."""
        exists = self.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return self.con.execute(sql).fetchall() if exists else []

    def load(self) -> None:
        c = self.con
        self.load_translations()
        self.sources = {r["source_id"]: dict(r) for r in c.execute("SELECT * FROM sources")}
        self.entities = {r["entity_id"]: dict(r) for r in c.execute("SELECT * FROM entities")}
        self.venues = {r["venue_id"]: dict(r) for r in c.execute("SELECT * FROM venues")}
        self.events = {r["event_id"]: dict(r) for r in c.execute("SELECT * FROM events")}
        self.lifecycle = {r[0]: r[1] for r in self.derived("event_status", "SELECT event_id, lifecycle FROM event_status")}
        self.participants = collections.defaultdict(list)
        self.by_entity_events = collections.defaultdict(list)
        for r in c.execute("SELECT * FROM event_participants ORDER BY event_id, role, name_as_listed"):
            self.participants[r["event_id"]].append(dict(r))
            self.by_entity_events[r["entity_id"]].append(dict(r))
        self.event_evidence = collections.defaultdict(list)
        for r in c.execute("SELECT ee.event_id, e.* FROM event_evidence ee JOIN evidence e USING(evidence_id) "
                           "ORDER BY e.fetched_at"):
            self.event_evidence[r["event_id"]].append(dict(r))
        self.event_links = collections.defaultdict(list)
        for r in self.derived("event_links", "SELECT * FROM event_links"):
            self.event_links[r["event_id"]].append(dict(r))
        self.relationships_all = [dict(r) for r in c.execute("SELECT * FROM relationships")]
        self.reports_all = [dict(r) for r in c.execute("SELECT * FROM reports")]
        self.relationships = collections.defaultdict(list)
        for r in c.execute("SELECT * FROM relationships"):
            self.relationships[r["subject_entity_id"]].append(dict(r))
            self.relationships[r["object_entity_id"]].append(dict(r))
        self.entity_links = collections.defaultdict(list)
        for r in c.execute("SELECT * FROM entity_links WHERE reversed_at IS NULL"):
            self.entity_links[r["entity_id_a"]].append((r["entity_id_b"], dict(r)))
            self.entity_links[r["entity_id_b"]].append((r["entity_id_a"], dict(r)))
        self.aliases = collections.defaultdict(list)
        for r in c.execute("SELECT entity_id, name, lang, namespace, external_id, match_status FROM aliases"):
            self.aliases[r["entity_id"]].append(dict(r))
        self.mentions = collections.defaultdict(list)
        for r in c.execute("SELECT * FROM article_mentions"):
            self.mentions[r["entity_id"]].append(dict(r))
        self.signals = collections.defaultdict(dict)
        for r in c.execute("SELECT subject_id, metric, value, edition_region, asof FROM signals "
                           "WHERE asof=(SELECT max(asof) FROM signals)"):
            self.signals[r["subject_id"]][r["metric"]] = r["value"]
                # Notes exist only for entities that something in the vault points at.
        referenced = set(self.by_entity_events) | set(self.relationships) | set(self.mentions)
        referenced |= {e["organizer_entity_id"] for e in self.events.values() if e["organizer_entity_id"]}
        referenced |= {v["owner_entity_id"] for v in self.venues.values() if v["owner_entity_id"]}
        self.noted_entities = {eid for eid in referenced if eid in self.entities}
        for eid in sorted(self.noted_entities):
            ent = self.entities[eid]
            self.name_for("entity", eid, ent["canonical_name"])
        for eid in sorted(self.events):
            self.name_for("event", eid, self.events[eid]["title"])
        for sid in sorted(self.sources):
            self.name_for("source", sid, self.sources[sid]["name"] or sid)

    # -- link helpers
    def entity_link(self, eid: Optional[str], fallback: Optional[str] = None, in_table: bool = False) -> str:
        if eid and eid in self.noted_entities:
            fn = table_link if in_table else link
            return fn(self.names[("entity", eid)], self.entities[eid]["canonical_name"])
        if not fallback:
            return "—"
        return cell(fallback) if in_table else esc(fallback)

    def event_link(self, eid: str, in_table: bool = False) -> str:
        ev = self.events[eid]
        fn = table_link if in_table else link
        # Proper titles keep their original wording; automatic title translations stay in the event note.
        return fn(self.names[("event", eid)], ev["title"] or "제목 없음")

    def source_link(self, sid: Optional[str], in_table: bool = False) -> str:
        if not sid or sid not in self.sources:
            return sid or "—"
        fn = table_link if in_table else link
        return fn(self.names[("source", sid)], self.sources[sid]["name"] or sid)

    def venue_text(self, ev: dict, in_table: bool = False) -> str:
        venue = self.venues.get(ev["venue_id"]) if ev["venue_id"] else None
        owner = venue["owner_entity_id"] if venue else ev["organizer_entity_id"]
        label = venue["name"] if venue else None
        if owner:
            shown = self.entity_link(owner, label, in_table)
        else:
            shown = (cell(label) if in_table else esc(label)) if label else "—"
        place = cell(", ".join(x for x in (ev["city"], ev["country_code"]) if x)) if (ev["city"] or ev["country_code"]) else ""
        return f"{shown} ({place})" if place else shown

    # ------------------------------------------------------------------------------------------- notes
    def event_folder(self, ev: dict) -> str:
        year = (ev["start_date"] or ev["end_date"] or "")[:4]
        year = year if re.fullmatch(r"\d{4}", year) else "연도미상"
        return f"03_전시·프로그램/{EDITION_KO[ev['edition_region']]}/{year}"

    def write_events(self) -> None:
        index = collections.defaultdict(list)
        for eid in sorted(self.events):
            ev = self.events[eid]
            folder = self.event_folder(ev)
            index[folder].append(eid)
            title_ko = self.ko_of("events", eid, "title", ev["title"])
            desc_ko = self.ko_of("events", eid, "description_excerpt", ev["description_excerpt"])
            fm = front_matter({
                "type": "event", "event_id": eid, "event_type": ev["event_type"], "subtype": ev["subtype"],
                "edition": ev["edition_region"], "country": ev["country_code"], "city": ev["city"],
                "start": ev["start_date"], "start_precision": ev["start_precision"], "end": ev["end_date"],
                "end_precision": ev["end_precision"], "lifecycle": self.lifecycle.get(eid),
                "source_id": ev["source_id"], "url": ev["url"], "publishable": False,
                "tags": [f"edition/{ev['edition_region'] or 'unassigned'}", f"event/{ev['event_type']}"],
            })
            lines = [fm, f"# {esc(ev['title'] or '제목 없음')}", ""]
            if title_ko:
                lines += [f"**한국어({TRANSLATION_NOTE})**: {esc(title_ko)}", ""]
            lines += [
                f"- 유형: {EVENT_TYPE_KO.get(ev['event_type'], ev['event_type'])}" + (f" · {ev['subtype']}" if ev["subtype"] else ""),
                f"- 기간: {period(ev['start_date'], ev['end_date'])} (정밀도 {ev['start_precision'] or '?'}/{ev['end_precision'] or '?'})"
                + (f" · 원문 표기 `{cell(ev['date_text'])}`" if ev["date_text"] else ""),
                f"- 상태(2026 스냅샷): {self.lifecycle.get(eid) or '미상'}",
                f"- 장소: {self.venue_text(ev)}",
                f"- 에디션: [[{EDITION_KO[ev['edition_region']]} 에디션]]" if ev["edition_region"] else "- 에디션: 미지정(장소 국가 미상)",
                f"- 출처: {self.source_link(ev['source_id'])}" + (f" · [원문 페이지]({ev['url']})" if ev["url"] else ""),
            ]
            if ev["organizer_entity_id"]:
                lines.append(f"- 주최: {self.entity_link(ev['organizer_entity_id'])}")
            parts = self.participants.get(eid, [])
            if parts:
                lines += ["", f"## 참여 ({len(parts)})", ""]
                for p in parts:
                    lines.append(f"- {p['role']}: {self.entity_link(p['entity_id'], p['name_as_listed'])}"
                                 + (f" (원문 표기 {esc(p['name_as_listed'])})" if p["name_as_listed"] and p["entity_id"] in self.noted_entities
                                    and p["name_as_listed"] != self.entities[p["entity_id"]]["canonical_name"] else ""))
            if ev["description_excerpt"]:
                lines += ["", "## 소개 발췌 (300자 이하)", "", f"> {cell(ev['description_excerpt'])}"]
                if desc_ko:
                    lines += ["", f"**한국어({TRANSLATION_NOTE})**: {cell(desc_ko)}"]
            if self.event_links.get(eid):
                lines += ["", "## 연결된 행사", ""]
                for l in self.event_links[eid]:
                    target = l["canonical_event_id"]
                    shown = self.event_link(target) if target in self.events else target
                    lines.append(f"- {l['link_type']}: {shown} — {esc(l['reason'] or '')}")
            evid = self.event_evidence.get(eid, [])
            if evid:
                lines += ["", "## 증거", "", "| 가져온 시각 | HTTP | URL | 원문 SHA-256 |", "|---|---|---|---|"]
                for e in evid[:10]:
                    lines.append(f"| {cell(e['fetched_at'])} | {cell(e['http_status'])} | {cell(e['url'])} | `{(e['raw_sha256'] or '—')[:16]}` |")
            self.write(f"{folder}/{self.names[('event', eid)]}.md", "\n".join(lines))
        for folder, eids in index.items():
            edition, year = folder.split("/")[1:]
            eids.sort(key=lambda x: (self.events[x]["start_date"] or "9999", x))
            lines = [front_matter({"type": "index", "edition": edition, "year": year}),
                     f"# {edition} · {year} 전시·프로그램 ({len(eids)}건)", "",
                     "| 시작 | 종료 | 유형 | 제목 | 장소 | 출처 |", "|---|---|---|---|---|---|"]
            for x in eids:
                ev = self.events[x]
                lines.append(f"| {cell(ev['start_date'])} | {cell(ev['end_date'])} | {cell(EVENT_TYPE_KO.get(ev['event_type'], ev['event_type']))} | "
                             f"{self.event_link(x, True)} | {flat(self.venue_text(ev, True))} | {self.source_link(ev['source_id'], True)} |")
            self.write(f"{folder}/_{edition} {year} 목록.md", "\n".join(lines))

    def entity_folder(self, ent: dict) -> str:
        if ent["entity_type"] in PERSON_TYPES:
            first = (ent["canonical_name"] or "#").strip()[:1].upper()
            if "\uac00" <= first <= "\ud7a3":
                bucket = "가-힣"
            elif re.match(r"[A-Z]", first):
                bucket = first
            elif re.match(r"[\u3040-\u30ff\u4e00-\u9fff]", first):
                bucket = "日本語·漢字"
            else:
                bucket = "기타 문자"
            return f"04_작가/{bucket}"
        return f"05_기관/{ORG_FOLDER.get(ent['entity_type'], '미분류')}"

    def write_entities(self) -> None:
        works_by_artist = collections.defaultdict(list)
        for r in self.con.execute("SELECT work_id, artist_entity_id, title, date_text, medium, source_id, url FROM works "
                                  "WHERE artist_entity_id IS NOT NULL ORDER BY date_text"):
            if r["artist_entity_id"] in self.noted_entities and len(works_by_artist[r["artist_entity_id"]]) < 20:
                works_by_artist[r["artist_entity_id"]].append(dict(r))
        hosted = collections.defaultdict(list)
        for eid, ev in self.events.items():
            venue = self.venues.get(ev["venue_id"]) if ev["venue_id"] else None
            for owner in {ev["organizer_entity_id"], venue["owner_entity_id"] if venue else None} - {None}:
                hosted[owner].append(eid)
        for eid in sorted(self.noted_entities):
            ent = self.entities[eid]
            person = ent["entity_type"] in PERSON_TYPES
            wikidata = sorted({a["external_id"] for a in self.aliases.get(eid, []) if a["namespace"] == "wikidata" and a["external_id"]})
            fm = front_matter({
                "type": "artist" if person else "organization", "entity_id": eid, "entity_type": ent["entity_type"],
                "nationality_text": ent["nationality_text"], "birth_year": ent["birth_year"], "death_year": ent["death_year"],
                "verification_status": ent["verification_status"], "official_url": ent["official_url"],
                "wikidata": wikidata, "identity_confirmed": False,
                "tags": ["artist" if person else f"org/{ent['entity_type']}"],
            })
            lines = [fm, f"# {esc(ent['canonical_name'])}", ""]
            if person:
                lines += ["> [!note] 이름이 같다고 같은 사람은 아닙니다. 아래 동일인 연결은 출처 근거가 있는 후보이며 되돌릴 수 있습니다.", ""]
            facts = [("유형", ent["entity_type"]), ("국적 표기(원문)", ent["nationality_text"]),
                     ("생몰년", f"{ent['birth_year'] or '?'}–{ent['death_year'] or ''}" if ent["birth_year"] or ent["death_year"] else None),
                     ("공식 URL", ent["official_url"]), ("검증 상태", ent["verification_status"]),
                     ("Wikidata", ", ".join(f"[{q}](https://www.wikidata.org/wiki/{q})" for q in wikidata) if wikidata else None)]
            lines += [f"- {k}: {v if k == 'Wikidata' else esc(v)}" for k, v in facts if v]
            other_names = sorted({a["name"] for a in self.aliases.get(eid, []) if a["name"] and a["name"] != ent["canonical_name"]})
            if other_names:
                lines.append(f"- 다른 표기: {esc(', '.join(other_names[:15]))}" + (" …" if len(other_names) > 15 else ""))
            sig = self.signals.get(eid) or {}
            if sig:
                lines += ["", "## 관찰 카운트 (점수·순위 아님, 게시 불가)", ""]
                for metric in sorted(sig):
                    value = sig[metric]
                    lines.append(f"- `{metric}`: {value:g}" if isinstance(value, (int, float)) else f"- `{metric}`: {value}")
            links = self.entity_links.get(eid, [])
            if links:
                lines += ["", "## 동일인 후보 연결", "", "| 상태 | 대상 | 방법 | 근거 |", "|---|---|---|---|"]
                for other, l in sorted(links, key=lambda x: (x[1]["status"], x[0]))[:30]:
                    lines.append(f"| {cell(l['status'])} | {self.entity_link(other, other, True)} | {cell(l['method'])} | {cell((l['evidence'] or '')[:120])} |")
            parts = sorted(self.by_entity_events.get(eid, []), key=lambda p: self.events[p["event_id"]]["start_date"] or "")
            if parts:
                lines += ["", f"## 전시·선정 참여 ({len(parts)})", "", "| 시작 | 역할 | 행사 | 장소 | 에디션 |", "|---|---|---|---|---|"]
                for p in parts:
                    ev = self.events[p["event_id"]]
                    lines.append(f"| {cell(ev['start_date'])} | {cell(p['role'])} | {self.event_link(p['event_id'], True)} | "
                                 f"{flat(self.venue_text(ev, True))} | {cell(EDITION_KO[ev['edition_region']])} |")
            own = sorted(hosted.get(eid, []), key=lambda x: self.events[x]["start_date"] or "", reverse=True)
            if own:
                lines += ["", f"## 개최·주최 행사 ({len(own)})", "", "| 시작 | 종료 | 행사 | 상태 |", "|---|---|---|---|"]
                for x in own[:200]:
                    ev = self.events[x]
                    lines.append(f"| {cell(ev['start_date'])} | {cell(ev['end_date'])} | {self.event_link(x, True)} | {cell(self.lifecycle.get(x))} |")
                if len(own) > 200:
                    lines.append(f"\n전체 {len(own)}건 중 최근 200건만 표시합니다.")
            rels = self.relationships.get(eid, [])
            if rels:
                lines += ["", "## 관계 (공식 명단 관측)", "", "| 관계 | 상대 | 첫 관측 | 마지막 관측 | 상태 |", "|---|---|---|---|---|"]
                for r in rels:
                    other = r["object_entity_id"] if r["subject_entity_id"] == eid else r["subject_entity_id"]
                    lines.append(f"| {cell(r['rel_type'])} | {self.entity_link(other, other, True)} | {cell((r['first_seen_at'] or '')[:10])} | "
                                 f"{cell((r['last_seen_at'] or '')[:10])} | {cell(r['status'])} |")
                lines.append("\n첫 명단 관측은 '신규 소속'의 증거가 아닙니다.")
            works = works_by_artist.get(eid)
            if works:
                lines += ["", "## 소장품 기록 (최대 20건)", "", "| 연도 | 제목 | 재료 | 출처 |", "|---|---|---|---|"]
                for w in works:
                    title = self.bilingual("works", w["work_id"], "title", w["title"])
                    shown = md_link(title, w["url"])
                    lines.append(f"| {cell(w['date_text'])} | {shown} | {cell(w['medium'])} | {self.source_link(w['source_id'], True)} |")
            ments = self.mentions.get(eid)
            if ments:
                lines += ["", f"## 기사 언급 ({len(ments)})", ""]
                for m in ments[:30]:
                    lines.append(f"- {m['mention_type']} · {m['status']}: {cell((m['evidence_text'] or '')[:200])}")
            self.write(f"{self.entity_folder(ent)}/{self.names[('entity', eid)]}.md", "\n".join(lines))

    def write_sources(self) -> None:
        runs = collections.defaultdict(dict)
        for r in self.con.execute("SELECT * FROM crawl_runs ORDER BY started_at"):
            runs[r["source_id"]][r["mode"]] = dict(r)
        coverage = collections.defaultdict(list)
        for r in self.con.execute("SELECT * FROM coverage WHERE asof=(SELECT max(asof) FROM coverage)"):
            coverage[r["source_id"]].append(dict(r))
        counts = collections.defaultdict(lambda: collections.Counter())
        for table in ("events", "articles", "works", "evidence"):
            for sid, n in self.con.execute(f"SELECT source_id, count(*) FROM {table} GROUP BY 1"):
                counts[sid][table] = n
        by_state = collections.defaultdict(list)
        for sid in sorted(self.sources):
            s = self.sources[sid]
            state = s["operational_state"] or "unknown"
            by_state[state].append(sid)
            fm = front_matter({"type": "source", "source_id": sid, "operational_state": state, "region_scope": s["region_scope"],
                               "access_method": s["access_method"], "text_storage_policy": s["text_storage_policy"],
                               "blueprint_data_id": s["blueprint_data_id"], "tags": [f"source/{state}"]})
            lines = [fm, f"# {esc(s['name'] or sid)}", "", f"- source_id: `{sid}`"]
            for label, key in (("운영 상태", "operational_state"), ("지역 범위", "region_scope"), ("국가", "country_codes"),
                               ("수집 방식", "access_method"), ("본문 저장 정책", "text_storage_policy"), ("robots", "robots_status"),
                               ("Blueprint D", "blueprint_data_id"), ("기본 URL", "base_url"), ("진입 URL", "entry_url"),
                               ("약관 URL", "terms_url"), ("수집 약관 판정", "st_collection_terms"), ("이미지 약관 판정", "st_image_terms"),
                               ("이력 범위", "st_history"), ("증분 수집", "st_incremental")):
                if s.get(key):
                    lines.append(f"- {label}: {esc(s[key])}")
            if s.get("notes"):
                lines += ["", "## 메모", "", esc(s["notes"])]
            c = counts.get(sid)
            if c:
                lines += ["", "## 저장 행수", ""] + [f"- {k}: {v:,}" for k, v in sorted(c.items())]
            if runs.get(sid):
                lines += ["", "## 최근 실행 (모드별 마지막)", "", "| 모드 | 시작 | 상태 | 요청 | 추가 | 갱신 | 동일 | 오류 |", "|---|---|---|---|---|---|---|---|"]
                for mode, r in sorted(runs[sid].items()):
                    lines.append(f"| {mode} | {cell(r['started_at'])} | {cell(r['state'])} | {cell(r['http_requests'])} | {cell(r['records_inserted'])} | "
                                 f"{cell(r['records_updated'])} | {cell(r['records_unchanged'])} | {cell((r['error'] or '')[:160])} |")
            if coverage.get(sid):
                lines += ["", "## 커버리지", "", "| 에디션 | 종류 | 행수 | 최초 | 최신 | 최근90일 | 완전성 |", "|---|---|---|---|---|---|---|"]
                for r in coverage[sid]:
                    lines.append(f"| {cell(r['edition_region'])} | {cell(r['record_kind'])} | {cell(r['n_records'])} | {cell(r['earliest_date'])} | "
                                 f"{cell(r['latest_date'])} | {cell(r['n_last_90d'])} | {cell(r['completeness'])} |")
            self.write(f"09_출처/{state}/{self.names[('source', sid)]}.md", "\n".join(lines))
        lines = [front_matter({"type": "index"}), "# 출처 목록", "",
                 "`blocked_access`=기술적 접근 불가, `blocked_permission`/`blocked_credentials`=권한·키 필요, `partial`=일부만 수집.", ""]
        for state in sorted(by_state):
            lines += [f"## {state} ({len(by_state[state])})", "", "| 출처 | 지역 | 방식 | 이벤트 | 기사 | 작품 |", "|---|---|---|---|---|---|"]
            for sid in by_state[state]:
                s, c = self.sources[sid], counts.get(sid, {})
                lines.append(f"| {self.source_link(sid, True)} | {cell(s['region_scope'])} | {cell(s['access_method'])} | "
                             f"{c.get('events', 0):,} | {c.get('articles', 0):,} | {c.get('works', 0):,} |")
            lines.append("")
        self.write("09_출처/_출처 목록.md", "\n".join(lines))

    def article_rows(self):
        return self.con.execute("SELECT * FROM articles ORDER BY source_id, published_at, article_id")

    def write_articles(self) -> None:
        groups = collections.defaultdict(list)
        restricted = collections.Counter()
        for r in self.article_rows():
            src = self.sources.get(r["source_id"], {})
            if src.get("operational_state") == "blocked_permission":
                restricted[r["source_id"]] += 1
                continue
            month = (r["published_at"] or "")[:7] or "날짜미상"
            groups[(r["source_id"], month)].append(dict(r))
        per_source = collections.defaultdict(list)
        base_names = collections.Counter(clean_name(short_source(self.sources.get(s, {}).get("name") or s), 60) for s in {k[0] for k in groups})
        for (sid, month), rows in sorted(groups.items()):
            src_name = clean_name(short_source(self.sources.get(sid, {}).get("name") or sid), 60)
            if base_names[src_name] > 1:
                src_name = f"{src_name} ({sid})"
            note = f"{src_name} {month}"
            per_source[sid].append((month, note, len(rows)))
            lines = [front_matter({"type": "article_digest", "source_id": sid, "month": month, "count": len(rows)}),
                     f"# {esc(self.sources.get(sid, {}).get('name') or sid)} · {month} ({len(rows)}건)", "",
                     f"출처: {self.source_link(sid)} · 제목·메타데이터와 300자 이하 발췌만 보관합니다. 본문은 원문 링크에서 읽습니다.", ""]
            if sid in READING_EXCLUDED_SOURCES:
                lines += ["> [!info] 원본 DB에서 가져온 날짜 없는 발견용 메타데이터입니다. 데일리 인사이트 읽을거리에는 쓰지 않습니다.", ""]
            elif sid == LEGACY_NEWS_SOURCE:
                lines += ["> [!info] 원본 프로젝트(아트랜드v2v_20261020.zip)가 Naver 검색 API·Google News RSS로 모은 기사 메타데이터입니다(2026-10-19까지). "
                          "이후 국내 기사는 언론사 공식 RSS 출처(`kr_*_rss`)가 이어 받습니다.", ""]
            lines += ["| 날짜 | 유형 | 제목(원문) | 한국어 자동번역 | 필자 |", "|---|---|---|---|---|"]
            for a in rows:
                title = md_link(a["title"], a["canonical_url"])
                ko = self.ko_of("articles", a["article_id"], "title", a["title"])
                lines.append(f"| {cell((a['published_at'] or '')[:10])} | {cell(a['article_type'])} | {title} | {cell(ko)} | {cell(a['author_text'])} |")
            excerpts = [a for a in rows if a["excerpt"]]
            if excerpts:
                lines += ["", "## 발췌 (300자 이하)", ""]
                for a in excerpts:
                    ko = self.ko_of("articles", a["article_id"], "excerpt", a["excerpt"])
                    lines += [f"- **{cell(a['title'])}** — {cell(a['excerpt'])}"] + ([f"  - 한국어({TRANSLATION_NOTE}): {cell(ko)}"] if ko else [])
            self.write(f"06_기사·비평/{src_name}/{note}.md", "\n".join(lines))
        lines = [front_matter({"type": "index"}), "# 기사·비평 목록", "",
                 "출처별 월간 묶음입니다. 전문은 저장하지 않으며 각 행은 원문 링크로 이어집니다.", ""]
        for sid in sorted(per_source, key=lambda s: (self.sources.get(s, {}).get("name") or s)):
            total = sum(n for _, _, n in per_source[sid])
            lines.append(f"## {self.sources.get(sid, {}).get('name') or sid} ({total:,}건)")
            lines.append("")
            lines.append(" · ".join(link(note, month) for month, note, _ in sorted(per_source[sid], reverse=True)))
            lines.append("")
        if restricted:
            lines += ["## 제외", "", "권한 제한 출처(수집 비활성화)의 과거 행은 볼트에 넣지 않았습니다: "
                      + ", ".join(f"{k} {v}건" for k, v in sorted(restricted.items()))]
        self.write("06_기사·비평/_기사·비평 목록.md", "\n".join(lines))

    def write_reports(self) -> None:
        metrics = collections.defaultdict(list)
        for r in self.con.execute("SELECT * FROM report_metrics ORDER BY report_id, page, metric_id"):
            metrics[r["report_id"]].append(dict(r))
        rows = [dict(r) for r in self.con.execute("SELECT * FROM reports ORDER BY published_date DESC, report_id")]
        index = [front_matter({"type": "index"}), f"# 리포트 ({len(rows)})", "",
                 "| 발행일 | 제목 | 발행처 | 지표 수 | 접근 |", "|---|---|---|---|---|"]
        for r in rows:
            name = self.name_for("report", r["report_id"], r["title"])
            title = self.bilingual("reports", r["report_id"], "title", r["title"])
            lines = [front_matter({"type": "report", "report_id": r["report_id"], "publisher": r["publisher"],
                                   "published": r["published_date"], "access_status": r["access_status"], "publishable": False}),
                     f"# {esc(r['title'])}", ""]
            ko = self.ko_of("reports", r["report_id"], "title", r["title"])
            if ko:
                lines += [f"**한국어({TRANSLATION_NOTE})**: {esc(ko)}", ""]
            for label, key in (("발행처", "publisher"), ("저자", "authors"), ("후원", "sponsor"), ("발행일", "published_date"),
                               ("관측 기간", "observation_period"), ("지역 범위", "geo_scope"), ("방법론", "methodology"),
                               ("표본", "sample"), ("가격 기준", "price_basis"), ("공식 URL", "official_url"), ("쪽수", "pages"),
                               ("권리", "rights_note"), ("접근 상태", "access_status"), ("메모", "notes")):
                if r.get(key):
                    lines.append(f"- {label}: {esc(r[key])}")
            ms = metrics.get(r["report_id"], [])
            if ms:
                lines += ["", "## 지표 (보고서 원문 수치, 쪽 표시)", "", "| 지표 | 값 | 단위 | 지역 | 기간 | 쪽 | 발췌 | 한국어 |", "|---|---|---|---|---|---|---|---|"]
                for m in ms:
                    ko = self.ko_of("report_metrics", m["metric_id"], "excerpt", m["excerpt"])
                    lines.append(f"| {cell(m['metric_name'])} | {cell(m['value_text'] or m['value'])} | {cell(m['unit'])} | {cell(m['geography'])} | "
                                 f"{cell(m['period'])} | {cell(m['page'])} | {cell(m['excerpt'])} | {cell(ko)} |")
                lines.append("\n보고서마다 표본·가격 기준이 다르므로 서로 직접 비교하지 않습니다.")
            self.write(f"07_리포트/{name}.md", "\n".join(lines))
            index.append(f"| {cell(r['published_date'])} | {table_link(name, title)} | {cell(r['publisher'])} | {len(ms)} | {cell(r['access_status'])} |")
        self.write("07_리포트/_리포트 목록.md", "\n".join(index))

    def cards(self) -> List[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM evidence_cards ORDER BY edition_region, section, card_id")]

    def card_note_name(self, card: dict) -> str:
        return self.name_for("card", card["card_id"], card["title"])

    def card_body(self, card: dict, heading: str = "##") -> List[str]:
        lines = [f"{heading} {esc(card['title'])}", "", f"`{card['section']}` · `{card['card_kind']}` · 상태 `{card['status']}` · 독립 출처 {card['n_independent_sources'] or 0}곳", ""]
        for label, key in (("사실", "facts"), ("비교", "comparison"), ("해석", "interpretation"), ("반대 근거", "counter_evidence"), ("한계", "limitations")):
            if card.get(key):
                body = esc(card[key]).replace("\n", "\n> ")
                lines += [f"**{label}**", "", f"> {body}", ""]
        urls = json.loads(card["evidence_urls"] or "[]")
        if urls:
            lines += ["**증거 URL**", ""] + [f"- {esc(u)}" for u in urls[:20]] + [""]
        events = json.loads(card["event_ids"] or "[]")
        linked = [self.event_link(e) for e in events if e in self.events]
        if linked:
            lines += ["**연결 행사**: " + ", ".join(linked[:20]), ""]
        return lines

    def write_cards(self) -> None:
        cards = self.cards()
        index = [front_matter({"type": "index"}), f"# 증거 카드 ({len(cards)}) — 모두 미게시 초안", "", DRAFT_CALLOUT,
                 "| 에디션 | 섹션 | 종류 | 카드 |", "|---|---|---|---|"]
        for card in cards:
            name = self.card_note_name(card)
            fm = front_matter({"type": "evidence_card", "card_id": card["card_id"], "edition": card["edition_region"],
                               "section": card["section"], "card_kind": card["card_kind"], "status": card["status"],
                               "asof": card["asof"], "publishable": False})
            self.write(f"08_증거카드/{EDITION_KO.get(card['edition_region'], card['edition_region'])}/{name}.md",
                       fm + DRAFT_CALLOUT + "\n" + "\n".join(self.card_body(card, "#")))
            index.append(f"| {cell(EDITION_KO.get(card['edition_region']))} | {cell(card['section'])} | {cell(card['card_kind'])} | {table_link(name, card['title'])} |")
        self.write("08_증거카드/_증거카드 목록.md", "\n".join(index))

    def write_works(self) -> None:
        rows = self.con.execute(
            "SELECT source_id, count(*) n, sum(artist_entity_id IS NOT NULL) linked, sum(is_public_domain=1) pd, "
            "min(first_seen_at) first, max(last_seen_at) last FROM works GROUP BY 1 ORDER BY 2 DESC").fetchall()
        index = [front_matter({"type": "index"}), "# 소장품 기록 요약", "",
                 "작품 70만여 건은 노트 하나씩 만들지 않고 출처별 요약과 표본으로 보여 줍니다. 전체 행은 SQLite에 있습니다. 이미지는 저장하지 않습니다.", "",
                 "| 출처 | 작품 수 | 작가 연결 | 퍼블릭 도메인 표시 |", "|---|---|---|---|"]
        for r in rows:
            sid = r["source_id"]
            name = f"소장품 {clean_name(self.sources.get(sid, {}).get('name') or sid, 60)}"
            cls = self.con.execute("SELECT coalesce(classification,'(없음)'), count(*) FROM works WHERE source_id=? GROUP BY 1 ORDER BY 2 DESC LIMIT 15", (sid,)).fetchall()
            sample = self.con.execute("SELECT work_id, title, date_text, medium, url, artist_entity_id FROM works WHERE source_id=? "
                                      "ORDER BY last_seen_at DESC, work_id LIMIT 50", (sid,)).fetchall()
            lines = [front_matter({"type": "works_summary", "source_id": sid, "works": r["n"]}),
                     f"# {esc(self.sources.get(sid, {}).get('name') or sid)} 소장품 기록", "", f"- 출처: {self.source_link(sid)}",
                     f"- 작품 {r['n']:,}건 · 작가 연결 {r['linked'] or 0:,} · 퍼블릭 도메인 표시 {r['pd'] or 0:,}",
                     f"- 관측 기간: {(r['first'] or '')[:10]} ~ {(r['last'] or '')[:10]}", "",
                     "## 분류 상위 15", "", "| 분류 | 건수 |", "|---|---|"]
            lines += [f"| {cell(c[0])} | {c[1]:,} |" for c in cls]
            lines += ["", "## 최근 관측 표본 50", "", "| 연도 | 제목 | 재료 | 작가 |", "|---|---|---|---|"]
            for w in sample:
                title = self.bilingual("works", w["work_id"], "title", w["title"])
                shown = md_link(title, w["url"])
                lines.append(f"| {cell(w['date_text'])} | {shown} | {cell(w['medium'])} | {self.entity_link(w['artist_entity_id'], '—', True)} |")
            self.write(f"11_소장품/{name}.md", "\n".join(lines))
            index.append(f"| {table_link(name, self.sources.get(sid, {}).get('name') or sid)} | {r['n']:,} | {r['linked'] or 0:,} | {r['pd'] or 0:,} |")
        self.write("11_소장품/_소장품 요약.md", "\n".join(index))

    def write_market(self) -> None:
        self.write("10_시장참고/_시장참고.md", "\n".join([
            front_matter({"type": "index"}), "# 시장 참고", "", "- [[경매 정규화 요약]]", "- [[_리포트 목록|리포트·지표]]",
            "- 시장 섹션(H08) 카드: [[_증거카드 목록]]"]))
        if self.auction is None:
            self.write("10_시장참고/경매 정규화 요약.md", "# 경매 정규화 요약\n\n`db/auction_normalized.sqlite`가 없어 요약을 만들지 않았습니다.")
            return
        a = self.auction
        houses = a.execute("SELECT house, count(*), sum(status='sold'), sum(price_comparability='comparable_within_basis'), "
                           "min(sale_date), max(sale_date) FROM normalized_lots GROUP BY 1 ORDER BY 2 DESC").fetchall()
        reasons = a.execute("SELECT price_comparability, count(*) FROM normalized_lots GROUP BY 1 ORDER BY 2 DESC").fetchall()
        lines = [front_matter({"type": "market_reference", "publishable": False}), "# 경매 참고 자료 (원본 DB 정규화)", "",
                 "> [!caution] 원본 `art_market.db`를 바꾸지 않고 통화·낙찰 상태·가격 기준을 분리한 참고 자료입니다. "
                 "'비교 가능'은 같은 가격 기준(낙찰가 / 수수료 포함가)·USD 환산이 가능하다는 기계적 조건일 뿐 검증된 시장 통계가 아닙니다. "
                 "경매사 약관 검토 전에는 게시하지 않습니다.", "",
                 "## 경매사별", "", "| 경매사 | 랏 | 낙찰 | 비교 가능 | 첫 경매 | 마지막 경매 |", "|---|---|---|---|---|---|"]
        lines += [f"| {cell(h[0])} | {h[1]:,} | {h[2] or 0:,} | {h[3] or 0:,} | {cell(h[4])} | {cell(h[5])} |" for h in houses]
        lines += ["", "## 비교 가능/제외 사유", "", "| 판정 | 랏 |", "|---|---|"] + [f"| `{cell(r[0])}` | {r[1]:,} |" for r in reasons]
        lines += ["", "## 연도 × 경매사 × 가격 기준 (비교 가능 랏만, USD 중앙값)", "",
                  "| 연도 | 경매사 | 가격 기준 | 랏 | 중앙값 USD |", "|---|---|---|---|---|"]
        bucket = collections.defaultdict(list)
        for house, year, group, usd in a.execute(
                "SELECT house, substr(sale_date,1,4), comparison_group, price_usd FROM normalized_lots "
                "WHERE price_comparability='comparable_within_basis' AND price_usd IS NOT NULL"):
            bucket[(year, house, group)].append(usd)
        for (year, house, group), values in sorted(bucket.items(), reverse=True):
            lines.append(f"| {cell(year)} | {cell(house)} | `{cell(group)}` | {len(values):,} | {statistics.median(values):,.0f} |")
        lines.append("\n낙찰가와 수수료 포함가는 서로 비교하지 않습니다. 경매사마다 수록 기간이 달라 연도 간 증감을 시장 추세로 읽지 않습니다.")
        self.write("10_시장참고/경매 정규화 요약.md", "\n".join(lines))

    # ------------------------------------------------------------------------------------------- daily insight
    def _events_for(self, edition: str):
        return [ev for ev in self.events.values() if ev["edition_region"] == edition]

    # -- daily report helpers
    def is_specialist(self, a: dict) -> bool:
        """Art-specialist outlets and official institution feeds; general-news feeds and search results are not."""
        if not hasattr(self, "_general_sources"):
            from .sources import gl_news, kr_news
            self._general_sources = {NAVER_SOURCE, LEGACY_NEWS_SOURCE} | {
                r["source_id"] for r in kr_news.SOURCES + gl_news.SOURCES if r.get("art_filter")}
        return a["source_id"] not in self._general_sources

    def find_entity(self, name: str) -> Optional[str]:
        """A noted entity whose canonical name equals `name` (exact, casefold); None when absent or ambiguous."""
        if not hasattr(self, "_by_name"):
            idx: Dict[str, List[str]] = collections.defaultdict(list)
            for eid in self.noted_entities:
                idx[(self.entities[eid]["canonical_name"] or "").casefold()].append(eid)
            self._by_name = idx
        hits = self._by_name.get(name.casefold(), [])
        return hits[0] if len(hits) == 1 else None

    def home_editions(self) -> Dict[str, str]:
        """entity_id -> edition holding most of its events (organiser, venue owner or participant)."""
        if not hasattr(self, "_home"):
            counts: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
            for ev in self.events.values():
                if not ev["edition_region"]:
                    continue
                ids = {ev["organizer_entity_id"], (self.venues.get(ev["venue_id"]) or {}).get("owner_entity_id")}
                # organisations count only where they run the programme; a gallery listed as a fair exhibitor is not local
                ids |= {p["entity_id"] for p in self.participants.get(ev["event_id"], [])
                        if (self.entities.get(p["entity_id"]) or {}).get("entity_type") in PERSON_TYPES}
                for eid in ids - {None}:
                    counts[eid][ev["edition_region"]] += 1
            self._home = {eid: c.most_common(1)[0][0] for eid, c in counts.items()}
        return self._home

    def name_matcher(self, edition: str) -> news_digest.NameMatcher:
        """Institutions and venues with programme in this edition, plus artists in its last 12 months of programme."""
        if not hasattr(self, "_matchers"):
            self._matchers = {}
        if edition not in self._matchers:
            names: Dict[str, str] = {}
            since = self.asof - dt.timedelta(days=365)
            for ev in self._events_for(edition):
                for eid in (ev["organizer_entity_id"], (self.venues.get(ev["venue_id"]) or {}).get("owner_entity_id")):
                    if eid in self.noted_entities:
                        names.setdefault(self.entities[eid]["canonical_name"], eid)
                if ev["event_type"] in SHOWING_TYPES and (day(ev["start_date"]) or dt.date.min) >= since:
                    for p in self.participants.get(ev["event_id"], []):
                        if p["role"] in ("artist", "exhibitor") and p["entity_id"] in self.noted_entities:
                            names.setdefault(self.entities[p["entity_id"]]["canonical_name"], p["entity_id"])
            self._matchers[edition] = news_digest.NameMatcher(names)
        return self._matchers[edition]

    def stories(self, scope: str, start: dt.date, end: dt.date, report_day: dt.date) -> List[dict]:
        matcher = self.name_matcher(scope) if scope in EDITIONS else None
        rows = self.reading(scope, start, end)
        if scope in ("AMERICAS", "EUROPE"):  # international outlets: a story belongs where it happens
            from .daily_trend import EDITION_HINT
            other = "EUROPE" if scope == "AMERICAS" else "AMERICAS"
            for a in self.reading("GLOBAL", start, end):
                text = f"{a['title'] or ''} {a.get('excerpt') or ''}"
                if EDITION_HINT[scope].search(text) and not EDITION_HINT[other].search(text):
                    rows.append(a)
        return news_digest.build_stories(rows, self.is_specialist, matcher, report_day.isoformat())

    def source_label(self, a: dict, bare: bool = False) -> str:
        """Outlet name; search/legacy rows say how they arrived unless `bare` (lists of outlets)."""
        if a["source_id"] in (NAVER_SOURCE, LEGACY_NEWS_SOURCE):
            via = "Naver 검색" if a["source_id"] == NAVER_SOURCE else "원본 수집"
            return (a["publisher"] or "출처 미상") if bare else f"{a['publisher'] or '출처 미상'} ({via})"
        return short_source(self.sources.get(a["source_id"], {}).get("name") or a["source_id"])

    def story_title(self, a: dict, limit: int = 110) -> str:
        plain = re.sub(r"\s+", " ", a["title"] or "제목 없음").replace("[", "(").replace("]", ")").strip()
        if len(plain) > limit:
            plain = plain[:limit].rstrip() + "…"
        return f"[{plain}]({a['canonical_url']})" if a["canonical_url"] else esc(plain)

    def notes_by_url(self, d: dt.date) -> Dict[str, dict]:
        """URL -> editor judgement, from every note file near `d`: main-story notes, daily notes and award notes."""
        from . import editorial, frontpage_render
        notes, by_url = editorial.load_notes_upto(d), {}
        packets = editorial.load_packets_upto(d)
        cands = {}
        for pk in packets:
            cands.update(pk.get("candidates") or {})
        for pk in packets:
            for e in (pk.get("editions") or {}).values():
                for st in e["major"] + e["rookie"]:
                    nv = notes["major"].get(st["key"])
                    if nv and not nv.get("exclude"):
                        by_url.update({m["url"]: nv for m in st["members"]})
                    aw = notes["awards"].get(st["key"])
                    if aw:
                        by_url.update({m["url"]: self.award_note(aw, cands) for m in st["members"]})
        for key, aw in notes["awards"].items():
            if aw.get("url"):
                by_url.setdefault(aw["url"], self.award_note(aw, cands))
        for nv in notes["major"].values():
            if not nv.get("exclude"):
                by_url.update({s_["url"]: nv for s_ in nv.get("sources", [])})
        by_url.update(notes["daily"])
        return by_url

    @staticmethod
    def award_note(aw: dict, cands: dict) -> dict:
        from .frontpage_render import TRACK_LABEL
        names = [w["name"] for w in aw.get("winners", [])]
        why = [f"상: {aw['award']} — {aw.get('organizer', '')}, {TRACK_LABEL.get(aw.get('track'), '')}. {aw.get('track_reason', '')}"]
        why += [f"{w['name']}{'(' + w['genre'] + ')' if w.get('genre') else ''}: {w['why']}" for w in aw.get("winners", [])[:3] if w.get("why")]
        verdict = [f"{n} {cands[n]['status']}" for n in names if n in cands]
        so = ("ROOKIE RADAR 판단 — " + ", ".join(verdict) + ". 근거(상의 무게·루키 조건)는 홈의 ROOKIE RADAR와 '루키 관찰 명단' 노트.") if verdict \
            else "수상자 판단 전 — 명단을 확인한 뒤 ROOKIE RADAR에 넣는다."
        rewards = ", ".join(aw.get("rewards") or [])
        brief = f"{aw.get('organizer', '')}의 {aw['award']}에 {', '.join(names) or '수상자 미확인'}" + (f" — {rewards}" if rewards else "") + "."
        return dict(brief=brief, why=why, so_what=so)

    def story_lines(self, rank: int, story: dict) -> List[str]:
        a = story["lead"]
        lines = [f"{rank}. **{self.story_title(a)}** · {esc(self.source_label(a))} · {(a['published_at'] or '')[5:10]}"]
        note = next((self._note_by_url[m["canonical_url"]] for m in story["members"]
                     if m["canonical_url"] in getattr(self, "_note_by_url", {})), None)
        if note:
            lines.append(f"    - **요약** {esc(note.get('brief') or note.get('summary', ''))}")
            lines += [f"    - **왜 주요 소식** {esc(w)}" for w in note.get("why", [])[:3]]
            lines.append(f"    - **→ 그래서?** {esc(note['so_what'])}")
        else:
            from . import editorial
            j = editorial.auto_judgement(story, day(a["published_at"]) or self.asof)
            ko = useful_ko(self.ko_of("articles", a["article_id"], "title", a["title"]))
            summary = j["summary"] or (f"{ko} (제목 기준·자동번역)" if ko else "요약할 본문 발췌가 없는 매체 — 제목 기준")
            lines.append(f"    - **요약** {esc(summary)}")
            lines += [f"    - **왜 {'주요 소식' if j['level'] == '주요' else '여기 있나'}** {esc(w)}" for w in j["why"]]
            lines.append(f"    - **→ 그래서?** {esc(j['so_what'])} <small>(자동 판단 · {j['level']} {j['points']}점 · 편집 메모 없음)</small>")
        lines.append(f"    - <small>읽는 순서 점수 {story['score']} ({' · '.join(story['reasons']) or '최신순'}) · {story['topic_label']}</small>")
        if story["names"]:
            linked = [self.entity_link(eid, name) for name, eid in story["names"][:3]]
            lines.append(f"    - 관련 노트: {', '.join(linked)}")
        others = [m for m in story["members"] if m is not a]
        if others:
            outlets = sorted({self.source_label(m, bare=True) for m in others})
            lines.append(f"    - 같은 소식 {len(others)}건: {esc(', '.join(outlets[:4]))}" + (f" 외 {len(outlets) - 4}곳" if len(outlets) > 4 else ""))
        ko = useful_ko(self.ko_of("articles", a["article_id"], "title", a["title"]))
        if ko:
            lines.append(f"    - 한국어({TRANSLATION_NOTE}): {esc(ko)}")
        return lines

    def story_line(self, story: dict) -> str:
        a = story["lead"]
        more = len(story["outlets"]) - 1
        line = f"- {(a['published_at'] or '')[5:10]} · {self.story_title(a)} — {esc(self.source_label(a))}" + (f" 외 {more}곳" if more > 0 else "")
        ko = useful_ko(self.ko_of("articles", a["article_id"], "title", a["title"]))
        return line + (f"\n  - 한국어({TRANSLATION_NOTE}): {esc(ko)}" if ko else "")

    def analysis_lines(self, edition: str, d: dt.date, cards: List[dict], rookies: List[dict]) -> List[str]:
        """Blueprint front-page cards A–F (H01–H08), each as a folded callout so the report reads top-down."""
        key = lambda ev: (ev["start_date"] or "", ev["event_id"])

        def title(ev):
            return ev["title"] or "제목 없음"

        def n(value):
            return "?" if value is None else f"{value:g}"

        out: List[str] = []
        today_cards = [c for c in cards if c["edition_region"] == edition and c["asof"] == d.isoformat()]
        sections = (("A", "Core Trend", "H01"), ("B", "작가·작품 이야기", "H02"), ("C", "기관·갤러리 동향", "H04", "H05"),
                    ("D", "주제·지역 흐름", "H06", "H03"), ("E", "Rookie 관찰", "H07"), ("F", "시장 참고", "H08"))
        for code, name, *hs in sections:
            lines: List[str] = []
            section_cards = [c for c in today_cards if c["section"] in hs]
            if code == "A":
                observed = sorted(((eid, s) for eid, s in self.signals.items()
                                   if s.get("I_events_recent90") and eid in self.noted_entities and any(
                                       self.events[p["event_id"]]["edition_region"] == edition for p in self.by_entity_events.get(eid, []))),
                                  key=lambda x: (-(x[1].get("I_independent_owner_groups_recent90") or 0), -(x[1].get("I_events_recent90") or 0), x[0]))
                lines.append("트렌드 점수는 산출하지 않습니다(가중치 가설 미검증, E축 미관측, 커버리지 게이트 측정 불가).")
                if observed and d == self.asof:
                    lines += ["최근 90일 서로 다른 기관에서 관찰된 작가 후보(내부 참고, 순위 아님):", ""]
                    for eid, s in observed[:5]:
                        lines.append(f"- {self.entity_link(eid)} — 최근 90일 행사 {n(s.get('I_events_recent90'))}건, 독립 기관 그룹 "
                                     f"{n(s.get('I_independent_owner_groups_recent90'))}곳, 이전 90일 {n(s.get('I_events_prev90'))}건")
                count = len(observed) if d == self.asof else 0
            else:
                for card in section_cards:
                    kind = "근거 부족 안내" if card["card_kind"] == "gap_notice" else "초안 카드"
                    lines.append(f"- {kind}: {link(self.card_note_name(card), card['title'])}")
                    if card.get("facts") and card["card_kind"] != "gap_notice":
                        for fact in card["facts"].splitlines()[:4]:
                            lines.append(f"  - {esc(fact)}")
                if not section_cards and d != self.asof:
                    lines.append(f"- 카드 스냅샷은 {self.asof.isoformat()} 하나뿐이라 이 날짜에는 카드가 없습니다.")
                elif not section_cards:
                    lines.append("- 이 에디션에는 해당 섹션 카드가 없습니다(근거 부족).")
                if code == "E" and rookies:
                    lines += ["", "최근 12개월 공식 선정·레지던시·시상 기록:", ""]
                    for ev in sorted(rookies, key=key, reverse=True)[:8]:
                        who = ", ".join(self.entity_link(p["entity_id"], p["name_as_listed"]) for p in self.participants.get(ev["event_id"], [])[:4])
                        lines.append(f"- {ev['start_date'] or ev['announced_date'] or '날짜 미상'} · {link(self.names[('event', ev['event_id'])], title(ev))}"
                                     + (f" — {who}" if who else ""))
                    lines.append("")
                    lines.append("선정 1건은 관찰 후보일 뿐 Rookie 확정이 아니며 경력 단계는 확인하지 않았습니다.")
                if code == "F":
                    lines.append("- 경매 데이터는 비교 기준이 다른 참고 자료입니다: [[경매 정규화 요약]]")
                count = sum(c["card_kind"] != "gap_notice" for c in section_cards)
            badge = f"초안 {count}건" if count else "근거 부족"
            out += callout("abstract", f"{code}. {name} ({'/'.join(hs)}) — {badge}", lines, folded=True) + [""]
        return out

    def daily(self, edition: str, d: dt.date, cards: List[dict]) -> str:
        week_ago, horizon = d - dt.timedelta(days=6), d + dt.timedelta(days=14)
        showing = [ev for ev in self._events_for(edition) if ev["event_type"] in SHOWING_TYPES]
        open_now, opened, upcoming, closing = [], [], [], []
        for ev in showing:
            start, end = day(ev["start_date"]), day(ev["end_date"])
            if start and end and start <= d <= end:
                open_now.append(ev)
                if (end - d).days <= 7:
                    closing.append(ev)
            if start and week_ago <= start <= d:
                opened.append(ev)
            if start and d < start <= horizon:
                upcoming.append(ev)
        rookies = [ev for ev in self._events_for(edition) if ev["event_type"] in ROOKIE_TYPES
                   and (day(ev["announced_date"]) or day(ev["start_date"]) or dt.date.min) >= d - dt.timedelta(days=365)
                   and (day(ev["announced_date"]) or day(ev["start_date"]) or dt.date.max) <= d + dt.timedelta(days=120)]
        key = lambda ev: (ev["start_date"] or "", ev["event_id"])
        opened.sort(key=key, reverse=True); upcoming.sort(key=key); closing.sort(key=lambda ev: ev["end_date"] or "")
        open_now.sort(key=key, reverse=True)
        cities = collections.Counter(ev["city"] for ev in open_now if ev["city"])
        venues_open = {ev["venue_id"] or ev["organizer_entity_id"] or ev["source_id"] for ev in open_now}
        label = EDITION_KO[edition]
        week_stories = self.stories(edition, week_ago, d, d)
        n_articles = sum(len(s["members"]) for s in week_stories)
        # Top stories: the last two days first; older stories of the week only fill empty places.
        recent = [s for s in week_stories if (day(s["lead"]["published_at"]) or dt.date.min) >= d - dt.timedelta(days=1)]
        top = (recent + [s for s in week_stories if s not in recent])[:TOP_STORIES]
        top_ids = {id(s) for s in top}
        by_topic: Dict[str, List[dict]] = collections.defaultdict(list)
        for s in week_stories:
            by_topic[s["topic"]].append(s)

        def title(ev):
            return ev["title"] or "제목 없음"

        def artists(ev, n=4):
            names = [p for p in self.participants.get(ev["event_id"], []) if p["role"] in ("artist", "exhibitor")]
            shown = [self.entity_link(p["entity_id"], p["name_as_listed"]) for p in names[:n]]
            return ", ".join(shown) + (f" 외 {len(names) - n}명" if len(names) > n else "")

        lines = [front_matter({"type": "daily_insight", "edition": edition, "date": d.isoformat(), "publishable": False,
                               "status": "draft_unreviewed", "open_events": len(open_now), "articles_7d": n_articles,
                               "stories_7d": len(week_stories), "tags": ["daily-insight", f"edition/{edition}"]}),
                 f"# ARTREND {label} · 데일리 리포트 · {d.isoformat()} ({WEEKDAY_KO[d.weekday()]})", "", DRAFT_CALLOUT, ""]
        # navigation: previous/next day inside the generated range, and the same day in the other editions
        first = self.asof - dt.timedelta(days=self.days - 1)
        nav = []
        if d > first:
            prev = d - dt.timedelta(days=1)
            nav.append(link(f"{prev.isoformat()} {label}", f"← {prev.isoformat()}"))
        nav += [link("데일리 인사이트 목록", "목록"), link(f"{label} 에디션", f"{label} 에디션")]
        if d < self.asof:
            nxt = d + dt.timedelta(days=1)
            nav.append(link(f"{nxt.isoformat()} {label}", f"{nxt.isoformat()} →"))
        others = [link(f"{d.isoformat()} {EDITION_KO[e]}", EDITION_KO[e]) for e in EDITIONS if e != edition]
        lines += [" · ".join(nav), "", "같은 날 다른 에디션: " + " · ".join(others), ""]

        # 0. at a glance: editor summary + observed insights first (W42), counts after
        from . import editorial, frontpage_render
        notes = editorial.load_notes(d)
        home = f"ARTREND {label} 홈" if d == self.asof and edition in frontpage_render.EDITION_KO else ""
        from .daily_trend import trend_lines
        glance = frontpage_render.glance_lines(notes, edition, anchor_page=home, heading="## 한눈에",
                                               trend=trend_lines(self, edition, d, week_stories))
        self._note_by_url = self.notes_by_url(d)
        if glance:
            lines += glance
        else:
            lines += ["## 한눈에", "", "> [!empty] 이날은 편집 요약이 없습니다", "> 아래 순서는 자동 점수(보도 수·전문지·이름·수상·금액)이며 '왜 중요한가'는 편집 메모(`editorial/notes_<날짜>.json`)가 있어야 나옵니다.", ""]
        lines += ["### 숫자로 본 오늘", "",
                  "| 진행 중 전시 | 이번 주 개막 | 2주 내 개막 | 7일 내 종료 | 지난 7일 기사 | 소식(같은 기사 묶음) |",
                  "|---:|---:|---:|---:|---:|---:|",
                  f"| {len(open_now)} | {len(opened)} | {len(upcoming)} | {len(closing)} | {n_articles:,} | {len(week_stories):,} |", ""]
        if open_now or opened or upcoming:
            city_text = ", ".join(f"{c} {k}건" for c, k in cities.most_common(3))
            lede = (f"{d.month}월 {d.day}일, 관찰 중인 {label} 기관·갤러리 {len(venues_open)}곳에서 전시와 프로그램 {len(open_now)}건이 열려 있습니다."
                    + (f" 도시별로는 {city_text}입니다." if city_text else ""))
            lede += f" 지난 7일 동안 {len(opened)}건이 새로 개막했고, 앞으로 2주 안에 {len(upcoming)}건이 문을 엽니다."
            if closing:
                lede += f" 이번 주 안에 막을 내리는 전시는 {len(closing)}건입니다."
        else:
            lede = (f"{d.isoformat()} 기준 {label} 에디션의 관찰 범위에서는 일 단위 기간이 확인된 진행 중 전시가 없습니다. "
                    "수집 범위 공백이며 '전시가 없다'는 뜻이 아닙니다.")
        if week_stories:
            topics = sorted(((k, len(v)) for k, v in by_topic.items() if k != news_digest.OTHER_TOPIC[0]), key=lambda x: -x[1])
            lede += (f" 기사 {n_articles:,}건은 같은 소식끼리 묶으면 {len(week_stories):,}개입니다."
                     + (f" 가장 많은 주제는 {TOPIC_LABEL[topics[0][0]]} {topics[0][1]:,}개입니다." if topics else ""))
        lines += [lede, ""]

        # 1. top stories
        lines += ["## 1. 오늘의 주요 소식", ""]
        if top:
            for i, s in enumerate(top, 1):
                lines += self.story_lines(i, s)
            lines.append("")
            lines += callout("info", "고르는 규칙", SCORE_RULES, folded=True) + [""]
        else:
            lines += [f"- 지난 7일 {label} 매체·기관 출처의 새 글이 관찰되지 않았습니다.", ""]

        # 2. calendar
        lines += ["## 2. 전시 캘린더", ""]
        lines += [f"### 이번 주 개막 ({len(opened)})", ""]
        if opened:
            for ev in opened[:6]:
                who = artists(ev)
                lines.append(f"- **{link(self.names[('event', ev['event_id'])], title(ev))}** — {self.venue_text(ev)}. "
                             f"{period(ev['start_date'], ev['end_date'])}." + (f" 참여: {who}." if who else ""))
            if len(opened) > 6:
                lines.append(f"- 외 {len(opened) - 6}건은 맨 아래 '부록'에 있습니다.")
        else:
            lines.append("- 관찰 범위에서 이번 주 개막한 전시가 없습니다.")
        lines += ["", f"### 곧 개막 · 2주 안 ({len(upcoming)})", ""]
        lines += [f"- {ev['start_date']} · {link(self.names[('event', ev['event_id'])], title(ev))} — {self.venue_text(ev)}" for ev in upcoming[:8]] \
            or ["- 관찰 범위에서 2주 안에 개막 예정인 전시가 없습니다."]
        if len(upcoming) > 8:
            lines.append(f"- 외 {len(upcoming) - 8}건")
        lines += ["", f"### 놓치기 전에 · 7일 안 종료 ({len(closing)})", ""]
        lines += [f"- ~{ev['end_date']} · {link(self.names[('event', ev['event_id'])], title(ev))} — {self.venue_text(ev)}" for ev in closing[:8]] \
            or ["- 관찰 범위에서 7일 안에 끝나는 전시가 없습니다."]
        lines.append("")

        # 3. by topic (the top stories are not repeated)
        lines += ["## 3. 주제별 소식 · 지난 7일", ""]
        any_topic = False
        for topic_key, topic_label in TOPIC_ORDER:
            rest = [s for s in by_topic.get(topic_key, []) if id(s) not in top_ids]
            if not rest:
                continue
            any_topic = True
            lines += [f"### {topic_label} ({len(by_topic[topic_key]):,})", ""] + [self.story_line(s) for s in rest[:PER_TOPIC]]
            if len(rest) > PER_TOPIC:
                lines.append(f"- 외 {len(rest) - PER_TOPIC:,}개 소식: [[_기사·비평 목록]]")
            lines.append("")
        if not any_topic:
            lines += ["- 주요 소식 밖의 기사가 없습니다.", ""]

        # 4. global criticism / announcements
        global_stories = self.stories("GLOBAL", week_ago, d, d)
        if global_stories:
            crit = [s for s in global_stories if s["topic"] == "criticism"]
            rest = [s for s in global_stories if s["topic"] != "criticism"]
            lines += ["## 4. 글로벌 비평·공지 · 지난 7일", ""]
            if crit:
                lines += ["### 비평·리뷰", ""] + [self.story_line(s) for s in crit[:5]] + [""]
            if rest:
                lines += ["### 소식·공지", ""] + [self.story_line(s) for s in rest[:5]] + [""]

        # 5. analysis cards
        lines += ["## 5. 분석 카드 (Blueprint H01–H08)", "", "카드는 모두 `publishable=0` 초안입니다. 제목을 눌러 펼칩니다.", ""]
        lines += self.analysis_lines(edition, d, cards, rookies)

        # 6. editor
        lines += ["## 6. 편집자 메모", "",
                  "> [!question] 왜 지금인가?",
                  "> 데이터는 개막 사실·기간·보도 건수만 말합니다. 선정 이유와 맥락은 원문 보도자료·전시 서문·기사를 읽은 뒤 작성합니다.",
                  "", "- [ ] 주요 소식 1~3번 원문 확인", "- [ ] 이번 주 개막 전시 중 취재 후보 표시", "- [ ] 자동번역 제목은 원문으로 다시 읽기", ""]

        # appendix: everything open now, folded
        lines += [f"## 부록. 지금 열려 있는 전시 전체 ({len(open_now)})", ""]
        if open_now:
            rows = ["| 시작 | 종료 | 행사 | 장소 |", "|---|---|---|---|"]
            for ev in open_now[:80]:
                rows.append(f"| {cell(ev['start_date'])} | {cell(ev['end_date'])} | {self.event_link(ev['event_id'], True)} | "
                            f"{flat(self.venue_text(ev, True))} |")
            if len(open_now) > 80:
                rows += ["", f"진행 중 {len(open_now)}건 중 최근 개막 80건만 표시합니다."]
            lines += callout("note", "펼쳐서 보기", rows, folded=True)
        else:
            lines.append("- 없음")
        lines += ["", "---", f"생성 근거: `db/artrend_magazine.sqlite` · 기준일 {d.isoformat()} · 일 단위 기간이 확인된 행사만 집계 · "
                  f"에디션은 개최 장소 기준 · 기사 순서는 설명 가능한 점수(편집 판단 아님)"]
        return "\n".join(lines)

    def reading(self, scope: str, start: dt.date, end: dt.date) -> List[dict]:
        if not hasattr(self, "_reading_rows"):
            self._reading_rows = [dict(r) for r in self.con.execute(
                "SELECT a.*, s.region_scope FROM articles a JOIN sources s USING(source_id) "
                "WHERE s.operational_state != 'blocked_permission' AND coalesce(a.article_type,'') != 'sponsored' "
                "AND a.published_at IS NOT NULL ORDER BY a.published_at DESC, a.article_id")]
        out = []
        for a in self._reading_rows:
            if a["source_id"] in READING_EXCLUDED_SOURCES:
                continue
            if (a["type_basis"] or "").endswith(":snippet"):  # Naver hit whose art words are only in the snippet
                continue
            if a["source_id"] == LEGACY_NEWS_SOURCE:
                article_scope = LEGACY_NEWS_LANG_SCOPE.get(a["lang"], "GLOBAL")
            elif a["region_scope"] == "GLOBAL":
                article_scope = "GLOBAL"
            else:
                article_scope = ARTICLE_SCOPE_EDITION.get(a["region_scope"])
            if article_scope != scope:
                continue
            published = day(a["published_at"])
            if published and start <= published <= end:
                out.append(a)
        return out

    def article_line(self, a: dict) -> str:
        ko = self.ko_of("articles", a["article_id"], "title", a["title"])
        plain = re.sub(r"\s+", " ", a["title"] or "제목 없음").replace("[", "(").replace("]", ")")
        title = f"[{plain}]({a['canonical_url']})" if a["canonical_url"] else esc(plain)
        source = self.source_label(a)
        return f"- {(a['published_at'] or '')[:10]} · {source} · {title}" + (f"\n  - 한국어({TRANSLATION_NOTE}): {esc(ko)}" if ko else "")

    def write_daily(self) -> None:
        cards = self.cards()
        dates = [self.asof - dt.timedelta(days=i) for i in range(self.days)]
        index = [front_matter({"type": "index"}), "# 데일리 인사이트 목록", "", DRAFT_CALLOUT,
                 "메인페이지 샘플입니다. 순서: 한눈에 → 1 주요 소식 → 2 전시 캘린더 → 3 주제별 소식 → 4 글로벌 비평 → 5 분석 카드(H01–H08, 접힘) → 6 편집자 메모 → 부록.", "",
                 "| 날짜 | " + " | ".join(EDITION_KO[e] for e in EDITIONS) + " |", "|---|" + "---|" * len(EDITIONS)]
        for d in dates:
            row = []
            for edition in EDITIONS:
                name = f"{d.isoformat()} {EDITION_KO[edition]}"
                self.write(f"01_데일리인사이트/{d.isoformat()}/{name}.md", self.daily(edition, d, cards))
                row.append(table_link(name, EDITION_KO[edition]))
            index.append(f"| {d.isoformat()} | " + " | ".join(row) + " |")
        self.write("01_데일리인사이트/데일리 인사이트 목록.md", "\n".join(index))

    def card_link(self, card: dict) -> str:
        return link(self.card_note_name(card), card["title"])

    def report_link(self, report: dict) -> str:
        name = self.names.get(("report", report["report_id"]))
        return link(name, report["title"]) if name else esc(report["title"])

    def write_frontpages(self) -> None:
        from . import frontpage, frontpage_render
        self.front_snapshots = frontpage.build_all(self, self.asof)
        from . import editorial
        packets, notes, watch = editorial.load_packets(self.asof), editorial.load_notes(self.asof), editorial.load_watchlist()
        self.editorial_notes = notes
        for region, snap in self.front_snapshots.items():
            r = frontpage_render.Renderer(self, snap)
            r.editorial = frontpage_render.EditorialRenderer(self, region, packets, notes, watch)
            self.write(f"00_프런트페이지/ARTREND {r.label} 홈.md", r.page())
            self.write(f"00_프런트페이지/선발 기록/선발 기록 ({r.label}).md", r.audit_page())
        self.write("00_프런트페이지/데이터 부족 점검.md", frontpage_render.gap_overview(self, self.front_snapshots))
        self.write("00_프런트페이지/루키 관찰 명단.md", frontpage_render.watchlist_page(self, watch, self.asof))
        self.write("00_프런트페이지/프런트페이지 로직.md", frontpage_render.logic_note(self.asof))
        self.front_json = {region: frontpage_render.snapshot_json(self, snap) for region, snap in self.front_snapshots.items()}

    def write_editions(self) -> None:
        for edition in EDITIONS:
            label = EDITION_KO[edition]
            evs = self._events_for(edition)
            by_year = collections.Counter(self.event_folder(ev).rsplit("/", 1)[1] for ev in evs)
            by_type = collections.Counter(ev["event_type"] for ev in evs)
            by_country = collections.Counter(ev["country_code"] or "?" for ev in evs)
            by_source = collections.Counter(ev["source_id"] for ev in evs)
            lines = [front_matter({"type": "edition", "edition": edition}), f"# {label} 에디션", "",
                     f"- 오늘의 데일리 인사이트: [[{self.asof.isoformat()} {label}]]",
                     f"- 행사 {len(evs):,}건 · 국가 {', '.join(f'{k} {v}' for k, v in by_country.most_common(8))}",
                     f"- 유형: {', '.join(f'{EVENT_TYPE_KO.get(k, k)} {v}' for k, v in by_type.most_common())}", "",
                     "## 연도별 목록", ""]
            for year in sorted(by_year, reverse=True):
                lines.append(f"- [[_{label} {year} 목록|{year}]] — {by_year[year]:,}건")
            lines += ["", "## 출처별 행사 수", "", "| 출처 | 행사 |", "|---|---|"]
            lines += [f"| {self.source_link(s, True)} | {n:,} |" for s, n in by_source.most_common()]
            self.write(f"02_에디션/{label} 에디션.md", "\n".join(lines))
        unassigned = [ev for ev in self.events.values() if not ev["edition_region"]]
        self.write("02_에디션/미지정.md", "\n".join([
            front_matter({"type": "edition", "edition": None}), "# 에디션 미지정", "",
            f"개최 장소 국가를 확인하지 못한 행사 {len(unassigned):,}건입니다. 추정해서 배정하지 않습니다.", "",
            "- 목록: `03_전시·프로그램/미지정/` 폴더"]))

    def write_home(self, stats: Dict[str, int]) -> None:
        m = self.manifest
        val = m.get("validation", {})
        ts = m.get("translation_status", {})
        lines = [front_matter({"type": "home", "asof": self.asof.isoformat()}), "# ARTREND 데이터 볼트", "",
                 f"기준일 **{self.asof.isoformat()}** · 원본: `db/artrend_magazine.sqlite` (스키마 {self._meta('schema_version')}) · 모든 페이지는 내부 열람용 초안입니다.", "",
                 "## 바로 가기", "",
                 "- **프런트페이지 목업**: " + " · ".join(f"[[ARTREND {EDITION_KO[e]} 홈|{EDITION_KO[e]}]]" for e in ("KR", "JP", "AMERICAS", "EUROPE"))
                 + " · [[프런트페이지 로직]] · [[데이터 부족 점검]]",
                 "- 오늘의 데일리 인사이트: " + " · ".join(f"[[{self.asof.isoformat()} {EDITION_KO[e]}|{EDITION_KO[e]}]]" for e in EDITIONS),
                 "- [[데일리 인사이트 목록]] (최근 날짜별 메인페이지 샘플)",
                 "- 에디션: " + " · ".join(f"[[{EDITION_KO[e]} 에디션|{EDITION_KO[e]}]]" for e in EDITIONS) + " · [[미지정]]",
                 "- [[_출처 목록]] · [[_기사·비평 목록]] · [[_리포트 목록]] · [[_증거카드 목록]] · [[_시장참고]] · [[_소장품 요약]]",
                 "- [[읽는 법]] · [[데이터 한계]]", "",
                 "## 볼트에 담긴 것", "", "| 항목 | 노트/행 |", "|---|---|"]
        lines += [f"| {k} | {v:,} |" for k, v in stats.items()]
        lines += ["", "## 검증 상태", "",
                  f"- 검증 실패 {val.get('failures', '?')} · 경고 {val.get('warnings', '?')} (검증 {val.get('validated_at', '?')})",
                  "- 번역: " + ", ".join(f"{k} {v:,}" for k, v in sorted(ts.items())) if ts else "- 번역 상태: manifest 없음",
                  "- 신호·카드 `publishable=0`. 자동번역은 모두 검수 전입니다."]
        self.write("00_홈.md", "\n".join(lines))
        self.write("00_안내/읽는 법.md", "\n".join([
            front_matter({"type": "guide"}), "# 읽는 법", "",
            "- **폴더**: 01 데일리 인사이트 → 02 에디션 → 03 전시·프로그램(에디션/연도) → 04 작가(첫 글자) → 05 기관(유형) → 06 기사·비평(출처/월) → 07 리포트 → 08 증거카드 → 09 출처(운영 상태) → 10 시장참고 → 11 소장품.",
            "- **링크**: 작가·기관·행사·출처는 서로 위키링크로 이어집니다. 그래프 보기와 백링크 패널로 연결을 따라갈 수 있습니다.",
            "- **속성**: 모든 노트 맨 위 YAML에 `type`, `edition`, `start`, `source_id`, `publishable` 등이 있어 Obsidian 속성 보기·Dataview로 거를 수 있습니다.",
            "- **번역**: '한국어(자동번역·검수 전)'은 로컬 모델 자동번역입니다. 원문을 항상 옆에 둡니다. 이름 누락·의미 왜곡이 표본에서 확인되었으니 인용 전 원문을 봅니다.",
            "- **에디션**: 개최 장소 기준입니다. 홍콩·중국·대만·중동은 '기타', 국가 미상은 '미지정'입니다.",
            "- **날짜**: 연도만 아는 행사는 `YYYY`로 둡니다. 데일리 집계는 일 단위 기간이 확인된 행사만 셉니다.",
            "- **동일인**: 이름이 같아도 같은 사람으로 확정하지 않습니다. '동일인 후보 연결'은 근거와 상태(candidate/confirmed)를 함께 보여 줍니다.",
            "- **이미지**: 내려받거나 넣지 않았습니다. 원문 링크로 확인합니다.",
            "- **다시 만들기**: `.venv/bin/python -m artrend_mag.cli vault` (수집·번역 갱신 뒤 실행)."]))
        limits = m.get("limitations") or []
        attention = (m.get("public_source_batch") or {}).get("attention") or []
        lines = [front_matter({"type": "guide"}), "# 데이터 한계", "",
                 "미소진·기술 제한·권한/키 제한은 서로 다른 뜻입니다. 자세한 상태는 각 출처 노트의 '최근 실행'에 있습니다.", ""]
        if limits:
            lines += ["## manifest 기록", ""] + [f"- {cell(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))}" for x in limits] + [""]
        if attention:
            lines += ["## 최근 실행에서 주의가 필요한 출처", "", "| 출처 | 모드 | 상태 | 저장 | 사유 |", "|---|---|---|---|---|"]
            lines += [f"| {self.source_link(x.get('source_id'), True)} | {cell(x.get('mode'))} | {cell(x.get('state'))} | {cell(x.get('inserted'))} | {cell((x.get('reason') or '')[:160])} |"
                      for x in attention]
        self.write("00_안내/데이터 한계.md", "\n".join(lines))

    def _meta(self, key: str) -> str:
        row = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else "?"

    def build(self) -> Dict[str, int]:
        self.load()
        self.write_events()
        self.write_entities()
        self.write_sources()
        self.write_articles()
        self.write_reports()
        self.write_cards()
        self.write_works()
        self.write_market()
        self.write_editions()
        self.write_daily()
        self.write_frontpages()
        person = sum(self.entities[e]["entity_type"] in PERSON_TYPES for e in self.noted_entities)
        stats = {"데일리 인사이트 페이지": self.days * len(EDITIONS), "전시·프로그램 노트": len(self.events),
                 "작가 노트": person, "기관 노트": len(self.noted_entities) - person, "출처 노트": len(self.sources)}
        self.write_home(stats)
        (self.out / ".obsidian").mkdir(exist_ok=True)
        (self.out / ".obsidian" / "app.json").write_text(json.dumps({"showFrontmatter": True, "useMarkdownLinks": False,
                                                                    "newLinkFormat": "shortest"}, indent=2), encoding="utf-8")
        (self.out / "99_내메모").mkdir(exist_ok=True)
        (self.out / "99_내메모" / "여기에 메모.md").write_text(
            "# 내 메모\n\n이 폴더와 `.obsidian` 설정은 `cli vault`로 다시 만들어도 유지됩니다. 다른 폴더는 매번 새로 생성됩니다.\n",
            encoding="utf-8")
        stats["파일 합계"] = self.files
        return stats


def build_vault(out: Path, asof: dt.date, days: int = 7, db_path: Path = DB_PATH,
                auction_path: Optional[Path] = None, manifest_path: Optional[Path] = None) -> Dict[str, int]:
    out = Path(out)
    staging = out.with_name(out.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    auction = sqlite3.connect(f"file:{auction_path}?mode=ro", uri=True) if auction_path and Path(auction_path).exists() else None
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8")) if manifest_path and Path(manifest_path).exists() else {}
    try:
        builder = VaultBuilder(con, staging, asof, days, auction, manifest)
        stats = builder.build()
        snapshot_dir = out.parent / "frontpage"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for region, payload in getattr(builder, "front_json", {}).items():
            (snapshot_dir / f"ARTREND_home_{region}_{asof.isoformat()}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    finally:
        con.close()
        if auction is not None:
            auction.close()
    if out.exists():
        for keep in USER_OWNED:
            if (out / keep).exists():
                shutil.rmtree(staging / keep, ignore_errors=True)
                shutil.move(str(out / keep), str(staging / keep))
        shutil.rmtree(out)
    staging.rename(out)
    install_css(out)
    return stats


def install_css(vault: Path) -> None:
    """Write the home mock-up snippet (ours, overwritten) and enable it without touching other appearance settings."""
    from .frontpage_render import CSS
    snippets = vault / ".obsidian" / "snippets"
    snippets.mkdir(parents=True, exist_ok=True)
    (snippets / "artrend-home.css").write_text(CSS, encoding="utf-8")
    appearance = vault / ".obsidian" / "appearance.json"
    data = json.loads(appearance.read_text(encoding="utf-8")) if appearance.exists() else {}
    enabled = data.setdefault("enabledCssSnippets", [])
    if "artrend-home" not in enabled:
        enabled.append("artrend-home")
        appearance.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main(asof: Optional[str] = None, days: int = 7, out: Optional[str] = None) -> Dict[str, int]:
    target = Path(out) if out else WORK_ROOT / "outputs" / "ARTREND_Obsidian_Vault"
    stats = build_vault(target, dt.date.fromisoformat(asof) if asof else dt.date.today(), days,
                        auction_path=WORK_ROOT / "db" / "auction_normalized.sqlite",
                        manifest_path=WORK_ROOT / "outputs" / "delivery_manifest.json")
    print(json.dumps({"vault": str(target), **stats}, ensure_ascii=False))
    return stats
