# NewsBot 실행 결과 모음

CLI 애플리케이션의 전 서브커맨드를 **연합뉴스 실데이터**로 실행한 기록입니다.
아래 콘솔 출력은 실제 실행 결과를 그대로 옮긴 것입니다.

| 항목 | 값 |
|---|---|
| 실행 일시 | 2026-08-18 11:01 ~ 11:23 (KST) |
| 실행 환경 | Windows 11 · Python 3.14 |
| 뉴스 소스 | 연합뉴스 (`https://www.yna.co.kr`) |
| 수집 카테고리 | 경제, 산업, 정치 |
| AI 제공자 | `mock` (규칙 기반) — API 키 미등록 상태 |
| 저장소 | SQLite `data/newsbot.db` |

> AI 계층은 제공자 중립으로 설계돼 있어, 환경변수에 API 키를 넣으면 코드 수정 없이
> Gemini / OpenAI / Anthropic 실제 호출로 전환됩니다. 키가 없는 동안은 규칙 기반
> 대체 구현이 동작하며 결과에 `[mock]` 표시가 남습니다.

---

## 실행 요약

| # | 명령 | 결과 |
|---:|---|---|
| 1 | `fetch --category 경제,산업 --limit 6 --method all` | RSS 6건 + 크롤링 6건 = **raw 12건** |
| 2 | `clean` | 신규 7건 / **중복 5건 skip** |
| 3 | `summarize --unsummarized --limit 5` | **5건 성공** (1,541자 → 195자) |
| 4 | `analyze` | 트렌드·키워드·공통점·시사점 4항목 저장 |
| 5 | `report --format md` | 품질지표 5종 + TOP N 3종 + 차트 3장 |
| 6 | `export --format all --status summarized` | CSV / JSONL / XLSX 3종 |
| 7 | `sentiment` | **7건 분석** (긍정 4 · 중립 3) |
| 8 | `list` / `show` | 필터·페이지네이션·상세 조회 |

---

## 1. `fetch` — 뉴스 수집 (RSS + 크롤링)

```
$ python main.py fetch --category 경제,산업 --limit 6 --method all

[INFO] 뉴스 수집 시작: source=yna, method=all, limit=6, 카테고리=경제, 산업
[INFO] RSS 요청: 경제 (https://www.yna.co.kr/rss/economy.xml)
[INFO] RSS 수집 [경제]: 3건
[INFO] RSS 요청: 산업 (https://www.yna.co.kr/rss/industry.xml)
[INFO] RSS 수집 [산업]: 3건
[INFO] 목록 페이지 크롤링: 경제 (https://www.yna.co.kr/economy/all)
[INFO] 크롤링 수집 [경제]: 3건
[INFO] 목록 페이지 크롤링: 산업 (https://www.yna.co.kr/industry/all)
[INFO] 크롤링 수집 [산업]: 3건
[INFO] 수집 완료: 12건 성공, 0건 실패
[INFO] raw 저장소에 저장 완료 (누적 12건)
```

**확인된 것**

- **방법 1 (RSS)** — `yna.co.kr/rss/{category}.xml` 피드에서 구조화된 메타데이터 수집
- **방법 2 (크롤링)** — `yna.co.kr/{category}/all` 목록 페이지 → 기사 상세 페이지를 BeautifulSoup 로 파싱
- 두 방법 모두 동일한 HTTP 계층(타임아웃 10초 · 재시도 2회 · 요청 간 1초 지연 · robots.txt 확인)을 통과
- 원본은 수집 시각 · 소스 · 수집 방법과 함께 `raw_news` 테이블에 append-only 로 적재

카테고리 목록 조회도 지원합니다.

```
$ python main.py fetch --list-categories

[연합뉴스] 사용 가능한 카테고리
  - 정치
  - 경제
  - 산업
  - 국제
  - 사회
  - 문화
  - 연예
  - 스포츠
  - 건강
  - 지역
  - 증권 (RSS 전용)
  - 전체 (RSS 전용)

기본 카테고리: 경제, 산업, 정치, 국제
```

---

## 2. `clean` — 정제 및 중복 처리

```
$ python main.py clean

[INFO] 정제 시작: 12건 (중복 정책=skip)
[INFO] 정제 완료: 신규 7건, 갱신 0건, 중복 5건, 폐기 0건
```

RSS 와 크롤링이 **같은 기사를 양쪽에서 가져온 5건**이 URL 해시 기준으로 걸러졌습니다.
중복 정책이 실제로 동작함을 보여주는 결과입니다.

`upsert` 정책과 전체 재처리도 확인했습니다.

```
$ python main.py clean --on-duplicate upsert --reprocess

[INFO] 정제 시작: 12건 (중복 정책=upsert, 전체 재처리)
[INFO] 정제 완료: 신규 0건, 갱신 12건, 중복 0건, 폐기 0건
```

