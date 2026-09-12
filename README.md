# NewsBot — 뉴스 수집 · AI 요약 · 인사이트 분석 · 리포트 CLI

뉴스를 **수집(RSS + 크롤링)** → **정제(raw/clean 분리)** → **AI 요약** → **AI 인사이트 분석**
→ **시각화·리포트** → **내보내기(CSV/JSONL/Excel)** 까지 처리하는 커맨드라인 애플리케이션입니다.

---

## 1. 빠른 시작

```bash
# 0) 의존성 설치 (Python 3.10 이상)
pip install -r requirements.txt

# 1) 설정 파일 준비 (이미 config.json 이 있으면 생략)
cp config.example.json config.json

# 2) (선택) AI API 키 등록 — 없으면 규칙 기반 mock 모드로 동작합니다
cp .env.example .env      # .env 를 열어 키를 채웁니다

# 3) 전체 파이프라인 실행
python main.py fetch --category 경제,산업 --limit 20 --auto-clean
python main.py summarize --unsummarized --limit 10
python main.py analyze --category 경제
python main.py report --format md
python main.py export --format csv --status summarized
```

---

## 2. 폴더 구조

```
a2-2/
├── main.py                     # CLI 진입점 (newsbot.cli.main 호출)
├── config.json                 # 설정: 뉴스 소스 URL, 중복 정책, AI 모델, 경로, 로깅
├── config.example.json         # 설정 템플릿
├── .env.example                # API 키 환경변수 템플릿 (.env 는 커밋 금지)
├── requirements.txt
├── README.md
│
├── newsbot/                    # ── 애플리케이션 패키지 (모듈 13개) ──
│   ├── config.py               # 설정 로딩 / 점표기 조회 / 환경변수에서 API 키 해석
│   ├── logger.py               # 콘솔 + 회전 파일 로깅 (INFO/WARNING/ERROR)
│   ├── utils.py                # 텍스트 정규화 · 날짜 파싱 · URL 정규화 · 해시 · 토큰화
│   ├── storage.py              # SQLite 저장소 (raw / clean / analyses / fetch_runs)
│   ├── cleaner.py              # 정제 규칙 + 중복 정책(skip/upsert)
│   ├── visualize.py            # matplotlib 차트 3종 (한글 폰트 적용, PNG)
│   ├── report.py               # 품질 지표 · TOP N · AI 인사이트 리포트 (콘솔/TXT/MD)
│   ├── exporter.py             # CSV / JSONL / Excel 내보내기
│   ├── cli.py                  # argparse 서브커맨드 정의 + 명령 구현
│   │
│   ├── collectors/             # 수집 계층
│   │   ├── http_client.py      #   타임아웃 · 재시도 · 요청 간 지연 · robots.txt
│   │   ├── rss.py              #   방법 1: RSS 피드 수집
│   │   ├── crawler.py          #   방법 2: 목록/상세 페이지 크롤링 (BeautifulSoup)
│   │   ├── article.py          #   기사 HTML 파서 (두 수집기가 공유)
│   │   └── base.py             #   수집 결과 자료구조
│   │
│   └── ai/                     # AI 계층
│       ├── client.py           #   Gemini / OpenAI / Anthropic 공통 호출 + mock 판별
│       ├── mock.py             #   API 키가 없을 때의 규칙 기반 대체 구현
│       ├── summarizer.py       #   뉴스 요약
│       ├── analyzer.py         #   기간·카테고리 종합 인사이트 분석
│       └── sentiment.py        #   감성 분석 (보너스)
│
├── data/newsbot.db             # SQLite 영구 저장소 (자동 생성)
├── logs/newsbot.log            # 실행 로그 (자동 생성)
└── output/
    ├── charts/                 # PNG 차트
    ├── reports/                # TXT / MD 리포트
    └── exports/                # CSV / JSONL / XLSX
```

---

## 3. 설정

### 3-1. config.json

