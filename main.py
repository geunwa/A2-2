"""NewsBot CLI 진입점.

사용법:
    python main.py --help
    python main.py fetch --source yna --method all --limit 20
    python main.py clean --on-duplicate skip
    python main.py summarize --unsummarized --limit 10
    python main.py analyze --date-from 2026-08-01 --date-to 2026-08-18 --category 경제
    python main.py report --format md
    python main.py export --format csv --status summarized
"""

import sys

from newsbot.cli import main

if __name__ == "__main__":
    sys.exit(main())
