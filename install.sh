#!/usr/bin/env bash
# =============================================================================
# News Sentry — 一键安装脚本
# =============================================================================
# 用法:
#   bash install.sh                 # 安装生产依赖
#   bash install.sh --dev           # 安装生产 + 开发依赖
#   bash install.sh --check         # 安装 + 运行测试
#   bash install.sh --dev --api     # 安装开发依赖 + API 服务 (uvicorn)
#   bash install.sh --proxy --api   # 安装代理支持 + API 服务
#   bash install.sh --with-service  # 安装后注册为 OS 服务
#   bash install.sh -y --dev        # 非交互模式
#   bash install.sh --help          # 显示帮助
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
DEV_MODE=false
CHECK_MODE=false
YES_MODE=false
API_MODE=false
PROXY_MODE=false
WITH_SERVICE=false

# ── 参数解析 ─────────────────────────────────────────────────────────────────

for arg in "$@"; do
    case $arg in
        --dev)    DEV_MODE=true ;;
        --check)  CHECK_MODE=true; DEV_MODE=true ;;
        --api)    API_MODE=true ;;
        --proxy)  PROXY_MODE=true ;;
        --with-service) WITH_SERVICE=true ;;
        --yes|-y) YES_MODE=true ;;
        --help|-h)
            echo "News Sentry — 一键安装脚本"
            echo ""
            echo "用法: bash install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  (无)             安装生产依赖"
            echo "  --dev             安装生产 + 开发依赖 (pytest, mypy, ruff)"
            echo "  --check           安装全部依赖 + 运行测试"
            echo "  --api             安装 API 服务依赖 (uvicorn, FastAPI)"
            echo "  --proxy           安装 SOCKS5 代理支持 (httpx[socks])"
            echo "  --with-service    安装后自动注册为 OS 后台服务 (LaunchAgent/systemd)"
            echo "  --yes, -y         非交互模式 (自动重建已有虚拟环境)"
            echo "  --help            显示此帮助"
            echo ""
            echo "示例:"
            echo "  bash install.sh --dev --api          # 开发 + API 服务"
            echo "  bash install.sh --proxy --api        # 代理 + API + 生产部署"
            echo "  bash install.sh -y --dev --with-service  # 一键全自动安装"
            echo ""
            echo "前置条件:"
            echo "  - Python >= 3.11"
            echo "  - pip (随 Python 安装)"
            echo "  - git (可选，用于克隆仓库)"
            exit 0
            ;;
        *) echo -e "${RED}未知参数: $arg${NC}"; exit 1 ;;
    esac
done

# ── 前置条件检查 ─────────────────────────────────────────────────────────────

echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       News Sentry — 自动安装脚本                 ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# 1. Python 版本检查
echo -n "检查 Python >= 3.11 ... "
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}失败${NC}"
    echo ""
    echo -e "${RED}错误: 未找到 Python >= 3.11${NC}"
    echo ""
    echo "请安装 Python 3.11+:"
    echo "  macOS:   brew install python@3.13"
    echo "  Ubuntu:  sudo apt install python3.12 python3.12-venv"
    echo "  Windows: https://www.python.org/downloads/"
    exit 1
fi
echo -e "${GREEN}$PYTHON ($ver)${NC}"

# 2. pip 可用性
echo -n "检查 pip ... "
if ! "$PYTHON" -m pip --version &>/dev/null; then
    echo -e "${RED}失败${NC}"
    echo -e "${RED}错误: pip 不可用。请运行: $PYTHON -m ensurepip${NC}"
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# 3. 磁盘空间（至少 200MB）
echo -n "检查磁盘空间 ... "
if command -v df &>/dev/null; then
    # macOS df 不支持 -BM；Linux 支持
    if df -BM "$PROJECT_ROOT" 2>/dev/null | tail -1 | awk '{print $4}' | grep -q .; then
        avail=$(df -BM "$PROJECT_ROOT" 2>/dev/null | tail -1 | awk '{print $4}' | sed 's/M//')
    else
        # macOS fallback: df -m (1M blocks)
        avail=$(df -m "$PROJECT_ROOT" 2>/dev/null | tail -1 | awk '{print $4}')
    fi
    if [ -n "$avail" ] && [ "$avail" -lt 200 ] 2>/dev/null; then
        echo -e "${YELLOW}警告: 可用空间 ${avail}MB (建议 >= 200MB)${NC}"
    else
        echo -e "${GREEN}${avail:-?} MB${NC}"
    fi
else
    echo -e "${YELLOW}跳过 (df 不可用)${NC}"
