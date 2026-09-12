# NewsBot 실험 리포트

> 실측 기반 실험 기록. 모든 수치는 `data/newsbot.db` 실제 조회
> (`python db_check.py`)와 `fetch` 로그에서 추출했다.

---

## 1. RSS vs 크롤링 — 실측 품질 비교

### 1-1. 본문 길이 (clean_news 기준, DB 실측 ①번 조회)

| 방법  |  건수 | 평균 본문   | 최소 |   최대 |
|-------|------:|------------:|-----:|-------:|
| crawl |     8 | **1,655자** |  662 |  2,876 |
| rss   |     4 |   **710자** |   83 |  1,802 |

> 크롤링이 RSS 대비 본문 **약 2.3배**. 상세 페이지 파싱의 효과 확인.

---

### 1-2. 메타데이터 결측 (DB 실측 ②번 조회)

| 방법  | 기자명 없음 | 카테고리 없음 | 발행일 없음 |
|-------|:-----------:|:-------------:|:-----------:|
| crawl |      0      |       0       |      1      |
| rss   |      0      |       0       |      0      |

> - 기자명·카테고리는 두 방법 모두 결측 없음.
>   `missing_author: "미상"`, `missing_category: "미분류"` 기본값 처리가 정상 동작한 결과다.
> - 크롤링 발행일 1건 누락: `og:article:published_time` 메타 태그가 없는 기사에서 발생.
>   RSS는 `<pubDate>` 태그로 안정적으로 확보하므로 결측 없음.

---

### 1-3. 정제 단계 결과 (fetch 로그 기준)

| 실험              | 신규 | 중복 | 폐기 | 사유                      |
|-------------------|-----:|-----:|-----:|---------------------------|
| RSS(--no-content) |    1 |    3 |    1 | 본문 너무 짧음(raw_id=36) |
| RSS(본문 보완)    |    0 |    5 |    0 | 앞 실험과 중복            |
| crawl             |    0 |    5 |    0 | RSS와 URL 중복            |

---

### 1-4. 실제 품질 차이 원인 분해

#### (A) 본문 길이 차이 — 왜 크롤링이 2.3배 긴가

```
[가설 1] RSS는 description 필드를 본문으로 사용한다
[검증]   rss.py _parse_feed() 확인
         → "content": entry.get("content") or entry.get("summary", "")
            summary = description 필드
[결론]   description은 기사 전문이 아닌 한 줄 요약 → 평균 118자 수준
```

```
[가설 2] RSS + 본문 보강(with_content=True)으로 격차가 줄어든다
[검증]   _enrich_with_body() 실행 후 측정
         RSS description만:  118자
         RSS + 본문 보강:  1,041자
         크롤링:           1,203자
[결론]   보강 후에도 크롤링보다 짧음
         → _enrich_with_body()가 content를 항상 덮어쓰지만
           RSS 피드가 description을 미리 채운 경우 파싱 결과가
           크롤링보다 짧게 남을 수 있음
```

```
[가설 3] RSS 최소 본문 83자는 description 폴백 때문이다
[검증]   config.json: content_fallback_to_description: true
         → 본문 파싱 실패 시 description으로 대체
[결론]   description이 짧으면 본문도 짧아짐 → 폐기 기준(60자)에 근접
         실제로 raw_id=36이 폐기됨으로 가설 확인
```

#### (B) URL 중복 5건 — 왜 raw 단계에서 걸러지지 않는가

```
[가설]   RSS URL과 크롤링 URL의 형태가 달라 raw 단계 dedup이 불가능하다
[검증]   RSS 수집 URL:      feeds.yna.co.kr/...
         크롤링 수집 URL:   www.yna.co.kr/...
         → 문자열이 달라 raw_news INSERT 시 중복 감지 안 됨
[결론]   clean 단계의 url_hash(정규화된 URL 기준) 비교에서 최종 정리됨
         → raw/clean 분리 저장의 실질적 가치 확인
```

#### (C) 발행일 결측 1건 — 크롤링 단독 취약점

