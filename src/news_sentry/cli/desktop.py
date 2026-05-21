"""News Sentry — desktop 命令：增强版原生桌面窗口。

提供:
  - 原生菜单（文件: 打开数据目录/日志/退出，帮助: 关于/版本）
  - confirm_close + 隐藏到系统托盘（pystray）
  - 服务器生命周期管理
  - 窗口配置持久化（大小、位置、端口）

使用:
  news-sentry desktop --port 8000

依赖:
  pip install 'news-sentry[desktop]'  # pywebview + pystray + Pillow
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import click

from news_sentry.cli import main

# ── 配置 ──────────────────────────────────────────────────

_DESKTOP_CONFIG_DIR = Path.home() / ".news-sentry"
_DESKTOP_CONFIG_PATH = _DESKTOP_CONFIG_DIR / "desktop.json"


def _load_desktop_config() -> dict[str, Any]:
    """加载桌面配置（窗口大小、位置、端口等）。"""
    if _DESKTOP_CONFIG_PATH.is_file():
        try:
            return json.loads(_DESKTOP_CONFIG_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_desktop_config(config: dict[str, Any]) -> None:
    """保存桌面配置。"""
    _DESKTOP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _DESKTOP_CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ── 服务器生命周期 ────────────────────────────────────────

_server_thread: threading.Thread | None = None
_stop_server = False


def _run_server(host: str, port: int) -> None:
    """在后台线程启动 uvicorn。"""
    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(
        "news_sentry.core.api_server:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )


def _start_server(host: str, port: int) -> threading.Thread:
    """启动服务器后台线程。"""
    global _server_thread
    thread = threading.Thread(
        target=_run_server,
        args=(host, port),
        daemon=True,
        name="news-sentry-uvicorn",
    )
    thread.start()
    _server_thread = thread
    return thread


# ── 托盘图标 ──────────────────────────────────────────────

_tray_icon: Any = None  # pystray.Icon


def _create_tray_menu(window: Any, port: int) -> Any:
    """创建系统托盘右键菜单。"""
    import pystray  # type: ignore[import-untyped]

    def _on_open(icon: object, item: object) -> None:  # noqa: ARG001
        window.show()
        window.restore()

    def _on_hide(icon: object, item: object) -> None:  # noqa: ARG001
        window.hide()

    def _on_quit(icon: object, item: object) -> None:  # noqa: ARG001
        icon.stop()  # type: ignore[attr-defined]
        window.destroy()
        _stop_tray()
        os._exit(0)

    return pystray.Menu(
        pystray.MenuItem("打开窗口", _on_open, default=True),
        pystray.MenuItem("隐藏窗口", _on_hide),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"服务: 127.0.0.1:{port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _on_quit),
    )


def _make_tray_image(color: tuple[int, int, int, int]) -> object:
    """生成托盘图标（PIL Image）。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


def _start_tray(window: Any, port: int) -> Any:
    """在后台线程启动系统托盘。"""
    import pystray

    icon = pystray.Icon(
        "news-sentry",
        _make_tray_image((59, 130, 246, 255)),  # blue-500
        "News Sentry — 运行中",
        _create_tray_menu(window, port),
    )

    def _run() -> None:
        global _tray_icon
        _tray_icon = icon
        icon.run()

    thread = threading.Thread(target=_run, daemon=True, name="news-sentry-tray")
    thread.start()
    return icon


def _stop_tray() -> None:
    """停止系统托盘。"""
    global _tray_icon
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception:  # noqa: S110
            pass
        _tray_icon = None


# ── 原生菜单 ──────────────────────────────────────────────


def _open_dir(path: str) -> None:
    """跨平台打开目录。"""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])  # noqa: S603, S607
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])  # noqa: S603, S607
    except Exception:  # noqa: S110
        pass


def _build_native_menu(data_dir: str, log_dir: str) -> list[Any]:
    """构建 pywebview 原生菜单。"""
    from webview.menu import Menu, MenuAction, MenuSeparator

    return [
        Menu(
            "文件",
            [
                MenuAction("打开数据目录", lambda: _open_dir(data_dir)),
                MenuAction("打开日志", lambda: _open_dir(log_dir)),
                MenuSeparator(),
                MenuAction("退出", lambda: _do_quit(None, data_dir)),
            ],
        ),
        Menu(
            "帮助",
            [
                MenuAction("关于 News Sentry", _show_about),
            ],
        ),
    ]


def _os_info() -> str:
    """返回跨平台 OS 描述字符串。"""
    system = platform.system()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if system == "Windows":
        return f"Windows {platform.release()}"
    # Linux — 尝试读取 /etc/os-release
    os_info = f"Linux {platform.release()}"
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                os_info = line.split("=", 1)[1].strip('"')
                break
    except (OSError, ValueError):
        pass
    return os_info


def _show_about() -> None:
    """显示关于对话框。"""
    from importlib.metadata import version as _pkg_version

    try:
        ver = _pkg_version("news-sentry")
    except Exception:
        ver = "unknown"

    import webview

    active = webview.active_window()
    if active is None:
        return
    webview.Window.create_confirmation_dialog(
        active,
        "关于 News Sentry",
        f"News Sentry v{ver}\n\n"
        "新闻智能监控平台\n\n"
        f"Python {platform.python_version()}\n"
        f"{_os_info()}\n"
        f"pywebview 6.x",
    )


