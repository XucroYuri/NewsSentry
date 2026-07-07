import { useCallback, useMemo, useState } from "react"
import type { KeyboardEvent, MouseEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { votePublicNewsItem, unvotePublicNewsItem } from "@/lib/api"
import { isVoted as checkVoted, markVoted, unmarkVoted } from "@/lib/vote-state"
import {
  buildPublicAppPath,
  parseLocationRoute,
  type PublicRoute,
} from "@/lib/routes"
import type { PublicNewsItem } from "@/types/public-news"

/**
 * Format age like HN: "3 hours ago", "just now", "1 day ago".
 *
 * Kept terse to match the HN-style metadata second line.
 */
function formatAge(publishedAt: string, now: Date = new Date()): string {
  const publishedMs = new Date(publishedAt).getTime()
  const nowMs = now.getTime()
  if (!Number.isFinite(publishedMs) || !Number.isFinite(nowMs)) return "未知时间"
  const deltaSec = Math.max(0, (nowMs - publishedMs) / 1000)
  if (deltaSec < 60) return "刚刚"
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)} 分钟前`
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)} 小时前`
  if (deltaSec < 86400 * 7) return `${Math.floor(deltaSec / 86400)} 天前`
  // Beyond a week, fall back to date.
  return new Date(publishedAt).toLocaleDateString("zh-CN")
}

function domainOf(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return parsed.hostname.replace(/^www\./, "")
  } catch {
    return null
  }
}

function navigateToPublicRoute(route: PublicRoute) {
  window.history.pushState({}, "", buildPublicAppPath(route))
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function handleRowClick(event: MouseEvent<HTMLAnchorElement>, route: PublicRoute) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }
  event.preventDefault()
  navigateToPublicRoute(route)
}

function handleRowKeyDown(event: KeyboardEvent<HTMLElement>, route: PublicRoute) {
  if (event.key !== "Enter" && event.key !== " ") return
  event.preventDefault()
  navigateToPublicRoute(route)
}

export interface NewsListRowProps {
  item: PublicNewsItem
  rank: number
  returnTo?: PublicRoute | null
  isRead?: boolean
  isNew?: boolean
  /** Highlight as a hot row (rank 1-3 typically). */
  hot?: boolean
}

/**
 * HN-style ranked list row.
 *
 * Layout (preserves brand identity — golden accent on rank, Geist font):
 *
 *   1.  News title goes here    (ansa.it · italy)
 *       推荐分 · 来源 · 时间 · 相关 N 条
 *
 * Two-line pattern matches HN. Clicking the row navigates to event detail.
 */
