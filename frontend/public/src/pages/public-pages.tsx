import { useEffect, useMemo, useState } from "react"
import type { MouseEvent } from "react"
import {
  ArrowLeftIcon,
  ArrowUpRightIcon,
  BellIcon,
  ChevronRightIcon,
  Clock3Icon,
  CopyIcon,
  Globe2Icon,
  Loader2Icon,
  NewspaperIcon,
  SparklesIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SeoHead } from "@/components/seo/seo-head"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { getPublicNewsItem, listPublicNews, PublicNewsApiError } from "@/lib/api"
import { type FeedFilters, groupItemsByDate, type PublicChannel } from "@/lib/feed-state"
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
import type { PublicAnalysisResponse, PublicNewsItem, PublicTargetInfo } from "@/types/public-news"
import { buildPublicAppPath, parseLocationRoute, type PublicRoute } from "@/lib/routes"

const channels: Array<{
  id: PublicChannel
  label: string
  description: string
}> = [
  { id: "featured", label: "精选", description: "跨目标展示最高价值新闻，先读判断，再看来源。" },
  { id: "all", label: "全部", description: "按发布时间浏览公共新闻流" },
  { id: "targets", label: "目标", description: "按 target 浏览精选新闻流" },
  { id: "sources", label: "来源", description: "按媒体与信源观察覆盖面" },
  { id: "analysis", label: "态势", description: "查看公开态势摘要" },
  { id: "daily", label: "日报", description: "读者化日内摘要入口" },
]

