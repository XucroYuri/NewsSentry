"""News Sentry — desktop 命令：pywebview 原生桌面窗口启动器。

使用方式：
  news-sentry desktop --port 8000 --window-width 1280 --window-height 800

依赖：
  pip install 'news-sentry[desktop]'  # 安装 pywebview
"""

from __future__ import annotations

import sys
import threading

import click

from news_sentry.cli import main


def _run_server(host: str, port: int) -> None:
    """在后台线程启动 uvicorn 服务器。"""
    import uvicorn

    uvicorn.run(
        "news_sentry.core.api_server:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )


@main.command("desktop")
@click.option("--port", default=8000, type=int, help="本地 API 服务器端口")
@click.option("--window-width", default=1280, type=int, help="桌面窗口宽度（px）")
@click.option("--window-height", default=800, type=int, help="桌面窗口高度（px）")
def desktop(port: int, window_width: int, window_height: int) -> None:
    """Launch native desktop window wrapping the API Server (pywebview).

    自动启动本地 API 服务器并打开原生桌面窗口，
    提供接近原生应用的体验（独立窗口、系统菜单栏等）。

    需要安装 pywebview：pip install 'news-sentry[desktop]'
    """
    try:
        import webview as wv  # type: ignore[import-not-found]
    except ImportError:
        click.echo(
            "Error: pywebview is not installed.\n"
            "Install it with:  pip install 'news-sentry[desktop]'",
            err=True,
        )
        sys.exit(1)

    # 在后台线程启动 uvicorn 服务器
    server_thread = threading.Thread(
        target=_run_server,
        args=("127.0.0.1", port),
        daemon=True,
        name="news-sentry-uvicorn",
    )
    server_thread.start()

    click.echo(f"Starting desktop window → http://127.0.0.1:{port}")
    click.echo("Close the window to stop the server.")

    wv.create_window(
        "News Sentry — 新闻情报监控",
        f"http://127.0.0.1:{port}",
        width=window_width,
        height=window_height,
    )
    wv.start()
