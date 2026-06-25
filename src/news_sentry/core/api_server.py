"""Implements: docs/spec/phase-22-api-gateway.md §1

API Server — FastAPI REST API 网关。

提供:
  - GET /api/v1/targets — 可用 target 列表
  - GET /api/v1/stats — 事件统计
  - GET /api/v1/events — 查询事件列表（支持筛选）
  - GET /api/v1/events/{event_id} — 查询单个事件
  - POST /api/v1/webhook — 接收外部事件（Webhook 入站）
  - POST /api/v1/events/import — 批量导入外部事件
  - GET /api/v1/health — 健康检查
  - GET /docs — OpenAPI/Swagger UI
  - GET / — 前端 Web UI（由静态文件提供）

认证: 用户名+密码登录 → Bearer Token（API Key 向后兼容）。
速率限制: 60 req/min per user。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from pydantic import BeforeValidator, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import news_sentry.core.site_utils as _site_utils_patched  # _static_dir 同步用（create_app 内）
from news_sentry.api.middleware.auth import (
    _PERMISSIONS,
    _TOKEN_STORE,
    _create_persistent_token_for_user,
    _create_stream_token_for_user,
    _create_token_for_user,  # noqa: F401 — re-export for tests
    _extract_bearer_token,
    _get_valid_api_keys,
    _local_auth_bypass_enabled,
    _login_limiter,
    _revoke_sessions_for_username,
    _verify_stream_token,
    _verify_token_async,
    get_current_user,
    require_permission,
)
from news_sentry.api.routes.notifications import init_notifications
from news_sentry.api.routes.notifications import router as ws_router
from news_sentry.api.routes.webhook import init_webhook
from news_sentry.api.routes.webhook import router as webhook_router

# ── Pydantic 模型（已提取至 news_sentry.api.schemas）───
from news_sentry.api.schemas import (
    RESEARCH_REVIEW_DECISIONS,
    AIEnrichmentConfigUpdate,
    AlertHistoryItem,
    AlertHistoryResponse,
    AnnotationCreateRequest,
    AnnotationInfo,
    AnnotationListResponse,
    AnnotationUpdateRequest,
    ArchiveRequest,
    BackupResponse,
    CanonicalBackfillRequest,
    ChainListResponse,
    ChainSummaryInfo,
    CollectorConfigUpdate,
    DailySentimentCount,
    DestinationConfigUpdate,
    DestinationInfo,
    DestinationListResponse,
    EntityDetailResponse,
    EntityListResponse,
    EntityMergeRequest,
    EntityMergeResponse,
    EventChainResponse,
    EventLinksResponse,
    EventResponse,
    FeedbackItem,
    FeedbackListResponse,
    FeedbackStatsResponse,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FilterConfigUpdate,
    FilterRulesResponse,
    HeartbeatResponse,
    ImportEventItem,
    ImportResponse,
    LoginRequest,
    LoginResponse,
    NarrativeResponse,
    NotificationRuleInfo,
    NotificationRuleListResponse,
    NotificationRuleRequest,
    ProviderRoutesResponse,
    PruneResponse,
    PublicAnalysisResponse,
    PublicBootstrapResponse,
    PublicFacetsResponse,
    PublicNewsFeedResponse,
    PublicNewsItem,
    PublicTranslationConfigUpdate,
    RegionListResponse,
    ResearchArtifactCreateRequest,
    ResearchArtifactPatchRequest,
    ResearchGraphMergeRequest,
    ResearchGraphSplitRequest,
    RouteConfigUpdate,
    RouteInfo,
    RulesOptimizeRequest,
    RulesOptimizeResponse,
    RunDetailResponse,
    RunInfo,
    RunListResponse,
    SentimentTrendsResponse,
    SmartAlertItem,
    SmartAlertsResponse,
    SocialAccountCreateRequest,
    SocialAccountPatchRequest,
    SocialDimensionCreateRequest,
    SocialDimensionPatchRequest,
    SourceConfigUpdate,
    SourceCreateRequest,
    SourceHealthInfo,
    SourceHealthListResponse,
    SourceInfo,
    SourceListResponse,
    SourcePatchRequest,
    StatsResponse,
    TargetConfigUpdate,
    TargetCreateRequest,
    TargetListResponse,
    TargetPatchRequest,
    TodayStatsResponse,
    TopEventInfo,
    TopEventsResponse,
    TopicTrendItem,
    TopicTrendsResponse,
    TransitionEventRequest,
    TransitionEventResponse,
    TriggerResponse,
    WebhookPayload,
    WebhookResponse,
)
from news_sentry.api.ws_manager import ConnectionManager

# ── 共享状态 ─────────────────────────────────────────
from news_sentry.core._state import (
    _HTTP_PHRASES,
    _REGION_TYPES,
    _ai_enrichment_state,
    _auto_collector_state,
    _public_translation_state,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.auth import hash_password, verify_password

# ── 从辅助模块导入（从 api_server.py 提取）──────────────────────
from news_sentry.core.collector_config_utils import (
    _ai_enrichment_config_to_dict,
    _ai_enrichment_loop,
    _ai_enrichment_status_payload,
    _apply_ai_enrichment_config,
    _apply_collector_config,
    _apply_public_translation_config,
    _auto_collect_loop,
    _cached_collector_diagnostics_payload,
    _collector_payload,
    _current_ai_enrichment_config,
    _current_public_translation_config,
    _load_ai_enrichment_config,
    _load_collector_config,
    _load_public_translation_config,
    _parse_target_ids,
    _public_translation_config_to_dict,
    _public_translation_loop,
    _public_translation_status_payload,
    _run_ai_enrichment_once,
    _run_public_translation_once,
    _save_ai_enrichment_config,
    _save_collector_config,
    _save_public_translation_config,
    _update_collector_run_metrics,  # noqa: F401 re-exported for test access
)
from news_sentry.core.config_cache import ConfigCache
from news_sentry.core.event_bus import EventBus
from news_sentry.core.event_io_utils import (
    _archive_duplicate_drafts,
    _draft_diagnostics,
    _load_all_events,
    _load_event_by_id_from_stage,  # noqa: F401 re-exported for test & runtime access
    _load_indexed_event_detail,
    _load_indexed_event_frontmatter,  # noqa: F401 re-exported for test & runtime access
    _load_single_event,
    _markdown_download_response,
    _save_webhook_event,
)
from news_sentry.core.public_news_utils import (
    _classification_diagnostics_from_events,
    _classification_diagnostics_from_store,
    _clear_admin_caches,
    _feed_event_payload,
    _public_news_target_ids,  # noqa: F401 re-exported for test access
    _public_projection_event,  # noqa: F401 re-exported for test access
    _row_publication_ready,  # noqa: F401 re-exported for test access
)
from news_sentry.core.site_utils import (
    _git_commit_for_path,
    _index_html_response,
    _mount_spa_routes,
    _public_app_asset_response,
    _public_app_index_response,
    _public_discoverability_text,
    _public_site_base_url,
    _render_public_sitemap_xml,
    _static_build_hash,
    _static_dir,
)
from news_sentry.core.source_inventory import (
    SourceInventoryService,  # noqa: F401 re-exported for test access
)
from news_sentry.core.target_config_utils import (
    _append_source_ref,
    _atomic_write_yaml,
    _build_source_config,
    _cached_source_inventory,
    _cached_target_validation,
    _config_base_dir,
    _copy_target_config_skeleton,
    _deep_merge,
    _default_classification_config,
    _default_filter_config,
    _default_template_source,
    _ensure_global_config_defaults,
    _ensure_target_exists,
    _filter_source_health_records,
    _find_social_dimension_path,
    _load_memory_source_health_records,
    _load_single_source,
    _load_source_configs,
    _load_target_configs,
    _load_yaml_file,
    _normalize_source_ref,
    _social_dimensions,
    _source_config_path,
    _source_info_from_config,
    _source_is_archived,
    _source_is_standard,
    _stop_target_in_collector_config,
    _target_api_event_count,
    _target_config_path,
    _target_info_from_config,
    _target_info_from_config_for_response,
    _target_is_archived,
    _target_lifecycle,
    _target_region_type,
    _template_target_config,
    _validate_source_slug,
    _validate_target_config,  # noqa: F401 re-exported for test & runtime access
    _validate_target_slug,
)
from news_sentry.core.target_store_utils import (
    _get_target_store,
    _load_run_logs,
    _visible_index_event_from_row,  # noqa: F401 re-exported for test access
    _visible_index_events_page,
)
from news_sentry.skills.filter.classification_taxonomy import (
    canonical_l0,
    l0_query_values,
)

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    ),
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://cloudflareinsights.com https://static.cloudflareinsights.com; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "object-src 'none'"
    ),
}










_PUBLIC_SITE_BASE_URL = "https://news-sentry.com"
_PUBLIC_SITE_NAME = "News Sentry"
_PUBLIC_SITE_TITLE = "News Sentry | 新闻哨兵"
_PUBLIC_SITE_DESCRIPTION = (
    "News Sentry 新闻哨兵面向中文读者追踪全球新闻，按地区、议题和相关对象筛选重点事件，"
    "提供中文摘要、原文标题、信源信息与 Breaking News 指数。"
)

# ── FastAPI 认证依赖 ───────────────────────────────────

_store: AsyncStore | None = None
_target_stores: dict[str, AsyncStore] = {}  # target_id → state.db 缓存
_deployment_env: str = ""  # cloudflare|hetzner|docker|local|unknown
_skip_lifespan: bool = False  # 测试时跳过 lifespan 异步操作（避免 aiosqlite 跨 loop 挂起）
_data_dir: Path = Path(os.environ.get("NEWSSENTRY_DATA_DIR", "./data"))
_OVERVIEW_CACHE_TTL_SECONDS = 15.0
_source_inventory_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_PUBLIC_SOURCE_CONFIG_CACHE_TTL_SECONDS = 60.0
_public_source_configs_cache: dict[tuple[str, str], dict[str, Any]] = {}
_target_validation_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_collector_diagnostics_cache: dict[str, Any] = {}

# SSE 实时推送 — 每个 target_id 对应一组客户端队列
# 当新事件到达时，通知所有监听该 target 的 SSE 连接
_sse_queues: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)
_sse_lock = asyncio.Lock()


async def _notify_sse_clients(target_id: str, event: str, payload: dict[str, Any]) -> None:
    """向指定 target 的所有 SSE 客户端推送消息。"""
    async with _sse_lock:
        queues = _sse_queues.get(target_id, [])
        for q in queues:
            await q.put({"event": event, "payload": payload})


logger = logging.getLogger(__name__)


# InvisibleIndexedEvent / _INVISIBLE_INDEXED_EVENT imported from news_sentry.core._state


async def _read_json_object(request: Request) -> dict[str, Any]:
    """读取 JSON object body，并把空/非法 JSON 转成 400。"""
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    return cast(dict[str, Any], body)


def _load_single_run_log(
    data_dir: Path,
    run_id: str,
    target_id: str,
) -> dict[str, Any] | None:
    """读取单个运行日志详情。"""
    log_dir = data_dir / target_id / "logs"
    if not log_dir.is_dir():
        return None
    for f in log_dir.glob("*.json"):
        if run_id in f.name:
            try:
                data: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
                return data
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _load_heartbeat(
    data_dir: Path,
    target_id: str,
) -> dict[str, Any]:
    """读取心跳文件。"""
    hb_path = data_dir / target_id / "logs" / ".heartbeat-hermes.json"
    if not hb_path.is_file():
        return {"active": False}
    try:
        data = json.loads(hb_path.read_text(encoding="utf-8"))
        return {
            "active": data.get("status") == "running",
            "run_id": data.get("run_id", ""),
            "last_stage": data.get("last_stage", ""),
            "last_at": data.get("last_at", ""),
            "status": data.get("status", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {"active": False}


# ── 事件存储读取 ────────────────────────────────────────


def _load_events_from_data(
    data_dir: Path,
    target_id: str,
    page: int,
    page_size: int,
    classification: str | None = None,
    source_id: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
) -> EventResponse:
    """从 data/{target_id}/drafts/ 读取事件列表，支持筛选。"""
    events = _load_all_events(data_dir, target_id)

    # 筛选
    if classification is not None:
        accepted = l0_query_values(classification)
        events = [
            e
            for e in events
            if isinstance(e.get("classification"), dict)
            and canonical_l0(e["classification"].get("l0")) in accepted
        ]
    if source_id is not None:
        events = [e for e in events if e.get("source_id") == source_id]
    if min_score is not None:
        events = [
            e
            for e in events
            if isinstance(e.get("news_value_score"), (int, float))
            and e["news_value_score"] >= min_score
        ]
    if search is not None:
        keyword = search.lower()
        events = [e for e in events if keyword in (e.get("title_original") or "").lower()]

    # 分页
    start = (page - 1) * page_size
    page_events = events[start : start + page_size]

    return EventResponse(
        total=len(events),
        events=page_events,
        page=page,
        page_size=page_size,
    )


def _group_events_by_date(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将事件列表按 published_at 日期分组。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        pub = ev.get("published_at", "")
        date_key = pub[:10] if pub else "unknown"
        if date_key not in groups:
            groups[date_key] = []
        groups[date_key].append(ev)
    # 按日期降序排列
    result = []
    for date_key in sorted(groups.keys(), reverse=True):
        deduped = _dedupe_feed_events(groups[date_key])
        result.append({"date": date_key, "events": [_feed_event_payload(ev) for ev in deduped]})
    return result


def _feed_dedupe_key(ev: dict[str, Any]) -> str:
    story_id = ev.get("story_id")
    if story_id:
        return f"story:{story_id}"
    cluster_id = ev.get("cluster_id")
    if cluster_id:
        return f"cluster:{cluster_id}"
    title = str(ev.get("title_translated") or ev.get("title_original") or "").strip().lower()
    normalized = re.sub(r"\W+", " ", title, flags=re.UNICODE).strip()
    if normalized:
        return f"title:{normalized}"
    return f"event:{ev.get('event_id') or ev.get('id') or uuid.uuid4().hex}"


def _dedupe_feed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate story mentions for public feed display without deleting data."""
    deduped: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for event in events:
        key = _feed_dedupe_key(event)
        if key not in by_key:
            item = dict(event)
            item["related_count"] = int(item.get("related_count") or 0)
            by_key[key] = item
            deduped.append(item)
            continue
        kept = by_key[key]
        kept["related_count"] = (
            int(kept.get("related_count") or 0) + 1 + int(event.get("related_count") or 0)
        )
    return deduped


async def _store_has_target_event_index(store: Any, target_id: str) -> bool:
    get_count = getattr(store, "get_target_event_count", None)
    if get_count is None:
        return False
    count = await get_count(target_id)
    return int(count or 0) > 0




_PUBLIC_NEWS_STAGE = "drafts"
_PUBLIC_NEWS_DEFAULT_PAGE_SIZE = 30
_PUBLIC_NEWS_MAX_PAGE_SIZE = 100
_PUBLIC_NEWS_MIN_SCAN = 80
_PUBLIC_NEWS_MAX_SCAN = 300
_PUBLIC_NEWS_MIN_POLL_AFTER_MS = 30_000
_PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS = 60_000
_PUBLIC_NEWS_IDLE_POLL_AFTER_MS = 180_000
_PUBLIC_NEWS_FEATURED_SCORE = 60
_PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS = 60.0  # 从 15s 延长到 60s，减轻源站负担
_PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS = 60.0  # since_cursor 轮询也受益
_PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS = 5.0  # 搜索仍保留短 TTL
_PUBLIC_SHARED_JSON_CACHE_CONTROL = "public, max-age=30, s-maxage=60, stale-while-revalidate=300"
_PUBLIC_APP_SHELL_CACHE_CONTROL = "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
_PUBLIC_BOOTSTRAP_CACHE_TTL_SECONDS = 300.0
_PUBLIC_BOOTSTRAP_CACHE_CONTROL = "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
_PUBLIC_REGIONS_CACHE_TTL_SECONDS = 60
_PUBLIC_FACETS_CACHE_TTL_SECONDS = 60
_PUBLIC_NEWS_SLOW_LOG_MS = 3000
_PUBLIC_NEWS_INTERNAL_DATA_DIRS = {
    "backup",
    "cache",
    "eval",
    "locks",
    "logs",
    "memory",
    "tmp",
}
_PUBLIC_NEWS_EVENT_DIRS = {
    "archive",
    "drafts",
    "evaluated",
    "published",
    "raw",
    "reviewed",
}
_public_news_feed_cache: dict[str, dict[str, Any]] = {}
_public_regions_cache: dict[str, dict[str, Any]] = {}
_public_facets_cache: dict[str, dict[str, Any]] = {}
_admin_overview_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_admin_targets_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_ADMIN_CACHE_TTL_SECONDS = 15.0