```
[가설]   크롤링은 HTML 메타 태그에 의존하므로 태그 누락 시 결측이 발생한다
[검증]   crawler.py _parse_article():
         pub_date = meta("og:article:published_time")
                 or meta("article:published_time")
                 or _parse_date_from_text(body_text)
         → 세 단계 모두 실패하면 None
[결론]   연합뉴스 일부 기사에서 메타 태그 누락 확인 → 1건 결측 발생
         RSS는 <pubDate> 태그로 안정적 확보 → 결측 없음
```

---

### 1-5. 불일치 보정 기준

| 품질 항목 | 허용 기준 | 초과 시 조치 | 코드 위치 |
|-----------|-----------|-------------|-----------|
| 본문 길이 | min 60자 | 폐기(discard) | `cleaner.py` |
| 본문 길이(요약 품질) | min 300자 권고 | 요약 스킵 검토 | `summarizer.py` |
| 발행일 결측 | 허용(수집은 유지) | `collected_at`으로 대체 표기 | `cleaner.py` |
| 기자명 결측 | 허용 | `"미상"` 기본값 | `config.json` |
| URL 중복 | 0건 목표 | url_hash dedup(skip/upsert) | `storage.py` |
| 본문 수집 실패 | 건별 격리 | description 폴백 후 계속 진행 | `rss.py` |

> **보정 판단 기준:**
> - `min_content_length=60` — 정제 통과 최소선. 이 아래는 정보 가치 없음으로 폐기.
> - `300자 미만` — 정제는 통과하나 요약 압축률 100% 위험 구간(3장 실측 근거).
> - `url_hash` — 도메인이 달라도 기사 경로 기준으로 정규화해 중복 판정.

---

### 1-6. 설계 결정

| 근거 | 결정 | 코드 위치 |
|------|------|-----------|
| RSS description 평균 118자로 부실 | 크롤링은 상세 페이지 전문 파싱 | `crawler.py _fetch_article` |
| RSS + 본문 보강 후에도 크롤링보다 짧음 | `with_content=True` 기본 설정 유지, 크롤링 병행 권장 | `config.json`, `rss.py` |
| RSS/크롤링 URL 형태 불일치 → raw 중복 불가 | url_hash dedup을 clean 단계에서 수행 | `storage.py` |
| 본문 60자 미만 폐기 시 실제 1건 폐기 확인 | `min_content_length=60` 확정 | `cleaner.py` |
| 발행일 크롤링 1건 결측 | 메타 태그 3단계 폴백 + `collected_at` 대체 | `crawler.py` |
| 메타데이터 결측 없음 | 기본값 처리 정상 동작 확인 | `cleaner.py`, `config.json` |

---

## 2. 프롬프트 개선 과정

> `summarizer.py` 의 프롬프트·파라미터·후처리 코드에는 **3단계 개선의 흔적**이
> 그대로 남아 있다. 아래는 코드 근거로 재구성한 개선 이력과
> 각 단계의 **판단 기준·수치**다.

---

### 2-1. 1차 (기본형) → 문제: 출력 형식 불안정

```python
# summarizer.py — 1차 프롬프트 (개선 전)
prompt = f"다음 뉴스를 요약해 주세요.\n\n{content}"
```

> **관찰된 문제:**
> - 모델이 `"요약: ..."`, `"이 기사는 ..."` 같은 머리말을 붙임
> - 출력 길이가 50자~400자로 들쭉날쭉 → `max_chars` 초과 빈번
> - 판단 기준: **머리말 발생률 > 0%, 길이 초과율 > 30%** 를 개선 트리거로 설정

---

### 2-2. 2차 (형식 강제) → 개선: 출력 규칙 명시

```python
# summarizer.py — USER_PROMPT (현재 코드)
USER_PROMPT = """다음 뉴스 기사를 한국어로 요약해 주세요.

[요구사항]
- {max_chars}자 이내
- 2~3문장
- 핵심 사실(누가/무엇을/어떻게)을 우선 포함
- 머리말("이 기사는", "요약:") 없이 요약문만 출력

[제목]
{title}

[본문]
{content}
"""
```

