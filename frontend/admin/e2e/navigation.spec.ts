import { test, expect } from "@playwright/test"

/**
 * 导航和侧栏 E2E 测试 — 全 mock API
 *
 * 测试用例:
 * - 侧栏渲染所有导航项
 * - 点击导航项切换页面
 * - 侧栏折叠/展开
 * - 登出返回登录页
 */

async function loginByToken(page: any) {
  // 必须先加载页面才能访问 localStorage
  await page.goto("/")
  await page.evaluate(() =>
    localStorage.setItem("news_sentry_token", "e2e-test-token")
  )
  await page.reload()
}

const navLabels = [
  "管理总览",
  "新闻事件",
  "草稿审核",
  "目标工作台",
  "通知规则",
  "实体管理",
  "注解日志",
  "可观测性诊断",
  "用户管理",
]

test.describe("导航与侧栏", () => {
  test.beforeEach(async ({ page }) => {
    // Mock all common API endpoints
    await page.route("**/api/v1/admin/targets", async (route) => {
      if (route.request().method() === "GET") {
        const url = new URL(route.request().url())
        const withMeta = url.searchParams.get("with_meta")
        if (withMeta === "true") {
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([
              {
                id: "it-news",
                display_name: "意大利新闻",
                language: "it",
                enabled: true,
                archived: false,
              },
            ]),
          })
        }
        return route.fulfill({ status: 200, body: "[]" })
      }
      return route.continue()
    })

    // Mock events
    await page.route("**/api/v1/admin/events*", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ total: 0, events: [], page: 1, page_size: 20 }),
      })
    })

    await loginByToken(page)
    await page.goto("/")
  })

  test("侧栏渲染所有导航项", async ({ page }) => {
    for (const label of navLabels) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
    }
  })

  test("点击新闻事件切换到 EventsPage", async ({ page }) => {
    await page.getByText("新闻事件").click()
    // header 显示页面标题
    await expect(
      page.locator("header").getByText("新闻事件")
    ).toBeVisible()
  })

  test("点击草稿审核切换到 DraftsPage", async ({ page }) => {
    await page.getByText("草稿审核").click()
    await expect(
      page.locator("header").getByText("草稿审核")
    ).toBeVisible()
  })

  test("侧栏折叠/展开", async ({ page }) => {
    // 初始侧栏展开 — nav labels 可见
    await expect(page.getByText("新闻事件")).toBeVisible()
    // 点击收起按钮
    const toggleBtn = page.getByLabel("收起侧栏")
    await toggleBtn.click()
    // 新建事件文本隐藏（侧栏收起时只显示图标）
    await expect(page.getByText("新闻事件")).not.toBeVisible()
  })

  test("登出返回登录页", async ({ page }) => {
    // 点击登出按钮
    await page.getByText("登出").click()
    // 应返回登录页
    await expect(page.getByText("News Sentry")).toBeVisible()
    await expect(page.getByText("管理后台")).toBeVisible()
    // token 被清除
    const token = await page.evaluate(() =>
      localStorage.getItem("news_sentry_token")
    )
    expect(token).toBeNull()
  })
})
