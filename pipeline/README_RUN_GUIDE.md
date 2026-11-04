# ARTREND 데이터 수집·검증·한국어 번역 실행 안내

작업 위치는 `ARTRENData/ARTREND_magazine_data/`입니다. 원본 파일·DB·ZIP·자료실은 읽기 전용이며 기존 크롤러나 스케줄러는 실행하지 않습니다. 로그인·결제·접근 차단 우회, 이미지 다운로드, 게시·배포, 스케줄러 설치는 하지 않습니다.

## 파일 구성

| 위치 | 내용 |
|---|---|
| `artrend_mag/` | 수집·정규화·번역·검증 코드. 출처 구현 규약: `work/SOURCE_CONTRACT.md` |
| `db/artrend_magazine.sqlite` | 정규화된 통합 데이터와 원문별 번역·검수 상태 |
| `db/auction_normalized.sqlite` | 원본 경매 DB와 분리된 원문·정규화 스테이징 |
| `raw/<source_id>/<run_id>/` | 보관이 허용된 기관 응답 및 URL·SHA256·수집 시각 색인 |
| `runs/<run_id>/manifest.json` | 실행 버전, 출처별 상태·처리량·제한 사항 |
| `work/audit/` | 원본 자산 조사, 검증, 번역·아카이브 실행 기록 |
| `work/translation/` | 로컬 번역 모델, 설치 출처·버전·해시 |
| `outputs/ARTREND_Data_Audit_and_Collection_Results_<YYYYMMDD>.xlsx` | D01–D71 감사, 출처별 수집 내역, 원문·한국어 대조, 경매 품질 |

언론은 제목·URL·저자·발행일·분류 등 메타데이터만 보관합니다. 기존 발췌문은 최대 300자이며 기사 본문 수집·번역은 하지 않습니다.

## 환경 설정

```bash
cd ARTRENData/ARTREND_magazine_data
mkdir -p work/tmp work/pip_cache
export TMPDIR="$PWD/work/tmp" SQLITE_TMPDIR="$PWD/work/tmp"
export PIP_CACHE_DIR="$PWD/work/pip_cache"
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# .env가 아직 없을 때만 복사합니다. 기존 키 설정을 덮어쓰지 않습니다.
test -e .env || cp .env.example .env
set -a; . ./.env; set +a
.venv/bin/python -m artrend_mag.cli init
.venv/bin/python -m artrend_mag.cli import-legacy
```

`.env`는 자동 로딩되지 않습니다. CLI와 독립 번역 명령은 임시 파일도 프로젝트의 `work/tmp`에 둡니다. 직접 다른 모듈을 실행할 때도 위 환경 변수를 유지합니다. 원본 가져오기는 읽기 전용이며 같은 자료를 다시 가져와도 중복 삽입하지 않습니다.

## 수집·갱신 명령

| 목적 | 명령 |
|---|---|
| 최초 수집 | `.venv/bin/python -m artrend_mag.cli update --mode initial` |
| 정기 증분 갱신 | `.venv/bin/python -m artrend_mag.cli update --mode incremental` |
| 갱신 후 로컬 한국어 번역도 수행 | `.venv/bin/python -m artrend_mag.cli update --mode incremental --translate` |
| 한국 지역만 갱신 | `.venv/bin/python -m artrend_mag.cli update --mode incremental --region KR` |
| 특정 출처 | `.venv/bin/python -m artrend_mag.cli collect --mode incremental --sources broad_public,kiaf_seoul` |
| 출처 목록 | `.venv/bin/python -m artrend_mag.cli list-sources` |
| 파생층·검증·엑셀 각각 갱신 | `... cli derive`, `... cli validate`, `... cli export` |

`update` 순서: 전시·기사 수집 → 파생층 → Wikidata 후보·Wikipedia 조회량 → 파생층 → 선택적 번역 → 검증 → 엑셀입니다. 번역 실패나 검증 실패 때도 엑셀 내보내기를 시도하되 오류를 성공으로 숨기지 않습니다. `--translate`는 설치된 모델을 사전 확인하며 자동 다운로드하지 않습니다.

**CLI 종료 코드 0은 모든 출처 성공을 뜻하지 않습니다.** manifest의 출처별 `state`, `error`, `notes`를 확인해야 합니다. 최초 수집도 무제한 전체 역사 수집이 아닙니다. 기본 조사 범위는 2025-04 이후이며 출처가 저비용으로 노출하는 과거 자료는 추가됩니다. 요청 한도·공개 페이지 범위·실제 날짜를 별도로 기록합니다.

