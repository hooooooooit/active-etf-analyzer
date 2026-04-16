# Active ETF Analyzer

KRX 상장 equity 액티브 ETF(AUM 상위, 매일 동적 선정)의 **전 영업일(D-1) vs 전전 영업일(D-2)** 구성종목 **계약수(주수) 변화**를 기준으로 실제 운용 의사결정(매수/매도/편입/편출)만 추출하여 Slack Incoming Webhook으로 전송하는 자동화 도구. Claude routine으로 매일 아침 cron 실행 전제.

> **Claude 작업 지침**: 기능이 추가되거나 삭제될 때 반드시 이 문서를 업데이트할 것

## 프로젝트 구조

```
stock_ws/
├── main.py                    # 메인 실행 (7단계 워크플로우: 분석 + 캐시 정리)
├── config.py                  # 선정 파라미터, 제외 키워드, 임계값, Slack/KRX 자격증명
├── requirements.txt           # pykrx, pandas, requests, python-dotenv, yfinance
├── run.sh                     # cron 실행용 래퍼 (venv 활성화 + 로그 + 실행)
├── .env.example               # SLACK_WEBHOOK_URL, KRX_USER_ID, KRX_PASSWORD
├── modules/
│   ├── business_day.py        # pykrx 기반 영업일 탐색
│   ├── data_fetcher.py        # KRX 로그인 + 전종목 snapshot + 동적 ETF 선정 + 구성종목 수집(+비중 재계산+해외종목 yfinance 보강) + 캐싱 + 신규 상장 감지
│   ├── analyzer.py            # ETF별 diff + 공통 시그널 집계
│   ├── cache_cleaner.py       # 오래된 캐시 파일 자동 정리 (날짜 기반)
│   └── slack_notifier.py      # Block Kit 렌더 + webhook POST (신규 상장 섹션 포함)
├── logs/                      # cron 실행 로그 (자동 생성, 30일 보관)
└── data/                      # ETF별 일자별 홀딩 캐시 + 전종목 snapshot 캐시
    ├── ticker_map.json        # 해외종목 수동 매핑 (yfinance Search 실패분)
    ├── yf_ticker_cache.json   # yfinance 티커 검색 결과 캐시 (자동 축적)
    ├── pykrx_readme.md        # pykrx 전체 문서 (25,000+ 토큰, 직접 읽지 말 것)
    └── pykrx_api_index.md     # API 인덱스 (이것부터 참조)
```

## 실행 방법

```bash
# 오늘 기준 (어제 vs 그저께 비교) → Slack 전송
python main.py

# 특정 날짜 기준 (해당 날짜 이전의 영업일 2일 비교)
python main.py --date 20260306

# Slack 전송 없이 Block Kit JSON만 stdout 출력
python main.py --dry-run
```

휴일(주말/공휴일)에 실행되면 영업일 2일을 찾지 못해 **조용히 exit 0** (Slack 전송 없음).

### cron 스케줄링 (매일 09:00)

```bash
# crontab -e 로 등록
# 평일만 실행 (1-5 = 월~금)
0 9 * * 1-5 /path/to/active-etf-analyzer/run.sh

# 또는 매일 실행 (휴일은 main.py가 자동 스킵하므로 매일 돌려도 무방)
0 9 * * * /path/to/active-etf-analyzer/run.sh
```

`run.sh`가 처리하는 것: venv 자동 활성화, `logs/` 디렉토리에 실행 로그 기록 (30일 보관), `.env`는 `config.py`에서 절대경로로 로드하므로 cron 환경에서도 정상 동작.

## 주요 워크플로우 (main.py)

1. 기준일 이전 최근 영업일 2개 탐색 (D-1, D-2) — 부족하면 휴일 스킵
2. **대상 ETF 동적 선정**: '액티브' ETF 중 `EXCLUDE_KEYWORDS`(채권/금리/MMF 등)를 제외한 equity 계열에서, `PRIORITY_MANAGERS`(TIME/KoAct) 각 AUM 상위 `TOP_N_PER_MANAGER`개 + 나머지 전체 AUM 상위 `TOP_N_OTHER`개 (중복 제외) = 총 15개
3. **신규 상장 액티브 ETF 감지**: D-2에는 없고 D-1에 존재하는 '액티브' ETF 탐지
4. 대상 ETF에 대해 D-1, D-2 구성종목 수집 + 신규 상장 ETF의 D-1 구성종목 수집 (캐시 활용)
5. ETF별 비중 diff 계산 (`New/Out/Up/Down/Flat`) + 공통 시그널 집계 (N개 이상 ETF에서 동시 증가/신규 편입)
6. Block Kit 메시지 조립 (신규 상장 섹션 + 공통 시그널 + ETF별 diff) → Slack Incoming Webhook POST
7. **오래된 캐시 자동 정리** — `CACHE_KEEP_DAYS`(기본 7일) 이전의 `cache_*.csv` 파일 삭제

