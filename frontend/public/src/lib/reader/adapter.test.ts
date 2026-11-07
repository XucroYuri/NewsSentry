import { describe, expect, it, vi, afterEach } from "vitest"
import { createReaderAdapter, safeProxyUrl, safeReaderLink } from "./adapter"
import { createMockReaderAdapter, mockArticle, mockImageUrl } from "./mock-adapter"
import { parseReaderRoute, readerMode, readerPath } from "./routes"
import { preferredLocale, readerLocales } from "./locales"
import messages from "./messages.json"

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
const translationInput = { markdown: mockArticle.markdown, targetLang: "zh", contentHash: mockArticle.contentHash, sourceLang: "en" }
const completedJob = { jobId: "job-1", status: "succeeded", attemptCount: 1, translated: "译文", lang: "zh", cached: true, provider: "kv" }
const savedJobKey = `news-sentry-reader-job:v1:${JSON.stringify(["article-1", translationInput.contentHash, "zh", "en"])}`

afterEach(() => { localStorage.clear(); sessionStorage.clear(); vi.useRealTimers(); vi.restoreAllMocks() })

describe("Reader #76 adapter", () => {
  it("posts exact DTOs to same-origin endpoints with cookies and abort signal", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(mockArticle)).mockResolvedValueOnce(json(completedJob))
    const adapter = createReaderAdapter(fetcher)
    const controller = new AbortController()
    expect(await adapter.preview({ articleId: "evt-1" }, controller.signal)).toEqual(mockArticle)
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/reader/preview", expect.objectContaining({ method: "POST", credentials: "same-origin", redirect: "error", signal: controller.signal, body: JSON.stringify({ articleId: "evt-1" }) }))
    const input = { markdown: mockArticle.markdown, targetLang: "zh", contentHash: mockArticle.contentHash, sourceLang: "en" }
    expect(await adapter.translate(input)).toMatchObject({ translated: "译文", cached: true })
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/reader/translate", expect.objectContaining({ body: JSON.stringify(input) }))
  })

  it("polls queued and running jobs with 1500–5000ms backoff and reports real states", async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ jobId: "job/1", status: "queued", attemptCount: 0 }))
      .mockImplementation(() => Promise.resolve(json({ jobId: "job/1", status: "running", attemptCount: 1 })))
    const progress = vi.fn()
    const controller = new AbortController()
    const pending = createReaderAdapter(fetcher).translate(translationInput, controller.signal, { articleId: "article-1", onProgress: progress })
    await vi.advanceTimersByTimeAsync(0)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "queued", attemptCount: 0 }))
    for (const delay of [1500, 2250, 3375, 5000, 5000]) {
      const count = fetcher.mock.calls.length
      await vi.advanceTimersByTimeAsync(delay - 1)
      expect(fetcher).toHaveBeenCalledTimes(count)
      await vi.advanceTimersByTimeAsync(1)
      expect(fetcher).toHaveBeenCalledTimes(count + 1)
    }
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "running", attemptCount: 1 }))
    expect(fetcher).toHaveBeenLastCalledWith("/api/v1/reader/translate/job%2F1", expect.objectContaining({ method: "GET", credentials: "same-origin", redirect: "error", signal: controller.signal, body: undefined }))
    fetcher.mockImplementation(() => Promise.resolve(json({ ...completedJob, jobId: "job/1" })))
    await vi.advanceTimersByTimeAsync(5000)
    await expect(pending).resolves.toMatchObject({ translated: "译文" })
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "succeeded" }))
    expect(vi.getTimerCount()).toBe(0)
  })

  it("keeps polling beyond 120 seconds without an early client abort", async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(json({ jobId: "long-job", status: "running", attemptCount: 1 })))
    const controller = new AbortController()
    const settled = vi.fn()
    const pending = createReaderAdapter(fetcher).translate(translationInput, controller.signal)
    void pending.then(settled)
    await vi.advanceTimersByTimeAsync(180_000)
    expect(controller.signal.aborted).toBe(false)
    expect(settled).not.toHaveBeenCalled()
    expect(fetcher.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1)
    fetcher.mockImplementation(() => Promise.resolve(json(completedJob)))
    await vi.advanceTimersByTimeAsync(5000)
    await expect(pending).resolves.toMatchObject({ translated: "译文" })
  })

  it("cancels the poll wait on abort and restores the saved job with GET after refresh", async () => {
    vi.useFakeTimers()
    const firstFetch = vi.fn().mockResolvedValue(json({ jobId: "restore-job", status: "queued", attemptCount: 0 }))
    const controller = new AbortController()
    const pending = createReaderAdapter(firstFetch).translate(translationInput, controller.signal, { articleId: "article-1" })
    const cancelled = expect(pending).rejects.toMatchObject({ name: "AbortError" })
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await cancelled
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(firstFetch).toHaveBeenCalledTimes(1)
    const restoredFetch = vi.fn().mockResolvedValue(json({ ...completedJob, jobId: "restore-job" }))
    await expect(createReaderAdapter(restoredFetch).translate(translationInput, undefined, { articleId: "article-1" })).resolves.toMatchObject({ translated: "译文" })
    expect(restoredFetch).toHaveBeenCalledExactlyOnceWith("/api/v1/reader/translate/restore-job", expect.objectContaining({ method: "GET", credentials: "same-origin" }))
  })

  it("passes abort to an in-flight poll request", async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ jobId: "job-1", status: "running", attemptCount: 1 }))
      .mockImplementation((_url, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true })
      }))
    const pending = createReaderAdapter(fetcher).translate(translationInput, controller.signal)
    const cancelled = expect(pending).rejects.toMatchObject({ name: "AbortError" })
    await vi.advanceTimersByTimeAsync(1500)
    expect(fetcher).toHaveBeenCalledTimes(2)
    controller.abort()
    await cancelled
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each(["another-account-job", "nonexistent-job", "cleaned-job"])("clears restored 404 reference %s and requires explicit resubmission even after refresh", async (jobId) => {
    vi.useFakeTimers()
    sessionStorage.setItem(savedJobKey, jobId)
    sessionStorage.setItem("unrelated-job", "keep")
    const fetcher = vi.fn().mockResolvedValue(json({ code: "NOT_FOUND", message: "Not found" }, 404))
    const progress = vi.fn()
    const context = { articleId: "article-1", onProgress: progress }
    const api = createReaderAdapter(fetcher)
    await expect(api.translate(translationInput, undefined, context)).rejects.toMatchObject({
      status: 404, code: "TRANSLATION_JOB_NOT_FOUND",
    })
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(`/api/v1/reader/translate/${jobId}`, expect.objectContaining({ method: "GET" }))
    expect(sessionStorage.getItem(savedJobKey)).toBeNull()
    expect(sessionStorage.getItem("unrelated-job")).toBe("keep")
    expect(progress).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000)
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, context)).rejects.toMatchObject({ code: "TRANSLATION_JOB_NOT_FOUND" })
    expect(fetcher).toHaveBeenCalledTimes(1)

    fetcher.mockImplementation(() => Promise.resolve(json(completedJob)))
    await expect(api.translate({ ...translationInput, retry: true }, undefined, context)).resolves.toMatchObject({ translated: "译文" })
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/reader/translate", expect.objectContaining({
      method: "POST", body: JSON.stringify({ ...translationInput, retry: true }),
    }))
    expect(sessionStorage.getItem(savedJobKey)).toBe("job-1")
    expect(sessionStorage.getItem(`${savedJobKey}:resubmit`)).toBeNull()
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, context)).resolves.toMatchObject({ translated: "译文" })
    expect(fetcher).toHaveBeenNthCalledWith(3, "/api/v1/reader/translate/job-1", expect.objectContaining({ method: "GET" }))
  })

  it("stops polling and clears the reference if an existing job disappears", async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ jobId: "deleted-job", status: "running", attemptCount: 1 }))
      .mockResolvedValue(json({ code: "NOT_FOUND" }, 404))
    const pending = createReaderAdapter(fetcher).translate(translationInput, undefined, { articleId: "article-1" })
    const failed = expect(pending).rejects.toMatchObject({ status: 404, code: "TRANSLATION_JOB_NOT_FOUND" })
    await vi.advanceTimersByTimeAsync(1500)
    await failed
    expect(sessionStorage.getItem(savedJobKey)).toBeNull()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher).toHaveBeenLastCalledWith("/api/v1/reader/translate/deleted-job", expect.objectContaining({ method: "GET" }))
  })

  it("keeps explicit resubmission required if the new POST fails", async () => {
    sessionStorage.setItem(savedJobKey, "missing-job")
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({}, 404))
      .mockResolvedValue(json({ code: "TRANSLATION_SUBMIT_DISABLED" }, 503))
    const api = createReaderAdapter(fetcher)
    const context = { articleId: "article-1" }
    await expect(api.translate(translationInput, undefined, context)).rejects.toMatchObject({ code: "TRANSLATION_JOB_NOT_FOUND" })
    await expect(api.translate({ ...translationInput, retry: true }, undefined, context)).rejects.toMatchObject({ status: 503 })
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, context)).rejects.toMatchObject({ code: "TRANSLATION_JOB_NOT_FOUND" })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it.each([403, 429, 503])("preserves restored job references and errors for GET %s", async (status) => {
    sessionStorage.setItem(savedJobKey, "existing-job")
    const fetcher = vi.fn().mockResolvedValue(json({ code: "TEST_ERROR", message: "detail" }, status))
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, { articleId: "article-1" })).rejects.toMatchObject({ status, code: "TEST_ERROR", message: "detail" })
    expect(sessionStorage.getItem(savedJobKey)).toBe("existing-job")
    expect(sessionStorage.getItem(`${savedJobKey}:resubmit`)).toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it("validates and forwards real chunk counts independently of execution attempts", async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ jobId: "chunks", status: "queued", attemptCount: 0, completedChunks: 0, totalChunks: 0 }))
      .mockResolvedValueOnce(json({ jobId: "chunks", status: "running", attemptCount: 1, completedChunks: 0, totalChunks: 4 }))
      .mockResolvedValueOnce(json({ jobId: "chunks", status: "running", attemptCount: 2, completedChunks: 2, totalChunks: 4 }))
      .mockResolvedValueOnce(json({ ...completedJob, jobId: "chunks", completedChunks: 4, totalChunks: 4 }))
    const progress = vi.fn()
    const pending = createReaderAdapter(fetcher).translate(translationInput, undefined, { onProgress: progress })
    await vi.advanceTimersByTimeAsync(0)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ completedChunks: 0, totalChunks: 0 }))
    await vi.advanceTimersByTimeAsync(1500)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ completedChunks: 0, totalChunks: 4 }))
    await vi.advanceTimersByTimeAsync(2250)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ completedChunks: 2, totalChunks: 4 }))
    await vi.advanceTimersByTimeAsync(3375)
    await expect(pending).resolves.toMatchObject({ translated: "译文" })
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ completedChunks: 4, totalChunks: 4 }))
  })

  it.each([
    { completedChunks: -1, totalChunks: 4 },
    { completedChunks: 1.5, totalChunks: 4 },
    { completedChunks: "1", totalChunks: 4 },
    { completedChunks: null, totalChunks: 4 },
    { completedChunks: 5, totalChunks: 4 },
    { completedChunks: 0, totalChunks: -1 },
    { completedChunks: 0, totalChunks: 1.5 },
    { completedChunks: 0, totalChunks: "4" },
    { completedChunks: 0, totalChunks: null },
    { completedChunks: 0, totalChunks: Number.MAX_SAFE_INTEGER + 1 },
    { completedChunks: 1 },
    { totalChunks: 4 },
  ])("rejects invalid chunk progress %j", async (counts) => {
    const progress = vi.fn()
    const fetcher = vi.fn().mockResolvedValue(json({ ...completedJob, ...counts }))
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, { onProgress: progress })).rejects.toMatchObject({ code: "INVALID_READER_RESPONSE" })
    expect(progress).not.toHaveBeenCalled()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it.each(["failed", "timed_out"])("restores %s without resubmitting and POSTs only on explicit retry", async (status) => {
    const job = { jobId: "failed-job", status, attemptCount: 1, code: "MODEL_ERROR", message: "model detail" }
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(json(job)))
    const api = createReaderAdapter(fetcher)
    const context = { articleId: "article-1", onProgress: vi.fn() }
    await expect(api.translate(translationInput, undefined, context)).rejects.toMatchObject({ code: "MODEL_ERROR", message: "model detail", jobStatus: status })
    await expect(createReaderAdapter(fetcher).translate(translationInput, undefined, context)).rejects.toMatchObject({ jobStatus: status })
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/reader/translate/failed-job", expect.objectContaining({ method: "GET" }))
    expect(context.onProgress).toHaveBeenLastCalledWith(expect.objectContaining({ status }))
    fetcher.mockImplementation(() => Promise.resolve(json({ ...completedJob, attemptCount: 2 })))
    await expect(api.translate({ ...translationInput, retry: true }, undefined, context)).resolves.toMatchObject({ translated: "译文" })
    expect(fetcher).toHaveBeenNthCalledWith(3, "/api/v1/reader/translate", expect.objectContaining({ method: "POST", body: JSON.stringify({ ...translationInput, retry: true }) }))
  })

  it("preserves the upstream rate-limit status from a failed job", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({
      jobId: "rate-limited-job", status: "failed", attemptCount: 1,
      code: "MAGPIE_UNAVAILABLE", message: "免费翻译路由暂不可用。", errorStatus: 429,
    }))
    await expect(createReaderAdapter(fetcher).translate(translationInput)).rejects.toMatchObject({
      status: 429, code: "MAGPIE_UNAVAILABLE", jobStatus: "failed",
    })
  })

  it("isolates saved jobs by article, content hash, locale and source language", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(json(completedJob)))
    const api = createReaderAdapter(fetcher)
    await api.translate(translationInput, undefined, { articleId: "a" })
    await api.translate(translationInput, undefined, { articleId: "b" })
    await api.translate({ ...translationInput, contentHash: "new-hash" }, undefined, { articleId: "a" })
    await api.translate({ ...translationInput, targetLang: "ja" }, undefined, { articleId: "a" })
    await api.translate({ ...translationInput, sourceLang: "fr" }, undefined, { articleId: "a" })
    await api.translate(translationInput, undefined, { articleId: "a" })
    expect(fetcher.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(5)
    expect(fetcher).toHaveBeenLastCalledWith("/api/v1/reader/translate/job-1", expect.objectContaining({ method: "GET" }))
  })

  it("works when sessionStorage is unavailable and accepts optional success metadata", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError") })
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError") })
    const fetcher = vi.fn().mockResolvedValue(json({ jobId: "job-1", status: "succeeded", attemptCount: 1, translated: "译文", lang: "zh" }))
    await expect(createReaderAdapter(fetcher).translate(translationInput)).resolves.toEqual({ translated: "译文", lang: "zh", cached: false, provider: "" })
  })

  it.each([
    { ...completedJob, status: "unknown" },
    { ...completedJob, jobId: "" },
    { ...completedJob, attemptCount: -1 },
    { ...completedJob, translated: "" },
    { jobId: "job-1", status: "failed", attemptCount: 1 },
  ])("rejects invalid translation jobs: %j", async (job) => {
    await expect(createReaderAdapter(vi.fn().mockResolvedValue(json(job))).translate(translationInput)).rejects.toMatchObject({ code: "INVALID_READER_RESPONSE" })
  })

  it("does not submit when already aborted", async () => {
    const controller = new AbortController()
    controller.abort()
    const fetcher = vi.fn()
    await expect(createReaderAdapter(fetcher).translate(translationInput, controller.signal)).rejects.toMatchObject({ name: "AbortError" })
    expect(fetcher).not.toHaveBeenCalled()
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

  it.each(["translate-failed", "translate-timed-out"])("mock reports real states and supports explicit retry for %s", async (state) => {
    vi.useFakeTimers()
    const api = createMockReaderAdapter(state)
    const progress = vi.fn()
    const pending = api.translate(translationInput, undefined, { onProgress: progress })
    const failed = expect(pending).rejects.toMatchObject({ jobStatus: state === "translate-failed" ? "failed" : "timed_out" })
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "queued" }))
    await vi.advanceTimersByTimeAsync(40)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "running" }))
    await vi.advanceTimersByTimeAsync(120)
    await failed
    const retry = api.translate({ ...translationInput, retry: true }, undefined, { onProgress: progress })
    await vi.advanceTimersByTimeAsync(160)
    await expect(retry).resolves.toMatchObject({ lang: "zh" })
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ status: "succeeded", attemptCount: 2 }))
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
