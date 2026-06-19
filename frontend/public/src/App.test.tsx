import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { afterEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import type { PublicNewsFeedResponse, PublicNewsItem } from "@/types/public-news"

const LEAD_TITLE = "意大利总理与欧盟领导人讨论对华贸易关系"

function makeItem(id: string, overrides: Partial<PublicNewsItem> = {}): PublicNewsItem {
  return {
    id,
    targetId: "italy",
    targetLabel: "意大利新闻监控",
    source: {
      id: "ansa",
      name: "ANSA.it",
      type: "rss",
      credibilityLabel: "主流媒体",
    },
    publishedAt: "2026-06-09T08:00:00Z",
    title: LEAD_TITLE,
    originalTitle: "Italy and EU leaders discuss trade",
    summary: "会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。",
    recommendationReason: "该新闻同时涉及欧盟政策、意大利产业与中国相关贸易议题。",
    originalUrl: "https://example.com/news",
    detailUrl: "/public-app/events/" + id + "?target_id=italy",
    tags: ["国际关系", "贸易"],
    entities: [{ name: "欧盟", type: "organization" }],
    relatedCount: 2,
    discussionCount: 1,
    valueLabel: "精选",
    valueScore: 92,
    chinaRelevanceLabel: "中",
    ...overrides,
  }
}

function feed(items: PublicNewsItem[], latestCursor = "cursor-initial"): PublicNewsFeedResponse {
  return {
    items,
    latestCursor,
    nextCursor: "cursor-older",
    pollAfterMs: 30_000,
    hasNewer: false,
    total: items.length,
  }
}

function jsonResponse(payload: unknown, init: ResponseInit = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json", ETag: '"etag"', "X-Poll-After-Ms": "30000" },
      ...init,
    }),
  )
}

function installFetchMock() {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith("/api/v1/targets")) {
      return jsonResponse({
        targets: [
          {
            target_id: "italy",
            display_name: "意大利新闻监控",
            primary_language: "it",
            monitoring_type: "country",
            monitoring_label: "国别监控目标",
            source_count: 163,
            event_count: 52,
            lifecycle: {},
            archived: false,
          },
          {
            target_id: "china-watch-en",
            display_name: "涉中新闻监控",
            primary_language: "en",
            monitoring_type: "topic",
            monitoring_label: "专题监控目标",
            source_count: 42,
            event_count: 18,
            lifecycle: {},
            archived: false,
          },
          {
            target_id: "empty-target",
            display_name: "空目标新闻监控",
            primary_language: "en",
            monitoring_type: "country",
            monitoring_label: "国别监控目标",
            source_count: 0,
            event_count: 0,
            lifecycle: {},
            archived: false,
          },
        ],
      })
    }
    if (url.startsWith("/api/v1/public/targets/italy/analysis")) {
      return jsonResponse({
        target_id: "italy",
        target_name: "意大利新闻监控",
        days: 14,
        summary: {
          total_events: 52,
          high_value_events: 12,
          avg_news_value_score: 81,
          avg_china_relevance: 66,
        },
        classification_distribution: [{ name: "国际关系", count: 20 }],
        source_distribution: [{ source_id: "ansa", display_name: "ANSA.it", count: 7 }],
        top_entities: [{ name: "欧盟", entity_type: "organization", mention_count: 4 }],
        topic_trends: [],
        sentiment_trend: [],
        active_chains: [],
        generated_at: "2026-06-09T08:00:00Z",
      })
    }
    if (url.includes("since_cursor=cursor-initial")) {
      return jsonResponse(feed([makeItem("event-new", { title: "欧盟宣布新的贸易磋商议程" })], "cursor-new"))
    }
    if (url.startsWith("/api/v1/public/news/event-1")) {
      return jsonResponse(
        makeItem("event-1", {
          originalTitle: "Italy and EU leaders discuss trade in Rome",
          summary: "完整摘要：会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。",
          entities: [
            { name: "欧盟", type: "organization" },
            { name: "意大利总理", type: "person" },
          ],
        }),
      )
    }
    if (url.includes("before_cursor=cursor-older")) {
      return jsonResponse(feed([makeItem("event-old", { title: "意大利港口恢复常态运营" })], "cursor-older-2"))
    }
    if (url.includes("source_id=ansa")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-source", { title: "ANSA 报道意大利工业订单回升" }),
        ]),
      )
    }
    if (url.includes("date=2026-06-09")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-daily", { title: "意大利议会关注供应链安全", valueScore: 88 }),
        ]),
      )
    }
    if (url.startsWith("/api/v1/public/news")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-ansa-2", {
            title: "ANSA 追踪欧盟产业政策后续",
            tags: ["国际关系", "产业"],
          }),
          makeItem("event-reuters", {
            source: { id: "reuters", name: "Reuters", type: "api", credibilityLabel: "主流媒体" },
            title: "路透关注意大利能源政策调整",
            tags: ["经济", "能源"],
          }),
        ]),
      )
    }
    return jsonResponse({})
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

