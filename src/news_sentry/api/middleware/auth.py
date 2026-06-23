"""Auth middleware — token management, admin auth, rate limiting.

Extracted from api_server.py (Phase 2 拆分).

Usage:
    from news_sentry.api.middleware import auth
    auth.configure(store)  # called once in create_app() lifespan
"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict
from ipaddress import ip_address
from typing import Any

from fastapi import Depends, HTTPException, Request

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.auth import (  # noqa: F401 — re-export for convenience
    hash_password,
    verify_password,
)

# ── 本地回环检测（从 api_server 复制，避免循环导入）─


def _is_loopback_host(host: str | None) -> bool:
    """判断主机名/IP 是否为本机回环地址。"""
    value = (host or "").split(",", 1)[0].strip().lower()
    if not value:
        return False
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    if value in {"localhost", "testserver"}:
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def _is_loopback_request(request: Request) -> bool:
    """优先使用真实客户端地址，TestClient 回退到 Host。"""
    client_host = request.client.host if request.client else ""
    if client_host and client_host != "testclient":
        return _is_loopback_host(client_host)
    return _is_loopback_host(request.headers.get("host"))


def _is_testclient_default_host(request: Request) -> bool:
    """仅为默认 TestClient host 保留免登录兜底。"""
    client_host = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").split(",", 1)[0].strip().lower()
    return client_host == "testclient" and host.startswith("testserver")


# ── 模块级可配置状态（由 api_server.create_app() 注入）───

_store: AsyncStore | None = None


def configure(store: AsyncStore | None) -> None:
    """由 create_app() 调用，注入全局 AsyncStore。"""
    global _store
    _store = store


# ── 权限 ──────────────────────────────────────────────

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
_STREAM_TOKEN_STORE: dict[str, dict[str, Any]] = {}
_STREAM_TOKEN_TTL = 120  # 2 minutes


def _create_token_for_user(username: str, role: str, has_api_key: bool) -> dict[str, Any]:
    """为已认证用户创建 session token（内存写入）。"""
    token = secrets.token_hex(32)
    now = time.time()
    info = {
        "username": username,
        "role": role,
        "has_api_key": has_api_key,
        "created_at": now,
        "expires_at": now + _TOKEN_TTL,
    }
    _TOKEN_STORE[token] = info

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": _TOKEN_TTL,
        "username": username,
        "role": role,
        "has_api_key": has_api_key,
    }


async def _create_persistent_token_for_user(
    username: str,
    role: str,
    has_api_key: bool,
) -> dict[str, Any]:
    """创建 token，并在 SQLite 已就绪时同步持久化 session。"""
    result = _create_token_for_user(username, role, has_api_key)
    if _store is not None and _store._db is not None:  # noqa: SLF001
        await _store.create_session(
            result["access_token"],
            username,
            role,
            has_api_key,
            _TOKEN_TTL,
        )
    return result


def _create_stream_token_for_user(username: str, role: str) -> dict[str, Any]:
    """为 SSE 创建短期 stream token，避免把主 bearer 暴露到 URL。"""
    token = secrets.token_urlsafe(24)
    now = time.time()
    _STREAM_TOKEN_STORE[token] = {
        "username": username,
        "role": role,
        "created_at": now,
        "expires_at": now + _STREAM_TOKEN_TTL,
    }
    return {
        "stream_token": token,
        "token_type": "sse",
        "expires_in": _STREAM_TOKEN_TTL,
        "username": username,
        "role": role,
    }


def _verify_token(token: str) -> dict[str, Any] | None:
    """验证 Token 有效性（内存优先，SQLite 回退）。"""
    info = _TOKEN_STORE.get(token)
    if info:
        if time.time() > info["expires_at"]:
            _TOKEN_STORE.pop(token, None)
            return None
        return info
    return None


def _verify_stream_token(token: str) -> dict[str, Any] | None:
    """验证短期 SSE token。"""
    info = _STREAM_TOKEN_STORE.get(token)
    if info:
        if time.time() > info["expires_at"]:
            _STREAM_TOKEN_STORE.pop(token, None)
            return None
        return info
    return None


async def _verify_token_async(token: str) -> dict[str, Any] | None:
    """异步验证 Token（含 SQLite 回退 + 内存回填）。"""
    info = _verify_token(token)
    if info:
        return info
    # SQLite 回退：服务重启后内存为空，从持久化存储恢复
    if _store is not None and _store._db is not None:  # noqa: SLF001
        session = await _store.get_session(token)
        if session:
            if time.time() > session["expires_at"]:
                await _store.delete_session(token)
                return None
            # 回填到内存
            _TOKEN_STORE[token] = session
            return session
    return None


async def _revoke_sessions_for_username(username: str) -> None:
    """撤销指定用户的全部 bearer / stream token。"""
    for token, info in list(_TOKEN_STORE.items()):
        if info.get("username") == username:
            _TOKEN_STORE.pop(token, None)
    for token, info in list(_STREAM_TOKEN_STORE.items()):
        if info.get("username") == username:
            _STREAM_TOKEN_STORE.pop(token, None)
    if _store is not None and _store._db is not None:  # noqa: SLF001
        await _store.delete_sessions_for_user(username)


def _extract_bearer_token(request: Request) -> str | None:
    """从 Authorization header 提取 Bearer token。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


# ── 本地认证旁路 ───────────────────────────────────────


def _local_auth_bypass_enabled(request: Request) -> bool:
    """本地桌面/开发模式下跳过账号密码认证。"""
    explicit_env = os.environ.get("NEWSSENTRY_DEPLOYMENT_ENV", "").strip().lower()
    if explicit_env == "local":
        return _is_loopback_request(request)
    if explicit_env:
        return False
    return _is_testclient_default_host(request)


def _local_admin_user() -> dict[str, Any]:
    """本地免登录模式使用的虚拟管理员。"""
    return {
        "username": "local-admin",
        "role": "admin",
        "has_api_key": False,
        "local": True,
    }


# ── FastAPI 认证依赖 ───────────────────────────────────


async def get_current_user(request: Request) -> dict[str, Any]:
    """提取并验证 Bearer token，返回用户信息（内存 + SQLite 回退）。"""
    token = _extract_bearer_token(request)
    if token:
        info = await _verify_token_async(token)
        if info:
            # 检查 store 中的最新 api_key 状态
            if _store is not None:
                user = await _store.get_user(info["username"])
                if user:
                    info["has_api_key"] = bool(user.get("api_key"))
                    info["role"] = user.get("role", info["role"])
            return info
        if not _local_auth_bypass_enabled(request):
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    if _local_auth_bypass_enabled(request):
        return _local_admin_user()

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication")
    raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_permission(permission: str) -> Any:
    """依赖工厂：检查用户权限。"""

    async def _check(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
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
