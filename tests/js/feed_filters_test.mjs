import assert from "node:assert/strict";
import {
  CHANNELS,
  eventTerms,
  eventMatchesChannel,
  eventMatchesSearch,
  filterGroups,
  countEvents,
  channelsWithCounts,
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
      {
        event_id: "evt-economics",
        display_title: "Industrial production and market confidence rise",
        source_display_name: "ANSA",
        score: 64,
        flat_tags: ["economics"],
        classification: { l0: "economics" },
      },
      {
        event_id: "evt-society",
        display_title: "Healthcare and school services face local pressure",
        source_display_name: "ANSA",
        score: 58,
        flat_tags: ["health"],
        classification: { l0: "health" },
      },
      {
        event_id: "evt-energy",
        display_title: "Energy transition investment expands",
        source_display_name: "Il Sole 24 Ore",
        score: 70,
        flat_tags: ["environment_energy", "energy_transition"],
        classification: { l0: "environment_energy", l1: [{ code: "energy_transition" }] },
      },
      {
        event_id: "evt-security",
        display_title: "Security alert after supply chain attack",
        source_display_name: "Reuters",
        score: 68,
        flat_tags: ["security"],
        classification: { l0: "security" },
        story_id: "story-risk",
        clustering: { cluster_type: "same_event", cluster_size: 2 },
      },
      {
        event_id: "evt-war-title",
        display_title: "Gli Usa attaccano siti nucleari in Iran",
        source_display_name: "ANSA",
        score: 65,
        flat_tags: ["international"],
        classification: { l0: "international" },
      },
      {
        event_id: "evt-culture",
        display_title: "Vatican heritage exhibition opens in Rome",
        source_display_name: "ANSA",
        score: 55,
        flat_tags: ["vatican"],
        classification: { l0: "culture" },
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
assert.equal(eventMatchesChannel(groups[0].events[2], "industry"), true);
assert.equal(eventMatchesChannel(groups[0].events[3], "society"), true);
assert.equal(eventMatchesChannel(groups[0].events[4], "environment"), true);
assert.equal(eventMatchesChannel(groups[0].events[5], "risk"), true);
assert.equal(eventMatchesChannel(groups[0].events[5], "clusters"), true);
assert.equal(eventMatchesChannel(groups[0].events[6], "risk"), true);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "economy", l1: ["trade"] },
    flat_tags: [],
    score: 55,
  }, "industry"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "international-relations", l1: ["sanctions"] },
    display_title: "EU sanctions debate",
  }, "risk"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "tech", l1: ["ai"] },
    display_title: "AI policy for data centers",
  }, "tech"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "china-related", l1: ["china-italy-bilateral"] },
    china_relevance: 10,
  }, "china"),
  true,
);
assert.equal(eventMatchesSearch(groups[0].events[0], "compliance"), true);
assert.equal(eventMatchesSearch(groups[0].events[1], "reuters"), false);
assert.equal(eventMatchesSearch({ title: "Fallback Title", source: "Wire" }, "fallback"), true);
assert.equal(eventMatchesSearch({ title: "Fallback Title", source: "Wire" }, "wire"), true);
assert.equal(eventMatchesSearch({ id: "fallback-id-001" }, "fallback-id"), true);
assert.equal(eventMatchesSearch({ source_name: "Wire Desk" }, "wire desk"), true);
assert.deepEqual(eventTerms({ flat_tags: [0] }), ["0"]);
assert.deepEqual(eventTerms({ flat_tags: [{ code: 0 }] }), ["0"]);
assert.deepEqual(
  eventTerms({
    flat_tags: ["economics", "security", "china_related"],
    classification: { l0: "international" },
  }),
  ["economy", "public-safety", "china-related", "international-relations"],
);

const policyGroups = filterGroups(groups, { channelId: "policy", query: "" });
assert.equal(countEvents(policyGroups), 1);
assert.equal(policyGroups[0].events[0].event_id, "evt-policy");

const industryGroups = filterGroups(groups, { channelId: "industry", query: "" });
assert.equal(countEvents(industryGroups), 2);

const societyGroups = filterGroups(groups, { channelId: "society", query: "" });
assert.equal(countEvents(societyGroups), 1);

const clusterGroups = filterGroups(groups, { channelId: "clusters", query: "" });
assert.equal(countEvents(clusterGroups), 1);

const visibleChannels = channelsWithCounts(groups, { currentChannel: "featured" });
assert.deepEqual(
  visibleChannels.map((channel) => [channel.id, channel.count]),
  [
    ["all", 8],
    ["featured", 2],
    ["policy", 1],
    ["industry", 2],
    ["tech", 1],
    ["risk", 2],
    ["society", 1],
    ["environment", 1],
    ["international", 1],
    ["culture", 1],
    ["clusters", 1],
    ["china", 1],
  ],
);
assert.deepEqual(
  channelsWithCounts(groups, { currentChannel: "all", maxSecondaryChannels: 5 }).map((channel) => [channel.id, channel.count]),
  [
    ["all", 8],
    ["featured", 2],
    ["policy", 1],
    ["industry", 2],
    ["tech", 1],
    ["risk", 2],
    ["society", 1],
  ],
);
const currentEmptyChannels = channelsWithCounts(groups, { currentChannel: "missing-channel" });
assert.equal(currentEmptyChannels.some((channel) => channel.id === "missing-channel"), false);
const noTechGroups = [{ date: "2026-05-27", events: [groups[0].events[2]] }];
assert.deepEqual(
  channelsWithCounts(noTechGroups, { currentChannel: "all", maxSecondaryChannels: 5 }).map((channel) => channel.id),
  ["all", "featured", "industry"],
);
assert.deepEqual(
  channelsWithCounts(noTechGroups, { currentChannel: "tech", maxSecondaryChannels: 5 }).map((channel) => channel.id),
  ["all", "featured", "industry", "tech"],
);

const searchGroups = filterGroups(groups, { channelId: "all", query: "infrastructure" });
assert.equal(countEvents(searchGroups), 1);
assert.equal(searchGroups[0].events[0].event_id, "evt-tech");

const emptyGroups = filterGroups(groups, { channelId: "risk", query: "missing" });
assert.equal(countEvents(emptyGroups), 0);

console.log("feed_filters tests passed");
