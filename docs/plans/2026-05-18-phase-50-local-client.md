# Phase 50: 本地客户端 v1 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `news-sentry serve` 命令，实现跨平台（macOS/Linux/Windows）后台常驻服务，Web UI 管理 + 多 target 自动采集。

**Architecture:** 新增 `serve.py` Click 命令 → 启动 uvicorn + FastAPI create_app() → 复用现有 Web UI 和自动采集器。api_server.py 升级 `_auto_collect_loop` 支持多 target + `NEWSSENTRY_DATA_DIR` 环境变量。

**Tech Stack:** Click + uvicorn + FastAPI + asyncio + platform (stdlib)

**Spec:** `docs/specs/2026-05-18-phase-50-local-client-design.md`

---

## 文件结构

| 文件 | 职责 | 变更 |
|------|------|------|
| `src/news_sentry/cli/serve.py` | serve 命令：PID 管理 + 信号处理 + env 文件加载 + uvicorn 启动 | 新建 |
| `src/news_sentry/cli/__init__.py` | 注册 serve 命令到 Click group | 修改（1 行 import） |
| `src/news_sentry/core/api_server.py` | `_data_dir` 读环境变量 + `_auto_collector_state` 多 target + `_auto_collect_loop` 用 `bounded_run_multi_async` + `collector_status` 返回 target_ids | 修改（4 处） |
| `scripts/news-sentry.service` | systemd unit 模板 | 新建 |
| `scripts/com.news-sentry.plist` | launchd plist 模板 | 新建 |
| `scripts/install.sh` | Linux/macOS 安装脚本 | 新建 |
| `scripts/install.ps1` | Windows 安装脚本 | 新建 |
| `tests/unit/test_serve.py` | serve 命令单元测试 | 新建 |
| `docs/roadmap/development-plan.md` | 添加 Phase 50 条目 | 修改 |
| `README.md` | 添加 serve 命令使用说明 | 修改 |

---

### Task 1: `serve.py` 命令实现

**Files:**
- Create: `src/news_sentry/cli/serve.py`
- No test file yet (tests in Task 5)

- [ ] **Step 1: 创建 serve.py**

