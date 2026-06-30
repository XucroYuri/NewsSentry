/**
 * M-8 API 响应契约 — Cloudflare Workers 共享类型。
 *
 * 每个接口镜像了 `src/news_sentry/api/schemas.py` 中对应的 Pydantic 模型。
 * Workers 端点必须使用这些类型以确保 JSON 响应形状与 Python API 一致。
 *
 * 同步规则：如果修改 schemas.py 中的对应模型，
 * 必须同步更新此文件。
 */

// ── /api/v1/health ───────────────────────────────────────────────────────
// Python: 内联 dict[str, Any]
export interface HealthResponse {
  status: string;
  total_events: number;
  latest_collected_at: string | null;
  public_quality?: {
    summary_ready: number;
    recommendation_ready: number;
    featured_total: number;
    latest_public_at: string | null;
  };
}

// ── /api/v1/public/news ──────────────────────────────────────────────────
// Python: PublicNewsFeedResponse

export interface PublicNewsSource {
  id: string;
  name: string;
  type: "rss" | "api" | "web" | "social" | "official" | "unknown";
  credibilityLabel?: string | null;
}

export interface PublicNewsEntity {
  name: string;
  type?: string | null;
}

export interface PublicNewsItem {
  id: string;
  targetId: string;
  targetLabel: string;
  source: PublicNewsSource;
  publishedAt: string;
  title: string;
  originalTitle?: string | null;
  summary?: string | null;
  recommendationReason?: string | null;
  fullContent?: string | null;
  imageUrls: string[];
  originalUrl?: string | null;
  detailUrl: string;
  tags: string[];
  issueTags: string[];
  relatedTags: string[];
  regionTags: string[];
  entities: PublicNewsEntity[];
  relatedCount: number;
  discussionCount?: number | null;
  valueLabel: "精选" | "关注" | "普通" | "待评估";
  valueScore?: number | null;
  breakingScore?: number | null;
  breakingLabel?: "flash" | "breaking" | "watch" | "timeline" | null;
  breakingReason?: string | null;
  breakingConfidence?: number | null;
  breakingDimensions?: Record<string, number>;
  targetTimezone?: string | null;
  publishedAtLocal?: string | null;
  availableLocales?: string[];
  chinaRelevanceLabel: "高" | "中" | "低" | "未知";
}

export interface PublicNewsFeedResponse {
  items: PublicNewsItem[];
  latestCursor?: string | null;
  nextCursor?: string | null;
  pollAfterMs: number;
  hasNewer: boolean;
  total: number;
}

// ── /api/v1/public/news/{event_id} ───────────────────────────────────────
// Python: PublicNewsItem（同 new-feed，直接复用）

// ── /api/v1/public/facets ────────────────────────────────────────────────
// Python: PublicFacetsResponse

export interface PublicFacetItem {
  id: string;
  label: string;
  count: number;
}

export interface PublicFacetsResponse {
  regions: PublicFacetItem[];
  issues: PublicFacetItem[];
  related: PublicFacetItem[];
}

// ── /api/v1/public/bootstrap ─────────────────────────────────────────────
// Python: PublicBootstrapResponse

export interface RegionInfo {
  region_id: string;
  display_name: string;
  primary_language: string;
  region_type: "country" | "region" | "continent" | "global";
  source_count: number;
  event_count: number;
  lifecycle: Record<string, unknown>;
  archived: boolean;
}

export interface RegionListResponse {
  regions: RegionInfo[];
}

export interface TargetInfo {
  target_id: string;
  display_name: string;
  primary_language: string;
  region_type: "country" | "region" | "continent" | "global";
  source_count: number;
  event_count: number;
  lifecycle: Record<string, unknown>;
  archived: boolean;
}

export interface TargetListResponse {
  targets: TargetInfo[];
}

export interface PublicBootstrapResponse {
  news: PublicNewsFeedResponse;
  regions: RegionListResponse;
  facets: PublicFacetsResponse;
  generatedAt: string;
}

// ── /api/v1/webhook ──────────────────────────────────────────────────────
// Python: WebhookResponse

export interface WebhookResponse {
  status: string;
  event_id: string;
  message: string;
}

// ── /api/v1/events/import ────────────────────────────────────────────────
// Python: ImportResponse

export interface ImportEventItem {
  target_id: string;
  source_id: string;
  title_original: string;
  url: string;
  collected_at: string;
  content_original?: string;
  language?: string;
  title?: string;
  summary?: string;
  recommendation_reason?: string;
  breaking_score?: number;
  breaking_label?: string;
  breaking_reason?: string;
  breaking_confidence?: number;
  breaking_dimensions?: Record<string, number>;
  breaking_score_version?: string;
  target_timezone?: string;
  published_at_local?: string;
  localizations?: Array<{
    locale: string;
    title: string;
    summary?: string;
    recommendation_reason?: string;
    tags?: string[];
    issue_tags?: string[];
    related_tags?: string[];
    region_tags?: string[];
    language?: string;
    quality_score?: number;
    model?: string;
    route_id?: string;
  }>;
  classification?: Record<string, unknown> | null;
  pipeline_stage?: string;
  published_at?: string;
}

export interface ImportResponse {
  imported: number;
  updated: number;
  skipped: number;
  errors: string[];
}