## 핵심 개념

| 용어 | 설명 |
|------|------|
| `Shares_Today` / `Shares_Prev` | D-1 / D-2 해당 ETF 내 종목 계약수(주수) |
| `Shares_Diff` | `Shares_Today - Shares_Prev` — **실제 매매 판별 기준** |
| `Weight_Today` / `Weight_Prev` | D-1 / D-2 비중 (%) — 참고 표시용 |
| `Status` | `New` (신규 편입) / `Out` (편출) / `Buy` (계약수 증가=매수) / `Sell` (계약수 감소=매도) / `Hold` (계약수 동일, 비중 변화는 주가에 의한 것) |
| 공통 시그널 | 여러 ETF에서 동시에 `New` 또는 `Buy` 상태인 종목 — **카운트 기반** 집계 |

**비중 재계산**: pykrx의 `get_etf_portfolio_deposit_file`은 `비중` 컬럼을 0으로 반환하는 경우가 있어, `data_fetcher.py`에서 `금액` 컬럼을 `sum(금액)` (CU 단위 총액)으로 나눠 비중을 재계산한다. PDF 데이터는 ETF 전체가 아닌 **설정단위(CU)당** 데이터이므로 MKTCAP이 아닌 sum(금액)이 올바른 분모.

**해외종목 가격 보강**: KRX는 해외 상장 종목에 대해 `금액=0`을 반환한다. `yfinance`로 해외 주가를 조회하고 USD/KRW 환율을 곱해 `금액`을 채운 뒤 비중을 재계산한다. 종목명→Yahoo 티커 매핑은 `yfinance.Search` 자동 검색(접미사 정리 + US 거래소 필터, 92% 성공률) + `data/ticker_map.json` 수동 매핑(실패분 ~9개). 매핑 결과는 `data/yf_ticker_cache.json`에 영구 캐싱.

**계약수 기준 분석**: 비중 변화는 주가 등락에 의한 패시브 변화를 포함하므로, `계약수`(주수)가 실제로 변한 종목만 변화로 보고한다. 주가에 의한 비중 변동은 `Hold`로 무시.

## 설정 (config.py)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `PRIORITY_MANAGERS` | `['TIME', 'KoAct']` | 우선 운용사 (각각 AUM 상위 N개씩 먼저 확보) |
| `TOP_N_PER_MANAGER` | 5 | 우선 운용사당 AUM 상위 N개 |
| `TOP_N_OTHER` | 5 | 나머지 전체 AUM 상위 N개 (우선 운용사와 중복 제외) |
| `EXCLUDE_KEYWORDS` | `금리`, `채권`, `머니마켓`, `국채`, `국고채`, `회사채`, `금융채`, `단기채`, `특수은행채`, `은행채`, `CD`, `KOFR`, `MMF` | 채권/금리/MMF 계열 액티브 ETF 제외 (구성종목 diff 의미 없음) |
| `COMMON_SIGNAL_MIN_ETFS` | 3 | 공통 시그널 인정 최소 ETF 수 |
| `MAX_CHANGES_PER_ETF` | 5 | Slack 메시지에 ETF당 표시할 카테고리별 종목 수 |
| `NEW_LISTING_TOP_N` | 10 | 신규 상장 ETF 섹션에 표시할 상위 종목 수 |
| `CACHE_KEEP_DAYS` | 7 | 캐시 파일 보관 일수 (이전 파일 자동 삭제) |
| `MAX_RETRIES` / `RETRY_DELAY` | 3 / 1 | API 재시도 |

## 환경변수 (.env)

`.env.example` 참고. `python-dotenv`로 자동 로드.

- `SLACK_WEBHOOK_URL` — Slack Incoming Webhook URL
- `KRX_USER_ID`, `KRX_PASSWORD` — https://data.krx.co.kr 계정 (ETF API는 인증 필수)

## 의존성

- **pykrx**: KRX ETF 데이터 조회
- **pandas**: DataFrame 처리
- **requests**: Slack webhook POST
- **python-dotenv**: `.env` 로드
- **yfinance**: 해외종목 주가 + USD/KRW 환율 조회 (미설치 시 계약수 변화율 폴백)

## 캐싱 (data_fetcher.py)

