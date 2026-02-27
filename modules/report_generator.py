"""
PDF 리포트 생성 모듈
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # [GUI 없는 환경용 백엔드]
import matplotlib.pyplot as plt
from fpdf import FPDF

import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])
from config import REPORT_DIR, TOP_N, FONT_CANDIDATES

logger = logging.getLogger(__name__)


def _setup_korean_font():
    """
    [한글 폰트 설정 - matplotlib]
    시스템에 설치된 폰트 중 사용 가능한 한글 폰트 선택
    """
    import matplotlib.font_manager as fm

    # [시스템 폰트 목록에서 한글 폰트 검색]
    font_found = False
    for font_name in FONT_CANDIDATES:
        fonts = [f for f in fm.fontManager.ttflist if font_name in f.name]
        if fonts:
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            logger.info(f"한글 폰트 설정: {font_name}")
            font_found = True
            break

    if not font_found:
        logger.warning("한글 폰트를 찾을 수 없습니다. 기본 폰트 사용")
        plt.rcParams['axes.unicode_minus'] = False


def _create_returns_chart(etf_info: pd.DataFrame, date: str) -> Optional[Path]:
    """
    ETF 3개월 수익률 비교 차트 생성

    Args:
        etf_info: ETF 정보 DataFrame
        date: 기준일

    Returns:
        차트 이미지 경로
    """
    if etf_info.empty:
        return None

    _setup_korean_font()

    fig, ax = plt.subplots(figsize=(10, 8))

    # [3개월 수익률 기준 정렬]
    df_sorted = etf_info.sort_values('Returns_3M', ascending=True)

    # [바 차트 색상 설정 (상승: 빨강, 하락: 파랑)]
    colors = ['#e74c3c' if x >= 0 else '#3498db' for x in df_sorted['Returns_3M']]

    bars = ax.barh(df_sorted['Name'], df_sorted['Returns_3M'], color=colors)

    ax.set_xlabel('3개월 수익률 (%)')
    ax.set_title(f'액티브 ETF 3개월 수익률 비교 ({date})')
    ax.axvline(x=0, color='gray', linestyle='-', linewidth=0.5)

    # [값 표시]
    for bar, val in zip(bars, df_sorted['Returns_3M']):
        ax.text(val, bar.get_y() + bar.get_height()/2,
                f' {val:+.2f}%',
                va='center', ha='left' if val >= 0 else 'right',
                fontsize=8)

    plt.tight_layout()

    # [이미지 저장]
    REPORT_DIR.mkdir(exist_ok=True)
    chart_path = REPORT_DIR / f"chart_{date}.png"
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()

    logger.info(f"차트 저장: {chart_path}")
    return chart_path


class KoreanPDF(FPDF):
    """한글 지원 PDF 클래스"""

    def __init__(self):
        super().__init__()
        self._setup_font()

    def _setup_font(self):
        """
        [한글 폰트 등록 - fpdf2]
        시스템 폰트 경로에서 NanumGothic 검색
        """
        import os

        # [일반적인 폰트 경로]
        font_paths = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/nanum-coding/NanumGothicCoding.ttf",
            "C:/Windows/Fonts/NanumGothic.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            os.path.expanduser("~/.fonts/NanumGothic.ttf"),
        ]

        font_found = False
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    self.add_font("Korean", "", font_path, uni=True)
                    self.font_name = "Korean"
                    font_found = True
                    logger.info(f"PDF 폰트 등록: {font_path}")
                    break
                except Exception as e:
                    logger.debug(f"폰트 등록 실패 ({font_path}): {e}")

        if not font_found:
            # [폰트 없으면 기본 폰트 사용 (한글 깨질 수 있음)]
            self.font_name = "Helvetica"
            logger.warning("한글 폰트를 찾을 수 없어 기본 폰트 사용")

    def header(self):
        self.set_font(self.font_name, size=12)
        self.cell(0, 10, 'Active ETF Analyzer Report', ln=True, align='C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_name, size=8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')


def generate_pdf(
    etf_info: pd.DataFrame,
    consensus_df: pd.DataFrame,
    diff_df: pd.DataFrame,
    date: str = None
) -> Path:
    """
    PDF 리포트 생성

    Args:
        etf_info: 분석 대상 ETF 현황
        consensus_df: 합산 보유 비중 분석 결과
        diff_df: 전일 대비 변동 분석 결과
        date: 리포트 기준일

    Returns:
        생성된 PDF 파일 경로
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    REPORT_DIR.mkdir(exist_ok=True)

    pdf = KoreanPDF()
    pdf.add_page()

    # [제목]
    pdf.set_font(pdf.font_name, size=16)
    pdf.cell(0, 10, f'Active ETF Analysis Report - {date}', ln=True, align='C')
    pdf.ln(10)

    # [Table 1: 분석 대상 ETF 현황]
    pdf.set_font(pdf.font_name, size=12)
    pdf.cell(0, 8, '1. Analysis Target ETF Overview', ln=True)
    pdf.ln(3)

    _add_etf_table(pdf, etf_info)
    pdf.ln(10)

    # [Table 2: 합산 보유 비중 Top 10]
    pdf.set_font(pdf.font_name, size=12)
    pdf.cell(0, 8, f'2. Consensus Holdings Top {TOP_N}', ln=True)
    pdf.ln(3)

    _add_holdings_table(pdf, consensus_df.head(TOP_N))
    pdf.ln(10)

    # [Table 3: 비중 증가 Top 10]
    pdf.set_font(pdf.font_name, size=12)
    pdf.cell(0, 8, f'3. Weight Change Top {TOP_N}', ln=True)
    pdf.ln(3)

    top_changes = diff_df[diff_df['Weight_Diff'] > 0].head(TOP_N)
    _add_diff_table(pdf, top_changes)

    # [Chart: ETF 수익률 비교]
    pdf.add_page()
    pdf.set_font(pdf.font_name, size=12)
    pdf.cell(0, 8, '4. ETF Returns Comparison', ln=True)
    pdf.ln(5)

    chart_path = _create_returns_chart(etf_info, date)
    if chart_path and chart_path.exists():
        pdf.image(str(chart_path), x=10, w=190)

    # [PDF 저장]
    pdf_path = REPORT_DIR / f"report_{date}.pdf"
    pdf.output(str(pdf_path))

    logger.info(f"PDF 리포트 생성 완료: {pdf_path}")
    return pdf_path


