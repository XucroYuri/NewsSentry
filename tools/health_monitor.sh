#!/usr/bin/env bash
# health_monitor.sh - News Sentry host health monitor.
#
# Usage:
#   ./tools/health_monitor.sh [--service NAME] [--container NAME] [--mem WARN CRIT] [--disk WARN CRIT]
#
# Options:
#   --service NAME    Monitor a systemd service such as news-sentry.
#   --container NAME  Monitor a Docker container. Defaults to news-sentry when no service is set.
#   --mem WARN CRIT   Memory warning/critical thresholds in percent. Defaults: 90 95.
#   --disk WARN CRIT  Disk warning/critical thresholds in percent. Defaults: 85 95.
#   --quiet           Only print alarms.
#   --json            Print JSON.

set -euo pipefail

SERVICE=""
CONTAINER="news-sentry"
MEM_WARN=90
MEM_CRIT=95
DISK_WARN=85
DISK_CRIT=95
QUIET=false
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service)   SERVICE="$2"; CONTAINER=""; shift 2 ;;
        --container) CONTAINER="$2"; shift 2 ;;
        --mem)       MEM_WARN="$2"; MEM_CRIT="$3"; shift 3 ;;
        --disk)      DISK_WARN="$2"; DISK_CRIT="$3"; shift 3 ;;
        --quiet)     QUIET=true; shift ;;
        --json)      JSON_OUTPUT=true; shift ;;
        --help)      sed -n '2,14p' "$0"; exit 0 ;;
        *)           echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATA_DIR="${DATA_DIR:-${NEWSSENTRY_DATA_DIR:-/app/data}}"

if command -v free &>/dev/null; then
    read -r MEM_PCT MEM_USED_GB MEM_TOTAL_GB < <(
        free | awk '/Mem:/ {printf "%.1f %.1f %.1f\n", $3/$2*100, $3/1024/1024, $2/1024/1024}'
    )
else
    MEM_TOTAL_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    PAGE_SIZE=$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)
    FREE_PAGES=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
    INACTIVE_PAGES=$(vm_stat | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
    FREE_BYTES=$(( (FREE_PAGES + INACTIVE_PAGES) * PAGE_SIZE ))
    USED_BYTES=$(( MEM_TOTAL_BYTES - FREE_BYTES ))
    read -r MEM_PCT MEM_USED_GB MEM_TOTAL_GB < <(
        awk -v used="${USED_BYTES}" -v total="${MEM_TOTAL_BYTES}" 'BEGIN {
          printf "%.1f %.1f %.1f\n", used*100/total, used/1024/1024/1024, total/1024/1024/1024
        }'
    )
fi

if [[ -d "${DATA_DIR}" ]]; then
    DISK_INFO=$(df "${DATA_DIR}" | awk 'NR==2 {printf "%.1f %d %d", $5+0, $3/1024/1024, $4/1024/1024}')
else
    DISK_INFO=$(df / | awk 'NR==2 {printf "%.1f %d %d", $5+0, $3/1024/1024, $4/1024/1024}')
fi
DISK_PCT=$(echo "$DISK_INFO" | awk '{print $1}')
DISK_USED_GB=$(echo "$DISK_INFO" | awk '{print $2}')
DISK_AVAIL_GB=$(echo "$DISK_INFO" | awk '{print $3}')

SERVICE_STATUS="not_configured"
if [[ -n "${SERVICE}" ]]; then
    if command -v systemctl &>/dev/null; then
        if systemctl is-active --quiet "${SERVICE}"; then
            SERVICE_STATUS="active"
        else
            SERVICE_STATUS=$(systemctl is-active "${SERVICE}" 2>/dev/null || echo "unknown")
        fi
    else
        SERVICE_STATUS="systemctl_missing"
    fi
fi

