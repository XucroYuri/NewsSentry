#!/usr/bin/env node
/**
 * Optional browser QA for the public News Sentry portal.
 *
 * Usage:
 *   NODE_PATH=/path/to/node_modules node tools/public_portal_browser_check.mjs \
 *     --base-url http://127.0.0.1:8765 --out /tmp/news-sentry-public-qa
 *
 * The script assumes a local/remote News Sentry server is already running. It
 * mocks public API responses in the browser so the layout is checked with
 * stable data while leaving the server unchanged.
 */

import { createRequire } from "node:module";
import fs from "node:fs";

const require = createRequire(import.meta.url);

function argValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

async function loadPlaywright() {
  try {
    return require("playwright");
  } catch {
    console.error("Playwright is required for browser QA. Install it or run with NODE_PATH pointing to a bundled node_modules.");
    process.exit(2);
  }
}

const baseUrl = argValue("--base-url", "http://127.0.0.1:8765").replace(/\/$/, "");
const outDir = argValue("--out", "/tmp/news-sentry-public-qa");
fs.mkdirSync(outDir, { recursive: true });

const now = Date.now();
const targets = [
  { target_id: "japan", display_name: "日本新闻监控", event_count: 88, source_count: 91, primary_language: "ja", status: "正常" },
  { target_id: "italy", display_name: "意大利新闻监控", event_count: 52, source_count: 163, primary_language: "it", status: "正常" },
];

const events = [
  {
    id: "evt-001",
    event_id: "evt-001",
    display_title: "意大利总理与欧盟领导人讨论对华贸易关系与市场准入",
    title_original: "Italia e UE discutono relazioni commerciali con la Cina",
    summary: "会谈聚焦降低关键行业壁垒，双方同意继续就电动汽车与清洁能源供应链保持沟通。",
    ai_reason: "该事件同时涉及欧盟政策、意大利产业准入和中国相关贸易议题，具备持续跟踪价值。",
    source_id: "ANSA.it",
    source_display_name: "ANSA.it",
    source_type: "rss",
    published_at: new Date(now).toISOString(),
    score: 92,
    news_value_score: 92,
    china_relevance: 81,
    sentiment_score: 0.12,
    flat_tags: ["国际关系", "贸易"],
    topic_tags: ["欧盟", "市场准入"],
    classification: { l0: "国际关系" },
    nlp_entities: [{ name: "欧盟委员会", entity_type: "ORG" }, { name: "意大利总理", entity_type: "PERSON" }],
    sentiment: "neutral",
    country: "意大利",
    language: "zh",
    pipeline_stage: "judged",
    url: "https://example.com/italy-eu-china",
  },
  {
    id: "evt-002",
    event_id: "evt-002",
    display_title: "意大利众议院通过 2026 年预算框架决议",
    summary: "政府强调财政纪律与增长并重，反对党批评紧缩措施将抑制经济。",
    source_id: "la-repubblica",
    source_display_name: "la Repubblica",
    source_type: "rss",
    published_at: new Date(now - 35 * 60 * 1000).toISOString(),
    score: 78,
    news_value_score: 78,
    china_relevance: 58,
    flat_tags: ["政治"],
    sentiment: "neutral",
    country: "意大利",
  },
];

const analysis = {
  target_id: "italy",
  target_name: "意大利新闻监控",
  summary: { total_events: 52, high_value_events: 9, avg_news_value_score: 71.2, avg_china_relevance: 58.1 },
  topic_trends: [{ topic: "欧盟贸易政策", trend_direction: "rising", hotness: 88, current_count: 21, prev_count: 9 }],
  sentiment_trend: [{ day: "06-07", positive: 4, neutral: 12, negative: 4 }],
  top_entities: [{ name: "欧盟委员会", entity_type: "ORG", mention_count: 18 }, { name: "意大利总理", entity_type: "PERSON", mention_count: 15 }],
  classification_distribution: [{ name: "国际关系", count: 35 }],
  source_distribution: [{ display_name: "ANSA.it", count: 31 }],
  active_chains: [],
};

function assertCheck(condition, message, details = {}) {
  if (condition) return;
  const err = new Error(message);
  err.details = details;
  throw err;
}

async function installMocks(page) {
  await page.route("**/api/v1/targets", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ targets }),
  }));
  await page.route("**/api/v1/events/feed?**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ total: events.length, groups: [{ date: new Date().toISOString().slice(0, 10), events }] }),
  }));
  await page.route("**/api/v1/public/targets/italy/analysis?**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(analysis),
  }));
  await page.route("**/api/v1/events/evt-001?**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(events[0]),
  }));
  await page.route("**/api/v1/events/evt-001/links?**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ links: [] }),
  }));
}

