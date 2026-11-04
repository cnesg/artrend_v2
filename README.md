# ARTREND — 웹 매거진 (Vercel)

데이터를 정해진 판단 규칙으로 읽어 매일 트렌드 인사이트를 싣는 미술 매거진입니다. 한국, 일본, 미주, 유럽 4개 에디션이 있습니다.
첫 화면은 헤더(날짜·갱신 시각·에디션 전환), **TRENDING NOW**(가장 중요한 소식 3건), 회색 띠(HOT TRENDS 키워드, ROOKIE RADAR·GALLERY MOVES 카드, TODAY'S INSIGHT 헤드라인 슬라이드, TRENDING ARTISTS) 순서입니다(`components/Top.tsx`, `HeroCarousel.tsx`, `Art.tsx`). 헤드라인은 전시, 갤러리, 기관, 작가, 수상·루키, 비평, 페어, 보도 데이터를 함께 읽어서 고릅니다.
HOT TRENDS 키워드(`artrend_mag/keywords.py`)는 미술 개념 사전·이름 붙은 행사·화제 작가만 후보로 삼고, 이번 주 서로 다른 소식 3건·매체 2곳 이상이면서 지난 4주보다 비중이 1.4배 이상 늘어난 것만 싣습니다. 칩을 누르면 근거 건수와 예시 기사가 열립니다. 이미지는 권리 문제로 쓰지 않고 색면 구성으로 대신합니다.
그 아래로 지금 주목받는 작가, 편집자 브리핑(무슨 일이고 왜 중요하며 그래서 무엇이 달라지는지), 주요 소식, 이번 주 전시, 갤러리 움직임, ROOKIE RADAR, 비평과 페어가 이어집니다.

## 구조

| 경로 | 내용 |
|---|---|
| `app/`, `components/`, `lib/` | Next.js 15 정적 사이트. `data/`의 JSON만 읽기 때문에 서버리스 함수와 DB가 필요 없습니다 |
| `data/` | 하루 단위 피드: `site.json`, `<날짜>/<KR·JP·AMERICAS·EUROPE>.json`, `logic.json`, `rookie_watchlist.json`. 매일 자동으로 갱신됩니다 |
| `pipeline/` | 수집·판단 백엔드 코드(`artrend_mag`)와 테스트, 편집 메모(`editorial/`). DB·원본·`.env`는 저장소에 넣지 않습니다 |
| `scripts/daily_update.sh` | 매일 수집 → 판단 → 볼트·웹 피드 생성 → `data/` 커밋·푸시 |
| `scripts/com.artrend.daily.plist`, `install_schedule.sh` | macOS launchd로 매일 07:00에 시작하고 08:30에 게시합니다 |
| `.github/workflows/check.yml` | 푸시할 때마다 빌드를 검사해 깨진 데이터가 배포되기 전에 잡습니다 |

페이지는 다음과 같습니다.
- `/kr` `/jp` `/americas` `/europe`: 최신 호
- `/<에디션>/<날짜>`: 지난 7일 아카이브
- `/logic`: 판단 기준
- `/rookie`: 루키 관찰 명단

## 왜 08:30 갱신을 Mac에서 돌리나

수집 DB는 약 1GB이고 원본은 1.4GB입니다. 여기에 Naver API 키도 필요합니다. 그래서 GitHub Actions나 Vercel 함수에서 매일 다시 만들 수 없습니다.
수집과 판단은 DB가 있는 Mac에서 돌리고, 결과 JSON(수 MB)만 푸시합니다. 07:00에 수집을 시작하고, 다 만든 결과는 08:30까지 기다렸다가 푸시합니다. 푸시가 들어오면 Vercel이 자동으로 다시 빌드해(약 1분) 08:30 무렵 새 호가 올라갑니다. 수집이 08:30을 넘기면 끝나는 즉시 푸시합니다. 게시 시각은 `PUBLISH_AT=09:00`처럼 바꿀 수 있습니다.
수집이 일부 실패해도 이미 모은 데이터로 페이지를 만듭니다. 편집 메모가 없는 날은 규칙 기반의 '자동 판단'이 요약·이유·그래서를 채웁니다.

## 설정 순서

1. **GitHub 저장소 만들기** (비공개 권장)
   ```bash
   cd artrend-web
   git init && git add . && git commit -m "ARTREND web"
   gh repo create artrend-web --private --source . --push
   ```
2. **Vercel 연결**
   - Vercel 대시보드에서 Add New → Project로 이 저장소를 가져옵니다. Framework는 Next.js로 자동 인식되며 설정을 바꿀 필요는 없습니다.
   - 게시 전 내부 초안이므로 Settings → Deployment Protection에서 비밀번호나 Vercel Authentication을 켜 두세요.
   - 사이트는 `noindex` 헤더와 메타로 검색 노출을 막아 두었습니다.
3. **매일 08:30 자동 갱신 설치** (DB가 있는 Mac에서 한 번만)
   ```bash
   scripts/install_schedule.sh /Users/rainierai/Desktop/ARTRENData/ARTREND_magazine_data
   launchctl start com.artrend.daily      # 지금 한 번 실행해 보기
   ```
   - Mac은 07:00~08:30에 켜져 있어야 합니다. 잠자기 상태라면 깨어난 직후에 실행됩니다.
   - 시스템 설정 → 배터리 → 옵션에서 정기 깨우기를 설정하거나 `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00`을 쓰세요.
   - 로그는 `<pipeline>/runs/daily_<날짜>.log`에 남습니다.
   - `git push`는 이 Mac의 GitHub 인증(`gh auth login`)을 그대로 씁니다.
4. **수동 실행**
   ```bash
   ARTREND_PIPELINE=/Users/rainierai/Desktop/ARTRENData/ARTREND_magazine_data scripts/daily_update.sh
   ```

## 편집자가 손대는 곳

자동 판단만으로도 페이지는 매일 채워집니다. 편집자 판단을 넣으려면 `pipeline` 쪽 `editorial/notes_<날짜>.json`을 쓰면 됩니다.
- `major`: 주요 소식의 요약·이유·그래서
- `awards`: 수상·선정
- `glance`: 이번 주 흐름
- `daily`: 개별 기사 메모

편집 메모가 자동 판단보다 우선합니다. 메모는 앞뒤 일주일 동안 재사용됩니다.
형식은 `pipeline/README_RUN_GUIDE.md`를 참고하세요.

## 로컬 미리보기

```bash
npm install
npm run dev     # http://localhost:3000/kr
```

## 원칙

- 모든 카드와 신호는 `publishable=false` 상태의 내부 초안입니다.
- 언론 기사는 링크와 300자 이하 요약만 싣고, 본문과 이미지는 저장하지 않습니다.
- 로그인, 유료 장벽, robots, 이용약관을 우회하지 않습니다. 수집을 금지한 매체는 수집하지 않습니다.
- 신호 세기는 숫자 기준일 뿐 예술적 가치에 대한 판단이 아닙니다. 가격과 조회수도 예술적 가치로 보지 않습니다.
- 데이터가 없으면 0이 아니라 '확인 안 됨'으로 표시합니다.

## EARLY SIGNAL · OFFICIAL · 이미지 (11/4 추가)

- `early` (artrend_mag/early.py): 지금 열려 있거나 21일 안에 여는 전시를 보도 증가, 작가 지명도, 대형 행사, 곧 종료 여부로 점수화합니다. TRENDING NOW도 이 목록에서 고릅니다. '폐막·n만 명 찾아' 같은 사후 기사는 헤드라인과 메인 뉴스에서 뒤로 밀립니다.
- `official`: 미술관·갤러리 공식 뉴스/공지(`news_*` 출처 67곳, `kr_heredium`)에서 최근 2주 발표를 모읍니다. 채용·휴관·티켓 공지는 제외합니다.
- 이미지: 기관 공식 이미지 URL을 링크로만 표시합니다(내부 미리보기용, 저장하지 않음). 공개 배포 전에는 `image_rights`의 권리 상태를 확인하세요.