fi

echo ""

# ── 环境变量 ─────────────────────────────────────────────────────────────────

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${YELLOW}未找到 .env 文件，从 .env.example 创建...${NC}"
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo -e "${GREEN}已创建 .env（使用默认 local-workstation profile）${NC}"
    echo -e "${YELLOW}如需修改，请编辑: $PROJECT_ROOT/.env${NC}"
    echo ""
fi

# ── 虚拟环境 ─────────────────────────────────────────────────────────────────

VENV="$PROJECT_ROOT/.venv"
if [ -d "$VENV" ]; then
    if $YES_MODE; then
        rm -rf "$VENV"
        echo "已删除旧虚拟环境 (--yes 非交互模式)"
    else
        echo -n "发现已有虚拟环境，重建? [y/N] "
        read -r yn
        case $yn in
            [Yy]*) rm -rf "$VENV"; echo "已删除旧虚拟环境" ;;
            *)     echo "使用现有虚拟环境"; echo ""; exit 0 ;;
        esac
    fi
fi

echo -n "创建虚拟环境 ($VENV) ... "
"$PYTHON" -m venv "$VENV"
echo -e "${GREEN}OK${NC}"

# ── 安装依赖 ─────────────────────────────────────────────────────────────────

echo -n "升级 pip ... "
"$VENV/bin/pip" install --upgrade pip setuptools wheel -q
echo -e "${GREEN}OK${NC}"

# Build extras list (e.g. "dev,api,proxy" or just "api")
EXTRAS=""
$DEV_MODE && EXTRAS="${EXTRAS}dev,"
$API_MODE && EXTRAS="${EXTRAS}api,"
$PROXY_MODE && EXTRAS="${EXTRAS}proxy,"
EXTRAS="${EXTRAS%,}"  # strip trailing comma

if [ -n "$EXTRAS" ]; then
    echo -n "安装 News Sentry [$EXTRAS] ... "
    "$VENV/bin/pip" install -e "$PROJECT_ROOT[$EXTRAS]" -q
else
    echo -n "安装 News Sentry (生产依赖) ... "
    "$VENV/bin/pip" install -e "$PROJECT_ROOT" -q
fi
echo -e "${GREEN}OK${NC}"

# ── 验证 ─────────────────────────────────────────────────────────────────────

echo -n "验证安装 ... "
INSTALLED_VER=$("$VENV/bin/python" -c "import news_sentry; print('OK')" 2>&1)
if [ "$INSTALLED_VER" = "OK" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}失败: $INSTALLED_VER${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  安装完成！                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── 可选: 外部工具检查 ───────────────────────────────────────────────────────

echo "外部工具检查（可选，用于高级功能）:"
echo ""

check_tool() {
    local name="$1"
    local purpose="$2"
    local install_cmd="$3"
    printf "  %-25s " "$name"
    if command -v "$name" &>/dev/null; then
        echo -e "${GREEN}已安装${NC}"
    else
        echo -e "${YELLOW}未安装${NC}  ($purpose)"
        echo "                                    安装: $install_cmd"
    fi
}

check_tool "hermes"  "Hermes Agent (cron 调度)"   "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
check_tool "git"     "版本控制"                    "macOS: brew install git / Ubuntu: sudo apt install git"
check_tool "gh"      "GitHub CLI (可选)"           "brew install gh"

echo ""

# ── 可选: 注册为 OS 服务 ──────────────────────────────────────────────────────

if $WITH_SERVICE; then
    echo "注册 News Sentry 为 OS 后台服务..."
    if ! "$VENV/bin/pip" show uvicorn &>/dev/null; then
        echo -e "${YELLOW}警告: uvicorn 未安装。已自动追加 --api extras${NC}"
        "$VENV/bin/pip" install -e "$PROJECT_ROOT[api]" -q
        echo -e "${GREEN}  uvicorn 安装完成${NC}"
    fi
    "$VENV/bin/python" -m news_sentry.cli install --force \
        --data-dir ~/.news-sentry/data \
        --log-dir ~/.news-sentry/logs
    echo ""
fi

echo "下一步:"
echo "  cd $PROJECT_ROOT"
echo "  source .venv/bin/activate        # 激活虚拟环境"
echo "  make dry-run                      # 验证配置"
if $WITH_SERVICE; then
    echo "  news-sentry status                # 查看服务状态"
fi

if $CHECK_MODE; then
    echo ""
    echo "运行测试套件..."
    "$VENV/bin/python" -m pytest tests/ -q --tb=short
fi
