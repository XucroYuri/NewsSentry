import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ComponentType, ReactNode } from "react"
import {
  ArrowUpRightIcon,
  BotIcon,
  CalendarDaysIcon,
  ChevronRightIcon,
  FilterIcon,
  HistoryIcon,
  ListIcon,
  Loader2Icon,
  MailIcon,
  MenuIcon,
  MoonIcon,
  RefreshCwIcon,
  RadioIcon,
  SearchIcon,
  SparklesIcon,
  SunIcon,
  ZapIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { SeoHead } from "@/components/seo/seo-head"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useHashRoute } from "@/hooks/use-hash-route"
import { usePublicAnalysis } from "@/hooks/use-public-analysis"
import { usePublicFeed } from "@/hooks/use-public-feed"
import { usePublicTargets } from "@/hooks/use-public-targets"
import { getPublicBootstrap, listPublicFacets, readSSRBootstrap, readSSRFeed } from "@/lib/api"
import { getApiBase, setApiBase } from "@/lib/locals-settings"
import { type FeedFilters, makeFeedQuery, type PublicChannel } from "@/lib/feed-state"
import { targetShortLabel, todayKey } from "@/lib/public-view"
import { buildPublicAppPath, routeToChannel, type PublicRoute } from "@/lib/routes"
import { buildRouteSeoPayload } from "@/lib/seo/site-seo"
import {
  AnalysisPage,
  DailyPage,
  EventDetailPage,
  NewsFeedPage,
  SourceDetailPage,
  SourceDirectoryPage,
} from "@/pages/public-pages"
import type { PublicBootstrapResponse, PublicFacetsResponse, PublicTargetInfo } from "@/types/public-news"

const PAGE_SIZE = 20
const PUBLIC_APP_VERSION = "v2.0.0"

type NavId = "breaking" | "all" | "daily" | "agent" | "update"
type ThemePreference = "system" | "light" | "dark"

const navItems: Array<{
  id: NavId
  label: string
  sublabel?: string
  icon: ComponentType<{ className?: string }>
}> = [
  { id: "breaking", label: "新闻哨兵", sublabel: "Breaking News", icon: ZapIcon },
  { id: "all", label: "新闻纵览", sublabel: "All News", icon: ListIcon },
  { id: "daily", label: "新闻日报", sublabel: "Daily News", icon: CalendarDaysIcon },
  { id: "agent", label: "Agent", icon: BotIcon },
  { id: "update", label: "Update", icon: HistoryIcon },
]

function queryValue(search: URLSearchParams, key: string) {
  const value = search.get(key)?.trim()
  return value || undefined
}

const facetLabelAliases: Record<string, string> = {
  "LGBTQ+权益": "LGBTQ",
  "中东局势": "中东",
  "产业改革": "产业",
  "人道主义援助": "人道援助",
  "体育产业": "体育",
  "公共安全": "安全",
  "北美政治": "北美政局",
  "国际关系": "外交",
  "国际援助": "援助",
  "国际贸易": "外贸",
  "地方文化": "地方",
  "职业高尔夫": "高尔夫",
  "赛事管理": "赛事",
}

function displayFacetLabel(label: string) {
  const normalized = label.trim()
  return facetLabelAliases[normalized] ?? normalized
}

function searchFromFilters(filters: FeedFilters) {
  const search = new URLSearchParams()
  if (filters.targetId) search.set("target_id", filters.targetId)
  if (filters.sourceId) search.set("source_id", filters.sourceId)
  if (filters.category) search.set("category", filters.category)
  if (filters.issue) search.set("issue", filters.issue)
  if (filters.related) search.set("related", filters.related)
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
    issue: queryValue(route.search, "issue"),
    related: queryValue(route.search, "related"),
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

function routeForNav(id: NavId): PublicRoute {
  if (id === "all") {
    return { name: "feed", channel: "all", search: new URLSearchParams() }
  }
  if (id === "daily") {
    return { name: "daily", date: todayKey(), search: new URLSearchParams() }
  }
  if (id === "agent") {
    return { name: "agent", search: new URLSearchParams() }
  }
  if (id === "update") {
    return { name: "update", search: new URLSearchParams() }
  }
  return { name: "feed", channel: "featured", search: new URLSearchParams() }
}

function activeNavFromRoute(route: PublicRoute, filters: FeedFilters): NavId {
  if (route.name === "agent") return "agent"
  if (route.name === "update") return "update"
  if (route.name === "daily") return "daily"
  if (route.name === "sources" || route.name === "sourceDetail") return "all"
  if (route.name === "feed" && (filters.channel === "all" || filters.channel === "targets")) return "all"
  return "breaking"
}

function filtersEqual(left: FeedFilters, right: FeedFilters) {
  return (
    left.channel === right.channel &&
    left.targetId === right.targetId &&
    left.sourceId === right.sourceId &&
    left.category === right.category &&
    left.issue === right.issue &&
    left.related === right.related &&
    left.search === right.search &&
    left.date === right.date &&
    left.pageSize === right.pageSize
  )
}

function useThemePreference() {
  const [theme, setTheme] = useState<ThemePreference>(() => {
    try {
      const saved = window.localStorage.getItem("news-sentry-theme")
      if (saved === "dark" || saved === "light" || saved === "system") return saved
    } catch {
      // Ignore storage failures; system theme remains the default.
    }
    return "system"
  })

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove("dark", "light")
    if (theme !== "system") root.classList.add(theme)
    try {
      window.localStorage.setItem("news-sentry-theme", theme)
    } catch {
      // Theme preference is nice-to-have; rendering should not depend on storage.
    }
  }, [theme])

  return { theme, setTheme }
}

