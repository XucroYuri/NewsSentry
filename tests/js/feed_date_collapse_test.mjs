import assert from "node:assert/strict";

globalThis.window = {
  addEventListener: () => {},
  location: { origin: "http://localhost" },
};
globalThis.document = {
  createElement: () => ({
    textContent: "",
    get innerHTML() {
      return String(this.textContent)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    },
  }),
  body: {
    classList: {
      add: () => {},
      remove: () => {},
    },
  },
};
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: { onLine: true, language: "zh-CN" },
});
globalThis.localStorage = {};

const { renderTimeline } = await import("../../src/news_sentry/static/pages/feed.js");

const event = {
  event_id: "evt-1",
  source_id: "ansa",
  title_original: "Italy politics update",
  published_at: "2026-05-31T10:00:00Z",
  news_value_score: 72,
};

const expanded = renderTimeline("2026-05-31", [event], {}, { targetId: "italy", collapsedDates: new Set() });
assert.match(expanded, /<div class="feed-date-header" data-date="2026-05-31">/);
assert.match(expanded, /<button[^>]+class="feed-date-toggle"/);
assert.match(expanded, /aria-expanded="true"/);
assert.doesNotMatch(expanded, /feed-date-content feed-timeline" hidden/);

const collapsed = renderTimeline("2026-05-31", [event], {}, {
  targetId: "italy",
  collapsedDates: new Set(["2026-05-31"]),
});
assert.match(collapsed, /class="feed-date-group is-collapsed"/);
assert.match(collapsed, /aria-expanded="false"/);
assert.match(collapsed, /data-date="2026-05-31"/);
assert.match(collapsed, /<span class="feed-date-count">1 条<\/span>/);
assert.match(collapsed, /<div class="feed-date-content feed-timeline" hidden>/);

const translated = renderTimeline("2026-05-31", [{
  ...event,
  display_title: "意大利政治动态",
  original_title: "Italy politics update",
}], {}, { targetId: "italy", collapsedDates: new Set() });
assert.match(translated, /<a class="feed-item-title"[^>]*>意大利政治动态<\/a>/);
assert.match(translated, /<div class="feed-item-original-title">Italy politics update<\/div>/);

console.log("feed date collapse tests passed");
