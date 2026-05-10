"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.4

OpenCLICollector — collects news events via OpenCLI tool execution.
Input: SourceChannel config (type=opencli). Output: list[NewsEvent] at stage=collected.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.ratelimit import RateLimiter
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


class OpenCLICollector:
    """通过 OpenCLI 工具调用采集新闻事件。

    从 SourceChannel config 读取 tool_ref + validated_args，
    调用 OpenCLIToolAdapter.execute()，将 stdout JSON 解析为 NewsEvent 列表。

    SourceChannel config 预期字段:
        type: opencli
        tool_ref: opencli.fetch (或其它 toolmanifest 中的 tool_id)
        validated_args: {url, output_path, ...}
        source_id: str
        target_id: str
    """

    def __init__(
        self,
        config: dict[str, Any],
        tool_adapter: OpenCLIToolAdapter,
        sandbox_enforcer: Any = None,  # noqa: ANN401
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """初始化 OpenCLI 采集器。

        Args:
            config: SourceChannel 配置 dict。
            tool_adapter: 已初始化（已加载 manifest）的 OpenCLIToolAdapter。
            sandbox_enforcer: 沙箱执行器（预留，当前由 adapter 内部使用）。
        """
        self._config = config
        self._adapter = tool_adapter
        self._sandbox = sandbox_enforcer
        self._rate_limiter = rate_limiter or RateLimiter()
        self._source_id: str = config.get("source_id", "opencli-source")
        self._target_id: str = config.get("target_id", "unknown")
        self._tool_ref: str = config.get("tool_ref", "opencli.fetch")
        self._validated_args: dict[str, Any] = dict(config.get("validated_args", {}))
        # 注册当前源的速率限制间隔
        interval = float(config.get("fetch_interval_seconds", 5.0))
        self._rate_limiter.set_interval(self._source_id, interval)

    def collect(self, run_id: str) -> list[NewsEvent]:
        """执行 OpenCLI 工具调用，解析结果为 NewsEvent 列表。

        Args:
            run_id: 本次运行标识。

        Returns:
            解析出的 NewsEvent 列表，pipeline_stage=COLLECTED。
            工具不可用或沙箱拦截时返回空列表。

        Raises:
            RuntimeError: 工具执行失败（非预期错误）时抛出。
        """
        # 按源速率限制：等待最小间隔后再执行工具
        self._rate_limiter.wait_if_needed(self._source_id)

        if not self._tool_ref:
            return []

        result = self._adapter.execute(self._tool_ref, self._validated_args, run_id)

        if not result.success:
            # 注意：exit code 66 (result_empty) 经 _map_exit_code 映射后返回 None（非错误），
            # 此时 result.success=True 但 stdout 为空，_parse_output 会正确返回 []。
            # opencli 未安装、沙箱拦截、认证要求 — 返回空列表（预期行为）
            allowed_types = ("opencli_not_installed", "sandbox_blocked", "auth_required")
            if result.error and result.error.get("type") in allowed_types:
                return []
            raise RuntimeError(
                f"OpenCLI tool '{self._tool_ref}' failed: "
                f"{result.error.get('message', result.stderr) if result.error else result.stderr}"
            )

        # 解析 stdout JSON → NewsEvent 列表
        return self._parse_output(result.stdout, run_id)

    def _parse_output(self, stdout: str, run_id: str) -> list[NewsEvent]:
        """将工具 stdout 解析为 NewsEvent 列表。

        支持两种格式:
        1. JSON 数组: [{"title": ..., "url": ..., ...}, ...]
        2. JSON 对象含 items 字段: {"items": [...]}

        Args:
            stdout: 工具标准输出字符串。
            run_id: 本次运行标识。

        Returns:
            NewsEvent 列表。
        """
        if not stdout or not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        # 统一为列表
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "items" in data:
            items = data.get("items", [])
        else:
            items = [data] if data else []

        collected_at = datetime.now(UTC).isoformat()
        events: list[NewsEvent] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                title = str(item.get("title", "") or item.get("title_original", ""))
                url = str(item.get("url", "") or item.get("link", ""))
                content = str(
                    item.get("content", "")
                    or item.get("summary", "")
                    or item.get("description", "")
                )
                published_at = str(
                    item.get("published_at", "")
                    or item.get("date", "")
                    or collected_at
                )
                source_id = str(item.get("source_id", self._source_id))

                if not title and not url:
                    continue

                event_id = NewsEvent.make_id(self._target_id, source_id, url, published_at)

                event = NewsEvent(
                    id=event_id,
                    run_id=run_id,
                    source_id=source_id,
                    url=url,
                    title_original=title,
                    content_original=content,
                    language=self._detect_language(item),
                    published_at=published_at,
                    collected_at=collected_at,
                    pipeline_stage=PipelineStage.COLLECTED,
                    metadata={
                        "collection": {
                            "method": "opencli",
                            "tool_ref": self._tool_ref,
                        }
                    },
                )
                events.append(event)
            except Exception:  # noqa: S112
                continue

        return events

    @staticmethod
    def _detect_language(item: dict[str, Any]) -> Language:
        """从原始条目推测语言。"""
        lang_hint = str(item.get("language", "") or item.get("lang", "")).lower()
        if lang_hint in ("it", "italian", "ita"):
            return Language.IT
        if lang_hint in ("en", "english", "eng"):
            return Language.EN
        return Language.IT  # 默认意大利语