function ThemeToggle({
  theme,
  onChange,
}: {
  theme: ThemePreference
  onChange: (theme: ThemePreference) => void
}) {
  const nextTheme: ThemePreference =
    theme === "system" ? "light" : theme === "light" ? "dark" : "system"
  const labels: Record<ThemePreference, string> = {
    system: "跟随系统",
    light: "浅色",
    dark: "深色",
  }
  const Icon = theme === "dark" ? MoonIcon : theme === "light" ? SunIcon : SparklesIcon

  return (
    <button
      type="button"
      aria-label={`切换主题：当前${labels[theme]}，点击切换到${labels[nextTheme]}`}
      onClick={() => onChange(nextTheme)}
      className="flex size-6 items-center justify-center rounded-full text-muted-foreground transition hover:bg-primary/10 hover:text-primary"
    >
      <Icon className="size-3" aria-hidden="true" />
    </button>
  )
}

type BootstrapState =
  | { status: "loading"; data: null }
  | { status: "ready"; data: PublicBootstrapResponse }
  | { status: "error"; data: null }

function regionsToTargets(payload: PublicBootstrapResponse | null): PublicTargetInfo[] | null {
  if (!payload) return null
  return payload.regions.regions.map((region) => ({
    target_id: region.region_id,
    display_name: region.display_name,
    primary_language: region.primary_language,
    monitoring_type: region.region_type,
    monitoring_label: "地区",
    source_count: region.source_count,
    event_count: region.event_count,
    lifecycle: region.lifecycle,
    archived: region.archived,
  }))
}

