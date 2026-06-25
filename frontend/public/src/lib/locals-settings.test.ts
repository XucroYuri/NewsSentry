import { beforeEach, describe, expect, it } from "vitest"
import { getApiBase, getSettings, resolveUrl, setApiBase } from "@/lib/locals-settings"

const STORAGE_KEY = "news-sentry:settings"

describe("locals-settings", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  // ── getSettings ──

  describe("getSettings", () => {
    it("returns default settings when no stored value exists", () => {
      const settings = getSettings()
      // 未设置 localStorage 时 apiBase 为 null（未配置 VITE_API_BASE 时）
      expect(settings.apiBase).toBeNull()
    })

    it("returns stored settings when present", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ apiBase: "https://api.example.com" }))
      const settings = getSettings()
      expect(settings.apiBase).toBe("https://api.example.com")
    })

    it("strips trailing slash from stored apiBase", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ apiBase: "https://api.example.com/" }))
      const settings = getSettings()
      expect(settings.apiBase).toBe("https://api.example.com")
    })

    it("treats non-string apiBase as null", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ apiBase: 12345 }))
      const settings = getSettings()
      expect(settings.apiBase).toBeNull()
    })

    it("returns defaults when JSON is invalid", () => {
      localStorage.setItem(STORAGE_KEY, "{ bad json")
      const settings = getSettings()
      expect(settings.apiBase).toBeNull()
    })
  })

  // ── getApiBase ──

  describe("getApiBase", () => {
    it("returns null by default", () => {
      expect(getApiBase()).toBeNull()
    })

    it("returns stored apiBase value", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ apiBase: "https://api.example.com" }))
      expect(getApiBase()).toBe("https://api.example.com")
    })
  })

  // ── setApiBase ──

  describe("setApiBase", () => {
    it("persists a valid URL to localStorage", () => {
      setApiBase("https://api.example.com")
      const raw = localStorage.getItem(STORAGE_KEY)
      expect(raw).not.toBeNull()
      const parsed = JSON.parse(raw!)
      expect(parsed.apiBase).toBe("https://api.example.com")
    })

    it("strips trailing slash when saving", () => {
      setApiBase("https://api.example.com///")
      const raw = localStorage.getItem(STORAGE_KEY)
      const parsed = JSON.parse(raw!)
      expect(parsed.apiBase).toBe("https://api.example.com")
    })

    it("converts empty string to null", () => {
      setApiBase("")
      const raw = localStorage.getItem(STORAGE_KEY)
      const parsed = JSON.parse(raw!)
      expect(parsed.apiBase).toBeNull()
    })

    it("converts whitespace-only string to null", () => {
      setApiBase("   ")
      const raw = localStorage.getItem(STORAGE_KEY)
      const parsed = JSON.parse(raw!)
      expect(parsed.apiBase).toBeNull()
    })

    it("converts null to null (reset to default)", () => {
      setApiBase("https://api.example.com")
      setApiBase(null)
      const raw = localStorage.getItem(STORAGE_KEY)
      const parsed = JSON.parse(raw!)
      expect(parsed.apiBase).toBeNull()
    })
  })

  // ── resolveUrl ──

  describe("resolveUrl", () => {
    it("returns path as-is when apiBase is null", () => {
      expect(resolveUrl("/api/v1/health")).toBe("/api/v1/health")
    })

    it("prepends apiBase to path when set", () => {
      setApiBase("https://api.example.com")
      expect(resolveUrl("/api/v1/health")).toBe("https://api.example.com/api/v1/health")
    })

    it("returns path as-is for empty-string apiBase", () => {
      // 空字符串被 setApiBase 规范化为 null，但直接测试 resolveUrl 也需要
      // 先设置为某个值，再清除 localStorage 恢复默认
      setApiBase("https://api.example.com")
      localStorage.removeItem(STORAGE_KEY)
      expect(resolveUrl("/api/v1/events")).toBe("/api/v1/events")
    })
  })
})
