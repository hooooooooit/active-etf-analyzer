"""
Active ETF Analyzer 설정 파일
"""
import os
from pathlib import Path

# [기본 경로 설정]
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"

# [필터링 설정]
MIN_RETURNS_3M = 0  # 3개월 수익률 하한선 (%). 0이면 모든 양수 수익률
TOP_N_RETURNS = 20  # 3개월 수익률 상위 N개 ETF만 분석 (0이면 제한 없음)
LOOKBACK_DAYS = 90  # 수익률 계산 기간 (일)

# [재시도 설정]
MAX_RETRIES = 3  # API 호출 최대 재시도 횟수
RETRY_DELAY = 1  # 재시도 간 대기 시간 (초)

# [리포트 설정]
TOP_N = 10  # 상위 N개 종목 표시

# [한글 폰트 설정 (matplotlib용)]
FONT_CANDIDATES = [
    "NanumGothic",
    "Malgun Gothic",
    "AppleGothic",
    "DejaVu Sans"
]

def ensure_directories():
    """필요한 디렉토리가 없으면 생성"""
    DATA_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
