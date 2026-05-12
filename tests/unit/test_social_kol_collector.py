"""SocialKOLCollector 升级后测试 — 从 stub 到真实 Bridge 采集。"""
from unittest.mock import ANY, MagicMock

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.skills.collect.social_kol_collector import SocialKOLCollector


class MockSandbox:
    policy = MagicMock(policy_id="kol-experiment")


def make_account(handle="@test", tier="L1", monitor_mode="active",
                 url="https://x.com/test", fetch_max_per_run=10):
    return {
        "handle": handle, "tier": tier, "monitor_mode": monitor_mode,
        "url": url, "fetch_max_per_run": fetch_max_per_run,
        "display_name": "Test Account", "category": "test",
    }


def make_success_result(tool_id="opencli.navigate", stdout="") -> ToolRunResult:
    """构造成功的 ToolRunResult。"""
    return ToolRunResult(
        tool_id=tool_id, run_id="test-run",
        success=True, exit_code=0, stdout=stdout,
    )


def make_failure_result(tool_id="opencli.navigate") -> ToolRunResult:
    """构造失败的 ToolRunResult。"""
    return ToolRunResult(
        tool_id=tool_id, run_id="test-run",
        success=False, exit_code=1,
        error={"type": "timeout", "message": "timed out"},
    )


class TestLoadAccounts:
    def test_load_from_config(self):
        """从配置 dict 加载账号列表。"""
        config = {
            "platform": "twitter",
            "accounts": [make_account(), make_account(handle="@test2")],
            "session_profile_ref": "config/session-profiles/italy/twitter.yaml",
        }
        collector = SocialKOLCollector(MagicMock(), MockSandbox(), {}, config)
        assert len(collector.accounts) == 2

    def test_filter_by_tier(self):
        """按 tier 过滤账号。"""
        config = {
            "platform": "twitter",
            "accounts": [
                make_account("@l1a", tier="L1"),
                make_account("@l1b", tier="L1"),
                make_account("@l2a", tier="L2"),
                make_account("@l3a", tier="L3"),
            ],
        }
        collector = SocialKOLCollector(MagicMock(), MockSandbox(), {}, config)
        l1_accounts = collector.get_accounts_by_tier("L1")
        assert len(l1_accounts) == 2

    def test_filter_by_monitor_mode(self):
        """按 monitor_mode 过滤。"""
        config = {
            "platform": "twitter",
            "accounts": [
                make_account("@active1", monitor_mode="active"),
                make_account("@active2", monitor_mode="active"),
                make_account("@semi1", monitor_mode="semi_active"),
            ],
        }
        collector = SocialKOLCollector(MagicMock(), MockSandbox(), {}, config)
        active = collector.get_accounts_by_mode("active")
        assert len(active) == 2
        semi = collector.get_accounts_by_mode("semi_active")
        assert len(semi) == 1


