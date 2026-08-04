import assert from "node:assert/strict";
import { test } from "node:test";
class FakeKV {
  map = new Map<string, string>();
  async put(k: string, v: string) { this.map.set(k, v); }
  async get(k: string) { return this.map.get(k) ?? null; }
}
import { setSnapshotKv, kvSnapshotKey, kvReadSnapshot } from "../workers/lib/kv-snapshot-store.ts";
import { writeSnapshotAndMaybeKv } from "../workers/lib/public-read-snapshots.ts";

// NOTE: kvWriteSnapshot runs sanitizePublicSnapshotPayload on write, which
// filters feed items lacking a timeframe-safe publishedAt. Use a sanitizer-
// compatible feed so the KV read-back assertion holds.
//
// Sanitizer behavior for a feed `{ items: [{ id, publishedAt }] }`: the item is
// preserved and `latestCursor` is derived from `items[0].id` (here "x"), so the
// KV read-back payload equals the shape below.
const COMPATIBLE_FEED = {
  items: [{ id: "x", publishedAt: "2024-01-01T00:00:00.000Z" }],
};

test("writeSnapshotAndMaybeKv writes D1 and KV together", async () => {
  const kv = new FakeKV();
  setSnapshotKv(kv as any);
  let d1WriteCount = 0;
  const db = { prepare: () => ({ bind: () => ({ run: async () => { d1WriteCount++; } }) }) };
  await writeSnapshotAndMaybeKv(db as any, "news:featured:v1", COMPATIBLE_FEED, 1, null, new Date().toISOString());
  assert.equal(d1WriteCount, 1);
  const got = await kvReadSnapshot(kv as any, "news:featured:v1");
  // KV stores the sanitized payload; assert the sanitized shape (item preserved with publishedAt).
  assert.deepEqual(got?.payload, { items: [{ id: "x", publishedAt: "2024-01-01T00:00:00.000Z" }], latestCursor: "x", nextCursor: null });
});
