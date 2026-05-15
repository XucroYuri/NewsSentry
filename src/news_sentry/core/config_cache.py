"""配置文件 TTL 缓存层，包装 YAML 文件读取。

- cachetools.TTLCache 提供自动过期（TTL=60s）
- POST /config/reload 通过 cache.clear() 主动失效
- 线程安全：FastAPI 同步端点中调用，无 asyncio.Lock 需求
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from cachetools import TTLCache


class ConfigCache:
    """带 TTL 过期的 YAML 配置缓存。

    Args:
        ttl: 缓存存活时间（秒），默认 60。
        maxsize: 最大缓存条目数，默认 128。
    """

    def __init__(self, ttl: float = 60, maxsize: int = 128) -> None:
        self._cache: TTLCache[str, dict[str, Any] | None] = TTLCache(
            maxsize=maxsize,
            ttl=ttl,
        )
        self.hits: int = 0
        self.misses: int = 0

    def load_yaml(self, path: Path) -> dict[str, Any] | None:
        """读取 YAML 文件，优先从缓存返回。

        Returns:
            解析后的 dict，文件不存在返回 None。
        """
        key = str(path.resolve())
        if key in self._cache:
            self.hits += 1
            return self._cache[key]

        self.misses += 1
        if not path.is_file():
            self._cache[key] = None
            return None

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            result = data if isinstance(data, dict) else None
        except yaml.YAMLError:
            result = None

        self._cache[key] = result
        return result

    def clear(self) -> None:
        """清除全部缓存条目。"""
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def reload(self) -> None:
        """清除缓存（clear 的语义别名，供 API 端点调用）。"""
        self.clear()
