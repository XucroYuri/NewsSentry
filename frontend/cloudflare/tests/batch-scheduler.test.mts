import assert from "node:assert/strict";
import { test } from "node:test";
import { nextBatch } from "../workers/lib/collect/batch-scheduler.ts";

test("nextBatch selects a bounded slice from cursor then wraps", () => {
  const t = ["a", "b", "c", "d", "e"];
  const r1 = nextBatch(t, 0, 2);   // selects [a,b], cursor 2, not complete
  assert.deepEqual(r1.selected, ["a", "b"]);
  assert.equal(r1.next_cursor, 2);
  assert.equal(r1.complete_cycle, false);
  const r2 = nextBatch(t, 2, 2);   // [c,d]
  assert.deepEqual(r2.selected, ["c", "d"]);
  const r3 = nextBatch(t, 4, 2);   // wraps: [e,a], complete
  assert.deepEqual(r3.selected, ["e", "a"]);
  assert.equal(r3.complete_cycle, true);
});
test("nextBatch handles empty and batchSize 0", () => {
  assert.deepEqual(nextBatch([], 0, 8), { selected: [], next_cursor: 0, complete_cycle: true });
  assert.deepEqual(nextBatch(["x"], 0, 0), { selected: ['x'], next_cursor: 0, complete_cycle: true });
});
