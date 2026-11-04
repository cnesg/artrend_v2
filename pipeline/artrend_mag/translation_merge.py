"""Merge Korean metadata only when its original text and declared language still match."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from .config import AUDIT_ROOT, DB_PATH, WORK_ROOT, configure_local_temporary_files, iso_now
from .translation import CANDIDATE_SQL, ensure_translation_table


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest() if isinstance(value, str) else None


def _current_fields(con):
    configure_local_temporary_files()
    con.create_function('artrend_translation_hash', 1, _hash)
    con.execute('DROP TABLE IF EXISTS temp._translation_current')
    con.execute('CREATE TEMP TABLE _translation_current AS SELECT c.*, '
                'artrend_translation_hash(original_text) AS text_hash FROM (' + CANDIDATE_SQL + ') c')
    con.execute('CREATE UNIQUE INDEX temp.translation_current_key '
                'ON _translation_current(source_table,source_key,source_field)')


def _invalidate(con):
    cursor = con.execute("""UPDATE metadata_translations AS t
        SET status='pending', translation_ko=NULL, needs_review=1,
            status_reason='source_changed_or_removed', updated_at=?
        WHERE (status!='pending' OR status_reason IS NOT 'source_changed_or_removed')
          AND NOT EXISTS (SELECT 1 FROM _translation_current c
            WHERE c.source_table=t.source_table AND c.source_key=t.source_key
              AND c.source_field=t.source_field AND c.original_text=t.original_text
              AND c.text_hash=t.source_text_hash AND c.source_lang IS t.declared_lang)""", (iso_now(),))
    return cursor.rowcount


def invalidate_stale_translations(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='metadata_translations'").fetchone():
        return 0
    _current_fields(con)
    try:
        return _invalidate(con)
    finally:
        con.execute('DROP TABLE temp._translation_current')


def merge_translations(con, source_path):
    source_path = Path(source_path).resolve()
    source_path.relative_to(WORK_ROOT.resolve())
    if not source_path.is_file():
        raise ValueError('Translation input database does not exist')
    ensure_translation_table(con)
    con.commit()
    con.execute('ATTACH DATABASE ? AS translation_input', (source_path.as_uri() + '?mode=ro',))
    try:
        columns = [row[1] for row in con.execute('PRAGMA main.table_info(metadata_translations)')]
        incoming = [row[1] for row in con.execute('PRAGMA translation_input.table_info(metadata_translations)')]
        if columns != incoming:
            raise ValueError('Translation snapshot schema differs from the current schema')
        _current_fields(con)
        valid = '''FROM translation_input.metadata_translations i JOIN _translation_current c
          ON c.source_table=i.source_table AND c.source_key=i.source_key AND c.source_field=i.source_field
          WHERE i.original_text=c.original_text AND i.source_text_hash=c.text_hash
            AND i.source_text_hash=artrend_translation_hash(i.original_text)
            AND i.declared_lang IS c.source_lang'''
        total = con.execute('SELECT COUNT(*) FROM translation_input.metadata_translations').fetchone()[0]
        eligible = con.execute('SELECT COUNT(*) ' + valid).fetchone()[0]
        keys = {'source_table', 'source_key', 'source_field', 'created_at'}
        changed_fields = [name for name in columns if name not in keys and name != 'updated_at']
        assignments = ','.join(name + '=excluded.' + name for name in columns if name not in keys)
        different = ' OR '.join('metadata_translations.' + name + ' IS NOT excluded.' + name for name in changed_fields)
        before = con.total_changes
        con.execute('INSERT INTO metadata_translations(' + ','.join(columns) + ') SELECT '
                    + ','.join('i.' + name for name in columns) + ' ' + valid
                    + ' ON CONFLICT(source_table,source_key,source_field) DO UPDATE SET ' + assignments
                    + ' WHERE excluded.updated_at>=metadata_translations.updated_at AND (' + different + ')')
        merged = con.total_changes - before
        invalidated = _invalidate(con)
        con.commit()
        return dict(input_rows=total, current_source_matches=eligible, merged_changes=merged,
                    rejected_stale_or_missing=total-eligible, invalidated_existing=invalidated,
                    source_database=str(source_path), finished_at=iso_now())
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute('DROP TABLE IF EXISTS temp._translation_current')
        con.execute('DETACH DATABASE translation_input')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True, type=Path)
    parser.add_argument('--target-db', default=DB_PATH, type=Path)
    args = parser.parse_args(argv)
    target = args.target_db.resolve()
    target.relative_to(WORK_ROOT.resolve())
    if target == args.source_db.resolve():
        parser.error('Source and target databases must be different')
    con = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=120)
    try:
        result = merge_translations(con, args.source_db)
    finally:
        con.close()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    path = AUDIT_ROOT / 'translation_merge_latest.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
