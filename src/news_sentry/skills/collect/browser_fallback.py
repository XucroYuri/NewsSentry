"""浏览器采集多层兜底模块。

实现 3 层降级：
  Layer 1: OpenCLI Bridge（首选，零 token）
  Layer 2: Playwright MCP（兜底，零 token）
  Layer 3: Computer Use（仅 L1 最终保障，消耗 token）
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any


class FallbackLayer(IntEnum):
    """降级层级"""
    LAYER_1 = 1    # OpenCLI Bridge
    LAYER_2 = 2    # Playwright MCP
    LAYER_3 = 3    # Computer Use


class LayerStatus:
    """某层的当前状态。"""
    def __init__(self) -> None:
        self.consecutive_failures: int = 0
        self.total_uses_today: int = 0


class BrowserFallback:
    """管理浏览器采集的多层降级逻辑。

    使用方式:
        bf = BrowserFallback(fallback_config)
        if bf.active_layer == 1:
            result = try_opencli_bridge(...)
        elif bf.active_layer == 2:
            result = try_playwright_mcp(...)
        elif bf.should_use_layer_3(tier):
            result = try_computer_use(...)

        if result.success:
            bf.record_success()
        else:
            bf.record_failure()
    """

    def __init__(self, config: dict[str, Any]) -> None:
        fb = config.get("browser_fallback", {})
        self._degrade_l2: int = int(fb.get("degrade_to_layer2_after_failures", 2))
        self._degrade_l3: int = int(fb.get("degrade_to_layer3_after_failures", 5))

        l3_cfg = fb.get("layer_3", {})
        self._max_l3_per_day: int = int(l3_cfg.get("max_uses_per_source_per_day", 3))

        self.active_layer: int = 1
        self._layer1 = LayerStatus()
        self._layer2 = LayerStatus()
        self._layer3 = LayerStatus()

    def record_failure(self) -> None:
        """记录当前层失败，触发可能的降级。"""
        if self.active_layer == 1:
            self._layer1.consecutive_failures += 1
        elif self.active_layer == 2:
            self._layer2.consecutive_failures += 1

        total = self._layer1.consecutive_failures + self._layer2.consecutive_failures
        if self.active_layer == 1 and self._layer1.consecutive_failures >= self._degrade_l2:
            self.active_layer = 2
        elif self.active_layer == 2 and total >= self._degrade_l3:
            pass  # Layer 3 通过 should_use_layer_3 手动触发

    def record_success(self) -> None:
        """记录当前层成功，尝试恢复。"""
        if self.active_layer == 2:
            self._layer2.consecutive_failures = 0
            self._layer1.consecutive_failures -= 1
            if self._layer1.consecutive_failures <= 0:
                self._layer1.consecutive_failures = 0
                self.active_layer = 1
        elif self.active_layer == 1:
            self._layer1.consecutive_failures = max(0, self._layer1.consecutive_failures - 1)

    def should_use_layer_3(self, tier: str) -> bool:
        """检查是否应使用 Layer 3（仅 L1 + 总失败数达到阈值）。"""
        if tier != "L1":
            return False
        total = self._layer1.consecutive_failures + self._layer2.consecutive_failures
        return total >= self._degrade_l3 and self._layer3.total_uses_today < self._max_l3_per_day
