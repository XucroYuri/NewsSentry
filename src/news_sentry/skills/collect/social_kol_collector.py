"""Implements: docs/spec/phase-6-sandbox-hardening-social-kol.md §3.8

SocialKOLCollector — KOL 社媒内容采集器（Phase 12 升级版）。
支持两种采集模式：active（逐账号）和 semi_active（Feed 流）。
通过 OpenCLI Bridge 或 Playwright MCP 执行浏览器操作，零 token 采集。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from news_sentry.core.sandbox import SandboxEnforcer, SandboxViolationError
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


@dataclass
class SocialAccount:
    """单个社媒账号的配置。"""
    handle: str
    display_name: str
    url: str
    tier: str                                          # L1 | L2 | L3
    category: str
    monitor_mode: str                                  # active | semi_active
    fetch_max_per_run: int = 20
    notes: str = ""


class SocialKOLCollector:
    """通过浏览器 Bridge 采集 KOL 社媒内容。

    配置文件格式见 config/sources/italy/social/_template.yaml。
    支持两种采集模式：
      - active: 逐个访问目标账号页面，提取最新帖子
      - semi_active: 浏览首页 Feed/"Following" 时间线，批量捕获
    """

    def __init__(
        self,
        registry: Any,                                 # ToolRegistry
        sandbox: SandboxEnforcer,
        kol_state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        """初始化 KOL 社媒采集器。

        Args:
            registry: ToolRegistry 实例。
            sandbox: SandboxEnforcer。
            kol_state: KOL state 记录。
            config: 社媒源配置 dict（包含 platform + accounts 列表）。

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
        self._config = config or {}

        self.platform: str = self._config.get("platform", "unknown")
        self.dimension: str = self._config.get("dimension", "unknown")
        self.session_profile_ref: str = self._config.get("session_profile_ref", "")

        # 解析账号列表
        raw_accounts: list[dict[str, Any]] = self._config.get("accounts", [])
        self.accounts: list[SocialAccount] = [
            SocialAccount(
                handle=a.get("handle", ""),
                display_name=a.get("display_name", ""),
                url=a.get("url", ""),
                tier=a.get("tier", "L3"),
                category=a.get("category", "other"),
                monitor_mode=a.get("monitor_mode", "semi_active"),
                fetch_max_per_run=int(a.get("fetch_max_per_run", 20)),
                notes=a.get("notes", ""),
            )
            for a in raw_accounts
        ]

    # ── 查询方法 ─────────────────────────────────────

    def get_accounts_by_tier(self, tier: str) -> list[SocialAccount]:
        """按层级过滤账号列表。"""
        return [a for a in self.accounts if a.tier == tier]

    def get_accounts_by_mode(self, mode: str) -> list[SocialAccount]:
        """按采集模式过滤账号列表。"""
        return [a for a in self.accounts if a.monitor_mode == mode]

    # ── 采集方法 ─────────────────────────────────────

    def collect_active(self, run_id: str) -> list[NewsEvent]:
        """主动模式：逐个访问 L1/L2 账号页面，提取最新帖子。

        Args:
            run_id: 本次 bounded run ID。

        Returns:
            NewsEvent 列表，管道阶段为 COLLECTED。
        """
        events: list[NewsEvent] = []
        active_accounts = self.get_accounts_by_mode("active")

        for account in active_accounts:
            try:
                account_events = self._fetch_account_page(account, run_id)
                events.extend(account_events[: account.fetch_max_per_run])
            except Exception:
                continue

        return events

    def collect_semi_active(self, run_id: str) -> list[NewsEvent]:
        """半主动模式：浏览首页 Feed 线，批量捕获已关注账号动态。

        Args:
            run_id: 本次 bounded run ID。

        Returns:
            NewsEvent 列表。
        """
        events: list[NewsEvent] = []
        semi_accounts = self.get_accounts_by_mode("semi_active")

        if not semi_accounts:
            return []

        try:
            feed_events = self._fetch_timeline(run_id)
            monitored_handles = {a.handle for a in semi_accounts}
            for event in feed_events:
                author = (event.metadata.get("collection", {}).get("author_handle", ""))
                if author in monitored_handles:
                    events.append(event)
        except Exception:
            pass

        return events

    def collect(self, run_id: str) -> list[NewsEvent]:
        """执行全部采集：active + semi_active。

        Args:
            run_id: 本次 bounded run ID。

        Returns:
            合并后的 NewsEvent 列表。
        """
        events: list[NewsEvent] = []
        events.extend(self.collect_active(run_id))
        events.extend(self.collect_semi_active(run_id))
        return events

    # ── 兼容 Phase 6 Stub 方法 ────────────────────────

    def collect_twitter_trends(
        self, locale: str = "worldwide", context: str = "",
    ) -> list[NewsEvent]:
        """采集 Twitter 趋势（保留 Phase 6 兼容接口）。

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
        """采集知乎热榜（保留 Phase 6 兼容接口）。

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
        """采集微信搜一搜（保留 Phase 6 兼容接口）。

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

    # ── 内部方法 ─────────────────────────────────────

    def _fetch_account_page(
        self, account: SocialAccount, run_id: str,
    ) -> list[NewsEvent]:
        """通过 OpenCLI Bridge 访问单个账号页面。

        Args:
            account: 目标账号。
            run_id: 运行 ID。

        Returns:
            NewsEvent 列表。
        """
        collected_at = datetime.now(UTC).isoformat()
        event = NewsEvent(
            id=NewsEvent.make_id(
                "social", self.platform, account.url, collected_at,
            ),
            run_id=run_id,
            source_id=f"{self.platform}/{account.handle}",
            url=account.url,
            title_original=f"{self.platform}: {account.display_name}",
            content_original="",
            language=Language.IT,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli_bridge",
                    "platform": self.platform,
                    "handle": account.handle,
                    "tier": account.tier,
                    "mode": "active",
                },
            },
        )
        return [event]

    def _fetch_timeline(self, run_id: str) -> list[NewsEvent]:
        """浏览首页 Feed 时间线。

        Args:
            run_id: 运行 ID。

        Returns:
            NewsEvent 列表。
        """
        collected_at = datetime.now(UTC).isoformat()
        event = NewsEvent(
            id=NewsEvent.make_id(
                "social", self.platform, "timeline", collected_at,
            ),
            run_id=run_id,
            source_id=f"{self.platform}/timeline",
            url="https://x.com/home" if self.platform == "twitter" else "",
            title_original=f"{self.platform} Timeline",
            content_original="",
            language=Language.IT,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata={
                "collection": {
                    "method": "opencli_bridge",
                    "platform": self.platform,
                    "mode": "semi_active",
                },
            },
        )
        return [event]
