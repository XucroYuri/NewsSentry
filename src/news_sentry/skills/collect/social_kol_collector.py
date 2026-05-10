"""Implements: docs/spec/phase-6-sandbox-hardening-social-kol.md §3.8

SocialKOLCollector — KOL 社媒实验通道采集器（Phase 6 Stub）。
推特/知乎/微信趋势采集，所有产出标记 kol-experiment channel。
受 kol-experiment sandbox 策略约束，需 session_profile 治理。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from news_sentry.core.sandbox import SandboxEnforcer, SandboxViolationError
from news_sentry.core.tool_registry import ToolRegistry
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


class SocialKOLCollector:
    """通过 OpenCLI 工具采集 KOL 社媒内容（Phase 6 实验通道）。

    构造函数硬性检查 sandbox.policy.policy_id == "kol-experiment"，
    非 kol-experiment 沙箱下立即抛 SandboxViolationError。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        sandbox: SandboxEnforcer,
        kol_state: dict[str, Any],
    ) -> None:
        """初始化 KOL 社媒采集器。

        Args:
            registry: ToolRegistry 实例，用于工具调用。
            sandbox: SandboxEnforcer，policy_id 必须为 "kol-experiment"。
            kol_state: 从 kol-state.yaml 加载的 KOL 实体记录。

        Raises:
            SandboxViolationError: 非 kol-experiment 沙箱策略。
        """
        if sandbox.policy.policy_id != "kol-experiment":
            raise SandboxViolationError(
                f"SocialKOLCollector 要求 sandbox policy_id='kol-experiment'，"
                f"当前为 '{sandbox.policy.policy_id}'",
                {"required_policy": "kol-experiment", "actual": sandbox.policy.policy_id},
            )

        self._registry = registry
        self._sandbox = sandbox
        self._kol_state = kol_state

    # ── 采集方法（Phase 6 Stub） ──────────────────────────────

    def collect_twitter_trends(
        self, locale: str = "worldwide", context: str = "",
    ) -> list[NewsEvent]:
        """采集 Twitter 趋势（stub）。

        Args:
            locale: 趋势地区（如 "italy", "japan"）。
            context: 采集上下文标识。

        Returns:
            NewsEvent 列表，含 kol-experiment channel 标记。
        """
        collected_at = datetime.now(UTC).isoformat()
        event = NewsEvent(
            id=NewsEvent.make_id("kol", "twitter", f"trends/{locale}", collected_at),
            run_id=context or "kol-twitter",
            source_id="twitter",
            url=f"https://twitter.com/explore/tabs/trends?locale={locale}",
            title_original=f"Twitter Trends: {locale}",
            content_original="",
            language=Language.IT,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli",
                    "tool_ref": "opencli.twitter.trending",
                },
                "acquisition": {
                    "channel": "kol-experiment",
                    "locale": locale,
                },
            },
        )
        return [event]

    def collect_zhihu_hot(self, context: str = "") -> list[NewsEvent]:
        """采集知乎热榜（stub）。

        Args:
            context: 采集上下文标识。

        Returns:
            NewsEvent 列表，含 kol-experiment channel 标记。
        """
        collected_at = datetime.now(UTC).isoformat()
        event = NewsEvent(
            id=NewsEvent.make_id("kol", "zhihu", "hot", collected_at),
            run_id=context or "kol-zhihu",
            source_id="zhihu",
            url="https://www.zhihu.com/hot",
            title_original="知乎热榜",
            content_original="",
            language=Language.ZH,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli",
                    "tool_ref": "opencli.zhihu.hot",
                },
                "acquisition": {
                    "channel": "kol-experiment",
                },
            },
        )
        return [event]

    def collect_weixin_search(
        self, query: str, context: str = "",
    ) -> list[NewsEvent]:
        """采集微信搜一搜（stub，高风险，需 session_profile）。

        Args:
            query: 搜索关键词。
            context: 采集上下文标识。

        Returns:
            NewsEvent 列表，含 kol-experiment channel 标记。
        """
        collected_at = datetime.now(UTC).isoformat()
        event = NewsEvent(
            id=NewsEvent.make_id("kol", "weixin", f"search/{query}", collected_at),
            run_id=context or "kol-weixin",
            source_id="weixin",
            url=f"https://weixin.qq.com/search?q={query}",
            title_original=f"WeChat Search: {query}",
            content_original="",
            language=Language.ZH,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli",
                    "tool_ref": "opencli.weixin.search",
                },
                "acquisition": {
                    "channel": "kol-experiment",
                    "query": query,
                },
            },
        )
        return [event]
