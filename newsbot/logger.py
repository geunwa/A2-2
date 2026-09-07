"""로깅 설정 모듈.

- 콘솔: `[INFO] 메시지` 형태로 간결하게 (과제 예시 출력 형식)
- 파일: 시각 / 모듈 / 레벨까지 남기는 상세 포맷 (RotatingFileHandler)
- INFO / WARNING / ERROR 세 레벨을 모두 사용한다.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOGGER_NAME = "newsbot"

_CONSOLE_FORMAT = "[%(levelname)s] %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def _force_utf8_stdout() -> None:
    """Windows 콘솔에서 한글/기호가 깨지지 않도록 표준 출력을 UTF-8 로 맞춘다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # 리다이렉션된 스트림 등
                pass


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    console: bool = True,
    max_bytes: int = 2_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """애플리케이션 루트 로거를 구성해 돌려준다. 재호출해도 핸들러가 중복되지 않는다."""
    _force_utf8_stdout()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if console:
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(logger.level)
        ch.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        logger.addHandler(ch)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)  # 파일에는 더 자세히 남긴다
        fh.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(fh)

    # 서드파티 라이브러리의 잡음 억제
    for noisy in ("urllib3", "matplotlib", "matplotlib.font_manager", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """`newsbot.<name>` 하위 로거를 돌려준다."""
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
