#!/usr/bin/env bash
# Run one production realtime collection batch for active public region targets.

set -uo pipefail

REPO_DIR="${NEWSSENTRY_REPO_DIR:-/opt/news-sentry/production/repo}"
DATA_DIR="${NEWSSENTRY_DATA_DIR:-/srv/news-sentry/production/data}"
PROFILE="${NEWSSENTRY_PROFILE:-cloud-vps}"
PYTHON_BIN="${NEWSSENTRY_PYTHON:-/opt/news-sentry/production/venv/bin/python}"
COLLECTOR_CONFIG="${NEWSSENTRY_COLLECTOR_CONFIG:-${REPO_DIR}/config/runtime/collector.yaml}"
BATCH_SIZE="${NEWSSENTRY_REALTIME_BATCH_SIZE:-12}"
STRICT="${NEWSSENTRY_REALTIME_STRICT:-0}"
LOCK_DIR="${NEWSSENTRY_LOCK_DIR:-${DATA_DIR}/locks}"
CURSOR_FILE="${NEWSSENTRY_REALTIME_CURSOR_FILE:-${DATA_DIR}/runtime/realtime-target-cursor.txt}"

export NEWSSENTRY_DATA_DIR="${DATA_DIR}"
export NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR="${NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR:-1}"

mkdir -p "${LOCK_DIR}" "${DATA_DIR}/logs" "$(dirname "${CURSOR_FILE}")"
exec 9>"${LOCK_DIR}/news-sentry-realtime.lock"
if ! flock -n 9; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] realtime cycle already running; skip"
  exit 0
fi

cd "${REPO_DIR}" || exit 2

load_targets() {
  if [ -n "${NEWSSENTRY_REALTIME_TARGETS:-}" ]; then
    printf "%s\n" "${NEWSSENTRY_REALTIME_TARGETS}"
    return 0
  fi
  "${PYTHON_BIN}" - "${COLLECTOR_CONFIG}" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
targets = payload.get("target_ids") or []
if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
    raise SystemExit(f"Invalid collector target_ids in {path}")
print(" ".join(targets))
PY
}

targets_text="$(load_targets)"
read -r -a target_array <<< "${targets_text}"
total_targets="${#target_array[@]}"
if [ "${total_targets}" -eq 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] no realtime targets configured"
  exit 0
fi

if ! [[ "${BATCH_SIZE}" =~ ^[0-9]+$ ]] || [ "${BATCH_SIZE}" -le 0 ]; then
  echo "Invalid NEWSSENTRY_REALTIME_BATCH_SIZE=${BATCH_SIZE}" >&2
  exit 2
fi

cursor=0
if [ -f "${CURSOR_FILE}" ]; then
  cursor="$(tr -cd '0-9' < "${CURSOR_FILE}" | head -c 12)"
  cursor="${cursor:-0}"
fi
if [ "${cursor}" -ge "${total_targets}" ]; then
  cursor=0
fi

batch_count="${BATCH_SIZE}"
if [ "${batch_count}" -gt "${total_targets}" ]; then
  batch_count="${total_targets}"
fi

selected_targets=()
for ((offset = 0; offset < batch_count; offset++)); do
  index=$(((cursor + offset) % total_targets))
  selected_targets+=("${target_array[$index]}")
done
next_cursor=$(((cursor + batch_count) % total_targets))

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] realtime batch targets=${batch_count}/${total_targets} cursor=${cursor} next=${next_cursor} selected=${selected_targets[*]}"

status=0
failures=0
for target in "${selected_targets[@]}"; do
  log_dir="${DATA_DIR}/${target}/logs"
  mkdir -p "${log_dir}"
  log_file="${log_dir}/realtime.log"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[${started_at}] start target=${target} profile=${PROFILE}" | tee -a "${log_file}"

  if "${PYTHON_BIN}" -m news_sentry.cli run --target "${target}" --stage all --profile "${PROFILE}" >> "${log_file}" 2>&1; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ok target=${target}" | tee -a "${log_file}"
  else
    rc=$?
    status=${rc}
    failures=$((failures + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] failed target=${target} rc=${rc}" | tee -a "${log_file}" >&2
  fi
done

printf "%s\n" "${next_cursor}" > "${CURSOR_FILE}"

if [ "${failures}" -gt 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] realtime batch completed with failures=${failures}/${batch_count} strict=${STRICT}" >&2
fi

if [ "${STRICT}" = "1" ] && [ "${failures}" -gt 0 ]; then
  exit "${status}"
fi

exit 0
