"""Target config helpers — target/source config loading, validation, health, YAML I/O.

Extracted from api_server.py module-level functions.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from fastapi import HTTPException

import news_sentry.core._state as _st
from news_sentry.api.schemas import RegionInfo, SourceCreateRequest, SourceInfo, TargetInfo
from news_sentry.core._state import (
    _OVERVIEW_CACHE_TTL_SECONDS,
    _PUBLIC_ANALYSIS_STAGE,
    _PUBLIC_NEWS_MAX_SCAN,
    _PUBLIC_SOURCE_CONFIG_CACHE_TTL_SECONDS,
    _REGION_TYPE_LABELS,
    _REGION_TYPES,
    _SOURCE_SLUG_RE,
    _TARGET_SLUG_RE,
    _public_source_configs_cache,
    _source_inventory_cache,
    _target_validation_cache,
)
from news_sentry.core.public_news_utils import (
    _public_news_target_ids,
    _query_public_projection_events,
)
from news_sentry.core.source_inventory import SourceInventoryService
from news_sentry.core.target_store_utils import _get_target_store

logger = logging.getLogger(__name__)

# ── Late-bound / lazy imports ──
_store_for_target: Any = None


def _load_target_configs() -> list[dict[str, Any]]:
    """从 config/targets/ 读取所有 target 配置。"""
    config_dir = Path("config/targets")
    if not config_dir.is_dir():
        return []
    targets: list[dict[str, Any]] = []
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        # 跳过模板文件
        if yaml_file.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                targets.append(data)
        except yaml.YAMLError:
            continue
    return targets



def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    """安全读取单个 YAML 文件。"""
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None



def _source_path_for_ref(target_id: str, source_ref: str) -> Path:
    """Resolve target-local refs and shared source-pool refs to YAML files."""
    raw_ref = str(source_ref or "")
    ref = _normalize_source_ref(
        raw_ref.removeprefix("pool:") if raw_ref.startswith("pool:") else raw_ref
    )
    if raw_ref.startswith("pool:"):
        return Path("config/source-pools") / f"{ref}.yaml"
    return Path("config/sources") / target_id / f"{ref}.yaml"



def _load_source_configs(target_id: str) -> list[dict[str, Any]]:
    """Load source configs referenced by target, including shared source-pool refs."""
    sources_dir = Path(f"config/sources/{target_id}")
    target_config = _load_target_config(target_id)
    refs = [
        str(ref)
        for ref in (target_config or {}).get("source_channel_refs", [])
        if isinstance(ref, str) and not str(ref).startswith("social/")
    ]
    if not refs and not sources_dir.is_dir():
        return []
    sources: list[dict[str, Any]] = []
    if refs:
        for source_ref in refs:
            yaml_file = _source_path_for_ref(target_id, source_ref)
            data = _load_yaml_file(yaml_file)
            if data and isinstance(data, dict):
                data["_source_id"] = source_ref
                data["_source_ref"] = source_ref
                data["_file_path"] = str(yaml_file)
                sources.append(data)
        return sources
    for yaml_file in sorted(sources_dir.rglob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        data = _load_yaml_file(yaml_file)
        if data and isinstance(data, dict):
            rel = yaml_file.relative_to(sources_dir).with_suffix("")
            data["_source_id"] = str(rel)
            data["_source_ref"] = str(rel)
            data["_file_path"] = str(yaml_file)
            sources.append(data)
    return sources



def _cached_public_source_configs(target_id: str) -> list[dict[str, Any]]:
    """Cache source YAML reads used by public feed item projection."""
    key = f"{Path.cwd()}:{target_id}"
    now = time.monotonic()
    cached = _public_source_configs_cache.get(key)
    if (
        cached
        and now - float(cached.get("created_at", 0)) <= _PUBLIC_SOURCE_CONFIG_CACHE_TTL_SECONDS
    ):
        sources = cached.get("sources")
        if isinstance(sources, list):
            return cast(list[dict[str, Any]], sources)

    sources = _load_source_configs(target_id)
    _public_source_configs_cache[key] = {
        "created_at": now,
        "sources": sources,
    }
    return sources



def _file_signature(paths: list[Path]) -> str:
    """Return a cheap mtime/size signature for cache invalidation."""
    items: list[tuple[str, int, int]] = []
    for path in sorted(set(paths), key=lambda p: str(p)):
        try:
            stat = path.stat()
        except OSError:
            items.append((str(path), -1, -1))
            continue
        items.append((str(path), stat.st_mtime_ns, stat.st_size))
    return sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()



def _target_source_paths(target_id: str) -> list[Path]:
    sources_dir = Path("config/sources") / target_id
    if not sources_dir.is_dir():
        return []
    return [path for path in sources_dir.rglob("*.yaml") if not path.name.startswith("_")]



def _target_inventory_signature(target_id: str) -> str:
    paths = [
        _target_config_path(target_id),
        *_target_source_paths(target_id),
        _st._data_dir / target_id / "memory" / "source_health.yaml",
    ]
    return _file_signature(paths)



def _target_validation_signature(target_id: str) -> str:
    paths = [_target_config_path(target_id), *_target_source_paths(target_id)]
    data = _load_target_config(target_id)
    if isinstance(data, dict):
        for field in (
            "filter_rules_ref",
            "classification_rules_ref",
            "sandbox_profile_ref",
            "provider_routes_ref",
            "output_destinations_ref",
        ):
            ref = data.get(field)
            if ref:
                paths.append(Path(str(ref)))
    return _file_signature(paths)



def _cached_source_inventory(target_id: str) -> dict[str, Any]:
    signature = _target_inventory_signature(target_id)
    key = f"{Path.cwd()}:{_st._data_dir}:{target_id}"
    now = time.monotonic()
    cached = _source_inventory_cache.get(key)
    if (
        cached
        and cached.get("signature") == signature
        and now - float(cached.get("created_at", 0)) <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = cached.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = SourceInventoryService(Path.cwd(), _st._data_dir).build_target_inventory(target_id)
    _source_inventory_cache[key] = {
        "signature": signature,
        "created_at": now,
        "value": value,
    }
    return value



def _cached_target_validation(target_id: str) -> dict[str, Any]:
    signature = _target_validation_signature(target_id)
    key = f"{Path.cwd()}:{_st._data_dir}:{target_id}"
    now = time.monotonic()
    cached = _target_validation_cache.get(key)
    if (
        cached
        and cached.get("signature") == signature
        and now - float(cached.get("created_at", 0)) <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = cached.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = _validate_target_config(target_id)
    _target_validation_cache[key] = {
        "signature": signature,
        "created_at": now,
        "value": value,
    }
    return value



def _source_ids_for_target(target_id: str) -> set[str]:
    """返回 target 当前启用的信源 ID，用于后台健康状态过滤。"""
    ids: set[str] = set()
    for source in _load_source_configs(target_id):
        raw_lifecycle = source.get("lifecycle")
        lifecycle: dict[str, Any] = raw_lifecycle if isinstance(raw_lifecycle, dict) else {}
        if source.get("enabled", True) is False:
            continue
        if source.get("deprecated") is True:
            continue
        if lifecycle.get("status") == "archived":
            continue
        for key in ("source_id", "id", "_source_id", "_source_ref"):
            value = source.get(key)
            if value:
                normalized = str(value).strip()
                ids.add(normalized)
                ids.add(Path(normalized).name)
    return ids



def _filter_source_health_records(
    target_id: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按当前 target 的信源配置过滤健康记录；无配置时保留原结果。"""
    source_ids = _source_ids_for_target(target_id)
    if not source_ids:
        return records
    filtered: list[dict[str, Any]] = []
    for record in records:
        source_id = str(record.get("source_id", "")).strip()
        if source_id in source_ids or Path(source_id).name in source_ids:
            filtered.append(record)
    return filtered



