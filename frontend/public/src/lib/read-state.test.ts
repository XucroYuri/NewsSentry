import { beforeEach, describe, expect, it } from "vitest"
import { clearReadHistory, getReadIds, markAsRead, markManyAsRead } from "@/lib/read-state"

describe("read-state", () => {
  beforeEach(() => {
    localStorage.clear()
    clearReadHistory()
  })

  it("starts with no read ids", () => {
    expect(getReadIds().size).toBe(0)
  })

  it("marks a single id as read", () => {
    markAsRead("event-1")
    const ids = getReadIds()
    expect(ids.has("event-1")).toBe(true)
    expect(ids.size).toBe(1)
  })

  it("marks many ids as read", () => {
    markManyAsRead(["event-1", "event-2", "event-3"])
    const ids = getReadIds()
    expect(ids.has("event-1")).toBe(true)
    expect(ids.has("event-2")).toBe(true)
    expect(ids.has("event-3")).toBe(true)
    expect(ids.size).toBe(3)
  })

  it("does not duplicate already-read ids", () => {
    markAsRead("event-1")
    markAsRead("event-1")
    expect(getReadIds().size).toBe(1)
  })

  it("skips empty ids", () => {
    markAsRead("")
    markManyAsRead(["", "event-1", ""])
    expect(getReadIds().size).toBe(1)
    expect(getReadIds().has("event-1")).toBe(true)
  })

  it("clears all read history", () => {
    markManyAsRead(["event-1", "event-2"])
    clearReadHistory()
    expect(getReadIds().size).toBe(0)
  })

  it("is idempotent in markManyAsRead across calls", () => {
    markManyAsRead(["event-1", "event-2"])
    markManyAsRead(["event-2", "event-3"])
    const ids = getReadIds()
    expect(ids.size).toBe(3)
    expect(ids.has("event-3")).toBe(true)
  })
})