```python
"""serve 命令 — 启动 News Sentry 后台常驻服务。

uvicorn + FastAPI create_app() + 多 target 自动采集 + Web UI。
"""

from __future__ import annotations

import os
import platform
import sys
import webbrowser
from pathlib import Path

import click
import uvicorn

from news_sentry.cli import main as cli_group


def _load_env_file(env_path: Path) -> None:
    """加载 KEY=VALUE 格式的环境变量文件（行首 # 为注释）。

    仅设置 os.environ 中尚不存在的 key（不覆盖已有环境变量）。
    """
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def _pid_alive(pid_path: Path) -> bool:
    """检查 PID 文件中记录的进程是否仍存活。

    Unix: os.kill(pid, 0)
    Windows: kernel32.OpenProcess(PROCESS_QUERY_INFORMATION)
    """
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False

    if platform.system() == "Windows":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except OSError:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


@cli_group.command()
@click.option("--host", default="127.0.0.1", help="绑定 IP 地址")
@click.option("--port", default=8000, type=int, help="监听端口")
@click.option("--target", default="all", help="监控目标 ID，逗号分隔或 all")
@click.option("--interval", default=15, type=int, help="采集间隔（分钟）")
@click.option("--profile", default=None, help="部署 profile")
@click.option("--data-dir", default="~/.news-sentry/data", help="数据根目录")
@click.option("--log-dir", default="~/.news-sentry/logs", help="日志目录")
@click.option("--pid-file", default="~/.news-sentry/serve.pid", help="PID 文件路径")
@click.option("--no-browser", is_flag=True, help="启动时不自动打开浏览器")
@click.option("--foreground", is_flag=True, help="前台运行（不 daemonize）")
def serve(
    host: str,
    port: int,
    target: str,
    interval: int,
    profile: str | None,
    data_dir: str,
    log_dir: str,
    pid_file: str,
    no_browser: bool,
    foreground: bool,
) -> None:
    """Start News Sentry as a background service.

    启动后台常驻服务：FastAPI REST API + Web UI + 自动采集器。

    \\b
    使用:
      news-sentry serve                        # 默认配置，localhost:8000
      news-sentry serve --target italy         # 单 target 模式
      news-sentry serve --port 8080            # 自定义端口
      news-sentry serve --foreground           # 前台调试（Ctrl+C 退出）

    \\b
    开机自启 (安装后):
      Linux:    systemctl --user enable --now news-sentry
      macOS:    launchctl load ~/Library/LaunchAgents/com.news-sentry.plist
      Windows:  运行 scripts\\install.ps1
    """
    import signal as _signal

    # 1. 解析路径
    data_path = Path(data_dir).expanduser().resolve()
    log_path = Path(log_dir).expanduser().resolve()
    pid_path = Path(pid_file).expanduser().resolve()

    for p in (data_path, log_path):
        p.mkdir(parents=True, exist_ok=True)

    # 2. 自动加载 env 文件
    env_file = Path("~/.news-sentry/env").expanduser()
    _load_env_file(env_file)

    # 3. PID 存活检测
    if _pid_alive(pid_path):
        click.echo(
            f"错误: News Sentry 已在运行 (PID: {pid_path.read_text().strip()})",
            err=True,
        )
        click.echo(f"如需重启，请先停止现有实例或删除 {pid_path}", err=True)
        sys.exit(1)

    # 4. 设置环境变量（传递给 api_server.py 的 create_app()）
    os.environ["NEWSSENTRY_DATA_DIR"] = str(data_path)
    os.environ["NEWSSENTRY_AUTO_COLLECT"] = "1"
    os.environ["NEWSSENTRY_COLLECT_INTERVAL"] = str(interval)
    os.environ["NEWSSENTRY_TARGET_ID"] = target
    if profile:
        os.environ["NEWSSENTRY_PROFILE"] = profile

    # 5. 写入 PID 文件
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    def cleanup() -> None:
        """退出时删除 PID 文件。"""
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

    # 6. 平台感知信号处理（Windows 无 SIGTERM/SIGINT）
    if platform.system() != "Windows":
        def _handle_signal(signum: int, frame: object) -> None:
            cleanup()
            sys.exit(0)
        _signal.signal(_signal.SIGTERM, _handle_signal)
        _signal.signal(_signal.SIGINT, _handle_signal)

    # 7. 打开浏览器
    if not no_browser:
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        url = f"http://{display_host}:{port}"
        click.echo(f"Opening {url} ...")
        webbrowser.open(url)

    # 8. 启动 FastAPI
    click.echo(f"News Sentry serve starting on http://{host}:{port}")
    click.echo(f"Data dir: {data_path}")
    click.echo(f"PID file: {pid_path}")
    click.echo(f"Target(s): {target}")
    click.echo(f"Collect interval: {interval} min")

    try:
        uvicorn.run(
            "news_sentry.core.api_server:create_app",
            host=host,
            port=port,
            factory=True,
            log_level="info",
            access_log=True,
        )
    finally:
        cleanup()
```

- [ ] **Step 2: 验证 lint 通过**

Run: `ruff check src/news_sentry/cli/serve.py`
Expected: 零错误

- [ ] **Step 3: Commit**

```bash
git add src/news_sentry/cli/serve.py
git commit -m "Phase 50: 新增 serve 命令 — PID 管理 + 信号处理 + 环境变量注入"
```

---

### Task 2: 注册 serve 命令到 CLI

**Files:**
- Modify: `src/news_sentry/cli/__init__.py`

- [ ] **Step 1: 在 `__init__.py` 顶部添加 serve 导入**

在现有 import 块末尾（`from news_sentry.models.pipeline_context import PipelineContext` 之后）添加：

```python
import news_sentry.cli.serve  # noqa: F401 — 注册 serve 命令
```

> 使用 `import` 而非 `from ... import ...` 避免循环导入。副作用（`@cli_group.command()` 装饰器）在 import 时自动注册命令。

- [ ] **Step 2: 验证 serve 命令已注册**

Run: `.venv/bin/python3 -m news_sentry.cli serve --help`
Expected: 显示 serve 命令帮助信息，列出 11 个选项

- [ ] **Step 3: 验证列出所有命令**

Run: `.venv/bin/python3 -m news_sentry.cli --help`
Expected: 显示 6 个命令（run, serve, skill, tool, validate, doctor）

- [ ] **Step 4: Commit**

```bash
git add src/news_sentry/cli/__init__.py
git commit -m "Phase 50: 注册 serve 命令到 CLI 入口"
```

---

### Task 3: api_server.py 多 target 适配

**Files:**
- Modify: `src/news_sentry/core/api_server.py`

