import type { PublicChannel } from "@/lib/feed-state"

export type PublicRoute =
  | { name: "feed"; channel: PublicChannel; search: URLSearchParams; locale?: string }
  | { name: "event"; eventId: string; targetId?: string; search: URLSearchParams; locale?: string }
  | { name: "sources"; search: URLSearchParams; locale?: string }
  | { name: "sourceDetail"; sourceId: string; search: URLSearchParams; locale?: string }
  | { name: "daily"; date?: string; search: URLSearchParams; locale?: string }
  | { name: "agent"; search: URLSearchParams; locale?: string }
  | { name: "update"; search: URLSearchParams; locale?: string }
  | { name: "subscribe"; search: URLSearchParams; locale?: string }
  | { name: "analysis"; targetId?: string; section?: string; search: URLSearchParams; locale?: string }

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

function parseRouteParts(pathPart: string, search: URLSearchParams, locale = "zh"): PublicRoute {
  const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent)
  const [root, second] = segments

  if (root === "events" && second) {
    return {
      name: "event",
      eventId: second,
      targetId: search.get("target_id") ?? undefined,
      search,
      locale,
    }
  }
  if (root === "sources" && second) {
    return { name: "sourceDetail", sourceId: second, search, locale }
  }
  if (root === "sources") {
    return { name: "sources", search, locale }
  }
  if (root === "daily") {
    return { name: "daily", date: search.get("date") ?? undefined, search, locale }
  }
  if (root === "agent") {
    return { name: "agent", search, locale }
  }
  if (root === "update") {
    return { name: "update", search, locale }
  }
  if (root === "subscribe") {
    return { name: "subscribe", search, locale }
  }
  if (root === "analysis") {
    return {
      name: "analysis",
      targetId: search.get("target_id") ?? undefined,
      section: search.get("section") ?? undefined,
      search,
      locale,
    }
  }
  return { name: "feed", channel: channelFromSearch(search), search, locale }
}

export function parseHashRoute(hash: string, locale = "zh"): PublicRoute {
  const normalized = normalizeHash(hash || "/feed")
  const [pathPart, queryPart = ""] = normalized.split("?")
  return parseRouteParts(pathPart, new URLSearchParams(queryPart), locale)
}

function parsePublicAppPath(pathname: string, search: string): PublicRoute | null {
  const normalized = pathname.replace(/\/+$/, "") || "/"
  const isItalian = normalized.startsWith("/public-app/it")
  const locale = isItalian ? "it" : "zh"

  // 意大利语首页: /public-app/it 或 /public-app/it/
  if (normalized === "/public-app/it" || normalized === "/public-app/it/") {
    return {
      name: "feed",
      channel: channelFromSearch(buildSearchParams(search)),
      search: buildSearchParams(search),
      locale,
    }
  }

  if (normalized === "/public-app") {
    return {
      name: "feed",
      channel: channelFromSearch(buildSearchParams(search)),
      search: buildSearchParams(search),
      locale,
    }
  }
  if (!normalized.startsWith("/public-app/")) return null

  let pathPart = normalized.slice("/public-app".length)
  // 剥离 /it/ 前缀以获取实际路由
  if (pathPart.startsWith("/it/")) {
    pathPart = pathPart.slice(3) // "/it" → 移除
    if (!pathPart) pathPart = "/"
  } else if (pathPart === "/it") {
    pathPart = "/"
  }

  const params = buildSearchParams(search)
  return parseRouteParts(pathPart || "/", params, locale)
}

export function parseLocationRoute(
  locationLike: Pick<Location, "pathname" | "search" | "hash">,
): PublicRoute {
  const hash = locationLike.hash?.trim() ?? ""
  if (hash.startsWith("#/")) return parseHashRoute(hash)
  const params = buildSearchParams(locationLike.search)
  const pathname = locationLike.pathname
  // 检测意大利语路径前缀
  const isItalian = pathname.startsWith("/public-app/it")
  const locale = isItalian ? "it" : "zh"
  if (pathname.replace(/\/+$/, "") === "/sources") {
    return { name: "sources", search: params, locale }
  }
  if (pathname.replace(/\/+$/, "") === "/subscribe") {
    return { name: "subscribe", search: params, locale }
  }
  return parsePublicAppPath(pathname, locationLike.search) ?? parseHashRoute(hash, locale)
}

export function routeToChannel(route: PublicRoute): PublicChannel {
  if (route.name === "feed") return route.channel
  if (route.name === "sources" || route.name === "sourceDetail") return "sources"
  if (route.name === "daily") return "daily"
  if (route.name === "agent" || route.name === "update" || route.name === "subscribe") return "featured"
  if (route.name === "analysis") return "analysis"
  return "featured"
}

function localePrefix(locale: string) {
  return locale === "it" ? "/public-app/it" : "/public-app"
}

export function buildPublicAppPath(route: PublicRoute) {
  const prefix = localePrefix(route.locale ?? "zh")
  if (route.name === "event") {
    const params = new URLSearchParams(route.search)
    if (route.targetId) params.set("target_id", route.targetId)
    else params.delete("target_id")
    const query = params.toString()
    return `${prefix}/events/${encodeURIComponent(route.eventId)}${query ? `?${query}` : ""}`
  }
  if (route.name === "sourceDetail") return `${prefix}/sources/${encodeURIComponent(route.sourceId)}`
  if (route.name === "sources") return route.locale === "it" ? `${prefix}/sources` : "/sources"
  if (route.name === "daily") {
    const params = new URLSearchParams()
    if (route.date) params.set("date", route.date)
    const query = params.toString()
    return `${prefix}/daily${query ? `?${query}` : ""}`
  }
  if (route.name === "agent") return `${prefix}/agent`
  if (route.name === "update") return `${prefix}/update`
  if (route.name === "subscribe") return route.locale === "it" ? `${prefix}/subscribe` : "/subscribe"
  if (route.name === "analysis") {
    const params = new URLSearchParams()
    if (route.targetId) params.set("target_id", route.targetId)
    if (route.section) params.set("section", route.section)
    route.search.forEach((value, key) => {
      if (!params.has(key)) params.set(key, value)
    })
    const query = params.toString()
    return `${prefix}/analysis${query ? `?${query}` : ""}`
  }
  const params = new URLSearchParams()
  if (route.channel !== "featured") params.set("channel", route.channel)
  route.search.forEach((value, key) => {
    if (key !== "channel") params.set(key, value)
  })
  const query = params.toString()
  return `${prefix}/${query ? `?${query}` : ""}`
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
