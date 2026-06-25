import { test, expect } from "@playwright/test"

/**
 * Targets 管理页 E2E 测试 — 全 mock API
 */

async function loginByToken(page: any) {
  await page.goto("/")
  await page.evaluate(() =>
    localStorage.setItem("news_sentry_token", "e2e-test-token")
  )
  await page.reload()
}

// fetchAdminTargets(true) → GET /api/v1/admin/targets?include_archived=true
// 返回 { targets: [...] }，字段名 target_id
const mockTargetsResponse = {
  targets: [
    {
      target_id: "it-news",
      display_name: "意大利新闻",
      primary_language: "it",
      enabled: true,
      archived: false,
    },
    {
      target_id: "us-politics",
      display_name: "美国政治",
      primary_language: "en",
      enabled: true,
      archived: false,
    },
    {
      target_id: "jp-tech",
      display_name: "日本科技",
      primary_language: "ja",
      enabled: false,
      archived: true,
    },
  ],
}

test.describe("目标工作台", () => {
  test.beforeEach(async ({ page }) => {
    // Mock targets API
    await page.route("**/api/v1/admin/targets**", async (route) => {
      const method = route.request().method()
      if (method === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(mockTargetsResponse),
        })
      }
      if (method === "POST") {
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            target_id: "new-target",
            display_name: "新目标",
          }),
        })
      }
      if (method === "PATCH") {
        return route.fulfill({ status: 200, body: "{}" })
      }
      return route.continue()
    })

    await loginByToken(page)
    await page.goto("/")
    // 点击侧栏进入 targets 页（避免 strict mode）
    await page.getByText("目标工作台").first().click()
  })

  test("渲染 targets 列表", async ({ page }) => {
    await expect(page.getByText("意大利新闻")).toBeVisible()
    await expect(page.getByText("美国政治")).toBeVisible()
    await expect(page.getByText("日本科技")).toBeVisible()
  })

  test("搜索过滤 targets", async ({ page }) => {
    const searchInput = page.getByPlaceholder(/搜索/)
    await searchInput.fill("意大利")
    await expect(page.getByText("意大利新闻")).toBeVisible()
    await expect(page.getByText("美国政治")).not.toBeVisible()
    await expect(page.getByText("日本科技")).not.toBeVisible()
  })

  test("创建对话框 — 打开和关闭", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /新建/ })
    await createBtn.click()
    // 对话框标题
    await expect(page.getByText("创建监控目标")).toBeVisible()
    // 关闭 — Esc
    await page.keyboard.press("Escape")
    await expect(page.getByText("创建监控目标")).not.toBeVisible()
  })

  test("创建表单 — 空值时禁用提交", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /新建/ })
    await createBtn.click()
    // dialog 内的提交按钮应被禁用
    const confirmBtn = page.getByRole("button", { name: /创建/ })
    await expect(confirmBtn).toBeDisabled()
  })

  test("成功创建 target", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /新建/ })
    await createBtn.click()

    // 对话框已打开
    await expect(page.getByText("创建监控目标")).toBeVisible()

    // 填写表单 — 使用正确的 placeholder
    await page.getByPlaceholder("例如: de-economy").fill("new-target")
    await page.getByPlaceholder("例如: 德国经济").fill("新目标")

    const confirmBtn = page.getByRole("button", { name: "创建", exact: true })
    await confirmBtn.click()
    // 对话框关闭
    await expect(page.getByText("创建监控目标")).not.toBeVisible({ timeout: 3000 })
  })
})
