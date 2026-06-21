import type {
  PublicAnalysisResponse,
  PublicBootstrapResponse,
  PublicBootstrapResult,
  PublicFacetsResponse,
  PublicFacetItem,
  PublicNewsFeedResponse,
  PublicNewsItem,
  PublicNewsListResult,
  PublicNewsQuery,
  PublicNewsRequestOptions,
  PublicRegionInfo,
  PublicRegionListResponse,
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
  appendParam(params, "region_id", query.regionId)
  appendParam(params, "source_id", query.sourceId)
  appendParam(params, "category", query.category)
  appendParam(params, "issue", query.issue)
  appendParam(params, "related", query.related)
  appendParam(params, "date", query.date)
  appendParam(params, "q", query.q)
  appendParam(params, "before_cursor", query.beforeCursor)
  appendParam(params, "since_cursor", query.sinceCursor)
  appendParam(params, "page_size", query.pageSize)
  const suffix = params.toString()
  return `/api/v1/public/news${suffix ? `?${suffix}` : ""}`
}

export function buildPublicBootstrapUrl(query: PublicNewsQuery = {}) {
  const params = new URLSearchParams()
  appendParam(params, "featured", query.featured)
  appendParam(params, "target_id", query.targetId)
  appendParam(params, "region_id", query.regionId)
  appendParam(params, "source_id", query.sourceId)
  appendParam(params, "category", query.category)
  appendParam(params, "issue", query.issue)
  appendParam(params, "related", query.related)
  appendParam(params, "date", query.date)
  appendParam(params, "q", query.q)
  appendParam(params, "page_size", query.pageSize)
  const suffix = params.toString()
  return `/api/v1/public/bootstrap${suffix ? `?${suffix}` : ""}`
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
    !isStringArray(value.issueTags) ||
    !isStringArray(value.relatedTags) ||
    !isStringArray(value.regionTags) ||
    !Array.isArray(value.entities) ||
    typeof value.relatedCount !== "number" ||
    typeof value.valueLabel !== "string" ||
    typeof value.chinaRelevanceLabel !== "string"
  ) {
    throw new PublicNewsApiError("Public news item response shape is invalid")
  }
}

function assertRegion(value: unknown): asserts value is PublicRegionInfo {
  if (!isRecord(value)) {
    throw new PublicNewsApiError("Region item is not an object")
  }
  if (
    typeof value.region_id !== "string" ||
    typeof value.display_name !== "string" ||
    typeof value.primary_language !== "string" ||
    typeof value.region_type !== "string" ||
    typeof value.source_count !== "number" ||
    typeof value.event_count !== "number" ||
    typeof value.archived !== "boolean"
  ) {
    throw new PublicNewsApiError("Region list response shape is invalid")
  }
}

function assertRegionList(value: unknown): asserts value is PublicRegionListResponse {
  if (!isRecord(value) || !Array.isArray(value.regions)) {
    throw new PublicNewsApiError("Region list response shape is invalid")
  }
  for (const region of value.regions) {
    assertRegion(region)
  }
}

function assertFacetItem(value: unknown): asserts value is PublicFacetItem {
  if (!isRecord(value)) {
    throw new PublicNewsApiError("Facet item is not an object")
  }
  if (
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    typeof value.count !== "number"
  ) {
    throw new PublicNewsApiError("Facet response shape is invalid")
  }
}

function assertPublicFacets(value: unknown): asserts value is PublicFacetsResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.regions) ||
    !Array.isArray(value.issues) ||
    !Array.isArray(value.related)
  ) {
    throw new PublicNewsApiError("Facet response shape is invalid")
  }
  for (const item of [...value.regions, ...value.issues, ...value.related]) {
    assertFacetItem(item)
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

function assertPublicBootstrap(value: unknown): asserts value is PublicBootstrapResponse {
  if (!isRecord(value) || typeof value.generatedAt !== "string") {
    throw new PublicNewsApiError("Public bootstrap response shape is invalid")
  }
  assertPublicNewsFeed(value.news)
  assertRegionList(value.regions)
  assertPublicFacets(value.facets)
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

export async function getPublicBootstrap(
  query: PublicNewsQuery = {},
  options: PublicNewsRequestOptions = {},
): Promise<PublicBootstrapResult> {
  const fetcher = options.fetcher ?? fetch
  const response = await fetcher(buildPublicBootstrapUrl(query), {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new PublicNewsApiError(`Public bootstrap request failed with ${response.status}`, response.status)
  }
  return {
    data: await parseJsonResponse(response, assertPublicBootstrap),
    etag: response.headers.get("ETag"),
  }
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
  const response = await fetcher("/api/v1/regions?include_empty=true", {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new PublicNewsApiError(`Region list request failed with ${response.status}`, response.status)
  }
  const regionList = await parseJsonResponse(response, assertRegionList)
  return {
    targets: regionList.regions.map((region) => ({
      target_id: region.region_id,
      display_name: region.display_name,
      primary_language: region.primary_language,
      monitoring_type: region.region_type,
      monitoring_label: "地区",
      source_count: region.source_count,
      event_count: region.event_count,
      lifecycle: region.lifecycle,
      archived: region.archived,
    })),
  }
}

export async function listPublicFacets(
  query: Pick<PublicNewsQuery, "regionId" | "targetId" | "issue" | "related" | "date" | "q"> = {},
  options: PublicNewsRequestOptions = {},
): Promise<PublicFacetsResponse> {
  const fetcher = options.fetcher ?? fetch
  const params = new URLSearchParams()
  appendParam(params, "region_id", query.regionId ?? query.targetId)
  appendParam(params, "issue", query.issue)
  appendParam(params, "related", query.related)
  appendParam(params, "date", query.date)
  appendParam(params, "q", query.q)
  const suffix = params.toString()
  const response = await fetcher(`/api/v1/public/facets${suffix ? `?${suffix}` : ""}`, {
    signal: options.signal,
  })
  if (!response.ok) {
    throw new PublicNewsApiError(`Public facets request failed with ${response.status}`, response.status)
  }
  return parseJsonResponse(response, assertPublicFacets)
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
