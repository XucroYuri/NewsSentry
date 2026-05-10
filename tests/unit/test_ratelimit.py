"""RateLimiter 模块测试。

覆盖：基本等待、间隔未到时无需等待、抖动范围、多源独立追踪、默认间隔。
"""
from __future__ import annotations

from unittest import mock

from news_sentry.core.ratelimit import RateLimiter


class TestRateLimiterBasic:
    """基本功能测试。"""

    def test_first_call_does_not_wait(self):
        """首次调用不应等待。"""
        limiter = RateLimiter()
        with mock.patch("time.sleep") as mock_sleep:
            waited = limiter.wait_if_needed("source-1")
            mock_sleep.assert_not_called()
        assert waited == 0.0

    def test_no_wait_when_interval_elapsed(self):
        """上次抓取距今超过间隔时不应等待。"""
        limiter = RateLimiter()
        limiter.set_interval("source-1", 0.1)
        # 模拟上次抓取在 monotonic=0.0
        limiter._last_fetch["source-1"] = 0.0

        # 当前时间 monotonic=1.0，已过 1.0 秒 > 0.1 秒间隔
        with mock.patch("time.monotonic", side_effect=[1.0, 1.0]):
            with mock.patch("time.sleep") as mock_sleep:
                waited = limiter.wait_if_needed("source-1")
                mock_sleep.assert_not_called()
                assert waited == 0.0

    def test_wait_when_interval_not_elapsed(self):
        """间隔未到时应等待。"""
        limiter = RateLimiter()
        limiter.set_interval("source-1", 1.0)
        limiter._last_fetch["source-1"] = 0.0

        # 仅过 0.1 秒，需要等待约 0.9 秒（含抖动）
        with mock.patch("time.monotonic", side_effect=[0.1, 0.1, 1.0, 1.0]):
            with mock.patch("time.sleep") as mock_sleep:
                waited = limiter.wait_if_needed("source-1")
                mock_sleep.assert_called_once()
                assert waited >= 0.0

    def test_reset_clears_all_state(self):
        """reset 应清除所有追踪状态。"""
        limiter = RateLimiter()
        limiter.set_interval("src", 100.0)
        limiter._last_fetch["src"] = 0.0

        limiter.reset()
        # reset 后首次调用不等待
        with mock.patch("time.sleep") as mock_sleep:
            waited = limiter.wait_if_needed("src")
            mock_sleep.assert_not_called()
        assert waited == 0.0

    def test_default_interval_when_not_set(self):
        """未设置间隔时使用默认值 5.0 秒。"""
        limiter = RateLimiter(default_interval_seconds=0.1)
        limiter._last_fetch["src"] = 0.0

        # 时间仅过 0.01 秒，应等待
        with mock.patch("time.monotonic", side_effect=[0.01, 0.01, 0.11, 0.11]):
            with mock.patch("time.sleep") as mock_sleep:
                limiter.wait_if_needed("src")
                mock_sleep.assert_called_once()


class TestJitter:
    """抖动范围测试。"""

    def test_jitter_within_20_percent(self):
        """抖动应在基准间隔的 ±20% 范围内。"""
        limiter = RateLimiter()
        interval = 5.0
        limiter.set_interval("src", interval)

        sleep_values: list[float] = []
        for _ in range(100):
            with mock.patch("time.monotonic", side_effect=[0.001, 0.001, 5.0, 5.0]):
                with mock.patch("time.sleep") as mock_sleep:
                    limiter._last_fetch["src"] = 0.0
                    limiter.wait_if_needed("src")
                    if mock_sleep.called:
                        sleep_arg = mock_sleep.call_args[0][0]
                        sleep_values.append(sleep_arg)

        assert len(sleep_values) > 0
        # jitter ±20%: 5.0 * 0.8 - 0.001 = 3.999, 5.0 * 1.2 - 0.001 = 5.999
        for v in sleep_values:
            assert 3.9 <= v <= 6.1, f"sleep value {v} outside jitter range"

    def test_jitter_variation(self):
        """多次调用应产生不同的抖动值（非固定延迟）。"""
        limiter = RateLimiter()
        limiter.set_interval("src", 5.0)

        sleep_values: list[float] = []
        for _ in range(50):
            with mock.patch("time.monotonic", side_effect=[0.001, 0.001, 5.0, 5.0]):
                with mock.patch("time.sleep") as mock_sleep:
                    limiter._last_fetch["src"] = 0.0
                    limiter.wait_if_needed("src")
                    if mock_sleep.called:
                        sleep_values.append(mock_sleep.call_args[0][0])

        unique = {round(v, 3) for v in sleep_values}
        assert len(unique) > 1, f"jitter produced identical values: {unique}"


class TestMultipleSources:
    """多源独立追踪测试。"""

    def test_independent_tracking(self):
        """不同 source_id 应独立追踪，互不影响。"""
        limiter = RateLimiter()
        limiter.set_interval("src-a", 1.0)
        limiter.set_interval("src-b", 1.0)

        # src-a 首次调用
        with mock.patch("time.sleep") as mock_sleep:
            waited_a = limiter.wait_if_needed("src-a")
            mock_sleep.assert_not_called()
        assert waited_a == 0.0

        # src-b 首次调用（不应受 src-a 影响）
        with mock.patch("time.sleep") as mock_sleep:
            waited_b = limiter.wait_if_needed("src-b")
            mock_sleep.assert_not_called()
        assert waited_b == 0.0

        # 手动设置上次抓取时间为 0.0，确保两者状态一致
        limiter._last_fetch["src-a"] = 0.0
        limiter._last_fetch["src-b"] = 0.0

        # src-a 再次立即调用应等待
        with mock.patch("time.monotonic", side_effect=[0.1, 0.1, 1.0, 1.0]):
            with mock.patch("time.sleep") as mock_sleep:
                limiter.wait_if_needed("src-a")
                mock_sleep.assert_called_once()

        # src-b 再次立即调用也应等待（独立追踪）
        with mock.patch("time.monotonic", side_effect=[0.15, 0.15, 1.0, 1.0]):
            with mock.patch("time.sleep") as mock_sleep:
                limiter.wait_if_needed("src-b")
                mock_sleep.assert_called_once()

    def test_different_intervals_per_source(self):
        """不同源可以配置不同的间隔。"""
        limiter = RateLimiter()
        limiter.set_interval("fast", 0.5)
        limiter.set_interval("slow", 5.0)
        limiter._last_fetch["fast"] = 0.0
        limiter._last_fetch["slow"] = 0.0

        # fast: 0.1 秒后调用（0.1 < 0.5 * 0.8 = 0.4，需要等待）
        with mock.patch("time.monotonic", side_effect=[0.1, 0.1, 0.5, 0.5]):
            with mock.patch("time.sleep") as mock_sleep:
                limiter.wait_if_needed("fast")
                mock_sleep.assert_called_once()

        # slow: 0.1 秒后调用（0.1 < 5.0 * 0.8 = 4.0，需要等待更久）
        with mock.patch("time.monotonic", side_effect=[0.1, 0.1, 5.0, 5.0]):
            with mock.patch("time.sleep") as mock_sleep:
                limiter.wait_if_needed("slow")
                mock_sleep.assert_called_once()


class TestConstructor:
    """构造函数测试。"""

    def test_custom_default_interval(self):
        """可以指定自定义默认间隔。"""
        limiter = RateLimiter(default_interval_seconds=10.0)
        assert limiter._default_interval == 10.0
