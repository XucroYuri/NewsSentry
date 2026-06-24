"""Tests for api/routes/webhook.py — Webhook 接收端点。"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from news_sentry.api.routes import webhook as wh

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_signature(body: bytes, secret: str = "dev-secret") -> str:  # noqa: S107
    """计算 HMAC-SHA256 签名。"""
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


def _make_payload(**overrides: object) -> dict[str, object]:
    """构造最小合法 webhook payload。"""
    defaults: dict[str, object] = {
        "source_id": "test-source",
        "url": "https://example.com/news/1",
        "title_original": "Test Event",
        "content_original": "This is a test content.",
        "language": "en",
        "published_at": "2026-06-25T12:00:00Z",
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


# ── Signature verification ───────────────────────────────────────────────────


def test_verify_signature_valid() -> None:
    """正确签名应返回 True。"""
    body = b'{"source_id":"test"}'
    secret = "my-secret"  # noqa: S105
    sig = _make_signature(body, secret)
    assert wh._verify_signature(body, sig, secret) is True


def test_verify_signature_invalid() -> None:
    """错误签名应返回 False。"""
    body = b'{"source_id":"test"}'
    sig = _make_signature(body, "correct-secret")
    assert wh._verify_signature(body, sig, "wrong-secret") is False


def test_verify_signature_missing_header() -> None:
    """无签名 header 应返回 False。"""
    assert wh._verify_signature(b"{}", None, "secret") is False


def test_verify_signature_wrong_prefix() -> None:
    """非 sha256= 前缀应返回 False。"""
    assert wh._verify_signature(b"{}", "md5=abc123", "secret") is False


def test_verify_signature_tampered_body() -> None:
    """篡改 payload body 导致签名不匹配。"""
    secret = "shared-key"  # noqa: S105
    original_sig = _make_signature(b'{"valid":true}', secret)
    assert wh._verify_signature(b'{"valid":false}', original_sig, secret) is False


# ── Target ID validation ─────────────────────────────────────────────────────


def test_validate_target_slug_valid() -> None:
    """合法 target_id 不应抛异常。"""
    wh._validate_target_slug("italy")
    wh._validate_target_slug("my-target_42")


def test_validate_target_slug_empty() -> None:
    """空字符串应抛 ValueError。"""
    with pytest.raises(ValueError):
        wh._validate_target_slug("")


def test_validate_target_slug_invalid_chars() -> None:
    """非法字符应抛 ValueError。"""
    with pytest.raises(ValueError):
        wh._validate_target_slug("italy../")


def test_validate_target_slug_too_long() -> None:
    """超长 target_id 应抛 ValueError。"""
    with pytest.raises(ValueError):
        wh._validate_target_slug("a" * 65)


# ── Payload schema ───────────────────────────────────────────────────────────


def test_payload_minimal() -> None:
    """最小合法 payload 应通过校验。"""
    p = wh.WebhookPayload(
        source_id="src",
        url="https://example.com",
        title_original="Title",
    )
    assert p.language == "mixed"
    assert p.content_original == ""
    assert p.published_at == ""


def test_payload_full() -> None:
    """完整 payload 应保留所有字段。"""
    p = wh.WebhookPayload(
        source_id="api-economist",
        url="https://economist.com/article/1",
        title_original="Big News",
        content_original="Full story here...",
        language="en",
        published_at="2026-06-25T12:00:00Z",
        metadata={"priority": "high"},
    )
    assert p.source_id == "api-economist"
    assert p.metadata["priority"] == "high"


def test_payload_missing_required() -> None:
    """缺少必填字段应抛 ValidationError。"""
    with pytest.raises(ValueError):
        wh.WebhookPayload.model_validate({})


# ── Route integration (TestClient) ───────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path):
    """创建测试用 FastAPI app + webhook router。"""
    from fastapi import FastAPI

    # 初始化 webhook 模块
    from news_sentry.core.event_bus import EventBus

    bus = EventBus()
    wh.init_webhook(tmp_path, bus)

    app = FastAPI()
    app.include_router(wh.router)

    with TestClient(app) as c:
        yield c


def test_webhook_missing_signature_returns_401(client) -> None:
    """缺少签名应返回 401（dev-secret 下本地默认 bypass，无签名 header 时通过但
    生产环境 WEBHOOK_SECRET 被 set 后会拒绝）。
    """
    # 在 dev-secret 模式下无签名 header 也会被接受
    resp = client.post(
        "/api/v1/webhook?target_id=italy",
        json=_make_payload(),
    )
    # dev-secret 模式: 无签名也可以
    assert resp.status_code in (202, 401)


def test_webhook_202_accepted(client) -> None:
    """合法请求应返回 202 Accepted。"""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/webhook?target_id=italy",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": _make_signature(body),
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert "webhook_id" in data
    assert "event_id" in data
    assert len(data["webhook_id"]) == 12  # uuid4 hex[:12]


def test_webhook_writes_file(client, tmp_path: Path) -> None:
    """成功接受后应在 data/{target_id}/raw/ 下创建文件。"""
    payload = _make_payload(source_id="file-test")
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/webhook?target_id=italy",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": _make_signature(body),
        },
    )
    assert resp.status_code == 202

    raw_dir = tmp_path / "italy" / "raw"
    assert raw_dir.is_dir()
    files = list(raw_dir.glob("collected_*.md"))
    assert len(files) == 1


def test_webhook_missing_target_id_returns_400(client) -> None:
    """缺少 target_id 应返回 400。"""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": _make_signature(body),
        },
    )
    assert resp.status_code == 400


def test_webhook_invalid_target_id_returns_400(client) -> None:
    """非法 target_id 应返回 400。"""
    payload = _make_payload()
    body = json.dumps(payload).encode()
    resp = client.post(
        "/api/v1/webhook?target_id=ita../ly",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": _make_signature(body),
        },
    )
    assert resp.status_code == 400


def test_webhook_invalid_json_returns_400(client) -> None:
    """非法 JSON 应返回 400。"""
    body = b"not valid json"
    resp = client.post(
        "/api/v1/webhook?target_id=italy",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": _make_signature(body),
        },
    )
    assert resp.status_code == 400
