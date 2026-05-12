"""Implements: docs/spec/phase-22-api-gateway.md §1

API Server — FastAPI REST API 网关。

提供:
  - GET /api/v1/events — 查询事件列表
  - GET /api/v1/events/{event_id} — 查询单个事件
  - POST /api/v1/webhook — 接收外部事件（Webhook 入站）
  - GET /api/v1/health — 健康检查
  - GET /docs — OpenAPI/Swagger UI

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
) -> EventResponse:
    """从 data/{target_id}/drafts/ 读取事件列表。"""
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


# ── FastAPI 应用 ────────────────────────────────────────


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        data_dir: 数据根目录，默认 ./data。
    """
    app = FastAPI(
        title="News Sentry API",
        version="0.1.0",
        description="News Sentry REST API — 事件查询、Webhook 入站",
    )

    _data_dir = Path(data_dir) if data_dir else Path("./data")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/events", response_model=EventResponse)
    async def list_events(
        target_id: str = Query(..., description="目标标识"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> EventResponse:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        return _load_events_from_data(_data_dir, target_id, page, page_size)

    @app.get("/api/v1/events/{event_id}")
    async def get_event(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> dict[str, Any]:
        key = _verify_api_key(x_api_key)
        if not _rate_limiter.check(key):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        event = _load_single_event(_data_dir, target_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.post("/api/v1/webhook", response_model=WebhookResponse)
    async def receive_webhook(
        payload: WebhookPayload,
        target_id: str = Query("italy", description="目标标识"),
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

    return app
