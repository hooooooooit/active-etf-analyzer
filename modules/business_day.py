"""
영업일 탐색 유틸리티

pykrx API는 휴일(주말/공휴일)에 빈 DataFrame을 반환하므로,
대표 ETF 하나로 OHLCV 조회를 시도해 데이터 유무로 영업일을 판정한다.
"""
import logging
from datetime import datetime, timedelta
from typing import List

from pykrx import stock

logger = logging.getLogger(__name__)

# 영업일 판정용 대표 티커 (KoAct AI인프라액티브 — 유동성 충분)
_PROBE_TICKER = "487130"
# 최대 역탐색 일수 (연속 휴일 대비)
_MAX_LOOKBACK_DAYS = 14


def is_business_day(date: str) -> bool:
    """해당 날짜에 거래가 있었는지 판정.

    Args:
        date: YYYYMMDD

    Returns:
        True = 영업일, False = 휴일 또는 미래일
    """
    try:
        df = stock.get_etf_ohlcv_by_date(date, date, _PROBE_TICKER)
        return df is not None and not df.empty
    except Exception as e:
        logger.debug(f"is_business_day({date}) 판정 실패: {e}")
        return False


def get_recent_business_days(ref_date: str, n: int = 2) -> List[str]:
    """ref_date 이전(미포함)의 최근 n개 영업일을 YYYYMMDD 리스트로 반환.

    예: ref_date='20260306'(금) → ['20260305'(목), '20260304'(수)]
        ref_date='20260302'(월) → ['20260227'(금), '20260226'(목)] — 주말 건너뜀

    Args:
        ref_date: 기준일 (이 날짜 자체는 포함하지 않음)
        n: 필요한 영업일 개수

    Returns:
        최근 영업일 리스트 (최신순). 부족하면 빈 리스트.
    """
    ref_dt = datetime.strptime(ref_date, "%Y%m%d")
    found: List[str] = []

    for days_back in range(1, _MAX_LOOKBACK_DAYS + 1):
        candidate = ref_dt - timedelta(days=days_back)

        # 주말 사전 필터 (API 호출 절약)
        if candidate.weekday() >= 5:
            continue

        candidate_str = candidate.strftime("%Y%m%d")
        if is_business_day(candidate_str):
            found.append(candidate_str)
            logger.debug(f"영업일 확인: {candidate_str}")
            if len(found) >= n:
                return found

    logger.warning(
        f"{ref_date} 기준 최근 {n}개 영업일을 찾지 못함 "
        f"(lookback {_MAX_LOOKBACK_DAYS}일, 발견 {len(found)}개)"
    )
    return []
