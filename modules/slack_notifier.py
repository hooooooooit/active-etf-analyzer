"""
Slack Incoming Webhook 전송 모듈

Block Kit 형식의 메시지를 구성하고 webhook URL로 POST 한다.
"""
import logging
from pathlib import Path
from typing import Dict, List
import pandas as pd
import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MAX_CHANGES_PER_ETF, NEW_LISTING_TOP_N

logger = logging.getLogger(__name__)

# Slack Block Kit 제한
_MAX_BLOCKS = 50
_MAX_TEXT_CHARS = 2900  # section text 안전 마진 (공식 3000)


# ============================================================
# 포맷 유틸
# ============================================================

def _fmt_pct(v: float) -> str:
    """+3.20% / -1.50% 형식."""
    return f"{v:+.2f}%"


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _take_top(df: pd.DataFrame, n: int, by: str, ascending: bool) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values(by, ascending=ascending).head(n)


# ============================================================
# 블록 빌더
# ============================================================

def _header_block(date: str) -> Dict:
    return {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"📅 {_fmt_date(date)} Active ETF 매매 변동 (전일 vs 전전일)",
            "emoji": True,
        },
    }


def _divider() -> Dict:
    return {"type": "divider"}


def _correction_proximity_block(kospi_stats: Dict) -> List[Dict]:
    """코스피 급락 통계 기반 조정 접근도 섹션."""
    if not kospi_stats:
        return []

    lines = ["*📉 코스피 조정 접근도* _(통계 기반, {:.1f}년 데이터)_".format(
        kospi_stats["total_years"]
    )]

    for label, tier in kospi_stats["tiers"].items():
        days_since = tier["days_since"]
        avg_gap = tier["avg_gap_cd"]
        if days_since is None or avg_gap is None:
            continue

        ratio = days_since / avg_gap
        pct = min(ratio * 100, 999)

        # 게이지 바 (10칸)
        filled = min(int(ratio * 10), 10)
        bar = "█" * filled + "░" * (10 - filled)

        # 위험도 이모지
        if ratio >= 1.0:
            emoji = "🔴"
        elif ratio >= 0.7:
            emoji = "🟡"
        else:
            emoji = "🟢"

        lines.append(
            f"  {emoji} `{label}` {bar} {pct:.0f}%  "
            f"— 마지막 {days_since}일 전 (평균 {avg_gap:,}일 간격)"
        )

    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


def _common_signals_block(common: pd.DataFrame) -> List[Dict]:
    """공통 시그널 섹션. 비어있으면 빈 리스트."""
    if common.empty:
        return []

    lines = ["*공통 시그널* _(여러 ETF에서 동시 매수/신규 편입)_"]
    for _, r in common.iterrows():
        new_tag = f" (신규 {int(r['New_Count'])})" if r['New_Count'] > 0 else ""
        lines.append(
            f"• `{r['StockName']}` — {int(r['ETF_Count'])}개 ETF{new_tag}"
        )

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS - 20] + "\n_(이하 생략)_"

    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def _fmt_shares(v: float) -> str:
    """+1,200주 / -300주 형식. 소수점 계약수는 소수 1자리."""
    if v == int(v):
        return f"{int(v):+,}주"
    return f"{v:+,.1f}주"


_MIN_WEIGHT = 0.1  # 이 값(%) 미만이면 비중 표시 무의미 → 계약수로 전환

def _fmt_weight_change(w_today: float, w_prev: float) -> str:
    """비중 변화 표시. 둘 다 미미하면 빈 문자열."""
    if max(w_today, w_prev) < _MIN_WEIGHT:
        return ""
    if w_prev < _MIN_WEIGHT:
        return f" (→{w_today:.2f}%)"
    if w_today < _MIN_WEIGHT:
        return f" ({w_prev:.2f}%→)"
    diff = w_today - w_prev
    return f" ({w_prev:.2f}%→{w_today:.2f}%, {diff:+.2f}%)"


