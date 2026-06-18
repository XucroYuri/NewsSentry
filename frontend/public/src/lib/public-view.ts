import { buildPublicAppPath, type PublicRoute } from "@/lib/routes"
import type { PublicNewsItem, PublicNewsSourceType } from "@/types/public-news"

export interface SourceSummary {
  id: string
  name: string
  type: PublicNewsSourceType
  credibilityLabel?: string | null
  count: number
  latestPublishedAt: string | null
  latestTitle: string | null
  statusLabel: "近期活跃" | "近期较少更新" | "等待更多样本"
}

export interface DailyDigest {
  date: string
  total: number
  topItems: PublicNewsItem[]
  topicLabels: string[]
  sourceLabels: string[]
  riskLabels: string[]
}

export interface RelatedBuckets {
  sameSource: PublicNewsItem[]
  sameTarget: PublicNewsItem[]
  sameTopic: PublicNewsItem[]
}

export function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间待确认"
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

export function formatFullTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间待确认"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

export function sourceTypeLabel(type: PublicNewsSourceType) {
  const labels: Record<PublicNewsSourceType, string> = {
    rss: "媒体源",
    api: "API",
    web: "网页",
    social: "社媒",
    official: "官方",
    unknown: "来源",
  }
  return labels[type] ?? "来源"
}

export function buildPublicDetailUrl(
  item: PublicNewsItem,
  options: { returnTo?: PublicRoute | null } = {},
) {
  const params = new URLSearchParams()
  if (item.targetId) params.set("target_id", item.targetId)
  if (options.returnTo) params.set("return_to", buildPublicAppPath(options.returnTo))
  const query = params.toString()
  return `/public-app/events/${encodeURIComponent(item.id)}${query ? `?${query}` : ""}`
}

export function summaryText(item: PublicNewsItem) {
  return [
    item.title,
    item.summary ? `摘要：${item.summary}` : null,
    item.recommendationReason ? `推荐理由：${item.recommendationReason}` : null,
    `来源：${item.source.name}`,
    item.originalUrl ? `原文：${item.originalUrl}` : null,
  ]
    .filter(Boolean)
    .join("\n")
}

export function buildSourceSummaries(items: PublicNewsItem[]): SourceSummary[] {
  const summaries = new Map<string, SourceSummary>()
  for (const item of items) {
    const existing = summaries.get(item.source.id)
    if (!existing) {
      summaries.set(item.source.id, {
        id: item.source.id,
        name: item.source.name,
        type: item.source.type,
        credibilityLabel: item.source.credibilityLabel,
        count: 1,
        latestPublishedAt: item.publishedAt,
        latestTitle: item.title,
        statusLabel: "等待更多样本",
      })
      continue
    }
    existing.count += 1
    if (
      !existing.latestPublishedAt ||
      new Date(item.publishedAt).getTime() > new Date(existing.latestPublishedAt).getTime()
    ) {
      existing.latestPublishedAt = item.publishedAt
      existing.latestTitle = item.title
    }
  }
  return [...summaries.values()]
    .map((summary): SourceSummary => {
      const statusLabel: SourceSummary["statusLabel"] =
        summary.count >= 2 ? "近期活跃" : summary.count === 1 ? "近期较少更新" : "等待更多样本"
      return {
        ...summary,
        statusLabel,
      }
    })
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
}

export function dateKey(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toISOString().slice(0, 10)
}

export function todayKey() {
  return new Date().toISOString().slice(0, 10)
}

export function buildDailyDigest(items: PublicNewsItem[], date: string): DailyDigest {
  const dailyItems = items.filter((item) => dateKey(item.publishedAt) === date)
  const topItems = [...dailyItems]
    .sort((a, b) => (b.valueScore ?? 0) - (a.valueScore ?? 0))
    .slice(0, 5)
  const topicLabels = unique(dailyItems.flatMap((item) => item.tags)).slice(0, 8)
  const sourceLabels = unique(dailyItems.map((item) => item.source.name)).slice(0, 8)
  const riskLabels = unique(
    dailyItems
      .filter((item) => item.valueLabel === "精选" || (item.valueScore ?? 0) >= 85)
      .flatMap((item) => item.tags),
  ).slice(0, 5)
  return {
    date,
    total: dailyItems.length,
    topItems,
    topicLabels,
    sourceLabels,
    riskLabels,
  }
}

export function buildRelatedBuckets(
  current: PublicNewsItem,
  candidates: PublicNewsItem[],
): RelatedBuckets {
  const pool = candidates.filter((item) => item.id !== current.id)
  const firstTopic = current.tags[0]
  return {
    sameSource: pool.filter((item) => item.source.id === current.source.id).slice(0, 5),
    sameTarget: pool.filter((item) => item.targetId === current.targetId).slice(0, 5),
    sameTopic: firstTopic
      ? pool.filter((item) => item.tags.includes(firstTopic)).slice(0, 5)
      : [],
  }
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))]
}
