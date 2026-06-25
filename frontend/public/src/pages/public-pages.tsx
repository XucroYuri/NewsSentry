import { useEffect, useMemo, useRef, useState } from "react"
import type { KeyboardEvent, MouseEvent } from "react"
import {
  ArrowLeftIcon,
  ArrowUpRightIcon,
  BellIcon,
  CalendarDaysIcon,
  ChevronRightIcon,
  CopyIcon,
  Globe2Icon,
  Loader2Icon,
  MailIcon,
  NewspaperIcon,
  RadioIcon,
  RssIcon,
  StarIcon,
  TrendingUpIcon,
  UsersIcon,
  XIcon,
  ZapIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SeoHead } from "@/components/seo/seo-head"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { getPublicNewsItem, listPublicNews, PublicNewsApiError } from "@/lib/api"
import { type FeedFilters, groupItemsByDate, type PublicChannel } from "@/lib/feed-state"
import { getReadIds, markAsRead, markManyAsRead } from "@/lib/read-state"
import {
  buildDailyDigest,
  type DailyDigestTopicGroup,
  buildRelatedBuckets,
  buildSourceSummaries,
  formatFullTime,
  formatTime,
  sourceTypeLabel,
  summaryText,
  targetShortLabel,
  todayKey,
} from "@/lib/public-view"
import { buildEventSeoPayload } from "@/lib/seo/site-seo"
import type { FeedState } from "@/hooks/use-public-feed"
import type { PublicAnalysisResponse, PublicNewsItem, PublicNewsSourceType, PublicTargetInfo } from "@/types/public-news"
import { buildPublicAppPath, parseLocationRoute, type PublicRoute } from "@/lib/routes"

const channels: Array<{
  id: PublicChannel
  label: string
  description: string
}> = [
  { id: "featured", label: "精选", description: "跨目标展示最高价值新闻，先读判断，再看来源。" },
  { id: "all", label: "全部", description: "按发布时间浏览公共新闻流" },
  { id: "targets", label: "地区", description: "按地区浏览精选新闻流" },
  { id: "sources", label: "来源", description: "按媒体与信源观察覆盖面" },
  { id: "analysis", label: "态势", description: "查看公开态势摘要" },
  { id: "daily", label: "日报", description: "读者化日内摘要入口" },
]

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
    .map((label) => label.trim())
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
                      <span className="mt-4 size-2 rounded-full bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.18)]" />
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

// ─── SubscribePage ────────────────────────────────────────────────

interface RegionSnapshot {
  target_id: string
  display_name: string
  event_count: number
  source_count: number
  preview: PublicNewsItem[]
  facets: { issues: Array<{ id: string; label: string; count: number }>; related: Array<{ id: string; label: string; count: number }> }
  loading: boolean
  error: boolean
}

