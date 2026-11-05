import { ReaderApiError, type ReaderAdapter, type ReaderArticle, type ReaderTranslation } from "./types"

export function safeReaderLink(value: string, origin = window.location.origin): string | undefined {
  if (!value.trim()) return undefined
  try {
    const url = new URL(value, origin)
    if (!["http:", "https:"].includes(url.protocol) || url.href.split("/")[2] !== url.host) return undefined
    return url.href
  } catch {
    return undefined
  }
}

export function safeProxyUrl(value: string, origin = window.location.origin): string | undefined {
  const href = safeReaderLink(value, origin)
  if (!href) return undefined
  const url = new URL(href)
  if (url.origin !== origin || url.pathname !== "/api/v1/reader/image" || url.hash) return undefined
  if (!/^[a-f0-9]{64}$/.test(url.searchParams.get("s") ?? "")) return undefined
  if (!safeReaderLink(url.searchParams.get("u") ?? "", origin) || !url.searchParams.get("u")) return undefined
  return `${url.pathname}${url.search}`
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function invalid(): never {
  throw new ReaderApiError(502, "INVALID_READER_RESPONSE", "Invalid reader response")
}

function articleResponse(value: unknown): ReaderArticle {
  if (!record(value)) return invalid()
  const { markdown, images, sourceUrl, lang, title, contentHash, attribution } = value
  if (
    typeof markdown !== "string" || !markdown.trim() || !Array.isArray(images) ||
    typeof sourceUrl !== "string" || !safeReaderLink(sourceUrl) ||
    typeof lang !== "string" || typeof title !== "string" ||
    typeof contentHash !== "string" || !/^[a-f0-9]{32}$/.test(contentHash) ||
    typeof attribution !== "string"
  ) return invalid()
  return {
    markdown, sourceUrl, lang, title, contentHash, attribution,
    images: images.map((image) => {
      if (!record(image) || typeof image.src !== "string" || typeof image.proxyUrl !== "string" || (image.alt !== undefined && typeof image.alt !== "string")) return invalid()
      // 无效代理保留为失败占位，绝不回退 src。
      return { src: image.src, proxyUrl: safeProxyUrl(image.proxyUrl) ?? "", alt: image.alt }
    }),
  }
}

function translationResponse(value: unknown): ReaderTranslation {
  if (!record(value) || typeof value.translated !== "string" || !value.translated.trim() || typeof value.lang !== "string" || typeof value.cached !== "boolean" || typeof value.provider !== "string") return invalid()
  return { translated: value.translated, lang: value.lang, cached: value.cached, provider: value.provider }
}

export function createReaderAdapter(fetcher: typeof fetch = fetch): ReaderAdapter {
  async function post(path: string, body: unknown, signal?: AbortSignal): Promise<unknown> {
    const response = await fetcher(`/api/v1/reader/${path}`, {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal,
    })
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      throw new ReaderApiError(
        response.status,
        record(payload) && typeof payload.code === "string" ? payload.code : "READER_UNAVAILABLE",
        record(payload) && typeof payload.message === "string" ? payload.message : "Reader unavailable",
      )
    }
    return payload
  }
  return {
    preview: async (input, signal) => articleResponse(await post("preview", input, signal)),
    translate: async (input, signal) => translationResponse(await post("translate", input, signal)),
  }
}