function usePublicBootstrap(filters: FeedFilters): BootstrapState {
  const ssrData = readSSRBootstrap()

  // 仅在首页默认查询（featured，无筛选）时使用 SSR 数据
  const ssrApplicable =
    ssrData !== null &&
    filters.channel === "featured" &&
    !filters.targetId &&
    !filters.sourceId &&
    !filters.category &&
    !filters.issue &&
    !filters.related &&
    !filters.search &&
    !filters.date

  const [state, setState] = useState<BootstrapState>(() =>
    ssrApplicable ? { status: "ready", data: ssrData } : { status: "loading", data: null },
  )
  const didConsumeSSR = useRef(ssrApplicable)

  useEffect(() => {
    if (didConsumeSSR.current) {
      didConsumeSSR.current = false
      return
    }
    let cancelled = false
    const controller = new AbortController()
    setState({ status: "loading", data: null })
    async function loadBootstrap() {
      try {
        const result = await getPublicBootstrap(makeFeedQuery(filters), {
          signal: controller.signal,
        })
        if (!cancelled) setState({ status: "ready", data: result.data })
      } catch {
        if (!cancelled) setState({ status: "error", data: null })
      }
    }
    void loadBootstrap()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [filters])

  return state
}

function usePublicFacets(
  filters: FeedFilters,
  initialFacets: PublicFacetsResponse | null = null,
  waitForInitialData = false,
) {
  const [facets, setFacets] = useState<PublicFacetsResponse>({
    regions: [],
    issues: [],
    related: [],
  })
  // 记录“已直接使用静态初始数据且后续 filters 未改变”的版本号
  const consumedInitialForFilters = useRef<FeedFilters | null>(null)

  useEffect(() => {
    if (!initialFacets) return
    setFacets(initialFacets)
    // 标记：当前 filters 下静态数据已消费
    if (!waitForInitialData) {
      consumedInitialForFilters.current = { ...filters }
    }
  }, [initialFacets]) // 仅依赖 initialFacets（SSR 注入）变化，不随 filters 变化重置

  useEffect(() => {
    if (waitForInitialData) return
    const filtersWereConsumed =
      consumedInitialForFilters.current !== null &&
      filtersEqual(consumedInitialForFilters.current, filters)
    if (filtersWereConsumed) return
    // filters 变化后清除标记，避免后续误跳过
    if (consumedInitialForFilters.current !== null) {
      consumedInitialForFilters.current = null
    }

    let cancelled = false
    const controller = new AbortController()
    async function loadFacets() {
      try {
        const response = await listPublicFacets(
          {
            targetId: filters.targetId,
            issue: filters.issue,
            related: filters.related,
            date: filters.date,
            q: filters.search,
          },
          { signal: controller.signal },
        )
        if (!cancelled) setFacets(response)
      } catch {
        if (!cancelled) {
          setFacets({ regions: [], issues: [], related: [] })
        }
      }
    }
    void loadFacets()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [filters.date, filters.issue, filters.related, filters.search, filters.targetId, waitForInitialData])

  return facets
}

function NavButton({
  item,
  active,
  onSelect,
}: {
  item: (typeof navItems)[number]
  active: boolean
  onSelect: (id: NavId) => void
}) {
  const Icon = item.icon
  return (
    <button
      type="button"
      aria-label={item.sublabel ? `${item.label} ${item.sublabel}` : item.label}
      aria-pressed={active}
      onClick={() => onSelect(item.id)}
      className="group flex w-full min-w-0 max-w-full items-center gap-2 overflow-hidden rounded-lg px-2.5 py-2 text-left text-xs font-medium text-muted-foreground transition hover:bg-primary/10 hover:text-primary aria-pressed:border aria-pressed:border-primary/30 aria-pressed:bg-primary/15 aria-pressed:text-primary"
    >
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 overflow-hidden">
        <span className="block truncate">{item.label}</span>
        {item.sublabel ? (
          <span className="block truncate text-[10px] font-normal opacity-70">{item.sublabel}</span>
        ) : null}
      </span>
    </button>
  )
}

function UtilityMenu({
  theme,
  onThemeChange,
}: {
  theme: ThemePreference
  onThemeChange: (theme: ThemePreference) => void
}) {
  const utilityLinks = [
    { label: "Sources", href: "/sources", icon: RadioIcon },
    { label: "Subscribe", href: "/subscribe", icon: MailIcon },
  ]

  return (
    <nav
      aria-label="侧边栏辅助菜单"
      className="grid w-full min-w-0 max-w-full grid-cols-3 gap-0.5 self-start overflow-hidden rounded-full border border-border bg-background/70 p-0.5 dark:border-white/10 dark:bg-white/[0.03]"
    >
      {utilityLinks.map((link) => {
        const Icon = link.icon
        return (
          <a
            key={link.href}
            href={link.href}
            aria-label={link.label}
            className="flex size-6 items-center justify-center rounded-full text-muted-foreground transition hover:bg-primary/10 hover:text-primary"
            title={link.label}
          >
            <Icon className="size-3" aria-hidden="true" />
          </a>
        )
      })}
      <ThemeToggle theme={theme} onChange={onThemeChange} />
    </nav>
  )
}

function SidebarNav({
  active,
  theme,
  onThemeChange,
  onSelect,
}: {
  active: NavId
  theme: ThemePreference
  onThemeChange: (theme: ThemePreference) => void
  onSelect: (id: NavId) => void
}) {
  return (
    <aside className="sticky top-0 hidden h-screen w-40 min-w-0 overflow-hidden border-r border-border bg-card px-2 py-3 text-foreground dark:border-white/10 dark:bg-[#070b14] lg:grid lg:grid-rows-[auto_1fr_auto]">
      <a href="/public-app/" className="mb-3 flex h-10 min-w-0 max-w-full items-center overflow-hidden px-2">
        <span className="text-base font-black tracking-wide">
          News<span className="text-primary">Sentry</span>
        </span>
      </a>
      <nav aria-label="公共站侧边栏" className="grid min-w-0 content-start gap-1 overflow-hidden">
        {navItems.map((item) => (
          <NavButton key={item.id} item={item} active={active === item.id} onSelect={onSelect} />
        ))}
      </nav>
      <UtilityMenu theme={theme} onThemeChange={onThemeChange} />
    </aside>
  )
}

function MobileNavigation({
  active,
  onSelect,
}: {
  active: NavId
  onSelect: (id: NavId) => void
}) {
  return (
    <nav
      aria-label="移动端公共菜单"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t bg-background/95 px-2 pb-[calc(env(safe-area-inset-bottom)+0.2rem)] pt-1 shadow-[0_-2px_12px_rgba(15,23,42,0.1)] backdrop-blur lg:hidden"
    >
      {navItems.map((item) => {
        const Icon = item.icon
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={active === item.id}
            onClick={() => onSelect(item.id)}
            className="flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-md px-1 py-1 text-xs text-muted-foreground aria-pressed:text-primary"
          >
            <Icon className="size-4" aria-hidden="true" />
            <span className="truncate">{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

function MobileHeader({
  onRefresh,
  refreshing,
  theme,
  onThemeChange,
  onNavigate,
}: {
  onRefresh: () => void
  refreshing: boolean
  theme: ThemePreference
  onThemeChange: (theme: ThemePreference) => void
  onNavigate: (id: NavId) => void
}) {
  return (
    <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b bg-background/90 px-3 py-3 backdrop-blur lg:hidden">
      <a href="/public-app/" className="min-w-0">
        <p className="truncate text-sm font-black">News Sentry</p>
        <p className="truncate text-xs text-muted-foreground">新闻哨兵</p>
      </a>
      <div className="flex items-center gap-2">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="outline" size="icon" aria-label="打开菜单">
              <MenuIcon className="size-4" aria-hidden="true" />
            </Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>News Sentry</SheetTitle>
              <SheetDescription className="text-xs text-muted-foreground">
                选择公共站栏目或切换主题。
              </SheetDescription>
            </SheetHeader>
            <div className="grid gap-4 pr-4">
              <div className="grid gap-2">
                {navItems.map((item) => (
                  <NavButton key={item.id} item={item} active={false} onSelect={onNavigate} />
                ))}
              </div>
              <UtilityMenu theme={theme} onThemeChange={onThemeChange} />
            </div>
          </SheetContent>
        </Sheet>
        <Button variant="outline" size="icon" onClick={onRefresh} disabled={refreshing} aria-label="刷新">
          {refreshing ? (
            <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCwIcon className="size-4" aria-hidden="true" />
          )}
        </Button>
      </div>
    </header>
  )
}

function AppShell({
  children,
  onRefresh,
  refreshing,
  activeNav,
  onNavigate,
}: {
  children: ReactNode
  onRefresh: () => void
  refreshing: boolean
  activeNav: NavId
  onNavigate: (id: NavId) => void
}) {
  const { theme, setTheme } = useThemePreference()
  return (
    <div className="min-h-screen bg-background text-foreground lg:grid lg:grid-cols-[160px_minmax(0,1fr)]">
      <SidebarNav active={activeNav} theme={theme} onThemeChange={setTheme} onSelect={onNavigate} />
      <div className="min-w-0">
        <MobileHeader
          onRefresh={onRefresh}
          refreshing={refreshing}
          theme={theme}
          onThemeChange={setTheme}
          onNavigate={onNavigate}
        />
        {children}
      </div>
      <MobileNavigation active={activeNav} onSelect={onNavigate} />
    </div>
  )
}

function FilterPanel({
  filters,
  targets,
  facets,
  sources,
  onChange,
}: {
  filters: FeedFilters
  targets: PublicTargetInfo[]
  facets: PublicFacetsResponse
  sources: Array<{ id: string; name: string; count: number }>
  onChange: (patch: Partial<FeedFilters>) => void
}) {
  const [search, setSearch] = useState(filters.search ?? "")

  useEffect(() => {
    setSearch(filters.search ?? "")
  }, [filters.search])

  return (
    <div className="grid w-full min-w-0 max-w-full gap-4 overflow-hidden">
      <form
        className="grid w-full min-w-0 max-w-full gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          onChange({ search })
        }}
      >
        <label className="text-xs font-medium text-muted-foreground" htmlFor="public-search">
          搜索新闻
        </label>
        <div className="grid w-full min-w-0 max-w-full grid-cols-[minmax(0,1fr)_2.5rem] gap-2">
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

      <section className="grid w-full min-w-0 gap-2" aria-label="议题筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">议题</p>
          {filters.issue ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ issue: undefined })}>
              清除
            </Button>
          ) : null}
        </div>
        <div className="flex w-full min-w-0 gap-2 overflow-x-auto lg:grid lg:grid-cols-2">
          {facets.issues.map((issue) => (
            <Button
              key={issue.id}
              type="button"
              variant={filters.issue === issue.label ? "default" : "outline"}
              size="sm"
              aria-pressed={filters.issue === issue.label}
              onClick={() =>
                onChange({ issue: filters.issue === issue.label ? undefined : issue.label })
              }
              className="min-w-0 shrink-0 justify-start lg:w-full lg:shrink"
            >
              <span className="truncate">{issue.label}</span>
              <span className="ml-auto text-[10px] opacity-70">{issue.count}</span>
            </Button>
          ))}
        </div>
      </section>

      <section className="grid w-full min-w-0 gap-2" aria-label="相关筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">相关</p>
          {filters.related ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ related: undefined })}>
              清除
            </Button>
          ) : null}
        </div>
        <div className="flex w-full min-w-0 gap-2 overflow-x-auto lg:grid lg:grid-cols-2">
          {facets.related.map((related) => (
            <Button
              key={related.id}
              type="button"
              variant={filters.related === related.label ? "default" : "outline"}
              size="sm"
              aria-pressed={filters.related === related.label}
              onClick={() =>
                onChange({
                  related: filters.related === related.label ? undefined : related.label,
                })
              }
              className="min-w-0 shrink-0 justify-start lg:w-full lg:shrink"
            >
              <span className="truncate">{related.label}</span>
              <span className="ml-auto text-[10px] opacity-70">{related.count}</span>
            </Button>
          ))}
        </div>
      </section>

      <section className="grid w-full min-w-0 gap-2" aria-label="地区筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">地区</p>
          {filters.targetId ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ targetId: undefined })}>
              全部
            </Button>
          ) : null}
        </div>
        <div className="grid w-full min-w-0 gap-2">
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
                className="h-auto w-full min-w-0 justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0 flex-1 truncate">{targetShortLabel(target.display_name)}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{target.event_count}</span>
              </Button>
            ))
          ) : (
            <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              地区列表正在加载，新闻流仍可浏览。
            </p>
          )}
        </div>
      </section>

      <section className="grid w-full min-w-0 gap-2" aria-label="来源筛选">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">来源</p>
          {filters.sourceId ? (
            <Button variant="ghost" size="sm" onClick={() => onChange({ sourceId: undefined })}>
              全部
            </Button>
          ) : null}
        </div>
        <div className="grid w-full min-w-0 gap-1">
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
                className="h-auto w-full min-w-0 justify-between gap-3 px-3 py-2 text-left"
              >
                <span className="min-w-0 flex-1 truncate">{source.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{source.count}</span>
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

function FilterSheet({ children }: { children: ReactNode }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 shrink-0 rounded-md px-2.5">
          <FilterIcon className="size-3.5" aria-hidden="true" />
          筛选
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>筛选新闻</SheetTitle>
          <SheetDescription className="text-xs text-muted-foreground">
            按关键词、地区、议题、相关和来源收窄新闻流。
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 overflow-y-auto pr-4">{children}</div>
      </SheetContent>
    </Sheet>
  )
}

