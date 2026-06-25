import { describe, expect, it } from "vitest"

import {
  appendOlderItems,
  formatDateGroup,
  groupItemsByDate,
  makeFeedQuery,
  mergeNewerItems,
  nextPollDelayMs,
  shouldPausePolling,
} from "@/lib/feed-state"
import type { PublicNewsItem } from "@/types/public-news"

function item(id: string, title?: string, publishedAt?: string): PublicNewsItem {
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
    publishedAt: publishedAt ?? "2026-06-09T08:00:00Z",
    title: title ?? id,
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

// ── groupItemsByDate + formatDateGroup ──

describe("groupItemsByDate", () => {
  it("groups items by date key (YYYY-MM-DD)", () => {
    const items = [
      item("a", undefined, "2026-06-09T08:00:00Z"),
      item("b", undefined, "2026-06-09T12:00:00Z"),
      item("c", undefined, "2026-06-08T08:00:00Z"),
    ]
    const groups = groupItemsByDate(items)
    expect(groups).toHaveLength(2)
    expect(groups[0]!.key).toBe("2026-06-09")
    expect(groups[0]!.items.map((i) => i.id)).toEqual(["a", "b"])
    expect(groups[1]!.key).toBe("2026-06-08")
    expect(groups[1]!.items.map((i) => i.id)).toEqual(["c"])
  })

  it("handles items with invalid dates", () => {
    const items = [
      item("a", undefined, "invalid-date"),
      item("b", undefined, "2026-06-09T08:00:00Z"),
    ]
    const groups = groupItemsByDate(items)
    expect(groups).toHaveLength(2)
    // unknown key comes first (inserted first), then the valid date
    const unknownGroup = groups.find((g) => g.key === "unknown")
    expect(unknownGroup).toBeDefined()
    expect(unknownGroup!.items.map((i) => i.id)).toEqual(["a"])
    expect(unknownGroup!.label).toBe("时间待确认")
  })

  it("preserves insertion order by date occurrence", () => {
    const items = [
      item("first", undefined, "2026-06-07T08:00:00Z"),
      item("second", undefined, "2026-06-09T08:00:00Z"),
      item("third", undefined, "2026-06-07T12:00:00Z"),
    ]
    const groups = groupItemsByDate(items)
    expect(groups[0]!.key).toBe("2026-06-07")
    expect(groups[1]!.key).toBe("2026-06-09")
    // second item gets appended to existing 06-07 group
    expect(groups[0]!.items.map((i) => i.id)).toEqual(["first", "third"])
  })

  it("returns empty array for no items", () => {
    expect(groupItemsByDate([])).toEqual([])
  })
})

describe("formatDateGroup", () => {
  it('returns "今天" for today', () => {
    const today = new Date().toISOString()
    expect(formatDateGroup(today)).toBe("今天")
  })

  it('returns "昨天" for yesterday', () => {
    const yesterday = new Date()
    yesterday.setDate(yesterday.getDate() - 1)
    expect(formatDateGroup(yesterday.toISOString())).toBe("昨天")
  })

  it("returns zh-CN formatted date for older dates", () => {
    const result = formatDateGroup("2026-01-15T08:00:00Z")
    expect(result).toContain("1月")
    expect(result).toContain("15日")
  })

  it('returns "时间待确认" for invalid dates', () => {
    expect(formatDateGroup("invalid")).toBe("时间待确认")
  })
})