def _source_health_status_from_memory(entry: dict[str, Any]) -> str:
    """把 Memory source_health.yaml 形状归一为 API 状态。"""
    failures = int(entry.get("consecutive_failures") or 0)
    total_runs = int(entry.get("total_runs") or 0)
    total_failures = int(entry.get("total_failures") or 0)
    if failures >= 10:
        return "dead"
    if failures >= 3:
        return "degraded"
    if total_runs > 0 and total_failures >= total_runs:
        return "degraded"
    return "healthy"



def _source_health_error_count_from_memory(entry: dict[str, Any]) -> int:
    """优先使用连续失败数；没有时退回总失败数。"""
    return int(entry.get("consecutive_failures") or entry.get("total_failures") or 0)



def _load_memory_source_health_records(target_id: str | None = None) -> list[dict[str, Any]]:
    """读取真实采集写入的 memory/source_health.yaml 并转成 API 响应形状。"""
    target_ids: list[str]
    if target_id:
        target_ids = [target_id]
    elif _st._data_dir.exists():
        target_ids = sorted(d.name for d in _st._data_dir.iterdir() if d.is_dir())
    else:
        target_ids = []

    records: list[dict[str, Any]] = []
    for tid in target_ids:
        path = _st._data_dir / tid / "memory" / "source_health.yaml"
        if not path.is_file():
            continue
        data = _load_yaml_file(path)
        if not isinstance(data, dict):
            continue
        for source_id, entry in data.items():
            if not isinstance(entry, dict):
                continue
            records.append(
                {
                    "source_id": str(source_id),
                    "status": _source_health_status_from_memory(entry),
                    "last_check": entry.get("last_success_at")
                    or entry.get("last_failure_at")
                    or "",
                    "error_count": _source_health_error_count_from_memory(entry),
                    "last_error": entry.get("last_error"),
                    "last_success_at": entry.get("last_success_at"),
                    "last_failure_at": entry.get("last_failure_at"),
                    "metadata": {
                        "target_id": tid,
                        "last_success_at": entry.get("last_success_at"),
                        "last_failure_at": entry.get("last_failure_at"),
                        "last_error": entry.get("last_error"),
                        "total_runs": entry.get("total_runs", 0),
                        "total_failures": entry.get("total_failures", 0),
                        "consecutive_failures": entry.get("consecutive_failures", 0),
                    },
                }
            )
    return records



