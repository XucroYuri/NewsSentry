import { describe, expect, it } from "vitest"

import { cn, getLifecycleStatus, scoreVariant } from "@/lib/utils"

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b")
  })

  it("resolves Tailwind conflicts via twMerge", () => {
    // twMerge: later classes override earlier conflicting ones
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4")
  })

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "extra")).toBe("base extra")
  })

  it("returns empty string for no inputs", () => {
    expect(cn()).toBe("")
  })
})

describe("scoreVariant", () => {
  it('returns "outline" for undefined', () => {
    expect(scoreVariant(undefined)).toBe("outline")
  })

  it('returns "success" for score >= 80', () => {
    expect(scoreVariant(80)).toBe("success")
    expect(scoreVariant(95)).toBe("success")
    expect(scoreVariant(100)).toBe("success")
  })

  it('returns "secondary" for 50 <= score < 80', () => {
    expect(scoreVariant(50)).toBe("secondary")
    expect(scoreVariant(65)).toBe("secondary")
    expect(scoreVariant(79)).toBe("secondary")
  })

  it('returns "outline" for score < 50', () => {
    expect(scoreVariant(0)).toBe("outline")
    expect(scoreVariant(30)).toBe("outline")
    expect(scoreVariant(49)).toBe("outline")
  })
})

describe("getLifecycleStatus", () => {
  it("extracts status from a lifecycle object", () => {
    expect(getLifecycleStatus({ status: "active" })).toBe("active")
    expect(getLifecycleStatus({ status: "idle", extra: 1 })).toBe("idle")
  })

  it("returns empty string for null or undefined", () => {
    expect(getLifecycleStatus(null)).toBe("")
    expect(getLifecycleStatus(undefined)).toBe("")
  })

  it("returns empty string for a plain string input", () => {
    expect(getLifecycleStatus("some-string")).toBe("")
  })

  it("returns empty string when lifecycle object has no status key", () => {
    expect(getLifecycleStatus({})).toBe("")
  })
})
