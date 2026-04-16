"""
pykrx를 이용한 ETF 데이터 수집 모듈

- KRX 로그인 (ETF API는 2026-02-27 이후 인증 필수)
- ETF 구성종목(PDF) 조회 + 비중 재계산
- 조회 결과는 data/cache_{date}_holdings_{ticker}.csv 로 캐싱
"""
import time
import json
import re
import logging
from datetime import timedelta
from pathlib import Path
from typing import Optional
import pandas as pd
from pykrx import stock

try:
    import yfinance as yf
    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    MAX_RETRIES, RETRY_DELAY, DATA_DIR,
    KRX_USER_ID, KRX_PASSWORD,
    PRIORITY_MANAGERS, TOP_N_PER_MANAGER, TOP_N_OTHER,
    EXCLUDE_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ============================================================
# KRX 로그인 (ETF API 인증 필수)
# ============================================================

def setup_krx_session() -> bool:
    """KRX 로그인 세션을 pykrx에 주입.

    Returns:
        True 로그인 성공, False 실패/자격증명 없음
    """
    import requests
    from pykrx.website.comm import webio

    _session = requests.Session()
    _session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd'
    })

    def _session_post_read(self, **params):
        return _session.post(self.url, headers=self.headers, data=params)

    webio.Post.read = _session_post_read

    if not KRX_USER_ID or not KRX_PASSWORD:
        logger.warning("KRX 계정 정보 없음 (.env에 KRX_USER_ID/KRX_PASSWORD 설정 필요)")
        return False

    try:
        _session.get("https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd")

        login_url = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
        login_data = {
            "mbrNm": "", "telNo": "", "di": "", "certType": "",
            "mbrId": KRX_USER_ID, "pw": KRX_PASSWORD,
        }
        response = _session.post(login_url, data=login_data)

        if response.status_code != 200:
            logger.error(f"KRX 로그인 실패 (HTTP {response.status_code})")
            return False

        result = response.json()
        if result.get("_error_code") == "CD001":
            logger.info("KRX 로그인 성공")
            return True

        # 중복 로그인 → skipDup 재시도
        if result.get("_error_code") == "CD011":
            login_data["skipDup"] = "Y"
            response = _session.post(login_url, data=login_data)
            result = response.json()
            if result.get("_error_code") == "CD001":
                logger.info("KRX 로그인 성공 (중복 로그인 해제)")
                return True

        logger.error(f"KRX 로그인 실패: {result.get('_error_message', 'Unknown')}")
        return False

    except Exception as e:
        logger.error(f"KRX 로그인 중 오류: {e}")
        return False


# 모듈 로드 시 자동 로그인
setup_krx_session()


# ============================================================
# 캐시 유틸
# ============================================================

