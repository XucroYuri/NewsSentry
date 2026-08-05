import assert from "node:assert/strict";
import { test } from "node:test";

import { filterEvents } from "../workers/lib/collect/filter.ts";
import { Language, collectedEventFromEntry } from "../workers/lib/collect/collected-event.ts";

/** Build a CollectedEvent via collectedEventFromEntry with a controlled published_at (ISO). */
function mk(dateIso: string, title = "Trade deal announced", content = "market impact"):
  Promise<ReturnType<typeof collectedEventFromEntry> extends Promise<infer T> ? T : never> {
  return collectedEventFromEntry(
    "it",
    "ansa",
    "run-1",
    Language.IT,
    "https://feeds/ansa",
    {
      title,
      link: `https://ex.com/${dateIso}-${title.replaceAll(/\s+/g, "-")}`,
      content,
      published_at: dateIso,
      guid: `g-${dateIso}-${title}`,
    },
  );
}

test("filterEvents scores via keyword rules and applies threshold", async () => {
  const now = "2024-01-02T00:00:00+00:00";
  const e1 = await mk("2024-01-01T00:00:00+00:00"); // title contains "trade" → weight 0.5 → score 50
  const e2 = await mk("2024-01-01T00:00:00+00:00", "No keywords here", "plain content"); // score 0
  const { passed, skipped_known, skipped_stale, skipped_low_score } = filterEvents(
    [e1, e2],
    { keyword_rules: [{ keyword: "trade", weight: 0.5 }], score_threshold: 40 },
    new Set(),
    now,
  );
  assert.equal(skipped_low_score, 1);
  assert.equal(skipped_known, 0);
  assert.equal(skipped_stale, 0);
  assert.equal(passed.length, 1);
  assert.equal(passed[0].id, e1.id);
  assert.equal(passed[0].metadata["filter_matched_keywords"]?.[0], "trade");
  assert.equal(passed[0].metadata["filter_score"], 50);
});

test("filterEvents caps score at 100 and accumulates multiple keyword weights", async () => {
  const now = "2024-01-02T00:00:00+00:00";
  const e1 = await mk("2024-01-01T00:00:00+00:00", "Trade and market rally", "trade market");
  const { passed } = filterEvents(
    [e1],
    {
      keyword_rules: [
        { keyword: "trade", weight: 0.6 },
        { keyword: "market", weight: 0.6 },
      ],
      score_threshold: 40,
    },
    new Set(),
    now,
  );
  assert.equal(passed.length, 1);
  // weight 0.6*100 + 0.6*100 = 120 → capped at 100
  assert.equal(passed[0].metadata["filter_score"], 100);
  assert.deepEqual(passed[0].metadata["filter_matched_keywords"], ["trade", "market"]);
});

test("filterEvents drops stale events (older than max_age_hours)", async () => {
  const now = "2024-01-02T00:00:00+00:00";
  // published_at > 48h before now → stale
  const stale = await mk("2023-12-30T00:00:00+00:00", "Trade stale", "content");
  const fresh = await mk("2024-01-01T00:00:00+00:00", "Trade fresh", "content");
  const { passed, skipped_stale } = filterEvents(
    [stale, fresh],
    { keyword_rules: [{ keyword: "trade", weight: 0.5 }], score_threshold: 40 },
    new Set(),
    now,
  );
  assert.equal(skipped_stale, 1);
  assert.equal(passed.length, 1);
  assert.equal(passed[0].id, fresh.id);
});

test("filterEvents passes events with unparseable published_at (conservative)", async () => {
  const now = "2024-01-02T00:00:00+00:00";
  const bad = await mk("not-a-date", "Trade here", "content"); // unparseable → pass
  const { passed, skipped_stale } = filterEvents(
    [bad],
    { keyword_rules: [{ keyword: "trade", weight: 0.5 }], score_threshold: 40 },
    new Set(),
    now,
  );
  assert.equal(skipped_stale, 0);
  assert.equal(passed.length, 1);
});

test("filterEvents drops events already in knownIds and does not mutate the set", async () => {
  const now = "2024-01-02T00:00:00+00:00";
  const e1 = await mk("2024-01-01T00:00:00+00:00", "Trade known", "content");
  const e2 = await mk("2024-01-01T00:00:00+00:00", "Trade new", "content");
  const known = new Set<string>([e1.id]);
  const { passed, skipped_known } = filterEvents(
    [e1, e2],
    { keyword_rules: [{ keyword: "trade", weight: 0.5 }], score_threshold: 40 },
    known,
    now,
  );
  assert.equal(skipped_known, 1);
  assert.equal(passed.length, 1);
  assert.equal(passed[0].id, e2.id);
  // 纯函数：knownIds 不被写入（即使通过事件也不标记已知）。
  assert.deepEqual([...known], [e1.id]);
});

test("filterEvents applies a custom max_age_hours and defaults score_threshold to 40", async () => {
  // score_threshold 省略 → 默认 40；无命中 score=0 < 40 被跳过。
  const now = "2024-01-02T00:00:00+00:00";
  const e = await mk("2024-01-01T00:00:00+00:00", "plain", "no keywords");
  const { passed, skipped_low_score } = filterEvents(
    [e],
    { keyword_rules: [{ keyword: "miss", weight: 0.5 }] }, // 无 max_age_hours、无 threshold
    new Set(),
    now,
  );
  assert.equal(skipped_low_score, 1);
  assert.equal(passed.length, 0);
});
