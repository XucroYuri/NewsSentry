/**
 * TypeScript port of `src/news_sentry/core/hn_ranking.py`.
 *
 * MUST produce byte-identical numeric output to the Python implementation.
 * The Python test suite (`tests/unit/test_hn_ranking.py::TestParityContract`)
 * documents the canonical values; this TS module mirrors the same formula.
 *
 * Reference: https://medium.com/hacker-news-ranking-algorithm-8d23a857dda4
 *
 * Formula:  score = (points - 1) ^ 0.8 / (age_hours + 2) ^ gravity
 *
 * Phase 1 (see docs/upgrades/hacker-news-style-upgrade-plan.md):
 *   - `points` derived from `valueScore / 10` (no votes yet).
 *   - Phase 2 will add anonymous vote_count on top.
 */

export const DEFAULT_GRAVITY = 1.8
export const DEFAULT_POINTS_DIVISOR = 10
export const MIN_POINTS_INPUT = 0

/**
 * Compute the canonical HN ranking score.
 *
 * Returns 0 for invalid inputs (NaN, Infinity, negative age) so items sink
 * rather than poisoning the ranking.
 */
export function computeHnScore(
  points: number,
  ageHours: number,
  gravity: number = DEFAULT_GRAVITY,
): number {
  if (!Number.isFinite(points) || !Number.isFinite(ageHours)) return 0
  if (!Number.isFinite(gravity) || gravity <= 0) return 0
  if (ageHours < 0) ageHours = 0

  const base = Math.max(points - 1, MIN_POINTS_INPUT)
  if (base === 0) return 0

  const numerator = Math.pow(base, 0.8)
  const denominator = Math.pow(ageHours + 2, gravity)
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator)) return 0
  if (denominator <= 0) return 0
  return numerator / denominator
}

/**
 * Derive a HN-style `points` value from `valueScore` (0-100).
 *
 * Phase 2 callers pass `voteCount` to add real anonymous votes.
 */
export function pointsFromValueScore(
  valueScore: number | null | undefined,
  divisor: number = DEFAULT_POINTS_DIVISOR,
  voteCount: number = 0,
): number {
  let score: number
  if (valueScore == null) {
    score = 0
  } else if (typeof valueScore !== "number" || !Number.isFinite(valueScore)) {
    score = 0
  } else if (valueScore < 0) {
    score = 0
  } else {
    score = valueScore
  }
  if (divisor <= 0 || !Number.isFinite(divisor)) divisor = DEFAULT_POINTS_DIVISOR
  if (!Number.isInteger(voteCount) || voteCount < 0) voteCount = 0
  return score / divisor + voteCount
}

/**
 * Compute age (in hours) between `publishedAt` and `now` (UTC).
 *
 * Returns 0 on parse failure or future-dated input.
 */
export function ageHoursFromPublished(
  publishedAt: string | Date | null | undefined,
  now: Date | null = null,
): number {
  if (publishedAt == null) return 0
  const published =
    publishedAt instanceof Date ? publishedAt : parseIsoDate(publishedAt)
  if (published == null) return 0
  const current = now ?? new Date()
  const publishedMs = published.getTime()
  const currentMs = current.getTime()
  if (!Number.isFinite(publishedMs) || !Number.isFinite(currentMs)) return 0
  const deltaMs = currentMs - publishedMs
  if (deltaMs < 0) return 0
  return deltaMs / 3_600_000
}

/**
 * Re-compute (hnScore, points, ageHours) for a public news item.
 *
 * Useful for client-side re-ranking when the server's snapshot is stale or
 * when merging live updates with cached items.
 */
export function hnScoreForItem(
  item: { valueScore?: number | null; publishedAt: string },
  options: { now?: Date | null; gravity?: number; voteCount?: number } = {},
): { hnScore: number; points: number; ageHours: number } {
  const points = pointsFromValueScore(item.valueScore, DEFAULT_POINTS_DIVISOR, options.voteCount ?? 0)
  const ageHours = ageHoursFromPublished(item.publishedAt, options.now ?? null)
  const hnScore = computeHnScore(points, ageHours, options.gravity ?? DEFAULT_GRAVITY)
  return { hnScore, points, ageHours }
}

/**
 * Stable-sort items by descending HN score.
 *
 * Ties preserve insertion order — callers can pre-sort by secondary keys
 * (e.g. `breakingScore`) before invoking this.
 */
export function rankByHnScore<T>(items: T[], scoreGetter: (item: T) => number): T[] {
  const decorated = items.map((item, idx) => ({ item, score: scoreGetter(item), idx }))
  decorated.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score
    return a.idx - b.idx
  })
  return decorated.map((entry) => entry.item)
}

// ── Internal helpers ────────────────────────────────────────────────────────

const ISO_REGEX = /^\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/

function parseIsoDate(value: string): Date | null {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!ISO_REGEX.test(trimmed)) {
    // Last-resort — Date.parse is lenient but may yield NaN.
    const fallback = new Date(trimmed)
    return Number.isNaN(fallback.getTime()) ? null : fallback
  }
  const normalised = trimmed.replace(/([+-]\d{2}):?(\d{2})$/, "$1:$2").replace(/Z$/, "Z")
  const parsed = new Date(normalised)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}