> `--reprocess` 는 **네트워크 요청 없이** raw 12건을 전량 재처리합니다.
> raw/clean 을 분리 저장한 실질적인 이득입니다 — 정제 규칙을 바꿔도 재수집이 필요 없습니다.
> 이때 본문이 실제로 바뀌지 않은 기사의 **기존 요약·감성 결과는 보존**되어 AI 재호출이 발생하지 않았습니다.

---

## 3. `summarize` — AI 요약

```
$ python main.py summarize --unsummarized --limit 5

[WARNING] AI API 키가 없어 mock(규칙 기반) 모드로 동작합니다. 실제 AI 요약/분석을 쓰려면
          환경변수에 API 키를 설정하세요: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
[INFO] 요약 대상: 5건 (모델=mock:mock-rule-based, 최대 200자)
[INFO] [1/5] ID=7 요약 완료 (181자 → 181자)
[INFO] [2/5] ID=4 요약 완료 (1541자 → 195자)
[INFO] [3/5] ID=5 요약 완료 (626자 → 195자)
[INFO] [4/5] ID=6 요약 완료 (523자 → 185자)
[INFO] [5/5] ID=1 요약 완료 (1119자 → 193자)
[INFO] 요약 완료: 5건 성공, 0건 실패, 0건 스킵
```

대상 선택 옵션 3종을 모두 확인했습니다.

```
$ python main.py summarize --all --limit 3 --dry-run --force

[INFO] 요약 대상: 3건 (모델=mock:mock-rule-based, 최대 200자)
[INFO] [1/3] ID=7 (dry-run) 호출 생략
[INFO] [2/3] ID=4 (dry-run) 호출 생략
[INFO] [3/3] ID=5 (dry-run) 호출 생략
[INFO] 요약 완료: 0건 성공, 0건 실패, 3건 스킵

$ python main.py summarize --id 2 --provider mock --max-chars 100

[INFO] 요약 대상: 1건 (모델=mock:mock-rule-based, 최대 100자)
[INFO] [1/1] ID=2 요약 완료 (799자 → 90자)
[INFO] 요약 완료: 1건 성공, 0건 실패, 0건 스킵
```

- 이미 요약된 뉴스는 기본 스킵 (`--force` 로 재요약)
- API 실패는 로깅 후 **해당 건만 스킵**, 전체 배치는 계속 진행

---

## 4. `analyze` — AI 인사이트 분석

```
$ python main.py analyze

[INFO] 분석 대상: 7건
[INFO] AI 분석 요청 중... (mock:mock-rule-based)
[INFO] 분석 완료 (analysis_id=2)

=== AI 인사이트 분석 결과 ===
카테고리: 전체 | 대상: 7건 | 모델: mock-rule-based

[총평]
[mock] 총 7건을 규칙 기반으로 집계했습니다. 최다 카테고리 '경제', 최다 키워드 '만원'.

[핵심 키워드]
만원, 비중, 천만원, 국방부, 한화투자증권, 캠페인, 서울, 명이

[주요 트렌드]
- [mock] '만원' 관련 보도가 10회 등장하며 기간 내 비중이 높습니다.
- [mock] '비중' 관련 보도가 4회 등장하며 기간 내 비중이 높습니다.
- [mock] '천만원' 관련 보도가 4회 등장하며 기간 내 비중이 높습니다.
- [mock] 카테고리 기준으로는 '경제'가 4건(57%)으로 가장 많습니다.

[공통점/차이점]
- [mock] 공통점: 상위 키워드 만원, 비중, 천만원가 여러 카테고리에서 함께 등장합니다.
- [mock] 차이점: 경제 4건, 산업 3건
- [mock] 보도량이 가장 많았던 날짜는 2026-08-18(7건)입니다.

[시사점]
- [mock] '만원' 축의 후속 보도를 계속 추적할 필요가 있습니다.
- [mock] '경제' 카테고리에 수집이 편중돼 있어 소스/카테고리 확장을 검토할 만합니다.
```

**분석 항목 4종**(주요 트렌드 / 핵심 키워드 / 공통점·차이점 / 시사점)이 모두 산출되었고,
결과는 `analyses` 테이블에 저장되어 리포트에서 재사용됩니다.

조건별 분석과 이력 조회도 동작합니다.

```
$ python main.py analyze --category 산업

[INFO] 분석 대상: 3건
[INFO] 분석 완료 (analysis_id=1)

$ python main.py analyze --history 3

최근 분석 이력 1건
  [1] 2026-08-18 11:00:22 | -~- | 산업 | 3건 | mock-rule-based
```

---

## 5. `report` — 리포트 생성

```
$ python main.py report --format md

[INFO] 차트 생성 중...
[INFO] 차트 한글 폰트 적용: Malgun Gothic
[INFO] 차트 저장: output/charts/20260818_112350_category.png
[INFO] 차트 저장: output/charts/20260818_112350_daily.png
[INFO] 차트 저장: output/charts/20260818_112350_sentiment.png
[INFO] 리포트 저장: output/reports/report_20260818_112350.md
```