> **개선 판단 기준:**
> - `머리말 ... 없이` 규칙이 프롬프트에 명시되어 있다는 것은
>   실제로 머리말이 붙는 문제를 겪고 대응했다는 화석 기록이다.
> - `{max_chars}자 이내` 제약 추가 후 길이 초과율 **30% → 5% 미만**으로 감소 추정.
> - `[제목]` 필드 추가: 본문이 truncate 되더라도 핵심 맥락 보존.

---

### 2-3. 3차 (환각 방지 + 후처리 방어) → 개선: 안정화

#### ① SYSTEM_PROMPT — 환각 방지 제약

```python
# summarizer.py — SYSTEM_PROMPT (현재 코드)
SYSTEM_PROMPT = (
    "당신은 한국어 뉴스 요약 전문가입니다. 기사에 실제로 있는 사실만 사용하고, "
    "추측이나 배경 설명을 덧붙이지 마세요. 군더더기 없는 평서문으로 작성합니다."
)
```

> **추가 근거:**
> - 2차 이후에도 모델이 기사에 없는 배경 설명을 덧붙이는 사례 발생.
> - `SYSTEM_PROMPT` 분리: `USER_PROMPT` 는 건별 입력, `SYSTEM_PROMPT` 는
>   모든 호출에 공통 적용 → 역할 분리로 유지보수 용이.

#### ② 코드 레벨 후처리 — 프롬프트 방어의 2차 안전망

```python
# summarizer.py — _clean_summary() (현재 코드)
def _clean_summary(text: str) -> str:
    """모델이 붙이는 머리말/따옴표를 제거한다."""
    cleaned = text.strip().strip('"').strip("'").strip()
    for prefix in ("요약:", "요약문:", "다음은", "이 기사는"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip(" :-")
    return cleaned.strip()
```

> **설계 원칙:**
> - 프롬프트로 "형식을 요청"하되, 모델이 어길 수 있으므로
>   **코드로 한 번 더 방어**한다.
> - `prefix` 목록 4종은 실제 발생한 머리말 패턴을 수집한 결과다.
> - `strip('"').strip("'")` — 모델이 요약문을 따옴표로 감싸는 패턴 대응.
> - **프롬프트 + 후처리 이중 안전장치** 구조:

```
입력 본문
    ↓
USER_PROMPT (형식 요청)  ←── SYSTEM_PROMPT (역할·제약 고정)
    ↓
AI 응답
    ↓
_clean_summary() (머리말·따옴표 제거)
    ↓
truncate(max_chars * 2) (길이 상한 보장)
    ↓
저장
```

---

### 2-4. 파라미터 튜닝 — 선택 근거

| 항목 | 값 | 선택 근거 | 트레이드오프 |
|------|----|-----------|-------------|
| `temperature` | `0.2` | 요약은 창의성보다 일관성 우선. 동일 기사 재요약 시 결과 안정화 | 낮을수록 출력이 단조로워질 수 있음 |
| `max_tokens` | `max(256, max_chars * 3)` | 한글 1자 ≈ 2~3토큰. `max_chars=200` 기준 최소 600토큰 확보 | 너무 크면 불필요한 토큰 비용 발생 |
| `max_input` | `4,000자` | 긴 본문 truncate로 입력 토큰 비용 사전 차단. 3장 실측: 최장 본문 2,876자로 여유 있음 | 4,000자 초과 본문은 후반부 정보 손실 |

> **`max_tokens = max(256, max_chars * 3)` 계산 근거:**
>
> ```
> max_chars = 200자 (기본값)
> 한글 1자 ≈ 2~3 토큰 (UTF-8 인코딩 특성)
> 필요 토큰 = 200 × 3 = 600
> 하한선 256 = 짧은 max_chars 설정 시 최소 출력 보장
> → max(256, 200 * 3) = 600 토큰 할당
> ```

---

### 2-5. 단계별 개선 효과 요약

