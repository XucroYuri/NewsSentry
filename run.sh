#!/usr/bin/env bash
# News Sentry — CLI 入口包装脚本
# 用法: ./run.sh [doctor|collect|filter|judge|output|all|serve] [--target <id>] [--profile <id>]
#
# 示例:
#   ./run.sh doctor --target italy
#   ./run.sh collect --target italy --profile local-workstation
#   ./run.sh serve --target italy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ── 0. Python 版本检查 ──
PYTHON_MIN="3.11"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"

check_python_version() {
    local py="$1"
    if [ ! -x "${py}" ]; then
        echo "ERROR: Python not found at ${py}" >&2
        echo "Please create a virtualenv: python3 -m venv .venv" >&2
        exit 1
    fi
    local version_str
    version_str="$("${py}" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
    local major minor
    IFS='.' read -r major minor <<< "${version_str}"
    local min_major min_minor
    IFS='.' read -r min_major min_minor <<< "${PYTHON_MIN}"
    if [ "${major}" -lt "${min_major}" ] || { [ "${major}" -eq "${min_major}" ] && [ "${minor}" -lt "${min_minor}" ]; }; then
        echo "ERROR: Python ${PYTHON_MIN}+ required, found ${version_str}" >&2
        exit 1
    fi
}

check_python_version "${PYTHON_BIN}"

# ── 1. 激活虚拟环境 ──
export VIRTUAL_ENV="${SCRIPT_DIR}/.venv"
export PATH="${VIRTUAL_ENV}/bin:${PATH}"

# ── 2. 设置 PYTHONPATH ──
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH:-}"

# ── 3. 检查依赖 ──
if ! python -c "import news_sentry" 2>/dev/null; then
    echo "ERROR: news_sentry package not importable. Install with: pip install -e ." >&2
    exit 1
fi

# ── 4. 转发参数 ──
exec python -m news_sentry.cli "$@"
