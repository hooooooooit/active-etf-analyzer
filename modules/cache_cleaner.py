"""
캐시 파일 자동 정리 모듈

data/ 디렉토리의 cache_*.csv, cache_*.json 파일 중
지정 일수(기본 7일)보다 오래된 파일을 삭제한다.
"""
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from config import DATA_DIR, CACHE_KEEP_DAYS

logger = logging.getLogger(__name__)

# 캐시 파일명에서 날짜 추출: cache_{YYYYMMDD}_...
_DATE_PATTERN = re.compile(r'^cache_(\d{8})_')


def cleanup_old_cache(keep_days: int = CACHE_KEEP_DAYS) -> int:
    """지정 일수보다 오래된 캐시 파일을 삭제한다.

    Args:
        keep_days: 보관할 일수 (이보다 오래된 파일 삭제)

    Returns:
        삭제된 파일 수
    """
    if not DATA_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y%m%d")

    deleted = 0
    for path in DATA_DIR.glob("cache_*"):
        match = _DATE_PATTERN.match(path.name)
        if not match:
            continue

        file_date = match.group(1)
        if file_date < cutoff_str:
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                logger.warning(f"캐시 삭제 실패: {path.name} — {e}")

    if deleted:
        logger.info(f"오래된 캐시 {deleted}개 삭제 (보관 기준: {keep_days}일)")

    return deleted
