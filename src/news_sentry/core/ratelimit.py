"""按源速率限制 — 避免在同一采集运行中重复访问同一数据源。

使用 monotonic 时钟 + 随机抖动，防止惊群效应。
"""

from __future__ import annotations

import random
import time


class RateLimiter:
    """共享速率限制器，跨采集器协调按源最小抓取间隔。

    追踪每个 source_id 的上次抓取时间（monotonic），
    按需等待以确保不低于配置的最小间隔（含 ±20% 随机抖动）。
    """

    def __init__(self, default_interval_seconds: float = 5.0) -> None:
        """初始化速率限制器。

        Args:
            default_interval_seconds: 未配置 fetch_interval_seconds 时使用的默认间隔。
        """
        self._last_fetch: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._default_interval = float(default_interval_seconds)

    def set_interval(self, source_id: str, interval_seconds: float) -> None:
        """设置指定源的抓取最小间隔（秒）。

        Args:
            source_id: 数据源标识符。
            interval_seconds: 两次抓取之间的最小秒数。
        """
        self._intervals[source_id] = float(interval_seconds)

    def wait_if_needed(self, source_id: str) -> float:
        """如有必要则等待，确保满足最小间隔（含随机抖动）。

        Args:
            source_id: 数据源标识符。

        Returns:
            实际等待的秒数（未等待时返回 0.0）。
        """
        base_interval = self._intervals.get(source_id, self._default_interval)
        # ±20% 随机抖动，避免惊群
        jitter = base_interval * 0.2 * (random.random() * 2.0 - 1.0)  # noqa: S311
        target_interval = base_interval + jitter

        now = time.monotonic()
        last = self._last_fetch.get(source_id)
        if last is not None:
            elapsed = now - last
            if elapsed < target_interval:
                wait_sec = target_interval - elapsed
                t0 = time.monotonic()
                time.sleep(wait_sec)
                actual_waited = time.monotonic() - t0
                self._last_fetch[source_id] = time.monotonic()
                return actual_waited

        self._last_fetch[source_id] = time.monotonic()
        return 0.0

    def reset(self) -> None:
        """重置所有追踪状态（用于测试）。"""
        self._last_fetch.clear()
        self._intervals.clear()
