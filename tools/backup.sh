#!/usr/bin/env bash
# backup.sh — News Sentry 数据备份脚本
#
# 每日增量备份 + 每周全量备份，保留 4 周全量。
# 配合 cron 使用:
#   0 3 * * * /path/to/tools/backup.sh --data-dir /app/data --backup-dir /app/backups
#
# 用法:
#   ./tools/backup.sh [--data-dir DIR] [--backup-dir DIR] [--keep-weeks N]
#
set -euo pipefail

# ── 默认值 ──
DATA_DIR="${NEWSSENTRY_DATA_DIR:-./data}"
BACKUP_DIR="${NEWSSENTRY_BACKUP_DIR:-./backups}"
KEEP_WEEKS=4

while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-dir)    DATA_DIR="$2"; shift 2 ;;
        --backup-dir)  BACKUP_DIR="$2"; shift 2 ;;
        --keep-weeks)  KEEP_WEEKS="$2"; shift 2 ;;
        --help)        head -12 "$0" | tail -9; exit 0 ;;
        *)             echo "未知选项: $1"; exit 1 ;;
    esac
done

if [[ ! -d "${DATA_DIR}" ]]; then
    echo "ERROR: 数据目录不存在: ${DATA_DIR}" >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"

# ── 备份类型 ──
DOW=$(date +%u)  # 1=周一, 7=周日
TIMESTAMP=$(date +"%Y%m%dT%H%M%S")
IS_FULL=false

if [[ "${DOW}" == "1" ]]; then
    # 周一做全量备份
    IS_FULL=true
    SUFFIX="full"
else
    SUFFIX="incr"
fi

BACKUP_FILE="${BACKUP_DIR}/news-sentry-${TIMESTAMP}-${SUFFIX}.tar.gz"

# ── 执行备份 ──
if [[ "${IS_FULL}" == true ]]; then
    tar -czf "${BACKUP_FILE}" -C "$(dirname "${DATA_DIR}")" "$(basename "${DATA_DIR}")" 2>/dev/null
else
    # 增量：仅备份 24h 内修改的文件
    tar -czf "${BACKUP_FILE}" -C "$(dirname "${DATA_DIR}")" \
        --newer-mtime="$(date -d '1 day ago' +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)" \
        "$(basename "${DATA_DIR}")" 2>/dev/null || \
    # fallback：如果增量无文件，跳过
    true
fi

# 检查备份文件是否有效
if [[ -f "${BACKUP_FILE}" ]] && [[ $(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null) -gt 0 ]]; then
    echo "[${TIMESTAMP}] 备份完成: $(basename "${BACKUP_FILE}") ($(du -h "${BACKUP_FILE}" | cut -f1))"
else
    # 无增量文件时删除空备份
    rm -f "${BACKUP_FILE}" 2>/dev/null || true
    echo "[${TIMESTAMP}] 增量备份跳过（无新文件）"
fi

# ── 清理过期备份 ──
# 保留最近 KEEP_WEEKS 周的全量备份，每日增量保留 7 天
if [[ "${IS_FULL}" == true ]]; then
    # 清理超过 KEEP_WEEKS 周的全量备份
    FULL_COUNT=$(find "${BACKUP_DIR}" -name "news-sentry-*-full.tar.gz" | wc -l | tr -d ' ')
    if [[ "${FULL_COUNT}" -gt "${KEEP_WEEKS}" ]]; then
        find "${BACKUP_DIR}" -name "news-sentry-*-full.tar.gz" -type f \
            | sort | head -n $((FULL_COUNT - KEEP_WEEKS)) \
            | xargs rm -f 2>/dev/null || true
        echo "清理过期全量备份: 保留最近 ${KEEP_WEEKS} 份"
    fi
fi

# 清理 7 天以上的增量备份
find "${BACKUP_DIR}" -name "news-sentry-*-incr.tar.gz" -type f -mtime +7 \
    -delete 2>/dev/null || true

exit 0