function normalizeError(error: unknown) {
  if (error instanceof PublicNewsApiError) return error.message
  if (error instanceof Error) return error.message
  return "公共新闻接口暂时不可用，请稍后重试。"
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

function NewsCard({ item, returnTo }: { item: PublicNewsItem; returnTo?: PublicRoute | null }) {
  const reason = item.recommendationReason?.trim()
  const detailRoute = buildDetailRoute(item, returnTo)
  const targetLabel = targetShortLabel(item.targetLabel)

  return (
    <article className="rounded-lg border bg-card/95 px-3 py-3 transition-colors hover:border-primary/50 hover:bg-accent/20 dark:bg-card/80">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start">
        <div className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Clock3Icon className="size-3.5" aria-hidden="true" />
            {formatTime(item.publishedAt)}
          </span>
          <span className="inline-flex min-w-0 items-center gap-1">
            <Globe2Icon className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{item.source.name}</span>
          </span>
          <Badge variant="outline" className="font-normal" title={item.targetLabel}>{targetLabel}</Badge>
          <Badge variant={item.valueLabel === "精选" ? "default" : "secondary"} className="rounded-full">
            {item.valueScore !== undefined && item.valueScore !== null
              ? `分值 ${Math.round(item.valueScore)}`
              : item.valueLabel}
          </Badge>
        </div>

        <div className="grid gap-1.5">
          <h2 className="text-base font-semibold leading-6 text-foreground sm:text-lg">
            {item.title}
          </h2>
          <p className="line-clamp-2 text-sm leading-5 text-muted-foreground">
            {item.summary || "中文摘要正在补齐，完成后会进入公共阅读流。"}
          </p>
        </div>

        {reason ? (
          <div className="line-clamp-2 rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1.5 text-xs leading-5 text-muted-foreground">
            <span className="font-medium text-foreground">推荐理由：</span>
            {reason}
          </div>
        ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
          <Button asChild variant="outline" size="sm">
            <a
              href={buildPublicAppPath(detailRoute)}
              onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
            >
              详情
              <ChevronRightIcon className="size-4" aria-hidden="true" />
            </a>
          </Button>
          {item.originalUrl ? (
            <Button asChild variant="ghost" size="sm">
              <a href={item.originalUrl} target="_blank" rel="noreferrer">
                原文
                <ArrowUpRightIcon className="size-4" aria-hidden="true" />
              </a>
            </Button>
          ) : null}
        </div>
      </div>
    </article>
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
  const grouped = useMemo(() => groupItemsByDate(state.items), [state.items])
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
  const emptyDescription =
    filters.channel === "analysis"
      ? "当前窗口还没有足够样本形成态势。采集与增强继续运行，稍后会补充趋势、实体和追踪链。"
      : "已采集新闻正在补齐中文标题与中文摘要。完成翻译后会自动进入公共阅读流。"

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border bg-card/95 dark:bg-card/80">
      <LiveUpdateBanner count={state.pendingNewItems.length} onApply={onApplyPending} />

      {state.status === "loading" ? <LoadingFeed /> : null}
      {state.status === "error" ? (
        <ErrorState message={state.error ?? "加载失败"} onRetry={onRefresh} />
      ) : null}
      {state.status === "empty" ? (
        <EmptyExplanation title="翻译队列处理中" description={emptyDescription} />
      ) : null}
      {hasItems ? (
        <div>
          <section className="border-b bg-muted/20 px-3 py-3" aria-label="当前热点">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold">当前热点</h2>
              </div>
              <span className="text-xs text-muted-foreground">TOP {topItems.length}</span>
            </div>
            <div className="grid gap-1.5">
              {topItems.map((item, index) => {
                const detailRoute = buildDetailRoute(item, feedRoute)
                return (
                  <a
                    key={item.id}
                    href={buildPublicAppPath(detailRoute)}
                    onClick={(event) => handleRouteAnchorClick(event, detailRoute)}
                    className="grid gap-1.5 rounded-md border bg-background/80 p-2 text-sm hover:border-primary/50 md:grid-cols-[2rem_minmax(0,1fr)_auto] md:items-center"
                  >
                    <span className="text-base font-semibold text-primary">{index + 1}</span>
                    <span className="line-clamp-2 font-semibold">{item.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {item.source.name} · {formatTime(item.publishedAt)}
                    </span>
                    {item.recommendationReason || item.summary || item.originalTitle ? (
                      <span className="hidden line-clamp-1 text-xs text-muted-foreground sm:block md:col-start-2 md:col-end-4">
                        {item.recommendationReason || item.summary || item.originalTitle}
                      </span>
                    ) : null}
                  </a>
                )
              })}
            </div>
          </section>
          <div className="border-b px-3 py-2 text-sm font-semibold">新闻时间线</div>
          {grouped.map((group) => (
            <section key={group.key} aria-label={group.label} className="grid gap-2 px-3 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <span>{group.label}</span>
                <span className="h-px flex-1 bg-border" />
              </div>
              <div className="grid gap-2">
                {group.items.map((item) => (
                  <div key={item.id} className="grid gap-2 md:grid-cols-[3.5rem_0.75rem_minmax(0,1fr)]">
                    <time className="pt-3 text-xs font-semibold text-muted-foreground">
                      {formatTime(item.publishedAt)}
                    </time>
                    <div className="hidden md:grid md:justify-center">
                      <span className="mt-4 size-2 rounded-full bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.18)]" />
                    </div>
                    <NewsCard item={item} returnTo={feedRoute} />
                  </div>
                ))}
              </div>
            </section>
          ))}
          <div className="flex items-center justify-center border-t px-4 py-4">
            <Button
              variant="outline"
              onClick={onLoadMore}
              disabled={loadingMore || !state.nextCursor}
            >
              {loadingMore ? (
                <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <NewspaperIcon className="size-4" aria-hidden="true" />
              )}
              {state.nextCursor ? "加载更多" : "没有更多了"}
            </Button>
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
              <span className="font-medium">{item.title}</span>
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
        }
        try {
          const relatedResult = await listPublicNews({
            targetId: route.targetId ?? detail.targetId,
            pageSize: 12,
          })
          if (!cancelled) {
            setRelated(relatedResult.data?.items ?? [])
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
          <h1 className="mt-2 text-xl font-semibold leading-tight sm:text-2xl">{item.title}</h1>
          {item.originalTitle ? (
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.originalTitle}</p>
          ) : null}
        </div>
        <div className="grid gap-4 px-3 py-4 sm:px-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <section className="grid gap-4">
            <div>
              <h2 className="text-base font-semibold">新闻摘要</h2>
              <p className="mt-2 text-sm leading-7 text-muted-foreground">
                {item.summary || "这条新闻仍在生成读者摘要，已保留来源与原文入口。"}
              </p>
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

  return (
    <section className="overflow-hidden rounded-lg border bg-background">
      <div className="border-b px-3 py-3">
        <Badge variant="outline" className="mb-2">
          来源
        </Badge>
        <h1 className="text-xl font-semibold leading-tight">来源目录</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          按公开新闻聚合媒体和信源，帮助读者理解新闻来自哪里。
        </p>
      </div>
      {status === "loading" ? <LoadingFeed /> : null}
      {status === "error" ? (
        <ErrorState message="来源目录暂时不可用。" onRetry={() => window.location.reload()} />
      ) : null}
      {status === "ready" && sources.length === 0 ? (
        <EmptyExplanation title="暂无来源样本" description="公共新闻仍在采集/增强，来源目录会随新闻流自动形成。" />
      ) : null}
      {sources.length > 0 ? (
        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {sources.map((source) => {
            const sourceRoute: Extract<PublicRoute, { name: "sourceDetail" }> = {
              name: "sourceDetail",
              sourceId: source.id,
              search: new URLSearchParams(),
            }
            return (
              <a
                key={source.id}
                href={buildPublicAppPath(sourceRoute)}
                onClick={(event) => handleRouteAnchorClick(event, sourceRoute)}
                className="grid gap-2 rounded-md border bg-card p-3 transition-colors hover:border-primary/40"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold">{source.name}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {sourceTypeLabel(source.type)}
                    </p>
                  </div>
                  <Badge variant={source.statusLabel === "近期活跃" ? "default" : "secondary"}>
                    {source.statusLabel}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">近期 {source.count} 条新闻</p>
                {source.latestTitle ? <p className="line-clamp-2 text-sm">{source.latestTitle}</p> : null}
              </a>
            )
          })}
        </div>
      ) : null}
    </section>
  )
}

export function SourceDetailPage({ sourceId }: { sourceId: string }) {
  const [items, setItems] = useState<PublicNewsItem[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")

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
            来源目录
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
        <NewsCard key={item.id} item={item} returnTo={sourceRoute} />
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
            <span className="font-medium text-primary">分值 {Math.round(item.valueScore)}</span>
          ) : null}
        </div>
        <h2 className="line-clamp-2 text-sm font-semibold leading-5 sm:text-base">{item.title}</h2>
        <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
          {item.recommendationReason || item.summary || "中文摘要正在补齐。"}
        </p>
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
              <span className="line-clamp-2 text-sm font-medium leading-5">{item.title}</span>
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
      {status === "ready" && digest.total === 0 ? (
        <EmptyExplanation
          title="今日样本仍在采集/增强"
          description="日报会在公开新闻进入后自动形成重点、主题、来源和风险摘要。"
        />
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
