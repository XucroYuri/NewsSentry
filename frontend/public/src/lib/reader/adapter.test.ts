import { describe, expect, it, vi, afterEach } from "vitest"
import { createReaderAdapter, safeProxyUrl, safeReaderLink } from "./adapter"
import { createMockReaderAdapter, mockArticle, mockImageUrl } from "./mock-adapter"
import { parseReaderRoute, readerMode, readerPath } from "./routes"
import { preferredLocale, readerLocales } from "./locales"
import messages from "./messages.json"

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })

describe("Reader #76 adapter", () => {
  it("posts exact DTOs to same-origin endpoints with cookies and abort signal", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(mockArticle)).mockResolvedValueOnce(json({ translated: "译文", lang: "zh", cached: true, provider: "kv" }))
    const adapter = createReaderAdapter(fetcher)
    const controller = new AbortController()
    expect(await adapter.preview({ articleId: "evt-1" }, controller.signal)).toEqual(mockArticle)
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/reader/preview", expect.objectContaining({ method: "POST", credentials: "same-origin", redirect: "error", signal: controller.signal, body: JSON.stringify({ articleId: "evt-1" }) }))
    const input = { markdown: mockArticle.markdown, targetLang: "zh", contentHash: mockArticle.contentHash, sourceLang: "en" }
    expect(await adapter.translate(input)).toMatchObject({ translated: "译文", cached: true })
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/reader/translate", expect.objectContaining({ body: JSON.stringify(input) }))
  })

  it.each([403, 422, 429, 503])("preserves structured status/code for %s fallback", async (status) => {
    const adapter = createReaderAdapter(vi.fn().mockResolvedValue(json({ error: "unavailable", code: "TEST_ERROR", message: "detail" }, status)))
    await expect(adapter.preview({ url: "https://example.com" })).rejects.toMatchObject({ status, code: "TEST_ERROR", message: "detail" })
  })

  it("rejects corrupt DTOs and never substitutes original image src", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({ ...mockArticle, contentHash: "bad" })).mockResolvedValueOnce(json({ ...mockArticle, images: [{ src: "https://foreign.test/a.png", proxyUrl: "https://foreign.test/a.png" }] }))
    const adapter = createReaderAdapter(fetcher)
    await expect(adapter.preview({ articleId: "x" })).rejects.toMatchObject({ code: "INVALID_READER_RESPONSE" })
    expect((await adapter.preview({ articleId: "x" })).images[0].proxyUrl).toBe("")
  })

  it("allows only signed same-origin proxy URLs and HTTP(S) links", () => {
    expect(safeProxyUrl(mockImageUrl)).toBe(mockImageUrl)
    for (const url of ["https://foreign.test/a.png", "//foreign.test/api/v1/reader/image", "/api/v1/reader/image?u=x&s=bad", "data:image/svg+xml,test", "javascript:alert(1)", `${mockImageUrl}#x`]) expect(safeProxyUrl(url)).toBeUndefined()
    expect(safeReaderLink("javascript:alert(1)")).toBeUndefined()
    expect(safeReaderLink("https://user:pass@example.com/")).toBeUndefined()
    expect(safeReaderLink("https://example.com/news")).toBe("https://example.com/news")
  })

  it("mock preserves proxy destinations, supports failure and cancellation", async () => {
    const adapter = createMockReaderAdapter()
    const result = await adapter.translate({ markdown: mockArticle.markdown, contentHash: mockArticle.contentHash, targetLang: "ar" })
    expect(result.translated).toContain(mockImageUrl)
    expect(result.translated).toContain("الملاحة")
    await expect(createMockReaderAdapter("translate-unavailable").translate({ markdown: "x", contentHash: "x", targetLang: "zh" })).rejects.toMatchObject({ status: 503 })
    const controller = new AbortController()
    const pending = adapter.preview({ articleId: "x" }, controller.signal)
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: "AbortError" })
  })
})

describe("Reader gating and locale routes", () => {
  it("defaults off and confines mock to loopback even with query override", () => {
    expect(readerMode({ hostname: "news-sentry.com", search: "?reader=mock&READER_V1=1" }, "0")).toBe("off")
    expect(readerMode({ hostname: "127.0.0.1", search: "?reader=mock" }, "0")).toBe("mock")
    expect(readerMode({ hostname: "news-sentry.com", search: "" }, "1")).toBe("live")
  })

  it("keeps ten complete message dictionaries and URL locale plus preference", () => {
    expect(readerLocales).toHaveLength(10)
    for (const locale of readerLocales) {
      expect(Object.keys(messages[locale]).sort()).toEqual(Object.keys(messages.zh).sort())
      expect(Object.values(messages[locale]).every(Boolean)).toBe(true)
      expect(parseReaderRoute({ pathname: `/${locale}/reader/evt%201`, search: `?locale=${locale}` })).toMatchObject({ locale, articleId: "evt 1" })
    }
    localStorage.setItem("news-sentry-reader-locale", "ja")
    expect(preferredLocale()).toBe("ja")
    expect(preferredLocale("ar")).toBe("ar")
    expect(readerPath("evt 1", "ko")).toBe("/ko/reader/evt%201?locale=ko")
    expect(parseReaderRoute({ pathname: "/zz/reader/x", search: "" })).toBeNull()
    expect(parseReaderRoute({ pathname: "/zh/reader/%zz", search: "" })).toBeNull()
  })
})
