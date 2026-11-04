import tempfile
import unittest
from pathlib import Path

import openpyxl
from artrend_mag.sourcebook_audit import compare_row, read_sourcebook, url_key


class SourcebookAuditTests(unittest.TestCase):
    def test_same_host_is_not_complete_coverage(self):
        sources = [{'source_id': 'criticism', 'base_url': 'https://www.example.org/criticism',
                    'entry_url': 'https://www.example.org/criticism/sitemap.xml'}]
        row = compare_row({'url': 'https://example.org/journal', 'final_url': None}, sources)
        self.assertEqual(row['candidate_source_ids'], ['criticism'])
        self.assertEqual(row['exact_url_source_ids'], [])
        self.assertEqual(row['collection_decision'], '미검증')

    def test_exact_url_still_requires_field_and_permission_review(self):
        row = compare_row({'url': 'https://www.example.org/'},
                          [{'source_id': 'museum', 'base_url': 'https://example.org'}])
        self.assertEqual(row['exact_url_source_ids'], ['museum'])
        self.assertEqual(row['collection_decision'], '미검증')
        self.assertIsNone(url_key('=HYPERLINK("https://example.org")'))

    def test_preserves_each_row_and_original_field_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.xlsx'
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.title = '01_뉴스매거진'
            sheet.append(['안내'])
            sheet.append(['출처ID', '우선순위', '출처'])
            sheet.append(['한국-01-001', 'P1', '=1+1', None, '매체', 'https://example.org'])
            sheet.append(['한국-01-002', 'P2', '메뉴가 다른 출처', None, '비평', 'https://example.org'])
            book.save(path)
            original = path.read_bytes()
            rows = read_sourcebook(path, 'KR')
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['name'], '=1+1')
            self.assertEqual(rows[0]['row_number'], 3)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
