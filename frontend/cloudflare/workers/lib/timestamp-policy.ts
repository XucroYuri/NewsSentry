export const COLLECTED_AT_FUTURE_TOLERANCE_MS = 5 * 60_000;
export const PUBLISHED_AT_FUTURE_TOLERANCE_MS = 24 * 60 * 60_000;

export type TimestampPolicyReason =
  | "invalid_collected_at"
  | "invalid_published_at"
  | "future_collected_at"
  | "future_published_at";

export type TimestampPolicyResult =
  | {
      ok: true;
      collectedAt: string;
      publishedAt: string;
    }
  | {
      ok: false;
      reason: TimestampPolicyReason;
    };

function parseTimestamp(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isPublishedTimestampSafe(value: unknown, nowMs = Date.now()): boolean {
  if (typeof value !== "string" || !value.trim()) return false;
  const publishedMs = parseTimestamp(value);
  return publishedMs !== null && publishedMs <= nowMs + PUBLISHED_AT_FUTURE_TOLERANCE_MS;
}

/** Assess timestamps at the ingest boundary using an injected clock for tests. */
export function assessEventTimestamps(
  collectedAtValue: unknown,
  publishedAtValue: unknown,
  nowMs = Date.now(),
): TimestampPolicyResult {
  if (typeof collectedAtValue !== "string" || !collectedAtValue.trim()) {
    return { ok: false, reason: "invalid_collected_at" };
  }
  const collectedMs = parseTimestamp(collectedAtValue);
  if (collectedMs === null) return { ok: false, reason: "invalid_collected_at" };
  if (collectedMs > nowMs + COLLECTED_AT_FUTURE_TOLERANCE_MS) {
    return { ok: false, reason: "future_collected_at" };
  }

  const publishedRaw =
    typeof publishedAtValue === "string" && publishedAtValue.trim()
      ? publishedAtValue
      : collectedAtValue;
  const publishedMs = parseTimestamp(publishedRaw);
  if (publishedMs === null) return { ok: false, reason: "invalid_published_at" };
  if (publishedMs > nowMs + PUBLISHED_AT_FUTURE_TOLERANCE_MS) {
    return { ok: false, reason: "future_published_at" };
  }

  return {
    ok: true,
    collectedAt: new Date(collectedMs).toISOString(),
    publishedAt: new Date(publishedMs).toISOString(),
  };
}
