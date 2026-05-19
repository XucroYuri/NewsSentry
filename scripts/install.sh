#!/usr/bin/env bash
# =============================================================================
# News Sentry — 服务安装脚本（Linux / macOS）
# =============================================================================
# 自动检测操作系统，创建目录结构与 Python 虚拟环境，并注册为 OS 级后台服务。
#
# 用法:
#   bash install.sh                    # 交互式安装
#   bash install.sh --non-interactive  # 非交互式（不提示，使用默认值）
#   bash install.sh --uninstall        # 停止并移除服务
#   bash install.sh --help             # 显示帮助
# =============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

BASE="$HOME/.news-sentry"
VENV="$BASE/venv"
DATA_DIR="$BASE/data"
LOGS_DIR="$BASE/logs"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
UNINSTALL=false
NON_INTERACTIVE=false

# ── 参数解析 ─────────────────────────────────────────────────────────────────

for arg in "$@"; do
    case $arg in
        --non-interactive) NON_INTERACTIVE=true ;;
        --uninstall)       UNINSTALL=true ;;
        --help|-h)
            head -24 "$0" | tail -21
            exit 0
            ;;
        *) echo -e "${RED}未知参数: $arg${NC}"; exit 1 ;;
    esac
done

# ── 卸载模式 ─────────────────────────────────────────────────────────────────

if $UNINSTALL; then
    echo -e "${YELLOW}正在卸载 News Sentry 服务...${NC}"

    if [[ "$(uname -s)" == "Linux" ]]; then
        systemctl --user stop news-sentry.service 2>/dev/null || true
        systemctl --user disable news-sentry.service 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/news-sentry.service"
        echo -e "${GREEN}已移除 systemd 用户单元。${NC}"
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        launchctl unload "$HOME/Library/LaunchAgents/com.news-sentry.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/com.news-sentry.plist"
        echo -e "${GREEN}已移除 LaunchAgent plist。${NC}"
    fi

    echo ""
    echo -e "${YELLOW}注意: $BASE 目录未被删除（包含数据与日志）。"
    echo "如要完全移除，请手动执行: rm -rf $BASE"
    exit 0
fi

# ── 安装模式 ─────────────────────────────────────────────────────────────────

echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     News Sentry — 服务安装脚本                    ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "操作系统: $(uname -s)"

# 1. 创建目录结构
echo ""
echo -e "${CYAN}[1/5] 创建目录结构...${NC}"
mkdir -p "$DATA_DIR" "$LOGS_DIR"
echo -e "  ${GREEN}+${NC} $DATA_DIR"
echo -e "  ${GREEN}+${NC} $LOGS_DIR"

# 2. Python 检测
echo ""
echo -e "${CYAN}[2/5] 检测 Python 环境...${NC}"
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
    echo -e "  ${RED}未找到 Python >= 3.11${NC}"
    echo ""
    echo "请先安装 Python 3.11+:"
    echo "  macOS:  brew install python@3.13"
    echo "  Ubuntu: sudo apt install python3.12 python3.12-venv"
    exit 1
fi
echo -e "  ${GREEN}找到: $PYTHON ($ver)${NC}"

# 3. 创建虚拟环境
echo ""
echo -e "${CYAN}[3/5] 准备虚拟环境...${NC}"
if [ -d "$VENV" ]; then
    echo "  虚拟环境已存在: $VENV"
    if $NON_INTERACTIVE; then
        echo "  (non-interactive: 使用现有虚拟环境)"
    else
        echo -n "  重建虚拟环境? [y/N] "
        read -r yn
        case $yn in
            [Yy]*) rm -rf "$VENV"; echo "  已删除旧虚拟环境" ;;
            *)     echo "  保留现有虚拟环境" ;;
        esac
    fi
fi

if [ ! -d "$VENV" ]; then
    echo "  创建虚拟环境..."
    "$PYTHON" -m venv "$VENV"
    echo -e "  ${GREEN}虚拟环境已创建${NC}"
fi

