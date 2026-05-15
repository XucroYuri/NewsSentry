"""LLM 缓存管理器 — 包装 AsyncStore.llm_cache 操作。

SHA-256 key 生成，翻译缓存 LRU 淘汰，研判缓存永不过期。
"""

from __future__ import annotations

import hashlib
import logging

from news_sentry.core.async_store import AsyncStore

logger = logging.getLogger(__name__)


class LLMCacheManager:
    """LLM 响应缓存管理器。"""

    def __init__(
        self,
        store: AsyncStore,
        max_entries: int = 10000,
        default_temperature: float = 0.3,
    ) -> None:
        self._store = store
        self._max_entries = max_entries
        self._default_temperature = default_temperature

    def make_cache_key(
        self,
        prefix: str,
        prompt: str,
        model: str,
        temperature: float | None = None,
    ) -> str:
        """生成 SHA-256 缓存 key。"""
        temp = temperature if temperature is not None else self._default_temperature
        raw = f"{prefix}:{prompt}:{model}:{temp}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, cache_key: str) -> str | None:
        """获取缓存响应。"""
        return await self._store.get_cached_response(cache_key)

    async def set(self, cache_key: str, response: str, model: str) -> None:
        """设置缓存响应，然后检查淘汰。"""
        await self._store.set_cached_response(cache_key, response, model)
        await self.evict_if_needed()

    async def evict_if_needed(self) -> int:
        """按 LRU 策略淘汰超限条目。"""
        return await self._store.evict_if_needed(self._max_entries)
