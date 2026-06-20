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
  latestSummary: string | null
  regionLabels: string[]
  issueLabels: string[]
  relatedLabels: string[]
  statusLabel: "近期活跃" | "近期较少更新" | "等待更多样本"
}

export interface DailyDigest {
  date: string
  total: number
  topItems: PublicNewsItem[]
  topicGroups: DailyDigestTopicGroup[]
  topicLabels: string[]
  sourceLabels: string[]
  riskLabels: string[]
}

export interface DailyDigestTopicGroup {
  label: string
  count: number
  items: PublicNewsItem[]
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

export function targetShortLabel(label?: string | null) {
  const value = label?.trim()
  if (!value) return "目标"
  return (
    value
      .replace(/新闻监控/g, "")
      .replace(/监控目标/g, "")
      .replace(/国别监控/g, "")
      .replace(/观察/g, "")
      .trim() || value
  )
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
        latestSummary: item.summary ?? null,
        regionLabels: unique([targetShortLabel(item.targetLabel), ...item.regionTags]),
        issueLabels: unique(item.issueTags.length > 0 ? item.issueTags : item.tags),
        relatedLabels: unique(item.relatedTags),
        statusLabel: "等待更多样本",
      })
      continue
    }
    existing.count += 1
    existing.regionLabels = unique([
      ...existing.regionLabels,
      targetShortLabel(item.targetLabel),
      ...item.regionTags,
    ])
    existing.issueLabels = unique([
      ...existing.issueLabels,
      ...(item.issueTags.length > 0 ? item.issueTags : item.tags),
    ])
    existing.relatedLabels = unique([...existing.relatedLabels, ...item.relatedTags])
    if (
      !existing.latestPublishedAt ||
      new Date(item.publishedAt).getTime() > new Date(existing.latestPublishedAt).getTime()
    ) {
      existing.latestPublishedAt = item.publishedAt
      existing.latestTitle = item.title
      existing.latestSummary = item.summary ?? null
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
    .slice(0, 6)
  const topicLabels = unique(dailyItems.flatMap((item) => item.tags.map(readableTopicLabel))).slice(
    0,
    8,
  )
  const sourceLabels = unique(dailyItems.map((item) => item.source.name)).slice(0, 8)
  const riskLabels = unique(
    dailyItems
      .filter((item) => item.valueLabel === "精选" || (item.valueScore ?? 0) >= 85)
      .flatMap((item) => item.tags.map(readableTopicLabel)),
  ).slice(0, 5)
  const topicGroups = buildDailyTopicGroups(dailyItems)
  return {
    date,
    total: dailyItems.length,
    topItems,
    topicGroups,
    topicLabels,
    sourceLabels,
    riskLabels,
  }
}

function buildDailyTopicGroups(items: PublicNewsItem[]): DailyDigestTopicGroup[] {
  const groups = new Map<string, PublicNewsItem[]>()
  for (const item of items) {
    const label = primaryTopicLabel(item)
    const bucket = groups.get(label) ?? []
    bucket.push(item)
    groups.set(label, bucket)
  }
  return [...groups.entries()]
    .map(([label, groupItems]) => ({
      label,
      count: groupItems.length,
      items: [...groupItems]
        .sort(
          (a, b) =>
            (b.valueScore ?? 0) - (a.valueScore ?? 0) ||
            new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime(),
        )
        .slice(0, 3),
    }))
    .sort(
      (a, b) =>
        b.count - a.count ||
        (b.items[0]?.valueScore ?? 0) - (a.items[0]?.valueScore ?? 0) ||
        a.label.localeCompare(b.label),
    )
    .slice(0, 6)
}

function primaryTopicLabel(item: PublicNewsItem) {
  const tag = item.tags.map(readableTopicLabel).find(Boolean)
  return tag || targetShortLabel(item.targetLabel)
}

function readableTopicLabel(value: string) {
  const normalized = value.trim()
  const labels: Record<string, string> = {
    uncategorized: "",
    "public-safety": "公共安全",
    politics: "政治",
    "international-relations": "国际关系",
    culture: "文化",
    society: "社会",
    economy: "经济",
    tech: "科技",
    technology: "科技",
  }
  return labels[normalized] ?? normalized
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