| 블록 | 설명 |
|---|---|
| `paths` | DB·차트·리포트·내보내기·로그 경로 |
| `http` | `timeout`, `max_retries`, `backoff_sec`, `request_delay_sec`, `user_agent`, `respect_robots` |
| `sources` | 뉴스 소스별 RSS/목록 URL 템플릿, 카테고리 매핑, 본문 선택자, 제거할 문단 패턴 |
| `cleaning` | `on_duplicate`(skip/upsert), 필수 필드, 최소 길이, 결측 기본값 |
| `ai` | 제공자·모델·엔드포인트·**API 키 환경변수 이름**, 요약/분석/감성 파라미터 |
| `report` | TOP N 기본값, 리포트 형식, 차트 포함 여부 |
| `chart` | 한글 폰트 후보, DPI, 기본 크기 |
| `logging` | 레벨, 로그 파일, 회전 크기 |

카테고리는 한글 라벨 → 사이트 슬러그로 매핑되어 있습니다.

```jsonc
"categories": { "정치": "politics", "경제": "economy", "산업": "industry", ... }
```

사용 가능한 카테고리는 아래로 확인합니다.

```bash
python main.py fetch --list-categories
```

### 3-2. API 키 관리 

`config.json` 에는 **키 값이 아니라 환경변수 이름만** 저장합니다.

```jsonc
"ai": {
  "provider": "auto",                     // auto | gemini | openai | anthropic | mock
  "providers": {
    "gemini":    { "api_key_env": "GEMINI_API_KEY",    "model": "gemini-2.5-flash" },
    "openai":    { "api_key_env": "OPENAI_API_KEY",    "model": "gpt-4o-mini" },
    "anthropic": { "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-opus-5" }
  }
}
```

키 주입 방법은 세 가지 중 아무거나 쓰면 됩니다.

```powershell
# PowerShell
$env:GEMINI_API_KEY = "발급받은키"
```
```bash
# bash / zsh
export GEMINI_API_KEY="발급받은키"
```
```ini
# 또는 프로젝트 루트의 .env 파일 (기존 환경변수가 우선합니다)
GEMINI_API_KEY=발급받은키
```

`provider: "auto"` 이면 키가 존재하는 제공자를 우선순위대로 자동 선택합니다.
**키가 하나도 없으면 `mock`(규칙 기반) 모드로 떨어져** 네트워크 없이도 전체 기능을 확인할 수 있고,
결과에는 항상 `[mock]` 표시가 남습니다. 키를 넣는 순간 코드 수정 없이 실제 LLM 호출로 전환됩니다.

---

## 4. 명령어 레퍼런스

전역 옵션: `--config <경로>`, `--log-level {DEBUG,INFO,WARNING,ERROR}`

### `fetch` — 뉴스 수집 → raw 저장

```bash
python main.py fetch --source yna --method all --category 경제,산업 --limit 20 --auto-clean
```

| 옵션 | 설명 |
|---|---|
| `--source` | 뉴스 소스 키 (기본: `sources.default`) |
| `--method` | `rss` · `crawl` · `all`(기본) |
| `--category` | 카테고리. 반복 지정 또는 쉼표 구분 |
| `--limit` | **수집 방법별** 최대 기사 수 (기본 20) |
| `--no-content` | RSS 수집 시 본문 페이지를 추가로 받지 않음(빠름) |
| `--delay` | 요청 간 최소 지연(초). 설정값을 덮어씀 |
| `--auto-clean` | 수집 직후 정제까지 이어서 실행 |
| `--list-categories` | 사용 가능한 카테고리 출력 |

```
[INFO] 뉴스 수집 시작: source=yna, method=all, limit=6, 카테고리=경제, 산업
[INFO] RSS 요청: 경제 (https://www.yna.co.kr/rss/economy.xml)
[INFO] RSS 수집 [경제]: 3건
[INFO] 목록 페이지 크롤링: 경제 (https://www.yna.co.kr/economy/all)
[INFO] 크롤링 수집 [경제]: 3건
[INFO] 수집 완료: 12건 성공, 0건 실패
[INFO] raw 저장소에 저장 완료 (누적 12건)
```

