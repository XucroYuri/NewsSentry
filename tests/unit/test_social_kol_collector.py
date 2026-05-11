"""SocialKOLCollector 升级后测试 — 从 stub 到真实 Bridge 采集。"""
import pytest
from unittest.mock import MagicMock, patch
from news_sentry.skills.collect.social_kol_collector import SocialKOLCollector


class MockSandbox:
    policy = MagicMock(policy_id="kol-experiment")


def make_account(handle="@test", tier="L1", monitor_mode="active",
                 url="https://x.com/test"):
    return {
        "handle": handle, "tier": tier, "monitor_mode": monitor_mode,
        "url": url, "fetch_max_per_run": 10,
        "display_name": "Test Account", "category": "test",
    }


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
