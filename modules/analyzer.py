"""
액티브 ETF 구성 종목 분석 모듈
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List
import pandas as pd

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
from config import DATA_DIR, TOP_N

logger = logging.getLogger(__name__)


def load_previous_data(date: str = None) -> Optional[pd.DataFrame]:
    """
    전일(T-1) 분석 데이터 로드

    Args:
        date: 기준일 (YYYYMMDD). None이면 당일 기준 전일 데이터 로드

    Returns:
        전일 분석 데이터 DataFrame 또는 None
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # [전일 날짜 계산 - 영업일 고려 필요시 수정]
    current_date = datetime.strptime(date, "%Y%m%d")
    prev_date = current_date - timedelta(days=1)

    # [주말 건너뛰기]
    while prev_date.weekday() >= 5:  # 토요일(5), 일요일(6)
        prev_date -= timedelta(days=1)

    prev_date_str = prev_date.strftime("%Y%m%d")
    prev_file = DATA_DIR / f"{prev_date_str}.csv"

    if prev_file.exists():
        logger.info(f"전일 데이터 로드: {prev_file}")
        return pd.read_csv(prev_file, encoding='utf-8-sig')
    else:
        logger.info(f"전일 데이터 없음: {prev_file}")
        return None


def analyze_holdings(
    holdings_list: List[pd.DataFrame],
    prev_df: Optional[pd.DataFrame] = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    전체 액티브 ETF의 구성 종목 비중 분석

    Args:
        holdings_list: 각 ETF의 구성종목 DataFrame 리스트
        prev_df: 전일 분석 데이터

    Returns:
        (합산 비중 분석 결과, 비중 변동 분석 결과) 튜플
    """
    if not holdings_list:
        logger.warning("분석할 구성종목 데이터가 없습니다")
        return pd.DataFrame(), pd.DataFrame()

    # [Step 1] 모든 ETF 구성종목 통합
    combined_df = pd.concat(holdings_list, ignore_index=True)
    logger.info(f"통합 데이터: {len(combined_df)} 행")

    # [Step 2] 종목명 기준 합산 비중 계산]
    # pykrx PDF 데이터 컬럼 확인 후 비중 컬럼명 조정 필요
    weight_col = None
    for col in ['비중', '비중(%)', 'Weight', '구성비중']:
        if col in combined_df.columns:
            weight_col = col
            break

    if weight_col is None:
        logger.warning(f"비중 컬럼을 찾을 수 없음. 컬럼: {combined_df.columns.tolist()}")
        # [비중 컬럼이 없는 경우 금액 기반으로 비중 계산 시도]
        if '평가금액' in combined_df.columns:
            total_value = combined_df['평가금액'].sum()
            combined_df['비중'] = (combined_df['평가금액'] / total_value * 100).round(4)
            weight_col = '비중'
        else:
            return pd.DataFrame(), pd.DataFrame()

    # [종목명 컬럼 확인]
    name_col = None
    for col in ['종목명', '종목', 'Name', '구성종목명']:
        if col in combined_df.columns:
            name_col = col
            break

    if name_col is None:
        logger.warning(f"종목명 컬럼을 찾을 수 없음. 컬럼: {combined_df.columns.tolist()}")
        return pd.DataFrame(), pd.DataFrame()

    # [Step 3] 종목별 평균 비중 계산 (전체 액티브 ETF 내)]
    # 비중 합계: 해당 종목이 여러 ETF에 편입된 경우 합산
    # 평균 비중: 편입된 ETF 수로 나눈 평균
    consensus_df = combined_df.groupby(name_col).agg({
        weight_col: ['sum', 'mean', 'count']
    }).reset_index()

    consensus_df.columns = ['StockName', 'TotalWeight', 'AvgWeight', 'ETF_Count']

    # [합산 비중 기준 정렬]
    consensus_df = consensus_df.sort_values('TotalWeight', ascending=False)
    consensus_df['Rank'] = range(1, len(consensus_df) + 1)

    logger.info(f"종목 수: {len(consensus_df)}")

    # [Step 4] 전일 대비 변동 분석
    if prev_df is not None and not prev_df.empty:
        diff_df = _calculate_diff(consensus_df, prev_df)
    else:
        # [전일 데이터 없는 경우 모든 종목을 신규로 표시]
        diff_df = consensus_df.copy()
        diff_df['Weight_Diff'] = 0.0
        diff_df['Status'] = 'New'
        diff_df['Prev_Weight'] = 0.0

    return consensus_df, diff_df


def _calculate_diff(
    today_df: pd.DataFrame,
    prev_df: pd.DataFrame
) -> pd.DataFrame:
    """
    [비중 변동 계산 로직]

    전일 대비 비중 변화(Δ) 및 편입/제외 상태 분류:
    - New: 오늘 신규 편입된 종목
    - Out: 오늘 제외된 종목 (전일에는 있었으나 오늘은 없음)
    - Maintain: 유지 중인 종목
    """
    # [Outer Join으로 모든 종목 포함]
    merged = pd.merge(
        today_df[['StockName', 'TotalWeight']],
        prev_df[['StockName', 'TotalWeight']],
        on='StockName',
        how='outer',
        suffixes=('_Today', '_Prev')
    )

    # [결측값 0으로 채우기]
    merged['TotalWeight_Today'] = merged['TotalWeight_Today'].fillna(0)
    merged['TotalWeight_Prev'] = merged['TotalWeight_Prev'].fillna(0)

    # [비중 변화 계산]
    merged['Weight_Diff'] = (
        merged['TotalWeight_Today'] - merged['TotalWeight_Prev']
    ).round(4)

    # [상태 분류]
    def classify_status(row):
        if row['TotalWeight_Prev'] == 0 and row['TotalWeight_Today'] > 0:
            return 'New'
        elif row['TotalWeight_Today'] == 0 and row['TotalWeight_Prev'] > 0:
            return 'Out'
        else:
            return 'Maintain'

    merged['Status'] = merged.apply(classify_status, axis=1)

    # [컬럼명 정리]
    result = merged.rename(columns={
        'TotalWeight_Today': 'TotalWeight',
        'TotalWeight_Prev': 'Prev_Weight'
    })

    # [비중 변화 크기 기준 정렬]
    result = result.sort_values('Weight_Diff', ascending=False)

    return result


def save_daily_data(consensus_df: pd.DataFrame, date: str = None) -> Path:
    """
    당일 분석 결과 저장 (다음 날 비교용)

    Args:
        consensus_df: 합산 비중 분석 결과
        date: 저장 기준일

    Returns:
        저장된 파일 경로
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    DATA_DIR.mkdir(exist_ok=True)
    file_path = DATA_DIR / f"{date}.csv"

    consensus_df.to_csv(file_path, index=False, encoding='utf-8-sig')
    logger.info(f"데이터 저장 완료: {file_path}")

    return file_path


def get_top_holdings(consensus_df: pd.DataFrame, n: int = TOP_N) -> pd.DataFrame:
    """상위 N개 종목 추출"""
    return consensus_df.head(n).copy()


def get_top_changes(diff_df: pd.DataFrame, n: int = TOP_N) -> pd.DataFrame:
    """비중 증가 상위 N개 종목 추출"""
    # [신규 편입 또는 비중 증가 종목만]
    increases = diff_df[diff_df['Weight_Diff'] > 0].head(n)
    return increases.copy()


def get_new_entries(diff_df: pd.DataFrame) -> pd.DataFrame:
    """신규 편입 종목"""
    return diff_df[diff_df['Status'] == 'New'].copy()


def get_exits(diff_df: pd.DataFrame) -> pd.DataFrame:
    """제외 종목"""
    return diff_df[diff_df['Status'] == 'Out'].copy()
