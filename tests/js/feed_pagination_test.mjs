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

const {
  renderFeedCountText,
  renderFeedFooterHtml,
  mergeFeedGroups,
} = await import("../../src/news_sentry/static/pages/feed.js");

assert.equal(renderFeedCountText({ loadedCount: 100, totalCount: 2836 }), "已加载 100 / 共 2836 条");
assert.equal(renderFeedCountText({ loadedCount: 12, totalCount: 12 }), "12 条");
assert.equal(
  renderFeedCountText({ loadedCount: 8, loadedTotal: 100, totalCount: 2836, filtered: true }),
  "当前筛选 8 条 · 已加载 100 / 共 2836 条",
);

assert.match(
  renderFeedFooterHtml({ loadedCount: 100, totalCount: 2836, loadingMore: false }),
  /加载更多/,
);
assert.match(
  renderFeedFooterHtml({ loadedCount: 100, totalCount: 2836, filtered: true }),
  /筛选仅作用于已加载/,
);
assert.equal(renderFeedFooterHtml({ loadedCount: 2836, totalCount: 2836 }), "");

const merged = mergeFeedGroups(
  [{ date: "2026-05-30", events: [{ event_id: "a" }] }],
  [
    { date: "2026-05-30", events: [{ event_id: "b" }] },
    { date: "2026-05-29", events: [{ event_id: "c" }] },
  ],
);
assert.deepEqual(merged, [
  { date: "2026-05-30", events: [{ event_id: "a" }, { event_id: "b" }] },
  { date: "2026-05-29", events: [{ event_id: "c" }] },
]);

console.log("feed pagination tests passed");
