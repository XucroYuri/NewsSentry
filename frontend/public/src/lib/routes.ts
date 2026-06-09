import type { PublicChannel } from "@/lib/feed-state"

export type PublicRoute =
  | { name: "feed"; channel: PublicChannel; search: URLSearchParams }
  | { name: "event"; eventId: string; targetId?: string; search: URLSearchParams }
  | { name: "sources"; search: URLSearchParams }
  | { name: "sourceDetail"; sourceId: string; search: URLSearchParams }
  | { name: "daily"; date?: string; search: URLSearchParams }
  | { name: "analysis"; targetId?: string; section?: string; search: URLSearchParams }

const feedChannels = new Set<PublicChannel>([
  "featured",
  "all",
  "targets",
  "sources",
  "analysis",
  "daily",
])

function normalizeHash(hash: string) {
  const value = hash.startsWith("#") ? hash.slice(1) : hash
  return value.startsWith("/") ? value : `/${value}`
}

function channelFromSearch(search: URLSearchParams): PublicChannel {
  const channel = search.get("channel")
  if (channel && feedChannels.has(channel as PublicChannel)) return channel as PublicChannel
  return "featured"
}

export function parseHashRoute(hash: string): PublicRoute {
  const normalized = normalizeHash(hash || "/feed")
  const [pathPart, queryPart = ""] = normalized.split("?")
  const search = new URLSearchParams(queryPart)
  const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent)
  const [root, second] = segments

  if (root === "events" && second) {
    return {
      name: "event",
      eventId: second,
      targetId: search.get("target_id") ?? undefined,
      search,
    }
  }
  if (root === "sources" && second) {
    return { name: "sourceDetail", sourceId: second, search }
  }
  if (root === "sources") {
    return { name: "sources", search }
  }
  if (root === "daily") {
    return { name: "daily", date: search.get("date") ?? undefined, search }
  }
  if (root === "analysis") {
    return {
      name: "analysis",
      targetId: search.get("target_id") ?? undefined,
      section: search.get("section") ?? undefined,
      search,
    }
  }
  return { name: "feed", channel: channelFromSearch(search), search }
}

export function routeToChannel(route: PublicRoute): PublicChannel {
  if (route.name === "feed") return route.channel
  if (route.name === "sources" || route.name === "sourceDetail") return "sources"
  if (route.name === "daily") return "daily"
  if (route.name === "analysis") return "analysis"
  return "featured"
}

export function buildRouteHash(route: PublicRoute) {
  if (route.name === "event") {
    const params = new URLSearchParams()
    if (route.targetId) params.set("target_id", route.targetId)
    const query = params.toString()
    return `#/events/${encodeURIComponent(route.eventId)}${query ? `?${query}` : ""}`
  }
  if (route.name === "sourceDetail") return `#/sources/${encodeURIComponent(route.sourceId)}`
  if (route.name === "sources") return "#/sources"
  if (route.name === "daily") {
    const params = new URLSearchParams()
    if (route.date) params.set("date", route.date)
    const query = params.toString()
    return `#/daily${query ? `?${query}` : ""}`
  }
  if (route.name === "analysis") {
    const params = new URLSearchParams()
    if (route.targetId) params.set("target_id", route.targetId)
    if (route.section) params.set("section", route.section)
    route.search.forEach((value, key) => {
      if (!params.has(key)) params.set(key, value)
    })
    const query = params.toString()
    return `#/analysis${query ? `?${query}` : ""}`
  }
  const params = new URLSearchParams({ channel: route.channel })
  route.search.forEach((value, key) => {
    if (key !== "channel") params.set(key, value)
  })
  const query = params.toString()
  return `#/feed${query ? `?${query}` : ""}`
}
