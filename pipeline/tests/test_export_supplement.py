import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
from artrend_mag import db, export_supplement
from artrend_mag.export_workbook import WB
from artrend_mag.translation import translate_metadata


class Backend:
    model_name = 'fixture'
    model_version = '1'

    def translate_many(self, texts, source_lang, target_lang):
        return ['한국어 번역문'] * len(texts)


class SupplementExportTests(unittest.TestCase):
    def test_original_korean_provenance_and_market_counts_are_written(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        db.init_schema(con)
        db.upsert_source(con, 'test', name='Test', source_kind='museum', access_method='local')
        db.upsert_event(con, {}, source_id='test', source_event_key='1', event_type='exhibition',
                        title='=1+1', title_lang='en', parser_version='test', url='https://example.org/event')
        translate_metadata(con, backend=Backend())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'db').mkdir()
            market = sqlite3.connect(str(root / 'db' / 'auction_normalized.sqlite'))
            market.execute('CREATE TABLE normalized_lots(house,status,price_basis,price_comparability,sale_date_reason,currency_reason,sale_date)')
            market.executemany('INSERT INTO normalized_lots VALUES(?,?,?,?,?,?,?)', [
                ('House', 'sold', 'hammer', 'comparable_within_basis', None, None, '2026-01-01'),
                ('House', 'unsold', 'hammer', 'non_comparable_not_sold', None, None, '2026-02-01')])
            market.commit()
            market.close()
            path = root / 'audit.xlsx'
            book = WB(str(path))
            with patch.object(export_supplement, 'WORK_ROOT', root):
                export_supplement.append_supplement_sheets(book, con)
            book.close()
            result = openpyxl.load_workbook(path, read_only=False, data_only=False)
            sheet = result['14b_한국어_원문대조']
            self.assertEqual(sheet['G5'].value, '=1+1')
            self.assertEqual(sheet['G5'].data_type, 's')
            self.assertEqual(sheet['H5'].value, '한국어 번역문')
            self.assertEqual(sheet['E5'].value, 'https://example.org/event')
            self.assertEqual(sheet['P5'].value, 'en')
            self.assertEqual(sheet['Q5'].value, 'metadata')
            self.assertEqual(sheet.auto_filter.ref, 'A4:T5')
            quality = list(result['15_경매정규화_품질'].values)
            self.assertIn(('price_comparability', 'non_comparable_not_sold', 1), quality)
            result.close()
        con.close()


if __name__ == '__main__':
    unittest.main()
