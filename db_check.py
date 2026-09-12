"""EXPERIMENT.md 실측용 임시 DB 조회 스크립트."""
import sqlite3
from pathlib import Path

# config.json 의 paths.db 경로에 맞게 조정 (아래는 일반적 위치)
DB_PATH = Path("data/newsbot.db")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def show(title, sql):
    print(f"\n{'='*60}\n{title}\n{'='*60}")
    rows = conn.execute(sql).fetchall()
    if not rows:
        print("(결과 없음)")
        return
    # 헤더
    cols = rows[0].keys()
    print(" | ".join(f"{c}" for c in cols))
    print("-" * 60)
    for r in rows:
        print(" | ".join(str(r[c]) for c in cols))

# ① 수집 방법별 본문 길이 (1장 핵심 데이터)
show("① 수집 방법별 본문 길이", """
    SELECT collect_method AS 방법,
           COUNT(*)               AS 건수,
           ROUND(AVG(content_length)) AS 평균길이,
           MIN(content_length)    AS 최소,
           MAX(content_length)    AS 최대
    FROM clean_news
    GROUP BY collect_method
""")

# ② 카테고리/기자명 결측 비교 (1장 보조)
show("② 방법별 메타데이터 결측", """
    SELECT collect_method AS 방법,
           SUM(CASE WHEN author IS NULL OR author='' THEN 1 ELSE 0 END) AS 기자명없음,
           SUM(CASE WHEN category IS NULL OR category='' THEN 1 ELSE 0 END) AS 카테고리없음
    FROM clean_news
    GROUP BY collect_method
""")

# ③ 요약 압축률 상세 (3장 토큰/비용용)
show("③ 본문→요약 압축률", """
    SELECT id,
           content_length          AS 본문길이,
           summary_length          AS 요약길이,
           ROUND(summary_length * 100.0 / content_length, 1) AS 압축률
    FROM clean_news
    WHERE summary_length IS NOT NULL AND content_length > 0
    ORDER BY content_length DESC
""")

conn.close()