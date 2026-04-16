"""
Active ETF Analyzer 설정 파일
"""
import os
from pathlib import Path

# [.env 자동 로드 — 있으면 사용, 없으면 무시]
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# [기본 경로]
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# [대상 ETF 동적 선정]
# TIME / KoAct 각 AUM 상위 N개 + 나머지 전체 AUM 상위 N개 (중복 제외)
PRIORITY_MANAGERS = ['TIME', 'KoAct']   # 우선 운용사 (각각 N개씩)
TOP_N_PER_MANAGER = 5                   # 우선 운용사당 AUM 상위 N개
TOP_N_OTHER = 5                         # 나머지 전체에서 AUM 상위 N개 (우선 운용사와 중복 제외)

# 채권/금리/MMF 계열 '액티브' ETF 제외 키워드 (구성종목 diff가 의미 있는 equity 계열만)
EXCLUDE_KEYWORDS = [
    '금리', '채권', '머니마켓', '국채', '국고채', '회사채',
    '금융채', '단기채', '특수은행채', '은행채', 'CD', 'KOFR', 'MMF',
    '커버드콜',
]

# [분석 파라미터]
COMMON_SIGNAL_MIN_ETFS = 3     # N개 이상 ETF에서 동시 매수/신규 편입 시 공통 시그널
MAX_CHANGES_PER_ETF = 5        # ETF당 표시할 최대 변화 종목 수 (카테고리별)
NEW_LISTING_TOP_N = 10         # 신규 상장 ETF 섹션에 표시할 상위 종목 수

# [재시도 설정]
MAX_RETRIES = 3                # API 호출 최대 재시도 횟수
RETRY_DELAY = 1                # 재시도 간 대기 시간 (초)

# [KRX 로그인 — ETF/ETN/ELW API는 인증 필수]
# https://data.krx.co.kr 계정이 필요합니다. .env에 설정할 것
KRX_USER_ID = os.getenv("KRX_USER_ID", "")
KRX_PASSWORD = os.getenv("KRX_PASSWORD", "")

# [Slack Incoming Webhook]
# https://api.slack.com/messaging/webhooks 에서 생성한 URL을 .env에 설정
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def ensure_directories():
    """필요한 디렉토리 생성"""
    DATA_DIR.mkdir(exist_ok=True)
