import { BREAKING_SCORE_VERSION } from "./public-news-query";

interface BreakingScoreRow {
  event_id: string;
  target_id: string;
  published_at: string;
  issue_tags: string | null;
  related_tags: string | null;
  breaking_raw_score: number | null;
  breaking_percentile: number | null;
  breaking_calibrated_score: number | null;
  breaking_score: number | null;
  breaking_label: string | null;
  breaking_confidence: number | null;
  breaking_score_version: string | null;
}

interface ScoreStats {
  scopeKey: string;
  windowDays: number;
  values: number[];
  mean: number;
  stddev: number;
  p50: number;
  p75: number;
  p90: number;
  p95: number;
}

function clampScore(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function parseJsonArray(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  if (values.length === 1) return values[0] ?? 0;
  const sorted = [...values].sort((left, right) => left - right);
  const rank = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(rank);
  const upper = Math.ceil(rank);
  if (lower === upper) return sorted[lower] ?? 0;
  const lowerValue = sorted[lower] ?? 0;
  const upperValue = sorted[upper] ?? lowerValue;
  return lowerValue + (upperValue - lowerValue) * (rank - lower);
}

function buildStats(scopeKey: string, windowDays: number, values: number[]): ScoreStats {
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
  const variance = values.length
    ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length
    : 0;
  return {
    scopeKey,
    windowDays,
    values,
    mean,
    stddev: Math.sqrt(variance),
    p50: percentile(values, 50),
    p75: percentile(values, 75),
    p90: percentile(values, 90),
    p95: percentile(values, 95),
  };
}

function percentileForScore(score: number, stats: ScoreStats): number {
  if (stats.values.length < 30) return score;
  const sorted = [...stats.values].sort((left, right) => left - right);
  let count = 0;
  for (const value of sorted) {
    if (value <= score) count += 1;
  }
  return Math.max(0, Math.min(100, (count / sorted.length) * 100));
}

function labelForScore(score: number, percentileValue: number, confidence: number): string {
  if (score >= 85 && percentileValue >= 95 && confidence >= 70) return "flash";
  if (score >= 72 && percentileValue >= 90 && confidence >= 60) return "breaking";
  if (score >= 52 || percentileValue >= 75) return "watch";
  return "timeline";
}

function addScore(scopes: Map<string, number[]>, scopeKey: string, score: number): void {
  const values = scopes.get(scopeKey) ?? [];
  values.push(score);
  scopes.set(scopeKey, values);
}

function scopeKeysForRow(row: BreakingScoreRow): string[] {
  return [
    "global",
    `target:${row.target_id}`,
    ...parseJsonArray(row.issue_tags).map((tag) => `issue:${tag}`),
    ...parseJsonArray(row.related_tags).map((tag) => `related:${tag}`),
  ];
}

function chooseStats(row: BreakingScoreRow, stats: Map<string, ScoreStats>): ScoreStats | null {
  const targetStats = stats.get(`target:${row.target_id}`);
  if (targetStats && targetStats.values.length >= 30) return targetStats;
  return stats.get("global") ?? null;
}

function scoreChanged(current: number | null, next: number, precision = 0): boolean {
  if (current === null || current === undefined) return true;
  const factor = 10 ** precision;
  return Math.round(Number(current) * factor) !== Math.round(next * factor);
}

export async function refreshBreakingScoreStats(
  db: D1Database,
  options: { windowDays?: number; limit?: number } = {},
): Promise<Record<string, unknown>> {
  const windowDays = Math.max(1, Math.trunc(options.windowDays ?? 30));
  const limit = Math.max(100, Math.trunc(options.limit ?? 5000));
  const result = await db
    .prepare(
      `SELECT event_id, target_id, published_at, issue_tags, related_tags,
              breaking_raw_score, breaking_percentile, breaking_calibrated_score,
              breaking_score, breaking_label, breaking_confidence, breaking_score_version
       FROM events
       WHERE pipeline_stage = 'drafts'
         AND COALESCE(breaking_raw_score, breaking_score) IS NOT NULL
         AND datetime(COALESCE(published_at, collected_at, created_at)) >= datetime('now', ?)
       ORDER BY published_at DESC
       LIMIT ?`,
    )
    .bind(`-${windowDays} days`, limit)
    .all<BreakingScoreRow>();
  const rows = result.results || [];
  if (rows.length === 0) {
    return { status: "empty", window_days: windowDays, updated_events: 0, stats_scopes: 0 };
  }

  const scopes = new Map<string, number[]>();
  for (const row of rows) {
    const score = clampScore(row.breaking_raw_score ?? row.breaking_score);
    for (const scopeKey of scopeKeysForRow(row)) {
      addScore(scopes, scopeKey, score);
    }
  }

  const stats = new Map<string, ScoreStats>();
  for (const [scopeKey, values] of scopes.entries()) {
    const next = buildStats(scopeKey, windowDays, values);
    stats.set(scopeKey, next);
    await db
      .prepare(
        `INSERT INTO breaking_score_stats (
           scope_key, window_days, mean_score, stddev_score,
           p50, p75, p90, p95, sample_count, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
         ON CONFLICT(scope_key) DO UPDATE SET
           window_days=excluded.window_days,
           mean_score=excluded.mean_score,
           stddev_score=excluded.stddev_score,
           p50=excluded.p50,
           p75=excluded.p75,
           p90=excluded.p90,
           p95=excluded.p95,
           sample_count=excluded.sample_count,
           updated_at=datetime('now')`,
      )
      .bind(
        next.scopeKey,
        next.windowDays,
        next.mean,
        next.stddev,
        next.p50,
        next.p75,
        next.p90,
        next.p95,
        next.values.length,
      )
      .run();
  }

  let updatedEvents = 0;
  for (const row of rows) {
    const rawScore = clampScore(row.breaking_raw_score ?? row.breaking_score);
    const selectedStats = chooseStats(row, stats);
    const percentileValue = selectedStats ? percentileForScore(rawScore, selectedStats) : rawScore;
    const calibratedScore = clampScore(rawScore * 0.7 + percentileValue * 0.3);
    const confidence = clampScore(row.breaking_confidence, 60);
    const label = labelForScore(calibratedScore, percentileValue, confidence);
    const roundedPercentile = Math.round(percentileValue * 100) / 100;
    if (
      !scoreChanged(row.breaking_raw_score, rawScore) &&
      !scoreChanged(row.breaking_percentile, roundedPercentile, 2) &&
      !scoreChanged(row.breaking_calibrated_score, calibratedScore) &&
      !scoreChanged(row.breaking_score, calibratedScore) &&
      row.breaking_label === label &&
      row.breaking_score_version === BREAKING_SCORE_VERSION
    ) {
      continue;
    }
    await db
      .prepare(
        `UPDATE events
         SET breaking_raw_score = ?,
             breaking_percentile = ?,
             breaking_calibrated_score = ?,
             breaking_score = ?,
             breaking_label = ?,
             breaking_score_version = ?
         WHERE event_id = ?`,
      )
      .bind(
        rawScore,
        roundedPercentile,
        calibratedScore,
        calibratedScore,
        label,
        BREAKING_SCORE_VERSION,
        row.event_id,
      )
      .run();
    updatedEvents += 1;
  }

  return {
    status: "ok",
    window_days: windowDays,
    scored_events: rows.length,
    updated_events: updatedEvents,
    stats_scopes: stats.size,
  };
}
