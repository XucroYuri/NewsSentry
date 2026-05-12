#!/usr/bin/env bash
# health_monitor.sh — News Sentry 基础健康监控
#
# 检查内存、磁盘、Docker 容器状态，超阈值时输出告警。
# 可配合 cron 定期执行，告警写入 /app/data/logs/health/。
#
# 用法:
#   ./tools/health_monitor.sh [--container NAME] [--mem WARN CRIT] [--disk WARN CRIT]
#
# 选项:
#   --container NAME  监控的容器名 (默认: news-sentry)
#   --mem WARN CRIT   内存告警阈值 % (默认: 90 95)
#   --disk WARN CRIT  磁盘告警阈值 % (默认: 85 95)
#   --quiet           仅输出告警，不输出正常状态
#   --json            JSON 格式输出
#
set -euo pipefail

# ── 默认值 ──
CONTAINER="news-sentry"
MEM_WARN=90
MEM_CRIT=95
DISK_WARN=85
DISK_CRIT=95
QUIET=false
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --container) CONTAINER="$2"; shift 2 ;;
        --mem)       MEM_WARN="$2"; MEM_CRIT="$3"; shift 3 ;;
        --disk)      DISK_WARN="$2"; DISK_CRIT="$3"; shift 3 ;;
        --quiet)     QUIET=true; shift ;;
        --json)      JSON_OUTPUT=true; shift ;;
        --help)      head -15 "$0" | tail -12; exit 0 ;;
        *)           echo "未知选项: $1"; exit 1 ;;
    esac
done

# ── 收集指标 ──
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# 内存使用率（兼容 macOS 和 Linux）
if command -v free &>/dev/null; then
    MEM_INFO=$(free | awk '/Mem:/ {printf "%.1f %.1f %.1f", $3/$2*100, $3/1024/1024, $2/1024/1024}')
