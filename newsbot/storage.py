"""영구 저장소(SQLite) 계층.

raw / clean 을 **물리적으로 분리된 테이블**로 관리한다.

- ``raw_news``  : 수집한 원본을 그대로(JSON) + 수집 시각/소스/수집 방법과 함께 append-only 로 적재.
                  파싱 규칙이 바뀌어도 재처리(clean 재생성)가 가능하다.
- ``clean_news``: 검증·정규화를 통과한 분석용 데이터. URL 해시 UNIQUE 로 중복을 통제한다.
- ``analyses``  : AI 인사이트 분석 결과 이력.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from .logger import get_logger
from .utils import now_str

log = get_logger("storage")

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS raw_news (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT    NOT NULL,           -- 소스 키 (예: yna)
    source_name    TEXT,                       -- 소스 표시명 (예: 연합뉴스)
    collect_method TEXT    NOT NULL,           -- 수집 방법: rss | crawl
    origin_url     TEXT,                       -- 수집 출처(피드/목록 페이지) URL
    url            TEXT,                       -- 기사 URL
    url_hash       TEXT,
    category       TEXT,
    collected_at   TEXT    NOT NULL,           -- 수집 시각 (KST)
    payload        TEXT    NOT NULL,           -- 원본 JSON 문자열
    processed      INTEGER NOT NULL DEFAULT 0  -- clean 단계 처리 여부
);

CREATE INDEX IF NOT EXISTS idx_raw_hash      ON raw_news(url_hash);
CREATE INDEX IF NOT EXISTS idx_raw_processed ON raw_news(processed);

CREATE TABLE IF NOT EXISTS clean_news (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id          INTEGER,
    url_hash        TEXT    NOT NULL UNIQUE,   -- 중복 판정 키
    url             TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    description     TEXT,
    category        TEXT,
    source          TEXT,
    source_name     TEXT,
    author          TEXT,
    collect_method  TEXT,
    published_at    TEXT,                      -- 'YYYY-MM-DD HH:MM:SS'
    published_date  TEXT,                      -- 'YYYY-MM-DD'
    collected_at    TEXT,
    collected_date  TEXT,
    content_length  INTEGER DEFAULT 0,
    summary         TEXT,
    summary_length  INTEGER,
    summary_model   TEXT,
    summarized_at   TEXT,
    sentiment       TEXT,                      -- 긍정 | 부정 | 중립
    sentiment_score REAL,
    sentiment_reason TEXT,
    sentiment_model TEXT,
    sentiment_at    TEXT,
    status          TEXT    NOT NULL DEFAULT 'clean',   -- clean | summarized
    created_at      TEXT,
    updated_at      TEXT,
    FOREIGN KEY (raw_id) REFERENCES raw_news(id)
);

CREATE INDEX IF NOT EXISTS idx_clean_category  ON clean_news(category);
CREATE INDEX IF NOT EXISTS idx_clean_pubdate   ON clean_news(published_date);
CREATE INDEX IF NOT EXISTS idx_clean_status    ON clean_news(status);

CREATE TABLE IF NOT EXISTS analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    date_from     TEXT,
    date_to       TEXT,
    category      TEXT,
    target_count  INTEGER NOT NULL DEFAULT 0,
    provider      TEXT,
    model         TEXT,
    trends        TEXT,       -- JSON 배열
    keywords      TEXT,       -- JSON 배열
    comparison    TEXT,       -- JSON 배열 (공통점/차이점)
    implications  TEXT,       -- JSON 배열 (시사점)
    overview      TEXT,
    raw_response  TEXT
);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT,
    finished_at    TEXT,
    source         TEXT,
    collect_method TEXT,
    requested      INTEGER DEFAULT 0,
    succeeded      INTEGER DEFAULT 0,
    failed         INTEGER DEFAULT 0,
    note           TEXT
);
"""

CLEAN_COLUMNS = (
    "raw_id", "url_hash", "url", "title", "content", "description", "category",
    "source", "source_name", "author", "collect_method", "published_at",
    "published_date", "collected_at", "collected_date", "content_length",
)


