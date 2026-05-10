"""Implements: docs/spec/phase-3-kernel-mvp.md §3.7

RunLog — 每次 bounded run 的结构化审计日志。
输出: logs/{run_id}.json
覆盖率: core/run_log.py（本文件，2026-05-09）
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunLog:
    """每次 bounded run 的审计日志，内存缓冲，write() 时一次性序列化写入 JSON。"""

    def __init__(
        self,
        log_dir: Path,
        run_id: str,
        target_id: str | None = None,
        profile_id: str = "local-workstation",
        output_root: str | None = None,
    ) -> None:
        """
        log_dir: logs/ 目录路径
        run_id: 本次运行的唯一标识
        target_id: 当前监控目标 ID。未传入时兼容旧 run_id 前缀推断。
        profile_id: 当前 bounded run 使用的 deployment profile。
        output_root: 可观测的数据根目录，项目内路径应使用 portable 形式。
        """
        self.log_dir = log_dir
        self.run_id = run_id
        self.target_id = target_id or self._parse_target_id_from_run_id(run_id)
        self.profile_id = profile_id
        self.output_root = output_root
        self.started_at = datetime.now(UTC).isoformat()
        self._phases: dict[str, dict[str, Any]] = {}
        self._written: bool = False
        self._output_path: Path | None = None

    # ------------------------------------------------------------------
    # 阶段生命周期
    # ------------------------------------------------------------------

    def log_phase_start(self, stage: str) -> None:
        """记录阶段开始"""
        phase = self._get_or_create_phase(stage)
        phase["started_at"] = datetime.now(UTC).isoformat()

    def log_phase_end(self, stage: str, items_count: int, duration_ms: float) -> None:
        """记录阶段结束（含处理数量和耗时）"""
        phase = self._get_or_create_phase(stage)
        phase["ended_at"] = datetime.now(UTC).isoformat()
        phase["items_count"] = items_count
        phase["duration_ms"] = duration_ms

    # ------------------------------------------------------------------
    # 事件与错误记录
    # ------------------------------------------------------------------

    def log_event(self, stage: str, event_id: str, action: str) -> None:
        """记录单个事件的处理动作（如 collected / filtered_in / filtered_out）"""
        phase = self._get_or_create_phase(stage)
        phase["_events"].append({"event_id": event_id, "action": action})

    def log_error(self, stage: str, error: str, event_id: str | None = None) -> None:
        """记录错误"""
        phase = self._get_or_create_phase(stage)
        err_entry: dict[str, str] = {"message": error}
        if event_id is not None:
            err_entry["event_id"] = event_id
        phase["errors"].append(err_entry)

    @property
    def errors_count(self) -> int:
        """返回当前运行日志中已记录的错误总数。"""
        return sum(len(phase["errors"]) for phase in self._phases.values())

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def write(self) -> Path:
        """将完整的运行日志写入 JSON 文件，返回文件路径。多次调用幂等，只写第一次。"""
        if self._written and self._output_path is not None:
            return self._output_path
        self._written = True

        ended_at = datetime.now(UTC).isoformat()

        phases_list = []
        for stage in self._phases:
            p = self._phases[stage]
            phases_list.append({
                "stage": p["stage"],
                "started_at": p["started_at"],
                "ended_at": p["ended_at"],
                "duration_ms": p["duration_ms"],
                "items_count": p["items_count"],
                "errors_count": len(p["errors"]),
                "errors": p["errors"],
            })

        summary = self._compute_summary()
        errors = self._flatten_errors()

        output = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "target_id": self.target_id,
            "profile_id": self.profile_id,
            "output_root": self.output_root,
            "phases": phases_list,
            "errors_count": len(errors),
            "errors": errors,
            "summary": summary,
        }

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._output_path = self.log_dir / f"{self.run_id}.json"
        self._output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return self._output_path

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_or_create_phase(self, stage: str) -> dict[str, Any]:
        """获取或创建阶段内部缓存"""
        if stage not in self._phases:
            self._phases[stage] = {
                "stage": stage,
                "started_at": None,
                "ended_at": None,
                "duration_ms": None,
                "items_count": 0,
                "errors": [],
                "_events": [],  # 内部追踪，不写入文件
            }
        return self._phases[stage]

    def _compute_summary(self) -> dict[str, Any]:
        """从内部事件追踪聚合摘要统计"""
        total_collected = 0
        total_filtered_in = 0
        total_filtered_out = 0
        total_errors = 0

        for phase in self._phases.values():
            total_errors += len(phase["errors"])
            for ev in phase.get("_events", []):
                action = ev["action"]
                if action == "collected":
                    total_collected += 1
                elif action == "filtered_in":
                    total_filtered_in += 1
                elif action == "filtered_out":
                    total_filtered_out += 1

        return {
            "total_events_collected": total_collected,
            "total_events_filtered_in": total_filtered_in,
            "total_events_filtered_out": total_filtered_out,
            "total_errors": total_errors,
        }

    def _flatten_errors(self) -> list[dict[str, str]]:
        """聚合所有 phase errors，便于自动化只解析 RunLog 顶层。"""
        errors: list[dict[str, str]] = []
        for stage, phase in self._phases.items():
            for err in phase["errors"]:
                entry = {"scope": stage, "stage": stage, **err}
                if stage == "collect" and "event_id" in entry:
                    entry["source_id"] = entry["event_id"]
                errors.append(entry)
        return errors

    @staticmethod
    def _parse_target_id_from_run_id(run_id: str) -> str:
        """从 run_id 中恢复 target_id。

        run_id 格式可为以下之一：
        - {target_id}_{YYYYmmddTHHMMSSZ}_{hash8}（正式 runs）
        - {target_id}_{YYYYmmddTHHMMSS}（简短测试 runs）
        其中 target_id 可能包含下划线（如 eu_china），
        通过匹配时间戳模式 ``_\\d{8}T\\d{6}Z?`` 来定位 target_id 结束位置。
        """
        m = re.match(r"^(.+?)_\d{8}T\d{6}Z?(?:_.*)?$", run_id)
        if m:
            return m.group(1)
        return run_id
