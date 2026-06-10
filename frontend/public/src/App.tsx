import { useCallback, useEffect, useMemo, useState } from "react"
import {
  BookOpenIcon,
  CalendarDaysIcon,
  FilterIcon,
  Globe2Icon,
  Loader2Icon,
  RadioTowerIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  TrendingUpIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Toaster } from "@/components/ui/sonner"
import { useHashRoute } from "@/hooks/use-hash-route"
import { usePublicAnalysis } from "@/hooks/use-public-analysis"
import { usePublicFeed } from "@/hooks/use-public-feed"
import { usePublicTargets } from "@/hooks/use-public-targets"
import { type FeedFilters, type PublicChannel } from "@/lib/feed-state"
import { formatFullTime, todayKey } from "@/lib/public-view"
import { routeToChannel, type PublicRoute } from "@/lib/routes"
import {
  AnalysisPage,
  DailyPage,
  EventDetailPage,
  NewsFeedPage,
  SourceDetailPage,
  SourceDirectoryPage,
} from "@/pages/public-pages"
import type { PublicAnalysisResponse, PublicNewsItem, PublicTargetInfo } from "@/types/public-news"

const PAGE_SIZE = 20

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

const categories = ["国际关系", "政治", "经济", "社会", "文化", "科技"]

function queryValue(search: URLSearchParams, key: string) {
  const value = search.get(key)?.trim()
  return value || undefined
}

function searchFromFilters(filters: FeedFilters) {
  const search = new URLSearchParams()
  if (filters.targetId) search.set("target_id", filters.targetId)
  if (filters.sourceId) search.set("source_id", filters.sourceId)
  if (filters.category) search.set("category", filters.category)
  if (filters.search) search.set("q", filters.search)
  if (filters.date) search.set("date", filters.date)
  return search
}

function filtersFromRoute(route: PublicRoute): FeedFilters {
  if (route.name !== "feed") {
    return {
      channel: routeToChannel(route),
      pageSize: PAGE_SIZE,
    }
  }
  return {
    channel: route.channel,
    targetId: queryValue(route.search, "target_id"),
    sourceId: queryValue(route.search, "source_id"),
    category: queryValue(route.search, "category"),
    search: queryValue(route.search, "q"),
    date: queryValue(route.search, "date"),
    pageSize: PAGE_SIZE,
  }
}

function feedRouteFromFilters(filters: FeedFilters): PublicRoute {
  return {
    name: "feed",
    channel: filters.channel,
    search: searchFromFilters(filters),
  }
}

function AppShell({
  children,
  onRefresh,
  refreshing,
}: {
  children: React.ReactNode
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <div className="min-h-screen bg-[hsl(42_33%_98%)] text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1600px] items-center justify-between gap-4 px-4 py-3 lg:px-6">
          <a href="#/feed" className="flex min-w-0 items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md border border-primary/25 bg-primary/5 text-primary">
              <BookOpenIcon className="size-5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-base font-semibold leading-5">News Sentry</p>
              <p className="truncate text-xs text-muted-foreground">公共新闻流 · 灰度入口</p>
            </div>
          </a>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? (
              <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCwIcon className="size-4" aria-hidden="true" />
            )}
            刷新
          </Button>
        </div>
      </header>
      {children}
      <Toaster position="top-center" richColors closeButton />
    </div>
  )
}

function ChannelNav({
  active,
  onChange,
}: {
  active: PublicChannel
  onChange: (channel: PublicChannel) => void
}) {
  return (
    <nav
      aria-label="公共频道"
      className="flex min-w-0 max-w-full gap-2 overflow-x-auto pb-1 lg:grid lg:grid-cols-2 lg:overflow-visible lg:pb-0"
    >
      {channels.map((channel) => (
        <Button
          key={channel.id}
          type="button"
          variant={active === channel.id ? "default" : "outline"}
          size="sm"
          aria-pressed={active === channel.id}
          onClick={() => onChange(channel.id)}
          className="min-w-0 shrink-0 lg:w-full lg:shrink"
        >
          {channel.label}
        </Button>
      ))}
    </nav>
  )
}