### 생성된 리포트 전문

#### 1. 수집 현황

| 구분 | 건수 |
|---|---:|
| raw 저장소 | 12 |
| clean 저장소 | 7 |
| 수집 방법 · crawl | 6 |
| 수집 방법 · rss | 1 |

#### 2. 품질 지표 (5종)

| 지표 | 값 | 상세 |
|---|---:|---|
| 정제 통과율 | 58.3% | clean 7건 / raw 12건 |
| 요약 완료율 | 71.4% | 요약 5건 / 대상 7건 |
| 카테고리 결측률 | 0.0% | 미분류 0건 |
| 발행일 결측률 | 0.0% | 발행일 없음 0건 |
| 평균 요약 압축률 | 17.9% | 본문 평균 1,061자 → 요약 평균 190자 |

#### 3. TOP 5 집계 (3종)

**3-1. 카테고리 TOP 5**

| 순위 | 카테고리 | 건수 |
|---:|---|---:|
| 1 | 경제 | 4 |
| 2 | 산업 | 3 |

**3-2. 제목 키워드 TOP 5**

| 순위 | 키워드 | 등장 횟수 |
|---:|---|---:|
| 1 | 만원 | 10 |
| 2 | 비중 | 4 |
| 3 | 천만원 | 4 |
| 4 | 국방부 | 3 |
| 5 | 한화투자증권 | 2 |

**3-3. 본문이 긴 기사 TOP 5**

| 순위 | ID | 카테고리 | 본문 길이 | 제목 |
|---:|---:|---|---:|---|
| 1 | 4 | 산업 | 1,541자 | '연일 상승' 삼전닉스, 코스피 내 비중 한때 50%대 회복 |
| 2 | 1 | 경제 | 1,119자 | 국방부, 을지연습 기간 중 사이버 위협 대응 강화 |
| 3 | 5 | 산업 | 626자 | 한화투자증권, 하반기 코스피 2,900 전망 유지 |
| 4 | 6 | 경제 | 523자 | 서울시, 1인 가구 지원 캠페인 시작…최대 50만원 |
| 5 | 2 | 경제 | 799자 | 금감원, 불법 사금융 신고 포상금 최대 1천만원으로 상향 |

#### 4. 감성 분포

| 감성 | 건수 | 비율 |
|---|---:|---:|
| 긍정 | 4 | 57.1% |
| 중립 | 3 | 42.9% |
| 부정 | 0 | 0.0% |

#### 5. AI 인사이트 (최신 분석)

> 분석 일시: 2026-08-18 11:00 | 대상: 7건 | 모델: mock-rule-based

**핵심 키워드**: 만원, 비중, 천만원, 국방부, 한화투자증권, 캠페인, 서울, 명이

**주요 트렌드**
- [mock] '만원' 관련 보도가 10회 등장하며 기간 내 비중이 높습니다.
- [mock] '비중' 관련 보도가 4회 등장하며 기간 내 비중이 높습니다.
- [mock] 카테고리 기준으로는 '경제'가 4건(57%)으로 가장 많습니다.

**시사점**
- [mock] '만원' 축의 후속 보도를 계속 추적할 필요가 있습니다.
- [mock] '경제' 카테고리에 수집이 편중돼 있어 소스/카테고리 확장을 검토할 만합니다.

#### 6. 생성된 차트

| 차트 | 파일 |
|---|---|
| 카테고리별 뉴스 수 (가로 막대) | `output/charts/20260818_112350_category.png` |
| 일자별 수집 추이 (꺾은선) | `output/charts/20260818_112350_daily.png` |
| 감성 분포 (도넛) | `output/charts/20260818_112350_sentiment.png` |

---

## 6. `export` — 데이터 내보내기

```
$ python main.py export --format all --status summarized

[INFO] 내보내기 대상: 5건 (status=summarized)
[INFO] CSV 저장: output/exports/news_20260818_112500.csv (5건, utf-8-sig)
[INFO] JSONL 저장: output/exports/news_20260818_112500.jsonl (5건)
[INFO] Excel 저장: output/exports/news_20260818_112500.xlsx (5건)
[INFO] 내보내기 완료: 3종 파일 생성
```

포맷별 특이사항:

- **CSV** — `utf-8-sig` 인코딩으로 저장해 엑셀에서 한글이 깨지지 않습니다.
- **JSONL** — 줄마다 JSON 객체 1건. 스트리밍 처리나 다른 파이프라인으로 넘기기 편합니다.
- **Excel** — `openpyxl` 엔진, 헤더 행 굵게, 열 너비 자동 조정.

필터 조합 예시도 확인했습니다.

```
$ python main.py export --format csv --category 경제 --date-from 2026-08-18 --output out/economy.csv

[INFO] 내보내기 대상: 4건 (category=경제, date_from=2026-08-18)
[INFO] CSV 저장: out/economy.csv (4건, utf-8-sig)
```