_public_bootstrap_cache: dict[str, dict[str, Any]] = {}




_PUBLIC_ANALYSIS_STAGE = "drafts"
_PUBLIC_ANALYSIS_CHAIN_LIMIT = 10















_log = logging.getLogger("news_sentry.auto_collector")
_ai_enrichment_log = logging.getLogger("news_sentry.ai_enrichment")
_public_translation_log = logging.getLogger("news_sentry.public_translation")

_COLLECTOR_STAGES = {"all", "collect", "filter", "judge", "output"}


async def _bootstrap_users() -> None:
    """确保至少存在一个管理员用户。"""
    if _store is None:
        return
    users = await _store.list_users()
    if users:
        return
    admin_user = os.environ.get("NEWSSENTRY_ADMIN_USER", "admin")
    admin_pass = os.environ.get("NEWSSENTRY_ADMIN_PASSWORD", "")
    api_key = os.environ.get("NEWSSENTRY_API_KEY", "").split(",")[0].strip() or None
    if not admin_pass:
        admin_pass = secrets.token_urlsafe(16)
        logger.warning("Generated admin password (first launch): %s", admin_pass)
    pw_hash, salt = hash_password(admin_pass)
    await _store.create_user(
        username=admin_user,
        password_hash=pw_hash,
        salt=salt,
        role="admin",
        api_key=api_key,
        must_change_pw=0 if os.environ.get("NEWSSENTRY_ADMIN_PASSWORD") else 1,
    )
    logger.info("Bootstrapped admin user: %s", admin_user)


def _detect_deployment_env() -> str:
    """检测部署环境。

    优先级：NEWSSENTRY_DEPLOYMENT_ENV > CF_ACCOUNT_ID 存在判断 > Docker 判断 > local。
    返回: cloudflare | hetzner | docker | local | unknown
    """
    global _deployment_env
    if _deployment_env:
        return _deployment_env

    env = os.environ.get("NEWSSENTRY_DEPLOYMENT_ENV", "").strip().lower()
    if env:
        _deployment_env = env
        logger.info("Deployment env (explicit): %s", env)
        return env

    # 自动检测
    if os.environ.get("CF_ACCOUNT_ID"):
        _deployment_env = "cloudflare"
    elif (
        os.path.exists("/.dockerenv") or "docker" in (os.environ.get("container", "") or "").lower()
    ):
        _deployment_env = "docker"
    else:
        _deployment_env = "local"

    logger.info("Deployment env (detected): %s", _deployment_env)
    return _deployment_env


async def _close_target_stores() -> None:
    """关闭按 target 缓存的 AsyncStore，避免 lifespan 结束后残留连接。"""
    stores = list(_target_stores.values())
    _target_stores.clear()
    for store in stores:
        try:
            await store.close()
        except Exception:  # noqa: S110
            pass


def _close_store_sync_if_possible(store: Any) -> None:
    if not isinstance(store, AsyncStore) or store._db is None:  # noqa: SLF001
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(store.close())


async def _source_health_records_for_target(target_id: str) -> list[dict[str, Any]]:
    """按优先级读取 target 信源健康：target SQLite、全局 SQLite、真实 memory YAML。"""
    records: list[dict[str, Any]] = []
    target_store = await _get_target_store(target_id)
    if target_store is not None:
        records = await target_store.get_all_source_health()
    if not records and _store is not None:
        records = await _store.get_all_source_health()
    if not records:
        records = _load_memory_source_health_records(target_id)
    return _filter_source_health_records(target_id, records)


async def _store_for_target(target_id: str) -> AsyncStore | None:
    """优先返回 target state.db；没有时退回全局 store。"""
    target_store = await _get_target_store(target_id)
    return target_store if target_store is not None else _store


def _research_graph_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 422
    return HTTPException(status_code=status_code, detail=detail)


def _validate_research_metadata(artifact_type: str, metadata: dict[str, Any]) -> None:
    """校验 research artifact metadata 中的人工决策契约。"""
    decision = metadata.get("decision")
    if artifact_type == "review_state" and decision not in RESEARCH_REVIEW_DECISIONS:
        raise HTTPException(status_code=422, detail="Unsupported review decision")
    if artifact_type == "merge_decision":
        if decision != "proposed":
            raise HTTPException(status_code=422, detail="Unsupported merge decision")
        _require_non_empty_string_list(
            metadata,
            "candidate_canonical_event_ids",
            "merge_decision requires candidate IDs",
        )
    if artifact_type == "split_decision":
        if decision != "proposed":
            raise HTTPException(status_code=422, detail="Unsupported split decision")
        _require_non_empty_string_list(
            metadata,
            "affected_mention_ids",
            "split_decision requires affected mentions",
        )


def _require_non_empty_string_list(
    metadata: dict[str, Any],
    field_name: str,
    detail: str,
) -> list[str]:
    values = metadata.get(field_name)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value.strip() for value in values)
    ):
        raise HTTPException(status_code=422, detail=detail)
    return values


