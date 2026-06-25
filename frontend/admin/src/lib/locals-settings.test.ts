import { describe, expect, it } from "vitest"

import { getApiBase, getSettings, resolveUrl, setApiBase } from "@/lib/locals-settings"

// helpers to keep localStorage clean between tests
function clearSettings() {
  localStorage.removeItem("news-sentry:settings")
}

describe("locals-settings", () => {
  describe("getSettings / getApiBase", () => {
    it("returns default settings when nothing is stored", () => {
      clearSettings()
      const settings = getSettings()
      expect(settings.apiBase).toBeNull()
      expect(getApiBase()).toBeNull()
    })

    it("returns stored apiBase", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: "https://example.com" }),
      )
      expect(getApiBase()).toBe("https://example.com")
      clearSettings()
    })

    it("returns null for invalid JSON in localStorage", () => {
      localStorage.setItem("news-sentry:settings", "{invalid")
      expect(getApiBase()).toBeNull()
      clearSettings()
    })

    it("returns null when apiBase is not a string", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: 123 }),
      )
      expect(getApiBase()).toBeNull()
      clearSettings()
    })

    it("strips trailing slash from stored apiBase", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: "https://example.com/" }),
      )
      expect(getApiBase()).toBe("https://example.com")
      clearSettings()
    })
  })

  describe("setApiBase", () => {
    it("saves and retrieves a URL", () => {
      clearSettings()
      setApiBase("https://api.example.com")
      expect(getApiBase()).toBe("https://api.example.com")
      clearSettings()
    })

    it("strips trailing slash on save", () => {
      clearSettings()
      setApiBase("https://api.example.com/")
      expect(getApiBase()).toBe("https://api.example.com")
      clearSettings()
    })

    it("treats empty string as null (reset to default)", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: "https://old.com" }),
      )
      setApiBase("")
      expect(getApiBase()).toBeNull()
      clearSettings()
    })

    it("treats null as reset", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: "https://old.com" }),
      )
      setApiBase(null)
      expect(getApiBase()).toBeNull()
      clearSettings()
    })
  })

  describe("resolveUrl", () => {
    it("returns path unchanged when apiBase is null", () => {
      clearSettings()
      expect(resolveUrl("/api/v1/health")).toBe("/api/v1/health")
    })

    it("prepends apiBase to path when set", () => {
      localStorage.setItem(
        "news-sentry:settings",
        JSON.stringify({ apiBase: "https://api.example.com" }),
      )
      expect(resolveUrl("/api/v1/targets")).toBe(
        "https://api.example.com/api/v1/targets",
      )
      clearSettings()
    })
  })
})