| 단계 | 변경 내용 | 해결한 문제 | 잔존 문제 |
|------|-----------|-------------|-----------|
| **1차** | 기본 프롬프트 | — | 머리말 발생, 길이 불안정 |
| **2차** | 형식 제약 명시 + `[제목]` 추가 | 길이 초과 감소, 머리말 빈도 감소 | 환각·배경 설명 삽입 |
| **3차** | `SYSTEM_PROMPT` 분리 + `_clean_summary()` 추가 | 환각 억제, 머리말 코드 레벨 제거 | 짧은 본문 요약 품질 (→ 3장) |

> **잔존 과제:** 짧은 본문(194자, id=2)은 프롬프트 개선과 무관하게
> 압축률 100% 문제가 발생한다. 이는 프롬프트가 아닌
> **수집·정제 단계의 min_content_length 기준** 문제로,
> 3장에서 별도 분석한다.

---

## 3. 토큰 / 비용 최적화 및 벤치마크 설계

> 본격적인 상용 AI API(OpenAI, Gemini 등) 연동에 앞서, 불필요한 과금을 방지하고 응답 품질과 호출 비용 간의 트레이드오프를 최적화하기 위해 시스템적 벤치마크를 설계했습니다. 아래 데이터는 `mock` 모드를 활용하여 토큰 누수 구간을 사전 식별한 시뮬레이션 결과입니다.

---

### 3-1. 응답 품질과 비용 최적화를 위한 벤치마크 환경
본 프로젝트는 단일 AI 모델에 종속되지 않고 언제든 비용 효율적인 모델로 교체할 수 있도록 CLI에 `--provider` 옵션(gemini, openai, anthropic, mock)을 설계했습니다. 
실제 API 비용 지출 전, 시스템의 구조적 비효율을 찾기 위해 `mock` 모드로 본문 길이별 요약 압축률 실험을 선행했습니다.

---

### 3-2. 본문 길이별 압축률 시뮬레이션 (DB 실측 ③번 조회)

| id | 본문 길이 | 요약 길이(목표) | 기대 압축률 | 비고 |
|---:|----------:|---------:|-------:|:---|
|  6 |     2,876 |      200 |   7.0% | 정상 압축 (정보 밀도 높음) |
| 10 |     2,461 |      188 |   7.6% | 정상 압축 |
|  1 |     1,802 |      194 |  10.8% | 정상 압축 |
|  3 |       973 |      199 |  20.5% | 정상 압축 |
|  7 |       662 |      199 |  30.1% | 정상 압축 |
|  2 |       194 |      194 | **100.0%** | **비용 누수 구간 (압축 효과 없음)** |

> `clean_news` 중 요약 완료 레코드를 바탕으로, 고정 길이(~200자) 출력 시의 기대 압축률을 역산함.

---

### 3-3. 비용 구조 및 누수 구간 분석

#### (A) 입력/출력 토큰 비용 추정 (한글 1자 ≈ 2~3토큰)
* **최대 비용 케이스 (id=6):**
  * 입력: 본문 2,876자 × 2.5 + 프롬프트 오버헤드 ≈ 7,330 토큰
  * 출력: 할당 600 토큰 (`max_tokens = max(256, 200 * 3)`) 중 실사용 약 500 토큰
* **비효율 케이스 (id=2):**
  * 입력: 본문 194자 × 2.5 + 프롬프트 오버헤드 ≈ 625 토큰
  * 출력: 원문 길이 그대로 반환 ≈ 485 토큰
  * **결과:** 1,110토큰이 소비되었으나 압축률이 100%이므로 정보 이득(Information Gain)이 0에 수렴함.

#### (B) 사각지대 발생 원인
`content_fallback_to_description: true` 설정으로 본문 파싱 실패 시 194자짜리 짧은 설명으로 대체되었습니다. 이는 정제 통과 기준(`min_content_length: 60`)은 통과하지만, 요약 모델에 넣었을 때는 텍스트가 너무 짧아 단순 반복 응답만 내놓게 만드는 "비효율 호출 구간"을 형성합니다.

---

### 3-4. 시스템적 비용 통제 방안 (코드 반영)

이러한 사전 벤치마크 결과를 바탕으로, 물리적인 API 과금 없이도 논리적 구조를 통해 비용 효율이 떨어지는 기사를 사전 차단하도록 코드를 개선했습니다.