def _load_single_source(target_id: str, source_id: str) -> dict[str, Any] | None:
    """读取单个源渠道配置。"""
    source_path = _source_config_path(target_id, source_id)
    if not source_path.parent.exists():
        return None
    return _load_yaml_file(source_path)


# ── 配置写入辅助函数 ─────────────────────────────────



def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个 dict，返回新 dict。override 的值覆盖 base。"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result



def _atomic_write_yaml(filepath: Path, data: dict[str, Any]) -> None:
    """原子写入 YAML 文件（UUID tmp + os.replace）。"""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp = filepath.parent / f".{filepath.name}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        os.replace(tmp, filepath)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

def _target_config_path(target_id: str) -> Path:
    _validate_target_slug(target_id)
    return Path("config/targets") / f"{target_id}.yaml"



def _source_config_path(target_id: str, source_ref: str) -> Path:
    _validate_target_slug(target_id)
    safe_ref = _normalize_source_ref(source_ref)
    return Path("config/sources") / target_id / f"{safe_ref}.yaml"



def _normalize_source_ref(source_ref: str) -> str:
    """规范化 config/sources/{target}/ 下的相对引用。"""
    ref = str(source_ref or "").replace("\\", "/").strip("/")
    if not ref or ref.startswith(".") or "/../" in f"/{ref}/" or Path(ref).is_absolute():
        raise HTTPException(status_code=400, detail="Invalid source ref")
    if any(not part or part.startswith(".") for part in ref.split("/")):
        raise HTTPException(status_code=400, detail="Invalid source ref")
    return ref



def _validate_target_slug(target_id: str) -> None:
    if not _TARGET_SLUG_RE.match(target_id):
        raise HTTPException(status_code=400, detail="Invalid target_id")



def _validate_source_slug(source_id: str) -> None:
    if not _SOURCE_SLUG_RE.match(source_id):
        raise HTTPException(status_code=400, detail="Invalid source_id")



def _load_target_config(target_id: str) -> dict[str, Any] | None:
    return _load_yaml_file(_target_config_path(target_id))



def _target_lifecycle(data: dict[str, Any]) -> dict[str, Any]:
    lifecycle = data.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return {"status": "active"}
    status = lifecycle.get("status") or "active"
    return {**lifecycle, "status": status}



def _target_is_archived(data: dict[str, Any]) -> bool:
    return _target_lifecycle(data).get("status") == "archived"