else
    # macOS: 用 vm_stat 计算
    PAGE_SIZE=$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)
    MEM_TOTAL_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    MEM_TOTAL_GB=$(echo "scale=1; ${MEM_TOTAL_BYTES}/1024/1024/1024" | bc)
    FREE_PAGES=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
    INACTIVE_PAGES=$(vm_stat | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
    FREE_BYTES=$(( (FREE_PAGES + INACTIVE_PAGES) * PAGE_SIZE ))
    USED_BYTES=$(( MEM_TOTAL_BYTES - FREE_BYTES ))
    MEM_USED_GB=$(echo "scale=1; ${USED_BYTES}/1024/1024/1024" | bc)
    MEM_PCT=$(echo "scale=1; ${USED_BYTES}*100/${MEM_TOTAL_BYTES}" | bc)
fi
MEM_PCT=$(echo "$MEM_PCT" | awk '{print $1}')
MEM_USED_GB=$(echo "$MEM_USED_GB" | awk '{print $1}')
MEM_TOTAL_GB=$(echo "$MEM_TOTAL_GB" | awk '{print $1}')

# 磁盘使用率（/app/data 挂载点或根分区）
DATA_DIR="${DATA_DIR:-/app/data}"
if [[ -d "${DATA_DIR}" ]]; then
    DISK_INFO=$(df "${DATA_DIR}" | awk 'NR==2 {printf "%.1f %d %d", $5+0, $3/1024/1024, $4/1024/1024}')
else
    DISK_INFO=$(df / | awk 'NR==2 {printf "%.1f %d %d", $5+0, $3/1024/1024, $4/1024/1024}')
fi
DISK_PCT=$(echo "$DISK_INFO" | awk '{print $1}')
DISK_USED_GB=$(echo "$DISK_INFO" | awk '{print $2}')
DISK_AVAIL_GB=$(echo "$DISK_INFO" | awk '{print $3}')

# Docker 容器状态
CONTAINER_STATUS="not_found"
CONTAINER_UPTIME=""
CONTAINER_RESTARTS=0
if command -v docker &>/dev/null; then
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
        CONTAINER_STATUS=$(docker inspect --format '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || echo "unknown")
        CONTAINER_UPTIME=$(docker inspect --format '{{.State.StartedAt}}' "${CONTAINER}" 2>/dev/null || echo "")
        CONTAINER_RESTARTS=$(docker inspect --format '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo "0")
    fi
fi

# ── 告警判断 ──
ALARMS=()

if (( $(echo "$MEM_PCT >= $MEM_CRIT" | bc -l) )); then
    ALARMS+=("CRITICAL: 内存 ${MEM_PCT}% >= ${MEM_CRIT}% (已用 ${MEM_USED_GB}GB / ${MEM_TOTAL_GB}GB)")
elif (( $(echo "$MEM_PCT >= $MEM_WARN" | bc -l) )); then
    ALARMS+=("WARNING: 内存 ${MEM_PCT}% >= ${MEM_WARN}% (已用 ${MEM_USED_GB}GB / ${MEM_TOTAL_GB}GB)")
fi

if (( $(echo "$DISK_PCT >= $DISK_CRIT" | bc -l) )); then
    ALARMS+=("CRITICAL: 磁盘 ${DISK_PCT}% >= ${DISK_CRIT}% (可用 ${DISK_AVAIL_GB}GB)")
elif (( $(echo "$DISK_PCT >= $DISK_WARN" | bc -l) )); then
    ALARMS+=("WARNING: 磁盘 ${DISK_PCT}% >= ${DISK_WARN}% (可用 ${DISK_AVAIL_GB}GB)")
fi

if [[ "$CONTAINER_STATUS" != "running" ]]; then
    ALARMS+=("CRITICAL: 容器 ${CONTAINER} 状态=${CONTAINER_STATUS}")
fi

if [[ "$CONTAINER_RESTARTS" -gt 3 ]]; then
    ALARMS+=("WARNING: 容器 ${CONTAINER} 重启次数=${CONTAINER_RESTARTS}")
fi

# ── 输出 ──
if [[ "$JSON_OUTPUT" == true ]]; then
    ALARMS_JSON=$(printf '%s\n' "${ALARMS[@]+"${ALARMS[@]}"}" | jq -R . | jq -s . 2>/dev/null || echo "[]")
    cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "memory_pct": ${MEM_PCT},
  "memory_used_gb": ${MEM_USED_GB},
  "memory_total_gb": ${MEM_TOTAL_GB},
  "disk_pct": ${DISK_PCT},
  "disk_used_gb": ${DISK_USED_GB},
  "disk_avail_gb": ${DISK_AVAIL_GB},
  "container": "${CONTAINER}",
  "container_status": "${CONTAINER_STATUS}",
  "container_restarts": ${CONTAINER_RESTARTS},
  "alarms": ${ALARMS_JSON},
  "alarm_count": ${#ALARMS[@]}
}
EOF
else
    if [[ "$QUIET" == false ]] || [[ ${#ALARMS[@]} -gt 0 ]]; then
        echo "[${TIMESTAMP}] 健康检查"
        echo "  内存: ${MEM_PCT}% (${MEM_USED_GB}GB / ${MEM_TOTAL_GB}GB)"
        echo "  磁盘: ${DISK_PCT}% (可用 ${DISK_AVAIL_GB}GB)"
        echo "  容器: ${CONTAINER} → ${CONTAINER_STATUS} (重启 ${CONTAINER_RESTARTS} 次)"
        for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
            echo "  ⚠ ${alarm}"
        done
    fi
fi

# ── 写入日志（仅 /app/data 存在时） ──
LOG_DIR="/app/data/logs/health"
if [[ -d "/app/data" ]]; then
    mkdir -p "${LOG_DIR}" 2>/dev/null || true
    if [[ -d "${LOG_DIR}" ]]; then
        LOG_FILE="${LOG_DIR}/health-$(date -u +"%Y%m%d").jsonl"
        ALARMS_JSON=$(printf '%s\n' "${ALARMS[@]+"${ALARMS[@]}"}" | jq -R . | jq -s . 2>/dev/null || echo "[]")
        echo "{\"timestamp\":\"${TIMESTAMP}\",\"memory_pct\":${MEM_PCT},\"disk_pct\":${DISK_PCT},\"container_status\":\"${CONTAINER_STATUS}\",\"alarms\":${ALARMS_JSON}}" >> "${LOG_FILE}"
    fi
fi

# 返回码：有 CRITICAL 告警时返回 2，WARNING 返回 1，正常返回 0
for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
    if [[ "$alarm" == CRITICAL* ]]; then
        exit 2
    fi
done
for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
    if [[ "$alarm" == WARNING* ]]; then
        exit 1
    fi
done
exit 0
