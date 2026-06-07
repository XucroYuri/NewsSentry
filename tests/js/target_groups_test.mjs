import assert from "node:assert/strict";

import {
  groupTargetsByKind,
  normalizeTargetKind,
  targetTopicLabel,
} from "../../src/news_sentry/static/pages/target_groups.js";

const targets = [
  { target_id: "italy", display_name: "意大利新闻监控", event_count: 10 },
  { target_id: "china-watch-en", display_name: "China Watch (English)", event_count: 20 },
  { target_id: "ai-safety", display_name: "AI Safety", monitoring_type: "topic", topic_label: "AI 安全" },
];

assert.equal(normalizeTargetKind(targets[0]), "country");
assert.equal(normalizeTargetKind(targets[1]), "topic");
assert.equal(targetTopicLabel(targets[1]), "涉中舆情");

const groups = groupTargetsByKind(targets);
assert.equal(groups[0].id, "topic");
assert.equal(groups[0].label, "专题监控目标");
assert.deepEqual(groups[0].targets.map((target) => target.target_id), ["china-watch-en", "ai-safety"]);
assert.equal(groups[1].id, "country");
assert.equal(groups[1].label, "国别监控目标");
assert.deepEqual(groups[1].targets.map((target) => target.target_id), ["italy"]);

console.log("target grouping tests passed");

