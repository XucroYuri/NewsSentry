import { test, expect } from "@playwright/test"

/**
 * Events 和 Drafts 页面 E2E 测试 — 全 mock API
 */

async function loginByToken(page: any) {
  await page.goto("/")
  await page.evaluate(() =>
    localStorage.setItem("news_sentry_token", "e2e-test-token")
  )
  await page.reload()
}

const mockTargetsResponse = {
  targets: [
    {
      target_id: "it-news",
      display_name: "意大利新闻",
      primary_language: "it",
      enabled: true,
      archived: false,
    },
  ],
}

const mockEventsResponse = {
  total: 2,
  events: [
    {
      event_id: "ev-001",
      title_original: "意大利大选结果揭晓",
      source_id: "ansa",
      published_at: "2026-06-25T10:00:00Z",
      news_value_score: 85,
      classification_l0: "politics",
      sentiment: "neutral",
    },
    {
      event_id: "ev-002",
      title_original: "米兰时装周开幕",
      source_id: "ansa",
      published_at: "2026-06-24T14:00:00Z",
      news_value_score: 60,
      classification_l0: "culture",
      sentiment: "positive",
    },
  ],
  page: 1,
  page_size: 20,
}

const mockDraftsResponse = {
  total: 1,
  events: [
    {
      event_id: "ev-003",
      title_original: "意大利经济数据发布",
      source_id: "ilsole24ore",
      published_at: "2026-06-25T08:30:00Z",
      news_value_score: 75,
      classification_l0: "economy",
      sentiment: "neutral",
      stage: "drafts",
    },
  ],
  page: 1,
  page_size: 20,
}

const emptyResponse = { total: 0, events: [], page: 1, page_size: 20 }

test.describe("Events & Drafts 页面", () => {
  test.beforeEach(async ({ page }) => {
    await loginByToken(page)
  })

  test("Events 列表加载成功", async ({ page }) => {
    // Mock targets API — fetchAdminTargets(true) → GET /api/v1/admin/targets?include_archived=true
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockTargetsResponse),
        })
      }
      return route.continue()
    })

    // Mock events API — fetchEvents → GET /api/v1/events?...
    await page.route("**/api/v1/events*", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockEventsResponse),
      })
    })

    await page.goto("/")
    await page.getByText("新闻事件").first().click()

    await expect(page.getByText("意大利大选结果揭晓")).toBeVisible({ timeout: 5000 })
    await expect(page.getByText("米兰时装周开幕")).toBeVisible()
  })

  test("Events 空状态", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockTargetsResponse),
        })
      }
      return route.continue()
    })

    await page.route("**/api/v1/events*", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(emptyResponse),
      })
    })

    await page.goto("/")
    await page.getByText("新闻事件").first().click()

    const eventCards = page.getByText(/大选|时装周/)
    await expect(eventCards).toHaveCount(0)
  })

  test("Drafts 列表加载成功", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockTargetsResponse),
        })
      }
      return route.continue()
    })

    // Drafts page 同样调用 /api/v1/events (with stage=drafts)
    await page.route("**/api/v1/events*", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockDraftsResponse),
      })
    })

    await page.goto("/")
    await page.getByText("草稿审核").first().click()

    await expect(page.getByText("意大利经济数据发布")).toBeVisible({ timeout: 5000 })
  })

  test("Drafts 空状态", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockTargetsResponse),
        })
      }
      return route.continue()
    })

    await page.route("**/api/v1/events*", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(emptyResponse),
      })
    })

    await page.goto("/")
    await page.getByText("草稿审核").first().click()

    const draftCards = page.getByText(/经济数据/)
    await expect(draftCards).toHaveCount(0)
  })
})
