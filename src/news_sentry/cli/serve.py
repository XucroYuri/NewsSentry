"""News Sentry — serve 命令: 启动 API Server + 后台采集循环。

通过 ``NEWSSENTRY_DATA_DIR`` / ``NEWSSENTRY_AUTO_COLLECT`` 等环境变量
控制 ``create_app()`` 的启动行为，无需修改 api_server 代码。
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import signal
import sys
import webbrowser
from pathlib import Path

import click

from news_sentry.cli import main


def _load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE format env file, without overriding existing env vars.

    Skips comment lines starting with #.
    """
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _pid_alive(pid_path: Path) -> bool:
    """Check whether the process recorded in a PID file is still alive.

    Unix: os.kill(pid, 0)
    Windows: kernel32.OpenProcess
    """
    if not pid_path.is_file():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False

    if platform.system() == "Windows":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        synchronize = 0x100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _setup_log_file(log_path: Path, log_dir: Path) -> None:
    """Add a file handler so uvicorn/uvicorn.access logs are written to disk."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(fmt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(handler)


@main.command("serve")
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", default=8000, type=int, help="Bind port.")
@click.option(
    "--target",
    default="all",
    help="Monitor target ID (comma-separated or all). Sets NEWSSENTRY_TARGET_ID.",
)
@click.option(
    "--interval",
    default=15,
    type=int,
    help="Auto-collect interval in minutes (default 15). Sets NEWSSENTRY_COLLECT_INTERVAL.",
)
@click.option(
    "--stage",
    default="all",
    type=click.Choice(["collect", "filter", "judge", "output", "all"]),
    help="Pipeline stage for auto-collect loop (default: all). Sets NEWSSENTRY_COLLECT_STAGE.",
)
@click.option(
    "--profile",
    default=None,
    help="Deployment profile ID. Sets NEWSSENTRY_PROFILE.",
)
@click.option(
    "--data-dir",
    default="~/.news-sentry/data",
    help="Data root directory. Sets NEWSSENTRY_DATA_DIR.",
)
@click.option(
    "--log-dir",
    default="~/.news-sentry/logs",
    help="Log directory.",
)
@click.option(
    "--pid-file",
    default="~/.news-sentry/serve.pid",
    help="PID file path for singleton guard.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Skip opening browser on startup.",
)
@click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="Run in foreground (default behavior; flag reserved for future daemon mode).",
)
def serve(
    host: str,
    port: int,
    target: str,
    interval: int,
    stage: str,
    profile: str | None,
    data_dir: str,
    log_dir: str,
    pid_file: str,
    no_browser: bool,
    foreground: bool,  # noqa: ARG001 — reserved for future daemon mode
) -> None:
    """Start API Server with background auto-collect loop."""
    # 1. Expand paths
    data_path = Path(data_dir).expanduser().resolve()
    log_path_dir = Path(log_dir).expanduser().resolve()
    pid_path = Path(pid_file).expanduser().resolve()
    log_file = log_path_dir / "serve.log"

    # 2. Create directories
    data_path.mkdir(parents=True, exist_ok=True)
    log_path_dir.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    # 3. Auto-load ~/.news-sentry/env
    env_file = Path("~/.news-sentry/env").expanduser()
    if env_file.is_file():
        _load_env_file(env_file)

    # 4. PID alive check — reject if already running
    if _pid_alive(pid_path):
        click.echo(f"Error: News Sentry already running (PID file: {pid_path})", err=True)
        sys.exit(1)

    # 5. Set env vars for create_app() / auto-collector
    os.environ["NEWSSENTRY_DATA_DIR"] = str(data_path)
    os.environ["NEWSSENTRY_AUTO_COLLECT"] = "1"
    os.environ["NEWSSENTRY_COLLECT_INTERVAL"] = str(interval)
    os.environ["NEWSSENTRY_COLLECT_STAGE"] = stage
    os.environ["NEWSSENTRY_TARGET_ID"] = target
    if profile:
        os.environ["NEWSSENTRY_PROFILE"] = profile

    # 6. Write PID file
    pid_path.write_text(str(os.getpid()))

    # 7. PID cleanup — atexit (guaranteed) + signal (best-effort for Unix)
    def _cleanup_pid() -> None:
        try:
            pid_path.unlink(missing_ok=True)
        except Exception:  # noqa: S110 — best-effort cleanup
            pass

    atexit.register(_cleanup_pid)

    if platform.system() != "Windows":

        def _handle_signal(signum: int, frame: object) -> None:
            sys.exit(0)

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    # 8. Log file — uvicorn logs to disk via file handler
    _setup_log_file(log_file, log_path_dir)

    # 9. Open browser unless --no-browser
    if not no_browser:
        display_host = "127.0.0.1" if host == "0.0.0.0" else host  # noqa: S104
        url = f"http://{display_host}:{port}"
        click.echo(f"Opening browser: {url}")
        try:
            webbrowser.open(url)
        except Exception:  # noqa: S110 — browser open is best-effort on headless servers
            pass

    # 10. Startup banner
    click.echo("")
    click.echo("  News Sentry v1.6.0 — local server")
    click.echo("  ─────────────────────────────────")
    click.echo(f"  API:      http://{host}:{port}")
    click.echo(f"  Data:     {data_path}")
    click.echo(f"  Log:      {log_file}")
    click.echo(f"  Target:   {target}")
    click.echo(f"  Stage:    {stage}")
    if profile:
        click.echo(f"  Profile:  {profile}")
    click.echo(f"  Interval: {interval} min")
    click.echo("  ─────────────────────────────────")
    click.echo("")

    import uvicorn

    uvicorn.run(
        "news_sentry.core.api_server:create_app",
        factory=True,
        host=host,
        port=port,
    )
