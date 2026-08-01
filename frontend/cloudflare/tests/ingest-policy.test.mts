import assert from "node:assert/strict";
import test from "node:test";

import {
  sanitizeExternalUrlList,
  validateExternalUrl,
} from "../workers/lib/external-url.ts";
import { rowToPublicNewsItem } from "../workers/lib/public-news-query.ts";
import { sanitizePublicSnapshotPayload } from "../workers/lib/snapshot-policy.ts";
import {
  assessEventTimestamps,
  isPublishedTimestampSafe,
} from "../workers/lib/timestamp-policy.ts";

test("external URL policy accepts only uncredentialed HTTP(S)", () => {
  assert.deepEqual(validateExternalUrl("https://example.com/news?id=1"), {
    ok: true,
    normalizedUrl: "https://example.com/news?id=1",
  });
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,hello",
    "file:///etc/passwd",
    "https://user:pass@example.com/news",
    " https://example.com/news",
    "https:\\example.com\\news",
    "https://example.com/\u0000news",
  ]) {
    assert.equal(validateExternalUrl(value).ok, false, value);
  }
});

test("live public rows never expose unsafe image URL schemes", () => {
  assert.deepEqual(
    sanitizeExternalUrlList([
      "https://images.example.com/a.jpg",
      "javascript:alert(1)",
      "data:image/svg+xml,unsafe",
      "https://user:pass@example.com/private.jpg",
    ]),
    ["https://images.example.com/a.jpg"],
  );

  const item = rowToPublicNewsItem({
    event_id: "event-1",
    target_id: "global",
    target_label: "Global",
    source_id: "source-1",
    source_name: "Source",
    source_type: "rss",
    published_at: "2026-08-01T00:00:00Z",
    title: "Safe title",
    original_title: null,
    summary: null,
    recommendation_reason: null,
    full_content: null,
    original_url: "https://example.com/article",
    detail_url: "/public-app/news/event-1",
    image_urls: JSON.stringify([
      "https://images.example.com/a.jpg",
      "javascript:alert(1)",
    ]),
    tags: "[]",
    issue_tags: "[]",
    related_tags: "[]",
    region_tags: "[]",
    entities: "[]",
    related_count: 0,
    discussion_count: 0,
    value_label: "normal",
    value_score: 50,
    breaking_score: null,
    breaking_label: null,
    breaking_reason: null,
    breaking_confidence: null,
    breaking_dimensions: null,
    target_timezone: "UTC",
    published_at_local: null,
    available_locales: "[]",
    china_relevance_label: "unknown",
    credibility_label: null,
  });

  assert.deepEqual(item.imageUrls, ["https://images.example.com/a.jpg"]);
});

test("timestamp policy quarantines invalid and future timestamps", () => {
  const now = Date.parse("2026-08-01T00:00:00.000Z");
  assert.equal(
    assessEventTimestamps("2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z", now).ok,
    true,
  );
  assert.deepEqual(
    assessEventTimestamps("2026-08-01T00:06:00Z", undefined, now),
    { ok: false, reason: "future_collected_at" },
  );
  assert.deepEqual(
    assessEventTimestamps("2026-08-01T00:00:00Z", "2028-01-01T00:00:00Z", now),
    { ok: false, reason: "future_published_at" },
  );
  assert.deepEqual(assessEventTimestamps("not-a-date", undefined, now), {
    ok: false,
    reason: "invalid_collected_at",
  });
  assert.equal(isPublishedTimestampSafe("2026-08-01T23:59:59Z", now), true);
  assert.equal(isPublishedTimestampSafe("2026-08-02T00:00:01Z", now), false);
});

test("legacy snapshot reads remove future items and unsafe external URLs", () => {
  const now = Date.parse("2026-08-01T00:00:00.000Z");
  const payload = sanitizePublicSnapshotPayload(
    {
      items: [
        {
          id: "safe",
          publishedAt: "2026-08-01T00:00:00Z",
          originalUrl: "javascript:alert(1)",
          imageUrls: ["https://images.example.com/a.jpg", "data:text/html,unsafe"],
        },
        {
          id: "future",
          publishedAt: "2028-01-01T00:00:00Z",
          originalUrl: "https://example.com/future",
          imageUrls: [],
        },
      ],
      latestCursor: "future",
      nextCursor: "future",
      total: 2,
    },
    now,
  ) as { items: Array<Record<string, unknown>>; latestCursor: string; nextCursor: string | null };

  assert.equal(payload.items.length, 1);
  assert.equal(payload.items[0].id, "safe");
  assert.equal(payload.items[0].originalUrl, null);
  assert.deepEqual(payload.items[0].imageUrls, ["https://images.example.com/a.jpg"]);
  assert.equal(payload.latestCursor, "safe");
  assert.equal(payload.nextCursor, null);
});