def _safe_research_artifact_id_part(value: str, fallback: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-") or fallback


def _stable_research_metadata_key(artifact_type: str, metadata: dict[str, Any]) -> str:
    if artifact_type == "merge_decision":
        candidates = sorted(
            _require_non_empty_string_list(
                metadata,
                "candidate_canonical_event_ids",
                "merge_decision requires candidate IDs",
            )
        )
        return json.dumps({"candidate_canonical_event_ids": candidates}, sort_keys=True)
    if artifact_type == "split_decision":
        mentions = sorted(
            _require_non_empty_string_list(
                metadata,
                "affected_mention_ids",
                "split_decision requires affected mentions",
            )
        )
        return json.dumps({"affected_mention_ids": mentions}, sort_keys=True)
    return "review_state"


def _new_research_artifact_id(
    target_id: str,
    artifact_type: str,
    subject_id: str,
    metadata: dict[str, Any],
) -> str:
    safe_target = _safe_research_artifact_id_part(target_id, "target")
    safe_type = _safe_research_artifact_id_part(artifact_type, "artifact")
    if artifact_type in {"review_state", "merge_decision", "split_decision"}:
        identity = {
            "target_id": target_id,
            "artifact_type": artifact_type,
            "subject_type": "canonical_event",
            "subject_id": subject_id,
            "metadata_key": _stable_research_metadata_key(artifact_type, metadata),
        }
        digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        return f"ra_{safe_target}_{safe_type}_{digest}"
    return f"ra_{safe_target}_{safe_type}_{uuid.uuid4().hex[:12]}"


async def _restore_sessions() -> None:
    """启动时清理过期 session。活跃 token 通过请求时 SQLite 回退恢复。"""
    if _store is None:
        return
    deleted = await _store.delete_expired_sessions()
    if deleted:
        logger.info("清理过期 session: %d 条", deleted)



# R2: WebSocket/EventBus 模块级句柄（在 lifespan 内外共享）
_event_bus: EventBus | None = None
_ws_manager: ConnectionManager | None = None
_ws_sub_id: str | None = None


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """FastAPI lifespan: 启动引导 + 后台采集循环。"""
    global _store
    if _store is not None and not _skip_lifespan:
        await _store.initialize()
        await _bootstrap_users()
        await _restore_sessions()
    task = None
    ai_task = None
    translation_task = None
    if _auto_collector_state["enabled"] and not _skip_lifespan:
        task = asyncio.create_task(_auto_collect_loop())
        _auto_collector_state["task"] = task
    if _ai_enrichment_state["enabled"] and not _skip_lifespan:
        ai_task = asyncio.create_task(_ai_enrichment_loop())
        _ai_enrichment_state["task"] = ai_task
    if _public_translation_state["enabled"] and not _skip_lifespan:
        translation_task = asyncio.create_task(_public_translation_loop())
        _public_translation_state["task"] = translation_task

    # R2: EventBus + ConnectionManager 初始化
    global _event_bus, _ws_manager, _ws_sub_id  # noqa: PLW0603

    _event_bus = EventBus()
    _ws_manager = ConnectionManager()
    _ws_sub_id = None
    if not _skip_lifespan:
        try:
            from news_sentry.api.routes.notifications import _handle_alert

            _ws_sub_id = await _event_bus.subscribe("alert.triggered.browser", _handle_alert)
            init_notifications(_ws_manager, _event_bus)
            init_webhook(_data_dir, _event_bus)
            logger.info("R2 EventBus + ConnectionManager 已就绪")
        except Exception as exc:
            logger.warning("R2 初始化失败（非阻塞）: %s", exc)

    yield
    if task is not None:
        _auto_collector_state["enabled"] = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if ai_task is not None:
        _ai_enrichment_state["enabled"] = False
        ai_task.cancel()
        try:
            await ai_task
        except asyncio.CancelledError:
            pass
    if translation_task is not None:
        _public_translation_state["enabled"] = False
        translation_task.cancel()
        try:
            await translation_task
        except asyncio.CancelledError:
            pass
    if _store is not None:
        await _store.close()
        _store = None
        from news_sentry.api.middleware.auth import configure as _auth_configure

        _auth_configure(None)
    # R2: EventBus 清理
    try:
        if _ws_sub_id is not None:
            await _event_bus.unsubscribe(_ws_sub_id)
            logger.info("R2 EventBus 订阅已取消")
    except Exception as exc:
        logger.warning("R2 清理失败（非阻塞）: %s", exc)

    await _close_target_stores()


# ── FastAPI 应用 ────────────────────────────────────────


def _http_status_phrase(status_code: int) -> str:
    return _HTTP_PHRASES.get(status_code, f"HTTP {status_code}")


def create_app(
    data_dir: str | Path | None = None,
    store: AsyncStore | None = None,
    auto_store: bool = True,
    skip_lifespan: bool = False,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        data_dir: 数据根目录，默认 ./data。
        store: AsyncStore 实例（Phase 28 新增，用于 SQLite 查询）。
        auto_store: 无传入 store 时自动创建（Cloudflare/生产=True，测试=False）。
        skip_lifespan: 跳过 lifespan 中的异步初始化（测试场景，避免 aiosqlite 跨 loop 挂起）。
    """
    global _skip_lifespan
    _skip_lifespan = skip_lifespan

    app = FastAPI(
        title="News Sentry API",
        version="0.1.0",
        description="News Sentry REST API — 事件查询、统计、Webhook 入站",
        lifespan=_app_lifespan,
    )

    # CORS 中间件 — 从环境变量读取允许的源
    from fastapi.middleware.cors import CORSMiddleware

    allowed_origins = [
        o.strip()
        for o in os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000",
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # ── 全局异常处理器 ────────────────────────────────

    def _build_error_response(
        status_code: int, detail: str, extra: dict[str, Any] | None = None
    ) -> JSONResponse:
        """构建统一错误响应 JSON。"""
        headers: dict[str, str] = {}
        if status_code in (401, 403):
            reason_map = {401: "missing_or_invalid_token", 403: "insufficient_permission"}
            headers.setdefault(
                "X-News-Sentry-Auth-Reason",
                reason_map.get(status_code, "forbidden"),
            )
        if status_code >= 500:
            headers.setdefault("X-News-Sentry-Error-Level", "critical")

        body: dict[str, Any] = {
            "error": _http_status_phrase(status_code),
            "detail": detail,
            "status_code": status_code,
        }
        if extra:
            body.update(extra)
        return JSONResponse(status_code=status_code, content=body, headers=headers)

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """将 FastAPI HTTPException 转为统一错误 JSON 格式。"""
        return _build_error_response(
            exc.status_code,
            str(exc.detail),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _build_error_response(
            exc.status_code,
            str(exc.detail),
        )

    @app.exception_handler(ValidationError)
    async def _validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
        """Pydantic 请求体验证失败 → 422 统一格式。"""
        errors = exc.errors(include_url=False)
        return _build_error_response(
            422,
            "Request validation failed",
            {"validation_errors": errors},
        )

    @app.exception_handler(Exception)
    async def _catchall_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """捕获未预见的异常 → 500 统一格式（生产环境不泄露 traceback）。"""
        import logging
        import traceback

        logger = logging.getLogger("news_sentry.api")
        logger.error(
            "Unhandled exception on %s %s: %s\n%s",
            request.method,
            request.url.path,
            exc,
            traceback.format_exc(),
        )

        return _build_error_response(500, "An unexpected error occurred")

    global _store, _data_dir
    import news_sentry.core._state as _state_mod
    if _store is not None and _store is not store:
        _close_store_sync_if_possible(_store)
    if _target_stores:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_close_target_stores())
    _data_dir = Path(data_dir or os.environ.get("NEWSSENTRY_DATA_DIR", "./data"))
    _state_mod._data_dir = _data_dir  # 同步到 _state 模块（供 target_store_utils 等使用）
    _state_mod._target_stores.clear()
    _state_mod._target_stores.update(_target_stores)  # 原位更新避免 from-import 失效
    _public_news_feed_cache.clear()
    _public_source_configs_cache.clear()
    _detect_deployment_env()
    if store is not None:
        _store = store
        _state_mod._store = _store  # 同步到 _state 模块（供 collector_config_utils 等使用）
        # 同步到 auth middleware
        from news_sentry.api.middleware.auth import configure as _auth_configure

        _auth_configure(store)
    elif _store is None and auto_store:
        _store = AsyncStore(_data_dir / "async_store.db")
        _state_mod._store = _store  # 同步到 _state 模块
        from news_sentry.api.middleware.auth import configure as _auth_configure

        _auth_configure(_store)
        # 确保 SQLite 连接在端点接收请求前就绪。
        # 生产环境（uvicorn）下生命周期会调用 initialize()，此处仅
        # 在没有运行中事件循环时（如某些测试场景）做同步初始化兜底。
        if _store._db is None:
            try:
                asyncio.get_running_loop()
                # 事件循环已运行（uvicorn），由生命周期处理初始化。
            except RuntimeError:
                asyncio.run(_store.initialize())
                # atexit: CLI 单次调用场景关闭 aiosqlite 连接，防止进程挂起
                import atexit as _atexit

                _s = _store

                def _cleanup() -> None:
                    try:
                        if _s._db is not None:
                            asyncio.run(_s.close())
                    except Exception:  # noqa: S110
                        pass

                _atexit.register(_cleanup)
    elif not auto_store:
        _store = None  # 显式禁用，测试环境重置
        _state_mod._store = None  # 同步到 _state 模块
        from news_sentry.api.middleware.auth import configure as _auth_configure

        _auth_configure(None)
    _config_cache = ConfigCache(ttl=60, maxsize=128)

    # 用 env 推导的默认值填充 _auto_collector_state
    # _apply_collector_config 会进一步从 YAML 细化运行参数
    _auto_collector_state.update({
        "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
        "target_ids": _parse_target_ids(
            os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "all"))
        ),
        "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "2")),
        "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),
        "running": False,
        "last_run_at": None,
        "last_run_status": None,
        "last_events_collected": 0,
        "last_error": None,
        "next_run_at": None,
        "total_runs": 0,
        "task": None,
    })
    _apply_collector_config(_load_collector_config())
    _apply_ai_enrichment_config(_load_ai_enrichment_config())
    _apply_public_translation_config(_load_public_translation_config())
    _state_mod._deployment_env = _deployment_env

    # 同步 _static_dir 到 site_utils：使测试 monkeypatch api_server._static_dir 也能
    # 影响 site_utils._static_dir，从而影响 _public_app_index_response 等函数。
    # 需在每次 create_app() 调用时同步，因为 monkeypatch 在调用前才设置。
    import sys as _sys
    _api_server_mod = _sys.modules[__name__]
    _site_utils_patched._static_dir = _api_server_mod._static_dir

    # 同步 _store_for_target / _store_has_target_event_index / _visible_index_events_page
    # 到 event_io_utils 模块。event_io_utils 用 None 占位初始化，这些函数定义在
    # api_server 或 target_store_utils 中，需要在 create_app() 时同步过去，
    # 避免调用时 'NoneType' object is not callable。
    _event_io_mod = cast(Any, _sys.modules.get("news_sentry.core.event_io_utils"))
    if _event_io_mod is not None:
        _event_io_mod._store_for_target = _store_for_target
        _event_io_mod._store_has_target_event_index = _store_has_target_event_index
        _event_io_mod._visible_index_events_page = _visible_index_events_page
        _event_io_mod._validate_target_slug = _validate_target_slug

    _public_news_mod = cast(Any, _sys.modules.get("news_sentry.core.public_news_utils"))
    if _public_news_mod is not None:
        _public_news_mod._get_target_store = _get_target_store
        _public_news_mod._store_has_target_event_index = _store_has_target_event_index
        _public_news_mod._visible_index_events_page = _visible_index_events_page

    _tcu_mod = cast(Any, _sys.modules.get("news_sentry.core.target_config_utils"))
    if _tcu_mod is not None:
        _tcu_mod._store_for_target = _store_for_target

    _site_mod = cast(Any, _sys.modules.get("news_sentry.core.site_utils"))
    if _site_mod is not None:
        from news_sentry.core.public_site_projection import (
            PublicSiteProjectionStore as _PublicSiteProjectionStore,
        )
        from news_sentry.core.public_site_projection import (
            SitemapEntry as _SitemapEntry,
        )
        _site_mod._get_target_store = _get_target_store
        _site_mod.SitemapEntry = _SitemapEntry
        _site_mod.PublicSiteProjectionStore = _PublicSiteProjectionStore

    # ── 公开端点（无需认证）─────────────────────────────

    async def health(response: Response) -> dict[str, Any]:
        build = _static_build_hash()
        commit = _git_commit_for_path(Path(__file__))
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-News-Sentry-Deploy-Commit"] = (
            commit[:12] if commit != "unknown" else commit
        )
        response.headers["X-News-Sentry-Static-Build"] = build

        # ── 数据新鲜度 ──
        latest_collected_at: str | None = None
        total_events: int = 0
        if _store is not None and _store._db is not None:
            try:
                async with _store._db.execute(
                    "SELECT MAX(collected_at), COUNT(*) FROM event_index"
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    latest_collected_at = row[0]
                    total_events = row[1] or 0
            except Exception:  # noqa: S110 — 数据新鲜度查询失败时静默回退
                pass

        return {
            "status": "ok",
            "total_events": total_events,
            "latest_collected_at": latest_collected_at,
        }

    async def global_diagnostics(
        response: Response,
    ) -> dict[str, Any]:
        """全局可观测性诊断摘要（公开，聚合所有 target）。

        无需认证，汇总采集器状态、数据目录、最后采集、信源健康、
        事件总数等关键指标，用于快速定位"无数据"、"采集卡死"等问题。
        """
        response.headers["Cache-Control"] = "no-store"
        build = _static_build_hash()
        commit = _git_commit_for_path(Path(__file__))

        # ── 采集器状态 ──
        collector = _collector_payload()

        # ── AI Key ──
        has_ai_key = bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("GROQ_API_KEY")
        )

        # ── 数据目录与 target 列表 ──
        data_exists = _data_dir.exists()
        target_dirs = (
            sorted([d.name for d in _data_dir.iterdir() if d.is_dir()]) if data_exists else []
        )

        # ── 信源健康 ──
        healthy_sources = 0
        unhealthy_sources = 0
        if data_exists:
            for tid in target_dirs:
                memory_health = _filter_source_health_records(
                    tid,
                    _load_memory_source_health_records(tid),
                )
                if memory_health:
                    for item in memory_health:
                        if item.get("status") == "healthy":
                            healthy_sources += 1
                        else:
                            unhealthy_sources += 1
                    continue
                health_file = _data_dir / tid / "source_health.json"
                if health_file.exists():
                    try:
                        health_data = json.loads(health_file.read_text())
                        items = health_data if isinstance(health_data, list) else []
                        for item in items:
                            if item.get("healthy"):
                                healthy_sources += 1
                            else:
                                unhealthy_sources += 1
                    except Exception:  # noqa: S110
                        pass

        # ── 事件总数 ──
        total_events: int = 0
        latest_collected_at: str | None = None
        if _store is not None and _store._db is not None:
            try:
                async with _store._db.execute(
                    "SELECT MAX(collected_at), COUNT(*) FROM event_index"
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    latest_collected_at = row[0]
                    total_events = row[1] or 0
            except Exception:  # noqa: S110
                pass

        # ── 最新运行 ──
        recent_runs: list[dict[str, Any]] = []
        if target_dirs:
            recent_runs = _load_run_logs(_data_dir, target_dirs[0], 5)

        return {
            "deploy": {
                "commit": commit[:12] if commit != "unknown" else commit,
                "build": build,
            },
            "collector": {
                "enabled": collector["enabled"],
                "running": collector["running"],
                "last_run_at": collector.get("last_run_at"),
                "next_run_at": collector.get("next_run_at"),
            },
            "ai_key_configured": has_ai_key,
            "data": {
                "directory": str(_data_dir),
                "target_count": len(target_dirs),
                "targets": target_dirs,
            },
            "source_health": {
                "healthy": healthy_sources,
                "unhealthy": unhealthy_sources,
                "total": healthy_sources + unhealthy_sources,
            },
            "events": {
                "total": total_events,
                "latest_collected_at": latest_collected_at,
            },
            "recent_runs": recent_runs[:5],
        }

    async def prometheus_metrics(
        response: Response,
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> PlainTextResponse:
        """Prometheus-compatible metrics endpoint (auth-required)."""
        import platform as _platform
        import time as _time

        lines: list[str] = []
        build = _static_build_hash()

        # Application info
        lines.append("# HELP news_sentry_info Application metadata")
        lines.append("# TYPE news_sentry_info gauge")
        lines.append(f'news_sentry_info{{version="2.0.0", build="{build}"}} 1')

        # Uptime
        lines.append("# HELP news_sentry_uptime_seconds Process uptime")
        lines.append("# TYPE news_sentry_uptime_seconds gauge")
        lines.append(f"news_sentry_uptime_seconds {_time.monotonic():.1f}")

        # Python version
        lines.append("# HELP news_sentry_python_info Python version")
        lines.append("# TYPE news_sentry_python_info gauge")
        lines.append(f'news_sentry_python_info{{version="{_platform.python_version()}"}} 1')

        # Auto-collector status
        auto_enabled = 1 if os.environ.get("NEWSSENTRY_AUTO_COLLECT", "") == "1" else 0
        lines.append("# HELP news_sentry_auto_collect_enabled Auto-collector status")
        lines.append("# TYPE news_sentry_auto_collect_enabled gauge")
        lines.append(f"news_sentry_auto_collect_enabled {auto_enabled}")

        response.headers["Cache-Control"] = "no-store"
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")

    async def runtime_info(
        response: Response,
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        build = _static_build_hash()
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "static_build": build,
        }

    # ── 静态资源 / SPA 前端路由 ──────

    async def index_html(request: Request) -> HTMLResponse:  # type: ignore[no-redef]
        return _public_app_index_response(
            base_url=_public_site_base_url(request),
            canonical_path="/",
        )

    async def publication_reader_page(request: Request) -> HTMLResponse:  # type: ignore[no-redef]
        return _public_app_index_response(
            base_url=_public_site_base_url(request),
            canonical_path=request.url.path,
        )

    async def admin_index_html() -> HTMLResponse:  # type: ignore[no-redef]
        return _index_html_response()

    async def admin_path_html(path: str) -> Response:  # type: ignore[no-redef]
        # Serve static assets (JS/CSS/images) directly; everything else is an SPA fallback
        admin_root = _static_dir() / "admin"
        clean_path = path.strip("/")
        file_path = (admin_root / clean_path).resolve()
        try:
            file_path.relative_to(admin_root.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="Static asset not found") from None
        if file_path.is_file():
            cache_control = (
                "public, max-age=31536000, immutable"
                if clean_path.startswith("assets/")
                else "no-store"
            )
            return FileResponse(file_path, headers={"Cache-Control": cache_control})
        return _index_html_response()

    async def robots_txt(request: Request) -> PlainTextResponse:  # type: ignore[no-redef]
        base_url = _public_site_base_url(request)
        body = _public_discoverability_text("robots.txt").replace(
            f"{_PUBLIC_SITE_BASE_URL}/sitemap.xml",
            f"{base_url}/sitemap.xml",
        )
        return PlainTextResponse(
            body,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def llms_txt() -> PlainTextResponse:  # type: ignore[no-redef]
        return PlainTextResponse(
            _public_discoverability_text("llms.txt"),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def sitemap_xml(request: Request) -> Response:  # type: ignore[no-redef]
        xml = await _render_public_sitemap_xml(
            _store,
            base_url=_public_site_base_url(request),
        )
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def public_app_index(request: Request) -> HTMLResponse:  # type: ignore[no-redef]
        async def _ssr_bootstrap_json_impl() -> str | None:
            """尝试获取公开首页 bootstrap 数据，失败时返回 None 使前端正常回退。"""
            try:
                news_task = _public_news_feed_payload_for_bootstrap(
                    featured=True,
                    region_id=None,
                    source_id=None,
                    category=None,
                    issue=None,
                    related=None,
                    date=None,
                    q=None,
                    page_size=20,
                )
                regions_task = _cached_public_regions(include_empty=True)
                facets_task = _cached_public_facets(
                    region_id=None,
                    issue=None,
                    related=None,
                    date=None,
                    q=None,
                )
                (news, _news_etag, _elapsed_ms), regions, facets = await asyncio.gather(
                    news_task,
                    regions_task,
                    facets_task,
                )
                payload = PublicBootstrapResponse(
                    news=news,
                    regions=regions,
                    facets=facets,
                    generatedAt=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                )
                return payload.model_dump_json(by_alias=True, exclude_none=True)
            except Exception:
                logger.warning(
                    "SSR bootstrap fetch failed, page will use client-side API", exc_info=True
                )
                return None

        bootstrap_json = await _ssr_bootstrap_json_impl()
        return _public_app_index_response(
            base_url=_public_site_base_url(request),
            bootstrap_json=bootstrap_json,
        )

    async def public_app_asset(asset_path: str, request: Request) -> Response:  # type: ignore[no-redef]
        locale = "zh"
        clean_path = asset_path.strip("/")
        if clean_path == "it" or clean_path.startswith("it/"):
            locale = "it"
            actual_asset = clean_path[3:].lstrip("/") if clean_path.startswith("it/") else ""
            if not actual_asset:
                return _public_app_index_response(
                    base_url=_public_site_base_url(request),
                    canonical_path="/public-app/it/",
                    locale=locale,
                )
            canonical_path = f"/public-app/it/{actual_asset.strip('/')}"
            if actual_asset.strip("/") == "sources":
                canonical_path = "/sources"
            elif actual_asset.strip("/") == "subscribe":
                canonical_path = "/subscribe"
            return _public_app_asset_response(
                actual_asset,
                base_url=_public_site_base_url(request),
                canonical_path=canonical_path,
                locale=locale,
            )
        if not clean_path:
            return _public_app_index_response(base_url=_public_site_base_url(request))
        canonical_path = f"/public-app/{clean_path}"
        if clean_path == "sources":
            canonical_path = "/sources"
        elif clean_path == "subscribe":
            canonical_path = "/subscribe"
        return _public_app_asset_response(
            asset_path,
            base_url=_public_site_base_url(request),
            canonical_path=canonical_path,
        )

    async def collector_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回后台自动采集循环的状态。"""
        return _collector_payload()

    async def collector_config(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回可编辑的自动采集配置与当前运行状态。"""
        return _collector_payload()

    async def update_collector_config(
        config: CollectorConfigUpdate,
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新自动采集配置并持久化到 config/runtime/collector.yaml。"""
        current = _collector_payload()
        update = config.model_dump(exclude_none=True)
        normalized = _apply_collector_config({**current, **update})
        _save_collector_config(normalized)
        return _collector_payload()

    async def start_collector(
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """启用自动采集；非测试生命周期下会启动后台循环。"""
        normalized = _apply_collector_config({**_collector_payload(), "enabled": True})
        _save_collector_config(normalized)
        task = _auto_collector_state.get("task")
        if not _skip_lifespan and (task is None or task.done()):
            _auto_collector_state["task"] = asyncio.create_task(_auto_collect_loop())
        return _collector_payload()

    async def stop_collector(
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """停用自动采集并取消正在等待的后台循环。"""
        normalized = _apply_collector_config({**_collector_payload(), "enabled": False})
        _save_collector_config(normalized)
        task = _auto_collector_state.get("task")
        if task is not None and not task.done():
            task.cancel()
        _auto_collector_state["running"] = False
        _auto_collector_state["next_run_at"] = None
        return _collector_payload()

    async def collector_diagnostics(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回采集系统诊断信息，帮助排查"无数据"问题。"""
        return _cached_collector_diagnostics_payload()

    async def ai_enrichment_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回低频 AI 增强 worker 状态、额度和冷却信息。"""
        return await _ai_enrichment_status_payload()

    async def update_ai_enrichment_config(
        config: AIEnrichmentConfigUpdate,
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新低频 AI 增强配置并持久化到 config/runtime/ai_enrichment.yaml。"""
        current = _ai_enrichment_config_to_dict(_current_ai_enrichment_config())
        update = config.model_dump(exclude_none=True)
        normalized = _save_ai_enrichment_config({**current, **update})
        _apply_ai_enrichment_config(normalized)
        return await _ai_enrichment_status_payload()

    async def run_ai_enrichment(
        dry_run: bool = Query(False, description="只返回计划批次，不调用 Provider"),
        target_id: str | None = Query(None, description="指定 target；默认按配置"),
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """手动触发低频 AI 增强；dry-run 不消耗 OpenRouter 请求。"""
        result = await _run_ai_enrichment_once(target_id=target_id, dry_run=dry_run)
        _ai_enrichment_state["last_run_at"] = datetime.now(UTC).isoformat()
        _ai_enrichment_state["last_run_status"] = result.get("status", "dry_run")
        _ai_enrichment_state["last_error"] = result.get("error")
        _ai_enrichment_state["last_updates"] = len(result.get("updates") or [])
        _ai_enrichment_state["total_runs"] += 0 if dry_run else 1
        return result

    async def public_translation_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回公共站翻译 worker 状态。"""
        return await _public_translation_status_payload()

    async def update_public_translation_config(
        config: PublicTranslationConfigUpdate,
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新公共站翻译 worker 配置并持久化。"""
        current = _public_translation_config_to_dict(_current_public_translation_config())
        update = config.model_dump(exclude_none=True)
        normalized = _save_public_translation_config({**current, **update})
        _apply_public_translation_config(normalized)
        return await _public_translation_status_payload()

    async def run_public_translation(
        dry_run: bool = Query(False, description="只返回待翻译候选，不调用 Provider"),
        target_id: str | None = Query(None, description="指定 target；默认全部公开 target"),
        _user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """手动触发公共站翻译；dry-run 不消耗外部翻译额度。"""
        result = await _run_public_translation_once(target_id=target_id, dry_run=dry_run)
        _public_translation_state["last_run_at"] = datetime.now(UTC).isoformat()
        _public_translation_state["last_run_status"] = result.get("status", "dry_run")
        _public_translation_state["last_error"] = result.get("error")
        _public_translation_state["last_updates"] = len(result.get("updates") or [])
        _public_translation_state["total_runs"] += 0 if dry_run else 1
        return result

    async def data_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回数据状态概览（用于诊断新部署/数据恢复场景）。

        返回 data_dir 状态、各 target 文件产物与 API/SQLite 索引统计、
        store 可用性、部署环境信息。
        """
        target_events: dict[str, dict[str, Any]] = {}
        file_total = 0
        api_total = 0
        seen_targets: set[str] = set()

        for config in _load_target_configs():
            info = _target_info_from_config(config, _data_dir)
            if not info.target_id:
                continue
            tid = info.target_id
            file_count = len(_load_all_events(_data_dir, tid))
            api_count = await _target_api_event_count(tid)
            event_count = max(file_count, api_count)
            file_total += file_count
            api_total += api_count
            seen_targets.add(tid)
            target_events[tid] = {
                "events": event_count,
                "event_count": event_count,
                "file_events": file_count,
                "api_events": api_count,
                "source_count": info.source_count,
                "has_state_db": (_data_dir / tid / "state.db").exists(),
            }

        if _data_dir.exists():
            for target_dir in sorted(_data_dir.iterdir()):
                if not target_dir.is_dir():
                    continue
                tid = target_dir.name
                if tid in seen_targets:
                    continue
                file_count = len(_load_all_events(_data_dir, tid))
                api_count = await _target_api_event_count(tid)
                event_count = max(file_count, api_count)
                if event_count == 0 and not (target_dir / "state.db").exists():
                    continue
                file_total += file_count
                api_total += api_count
                target_events[tid] = {
                    "events": event_count,
                    "event_count": event_count,
                    "file_events": file_count,
                    "api_events": api_count,
                    "source_count": 0,
                    "has_state_db": (target_dir / "state.db").exists(),
                }

        return {
            "data_dir": str(_data_dir),
            "data_dir_exists": _data_dir.exists(),
            "deployment_env": _detect_deployment_env(),
            "store_available": _store is not None,
            "target_stores_open": len(_target_stores),
            "file_event_total": file_total,
            "api_event_total": api_total,
            "total_events_all_targets": max(file_total, api_total),
            "targets": target_events,
            "runtime_info": {
                "code_path": str(Path(__file__).resolve()),
                "git_commit": _git_commit_for_path(Path(__file__)),
                "data_dir": str(_data_dir.resolve()),
            },
            "auto_collector": {
                "enabled": _auto_collector_state["enabled"],
                "last_run_at": _auto_collector_state["last_run_at"],
            },
        }

    async def auth_login(login: LoginRequest) -> LoginResponse:  # type: ignore[no-redef]
        """用户名+密码登录（返回 access token 和用户信息）。"""
        username = login.username.strip()
        password = login.password

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        # 暴力破解保护
        if not _login_limiter.check(f"login:{username}"):
            raise HTTPException(status_code=429, detail="Too many login attempts")

        # 验证用户
        if _store is None:
            raise HTTPException(status_code=503, detail="User store not available")
        user = await _store.get_user(username)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(password, user["password_hash"], user["salt"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        result = await _create_persistent_token_for_user(
            username,
            user["role"],
            bool(user.get("api_key")),
        )
        return LoginResponse(
            access_token=result["access_token"],
            token_type=result["token_type"],
            expires_in=result["expires_in"],
            username=result["username"],
            role=result["role"],
            has_api_key=result["has_api_key"],
            must_change_password=bool(user.get("must_change_pw", 0)),
        )

    async def auth_token(request: Request) -> dict[str, Any]:
        """API Key 换取短期 Token（向后兼容 CLI/cron）。"""
        body = await _read_json_object(request)
        api_key = body.get("api_key", "")
        valid_keys = _get_valid_api_keys()

        # 也检查用户存储中的 API Key
        if _store is not None and api_key:
            users = await _store.list_users()
            for u in users:
                if u.get("api_key") == api_key:
                    return await _create_persistent_token_for_user(
                        u["username"],
                        u.get("role", "reader"),
                        True,
                    )

        if not valid_keys:
            if _local_auth_bypass_enabled(request):
                return await _create_persistent_token_for_user("dev", "admin", False)
            raise HTTPException(
                status_code=503,
                detail="API key is required outside local mode",
            )
        if api_key not in valid_keys:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return await _create_persistent_token_for_user(f"key_{api_key[:8]}", "admin", True)

    async def auth_stream_token(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """为 EventSource 连接创建短期 token，避免把主 bearer 放进 URL。"""
        return _create_stream_token_for_user(user["username"], user["role"])

    async def auth_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        """返回当前用户信息。"""
        return {
            "username": user["username"],
            "role": user["role"],
            "permissions": sorted(_PERMISSIONS.get(user["role"], set())),
            "has_api_key": user.get("has_api_key", False),
        }

    async def auth_logout(request: Request) -> dict[str, str]:
        """注销当前 token（内存 + SQLite 双删）。"""
        token = _extract_bearer_token(request)
        if token:
            _TOKEN_STORE.pop(token, None)
            if _store is not None:
                await _store.delete_session(token)
        return {"status": "ok"}

    async def auth_change_password(
        request: Request, user: dict[str, Any] = Depends(get_current_user)
    ) -> dict[str, str]:
        """修改当前用户密码。"""
        body = await request.json()
        current_pw = body.get("current_password", "")
        new_pw = body.get("new_password", "")
        if not current_pw or not new_pw:
            raise HTTPException(status_code=400, detail="Current and new password required")
        if len(new_pw) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

        if _store is None:
            raise HTTPException(status_code=503, detail="User store not available")
        user_record = await _store.get_user(user["username"])
        if not user_record:
            raise HTTPException(status_code=401, detail="User not found")
        if not verify_password(current_pw, user_record["password_hash"], user_record["salt"]):
            raise HTTPException(status_code=401, detail="Current password incorrect")

        pw_hash, salt = hash_password(new_pw)
        await _store.update_user_password(user["username"], pw_hash, salt)
        await _revoke_sessions_for_username(user["username"])
        return {"status": "ok"}

    # ── 用户管理 (admin) ──────────────────────────────────

    async def auth_setup_status() -> dict[str, Any]:
        """检查是否已完成初始设置（创建管理员）。"""
        if _store is None:
            return {"setup_completed": False, "error": "store_not_available"}
        users = await _store.list_users()
        if not users:
            return {"setup_completed": False, "needs_setup": True}
        # 如果所有用户都是 must_change_pw，说明还没完成首次设置
        all_must_change = all(bool(u.get("must_change_pw", 0)) for u in users)
        return {"setup_completed": not all_must_change, "needs_setup": all_must_change}

    async def auth_setup(request: Request) -> dict[str, Any]:
        """首次设置：创建管理员账户（仅在无用户时可用）。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        users = await _store.list_users()
        if users:
            raise HTTPException(status_code=409, detail="Setup already completed")
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        pw_hash, salt = hash_password(password)
        await _store.create_user(
            username=username,
            password_hash=pw_hash,
            salt=salt,
            role="admin",
            must_change_pw=0,
        )
        logger.info("Initial setup completed: admin user '%s' created", username)
        result = await _create_persistent_token_for_user(username, "admin", False)
        return result

    async def admin_list_users(
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """列出所有用户（不含 password_hash/salt）。"""
        if _store is None:
            return {"users": [], "total": 0}
        users = await _store.list_users()
        safe_users = []
        for u in users:
            safe_users.append(
                {
                    "username": u["username"],
                    "role": u["role"],
                    "has_api_key": bool(u.get("api_key")),
                    "must_change_pw": bool(u.get("must_change_pw", 0)),
                    "created_at": u.get("created_at", ""),
                    "updated_at": u.get("updated_at", ""),
                }
            )
        return {"users": safe_users}

    async def admin_create_user(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """创建新用户。"""
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
        role = body.get("role", "reader")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        if role not in ("admin", "reader"):
            raise HTTPException(status_code=400, detail="Role must be admin or reader")

        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")

        existing = await _store.get_user(username)
        if existing:
            raise HTTPException(status_code=409, detail=f"User '{username}' already exists")

        pw_hash, salt = hash_password(password)
        ok = await _store.create_user(username, pw_hash, salt, role=role, must_change_pw=1)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to create user")
        _clear_admin_caches()
        return {"status": "ok", "username": username}

    async def admin_delete_user(
        username: str,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """删除用户。不能删除自己。"""
        if username == user["username"]:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        ok = await _store.delete_user(username)
        if not ok:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        await _revoke_sessions_for_username(username)
        _clear_admin_caches()
        return {"status": "ok"}

    async def admin_reset_password(
        username: str,
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """重置用户密码。"""
        body = await request.json()
        new_password = body.get("new_password", "")
        if not new_password or len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")

        existing = await _store.get_user(username)
        if not existing:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")

        pw_hash, salt = hash_password(new_password)
        await _store.update_user_password(username, pw_hash, salt)
        await _revoke_sessions_for_username(username)
        _clear_admin_caches()
        return {"status": "ok"}

    # ── API Key 设置 ─────────────────────────────────────

    async def get_api_key_setting(
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """获取当前用户的 API Key 设置。"""
        if _store is None:
            return {"has_api_key": False, "api_key_preview": ""}
        user_record = await _store.get_user(user["username"])
        api_key = user_record.get("api_key") if user_record else None
        preview = f"{api_key[:4]}...{api_key[-4:]}" if api_key and len(api_key) >= 8 else ""
        return {
            "has_api_key": bool(api_key),
            "api_key_preview": preview,
        }

    async def set_api_key_setting(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """设置当前用户的 API Key。"""
        body = await request.json()
        api_key = body.get("api_key", "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="API Key cannot be empty")
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        await _store.update_user_api_key(user["username"], api_key)
        # 更新 token 中的 has_api_key 状态
        token = _extract_bearer_token(request)
        if token and token in _TOKEN_STORE:
            _TOKEN_STORE[token]["has_api_key"] = True
        return {"status": "ok"}

    async def delete_api_key_setting(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """删除当前用户的 API Key。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        await _store.update_user_api_key(user["username"], None)
        token = _extract_bearer_token(request)
        if token and token in _TOKEN_STORE:
            _TOKEN_STORE[token]["has_api_key"] = False
        return {"status": "ok"}

    # ── 通知设置 ──────────────────────────────────────────

    _notifications_defaults: dict[str, Any] = {
        "channels": {
            "email": {
                "enabled": False,
                "smtp_host": "",
                "smtp_port": 587,
                "from_address": "",
                "to_addresses": [],
            },
            "feishu": {"enabled": False, "webhook_url": ""},
            "generic_webhook": {"enabled": False, "url": "", "secret": ""},
        },
        "rules": {
            "min_score": 80,
            "include_classifications": ["L1-breaking", "L2-significant"],
            "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
        },
    }

    async def _load_notifications() -> dict[str, Any]:
        """读取通知配置 — SQLite 优先，JSON 文件作为回退并自动迁移。"""
        if _store is not None:
            config = await _store.get_notifications()
            if config:
                return config
            # SQLite 中不存在，尝试从 JSON 文件迁移
            nf = _data_dir / "notifications.json"
            if nf.exists():
                try:
                    file_config: dict[str, Any] = json.loads(nf.read_text(encoding="utf-8"))
                    await _store.save_notifications(file_config)
                    _log.info("通知设置已从 notifications.json 迁移到 SQLite")
                    return file_config
                except Exception as exc:
                    _log.warning("Failed to migrate notifications.json: %s", exc)
        # 回退：直接读 JSON 文件
        nf = _data_dir / "notifications.json"
        if nf.exists():
            try:
                result: dict[str, Any] = json.loads(nf.read_text(encoding="utf-8"))
                return result
            except Exception as exc:
                _log.warning("Failed to load notifications.json: %s", exc)
        return dict(_notifications_defaults)

    async def _save_notifications(config: dict[str, Any]) -> None:
        """写入通知配置 — SQLite 为主，JSON 文件作为备份。"""
        if _store is not None:
            await _store.save_notifications(config)
        # 也写一份 JSON 文件作为可读备份
        _data_dir.mkdir(parents=True, exist_ok=True)
        nf = _data_dir / "notifications.json"
        nf.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    async def get_notifications(
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """获取通知渠道配置。"""
        return await _load_notifications()

    async def update_notifications(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """更新通知渠道配置。"""
        body = await request.json()
        await _save_notifications(body)
        return {"status": "ok"}

    # ── 简报邮件发送 ──────────────────────────────────────

    async def send_briefing(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """生成简报并发送邮件。"""
        body = await request.json()
        target_id = body.get("target_id", "all")
        recipients = body.get("recipients")

        # 1. 读取通知配置获取 SMTP 设置
        notif = await _load_notifications()
        email_ch = notif.get("channels", {}).get("email", {})
        if not email_ch.get("enabled") or not email_ch.get("smtp_host"):
            raise HTTPException(
                status_code=400,
                detail="Email notifications not configured. Enable in Settings > Notifications.",
            )

        to_addrs = recipients or email_ch.get("to_addresses", [])
        if not to_addrs:
            raise HTTPException(status_code=400, detail="No recipients specified")

        # 2. 收集数据
        events_data: list[dict[str, Any]] = []
        if _store is not None:
            try:
                tids = (
                    [target_id]
                    if target_id != "all"
                    else _auto_collector_state.get("target_ids", [])
                )
                for tid in tids:
                    evts = await _store.query_events(
                        tid,
                        "evaluated",
                        limit=10,
                    )
                    events_data.extend(evts)
            except Exception as exc:
                _log.warning("Briefing data collection error: %s", exc)

        # 3. 生成 Markdown 简报
        md_lines = ["# News Sentry 简报", ""]
        md_lines.append("## 高价值事件")
        for ev in events_data[:10]:
            title = ev.get("title_original") or ev.get("title") or ev.get("event_id", "—")
            score = ev.get("news_value_score", "—")
            source = ev.get("source_id", "—")
            md_lines.append(f"- [{score}] {title} — {source}")

        md = "\n".join(md_lines)

        # 4. 发送邮件
        try:
            import smtplib
            from email.mime.text import MIMEText

            smtp_host = email_ch["smtp_host"]
            smtp_port = email_ch.get("smtp_port", 587)
            from_addr = email_ch.get("from_address", "news-sentry@localhost")

            msg = MIMEText(md, "plain", "utf-8")
            msg["Subject"] = f"News Sentry 简报 — {target_id}"
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.sendmail(from_addr, to_addrs, msg.as_string())

            return {
                "status": "ok",
                "recipients": to_addrs,
                "events_count": len(events_data),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to send email: {exc}") from exc

    async def list_targets(
        include_empty: bool = Query(
            False,
            description="是否包含已有信源但暂无公开 ready 新闻的地区入口",
        ),
    ) -> TargetListResponse:
        """兼容旧接口：返回公开可浏览的地区列表。"""
        from news_sentry.core import public_handlers
        return await public_handlers.list_public_targets(_data_dir, include_empty=include_empty)

    async def _public_regions_payload(*, include_empty: bool = False) -> RegionListResponse:
        from news_sentry.core import public_handlers
        return await public_handlers.public_regions_payload(
            _data_dir, _store, include_empty=include_empty
        )

    async def _cached_public_regions(
        response: Response | None = None,
        *,
        include_empty: bool = False,
    ) -> RegionListResponse:
        from news_sentry.core import public_handlers
        return await public_handlers.cached_public_regions(
            _data_dir,
            _store,
            _public_regions_cache,
            _PUBLIC_REGIONS_CACHE_TTL_SECONDS,
            _public_regions_payload,
            response,
            include_empty=include_empty,
        )

    async def _public_facets_payload(
        *,
        region_id: str | None,
        issue: str | None,
        related: str | None,
        date: str | None,
        q: str | None,
    ) -> PublicFacetsResponse:
        from news_sentry.core import public_handlers
        return await public_handlers.public_facets_payload(
            _data_dir,
            region_id=region_id,
            issue=issue,
            related=related,
            date=date,
            q=q,
        )

    async def _cached_public_facets(
        *,
        response: Response | None = None,
        region_id: str | None,
        issue: str | None,
        related: str | None,
        date: str | None,
        q: str | None,
    ) -> PublicFacetsResponse:
        from news_sentry.core import public_handlers
        return await public_handlers.cached_public_facets(
            _data_dir,
            _store,
            _public_facets_cache,
            _PUBLIC_FACETS_CACHE_TTL_SECONDS,
            _public_facets_payload,
            response=response,
            region_id=region_id,
            issue=issue,
            related=related,
            date=date,
            q=q,
        )

    async def list_regions(
        response: Response,
        include_empty: bool = Query(
            False,
            description="是否包含已有信源但暂无公开 ready 新闻的地区入口",
        ),
    ) -> RegionListResponse:
        """返回公开可浏览的地区入口；topic target 不再作为公共入口。"""
        return await _cached_public_regions(response, include_empty=include_empty)

    async def list_admin_targets(
        include_archived: bool = Query(False, description="是否包含已归档 target"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """管理后台 target 全生命周期列表（缓存 TTL 15s）。"""
        cache_key = f"archived={include_archived}"
        cached = _admin_targets_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < _ADMIN_CACHE_TTL_SECONDS:
            return cached[1]
        configs = _load_target_configs()
        targets = []
        for config in configs:
            if not include_archived and _target_is_archived(config):
                continue
            target = await _target_info_from_config_for_response(config, _data_dir)
            targets.append(target.model_dump())
        result: dict[str, Any] = {"targets": targets}
        _admin_targets_cache[cache_key] = (now, result)
        return result

    async def create_admin_target(
        payload: TargetCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """通过模板或克隆创建完整 target 配置骨架。"""
        _validate_target_slug(payload.target_id)
        target_path = _target_config_path(payload.target_id)
        if target_path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"Target '{payload.target_id}' already exists",
            )
        _ensure_global_config_defaults()

        if payload.mode == "template":
            target_data = _template_target_config(
                target_id=payload.target_id,
                display_name=payload.display_name,
                language_scope=payload.language_scope,
                timezone=payload.timezone,
                monitoring_type=payload.monitoring_type,
                region_type=payload.region_type,
            )
            _atomic_write_yaml(
                _source_config_path(payload.target_id, "rss-template"),
                _default_template_source(payload.target_id),
            )
            _atomic_write_yaml(
                _config_base_dir() / "filters" / payload.target_id / "default.yaml",
                _default_filter_config(payload.target_id),
            )
            _atomic_write_yaml(
                _config_base_dir() / "classification" / f"rules-{payload.target_id}.yaml",
                _default_classification_config(payload.target_id),
            )
        else:
            if not payload.source_target_id:
                raise HTTPException(status_code=400, detail="clone mode requires source_target_id")
            source_target = _ensure_target_exists(payload.source_target_id)
            source_refs = _copy_target_config_skeleton(payload.source_target_id, payload.target_id)
            target_data = _template_target_config(
                target_id=payload.target_id,
                display_name=payload.display_name,
                language_scope=payload.language_scope,
                timezone=payload.timezone,
                monitoring_type=payload.monitoring_type or _target_region_type(source_target),
                region_type=payload.region_type or _target_region_type(source_target),
                source_refs=source_refs,
            )
            for key in ("sandbox_profile_ref", "provider_routes_ref", "output_destinations_ref"):
                if source_target.get(key):
                    target_data[key] = source_target[key]
            if isinstance(source_target.get("classification"), dict):
                target_data["classification"] = source_target["classification"]
            if isinstance(source_target.get("focus_areas"), list):
                target_data["focus_areas"] = source_target["focus_areas"]

        _atomic_write_yaml(target_path, target_data)
        _config_cache.clear()
        _clear_admin_caches()
        return _target_info_from_config(target_data, _data_dir).model_dump()

    async def patch_admin_target(
        target_id: str,
        payload: TargetPatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新 target 基础资料。"""
        data = _ensure_target_exists(target_id)
        updates = payload.model_dump(exclude_unset=True)
        data = _deep_merge(data, updates)
        data["target_id"] = target_id
        data.pop("topic_label", None)
        if data.get("region_type") in _REGION_TYPES:
            data["monitoring_type"] = data["region_type"]
        _atomic_write_yaml(_target_config_path(target_id), data)
        _config_cache.clear()
        _clear_admin_caches()
        return data

    async def archive_admin_target(
        target_id: str,
        payload: ArchiveRequest | None = None,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """归档 target：公开首页隐藏，历史数据保留。"""
        data = _ensure_target_exists(target_id)
        data["lifecycle"] = {
            **_target_lifecycle(data),
            "status": "archived",
            "archived_at": datetime.now(UTC).isoformat(),
            "archive_reason": payload.reason if payload else None,
        }
        _atomic_write_yaml(_target_config_path(target_id), data)
        _stop_target_in_collector_config(target_id)
        _config_cache.clear()
        _clear_admin_caches()
        return data

    async def restore_admin_target(
        target_id: str,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """恢复 target：重新进入公开首页和后台列表，但不自动启动采集。"""
        data = _ensure_target_exists(target_id)
        lifecycle = _target_lifecycle(data)
        lifecycle["status"] = "active"
        lifecycle.pop("archive_reason", None)
        data["lifecycle"] = lifecycle
        _atomic_write_yaml(_target_config_path(target_id), data)
        _config_cache.clear()
        _clear_admin_caches()
        return data

    async def admin_target_overview(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """单个 target 工作台总览。"""
        target_data = _ensure_target_exists(target_id)
        inventory = _cached_source_inventory(target_id)
        inventory_summary = inventory["summary"]
        inventory_sources = inventory["sources"]
        standard_inventory_sources = [
            item
            for item in inventory_sources
            if item.get("type") in {"rss", "api"} and not item.get("missing_file")
        ]
        target_info = await _target_info_from_config_for_response(target_data, _data_dir)
        target_store = await _get_target_store(target_id)
        events: list[dict[str, Any]] = []
        classification_diagnostics = await _classification_diagnostics_from_store(
            target_id,
            target_store,
        )
        has_index = target_store is not None and await _store_has_target_event_index(
            target_store,
            target_id,
        )
        if classification_diagnostics is None or (
            not classification_diagnostics.get("distribution") and not has_index
        ):
            events = _load_all_events(_data_dir, target_id)
            classification_diagnostics = _classification_diagnostics_from_events(events)
        validation = _cached_target_validation(target_id)
        recent_runs = _load_run_logs(_data_dir, target_id, 5)
        return {
            "target": target_info.model_dump(),
            "profile": target_data,
            "sources": {
                "total": inventory_summary["standard_sources"],
                "active": sum(1 for item in standard_inventory_sources if not item["archived"]),
                "archived": sum(1 for item in standard_inventory_sources if item["archived"]),
                "missing_refs": inventory_summary["missing_refs"],
                "unreferenced_files": inventory_summary["unreferenced_files"],
            },
            "social": {
                "dimensions": inventory_summary["social_dimensions"],
                "accounts": inventory_summary["social_accounts"],
                "archived_accounts": sum(
                    int(item.get("archived_account_count") or 0)
                    for item in inventory_sources
                    if item.get("type") == "social"
                ),
            },
            "events": {"total": target_info.event_count},
            "classification_diagnostics": classification_diagnostics,
            "recent_runs": recent_runs,
            "validation": validation,
            "collector": _collector_payload(),
        }

    async def validate_admin_target(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """预检 target 配置链路。"""
        return _cached_target_validation(target_id)

    async def admin_target_inventory(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回 target 信源统一对账视图。"""
        _ensure_target_exists(target_id)
        return _cached_source_inventory(target_id)

    async def list_admin_target_sources(
        target_id: str,
        include_archived: bool = Query(False, description="是否包含已归档信源"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """列出 target 的标准 RSS/API 信源。"""
        _ensure_target_exists(target_id)
        sources = []
        for source in _load_source_configs(target_id):
            if not _source_is_standard(source):
                continue
            if not include_archived and _source_is_archived(source):
                continue
            sources.append(_source_info_from_config(source).model_dump())
        return {"target_id": target_id, "sources": sources}

    async def create_admin_target_source(
        target_id: str,
        payload: SourceCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """新增标准信源，并写入 target source_channel_refs。"""
        _ensure_target_exists(target_id)
        source_ref, data = _build_source_config(payload)
        path = _source_config_path(target_id, source_ref)
        if path.exists():
            raise HTTPException(status_code=409, detail=f"Source '{source_ref}' already exists")
        _atomic_write_yaml(path, data)
        _append_source_ref(target_id, source_ref)
        _config_cache.clear()
        data["_source_id"] = source_ref
        data["_file_path"] = str(path)
        _clear_admin_caches()
        return _source_info_from_config(data).model_dump()

    async def patch_admin_target_source(
        target_id: str,
        source_ref: str,
        payload: SourcePatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """编辑标准信源。"""
        _ensure_target_exists(target_id)
        normalized_ref = _normalize_source_ref(source_ref)
        path = _source_config_path(target_id, normalized_ref)
        data = _load_yaml_file(path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Source '{normalized_ref}' not found")
        updates = payload.model_dump(exclude_unset=True)
        for key, value in updates.items():
            if value is None:
                continue
            data[key] = value
        _atomic_write_yaml(path, data)
        _config_cache.clear()
        data["_source_id"] = normalized_ref
        data["_file_path"] = str(path)
        _clear_admin_caches()
        return _source_info_from_config(data).model_dump()

    async def archive_admin_target_source(
        target_id: str,
        source_ref: str,
        payload: ArchiveRequest | None = None,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """归档标准信源：禁用但保留 YAML 和历史事件。"""
        _ensure_target_exists(target_id)
        normalized_ref = _normalize_source_ref(source_ref)
        path = _source_config_path(target_id, normalized_ref)
        data = _load_yaml_file(path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Source '{normalized_ref}' not found")
        data["enabled"] = False
        data["deprecated"] = True
        data["deprecated_reason"] = payload.reason if payload else "archived"
        _atomic_write_yaml(path, data)
        _config_cache.clear()
        data["_source_id"] = normalized_ref
        data["_file_path"] = str(path)
        _clear_admin_caches()
        return _source_info_from_config(data).model_dump()

    async def restore_admin_target_source(
        target_id: str,
        source_ref: str,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """恢复已归档标准信源。"""
        _ensure_target_exists(target_id)
        normalized_ref = _normalize_source_ref(source_ref)
        path = _source_config_path(target_id, normalized_ref)
        data = _load_yaml_file(path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Source '{normalized_ref}' not found")
        data["enabled"] = True
        data["deprecated"] = False
        data.pop("deprecated_reason", None)
        _atomic_write_yaml(path, data)
        _config_cache.clear()
        data["_source_id"] = normalized_ref
        data["_file_path"] = str(path)
        _clear_admin_caches()
        return _source_info_from_config(data).model_dump()

    async def get_admin_target_social(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """读取 target 社媒矩阵。"""
        _ensure_target_exists(target_id)
        dimensions = _social_dimensions(target_id)
        return {"target_id": target_id, "dimensions": dimensions}

    async def create_admin_social_dimension(
        target_id: str,
        payload: SocialDimensionCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """新增社媒维度。"""
        _ensure_target_exists(target_id)
        platform = _normalize_source_ref(payload.platform)
        dimension = _normalize_source_ref(payload.dimension)
        source_ref = f"social/{platform}/{dimension}"
        path = _source_config_path(target_id, source_ref)
        if path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"Social dimension '{dimension}' already exists",
            )
        data: dict[str, Any] = {
            "platform": platform,
            "dimension": dimension,
            "collect_mode": payload.collect_mode,
            "session_profile_ref": payload.session_profile_ref
            or f"config/session-profiles/{target_id}/{platform}.session.yaml",
            "accounts": [],
        }
        if payload.notes:
            data["notes"] = payload.notes
        _atomic_write_yaml(path, data)
        _append_source_ref(target_id, source_ref)
        _config_cache.clear()
        data["_source_ref"] = source_ref
        data["_file_path"] = str(path)
        data["account_count"] = 0
        data["archived_count"] = 0
        _clear_admin_caches()
        return data

    async def patch_admin_social_dimension(
        target_id: str,
        dimension: str,
        payload: SocialDimensionPatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """编辑社媒维度。"""
        _ensure_target_exists(target_id)
        path = _find_social_dimension_path(target_id, dimension)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Social dimension '{dimension}' not found")
        data = _load_yaml_file(path) or {}
        for key, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                data[key] = value
        _atomic_write_yaml(path, data)
        _config_cache.clear()
        _clear_admin_caches()
        return data

    async def create_admin_social_account(
        target_id: str,
        dimension: str,
        payload: SocialAccountCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """新增社媒账号。"""
        _ensure_target_exists(target_id)
        path = _find_social_dimension_path(target_id, dimension)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Social dimension '{dimension}' not found")
        data = _load_yaml_file(path) or {}
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []
        if any(
            isinstance(account, dict) and account.get("handle") == payload.handle
            for account in accounts
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Account '{payload.handle}' already exists",
            )
        account = payload.model_dump(exclude_none=True)
        accounts.append(account)
        data["accounts"] = accounts
        _atomic_write_yaml(path, data)
        _config_cache.clear()
        _clear_admin_caches()
        return account

    async def patch_admin_social_account(
        target_id: str,
        dimension: str,
        handle: str,
        payload: SocialAccountPatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """编辑或归档社媒账号。"""
        _ensure_target_exists(target_id)
        path = _find_social_dimension_path(target_id, dimension)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Social dimension '{dimension}' not found")
        data = _load_yaml_file(path) or {}
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []
        for account in accounts:
            if isinstance(account, dict) and account.get("handle") == handle:
                for key, value in payload.model_dump(exclude_unset=True).items():
                    if value is not None:
                        account[key] = value
                _atomic_write_yaml(path, data)
                _config_cache.clear()
                _clear_admin_caches()
                return account
        raise HTTPException(status_code=404, detail=f"Account '{handle}' not found")

    async def admin_overview(
        target_id: str | None = Query(None, description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """管理后台总览聚合：目标、采集、诊断、健康、反馈与告警（缓存 TTL 15s）。"""
        cache_key = f"overview_tid={target_id or '__default__'}"
        cached = _admin_overview_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < _ADMIN_CACHE_TTL_SECONDS:
            return cached[1]
        targets = []
        for config in _load_target_configs():
            if _target_is_archived(config):
                continue
            target = await _target_info_from_config_for_response(config, _data_dir)
            targets.append(target.model_dump())
        selected_target = target_id or (targets[0]["target_id"] if targets else "")

        diagnostics = await collector_diagnostics(user)
        source_health_records: list[dict[str, Any]] = []
        if selected_target:
            source_health_records = await _source_health_records_for_target(selected_target)

        feedback: dict[str, Any] = {
            "total": 0,
            "publish_override": 0,
            "archive_override": 0,
            "comment": 0,
        }
        alerts: dict[str, Any] = {"total": 0, "items": []}
        if _store is not None and selected_target:
            try:
                feedback = await _store.get_feedback_stats(selected_target)
            except AttributeError:
                feedback = dict(feedback)
            try:
                alert_items = await _store.get_alert_history(selected_target)
                alerts = {"total": len(alert_items), "items": alert_items[:5]}
            except AttributeError:
                alerts = {"total": 0, "items": []}

        recent_runs = _load_run_logs(_data_dir, selected_target, 5) if selected_target else []
        result: dict[str, Any] = {
            "target_id": selected_target,
            "targets": targets,
            "collector": _collector_payload(),
            "diagnostics": diagnostics,
            "source_health": {
                "total": len(source_health_records),
                "unhealthy": sum(
                    1
                    for item in source_health_records
                    if item.get("status") not in {"ok", "healthy"}
                ),
                "items": source_health_records[:8],
            },
            "recent_runs": recent_runs,
            "feedback": feedback,
            "alerts": alerts,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        _admin_overview_cache[cache_key] = (now, result)
        return result

    async def get_public_target_analysis(
        target_id: str,
        days: Annotated[
            Literal[7, 14, 30],
            Query(description="分析窗口天数"),
            BeforeValidator(int),
        ] = 14,
    ) -> PublicAnalysisResponse:
        """公开匿名只读分析快照。"""
        from news_sentry.core import public_handlers
        return await public_handlers.get_public_target_analysis_handler(
            _get_target_store, _store, _data_dir, target_id, days=days
        )

    async def list_public_facets(
        response: Response,
        region_id: str | None = Query(None, description="按地区筛选"),
        target_id: str | None = Query(None, description="兼容旧参数：按地区筛选"),
        issue: str | None = Query(None, description="按议题标签筛选"),
        related: str | None = Query(None, description="按相关对象标签筛选"),
        date: str | None = Query(None, description="日期筛选 YYYY-MM-DD"),
        q: str | None = Query(None, description="全文关键词搜索"),
    ) -> PublicFacetsResponse:
        """返回当前可见公共新闻中的地区、议题与相关对象 facets。"""
        effective_region_id = region_id or target_id
        return await _cached_public_facets(
            response=response,
            region_id=effective_region_id,
            issue=issue,
            related=related,
            date=date,
            q=q,
        )

    async def subscribe(
        target_id: str = Query(..., description="目标地区 ID"),
        source_id: str | None = Query(None, description="信源 ID（可选）"),
        issue: str | None = Query(None, description="议题标签（可选）"),
        email: str | None = Query(None, description="邮件地址（可选）"),
        preferred_language: str | None = Query(None, description="偏好语言"),
    ) -> JSONResponse:
        """创建订阅记录（v1: 存本地 JSON，不发邮件）。"""
        from news_sentry.core import public_handlers
        return await public_handlers.subscribe_handler(
            _data_dir,
            target_id,
            source_id=source_id,
            issue=issue,
            email=email,
            preferred_language=preferred_language,
        )

    async def _public_news_feed_payload_for_bootstrap(
        *,
        featured: bool,
        region_id: str | None,
        source_id: str | None,
        category: str | None,
        issue: str | None,
        related: str | None,
        date: str | None,
        q: str | None,
        page_size: int,
    ) -> tuple[PublicNewsFeedResponse, str, int]:
        from news_sentry.core import public_handlers
        return await public_handlers.public_news_feed_payload_for_bootstrap(
            _data_dir,
            _store,
            _public_news_feed_cache,
            featured=featured,
            region_id=region_id,
            source_id=source_id,
            category=category,
            issue=issue,
            related=related,
            date=date,
            q=q,
            page_size=page_size,
        )

    async def get_public_bootstrap(
        request: Request,
        response: Response,
        featured: bool = Query(True, description="首屏是否优先取精选新闻"),
        target_id: str | None = Query(None, description="兼容旧参数：按地区筛选"),
        region_id: str | None = Query(None, description="按地区筛选"),
        source_id: str | None = Query(None, description="按来源筛选"),
        category: str | None = Query(None, description="按 classification.l0 筛选"),
        issue: str | None = Query(None, description="按议题标签筛选"),
        related: str | None = Query(None, description="按相关对象标签筛选"),
        date: str | None = Query(None, description="日期筛选 YYYY-MM-DD"),
        q: str | None = Query(None, description="全文关键词搜索"),
        page_size: int = Query(
            20,
            ge=1,
            le=_PUBLIC_NEWS_MAX_PAGE_SIZE,
        ),
    ) -> PublicBootstrapResponse | Response:
        from news_sentry.core import public_handlers
        return cast(
            "PublicBootstrapResponse | Response",
            await public_handlers.get_public_bootstrap_handler(
            _data_dir,
            _store,
            _get_target_store,
            _public_regions_cache,
            _public_facets_cache,
            _public_bootstrap_cache,
            _public_news_feed_cache,
            _public_news_feed_payload_for_bootstrap,
            _cached_public_regions,
            _cached_public_facets,
            request,
            response,
            featured=featured,
            target_id=target_id,
            region_id=region_id,
            source_id=source_id,
            category=category,
            issue=issue,
            related=related,
            date=date,
            q=q,
            page_size=page_size,
        ))

    async def list_public_news(
        request: Request,
        response: Response,
        featured: bool = Query(False, description="仅返回精选/关注新闻"),
        target_id: str | None = Query(None, description="兼容旧参数：按地区筛选"),
        region_id: str | None = Query(None, description="按地区筛选"),
        source_id: str | None = Query(None, description="按来源筛选"),
        category: str | None = Query(None, description="按 classification.l0 筛选"),
        issue: str | None = Query(None, description="按议题标签筛选"),
        related: str | None = Query(None, description="按相关对象标签筛选"),
        date: str | None = Query(None, description="日期筛选 YYYY-MM-DD"),
        q: str | None = Query(None, description="全文关键词搜索"),
        before_cursor: str | None = Query(None, description="加载更早新闻的 cursor"),
        since_cursor: str | None = Query(None, description="检查更新新闻的 cursor"),
        page_size: int = Query(
            _PUBLIC_NEWS_DEFAULT_PAGE_SIZE,
            ge=1,
            le=_PUBLIC_NEWS_MAX_PAGE_SIZE,
        ),
    ) -> PublicNewsFeedResponse | Response:
        """公共新闻流 presentation API，匿名只读，支持低负担增量更新。"""
        from news_sentry.core import public_handlers
        return cast(
            "PublicNewsFeedResponse | Response",
            await public_handlers.list_public_news_handler(
            _data_dir,
            _store,
            _get_target_store,
            _public_news_feed_cache,
            request,
            response,
            featured=featured,
            target_id=target_id,
            region_id=region_id,
            source_id=source_id,
            category=category,
            issue=issue,
            related=related,
            date=date,
            q=q,
            before_cursor=before_cursor,
            since_cursor=since_cursor,
            page_size=page_size,
        ))

    async def get_public_news_item(
        event_id: str,
        target_id: str | None = Query(None, description="可选 target 提示"),
    ) -> PublicNewsItem:
        """公共新闻详情 presentation API，不暴露后台字段。"""
        from news_sentry.core import public_handlers
        return await public_handlers.get_public_news_item_handler(
            _data_dir, _store, _get_target_store, event_id, target_id=target_id
        )

    async def get_stats(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> StatsResponse:
        """返回指定 target 的事件统计（优先使用 target state.db）。"""
        # 优先使用 target 自己的 state.db（与 pipeline 共享同一数据库）
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store

        if store_to_query is not None:
            stats = await store_to_query.get_stats_aggregated(target_id)
            if stats["total_events"] > 0:
                return StatsResponse(
                    target_id=target_id,
                    total_events=stats["total_events"],
                    avg_news_value_score=stats["avg_news_value_score"],
                    avg_china_relevance=stats["avg_china_relevance"],
                    by_classification=stats["by_classification"],
                    by_source=stats["by_source"],
                    sentiment_breakdown=stats.get("sentiment_breakdown", {}),
                    top_entities=stats.get("top_entities", []),
                )

        # 降级路径：无 store / store 为空 / 文件系统扫描
        events = _load_all_events(_data_dir, target_id)

        total = len(events)
        scores = [
            e["news_value_score"]
            for e in events
            if isinstance(e.get("news_value_score"), (int, float))
        ]
        relevances = [
            e["china_relevance"]
            for e in events
            if isinstance(e.get("china_relevance"), (int, float))
        ]

        avg_score = sum(scores) / len(scores) if scores else None
        avg_relevance = sum(relevances) / len(relevances) if relevances else None

        by_classification: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)
        for e in events:
            cls_data = e.get("classification")
            if isinstance(cls_data, dict):
                l0 = cls_data.get("l0")
                if l0:
                    by_classification[canonical_l0(l0)] += 1
            src = e.get("source_id")
            if src:
                by_source[src] += 1

        return StatsResponse(
            target_id=target_id,
            total_events=total,
            avg_news_value_score=avg_score,
            avg_china_relevance=avg_relevance,
            by_classification=dict(by_classification),
            by_source=dict(by_source),
            top_entities=[],
        )

    # ── 配置读取端点（无需认证）─────────────────────────

    async def get_target_config(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """读取指定 target 的完整配置。"""
        config_path = Path(f"config/targets/{target_id}.yaml")
        data = _config_cache.load_yaml(config_path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")
        return data

    async def list_sources(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> SourceListResponse:
        """列出指定 target 的所有源渠道。"""
        raw_sources = _load_source_configs(target_id)
        sources: list[SourceInfo] = []
        for s in raw_sources:
            sources.append(_source_info_from_config(s))
        return SourceListResponse(target_id=target_id, sources=sources)

    async def get_source_config(
        target_id: str,
        source_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """读取单个源渠道的完整配置。"""
        data = _load_single_source(target_id, source_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source '{source_id}' not found for target '{target_id}'",
            )
        return data

    async def get_filter_rules(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> FilterRulesResponse:
        """读取指定 target 的过滤规则。"""
        filter_path = _config_base_dir() / "filters" / target_id / "default.yaml"
        data = _config_cache.load_yaml(filter_path)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Filter rules not found for target '{target_id}'",
            )
        keyword_rules = data.get("keyword_rules", [])
        if not isinstance(keyword_rules, list):
            keyword_rules = []
        return FilterRulesResponse(
            target_id=target_id,
            score_threshold=data.get("score_threshold"),
            max_age_hours=data.get("max_age_hours"),
            dedup_window_hours=data.get("dedup_window_hours"),
            keyword_rules_count=len(keyword_rules),
            keyword_rules=keyword_rules,
        )

    async def list_destinations(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> DestinationListResponse:
        """读取所有输出目的地配置。"""
        dest_path = _config_base_dir() / "output" / "destinations.yaml"
        data = _config_cache.load_yaml(dest_path)
        if data is None:
            return DestinationListResponse(destinations=[])
        raw_dests = data.get("destinations", [])
        if not isinstance(raw_dests, list):
            raw_dests = []
        destinations: list[DestinationInfo] = []
        for d in raw_dests:
            if not isinstance(d, dict):
                continue
            destinations.append(
                DestinationInfo(
                    destination_id=d.get("destination_id", ""),
                    type=d.get("type", ""),
                    enabled=d.get("enabled", False),
                    filter_min_news_value_score=d.get("filter", {}).get("min_news_value_score")
                    if isinstance(d.get("filter"), dict)
                    else None,
                    filter_min_china_relevance=d.get("filter", {}).get("min_china_relevance")
                    if isinstance(d.get("filter"), dict)
                    else None,
                    notes=d.get("notes"),
                )
            )
        return DestinationListResponse(destinations=destinations)

    async def get_provider_routes(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> ProviderRoutesResponse:
        """读取 AI Provider 路由配置。"""
        routes_path = _config_base_dir() / "provider" / "routes.yaml"
        data = _config_cache.load_yaml(routes_path)
        if data is None:
            raise HTTPException(status_code=404, detail="Provider routes not found")
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raw_routes = []
        routes: list[RouteInfo] = []
        for r in raw_routes:
            if not isinstance(r, dict):
                continue
            routes.append(
                RouteInfo(
                    route_id=r.get("route_id", ""),
                    task_type=r.get("task_type", ""),
                    provider=r.get("provider", ""),
                    model=r.get("model", ""),
                    model_env_var=r.get("model_env_var"),
                    model_pool=r.get("model_pool", []) or [],
                    timeout_seconds=r.get("timeout_seconds", 30),
                    max_cost_usd_per_call=r.get("max_cost_usd_per_call", 0.0),
                    audit=r.get("audit", False),
                    fallback_route_ids=r.get("fallback_route_ids", []) or [],
                )
            )
        return ProviderRoutesResponse(
            routes_version=data.get("routes_version", ""),
            routes=routes,
            fallback_route_id=data.get("fallback_route_id"),
        )

    # ── 实体端点 ────────────────────────────────────────

    # Lazy-imported to avoid circular dependencies at module level
    from news_sentry.core.canonical_handlers import (
        canonical_backfill as _canonical_backfill_fn,
    )
    from news_sentry.core.canonical_handlers import (
        canonical_diagnostics as _canonical_diagnostics_fn,
    )
    from news_sentry.core.canonical_handlers import (
        create_research_artifact as _create_research_artifact_fn,
    )
    from news_sentry.core.canonical_handlers import (
        export_canonical_event_markdown as _export_canonical_event_markdown_fn,
    )
    from news_sentry.core.canonical_handlers import (
        get_canonical_event as _get_canonical_event_fn,
    )
    from news_sentry.core.canonical_handlers import (
        list_canonical_event_mentions as _list_canonical_event_mentions_fn,
    )
    from news_sentry.core.canonical_handlers import (
        list_canonical_event_relations as _list_canonical_event_relations_fn,
    )
    from news_sentry.core.canonical_handlers import (
        list_canonical_events as _list_canonical_events_fn,
    )
    from news_sentry.core.canonical_handlers import (
        list_research_artifacts_handler as _list_research_artifacts_handler_fn,
    )
    from news_sentry.core.canonical_handlers import (
        patch_research_artifact as _patch_research_artifact_fn,
    )
    from news_sentry.core.canonical_handlers import (
        research_event_detail as _research_event_detail_fn,
    )
    from news_sentry.core.canonical_handlers import (
        research_graph_merge as _research_graph_merge_fn,
    )
    from news_sentry.core.canonical_handlers import (
        research_graph_operations as _research_graph_operations_fn,
    )
    from news_sentry.core.canonical_handlers import (
        research_graph_split as _research_graph_split_fn,
    )
    from news_sentry.core.canonical_handlers import (
        research_queue as _research_queue_fn,
    )
    from news_sentry.core.entity_handlers import (
        annotation_create_annotation,
        annotation_delete_annotation,
        annotation_list_annotations,
        annotation_review_annotation,
        annotation_update_annotation,
        entity_get_entity,
        entity_get_entity_events,
        entity_list_entities,
        entity_merge_entities,
        entity_search_entities,
        notification_list_notification_rules,
        notification_upsert_notification_rule,
    )
    from news_sentry.core.maintenance_handlers import (
        list_backups as _list_backups_fn,
    )
    from news_sentry.core.maintenance_handlers import (
        maintenance_archive_duplicate_drafts as _maintenance_archive_duplicate_drafts_fn,
    )
    from news_sentry.core.maintenance_handlers import (
        maintenance_backup as _maintenance_backup_fn,
    )
    from news_sentry.core.maintenance_handlers import (
        maintenance_draft_diagnostics as _maintenance_draft_diagnostics_fn,
    )
    from news_sentry.core.maintenance_handlers import (
        maintenance_prune as _maintenance_prune_fn,
    )
    from news_sentry.core.maintenance_handlers import (
        restore_backup as _restore_backup_fn,
    )

    async def list_entities(
        entity_type: str | None = Query(None, description="按实体类型过滤"),
        target_id: str | None = Query(None, description="按目标过滤"),
        min_mentions: int = Query(1, ge=1, description="最少提及次数"),
        limit: int = Query(20, ge=1, le=100, description="返回数量"),
        sort: str = Query("mention_count", description="排序: mention_count 或 last_seen"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EntityListResponse:
        """返回实体列表（优先使用 target state.db）。"""
        return await entity_list_entities(
            store=_store,
            get_target_store=_get_target_store,
            entity_type=entity_type,
            target_id=target_id,
            min_mentions=min_mentions,
            limit=limit,
            sort=sort,
            user=user,
        )

    async def get_entity(
        entity_id: int,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EntityDetailResponse:
        """返回实体详情及关联事件。"""
        return await entity_get_entity(store=_store, entity_id=entity_id, user=user)

    async def search_entities(
        q: str = Query(..., min_length=1, description="搜索关键词"),
        limit: int = Query(20, ge=1, le=100, description="返回数量"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EntityListResponse:
        """FTS5 全文搜索实体。"""
        return await entity_search_entities(store=_store, q=q, limit=limit, user=user)

    async def merge_entities(
        body: EntityMergeRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EntityMergeResponse:
        """合并两个实体。"""
        return await entity_merge_entities(store=_store, body=body, user=user)

    async def get_entity_events(
        entity_id: int,
        limit: int = Query(50, ge=1, le=200, description="返回数量"),
        offset: int = Query(0, ge=0, description="偏移量"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """获取实体关联的所有事件（分页）。"""
        return await entity_get_entity_events(
            store=_store, entity_id=entity_id, limit=limit, offset=offset, user=user,
        )

    async def create_annotation(
        body: AnnotationCreateRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> AnnotationInfo:
        """写入一条人工注解记录。"""
        return await annotation_create_annotation(store=_store, body=body, user=user)

    async def list_annotations(
        entity_id: int | None = Query(None, description="实体ID"),
        event_id: str | None = Query(None, description="事件ID"),
        reviewed: bool | None = Query(None, description="审核状态"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> AnnotationListResponse:
        """列出注解记录（可按实体/事件/审核状态筛选）。"""
        return await annotation_list_annotations(
            store=_store,
            entity_id=entity_id,
            event_id=event_id,
            reviewed=reviewed,
            limit=limit,
            offset=offset,
            user=user,
        )

    async def update_annotation(
        annotation_id: int,
        body: AnnotationUpdateRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> AnnotationInfo:
        """更新注解内容。"""
        return await annotation_update_annotation(
            store=_store, annotation_id=annotation_id, body=body, user=user,
        )

    async def delete_annotation(
        annotation_id: int,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, str]:
        """删除一条注解记录。"""
        return await annotation_delete_annotation(
            store=_store, annotation_id=annotation_id, user=user,
        )

    async def review_annotation(
        annotation_id: int,
        body: dict[str, Any],
        user: dict[str, Any] = Depends(get_current_user),
    ) -> AnnotationInfo:
        """标记注解审核状态。"""
        return await annotation_review_annotation(
            store=_store, annotation_id=annotation_id, body=body, user=user,
        )

    # ── Notification Rules (R1) ────────────────────────

    async def upsert_notification_rule(
        body: NotificationRuleRequest,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> NotificationRuleInfo:
        """创建或更新通知规则。"""
        result = await notification_upsert_notification_rule(
            store=_store, body=body, user=user,
        )
        return NotificationRuleInfo(**result)

    async def list_notification_rules(
        user_id: str | None = Query(None, description="按用户筛选"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> NotificationRuleListResponse:
        """列出通知规则。"""
        rules = await notification_list_notification_rules(
            store=_store, user_id=user_id, user=user,
        )
        return NotificationRuleListResponse(
            rules=[NotificationRuleInfo(**r) for r in rules],
            total=len(rules),
        )

    async def delete_notification_rule(
        rule_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """删除通知规则。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not ready")
        # 安全校验：只允许删除自己的规则
        rules = await _store.list_notification_rules(user_id=user.get("sub", ""))
        if not any(r["id"] == rule_id for r in rules):
            raise HTTPException(status_code=403, detail="Not your rule")
        deleted = await _store.delete_notification_rule(rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"deleted": True, "rule_id": rule_id}

    # ── 需认证端点 ────────────────────────────────────

    async def get_today_stats_api(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> TodayStatsResponse:
        """今日 vs 昨日对比统计。"""
        store_to_query = await _store_for_target(target_id)
        if store_to_query is None:
            return TodayStatsResponse(target_id=target_id)
        stats = await store_to_query.get_today_stats(target_id)
        return TodayStatsResponse(target_id=target_id, **stats)

    async def get_top_events_api(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(7, ge=1, le=30, description="天数"),
        limit: int = Query(5, ge=1, le=20, description="数量"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> TopEventsResponse:
        """近期高价值事件（优先使用 target state.db）。"""
        events: list[dict[str, Any]] = []
        store_to_query = await _store_for_target(target_id)
        if store_to_query is not None:
            events = await store_to_query.get_top_events(target_id, days=days, limit=limit)
        return TopEventsResponse(
            target_id=target_id,
            events=[TopEventInfo(**e) for e in events],
        )

    async def list_events(
        target_id: str = Query(..., description="目标标识"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        stage: str | None = Query(None, description="按审核阶段筛选: drafts/reviewed/published"),
        classification: str | None = Query(None, description="按 classification.l0 筛选"),
        source_id: str | None = Query(None, description="按 source_id 筛选"),
        min_score: int | None = Query(None, description="最低 news_value_score"),
        search: str | None = Query(None, description="在 title_original 中搜索关键词"),
        sentiment: str | None = Query(
            None, description="按 sentiment 筛选 (positive/negative/neutral)"
        ),
        entity: str | None = Query(None, description="按实体名筛选"),
        topic_tag: str | None = Query(None, description="按主题标签筛选"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EventResponse:
        from news_sentry.core import events_handlers
        return cast(EventResponse, await events_handlers.list_events_handler(
            _data_dir,
            _get_target_store,
            _store,
            _visible_index_events_page,
            _load_events_from_data,
            _store_has_target_event_index,
            target_id=target_id,
            page=page,
            page_size=page_size,
            stage=stage,
            classification=classification,
            source_id=source_id,
            min_score=min_score,
            search=search,
            sentiment=sentiment,
            entity=entity,
            topic_tag=topic_tag,
        ))

    # ── 新闻流 Feed API ─────────────────────────────────────

    async def events_feed(
        target_id: str = Query(..., description="目标标识"),
        date: str | None = Query(None, description="日期筛选 YYYY-MM-DD"),
        page: int = Query(1, ge=1),
        page_size: int = Query(30, ge=1, le=100),
    ) -> dict[str, Any]:
        """新闻流接口 — 按日期分组返回事件，含 AI 推荐标签。"""
        from news_sentry.core import events_handlers
        return await events_handlers.events_feed_handler(
            _data_dir,
            _get_target_store,
            _store,
            _visible_index_events_page,
            _load_events_from_data,
            _group_events_by_date,
            _store_has_target_event_index,
            target_id=target_id,
            date=date,
            page=page,
            page_size=page_size,
        )

    async def export_public_event_markdown(
        target_id: str,
        event_id: str,
    ) -> Response:
        """公开单篇新闻 Markdown 下载投影，不写入磁盘。"""
        from news_sentry.core import public_handlers
        return await public_handlers.export_public_event_markdown_handler(
            _data_dir,
            _store,
            _get_target_store,
            _markdown_download_response,
            target_id,
            event_id,
        )

    # ── SSE 实时推送 ─────────────────────────────────────

    async def event_stream(
        request: Request,
        target_id: str = Query(..., description="目标标识"),
        stream_token: str | None = Query(
            None,
            description="Short-lived SSE token for EventSource connections",
        ),
    ) -> StreamingResponse:
        """SSE 端点：推送新事件通知到浏览器。

        EventSource 无法设置 Authorization 头，因此支持短期 stream token 查询参数。
        优先使用 Authorization 头，无头时检查 stream_token 参数。

        客户端通过 EventSource 连接，每 15s 发送心跳保活。
        当有新事件通过 Webhook 或 Import 到达时，推送事件摘要。
        """

        # 手动认证：支持 Authorization 头 和短期 stream token 两种方式
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header.replace("Bearer ", "").strip()
        if not _local_auth_bypass_enabled(request):
            info: dict[str, Any] | None = None
            if bearer:
                info = await _verify_token_async(bearer)
            elif stream_token:
                info = _verify_stream_token(stream_token)
            if not info:
                raise HTTPException(status_code=401, detail="Invalid or expired token")

        queue: asyncio.Queue[Any] = asyncio.Queue()
        async with _sse_lock:
            _sse_queues[target_id].append(queue)

        async def _cleanup() -> None:
            async with _sse_lock:
                queues = _sse_queues.get(target_id, [])
                if queue in queues:
                    queues.remove(queue)

        async def _generate() -> AsyncGenerator[str, None]:
            try:
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15)
                        payload = json.dumps(data["payload"], ensure_ascii=False)
                        yield f"event: {data['event']}\ndata: {payload}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"  # 心跳保活
            finally:
                await _cleanup()

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def get_event(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> dict[str, Any]:
        from news_sentry.core import events_handlers
        return await events_handlers.get_event_handler(
            _data_dir,
            _get_target_store,
            _store,
            _load_indexed_event_detail,
            _load_single_event,
            _store_has_target_event_index,
            event_id=event_id,
            target_id=target_id,
        )

    async def receive_webhook(
        payload: WebhookPayload,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> WebhookResponse:
        _validate_target_slug(target_id)
        event_id = _save_webhook_event(_data_dir, target_id, payload)
        sse_data: dict[str, Any] = {"event_id": event_id, "source": "webhook"}
        asyncio.ensure_future(_notify_sse_clients(target_id, "new_event", sse_data))
        return WebhookResponse(
            status="accepted",
            event_id=event_id,
            message=f"Event {event_id} saved to {target_id}/raw/",
        )

    async def import_events(
        events: list[ImportEventItem],
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> ImportResponse:
        """批量导入外部事件。

        接受 JSON 数组，逐条写入 data/{target_id}/raw/ 并索引到 SQLite。
        已存在的事件（event_id 相同）会被跳过。
        """
        from news_sentry.core import events_handlers
        return cast(ImportResponse, await events_handlers.import_events_handler(
            _store,
            _data_dir,
            _validate_target_slug,
            _validate_source_slug,
            _notify_sse_clients,
            events,
        ))

    async def reload_config(
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, str]:
        """清除配置缓存，下次请求时重新从文件加载。"""
        _config_cache.reload()
        return {"status": "ok", "message": "Configuration cache cleared"}

    # ── M-35.2: 事件审核阶段转换 ───────────────────────────

    async def transition_event_stage(
        event_id: str,
        body: TransitionEventRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> TransitionEventResponse:
        """将事件在 drafts → reviewed → published 之间转换。

        读取原事件文件，更新 review_stage，移动目录，同步更新 SQLite 索引。
        """
        from news_sentry.core import events_handlers
        return cast(TransitionEventResponse, await events_handlers.transition_event_stage_handler(
            _store,
            _data_dir,
            _store_for_target,
            event_id=event_id,
            body=body,
        ))

    # ── Phase 42: 配置写入端点 ────────────────────────────

    async def update_target_config(
        target_id: str,
        body: TargetConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        _config_cache.clear()

        return merged

    async def update_source_config(
        target_id: str,
        source_id: str,
        body: SourceConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        _config_cache.clear()

        return merged

    async def update_filter_config(
        target_id: str,
        body: FilterConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        _config_cache.clear()

        return merged

    async def update_destination_config(
        destination_id: str,
        body: DestinationConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        _config_cache.clear()

        return result

    async def update_provider_route(
        route_id: str,
        body: RouteConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        _config_cache.clear()

        return result

    # ── Phase 34: 运维端点 ────────────────────────────────

    async def list_runs(
        target_id: str = Query(..., description="目标标识"),
        limit: int = Query(20, ge=1, le=100),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> RunListResponse:
        runs = _load_run_logs(_data_dir, target_id, limit)
        return RunListResponse(runs=[RunInfo(**r) for r in runs])

    async def get_active_run(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> HeartbeatResponse:
        data = _load_heartbeat(_data_dir, target_id)
        return HeartbeatResponse(**data)

    async def get_run_detail(
        run_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> RunDetailResponse:
        data = _load_single_run_log(_data_dir, run_id, target_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return RunDetailResponse(
            run_id=data.get("run_id", run_id),
            target_id=data.get("target_id", target_id),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            phases=data.get("phases", []),
            errors_count=data.get("errors_count", 0),
            errors=data.get("errors", []),
            summary=data.get("summary", {}),
        )

    async def list_source_health(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> SourceHealthListResponse:
        records = await _source_health_records_for_target(target_id)
        return SourceHealthListResponse(sources=[SourceHealthInfo(**r) for r in records])

    async def trigger_run(
        target_id: str = Query(..., description="目标标识"),
        stage: str = Query("all", description="执行阶段"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> TriggerResponse:
        try:
            import asyncio
            import traceback

            from news_sentry.core.async_run import bounded_run_async

            run_id = f"{target_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

            async def _run_and_log() -> None:
                try:
                    await bounded_run_async(target_id=target_id, stage=stage, run_id=run_id)
                except Exception:
                    logger.exception(
                        "Pipeline run failed: run_id=%s target=%s stage=%s\n%s",
                        run_id,
                        target_id,
                        stage,
                        traceback.format_exc(),
                    )

            asyncio.create_task(_run_and_log())
            return TriggerResponse(
                status="triggered",
                run_id=run_id,
                message=f"Pipeline triggered for {target_id}/{stage}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # ── Phase 35: 追踪链端点 ──────────────────────────────

    async def get_event_links(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EventLinksResponse:
        """获取某事件的关联事件列表。"""
        from news_sentry.core import events_handlers
        return cast(EventLinksResponse, await events_handlers.get_event_links_handler(
            _store,
            event_id=event_id,
            target_id=target_id,
        ))

    async def get_event_chain(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EventChainResponse:
        """获取某事件的完整追踪链。"""
        from news_sentry.core import events_handlers
        return cast(EventChainResponse, await events_handlers.get_event_chain_handler(
            _store,
            event_id=event_id,
            target_id=target_id,
        ))

    async def list_chains(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> ChainListResponse:
        """列出当前 target 的活跃追踪链。"""
        if _store is None:
            return ChainListResponse(chains=[])
        chains = await _store.get_active_chains(target_id)
        return ChainListResponse(
            chains=[ChainSummaryInfo(**c) for c in chains],
        )

    async def get_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> NarrativeResponse:
        """获取链的 AI 叙述。"""
        if _store is None:
            raise HTTPException(status_code=404, detail="No narrative found")
        result = await _store.get_narrative(root_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Narrative not found")
        return NarrativeResponse(
            chain_root_id=result["chain_root_id"],
            narrative=result["narrative"],
            event_count=result["event_count"],
            model_used=result["model_used"],
            generated_at=result["updated_at"],
        )

    async def regenerate_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> NarrativeResponse:
        """手动重新生成链叙述。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            from news_sentry.core.async_run import _generate_narratives, _try_create_provider_router

            router = _try_create_provider_router()
            if router is None:
                raise HTTPException(status_code=503, detail="AI provider not configured")
            # 删除旧叙述强制重新生成
            if _store._db is not None:
                await _store._db.execute(
                    "DELETE FROM chain_narratives WHERE chain_root_id = ?", [root_id]
                )
                await _store._db.commit()
            await _generate_narratives(_store, target_id, router=router)
            result = await _store.get_narrative(root_id)
            if result is None:
                raise HTTPException(status_code=500, detail="Narrative generation failed")
            return NarrativeResponse(
                chain_root_id=result["chain_root_id"],
                narrative=result["narrative"],
                event_count=result["event_count"],
                model_used=result["model_used"],
                generated_at=result["updated_at"],
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def get_topic_trends(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(14, ge=7, le=30, description="天数"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> TopicTrendsResponse:
        """主题热度趋势。"""
        store_to_query = await _store_for_target(target_id)
        if store_to_query is None:
            return TopicTrendsResponse(
                target_id=target_id,
                days=days,
                topics=[],
                generated_at=datetime.now(UTC).isoformat(),
            )
        try:
            daily_counts = await store_to_query.get_topic_daily_counts(target_id, days=days)
            top_topics = await store_to_query.get_top_topics(target_id, days=days, limit=10)
            from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends

            topics = compute_topic_trends(daily_counts, top_topics, total_days=days)
            return TopicTrendsResponse(
                target_id=target_id,
                days=days,
                topics=[TopicTrendItem(**t.model_dump()) for t in topics],
                generated_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def get_sentiment_trends(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(14, ge=7, le=30, description="天数"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> SentimentTrendsResponse:
        """情感分布趋势。"""
        store_to_query = await _store_for_target(target_id)
        if store_to_query is None:
            return SentimentTrendsResponse(
                target_id=target_id,
                days=days,
                daily_sentiment=[],
                generated_at=datetime.now(UTC).isoformat(),
            )
        try:
            raw = await store_to_query.get_sentiment_daily_counts(target_id, days=days)
            # 转换为按天聚合
            day_map: dict[str, DailySentimentCount] = {}
            for entry in raw:
                d = entry["day"]
                if d not in day_map:
                    day_map[d] = DailySentimentCount(day=d)
                item = day_map[d]
                sentiment = entry["sentiment"]
                if sentiment == "positive":
                    item.positive = entry["count"]
                elif sentiment == "negative":
                    item.negative = entry["count"]
                elif sentiment == "neutral":
                    item.neutral = entry["count"]
            daily = sorted(day_map.values(), key=lambda x: x.day)
            return SentimentTrendsResponse(
                target_id=target_id,
                days=days,
                daily_sentiment=daily,
                generated_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    async def get_smart_alerts(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> SmartAlertsResponse:
        """获取智能告警列表。"""
        store_to_query = await _store_for_target(target_id)
        if store_to_query is None:
            return SmartAlertsResponse(target_id=target_id, alerts=[], total=0)
        try:
            from news_sentry.core.alert_pipeline import AlertPipeline

            pipeline = AlertPipeline([])
            alerts = await pipeline.check_smart_alerts(store_to_query, target_id)
            return SmartAlertsResponse(
                target_id=target_id,
                alerts=[SmartAlertItem(**a) for a in alerts],
                total=len(alerts),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # ── Canonical projection endpoints ─────────────────

    async def canonical_diagnostics(
        target_id: str,
        since: str | None = None,
        limit: int = Query(500, ge=1, le=5000),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _canonical_diagnostics_fn(
            get_target_store=_get_target_store,
            target_id=target_id,
            since=since,
            limit=limit,
        )

    async def canonical_backfill(
        payload: CanonicalBackfillRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _canonical_backfill_fn(
            get_target_store=_get_target_store,
            payload=payload,
        )

    async def list_canonical_events(
        target_id: str,
        limit: int = Query(50, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _list_canonical_events_fn(
            get_target_store=_get_target_store,
            target_id=target_id,
            limit=limit,
            offset=offset,
            status=status,
        )

    async def get_canonical_event(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _get_canonical_event_fn(
            get_target_store=_get_target_store,
            canonical_event_id=canonical_event_id,
            target_id=target_id,
        )

    async def list_canonical_event_mentions(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _list_canonical_event_mentions_fn(
            get_target_store=_get_target_store,
            canonical_event_id=canonical_event_id,
            target_id=target_id,
        )

    async def list_canonical_event_relations(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _list_canonical_event_relations_fn(
            get_target_store=_get_target_store,
            canonical_event_id=canonical_event_id,
            target_id=target_id,
        )

    async def export_canonical_event_markdown(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> Response:
        return await _export_canonical_event_markdown_fn(
            get_target_store=_get_target_store,
            markdown_download_response=_markdown_download_response,
            canonical_event_id=canonical_event_id,
            target_id=target_id,
        )

    # ── Research workflow endpoints ────────────────────

    # ── Research workflow endpoints ────────────────────

    async def research_queue(
        target_id: str,
        status: str = Query("open", pattern="^(open|resolved|all)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _research_queue_fn(
            get_target_store=_get_target_store,
            target_id=target_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def research_graph_merge(
        payload: ResearchGraphMergeRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _research_graph_merge_fn(
            get_target_store=_get_target_store,
            payload=payload,
            user=user,
        )

    async def research_graph_split(
        payload: ResearchGraphSplitRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _research_graph_split_fn(
            get_target_store=_get_target_store,
            payload=payload,
            user=user,
        )

    async def research_graph_operations(
        target_id: str,
        operation_type: str | None = Query(None, pattern="^(merge|split)$"),
        decision_artifact_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _research_graph_operations_fn(
            get_target_store=_get_target_store,
            target_id=target_id,
            operation_type=operation_type,
            decision_artifact_id=decision_artifact_id,
            limit=limit,
            offset=offset,
        )

    async def research_event_detail(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _research_event_detail_fn(
            get_target_store=_get_target_store,
            canonical_event_id=canonical_event_id,
            target_id=target_id,
        )

    async def list_research_artifacts(
        target_id: str,
        subject_type: str = Query("canonical_event", pattern="^canonical_event$"),
        subject_id: str | None = None,
        artifact_type: str | None = Query(
            None,
            pattern="^(review_state|annotation|note|merge_decision|split_decision)$",
        ),
        status: str | None = Query(None, pattern="^(open|resolved|archived)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _list_research_artifacts_handler_fn(
            get_target_store=_get_target_store,
            target_id=target_id,
            subject_type=subject_type,
            subject_id=subject_id,
            artifact_type=artifact_type,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def create_research_artifact(
        payload: ResearchArtifactCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _create_research_artifact_fn(
            get_target_store=_get_target_store,
            new_artifact_id_fn=_new_research_artifact_id,
            validate_metadata_fn=_validate_research_metadata,
            payload=payload,
            user=user,
        )

    async def patch_research_artifact(
        artifact_id: str,
        target_id: str,
        payload: ResearchArtifactPatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _patch_research_artifact_fn(
            get_target_store=_get_target_store,
            validate_metadata_fn=_validate_research_metadata,
            artifact_id=artifact_id,
            target_id=target_id,
            payload=payload,
        )

    # ── 维护端点 (Phase 40) ─────────────────────────────

    async def maintenance_draft_diagnostics(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _maintenance_draft_diagnostics_fn(
            draft_diagnostics_fn=_draft_diagnostics,
            data_dir=_data_dir,
            target_id=target_id,
        )

    async def maintenance_archive_duplicate_drafts(
        target_id: str = Query(..., description="目标标识"),
        dry_run: bool = Query(False, description="仅返回计划，不移动文件"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        return await _maintenance_archive_duplicate_drafts_fn(
            archive_fn=_archive_duplicate_drafts,
            data_dir=_data_dir,
            target_id=target_id,
            dry_run=dry_run,
        )

    async def maintenance_prune(
        target_id: str = Query(..., description="目标标识"),
        max_age_days: int = Query(30, ge=7, le=365, description="保留天数"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> PruneResponse:
        result = await _maintenance_prune_fn(
            store=_store,
            target_id=target_id,
            max_age_days=max_age_days,
        )
        return PruneResponse(**result)

    async def maintenance_backup(
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> BackupResponse:
        result = await _maintenance_backup_fn(store=_store)
        return BackupResponse(**result)

    async def list_backups(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        return await _list_backups_fn(store=_store)

    async def restore_backup(
        filename: str = Query(..., description="备份文件名"),
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        return await _restore_backup_fn(
            store=_store,
            filename=filename,
        )

    # ── 反馈闭环 + 告警管理 (Phase 41) ──────────────────

    async def submit_feedback(
        req: FeedbackSubmitRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> FeedbackSubmitResponse:
        """提交人工反馈。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        event = await _store.get_event_by_id(req.target_id, req.event_id)
        original_rec = None
        source_id = None
        if event:
            original_rec = event.get("original_recommendation")
            source_id = event.get("source_id")
        row_id = await _store.save_feedback(
            target_id=req.target_id,
            event_id=req.event_id,
            verdict_type=req.verdict_type,
            comment=req.comment,
            original_recommendation=original_rec,
            source_id=source_id,
        )
        return FeedbackSubmitResponse(
            id=row_id, event_id=req.event_id, verdict_type=req.verdict_type
        )

    async def list_feedback(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> FeedbackListResponse:
        """获取反馈列表。"""
        if _store is None:
            return FeedbackListResponse(feedback=[], total=0)
        items = await _store.get_feedback(target_id)
        feedback = [
            FeedbackItem(
                id=f["id"],
                event_id=f["event_id"],
                target_id=f["target_id"],
                verdict_type=f["verdict_type"],
                original_recommendation=f.get("original_recommendation"),
                comment=f.get("comment"),
                keywords_matched=f.get("keywords_matched"),
                source_id=f.get("source_id"),
                created_at=f.get("created_at"),
            )
            for f in items
        ]
        return FeedbackListResponse(feedback=feedback, total=len(feedback))

    async def feedback_stats(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> FeedbackStatsResponse:
        """获取反馈统计。"""
        if _store is None:
            return FeedbackStatsResponse(total=0, publish_override=0, archive_override=0, comment=0)
        stats = await _store.get_feedback_stats(target_id)
        return FeedbackStatsResponse(**stats)

    async def optimize_rules(
        req: RulesOptimizeRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> RulesOptimizeResponse:
        """触发规则优化。"""
        filter_yaml = (_config_base_dir() / "filters" / req.target_id / "default.yaml").resolve()
        if not filter_yaml.exists():
            raise HTTPException(status_code=404, detail=f"Filter config not found: {filter_yaml}")
        from news_sentry.core.rules_optimizer import RulesOptimizer

        import news_sentry.core._state as _st2
        data_dir = _st2._data_dir / req.target_id if _st2._data_dir else Path("data") / req.target_id
        optimizer = RulesOptimizer(filter_yaml, data_dir)
        result = optimizer.optimize(dry_run=req.dry_run)
        return RulesOptimizeResponse(
            total_verdicts=result["total_verdicts"],
            adjustments=result["adjustments"],
            adjustments_detail=result["adjustments_detail"],
            written=result["written"],
        )

    async def alert_history(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> AlertHistoryResponse:
        """获取告警历史。"""
        if _store is None:
            return AlertHistoryResponse(alerts=[], total=0)
        items = await _store.get_alert_history(target_id)
        alerts = [
            AlertHistoryItem(
                id=a["id"],
                target_id=a["target_id"],
                alert_type=a["alert_type"],
                severity=a["severity"],
                message=a["message"],
                details=a.get("details"),
                created_at=a.get("created_at"),
            )
            for a in items
        ]
        return AlertHistoryResponse(alerts=alerts, total=len(alerts))


    # ── 路由注册（通过 APIRouter）──────────────────
    from news_sentry.api.routes.admin import register_admin_routes
    from news_sentry.api.routes.canonical import register_canonical_routes
    from news_sentry.api.routes.entities import register_entity_routes
    from news_sentry.api.routes.maintenance import register_maintenance_routes
    from news_sentry.api.routes.public import register_public_routes
    from news_sentry.api.routes.targets import register_target_routes

    public_router = APIRouter()
    admin_router = APIRouter()

    # 构建 handler + response_model 字典
    _public_handlers = {
        "health": health,
        "global_diagnostics": global_diagnostics,
        "index_html": index_html,
        "publication_reader_page": publication_reader_page,
        "admin_index_html": admin_index_html,
        "admin_path_html": admin_path_html,
        "robots_txt": robots_txt,
        "llms_txt": llms_txt,
        "sitemap_xml": sitemap_xml,
        "public_app_index": public_app_index,
        "public_app_asset": public_app_asset,
        "auth_login": auth_login,
        "auth_token": auth_token,
        "auth_logout": auth_logout,
        "auth_setup_status": auth_setup_status,
        "auth_setup": auth_setup,
        "list_targets": list_targets,
        "list_regions": list_regions,
        "get_public_target_analysis": get_public_target_analysis,
        "list_public_facets": list_public_facets,
        "subscribe": subscribe,
        "get_public_bootstrap": get_public_bootstrap,
        "list_public_news": list_public_news,
        "get_public_news_item": get_public_news_item,
        "list_events": list_events,
        "events_feed": events_feed,
        "event_stream": event_stream,
        "get_event": get_event,
        "list_research_artifacts": list_research_artifacts,
        # response_model classes
        "LoginResponse": LoginResponse,
        "TargetListResponse": TargetListResponse,
        "RegionListResponse": RegionListResponse,
        "PublicAnalysisResponse": PublicAnalysisResponse,
        "PublicFacetsResponse": PublicFacetsResponse,
        "PublicBootstrapResponse": PublicBootstrapResponse,
        "PublicNewsFeedResponse": PublicNewsFeedResponse,
        "PublicNewsItem": PublicNewsItem,
        "EventResponse": EventResponse,
    }
    register_public_routes(public_router, _public_handlers)

    _admin_handlers = {
        "prometheus_metrics": prometheus_metrics,
        "runtime_info": runtime_info,
        "collector_status": collector_status,
        "collector_config": collector_config,
        "update_collector_config": update_collector_config,
        "start_collector": start_collector,
        "stop_collector": stop_collector,
        "collector_diagnostics": collector_diagnostics,
        "ai_enrichment_status": ai_enrichment_status,
        "update_ai_enrichment_config": update_ai_enrichment_config,
        "run_ai_enrichment": run_ai_enrichment,
        "public_translation_status": public_translation_status,
        "update_public_translation_config": update_public_translation_config,
        "run_public_translation": run_public_translation,
        "data_status": data_status,
        "auth_stream_token": auth_stream_token,
        "auth_me": auth_me,
        "auth_change_password": auth_change_password,
        "admin_list_users": admin_list_users,
        "admin_create_user": admin_create_user,
        "admin_delete_user": admin_delete_user,
        "admin_reset_password": admin_reset_password,
        "get_api_key_setting": get_api_key_setting,
        "set_api_key_setting": set_api_key_setting,
        "delete_api_key_setting": delete_api_key_setting,
        "get_notifications": get_notifications,
        "update_notifications": update_notifications,
        "send_briefing": send_briefing,
        "list_admin_targets": list_admin_targets,
        "create_admin_target": create_admin_target,
        "patch_admin_target": patch_admin_target,
        "archive_admin_target": archive_admin_target,
        "restore_admin_target": restore_admin_target,
        "admin_target_overview": admin_target_overview,
        "validate_admin_target": validate_admin_target,
        "admin_target_inventory": admin_target_inventory,
        "list_admin_target_sources": list_admin_target_sources,
        "create_admin_target_source": create_admin_target_source,
        "patch_admin_target_source": patch_admin_target_source,
        "archive_admin_target_source": archive_admin_target_source,
        "restore_admin_target_source": restore_admin_target_source,
        "get_admin_target_social": get_admin_target_social,
        "create_admin_social_dimension": create_admin_social_dimension,
        "patch_admin_social_dimension": patch_admin_social_dimension,
        "create_admin_social_account": create_admin_social_account,
        "patch_admin_social_account": patch_admin_social_account,
        "admin_overview": admin_overview,
        "get_stats": get_stats,
        "get_today_stats_api": get_today_stats_api,
        "get_top_events_api": get_top_events_api,
        "get_target_config": get_target_config,
        "list_sources": list_sources,
        "get_source_config": get_source_config,
        "get_filter_rules": get_filter_rules,
        "list_destinations": list_destinations,
        "get_provider_routes": get_provider_routes,
        "update_target_config": update_target_config,
        "update_source_config": update_source_config,
        "update_filter_config": update_filter_config,
        "update_destination_config": update_destination_config,
        "update_provider_route": update_provider_route,
        "reload_config": reload_config,
        "list_entities": list_entities,
        "get_entity": get_entity,
        "search_entities": search_entities,
        "merge_entities": merge_entities,
        "get_entity_events": get_entity_events,
        "create_annotation": create_annotation,
        "list_annotations": list_annotations,
        "update_annotation": update_annotation,
        "delete_annotation": delete_annotation,
        "review_annotation": review_annotation,
        "upsert_notification_rule": upsert_notification_rule,
        "list_notification_rules": list_notification_rules,
        "delete_notification_rule": delete_notification_rule,
        "receive_webhook": receive_webhook,
        "import_events": import_events,
        "transition_event_stage": transition_event_stage,
        "list_runs": list_runs,
        "get_active_run": get_active_run,
        "get_run_detail": get_run_detail,
        "list_source_health": list_source_health,
        "trigger_run": trigger_run,
        "get_event_links": get_event_links,
        "get_event_chain": get_event_chain,
        "list_chains": list_chains,
        "get_chain_narrative": get_chain_narrative,
        "regenerate_chain_narrative": regenerate_chain_narrative,
        "get_topic_trends": get_topic_trends,
        "get_sentiment_trends": get_sentiment_trends,
        "get_smart_alerts": get_smart_alerts,
        "alert_history": alert_history,
        "canonical_diagnostics": canonical_diagnostics,
        "canonical_backfill": canonical_backfill,
        "list_canonical_events": list_canonical_events,
        "get_canonical_event": get_canonical_event,
        "list_canonical_event_mentions": list_canonical_event_mentions,
        "list_canonical_event_relations": list_canonical_event_relations,
        "export_canonical_event_markdown": export_canonical_event_markdown,
        "research_queue": research_queue,
        "research_graph_merge": research_graph_merge,
        "research_graph_split": research_graph_split,
        "research_graph_operations": research_graph_operations,
        "research_event_detail": research_event_detail,
        "create_research_artifact": create_research_artifact,
        "patch_research_artifact": patch_research_artifact,
        "maintenance_draft_diagnostics": maintenance_draft_diagnostics,
        "maintenance_archive_duplicate_drafts": maintenance_archive_duplicate_drafts,
        "maintenance_prune": maintenance_prune,
        "maintenance_backup": maintenance_backup,
        "list_backups": list_backups,
        "restore_backup": restore_backup,
        "submit_feedback": submit_feedback,
        "list_feedback": list_feedback,
        "feedback_stats": feedback_stats,
        "optimize_rules": optimize_rules,
        # response_model classes
        "StatsResponse": StatsResponse,
        "TodayStatsResponse": TodayStatsResponse,
        "TopEventsResponse": TopEventsResponse,
        "SourceListResponse": SourceListResponse,
        "FilterRulesResponse": FilterRulesResponse,
        "DestinationListResponse": DestinationListResponse,
        "ProviderRoutesResponse": ProviderRoutesResponse,
        "EntityListResponse": EntityListResponse,
        "EntityDetailResponse": EntityDetailResponse,
        "EntityMergeResponse": EntityMergeResponse,
        "AnnotationListResponse": AnnotationListResponse,
        "NotificationRuleListResponse": NotificationRuleListResponse,
        "WebhookResponse": WebhookResponse,
        "ImportResponse": ImportResponse,
        "RunListResponse": RunListResponse,
        "HeartbeatResponse": HeartbeatResponse,
        "RunDetailResponse": RunDetailResponse,
        "SourceHealthListResponse": SourceHealthListResponse,
        "TriggerResponse": TriggerResponse,
        "EventLinksResponse": EventLinksResponse,
        "EventChainResponse": EventChainResponse,
        "ChainListResponse": ChainListResponse,
        "NarrativeResponse": NarrativeResponse,
        "TopicTrendsResponse": TopicTrendsResponse,
        "SentimentTrendsResponse": SentimentTrendsResponse,
        "SmartAlertsResponse": SmartAlertsResponse,
        "AlertHistoryResponse": AlertHistoryResponse,
        "PruneResponse": PruneResponse,
        "BackupResponse": BackupResponse,
        "FeedbackSubmitResponse": FeedbackSubmitResponse,
        "FeedbackListResponse": FeedbackListResponse,
        "FeedbackStatsResponse": FeedbackStatsResponse,
        "RulesOptimizeResponse": RulesOptimizeResponse,
    }
    register_admin_routes(admin_router, _admin_handlers)
    register_canonical_routes(admin_router, _admin_handlers)
    register_entity_routes(admin_router, _admin_handlers)
    register_maintenance_routes(admin_router, _admin_handlers)
    register_target_routes(admin_router, _admin_handlers)

    app.include_router(admin_router)
    app.include_router(public_router)
    app.include_router(ws_router)
    app.include_router(webhook_router)

    _mount_spa_routes(app)

    return app

