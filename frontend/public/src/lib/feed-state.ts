import type { PublicNewsItem, PublicNewsQuery } from "@/types/public-news"

export type PublicChannel = "featured" | "all" | "targets" | "sources" | "analysis" | "daily"

export interface FeedFilters {
  channel: PublicChannel
  targetId?: string
  sourceId?: string
  category?: string
  search?: string
  date?: string
  pageSize?: number
}

export interface PollDelayInput {
  serverMs?: number | null
  failureCount: number
}

export interface PollPauseInput {
  visibilityState: DocumentVisibilityState | "visible" | "hidden"
  online: boolean
}

const MIN_POLL_MS = 30_000
const MAX_POLL_MS = 5 * 60_000

function clean(value: string | undefined) {
  const next = value?.trim()
  return next ? next : undefined
}

export function makeFeedQuery(filters: FeedFilters): PublicNewsQuery {
  const query: PublicNewsQuery = {}
  if (filters.channel === "featured") query.featured = true
  query.targetId = clean(filters.targetId)
  query.sourceId = clean(filters.sourceId)
  query.category = clean(filters.category)
  query.date = clean(filters.date)
  query.q = clean(filters.search)
  if (filters.pageSize !== undefined) query.pageSize = filters.pageSize
  return query
}

export function mergeNewerItems(current: PublicNewsItem[], newer: PublicNewsItem[]) {
  const seen = new Set<string>()
  const merged: PublicNewsItem[] = []
  for (const item of [...newer, ...current]) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    merged.push(item)
  }
  return merged
}

export function appendOlderItems(current: PublicNewsItem[], older: PublicNewsItem[]) {
  const seen = new Set(current.map((item) => item.id))
  return [...current, ...older.filter((item) => !seen.has(item.id))]
}

export function nextPollDelayMs({ serverMs, failureCount }: PollDelayInput) {
  const base = Math.min(Math.max(serverMs ?? MIN_POLL_MS, MIN_POLL_MS), MAX_POLL_MS)
  if (failureCount <= 0) return base
  return Math.min(base * 2 ** failureCount, MAX_POLL_MS)
}

export function shouldPausePolling({ visibilityState, online }: PollPauseInput) {
  return visibilityState !== "visible" || !online
}

export function groupItemsByDate(items: PublicNewsItem[]) {
  return items.reduce<Array<{ key: string; label: string; items: PublicNewsItem[] }>>((groups, item) => {
    const date = new Date(item.publishedAt)
    const key = Number.isNaN(date.getTime()) ? "unknown" : date.toISOString().slice(0, 10)
    const existing = groups.find((group) => group.key === key)
    if (existing) {
      existing.items.push(item)
      return groups
    }
    groups.push({
      key,
      label: formatDateGroup(item.publishedAt),
      items: [item],
    })
    return groups
  }, [])
}

export function formatDateGroup(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "时间待确认"
  const now = new Date()
  const today = now.toISOString().slice(0, 10)
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const key = date.toISOString().slice(0, 10)
  if (key === today) return "今天"
  if (key === yesterday.toISOString().slice(0, 10)) return "昨天"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date)
}
