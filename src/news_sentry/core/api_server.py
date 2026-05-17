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
import secrets
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.auth import hash_password, verify_password
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


class ImportEventItem(BaseModel):
    """批量导入的单条事件。"""

    target_id: str
    source_id: str
    title_original: str
    url: str
    collected_at: str
    content_original: str = ""
    language: str = "mixed"
    classification: dict[str, Any] | None = None
    pipeline_stage: str = "collected"
    published_at: str = ""


class ImportResponse(BaseModel):
    """批量导入响应。"""

    imported: int
    skipped: int
    errors: list[str]


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
    top_entities: list[dict[str, Any]] = []


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


# ── 配置写入模型 ──────────────────────────────────────


class TargetConfigUpdate(BaseModel):
    """Target 配置更新请求。"""

    display_name: str | None = None
    timezone: str | None = None
    classification: dict[str, Any] | None = None
    language_scope: dict[str, Any] | None = None


class SourceConfigUpdate(BaseModel):
    """Source 配置更新请求。"""

    display_name: str | None = None
    url: str | None = None
    credibility_base: float | None = None
    fetch_interval_minutes: int | None = None
    max_items_per_run: int | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


class FilterConfigUpdate(BaseModel):
    """Filter 配置更新请求。"""

    score_threshold: int | None = None
    max_age_hours: int | None = None
    dedup_window_hours: int | None = None
    keyword_rules: list[dict[str, Any]] | None = None


class DestinationConfigUpdate(BaseModel):
    """Destination 配置更新请求。"""

    enabled: bool | None = None
    filter: dict[str, Any] | None = None
    notes: str | None = None


class RouteConfigUpdate(BaseModel):
    """Provider Route 配置更新请求。"""

    timeout_seconds: int | None = None
    max_cost_usd_per_call: float | None = None
    audit: bool | None = None
    fallback_route_ids: list[str] | None = None


class EntityInfo(BaseModel):
    """实体摘要信息。"""

    id: int
    canonical_name: str
    entity_type: str
    mention_count: int
    first_seen: str
    last_seen: str
    target_ids: str = ""


class EntityListResponse(BaseModel):
    """实体列表响应。"""

    total: int
    entities: list[EntityInfo]


class EntityDetailResponse(BaseModel):
    """实体详情响应。"""

    entity: EntityInfo
    recent_events: list[dict[str, Any]] = []


class RunInfo(BaseModel):
    """运行历史条目。"""

    run_id: str
    target_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: float = 0
    events_collected: int = 0
    errors_count: int = 0
    status: str = "completed"


class RunListResponse(BaseModel):
    """运行历史列表响应。"""

    runs: list[RunInfo]


class RunDetailResponse(BaseModel):
    """运行详情响应。"""

    run_id: str
    target_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    phases: list[dict[str, Any]] = []
    errors_count: int = 0
    errors: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}


class HeartbeatResponse(BaseModel):
    """活跃运行心跳响应。"""

    active: bool
    run_id: str = ""
    last_stage: str = ""
    last_at: str = ""
    status: str = ""


class SourceHealthInfo(BaseModel):
    """信源健康状态条目。"""

    source_id: str
    status: str
    last_check: str
    error_count: int = 0
    metadata: dict[str, Any] = {}


class SourceHealthListResponse(BaseModel):
    """信源健康列表响应。"""

    sources: list[SourceHealthInfo]


class TriggerResponse(BaseModel):
    """Pipeline 触发响应。"""

    status: str
    run_id: str
    message: str


class EventLinkInfo(BaseModel):
    """事件关联条目。"""

    linked_event_id: str
    link_type: str
    strength: float
    direction: str
    signals: dict[str, Any] = {}
    linked_event_title: str | None = None
    linked_event_time: str | None = None


class EventLinksResponse(BaseModel):
    """事件关联列表响应。"""

    event_id: str
    links: list[EventLinkInfo]


class ChainEventInfo(BaseModel):
    """链中事件条目。"""

    event_id: str
    title_original: str | None = None
    published_at: str | None = None
    link_type: str | None = None


class EventChainResponse(BaseModel):
    """事件追踪链响应。"""

    chain_id: str
    events: list[ChainEventInfo]
    total: int


class ChainSummaryInfo(BaseModel):
    """追踪链摘要。"""

    root_event_id: str
    event_count: int
    latest_time: str = ""
    latest_title: str = ""


class ChainListResponse(BaseModel):
    """追踪链列表响应。"""

    chains: list[ChainSummaryInfo]


