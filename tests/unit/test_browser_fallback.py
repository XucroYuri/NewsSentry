"""BrowserFallback 模块测试。"""
from news_sentry.skills.collect.browser_fallback import (
    BrowserFallback,
)


class TestBrowserFallback:
    def test_initial_layer_is_1(self):
        """初始活跃层为 Layer 1。"""
        bf = BrowserFallback(config={})
        assert bf.active_layer == 1

    def test_degrade_to_layer2_after_failures(self):
        """Layer 1 连续失败 2 次降级到 Layer 2。"""
        config = {"browser_fallback": {"degrade_to_layer2_after_failures": 2}}
        bf = BrowserFallback(config)
        bf.record_failure()
        assert bf.active_layer == 1  # 1 次失败不降级
        bf.record_failure()
        assert bf.active_layer == 2  # 2 次失败降级到 Layer 2

    def test_degrade_to_layer3_only_for_l1(self):
        """Layer 1+2 合计失败 5 次，仅对 L1 降级到 Layer 3。"""
        config = {
            "browser_fallback": {
                "degrade_to_layer2_after_failures": 2,
                "degrade_to_layer3_after_failures": 5,
            }
        }
        bf = BrowserFallback(config)
        for _ in range(5):
            bf.record_failure()
        assert bf.should_use_layer_3(tier="L1") is True
        assert bf.should_use_layer_3(tier="L2") is False  # 非 L1 不降级到 L3

    def test_success_resets_layer(self):
        """成功后恢复 Layer 1。"""
        bf = BrowserFallback(config={})
        for _ in range(2):
            bf.record_failure()
        assert bf.active_layer == 2
        bf.record_success()
        assert bf.active_layer == 2  # 仅成功 1 次仍为 Layer 2
        bf.record_success()
        assert bf.active_layer == 1       # 连续成功 2 次恢复到 Layer 1
