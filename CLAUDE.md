# Active ETF Analyzer

KRX 상장 액티브 ETF의 구성 종목을 분석하고, 전일 대비 변동을 추적하여 PDF 리포트를 생성하는 도구

> **Claude 작업 지침**: 기능이 추가되거나 삭제될 때 반드시 이 문서를 업데이트할 것

## 프로젝트 구조

```
stock_ws/
├── main.py              # 메인 실행 파일 (전체 워크플로우 조율)
├── config.py            # 설정 파일 (경로, 필터링 조건, 폰트 등)
├── requirements.txt     # 의존성: pykrx, pandas, fpdf2, matplotlib
├── modules/
│   ├── data_fetcher.py  # pykrx로 ETF 데이터 수집 (티커, 구성종목, 수익률) + 캐싱
│   ├── analyzer.py      # 구성 종목 비중 분석 (컨센서스 계산, 변동 추적)
│   └── report_generator.py  # PDF 리포트 및 차트 생성
├── data/                # 일별 분석 결과 CSV + 캐시 파일
│   ├── pykrx_readme.md  # pykrx 전체 문서 (25,000+ 토큰, 직접 읽지 말 것)
│   └── pykrx_api_index.md  # API 인덱스 (이것부터 참조)
└── reports/             # PDF 리포트 및 차트 이미지
```

## 실행 방법

```bash
# 당일 기준 실행
python main.py

# 특정 날짜 기준
python main.py --date 20260227

# 옵션
python main.py --top-n 30         # 수익률 상위 30개 ETF 분석
python main.py --min-returns 5    # 최소 5% 이상 수익률 필터
```

## 주요 워크플로우 (main.py)

1. 전일 데이터 로드 (`data/{prev_date}.csv`)
2. 3개월 수익률 상위 액티브 ETF 필터링 (기본 20개)
3. ETF 기본 정보 조회 (종가, 수익률 등)
4. 각 ETF 구성 종목 수집 (PDF 데이터)
5. 전체 종목 합산 비중 분석 + 전일 대비 변동 계산
6. PDF 리포트 생성
7. 당일 데이터 저장 (다음 날 비교용)

## 핵심 개념

- **TotalWeight**: 여러 ETF에 편입된 종목의 비중 합계
- **AvgWeight**: 편입된 ETF 수로 나눈 평균 비중
- **ETF_Count**: 해당 종목이 편입된 ETF 수
- **Status**: New (신규 편입), Out (제외), Maintain (유지)
- **Weight_Diff**: 전일 대비 비중 변화량

## 설정 (config.py)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TOP_N_RETURNS` | 20 | 3개월 수익률 상위 N개 ETF 분석 |
| `MIN_RETURNS_3M` | 0 | 최소 수익률 기준 (%) |
| `LOOKBACK_DAYS` | 90 | 수익률 계산 기간 (일) |
| `TOP_N` | 10 | 리포트에 표시할 상위 종목 수 |

## 의존성

- **pykrx**: KRX 주식/ETF 데이터 조회
- **pandas**: 데이터 처리
- **fpdf2**: PDF 생성
- **matplotlib**: 차트 생성

## 캐싱 (data_fetcher.py)

API 호출 결과를 `data/` 폴더에 캐시하여 재실행 시 속도 향상

| 함수 | 캐시 파일 | 형식 |
|------|----------|------|
| `get_target_etfs()` | `cache_{날짜}_target_etfs_min{최소수익률}_top{N}.json` | JSON |
| `get_etf_holdings()` | `cache_{날짜}_holdings_{티커}.csv` | CSV |
| `get_etf_info()` | `cache_{날짜}_etf_info_{해시}.csv` | CSV |

## PDF 리포트 구성 (report_generator.py)

1. **Analysis Target ETF Overview** - 분석 대상 ETF 현황
2. **Consensus Holdings Top N** - 합산 보유 비중 상위 종목
3. **Weight Increase Top N** - 비중 급증 종목 (기존 보유 중)
4. **Weight Decrease Top N** - 비중 급감 종목 (기존 보유 중)
5. **ETF Returns Comparison** - 3개월 수익률 비교 차트

## 코드 컨벤션

- 한글 주석 사용 (`[Step N]`, `[설명]` 형태)
- 로깅: `logging` 모듈 사용
- 날짜 형식: `YYYYMMDD` 문자열
- DataFrame 컬럼: PascalCase (StockName, TotalWeight 등)

---

## Claude 작업 지침

### 작업 시작 전 필수 사항

**pykrx API 문서 최신화** (하루 1회)

작업 시작 전 `data/pykrx_readme.md` 파일의 최신화 여부를 확인하고, 당일 최신화 이력이 없으면 GitHub에서 최신 문서를 가져와 업데이트할 것.

1. `data/pykrx_readme.md` 파일 상단의 `last_updated` 날짜 확인
2. 당일 날짜와 다르면 https://github.com/sharebook-kr/pykrx 의 README.md를 WebFetch로 가져와 `data/pykrx_readme.md` 업데이트
3. 파일 상단에 아래 형식으로 최신화 날짜 기록:
   ```
   <!-- last_updated: YYYYMMDD -->
   ```
4. 당일 이미 최신화된 경우 스킵

**pykrx API 참조 방법**

전체 문서(`data/pykrx_readme.md`)는 25,000+ 토큰이므로 전체를 읽지 말 것.

1. **인덱스 먼저 확인**: `data/pykrx_api_index.md`에서 필요한 API의 라인 위치 확인
2. **해당 부분만 읽기**: `Read data/pykrx_readme.md --offset {라인} --limit 30`
3. **검색 활용**: `Grep "get_etf_portfolio" data/pykrx_readme.md`

```
# 현재 프로젝트에서 사용 중인 API
stock.get_etf_ticker_list(date)              # ETF 티커 목록
stock.get_etf_ticker_name(ticker)            # ETF 이름
stock.get_etf_ohlcv_by_date(start, end, ticker)  # ETF OHLCV
stock.get_etf_price_change_by_ticker(start, end) # 전종목 등락률
stock.get_etf_portfolio_deposit_file(ticker, date) # PDF(구성종목)
```

---

### 문서 유지보수

**기능 추가/삭제/수정 시 이 문서에 반영해야 할 항목:**

1. **프로젝트 구조**: 파일 추가/삭제 시 트리 업데이트
2. **주요 워크플로우**: 실행 흐름 변경 시 업데이트
3. **핵심 개념**: 새로운 용어/개념 추가 시 설명 추가
4. **설정**: config.py 변수 추가/삭제 시 테이블 업데이트
5. **캐싱**: 캐시 파일 형식 변경 시 테이블 업데이트
6. **PDF 리포트 구성**: 섹션 추가/삭제 시 목록 업데이트
7. **의존성**: 새 라이브러리 추가 시 목록 업데이트
