#!/usr/bin/env python3
"""
Active ETF Analyzer — Slack 자동 알림

고정 ETF 목록에 대해 최근 영업일(D-1) vs 전전 영업일(D-2)의
구성종목 비중 변화를 계산하여 Slack Incoming Webhook으로 전송한다.

휴일(장이 쉬는 날)에 실행되면 조용히 exit 0.
"""
import argparse
import json
import logging
import sys
from datetime import datetime

from config import (
    SLACK_WEBHOOK_URL,
    COMMON_SIGNAL_MIN_ETFS,
    ensure_directories,
)
from modules.business_day import get_recent_business_days
from modules.data_fetcher import (
    get_etf_holdings,
    select_target_etfs,
    find_newly_listed_active_etfs,
)
from modules.analyzer import analyze_all_etfs, find_common_signals
from modules.slack_notifier import build_blocks, send_to_slack


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main(date_arg: str = None, dry_run: bool = False) -> int:
    setup_logging()
    logger = logging.getLogger(__name__)
    ensure_directories()

    ref_date = date_arg or datetime.now().strftime("%Y%m%d")
    logger.info(f"기준일: {ref_date} (이 날짜 이전의 영업일 2일 비교)")

    # [Step 1] 최근 영업일 2개 탐색 (D-1, D-2)
    biz_days = get_recent_business_days(ref_date, n=2)
    if len(biz_days) < 2:
        logger.info("영업일 2일치 데이터 없음 — 휴일/장 개시 전 스킵")
        return 0

    d_today, d_prev = biz_days
    logger.info(f"비교: D-1={d_today}  vs  D-2={d_prev}")

    # [Step 2] 대상 ETF 동적 선정 (AUM ∪ 거래대금 상위)
    targets = select_target_etfs(d_today)
    if not targets:
        logger.error("대상 ETF 선정 실패 — 전송 생략")
        return 1
    tickers = [t['ticker'] for t in targets]
    etf_names = {t['ticker']: t['name'] for t in targets}

    # [Step 3] 신규 상장 액티브 ETF 감지 (D-1에만 존재)
    newly_listed = find_newly_listed_active_etfs(d_today, d_prev)
    if newly_listed:
        logger.info(f"신규 상장 액티브 ETF {len(newly_listed)}개 감지")

    # [Step 4] ETF별 홀딩 수집
    holdings_today = {}
    holdings_prev = {}
    for t in tickers:
        logger.info(f"  - {t} {etf_names[t]}")
        holdings_today[t] = get_etf_holdings(t, d_today)
        holdings_prev[t] = get_etf_holdings(t, d_prev)

    # 신규 상장 ETF 구성종목 (당일만)
    newly_listed_holdings = {}
    for item in newly_listed:
        newly_listed_holdings[item['ticker']] = {
            'name': item['name'],
            'holdings': get_etf_holdings(item['ticker'], d_today),
        }

    # [Step 5] 분석
    etf_diffs = analyze_all_etfs(holdings_today, holdings_prev, etf_names)
    common = find_common_signals(etf_diffs, min_etfs=COMMON_SIGNAL_MIN_ETFS)

    changed_count = sum(1 for e in etf_diffs if e['has_changes'])
    logger.info(
        f"분석 완료: ETF {len(etf_diffs)}개 중 {changed_count}개 변화, "
        f"공통 시그널 {len(common)}개, 신규 상장 {len(newly_listed_holdings)}개"
    )

    if not etf_diffs and not newly_listed_holdings:
        logger.info("비교 가능한 ETF 없음 — 전송 생략")
        return 0

    # [Step 6] Slack 전송
    blocks = build_blocks(d_today, d_prev, etf_diffs, common, newly_listed_holdings)

    if dry_run or not SLACK_WEBHOOK_URL:
        if not SLACK_WEBHOOK_URL and not dry_run:
            logger.warning("SLACK_WEBHOOK_URL 미설정 — dry-run으로 전환")
        logger.info(f"[DRY-RUN] 블록 {len(blocks)}개, Slack 전송 생략")
        print(json.dumps(blocks, ensure_ascii=False, indent=2))
        return 0

    success = send_to_slack(SLACK_WEBHOOK_URL, blocks)
    return 0 if success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Active ETF Analyzer (Slack)')
    parser.add_argument(
        '--date', '-d', type=str, default=None,
        help='기준일 (YYYYMMDD). 이 날짜 이전의 영업일 2일을 비교. 기본: 오늘',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Slack 전송 없이 Block Kit JSON만 stdout에 출력',
    )
    args = parser.parse_args()

    sys.exit(main(args.date, args.dry_run))
