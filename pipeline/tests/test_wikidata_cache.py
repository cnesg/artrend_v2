import sqlite3
import unittest

from artrend_mag.sources.wikidata_ids import _pending_names, _query_key


class LookupCacheTests(unittest.TestCase):
    def test_negative_cache_does_not_starve_later_names(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE identifier_queries(source_id, query_key, checked_at, outcome)')
        rows = [{'nm': 'Artist ' + str(i), 'ents': 'entity' + str(i)} for i in range(4)]
        for row, outcome in zip(rows, ['no_match', 'ambiguous', 'unique_candidate']):
            con.execute('INSERT INTO identifier_queries VALUES(?,?,?,?)',
                        ('wikidata_ids', _query_key(row), '2026-10-28', outcome))
        pending, cached = _pending_names(con, 'wikidata_ids', rows, '2026-10-01', 1)
        self.assertEqual(pending, [rows[3]])
        self.assertEqual(cached, 3)
        pending, cached = _pending_names(con, 'wikidata_ids', rows, '2026-11-01', 2)
        self.assertEqual(pending, rows[:2])
        self.assertEqual(cached, 0)
        con.close()

    def test_key_preserves_entity_context_but_ignores_order(self):
        self.assertEqual(_query_key({'nm': 'Artist', 'ents': 'a,b'}),
                         _query_key({'nm': 'Artist', 'ents': 'b,a'}))
        self.assertNotEqual(_query_key({'nm': 'Artist', 'ents': 'a'}),
                            _query_key({'nm': 'Artist', 'ents': 'a,b'}))


if __name__ == '__main__':
    unittest.main()