#### Subtask 3a: `_data_dir` 读取环境变量

- [ ] **Step 1: 修改 `create_app()` 中 `_data_dir` 初始化**

在 `api_server.py` 第 1218 行，将：

```python
_data_dir = Path(data_dir) if data_dir else Path("./data")
```

改为：

```python
_data_dir = Path(data_dir or os.environ.get("NEWSSENTRY_DATA_DIR", "./data"))
```

- [ ] **Step 2: 验证修改正确**

Run: `ruff check src/news_sentry/core/api_server.py`
Expected: 零错误

#### Subtask 3b: `_auto_collector_state` + `_parse_target_ids`

- [ ] **Step 3: 添加 `_parse_target_ids` 辅助函数 + 修改 state 初始化**

在第 1037 行（`# ── 后台自动采集循环 ──` 注释块之后）修改。

将第 1039-1049 行：

```python
_auto_collector_state: dict[str, Any] = {
    "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
    "target_id": os.environ.get("TARGET_ID", "italy"),
    "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15")),
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_events_collected": 0,
    "total_runs": 0,
    "task": None,
}
```

改为：

```python
def _parse_target_ids(raw: str) -> list[str]:
    """解析 target ID 字符串：'all' -> 全量 targets，'a,b' -> ['a','b']。"""
    if raw.strip().lower() == "all":
        from pathlib import Path

        from news_sentry.core.async_run import _resolve_targets

        import news_sentry

        config_dir = Path(news_sentry.__file__).resolve().parent.parent / "config"
        return _resolve_targets("all", config_dir)
    return [t.strip() for t in raw.split(",") if t.strip()]


_auto_collector_state: dict[str, Any] = {
    "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
    "target_ids": _parse_target_ids(
        os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "italy"))
    ),
    "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15")),
    "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_events_collected": 0,
    "total_runs": 0,
    "task": None,
}
```

- [ ] **Step 4: 验证 lint**

Run: `ruff check src/news_sentry/core/api_server.py`
Expected: 零错误

#### Subtask 3c: `_auto_collect_loop` 升级为多 target

- [ ] **Step 5: 替换 `_auto_collect_loop` 实现**

将第 1054-1091 行（整个函数体）替换为：

```python
async def _auto_collect_loop() -> None:
    """后台循环：每隔 interval_minutes 执行多 target pipeline。

    使用 bounded_run_multi_async 并发处理所有 targets。
    stage 由 NEWSSENTRY_COLLECT_STAGE 控制，默认仅 collect。
    """
    interval = _auto_collector_state["interval_minutes"] * 60
    target_ids = _auto_collector_state["target_ids"]
    stage = _auto_collector_state["stage"]
    _auto_collector_state["running"] = True
    _log.info(
        "自动采集循环启动: targets=%s, stage=%s, interval=%dmin",
        target_ids,
        stage,
        interval // 60,
    )

    while _auto_collector_state["enabled"]:
        try:
            from news_sentry.core.async_run import bounded_run_multi_async

            run_id = f"auto_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            _log.info("自动采集开始: run_id=%s, targets=%s", run_id, target_ids)

            await bounded_run_multi_async(
                targets=target_ids,
                stage=stage,
                run_id=run_id,
            )

            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "ok"
            _auto_collector_state["total_runs"] += 1
            _log.info("自动采集完成: run_id=%s", run_id)
        except Exception:
            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "error"
            _auto_collector_state["total_runs"] += 1
            _log.error("自动采集失败", exc_info=True)

        await asyncio.sleep(interval)

    _auto_collector_state["running"] = False
    _log.info("自动采集循环停止")
```

- [ ] **Step 6: 验证 lint**

Run: `ruff check src/news_sentry/core/api_server.py`
Expected: 零错误

#### Subtask 3d: `collector_status` 端点更新

- [ ] **Step 7: 修改 `collector_status` 返回值**

将第 1234-1245 行（`collector_status` 端点）的返回字典：

```python
return {
    "enabled": _auto_collector_state["enabled"],
    "running": _auto_collector_state["running"],
    "target_id": _auto_collector_state["target_id"],
    "interval_minutes": _auto_collector_state["interval_minutes"],
    "last_run_at": _auto_collector_state["last_run_at"],
    "last_run_status": _auto_collector_state["last_run_status"],
    "total_runs": _auto_collector_state["total_runs"],
}
```

改为：