function FilterPanel({
  filters,
  targets,
  sources,
  onChange,
}: {
  filters: FeedFilters
  targets: PublicTargetInfo[]
  sources: Array<{ id: string; name: string; count: number }>
  onChange: (patch: Partial<FeedFilters>) => void
}) {
  const [search, setSearch] = useState(filters.search ?? "")

  useEffect(() => {
    setSearch(filters.search ?? "")
  }, [filters.search])

  return (
    <div className="grid min-w-0 gap-4">
      <form
        className="grid min-w-0 gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          onChange({ search })
        }}
      >
        <label className="text-xs font-medium text-muted-foreground" htmlFor="public-search">
          搜索新闻
        </label>
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_2.5rem] gap-2">
          <Input
            id="public-search"
            value={search}
            placeholder="搜索标题、摘要、来源"
            onChange={(event) => setSearch(event.currentTarget.value)}
            className="min-w-0"
          />
          <Button type="submit" size="icon" aria-label="搜索">
            <SearchIcon className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </form>

      <section className="grid gap-2" aria-label="分类筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">分类</p>
          {filters.category ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ category: undefined })}>
              清除
            </Button>
          ) : null}
        </div>
        <div className="flex min-w-0 gap-2 overflow-x-auto lg:grid lg:grid-cols-2">
          {categories.map((category) => (
            <Button
              key={category}
              type="button"
              variant={filters.category === category ? "default" : "outline"}
              size="sm"
              aria-pressed={filters.category === category}
              onClick={() =>
                onChange({ category: filters.category === category ? undefined : category })
              }
              className="min-w-0 shrink-0 justify-start lg:shrink"
            >
              {category}
            </Button>
          ))}
        </div>
      </section>

      <section className="grid gap-2" aria-label="目标筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">目标</p>
          {filters.targetId ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ targetId: undefined })}>
              全部
            </Button>
          ) : null}
        </div>
        <div className="grid gap-2">
          {targets.length > 0 ? (
            targets.slice(0, 8).map((target) => (
              <Button
                key={target.target_id}
                type="button"
                variant={filters.targetId === target.target_id ? "secondary" : "ghost"}
                aria-pressed={filters.targetId === target.target_id}
                onClick={() =>
                  onChange({
                    channel: "targets",
                    targetId:
                      filters.targetId === target.target_id ? undefined : target.target_id,
                  })
                }
                className="h-auto justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0 truncate">{target.display_name}</span>
                <span className="text-xs text-muted-foreground">{target.event_count}</span>
              </Button>
            ))
          ) : (
            <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              目标列表正在加载，新闻流仍可浏览。
            </p>
          )}
        </div>
      </section>

      <section className="grid gap-2" aria-label="来源筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">来源</p>
          {filters.sourceId ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ sourceId: undefined })}>
              全部
            </Button>
          ) : null}
        </div>
        <div className="grid gap-1">
          {sources.length > 0 ? (
            sources.slice(0, 8).map((source) => (
              <Button
                key={source.id}
                type="button"
                variant={filters.sourceId === source.id ? "secondary" : "ghost"}
                aria-pressed={filters.sourceId === source.id}
                onClick={() =>
                  onChange({
                    channel: "sources",
                    sourceId: filters.sourceId === source.id ? undefined : source.id,
                  })
                }
                className="h-auto justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0 truncate">{source.name}</span>
                <span className="text-xs text-muted-foreground">{source.count}</span>
              </Button>
            ))
          ) : (
            <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              加载新闻后会显示可筛选来源。
            </p>
          )}
        </div>
      </section>
    </div>
  )
}

function MobileFilterSheet({ children }: { children: React.ReactNode }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className="lg:hidden">
          <FilterIcon className="size-4" aria-hidden="true" />
          筛选
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>筛选新闻</SheetTitle>
        </SheetHeader>
        <div className="min-h-0 overflow-y-auto pr-4">{children}</div>
      </SheetContent>
    </Sheet>
  )
}

