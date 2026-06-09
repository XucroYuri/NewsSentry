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
  "feed-refresh",
  "feed-analysis-link",
].map((needle) => toolbarHtml.indexOf(needle));

assert.deepEqual(
  actionOrder.map((index) => index >= 0),
  [true, true, true],
  "public toolbar should render search, refresh and analysis controls",
);
assert.deepEqual(
  [...actionOrder].sort((a, b) => a - b),
  actionOrder,
  "public toolbar controls should keep the primary reading workflow order",
);
assert.equal(
  toolbarHtml.includes("feed-view-toggle"),
  false,
  "public toolbar should not expose the admin compact-view toggle",
);
assert.equal(
  renderFeedToolbarActions({ publicMode: false, targetId: "italy" }).includes("feed-analysis-link"),
  false,
  "admin feed toolbar should not render the public analysis link",
);

console.log("feed toolbar tests passed");
