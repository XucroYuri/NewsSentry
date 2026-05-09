"""Implements: docs/spec/phase-3-kernel-mvp.md §3.8

Memory — manages known IDs, source health, cursors, KOL state.
Storage: {target}/memory/ directory (YAML files).
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class Memory:
    """跨运行状态持久化：已知ID去重、源健康追踪、游标、Provider统计。

    所有 YAML 读写受 threading.Lock 保护，文件写入使用原子 rename（.tmp → .yaml）。
    """

    _KNOWN_IDS_FILE = "known_item_ids.yaml"
    _SOURCE_HEALTH_FILE = "source_health.yaml"
    _CURSORS_FILE = "cursors.yaml"
    _PROVIDER_STATS_FILE = "provider_stats.yaml"
    _DEFAULT_TTL_DAYS = 30

    def __init__(self, memory_dir: Path) -> None:
        """初始化 Memory，从 memory_dir 加载所有 YAML 状态文件。

        Args:
            memory_dir: memory/ 目录路径，不存在则自动创建。
        """
        self._memory_dir = Path(memory_dir)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._known_ids: dict[str, str] = (
            self._read_yaml(self._KNOWN_IDS_FILE) or {}
        )
        self._source_health: dict[str, dict[str, Any]] = (
            self._read_yaml(self._SOURCE_HEALTH_FILE) or {}
        )
        self._cursors: dict[str, str] = (
            self._read_yaml(self._CURSORS_FILE) or {}
        )
        self._provider_stats: dict[str, dict[str, Any]] = (
            self._read_yaml(self._PROVIDER_STATS_FILE) or {}
        )

    # ------------------------------------------------------------------
    # YAML I/O helpers
    # ------------------------------------------------------------------

    def _file_path(self, filename: str) -> Path:
        return self._memory_dir / filename

    def _read_yaml(self, filename: str) -> dict[str, Any] | None:
        """读取 YAML 文件，不存在则返回 None。"""
        path = self._file_path(filename)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    def _write_yaml(self, filename: str, data: dict[str, Any]) -> None:
        """原子写入：先写 .tmp 文件，再 rename 到目标。

        调用方必须持有 self._lock。
        """
        target = self._file_path(filename)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp.rename(target)

    # ------------------------------------------------------------------
    # Known IDs（去重）
    # ------------------------------------------------------------------

    def is_known(self, event_id: str) -> bool:
        """检查 event_id 是否已处理过，O(1) 字典查找。"""
        with self._lock:
            return event_id in self._known_ids

    def mark_known(self, event_id: str) -> None:
        """将 event_id 标记为已知，记录首次出现时间戳。

        采集阶段获取到事件后立即调用，用于后续去重。
        """
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._known_ids[event_id] = now
            self._write_yaml(self._KNOWN_IDS_FILE, self._known_ids)

    def prune_old_ids(self, ttl_days: int = _DEFAULT_TTL_DAYS) -> int:
        """清理超过 ttl_days 天的已知 ID 条目，返回清理数量。"""
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        with self._lock:
            stale = [
                eid
                for eid, ts in self._known_ids.items()
                if datetime.fromisoformat(ts) < cutoff
            ]
            for eid in stale:
                del self._known_ids[eid]
            if stale:
                self._write_yaml(self._KNOWN_IDS_FILE, self._known_ids)
            return len(stale)

    # ------------------------------------------------------------------
    # Source Health（源健康）
    # ------------------------------------------------------------------

    def get_source_health(self, source_id: str) -> dict[str, Any]:
        """获取指定源的运行状况快照。

        Returns:
            dict with keys: last_success_at, last_failure_at, success_count,
            failure_count, last_error, success_rate。不存在则返回空 dict。
        """
        with self._lock:
            entry = self._source_health.get(source_id)
            return entry.copy() if entry else {}

    def update_source_health(
        self, source_id: str, success: bool, error_msg: str | None = None
    ) -> None:
        """更新源的健康状态：记录成功/失败、重新计算成功率。

        Args:
            source_id: 来源标识。
            success: 本次拉取是否成功。
            error_msg: 失败时的错误信息。
        """
        now = datetime.now(UTC).isoformat()
        with self._lock:
            entry = self._source_health.get(source_id)
            if entry is None:
                entry = {
                    "last_success_at": None,
                    "last_failure_at": None,
                    "success_count": 0,
                    "failure_count": 0,
                    "last_error": None,
                    "success_rate": 1.0,
                }
            if success:
                entry["last_success_at"] = now
                entry["success_count"] += 1
            else:
                entry["last_failure_at"] = now
                entry["failure_count"] += 1
                entry["last_error"] = error_msg
            total = entry["success_count"] + entry["failure_count"]
            entry["success_rate"] = round(entry["success_count"] / total, 3) if total > 0 else 1.0
            self._source_health[source_id] = entry
            self._write_yaml(self._SOURCE_HEALTH_FILE, self._source_health)

    # ------------------------------------------------------------------
    # Cursors（拉取游标）
    # ------------------------------------------------------------------

    def get_cursor(self, source_id: str) -> str | None:
        """获取源的拉取游标（如 RSS 的 ETag/Last-Modified）。"""
        with self._lock:
            return self._cursors.get(source_id)

    def set_cursor(self, source_id: str, cursor: str) -> None:
        """更新源的拉取游标，用于增量拉取。"""
        with self._lock:
            self._cursors[source_id] = cursor
            self._write_yaml(self._CURSORS_FILE, self._cursors)

    # ------------------------------------------------------------------
    # Provider Stats（AI 调用统计）
    # ------------------------------------------------------------------

    def get_provider_stats(self, provider_id: str) -> dict[str, Any]:
        """获取 AI provider 的调用统计。

        Returns:
            dict with keys: total_calls, successful_calls, failed_calls,
            total_tokens。不存在则返回空 dict。
        """
        with self._lock:
            entry = self._provider_stats.get(provider_id)
            return entry.copy() if entry else {}

    def update_provider_stats(
        self, provider_id: str, tokens_used: int, success: bool
    ) -> None:
        """更新 provider 调用统计：记录调用次数、token 用量、成功/失败。

        Args:
            provider_id: AI 提供商标识。
            tokens_used: 本次调用使用的 token 数。
            success: 调用是否成功。
        """
        with self._lock:
            entry = self._provider_stats.get(provider_id)
            if entry is None:
                entry = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "total_tokens": 0,
                }
            entry["total_calls"] += 1
            entry["total_tokens"] += tokens_used
            if success:
                entry["successful_calls"] += 1
            else:
                entry["failed_calls"] += 1
            self._provider_stats[provider_id] = entry
            self._write_yaml(self._PROVIDER_STATS_FILE, self._provider_stats)
