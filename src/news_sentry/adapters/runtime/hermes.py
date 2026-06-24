"""Implements: docs/spec/phase-2-runtime-carrier-alignment.md §3.2

HermesAdapter — 薄适配器，将 bounded_run() 接入 Hermes 运行时 (ADR-0006)。
不依赖 Hermes 内部 API，仅委托本地 kernel 执行。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from news_sentry.adapters.runtime.base import RuntimeHostAdapter
from news_sentry.core.run import ConfigError, bounded_run


@RuntimeHostAdapter.register
class HermesAdapter:
    """Hermes Agent 运行时适配器。委托 bounded_run() 执行 pipeline 阶段。"""

    runtime_id = "hermes"

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化适配器，存储运行时配置。

        Args:
            config: 运行时配置字典，至少包含 project_root 路径。
        """
        self._config = config

    def trigger_run(self, target_id: str, stage: str, run_id: str | None = None) -> str:
        """触发一次 bounded run，返回 run_id。

        Args:
            target_id: 目标标识符（如 "my-target"）。
            stage: pipeline 阶段。
            run_id: 可选运行 ID，不提供则自动生成。

        Returns:
            运行 ID 字符串。

        Raises:
            ValueError: 配置加载失败时。
        """
        try:
            ctx = bounded_run(
                target_id,
                stage,
                run_id=run_id,
                config_dir=str(self._config.get("project_root", Path.cwd())),
            )
            return ctx.run_id
        except ConfigError as e:
            raise ValueError(str(e)) from e
        except Exception:
            # 若异常发生在 run_id 生成前，手动生成一个用于追踪
            if run_id is None:
                ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                run_id = f"{target_id}_{ts}_{uuid.uuid4().hex[:8]}"
            return run_id

    def get_run_status(self, run_id: str) -> dict[str, str]:
        """查询运行状态。

        通过检查 data/{target_id}/logs/{run_id}.json 日志文件判断状态。
        target_id 从 run_id 中解析。

        Args:
            run_id: 运行 ID。

        Returns:
            含 status / run_id / target_id 的字典。
        """
        target_id = self._parse_target_id(run_id)
        project_root = Path(self._config.get("project_root", Path.cwd()))
        log_file = project_root / "data" / target_id / "logs" / f"{run_id}.json"
        heartbeat_file = project_root / "data" / target_id / "logs" / ".heartbeat-hermes.json"

        if log_file.is_file():
            data = json.loads(log_file.read_text(encoding="utf-8"))
            if data.get("ended_at"):
                return {"status": "done", "run_id": run_id, "target_id": target_id}
            return {"status": "running", "run_id": run_id, "target_id": target_id}

        if heartbeat_file.is_file():
            hb = json.loads(heartbeat_file.read_text(encoding="utf-8"))
            if hb.get("status") == "running":
                return {"status": "running", "run_id": run_id, "target_id": target_id}

        return {"status": "failed", "run_id": run_id, "target_id": target_id}

    def list_skills(self) -> list[str]:
        """列出已注册的技能 ID。

        Returns:
            技能 ID 列表：["collect", "filter", "judge", "output"]。
        """
        return ["collect", "filter", "judge", "output"]

    @staticmethod
    def _parse_target_id(run_id: str) -> str:
        """从 run_id 中恢复 target_id。

        run_id 格式：{target_id}_{YYYYmmddTHHMMSSZ}_{hash8}
        其中 target_id 可能含下划线。
        """
        m = re.match(r"^(.+?)_\d{8}T\d{6}Z?(?:_.*)?$", run_id)
        if m:
            return m.group(1)
        return run_id