### `clean` — 정제 → clean 저장

```bash
python main.py clean --on-duplicate upsert --limit 100
```

| 옵션 | 설명 |
|---|---|
| `--limit` | 처리할 raw 최대 건수 |
| `--on-duplicate` | `skip`(기본) · `upsert` |
| `--reprocess` | 이미 처리한 raw 도 다시 정제 (정제 규칙을 바꿨을 때) |

```
[INFO] 정제 시작: 12건 (중복 정책=skip)
[INFO] 정제 완료: 신규 7건, 갱신 0건, 중복 5건, 폐기 0건
```

### `summarize` — AI 요약

```bash
python main.py summarize --unsummarized --limit 10
python main.py summarize --id 42 --max-chars 150 --force
python main.py summarize --all --category 경제 --dry-run
```

| 옵션 | 설명 |
|---|---|
| `--all` / `--id N` / `--unsummarized` | 대상 선택 (기본 `--unsummarized`) |
| `--limit`, `--category`, `--date-from/--date-to/--date` | 대상 필터 |
| `--max-chars` | 요약 최대 글자 수 |
| `--force` | 이미 요약된 뉴스도 다시 요약 |
| `--dry-run` | 대상만 확인하고 API 호출 생략 |
| `--provider` | AI 제공자 강제 지정 |

```
[INFO] 요약 대상: 5건 (모델=mock:mock-rule-based, 최대 200자)
[INFO] [1/5] ID=7 요약 완료 (181자 → 181자)
[INFO] [2/5] ID=4 요약 완료 (1541자 → 195자)
[INFO] 요약 완료: 5건 성공, 0건 실패, 0건 스킵
```

이미 요약된 뉴스는 기본 스킵, API 실패는 **로깅 후 해당 건만 스킵**하고 전체 작업은 계속됩니다.

### `analyze` — AI 인사이트 분석

```bash
python main.py analyze --date-from 2026-08-01 --date-to 2026-08-18 --category 경제
python main.py analyze --history 5          # 최근 분석 이력만 조회
```

분석 항목 4종: **주요 트렌드 / 핵심 키워드 / 공통점·차이점 / 시사점**.
결과는 `analyses` 테이블에 저장되어 `report` 에서 재사용됩니다.

```
=== AI 인사이트 분석 결과 ===
카테고리: 산업 | 대상: 3건 | 모델: mock-rule-based

[핵심 키워드]
코스피, 시가총액, 반도체, 선물, 을지연습

[주요 트렌드]
- ...
[시사점]
- ...
```

### `report` — 리포트 + 차트

```bash
python main.py report --format md --top 5
python main.py report --date 2026-08-18 --no-charts --no-file
```

포함 내용: 수집 현황 · **품질 지표 5종** · **TOP N 집계 3종** · 감성 분포 · **AI 인사이트** · 차트 경로.
콘솔에 출력하고 동시에 `output/reports/report_<타임스탬프>.md|txt` 로 저장합니다.

품질 지표: 정제 통과율 · 요약 완료율 · 카테고리 결측률 · 발행일 결측률 · 평균 요약 압축률
TOP N: 카테고리 TOP N · 제목 키워드 TOP N · 본문이 긴 기사 TOP N

### `export` — 내보내기

```bash
python main.py export --format csv   --status summarized
python main.py export --format excel --category 경제 --date-from 2026-08-01
python main.py export --format all   --output out/news.csv
```

| 옵션 | 설명 |
|---|---|
| `--format` | `csv` · `jsonl` · `excel` · `all` |
| `--status` | `all`(기본) · `summarized` · `unsummarized` |
| `--category`, `--keyword`, `--date-*`, `--limit` | 필터 |
| `--output` | 저장 경로 (단일 포맷일 때) |

CSV 는 `utf-8-sig` 로 저장해 엑셀에서 한글이 깨지지 않습니다.

### `list` · `show` · `sentiment` (보너스)

