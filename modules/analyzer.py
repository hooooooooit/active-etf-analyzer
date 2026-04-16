"""
ETF별 구성종목 변동 분석 모듈

- 한 ETF의 두 날짜(D-1 vs D-2) 구성종목을 비교
- **계약수(주수) 변화**를 기준으로 실제 운용 의사결정만 추출
  (주가 등락에 의한 패시브 비중 변화는 무시)
- 여러 ETF에 공통으로 나타나는 신호(3개 이상 ETF에서 동시 매수/신규 편입) 추출
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import COMMON_SIGNAL_MIN_ETFS

logger = logging.getLogger(__name__)


# ============================================================
# 단일 ETF diff (계약수 기반)
# ============================================================

def diff_etf(
    today: Optional[pd.DataFrame],
    prev: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """단일 ETF의 D-1 vs D-2 구성종목 비교 (계약수 변화 기준).

    Returns:
        컬럼: [StockName, Shares_Today, Shares_Prev, Shares_Diff,
               Weight_Today, Weight_Prev, Weight_Diff, Status]
        Status: 'New' | 'Out' | 'Buy' | 'Sell' | 'Hold'
        - New/Out: 종목 편입/편출
        - Buy/Sell: 계약수 증가/감소 (실제 매매)
        - Hold: 계약수 변화 없음 (비중 변화는 주가에 의한 것)
    """
    cols = ['StockName', 'Shares_Today', 'Shares_Prev', 'Shares_Diff',
            'Weight_Today', 'Weight_Prev', 'Weight_Diff', 'Status']
    if today is None or today.empty or prev is None or prev.empty:
        return pd.DataFrame(columns=cols)

    # 구성종목명 + 계약수 + 비중 추출
    def _prep(df, suffix):
        out = df[['구성종목명', '계약수', '비중']].copy()
        out.columns = ['StockName', f'Shares_{suffix}', f'Weight_{suffix}']
        out[f'Shares_{suffix}'] = pd.to_numeric(out[f'Shares_{suffix}'], errors='coerce').fillna(0)
        out[f'Weight_{suffix}'] = pd.to_numeric(out[f'Weight_{suffix}'], errors='coerce').fillna(0)
        return out

    t = _prep(today, 'Today')
    p = _prep(prev, 'Prev')

    merged = pd.merge(t, p, on='StockName', how='outer')
    for c in ['Shares_Today', 'Shares_Prev', 'Weight_Today', 'Weight_Prev']:
        merged[c] = merged[c].fillna(0)
    merged['Shares_Diff'] = merged['Shares_Today'] - merged['Shares_Prev']
    merged['Weight_Diff'] = (merged['Weight_Today'] - merged['Weight_Prev']).round(4)

    # 계약수 diff 최소 임계값 (외국주 ETF는 소수점 계약수 → 0.01 수준 오차 발생)
    _SHARES_NOISE = 0.5

    def _status(row):
        if row['Shares_Prev'] == 0 and row['Shares_Today'] > 0:
            return 'New'
        if row['Shares_Today'] == 0 and row['Shares_Prev'] > 0:
            return 'Out'
        if row['Shares_Diff'] >= _SHARES_NOISE:
            return 'Buy'
        if row['Shares_Diff'] <= -_SHARES_NOISE:
            return 'Sell'
        return 'Hold'

    merged['Status'] = merged.apply(_status, axis=1)
    return merged[cols].sort_values('Shares_Diff', ascending=False).reset_index(drop=True)


# ============================================================
# 운용사 추출
# ============================================================

_MANAGER_PREFIXES = [
    'KoAct', 'TIME', 'TIGER', 'KODEX', 'KBSTAR', 'RISE',
    'ACE', 'PLUS', 'SOL', 'HANARO', 'ARIRANG', 'KINDEX',
    'UNICORN', '1Q',
]


def extract_manager(etf_name: str) -> str:
    """ETF 이름에서 운용사 prefix 추출. 매칭 실패 시 'Other'."""
    if not etf_name:
        return 'Other'
    for prefix in _MANAGER_PREFIXES:
        if etf_name.startswith(prefix):
            return prefix
    return 'Other'


# ============================================================
# 전체 ETF 분석
# ============================================================

def analyze_all_etfs(
    holdings_today: Dict[str, pd.DataFrame],
    holdings_prev: Dict[str, pd.DataFrame],
    etf_names: Dict[str, str],
) -> List[Dict]:
    """각 ETF의 D-1 vs D-2 diff (계약수 기준).

    Returns:
        [{ticker, name, manager, new, out, buy, sell, has_changes}, ...]
        new/out/buy/sell은 각각 DataFrame
    """
    results: List[Dict] = []

    for ticker, today_df in holdings_today.items():
        prev_df = holdings_prev.get(ticker)
        name = etf_names.get(ticker, ticker)

        diff = diff_etf(today_df, prev_df)
        if diff.empty:
            logger.info(f"{ticker} {name}: 비교 데이터 부족 (스킵)")
            continue

        new = diff[diff['Status'] == 'New']
        out = diff[diff['Status'] == 'Out']
        buy = diff[diff['Status'] == 'Buy']
        sell = diff[diff['Status'] == 'Sell']

        has_changes = bool(len(new) or len(out) or len(buy) or len(sell))

        # 비중 상위 3개 (현재 포트폴리오 구성 요약). 비중 없으면 계약수 기준.
        has_weight = diff[diff['Weight_Today'] >= 1.0]
        if not has_weight.empty:
            top3 = has_weight.nlargest(3, 'Weight_Today')
        else:
            top3 = diff[diff['Shares_Today'] > 0].nlargest(3, 'Shares_Today')

        # 현금 비중 (현금/예치금 관련 행)
        _CASH_KW = ['현금', '예치', '설정현금']
        cash_mask = diff['StockName'].str.contains('|'.join(_CASH_KW), na=False)
        cash_today = float(diff.loc[cash_mask, 'Weight_Today'].sum())
        cash_prev = float(diff.loc[cash_mask, 'Weight_Prev'].sum())

        results.append({
            'ticker': ticker,
            'name': name,
            'manager': extract_manager(name),
            'new': new.reset_index(drop=True),
            'out': out.reset_index(drop=True),
            'buy': buy.reset_index(drop=True),
            'sell': sell.reset_index(drop=True),
            'top_holdings': top3.reset_index(drop=True),
            'has_changes': has_changes,
            'cash_today': cash_today,
            'cash_prev': cash_prev,
        })

    return results


# ============================================================
# 공통 시그널
# ============================================================

def find_common_signals(
    etf_diffs: List[Dict],
    min_etfs: int = COMMON_SIGNAL_MIN_ETFS,
) -> pd.DataFrame:
    """여러 ETF에서 동시에 New 또는 Buy 상태인 종목을 카운트 기반으로 집계.

    Returns:
        컬럼: [StockName, ETF_Count, Avg_Shares_Diff, New_Count]
        해당 없음 시 빈 DataFrame.
    """
    rows = []
    for etf in etf_diffs:
        for status_key in ('new', 'buy'):
            sub = etf[status_key]
            for _, r in sub.iterrows():
                rows.append({
                    'StockName': r['StockName'],
                    'Shares_Diff': r['Shares_Diff'],
                    'Is_New': status_key == 'new',
                })

    if not rows:
        return pd.DataFrame(columns=['StockName', 'ETF_Count', 'Avg_Shares_Diff', 'New_Count'])

    df = pd.DataFrame(rows)
    agg = df.groupby('StockName').agg(
        ETF_Count=('Shares_Diff', 'count'),
        Avg_Shares_Diff=('Shares_Diff', 'mean'),
        New_Count=('Is_New', 'sum'),
    ).reset_index()

    agg = agg[agg['ETF_Count'] >= min_etfs]
    agg['Avg_Shares_Diff'] = agg['Avg_Shares_Diff'].round(1)
    agg = agg.sort_values(
        ['ETF_Count', 'Avg_Shares_Diff'], ascending=[False, False]
    ).reset_index(drop=True)

    return agg
