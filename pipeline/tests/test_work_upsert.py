import sqlite3
import unittest

from artrend_mag import db


class WorkUpsertTests(unittest.TestCase):
    def test_counts_and_complete_field_updates(self):
        con = sqlite3.connect(':memory:')
        db.init_schema(con)
        db.upsert_source(con, 'test', name='Test collection', source_kind='museum', access_method='local')
        values = dict(id_namespace='test_work', id_value='1', source_id='test',
                      title='Work', date_text='1900', medium='Oil', classification='Painting',
                      url='https://example.org/1', is_public_domain=True)
        first = {}
        key = db.upsert_work(con, first, **values)
        self.assertEqual(first, {'inserted': 1, 'works': 1})
        second = {}
        self.assertEqual(db.upsert_work(con, second, **values), key)
        self.assertEqual(second, {'unchanged': 1, 'works': 1})
        values.update(date_text='1901', classification='Drawing', url='https://example.org/object/1')
        third = {}
        db.upsert_work(con, third, **values)
        self.assertEqual(third, {'updated': 1, 'works': 1})
        self.assertEqual(con.execute('SELECT date_text,classification,url FROM works WHERE work_id=?', (key,)).fetchone(),
                         ('1901', 'Drawing', 'https://example.org/object/1'))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM works').fetchone()[0], 1)
        con.close()


if __name__ == '__main__':
    unittest.main()