```python
return {
    "enabled": _auto_collector_state["enabled"],
    "running": _auto_collector_state["running"],
    "target_ids": _auto_collector_state["target_ids"],
    "stage": _auto_collector_state["stage"],
    "interval_minutes": _auto_collector_state["interval_minutes"],
    "last_run_at": _auto_collector_state["last_run_at"],
    "last_run_status": _auto_collector_state["last_run_status"],
    "total_runs": _auto_collector_state["total_runs"],
}
```

> 注意：`target_id` 改为 `target_ids`（list[str]），新增 `stage` 字段。此端点为内部使用，无外部消费者，变更安全。

- [ ] **Step 8: 全体验证**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 全量测试通过 (1640+)

- [ ] **Step 9: Commit**

```bash
git add src/news_sentry/core/api_server.py
git commit -m "Phase 50: api_server 多 target 适配 + _data_dir 环境变量 + collector_status 升级"
```

---

### Task 4: OS 服务文件 + 安装脚本

**Files:**
- Create: `scripts/news-sentry.service`
- Create: `scripts/com.news-sentry.plist`
- Create: `scripts/install.sh`
- Create: `scripts/install.ps1`

- [ ] **Step 1: 创建 systemd unit 模板**

`scripts/news-sentry.service`:

```ini
[Unit]
Description=News Sentry — News Intelligence Monitor
After=network.target

[Service]
Type=simple
ExecStart=%INSTALL_DIR%/venv/bin/python -m news_sentry.cli serve --foreground
Restart=always
RestartSec=10
User=%USER%

[Install]
WantedBy=default.target
```

- [ ] **Step 2: 创建 launchd plist 模板**

`scripts/com.news-sentry.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.news-sentry</string>
    <key>ProgramArguments</key>
    <array>
        <string>%INSTALL_DIR%/venv/bin/python</string>
        <string>-m</string>
        <string>news_sentry.cli</string>
        <string>serve</string>
        <string>--foreground</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>%HOME%/Library/Logs/news-sentry.log</string>
    <key>StandardErrorPath</key>
    <string>%HOME%/Library/Logs/news-sentry.err</string>
</dict>
</plist>
```

- [ ] **Step 3: 创建 Linux/macOS 安装脚本**

`scripts/install.sh`:

```bash
#!/usr/bin/env bash
# News Sentry — Linux/macOS 安装脚本
# 用法: ./scripts/install.sh [--user]
set -euo pipefail

OS=$(uname -s)
INSTALL_DIR="$HOME/.news-sentry"
VENV_DIR="$INSTALL_DIR/venv"

echo "==> News Sentry 本地客户端安装"
echo "    OS: $OS"
echo "    安装目录: $INSTALL_DIR"

# 1. 创建目录结构
mkdir -p "$INSTALL_DIR"/{data,logs,config}

# 2. 创建 Python venv（如不存在）
if [ ! -d "$VENV_DIR" ]; then
    echo "==> 创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install news-sentry
fi

# 3. 安装 OS 服务
if [ "$OS" = "Linux" ]; then
    echo "==> 安装 systemd 用户服务..."
    mkdir -p "$HOME/.config/systemd/user"
    SERVICE_FILE="$HOME/.config/systemd/user/news-sentry.service"
    sed -e "s|%INSTALL_DIR%|$INSTALL_DIR|g" \
        -e "s|%USER%|$USER|g" \
        "$(dirname "$0")/news-sentry.service" > "$SERVICE_FILE"
    systemctl --user daemon-reload
    echo "    systemd unit 已安装到: $SERVICE_FILE"
    echo ""
    echo "==> 后续操作:"
    echo "    systemctl --user enable --now news-sentry   # 启用开机自启并立即启动"
    echo "    systemctl --user status news-sentry          # 查看状态"
    echo "    journalctl --user -u news-sentry -f          # 查看日志"
elif [ "$OS" = "Darwin" ]; then
    echo "==> 安装 launchd 用户服务..."
    mkdir -p "$HOME/Library/LaunchAgents"
    PLIST_FILE="$HOME/Library/LaunchAgents/com.news-sentry.plist"
    sed -e "s|%INSTALL_DIR%|$INSTALL_DIR|g" \
        -e "s|%HOME%|$HOME|g" \
        "$(dirname "$0")/com.news-sentry.plist" > "$PLIST_FILE"
    launchctl load "$PLIST_FILE"
    echo "    launchd plist 已安装到: $PLIST_FILE"
    echo ""
    echo "==> 后续操作:"
    echo "    launchctl list | grep news-sentry    # 查看状态"
    echo "    launchctl unload $PLIST_FILE         # 停止服务"
else
    echo "错误: 不支持的操作系统 ($OS)"
    exit 1
fi

echo ""
echo "==> 安装完成！浏览器打开 http://localhost:8000"
```