function RightRail({
  analysis,
  analysisError,
  targets,
  latestItem,
}: {
  analysis: PublicAnalysisResponse | null
  analysisError: string | null
  targets: PublicTargetInfo[]
  latestItem: PublicNewsItem | null
}) {
  const summary = analysis?.summary
  const statusItems = [
    {
      label: "事件样本",
      value: summary ? `${summary.total_events}` : "等待",
      helper: summary && summary.total_events > 0 ? "当前窗口" : "样本不足",
    },
    {
      label: "高价值事件",
      value: summary ? `${summary.high_value_events}` : "等待",
      helper: "需要持续复核",
    },
    {
      label: "新闻价值",
      value:
        summary?.avg_news_value_score !== undefined && summary.avg_news_value_score !== null
          ? Math.round(summary.avg_news_value_score).toString()
          : "待增强",
      helper: "均值",
    },
  ]
  return (
    <aside className="grid h-fit min-w-0 gap-4">
      <Card className="rounded-lg">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUpIcon className="size-4 text-primary" aria-hidden="true" />
            态势摘要
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="grid min-w-0 grid-cols-3 gap-2">
            {statusItems.map((item) => (
              <div key={item.label} className="min-w-0 rounded-md border bg-muted/35 p-2">
                <p className="truncate text-xs text-muted-foreground">{item.label}</p>
                <p className="mt-1 truncate text-lg font-semibold">{item.value}</p>
                <p className="truncate text-xs text-muted-foreground">{item.helper}</p>
              </div>
            ))}
          </div>
          {analysisError ? (
            <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              态势摘要暂时不可用，新闻流仍可正常浏览。
            </p>
          ) : null}
          {analysis && analysis.topic_trends.length === 0 ? (
            <p className="rounded-md border border-dashed p-3 text-sm leading-6 text-muted-foreground">
              当前窗口趋势样本不足，等待更多实体/主题增强数据后会形成趋势。
            </p>
          ) : null}
          {analysis?.source_distribution.slice(0, 4).map((source) => (
            <div key={source.source_id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-muted-foreground">{source.display_name}</span>
              <span className="font-medium">{source.count}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <RadioTowerIcon className="size-4 text-primary" aria-hidden="true" />
            监控目标
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {targets.slice(0, 5).map((target) => (
            <div key={target.target_id} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{target.display_name}</span>
              <span className="text-muted-foreground">{target.event_count}</span>
            </div>
          ))}
          {targets.length === 0 ? (
            <p className="text-muted-foreground">目标列表正在加载。</p>
          ) : null}
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarDaysIcon className="size-4 text-primary" aria-hidden="true" />
            更新节奏
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm text-muted-foreground">
          <p className="break-words">
            {latestItem ? `最新新闻：${formatFullTime(latestItem.publishedAt)}` : "等待新闻进入公共流。"}
          </p>
          <p>页面会低频轮询，有新内容时只提示，不打断当前阅读位置。</p>
        </CardContent>
      </Card>
    </aside>
  )
}

function MobileBottomNav({
  active,
  onChange,
}: {
  active: PublicChannel
  onChange: (channel: PublicChannel) => void
}) {
  const mobileItems: Array<{
    id: PublicChannel
    label: string
    icon: React.ComponentType<{ className?: string }>
  }> = [
    { id: "featured", label: "信号", icon: SparklesIcon },
    { id: "targets", label: "目标", icon: RadioTowerIcon },
    { id: "sources", label: "来源", icon: Globe2Icon },
    { id: "analysis", label: "态势", icon: TrendingUpIcon },
    { id: "daily", label: "日报", icon: CalendarDaysIcon },
  ]
  return (
    <nav
      aria-label="移动端公共频道"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t bg-background/95 px-2 pb-[calc(env(safe-area-inset-bottom)+0.25rem)] pt-1.5 shadow-[0_-4px_16px_rgba(15,23,42,0.08)] backdrop-blur lg:hidden"
    >
      {mobileItems.map((item) => {
        const Icon = item.icon
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={active === item.id}
            onClick={() => onChange(item.id)}
            className="flex min-w-0 flex-col items-center justify-center gap-1 rounded-md px-1 py-1.5 text-xs text-muted-foreground aria-pressed:text-primary"
          >
            <Icon className="size-4" aria-hidden="true" />
            <span className="truncate">{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

export default function App() {
  const { route, navigate } = useHashRoute()
  const activeChannel = routeToChannel(route)
  const [filters, setFilters] = useState<FeedFilters>(() => filtersFromRoute(route))

  useEffect(() => {
    if (route.name === "feed") {
      setFilters(filtersFromRoute(route))
    }
  }, [route])

  const feed = usePublicFeed(filters, { poll: route.name === "feed" })
  const targets = usePublicTargets()
  const sourceOptions = useMemo(() => {
    const sources = new Map<string, { id: string; name: string; count: number }>()
    for (const item of feed.feedState.items) {
      const existing = sources.get(item.source.id)
      if (existing) existing.count += 1
      else sources.set(item.source.id, { id: item.source.id, name: item.source.name, count: 1 })
    }
    return [...sources.values()].sort((a, b) => b.count - a.count)
  }, [feed.feedState.items])
  const selectedTargetId =
    filters.targetId || feed.feedState.items[0]?.targetId || targets[0]?.target_id || null
  const { analysis, analysisError } = usePublicAnalysis(selectedTargetId)

  const updateFilters = useCallback(
    (patch: Partial<FeedFilters>) => {
      const nextFilters = { ...filters, ...patch, pageSize: PAGE_SIZE }
      setFilters(nextFilters)
      if (route.name === "feed") {
        navigate(feedRouteFromFilters(nextFilters))
      }
    },
    [filters, navigate, route.name],
  )

  const changeChannel = useCallback(
    (channel: PublicChannel) => {
      if (channel === "sources") {
        navigate({ name: "sources", search: new URLSearchParams() })
        return
      }
      if (channel === "daily") {
        navigate({ name: "daily", date: todayKey(), search: new URLSearchParams() })
        return
      }
      if (channel === "analysis") {
        navigate({
          name: "analysis",
          targetId: selectedTargetId ?? undefined,
          section: undefined,
          search: new URLSearchParams(),
        })
        return
      }
      const nextFilters = { ...filters, channel, pageSize: PAGE_SIZE }
      setFilters(nextFilters)
      navigate(feedRouteFromFilters(nextFilters))
    },
    [filters, navigate, selectedTargetId],
  )

  const filterPanel = (
    <FilterPanel
      filters={filters}
      targets={targets}
      sources={sourceOptions}
      onChange={updateFilters}
    />
  )
  const latestItem = feed.feedState.items[0] ?? null

  let mainContent: React.ReactNode
  let showLeftRail = true
  let showRightRail = true

  if (route.name === "event") {
    showLeftRail = false
    showRightRail = false
    mainContent = <EventDetailPage route={route} />
  } else if (route.name === "sources") {
    showRightRail = false
    mainContent = <SourceDirectoryPage />
  } else if (route.name === "sourceDetail") {
    showRightRail = false
    mainContent = <SourceDetailPage sourceId={route.sourceId} />
  } else if (route.name === "daily") {
    showRightRail = false
    mainContent = <DailyPage date={route.date} />
  } else if (route.name === "analysis") {
    showRightRail = false
    mainContent = (
      <AnalysisPage
        analysis={analysis}
        analysisError={analysisError}
        targets={targets}
        preferredSection={route.section}
      />
    )
  } else {
    mainContent = (
      <NewsFeedPage
        filters={filters}
        state={feed.feedState}
        refreshing={feed.refreshing}
        loadingMore={feed.loadingMore}
        onRefresh={() => void feed.loadFeed("refresh")}
        onLoadMore={() => void feed.loadMore()}
        onApplyPending={feed.applyPending}
      />
    )
  }

  return (
    <AppShell onRefresh={() => void feed.loadFeed("refresh")} refreshing={feed.refreshing}>
      <main
        className={
          showLeftRail && showRightRail
            ? "mx-auto grid w-full max-w-[1600px] gap-4 px-4 pb-24 pt-4 lg:grid-cols-[260px_minmax(0,1fr)_320px] lg:px-6 lg:pb-8"
            : "mx-auto grid w-full max-w-[1280px] gap-4 px-4 pb-24 pt-4 lg:px-6 lg:pb-8"
        }
      >
        {showLeftRail ? (
          <aside className="hidden min-w-0 overflow-hidden lg:block">
            <div className="sticky top-[4.5rem] grid gap-4">
              <Card className="min-w-0 overflow-hidden rounded-lg">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">公共频道</CardTitle>
                </CardHeader>
                <CardContent className="grid min-w-0 gap-3">
                  <ChannelNav active={activeChannel} onChange={changeChannel} />
                </CardContent>
              </Card>
              {route.name === "feed" ? (
                <Card className="min-w-0 overflow-hidden rounded-lg">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">筛选</CardTitle>
                  </CardHeader>
                  <CardContent className="min-w-0">{filterPanel}</CardContent>
                </Card>
              ) : null}
            </div>
          </aside>
        ) : null}

        <section className="grid min-w-0 gap-3">
          <div className="flex min-w-0 items-center justify-between gap-3 lg:hidden">
            <div className="min-w-0 flex-1">
              <ChannelNav active={activeChannel} onChange={changeChannel} />
            </div>
            {route.name === "feed" ? <MobileFilterSheet>{filterPanel}</MobileFilterSheet> : null}
          </div>
          {mainContent}
        </section>

        {showRightRail ? (
          <div className="hidden min-w-0 lg:block">
            <div className="sticky top-[4.5rem]">
              <RightRail
                analysis={analysis}
                analysisError={analysisError}
                targets={targets}
                latestItem={latestItem}
              />
            </div>
          </div>
        ) : null}
      </main>
      <MobileBottomNav active={activeChannel} onChange={changeChannel} />
    </AppShell>
  )
}
