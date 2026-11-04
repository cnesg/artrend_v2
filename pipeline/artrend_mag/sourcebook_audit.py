"""Read the four supplied sourcebooks without changing them; preserve every source row."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import openpyxl

from .config import AUDIT_ROOT, DB_PATH, WORK_ROOT, configure_local_temporary_files, iso_now

REGIONS = {'미주': 'AMERICAS', '유럽': 'EUROPE', '일본': 'JP', '한국': 'KR'}
FIELDS = ('sourcebook_id', 'priority', 'name', 'scope', 'kind', 'url', 'menu',
          'requested_fields', 'editorial_use', 'cadence', 'collection_suggestion',
          'access_note', 'rights_note', 'verification_level', 'evidence_url',
          'link_status', 'final_url', 'link_checked_at')


def url_key(value):
    if not isinstance(value, str):
        return None
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
        return None
    host = parts.hostname.lower().removeprefix('www.')
    return host, parts.path.rstrip('/') or '/', parts.query


def read_sourcebook(path, region):
    book = openpyxl.load_workbook(path, read_only=True, data_only=False)
    rows = []
    try:
        for sheet in book:
            found_header = False
            for row_number, values in enumerate(sheet.iter_rows(values_only=True), 1):
                if values and values[0] == '출처ID':
                    found_header = True
                    continue
                if not found_header or not values or not isinstance(values[0], str):
                    continue
                if not re.fullmatch(r'.+-\d{2}-\d{3}', values[0]):
                    continue
                record = dict(zip(FIELDS, list(values) + [None] * len(FIELDS)))
                record.update(sourcebook_region=region, workbook=str(path), sheet=sheet.title,
                              row_number=row_number)
                rows.append(record)
    finally:
        book.close()
    return rows


def compare_row(row, sources):
    row_keys = {key for value in (row.get('url'), row.get('final_url'))
                for key in [url_key(value)] if key}
    exact, same_host = [], []
    for source in sources:
        keys = {key for field in ('base_url', 'entry_url')
                for key in [url_key(source.get(field))] if key}
        if row_keys & keys:
            exact.append(source['source_id'])
        elif {key[0] for key in row_keys} & {key[0] for key in keys}:
            same_host.append(source['source_id'])
    return dict(row, candidate_source_ids=sorted(set(exact + same_host)),
                exact_url_source_ids=sorted(exact),
                comparison='동일 URL 후보·필드 범위 재확인' if exact else
                           '동일 호스트 후보·메뉴 범위 재확인' if same_host else '기존 등록 출처와 미대응',
                collection_decision='미검증',
                comparison_note='URL 일치는 수집 완료·허가·동일 데이터 범위의 증거가 아닙니다.')


def source_snapshot(con):
    sources = [dict(row) for row in con.execute('SELECT * FROM sources ORDER BY source_id')]
    for table in ('events', 'articles', 'works', 'relationships'):
        counts = dict(con.execute(f'SELECT source_id,COUNT(*) FROM {table} GROUP BY source_id'))
        for source in sources:
            source[table + '_stored'] = counts.get(source['source_id'], 0)
    for source in sources:
        row = con.execute('SELECT * FROM crawl_runs WHERE source_id=? ORDER BY started_at DESC LIMIT 1',
                          (source['source_id'],)).fetchone()
        source['latest_run'] = dict(row) if row else None
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=WORK_ROOT.parent / 'list')
    args = parser.parse_args(argv)
    configure_local_temporary_files()
    con = sqlite3.connect(DB_PATH.as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN')
        sources = source_snapshot(con)
    finally:
        con.close()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    inputs, all_rows, owners = [], [], {}
    for label, region in REGIONS.items():
        path = (args.directory / f'{label}_아트매거진_리서치리스트.xlsx').resolve()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = [compare_row(row, sources) for row in read_sourcebook(path, region)]
        for row in rows:
            key = url_key(row.get('url')) or url_key(row.get('final_url'))
            host = key[0] if key else 'missing:' + row['sourcebook_id']
            row['collection_owner'] = owners.setdefault(host, region)
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != after:
            raise RuntimeError(f'Sourcebook changed during read: {path}')
        counts = {state: sum(row['comparison'] == state for row in rows)
                  for state in sorted({row['comparison'] for row in rows})}
        inputs.append(dict(path=str(path), sha256=before, region=region, rows=len(rows), comparisons=counts))
        (AUDIT_ROOT / f'sourcebook_{region}.json').write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        all_rows.extend(rows)
    for region in REGIONS.values():
        (AUDIT_ROOT / f'sourcebook_owner_{region}.json').write_text(
            json.dumps([row for row in all_rows if row['collection_owner'] == region],
                       ensure_ascii=False, indent=2), encoding='utf-8')
    receipt = dict(generated_at=iso_now(), inputs=inputs, sourcebook_rows=len(all_rows),
                   registered_sources=len(sources),
                   note='원본은 미검증 출처 제안서입니다. 기존 수집 범위·접근·권리는 별도 검증합니다.')
    for name, payload in (('sourcebook_rows.json', all_rows), ('sourcebook_registry_snapshot.json', sources),
                          ('sourcebook_inventory.json', receipt)):
        (AUDIT_ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
