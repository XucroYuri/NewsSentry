"""从 api_server.py 的 create_app() 闭包中提取的 public API endpoint handler 逻辑。

每个异步函数接收 store、data_dir、get_target_store 和缓存字典作为前几个参数，
后接 query/path/body 参数。FastAPI 注解（Query、Depends 等）保留在 create_app() 的瘦闭包内。

模式遵循 canonical_handlers.py、maintenance_handlers.py、entity_handlers.py。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from news_sentry.api.schemas import (
    PublicAnalysisResponse,
    PublicBootstrapResponse,
    PublicFacetsResponse,
    PublicNewsFeedResponse,
    PublicNewsItem,
    RegionListResponse,
    TargetListResponse,
)
from news_sentry.core import target_config_utils
from news_sentry.core._state import InvisibleIndexedEvent
from news_sentry.core.event_io_utils import (
    _load_all_events,
    _load_indexed_event_detail,
    _load_single_event,
    _render_public_event_markdown,
)
from news_sentry.core.public_news_utils import (
    _event_issue_tags,
    _event_public_translation_ready,
    _event_related_tags,
    _load_public_projection_detail,
    _public_analysis_from_store,
    _public_bootstrap_cache_headers,
    _public_cache_entry_valid,
    _public_distributions_from_events,
    _public_events_within_window,
    _public_facet_items,
    _public_news_cache_entry_valid,
    _public_news_cache_headers,
    _public_news_candidate_events,
    _public_news_decode_cursor,
    _public_news_encode_cursor,
    _public_news_etag,
    _public_news_feed_cache_key,
    _public_news_feed_cache_ttl,
    _public_news_item,
    _public_news_log_slow_miss,
    _public_news_matches,
    _public_news_sort_key,
    _public_news_target_ids,
    _public_payload_etag,
    _public_region_facet_items,
    _public_shared_cache_headers,
    _public_summary_from_events,
    _target_display_name,
)
from news_sentry.core.target_config_utils import (
    _region_info_from_config,
    _target_info_from_config,
    _target_is_archived,
    _target_is_public_region,
)

logger = logging.getLogger(__name__)

# ── 常量（从 api_server.py 模块层提取）─────────────────────────────
_PUBLIC_NEWS_MAX_SCAN = 300
_PUBLIC_NEWS_MIN_SCAN = 80
_PUBLIC_NEWS_DEFAULT_PAGE_SIZE = 30
_PUBLIC_NEWS_MAX_PAGE_SIZE = 100
_PUBLIC_NEWS_MIN_POLL_AFTER_MS = 30_000
_PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS = 60_000
_PUBLIC_NEWS_IDLE_POLL_AFTER_MS = 180_000

_PUBLIC_REGIONS_CACHE_TTL_SECONDS = 60.0
_PUBLIC_FACETS_CACHE_TTL_SECONDS = 60.0
_PUBLIC_BOOTSTRAP_CACHE_TTL_SECONDS = 300.0


# ═══════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════

async def _store_has_target_event_index(store: Any, target_id: str) -> bool:
    """检查 store 对于给定 target 是否有事件索引（轻量检查）。"""
    try:
        get_count = getattr(store, "count_events", None)
        if get_count is None:
            return False
        count = await get_count(target_id)
        return int(count or 0) > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# Public Regions
# ═══════════════════════════════════════════════════════════════════════


async def public_regions_payload(
    data_dir: Any,
    store: Any,  # 仅用于缓存键中的 id(store)
    *,
    include_empty: bool = False,
) -> RegionListResponse:
    configs = target_config_utils._load_target_configs()
    event_counts = await target_config_utils._public_target_event_counts(data_dir)
    regions = []
    for config in configs:
        if _target_is_archived(config) or not _target_is_public_region(config):
            continue
        region = _region_info_from_config(config, data_dir)
        if region.region_id:
            region = region.model_copy(
                update={"event_count": event_counts.get(region.region_id, 0)}
            )
        if region.source_count <= 0:
            continue
        if not include_empty and region.event_count <= 0:
            continue
        regions.append(region)
    return RegionListResponse(regions=regions)


async def cached_public_regions(
    data_dir: Any,
    store: Any,
    cache: dict[str, Any],
    ttl: int,
    regions_payload_fn: Any,
    response: Any | None = None,
    *,
    include_empty: bool = False,
) -> RegionListResponse:
    started = time.perf_counter()
    cache_key = f"{Path(data_dir).resolve()}:{id(store)}:regions:include_empty={int(include_empty)}"
    now = time.monotonic()
    cache_entry = cache.get(cache_key)
    if _public_cache_entry_valid(cache_entry, now):
        assert cache_entry is not None
        payload = cast(RegionListResponse, cache_entry["payload"])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        headers = _public_shared_cache_headers(
            etag=str(cache_entry["etag"]),
            cache_status="hit",
            timing_name="public-regions",
            header_name="Regions",
            elapsed_ms=elapsed_ms,
        )
        if response is not None:
            response.headers.update(headers)
        return payload

    payload = await regions_payload_fn(include_empty=include_empty)
    etag = _public_payload_etag("public-regions", payload)
    cache[cache_key] = {
        "etag": etag,
        "expires_at": time.monotonic() + ttl,
        "payload": payload,
    }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    headers = _public_shared_cache_headers(
        etag=etag,
        cache_status="miss",
        timing_name="public-regions",
        header_name="Regions",
        elapsed_ms=elapsed_ms,
    )
    if response is not None:
        response.headers.update(headers)
    return payload


# ═══════════════════════════════════════════════════════════════════════
# Public Facets
# ═══════════════════════════════════════════════════════════════════════


async def public_facets_payload(
    data_dir: Any,
    *,
    region_id: str | None,
    issue: str | None,
    related: str | None,
    date: str | None,
    q: str | None,
) -> PublicFacetsResponse:
    target_ids = _public_news_target_ids(data_dir, region_id)
    candidates, _total = await _public_news_candidate_events(
        data_dir,
        target_ids,
        limit=_PUBLIC_NEWS_MAX_SCAN,
        allow_projection_first=True,
        allow_file_fallback=region_id is not None,
        featured=False,
        source_id=None,
        category=None,
        date=date,
        q=q,
    )
    region_counts: dict[str, int] = defaultdict(int)
    issue_counts: dict[str, int] = defaultdict(int)
    related_counts: dict[str, int] = defaultdict(int)
    for tid, event in candidates:
        if not _public_news_matches(
            event,
            featured=False,
            source_id=None,
            category=None,
            issue=issue,
            related=related,
            date=date,
            q=q,
        ):
            continue
        region_counts[tid] += 1
        for tag in _event_issue_tags(event):
            issue_counts[tag] += 1
        for tag in _event_related_tags(event):
            related_counts[tag] += 1
    return PublicFacetsResponse(
        regions=_public_region_facet_items(region_counts),
        issues=_public_facet_items(issue_counts),
        related=_public_facet_items(related_counts),
    )


async def cached_public_facets(
    data_dir: Any,
    store: Any,
    cache: dict[str, Any],
    ttl: int,
    facets_payload_fn: Any,
    *,
    response: Any | None = None,
    region_id: str | None,
    issue: str | None,
    related: str | None,
    date: str | None,
    q: str | None,
) -> PublicFacetsResponse:
    started = time.perf_counter()
    cache_key = json.dumps(
        {
            "data_dir": str(Path(data_dir).resolve()),
            "store": id(store),
            "region_id": region_id or "",
            "issue": issue or "",
            "related": related or "",
            "date": date or "",
            "q": q or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    now = time.monotonic()
    cache_entry = cache.get(cache_key)
    if _public_cache_entry_valid(cache_entry, now):
        assert cache_entry is not None
        payload = cast(PublicFacetsResponse, cache_entry["payload"])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        headers = _public_shared_cache_headers(
            etag=str(cache_entry["etag"]),
            cache_status="hit",
            timing_name="public-facets",
            header_name="Facets",
            elapsed_ms=elapsed_ms,
        )
        if response is not None:
            response.headers.update(headers)
        return payload

    payload = await facets_payload_fn(
        region_id=region_id,
        issue=issue,
        related=related,
        date=date,
        q=q,
    )
    etag = _public_payload_etag("public-facets", payload)
    cache[cache_key] = {
        "etag": etag,
        "expires_at": time.monotonic() + ttl,
        "payload": payload,
    }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    headers = _public_shared_cache_headers(
        etag=etag,
        cache_status="miss",
        timing_name="public-facets",
        header_name="Facets",
        elapsed_ms=elapsed_ms,
    )
    if response is not None:
        response.headers.update(headers)
    return payload


# ═══════════════════════════════════════════════════════════════════════
# list_targets
# ═══════════════════════════════════════════════════════════════════════


async def list_public_targets(
    data_dir: Any,
    include_empty: bool = False,
) -> TargetListResponse:
    """兼容旧接口：返回公开可浏览的地区列表。"""
    configs = target_config_utils._load_target_configs()
    event_counts = await target_config_utils._public_target_event_counts(data_dir)
    targets = []
    for config in configs:
        if _target_is_archived(config) or not _target_is_public_region(config):
            continue
        target = _target_info_from_config(config, data_dir)
        if target.target_id:
            target = target.model_copy(
                update={"event_count": event_counts.get(target.target_id, 0)}
            )
        if target.source_count <= 0:
            continue
        if not include_empty and target.event_count <= 0:
            continue
        targets.append(target)
    return TargetListResponse(targets=targets)


# ═══════════════════════════════════════════════════════════════════════
# subscribe
# ═══════════════════════════════════════════════════════════════════════


async def subscribe_handler(
    data_dir: Any,
    target_id: str,
    source_id: str | None = None,
    issue: str | None = None,
    email: str | None = None,
    preferred_language: str | None = None,
) -> JSONResponse:
    """创建订阅记录（v1: 存本地 JSON，不发邮件）。"""
    subscription: dict[str, Any] = {
        "subscription_id": (
            f"sub_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_"
            f"{uuid.uuid4().hex[:8]}"
        ),
        "target_id": target_id,
        "source_id": source_id,
        "issue": issue,
        "email": email,
        "preferred_language": preferred_language,
        "subscribed_at": datetime.now(UTC).isoformat(),
        "status": "active",
    }
    subs_dir = Path(data_dir) / "subscriptions"
    try:
        subs_dir.mkdir(parents=True, exist_ok=True)
        file_path = subs_dir / f"{subscription['subscription_id']}.json"
        file_path.write_text(
            json.dumps(subscription, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save subscription: {exc}",
        ) from exc
    return JSONResponse(content=subscription, status_code=201)


# ═══════════════════════════════════════════════════════════════════════
# Public Target Analysis
# ═══════════════════════════════════════════════════════════════════════


async def get_public_target_analysis_handler(
    get_target_store: Any,
    store: Any,
    data_dir: Any,
    target_id: str,
    days: int = 14,
) -> PublicAnalysisResponse:
    """公开匿名只读分析快照。"""
    target_store = await get_target_store(target_id)
    store_to_query = target_store if target_store is not None else store
    if store_to_query is not None:
        try:
            store_response = await _public_analysis_from_store(target_id, days, store_to_query)
            if store_response is not None:
                return store_response
        except Exception:
            logger.debug(
                "Public analysis store aggregation failed; falling back to filesystem",
                exc_info=True,
            )

    events = _public_events_within_window(_load_all_events(data_dir, target_id), days)
    classification_distribution, source_distribution = _public_distributions_from_events(events)
    return PublicAnalysisResponse(
        target_id=target_id,
        target_name=_target_display_name(target_id),
        days=days,
        summary=_public_summary_from_events(events),
        classification_distribution=classification_distribution,
        source_distribution=source_distribution,
        top_entities=[],
        topic_trends=[],
        sentiment_trend=[],
        active_chains=[],
        generated_at=datetime.now(UTC).isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════════
# Public News Feed (bootstrap payload)
# ═══════════════════════════════════════════════════════════════════════


async def public_news_feed_payload_for_bootstrap(
    data_dir: Any,
    store: Any,
    feed_cache: dict[str, Any],
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
    started = time.perf_counter()
    cache_key = _public_news_feed_cache_key(
        featured=featured,
        target_id=region_id,
        issue=issue,
        related=related,
        source_id=source_id,
        category=category,
        date=date,
        q=q,
        before_cursor=None,
        since_cursor=None,
        page_size=page_size,
    )
    now = time.monotonic()
    cache_entry = feed_cache.get(cache_key)
    if _public_news_cache_entry_valid(cache_entry, now):
        assert cache_entry is not None
        return (
            cast(PublicNewsFeedResponse, cache_entry["payload"]),
            str(cache_entry["etag"]),
            int((time.perf_counter() - started) * 1000),
        )

    target_ids = _public_news_target_ids(data_dir, region_id)
    allow_projection_first = not any((bool(source_id), bool(category), bool(date), bool(q)))
    query_limit = (
        min(_PUBLIC_NEWS_MAX_SCAN, page_size + 1)
        if allow_projection_first
        else min(_PUBLIC_NEWS_MAX_SCAN, max(page_size * 4, _PUBLIC_NEWS_MIN_SCAN))
    )
    candidates, candidate_total = await _public_news_candidate_events(
        data_dir,
        target_ids,
        limit=query_limit,
        allow_projection_first=allow_projection_first,
        allow_file_fallback=region_id is not None,
        featured=featured,
        source_id=source_id,
        category=category,
        date=date,
        q=q,
    )
    filtered: list[tuple[str, dict[str, Any]]] = []
    for tid, event in candidates:
        if _public_news_matches(
            event,
            featured=featured,
            source_id=source_id,
            category=category,
            issue=issue,
            related=related,
            date=date,
            q=q,
        ):
            filtered.append((tid, event))
    page_pairs = filtered[:page_size]
    items: list[PublicNewsItem] = []
    for tid, event in page_pairs:
        try:
            items.append(_public_news_item(tid, event))
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to render bootstrap public news item target=%s event_id=%s",
                tid,
                event.get("event_id") or event.get("id"),
            )
    latest_cursor = _public_news_encode_cursor(page_pairs[0][1]) if page_pairs else None
    next_cursor = (
        _public_news_encode_cursor(page_pairs[-1][1])
        if len(filtered) > len(page_pairs) and page_pairs
        else None
    )
    payload = PublicNewsFeedResponse(
        items=items,
        latestCursor=latest_cursor,
        nextCursor=next_cursor,
        pollAfterMs=_PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS,
        hasNewer=False,
        total=max(candidate_total, len(filtered)),
    )
    etag = _public_news_etag(items, latest_cursor)
    feed_cache[cache_key] = {
        "etag": etag,
        "expires_at": time.monotonic() + _public_news_feed_cache_ttl(q=q, since_cursor=None),
        "payload": payload,
        "poll_after_ms": _PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS,
    }
    return payload, etag, int((time.perf_counter() - started) * 1000)


# ═══════════════════════════════════════════════════════════════════════
# Public Bootstrap
# ═══════════════════════════════════════════════════════════════════════


async def get_public_bootstrap_handler(
    data_dir: Any,
    store: Any,
    get_target_store: Any,
    regions_cache: dict[str, Any],
    facets_cache: dict[str, Any],
    bootstrap_cache: dict[str, Any],
    feed_cache: dict[str, Any],
    feed_payload_fn: Any,
    cached_regions_fn: Any,
    cached_facets_fn: Any,
    request: Any,
    response: Any,
    featured: bool = True,
    target_id: str | None = None,
    region_id: str | None = None,
    source_id: str | None = None,
    category: str | None = None,
    issue: str | None = None,
    related: str | None = None,
    date: str | None = None,
    q: str | None = None,
    page_size: int = 20,
) -> Any:
    started = time.perf_counter()
    effective_region_id = region_id or target_id
    cache_key = json.dumps(
        {
            "data_dir": str(Path(data_dir).resolve()),
            "store": id(store),
            "featured": featured,
            "region_id": effective_region_id or "",
            "source_id": source_id or "",
            "category": category or "",
            "issue": issue or "",
            "related": related or "",
            "date": date or "",
            "q": q or "",
            "page_size": page_size,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    now = time.monotonic()
    cache_entry = bootstrap_cache.get(cache_key)
    if _public_cache_entry_valid(cache_entry, now):
        assert cache_entry is not None
        payload = cast(PublicBootstrapResponse, cache_entry["payload"])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        headers = _public_bootstrap_cache_headers(
            etag=str(cache_entry["etag"]),
            cache_status="hit",
            elapsed_ms=elapsed_ms,
        )
        if request.headers.get("if-none-match") == headers["ETag"]:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return payload

    news, _news_etag, _news_elapsed_ms = await feed_payload_fn(
        featured=featured,
        region_id=effective_region_id,
        source_id=source_id,
        category=category,
        issue=issue,
        related=related,
        date=date,
        q=q,
        page_size=page_size,
    )
    regions = await cached_regions_fn(include_empty=True)
    facets = await cached_facets_fn(
        region_id=effective_region_id,
        issue=issue,
        related=related,
        date=date,
        q=q,
    )
    payload = PublicBootstrapResponse(
        news=news,
        regions=regions,
        facets=facets,
        generatedAt=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    etag = _public_payload_etag("public-bootstrap", payload)
    bootstrap_cache[cache_key] = {
        "etag": etag,
        "expires_at": time.monotonic() + _PUBLIC_BOOTSTRAP_CACHE_TTL_SECONDS,
        "payload": payload,
    }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    headers = _public_bootstrap_cache_headers(
        etag=etag,
        cache_status="miss",
        elapsed_ms=elapsed_ms,
    )
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


# ═══════════════════════════════════════════════════════════════════════
# list_public_news
# ═══════════════════════════════════════════════════════════════════════


async def list_public_news_handler(
    data_dir: Any,
    store: Any,
    get_target_store: Any,
    feed_cache: dict[str, Any],
    request: Any,
    response: Any,
    featured: bool = False,
    target_id: str | None = None,
    region_id: str | None = None,
    source_id: str | None = None,
    category: str | None = None,
    issue: str | None = None,
    related: str | None = None,
    date: str | None = None,
    q: str | None = None,
    before_cursor: str | None = None,
    since_cursor: str | None = None,
    page_size: int = _PUBLIC_NEWS_DEFAULT_PAGE_SIZE,
) -> Any:
    """公共新闻流 presentation API，匿名只读，支持低负担增量更新。"""
    if before_cursor and since_cursor:
        raise HTTPException(
            status_code=422,
            detail="before_cursor and since_cursor cannot be used together",
        )
    before_key = _public_news_decode_cursor(before_cursor)
    since_key = _public_news_decode_cursor(since_cursor)
    effective_region_id = region_id or target_id
    started = time.perf_counter()
    cache_key = _public_news_feed_cache_key(
        featured=featured,
        target_id=effective_region_id,
        issue=issue,
        related=related,
        source_id=source_id,
        category=category,
        date=date,
        q=q,
        before_cursor=before_cursor,
        since_cursor=since_cursor,
        page_size=page_size,
    )
    now = time.monotonic()
    cache_entry = feed_cache.get(cache_key)
    if _public_news_cache_entry_valid(cache_entry, now):
        assert cache_entry is not None
        cached_payload = cast(PublicNewsFeedResponse, cache_entry["payload"])
        cached_etag = str(cache_entry["etag"])
        cached_poll_after_ms = int(cache_entry["poll_after_ms"])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        headers = _public_news_cache_headers(
            cache_status="hit",
            etag=cached_etag,
            poll_after_ms=cached_poll_after_ms,
            elapsed_ms=elapsed_ms,
        )
        if request.headers.get("if-none-match") == cached_etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return cached_payload

    target_ids = _public_news_target_ids(data_dir, effective_region_id)
    allow_projection_first = not any(
        (
            bool(source_id),
            bool(category),
            bool(date),
            bool(q),
            bool(before_cursor),
            bool(since_cursor),
        )
    )
    if allow_projection_first:
        query_limit = min(_PUBLIC_NEWS_MAX_SCAN, page_size + 1)
    else:
        query_limit = (
            _PUBLIC_NEWS_MAX_SCAN
            if before_cursor or since_cursor or q or date
            else min(_PUBLIC_NEWS_MAX_SCAN, max(page_size * 4, _PUBLIC_NEWS_MIN_SCAN))
        )
    candidates, candidate_total = await _public_news_candidate_events(
        data_dir,
        target_ids,
        limit=query_limit,
        allow_projection_first=allow_projection_first,
        allow_file_fallback=effective_region_id is not None,
        featured=featured,
        source_id=source_id,
        category=category,
        date=date,
        q=q,
        before_key=before_key,
        since_key=since_key,
    )

    filtered: list[tuple[str, dict[str, Any]]] = []
    for tid, event in candidates:
        if not _public_news_matches(
            event,
            featured=featured,
            source_id=source_id,
            category=category,
            issue=issue,
            related=related,
            date=date,
            q=q,
        ):
            continue
        key = _public_news_sort_key(event)
        if since_key is not None and key <= since_key:
            continue
        if before_key is not None and key >= before_key:
            continue
        filtered.append((tid, event))

    page_pairs = filtered[:page_size]
    items: list[PublicNewsItem] = []
    for tid, event in page_pairs:
        try:
            items.append(_public_news_item(tid, event))
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to render public news item target=%s event_id=%s",
                tid,
                event.get("event_id") or event.get("id"),
            )
    latest_cursor = _public_news_encode_cursor(page_pairs[0][1]) if page_pairs else since_cursor
    next_cursor = None
    if page_pairs and len(filtered) > len(page_pairs):
        next_cursor = _public_news_encode_cursor(page_pairs[-1][1])
    if since_cursor:
        poll_after_ms = (
            _PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS if items else _PUBLIC_NEWS_IDLE_POLL_AFTER_MS
        )
    else:
        poll_after_ms = _PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS
    poll_after_ms = max(poll_after_ms, _PUBLIC_NEWS_MIN_POLL_AFTER_MS)
    payload = PublicNewsFeedResponse(
        items=items,
        latestCursor=latest_cursor,
        nextCursor=next_cursor,
        pollAfterMs=poll_after_ms,
        hasNewer=bool(since_cursor and items),
        total=max(candidate_total, len(filtered)),
    )
    etag = _public_news_etag(items, latest_cursor)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _public_news_log_slow_miss(
        elapsed_ms=elapsed_ms,
        target_count=len(target_ids),
        candidate_count=len(candidates),
        filtered_count=len(filtered),
        item_count=len(items),
        featured=featured,
        has_target=effective_region_id is not None,
        has_source=source_id is not None,
        has_category=category is not None,
        has_date=date is not None,
        has_q=q is not None,
        has_before=before_cursor is not None,
        has_since=since_cursor is not None,
        page_size=page_size,
    )
    headers = _public_news_cache_headers(
        cache_status="miss",
        etag=etag,
        poll_after_ms=poll_after_ms,
        elapsed_ms=elapsed_ms,
    )
    if not (since_cursor and not items):
        feed_cache[cache_key] = {
            "etag": etag,
            "expires_at": time.monotonic()
            + _public_news_feed_cache_ttl(q=q, since_cursor=since_cursor),
            "payload": payload,
            "poll_after_ms": poll_after_ms,
        }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


# ═══════════════════════════════════════════════════════════════════════
# get_public_news_item
# ═══════════════════════════════════════════════════════════════════════


async def get_public_news_item_handler(
    data_dir: Any,
    store: Any,
    get_target_store: Any,
    event_id: str,
    target_id: str | None = None,
) -> PublicNewsItem:
    """公共新闻详情 presentation API，不暴露后台字段。"""
    target_ids = _public_news_target_ids(data_dir, target_id)
    for tid in target_ids:
        target_store = await get_target_store(tid)
        stores = [s for s in (target_store, store) if s is not None]
        for s in stores:
            projection_event = await _load_public_projection_detail(
                s,
                target_id=tid,
                event_id=event_id,
            )
            if isinstance(projection_event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if projection_event is not None:
                return _public_news_item(tid, projection_event, include_content=True)
            event = await _load_indexed_event_detail(data_dir, tid, s, event_id)
            if isinstance(event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if event is not None and _event_public_translation_ready(event):
                return _public_news_item(tid, event, include_content=True)
            if target_id and await _store_has_target_event_index(s, tid):
                raise HTTPException(status_code=404, detail="Event not found")

        event = _load_single_event(data_dir, tid, event_id)
        if event is not None and _event_public_translation_ready(event):
            return _public_news_item(tid, event, include_content=True)
    raise HTTPException(status_code=404, detail="Event not found")


# ═══════════════════════════════════════════════════════════════════════
# export_public_event_markdown
# ═══════════════════════════════════════════════════════════════════════


async def export_public_event_markdown_handler(
    data_dir: Any,
    store: Any,
    get_target_store: Any,
    markdown_download_response: Any,
    target_id: str,
    event_id: str,
) -> Response:
    """公开单篇新闻 Markdown 下载投影，不写入磁盘。"""
    target_store = await get_target_store(target_id)
    if target_store is not None:
        event = await _load_indexed_event_detail(
            data_dir,
            target_id,
            target_store,
            event_id,
        )
        if isinstance(event, InvisibleIndexedEvent):
            raise HTTPException(status_code=404, detail="Event not found")
        if event is not None:
            return markdown_download_response(
                f"{event_id}.md",
                _render_public_event_markdown(target_id, event),
            )
        if await _store_has_target_event_index(target_store, target_id):
            raise HTTPException(status_code=404, detail="Event not found")

    if store is not None:
        event = await _load_indexed_event_detail(
            data_dir,
            target_id,
            store,
            event_id,
        )
        if isinstance(event, InvisibleIndexedEvent):
            raise HTTPException(status_code=404, detail="Event not found")
        if event is not None:
            return markdown_download_response(
                f"{event_id}.md",
                _render_public_event_markdown(target_id, event),
            )
        if await _store_has_target_event_index(store, target_id):
            raise HTTPException(status_code=404, detail="Event not found")

    event = _load_single_event(data_dir, target_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return markdown_download_response(
        f"{event_id}.md",
        _render_public_event_markdown(target_id, event),
    )
