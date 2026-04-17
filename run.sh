#!/usr/bin/env bash
# Active ETF Analyzer — cron 실행용 래퍼 스크립트
#
# crontab 등록 예시 (평일 09:00):
#   0 9 * * 1-5 /path/to/active-etf-analyzer/run.sh
#
# 또는 매일 실행 (휴일은 main.py가 자동 스킵):
#   0 9 * * * /path/to/active-etf-analyzer/run.sh

set -euo pipefail

# 프로젝트 루트 (이 스크립트가 있는 디렉토리)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 로그 파일 (최근 실행 기록 보관)
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"

# venv 활성화 (있으면)
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# 실행 + 로그 기록
echo "[$(date)] Active ETF Analyzer 시작" | tee "$LOG_FILE"
python "$SCRIPT_DIR/main.py" 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date)] 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"

# 오래된 로그 정리 (30일 이전)
find "$LOG_DIR" -name "run_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