# 4. 安装/升级 news-sentry
echo ""
echo -e "${CYAN}[4/5] 安装 News Sentry...${NC}"
"$VENV/bin/pip" install --upgrade pip -q
if "$VENV/bin/python" -c "import news_sentry" 2>/dev/null; then
    echo "  news_sentry 已安装，升级到最新版本..."
    "$VENV/bin/pip" install --upgrade news-sentry -q 2>/dev/null || true
    # 如果 PyPI 不可用，尝试从本地项目安装
    if [ -f "$SCRIPTS_DIR/../pyproject.toml" ]; then
        "$VENV/bin/pip" install -e "$(dirname "$SCRIPTS_DIR")" -q 2>/dev/null || true
    fi
else
    echo "  安装 news_sentry..."
    # 优先从 PyPI 安装，失败则从本地项目
    if ! "$VENV/bin/pip" install news-sentry -q 2>/dev/null; then
        if [ -f "$SCRIPTS_DIR/../pyproject.toml" ]; then
            echo -e "  ${YELLOW}PyPI 不可用，从本地项目安装${NC}"
            "$VENV/bin/pip" install -e "$(dirname "$SCRIPTS_DIR")" -q
        else
            echo -e "${RED}无法安装 news_sentry：PyPI 不可用且未找到本地项目${NC}"
            exit 1
        fi
    fi
fi

# 验证安装
if ! "$VENV/bin/python" -c "import news_sentry" 2>/dev/null; then
    echo -e "  ${RED}安装验证失败: 无法导入 news_sentry${NC}"
    exit 1
fi
echo -e "  ${GREEN}News Sentry 安装/升级完成${NC}"

# 5. 注册 OS 服务
echo ""
echo -e "${CYAN}[5/5] 注册为系统服务...${NC}"

OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
    _install_linux
elif [[ "$OS" == "Darwin" ]]; then
    _install_macos
else
    echo -e "${RED}不支持的操作系统: $OS${NC}"
    echo "请手动配置服务。"
    exit 1
fi

# ── 完成 ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  安装完成！                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "数据目录: $DATA_DIR"
echo "日志目录: $LOGS_DIR"
echo "日志文件: $LOGS_DIR/serve.log"
echo ""
echo "常用命令:"
if [[ "$OS" == "Linux" ]]; then
    echo "  systemctl --user status news-sentry   # 查看状态"
    echo "  systemctl --user restart news-sentry  # 重启"
    echo "  journalctl --user -u news-sentry -f   # 查看日志"
elif [[ "$OS" == "Darwin" ]]; then
    echo "  launchctl list com.news-sentry         # 查看状态"
    echo "  launchctl kickstart gui/\$(id -u)/com.news-sentry  # 重启"
    echo "  tail -f $LOGS_DIR/serve.log    # 查看日志"
fi
echo ""
echo "Web Dashboard: http://localhost:8080 (默认端口)"

# ── Linux: systemd user unit ─────────────────────────────────────────────────

_install_linux() {
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_DIR"

    cp "$SCRIPTS_DIR/news-sentry.service" "$SYSTEMD_DIR/news-sentry.service"
    echo -e "  ${GREEN}+${NC} 已复制 systemd 单元到 $SYSTEMD_DIR"

    systemctl --user daemon-reload
    echo -e "  ${GREEN}+${NC} systemd daemon-reload 完成"

    systemctl --user enable news-sentry.service
    echo -e "  ${GREEN}+${NC} 已启用 news-sentry.service（开机自启）"

    systemctl --user restart news-sentry.service 2>/dev/null || systemctl --user start news-sentry.service
    echo -e "  ${GREEN}+${NC} 服务已启动"

    # 启用 linger（允许用户服务在未登录时运行）
    if command -v loginctl &>/dev/null; then
        loginctl enable-linger "$USER" 2>/dev/null || true
    fi
}

# ── macOS: LaunchAgent plist ─────────────────────────────────────────────────

_install_macos() {
    PLIST_SRC="$SCRIPTS_DIR/com.news-sentry.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.news-sentry.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    # 替换 plist 中的 REPLACE_ME 占位符为实际用户名
    sed "s|/Users/REPLACE_ME|$HOME|g" "$PLIST_SRC" > "$PLIST_DST"
    echo -e "  ${GREEN}+${NC} 已复制 LaunchAgent plist 到 $PLIST_DST"

    # 先卸载旧实例（如存在），再加载
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo -e "  ${GREEN}+${NC} LaunchAgent 已加载"
}
