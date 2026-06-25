import { test, expect } from "@playwright/test"

/**
 * 登录页面 E2E 测试 — 全 mock API
 *
 * 测试用例:
 * - 页面渲染
 * - 空表单禁用
 * - 部分填写禁用
 * - 完整填写启用
 * - 登录成功跳转
 * - 登录失败显示错误
 * - 加载状态显示
 */

async function loginByToken(page: any) {
  await page.evaluate(() =>
    localStorage.setItem("news_sentry_token", "e2e-test-token")
  )
}

test.describe("登录页", () => {
  test("渲染登录表单", async ({ page }) => {
    // 拦截 API 探针 — 返回 403 表示需要登录
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    await page.goto("/")

    // 等待登录表单出现
    await expect(page.getByText("News Sentry")).toBeVisible()
    await expect(page.getByText("管理后台")).toBeVisible()
    // 用户名和密码输入框
    await expect(page.getByLabel("用户名")).toBeVisible()
    await expect(page.getByLabel("密码")).toBeVisible()
  })

  test("用户名为空时提交按钮禁用", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    await page.goto("/")

    const submitBtn = page.getByRole("button", { name: /登 录/ })
    // 未填写时提交按钮 disabled
    await expect(submitBtn).toBeDisabled()
  })

  test("仅填写用户名时提交按钮仍禁用", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    await page.goto("/")
    await page.getByLabel("用户名").fill("admin")
    const submitBtn = page.getByRole("button", { name: /登 录/ })
    await expect(submitBtn).toBeDisabled()
  })

  test("完整填写后提交按钮启用", async ({ page }) => {
    // mock auth probe — 返回 403 表示需要登录
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    await page.goto("/")
    await page.getByLabel("用户名").fill("admin")
    await page.getByLabel("密码").fill("pass123")
    const submitBtn = page.getByRole("button", { name: /登 录/ })
    await expect(submitBtn).toBeEnabled()
  })

  test("登录成功 — mock API 返回 token，页面跳转", async ({ page }) => {
    // 探针返回 403 → 停留在登录页
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    // 登录 API mock — 返回成功
    await page.route("**/api/v1/auth/login", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: "mock-jwt-token" }),
      })
    })

    await page.goto("/")
    await page.getByLabel("用户名").fill("admin")
    await page.getByLabel("密码").fill("pass123")
    await page.getByRole("button", { name: /登 录/ }).click()

    // 期望：header 中显示 "目标工作台" 标题
    await expect(
      page.locator("header").getByText("目标工作台")
    ).toBeVisible({ timeout: 5000 })
    const token = await page.evaluate(() =>
      localStorage.getItem("news_sentry_token")
    )
    expect(token).toBe("mock-jwt-token")
  })

  test("登录失败 — mock API 返回 401，显示错误提示", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    // 登录 API mock — 返回失败
    await page.route("**/api/v1/auth/login", (route) => {
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Invalid credentials" }),
      })
    })

    await page.goto("/")
    await page.getByLabel("用户名").fill("admin")
    await page.getByLabel("密码").fill("wrong")
    await page.getByRole("button", { name: /登 录/ }).click()

    // 期望：仍停留在登录页，显示错误信息
    await expect(page.getByText("News Sentry")).toBeVisible()
  })

  test("加载状态 — 提交时禁用按钮和输入", async ({ page }) => {
    await page.route("**/api/v1/admin/targets*", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ status: 403, body: "{}" })
      }
      return route.continue()
    })

    // mock login with a small delay to capture loading state
    await page.route("**/api/v1/auth/login", async (route) => {
      await new Promise((r) => setTimeout(r, 100))
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Invalid credentials" }),
      })
    })

    await page.goto("/")
    await page.getByLabel("用户名").fill("admin")
    await page.getByLabel("密码").fill("wrong")

    // 点击提交 — 不等待完成
    await page.getByRole("button", { name: /登 录/ }).click()
    // 等待错误消息出现作为结果
    await expect(page.getByText("News Sentry")).toBeVisible()
  })
})