| 함수 | 캐시 파일 | 형식 |
|------|----------|------|
| `get_etf_holdings(ticker, date)` | `data/cache_{date}_holdings_{ticker}.csv` | CSV (해외종목 금액 보강 + 재계산된 비중 포함) |
| `_fetch_etf_full_snapshot(date)` | `data/cache_{date}_etf_snapshot.csv` | CSV (전종목 MKTCAP/ACC_TRDVAL/LIST_SHRS 포함, 동적 선정·신규 상장 감지용) |
| `_resolve_yahoo_tickers()` | `data/yf_ticker_cache.json` | JSON (종목명→Yahoo 티커, 영구) |
| (수동 매핑) | `data/ticker_map.json` | JSON (yfinance Search 실패 종목 ~9개) |
| `cleanup_old_cache()` | `data/cache_*` 중 오래된 파일 삭제 | `CACHE_KEEP_DAYS`(7일) 기준, 파일명의 날짜로 판별 |

## Slack 메시지 구성 (slack_notifier.py)

Block Kit 구조:

1. **Header** — 📅 `{날짜} Active ETF 비중 변화 (전일 vs 전전일)`
2. **신규 상장 Section** (있을 때만) — 🆕 당일(D-1) 신규 상장된 '액티브' ETF의 상위 `NEW_LISTING_TOP_N` 구성종목
3. **Divider** (신규 상장 있을 때만)
4. **공통 시그널 Section** (있을 때만) — N개 이상 ETF에서 동시에 증가/신규 편입된 종목 불릿 리스트
5. **Divider**
6. **ETF별 Section** (운용사별 그룹핑, 변화 있는 ETF만) — 각 섹션에 `신규 / 증가 / 감소 / 편출` 라벨로 요약. 카테고리당 `MAX_CHANGES_PER_ETF` 개로 제한
7. **Context footer** — 분석 ETF 수, 변화 감지 수, D-2 날짜

Block 50개 제한 도달 시 "일부만 표시" 안내 블록 추가.

## 코드 컨벤션

- 한글 주석 사용 (`[Step N]`, `[설명]` 형태)
- 로깅: `logging` 모듈
- 날짜 형식: `YYYYMMDD` 문자열
- DataFrame 컬럼: PascalCase (`StockName`, `Weight_Today` 등)

---

## Claude 작업 지침

### 작업 시작 전 필수 사항

**pykrx API 문서 최신화** (하루 1회)

1. `data/pykrx_readme.md` 상단의 `<!-- last_updated: YYYYMMDD -->` 확인
2. 당일 날짜와 다르면 https://github.com/sharebook-kr/pykrx 의 README.md를 WebFetch로 가져와 업데이트
3. 당일 이미 최신화된 경우 스킵

**pykrx API 참조 방법**

전체 문서는 25,000+ 토큰이므로 전체를 읽지 말 것.

1. **인덱스 먼저**: `data/pykrx_api_index.md`에서 라인 위치 확인
2. **해당 부분만**: `Read data/pykrx_readme.md --offset {라인} --limit 30`
3. **검색 활용**: `Grep "get_etf_portfolio" data/pykrx_readme.md`

```
# 현재 사용 중인 API
stock.get_etf_ticker_name(ticker)                  # ETF 이름
stock.get_etf_ohlcv_by_date(start, end, ticker)    # 영업일 판정용
stock.get_etf_portfolio_deposit_file(ticker, date) # 구성종목(PDF) — CU 단위
# 내부 클래스 직접 호출 (공개 wrapper 미노출 필드 사용)
pykrx.website.krx.etx.core.전종목시세_ETF().fetch(date)
  # → MKTCAP(시총), ACC_TRDVAL(거래대금), LIST_SHRS(상장좌수), NAV, ISU_ABBRV 등
# yfinance (해외종목 가격 보강)
yf.Search(name)               # 회사명 → Yahoo 티커 검색
yf.download(tickers, ...)     # 종가 배치 조회
yf.Ticker('USDKRW=X')        # 환율 조회
```

---

### 문서 유지보수

**기능 추가/삭제/수정 시 이 문서에 반영해야 할 항목:**

1. **프로젝트 구조**: 파일 추가/삭제 시 트리 업데이트
2. **주요 워크플로우**: 실행 흐름 변경 시 업데이트
3. **핵심 개념**: 새로운 용어/개념 추가 시 설명 추가
4. **설정**: config.py 변수 추가/삭제 시 테이블 업데이트
5. **환경변수**: 새 환경변수 추가 시 목록 업데이트
6. **캐싱**: 캐시 파일 형식 변경 시 테이블 업데이트
7. **Slack 메시지 구성**: Block 구조 변경 시 업데이트
8. **의존성**: 새 라이브러리 추가 시 목록 업데이트
