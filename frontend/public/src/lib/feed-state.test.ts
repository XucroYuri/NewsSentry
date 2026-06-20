import { describe, expect, it } from "vitest"

import {
  appendOlderItems,
  makeFeedQuery,
  mergeNewerItems,
  nextPollDelayMs,
  shouldPausePolling,
} from "@/lib/feed-state"
import type { PublicNewsItem } from "@/types/public-news"

function item(id: string, title = id): PublicNewsItem {
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
    title,
    originalTitle: null,
    summary: "摘要",
    recommendationReason: "推荐理由",
    originalUrl: "https://example.com/news",
    detailUrl: "/public-app/events/" + id + "?target_id=italy",
    tags: ["国际关系"],
    issueTags: ["国际关系"],
    relatedTags: ["涉欧"],
    regionTags: ["意大利"],
    entities: [],
    relatedCount: 0,
    discussionCount: 0,
    valueLabel: "精选",
    valueScore: 80,
    chinaRelevanceLabel: "中",
  }
}

describe("feed state helpers", () => {
  it("maps reader filters to the public news API query", () => {
    expect(
      makeFeedQuery({
        channel: "featured",
        targetId: "italy",
        sourceId: "ansa",
        issue: "国际关系",
        related: "涉欧",
        search: "欧盟",
        pageSize: 20,
      }),
    ).toEqual({
      featured: true,
      targetId: "italy",
      sourceId: "ansa",
      issue: "国际关系",
      related: "涉欧",
      q: "欧盟",
      pageSize: 20,
    })
  })

  it("merges newer items above the current list without duplicates", () => {
    const current = [item("b"), item("a")]
    const newer = [item("c"), item("b", "duplicate")]

    expect(mergeNewerItems(current, newer).map((entry) => entry.id)).toEqual(["c", "b", "a"])
  })

  it("appends older pages without duplicating existing items", () => {
    const current = [item("c"), item("b")]
    const older = [item("b"), item("a")]

    expect(appendOlderItems(current, older).map((entry) => entry.id)).toEqual(["c", "b", "a"])
  })

  it("clamps normal polling and backs off failures", () => {
    expect(nextPollDelayMs({ serverMs: 2_000, failureCount: 0 })).toBe(30_000)
    expect(nextPollDelayMs({ serverMs: 60_000, failureCount: 2 })).toBeGreaterThan(60_000)
  })

  it("pauses polling when the page is hidden or offline", () => {
    expect(shouldPausePolling({ visibilityState: "hidden", online: true })).toBe(true)
    expect(shouldPausePolling({ visibilityState: "visible", online: false })).toBe(true)
    expect(shouldPausePolling({ visibilityState: "visible", online: true })).toBe(false)
  })
})
