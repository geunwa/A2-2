"""AI 연동 패키지.

- ``client.py``     : 제공자(Gemini/OpenAI/Anthropic) 공통 호출 계층 + 오프라인 mock 판별
- ``mock.py``       : API 키가 없을 때 쓰는 규칙 기반 대체 구현(오프라인 데모용)
- ``summarizer.py`` : 뉴스 본문 요약
- ``analyzer.py``   : 기간/카테고리 종합 인사이트 분석
- ``sentiment.py``  : 감성 분석 (보너스)
"""

from .client import AIClient, AIError
from .summarizer import Summarizer
from .analyzer import Analyzer
from .sentiment import SentimentAnalyzer

__all__ = ["AIClient", "AIError", "Summarizer", "Analyzer", "SentimentAnalyzer"]
