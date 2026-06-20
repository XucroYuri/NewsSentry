import { describe, expect, it, vi } from "vitest"

import {
  buildPublicNewsUrl,
  getPublicNewsItem,
  getPublicTargetAnalysis,
  listPublicNews,
  listTargets,
  PublicNewsApiError,
} from "@/lib/api"
import type { PublicNewsFeedResponse, PublicNewsItem } from "@/types/public-news"

const item: PublicNewsItem = {
  id: "event-1",
  targetId: "italy",
  targetLabel: "意大利新闻监控",
  source: {
    id: "ansa",
    name: "ANSA.it",
    type: "rss",
    credibilityLabel: "主流媒体",
  },
  publishedAt: "2026-06-09T08:00:00Z",
  title: "意大利总理与欧盟领导人讨论贸易关系",
  originalTitle: "Italy and EU leaders discuss trade",
  summary: "会谈聚焦贸易政策与市场准入。",
  recommendationReason: "该新闻同时涉及欧盟政策和意大利政府议程。",
  originalUrl: "https://example.com/news",
  detailUrl: "/public-app/events/event-1?target_id=italy",
  tags: ["国际关系"],
  issueTags: ["国际关系"],
  relatedTags: ["涉欧"],
  regionTags: ["意大利"],
  entities: [{ name: "欧盟", type: "organization" }],
  relatedCount: 2,
  discussionCount: 0,
  valueLabel: "精选",
  valueScore: 92,
  chinaRelevanceLabel: "中",
}

const feed: PublicNewsFeedResponse = {
  items: [item],
  latestCursor: "cursor-new",
  nextCursor: "cursor-old",
  pollAfterMs: 60000,
  hasNewer: false,
  total: 1,
}

function jsonResponse(payload: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json", ...init.headers },
    ...init,
  })
}

describe("public news API client", () => {
  it("builds the public news query with backend parameter names", () => {
    expect(
      buildPublicNewsUrl({
        featured: true,
        targetId: "italy",
        sourceId: "ansa",
        category: "国际关系",
        beforeCursor: "old",
        pageSize: 5,
      }),
    ).toBe(
      "/api/v1/public/news?featured=true&target_id=italy&source_id=ansa&category=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB&before_cursor=old&page_size=5",
    )
  })

  it("returns typed feed data and cache headers", async () => {
    const fetcher = vi.fn(async () =>
      jsonResponse(feed, {
        headers: {
          ETag: '"feed-tag"',
          "X-Poll-After-Ms": "60000",
        },
      }),
    ) as typeof fetch

    const result = await listPublicNews({ pageSize: 5 }, { fetcher })

    expect(fetcher).toHaveBeenCalledWith("/api/v1/public/news?page_size=5", {
      headers: new Headers(),
      signal: undefined,
    })
    expect(result.notModified).toBe(false)
    expect(result.etag).toBe('"feed-tag"')
    expect(result.data?.items[0]?.source.name).toBe("ANSA.it")
  })

  it("handles 304 without parsing a body", async () => {
    const fetcher = vi.fn(async () =>
      new Response(null, {
        status: 304,
        headers: {
          ETag: '"feed-tag"',
          "X-Poll-After-Ms": "180000",
        },
      }),
    ) as typeof fetch

    const result = await listPublicNews({ sinceCursor: "cursor-new" }, { etag: '"feed-tag"', fetcher })

    expect(result).toEqual({
      data: null,
      etag: '"feed-tag"',
      notModified: true,
      pollAfterMs: 180000,
    })
  })

  it("rejects invalid feed shapes", async () => {
    const fetcher = vi.fn(async () => jsonResponse({ items: [{}] })) as typeof fetch

    await expect(listPublicNews({}, { fetcher })).rejects.toBeInstanceOf(PublicNewsApiError)
  })

  it("loads a public news detail item", async () => {
    const fetcher = vi.fn(async () => jsonResponse(item)) as typeof fetch

    const detail = await getPublicNewsItem("event-1", { targetId: "italy", fetcher })

    expect(fetcher).toHaveBeenCalledWith("/api/v1/public/news/event-1?target_id=italy", {
      signal: undefined,
    })
    expect(detail.title).toContain("意大利总理")
  })

  it("loads public targets for reader filters", async () => {
    const fetcher = vi.fn(async () =>
      jsonResponse({
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
      }),
    ) as typeof fetch

    const response = await listTargets({ fetcher })

    expect(fetcher).toHaveBeenCalledWith("/api/v1/regions", {
      signal: undefined,
    })
    expect(response.targets[0]?.display_name).toBe("意大利新闻监控")
  })

  it("loads public target analysis for the right rail", async () => {
    const fetcher = vi.fn(async () =>
      jsonResponse({
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
        top_entities: [],
        topic_trends: [],
        sentiment_trend: [],
        active_chains: [],
        generated_at: "2026-06-09T08:00:00Z",
      }),
    ) as typeof fetch

    const response = await getPublicTargetAnalysis("italy", 14, { fetcher })

    expect(fetcher).toHaveBeenCalledWith("/api/v1/public/targets/italy/analysis?days=14", {
      signal: undefined,
    })
    expect(response.summary.total_events).toBe(52)
  })
})