개발용 `ARTREND_SCRATCH=<이름>`은 DB·응답·실행 기록을 `work/dev/<이름>/`으로 분리합니다. 운영 DB를 쓰는 수집·파생·번역 병합·내보내기는 동시에 실행하지 않습니다.

## 아카이브 이어받기

```bash
# 현재 노출된 비평 sitemap의 미관측 URL을 이어받습니다.
.venv/bin/python -m artrend_mag.backfill --sources eflux_criticism --exhaust --max-batches 24
# 발표자료는 지정한 날짜 범위의 배치 경계까지 이어받습니다.
.venv/bin/python -m artrend_mag.backfill --sources eflux_announcements --since 2025-04-01 --max-batches 60
```

각 배치는 미관측 상세 페이지를 최대 60건 처리합니다. 최근 배치 전체의 발행일이 경계 이전이고 날짜 미상이 없어야 날짜 경계 도달로 기록합니다. 기존의 오래된 자료 한 건이나 sitemap의 수정일을 발행일 경계로 대체하지 않습니다. `--max-batches` 도달은 소진이 아닙니다. 노출 sitemap 소진도 사이트 전체 자료의 완전성을 증명하지 않습니다. `work/audit/backfill_*.json`의 종료 사유를 확인합니다. 배치 소속은 같은 초에 기록된 이전 행이 섞이지 않도록 실행 전후 행 번호 범위로 판정하며, 집계 건수가 실행 기록의 삽입 건수와 다르면 `batch_membership_mismatch_review_required`로 멈춥니다.

The Broad 작가 페이지는 공개 HTML에서 실제로 관찰된 링크가 있을 때만 요청합니다. 작품 URL에서 추론한 상위 경로는 작가 식별자로만 쓰고 요청 대상으로 만들지 않습니다. 이전 실행에서 발견한 미수집 상세 페이지는 다음 실행에서도 대기열에 남습니다.

신규 수집기 일괄 확인과 마무리 단계는 다음 순서로 한 번에 하나의 쓰기 작업만 실행합니다.

```bash
sh work/dev/VerifiedBatch/run_chain.sh   # 신규 출처 초기·증분 → Broad 잔여 상세 → e-flux 발표자료
sh work/dev/VerifiedBatch/finalize.sh    # 백업 → 번역 병합 → derive → Wikidata/pageviews → 신규 번역 → validate → export → manifest
```

`collect_sources.py`는 대기열 작성 시점의 수집기 코드 해시가 바뀌면 실행을 거부하고, 실행 중인 다른 수집이 있으면 멈춥니다. 출처별 결과는 `work/audit/public_source_collection_results.json`에 남으며, 초기 실행이 차단·오류이면 증분 실행을 자동 재시도하지 않습니다. 명령 종료 코드 0은 수집 성공을 뜻하지 않으므로 각 실행 상태와 오류 메모를 확인합니다.

The Broad는 현재 공개 목록에서 발견한 미관측 작품 상세·작가 페이지를 우선 처리합니다. 증분 실행은 이미 확인한 페이지도 순환 갱신합니다. 공개 전시·온뷰 표본·작가별 목록은 구분하며 전체 소장품 목록이라고 부르지 않습니다. KIAF는 공개 Info 페이지의 페어 날짜·장소만 수집합니다. 전시자 화면은 허용된 120초 진단까지 시간 초과였으므로 추가 자동 렌더링이나 내부 Vue API 호출을 하지 않습니다. 이 제한은 기술적 미추출이지 접근권한 차단으로 단정하지 않습니다.

## 로컬 한국어 번역

```bash
.venv/bin/pip install -r requirements-translation.txt
# 명시적으로 요청할 때만 검증된 공개 모델을 내려받습니다.
.venv/bin/python -m artrend_mag.translation install-model --languages en,ja,fr,de,es,it,nl,pl,pt,ru,zh
.venv/bin/python -m artrend_mag.translation availability
.venv/bin/python -m artrend_mag.translation --batch-size 500 --progress-every 10000
```

