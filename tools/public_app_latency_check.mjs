#!/usr/bin/env node
/**
 * Browser latency QA for the React public app.
 *
 * Usage:
 *   NODE_PATH=/path/to/node_modules node tools/public_app_latency_check.mjs \
 *     --base-url https://news-sentry.com --out /tmp/news-sentry-public-app-latency
 *
 * The script uses real public endpoints. It is intentionally read-only.
 */

import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)

function argValue(name, fallback) {
  const index = process.argv.indexOf(name)
  if (index === -1 || index + 1 >= process.argv.length) return fallback
  return process.argv[index + 1]
}

function intArg(name, fallback) {
  const value = Number.parseInt(argValue(name, String(fallback)), 10)
  return Number.isFinite(value) ? value : fallback
}

async function loadPlaywright() {
  try {
    return require("playwright")
  } catch {
    console.error(
      "Playwright is required. Install it or run with NODE_PATH pointing to a bundled node_modules.",
    )
    process.exit(2)
  }
}

const baseUrl = argValue("--base-url", "http://127.0.0.1:8765").replace(/\/$/, "")
const outDir = argValue("--out", "/tmp/news-sentry-public-app-latency")
const firstArticleThresholdMs = intArg("--first-article-ms", 5_000)
const warmFirstArticleThresholdMs = intArg("--warm-first-article-ms", 3_000)
const detailThresholdMs = intArg("--detail-ms", 1_500)
fs.mkdirSync(outDir, { recursive: true })

function assertCheck(condition, message, details = {}) {
  if (condition) return
  const error = new Error(message)
  error.details = details
  throw error
}

function compactUrl(value) {
  return value.replace(baseUrl, "")
}

function summarizeRequests(records) {
  return records.map((record) => ({
    atMs: record.atMs,
    url: compactUrl(record.url),
    status: record.status,
    cache: record.cache,
    elapsed: record.elapsed,
  }))
}

async function collectRun(browser, viewport, label, expectedFirstArticleMs) {
  const page = await browser.newPage({ viewport })
  const started = Date.now()
  const network = []
  const errors = []

  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`)
  })
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`))
  page.on("response", async (response) => {
    const url = response.url()
    if (!url.includes("/api/v1/") && !url.includes("/public-app/assets/")) return
    network.push({
      atMs: Date.now() - started,
      url,
      status: response.status(),
      cache: response.headers()["x-news-sentry-feed-cache"] || "",
      elapsed: response.headers()["x-news-sentry-feed-elapsed-ms"] || "",
    })
  })

  await page.goto(`${baseUrl}/public-app/`, { waitUntil: "domcontentloaded", timeout: 30_000 })
  const domContentLoadedMs = Date.now() - started
  await page.locator("article").first().waitFor({ state: "visible", timeout: 15_000 })
  const firstArticleMs = Date.now() - started
  const initialFeedRequests = network.filter((record) =>
    compactUrl(record.url).startsWith("/api/v1/public/news?featured=true&page_size=20"),
  )
  const firstArticleText = await page.locator("article").first().innerText()

  const bottomNav = await page.evaluate(() => {
    const nav = document.querySelector('nav[aria-label="移动端公共频道"]')
    const rect = nav?.getBoundingClientRect()
    const style = nav ? getComputedStyle(nav) : null
    return {
      present: Boolean(nav),
      position: style?.position || "",
      bottom: rect?.bottom ?? null,
      viewportHeight: window.innerHeight,
    }
  })

  const detailLink = page.locator('article a[href*="#/events/"]').first()
  const hasDetailLink = (await detailLink.count()) > 0
  let detailMs = null
  if (hasDetailLink) {
    const detailStarted = Date.now()
    await detailLink.click()
    await page.waitForFunction(
      () => window.location.hash.includes("/events/") && Boolean(document.querySelector("article h1")),
      null,
      { timeout: 15_000 },
    )
    detailMs = Date.now() - detailStarted
  }

  await page.screenshot({ path: path.join(outDir, `${label}.png`), fullPage: true })
  await page.close()

  const result = {
    label,
    viewport,
    domContentLoadedMs,
    firstArticleMs,
    detailMs,
    firstArticleText: firstArticleText.slice(0, 180),
    initialFeedRequestCount: initialFeedRequests.length,
    initialFeedRequests: summarizeRequests(initialFeedRequests),
    requestCount: network.length,
    requests: summarizeRequests(network),
    bottomNav,
    errors,
  }

  assertCheck(errors.length === 0, `${label}: browser errors detected`, result)
  assertCheck(firstArticleMs <= expectedFirstArticleMs, `${label}: first article too slow`, result)
  assertCheck(initialFeedRequests.length === 1, `${label}: initial feed should be requested once`, result)
  if (detailMs !== null) {
    assertCheck(detailMs <= detailThresholdMs, `${label}: detail main content too slow`, result)
  }
  if (viewport.width < 768) {
    assertCheck(bottomNav.present, `${label}: mobile bottom nav missing`, result)
    assertCheck(bottomNav.position === "fixed", `${label}: mobile bottom nav is not fixed`, result)
    assertCheck(
      typeof bottomNav.bottom === "number" && bottomNav.bottom <= bottomNav.viewportHeight + 1,
      `${label}: mobile bottom nav is not pinned to the viewport`,
      result,
    )
  }
  return result
}

const { chromium } = await loadPlaywright()
let browser
try {
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true })
  } catch {
    browser = await chromium.launch({ headless: true })
  }

  const results = []
  results.push(
    await collectRun(
      browser,
      { width: 1440, height: 900 },
      "desktop-cold",
      firstArticleThresholdMs,
    ),
  )
  results.push(
    await collectRun(
      browser,
      { width: 1440, height: 900 },
      "desktop-warm",
      warmFirstArticleThresholdMs,
    ),
  )
  results.push(
    await collectRun(browser, { width: 390, height: 844 }, "mobile-cold", firstArticleThresholdMs),
  )

  const output = {
    baseUrl,
    generatedAt: new Date().toISOString(),
    thresholds: {
      firstArticleMs: firstArticleThresholdMs,
      warmFirstArticleMs: warmFirstArticleThresholdMs,
      detailMs: detailThresholdMs,
    },
    results,
  }
  fs.writeFileSync(path.join(outDir, "latency-report.json"), JSON.stringify(output, null, 2))
  console.log(JSON.stringify(output, null, 2))
} finally {
  await browser?.close()
}
