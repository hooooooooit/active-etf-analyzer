# pykrx API Index

> 전체 문서: `data/pykrx_readme.md` (25,000+ 토큰)
> 새 API가 필요하면 이 인덱스에서 위치 확인 후 해당 라인만 읽기

## 현재 프로젝트에서 사용 중인 API

| API | 용도 | 문서 라인 |
|-----|------|----------|
| `stock.get_etf_ticker_list(date)` | ETF 티커 목록 조회 | 1113 |
| `stock.get_etf_ticker_name(ticker)` | ETF 이름 조회 | 1132 |
| `stock.get_etf_ohlcv_by_date(start, end, ticker)` | ETF OHLCV 조회 | 1145 |
| `stock.get_etf_price_change_by_ticker(start, end)` | 전종목 등락률 조회 | 1203 |
| `stock.get_etf_portfolio_deposit_file(ticker, date)` | PDF(구성종목) 조회 | 1222 |

---

## API 카테고리별 인덱스

### Stock 모듈 (`from pykrx import stock`)

#### MarketData API (라인 85-708)
| 라인 | API | 설명 |
|------|-----|------|
| 88 | `get_market_ticker_list` | 주식 티커 목록 |
| 130 | `get_market_ohlcv_by_date` | 일자별 OHLCV |
| 182 | `get_market_ohlcv_by_ticker` | 전체 종목 시세 |
| 209 | `get_market_price_change_by_ticker` | 가격 변동 |
| 258 | `get_market_fundamental_by_ticker` | DIV/BPS/PER/EPS |
| 310 | `get_market_trading_value_by_date` | 거래대금 추이 |
| 490 | `get_market_trading_volume_by_date` | 거래량 추이 |
| 542 | `get_market_trading_volume_by_investor` | 투자자별 거래량 |
| 614 | `get_market_cap_by_ticker` | 시가총액 |
| 666 | `get_exhaustion_rates_of_foreign_investment_by_ticker` | 외국인 보유량 |

#### Index API (라인 708-892)
| 라인 | API | 설명 |
|------|-----|------|
| 711 | `get_index_ticker_list` | 인덱스 목록 |
| 785 | `get_index_portfolio_deposit_file` | 인덱스 구성종목 |
| 799 | `get_index_ohlcv_by_date` | 인덱스 OHLCV |
| 840 | `get_index_price_change_by_ticker` | 인덱스 등락률 |

#### Short Selling API (라인 892-1111)
| 라인 | API | 설명 |
|------|-----|------|
| 895 | `get_shorting_status_by_date` | 공매도 현황 |
| 912 | `get_shorting_volume_by_date` | 공매도 거래량 |
| 1027 | `get_shorting_balance_by_ticker` | 공매도 잔고 |

---

### ETF/ETN/ELW API (라인 1111-1407)

#### ETF (라인 1113-1357)
| 라인 | API | 설명 |
|------|-----|------|
| 1113 | `get_etf_ticker_list` | ETF 티커 목록 |
| 1132 | `get_etf_ticker_name` | ETF 이름 |
| 1145 | `get_etf_ohlcv_by_date` | ETF OHLCV |
| 1177 | `get_etf_ohlcv_by_ticker` | 전종목 OHLCV |
| 1203 | `get_etf_price_change_by_ticker` | 전종목 등락률 |
| 1222 | `get_etf_portfolio_deposit_file` | PDF (구성종목) |
| 1245 | `get_etf_tracking_error` | 괴리율 |
| 1262 | `get_etf_tracking_error_rate` | 추적오차율 |
| 1279 | `get_etf_trading_value_by_date` | 거래실적 |

#### ETN (라인 1358-1383)
| 라인 | API | 설명 |
|------|-----|------|
| 1358 | `get_etn_ticker_list` | ETN 티커 목록 |
| 1368 | `get_etn_ticker_name` | ETN 이름 |

#### ELW (라인 1384-1407)
| 라인 | API | 설명 |
|------|-----|------|
| 1384 | `get_elw_ticker_list` | ELW 티커 목록 |
| 1394 | `get_elw_ticker_name` | ELW 이름 |

---

### Bond 모듈 (`from pykrx import bond`) (라인 1407-1455)
| 라인 | API | 설명 |
|------|-----|------|
| 1410 | `get_otc_treasury_yields` | 장외 채권수익률 |
| 1450 | `get_government_bond_yield` | 지표 수익률 |

---

## 검색 팁

```bash
# 특정 API 문서 찾기
Grep "get_etf_portfolio" data/pykrx_readme.md

# 특정 라인 범위 읽기 (예: ETF PDF API)
Read data/pykrx_readme.md --offset 1222 --limit 30
```