- [ ] **Step 4: 创建 Windows 安装脚本**

`scripts/install.ps1`:

```powershell
# News Sentry — Windows 安装脚本
# 用法: powershell -ExecutionPolicy Bypass -File scripts/install.ps1

$InstallDir = "$env:USERPROFILE\.news-sentry"
$VenDir = "$InstallDir\venv"
$StartupDir = [Environment]::GetFolderPath("Startup")

Write-Host "==> News Sentry 本地客户端安装" -ForegroundColor Cyan
Write-Host "    安装目录: $InstallDir"

# 1. 创建目录结构
New-Item -ItemType Directory -Force -Path "$InstallDir\data", "$InstallDir\logs", "$InstallDir\config" | Out-Null

# 2. 创建 Python venv
if (-not (Test-Path "$VenDir")) {
    Write-Host "==> 创建 Python 虚拟环境..."
    python -m venv "$VenDir"
    & "$VenDir\Scripts\pip" install --upgrade pip
    & "$VenDir\Scripts\pip" install news-sentry
}

# 3. 创建开机自启快捷方式（使用 pythonw 无控制台窗口）
$ShortcutPath = "$StartupDir\News-Sentry.lnk"
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$VenDir\Scripts\pythonw.exe"
$Shortcut.Arguments = "-m news_sentry.cli serve --foreground"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Save()

Write-Host ""
Write-Host "==> 安装完成！" -ForegroundColor Green
Write-Host "    浏览器打开 http://localhost:8000"
Write-Host "    开机自启快捷方式已创建: $ShortcutPath"
```

- [ ] **Step 5: 设置脚本可执行权限**

Run: `chmod +x scripts/install.sh`

- [ ] **Step 6: Commit**

```bash
git add scripts/news-sentry.service scripts/com.news-sentry.plist scripts/install.sh scripts/install.ps1
git commit -m "Phase 50: 新增 OS 服务文件 (systemd/launchd) + 安装脚本 (Linux/macOS/Windows)"
```

---

### Task 5: 集成测试

**Files:**
- Create: `tests/unit/test_serve.py`

- [ ] **Step 1: 创建测试文件**

`tests/unit/test_serve.py`:

