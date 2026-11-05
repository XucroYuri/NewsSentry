import { asReaderLocale, preferredLocale, type ReaderLocale } from "./locales"

export type ReaderMode = "off" | "mock" | "live"

export function readerMode(
  location: Pick<Location, "hostname" | "search"> = window.location,
  flag: string | undefined = import.meta.env.VITE_READER_V1,
): ReaderMode {
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)
  if (local && new URLSearchParams(location.search).get("reader") === "mock") return "mock"
  return flag === "1" ? "live" : "off"
}

export function parseReaderRoute(location: Pick<Location, "pathname" | "search">) {
  const path = location.pathname.replace(/^\/public-app(?=\/)/, "")
  const match = path.match(/^\/(?:([a-z]{2})\/)?reader\/([^/]+)\/?$/)
  if (!match || (match[1] && !asReaderLocale(match[1]))) return null
  try {
    const params = new URLSearchParams(location.search)
    return {
      articleId: decodeURIComponent(match[2]),
      locale: preferredLocale(match[1] ?? params.get("locale")),
      params,
    }
  } catch {
    return null
  }
}

export function readerPath(articleId: string, locale: ReaderLocale, params = new URLSearchParams()) {
  const search = new URLSearchParams(params)
  search.set("locale", locale)
  return `${import.meta.env.BASE_URL}${locale}/reader/${encodeURIComponent(articleId)}?${search}`
}

export function readerLink(item: {
  id: string
  title: string
  originalUrl?: string | null
  publishedAt?: string | null
  source: { name: string }
}, locale = preferredLocale()) {
  const params = new URLSearchParams({ title: item.title, source: item.source.name })
  if (item.originalUrl) params.set("url", item.originalUrl)
  if (item.publishedAt) params.set("published_at", item.publishedAt)
  if (readerMode() === "mock") params.set("reader", "mock")
  return readerPath(item.id, locale, params)
}
