"""Implements: docs/spec/phase-22-api-gateway.md §1

API Server — FastAPI REST API 网关。

提供:
  - GET /api/v1/targets — 可用 target 列表
  - GET /api/v1/stats — 事件统计
  - GET /api/v1/events — 查询事件列表（支持筛选）
  - GET /api/v1/events/{event_id} — 查询单个事件
  - POST /api/v1/webhook — 接收外部事件（Webhook 入站）
  - GET /api/v1/health — 健康检查
  - GET /docs — OpenAPI/Swagger UI
  - GET / — 前端 Web UI（由静态文件提供）

认证: API Key 通过 X-API-Key header 或 ?api_key= 查询参数。
速率限制: 60 req/min per API key。
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.config_cache import ConfigCache

# ── Pydantic 模型 ──────────────────────────────────────


class EventResponse(BaseModel):
    """事件列表响应。"""

    total: int
    events: list[dict[str, Any]]
    page: int
    page_size: int


class WebhookPayload(BaseModel):
    """Webhook 入站事件载荷。"""

    source_id: str
    url: str
    title_original: str
    content_original: str = ""
    language: str = "mixed"
    published_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    """Webhook 接收确认。"""

    status: str
    event_id: str
    message: str


class TargetInfo(BaseModel):
    """Target 基本信息。"""

    target_id: str
    display_name: str
    primary_language: str
    source_count: int


class TargetListResponse(BaseModel):
    """Target 列表响应。"""

    targets: list[TargetInfo]


class StatsResponse(BaseModel):
    """事件统计响应。"""

    target_id: str
    total_events: int
    avg_news_value_score: float | None
    avg_china_relevance: float | None
    by_classification: dict[str, int]
    by_source: dict[str, int]
    sentiment_breakdown: dict[str, int] = {}


class SourceInfo(BaseModel):
    """源渠道摘要信息。"""

    source_id: str
    display_name: str
    type: str  # rss | api | opencli | social
    enabled: bool
    credibility_base: float | None = None
    health_last_success: str | None = None
    health_consecutive_failures: int | None = None
    url: str | None = None


class SourceListResponse(BaseModel):
    """源渠道列表响应。"""

    target_id: str
    sources: list[SourceInfo]


class FilterRulesResponse(BaseModel):
    """过滤规则响应。"""

    target_id: str
    score_threshold: int | None = None
    max_age_hours: int | None = None
    dedup_window_hours: int | None = None
    keyword_rules_count: int
    keyword_rules: list[dict[str, Any]]


class DestinationInfo(BaseModel):
    """输出目的地摘要信息。"""

    destination_id: str
    type: str
    enabled: bool
    filter_min_news_value_score: int | None = None
    filter_min_china_relevance: int | None = None
    notes: str | None = None


class DestinationListResponse(BaseModel):
    """输出目的地列表响应。"""

    destinations: list[DestinationInfo]


class RouteInfo(BaseModel):
    """Provider 路由条目。"""

    route_id: str
    task_type: str
    provider: str
    model: str
    timeout_seconds: int
    max_cost_usd_per_call: float
    audit: bool
    fallback_route_ids: list[str] = []


class ProviderRoutesResponse(BaseModel):
    """Provider 路由配置响应。"""

    routes_version: str
    routes: list[RouteInfo]
    fallback_route_id: str | None = None


# ── API Key 认证 ───────────────────────────────────────

_API_KEY_ENV = "NEWSSENTRY_API_KEY"


def _get_valid_api_keys() -> set[str]:
    """从环境变量加载有效 API Key（逗号分隔）。"""
    raw = os.environ.get(_API_KEY_ENV, "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def _verify_api_key(api_key: str | None) -> str:
    """验证 API Key，返回有效的 key 或抛 401。"""
    valid_keys = _get_valid_api_keys()
    # 无配置 key 时允许所有请求（开发模式）
    if not valid_keys:
        return api_key or "dev"
    if not api_key or api_key not in valid_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


# ── 速率限制 ────────────────────────────────────────────

_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 60  # requests per window


class _RateLimiter:
    """简易内存速率限制器（每 API key 独立计数）。"""

    def __init__(
        self,
        max_requests: int = _RATE_LIMIT_MAX,
        window: int = _RATE_LIMIT_WINDOW,
    ) -> None:
        self._max = max_requests
        self._window = window
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """检查是否超限。返回 True 表示允许。"""
        now = time.monotonic()
        cutoff = now - self._window
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        if len(self._hits[key]) >= self._max:
            return False
        self._hits[key].append(now)
        return True


_rate_limiter = _RateLimiter()


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
        events = [
            e
            for e in events
            if isinstance(e.get("classification"), dict)
            and e["classification"].get("l0") == classification
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


def _load_single_event(data_dir: Path, target_id: str, event_id: str) -> dict[str, Any] | None:
    """查找单个事件。"""
    drafts_dir = data_dir / target_id / "drafts"
    if not drafts_dir.is_dir():
        return None
    for md_file in drafts_dir.glob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(raw)
            if fm and fm.get("id") == event_id:
                return fm
        except Exception:  # noqa: S112
            continue
    return None


def _save_webhook_event(
    data_dir: Path,
    target_id: str,
    payload: WebhookPayload,
) -> str:
    """将 Webhook 事件写入 data/{target_id}/raw/。"""
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    hash8 = sha256(f"{payload.source_id}{payload.url}{date_str}".encode()).hexdigest()[:8]
    event_id = f"ne-webhook-{payload.source_id}-{date_str}-{hash8}"

    raw_dir = data_dir / target_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    event_data = {
        "id": event_id,
        "run_id": "webhook",
        "source_id": payload.source_id,
        "url": payload.url,
        "title_original": payload.title_original,
        "content_original": payload.content_original,
        "language": payload.language,
        "published_at": payload.published_at or now.isoformat(),
        "collected_at": now.isoformat(),
        "pipeline_stage": "collected",
        "metadata": payload.metadata,
    }

    filepath = raw_dir / f"collected_{payload.source_id}_{event_id}.md"
    fm = yaml.dump(event_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    body = f"# {payload.title_original}\n\n{payload.content_original}\n"
    content = f"---\n{fm}---\n\n{body}"
    filepath.write_text(content, encoding="utf-8")

    return event_id


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    """解析 YAML frontmatter。"""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
        return fm if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None


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


def _load_source_configs(target_id: str) -> list[dict[str, Any]]:
    """从 config/sources/{target_id}/ 读取所有源渠道配置。"""
    sources_dir = Path(f"config/sources/{target_id}")
    if not sources_dir.is_dir():
        return []
    sources: list[dict[str, Any]] = []
    for yaml_file in sorted(sources_dir.rglob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        data = _load_yaml_file(yaml_file)
        if data and isinstance(data, dict):
            rel = yaml_file.relative_to(sources_dir).with_suffix("")
            data["_source_id"] = str(rel)
            data["_file_path"] = str(yaml_file)
            sources.append(data)
    return sources


def _load_single_source(target_id: str, source_id: str) -> dict[str, Any] | None:
    """读取单个源渠道配置。"""
    sources_dir = Path(f"config/sources/{target_id}")
    if not sources_dir.is_dir():
        return None
    # source_id 可能是子路径，如 "api/gnews-italy"
    source_path = sources_dir / f"{source_id}.yaml"
    return _load_yaml_file(source_path)


def _load_all_events(data_dir: Path, target_id: str) -> list[dict[str, Any]]:
    """从 data/{target_id}/drafts/ 读取所有事件（不分页）。"""
    drafts_dir = data_dir / target_id / "drafts"
    events: list[dict[str, Any]] = []
    if drafts_dir.is_dir():
        for md_file in sorted(drafts_dir.glob("*.md"), reverse=True):
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm = _parse_frontmatter(raw)
                if fm:
                    events.append(fm)
            except Exception:  # noqa: S112
                continue
    return events


def _load_event_by_path(file_path: str | None) -> dict[str, Any] | None:
    """根据 file_path 读取单个 .md 文件的 frontmatter。"""
    if file_path is None:
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return _parse_frontmatter(raw)
    except Exception:  # noqa: S112
        return None


# ── FastAPI 应用 ────────────────────────────────────────


def create_app(
    data_dir: str | Path | None = None,
    store: AsyncStore | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        data_dir: 数据根目录，默认 ./data。
        store: AsyncStore 实例（Phase 28 新增，用于 SQLite 查询）。
    """
    app = FastAPI(
        title="News Sentry API",
        version="0.1.0",
        description="News Sentry REST API — 事件查询、统计、Webhook 入站",
    )

    _data_dir = Path(data_dir) if data_dir else Path("./data")
    _store = store
    _config_cache = ConfigCache(ttl=60, maxsize=128)

    # ── 公开端点（无需认证）─────────────────────────────

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/targets", response_model=TargetListResponse)
    async def list_targets() -> TargetListResponse:
        """返回所有可用的 target 列表。"""
        configs = _load_target_configs()
        targets = [
            TargetInfo(
                target_id=c.get("target_id", ""),
                display_name=c.get("display_name", ""),
                primary_language=c.get("language_scope", {}).get("primary", ""),
                source_count=len(c.get("source_channel_refs", [])),
            )
            for c in configs
        ]
        return TargetListResponse(targets=targets)

    @app.get("/api/v1/stats", response_model=StatsResponse)
    async def get_stats(
        target_id: str = Query(..., description="目标标识"),
    ) -> StatsResponse:
        """返回指定 target 的事件统计（SQLite 聚合查询）。"""
        if _store is not None:
            stats = await _store.get_stats_aggregated(target_id)
            return StatsResponse(
                target_id=target_id,
                total_events=stats["total_events"],
                avg_news_value_score=stats["avg_news_value_score"],
                avg_china_relevance=stats["avg_china_relevance"],
                by_classification=stats["by_classification"],
                by_source=stats["by_source"],
                sentiment_breakdown=stats.get("sentiment_breakdown", {}),
            )

        # 降级路径：无 store 时走原始文件扫描
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
                    by_classification[l0] += 1
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
        )

    # ── 配置读取端点（无需认证）─────────────────────────

    @app.get("/api/v1/config/targets/{target_id}")
    async def get_target_config(target_id: str) -> dict[str, Any]:
        """读取指定 target 的完整配置。"""
        config_path = Path(f"config/targets/{target_id}.yaml")
        data = _config_cache.load_yaml(config_path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")
        return data

    @app.get(
        "/api/v1/config/targets/{target_id}/sources",
        response_model=SourceListResponse,
    )
    async def list_sources(target_id: str) -> SourceListResponse:
        """列出指定 target 的所有源渠道。"""
        raw_sources = _load_source_configs(target_id)
        sources: list[SourceInfo] = []
        for s in raw_sources:
            # 提取 url：RSS 的 url 字段，API 的 endpoint.url
            url_val = s.get("url")
            if url_val is None:
                ep = s.get("endpoint")
                if isinstance(ep, dict):
                    url_val = ep.get("url")
            # 提取 health 信息
            health = s.get("health")
            health_last = None
            health_failures = None
            if isinstance(health, dict):
                health_last = health.get("last_success_at")
                health_failures = health.get("consecutive_failures")
            sources.append(
                SourceInfo(
                    source_id=s.get("source_id", s["_source_id"]),
                    display_name=s.get("display_name", ""),
                    type=s.get("type", "unknown"),
                    enabled=s.get("enabled", True),
                    credibility_base=s.get("credibility_base"),
                    health_last_success=health_last,
                    health_consecutive_failures=health_failures,
                    url=url_val,
                )
            )
        return SourceListResponse(target_id=target_id, sources=sources)

    @app.get("/api/v1/config/targets/{target_id}/sources/{source_id:path}")
    async def get_source_config(target_id: str, source_id: str) -> dict[str, Any]:
        """读取单个源渠道的完整配置。"""
        data = _load_single_source(target_id, source_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source '{source_id}' not found for target '{target_id}'",
            )
        return data

    @app.get(
        "/api/v1/config/targets/{target_id}/filters",
        response_model=FilterRulesResponse,
    )
    async def get_filter_rules(target_id: str) -> FilterRulesResponse:
        """读取指定 target 的过滤规则。"""
        filter_path = Path(f"config/filters/{target_id}/default.yaml")
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

    @app.get(
        "/api/v1/config/output/destinations",
        response_model=DestinationListResponse,
    )
    async def list_destinations() -> DestinationListResponse:
        """读取所有输出目的地配置。"""
        dest_path = Path("config/output/destinations.yaml")
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

    @app.get(
        "/api/v1/config/provider/routes",
        response_model=ProviderRoutesResponse,
    )
    async def get_provider_routes() -> ProviderRoutesResponse:
        """读取 AI Provider 路由配置。"""
        routes_path = Path("config/provider/routes.yaml")
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

    # ── 需认证端点 ────────────────────────────────────

    @app.get("/api/v1/events", response_model=EventResponse)
    async def list_events(
        target_id: str = Query(..., description="目标标识"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        classification: str | None = Query(None, description="按 classification.l0 筛选"),
        source_id: str | None = Query(None, description="按 source_id 筛选"),
        min_score: int | None = Query(None, description="最低 news_value_score"),
        search: str | None = Query(None, description="在 title_original 中搜索关键词"),
        sentiment: str | None = Query(
            None, description="按 sentiment 筛选 (positive/negative/neutral)"
        ),
        entity: str | None = Query(None, description="按实体名筛选"),
        topic_tag: str | None = Query(None, description="按主题标签筛选"),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> EventResponse:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        if _store is not None:
            offset = (page - 1) * page_size
            result = await _store.query_events_paginated(
                target_id=target_id,
                stage="drafts",
                limit=page_size,
                offset=offset,
                source_id=source_id,
                classification_l0=classification,
                min_score=min_score,
                sentiment=sentiment,
                entity_name=entity,
                topic_tag=topic_tag,
            )
            total = result["total"]
            page_events: list[dict[str, Any]] = []

            for row in result["rows"]:
                event_fm = _load_event_by_path(row["file_path"])
                if event_fm is None:
                    continue
                if search is not None:
                    keyword = search.lower()
                    if keyword not in (event_fm.get("title_original") or "").lower():
                        total -= 1
                        continue
                page_events.append(event_fm)

            return EventResponse(
                total=total,
                events=page_events,
                page=page,
                page_size=page_size,
            )

        # 降级路径
        return _load_events_from_data(
            _data_dir,
            target_id,
            page,
            page_size,
            classification=classification,
            source_id=source_id,
            min_score=min_score,
            search=search,
        )

    @app.get("/api/v1/events/{event_id}")
    async def get_event(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> dict[str, Any]:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        if _store is not None:
            file_path = await _store.get_event_file_path(event_id)
            if file_path is None:
                raise HTTPException(status_code=404, detail="Event not found")
            event = _load_event_by_path(file_path)
            if event is None:
                raise HTTPException(status_code=404, detail="Event file not found")
            return event

        # 降级路径
        event = _load_single_event(_data_dir, target_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.post("/api/v1/webhook", response_model=WebhookResponse)
    async def receive_webhook(
        payload: WebhookPayload,
        target_id: str = Query(..., description="目标标识"),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> WebhookResponse:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        event_id = _save_webhook_event(_data_dir, target_id, payload)
        return WebhookResponse(
            status="accepted",
            event_id=event_id,
            message=f"Event {event_id} saved to {target_id}/raw/",
        )

    @app.post("/api/v1/config/reload")
    async def reload_config(
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> dict[str, str]:
        """清除配置缓存，下次请求时重新从文件加载。"""
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _config_cache.reload()
        return {"status": "ok", "message": "Configuration cache cleared"}

    # ── 静态文件（必须在所有 API 路由之后挂载）────────
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