function FacetFilterRow({
  label,
  allLabel,
  items,
  activeValue,
  onSelect,
}: {
  label: string
  allLabel?: string
  items: Array<{ id: string; label: string; count?: number }>
  activeValue?: string
  onSelect: (value?: string) => void
}) {
  if (!allLabel && items.length === 0) return null

  return (
    <div className="grid min-w-0 gap-1 md:grid-cols-[4.25rem_minmax(0,1fr)] md:items-start">
      <span className="pt-1.5 text-[11px] font-semibold leading-none text-muted-foreground">
        {label}
      </span>
      <div className="flex min-w-0 flex-wrap gap-1.5 overflow-visible" aria-label={`${label}筛选`}>
        {allLabel ? (
          <Button
            type="button"
            variant={activeValue ? "outline" : "default"}
            size="sm"
            aria-pressed={!activeValue}
            className="h-7 shrink-0 rounded-md px-2 text-xs"
            onClick={() => onSelect(undefined)}
          >
            {allLabel}
          </Button>
        ) : null}
        {items.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant={activeValue === item.id ? "default" : "outline"}
            size="sm"
            aria-pressed={activeValue === item.id}
            title={item.label}
            className="h-7 max-w-[9rem] rounded-md px-2 text-xs"
            onClick={() => onSelect(item.id)}
          >
            <span className="truncate">{displayFacetLabel(item.label)}</span>
            {typeof item.count === "number" ? (
              <span aria-hidden="true" className="ml-1 text-[10px] opacity-70">
                {item.count}
              </span>
            ) : null}
          </Button>
        ))}
      </div>
    </div>
  )
}