def _target_monitoring_type(data: dict[str, Any]) -> str:
    raw = data.get("monitoring_type") or data.get("target_type")
    aliases = {
        "country": "country",
        "country-target": "country",
        "country_monitoring": "country",
        "nation": "country",
        "topic": "topic",
        "topic-target": "topic",
        "theme": "topic",
        "subject": "topic",
        "special-topic": "topic",
    }
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace("_", "-")
        if normalized in aliases:
            return aliases[normalized]
    target_id = str(data.get("target_id") or "").strip().lower()
    if (
        target_id == "china-watch-en"
        or target_id.startswith("china-watch")
        or data.get("topic_label")
    ):
        return "topic"
    return "country"



def _target_region_type(data: dict[str, Any]) -> str:
    raw = data.get("region_type") or data.get("monitoring_type") or data.get("target_type")
    aliases = {
        "country": "country",
        "country-target": "country",
        "country_monitoring": "country",
        "nation": "country",
        "region": "region",
        "regional": "region",
        "area": "region",
        "continent": "continent",
        "global": "global",
        "world": "global",
    }
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace("_", "-")
        if normalized in aliases:
            return aliases[normalized]
    return "country"



def _target_is_public_region(data: dict[str, Any]) -> bool:
    if _target_monitoring_type(data) == "topic" or data.get("topic_label"):
        return False
    return _target_region_type(data) in _REGION_TYPES



