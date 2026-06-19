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
import base64
import json
import logging
import math
import os
import re
import secrets
import shutil
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html import escape as html_escape
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, BeforeValidator, Field, ValidationError, field_validator

from news_sentry.core.ai_enrichment import (
    AIEnrichmentConfig,
    AIEnrichmentEngine,
    normalize_ai_enrichment_config,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.auth import hash_password, verify_password
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions
from news_sentry.core.config_cache import ConfigCache
from news_sentry.core.markdown_export import (
    render_canonical_event_markdown,
    render_news_event_markdown,
)
from news_sentry.core.public_site_projection import PublicSiteProjectionStore, SitemapEntry
from news_sentry.core.public_translation import (
    PublicTranslationConfig,
    PublicTranslationEngine,
    normalize_public_translation_config,
    public_publication_ready,
    public_translation_ready,
)
from news_sentry.core.source_inventory import SourceInventoryService
from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.classification_taxonomy import (
    canonical_l0,
    l0_query_values,
    normalize_classification,
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


def _security_headers_with_script_nonce(nonce: str) -> dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    headers["Content-Security-Policy"] = _SECURITY_HEADERS["Content-Security-Policy"].replace(
        "script-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
    )
    return headers


_SCRIPT_TAG_WITHOUT_NONCE_RE = re.compile(r"<script(?![^>]*\bnonce=)", re.IGNORECASE)


def _inject_script_nonce(html: str, nonce: str) -> str:
    return _SCRIPT_TAG_WITHOUT_NONCE_RE.sub(f'<script nonce="{nonce}"', html)


_PUBLIC_SITE_BASE_URL = "https://news-sentry.com"
_PUBLIC_SITE_NAME = "News Sentry"
_PUBLIC_SITE_DESCRIPTION = (
    "News Sentry 公共新闻流提供面向读者的国际新闻摘要、来源脉络与目标监控视角。"
)
_PUBLICATION_SITE_TITLE = "News Sentry | 跨境新闻信号过滤器"
_PUBLICATION_SITE_DESCRIPTION = (
    "News Sentry 是面向中文专业读者的跨境观察哨兵，追踪海外政策、"
    "产业、舆论和供应链变化对中国企业与跨境业务的影响。"
)
_PUBLICATION_SAMPLE_UPDATED_AT = "2026-06-19 08:00 UTC"
_PUBLICATION_SAMPLE_SIGNALS: list[dict[str, str]] = [
    {
        "level": "S1",
        "label": "政策变化",
        "title": "欧盟贸易防御工具仍是对华出口合规的关键观察项",
        "judgment": (
            "对依赖欧盟市场的中国制造和跨境卖家，反倾销、反补贴与 "
            "CBAM 相关更新会直接影响报价、交付周期和客户沟通。"
        ),
        "source": "European Commission Trade Defence",
        "source_url": "https://policy.trade.ec.europa.eu/enforcement-and-protection/trade-defence_en",
        "source_time": "来源页持续更新",
        "captured_time": _PUBLICATION_SAMPLE_UPDATED_AT,
        "impact": "中国出口企业、欧洲渠道商、合规团队",
        "watch_next": "新立案调查、临时税率、实施条例和企业豁免窗口。",
    },
    {
        "level": "S1",
        "label": "市场准入",
        "title": "美国关税与出口管制仍是出海供应链的高敏变量",
        "judgment": (
            "面向美国市场的硬件、消费电子和高技术链条需要持续跟踪 "
            "Section 301、实体清单和关键技术限制的叠加影响。"
        ),
        "source": "USTR Section 301 / Tariff Actions",
        "source_url": "https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions",
        "source_time": "来源页持续更新",
        "captured_time": _PUBLICATION_SAMPLE_UPDATED_AT,
        "impact": "跨境电商、制造外迁团队、北美销售负责人",
        "watch_next": "税率复审、公众意见征询、豁免清单和行业游说信号。",
    },
    {
        "level": "S2",
        "label": "供应链变化",
        "title": "日本产业政策对先进制造供应链具有早期指示意义",
        "judgment": (
            "日本经产省公告常提前暴露半导体、能源和关键材料领域的 "
            "补贴方向，对区域产能布局和客户需求有参考价值。"
        ),
        "source": "METI Press Releases",
        "source_url": "https://www.meti.go.jp/english/press/",
        "source_time": "来源页持续更新",
        "captured_time": _PUBLICATION_SAMPLE_UPDATED_AT,
        "impact": "半导体链条、新能源企业、日本市场团队",
        "watch_next": "补贴对象、采购限制、联合研发和区域招商政策。",
    },
    {
        "level": "S2",
        "label": "产业信号",
        "title": "德国工业政策和能源价格信号影响欧洲制造需求",
        "judgment": (
            "德国制造业订单、能源政策和产业补贴变化，通常会传导到 "
            "中国零部件、设备和工业服务供应商。"
        ),
        "source": "BMWK Federal Ministry for Economic Affairs",
        "source_url": "https://www.bmwk.de/Navigation/EN/Home/home.html",
        "source_time": "来源页持续更新",
        "captured_time": _PUBLICATION_SAMPLE_UPDATED_AT,
        "impact": "汽车零部件、工业设备、欧洲 B2B 团队",
        "watch_next": "能源补贴、产业转型基金、汽车链条调整和工会谈判。",
    },
    {
        "level": "S3",
        "label": "舆论风险",
        "title": "法国监管与消费者议题会放大跨境品牌声誉风险",
        "judgment": (
            "法国市场对平台责任、数据保护和消费权益的监管讨论较敏感，"
            "跨境品牌需要提前准备客服、合规和公关口径。"
        ),
        "source": "French Ministry of Economy",
        "source_url": "https://www.economie.gouv.fr/",
        "source_time": "来源页持续更新",
        "captured_time": _PUBLICATION_SAMPLE_UPDATED_AT,
        "impact": "DTC 品牌、平台卖家、欧洲合规负责人",
        "watch_next": "平台规则、消费者保护处罚、数据监管和媒体关注度。",
    },
]
_PUBLICATION_TARGETS: list[dict[str, str]] = [
    {
        "id": "china-watch-en",
        "name": "China Watch EN",
        "summary": "跟踪英文世界对中国政策、产业和地缘议题的外部叙事。",
    },
    {
        "id": "france",
        "name": "France",
        "summary": "观察法国监管、消费市场和欧盟政策互动。",
    },
    {
        "id": "germany",
        "name": "Germany",
        "summary": "关注德国工业、能源、汽车链和欧洲制造需求。",
    },
    {
        "id": "italy",
        "name": "Italy",
        "summary": "跟踪意大利政经、产业政策和地中海供应链信号。",
    },
    {
        "id": "japan",
        "name": "Japan",
        "summary": "观察日本产业政策、先进制造和区域供应链变化。",
    },
]
_PUBLICATION_TRUST_PAGES: dict[str, dict[str, Any]] = {
    "about": {
        "title": "关于 News Sentry",
        "eyebrow": "About",
        "intro": (
            "News Sentry 是跨境观察哨兵，服务需要快速理解海外变化的中文"
            "专业读者。我们把公开新闻、官方文件和权威来源整理成可追踪的信号。"
        ),
        "needle": "编辑标准",
        "points": [
            "编辑标准：优先选择对中国企业、跨境业务和供应链有实质影响的事件。",
            "产品边界：News Sentry 增强人工研判，不自动替代编辑判断。",
            "信任承诺：事实来源可追溯，样例内容清楚标记，不伪装成实时自动结果。",
        ],
    },
    "method": {
        "title": "方法论",
        "eyebrow": "Method",
        "intro": (
            "News Sentry 的方法论不是追求全量搬运，而是把采集、过滤、研判、"
            "输出和反馈串成可审计流程。"
        ),
        "needle": "筛选流程",
        "points": [
            "筛选流程：先确认来源与事实，再判断对地区、产业链和主体对象的影响。",
            "AI 辅助：AI 用于摘要、归类和初步研判，关键发布判断保留人工介入。",
            "质量门槛：首页精选必须有摘要、推荐理由和明确分类。",
        ],
    },
    "sources": {
        "title": "来源透明度",
        "eyebrow": "Sources",
        "intro": (
            "公开站把来源视为信任资产。来源页会逐步展示覆盖范围、活跃度、"
            "可信度说明和最近进入精选的内容。"
        ),
        "needle": "来源透明度",
        "points": [
            "来源透明度：优先使用官方机构、权威媒体、监管公告和可验证的一手材料。",
            "覆盖范围：P0 聚焦中外互动、海外政策、产业和供应链信号。",
            "后续升级：P1 将来源页扩展为来源雷达，展示活跃度和精选记录。",
        ],
    },
    "subscribe": {
        "title": "订阅 News Sentry",
        "eyebrow": "Subscribe",
        "intro": (
            "P0 先开放订阅入口和内容形态说明，P2 会补齐邮件确认、退订页、"
            "目标订阅和 RSS 输出。"
        ),
        "needle": "每日信号",
        "points": [
            "每日信号：每天汇总 3-5 条最值得跨境团队关注的变化。",
            "每周观察：把一周信号串联成趋势判断，适合管理层和团队同步。",
            "目标更新：围绕国家、政策议题、产业链或主体对象发送变化提醒。",
        ],
    },
}

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
    monitoring_type: str = "country"
    monitoring_label: str = "国别监控目标"
    topic_label: str | None = None
    source_count: int
    event_count: int = 0
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False


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
    source_ref: str | None = None
    display_name: str
    type: str  # rss | api | opencli | social
    enabled: bool
    archived: bool = False
    deprecated: bool = False
    deprecated_reason: str | None = None
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
    model_env_var: str | None = None
    model_pool: list[str] = []
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
    model_env_var: str | None = None
    model_pool: list[str] | None = None
    max_cost_usd_per_call: float | None = None
    audit: bool | None = None
    fallback_route_ids: list[str] | None = None


class CollectorConfigUpdate(BaseModel):
    """自动采集器运行配置更新请求。"""

    enabled: bool | None = None
    target_ids: list[str] | str | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    stage: str | None = None


class AIEnrichmentConfigUpdate(BaseModel):
    """低频 AI 增强运行配置更新请求。"""

    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    daily_request_limit: int | None = Field(default=None, ge=1, le=1000)
    per_cycle_request_limit: int | None = Field(default=None, ge=1, le=20)
    max_chars_per_request: int | None = Field(default=None, ge=500, le=40000)
    cooldown_after_429_minutes: int | None = Field(default=None, ge=5, le=1440)
    targets: list[str] | str | None = None
    candidate_limit: int | None = Field(default=None, ge=1, le=2000)


class PublicTranslationConfigUpdate(BaseModel):
    """公共站翻译 worker 运行配置更新请求。"""

    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    per_cycle_limit: int | None = Field(default=None, ge=1, le=500)
    candidate_limit: int | None = Field(default=None, ge=1, le=5000)
    source_lang: str | None = None
    target_lang: str | None = None


class CanonicalBackfillRequest(BaseModel):
    target_id: str
    since: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    apply: bool = False
    projection_run_id: str | None = None


RESEARCH_ARTIFACT_TYPES = {
    "review_state",
    "annotation",
    "note",
    "merge_decision",
    "split_decision",
}
RESEARCH_ARTIFACT_STATUSES = {"open", "resolved", "archived"}
RESEARCH_REVIEW_DECISIONS = {
    "confirmed",
    "needs_merge",
    "needs_split",
    "needs_more_evidence",
    "not_relevant",
}


class ResearchArtifactCreateRequest(BaseModel):
    target_id: str
    artifact_type: str
    title: str
    body: str = ""
    subject_type: str = "canonical_event"
    subject_id: str
    status: str = "open"
    visibility: str = "local_private"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, value: str) -> str:
        if value not in RESEARCH_ARTIFACT_TYPES:
            raise ValueError(f"Unsupported research artifact type: {value}")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in RESEARCH_ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported research artifact status: {value}")
        return value

    @field_validator("subject_type")
    @classmethod
    def validate_subject_type(cls, value: str) -> str:
        if value != "canonical_event":
            raise ValueError("MVP only supports canonical_event artifacts")
        return value


class ResearchArtifactPatchRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in RESEARCH_ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported research artifact status: {value}")
        return value


class ResearchGraphMergeRequest(BaseModel):
    target_id: str
    decision_artifact_id: str | None = None
    survivor_canonical_event_id: str
    merged_canonical_event_ids: list[str] = Field(min_length=1)
    title_override: str | None = None
    summary_override: str | None = None
    dry_run: bool = True


class ResearchGraphSplitRequest(BaseModel):
    target_id: str
    decision_artifact_id: str | None = None
    source_canonical_event_id: str
    affected_mention_ids: list[str] = Field(min_length=1)
    new_title: str | None = None
    new_summary: str | None = None
    dry_run: bool = True


class TargetCreateRequest(BaseModel):
    """Target 创建请求。"""

    mode: Literal["template", "clone"]
    target_id: str
    display_name: str
    language_scope: dict[str, Any]
    timezone: str
    monitoring_type: Literal["country", "topic"] | None = None
    topic_label: str | None = None
    source_target_id: str | None = None
    template_id: str | None = None


class TargetPatchRequest(BaseModel):
    """Target 生命周期工作台内的基础资料更新。"""

    display_name: str | None = None
    monitoring_type: Literal["country", "topic"] | None = None
    topic_label: str | None = None
    language_scope: dict[str, Any] | None = None
    timezone: str | None = None
    classification: dict[str, Any] | None = None
    focus_areas: list[dict[str, Any]] | None = None
    lifecycle: dict[str, Any] | None = None


class ArchiveRequest(BaseModel):
    """归档操作请求。"""

    reason: str | None = None


class SourceCreateRequest(BaseModel):
    """标准信源创建请求。"""

    source_id: str
    display_name: str
    type: Literal["rss", "api", "opencli"]
    source_ref: str | None = None
    url: str | None = None
    endpoint: dict[str, Any] | None = None
    api_mapping: dict[str, Any] | None = None
    tool_ref: str | None = None
    tool_params: dict[str, Any] | None = None
    opencli_command: str | None = None
    sandbox_profile_ref: str | None = None
    credibility_base: float = Field(default=0.75, ge=0.0, le=1.0)
    fetch_interval_minutes: int = Field(default=30, ge=1)
    max_items_per_run: int = Field(default=20, ge=1)
    timeout_seconds: int = Field(default=20, ge=1, le=300)
    enabled: bool = True
    notes: str | None = None


class SourcePatchRequest(BaseModel):
    """标准信源编辑请求。"""

    display_name: str | None = None
    url: str | None = None
    endpoint: dict[str, Any] | None = None
    api_mapping: dict[str, Any] | None = None
    tool_ref: str | None = None
    tool_params: dict[str, Any] | None = None
    opencli_command: str | None = None
    sandbox_profile_ref: str | None = None
    credibility_base: float | None = Field(default=None, ge=0.0, le=1.0)
    fetch_interval_minutes: int | None = Field(default=None, ge=1)
    max_items_per_run: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    enabled: bool | None = None
    notes: str | None = None


class SocialDimensionCreateRequest(BaseModel):
    """社媒维度创建请求。"""

    platform: str = "twitter"
    dimension: str
    collect_mode: str = "opencli_bridge"
    session_profile_ref: str | None = None
    notes: str | None = None


class SocialDimensionPatchRequest(BaseModel):
    """社媒维度编辑请求。"""

    collect_mode: str | None = None
    session_profile_ref: str | None = None
    notes: str | None = None


class SocialAccountCreateRequest(BaseModel):
    """社媒账号创建请求。"""

    handle: str
    display_name: str | None = None
    url: str | None = None
    tier: str | None = None
    category: str | None = None
    monitor_mode: str = "active"
    fetch_max_per_run: int | None = Field(default=None, ge=1)
    notes: str | None = None


class SocialAccountPatchRequest(BaseModel):
    """社媒账号编辑请求。"""

    display_name: str | None = None
    url: str | None = None
    tier: str | None = None
    category: str | None = None
    monitor_mode: str | None = None
    fetch_max_per_run: int | None = Field(default=None, ge=1)
    notes: str | None = None


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
    last_error: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
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


class PublicAnalysisSummary(BaseModel):
    """公开分析快照的摘要统计。"""

    total_events: int = 0
    high_value_events: int = 0
    avg_news_value_score: float | None = None
    avg_china_relevance: float | None = None


class PublicDistributionItem(BaseModel):
    """公开聚合分布条目。"""

    name: str
    count: int


class PublicSourceDistributionItem(BaseModel):
    """公开信源分布条目。"""

    source_id: str
    display_name: str
    count: int


class PublicEntityItem(BaseModel):
    """公开实体聚合条目。"""

    name: str
    entity_type: str = ""
    mention_count: int = 0


class PublicChainItem(BaseModel):
    """公开追踪链摘要。"""

    root_event_id: str
    event_count: int
    latest_time: str = ""
    latest_title: str = ""
    narrative_summary: str = ""


class PublicAnalysisResponse(BaseModel):
    """公开 target 分析快照。"""

    target_id: str
    target_name: str
    days: int
    summary: PublicAnalysisSummary
    classification_distribution: list[PublicDistributionItem] = Field(default_factory=list)
    source_distribution: list[PublicSourceDistributionItem] = Field(default_factory=list)
    top_entities: list[PublicEntityItem] = Field(default_factory=list)
    topic_trends: list[TopicTrendItem] = Field(default_factory=list)
    sentiment_trend: list[DailySentimentCount] = Field(default_factory=list)
    active_chains: list[PublicChainItem] = Field(default_factory=list)
    generated_at: str


class PublicNewsSource(BaseModel):
    """读者侧新闻来源摘要。"""

    id: str
    name: str
    type: Literal["rss", "api", "web", "social", "official", "unknown"] = "unknown"
    credibility_label: str | None = Field(default=None, alias="credibilityLabel")

    model_config = {"populate_by_name": True}


class PublicNewsEntity(BaseModel):
    """读者侧实体摘要。"""

    name: str
    type: str | None = None


class PublicNewsItem(BaseModel):
    """公共门户使用的读者侧新闻条目。"""

    id: str
    target_id: str = Field(alias="targetId")
    target_label: str = Field(alias="targetLabel")
    source: PublicNewsSource
    published_at: str = Field(alias="publishedAt")
    title: str
    original_title: str | None = Field(default=None, alias="originalTitle")
    summary: str | None = None
    recommendation_reason: str | None = Field(default=None, alias="recommendationReason")
    full_content: str | None = Field(default=None, alias="fullContent")
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")
    original_url: str | None = Field(default=None, alias="originalUrl")
    detail_url: str = Field(alias="detailUrl")
    tags: list[str] = Field(default_factory=list)
    entities: list[PublicNewsEntity] = Field(default_factory=list)
    related_count: int = Field(default=0, alias="relatedCount")
    discussion_count: int | None = Field(default=None, alias="discussionCount")
    value_label: Literal["精选", "关注", "普通", "待评估"] = Field(alias="valueLabel")
    value_score: int | float | None = Field(default=None, alias="valueScore")
    china_relevance_label: Literal["高", "中", "低", "未知"] = Field(
        default="未知",
        alias="chinaRelevanceLabel",
    )

    model_config = {"populate_by_name": True}


class PublicNewsFeedResponse(BaseModel):
    """公共新闻流响应 envelope，支持低负担增量更新。"""

    items: list[PublicNewsItem]
    latest_cursor: str | None = Field(default=None, alias="latestCursor")
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    poll_after_ms: int = Field(default=60000, alias="pollAfterMs")
    has_newer: bool = Field(default=False, alias="hasNewer")
    total: int = 0

    model_config = {"populate_by_name": True}


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


# ── FastAPI 认证依赖 ───────────────────────────────────

# _store 在 create_app() 内赋值，此处为模块级引用占位
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


VISIBLE_INDEX_QUERY_BATCH_SIZE = 1000


class InvisibleIndexedEvent:
    """Sentinel for an indexed event that exists but is not public-visible."""


_INVISIBLE_INDEXED_EVENT = InvisibleIndexedEvent()


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


async def _read_json_object(request: Request) -> dict[str, Any]:
    """读取 JSON object body，并把空/非法 JSON 转成 400。"""
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    return cast(dict[str, Any], body)


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


def _latest_run_log_summary(data_dir: Path) -> dict[str, Any] | None:
    """从所有 target 日志中找最近一次真实运行，用于服务重启后的状态恢复。"""
    if not data_dir.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for target_dir in sorted(data_dir.iterdir()):
        if not target_dir.is_dir():
            continue
        candidates.extend(_load_run_logs(data_dir, target_dir.name, 1))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("ended_at") or item.get("started_at") or "")


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


def _event_matches_date(event: dict[str, Any], date: str | None) -> bool:
    if date is None:
        return True
    return (event.get("published_at") or "").startswith(date)


def _event_matches_search(event: dict[str, Any], search: str | None) -> bool:
    if search is None:
        return True
    keyword = search.lower()
    return keyword in (event.get("title_original") or "").lower()