class NarrativeResponse(BaseModel):
    """链叙述响应。"""

    chain_root_id: str
    narrative: str
    event_count: int = 0
    model_used: str = ""
    generated_at: str = ""


class TopicTrendItem(BaseModel):
    """主题趋势条目。"""

    topic: str
    trend_direction: str
    hotness: int
    current_count: int
    prev_count: int
    event_count: int
    daily_counts: list[dict[str, Any]]


class TopicTrendsResponse(BaseModel):
    """主题趋势响应。"""

    target_id: str
    days: int
    topics: list[TopicTrendItem]
    generated_at: str


class DailySentimentCount(BaseModel):
    """每日情感计数。"""

    day: str
    positive: int = 0
    negative: int = 0
    neutral: int = 0


class SentimentTrendsResponse(BaseModel):
    """情感趋势响应。"""

    target_id: str
    days: int
    daily_sentiment: list[DailySentimentCount]
    generated_at: str


class SmartAlertItem(BaseModel):
    """智能告警条目。"""

    type: str
    severity: str
    message: str
    details: dict[str, Any] = {}
    triggered_at: str = ""


class SmartAlertsResponse(BaseModel):
    """智能告警响应。"""

    target_id: str
    alerts: list[SmartAlertItem]
    total: int


class TodayStatsResponse(BaseModel):
    """今日 vs 昨日统计响应。"""

    target_id: str
    today_count: int = 0
    today_avg_score: float | None = None
    today_max_score: int | None = None
    yesterday_count: int = 0
    yesterday_avg_score: float | None = None


class TopEventInfo(BaseModel):
    """高价值事件条目。"""

    event_id: str
    title_original: str
    news_value_score: int
    source_id: str | None = None
    published_at: str | None = None


class TopEventsResponse(BaseModel):
    """高价值事件响应。"""

    target_id: str
    events: list[TopEventInfo]


class PruneResponse(BaseModel):
    """数据清理响应。"""

    target_id: str
    deleted_events: int = 0
    deleted_links: int = 0
    deleted_ids: int = 0


class BackupResponse(BaseModel):
    """备份响应。"""

    backup_path: str
    size_bytes: int = 0


class FeedbackSubmitRequest(BaseModel):
    """提交反馈请求。"""

    target_id: str
    event_id: str
    verdict_type: str  # publish_override | archive_override | comment
    comment: str = ""


class FeedbackSubmitResponse(BaseModel):
    """提交反馈响应。"""

    id: int
    event_id: str
    verdict_type: str


class FeedbackStatsResponse(BaseModel):
    """反馈统计响应。"""

    total: int
    publish_override: int
    archive_override: int
    comment: int


class FeedbackItem(BaseModel):
    """反馈条目。"""

    id: int
    event_id: str
    target_id: str
    verdict_type: str
    original_recommendation: str | None = None
    comment: str | None = None
    keywords_matched: str | None = None
    source_id: str | None = None
    created_at: str | None = None


class FeedbackListResponse(BaseModel):
    """反馈列表响应。"""

    feedback: list[FeedbackItem]
    total: int


class RulesOptimizeRequest(BaseModel):
    """规则优化请求。"""

    target_id: str
    dry_run: bool = True


class RulesOptimizeResponse(BaseModel):
    """规则优化响应。"""

    total_verdicts: int
    adjustments: int
    adjustments_detail: list[dict[str, Any]]
    written: bool


class AlertHistoryItem(BaseModel):
    """告警历史条目。"""

    id: int
    target_id: str
    alert_type: str
    severity: str
    message: str
    details: str | None = None
    created_at: str | None = None


class AlertHistoryResponse(BaseModel):
    """告警历史响应。"""

    alerts: list[AlertHistoryItem]
    total: int


# ── 用户认证 ───────────────────────────────────────────

_PERMISSIONS: dict[str, set[str]] = {
    "reader": {"read"},
    "admin": {"read", "write", "admin"},
}


# ── 速率限制 ────────────────────────────────────────────

_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 60  # requests per window


class _RateLimiter:
    """简易内存速率限制器（每用户独立计数）。"""

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

# 登录暴力破解保护：每用户名 5 次/5 分钟
_login_limiter = _RateLimiter(max_requests=5, window=300)


# ── Token 认证 ─────────────────────────────────────────

_TOKEN_STORE: dict[str, dict[str, Any]] = {}
_TOKEN_TTL = 86400  # 24 hours


