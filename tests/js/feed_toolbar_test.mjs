import assert from "node:assert/strict";

globalThis.window = {
  addEventListener: () => {},
  location: { origin: "http://localhost" },
};
globalThis.document = {
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

const { renderFeedToolbarActions } = await import("../../src/news_sentry/static/pages/feed.js");

const toolbarHtml = renderFeedToolbarActions({ publicMode: true, targetId: "italy" });
const actionOrder = [
  "feed-search",
  "feed-date-filter",
  "feed-view-toggle",
  "feed-refresh",
].map((needle) => toolbarHtml.indexOf(needle));

assert.deepEqual(
  actionOrder.map((index) => index >= 0),
  [true, true, true, true],
  "public toolbar should render search, date, view toggle and refresh controls",
);
assert.deepEqual(
  [...actionOrder].sort((a, b) => a - b),
  actionOrder,
  "public toolbar controls should be ordered by primary filtering workflow",
);
assert.equal(
  toolbarHtml.includes("feed-analysis-link"),
  false,
  "public toolbar should not link to deferred public analysis pages",
);
assert.equal(
  renderFeedToolbarActions({ publicMode: false, targetId: "italy" }).includes("feed-analysis-link"),
  false,
  "admin feed toolbar should not render deferred public analysis links",
);

console.log("feed toolbar tests passed");