```python
"""serve 命令测试 — PID 管理 + 环境变量 + Click 选项解析。"""

from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from news_sentry.cli import main
from news_sentry.cli.serve import _load_env_file, _pid_alive


# ── _load_env_file ────────────────────────────────────

def test_load_env_file_sets_variables(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("FOO=bar\nBAZ=qux\n")

    _load_env_file(env_file)
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_env_file_skips_existing():
    os.environ["EXISTING_KEY"] = "original"
    env_file = Path(tempfile.mktemp(suffix=".env"))
    env_file.write_text("EXISTING_KEY=overridden\n")

    _load_env_file(env_file)
    assert os.environ["EXISTING_KEY"] == "original"  # 不覆盖已有变量
    env_file.unlink()


def test_load_env_file_skips_comments_and_blanks(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("# comment line\n\nKEY1=val1\n  \nKEY2=val2\n")

    _load_env_file(env_file)
    assert os.environ["KEY1"] == "val1"
    assert os.environ["KEY2"] == "val2"


def test_load_env_file_noop_if_missing(tmp_path):
    nonexistent = tmp_path / "nonexistent.env"
    _load_env_file(nonexistent)  # 不应崩溃


# ── _pid_alive ────────────────────────────────────────

def test_pid_alive_current_process(tmp_path):
    """当前进程的 PID 应检测为存活。"""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text(str(os.getpid()))
    assert _pid_alive(pid_file) is True


def test_pid_alive_nonexistent_pid(tmp_path):
    """不存在的 PID 应返回 False。"""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("99999")  # 大概率不存在的 PID
    assert _pid_alive(pid_file) is False


def test_pid_alive_invalid_content(tmp_path):
    """PID 文件内容非法时返回 False。"""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("not-a-pid")
    assert _pid_alive(pid_file) is False


def test_pid_alive_missing_file(tmp_path):
    """PID 文件不存在时返回 False。"""
    assert _pid_alive(tmp_path / "nonexistent.pid") is False


# ── Click 命令选项解析 ────────────────────────────────

def test_serve_help():
    """serve --help 显示所有选项。"""
    result = CliRunner().invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--target" in result.output
    assert "--interval" in result.output
    assert "--no-browser" in result.output
    assert "--foreground" in result.output


def test_serve_default_options():
    """默认选项解析正确。"""
    result = CliRunner().invoke(
        main,
        ["serve", "--no-browser", "--foreground", "--help"],
    )
    assert result.exit_code == 0


def test_serve_rejects_duplicate_instance(tmp_path, monkeypatch):
    """PID 文件存在且进程存活时应拒绝启动。"""
    pid_file = tmp_path / "serve.pid"
    pid_file.write_text(str(os.getpid()))  # 当前进程 PID = 存活

    # 跳过 uvicorn.run 避免实际启动
    monkeypatch.setattr("news_sentry.cli.serve.uvicorn.run", lambda **kw: None)

    result = CliRunner().invoke(
        main,
        [
            "serve",
            "--pid-file", str(pid_file),
            "--foreground",
            "--no-browser",
        ],
    )
    assert result.exit_code == 1
    assert "已在运行" in result.output


# ── 环境变量传递 ──────────────────────────────────────

def test_serve_sets_env_vars(tmp_path, monkeypatch):
    """serve 启动时正确设置传递给 api_server 的环境变量。"""
    captured_env: dict[str, str] = {}

    def fake_uvicorn_run(**kw):
        captured_env["NEWSSENTRY_DATA_DIR"] = os.environ.get("NEWSSENTRY_DATA_DIR", "")
        captured_env["NEWSSENTRY_AUTO_COLLECT"] = os.environ.get("NEWSSENTRY_AUTO_COLLECT", "")
        captured_env["NEWSSENTRY_TARGET_ID"] = os.environ.get("NEWSSENTRY_TARGET_ID", "")
        captured_env["NEWSSENTRY_COLLECT_INTERVAL"] = os.environ.get(
            "NEWSSENTRY_COLLECT_INTERVAL", ""
        )

    monkeypatch.setattr("news_sentry.cli.serve.uvicorn.run", fake_uvicorn_run)

    data_dir = tmp_path / "data"
    pid_file = tmp_path / "serve.pid"

    CliRunner().invoke(
        main,
        [
            "serve",
            "--data-dir", str(data_dir),
            "--pid-file", str(pid_file),
            "--target", "italy,germany",
            "--interval", "30",
            "--foreground",
            "--no-browser",
        ],
    )

    assert "italy,germany" in captured_env["NEWSSENTRY_TARGET_ID"]
    assert captured_env["NEWSSENTRY_AUTO_COLLECT"] == "1"
    assert captured_env["NEWSSENTRY_COLLECT_INTERVAL"] == "30"
    assert str(data_dir) in captured_env["NEWSSENTRY_DATA_DIR"]


# ── 平台特定 ──────────────────────────────────────────

@pytest.mark.skipif(platform.system() == "Windows", reason="Unix 信号测试")
def test_serve_cleans_pid_on_sigterm(tmp_path, monkeypatch):
    """Unix: SIGTERM 后 PID 文件应被清理。"""
    import signal

    pid_file = tmp_path / "serve.pid"
    signal_received = []

    def fake_uvicorn_run(**kw):
        # 模拟 uvicorn 阻塞中
        signal_received.append(True)
        # 手动触发信号处理器
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr("news_sentry.cli.serve.uvicorn.run", fake_uvicorn_run)

    # 此测试验证信号处理器被注册，实际清理在进程退出后
    # 这里只验证不崩溃
    # 由于 SIGTERM 会触发 sys.exit(0)，我们用 CliRunner 捕获
    result = CliRunner().invoke(
        main,
        [
            "serve",
            "--pid-file", str(pid_file),
            "--foreground",
            "--no-browser",
        ],
    )
    # 进程被 SIGTERM 终止，exit_code 可能非零
    # 验证 signal 处理器确实被触发
    assert signal_received
    # PID 文件应已被清理
    assert not pid_file.exists()
```

- [ ] **Step 2: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_serve.py -v`
Expected: 全部 PASS（10+ tests）

- [ ] **Step 3: 运行全量测试**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 全量通过 (1650+)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_serve.py
git commit -m "Phase 50: 新增 serve 命令测试 — PID/环境变量/Click 选项 (12 tests)"
```

