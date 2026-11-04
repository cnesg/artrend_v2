"""Resume bounded public metadata archives, never treating a batch as full coverage.

python -m artrend_mag.backfill --since 2025-04-01
The cutoff is a newest-ID traversal boundary, not proof of exhaustive chronological coverage.
Each normal collector run retains its own manifest. Stops on access errors, request failures,
or no new stored records. Does not bypass robots, permissions or request pacing.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys

from . import db, runner
from .config import AUDIT_ROOT, iso_now

SUPPORTED = ('eflux_criticism', 'eflux_announcements')


def snapshot(con, source):
    row = con.execute('SELECT COUNT(*), MIN(published_at), COALESCE(MAX(rowid),0) FROM articles WHERE source_id=?', (source,)).fetchone()
    return {'stored': row[0], 'oldest_publication': row[1], 'last_article_rowid': row[2]}

def batch_dates(con, source, start_rowid, end_rowid):
    """Bound new rows from the serial collector without second-resolution timestamp overlap."""
    row = con.execute("""SELECT COUNT(*), MAX(published_at), SUM(published_at IS NULL)
                         FROM articles WHERE source_id=? AND rowid>? AND rowid<=?""",
                      (source, start_rowid, end_rowid)).fetchone()
    return {'new_rows': row[0], 'newest_publication': row[1], 'unknown_dates': row[2] or 0}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', default=','.join(SUPPORTED))
    p.add_argument('--since', default='2025-04-01')
    p.add_argument('--max-batches', type=int, default=100)
    p.add_argument('--exhaust', action='store_true', help='ignore date boundary and exhaust the exposed sitemap')
    a = p.parse_args(argv)
    dt.date.fromisoformat(a.since)
    if a.max_batches < 1:
        p.error('--max-batches must be positive')
    sources = [s for s in a.sources.split(',') if s]
    if any(s not in SUPPORTED for s in sources):
        p.error('supported sources: ' + ','.join(SUPPORTED))
    registry = runner.discover()
    report = {'started_at': iso_now(), 'since': a.since,
              'scope': 'Exposed sitemap exhaustion' if a.exhaust else 'Newest-ID traversal to a full old-date batch; not exhaustive chronological coverage proof',
              'sources': {}}
    path = AUDIT_ROOT / ('backfill_' + dt.datetime.now().strftime('%Y%m%dT%H%M%S') + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['updated_at'] = iso_now()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for source in sources:
        con = db.connect()
        before = snapshot(con, source)
        con.close()
        item = {'before': before, 'batches': [], 'state': 'running'}
        report['sources'][source] = item
        save()
        if registry[source][1].get('disabled'):
            item['state'] = 'blocked_permission_or_disabled'
            save()
            continue
        for _ in range(a.max_batches):
            con = db.connect()
            current = snapshot(con, source)
            con.close()
            try:
                # A fresh interpreter sees source registry changes between resumable batches.
                subprocess.run([sys.executable, '-m', 'artrend_mag.cli', 'collect',
                                '--mode', 'initial', '--sources', source], check=True)
            except BaseException as exc:
                item['state'] = 'interrupted_command'
                item['error'] = str(exc)
                save()
                raise
            con = db.connect()
            run = dict(con.execute('SELECT * FROM crawl_runs WHERE source_id=? ORDER BY started_at DESC LIMIT 1', (source,)).fetchone())
            after = snapshot(con, source)
            con.close()
            item['batches'].append({key: run[key] for key in ('run_id', 'state', 'records_inserted', 'records_updated', 'error')})
            item['after'] = after
            save()
            if run['state'] not in ('success', 'no_change'):
                item['state'] = 'stopped_on_source_error'
                break
            if after['stored'] == current['stored']:
                item['state'] = 'no_unseen_records_in_current_sitemap'
                break
            con = db.connect()
            dates = batch_dates(con, source, current['last_article_rowid'], after['last_article_rowid'])
            con.close()
            item['batches'][-1]['new_record_dates'] = dates
            if dates['new_rows'] != run['records_inserted']:
                item['state'] = 'batch_membership_mismatch_review_required'
                break
            if (not a.exhaust and dates['new_rows'] and not dates['unknown_dates']
                    and dates['newest_publication'] and dates['newest_publication'][:10] <= a.since):
                item['state'] = 'date_window_batch_boundary_reached'
                break
        else:
            item['state'] = 'batch_budget_reached_resume_required'
        item.setdefault('after', current if not registry[source][1].get('disabled') else before)
        save()
    print(str(path), flush=True)


if __name__ == '__main__':
    main()
