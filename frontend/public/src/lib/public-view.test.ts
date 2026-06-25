import { describe, expect, it } from "vitest"

import {
  buildDailyDigest,
  buildPublicDetailUrl,
  buildRelatedBuckets,
  buildSourceSummaries,
  dateKey,
  formatFullTime,
  formatTime,
  sourceTypeLabel,
  summaryText,
  targetShortLabel,
  todayKey,
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

// ── formatTime / formatFullTime ──

describe("formatTime", () => {
  it("formats ISO date to HH:MM in zh-CN", () => {
    const result = formatTime("2026-06-09T14:30:00Z")
    // zh-CN 2-digit hour/minute
    expect(result).toMatch(/^\d{2}:\d{2}$/)
  })

  it('returns "时间待确认" for invalid input', () => {
    expect(formatTime("invalid")).toBe("时间待确认")
    expect(formatTime("")).toBe("时间待确认")
  })
})

describe("formatFullTime", () => {
  it("formats ISO date to MM/DD HH:MM in zh-CN", () => {
    const result = formatFullTime("2026-06-09T14:30:00Z")
    // zh-CN 2-digit month/day + 2-digit hour/minute
    expect(result).toMatch(/^\d{2}\/\d{2} \d{2}:\d{2}$/)
  })

  it('returns "时间待确认" for invalid input', () => {
    expect(formatFullTime("invalid")).toBe("时间待确认")
  })
})

// ── sourceTypeLabel ──

describe("sourceTypeLabel", () => {
  it("maps known source types to Chinese labels", () => {
    expect(sourceTypeLabel("rss")).toBe("媒体源")
    expect(sourceTypeLabel("api")).toBe("API")
    expect(sourceTypeLabel("web")).toBe("网页")
    expect(sourceTypeLabel("social")).toBe("社媒")
    expect(sourceTypeLabel("official")).toBe("官方")
    expect(sourceTypeLabel("unknown")).toBe("来源")
  })
})

// ── targetShortLabel ──

describe("targetShortLabel", () => {
  it("strips known suffix patterns", () => {
    expect(targetShortLabel("意大利新闻监控")).toBe("意大利")
    expect(targetShortLabel("法国监控目标")).toBe("法国")
    expect(targetShortLabel("德国国别监控")).toBe("德国")
    expect(targetShortLabel("日本观察")).toBe("日本")
  })

  it('returns "目标" for empty/falsy input', () => {
    expect(targetShortLabel(null)).toBe("目标")
    expect(targetShortLabel(undefined)).toBe("目标")
    expect(targetShortLabel("")).toBe("目标")
    expect(targetShortLabel("   ")).toBe("目标")
  })

  it("returns trimmed value when no suffix matches", () => {
    expect(targetShortLabel("美国")).toBe("美国")
    expect(targetShortLabel("  英国  ")).toBe("英国")
  })
})

// ── summaryText ──

describe("summaryText", () => {
  it("joins title, summary, recommendation, source, URL with newlines", () => {
    const text = summaryText(item("ev1"))
    expect(text).toContain("新闻 ev1")
    expect(text).toContain("摘要：摘要 ev1")
    expect(text).toContain("推荐理由：推荐理由 ev1")
    expect(text).toContain("来源：ANSA.it")
    expect(text).toContain("原文：https://example.com/ev1")
  })

  it("omits null/undefined optional fields", () => {
    const text = summaryText(
      item("ev2", { summary: null, recommendationReason: null, originalUrl: null }),
    )
    expect(text).not.toContain("摘要：")
    expect(text).not.toContain("推荐理由：")
    expect(text).not.toContain("原文：")
    expect(text).toContain("新闻 ev2")
    expect(text).toContain("来源：ANSA.it")
  })
})

// ── dateKey / todayKey ──

describe("dateKey", () => {
  it("extracts YYYY-MM-DD from ISO string", () => {
    expect(dateKey("2026-06-09T14:30:00Z")).toBe("2026-06-09")
    expect(dateKey("2026-01-01T00:00:00Z")).toBe("2026-01-01")
  })

  it("returns empty string for invalid dates", () => {
    expect(dateKey("invalid")).toBe("")
    expect(dateKey("")).toBe("")
  })
})

describe("todayKey", () => {
  it("returns today as YYYY-MM-DD", () => {
    const key = todayKey()
    expect(key).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    const today = new Date().toISOString().slice(0, 10)
    expect(key).toBe(today)
  })
})