class TestFetchAccountPage:
    """_fetch_account_page 通过 ToolRegistry.execute 调用 OpenCLI Bridge。"""

    def test_calls_registry_navigate(self):
        """应调用 registry.execute('opencli.navigate', ...) 导航到账号页面。"""
        mock_registry = MagicMock()
        mock_registry.execute.return_value = make_success_result(
            stdout="Navigated to https://x.com/test"
        )
        config = {"platform": "twitter", "accounts": [make_account()]}
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        collector._fetch_account_page(account, "run-001")

        mock_registry.execute.assert_any_call(
            "opencli.navigate",
            "social_kol_collector",
            {"url": "https://x.com/test"},
            "run-001",
            collector._sandbox,
        )

    def test_calls_registry_get_text_after_navigate(self):
        """导航成功后应调用 opencli.get_text 提取页面文本。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(
                tool_id="opencli.get_text",
                stdout="Post 1: Breaking news\nPost 2: Analysis",
            ),
        ]
        config = {"platform": "twitter", "accounts": [make_account()]}
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        collector._fetch_account_page(account, "run-001")

        mock_registry.execute.assert_any_call(
            "opencli.get_text",
            "social_kol_collector",
            {"selector": "[data-testid='tweetText']", "output_path": ANY},
            "run-001",
            collector._sandbox,
        )

    def test_returns_news_events_on_success(self):
        """execute 成功时应返回填充了 content_original 的 NewsEvent 列表。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(
                tool_id="opencli.get_text",
                stdout="Breaking news from Italy",
            ),
        ]
        config = {"platform": "twitter", "accounts": [make_account()]}
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        events = collector._fetch_account_page(account, "run-001")

        assert len(events) >= 1
        assert events[0].content_original != ""
        assert "Breaking news from Italy" in events[0].content_original
        assert events[0].source_id == "twitter/@test"

    def test_returns_empty_list_on_navigate_failure(self):
        """navigate 失败时应返回空列表（不抛异常）。"""
        mock_registry = MagicMock()
        mock_registry.execute.return_value = make_failure_result(
            tool_id="opencli.navigate"
        )
        config = {"platform": "twitter", "accounts": [make_account()]}
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        events = collector._fetch_account_page(account, "run-001")

        assert events == []

    def test_returns_empty_list_on_get_text_failure(self):
        """navigate 成功但 get_text 失败时应返回空列表。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_failure_result(tool_id="opencli.get_text"),
        ]
        config = {"platform": "twitter", "accounts": [make_account()]}
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        events = collector._fetch_account_page(account, "run-001")

        assert events == []

    def test_respects_fetch_max_per_run(self):
        """返回的 NewsEvent 数量不应超过 account.fetch_max_per_run。"""
        mock_registry = MagicMock()
        # Simulate many posts in stdout
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(
                tool_id="opencli.get_text",
                stdout="\n---\n".join([f"Post {i}" for i in range(20)]),
            ),
        ]
        config = {
            "platform": "twitter",
            "accounts": [make_account(fetch_max_per_run=3)],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)
        account = collector.accounts[0]

        events = collector._fetch_account_page(account, "run-001")

        assert len(events) <= 3


class TestFetchTimeline:
    """_fetch_timeline 通过 ToolRegistry 浏览首页 Feed 时间线。"""

    def test_calls_registry_navigate_to_home(self):
        """应调用 registry.execute 导航到平台首页 Feed。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(tool_id="opencli.get_text", stdout="Feed content"),
        ]
        config = {
            "platform": "twitter",
            "accounts": [make_account(monitor_mode="semi_active")],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)

        collector._fetch_timeline("run-001")

        # Should navigate to the platform's home/feed URL
        navigate_call = mock_registry.execute.call_args_list[0]
        assert navigate_call[0][0] == "opencli.navigate"
        assert "x.com/home" in navigate_call[0][2]["url"]

    def test_returns_news_events_with_timeline_content(self):
        """成功时应返回含 Feed 内容的 NewsEvent 列表。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(
                tool_id="opencli.get_text",
                stdout="Timeline post 1\nTimeline post 2",
            ),
        ]
        config = {
            "platform": "twitter",
            "accounts": [make_account(monitor_mode="semi_active")],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)

        events = collector._fetch_timeline("run-001")

        assert len(events) >= 1
        assert events[0].content_original != ""

    def test_returns_empty_list_on_failure(self):
        """execute 失败时应返回空列表。"""
        mock_registry = MagicMock()
        mock_registry.execute.return_value = make_failure_result(
            tool_id="opencli.navigate"
        )
        config = {
            "platform": "twitter",
            "accounts": [make_account(monitor_mode="semi_active")],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)

        events = collector._fetch_timeline("run-001")

        assert events == []


class TestCollectActiveIntegration:
    """collect_active 端到端集成 — 多账号 Bridge 采集。"""

    def test_collects_from_all_active_accounts(self):
        """应遍历所有 active 模式账号并调用 Bridge 采集。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(tool_id="opencli.get_text", stdout="Post A"),
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(tool_id="opencli.get_text", stdout="Post B"),
        ]
        config = {
            "platform": "twitter",
            "accounts": [
                make_account("@a", monitor_mode="active"),
                make_account("@b", monitor_mode="active"),
            ],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)

        events = collector.collect_active("run-001")

        assert len(events) >= 2

    def test_skips_failed_accounts_continues_others(self):
        """某个账号采集失败时不中断，继续处理后续账号。"""
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = [
            # First account fails on navigate
            make_failure_result(tool_id="opencli.navigate"),
            # Second account succeeds
            make_success_result(tool_id="opencli.navigate"),
            make_success_result(tool_id="opencli.get_text", stdout="Post from B"),
        ]
        config = {
            "platform": "twitter",
            "accounts": [
                make_account("@bad", monitor_mode="active"),
                make_account("@good", monitor_mode="active"),
            ],
        }
        collector = SocialKOLCollector(mock_registry, MockSandbox(), {}, config)

        events = collector.collect_active("run-001")

        assert len(events) >= 1
