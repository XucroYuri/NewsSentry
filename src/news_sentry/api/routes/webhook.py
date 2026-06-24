"""Webhook 接收端点 — 外部系统推送原始事件入站。

端点: POST /api/v1/webhook
认证: X-Signature-256 HMAC-SHA256 签名验证（基于 WEBHOOK_SECRET）
速率限制: 令牌桶 1 req/s（全局）+ payload 大小限制 1MB
集成: 保存后通过 EventBus 发布 news.incoming.{target_id}
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from news_sentry.core.async_rate_limiter import AsyncRateLimiter
from news_sentry.core.event_bus import EventBus

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 模块级引用（由应用启动时注入） ──
_data_dir: Path | None = None
_event_bus: EventBus | None = None
_limiter: AsyncRateLimiter | None = None

# ── 配置常量 ──
MAX_PAYLOAD_BYTES = 1_048_576  # 1MB
WEBHOOK_RATE_PER_SEC = 1.0
WEBHOOK_BURST = 5

# ── Schema ──


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
    webhook_id: str
    event_id: str
    message: str


# ── 初始化 ──


def init_webhook(data_dir: Path, event_bus: EventBus) -> None:
    """由应用 lifespan 调用注入依赖。"""
    global _data_dir, _event_bus, _limiter  # noqa: PLW0603
    _data_dir = data_dir
    _event_bus = event_bus
    _limiter = AsyncRateLimiter(rate=WEBHOOK_RATE_PER_SEC, burst=WEBHOOK_BURST)
    logger.info("Webhook 模块已初始化: max_payload=%d bytes", MAX_PAYLOAD_BYTES)


# ── 签名验证 ──


def _verify_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """验证 X-Signature-256 header 是否与 payload HMAC-SHA256 匹配。"""
    if not signature_header:
        return False
    # X-Signature-256: sha256=<hex>
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[7:]
    computed_hex = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed_hex, expected_hex)


def _get_webhook_secret() -> str:
    """从环境变量读取 webhook shared secret。

    生产环境应通过 WEBHOOK_SECRET 注入；本地开发回退到 'dev-secret'。
    """
    import os
    return os.environ.get("WEBHOOK_SECRET", "dev-secret")


# ── 端点 ──


@router.post("/api/v1/webhook")
async def receive_webhook(
    request: Request,
    x_signature_256: str | None = Header(None, alias="X-Signature-256"),
) -> JSONResponse:
    """接收外部系统推送的新闻事件。

    认证: X-Signature-256 header
    速率限制: 1 req/s (burst 5)
    Payload 限制: 1MB

    返回:
        202 Accepted on success
        400 Bad Request on oversized payload
        401 Unauthorized on invalid signature
        429 Too Many Requests on rate limit exceeded
    """
    # 0. 速率限制
    if _limiter is not None:
        try:
            await asyncio.wait_for(_limiter.acquire(), timeout=2.0)
        except TimeoutError:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "detail": "请求过于频繁，请稍后再试"},
            )

    # 0.1 依赖注入检查
    if _data_dir is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_initialized", "detail": "Webhook 模块未初始化"},
        )

    # 1. Payload 大小限制
    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        return JSONResponse(
            status_code=400,
            content={"error": "payload_too_large", "detail": f"最大 {MAX_PAYLOAD_BYTES} bytes"},
        )

    # 2. 签名验证
    secret = _get_webhook_secret()
    # 本地开发 dev-secret 不强制签名验证
    dev_secret = "dev-secret"  # noqa: S105
    if secret != dev_secret or x_signature_256:
        if not _verify_signature(body, x_signature_256, secret):
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_signature", "detail": "签名验证失败"},
            )

    # 3. 解析 JSON
    try:
        raw_body = body.decode("utf-8")
        payload = WebhookPayload.model_validate_json(raw_body)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_payload", "detail": f"解析失败: {e}"},
        )

    # 4. 验证 target_id（从 URL query param 或 metadata 中获取）
    target_id = request.query_params.get("target_id", "")
    if not target_id:
        # fallback: metadata 字段
        pm = payload.metadata or {}
        target_id = str(pm.get("target_id", ""))
    if not target_id:
        return JSONResponse(
            status_code=400,
            content={"error": "missing_target_id", "detail": "需要 target_id 参数"},
        )
    try:
        _validate_target_slug(target_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_target_id", "detail": f"target_id 格式无效: {target_id}"},
        )

    webhook_id = str(uuid.uuid4())[:12]

    # 5. 生成确定性 event_id
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    hash8 = hashlib.sha256(
        f"{payload.source_id}{payload.url}{date_str}".encode()
    ).hexdigest()[:8]
    event_id = f"ne-webhook-{payload.source_id}-{date_str}-{hash8}"

    # 6. 写入 data/{target_id}/raw/
    raw_dir = _data_dir / target_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    event_data: dict[str, Any] = {
        "id": event_id,
        "webhook_id": webhook_id,
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
    content = payload.content_original or "(empty)"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"---\n{fm}---\n\n{content}")

    logger.info(
        "Webhook accepted: webhook_id=%s event_id=%s target=%s source=%s",
        webhook_id, event_id, target_id, payload.source_id,
    )

    # 7. 通过 EventBus 发布通知
    if _event_bus is not None:
        try:
            await _event_bus.publish(
                f"news.incoming.{target_id}",
                {
                    "event_id": event_id,
                    "webhook_id": webhook_id,
                    "target_id": target_id,
                    "source_id": payload.source_id,
                    "title": payload.title_original,
                    "language": payload.language,
                },
            )
        except Exception:
            logger.warning("EventBus publish 失败（非阻塞）", exc_info=True)

    return JSONResponse(
        status_code=202,
        content=WebhookResponse(
            status="accepted",
            webhook_id=webhook_id,
            event_id=event_id,
            message=f"Event {event_id} saved to {target_id}/raw/",
        ).model_dump(),
    )


# ── 辅助 ──

def _validate_target_slug(target_id: str) -> None:
    """校验 target_id 仅含安全字符。"""
    if not target_id or not isinstance(target_id, str):
        raise ValueError("Invalid target_id")
    # 只允许字母、数字、连字符、下划线
    if not all(c.isalnum() or c in "-_" for c in target_id):
        raise ValueError(f"Invalid target_id: {target_id}")
    if len(target_id) > 64:
        raise ValueError(f"target_id too long: {len(target_id)}")
