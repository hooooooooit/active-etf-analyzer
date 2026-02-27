"""
pykrx를 이용한 ETF 데이터 수집 모듈
"""
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
from pykrx import stock

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
from config import MAX_RETRIES, RETRY_DELAY, MIN_RETURNS_3M, TOP_N_RETURNS, LOOKBACK_DAYS

logger = logging.getLogger(__name__)


def _retry_api_call(func, *args, **kwargs):
    """
    [API 호출 재시도 로직]
    네트워크 오류나 일시적 장애에 대비하여 최대 MAX_RETRIES회 재시도
    """
    for attempt in range(MAX_RETRIES):
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.warning(f"API 호출 실패 (시도 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise


def get_target_etfs(
    min_returns: float = MIN_RETURNS_3M,
    top_n: int = TOP_N_RETURNS,
    date: str = None
) -> List[str]:
    """
    분석 대상 액티브 ETF 티커 목록 추출
    [3개월 수익률 기준 필터링 - 최적화 버전]

    Args:
        min_returns: 최소 수익률 기준 (%)
        top_n: 수익률 상위 N개만 선택 (0이면 제한 없음)
        date: 조회 기준일 (YYYYMMDD). None이면 당일

    Returns:
        액티브 ETF 티커 리스트
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    logger.info(f"ETF 티커 목록 조회 중... (기준일: {date})")

    # [Step 1] 전체 ETF 티커 목록 획득
    all_tickers = _retry_api_call(stock.get_etf_ticker_list, date)
    logger.info(f"전체 ETF 수: {len(all_tickers)}")

    # [Step 2] '액티브' 이름 필터링
    active_tickers = {}
    for ticker in all_tickers:
        try:
            name = stock.get_etf_ticker_name(ticker)
            if "액티브" in name:
                active_tickers[ticker] = name
        except Exception:
            continue

    logger.info(f"액티브 ETF 수: {len(active_tickers)}")

    # [Step 3] 한 번에 모든 ETF의 N일 수익률 조회 (최적화)]
    end_dt = datetime.strptime(date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    start_date = start_dt.strftime("%Y%m%d")

    logger.info(f"수익률 조회 중... ({start_date} ~ {date})")

    try:
        # [get_etf_price_change_by_ticker로 전체 ETF 수익률 한 번에 조회]
        price_change_df = _retry_api_call(
            stock.get_etf_price_change_by_ticker, start_date, date
        )
        logger.info(f"수익률 데이터 조회 완료: {len(price_change_df)}개 ETF")
    except Exception as e:
        logger.error(f"수익률 데이터 조회 실패: {e}")
        return []

    # [Step 4] 액티브 ETF만 필터링하고 수익률 정렬
    etf_returns = []
    for ticker, name in active_tickers.items():
        if ticker in price_change_df.index:
            returns = price_change_df.loc[ticker, '등락률']
            etf_returns.append({
                'ticker': ticker,
                'name': name,
                'returns_3m': round(returns, 2)
            })

    # [수익률 기준 정렬 (내림차순)]
    etf_returns.sort(key=lambda x: x['returns_3m'], reverse=True)

    # [최소 수익률 필터링]
    if min_returns > 0:
        etf_returns = [e for e in etf_returns if e['returns_3m'] >= min_returns]
        logger.info(f"수익률 >= {min_returns}% 필터 후: {len(etf_returns)}개")

    # [상위 N개 선택]
    if top_n > 0 and len(etf_returns) > top_n:
        etf_returns = etf_returns[:top_n]
        logger.info(f"상위 {top_n}개 선택")

    target_tickers = [e['ticker'] for e in etf_returns]

    logger.info(f"분석 대상 액티브 ETF 수: {len(target_tickers)}")

    # [선택된 ETF 목록 출력]
    for e in etf_returns[:10]:
        logger.info(f"  - {e['ticker']} {e['name']}: {e['returns_3m']:+.2f}%")
    if len(etf_returns) > 10:
        logger.info(f"  ... 외 {len(etf_returns) - 10}개")

    return target_tickers


def get_etf_holdings(ticker: str, date: str = None) -> Optional[pd.DataFrame]:
    """
    개별 ETF의 구성 종목 및 비중 조회

    Args:
        ticker: ETF 티커
        date: 조회 기준일 (YYYYMMDD)

    Returns:
        구성 종목 DataFrame (종목코드, 종목명, 비중 등)
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    try:
        # [PDF(구성종목) 데이터 조회]
        df = _retry_api_call(stock.get_etf_portfolio_deposit_file, ticker, date)

        if df is None or df.empty:
            logger.warning(f"{ticker}: 구성종목 데이터 없음")
            return None

        # [ETF 티커 정보 추가]
        df['ETF_Ticker'] = ticker
        df['ETF_Name'] = stock.get_etf_ticker_name(ticker)

        # [인덱스(티커)를 컬럼으로 변환]
        df = df.reset_index()
        if 'index' in df.columns:
            df = df.rename(columns={'index': '종목코드'})

        return df

    except Exception as e:
        logger.error(f"{ticker} 구성종목 조회 실패: {e}")
        return None


def get_etf_info(tickers: List[str], date: str = None) -> pd.DataFrame:
    """
    ETF 기본 정보 조회 (수익률, 거래량 등)

    Args:
        tickers: ETF 티커 리스트
        date: 조회 기준일

    Returns:
        ETF 정보 DataFrame
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # [수익률 데이터 미리 조회]
    end_dt = datetime.strptime(date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    start_date = start_dt.strftime("%Y%m%d")

    try:
        price_change_df = _retry_api_call(
            stock.get_etf_price_change_by_ticker, start_date, date
        )
    except Exception:
        price_change_df = pd.DataFrame()

    etf_data = []

    for ticker in tickers:
        try:
            name = stock.get_etf_ticker_name(ticker)
            ohlcv = _retry_api_call(stock.get_etf_ohlcv_by_date, date, date, ticker)

            if ohlcv.empty:
                continue

            row = ohlcv.iloc[-1]

            # [당일 등락률 계산: (종가 - 시가) / 시가 * 100]
            change_pct = ((row['종가'] - row['시가']) / row['시가'] * 100) if row['시가'] > 0 else 0

            # [3개월 수익률]
            returns_3m = 0
            if ticker in price_change_df.index:
                returns_3m = round(price_change_df.loc[ticker, '등락률'], 2)

            etf_data.append({
                'Ticker': ticker,
                'Name': name,
                'Close': row['종가'],
                'NAV': row.get('NAV', row['종가']),
                'Volume': row['거래량'],
                'TradingValue': row.get('거래대금', 0),
                'Change_Pct': round(change_pct, 2),
                'Returns_3M': returns_3m
            })

        except Exception as e:
            logger.debug(f"{ticker} 정보 조회 실패: {e}")
            continue

    return pd.DataFrame(etf_data)
