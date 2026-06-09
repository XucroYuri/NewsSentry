import { useEffect, useMemo, useState } from "react"
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
  RefreshCwIcon,
  SparklesIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { getPublicNewsItem, listPublicNews, PublicNewsApiError } from "@/lib/api"
import { type FeedFilters, groupItemsByDate, type PublicChannel } from "@/lib/feed-state"
import {
  buildDailyDigest,
  buildPublicDetailUrl,
  buildRelatedBuckets,
  buildSourceSummaries,
  formatFullTime,
  formatTime,
  sourceTypeLabel,
  summaryText,
  todayKey,
} from "@/lib/public-view"
import type { FeedState } from "@/hooks/use-public-feed"
import type { PublicAnalysisResponse, PublicNewsItem, PublicTargetInfo } from "@/types/public-news"
import { buildRouteHash, type PublicRoute } from "@/lib/routes"

const channels: Array<{
  id: PublicChannel
  label: string
  description: string
}> = [
  { id: "featured", label: "精选", description: "优先展示高价值和中国相关信号" },
  { id: "all", label: "全部", description: "按发布时间浏览公共新闻流" },
  { id: "targets", label: "目标", description: "按监控目标查看新闻" },
  { id: "sources", label: "来源", description: "按媒体与信源观察覆盖面" },
  { id: "analysis", label: "态势", description: "查看公开态势摘要" },
  { id: "daily", label: "日报", description: "读者化日内摘要入口" },
]

function normalizeError(error: unknown) {
  if (error instanceof PublicNewsApiError) return error.message
  if (error instanceof Error) return error.message
  return "公共新闻接口暂时不可用，请稍后重试。"
}

function channelHeading(channel: PublicChannel) {
  if (channel === "daily") return "今日日报"
  if (channel === "analysis") return "态势简报"
  if (channel === "targets") return "目标新闻"
  if (channel === "sources") return "来源观察"
  if (channel === "all") return "全部新闻"
  return "精选新闻"
}

