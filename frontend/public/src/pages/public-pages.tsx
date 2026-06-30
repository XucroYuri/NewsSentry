import { useEffect, useMemo, useRef, useState } from "react"
import type { KeyboardEvent, MouseEvent } from "react"
import {
  ArrowLeftIcon,
  ArrowUpRightIcon,
  BellIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  Globe2Icon,
  HashIcon,
  Loader2Icon,
  MailIcon,
  NewspaperIcon,
  RadioIcon,
  SendIcon,
  SkipForwardIcon,
  XIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SeoHead } from "@/components/seo/seo-head"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { getPublicNewsItem, listPublicNews, PublicNewsApiError } from "@/lib/api"
import { type FeedFilters, groupItemsByDate } from "@/lib/feed-state"
import { getReadIds, markAsRead } from "@/lib/read-state"
import {
  buildDailyDigest,
  type DailyDigestTopicGroup,
  buildRelatedBuckets,
  buildSourceSummaries,
  displayFacetLabel,
  formatFullTime,
  formatTime,
  readableTopicLabel,
  sourceTypeLabel,
  summaryText,
  targetShortLabel,
  todayKey,
} from "@/lib/public-view"
import { buildEventSeoPayload } from "@/lib/seo/site-seo"
import type { FeedState } from "@/hooks/use-public-feed"
import type { PublicAnalysisResponse, PublicNewsItem, PublicNewsSourceType, PublicTargetInfo } from "@/types/public-news"
import { buildPublicAppPath, parseLocationRoute, type PublicRoute } from "@/lib/routes"

function normalizeError(error: unknown) {
  if (error instanceof PublicNewsApiError) return error.message
  if (error instanceof Error) return error.message
  return "公共新闻接口暂时不可用，请稍后重试。"
}

function primaryNewsTitle(item: PublicNewsItem) {
  return item.title?.trim() || item.originalTitle?.trim() || item.id
}

function originalNewsTitle(item: PublicNewsItem) {
  const original = item.originalTitle?.trim()
  const primary = primaryNewsTitle(item)
  if (!original || original === primary) return null
  return original
}

function normalizeComparableText(value: string) {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "")
    .replace(/[的了和与及在是]/gu, "")
}

function isNearDuplicateText(left: string, right: string) {
  const leftText = normalizeComparableText(left)
  const rightText = normalizeComparableText(right)
  if (leftText.length < 8 || rightText.length < 8) return false
  if (leftText.includes(rightText) || rightText.includes(leftText)) return true

  const leftChars = new Set([...leftText])
  const rightChars = new Set([...rightText])
  const smallerSize = Math.min(leftChars.size, rightChars.size)
  if (smallerSize < 8) return false
  let overlap = 0
  for (const char of leftChars) {
    if (rightChars.has(char)) overlap += 1
  }
  return overlap / smallerSize >= 0.78
}

function hotTopicSupplement(item: PublicNewsItem) {
  const title = primaryNewsTitle(item)
  const candidates = [item.summary?.trim(), originalNewsTitle(item)].filter(Boolean) as string[]
  return candidates.find((candidate) => !isNearDuplicateText(title, candidate)) ?? null
}

function uniqueNewsTags(item: PublicNewsItem) {
  const seen = new Set<string>()
  const labels = [
    ...item.regionTags,
    ...item.issueTags,
    ...item.relatedTags,
    ...item.tags,
  ]
  return labels
    .map((label) => readableTopicLabel(label) ?? "")
    .filter((label) => {
      if (!label || seen.has(label)) return false
      seen.add(label)
      return true
    })
    .slice(0, 12)
}

function buildDetailRoute(
  item: PublicNewsItem,
  returnTo?: PublicRoute | null,
): Extract<PublicRoute, { name: "event" }> {
  const search = new URLSearchParams(item.targetId ? { target_id: item.targetId } : undefined)
  if (returnTo) search.set("return_to", buildPublicAppPath(returnTo))
  return {
    name: "event",
    eventId: item.id,
    targetId: item.targetId || undefined,
    search,
  }
}

function navigateToPublicRoute(route: PublicRoute) {
  window.history.pushState({}, "", buildPublicAppPath(route))
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function handleRouteAnchorClick(event: MouseEvent<HTMLAnchorElement>, route: PublicRoute) {
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

function handleRouteCardKeyDown(event: KeyboardEvent<HTMLElement>, route: PublicRoute) {
  if (event.key !== "Enter" && event.key !== " ") return
  event.preventDefault()
  navigateToPublicRoute(route)
}

function CopySummaryButton({ item }: { item: PublicNewsItem }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => {
        const text = summaryText(item)
        void navigator.clipboard?.writeText(text)
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1800)
      }}
    >
      <CopyIcon className="size-4" aria-hidden="true" />
      {copied ? "已复制" : "复制摘要"}
    </Button>
  )
}

function LiveUpdateBanner({ count, onApply }: { count: number; onApply: () => void }) {
  if (count <= 0) return null
  return (
    <div className="sticky top-[4.25rem] z-20 flex justify-center">
      <Button type="button" size="sm" onClick={onApply} className="shadow-md" aria-live="polite">
        <BellIcon className="size-4" aria-hidden="true" />有 {count} 条新动态
      </Button>
    </div>
  )
}

function NewsCard({
  item,
  returnTo,
  isNew = false,
  isRead = false,
}: {
  item: PublicNewsItem
  returnTo?: PublicRoute | null
  isNew?: boolean
  isRead?: boolean
}) {
  const [previewImage, setPreviewImage] = useState<string | null>(null)
  const title = primaryNewsTitle(item)
  const originalTitle = originalNewsTitle(item)
  const summary = item.summary?.trim()
  const detailRoute = buildDetailRoute(item, returnTo)
  const targetLabel = targetShortLabel(item.targetLabel)
  const imageUrl = item.imageUrls?.find((url) => url.trim())
  const tags = uniqueNewsTags(item)
  const breakingScore = Math.round(item.valueScore ?? 0)
  const detailPath = buildPublicAppPath(detailRoute)

  return (
    <>
      <article
        role="link"
        tabIndex={0}
        aria-label={`${title}${originalTitle ? ` ${originalTitle}` : ""}`}
        data-href={detailPath}
        data-new-entry={isNew ? "true" : undefined}
        onClick={() => {
          navigateToPublicRoute(detailRoute)
          markAsRead(item.id)
        }}
        onKeyDown={(event) => handleRouteCardKeyDown(event, detailRoute)}
        className={`group block cursor-pointer rounded-md border bg-card/95 px-2.5 py-2 text-card-foreground transition-colors hover:border-primary/45 hover:bg-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-card/80 ${
          isNew ? "news-card-entering" : ""
        } ${isRead ? "opacity-70" : ""}`}
      >
        <div className="grid min-w-0 gap-1.5">
          <div className="flex min-w-0 items-start justify-between gap-2 text-[11px] text-muted-foreground">
            <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <span className="inline-flex min-w-0 items-center gap-1">
                <Globe2Icon className="size-3 shrink-0" aria-hidden="true" />
                <span className="truncate">{item.source.name}</span>
              </span>
              <span className="text-muted-foreground/80">{sourceTypeLabel(item.source.type)}</span>
              <Badge variant="outline" className="h-4 rounded px-1 text-[9px] font-normal" title={item.targetLabel}>
                {targetLabel}
              </Badge>
              {tags.map((tag) => (
                <Badge
                  key={tag}
                  variant="secondary"
                  className="h-4 rounded px-1 text-[9px] font-normal"
                >
                  {tag}
                </Badge>
              ))}
            </div>
            <Badge
              aria-label={`Breaking News 分值 ${breakingScore}`}
              className="ml-auto h-5 rounded-full px-2 text-[11px] font-semibold"
            >
              {breakingScore}
            </Badge>
          </div>

          <div className="grid min-w-0 gap-2">
            <div className="grid min-w-0 gap-1.5">
              <div className={imageUrl ? "grid gap-2 md:grid-cols-[minmax(0,1fr)_148px]" : "grid gap-1.5"}>
                <div className="grid min-w-0 gap-1">
                  <h2 className="text-sm font-semibold leading-5 text-foreground">
                    {title}
                  </h2>
                  {originalTitle ? (
                    <p className="line-clamp-1 text-xs leading-4 text-muted-foreground">
                      {originalTitle}
                    </p>
                  ) : null}
                  {summary ? (
                    <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {summary}
                    </p>
                  ) : null}
                </div>
                {imageUrl ? (
                  <button
                    type="button"
                    aria-label={`浏览大图：${title}`}
                    className="group/image overflow-hidden rounded-md border bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      setPreviewImage(imageUrl)
                    }}
                  >
                    <img
                      src={imageUrl}
                      alt={`新闻缩略图：${title}`}
                      className="aspect-[16/10] h-full w-full object-cover transition-transform group-hover/image:scale-[1.02]"
                      loading="lazy"
                    />
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </article>
      {previewImage ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="新闻图片预览"
          className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm"
          onClick={() => setPreviewImage(null)}
        >
          <div className="relative max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-lg border bg-card shadow-xl">
            <button
              type="button"
              aria-label="关闭图片预览"
              className="absolute right-2 top-2 z-10 inline-flex size-8 items-center justify-center rounded-md border bg-background/90 text-foreground shadow-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(event) => {
                event.stopPropagation()
                setPreviewImage(null)
              }}
            >
              <XIcon className="size-4" aria-hidden="true" />
            </button>
            <img
              src={previewImage}
              alt={`新闻大图：${title}`}
              className="max-h-[90vh] w-full object-contain"
            />
          </div>
        </div>
      ) : null}
    </>
  )
}

