import { describe, expect, it } from "vitest"

import { AdminApiError, apiUrl, authHeaders, throwApiError } from "@backend/api/util"

describe("AdminApiError", () => {
  it("stores statusCode and detail", () => {
    const err = new AdminApiError(404, "Not Found")
    expect(err.statusCode).toBe(404)
    expect(err.detail).toBe("Not Found")
    expect(err.message).toBe("[404] Not Found")
    expect(err.name).toBe("AdminApiError")
  })

  it("isAuthError returns true for 401 and 403", () => {
    expect(new AdminApiError(401, "Unauthorized").isAuthError).toBe(true)
    expect(new AdminApiError(403, "Forbidden").isAuthError).toBe(true)
  })

  it("isAuthError returns false for other status codes", () => {
    expect(new AdminApiError(404, "Not Found").isAuthError).toBe(false)
    expect(new AdminApiError(500, "Error").isAuthError).toBe(false)
  })

  it("isServerError returns true for status >= 500", () => {
    expect(new AdminApiError(500, "Internal").isServerError).toBe(true)
    expect(new AdminApiError(502, "Bad Gateway").isServerError).toBe(true)
    expect(new AdminApiError(503, "Unavailable").isServerError).toBe(true)
  })

  it("isServerError returns false for status < 500", () => {
    expect(new AdminApiError(499, "Client").isServerError).toBe(false)
    expect(new AdminApiError(404, "Not Found").isServerError).toBe(false)
    expect(new AdminApiError(200, "OK").isServerError).toBe(false)
  })
})

describe("apiUrl", () => {
  it("prepends /api/v1 to the given path", () => {
    // When no custom apiBase is set, apiUrl returns /api/v1 + path
    const url = apiUrl("/admin/targets")
    expect(url).toBe("/api/v1/admin/targets")
  })

  it("handles paths without leading slash", () => {
    const url = apiUrl("entities/search")
    expect(url).toBe("/api/v1entities/search")
  })
})

describe("authHeaders", () => {
  it("returns empty object when no token in localStorage", () => {
    localStorage.removeItem("news_sentry_token")
    expect(authHeaders()).toEqual({})
  })

  it("returns Authorization header when token is set", () => {
    localStorage.setItem("news_sentry_token", "test-jwt-token")
    expect(authHeaders()).toEqual({ Authorization: "Bearer test-jwt-token" })
    localStorage.removeItem("news_sentry_token")
  })
})

describe("throwApiError", () => {
  it("throws AdminApiError with fallback detail when response body is not JSON", async () => {
    const res = new Response("plain text", { status: 500 })
    await expect(throwApiError(res, "Something went wrong")).rejects.toMatchObject({
      name: "AdminApiError",
      statusCode: 500,
      detail: "Something went wrong",
    })
  })

  it("throws AdminApiError with detail from JSON response body", async () => {
    const res = new Response(
      JSON.stringify({ detail: "Target not found" }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    )
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      name: "AdminApiError",
      statusCode: 404,
      detail: "Target not found",
    })
  })

  it("falls back to error field when detail is not present", async () => {
    const res = new Response(
      JSON.stringify({ error: "Validation failed" }),
      { status: 422, headers: { "Content-Type": "application/json" } },
    )
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      name: "AdminApiError",
      statusCode: 422,
      detail: "Validation failed",
    })
  })

  it("prefers status_code from JSON body over res.status", async () => {
    const res = new Response(
      JSON.stringify({ detail: "Rate limited", status_code: 429 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      name: "AdminApiError",
      statusCode: 429,
      detail: "Rate limited",
    })
  })
})
