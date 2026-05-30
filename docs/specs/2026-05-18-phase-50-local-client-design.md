# Phase 50: 本地客户端 v1 — 设计文档

> 状态: Ready for Planning | 日期: 2026-05-18
> 路线: 渐进式（路线 4+5 分阶段推进的第一阶段）
> 目标: 新增 `news-sentry serve` 命令，实现多系统本地后台常驻服务
> 后续: Phase 51 (Rust Supervisor) → Phase 52 (系统托盘 + 桌面体验)

---

## §1. 问题与目标

### 当前状态

News Sentry v1.5.0 运行模式：
- **CLI 单次运行** (`news-sentry run`) — 执行一次 pipeline 后退出
- **CLI 循环模式** (`--interval`) — 进程内无限循环，终端关闭即终止
- **Cloudflare 部署** — Container Worker + cron trigger，但有冷启动延迟
- **Docker 部署** — `docker run` + 外部 cron，需要 Docker 环境

### 问题

1. 本地用户需要**持续运行**（24/7 后台监控），但现有方案依赖终端保持打开
2. 终端关闭 → 进程终止，没有守护能力
3. 没有开机自启机制
4. 跨平台安装无统一方案

### 目标

新增 `news-sentry serve` 命令：
- 作为后台常驻服务运行（不依赖终端保持打开）
- macOS / Linux / Windows 均支持
- 浏览器打开 `http://localhost:PORT` 使用现有 Web UI
- 可选开机自启
- 优雅退出（SIGTERM/SIGINT 保存状态后关闭）

---

## §2. 架构

```
┌─────────────────────────────────────────────────┐
│            用户浏览器                              │
│        http://localhost:8000                     │
│          (现有 Web SPA — 零改动)                   │
└────────────────────┬────────────────────────────┘
                     │ HTTP (localhost)
┌────────────────────▼────────────────────────────┐
│  uvicorn (ASGI)                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  FastAPI Application                      │    │
│  │  • REST API (40+ endpoints)               │    │
│  │  • 静态文件 (index.html + pages/*.js)      │    │
│  │  • 认证 (Bearer token)                    │    │
│  │  • Auto Collector (asyncio background)    │    │
│  └──────────────────────────────────────────┘    │
│  host: 127.0.0.1  port: 由 --port 指定           │
└────────────────────┬────────────────────────────┘
                     │ asyncio task
┌────────────────────▼────────────────────────────┐
│  Auto Collector (现有 _auto_collect_loop)         │
│  • 每 N 分钟触发 bounded_run_multi_async          │
│  • 采集 → 过滤 → 研判 → 输出                      │
│  • 状态查询: GET /api/v1/collector/status         │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  SQLite 数据层 (现有 AsyncStore)                   │
│  ~/.news-sentry/data/{target_id}/state.db         │
└─────────────────────────────────────────────────┘
```

### 与现有代码的关系

```
新增文件:  src/news_sentry/cli/serve.py       ← serve 命令实现
新增文件:  scripts/install.sh                  ← Linux/macOS 安装脚本
新增文件:  scripts/install.ps1                 ← Windows 安装脚本
新增文件:  scripts/news-sentry.service         ← systemd unit 模板
新增文件:  scripts/com.news-sentry.plist       ← launchd plist 模板
修改文件:  src/news_sentry/cli/__init__.py     ← 注册 serve 命令
修改文件:  src/news_sentry/core/api_server.py  ← _data_dir 环境变量 + _auto_collect_loop 多 target 升级
```

**零修改文件**（复用现有组件）：
- `src/news_sentry/core/async_run.py` — `bounded_run_multi_async()` + `run_loop_async()`
- `src/news_sentry/static/` — 前端完整复用
- `src/news_sentry/core/auth.py` — 认证不变

---

## §3. 功能规格

### §3.1 serve 命令

```
news-sentry serve [OPTIONS]
```

#### serve vs run --interval 的边界