- 영어→한국어: 공식 OPUS 원본 `opusTCv20210807-sepvoc_transformer-big_2022-07-28.zip`, 서로 다른 원문·목표 언어 어휘/토크나이저, CTranslate2 int8입니다. 아카이브 SHA256은 `41f771fa28e864428dd7589992867b2b6dfa402f1191670e818e019dddfceef7`이며 출처·CC-BY-4.0·변환 버전·파일별 해시는 `work/translation/original_opus/ct2-int8/artrend_model.json`에 있습니다.
- 다른 지원 언어는 고정 버전 Argos 모델로 영어를 거친 뒤 같은 한국어 모델을 사용합니다. 양 단계의 추론 호출은 최대 32개 단위로 묶습니다. 품질이 불량했던 별도 Hugging Face 변환본과 기존 Argos 한국어 모델은 사용하지 않습니다.
- 대상은 전시·기사·작품·보고서 제목 및 허용된 짧은 발췌뿐입니다. 원문을 덮어쓰지 않고 원문 해시·언어 판단 근거·모델·버전·상태·검수 필요 여부를 저장합니다.
- `translated`는 자동 추론 결과가 저장되었다는 뜻이며 정확성 검증 완료가 아닙니다. 특히 일본어 중계 번역 표본에서 고유명사 왜곡과 문장 일부 누락이 관찰되었습니다. 원문 대조 검수 전에는 게시하지 않습니다.
- 완료된 작업 DB의 추가 표본 검사에서도 영어 기사 의미 왜곡, 작가명 누락, `accession` 오역과 이탈리아어 구절 누락이 확인됐습니다. `work/audit/translation_model_and_sample_audit.json`에 원문·번역·관찰 내용을 남겼습니다. 모델 파일 해시 일치는 재현성 검사이며 번역 품질 보증이 아닙니다.
- 언어가 불명확하거나 모델이 없는 항목은 `pending`, 품질·추론 실패는 `error`, 한국어 원문은 `skipped`입니다. 이를 번역 완료 건수에 섞지 않습니다.

대규모 번역은 새 작업 DB에서 수행한 뒤 병합하는 편이 안전합니다. 아래 예시는 기존 작업 DB가 있으면 중단합니다.

```bash
.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
root = Path.cwd()
target = root / 'work/dev/KoreanRun/dev.sqlite'
if target.exists():
    raise SystemExit('기존 작업 DB가 있습니다. 덮어쓰지 말고 이어서 번역하거나 다른 이름을 사용하세요.')
target.parent.mkdir(parents=True, exist_ok=True)
source = sqlite3.connect((root / 'db/artrend_magazine.sqlite').as_uri() + '?mode=ro', uri=True)
destination = sqlite3.connect(str(target))
source.backup(destination)
destination.close()
source.close()
PY
ARTREND_SCRATCH=KoreanRun .venv/bin/python -m artrend_mag.translation --batch-size 500
.venv/bin/python -m artrend_mag.translation_merge --source-db work/dev/KoreanRun/dev.sqlite
.venv/bin/python -m artrend_mag.cli export
```

병합은 현재 원문·원문 해시·기록된 언어가 일치하는 행만 받아들이며 더 새로운 번역을 덮어쓰지 않습니다. 변경·삭제된 원문의 낡은 번역은 무효화합니다. 스냅샷 생성 이후 추가된 자료는 별도 번역이 필요합니다. 내보내기도 낡은 번역을 검사합니다.

## 경매 정규화

```bash
.venv/bin/python -m artrend_mag.market_normalize
```

원본 `art_market.db`는 immutable 읽기 전용입니다. 입력 해시와 원본 값, 정규화 결과, 품질 수치는 `outputs/auction_normalize_manifest.json`과 별도 경매 DB에 남습니다. 낙찰 상태·유효한 비미래 날짜·양수 가격·알려진 가격 기준·필요한 환율을 충족해야 기계적인 비교조건 충족으로 분류합니다. 이는 명목 달러 환산 후보일 뿐, 작품·작가·제작연도·물가 등을 통제한 동질 시장 비교를 보장하지 않습니다. 해머가와 수수료 포함가는 섞지 않습니다. 환율은 등록된 ECB 동일일 또는 이전 7일 이내 자료만 쓰며 없는 환율을 만들어 채우지 않습니다.

## 엑셀을 읽는 방법

`00b_카테고리별_수집출처`는 기관/전시/페어, 갤러리, 수상/레지던시, 비평/뉴스, 작품/신원, 시장/보고서/환율, 주목도 등으로 출처를 분류합니다. URL·실제 저장 건수·필드·기간·개최 지역·실행 상태·권리 제한을 확인할 수 있습니다. 출처의 지역 범위와 행사의 실제 개최 지역은 다릅니다. 보고서 귀속은 공식 URL과 증거의 정확한 연결을 사용하며 미귀속 행은 별도로 표시합니다.