```bash
python main.py list --category 경제 --keyword 코스피 --status summarized --page 2 --page-size 10
python main.py show 42 --full
python main.py sentiment --limit 20
```

```
총 7건 | 1/1 페이지 (페이지당 10건)
   ID 발행일         카테고리     요약   감성   제목
    4 2026-08-18  산업        O    긍정  '연일 상승' 삼전닉스, 코스피 내 비중 한때 50%대 회복
```

---

## 5. 데이터 저장 구조

**SQLite** (`data/newsbot.db`) 4개 테이블을 사용합니다. 메모리에만 두는 데이터는 없습니다.

| 테이블 | 역할 |
|---|---|
| `raw_news` | 수집 원본(JSON) + 수집 시각 · 소스 · 수집 방법. **append-only** |
| `clean_news` | 검증·정규화된 분석용 데이터. `url_hash` UNIQUE 로 중복 통제. 요약·감성 결과 포함 |
| `analyses` | AI 인사이트 분석 이력 (트렌드/키워드/비교/시사점) |
| `fetch_runs` | 수집 실행 이력 (성공·실패 건수) |

### raw 와 clean 을 왜 나누는가

| | raw | clean |
|---|---|---|
| 성격 | 수집 시점의 **사실 기록(원장)** | 분석이 신뢰할 수 있는 **정형 데이터** |
| 스키마 | 느슨함(원본 JSON 그대로) | 엄격함(필수 필드·타입·형식 보장) |
| 쓰기 | 추가만(append-only) | 정책에 따라 insert / upsert |
| 이점 | 파싱 규칙이 바뀌어도 **재수집 없이 재처리** 가능, 수집 오류 원인 추적 가능 | 중복·결측·형식 오류가 없어 요약/집계/리포트가 단순해짐 |

정제 규칙을 바꿨다면 `python main.py clean --reprocess` 로 raw 전체를 다시 정제할 수 있습니다.
네트워크 요청은 한 번도 다시 나가지 않습니다 — 이것이 분리 저장의 실질적인 가치입니다.

### 중복 처리 정책

중복 판정 키는 **정규화된 URL 의 SHA-1 해시**입니다(추적 파라미터 `?section=`, `utm_*` 등 제거).

- `skip` (기본): 이미 있는 기사는 건너뜁니다. 수집 로그에 중복 건수가 남습니다.
- `upsert`: 제목·본문·카테고리를 최신 내용으로 갱신합니다.
  **본문이 실제로 바뀐 경우에만** 기존 요약·감성 결과를 초기화해, 불필요한 AI 재호출을 막습니다.

RSS 와 크롤링을 동시에 돌리면 같은 기사가 양쪽에서 들어오는데, 이때 중복 정책이 실제로 동작합니다
(예: raw 12건 → clean 7건, 중복 5건 skip).

---

## 6. 학습 정리 (과제 목표)

> 실측 수치·실험 근거·개선 과정 전체 → [EXPERIMENT.md](EXPERIMENT.md)

### 6-1. API/RSS 방식 vs 크롤링 방식

| | RSS / 공개 API | 크롤링 |
|---|---|---|
| 데이터 형태 | 발행처가 제공하는 **구조화된 XML/JSON** | 사람이 보는 **HTML** |
| 안정성 | 높음. 스키마가 계약처럼 유지됨 | 낮음. 사이트 개편 한 번에 파서가 깨짐 |
| 요청 수 | 1회 요청에 수십 건 메타데이터 | 목록 1회 + 기사마다 1회 |
| 얻는 정보 | 제목·링크·발행일·요약 등 **제한적** (본문 전문 없음) | 본문 전문·기자명·상세 메타까지 **자유롭게** |
| 정책 부담 | 낮음(제공 목적이 배포) | robots.txt·이용약관·요청량 제한 준수 필요 |
| 속도 | 빠름 | 느림(지연을 넣어야 하므로 더 느림) |

