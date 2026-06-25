import { beforeEach, describe, expect, it } from "vitest"
import { AdminApiError, apiUrl, authHeaders, resolveUrl, throwApiError } from "./util"

const SETTINGS_KEY = "news-sentry:settings"
const TOKEN_KEY = "news_sentry_token"

describe("util — API URL resolution", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  // ── resolveUrl ──

  describe("resolveUrl", () => {
    it("returns path as-is when no apiBase is set", () => {
      expect(resolveUrl("/api/v1/health")).toBe("/api/v1/health")
    })

    it("prepends apiBase when set", () => {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({ apiBase: "https://api.example.com" }),
      )
      expect(resolveUrl("/api/v1/health")).toBe("https://api.example.com/api/v1/health")
    })

    it("strips trailing slash from stored apiBase", () => {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({ apiBase: "https://api.example.com/" }),
      )
      expect(resolveUrl("/api/v1/health")).toBe("https://api.example.com/api/v1/health")
    })

    it("returns path as-is when apiBase is non-string", () => {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiBase: 123 }))
      expect(resolveUrl("/api/v1/health")).toBe("/api/v1/health")
    })

    it("returns path as-is when localStorage JSON is corrupt", () => {
      localStorage.setItem(SETTINGS_KEY, "{ bad")
      expect(resolveUrl("/api/v1/health")).toBe("/api/v1/health")
    })
  })

  // ── apiUrl ──

  describe("apiUrl", () => {
    it("prefixes with /api/v1", () => {
      expect(apiUrl("/health")).toBe("/api/v1/health")
    })

    it("handles full path correctly", () => {
      expect(apiUrl("/events")).toBe("/api/v1/events")
    })

    it("prepends apiBase when configured", () => {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({ apiBase: "https://api.example.com" }),
      )
      expect(apiUrl("/health")).toBe("https://api.example.com/api/v1/health")
    })
  })

  // ── authHeaders ──

  describe("authHeaders", () => {
    it("returns empty object when no token is stored", () => {
      expect(authHeaders()).toEqual({})
    })

    it("returns Bearer header when token exists", () => {
      localStorage.setItem(TOKEN_KEY, "test-jwt-token")
      expect(authHeaders()).toEqual({ Authorization: "Bearer test-jwt-token" })
    })

    it("returns empty object when token is empty string", () => {
      localStorage.setItem(TOKEN_KEY, "")
      expect(authHeaders()).toEqual({})
    })
  })
})

// ── AdminApiError ──

describe("AdminApiError", () => {
  it("constructs with statusCode and detail", () => {
    const err = new AdminApiError(404, "Not found")
    expect(err.statusCode).toBe(404)
    expect(err.detail).toBe("Not found")
    expect(err.message).toBe("[404] Not found")
    expect(err.name).toBe("AdminApiError")
    expect(err).toBeInstanceOf(Error)
  })

  describe("isAuthError", () => {
    it("returns true for 401", () => {
      expect(new AdminApiError(401, "Unauthorized").isAuthError).toBe(true)
    })

    it("returns true for 403", () => {
      expect(new AdminApiError(403, "Forbidden").isAuthError).toBe(true)
    })

    it("returns false for 404", () => {
      expect(new AdminApiError(404, "Not found").isAuthError).toBe(false)
    })

    it("returns false for 500", () => {
      expect(new AdminApiError(500, "Server error").isAuthError).toBe(false)
    })
  })

  describe("isServerError", () => {
    it("returns true for 500", () => {
      expect(new AdminApiError(500, "Server error").isServerError).toBe(true)
    })

    it("returns true for 502", () => {
      expect(new AdminApiError(502, "Bad gateway").isServerError).toBe(true)
    })

    it("returns false for 404", () => {
      expect(new AdminApiError(404, "Not found").isServerError).toBe(false)
    })

    it("returns false for 403", () => {
      expect(new AdminApiError(403, "Forbidden").isServerError).toBe(false)
    })
  })
})

// ── throwApiError ──

describe("throwApiError", () => {
  it("throws AdminApiError with detail from JSON body", async () => {
    const res = new Response(JSON.stringify({ detail: "Something went wrong" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    })
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      statusCode: 400,
      detail: "Something went wrong",
    })
  })

  it("falls back to error field when detail is absent", async () => {
    const res = new Response(JSON.stringify({ error: "Generic error" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    })
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      statusCode: 400,
      detail: "Generic error",
    })
  })

  it("uses fallback when body has no detail or error", async () => {
    const res = new Response("{}", {
      status: 500,
      headers: { "Content-Type": "application/json" },
    })
    await expect(throwApiError(res, "Default fallback")).rejects.toMatchObject({
      statusCode: 500,
      detail: "Default fallback",
    })
  })

  it("uses fallback when JSON parsing fails", async () => {
    const res = new Response("not json", { status: 502 })
    await expect(throwApiError(res, "Parse fallback")).rejects.toMatchObject({
      statusCode: 502,
      detail: "Parse fallback",
    })
  })

  it("uses status_code from body when present", async () => {
    const res = new Response(
      JSON.stringify({ detail: "Nested error", status_code: 422 }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    )
    await expect(throwApiError(res, "fallback")).rejects.toMatchObject({
      statusCode: 422,
      detail: "Nested error",
    })
  })
})