def _visible_index_event_from_row(
    data_dir: Path,
    target_id: str,
    stage: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    file_path = row.get("file_path")
    if not _indexed_file_path_is_visible_in_stage(
        data_dir,
        target_id,
        stage,
        file_path,
    ):
        return None
    event = _load_indexed_event_frontmatter(data_dir, target_id, stage, row)
    if event is None:
        event = _event_from_index_row(row)
    return _merge_index_metadata(event, row)


async def _visible_index_events_page(
    store: Any,
    data_dir: Path,
    target_id: str,
    *,
    stage: str,
    page: int,
    page_size: int,
    date: str | None = None,
    search: str | None = None,
    source_id: str | None = None,
    classification_l0: str | None = None,
    min_score: int | None = None,
    sentiment: str | None = None,
    entity_name: str | None = None,
    topic_tag: str | None = None,
    exact_total: bool = True,
) -> dict[str, Any]:
    """读取可公开展示的 index 事件，再分页，避免 stale 行占据页面。"""
    start = (page - 1) * page_size
    page_events: list[dict[str, Any]]

    if not exact_total and date is None and search is None:
        offset = start
        index_total = 0
        page_events = []

        while len(page_events) < page_size:
            result = await store.query_events_paginated(
                target_id=target_id,
                stage=stage,
                limit=page_size,
                offset=offset,
                source_id=source_id,
                classification_l0=classification_l0,
                min_score=min_score,
                sentiment=sentiment,
                entity_name=entity_name,
                topic_tag=topic_tag,
            )
            index_total = result["total"]
            rows = result["rows"]
            if not rows:
                break

            for row in rows:
                event = _visible_index_event_from_row(data_dir, target_id, stage, row)
                if event is not None:
                    page_events.append(event)
                    if len(page_events) >= page_size:
                        break

            offset += len(rows)
            if offset >= index_total:
                break

        return {
            "index_total": index_total,
            "total": index_total,
            "events": page_events,
        }

    end = start + page_size
    offset = 0
    index_total = 0
    visible_total = 0
    page_events = []

    while True:
        result = await store.query_events_paginated(
            target_id=target_id,
            stage=stage,
            limit=VISIBLE_INDEX_QUERY_BATCH_SIZE,
            offset=offset,
            source_id=source_id,
            classification_l0=classification_l0,
            min_score=min_score,
            sentiment=sentiment,
            entity_name=entity_name,
            topic_tag=topic_tag,
        )
        index_total = result["total"]
        rows = result["rows"]
        if not rows:
            break

        for row in rows:
            event = _visible_index_event_from_row(data_dir, target_id, stage, row)
            if event is None:
                continue
            if not _event_matches_date(event, date):
                continue
            if not _event_matches_search(event, search):
                continue
            if start <= visible_total < end:
                page_events.append(event)
            visible_total += 1

        offset += len(rows)
        if offset >= index_total:
            break

    return {
        "index_total": index_total,
        "total": visible_total,
        "events": page_events,
    }


async def _store_has_target_event_index(store: Any, target_id: str) -> bool:
    get_count = getattr(store, "get_target_event_count", None)
    if get_count is None:
        return False
    count = await get_count(target_id)
    return int(count or 0) > 0


def _first_sentence(text: str, max_chars: int = 60) -> str:
    """提取适合新闻流展示的第一句摘要。"""
    compact = " ".join(text.split())
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in compact:
            compact = compact.split(sep, 1)[0] + sep
            break
    if len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def _event_score(ev: dict[str, Any]) -> int | float | None:
    score = ev.get("news_value_score", ev.get("importance_score"))
    return score if isinstance(score, (int, float)) else None


def _event_classification(ev: dict[str, Any]) -> dict[str, Any] | None:
    direct = ev.get("classification")
    if isinstance(direct, dict):
        return normalize_classification(direct)
    metadata = ev.get("metadata")
    if isinstance(metadata, dict):
        classification = metadata.get("classification")
        if isinstance(classification, dict):
            return normalize_classification(classification)
    return None


def _classification_l0_label(value: Any) -> str:
    label = canonical_l0(str(value).strip()) if value is not None else ""
    return label or "uncategorized"


def _classification_diagnostics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    distribution: dict[str, int] = defaultdict(int)
    for ev in events:
        classification = _event_classification(ev) or {}
        distribution[_classification_l0_label(classification.get("l0"))] += 1
    result = dict(distribution)
    return {
        "distribution": result,
        "uncategorized_count": result.get("uncategorized", 0),
    }


async def _classification_diagnostics_from_store(
    target_id: str,
    store: AsyncStore | None,
) -> dict[str, Any] | None:
    if store is None or store._db is None:  # noqa: SLF001
        return None
    try:
        async with store._db.execute(  # noqa: SLF001
            "SELECT COALESCE(NULLIF(TRIM(classification_l0), ''), 'uncategorized') AS label, "
            "COUNT(*) AS count "
            "FROM event_index "
            "WHERE target_id = ? "
            "GROUP BY label",
            (target_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception:  # noqa: S112
        logger.exception("Failed to load classification diagnostics from store")
        return None
    distribution: dict[str, int] = defaultdict(int)
    for row in rows:
        distribution[_classification_l0_label(row[0])] += int(row[1])
    return {
        "distribution": distribution,
        "uncategorized_count": distribution.get("uncategorized", 0),
    }


def _event_topic_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("topic_tags")
    metadata = ev.get("metadata")
    if not raw and isinstance(metadata, dict):
        raw = metadata.get("topic_tags")
    return [str(tag) for tag in raw[:2]] if isinstance(raw, list) else []


def _tag_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("code", "name", "label", "title"):
            if key in value and value[key] is not None and value[key] != "":
                return str(value[key])
        return ""
    return "" if value is None or value == "" else str(value)


def _event_flat_tags(ev: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    classification = _event_classification(ev)
    if classification:
        l0 = classification.get("l0")
        if l0 is not None and l0 != "":
            tags.append(str(l0))
        l1 = classification.get("l1")
        if isinstance(l1, list):
            tags.extend(tag for item in l1[:1] if (tag := _tag_text(item)))
        elif l1 is not None and l1 != "":
            if tag := _tag_text(l1):
                tags.append(tag)

    tags.extend(_event_topic_tags(ev))
    entities = ev.get("nlp_entities") or ev.get("entities") or []
    if isinstance(entities, list):
        for entity in entities:
            name = entity.get("name") if isinstance(entity, dict) else entity
            if name is not None and name != "":
                tags.append(str(name))
                break

    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:4]


def _event_ai_reason(ev: dict[str, Any]) -> str:
    public_reason = _event_explicit_recommendation_reason(ev)
    if public_reason:
        return public_reason
    raw_judge = ev.get("judge_result")
    judge = raw_judge if isinstance(raw_judge, dict) else {}
    rationale = judge.get("rationale")
    return _first_sentence(rationale) if isinstance(rationale, str) else ""


_PUBLIC_CLASSIFICATION_LABELS = {
    "international-relations": "国际关系",
    "politics": "政治",
    "economy": "经济",
    "society": "社会",
    "culture": "文化",
    "technology": "科技",
}


def _public_target_reason_label(target_id: str) -> str:
    label = _target_display_name(target_id).strip() or target_id
    for suffix in ("新闻监控", "监控目标", "监控"):
        if label.endswith(suffix):
            label = label[: -len(suffix)].strip()
    return label or target_id


def _public_classification_reason_label(ev: dict[str, Any]) -> str:
    classification = _event_classification(ev) or {}
    l0 = canonical_l0(str(classification.get("l0") or ""))
    return _PUBLIC_CLASSIFICATION_LABELS.get(l0, "")


def _public_synthesized_recommendation_reason(target_id: str, ev: dict[str, Any]) -> str:
    target_label = _public_target_reason_label(target_id)
    category_label = _public_classification_reason_label(ev)
    score = _event_score(ev)
    china_label = _public_china_relevance_label(ev.get("china_relevance"))

    subject = f"{target_label}相关"
    if category_label:
        subject += f"{category_label}信号"
    else:
        subject += "新闻信号"

    signals: list[str] = []
    if score is not None:
        signals.append(f"价值分 {round(score)}")
    if china_label != "未知":
        signals.append(f"涉中关联{china_label}")
    source_name = str(ev.get("source_display_name") or "").strip()
    if source_name:
        signals.append(f"来源：{source_name}")

    signal_text = "，".join(signals)
    if signal_text:
        return f"{subject}，{signal_text}，建议纳入同一时间线持续跟踪。"
    return f"{subject}，建议纳入同一时间线持续跟踪。"


def _event_summary(ev: dict[str, Any]) -> str:
    summary = _event_public_summary(ev)
    if summary:
        return _first_sentence(summary, max_chars=96)
    for key in ("summary", "description", "content_translated", "content_original"):
        value = ev.get(key)
        if isinstance(value, str) and value.strip():
            return _first_sentence(value, max_chars=96)
    return ""


def _event_translation(ev: dict[str, Any]) -> dict[str, Any]:
    metadata = ev.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    translation = metadata.get("translation")
    return translation if isinstance(translation, dict) else {}


def _event_public_title(ev: dict[str, Any]) -> str:
    title = _event_translation(ev).get("title_pre")
    return " ".join(str(title or "").split())


def _event_public_summary(ev: dict[str, Any]) -> str:
    summary = _event_translation(ev).get("summary_pre")
    return " ".join(str(summary or "").split())


def _event_public_translation_ready(ev: dict[str, Any]) -> bool:
    metadata = ev.get("metadata")
    return public_translation_ready(metadata if isinstance(metadata, dict) else None)


def _event_explicit_recommendation_reason(ev: dict[str, Any]) -> str:
    metadata = ev.get("metadata")
    if isinstance(metadata, dict):
        raw_publication = metadata.get("publication")
        publication = raw_publication if isinstance(raw_publication, dict) else {}
        reason = publication.get("recommendation_reason")
        if isinstance(reason, str) and reason.strip():
            return _first_sentence(reason)
    return ""


def _public_news_has_featured_quality(ev: dict[str, Any]) -> bool:
    if not _event_summary(ev):
        return False
    if not _event_explicit_recommendation_reason(ev):
        return False
    classification = _event_classification(ev) or {}
    if canonical_l0(str(classification.get("l0") or "")) == "uncategorized":
        return False
    return True


_PUBLIC_NEWS_STAGE = "drafts"
_PUBLIC_NEWS_DEFAULT_PAGE_SIZE = 30
_PUBLIC_NEWS_MAX_PAGE_SIZE = 100
_PUBLIC_NEWS_MIN_SCAN = 80
_PUBLIC_NEWS_MAX_SCAN = 300
_PUBLIC_NEWS_MIN_POLL_AFTER_MS = 30_000
_PUBLIC_NEWS_DEFAULT_POLL_AFTER_MS = 60_000
_PUBLIC_NEWS_IDLE_POLL_AFTER_MS = 180_000
_PUBLIC_NEWS_FEATURED_SCORE = 60
_PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS = 15.0
_PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS = 30.0
_PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS = 5.0
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
_PUBLIC_TEXT_LATIN1_HINTS = ("Ã", "Â", "â€")
_STRAY_ACCENTED_CAPS = str.maketrans(
    {
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
)


def _public_news_feed_cache_ttl(*, q: str | None, since_cursor: str | None) -> float:
    if q:
        return _PUBLIC_NEWS_FEED_SEARCH_CACHE_TTL_SECONDS
    if since_cursor:
        return _PUBLIC_NEWS_FEED_UPDATE_CACHE_TTL_SECONDS
    return _PUBLIC_NEWS_FEED_CACHE_TTL_SECONDS


def _repair_utf8_mojibake(text: str) -> str:
    if not any(hint in text for hint in _PUBLIC_TEXT_LATIN1_HINTS):
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired.strip() or text


def _normalize_stray_accented_caps(text: str) -> str:
    chars = list(text)
    for index, char in enumerate(chars):
        lowered = char.translate(_STRAY_ACCENTED_CAPS)
        if lowered == char:
            continue
        previous = chars[index - 1] if index > 0 else ""
        if previous and previous.islower():
            chars[index] = lowered
    return "".join(chars)


def _normalize_public_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = _repair_utf8_mojibake(text)
    text = _normalize_stray_accented_caps(text)
    return text or None


def _public_news_feed_cache_key(
    *,
    featured: bool,
    target_id: str | None,
    source_id: str | None,
    category: str | None,
    date: str | None,
    q: str | None,
    before_cursor: str | None,
    since_cursor: str | None,
    page_size: int,
) -> str:
    material = {
        "before_cursor": before_cursor or "",
        "category": category or "",
        "date": date or "",
        "featured": bool(featured),
        "page_size": int(page_size),
        "q": q or "",
        "since_cursor": since_cursor or "",
        "source_id": source_id or "",
        "target_id": target_id or "",
    }
    return json.dumps(material, ensure_ascii=False, sort_keys=True)


def _public_news_cache_entry_valid(entry: dict[str, Any] | None, now: float) -> bool:
    return bool(
        entry and isinstance(entry.get("expires_at"), (int, float)) and entry["expires_at"] > now
    )


def _public_news_cache_headers(
    *,
    cache_status: Literal["hit", "miss", "bypass"],
    etag: str,
    poll_after_ms: int,
    elapsed_ms: int,
) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate",
        "X-Poll-After-Ms": str(poll_after_ms),
        "X-News-Sentry-Feed-Cache": cache_status,
        "X-News-Sentry-Feed-Elapsed-Ms": str(max(0, int(elapsed_ms))),
    }


def _public_news_log_slow_miss(
    *,
    elapsed_ms: int,
    target_count: int,
    candidate_count: int,
    filtered_count: int,
    item_count: int,
    featured: bool,
    has_target: bool,
    has_source: bool,
    has_category: bool,
    has_date: bool,
    has_q: bool,
    has_before: bool,
    has_since: bool,
    page_size: int,
) -> None:
    if elapsed_ms < _PUBLIC_NEWS_SLOW_LOG_MS:
        return
    logger.warning(
        "public news feed slow miss elapsed_ms=%s target_count=%s candidate_count=%s "
        "filtered_count=%s item_count=%s featured=%s has_target=%s has_source=%s "
        "has_category=%s has_date=%s has_q=%s has_before=%s has_since=%s page_size=%s",
        elapsed_ms,
        target_count,
        candidate_count,
        filtered_count,
        item_count,
        featured,
        has_target,
        has_source,
        has_category,
        has_date,
        has_q,
        has_before,
        has_since,
        page_size,
    )


def _public_news_event_datetime(ev: dict[str, Any]) -> datetime:
    parsed = _parse_published_at_utc(ev.get("published_at"))
    return parsed or datetime.min.replace(tzinfo=UTC)


def _public_news_sort_key(ev: dict[str, Any]) -> tuple[datetime, str]:
    event_id = str(ev.get("event_id") or ev.get("id") or "")
    return (_public_news_event_datetime(ev), event_id)


def _public_news_encode_cursor(ev: dict[str, Any]) -> str:
    published_at = _public_news_event_datetime(ev).isoformat()
    event_id = str(ev.get("event_id") or ev.get("id") or "")
    raw = f"{published_at}\0{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_news_decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}").decode("utf-8")
        published_at, event_id = raw.split("\0", 1)
        parsed = datetime.fromisoformat(published_at)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC), event_id


def _public_news_store_cursor_key(key: tuple[datetime, str] | None) -> tuple[str, str] | None:
    if key is None:
        return None
    published_at, event_id = key
    return published_at.astimezone(UTC).isoformat(), event_id


def _is_public_target_id(value: str) -> bool:
    target_id = value.strip()
    if not target_id or target_id.startswith((".", "_")):
        return False
    normalized = target_id.lower()
    if normalized in _PUBLIC_NEWS_INTERNAL_DATA_DIRS:
        return False
    return not (normalized == "example-target" or normalized.startswith("example-"))


def _looks_like_public_target_data_dir(path: Path) -> bool:
    if not path.is_dir() or not _is_public_target_id(path.name):
        return False
    if (path / "state.db").is_file():
        return True
    return any((path / name).is_dir() for name in _PUBLIC_NEWS_EVENT_DIRS)


def _public_news_target_ids(data_dir: Path, target_id: str | None) -> list[str]:
    if target_id:
        return [target_id]
    ids: set[str] = set()
    for config in _load_target_configs():
        value = config.get("target_id")
        if isinstance(value, str) and _is_public_target_id(value):
            ids.add(value.strip())
    if data_dir.is_dir():
        for child in data_dir.iterdir():
            if _looks_like_public_target_data_dir(child):
                ids.add(child.name)
    return sorted(ids)


def _public_source_type(
    value: Any,
) -> Literal["rss", "api", "web", "social", "official", "unknown"]:
    text = str(value or "").strip().lower()
    if text in {"rss", "api", "web", "social", "official"}:
        return cast(Literal["rss", "api", "web", "social", "official"], text)
    if text in {"opencli", "browser", "scraper"}:
        return "web"
    return "unknown"


def _credibility_label(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    score = float(value)
    if score <= 1:
        score *= 100
    if score >= 80:
        return "高"
    if score >= 50:
        return "中"
    return "低"


def _public_source_info(target_id: str, source_id: str, ev: dict[str, Any]) -> PublicNewsSource:
    for source in _cached_public_source_configs(target_id):
        candidates = {
            str(source.get(key) or "")
            for key in ("source_id", "id", "_source_id", "_source_ref", "source_ref")
        }
        if source_id and source_id in candidates:
            display_name = source.get("display_name") or source.get("name") or source_id
            return PublicNewsSource(
                id=source_id,
                name=str(display_name),
                type=_public_source_type(source.get("type")),
                credibilityLabel=_credibility_label(source.get("credibility_base")),
            )
    return PublicNewsSource(
        id=source_id,
        name=str(ev.get("source_display_name") or source_id or "未知来源"),
        type=_public_source_type(ev.get("source_type")),
        credibilityLabel=_credibility_label(ev.get("source_credibility")),
    )


def _public_news_entities(ev: dict[str, Any]) -> list[PublicNewsEntity]:
    raw = ev.get("nlp_entities") or ev.get("entities") or []
    entities: list[PublicNewsEntity] = []
    if not isinstance(raw, list):
        return entities
    for item in raw[:8]:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            entity_type = item.get("type") or item.get("entity_type")
            if name:
                entities.append(
                    PublicNewsEntity(
                        name=name,
                        type=str(entity_type) if entity_type else None,
                    )
                )
        elif item is not None and str(item).strip():
            entities.append(PublicNewsEntity(name=str(item).strip()))
    return entities


def _public_value_label(score: int | float | None) -> Literal["精选", "关注", "普通", "待评估"]:
    if score is None:
        return "待评估"
    if score >= 80:
        return "精选"
    if score >= 60:
        return "关注"
    return "普通"


def _public_china_relevance_label(value: Any) -> Literal["高", "中", "低", "未知"]:
    if not isinstance(value, (int, float)):
        return "未知"
    if value >= 70:
        return "高"
    if value >= 30:
        return "中"
    return "低"


def _event_article_payload(ev: dict[str, Any]) -> dict[str, Any]:
    metadata = ev.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    article = metadata.get("article")
    return article if isinstance(article, dict) else {}


def _event_full_content(ev: dict[str, Any]) -> str:
    article = _event_article_payload(ev)
    for value in (
        article.get("full_text"),
        ev.get("content_translated"),
        ev.get("content_original"),
    ):
        text = " ".join(str(value or "").split())
        if text:
            return text[:50_000]
    return ""


def _event_image_urls(ev: dict[str, Any]) -> list[str]:
    article = _event_article_payload(ev)
    urls: list[str] = []
    raw_urls = article.get("image_urls")
    if isinstance(raw_urls, list):
        urls.extend(str(url) for url in raw_urls if str(url or "").strip())
    lead = str(article.get("lead_image_url") or "").strip()
    if lead:
        urls.insert(0, lead)
    deduped: list[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped[:8]


def _public_news_item(
    target_id: str,
    ev: dict[str, Any],
    *,
    include_content: bool = False,
) -> PublicNewsItem:
    payload = _feed_event_payload(ev)
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    score = _event_score(payload)
    original_url = str(payload.get("url") or "").strip() or None
    recommendation_reason = str(payload.get("ai_reason") or "").strip()
    public_title = _event_public_title(payload) or str(payload.get("display_title") or event_id)
    return PublicNewsItem(
        id=event_id,
        targetId=target_id,
        targetLabel=_target_display_name(target_id),
        source=_public_source_info(target_id, str(payload.get("source_id") or ""), payload),
        publishedAt=str(payload.get("published_at") or ""),
        title=public_title,
        originalTitle=str(payload.get("original_title") or "") or None,
        summary=str(payload.get("summary") or "") or None,
        recommendationReason=recommendation_reason or None,
        fullContent=_event_full_content(payload) if include_content else None,
        imageUrls=_event_image_urls(payload) if include_content else [],
        originalUrl=original_url,
        detailUrl=(
            f"/public-app/events/{quote(event_id, safe='')}?target_id={quote(target_id, safe='')}"
        ),
        tags=list(payload.get("flat_tags") or []),
        entities=_public_news_entities(payload),
        relatedCount=int(payload.get("related_count") or 0),
        discussionCount=int(payload["discussion_count"])
        if isinstance(payload.get("discussion_count"), int)
        else None,
        valueLabel=_public_value_label(score),
        valueScore=score,
        chinaRelevanceLabel=_public_china_relevance_label(payload.get("china_relevance")),
    )


def _public_news_matches(
    ev: dict[str, Any],
    *,
    featured: bool,
    source_id: str | None,
    category: str | None,
    date: str | None,
    q: str | None,
) -> bool:
    if not _event_public_translation_ready(ev):
        return False
    if featured and (_event_score(ev) or 0) < _PUBLIC_NEWS_FEATURED_SCORE:
        return False
    if featured and not _public_news_has_featured_quality(ev):
        return False
    if source_id and ev.get("source_id") != source_id:
        return False
    if category:
        normalized_category = canonical_l0(category)
        classification = _event_classification(ev) or {}
        if canonical_l0(str(classification.get("l0") or "")) != normalized_category:
            return False
    if date and not str(ev.get("published_at") or "").startswith(date):
        return False
    if q:
        keyword = q.lower()
        haystack = " ".join(
            value
            for value in (
                _event_public_title(ev),
                _event_public_summary(ev),
                str(ev.get("source_id") or ""),
                str(ev.get("source_display_name") or ""),
                " ".join(_event_flat_tags(ev)),
            )
            if value
        ).lower()
        if keyword not in haystack:
            return False
    return True


def _public_projection_text(value: Any) -> str | None:
    return _normalize_public_text(value)


def _public_projection_event(row: dict[str, Any]) -> dict[str, Any]:
    """把 public projection row 补齐到 PublicNewsItem 所需的最小展示事件形状。"""
    event = _event_from_index_row(row)
    raw_metadata = row.get("metadata")
    metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
    raw_translation = metadata.get("translation")
    translation = cast(dict[str, Any], raw_translation) if isinstance(raw_translation, dict) else {}
    raw_publication = metadata.get("publication")
    publication = cast(dict[str, Any], raw_publication) if isinstance(raw_publication, dict) else {}
    raw_source_meta = metadata.get("source")
    source_meta = cast(dict[str, Any], raw_source_meta) if isinstance(raw_source_meta, dict) else {}

    if translated_title := _public_projection_text(translation.get("title_pre")):
        event["title_translated"] = translated_title

    if summary := _public_projection_text(translation.get("summary_pre")):
        event["summary"] = summary
        event.setdefault("description", summary)
        event.setdefault("content_translated", summary)

    article = metadata.get("article")
    if isinstance(article, dict):
        if full_text := _public_projection_text(article.get("full_text")):
            event["content_original"] = full_text

    recommendation_reason = _public_projection_text(publication.get("recommendation_reason"))
    if recommendation_reason:
        event["judge_result"] = {"rationale": recommendation_reason}

    if source_display_name := _public_projection_text(
        metadata.get("source_display_name")
        or source_meta.get("display_name")
        or source_meta.get("name")
    ):
        event["source_display_name"] = source_display_name
    if source_type := _public_projection_text(
        metadata.get("source_type") or source_meta.get("type")
    ):
        event["source_type"] = source_type
    source_credibility = metadata.get(
        "source_credibility",
        source_meta.get("credibility_base"),
    )
    if source_credibility:
        event["source_credibility"] = source_credibility

    topic_tags = metadata.get("topic_tags")
    if isinstance(topic_tags, list):
        event["topic_tags"] = topic_tags

    entities = metadata.get("nlp_entities")
    if not isinstance(entities, list):
        entities = metadata.get("entities")
    if isinstance(entities, list):
        event["nlp_entities"] = entities

    if isinstance(metadata.get("related_count"), int):
        event["related_count"] = metadata["related_count"]
    if isinstance(metadata.get("discussion_count"), int):
        event["discussion_count"] = metadata["discussion_count"]

    return event


async def _query_public_projection_events(
    store: Any,
    *,
    target_id: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]] | None:
    query_rows = getattr(store, "query_public_projection_rows", None)
    if query_rows is None:
        return None
    rows = await query_rows(target_id=target_id, limit=limit, offset=offset)
    if not isinstance(rows, list):
        return []
    return [
        _public_projection_event(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("event_id") or row.get("id") or "").strip()
        and public_translation_ready(
            row.get("metadata") if isinstance(row.get("metadata"), dict) else None
        )
    ]


async def _find_public_projection_event(
    store: Any,
    *,
    target_id: str,
    event_id: str,
    batch_size: int = 200,
) -> dict[str, Any] | None:
    offset = 0
    while True:
        events = await _query_public_projection_events(
            store,
            target_id=target_id,
            limit=batch_size,
            offset=offset,
        )
        if events is None or not events:
            return None
        for event in events:
            if str(event.get("event_id") or event.get("id") or "") == event_id:
                return event
        if len(events) < batch_size:
            return None
        offset += len(events)


async def _load_public_projection_detail(
    store: Any,
    *,
    target_id: str,
    event_id: str,
) -> dict[str, Any] | InvisibleIndexedEvent | None:
    get_row = getattr(store, "get_event_index_row", None)
    if get_row is not None:
        row = await get_row(target_id, event_id)
        if row is None:
            return None
        if row.get("stage") != _PUBLIC_NEWS_STAGE:
            return _INVISIBLE_INDEXED_EVENT
        if not public_translation_ready(
            row.get("metadata") if isinstance(row.get("metadata"), dict) else None
        ):
            return _INVISIBLE_INDEXED_EVENT
        return _public_projection_event(row)
    return await _find_public_projection_event(store, target_id=target_id, event_id=event_id)


async def _public_news_events_for_target(
    data_dir: Path,
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
    allow_projection_first: bool = True,
    min_score: int | None = None,
    source_id: str | None = None,
    classification_l0: str | None = None,
    date: str | None = None,
    q: str | None = None,
    before_key: tuple[datetime, str] | None = None,
    since_key: tuple[datetime, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if (
        allow_projection_first
        and store is not None
        and min_score is None
        and source_id is None
        and classification_l0 is None
        and date is None
        and q is None
        and before_key is None
        and since_key is None
    ):
        projection_events = await _query_public_projection_events(
            store,
            target_id=target_id,
            limit=limit,
        )
        if projection_events:
            return projection_events, len(projection_events)
    if store is not None and await _store_has_target_event_index(store, target_id):
        query_public_rows = getattr(store, "query_public_news_rows", None)
        if query_public_rows is not None:
            result = await query_public_rows(
                target_id=target_id,
                stage=_PUBLIC_NEWS_STAGE,
                limit=limit,
                source_id=source_id,
                classification_l0=classification_l0,
                min_score=min_score,
                date=date,
                search=q,
                before_key=_public_news_store_cursor_key(before_key),
                since_key=_public_news_store_cursor_key(since_key),
            )
            rows = result.get("rows", [])
            if isinstance(rows, list):
                events = [
                    _merge_index_metadata(_event_from_index_row(row), row)
                    for row in cast(list[dict[str, Any]], rows)
                    if public_translation_ready(
                        row.get("metadata") if isinstance(row.get("metadata"), dict) else None
                    )
                ]
                return events, int(result.get("total") or len(events))
            return [], 0

        result = await _visible_index_events_page(
            store,
            data_dir,
            target_id,
            stage=_PUBLIC_NEWS_STAGE,
            page=1,
            page_size=limit,
            date=date,
            search=q,
            source_id=source_id,
            classification_l0=classification_l0,
            min_score=min_score,
            exact_total=False,
        )
        events = result.get("events", [])
        if isinstance(events, list):
            ready_events = [event for event in events if _event_public_translation_ready(event)]
            total = min(int(result.get("total") or len(ready_events)), len(ready_events))
            return ready_events, total
        return [], 0
    events = _load_all_events(data_dir, target_id)
    ready_events = [event for event in events if _event_public_translation_ready(event)]
    return ready_events, len(ready_events)


async def _public_news_candidate_events(
    data_dir: Path,
    target_ids: list[str],
    *,
    limit: int,
    allow_projection_first: bool = True,
    featured: bool,
    source_id: str | None = None,
    category: str | None = None,
    date: str | None = None,
    q: str | None = None,
    before_key: tuple[datetime, str] | None = None,
    since_key: tuple[datetime, str] | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    total = 0
    min_score = _PUBLIC_NEWS_FEATURED_SCORE if featured else None
    classification_l0 = category if category else None
    for target_id in target_ids:
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store
        events, target_total = await _public_news_events_for_target(
            data_dir,
            target_id,
            store_to_query,
            limit=limit,
            allow_projection_first=allow_projection_first,
            min_score=min_score,
            source_id=source_id,
            classification_l0=classification_l0,
            date=date,
            q=q,
            before_key=before_key,
            since_key=since_key,
        )
        total += target_total
        for event in events:
            candidates.append((target_id, event))
    candidates.sort(key=lambda item: _public_news_sort_key(item[1]), reverse=True)
    return candidates, total


def _public_news_etag(items: list[PublicNewsItem], latest_cursor: str | None) -> str:
    material = json.dumps(
        {
            "latest": latest_cursor,
            "ids": [item.id for item in items],
            "updated": [item.published_at for item in items],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f'"public-news-{sha256(material.encode("utf-8")).hexdigest()[:16]}"'


def _feed_event_payload(ev: dict[str, Any]) -> dict[str, Any]:
    """为新闻流补充展示字段；不改变 NewsEvent 存储契约。"""
    event_id = ev.get("event_id") or ev.get("id") or ""
    source_id = ev.get("source_id") or ""
    raw_judge = ev.get("judge_result")
    judge: dict[str, Any] = raw_judge if isinstance(raw_judge, dict) else {}
    raw_metadata = ev.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_clustering = metadata.get("clustering")
    clustering: dict[str, Any] = raw_clustering if isinstance(raw_clustering, dict) else {}
    classification = _event_classification(ev) or {}
    title_pre = _event_public_title(ev)
    original_title = _normalize_public_text(ev.get("title_original") or event_id) or event_id
    display_title = _normalize_public_text(ev.get("title_translated")) or original_title or event_id
    payload = dict(ev)
    payload["event_id"] = event_id
    payload["display_title"] = display_title
    payload["original_title"] = original_title
    payload["title_pre"] = title_pre
    payload["has_translated_display_title"] = bool(title_pre and title_pre != original_title)
    payload["score"] = _event_score(ev)
    payload["source_display_name"] = ev.get("source_display_name") or source_id
    payload["flat_tags"] = _event_flat_tags(ev)
    payload["cluster_id"] = ev.get("cluster_id")
    payload["story_id"] = ev.get("story_id")
    payload["clustering"] = clustering
    payload["classification"] = classification
    payload["ai_reason"] = _event_ai_reason(ev)
    payload["summary"] = _event_summary(ev)
    payload["recommendation"] = ev.get("recommendation") or judge.get("recommendation")
    payload["related_count"] = ev.get("related_count") or 0
    return payload


def _avg_or_none(values: list[int | float]) -> float | None:
    """计算公开快照均值，空集合返回 None。"""
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _distribution_items(
    counts: dict[str, int],
    *,
    limit: int = 10,
) -> list[PublicDistributionItem]:
    """按 count 降序、key 升序输出公开分布。"""
    pairs = [(str(name), int(count)) for name, count in counts.items() if name and count > 0]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return [PublicDistributionItem(name=name, count=count) for name, count in pairs[:limit]]


def _source_distribution_items(
    counts: dict[str, int],
    *,
    limit: int = 10,
) -> list[PublicSourceDistributionItem]:
    """输出公开信源分布，display_name 默认使用 source_id。"""
    pairs = [
        (str(source_id), int(count))
        for source_id, count in counts.items()
        if source_id and count > 0
    ]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return [
        PublicSourceDistributionItem(source_id=source_id, display_name=source_id, count=count)
        for source_id, count in pairs[:limit]
    ]


def _public_summary_from_events(events: list[dict[str, Any]]) -> PublicAnalysisSummary:
    """从 draft frontmatter 聚合公开摘要。"""
    scores = [score for ev in events if (score := _event_score(ev)) is not None]
    relevances = [
        relevance
        for ev in events
        if isinstance((relevance := ev.get("china_relevance")), (int, float))
    ]
    return PublicAnalysisSummary(
        total_events=len(events),
        high_value_events=sum(1 for score in scores if score >= 70),
        avg_news_value_score=_avg_or_none(scores),
        avg_china_relevance=_avg_or_none(relevances),
    )


def _public_distributions_from_events(
    events: list[dict[str, Any]],
) -> tuple[list[PublicDistributionItem], list[PublicSourceDistributionItem]]:
    """从 draft frontmatter 聚合公开分类和信源分布。"""
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for ev in events:
        classification = _event_classification(ev)
        if classification:
            l0 = classification.get("l0")
            if l0:
                by_classification[str(l0)] += 1
        source_id = ev.get("source_id")
        if source_id:
            by_source[str(source_id)] += 1
    return _distribution_items(by_classification), _source_distribution_items(by_source)


def _parse_published_at_utc(value: Any) -> datetime | None:
    """解析事件发布时间；缺失或不可解析时返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _public_events_within_window(
    events: list[dict[str, Any]],
    days: int,
) -> list[dict[str, Any]]:
    """过滤公开分析时间窗口；无时间戳草稿保留以兼容旧数据。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for event in events:
        published_at = event.get("published_at")
        if not published_at:
            filtered.append(event)
            continue
        parsed = _parse_published_at_utc(published_at)
        if parsed is None or parsed >= cutoff:
            filtered.append(event)
    return filtered


def _target_display_name(target_id: str) -> str:
    """读取公开 target 名称，缺失时回退到 target_id。"""
    for config in _load_target_configs():
        if config.get("target_id") == target_id:
            display_name = config.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name
            return target_id
    return target_id


_PUBLIC_ANALYSIS_STAGE = "drafts"
_PUBLIC_ANALYSIS_CHAIN_LIMIT = 10


def _split_store_list(value: Any) -> list[str]:
    """拆分 store 中逗号分隔的 NLP 字段。"""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _store_day(value: Any) -> str:
    """从 ISO 日期字符串取 YYYY-MM-DD。"""
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


async def _public_event_rows_from_store(
    target_id: str,
    days: int,
    store: AsyncStore,
) -> list[dict[str, Any]]:
    """读取公开新闻流可见事件索引；仅 drafts stage 对匿名端可见。"""
    if store._db is None:  # noqa: SLF001
        return []
    async with store._db.execute(  # noqa: SLF001
        "SELECT event_id, source_id, news_value_score, china_relevance, "
        "classification_l0, published_at, sentiment, entity_names, topic_tags "
        "FROM event_index "
        "WHERE target_id = ? AND stage = ? "
        "AND (published_at IS NULL OR published_at = '' "
        "OR published_at >= date('now', ? || ' days')) "
        "ORDER BY published_at DESC",
        [target_id, _PUBLIC_ANALYSIS_STAGE, f"-{days}"],
    ) as cursor:
        rows = await cursor.fetchall()
    cols = (
        "event_id",
        "source_id",
        "news_value_score",
        "china_relevance",
        "classification_l0",
        "published_at",
        "sentiment",
        "entity_names",
        "topic_tags",
    )
    return [dict(zip(cols, row, strict=True)) for row in rows]


async def _public_active_chains_from_store(
    target_id: str,
    store: AsyncStore,
    *,
    limit: int = _PUBLIC_ANALYSIS_CHAIN_LIMIT,
) -> list[PublicChainItem]:
    """读取公开追踪链摘要，并在 root 查询阶段硬性限量。"""
    if store._db is None:  # noqa: SLF001
        return []

    async with store._db.execute(  # noqa: SLF001
        "SELECT DISTINCT el.source_event_id, source.published_at "
        "FROM event_links el "
        "JOIN event_index source ON source.event_id = el.source_event_id "
        "WHERE el.target_id = ? AND source.target_id = ? AND source.stage = ? "
        "ORDER BY source.published_at DESC LIMIT ?",
        [target_id, target_id, _PUBLIC_ANALYSIS_STAGE, limit],
    ) as cursor:
        root_rows = await cursor.fetchall()
    root_ids = [str(row[0]) for row in root_rows if row[0]]
    if not root_ids:
        return []

    placeholders = ",".join("?" for _ in root_ids)
    narrative_map: dict[str, str] = {}
    async with store._db.execute(  # noqa: SLF001
        f"SELECT chain_root_id, narrative FROM chain_narratives "  # noqa: S608
        f"WHERE chain_root_id IN ({placeholders})",
        root_ids,
    ) as cursor:
        async for row in cursor:
            narrative_map[str(row[0])] = str(row[1] or "")

    chains: list[PublicChainItem] = []
    for root_id in root_ids:
        async with store._db.execute(  # noqa: SLF001
            "SELECT DISTINCT ei.event_id, ei.title_original, ei.published_at "
            "FROM event_index ei "
            "WHERE ei.target_id = ? AND ei.stage = ? "
            "AND (ei.event_id = ? "
            "OR ei.event_id IN ("
            "SELECT target_event_id FROM event_links "
            "WHERE target_id = ? AND source_event_id = ?"
            ") "
            "OR ei.event_id IN ("
            "SELECT source_event_id FROM event_links "
            "WHERE target_id = ? AND target_event_id = ?"
            ")) "
            "ORDER BY ei.published_at ASC",
            [
                target_id,
                _PUBLIC_ANALYSIS_STAGE,
                root_id,
                target_id,
                root_id,
                target_id,
                root_id,
            ],
        ) as cursor:
            chain_rows = list(await cursor.fetchall())
        if len(chain_rows) < 2:
            continue
        latest = chain_rows[-1]
        narrative = narrative_map.get(root_id, "")
        chains.append(
            PublicChainItem(
                root_event_id=root_id,
                event_count=len(chain_rows),
                latest_time=str(latest[2] or ""),
                latest_title=str(latest[1] or ""),
                narrative_summary=narrative[:50] + "..." if len(narrative) > 50 else narrative,
            )
        )
    chains.sort(key=lambda chain: chain.latest_time, reverse=True)
    return chains[:limit]


async def _public_analysis_from_store(
    target_id: str,
    days: int,
    store: AsyncStore,
) -> PublicAnalysisResponse | None:
    """从 SQLite store 聚合公开分析快照；空 store 交给文件系统降级。"""
    public_rows = await _public_event_rows_from_store(target_id, days, store)
    total_events = len(public_rows)
    if total_events == 0:
        return None

    scores = [
        score
        for event in public_rows
        if isinstance((score := event.get("news_value_score")), (int, float))
    ]
    relevances = [
        relevance
        for event in public_rows
        if isinstance((relevance := event.get("china_relevance")), (int, float))
    ]
    by_classification: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    entity_counts: dict[str, int] = defaultdict(int)
    topic_counts: dict[str, int] = defaultdict(int)
    topic_daily: dict[tuple[str, str], int] = defaultdict(int)
    sentiment_by_day: dict[str, DailySentimentCount] = {}

    for event in public_rows:
        classification = event.get("classification_l0")
        if classification:
            by_classification[canonical_l0(str(classification))] += 1
        source_id = event.get("source_id")
        if source_id:
            by_source[str(source_id)] += 1

        for entity_name in _split_store_list(event.get("entity_names")):
            entity_counts[entity_name] += 1

        day = _store_day(event.get("published_at"))
        for topic in _split_store_list(event.get("topic_tags")):
            topic_counts[topic] += 1
            if day:
                topic_daily[(topic, day)] += 1

        sentiment = event.get("sentiment")
        if day and sentiment in {"positive", "negative", "neutral"}:
            sentiment_item = sentiment_by_day.setdefault(day, DailySentimentCount(day=day))
            if sentiment == "positive":
                sentiment_item.positive += 1
            elif sentiment == "negative":
                sentiment_item.negative += 1
            elif sentiment == "neutral":
                sentiment_item.neutral += 1

    topic_daily_counts = [
        {"topic": topic, "day": day, "count": count}
        for (topic, day), count in sorted(topic_daily.items())
    ]
    top_topics = [
        {"topic": topic, "count": count}
        for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]
    active_chains = await _public_active_chains_from_store(target_id, store)

    from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends

    topic_trends = [
        TopicTrendItem(**trend.model_dump())
        for trend in compute_topic_trends(topic_daily_counts, top_topics, total_days=days)
    ]

    summary = PublicAnalysisSummary(
        total_events=total_events,
        high_value_events=sum(1 for score in scores if score >= 70),
        avg_news_value_score=_avg_or_none(scores),
        avg_china_relevance=_avg_or_none(relevances),
    )

    return PublicAnalysisResponse(
        target_id=target_id,
        target_name=_target_display_name(target_id),
        days=days,
        summary=summary,
        classification_distribution=_distribution_items(by_classification),
        source_distribution=_source_distribution_items(by_source),
        top_entities=[
            PublicEntityItem(
                name=name,
                mention_count=count,
            )
            for name, count in sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))[
                :10
            ]
        ],
        topic_trends=topic_trends,
        sentiment_trend=sorted(sentiment_by_day.values(), key=lambda item: item.day),
        active_chains=active_chains,
        generated_at=datetime.now(UTC).isoformat(),
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


def _cached_public_source_configs(target_id: str) -> list[dict[str, Any]]:
    """Cache source YAML reads used by public feed item projection."""
    key = (str(Path.cwd()), target_id)
    now = time.monotonic()
    cached = _public_source_configs_cache.get(key)
    if (
        cached
        and now - float(cached.get("created_at", 0)) <= _PUBLIC_SOURCE_CONFIG_CACHE_TTL_SECONDS
    ):
        sources = cached.get("sources")
        if isinstance(sources, list):
            return cast(list[dict[str, Any]], sources)

    sources = _load_source_configs(target_id)
    _public_source_configs_cache[key] = {
        "created_at": now,
        "sources": sources,
    }
    return sources


def _file_signature(paths: list[Path]) -> str:
    """Return a cheap mtime/size signature for cache invalidation."""
    items: list[tuple[str, int, int]] = []
    for path in sorted(set(paths), key=lambda p: str(p)):
        try:
            stat = path.stat()
        except OSError:
            items.append((str(path), -1, -1))
            continue
        items.append((str(path), stat.st_mtime_ns, stat.st_size))
    return sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()


def _target_source_paths(target_id: str) -> list[Path]:
    sources_dir = Path("config/sources") / target_id
    if not sources_dir.is_dir():
        return []
    return [path for path in sources_dir.rglob("*.yaml") if not path.name.startswith("_")]


def _target_inventory_signature(target_id: str) -> str:
    paths = [
        _target_config_path(target_id),
        *_target_source_paths(target_id),
        _data_dir / target_id / "memory" / "source_health.yaml",
    ]
    return _file_signature(paths)


def _target_validation_signature(target_id: str) -> str:
    paths = [_target_config_path(target_id), *_target_source_paths(target_id)]
    data = _load_target_config(target_id)
    if isinstance(data, dict):
        for field in (
            "filter_rules_ref",
            "classification_rules_ref",
            "sandbox_profile_ref",
            "provider_routes_ref",
            "output_destinations_ref",
        ):
            ref = data.get(field)
            if ref:
                paths.append(Path(str(ref)))
    return _file_signature(paths)


def _cached_source_inventory(target_id: str) -> dict[str, Any]:
    signature = _target_inventory_signature(target_id)
    key = (str(Path.cwd()), str(_data_dir), target_id)
    now = time.monotonic()
    cached = _source_inventory_cache.get(key)
    if (
        cached
        and cached.get("signature") == signature
        and now - float(cached.get("created_at", 0)) <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = cached.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = SourceInventoryService(Path.cwd(), _data_dir).build_target_inventory(target_id)
    _source_inventory_cache[key] = {
        "signature": signature,
        "created_at": now,
        "value": value,
    }
    return value


def _cached_target_validation(target_id: str) -> dict[str, Any]:
    signature = _target_validation_signature(target_id)
    key = (str(Path.cwd()), str(_data_dir), target_id)
    now = time.monotonic()
    cached = _target_validation_cache.get(key)
    if (
        cached
        and cached.get("signature") == signature
        and now - float(cached.get("created_at", 0)) <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = cached.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = _validate_target_config(target_id)
    _target_validation_cache[key] = {
        "signature": signature,
        "created_at": now,
        "value": value,
    }
    return value


def _source_ids_for_target(target_id: str) -> set[str]:
    """返回 target 当前启用的信源 ID，用于后台健康状态过滤。"""
    ids: set[str] = set()
    for source in _load_source_configs(target_id):
        raw_lifecycle = source.get("lifecycle")
        lifecycle: dict[str, Any] = raw_lifecycle if isinstance(raw_lifecycle, dict) else {}
        if source.get("enabled", True) is False:
            continue
        if source.get("deprecated") is True:
            continue
        if lifecycle.get("status") == "archived":
            continue
        for key in ("source_id", "id", "_source_id"):
            value = source.get(key)
            if value:
                normalized = str(value).strip()
                ids.add(normalized)
                ids.add(Path(normalized).name)
    return ids


def _filter_source_health_records(
    target_id: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按当前 target 的信源配置过滤健康记录；无配置时保留原结果。"""
    source_ids = _source_ids_for_target(target_id)
    if not source_ids:
        return records
    filtered: list[dict[str, Any]] = []
    for record in records:
        source_id = str(record.get("source_id", "")).strip()
        if source_id in source_ids or Path(source_id).name in source_ids:
            filtered.append(record)
    return filtered


def _source_health_status_from_memory(entry: dict[str, Any]) -> str:
    """把 Memory source_health.yaml 形状归一为 API 状态。"""
    failures = int(entry.get("consecutive_failures") or 0)
    total_runs = int(entry.get("total_runs") or 0)
    total_failures = int(entry.get("total_failures") or 0)
    if failures >= 10:
        return "dead"
    if failures >= 3:
        return "degraded"
    if total_runs > 0 and total_failures >= total_runs:
        return "degraded"
    return "healthy"


def _source_health_error_count_from_memory(entry: dict[str, Any]) -> int:
    """优先使用连续失败数；没有时退回总失败数。"""
    return int(entry.get("consecutive_failures") or entry.get("total_failures") or 0)


def _load_memory_source_health_records(target_id: str | None = None) -> list[dict[str, Any]]:
    """读取真实采集写入的 memory/source_health.yaml 并转成 API 响应形状。"""
    target_ids: list[str]
    if target_id:
        target_ids = [target_id]
    elif _data_dir.exists():
        target_ids = sorted(d.name for d in _data_dir.iterdir() if d.is_dir())
    else:
        target_ids = []

    records: list[dict[str, Any]] = []
    for tid in target_ids:
        path = _data_dir / tid / "memory" / "source_health.yaml"
        if not path.is_file():
            continue
        data = _load_yaml_file(path)
        if not isinstance(data, dict):
            continue
        for source_id, entry in data.items():
            if not isinstance(entry, dict):
                continue
            records.append(
                {
                    "source_id": str(source_id),
                    "status": _source_health_status_from_memory(entry),
                    "last_check": entry.get("last_success_at")
                    or entry.get("last_failure_at")
                    or "",
                    "error_count": _source_health_error_count_from_memory(entry),
                    "last_error": entry.get("last_error"),
                    "last_success_at": entry.get("last_success_at"),
                    "last_failure_at": entry.get("last_failure_at"),
                    "metadata": {
                        "target_id": tid,
                        "last_success_at": entry.get("last_success_at"),
                        "last_failure_at": entry.get("last_failure_at"),
                        "last_error": entry.get("last_error"),
                        "total_runs": entry.get("total_runs", 0),
                        "total_failures": entry.get("total_failures", 0),
                        "consecutive_failures": entry.get("consecutive_failures", 0),
                    },
                }
            )
    return records


def _load_single_source(target_id: str, source_id: str) -> dict[str, Any] | None:
    """读取单个源渠道配置。"""
    source_path = _source_config_path(target_id, source_id)
    if not source_path.parent.exists():
        return None
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


_TARGET_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SOURCE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _target_config_path(target_id: str) -> Path:
    _validate_target_slug(target_id)
    return Path("config/targets") / f"{target_id}.yaml"


def _source_config_path(target_id: str, source_ref: str) -> Path:
    _validate_target_slug(target_id)
    safe_ref = _normalize_source_ref(source_ref)
    return Path("config/sources") / target_id / f"{safe_ref}.yaml"


def _normalize_source_ref(source_ref: str) -> str:
    """规范化 config/sources/{target}/ 下的相对引用。"""
    ref = str(source_ref or "").replace("\\", "/").strip("/")
    if not ref or ref.startswith(".") or "/../" in f"/{ref}/" or Path(ref).is_absolute():
        raise HTTPException(status_code=400, detail="Invalid source ref")
    if any(not part or part.startswith(".") for part in ref.split("/")):
        raise HTTPException(status_code=400, detail="Invalid source ref")
    return ref


def _validate_target_slug(target_id: str) -> None:
    if not _TARGET_SLUG_RE.match(target_id):
        raise HTTPException(status_code=400, detail="Invalid target_id")


def _validate_source_slug(source_id: str) -> None:
    if not _SOURCE_SLUG_RE.match(source_id):
        raise HTTPException(status_code=400, detail="Invalid source_id")


def _load_target_config(target_id: str) -> dict[str, Any] | None:
    return _load_yaml_file(_target_config_path(target_id))


def _target_lifecycle(data: dict[str, Any]) -> dict[str, Any]:
    lifecycle = data.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return {"status": "active"}
    status = lifecycle.get("status") or "active"
    return {**lifecycle, "status": status}


def _target_is_archived(data: dict[str, Any]) -> bool:
    return _target_lifecycle(data).get("status") == "archived"


_TARGET_MONITORING_LABELS = {
    "country": "国别监控目标",
    "topic": "专题监控目标",
}


def _target_monitoring_type(data: dict[str, Any]) -> str:
    raw = data.get("monitoring_type") or data.get("target_type")
    aliases = {
        "country": "country",
        "country-target": "country",
        "country_monitoring": "country",
        "nation": "country",
        "topic": "topic",
        "topic-target": "topic",
        "theme": "topic",
        "subject": "topic",
        "special-topic": "topic",
    }
    if isinstance(raw, str):
        normalized = raw.strip().lower().replace("_", "-")
        if normalized in aliases:
            return aliases[normalized]
    target_id = str(data.get("target_id") or "").strip().lower()
    if (
        target_id == "china-watch-en"
        or target_id.startswith("china-watch")
        or data.get("topic_label")
    ):
        return "topic"
    return "country"


def _target_topic_label(data: dict[str, Any]) -> str | None:
    for key in ("topic_label", "monitoring_topic", "topic_name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    target_id = str(data.get("target_id") or "").strip().lower()
    if target_id == "china-watch-en":
        return "涉中舆情"
    return None


def _target_info_from_config(data: dict[str, Any], data_dir: Path) -> TargetInfo:
    target_id = data.get("target_id", "")
    lifecycle = _target_lifecycle(data)
    monitoring_type = _target_monitoring_type(data)
    refs = [ref for ref in data.get("source_channel_refs", []) if isinstance(ref, str)]
    return TargetInfo(
        target_id=target_id,
        display_name=data.get("display_name", ""),
        primary_language=data.get("language_scope", {}).get("primary", "")
        if isinstance(data.get("language_scope"), dict)
        else "",
        monitoring_type=monitoring_type,
        monitoring_label=_TARGET_MONITORING_LABELS.get(monitoring_type, "监控目标"),
        topic_label=_target_topic_label(data),
        source_count=len(refs),
        event_count=0,
        lifecycle=lifecycle,
        archived=lifecycle.get("status") == "archived",
    )


async def _target_public_event_count(target_id: str, data_dir: Path) -> int:
    """Return the count the public feed can actually show for a target."""
    try:
        store = await _store_for_target(target_id)
        if store is not None and await _store_has_target_event_index(store, target_id):
            get_count = getattr(store, "get_public_event_count", None)
            if get_count is not None:
                return int(await get_count(target_id, _PUBLIC_ANALYSIS_STAGE))
            visible = await _visible_index_events_page(
                store,
                data_dir,
                target_id,
                stage=_PUBLIC_ANALYSIS_STAGE,
                page=1,
                page_size=1,
                exact_total=False,
            )
            events = visible.get("events") if isinstance(visible, dict) else []
            if isinstance(events, list):
                return len([event for event in events if _event_public_translation_ready(event)])
            return 0
    except Exception:
        logger.exception("Failed to count indexed public events for target %s", target_id)
    return len(
        [
            event
            for event in _load_all_events(data_dir, target_id)
            if _event_public_translation_ready(event)
        ]
    )


async def _target_api_event_count(target_id: str) -> int:
    """Return all indexed API events for a target, regardless of public stage."""
    try:
        store = await _store_for_target(target_id)
        if store is None:
            return 0
        get_count = getattr(store, "get_target_event_count", None)
        if get_count is None:
            return 0
        return int(await get_count(target_id) or 0)
    except Exception:
        logger.exception("Failed to count indexed API events for target %s", target_id)
        return 0


async def _target_info_from_config_for_response(
    data: dict[str, Any],
    data_dir: Path,
) -> TargetInfo:
    info = _target_info_from_config(data, data_dir)
    if not info.target_id:
        return info
    event_count = await _target_public_event_count(info.target_id, data_dir)
    return info.model_copy(update={"event_count": event_count})


def _source_is_standard(source: dict[str, Any]) -> bool:
    return source.get("type") in {"rss", "api", "opencli"}


def _source_is_archived(source: dict[str, Any]) -> bool:
    return (
        bool(source.get("deprecated"))
        or source.get("enabled") is False
        and bool(source.get("deprecated_reason"))
    )


def _source_info_from_config(source: dict[str, Any]) -> SourceInfo:
    url_val = source.get("url")
    if url_val is None:
        endpoint = source.get("endpoint")
        if isinstance(endpoint, dict):
            url_val = endpoint.get("url")
    health = source.get("health")
    health_last = None
    health_failures = None
    if isinstance(health, dict):
        health_last = health.get("last_success_at")
        health_failures = health.get("consecutive_failures")
    source_ref_raw = source.get("_source_id") or source.get("source_ref") or source.get("source_id")
    source_ref = str(source_ref_raw) if source_ref_raw is not None else None
    source_id = str(source.get("source_id") or source_ref or "")
    health_failures_int = int(health_failures) if health_failures is not None else None
    return SourceInfo(
        source_id=source_id,
        source_ref=source_ref,
        display_name=str(source.get("display_name") or ""),
        type=str(source.get("type") or "unknown"),
        enabled=bool(source.get("enabled", True)),
        archived=_source_is_archived(source),
        deprecated=bool(source.get("deprecated", False)),
        deprecated_reason=source.get("deprecated_reason"),
        credibility_base=source.get("credibility_base"),
        health_last_success=str(health_last) if health_last is not None else None,
        health_consecutive_failures=health_failures_int,
        url=str(url_val) if url_val is not None else None,
    )


def _ensure_target_exists(target_id: str) -> dict[str, Any]:
    data = _load_target_config(target_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Target '{target_id}' not found")
    return data


def _append_source_ref(target_id: str, source_ref: str) -> None:
    data = _ensure_target_exists(target_id)
    refs = data.get("source_channel_refs")
    if not isinstance(refs, list):
        refs = []
    if source_ref not in refs:
        refs.append(source_ref)
    data["source_channel_refs"] = refs
    _atomic_write_yaml(_target_config_path(target_id), data)


def _default_filter_config(target_id: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "score_threshold": 35,
        "max_age_hours": 72,
        "dedup_window_hours": 24,
        "keyword_rules": [],
    }


def _default_classification_config(target_id: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "axes": [
            {"id": "policy", "label": "政策"},
            {"id": "industry", "label": "产业"},
            {"id": "technology", "label": "技术"},
            {"id": "risk", "label": "风险"},
        ],
    }


def _ensure_global_config_defaults() -> None:
    if not Path("config/sandbox/default.yaml").is_file():
        _atomic_write_yaml(Path("config/sandbox/default.yaml"), {"profile": "default"})
    if not Path("config/provider/routes.yaml").is_file():
        _atomic_write_yaml(
            Path("config/provider/routes.yaml"),
            {"routes_version": "1", "routes": []},
        )
    if not Path("config/output/destinations.yaml").is_file():
        _atomic_write_yaml(Path("config/output/destinations.yaml"), {"destinations": []})


def _template_target_config(
    *,
    target_id: str,
    display_name: str,
    language_scope: dict[str, Any],
    timezone: str,
    monitoring_type: str | None = None,
    topic_label: str | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = source_refs if source_refs is not None else ["rss-template"]
    data = {
        "target_id": target_id,
        "display_name": display_name,
        "monitoring_type": monitoring_type or "country",
        "language_scope": language_scope,
        "timezone": timezone,
        "source_channel_refs": refs,
        "filter_rules_ref": f"config/filters/{target_id}/default.yaml",
        "classification_rules_ref": f"config/classification/rules-{target_id}.yaml",
        "sandbox_profile_ref": "config/sandbox/default.yaml",
        "provider_routes_ref": "config/provider/routes.yaml",
        "output_destinations_ref": "config/output/destinations.yaml",
        "classification": {"country_axes": {}},
        "focus_areas": [],
        "lifecycle": {"status": "active"},
    }
    if topic_label:
        data["topic_label"] = topic_label
    return data


def _default_template_source(target_id: str) -> dict[str, Any]:
    return {
        "source_id": "rss-template",
        "display_name": f"{target_id} RSS Template",
        "type": "rss",
        "url": f"https://example.com/{target_id}/rss.xml",
        "credibility_base": 0.7,
        "fetch_interval_minutes": 60,
        "max_items_per_run": 20,
        "timeout_seconds": 20,
        "enabled": False,
        "deprecated": True,
        "deprecated_reason": "模板占位，启用前请替换为真实信源",
    }


def _copy_target_config_skeleton(source_target_id: str, target_id: str) -> list[str]:
    """复制 target 的配置骨架，不复制 data/ 历史数据。"""
    source_sources = Path("config/sources") / source_target_id
    target_sources = Path("config/sources") / target_id
    if source_sources.is_dir():
        shutil.copytree(source_sources, target_sources, dirs_exist_ok=True)

    source_filter = Path("config/filters") / source_target_id
    target_filter = Path("config/filters") / target_id
    if source_filter.is_dir():
        shutil.copytree(source_filter, target_filter, dirs_exist_ok=True)
    else:
        _atomic_write_yaml(target_filter / "default.yaml", _default_filter_config(target_id))

    source_classification = Path("config/classification") / f"rules-{source_target_id}.yaml"
    target_classification = Path("config/classification") / f"rules-{target_id}.yaml"
    if source_classification.is_file():
        data = _load_yaml_file(source_classification) or {}
        if "target_id" in data:
            data["target_id"] = target_id
        _atomic_write_yaml(target_classification, data)
    else:
        _atomic_write_yaml(target_classification, _default_classification_config(target_id))

    target_data = _ensure_target_exists(source_target_id)
    refs = target_data.get("source_channel_refs", [])
    return [str(ref) for ref in refs if isinstance(ref, str)]


def _stop_target_in_collector_config(target_id: str) -> None:
    config_path = Path("config/runtime/collector.yaml")
    data = _load_yaml_file(config_path)
    if not data:
        return
    target_ids = data.get("target_ids")
    changed = False
    if isinstance(target_ids, list) and target_id in target_ids:
        data["target_ids"] = [item for item in target_ids if item != target_id]
        changed = True
    elif isinstance(target_ids, str) and target_ids == target_id:
        data["target_ids"] = []
        changed = True
    if changed:
        _atomic_write_yaml(config_path, data)


def _build_source_config(payload: SourceCreateRequest) -> tuple[str, dict[str, Any]]:
    _validate_source_slug(payload.source_id)
    source_ref = _normalize_source_ref(payload.source_ref or payload.source_id)
    data: dict[str, Any] = {
        "source_id": payload.source_id,
        "display_name": payload.display_name,
        "type": payload.type,
        "credibility_base": payload.credibility_base,
        "fetch_interval_minutes": payload.fetch_interval_minutes,
        "max_items_per_run": payload.max_items_per_run,
        "timeout_seconds": payload.timeout_seconds,
        "enabled": payload.enabled,
    }
    if payload.notes:
        data["notes"] = payload.notes
    if payload.type == "rss":
        if not payload.url:
            raise HTTPException(status_code=400, detail="RSS source requires url")
        data["url"] = payload.url
    elif payload.type == "api":
        endpoint = payload.endpoint or {"url": payload.url, "method": "GET"}
        if not endpoint.get("url"):
            raise HTTPException(status_code=400, detail="API source requires endpoint.url")
        data["endpoint"] = endpoint
        data["api_mapping"] = payload.api_mapping or {}
    elif payload.type == "opencli":
        tool_ref = payload.tool_ref or payload.opencli_command
        if not tool_ref:
            raise HTTPException(status_code=400, detail="OpenCLI source requires tool_ref")
        data["tool_ref"] = tool_ref
        data["opencli_command"] = tool_ref
        data["tool_params"] = payload.tool_params or {}
        if payload.sandbox_profile_ref:
            data["sandbox_profile_ref"] = payload.sandbox_profile_ref
    return source_ref, data


def _social_dimensions(target_id: str) -> list[dict[str, Any]]:
    root = Path("config/sources") / target_id / "social"
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.yaml")):
        data = _load_yaml_file(path)
        if not data:
            continue
        rel = path.relative_to(Path("config/sources") / target_id).with_suffix("")
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            accounts = []
        data["_source_ref"] = str(rel)
        data["_file_path"] = str(path)
        data["accounts"] = accounts
        data["account_count"] = len(accounts)
        data["archived_count"] = sum(
            1
            for account in accounts
            if isinstance(account, dict) and account.get("monitor_mode") == "archived"
        )
        items.append(data)
    return items


def _find_social_dimension_path(target_id: str, dimension: str) -> Path | None:
    for item in _social_dimensions(target_id):
        if item.get("dimension") == dimension:
            file_path = item.get("_file_path")
            return Path(file_path) if file_path else None
    return None


def _validate_target_config(target_id: str) -> dict[str, Any]:
    """返回 target 配置链路预检结果。"""
    checks: list[dict[str, Any]] = []
    data = _load_target_config(target_id)
    if data is None:
        return {
            "target_id": target_id,
            "ok": False,
            "checks": [
                {
                    "id": "target_config",
                    "label": "Target 配置",
                    "ok": False,
                    "severity": "error",
                    "message": "Target 配置文件不存在",
                    "items": [],
                }
            ],
        }

    refs = [str(ref) for ref in data.get("source_channel_refs", []) if isinstance(ref, str)]
    duplicate_refs = sorted({ref for ref in refs if refs.count(ref) > 1})
    missing_refs = [
        ref for ref in refs if not (Path("config/sources") / target_id / f"{ref}.yaml").is_file()
    ]
    checks.append(
        {
            "id": "source_refs",
            "label": "信源引用",
            "ok": not duplicate_refs and not missing_refs,
            "severity": "error" if duplicate_refs or missing_refs else "ok",
            "message": "信源引用完整"
            if not duplicate_refs and not missing_refs
            else "存在重复或缺失的信源引用",
            "items": [{"type": "duplicate", "ref": ref} for ref in duplicate_refs]
            + [{"type": "missing", "ref": ref} for ref in missing_refs],
        }
    )

    ref_fields = [
        ("filter_rules_ref", "过滤规则"),
        ("classification_rules_ref", "分类规则"),
        ("sandbox_profile_ref", "沙箱配置"),
        ("provider_routes_ref", "Provider 路由"),
        ("output_destinations_ref", "输出配置"),
    ]
    for field, label in ref_fields:
        ref = data.get(field)
        exists = bool(ref) and Path(str(ref)).is_file()
        checks.append(
            {
                "id": field,
                "label": label,
                "ok": exists,
                "severity": "error" if not exists else "ok",
                "message": "引用文件存在" if exists else f"{label}引用缺失",
                "items": [] if exists else [{"ref": ref}],
            }
        )

    bad_urls: list[dict[str, str]] = []
    for source in _load_source_configs(target_id):
        if not _source_is_standard(source):
            continue
        url_val = source.get("url")
        if url_val is None and isinstance(source.get("endpoint"), dict):
            url_val = source["endpoint"].get("url")
        if (
            source.get("type") != "opencli"
            and url_val
            and not str(url_val).startswith(("http://", "https://"))
        ):
            bad_urls.append({"source_ref": str(source.get("_source_id", "")), "url": str(url_val)})
    checks.append(
        {
            "id": "source_urls",
            "label": "信源 URL",
            "ok": not bad_urls,
            "severity": "error" if bad_urls else "ok",
            "message": "URL 格式可用" if not bad_urls else "存在非 HTTP(S) URL",
            "items": bad_urls,
        }
    )

    missing_sessions: list[dict[str, str]] = []
    for social in _social_dimensions(target_id):
        ref = social.get("session_profile_ref")
        if ref and not Path(str(ref)).is_file():
            missing_sessions.append(
                {"dimension": str(social.get("dimension", "")), "session_profile_ref": str(ref)}
            )
    checks.append(
        {
            "id": "social_sessions",
            "label": "社媒会话",
            "ok": not missing_sessions,
            "severity": "warning" if missing_sessions else "ok",
            "message": "社媒会话配置存在" if not missing_sessions else "部分社媒会话配置缺失",
            "items": missing_sessions,
        }
    )
    return {
        "target_id": target_id,
        "ok": all(check["ok"] or check["severity"] == "warning" for check in checks),
        "checks": checks,
    }


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


def _draft_file_records(data_dir: Path, target_id: str) -> list[dict[str, Any]]:
    """读取 draft 文件的轻量诊断记录，不改变文件。"""
    drafts_dir = data_dir / target_id / "drafts"
    if not drafts_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for md_file in sorted(drafts_dir.glob("*.md")):
        event = _load_event_by_path(str(md_file)) or {}
        title = event.get("title_original") or event.get("title") or ""
        records.append(
            {
                "event_id": _event_id_from_frontmatter(event) or "",
                "path": str(md_file.relative_to(data_dir)),
                "title": str(title),
            }
        )
    return records


async def _draft_index_rows_for_target(
    store: AsyncStore | None,
    target_id: str,
) -> list[dict[str, Any]]:
    """读取 target drafts 索引行，用于维护诊断。"""
    if store is None or store._db is None:  # noqa: SLF001
        return []
    try:
        async with store._db.execute(  # noqa: SLF001
            "SELECT event_id, file_path, title_original "
            "FROM event_index WHERE target_id = ? AND stage = ? "
            "ORDER BY COALESCE(published_at, created_at, '') DESC",
            (target_id, _PUBLIC_ANALYSIS_STAGE),
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception:  # noqa: S112
        logger.exception("Failed to load draft index rows for target %s", target_id)
        return []
    return [
        {"event_id": str(row[0] or ""), "file_path": row[1], "title": str(row[2] or "")}
        for row in rows
    ]


async def _draft_diagnostics(data_dir: Path, target_id: str) -> dict[str, Any]:
    """生成 draft 文件与 SQLite 索引的只读一致性诊断。"""
    draft_files = _draft_file_records(data_dir, target_id)
    store = await _store_for_target(target_id)
    index_available = store is not None and await _store_has_target_event_index(store, target_id)
    index_rows = await _draft_index_rows_for_target(store, target_id) if index_available else []
    indexed_ids = {row["event_id"] for row in index_rows if row.get("event_id")}
    visible_index_count = 0
    if index_available:
        visible = await _visible_index_events_page(
            store,
            data_dir,
            target_id,
            stage=_PUBLIC_ANALYSIS_STAGE,
            page=1,
            page_size=1,
        )
        visible_index_count = int(visible["total"])

    grouped_files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in draft_files:
        event_id = item.get("event_id") or ""
        if event_id:
            grouped_files[event_id].append(item)

    duplicate_event_ids = [
        {
            "event_id": event_id,
            "count": len(items),
            "files": [item["path"] for item in items],
        }
        for event_id, items in sorted(grouped_files.items())
        if len(items) > 1
    ]
    orphan_files = [
        item
        for item in draft_files
        if index_available and (not item.get("event_id") or item.get("event_id") not in indexed_ids)
    ]
    missing_index_files = []
    for row in index_rows:
        file_path = row.get("file_path")
        if not file_path:
            continue
        if not _indexed_file_path_is_visible_in_stage(
            data_dir,
            target_id,
            _PUBLIC_ANALYSIS_STAGE,
            str(file_path),
        ):
            continue
        if not Path(str(file_path)).is_file():
            missing_index_files.append(
                {
                    "event_id": row.get("event_id") or "",
                    "path": str(file_path),
                    "title": row.get("title") or "",
                }
            )

    return {
        "target_id": target_id,
        "stage": _PUBLIC_ANALYSIS_STAGE,
        "index_available": bool(index_available),
        "draft_file_count": len(draft_files),
        "indexed_count": len(index_rows),
        "visible_index_count": visible_index_count,
        "orphan_file_count": len(orphan_files),
        "orphan_files": orphan_files,
        "duplicate_event_ids": duplicate_event_ids,
        "missing_index_file_count": len(missing_index_files),
        "missing_index_files": missing_index_files,
    }


def _relative_to_data_dir(data_dir: Path, path: Path) -> str:
    """返回面向 API 的 data_dir 相对路径。"""
    try:
        return str(path.relative_to(data_dir))
    except ValueError:
        return str(path)


def _duplicate_draft_keep_path(
    data_dir: Path,
    target_id: str,
    event_id: str,
    items: list[dict[str, Any]],
    index_rows: list[dict[str, Any]],
) -> Path:
    """从重复 draft 文件中选择要保留的 canonical 文件。"""
    candidate_paths = [data_dir / str(item["path"]) for item in items if item.get("path")]
    candidate_lookup = {path.resolve(strict=False): path for path in candidate_paths}
    drafts_dir = data_dir / target_id / "drafts"
    for row in index_rows:
        if row.get("event_id") != event_id or not row.get("file_path"):
            continue
        indexed_path = Path(str(row["file_path"]))
        if not indexed_path.is_absolute():
            indexed_path = data_dir / indexed_path
        try:
            indexed_path.relative_to(drafts_dir)
        except ValueError:
            continue
        kept = candidate_lookup.get(indexed_path.resolve(strict=False))
        if kept is not None:
            return kept

    canonical_name = f"{event_id}.md"
    for path in sorted(candidate_paths, key=lambda p: str(p)):
        if path.name == canonical_name:
            return path
    return sorted(candidate_paths, key=lambda p: str(p))[0]


def _unique_archive_path(archive_dir: Path, source_path: Path) -> Path:
    """避免归档目录内同名文件互相覆盖。"""
    candidate = archive_dir / source_path.name
    if not candidate.exists():
        return candidate
    suffix = uuid.uuid4().hex[:8]
    return archive_dir / f"{source_path.stem}-{suffix}{source_path.suffix}"


async def _archive_duplicate_drafts(
    data_dir: Path,
    target_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """将重复 event_id 的多余 draft 文件安全移动到 archive，不硬删除。"""
    _validate_target_slug(target_id)
    draft_files = _draft_file_records(data_dir, target_id)
    store = await _store_for_target(target_id)
    index_rows = await _draft_index_rows_for_target(store, target_id)
    grouped_files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in draft_files:
        event_id = item.get("event_id") or ""
        if event_id:
            grouped_files[event_id].append(item)

    duplicate_groups = {
        event_id: items for event_id, items in grouped_files.items() if len(items) > 1
    }
    archive_batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = data_dir / target_id / "archive" / "duplicate-drafts" / archive_batch
    archived_files: list[dict[str, Any]] = []
    skipped_files: list[dict[str, Any]] = []

    for event_id, items in sorted(duplicate_groups.items()):
        keep_path = _duplicate_draft_keep_path(data_dir, target_id, event_id, items, index_rows)
        for item in sorted(items, key=lambda value: str(value.get("path") or "")):
            source_path = data_dir / str(item["path"])
            if source_path.resolve(strict=False) == keep_path.resolve(strict=False):
                continue
            destination = _unique_archive_path(archive_dir, source_path)
            record = {
                "event_id": event_id,
                "source_path": _relative_to_data_dir(data_dir, source_path),
                "archived_path": _relative_to_data_dir(data_dir, destination),
                "kept_path": _relative_to_data_dir(data_dir, keep_path),
            }
            if dry_run:
                archived_files.append(record)
                continue
            if not source_path.is_file():
                skipped_files.append({**record, "reason": "source_missing"})
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination))
            archived_files.append(record)

    if archived_files and not dry_run:
        manifest_path = archive_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "target_id": target_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "archived_files": archived_files,
                    "skipped_files": skipped_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "target_id": target_id,
        "dry_run": dry_run,
        "duplicate_group_count": len(duplicate_groups),
        "archived_count": len(archived_files),
        "archived_files": archived_files,
        "skipped_files": skipped_files,
    }


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


def _load_event_by_id_from_stage(
    data_dir: Path,
    target_id: str,
    stage: str,
    event_id: str | None,
) -> dict[str, Any] | None:
    """当 SQLite file_path 失效时，从目标 stage 目录按事件 ID 找回 frontmatter。"""
    if not event_id:
        return None
    stage_dir = data_dir / target_id / stage
    if not stage_dir.is_dir():
        return None

    candidates: list[Path] = []
    id_short = event_id[:12]
    if id_short:
        candidates.extend(sorted(stage_dir.glob(f"*{id_short}*.md")))
    candidates.extend(sorted(stage_dir.glob("*.md")))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        event = _load_event_by_path(str(path))
        if event and (event.get("event_id") or event.get("id")) == event_id:
            return event
    return None


def _load_event_by_exact_id_filename(
    data_dir: Path,
    target_id: str,
    stage: str,
    event_id: str | None,
) -> dict[str, Any] | None:
    """按文件名中的完整 event_id 精确找回 frontmatter，避免全目录扫描。"""
    if not event_id:
        return None
    stage_dir = data_dir / target_id / stage
    if not stage_dir.is_dir():
        return None
    for path in sorted(stage_dir.glob(f"*{event_id}*.md")):
        event = _load_event_by_path(str(path))
        if _event_id_from_frontmatter(event) == event_id:
            return event
    return None


def _event_id_from_frontmatter(event: dict[str, Any] | None) -> str | None:
    if not event:
        return None
    value = event.get("event_id") or event.get("id")
    return str(value) if value else None


def _event_from_index_row(row: dict[str, Any]) -> dict[str, Any]:
    """当事件文件失效时，用 SQLite 索引行构造最小事件数据。"""
    event_id = row.get("event_id") or row.get("id") or ""
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    event: dict[str, Any] = {
        "id": event_id,
        "event_id": event_id,
        "source_id": row.get("source_id"),
        "url": row.get("url"),
        "title_original": row.get("title_original"),
        "published_at": row.get("published_at"),
        "created_at": row.get("created_at"),
        "news_value_score": row.get("news_value_score"),
        "china_relevance": row.get("china_relevance"),
        "sentiment": row.get("sentiment"),
        "metadata": metadata,
    }
    classification_l0 = row.get("classification_l0")
    if classification_l0:
        event["classification"] = {"l0": classification_l0}
    return {key: value for key, value in event.items() if value is not None}


def _deep_merge_mapping(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge_mapping(
                cast(dict[str, Any], existing),
                cast(dict[str, Any], value),
            )
        else:
            merged[key] = value
    return merged


def _merge_index_metadata(event: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    raw_index_metadata = row.get("metadata")
    index_metadata = (
        cast(dict[str, Any], raw_index_metadata) if isinstance(raw_index_metadata, dict) else {}
    )
    if not index_metadata:
        return event
    merged_event = dict(event)
    raw_current_metadata = merged_event.get("metadata")
    current_metadata = (
        cast(dict[str, Any], raw_current_metadata) if isinstance(raw_current_metadata, dict) else {}
    )
    merged_event["metadata"] = _deep_merge_mapping(current_metadata, index_metadata)
    return merged_event


def _markdown_download_response(filename: str, content: str) -> Response:
    """返回 Markdown attachment 响应，不触碰文件系统。"""
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    safe_name = safe_name.strip("._") or "export"
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_number(
    value: Any,
    *,
    integer: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if integer else number


def _safe_language(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return "mixed"
    primary = raw.split("-", maxsplit=1)[0]
    accepted = {"it", "en", "zh", "ja", "de", "fr", "mixed"}
    return primary if primary in accepted else "mixed"


def _safe_datetime_text(value: Any) -> str:
    text = str(value or "").strip()
    return text or datetime.now(UTC).isoformat()


def _safe_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _news_event_from_export_data(target_id: str, data: dict[str, Any]) -> NewsEvent:
    """把 API 详情/索引投影补齐为 renderer 需要的 NewsEvent。"""
    event_id = _safe_text(data.get("id") or data.get("event_id"), "export-event")
    metadata = _safe_mapping(data.get("metadata"))
    classification = data.get("classification")
    if isinstance(classification, dict):
        metadata.setdefault("classification", classification)

    published_at = _safe_datetime_text(data.get("published_at") or data.get("created_at"))
    collected_at = _safe_datetime_text(
        data.get("collected_at") or data.get("created_at") or published_at
    )
    stage = str(data.get("pipeline_stage") or data.get("stage") or "outputted")
    if stage not in {"collected", "filtered", "judged", "outputted"}:
        stage = "outputted"

    return NewsEvent.model_validate(
        {
            "id": event_id,
            "run_id": str(data.get("run_id") or f"export-{target_id}"),
            "source_id": _safe_text(data.get("source_id"), "unknown"),
            "url": _safe_text(data.get("url"), ""),
            "title_original": _safe_text(data.get("title_original") or data.get("title"), event_id),
            "title_translated": data.get("title_translated"),
            "content_original": _safe_text(data.get("content_original") or data.get("summary"), ""),
            "content_translated": data.get("content_translated"),
            "language": _safe_language(data.get("language")),
            "published_at": published_at,
            "collected_at": collected_at,
            "pipeline_stage": stage,
            "news_value_score": _safe_number(
                data.get("news_value_score"), integer=True, minimum=0, maximum=100
            ),
            "china_relevance": _safe_number(
                data.get("china_relevance"), integer=True, minimum=0, maximum=100
            ),
            "sentiment_score": _safe_number(data.get("sentiment_score"), minimum=-1.0, maximum=1.0),
            "cluster_id": data.get("cluster_id"),
            "story_id": data.get("story_id"),
            "metadata": metadata,
        }
    )


def _render_public_event_markdown_fallback(target_id: str, event: dict[str, Any]) -> str:
    event_id = _safe_text(event.get("id") or event.get("event_id"), "export-event")
    title = _safe_text(event.get("title_original") or event.get("title"), event_id)
    source_id = _safe_text(event.get("source_id"), "unknown")
    url = _safe_text(event.get("url"), "")
    published_at = _safe_datetime_text(event.get("published_at") or event.get("created_at"))
    frontmatter = yaml.dump(
        {
            "id": event_id,
            "target_id": target_id,
            "source_id": source_id,
            "url": url,
            "title_original": title,
            "published_at": published_at,
            "pipeline_stage": "outputted",
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{frontmatter}\n---\n\n# {title}\n\n**来源:** {source_id}\n"


def _render_public_event_markdown(target_id: str, event: dict[str, Any]) -> str:
    try:
        return render_news_event_markdown(_news_event_from_export_data(target_id, event))
    except ValidationError:
        return _render_public_event_markdown_fallback(target_id, event)


def _indexed_file_path_is_visible_in_stage(
    data_dir: Path,
    target_id: str,
    stage: str,
    file_path: str | None,
) -> bool:
    """file_path 为空允许索引兜底；记录路径时必须位于预期 stage 目录。"""
    if not file_path:
        return True
    path = Path(file_path)
    try:
        path.resolve().relative_to((data_dir / target_id / stage).resolve())
    except ValueError:
        return False
    return True


def _load_indexed_event_frontmatter(
    data_dir: Path,
    target_id: str,
    stage: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """读取 SQLite 索引行对应的 frontmatter，并防止旧碰撞 file_path 污染展示。"""
    event_id = row.get("event_id")
    event_fm = _load_event_by_path(row.get("file_path"))
    if event_fm is not None and _event_id_from_frontmatter(event_fm) != event_id:
        event_fm = None
    if event_fm is None and row.get("file_path") is not None:
        event_fm = _load_event_by_id_from_stage(data_dir, target_id, stage, event_id)
    if event_fm is None and stage == "drafts":
        event_fm = _load_event_by_exact_id_filename(data_dir, target_id, "evaluated", event_id)
    return event_fm


async def _load_indexed_event_detail(
    data_dir: Path,
    target_id: str,
    store: Any,
    event_id: str,
) -> dict[str, Any] | InvisibleIndexedEvent | None:
    """从 store 读取详情，并校验 file_path 指向的 frontmatter 属于该事件。"""
    get_row = getattr(store, "get_event_index_row", None)
    if get_row is None:
        return None
    row = await get_row(target_id, event_id)
    if row is None or row.get("stage") != "drafts":
        return _INVISIBLE_INDEXED_EVENT if row is not None else None
    file_path = row.get("file_path")
    if not _indexed_file_path_is_visible_in_stage(data_dir, target_id, "drafts", file_path):
        return _INVISIBLE_INDEXED_EVENT

    if file_path is not None:
        event = _load_event_by_path(file_path)
        if event is not None and _event_id_from_frontmatter(event) == event_id:
            return _merge_index_metadata(event, row)
        event = _load_event_by_id_from_stage(data_dir, target_id, "drafts", event_id)
        if event is not None:
            return _merge_index_metadata(event, row)

    return _merge_index_metadata(_event_from_index_row(row), row)


# ── 后台自动采集循环 ──────────────────────────────────────


def _parse_target_ids(raw: str) -> list[str]:
    """解析 target ID 字符串：'all' → 全量 targets，'a,b' → ['a','b']."""
    if raw.strip().lower() == "all":
        from news_sentry.core.async_run import _resolve_targets
        from news_sentry.core.run import _find_project_root

        return _resolve_targets("all", _find_project_root())
    return [t.strip() for t in raw.split(",") if t.strip()]


_auto_collector_state: dict[str, Any] = {
    "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
    "target_ids": _parse_target_ids(
        os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "all"))
    ),
    "interval_minutes": int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15")),
    "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),
    "running": False,
    "last_run_at": None,
    "last_run_status": None,
    "last_events_collected": 0,
    "last_error": None,
    "next_run_at": None,
    "total_runs": 0,
    "task": None,
}

_log = logging.getLogger("news_sentry.auto_collector")
_ai_enrichment_log = logging.getLogger("news_sentry.ai_enrichment")
_public_translation_log = logging.getLogger("news_sentry.public_translation")

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

_COLLECTOR_STAGES = {"all", "collect", "filter", "judge", "output"}


def _collector_config_path() -> Path:
    """返回本地持久化的采集器配置路径。"""
    return Path("config/runtime/collector.yaml")


def _collector_env_defaults() -> dict[str, Any]:
    """从环境变量构造采集器默认值。"""
    try:
        interval = int(os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "15"))
    except ValueError:
        interval = 15
    return {
        "enabled": os.environ.get("NEWSSENTRY_AUTO_COLLECT", "1") == "1",
        "target_ids": _parse_target_ids(
            os.environ.get("NEWSSENTRY_TARGET_ID", os.environ.get("TARGET_ID", "all"))
        ),
        "interval_minutes": interval,
        "stage": os.environ.get("NEWSSENTRY_COLLECT_STAGE", "collect"),
    }


def _normalize_collector_config(raw: dict[str, Any]) -> dict[str, Any]:
    """规范化采集器配置，保证 API 与 YAML 使用同一形状。"""
    defaults = _collector_env_defaults()
    data = {**defaults, **{k: v for k, v in raw.items() if v is not None}}

    target_ids_raw = data.get("target_ids", defaults["target_ids"])
    if isinstance(target_ids_raw, str):
        target_ids = _parse_target_ids(target_ids_raw)
    elif isinstance(target_ids_raw, list):
        target_ids = [str(t).strip() for t in target_ids_raw if str(t).strip()]
    else:
        target_ids = defaults["target_ids"]

    stage = str(data.get("stage") or defaults["stage"]).strip().lower()
    if stage not in _COLLECTOR_STAGES:
        stage = defaults["stage"] if defaults["stage"] in _COLLECTOR_STAGES else "collect"

    try:
        interval = int(data.get("interval_minutes", defaults["interval_minutes"]))
    except (TypeError, ValueError):
        interval = int(defaults["interval_minutes"])
    interval = max(1, min(interval, 1440))

    return {
        "enabled": bool(data.get("enabled")),
        "target_ids": target_ids,
        "interval_minutes": interval,
        "stage": stage,
    }


def _load_collector_config() -> dict[str, Any]:
    """读取采集器配置；没有 YAML 时使用环境变量默认值。"""
    path = _collector_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_collector_config(loaded)


def _save_collector_config(config: dict[str, Any]) -> None:
    """持久化采集器配置到 config/runtime/collector.yaml。"""
    normalized = _normalize_collector_config(config)
    path = _collector_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, normalized)


def _apply_collector_config(config: dict[str, Any]) -> dict[str, Any]:
    """应用采集器配置到内存状态并返回规范化结果。"""
    normalized = _normalize_collector_config(config)
    _auto_collector_state["enabled"] = normalized["enabled"]
    _auto_collector_state["target_ids"] = normalized["target_ids"]
    _auto_collector_state["interval_minutes"] = normalized["interval_minutes"]
    _auto_collector_state["stage"] = normalized["stage"]
    return normalized


def _collector_payload() -> dict[str, Any]:
    """返回统一的采集器状态响应。"""
    latest_log = _latest_run_log_summary(_data_dir)
    last_run_at = _auto_collector_state["last_run_at"]
    last_run_status = _auto_collector_state["last_run_status"]
    last_events_collected = _auto_collector_state.get("last_events_collected", 0)
    if latest_log and not last_run_at:
        last_run_at = latest_log.get("ended_at") or latest_log.get("started_at")
        last_run_status = latest_log.get("status")
        last_events_collected = latest_log.get("events_collected", 0)
    return {
        "enabled": _auto_collector_state["enabled"],
        "running": _auto_collector_state["running"],
        "target_ids": _auto_collector_state["target_ids"],
        "stage": _auto_collector_state["stage"],
        "interval_minutes": _auto_collector_state["interval_minutes"],
        "last_run_at": last_run_at,
        "last_run_status": last_run_status,
        "last_events_collected": last_events_collected,
        "last_error": _auto_collector_state.get("last_error"),
        "next_run_at": _auto_collector_state.get("next_run_at"),
        "total_runs": _auto_collector_state["total_runs"],
    }


def _collector_diagnostics_signature() -> str:
    paths: list[Path] = []
    if _data_dir.exists():
        for target_dir in sorted(d for d in _data_dir.iterdir() if d.is_dir()):
            paths.append(target_dir / "memory" / "source_health.yaml")
            paths.append(target_dir / "source_health.json")
            paths.extend(_target_source_paths(target_dir.name))
    return _file_signature(paths)


def _build_collector_diagnostics_payload() -> dict[str, Any]:
    """Build collector diagnostics without endpoint/auth concerns."""
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "name": "auto_collect_enabled",
            "ok": _auto_collector_state["enabled"],
            "message": (
                "已启用"
                if _auto_collector_state["enabled"]
                else "未启用 — 设置 NEWSSENTRY_AUTO_COLLECT=1"
            ),
        }
    )

    has_ai_key = bool(
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    checks.append(
        {
            "name": "ai_api_key",
            "ok": has_ai_key,
            "message": "已配置" if has_ai_key else "未配置 AI API Key — 研判/翻译将跳过",
        }
    )

    data_exists = _data_dir.exists()
    target_dirs = sorted([d.name for d in _data_dir.iterdir() if d.is_dir()]) if data_exists else []
    checks.append(
        {
            "name": "data_directory",
            "ok": data_exists and len(target_dirs) > 0,
            "message": (
                f"数据目录: {_data_dir} — {len(target_dirs)} 个 target: "
                f"{', '.join(target_dirs) if target_dirs else '无'}"
            ),
        }
    )

    healthy = 0
    unhealthy = 0
    if data_exists:
        for tid in target_dirs:
            memory_health = _filter_source_health_records(
                tid,
                _load_memory_source_health_records(tid),
            )
            if memory_health:
                for item in memory_health:
                    if item.get("status") == "healthy":
                        healthy += 1
                    else:
                        unhealthy += 1
                continue
            health_file = _data_dir / tid / "source_health.json"
            if health_file.exists():
                try:
                    health_data = json.loads(health_file.read_text())
                    items = health_data if isinstance(health_data, list) else []
                    for item in items:
                        if item.get("healthy"):
                            healthy += 1
                        else:
                            unhealthy += 1
                except Exception:  # noqa: S110
                    pass
    checks.append(
        {
            "name": "source_health",
            "ok": (healthy + unhealthy) > 0,
            "message": (
                f"健康: {healthy}, 异常: {unhealthy}"
                if (healthy + unhealthy) > 0
                else "暂无信源健康数据 — 运行一次采集后生成"
            ),
        }
    )

    last_run = _collector_payload()["last_run_at"]
    checks.append(
        {
            "name": "last_collection",
            "ok": last_run is not None,
            "message": f"最后采集: {last_run}" if last_run else "尚未执行采集 — 等待首次采集周期",
        }
    )

    overall = all(check["ok"] for check in checks)
    return {"overall": "healthy" if overall else "attention_needed", "checks": checks}


def _cached_collector_diagnostics_payload() -> dict[str, Any]:
    signature = _collector_diagnostics_signature()
    now = time.monotonic()
    if (
        _collector_diagnostics_cache.get("signature") == signature
        and now - float(_collector_diagnostics_cache.get("created_at", 0))
        <= _OVERVIEW_CACHE_TTL_SECONDS
    ):
        value = _collector_diagnostics_cache.get("value")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    value = _build_collector_diagnostics_payload()
    _collector_diagnostics_cache.update(
        {
            "signature": signature,
            "created_at": now,
            "value": value,
        }
    )
    return value


def _ai_enrichment_config_path() -> Path:
    return Path("config/runtime/ai_enrichment.yaml")


def _ai_enrichment_env_defaults() -> dict[str, Any]:
    return {
        "enabled": os.environ.get("NEWSSENTRY_AI_ENRICHMENT", "1") == "1",
        "interval_minutes": int(os.environ.get("NEWSSENTRY_AI_ENRICH_INTERVAL", "60")),
        "daily_request_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_DAILY_LIMIT", "45")),
        "per_cycle_request_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_PER_CYCLE", "3")),
        "max_chars_per_request": int(os.environ.get("NEWSSENTRY_AI_ENRICH_MAX_CHARS", "6000")),
        "cooldown_after_429_minutes": int(
            os.environ.get("NEWSSENTRY_AI_ENRICH_COOLDOWN_MINUTES", "120")
        ),
        "targets": os.environ.get("NEWSSENTRY_AI_ENRICH_TARGETS", "all"),
        "candidate_limit": int(os.environ.get("NEWSSENTRY_AI_ENRICH_CANDIDATES", "200")),
    }


def _ai_enrichment_config_to_dict(config: AIEnrichmentConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "interval_minutes": config.interval_minutes,
        "daily_request_limit": config.daily_request_limit,
        "per_cycle_request_limit": config.per_cycle_request_limit,
        "max_chars_per_request": config.max_chars_per_request,
        "cooldown_after_429_minutes": config.cooldown_after_429_minutes,
        "targets": list(config.targets),
        "candidate_limit": config.candidate_limit,
    }


def _normalize_ai_enrichment_config(raw: dict[str, Any] | None) -> AIEnrichmentConfig:
    return normalize_ai_enrichment_config({**_ai_enrichment_env_defaults(), **(raw or {})})


def _load_ai_enrichment_config() -> AIEnrichmentConfig:
    path = _ai_enrichment_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_ai_enrichment_config(loaded)


def _save_ai_enrichment_config(config: dict[str, Any]) -> AIEnrichmentConfig:
    normalized = _normalize_ai_enrichment_config(config)
    path = _ai_enrichment_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, _ai_enrichment_config_to_dict(normalized))
    return normalized


def _apply_ai_enrichment_config(config: AIEnrichmentConfig | dict[str, Any]) -> AIEnrichmentConfig:
    normalized = (
        config
        if isinstance(config, AIEnrichmentConfig)
        else _normalize_ai_enrichment_config(config)
    )
    for key, value in _ai_enrichment_config_to_dict(normalized).items():
        _ai_enrichment_state[key] = value
    return normalized


def _current_ai_enrichment_config() -> AIEnrichmentConfig:
    return normalize_ai_enrichment_config(
        {
            "enabled": _ai_enrichment_state["enabled"],
            "interval_minutes": _ai_enrichment_state["interval_minutes"],
            "daily_request_limit": _ai_enrichment_state["daily_request_limit"],
            "per_cycle_request_limit": _ai_enrichment_state["per_cycle_request_limit"],
            "max_chars_per_request": _ai_enrichment_state["max_chars_per_request"],
            "cooldown_after_429_minutes": _ai_enrichment_state["cooldown_after_429_minutes"],
            "targets": _ai_enrichment_state["targets"],
            "candidate_limit": _ai_enrichment_state["candidate_limit"],
        }
    )


def _public_translation_config_path() -> Path:
    return Path("config/runtime/public_translation.yaml")


def _safe_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _safe_int_env_value(value: str | None, default: int) -> int:
    try:
        return int(value or str(default))
    except (TypeError, ValueError):
        return default


def _public_translation_env_defaults() -> dict[str, Any]:
    publication_interval = os.environ.get(
        "NEWSSENTRY_PUBLIC_PUBLICATION_INTERVAL",
        os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_INTERVAL", "5"),
    )
    publication_per_cycle = os.environ.get(
        "NEWSSENTRY_PUBLIC_PUBLICATION_PER_CYCLE",
        os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_PER_CYCLE", "50"),
    )
    return {
        "enabled": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION", "1") == "1",
        "interval_minutes": _safe_int_env_value(publication_interval, 5),
        "per_cycle_limit": _safe_int_env_value(publication_per_cycle, 50),
        "candidate_limit": _safe_int_env("NEWSSENTRY_PUBLIC_TRANSLATION_CANDIDATES", 500),
        "source_lang": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_SOURCE_LANG", "auto"),
        "target_lang": os.environ.get("NEWSSENTRY_PUBLIC_TRANSLATION_TARGET_LANG", "zh"),
    }


def _public_translation_config_to_dict(config: PublicTranslationConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "interval_minutes": config.interval_minutes,
        "per_cycle_limit": config.per_cycle_limit,
        "candidate_limit": config.candidate_limit,
        "source_lang": config.source_lang,
        "target_lang": config.target_lang,
    }


def _normalize_public_translation_config(
    raw: dict[str, Any] | None,
) -> PublicTranslationConfig:
    return normalize_public_translation_config(
        {**_public_translation_env_defaults(), **(raw or {})}
    )


def _load_public_translation_config() -> PublicTranslationConfig:
    path = _public_translation_config_path()
    loaded: dict[str, Any] = {}
    if path.is_file():
        loaded = _load_yaml_file(path) or {}
    return _normalize_public_translation_config(loaded)


def _save_public_translation_config(config: dict[str, Any]) -> PublicTranslationConfig:
    normalized = _normalize_public_translation_config(config)
    path = _public_translation_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, _public_translation_config_to_dict(normalized))
    return normalized


def _apply_public_translation_config(
    config: PublicTranslationConfig | dict[str, Any],
) -> PublicTranslationConfig:
    normalized = (
        config
        if isinstance(config, PublicTranslationConfig)
        else _normalize_public_translation_config(config)
    )
    for key, value in _public_translation_config_to_dict(normalized).items():
        _public_translation_state[key] = value
    return normalized


def _current_public_translation_config() -> PublicTranslationConfig:
    return normalize_public_translation_config(
        {
            "enabled": _public_translation_state["enabled"],
            "interval_minutes": _public_translation_state["interval_minutes"],
            "per_cycle_limit": _public_translation_state["per_cycle_limit"],
            "candidate_limit": _public_translation_state["candidate_limit"],
            "source_lang": _public_translation_state["source_lang"],
            "target_lang": _public_translation_state["target_lang"],
        }
    )


def _ai_enrichment_today() -> str:
    return datetime.now(UTC).date().isoformat()


def _ai_enrichment_target_ids(
    config: AIEnrichmentConfig,
    target_id: str | None = None,
) -> list[str]:
    if target_id and target_id != "all":
        return [target_id]
    if "all" in config.targets:
        return [item["target_id"] for item in _load_target_configs() if item.get("target_id")]
    return list(config.targets)


def _create_ai_provider_router() -> Any | None:  # noqa: ANN401
    try:
        from news_sentry.core.provider_router import ProviderRouter
        from news_sentry.models.provider_config import ProviderRoutesConfig

        routes_path = Path("config/provider/routes.yaml")
        if not routes_path.is_file():
            return None
        data = _load_yaml_file(routes_path)
        if not isinstance(data, dict):
            return None
        return ProviderRouter(ProviderRoutesConfig(**data))
    except Exception as exc:  # noqa: BLE001
        _ai_enrichment_log.warning("AI enrichment provider router unavailable: %s", exc)
        return None


def _build_ai_provider_factory() -> Any:  # noqa: ANN401
    from news_sentry.core.run import _build_provider_factory

    return _build_provider_factory()


async def _ai_enrichment_store_for_target(target_id: str) -> AsyncStore | None:
    target_store = await _get_target_store(target_id)
    return target_store if target_store is not None else _store


async def _ai_enrichment_rows_for_target(
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if store is None:
        return []
    result = await _visible_index_events_page(
        store,
        _data_dir,
        stage="drafts",
        target_id=target_id,
        page=1,
        page_size=limit,
        exact_total=False,
    )
    return list(result.get("events") or [])


async def _ai_enrichment_usage_store(target_stores: list[AsyncStore | None]) -> AsyncStore | None:
    if _store is not None:
        return _store
    for store in target_stores:
        if store is not None:
            return store
    return None


async def _ai_enrichment_status_payload() -> dict[str, Any]:
    config = _current_ai_enrichment_config()
    usage_store = await _ai_enrichment_usage_store([])
    usage = (
        await usage_store.get_ai_enrichment_usage(_ai_enrichment_today())
        if usage_store is not None
        else {
            "usage_date": _ai_enrichment_today(),
            "request_count": 0,
            "cooldown_until": None,
            "last_error": None,
        }
    )
    return {
        "enabled": _ai_enrichment_state["enabled"],
        "running": _ai_enrichment_state["running"],
        "config": _ai_enrichment_config_to_dict(config),
        "usage": usage,
        "remaining_daily_requests": max(
            0, config.daily_request_limit - int(usage.get("request_count") or 0)
        ),
        "last_run_at": _ai_enrichment_state.get("last_run_at"),
        "last_run_status": _ai_enrichment_state.get("last_run_status"),
        "last_error": _ai_enrichment_state.get("last_error"),
        "next_run_at": _ai_enrichment_state.get("next_run_at"),
        "total_runs": _ai_enrichment_state["total_runs"],
        "last_updates": _ai_enrichment_state.get("last_updates", 0),
    }


async def _run_ai_enrichment_once(
    *,
    target_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = _current_ai_enrichment_config()
    engine = AIEnrichmentEngine(config)
    target_ids = _ai_enrichment_target_ids(config, target_id)
    stores_by_target: dict[str, AsyncStore | None] = {}
    rows_by_target: dict[str, list[dict[str, Any]]] = {}
    for tid in target_ids:
        store = await _ai_enrichment_store_for_target(tid)
        stores_by_target[tid] = store
        rows_by_target[tid] = await _ai_enrichment_rows_for_target(
            tid, store, limit=config.candidate_limit
        )

    if dry_run:
        return {
            "dry_run": True,
            "targets": target_ids,
            "batches": [
                engine.payload_for_batch(batch)
                for tid in target_ids
                for batch in engine.plan_batches(tid, rows_by_target[tid])[
                    : config.per_cycle_request_limit
                ]
            ],
        }

    usage_store = await _ai_enrichment_usage_store(list(stores_by_target.values()))
    if usage_store is None:
        return {"dry_run": False, "status": "no_store", "targets": target_ids, "updates": []}

    today = _ai_enrichment_today()
    usage = await usage_store.get_ai_enrichment_usage(today)
    if usage.get("cooldown_until") and str(usage["cooldown_until"]) > datetime.now(UTC).isoformat():
        return {
            "dry_run": False,
            "status": "cooldown",
            "targets": target_ids,
            "cooldown_until": usage.get("cooldown_until"),
            "updates": [],
        }
    if int(usage.get("request_count") or 0) >= config.daily_request_limit:
        return {"dry_run": False, "status": "daily_limit", "targets": target_ids, "updates": []}

    router = _create_ai_provider_router()
    if router is None:
        return {"dry_run": False, "status": "no_router", "targets": target_ids, "updates": []}

    provider_factory = _build_ai_provider_factory()
    total_updates: list[dict[str, Any]] = []
    total_requests = 0
    target_results: list[dict[str, Any]] = []
    for tid in target_ids:
        used_today = int(usage.get("request_count") or 0)
        remaining = config.daily_request_limit - used_today - total_requests
        if remaining <= 0:
            break
        target_config = AIEnrichmentConfig(
            **{
                **_ai_enrichment_config_to_dict(config),
                "per_cycle_request_limit": min(config.per_cycle_request_limit, remaining),
            }
        )
        result = await AIEnrichmentEngine(target_config).run_batches(
            target_id=tid,
            rows=rows_by_target[tid],
            router=router,
            provider_factory=provider_factory,
        )
        total_requests += int(result.get("requests_attempted") or 0)
        if result.get("status") == "cooldown":
            await usage_store.increment_ai_enrichment_usage(today, total_requests)
            await usage_store.set_ai_enrichment_cooldown(
                today,
                AIEnrichmentEngine.cooldown_until(config),
                str(result.get("error") or "rate limited"),
            )
            return {
                "dry_run": False,
                "status": "cooldown",
                "targets": target_ids,
                "requests_attempted": total_requests,
                "updates": total_updates,
                "target_results": target_results,
                "error": result.get("error"),
            }
        updates = list(result.get("updates") or [])
        store = stores_by_target[tid]
        if store is not None:
            for update in updates:
                event_id = str(update.get("event_id") or update.get("id") or "")
                raw_metadata = update.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                if event_id:
                    await store.update_event_metadata(tid, event_id, metadata)
                    ai_meta = metadata.get("ai_enrichment") if isinstance(metadata, dict) else {}
                    await store.record_ai_enrichment_event(
                        tid,
                        event_id,
                        field_hash=ai_meta.get("title_hash") if isinstance(ai_meta, dict) else None,
                        status="completed",
                        model=ai_meta.get("model") if isinstance(ai_meta, dict) else None,
                        route_id=ai_meta.get("route_id") if isinstance(ai_meta, dict) else None,
                    )
        total_updates.extend(updates)
        target_results.append(
            {
                "target_id": tid,
                "status": result.get("status"),
                "requests_attempted": result.get("requests_attempted", 0),
                "updates": len(updates),
            }
        )

    if total_requests:
        await usage_store.increment_ai_enrichment_usage(today, total_requests)
    return {
        "dry_run": False,
        "status": "ok",
        "targets": target_ids,
        "requests_attempted": total_requests,
        "updates": total_updates,
        "target_results": target_results,
    }


def _public_translation_target_ids(target_id: str | None = None) -> list[str]:
    if target_id and target_id != "all":
        return [target_id]
    return [item["target_id"] for item in _load_target_configs() if item.get("target_id")]


async def _public_translation_store_for_target(target_id: str) -> AsyncStore | None:
    target_store = await _get_target_store(target_id)
    return target_store if target_store is not None else _store


async def _public_translation_rows_for_target(
    target_id: str,
    store: AsyncStore | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if store is None:
        return []
    list_candidates = getattr(store, "list_public_translation_candidates", None)
    if list_candidates is None:
        return []
    rows = await list_candidates(target_id, limit=limit)
    return list(rows or [])


def _provider_available(provider_name: str) -> bool:
    try:
        provider_factory = _build_ai_provider_factory()
        provider = provider_factory(provider_name)
        return bool(provider is not None and provider.health_check())
    except Exception:  # noqa: BLE001
        return False


def _missing_publication_reason(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or public_publication_ready(metadata):
        return False
    translation = metadata.get("translation")
    publication = metadata.get("publication")
    if not isinstance(translation, dict):
        return False
    title = str(translation.get("title_pre") or "").strip()
    summary = str(translation.get("summary_pre") or "").strip()
    if not title or not summary:
        return False
    if not isinstance(publication, dict):
        return True
    return not str(publication.get("recommendation_reason") or "").strip()


async def _public_translation_status_payload() -> dict[str, Any]:
    config = _current_public_translation_config()
    target_ids = _public_translation_target_ids()
    publication_ready_count = 0
    pending_reason_count = 0
    for tid in target_ids:
        publication_ready_count += await _target_public_event_count(tid, _data_dir)
        store = await _public_translation_store_for_target(tid)
        rows = await _public_translation_rows_for_target(
            tid,
            store,
            limit=min(config.candidate_limit, 1000),
        )
        pending_reason_count += sum(1 for row in rows if _missing_publication_reason(row))
    return {
        "enabled": _public_translation_state["enabled"],
        "running": _public_translation_state["running"],
        "config": _public_translation_config_to_dict(config),
        "publication_ready_count": publication_ready_count,
        "pending_reason_count": pending_reason_count,
        "freellmapi_available": _provider_available("freellmapi"),
        "last_run_at": _public_translation_state.get("last_run_at"),
        "last_run_status": _public_translation_state.get("last_run_status"),
        "last_error": _public_translation_state.get("last_error"),
        "next_run_at": _public_translation_state.get("next_run_at"),
        "total_runs": _public_translation_state["total_runs"],
        "last_updates": _public_translation_state.get("last_updates", 0),
    }


async def _run_public_translation_once(
    *,
    target_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = _current_public_translation_config()
    engine = PublicTranslationEngine(config)
    target_ids = _public_translation_target_ids(target_id)
    stores_by_target: dict[str, AsyncStore | None] = {}
    rows_by_target: dict[str, list[dict[str, Any]]] = {}
    for tid in target_ids:
        store = await _public_translation_store_for_target(tid)
        stores_by_target[tid] = store
        rows_by_target[tid] = await _public_translation_rows_for_target(
            tid,
            store,
            limit=config.candidate_limit,
        )

    if dry_run:
        candidates = [
            {
                "target_id": tid,
                "event_id": row.get("event_id"),
                "title_original": row.get("title_original"),
                "published_at": row.get("published_at"),
                "attempts": row.get("translation_attempts") or 0,
            }
            for tid in target_ids
            for row in rows_by_target[tid]
            if engine.row_is_due(row)
        ][: config.per_cycle_limit]
        return {
            "dry_run": True,
            "targets": target_ids,
            "candidates": candidates,
            "total_candidates": sum(len(rows_by_target[tid]) for tid in target_ids),
        }

    router = _create_ai_provider_router()
    if router is None:
        return {"dry_run": False, "status": "no_router", "targets": target_ids, "updates": []}

    provider_factory = _build_ai_provider_factory()
    total_updates: list[dict[str, Any]] = []
    total_failed = 0
    target_results: list[dict[str, Any]] = []
    for tid in target_ids:
        store = stores_by_target[tid]
        if store is None:
            target_results.append({"target_id": tid, "status": "no_store", "updated": 0})
            continue
        remaining = config.per_cycle_limit - len(total_updates)
        if remaining <= 0:
            break
        target_config = PublicTranslationConfig(
            **{
                **_public_translation_config_to_dict(config),
                "per_cycle_limit": remaining,
            }
        )
        result = await PublicTranslationEngine(target_config).run_rows(
            target_id=tid,
            rows=rows_by_target[tid],
            store=store,
            router=router,
            provider_factory=provider_factory,
        )
        updates = list(result.get("updates") or [])
        total_updates.extend(updates)
        total_failed += int(result.get("failed") or 0)
        target_results.append(
            {
                "target_id": tid,
                "status": result.get("status"),
                "updated": len(updates),
                "failed": int(result.get("failed") or 0),
            }
        )
        if len(total_updates) >= config.per_cycle_limit:
            break

    if total_updates and total_failed:
        status = "partial"
    elif total_updates:
        status = "ok"
    elif total_failed:
        status = "retrying"
    else:
        status = "empty"
    return {
        "dry_run": False,
        "status": status,
        "targets": target_ids,
        "updates": total_updates,
        "failed": total_failed,
        "target_results": target_results,
    }


def _update_collector_run_metrics(contexts: Any) -> None:
    """把多 target pipeline 上下文汇总到采集器状态。"""
    if contexts is None:
        context_items: list[Any] = []
    elif isinstance(contexts, (list, tuple, set)):
        context_items = list(contexts)
    else:
        context_items = [contexts]

    _auto_collector_state["last_events_collected"] = sum(
        int(getattr(ctx, "events_collected", 0) or 0) for ctx in context_items
    )


async def _auto_collect_loop() -> None:
    """后台循环：每隔 interval_minutes 对每个 target 执行 pipeline 阶段。

    通过 NEWSSENTRY_COLLECT_STAGE 控制执行的阶段（默认 collect），
    通过 NEWSSENTRY_TARGET_ID 控制 target 范围（默认 all，逗号分隔或 all）。
    """
    _auto_collector_state["running"] = True
    _log.info(
        "自动采集循环启动: targets=%s, stage=%s, interval=%dmin",
        _auto_collector_state["target_ids"],
        _auto_collector_state["stage"],
        _auto_collector_state["interval_minutes"],
    )

    while _auto_collector_state["enabled"]:
        try:
            from news_sentry.core.async_run import bounded_run_multi_async

            target_ids = _auto_collector_state["target_ids"]
            stage = _auto_collector_state["stage"]
            run_id = f"auto_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            _log.info("自动采集开始: run_id=%s, targets=%s", run_id, target_ids)

            contexts = await bounded_run_multi_async(
                targets=target_ids,
                stage=stage,
                run_id=run_id,
            )
            _update_collector_run_metrics(contexts)

            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "ok"
            _auto_collector_state["last_error"] = None
            _auto_collector_state["total_runs"] += 1
            _log.info("自动采集完成: run_id=%s", run_id)
        except Exception as exc:
            _auto_collector_state["last_run_at"] = datetime.now(UTC).isoformat()
            _auto_collector_state["last_run_status"] = "error"
            _auto_collector_state["last_error"] = str(exc)
            _auto_collector_state["total_runs"] += 1
            _log.error("自动采集失败", exc_info=True)

        interval = _auto_collector_state["interval_minutes"] * 60
        _auto_collector_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)

    _auto_collector_state["running"] = False
    _auto_collector_state["next_run_at"] = None
    _log.info("自动采集循环停止")


async def _ai_enrichment_loop() -> None:
    """Low-frequency OpenRouter/free-model enrichment loop."""
    _ai_enrichment_state["running"] = True
    _ai_enrichment_log.info(
        "AI 增强循环启动: targets=%s interval=%dmin daily_limit=%d",
        _ai_enrichment_state["targets"],
        _ai_enrichment_state["interval_minutes"],
        _ai_enrichment_state["daily_request_limit"],
    )

    while _ai_enrichment_state["enabled"]:
        interval = int(_ai_enrichment_state["interval_minutes"]) * 60
        _ai_enrichment_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)
        if not _ai_enrichment_state["enabled"]:
            break
        try:
            result = await _run_ai_enrichment_once()
            _ai_enrichment_state["last_run_at"] = datetime.now(UTC).isoformat()
            _ai_enrichment_state["last_run_status"] = result.get("status")
            _ai_enrichment_state["last_error"] = result.get("error")
            _ai_enrichment_state["last_updates"] = len(result.get("updates") or [])
            _ai_enrichment_state["total_runs"] += 1
        except Exception as exc:  # noqa: BLE001
            _ai_enrichment_state["last_run_at"] = datetime.now(UTC).isoformat()
            _ai_enrichment_state["last_run_status"] = "error"
            _ai_enrichment_state["last_error"] = str(exc)
            _ai_enrichment_state["last_updates"] = 0
            _ai_enrichment_state["total_runs"] += 1
            _ai_enrichment_log.error("AI 增强循环失败", exc_info=True)

    _ai_enrichment_state["running"] = False
    _ai_enrichment_state["next_run_at"] = None
    _ai_enrichment_log.info("AI 增强循环停止")


async def _public_translation_loop() -> None:
    """Public translation loop: run immediately, then retry with interval backoff."""
    _public_translation_state["running"] = True
    _public_translation_log.info(
        "公共翻译循环启动: interval=%dmin per_cycle=%d candidates=%d",
        _public_translation_state["interval_minutes"],
        _public_translation_state["per_cycle_limit"],
        _public_translation_state["candidate_limit"],
    )

    while _public_translation_state["enabled"]:
        try:
            result = await _run_public_translation_once()
            _public_translation_state["last_run_at"] = datetime.now(UTC).isoformat()
            _public_translation_state["last_run_status"] = result.get("status")
            _public_translation_state["last_error"] = result.get("error")
            _public_translation_state["last_updates"] = len(result.get("updates") or [])
            _public_translation_state["total_runs"] += 1
        except Exception as exc:  # noqa: BLE001
            _public_translation_state["last_run_at"] = datetime.now(UTC).isoformat()
            _public_translation_state["last_run_status"] = "error"
            _public_translation_state["last_error"] = str(exc)
            _public_translation_state["last_updates"] = 0
            _public_translation_state["total_runs"] += 1
            _public_translation_log.error("公共翻译循环失败", exc_info=True)

        interval = int(_public_translation_state["interval_minutes"]) * 60
        _public_translation_state["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=interval)
        ).isoformat()
        await asyncio.sleep(interval)

    _public_translation_state["running"] = False
    _public_translation_state["next_run_at"] = None
    _public_translation_log.info("公共翻译循环停止")


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


def _target_db_path(target_id: str) -> Path:
    """目标 state.db 路径: {data_dir}/{target_id}/state.db"""
    return _data_dir / target_id / "state.db"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static"


def _load_static_manifest_template(static_dir: Path) -> dict[str, Any]:
    fallback = {
        "build": "development",
        "cacheName": "news-sentry-development",
        "assets": ["/", "/index.html", "/app.js", "/style.css", "/public.css", "/sw.js"],
    }
    manifest_path = static_dir / "build_manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    assets = data.get("assets")
    if not isinstance(assets, list) or not assets:
        assets = fallback["assets"]
    clean_assets = [str(asset) for asset in assets if str(asset)]
    build = str(data.get("build") or fallback["build"])
    return {
        "build": build,
        "cacheName": str(data.get("cacheName") or f"news-sentry-{build}"),
        "assets": clean_assets,
    }


def _static_asset_path(static_dir: Path, asset: str) -> Path:
    asset_path = asset.split("?", 1)[0].lstrip("/")
    if not asset_path:
        asset_path = "index.html"
    return static_dir / asset_path


def _build_static_manifest(static_dir: Path | None = None) -> dict[str, Any]:
    """生成当前静态资源内容 hash，避免本地服务继续暴露旧 build id。"""
    static_root = static_dir or _static_dir()
    template = _load_static_manifest_template(static_root)
    digest = sha256()
    files_seen = 0
    for asset in template["assets"]:
        if asset.startswith(("http://", "https://")) or asset == "/build_manifest.json":
            continue
        path = _static_asset_path(static_root, asset)
        if not path.is_file():
            continue
        digest.update(asset.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files_seen += 1
    build = digest.hexdigest()[:12] if files_seen else str(template["build"])
    return {
        "build": build,
        "cacheName": f"news-sentry-{build}",
        "assets": template["assets"],
    }


def _index_html_response() -> HTMLResponse:
    index_path = _static_dir() / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Static asset not found")
    nonce = secrets.token_urlsafe(16)
    html = index_path.read_text(encoding="utf-8").replace("__CSP_NONCE__", nonce)
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": "no-cache",
        },
    )


def _publication_json_ld_script(data: dict[str, Any], *, nonce: str) -> str:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script nonce="{nonce}" type="application/ld+json">{body}</script>'


def _publication_nav() -> str:
    links = [
        ("/", "新闻哨兵", "Breaking News"),
        ("/public-app/?channel=all", "新闻纵览", "All News"),
        ("/public-app/daily", "新闻日报", "Daily News"),
        ("/public-app/agent", "Agent", ""),
        ("/public-app/update", "Update", ""),
    ]
    return "\n".join(
        (
            f'<a class="side-link" href="{html_escape(href, quote=True)}">'
            f"<span>{html_escape(label)}</span>"
            f"{f'<small>{html_escape(sublabel)}</small>' if sublabel else ''}"
            "</a>"
        )
        for href, label, sublabel in links
    )


def _publication_sidebar() -> str:
    return f"""
      <aside class="sidebar" aria-label="公共站侧边栏">
        <a class="sidebar-brand" href="/" aria-label="News Sentry 首页">
          <span>News</span><strong>Sentry</strong>
        </a>
        <nav aria-label="公开站点导航">
          {_publication_nav()}
        </nav>
        <div class="sidebar-footer">
          <a href="/about">关于 About</a>
          <a href="/method">方法论 Method</a>
          <a href="/sources">来源 Sources</a>
          <a href="/subscribe">订阅 Subscribe</a>
        </div>
      </aside>
    """


def _publication_styles() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #172033;
      --muted: #5d6678;
      --line: #d9dee8;
      --panel: #f7f9fc;
      --paper: #ffffff;
      --brand: #8f1d2c;
      --brand-strong: #721523;
      --brand-soft: rgba(143, 29, 44, 0.1);
      --brand-border: rgba(143, 29, 44, 0.24);
      --amber: #a15c00;
      --page-pad: clamp(16px, 2.4vw, 36px);
      font-family: Inter, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-size: 16px;
      line-height: 1.65;
    }
    a { color: inherit; text-decoration: none; }
    .site-header {
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .bar, main, .site-footer {
      width: 100%;
      max-width: none;
      margin: 0;
    }
    .bar {
      min-height: 68px;
      padding-left: var(--page-pad);
      padding-right: var(--page-pad);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-weight: 760;
      letter-spacing: 0;
      white-space: nowrap;
    }
    .brand img { width: 30px; height: 30px; }
    nav {
      display: flex;
      align-items: center;
      gap: 18px;
      color: var(--muted);
      font-size: 14px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    nav a:hover { color: var(--brand); }
    .hero {
      padding: 52px var(--page-pad) 28px;
      display: grid;
      grid-template-columns: minmax(0, 1.18fr) minmax(380px, 0.82fr);
      gap: 32px;
      align-items: start;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow {
      margin: 0 0 10px;
      color: var(--brand);
      font-size: 14px;
      font-weight: 720;
    }
    h1 {
      margin: 0;
      max-width: 760px;
      font-size: clamp(34px, 5vw, 64px);
      line-height: 1.05;
      letter-spacing: 0;
    }
    h2 {
      margin: 0 0 16px;
      font-size: 25px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    h3 {
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.3;
      letter-spacing: 0;
    }
    p { margin: 0; }
    .lede {
      margin-top: 18px;
      max-width: 720px;
      color: var(--muted);
      font-size: 18px;
    }
    .meta-row {
      margin-top: 22px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 14px;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      background: var(--panel);
    }
    .actions { margin-top: 26px; display: flex; gap: 12px; flex-wrap: wrap; }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 0 16px;
      border-radius: 6px;
      border: 1px solid var(--line);
      font-weight: 680;
    }
    .button.primary {
      color: #fff;
      background: var(--brand);
      border-color: var(--brand);
    }
    .headline, .signal, .trust-panel, .target {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
    }
    .headline { padding: 22px; box-shadow: 0 14px 36px rgba(23, 32, 51, 0.08); }
    .badge-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 0 8px;
      border-radius: 5px;
      background: #f9e9ec;
      color: var(--brand-strong);
      font-size: 12px;
      font-weight: 740;
    }
    .badge.level { background: #fff4df; color: var(--amber); }
    .section {
      padding: 34px var(--page-pad);
      border-bottom: 1px solid var(--line);
    }
    .reader-home {
      padding: 22px var(--page-pad) 40px;
    }
    .reader-intro {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--line);
    }
    .reader-intro h1 {
      max-width: 760px;
      font-size: clamp(30px, 4vw, 48px);
      line-height: 1.08;
    }
    .reader-intro .lede {
      max-width: 760px;
      font-size: 16px;
    }
    .reader-section {
      padding: 28px 0 0;
    }
    .hotspot-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }
    .latest-list {
      display: grid;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--paper);
    }
    .latest-list .signal {
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
    }
    .latest-list .signal:last-child {
      border-bottom: 0;
    }
    .section-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }
    .section-head p { color: var(--muted); max-width: 640px; }
    .signal-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
    }
    .signal { padding: 18px; }
    .signal dl {
      margin: 14px 0 0;
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 6px 12px;
      color: var(--muted);
      font-size: 14px;
    }
    .signal dt { color: var(--ink); font-weight: 700; }
    .signal dd { margin: 0; overflow-wrap: anywhere; }
    .signal a { color: var(--brand); }
    .targets {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .target { padding: 16px; background: var(--panel); }
    .target strong { display: block; margin-bottom: 6px; }
    .target p { color: var(--muted); font-size: 14px; }
    .trust-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }
    .trust-panel { padding: 16px; min-height: 150px; }
    .trust-panel p { color: var(--muted); font-size: 14px; }
    .trust-panel a { color: var(--brand); font-weight: 700; }
    .note {
      margin-top: 18px;
      padding: 14px 16px;
      border-left: 4px solid var(--brand);
      background: #f9e9ec;
      color: var(--brand-strong);
      font-size: 14px;
    }
    .site-footer {
      padding: 28px var(--page-pad) 44px;
      color: var(--muted);
      font-size: 14px;
    }
    .publication-shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      background: #f8fafc;
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 12px;
      padding: 12px 8px;
      background: #070b14;
      color: #f1f5f9;
      border-right: 1px solid rgba(255, 255, 255, 0.08);
    }
    .sidebar-brand {
      min-height: 52px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 3px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.035);
      font-size: 18px;
      font-weight: 850;
      letter-spacing: 0;
    }
    .sidebar-brand strong { color: var(--brand); }
    .sidebar nav {
      display: grid;
      align-content: start;
      gap: 4px;
      color: #64748b;
      font-size: 13px;
    }
    .side-link {
      display: grid;
      min-height: 36px;
      padding: 7px 10px;
      border-radius: 8px;
      font-weight: 650;
    }
    .side-link:hover,
    .side-link:first-child {
      color: var(--brand);
      background: var(--brand-soft);
      box-shadow: inset 0 0 0 1px var(--brand-border);
    }
    .side-link small {
      color: inherit;
      opacity: 0.72;
      font-size: 11px;
      font-weight: 500;
    }
    .sidebar-footer {
      display: grid;
      gap: 4px;
      padding: 8px;
      color: #64748b;
      font-size: 12px;
    }
    .sidebar-footer a:hover { color: var(--brand); }
    .app-main {
      min-width: 0;
      padding: 16px clamp(12px, 1.6vw, 24px) 36px;
    }
    .page-theme {
      display: grid;
      gap: 12px;
    }
    .feed-hero,
    .hot-panel,
    .timeline-panel,
    .trust-page.panel {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper);
      box-shadow: none;
    }
    .feed-hero {
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .feed-hero h1 {
      font-size: clamp(30px, 4vw, 46px);
      max-width: none;
    }
    .hero-row {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .segmented {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .segmented::-webkit-scrollbar { display: none; }
    .segmented a,
    .search-pill {
      min-height: 32px;
      padding: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      background: var(--panel);
      font-size: 13px;
      white-space: nowrap;
    }
    .segmented a:first-child {
      color: var(--brand);
      border-color: var(--brand-border);
      background: var(--brand-soft);
    }
    .hot-panel,
    .timeline-panel { padding: 12px 14px; }
    .hot-list {
      display: grid;
      gap: 6px;
      margin-top: 8px;
    }
    .hot-item {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 7px 0;
      border-top: 1px solid var(--line);
    }
    .hot-rank { color: var(--brand); font-weight: 800; }
    .hot-title {
      font-weight: 740;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .hot-meta { color: var(--muted); font-size: 13px; }
    .timeline-day {
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 740;
    }
    .timeline-row {
      display: grid;
      grid-template-columns: 58px 12px minmax(0, 1fr);
      gap: 10px;
      margin-top: 8px;
    }
    .timeline-time {
      padding-top: 12px;
      color: var(--muted);
      font-weight: 760;
    }
    .timeline-dot {
      margin-top: 16px;
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--brand);
      box-shadow: 0 0 0 3px var(--brand-soft);
    }
    .timeline-card {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper);
    }
    .timeline-card h3 { margin-bottom: 8px; }
    .timeline-card p { color: var(--muted); }
    .recommendation {
      margin-top: 8px;
      padding: 8px 10px;
      border: 1px solid var(--brand-border);
      border-radius: 6px;
      background: var(--brand-soft);
      color: var(--muted);
      font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --ink: #f1f5f9;
        --muted: #94a3b8;
        --line: rgba(148, 163, 184, 0.2);
        --panel: rgba(15, 23, 42, 0.72);
        --paper: #111827;
        --brand: #d45b67;
        --brand-strong: #f0a0a9;
        --brand-soft: rgba(212, 91, 103, 0.14);
        --brand-border: rgba(212, 91, 103, 0.28);
        background: #080d18;
      }
      body { background: #080d18; }
      .publication-shell { background: #080d18; }
      .feed-hero,
      .hot-panel,
      .timeline-panel,
      .trust-page.panel {
        box-shadow: none;
      }
    }
    .trust-page {
      padding: 46px var(--page-pad);
      max-width: none;
    }
    .trust-page > .eyebrow,
    .trust-page > h1,
    .trust-page > .lede,
    .trust-page > ul,
    .trust-page > .actions {
      max-width: 880px;
    }
    .trust-page ul { margin: 22px 0; padding-left: 20px; }
    .trust-page li { margin-bottom: 10px; }
    .subscription-box {
      margin-top: 22px;
      max-width: 960px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      display: flex;
      align-items: end;
      gap: 12px;
      flex-wrap: wrap;
    }
    .subscription-box label,
    .subscription-box p {
      flex-basis: 100%;
    }
    .subscription-box input {
      width: min(360px, 100%);
      min-height: 42px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
      background: #fff;
    }
    @media (max-width: 900px) {
      .bar {
        align-items: flex-start;
        flex-direction: column;
        padding-top: 16px;
        padding-bottom: 16px;
      }
      nav { justify-content: flex-start; gap: 12px; }
      .hero, .signal-grid, .targets, .trust-grid { grid-template-columns: 1fr; }
      .hero { padding-top: 34px; }
      .reader-intro { align-items: flex-start; flex-direction: column; }
      .section-head { align-items: flex-start; flex-direction: column; }
      .subscription-box { align-items: stretch; }
      .publication-shell {
        display: block;
        max-width: 100%;
        overflow-x: hidden;
      }
      .sidebar {
        position: sticky;
        top: 0;
        z-index: 20;
        height: auto;
        max-width: 100%;
        grid-template-columns: auto minmax(0, 1fr);
        grid-template-rows: auto;
        align-items: center;
        padding: 10px var(--page-pad);
        overflow: hidden;
      }
      .sidebar-brand {
        min-height: 44px;
        padding: 0 12px;
        border-radius: 14px;
        font-size: 15px;
        white-space: nowrap;
      }
      .sidebar nav {
        display: flex;
        min-width: 0;
        overflow-x: auto;
        overscroll-behavior-x: contain;
        scrollbar-width: none;
      }
      .sidebar nav::-webkit-scrollbar { display: none; }
      .side-link {
        min-width: max-content;
        min-height: 36px;
        padding: 7px 10px;
      }
      .sidebar-footer { display: none; }
      .app-main { padding: 10px var(--page-pad) 34px; }
      .page-theme { gap: 10px; }
      .feed-hero {
        padding: 10px;
        gap: 8px;
      }
      .feed-hero h1 {
        font-size: clamp(22px, 7vw, 30px);
      }
      .feed-hero .lede,
      .search-pill {
        display: none;
      }
      .feed-hero,
      .hot-panel,
      .timeline-panel,
      .timeline-card {
        max-width: 100%;
        min-width: 0;
      }
      .hot-panel,
      .timeline-panel {
        padding: 10px;
      }
      .hot-list {
        gap: 0;
        margin-top: 6px;
      }
      .hot-item {
        grid-template-columns: 24px minmax(0, 1fr);
        gap: 8px;
        padding: 6px 0;
      }
      .hot-meta {
        grid-column: 2;
        font-size: 12px;
      }
      .timeline-row { grid-template-columns: 1fr; }
      .timeline-time, .timeline-dot { display: none; }
      .timeline-card h3,
      .timeline-card p,
      .hot-title {
        overflow-wrap: anywhere;
      }
    }
    """


def _publication_signal_card(signal: dict[str, str], *, index: int = 0) -> str:
    label = html_escape(signal["label"])
    level = html_escape(signal["level"])
    title = html_escape(signal["title"])
    judgment = html_escape(signal["judgment"])
    source = html_escape(signal["source"])
    source_url = html_escape(signal["source_url"], quote=True)
    source_time = html_escape(signal["source_time"])
    captured_time = html_escape(signal["captured_time"])
    impact = html_escape(signal["impact"])
    watch_next = html_escape(signal["watch_next"])
    display_time = source_time.split(" ")[-1] if " " in source_time else source_time
    return f"""
      <div class="timeline-row">
        <time class="timeline-time">{html_escape(display_time)}</time>
        <span class="timeline-dot" aria-hidden="true"></span>
        <article class="timeline-card">
          <div class="badge-row">
            <span class="badge level">精选 {level}</span>
            <span class="badge">{label}</span>
            <span class="badge">TOP {index}</span>
          </div>
          <h3>{title}</h3>
          <p>{judgment}</p>
          <div class="recommendation"><strong>推荐理由：</strong>{judgment}</div>
          <dl>
            <dt>事实来源</dt>
            <dd><a href="{source_url}" rel="nofollow noopener">{source}</a></dd>
            <dt>原文时间</dt>
            <dd>{source_time}</dd>
            <dt>本站更新</dt>
            <dd>{captured_time}</dd>
            <dt>影响对象</dt>
            <dd>{impact}</dd>
            <dt>继续观察</dt>
            <dd>{watch_next}</dd>
          </dl>
        </article>
      </div>
    """


def _publication_hot_item(signal: dict[str, str], *, index: int) -> str:
    title = html_escape(signal["title"])
    source = html_escape(signal["source"])
    source_time = html_escape(signal["source_time"])
    source_url = html_escape(signal["source_url"], quote=True)
    return f"""
      <a class="hot-item" href="{source_url}" rel="nofollow noopener">
        <span class="hot-rank">{index}</span>
        <span class="hot-title">{title}</span>
        <span class="hot-meta">{source} · {source_time}</span>
      </a>
    """


def _publication_base_head(
    *,
    title: str,
    description: str,
    canonical_url: str,
    nonce: str,
    json_ld: dict[str, Any],
) -> str:
    escaped_title = html_escape(title)
    escaped_description = html_escape(description)
    escaped_canonical = html_escape(canonical_url, quote=True)
    return f"""
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escaped_title}</title>
  <meta name="description" content="{escaped_description}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{escaped_canonical}">
  <link rel="icon" href="/icons/icon-192.svg" type="image/svg+xml">
  <meta name="theme-color" content="#ffffff">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="News Sentry">
  <meta property="og:title" content="{escaped_title}">
  <meta property="og:description" content="{escaped_description}">
  <meta property="og:url" content="{escaped_canonical}">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="{escaped_title}">
  <meta name="twitter:description" content="{escaped_description}">
  {_publication_json_ld_script(json_ld, nonce=nonce)}
  <style>{_publication_styles()}</style>
    """


def _publication_header() -> str:
    return f"""
  <header class="site-header">
    <div class="bar">
      <a class="brand" href="/" aria-label="News Sentry 首页">
        <img src="/icons/icon-192.svg" alt="" width="30" height="30">
        <span>News Sentry</span>
      </a>
      <nav aria-label="公开站点导航">
        {_publication_nav()}
      </nav>
    </div>
  </header>
    """


def _publication_homepage_response(*, base_url: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    canonical_url = f"{base_url}/"
    updated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": _PUBLICATION_SITE_TITLE,
        "description": _PUBLICATION_SITE_DESCRIPTION,
        "url": canonical_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": "News Sentry",
            "url": canonical_url,
        },
        "about": [
            "cross-border intelligence",
            "China-related signals",
            "policy monitoring",
            "supply chain risk",
        ],
        "hasPart": [
            {
                "@type": "CreativeWork",
                "name": signal["title"],
                "description": signal["judgment"],
            }
            for signal in _PUBLICATION_SAMPLE_SIGNALS
        ],
    }
    head = _publication_base_head(
        title=_PUBLICATION_SITE_TITLE,
        description=_PUBLICATION_SITE_DESCRIPTION,
        canonical_url=canonical_url,
        nonce=nonce,
        json_ld=json_ld,
    )
    hotspot_cards = "\n".join(
        _publication_hot_item(signal, index=index)
        for index, signal in enumerate(_PUBLICATION_SAMPLE_SIGNALS[:3], start=1)
    )
    latest_cards = "\n".join(
        _publication_signal_card(signal, index=index)
        for index, signal in enumerate(_PUBLICATION_SAMPLE_SIGNALS, start=1)
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
{head}
</head>
<body>
  <div class="publication-shell">
    {_publication_sidebar()}
    <main class="app-main">
      <div class="page-theme page-theme-feed">
        <section class="feed-hero" aria-labelledby="publication-title">
          <div class="hero-row">
            <div>
              <p class="eyebrow">跨境观察哨兵</p>
              <h1 id="publication-title">新闻哨兵</h1>
              <p class="lede">
                Breaking News · AI 辅助从公共新闻流中筛出重大、时效性高、
                对中国企业和跨境业务有影响的新闻信号。
              </p>
            </div>
            <div class="meta-row">
              <span class="pill">最近更新时间：{html_escape(updated_at)}</span>
              <span class="pill">样例信号已标注来源</span>
            </div>
          </div>
          <div class="hero-row">
            <div class="segmented" aria-label="频道筛选">
              <a href="/">全部</a>
              <a href="/public-app/?category=policy">政策</a>
              <a href="/public-app/?category=industry">产业</a>
              <a href="/public-app/?category=supply-chain">供应链</a>
              <a href="/public-app/?category=market">市场准入</a>
            </div>
            <a class="search-pill" href="/public-app/">搜索标题/摘要...</a>
          </div>
        </section>

        <section class="hot-panel" id="today-hotspots">
          <div class="section-head">
            <div>
              <p class="eyebrow">Hot Signals</p>
              <h2>当前热点</h2>
            </div>
            <p>多来源重要度 · 随时间衰减</p>
          </div>
          <div class="hot-list">{hotspot_cards}</div>
        </section>

        <section class="timeline-panel" id="latest">
          <div class="section-head">
            <div>
              <p class="eyebrow">Timeline</p>
              <h2>新闻时间线</h2>
            </div>
            <p>按日期分组，快速扫读来源、分值、摘要和推荐理由。</p>
          </div>
          <div class="timeline-day">今天</div>
          {latest_cards}
        </section>
      </div>
    </main>
  </div>
</body>
</html>
"""
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": "no-cache",
        },
    )


def _publication_trust_page_response(*, page: str, base_url: str) -> HTMLResponse:
    content = _PUBLICATION_TRUST_PAGES.get(page)
    if content is None:
        raise HTTPException(status_code=404, detail="Trust page not found")
    nonce = secrets.token_urlsafe(16)
    path = f"/{page}"
    canonical_url = f"{base_url}{path}"
    title = f"{content['title']} | News Sentry"
    intro = str(content["intro"])
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": intro,
        "url": canonical_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": "News Sentry",
            "url": f"{base_url}/",
        },
    }
    head = _publication_base_head(
        title=title,
        description=intro,
        canonical_url=canonical_url,
        nonce=nonce,
        json_ld=json_ld,
    )
    points = "\n".join(
        f"<li>{html_escape(str(point))}</li>" for point in cast(list[Any], content["points"])
    )
    subscribe_extra = ""
    if page == "subscribe":
        subscribe_extra = """
        <div class="subscription-box">
          <label for="email">邮件订阅入口</label>
          <p>订阅数据模型会在 P2 接入；P0 先固定公开入口和内容承诺。</p>
          <input id="email" type="email" name="email" placeholder="you@example.com">
          <a class="button primary" href="/public-app/">先浏览今日信号</a>
        </div>
        """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
{head}
</head>
<body>
  <div class="publication-shell">
    {_publication_sidebar()}
    <main class="app-main">
      <section class="trust-page panel">
        <p class="eyebrow">{html_escape(str(content["eyebrow"]))}</p>
        <h1>{html_escape(str(content["title"]))}</h1>
        <p class="lede">{html_escape(intro)}</p>
        <ul>{points}</ul>
        {subscribe_extra}
        <div class="actions">
          <a class="button primary" href="/public-app/">进入今日信号</a>
          <a class="button" href="/">回到首页</a>
        </div>
      </section>
      <footer class="site-footer">
        News Sentry · {html_escape(str(content["needle"]))} ·
        <a href="/sources">来源</a> · <a href="/method">方法论</a>
      </footer>
    </main>
  </div>
</body>
</html>
"""
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": "no-cache",
        },
    )


def _public_app_dir(static_dir: Path | None = None) -> Path:
    return (static_dir or _static_dir()) / "public_app"


def _frontend_public_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "public" / "public"


def _public_discoverability_asset_path(filename: str) -> Path:
    candidates = (
        _frontend_public_dir() / filename,
        _static_dir() / filename,
        _public_app_dir() / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail=f"{filename} not found")


def _public_discoverability_text(filename: str) -> str:
    return _public_discoverability_asset_path(filename).read_text(encoding="utf-8")


def _public_site_base_url(request: Request | None = None) -> str:
    configured = os.environ.get("NEWSSENTRY_PUBLIC_SITE_BASE_URL")
    if configured:
        return configured.rstrip("/")
    if request is not None:
        host = request.headers.get("host", "").strip().lower()
        if host in {"news-sentry.com", "preview.news-sentry.com"}:
            return f"{request.url.scheme}://{host}"
    return _PUBLIC_SITE_BASE_URL.rstrip("/")


async def _render_public_sitemap_xml(store: Any, *, base_url: str) -> str:
    entries = await _public_sitemap_entries(base_url=base_url)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in entries:
        lines.extend(
            [
                "  <url>",
                f"    <loc>{xml_escape(entry.loc)}</loc>",
                f"    <lastmod>{xml_escape(entry.lastmod)}</lastmod>",
                "  </url>",
            ]
        )
    lines.append("</urlset>")
    return "\n".join(lines)


async def _public_sitemap_entries(*, base_url: str) -> list[Any]:
    entries: list[Any] = []
    for target_id in _public_news_target_ids(_data_dir, None):
        store = await _store_for_target(target_id)
        if store is None:
            continue
        projection_store = PublicSiteProjectionStore(store, base_url=base_url)
        entries.extend(await projection_store.list_sitemap_entries(target_id=target_id, limit=1000))
    if not entries and _store is not None:
        projection_store = PublicSiteProjectionStore(_store, base_url=base_url)
        entries = await projection_store.list_sitemap_entries(limit=1000)
    if entries:
        return entries
    return [
        SitemapEntry(
            loc=f"{base_url}/",
            lastmod=datetime.now(UTC).isoformat(),
        )
    ]


def _inject_public_homepage_seo(html: str, *, base_url: str) -> str:
    canonical_url = f"{base_url}/public-app/"
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "News Sentry Public",
            "description": _PUBLIC_SITE_DESCRIPTION,
            "url": canonical_url,
            "isPartOf": {
                "@type": "WebSite",
                "name": _PUBLIC_SITE_NAME,
                "url": canonical_url,
            },
        },
        ensure_ascii=False,
    )
    tags: list[str] = []
    if 'rel="canonical"' not in html:
        tags.append(f'    <link rel="canonical" href="{canonical_url}" />')
    if 'property="og:url"' not in html:
        tags.append(f'    <meta property="og:url" content="{canonical_url}" />')
    if "application/ld+json" not in html:
        tags.append(f'    <script type="application/ld+json">{json_ld}</script>')
    if not tags or "</head>" not in html:
        return html
    return html.replace("</head>", "\n" + "\n".join(tags) + "\n  </head>", 1)


def _public_app_index_response(*, base_url: str | None = None) -> HTMLResponse:
    index_path = _public_app_dir() / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Public app not built")
    nonce = secrets.token_urlsafe(16)
    html = index_path.read_text(encoding="utf-8")
    if base_url:
        html = _inject_public_homepage_seo(html, base_url=base_url)
    html = _inject_script_nonce(html, nonce)
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": "no-cache",
        },
    )


def _public_app_asset_response(asset_path: str) -> Response:
    public_root = _public_app_dir().resolve()
    clean_asset_path = asset_path.strip("/")
    if not clean_asset_path:
        return _public_app_index_response()
    file_path = (public_root / clean_asset_path).resolve()
    try:
        file_path.relative_to(public_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Static asset not found") from None
    if file_path.is_file():
        cache_control = (
            "public, max-age=31536000, immutable"
            if clean_asset_path.startswith("assets/")
            else "no-cache"
        )
        return FileResponse(file_path, headers={"Cache-Control": cache_control})
    if clean_asset_path.startswith("assets/"):
        raise HTTPException(status_code=404, detail="Static asset not found")
    return _public_app_index_response()


def _git_dir_for_path(path: Path) -> Path | None:
    for parent in [path.resolve(), *path.resolve().parents]:
        dot_git = parent / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            try:
                content = dot_git.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if content.startswith("gitdir:"):
                git_dir = Path(content.split(":", 1)[1].strip())
                return git_dir if git_dir.is_absolute() else (parent / git_dir).resolve()
    return None


def _git_commit_for_path(path: Path) -> str:
    git_dir = _git_dir_for_path(path)
    if git_dir is None:
        return os.environ.get("NEWS_SENTRY_GIT_COMMIT", "unknown")
    try:
        common_dir_path = git_dir / "commondir"
        common_dir = (
            (git_dir / common_dir_path.read_text(encoding="utf-8").strip()).resolve()
            if common_dir_path.is_file()
            else git_dir
        )
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            for ref_path in (git_dir / ref, common_dir / ref):
                if ref_path.is_file():
                    return ref_path.read_text(encoding="utf-8").strip()[:12]
            return "unknown"
        return head[:12]
    except OSError:
        return os.environ.get("NEWS_SENTRY_GIT_COMMIT", "unknown")


async def _get_target_store(target_id: str) -> AsyncStore | None:
    """获取 target 对应的 AsyncStore（优先使用 pipeline 的 state.db）。

    缓存已打开的 store，避免重复初始化。
    """
    db_path = _target_db_path(target_id)
    if target_id in _target_stores:
        cached = _target_stores[target_id]
        if cached.db_path == db_path:
            return cached
        try:
            await cached.close()
        except Exception:  # noqa: S110
            pass
        _target_stores.pop(target_id, None)

    if db_path.exists():
        store = AsyncStore(db_path)
        await store.initialize()
        _target_stores[target_id] = store
        logger.debug("Opened target store: %s", db_path)
        return store

    return None


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
    await _close_target_stores()


# ── FastAPI 应用 ────────────────────────────────────────


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

    global _store, _data_dir
    if _store is not None and _store is not store:
        _close_store_sync_if_possible(_store)
    if _target_stores:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_close_target_stores())
    _data_dir = Path(data_dir or os.environ.get("NEWSSENTRY_DATA_DIR", "./data"))
    _public_news_feed_cache.clear()
    _public_source_configs_cache.clear()
    _detect_deployment_env()
    if store is not None:
        _store = store
    elif _store is None and auto_store:
        _store = AsyncStore(_data_dir / "async_store.db")
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
    _config_cache = ConfigCache(ttl=60, maxsize=128)
    _apply_collector_config(_load_collector_config())
    _apply_ai_enrichment_config(_load_ai_enrichment_config())
    _apply_public_translation_config(_load_public_translation_config())

    # ── 公开端点（无需认证）─────────────────────────────

    @app.get("/api/v1/health")
    async def health(response: Response) -> dict[str, str]:
        manifest = _build_static_manifest()
        commit = _git_commit_for_path(Path(__file__))
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-News-Sentry-Deploy-Commit"] = (
            commit[:12] if commit != "unknown" else commit
        )
        response.headers["X-News-Sentry-Static-Build"] = manifest["build"]
        return {"status": "ok"}

    @app.get("/api/v1/runtime/info")
    async def runtime_info(
        response: Response,
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        manifest = _build_static_manifest()
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "static_build": manifest["build"],
            "static_cache_name": manifest["cacheName"],
        }

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def index_html(request: Request) -> HTMLResponse:
        return _publication_homepage_response(base_url=_public_site_base_url(request))

    @app.get("/about", include_in_schema=False)
    @app.get("/method", include_in_schema=False)
    @app.get("/sources", include_in_schema=False)
    @app.get("/subscribe", include_in_schema=False)
    async def publication_trust_page(request: Request) -> HTMLResponse:
        page = request.url.path.strip("/")
        return _publication_trust_page_response(page=page, base_url=_public_site_base_url(request))

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def admin_index_html() -> HTMLResponse:
        return _index_html_response()

    @app.get("/admin/{path:path}", include_in_schema=False)
    async def admin_path_html(path: str) -> HTMLResponse:
        _ = path
        return _index_html_response()

    @app.get("/build_manifest.json")
    async def build_manifest(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return _build_static_manifest()

    @app.get("/robots.txt", include_in_schema=False)
    async def robots_txt(request: Request) -> PlainTextResponse:
        base_url = _public_site_base_url(request)
        body = _public_discoverability_text("robots.txt").replace(
            f"{_PUBLIC_SITE_BASE_URL}/sitemap.xml",
            f"{base_url}/sitemap.xml",
        )
        return PlainTextResponse(
            body,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/llms.txt", include_in_schema=False)
    async def llms_txt() -> PlainTextResponse:
        return PlainTextResponse(
            _public_discoverability_text("llms.txt"),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap_xml(request: Request) -> Response:
        xml = await _render_public_sitemap_xml(
            _store,
            base_url=_public_site_base_url(request),
        )
        return Response(
            content=xml,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/app.js", include_in_schema=False)
    async def app_script() -> FileResponse:
        app_js_path = _static_dir() / "app.js"
        if not app_js_path.is_file():
            raise HTTPException(status_code=404, detail="Static asset not found")
        return FileResponse(
            app_js_path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/public.css", include_in_schema=False)
    async def public_stylesheet() -> FileResponse:
        public_css_path = _static_dir() / "public.css"
        if not public_css_path.is_file():
            raise HTTPException(status_code=404, detail="Static asset not found")
        return FileResponse(
            public_css_path,
            media_type="text/css",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker_script() -> FileResponse:
        sw_path = _static_dir() / "sw.js"
        if not sw_path.is_file():
            raise HTTPException(status_code=404, detail="Service worker not found")
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.api_route("/public-app", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/public-app/", methods=["GET", "HEAD"], include_in_schema=False)
    async def public_app_index(request: Request) -> HTMLResponse:
        return _public_app_index_response(base_url=_public_site_base_url(request))

    @app.api_route(
        "/public-app/{asset_path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def public_app_asset(asset_path: str, request: Request) -> Response:
        if not asset_path.strip("/"):
            return _public_app_index_response(base_url=_public_site_base_url(request))
        return _public_app_asset_response(asset_path)

    @app.get("/api/v1/collector/status")
    async def collector_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回后台自动采集循环的状态。"""
        return _collector_payload()

    @app.get("/api/v1/collector/config")
    async def collector_config(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回可编辑的自动采集配置与当前运行状态。"""
        return _collector_payload()

    @app.put("/api/v1/collector/config")
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

    @app.post("/api/v1/collector/start")
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

    @app.post("/api/v1/collector/stop")
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

    @app.get("/api/v1/collector/diagnostics")
    async def collector_diagnostics(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回采集系统诊断信息，帮助排查"无数据"问题。"""
        return _cached_collector_diagnostics_payload()

    @app.get("/api/v1/ai/enrichment/status")
    async def ai_enrichment_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回低频 AI 增强 worker 状态、额度和冷却信息。"""
        return await _ai_enrichment_status_payload()

    @app.put("/api/v1/ai/enrichment/config")
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

    @app.post("/api/v1/ai/enrichment/run")
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

    @app.get("/api/v1/ai/translation/status")
    async def public_translation_status(
        _user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回公共站翻译 worker 状态。"""
        return await _public_translation_status_payload()

    @app.put("/api/v1/ai/translation/config")
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

    @app.post("/api/v1/ai/translation/run")
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

    @app.get("/api/v1/status")
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

        result = await _create_persistent_token_for_user(
            username,
            user["role"],
            bool(user.get("api_key")),
        )
        result["must_change_password"] = bool(user.get("must_change_pw", 0))
        return result

    @app.post("/api/v1/auth/token")
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

    @app.post("/api/v1/auth/stream-token")
    async def auth_stream_token(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """为 EventSource 连接创建短期 token，避免把主 bearer 放进 URL。"""
        return _create_stream_token_for_user(user["username"], user["role"])

    @app.get("/api/v1/auth/me")
    async def auth_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        """返回当前用户信息。"""
        return {
            "username": user["username"],
            "role": user["role"],
            "permissions": sorted(_PERMISSIONS.get(user["role"], set())),
            "has_api_key": user.get("has_api_key", False),
        }

    @app.post("/api/v1/auth/logout")
    async def auth_logout(request: Request) -> dict[str, str]:
        """注销当前 token（内存 + SQLite 双删）。"""
        token = _extract_bearer_token(request)
        if token:
            _TOKEN_STORE.pop(token, None)
            if _store is not None:
                await _store.delete_session(token)
        return {"status": "ok"}

    @app.post("/api/v1/auth/change-password")
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

    @app.get("/api/v1/auth/setup-status")
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

    @app.post("/api/v1/auth/setup")
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

    @app.get("/api/v1/admin/users")
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

    @app.post("/api/v1/admin/users")
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
        return {"status": "ok", "username": username}

    @app.delete("/api/v1/admin/users/{username}")
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
        return {"status": "ok"}

    @app.post("/api/v1/admin/users/{username}/reset-password")
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
        return {"status": "ok"}

    # ── API Key 设置 ─────────────────────────────────────

    @app.get("/api/v1/settings/api-key")
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

    @app.put("/api/v1/settings/api-key")
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

    @app.delete("/api/v1/settings/api-key")
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

    @app.get("/api/v1/settings/notifications")
    async def get_notifications(
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """获取通知渠道配置。"""
        return await _load_notifications()

    @app.put("/api/v1/settings/notifications")
    async def update_notifications(
        request: Request,
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, str]:
        """更新通知渠道配置。"""
        body = await request.json()
        await _save_notifications(body)
        return {"status": "ok"}

    # ── 简报邮件发送 ──────────────────────────────────────

    @app.post("/api/v1/briefing/send")
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

    @app.get("/api/v1/targets", response_model=TargetListResponse)
    async def list_targets() -> TargetListResponse:
        """返回公开可浏览的 active target 列表。"""
        configs = _load_target_configs()
        targets = []
        for config in configs:
            if _target_is_archived(config):
                continue
            target = await _target_info_from_config_for_response(config, _data_dir)
            if target.source_count <= 0 or target.event_count <= 0:
                continue
            targets.append(target)
        return TargetListResponse(targets=targets)

    @app.get("/api/v1/admin/targets")
    async def list_admin_targets(
        include_archived: bool = Query(False, description="是否包含已归档 target"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """管理后台 target 全生命周期列表。"""
        configs = _load_target_configs()
        targets = []
        for config in configs:
            if not include_archived and _target_is_archived(config):
                continue
            target = await _target_info_from_config_for_response(config, _data_dir)
            targets.append(target.model_dump())
        return {"targets": targets}

    @app.post("/api/v1/admin/targets")
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
                topic_label=payload.topic_label,
            )
            _atomic_write_yaml(
                _source_config_path(payload.target_id, "rss-template"),
                _default_template_source(payload.target_id),
            )
            _atomic_write_yaml(
                Path("config/filters") / payload.target_id / "default.yaml",
                _default_filter_config(payload.target_id),
            )
            _atomic_write_yaml(
                Path("config/classification") / f"rules-{payload.target_id}.yaml",
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
                monitoring_type=payload.monitoring_type or _target_monitoring_type(source_target),
                topic_label=payload.topic_label or _target_topic_label(source_target),
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
        return _target_info_from_config(target_data, _data_dir).model_dump()

    @app.patch("/api/v1/admin/targets/{target_id}")
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
        if data.get("monitoring_type") != "topic" or not data.get("topic_label"):
            data.pop("topic_label", None)
        _atomic_write_yaml(_target_config_path(target_id), data)
        _config_cache.clear()
        return data

    @app.post("/api/v1/admin/targets/{target_id}/archive")
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
        return data

    @app.post("/api/v1/admin/targets/{target_id}/restore")
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
        return data

    @app.get("/api/v1/admin/targets/{target_id}/overview")
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
            if item.get("type") in {"rss", "api", "opencli"} and not item.get("missing_file")
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

    @app.post("/api/v1/admin/targets/{target_id}/validate")
    async def validate_admin_target(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """预检 target 配置链路。"""
        return _cached_target_validation(target_id)

    @app.get("/api/v1/admin/targets/{target_id}/inventory")
    async def admin_target_inventory(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """返回 target 信源统一对账视图。"""
        _ensure_target_exists(target_id)
        return _cached_source_inventory(target_id)

    @app.get("/api/v1/admin/targets/{target_id}/sources")
    async def list_admin_target_sources(
        target_id: str,
        include_archived: bool = Query(False, description="是否包含已归档信源"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """列出 target 的标准 RSS/API/OpenCLI 信源。"""
        _ensure_target_exists(target_id)
        sources = []
        for source in _load_source_configs(target_id):
            if not _source_is_standard(source):
                continue
            if not include_archived and _source_is_archived(source):
                continue
            sources.append(_source_info_from_config(source).model_dump())
        return {"target_id": target_id, "sources": sources}

    @app.post("/api/v1/admin/targets/{target_id}/sources")
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
        return _source_info_from_config(data).model_dump()

    @app.patch("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}")
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
        return _source_info_from_config(data).model_dump()

    @app.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/archive")
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
        return _source_info_from_config(data).model_dump()

    @app.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/restore")
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
        return _source_info_from_config(data).model_dump()

    @app.get("/api/v1/admin/targets/{target_id}/social")
    async def get_admin_target_social(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """读取 target 社媒矩阵。"""
        _ensure_target_exists(target_id)
        dimensions = _social_dimensions(target_id)
        return {"target_id": target_id, "dimensions": dimensions}

    @app.post("/api/v1/admin/targets/{target_id}/social/dimensions")
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
        return data

    @app.patch("/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}")
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
        return data

    @app.post("/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts")
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
        return account

    @app.patch("/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts/{handle}")
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
                return account
        raise HTTPException(status_code=404, detail=f"Account '{handle}' not found")

    @app.get("/api/v1/admin/overview")
    async def admin_overview(
        target_id: str | None = Query(None, description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """管理后台总览聚合：目标、采集、诊断、健康、反馈与告警。"""
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
        return {
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

    @app.get(
        "/api/v1/public/targets/{target_id}/analysis",
        response_model=PublicAnalysisResponse,
    )
    async def get_public_target_analysis(
        target_id: str,
        days: Annotated[
            Literal[7, 14, 30],
            Query(description="分析窗口天数"),
            BeforeValidator(int),
        ] = 14,
    ) -> PublicAnalysisResponse:
        """公开匿名只读分析快照。"""
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store
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

        events = _public_events_within_window(_load_all_events(_data_dir, target_id), days)
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

    @app.get("/api/v1/public/news", response_model=PublicNewsFeedResponse)
    async def list_public_news(
        request: Request,
        response: Response,
        featured: bool = Query(False, description="仅返回精选/关注新闻"),
        target_id: str | None = Query(None, description="按 target 筛选"),
        source_id: str | None = Query(None, description="按来源筛选"),
        category: str | None = Query(None, description="按 classification.l0 筛选"),
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
        if before_cursor and since_cursor:
            raise HTTPException(
                status_code=422,
                detail="before_cursor and since_cursor cannot be used together",
            )
        before_key = _public_news_decode_cursor(before_cursor)
        since_key = _public_news_decode_cursor(since_cursor)
        started = time.perf_counter()
        cache_key = _public_news_feed_cache_key(
            featured=featured,
            target_id=target_id,
            source_id=source_id,
            category=category,
            date=date,
            q=q,
            before_cursor=before_cursor,
            since_cursor=since_cursor,
            page_size=page_size,
        )
        now = time.monotonic()
        cache_entry = _public_news_feed_cache.get(cache_key)
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

        target_ids = _public_news_target_ids(_data_dir, target_id)
        allow_projection_first = not any(
            (
                featured,
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
            _data_dir,
            target_ids,
            limit=query_limit,
            allow_projection_first=allow_projection_first,
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
        items = [_public_news_item(tid, event) for tid, event in page_pairs]
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
            has_target=target_id is not None,
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
            _public_news_feed_cache[cache_key] = {
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

    @app.get("/api/v1/public/news/{event_id}", response_model=PublicNewsItem)
    async def get_public_news_item(
        event_id: str,
        target_id: str | None = Query(None, description="可选 target 提示"),
    ) -> PublicNewsItem:
        """公共新闻详情 presentation API，不暴露后台字段。"""
        target_ids = _public_news_target_ids(_data_dir, target_id)
        for tid in target_ids:
            target_store = await _get_target_store(tid)
            stores = [store for store in (target_store, _store) if store is not None]
            for store in stores:
                projection_event = await _load_public_projection_detail(
                    store,
                    target_id=tid,
                    event_id=event_id,
                )
                if isinstance(projection_event, InvisibleIndexedEvent):
                    raise HTTPException(status_code=404, detail="Event not found")
                if projection_event is not None:
                    return _public_news_item(tid, projection_event, include_content=True)
                event = await _load_indexed_event_detail(_data_dir, tid, store, event_id)
                if isinstance(event, InvisibleIndexedEvent):
                    raise HTTPException(status_code=404, detail="Event not found")
                if event is not None and _event_public_translation_ready(event):
                    return _public_news_item(tid, event, include_content=True)
                if target_id and await _store_has_target_event_index(store, tid):
                    raise HTTPException(status_code=404, detail="Event not found")

            event = _load_single_event(_data_dir, tid, event_id)
            if event is not None and _event_public_translation_ready(event):
                return _public_news_item(tid, event, include_content=True)
        raise HTTPException(status_code=404, detail="Event not found")

    @app.get("/api/v1/stats", response_model=StatsResponse)
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

    @app.get("/api/v1/config/targets/{target_id}")
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

    @app.get(
        "/api/v1/config/targets/{target_id}/sources",
        response_model=SourceListResponse,
    )
    async def list_sources(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
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

    @app.get(
        "/api/v1/config/targets/{target_id}/filters",
        response_model=FilterRulesResponse,
    )
    async def get_filter_rules(
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
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
        user: dict[str, Any] = Depends(get_current_user),
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
        user: dict[str, Any] = Depends(get_current_user),
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

    @app.get("/api/v1/entities", response_model=EntityListResponse)
    async def list_entities(
        entity_type: str | None = Query(None, description="按实体类型过滤"),
        target_id: str | None = Query(None, description="按目标过滤"),
        min_mentions: int = Query(1, ge=1, description="最少提及次数"),
        limit: int = Query(20, ge=1, le=100, description="返回数量"),
        sort: str = Query("mention_count", description="排序: mention_count 或 last_seen"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EntityListResponse:
        """返回实体列表（优先使用 target state.db）。"""
        # 如果指定了 target_id，优先使用 target 自己的 state.db
        store_to_query = _store
        if target_id is not None:
            ts = await _get_target_store(target_id)
            if ts is not None:
                store_to_query = ts
        if store_to_query is None:
            return EntityListResponse(total=0, entities=[])
        entities = await store_to_query.query_entities(
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
        user: dict[str, Any] = Depends(get_current_user),
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
        user: dict[str, Any] = Depends(get_current_user),
    ) -> TodayStatsResponse:
        """今日 vs 昨日对比统计。"""
        store_to_query = await _store_for_target(target_id)
        if store_to_query is None:
            return TodayStatsResponse(target_id=target_id)
        stats = await store_to_query.get_today_stats(target_id)
        return TodayStatsResponse(target_id=target_id, **stats)

    @app.get("/api/v1/events/top", response_model=TopEventsResponse)
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
        user: dict[str, Any] = Depends(get_current_user),
    ) -> EventResponse:

        # 优先使用 target 自己的 state.db（与 pipeline 共享同一数据库）
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store

        if store_to_query is not None:
            result = await _visible_index_events_page(
                store_to_query,
                _data_dir,
                stage="drafts",
                target_id=target_id,
                page=page,
                page_size=page_size,
                source_id=source_id,
                classification_l0=classification,
                min_score=min_score,
                sentiment=sentiment,
                entity_name=entity,
                topic_tag=topic_tag,
                search=search,
            )
            # target 已进入索引模式后，SQLite 是权威来源；只有全空 legacy target 才回退。
            if result["index_total"] > 0:
                return EventResponse(
                    total=result["total"],
                    events=result["events"],
                    page=page,
                    page_size=page_size,
                )
            if await _store_has_target_event_index(store_to_query, target_id):
                return EventResponse(total=0, events=[], page=page, page_size=page_size)

        # 降级路径（无 store / store 为空 / 文件系统路径）
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

    # ── 新闻流 Feed API ─────────────────────────────────────

    @app.get("/api/v1/events/feed")
    async def events_feed(
        target_id: str = Query(..., description="目标标识"),
        date: str | None = Query(None, description="日期筛选 YYYY-MM-DD"),
        page: int = Query(1, ge=1),
        page_size: int = Query(30, ge=1, le=100),
    ) -> dict[str, Any]:
        """新闻流接口 — 按日期分组返回事件，含 AI 推荐标签。"""
        target_store = await _get_target_store(target_id)
        store_to_query = target_store if target_store is not None else _store

        if store_to_query is not None:
            result = await _visible_index_events_page(
                store_to_query,
                _data_dir,
                stage="drafts",
                target_id=target_id,
                page=page,
                page_size=page_size,
                date=date,
                exact_total=page_size <= 1,
            )
            if result["index_total"] > 0:
                # 按日期分组
                grouped = _group_events_by_date(result["events"])
                return {
                    "total": result["total"],
                    "page": page,
                    "page_size": page_size,
                    "groups": grouped,
                }
            if await _store_has_target_event_index(store_to_query, target_id):
                return {
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "groups": [],
                }

        # 降级: 文件系统
        all_events_resp = _load_events_from_data(_data_dir, target_id, 1, 1000)
        events = all_events_resp.events
        if date:
            events = [e for e in events if (e.get("published_at") or "").startswith(date)]
        grouped = _group_events_by_date(events)
        return {
            "total": len(events),
            "page": page,
            "page_size": page_size,
            "groups": grouped,
        }

    @app.get("/api/v1/news/target/{target_id}/events/{event_id}/export/markdown")
    async def export_public_event_markdown(
        target_id: str,
        event_id: str,
    ) -> Response:
        """公开单篇新闻 Markdown 下载投影，不写入磁盘。"""
        target_store = await _get_target_store(target_id)
        if target_store is not None:
            event = await _load_indexed_event_detail(
                _data_dir,
                target_id,
                target_store,
                event_id,
            )
            if isinstance(event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if event is not None:
                return _markdown_download_response(
                    f"{event_id}.md",
                    _render_public_event_markdown(target_id, event),
                )
            if await _store_has_target_event_index(target_store, target_id):
                raise HTTPException(status_code=404, detail="Event not found")

        if _store is not None:
            event = await _load_indexed_event_detail(
                _data_dir,
                target_id,
                _store,
                event_id,
            )
            if isinstance(event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if event is not None:
                return _markdown_download_response(
                    f"{event_id}.md",
                    _render_public_event_markdown(target_id, event),
                )
            if await _store_has_target_event_index(_store, target_id):
                raise HTTPException(status_code=404, detail="Event not found")

        event = _load_single_event(_data_dir, target_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return _markdown_download_response(
            f"{event_id}.md",
            _render_public_event_markdown(target_id, event),
        )

    # ── SSE 实时推送 ─────────────────────────────────────

    @app.get("/api/v1/events/stream")
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

    @app.get("/api/v1/events/{event_id}")
    async def get_event(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> dict[str, Any]:

        # 优先使用 target 自己的 state.db
        target_store = await _get_target_store(target_id)
        if target_store is not None:
            event = await _load_indexed_event_detail(
                _data_dir,
                target_id,
                target_store,
                event_id,
            )
            if isinstance(event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if event is not None:
                return event
            if await _store_has_target_event_index(target_store, target_id):
                raise HTTPException(status_code=404, detail="Event not found")

        if _store is not None:
            event = await _load_indexed_event_detail(
                _data_dir,
                target_id,
                _store,
                event_id,
            )
            if isinstance(event, InvisibleIndexedEvent):
                raise HTTPException(status_code=404, detail="Event not found")
            if event is not None:
                return event
            if await _store_has_target_event_index(_store, target_id):
                raise HTTPException(status_code=404, detail="Event not found")

        # 降级路径（无 store / store 中未找到 / 文件系统路径）
        event = _load_single_event(_data_dir, target_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.post("/api/v1/webhook", response_model=WebhookResponse)
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

    @app.post("/api/v1/events/import", response_model=ImportResponse)
    async def import_events(
        events: list[ImportEventItem],
        user: dict[str, Any] = Depends(require_permission("write")),
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
                _validate_target_slug(item.target_id)
                _validate_source_slug(item.source_id)
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

                # SSE 通知
                sse_payload = {"event_id": event_id, "source": "import"}
                asyncio.ensure_future(_notify_sse_clients(item.target_id, "new_event", sse_payload))

                imported += 1
            except Exception as exc:
                errors.append(f"events[{i}]: {exc}")

        return ImportResponse(imported=imported, skipped=skipped, errors=errors)

    @app.post("/api/v1/config/reload")
    async def reload_config(
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, str]:
        """清除配置缓存，下次请求时重新从文件加载。"""
        _config_cache.reload()
        return {"status": "ok", "message": "Configuration cache cleared"}

    # ── Phase 42: 配置写入端点 ────────────────────────────

    @app.put("/api/v1/config/targets/{target_id}")
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

    @app.patch("/api/v1/config/targets/{target_id}/sources/{source_id:path}")
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

    @app.patch("/api/v1/config/targets/{target_id}/filters")
    async def update_filter_config(
        target_id: str,
        body: FilterConfigUpdate,
        user: dict[str, Any] = Depends(require_permission("write")),
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
        user: dict[str, Any] = Depends(require_permission("write")),
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
        user: dict[str, Any] = Depends(require_permission("write")),
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
        user: dict[str, Any] = Depends(get_current_user),
    ) -> RunListResponse:
        runs = _load_run_logs(_data_dir, target_id, limit)
        return RunListResponse(runs=[RunInfo(**r) for r in runs])

    @app.get("/api/v1/runs/active", response_model=HeartbeatResponse)
    async def get_active_run(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> HeartbeatResponse:
        data = _load_heartbeat(_data_dir, target_id)
        return HeartbeatResponse(**data)

    @app.get("/api/v1/runs/{run_id:path}", response_model=RunDetailResponse)
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

    @app.get("/api/v1/sources/health", response_model=SourceHealthListResponse)
    async def list_source_health(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> SourceHealthListResponse:
        records = await _source_health_records_for_target(target_id)
        return SourceHealthListResponse(sources=[SourceHealthInfo(**r) for r in records])

    @app.post("/api/v1/runs/trigger", response_model=TriggerResponse)
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

    @app.get("/api/v1/events/{event_id}/links", response_model=EventLinksResponse)
    async def get_event_links(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
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
        user: dict[str, Any] = Depends(get_current_user),
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
        user: dict[str, Any] = Depends(get_current_user),
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

    @app.post("/api/v1/chains/{root_id}/narrative", response_model=NarrativeResponse)
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

    @app.get("/api/v1/trends/topics", response_model=TopicTrendsResponse)
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

    @app.get("/api/v1/trends/sentiment", response_model=SentimentTrendsResponse)
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

    @app.get("/api/v1/alerts/smart", response_model=SmartAlertsResponse)
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

    @app.get("/api/v1/canonical/diagnostics")
    async def canonical_diagnostics(
        target_id: str,
        since: str | None = None,
        limit: int = Query(500, ge=1, le=5000),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        service = CanonicalProjectionService(store)
        diagnostics = await service.project(
            ProjectionOptions(target_id=target_id, since=since, limit=limit, apply=False)
        )
        return diagnostics.to_dict()

    @app.post("/api/v1/canonical/backfill")
    async def canonical_backfill(
        payload: CanonicalBackfillRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        service = CanonicalProjectionService(store)
        diagnostics = await service.project(
            ProjectionOptions(
                target_id=payload.target_id,
                since=payload.since,
                limit=payload.limit,
                apply=payload.apply,
                projection_run_id=payload.projection_run_id,
            )
        )
        return diagnostics.to_dict()

    @app.get("/api/v1/canonical/events")
    async def list_canonical_events(
        target_id: str,
        limit: int = Query(50, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        events = await store.list_canonical_events(
            target_id=target_id,
            limit=limit,
            offset=offset,
            status=status,
        )
        return {"events": events, "limit": limit, "offset": offset}

    async def _canonical_event_or_404(
        store: AsyncStore,
        canonical_event_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        event = await store.get_canonical_event(canonical_event_id)
        if not event or event.get("target_id") != target_id:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        return event

    @app.get("/api/v1/canonical/events/{canonical_event_id}")
    async def get_canonical_event(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        return await _canonical_event_or_404(store, canonical_event_id, target_id)

    @app.get("/api/v1/canonical/events/{canonical_event_id}/mentions")
    async def list_canonical_event_mentions(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        await _canonical_event_or_404(store, canonical_event_id, target_id)
        mentions = await store.list_event_mentions(canonical_event_id)
        return {"canonical_event_id": canonical_event_id, "mentions": mentions}

    @app.get("/api/v1/canonical/events/{canonical_event_id}/relations")
    async def list_canonical_event_relations(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        await _canonical_event_or_404(store, canonical_event_id, target_id)
        relations = await store.list_canonical_relations(canonical_event_id)
        return {"canonical_event_id": canonical_event_id, "relations": relations}

    @app.get("/api/v1/canonical/events/{canonical_event_id}/export/markdown")
    async def export_canonical_event_markdown(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> Response:
        """导出 canonical event evidence package Markdown，不写入磁盘。"""
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await _canonical_event_or_404(store, canonical_event_id, target_id)
        mentions = await store.list_event_mentions(canonical_event_id)
        relations = await store.list_canonical_relations(canonical_event_id)
        artifacts = await store.list_research_artifacts(
            target_id=target_id,
            subject_type="canonical_event",
            subject_id=canonical_event_id,
            limit=200,
        )
        content = render_canonical_event_markdown(event, mentions, relations, artifacts)
        return _markdown_download_response(f"{canonical_event_id}.md", content)

    # ── Research workflow endpoints ────────────────────

    @app.get("/api/v1/research/queue")
    async def research_queue(
        target_id: str,
        status: str = Query("open", pattern="^(open|resolved|all)$"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        return await store.list_research_queue(
            target_id=target_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/v1/research/graph/merge")
    async def research_graph_merge(
        payload: ResearchGraphMergeRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        created_by = (
            "local-user" if user.get("local") else str(user.get("username") or "local-user")
        )
        try:
            if payload.dry_run:
                return await store.preview_canonical_merge(
                    target_id=payload.target_id,
                    decision_artifact_id=payload.decision_artifact_id,
                    survivor_canonical_event_id=payload.survivor_canonical_event_id,
                    merged_canonical_event_ids=payload.merged_canonical_event_ids,
                    title_override=payload.title_override,
                    summary_override=payload.summary_override,
                    created_by=created_by,
                )
            return await store.apply_canonical_merge(
                target_id=payload.target_id,
                decision_artifact_id=payload.decision_artifact_id,
                survivor_canonical_event_id=payload.survivor_canonical_event_id,
                merged_canonical_event_ids=payload.merged_canonical_event_ids,
                title_override=payload.title_override,
                summary_override=payload.summary_override,
                created_by=created_by,
            )
        except ValueError as exc:
            raise _research_graph_error(exc) from exc

    @app.post("/api/v1/research/graph/split")
    async def research_graph_split(
        payload: ResearchGraphSplitRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        created_by = (
            "local-user" if user.get("local") else str(user.get("username") or "local-user")
        )
        try:
            if payload.dry_run:
                return await store.preview_canonical_split(
                    target_id=payload.target_id,
                    decision_artifact_id=payload.decision_artifact_id,
                    source_canonical_event_id=payload.source_canonical_event_id,
                    affected_mention_ids=payload.affected_mention_ids,
                    new_title=payload.new_title,
                    new_summary=payload.new_summary,
                    created_by=created_by,
                )
            return await store.apply_canonical_split(
                target_id=payload.target_id,
                decision_artifact_id=payload.decision_artifact_id,
                source_canonical_event_id=payload.source_canonical_event_id,
                affected_mention_ids=payload.affected_mention_ids,
                new_title=payload.new_title,
                new_summary=payload.new_summary,
                created_by=created_by,
            )
        except ValueError as exc:
            raise _research_graph_error(exc) from exc

    @app.get("/api/v1/research/graph/operations")
    async def research_graph_operations(
        target_id: str,
        operation_type: str | None = Query(None, pattern="^(merge|split)$"),
        decision_artifact_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        try:
            operations = await store.list_canonical_graph_operations(
                target_id=target_id,
                operation_type=operation_type,
                decision_artifact_id=decision_artifact_id,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"operations": operations, "limit": limit, "offset": offset}

    @app.get("/api/v1/research/events/{canonical_event_id}")
    async def research_event_detail(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await _canonical_event_or_404(store, canonical_event_id, target_id)
        mentions = await store.list_event_mentions(canonical_event_id)
        relations = await store.list_canonical_relations(canonical_event_id)
        artifacts = await store.list_research_artifacts(
            target_id=target_id,
            subject_type="canonical_event",
            subject_id=canonical_event_id,
            limit=200,
        )
        return {
            "event": event,
            "mentions": mentions,
            "relations": relations,
            "artifacts": artifacts,
        }

    @app.get("/api/v1/research/artifacts")
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
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        if subject_id is not None:
            await _canonical_event_or_404(store, subject_id, target_id)
        artifacts = await store.list_research_artifacts(
            target_id=target_id,
            subject_type=subject_type,
            subject_id=subject_id,
            artifact_type=artifact_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"artifacts": artifacts, "limit": limit, "offset": offset}

    @app.post("/api/v1/research/artifacts")
    async def create_research_artifact(
        payload: ResearchArtifactCreateRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        _validate_research_metadata(payload.artifact_type, payload.metadata)
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        await _canonical_event_or_404(store, payload.subject_id, payload.target_id)
        canonical_event_ids = [payload.subject_id]
        candidates = payload.metadata.get("candidate_canonical_event_ids")
        if isinstance(candidates, list):
            canonical_event_ids.extend(str(candidate) for candidate in candidates)
        artifact_id = _new_research_artifact_id(
            payload.target_id,
            payload.artifact_type,
            payload.subject_id,
            payload.metadata,
        )
        created_by = (
            "local-user" if user.get("local") else str(user.get("username") or "local-user")
        )
        try:
            await store.upsert_research_artifact(
                {
                    "artifact_id": artifact_id,
                    "target_id": payload.target_id,
                    "artifact_type": payload.artifact_type,
                    "title": payload.title,
                    "body": payload.body,
                    "subject_type": payload.subject_type,
                    "subject_id": payload.subject_id,
                    "canonical_event_ids": canonical_event_ids,
                    "status": payload.status,
                    "visibility": payload.visibility,
                    "created_by": created_by,
                    "metadata": payload.metadata,
                }
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        artifact = await store.get_research_artifact(artifact_id)
        return {"artifact": artifact}

    @app.patch("/api/v1/research/artifacts/{artifact_id}")
    async def patch_research_artifact(
        artifact_id: str,
        target_id: str,
        payload: ResearchArtifactPatchRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        current = await store.get_research_artifact(artifact_id)
        if current is None or current.get("target_id") != target_id:
            raise HTTPException(status_code=404, detail="Research artifact not found")
        patch = payload.model_dump(exclude_none=True)
        if "metadata" in patch:
            _validate_research_metadata(str(current.get("artifact_type")), patch["metadata"])
        try:
            updated = await store.update_research_artifact(
                artifact_id,
                target_id=target_id,
                patch=patch,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Research artifact not found")
        return {"artifact": updated}

    # ── 维护端点 (Phase 40) ─────────────────────────────

    @app.get("/api/v1/maintenance/draft-diagnostics")
    async def maintenance_draft_diagnostics(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """只读诊断 draft 文件与运行时索引的一致性。"""
        return await _draft_diagnostics(_data_dir, target_id)

    @app.post("/api/v1/maintenance/archive-duplicate-drafts")
    async def maintenance_archive_duplicate_drafts(
        target_id: str = Query(..., description="目标标识"),
        dry_run: bool = Query(False, description="仅返回计划，不移动文件"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        """将重复 event_id 的多余 draft 文件归档，保留可公开读取的 canonical 文件。"""
        return await _archive_duplicate_drafts(_data_dir, target_id, dry_run=dry_run)

    @app.post("/api/v1/maintenance/prune", response_model=PruneResponse)
    async def maintenance_prune(
        target_id: str = Query(..., description="目标标识"),
        max_age_days: int = Query(30, ge=7, le=365, description="保留天数"),
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> PruneResponse:
        """手动触发数据清理。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        result = await _store.prune_old_data(target_id, max_age_days=max_age_days)
        return PruneResponse(target_id=target_id, **result)

    @app.post("/api/v1/maintenance/backup", response_model=BackupResponse)
    async def maintenance_backup(
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> BackupResponse:
        """手动触发数据库备份。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        backup_dir = _store.db_path.parent / "backups"
        backup_path = await _store.backup_db(backup_dir)
        size = backup_path.stat().st_size if backup_path.exists() else 0
        return BackupResponse(backup_path=str(backup_path), size_bytes=size)

    @app.get("/api/v1/maintenance/backups")
    async def list_backups(
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """列出可用备份。"""
        if _store is None:
            return {"backups": []}
        backup_dir = _store.db_path.parent / "backups"
        if not backup_dir.exists():
            return {"backups": []}
        backups = []
        for f in sorted(backup_dir.glob("state_*.db"), reverse=True):
            backups.append(
                {
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "created_at": f.stat().st_ctime,
                }
            )
        return {"backups": backups}

    @app.post("/api/v1/maintenance/restore")
    async def restore_backup(
        filename: str = Query(..., description="备份文件名"),
        user: dict[str, Any] = Depends(require_permission("admin")),
    ) -> dict[str, Any]:
        """从备份恢复数据库（需 admin 权限）。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        backup_dir = _store.db_path.parent / "backups"
        backup_path = backup_dir / filename
        if not backup_path.exists() or not filename.startswith("state_"):
            raise HTTPException(status_code=404, detail="Backup not found")
        # 安全检查：防止路径遍历
        if ".." in filename or "/" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        import shutil

        # 先备份当前数据库
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        current_backup = _store.db_path.parent / f"state_pre_restore_{ts}.db"
        shutil.copy2(str(_store.db_path), str(current_backup))
        # 关闭当前连接
        await _store.close()
        # 替换数据库文件
        shutil.copy2(str(backup_path), str(_store.db_path))
        # 重新初始化
        await _store.initialize()
        return {"status": "restored", "restored_from": filename}

    # ── 反馈闭环 + 告警管理 (Phase 41) ──────────────────

    @app.post("/api/v1/feedback", response_model=FeedbackSubmitResponse)
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

    @app.get("/api/v1/feedback", response_model=FeedbackListResponse)
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

    @app.get("/api/v1/feedback/stats", response_model=FeedbackStatsResponse)
    async def feedback_stats(
        target_id: str = Query(..., description="目标标识"),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> FeedbackStatsResponse:
        """获取反馈统计。"""
        if _store is None:
            return FeedbackStatsResponse(total=0, publish_override=0, archive_override=0, comment=0)
        stats = await _store.get_feedback_stats(target_id)
        return FeedbackStatsResponse(**stats)

    @app.post("/api/v1/rules/optimize", response_model=RulesOptimizeResponse)
    async def optimize_rules(
        req: RulesOptimizeRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> RulesOptimizeResponse:
        """触发规则优化。"""
        filter_yaml = (Path("config") / "filters" / req.target_id / "default.yaml").resolve()
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

    # ── 静态文件（必须在所有 API 路由之后挂载）────────
    static_dir = _static_dir()
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
