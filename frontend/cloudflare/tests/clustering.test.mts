import assert from "node:assert/strict";
import { test } from "node:test";
import { assignClusters } from "../workers/lib/collect/clustering.ts";
import type { CollectedEvent } from "../workers/lib/collect/collected-event.ts";

/** 构造一个最小可用 CollectedEvent；classification 供 token/term 聚类。 */
function makeEvent(id: string, sourceId: string, title: string, classification: Record<string, unknown>): CollectedEvent {
  return {
    id,
    run_id: "run-1",
    source_id: sourceId,
    url: `https://ex.com/${id}`,
    title_original: title,
    content_original: "",
    language: "it",
    published_at: "2024-01-01T00:00:00+00:00",
    collected_at: "2024-01-01T00:00:00+00:00",
    pipeline_stage: "collected",
    metadata: { classification },
  };
}

test("assignClusters groups two similar events into the same cluster/story and isolates a different one", async () => {
  const a = makeEvent("a", "ansa", "US contractor killed in ukraine drone attack", { l0: "politics", l1: ["military"] });
  const b = makeEvent("b", "ap", "ukraine drone strike kills american contractor", { l0: "politics", l1: ["military"] });
  const c = makeEvent("c", "reuters", "Apple iPhone battery technology innovation", { l0: "tech", l1: ["consumer"] });

  const [aRes, bRes, cRes] = await assignClusters([a, b, c], "it");

  const ca = aRes.metadata["clustering"] as Record<string, unknown>;
  const cb = bRes.metadata["clustering"] as Record<string, unknown>;
  const cc = cRes.metadata["clustering"] as Record<string, unknown>;

  // a 与 b 同一 cluster / story，c 不同。
  assert.equal(aRes.metadata["clustering"], ca);
  assert.equal(ca["cluster_id"], cb["cluster_id"]);
  assert.equal(ca["story_id"], cb["story_id"]);
  assert.notEqual(ca["cluster_id"], cc["cluster_id"]);
  assert.notEqual(ca["story_id"], cc["story_id"]);

  // a/b 为 same_event；c 为 single_event。
  assert.equal(ca["cluster_type"], "same_event");
  assert.equal(ca["cluster_size"], 2);
  assert.equal(cc["cluster_type"], "single_event");
  assert.equal(cc["cluster_size"], 1);

  // confidence：合组 higher，单事件 55。
  assert.ok(((ca["confidence"] as number) > 55));
  assert.equal(cc["confidence"], 55);
});

test("assignClusters returns same array (in-place) and empty input returns empty", async () => {
  const events = [makeEvent("a", "ansa", "One", { l0: "politics", l1: ["military"] })];
  const out = await assignClusters(events, "it");
  assert.equal(out, events);
  assert.deepEqual(await assignClusters([], "it"), []);
});

test("cluster ids follow cluster-{target}-{12hex} shape", async () => {
  const a = makeEvent("a", "ansa", "US contractor killed in ukraine drone attack", { l0: "politics", l1: ["military"] });
  const [aRes] = await assignClusters([a], "it");
  const c = aRes.metadata["clustering"] as Record<string, unknown>;
  assert.match(String(c["cluster_id"]), /^cluster-it-[0-9a-f]{12}$/);
  assert.match(String(c["story_id"]), /^story-it-[0-9a-f]{12}$/);
  assert.ok(Array.isArray(c["matched_by"]));
  assert.ok(typeof c["reason"] === "string");
  assert.ok(typeof c["clustered_at"] === "string");
});
