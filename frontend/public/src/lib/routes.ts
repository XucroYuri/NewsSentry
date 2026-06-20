import type { PublicChannel } from "@/lib/feed-state"

export type PublicRoute =
  | { name: "feed"; channel: PublicChannel; search: URLSearchParams }
  | { name: "event"; eventId: string; targetId?: string; search: URLSearchParams }
  | { name: "sources"; search: URLSearchParams }
  | { name: "sourceDetail"; sourceId: string; search: URLSearchParams }
  | { name: "daily"; date?: string; search: URLSearchParams }
  | { name: "agent"; search: URLSearchParams }
  | { name: "update"; search: URLSearchParams }
  | { name: "subscribe"; search: URLSearchParams }
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

function buildSearchParams(search: string) {
  const value = search.startsWith("?") ? search.slice(1) : search
  return new URLSearchParams(value)
}

function parseRouteParts(pathPart: string, search: URLSearchParams): PublicRoute {
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
  if (root === "agent") {
    return { name: "agent", search }
  }
  if (root === "update") {
    return { name: "update", search }
  }
  if (root === "subscribe") {
    return { name: "subscribe", search }
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

export function parseHashRoute(hash: string): PublicRoute {
  const normalized = normalizeHash(hash || "/feed")
  const [pathPart, queryPart = ""] = normalized.split("?")
  return parseRouteParts(pathPart, new URLSearchParams(queryPart))
}

function parsePublicAppPath(pathname: string, search: string): PublicRoute | null {
  const normalized = pathname.replace(/\/+$/, "") || "/"
  if (normalized === "/public-app") {
    return {
      name: "feed",
      channel: channelFromSearch(buildSearchParams(search)),
      search: buildSearchParams(search),
    }
  }
  if (!normalized.startsWith("/public-app/")) return null
  const pathPart = normalized.slice("/public-app".length)
  const params = buildSearchParams(search)
  return parseRouteParts(pathPart || "/", params)
}

export function parseLocationRoute(
  locationLike: Pick<Location, "pathname" | "search" | "hash">,
): PublicRoute {
  const hash = locationLike.hash?.trim() ?? ""
  if (hash.startsWith("#/")) return parseHashRoute(hash)
  const params = buildSearchParams(locationLike.search)
  if (locationLike.pathname.replace(/\/+$/, "") === "/sources") {
    return { name: "sources", search: params }
  }
  if (locationLike.pathname.replace(/\/+$/, "") === "/subscribe") {
    return { name: "subscribe", search: params }
  }
  return parsePublicAppPath(locationLike.pathname, locationLike.search) ?? parseHashRoute(hash)
}

export function routeToChannel(route: PublicRoute): PublicChannel {
  if (route.name === "feed") return route.channel
  if (route.name === "sources" || route.name === "sourceDetail") return "sources"
  if (route.name === "daily") return "daily"
  if (route.name === "agent" || route.name === "update" || route.name === "subscribe") return "featured"
  if (route.name === "analysis") return "analysis"
  return "featured"
}

export function buildPublicAppPath(route: PublicRoute) {
  if (route.name === "event") {
    const params = new URLSearchParams(route.search)
    if (route.targetId) params.set("target_id", route.targetId)
    else params.delete("target_id")
    const query = params.toString()
    return `/public-app/events/${encodeURIComponent(route.eventId)}${query ? `?${query}` : ""}`
  }
  if (route.name === "sourceDetail") return `/public-app/sources/${encodeURIComponent(route.sourceId)}`
  if (route.name === "sources") return "/sources"
  if (route.name === "daily") {
    const params = new URLSearchParams()
    if (route.date) params.set("date", route.date)
    const query = params.toString()
    return `/public-app/daily${query ? `?${query}` : ""}`
  }
  if (route.name === "agent") return "/public-app/agent"
  if (route.name === "update") return "/public-app/update"
  if (route.name === "subscribe") return "/subscribe"
  if (route.name === "analysis") {
    const params = new URLSearchParams()
    if (route.targetId) params.set("target_id", route.targetId)
    if (route.section) params.set("section", route.section)
    route.search.forEach((value, key) => {
      if (!params.has(key)) params.set(key, value)
    })
    const query = params.toString()
    return `/public-app/analysis${query ? `?${query}` : ""}`
  }
  const params = new URLSearchParams()
  if (route.channel !== "featured") params.set("channel", route.channel)
  route.search.forEach((value, key) => {
    if (key !== "channel") params.set(key, value)
  })
  const query = params.toString()
  return `/public-app/${query ? `?${query}` : ""}`
}

export function buildRouteHash(route: PublicRoute) {
  if (route.name === "event") {
    const params = new URLSearchParams(route.search)
    if (route.targetId) params.set("target_id", route.targetId)
    else params.delete("target_id")
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
  if (route.name === "agent") return "#/agent"
  if (route.name === "update") return "#/update"
  if (route.name === "subscribe") return "#/subscribe"
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
