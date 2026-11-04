import sqlite3
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from artrend_mag.source_catalog import HEADERS, catalog_rows


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = patch('artrend_mag.source_catalog.WORK_ROOT', Path(directory.name))
        root.start()
        self.addCleanup(root.stop)

    def test_counts_blocked_history_and_exact_report_attribution(self):
        con = sqlite3.connect(':memory:')
        con.executescript('''
            CREATE TABLE events(source_id, start_date, edition_region, event_type);
            CREATE TABLE articles(source_id, published_at);
            CREATE TABLE works(source_id);
            CREATE TABLE relationships(source_id);
            CREATE TABLE aliases(source_id);
            CREATE TABLE fx_rates(source_id, rate_date);
            CREATE TABLE evidence(source_id, url);
            CREATE TABLE reports(report_id, official_url, observation_period);
            CREATE TABLE signals(model_version, asof);
            CREATE TABLE sources(source_id);
            INSERT INTO sources VALUES ('restricted'), ('report'), ('museum'), ('unrun');
            INSERT INTO articles VALUES ('restricted', '2026-01-01');
            INSERT INTO evidence VALUES ('report', 'https://example.org/report.pdf');
            INSERT INTO evidence VALUES ('report', 'https://example.org/report.pdf');
            INSERT INTO reports VALUES ('r1', 'https://example.org/report.pdf', '2025');
            INSERT INTO reports VALUES ('r2', 'https://different.org/report.pdf', '2024');
            INSERT INTO events VALUES ('museum', '2026-03', 'OTHER', 'exhibition');
        ''')
        sources = [
            {'source_id': 'restricted', 'name': 'Media', 'source_kind': 'media', 'operational_state': 'blocked_permission'},
            {'source_id': 'report', 'name': 'Report', 'source_kind': 'report'},
            {'source_id': 'museum', 'name': 'Museum', 'source_kind': 'museum', 'region_scope': 'GLOBAL'},
            {'source_id': 'unrun', 'name': 'Unrun', 'source_kind': 'gallery'},
        ]
        rows = catalog_rows(con, sources, {})
        self.assertTrue(all(len(row) == len(HEADERS) for row in rows))
        mapped = {row[2]: dict(zip(HEADERS, row)) for row in rows}
        self.assertEqual(mapped['restricted']['기사 메타 건수'], 1)
        self.assertIn('차단', mapped['restricted']['수집 상태'])
        self.assertIn('기존 보유자료', mapped['restricted']['수집 상태'])
        self.assertEqual(mapped['report']['보고서 건수'], 1)
        self.assertEqual(mapped['(미귀속)']['보고서 건수'], 1)
        self.assertEqual(mapped['report']['증거 행수'], 2)
        self.assertEqual(mapped['report']['기타 자료 관측기간'], '보고서 관측기간: 2025')
        self.assertEqual(mapped['museum']['실제 개최 지역'], 'OTHER')
        self.assertEqual(mapped['museum']['소스 관찰범위'], 'GLOBAL')
        self.assertEqual(mapped['unrun']['수집 상태'], '미수집/등록만 됨')
        self.assertIsNone(mapped['unrun']['최근 실행 완료시각'])
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))
        con.close()


if __name__ == '__main__':
    unittest.main()