class Storage:
    """SQLite 저장소. with 문으로 사용한다."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    # ------------------------------------------------------------ 라이프사이클
    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------- raw
    def insert_raw(self, record: dict[str, Any]) -> int:
        """원본 레코드를 raw 저장소에 적재한다(무조건 append)."""
        payload = json.dumps(record.get("payload", record), ensure_ascii=False)
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO raw_news
                   (source, source_name, collect_method, origin_url, url,
                    url_hash, category, collected_at, payload, processed)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (
                    record.get("source"),
                    record.get("source_name"),
                    record.get("collect_method"),
                    record.get("origin_url"),
                    record.get("url"),
                    record.get("url_hash"),
                    record.get("category"),
                    record.get("collected_at") or now_str(),
                    payload,
                ),
            )
        return int(cur.lastrowid)

    def raw_hashes(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT url_hash FROM raw_news WHERE url_hash IS NOT NULL"
        ).fetchall()
        return {r["url_hash"] for r in rows}

    def fetch_raw(self, *, only_unprocessed: bool = True, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM raw_news"
        params: list[Any] = []
        if only_unprocessed:
            sql += " WHERE processed = 0"
        sql += " ORDER BY id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return self.conn.execute(sql, params).fetchall()

    def mark_raw_processed(self, raw_ids: Iterable[int]) -> None:
        ids = [(int(i),) for i in raw_ids]
        if not ids:
            return
        with self.conn:
            self.conn.executemany("UPDATE raw_news SET processed = 1 WHERE id = ?", ids)

    def count_raw(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS c FROM raw_news").fetchone()["c"])

    # ----------------------------------------------------------------- clean
    def find_clean_by_hash(self, url_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM clean_news WHERE url_hash = ?", (url_hash,)
        ).fetchone()

    def insert_clean(self, record: dict[str, Any]) -> int:
        now = now_str()
        values = [record.get(col) for col in CLEAN_COLUMNS]
        placeholders = ",".join("?" * (len(CLEAN_COLUMNS) + 3))
        with self.conn:
            cur = self.conn.execute(
                f"""INSERT INTO clean_news ({','.join(CLEAN_COLUMNS)}, status, created_at, updated_at)
                    VALUES ({placeholders})""",
                (*values, "clean", now, now),
            )
        return int(cur.lastrowid)

    def upsert_clean(self, record: dict[str, Any], existing_id: int) -> None:
        """중복 정책이 upsert 일 때 본문/메타를 최신 내용으로 갱신한다.

        요약/감성 결과는 지우지 않는다(본문이 실제로 바뀐 경우만 초기화).
        """
        existing = self.conn.execute(
            "SELECT content FROM clean_news WHERE id = ?", (existing_id,)
        ).fetchone()
        content_changed = bool(existing) and (existing["content"] or "") != (record.get("content") or "")

        assignments = ", ".join(f"{col} = ?" for col in CLEAN_COLUMNS if col != "url_hash")
        params = [record.get(col) for col in CLEAN_COLUMNS if col != "url_hash"]
        sql = f"UPDATE clean_news SET {assignments}, updated_at = ?"
        params.append(now_str())
        if content_changed:
            sql += (", summary = NULL, summary_length = NULL, summary_model = NULL,"
                    " summarized_at = NULL, sentiment = NULL, sentiment_score = NULL,"
                    " sentiment_reason = NULL, sentiment_model = NULL, sentiment_at = NULL,"
                    " status = 'clean'")
        sql += " WHERE id = ?"
        params.append(int(existing_id))
        with self.conn:
            self.conn.execute(sql, params)

    def get_news(self, news_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM clean_news WHERE id = ?", (int(news_id),)).fetchone()

    # ---------------------------------------------------------------- 조회/필터
    @staticmethod
    def _build_filters(
        *,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        source: str | None = None,
        news_id: int | None = None,
        date_field: str = "published_date",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if news_id is not None:
            clauses.append("id = ?")
            params.append(int(news_id))
        if category:
            clauses.append("category = ?")
            params.append(category)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if date_from:
            clauses.append(f"{date_field} >= ?")
            params.append(date_from)
        if date_to:
            clauses.append(f"{date_field} <= ?")
            params.append(date_to)
        if keyword:
            clauses.append("(title LIKE ? OR content LIKE ? OR IFNULL(summary,'') LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        if status == "summarized":
            clauses.append("summary IS NOT NULL AND TRIM(summary) <> ''")
        elif status == "unsummarized":
            clauses.append("(summary IS NULL OR TRIM(summary) = '')")
        elif status == "unanalyzed":  # 감성 미분석
            clauses.append("(sentiment IS NULL OR TRIM(sentiment) = '')")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def query_news(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        order: str = "DESC",
        order_by: str = "published_at",
        **filters,
    ) -> list[sqlite3.Row]:
        where, params = self._build_filters(**filters)
        order_dir = "ASC" if str(order).upper() == "ASC" else "DESC"
        allowed = {"published_at", "collected_at", "id", "content_length", "title"}
        column = order_by if order_by in allowed else "published_at"
        sql = f"SELECT * FROM clean_news{where} ORDER BY {column} {order_dir}, id {order_dir}"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        return self.conn.execute(sql, params).fetchall()

    def count_news(self, **filters) -> int:
        where, params = self._build_filters(**filters)
        row = self.conn.execute(f"SELECT COUNT(*) AS c FROM clean_news{where}", params).fetchone()
        return int(row["c"])

    # ------------------------------------------------------------------ 요약
    def save_summary(self, news_id: int, summary: str, model: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE clean_news
                   SET summary = ?, summary_length = ?, summary_model = ?,
                       summarized_at = ?, status = 'summarized', updated_at = ?
                   WHERE id = ?""",
                (summary, len(summary), model, now_str(), now_str(), int(news_id)),
            )

    def save_sentiment(
        self, news_id: int, sentiment: str, score: float | None, reason: str | None, model: str
    ) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE clean_news
                   SET sentiment = ?, sentiment_score = ?, sentiment_reason = ?,
                       sentiment_model = ?, sentiment_at = ?, updated_at = ?
                   WHERE id = ?""",
                (sentiment, score, reason, model, now_str(), now_str(), int(news_id)),
            )

    # ------------------------------------------------------------------ 분석
    def insert_analysis(self, record: dict[str, Any]) -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO analyses
                   (created_at, date_from, date_to, category, target_count, provider,
                    model, trends, keywords, comparison, implications, overview, raw_response)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    now_str(),
                    record.get("date_from"),
                    record.get("date_to"),
                    record.get("category"),
                    int(record.get("target_count") or 0),
                    record.get("provider"),
                    record.get("model"),
                    json.dumps(record.get("trends") or [], ensure_ascii=False),
                    json.dumps(record.get("keywords") or [], ensure_ascii=False),
                    json.dumps(record.get("comparison") or [], ensure_ascii=False),
                    json.dumps(record.get("implications") or [], ensure_ascii=False),
                    record.get("overview"),
                    record.get("raw_response"),
                ),
            )
        return int(cur.lastrowid)

    def get_analysis(self, analysis_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM analyses WHERE id = ?", (int(analysis_id),)).fetchone()
        return _analysis_row_to_dict(row) if row else None

    def latest_analysis(
        self, *, category: str | None = None, date_from: str | None = None, date_to: str | None = None
    ) -> dict[str, Any] | None:
        clauses, params = [], []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if date_from:
            clauses.append("IFNULL(date_from,'') >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("IFNULL(date_to,'9999-12-31') <= ?")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        row = self.conn.execute(
            f"SELECT * FROM analyses{where} ORDER BY id DESC LIMIT 1", params
        ).fetchone()
        return _analysis_row_to_dict(row) if row else None

    def list_analyses(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [_analysis_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------ 집계
    def category_counts(self, **filters) -> list[tuple[str, int]]:
        where, params = self._build_filters(**filters)
        rows = self.conn.execute(
            f"""SELECT IFNULL(NULLIF(TRIM(category),''), '미분류') AS k, COUNT(*) AS c
                FROM clean_news{where} GROUP BY k ORDER BY c DESC, k ASC""",
            params,
        ).fetchall()
        return [(r["k"], int(r["c"])) for r in rows]

    def daily_counts(self, *, date_field: str = "collected_date", **filters) -> list[tuple[str, int]]:
        where, params = self._build_filters(**filters)
        rows = self.conn.execute(
            f"""SELECT IFNULL({date_field}, '미상') AS k, COUNT(*) AS c
                FROM clean_news{where} GROUP BY k ORDER BY k ASC""",
            params,
        ).fetchall()
        return [(r["k"], int(r["c"])) for r in rows]

    def sentiment_counts(self, **filters) -> list[tuple[str, int]]:
        where, params = self._build_filters(**filters)
        rows = self.conn.execute(
            f"""SELECT sentiment AS k, COUNT(*) AS c FROM clean_news{where}
                {'AND' if where else 'WHERE'} sentiment IS NOT NULL AND TRIM(sentiment) <> ''
                GROUP BY k ORDER BY c DESC""",
            params,
        ).fetchall()
        return [(r["k"], int(r["c"])) for r in rows]

    def method_counts(self) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            """SELECT collect_method AS k, COUNT(*) AS c FROM clean_news
               GROUP BY k ORDER BY c DESC"""
        ).fetchall()
        return [(r["k"] or "미상", int(r["c"])) for r in rows]

    def aggregate_metrics(self, **filters) -> dict[str, Any]:
        """리포트용 품질 지표 집계."""
        where, params = self._build_filters(**filters)
        row = self.conn.execute(
            f"""SELECT
                    COUNT(*)                                                   AS total,
                    SUM(CASE WHEN summary IS NOT NULL AND TRIM(summary)<>'' THEN 1 ELSE 0 END) AS summarized,
                    SUM(CASE WHEN sentiment IS NOT NULL AND TRIM(sentiment)<>'' THEN 1 ELSE 0 END) AS sentimented,
                    SUM(CASE WHEN category IS NULL OR TRIM(category)='' OR category='미분류' THEN 1 ELSE 0 END) AS uncategorized,
                    SUM(CASE WHEN published_at IS NULL OR TRIM(published_at)='' THEN 1 ELSE 0 END) AS no_pubdate,
                    AVG(content_length)                                        AS avg_len,
                    MIN(content_length)                                        AS min_len,
                    MAX(content_length)                                        AS max_len,
                    AVG(summary_length)                                        AS avg_summary_len,
                    MIN(published_date)                                        AS first_date,
                    MAX(published_date)                                        AS last_date
                FROM clean_news{where}""",
            params,
        ).fetchone()
        return {k: row[k] for k in row.keys()}

    def top_articles(self, n: int = 5, **filters) -> list[sqlite3.Row]:
        return self.query_news(limit=n, order_by="content_length", order="DESC", **filters)

    # -------------------------------------------------------------- 실행 이력
    def log_fetch_run(self, record: dict[str, Any]) -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO fetch_runs
                   (started_at, finished_at, source, collect_method, requested, succeeded, failed, note)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.get("started_at"),
                    record.get("finished_at") or now_str(),
                    record.get("source"),
                    record.get("collect_method"),
                    int(record.get("requested") or 0),
                    int(record.get("succeeded") or 0),
                    int(record.get("failed") or 0),
                    record.get("note"),
                ),
            )
        return int(cur.lastrowid)


def _analysis_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = {k: row[k] for k in row.keys()}
    for field in ("trends", "keywords", "comparison", "implications"):
        try:
            data[field] = json.loads(data.get(field) or "[]")
        except (TypeError, json.JSONDecodeError):
            data[field] = []
    return data


def rows_to_dicts(rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in rows]
