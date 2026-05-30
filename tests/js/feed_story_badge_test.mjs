import assert from "node:assert/strict";

globalThis.window = {
  addEventListener: () => {},
  location: { origin: "http://localhost" },
};
globalThis.document = {
  createElement: () => ({
    innerHTML: "",
    set textContent(value) {
      this.innerHTML = String(value)
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

const { storyBadge } = await import("../../src/news_sentry/static/pages/feed.js");

assert.match(
  storyBadge({
    story_id: "story-1",
    clustering: { cluster_type: "same_event" },
  }),
  /同一事件/,
);
assert.match(
  storyBadge({
    story_id: "story-2",
    clustering: { cluster_type: "storyline" },
  }),
  /故事线/,
);
assert.equal(
  storyBadge({
    story_id: "story-single",
    clustering: { cluster_type: "single_event" },
  }),
  "",
);
assert.equal(storyBadge({ clustering: { cluster_type: "same_event" } }), "");

console.log("feed story badge tests passed");