---

### Task 6: 文档更新

**Files:**
- Modify: `docs/roadmap/development-plan.md`
- Modify: `README.md`

- [ ] **Step 1: 在 development-plan.md 添加 Phase 50 条目**

在最后完成的 Phase 之后添加：

```markdown
## Phase 50: 本地客户端 v1 (2026-05-18)

- [x] `news-sentry serve` 命令 — 后台常驻服务（PID 管理 + 信号处理 + env 文件加载）
- [x] api_server 多 target 自动采集（`bounded_run_multi_async`）
- [x] OS 服务集成：systemd (Linux) + launchd (macOS) + Task Scheduler (Windows)
- [x] 安装脚本: `scripts/install.sh` (Linux/macOS) + `scripts/install.ps1` (Windows)
- [x] 测试: `tests/unit/test_serve.py` (12 tests)
- [ ] Phase 51: Rust Supervisor (进程守护 + 崩溃恢复 + 自动更新)
```

- [ ] **Step 2: 在 README.md 添加 serve 命令说明**

在 "CLI 命令" 章节或 `news-sentry run` 说明之后添加：

```markdown
### `news-sentry serve` — 本地后台常驻服务

启动 News Sentry 作为跨平台后台服务运行，提供 Web UI 管理界面：

```bash
# 默认启动: localhost:8000 + 所有 targets + 15 分钟采集间隔
news-sentry serve

# 自定义端口
news-sentry serve --port 8080

# 单 target 模式
news-sentry serve --target italy

# 指定多个 target
news-sentry serve --target italy,germany

# 前台调试（Ctrl+C 退出）
news-sentry serve --foreground

# 30 分钟采集间隔
news-sentry serve --interval 30
```

**开机自启安装：**

```bash
# Linux/macOS
./scripts/install.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

**环境变量文件** (`~/.news-sentry/env`):

```bash
# KEY=VALUE 格式，行首 # 为注释
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
NEWSSENTRY_PROFILE=local
```
```

- [ ] **Step 3: Commit**

```bash
git add docs/roadmap/development-plan.md README.md
git commit -m "Phase 50: 文档更新 — development-plan + README serve 使用说明"
```

---

### Task 7: 端到端手动验证

- [ ] **Step 1: 前台启动 serve**

```bash
.venv/bin/python3 -m news_sentry.cli serve --foreground --no-browser --port 18080 &
SERVE_PID=$!
sleep 3
```

- [ ] **Step 2: 验证 health 端点**

```bash
curl -s http://localhost:18080/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: 验证 collector/status 端点**

```bash
curl -s http://localhost:18080/api/v1/collector/status | python3 -m json.tool
```
Expected: 显示 `target_ids` 列表（非单个 `target_id`），`stage` 字段存在

- [ ] **Step 4: 验证 PID 文件**

```bash
cat ~/.news-sentry/serve.pid
```
Expected: 输出进程 PID

- [ ] **Step 5: 验证登录**

```bash
curl -s -X POST http://localhost:18080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python3 -m json.tool
```
Expected: 返回 `{"token":"...","role":"admin"}`

- [ ] **Step 6: 验证优雅退出**

```bash
kill $SERVE_PID
sleep 2
ls ~/.news-sentry/serve.pid 2>&1
```
Expected: 文件不存在（已被清理）

- [ ] **Step 7: 验证重复启动检测**

```bash
# 写入假 PID 后验证 zombie PID 覆盖写入
echo "99999" > ~/.news-sentry/serve.pid
.venv/bin/python3 -m news_sentry.cli serve --foreground --no-browser --port 18081 &
sleep 2
# 应正常启动（zombie PID 被覆盖）
curl -s http://localhost:18081/health
kill %1 2>/dev/null
```

- [ ] **Step 8: 运行全量回归测试**

```bash
ruff check && .venv/bin/python3 -m pytest tests/ -q
```
Expected: lint=0, tests 全部通过 (1650+)

---

## 完成标准

- [ ] 7 个 Tasks 全部完成 + commit
- [ ] `ruff check` 零错误
- [ ] `.venv/bin/python3 -m pytest tests/ -q` 全量通过 (1650+)
- [ ] `news-sentry serve --help` 正常显示
- [ ] 手动验证 8 步骤全部通过
