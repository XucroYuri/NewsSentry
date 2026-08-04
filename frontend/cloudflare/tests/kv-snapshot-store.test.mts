import assert from "node:assert/strict";
import { test } from "node:test";

// 轻量 KV 模拟：put/get 存内存 Map
class FakeKV {
  map = new Map<string, string>();
  async put(k: string, v: string) { this.map.set(k, v); }
  async get(k: string) { return this.map.get(k) ?? null; }
}
const kv = new FakeKV();

import {
  kvSnapshotKey,
  kvReadSnapshot,
  kvWriteSnapshot,
} from "../workers/lib/kv-snapshot-store.ts";

test("kvSnapshotKey prefixes and prefixes are deterministic", () => {
  assert.equal(kvSnapshotKey("news:featured:v1"), kvSnapshotKey("news:featured:v1"));
  assert.ok(kvSnapshotKey("news:featured:v1").startsWith("k:"));
});

test("kvWriteSnapshot then kvReadSnapshot round-trips an unknown payload", async () => {
  const payload = {
    foo: 1,
    items: [{ id: "n1", publishedAt: "2026-01-01T00:00:00.000Z" }],
    latestCursor: "n1",
    nextCursor: "n1",
  };
  await kvWriteSnapshot(kv as any, "news:featured:v1", payload);
  const got = await kvReadSnapshot(kv as any, "news:featured:v1");
  assert.deepEqual(got?.payload, payload);
  assert.ok(got?.etag);
});

test("kvReadSnapshot returns null on missing key", async () => {
  const got = await kvReadSnapshot(kv as any, "no-such-key");
  assert.equal(got, null);
});