async function findLeadStory() {
  expect((await screen.findAllByText(LEAD_TITLE)).length).toBeGreaterThan(0)
}

describe("Phase 84 public portal app", () => {
  it("declares the shared site icon to avoid browser favicon 404s", () => {
    const html = readFileSync("index.html", "utf8")

    expect(html).toContain('rel="icon"')
    expect(html).toContain('href="/icons/icon-192.svg"')
  })

  afterEach(() => {
    cleanup()
    window.history.replaceState({}, "", "/")
    window.location.hash = ""
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("renders an AIHOT-style sidebar reader feed instead of the simplified top nav shell", async () => {
    installFetchMock()

    render(<App />)

    expect(await screen.findByRole("heading", { name: "新闻哨兵" })).toBeInTheDocument()
    expect(screen.getAllByRole("heading", { name: "新闻哨兵" })).toHaveLength(1)
    expect(screen.getByRole("heading", { name: "当前热点" })).toBeInTheDocument()
    expect(screen.getByText("新闻时间线")).toBeInTheDocument()
    const nav = screen.getByRole("navigation", { name: "公共站侧边栏" })
    expect(within(nav).getByRole("button", { name: /新闻哨兵 Breaking News/ })).toBeInTheDocument()
    expect(within(nav).getByRole("button", { name: /新闻纵览 All News/ })).toBeInTheDocument()
    expect(within(nav).getByRole("button", { name: /新闻日报 Daily News/ })).toBeInTheDocument()
    expect(within(nav).getByRole("button", { name: "Agent" })).toBeInTheDocument()
    expect(within(nav).getByRole("button", { name: "Update" })).toBeInTheDocument()
    expect(within(nav).getByRole("button", { name: /新闻哨兵 Breaking News/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    expect(screen.getAllByText(LEAD_TITLE).length).toBeGreaterThan(0)
    expect(screen.getAllByText("ANSA.it").length).toBeGreaterThan(0)
    expect(screen.getAllByText(/推荐理由/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/\d{2}:\d{2}/).length).toBeGreaterThan(0)
    expect(screen.getAllByText("意大利").length).toBeGreaterThan(0)
    expect(screen.queryByText("公共频道")).not.toBeInTheDocument()
    expect(screen.queryByText("态势摘要")).not.toBeInTheDocument()
    expect(screen.queryByText("监控目标")).not.toBeInTheDocument()
    expect(screen.queryByText("更新节奏")).not.toBeInTheDocument()
    expect(screen.queryByText("公共新闻 API smoke")).not.toBeInTheDocument()
    expect(screen.queryByText("跨目标展示最高价值新闻，先读判断，再看来源。")).not.toBeInTheDocument()
  })

  it("renders a compact sidebar utility bar without a framed logo or text link stack", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻哨兵" })
    const logo = screen.getByRole("link", { name: "NewsSentry" })
    expect(logo.className).not.toMatch(/\bborder\b/)
    expect(logo.className).not.toContain("bg-white/[0.03]")
    const sidebar = container.querySelector("aside")
    expect(sidebar?.className).not.toContain("bg-slate-950")
    expect(sidebar?.className).toContain("bg-card")

    const utilityNav = screen.getByRole("navigation", { name: "侧边栏辅助菜单" })
    expect(utilityNav.className).toContain("self-start")
    expect(utilityNav.className).toContain("w-full")
    expect(utilityNav.className).not.toContain("w-max")
    expect(within(utilityNav).getByRole("link", { name: "About" })).toBeInTheDocument()
    expect(within(utilityNav).getByRole("link", { name: "Method" })).toBeInTheDocument()
    expect(within(utilityNav).getByRole("link", { name: "Sources" })).toBeInTheDocument()
    expect(within(utilityNav).getByRole("link", { name: "Subscribe" })).toBeInTheDocument()
    expect(within(utilityNav).getAllByRole("button", { name: /切换主题/ })).toHaveLength(1)
    expect(screen.queryByLabelText("跟随系统")).not.toBeInTheDocument()
    expect(container.querySelector(".grid.gap-1.text-xs.text-slate-500")).toBeNull()
  })

  it("constrains the desktop sidebar controls so active items cannot spill into the content column", async () => {
    installFetchMock()
    window.location.hash = "#/daily?date=2026-06-09"

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻日报" })
    const sidebar = container.querySelector("aside")
    expect(sidebar?.className).toContain("overflow-hidden")
    const nav = screen.getByRole("navigation", { name: "公共站侧边栏" })
    expect(nav.className).toContain("min-w-0")
    expect(nav.className).toContain("overflow-hidden")

    const activeDailyButton = within(nav).getByRole("button", {
      name: /新闻日报 Daily News/,
      pressed: true,
    })
    expect(activeDailyButton.className).toContain("min-w-0")
    expect(activeDailyButton.className).toContain("max-w-full")
    expect(activeDailyButton.className).toContain("overflow-hidden")

    const utilityNav = screen.getByRole("navigation", { name: "侧边栏辅助菜单" })
    expect(utilityNav.className).toContain("w-full")
    expect(utilityNav.className).not.toContain("w-max")
    expect(within(utilityNav).getByRole("link", { name: "About" }).className).toContain("size-6")
    expect(within(utilityNav).getAllByRole("button", { name: /切换主题/ })[0].className).toContain(
      "size-6",
    )
  })

  it("uses the compact burgundy theme without cyan or blue public-reader accents", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻哨兵" })
    const renderedMarkup = container.innerHTML
    expect(renderedMarkup).not.toMatch(/cyan|text-blue|bg-blue|border-blue/i)

    const css = readFileSync("src/index.css", "utf8")
    expect(css).toContain("--primary: 356 64% 37%")
    expect(css).toContain("--primary: 356 58% 58%")
    expect(css).not.toMatch(/188 86% 53%|188 80% 12%|#22d3ee|#0891b2|cyan|--blue|--teal/i)
  })

  it("uses compact non-explanatory loading states on public reader pages", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/targets")) return jsonResponse({ targets: [] })
      if (url.startsWith("/api/v1/public/news")) return new Promise<Response>(() => undefined)
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

    await screen.findByRole("heading", { name: "新闻哨兵" })
    const loadingState = screen.getByLabelText("紧凑加载状态")
    expect(loadingState.className).toContain("py-2")
    expect(screen.getByText("更新中")).toBeInTheDocument()
    expect(screen.queryByText("正在整理最新新闻")).not.toBeInTheDocument()
    expect(screen.queryByText("新闻流会在最新信号整理好后自动出现。")).not.toBeInTheDocument()
  })

  it("keeps Agent and Update information pages dense instead of card-heavy explainers", async () => {
    installFetchMock()
    window.location.hash = "#/agent"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "Agent" })).toBeInTheDocument()
    const agentPanel = screen.getByLabelText("Agent 信息页")
    expect(agentPanel.className).toContain("py-2")
    expect(screen.queryByText("AGENT ACCESS")).not.toBeInTheDocument()
    expect(screen.queryByText(/P0 只开放说明/)).not.toBeInTheDocument()

    window.location.hash = "#/update"
    window.dispatchEvent(new HashChangeEvent("hashchange"))

    expect(await screen.findByRole("heading", { name: "Update" })).toBeInTheDocument()
    const updatePanel = screen.getByLabelText("Update 信息页")
    expect(updatePanel.className).toContain("py-2")
    expect(screen.queryByText("UPDATE LOG")).not.toBeInTheDocument()
    expect(screen.queryByText(/不替代内部部署日志/)).not.toBeInTheDocument()
  })

  it("keeps the feed shell on a full-width desktop grid instead of centering it in a max-width wrapper", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻哨兵" })
    const main = container.querySelector("main")
    expect(main).not.toBeNull()
    expect(main?.className).toContain("w-full")
    expect(main?.className).not.toContain("max-w-[1600px]")
    expect(container.firstElementChild?.className).toContain("lg:grid-cols-[160px_minmax(0,1fr)]")
  })

  it.each([
    ["event detail", "#/events/event-1?target_id=italy", LEAD_TITLE],
    ["sources directory", "#/sources", "来源目录"],
    ["daily digest", "#/daily?date=2026-06-09", "新闻日报"],
    ["analysis briefing", "#/analysis?target_id=italy", "态势简报"],
  ])("keeps the %s shell full-width instead of centering it", async (_label, hash, heading) => {
    installFetchMock()
    window.location.hash = hash

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: heading })
    const main = container.querySelector("main")
    expect(main).not.toBeNull()
    expect(main?.className).toContain("w-full")
    expect(main?.className).not.toContain("mx-auto")
    expect(main?.className).not.toContain("max-w-[1280px]")
  })

  it("renders the reading feed without desktop side rails", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻哨兵" })
    expect(container.querySelector("main > aside")).toBeNull()
    expect(screen.getByRole("button", { name: "筛选" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "国际关系" })).not.toBeInTheDocument()
  })

  it("does not reload the same feed during initial route hydration", async () => {
    const fetchMock = installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    await findLeadStory()
    const initialFeedCalls = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/public/news?featured=true&page_size=20",
    )
    expect(initialFeedCalls).toHaveLength(1)
  })

  it("falls back to the all-news stream when the featured feed is empty", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/targets")) {
        return jsonResponse({ targets: [] })
      }
      if (url === "/api/v1/public/news?featured=true&page_size=20") {
        return jsonResponse(feed([]))
      }
      if (url === "/api/v1/public/news?page_size=20") {
        return jsonResponse(feed([makeItem("event-fallback", { valueScore: 96 })]))
      }
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

    await findLeadStory()
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/v1/public/news?page_size=20"),
    ).toBe(true)
  })

  it("does not load target analysis on the default reading feed", async () => {
    let resolveFeed: (() => void) | undefined
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/targets")) {
        return jsonResponse({
          targets: [
            {
              target_id: "china-watch-en",
              display_name: "中国观察",
              primary_language: "en",
              monitoring_type: "country",
              monitoring_label: "国别监控目标",
              source_count: 12,
              event_count: 8,
              lifecycle: {},
              archived: false,
            },
            {
              target_id: "italy",
              display_name: "意大利新闻监控",
              primary_language: "it",
              monitoring_type: "country",
              monitoring_label: "国别监控目标",
              source_count: 163,
              event_count: 52,
              lifecycle: {},
              archived: false,
            },
          ],
        })
      }
      if (url.startsWith("/api/v1/public/targets/")) {
        return jsonResponse({
          target_id: url.includes("china-watch-en") ? "china-watch-en" : "italy",
          target_name: url.includes("china-watch-en") ? "中国观察" : "意大利新闻监控",
          days: 14,
          summary: {
            total_events: 1,
            high_value_events: 1,
            avg_news_value_score: 80,
            avg_china_relevance: 60,
          },
          classification_distribution: [],
          source_distribution: [],
          top_entities: [],
          topic_trends: [],
          sentiment_trend: [],
          active_chains: [],
          generated_at: "2026-06-09T08:00:00Z",
        })
      }
      if (url.startsWith("/api/v1/public/news")) {
        return new Promise<Response>((resolve) => {
          resolveFeed = () => {
            resolve(
              new Response(JSON.stringify(feed([makeItem("event-1")])), {
                status: 200,
                headers: { "Content-Type": "application/json", ETag: '"etag"' },
              }),
            )
          }
        })
      }
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/v1/targets"))).toBe(
        true,
      ),
    )
    await new Promise((resolve) => window.setTimeout(resolve, 25))
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/v1/public/targets/china-watch-en/analysis"),
      ),
    ).toBe(false)

    resolveFeed?.()
    await findLeadStory()
    await new Promise((resolve) => window.setTimeout(resolve, 25))
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/v1/public/targets/italy/analysis"),
      ),
    ).toBe(false)
  })

  it("opens the filter drawer only when the reader asks for more filters", async () => {
    installFetchMock()

    render(<App />)

    await findLeadStory()
    expect(screen.queryByRole("button", { name: "国际关系" })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "筛选" }))

    expect(await screen.findByRole("heading", { name: "筛选新闻" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "国际关系" })).toBeInTheDocument()
    expect(screen.getByLabelText("搜索新闻")).toBeInTheDocument()
  })

  it("uses target chips as the primary target entry and keeps the feed shape", async () => {
    installFetchMock()

    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getByRole("button", { name: "意大利" }))

    expect(window.location.pathname).toBe("/public-app/")
    expect(window.location.search).toContain("channel=targets")
    expect(window.location.search).toContain("target_id=italy")
    expect(await screen.findByRole("heading", { name: "意大利" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "当前热点" })).toBeInTheDocument()
  })

  it("keeps All News target selection in the top bar without a separate target overview panel", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "新闻纵览" })).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "目标入口列表" })).not.toBeInTheDocument()
    const targetGroups = screen.getByRole("region", { name: "目标分组筛选" })
    expect(within(targetGroups).getByText("国别分类")).toBeInTheDocument()
    expect(within(targetGroups).getByText("话题分类")).toBeInTheDocument()
    expect(within(targetGroups).getByRole("button", { name: "意大利" })).toBeInTheDocument()
    expect(within(targetGroups).getByRole("button", { name: "涉中" })).toBeInTheDocument()
    expect(within(targetGroups).queryByRole("button", { name: "空目标" })).not.toBeInTheDocument()
    expect(screen.queryByText("事件样本")).not.toBeInTheDocument()
  })

  it("does not turn missing recommendation reasons into fixed placeholder copy", async () => {
    const fetchMock = installFetchMock()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/targets")) {
        return jsonResponse({ targets: [] })
      }
      if (url.startsWith("/api/v1/public/news")) {
        return jsonResponse(
          feed([
            makeItem("event-without-reason", {
              recommendationReason: null,
              valueLabel: "关注",
              valueScore: 74,
            }),
          ]),
        )
      }
      return jsonResponse({})
    })

    render(<App />)

    await findLeadStory()
    expect(
      screen.queryByText("已进入公共新闻流，等待更多背景和关联信号增强。"),
    ).not.toBeInTheDocument()
    expect(screen.queryByText("推荐理由：")).not.toBeInTheDocument()
  })

  it("shows reader-friendly copy while the first news request is slow", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)))

    render(<App />)

    expect(screen.getByLabelText("紧凑加载状态")).toBeInTheDocument()
    expect(screen.getByText("更新中")).toBeInTheDocument()
    expect(screen.queryByText("正在整理最新新闻")).not.toBeInTheDocument()
    expect(screen.queryByText("新闻流会在最新信号整理好后自动出现。")).not.toBeInTheDocument()
    expect(screen.queryByText(/API|stage|target_id|page_size/)).not.toBeInTheDocument()
  })

  it("shows new items as a non-interrupting banner before inserting them", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    installFetchMock()
    render(<App />)

    await findLeadStory()
    await vi.advanceTimersByTimeAsync(30_000)

    expect(await screen.findByRole("button", { name: "有 1 条新动态" })).toBeInTheDocument()
    expect(screen.queryByText("欧盟宣布新的贸易磋商议程")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "有 1 条新动态" }))

    expect(screen.getAllByText("欧盟宣布新的贸易磋商议程").length).toBeGreaterThan(0)
  })

  it("loads older news and keeps the mobile bottom navigation active", async () => {
    installFetchMock()
    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }))

    expect(await screen.findByText("意大利港口恢复常态运营")).toBeInTheDocument()
    expect(screen.getByRole("navigation", { name: "移动端公共菜单" })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /新闻哨兵/ })[1]).toHaveAttribute("aria-pressed", "true")
  })

  it("opens a reader event detail page with source, entities, copy, and related signals", async () => {
    installFetchMock()
    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getAllByRole("link", { name: /详情/ })[0])
    window.dispatchEvent(new HashChangeEvent("hashchange"))

    expect(await screen.findByRole("heading", { name: LEAD_TITLE })).toBeInTheDocument()
    expect(await screen.findByText("Italy and EU leaders discuss trade in Rome")).toBeInTheDocument()
    expect(
      await screen.findByText("完整摘要：会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。"),
    ).toBeInTheDocument()
    expect(screen.getAllByText("ANSA.it").length).toBeGreaterThan(0)
    expect(screen.getByText("欧盟")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "复制摘要" })).toBeInTheDocument()
    expect(screen.getByText("同来源信号")).toBeInTheDocument()
  })

  it("preserves the targets channel context when opening and leaving an event detail page", async () => {
    installFetchMock()
    window.history.replaceState({}, "", "/public-app/?channel=targets&target_id=italy")

    render(<App />)

    await findLeadStory()
    const detailLink = screen.getAllByRole("link", { name: /详情/ })[0]
    expect(detailLink.getAttribute("href")).toContain("return_to=%2Fpublic-app%2F%3Fchannel%3Dtargets%26target_id%3Ditaly")

    fireEvent.click(detailLink)

    expect(
      await screen.findByRole("heading", { name: LEAD_TITLE }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("link", { name: "返回新闻流" }))

    await screen.findByRole("heading", { name: "意大利" })
    expect(window.location.pathname).toBe("/public-app/")
    expect(window.location.search).toContain("channel=targets")
    expect(window.location.search).toContain("target_id=italy")
  })

  it("shows event detail before related signals finish loading", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/public/news/event-1")) {
        return jsonResponse(
          makeItem("event-1", {
            originalTitle: "Italy and EU leaders discuss trade in Rome",
            summary: "完整摘要：会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。",
          }),
        )
      }
      if (url.includes("target_id=italy") && url.includes("page_size=50")) {
        return new Promise<Response>(() => undefined)
      }
      if (url.startsWith("/api/v1/public/news")) {
        return jsonResponse(feed([makeItem("event-1")]))
      }
      if (url.startsWith("/api/v1/targets")) {
        return jsonResponse({ targets: [] })
      }
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)
    window.location.hash = "#/events/event-1?target_id=italy"

    render(<App />)

    expect(
      await screen.findByRole(
        "heading",
        { name: LEAD_TITLE },
        { timeout: 500 },
      ),
    ).toBeInTheDocument()
    expect(screen.getByText("Italy and EU leaders discuss trade in Rome")).toBeInTheDocument()
  })

  it("uses a smaller related-signals request window on the detail page", async () => {
    const fetchMock = installFetchMock()
    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getAllByRole("link", { name: /详情/ })[0])

    await screen.findByRole("heading", { name: LEAD_TITLE })
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).startsWith("/api/v1/public/news?target_id=italy&page_size=12"),
        ),
      ).toBe(true),
    )
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/v1/public/news?target_id=italy&page_size=50"),
      ),
    ).toBe(false)
  })

  it("renders source directory and source detail routes from the existing news API", async () => {
    installFetchMock()
    window.location.hash = "#/sources"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "来源目录" })).toBeInTheDocument()
    expect(screen.getByText("近期活跃")).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole("link", { name: /ANSA.it/ })[0])
    window.dispatchEvent(new HashChangeEvent("hashchange"))

    expect(await screen.findByRole("heading", { name: "ANSA.it" })).toBeInTheDocument()
    expect(await screen.findByText("ANSA 报道意大利工业订单回升")).toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: /详情/ }).length).toBeGreaterThan(0)
  })

  it("renders a reader daily digest without requiring backend daily API", async () => {
    installFetchMock()
    window.location.hash = "#/daily?date=2026-06-09"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "新闻日报" })).toBeInTheDocument()
    const dailySummaryBar = screen.getByLabelText("日报摘要栏")
    expect(dailySummaryBar.className).toContain("py-2")
    expect(within(dailySummaryBar).getByText("2 条")).toBeInTheDocument()
    expect(within(dailySummaryBar).queryByText("日报")).not.toBeInTheDocument()
    expect(screen.getAllByText("2026-06-09").length).toBeGreaterThan(0)
    expect(screen.getByRole("heading", { name: "今日速读" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "主题简报" })).toBeInTheDocument()
    expect(screen.getAllByText("意大利议会关注供应链安全").length).toBeGreaterThan(0)
    expect(screen.queryByText(/优先阅读今日速读/)).not.toBeInTheDocument()
    expect(screen.queryByText("主要主题")).not.toBeInTheDocument()
    expect(screen.queryByText("覆盖来源")).not.toBeInTheDocument()
    expect(
      screen
        .getAllByRole("button", { name: /新闻日报/ })
        .some((button) => button.getAttribute("aria-pressed") === "true"),
    ).toBe(true)
  })

  it("hydrates feed filters from the public app hash query", async () => {
    const fetchMock = installFetchMock()
    window.location.hash =
      "#/feed?channel=targets&target_id=italy&source_id=ansa&category=国际关系&q=欧盟&date=2026-06-09"

    render(<App />)

    expect(await screen.findByDisplayValue("欧盟")).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = String(input)
        return (
          url.startsWith("/api/v1/public/news?") &&
          url.includes("target_id=italy") &&
          url.includes("source_id=ansa") &&
          url.includes("category=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB") &&
          url.includes("q=%E6%AC%A7%E7%9B%9F") &&
          url.includes("date=2026-06-09")
        )
      }),
    ).toBe(true)
    expect(
      screen
        .getAllByRole("button", { name: /新闻纵览/ })
        .some((button) => button.getAttribute("aria-pressed") === "true"),
    ).toBe(true)
  })

  it("renders Agent and Update information pages without calling a new backend API", async () => {
    const fetchMock = installFetchMock()
    window.location.hash = "#/agent"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "Agent" })).toBeInTheDocument()
    expect(screen.getByLabelText("Agent 信息页")).toBeInTheDocument()
    expect(screen.getByText("llms.txt")).toBeInTheDocument()
    expect(screen.getByText("Public API")).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/v1/public/agent"))).toBe(false)

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "公共站侧边栏" })).getByRole("button", {
        name: "Update",
      }),
    )

    expect(await screen.findByRole("heading", { name: "Update" })).toBeInTheDocument()
    expect(screen.getByLabelText("Update 信息页")).toBeInTheDocument()
    expect(screen.getByText("AIHOT 化公共阅读体验")).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/v1/public/update"))).toBe(false)
  })

  it("writes feed filter changes back into the public app url", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getByRole("button", { name: "筛选" }))
    fireEvent.click(await screen.findByRole("button", { name: "国际关系" }))

    expect(window.location.pathname).toBe("/public-app/")
    expect(window.location.search).toContain("category=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB")
  })
})
