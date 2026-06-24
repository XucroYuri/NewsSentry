#!/usr/bin/env bash
# check.sh — News Sentry 一键质量检查
# 用法: ./check.sh [--fix] [--no-slow]
#   --fix      自动修复可修复的问题 (ruff format)
#   --no-slow  跳过 pytest + coverage (快速模式，仅 lint + type)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# 环境
export VIRTUAL_ENV="${SCRIPT_DIR}/.venv"
export PATH="${VIRTUAL_ENV}/bin:${PATH}"
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH:-}"

FIX_MODE=false
FAST_MODE=false
for arg in "$@"; do
    case "$arg" in
        --fix) FIX_MODE=true ;;
        --no-slow) FAST_MODE=true ;;
    esac
done

PASS=0
FAIL=0

check() {
    local label="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "  ✅ ${label}"
        PASS=$((PASS + 1))
    else
        echo "  ❌ ${label}"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "═══════════════════════════════════════"
echo "  News Sentry — Quality Check"
echo "═══════════════════════════════════════"
echo ""

# ── Lint ──
echo "── Lint ──"
check "ruff check"   python -m ruff check
if $FIX_MODE; then
    check "ruff format"  python -m ruff format
fi

# ── Type ──
echo "── Type ──"
check "mypy"         python -m mypy src/news_sentry/ --no-error-summary

# ── Test ──
if $FAST_MODE; then
    echo ""
    echo "  ⏩ Skipping tests (--no-slow)"
else
    echo "── Tests ──"
    check "pytest"   python -m pytest tests/ -q --tb=short
fi

# ── Summary ──
echo ""
echo "───────────────────────────────────────"
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
    echo "  All ${TOTAL} checks passed ✅"
else
    echo "  ${PASS}/${TOTAL} passed, ${FAIL} failed ❌"
fi
echo "───────────────────────────────────────"
echo ""

exit "$FAIL"