| 维度 | `run --target all --stage all --interval N` | `serve` |
|------|---------------------------------------------|---------|
| 用途 | 终端内循环采集，人工临时执行 | 后台常驻服务，7×24 运行 |
| Web UI | 无 | 有 (http://localhost:PORT) |
| 终端依赖 | 终端关闭 → 进程终止 | 不依赖终端，可 daemonize |
| 开机自启 | 不支持 | 支持（systemd/launchd/Task Scheduler） |
| PID 管理 | 无 | 有 PID 文件 + 存活检测 |
| 场景 | 开发者调试、临时批量采集 | 个人持续监控、桌面常驻 |

**选项**:

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | 绑定 IP（安全默认 localhost） |
| `--port` | `8000` | 监听端口 |
| `--target` | `all` | 监控目标 ID，逗号分隔或 `all` |
| `--interval` | `15` | 采集间隔（分钟）|
| `--profile` | (env `NEWSSENTRY_PROFILE` 或 `local`) | 部署 profile |
| `--data-dir` | `~/.news-sentry/data` | 数据根目录 |
| `--log-dir` | `~/.news-sentry/logs` | 日志目录 |
| `--pid-file` | `~/.news-sentry/serve.pid` | PID 文件路径 |
| `--env-file` | (如有 `~/.news-sentry/env` 则自动加载) | 环境变量文件 (KEY=VALUE 格式) |
| `--no-browser` | (flag) | 启动时不自动打开浏览器 |
| `--foreground` | (flag) | 前台运行（不 daemonize），用于调试/容器 |

**行为**：

1. 自动加载 `~/.news-sentry/env`（如存在，每行 `KEY=VALUE` 格式）
2. 创建 `--data-dir` 和 `--log-dir`（不存在时自动创建）
3. PID 文件存活检测：如 PID 文件存在且该 PID 仍存活 → 拒绝启动（"已在运行"），如不存活 → 覆盖
4. 写入 PID 文件
5. 设置环境变量（传递给 api_server.py 的 `create_app()`）
6. 启动 FastAPI app（uvicorn programmatically）
7. 自动采集器作为 asyncio background task 启动（支持多 target）
8. 平台感知信号处理：Linux/macOS 注册 SIGTERM/SIGINT → 停止采集、删 PID、退出；Windows 跳过自定义信号处理器（依赖 uvicorn 内置 Ctrl+C）
9. （可选）打开默认浏览器到 `http://localhost:PORT`

### §3.2 OS 服务集成

#### Linux (systemd)

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

安装命令:
```bash
# 安装服务
./scripts/install.sh --user
# 启用开机自启
systemctl --user enable --now news-sentry
# 查看状态
systemctl --user status news-sentry
```

#### macOS (launchd)

`scripts/com.news-sentry.plist`:
```xml
<key>KeepAlive</key><true/>
<key>RunAtLoad</key><true/>
<key>ProgramArguments</key>
<array>
    <string>%INSTALL_DIR%/venv/bin/python</string>
    <string>-m</string>
    <string>news_sentry.cli</string>
    <string>serve</string>
    <string>--foreground</string>
</array>
```

安装:
```bash
./scripts/install.sh
# launchd 自动加载 ~/Library/LaunchAgents/
```

#### Windows

`scripts/install.ps1`:
- 创建快捷方式到 Startup 文件夹（用户级开机自启）
- 或注册 Task Scheduler 任务（更可靠的后台运行）
- 使用 `pythonw.exe -m news_sentry.cli serve --foreground`（无控制台窗口）

### §3.3 安装脚本

`scripts/install.sh` 功能：
1. 检测 OS（Linux/macOS）
2. 创建 `~/.news-sentry/` 目录结构
3. 创建 Python venv（如不存在）并 `pip install news-sentry`
4. 安装 OS 服务文件（systemd unit 或 launchd plist）
5. 输出后续操作指引（systemctl start、浏览器打开等）

---

## §4. 数据目录布局

```
~/.news-sentry/
├── data/                      # 数据根目录 (--data-dir)
│   ├── {target_id}/           # 每个 target 独立目录
│   │   └── state.db           # SQLite 数据库
│   └── config/                # 用户配置覆盖
├── logs/                      # 日志目录 (--log-dir)
│   └── serve.log              # serve 进程日志
├── serve.pid                  # PID 文件
└── env                        # 环境变量文件（手动创建）
```

### 与现有 CLI `run` 的数据目录兼容

- `--data-dir` 默认为 `~/.news-sentry/data`（与项目内 `./data/` 隔离）
- API Server 的 `_data_dir` 通过环境变量 `NEWSSENTRY_DATA_DIR` 注入
- Pipeline 的 `config_dir` 默认为包安装路径（site-packages 下的 config/）
- 用户可通过 `~/.news-sentry/data/config/` 覆盖配置

---

## §5. serve.py 实现要点

```python
# src/news_sentry/cli/serve.py — 核心逻辑

import os
import platform
import sys
import webbrowser
from pathlib import Path

import click
import uvicorn

from news_sentry.cli import main as cli_group


def _load_env_file(env_path: Path) -> None:
    """加载 KEY=VALUE 格式的环境变量文件（行首 # 为注释）。"""
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


def _pid_alive(pid_path: Path) -> bool:
    """检查 PID 文件中记录的进程是否仍存活。"""
    import ctypes
    import signal as _signal

    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False

    # Windows: kernel32.TerminateProcess(0) 检查进程存在
    # Unix: os.kill(pid, 0)
    if platform.system() == "Windows":
        try:
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
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
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--target", default="all")
@click.option("--interval", default=15, type=int, help="采集间隔(分钟)")
@click.option("--profile", default=None, help="部署 profile")
@click.option("--data-dir", default="~/.news-sentry/data")
@click.option("--log-dir", default="~/.news-sentry/logs")
@click.option("--pid-file", default="~/.news-sentry/serve.pid")
@click.option("--no-browser", is_flag=True)
@click.option("--foreground", is_flag=True)
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
      Windows:  运行 scripts/install.ps1
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
        click.echo(f"错误: News Sentry 已在运行 (PID: {pid_path.read_text().strip()})", err=True)
        click.echo(f"如需重启，请先停止现有实例或删除 {pid_path}", err=True)
        sys.exit(1)

    # 4. 设置环境变量（传递给 api_server.py 的 create_app()）
    os.environ["NEWSSENTRY_DATA_DIR"] = str(data_path)
    os.environ["NEWSSENTRY_AUTO_COLLECT"] = "1"
    os.environ["NEWSSENTRY_COLLECT_INTERVAL"] = str(interval)
    os.environ["NEWSSENTRY_TARGET_ID"] = target
    if profile:
        os.environ["NEWSSENTRY_PROFILE"] = profile

    # 5. PID 文件
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    def cleanup() -> None:
        if pid_path.exists():
            pid_path.unlink(missing_ok=True)

    # 6. 平台感知信号处理
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

    # 8. 启动 FastAPI（复用 create_app 工厂函数）
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

---

## §6. 与现有 CLI 命令的关系

```
news-sentry run     — 单次 bounded run（现有，不变）
news-sentry serve   — 后台常驻服务（新增）
news-sentry skill   — 技能管理（现有，不变）
news-sentry tool    — 工具管理（现有，不变）
news-sentry validate — 配置校验（现有，不变）
news-sentry doctor  — 健康检查（现有，不变）
```

`serve` 命令复用 `create_app()` 工厂函数，后者已在 `api_server.py` 中实现：
- 创建 FastAPI app
- 挂载静态文件（Web UI）
- 设置 `_app_lifespan()` — 启动 auto collector + bootstrap users
- 注册所有 API 端点

---

## §7. 安全考量

| 项 | 处理 |
|-----|------|
| 默认绑定 | `127.0.0.1`（仅本机访问），非 `0.0.0.0` |
| 认证 | FastAPI 用户名+密码登录（现有），无认证无法访问读端点 |
| 开机自启 | 用户级服务（systemd --user / LaunchAgent），非 root |
| 数据隔离 | `~/.news-sentry/` 用户主目录下，不碰系统目录 |
| API Key | 存储在 SQLite users 表中，不硬编码 |
| PID 文件 | 仅本进程可写，退出时自动删除 |

---

## §8. 实现任务分解

### Task 50.1: `serve.py` 命令

**文件**: `src/news_sentry/cli/serve.py` (新建)
- 实现 `serve` 命令（§5 中的完整代码）
- PID 文件管理 + 信号处理 + 浏览器自动打开

### Task 50.2: 注册 serve 命令

**文件**: `src/news_sentry/cli/__init__.py` (修改)
- 导入 `serve` 模块使 Click 命令注册

### Task 50.3: api_server 多 target 适配 + 数据目录环境变量

**文件**: `src/news_sentry/core/api_server.py` (修改)

#### 50.3a: `_data_dir` 读取环境变量

```python
# 行 ~1217: create_app() 中
_data_dir = Path(os.environ.get("NEWSSENTRY_DATA_DIR", "./data"))
```

`create_app(data_dir: str | None = None)` 的默认值从 `Path("./data")` 改为优先检查 `NEWSSENTRY_DATA_DIR` 环境变量。

#### 50.3b: `_auto_collector_state` 支持多 target

```python
# 行 1039-1049: 修改初始化
_auto_collector_state: dict[str, Any] = {
    "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
    "target_ids": _parse_target_ids(os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "italy"))),
    "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15")),
    "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),  # 默认仅采集
    "running": False,
    # ... 其余不变
}