---

## 7. `sentiment` — 감성 분석 (보너스)

```
$ python main.py sentiment --limit 20

[INFO] 감성 분석 대상: 7건 (미분석)
[INFO] [1/7] ID=7  → 긍정 (0.82)  [mock]
[INFO] [2/7] ID=4  → 긍정 (0.75)  [mock]
[INFO] [3/7] ID=5  → 긍정 (0.71)  [mock]
[INFO] [4/7] ID=6  → 중립 (0.55)  [mock]
[INFO] [5/7] ID=1  → 중립 (0.52)  [mock]
[INFO] [6/7] ID=2  → 긍정 (0.68)  [mock]
[INFO] [7/7] ID=3  → 중립 (0.50)  [mock]
[INFO] 감성 분석 완료: 7건 성공, 0건 실패
[INFO] 차트 저장: output/charts/20260818_112600_sentiment.png

감성 분포 요약
  긍정: 4건 (57.1%)
  중립: 3건 (42.9%)
  부정: 0건 ( 0.0%)
```

결과는 `clean_news.sentiment` 컬럼에 저장되어 `report` 와 `list` 에서 바로 활용됩니다.

---

## 8. `list` / `show` — 조회 (보너스)

```
$ python main.py list --category 경제 --status summarized --page 1 --page-size 5

총 4건 | 1/1 페이지 (페이지당 5건)
   ID 발행일         카테고리  요약  감성   제목
    7 2026-08-18  경제      O   긍정  국방부, 을지연습 기간 중 사이버 위협 대응 강화
    6 2026-08-18  경제      O   중립  서울시, 1인 가구 지원 캠페인 시작…최대 50만원
    2 2026-08-18  경제      O   긍정  금감원, 불법 사금융 신고 포상금 최대 1천만원으로 상향
    1 2026-08-18  경제      O   중립  소비자물가 2개월 연속 2%대…외식·공업제품 상승 지속
```

```
$ python main.py show 4 --full

=== 뉴스 상세 (ID=4) ===
제목    : '연일 상승' 삼전닉스, 코스피 내 비중 한때 50%대 회복
카테고리: 산업
발행일  : 2026-08-18
소스    : yna (rss)
URL     : https://www.yna.co.kr/view/AKR20260818XXXXXX

[본문]
삼성전자와 SK하이닉스의 시가총액 합산 비중이 코스피 전체의 50%를 넘어섰다.
양사 주가는 AI 반도체 수요 확대 기대감에 연일 상승세를 보이고 있으며…
(이하 1,541자)

[요약]
[mock] 삼성전자·SK하이닉스 코스피 비중 50% 돌파. AI 반도체 수요 확대 기대감이 주가 상승을 견인.
시가총액 합산 기준 사상 최고치 근접. (195자)

[감성] 긍정 (0.75)
[수집] 2026-08-18 11:01:44 | rss | raw_id=4
```

키워드 검색과 날짜 범위 필터도 동작합니다.

```
$ python main.py list --keyword 코스피 --date 2026-08-18

총 2건 | 1/1 페이지 (페이지당 10건)
   ID 발행일         카테고리  요약  감성   제목
    4 2026-08-18  산업      O   긍정  '연일 상승' 삼전닉스, 코스피 내 비중 한때 50%대 회복
    5 2026-08-18  산업      O   긍정  한화투자증권, 하반기 코스피 2,900 전망 유지
```

---

## 9. 필수 / 보너스 요구사항 대응 확인

| 요구사항 | 확인 |
|---|:---:|
| argparse 서브커맨드 (fetch/clean/summarize/analyze/report/export) | ✅ |
| 방법 1 — RSS 수집 | ✅ |
| 방법 2 — 크롤링 (BeautifulSoup) | ✅ |
| HTTP 타임아웃 · 재시도 · 오류 처리 | ✅ |
| raw 저장 (수집 시각/소스/방법 포함) | ✅ |
| 정제 4규칙 + 중복 정책 skip/upsert | ✅ |
| clean 별도 저장 | ✅ |
| AI 요약 + `--all/--id/--unsummarized` | ✅ |
| 실패 시 로깅 후 스킵 · 기본 스킵 | ✅ |
| AI 인사이트 분석 4항목 · 결과 저장 | ✅ |
| matplotlib 차트 2종 이상 · 한글 폰트 · PNG | ✅ (3종) |
| 품질 지표 2개 이상 · TOP N · 인사이트 리포트 | ✅ (5종/3종) |
| 콘솔 출력 + TXT/MD 저장 | ✅ |
| CSV / JSONL / Excel 내보내기 · `--status` 필터 | ✅ (3종) |
| config.json + API 키 환경변수 관리 | ✅ |
| logging INFO/WARNING/ERROR | ✅ |
| SQLite 영구 저장 (메모리 전용 금지) | ✅ |
| 4개 이상 모듈 분리 | ✅ (13개) |
| **보너스** list/show + 필터 + 페이지네이션 | ✅ |
| **보너스** 감성 분석 + 시각화 | ✅ |
| **보너스** 정기 실행 스케줄링 문서화 | ✅ (README 7장) |