`14_번역현황`, `14b_한국어_원문대조`의 단위는 문서가 아니라 번역 대상 필드입니다. `15_경매정규화_품질`, `15b_경매_하우스별`, `15c_경매_실행근거`는 경매 스테이징과 실행 근거를 보여줍니다. 서로 다른 단위의 전시·기사·작품·별칭·증거 수를 하나의 총건수로 더하지 않습니다.

`16_리서치목록_대조`는 추가 리서치 목록 4종의 329개 항목을 유지합니다. 후속 조사 결과는 같은 목록 ID의 이전 판정을 대체하며, 출처 미대응 건수는 0이 아닌 빈칸입니다. 저장 건수는 연결된 출처 전체의 DB 행수이지 해당 메뉴의 수집 완료율이 아닙니다. `implemented_pending_run`은 구현 판정이므로 실제 실행 상태·저장량과 함께 읽어야 합니다. `work/audit/sourcebook_reconciliation_in_progress.xlsx`는 진행 중 확인본이며 최종 통합 산출물이 아닙니다.

리서치 목록 원본의 현재 위치는 `../list/` (`ARTRENData/list/`)입니다. 최초 감사 당시 `Desktop/list/`에서 이동됐으며 네 파일의 내용 해시는 모두 동일합니다. 당시 경로를 담은 기준 감사 파일은 보존하고 현재 경로·해시 대조는 `work/audit/sourcebook_originals_reverification.json`에 기록했습니다. `sourcebook_audit`의 기본 입력 경로도 현재 위치를 사용합니다.

## 접근·해석·게시 제한

- 식별 가능한 User-Agent, robots 규칙, 동일 호스트 최소 3초 또는 더 긴 Crawl-delay, 출처별 요청 한도를 지킵니다. 401/402/403/407/451, 로그인, 실제 CAPTCHA·WAF는 중단합니다. 429/503은 허용된 짧은 Retry-After 범위만 따릅니다.
- robots 파일을 연결 오류나 HTTP 오류로 읽지 못한 경우도 대상 페이지 수집을 중단하지만, 이는 `robots_unavailable` / `blocked_access`로 기록합니다. 확인된 robots 규칙의 금지인 `robots_disallow` / `blocked_permission`과 구분합니다. 이전 실행의 오류 문자열에 `robots_error(...)`가 있으면 법적 허가 거절로 해석하지 않습니다.
- Guggenheim의 일반 공개 렌더링은 확인된 뉴욕 페이지 범위만 사용합니다. 같은 출처의 공개 GET을 수집기로 중계하며 인증·외부 직접 통신·이미지·차단 우회를 허용하지 않습니다. 필요 시 `requirements-browser.txt`와 `PLAYWRIGHT_BROWSERS_PATH="$PWD/work/browser_binaries" .venv/bin/playwright install chromium`으로 선택 구성요소를 설치합니다.
- ARTnews·Art in America·Artforum·ArtAsiaPacific 자동 수집은 허가 전 비활성입니다. RSS가 열린다는 사실은 약관의 예외가 아닙니다. 기존 자료도 내부 감사용입니다.
- MMCA 공개 API(15058313), Naver 등 키가 필요한 API는 키/권한을 별도 확보해야 합니다. 키만으로 미구현 어댑터가 완성되지는 않습니다. Rijksmuseum은 키 없는 공개 OAI-PMH 메타데이터 경로가 확인되어 별도 수집기가 구현됐습니다. 기존 키 기반 API의 제한을 기관 전체에 적용하지 않으며, 운영 수집 여부·페이지 한도·잔여 토큰은 실제 실행 기록으로 확인합니다. SONGEUN robots 전면 금지와 다른 출처의 실제 차단은 우회하지 않습니다.
- K-ARTMARKET 최근 보고서 상세는 공개 GET으로 확인했습니다. 점검한 2024–2026 상세에서 공개 PDF 첨부는 발견되지 않았으며 인쇄본 신청·상업적 이용 승인 문제가 남습니다. POST 전용이라 접근할 수 없다는 예전 설명은 적용하지 않습니다.
- 개최지로 판을 배정합니다. 홍콩·중국 본토·대만·중동은 OTHER, 장소 미상은 미배정입니다. 수집일을 행사일로 대체하지 않습니다. 원문 자체의 역전된 날짜는 검토 큐에 남기며 추측해 고치지 않습니다.
- 공유된 권위 식별자나 명시적 검토 없이는 신원을 확정하지 않습니다. 이름 일치·Wikidata 단일 라벨 일치는 가역적인 후보입니다. 음성/다의 조회 캐시는 30일이며 확정 신원을 뜻하지 않습니다.
- Blueprint의 가중치와 임계값은 검증되지 않은 가설입니다. 관찰되지 않은 값은 0으로 채우지 않습니다. 신호와 카드의 `publishable=0`을 유지합니다.
- 수집 허용과 잡지 재배포 허용은 별개입니다. 이미지 URL이나 권리 상태 미상은 사용 허가가 아닙니다. 모든 카드·자동번역은 편집·권리·신원 검토 전 미게시 상태입니다.