function RegionSubscribeCard({
  region,
}: {
  region: RegionSnapshot
  onExpand: (targetId: string) => void
}) {
  const label = targetShortLabel(region.display_name)
  return (
    <div className="grid gap-3 rounded-lg border bg-card/80 p-3">
      {/* 头部：地区名 + 统计 */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Globe2Icon className="size-4 shrink-0 text-primary" aria-hidden="true" />
          <h3 className="text-sm font-semibold truncate">{label}</h3>
          <Badge variant="outline" className="h-5 rounded px-1.5 text-[10px]">
            {region.event_count} 条
          </Badge>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <RadioIcon className="size-3" aria-hidden="true" />
          <span>{region.source_count}</span>
        </div>
      </div>

      {/* 议题标签 */}
      {region.facets.issues.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {region.facets.issues.slice(0, 5).map((issue) => (
            <Badge key={issue.id} variant="secondary" className="h-5 rounded px-1.5 text-[10px] font-normal">
              {issue.label}
              <span className="ml-0.5 opacity-60">{issue.count}</span>
            </Badge>
          ))}
        </div>
      ) : region.loading ? (
        <Skeleton className="h-5 w-32" />
      ) : null}

      {/* 最近新闻预览 */}
      {region.loading ? (
        <div className="grid gap-2">
          {[1, 2].map((i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : region.error ? (
        <p className="text-xs text-muted-foreground">暂时无法加载该地区预览</p>
      ) : region.preview.length > 0 ? (
        <div className="grid gap-1.5">
          {region.preview.slice(0, 3).map((item) => (
            <a
              key={item.id}
              href={buildPublicAppPath(
                parseLocationRoute({
                  pathname: `/public-app/events/${item.id}`,
                  search: `?target_id=${region.target_id}`,
                  hash: "",
                }),
              )}
              onClick={(event) =>
                handleRouteAnchorClick(
                  event,
                  parseLocationRoute({
                    pathname: `/public-app/events/${item.id}`,
                    search: `?target_id=${region.target_id}`,
                    hash: "",
                  }),
                )
              }
              className="flex items-center gap-2 rounded-md px-1.5 py-1 text-xs leading-5 transition-colors hover:bg-accent/50"
            >
              <ZapIcon className="size-3 shrink-0 text-primary/60" aria-hidden="true" />
              <span className="line-clamp-1">{primaryNewsTitle(item)}</span>
              <span className="shrink-0 text-[10px] text-muted-foreground">{formatTime(item.publishedAt)}</span>
            </a>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">该地区暂无最近新闻</p>
      )}

      {/* 操作区 */}
      <div className="flex items-center gap-2 border-t pt-2">
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-7 rounded-md px-2 text-xs flex-1"
        >
          <a href={`/public-app/?channel=targets&target_id=${region.target_id}`}>浏览</a>
        </Button>
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-7 rounded-md px-2 text-xs"
        >
          <a
            href={`/public-app/daily?date=${todayKey()}&target_id=${region.target_id}`}
          >
            <CalendarDaysIcon className="size-3 mr-1" aria-hidden="true" />
            日报
          </a>
        </Button>
      </div>
    </div>
  )
}

function SubscribeSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="grid gap-3 rounded-lg border bg-card/80 p-3">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ))}
    </div>
  )
}

export function SubscribePage() {
  const [regions, setRegions] = useState<RegionSnapshot[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")

  // 第一步：拉取所有地区
  useEffect(() => {
    let cancelled = false
    async function loadRegions() {
      setStatus("loading")
      try {
        const { listTargets } = await import("@/lib/api")
        const result = await listTargets()
        if (!cancelled) {
          const active = result.targets
            .filter((t) => t.event_count > 0)
            .sort((a, b) => b.event_count - a.event_count)
            .map((t) => ({
              target_id: t.target_id,
              display_name: t.display_name,
              event_count: t.event_count,
              source_count: t.source_count,
              preview: [] as PublicNewsItem[],
              facets: { issues: [], related: [] },
              loading: true,
              error: false,
            }))
          setRegions(active)
          setStatus("ready")
        }
      } catch {
        if (!cancelled) setStatus("error")
      }
    }
    void loadRegions()
    return () => {
      cancelled = true
    }
  }, [])

  // 第二步：为有事件的地区拉取预览
  useEffect(() => {
    if (regions.length === 0) return
    let cancelled = false

    async function loadRegionPreview(targetId: string) {
      try {
        const { listPublicNews, listPublicFacets } = await import("@/lib/api")
        const [newsResult, facetsResult] = await Promise.all([
          listPublicNews({ targetId, pageSize: 3 }),
          listPublicFacets({ targetId }),
        ])
        if (!cancelled) {
          setRegions((prev) =>
            prev.map((r) =>
              r.target_id === targetId
                ? {
                    ...r,
                    preview: newsResult.data?.items ?? [],
                    facets: facetsResult,
                    loading: false,
                    error: false,
                  }
                : r,
            ),
          )
        }
      } catch {
        if (!cancelled) {
          setRegions((prev) =>
            prev.map((r) =>
              r.target_id === targetId ? { ...r, loading: false, error: true } : r,
            ),
          )
        }
      }
    }

    for (const region of regions) {
      void loadRegionPreview(region.target_id)
    }
    return () => {
      cancelled = true
    }
  }, [regions.length === 0 ? "initial" : regions.map((r) => r.target_id).join(",")])

  const totalEvents = useMemo(
    () => regions.reduce((sum, r) => sum + r.event_count, 0),
    [regions],
  )
  const totalSources = useMemo(
    () => regions.reduce((sum, r) => sum + r.source_count, 0),
    [regions],
  )

  return (
    <section className="overflow-hidden rounded-lg border bg-background" aria-label="订阅管理">
      {/* 页面头部 */}
      <div className="border-b px-3 py-3">
        <Badge variant="outline" className="mb-2">
          订阅 Subscribe
        </Badge>
        <h1 className="text-xl font-semibold leading-tight">订阅中心</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          按地区订阅新闻哨兵更新，通过邮件或 RSS 接收每日/每周信号。选择你关注的地区开始。
        </p>

        {/* 统计卡片 */}
        {status === "ready" ? (
          <div className="mt-3 grid grid-cols-3 gap-2">
            <div className="flex items-center gap-2 rounded-md border bg-card/60 px-3 py-2">
              <Globe2Icon className="size-4 text-primary" aria-hidden="true" />
              <div>
                <p className="text-lg font-bold leading-none">{regions.length}</p>
                <p className="text-[10px] text-muted-foreground">活跃地区</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-md border bg-card/60 px-3 py-2">
              <NewspaperIcon className="size-4 text-primary" aria-hidden="true" />
              <div>
                <p className="text-lg font-bold leading-none">{totalEvents}</p>
                <p className="text-[10px] text-muted-foreground">新闻总量</p>
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-md border bg-card/60 px-3 py-2">
              <RadioIcon className="size-4 text-primary" aria-hidden="true" />
              <div>
                <p className="text-lg font-bold leading-none">{totalSources}</p>
                <p className="text-[10px] text-muted-foreground">活跃信源</p>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* 订阅方式介绍 */}
      <div className="border-b px-3 py-3">
        <h2 className="text-sm font-semibold">可用订阅方式</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <a
            href={`/api/v1/events/feed?target_id=${regions[0]?.target_id ?? "italy"}`}
            className="flex items-start gap-2 rounded-md border bg-card/60 px-3 py-2 transition-colors hover:border-primary/50"
          >
            <RssIcon className="size-4 shrink-0 mt-0.5 text-primary" aria-hidden="true" />
            <div>
              <strong className="block text-xs text-foreground">RSS 订阅</strong>
              <span className="text-[10px] text-muted-foreground">支持所有 RSS 阅读器</span>
            </div>
          </a>
          <a
            href="/subscribe"
            className="flex items-start gap-2 rounded-md border bg-card/60 px-3 py-2 transition-colors hover:border-primary/50"
          >
            <MailIcon className="size-4 shrink-0 mt-0.5 text-primary" aria-hidden="true" />
            <div>
              <strong className="block text-xs text-foreground">邮件摘要</strong>
              <span className="text-[10px] text-muted-foreground">每日信号 + 周三周报</span>
            </div>
          </a>
          <a
            href="/public-app/daily"
            className="flex items-start gap-2 rounded-md border bg-card/60 px-3 py-2 transition-colors hover:border-primary/50"
          >
            <BellIcon className="size-4 shrink-0 mt-0.5 text-primary" aria-hidden="true" />
            <div>
              <strong className="block text-xs text-foreground">新闻日报预览</strong>
              <span className="text-[10px] text-muted-foreground">按日期组包的内容简报</span>
            </div>
          </a>
        </div>
      </div>

      {/* 地区订阅卡片 */}
      <div className="px-3 py-3">
        <h2 className="text-sm font-semibold mb-2">按地区订阅</h2>
        {status === "loading" ? (
          <SubscribeSkeleton />
        ) : status === "error" ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-6 text-center">
            <p className="text-sm text-destructive">无法加载地区列表，请刷新重试</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => window.location.reload()}
            >
              刷新
            </Button>
          </div>
        ) : regions.length === 0 ? (
          <div className="rounded-md border border-dashed px-3 py-6 text-center">
            <Globe2Icon className="mx-auto size-6 text-muted-foreground" aria-hidden="true" />
            <p className="mt-2 text-sm text-muted-foreground">暂无活跃地区数据</p>
            <p className="text-xs text-muted-foreground">新闻采集正在进行中，请稍后回来</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {regions.map((region) => (
              <RegionSubscribeCard
                key={region.target_id}
                region={region}
                onExpand={() => {}}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
