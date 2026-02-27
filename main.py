#!/usr/bin/env python3
"""
Active ETF Analyzer - 메인 실행 파일

KRX 상장 액티브 ETF의 구성 종목을 분석하고,
전일 대비 변동을 추적하여 PDF 리포트를 생성합니다.

[필터링 기준: 3개월 수익률 상위 ETF]
"""
import logging
import sys
from datetime import datetime
from typing import List
import pandas as pd

from config import TOP_N_RETURNS, MIN_RETURNS_3M, LOOKBACK_DAYS, ensure_directories
from modules.data_fetcher import get_target_etfs, get_etf_holdings, get_etf_info
from modules.analyzer import (
    load_previous_data,
    analyze_holdings,
    save_daily_data,
    get_top_holdings,
    get_top_changes,
    get_new_entries,
    get_exits
)
from modules.report_generator import generate_pdf


def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def main(date: str = None):
    """
    메인 실행 함수

    Args:
        date: 분석 기준일 (YYYYMMDD). None이면 당일
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    logger.info("=" * 60)
    logger.info(f"Active ETF Analyzer 시작 (기준일: {date})")
    logger.info("=" * 60)

    # [Step 0: 디렉토리 초기화]
    ensure_directories()

    # [Step 1: 전일 데이터 로드]
    logger.info("[Step 1] 전일 데이터 로드 중...")
    prev_df = load_previous_data(date)
    if prev_df is not None:
        logger.info(f"  - 전일 종목 수: {len(prev_df)}")
    else:
        logger.info("  - 전일 데이터 없음 (첫 실행 또는 파일 없음)")

    # [Step 2: 분석 대상 액티브 ETF 필터링]
    # 3개월 수익률 상위 ETF 선택
    logger.info(f"[Step 2] 액티브 ETF 필터링 중... ({LOOKBACK_DAYS}일 수익률 상위 {TOP_N_RETURNS}개)")
    target_tickers = get_target_etfs(min_returns=MIN_RETURNS_3M, top_n=TOP_N_RETURNS, date=date)

    if not target_tickers:
        logger.error("분석 대상 ETF가 없습니다. 프로그램을 종료합니다.")
        return

    logger.info(f"  - 분석 대상 ETF 수: {len(target_tickers)}")

    # [Step 3: ETF 기본 정보 조회]
    logger.info("[Step 3] ETF 기본 정보 조회 중...")
    etf_info = get_etf_info(target_tickers, date)
    logger.info(f"  - 조회된 ETF 수: {len(etf_info)}")

    # [Step 4: 구성 종목 수집]
    logger.info("[Step 4] ETF 구성 종목 수집 중...")
    holdings_list: List[pd.DataFrame] = []

    for i, ticker in enumerate(target_tickers, 1):
        logger.info(f"  - [{i}/{len(target_tickers)}] {ticker} 구성종목 조회...")
        holdings = get_etf_holdings(ticker, date)
        if holdings is not None and not holdings.empty:
            holdings_list.append(holdings)
            logger.info(f"    -> {len(holdings)}개 종목")

    if not holdings_list:
        logger.error("구성종목 데이터를 수집할 수 없습니다.")
        return

    # [Step 5: 분석 수행]
    logger.info("[Step 5] 분석 수행 중...")
    consensus_df, diff_df = analyze_holdings(holdings_list, prev_df)

    if consensus_df.empty:
        logger.error("분석 결과가 비어있습니다.")
        return

    # [분석 결과 요약 출력]
    logger.info("-" * 40)
    logger.info("[ 분석 결과 요약 ]")
    logger.info(f"  - 총 종목 수: {len(consensus_df)}")

    top_holdings = get_top_holdings(consensus_df, 5)
    logger.info("  - 보유 비중 Top 5:")
    for _, row in top_holdings.iterrows():
        logger.info(f"    {row['StockName']}: {row['TotalWeight']:.2f}%")

    if not diff_df.empty:
        new_entries = get_new_entries(diff_df)
        exits = get_exits(diff_df)
        logger.info(f"  - 신규 편입: {len(new_entries)}개")
        logger.info(f"  - 제외: {len(exits)}개")

    # [Step 6: PDF 리포트 생성]
    logger.info("[Step 6] PDF 리포트 생성 중...")
    pdf_path = generate_pdf(etf_info, consensus_df, diff_df, date)
    logger.info(f"  - PDF 저장: {pdf_path}")

    # [Step 7: 당일 데이터 저장 (다음 날 비교용)]
    logger.info("[Step 7] 당일 데이터 저장 중...")
    data_path = save_daily_data(consensus_df, date)
    logger.info(f"  - 데이터 저장: {data_path}")

    logger.info("=" * 60)
    logger.info("Active ETF Analyzer 완료!")
    logger.info("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Active ETF Analyzer')
    parser.add_argument(
        '--date', '-d',
        type=str,
        default=None,
        help='분석 기준일 (YYYYMMDD). 기본값: 당일'
    )
    parser.add_argument(
        '--top-n',
        type=int,
        default=None,
        help=f'수익률 상위 N개 ETF 선택. 기본값: {TOP_N_RETURNS}'
    )
    parser.add_argument(
        '--min-returns',
        type=float,
        default=None,
        help=f'최소 수익률 기준 (%). 기본값: {MIN_RETURNS_3M}'
    )

    args = parser.parse_args()

    # [설정 오버라이드]
    if args.top_n is not None:
        import config
        config.TOP_N_RETURNS = args.top_n

    if args.min_returns is not None:
        import config
        config.MIN_RETURNS_3M = args.min_returns

    main(args.date)
