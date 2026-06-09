import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const eventsJs = readFileSync("src/news_sentry/static/pages/events.js", "utf8");
const publicCss = readFileSync("src/news_sentry/static/public.css", "utf8");

assert.match(
  eventsJs,
  /function renderPublicEventDetail/,
  "public event details should have a dedicated article renderer",
);

assert.match(
  eventsJs,
  /if \(publicMode\) \{[\s\S]*renderPublicEventDetail/,
  "public event routes should render the article view before admin detail markup",
);

assert.match(
  eventsJs,
  /renderPublicBottomNav\(targetId, "monitor"\)/,
  "public event article should preserve the mobile public navigation",
);

assert.match(
  eventsJs,
  /class="public-article-card"/,
  "public event detail should render as a news article card",
);

assert.match(
  eventsJs,
  /public-article-breadcrumb/,
  "public event detail should expose a reader-facing breadcrumb",
);

assert.match(
  eventsJs,
  /public-article-context/,
  "public event detail should show target and source context for readers",
);

assert.match(
  publicCss,
  /\.public-article-head h1[\s\S]*font-size: clamp/,
  "public article headlines should use an editorial headline scale",
);

assert.match(
  publicCss,
  /\.public-event-row\.is-lead/,
  "public feed should define a lead-story treatment",
);

assert.match(
  publicCss,
  /@media \(max-width: 820px\)[\s\S]*\.public-event-item[\s\S]*grid-template-columns: minmax\(0, 1fr\)/,
  "public mobile event cards should stack the score block instead of squeezing story text",
);

assert.match(
  publicCss,
  /@media \(max-width: 820px\)[\s\S]*\.public-article[\s\S]*calc\(86px \+ env\(safe-area-inset-bottom\)\)/,
  "public mobile article pages should reserve safe space for the fixed bottom navigation",
);

assert.match(
  publicCss,
  /@media \(max-width: 820px\)[\s\S]*\.public-article-head h1[\s\S]*font-size: 1\.72rem/,
  "public mobile article headlines should be compact enough for news reading",
);

assert.match(
  eventsJs,
  /class="public-article-deck"/,
  "public event detail should include a deck or explanatory summary area",
);

console.log("public event detail tests passed");