이 프로젝트는 **둘을 결합**했습니다. RSS 로 목록·메타데이터를 싸게 확보하고
(`newsbot/collectors/rss.py`), 본문이 필요한 경우에만 기사 페이지를 추가로 파싱합니다.
`crawler.py` 는 RSS 없이 목록 페이지부터 크롤링하는 독립 경로입니다.

### 6-2. 외부 API 오류 처리

모든 HTTP 요청은 [`collectors/http_client.py`](newsbot/collectors/http_client.py) 한 곳을 지납니다.

- **타임아웃**: 모든 요청에 `timeout` 을 겁니다. 없으면 스레드가 무한 대기합니다.
- **분류된 재시도**: 타임아웃 · 연결 오류 · `429` · `5xx` 는 **지수 백오프**(1.5s → 3s → 6s)로 재시도하고,
  `404` 같은 `4xx` 는 재시도해도 소용없으므로 즉시 실패시킵니다.
- **실패 격리**: 기사 1건의 실패가 배치 전체를 중단시키지 않습니다. `FetchError` 로 감싸
  로그를 남기고 다음 항목으로 넘어가며, 최종 집계에 성공/실패 건수를 보고합니다.
- AI API 도 같은 구조입니다([`ai/client.py`](newsbot/ai/client.py)) — 재시도 후에도 실패하면
  `AIError` 를 던지고 호출부가 "로깅 후 스킵" 합니다.

### 6-3. raw / clean 분리
→ 5장 참조.

### 6-4. AI API 호출 흐름

```
대상 선택(SQL)  →  프롬프트 구성(system + user)  →  HTTP POST  →  응답 텍스트 추출
      →  후처리(머리말 제거 / JSON 파싱)  →  DB 저장  →  진행 로그
```

- 요약은 자연어 텍스트를 그대로 받고([`summarizer.py`](newsbot/ai/summarizer.py)),
  분석·감성은 **JSON 스키마를 지정해** 받은 뒤 `extract_json()` 으로 관대하게 파싱합니다
  (코드펜스나 앞뒤 설명이 섞여도 복구).
- 제공자별 차이(Gemini `contents`/`systemInstruction`, OpenAI `messages`, Anthropic `x-api-key`)는
  `AIClient` 안에 격리되어 있어, 호출부는 `client.complete(prompt, system=...)` 하나만 압니다.
- 분석은 기사 N건을 **한 번의 요청**으로 묶어 보냅니다. 건별 호출보다 비용·시간이 크게 절약되고,
  "공통점/차이점" 같은 항목은 전체를 함께 봐야 나옵니다.

### 6-5. 집계와 matplotlib 시각화

집계는 SQL 에서(`GROUP BY`), 그리기는 [`visualize.py`](newsbot/visualize.py) 에서 합니다.

| 차트 | 형태 | 이유 |
|---|---|---|
| 카테고리별 뉴스 수 | 가로 막대 | 항목명이 한글이라 세로 막대는 라벨이 겹침 |
| 일자별 수집 추이 | 꺾은선(하루뿐이면 막대) | 시간에 따른 변화 |
| 감성 분포 | 도넛 | 전체 대비 구성비 |

- **한글 폰트**: `matplotlib.font_manager` 로 설치된 폰트를 조회해
  `chart.font_candidates`(맑은 고딕 → 나눔고딕 → Noto Sans KR …) 중 첫 번째 것을 적용하고,
  `axes.unicode_minus = False` 로 마이너스 기호 깨짐을 막습니다. 못 찾으면 경고를 남깁니다.
- **`Agg` 백엔드**를 강제해 GUI 없는 서버·스케줄러 환경에서도 PNG 로만 저장됩니다.
- 격자·축은 흐리게 두고 값은 막대 끝과 최고점에만 직접 표기해, 색에만 의존하지 않게 했습니다.
  감성 색은 색각 이상에서도 구분되도록 파랑(긍정)↔회색(중립)↔주황(부정) 발산형을 씁니다.

---

## 7. 정기 실행 스케줄링 (보너스)

수집 → 정제 → 요약을 매일 자동 실행하는 방법입니다.

### 7-1. Windows 작업 스케줄러

