import { describe, expect, it } from "vitest"

import {
  buildDailyDigest,
  buildPublicDetailUrl,
  buildRelatedBuckets,
  buildSourceSummaries,
} from "@/lib/public-view"
import type { PublicNewsItem } from "@/types/public-news"

function item(id: string, overrides: Partial<PublicNewsItem> = {}): PublicNewsItem {
  return {
    id,
    targetId: "italy",
    targetLabel: "意大利新闻监控",
    source: { id: "ansa", name: "ANSA.it", type: "rss", credibilityLabel: "主流媒体" },
    publishedAt: "2026-06-09T08:00:00Z",
    title: `新闻 ${id}`,
    originalTitle: `Original ${id}`,
    summary: `摘要 ${id}`,
    recommendationReason: `推荐理由 ${id}`,
    originalUrl: `https://example.com/${id}`,
    detailUrl: "/public-app/events/" + id + "?target_id=italy",
    tags: ["国际关系", "贸易"],
    issueTags: ["国际关系"],
    relatedTags: ["涉欧"],
    regionTags: ["意大利"],
    entities: [{ name: "欧盟", type: "organization" }],
    relatedCount: 0,
    discussionCount: 0,
    valueLabel: "精选",
    valueScore: 90,
    chinaRelevanceLabel: "中",
    ...overrides,
  }
}

describe("public reader view helpers", () => {
  it("builds new public app detail links instead of legacy hash URLs", () => {
    expect(buildPublicDetailUrl(item("event-1"))).toBe(
      "/public-app/events/event-1?target_id=italy",
    )
  })

  it("aggregates source summaries from public news", () => {
    const sources = buildSourceSummaries([
      item("a"),
      item("b", { source: { id: "ansa", name: "ANSA.it", type: "rss" } }),
      item("c", { source: { id: "reuters", name: "Reuters", type: "api" } }),
    ])

    expect(sources.map((source) => [source.id, source.count, source.statusLabel])).toEqual([
      ["ansa", 2, "近期活跃"],
      ["reuters", 1, "近期较少更新"],
    ])
  })

  it("builds a reader daily digest for a selected date", () => {
    const digest = buildDailyDigest(
      [
        item("a", { valueScore: 82, tags: ["国际关系", "贸易"] }),
        item("b", { valueScore: 94, tags: ["政治"] }),
        item("old", { publishedAt: "2026-06-08T08:00:00Z", tags: ["经济"] }),
      ],
      "2026-06-09",
    )

    expect(digest.total).toBe(2)
    expect(digest.topItems[0]?.id).toBe("b")
    expect(digest.topicLabels).toEqual(["国际关系", "贸易", "政治"])
    expect(digest.sourceLabels).toEqual(["ANSA.it"])
  })

  it("groups related events by source, target, and topic without including the current event", () => {
    const current = item("current", { source: { id: "ansa", name: "ANSA.it", type: "rss" } })
    const buckets = buildRelatedBuckets(current, [
      current,
      item("same-source", { source: { id: "ansa", name: "ANSA.it", type: "rss" } }),
      item("same-target", { source: { id: "rai", name: "Rai", type: "rss" }, tags: ["经济"] }),
      item("same-topic", {
        targetId: "france",
        source: { id: "lemonde", name: "Le Monde", type: "rss" },
        tags: ["国际关系"],
      }),
    ])

    expect(buckets.sameSource.map((entry) => entry.id)).toEqual(["same-source"])
    expect(buckets.sameTarget.map((entry) => entry.id)).toEqual(["same-source", "same-target"])
    expect(buckets.sameTopic.map((entry) => entry.id)).toEqual(["same-source", "same-topic"])
  })
})
