"""News Sentry — serve/stop/install/status/logs/restart/uninstall 命令。

通过 ``NEWSSENTRY_DATA_DIR`` / ``NEWSSENTRY_AUTO_COLLECT`` 等环境变量
控制 ``create_app()`` 的启动行为，无需修改 api_server 代码。
"""

from __future__ import annotations

import atexit
import logging
import os
import platform
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import UTC, datetime
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

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
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


def _kill_process(pid: int) -> bool:
    """Cross-platform process termination. Returns True on success."""
    if platform.system() == "Windows":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


def _setup_log_file(log_path: Path, log_dir: Path) -> None:
    """Add a file handler so uvicorn and news_sentry logs are written to disk."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(fmt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "news_sentry"):
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
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
    help="Log level for uvicorn and app logs (default: info).",
)
def serve(
    host: str,
    port: int,
    target: str,
    interval: int,
    stage: str,
    log_level: str,
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

    # 8. Check uvicorn availability before proceeding
    try:
        import uvicorn  # noqa: F401 — verify uvicorn is importable
    except ImportError:
        click.echo(
            "Error: uvicorn is not installed.\nInstall it with:\n  pip install 'news-sentry[api]'",
            err=True,
        )
        sys.exit(1)

    # 9. Set log level on app loggers before adding file handler
    level = getattr(logging, log_level.upper(), logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "news_sentry"):
        logging.getLogger(name).setLevel(level)

    # 10. Log file — uvicorn/app logs to disk via file handler
    _setup_log_file(log_file, log_path_dir)

    # 11. Open browser unless --no-browser
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
    from importlib.metadata import version as _pkg_version

    click.echo(f"  News Sentry v{_pkg_version('news-sentry')} — local server")
    click.echo("  ─────────────────────────────────")
    click.echo(f"  API:      http://{host}:{port}")
    click.echo(f"  Data:     {data_path}")
    click.echo(f"  Log:      {log_file}")
    click.echo(f"  Target:   {target}")
    click.echo(f"  Stage:    {stage}")
    if profile:
        click.echo(f"  Profile:  {profile}")
    click.echo(f"  Interval: {interval} min")
    click.echo(f"  LogLevel: {log_level}")
    click.echo("  ─────────────────────────────────")
    click.echo("")

    uvicorn.run(
        "news_sentry.core.api_server:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=log_level,
    )


@main.command("stop")
@click.option(
    "--pid-file",
    default="~/.news-sentry/serve.pid",
    help="PID file path of the running server.",
)
def stop(pid_file: str) -> None:
    """Stop a running News Sentry server (by PID file)."""
    pid_path = Path(pid_file).expanduser().resolve()

    if not pid_path.is_file():
        click.echo(f"No PID file found at {pid_path}. Server may not be running.")
        return

    pid_str = pid_path.read_text().strip()
    try:
        pid = int(pid_str)
    except (ValueError, OSError):
        click.echo(f"Invalid PID file content: {pid_str}", err=True)
        pid_path.unlink(missing_ok=True)
        return

    if not _pid_alive(pid_path):
        click.echo(f"PID {pid} is not alive. Removing stale PID file.")
        pid_path.unlink(missing_ok=True)
        return

    click.echo(f"Stopping News Sentry (PID: {pid})...")
    if not _kill_process(pid):
        click.echo(f"Failed to send signal to PID {pid}", err=True)
        sys.exit(1)

    pid_path.unlink(missing_ok=True)
    click.echo(f"Server stopped (PID: {pid}).")


# ── shared defaults for install / restart ────────────────────────────────

_SERVE_OPTIONS = [
    click.option("--host", default="127.0.0.1", help="Bind address."),
    click.option("--port", default=8000, type=int, help="Bind port."),
    click.option("--target", default="all", help="Comma-separated target IDs or 'all'."),
    click.option("--interval", default=15, type=int, help="Auto-collect interval (minutes)."),
    click.option(
        "--stage",
        default="all",
        type=click.Choice(["collect", "filter", "judge", "output", "all"]),
        help="Pipeline stage.",
    ),
    click.option("--profile", default=None, help="Deployment profile ID."),
    click.option("--data-dir", default="~/.news-sentry/data", help="Data root directory."),
    click.option("--log-dir", default="~/.news-sentry/logs", help="Log directory."),
    click.option("--pid-file", default="~/.news-sentry/serve.pid", help="PID file path."),
    click.option("--no-browser", is_flag=True, default=False, help="Skip opening browser."),
    click.option(
        "--log-level",
        default="info",
        type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
        help="Log level.",
    ),
]


def _serve_options(func):  # type: ignore[no-untyped-def]  # noqa: ANN202 ANN001
    """Decorator that applies common serve options to a Click command."""
    for option in reversed(_SERVE_OPTIONS):
        func = option(func)
    return func


# ── plist / systemd template helpers ─────────────────────────────────────


def _plist_content(  # noqa: PLR0913
    label: str,
    program_args: list[str],
    working_dir: str,
    stdout_path: str,
    stderr_path: str,
    data_dir: str,
    auto_collect: str,
    collect_interval: str,
) -> str:
    """Generate a macOS LaunchAgent plist."""
    return (
        (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
            ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            f"  <key>Label</key>\n"
            f"  <string>{label}</string>\n"
            f"  <key>KeepAlive</key>\n"
            f"  <true/>\n"
            f"  <key>RunAtLoad</key>\n"
            f"  <true/>\n"
            f"  <key>ProgramArguments</key>\n"
            f"  <array>\n"
        )
        + "".join(f"    <string>{a}</string>\n" for a in program_args)
        + (
            f"  </array>\n"
            f"  <key>WorkingDirectory</key>\n"
            f"  <string>{working_dir}</string>\n"
            f"  <key>StandardOutPath</key>\n"
            f"  <string>{stdout_path}</string>\n"
            f"  <key>StandardErrorPath</key>\n"
            f"  <string>{stderr_path}</string>\n"
            f"  <key>EnvironmentVariables</key>\n"
            f"  <dict>\n"
            f"    <key>NEWSSENTRY_DATA_DIR</key>\n"
            f"    <string>{data_dir}</string>\n"
            f"    <key>NEWSSENTRY_AUTO_COLLECT</key>\n"
            f"    <string>{auto_collect}</string>\n"
            f"    <key>NEWSSENTRY_COLLECT_INTERVAL</key>\n"
            f"    <string>{collect_interval}</string>\n"
            f"  </dict>\n"
            f"  <key>ProcessType</key>\n"
            f"  <string>Background</string>\n"
            f"  <key>ThrottleInterval</key>\n"
            f"  <integer>5</integer>\n"
            f"</dict>\n"
            f"</plist>\n"
        )
    )


def _systemd_content(  # noqa: PLR0913
    description: str,
    exec_start: str,
    working_dir: str,
    stdout_path: str,
    stderr_path: str,
    data_dir: str,
    log_dir: str,
) -> str:
    """Generate a systemd user service unit file."""
    return (
        f"[Unit]\n"
        f"Description={description}\n"
        f"Documentation=https://github.com/xucroyuri/news-sentry\n"
        f"After=network.target\n\n"
        f"[Service]\n"
        f"Type=simple\n"
        f"ExecStart={exec_start}\n"
        f"WorkingDirectory={working_dir}\n"
        f"Restart=always\n"
        f"RestartSec=10\n"
        f"StandardOutput=append:{stdout_path}\n"
        f"StandardError=append:{stderr_path}\n"
        f"Environment=NEWSSENTRY_DATA_DIR={data_dir}\n"
        f"Environment=NEWSSENTRY_LOG_DIR={log_dir}\n\n"
        f"[Install]\n"
        f"WantedBy=default.target\n"
    )


# ── install ──────────────────────────────────────────────────────────────


@main.command("install")
@_serve_options  # type: ignore[untyped-decorator]
@click.option("--force", is_flag=True, default=False, help="Overwrite existing service file.")
def install(  # noqa: PLR0913
    host: str,
    port: int,
    target: str,
    interval: int,
    stage: str,
    log_level: str,
    profile: str | None,
    data_dir: str,
    log_dir: str,
    pid_file: str,
    no_browser: bool,
    force: bool,
    foreground: bool = False,  # noqa: ARG001
) -> None:
    """Register News Sentry as an OS background service.

    macOS  → LaunchAgent  (~/Library/LaunchAgents/)
    Linux  → systemd user unit (~/.config/systemd/user/)
    """
    system = platform.system()
    data_path = Path(data_dir).expanduser().resolve()
    log_path_dir = Path(log_dir).expanduser().resolve()
    log_file = log_path_dir / "serve.log"

    # Build the serve command line for the service file.
    serve_args = [
        sys.executable,
        "-m",
        "news_sentry.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--target",
        target,
        "--interval",
        str(interval),
        "--stage",
        stage,
        "--log-level",
        log_level,
        "--data-dir",
        str(data_path),
        "--log-dir",
        str(log_path_dir),
        "--pid-file",
        str(Path(pid_file).expanduser().resolve()),
        "--foreground",
    ]
    if profile:
        serve_args.extend(["--profile", profile])
    if no_browser:
        serve_args.append("--no-browser")

    # Create required directories upfront.
    data_path.mkdir(parents=True, exist_ok=True)
    log_path_dir.mkdir(parents=True, exist_ok=True)

    if system == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/com.news-sentry.plist"
        if plist_path.exists() and not force:
            click.echo(f"Service already installed at {plist_path}. Use --force to overwrite.")
            sys.exit(1)

        content = _plist_content(
            label="com.news-sentry",
            program_args=serve_args,
            working_dir=str(Path.home() / ".news-sentry"),
            stdout_path=str(log_file),
            stderr_path=str(log_file),
            data_dir=str(data_path),
            auto_collect="1",
            collect_interval=str(interval),
        )
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(content, encoding="utf-8")
        click.echo(f"LaunchAgent written → {plist_path}")

        # Try to load immediately.
        try:
            subprocess.run(  # noqa: S603
                ["launchctl", "load", str(plist_path)],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo("Service loaded. It will start automatically at next login.")
        except subprocess.CalledProcessError as exc:
            click.echo(
                f"Note: launchctl load failed ({exc.stderr.strip()}). "
                f"You can load it manually:\n  launchctl load {plist_path}"
            )

    elif system == "Linux":
        unit_dir = Path.home() / ".config/systemd/user"
        unit_path = unit_dir / "news-sentry.service"
        if unit_path.exists() and not force:
            click.echo(f"Service already installed at {unit_path}. Use --force to overwrite.")
            sys.exit(1)

        content = _systemd_content(
            description="News Sentry — News Intelligence Monitor",
            exec_start=" ".join(serve_args),
            working_dir=str(Path.home() / ".news-sentry"),
            stdout_path=str(log_file),
            stderr_path=str(log_file),
            data_dir=str(data_path),
            log_dir=str(log_path_dir),
        )
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(content, encoding="utf-8")
        click.echo(f"systemd user unit written → {unit_path}")

        try:
            subprocess.run(  # noqa: S603
                ["systemctl", "--user", "daemon-reload"],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(  # noqa: S603
                ["systemctl", "--user", "enable", "news-sentry.service"],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo("Service enabled. Start it with:\n  systemctl --user start news-sentry")
        except subprocess.CalledProcessError as exc:
            click.echo(
                f"Note: systemctl failed ({exc.stderr.strip()}). "
                f"Set it up manually:\n"
                f"  systemctl --user daemon-reload\n"
                f"  systemctl --user enable --now news-sentry"
            )

    elif system == "Windows":
        # Register as a Scheduled Task triggered at logon.
        launcher_ps1 = Path.home() / ".news-sentry" / "launcher.ps1"
        launcher_ps1.parent.mkdir(parents=True, exist_ok=True)

        # Build the serve command line for the launcher script.
        serve_cmd = (
            f"& '{sys.executable}' -m news_sentry.cli serve "
            f"--host {host} --port {port} --target {target} "
            f"--interval {interval} --stage {stage} --log-level {log_level} "
            f"--data-dir '{data_path}' --log-dir '{log_path_dir}' "
            f"--pid-file '{Path(pid_file).expanduser().resolve()}' "
            f"--foreground"
        )
        if profile:
            serve_cmd += f" --profile {profile}"
        if no_browser:
            serve_cmd += " --no-browser"
        ps_content = (
            f"# News Sentry launcher — triggered by Scheduled Task at logon\n"
            f"Set-Location '{launcher_ps1.parent}'\n"
            f"{serve_cmd} *>> '{log_file}'\n"
        )
        launcher_ps1.write_text(ps_content, encoding="utf-8")
        click.echo(f"Launcher written → {launcher_ps1}")

        # Remove old task if it exists, then create new one.
        subprocess.run(  # noqa: S603
            ["schtasks", "/Delete", "/TN", "NewsSentry", "/F"],  # noqa: S607
            capture_output=True,
        )
        try:
            ps_args = (
                "powershell.exe -NoProfile -WindowStyle Hidden "
                f'-ExecutionPolicy Bypass -File "{launcher_ps1}"'
            )
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "schtasks",
                    "/Create",
                    "/TN",
                    "NewsSentry",
                    "/TR",
                    ps_args,
                    "/SC",
                    "ONLOGON",
                    "/IT",
                    "/F",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo("Scheduled Task 'NewsSentry' created (runs at logon).")
        except subprocess.CalledProcessError as exc:
            click.echo(
                f"Note: schtasks failed ({exc.stderr.strip()}). "
                f"Create the task manually or use a Scheduled Task trigger."
            )

        # Start the task immediately.
        subprocess.run(  # noqa: S603
            ["schtasks", "/Run", "/TN", "NewsSentry"],  # noqa: S607
            capture_output=True,
        )
        click.echo("Task started. Check status with: news-sentry status")

    else:
        click.echo(f"Unsupported OS: {system}. Manual setup required.", err=True)
        sys.exit(1)


# ── status ───────────────────────────────────────────────────────────────


def _format_uptime(started_at: float) -> str:
    """Return a human-readable uptime string from a Unix timestamp."""
    seconds = int(time.time() - started_at)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


@main.command("status")
@click.option("--pid-file", default="~/.news-sentry/serve.pid", help="PID file path.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output as JSON.")
def status(pid_file: str, json_output: bool) -> None:
    """Show whether the News Sentry server is running."""
    pid_path = Path(pid_file).expanduser().resolve()
    alive = _pid_alive(pid_path)

    if json_output:
        import json as _json

        info: dict[str, object] = {"running": alive}
        if alive and pid_path.is_file():
            pid = int(pid_path.read_text().strip())
            mtime = pid_path.stat().st_mtime
            info["pid"] = pid
            info["pid_file"] = str(pid_path)
            info["started_at"] = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
            info["uptime"] = _format_uptime(mtime)
        click.echo(_json.dumps(info, indent=2))
        return

    if not alive:
        click.echo("News Sentry:  stopped")
        click.echo(f"  PID file: {pid_path}")
        click.echo("  Run 'news-sentry serve' to start the server.")
        return

    pid = int(pid_path.read_text().strip())
    mtime = pid_path.stat().st_mtime
    started = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    click.echo("News Sentry:  running")
    click.echo(f"  PID:        {pid}")
    click.echo(f"  Started:    {started}")
    click.echo(f"  Uptime:     {_format_uptime(mtime)}")
    click.echo(f"  PID file:   {pid_path}")

    # Best-effort: read NEWSSENTRY_ env vars from /proc on Linux.
    if platform.system() == "Linux":
        try:
            env_text = Path(f"/proc/{pid}/environ").read_text(encoding="utf-8")
            for item in env_text.split("\0"):
                if "=" in item:
                    k, _, v = item.partition("=")
                    if k.startswith("NEWSSENTRY_"):
                        click.echo(f"  {k}: {v}")
        except OSError:
            pass


# ── logs ─────────────────────────────────────────────────────────────────


@main.command("logs")
@click.option("--log-dir", default="~/.news-sentry/logs", help="Log directory.")
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show.")
@click.option("--follow", "-f", is_flag=True, default=False, help="Follow log output.")
def logs(log_dir: str, lines: int, follow: bool) -> None:
    """View News Sentry server logs."""
    log_path = Path(log_dir).expanduser().resolve() / "serve.log"

    if not log_path.is_file():
        click.echo(f"Log file not found: {log_path}", err=True)
        click.echo("The server may not have been started yet.", err=True)
        sys.exit(1)

    if follow:
        click.echo(f"Following {log_path} (Ctrl+C to exit)...")
        try:
            # Read last N lines first, then tail -f style follow.
            content = log_path.read_text(encoding="utf-8")
            all_lines = content.splitlines()
            for line in all_lines[-lines:]:
                click.echo(line)

            with open(log_path, encoding="utf-8") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if line:
                        click.echo(line.rstrip("\n"))
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            click.echo("")
            return
    else:
        content = log_path.read_text(encoding="utf-8")
        all_lines = content.splitlines()
        for line in all_lines[-lines:]:
            click.echo(line)


# ── restart ──────────────────────────────────────────────────────────────


@main.command("restart")
@_serve_options  # type: ignore[untyped-decorator]
def restart(  # noqa: PLR0913
    pid_file: str,
    host: str,
    port: int,
    target: str,
    interval: int,
    stage: str,
    log_level: str,
    profile: str | None,
    data_dir: str,
    log_dir: str,
    no_browser: bool,
    foreground: bool = False,  # noqa: ARG001
) -> None:
    """Restart the News Sentry server (stop then start)."""
    pid_path = Path(pid_file).expanduser().resolve()

    # Step 1 — stop running server if alive.
    if _pid_alive(pid_path):
        pid = int(pid_path.read_text().strip())
        click.echo(f"Stopping server (PID: {pid})...")
        _kill_process(pid)

        # Wait up to 10 seconds for the old process to exit.
        waited = 0.0
        while _pid_alive(pid_path) and waited < 10:
            time.sleep(0.5)
            waited += 0.5
        if _pid_alive(pid_path):
            click.echo("Warning: Old process did not exit within 10s. Starting anyway.")
    else:
        click.echo("Server not running — starting fresh.")

    # Step 2 — launch new process in the background.
    data_path = Path(data_dir).expanduser().resolve()
    log_path_dir = Path(log_dir).expanduser().resolve()
    serve_args = [
        sys.executable,
        "-m",
        "news_sentry.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--target",
        target,
        "--interval",
        str(interval),
        "--stage",
        stage,
        "--log-level",
        log_level,
        "--data-dir",
        str(data_path),
        "--log-dir",
        str(log_path_dir),
        "--pid-file",
        str(pid_path),
        "--foreground",
    ]
    if profile:
        serve_args.extend(["--profile", profile])
    if no_browser:
        serve_args.append("--no-browser")

    click.echo(f"Starting server on http://{host}:{port} ...")
    subprocess.Popen(serve_args, start_new_session=True)  # noqa: S603 — args built from flags, not user input
    time.sleep(1)

    if _pid_alive(pid_path):
        click.echo(f"Server restarted (PID: {pid_path.read_text().strip()}).")
    else:
        click.echo("Server process spawned — check status or logs for details.")


# ── uninstall ────────────────────────────────────────────────────────────


@main.command("uninstall")
@click.option("--pid-file", default="~/.news-sentry/serve.pid", help="PID file path.")
@click.option("--purge", is_flag=True, default=False, help="Also remove data directory.")
def uninstall(pid_file: str, purge: bool) -> None:
    """Remove News Sentry OS service registration.

    Stops the running server (if any) and removes the service file.
    Use --purge to also delete the data directory (~/.news-sentry/data).
    """
    pid_path = Path(pid_file).expanduser().resolve()
    system = platform.system()

    # 1. Stop the server if running.
    if _pid_alive(pid_path):
        pid = int(pid_path.read_text().strip())
        click.echo(f"Stopping server (PID: {pid})...")
        _kill_process(pid)
        time.sleep(0.5)
        pid_path.unlink(missing_ok=True)
        click.echo("Server stopped.")

    # 2. Remove OS service registration.
    if system == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/com.news-sentry.plist"
        if plist_path.is_file():
            subprocess.run(  # noqa: S603
                ["launchctl", "unload", str(plist_path)],  # noqa: S607
                capture_output=True,
            )
            plist_path.unlink()
            click.echo(f"Removed: {plist_path}")
        else:
            click.echo("No LaunchAgent plist found.")
    elif system == "Linux":
        unit_path = Path.home() / ".config/systemd/user/news-sentry.service"
        if unit_path.is_file():
            subprocess.run(  # noqa: S603
                ["systemctl", "--user", "disable", "--now", "news-sentry.service"],  # noqa: S607
                capture_output=True,
            )
            unit_path.unlink()
            subprocess.run(  # noqa: S603
                ["systemctl", "--user", "daemon-reload"],  # noqa: S607
                capture_output=True,
            )
            click.echo(f"Removed: {unit_path}")
        else:
            click.echo("No systemd unit file found.")
    elif system == "Windows":
        subprocess.run(  # noqa: S603
            ["schtasks", "/Delete", "/TN", "NewsSentry", "/F"],  # noqa: S607
            capture_output=True,
        )
        launcher = Path.home() / ".news-sentry" / "launcher.ps1"
        launcher.unlink(missing_ok=True)
        click.echo("Scheduled Task 'NewsSentry' removed.")
    else:
        click.echo(f"Manual cleanup required for {system}.")

    # 3. Optionally purge data.
    if purge:
        data_dir = Path.home() / ".news-sentry"
        if data_dir.is_dir():
            import shutil

            shutil.rmtree(data_dir)
            click.echo(f"Purged data directory: {data_dir}")

    click.echo("Uninstall complete.")
