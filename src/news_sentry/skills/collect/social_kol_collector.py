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
from news_sentry.skills.collect.browser_fallback import BrowserFallback


@dataclass
class SocialAccount:
    """单个社媒账号的配置。"""

    handle: str
    display_name: str
    url: str
    tier: str  # L1 | L2 | L3
    category: str
    monitor_mode: str  # active | semi_active
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
        registry: Any,  # noqa: ANN401 — ToolRegistry import would cause circular import
        sandbox: SandboxEnforcer,
        kol_state: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        fallback: BrowserFallback | None = None,
    ) -> None:
        """初始化 KOL 社媒采集器。

        Args:
            registry: ToolRegistry 实例。
            sandbox: SandboxEnforcer。
            kol_state: KOL state 记录。
            config: 社媒源配置 dict（包含 platform + accounts 列表）。
            fallback: BrowserFallback 降级管理器，未提供时用空配置创建。

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
        self._fallback = fallback or BrowserFallback(config or {})

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
            except Exception:  # noqa: S112 — skip failed account, continue with remaining
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
                author = event.metadata.get("collection", {}).get("author_handle", "")
                if author in monitored_handles:
                    events.append(event)
        except Exception:  # noqa: S110 — timeline fetch failure is non-fatal, return empty list
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
        self,
        locale: str = "worldwide",
        context: str = "",
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
        self,
        query: str,
        context: str = "",
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

    # ── 内部常量 ─────────────────────────────────────

    _BRIDGE_CALLER_ID: str = "social_kol_collector"
    _CONTENT_SELECTOR: str = "[data-testid='tweetText']"
    _POST_SEPARATOR: str = "\n---\n"

    # Layer 2 (Playwright MCP) tool IDs — 与 Layer 1 对应的 MCP 版本
    _L2_NAVIGATE_TOOL: str = "opencli.mcp.navigate"
    _L2_GET_TEXT_TOOL: str = "opencli.mcp.get_text"

    _PLATFORM_HOME_URL: dict[str, str] = {
        "twitter": "https://x.com/home",
        "facebook": "https://www.facebook.com/",
        "instagram": "https://www.instagram.com/",
        "linkedin": "https://www.linkedin.com/feed/",
        "youtube": "https://www.youtube.com/",
        "tiktok": "https://www.tiktok.com/",
        "reddit": "https://www.reddit.com/",
        "weibo": "https://weibo.com/",
    }

    # ── 内部方法 ─────────────────────────────────────

    def _execute_bridge_tool(
        self,
        tool_id: str,
        validated_args: dict[str, Any],
        run_id: str,
    ) -> Any:  # noqa: ANN401 — ToolRunResult is defined in adapters.tools.base
        """封装 registry.execute 调用，统一注入 binding_id 和 sandbox。"""
        return self._registry.execute(
            tool_id,
            self._BRIDGE_CALLER_ID,
            validated_args,
            run_id,
            self._sandbox,
        )

    def _parse_posts(self, stdout: str, max_posts: int) -> list[str]:
        """从 stdout 文本中解析帖子列表。

        Args:
            stdout: 采集工具返回的原始文本。
            max_posts: 上限截断数。

        Returns:
            去空后的帖子文本列表（不超 max_posts）。
        """
        if not stdout.strip():
            return []
        posts = [p.strip() for p in stdout.split(self._POST_SEPARATOR) if p.strip()]
        return posts[:max_posts]

    def _make_event(
        self,
        source_id: str,
        url: str,
        title: str,
        content: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> NewsEvent:
        """构造采集阶段的 NewsEvent。"""
        collected_at = datetime.now(UTC).isoformat()
        return NewsEvent(
            id=NewsEvent.make_id("social", self.platform, url, collected_at),
            run_id=run_id,
            source_id=source_id,
            url=url,
            title_original=title,
            content_original=content,
            language=Language.IT,
            published_at=collected_at,
            collected_at=collected_at,
            pipeline_stage=PipelineStage.COLLECTED,
            metadata=metadata or {},
        )

    def _should_use_layer_3(self, account: SocialAccount) -> bool:
        """检查是否应对该账号使用 Layer 3 (Computer Use)。"""
        return self._fallback.should_use_layer_3(account.tier)

    def _try_layer(self, account: SocialAccount, run_id: str) -> list[NewsEvent] | None:
        """按当前 active_layer 执行采集，返回 NewsEvent 列表或 None。

        Returns:
            NewsEvent 列表表示成功；None 表示该层采集失败。
        """
        if self._fallback.active_layer == 1:
            return self._try_opencli_bridge(account, run_id)
        elif self._fallback.active_layer == 2:
            return self._try_mcp_bridge(account, run_id)
        elif self._should_use_layer_3(account):
            return self._try_layer_3(account, run_id)
        return None

    def _try_opencli_bridge(
        self,
        account: SocialAccount,
        run_id: str,
    ) -> list[NewsEvent] | None:
        """Layer 1: OpenCLI Bridge 采集。"""
        nav_result = self._execute_bridge_tool(
            "opencli.navigate",
            {"url": account.url},
            run_id,
        )
        if not nav_result.success:
            return None

        extract_result = self._execute_bridge_tool(
            "opencli.get_text",
            {
                "selector": self._CONTENT_SELECTOR,
                "output_path": f"./data/tmp/{run_id}_account.txt",
            },
            run_id,
        )
        if not extract_result.success:
            return None

        posts = self._parse_posts(extract_result.stdout, account.fetch_max_per_run)
        return self._build_events(account, posts, run_id, "opencli_bridge")

    def _try_mcp_bridge(
        self,
        account: SocialAccount,
        run_id: str,
    ) -> list[NewsEvent] | None:
        """Layer 2: Playwright MCP 采集。"""
        nav_result = self._execute_bridge_tool(
            self._L2_NAVIGATE_TOOL,
            {"url": account.url},
            run_id,
        )
        if not nav_result.success:
            return None

        extract_result = self._execute_bridge_tool(
            self._L2_GET_TEXT_TOOL,
            {
                "selector": self._CONTENT_SELECTOR,
                "output_path": f"./data/tmp/{run_id}_account_l2.txt",
            },
            run_id,
        )
        if not extract_result.success:
            return None

        posts = self._parse_posts(extract_result.stdout, account.fetch_max_per_run)
        return self._build_events(account, posts, run_id, "playwright_mcp")

    def _try_layer_3(
        self,
        account: SocialAccount,
        run_id: str,
    ) -> list[NewsEvent] | None:
        """Layer 3: Computer Use — 经由 ProviderRouter，消耗 token。

        当前返回 None，完整实现需在 Agent 环境可用时接入。
        """
        return None

    def _build_events(
        self,
        account: SocialAccount,
        posts: list[str],
        run_id: str,
        method: str,
    ) -> list[NewsEvent]:
        """将帖子文本列表构造为 NewsEvent 列表。"""
        base_metadata = {
            "collection": {
                "method": method,
                "platform": self.platform,
                "handle": account.handle,
                "tier": account.tier,
                "mode": "active",
                "layer": self._fallback.active_layer,
            },
        }
        events: list[NewsEvent] = []
        for i, post_text in enumerate(posts):
            event = self._make_event(
                source_id=f"{self.platform}/{account.handle}",
                url=account.url,
                title=f"{self.platform}: {account.display_name} #{i + 1}",
                content=post_text,
                run_id=run_id,
                metadata=base_metadata,
            )
            events.append(event)
        return events

    def _fetch_account_page(
        self,
        account: SocialAccount,
        run_id: str,
    ) -> list[NewsEvent]:
        """通过降级链采集单个账号页面的最新帖子。

        流程：
          1. 按 _fallback.active_layer 选择当前活跃层采集
          2. 成功 → record_success() → 返回结果
          3. 失败 → record_failure() → 如果降级则重试新层
          4. 三层均失败 → 返回空列表

        Args:
            account: 目标账号。
            run_id: 运行 ID。

        Returns:
            NewsEvent 列表（最多 fetch_max_per_run 条）。
        """
        result = self._try_layer(account, run_id)
        if result is not None:
            self._fallback.record_success()
            return result

        self._fallback.record_failure()
        # record_failure 可能触发降级，重试新层
        retry_result = self._try_layer(account, run_id)
        if retry_result is not None:
            self._fallback.record_success()
            return retry_result

        return []

    def _fetch_timeline(self, run_id: str) -> list[NewsEvent]:
        """浏览首页 Feed 时间线。

        Args:
            run_id: 运行 ID。

        Returns:
            NewsEvent 列表。
        """
        home_url = self._PLATFORM_HOME_URL.get(
            self.platform,
            f"https://{self.platform}.com/",
        )

        # Step 1: 导航到首页 Feed
        nav_result = self._execute_bridge_tool(
            "opencli.navigate",
            {"url": home_url},
            run_id,
        )
        if not nav_result.success:
            return []

        # Step 2: 提取时间线文本
        extract_result = self._execute_bridge_tool(
            "opencli.get_text",
            {
                "selector": self._CONTENT_SELECTOR,
                "output_path": f"./data/tmp/{run_id}_timeline.txt",
            },
            run_id,
        )
        if not extract_result.success:
            return []

        # Step 3: 解析帖子列表
        posts = self._parse_posts(extract_result.stdout, max_posts=50)
        timeline_metadata = {
            "collection": {
                "method": "opencli_bridge",
                "platform": self.platform,
                "mode": "semi_active",
            },
        }

        events: list[NewsEvent] = []
        for i, post_text in enumerate(posts):
            event = self._make_event(
                source_id=f"{self.platform}/timeline",
                url=home_url,
                title=f"{self.platform} Timeline #{i + 1}",
                content=post_text,
                run_id=run_id,
                metadata=timeline_metadata,
            )
            events.append(event)

        return events
