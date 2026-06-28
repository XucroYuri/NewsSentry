import "@testing-library/jest-dom/vitest"

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { afterEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import { formatTime } from "@/lib/public-view"
import type { PublicNewsFeedResponse, PublicNewsItem } from "@/types/public-news"

const LEAD_TITLE = "意大利总理与欧盟领导人讨论对华贸易关系"
const LEAD_ORIGINAL_TITLE = "Italy and EU leaders discuss trade"

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
    originalTitle: LEAD_ORIGINAL_TITLE,
    summary: "会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。",
    recommendationReason: "该新闻同时涉及欧盟政策、意大利产业与中国相关贸易议题。",
    originalUrl: "https://example.com/news",
    detailUrl: "/public-app/events/" + id + "?target_id=italy",
    tags: ["国际关系", "贸易"],
    issueTags: ["国际关系"],
    relatedTags: ["涉中", "涉欧"],
    regionTags: ["意大利"],
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
    if (url.startsWith("/api/v1/public/bootstrap")) {
      return jsonResponse({
        news: feed([
          makeItem("event-1"),
          makeItem("event-ansa-2", {
            title: "ANSA 追踪欧盟产业政策后续",
            originalTitle: "ANSA tracks follow-up on EU industrial policy",
            tags: ["国际关系", "产业"],
          }),
          makeItem("event-reuters", {
            source: { id: "reuters", name: "Reuters", type: "api", credibilityLabel: "主流媒体" },
            title: "路透关注意大利能源政策调整",
            originalTitle: "Reuters follows Italy energy policy adjustments",
            tags: ["经济", "能源"],
          }),
        ]),
        regions: {
          regions: [
            {
              region_id: "italy",
              display_name: "意大利新闻监控",
              primary_language: "it",
              region_type: "country",
              source_count: 163,
              event_count: 52,
              lifecycle: {},
              archived: false,
            },
          ],
        },
        facets: {
          regions: [{ id: "italy", label: "意大利", count: 52 }],
          issues: [
            { id: "国际关系", label: "国际关系", count: 20 },
            { id: "能源", label: "能源", count: 8 },
          ],
          related: [
            { id: "涉中", label: "涉中", count: 14 },
            { id: "涉欧", label: "涉欧", count: 10 },
          ],
        },
        generatedAt: "2026-06-21T00:00:00Z",
      })
    }
    if (url.startsWith("/api/v1/regions")) {
      return jsonResponse({
        regions: [
          {
            region_id: "italy",
            display_name: "意大利新闻监控",
            primary_language: "it",
            region_type: "country",
            source_count: 163,
            event_count: 52,
            lifecycle: {},
            archived: false,
          },
          {
            region_id: "empty-region",
            display_name: "空地区新闻监控",
            primary_language: "en",
            region_type: "country",
            source_count: 0,
            event_count: 0,
            lifecycle: {},
            archived: false,
          },
        ],
      })
    }
    if (url.startsWith("/api/v1/public/facets")) {
      return jsonResponse({
        regions: [{ id: "italy", label: "意大利", count: 52 }],
        issues: [
          { id: "国际关系", label: "国际关系", count: 20 },
          { id: "能源", label: "能源", count: 8 },
        ],
        related: [
          { id: "涉中", label: "涉中", count: 14 },
          { id: "涉欧", label: "涉欧", count: 10 },
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
      return jsonResponse(
        feed([
          makeItem("event-new", {
            title: "欧盟宣布新的贸易磋商议程",
            originalTitle: "EU announces new trade talks agenda",
          }),
        ], "cursor-new"),
      )
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
      return jsonResponse(
        feed([
          makeItem("event-old", {
            title: "意大利港口恢复常态运营",
            originalTitle: "Italian ports resume normal operations",
          }),
        ], "cursor-older-2"),
      )
    }
    if (url.includes("source_id=ansa")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-source", {
            title: "ANSA 报道意大利工业订单回升",
            originalTitle: "ANSA reports Italian industrial orders rebound",
          }),
        ]),
      )
    }
    if (url.includes("date=2026-06-09")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-daily", {
            title: "意大利议会关注供应链安全",
            originalTitle: "Italian parliament scrutinizes supply-chain security",
            valueScore: 88,
          }),
        ]),
      )
    }
    if (url.startsWith("/api/v1/public/news")) {
      return jsonResponse(
        feed([
          makeItem("event-1"),
          makeItem("event-ansa-2", {
            title: "ANSA 追踪欧盟产业政策后续",
            originalTitle: "ANSA tracks follow-up on EU industrial policy",
            tags: ["国际关系", "产业"],
          }),
          makeItem("event-reuters", {
            source: { id: "reuters", name: "Reuters", type: "api", credibilityLabel: "主流媒体" },
            title: "路透关注意大利能源政策调整",
            originalTitle: "Reuters follows Italy energy policy adjustments",
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
    const icon = readFileSync("public/icons/icon-192.svg", "utf8")

    expect(html).toContain('<html lang="zh-CN">')
    expect(html).toContain("<title>News Sentry | 新闻哨兵</title>")
    expect(html).toContain('name="description"')
    expect(html).toContain('property="og:title" content="News Sentry | 新闻哨兵"')
    expect(html).toContain('rel="canonical" href="https://news-sentry.com/public-app/"')
    expect(html).toContain('"@context": "https://schema.org"')
    expect(html).toContain('"@type": "CollectionPage"')
    expect(html).toContain('rel="icon"')
    expect(html).toContain('href="/icons/icon-192.svg"')
    expect(icon).toContain("<svg")
  })

  it("ships Cloudflare Pages cache headers for immutable static assets", () => {
    const headers = readFileSync("public/_headers", "utf8")

    expect(headers).toContain("/assets/*")
    expect(headers).toContain("/icons/*")
    expect(headers).toContain("/sitemap.xml")
    expect(headers).toContain("Strict-Transport-Security")
    expect(headers).toContain("Content-Security-Policy")
    expect(headers).toContain("X-Frame-Options: DENY")
    expect(headers).toContain("/public-app*")
    expect(headers).toContain("max-age=0, must-revalidate, no-transform")
    expect(headers).toContain("max-age=31536000, immutable")
  })

  it("ships a static sitemap for Cloudflare Pages discoverability checks", () => {
    const sitemap = readFileSync("public/sitemap.xml", "utf8")
    const robots = readFileSync("public/robots.txt", "utf8")

    expect(robots).toContain("Sitemap: https://news-sentry.com/sitemap.xml")
    expect(sitemap).toContain("<urlset")
    expect(sitemap).toContain("<loc>https://news-sentry.com/public-app/</loc>")
    expect(sitemap).toContain("<loc>https://news-sentry.com/public-app/sources</loc>")
  })

  afterEach(() => {
    cleanup()
    document.body.innerHTML = ""
    window.history.replaceState({}, "", "/")
    window.location.hash = ""
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("renders a breaking-news home instead of the all-news timeline", async () => {
    installFetchMock()

    render(<App />)

    expect(await screen.findByRole("heading", { name: "极速突发" })).toBeInTheDocument()
    expect(screen.getAllByRole("heading", { name: "极速突发" })).toHaveLength(1)
    expect(await screen.findByRole("region", { name: "极速突发" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "高价值动态" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "最近推进" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "突发快捷入口" })).toBeInTheDocument()
    expect(screen.queryByText("新闻时间线")).not.toBeInTheDocument()
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
    expect(screen.getAllByRole("heading", { name: LEAD_TITLE }).length).toBeGreaterThan(0)
    expect(screen.getAllByText("ANSA.it").length).toBeGreaterThan(0)
    expect(screen.getAllByText("会谈聚焦贸易政策与市场准入，双方同意继续保持沟通。").length).toBeGreaterThan(0)
    expect(screen.getByText(/为什么重要：/)).toBeInTheDocument()
    expect(screen.getAllByText("92").length).toBeGreaterThan(0)
    expect(
      within(screen.getByRole("region", { name: "极速突发" })).getByRole("button", {
        name: "新闻纵览",
      }),
    ).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "筛选" })).not.toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "地区议题相关筛选" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /详情/ })).not.toBeInTheDocument()
    expect(screen.getAllByText(/\d{2}:\d{2}/).length).toBeGreaterThan(0)
    expect(screen.getAllByText("意大利").length).toBeGreaterThan(0)
    expect(screen.queryByText("公共频道")).not.toBeInTheDocument()
    expect(screen.queryByText("态势摘要")).not.toBeInTheDocument()
    expect(screen.queryByText("监控目标")).not.toBeInTheDocument()
    expect(screen.queryByText("更新节奏")).not.toBeInTheDocument()
    expect(screen.queryByText("公共新闻 API smoke")).not.toBeInTheDocument()
    expect(screen.queryByText("跨目标展示最高价值新闻，先读判断，再看来源。")).not.toBeInTheDocument()
  })

  it("renders timeline news cards with translated title, source context, image preview, tags, and index branches", async () => {
    const imageUrl = "https://example.com/news-image.jpg"
    const publishedAt = "2026-06-09T08:00:00Z"
    const cardTimeLabel = formatTime(publishedAt)
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) return jsonResponse({ regions: [] })
      if (url.startsWith("/api/v1/public/facets")) return jsonResponse({ regions: [], issues: [], related: [] })
      if (url.startsWith("/api/v1/public/news")) {
        return jsonResponse(
          feed([
            makeItem("event-with-image", {
              publishedAt,
              title: "微软双向转售 GPT 与 DeepSeek 成全球最大 AI 中间商",
              originalTitle:
                "Microsoft quietly becomes China's gateway to OpenAI and routes models through Singapore",
              summary:
                "微软把 OpenAI 与 DeepSeek 模型同时接入跨境客户网络，折射出全球 AI 供应链和合规路径正在重组。",
              tags: ["DeepSeek", "Microsoft", "行业动态"],
              issueTags: ["科技"],
              relatedTags: ["涉中", "涉美"],
              regionTags: ["全球"],
              imageUrls: [imageUrl],
              valueScore: 75,
            }),
          ]),
        )
      }
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    const matchingLinks = await screen.findAllByRole("link", {
      name: /微软双向转售 GPT 与 DeepSeek 成全球最大 AI 中间商/,
    })
    const card = matchingLinks.find((link) => link.tagName.toLowerCase() === "article")
    if (!card) throw new Error("Expected timeline article card to render")
    expect(card).toHaveClass("px-2.5")
    expect(card).toHaveClass("py-2")
    expect(screen.getAllByText(cardTimeLabel).length).toBeGreaterThan(0)
    expect(within(card).queryByText(cardTimeLabel)).not.toBeInTheDocument()
    expect(within(card).getByText("ANSA.it")).toBeInTheDocument()
    const cardHeading = within(card).getByRole("heading", { name: /微软双向转售 GPT 与 DeepSeek/ })
    expect(cardHeading).toHaveClass("text-sm")
    expect(cardHeading).toHaveClass("leading-5")
    expect(
      within(card).getByText(
        "Microsoft quietly becomes China's gateway to OpenAI and routes models through Singapore",
      ),
    ).toHaveClass("text-xs")
    expect(within(card).getByText(/全球 AI 供应链和合规路径正在重组/)).toHaveClass("text-xs")
    const metaRow = card.querySelector(".flex.min-w-0.items-start.justify-between")
    if (!metaRow) throw new Error("Expected news card meta row")
    expect(metaRow).toHaveClass("text-[11px]")
    expect(within(metaRow as HTMLElement).getByText("全球")).toBeInTheDocument()
    expect(within(metaRow as HTMLElement).getByText("科技")).toBeInTheDocument()
    expect(within(metaRow as HTMLElement).getByText("涉中")).toBeInTheDocument()
    expect(within(metaRow as HTMLElement).getByText("DeepSeek")).toBeInTheDocument()
    expect(within(card).queryByLabelText("新闻标签")).not.toBeInTheDocument()
    const scoreBadge = within(metaRow as HTMLElement).getByLabelText("Breaking News 分值 75")
    expect(scoreBadge).toHaveTextContent("75")
    expect(scoreBadge).toHaveClass("ml-auto")
    expect(within(card).queryByLabelText("Breaking News 指数")).not.toBeInTheDocument()
    expect(within(card).queryByText("Breaking News")).not.toBeInTheDocument()
    expect(within(card).queryByText("时效")).not.toBeInTheDocument()
    expect(within(card).queryByText("影响")).not.toBeInTheDocument()
    expect(within(card).queryByText("信源")).not.toBeInTheDocument()
    expect(within(card).queryByText("标签")).not.toBeInTheDocument()

    const thumbnail = within(card).getByRole("button", { name: /浏览大图/ })
    expect(within(thumbnail).getByRole("img", { name: /新闻缩略图/ })).toHaveAttribute("src", imageUrl)

    fireEvent.click(thumbnail)

    const dialog = await screen.findByRole("dialog", { name: "新闻图片预览" })
    expect(within(dialog).getByRole("img", { name: /新闻大图/ })).toHaveAttribute("src", imageUrl)
  })

  it("suppresses redundant hot-topic summaries while keeping the timeline summary", async () => {
    const redundantSummary = "意大利各省的骄傲：巡游全意大利各地的游行活动"
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) return jsonResponse({ regions: [] })
      if (url.startsWith("/api/v1/public/facets")) return jsonResponse({ regions: [], issues: [], related: [] })
      if (url.startsWith("/api/v1/public/news")) {
        return jsonResponse(
          feed([
            makeItem("event-redundant-hot", {
              title: "意大利各省骄傲之旅：巡游全意大利各地游行盛况",
              originalTitle: "Pride in provincia : viaggio nei cortei di tutta Italia",
              summary: redundantSummary,
              valueScore: 100,
            }),
          ]),
        )
      }
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    const hotTopics = await screen.findByRole("region", { name: "当前热点" })
    expect(within(hotTopics).queryByText(redundantSummary)).not.toBeInTheDocument()
    expect(screen.getByText(redundantSummary)).toBeInTheDocument()
  })

  it("keeps the hot-topic strip visually compact", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    const hotTopics = await screen.findByRole("region", { name: "当前热点" })
    expect(hotTopics).toHaveClass("py-1.5")
    expect(hotTopics).not.toHaveClass("py-3")
    const hotLinks = within(hotTopics).getAllByRole("link")
    expect(hotLinks[0]).toHaveClass("py-1")
    expect(hotLinks[0]).not.toHaveClass("p-2")
    expect(hotLinks[0]).not.toHaveClass("border")
    expect(hotLinks[0]).not.toHaveClass("bg-background/80")
    expect(hotLinks[0]).not.toHaveClass("rounded-md")
  })

  it("collapses a date group when the date header is clicked", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await findLeadStory()
    const todayGroup = screen.getByRole("region", { name: "6月9日周二" })
    expect(within(todayGroup).getByText(LEAD_ORIGINAL_TITLE)).toBeInTheDocument()

    const toggle = within(todayGroup).getByRole("button", { name: /6月9日周二/ })
    expect(toggle).toHaveAttribute("aria-expanded", "true")

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(within(todayGroup).queryByText(LEAD_ORIGINAL_TITLE)).not.toBeInTheDocument()
  })

  it("automatically inserts polled news at the top with an entering marker", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await findLeadStory()
    expect(screen.queryByRole("heading", { name: "欧盟宣布新的贸易磋商议程" })).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    const newCards = await screen.findAllByRole("link", { name: /欧盟宣布新的贸易磋商议程/ })
    const newArticle = newCards.find((node) => node.tagName.toLowerCase() === "article")
    if (!newArticle) throw new Error("Expected newly inserted timeline article")
    expect(newArticle).toHaveAttribute("data-new-entry", "true")
    expect(newArticle).toHaveClass("news-card-entering")
    expect(screen.queryByRole("button", { name: /有 \\d+ 条新动态/ })).not.toBeInTheDocument()
  })

  it("renders a compact sidebar utility bar without a framed logo or text link stack", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "极速突发" })
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
    expect(within(utilityNav).queryByRole("link", { name: "About" })).not.toBeInTheDocument()
    expect(within(utilityNav).queryByRole("link", { name: "Method" })).not.toBeInTheDocument()
    expect(within(utilityNav).getByRole("link", { name: "Sources" })).toHaveAttribute(
      "href",
      "/sources",
    )
    expect(within(utilityNav).getByRole("link", { name: "Subscribe" })).toHaveAttribute(
      "href",
      "/subscribe",
    )
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
    expect(within(utilityNav).queryByRole("link", { name: "About" })).not.toBeInTheDocument()
    expect(within(utilityNav).queryByRole("link", { name: "Method" })).not.toBeInTheDocument()
    expect(within(utilityNav).getByRole("link", { name: "Sources" }).className).toContain("size-6")
    expect(within(utilityNav).getAllByRole("button", { name: /切换主题/ })[0].className).toContain(
      "size-6",
    )
  })

  it("uses the compact burgundy theme without cyan or blue public-reader accents", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "极速突发" })
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
      if (url.startsWith("/api/v1/regions")) return jsonResponse({ regions: [] })
      if (url.startsWith("/api/v1/public/news")) return new Promise<Response>(() => undefined)
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

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
    expect(within(updatePanel).getByText("v2.0.0")).toBeInTheDocument()
    expect(within(updatePanel).queryByText("AIHOT 化公共阅读体验")).not.toBeInTheDocument()
    expect(screen.queryByText("UPDATE LOG")).not.toBeInTheDocument()
    expect(screen.queryByText(/不替代内部部署日志/)).not.toBeInTheDocument()
  })

  it("keeps the feed shell on a full-width desktop grid instead of centering it in a max-width wrapper", async () => {
    installFetchMock()

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "极速突发" })
    const main = container.querySelector("main")
    expect(main).not.toBeNull()
    expect(main?.className).toContain("w-full")
    expect(main?.className).not.toContain("max-w-[1600px]")
    expect(container.firstElementChild?.className).toContain("lg:grid-cols-[160px_minmax(0,1fr)]")
  })

  it.each([
    ["event detail", "#/events/event-1?target_id=italy", LEAD_TITLE],
    ["sources directory", "#/sources", "信源管理"],
    ["subscribe", "#/subscribe", "创建订阅"],
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

  it("renders Subscribe as a compact React public-shell page without a fake email form", async () => {
    installFetchMock()
    window.location.hash = "#/subscribe"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "创建订阅" })).toBeInTheDocument()
    expect(screen.getByText("订阅 Subscribe")).toBeInTheDocument()
    // 3-step funnel: email input exists, subscribe button is present
    const emailInput = screen.getByPlaceholderText("your@email.com")
    expect(emailInput).toBeInTheDocument()
    expect(emailInput).toHaveAttribute("type", "email")
    expect(screen.getByRole("button", { name: "订阅" })).toBeInTheDocument()
  })

  it("renders the reading feed without desktop side rails", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    const { container } = render(<App />)

    await screen.findByRole("heading", { name: "新闻纵览" })
    expect(container.querySelector("main > aside")).toBeNull()
    expect(screen.getByRole("button", { name: "筛选" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "地区议题相关筛选" })).toBeInTheDocument()
  })

  it("does not reload the same feed during initial route hydration", async () => {
    const fetchMock = installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    await findLeadStory()
    const initialFeedCalls = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/public/news?featured=true&page_size=20",
    )
    expect(initialFeedCalls).toHaveLength(0)
  })

  it("hydrates the default featured feed from SSR without an initial news request", async () => {
    const ssrTitle = "SSR 注入的首屏新闻"
    document.body.innerHTML = `<script id="news-sentry-feed" type="application/json">${JSON.stringify(
      feed([makeItem("event-ssr", { title: ssrTitle })]),
    )}</script>`
    const fetchMock = installFetchMock()
    window.location.hash = "#/feed?channel=featured"

    render(<App />)

    expect((await screen.findAllByText(ssrTitle)).length).toBeGreaterThan(0)
    const initialNewsCalls = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/v1/public/news?featured=true&page_size=20",
    )
    expect(initialNewsCalls).toHaveLength(0)
  })

  it("renders first-paint news from bootstrap while standalone feed is slow", async () => {
    const bootstrapTitle = "首屏启动数据里的意大利新闻"
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/public/bootstrap")) {
        return jsonResponse({
          news: feed([makeItem("event-bootstrap", { title: bootstrapTitle })]),
          regions: {
            regions: [
              {
                region_id: "italy",
                display_name: "意大利新闻监控",
                primary_language: "it",
                region_type: "country",
                source_count: 163,
                event_count: 52,
                lifecycle: {},
                archived: false,
              },
            ],
          },
          facets: {
            regions: [{ id: "italy", label: "意大利", count: 52 }],
            issues: [{ id: "外交", label: "外交", count: 3 }],
            related: [{ id: "涉欧", label: "涉欧", count: 2 }],
          },
          generatedAt: "2026-06-21T00:00:00Z",
        })
      }
      if (url.startsWith("/api/v1/public/news")) {
        return new Promise<Response>(() => undefined)
      }
      return jsonResponse({ regions: [], issues: [], related: [] })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<App />)

    expect((await screen.findAllByText(bootstrapTitle)).length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/v1/public/bootstrap"))).toBe(true)
  })

  it("falls back to the all-news stream when the featured feed is empty", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) {
        return jsonResponse({ regions: [] })
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
      if (url.startsWith("/api/v1/regions")) {
        return jsonResponse({
          regions: [
            {
              region_id: "italy",
              display_name: "意大利新闻监控",
              primary_language: "it",
              region_type: "country",
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
      expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/v1/regions"))).toBe(
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
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await findLeadStory()
    expect(screen.getByRole("button", { name: "外交" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /ANSA.it/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "筛选" }))

    expect(await screen.findByRole("heading", { name: "筛选新闻" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /ANSA.it/ })).toBeInTheDocument()
    expect(screen.getByLabelText("搜索新闻")).toBeInTheDocument()
  })

  it("uses region chips as the primary region entry and keeps the feed shape", async () => {
    installFetchMock()

    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getByRole("button", { name: /意大利/ }))

    expect(window.location.pathname).toBe("/public-app/")
    expect(window.location.search).toContain("channel=all")
    expect(window.location.search).toContain("target_id=italy")
    expect(await screen.findByRole("heading", { name: "意大利" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "当前热点" })).toBeInTheDocument()
  })

  it("keeps All News region, issue, and related selection in the top bar without topic targets", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "新闻纵览" })).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "目标入口列表" })).not.toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "目标分组筛选" })).not.toBeInTheDocument()
    const facets = screen.getByRole("region", { name: "地区议题相关筛选" })
    expect(within(facets).getByText("地区")).toBeInTheDocument()
    expect(within(facets).getByText("议题")).toBeInTheDocument()
    expect(within(facets).getByText("相关")).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "全部" })).toBeInTheDocument()
    expect(within(facets).queryByRole("button", { name: "全部地区" })).not.toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "意大利" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "外交" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "涉中" })).toBeInTheDocument()
    expect(within(facets).queryByRole("button", { name: "涉中新闻监控" })).not.toBeInTheDocument()
    expect(within(facets).queryByRole("button", { name: "空地区" })).not.toBeInTheDocument()
    expect(screen.queryByText("国别分类")).not.toBeInTheDocument()
    expect(screen.queryByText("话题分类")).not.toBeInTheDocument()
    expect(screen.queryByText("事件样本")).not.toBeInTheDocument()
  })

  it("wraps dense facet chips and shortens long facet labels without changing filter values", async () => {
    const fetchMock = installFetchMock()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) {
        return jsonResponse({ regions: [] })
      }
      if (url.startsWith("/api/v1/public/facets")) {
        return jsonResponse({
          regions: [],
          issues: [
            { id: "humanitarian-aid", label: "人道主义援助", count: 4 },
            { id: "sports-management", label: "赛事管理", count: 3 },
            { id: "lgbtq-rights", label: "LGBTQ+权益", count: 2 },
          ],
          related: [
            { id: "international-trade", label: "国际贸易", count: 5 },
            { id: "middle-east-situation", label: "中东局势", count: 2 },
          ],
        })
      }
      if (url.startsWith("/api/v1/public/news")) {
        return jsonResponse(feed([makeItem("event-1")]))
      }
      return jsonResponse({})
    })
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    const facets = await screen.findByRole("region", { name: "地区议题相关筛选" })
    const regionRow = within(facets).getByLabelText("地区筛选")
    const issueRow = within(facets).getByLabelText("议题筛选")
    const relatedRow = within(facets).getByLabelText("相关筛选")
    expect(regionRow.parentElement?.className).toContain("md:items-start")
    expect(issueRow.parentElement?.className).toContain("md:items-start")
    expect(relatedRow.parentElement?.className).toContain("md:items-start")
    expect(issueRow.parentElement?.className).not.toContain("md:items-center")
    expect(issueRow.className).toContain("flex-wrap")
    expect(issueRow.className).not.toContain("overflow-x-auto")
    expect(relatedRow.className).toContain("flex-wrap")
    expect(relatedRow.className).not.toContain("overflow-x-auto")
    expect(within(facets).getByRole("button", { name: "人道援助" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "赛事" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "LGBTQ" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "外贸" })).toBeInTheDocument()
    expect(within(facets).getByRole("button", { name: "中东" })).toBeInTheDocument()
    expect(within(facets).queryByText("人道主义援助")).not.toBeInTheDocument()

    fireEvent.click(within(facets).getByRole("button", { name: "人道援助" }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("issue=%E4%BA%BA%E9%81%93%E4%B8%BB%E4%B9%89%E6%8F%B4%E5%8A%A9"),
        ),
      ).toBe(true),
    )
  })

  it("does not turn missing recommendation reasons into fixed placeholder copy", async () => {
    const fetchMock = installFetchMock()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) {
        return jsonResponse({ regions: [] })
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

  it("keeps an empty public feed visually blank without leaking processing copy or raw titles", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) return jsonResponse({ regions: [] })
      if (url.startsWith("/api/v1/public/news")) return jsonResponse(feed([]))
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v1/public/news"))).toBe(
        true,
      )
    })
    expect(screen.queryByRole("heading", { name: "中文加工中" })).not.toBeInTheDocument()
    expect(screen.queryByText("中文标题、摘要和 AI 推荐理由完成后会自动进入公共阅读流。")).not.toBeInTheDocument()
    expect(screen.queryByText("等待内容")).not.toBeInTheDocument()
    expect(screen.queryByText(/Untranslated|French title|正在整理最新新闻/)).not.toBeInTheDocument()
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

  it("auto-inserts new items without interrupting the reader with a banner", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    installFetchMock()
    window.location.hash = "#/feed?channel=all"
    render(<App />)

    await findLeadStory()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })

    expect(screen.queryByRole("button", { name: /有 \d+ 条新动态/ })).not.toBeInTheDocument()
    expect(await screen.findAllByText("欧盟宣布新的贸易磋商议程")).not.toHaveLength(0)
    expect(screen.getAllByText("EU announces new trade talks agenda").length).toBeGreaterThan(0)
  })

  it("loads older news and keeps the mobile bottom navigation active", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"
    render(<App />)

    await findLeadStory()
    // 验证加载更多区域存在（IntersectionObserver 在 jsdom 中不可用，手动验证）
    expect(screen.getByText("加载更多")).toBeInTheDocument()
  })

  it("opens a reader event detail page with source, entities, copy, and related signals", async () => {
    installFetchMock()
    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getAllByRole("link", { name: new RegExp(LEAD_TITLE) })[0])
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
    const detailLink = screen.getAllByRole("link", { name: new RegExp(LEAD_TITLE) })[0]
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
      if (url.startsWith("/api/v1/regions")) {
        return jsonResponse({ regions: [] })
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
    fireEvent.click(screen.getAllByRole("link", { name: new RegExp(LEAD_TITLE) })[0])

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

  it("renders source management with category filters and source detail routes from the existing news API", async () => {
    installFetchMock()
    window.location.hash = "#/sources"

    render(<App />)

    expect(await screen.findByRole("heading", { name: "信源管理" })).toBeInTheDocument()
    const sourceManagement = screen.getByRole("region", { name: "信源管理" })
    expect(within(sourceManagement).queryByText("来源")).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "来源目录" })).not.toBeInTheDocument()
    expect(screen.getByRole("region", { name: "信源分类筛选" })).toBeInTheDocument()
    expect(screen.getByText("按类型分组")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "类型 2" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "状态 2" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "地区 2" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /全部类型/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /全部状态/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /全部地区/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "媒体源 1" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "API 1" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "意大利 2" })).toBeInTheDocument()
    expect(screen.getAllByText("近期活跃").length).toBeGreaterThan(0)
    expect(screen.getAllByText("信源 ID").length).toBeGreaterThan(0)
    expect(screen.getAllByText("覆盖地区").length).toBeGreaterThan(0)
    expect(screen.getAllByText("最新样本").length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole("button", { name: "API 1" }))
    expect(screen.queryByRole("link", { name: /ANSA.it/ })).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Reuters/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "类型 2" }))

    fireEvent.click(screen.getAllByRole("link", { name: /ANSA.it/ })[0])
    window.dispatchEvent(new HashChangeEvent("hashchange"))

    expect(await screen.findByRole("heading", { name: "ANSA.it" })).toBeInTheDocument()
    expect(await screen.findByText("ANSA 报道意大利工业订单回升")).toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: /ANSA 报道意大利工业订单回升/ }).length).toBeGreaterThan(0)
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

  it("keeps an empty daily page blank below the compact collecting status", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith("/api/v1/regions")) return jsonResponse({ regions: [] })
      if (url.startsWith("/api/v1/public/news")) return jsonResponse(feed([]))
      return jsonResponse({})
    })
    vi.stubGlobal("fetch", fetchMock)
    window.location.hash = "#/daily?date=2026-06-20"

    render(<App />)

    const dailySummaryBar = await screen.findByLabelText("日报摘要栏")
    expect(within(dailySummaryBar).getByText("采集中")).toBeInTheDocument()
    expect(screen.queryByText("今日样本仍在采集/增强")).not.toBeInTheDocument()
    expect(
      screen.queryByText("日报会在公开新闻进入后自动形成重点、主题、来源和风险摘要。"),
    ).not.toBeInTheDocument()
    expect(screen.queryByText("等待内容")).not.toBeInTheDocument()
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
          url.startsWith("/api/v1/public/bootstrap?") &&
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
    expect(screen.getByText("v2.0.0")).toBeInTheDocument()
    expect(screen.queryByText("AIHOT 化公共阅读体验")).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/v1/public/update"))).toBe(false)
  })

  it("writes feed filter changes back into the public app url", async () => {
    installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await findLeadStory()
    fireEvent.click(screen.getByRole("button", { name: /外交/ }))

    expect(window.location.pathname).toBe("/public-app/")
    expect(window.location.search).toContain("issue=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB")
  })

  it("filters the feed by issue and related facets from the compact top bar", async () => {
    const fetchMock = installFetchMock()
    window.location.hash = "#/feed?channel=all"

    render(<App />)

    await screen.findByRole("heading", { name: "新闻纵览" })
    fireEvent.click(screen.getByRole("button", { name: "能源" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => String(input).includes("issue=%E8%83%BD%E6%BA%90")),
      ).toBe(true),
    )

    fireEvent.click(screen.getByRole("button", { name: "涉中" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => String(input).includes("related=%E6%B6%89%E4%B8%AD")),
      ).toBe(true),
    )
  })
})