function CategorySidebar({
  facets,
  filters,
  onSelectIssue,
  onSelectRelated,
}: {
  facets: PublicFacetsResponse
  filters: FeedFilters
  onSelectIssue: (issue?: string) => void
  onSelectRelated: (related?: string) => void
}) {
  const [collapsed, setCollapsed] = useState(true)

  const issueList = useMemo(
    () => facets.issues.sort((a, b) => b.count - a.count).slice(0, 12),
    [facets.issues],
  )
  const relatedList = useMemo(
    () => facets.related.sort((a, b) => b.count - a.count).slice(0, 12),
    [facets.related],
  )

  if (issueList.length === 0 && relatedList.length === 0) return null

  return (
    <section
      className="hidden rounded-lg border bg-card/95 p-3 dark:bg-card/80 lg:block"
      aria-label="分类导航"
    >
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center justify-between gap-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
      >
        <span>分类浏览</span>
        <ChevronRightIcon
          className={`size-3.5 transition-transform ${collapsed ? "" : "rotate-90"}`}
          aria-hidden="true"
        />
      </button>
      {collapsed ? null : (
        <div className="mt-2 grid gap-3">
          {issueList.length > 0 ? (
            <div className="grid gap-1.5">
              <h3 className="text-[11px] font-medium text-muted-foreground">议题</h3>
              <div className="flex flex-wrap gap-1">
                {issueList.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() =>
                      onSelectIssue(filters.issue === item.label ? undefined : item.label)
                    }
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors hover:border-primary/40 hover:bg-accent ${
                      filters.issue === item.label
                        ? "border-primary bg-primary/10 text-primary"
                        : "text-muted-foreground"
                    }`}
                  >
                    {displayFacetLabel(item.label)}
                    <span className="text-[9px] opacity-60">{item.count}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {relatedList.length > 0 ? (
            <div className="grid gap-1.5">
              <h3 className="text-[11px] font-medium text-muted-foreground">相关</h3>
              <div className="flex flex-wrap gap-1">
                {relatedList.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() =>
                      onSelectRelated(
                        filters.related === item.label ? undefined : item.label,
                      )
                    }
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors hover:border-primary/40 hover:bg-accent ${
                      filters.related === item.label
                        ? "border-primary bg-primary/10 text-primary"
                        : "text-muted-foreground"
                    }`}
                  >
                    {displayFacetLabel(item.label)}
                    <span className="text-[9px] opacity-60">{item.count}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </section>
  )
}

function ReaderControls({
  filters,
  targets,
  facets,
  selectedTargetLabel,
  filterPanel,
  onChange,
}: {
  filters: FeedFilters
  targets: PublicTargetInfo[]
  facets: PublicFacetsResponse
  selectedTargetLabel?: string
  filterPanel: ReactNode
  onChange: (patch: Partial<FeedFilters>) => void
}) {
  const [search, setSearch] = useState(filters.search ?? "")
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsVisible, setSuggestionsVisible] = useState(false)
  const [suggestionIndex, setSuggestionIndex] = useState(-1)
  const suggestionTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchContainerRef = useRef<HTMLDivElement>(null)
  const regionItems = useMemo(
    () =>
      targets
        .filter((target) => target.source_count > 0)
        .map((target) => ({
          id: target.target_id,
          label: targetShortLabel(target.display_name),
          count: target.event_count > 0 ? target.event_count : undefined,
        })),
    [targets],
  )
  const issueItems = useMemo(
    () => facets.issues.map((item) => ({ id: item.label, label: item.label, count: item.count })),
    [facets.issues],
  )
  const relatedItems = useMemo(
    () => facets.related.map((item) => ({ id: item.label, label: item.label, count: item.count })),
    [facets.related],
  )

  // 搜索建议：在输入时调用 facets API，提取匹配的 issue/related 标签
  useEffect(() => {
    const q = search.trim()
    if (!q || q.length < 1) {
      setSuggestions([])
      setSuggestionsVisible(false)
      setSuggestionIndex(-1)
      return
    }
    // 如果输入匹配当前 facets 中的标签，直接本地过滤
    const localMatches = [
      ...facets.issues.map((item) => item.label),
      ...facets.related.map((item) => item.label),
    ].filter((label) => label.toLowerCase().includes(q.toLowerCase()))
    // 去重
    const localUnique = [...new Set(localMatches)].slice(0, 5)
    if (localUnique.length >= 3) {
      setSuggestions(localUnique)
      setSuggestionsVisible(true)
      setSuggestionIndex(-1)
      return
    }
    // 去抖动后调用 facets API
    if (suggestionTimer.current) clearTimeout(suggestionTimer.current)
    suggestionTimer.current = setTimeout(async () => {
      try {
        setSuggestionsLoading(true)
        const result = await listPublicFacets({ q }, {})
        const apiLabels = [
          ...result.issues.map((item) => item.label),
          ...result.related.map((item) => item.label),
        ]
        const apiUnique = [...new Set(apiLabels)].slice(0, 8)
        if (apiUnique.length > 0) {
          setSuggestions(apiUnique)
          setSuggestionsVisible(true)
        }
      } catch {
        // 搜索建议静默失败
      } finally {
        setSuggestionsLoading(false)
      }
    }, 250)
    return () => {
      if (suggestionTimer.current) clearTimeout(suggestionTimer.current)
    }
  }, [search, facets.issues, facets.related])

  // 关闭建议（点击外部）
  useEffect(() => {
    if (!suggestionsVisible) return
    const handleClick = (event: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setSuggestionsVisible(false)
        setSuggestionIndex(-1)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [suggestionsVisible])
  const heading = selectedTargetLabel
    ? targetShortLabel(selectedTargetLabel)
    : filters.channel === "all" || filters.channel === "targets"
      ? "新闻纵览"
      : "新闻哨兵"
  const description = selectedTargetLabel
    ? `正在浏览 ${targetShortLabel(selectedTargetLabel)} 的精选新闻流。`
    : filters.channel === "all" || filters.channel === "targets"
      ? "按地区、议题与相关标签筛选，直接进入同一条时间线阅读。"
      : "AI 辅助从公共新闻流里挑选时效性高、影响更明确的重大新闻。"

  useEffect(() => {
    setSearch(filters.search ?? "")
  }, [filters.search])

  return (
    <section className="grid gap-2 rounded-lg border bg-card/95 p-3 dark:bg-card/80">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight">{heading}</h1>
          <p className="hidden text-xs text-muted-foreground sm:block">{description}</p>
        </div>
        <div className="flex items-center gap-1.5 xl:w-[500px]">
          <div ref={searchContainerRef} className="relative min-w-0 flex-1">
            <form
              className="grid grid-cols-[minmax(0,1fr)_2rem] gap-1.5"
              onSubmit={(event) => {
                event.preventDefault()
                setSuggestionsVisible(false)
                onChange({ search })
              }}
            >
              <Input
                value={search}
                aria-label="快速搜索"
                placeholder="搜索标题/摘要/来源..."
                onChange={(event) => setSearch(event.currentTarget.value)}
                onFocus={() => {
                  if (search.trim() && suggestions.length > 0) setSuggestionsVisible(true)
                }}
                onKeyDown={(event) => {
                  if (!suggestionsVisible || suggestions.length === 0) return
                  if (event.key === "ArrowDown") {
                    event.preventDefault()
                    setSuggestionIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0))
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault()
                    setSuggestionIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1))
                  } else if (event.key === "Enter" && suggestionIndex >= 0) {
                    event.preventDefault()
                    setSearch(suggestions[suggestionIndex])
                    setSuggestionsVisible(false)
                    setSuggestionIndex(-1)
                    onChange({ search: suggestions[suggestionIndex] })
                  } else if (event.key === "Escape") {
                    setSuggestionsVisible(false)
                    setSuggestionIndex(-1)
                  }
                }}
                className="h-8 min-w-0 rounded-md"
              />
              <Button type="submit" size="icon" aria-label="搜索" className="size-8 rounded-md">
                <SearchIcon className="size-3.5" aria-hidden="true" />
              </Button>
            </form>
            {suggestionsVisible && suggestions.length > 0 ? (
              <ul
                role="listbox"
                aria-label="搜索建议"
                className="absolute left-0 right-8 top-full z-30 mt-1 max-h-56 overflow-y-auto rounded-md border bg-card shadow-lg"
              >
                {suggestionsLoading ? (
                  <li className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                    <Loader2Icon className="size-3 animate-spin" aria-hidden="true" />
                    获取建议中...
                  </li>
                ) : null}
                {suggestions.map((label, index) => (
                  <li key={label}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={suggestionIndex === index}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent aria-selected:bg-accent ${
                        suggestionIndex === index ? "bg-accent" : ""
                      }`}
                      onMouseDown={(event) => {
                        event.preventDefault() // 阻止 blur 抢先关闭建议
                        setSearch(label)
                        setSuggestionsVisible(false)
                        setSuggestionIndex(-1)
                        onChange({ search: label })
                      }}
                      onMouseEnter={() => setSuggestionIndex(index)}
                    >
                      <SearchIcon className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span>{label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <FilterSheet>{filterPanel}</FilterSheet>
        </div>
      </div>

      <div className="grid gap-1.5" role="region" aria-label="地区议题相关筛选">
        <FacetFilterRow
          label="地区"
          allLabel="全部"
          items={regionItems}
          activeValue={filters.targetId}
          onSelect={(value) =>
            onChange({
              channel: value ? "targets" : filters.channel === "featured" ? "featured" : "all",
              targetId: value,
            })
          }
        />
        <FacetFilterRow
          label="议题"
          items={issueItems}
          activeValue={filters.issue}
          onSelect={(value) => onChange({ issue: value })}
        />
        <FacetFilterRow
          label="相关"
          items={relatedItems}
          activeValue={filters.related}
          onSelect={(value) => onChange({ related: value })}
        />
      </div>
    </section>
  )
}

function InfoPanel({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section
      aria-label={`${title} 信息页`}
      className="overflow-hidden rounded-lg border bg-card/95 py-2 dark:bg-card/80"
    >
      <div className="border-b px-3 py-2">
        <h1 className="text-base font-semibold leading-tight">{title}</h1>
      </div>
      <div className="grid gap-2 p-3 text-sm leading-5 text-muted-foreground">{children}</div>
    </section>
  )
}

function AgentPage() {
  return (
    <InfoPanel title="Agent">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <a className="rounded-md border bg-background/60 px-3 py-2 hover:border-primary/50" href="/llms.txt">
          <strong className="block text-sm text-foreground">llms.txt</strong>
          <span className="text-xs">AI 阅读器站点说明</span>
        </a>
        <a className="rounded-md border bg-background/60 px-3 py-2 hover:border-primary/50" href="/api/v1/public/news">
          <strong className="block text-sm text-foreground">Public API</strong>
          <span className="text-xs">公共新闻流</span>
        </a>
        <a className="rounded-md border bg-background/60 px-3 py-2 hover:border-primary/50" href="/subscribe">
          <strong className="block text-sm text-foreground">Subscribe</strong>
          <span className="text-xs">每日/每周摘要</span>
        </a>
      </div>
    </InfoPanel>
  )
}

function SubscribePage() {
  const links = [
    {
      title: "每日信号",
      description: "每日高价值新闻摘要",
      href: "/public-app/",
    },
    {
      title: "新闻日报",
      description: "按日期聚合的简报",
      href: "/public-app/daily",
    },
    {
      title: "地区更新",
      description: "围绕重点地区的变化提醒",
      href: "/public-app/",
    },
  ]

  return (
    <InfoPanel title="订阅 Subscribe">
      <div className="flex flex-col gap-2 border-b pb-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>接收每日信号、新闻日报与地区更新。</span>
        <a className="font-medium text-primary hover:underline" href="/public-app/">
          进入新闻哨兵
        </a>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {links.map((link) => (
          <a
            key={link.title}
            className="rounded-md border bg-background/60 px-3 py-2 hover:border-primary/50"
            href={link.href}
          >
            <strong className="block text-sm text-foreground">{link.title}</strong>
            <span className="text-xs">{link.description}</span>
          </a>
        ))}
      </div>
    </InfoPanel>
  )
}

function UpdatePage({ updatedAt }: { updatedAt?: string | null }) {
  const [apiBase, setApiBaseState] = useState<string>(() => getApiBase() ?? "")

  const handleSave = useCallback(() => {
    const trimmed = apiBase.trim()
    setApiBase(trimmed || null)
  }, [apiBase])

  const handleReset = useCallback(() => {
    setApiBase(null)
    setApiBaseState("")
  }, [])

  return (
    <InfoPanel title="Update">
      <div className="grid gap-3">
        <div className="grid gap-2 rounded-md border bg-background/60 px-3 py-2 text-xs sm:grid-cols-[auto_1fr] sm:items-center">
          <span className="font-medium text-foreground">最近新闻刷新</span>
          <span>{updatedAt ? new Date(updatedAt).toLocaleString("zh-CN") : "等待新闻流"}</span>
          <span className="font-medium text-foreground">当前版本</span>
          <span>{PUBLIC_APP_VERSION}</span>
        </div>

        <div className="grid gap-2 rounded-md border bg-background/60 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-foreground">API 数据源</span>
            <span className="text-[10px] text-muted-foreground">
              {getApiBase() ? "Cloudflare Worker" : "同源（本地）"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Input
              value={apiBase}
              placeholder="留空 = 同源；或输入 https://news-sentry-api.xuyu.workers.dev"
              onChange={(e) => setApiBaseState(e.currentTarget.value)}
              className="h-7 min-w-0 flex-1 rounded-md text-xs"
            />
            <Button size="sm" className="h-7 shrink-0 rounded-md px-3 text-xs" onClick={handleSave}>
              保存
            </Button>
            <Button variant="outline" size="sm" className="h-7 shrink-0 rounded-md px-2 text-xs" onClick={handleReset}>
              重置
            </Button>
          </div>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            修改后刷新页面生效。同源模式下请求发到当前域名；Cloudflare Worker 模式请求发到指定 Worker URL。
          </p>
        </div>
      </div>
    </InfoPanel>
  )
}

export default function App() {
  const { route, navigate } = useHashRoute()
  const [filters, setFilters] = useState<FeedFilters>(() => filtersFromRoute(route))

  useEffect(() => {
    if (route.name === "feed") {
      const nextFilters = filtersFromRoute(route)
      setFilters((current) => (filtersEqual(current, nextFilters) ? current : nextFilters))
    }
  }, [route])

  const bootstrap = usePublicBootstrap(filters)
  const bootstrapTargets = useMemo(() => regionsToTargets(bootstrap.data), [bootstrap.data])
  const ssrFeed = useMemo(() => readSSRFeed(), [])
  const waitForBootstrap = bootstrap.status === "loading" && !ssrFeed
  const feed = usePublicFeed(filters, {
    poll: route.name === "feed",
    initialFeed: ssrFeed ?? bootstrap.data?.news ?? null,
    waitForInitialData: waitForBootstrap,
  })
  const targets = usePublicTargets(bootstrapTargets, waitForBootstrap)
  const facets = usePublicFacets(
    filters,
    bootstrap.data?.facets ?? null,
    waitForBootstrap,
  )
  const sourceOptions = useMemo(() => {
    const sources = new Map<string, { id: string; name: string; count: number }>()
    for (const item of feed.feedState.items) {
      const existing = sources.get(item.source.id)
      if (existing) existing.count += 1
      else sources.set(item.source.id, { id: item.source.id, name: item.source.name, count: 1 })
    }
    return [...sources.values()].sort((a, b) => b.count - a.count)
  }, [feed.feedState.items])
  const feedTargetId = filters.targetId || feed.feedState.items[0]?.targetId || null
  const analysisTargetId =
    route.name === "analysis"
      ? route.targetId || feedTargetId || targets[0]?.target_id || null
      : null
  const { analysis, analysisError } = usePublicAnalysis(analysisTargetId)
  const selectedTargetId = analysisTargetId ?? filters.targetId ?? feedTargetId ?? null
  const selectedTargetLabel =
    targets.find((target) => target.target_id === selectedTargetId)?.display_name ??
    feed.feedState.items.find((item) => item.targetId === selectedTargetId)?.targetLabel ??
    null
  const siteOrigin = window.location.origin || "https://news-sentry.com"
  const activeNav = activeNavFromRoute(route, filters)

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

  const navigatePrimary = useCallback(
    (id: NavId) => {
      const nextRoute = routeForNav(id)
      if (nextRoute.name === "feed") {
        const nextFilters = filtersFromRoute(nextRoute)
        setFilters(nextFilters)
      }
      navigate(nextRoute)
    },
    [navigate],
  )

  const filterPanel = (
    <FilterPanel
      filters={filters}
      targets={targets}
      facets={facets}
      sources={sourceOptions}
      onChange={updateFilters}
    />
  )
  const appSeoPayload = useMemo(() => {
    if (route.name === "event") return null
    return buildRouteSeoPayload({
      origin: siteOrigin,
      route,
      selectedTargetLabel,
      analysis,
    })
  }, [analysis, route, selectedTargetLabel, siteOrigin])

  let mainContent: ReactNode

  if (route.name === "event") {
    mainContent = <EventDetailPage route={route} />
  } else if (route.name === "sources") {
    mainContent = <SourceDirectoryPage />
  } else if (route.name === "sourceDetail") {
    mainContent = <SourceDetailPage sourceId={route.sourceId} />
  } else if (route.name === "daily") {
    mainContent = <DailyPage date={route.date} />
  } else if (route.name === "agent") {
    mainContent = <AgentPage />
  } else if (route.name === "update") {
    mainContent = <UpdatePage updatedAt={feed.feedState.items[0]?.publishedAt} />
  } else if (route.name === "subscribe") {
    mainContent = <SubscribePage />
  } else if (route.name === "analysis") {
    mainContent = (
      <AnalysisPage
        analysis={analysis}
        analysisError={analysisError}
        targets={targets}
        preferredSection={route.section}
      />
    )
  } else {
    const selectedFeedTargetLabel = filters.targetId
      ? targets.find((target) => target.target_id === filters.targetId)?.display_name ??
        feed.feedState.items.find((item) => item.targetId === filters.targetId)?.targetLabel
      : undefined
    mainContent = (
      <>
        <ReaderControls
          filters={filters}
          targets={targets}
          facets={facets}
          selectedTargetLabel={selectedFeedTargetLabel}
          filterPanel={filterPanel}
          onChange={updateFilters}
        />
        <NewsFeedPage
          filters={filters}
          state={feed.feedState}
          loadingMore={feed.loadingMore}
          onRefresh={() => void feed.loadFeed("refresh")}
          onLoadMore={() => void feed.loadMore()}
          onApplyPending={feed.applyPending}
        />
      </>
    )
  }

  return (
    <AppShell
      onRefresh={() => void feed.loadFeed("refresh")}
      refreshing={feed.refreshing}
      activeNav={activeNav}
      onNavigate={navigatePrimary}
    >
      <SeoHead payload={appSeoPayload} locale={route.locale} />
      <main className="grid w-full min-w-0 gap-3 px-2.5 pb-20 pt-2.5 sm:px-3 lg:px-4 lg:py-4 2xl:px-5">
        <section className="grid min-w-0 gap-3">
          {route.name === "feed" && (
            <CategorySidebar
              facets={facets}
              filters={filters}
              onSelectIssue={(issue) => updateFilters({ issue })}
              onSelectRelated={(related) => updateFilters({ related })}
            />
          )}
          {mainContent}
        </section>
      </main>
    </AppShell>
  )
}