def _add_etf_table(pdf: KoreanPDF, df: pd.DataFrame):
    """ETF 현황 테이블 추가"""
    pdf.set_font(pdf.font_name, size=9)

    # [헤더: 3개월 수익률 포함]
    col_widths = [25, 65, 28, 32, 40]
    headers = ['Ticker', 'Name', 'Close', 'Day Chg(%)', '3M Returns(%)']

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 7, header, border=1, align='C')
    pdf.ln()

    # [데이터]
    for _, row in df.iterrows():
        pdf.cell(col_widths[0], 6, str(row.get('Ticker', '')), border=1)
        # [긴 이름 자르기]
        name = str(row.get('Name', ''))[:23]
        pdf.cell(col_widths[1], 6, name, border=1)
        pdf.cell(col_widths[2], 6, f"{row.get('Close', 0):,.0f}", border=1, align='R')

        change = row.get('Change_Pct', 0)
        pdf.cell(col_widths[3], 6, f"{change:+.2f}%", border=1, align='R')

        # [3개월 수익률]
        returns_3m = row.get('Returns_3M', 0)
        pdf.cell(col_widths[4], 6, f"{returns_3m:+.2f}%", border=1, align='R')
        pdf.ln()


def _add_holdings_table(pdf: KoreanPDF, df: pd.DataFrame):
    """보유 비중 테이블 추가"""
    pdf.set_font(pdf.font_name, size=9)

    # [헤더]
    col_widths = [15, 80, 35, 35, 25]
    headers = ['Rank', 'Stock Name', 'Total Weight', 'Avg Weight', 'ETF Count']

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 7, header, border=1, align='C')
    pdf.ln()

    # [데이터]
    for _, row in df.iterrows():
        pdf.cell(col_widths[0], 6, str(int(row.get('Rank', 0))), border=1, align='C')

        name = str(row.get('StockName', ''))[:30]
        pdf.cell(col_widths[1], 6, name, border=1)
        pdf.cell(col_widths[2], 6, f"{row.get('TotalWeight', 0):.2f}%", border=1, align='R')
        pdf.cell(col_widths[3], 6, f"{row.get('AvgWeight', 0):.2f}%", border=1, align='R')
        pdf.cell(col_widths[4], 6, str(int(row.get('ETF_Count', 0))), border=1, align='C')
        pdf.ln()


def _add_diff_table(pdf: KoreanPDF, df: pd.DataFrame):
    """비중 변동 테이블 추가"""
    pdf.set_font(pdf.font_name, size=9)

    # [헤더]
    col_widths = [80, 35, 35, 40]
    headers = ['Stock Name', 'Current', 'Previous', 'Change']

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 7, header, border=1, align='C')
    pdf.ln()

    # [데이터]
    for _, row in df.iterrows():
        name = str(row.get('StockName', ''))[:30]
        pdf.cell(col_widths[0], 6, name, border=1)
        pdf.cell(col_widths[1], 6, f"{row.get('TotalWeight', 0):.2f}%", border=1, align='R')
        pdf.cell(col_widths[2], 6, f"{row.get('Prev_Weight', 0):.2f}%", border=1, align='R')

        diff = row.get('Weight_Diff', 0)
        diff_str = f"{diff:+.2f}%"
        pdf.cell(col_widths[3], 6, diff_str, border=1, align='R')
        pdf.ln()