def _cache_path(date: str, ticker: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR / f"cache_{date}_holdings_{ticker}.csv"


def _load_cache(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try:
            df = pd.read_csv(path, encoding='utf-8-sig', dtype={'티커': str, 'ETF_Ticker': str})
            logger.debug(f"캐시 로드: {path.name}")
            return df
        except Exception as e:
            logger.debug(f"캐시 로드 실패: {e}")
    return None


def _save_cache(df: pd.DataFrame, path: Path):
    try:
        df.to_csv(path, index=False, encoding='utf-8-sig')
        logger.debug(f"캐시 저장: {path.name}")
    except Exception as e:
        logger.debug(f"캐시 저장 실패: {e}")


def _retry(func, *args, **kwargs):
    """API 호출 재시도 (네트워크 일시 장애 대비)."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            logger.warning(f"API 호출 실패 (시도 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    raise last_exc


def _get_etf_mktcap(ticker: str, date: str) -> float:
    """snapshot에서 해당 ETF의 시가총액(MKTCAP) 조회. 없으면 0."""
    snap = _fetch_etf_full_snapshot(date)
    if snap is None:
        return 0
    row = snap[snap['ISU_SRT_CD'].astype(str) == str(ticker)]
    if row.empty:
        return 0
    return _parse_num(row['MKTCAP']).iloc[0]


# ============================================================
# 해외종목 가격 조회 (yfinance)
# ============================================================

_YF_TICKER_CACHE_PATH = DATA_DIR / "yf_ticker_cache.json"
_TICKER_MAP_PATH = DATA_DIR / "ticker_map.json"

_NAME_SUFFIXES = r'(-CL [A-Z]|-CLASS [A-Z]|-SP ADR|-ADR|-NY REG SHS|-SHS|-A$)'
_US_EXCHANGES = {'NMS', 'NYQ', 'PCX', 'NGM', 'NCM', 'ASE'}
_SKIP_KEYWORDS = ['설정현금', '원화현금', '외화현금', '선물', '예치금', '현금']


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save_json(data: dict, path: Path):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        logger.debug(f"JSON 저장 실패 ({path.name}): {e}")


def _resolve_yahoo_tickers(names: list[str]) -> dict[str, str]:
    """KRX 해외종목명 → Yahoo Finance 티커 매핑.

    우선순위: 수동 매핑 → 캐시 → yfinance Search (접미사 정리 + US 거래소 필터)
    """
    manual_map = _load_json(_TICKER_MAP_PATH)
    cache = _load_json(_YF_TICKER_CACHE_PATH)
    resolved = {}
    to_search = []

    for name in names:
        if name in manual_map:
            resolved[name] = manual_map[name]
        elif name in cache:
            resolved[name] = cache[name]
        else:
            to_search.append(name)

    if not to_search:
        return resolved

    logger.info(f"yfinance 티커 검색: {len(to_search)}개 종목")
    new_found = 0
    for name in to_search:
        cleaned = re.sub(_NAME_SUFFIXES, '', name).strip()
        try:
            s = yf.Search(cleaned)
            symbol = None
            for q in (s.quotes or []):
                if q.get('exchange') in _US_EXCHANGES:
                    symbol = q['symbol']
                    break
            if not symbol and s.quotes:
                symbol = s.quotes[0]['symbol']
            if symbol:
                resolved[name] = symbol
                cache[name] = symbol
                new_found += 1
        except Exception as e:
            logger.debug(f"yfinance 검색 실패 ({name}): {e}")

    if new_found:
        _save_json(cache, _YF_TICKER_CACHE_PATH)
        logger.info(f"yfinance 티커 매핑 완료: {new_found}개 신규")

    return resolved


def _fetch_foreign_prices_krw(
    name_to_symbol: dict[str, str], date: str
) -> dict[str, float]:
    """Yahoo 티커별 종가(KRW 환산)를 배치 조회."""
    if not name_to_symbol:
        return {}

    symbols = list(set(name_to_symbol.values()))
    all_symbols = symbols + ['USDKRW=X']

    # 해당 날짜 전후 7일 범위로 조회
    d = pd.Timestamp(f"{date[:4]}-{date[4:6]}-{date[6:8]}")
    start = (d - timedelta(days=7)).strftime('%Y-%m-%d')
    end = (d + timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        data = yf.download(all_symbols, start=start, end=end, progress=False)
        if data.empty:
            logger.warning("yfinance 가격 조회: 빈 데이터")
            return {}

        close = data['Close']
        if isinstance(close, pd.Series):
            close = close.to_frame(all_symbols[0])

        # 환율
        fx_rate = 1400.0
        if 'USDKRW=X' in close.columns:
            fx_col = close['USDKRW=X'].dropna()
            if not fx_col.empty:
                fx_rate = float(fx_col.iloc[-1])

        # 종목별 최신 종가 × 환율
        prices_krw = {}
        for name, symbol in name_to_symbol.items():
            if symbol in close.columns:
                price_col = close[symbol].dropna()
                if not price_col.empty:
                    prices_krw[name] = float(price_col.iloc[-1] * fx_rate)

        logger.info(
            f"해외종목 가격 조회: {len(prices_krw)}/{len(name_to_symbol)}개 성공 "
            f"(USD/KRW={fx_rate:.0f})"
        )
        return prices_krw

    except Exception as e:
        logger.error(f"yfinance 가격 조회 실패: {e}")
        return {}


def _enrich_foreign_holdings(
    df: pd.DataFrame, etf_ticker: str, date: str
) -> pd.DataFrame:
    """해외종목의 금액·비중을 yfinance 가격으로 보강한다."""
    amounts = pd.to_numeric(df['금액'], errors='coerce').fillna(0)
    shares = pd.to_numeric(df['계약수'], errors='coerce').fillna(0)

    # 해외종목 판별: 금액=0, 계약수>0, 비주식 아님
    foreign_names = []
    foreign_idx = []
    for idx in df.index:
        if amounts.loc[idx] == 0 and shares.loc[idx] > 0:
            name = str(df.loc[idx, '구성종목명'])
            if not any(kw in name for kw in _SKIP_KEYWORDS):
                foreign_names.append(name)
                foreign_idx.append(idx)

    if not foreign_names:
        return df

    # 1. 티커 매핑
    name_to_symbol = _resolve_yahoo_tickers(list(set(foreign_names)))
    if not name_to_symbol:
        logger.info(f"{etf_ticker}: 해외종목 {len(foreign_names)}개 티커 매핑 실패")
        return df

    # 2. 가격 조회 (KRW)
    prices_krw = _fetch_foreign_prices_krw(name_to_symbol, date)
    if not prices_krw:
        return df

    # 3. 금액 채우기
    df = df.copy()
    filled = 0
    for idx in foreign_idx:
        name = str(df.loc[idx, '구성종목명'])
        if name in prices_krw:
            qty = float(shares.loc[idx])
            df.loc[idx, '금액'] = int(qty * prices_krw[name])
            filled += 1

    # 4. 전체 비중 재계산 (sum(금액) 분모 — PDF는 CU 단위이므로 MKTCAP이 아님)
    new_amounts = pd.to_numeric(df['금액'], errors='coerce').fillna(0)
    total = new_amounts.sum()
    if total > 0:
        df['비중'] = (new_amounts / total * 100).round(4)
        logger.info(
            f"{etf_ticker}: 해외종목 {filled}/{len(foreign_names)}개 금액 보강, "
            f"비중 재계산 완료"
        )

    return df


# ============================================================
# ETF 구성종목 조회
# ============================================================

def get_etf_holdings(ticker: str, date: str) -> Optional[pd.DataFrame]:
    """개별 ETF의 구성종목을 조회하고 비중을 재계산한다.

    pykrx의 get_etf_portfolio_deposit_file은 '비중' 컬럼을 0으로 반환하는 경우가 많아,
    '금액' 컬럼을 ETF 총액으로 나눠 비중(%)을 재계산한다.

    Args:
        ticker: ETF 티커
        date: YYYYMMDD

    Returns:
        컬럼: [티커, 구성종목명, 계약수, 금액, 시가총액, 비중, ETF_Ticker, ETF_Name]
        실패 시 None.
    """
    cache = _cache_path(date, ticker)
    cached = _load_cache(cache)
    if cached is not None and not cached.empty:
        return cached

    try:
        df = _retry(stock.get_etf_portfolio_deposit_file, ticker, date)
        if df is None or df.empty:
            logger.warning(f"{ticker}@{date}: 구성종목 데이터 없음")
            return None

        # 인덱스(종목 티커)를 컬럼으로
        df = df.reset_index()
        if 'index' in df.columns:
            df = df.rename(columns={'index': '티커'})
        df['티커'] = df['티커'].astype(str)

        # 해외종목 금액 보강 (yfinance)
        if _HAS_YFINANCE and '금액' in df.columns and '구성종목명' in df.columns:
            df = _enrich_foreign_holdings(df, ticker, date)

        # 비중 재계산: pykrx의 '비중' 컬럼이 0으로만 차있으면 금액으로 역산
        # (PDF는 CU 단위 — sum(금액)이 분모)
        if '비중' in df.columns and '금액' in df.columns:
            weight_sum = pd.to_numeric(df['비중'], errors='coerce').fillna(0).sum()
            if weight_sum <= 0:
                amounts = pd.to_numeric(df['금액'], errors='coerce').fillna(0)
                total = amounts.sum()
                if total > 0:
                    df['비중'] = (amounts / total * 100).round(4)
                    logger.debug(f"{ticker}: 비중 재계산 (분모=sum(금액))")

        # ETF 식별 컬럼 추가
        df['ETF_Ticker'] = ticker
        try:
            df['ETF_Name'] = stock.get_etf_ticker_name(ticker)
        except Exception:
            df['ETF_Name'] = ticker

        _save_cache(df, cache)
        return df

    except Exception as e:
        logger.error(f"{ticker}@{date} 구성종목 조회 실패: {e}")
        return None


def get_etf_name(ticker: str) -> str:
    """ETF 이름 조회 (실패 시 티커 그대로 반환)."""
    try:
        return stock.get_etf_ticker_name(ticker)
    except Exception:
        return ticker


# ============================================================
# ETF 전종목 시세 / 동적 선정
# ============================================================

def _fetch_etf_full_snapshot(date: str) -> Optional[pd.DataFrame]:
    """전종목 시세 + 순자산 + 상장좌수 포함 snapshot.

    pykrx의 공개 wrapper에는 MKTCAP/LIST_SHRS가 노출되지 않아, 내부 KRX 클래스를 직접 호출.
    캐시: data/cache_{date}_etf_snapshot.csv
    """
    cache = DATA_DIR / f"cache_{date}_etf_snapshot.csv"
    if cache.exists():
        try:
            return pd.read_csv(cache, encoding='utf-8-sig', dtype={'ISU_SRT_CD': str})
        except Exception:
            pass

    try:
        from pykrx.website.krx.etx.core import 전종목시세_ETF
        df = _retry(전종목시세_ETF().fetch, date)
        if df is None or df.empty:
            return None
        _save_cache(df, cache)
        return df
    except Exception as e:
        logger.error(f"ETF 전종목 시세 조회 실패 ({date}): {e}")
        return None


def _parse_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(',', '', regex=False), errors='coerce').fillna(0)


def select_target_etfs(date: str) -> list[dict]:
    """대상 ETF 선정: 우선 운용사 각 N개 + 나머지 전체 AUM 상위 N개.

    PRIORITY_MANAGERS(TIME, KoAct) 각각 AUM 상위 TOP_N_PER_MANAGER개를 먼저 확보한 뒤,
    나머지 전체 equity 액티브 ETF 중 중복 없이 AUM 상위 TOP_N_OTHER개를 추가.

    Returns:
        [{'ticker': str, 'name': str, 'mktcap': float, 'trading_value': float,
          'group': 'TIME' | 'KoAct' | 'Other'}, ...]
    """
    df = _fetch_etf_full_snapshot(date)
    if df is None or df.empty:
        logger.warning(f"{date}: 전종목 snapshot 없음 — 대상 ETF 선정 실패")
        return []

    # '액티브' 포함 + 채권/금리/MM 제외
    active = df[df['ISU_ABBRV'].str.contains('액티브', na=False)].copy()
    if EXCLUDE_KEYWORDS:
        exclude_pattern = '|'.join(EXCLUDE_KEYWORDS)
        active = active[~active['ISU_ABBRV'].str.contains(exclude_pattern, na=False)]

    active['MKTCAP_NUM'] = _parse_num(active['MKTCAP'])
    active['TRDVAL_NUM'] = _parse_num(active['ACC_TRDVAL'])
    active = active[active['MKTCAP_NUM'] > 0]

    # [Step 1] 우선 운용사별 AUM 상위 N개
    picked_tickers = set()
    result = []

    for mgr in PRIORITY_MANAGERS:
        mgr_df = active[active['ISU_ABBRV'].str.startswith(mgr)]
        top = mgr_df.nlargest(TOP_N_PER_MANAGER, 'MKTCAP_NUM')
        for _, r in top.iterrows():
            t = str(r['ISU_SRT_CD'])
            picked_tickers.add(t)
            result.append({
                'ticker': t,
                'name': str(r['ISU_ABBRV']),
                'mktcap': float(r['MKTCAP_NUM']),
                'trading_value': float(r['TRDVAL_NUM']),
                'group': mgr,
            })
        logger.info(f"  {mgr}: AUM 상위 {len(top)}개 선정")

    # [Step 2] 나머지 전체에서 AUM 상위 N개 (중복 제외)
    remaining = active[~active['ISU_SRT_CD'].astype(str).isin(picked_tickers)]
    top_other = remaining.nlargest(TOP_N_OTHER, 'MKTCAP_NUM')
    for _, r in top_other.iterrows():
        result.append({
            'ticker': str(r['ISU_SRT_CD']),
            'name': str(r['ISU_ABBRV']),
            'mktcap': float(r['MKTCAP_NUM']),
            'trading_value': float(r['TRDVAL_NUM']),
            'group': 'Other',
        })

    mgr_counts = [f"{m} {sum(1 for r in result if r['group']==m)}" for m in PRIORITY_MANAGERS]
    other_count = sum(1 for r in result if r['group'] == 'Other')
    logger.info(f"대상 ETF 선정: {len(result)}개 ({', '.join(mgr_counts)}, Other {other_count})")
    return result


# ============================================================
# 신규 상장 액티브 ETF 감지
# ============================================================

def find_newly_listed_active_etfs(today_date: str, prev_date: str) -> list[dict]:
    """prev_date에는 없고 today_date에 존재하는 '액티브' ETF 탐지.

    Returns:
        [{'ticker': str, 'name': str}, ...]
    """
    today_df = _fetch_etf_full_snapshot(today_date)
    prev_df = _fetch_etf_full_snapshot(prev_date)
    if today_df is None or prev_df is None:
        return []

    prev_tickers = set(prev_df['ISU_SRT_CD'].astype(str))
    today_active = today_df[today_df['ISU_ABBRV'].str.contains('액티브', na=False)].copy()

    newly = today_active[~today_active['ISU_SRT_CD'].astype(str).isin(prev_tickers)]
    if newly.empty:
        return []

    return [
        {'ticker': str(r['ISU_SRT_CD']), 'name': str(r['ISU_ABBRV'])}
        for _, r in newly.iterrows()
    ]
