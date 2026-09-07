"""argparse 기반 서브커맨드 CLI.

    fetch     뉴스 수집 (RSS + 크롤링) → raw 저장
    clean     정제 + 중복 처리       → clean 저장
    summarize AI 요약
    analyze   AI 인사이트 분석
    report    품질 지표 · TOP N · 인사이트 리포트 + 차트
    export    CSV / JSONL / Excel 내보내기
    list      뉴스 목록 조회 (필터 + 페이지네이션)   [보너스]
    show      뉴스 상세 조회                          [보너스]
    sentiment 감성 분석                               [보너스]
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .ai.analyzer import Analyzer, format_analysis
from .ai.client import AIClient, AIError
from .ai.sentiment import SentimentAnalyzer
from .ai.summarizer import Summarizer
from .cleaner import Cleaner
from .collectors import CrawlCollector, HttpClient, RssCollector
from .collectors.base import CollectResult
from .config import Config, ConfigError, load_config
from .exporter import Exporter
from .logger import get_logger, setup_logging
from .report import ReportBuilder
from .storage import Storage
from .utils import now_kst, truncate, validate_date_arg
from .visualize import generate_charts

log = get_logger("cli")

METHODS = ("rss", "crawl", "all")


# ====================================================================== 파서
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="NewsBot - 뉴스 수집 · AI 요약 · 인사이트 분석 · 리포트 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python main.py fetch --source yna --method all --limit 20\n"
            "  python main.py clean --on-duplicate upsert\n"
            "  python main.py summarize --unsummarized --limit 10\n"
            "  python main.py analyze --date-from 2026-08-01 --date-to 2026-08-18 --category 경제\n"
            "  python main.py report --format md\n"
            "  python main.py export --format csv --status summarized\n"
        ),
    )
    parser.add_argument("--config", help="설정 파일 경로 (기본: config.json)")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="로그 레벨 (기본: 설정 파일 값)")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ------------------------------------------------------------- fetch
    p = sub.add_parser("fetch", help="뉴스 수집 (RSS/크롤링) 후 raw 저장소에 적재")
    p.add_argument("--source", help="뉴스 소스 키 (config.json 의 sources, 기본: sources.default)")
    p.add_argument("--method", choices=METHODS, default="all",
                   help="수집 방법: rss(피드) | crawl(크롤링) | all(둘 다, 기본)")
    p.add_argument("--category", action="append",
                   help="카테고리 (여러 번 지정 가능, 쉼표 구분도 허용)")
    p.add_argument("--limit", type=int, default=20, help="수집 방법별 최대 기사 수 (기본 20)")
    p.add_argument("--no-content", action="store_true",
                   help="RSS 수집 시 본문 페이지를 추가로 받지 않음(빠르지만 본문이 요약문 수준)")
    p.add_argument("--delay", type=float, help="요청 간 최소 지연(초). 설정값을 덮어씀")
    p.add_argument("--auto-clean", action="store_true", help="수집 직후 정제까지 이어서 실행")
    p.add_argument("--list-categories", action="store_true", help="사용 가능한 카테고리만 출력")
    p.set_defaults(func=cmd_fetch)

    # ------------------------------------------------------------- clean
    p = sub.add_parser("clean", help="raw → clean 정제 (검증/정규화/중복 처리)")
    p.add_argument("--limit", type=int, help="처리할 raw 최대 건수")
    p.add_argument("--on-duplicate", choices=["skip", "upsert"],
                   help="중복 정책 (기본: 설정 cleaning.on_duplicate)")
    p.add_argument("--reprocess", action="store_true",
                   help="이미 처리한 raw 도 다시 정제 (정제 규칙 변경 시 사용)")
    p.set_defaults(func=cmd_clean)

    # --------------------------------------------------------- summarize
    p = sub.add_parser("summarize", help="AI 요약 생성")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true", help="전체 뉴스 대상")
    target.add_argument("--id", type=int, help="특정 뉴스 ID 하나만")
    target.add_argument("--unsummarized", action="store_true",
                        help="아직 요약되지 않은 뉴스만 (기본)")
    p.add_argument("--limit", type=int, help="최대 처리 건수")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--max-chars", type=int, help="요약 최대 글자 수")
    p.add_argument("--force", action="store_true", help="이미 요약된 뉴스도 다시 요약")
    p.add_argument("--dry-run", action="store_true", help="대상만 확인하고 API 는 호출하지 않음")
    p.add_argument("--provider", help="AI 제공자 강제 지정 (gemini/openai/anthropic/mock)")
    p.set_defaults(func=cmd_summarize)

    # ----------------------------------------------------------- analyze
    p = sub.add_parser("analyze", help="기간/카테고리 종합 AI 인사이트 분석")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--keyword", help="제목/본문 키워드 필터")
    p.add_argument("--limit", type=int, help="분석에 사용할 최대 기사 수")
    p.add_argument("--no-save", action="store_true", help="결과를 DB에 저장하지 않음")
    p.add_argument("--provider", help="AI 제공자 강제 지정")
    p.add_argument("--history", type=int, metavar="N",
                   help="분석하지 않고 최근 N건의 분석 이력만 출력")
    p.set_defaults(func=cmd_analyze)

    # ------------------------------------------------------------ report
    p = sub.add_parser("report", help="품질 지표/TOP N/AI 인사이트 리포트 생성")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--top", type=int, help="TOP N 개수 (기본: 설정 report.top_n)")
    p.add_argument("--format", choices=["md", "txt"], help="리포트 파일 형식 (기본: 설정값)")
    p.add_argument("--output", help="리포트 저장 경로")
    p.add_argument("--no-charts", action="store_true", help="차트 생성 생략")
    p.add_argument("--no-file", action="store_true", help="파일 저장 없이 콘솔 출력만")
    p.set_defaults(func=cmd_report)

    # ------------------------------------------------------------ export
    p = sub.add_parser("export", help="CSV / JSONL / Excel 내보내기")
    p.add_argument("--format", choices=["csv", "jsonl", "excel", "all"], default="csv",
                   help="출력 포맷 (기본 csv)")
    p.add_argument("--status", choices=["all", "summarized", "unsummarized"], default="all",
                   help="상태 필터 (기본 all)")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--keyword", help="키워드 필터")
    p.add_argument("--limit", type=int, help="최대 건수")
    p.add_argument("--output", help="저장 경로 (단일 포맷일 때만)")
    p.set_defaults(func=cmd_export)

    # -------------------------------------------------------------- list
    p = sub.add_parser("list", help="[보너스] 뉴스 목록 조회 (필터 + 페이지네이션)")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--keyword", help="제목/본문/요약 키워드")
    p.add_argument("--status", choices=["all", "summarized", "unsummarized"], default="all")
    p.add_argument("--page", type=int, default=1, help="페이지 번호 (1부터)")
    p.add_argument("--page-size", type=int, default=10, help="페이지당 건수 (기본 10)")
    p.set_defaults(func=cmd_list)

    # -------------------------------------------------------------- show
    p = sub.add_parser("show", help="[보너스] 뉴스 상세 조회")
    p.add_argument("id", type=int, help="뉴스 ID")
    p.add_argument("--full", action="store_true", help="본문 전체 출력")
    p.set_defaults(func=cmd_show)

    # --------------------------------------------------------- sentiment
    p = sub.add_parser("sentiment", help="[보너스] AI 감성 분석 (긍정/부정/중립)")
    p.add_argument("--id", type=int, help="특정 뉴스 ID")
    p.add_argument("--limit", type=int, help="최대 처리 건수")
    p.add_argument("--category", help="카테고리 필터")
    _add_date_options(p)
    p.add_argument("--force", action="store_true", help="이미 분석된 뉴스도 다시 분석")
    p.add_argument("--provider", help="AI 제공자 강제 지정")
    p.set_defaults(func=cmd_sentiment)

    return parser


def _add_date_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date-from", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="종료일 (YYYY-MM-DD)")
    parser.add_argument("--date", help="특정 하루만 (YYYY-MM-DD). --date-from/--date-to 를 덮어씀")


# ================================================================== 헬퍼
def _resolve_dates(args: argparse.Namespace) -> tuple[str | None, str | None]:
    date = getattr(args, "date", None)
    if date:
        one = validate_date_arg(date, field="--date")
        return one, one
    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)
    return (
        validate_date_arg(date_from, field="--date-from") if date_from else None,
        validate_date_arg(date_to, field="--date-to") if date_to else None,
    )


def _split_categories(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out or None


def _open_storage(config: Config) -> Storage:
    return Storage(config.path("paths.db", mkdir=True))


def _make_ai_client(config: Config, args: argparse.Namespace) -> AIClient:
    return AIClient(config, provider=getattr(args, "provider", None))


# ================================================================== 명령 구현
def cmd_fetch(args: argparse.Namespace, config: Config) -> int:
    source_cfg = config.source(getattr(args, "source", None))
    categories = _split_categories(args.category)

    if args.list_categories:
        cats = list(source_cfg.get("categories", {}).keys())
        rss_only = source_cfg.get("rss_only_categories", [])
        print(f"[{source_cfg.get('name')}] 사용 가능한 카테고리")
        for name in cats:
            note = " (RSS 전용)" if name in rss_only else ""
            print(f"  - {name}{note}")
        print(f"\n기본 카테고리: {', '.join(source_cfg.get('default_categories', []))}")
        return 0

    http = HttpClient.from_config(config)
    if args.delay is not None:
        http.request_delay_sec = max(0.0, float(args.delay))

    methods = ["rss", "crawl"] if args.method == "all" else [args.method]
    started = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    log.info("뉴스 수집 시작: source=%s, method=%s, limit=%d, 카테고리=%s",
             source_cfg["key"], args.method, args.limit,
             ", ".join(categories or source_cfg.get("default_categories", [])) or "기본값")

    merged = CollectResult(method=args.method, source=source_cfg["key"])
    with http, _open_storage(config) as storage:
        for method in methods:
            collector = (
                RssCollector(config, http, source_cfg["key"]) if method == "rss"
                else CrawlCollector(config, http, source_cfg["key"])
            )
            try:
                result = collector.collect(
                    categories, args.limit, with_content=not args.no_content
                )
            except Exception as exc:
                log.error("[%s] 수집 중 오류: %s", method, exc)
                merged.add_error(f"{method}: {exc}")
                continue

            for record in result.records:
                storage.insert_raw(record)
            storage.log_fetch_run({
                "started_at": started, "source": source_cfg["key"], "collect_method": method,
                "requested": args.limit, "succeeded": result.succeeded, "failed": result.failed,
                "note": "; ".join(result.errors[:5]) or None,
            })
            merged.merge(result)

        log.info("수집 완료: %d건 성공, %d건 실패", merged.succeeded, merged.failed)
        log.info("raw 저장소에 저장 완료 (누적 %d건)", storage.count_raw())

        if merged.failed:
            log.warning("실패 사유 일부: %s", "; ".join(merged.errors[:3]))

        if args.auto_clean:
            log.info("--auto-clean: 정제 단계로 이어집니다.")
            Cleaner(config, storage).run()

    return 0 if merged.succeeded else 1


def cmd_clean(args: argparse.Namespace, config: Config) -> int:
    with _open_storage(config) as storage:
        stats = Cleaner(config, storage).run(
            limit=args.limit, on_duplicate=args.on_duplicate, reprocess=args.reprocess
        )
    return 0 if (stats.total == 0 or stats.inserted or stats.updated or stats.duplicated) else 1


def cmd_summarize(args: argparse.Namespace, config: Config) -> int:
    date_from, date_to = _resolve_dates(args)
    mode = "all" if args.all else ("id" if args.id is not None else "unsummarized")

    with _open_storage(config) as storage:
        client = _make_ai_client(config, args)
        stats = Summarizer(config, storage, client).run(
            mode=mode, news_id=args.id, limit=args.limit, category=args.category,
            date_from=date_from, date_to=date_to, force=args.force,
            max_chars=args.max_chars, dry_run=args.dry_run,
        )
    return 0 if stats.failed == 0 else 1


def cmd_analyze(args: argparse.Namespace, config: Config) -> int:
    with _open_storage(config) as storage:
        if args.history:
            rows = storage.list_analyses(args.history)
            if not rows:
                print("저장된 분석 결과가 없습니다.")
                return 0
            print(f"최근 분석 이력 {len(rows)}건")
            for item in rows:
                print(f"  [{item['id']}] {item['created_at']} | "
                      f"{item['date_from'] or '-'}~{item['date_to'] or '-'} | "
                      f"{item['category'] or '전체'} | {item['target_count']}건 | {item['model']}")
            return 0

        date_from, date_to = _resolve_dates(args)
        client = _make_ai_client(config, args)
        result = Analyzer(config, storage, client).run(
            date_from=date_from, date_to=date_to, category=args.category,
            keyword=args.keyword, limit=args.limit, save=not args.no_save,
        )

    if result is None:
        return 1
    print()
    print(format_analysis(result))
    print()
    return 0


def cmd_report(args: argparse.Namespace, config: Config) -> int:
    date_from, date_to = _resolve_dates(args)
    filters = {"date_from": date_from, "date_to": date_to, "category": args.category}

    with _open_storage(config) as storage:
        if storage.count_news(**filters) == 0:
            log.warning("조건에 맞는 뉴스가 없습니다. 먼저 fetch/clean 을 실행하세요.")
            return 1

        charts: dict[str, Any] = {}
        if not args.no_charts and config.get("report.include_charts", True):
            log.info("차트 생성 중...")
            charts = generate_charts(
                config, storage, prefix=now_kst().strftime("%Y%m%d_%H%M%S"), **filters
            )

        analysis = storage.latest_analysis(category=args.category)
        builder = ReportBuilder(config, storage)
        data = builder.build(
            date_from=date_from, date_to=date_to, category=args.category,
            top_n=args.top, charts=charts, analysis=analysis,
        )

        fmt = (args.format or config.get("report.format", "md")).lower()
        print()
        print(builder.render(data, "txt"))
        print()
        if not args.no_file:
            builder.save(data, fmt, args.output)
    return 0


def cmd_export(args: argparse.Namespace, config: Config) -> int:
    date_from, date_to = _resolve_dates(args)
    status = None if args.status == "all" else args.status

    with _open_storage(config) as storage:
        paths = Exporter(config, storage).export(
            args.format, output=args.output, status=status, category=args.category,
            date_from=date_from, date_to=date_to, keyword=args.keyword, limit=args.limit,
        )
    if not paths:
        return 1
    for path in paths:
        print(f"저장됨: {path}")
    return 0


def cmd_list(args: argparse.Namespace, config: Config) -> int:
    date_from, date_to = _resolve_dates(args)
    status = None if args.status == "all" else args.status
    page = max(1, args.page)
    page_size = max(1, args.page_size)
    filters = {
        "category": args.category, "date_from": date_from, "date_to": date_to,
        "keyword": args.keyword, "status": status,
    }

    with _open_storage(config) as storage:
        total = storage.count_news(**filters)
        rows = storage.query_news(limit=page_size, offset=(page - 1) * page_size, **filters)

    if total == 0:
        print("조건에 맞는 뉴스가 없습니다.")
        return 0

    last_page = (total + page_size - 1) // page_size
    print(f"\n총 {total:,}건 | {page}/{last_page} 페이지 (페이지당 {page_size}건)")
    print("-" * 92)
    print(f"{'ID':>5} {'발행일':<11} {'카테고리':<8} {'요약':<4} {'감성':<4} 제목")
    print("-" * 92)
    for row in rows:
        summarized = "O" if (row["summary"] or "").strip() else "-"
        sentiment = (row["sentiment"] or "-")[:2]
        print(f"{row['id']:>5} {(row['published_date'] or '-'):<11} "
              f"{(row['category'] or '-'):<8} {summarized:^4} {sentiment:^4} "
              f"{truncate(row['title'] or '', 46)}")
    print("-" * 92)
    if page < last_page:
        print(f"다음 페이지: --page {page + 1}")
    return 0


def cmd_show(args: argparse.Namespace, config: Config) -> int:
    with _open_storage(config) as storage:
        row = storage.get_news(args.id)
    if row is None:
        log.error("ID=%s 뉴스를 찾을 수 없습니다.", args.id)
        return 1

    content = row["content"] or ""
    print()
    print("=" * 76)
    print(f" [{row['id']}] {row['title']}")
    print("=" * 76)
    print(f" 카테고리 : {row['category']}")
    print(f" 소스     : {row['source_name']} ({row['collect_method']})")
    print(f" 기자     : {row['author']}")
    print(f" 발행일   : {row['published_at']}")
    print(f" 수집일   : {row['collected_at']}")
    print(f" URL      : {row['url']}")
    print(f" 본문길이 : {row['content_length']:,}자")
    if (row["summary"] or "").strip():
        print("-" * 76)
        print(f" [AI 요약] ({row['summary_model']}, {row['summary_length']}자)")
        print(f" {row['summary']}")
    if (row["sentiment"] or "").strip():
        print("-" * 76)
        print(f" [감성] {row['sentiment']} (score={row['sentiment_score']}) - {row['sentiment_reason']}")
    print("-" * 76)
    print(" [본문]")
    print(content if args.full else truncate(content, 600))
    print("=" * 76)
    print()
    return 0


def cmd_sentiment(args: argparse.Namespace, config: Config) -> int:
    date_from, date_to = _resolve_dates(args)
    with _open_storage(config) as storage:
        client = _make_ai_client(config, args)
        stats = SentimentAnalyzer(config, storage, client).run(
            news_id=args.id, limit=args.limit, category=args.category,
            date_from=date_from, date_to=date_to, force=args.force,
        )
    return 0 if stats.failed == 0 else 1


# ====================================================================== 진입점
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    setup_logging(
        level=args.log_level or config.get("logging.level", "INFO"),
        log_file=config.path("logging.file", mkdir=True) if config.get("logging.file") else None,
        console=bool(config.get("logging.console", True)),
        max_bytes=int(config.get("logging.max_bytes", 2_000_000)),
        backup_count=int(config.get("logging.backup_count", 3)),
    )

    try:
        return int(args.func(args, config) or 0)
    except KeyboardInterrupt:
        log.warning("사용자 중단(Ctrl+C)")
        return 130
    except (ConfigError, ValueError) as exc:
        log.error("%s", exc)
        return 2
    except AIError as exc:
        log.error("AI 오류: %s", exc)
        return 3
    except Exception as exc:  # 예기치 못한 오류도 로그로 남긴다
        log.exception("예기치 못한 오류: %s", exc)
        return 1
