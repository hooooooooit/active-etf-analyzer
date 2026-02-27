# Active ETF Analyzer

KRX 상장 액티브 ETF의 구성 종목을 분석하고, 전일 대비 변동을 추적하여 PDF 리포트를 생성하는 도구

## 프로젝트 구조

```
stock_ws/
├── main.py              # 메인 실행 파일 (전체 워크플로우 조율)
├── config.py            # 설정 파일 (경로, 필터링 조건, 폰트 등)
├── requirements.txt     # 의존성: pykrx, pandas, fpdf2, matplotlib
├── modules/
│   ├── data_fetcher.py  # pykrx로 ETF 데이터 수집 (티커, 구성종목, 수익률)
│   ├── analyzer.py      # 구성 종목 비중 분석 (컨센서스 계산, 변동 추적)
│   └── report_generator.py  # PDF 리포트 및 차트 생성
├── data/                # 일별 분석 결과 CSV (YYYYMMDD.csv)
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

## 코드 컨벤션

- 한글 주석 사용 (`[Step N]`, `[설명]` 형태)
- 로깅: `logging` 모듈 사용
- 날짜 형식: `YYYYMMDD` 문자열
- DataFrame 컬럼: PascalCase (StockName, TotalWeight 등)
