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
  analysisHasData,
  distributionPercent,
  metricText,
  trendDirectionLabel,
} = await import("../../src/news_sentry/static/pages/public_analysis.js");

assert.equal(metricText(12), "12");
assert.equal(metricText(12.345), "12.35");
assert.equal(metricText(null), "—");
assert.equal(metricText(undefined), "—");

assert.equal(distributionPercent(5, 10), 50);
assert.equal(distributionPercent(0, 10), 0);
assert.equal(distributionPercent(5, 0), 0);

assert.equal(trendDirectionLabel("rising"), "上升");
assert.equal(trendDirectionLabel("falling"), "下降");
assert.equal(trendDirectionLabel("stable"), "稳定");
assert.equal(trendDirectionLabel("unknown"), "稳定");

assert.equal(analysisHasData({ summary: { total_events: 1 } }), true);
assert.equal(analysisHasData({ classification_distribution: [{ name: "politics", count: 1 }] }), true);
assert.equal(analysisHasData({ source_distribution: [] }), false);
assert.equal(analysisHasData(null), false);

console.log("public analysis tests passed");
