import asyncio
import time

import pytest

from news_sentry.core.async_rate_limiter import AsyncRateLimiter


class TestAsyncRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_immediately_when_tokens_available(self):
        limiter = AsyncRateLimiter(rate=10.0, burst=10)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_waits_when_no_tokens(self):
        limiter = AsyncRateLimiter(rate=10.0, burst=1)
        await limiter.acquire()
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08
        assert elapsed < 0.3

    @pytest.mark.asyncio
    async def test_burst_allows_rapid_fire(self):
        limiter = AsyncRateLimiter(rate=1.0, burst=5)
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.2

    @pytest.mark.asyncio
    async def test_tokens_replenish_over_time(self):
        limiter = AsyncRateLimiter(rate=100.0, burst=2)
        await limiter.acquire()
        await limiter.acquire()
        await asyncio.sleep(0.05)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1