async function pageState(page) {
  return page.evaluate(() => ({
    adminVisible: [...document.querySelectorAll("#sidebar,#adminTopBar,#tabBar")]
      .some((el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)),
    publicTopVisible: !!document.querySelector(".public-top-bar")?.getClientRects().length,
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

async function checkCommon(page, label) {
  const state = await pageState(page);
  assertCheck(!state.adminVisible, `${label}: admin chrome should not be visible`, state);
  assertCheck(state.publicTopVisible, `${label}: public top bar should be visible`, state);
  assertCheck(!state.overflowX, `${label}: page should not overflow horizontally`, state);
}

async function checkMobileBottomNav(page, label, expectedHref) {
  const nav = await page.evaluate((href) => {
    const el = document.querySelector(".public-bottom-nav");
    const active = el?.querySelector("a.active");
    const rect = el?.getBoundingClientRect();
    const styles = el ? getComputedStyle(el) : null;
    return {
      visible: !!el?.getClientRects().length,
      position: styles?.position || "",
      top: rect?.top ?? -1,
      bottom: rect?.bottom ?? -1,
      height: rect?.height ?? 0,
      viewportHeight: window.innerHeight,
      activeHref: active?.getAttribute("href") || "",
      activeAriaCurrent: active?.getAttribute("aria-current") || "",
      expectedHref: href,
    };
  }, expectedHref);
  assertCheck(nav.visible, `${label}: mobile bottom nav should be visible`, nav);
  assertCheck(nav.position === "fixed", `${label}: mobile bottom nav should be fixed`, nav);
  assertCheck(nav.bottom <= nav.viewportHeight + 1, `${label}: mobile bottom nav should be pinned to viewport`, nav);
  assertCheck(nav.bottom - nav.height >= 0, `${label}: mobile bottom nav should not render below viewport`, nav);
  assertCheck(nav.activeHref === expectedHref, `${label}: mobile bottom nav should highlight the current route`, nav);
  assertCheck(nav.activeAriaCurrent === "page", `${label}: mobile bottom nav should expose aria-current`, nav);
}

async function runScenario(page, { label, hash, viewport, waitFor, screenshot, verify }) {
  await page.setViewportSize(viewport);
  await page.goto(`${baseUrl}/${hash}`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector(waitFor, { timeout: 10000 });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${outDir}/${screenshot}`, fullPage: true });
  await checkCommon(page, label);
  if (verify) await verify(page);
}

const { chromium } = await loadPlaywright();
let browser;
try {
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true });
  } catch {
    browser = await chromium.launch({ headless: true });
  }

  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  await installMocks(page);

  await runScenario(page, {
    label: "home desktop",
    hash: "#/news/feed",
    viewport: { width: 1440, height: 900 },
    waitFor: ".public-home-front",
    screenshot: "qa-home-desktop.png",
    verify: async (p) => {
      const nav = await p.evaluate(() => ({
        active: document.querySelector("#publicTopNav a.active")?.dataset?.publicNav,
        ariaCurrent: document.querySelector("#publicTopNav a.active")?.getAttribute("aria-current"),
        targetHref: document.querySelector('#publicTopNav [data-public-nav="target"]')?.getAttribute("href"),
      }));
      assertCheck(nav.active === "home", "home desktop: top nav should highlight channel", nav);
      assertCheck(nav.ariaCurrent === "page", "home desktop: top nav should expose aria-current", nav);
      assertCheck(nav.targetHref === "#/news/target/japan", "home desktop: top nav should point to most active target", nav);
    },
  });

  await runScenario(page, {
    label: "home mobile",
    hash: "#/news/feed",
    viewport: { width: 390, height: 844 },
    waitFor: ".public-home-front",
    screenshot: "qa-home-mobile.png",
    verify: async (p) => {
      const mobile = await p.evaluate(() => ({
        frontVisible: !!document.querySelector(".public-home-front")?.getClientRects().length,
      }));
      await checkMobileBottomNav(p, "home mobile", "#/news/feed");
      assertCheck(mobile.frontVisible, "home mobile: front page should render", mobile);
    },
  });

  await runScenario(page, {
    label: "italy deep link",
    hash: "#/news/target/italy",
    viewport: { width: 1440, height: 900 },
    waitFor: ".public-monitor-brief",
    screenshot: "qa-target-italy-desktop.png",
    verify: async (p) => {
      const nav = await p.evaluate(() => ({
        active: document.querySelector("#publicTopNav a.active")?.dataset?.publicNav,
        ariaCurrent: document.querySelector("#publicTopNav a.active")?.getAttribute("aria-current"),
        targetText: document.querySelector('#publicTopNav [data-public-nav="target"]')?.textContent?.trim(),
        targetHref: document.querySelector('#publicTopNav [data-public-nav="target"]')?.getAttribute("href"),
        priority: !!document.querySelector(".public-event-priority"),
      }));
      assertCheck(nav.active === "target", "italy deep link: top nav should highlight target", nav);
      assertCheck(nav.ariaCurrent === "page", "italy deep link: top nav should expose aria-current", nav);
      assertCheck(nav.targetText === "意大利" && nav.targetHref === "#/news/target/italy", "italy deep link: top nav should respect URL target", nav);
      assertCheck(nav.priority, "italy deep link: public feed should show event priority", nav);
    },
  });

  await runScenario(page, {
    label: "italy mobile",
    hash: "#/news/target/italy",
    viewport: { width: 390, height: 844 },
    waitFor: ".public-event-row",
    screenshot: "qa-target-italy-mobile.png",
    verify: async (p) => {
      const feed = await p.evaluate(() => ({
        hasTimeline: !!document.querySelector(".public-event-row"),
        hasFilters: !!document.querySelector(".feed-channel-bar"),
        hasSummary: !!document.querySelector(".public-monitor-brief"),
        firstEventTop: Math.round(document.querySelector(".public-event-row")?.getBoundingClientRect().top ?? 9999),
        firstTitleVisible: document.querySelector(".public-event-row .feed-item-title")?.getBoundingClientRect().top < window.innerHeight,
        toolbarVisible: !!document.querySelector(".feed-toolbar")?.getClientRects().length,
      }));
      await checkMobileBottomNav(p, "italy mobile", "#/news/target/italy");
      assertCheck(feed.hasTimeline && feed.hasFilters && feed.hasSummary, "italy mobile: target feed should include timeline, filters and summary", feed);
      assertCheck(feed.toolbarVisible && feed.firstTitleVisible && feed.firstEventTop < 844, "italy mobile: first story should start within the first viewport", feed);
    },
  });

  await runScenario(page, {
    label: "analysis desktop",
    hash: "#/news/target/italy/analysis",
    viewport: { width: 1440, height: 900 },
    waitFor: ".public-analysis-grid",
    screenshot: "qa-analysis-desktop.png",
    verify: async (p) => {
      const analysisPage = await p.evaluate(() => ({
        hasBrief: !!document.querySelector(".public-analysis-brief"),
        hasGrid: !!document.querySelector(".public-analysis-grid"),
        bottomVisible: !!document.querySelector(".public-bottom-nav")?.getClientRects().length,
        targetNavActive: document.querySelector("#publicTopNav a.active")?.dataset?.publicNav,
      }));
      assertCheck(analysisPage.hasBrief && analysisPage.hasGrid, "analysis desktop: brief and analysis grid should render", analysisPage);
      assertCheck(!analysisPage.bottomVisible, "analysis desktop: mobile bottom nav should not be visible", analysisPage);
      assertCheck(analysisPage.targetNavActive === "analysis", "analysis desktop: top nav should highlight analysis", analysisPage);
    },
  });

  await runScenario(page, {
    label: "analysis entities mobile",
    hash: "#/news/target/italy/analysis/entities",
    viewport: { width: 390, height: 844 },
    waitFor: "#entities",
    screenshot: "qa-analysis-entities-mobile.png",
    verify: async (p) => {
      const result = await p.evaluate(() => {
        const rect = document.querySelector("#entities")?.getBoundingClientRect();
        return {
          hash: window.location.hash,
          entityTop: rect?.top ?? -1,
          navHref: document.querySelector('.public-bottom-nav a[href="#/news/target/italy/analysis/entities"]')?.getAttribute("href"),
        };
      });
      await checkMobileBottomNav(p, "analysis entities mobile", "#/news/target/italy/analysis/entities");
      assertCheck(result.hash === "#/news/target/italy/analysis/entities", "analysis entities mobile: route should be section-aware", result);
      assertCheck(result.entityTop >= 0 && result.entityTop <= 844, "analysis entities mobile: entities section should be in viewport", result);
      assertCheck(result.navHref === "#/news/target/italy/analysis/entities", "analysis entities mobile: bottom nav should link to entities route", result);
    },
  });

  await runScenario(page, {
    label: "article mobile",
    hash: "#/news/target/italy/events/evt-001",
    viewport: { width: 390, height: 844 },
    waitFor: ".public-article-breadcrumb",
    screenshot: "qa-article-mobile.png",
    verify: async (p) => {
      const article = await p.evaluate(() => ({
        context: !!document.querySelector(".public-article-context"),
        breadcrumb: !!document.querySelector(".public-article-breadcrumb"),
      }));
      await checkMobileBottomNav(p, "article mobile", "#/news/target/italy");
      assertCheck(article.context && article.breadcrumb, "article mobile: article context and breadcrumb should render", article);
    },
  });

  assertCheck(!errors.length, "browser console/page errors should be empty", { errors });
  console.log(JSON.stringify({ ok: true, baseUrl, outDir }, null, 2));
} catch (err) {
  console.error(JSON.stringify({
    ok: false,
    message: err.message,
    details: err.details || null,
    baseUrl,
    outDir,
  }, null, 2));
  process.exit(1);
} finally {
  if (browser) await browser.close();
}
