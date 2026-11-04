"""Human-readable source inventory, using stored row counts rather than run counters."""
import sqlite3

from .config import WORK_ROOT

HEADERS = [
    '카테고리', '출처명', 'source_id', '출처 URL', '수집한 자료·필드', '수집 상태',
    '이벤트 건수', '기사 메타 건수', '작품 건수', '관계 건수', '보고서 건수',
    '식별·별칭 행수', '환율 행수', '페이지뷰 행수', '증거 행수', '경매 스테이징 행수',
    '이벤트 시작일 범위', '기사 발행일 범위', '기타 자료 관측기간', '실제 개최 지역', '소스 관찰범위',
    '최근 실행 완료시각', '최근 실행 결과', '수집 방법', '본문 보관 정책',
    '수집 약관·제한', '이미지 권리', '범위·주의사항',
]


def _category(source, counts):
    kind = source['source_kind']
    if counts['works'] and not counts['events']:
        return '05 작품·작가 식별'
    if kind == 'legacy_local':
        if counts['articles']:
            return '04 비평·뉴스'
        if 'award' in source['source_id']:
            return '03 수상·레지던시'
        if counts['events']:
            return '01 기관·전시·비엔날레·페어'
        if counts['reports'] or counts['auction_lots'] or 'report' in source['source_id'] or 'market' in source['source_id']:
            return '06 시장·리포트·환율'
        return '05 작품·작가 식별'
    return {
        'museum': '01 기관·전시·비엔날레·페어',
        'biennial': '01 기관·전시·비엔날레·페어',
        'fair': '01 기관·전시·비엔날레·페어',
        'gallery': '02 갤러리·관계',
        'award': '03 수상·레지던시',
        'residency': '03 수상·레지던시',
        'foundation': '03 수상·레지던시',
        'media': '04 비평·뉴스',
        'identifier': '05 작품·작가 식별',
        'report': '06 시장·리포트·환율',
        'reference': '06 시장·리포트·환율',
        'attention': '07 관심도 관측',
    }.get(kind, '08 기타')


