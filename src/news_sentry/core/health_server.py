"""Phase 18: Health Server — lightweight HTTP /health endpoint.

Returns JSON with process status, memory/disk usage, and recent run stats.
Uses stdlib http.server — no external dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for /health endpoint."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = json.dumps(_collect_health(), ensure_ascii=False, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default stderr logging."""
        pass


def _collect_health() -> dict[str, Any]:
    """Collect health metrics from the current process."""
    now = datetime.now(UTC).isoformat()

    # Memory info
    mem_info: dict[str, Any] = {}
    try:
        usage = shutil.disk_usage("/")
        mem_info["disk_total_gb"] = round(usage.total / 1024**3, 1)
        mem_info["disk_used_gb"] = round(usage.used / 1024**3, 1)
        mem_info["disk_free_gb"] = round(usage.free / 1024**3, 1)
        mem_info["disk_pct"] = round(usage.used / usage.total * 100, 1)
    except OSError as exc:
        logger.warning("无法获取根目录磁盘使用情况: %s", exc)

    # Data directory
    data_dir = os.environ.get("NEWSSENTRY_DATA_DIR", "./data")
    data_path = Path(data_dir)
    data_info: dict[str, Any] = {"path": str(data_path.resolve()), "exists": data_path.exists()}
    if data_path.exists():
        try:
            du = shutil.disk_usage(data_path)
            data_info["disk_pct"] = round(du.used / du.total * 100, 1)
            data_info["disk_free_gb"] = round(du.free / 1024**3, 1)
        except OSError as exc:
            logger.warning("无法获取数据目录磁盘使用情况: %s", exc)

    # Recent run logs
    logs_dir = data_path / "logs"
    recent_runs: list[str] = []
    if logs_dir.exists():
        try:
            recent_runs = sorted(
                [p.name for p in logs_dir.glob("run-*.json")],
                reverse=True,
            )[:5]
        except OSError as exc:
            logger.warning("无法读取运行日志目录: %s", exc)

    # Environment indicators
    env_status: dict[str, bool] = {
        "feishu_configured": bool(os.environ.get("FEISHU_WEBHOOK_URL")),
        "smtp_configured": bool(os.environ.get("SMTP_HOST")),
        "telegram_configured": bool(
            os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
        ),
    }

    return {
        "status": "ok",
        "timestamp": now,
        "process": {
            "pid": os.getpid(),
            "data_dir": data_info,
        },
        "system": mem_info,
        "recent_runs": recent_runs,
        "integrations": env_status,
    }


def start_health_server(port: int = 8080) -> HTTPServer:
    """Start health HTTP server in a daemon thread.

    Returns the HTTPServer instance (for testing).
    """
    server = HTTPServer(("0.0.0.0", port), HealthHandler)  # noqa: S104
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop_health_server(server: HTTPServer) -> None:
    """Stop the health HTTP server."""
    server.shutdown()
