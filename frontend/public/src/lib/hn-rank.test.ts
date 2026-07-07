import { describe, expect, it } from "vitest"

import {
  ageHoursFromPublished,
  computeHnScore,
  DEFAULT_GRAVITY,
  hnScoreForItem,
  pointsFromValueScore,
  rankByHnScore,
} from "@/lib/hn-rank"

describe("computeHnScore", () => {
  it("computes canonical HN values (parity with Python)", () => {
    // votes=100, age=1h: (99)^0.8 / (3)^1.8 ≈ 5.47
    expect(computeHnScore(100, 1.0)).toBeCloseTo(5.47, 1)
    // votes=10, age=10h: (9)^0.8 / (12)^1.8 ≈ 0.0662
    expect(computeHnScore(10, 10.0)).toBeCloseTo(0.0662, 3)
  })

  it("returns 0 when points <= 1", () => {
    expect(computeHnScore(0, 1)).toBe(0)
    expect(computeHnScore(1, 1)).toBe(0)
  })

  it("returns 0 for non-finite inputs", () => {
    expect(computeHnScore(NaN, 1)).toBe(0)
    expect(computeHnScore(10, Infinity)).toBe(0)
    expect(computeHnScore(10, 1, -1)).toBe(0)
    expect(computeHnScore(10, 1, 0)).toBe(0)
  })

  it("clamps negative age to 0", () => {
    expect(computeHnScore(10, -5)).toBe(computeHnScore(10, 0))
  })

  it("is monotonic in points", () => {
    const a = computeHnScore(5, 1)
    const b = computeHnScore(50, 1)
    expect(b).toBeGreaterThan(a)
  })

  it("decays with age", () => {
    const fresh = computeHnScore(20, 0.5)
    const stale = computeHnScore(20, 24)
    expect(fresh).toBeGreaterThan(stale)
  })
})

describe("pointsFromValueScore", () => {
  it("returns 0 for null/undefined", () => {
    expect(pointsFromValueScore(null)).toBe(0)
    expect(pointsFromValueScore(undefined)).toBe(0)
  })

  it("divides by default divisor 10", () => {
    expect(pointsFromValueScore(80)).toBe(8)
    expect(pointsFromValueScore(100)).toBe(10)
  })

  it("clamps negative to 0", () => {
    expect(pointsFromValueScore(-50)).toBe(0)
  })

  it("returns 0 for non-numeric", () => {
    expect(pointsFromValueScore("80" as unknown as number)).toBe(0)
    expect(pointsFromValueScore(NaN)).toBe(0)
    expect(pointsFromValueScore(Infinity)).toBe(0)
  })

  it("supports custom divisor", () => {
    expect(pointsFromValueScore(80, 20)).toBe(4)
  })

  it("falls back to default when divisor is 0 or negative", () => {
    expect(pointsFromValueScore(80, 0)).toBe(8)
    expect(pointsFromValueScore(80, -1)).toBe(8)
  })

  it("adds vote count (Phase 2 preview)", () => {
    expect(pointsFromValueScore(80, 10, 5)).toBe(13)
  })

  it("ignores negative vote count", () => {
    expect(pointsFromValueScore(80, 10, -3)).toBe(8)
  })
})

describe("ageHoursFromPublished", () => {
  it("returns 0 for null/undefined", () => {
    expect(ageHoursFromPublished(null)).toBe(0)
    expect(ageHoursFromPublished(undefined)).toBe(0)
  })

  it("returns 0 for invalid strings", () => {
    expect(ageHoursFromPublished("not-a-date")).toBe(0)
    expect(ageHoursFromPublished("")).toBe(0)
  })

  it("computes age in hours", () => {
    const now = new Date("2026-07-07T12:00:00Z")
    expect(ageHoursFromPublished("2026-07-07T10:00:00Z", now)).toBe(2)
  })

  it("returns 0 for future-dated input", () => {
    const now = new Date("2026-07-07T12:00:00Z")
    const future = new Date("2026-07-07T17:00:00Z")
    expect(ageHoursFromPublished(future, now)).toBe(0)
  })

  it("accepts Date object", () => {
    const now = new Date("2026-07-07T12:00:00Z")
    const published = new Date("2026-07-07T10:00:00Z")
    expect(ageHoursFromPublished(published, now)).toBe(2)
  })

  it("accepts date-only format", () => {
    const now = new Date("2026-07-07T12:00:00Z")
    // 2026-07-06 00:00 UTC → 36h ago
    expect(ageHoursFromPublished("2026-07-06", now)).toBeCloseTo(36)
  })

  it("uses current time when now is not provided", () => {
    const recentIso = new Date(Date.now() - 3_600_000).toISOString()
    const age = ageHoursFromPublished(recentIso)
    // Should be roughly 1 hour, allow some slack.
    expect(age).toBeGreaterThan(0.95)
    expect(age).toBeLessThan(1.1)
  })
})

describe("hnScoreForItem", () => {
  it("computes the trio from a public-news-like item", () => {
    const result = hnScoreForItem(
      { valueScore: 80, publishedAt: "2026-07-07T10:00:00Z" },
      { now: new Date("2026-07-07T12:00:00Z") },
    )
    expect(result.points).toBe(8)
    expect(result.ageHours).toBe(2)
    // (7)^0.8 / (4)^1.8
    const expected = Math.pow(7, 0.8) / Math.pow(4, DEFAULT_GRAVITY)
    expect(result.hnScore).toBeCloseTo(expected, 6)
  })

  it("returns 0 points and score when valueScore is missing", () => {
    const result = hnScoreForItem(
      { publishedAt: "2026-07-07T10:00:00Z" },
      { now: new Date("2026-07-07T12:00:00Z") },
    )
    expect(result.points).toBe(0)
    expect(result.hnScore).toBe(0)
  })
})

describe("rankByHnScore", () => {
  it("sorts by score descending", () => {
    const items = [
      { id: "a", score: 0.5 },
      { id: "b", score: 2 },
      { id: "c", score: 1 },
    ]
    const ranked = rankByHnScore(items, (x) => x.score)
    expect(ranked.map((x) => x.id)).toEqual(["b", "c", "a"])
  })

  it("preserves insertion order on ties", () => {
    const items = [
      { id: "first", score: 1 },
      { id: "second", score: 1 },
      { id: "third", score: 1 },
    ]
    const ranked = rankByHnScore(items, (x) => x.score)
    expect(ranked.map((x) => x.id)).toEqual(["first", "second", "third"])
  })

  it("handles empty input", () => {
    expect(rankByHnScore([], () => 0)).toEqual([])
  })

  it("does not mutate input", () => {
    const items = [
      { id: "a", score: 1 },
      { id: "b", score: 2 },
    ]
    const original = items.map((x) => ({ ...x }))
    rankByHnScore(items, (x) => x.score)
    expect(items).toEqual(original)
  })
})

describe("Python parity contract", () => {
  // Lock-step values verified against Python tests/unit/test_hn_ranking.py.
  // If this test changes, the Python test must change too.
  it.each([
    { points: 100, age: 1.0 },
    { points: 50, age: 5.0 },
    { points: 8, age: 2.0 },
    { points: 3, age: 24.0 },
    { points: 1, age: 0.0 },
  ])("matches Python for points=$points age=$age", ({ points, age }) => {
    const tsResult = computeHnScore(points, age)
    const expected = Math.pow(Math.max(points - 1, 0), 0.8) / Math.pow(age + 2, DEFAULT_GRAVITY)
    expect(tsResult).toBeCloseTo(expected, 9)
  })
})
