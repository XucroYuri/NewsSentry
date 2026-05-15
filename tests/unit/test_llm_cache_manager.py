"""Tests for core/llm_cache_manager.py — LLM 缓存管理器。"""

from __future__ import annotations

from pathlib import Path

import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.llm_cache_manager import LLMCacheManager


class TestLLMCacheManager:
    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_cache_key_is_deterministic(self, store: AsyncStore):
        """相同输入应生成相同 cache key。"""
        mgr = LLMCacheManager(store)
        key1 = mgr.make_cache_key("translate", "Hello world", "gpt-4o-mini")
        key2 = mgr.make_cache_key("translate", "Hello world", "gpt-4o-mini")
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_cache_key_differs_by_prefix(self, store: AsyncStore):
        """不同前缀应生成不同 key。"""
        mgr = LLMCacheManager(store)
        k1 = mgr.make_cache_key("translate", "prompt", "model")
        k2 = mgr.make_cache_key("judge", "prompt", "model")
        assert k1 != k2

    @pytest.mark.asyncio
    async def test_set_and_get(self, store: AsyncStore):
        """set 后 get 应返回缓存值。"""
        mgr = LLMCacheManager(store)
        key = mgr.make_cache_key("translate", "Hello", "gpt-4o-mini")
        await mgr.set(key, '{"title": "你好"}', "gpt-4o-mini")
        result = await mgr.get(key)
        assert result == '{"title": "你好"}'

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self, store: AsyncStore):
        """缓存未命中返回 None。"""
        mgr = LLMCacheManager(store)
        result = await mgr.get("nonexistent-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_evict_respects_max_entries(self, store: AsyncStore):
        """淘汰应遵守 max_entries。"""
        mgr = LLMCacheManager(store, max_entries=3)
        # set() 内部每次插入后自动淘汰，所以最终条目数不超过 max_entries
        for i in range(5):
            await mgr.set(f"key-{i}", f"value-{i}", "model")
        # LRU 淘汰: key-0, key-1 应被淘汰; key-2, key-3, key-4 保留
        assert await mgr.get("key-0") is None
        assert await mgr.get("key-1") is None
        assert await mgr.get("key-2") is not None
        assert await mgr.get("key-3") is not None
        assert await mgr.get("key-4") is not None
