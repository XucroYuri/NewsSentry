import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import type { PublicNewsFeedResponse, PublicNewsItem } from "@/types/public-news"

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
    title: "意大利总理与欧盟领导人讨论对华贸易关系",
    originalTitle: "Italy and EU leaders discuss trade",
    summary: "会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。",
    recommendationReason: "该新闻同时涉及欧盟政策、意大利产业与中国相关贸易议题。",
    originalUrl: "https://example.com/news",
    detailUrl: "/#/news/target/italy/events/" + id,
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

describe("Phase 84 public portal app", () => {
  afterEach(() => {
    cleanup()
    window.location.hash = ""
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("renders an AIHOT-style reader feed instead of the Phase 83 smoke shell", async () => {
    installFetchMock()

    render(<App />)

    expect(await screen.findByRole("heading", { name: "精选新闻" })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: "精选" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    expect(screen.getAllByRole("button", { name: "全部" }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole("button", { name: "日报" }).length).toBeGreaterThan(0)
    expect(screen.getByText("意大利总理与欧盟领导人讨论对华贸易关系")).toBeInTheDocument()
    expect(screen.getAllByText("ANSA.it").length).toBeGreaterThan(0)
    expect(screen.getAllByText(/推荐理由/).length).toBeGreaterThan(0)
    expect(screen.queryByText("公共新闻 API smoke")).not.toBeInTheDocument()
  })

  it("does not reload the same feed during initial route hydration", async () => {
    const fetchMock = installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    const initialFeedCalls = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/public/news?featured=true&page_size=20",
    )
    expect(initialFeedCalls).toHaveLength(1)
  })

  it("waits for feed context before loading right rail analysis on the feed page", async () => {
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
    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).startsWith("/api/v1/public/targets/italy/analysis"),
        ),
      ).toBe(true),
    )
  })

  it("shows reader-friendly copy while the first news request is slow", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)))

    render(<App />)

    expect(screen.getByText("正在整理最新新闻")).toBeInTheDocument()
    expect(screen.getByText("新闻流会在最新信号整理好后自动出现。")).toBeInTheDocument()
    expect(screen.queryByText(/API|stage|target_id|page_size/)).not.toBeInTheDocument()
  })

  it("shows new items as a non-interrupting banner before inserting them", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    installFetchMock()
    render(<App />)

    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    await vi.advanceTimersByTimeAsync(30_000)

    expect(await screen.findByRole("button", { name: "有 1 条新动态" })).toBeInTheDocument()
    expect(screen.queryByText("欧盟宣布新的贸易磋商议程")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "有 1 条新动态" }))

    expect(screen.getByText("欧盟宣布新的贸易磋商议程")).toBeInTheDocument()
  })

  it("loads older news and keeps the mobile bottom navigation active", async () => {
    installFetchMock()
    render(<App />)

    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }))

    expect(await screen.findByText("意大利港口恢复常态运营")).toBeInTheDocument()
    expect(screen.getByRole("navigation", { name: "移动端公共频道" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "信号" })).toHaveAttribute("aria-pressed", "true")
  })

  it("opens a reader event detail page with source, entities, copy, and related signals", async () => {
    installFetchMock()
    render(<App />)

    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    fireEvent.click(screen.getAllByRole("link", { name: /详情/ })[0])
    window.dispatchEvent(new HashChangeEvent("hashchange"))

    expect(await screen.findByRole("heading", { name: "意大利总理与欧盟领导人讨论对华贸易关系" })).toBeInTheDocument()
    expect(await screen.findByText("Italy and EU leaders discuss trade in Rome")).toBeInTheDocument()
    expect(
      await screen.findByText("完整摘要：会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。"),
    ).toBeInTheDocument()
    expect(screen.getAllByText("ANSA.it").length).toBeGreaterThan(0)
    expect(screen.getByText("欧盟")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "复制摘要" })).toBeInTheDocument()
    expect(screen.getByText("同来源信号")).toBeInTheDocument()
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
        { name: "意大利总理与欧盟领导人讨论对华贸易关系" },
        { timeout: 500 },
      ),
    ).toBeInTheDocument()
    expect(screen.getByText("Italy and EU leaders discuss trade in Rome")).toBeInTheDocument()
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
    expect(
      screen
        .getAllByRole("button", { name: "来源" })
        .some((button) => button.getAttribute("aria-pressed") === "true"),
    ).toBe(true)
  })

  it("renders a reader daily digest without requiring backend daily API", async () => {
    installFetchMock()
    window.location.hash = "#/daily?date=2026-06-09"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "今日日报" })).toBeInTheDocument()
    expect(screen.getByText("2026-06-09")).toBeInTheDocument()
    expect(screen.getByText("意大利议会关注供应链安全")).toBeInTheDocument()
    expect(screen.getByText(/重点新闻 2 条/)).toBeInTheDocument()
    expect(
      screen
        .getAllByRole("button", { name: "日报" })
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
        .getAllByRole("button", { name: "目标" })
        .some((button) => button.getAttribute("aria-pressed") === "true"),
    ).toBe(true)
  })

  it("writes feed filter changes back into the public app hash", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    await screen.findByText("意大利总理与欧盟领导人讨论对华贸易关系")
    fireEvent.click(screen.getAllByRole("button", { name: "国际关系" })[0])

    expect(window.location.hash).toContain("#/feed?")
    expect(window.location.hash).toContain("channel=featured")
    expect(window.location.hash).toContain("category=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB")
  })
})