def _create_token_for_user(username: str, role: str, has_api_key: bool) -> dict[str, Any]:
    """为已认证用户创建 session token。"""
    token = secrets.token_hex(32)
    now = time.time()
    _TOKEN_STORE[token] = {
        "username": username,
        "role": role,
        "has_api_key": has_api_key,
        "created_at": now,
        "expires_at": now + _TOKEN_TTL,
    }
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": _TOKEN_TTL,
        "username": username,
        "role": role,
        "has_api_key": has_api_key,
    }


def _verify_token(token: str) -> dict[str, Any] | None:
    """验证 Token 有效性。"""
    info = _TOKEN_STORE.get(token)
    if not info:
        return None
    if time.time() > info["expires_at"]:
        _TOKEN_STORE.pop(token, None)
        return None
    return info


def _extract_bearer_token(request: Request) -> str | None:
    """从 Authorization header 提取 Bearer token。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


# ── FastAPI 认证依赖 ───────────────────────────────────

# _store 在 create_app() 内赋值，此处为模块级引用占位
_store: AsyncStore | None = None

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> dict[str, Any]:
    """提取并验证 Bearer token，返回用户信息。"""
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication")
    info = _verify_token(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # 检查 store 中的最新 api_key 状态
    if _store is not None:
        user = await _store.get_user(info["username"])
        if user:
            info["has_api_key"] = bool(user.get("api_key"))
            info["role"] = user.get("role", info["role"])
    return info


def require_permission(permission: str) -> Any:
    """依赖工厂：检查用户权限。"""

    async def _check(user: dict = Depends(get_current_user)) -> dict[str, Any]:
        role = user.get("role", "reader")
        if permission not in _PERMISSIONS.get(role, set()):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if not _rate_limiter.check(user["username"]):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        return user

    return _check


# ── API Key 向后兼容 ──────────────────────────────────

_API_KEY_ENV = "NEWSSENTRY_API_KEY"


def _get_valid_api_keys() -> set[str]:
    """从环境变量 + 用户存储加载有效 API Key。"""
    keys: set[str] = set()
    raw = os.environ.get(_API_KEY_ENV, "")
    if raw:
        keys.update(k.strip() for k in raw.split(",") if k.strip())
    return keys


# ── 运行日志读取 ────────────────────────────────────────


def _load_run_logs(
    data_dir: Path,
    target_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """从 logs/ 目录读取最近的运行日志。"""
    log_dir = data_dir / target_id / "logs"
    if not log_dir.is_dir():
        return []
    json_files = sorted(log_dir.glob("*.json"), reverse=True)
    runs: list[dict[str, Any]] = []
    for f in json_files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            phases = data.get("phases", [])
            total_ms = sum(p.get("duration_ms", 0) for p in phases)
            summary = data.get("summary", {})
            runs.append(
                {
                    "run_id": data.get("run_id", f.stem),
                    "target_id": data.get("target_id", target_id),
                    "started_at": data.get("started_at", ""),
                    "ended_at": data.get("ended_at", ""),
                    "duration_ms": total_ms,
                    "events_collected": summary.get("total_events_collected", 0),
                    "errors_count": data.get("errors_count", 0),
                    "status": "completed" if data.get("ended_at") else "running",
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return runs


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


# ── 后台自动采集循环 ──────────────────────────────────────

_auto_collector_state: dict[str, Any] = {
    "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
    "target_id": os.environ.get("TARGET_ID", "italy"),
    "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15")),
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_events_collected": 0,
    "total_runs": 0,
    "task": None,
}

_log = logging.getLogger("news_sentry.auto_collector")


async def _auto_collect_loop() -> None:
    """后台循环：每隔 interval_minutes 执行一轮 collect+filter。

    仅采集 RSS/API 信源（纯 HTTP，无需浏览器），跳过 opencli_bridge。
    不执行 judge/output — 这些由 Cron 触发的全流程 pipeline 处理。
    """
    interval = _auto_collector_state["interval_minutes"] * 60
    target_id = _auto_collector_state["target_id"]
    _auto_collector_state["running"] = True
    _log.info("自动采集循环启动: target=%s, interval=%dmin", target_id, interval // 60)

    while _auto_collector_state["enabled"]:
        try:
            from news_sentry.core.async_run import bounded_run_async

            run_id = f"{target_id}_auto_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            _log.info("自动采集开始: run_id=%s", run_id)

            await bounded_run_async(
                target_id=target_id,
                stage="collect",  # 仅采集，不做 judge/output
                run_id=run_id,
            )

            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "ok"
            _auto_collector_state["total_runs"] += 1
            _log.info("自动采集完成: run_id=%s", run_id)
        except Exception:
            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "error"
            _auto_collector_state["total_runs"] += 1
            _log.error("自动采集失败", exc_info=True)

        await asyncio.sleep(interval)

    _auto_collector_state["running"] = False
    _log.info("自动采集循环停止")


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


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """FastAPI lifespan: 启动引导 + 后台采集循环。"""
    global _store
    if _store is not None:
        await _store.initialize()
        await _bootstrap_users()
    task = None
    if _auto_collector_state["enabled"]:
        task = asyncio.create_task(_auto_collect_loop())
        _auto_collector_state["task"] = task
    yield
    if task is not None:
        _auto_collector_state["enabled"] = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── FastAPI 应用 ────────────────────────────────────────


def create_app(
    data_dir: str | Path | None = None,
    store: AsyncStore | None = None,
    auto_store: bool = True,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        data_dir: 数据根目录，默认 ./data。
        store: AsyncStore 实例（Phase 28 新增，用于 SQLite 查询）。
        auto_store: 无传入 store 时自动创建（Cloudflare/生产=True，测试=False）。
    """
    app = FastAPI(
        title="News Sentry API",
        version="0.1.0",
        description="News Sentry REST API — 事件查询、统计、Webhook 入站",
        lifespan=_app_lifespan,
    )

    _data_dir = Path(data_dir) if data_dir else Path("./data")
    global _store
    if store is not None:
        _store = store
    elif _store is None and auto_store:
        _store = AsyncStore(_data_dir / "async_store.db")
    elif not auto_store:
        _store = None  # 显式禁用，测试环境重置
    _config_cache = ConfigCache(ttl=60, maxsize=128)

    # ── 公开端点（无需认证）─────────────────────────────

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/collector/status")
    async def collector_status() -> dict[str, Any]:
        """返回后台自动采集循环的状态。"""
        return {
            "enabled": _auto_collector_state["enabled"],
            "running": _auto_collector_state["running"],
            "target_id": _auto_collector_state["target_id"],
            "interval_minutes": _auto_collector_state["interval_minutes"],
            "last_run_at": _auto_collector_state["last_run_at"],
            "last_run_status": _auto_collector_state["last_run_status"],
            "total_runs": _auto_collector_state["total_runs"],
        }

    @app.post("/api/v1/auth/login")
    async def auth_login(request: Request) -> dict[str, Any]:
        """用户名+密码登录。"""
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")

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

        result = _create_token_for_user(username, user["role"], bool(user.get("api_key")))
        result["must_change_password"] = bool(user.get("must_change_pw", 0))
        return result

    @app.post("/api/v1/auth/token")
    async def auth_token(request: Request) -> dict[str, Any]:
        """API Key 换取短期 Token（向后兼容 CLI/cron）。"""
        body = await request.json()
        api_key = body.get("api_key", "")
        valid_keys = _get_valid_api_keys()

        # 也检查用户存储中的 API Key
        if _store is not None and api_key:
            users = await _store.list_users()
            for u in users:
                if u.get("api_key") == api_key:
                    return _create_token_for_user(u["username"], u.get("role", "reader"), True)

        if not valid_keys:
            # 开发模式：无配置 key 时允许所有请求
            return _create_token_for_user("dev", "admin", False)
        if api_key not in valid_keys:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return _create_token_for_user(f"key_{api_key[:8]}", "admin", True)

    @app.get("/api/v1/auth/me")
    async def auth_me(user: dict = Depends(get_current_user)) -> dict[str, Any]:
        """返回当前用户信息。"""
        return {
            "username": user["username"],
            "role": user["role"],
            "permissions": sorted(_PERMISSIONS.get(user["role"], set())),
            "has_api_key": user.get("has_api_key", False),
        }

    @app.post("/api/v1/auth/logout")
    async def auth_logout(request: Request) -> dict[str, str]:
        """注销当前 token。"""
        token = _extract_bearer_token(request)
        if token and token in _TOKEN_STORE:
            del _TOKEN_STORE[token]
        return {"status": "ok"}

    @app.post("/api/v1/auth/change-password")
    async def auth_change_password(
        request: Request, user: dict = Depends(get_current_user)
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
        return {"status": "ok"}

    # ── API Key 设置 ─────────────────────────────────────

    @app.get("/api/v1/settings/api-key")
    async def get_api_key_setting(
        user: dict = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """获取当前用户的 API Key 设置。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        user_record = await _store.get_user(user["username"])
        api_key = user_record.get("api_key") if user_record else None
        preview = f"{api_key[:4]}...{api_key[-4:]}" if api_key and len(api_key) >= 8 else ""
        return {
            "has_api_key": bool(api_key),
            "api_key_preview": preview,
        }

    @app.put("/api/v1/settings/api-key")
    async def set_api_key_setting(
        request: Request,
        user: dict = Depends(require_permission("admin")),
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

    @app.delete("/api/v1/settings/api-key")
    async def delete_api_key_setting(
        request: Request,
        user: dict = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """删除当前用户的 API Key。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        await _store.update_user_api_key(user["username"], None)
        token = _extract_bearer_token(request)
        if token and token in _TOKEN_STORE:
            _TOKEN_STORE[token]["has_api_key"] = False
        return {"status": "ok"}

    @app.get("/api/v1/targets", response_model=TargetListResponse)
    async def list_targets(
        user: dict = Depends(get_current_user),
    ) -> TargetListResponse:
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
        user: dict = Depends(get_current_user),
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
                top_entities=stats.get("top_entities", []),
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
            top_entities=[],
        )

    # ── 配置读取端点（无需认证）─────────────────────────

    @app.get("/api/v1/config/targets/{target_id}")
    async def get_target_config(
        target_id: str,
        user: dict = Depends(get_current_user),
    ) -> dict[str, Any]:
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
    async def list_sources(
        target_id: str,
        user: dict = Depends(get_current_user),
    ) -> SourceListResponse:
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
    async def get_source_config(
        target_id: str,
        source_id: str,
        user: dict = Depends(get_current_user),
    ) -> dict[str, Any]:
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
    async def get_filter_rules(
        target_id: str,
        user: dict = Depends(get_current_user),
    ) -> FilterRulesResponse:
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
    async def list_destinations(
        user: dict = Depends(get_current_user),
    ) -> DestinationListResponse:
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
    async def get_provider_routes(
        user: dict = Depends(get_current_user),
    ) -> ProviderRoutesResponse:
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

    # ── 实体端点 ────────────────────────────────────────

    @app.get("/api/v1/entities", response_model=EntityListResponse)
    async def list_entities(
        entity_type: str | None = Query(None, description="按实体类型过滤"),
        target_id: str | None = Query(None, description="按目标过滤"),
        min_mentions: int = Query(1, ge=1, description="最少提及次数"),
        user: dict = Depends(get_current_user),
        limit: int = Query(20, ge=1, le=100, description="返回数量"),
        sort: str = Query("mention_count", description="排序: mention_count 或 last_seen"),
    ) -> EntityListResponse:
        """返回实体列表。"""
        if _store is None:
            return EntityListResponse(total=0, entities=[])
        entities = await _store.query_entities(
            entity_type=entity_type,
            target_id=target_id,
            min_mentions=min_mentions,
            limit=limit,
            sort=sort,
        )
        return EntityListResponse(
            total=len(entities),
            entities=[EntityInfo(**e) for e in entities],
        )

    @app.get("/api/v1/entities/{entity_id}", response_model=EntityDetailResponse)
    async def get_entity(
        entity_id: int,
        user: dict = Depends(get_current_user),
    ) -> EntityDetailResponse:
        """返回实体详情及关联事件。"""
        if _store is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        detail = await _store.query_entity_detail(entity_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        recent = detail.pop("recent_events", [])
        return EntityDetailResponse(
            entity=EntityInfo(**detail),
            recent_events=recent,
        )

    # ── 需认证端点 ────────────────────────────────────

    @app.get("/api/v1/stats/today", response_model=TodayStatsResponse)
    async def get_today_stats_api(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> TodayStatsResponse:
        """今日 vs 昨日对比统计。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        stats = await _store.get_today_stats(target_id)
        return TodayStatsResponse(target_id=target_id, **stats)

    @app.get("/api/v1/events/top", response_model=TopEventsResponse)
    async def get_top_events_api(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(7, ge=1, le=30, description="天数"),
        limit: int = Query(5, ge=1, le=20, description="数量"),
        user: dict = Depends(get_current_user),
    ) -> TopEventsResponse:
        """近期高价值事件。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        events = await _store.get_top_events(target_id, days=days, limit=limit)
        return TopEventsResponse(
            target_id=target_id,
            events=[TopEventInfo(**e) for e in events],
        )

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
        user: dict = Depends(get_current_user),
    ) -> EventResponse:

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
        user: dict = Depends(get_current_user),
    ) -> dict[str, Any]:

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
        user: dict = Depends(require_permission("write")),
    ) -> WebhookResponse:
        event_id = _save_webhook_event(_data_dir, target_id, payload)
        return WebhookResponse(
            status="accepted",
            event_id=event_id,
            message=f"Event {event_id} saved to {target_id}/raw/",
        )

    @app.post("/api/v1/events/import", response_model=ImportResponse)
    async def import_events(
        events: list[ImportEventItem],
        user: dict = Depends(require_permission("write")),
    ) -> ImportResponse:
        """批量导入外部事件。

        接受 JSON 数组，逐条写入 data/{target_id}/raw/ 并索引到 SQLite。
        已存在的事件（event_id 相同）会被跳过。
        """

        imported = 0
        skipped = 0
        errors: list[str] = []

        for i, item in enumerate(events):
            try:
                now = datetime.now(UTC)
                # 确定性 event_id: sha256(source_id|url|collected_at)
                event_id = (
                    "ne-imp-"
                    + sha256(
                        f"{item.source_id}|{item.url}|{item.collected_at}".encode()
                    ).hexdigest()[:12]
                )

                # 去重检查
                if _store is not None and await _store.is_known(event_id):
                    skipped += 1
                    continue

                published_at = item.published_at or now.isoformat()
                event_data: dict[str, Any] = {
                    "id": event_id,
                    "run_id": "import",
                    "source_id": item.source_id,
                    "url": item.url,
                    "title_original": item.title_original,
                    "content_original": item.content_original,
                    "language": item.language,
                    "published_at": published_at,
                    "collected_at": item.collected_at,
                    "pipeline_stage": item.pipeline_stage,
                }
                if item.classification:
                    event_data["metadata"] = {"classification": item.classification}

                # 写入 raw/ 目录（YAML frontmatter）
                raw_dir = _data_dir / item.target_id / "raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                filepath = raw_dir / f"collected_{item.source_id}_{event_id}.md"
                fm = yaml.dump(
                    event_data, allow_unicode=True, default_flow_style=False, sort_keys=False
                )
                body = f"# {item.title_original}\n\n{item.content_original}\n"
                filepath.write_text(f"---\n{fm}---\n\n{body}", encoding="utf-8")

                # 索引到 SQLite
                if _store is not None and _store._db is not None:  # noqa: SLF001
                    await _store.mark_known(event_id)
                    classification_l0 = None
                    if isinstance(item.classification, dict):
                        classification_l0 = item.classification.get("l0")
                    await _store._db.execute(  # noqa: SLF001
                        """INSERT OR IGNORE INTO event_index
                           (event_id, target_id, stage, source_id,
                            classification_l0, title_original,
                            published_at, file_path, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            event_id,
                            item.target_id,
                            item.pipeline_stage,
                            item.source_id,
                            classification_l0,
                            item.title_original,
                            published_at,
                            str(filepath),
                            now.isoformat(),
                        ),
                    )
                    await _store._db.commit()  # noqa: SLF001

                imported += 1
            except Exception as exc:
                errors.append(f"events[{i}]: {exc}")

        return ImportResponse(imported=imported, skipped=skipped, errors=errors)

    @app.post("/api/v1/config/reload")
    async def reload_config(
        user: dict = Depends(require_permission("write")),
    ) -> dict[str, str]:
        """清除配置缓存，下次请求时重新从文件加载。"""
        _config_cache.reload()
        return {"status": "ok", "message": "Configuration cache cleared"}

    # ── Phase 42: 配置写入端点 ────────────────────────────

    @app.put("/api/v1/config/targets/{target_id}")
    async def update_target_config(
        target_id: str,
        body: TargetConfigUpdate,
        user: dict = Depends(require_permission("write")),
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

    @app.patch("/api/v1/config/targets/{target_id}/sources/{source_id:path}")
    async def update_source_config(
        target_id: str,
        source_id: str,
        body: SourceConfigUpdate,
        user: dict = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新 source 配置。"""

        filepath = Path(f"config/sources/{target_id}/{source_id}.yaml")
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

    @app.patch("/api/v1/config/targets/{target_id}/filters")
    async def update_filter_config(
        target_id: str,
        body: FilterConfigUpdate,
        user: dict = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新 filter 配置。"""

        filepath = Path(f"config/filters/{target_id}/default.yaml")
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

    @app.patch("/api/v1/config/output/destinations/{destination_id}")
    async def update_destination_config(
        destination_id: str,
        body: DestinationConfigUpdate,
        user: dict = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新 output destination 配置。"""

        filepath = Path("config/output/destinations.yaml")
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

    @app.patch("/api/v1/config/provider/routes/{route_id}")
    async def update_provider_route(
        route_id: str,
        body: RouteConfigUpdate,
        user: dict = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """更新 provider route 配置。"""

        filepath = Path("config/provider/routes.yaml")
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

    @app.get("/api/v1/runs", response_model=RunListResponse)
    async def list_runs(
        target_id: str = Query(..., description="目标标识"),
        limit: int = Query(20, ge=1, le=100),
        user: dict = Depends(get_current_user),
    ) -> RunListResponse:
        runs = _load_run_logs(_data_dir, target_id, limit)
        return RunListResponse(runs=[RunInfo(**r) for r in runs])

    @app.get("/api/v1/runs/active", response_model=HeartbeatResponse)
    async def get_active_run(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> HeartbeatResponse:
        data = _load_heartbeat(_data_dir, target_id)
        return HeartbeatResponse(**data)

    @app.get("/api/v1/runs/{run_id:path}", response_model=RunDetailResponse)
    async def get_run_detail(
        run_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
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

    @app.get("/api/v1/sources/health", response_model=SourceHealthListResponse)
    async def list_source_health(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> SourceHealthListResponse:
        if _store is None:
            return SourceHealthListResponse(sources=[])
        records = await _store.get_all_source_health()
        return SourceHealthListResponse(sources=[SourceHealthInfo(**r) for r in records])

    @app.post("/api/v1/runs/trigger", response_model=TriggerResponse)
    async def trigger_run(
        target_id: str = Query(..., description="目标标识"),
        stage: str = Query("all", description="执行阶段"),
        user: dict = Depends(require_permission("write")),
    ) -> TriggerResponse:
        try:
            import asyncio

            from news_sentry.core.async_run import bounded_run_async

            run_id = f"{target_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            asyncio.create_task(bounded_run_async(target_id=target_id, stage=stage, run_id=run_id))
            return TriggerResponse(
                status="triggered",
                run_id=run_id,
                message=f"Pipeline triggered for {target_id}/{stage}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # ── Phase 35: 追踪链端点 ──────────────────────────────

    @app.get("/api/v1/events/{event_id}/links", response_model=EventLinksResponse)
    async def get_event_links(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> EventLinksResponse:
        """获取某事件的关联事件列表。"""
        if _store is None:
            return EventLinksResponse(event_id=event_id, links=[])
        links = await _store.get_event_links(event_id)
        result_links: list[EventLinkInfo] = []
        for link in links:
            linked_id = link["linked_event_id"]
            title = None
            time_str = None
            if _store._db is not None:
                async with _store._db.execute(
                    "SELECT title_original, published_at FROM event_index WHERE event_id = ?",
                    [linked_id],
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        title = row[0]
                        time_str = row[1]
            result_links.append(
                EventLinkInfo(
                    linked_event_id=linked_id,
                    link_type=link["link_type"],
                    strength=link["strength"],
                    direction=link["direction"],
                    signals=link.get("signals", {}),
                    linked_event_title=title,
                    linked_event_time=time_str,
                )
            )
        return EventLinksResponse(event_id=event_id, links=result_links)

    @app.get("/api/v1/events/{event_id}/chain", response_model=EventChainResponse)
    async def get_event_chain(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> EventChainResponse:
        """获取某事件的完整追踪链。"""
        if _store is None:
            return EventChainResponse(chain_id=event_id, events=[], total=0)
        chain = await _store.get_event_chain(event_id, depth=5)
        events: list[ChainEventInfo] = []
        for ce in chain:
            events.append(
                ChainEventInfo(
                    event_id=ce["event_id"],
                    title_original=ce.get("title_original"),
                    published_at=ce.get("published_at"),
                    link_type=ce.get("link_type"),
                )
            )
        return EventChainResponse(chain_id=event_id, events=events, total=len(events))

    @app.get("/api/v1/chains", response_model=ChainListResponse)
    async def list_chains(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> ChainListResponse:
        """列出当前 target 的活跃追踪链。"""
        if _store is None:
            return ChainListResponse(chains=[])
        chains = await _store.get_active_chains(target_id)
        return ChainListResponse(
            chains=[ChainSummaryInfo(**c) for c in chains],
        )

    @app.get("/api/v1/chains/{root_id}/narrative", response_model=NarrativeResponse)
    async def get_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
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

    @app.post("/api/v1/chains/{root_id}/narrative", response_model=NarrativeResponse)
    async def regenerate_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(require_permission("write")),
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

    @app.get("/api/v1/trends/topics", response_model=TopicTrendsResponse)
    async def get_topic_trends(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(14, ge=7, le=30, description="天数"),
        user: dict = Depends(get_current_user),
    ) -> TopicTrendsResponse:
        """主题热度趋势。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            daily_counts = await _store.get_topic_daily_counts(target_id, days=days)
            top_topics = await _store.get_top_topics(target_id, days=days, limit=10)
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

    @app.get("/api/v1/trends/sentiment", response_model=SentimentTrendsResponse)
    async def get_sentiment_trends(
        target_id: str = Query(..., description="目标标识"),
        days: int = Query(14, ge=7, le=30, description="天数"),
        user: dict = Depends(get_current_user),
    ) -> SentimentTrendsResponse:
        """情感分布趋势。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            raw = await _store.get_sentiment_daily_counts(target_id, days=days)
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

    @app.get("/api/v1/alerts/smart", response_model=SmartAlertsResponse)
    async def get_smart_alerts(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> SmartAlertsResponse:
        """获取智能告警列表。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            from news_sentry.core.alert_pipeline import AlertPipeline

            pipeline = AlertPipeline([])
            alerts = await pipeline.check_smart_alerts(_store, target_id)
            return SmartAlertsResponse(
                target_id=target_id,
                alerts=[SmartAlertItem(**a) for a in alerts],
                total=len(alerts),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    # ── 维护端点 (Phase 40) ─────────────────────────────

    @app.post("/api/v1/maintenance/prune", response_model=PruneResponse)
    async def maintenance_prune(
        target_id: str = Query(..., description="目标标识"),
        max_age_days: int = Query(30, ge=7, le=365, description="保留天数"),
        user: dict = Depends(require_permission("write")),
    ) -> PruneResponse:
        """手动触发数据清理。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        result = await _store.prune_old_data(target_id, max_age_days=max_age_days)
        return PruneResponse(target_id=target_id, **result)

    @app.post("/api/v1/maintenance/backup", response_model=BackupResponse)
    async def maintenance_backup(
        user: dict = Depends(require_permission("write")),
    ) -> BackupResponse:
        """手动触发数据库备份。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        backup_dir = _store.db_path.parent / "backups"
        backup_path = await _store.backup_db(backup_dir)
        size = backup_path.stat().st_size if backup_path.exists() else 0
        return BackupResponse(backup_path=str(backup_path), size_bytes=size)

    # ── 反馈闭环 + 告警管理 (Phase 41) ──────────────────

    @app.post("/api/v1/feedback", response_model=FeedbackSubmitResponse)
    async def submit_feedback(
        req: FeedbackSubmitRequest,
        user: dict = Depends(require_permission("write")),
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

    @app.get("/api/v1/feedback", response_model=FeedbackListResponse)
    async def list_feedback(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> FeedbackListResponse:
        """获取反馈列表。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
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

    @app.get("/api/v1/feedback/stats", response_model=FeedbackStatsResponse)
    async def feedback_stats(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> FeedbackStatsResponse:
        """获取反馈统计。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        stats = await _store.get_feedback_stats(target_id)
        return FeedbackStatsResponse(**stats)

    @app.post("/api/v1/rules/optimize", response_model=RulesOptimizeResponse)
    async def optimize_rules(
        req: RulesOptimizeRequest,
        user: dict = Depends(require_permission("write")),
    ) -> RulesOptimizeResponse:
        """触发规则优化。"""
        config_dir = Path("config")
        filter_yaml = config_dir / f"filter-{req.target_id}.yaml"
        if not filter_yaml.exists():
            raise HTTPException(status_code=404, detail=f"Filter config not found: {filter_yaml}")
        from news_sentry.core.rules_optimizer import RulesOptimizer

        data_dir = Path("data") / req.target_id
        optimizer = RulesOptimizer(filter_yaml, data_dir)
        result = optimizer.optimize(dry_run=req.dry_run)
        return RulesOptimizeResponse(
            total_verdicts=result["total_verdicts"],
            adjustments=result["adjustments"],
            adjustments_detail=result["adjustments_detail"],
            written=result["written"],
        )

    @app.get("/api/v1/alerts/history", response_model=AlertHistoryResponse)
    async def alert_history(
        target_id: str = Query(..., description="目标标识"),
        user: dict = Depends(get_current_user),
    ) -> AlertHistoryResponse:
        """获取告警历史。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
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

    # ── 静态文件（必须在所有 API 路由之后挂载）────────
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
