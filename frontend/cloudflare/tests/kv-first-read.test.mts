import assert from "node:assert/strict";
import { test } from "node:test";

class FakeKV {
  map = new Map<string, string>();
  async put(k: string, v: string) { this.map.set(k, v); }
  async get(k: string) { return this.map.get(k) ?? null; }
}
const kv = new FakeKV();
const absentDb = { prepare: () => ({ bind: () => ({ first: async () => null }) }) };

import { kvWriteSnapshot } from "../workers/lib/kv-snapshot-store.ts";
import { readPublicSnapshotPayloadKvFirst } from "../workers/lib/public-read-snapshots.ts";

const key = "news:featured:v1:page_size=20";
const publishedAt = "2024-01-01T00:00:00.000Z";

test("KvFirst reads payload from KV when present", async () => {
  await kvWriteSnapshot(kv as any, key, { items: [{ id: "a", publishedAt }] });
  const payload = await readPublicSnapshotPayloadKvFirst(kv as any, absentDb as any, key);
  assert.deepEqual(payload, { items: [{ id: "a", publishedAt }], latestCursor: "a", nextCursor: null });
});

test("KvFirst falls back to D1 payload reader when KV misses", async () => {
  const missKey = "news:all:v1:page_size=20";
  const db = {
    prepare: () => ({
      bind: () => ({ first: async () => ({ payload_json: JSON.stringify({ items: [{ id: "b", publishedAt }] }) }) }),
    }),
  };
  const payload = await readPublicSnapshotPayloadKvFirst(kv as any, db as any, missKey);
  assert.deepEqual(payload, { items: [{ id: "b", publishedAt }], latestCursor: "b", nextCursor: null });
});