def catalog_rows(con, sources, last_run):
    counts_by_source = {}
    for table in ('events', 'articles', 'works', 'relationships', 'aliases', 'fx_rates', 'evidence'):
        for sid, count in con.execute(f'SELECT source_id, COUNT(*) FROM {table} GROUP BY source_id'):
            counts_by_source.setdefault(sid, {})[table] = count
    # Reports have no source_id: use exact official URL -> evidence attribution, never publisher-name guessing.
    for sid, count in con.execute('SELECT e.source_id, COUNT(DISTINCT r.report_id) FROM reports r '
                                  'JOIN evidence e ON e.url=r.official_url GROUP BY e.source_id'):
        counts_by_source.setdefault(sid, {})['reports'] = count
    pageviews = con.execute("SELECT COUNT(*) FROM signals WHERE model_version='pageviews-raw'").fetchone()[0]
    counts_by_source.setdefault('wikimedia_pageviews', {})['pageviews'] = pageviews
    auction_path = WORK_ROOT / 'db' / 'auction_normalized.sqlite'
    if auction_path.is_file():
        market = sqlite3.connect(auction_path.as_uri() + '?mode=ro', uri=True)
        try:
            if market.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_lots'").fetchone():
                count = market.execute('SELECT COUNT(*) FROM normalized_lots').fetchone()[0]
                counts_by_source.setdefault('legacy_art_market_db', {})['auction_lots'] = count
        finally:
            market.close()
    other_periods = {}
    for sid, first, last in con.execute(
            'SELECT source_id, MIN(rate_date), MAX(rate_date) FROM fx_rates GROUP BY source_id'):
        other_periods[sid] = f'환율 기준일: {first} ~ {last}'
    if pageviews:
        first, last = con.execute(
            "SELECT MIN(asof), MAX(asof) FROM signals WHERE model_version='pageviews-raw'").fetchone()
        other_periods['wikimedia_pageviews'] = f'페이지뷰 관측월: {first} ~ {last}'
    for sid, periods in con.execute(
            'SELECT e.source_id, GROUP_CONCAT(DISTINCT r.observation_period) FROM reports r '
            'JOIN evidence e ON e.url=r.official_url GROUP BY e.source_id'):
        other_periods[sid] = '보고서 관측기간: ' + (periods or '미상')
    event_periods = {r[0]: r[1:] for r in con.execute(
        'SELECT source_id, MIN(start_date), MAX(start_date), GROUP_CONCAT(DISTINCT edition_region) '
        'FROM events GROUP BY source_id')}
    article_periods = {r[0]: r[1:] for r in con.execute(
        'SELECT source_id, MIN(published_at), MAX(published_at) FROM articles GROUP BY source_id')}
    event_types = {r[0]: r[1] for r in con.execute(
        'SELECT source_id, GROUP_CONCAT(DISTINCT event_type) FROM events GROUP BY source_id')}
    fields = {
        'events': '이벤트: 제목·개최일/정밀도·장소·유형·URL',
        'articles': '기사 메타: 제목·저자·발행일·유형·URL (본문 제외)',
        'works': '작품: 제목·제작연도 원문·매체·소장기관·URL',
        'relationships': '관계: 주체·대상·관계유형·관측시각·근거',
        'reports': '보고서: 제목·발행기관·관측기간·공식URL·파일 해시',
        'aliases': '식별/별칭: 표기·언어·외부ID·매칭 상태',
        'fx_rates': '환율: 기준일·기준통화·상대통화·환율',
        'pageviews': '관심도: 월별 Wikipedia 사용자 페이지뷰 (순위 아님)',
        'auction_lots': '경매: 원본 lot·낙찰상태·통화·가격기준·환율·비교제외사유 (별도 auction_normalized.sqlite)',
    }
    keys = ('events', 'articles', 'works', 'relationships', 'reports', 'aliases', 'fx_rates', 'pageviews', 'evidence', 'auction_lots')
    registered = {s['source_id'] for s in sources}
    unattributed = {key: sum(counts.get(key, 0) for sid, counts in counts_by_source.items()
                            if sid not in registered) for key in keys}
    unattributed['reports'] = con.execute(
        'SELECT COUNT(*) FROM reports r WHERE NOT EXISTS '
        '(SELECT 1 FROM evidence e JOIN sources s ON s.source_id=e.source_id WHERE e.url=r.official_url)'
    ).fetchone()[0]
    if any(unattributed.values()):
        counts_by_source['(미귀속)'] = unattributed
        sources = list(sources) + [dict(source_id='(미귀속)', name='출처 연결 미확정 (로컬 자료 포함)',
                                       source_kind='unattributed',
                                       notes='원본 보유량에는 포함되지만 등록 출처와 직접 연결되지 않은 행. 출처를 추정해 배정하지 않음.')]
    output = []
    for s in sources:
        sid = s['source_id']
        counts = {key: counts_by_source.get(sid, {}).get(key, 0) for key in keys}
        run = last_run.get(sid, {})
        has_data = any(counts[k] for k in keys if k != 'evidence')
        state = s.get('operational_state') or ''
        if sid == '(미귀속)':
            status = '보유자료·출처 연결 미확정'
        elif state.startswith('blocked'):
            status = '접근/권한 차단' + (' (기존 보유자료 있음)' if has_data else '')
        elif run.get('state') in ('error', 'partial', 'blocked'):
            status = '일부 수집/최근 실행 문제' if has_data else '미수집/최근 실행 문제'
        elif has_data:
            status = '기존 로컬 자료 재사용' if sid.startswith('legacy_') else '수집 기록 있음 (범위 한정)'
        else:
            status = '미수집/등록만 됨'
        ev = event_periods.get(sid, (None, None, None))
        art = article_periods.get(sid, (None, None))
        period = lambda values: f'{values[0] or "미상"} ~ {values[1] or "미상"}'
        notes = ['건수는 현재 DB 보유 행수; 서로 다른 단위이므로 합산 금지. 필드별 결측 가능.',
                 '수집 기록은 전체 아카이브 확보 또는 발행 허가를 의미하지 않음.']
        if counts['events']:
            notes.append('이벤트 유형: ' + (event_types.get(sid) or '미상'))
        if s['source_kind'] == 'report' or 'report' in sid:
            notes.append('보고서 수는 공식 URL과 증거 URL이 정확히 연결된 건만 포함; 미연결 로컬 PDF는 07 시트 참조.')
        if s.get('st_history'):
            notes.append('과거 범위: ' + s['st_history'])
        if s.get('notes'):
            notes.append(s['notes'])
        if run.get('error'):
            notes.append('실행 메모: ' + run['error'])
        output.append([
            _category(s, counts), s['name'], sid, s.get('entry_url') or s.get('base_url'),
            '; '.join(label for key, label in fields.items() if counts[key]) or '저장된 본 데이터 없음',
            status, *[counts[k] for k in keys], period(ev) if counts['events'] else None,
            period(art) if counts['articles'] else None, other_periods.get(sid),
            ev[2] or None, s.get('region_scope'),
            run.get('finished_at'), run.get('state') or '실행 이력 없음', s.get('access_method'),
            s.get('text_storage_policy'), s.get('st_collection_terms'), s.get('st_image_terms'), '; '.join(notes),
        ])
    return sorted(output, key=lambda row: (row[0], row[1], row[2]))
