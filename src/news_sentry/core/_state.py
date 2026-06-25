"""Shared state and sentinel classes for api_server utility modules.

Extracted from api_server.py to break circular import dependencies.
"""

from __future__ import annotations

import re
from typing import Any


class InvisibleIndexedEvent:
    """Sentinel for an indexed event that exists but is not public-visible."""


_INVISIBLE_INDEXED_EVENT = InvisibleIndexedEvent()

_SCRIPT_TAG_WITHOUT_NONCE_RE: re.Pattern[str] = re.compile(
    r"<script(?![^>]*\bnonce=)", re.IGNORECASE
)

# ── Runtime state (initialized by api_server._app_lifespan) ──
_store: Any = None
_data_dir: Any = None
_target_stores: dict[str, Any] = {}
_sse_lock: Any = None
_auto_collector_state: dict[str, Any] = {}
_ai_enrichment_state: dict[str, Any] = {
    "enabled": True,
    "interval_minutes": 60,
    "daily_request_limit": 45,
    "per_cycle_request_limit": 3,
    "max_chars_per_request": 6000,
    "cooldown_after_429_minutes": 120,
    "targets": ["all"],
    "candidate_limit": 200,
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_error": None,
    "next_run_at": None,
    "total_runs": 0,
    "last_updates": 0,
    "task": None,
}
_ai_enrichment_log: Any = None
_public_translation_state: dict[str, Any] = {
    "enabled": True,
    "interval_minutes": 5,
    "per_cycle_limit": 50,
    "candidate_limit": 500,
    "source_lang": "auto",
    "target_lang": "zh",
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_error": None,
    "next_run_at": None,
    "total_runs": 0,
    "last_updates": 0,
    "task": None,
}
_public_translation_log: Any = None
_log: Any = None
_admin_overview_cache: dict[str, Any] = {}
_admin_targets_cache: dict[str, Any] = {}
_collector_diagnostics_cache: dict[str, Any] = {}
_public_source_configs_cache: dict[str, Any] = {}
_target_validation_cache: dict[str, Any] = {}
_source_inventory_cache: dict[str, Any] = {}
_public_bootstrap_cache: dict[str, Any] = {}
_public_facets_cache: dict[str, Any] = {}
_public_regions_cache: dict[str, Any] = {}
_public_news_feed_cache: dict[str, Any] = {}
_event_bus: Any = None
_ws_manager: Any = None
_ws_sub_id: int = 0
_deployment_env: str = "development"
_skip_lifespan: bool = False

# ── Constants ──
_COLLECTOR_STAGES: tuple[str, ...] = ("collect", "filter", "judge", "output", "all")

# Public site
_PUBLIC_SITE_BASE_URL: str = "https://news-sentry.com"
_PUBLIC_SITE_NAME: str = "News Sentry"
_PUBLIC_SITE_TITLE: str = "News Sentry | 新闻哨兵"
_PUBLIC_SITE_DESCRIPTION: str = (
    "News Sentry 新闻哨兵面向中文读者追踪全球新闻，按地区、议题和相关对象筛选重点事件，"
    "提供中文摘要、原文标题、信源信息与 Breaking News 指数。"
)
_PUBLIC_APP_SHELL_CACHE_CONTROL: str = (
    "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
)

# ── 意大利语 SEO ─────────────────────────────────────────
_PUBLIC_SITE_TITLE_IT: str = "News Sentry | Sentinella delle Notizie"
_PUBLIC_SITE_DESCRIPTION_IT: str = (
    "News Sentry è una sentinella delle notizie globali per lettori cinesi e italiani. "
    "Traccia eventi chiave per regione, tema e soggetto, offrendo riassunti in cinese, "
    "titoli originali, fonti e l'indice Breaking News."
)
_PUBLIC_SHARED_JSON_CACHE_CONTROL: str = "public, max-age=30, s-maxage=60, stale-while-revalidate=300"
_PUBLIC_BOOTSTRAP_CACHE_CONTROL: str = "public, max-age=300, s-maxage=300, stale-while-revalidate=600"
_PUBLIC_BOOTSTRAP_CACHE_TTL_SECONDS: int = 300
_PUBLIC_REGIONS_CACHE_TTL_SECONDS: int = 300
_PUBLIC_FACETS_CACHE_TTL_SECONDS: int = 300

