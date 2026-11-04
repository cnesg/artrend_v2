"""Stream Korean metadata translations and auction-staging quality into the audit workbook."""
import json
import sqlite3

from .config import WORK_ROOT


def _assessment_cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _stored_counts(con, source_ids):
    if not source_ids:
        return [None] * 4
    counts = []
    for table in ('events', 'articles', 'works', 'relationships'):
        n = 0
        for sid in source_ids:
            n += con.execute(f'SELECT COUNT(*) FROM {table} WHERE source_id=?', (sid,)).fetchone()[0]
        counts.append(n)
    return counts


def _stored_report_count(con, source_ids):
    if not source_ids:
        return None
    placeholders = ','.join('?' for _ in source_ids)
    return con.execute(
        'SELECT COUNT(DISTINCT r.report_id) FROM reports r '
        'JOIN evidence e ON e.url=r.official_url '
        f'WHERE e.source_id IN ({placeholders})', source_ids,
    ).fetchone()[0]


def append_sourcebook_sheet(wb, con):
    audit = WORK_ROOT / 'work' / 'audit'
    rows_path = audit / 'sourcebook_rows.json'
    if not rows_path.is_file():
        return
    assessed = {}
    for region in ('AMERICAS', 'EUROPE', 'JP', 'KR'):
        path = audit / f'sourcebook_assessment_{region}.json'
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8'))
            for item in payload if isinstance(payload, list) else payload.get('rows', []):
                assessed[item.get('sourcebook_id')] = item
    wave2_ids = set()
    for path in sorted((audit / 'wave2').glob('*_assessment.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, list):
            raise ValueError(f'Expected assessment row array: {path}')
        for item in payload:
            key = item['sourcebook_id']
            if key in wave2_ids:
                raise ValueError(f'Duplicate wave-2 assessment: {key}')
            wave2_ids.add(key)
            assessed[key] = item
    registered = {r[0]: r for r in con.execute('SELECT source_id, operational_state FROM sources')}
    out = []
    for row in json.loads(rows_path.read_text(encoding='utf-8')):
        item = assessed.get(row['sourcebook_id'], {})
        ids = sorted(set((item.get('source_ids') or []) + (item.get('implementation_source_ids') or [])
                         or row.get('candidate_source_ids') or []))
        live = [sid for sid in ids if sid in registered]
        states = '; '.join(f'{sid}={registered[sid][1] or "not_run"}' for sid in live)
        out.append([row['sourcebook_region'], row['sheet'], row['sourcebook_id'], row.get('priority'), row.get('name'),
                    row.get('kind'), row.get('url'), row.get('requested_fields'), row['comparison'],
                    item.get('disposition') or '판정 미완료', ', '.join(ids), states,
                    *_stored_counts(con, live),
                    _assessment_cell(item.get('requested_vs_observed_fields')),
                    _assessment_cell(item.get('terms_robots_evidence')),
                    _assessment_cell(item.get('limitations')), row.get('workbook'),
                    _stored_report_count(con, live)])
    wb.sheet('16_리서치목록_대조', '지역별 리서치 목록 4종 × 실제 수집 출처 대조',
             '목록 원본은 미검증 제안서입니다. URL 일치·HTTP 200은 수집 완료나 이용 허가가 아닙니다. 저장 건수는 연결 출처의 현재 행수이며 항목이 요청한 메뉴 전체를 뜻하지 않습니다. 보고서는 공식 URL과 근거 URL이 정확히 일치하는 고유 보고서만 집계합니다.',
             ['목록 지역', '목록 탭', '목록 ID', '우선순위', '출처명', '유형', 'URL', '요청 필드', 'URL 대조',
              '판정', '연결 source_id', '운영 상태', '저장 이벤트', '저장 기사', '저장 작품', '저장 관계',
              '요청 vs 관찰 필드', 'robots·약관 근거', '제한', '원본 파일', '직접 연결 보고서'],
             out, {4: 30, 6: 45, 7: 45, 9: 22, 10: 35, 11: 45, 16: 50, 17: 50, 18: 50, 20: 22})


def append_supplement_sheets(wb, con):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'metadata_translations' in tables:
        summary = con.execute('SELECT source_table, status, COUNT(*) FROM metadata_translations GROUP BY 1,2 ORDER BY 1,2')
        wb.sheet('14_번역현황', '한국어 메타데이터 번역 현황',
                 '건수는 문서 수가 아닌 번역 대상 필드 수. translated도 자동번역이며 편집 검토 전입니다. pending/error는 번역 완료가 아닙니다.',
                 ['원본 테이블', '번역 상태', '필드 수'], summary, {0: 30, 1: 30, 2: 20})
        query = '''
            SELECT t.source_table, t.source_key, t.source_field,
                   COALESCE(a.source_id,e.source_id,w.source_id),
                   COALESCE(a.canonical_url,e.url,w.url,r.official_url,mr.official_url),
                   t.source_lang, t.original_text, t.translation_ko,
                   t.status, t.status_reason, t.needs_review, t.model, t.model_version,
                   t.updated_at, t.source_text_hash, t.declared_lang, t.language_basis,
                   t.language_detector_version, t.language_confidence, t.language_margin
            FROM metadata_translations t
            LEFT JOIN articles a ON t.source_table='articles' AND a.article_id=t.source_key
            LEFT JOIN events e ON t.source_table='events' AND e.event_id=t.source_key
            LEFT JOIN works w ON t.source_table='works' AND w.work_id=t.source_key
            LEFT JOIN reports r ON t.source_table='reports' AND r.report_id=t.source_key
            LEFT JOIN report_metrics m ON t.source_table='report_metrics' AND m.metric_id=t.source_key
            LEFT JOIN reports mr ON mr.report_id=m.report_id
            ORDER BY t.source_table,t.source_key,t.source_field
        '''
        wb.sheet('14b_한국어_원문대조', '한국어 번역과 원문·출처 대조',
                 '원문은 그대로 보존. 한국어 번역은 검토 전 자동번역이며 인명·작품명 오역 가능. 본문 전문 수집/번역이 아니며 저작권 허가를 의미하지 않습니다. source_id가 비어 있는 보고서는 공식 URL로 확인합니다.',
                 ['자료 유형', '원본 ID', '필드', '출처 ID', '출처 URL', '원문 언어', '원문', '한국어 번역',
                  '번역 상태', '대기/오류 사유', '검토 필요(1)', '모델', '모델 버전', '처리시각', '원문 SHA-256',
                  '출처 선언 언어', '언어 판정 근거', '언어 판정기 버전', '언어 신뢰도', '언어 판정 차이'],
                 con.execute(query), {0: 20, 1: 30, 2: 25, 3: 30, 4: 55, 6: 70, 7: 70, 9: 60, 14: 65})
    else:
        wb.sheet('14_번역현황', '한국어 메타데이터 번역 현황', '아직 번역 실행 결과가 없습니다.',
                 ['상태'], [('미실행',)])

    append_sourcebook_sheet(wb, con)

    path = WORK_ROOT / 'db' / 'auction_normalized.sqlite'
    manifest = WORK_ROOT / 'outputs' / 'auction_normalize_manifest.json'
    if not path.is_file():
        return
    market = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if not market.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_lots'").fetchone():
            return
        quality = []
        for field in ('house', 'status', 'price_basis', 'price_comparability', 'sale_date_reason', 'currency_reason'):
            for value, count in market.execute(f'SELECT {field}, COUNT(*) FROM normalized_lots GROUP BY {field}'):
                quality.append((field, value, count))
        wb.sheet('15_경매정규화_품질', '기존 경매자료 정규화 품질',
                 '별도 db/auction_normalized.sqlite의 스테이징 자료. 원본 불변·통화/낙찰상태/가격기준을 분리. 비교 가능 표시는 기계적 조건 충족이지 검증된 시장 통계나 발행 허가가 아닙니다.',
                 ['품질 축', '값/사유', '레코드 수'], quality, {0: 30, 1: 65, 2: 20})
        summary = market.execute('''SELECT house, price_basis, status, COUNT(*),
            SUM(price_comparability='comparable_within_basis'), MIN(sale_date), MAX(sale_date)
            FROM normalized_lots GROUP BY house,price_basis,status ORDER BY house,price_basis,status''')
        wb.sheet('15b_경매_하우스별', '경매사·가격기준·상태별 보유량',
                 'hammer와 hammer_plus_premium을 합쳐 비교하지 않습니다. 원본 lot와 정규화 lot는 별도 SQLite에 모두 보존. 작품/작가 동일성은 자동 병합하지 않았습니다.',
                 ['경매사', '가격 기준', '낙찰 상태', '보유 행수', '기계적 비교조건 충족', '최초 유효일', '최종 유효일'],
                 summary, {0: 28, 1: 30, 2: 22})
        if manifest.is_file():
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            wb.sheet('15c_경매_실행근거', '경매 정규화 실행 근거',
                     'outputs/auction_normalize_manifest.json 원문. 원본 경매 DB의 전후 해시 및 환율 근거 확인용.',
                     ['항목', '값'], [(k, v) for k, v in payload.items()], {0: 30, 1: 110})
    finally:
        market.close()
