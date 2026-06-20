import "@testing-library/jest-dom/vitest"

import { createElement } from "react"
import { render } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { SeoHead } from "@/components/seo/seo-head"
import { buildPublicAppPath, parseLocationRoute } from "@/lib/routes"
import {
  applySiteSeo,
  buildCanonicalUrl,
  buildEventSeoPayload,
  buildRouteCanonicalPath,
  buildRouteSeoPayload,
} from "@/lib/seo/site-seo"
import type { PublicNewsItem } from "@/types/public-news"

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
    detailUrl: "/public-app/events/" + id + "?target_id=italy",
    tags: ["国际关系", "贸易"],
    issueTags: ["国际关系"],
    relatedTags: ["涉欧"],
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

describe("public site seo runtime", () => {
  beforeEach(() => {
    document.head.innerHTML = ""
    document.title = ""
  })

  it("builds canonical urls for public feed and detail routes", () => {
    expect(
      buildCanonicalUrl(
        "https://news-sentry.com",
        buildRouteCanonicalPath({
          name: "feed",
          channel: "featured",
          search: new URLSearchParams(),
        }),
      ),
    ).toBe("https://news-sentry.com/public-app/")

    expect(
      buildCanonicalUrl(
        "https://news-sentry.com",
        buildRouteCanonicalPath({
          name: "feed",
          channel: "targets",
          search: new URLSearchParams({
            target_id: "italy",
            category: "国际关系",
          }),
        }),
      ),
    ).toBe("https://news-sentry.com/public-app/")

    expect(
      buildCanonicalUrl(
        "https://news-sentry.com",
        buildRouteCanonicalPath({
          name: "event",
          eventId: "event-1",
          targetId: "italy",
          search: new URLSearchParams(),
        }),
      ),
    ).toBe("https://news-sentry.com/public-app/events/event-1?target_id=italy")
  })

  it("builds non hash public reader hrefs for feed, detail, source, and analysis routes", () => {
    expect(
      buildPublicAppPath({
        name: "feed",
        channel: "featured",
        search: new URLSearchParams(),
      }),
    ).toBe("/public-app/")
    expect(
      buildPublicAppPath({
        name: "event",
        eventId: "event-1",
        targetId: "italy",
        search: new URLSearchParams(),
      }),
    ).toBe("/public-app/events/event-1?target_id=italy")
    expect(
      buildPublicAppPath({
        name: "sourceDetail",
        sourceId: "ansa",
        search: new URLSearchParams(),
      }),
    ).toBe("/public-app/sources/ansa")
    expect(
      buildPublicAppPath({
        name: "analysis",
        targetId: "italy",
        section: undefined,
        search: new URLSearchParams(),
      }),
    ).toBe("/public-app/analysis?target_id=italy")
  })

  it("uses the source management title for the sources route", () => {
    const payload = buildRouteSeoPayload({
      origin: "https://news-sentry.com",
      route: { name: "sources", search: new URLSearchParams() },
    })

    expect(payload.title).toBe("信源管理 | News Sentry")
    expect(payload.description).toContain("管理")
  })

  it("builds a detail seo payload with news article json ld", () => {
    const payload = buildEventSeoPayload({
      origin: "https://news-sentry.com",
      route: {
        name: "event",
        eventId: "event-1",
        targetId: "italy",
        search: new URLSearchParams("target_id=italy"),
      },
      item: makeItem("event-1"),
    })

    expect(payload).not.toBeNull()
    if (!payload) throw new Error("expected detail seo payload")
    expect(payload.title).toContain("意大利总理与欧盟领导人讨论对华贸易关系")
    expect(payload.canonicalUrl).toBe(
      "https://news-sentry.com/public-app/events/event-1?target_id=italy",
    )
    expect(payload.jsonLd).toMatchObject({
      "@context": "https://schema.org",
      "@type": "NewsArticle",
      headline: "意大利总理与欧盟领导人讨论对华贸易关系",
      mainEntityOfPage: "https://news-sentry.com/public-app/events/event-1?target_id=italy",
    })
  })

  it("backfills detail canonical target_id from the loaded item when the route is missing it", () => {
    const payload = buildEventSeoPayload({
      origin: "https://news-sentry.com",
      route: {
        name: "event",
        eventId: "event-1",
        targetId: undefined,
        search: new URLSearchParams(),
      },
      item: makeItem("event-1", { targetId: "italy" }),
    })

    expect(payload).not.toBeNull()
    if (!payload) throw new Error("expected backfilled detail seo payload")
    expect(payload.canonicalUrl).toBe(
      "https://news-sentry.com/public-app/events/event-1?target_id=italy",
    )
    expect(payload.jsonLd).toMatchObject({
      mainEntityOfPage: "https://news-sentry.com/public-app/events/event-1?target_id=italy",
      url: "https://news-sentry.com/public-app/events/event-1?target_id=italy",
    })
  })

  it("withholds detail seo payload until an effective target_id is known", () => {
    const payload = buildEventSeoPayload({
      origin: "https://news-sentry.com",
      route: {
        name: "event",
        eventId: "event-1",
        targetId: undefined,
        search: new URLSearchParams(),
      },
      item: null,
    })

    expect(payload).toBeNull()
  })

  it("applies managed title, meta tags, canonical link, and json ld to the document head", () => {
    const payload = buildRouteSeoPayload({
      origin: "https://news-sentry.com",
      route: {
        name: "feed",
        channel: "featured",
        search: new URLSearchParams(),
      },
    })

    applySiteSeo(payload)

    expect(document.title).toBe(payload.title)
    expect(document.head.querySelector('meta[name="description"]')?.getAttribute("content")).toBe(
      payload.description,
    )
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://news-sentry.com/public-app/",
    )
    expect(document.head.querySelector('meta[property="og:url"]')?.getAttribute("content")).toBe(
      "https://news-sentry.com/public-app/",
    )
    expect(document.head.querySelector('script[type="application/ld+json"]')?.textContent).toContain(
      '"CollectionPage"',
    )
  })

  it("clears managed seo state when SeoHead transitions from a payload to null", () => {
    const payload = buildRouteSeoPayload({
      origin: "https://news-sentry.com",
      route: {
        name: "feed",
        channel: "featured",
        search: new URLSearchParams(),
      },
    })

    const { rerender } = render(createElement(SeoHead, { payload }))

    expect(document.title).toBe(payload.title)
    expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://news-sentry.com/public-app/",
    )
    expect(document.head.querySelector('script[type="application/ld+json"]')).toBeInTheDocument()

    rerender(createElement(SeoHead, { payload: null }))

    expect(document.title).toBe("News Sentry | 新闻哨兵")
    expect(document.head.querySelector('link[rel="canonical"]')).not.toBeInTheDocument()
    expect(document.head.querySelector('script[type="application/ld+json"]')).not.toBeInTheDocument()
    expect(document.head.querySelector('meta[property="og:url"]')).not.toBeInTheDocument()
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      "content",
      "News Sentry 新闻哨兵面向中文读者追踪全球新闻，按地区、议题和相关对象筛选重点事件，提供中文摘要、原文标题、信源信息与 Breaking News 指数。",
    )
  })

  it("parses non hash public app urls while preserving hash route support", () => {
    expect(
      parseLocationRoute({
        pathname: "/public-app/events/event-1",
        search: "?target_id=italy",
        hash: "",
      }),
    ).toMatchObject({
      name: "event",
      eventId: "event-1",
      targetId: "italy",
    })

    expect(
      parseLocationRoute({
        pathname: "/public-app/events/event-1",
        search: "?target_id=italy",
        hash: "#/daily?date=2026-06-09",
      }),
    ).toMatchObject({
      name: "daily",
      date: "2026-06-09",
    })
  })
})
