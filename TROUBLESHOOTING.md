# NewsBot 트러블슈팅 & 동작 설명서

> 전문가 피드백 4개 항목에 대한 원인 분석 및 올바른 사용법 안내  
> 코드 변경 없음 — 모든 항목은 설계된 동작이며, 올바른 옵션 사용으로 해결됩니다.

---

## 목차

1. [RSS와 크롤링 중복 수집 현상](#1-rss와-크롤링-중복-수집-현상)
2. [수집 오류 메시지가 불명확할 때](#2-수집-오류-메시지가-불명확할-때)
3. [`--limit` 옵션과 실제 수집 건수 차이](#3---limit-옵션과-실제-수집-건수-차이)
4. [`--auto-clean` 동작 범위](#4---auto-clean-동작-범위)

---

## 1. RSS와 크롤링 중복 수집 현상

### 현상

`fetch --method all` 실행 후 raw 저장소에 같은 기사가 두 번 저장되는 것처럼 보입니다.

```
예시 로그:
raw 저장소에 저장 완료 (누적 14건)   ← 기사 7개인데 14건?
```

### 원인

**① fetch 실행 순서**

`--method all`(기본값) 사용 시 RSS → 크롤링 순으로 순차 실행됩니다.

```python
# cli.py cmd_fetch()
methods = ["rss", "crawl"] if args.method == "all" else [args.method]

for method in methods:          # rss 먼저, crawl 나중
    ...
    storage.insert_raw(record)  # 각각 별도로 raw에 저장
```

**② URL 형태가 달라 중복 감지 불가**

같은 기사라도 RSS와 크롤링에서 가져오는 URL 형태가 다릅니다.

```
RSS 수집 URL  : https://feeds.yna.co.kr/article/AKR20260907...
크롤링 URL    : https://www.yna.co.kr/view/AKR20260907...
```

중복 판정은 `url_hash` 완전 일치 방식이므로, URL이 다르면 별개의 기사로 저장됩니다.

**③ 전체 흐름 요약**

```
fetch --method all 실행
  │
  ├─ [1단계] RSS 수집
  │     └─ feeds.yna.co.kr/... URL로 raw 저장
  │
  └─ [2단계] 크롤링 수집
        └─ www.yna.co.kr/... URL로 raw 저장 (중복 감지 안 됨)

clean 실행
  └─ 같은 기사 두 건 중 본문이 더 긴 크롤링본 채택 → 중복 제거
```

### 결론

> **설계된 정상 동작입니다.**  
> raw 저장소는 의도적으로 중복을 허용하며, `clean` 단계에서 최종 정리됩니다.  
> clean 이후 저장소에는 중복이 없습니다.

### 권장 사용법

```bash
# 수집 후 반드시 clean 실행
python main.py fetch --source yna --method all --limit 20
python main.py clean

# 또는 한 번에 처리
python main.py fetch --source yna --method all --limit 20 --auto-clean
```

---

## 2. 수집 오류 메시지가 불명확할 때

### 현상

수집 실패 시 출력되는 로그가 짧아 원인 파악이 어렵습니다.

```
[ERROR] [rss] 수집 중 오류: Connection timeout
```

### 원인

기본 로그 레벨(`INFO`)에서는 예외 메시지만 출력됩니다.

```python
# cli.py cmd_fetch()
except Exception as exc:
    log.error("[%s] 수집 중 오류: %s", method, exc)
```

스택 트레이스, 실패한 URL, 재시도 횟수 등 상세 정보는 `DEBUG` 레벨에서 확인할 수 있습니다.

### 해결 방법

`--log-level DEBUG` 옵션을 추가하면 상세 로그가 출력됩니다.

```bash
# 상세 로그로 원인 확인
python main.py fetch --source yna --log-level DEBUG

# 로그 파일로 저장하여 확인 (config.json 설정 필요)
python main.py fetch --source yna --log-level DEBUG --config config.json
```

### 로그 레벨별 출력 범위

| 레벨 | 출력 내용 |
|------|-----------|
| `ERROR` | 오류 메시지만 |
| `WARNING` | 오류 + 경고 |
| `INFO` | 오류 + 경고 + 진행 상황 (기본값) |
| `DEBUG` | 전체 상세 로그 (HTTP 요청, 재시도, URL 등) |

### config.json 로그 파일 설정 예시

```json
{
  "logging": {
    "level": "INFO",
    "file": "logs/newsbot.log",
    "console": true,
    "max_bytes": 2000000,
    "backup_count": 3
  }
}
```

---

## 3. `--limit` 옵션과 실제 수집 건수 차이

### 현상

`--limit 20`을 지정했는데 실제 수집 결과가 20건이 아닌 경우가 있습니다.

```bash
python main.py fetch --source yna --limit 20
# → raw 저장소에 40건 저장됨
```

### 원인

`--limit`은 **수집 방법별** 최대 건수입니다.  
`--method all`(기본값) 사용 시 RSS와 크롤링 각각에 `--limit`이 적용됩니다.

```python
# cli.py build_parser()
p.add_argument("--limit", type=int, default=20,
               help="수집 방법별 최대 기사 수 (기본 20)")
#                    ^^^^^^^^
#                    method별 한도

# cli.py cmd_fetch()
methods = ["rss", "crawl"] if args.method == "all" else [args.method]
for method in methods:
    result = collector.collect(categories, args.limit, ...)
    #                                      ^^^^^^^^^^
    #                                      rss에 20, crawl에 20 각각 적용
```

### 수집 건수 계산

| `--method` | `--limit` | 최대 수집 건수 |
|------------|-----------|----------------|
| `rss`      | 20        | 20건           |
| `crawl`    | 20        | 20건           |
| `all`      | 20        | **최대 40건**  |
| `all`      | 10        | **최대 20건**  |

### 권장 사용법

```bash
# RSS만 20건 수집
python main.py fetch --source yna --method rss --limit 20

# 크롤링만 20건 수집
python main.py fetch --source yna --method crawl --limit 20

# RSS + 크롤링 각 10건씩 (총 최대 20건)
python main.py fetch --source yna --method all --limit 10

# 전체 합산 40건이 필요한 경우
python main.py fetch --source yna --method all --limit 20
```

> **참고:** raw에 중복 저장된 기사는 `clean` 단계에서 자동으로 정리됩니다.  
> 최종 clean 저장소의 건수는 raw보다 적을 수 있습니다.

---

## 4. `--auto-clean` 동작 범위

### 현상

`--auto-clean` 사용 시 중복 정책(`--on-duplicate`) 등 세부 옵션이 적용되지 않습니다.

```bash
# 의도: upsert 정책으로 clean 하고 싶었는데 적용 안 됨
python main.py fetch --source yna --auto-clean --on-duplicate upsert
# → --on-duplicate 옵션은 fetch 명령에 없으므로 무시됨
```

### 원인

`--auto-clean`은 `clean` 명령을 **config.json 기본 설정값**으로 실행합니다.  
`clean` 명령의 세부 옵션(`--on-duplicate`, `--reprocess`, `--limit`)은 전달되지 않습니다.

```python
# cli.py cmd_fetch()
if args.auto_clean:
    log.info("--auto-clean: 정제 단계로 이어집니다.")
    Cleaner(config, storage).run()
    # ↑ 옵션 없이 기본값으로만 실행
    # --on-duplicate, --reprocess, --limit 전달 불가
```

### 동작 범위 비교

| 항목 | `--auto-clean` | `clean` 명령 별도 실행 |
|------|:--------------:|:----------------------:|
| 기본 정제 실행 | ✅ | ✅ |
| `--on-duplicate` 지정 | ❌ | ✅ |
| `--reprocess` 지정 | ❌ | ✅ |
| `--limit` 지정 | ❌ | ✅ |

### 권장 사용법

```bash
# 간단한 수집 + 기본 정제 (빠른 실행)
python main.py fetch --source yna --auto-clean

# 세부 옵션이 필요한 경우 → clean 명령 별도 실행
python main.py fetch --source yna
python main.py clean --on-duplicate upsert

# 정제 규칙이 바뀐 경우 전체 재처리
python main.py fetch --source yna
python main.py clean --reprocess --on-duplicate upsert

# 대량 수집 후 건수 제한하여 정제
python main.py fetch --source yna --method all --limit 50
python main.py clean --limit 100 --on-duplicate skip
```

### config.json 기본 중복 정책 설정

`--auto-clean` 사용 시 아래 설정값이 적용됩니다.

```json
{
  "cleaning": {
    "on_duplicate": "skip"
  }
}
```

`upsert`로 변경하면 `--auto-clean` 시에도 upsert 정책이 적용됩니다.

---

## 전체 권장 워크플로우

```bash
# 1. 수집
python main.py fetch --source yna --method all --limit 20

# 2. 정제 (중복 제거 포함)
python main.py clean --on-duplicate upsert

# 3. AI 요약
python main.py summarize --unsummarized --limit 10

# 4. 인사이트 분석
python main.py analyze --date-from 2026-09-01 --date-to 2026-09-07

# 5. 리포트 생성
python main.py report --format md

# 6. 내보내기
python main.py export --format csv --status summarized
```

---

## 피드백 항목 요약

> 교수 피드백 4개 항목에 대한 분석·실험·개선 근거는
> **[EXPERIMENT.md](EXPERIMENT.md)** 에 전체 수록되어 있습니다.
> 아래는 각 항목의 핵심 결론과 문서 위치를 안내합니다.

| # | 피드백 항목 | 핵심 결론 | 상세 문서 |
|---|------------|-----------|-----------|
| 1 | RSS vs 크롤링 실제 품질 차이 | 크롤링 본문 평균 1,655자 vs RSS 710자 (2.3배). URL 형태 불일치로 raw 중복 → clean 단계 url_hash로 정리 | [EXPERIMENT.md 1장](EXPERIMENT.md#1-rss-vs-크롤링--실측-품질-비교) |
| 2 | 프롬프트 개선 과정 | 1차(기본형) → 2차(형식 강제) → 3차(환각 방지 + 후처리) 3단계 개선. 길이 초과율 30% → 5% 미만 | [EXPERIMENT.md 2장](EXPERIMENT.md#2-프롬프트-개선-과정) |
| 3 | 토큰·비용 최적화 실험 | 본문 194자 → 압축률 100% 비효율 호출 식별. min_content_for_summary=300자 분리 기준 도출 | [EXPERIMENT.md 3장](EXPERIMENT.md#3-토큰--비용-최적화) |
| 4 | 데이터 불일치 디버깅 전략 | raw 12 → clean 7 원인을 STEP별 추적. 중복 5건(URL 형태 차이) + 재발 방지 설계 반영 | [EXPERIMENT.md 4장](EXPERIMENT.md#4-데이터-불일치-디버깅--raw-12--clean-7) |

> **이 문서(TROUBLESHOOTING.md)** 는 CLI 사용 중 발생하는
> 운영상 문제(중복 수집 현상, 로그 확인법, limit 계산, auto-clean 범위)를 다룹니다.
> 설계 판단·실험 근거·개선 이력은 EXPERIMENT.md를 참조하세요.