먼저 배치 파일 `run_daily.bat` 을 만듭니다.

```bat
@echo off
cd /d "C:\Users\User\Desktop\연구실\5_코디세이\a1\a2-2"
py main.py fetch --category 경제,산업,정치 --limit 30 --auto-clean
py main.py summarize --unsummarized --limit 30
py main.py analyze --date %date:~0,4%-%date:~5,2%-%date:~8,2%
py main.py report --format md
```

등록 (관리자 PowerShell):

```powershell
schtasks /create /tn "NewsBot 일일수집" /tr "C:\...\a2-2\run_daily.bat" /sc daily /st 07:00
schtasks /run   /tn "NewsBot 일일수집"     # 즉시 테스트
schtasks /query /tn "NewsBot 일일수집"     # 상태 확인
schtasks /delete /tn "NewsBot 일일수집" /f # 삭제
```

GUI 로 등록하려면: `taskschd.msc` → 작업 만들기 → 트리거(매일 07:00) →
동작(프로그램 시작 = 배치 파일 경로) → 조건에서 "AC 전원일 때만 실행" 해제.

### 7-2. Linux / macOS cron

```bash
crontab -e
```

```cron
# 매일 07:00 수집 + 정제 + 요약
0 7 * * * cd /home/user/newsbot && /usr/bin/python3 main.py fetch --limit 30 --auto-clean >> logs/cron.log 2>&1
5 7 * * * cd /home/user/newsbot && /usr/bin/python3 main.py summarize --unsummarized --limit 30 >> logs/cron.log 2>&1

# 매주 월요일 08:00 주간 분석 + 리포트
0 8 * * 1 cd /home/user/newsbot && /usr/bin/python3 main.py analyze --date-from $(date -d '7 days ago' +\%Y-\%m-\%d) >> logs/cron.log 2>&1
10 8 * * 1 cd /home/user/newsbot && /usr/bin/python3 main.py report --format md >> logs/cron.log 2>&1
```

cron 주의사항:
- cron 은 로그인 셸이 아니라 **환경변수를 상속하지 않습니다.** `.env` 파일을 쓰거나
  crontab 상단에 `GEMINI_API_KEY=...` 를 직접 선언하세요.
- `python3` 는 **절대 경로**로 지정합니다(`which python3` 로 확인).
- `%` 는 cron 에서 특수문자이므로 `\%` 로 이스케이프합니다.
- 명령마다 몇 분씩 간격을 두면 API 요청이 한꺼번에 몰리지 않습니다.

### 7-3. systemd timer (서버 권장)

```ini
# /etc/systemd/system/newsbot.service
[Service]
Type=oneshot
WorkingDirectory=/home/user/newsbot
EnvironmentFile=/home/user/newsbot/.env
ExecStart=/usr/bin/python3 main.py fetch --limit 30 --auto-clean
ExecStart=/usr/bin/python3 main.py summarize --unsummarized --limit 30
```
```ini
# /etc/systemd/system/newsbot.timer
[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```
```bash
sudo systemctl enable --now newsbot.timer
```

`Persistent=true` 덕분에 서버가 꺼져 있던 시간대의 실행도 부팅 후 한 번 보충됩니다.

---

## 8. 크롤링 정책 준수

- **robots.txt 확인**: 요청 전 `robots.txt` 를 파싱해 허용된 경로만 가져옵니다
  (`http.respect_robots`). 차단된 URL 은 건너뛰고 경고 로그를 남깁니다.
- **요청 간 지연**: 도메인 단위로 최소 간격(`http.request_delay_sec`, 기본 1초)을 강제합니다.
  동시 요청은 하지 않고 순차 처리합니다.
- **요청량 제한**: `--limit` 로 상한을 두고, 목록은 1페이지만 읽습니다.
- **식별 가능한 User-Agent**: `http.user_agent` 에 프로젝트 성격을 밝힙니다.
- 재배포·상업적 이용은 하지 않으며, 원문 URL 을 항상 함께 저장해 출처를 유지합니다.
- 대상 사이트의 이용약관이 바뀌면 `config.json` 의 소스 설정만 교체하면 됩니다.

