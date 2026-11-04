from pathlib import Path
import tempfile
import unittest

import openpyxl

from artrend_mag.export_workbook import WB


class WorkbookStreamingTests(unittest.TestCase):
    def test_generator_rows_and_literal_formula_like_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.xlsx'
            wb = WB(str(path))
            wb.sheet('source', 'Source metadata', 'No executable formulas', ['Title', 'Count'],
                     ((title, count) for title, count in [('=1+1', 2), ('한국어 제목', 3)]))
            wb.close()
            result = openpyxl.load_workbook(path, read_only=False, data_only=False)
            sheet = result['source']
            self.assertEqual(sheet['A5'].value, '=1+1')
            self.assertEqual(sheet['A5'].data_type, 's')
            self.assertEqual(sheet['A6'].value, '한국어 제목')
            self.assertEqual(sheet['B6'].value, 3)
            self.assertEqual(sheet.auto_filter.ref, 'A4:B6')
            self.assertEqual(sheet.freeze_panes, 'A5')
            result.close()


if __name__ == '__main__':
    unittest.main()