2026-10-28 신규 공개 출처 85개 일괄 실행에서 확인된 제한은 다음과 같습니다. 최신 상태는 `outputs/delivery_manifest.json`의 `public_source_batch`가 출처·모드별 최신 실행으로 다시 집계합니다.

- 기술적 접근 불가(robots 파일 미확인, 권한 거절 아님): A-DESK(ReadTimeout), 부산시립미술관(ConnectTimeout), 리안갤러리(SSLError).
- 권한 제한: TEFAF는 약관 제2조가 자동 수집을 금지하고 정적 자산 robots.txt가 HTTP 403이라 PDF를 요청하지 않았습니다.
- 부분 수집: AIC 검색 API는 2015년 이후 작품 10쪽(796건)까지 저장한 뒤 11쪽에서 HTTP 403으로 멈췄습니다. 공식 문서도 403이어서 문서화된 검색 창 한도인지 확인하지 못했고, 우회하지 않았습니다. Rijksmuseum OAI-PMH는 250쪽 한도와 이어받기 토큰을 사용하므로 소장품 전체가 아닙니다.
- 미소진(후속 구현 필요): Galerie UQAM 목록 카드에는 날짜가 없어 상세 페이지의 `p.date`를 읽도록 추가했지만, 아카이브 646건 중 초기 실행마다 미저장 40건만 읽으므로 아카이브는 미소진이고, Fonderie는 2026년 구분에 항목이 없었습니다. Lisson·Ropac 작가 목록은 이름만 기록하므로 실행 상태가 `no_records`입니다.
- 수정 후 재실행: 페어 7개는 개최장을 `venues` 행으로 저장하도록, 갤러리 8개는 참여 작가 저장 호출을(Esther Schipper는 `/exhibitions/`와 `/artists/`가 시점에 따라 HTTP 200과 404를 번갈아 반환해 재실행도 404로 실패했습니다. 기술적 간헐 실패로 남기고 재시도 폭주나 우회는 하지 않았습니다), 바르샤바 현대미술관은 바뀐 `/en/exhibitions/` 상세 경로를, Crousel은 `<figure>` 카드와 윗첨자 서수 날짜(`19<sup>th</sup>`) 해석을 수정했습니다. Crousel은 h2 작가 줄과 h3 전시 제목을 구분하며 `Group exhibition`은 작가로 저장하지 않습니다. 이들은 2026-10-28 마무리 단계에서 재실행했습니다(페어 7개 성공, 갤러리 10개 성공, Esther Schipper만 404 실패, 바르샤바 18건 추가).
- 날짜 보정: 120자를 넘는 안내 문장(오프닝 리셉션 등)은 전시 기간으로 읽지 않도록 고쳐 Johyun·Ota Fine Arts·Misako & Rosen을 재실행했습니다. Ropac 뉴스의 전시·행사·비엔날레·프로젝트 카드 날짜는 행사 기간이므로 `published_at`에 넣지 않고 `date_text`로만 보존합니다("Featured in …"·뉴스 카드만 게시일). 인천 연도 정밀도 행은 `YYYY`로 저장합니다.

2026-10-29 01:58 기준 최종 검증 상태(`outputs/delivery_manifest.json`):

