"""Phase 42 配置写入 handler — 从 api_server.py create_app() 提取。

提供 ``make_config_crud_handlers()`` 工厂函数，返回 6 个 handler:

- ``update_target_config`` — PUT /targets/{target_id}/config
- ``update_source_config`` — PATCH /sources/{target_id}/{source_id}/config
- ``update_filter_config`` — PATCH /filters/{target_id}/config
- ``update_destination_config`` — PATCH /destinations/{destination_id}/config
- ``update_provider_route`` — PATCH /provider/routes/{route_id}
- ``reload_config`` — POST /config/reload
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException

from news_sentry.api.schemas import (
    DestinationConfigUpdate,
    FilterConfigUpdate,
    RouteConfigUpdate,
    SourceConfigUpdate,
    TargetConfigUpdate,
)
from news_sentry.core.config_cache import ConfigCache
from news_sentry.core.target_config_utils import (
    _atomic_write_yaml,
    _config_base_dir,
    _deep_merge,
    _load_yaml_file,
    _source_config_path,
)


def make_config_crud_handlers(
    config_cache: ConfigCache,
    require_write_permission: Callable[..., Any],
) -> dict[str, Callable[..., Any]]:
    """创建 Config CRUD 写操作 handler — 注入闭包依赖。

    Args:
        config_cache: TTL 配置缓存实例 (在 create_app() 中创建)。
        require_write_permission: ``require_permission("write")`` 函数引用。

    Returns:
        {handler_name: handler_function} 字典。
    """

    async def reload_config(
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, str]:
        """清除配置缓存，下次请求时重新从文件加载。"""
        config_cache.reload()
        return {"status": "ok", "message": "Configuration cache cleared"}

    async def update_target_config(
        target_id: str,
        body: TargetConfigUpdate,
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, Any]:
        """更新 target 配置。"""
        filepath = Path(f"config/targets/{target_id}.yaml")
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Target config not found: {target_id}")

        existing = _load_yaml_file(filepath)
        if not existing:
            raise HTTPException(status_code=500, detail="Failed to load existing config")

        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        merged = _deep_merge(existing, update_data)

        _atomic_write_yaml(filepath, merged)
        config_cache.clear()

        return merged

    async def update_source_config(
        target_id: str,
        source_id: str,
        body: SourceConfigUpdate,
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, Any]:
        """更新 source 配置。"""
        filepath = _source_config_path(target_id, source_id)
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Source config not found: {source_id}")

        existing = _load_yaml_file(filepath)
        if not existing:
            raise HTTPException(status_code=500, detail="Failed to load existing config")

        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        merged = _deep_merge(existing, update_data)

        _atomic_write_yaml(filepath, merged)
        config_cache.clear()

        return merged

    async def update_filter_config(
        target_id: str,
        body: FilterConfigUpdate,
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, Any]:
        """更新 filter 配置。"""
        filepath = _config_base_dir() / "filters" / target_id / "default.yaml"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Filter config not found for: {target_id}")

        existing = _load_yaml_file(filepath)
        if not existing:
            raise HTTPException(status_code=500, detail="Failed to load existing config")

        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        merged = _deep_merge(existing, update_data)

        _atomic_write_yaml(filepath, merged)
        config_cache.clear()

        return merged

    async def update_destination_config(
        destination_id: str,
        body: DestinationConfigUpdate,
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, Any]:
        """更新 output destination 配置。"""
        filepath = _config_base_dir() / "output" / "destinations.yaml"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Destinations config not found")

        existing = _load_yaml_file(filepath)
        if not existing:
            raise HTTPException(status_code=500, detail="Failed to load existing config")

        dests: list[dict[str, Any]] = existing.get("destinations", [])
        found = False
        result: dict[str, Any] = {}
        for i, d in enumerate(dests):
            if d.get("destination_id") == destination_id:
                update_data = {k: v for k, v in body.model_dump().items() if v is not None}
                dests[i] = _deep_merge(d, update_data)
                result = dests[i]
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"Destination not found: {destination_id}")

        _atomic_write_yaml(filepath, existing)
        config_cache.clear()

        return result

    async def update_provider_route(
        route_id: str,
        body: RouteConfigUpdate,
        user: dict[str, Any] = Depends(require_write_permission),
    ) -> dict[str, Any]:
        """更新 provider route 配置。"""
        filepath = _config_base_dir() / "provider" / "routes.yaml"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Provider routes config not found")

        existing = _load_yaml_file(filepath)
        if not existing:
            raise HTTPException(status_code=500, detail="Failed to load existing config")

        routes: list[dict[str, Any]] = existing.get("routes", [])
        found = False
        result: dict[str, Any] = {}
        for i, r in enumerate(routes):
            if r.get("route_id") == route_id:
                update_data = {k: v for k, v in body.model_dump().items() if v is not None}
                routes[i] = _deep_merge(r, update_data)
                result = routes[i]
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"Route not found: {route_id}")

        _atomic_write_yaml(filepath, existing)
        config_cache.clear()

        return result

    return {
        "reload_config": reload_config,
        "update_target_config": update_target_config,
        "update_source_config": update_source_config,
        "update_filter_config": update_filter_config,
        "update_destination_config": update_destination_config,
        "update_provider_route": update_provider_route,
    }
