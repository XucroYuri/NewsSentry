"""Collector & enrichment config helpers — auto-collect, AI enrichment, public translation loops.

Extracted from api_server.py module-level functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from news_sentry.core._state import (
    _COLLECTOR_STAGES,
    _OVERVIEW_CACHE_TTL_SECONDS,
    _ai_enrichment_log,
    _ai_enrichment_state,
    _auto_collector_state,
    _collector_diagnostics_cache,
    _data_dir,
    _log,
    _public_translation_log,
    _public_translation_state,
    _store,
)
from news_sentry.core.ai_enrichment import (
    AIEnrichmentConfig,
    AIEnrichmentEngine,
    normalize_ai_enrichment_config,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.public_translation import (
    PublicTranslationConfig,
    PublicTranslationEngine,
    normalize_public_translation_config,
    public_publication_ready,
)
from news_sentry.core.target_config_utils import (
    _atomic_write_yaml,
    _file_signature,
    _filter_source_health_records,
    _load_memory_source_health_records,
    _load_target_configs,
    _load_yaml_file,
    _target_public_event_count,
    _target_source_paths,
)
from news_sentry.core.target_store_utils import (
    _get_target_store,
    _latest_run_log_summary,
    _visible_index_events_page,
)

logger = logging.getLogger(__name__)


def _parse_target_ids(raw: str) -> list[str]:
    """解析 target ID 字符串：'all' → 全量 targets，'a,b' → ['a','b']."""
    if raw.strip().lower() == "all":
        from news_sentry.core.async_run import _resolve_targets
        from news_sentry.core.run import _find_project_root

        return _resolve_targets("all", _find_project_root())
    return [t.strip() for t in raw.split(",") if t.strip()]

def _collector_config_path() -> Path:
    """返回本地持久化的采集器配置路径。"""
    return Path("config/runtime/collector.yaml")



def _collector_env_defaults() -> dict[str, Any]:
    """从环境变量构造采集器默认值。"""
    try:
        interval = int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15"))
    except ValueError:
        interval = 15
    return {
        "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
        "target_ids": _parse_target_ids(
            os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "all"))
        ),
        "interval_minutes": interval,
        "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),
    }



def _collector_env_enabled_override() -> bool | None:
    """返回显式环境变量采集开关。

    YAML 保存的是后台 UI 的运行时偏好；环境变量是进程启动边界。
    部署时需要能明确把 Web 进程和采集任务拆开，避免 API 服务启动时
    立即跑全量采集并拖慢健康检查。
    """
    value = os.environ.get("NEWSSENTRY_AUTO_COLLECT")
    if value is None:
        return None
    return value == "1"



def _normalize_collector_config(raw: dict[str, Any]) -> dict[str, Any]:
    """规范化采集器配置，保证 API 与 YAML 使用同一形状。"""
    defaults = _collector_env_defaults()
    data = {**defaults, **{k: v for k, v in raw.items() if v is not None}}
    enabled_override = _collector_env_enabled_override()

    target_ids_raw = data.get("target_ids", defaults["target_ids"])
    if isinstance(target_ids_raw, str):
        target_ids = _parse_target_ids(target_ids_raw)
    elif isinstance(target_ids_raw, list):
        target_ids = [str(t).strip() for t in target_ids_raw if str(t).strip()]
    else:
        target_ids = defaults["target_ids"]

    stage = str(data.get("stage") or defaults["stage"]).strip().lower()
    if stage not in _COLLECTOR_STAGES:
        stage = defaults["stage"] if defaults["stage"] in _COLLECTOR_STAGES else "collect"

    try:
        interval = int(data.get("interval_minutes", defaults["interval_minutes"]))
    except (TypeError, ValueError):
        interval = int(defaults["interval_minutes"])
    interval = max(1, min(interval, 1440))

    return {
        "enabled": enabled_override if enabled_override is not None else bool(data.get("enabled")),
        "target_ids": target_ids,
        "interval_minutes": interval,
        "stage": stage,
    }



def _load_collector_config() -> dict[str, Any]:
    """读取采集器配置；没有 YAML 时使用环境变量默认值。"""
    path = _collector_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_collector_config(loaded)



def _save_collector_config(config: dict[str, Any]) -> None:
    """持久化采集器配置到 config/runtime/collector.yaml。"""
    normalized = _normalize_collector_config(config)
    path = _collector_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, normalized)



def _apply_collector_config(config: dict[str, Any]) -> dict[str, Any]:
    """应用采集器配置到内存状态并返回规范化结果。"""
    normalized = _normalize_collector_config(config)
    _auto_collector_state["enabled"] = normalized["enabled"]
    _auto_collector_state["target_ids"] = normalized["target_ids"]
    _auto_collector_state["interval_minutes"] = normalized["interval_minutes"]
    _auto_collector_state["stage"] = normalized["stage"]
    return normalized



def _collector_payload() -> dict[str, Any]:
    """返回统一的采集器状态响应。"""
    latest_log = _latest_run_log_summary(_data_dir)
    last_run_at = _auto_collector_state["last_run_at"]
    last_run_status = _auto_collector_state["last_run_status"]
    last_events_collected = _auto_collector_state.get("last_events_collected", 0)
    if latest_log and not last_run_at:
        last_run_at = latest_log.get("ended_at") or latest_log.get("started_at")
        last_run_status = latest_log.get("status")
        last_events_collected = latest_log.get("events_collected", 0)
    return {
        "enabled": _auto_collector_state["enabled"],
        "running": _auto_collector_state["running"],
        "target_ids": _auto_collector_state["target_ids"],
        "stage": _auto_collector_state["stage"],
        "interval_minutes": _auto_collector_state["interval_minutes"],
        "last_run_at": last_run_at,
        "last_run_status": last_run_status,
        "last_events_collected": last_events_collected,
        "last_error": _auto_collector_state.get("last_error"),
        "next_run_at": _auto_collector_state.get("next_run_at"),
        "total_runs": _auto_collector_state["total_runs"],
    }



def _collector_diagnostics_signature() -> str:
    paths: list[Path] = []
    if _data_dir.exists():
        for target_dir in sorted(d for d in _data_dir.iterdir() if d.is_dir()):
            paths.append(target_dir / "memory" / "source_health.yaml")
            paths.append(target_dir / "source_health.json")
            paths.extend(_target_source_paths(target_dir.name))
    return _file_signature(paths)  # type: ignore[no-any-return]



def _build_collector_diagnostics_payload() -> dict[str, Any]:
    """Build collector diagnostics without endpoint/auth concerns."""
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "name": "auto_collect_enabled",
            "ok": _auto_collector_state["enabled"],
            "message": (
                "已启用"
                if _auto_collector_state["enabled"]
                else "未启用 — 设置 NEWSSENTRY_AUTO_COLLECT=1"
            ),
        }
    )

    has_ai_key = bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("GROQ_API_KEY")
    )
    checks.append(
        {
            "name": "ai_api_key",
            "ok": has_ai_key,
            "message": (
                "已配置"
                if has_ai_key
                else (
                    "未配置 AI API Key"
                    " (GEMINI_API_KEY/DEEPSEEK_API_KEY/GROQ_API_KEY)"
                    " — 研判/翻译将跳过"
                )
            ),
        }
    )

    data_exists = _data_dir.exists()
    target_dirs = sorted([d.name for d in _data_dir.iterdir() if d.is_dir()]) if data_exists else []
    checks.append(
        {
            "name": "data_directory",
            "ok": data_exists and len(target_dirs) > 0,
            "message": (
                f"数据目录: {_data_dir} — {len(target_dirs)} 个 target: "
                f"{', '.join(target_dirs) if target_dirs else '无'}"
            ),
        }
    )

    healthy = 0
    unhealthy = 0
    if data_exists:
        for tid in target_dirs:
            memory_health = _filter_source_health_records(
                tid,
                _load_memory_source_health_records(tid),
            )
            if memory_health:
                for item in memory_health:
                    if item.get("status") == "healthy":
                        healthy += 1
                    else:
                        unhealthy += 1
                continue
            health_file = _data_dir / tid / "source_health.json"
            if health_file.exists():
                try:
                    health_data = json.loads(health_file.read_text())
                    items = health_data if isinstance(health_data, list) else []
                    for item in items:
                        if item.get("healthy"):
                            healthy += 1
                        else:
                            unhealthy += 1
                except Exception:  # noqa: S110
                    pass
    checks.append(
        {
            "name": "source_health",
            "ok": (healthy + unhealthy) > 0,
            "message": (
                f"健康: {healthy}, 异常: {unhealthy}"
                if (healthy + unhealthy) > 0
                else "暂无信源健康数据 — 运行一次采集后生成"
            ),
        }
    )

    last_run = _collector_payload()["last_run_at"]
    checks.append(
        {
            "name": "last_collection",
            "ok": last_run is not None,
            "message": f"最后采集: {last_run}" if last_run else "尚未执行采集 — 等待首次采集周期",
        }
    )

    overall = all(check["ok"] for check in checks)
    return {"overall": "healthy" if overall else "attention_needed", "checks": checks}



def _cached_collector_diagnostics_payload() -> dict[str, Any]:
    signature = _collector_diagnostics_signature()
    now = time.monotonic()
    if (
        _collector_diagnostics_cache.get("signature") == signature
        and now - float(_collector_diagnostics_cache.get("created_at", 0))
        <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = _collector_diagnostics_cache.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = _build_collector_diagnostics_payload()
    _collector_diagnostics_cache.update(
        {
            "signature": signature,
            "created_at": now,
            "value": value,
        }
    )
    return value



def _ai_enrichment_config_path() -> Path:
    return Path("config/runtime/ai_enrichment.yaml")



def _ai_enrichment_env_defaults() -> dict[str, Any]:
    return {
        "enabled": os.environ.get("NEWSSENTRY_AI_ENRICHMENT", "1") == "1",
        "interval_minutes": int(os.environ.get("NEWSSENTRY_AI_ENRICH_INTERVAL", "60")),
        "daily_request_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_DAILY_LIMIT", "45")),
        "per_cycle_request_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_PER_CYCLE", "3")),
        "max_chars_per_request": int(os.environ.get("NEWSSENTRY_AI_ENRICH_MAX_CHARS", "6000")),
        "cooldown_after_429_minutes": int(
            os.environ.get("NEWSSENTRY_AI_ENRICH_COOLDOWN_MINUTES", "120")
        ),
        "targets": os.environ.get("NEWSSENTRY_AI_ENRICH_TARGETS", "all"),
        "candidate_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_CANDIDATES", "200")),
    }



def _ai_enrichment_config_to_dict(config: AIEnrichmentConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "interval_minutes": config.interval_minutes,
        "daily_request_limit": config.daily_request_limit,
        "per_cycle_request_limit": config.per_cycle_request_limit,
        "max_chars_per_request": config.max_chars_per_request,
        "cooldown_after_429_minutes": config.cooldown_after_429_minutes,
        "targets": list(config.targets),
        "candidate_limit": config.candidate_limit,
    }



def _normalize_ai_enrichment_config(raw: dict[str, Any] | None) -> AIEnrichmentConfig:
    return normalize_ai_enrichment_config({**_ai_enrichment_env_defaults(), **(raw or {})})



def _load_ai_enrichment_config() -> AIEnrichmentConfig:
    path = _ai_enrichment_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_ai_enrichment_config(loaded)



def _save_ai_enrichment_config(config: dict[str, Any]) -> AIEnrichmentConfig:
    normalized = _normalize_ai_enrichment_config(config)
    path = _ai_enrichment_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, _ai_enrichment_config_to_dict(normalized))
    return normalized



def _apply_ai_enrichment_config(config: AIEnrichmentConfig | dict[str, Any]) -> AIEnrichmentConfig:
    normalized = (
        config
        if isinstance(config, AIEnrichmentConfig)
        else _normalize_ai_enrichment_config(config)
    )
    for key, value in _ai_enrichment_config_to_dict(normalized).items():
        _ai_enrichment_state[key] = value
    return normalized



def _current_ai_enrichment_config() -> AIEnrichmentConfig:
    return normalize_ai_enrichment_config(
        {
            "enabled": _ai_enrichment_state["enabled"],
            "interval_minutes": _ai_enrichment_state["interval_minutes"],
            "daily_request_limit": _ai_enrichment_state["daily_request_limit"],
            "per_cycle_request_limit": _ai_enrichment_state["per_cycle_request_limit"],
            "max_chars_per_request": _ai_enrichment_state["max_chars_per_request"],
            "cooldown_after_429_minutes": _ai_enrichment_state["cooldown_after_429_minutes"],
            "targets": _ai_enrichment_state["targets"],
            "candidate_limit": _ai_enrichment_state["candidate_limit"],
        }
    )



def _public_translation_config_path() -> Path:
    return Path("config/runtime/public_translation.yaml")



def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default



def _safe_int_env_value(value: str | None, default: int) -> int:
    try:
        return int(value or str(default))
    except (TypeError, ValueError):
        return default



def _public_translation_env_defaults() -> dict[str, Any]:
    publication_interval = os.environ.get(
        "NEWSSENTRY_PUBLIC_PUBLICATION_INTERVAL",
        os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_INTERVAL", "5"),
    )
    publication_per_cycle = os.environ.get(
        "NEWSSENTRY_PUBLIC_PUBLICATION_PER_CYCLE",
        os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_PER_CYCLE", "50"),
    )
    return {
        "enabled": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION", "1") == "1",
        "interval_minutes": _safe_int_env_value(publication_interval, 5),
        "per_cycle_limit": _safe_int_env_value(publication_per_cycle, 50),
        "candidate_limit": _safe_int_env("NEWSSENTRY_PUBLIC_TRANSLATION_CANDIDATES", 500),
        "source_lang": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_SOURCE_LANG", "auto"),
        "target_lang": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_TARGET_LANG", "zh"),
    }



def _public_translation_config_to_dict(config: PublicTranslationConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "interval_minutes": config.interval_minutes,
        "per_cycle_limit": config.per_cycle_limit,
        "candidate_limit": config.candidate_limit,
        "source_lang": config.source_lang,
        "target_lang": config.target_lang,
    }



def _normalize_public_translation_config(
    raw: dict[str, Any] | None,
) -> PublicTranslationConfig:
    return normalize_public_translation_config(
        {**_public_translation_env_defaults(), **(raw or {})}
    )



def _load_public_translation_config() -> PublicTranslationConfig:
    path = _public_translation_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_public_translation_config(loaded)



def _save_public_translation_config(config: dict[str, Any]) -> PublicTranslationConfig:
    normalized = _normalize_public_translation_config(config)
    path = _public_translation_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, _public_translation_config_to_dict(normalized))
    return normalized



def _apply_public_translation_config(
    config: PublicTranslationConfig | dict[str, Any],
) -> PublicTranslationConfig:
    normalized = (
        config
        if isinstance(config, PublicTranslationConfig)
        else _normalize_public_translation_config(config)
    )
    for key, value in _public_translation_config_to_dict(normalized).items():
        _public_translation_state[key] = value
    return normalized



def _current_public_translation_config() -> PublicTranslationConfig:
    return normalize_public_translation_config(
        {
            "enabled": _public_translation_state["enabled"],
            "interval_minutes": _public_translation_state["interval_minutes"],
            "per_cycle_limit": _public_translation_state["per_cycle_limit"],
            "candidate_limit": _public_translation_state["candidate_limit"],
            "source_lang": _public_translation_state["source_lang"],
            "target_lang": _public_translation_state["target_lang"],
        }
    )



def _ai_enrichment_today() -> str:
    return datetime.now(UTC).date().isoformat()



def _ai_enrichment_target_ids(
    config: AIEnrichmentConfig,
    target_id: str | None = None,
) -> list[str]:
    if target_id and target_id != "all":
        return [target_id]
    if "all" in config.targets:
        return [item["target_id"] for item in _load_target_configs() if item.get("target_id")]
    return list(config.targets)



def _create_ai_provider_router() -> Any | None:  # noqa: ANN401
    try:
        from news_sentry.core.provider_router import ProviderRouter
        from news_sentry.models.provider_config import ProviderRoutesConfig

        routes_path = Path("config/provider/routes.yaml")
        if not routes_path.is_file():
            return None
        data = _load_yaml_file(routes_path)
        if not isinstance(data, dict):
            return None
        return ProviderRouter(ProviderRoutesConfig(**data))
    except Exception as exc:  # noqa: BLE001
        _ai_enrichment_log.warning("AI enrichment provider router unavailable: %s", exc)
        return None



def _build_ai_provider_factory() -> Any:  # noqa: ANN401
    from news_sentry.core.run import _build_provider_factory

    return _build_provider_factory()



async def _ai_enrichment_store_for_target(target_id: str) -> AsyncStore | None:
    target_store = await _get_target_store(target_id)
    return target_store if target_store is not None else _store  # type: ignore[no-any-return]



async def _ai_enrichment_rows_for_target(
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if store is None:
        return []
    result = await _visible_index_events_page(
        store,
        _data_dir,
        stage="drafts",
        target_id=target_id,
        page=1,
        page_size=limit,
        exact_total=False,
    )
    return list(result.get("events") or [])



async def _ai_enrichment_usage_store(target_stores: list[AsyncStore | None]) -> AsyncStore | None:
    if _store is not None:
        return _store  # type: ignore[no-any-return]
    for store in target_stores:
        if store is not None:
            return store
    return None



async def _ai_enrichment_status_payload() -> dict[str, Any]:
    config = _current_ai_enrichment_config()
    usage_store = await _ai_enrichment_usage_store([])
    usage = (
        await usage_store.get_ai_enrichment_usage(_ai_enrichment_today())
        if usage_store is not None
        else {
            "usage_date": _ai_enrichment_today(),
            "request_count": 0,
            "cooldown_until": None,
            "last_error": None,
        }
    )
    return {
        "enabled": _ai_enrichment_state["enabled"],
        "running": _ai_enrichment_state["running"],
        "config": _ai_enrichment_config_to_dict(config),
        "usage": usage,
        "remaining_daily_requests": max(
            0, config.daily_request_limit - int(usage.get("request_count") or 0)
        ),
        "last_run_at": _ai_enrichment_state.get("last_run_at"),
        "last_run_status": _ai_enrichment_state.get("last_run_status"),
        "last_error": _ai_enrichment_state.get("last_error"),
        "next_run_at": _ai_enrichment_state.get("next_run_at"),
        "total_runs": _ai_enrichment_state["total_runs"],
        "last_updates": _ai_enrichment_state.get("last_updates", 0),
    }



async def _run_ai_enrichment_once(
    *,
    target_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = _current_ai_enrichment_config()
    engine = AIEnrichmentEngine(config)
    target_ids = _ai_enrichment_target_ids(config, target_id)
    stores_by_target: dict[str, AsyncStore | None] = {}
    rows_by_target: dict[str, list[dict[str, Any]]] = {}
    for tid in target_ids:
        store = await _ai_enrichment_store_for_target(tid)
        stores_by_target[tid] = store
        rows_by_target[tid] = await _ai_enrichment_rows_for_target(
            tid, store, limit=config.candidate_limit
        )

    if dry_run:
        return {
            "dry_run": True,
            "targets": target_ids,
            "batches": [
                engine.payload_for_batch(batch)
                for tid in target_ids
                for batch in engine.plan_batches(tid, rows_by_target[tid])[
                    : config.per_cycle_request_limit
                ]
            ],
        }

    usage_store = await _ai_enrichment_usage_store(list(stores_by_target.values()))
    if usage_store is None:
        return {"dry_run": False, "status": "no_store", "targets": target_ids, "updates": []}

    today = _ai_enrichment_today()
    usage = await usage_store.get_ai_enrichment_usage(today)
    if usage.get("cooldown_until") and str(usage["cooldown_until"]) > datetime.now(UTC).isoformat():
        return {
            "dry_run": False,
            "status": "cooldown",
            "targets": target_ids,
            "cooldown_until": usage.get("cooldown_until"),
            "updates": [],
        }
    if int(usage.get("request_count") or 0) >= config.daily_request_limit:
        return {"dry_run": False, "status": "daily_limit", "targets": target_ids, "updates": []}

    router = _create_ai_provider_router()
    if router is None:
        return {"dry_run": False, "status": "no_router", "targets": target_ids, "updates": []}

    provider_factory = _build_ai_provider_factory()
    total_updates: list[dict[str, Any]] = []
    total_requests = 0
    target_results: list[dict[str, Any]] = []
    for tid in target_ids:
        used_today = int(usage.get("request_count") or 0)
        remaining = config.daily_request_limit - used_today - total_requests
        if remaining <= 0:
            break
        target_config = AIEnrichmentConfig(
            **{
                **_ai_enrichment_config_to_dict(config),
                "per_cycle_request_limit": min(config.per_cycle_request_limit, remaining),
            }
        )
        result = await AIEnrichmentEngine(target_config).run_batches(
            target_id=tid,
            rows=rows_by_target[tid],
            router=router,
            provider_factory=provider_factory,
        )
        total_requests += int(result.get("requests_attempted") or 0)
        if result.get("status") == "cooldown":
            await usage_store.increment_ai_enrichment_usage(today, total_requests)
            await usage_store.set_ai_enrichment_cooldown(
                today,
                AIEnrichmentEngine.cooldown_until(config),
                str(result.get("error") or "rate limited"),
            )
            return {
                "dry_run": False,
                "status": "cooldown",
                "targets": target_ids,
                "requests_attempted": total_requests,
                "updates": total_updates,
                "target_results": target_results,
                "error": result.get("error"),
            }
        updates = list(result.get("updates") or [])
        store = stores_by_target[tid]
        if store is not None:
            for update in updates:
                event_id = str(update.get("event_id") or update.get("id") or "")
                raw_metadata = update.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                if event_id:
                    await store.update_event_metadata(tid, event_id, metadata)
                    ai_meta = metadata.get("ai_enrichment") if isinstance(metadata, dict) else {}
                    await store.record_ai_enrichment_event(
                        tid,
                        event_id,
                        field_hash=ai_meta.get("title_hash") if isinstance(ai_meta, dict) else None,
                        status="completed",
                        model=ai_meta.get("model") if isinstance(ai_meta, dict) else None,
                        route_id=ai_meta.get("route_id") if isinstance(ai_meta, dict) else None,
                    )
        total_updates.extend(updates)
        target_results.append(
            {
                "target_id": tid,
                "status": result.get("status"),
                "requests_attempted": result.get("requests_attempted", 0),
                "updates": len(updates),
            }
        )

    if total_requests:
        await usage_store.increment_ai_enrichment_usage(today, total_requests)
    return {
        "dry_run": False,
        "status": "ok",
        "targets": target_ids,
        "requests_attempted": total_requests,
        "updates": total_updates,
        "target_results": target_results,
    }



def _public_translation_target_ids(target_id: str | None = None) -> list[str]:
    if target_id and target_id != "all":
        return [target_id]
    return [item["target_id"] for item in _load_target_configs() if item.get("target_id")]



async def _public_translation_store_for_target(target_id: str) -> AsyncStore | None:
    target_store = await _get_target_store(target_id)
    return target_store if target_store is not None else _store  # type: ignore[no-any-return]



async def _public_translation_rows_for_target(
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if store is None:
        return []
    list_candidates = getattr(store, "list_public_translation_candidates", None)
    if list_candidates is None:
        return []
    rows = await list_candidates(target_id, limit=limit)
    return list(rows or [])



def _provider_available(provider_name: str) -> bool:
    try:
        provider_factory = _build_ai_provider_factory()
        provider = provider_factory(provider_name)
        return bool(provider is not None and provider.health_check())
    except Exception:  # noqa: BLE001
        return False



def _missing_publication_reason(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or public_publication_ready(metadata):
        return False
    translation = metadata.get("translation")
    publication = metadata.get("publication")
    if not isinstance(translation, dict):
        return False
    title = str(translation.get("title_pre") or "").strip()
    summary = str(translation.get("summary_pre") or "").strip()
    if not title or not summary:
        return False
    if not isinstance(publication, dict):
        return True
    return not str(publication.get("recommendation_reason") or "").strip()



async def _public_translation_status_payload() -> dict[str, Any]:
    config = _current_public_translation_config()
    target_ids = _public_translation_target_ids()
    publication_ready_count = 0
    pending_reason_count = 0
    for tid in target_ids:
        publication_ready_count += await _target_public_event_count(tid, _data_dir)
        store = await _public_translation_store_for_target(tid)
        rows = await _public_translation_rows_for_target(
            tid,
            store,
            limit=min(config.candidate_limit, 1000),
        )
        pending_reason_count += sum(1 for row in rows if _missing_publication_reason(row))
    return {
        "enabled": _public_translation_state["enabled"],
        "running": _public_translation_state["running"],
        "config": _public_translation_config_to_dict(config),
        "publication_ready_count": publication_ready_count,
        "pending_reason_count": pending_reason_count,
        "last_run_at": _public_translation_state.get("last_run_at"),
        "last_run_status": _public_translation_state.get("last_run_status"),
        "last_error": _public_translation_state.get("last_error"),
        "next_run_at": _public_translation_state.get("next_run_at"),
        "total_runs": _public_translation_state["total_runs"],
        "last_updates": _public_translation_state.get("last_updates", 0),
    }



async def _run_public_translation_once(
    *,
    target_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = _current_public_translation_config()
    engine = PublicTranslationEngine(config)
    target_ids = _public_translation_target_ids(target_id)
    stores_by_target: dict[str, AsyncStore | None] = {}
    rows_by_target: dict[str, list[dict[str, Any]]] = {}
    for tid in target_ids:
        store = await _public_translation_store_for_target(tid)
        stores_by_target[tid] = store
        rows_by_target[tid] = await _public_translation_rows_for_target(
            tid,
            store,
            limit=config.candidate_limit,
        )

    if dry_run:
        candidates = [
            {
                "target_id": tid,
                "event_id": row.get("event_id"),
                "title_original": row.get("title_original"),
                "published_at": row.get("published_at"),
                "attempts": row.get("translation_attempts") or 0,
            }
            for tid in target_ids
            for row in rows_by_target[tid]
            if engine.row_is_due(row)
        ][: config.per_cycle_limit]
        return {
            "dry_run": True,
            "targets": target_ids,
            "candidates": candidates,
            "total_candidates": sum(len(rows_by_target[tid]) for tid in target_ids),
        }

    router = _create_ai_provider_router()
    if router is None:
        return {"dry_run": False, "status": "no_router", "targets": target_ids, "updates": []}

    provider_factory = _build_ai_provider_factory()
    total_updates: list[dict[str, Any]] = []
    total_failed = 0
    target_results: list[dict[str, Any]] = []
    for tid in target_ids:
        store = stores_by_target[tid]
        if store is None:
            target_results.append({"target_id": tid, "status": "no_store", "updated": 0})
            continue
        remaining = config.per_cycle_limit - len(total_updates)
        if remaining <= 0:
            break
        target_config = PublicTranslationConfig(
            **{
                **_public_translation_config_to_dict(config),
                "per_cycle_limit": remaining,
            }
        )
        result = await PublicTranslationEngine(target_config).run_rows(
            target_id=tid,
            rows=rows_by_target[tid],
            store=store,
            router=router,
            provider_factory=provider_factory,
        )
        updates = list(result.get("updates") or [])
        total_updates.extend(updates)
        total_failed += int(result.get("failed") or 0)
        target_results.append(
            {
                "target_id": tid,
                "status": result.get("status"),
                "updated": len(updates),
                "failed": int(result.get("failed") or 0),
            }
        )
        if len(total_updates) >= config.per_cycle_limit:
            break

    if total_updates and total_failed:
        status = "partial"
    elif total_updates:
        status = "ok"
    elif total_failed:
        status = "retrying"
    else:
        status = "empty"
    return {
        "dry_run": False,
        "status": status,
        "targets": target_ids,
        "updates": total_updates,
        "failed": total_failed,
        "target_results": target_results,
    }



def _update_collector_run_metrics(contexts: Any) -> None:
    """把多 target pipeline 上下文汇总到采集器状态。"""
    if contexts is None:
        context_items: list[Any] = []
    elif isinstance(contexts, (list, tuple, set)):
        context_items = list(contexts)
    else:
        context_items = [contexts]

    _auto_collector_state["last_events_collected"] = sum(
        int(getattr(ctx, "events_collected", 0) or 0) for ctx in context_items
    )



async def _auto_collect_loop() -> None:
    """后台循环：每隔 interval_minutes 对每个 target 执行 pipeline 阶段。

    通过 NEWSSENTRY_COLLECT_STAGE 控制执行的阶段（默认 collect），
    通过 NEWSSENTRY_TARGET_ID 控制 target 范围（默认 all，逗号分隔或 all）。
    """
    _auto_collector_state["running"] = True
    _log.info(
        "自动采集循环启动: targets=%s, stage=%s, interval=%dmin",
        _auto_collector_state["target_ids"],
        _auto_collector_state["stage"],
        _auto_collector_state["interval_minutes"],
    )

    while _auto_collector_state["enabled"]:
        try:
            from news_sentry.core.async_run import bounded_run_multi_async

            target_ids = _auto_collector_state["target_ids"]
            stage = _auto_collector_state["stage"]
            run_id = f"auto_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            _log.info("自动采集开始: run_id=%s, targets=%s", run_id, target_ids)

            contexts = await bounded_run_multi_async(
                targets=target_ids,
                stage=stage,
                run_id=run_id,
            )
            _update_collector_run_metrics(contexts)

            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "ok"
            _auto_collector_state["last_error"] = None
            _auto_collector_state["total_runs"] += 1
            _log.info("自动采集完成: run_id=%s", run_id)
        except Exception as exc:
            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "error"
            _auto_collector_state["last_error"] = str(exc)
            _auto_collector_state["total_runs"] += 1
            _log.error("自动采集失败", exc_info=True)

        interval = _auto_collector_state["interval_minutes"] * 60
        _auto_collector_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)

    _auto_collector_state["running"] = False
    _auto_collector_state["next_run_at"] = None
    _log.info("自动采集循环停止")



async def _ai_enrichment_loop() -> None:
    """Low-frequency OpenRouter/free-model enrichment loop."""
    _ai_enrichment_state["running"] = True
    _ai_enrichment_log.info(
        "AI 增强循环启动: targets=%s interval=%dmin daily_limit=%d",
        _ai_enrichment_state["targets"],
        _ai_enrichment_state["interval_minutes"],
        _ai_enrichment_state["daily_request_limit"],
    )

    while _ai_enrichment_state["enabled"]:
        interval = int(_ai_enrichment_state["interval_minutes"]) * 60
        _ai_enrichment_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)
        if not _ai_enrichment_state["enabled"]:
            break
        try:
            result = await _run_ai_enrichment_once()
            _ai_enrichment_state["last_run_at"] = datetime.now(UTC).isoformat()
            _ai_enrichment_state["last_run_status"] = result.get("status")
            _ai_enrichment_state["last_error"] = result.get("error")
            _ai_enrichment_state["last_updates"] = len(result.get("updates") or [])
            _ai_enrichment_state["total_runs"] += 1
        except Exception as exc:  # noqa: BLE001
            _ai_enrichment_state["last_run_at"] = datetime.now(UTC).isoformat()
            _ai_enrichment_state["last_run_status"] = "error"
            _ai_enrichment_state["last_error"] = str(exc)
            _ai_enrichment_state["last_updates"] = 0
            _ai_enrichment_state["total_runs"] += 1
            _ai_enrichment_log.error("AI 增强循环失败", exc_info=True)

    _ai_enrichment_state["running"] = False
    _ai_enrichment_state["next_run_at"] = None
    _ai_enrichment_log.info("AI 增强循环停止")



async def _public_translation_loop() -> None:
    """Public translation loop: run immediately, then retry with interval backoff."""
    _public_translation_state["running"] = True
    _public_translation_log.info(
        "公共翻译循环启动: interval=%dmin per_cycle=%d candidates=%d",
        _public_translation_state["interval_minutes"],
        _public_translation_state["per_cycle_limit"],
        _public_translation_state["candidate_limit"],
    )

    while _public_translation_state["enabled"]:
        try:
            result = await _run_public_translation_once()
            _public_translation_state["last_run_at"] = datetime.now(UTC).isoformat()
            _public_translation_state["last_run_status"] = result.get("status")
            _public_translation_state["last_error"] = result.get("error")
            _public_translation_state["last_updates"] = len(result.get("updates") or [])
            _public_translation_state["total_runs"] += 1
        except Exception as exc:  # noqa: BLE001
            _public_translation_state["last_run_at"] = datetime.now(UTC).isoformat()
            _public_translation_state["last_run_status"] = "error"
            _public_translation_state["last_error"] = str(exc)
            _public_translation_state["last_updates"] = 0
            _public_translation_state["total_runs"] += 1
            _public_translation_log.error("公共翻译循环失败", exc_info=True)

        interval = int(_public_translation_state["interval_minutes"]) * 60
        _public_translation_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)

    _public_translation_state["running"] = False
    _public_translation_state["next_run_at"] = None
    _public_translation_log.info("公共翻译循环停止")