def _fmt_change(row: dict) -> str:
    """비중 변화 or 계약수 변화율. 비중이 있으면 비중, 없으면 계약수 변화율(%)."""
    wt = row.get('Weight_Today', 0) or 0
    wp = row.get('Weight_Prev', 0) or 0
    weight_str = _fmt_weight_change(wt, wp)
    if weight_str:
        return weight_str
    # 비중 없음 → 계약수 변화율로 대체
    sp = row.get('Shares_Prev', 0) or 0
    sd = row.get('Shares_Diff', 0) or 0
    if sp > 0 and sd != 0:
        pct = sd / sp * 100
        return f" (수량 {pct:+.1f}%)"
    return ""


def _top_holdings_line(etf: Dict) -> str:
    """비중 상위 3개 종목 한 줄 요약. 비중 없으면 계약수 기준."""
    top = etf.get('top_holdings')
    if top is None or top.empty:
        return ""
    # 비중이 유의미한지 확인 (1% 이상인 종목이 있는지)
    has_weight = (top['Weight_Today'] >= 1.0).any()
    if has_weight:
        items = [
            f"{r['StockName']} {r['Weight_Today']:.1f}%"
            for _, r in top.iterrows()
        ]
    else:
        items = [
            f"{r['StockName']} {int(r['Shares_Today']):,}주"
            for _, r in top.iterrows()
        ]
    return f"  TOP: {', '.join(items)}"


def _cash_line(etf: Dict) -> str:
    """현금 비중 및 증감 한 줄. 비중 정보 없으면 빈 문자열."""
    ct = etf.get('cash_today', 0) or 0
    cp = etf.get('cash_prev', 0) or 0
    if ct <= 0 and cp <= 0:
        return ""
    ct = max(ct, 0)
    cp = max(cp, 0)
    diff = ct - cp
    return f"  현금 {ct:.1f}% ({diff:+.1f}%p)"


def _etf_block(etf: Dict, max_per_cat: int = MAX_CHANGES_PER_ETF) -> Dict:
    """단일 ETF의 변화 요약 섹션 (계약수 변화 기준)."""
    lines = [f"*[{etf['manager']}] {etf['name']}* `{etf['ticker']}`"]

    top_line = _top_holdings_line(etf)
    if top_line:
        lines.append(top_line)
    cash = _cash_line(etf)
    if cash:
        lines.append(cash)

    new = _take_top(etf['new'], max_per_cat, 'Shares_Today', ascending=False)
    buy = _take_top(etf['buy'], max_per_cat, 'Shares_Diff', ascending=False)
    sell = _take_top(etf['sell'], max_per_cat, 'Shares_Diff', ascending=True)
    out = _take_top(etf['out'], max_per_cat, 'Shares_Prev', ascending=False)

    if not new.empty:
        lines.append("  *신규 편입*")
        for _, r in new.iterrows():
            lines.append(f"    • {r['StockName']} {_fmt_shares(r['Shares_Today'])}{_fmt_weight_change(r['Weight_Today'], 0)}")

    if not buy.empty:
        lines.append("  *매수*")
        for _, r in buy.iterrows():
            lines.append(f"    • {r['StockName']} {_fmt_shares(r['Shares_Diff'])}{_fmt_change(r)}")

    if not sell.empty:
        lines.append("  *매도*")
        for _, r in sell.iterrows():
            lines.append(f"    • {r['StockName']} {_fmt_shares(r['Shares_Diff'])}{_fmt_change(r)}")

    if not out.empty:
        lines.append("  *편출*")
        for _, r in out.iterrows():
            lines.append(f"    • {r['StockName']} {_fmt_shares(-r['Shares_Prev'])}{_fmt_weight_change(0, r['Weight_Prev'])}")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS - 20] + "\n_(이하 생략)_"

    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _newly_listed_blocks(newly_listed_holdings: Dict[str, Dict]) -> List[Dict]:
    """신규 상장 액티브 ETF 섹션. 각 ETF별 상위 N개 종목을 표시.

    Args:
        newly_listed_holdings: {ticker: {'name': str, 'holdings': DataFrame}}
    """
    if not newly_listed_holdings:
        return []

    blocks: List[Dict] = [{
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*🆕 신규 상장 액티브 ETF ({len(newly_listed_holdings)}개)*  _첫 공개 구성_",
        },
    }]

    for ticker, item in newly_listed_holdings.items():
        name = item['name']
        df = item['holdings']
        if df is None or df.empty or '비중' not in df.columns:
            lines = [f"*{name}* `{ticker}`", "  _구성종목 조회 실패_"]
        else:
            name_col = '구성종목명' if '구성종목명' in df.columns else df.columns[1]
            top = df.sort_values('비중', ascending=False).head(NEW_LISTING_TOP_N)
            lines = [f"*{name}* `{ticker}`  _상위 {len(top)}개 종목_"]
            items = [
                f"{r[name_col]} {pd.to_numeric(r['비중'], errors='coerce'):.2f}%"
                for _, r in top.iterrows()
            ]
            lines.append("  " + ", ".join(items))

        text = "\n".join(lines)
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS - 20] + "\n_(이하 생략)_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    return blocks