def _target_topic_label(data: dict[str, Any]) -> str | None:
    for key in ("topic_label", "monitoring_topic", "topic_name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    target_id = str(data.get("target_id") or "").strip().lower()
    if target_id == "china-watch-en":
        return "涉中舆情"
    return None



def _target_info_from_config(data: dict[str, Any], data_dir: Path) -> TargetInfo:
    target_id = data.get("target_id", "")
    lifecycle = _target_lifecycle(data)
    monitoring_type = _target_region_type(data) if _target_is_public_region(data) else "topic"
    refs = [ref for ref in data.get("source_channel_refs", []) if isinstance(ref, str)]
    return TargetInfo(
        target_id=target_id,
        display_name=data.get("display_name", ""),
        primary_language=data.get("language_scope", {}).get("primary", "")
        if isinstance(data.get("language_scope"), dict)
        else "",
        monitoring_type=monitoring_type,
        monitoring_label=_REGION_TYPE_LABELS.get(monitoring_type, "地区"),
        topic_label=None if _target_is_public_region(data) else _target_topic_label(data),
        source_count=len(refs),
        event_count=0,
        lifecycle=lifecycle,
        archived=lifecycle.get("status") == "archived",
    )



def _region_info_from_config(data: dict[str, Any], data_dir: Path) -> RegionInfo:
    target = _target_info_from_config(data, data_dir)
    region_type = _target_region_type(data)
    region_type_value = cast(
        Literal["country", "region", "continent", "global"],
        region_type if region_type in _REGION_TYPES else "country",
    )
    return RegionInfo(
        region_id=target.target_id,
        display_name=target.display_name,
        primary_language=target.primary_language,
        region_type=region_type_value,
        source_count=target.source_count,
        event_count=target.event_count,
        lifecycle=target.lifecycle,
        archived=target.archived,
    )



async def _target_public_event_count(target_id: str, _data_dir: Path) -> int:
    """Return the count the public feed can actually show for a target."""
    try:
        store = await _get_target_store(target_id)
        if store is None:
            store = _st._store
        if store is None:
            return 0
        get_public_count = getattr(store, "get_public_event_count", None)
        if get_public_count is not None:
            return int(await get_public_count(target_id, _PUBLIC_ANALYSIS_STAGE) or 0)
        projection_events = await _query_public_projection_events(
            store,
            target_id=target_id,
            limit=_PUBLIC_NEWS_MAX_SCAN,
        )
        if projection_events is not None:
            return len(projection_events)
        return 0
    except Exception:
        logger.exception("Failed to count indexed public events for target %s", target_id)
        return 0



async def _public_target_event_counts(data_dir: Path) -> dict[str, int]:
    """Return public-ready event counts without scanning every target when global store exists."""
    if _st._store is not None:
        get_counts = getattr(_st._store, "get_public_event_counts_by_target", None)
        if get_counts is not None:
            try:
                store_counts = cast(dict[str, int], await get_counts(_PUBLIC_ANALYSIS_STAGE))
                if store_counts:
                    return store_counts
            except Exception:  # noqa: BLE001
                logger.exception("Failed to count public targets from global store")
    target_counts: dict[str, int] = {}
    for target_id in _public_news_target_ids(data_dir, None):
        count = await _target_public_event_count(target_id, data_dir)
        if count > 0:
            target_counts[target_id] = count
    return target_counts



async def _target_api_event_count(target_id: str) -> int:
    """Return all indexed API events for a target, regardless of public stage."""
    try:
        store = await _store_for_target(target_id)
        if store is None:
            return 0
        get_count = getattr(store, "get_target_event_count", None)
        if get_count is None:
            return 0
        return int(await get_count(target_id) or 0)
    except Exception:
        logger.exception("Failed to count indexed API events for target %s", target_id)
        return 0



async def _target_info_from_config_for_response(
    data: dict[str, Any],
    data_dir: Path,
) -> TargetInfo:
    info = _target_info_from_config(data, data_dir)
    if not info.target_id:
        return info
    event_count = await _target_public_event_count(info.target_id, data_dir)
    return info.model_copy(update={"event_count": event_count})



def _source_is_standard(source: dict[str, Any]) -> bool:
    return source.get("type") in {"rss", "api"}



def _source_is_archived(source: dict[str, Any]) -> bool:
    return (
        bool(source.get("deprecated"))
        or source.get("enabled") is False
        and bool(source.get("deprecated_reason"))
    )



def _source_info_from_config(source: dict[str, Any]) -> SourceInfo:
    url_val = source.get("url")
    if url_val is None:
        endpoint = source.get("endpoint")
        if isinstance(endpoint, dict):
            url_val = endpoint.get("url")
    health = source.get("health")
    health_last = None
    health_failures = None
    if isinstance(health, dict):
        health_last = health.get("last_success_at")
        health_failures = health.get("consecutive_failures")
    source_ref_raw = source.get("_source_id") or source.get("source_ref") or source.get("source_id")
    source_ref = str(source_ref_raw) if source_ref_raw is not None else None
    source_id = str(source.get("source_id") or source_ref or "")
    health_failures_int = int(health_failures) if health_failures is not None else None
    return SourceInfo(
        source_id=source_id,
        source_ref=source_ref,
        display_name=str(source.get("display_name") or ""),
        type=str(source.get("type") or "unknown"),
        enabled=bool(source.get("enabled", True)),
        archived=_source_is_archived(source),
        deprecated=bool(source.get("deprecated", False)),
        deprecated_reason=source.get("deprecated_reason"),
        credibility_base=source.get("credibility_base"),
        health_last_success=str(health_last) if health_last is not None else None,
        health_consecutive_failures=health_failures_int,
        url=str(url_val) if url_val is not None else None,
    )



def _ensure_target_exists(target_id: str) -> dict[str, Any]:
    data = _load_target_config(target_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")
    return data



def _append_source_ref(target_id: str, source_ref: str) -> None:
    data = _ensure_target_exists(target_id)
    refs = data.get("source_channel_refs")
    if not isinstance(refs, list):
        refs = []
    if source_ref not in refs:
        refs.append(source_ref)
    data["source_channel_refs"] = refs
    _atomic_write_yaml(_target_config_path(target_id), data)



def _default_filter_config(target_id: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "score_threshold": 35,
        "max_age_hours": 72,
        "dedup_window_hours": 24,
        "keyword_rules": [],
    }



def _default_classification_config(target_id: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "axes": [
            {"id": "policy", "label": "政策"},
            {"id": "industry", "label": "产业"},
            {"id": "technology", "label": "技术"},
            {"id": "risk", "label": "风险"},
        ],
    }



def _ensure_global_config_defaults() -> None:
    if not Path("config/sandbox/default.yaml").is_file():
        _atomic_write_yaml(Path("config/sandbox/default.yaml"), {"profile": "default"})
    if not Path("config/provider/routes.yaml").is_file():
        _atomic_write_yaml(
            Path("config/provider/routes.yaml"),
            {"routes_version": "1", "routes": []},
        )
    if not Path("config/output/destinations.yaml").is_file():
        _atomic_write_yaml(Path("config/output/destinations.yaml"), {"destinations": []})



def _template_target_config(
    *,
    target_id: str,
    display_name: str,
    language_scope: dict[str, Any],
    timezone: str,
    monitoring_type: str | None = None,
    region_type: str | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = source_refs if source_refs is not None else ["rss-template"]
    resolved_region_type = region_type or monitoring_type or "country"
    data = {
        "target_id": target_id,
        "display_name": display_name,
        "monitoring_type": resolved_region_type,
        "region_type": resolved_region_type,
        "language_scope": language_scope,
        "timezone": timezone,
        "source_channel_refs": refs,
        "filter_rules_ref": f"config/filters/{target_id}/default.yaml",
        "classification_rules_ref": f"config/classification/rules-{target_id}.yaml",
        "sandbox_profile_ref": "config/sandbox/default.yaml",
        "provider_routes_ref": "config/provider/routes.yaml",
        "output_destinations_ref": "config/output/destinations.yaml",
        "classification": {"country_axes": {}},
        "focus_areas": [],
        "lifecycle": {"status": "active"},
    }
    return data



def _default_template_source(target_id: str) -> dict[str, Any]:
    return {
        "source_id": "rss-template",
        "display_name": f"{target_id} RSS Template",
        "type": "rss",
        "url": f"https://example.com/{target_id}/rss.xml",
        "credibility_base": 0.7,
        "fetch_interval_minutes": 60,
        "max_items_per_run": 20,
        "timeout_seconds": 20,
        "enabled": False,
        "deprecated": True,
        "deprecated_reason": "模板占位，启用前请替换为真实信源",
    }



def _copy_target_config_skeleton(source_target_id: str, target_id: str) -> list[str]:
    """复制 target 的配置骨架，不复制 data/ 历史数据。"""
    source_sources = Path("config/sources") / source_target_id
    target_sources = Path("config/sources") / target_id
    if source_sources.is_dir():
        shutil.copytree(source_sources, target_sources, dirs_exist_ok=True)

    source_filter = Path("config/filters") / source_target_id
    target_filter = Path("config/filters") / target_id
    if source_filter.is_dir():
        shutil.copytree(source_filter, target_filter, dirs_exist_ok=True)
    else:
        _atomic_write_yaml(target_filter / "default.yaml", _default_filter_config(target_id))

    source_classification = Path("config/classification") / f"rules-{source_target_id}.yaml"
    target_classification = Path("config/classification") / f"rules-{target_id}.yaml"
    if source_classification.is_file():
        data = _load_yaml_file(source_classification) or {}
        if "target_id" in data:
            data["target_id"] = target_id
        _atomic_write_yaml(target_classification, data)
    else:
        _atomic_write_yaml(target_classification, _default_classification_config(target_id))

    target_data = _ensure_target_exists(source_target_id)
    refs = target_data.get("source_channel_refs", [])
    return [str(ref) for ref in refs if isinstance(ref, str)]



def _stop_target_in_collector_config(target_id: str) -> None:
    config_path = Path("config/runtime/collector.yaml")
    data = _load_yaml_file(config_path)
    if not data:
        return
    target_ids = data.get("target_ids")
    changed = False
    if isinstance(target_ids, list) and target_id in target_ids:
        data["target_ids"] = [item for item in target_ids if item != target_id]
        changed = True
    elif isinstance(target_ids, str) and target_ids == target_id:
        data["target_ids"] = []
        changed = True
    if changed:
        _atomic_write_yaml(config_path, data)



def _build_source_config(payload: SourceCreateRequest) -> tuple[str, dict[str, Any]]:
    _validate_source_slug(payload.source_id)
    source_ref = _normalize_source_ref(payload.source_ref or payload.source_id)
    data: dict[str, Any] = {
        "source_id": payload.source_id,
        "display_name": payload.display_name,
        "type": payload.type,
        "credibility_base": payload.credibility_base,
        "fetch_interval_minutes": payload.fetch_interval_minutes,
        "max_items_per_run": payload.max_items_per_run,
        "timeout_seconds": payload.timeout_seconds,
        "enabled": payload.enabled,
    }
    if payload.notes:
        data["notes"] = payload.notes
    if payload.type == "rss":
        if not payload.url:
            raise HTTPException(status_code=400, detail="RSS source requires url")
        data["url"] = payload.url
    elif payload.type == "api":
        endpoint = payload.endpoint or {"url": payload.url, "method": "GET"}
        if not endpoint.get("url"):
            raise HTTPException(status_code=400, detail="API source requires endpoint.url")
        data["endpoint"] = endpoint
        data["api_mapping"] = payload.api_mapping or {}
    return source_ref, data



def _social_dimensions(target_id: str) -> list[dict[str, Any]]:
    root = Path("config/sources") / target_id / "social"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.yaml")):
        data = _load_yaml_file(path)
        if not data:
            continue
        rel = path.relative_to(Path("config/sources") / target_id).with_suffix("")
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []
        data["_source_ref"] = str(rel)
        data["_file_path"] = str(path)
        data["accounts"] = accounts
        data["account_count"] = len(accounts)
        data["archived_count"] = sum(
            1
            for account in accounts
            if isinstance(account, dict) and account.get("monitor_mode") == "archived"
        )
        items.append(data)
    return items



def _find_social_dimension_path(target_id: str, dimension: str) -> Path | None:
    for item in _social_dimensions(target_id):
        if item.get("dimension") == dimension:
            file_path = item.get("_file_path")
            return Path(file_path) if file_path else None
    return None



def _validate_target_config(target_id: str) -> dict[str, Any]:
    """返回 target 配置链路预检结果。"""
    checks: list[dict[str, Any]] = []
    data = _load_target_config(target_id)
    if data is None:
        return {
            "target_id": target_id,
            "ok": False,
            "checks": [
                {
                    "id": "target_config",
                    "label": "Target 配置",
                    "ok": False,
                    "severity": "error",
                    "message": "Target 配置文件不存在",
                    "items": [],
                }
            ],
        }

    refs = [str(ref) for ref in data.get("source_channel_refs", []) if isinstance(ref, str)]
    duplicate_refs = sorted({ref for ref in refs if refs.count(ref) > 1})
    missing_refs = [
        ref
        for ref in refs
        if not ref.startswith("social/") and not _source_path_for_ref(target_id, ref).is_file()
    ]
    checks.append(
        {
            "id": "source_refs",
            "label": "信源引用",
            "ok": not duplicate_refs and not missing_refs,
            "severity": "error" if duplicate_refs or missing_refs else "ok",
            "message": "信源引用完整"
            if not duplicate_refs and not missing_refs
            else "存在重复或缺失的信源引用",
            "items": [{"type": "duplicate", "ref": ref} for ref in duplicate_refs]
            + [{"type": "missing", "ref": ref} for ref in missing_refs],
        }
    )

    ref_fields = [
        ("filter_rules_ref", "过滤规则"),
        ("classification_rules_ref", "分类规则"),
        ("sandbox_profile_ref", "沙箱配置"),
        ("provider_routes_ref", "Provider 路由"),
        ("output_destinations_ref", "输出配置"),
    ]
    for field, label in ref_fields:
        ref = data.get(field)
        exists = bool(ref) and Path(str(ref)).is_file()
        checks.append(
            {
                "id": field,
                "label": label,
                "ok": exists,
                "severity": "error" if not exists else "ok",
                "message": "引用文件存在" if exists else f"{label}引用缺失",
                "items": [] if exists else [{"ref": ref}],
            }
        )

    bad_urls: list[dict[str, str]] = []
    for source in _load_source_configs(target_id):
        if not _source_is_standard(source):
            continue
        url_val = source.get("url")
        if url_val is None and isinstance(source.get("endpoint"), dict):
            url_val = source["endpoint"].get("url")
        if url_val and not str(url_val).startswith(("http://", "https://")):
            bad_urls.append({"source_ref": str(source.get("_source_id", "")), "url": str(url_val)})
    checks.append(
        {
            "id": "source_urls",
            "label": "信源 URL",
            "ok": not bad_urls,
            "severity": "error" if bad_urls else "ok",
            "message": "URL 格式可用" if not bad_urls else "存在非 HTTP(S) URL",
            "items": bad_urls,
        }
    )

    missing_sessions: list[dict[str, str]] = []
    for social in _social_dimensions(target_id):
        ref = social.get("session_profile_ref")
        if ref and not Path(str(ref)).is_file():
            missing_sessions.append(
                {"dimension": str(social.get("dimension", "")), "session_profile_ref": str(ref)}
            )
    checks.append(
        {
            "id": "social_sessions",
            "label": "社媒会话",
            "ok": not missing_sessions,
            "severity": "warning" if missing_sessions else "ok",
            "message": "社媒会话配置存在" if not missing_sessions else "部分社媒会话配置缺失",
            "items": missing_sessions,
        }
    )
    return {
        "target_id": target_id,
        "ok": all(check["ok"] or check["severity"] == "warning" for check in checks),
        "checks": checks,
    }


