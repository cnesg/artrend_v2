import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artrend_mag import export_workbook


class BlueprintAuditTests(unittest.TestCase):
    def test_removed_fallback_claims_stay_missing_without_registry_or_db_evidence(self):
        for data_id in ("D33", "D53", "D54"):
            with self.subTest(data_id=data_id):
                status, reason = export_workbook._blueprint_status(data_id, [], {}, {})
                self.assertEqual(status, "missing")
                self.assertIn("등록 출처 없음", reason)
                self.assertNotIn("not attempted", reason)
                self.assertNotIn("RSS metadata only", reason)

    def test_met_claim_depends_on_current_work_and_run_counters(self):
        source = {"source_id": "met_collection_github", "blueprint_data_id": "D04"}
        status, reason = export_workbook._blueprint_status(
            "D04", [source], {}, {},
        )
        self.assertEqual(status, "missing")
        self.assertIn("DB 본자료 0행", reason)
        self.assertNotIn("not attempted", reason)

        status, reason = export_workbook._blueprint_status(
            "D04", [source], {"met_collection_github": {"state": "no_change", "records_unchanged": 3}},
            {"met_collection_github": {"works": 3}},
        )
        self.assertEqual(status, "current")
        self.assertIn("works=3", reason)
        self.assertIn("unchanged=3", reason)
        self.assertIn("CC0", reason)

    def test_broad_requires_observed_records_and_kadist_uses_registered_403(self):
        broad = {"source_id": "broad_public", "blueprint_data_id": "D54", "operational_state": None}
        status, reason = export_workbook._blueprint_status(
            "D54", [broad], {"broad_public": {"state": "success"}}, {},
        )
        self.assertEqual(status, "missing")
        self.assertNotIn("not attempted", reason)
        self.assertNotIn("live collection succeeded", reason)
        status, reason = export_workbook._blueprint_status(
            "D54", [broad], {"broad_public": {"state": "success"}},
            {"broad_public": {"events": 2, "works": 4}},
        )
        self.assertEqual(status, "current")
        self.assertIn("events=2", reason)
        self.assertIn("works=4", reason)
        self.assertIn("증분 실행", reason)
        self.assertNotIn("complete", reason.casefold())

        kadist = {
            "source_id": "kadist_public", "blueprint_data_id": "D53", "operational_state": "blocked_access",
            "st_live_response": "blocked(HTTP 403 on tested public pages)",
        }
        status, reason = export_workbook._blueprint_status("D53", [kadist], {}, {})
        self.assertEqual(status, "blocked")
        self.assertIn("HTTP 403", reason)
        self.assertNotIn("not attempted", reason)

    def test_artforum_rss_permission_status_comes_from_registry_metadata(self):
        source = {
            "source_id": "artforum_feed", "blueprint_data_id": "D33", "operational_state": "blocked_permission",
            "st_collection_terms": "Permission required for collection; RSS is not a permission exception",
        }
        status, reason = export_workbook._blueprint_status("D33", [source], {}, {})
        self.assertEqual(status, "blocked")
        self.assertIn("RSS is not a permission exception", reason)
        self.assertNotIn("RSS metadata only", reason)

    def test_kiaf_fair_edition_is_partial_and_exhibitors_remain_unresolved(self):
        source = {
            "source_id": "kiaf_seoul", "blueprint_data_id": "D23", "operational_state": None,
            "notes": "전시자 화면은 허용된 120초 렌더링 시도 뒤에도 미해결이며 추가 재시도나 직접 API 호출을 하지 않습니다.",
        }
        status, reason = export_workbook._blueprint_status(
            "D23", [source], {"kiaf_seoul": {"state": "success"}},
            {"kiaf_seoul": {"events": 1, "relationships": 0}},
            {"kiaf_seoul": {
                "n": 1, "first_start": "2026-09-02", "last_end": "2026-09-06", "cities": "Seoul",
                "venues": "COEX", "participant_events": 0,
            }},
        )
        self.assertEqual(status, "partial")
        self.assertIn("2026-09-02–2026-09-06", reason)
        self.assertIn("Seoul", reason)
        self.assertIn("COEX", reason)
        self.assertIn("전시자·갤러리 필드는 미확보", reason)
        self.assertIn("120초", reason)
        self.assertNotIn("exhibitors available", reason)

    def test_kiaf_success_run_without_database_rows_is_not_success(self):
        source = {"source_id": "kiaf_seoul", "blueprint_data_id": "D23", "operational_state": None}
        status, reason = export_workbook._blueprint_status(
            "D23", [source], {"kiaf_seoul": {"state": "success"}}, {}, {},
        )
        self.assertEqual(status, "missing")
        self.assertIn("DB 행사=0건", reason)
        self.assertIn("수집 성공으로 보지 않습니다", reason)

    def test_missing_registry_does_not_fabricate_mmca_access_status(self):
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE events(source_id TEXT); CREATE TABLE articles(source_id TEXT); CREATE TABLE works(source_id TEXT);")
        with tempfile.TemporaryDirectory() as directory, patch.object(export_workbook, "WORK_ROOT", Path(directory)):
            rows = export_workbook._rp_checks(con, {}, [], {})
        mmca = next(row for row in rows if row[0] == "SRC-KR-MMCA")
        self.assertIn("웹: not registered", mmca[2])
        self.assertIn("공식 API(15058313): not registered", mmca[2])
        self.assertNotIn("blocked_access(HTTP 400", mmca[2])
        con.close()

    def test_mmca_api_is_not_claimed_as_the_only_lawful_option(self):
        sources = [
            {"source_id": "mmca_web", "operational_state": "blocked_access", "robots_status": None, "notes": None},
            {"source_id": "mmca_datagokr_api", "operational_state": "blocked_credentials", "robots_status": None, "notes": None},
        ]
        steps = export_workbook._next_steps(sources)
        row = steps[0]
        self.assertIn("유일한 적법 경로로 단정하지 않습니다", row[4])
        self.assertIn("수동 입력", row[2])
        self.assertIn("artrend_mag.cli update --mode incremental [--translate]", steps[4][2])

    def test_market_stage_count_is_dynamic_and_price_bases_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "db").mkdir()
            market = sqlite3.connect(root / "db" / "auction_normalized.sqlite")
            market.execute("CREATE TABLE normalized_lots(price_basis TEXT)")
            market.executemany("INSERT INTO normalized_lots VALUES(?)", [
                ("hammer",), ("hammer",), ("hammer_plus_premium",),
            ])
            market.commit()
            market.close()
            with patch.object(export_workbook, "WORK_ROOT", root):
                result = export_workbook._auction_stage_summary()
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["by_basis"], {"hammer": 2, "hammer_plus_premium": 1})


if __name__ == "__main__":
    unittest.main()