---

## 9. 트러블슈팅

> 상세 원인 분석 및 올바른 사용법 → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

| 증상 | 원인 / 해결 |
|---|---|
| `설정 파일을 찾을 수 없습니다` | `cp config.example.json config.json` |
| `AI API 키가 없어 mock 모드로 동작합니다` | 정상 동작입니다. 실제 LLM 을 쓰려면 `.env` 또는 환경변수에 키를 넣으세요 |
| 차트의 한글이 □ 로 보임 | 한글 폰트 미설치. 나눔고딕 설치 후 `chart.font_candidates` 에 이름 추가 |
| `요청 실패(3회 시도)` | 네트워크/사이트 문제. `--log-level DEBUG` 로 상세 확인, `http.timeout` 상향 |
| 수집은 되는데 clean 이 0건 | 본문 파싱 실패 가능성. `logs/newsbot.log` 의 폐기 사유 확인 후 `sources.*.article_selectors` 조정 |
| Excel 내보내기 실패 | `pip install pandas openpyxl` |
| Windows 에서 `python` 이 아무것도 출력하지 않음 | Microsoft Store 스텁입니다. `py` 를 쓰거나 python.org 버전을 PATH 앞에 두세요 |

로그는 콘솔과 `logs/newsbot.log` 양쪽에 남습니다. 파일에는 시각·모듈·레벨이 포함된 상세 포맷으로 기록됩니다.

---

## 10. 요구사항 대응표

| 요구사항 | 구현 위치 |
|---|---|
| argparse 서브커맨드 (fetch/clean/summarize/analyze/report/export) | `newsbot/cli.py` |
| 방법 1 — RSS/API 수집 | `newsbot/collectors/rss.py` |
| 방법 2 — 크롤링 (BeautifulSoup) | `newsbot/collectors/crawler.py`, `article.py` |
| 타임아웃 · 오류 처리 · 재시도 | `newsbot/collectors/http_client.py` |
| raw 저장 (수집 시각/소스/방법 포함) | `newsbot/storage.py` (`raw_news`) |
| 정제 4규칙 (검증·정규화·날짜 통일·결측 처리) | `newsbot/cleaner.py` |
| 중복 정책 skip / upsert | `newsbot/cleaner.py`, `storage.upsert_clean()` |
| clean 별도 저장 | `newsbot/storage.py` (`clean_news`) |
| AI 요약 + `--all/--id/--unsummarized` | `newsbot/ai/summarizer.py`, `cli.py` |
| 실패 시 로깅 후 스킵 · 기본 스킵 | `summarizer.run()` |
| AI 인사이트 분석 4항목 · 결과 저장 | `newsbot/ai/analyzer.py`, `analyses` 테이블 |
| matplotlib 차트 2종 이상 · 한글 폰트 · PNG | `newsbot/visualize.py` |
| 품질 지표 5종 · TOP N 3종 · 인사이트 포함 리포트 | `newsbot/report.py` |
| 콘솔 출력 + TXT/MD 저장 | `report.py`, `cli.cmd_report()` |
| CSV / JSONL / Excel 내보내기 · `--status` 필터 | `newsbot/exporter.py` |
| config.json 설정 관리 · API 키 환경변수 | `config.json`, `newsbot/config.py` |
| logging INFO/WARNING/ERROR | `newsbot/logger.py` (전 모듈에서 사용) |
| SQLite 영구 저장 | `newsbot/storage.py` |
| 4개 이상 모듈 분리 | `newsbot/` 하위 13개 모듈 |
| **보너스** list / show + 필터 + 페이지네이션 | `cli.cmd_list()`, `cli.cmd_show()` |
| **보너스** 감성 분석 + 시각화 | `newsbot/ai/sentiment.py`, `visualize.chart_sentiment()` |
| **보너스** 정기 실행 스케줄링 문서화 | README 7장 |
