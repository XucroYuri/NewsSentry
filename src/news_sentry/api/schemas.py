"""API Pydantic schemas — extracted from api_server.py (Phase 2 拆分).

All request/response models used by the FastAPI application.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Research 常量（供模型校验使用）──────────────────────

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

# ── Pydantic 模型 ──────────────────────────────────────


class EventResponse(BaseModel):
    """事件列表响应。"""

    total: int
    events: list[dict[str, Any]]
    page: int
    page_size: int


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应 — 与 /api/v1/auth/login 返回值保持一致。"""

    access_token: str
    token_type: str
    expires_in: int
    username: str
    role: str
    has_api_key: bool = False
    must_change_password: bool = False


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


class TransitionEventRequest(BaseModel):
    """M-35.2: 事件审核阶段转换请求。"""

    target_id: str
    new_stage: Literal["drafts", "reviewed", "published"]


class TransitionEventResponse(BaseModel):
    """M-35.2: 事件审核阶段转换响应。"""

    event_id: str
    new_stage: str
    new_file_path: str


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


class RegionInfo(BaseModel):
    """公共地区入口，作为新版 public target 的语义承载。"""

    region_id: str
    display_name: str
    primary_language: str
    region_type: Literal["country", "region", "continent", "global"] = "country"
    source_count: int
    event_count: int = 0
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False


class RegionListResponse(BaseModel):
    """公共地区列表响应。"""

    regions: list[RegionInfo]


class PublicFacetItem(BaseModel):
    """公共新闻动态筛选标签。"""

    id: str
    label: str
    count: int


class PublicFacetsResponse(BaseModel):
    """公共新闻当前可见内容的动态 facets。"""

    regions: list[PublicFacetItem]
    issues: list[PublicFacetItem]
    related: list[PublicFacetItem]


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
    type: str  # rss | api | social
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
    monitoring_type: Literal["country", "region", "continent", "global"] | None = None
    region_type: Literal["country", "region", "continent", "global"] | None = None
    source_target_id: str | None = None
    template_id: str | None = None


class TargetPatchRequest(BaseModel):
    """Target 生命周期工作台内的基础资料更新。"""

    display_name: str | None = None
    monitoring_type: Literal["country", "region", "continent", "global"] | None = None
    region_type: Literal["country", "region", "continent", "global"] | None = None
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
    type: Literal["rss", "api"]
    source_ref: str | None = None
    url: str | None = None
    endpoint: dict[str, Any] | None = None
    api_mapping: dict[str, Any] | None = None
    tool_ref: str | None = None
    tool_params: dict[str, Any] | None = None
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
    collect_mode: str = "rss_bridge"
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
    confidence: int = 0
    needs_review: bool = False
    first_seen_source_id: str | None = None
    last_seen_source_id: str | None = None
    aliases: str = ""


class EntityMergeRequest(BaseModel):
    """实体合并请求。"""

    source_id: int
    target_id: int


class EntityMergeResponse(BaseModel):
    """实体合并响应。"""

    merged: bool
    source_name: str = ""
    target_name: str = ""
    error: str | None = None


class EntityListResponse(BaseModel):
    """实体列表响应。"""

    total: int
    entities: list[EntityInfo]


class EntityDetailResponse(BaseModel):
    """实体详情响应。"""

    entity: EntityInfo
    recent_events: list[dict[str, Any]] = []


class AnnotationCreateRequest(BaseModel):
    """创建人工注解请求。"""

    entity_id: int
    field: str
    old_value: str = ""
    new_value: str = ""
    event_id: str | None = None
    annotation_type: str = "manual"
    created_by: str = "local-user"


class AnnotationInfo(BaseModel):
    """注解记录响应。"""

    id: int
    entity_id: int
    event_id: str | None = None
    field: str
    old_value: str
    new_value: str
    annotation_type: str
    created_by: str
    created_at: str
    reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    canonical_name: str = ""


class AnnotationListResponse(BaseModel):
    """注解列表响应。"""

    annotations: list[AnnotationInfo]
    total: int = 0


class AnnotationUpdateRequest(BaseModel):
    """更新注解请求（编辑内容或审核状态）。"""

    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    annotation_type: str | None = None
    reviewed: bool | None = None
    reviewed_by: str | None = None


class NotificationRuleRequest(BaseModel):
    """通知规则创建/更新请求。"""

    id: str
    user_id: str = ""
    watch: dict[str, Any] = {}
    action: dict[str, Any] = {}
    quiet_hours: dict[str, Any] | None = None
    enabled: bool = True


class NotificationRuleInfo(BaseModel):
    """通知规则响应。"""

    id: str
    user_id: str
    enabled: bool
    rule: dict[str, Any] = {}
    created_at: str = ""
    updated_at: str = ""


class NotificationRuleListResponse(BaseModel):
    """通知规则列表响应。"""

    rules: list[NotificationRuleInfo]
    total: int = 0


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
    issue_tags: list[str] = Field(default_factory=list, alias="issueTags")
    related_tags: list[str] = Field(default_factory=list, alias="relatedTags")
    region_tags: list[str] = Field(default_factory=list, alias="regionTags")
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


class PublicBootstrapResponse(BaseModel):
    """公共阅读首屏启动 payload，避免首屏拆成多次动态查询。"""

    news: PublicNewsFeedResponse
    regions: RegionListResponse
    facets: PublicFacetsResponse
    generated_at: str = Field(alias="generatedAt")

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


# ═══════════════════════════════════════════════
# Admin Response Models
# ═══════════════════════════════════════════════


class AdminTargetItem(BaseModel):
    """管理后台 target 列表项。"""

    target_id: str
    name: str
    kind: str
    languages: list[str] = []
    source_count: int = 0
    event_count: int = 0
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    classification_profile: str | None = None
    total_events: int = 0


class AdminTargetListResponse(BaseModel):
    """管理后台 target 列表响应。"""

    targets: list[AdminTargetItem]
    total: int


class AdminUserItem(BaseModel):
    """管理后台用户列表项（不含密码哈希/盐）。"""

    username: str
    role: str
    has_api_key: bool = False
    must_change_pw: bool = False
    created_at: str | None = None


class AdminUserListResponse(BaseModel):
    """管理后台用户列表响应。"""

    users: list[AdminUserItem]
    total: int


class AdminSourceHealthItem(BaseModel):
    """信源健康摘要项。"""

    source_ref: str
    status: str = "unknown"
    last_fetch_at: str | None = None
    last_error: str | None = None
    error_count: int = 0


class AdminOverviewResponse(BaseModel):
    """管理总览聚合响应。"""

    target_id: str
    targets: list[dict[str, Any]]
    collector: dict[str, Any]
    diagnostics: dict[str, Any]
    source_health: dict[str, Any]
    recent_runs: list[dict[str, Any]]
    feedback: dict[str, Any]
    alerts: dict[str, Any]
    rules_metrics: dict[str, Any] | None = None


class AdminTargetOverviewResponse(BaseModel):
    """单个 target 工作台总览响应。"""

    target: dict[str, Any]
    profile: dict[str, Any]
    sources: dict[str, Any]
    social: dict[str, Any]
    events: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    validation: dict[str, Any]
    recent_runs: list[dict[str, Any]]
    pipeline_status: dict[str, Any] | None = None
