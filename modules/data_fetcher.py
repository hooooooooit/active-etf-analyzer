"""
pykrx를 이용한 ETF 데이터 수집 모듈
[캐싱 지원: 한 번 조회한 데이터는 data/ 폴더에 저장하여 재사용]
"""
import time
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
from pykrx import stock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MAX_RETRIES, RETRY_DELAY, MIN_RETURNS_3M, TOP_N_RETURNS, LOOKBACK_DAYS, DATA_DIR

logger = logging.getLogger(__name__)


# ============================================================
# 캐시 유틸리티 함수
# ============================================================

def _get_cache_path(date: str, cache_type: str, suffix: str = None) -> Path:
    """캐시 파일 경로 생성"""
    DATA_DIR.mkdir(exist_ok=True)
    if suffix:
        return DATA_DIR / f"cache_{date}_{cache_type}_{suffix}.csv"
    return DATA_DIR / f"cache_{date}_{cache_type}.csv"


def _load_cache_csv(cache_path: Path) -> Optional[pd.DataFrame]:
    """CSV 캐시 파일 로드"""
    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path, encoding='utf-8-sig')
            logger.info(f"캐시 로드: {cache_path.name}")
            return df
        except Exception as e:
            logger.debug(f"캐시 로드 실패: {e}")
    return None


def _save_cache_csv(df: pd.DataFrame, cache_path: Path):
    """DataFrame을 CSV 캐시로 저장"""
    try:
        df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        logger.info(f"캐시 저장: {cache_path.name}")
    except Exception as e:
        logger.debug(f"캐시 저장 실패: {e}")


def _load_cache_json(cache_path: Path) -> Optional[dict]:
    """JSON 캐시 파일 로드"""
    json_path = cache_path.with_suffix('.json')
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"캐시 로드: {json_path.name}")
            return data
        except Exception as e:
            logger.debug(f"캐시 로드 실패: {e}")
    return None


def _save_cache_json(data: dict, cache_path: Path):
    """dict를 JSON 캐시로 저장"""
    json_path = cache_path.with_suffix('.json')
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"캐시 저장: {json_path.name}")
    except Exception as e:
        logger.debug(f"캐시 저장 실패: {e}")


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
    [캐싱 지원: 동일 날짜/설정의 결과 재사용]

    Args:
        min_returns: 최소 수익률 기준 (%)
        top_n: 수익률 상위 N개만 선택 (0이면 제한 없음)
        date: 조회 기준일 (YYYYMMDD). None이면 당일

    Returns:
        액티브 ETF 티커 리스트
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # [캐시 확인]
    cache_path = _get_cache_path(date, f"target_etfs_min{min_returns}_top{top_n}")
    cached_data = _load_cache_json(cache_path)
    if cached_data:
        logger.info(f"캐시에서 타겟 ETF 로드: {len(cached_data['tickers'])}개")
        # 캐시된 ETF 목록 출력
        for e in cached_data['etf_returns'][:10]:
            logger.info(f"  - {e['ticker']} {e['name']}: {e['returns_3m']:+.2f}%")
        if len(cached_data['etf_returns']) > 10:
            logger.info(f"  ... 외 {len(cached_data['etf_returns']) - 10}개")
        return cached_data['tickers']

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

    # [캐시 저장]
    _save_cache_json({
        'tickers': target_tickers,
        'etf_returns': etf_returns,
        'min_returns': min_returns,
        'top_n': top_n
    }, cache_path)

    return target_tickers


def get_etf_holdings(ticker: str, date: str = None) -> Optional[pd.DataFrame]:
    """
    개별 ETF의 구성 종목 및 비중 조회
    [캐싱 지원: 동일 날짜/티커의 구성종목 재사용]

    Args:
        ticker: ETF 티커
        date: 조회 기준일 (YYYYMMDD)

    Returns:
        구성 종목 DataFrame (종목코드, 종목명, 비중 등)
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # [캐시 확인]
    cache_path = _get_cache_path(date, "holdings", ticker)
    cached_df = _load_cache_csv(cache_path)
    if cached_df is not None and not cached_df.empty:
        return cached_df

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

        # [캐시 저장]
        _save_cache_csv(df, cache_path)

        return df

    except Exception as e:
        logger.error(f"{ticker} 구성종목 조회 실패: {e}")
        return None


def get_etf_info(tickers: List[str], date: str = None) -> pd.DataFrame:
    """
    ETF 기본 정보 조회 (수익률, 거래량 등)
    [캐싱 지원: 동일 날짜/티커 목록의 ETF 정보 재사용]

    Args:
        tickers: ETF 티커 리스트
        date: 조회 기준일

    Returns:
        ETF 정보 DataFrame
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # [캐시 확인 - 티커 목록의 해시를 사용]
    tickers_hash = hash(tuple(sorted(tickers))) % 100000
    cache_path = _get_cache_path(date, f"etf_info_{tickers_hash}")
    cached_df = _load_cache_csv(cache_path)
    if cached_df is not None and not cached_df.empty:
        # 캐시된 티커가 요청된 티커와 일치하는지 확인
        cached_tickers = set(cached_df['Ticker'].tolist())
        if set(tickers) == cached_tickers:
            return cached_df

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

    result_df = pd.DataFrame(etf_data)

    # [캐시 저장]
    if not result_df.empty:
        _save_cache_csv(result_df, cache_path)

    return result_df