# Security
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

# Cache TTLs
_OVERVIEW_CACHE_TTL_SECONDS: int = 300
_ADMIN_CACHE_TTL_SECONDS: int = 300
_PUBLIC_SOURCE_CONFIG_CACHE_TTL_SECONDS: int = 300
_PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS: int = 60
_PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS: int = 15
_PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS: int = 300
_PUBLIC_NEWS_SLOW_LOG_MS: int = 3000
_PUBLIC_NEWS_FEATURED_SCORE: int = 60
_PUBLIC_NEWS_STAGE: str = "drafts"
_PUBLIC_ANALYSIS_STAGE: str = "drafts"
_PUBLIC_ANALYSIS_CHAIN_LIMIT: int = 10
_PUBLIC_NEWS_MAX_SCAN: int = 2000
_PUBLIC_NEWS_MIN_SCAN: int = 100
_PUBLIC_NEWS_MAX_PAGE_SIZE: int = 100
_PUBLIC_NEWS_DEFAULT_PAGE_SIZE: int = 20
_PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS: int = 60000
_PUBLIC_NEWS_IDLE_POLL_AFTER_MS: int = 120000
_PUBLIC_NEWS_MIN_POLL_AFTER_MS: int = 15000
_PUBLIC_NEWS_EVENT_DIRS: tuple[str, ...] = (
    "archive",
    "drafts",
    "evaluated",
    "published",
    "raw",
    "reviewed",
)
_PUBLIC_NEWS_INTERNAL_DATA_DIRS: tuple[str, ...] = (
    "backup",
    "cache",
    "eval",
    "locks",
    "logs",
    "memory",
    "tmp",
)
_PUBLIC_TEXT_LATIN1_HINTS: tuple[str, ...] = ("Ã", "Â", "â€")
_CHAR_ACCENTED_TO_BASIC = {
    "À": "à",
    "Á": "á",
    "Â": "â",
    "Ã": "ã",
    "Ä": "ä",
    "Å": "å",
    "Æ": "æ",
    "Ç": "ç",
    "È": "è",
    "É": "é",
    "Ê": "ê",
    "Ë": "ë",
    "Ì": "ì",
    "Í": "í",
    "Î": "î",
    "Ï": "ï",
    "Ñ": "ñ",
    "Ò": "ò",
    "Ó": "ó",
    "Ô": "ô",
    "Õ": "õ",
    "Ö": "ö",
    "Ø": "ø",
    "Œ": "œ",
    "Ù": "ù",
    "Ú": "ú",
    "Û": "û",
    "Ü": "ü",
    "Ý": "ý",
    "Ÿ": "ÿ",
}
_STRAY_ACCENTED_CAPS = str.maketrans(_CHAR_ACCENTED_TO_BASIC)
_RETIRED_TOPIC_TARGET_IDS: frozenset[str] = frozenset(
    {
        "africa-watch",
        "china-watch-en",
        "climate-water-food",
        "crisis-conflict",
        "critical-minerals",
        "defense-security",
        "digital-regulation",
        "energy-transition",
        "eu-policy",
        "fusion",
        "latin-america-watch",
        "middle-east-gulf",
        "migration-labor",
        "public-opinion-culture",
        "supply-chain-trade",
        "tech-ai-semiconductors",
        "us-policy",
    }
)

# Regex / validation
_SOURCE_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_-]*$")
_TARGET_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_-]*$")

# Region
_REGION_TYPE_LABELS: dict[str, str] = {
    "country": "地区",
    "region": "地区",
    "continent": "大洲",
    "global": "全球",
}
_REGION_TYPES: frozenset[str] = frozenset(_REGION_TYPE_LABELS)

# HTTP
_HTTP_PHRASES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}
