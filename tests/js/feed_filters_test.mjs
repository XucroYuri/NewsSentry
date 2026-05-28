import assert from "node:assert/strict";
import {
  CHANNELS,
  eventTerms,
  eventMatchesChannel,
  eventMatchesSearch,
  filterGroups,
  countEvents,
} from "../../src/news_sentry/static/pages/feed_filters.js";

const groups = [
  {
    date: "2026-05-26",
    events: [
      {
        event_id: "evt-policy",
        display_title: "EU AI regulation talks continue",
        source_display_name: "Reuters",
        score: 82,
        recommendation: "review",
        flat_tags: ["policy", { code: "china-relations", confidence: 0.9 }],
        classification: { l0: "politics", l1: [{ code: "regulation" }] },
        summary: "Policy summary",
        ai_reason: "Important for compliance teams",
        china_relevance: 65,
      },
      {
        event_id: "evt-tech",
        display_title: "Open model infrastructure expands",
        source_display_name: "TechCrunch",
        score: 61,
        flat_tags: ["technology", "infrastructure"],
        classification: { l0: "technology" },
        summary: "Technology summary",
        ai_reason: "",
        china_relevance: 10,
      },
    ],
  },
];

assert.equal(CHANNELS[0].id, "all");
assert.equal(eventMatchesChannel(groups[0].events[0], "featured"), true);
assert.equal(eventMatchesChannel(groups[0].events[0], "policy"), true);
assert.equal(eventMatchesChannel(groups[0].events[0], "china"), true);
assert.equal(
  eventMatchesChannel({ title_original: "Pechino chiede un compromesso su Iran" }, "china"),
  true,
);
assert.equal(eventMatchesChannel(groups[0].events[1], "tech"), true);
assert.equal(eventMatchesChannel(groups[0].events[1], "risk"), false);
assert.equal(eventMatchesSearch(groups[0].events[0], "compliance"), true);
assert.equal(eventMatchesSearch(groups[0].events[1], "reuters"), false);
assert.equal(eventMatchesSearch({ title: "Fallback Title", source: "Wire" }, "fallback"), true);
assert.equal(eventMatchesSearch({ title: "Fallback Title", source: "Wire" }, "wire"), true);
assert.equal(eventMatchesSearch({ id: "fallback-id-001" }, "fallback-id"), true);
assert.equal(eventMatchesSearch({ source_name: "Wire Desk" }, "wire desk"), true);
assert.deepEqual(eventTerms({ flat_tags: [0] }), ["0"]);
assert.deepEqual(eventTerms({ flat_tags: [{ code: 0 }] }), ["0"]);

const policyGroups = filterGroups(groups, { channelId: "policy", query: "" });
assert.equal(countEvents(policyGroups), 1);
assert.equal(policyGroups[0].events[0].event_id, "evt-policy");

const searchGroups = filterGroups(groups, { channelId: "all", query: "infrastructure" });
assert.equal(countEvents(searchGroups), 1);
assert.equal(searchGroups[0].events[0].event_id, "evt-tech");

const emptyGroups = filterGroups(groups, { channelId: "risk", query: "missing" });
assert.equal(countEvents(emptyGroups), 0);

console.log("feed_filters tests passed");
