export type PublicNewsSourceType = "rss" | "api" | "web" | "social" | "official" | "unknown"

export interface PublicNewsSource {
  id: string
  name: string
  type: PublicNewsSourceType
  credibilityLabel?: string | null
}

export interface PublicNewsEntity {
  name: string
  type?: string | null
}

export type PublicNewsValueLabel = "精选" | "关注" | "普通" | "待评估"
export type PublicChinaRelevanceLabel = "高" | "中" | "低" | "未知"

export interface PublicNewsItem {
  id: string
  targetId: string
  targetLabel: string
  source: PublicNewsSource
  publishedAt: string
  title: string
  originalTitle?: string | null
  summary?: string | null
  recommendationReason?: string | null
  fullContent?: string | null
  imageUrls?: string[]
  originalUrl?: string | null
  detailUrl: string
  tags: string[]
  issueTags: string[]
  relatedTags: string[]
  regionTags: string[]
  entities: PublicNewsEntity[]
  relatedCount: number
  discussionCount?: number | null
  valueLabel: PublicNewsValueLabel
  valueScore?: number | null
  breakingScore?: number | null
  breakingRawScore?: number | null
  breakingPercentile?: number | null
  breakingCalibratedScore?: number | null
  breakingVersion?: string | null
  breakingLabel?: "flash" | "breaking" | "watch" | "timeline" | null
  breakingReason?: string | null
  breakingConfidence?: number | null
  breakingDimensions?: Record<string, number>
  targetTimezone?: string | null
  publishedAtLocal?: string | null
  availableLocales?: string[]
  chinaRelevanceLabel: PublicChinaRelevanceLabel
}

export interface PublicNewsFeedResponse {
  items: PublicNewsItem[]
  latestCursor?: string | null
  nextCursor?: string | null
  pollAfterMs: number
  hasNewer: boolean
  total: number
}

export interface PublicNewsQuery {
  featured?: boolean
  locale?: string
  targetId?: string
  regionId?: string
  sourceId?: string
  category?: string
  issue?: string
  related?: string
  date?: string
  q?: string
  beforeCursor?: string
  sinceCursor?: string
  pageSize?: number
}

export interface PublicNewsRequestOptions {
  etag?: string
  targetId?: string
  signal?: AbortSignal
  fetcher?: typeof fetch
}

export interface PublicNewsListResult {
  data: PublicNewsFeedResponse | null
  etag: string | null
  notModified: boolean
  pollAfterMs: number | null
}

export interface PublicTargetInfo {
  target_id: string
  display_name: string
  primary_language: string
  monitoring_type: string
  monitoring_label: string
  source_count: number
  event_count: number
  lifecycle: Record<string, unknown>
  archived: boolean
}

export interface PublicTargetListResponse {
  targets: PublicTargetInfo[]
}

export interface PublicRegionInfo {
  region_id: string
  display_name: string
  primary_language: string
  region_type: "country" | "region" | "continent" | "global"
  source_count: number
  event_count: number
  lifecycle: Record<string, unknown>
  archived: boolean
}

export interface PublicRegionListResponse {
  regions: PublicRegionInfo[]
}

export interface PublicFacetItem {
  id: string
  label: string
  count: number
}

export interface PublicFacetsResponse {
  regions: PublicFacetItem[]
  issues: PublicFacetItem[]
  related: PublicFacetItem[]
}

export interface PublicBootstrapResponse {
  news: PublicNewsFeedResponse
  regions: PublicRegionListResponse
  facets: PublicFacetsResponse
  generatedAt: string
}

export interface PublicBootstrapResult {
  data: PublicBootstrapResponse
  etag: string | null
}

export interface PublicAnalysisSummary {
  total_events: number
  high_value_events: number
  avg_news_value_score?: number | null
  avg_china_relevance?: number | null
}

export interface PublicDistributionItem {
  name: string
  count: number
}

export interface PublicSourceDistributionItem {
  source_id: string
  display_name: string
  count: number
}

export interface PublicEntityItem {
  name: string
  entity_type?: string
  mention_count?: number
}

export interface PublicTopicTrendItem {
  topic: string
  trend_direction?: string
  hotness?: number
  current_count?: number
  prev_count?: number
  event_count?: number
  daily_counts?: Array<Record<string, unknown>>
}

export interface PublicChainItem {
  root_event_id: string
  event_count: number
  latest_time?: string
  latest_title?: string
  narrative_summary?: string
}

export interface PublicAnalysisResponse {
  target_id: string
  target_name: string
  days: number
  summary: PublicAnalysisSummary
  classification_distribution: PublicDistributionItem[]
  source_distribution: PublicSourceDistributionItem[]
  top_entities: PublicEntityItem[]
  topic_trends: PublicTopicTrendItem[]
  sentiment_trend: Array<Record<string, unknown>>
  active_chains: PublicChainItem[]
  generated_at: string
}