export function NewsListRow({
  item,
  rank,
  returnTo,
  isRead = false,
  isNew = false,
  hot = false,
}: NewsListRowProps) {
  const detailRoute = useMemo(() => {
    const search = new URLSearchParams(item.targetId ? { target_id: item.targetId } : undefined)
    if (returnTo) search.set("return_to", buildPublicAppPath(returnTo))
    return {
      name: "event" as const,
      eventId: item.id,
      targetId: item.targetId || undefined,
      search,
    }
  }, [item.id, item.targetId, returnTo])

  const detailPath = buildPublicAppPath(detailRoute)
  // Defensive fallbacks for cached/old API payloads that may miss HN fields.
  const hnScore = Math.max(0, item.hnScore ?? 0)
  const sourceDomain = domainOf(item.originalUrl) ?? item.source.name
  const isHot = hot || rank <= 3
  const ageLabel = formatAge(item.publishedAt)

  // Phase 2: anonymous upvote with optimistic UI + localStorage persistence.
  const [voted, setVoted] = useState(() => checkVoted(item.id))
  const [localVoteCount, setLocalVoteCount] = useState(item.voteCount ?? 0)
  const handleVoteToggle = useCallback(
    async (clickEvent: MouseEvent<HTMLButtonElement>) => {
      clickEvent.stopPropagation()
      clickEvent.preventDefault()
      if (voted) {
        // Optimistic unvote — revert on API failure.
        setVoted(false)
        setLocalVoteCount((c) => Math.max(0, c - 1))
        unmarkVoted(item.id)
        try {
          const result = await unvotePublicNewsItem(item.id, { targetId: item.targetId })
          setLocalVoteCount(result.voteCount)
        } catch {
          setVoted(true)
          setLocalVoteCount((c) => c + 1)
          markVoted(item.id)
        }
      } else {
        // Optimistic upvote — revert on API failure.
        setVoted(true)
        setLocalVoteCount((c) => c + 1)
        markVoted(item.id)
        try {
          const result = await votePublicNewsItem(item.id, { targetId: item.targetId })
          setLocalVoteCount(result.voteCount)
        } catch {
          setVoted(false)
          setLocalVoteCount((c) => Math.max(0, c - 1))
          unmarkVoted(item.id)
        }
      }
    },
    [item.id, voted],
  )

  return (
    <article
      role="link"
      tabIndex={0}
      aria-label={`${item.title}${item.originalTitle ? ` ${item.originalTitle}` : ""}`}
      data-href={detailPath}
      data-new-entry={isNew ? "true" : undefined}
      onClick={() => {
        navigateToPublicRoute(detailRoute)
      }}
      onKeyDown={(event) => handleRowKeyDown(event, detailRoute)}
      className={`group grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2 gap-y-0.5 px-2 py-1.5 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[2.25rem_minmax(0,1fr)] sm:px-3 sm:py-2 ${
        isNew ? "news-card-entering" : ""
      } ${isRead ? "opacity-70" : ""} ${
        isHot ? "border-l-2 border-l-amber-500/80 dark:border-l-amber-400/80" : "border-l-2 border-l-transparent"
      }`}
    >
      <span
        aria-label={`排名 ${rank}`}
        className={`pt-0.5 text-right font-mono text-sm font-bold tabular-nums sm:text-base ${
          isHot ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
        }`}
      >
        {rank}
      </span>
      <div className="grid min-w-0 gap-0.5">
        <a
          href={detailPath}
          onClick={(event) => handleRowClick(event, detailRoute)}
          className="min-w-0 truncate text-sm font-medium leading-5 text-foreground hover:text-amber-700 hover:underline dark:hover:text-amber-300 sm:text-[15px]"
        >
          <span className="min-w-0 truncate">{item.title}</span>
        </a>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
          <button
            type="button"
            onClick={handleVoteToggle}
            aria-pressed={voted}
            aria-label={voted ? `已投票 ${localVoteCount} 票，点击取消` : `投票，当前 ${localVoteCount} 票`}
            className={`inline-flex items-center gap-0.5 rounded font-medium transition-colors hover:bg-amber-500/10 ${
              voted
                ? "text-amber-600 dark:text-amber-400"
                : "text-muted-foreground hover:text-amber-600 dark:hover:text-amber-400"
            }`}
          >
            <span aria-hidden="true" className="text-[10px]">▲</span>
            <span className="tabular-nums">{localVoteCount}</span>
          </button>
          <span aria-hidden="true">·</span>
          <span
            className="inline-flex items-center gap-0.5 text-amber-700/70 dark:text-amber-300/70"
            aria-label={`推荐分 ${hnScore.toFixed(2)}`}
            title="推荐排序参考分"
          >
            <span>推荐</span>
            <span className="tabular-nums">{hnScore.toFixed(2)}</span>
          </span>
          <span aria-hidden="true">·</span>
          <span className="truncate">
            <span className="font-medium text-foreground/80">({sourceDomain})</span>
          </span>
          {item.targetLabel ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="truncate">{item.targetLabel}</span>
            </>
          ) : null}
          <span aria-hidden="true">·</span>
          <span>{ageLabel}</span>
          {item.relatedCount > 0 ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="truncate">相关 {item.relatedCount}</span>
            </>
          ) : null}
          {item.valueLabel ? (
            <>
              <span aria-hidden="true">·</span>
              <Badge
                variant={item.valueLabel === "精选" ? "default" : "outline"}
                className="h-3.5 rounded px-1 text-[9px] font-normal"
              >
                {item.valueLabel}
              </Badge>
            </>
          ) : null}
        </div>
      </div>
    </article>
  )
}

