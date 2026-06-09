import type {
  PublicAnalysisResponse,
  PublicNewsFeedResponse,
  PublicNewsItem,
  PublicNewsListResult,
  PublicNewsQuery,
  PublicNewsRequestOptions,
  PublicTargetInfo,
  PublicTargetListResponse,
} from "@/types/public-news"

export class PublicNewsApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = "PublicNewsApiError"
    this.status = status
  }
}

function appendParam(params: URLSearchParams, key: string, value: string | number | boolean | undefined) {
  if (value === undefined || value === "") return
  params.set(key, String(value))
}

export function buildPublicNewsUrl(query: PublicNewsQuery = {}) {
  const params = new URLSearchParams()
  appendParam(params, "featured", query.featured)
  appendParam(params, "target_id", query.targetId)
  appendParam(params, "source_id", query.sourceId)
  appendParam(params, "category", query.category)
  appendParam(params, "date", query.date)
  appendParam(params, "q", query.q)
  appendParam(params, "before_cursor", query.beforeCursor)
  appendParam(params, "since_cursor", query.sinceCursor)
  appendParam(params, "page_size", query.pageSize)
  const suffix = params.toString()
  return `/api/v1/public/news${suffix ? `?${suffix}` : ""}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function assertPublicNewsItem(value: unknown): asserts value is PublicNewsItem {
  if (!isRecord(value)) {
    throw new PublicNewsApiError("Public news item is not an object")
  }
  const source = value.source
  if (
    typeof value.id !== "string" ||
    typeof value.targetId !== "string" ||
    typeof value.targetLabel !== "string" ||
    !isRecord(source) ||
    typeof source.id !== "string" ||
    typeof source.name !== "string" ||
    typeof value.publishedAt !== "string" ||
    typeof value.title !== "string" ||
    typeof value.detailUrl !== "string" ||
    !isStringArray(value.tags) ||
    !Array.isArray(value.entities) ||
    typeof value.relatedCount !== "number" ||
    typeof value.valueLabel !== "string" ||
    typeof value.chinaRelevanceLabel !== "string"
  ) {
    throw new PublicNewsApiError("Public news item response shape is invalid")
  }
}

function assertPublicNewsFeed(value: unknown): asserts value is PublicNewsFeedResponse {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new PublicNewsApiError("Public news feed response shape is invalid")
  }
  for (const item of value.items) {
    assertPublicNewsItem(item)
  }
  if (
    typeof value.pollAfterMs !== "number" ||
    typeof value.hasNewer !== "boolean" ||
    typeof value.total !== "number"
  ) {
    throw new PublicNewsApiError("Public news feed metadata is invalid")
  }
}

function assertTarget(value: unknown): asserts value is PublicTargetInfo {
  if (!isRecord(value)) {
    throw new PublicNewsApiError("Target item is not an object")
  }
  if (
    typeof value.target_id !== "string" ||
    typeof value.display_name !== "string" ||
    typeof value.primary_language !== "string" ||
    typeof value.monitoring_type !== "string" ||
    typeof value.monitoring_label !== "string" ||
    typeof value.source_count !== "number" ||
    typeof value.event_count !== "number" ||
    typeof value.archived !== "boolean"
  ) {
    throw new PublicNewsApiError("Target list response shape is invalid")
  }
}

function assertTargetList(value: unknown): asserts value is PublicTargetListResponse {
  if (!isRecord(value) || !Array.isArray(value.targets)) {
    throw new PublicNewsApiError("Target list response shape is invalid")
  }
  for (const target of value.targets) {
    assertTarget(target)
  }
}

function assertDistributionList(value: unknown) {
  if (!Array.isArray(value)) {
    throw new PublicNewsApiError("Public analysis distribution is invalid")
  }
}

function assertPublicAnalysis(value: unknown): asserts value is PublicAnalysisResponse {
  if (!isRecord(value) || !isRecord(value.summary)) {
    throw new PublicNewsApiError("Public analysis response shape is invalid")
  }
  if (
    typeof value.target_id !== "string" ||
    typeof value.target_name !== "string" ||
    typeof value.days !== "number" ||
    typeof value.summary.total_events !== "number" ||
    typeof value.summary.high_value_events !== "number" ||
    typeof value.generated_at !== "string"
  ) {
    throw new PublicNewsApiError("Public analysis metadata is invalid")
  }
  assertDistributionList(value.classification_distribution)
  assertDistributionList(value.source_distribution)
  assertDistributionList(value.top_entities)
  assertDistributionList(value.topic_trends)
  assertDistributionList(value.sentiment_trend)
  assertDistributionList(value.active_chains)
}

async function parseJsonResponse<T>(response: Response, assertShape: (value: unknown) => asserts value is T) {
  const payload: unknown = await response.json()
  assertShape(payload)
  return payload
}

export async function listPublicNews(
  query: PublicNewsQuery = {},
  options: PublicNewsRequestOptions = {},
): Promise<PublicNewsListResult> {
  const fetcher = options.fetcher ?? fetch
  const headers = new Headers()
  if (options.etag) {
    headers.set("If-None-Match", options.etag)
  }
  const response = await fetcher(buildPublicNewsUrl(query), {
    headers,
    signal: options.signal,
  })
  const etag = response.headers.get("ETag")
  const pollAfterHeader = response.headers.get("X-Poll-After-Ms")
  const pollAfterMs = pollAfterHeader ? Number.parseInt(pollAfterHeader, 10) : null
  if (response.status === 304) {
    return {
      data: null,
      etag,
      notModified: true,
      pollAfterMs: Number.isFinite(pollAfterMs) ? pollAfterMs : null,
    }
  }
  if (!response.ok) {
    throw new PublicNewsApiError(`Public news request failed with ${response.status}`, response.status)
  }
  const data = await parseJsonResponse(response, assertPublicNewsFeed)
  return {
    data,
    etag,
    notModified: false,
    pollAfterMs: data.pollAfterMs,
  }
}

export async function getPublicNewsItem(
  eventId: string,
  options: PublicNewsRequestOptions = {},
): Promise<PublicNewsItem> {
  if (!eventId.trim()) {
    throw new PublicNewsApiError("Public news event id is required")
  }
  const fetcher = options.fetcher ?? fetch
  const params = new URLSearchParams()
  if (options.targetId) params.set("target_id", options.targetId)
  const suffix = params.toString()
  const response = await fetcher(`/api/v1/public/news/${encodeURIComponent(eventId)}${suffix ? `?${suffix}` : ""}`, {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new PublicNewsApiError(`Public news detail request failed with ${response.status}`, response.status)
  }
  return parseJsonResponse(response, assertPublicNewsItem)
}

export async function listTargets(
  options: PublicNewsRequestOptions = {},
): Promise<PublicTargetListResponse> {
  const fetcher = options.fetcher ?? fetch
  const response = await fetcher("/api/v1/targets", {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new PublicNewsApiError(`Target list request failed with ${response.status}`, response.status)
  }
  return parseJsonResponse(response, assertTargetList)
}

export async function getPublicTargetAnalysis(
  targetId: string,
  days: 7 | 14 | 30 = 14,
  options: PublicNewsRequestOptions = {},
): Promise<PublicAnalysisResponse> {
  if (!targetId.trim()) {
    throw new PublicNewsApiError("Public analysis target id is required")
  }
  const fetcher = options.fetcher ?? fetch
  const response = await fetcher(
    `/api/v1/public/targets/${encodeURIComponent(targetId)}/analysis?days=${days}`,
    {
      signal: options.signal,
    },
  )
  if (!response.ok) {
    throw new PublicNewsApiError(`Public analysis request failed with ${response.status}`, response.status)
  }
  return parseJsonResponse(response, assertPublicAnalysis)
}