CONTAINER_STATUS="not_configured"
CONTAINER_RESTARTS=0
if [[ -n "${CONTAINER}" ]]; then
    CONTAINER_STATUS="not_found"
    if command -v docker &>/dev/null; then
        if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
            CONTAINER_STATUS=$(docker inspect --format '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || echo "unknown")
            CONTAINER_RESTARTS=$(docker inspect --format '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo "0")
        fi
    fi
fi

ALARMS=()

if awk -v value="${MEM_PCT}" -v limit="${MEM_CRIT}" 'BEGIN {exit !(value >= limit)}'; then
    ALARMS+=("CRITICAL: memory ${MEM_PCT}% >= ${MEM_CRIT}%")
elif awk -v value="${MEM_PCT}" -v limit="${MEM_WARN}" 'BEGIN {exit !(value >= limit)}'; then
    ALARMS+=("WARNING: memory ${MEM_PCT}% >= ${MEM_WARN}%")
fi

if awk -v value="${DISK_PCT}" -v limit="${DISK_CRIT}" 'BEGIN {exit !(value >= limit)}'; then
    ALARMS+=("CRITICAL: disk ${DISK_PCT}% >= ${DISK_CRIT}%")
elif awk -v value="${DISK_PCT}" -v limit="${DISK_WARN}" 'BEGIN {exit !(value >= limit)}'; then
    ALARMS+=("WARNING: disk ${DISK_PCT}% >= ${DISK_WARN}%")
fi

if [[ -n "${SERVICE}" && "${SERVICE_STATUS}" != "active" ]]; then
    ALARMS+=("CRITICAL: service ${SERVICE} status=${SERVICE_STATUS}")
fi

if [[ -n "${CONTAINER}" && "${CONTAINER_STATUS}" != "running" ]]; then
    ALARMS+=("CRITICAL: container ${CONTAINER} status=${CONTAINER_STATUS}")
fi

if [[ "${CONTAINER_RESTARTS}" -gt 3 ]]; then
    ALARMS+=("WARNING: container ${CONTAINER} restarts=${CONTAINER_RESTARTS}")
fi

json_array() {
    if command -v jq &>/dev/null; then
        printf '%s\n' "${ALARMS[@]+"${ALARMS[@]}"}" | jq -R . | jq -s .
    else
        printf '['
        local first=true
        for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
            if [[ "${first}" == true ]]; then first=false; else printf ','; fi
            printf '"%s"' "$(printf '%s' "${alarm}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
        done
        printf ']'
    fi
}

ALARMS_JSON=$(json_array)

if [[ "${JSON_OUTPUT}" == true ]]; then
    cat <<EOF
{"timestamp":"${TIMESTAMP}","memory_pct":${MEM_PCT},"memory_used_gb":${MEM_USED_GB},"memory_total_gb":${MEM_TOTAL_GB},"disk_pct":${DISK_PCT},"disk_used_gb":${DISK_USED_GB},"disk_avail_gb":${DISK_AVAIL_GB},"service":"${SERVICE}","service_status":"${SERVICE_STATUS}","container":"${CONTAINER}","container_status":"${CONTAINER_STATUS}","container_restarts":${CONTAINER_RESTARTS},"alarms":${ALARMS_JSON},"alarm_count":${#ALARMS[@]}}
EOF
else
    if [[ "${QUIET}" == false ]] || [[ ${#ALARMS[@]} -gt 0 ]]; then
        echo "[${TIMESTAMP}] health check"
        echo "  memory: ${MEM_PCT}% (${MEM_USED_GB}GB / ${MEM_TOTAL_GB}GB)"
        echo "  disk: ${DISK_PCT}% (available ${DISK_AVAIL_GB}GB)"
        [[ -n "${SERVICE}" ]] && echo "  service: ${SERVICE} -> ${SERVICE_STATUS}"
        [[ -n "${CONTAINER}" ]] && echo "  container: ${CONTAINER} -> ${CONTAINER_STATUS} (restarts ${CONTAINER_RESTARTS})"
        for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
            echo "  ${alarm}"
        done
    fi
fi

LOG_DIR="${DATA_DIR}/logs/health"
if [[ -d "${DATA_DIR}" ]]; then
    mkdir -p "${LOG_DIR}" 2>/dev/null || true
    if [[ -d "${LOG_DIR}" ]]; then
        LOG_FILE="${LOG_DIR}/health-$(date -u +"%Y%m%d").jsonl"
        echo "{\"timestamp\":\"${TIMESTAMP}\",\"memory_pct\":${MEM_PCT},\"disk_pct\":${DISK_PCT},\"service_status\":\"${SERVICE_STATUS}\",\"container_status\":\"${CONTAINER_STATUS}\",\"alarms\":${ALARMS_JSON}}" >> "${LOG_FILE}"
    fi
fi

for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
    if [[ "${alarm}" == CRITICAL* ]]; then
        exit 2
    fi
done
for alarm in "${ALARMS[@]+"${ALARMS[@]}"}"; do
    if [[ "${alarm}" == WARNING* ]]; then
        exit 1
    fi
done
exit 0
