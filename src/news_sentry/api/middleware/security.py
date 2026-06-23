"""Security headers, CSP, cache headers, public site branding.

Extracted from api_server.py (Phase 2 拆分).
"""

from __future__ import annotations

import re
from typing import Literal

_SECURITY_HEADERS: dict[str, str] = {
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


def security_headers_with_script_nonce(nonce: str) -> dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    headers["Content-Security-Policy"] = _SECURITY_HEADERS["Content-Security-Policy"].replace(
        "script-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
    )
    return headers


_SCRIPT_TAG_WITHOUT_NONCE_RE = re.compile(r"<script(?![^>]*\bnonce=)", re.IGNORECASE)


def inject_script_nonce(html: str, nonce: str) -> str:
    return _SCRIPT_TAG_WITHOUT_NONCE_RE.sub(f'<script nonce="{nonce}"', html)


# ── 公共站点品牌 ────────────────────────────────────────

_PUBLIC_SITE_BASE_URL = "https://news-sentry.com"
_PUBLIC_SITE_NAME = "News Sentry"
_PUBLIC_SITE_TITLE = "News Sentry | 新闻哨兵"
_PUBLIC_SITE_DESCRIPTION = (
    "News Sentry 新闻哨兵面向中文读者追踪全球新闻，按地区、议题和相关对象筛选重点事件，"
    "提供中文摘要、原文标题、信源信息与 Breaking News 指数。"
)


# ── 公共 API 缓存 ───────────────────────────────────────

_PUBLIC_SHARED_JSON_CACHE_CONTROL = "public, max-age=30, s-maxage=60, stale-while-revalidate=300"


def public_shared_cache_headers(
    *,
    etag: str,
    cache_status: Literal["hit", "miss"],
    timing_name: str,
    header_name: str,
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": _PUBLIC_SHARED_JSON_CACHE_CONTROL,
        "Server-Timing": f"{timing_name};dur={max(0, int(elapsed_ms))}",
        f"X-News-Sentry-{header_name}-Cache": cache_status,
        f"X-News-Sentry-{header_name}-Elapsed-Ms": str(max(0, int(elapsed_ms))),
    }


def public_news_cache_headers(
    *,
    etag: str,
    cache_status: Literal["hit", "miss"],
    timing_name: str,
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": _PUBLIC_SHARED_JSON_CACHE_CONTROL,
        "Server-Timing": f"{timing_name};dur={max(0, int(elapsed_ms))}",
        "X-News-Sentry-News-Cache": cache_status,
        "X-News-Sentry-News-Elapsed-Ms": str(max(0, int(elapsed_ms))),
    }