export type SortMode = "top" | "recent" | "breaking"

export interface NewsListProps {
  items: PublicNewsItem[]
  returnTo?: PublicRoute | null
  readIds?: Set<string>
  recentlyInsertedIds?: Set<string>
  sortMode?: SortMode
  /** Skip rank numbers (used in search/filter results where order is contextual). */
  unranked?: boolean
}

/**
 * HN-style ranked list view. Pure display — sorting is done by callers or
 * inferred from `sortMode`. When `sortMode` is provided, items are sorted here
 * to keep NewsFeedPage logic simple.
 */
export function NewsList({
  items,
  returnTo,
  readIds,
  recentlyInsertedIds,
  sortMode = "top",
  unranked = false,
}: NewsListProps) {
  const sorted = useMemo(() => {
    if (unranked) return items
    const decorated = items.map((item, idx) => ({ item, idx }))
    if (sortMode === "top") {
      decorated.sort((a, b) => {
        const aScore = a.item.hnScore ?? 0
        const bScore = b.item.hnScore ?? 0
        if (aScore !== bScore) return bScore - aScore
        return a.idx - b.idx
      })
    } else if (sortMode === "breaking") {
      decorated.sort((a, b) => {
        const aScore = a.item.breakingScore ?? a.item.valueScore ?? 0
        const bScore = b.item.breakingScore ?? b.item.valueScore ?? 0
        if (aScore !== bScore) return bScore - aScore
        // Tiebreaker: publishedAt desc.
        return new Date(b.item.publishedAt).getTime() - new Date(a.item.publishedAt).getTime()
      })
    } else {
      // "recent" — already in chronological order from server, but stable-sort
      // explicitly to be safe.
      decorated.sort(
        (a, b) =>
          new Date(b.item.publishedAt).getTime() - new Date(a.item.publishedAt).getTime(),
      )
    }
    return decorated.map((entry) => entry.item)
  }, [items, sortMode, unranked])

  if (sorted.length === 0) {
    return (
      <p className="rounded-md border border-dashed px-3 py-3 text-sm text-muted-foreground">
        当前没有匹配的新闻条目。
      </p>
    )
  }

  return (
    <ol className="divide-y" aria-label="新闻排名列表">
      {sorted.map((item, index) => (
        <li key={item.id}>
          <NewsListRow
            item={item}
            rank={index + 1}
            returnTo={returnTo}
            isRead={readIds?.has(item.id) ?? false}
            isNew={recentlyInsertedIds?.has(item.id) ?? false}
          />
        </li>
      ))}
    </ol>
  )
}

/**
 * HN-style sort mode tabs. Pure presentational.
 */
export function SortTabs({
  value,
  onChange,
  counts,
}: {
  value: SortMode
  onChange: (next: SortMode) => void
  counts?: { top: number; recent: number; breaking: number }
}) {
  const tabs: Array<{ id: SortMode; label: string; count?: number }> = [
    { id: "top", label: "推荐", count: counts?.top },
    { id: "recent", label: "最新", count: counts?.recent },
    { id: "breaking", label: "突发", count: counts?.breaking },
  ]
  return (
    <nav
      aria-label="排序模式"
      className="flex w-full min-w-0 items-center gap-0.5 border-b bg-card/40 px-2 py-1 text-xs font-medium"
    >
      {tabs.map((tab) => {
        const active = tab.id === value
        return (
          <button
            key={tab.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(tab.id)}
            className={`inline-flex min-w-0 items-center gap-1 rounded-md px-2.5 py-1 transition-colors hover:bg-accent/60 ${
              active
                ? "bg-amber-500/10 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300"
                : "text-muted-foreground"
            }`}
          >
            <span>{tab.label}</span>
            {typeof tab.count === "number" ? (
              <span className="text-[10px] tabular-nums opacity-70">{tab.count}</span>
            ) : null}
          </button>
        )
      })}
    </nav>
  )
}

// Re-export to avoid name shadowing when consumers import both helpers.
export { parseLocationRoute }