def _do_quit(window: Any, data_dir: str) -> None:
    """退出应用：保存配置 → 停止服务 → 退出。"""
    # 保存当前窗口状态
    if window is not None:
        config = _load_desktop_config()
        config.update(
            {
                "window_width": window.width,
                "window_height": window.height,
                "window_x": window.x,
                "window_y": window.y,
            }
        )
        _save_desktop_config(config)

    _stop_tray()

    # pystray 后台线程可能导致 sys.exit 挂起，统一用 os._exit 强制退出
    os._exit(0)


# ── 主命令 ──────────────────────────────────────────────


@main.command("desktop")
@click.option("--port", default=8000, type=int, help="本地 API 服务器端口")
@click.option("--window-width", default=1280, type=int, help="桌面窗口宽度（px）")
@click.option("--window-height", default=800, type=int, help="桌面窗口高度（px）")
@click.option("--data-dir", default="~/.news-sentry/data", help="数据根目录")
@click.option("--log-dir", default="~/.news-sentry/logs", help="日志目录")
@click.option("--no-tray", is_flag=True, default=False, help="禁用系统托盘")
def desktop(
    port: int,
    window_width: int,
    window_height: int,
    data_dir: str,
    log_dir: str,
    no_tray: bool,
) -> None:
    """Launch native desktop window wrapping the API Server.

    自动启动本地 API 服务器并打开原生桌面窗口，
    提供原生菜单、系统托盘（可选）、配置持久化等桌面体验。

    需要安装桌面依赖：pip install 'news-sentry[desktop]'
    """
    # 1. 检查 pywebview
    try:
        import webview as wv
    except ImportError:
        click.echo(
            "Error: pywebview is not installed.\n"
            "Install it with:  pip install 'news-sentry[desktop]'",
            err=True,
        )
        sys.exit(1)

    # 2. 解析路径
    data_path = Path(data_dir).expanduser().resolve()
    log_path = Path(log_dir).expanduser().resolve()
    data_path.mkdir(parents=True, exist_ok=True)
    log_path.mkdir(parents=True, exist_ok=True)

    # 3. 设置环境变量
    os.environ["NEWSSENTRY_DATA_DIR"] = str(data_path)

    # 4. 加载已有配置
    config = _load_desktop_config()
    if not no_tray:
        window_width = int(config.get("window_width", window_width))
        window_height = int(config.get("window_height", window_height))
    port = int(config.get("port", port))

    # 5. 启动 API 服务器
    click.echo(f"Starting API server on 127.0.0.1:{port} ...")
    _start_server("127.0.0.1", port)
    time.sleep(0.5)

    # 6. 原生菜单
    menu = _build_native_menu(str(data_path), str(log_path))

    # 7. 创建桌面窗口
    window = wv.create_window(
        "News Sentry — 新闻情报监控",
        f"http://127.0.0.1:{port}",
        width=window_width,
        height=window_height,
        resizable=True,
        min_size=(800, 500),
        confirm_close=True,
        # macOS vibrancy — 毛玻璃效果
        vibrancy=True,
        # 自定义菜单
        menu=menu,
    )

    # 8. 系统托盘（可选）
    _tray_enabled = False
    if not no_tray:
        try:
            import pystray  # noqa: F401 — verify pystray is available

            _start_tray(window, port)
            _tray_enabled = True
            click.echo("System tray enabled (close to tray, right-click for menu)")
        except ImportError:
            pass

    # 9. 拦截窗口关闭事件
    if _tray_enabled:

        def _on_closing() -> None:
            """关闭窗口 → 隐藏到托盘。"""
            window.hide()  # type: ignore[union-attr]

        if window is not None:
            window.events.closing += _on_closing

    click.echo("")
    from importlib.metadata import version as _pkg_version

    try:
        ver = _pkg_version("news-sentry")
    except Exception:
        ver = "unknown"

    click.echo(f"  News Sentry v{ver} — 桌面模式")
    click.echo("  ─────────────────────────────")
    click.echo(f"  Server:   http://127.0.0.1:{port}")
    click.echo(f"  Data:     {data_path}")
    click.echo(f"  Logs:     {log_path}")
    click.echo(f"  Tray:     {'enabled' if _tray_enabled else 'disabled'}")
    click.echo("  ─────────────────────────────")
    click.echo('  Close window or click tray "退出" to quit.')
    click.echo("")

    # 10. 窗口关闭回调：保存配置
    def _on_window_closed() -> None:
        _save_desktop_config(
            {
                "window_width": window.width,  # type: ignore[union-attr]
                "window_height": window.height,  # type: ignore[union-attr]
                "port": port,
            }
        )

    if window is not None:
        try:
            window.events.closed += _on_window_closed
        except AttributeError:
            pass

    # 11. 启动 GUI 事件循环
    wv.start(
        menu=menu,
        private_mode=False,
    )