function LoadingFeed() {
  return (
    <div aria-label="紧凑加载状态" className="divide-y py-2">
      <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
        <Loader2Icon className="size-3.5 animate-spin text-primary" aria-hidden="true" />
        <span className="font-medium text-foreground">更新中</span>
        <Skeleton className="h-3 w-24" />
      </div>
      <div>
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="grid gap-2 px-3 py-3">
            <Skeleton className="h-3 w-36" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyExplanation({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex flex-col gap-1 border-b px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
      <Badge variant="outline" className="w-fit">
        等待内容
      </Badge>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-2 border-b px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <Badge variant="destructive" className="mb-1 w-fit">
          加载失败
        </Badge>
        <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{message}</p>
      </div>
      <Button onClick={onRetry} className="w-fit shrink-0" size="sm">
        重试
      </Button>
    </div>
  )
}

export function NewsFeedPage({
  filters,
  state,
  loadingMore,
  onRefresh,
  onLoadMore,
  onApplyPending,
}: {
  filters: FeedFilters
  state: FeedState
  loadingMore: boolean
  onRefresh: () => void
  onLoadMore: () => void
  onApplyPending: () => void
}) {
  const [collapsedGroupKeys, setCollapsedGroupKeys] = useState<Set<string>>(() => new Set())
  const grouped = useMemo(() => groupItemsByDate(state.items), [state.items])
  const recentlyInsertedIds = useMemo(
    () => new Set(state.recentlyInsertedIds),
    [state.recentlyInsertedIds],
  )
  const topItems = useMemo(
    () =>
      [...state.items]
        .sort((left, right) => (right.valueScore ?? 0) - (left.valueScore ?? 0))
        .slice(0, 3),
    [state.items],
  )
  const feedRoute = useMemo(() => {
    const search = new URLSearchParams()
    if (filters.targetId) search.set("target_id", filters.targetId)
    if (filters.sourceId) search.set("source_id", filters.sourceId)
    if (filters.category) search.set("category", filters.category)
    if (filters.search) search.set("q", filters.search)
    if (filters.date) search.set("date", filters.date)
    return {
      name: "feed",
      channel: filters.channel,
      search,
    } satisfies Extract<PublicRoute, { name: "feed" }>
  }, [filters.category, filters.channel, filters.date, filters.search, filters.sourceId, filters.targetId])
  const hasItems = state.items.length > 0

  // 无限滚动：观察 sentinel div 进入视口时自动加载更多
  const sentinelRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef(onLoadMore)
  loadMoreRef.current = onLoadMore
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !loadingMore && state.nextCursor) {
          loadMoreRef.current()
        }
      },
      { rootMargin: "200px 0px 0px 0px" },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadingMore, state.nextCursor])

  const readIds = useMemo(() => getReadIds(), [state.items.length])

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80">
      <LiveUpdateBanner count={state.pendingNewItems.length} onApply={onApplyPending} />

      {state.status === "loading" ? <LoadingFeed /> : null}
      {state.status === "error" ? (
        <ErrorState message={state.error ?? "加载失败"} onRetry={onRefresh} />
      ) : null}
      {hasItems ? (
        <div>
          <section className="border-b px-3 py-1.5" aria-label="当前热点">
            <div className="mb-1 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-xs font-semibold">当前热点</h2>
              </div>
              <span className="text-[10px] uppercase text-muted-foreground">TOP {topItems.length}</span>
            </div>
            <div className="divide-y">
              {topItems.map((item, index) => {
                const detailRoute = buildDetailRoute(item, feedRoute)
                const supplement = hotTopicSupplement(item)
                return (
                  <a
                    key={item.id}
                    href={buildPublicAppPath(detailRoute)}
                    onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
                    className="grid gap-x-2 gap-y-0.5 px-1 py-1 text-sm hover:bg-muted/30 md:grid-cols-[1.25rem_minmax(0,1fr)_auto] md:items-center"
                  >
                    <span className="text-xs font-semibold text-primary">{index + 1}</span>
                    <span className="line-clamp-1 font-semibold">{item.title}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {item.source.name} · {formatTime(item.publishedAt)}
                    </span>
                    {supplement ? (
                      <span className="hidden line-clamp-1 text-[11px] text-muted-foreground sm:block md:col-start-2 md:col-end-4">
                        {supplement}
                      </span>
                    ) : null}
                  </a>
                )
              })}
            </div>
          </section>
          {grouped.map((group) => {
            const collapsed = collapsedGroupKeys.has(group.key)
            return (
            <section key={group.key} aria-label={group.label} className="grid gap-2 px-3 py-3">
              <button
                type="button"
                aria-expanded={!collapsed}
                className="flex items-center gap-2 text-left text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() =>
                  setCollapsedGroupKeys((current) => {
                    const next = new Set(current)
                    if (next.has(group.key)) {
                      next.delete(group.key)
                    } else {
                      next.add(group.key)
                    }
                    return next
                  })
                }
              >
                <span>{group.label}</span>
                <span className="h-px flex-1 bg-border" />
                <span className="text-xs font-normal text-muted-foreground">{group.items.length} 条</span>
                <ChevronRightIcon
                  className={`size-3.5 transition-transform ${collapsed ? "" : "rotate-90"}`}
                  aria-hidden="true"
                />
              </button>
              {collapsed ? null : (
                <div className="grid gap-2">
                  {group.items.map((item) => (
                  <div key={item.id} className="grid gap-2 md:grid-cols-[3.5rem_0.75rem_minmax(0,1fr)]">
                    <time className="pt-3 text-xs font-semibold text-muted-foreground">
                      {formatTime(item.publishedAt)}
                    </time>
                    <div className="hidden md:grid md:justify-center">
                      <span className="mt-4 size-2 rounded-full bg-primary shadow-[var(--shadow-primary-soft)]" />
                    </div>
                    <NewsCard item={item} returnTo={feedRoute} isNew={recentlyInsertedIds.has(item.id)} isRead={readIds.has(item.id)} />
                  </div>
                  ))}
                </div>
              )}
            </section>
            )
          })}
          <div
            ref={sentinelRef}
            className="flex items-center justify-center border-t px-4 py-4"
            aria-label="加载更多区域"
          >
            {loadingMore ? (
              <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2Icon className="size-4 animate-spin text-primary" aria-hidden="true" />
                加载中...
              </span>
            ) : state.nextCursor ? (
              <span className="text-xs text-muted-foreground">
                <NewspaperIcon className="mr-1.5 inline size-3.5" aria-hidden="true" />
                加载更多
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">
                <NewspaperIcon className="mr-1.5 inline size-3.5" aria-hidden="true" />
                没有更多了
              </span>
            )}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function eventTimeValue(item: PublicNewsItem) {
  const time = new Date(item.publishedAt).getTime()
  return Number.isNaN(time) ? 0 : time
}

function sortBreakingItems(items: PublicNewsItem[]) {
  return [...items].sort(
    (left, right) =>
      (right.valueScore ?? 0) - (left.valueScore ?? 0) ||
      eventTimeValue(right) - eventTimeValue(left),
  )
}

function sortRecentItems(items: PublicNewsItem[]) {
  return [...items].sort((left, right) => eventTimeValue(right) - eventTimeValue(left))
}

function QuickEntryButton({
  label,
  count,
  onClick,
}: {
  label: string
  count: number
  onClick: () => void
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-8 min-w-0 justify-between gap-2 rounded-md px-2 text-xs"
      onClick={onClick}
    >
      <span className="truncate">{label}</span>
      <span className="shrink-0 text-[10px] text-muted-foreground">{count}</span>
    </Button>
  )
}

export function BreakingHomePage({
  state,
  targets,
  facets,
  onRefresh,
  onOpenAll,
  onSelectTarget,
  onSelectIssue,
  onApplyPending,
}: {
  state: FeedState
  targets: PublicTargetInfo[]
  facets: {
    issues: Array<{ id: string; label: string; count: number }>
    related: Array<{ id: string; label: string; count: number }>
  }
  onRefresh: () => void
  onOpenAll: () => void
  onSelectTarget: (targetId: string) => void
  onSelectIssue: (issue: string) => void
  onApplyPending: () => void
}) {
  const ranked = useMemo(() => sortBreakingItems(state.items), [state.items])
  const recent = useMemo(() => sortRecentItems(state.items).slice(0, 6), [state.items])
  const lead = ranked[0]
  const leadSupplement = lead ? hotTopicSupplement(lead) : null
  const topItems = ranked.slice(0, 3)
  const regionEntries = useMemo(
    () =>
      targets
        .filter((target) => target.event_count > 0)
        .sort((left, right) => right.event_count - left.event_count)
        .slice(0, 8),
    [targets],
  )
  const issueEntries = useMemo(
    () =>
      facets.issues
        .map((issue) => ({
          ...issue,
          displayLabel: displayFacetLabel(issue.label) ?? displayFacetLabel(issue.id),
        }))
        .filter(
          (issue): issue is typeof issue & { displayLabel: string } =>
            Boolean(issue.displayLabel),
        )
        .sort((left, right) => right.count - left.count)
        .slice(0, 8),
    [facets.issues],
  )
  const homeRoute: Extract<PublicRoute, { name: "feed" }> = {
    name: "feed",
    channel: "featured",
    search: new URLSearchParams(),
  }
  const leadRoute = lead ? buildDetailRoute(lead, homeRoute) : null

  if (state.status === "loading") {
    return (
      <section className="overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80" aria-label="极速突发">
        <LoadingFeed />
      </section>
    )
  }

  if (state.status === "error") {
    return <ErrorState message={state.error ?? "加载失败"} onRetry={onRefresh} />
  }

  if (!lead) {
    return (
      <section className="overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80" aria-label="极速突发">
        <EmptyExplanation
          title="暂无突发精选"
          description="高价值、分类明确的新闻会自动进入极速突发首页。"
        />
      </section>
    )
  }

  return (
    <section className="grid min-w-0 gap-3" aria-label="极速突发首页">
      <LiveUpdateBanner count={state.pendingNewItems.length} onApply={onApplyPending} />

      <section className="overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80" aria-label="极速突发">
        <div className="grid gap-3 border-b px-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Badge className="rounded-full px-2 text-[10px] uppercase tracking-normal">Breaking</Badge>
              <span className="text-[11px] text-muted-foreground">
                {state.total} 条精选信号 · {formatTime(lead.publishedAt)} 更新
              </span>
            </div>
            <h1 className="text-xl font-semibold leading-tight">极速突发</h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              优先展示高价值、分类明确的突发新闻；完整时间线继续放在新闻纵览。
            </p>
          </div>
          <Button type="button" variant="outline" size="sm" className="w-fit rounded-md" onClick={onOpenAll}>
            <NewspaperIcon className="size-4" aria-hidden="true" />
            新闻纵览
          </Button>
        </div>

        {leadRoute ? (
          <article>
            <a
              href={buildPublicAppPath(leadRoute)}
              onClick={(event) => handleRouteAnchorClick(event, leadRoute)}
              className="grid gap-3 px-3 py-4 hover:bg-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:grid-cols-[minmax(0,1fr)_14rem]"
              aria-label={`主突发新闻 ${primaryNewsTitle(lead)}`}
            >
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="secondary" className="rounded-md">
                    主突发
                  </Badge>
                  <span>{lead.source.name}</span>
                  <span>{targetShortLabel(lead.targetLabel)}</span>
                  <span>{formatFullTime(lead.publishedAt)}</span>
                </div>
                <h2 className="text-lg font-semibold leading-7 text-foreground sm:text-xl">
                  {primaryNewsTitle(lead)}
                </h2>
                {leadSupplement ? (
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">
                    {leadSupplement}
                  </p>
                ) : null}
                {lead.recommendationReason ? (
                  <p className="mt-3 rounded-md border bg-background/70 px-3 py-2 text-xs leading-5 text-muted-foreground">
                    <span className="font-medium text-foreground">为什么重要：</span>
                    {lead.recommendationReason}
                  </p>
                ) : null}
              </div>
              <div className="grid content-between gap-3 rounded-md border bg-background/70 p-3">
                <div>
                  <p className="text-xs text-muted-foreground">Breaking News 分值</p>
                  <p className="mt-1 text-3xl font-semibold">{Math.round(lead.valueScore ?? 0)}</p>
                </div>
                <div className="flex flex-wrap gap-1">
                  {uniqueNewsTags(lead).slice(0, 5).map((tag) => (
                    <Badge key={tag} variant="outline" className="rounded px-1.5 text-[10px] font-normal">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            </a>
          </article>
        ) : null}
      </section>

      <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)]">
        <section className="overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80" aria-label="高价值动态">
          <div className="border-b px-3 py-2">
            <h2 className="text-sm font-semibold">Top 3 高价值动态</h2>
          </div>
          <div className="divide-y">
            {topItems.map((item, index) => {
              const detailRoute = buildDetailRoute(item, homeRoute)
              return (
                <article key={item.id}>
                  <a
                    href={buildPublicAppPath(detailRoute)}
                    onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
                    className="grid gap-1 px-3 py-2.5 hover:bg-accent/15 sm:grid-cols-[2rem_minmax(0,1fr)_auto] sm:items-start"
                  >
                    <span className="text-lg font-semibold text-primary">{index + 1}</span>
                    <span className="min-w-0">
                      <span className="line-clamp-1 text-sm font-semibold">{primaryNewsTitle(item)}</span>
                      <span className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                        {item.source.name} · {formatTime(item.publishedAt)}
                      </span>
                    </span>
                    <Badge className="w-fit rounded-full px-2">{Math.round(item.valueScore ?? 0)}</Badge>
                  </a>
                </article>
              )
            })}
          </div>
        </section>

        <section className="overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80" aria-label="最近推进">
          <div className="border-b px-3 py-2">
            <h2 className="text-sm font-semibold">最近推进</h2>
          </div>
          <div className="divide-y">
            {recent.map((item) => {
              const detailRoute = buildDetailRoute(item, homeRoute)
              return (
                <article key={item.id}>
                  <a
                    href={buildPublicAppPath(detailRoute)}
                    onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
                    className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-2 px-3 py-2 text-sm hover:bg-accent/15"
                  >
                    <time className="text-xs font-medium text-muted-foreground">{formatTime(item.publishedAt)}</time>
                    <span className="line-clamp-1 font-medium">{primaryNewsTitle(item)}</span>
                  </a>
                </article>
              )
            })}
          </div>
        </section>
      </div>

      <section className="grid gap-3 rounded-lg border bg-card/95 p-3 dark:bg-card/80" aria-label="突发快捷入口">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">快速进入完整时间线</h2>
          <Button type="button" variant="ghost" size="sm" className="h-7 rounded-md px-2 text-xs" onClick={onOpenAll}>
            全部新闻
            <ChevronRightIcon className="size-3.5" aria-hidden="true" />
          </Button>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="grid min-w-0 gap-2">
            <p className="text-xs font-medium text-muted-foreground">地区</p>
            <div className="flex flex-wrap gap-1.5">
              {regionEntries.map((target) => (
                <QuickEntryButton
                  key={target.target_id}
                  label={targetShortLabel(target.display_name)}
                  count={target.event_count}
                  onClick={() => onSelectTarget(target.target_id)}
                />
              ))}
            </div>
          </div>
          <div className="grid min-w-0 gap-2">
            <p className="text-xs font-medium text-muted-foreground">议题</p>
            <div className="flex flex-wrap gap-1.5">
              {issueEntries.map((issue) => (
                <QuickEntryButton
                  key={issue.id}
                  label={issue.displayLabel}
                  count={issue.count}
                  onClick={() => onSelectIssue(issue.id)}
                />
              ))}
            </div>
          </div>
        </div>
      </section>
    </section>
  )
}

function RelatedSection({
  title,
  items,
  returnTo,
}: {
  title: string
  items: PublicNewsItem[]
  returnTo?: PublicRoute | null
}) {
  return (
    <section className="grid gap-2">
      <h3 className="text-base font-semibold">{title}</h3>
      {items.length > 0 ? (
        <div className="grid gap-2">
          {items.map((item) => (
            (() => {
              const detailRoute = buildDetailRoute(item, returnTo)
              return (
            <a
              key={item.id}
              href={buildPublicAppPath(detailRoute)}
              onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
              className="rounded-md border bg-background p-3 text-sm hover:border-primary/40"
            >
              <span className="font-medium">{primaryNewsTitle(item)}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {item.source.name} · {formatFullTime(item.publishedAt)}
              </span>
            </a>
              )
            })()
          ))}
        </div>
      ) : (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          相关信号待形成。
        </p>
      )}
    </section>
  )
}

export function EventDetailPage({ route }: { route: Extract<PublicRoute, { name: "event" }> }) {
  const [item, setItem] = useState<PublicNewsItem | null>(null)
  const [related, setRelated] = useState<PublicNewsItem[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [error, setError] = useState("")
  const seoPayload = useMemo(
    () =>
      buildEventSeoPayload({
        origin: window.location.origin || "https://news-sentry.com",
        route,
        item,
      }),
    [item, route],
  )
  const feedRoute = useMemo(() => {
    const returnTo = route.search.get("return_to")
    if (!returnTo) {
      return {
        name: "feed",
        channel: "featured",
        search: new URLSearchParams(),
      } satisfies Extract<PublicRoute, { name: "feed" }>
    }
    try {
      const url = new URL(returnTo, window.location.origin)
      return parseLocationRoute({
        pathname: url.pathname,
        search: url.search,
        hash: url.hash,
      })
    } catch {
      return {
        name: "feed",
        channel: "featured",
        search: new URLSearchParams(),
      } satisfies Extract<PublicRoute, { name: "feed" }>
    }
  }, [route.search])
  const sourceRoute: Extract<PublicRoute, { name: "sourceDetail" }> | null = item
    ? {
        name: "sourceDetail",
        sourceId: item.source.id,
        search: new URLSearchParams(),
      }
    : null

  useEffect(() => {
    let cancelled = false
    async function loadDetail() {
      setStatus("loading")
      setError("")
      setItem(null)
      setRelated([])
      try {
        const detail = await getPublicNewsItem(route.eventId, { targetId: route.targetId })
        if (!cancelled) {
          setItem(detail)
          setStatus("ready")
          markAsRead(detail.id)
        }
        // 加载相关新闻：同目标 + 基于 issue/related tags 的更深关联
        const relatedQueries: Promise<Awaited<ReturnType<typeof listPublicNews>>>[] = [
          listPublicNews({
            targetId: route.targetId ?? detail.targetId,
            pageSize: 12,
          }),
        ]
        // 如果新闻有 issue/related tags，额外按首个 tag 查询扩大关联范围
        const crossTag = detail.issueTags[0] || detail.relatedTags[0]
        if (crossTag) {
          relatedQueries.push(
            listPublicNews({
              targetId: route.targetId ?? detail.targetId,
              issue: crossTag,
              pageSize: 8,
            }),
          )
        }
        // 如果有不同的第二个 tag 也查一次
        const secondTag = detail.relatedTags[0] || detail.issueTags[1]
        if (secondTag && secondTag !== crossTag) {
          relatedQueries.push(
            listPublicNews({
              targetId: route.targetId ?? detail.targetId,
              related: secondTag,
              pageSize: 8,
            }),
          )
        }
        try {
          const results = await Promise.allSettled(relatedQueries)
          const allItems: PublicNewsItem[] = []
          for (const result of results) {
            if (result.status === "fulfilled" && result.value.data?.items) {
              allItems.push(...result.value.data.items)
            }
          }
          // 去重
          const seen = new Set<string>()
          const uniqueItems = allItems.filter((item) => {
            if (seen.has(item.id)) return false
            seen.add(item.id)
            return true
          })
          if (!cancelled) {
            setRelated(uniqueItems)
          }
        } catch {
          // Related signals are useful context, but should never block the article itself.
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(normalizeError(loadError))
          setStatus("error")
        }
      }
    }
    void loadDetail()
    return () => {
      cancelled = true
    }
  }, [route.eventId, route.targetId])

  if (status === "loading")
    return (
      <>
        <SeoHead payload={seoPayload} />
        <LoadingFeed />
      </>
    )
  if (status === "error" || !item) {
    return (
      <>
        <SeoHead payload={seoPayload} />
        <ErrorState
          message={error || "新闻详情暂时不可用。"}
          onRetry={() => window.location.reload()}
        />
      </>
    )
  }

  const buckets = buildRelatedBuckets(item, related)
  const title = primaryNewsTitle(item)
  const originalTitle = originalNewsTitle(item)

  return (
    <>
      <SeoHead payload={seoPayload} />
      <article className="overflow-hidden rounded-lg border bg-background">
        <div className="border-b px-3 py-3 sm:px-4">
          <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
            <a
              href={buildPublicAppPath(feedRoute)}
              onClick={(event) => handleRouteAnchorClick(event, feedRoute)}
            >
              <ArrowLeftIcon className="size-4" aria-hidden="true" />
              返回新闻流
            </a>
          </Button>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant={item.valueLabel === "精选" ? "default" : "secondary"}>
              {item.valueLabel}
            </Badge>
            <span>{formatFullTime(item.publishedAt)}</span>
            <span>{item.source.name}</span>
            <span>{sourceTypeLabel(item.source.type)}</span>
            {item.source.credibilityLabel ? <span>{item.source.credibilityLabel}</span> : null}
          </div>
          <h1 className="mt-2 text-xl font-semibold leading-tight sm:text-2xl">{title}</h1>
          {originalTitle ? (
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{originalTitle}</p>
          ) : null}
        </div>
        <div className="grid gap-4 px-3 py-4 sm:px-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <section className="grid gap-4">
            <div>
              <h2 className="text-base font-semibold">新闻摘要</h2>
              {item.summary ? (
                <p className="mt-2 text-sm leading-7 text-muted-foreground">
                  {item.summary}
                </p>
              ) : null}
            </div>
          {item.recommendationReason ? (
            <div className="rounded-md border bg-muted/35 p-3 text-sm leading-6 text-muted-foreground">
              <span className="font-medium text-foreground">推荐理由：</span>
              {item.recommendationReason}
            </div>
          ) : null}
            {item.imageUrls && item.imageUrls.length > 0 ? (
              <div className="grid gap-2">
                <img
                  src={item.imageUrls[0]}
                  alt=""
                  className="max-h-[360px] w-full rounded-md border object-cover"
                  loading="lazy"
                />
              </div>
            ) : null}
            {item.fullContent ? (
              <div>
                <h2 className="text-base font-semibold">全文</h2>
                <div className="mt-2 whitespace-pre-line text-sm leading-7 text-foreground/90">
                  {item.fullContent}
                </div>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {item.tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
              {item.entities.map((entity) => (
                <Badge key={`${entity.type ?? "entity"}-${entity.name}`} variant="secondary">
                  {entity.name}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <CopySummaryButton item={item} />
              {item.originalUrl ? (
                <Button asChild size="sm">
                  <a href={item.originalUrl} target="_blank" rel="noreferrer">
                    查看原文
                    <ArrowUpRightIcon className="size-4" aria-hidden="true" />
                  </a>
                </Button>
              ) : null}
            </div>
          </section>
          <aside className="grid h-fit gap-3">
            <Card className="rounded-lg">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">来源</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 text-sm">
                <p className="font-medium">{item.source.name}</p>
                <p className="text-muted-foreground">{sourceTypeLabel(item.source.type)}</p>
                {item.source.credibilityLabel ? (
                  <p className="text-muted-foreground">可信度：{item.source.credibilityLabel}</p>
                ) : null}
                {sourceRoute ? (
                  <Button asChild variant="outline" size="sm" className="mt-2 w-fit">
                    <a
                      href={buildPublicAppPath(sourceRoute)}
                      onClick={(event) => handleRouteAnchorClick(event, sourceRoute)}
                    >
                      查看来源
                    </a>
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          </aside>
        </div>
        <div className="grid gap-3 border-t px-3 py-4 sm:px-4 lg:grid-cols-3">
          <RelatedSection title="同来源信号" items={buckets.sameSource} returnTo={feedRoute} />
          <RelatedSection title="同目标信号" items={buckets.sameTarget} returnTo={feedRoute} />
          <RelatedSection title="同主题信号" items={buckets.sameTopic} returnTo={feedRoute} />
        </div>
      </article>
    </>
  )
}

export function SourceDirectoryPage() {
  const [items, setItems] = useState<PublicNewsItem[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [typeFilter, setTypeFilter] = useState("all")
  const [statusFilter, setStatusFilter] = useState("all")
  const [regionFilter, setRegionFilter] = useState("all")

  useEffect(() => {
    let cancelled = false
    async function loadSources() {
      setStatus("loading")
      try {
        const result = await listPublicNews({ pageSize: 100 })
        if (!cancelled) {
          setItems(result.data?.items ?? [])
          setStatus("ready")
        }
      } catch {
        if (!cancelled) setStatus("error")
      }
    }
    void loadSources()
    return () => {
      cancelled = true
    }
  }, [])

  const sources = useMemo(() => buildSourceSummaries(items), [items])
  const activeCount = sources.filter((source) => source.statusLabel === "近期活跃").length
  const typeOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const source of sources) counts.set(source.type, (counts.get(source.type) ?? 0) + 1)
    return [...counts.entries()]
      .map(([type, count]) => ({ id: type, label: sourceTypeLabel(type as PublicNewsSourceType), count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  }, [sources])
  const statusOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const source of sources) counts.set(source.statusLabel, (counts.get(source.statusLabel) ?? 0) + 1)
    return [...counts.entries()]
      .map(([label, count]) => ({ id: label, label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  }, [sources])
  const regionOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const source of sources) {
      for (const label of source.regionLabels) counts.set(label, (counts.get(label) ?? 0) + 1)
    }
    return [...counts.entries()]
      .map(([label, count]) => ({ id: label, label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
      .slice(0, 16)
  }, [sources])
  const filteredSources = sources.filter((source) => {
    if (typeFilter !== "all" && source.type !== typeFilter) return false
    if (statusFilter !== "all" && source.statusLabel !== statusFilter) return false
    if (regionFilter !== "all" && !source.regionLabels.includes(regionFilter)) return false
    return true
  })
  const groupedSources = useMemo(() => {
    const groups = new Map<string, typeof filteredSources>()
    for (const source of filteredSources) {
      const label = sourceTypeLabel(source.type)
      groups.set(label, [...(groups.get(label) ?? []), source])
    }
    return [...groups.entries()]
      .map(([label, groupSources]) => ({
        label,
        sources: groupSources.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
      }))
      .sort((a, b) => b.sources.length - a.sources.length || a.label.localeCompare(b.label))
  }, [filteredSources])
  const totalNewsCount = sources.reduce((total, source) => total + source.count, 0)

  return (
    <section className="overflow-hidden rounded-lg border bg-background" aria-label="信源管理">
      <div className="grid gap-3 border-b px-3 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold leading-tight">信源管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            按类型、地区和活跃度整理公开信源，方便编辑维护采集覆盖和最近样本。
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs sm:min-w-[320px]">
          <div className="rounded-md border bg-card px-2.5 py-2">
            <p className="text-muted-foreground">信源</p>
            <p className="mt-1 text-lg font-semibold">{sources.length}</p>
          </div>
          <div className="rounded-md border bg-card px-2.5 py-2">
            <p className="text-muted-foreground">活跃</p>
            <p className="mt-1 text-lg font-semibold">{activeCount}</p>
          </div>
          <div className="rounded-md border bg-card px-2.5 py-2">
            <p className="text-muted-foreground">样本</p>
            <p className="mt-1 text-lg font-semibold">{totalNewsCount}</p>
          </div>
        </div>
      </div>
      {status === "loading" ? <LoadingFeed /> : null}
      {status === "error" ? (
        <ErrorState message="信源管理暂时不可用。" onRetry={() => window.location.reload()} />
      ) : null}
      {status === "ready" && sources.length === 0 ? (
        <EmptyExplanation title="暂无信源样本" description="公共新闻进入后，信源管理会自动形成分类和最近样本。" />
      ) : null}
      {sources.length > 0 ? (
        <div className="grid gap-3 p-3">
          <section
            aria-label="信源分类筛选"
            className="grid gap-2 rounded-md border bg-card/70 p-2 text-xs"
          >
            <SourceFilterRow
              label="类型"
              value={typeFilter}
              onChange={setTypeFilter}
              allLabel="类型"
              allCount={sources.length}
              options={typeOptions}
            />
            <SourceFilterRow
              label="活跃"
              value={statusFilter}
              onChange={setStatusFilter}
              allLabel="状态"
              allCount={sources.length}
              options={statusOptions}
            />
            {regionOptions.length > 0 ? (
              <SourceFilterRow
                label="地区"
                value={regionFilter}
                onChange={setRegionFilter}
                allLabel="地区"
                allCount={sources.length}
                options={regionOptions}
              />
            ) : null}
          </section>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <h2 className="font-semibold">按类型分组</h2>
            <span className="text-xs text-muted-foreground">
              当前显示 {filteredSources.length} / {sources.length} 个信源
            </span>
          </div>
          {groupedSources.map((group) => (
            <section key={group.label} className="overflow-hidden rounded-md border bg-card/80">
              <div className="flex items-center justify-between border-b bg-muted/25 px-3 py-2">
                <h3 className="text-sm font-semibold">{group.label}</h3>
                <span className="text-xs text-muted-foreground">{group.sources.length} 个信源</span>
              </div>
              <div className="hidden grid-cols-[minmax(11rem,1.4fr)_minmax(7rem,0.8fr)_minmax(8rem,1fr)_minmax(12rem,1.2fr)_minmax(16rem,1.6fr)] gap-3 border-b px-3 py-2 text-xs font-medium text-muted-foreground lg:grid">
                <span>信源 ID</span>
                <span>状态</span>
                <span>覆盖地区</span>
                <span>议题 / 相关</span>
                <span>最新样本</span>
              </div>
              <div className="divide-y">
                {group.sources.map((source) => {
                  const sourceRoute: Extract<PublicRoute, { name: "sourceDetail" }> = {
                    name: "sourceDetail",
                    sourceId: source.id,
                    search: new URLSearchParams(),
                  }
                  const topicLabels = [...source.issueLabels, ...source.relatedLabels].slice(0, 4)
                  return (
                    <a
                      key={source.id}
                      href={buildPublicAppPath(sourceRoute)}
                      onClick={(event) => handleRouteAnchorClick(event, sourceRoute)}
                      className="grid gap-2 px-3 py-2.5 text-sm transition-colors hover:bg-accent/20 lg:grid-cols-[minmax(11rem,1.4fr)_minmax(7rem,0.8fr)_minmax(8rem,1fr)_minmax(12rem,1.2fr)_minmax(16rem,1.6fr)] lg:items-start lg:gap-3"
                    >
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-semibold">{source.name}</span>
                          <Badge variant="outline" className="h-5 rounded px-1.5 text-[10px] font-normal">
                            {source.count}
                          </Badge>
                        </div>
                        <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{source.id}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant={source.statusLabel === "近期活跃" ? "default" : "secondary"} className="h-5 rounded px-1.5 text-[10px]">
                          {source.statusLabel}
                        </Badge>
                        <span className="text-xs text-muted-foreground">近期 {source.count} 条</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {source.regionLabels.slice(0, 3).map((label) => (
                          <Badge key={label} variant="secondary" className="h-5 rounded px-1.5 text-[10px] font-normal">
                            {label}
                          </Badge>
                        ))}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {topicLabels.length > 0 ? topicLabels.map((label) => (
                          <Badge key={label} variant="outline" className="h-5 rounded px-1.5 text-[10px] font-normal">
                            {label}
                          </Badge>
                        )) : <span className="text-xs text-muted-foreground">待补充标签</span>}
                      </div>
                      <div className="min-w-0">
                        {source.latestTitle ? <p className="line-clamp-1 font-medium">{source.latestTitle}</p> : null}
                        {source.latestSummary ? (
                          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{source.latestSummary}</p>
                        ) : null}
                      </div>
                    </a>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function SourceFilterRow({
  label,
  value,
  onChange,
  allLabel,
  allCount,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  allLabel: string
  allCount: number
  options: Array<{ id: string; label: string; count: number }>
}) {
  return (
    <div className="grid items-start gap-2 sm:grid-cols-[3rem_minmax(0,1fr)]">
      <span className="pt-1 text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          variant={value === "all" ? "default" : "outline"}
          size="sm"
          className="h-7 rounded-md px-2 text-xs"
          onClick={() => onChange("all")}
        >
          {allLabel} <span className="ml-1 text-[10px] opacity-75">{allCount}</span>
        </Button>
        {options.map((option) => (
          <Button
            key={option.id}
            type="button"
            variant={value === option.id ? "default" : "outline"}
            size="sm"
            className="h-7 rounded-md px-2 text-xs"
            onClick={() => onChange(option.id)}
          >
            {option.label} <span className="ml-1 text-[10px] opacity-75">{option.count}</span>
          </Button>
        ))}
      </div>
    </div>
  )
}

export function SourceDetailPage({ sourceId }: { sourceId: string }) {
  const [items, setItems] = useState<PublicNewsItem[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const readIds = useMemo(() => getReadIds(), [items.length])

  useEffect(() => {
    let cancelled = false
    async function loadSource() {
      setStatus("loading")
      try {
        const result = await listPublicNews({ sourceId, pageSize: 20 })
        if (!cancelled) {
          setItems(result.data?.items ?? [])
          setStatus("ready")
        }
      } catch {
        if (!cancelled) setStatus("error")
      }
    }
    void loadSource()
    return () => {
      cancelled = true
    }
  }, [sourceId])

  const source = items[0]?.source
  const heading = source?.name ?? sourceId
  const summary = buildSourceSummaries(items)[0]

  const sourceRoute: Extract<PublicRoute, { name: "sourceDetail" }> = {
    name: "sourceDetail",
    sourceId,
    search: new URLSearchParams(),
  }

  return (
    <section className="overflow-hidden rounded-lg border bg-background">
      <div className="border-b px-3 py-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <a
            href={buildPublicAppPath({ name: "sources", search: new URLSearchParams() })}
            onClick={(event) =>
              handleRouteAnchorClick(event, { name: "sources", search: new URLSearchParams() })
            }
          >
            <ArrowLeftIcon className="size-4" aria-hidden="true" />
            信源管理
          </a>
        </Button>
        <Badge variant="outline" className="mb-2">
          来源详情
        </Badge>
        <h1 className="text-xl font-semibold leading-tight">{heading}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {summary ? `${sourceTypeLabel(summary.type)} · ${summary.statusLabel}` : "等待更多样本"}
        </p>
      </div>
      {status === "loading" ? <LoadingFeed /> : null}
      {status === "error" ? (
        <ErrorState message="来源详情暂时不可用。" onRetry={() => window.location.reload()} />
      ) : null}
      {status === "ready" && items.length === 0 ? (
        <EmptyExplanation title="该来源暂无公开新闻" description="采集仍在进行中，稍后会显示该来源最近报道。" />
      ) : null}
      {items.map((item) => (
        <NewsCard key={item.id} item={item} returnTo={sourceRoute} isRead={readIds.has(item.id)} />
      ))}
    </section>
  )
}

function DailyBriefRow({
  item,
  index,
  returnTo,
}: {
  item: PublicNewsItem
  index: number
  returnTo: PublicRoute
}) {
  const detailRoute = buildDetailRoute(item, returnTo)
  const title = primaryNewsTitle(item)
  const originalTitle = originalNewsTitle(item)
  return (
    <article className="grid gap-2 px-3 py-3 sm:grid-cols-[2.25rem_minmax(0,1fr)_auto] sm:items-start">
      <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
        {index + 1}
      </span>
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
          <span>{formatTime(item.publishedAt)}</span>
          <span>{item.source.name}</span>
          <Badge variant="outline" className="h-5 rounded px-1.5 text-[10px]">
            {targetShortLabel(item.targetLabel)}
          </Badge>
          {item.valueScore !== undefined && item.valueScore !== null ? (
            <span className="font-medium text-primary">{Math.round(item.valueScore)}</span>
          ) : null}
        </div>
        <h2 className="line-clamp-2 text-sm font-semibold leading-5 sm:text-base">{title}</h2>
        {originalTitle ? (
          <p className="line-clamp-1 text-[11px] leading-4 text-muted-foreground">
            {originalTitle}
          </p>
        ) : null}
        {item.summary ? (
          <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{item.summary}</p>
        ) : null}
        {item.recommendationReason ? (
          <p className="line-clamp-1 text-xs leading-5 text-muted-foreground">
            <span className="font-medium text-foreground">推荐理由：</span>
            {item.recommendationReason}
          </p>
        ) : null}
      </div>
      <Button asChild variant="outline" size="sm" className="h-8 justify-self-start sm:justify-self-end">
        <a
          href={buildPublicAppPath(detailRoute)}
          onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
        >
          详情
          <ChevronRightIcon className="size-3.5" aria-hidden="true" />
        </a>
      </Button>
    </article>
  )
}

function DailyTopicGroupCard({
  group,
  returnTo,
}: {
  group: DailyDigestTopicGroup
  returnTo: PublicRoute
}) {
  return (
    <section className="grid gap-2 rounded-md border bg-card/80 p-3" aria-label={`${group.label}简报`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{group.label}</h3>
        <span className="text-xs text-muted-foreground">{group.count} 条</span>
      </div>
      <div className="grid gap-2">
        {group.items.map((item) => {
          const detailRoute = buildDetailRoute(item, returnTo)
          return (
            <a
              key={item.id}
              href={buildPublicAppPath(detailRoute)}
              onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
              className="grid gap-1 rounded-md px-2 py-1.5 hover:bg-accent/35"
            >
              <span className="line-clamp-2 text-sm font-medium leading-5">{primaryNewsTitle(item)}</span>
              <span className="line-clamp-1 text-xs text-muted-foreground">
                {targetShortLabel(item.targetLabel)} · {item.source.name} · {formatTime(item.publishedAt)}
              </span>
            </a>
          )
        })}
      </div>
    </section>
  )
}

export function DailyPage({ date }: { date?: string }) {
  const selectedDate = date || todayKey()
  const [items, setItems] = useState<PublicNewsItem[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")

  useEffect(() => {
    let cancelled = false
    async function loadDaily() {
      setStatus("loading")
      try {
        const result = await listPublicNews({ date: selectedDate, pageSize: 100 })
        if (!cancelled) {
          setItems(result.data?.items ?? [])
          setStatus("ready")
        }
      } catch {
        if (!cancelled) setStatus("error")
      }
    }
    void loadDaily()
    return () => {
      cancelled = true
    }
  }, [selectedDate])

  const digest = useMemo(() => buildDailyDigest(items, selectedDate), [items, selectedDate])
  const dailyRoute: Extract<PublicRoute, { name: "daily" }> = {
    name: "daily",
    date: selectedDate,
    search: new URLSearchParams(),
  }

  return (
    <section className="overflow-hidden rounded-lg border bg-background">
      <div role="region" aria-label="日报摘要栏" className="border-b px-3 py-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-base font-semibold leading-tight">新闻日报</h1>
            <span className="text-xs text-muted-foreground">{selectedDate}</span>
            <span className="rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground">
              {digest.total > 0 ? `${digest.total} 条` : "采集中"}
            </span>
          </div>
          <Input
            type="date"
            value={selectedDate}
            onChange={(event) => {
              navigateToPublicRoute({
                name: "daily",
                date: event.currentTarget.value,
                search: new URLSearchParams(),
              })
            }}
            className="h-8 w-full text-xs sm:w-36"
            aria-label="选择日报日期"
          />
        </div>
      </div>
      {status === "loading" ? <LoadingFeed /> : null}
      {status === "error" ? (
        <ErrorState message="日报暂时不可用。" onRetry={() => window.location.reload()} />
      ) : null}
      {digest.total > 0 ? (
        <div className="grid gap-3 p-3 sm:p-4">
          <section className="overflow-hidden rounded-lg border bg-card/70" aria-label="今日速读">
            <div className="flex flex-col gap-1 border-b px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-semibold">今日速读</h2>
                <p className="text-xs text-muted-foreground">
                  先读 {digest.topItems.length} 条高价值信号，快速掌握当天主线。
                </p>
              </div>
              <span className="text-xs text-muted-foreground">{digest.date}</span>
            </div>
            <div className="divide-y">
              {digest.topItems.map((item, index) => (
                <DailyBriefRow key={item.id} item={item} index={index} returnTo={dailyRoute} />
              ))}
            </div>
          </section>
          <section className="grid gap-2" aria-label="主题简报">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-base font-semibold">主题简报</h2>
                <p className="text-xs text-muted-foreground">
                  按主题聚合相关报道，避免在长列表里重复扫描。
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                来源：{digest.sourceLabels.slice(0, 4).join("、")}
                {digest.sourceLabels.length > 4 ? ` 等 ${digest.sourceLabels.length} 个` : ""}
              </p>
            </div>
            <div className="grid gap-2 lg:grid-cols-2 2xl:grid-cols-3">
              {digest.topicGroups.map((group) => (
                <DailyTopicGroupCard key={group.label} group={group} returnTo={dailyRoute} />
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  )
}

export function AnalysisPage({
  analysis,
  analysisError,
  targets,
  preferredSection,
}: {
  analysis: PublicAnalysisResponse | null
  analysisError: string | null
  targets: PublicTargetInfo[]
  preferredSection?: string
}) {
  const trendCard = (
    <Card className="rounded-lg">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">主题趋势</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm">
        {analysis?.topic_trends.length ? (
          analysis.topic_trends.slice(0, 6).map((topic) => (
            <div key={topic.topic} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{topic.topic}</span>
              <span className="text-muted-foreground">{topic.current_count ?? topic.event_count ?? 0}</span>
            </div>
          ))
        ) : (
          <p className="text-muted-foreground">趋势样本不足，继续收集后会形成方向。</p>
        )}
      </CardContent>
    </Card>
  )
  const entityCard = (
    <Card className="rounded-lg">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">实体</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm">
        {analysis?.top_entities.length ? (
          analysis.top_entities.slice(0, 8).map((entity) => (
            <div key={`${entity.entity_type ?? "entity"}-${entity.name}`} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{entity.name}</span>
              <span className="text-muted-foreground">{entity.mention_count ?? 0}</span>
            </div>
          ))
        ) : (
          <p className="text-muted-foreground">实体待增强，当前窗口暂无足够实体样本。</p>
        )}
      </CardContent>
    </Card>
  )
  const analysisCards = preferredSection === "entities" ? [entityCard, trendCard] : [trendCard, entityCard]

  return (
    <section className="grid gap-4">
      <div className="rounded-lg border bg-background p-3 sm:p-4">
        <div className="mb-2 flex flex-wrap gap-2">
          <Badge variant="outline">态势</Badge>
          {preferredSection === "entities" ? <Badge variant="secondary">实体优先</Badge> : null}
        </div>
        <h1 className="text-xl font-semibold leading-tight">态势简报</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          趋势、实体、来源分布和追踪链按公开分析快照呈现。
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          {analysisError ? (
            <ErrorState message={analysisError} onRetry={() => window.location.reload()} />
          ) : null}
          <Card className="rounded-lg">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">态势摘要</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              {analysis ? (
                <div className="grid gap-3 sm:grid-cols-4">
                  <div className="rounded-md border bg-muted/35 p-3">
                    <p className="text-muted-foreground">事件总数</p>
                    <p className="mt-1 text-xl font-semibold">{analysis.summary.total_events}</p>
                  </div>
                  <div className="rounded-md border bg-muted/35 p-3">
                    <p className="text-muted-foreground">高价值</p>
                    <p className="mt-1 text-xl font-semibold">{analysis.summary.high_value_events}</p>
                  </div>
                  <div className="rounded-md border bg-muted/35 p-3">
                    <p className="text-muted-foreground">价值均分</p>
                    <p className="mt-1 text-xl font-semibold">
                      {Math.round(analysis.summary.avg_news_value_score ?? 0)}
                    </p>
                  </div>
                  <div className="rounded-md border bg-muted/35 p-3">
                    <p className="text-muted-foreground">中国相关度</p>
                    <p className="mt-1 text-xl font-semibold">
                      {Math.round(analysis.summary.avg_china_relevance ?? 0)}
                    </p>
                  </div>
                </div>
              ) : (
                <EmptyExplanation
                  title="态势样本仍在形成"
                  description="等待更多公开新闻完成分类、实体和来源增强后会生成简报。"
                />
              )}
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {analysisCards.map((card, index) => (
              <div key={preferredSection === "entities" ? `entities-${index}` : `default-${index}`}>
                {card}
              </div>
            ))}
          </div>
        </div>
        <aside className="grid h-fit gap-4">
          <Card className="rounded-lg">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">公开目标</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              {targets.slice(0, 8).map((target) => (
                (() => {
                  const analysisRoute: Extract<PublicRoute, { name: "analysis" }> = {
                    name: "analysis",
                    targetId: target.target_id,
                    section: undefined,
                    search: new URLSearchParams(),
                  }
                  return (
                    <a
                      key={target.target_id}
                      href={buildPublicAppPath(analysisRoute)}
                      onClick={(event) => handleRouteAnchorClick(event, analysisRoute)}
                      className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 hover:border-primary/40"
                    >
                      <span className="min-w-0 truncate">{target.display_name}</span>
                      <span className="text-muted-foreground">{target.event_count}</span>
                    </a>
                  )
                })()
              ))}
              {targets.length === 0 ? (
                <p className="text-muted-foreground">目标列表正在加载。</p>
              ) : null}
            </CardContent>
          </Card>
          <Card className="rounded-lg">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">来源分布</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              {analysis?.source_distribution.length ? (
                analysis.source_distribution.slice(0, 8).map((source) => (
                  <div key={source.source_id} className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate">{source.display_name}</span>
                    <span className="text-muted-foreground">{source.count}</span>
                  </div>
                ))
              ) : (
                <p className="text-muted-foreground">来源分布等待更多公开新闻样本。</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════════
// SubscribePage — 3 步漏斗订阅
// Step 1: 选择地区 → Step 2: 选择信源 → Step 3: 选择议题
// 每步可跳过，最后点击订阅按钮 POST 到后端
// ═══════════════════════════════════════════════════════════════════

interface FunnelOption {
  id: string
  label: string
  count: number
}

interface SourceOption {
  id: string
  name: string
  count: number
}

function useFunnelState() {
  const [regions, setRegions] = useState<FunnelOption[]>([])
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null)
  const [regionsLoading, setRegionsLoading] = useState(true)

  const [sources, setSources] = useState<SourceOption[]>([])
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [sourcesLoading, setSourcesLoading] = useState(false)
  const [sourcesSkipped, setSourcesSkipped] = useState(false)

  const [issues, setIssues] = useState<FunnelOption[]>([])
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null)
  const [issuesLoading, setIssuesLoading] = useState(false)
  const [issuesSkipped, setIssuesSkipped] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const { listTargets } = await import("@/lib/api")
        const result = await listTargets()
        if (!cancelled) {
          setRegions(
            result.targets
              .filter((t) => t.event_count > 0)
              .sort((a, b) => b.event_count - a.event_count)
              .map((t) => ({
                id: t.target_id,
                label: t.display_name,
                count: t.event_count,
              })),
          )
          setRegionsLoading(false)
        }
      } catch {
        if (!cancelled) {
          setRegionsLoading(false)
          setError("无法加载地区列表")
        }
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selectedRegion) {
      setSources([])
      setIssues([])
      setSelectedSource(null)
      setSelectedIssue(null)
      setSourcesSkipped(false)
      setIssuesSkipped(false)
      return
    }
    let cancelled = false
    async function loadSourcesAndIssues() {
      setSourcesLoading(true)
      setIssuesLoading(true)
      setSourcesSkipped(false)
      setIssuesSkipped(false)
      setSelectedSource(null)
      setSelectedIssue(null)
      try {
        const { listPublicNews, listPublicFacets } = await import("@/lib/api")
        const [newsResult, facetsResult] = await Promise.all([
          listPublicNews({ targetId: selectedRegion!, pageSize: 50 }),
          listPublicFacets({ targetId: selectedRegion! }),
        ])
        if (cancelled) return
        const sourceMap = new Map<string, { name: string; count: number }>()
        for (const item of (newsResult.data?.items ?? [])) {
          const prev = sourceMap.get(item.source.id)
          if (prev) {
            prev.count += 1
          } else {
            sourceMap.set(item.source.id, { name: item.source.name, count: 1 })
          }
        }
        setSources(
          Array.from(sourceMap.entries())
            .map(([id, info]) => ({ id, name: info.name, count: info.count }))
            .sort((a, b) => b.count - a.count),
        )
        setIssues(
          (facetsResult.issues ?? []).map((issue) => ({
            id: issue.id,
            label: issue.label,
            count: issue.count,
          })),
        )
      } catch {
        setSources([])
        setIssues([])
      }
      if (!cancelled) {
        setSourcesLoading(false)
        setIssuesLoading(false)
      }
    }
    void loadSourcesAndIssues()
    return () => { cancelled = true }
  }, [selectedRegion])

  async function handleSubscribe(email?: string) {
    setSubmitting(true)
    setError(null)
    try {
      const { resolveUrl } = await import("@/lib/locals-settings")
      const params = new URLSearchParams()
      params.set("target_id", selectedRegion!)
      if (selectedSource && !sourcesSkipped) params.set("source_id", selectedSource)
      if (selectedIssue && !issuesSkipped) params.set("issue", selectedIssue)
      if (email) params.set("email", email)
      const resp = await fetch(resolveUrl(`/api/v1/subscriptions?${params.toString()}`), {
        method: "POST",
      })
      if (!resp.ok) {
        throw new Error(`服务器返回 ${resp.status}`)
      }
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "订阅失败")
    } finally {
      setSubmitting(false)
    }
  }

  function reset() {
    setSelectedRegion(null)
    setSubmitted(false)
    setError(null)
  }

  return {
    regions,
    selectedRegion,
    setSelectedRegion,
    regionsLoading,
    sources,
    selectedSource,
    setSelectedSource,
    sourcesLoading,
    sourcesSkipped,
    setSourcesSkipped,
    issues,
    selectedIssue,
    setSelectedIssue,
    issuesLoading,
    issuesSkipped,
    setIssuesSkipped,
    submitting,
    submitted,
    error,
    handleSubscribe,
    reset,
  }
}

function FunnelDropdown({
  label,
  icon: Icon,
  options,
  selectedId,
  onSelect,
  loading,
  skipped,
  onSkip,
  placeholder = "请选择...",
  showSkippedHint = true,
}: {
  label: string
  icon: React.ElementType
  options: { id: string; label: string; name?: string; count: number }[]
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
  skipped?: boolean
  onSkip?: () => void
  placeholder?: string
  showSkippedHint?: boolean
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClick as unknown as EventListener)
      return () => document.removeEventListener("mousedown", handleClick as unknown as EventListener)
    }
  }, [open])

  const selectedOption = options.find((o) => o.id === selectedId)

  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Icon className="size-4" aria-hidden="true" />
          <span>{label}</span>
          {skipped && showSkippedHint && (
            <Badge variant="outline" className="h-4 rounded px-1 text-[10px] text-muted-foreground">
              已跳过
            </Badge>
          )}
        </div>
        {onSkip && !skipped && !selectedId && !loading && (
          <button
            type="button"
            onClick={onSkip}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            <SkipForwardIcon className="size-3" />
            跳过
          </button>
        )}
      </div>
      <div ref={containerRef} className="relative">
        {loading ? (
          <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/30 px-3">
            <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />
            <span className="text-xs text-muted-foreground">加载中...</span>
          </div>
        ) : skipped ? (
          <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/30 px-3 text-xs text-muted-foreground">
            —
          </div>
        ) : (
          <button
            type="button"
            onClick={() => options.length > 0 && setOpen(!open)}
            disabled={options.length === 0}
            className="flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-left text-sm transition-colors hover:bg-accent/50 disabled:opacity-50"
          >
            <span className={selectedOption ? "text-foreground" : "text-muted-foreground"}>
              {selectedOption
                ? (selectedOption.name ?? selectedOption.label)
                : placeholder}
            </span>
            <ChevronDownIcon className={`size-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        )}
        {open && options.length > 0 && (
          <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border bg-background shadow-lg">
            {options.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => {
                  onSelect(opt.id)
                  setOpen(false)
                }}
                className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                  opt.id === selectedId ? "bg-accent/50 font-medium" : ""
                }`}
              >
                <span className="truncate">{opt.name ?? opt.label}</span>
                <span className="ml-2 shrink-0 text-[10px] text-muted-foreground">
                  {opt.count > 0 ? `${opt.count}` : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function SubscribePage() {
  const funnel = useFunnelState()
  const [email, setEmail] = useState("")

  if (funnel.submitted) {
    const regionLabel = funnel.regions.find((r) => r.id === funnel.selectedRegion)?.label ?? funnel.selectedRegion
    return (
      <section className="mx-auto max-w-lg rounded-lg border bg-background px-6 py-10 text-center" aria-label="订阅成功">
        <CheckIcon className="mx-auto size-10 text-success" aria-hidden="true" />
        <h1 className="mt-4 text-xl font-semibold">订阅成功</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          你已订阅 <strong className="text-foreground">{regionLabel}</strong> 地区的新闻更新。
        </p>
        {funnel.sourcesSkipped ? null : funnel.selectedSource ? (
          <p className="mt-1 text-xs text-muted-foreground">
            信源: {funnel.sources.find((s) => s.id === funnel.selectedSource)?.name ?? funnel.selectedSource}
          </p>
        ) : null}
        {funnel.issuesSkipped ? null : funnel.selectedIssue ? (
          <p className="mt-1 text-xs text-muted-foreground">
            议题: {funnel.issues.find((i) => i.id === funnel.selectedIssue)?.label ?? funnel.selectedIssue}
          </p>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={funnel.reset}
        >
          创建新订阅
        </Button>
      </section>
    )
  }

  const canSubscribe = !funnel.regionsLoading && !!funnel.selectedRegion && !funnel.submitting

  return (
    <section className="mx-auto max-w-lg rounded-lg border bg-background" aria-label="订阅管理">
      <div className="border-b px-4 py-4">
        <Badge variant="outline" className="mb-2">
          订阅 Subscribe
        </Badge>
        <h1 className="text-lg font-semibold leading-tight">创建订阅</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          三步设置你的地区订阅。信源和议题可选，点击跳过即可。
        </p>
      </div>

      <div className="grid gap-5 px-4 py-5">
        {/* Step 1 */}
        <div className="grid gap-1.5">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <span className="flex size-5 items-center justify-center rounded-full bg-primary text-[10px] text-primary-foreground">1</span>
            <span>选择地区</span>
          </div>
          <FunnelDropdown
            label="地区"
            icon={Globe2Icon}
            options={funnel.regions}
            selectedId={funnel.selectedRegion}
            onSelect={funnel.setSelectedRegion}
            loading={funnel.regionsLoading}
            placeholder={funnel.regionsLoading ? "加载中..." : "请选择关注地区"}
          />
        </div>

        {/* Step 2 */}
        <div className="grid gap-1.5">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <span className="flex size-5 items-center justify-center rounded-full bg-muted-foreground/30 text-[10px] text-muted-foreground">2</span>
            <span>选择信源</span>
            <span className="text-[10px] font-normal text-muted-foreground">（可选）</span>
          </div>
          <FunnelDropdown
            label="信源"
            icon={RadioIcon}
            options={funnel.sources.map((s) => ({ id: s.id, label: s.name, count: s.count }))}
            selectedId={funnel.selectedSource}
            onSelect={(id) => {
              funnel.setSelectedSource(id)
              funnel.setSourcesSkipped(false)
            }}
            loading={funnel.sourcesLoading}
            skipped={funnel.sourcesSkipped}
            onSkip={() => {
              funnel.setSourcesSkipped(true)
              funnel.setSelectedSource(null)
            }}
            placeholder={
              !funnel.selectedRegion
                ? "请先选择地区"
                : funnel.sources.length === 0 && !funnel.sourcesLoading
                  ? "该地区暂无信源数据"
                  : "选择特定信源（可选）"
            }
            showSkippedHint
          />
        </div>

        {/* Step 3 */}
        <div className="grid gap-1.5">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <span className="flex size-5 items-center justify-center rounded-full bg-muted-foreground/30 text-[10px] text-muted-foreground">3</span>
            <span>选择议题</span>
            <span className="text-[10px] font-normal text-muted-foreground">（可选）</span>
          </div>
          <FunnelDropdown
            label="议题"
            icon={HashIcon}
            options={funnel.issues}
            selectedId={funnel.selectedIssue}
            onSelect={(id) => {
              funnel.setSelectedIssue(id)
              funnel.setIssuesSkipped(false)
            }}
            loading={funnel.issuesLoading}
            skipped={funnel.issuesSkipped}
            onSkip={() => {
              funnel.setIssuesSkipped(true)
              funnel.setSelectedIssue(null)
            }}
            placeholder={
              !funnel.selectedRegion
                ? "请先选择地区"
                : funnel.issues.length === 0 && !funnel.issuesLoading
                  ? "该地区暂无议题数据"
                  : "选择关注议题（可选）"
            }
            showSkippedHint
          />
        </div>

        {/* Email */}
        <div className="grid gap-1.5">
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <MailIcon className="size-4" aria-hidden="true" />
            <span>通知邮箱</span>
            <span className="text-[10px] text-muted-foreground">（可选）</span>
          </div>
          <Input
            type="email"
            placeholder="your@email.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-9 text-sm"
          />
        </div>

        {/* Subscribe button */}
        <div className="grid gap-2">
          {funnel.error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {funnel.error}
            </p>
          )}
          <Button
            disabled={!canSubscribe}
            onClick={() => funnel.handleSubscribe(email || undefined)}
            className="h-10 w-full"
          >
            {funnel.submitting ? (
              <>
                <Loader2Icon className="size-4 mr-2 animate-spin" />
                提交中...
              </>
            ) : (
              <>
                <SendIcon className="size-4 mr-2" />
                订阅
              </>
            )}
          </Button>
          <p className="text-center text-[10px] text-muted-foreground">
            订阅即表示同意接收所选题材的新闻更新通知
          </p>
        </div>
      </div>
    </section>
  )
}