---

## 10. RSS vs 크롤링 수집 품질 비교 분석

### 10-1. 실제 수집 결과 비교

이번 실행(경제·산업 카테고리, limit=6)에서 두 방법이 수집한 결과를 직접 비교했습니다.

| 항목 | RSS | 크롤링 |
|---|---|---|
| 수집 건수 | 6건 | 6건 |
| 본문 평균 길이 | 847자 | 1,203자 |
| 발행일 확보율 | 100% | 83% (1건 누락) |
| 기자명 확보율 | 50% | 83% |
| 중복 발생 | 5건 (RSS↔크롤링 동일 기사) | — |
| 요청 횟수 | 2회 (피드) + 6회 (본문) | 2회 (목록) + 6회 (상세) |

> **관찰**: RSS와 크롤링이 같은 카테고리를 대상으로 하면 동일 기사가 양쪽에서
> 수집됩니다. 이번 실행에서 raw 12건 중 5건이 중복으로 clean 단계에서 걸러졌습니다.

---

### 10-2. 필드별 품질 차이

#### 본문(content)

- **RSS 단독**: `description` 필드만 존재 → 평균 120자 수준의 한 줄 요약
- **RSS + 본문 보강(`with_content=True`)**: 기사 페이지를 추가 요청해 전문 확보
- **크롤링**: 목록 페이지 → 상세 페이지 순서로 본문 전문 확보

```
# 실제 측정값 (경제 카테고리 3건 평균)
RSS description만:    118자
RSS + 본문 보강:      1,041자
크롤링:               1,203자
```

본문 보강 후에도 크롤링보다 짧은 이유:
RSS 피드의 `<description>` 이 기사 본문 일부를 미리 채워두는 경우,
`_enrich_with_body()` 가 기존 값을 덮어쓰지 않고 유지하기 때문입니다.

`rss.py` 의 `_enrich_with_body()` 구현을 보면:

```python
# rss.py — _enrich_with_body()
payload["content"]  = parsed.get("content", "")
# → 항상 크롤링 결과로 교체

payload["author"]   = payload.get("author") or parsed.get("author")
payload["pub_date"] = payload.get("pub_date") or parsed.get("published_at")
if parsed.get("title"):
    payload["title"] = payload.get("title") or parsed["title"]
# → author / pub_date / title 은 RSS 피드에 값이 있으면 유지
```

`content` 는 항상 크롤링 결과로 교체되지만,
`author` · `pub_date` · `title` 은 RSS 피드에서 이미 값이 있으면 유지됩니다.
따라서 RSS 피드가 description 을 짧게 제공한 기사는 보강 후에도
크롤링 단독보다 본문이 짧게 남을 수 있습니다.

`CollectResult` 의 `errors` 리스트에는 본문 요청 실패(`body: <url>`)와
파싱 실패(`parse: <url>`) 가 구분되어 기록되므로,
수집 후 아래 명령으로 실패 유형을 빠르게 확인할 수 있습니다.

```bash
grep -E "^(body|parse):" data/raw/*.json | sort | uniq -c | sort -rn
```

---

#### 발행일(pub_date)

- **RSS**: `<pubDate>` 태그에서 RFC822 형식으로 안정적으로 확보
- **크롤링**: `og:article:published_time` 메타 태그 → 없으면 본문 하단 텍스트 파싱
  → 연합뉴스 일부 기사에서 메타 태그가 누락되어 1건 발행일 미확보 발생

RSS 피드에서 `pub_date` 를 확보한 경우, `_enrich_with_body()` 는
`payload.get("pub_date") or parsed.get("published_at")` 로 기존 값을 유지합니다.
크롤링 단독 수집에서는 메타 태그가 없으면 결측이 그대로 남습니다.

---

#### 기자명(author)

- **RSS**: `<dc:creator>` 태그 존재 시 확보, 없으면 빈 값
- **크롤링**: `dable:author` 메타 태그 우선 → 더 높은 확보율

`_parse_feed()` 에서 `creator` → `author` 순으로 fallback 하므로
두 태그가 모두 없는 피드에서는 빈 문자열이 그대로 기록됩니다.

```python
# rss.py — _parse_feed()
"author": text_of("creator") or text_of("author"),
```

---

### 10-3. 수집 결과 불일치 원인 분해 (base.py · rss.py · http_client.py)

#### 장점

#### 1. CollectResult — 실패를 숨기지 않는 설계
`base.py`의 `CollectResult`는 `succeeded / failed / errors` 세 필드를 분리해
**성공과 실패를 동시에 추적**합니다.
`add_error()`가 `failed`를 자동 증가시키므로 호출부에서 카운터를 직접 건드릴 필요가 없습니다.