def _summary_block(total_etfs: int, changed_etfs: int, date_prev: str) -> Dict:
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"분석 대상 ETF {total_etfs}개 중 {changed_etfs}개에서 변화 감지 "
                    f"· 비교 기준일 D-2 = `{_fmt_date(date_prev)}`"
                ),
            }
        ],
    }


# ============================================================
# Public API
# ============================================================

def build_blocks(
    date_today: str,
    date_prev: str,
    etf_diffs: List[Dict],
    common_signals: pd.DataFrame,
    newly_listed_holdings: Dict[str, Dict] = None,
    kospi_drop_stats: Dict = None,
) -> List[Dict]:
    """Block Kit 블록 리스트 구성.

    Args:
        date_today: 최근 영업일 (D-1)
        date_prev: 전전 영업일 (D-2)
        etf_diffs: analyze_all_etfs 결과
        common_signals: find_common_signals 결과
        newly_listed_holdings: {ticker: {'name', 'holdings'}} 오늘 상장한 신규 ETF
        kospi_drop_stats: get_kospi_drop_stats() 결과 (코스피 급락 통계)
    """
    blocks: List[Dict] = [_header_block(date_today)]

    # 코스피 조정 접근도 (맨 앞)
    if kospi_drop_stats:
        blocks.extend(_correction_proximity_block(kospi_drop_stats))
        blocks.append(_divider())

    # 신규 상장 ETF (오늘만 유효한 정보)
    if newly_listed_holdings:
        blocks.extend(_newly_listed_blocks(newly_listed_holdings))
        blocks.append(_divider())

    blocks.extend(_common_signals_block(common_signals))
    blocks.append(_divider())

    # 운용사별 그룹핑 후 ETF 이름 순
    sorted_etfs = sorted(etf_diffs, key=lambda e: (e['manager'], e['name']))

    for etf in sorted_etfs:
        if etf['has_changes']:
            blocks.append(_etf_block(etf))
        else:
            no_change_lines = [f"*[{etf['manager']}] {etf['name']}* `{etf['ticker']}`  _변동 없음_"]
            top_line = _top_holdings_line(etf)
            if top_line:
                no_change_lines.append(top_line)
            cash = _cash_line(etf)
            if cash:
                no_change_lines.append(cash)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(no_change_lines),
                },
            })
        if len(blocks) >= _MAX_BLOCKS - 2:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"_(블록 수 제한으로 {len(sorted_etfs)}개 중 일부만 표시)_",
                },
            })
            break

    changed_count = sum(1 for e in etf_diffs if e['has_changes'])
    blocks.append(_summary_block(len(etf_diffs), changed_count, date_prev))
    return blocks


def send_to_slack(webhook_url: str, blocks: List[Dict]) -> bool:
    """webhook URL로 Block Kit 메시지 POST.

    Returns:
        True 성공, False 실패
    """
    try:
        response = requests.post(
            webhook_url,
            json={"blocks": blocks},
            timeout=10,
        )
        if response.status_code == 200:
            logger.info(f"Slack 전송 성공 (블록 {len(blocks)}개)")
            return True
        logger.error(
            f"Slack 전송 실패 (HTTP {response.status_code}): {response.text[:200]}"
        )
        return False
    except requests.RequestException as e:
        logger.error(f"Slack 전송 중 오류: {e}")
        return False