- 테스트 259개 통과, `cli validate` 실패 0·경고 1(종료일이 시작일보다 이른 원문 행: MoMA 캘린더 1, MUAC 2, 도쿄도미술관 1, Misako & Rosen 1. Misako 행은 원문이 두 프로그램 기간을 한 줄에 적은 것). 미래 게시일 경고는 Ropac 수정 후 0입니다. 증거 원문 4,028개 SHA-256 불일치 0, 원본 파일 418개 해시 일치(폴더 집계 19개는 해시 대상 아님), 리서치 목록 4개 해시 동일, 외래키·무결성 검사 통과.
- Broad 공개 작품 1,294건 모두 상세 증거 보유(누락 0). e-flux 비평은 노출된 sitemap 2,060건(2010-06-10~2026-10-27) 전부, 공지는 5,220건(2024-10-02~2026-10-28)으로 2025-04-01 경계 이전 배치에 도달해 멈췄습니다. sitemap 날짜가 단조가 아니어서 2025-04-01 이후 완전성은 보장하지 않습니다. Rijksmuseum OAI 23,417건은 소장품 전체가 아닙니다.
- 번역 행 790,622개: 번역 108,147 · 대기 659,593 · 건너뜀 15,293 · 품질 게이트 거절 7,589. 모든 자동번역은 원문·해시·언어·모델·버전과 `needs_review`를 유지하며 게시용이 아닙니다. 언어 감지 점수의 마지막 자릿수 부동소수점 차이 때문에 동일 원문이 재번역되던 문제를 고쳐, 재실행 시 변경 없는 행은 `unchanged`로 집계됩니다.
- 신호 14,237개 `publishable=0`, 증거 카드 36개 모두 `draft_unreviewed`.

## 국내 미술 뉴스

