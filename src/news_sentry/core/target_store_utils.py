"""Target store helpers — shared between api_server and collector config utils.

Extracted from api_server.py to break circular dependency with collector_config_utils.py.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from news_sentry.core._state import _data_dir, _target_stores
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.event_io_utils import (
    _event_from_index_row,
    _indexed_file_path_is_visible_in_stage,
    _load_indexed_event_frontmatter,
    _merge_index_metadata,
)

logger = logging.getLogger(__name__)

VISIBLE_INDEX_QUERY_BATCH_SIZE = 1000


def _load_run_logs(
    data_dir: Path,
    target_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """从 logs/ 目录读取最近的运行日志。"""
    log_dir = data_dir / target_id / "logs"
    if not log_dir.is_dir():
        return []
    json_files = sorted(log_dir.glob("*.json"), reverse=True)
    runs: list[dict[str, Any]] = []
    for f in json_files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            phases = data.get("phases", [])
            total_ms = sum(p.get("duration_ms", 0) for p in phases)
            summary = data.get("summary", {})
            runs.append(
                {
                    "run_id": data.get("run_id", f.stem),
                    "target_id": data.get("target_id", target_id),
                    "started_at": data.get("started_at", ""),
                    "ended_at": data.get("ended_at", ""),
                    "duration_ms": total_ms,
                    "events_collected": summary.get("total_events_collected", 0),
                    "errors_count": data.get("errors_count", 0),
                    "status": "completed" if data.get("ended_at") else "running",
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def _latest_run_log_summary(data_dir: Path) -> dict[str, Any] | None:
    """从所有 target 日志中找最近一次真实运行，用于服务重启后的状态恢复。"""
    if not data_dir.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for target_dir in sorted(data_dir.iterdir()):
        if not target_dir.is_dir():
            continue
        candidates.extend(_load_run_logs(data_dir, target_dir.name, 1))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("ended_at") or item.get("started_at") or "")


def _target_db_path(target_id: str) -> Path:
    """目标 state.db 路径: {data_dir}/{target_id}/state.db"""
    return _data_dir / target_id / "state.db"


async def _get_target_store(target_id: str) -> AsyncStore | None:
    """获取 target 对应的 AsyncStore（优先使用 pipeline 的 state.db）。

    缓存已打开的 store，避免重复初始化。
    """
    db_path = _target_db_path(target_id)
    if target_id in _target_stores:
        cached = _target_stores[target_id]
        if cached.db_path == db_path:
            return cached
        try:
            await cached.close()
        except Exception:  # noqa: S110
            pass
        _target_stores.pop(target_id, None)

    if db_path.exists():
        store = AsyncStore(db_path)
        await store.initialize()
        _target_stores[target_id] = store
        logger.debug("Opened target store: %s", db_path)
        return store

    return None


def _event_matches_date(event: dict[str, Any], date: str | None) -> bool:
    if date is None:
        return True
    return (event.get("published_at") or "").startswith(date)


def _event_matches_search(event: dict[str, Any], search: str | None) -> bool:
    if search is None:
        return True
    keyword = search.lower()
    return keyword in (event.get("title_original") or "").lower()


def _visible_index_event_from_row(
    data_dir: Path,
    target_id: str,
    stage: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    file_path = row.get("file_path")
    if not _indexed_file_path_is_visible_in_stage(
        data_dir,
        target_id,
        stage,
        file_path,
    ):
        return None
    event = _load_indexed_event_frontmatter(data_dir, target_id, stage, row)
    if event is None:
        event = _event_from_index_row(row)
    return _merge_index_metadata(event, row)


async def _visible_index_events_page(
    store: Any,
    data_dir: Path,
    target_id: str,
    *,
    stage: str,
    page: int,
    page_size: int,
    date: str | None = None,
    search: str | None = None,
    source_id: str | None = None,
    classification_l0: str | None = None,
    min_score: int | None = None,
    sentiment: str | None = None,
    entity_name: str | None = None,
    topic_tag: str | None = None,
    exact_total: bool = True,
) -> dict[str, Any]:
    """读取可公开展示的 index 事件，再分页，避免 stale 行占据页面。"""
    start = (page - 1) * page_size
    page_events: list[dict[str, Any]]

    if not exact_total and date is None and search is None:
        offset = start
        index_total = 0
        page_events = []

        while len(page_events) < page_size:
            result = await store.query_events_paginated(
                target_id=target_id,
                stage=stage,
                limit=page_size,
                offset=offset,
                source_id=source_id,
                classification_l0=classification_l0,
                min_score=min_score,
                sentiment=sentiment,
                entity_name=entity_name,
                topic_tag=topic_tag,
            )
            index_total = result["total"]
            rows = result["rows"]
            if not rows:
                break

            for row in rows:
                event = _visible_index_event_from_row(data_dir, target_id, stage, row)
                if event is not None:
                    page_events.append(event)
                    if len(page_events) >= page_size:
                        break

            offset += len(rows)
            if offset >= index_total:
                break

        return {
            "index_total": index_total,
            "total": index_total,
            "events": page_events,
        }

    end = start + page_size
    offset = 0
    index_total = 0
    visible_total = 0
    page_events = []

    while True:
        result = await store.query_events_paginated(
            target_id=target_id,
            stage=stage,
            limit=VISIBLE_INDEX_QUERY_BATCH_SIZE,
            offset=offset,
            source_id=source_id,
            classification_l0=classification_l0,
            min_score=min_score,
            sentiment=sentiment,
            entity_name=entity_name,
            topic_tag=topic_tag,
        )
        index_total = result["total"]
        rows = result["rows"]
        if not rows:
            break

        for row in rows:
            event = _visible_index_event_from_row(data_dir, target_id, stage, row)
            if event is None:
                continue
            if not _event_matches_date(event, date):
                continue
            if not _event_matches_search(event, search):
                continue
            if start <= visible_total < end:
                page_events.append(event)
            visible_total += 1

        offset += len(rows)
        if offset >= index_total:
            break

    return {
        "index_total": index_total,
        "total": visible_total,
        "events": page_events,
    }
