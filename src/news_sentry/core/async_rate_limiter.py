"""令牌桶速率限制器（async 版本），替代同步固定间隔的 RateLimiter。"""

import asyncio


class AsyncRateLimiter:
    """令牌桶算法：允许短时间突发（burst），但平均速率不超限。

    Args:
        rate: 每秒补充的令牌数。
        burst: 桶容量（最大突发数）。
    """

    def __init__(self, rate: float = 0.2, burst: int = 10) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """获取一个令牌，无可用令牌时阻塞等待。"""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._last > 0:
                elapsed = now - self._last
                self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
