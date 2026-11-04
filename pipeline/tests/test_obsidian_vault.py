import datetime as dt
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from artrend_mag import db
from artrend_mag import obsidian_vault as ov
from artrend_mag.translation import ensure_translation_table


def insert(con, table, **row):
    con.execute(f"INSERT INTO {table}({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


SEEN = dict(first_seen_at="2026-10-29", last_seen_at="2026-10-29")


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    db.init_schema(con)
    ensure_translation_table(con)
    for sid, name, scope, state in (("src_kr", "KR Museum — listing", "KR", "active"),
                                    ("src_blocked", "Restricted Mag", "GLOBAL", "blocked_permission"),
                                    ("src_crit", "Global Critique", "GLOBAL", "active"),
                                    ("legacy_v2v_artnews", "v2v artnews.db", "GLOBAL", "local_only"),
                                    ("kr_naver_news_api", "Naver 뉴스 검색 API", "KR", "active")):
        insert(con, "sources", source_id=sid, name=name, source_kind="web", access_method="html", region_scope=scope,
               operational_state=state)
    insert(con, "entities", entity_id="ent_museum0001", entity_type="institution", canonical_name="Seoul Museum",
           id_namespace="t", id_value="m", **SEEN)
    insert(con, "entities", entity_id="ent_artist0001", entity_type="person", canonical_name="Kim [[Draft]] Artist",
           id_namespace="t", id_value="a", **SEEN)
    events = [
        ("evt_open000001", "Open Show", "2026-10-25", "2026-11-30"),     # opened this week, open now
        ("evt_soon000001", "Soon Show", "2026-11-05", "2026-12-01"),     # upcoming within 14 days
        ("evt_year000001", "Year Only", "2026", None),                   # year precision: never counted
    ]
    for eid, title, start, end in events:
        insert(con, "events", event_id=eid, source_id="src_kr", source_event_key=eid, event_type="exhibition", title=title,
               organizer_entity_id="ent_museum0001", city="Seoul", country_code="KR", edition_region="KR",
               start_date=start, end_date=end, content_hash="h", parser_version="t", **SEEN)
    insert(con, "event_participants", event_id="evt_open000001", entity_id="ent_artist0001", role="artist",
           name_as_listed="Kim Artist", extraction_method="test")
    # Observed in The Met CSV: catalogue titles wrapped in brackets, which would open a wikilink inside "[...](url)".
    insert(con, "works", work_id="wrk_bracket001", id_namespace="t", id_value="w", artist_entity_id="ent_artist0001",
           title="[Floyd on Porch]", url="https://x.test/w", source_id="src_kr", **SEEN)
    insert(con, "articles", article_id="art_blocked001", source_id="src_blocked", canonical_url="https://x.test/a",
           title="Restricted Title", article_type="news", published_at="2026-10-28", content_hash="h", **SEEN)
    insert(con, "articles", article_id="art_crit00001", source_id="src_crit", canonical_url="https://x.test/c",
           title="A critique of the new museum wing", article_type="criticism", published_at="2026-10-27", content_hash="h", **SEEN)
    insert(con, "articles", article_id="art_legacyko01", source_id="legacy_v2v_artnews", canonical_url="https://x.test/k",
           title="서울 갤러리 개인전 개막", article_type="unknown", lang="ko", publisher="뉴시스", published_at="2026-10-26", content_hash="h", **SEEN)
    for aid, title, tier in (("art_naver_t001", "국립현대미술관 신소장품전 개막", "title"), ("art_naver_s001", "은행 위문금 전달", "snippet")):
        insert(con, "articles", article_id=aid, source_id="kr_naver_news_api", canonical_url=f"https://x.test/{aid}", title=title,
               article_type="news", type_basis=f"naver_search_api:{tier}", lang="ko", publisher="yna.co.kr",
               published_at="2026-10-28", content_hash="h", **SEEN)
    insert(con, "metadata_translations", source_table="articles", source_key="art_crit00001", source_field="title",
           source_text_hash="h", original_text="A critique of the new museum wing", translation_ko="새 미술관 별관에 대한 비평", model="m", model_version="1",
           target_lang="ko", language_basis="metadata", language_detector_version="t", source_lang="en", status="translated", needs_review=1, created_at="x", updated_at="x")
    con.commit()
    con.close()


class ReadingOrderTests(unittest.TestCase):
    def test_one_busy_outlet_cannot_fill_the_reading_list(self):
        rows = [dict(source_id="a", publisher="A", id=i) for i in range(3)] + [dict(source_id="b", publisher="B", id=9)]
        self.assertEqual([(r["publisher"], r["id"]) for r in ov.interleave_by_source(rows)], [("A", 0), ("B", 9), ("A", 1), ("A", 2)])


class VaultBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        make_db(root / "t.sqlite")
        self.out = root / "vault"
        self.stats = ov.build_vault(self.out, dt.date(2026, 10, 29), days=2, db_path=root / "t.sqlite")
        self.files = {p.stem: p.read_text(encoding="utf-8") for p in self.out.rglob("*.md")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_wikilink_resolves_to_a_unique_note(self):
        names = [p.stem.casefold() for p in self.out.rglob("*.md")]
        self.assertEqual(len(names), len(set(names)))
        for stem, text in self.files.items():
            for target in re.findall(r"(?<!\\)\[\[([^\]|\\]+)", text):
                if target.startswith("#"):  # heading link inside the same note
                    continue
                self.assertIn(target.casefold(), names, f"{stem} -> {target}")

    def test_daily_page_counts_only_day_precision_events_and_stays_unpublishable(self):
        page = self.files["2026-10-29 한국"]
        self.assertIn("publishable: false", page)
        self.assertIn("전시와 프로그램 1건이 열려 있습니다", page)
        self.assertIn("지난 7일 동안 1건이 새로 개막했고, 앞으로 2주 안에 1건이 문을 엽니다", page)
        self.assertNotIn("Year Only", page)

    def test_permission_restricted_articles_are_excluded_and_translations_keep_originals(self):
        all_text = "\n".join(self.files.values())
        self.assertNotIn("Restricted Title", all_text)
        page = self.files["2026-10-29 한국"]
        self.assertIn("[A critique of the new museum wing](https://x.test/c)", page)
        self.assertIn("한국어(자동번역·검수 전): 새 미술관 별관에 대한 비평", page)

    def test_original_v2v_korean_news_is_read_on_the_korean_page_only(self):
        self.assertIn("[서울 갤러리 개인전 개막](https://x.test/k)** · 뉴시스 (원본 수집)", self.files["2026-10-29 한국"])
        self.assertNotIn("서울 갤러리 개인전 개막", self.files["2026-10-29 일본"])

    def test_naver_items_need_an_art_word_in_the_title_to_be_read(self):
        page = self.files["2026-10-29 한국"]
        self.assertIn("[국립현대미술관 신소장품전 개막]", page)
        self.assertIn("· yna.co.kr (Naver 검색) ·", page)
        self.assertNotIn("은행 위문금 전달", page)

    def test_daily_report_is_ordered_and_secondary_blocks_are_folded(self):
        page = self.files["2026-10-29 한국"]
        heads = ["## 한눈에", "## 1. 오늘의 주요 소식", "## 2. 전시 캘린더", "## 3. 주제별 소식", "## 5. 분석 카드", "## 6. 편집자 메모", "## 부록."]
        positions = [page.index(h) for h in heads]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("> [!info]- 고르는 규칙", page)
        self.assertIn("> [!abstract]- A. Core Trend (H01)", page)
        self.assertIn("    - **요약** ", page)
        self.assertIn("    - **→ 그래서?** ", page)
        self.assertIn("읽는 순서 점수", page)
        self.assertIn("[[2026-10-28 한국|← 2026-10-28]]", page)
        self.assertNotIn("2026-10-30 한국", page)  # no link past the last generated day

    def test_frontpage_mockups_follow_blueprint_order_and_show_gaps(self):
        page = self.files["ARTREND 한국 홈"]
        heads = ["## TODAY'S INSIGHT", "### 숫자로 본 한 주", "## ARTISTS IN FOCUS", "## TREND NEWS", "## EXHIBITIONS TO WATCH",
                 "## GALLERY MOVES", "## EMERGING PATTERNS", "## ROOKIE RADAR", "## MARKET CONTEXT", "## 방법과 관찰 범위"]
        positions = [page.index(h) for h in heads]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("publishable: false", page)
        self.assertIn("### 이 지역판에 부족한 것", page)
        for label in ("일본", "미주", "유럽"):
            self.assertIn(f"ARTREND {label} 홈", self.files)
        self.assertNotIn("ARTREND 기타 홈", self.files)
        self.assertIn("## 사용자 조치가 필요한 것", self.files["데이터 부족 점검"])
        self.assertTrue((self.out / ".obsidian" / "snippets" / "artrend-home.css").exists())

    def test_source_text_brackets_cannot_create_links(self):
        artist = next(t for s, t in self.files.items() if s.startswith("Kim Draft Artist"))
        self.assertIn("# Kim \\[\\[Draft\\]\\] Artist", artist)

    def test_rebuild_keeps_reader_notes_and_obsidian_settings(self):
        (self.out / "99_내메모" / "mine.md").write_text("keep me", encoding="utf-8")
        (self.out / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
        (self.out / "03_전시·프로그램" / "stale.md").write_text("generated", encoding="utf-8")
        ov.build_vault(self.out, dt.date(2026, 10, 29), days=1, db_path=Path(self.tmp.name) / "t.sqlite")
        self.assertEqual((self.out / "99_내메모" / "mine.md").read_text(encoding="utf-8"), "keep me")
        self.assertTrue((self.out / ".obsidian" / "workspace.json").exists())
        self.assertFalse((self.out / "03_전시·프로그램" / "stale.md").exists())

    def test_year_precision_event_note_keeps_year_string(self):
        note = next(t for s, t in self.files.items() if s.startswith("Year Only"))
        self.assertIn('start: "2026"', note)
        self.assertIn("03_", str(next(p for p in self.out.rglob("Year Only*.md"))))


if __name__ == "__main__":
    unittest.main()
