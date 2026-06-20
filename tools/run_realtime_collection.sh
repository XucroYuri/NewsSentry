#!/usr/bin/env bash
# Run one production realtime collection cycle for all active public targets.

set -uo pipefail

REPO_DIR="${NEWSSENTRY_REPO_DIR:-/opt/news-sentry/production/repo}"
DATA_DIR="${NEWSSENTRY_DATA_DIR:-/srv/news-sentry/production/data}"
PROFILE="${NEWSSENTRY_PROFILE:-cloud-vps}"
PYTHON_BIN="${NEWSSENTRY_PYTHON:-/opt/news-sentry/production/venv/bin/python}"
TARGETS="${NEWSSENTRY_REALTIME_TARGETS:-africa african-union algeria argentina asean asia-pacific australia austria bangladesh belgium brazil brics canada central-asia chile colombia czechia denmark east-asia egypt energy-opec-iea ethiopia europe european-union finland france g20 g7 germany global greece hungary imf-world-bank india indonesia international-organizations iran iraq ireland israel italy japan kenya kuwait latin-america malaysia mexico middle-east morocco netherlands new-zealand nigeria nordics norway pakistan peru philippines poland portugal qatar romania russia saudi-arabia security-nato-osce singapore south-africa south-asia south-korea southeast-asia spain sweden switzerland thailand trade-wto-oecd turkey ukraine un-system united-arab-emirates united-kingdom united-states vietnam}"
LOCK_DIR="${NEWSSENTRY_LOCK_DIR:-${DATA_DIR}/locks}"

export NEWSSENTRY_DATA_DIR="${DATA_DIR}"
export NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR="${NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR:-1}"

mkdir -p "${LOCK_DIR}" "${DATA_DIR}/logs"
exec 9>"${LOCK_DIR}/news-sentry-realtime.lock"
if ! flock -n 9; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] realtime cycle already running; skip"
  exit 0
fi

cd "${REPO_DIR}" || exit 2

status=0
for target in ${TARGETS}; do
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
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] failed target=${target} rc=${rc}" | tee -a "${log_file}" >&2
  fi
done

exit "${status}"