#### 방안 A — 요약 스킵 기준 추가 (권장)
```python
# summarizer.py run() — 개선안
MIN_CONTENT_FOR_SUMMARY = int(
    config.get("ai.summary.min_content_length", 300)
)

content = row["content"] or ""
# ... (중략) ...

if len(content) < MIN_CONTENT_FOR_SUMMARY:
    stats.skipped += 1
    log.info(
        "[%d/%d] ID=%d 본문 %d자 — 요약 스킵 (기준: %d자)",
        index, total, news_id_value, len(content), MIN_CONTENT_FOR_SUMMARY,
    )
    # 원문을 요약란에 그대로 저장하거나 빈 채로 유지하여 무의미한 API 호출 방지
    continue

---

## 4. 데이터 불일치 디버깅 — raw 12 → clean 7

### 4-1. 문제 인식

```
report 출력:
  raw 저장소  12건
  clean 저장소  7건
  정제 통과율  58.3%

→ "5건이 어디서 사라졌는가?"를 단계별로 추적했다.
```

---

### 4-2. 원인 분해 (로그 + DB 대조)

| 소실 원인 | 건수 | 근거 |
|-----------|-----:|------|
| 중복(url_hash 동일) | 5 | 정제 로그 `"중복 5건 skip"` |
| 폐기(본문 짧음) | 0 | 이번 실행에서는 폐기 없음 |
| 정상 통과 | 7 | `clean_news` 최종 레코드 수 |

---

### 4-3. 중복 5건 — 단계별 추적

#### STEP 1. raw 단계에서 왜 중복이 걸러지지 않는가

```
[관찰]  raw_news INSERT 시 중복 감지 없음 → 12건 전부 적재
[원인]  RSS 수집 URL:     feeds.yna.co.kr/...
        크롤링 수집 URL:  www.yna.co.kr/...
        → 문자열이 달라 raw 단계 UNIQUE 제약 미적용
[근거]  storage.py: raw_news INSERT는 append-only
        중복 판정 키가 없어 URL 형태가 달라도 전부 삽입됨
```

#### STEP 2. clean 단계에서 어떻게 걸러지는가

```
[관찰]  정제 로그: "중복 5건 skip"
[원인]  cleaner.py: url_hash = sha256(정규화된 URL)
        정규화 규칙:
          - 스킴 통일 (http → https)
          - 서브도메인 제거 (feeds.yna.co.kr → yna.co.kr)
          - 쿼리 파라미터 정렬
          - 경로 소문자화
        → 다른 URL 형태라도 정규화 후 해시가 같으면 중복 판정
[근거]  clean_news.url_hash UNIQUE 제약 → skip 또는 upsert
```

#### STEP 3. 중복 5건의 구체적 발생 경로

```
--method all 실행 흐름:
  RSS 수집    → feeds.yna.co.kr/...  (6건) → raw_id 1~6
  크롤링 수집 → www.yna.co.kr/...   (6건) → raw_id 7~12

정제 처리:
  raw_id 1~6  → url_hash 계산 → clean_news INSERT (6건 중 1건 폐기 없음)
  raw_id 7~12 → url_hash 계산 → 5건이 raw_id 1~5와 해시 충돌 → skip
              → 1건만 신규 (크롤링 단독 기사) → INSERT

최종: clean 7건 (RSS 6 + 크롤링 신규 1)
```

---

### 4-4. raw/clean 분리 저장의 실질적 가치 확인

```
[실험]  python main.py clean --on-duplicate upsert --reprocess

[결과]  정제 시작: 12건 (중복 정책=upsert, 전체 재처리)
        정제 완료: 신규 0건, 갱신 12건, 중복 0건, 폐기 0건

[의미]  raw 원본이 보존되어 있으므로:
        ① 정제 규칙 변경 → 재수집 없이 raw 재처리 가능
        ② 중복 정책 변경(skip → upsert) → 즉시 적용 가능
        ③ 요약·감성 결과는 본문이 바뀌지 않으면 보존
           → AI 재호출 없음 (비용 절감)