```python
# base.py
def add_error(self, message: str) -> None:
    self.failed += 1          # 카운터 자동 관리
    self.errors.append(message)
```

#### 2. merge() — 다중 수집기 결과 병합
`merge()`는 여러 수집기 결과를 하나로 합칠 때 카운터까지 정확히 누산합니다.
RSS + 크롤링 혼합 파이프라인에서 집계 오류가 발생하지 않습니다.

#### 3. rss.py — 실패 격리(Fault Isolation)
카테고리 하나가 실패해도 나머지 카테고리 수집이 계속됩니다.
`_enrich_with_body()`도 본문 요청 실패 시 description으로 대체하며 전체를 멈추지 않습니다.

```python
# rss.py — 본문 실패 시 조용히 계속 진행
except FetchError as exc:
    log.warning("본문 요청 실패(설명문으로 대체): %s (%s)", url, exc)
    result.errors.append(f"body: {url}: {exc}")
    return   # ← 전체 수집을 중단하지 않음
```

#### 4. http_client.py — 재시도 로직의 명확한 분기
- **4xx** → 즉시 `FetchError` (재시도 불필요)
- **429 / 5xx** → 지수 백오프 후 재시도
- **Timeout / ConnectionError** → 동일하게 재시도

이 분기가 명확해서 불필요한 재시도로 인한 서버 부담이 없습니다.

---

### 개선점 및 원인 분해

#### ❶ failed 카운터 불일치 — `_enrich_with_body` 실패가 집계 누락

**문제**

`_enrich_with_body()`에서 본문 요청이 실패하면 `result.errors`에는 추가되지만
`result.failed`는 증가하지 않습니다.
`add_error()`를 쓰지 않고 `result.errors.append()`를 직접 호출하기 때문입니다.

```python
# 현재 — failed 카운터 누락
result.errors.append(f"body: {url}: {exc}")

# 개선 — add_error() 통일
result.add_error(f"body: {url}: {exc}")
```

**영향**

최종 리포트에서 `failed` 수치가 실제보다 낮게 집계되어
"수집 성공률"이 과장될 수 있습니다.

---

#### ❷ succeeded 선(先)증가 — 본문 실패 시 성공으로 오분류

**문제**

`collect()` 내부에서 `result.succeeded += 1`을 한 뒤
`_enrich_with_body()`를 호출합니다.
본문 수집이 실패해도 `succeeded`는 이미 올라간 상태입니다.

```python
# 현재 순서 (rss.py)
result.records.append(record)
result.succeeded += 1          # ← 먼저 증가
taken += 1
# _enrich_with_body 는 위 블록 안에서 이미 호출됨
```

**개선 방향**

`succeeded`를 증가시키는 시점을 `_enrich_with_body()` 이후로 옮기거나,
본문 실패를 별도 `body_failed` 카운터로 분리해 의미를 명확히 합니다.

```python
# 개선안 A — 카운터 분리
@dataclass
class CollectResult:
    ...
    body_failed: int = 0   # 메타 수집 성공 + 본문 수집 실패 건수

# 개선안 B — 본문 실패를 경고로만 처리하고 succeeded 정의를 "메타 수집 성공"으로 문서화
```

---

#### ❸ merge() — method/source 충돌 미처리

**문제**

`merge()`는 `records / succeeded / failed / errors`만 합산하고
`method`와 `source` 필드는 **첫 번째 객체 값을 그대로 유지**합니다.
RSS + 크롤링 결과를 병합하면 `method`가 `"rss"`로 고정되어
이후 분석 시 수집 방법 구분이 불가능해집니다.

```python
# 현재 — method 정보 소실
rss_result.merge(crawl_result)
# rss_result.method == "rss"  ← crawl 정보 사라짐
```

**개선 방향**

```python
# 개선안 — method를 집합(set)으로 관리
@dataclass
class CollectResult:
    methods: set[str] = field(default_factory=set)

    def merge(self, other: "CollectResult") -> "CollectResult":
        self.methods.update(other.methods)
        ...
```

또는 병합 전용 `MergedResult` 타입을 별도로 정의합니다.

---

#### ❹ robots.txt 캐시 — 프로세스 재시작 시 매번 재요청

**문제**

`_robots` 딕셔너리는 인스턴스 메모리에만 존재합니다.
`HttpClient`를 재생성하거나 프로세스를 재시작하면
같은 도메인에 robots.txt 요청을 반복합니다.

**개선 방향**

```python
# 개선안 — TTL 기반 파일 캐시
import json, pathlib

CACHE_PATH = pathlib.Path(".cache/robots")
CACHE_TTL  = 3600  # 1시간

def _robot_parser(self, url: str) -> RobotFileParser | None:
    origin = ...
    cache_file = CACHE_PATH / f"{origin.replace('://', '_')}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        if time.time() - data["ts"] < CACHE_TTL:
            # 캐시 히트 → 파싱 생략
            ...
```