function channelTitle(channel: PublicChannel) {
  return channels.find((item) => item.id === channel)?.label ?? "精选"
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

function NewsCard({ item }: { item: PublicNewsItem }) {
  const tags = item.tags.slice(0, 4)
  const reason = item.recommendationReason || "已进入公共新闻流，等待更多背景和关联信号增强。"
  const discussionLabel =
    (item.discussionCount ?? 0) > 0
      ? `${item.discussionCount} 条讨论`
      : item.relatedCount > 0
        ? `${item.relatedCount} 条关联信号`
        : "关联信号待形成"

  return (
    <article className="border-b bg-background px-4 py-4 transition-colors hover:bg-accent/35 sm:px-5">
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <Badge variant={item.valueLabel === "精选" ? "default" : "secondary"}>
            {item.valueLabel}
          </Badge>
          <span className="inline-flex items-center gap-1">
            <Clock3Icon className="size-3.5" aria-hidden="true" />
            {formatTime(item.publishedAt)}
          </span>
          <span className="inline-flex min-w-0 items-center gap-1">
            <Globe2Icon className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{item.source.name}</span>
          </span>
          <span>{sourceTypeLabel(item.source.type)}</span>
          <span>{item.targetLabel}</span>
        </div>

        <div className="grid gap-2">
          <h2 className="text-lg font-semibold leading-7 text-foreground sm:text-xl">
            {item.title}
          </h2>
          <p className="text-sm leading-6 text-muted-foreground">
            {item.summary || item.originalTitle || "这条新闻仍在生成读者摘要，已保留来源与原文入口。"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {tags.map((tag) => (
            <Badge key={tag} variant="outline" className="font-normal">
              {tag}
            </Badge>
          ))}
          <Badge variant="outline" className="font-normal">
            对华相关度：{item.chinaRelevanceLabel}
          </Badge>
          <span className="text-xs text-muted-foreground">{discussionLabel}</span>
        </div>

        <div className="rounded-md border bg-muted/35 px-3 py-2 text-sm leading-6 text-muted-foreground">
          <span className="font-medium text-foreground">推荐理由：</span>
          {reason}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={buildPublicDetailUrl(item)}>
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
    <div>
      <div className="border-b px-4 py-4 sm:px-5">
        <Badge variant="outline" className="w-fit">
          正在整理最新新闻
        </Badge>
        <p className="mt-2 text-sm text-muted-foreground">新闻流会在最新信号整理好后自动出现。</p>
      </div>
      <div className="divide-y">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="grid gap-3 px-4 py-5 sm:px-5">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-6 w-5/6" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyExplanation({ title, description }: { title: string; description: string }) {
  return (
    <div className="grid gap-3 px-5 py-8">
      <Badge variant="outline" className="w-fit">
        等待内容
      </Badge>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="grid gap-3 px-5 py-8">
      <Badge variant="destructive" className="w-fit">
        加载失败
      </Badge>
      <p className="max-w-xl text-sm leading-6 text-muted-foreground">{message}</p>
      <Button onClick={onRetry} className="w-fit" size="sm">
        重试
      </Button>
    </div>
  )
}

export function NewsFeedPage({
  filters,
  state,
  refreshing,
  loadingMore,
  onRefresh,
  onLoadMore,
  onApplyPending,
}: {
  filters: FeedFilters
  state: FeedState
  refreshing: boolean
  loadingMore: boolean
  onRefresh: () => void
  onLoadMore: () => void
  onApplyPending: () => void
}) {
  const grouped = useMemo(() => groupItemsByDate(state.items), [state.items])
  const activeChannel = channels.find((item) => item.id === filters.channel)
  const hasItems = state.items.length > 0
  const emptyDescription =
    filters.channel === "analysis"
      ? "当前窗口还没有足够样本形成态势。采集与增强继续运行，稍后会补充趋势、实体和追踪链。"
      : "当前筛选条件下暂时没有可展示新闻。可以切换频道、放宽筛选，或稍后等待新采集结果进入公共流。"

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="outline">{channelTitle(filters.channel)}</Badge>
              {filters.category ? <Badge variant="secondary">{filters.category}</Badge> : null}
              {filters.search ? <Badge variant="secondary">搜索：{filters.search}</Badge> : null}
            </div>
            <h1 className="text-2xl font-semibold leading-tight sm:text-3xl">
              {channelHeading(filters.channel)}
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {activeChannel?.description}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? (
              <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCwIcon className="size-4" aria-hidden="true" />
            )}
            更新
          </Button>
        </div>
      </div>

      <LiveUpdateBanner count={state.pendingNewItems.length} onApply={onApplyPending} />

      {state.status === "loading" ? <LoadingFeed /> : null}
      {state.status === "error" ? (
        <ErrorState message={state.error ?? "加载失败"} onRetry={onRefresh} />
      ) : null}
      {state.status === "empty" ? (
        <EmptyExplanation title="还没有可展示的新闻" description={emptyDescription} />
      ) : null}
      {hasItems ? (
        <div>
          {grouped.map((group) => (
            <section key={group.key} aria-label={group.label}>
              <div className="sticky top-[3.75rem] z-10 border-b bg-muted/80 px-4 py-2 text-sm font-medium backdrop-blur sm:px-5">
                {group.label}
              </div>
              <div className="divide-y">
                {group.items.map((item) => (
                  <NewsCard key={item.id} item={item} />
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

function RelatedSection({ title, items }: { title: string; items: PublicNewsItem[] }) {
  return (
    <section className="grid gap-2">
      <h3 className="text-base font-semibold">{title}</h3>
      {items.length > 0 ? (
        <div className="grid gap-2">
          {items.map((item) => (
            <a
              key={item.id}
              href={buildPublicDetailUrl(item)}
              className="rounded-md border bg-background p-3 text-sm hover:border-primary/40"
            >
              <span className="font-medium">{item.title}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {item.source.name} · {formatFullTime(item.publishedAt)}
              </span>
            </a>
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

  useEffect(() => {
    let cancelled = false
    async function loadDetail() {
      setStatus("loading")
      try {
        const detail = await getPublicNewsItem(route.eventId, { targetId: route.targetId })
        const relatedResult = await listPublicNews({
          targetId: route.targetId ?? detail.targetId,
          pageSize: 50,
        })
        if (!cancelled) {
          setItem(detail)
          setRelated(relatedResult.data?.items ?? [])
          setStatus("ready")
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

  if (status === "loading") return <LoadingFeed />
  if (status === "error" || !item) {
    return <ErrorState message={error || "新闻详情暂时不可用。"} onRetry={() => window.location.reload()} />
  }

  const buckets = buildRelatedBuckets(item, related)

  return (
    <article className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b px-4 py-4 sm:px-6">
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-3">
          <a href="#/feed">
            <ArrowLeftIcon className="size-4" aria-hidden="true" />
            返回新闻流
          </a>
        </Button>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant={item.valueLabel === "精选" ? "default" : "secondary"}>{item.valueLabel}</Badge>
          <span>{formatFullTime(item.publishedAt)}</span>
          <span>{item.source.name}</span>
          <span>{sourceTypeLabel(item.source.type)}</span>
          {item.source.credibilityLabel ? <span>{item.source.credibilityLabel}</span> : null}
        </div>
        <h1 className="mt-3 text-2xl font-semibold leading-tight sm:text-3xl">{item.title}</h1>
        {item.originalTitle ? (
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.originalTitle}</p>
        ) : null}
      </div>
      <div className="grid gap-5 px-4 py-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <section className="grid gap-5">
          <div>
            <h2 className="text-base font-semibold">新闻摘要</h2>
            <p className="mt-2 text-sm leading-7 text-muted-foreground">
              {item.summary || "这条新闻仍在生成读者摘要，已保留来源、原文和推荐理由。"}
            </p>
          </div>
          <div className="rounded-md border bg-muted/35 p-3 text-sm leading-6 text-muted-foreground">
            <span className="font-medium text-foreground">推荐理由：</span>
            {item.recommendationReason || "等待更多 AI 增强说明。"}
          </div>
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
        <aside className="grid h-fit gap-4">
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
              <Button asChild variant="outline" size="sm" className="mt-2 w-fit">
                <a href={`#/sources/${encodeURIComponent(item.source.id)}`}>查看来源</a>
              </Button>
            </CardContent>
          </Card>
        </aside>
      </div>
      <div className="grid gap-4 border-t px-4 py-5 sm:px-6 lg:grid-cols-3">
        <RelatedSection title="同来源信号" items={buckets.sameSource} />
        <RelatedSection title="同目标信号" items={buckets.sameTarget} />
        <RelatedSection title="同主题信号" items={buckets.sameTopic} />
      </div>
    </article>
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
    <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b px-4 py-4 sm:px-5">
        <Badge variant="outline" className="mb-2">
          来源
        </Badge>
        <h1 className="text-2xl font-semibold leading-tight sm:text-3xl">来源目录</h1>
        <p className="mt-2 text-sm text-muted-foreground">
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
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          {sources.map((source) => (
            <a
              key={source.id}
              href={`#/sources/${encodeURIComponent(source.id)}`}
              className="grid gap-3 rounded-lg border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-lg font-semibold">{source.name}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">{sourceTypeLabel(source.type)}</p>
                </div>
                <Badge variant={source.statusLabel === "近期活跃" ? "default" : "secondary"}>
                  {source.statusLabel}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">近期 {source.count} 条新闻</p>
              {source.latestTitle ? (
                <p className="line-clamp-2 text-sm">{source.latestTitle}</p>
              ) : null}
            </a>
          ))}
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

  return (
    <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b px-4 py-4 sm:px-5">
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-3">
          <a href="#/sources">
            <ArrowLeftIcon className="size-4" aria-hidden="true" />
            来源目录
          </a>
        </Button>
        <Badge variant="outline" className="mb-2">
          来源详情
        </Badge>
        <h1 className="text-2xl font-semibold leading-tight sm:text-3xl">{heading}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
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
        <NewsCard key={item.id} item={item} />
      ))}
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

  return (
    <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b px-4 py-4 sm:px-5">
        <Badge variant="outline" className="mb-2">
          日报
        </Badge>
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold leading-tight sm:text-3xl">今日日报</h1>
            <p className="mt-2 text-sm text-muted-foreground">{selectedDate}</p>
          </div>
          <Input
            type="date"
            value={selectedDate}
            onChange={(event) => {
              window.location.hash = buildRouteHash({
                name: "daily",
                date: event.currentTarget.value,
                search: new URLSearchParams(),
              })
            }}
            className="w-full md:w-44"
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
        <div className="grid gap-5 p-4 sm:p-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border bg-muted/35 p-3">
              <p className="text-sm text-muted-foreground">重点新闻</p>
              <p className="mt-1 text-xl font-semibold">{digest.total} 条</p>
            </div>
            <div className="rounded-md border bg-muted/35 p-3">
              <p className="text-sm text-muted-foreground">主要主题</p>
              <p className="mt-1 text-xl font-semibold">{digest.topicLabels.length}</p>
            </div>
            <div className="rounded-md border bg-muted/35 p-3">
              <p className="text-sm text-muted-foreground">覆盖来源</p>
              <p className="mt-1 text-xl font-semibold">{digest.sourceLabels.length}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {digest.topicLabels.map((topic) => (
              <Badge key={topic} variant="outline">
                {topic}
              </Badge>
            ))}
          </div>
          <section className="grid gap-3">
            <h2 className="text-lg font-semibold">重点新闻 {digest.total} 条</h2>
            <div className="divide-y rounded-lg border">
              {digest.topItems.map((item) => (
                <NewsCard key={item.id} item={item} />
              ))}
            </div>
          </section>
          <section className="grid gap-2">
            <h2 className="text-lg font-semibold">来源链接</h2>
            <p className="text-sm text-muted-foreground">{digest.sourceLabels.join("、")}</p>
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
      <div className="rounded-lg border bg-background p-4 shadow-sm sm:p-5">
        <div className="mb-2 flex flex-wrap gap-2">
          <Badge variant="outline">态势</Badge>
          {preferredSection === "entities" ? <Badge variant="secondary">实体优先</Badge> : null}
        </div>
        <h1 className="text-2xl font-semibold leading-tight sm:text-3xl">态势简报</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          趋势、实体、来源分布和追踪链按公开分析快照呈现。
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
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
          <div className="grid gap-4 md:grid-cols-2">
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
                <a
                  key={target.target_id}
                  href={`#/analysis?target_id=${encodeURIComponent(target.target_id)}`}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 hover:border-primary/40"
                >
                  <span className="min-w-0 truncate">{target.display_name}</span>
                  <span className="text-muted-foreground">{target.event_count}</span>
                </a>
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
