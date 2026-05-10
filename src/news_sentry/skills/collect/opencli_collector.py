"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.3

OpenCLICollector — wraps OpenCLI tool calls to collect web page content.
Uses ToolManifest entries from config/toolmanifest/opencli-baseline.yaml (ADR-0011).
Translates OpenCLI tool output into NewsEvent objects at pipeline_stage=collected.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


class OpenCLICollector:
    """通过 OpenCLI 工具采集网页内容，产出 NewsEvent。"""

    def __init__(
        self,
        config: dict[str, Any],
        opencli_adapter: OpenCLIToolAdapter,
        sandbox_enforcer: Any = None,  # noqa: ANN401 — 由 adapter 内部持有，此处兼容 run.py 调用
    ) -> None:
        """初始化 OpenCLI 采集器。

        Args:
            config: SourceChannel 配置 dict。必须包含:
                - source_id: str
                - tool_ref: str（如 "opencli.fetch"）
                - validated_args: dict（如 {"url": "...", "output_path": "..."}）
            opencli_adapter: 已初始化的 OpenCLIToolAdapter 实例。
        """
        self._config = config
        self._adapter = opencli_adapter
        self._source_id: str = config["source_id"]
        self._tool_ref: str = config.get("tool_ref", "") or ""
        self._args: dict[str, Any] = config.get("validated_args", {}) or {}

    def collect(self, run_id: str) -> list[NewsEvent]:
        """执行 OpenCLI 工具调用并解析结果为 NewsEvent 列表。

        Args:
            run_id: 本次 bounded run ID。

        Returns:
            NewsEvent 列表，pipeline_stage=COLLECTED。
            工具失败时返回空列表。
        """
        if not self._tool_ref:
            return []

        result = self._adapter.execute(self._tool_ref, self._args, run_id)

        if not result.success:
            return []

        # 尝试将 stdout 解析为 JSON 事件数组
        events = self._parse_output(result.stdout, run_id)
        return events

    def _parse_output(self, stdout: str, run_id: str) -> list[NewsEvent]:
        """从 stdout 解析 NewsEvent 列表。

        支持格式:
          - JSON 数组: [{"title": "...", "url": "...", ...}, ...]
          - JSON 对象: {"title": "...", ...} (单条)
          - 纯文本: 当 JSON 解析失败时，生成一个 content_original 事件

        Args:
            stdout: OpenCLI 工具的标准输出。
            run_id: 本次 bounded run ID。

        Returns:
            解析出的 NewsEvent 列表。
        """
        collected_at = datetime.now(UTC).isoformat()
        stdout = stdout.strip()
        if not stdout:
            return []

        # 尝试 JSON
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                return [
                    event
                    for item in parsed
                    if isinstance(item, dict)
                    for event in [self._dict_to_event(item, run_id, collected_at)]
                    if event.title_original or event.url
                ]
            if isinstance(parsed, dict):
                return [self._dict_to_event(parsed, run_id, collected_at)]
        except (json.JSONDecodeError, TypeError):
            pass

        # fallback: 纯文本作为 content_original
        event = NewsEvent(
            id=NewsEvent.make_id("opencli", self._source_id, "opencli_output", collected_at),
            run_id=run_id,
            source_id=self._source_id,
            url=self._args.get("url", ""),
            title_original=f"OpenCLI output: {self._tool_ref}",
            content_original=stdout[:50_000],
            language=Language.IT,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli",
                    "tool_ref": self._tool_ref,
                }
            },
        )
        return [event]

    @staticmethod
    def _dict_to_event(
        item: dict[str, Any], run_id: str, collected_at: str, target_id: str = "unknown"
    ) -> NewsEvent:
        """将 JSON dict 转换为 NewsEvent。"""
        url = str(item.get("url", item.get("link", "")))
        title = str(item.get("title", item.get("title_original", "")))
        content = str(item.get("content", item.get("content_original", item.get("body", ""))))
        source_id = str(item.get("source_id", "opencli"))
        published = str(item.get("published_at", item.get("date", collected_at)))

        return NewsEvent(
            id=NewsEvent.make_id(target_id, source_id, url, published),
            run_id=run_id,
            source_id=source_id,
            url=url,
            title_original=title,
            content_original=content[:50_000],
            language=Language.IT,
            published_at=published,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli",
                    "tool_ref": item.get("tool_ref", ""),
                }
            },
        )
