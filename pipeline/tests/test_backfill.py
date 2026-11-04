import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from artrend_mag import backfill


class BackfillTests(unittest.TestCase):
    def test_batch_dates_exclude_adjacent_rows_with_the_same_timestamp(self):
        con = sqlite3.connect(':memory:')
        try:
            con.execute('CREATE TABLE articles(source_id TEXT,published_at TEXT,first_seen_at TEXT)')
            timestamp = '2026-10-28T12:00:00+09:00'
            con.execute('INSERT INTO articles VALUES(?,?,?)', ('eflux_criticism', '2026-10-01', timestamp))
            before = backfill.snapshot(con, 'eflux_criticism')
            con.execute('INSERT INTO articles VALUES(?,?,?)', ('eflux_criticism', '2025-01-01', timestamp))
            con.execute('INSERT INTO articles VALUES(?,?,?)', ('other', '2026-10-28', timestamp))
            after = backfill.snapshot(con, 'eflux_criticism')
            con.execute('INSERT INTO articles VALUES(?,?,?)', ('eflux_criticism', None, timestamp))
            dates = backfill.batch_dates(con, 'eflux_criticism', before['last_article_rowid'],
                                        after['last_article_rowid'])
            self.assertEqual(dates, {'new_rows': 1, 'newest_publication': '2025-01-01', 'unknown_dates': 0})
            latest = backfill.snapshot(con, 'eflux_criticism')
            dates = backfill.batch_dates(con, 'eflux_criticism', before['last_article_rowid'],
                                        latest['last_article_rowid'])
            self.assertEqual(dates['unknown_dates'], 1)
        finally:
            con.close()

    def test_old_stored_outlier_does_not_skip_archive_traversal(self):
        con = Mock()
        con.execute.return_value.fetchone.return_value = {
            'run_id': 'run1', 'state': 'success', 'records_inserted': 1,
            'records_updated': 0, 'error': None,
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(backfill, 'AUDIT_ROOT', Path(directory)), \
             patch.object(backfill.runner, 'discover', return_value={'eflux_criticism': (None, {})}), \
             patch.object(backfill.db, 'connect', return_value=con), \
             patch.object(backfill, 'snapshot', side_effect=[
                 {'stored': 10, 'oldest_publication': '2023-01-01', 'last_article_rowid': 10},
                 {'stored': 10, 'oldest_publication': '2023-01-01', 'last_article_rowid': 10},
                 {'stored': 11, 'oldest_publication': '2023-01-01', 'last_article_rowid': 11}]), \
             patch.object(backfill, 'batch_dates', return_value={
                 'new_rows': 1, 'newest_publication': '2025-01-01', 'unknown_dates': 0}), \
             patch.object(backfill.subprocess, 'run') as collect:
            backfill.main(['--sources', 'eflux_criticism', '--since', '2025-04-01'])
            self.assertEqual(collect.call_count, 1)
            report = json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(report['sources']['eflux_criticism']['state'], 'date_window_batch_boundary_reached')

    def test_unexpected_insert_count_cannot_establish_date_boundary(self):
        con = Mock()
        con.execute.return_value.fetchone.return_value = {
            'run_id': 'run1', 'state': 'success', 'records_inserted': 1,
            'records_updated': 0, 'error': None,
        }
        before = {'stored': 10, 'oldest_publication': '2025-01-01', 'last_article_rowid': 10}
        after = {'stored': 12, 'oldest_publication': '2025-01-01', 'last_article_rowid': 12}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(backfill, 'AUDIT_ROOT', Path(directory)), \
             patch.object(backfill.runner, 'discover', return_value={'eflux_criticism': (None, {})}), \
             patch.object(backfill.db, 'connect', return_value=con), \
             patch.object(backfill, 'snapshot', side_effect=[before, before, after]), \
             patch.object(backfill, 'batch_dates', return_value={
                 'new_rows': 2, 'newest_publication': '2025-01-01', 'unknown_dates': 0}), \
             patch.object(backfill.subprocess, 'run') as collect:
            backfill.main(['--sources', 'eflux_criticism', '--since', '2025-04-01'])
            self.assertEqual(collect.call_count, 1)
            report = json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(report['sources']['eflux_criticism']['state'],
                             'batch_membership_mismatch_review_required')

    def test_access_error_stops_without_retry(self):
        con = Mock()
        con.execute.return_value.fetchone.return_value = {
            'run_id': 'run1', 'state': 'blocked', 'records_inserted': 0,
            'records_updated': 0, 'error': 'robots disallow',
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(backfill, 'AUDIT_ROOT', Path(directory)), \
             patch.object(backfill.runner, 'discover', return_value={'eflux_criticism': (None, {})}), \
             patch.object(backfill.db, 'connect', return_value=con), \
             patch.object(backfill, 'snapshot', return_value={'stored': 10, 'oldest_publication': '2026-01-01'}), \
             patch.object(backfill.subprocess, 'run') as collect:
            backfill.main(['--sources', 'eflux_criticism', '--since', '2025-04-01'])
            self.assertEqual(collect.call_count, 1)
            report = json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(report['sources']['eflux_criticism']['state'], 'stopped_on_source_error')


if __name__ == '__main__':
    unittest.main()