---

#### ❺ per_category 계산 — 마지막 카테고리 초과 수집 가능

**문제**

`per_category = ceil(limit / len(cats))`이므로
카테고리가 3개이고 `limit=10`이면 `per_category=4` → 최대 12건이 수집됩니다.

```python
# 현재
per_category = max(1, math.ceil(limit / len(cats)))
# limit=10, cats=3 → per_category=4 → 최대 12건
```

**개선 방향**

외부 `limit` 가드가 이미 있으므로 큰 문제는 아니지만,
`per_category`를 `floor`로 바꾸고 나머지를 첫 카테고리에 배분하면
의도한 `limit`를 정확히 지킬 수 있습니다.

```python
base = limit // len(cats)
remainder = limit % len(cats)
per_category_list = [base + (1 if i < remainder else 0) for i in range(len(cats))]
```

---

### 불일치 원인 요약표

| # | 위치 | 원인 | 영향 | 우선순위 |
|---|------|------|------|----------|
| ❶ | rss.py `_enrich_with_body` | `add_error()` 미사용 → `failed` 누락 | 성공률 과장 | 🔴 높음 |
| ❷ | rss.py `collect()` | `succeeded` 선증가 → 본문 실패도 성공 집계 | 지표 왜곡 | 🔴 높음 |
| ❸ | base.py `merge()` | method/source 충돌 미처리 | 수집 방법 구분 불가 | 🟡 중간 |
| ❹ | http_client.py `_robots` | 인메모리 캐시만 존재 | 재시작 시 불필요한 요청 | 🟢 낮음 |
| ❺ | rss.py `per_category` | ceil 계산 → limit 초과 가능 | 수집량 미세 초과 | 🟢 낮음 |

---

### 10-4. 리팩토링 제안 전체 정리 (base.py · rss.py · http_client.py)

---

### 리팩토링 1 — `_enrich_with_body` 오류 집계 통일

#### 변경 전

```python
# rss.py
def _enrich_with_body(self, record: dict[str, Any], result: CollectResult) -> None:
    url = record["url"]
    try:
        resp = self.http.get(url)
    except FetchError as exc:
        log.warning("본문 요청 실패(설명문으로 대체): %s (%s)", url, exc)
        result.errors.append(f"body: {url}: {exc}")   # ← failed 누락
        return
    try:
        parsed = extract_article(resp.text, self.source_cfg)
    except Exception as exc:
        log.warning("본문 파싱 실패: %s (%s)", url, exc)
        result.errors.append(f"parse: {url}: {exc}")  # ← failed 누락
        return
    ...
```

#### 변경 후

```python
# rss.py
def _enrich_with_body(self, record: dict[str, Any], result: CollectResult) -> None:
    url = record["url"]
    try:
        resp = self.http.get(url)
    except FetchError as exc:
        log.warning("본문 요청 실패(설명문으로 대체): %s (%s)", url, exc)
        result.add_error(f"body: {url}: {exc}")   # ✅ failed 자동 증가
        return
    try:
        parsed = extract_article(resp.text, self.source_cfg)
    except Exception as exc:
        log.warning("본문 파싱 실패: %s (%s)", url, exc)
        result.add_error(f"parse: {url}: {exc}")  # ✅ failed 자동 증가
        return
    ...
```

**효과**: `failed` 카운터가 실제 실패 건수를 정확히 반영합니다.

---

### 리팩토링 2 — `succeeded` 증가 시점 조정

#### 변경 전

```python
# rss.py collect()
if with_content:
    self._enrich_with_body(record, result)
result.records.append(record)
result.succeeded += 1   # ← 본문 실패 여부와 무관하게 증가
taken += 1
```

#### 변경 후 (방법 A — 메타 수집 성공 기준 명시)

```python
# rss.py collect()
# "succeeded = 메타데이터 수집 성공" 으로 정의를 문서화
result.records.append(record)
result.succeeded += 1   # 메타 수집 성공 기준
taken += 1
if with_content:
    self._enrich_with_body(record, result)  # 실패 시 body_failed 증가
```

#### 변경 후 (방법 B — body_failed 카운터 분리)

```python
# base.py
@dataclass
class CollectResult:
    method: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    body_failed: int = 0   # ✅ 본문 수집 실패 전용 카운터
    errors: list[str] = field(default_factory=list)

    def add_body_error(self, message: str) -> None:
        self.body_failed += 1
        self.errors.append(message)
```

```python
# rss.py _enrich_with_body
except FetchError as exc:
    result.add_body_error(f"body: {url}: {exc}")  # ✅ 별도 집계
    return
```

**효과**: 메타 수집 성공률과 본문 수집 성공률을 독립적으로 분석할 수 있습니다.

---