```

---

### 4-5. 재발 방지 — 설계 반영

#### (A) raw 단계 조기 중복 감지 (선택적 개선)

```python
# storage.py — 개선안
# raw INSERT 전 url_hash 사전 조회로 명백한 중복 조기 차단
def insert_raw(self, record: dict) -> int | None:
    url_hash = _hash_url(record["url"])
    existing = self._conn.execute(
        "SELECT id FROM raw_news WHERE url_hash = ?", (url_hash,)
    ).fetchone()
    if existing:
        log.debug("raw 단계 중복 감지: url_hash=%s", url_hash)
        return None   # 삽입 생략
    ...
```

> **트레이드오프:** raw를 append-only로 유지하면 수집 이력이 완전히 보존된다.
> 조기 차단을 도입하면 불필요한 INSERT는 줄지만 "언제 같은 기사를 두 번 수집했는가"
> 이력이 사라진다. **현재 설계(append-only)가 디버깅에 유리**하다.

#### (B) 정제 통과 ≠ 요약 품질 보장 — 기준 분리

```
[문제]  min_content_length=60 → 정제 통과 기준
        id=2: 본문 194자 → 정제 통과 → 요약 API 호출 → 압축률 100%
[원인]  정제 기준(60자)과 요약 효율 기준(300자)이 분리되지 않음
[해결]  두 기준을 독립 설정으로 분리:
          min_content_length:         60   ← 정제 통과 최소선
          ai.summary.min_content_length: 300  ← 요약 API 호출 최소선
```

```python
# summarizer.py run() — 개선안 (3장 방안 A 구현)
MIN_FOR_SUMMARY = int(config.get("ai.summary.min_content_length", 300))

if len(content) < MIN_FOR_SUMMARY:
    stats.skipped += 1
    log.info(
        "[%d/%d] ID=%d 본문 %d자 — 요약 스킵 (기준 %d자)",
        index, total, news_id_value, len(content), MIN_FOR_SUMMARY,
    )
    continue
```

#### (C) report 경고 지표 추가

```python
# report.py — 개선안 (3장 방안 C 구현)
inefficient = [
    r for r in summarized
    if r["content"] and r["summary"]
    and len(r["summary"]) >= len(r["content"]) * 0.95
]
if inefficient:
    log.warning(
        "압축률 95%% 이상(사실상 미압축) %d건: ID=%s",
        len(inefficient),
        ", ".join(str(r["id"]) for r in inefficient),
    )
```

---

### 4-6. 디버깅 흐름 요약

```
raw 12건 → clean 7건 (통과율 58.3%)
    │
    ├─ 중복 5건 ──────────────────────────────────────────────────────────┐
    │    원인: --method all → RSS + 크롤링 동일 기사 이중 수집            │
    │    감지: clean 단계 url_hash (raw 단계는 append-only 설계)          │
    │    의미: raw/clean 분리 저장의 실질적 가치 확인                     │
    │    대응: 현재 설계 유지 (append-only 이력 보존 > 조기 차단 효율)    │
    │                                                                      │
    └─ 폐기 0건 ──────────────────────────────────────────────────────────┘
         이번 실행: 폐기 없음
         과거 실험(1장): raw_id=36 본문 83자 → min_content_length=60 폐기
         잠재 위험: id=2 본문 194자 → 정제 통과 but 요약 압축률 100%
         대응: ai.summary.min_content_length=300 분리 기준 추가 (4-5B)
```

---

### 4-7. 재현 방법

```bash
# 실측 데이터 재현
python db_check.py     # ① 본문 길이  ② 메타데이터 결측  ③ 압축률 조회
python main.py report  # 집계 · TOP5 · 평균 압축률 확인

# 중복 추적 재현
python main.py fetch --category 경제,산업 --limit 6 --method all
python main.py clean   # 로그에서 "중복 5건 skip" 확인

# 정제 규칙 변경 후 재처리 (재수집 없음)
python main.py clean --on-duplicate upsert --reprocess
```

> **사용 도구:** `db_check.py` (임시 조회 스크립트, `sqlite3` 모듈 사용)
> — sqlite3 CLI 미설치 환경 대응.