- 원본 `아트랜드v2v_20261020.zip`이 Naver 검색 API·Google News RSS로 모은 기사 메타데이터는 `legacy_v2v_artnews`로 들어 있습니다(한국어 14,191건·일본어 8,643·영어 16,313, 2025-10-01~2026-10-19).
- 2026-10-29부터 최신 국내 기사는 언론사 공식 RSS 9개(`kr_*_rss`: 연합뉴스·뉴시스·경향·동아·조선·세계 문화, 서울문화투데이, 아트코리아방송, D-ART)에서 받습니다. 첫 실행 143건. 일반 일간지 문화 피드는 미술 키워드가 제목·분류에 있는 기사만 남기고 맞은 키워드를 `type_basis`에 적습니다. 갤러리·전시·박물관·경매·옥션은 단독으로는 인정하지 않고 다른 미술 단어와 함께일 때만 인정합니다('국화전시회'·'게임박물관' 등 8건 제거). 제목·링크·날짜·필자·분류만 저장하며 본문·발췌·이미지는 저장하지 않고, 재사용 약관은 검토 전입니다.
- RSS는 최신 20~120건만 보여 주므로 `collect --mode incremental`을 매일 돌려야 이력이 쌓입니다. 2026-10-20~10-21 기사는 피드에 이미 없어 일부 비어 있습니다.
- Naver 뉴스 검색 API(`kr_naver_news_api`): 원본이 매일경제·한국경제·헤럴드·서울신문처럼 크롤러를 막는 언론사 기사를 받던 방법입니다(언론사 사이트에 직접 접속하지 않고 API가 제목·원문 링크·요약·발행시각을 줍니다). 원본 검색어(`v2v_entity_aliases.json`, 원본 entity_aliases.json 사본) 43개 + 백필 35개(initial만) + 넓은 미술 검색어 30개. 키는 프로젝트 `.env`의 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`에서만 읽고 DB·URL·원문 파일에 남기지 않습니다. 2026-10-29 첫 수집 14,094건(언론사 666곳, 2025-10-01~2026-10-29).
  - 관련성: 검색 결과 그대로는 골프·부동산·연예 기사가 섞입니다. 원본의 'about' 규칙(별칭+required_keywords, exclude_keywords 없음)을 쓰는 `alias` 473건, 제목에 미술 단어가 있는 `title` 7,978건, 요약에만 미술 단어가 2개 이상 있는 `snippet` 5,643건으로 `type_basis`에 구분합니다. 볼트 읽을거리에는 `alias`·`title`만 씁니다. 나머지(약 1만2천 건)는 저장하지 않았습니다.
  - Naver 요약은 검색어 주변 문장이라 검색어마다 달라집니다. 처음 저장한 요약(300자 이하)을 유지해 재실행 시 행이 바뀌지 않습니다.
  - 약관: Naver 개발자센터 약관(원본 기록상 '비상업적 활용'). 내부 조사용이며, 잡지 게재 전 약관 확인이 필요합니다. 하루 25,000회 한도 중 매일 갱신은 약 300~350회입니다.
- 못 쓰는 채널: Google News RSS는 news.google.com robots.txt가 `/rss/search`를 막아 쓰지 않습니다(원본 코드는 robots를 확인하지 않았습니다). 매일경제·헤럴드(robots 403), 한경·한겨레(HTTP 403), 서울신문·아시아경제(robots 차단)는 직접 RSS를 받지 않고 Naver API 결과로 들어옵니다.
- 매일 갱신 예: `.venv/bin/python -m artrend_mag.cli collect --mode incremental --region KR` 뒤 `cli vault`.

## 일본·해외 미술 뉴스

- 원본의 Google News RSS 경로는 news.google.com robots.txt가 `/rss` 전체(검색·헤드라인·주제·섹션)를 막고 Claude·GPT 등 AI 수집기도 이름으로 막아 이어 받지 않습니다. 원본이 받아 둔 일본어 8,643건·영어 16,313건(~2026-10-19)은 `legacy_v2v_artnews`로 볼트에 있습니다.
- 2026-10-29부터 언론사 공식 RSS 8곳(`gl_news.py`)을 추가했습니다. 첫 실행 70건.
  - 일본: 朝日新聞 文化, 産経新聞 ライフ(미술 단어 필터), This is Gallery Media, Spoon & Tamago(전체).
  - 해외: Observer Arts, Colossal, Le Monde Arts(전체), BBC Entertainment & Arts(미술 단어 필터). 기존 The Art Newspaper·ArtReview·e-flux·美術手帖·artscape·ART iT 등과 함께 읽을거리에 나옵니다.
  - 일본 일반지 문화면은 미술 기사가 하루 0~2건이라 양이 적습니다. 일본 기사는 기존 미술 전문 매체 피드가 주력입니다.
- 약관상 자동 수집 금지라 등록만 하고 끈 곳(`blocked_permission`): The Guardian(크롤러·스크레이퍼 금지), The New York Times(텍스트·데이터 마이닝 금지), SCMP(자동 시스템 일체 금지). Guardian·NYT는 키가 필요한 공식 API가 있습니다.
- 약관 페이지가 403이라 확인하지 못해 등록하지 않은 곳: artnet, Artsy, Smithsonian. Japan Times·fashion-press는 robots 403, 요미우리·도쿄신문·Tokyo Art Beat는 RSS 없음(404).
- RSS 1.0(RDF) 형식(아사히)을 읽도록 공용 파서를 고쳤고, 산케이 피드의 `null/` 링크는 언론사 주소로 바로잡습니다.

## 프런트페이지 목업 (한국·일본·미주·유럽)

- 볼트 `00_프런트페이지/ARTREND <지역> 홈`: Blueprint v1.2의 홈 구성(H00 헤더 → H01 TODAY'S INSIGHT → H02 ARTISTS IN FOCUS → H03 TREND NEWS → H04 EXHIBITIONS → H05 GALLERY MOVES → H06 EMERGING PATTERNS → H07 ROOKIE RADAR → H08 MARKET CONTEXT → H09 방법)을 지역마다 따로 계산합니다. 한장요약 W42의 '사실 → 그래서? → 숫자로 본 한 주 → 다가오는 일정 → 낯선 말' 구성을 넣었습니다.
- 계산은 `artrend_mag/frontpage.py`: 집계 마감 07:00 KST, 24시간·7일·직전 4주 창(HL02), 비교 패널·coverage(HL03), 보도 집중(HL07)·활동 확산(HL08)·새로운 징후·주요 소식, 편성(HL13), 섹션별 선발(FP04~FP10). 문장은 계산값을 넣은 고정 문형이며 언어모델이 쓰지 않습니다. 모두 `publishable=0`.
- 근거가 없는 섹션은 빈 상태와 '모자란 조건'을 보여 줍니다. 후보별 통과·탈락 사유는 `선발 기록 (<지역>)`, 지역 비교·크롤링 플랜 대조·사용자 조치는 `데이터 부족 점검`, 규칙 설명은 `프런트페이지 로직`에 있습니다.
- 웹사이트용 응답 형태(OP03)는 `outputs/frontpage/ARTREND_home_<지역>_<날짜>.json`입니다.
- 화면 스타일은 볼트의 `.obsidian/snippets/artrend-home.css`(자동 활성화). 꺼도 일반 콜아웃으로 읽힙니다.
- 매일 순서: `collect --mode incremental` → `cli brief --asof <오늘>`(주요 소식 후보·수상 기사 본문 읽기, 기준 점수) → 편집 메모 `editorial/notes_<오늘>.json` 작성(요약·왜·그래서?, 상별 주최·심사·지원·수상자·선정 사유) → `cli brief --asof <오늘> --check-names`(수상자 루키 조건 R01~R05 확인, `editorial/rookie_watchlist.json` 누적) → `cli vault --asof <오늘>`. 언론사 RSS는 35일 연속 수집(2026-12-03 이후)부터 보도 비교 패널에 들어갑니다.
- 본문은 robots가 허용하는 기사만 읽고 핵심 문장 300자 이하와 SHA-256만 `work/editorial/packets_<날짜>.json`에 남깁니다(본문·이미지 저장 없음). 수상자 이력 확인은 네이버 뉴스 검색 API(이름+"작가") 제목 기준이며 미술과 무관한 동명이인 기사는 걸러 냅니다.
- 홈의 '핵심 정리'(한장요약 W42 형식: 사실 요약 → 왜 주요 소식인가 → 그래서?)와 'ROOKIE RADAR'(상의 무게·트랙·수상자별 루키 조건)는 편집 메모가 있을 때 나옵니다. 누적 명단은 `00_프런트페이지/루키 관찰 명단`.

## Obsidian 볼트

`outputs/ARTREND_Obsidian_Vault/` 폴더(또는 같은 내용의 `outputs/ARTREND_Obsidian_Vault.zip`)를 Obsidian에서 '폴더를 볼트로 열기'로 엽니다. 시작 노트는 `00_홈`입니다.

- `01_데일리인사이트`: 기준일까지 7일 × 5개 에디션 데일리 리포트. 위에서 아래로 읽습니다: 전날·다음날·다른 에디션 이동 줄 → **한눈에**(진행 중·개막·종료·기사·소식 수 표와 요약 문장) → **1 오늘의 주요 소식**(같은 소식 기사를 제목 유사도로 묶어 대표 1건, 최근 2일 우선 8개, 줄마다 '왜: 5개 매체 보도 · 수상·선정 …' 점수 이유와 같은 소식을 낸 매체) → **2 전시 캘린더**(이번 주 개막·2주 내 개막·7일 내 종료) → **3 주제별 소식**(전시·프로그램 / 수상·인물 / 시장·경매·아트페어 / 기관·정책·제도 / 비평·리뷰 / 그 밖, 주제마다 5개) → **4 글로벌 비평·공지** → **5 분석 카드**(Blueprint A–F·H01–H08, 접힌 상자) → **6 편집자 메모**(체크리스트) → **부록**(열려 있는 전시 전체, 접힌 표). 묶기·점수 규칙은 원본 v2v `importance.py`(스토리 묶기 + 설명 가능한 점수)를 옮긴 `artrend_mag/news_digest.py`이며 페이지의 '고르는 규칙' 상자에 그대로 적혀 있습니다. 점수는 읽는 순서일 뿐 중요도 판단이 아니고, 카드·신호·게시 여부에 쓰지 않습니다. 모두 `publishable: false` 초안입니다.
- `02_에디션` → `03_전시·프로그램/에디션/연도` → `04_작가`(첫 글자) → `05_기관`(유형) → `06_기사·비평`(출처/월) → `07_리포트` → `08_증거카드` → `09_출처`(운영 상태) → `10_시장참고` → `11_소장품`(출처별 요약·표본, 작품 개별 노트 없음).
- 노트 사이는 위키링크로 이어져 그래프·백링크로 따라갈 수 있고, YAML 속성(`type`, `edition`, `start`, `source_id`, `publishable`)으로 거를 수 있습니다.
- 볼트는 DB를 읽기 전용으로 보여 주는 산출물입니다. 권한 제한 출처의 과거 기사 행은 넣지 않고, 원본 DB 발견용 기사 메타데이터는 목록에만 두며 읽을거리에는 쓰지 않습니다. 이미지는 넣지 않습니다. 고유 제목은 원문 그대로 링크하고 자동번역은 원문 옆에만 둡니다.
- 다시 만들기: `.venv/bin/python -m artrend_mag.cli vault --asof 2026-10-29 --days 7` (수집·번역 갱신 뒤). 다시 만들 때 `99_내메모` 폴더와 `.obsidian` 설정은 유지되고, 나머지 폴더는 새로 생성됩니다. 직접 쓴 메모는 `99_내메모`에 둡니다.

권장 갱신 주기는 기관·갤러리·페어 주 1회, 보고서 월 1회입니다. 첫 명단 관측은 신규 소속의 증거가 아니며 비교 가능한 다음 관측이 필요합니다. 스케줄러는 설치하지 않았습니다. 최종 범위와 남은 제한은 날짜별 manifest 및 검증 파일의 실제 상태를 기준으로 판단합니다.