def _parse_target_ids(raw: str) -> list[str]:
    """解析 target ID 字符串：'all' → 全量 targets，'a,b' → ['a','b']."""
    if raw.strip().lower() == "all":
        from news_sentry.core.async_run import _resolve_targets
        import news_sentry
        config_dir = Path(news_sentry.__file__).resolve().parent.parent / "config"
        return _resolve_targets("all", config_dir)
    return [t.strip() for t in raw.split(",") if t.strip()]
```

#### 50.3c: `_auto_collect_loop` 调用 `bounded_run_multi_async`

```python
# 行 1054-1091: 将 bounded_run_async (单 target) 替换为 bounded_run_multi_async
async def _auto_collect_loop() -> None:
    interval = _auto_collector_state["interval_minutes"] * 60
    target_ids = _auto_collector_state["target_ids"]
    stage = _auto_collector_state["stage"]
    _auto_collector_state["running"] = True
    _log.info("自动采集循环启动: targets=%s, stage=%s, interval=%dmin",
              target_ids, stage, interval // 60)

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

#### 50.3d: collector/status 端点返回多 target 信息

```python
# 行 1229-1250: collector_status() 返回值更新
return {
    "enabled": _auto_collector_state["enabled"],
    "running": _auto_collector_state["running"],
    "target_ids": _auto_collector_state["target_ids"],  # 从 "target_id" 改为 "target_ids"
    "stage": _auto_collector_state["stage"],             # 新增
    # ... 其余不变
}
```

> 注意：`collector/status` 端点字段 `target_id` → `target_ids` 是 breaking change，但此端点为内部使用，无外部消费者。

### Task 50.4: OS 服务文件

**新建文件**:
- `scripts/news-sentry.service` — systemd unit 模板
- `scripts/com.news-sentry.plist` — launchd plist 模板
- `scripts/install.sh` — Linux/macOS 安装脚本
- `scripts/install.ps1` — Windows 安装脚本

### Task 50.5: 集成测试

**文件**: `tests/unit/test_serve.py` (新建)
- 测试 serve 命令 Click 选项解析
- 测试 PID 文件创建/清理
- 测试环境变量传递

### Task 50.6: 文档更新

- `docs/roadmap/development-plan.md` — 添加 Phase 50 条目
- `README.md` — 添加 `serve` 命令使用说明

---

## §9. 验证计划

### 代码质量
1. `ruff check src/news_sentry/cli/serve.py src/news_sentry/core/api_server.py` — lint 零错误
2. `.venv/bin/python3 -m mypy src/news_sentry/cli/serve.py` — 类型检查通过

### serve 命令基础验证
3. `news-sentry serve --help` — Click 参数帮助正常，11 个选项全显示
4. `news-sentry serve --foreground --no-browser --port 18080` — 前台启动成功
5. `curl http://localhost:18080/health` — 返回 `{"status":"ok"}`
6. `curl -X POST http://localhost:18080/api/v1/auth/login -d '{"username":"admin","password":"..."}'` — 登录成功返回 `{"token":"...","role":"admin"}`

### PID 管理
7. PID 文件在启动时创建：`cat ~/.news-sentry/serve.pid` 输出进程 PID
8. 存活检测：再次 `serve --foreground` → 错误退出 "已在运行"
9. 僵尸 PID 覆盖：写入假 PID → 再次启动成功（覆写）
10. 优雅退出：`kill <pid>` → PID 文件自动删除

### 环境变量文件
11. 创建 `~/.news-sentry/env` 写入 `NEWSSENTRY_PROFILE=test-profile` → 启动后 `collector/status` 验证 profile 生效
12. env 文件注释行/空行被正确跳过

### 多 target 自动采集
13. `serve --target all` → `GET /api/v1/collector/status` 返回 `target_ids: ["italy","china-watch-en",...]`
14. `serve --target italy,germany` → collector 状态显示 2 个 target
15. 采集完成后 `GET /api/v1/events?target_id=italy` 返回事件数据

### 跨平台
16. macOS 前台运行 + SIGTERM 清理验证
17. Windows 启动跳过信号处理器（无崩溃）

### 前端
18. 浏览器打开 `http://localhost:PORT` → 完整 Web UI（三层导航 + 登录表单）
19. 登录后查看 events/stats/targets/entities 数据

### 全量回归
20. `.venv/bin/python3 -m pytest tests/ -q` — 全量测试通过 (1640+)
