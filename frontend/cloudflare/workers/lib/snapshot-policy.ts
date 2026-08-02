import { sanitizeExternalUrlList, validateExternalUrl } from "./external-url.ts";
import { isPublishedTimestampSafe } from "./timestamp-policy.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sanitizeSnapshotItem(value: unknown, nowMs: number): Record<string, unknown> | null {
  if (!isRecord(value) || !isPublishedTimestampSafe(value.publishedAt, nowMs)) return null;
  const item = { ...value };
  if (item.originalUrl !== null && item.originalUrl !== undefined) {
    const originalUrl = validateExternalUrl(item.originalUrl);
    item.originalUrl = originalUrl.ok ? originalUrl.normalizedUrl : null;
  }
  if (Array.isArray(item.imageUrls)) {
    item.imageUrls = sanitizeExternalUrlList(item.imageUrls);
  }
  return item;
}

function sanitizeSnapshotFeed(value: unknown, nowMs: number): unknown {
  if (!isRecord(value) || !Array.isArray(value.items)) return value;
  const items = value.items.flatMap((item) => {
    const sanitized = sanitizeSnapshotItem(item, nowMs);
    return sanitized ? [sanitized] : [];
  });
  return {
    ...value,
    items,
    latestCursor: isRecord(items[0]) && typeof items[0].id === "string" ? items[0].id : null,
    nextCursor:
      typeof value.nextCursor === "string" && items.some((item) => item.id === value.nextCursor)
        ? value.nextCursor
        : null,
  };
}

/** Protect reads from snapshots generated before current ingest policies existed. */
export function sanitizePublicSnapshotPayload(payload: unknown, nowMs = Date.now()): unknown {
  if (!isRecord(payload)) return payload;
  if (Array.isArray(payload.items)) return sanitizeSnapshotFeed(payload, nowMs);
  if (isRecord(payload.news) && Array.isArray(payload.news.items)) {
    return { ...payload, news: sanitizeSnapshotFeed(payload.news, nowMs) };
  }
  return payload;
}
