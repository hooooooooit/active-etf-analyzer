"""
일일 급락 빈도 분석기 (modules/daily_drop_analyzer.py)

코스피와 S&P 500의 전일 대비 일일 하락 통계를 계산합니다.
yfinance로 데이터를 가져와서 -3%, -5%, -10% 하락 빈도를 분석합니다.

사용법:
    python modules/daily_drop_analyzer.py
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_KOSPI_CACHE_PATH = Path(__file__).parent.parent / "data" / "kospi_drop_events.json"

INDICES = {
    "코스피": "^KS11",
    "S&P 500": "^GSPC",
}

THRESHOLDS = [-0.03, -0.05, -0.10]


def fetch_max_history(ticker: str) -> pd.DataFrame:
    """가능한 최대 기간의 일일 데이터를 가져옵니다."""
    t = yf.Ticker(ticker)
    df = t.history(period="max")
    if df.empty:
        raise RuntimeError(f"{ticker} 데이터를 가져올 수 없습니다.")
    return df


def analyze_daily_drops(df: pd.DataFrame, thresholds: List[float] = THRESHOLDS) -> Dict:
    """
    일일 수익률에서 각 임계값 이하 하락 통계를 계산합니다.

    Returns:
        dict with keys per threshold containing:
            count, yearly_avg, avg_gap_trading_days, avg_gap_calendar_days,
            last_date, days_since_last, recent_events
    """
    returns = df["Close"].pct_change().dropna()
    total_trading_days = len(returns)
    start_date = returns.index[0]
    end_date = returns.index[-1]
    total_years = (end_date - start_date).days / 365.25

    results = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "total_trading_days": total_trading_days,
        "total_years": round(total_years, 1),
        "tiers": {},
    }

    for threshold in thresholds:
        label = f"{threshold*100:.0f}%"
        mask = returns <= threshold
        drop_dates = returns.index[mask]
        count = len(drop_dates)

        if count > 0:
            yearly_avg = count / total_years
            avg_gap_td = total_trading_days / count
            avg_gap_cd = (end_date - start_date).days / count
            last_date = drop_dates[-1]
            days_since = (end_date - last_date).days

            # 최근 5건
            recent = []
            for d in drop_dates[-5:]:
                recent.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "return_pct": round(float(returns.loc[d]) * 100, 2),
                })

            # 간격 분포 (이벤트 간 거래일 수)
            if count > 1:
                gaps = []
                for i in range(1, len(drop_dates)):
                    gap_td = len(returns.loc[drop_dates[i-1]:drop_dates[i]]) - 1
                    gaps.append(gap_td)
                median_gap = sorted(gaps)[len(gaps) // 2]
                max_gap = max(gaps)
                min_gap = min(gaps)
            else:
                median_gap = None
                max_gap = None
                min_gap = None
        else:
            yearly_avg = 0
            avg_gap_td = None
            avg_gap_cd = None
            last_date = None
            days_since = None
            recent = []
            median_gap = None
            max_gap = None
            min_gap = None

        results["tiers"][label] = {
            "threshold": threshold,
            "count": count,
            "yearly_avg": round(yearly_avg, 2) if yearly_avg else 0,
            "avg_gap_trading_days": round(avg_gap_td) if avg_gap_td else None,
            "avg_gap_calendar_days": round(avg_gap_cd) if avg_gap_cd else None,
            "median_gap_trading_days": median_gap,
            "max_gap_trading_days": max_gap,
            "min_gap_trading_days": min_gap,
            "last_date": last_date.strftime("%Y-%m-%d") if last_date else None,
            "days_since_last": days_since,
            "recent_events": recent,
        }

    return results


def _load_drop_cache() -> Dict | None:
    if _KOSPI_CACHE_PATH.exists():
        return json.loads(_KOSPI_CACHE_PATH.read_text(encoding="utf-8"))
    return None


def _save_drop_cache(cache: Dict):
    _KOSPI_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"코스피 급락 이벤트 캐시 저장: {_KOSPI_CACHE_PATH}")


def _build_full_cache() -> Dict:
    """전체 히스토리에서 캐시를 처음부터 구축."""
    df = fetch_max_history("^KS11")
    returns = df["Close"].pct_change().dropna()
    start_date = returns.index[0]
    end_date = returns.index[-1]

    cache = {
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "data_start": start_date.strftime("%Y-%m-%d"),
        "data_end": end_date.strftime("%Y-%m-%d"),
        "total_trading_days": len(returns),
        "events": {},
    }

    for threshold in THRESHOLDS:
        label = f"{threshold * 100:.0f}%"
        mask = returns <= threshold
        events = []
        for d in returns.index[mask]:
            events.append({
                "date": d.strftime("%Y-%m-%d"),
                "return_pct": round(float(returns.loc[d]) * 100, 2),
            })
        cache["events"][label] = events

    _save_drop_cache(cache)
    return cache


def _update_cache_incremental(cache: Dict) -> Dict:
    """캐시의 data_end 이후 신규 데이터만 가져와 이벤트 추가."""
    last_end = cache["data_end"]
    # pct_change 계산을 위해 며칠 전부터 조회
    start = (datetime.strptime(last_end, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")

    t = yf.Ticker("^KS11")
    df = t.history(start=start)
    if df.empty:
        logger.warning("코스피 증분 데이터 조회 실패 — 캐시 그대로 사용")
        return cache

    returns = df["Close"].pct_change().dropna()
    new_returns = returns[returns.index > pd.Timestamp(last_end, tz=returns.index.tz)]

    if new_returns.empty:
        cache["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        _save_drop_cache(cache)
        return cache

    new_count = 0
    for threshold in THRESHOLDS:
        label = f"{threshold * 100:.0f}%"
        mask = new_returns <= threshold
        for d in new_returns.index[mask]:
            cache["events"][label].append({
                "date": d.strftime("%Y-%m-%d"),
                "return_pct": round(float(new_returns.loc[d]) * 100, 2),
            })
            new_count += 1

    cache["data_end"] = returns.index[-1].strftime("%Y-%m-%d")
    cache["total_trading_days"] = cache["total_trading_days"] + len(new_returns)
    cache["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    if new_count > 0:
        logger.info(f"코스피 급락 이벤트 {new_count}건 새로 감지")

    _save_drop_cache(cache)
    return cache


def _stats_from_cache(cache: Dict) -> Dict:
    """캐시에서 Slack 메시지용 통계 dict 생성."""
    today = datetime.now()
    data_start = datetime.strptime(cache["data_start"], "%Y-%m-%d")
    data_end = datetime.strptime(cache["data_end"], "%Y-%m-%d")
    total_days = (data_end - data_start).days
    total_years = round(total_days / 365.25, 1)

    stats = {
        "data_end": cache["data_end"],
        "total_years": total_years,
        "tiers": {},
    }
    for label, events in cache["events"].items():
        count = len(events)
        if count > 0:
            last_date = events[-1]["date"]
            days_since = (today - datetime.strptime(last_date, "%Y-%m-%d")).days
            avg_gap_cd = round(total_days / count)
        else:
            last_date = None
            days_since = None
            avg_gap_cd = None

        stats["tiers"][label] = {
            "avg_gap_cd": avg_gap_cd,
            "last_date": last_date,
            "days_since": days_since,
            "count": count,
        }
    return stats


def get_kospi_drop_stats() -> Dict | None:
    """코스피 급락 통계를 Slack 메시지용으로 반환 (캐시 활용).

    캐시 파일: data/kospi_drop_events.json
    - 당일 이미 업데이트됐으면 캐시에서 바로 계산
    - 캐시가 오래됐으면 증분 업데이트 (마지막 날짜 이후만 조회)
    - 캐시가 없으면 전체 히스토리에서 구축
    """
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        cache = _load_drop_cache()

        if cache and cache.get("last_updated") == today_str:
            logger.info("코스피 급락 캐시 사용 (당일 업데이트 완료)")
            return _stats_from_cache(cache)

        if cache and cache.get("data_end"):
            logger.info(f"코스피 급락 캐시 증분 업데이트 ({cache['data_end']} 이후)")
            cache = _update_cache_incremental(cache)
            return _stats_from_cache(cache)

        logger.info("코스피 급락 캐시 없음 — 전체 히스토리에서 구축")
        cache = _build_full_cache()
        return _stats_from_cache(cache)
    except Exception as e:
        logger.warning(f"코스피 급락 통계 조회 실패: {e}")
        return None


def build_markdown_report(all_results: Dict[str, Dict]) -> str:
    """마크다운 형식의 분석 레포트를 생성합니다."""
    lines = [
        "# 📊 일일 급락 빈도 분석 레포트",
        "",
        f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    for name, data in all_results.items():
        lines += [
            f"## {name}",
            "",
            f"기간: {data['start_date']} ~ {data['end_date']} "
            f"({data['total_trading_days']:,}거래일, {data['total_years']}년)",
            "",
            "### 요약",
            "",
            "| 임계값 | 총 횟수 | 연 빈도 | 평균 간격(거래일) | 평균 간격(캘린더일) | 마지막 발생 | 경과일 |",
            "|:------|:------:|:------:|:---------------:|:-----------------:|:----------:|:-----:|",
        ]

        for label, tier in data["tiers"].items():
            gap_td = f"{tier['avg_gap_trading_days']}일" if tier['avg_gap_trading_days'] else "—"
            gap_cd = f"{tier['avg_gap_calendar_days']}일" if tier['avg_gap_calendar_days'] else "—"
            last = tier['last_date'] or "—"
            since = f"{tier['days_since_last']}일" if tier['days_since_last'] is not None else "—"

            lines.append(
                f"| {label} | {tier['count']}회 "
                f"| {tier['yearly_avg']}/년 "
                f"| {gap_td} | {gap_cd} "
                f"| {last} | {since} |"
            )

        lines += [""]

        # 간격 분포
        lines += [
            "### 간격 분포 (이벤트 간 거래일)",
            "",
            "| 임계값 | 최소 | 중앙값 | 평균 | 최대 |",
            "|:------|:----:|:-----:|:----:|:----:|",
        ]

        for label, tier in data["tiers"].items():
            med = f"{tier['median_gap_trading_days']}" if tier['median_gap_trading_days'] is not None else "—"
            mx = f"{tier['max_gap_trading_days']}" if tier['max_gap_trading_days'] is not None else "—"
            mn = f"{tier['min_gap_trading_days']}" if tier['min_gap_trading_days'] is not None else "—"
            avg = f"{tier['avg_gap_trading_days']}" if tier['avg_gap_trading_days'] else "—"
            lines.append(f"| {label} | {mn} | {med} | {avg} | {mx} |")

        lines += [""]

        # 최근 이벤트
        for label, tier in data["tiers"].items():
            if tier["recent_events"]:
                lines += [
                    f"### 최근 {label} 이하 하락",
                    "",
                    "| 날짜 | 수익률 |",
                    "|:----:|:-----:|",
                ]
                for evt in reversed(tier["recent_events"]):
                    lines.append(f"| {evt['date']} | {evt['return_pct']}% |")
                lines.append("")

        lines.append("---")
        lines.append("")

    # 비교표
    if len(all_results) > 1:
        names = list(all_results.keys())
        lines += [
            "## 비교: " + " vs ".join(names),
            "",
            "| 임계값 |",
        ]

        header = "| 임계값 |"
        separator = "|:------|"
        for name in names:
            header += f" {name} 횟수 | {name} 연빈도 | {name} 평균간격 |"
            separator += ":------:|:------:|:--------:|"
        lines[-1] = header
        lines.append(separator)

        for label in list(all_results[names[0]]["tiers"].keys()):
            row = f"| {label} |"
            for name in names:
                tier = all_results[name]["tiers"].get(label, {})
                cnt = tier.get("count", "—")
                yr = tier.get("yearly_avg", "—")
                gap = tier.get("avg_gap_calendar_days", "—")
                gap_str = f"~{gap}일" if gap else "—"
                row += f" {cnt}회 | {yr}/년 | {gap_str} |"
            lines.append(row)

        lines.append("")

    lines += [
        "---",
        "_방법론: 전일 종가 대비 당일 종가의 일일 수익률 (day-over-day close-to-close)_  ",
        "_데이터: Yahoo Finance_",
    ]

    return "\n".join(lines)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    all_results = {}

    for name, ticker in INDICES.items():
        logger.info(f"{name} ({ticker}) 데이터 조회 중...")
        df = fetch_max_history(ticker)
        logger.info(f"  {len(df)}일치 로드 완료")

        logger.info(f"{name} 일일 급락 분석 중...")
        results = analyze_daily_drops(df)
        all_results[name] = results

        for label, tier in results["tiers"].items():
            logger.info(
                f"  {label}: {tier['count']}회, "
                f"연 {tier['yearly_avg']}회, "
                f"평균 {tier['avg_gap_trading_days']}거래일, "
                f"마지막 {tier['last_date']}"
            )

    # 레포트 생성
    report = build_markdown_report(all_results)

    # 저장
    from pathlib import Path
    out_path = Path(__file__).parent.parent / "reports" / "daily_drop_stats.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    logger.info(f"레포트 저장: {out_path}")

    # 콘솔 출력
    print()
    print(report)


if __name__ == "__main__":
    main()