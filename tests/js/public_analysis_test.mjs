import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

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

const analysisJs = readFileSync("src/news_sentry/static/pages/public_analysis.js", "utf8");
const publicCss = readFileSync("src/news_sentry/static/public.css", "utf8");

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

assert.match(
  analysisJs,
  /public-analysis-brief/,
  "public analysis should render a reader-facing brief before raw metrics",
);

assert.match(
  analysisJs,
  /public-analysis-brief-card/,
  "public analysis summary cards should carry status-specific visual tone classes",
);

assert.match(
  analysisJs,
  /tone: sampleTone/,
  "public analysis should derive a sample reliability tone from the event count",
);

assert.match(
  analysisJs,
  /态势简报/,
  "public analysis should use reader-facing brief language instead of backend analysis wording",
);

assert.match(
  analysisJs,
  /id="entities"/,
  "public analysis should expose an entities anchor for the mobile navigation",
);

assert.match(
  analysisJs,
  /focusAnalysisSection/,
  "public analysis should scroll to a requested reader section after rendering",
);

assert.match(
  analysisJs,
  /options\.focusSection/,
  "public analysis should accept a focusSection option from the public router",
);

assert.match(
  analysisJs,
  /bottomNavActiveForSection/,
  "public analysis should map focused sections to the correct bottom navigation state",
);

assert.match(
  analysisJs,
  /sectionId === "entities" \? "entities" : "trends"/,
  "public analysis entities route should highlight the entities tab instead of trends",
);

assert.match(
  publicCss,
  /\.public-analysis-brief[\s\S]*grid-template-columns: repeat\(4/,
  "public analysis brief should have a desktop editorial summary layout",
);

assert.match(
  publicCss,
  /\.public-analysis-brief-card\.strong::before/,
  "public analysis tone cards should expose a clear high-signal state marker",
);

console.log("public analysis tests passed");
