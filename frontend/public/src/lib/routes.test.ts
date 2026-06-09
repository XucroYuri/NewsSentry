import { describe, expect, it } from "vitest"

import { buildRouteHash, parseHashRoute, routeToChannel } from "@/lib/routes"

describe("public app hash routes", () => {
  it("defaults the public app root to the featured feed", () => {
    expect(parseHashRoute("")).toEqual({
      name: "feed",
      channel: "featured",
      search: new URLSearchParams(),
    })
  })

  it("parses feed, detail, source, daily, and analysis routes", () => {
    expect(parseHashRoute("#/feed?channel=daily").name).toBe("feed")
    expect(routeToChannel(parseHashRoute("#/feed?channel=sources"))).toBe("sources")
    expect(parseHashRoute("#/events/event-1?target_id=italy")).toMatchObject({
      name: "event",
      eventId: "event-1",
      targetId: "italy",
    })
    expect(parseHashRoute("#/sources/ansa")).toMatchObject({
      name: "sourceDetail",
      sourceId: "ansa",
    })
    expect(parseHashRoute("#/daily?date=2026-06-09")).toMatchObject({
      name: "daily",
      date: "2026-06-09",
    })
    expect(parseHashRoute("#/analysis?target_id=italy")).toMatchObject({
      name: "analysis",
      targetId: "italy",
    })
    expect(parseHashRoute("#/analysis?target_id=italy&section=entities")).toMatchObject({
      name: "analysis",
      targetId: "italy",
      section: "entities",
    })
  })

  it("builds reader route hashes with encoded query params and preserves feed filters", () => {
    expect(
      buildRouteHash({
        name: "event",
        eventId: "event 1",
        targetId: "italy",
        search: new URLSearchParams(),
      }),
    ).toBe("#/events/event%201?target_id=italy")
    expect(
      buildRouteHash({
        name: "daily",
        date: "2026-06-09",
        search: new URLSearchParams(),
      }),
    ).toBe("#/daily?date=2026-06-09")
    expect(
      buildRouteHash({
        name: "feed",
        channel: "targets",
        search: new URLSearchParams({
          target_id: "italy",
          category: "国际关系",
          q: "欧盟",
        }),
      }),
    ).toBe("#/feed?channel=targets&target_id=italy&category=%E5%9B%BD%E9%99%85%E5%85%B3%E7%B3%BB&q=%E6%AC%A7%E7%9B%9F")
    expect(
      buildRouteHash({
        name: "analysis",
        targetId: "italy",
        section: "entities",
        search: new URLSearchParams(),
      }),
    ).toBe("#/analysis?target_id=italy&section=entities")
  })
})
