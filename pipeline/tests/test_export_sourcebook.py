import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
from artrend_mag import db, export_supplement
from artrend_mag.export_workbook import WB


class SourcebookSheetTests(unittest.TestCase):
    def test_every_row_kept_and_unassessed_rows_are_not_marked_collected(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        db.upsert_source(con, 'museum', name='Museum', source_kind='museum', access_method='html')
        db.upsert_event(con, {}, source_id='museum', source_event_key='1', event_type='exhibition',
                        title='Show', parser_version='t')
        con.executemany('INSERT INTO reports(report_id,title,official_url) VALUES(?,?,?)', [
            ('linked', 'Linked report', 'https://m.org/report'),
            ('unattributed', 'Same host is not attribution', 'https://m.org/other-report'),
        ])
        for locator in ('index', 'detail'):
            db.add_evidence(con, source_id='museum', url='https://m.org/report',
                            fetched_at='2026-10-28', http_status=200, raw_path=None,
                            raw_sha256=None, locator=locator)
        base = {'sheet': 's', 'priority': 'P1', 'kind': 'k', 'requested_fields': 'f', 'workbook': 'w.xlsx'}
        rows = [dict(base, sourcebook_region='KR', sourcebook_id='한국-01-001', name='=A', url='https://m.org',
                     comparison='동일 URL', candidate_source_ids=['museum']),
                dict(base, sourcebook_region='JP', sourcebook_id='일본-01-001', name='B', url='https://b.org',
                     comparison='미대응', candidate_source_ids=[])]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / 'work' / 'audit'
            audit.mkdir(parents=True)
            (audit / 'sourcebook_rows.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            (audit / 'sourcebook_assessment_KR.json').write_text(json.dumps(
                [{'sourcebook_id': '한국-01-001', 'source_ids': ['museum'], 'disposition': 'feasible_remaining'}]))
            (audit / 'wave2').mkdir()
            (audit / 'wave2' / 'MuseumsASIA_assessment.json').write_text(json.dumps([
                {'sourcebook_id': '한국-01-001', 'source_ids': ['museum'],
                 'disposition': 'implemented_pending_run',
                 'requested_vs_observed_fields': {'observed': ['전시 제목']},
                 'terms_robots_evidence': ['공개 목록만 확인'],
                 'limitations': ['전체 이력 아님']}
            ], ensure_ascii=False), encoding='utf-8')
            path = root / 'a.xlsx'
            book = WB(str(path))
            with patch.object(export_supplement, 'WORK_ROOT', root):
                export_supplement.append_sourcebook_sheet(book, con)
            book.close()
            sheet = openpyxl.load_workbook(path)['16_리서치목록_대조']
            values = list(sheet.iter_rows(min_row=5, values_only=True))
            self.assertEqual(len(values), 2)
            self.assertEqual(values[0][4], '=A')
            self.assertEqual(values[0][9], 'implemented_pending_run')
            self.assertEqual(values[0][12], 1)
            self.assertEqual(values[0][20], 1)
            self.assertIn('전시 제목', values[0][16])
            self.assertIn('전체 이력 아님', values[0][18])
            self.assertEqual(sheet['E5'].data_type, 's')
            self.assertEqual(values[1][9], '판정 미완료')
            self.assertIsNone(values[1][12])
            self.assertIsNone(values[1][20])


if __name__ == '__main__':
    unittest.main()
