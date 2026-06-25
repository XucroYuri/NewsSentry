"""Global diagnostics handler — extracted from api_server.py create_app().

Provides the public ``/api/v1/diagnostics`` endpoint for observability.
Uses a factory pattern: the handler is created inside create_app() and
closure-captured helpers are passed once.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Response

import news_sentry.core._state as _st
from news_sentry.core.target_store_utils import _load_run_logs


def make_global_diagnostics(
    _static_build_hash: Callable[[], str],
    _git_commit_for_path: Callable[[Path], str],
    _collector_payload: Callable[[], dict[str, Any]],
    _filter_source_health_records: Callable[..., list[dict[str, Any]]],
    _load_memory_source_health_records: Callable[..., list[dict[str, Any]]],
) -> Callable[..., Any]:
    """创建 global_diagnostics handler — 注入闭包依赖。"""

    async def global_diagnostics(
        response: Response,
    ) -> dict[str, Any]:
        """全局可观测性诊断摘要（公开，聚合所有 target）。

        无需认证，汇总采集器状态、数据目录、最后采集、信源健康、
        事件总数等关键指标，用于快速定位"无数据"、"采集卡死"等问题。
        """
        response.headers["Cache-Control"] = "no-store"
        build = _static_build_hash()
        commit = _git_commit_for_path(Path(__file__))

        collector = _collector_payload()

        has_ai_key = bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("GROQ_API_KEY")
        )

        _data_dir = _st._data_dir
        data_exists = _data_dir.exists()
        target_dirs = (
            sorted([d.name for d in _data_dir.iterdir() if d.is_dir()]) if data_exists else []
        )

        healthy_sources = 0
        unhealthy_sources = 0
        if data_exists:
            for tid in target_dirs:
                memory_health = _filter_source_health_records(
                    tid,
                    _load_memory_source_health_records(tid),
                )
                if memory_health:
                    for item in memory_health:
                        if item.get("status") == "healthy":
                            healthy_sources += 1
                        else:
                            unhealthy_sources += 1
                    continue
                health_file = _data_dir / tid / "source_health.json"
                if health_file.exists():
                    try:
                        health_data = json.loads(health_file.read_text())
                        items = health_data if isinstance(health_data, list) else []
                        for item in items:
                            if item.get("healthy"):
                                healthy_sources += 1
                            else:
                                unhealthy_sources += 1
                    except Exception:  # noqa: S110
                        pass

        total_events: int = 0
        latest_collected_at: str | None = None
        _store = _st._store
        if _store is not None and _store._db is not None:
            try:
                async with _store._db.execute(
                    "SELECT MAX(collected_at), COUNT(*) FROM event_index"
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    latest_collected_at = row[0]
                    total_events = row[1] or 0
            except Exception:  # noqa: S110
                pass

        recent_runs: list[dict[str, Any]] = []
        if target_dirs:
            recent_runs = _load_run_logs(_data_dir, target_dirs[0], 5)

        return {
            "deploy": {
                "commit": commit[:12] if commit != "unknown" else commit,
                "build": build,
            },
            "collector": {
                "enabled": collector["enabled"],
                "running": collector["running"],
                "last_run_at": collector.get("last_run_at"),
                "next_run_at": collector.get("next_run_at"),
            },
            "ai_key_configured": has_ai_key,
            "data": {
                "directory": str(_data_dir),
                "target_count": len(target_dirs),
                "targets": target_dirs,
            },
            "source_health": {
                "healthy": healthy_sources,
                "unhealthy": unhealthy_sources,
                "total": healthy_sources + unhealthy_sources,
            },
            "events": {
                "total": total_events,
                "latest_collected_at": latest_collected_at,
            },
            "recent_runs": recent_runs[:5],
        }

    return global_diagnostics