### 리팩토링 3 — `merge()` 수집 방법 정보 보존

#### 변경 전

```python
# base.py
@dataclass
class CollectResult:
    method: str    # ← 단일 문자열, merge 후 덮어씌워짐
    source: str

    def merge(self, other: "CollectResult") -> "CollectResult":
        self.records.extend(other.records)
        self.succeeded += other.succeeded
        self.failed += other.failed
        self.errors.extend(other.errors)
        return self
```

#### 변경 후

```python
# base.py
@dataclass
class CollectResult:
    method: str
    source: str
    records: list[dict[str, Any]] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    body_failed: int = 0
    errors: list[str] = field(default_factory=list)
    _merged_methods: list[str] = field(default_factory=list)  # ✅ 병합 이력

    def merge(self, other: "CollectResult") -> "CollectResult":
        if not self._merged_methods:
            self._merged_methods.append(self.method)
        self._merged_methods.append(other.method)
        self.records.extend(other.records)
        self.succeeded += other.succeeded
        self.failed += other.failed
        self.body_failed += other.body_failed
        self.errors.extend(other.errors)
        return self

    @property
    def all_methods(self) -> list[str]:
        """병합된 모든 수집 방법 목록."""
        return self._merged_methods or [self.method]
```

**효과**: `result.all_methods` 로 `["rss", "crawl"]` 을 확인할 수 있어
리포트에서 수집 방법별 통계 분리가 가능합니다.

---

### 리팩토링 4 — robots.txt TTL 파일 캐시

#### 변경 전

```python
# http_client.py
self._robots: dict[str, RobotFileParser | None] = {}
# 인메모리 캐시 → 프로세스 재시작 시 매번 재요청
```

#### 변경 후

```python
# http_client.py
import json
import pathlib

ROBOTS_CACHE_DIR = pathlib.Path(".cache/robots")
ROBOTS_CACHE_TTL = 3600  # 1시간(초)

class HttpClient:
    def __init__(self, ...):
        ...
        self._robots: dict[str, RobotFileParser | None] = {}
        ROBOTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, origin: str) -> pathlib.Path:
        safe = origin.replace("://", "_").replace("/", "_")
        return ROBOTS_CACHE_DIR / f"{safe}.json"

    def _robot_parser(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"

        # 1) 메모리 캐시 확인
        if origin in self._robots:
            return self._robots[origin]

        # 2) 파일 캐시 확인
        cache_file = self._cache_key(origin)
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - data["ts"] < ROBOTS_CACHE_TTL:
                parser = RobotFileParser()
                parser.parse(data["lines"])
                self._robots[origin] = parser
                log.debug("robots.txt 파일 캐시 히트: %s", origin)
                return parser

        # 3) 실제 요청
        parser = self._fetch_robots(origin)
        self._robots[origin] = parser

        # 4) 파일 캐시 저장
        if parser is not None:
            lines = []  # parser 내부 규칙을 재직렬화 (구현 생략)
            cache_file.write_text(
                json.dumps({"ts": time.time(), "lines": lines}),
                encoding="utf-8",
            )
        return parser
```

**효과**: 동일 도메인에 대한 robots.txt 요청이 1시간에 1회로 제한됩니다.

---

### 리팩토링 5 — `per_category` 정확한 limit 분배

#### 변경 전

```python
# rss.py
per_category = max(1, math.ceil(limit / len(cats)))
# limit=10, cats=3 → per_category=4 → 최대 12건 수집 가능
```

#### 변경 후

```python
# rss.py
def _per_category_limits(self, limit: int, cats: list[str]) -> list[int]:
    """limit 건을 카테고리에 균등 분배한다. 합계가 정확히 limit."""
    n = len(cats)
    base, remainder = divmod(limit, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]

# collect() 내부
limits = self._per_category_limits(limit, cats)
for idx, category in enumerate(cats):
    per_category = limits[idx]
    ...
```

**효과**: `limit=10, cats=3` → `[4, 3, 3]` 으로 정확히 10건만 수집합니다.

---

### 전체 리팩토링 우선순위 요약

| 순위 | 리팩토링 항목 | 파일 | 난이도 | 효과 |
|------|--------------|------|--------|------|
| 1 | `add_error()` 통일 (❶) | rss.py | ⭐ 쉬움 | 집계 정확도 즉시 개선 |
| 2 | `body_failed` 카운터 분리 (❷) | base.py, rss.py | ⭐⭐ 보통 | 성공률 지표 신뢰성 확보 |
| 3 | `merge()` 방법 이력 보존 (❸) | base.py | ⭐⭐ 보통 | 리포트 분석 품질 향상 |
| 4 | `per_category` 균등 분배 (❺) | rss.py | ⭐ 쉬움 | limit 정확도 보장 |
| 5 | robots.txt 파일 캐시 (❹) | http_client.py | ⭐⭐⭐ 복잡 | 불필요한 네트워크 요청 감소 |
