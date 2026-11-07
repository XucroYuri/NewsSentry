import "@testing-library/jest-dom/vitest"
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { LocaleChips } from "./LocaleChips"
import { ModeToggle } from "./ModeToggle"
import { ProxyImage } from "./ProxyImage"
import { ReaderBody } from "./ReaderBody"
import ReaderPage, { ReaderView } from "./ReaderPage"
import { createReaderAdapter } from "@/lib/reader/adapter"
import { mockArticle, mockImageUrl } from "@/lib/reader/mock-adapter"
import { readerLocales } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"
import { parseReaderRoute } from "@/lib/reader/routes"
import { ReaderApiError, type ReaderAdapter, type ReaderTranslation, type TranslationContext } from "@/lib/reader/types"

const route = (locale = "zh") => parseReaderRoute({ pathname: `/${locale}/reader/demo`, search: `?locale=${locale}` })!
const translated = { translated: "## 译文标题\n\n完整译文内容。", lang: "zh", cached: false, provider: "test" }
const adapter = (): ReaderAdapter => ({ preview: vi.fn().mockResolvedValue(mockArticle), translate: vi.fn().mockResolvedValue(translated) })

afterEach(() => { cleanup(); localStorage.clear(); sessionStorage.clear(); window.history.replaceState({}, "", "/"); vi.restoreAllMocks() })

describe("Reader controls", () => {
  it("shows exactly ten SVG and language-code chips with endonym labels", () => {
    const change = vi.fn()
    const { container } = render(<LocaleChips locale="zh" onChange={change} />)
    expect(screen.getAllByRole("button")).toHaveLength(10)
    expect(container.querySelectorAll('img[src$=".svg"][loading="lazy"]')).toHaveLength(10)
    expect(screen.getByRole("button", { name: "JA · 日本語" })).toHaveTextContent("JA")
    fireEvent.click(screen.getByRole("button", { name: "AR · العربية" }))
    expect(change).toHaveBeenCalledWith("ar")
  })

  it("disables all chips and both modes during translation", () => {
    const change = vi.fn()
    render(<><LocaleChips locale="zh" disabled onChange={change} /><ModeToggle locale="zh" mode="translated" disabled onChange={change} /></>)
    for (const button of screen.getAllByRole("button")) { expect(button).toBeDisabled(); fireEvent.click(button) }
    expect(change).not.toHaveBeenCalled()
  })
})

describe("Reader safe body", () => {
  it("decodes text entities without activating encoded HTML or changing code spans", () => {
    const markdown = 'AT&amp;T&nbsp;News &copy; &#65; &#x42;\n\n&lt;img src=x onerror=alert(1)&gt;\n\n`&amp;`\n\n[source](https://example.com/?a=1&amp;b=2)'
    const { container } = render(<ReaderBody markdown={markdown} images={[]} locale="en" language="en" loadingLabel="Loading" />)
    expect(container.querySelector(".reader-body")?.textContent).toContain("AT&T News © A B")
    expect(container.querySelector(".reader-body")?.textContent).toContain("<img src=x onerror=alert(1)>")
    expect(container.querySelector("img, script")).toBeNull()
    expect(container.querySelector("code")).toHaveTextContent("&amp;")
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://example.com/?a=1&b=2")
  })

  it("replaces image errors without ever loading original src", () => {
    const { container } = render(<ProxyImage proxyUrl={mockImageUrl} alt="Harbour" locale="zh" />)
    expect(screen.getByRole("img")).toHaveAttribute("src", mockImageUrl)
    fireEvent.error(screen.getByRole("img"))
    expect(screen.getByText("图片暂时无法显示")).toBeVisible()
    expect(container.querySelector("img")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    expect(screen.getByRole("img")).toHaveAttribute("src", mockImageUrl)
  })

  it("drops raw HTML, unsafe links and images absent from the signed manifest", () => {
    const markdown = `<script>alert(1)</script>\n\n<iframe src='https://evil.test'></iframe>\n\n[bad](javascript:alert%281%29)\n\n![hotlink](https://evil.test/a.png)\n\n![proxy](${mockImageUrl})\n\n**Safe** [source](https://example.com)\n\n- item\n\n| Column |\n| --- |\n| Value |`
    const { container } = render(<ReaderBody markdown={markdown} images={mockArticle.images} locale="zh" language="en" loadingLabel="加载" />)
    expect(container.querySelector("script, iframe")).toBeNull()
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
    expect(screen.getAllByRole("img")).toHaveLength(1)
    expect(screen.getByRole("img")).toHaveAttribute("src", mockImageUrl)
    expect(screen.getByText("Safe").tagName).toBe("STRONG")
    expect(screen.getByRole("table")).toHaveTextContent("Value")
  })
})

describe("Reader states", () => {
  it.each([
    { saved: "ja", languages: ["pt-BR", "en-US"], language: "pt-BR", expected: "ja" },
    { saved: null, languages: ["zh-CN", "en-US"], language: "zh-CN", expected: "zh" },
    { saved: null, languages: ["nl-NL", "pt-BR", "en-US"], language: "nl-NL", expected: "pt" },
    { saved: null, languages: ["en-US"], language: "en-US", expected: "en" },
    { saved: "invalid", languages: ["fr-CA"], language: "fr-CA", expected: "fr" },
    { saved: null, languages: [], language: "de-DE", expected: "de" },
    { saved: null, languages: ["nl-NL"], language: "nl-NL", expected: "en" },
  ])("auto-picks $expected from saved=$saved and browser=$languages and requests translation", async ({ saved, languages, language, expected }) => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(languages)
    vi.spyOn(navigator, "language", "get").mockReturnValue(language)
    if (saved) localStorage.setItem("news-sentry-reader-locale", saved)
    const api = adapter()
    const input = parseReaderRoute({ pathname: "/reader/demo", search: "" })!
    const { container } = render(<ReaderView route={input} adapter={api} />)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(api.translate).toHaveBeenCalledWith(expect.objectContaining({ targetLang: expected }), expect.any(AbortSignal), expect.objectContaining({ articleId: "demo", onProgress: expect.any(Function) }))
    expect(container.querySelector("main")).toHaveAttribute("lang", expected)
    expect(container.querySelector(".reader-mode button:last-child")).toHaveAttribute("aria-pressed", "true")
    expect(window.location.pathname).toBe(`/${expected}/reader/demo`)
    expect(new URLSearchParams(window.location.search).get("locale")).toBe(expected)
    expect(localStorage.getItem("news-sentry-reader-locale")).toBe(saved)
  })

  it("uses browser preference when localStorage access is denied", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError") })
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["ar-SA"])
    const api = adapter()
    render(<ReaderView route={parseReaderRoute({ pathname: "/reader/demo", search: "" })!} adapter={api} />)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(api.translate).toHaveBeenCalledWith(expect.objectContaining({ targetLang: "ar" }), expect.any(AbortSignal), expect.objectContaining({ articleId: "demo" }))
  })

  it("loads translated by default and reversibly toggles without duplicate requests", async () => {
    const api = adapter()
    render(<ReaderView route={route()} adapter={api} />)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    fireEvent.click(screen.getByRole("button", { name: "原文" }))
    expect(screen.getByRole("heading", { name: "Background: pressure on the shipping corridor", level: 2 })).toBeVisible()
    fireEvent.click(screen.getByRole("button", { name: "译文" }))
    expect(screen.getByText("完整译文内容。")).toBeVisible()
    expect(api.translate).toHaveBeenCalledTimes(1)
  })

  it("holds body space and disables duplicate actions while translation is pending", async () => {
    let finish!: (value: ReaderTranslation) => void
    const api = adapter()
    api.translate = vi.fn(() => new Promise<ReaderTranslation>((resolve) => { finish = resolve }))
    const { container } = render(<ReaderView route={route()} adapter={api} />)
    await waitFor(() => expect(api.translate).toHaveBeenCalledTimes(1))
    expect(screen.getByRole("status", { name: "正在提交翻译任务…" })).toBeVisible()
    for (const button of container.querySelectorAll(".reader-toolbar button")) expect(button).toBeDisabled()
    expect(container.querySelector(".reader-body")).toHaveStyle({ visibility: "hidden" })
    finish(translated)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
  })

  it("renders queued and running states from progress callbacks without invented progress", async () => {
    let context: TranslationContext | undefined
    let finish!: (value: ReaderTranslation) => void
    const api = adapter()
    api.translate = vi.fn((_input, _signal, progress) => {
      context = progress
      progress?.onProgress?.({ jobId: "ui-job", status: "queued", attemptCount: 0 })
      return new Promise<ReaderTranslation>((resolve) => { finish = resolve })
    })
    const { container } = render(<ReaderView route={route()} adapter={api} />)
    expect(await screen.findByRole("status", { name: "翻译任务排队中…" })).toBeVisible()
    act(() => context?.onProgress?.({ jobId: "ui-job", status: "running", attemptCount: 1 }))
    expect(screen.getByRole("status", { name: "正在翻译…" })).toBeVisible()
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
    act(() => finish(translated))
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
  })

  it.each(["failed", "timed_out"] as const)("keeps the original after %s and retries with retry:true", async (status) => {
    const api = adapter()
    api.translate = vi.fn()
      .mockRejectedValueOnce(new ReaderApiError(503, "MODEL_ERROR", "detail", status))
      .mockResolvedValue(translated)
    render(<ReaderView route={route()} adapter={api} />)
    expect(await screen.findByRole("alert")).toHaveTextContent(status === "timed_out" ? "翻译任务已超时" : "翻译暂不可用")
    expect(screen.getByRole("heading", { name: "Background: pressure on the shipping corridor", level: 2 })).toBeVisible()
    expect(api.translate).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(api.translate).toHaveBeenLastCalledWith(expect.objectContaining({ retry: true }), expect.any(AbortSignal), expect.objectContaining({ articleId: "demo" }))
    expect(screen.queryByRole("alert")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "JA · 日本語" }))
    await waitFor(() => expect(api.translate).toHaveBeenCalledTimes(3))
    expect(api.translate).toHaveBeenLastCalledWith(expect.not.objectContaining({ retry: true }), expect.any(AbortSignal), expect.any(Object))
  })

  it.each(readerLocales)("shows true chunk progress in %s without estimating from attempts or time", async (locale) => {
    let context: TranslationContext | undefined
    let finish!: (value: ReaderTranslation) => void
    const api = adapter()
    api.translate = vi.fn((_input, _signal, progress) => {
      context = progress
      progress?.onProgress?.({ jobId: "chunks-ui", status: "queued", attemptCount: 0, completedChunks: 0, totalChunks: 4 })
      return new Promise<ReaderTranslation>((resolve) => { finish = resolve })
    })
    render(<ReaderView route={route(locale)} adapter={api} />)
    const label = (completed: number) => messages[locale].translationProgress.replace("{completed}", String(completed)).replace("{total}", "4")
    expect(await screen.findByRole("status", { name: `${messages[locale].translationQueued} ${label(0)}` })).toBeVisible()
    act(() => context?.onProgress?.({ jobId: "chunks-ui", status: "running", attemptCount: 1, completedChunks: 2, totalChunks: 4 }))
    expect(screen.getByRole("status")).toHaveTextContent(label(2))
    act(() => context?.onProgress?.({ jobId: "chunks-ui", status: "running", attemptCount: 2, completedChunks: 2, totalChunks: 4 }))
    expect(screen.getByRole("status")).toHaveTextContent(label(2))
    act(() => context?.onProgress?.({ jobId: "chunks-ui", status: "running", attemptCount: 2, completedChunks: 3, totalChunks: 4 }))
    expect(screen.getByRole("status")).toHaveTextContent(label(3))
    act(() => finish({ ...translated, lang: locale }))
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(screen.queryByRole("status")).toBeNull()
  })

  it.each(readerLocales)("requires clicking the localized resubmit action after a restored 404 in %s", async (locale) => {
    const key = `news-sentry-reader-job:v1:${JSON.stringify(["demo", mockArticle.contentHash, locale, mockArticle.lang])}`
    sessionStorage.setItem(key, "other-account-or-missing-job")
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
    const fetcher = vi.fn().mockImplementation((path: string) => {
      if (path.endsWith("/preview")) return Promise.resolve(json(mockArticle))
      if (path.endsWith("/other-account-or-missing-job")) return Promise.resolve(json({ code: "NOT_FOUND" }, 404))
      if (path.endsWith("/translate")) return Promise.resolve(json({ jobId: "new-job", status: "succeeded", attemptCount: 1, ...translated, lang: locale }))
      throw new Error(`Unexpected request: ${path}`)
    })
    const first = render(<ReaderView route={route(locale)} adapter={createReaderAdapter(fetcher)} />)
    expect(await screen.findByRole("alert")).toHaveTextContent(messages[locale].translationJobUnavailable)
    expect(screen.getByRole("heading", { name: "Background: pressure on the shipping corridor", level: 2 })).toBeVisible()
    expect(screen.getByRole("button", { name: messages[locale].resubmitTranslation })).toBeEnabled()
    expect(sessionStorage.getItem(key)).toBeNull()
    expect(fetcher.mock.calls.filter(([, init]) => init.method === "GET")).toHaveLength(1)
    expect(fetcher.mock.calls.filter(([path]) => path === "/api/v1/reader/translate")).toHaveLength(0)
    fireEvent.click(screen.getByRole("button", { name: messages[locale].translated }))
    await waitFor(() => expect(screen.getByRole("button", { name: messages[locale].original })).toHaveAttribute("aria-pressed", "true"))
    expect(fetcher).toHaveBeenCalledTimes(2)

    first.unmount()
    render(<ReaderView route={route(locale)} adapter={createReaderAdapter(fetcher)} />)
    expect(await screen.findByRole("alert")).toHaveTextContent(messages[locale].translationJobUnavailable)
    expect(fetcher).toHaveBeenCalledTimes(3)
    fireEvent.click(screen.getByRole("button", { name: messages[locale].resubmitTranslation }))
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(screen.queryByRole("alert")).toBeNull()
    expect(fetcher.mock.calls.filter(([path]) => path === "/api/v1/reader/translate")).toHaveLength(1)
    expect(fetcher).toHaveBeenLastCalledWith("/api/v1/reader/translate", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ markdown: mockArticle.markdown, contentHash: mockArticle.contentHash, sourceLang: mockArticle.lang, targetLang: locale, retry: true }),
    }))
  })

  it("restores a queued translation after remount with GET and no new POST", async () => {
    const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } })
    const fetcher = vi.fn().mockImplementation((path: string) => {
      if (path.endsWith("/preview")) return Promise.resolve(json(mockArticle))
      if (path.endsWith("/translate")) return Promise.resolve(json({ jobId: "restored-ui-job", status: "queued", attemptCount: 0 }))
      return Promise.resolve(json({ jobId: "restored-ui-job", status: "succeeded", attemptCount: 1, ...translated }))
    })
    const first = render(<ReaderView route={route()} adapter={createReaderAdapter(fetcher)} />)
    expect(await screen.findByRole("status", { name: "翻译任务排队中…" })).toBeVisible()
    first.unmount()
    const restoredApi = createReaderAdapter(fetcher)
    render(<ReaderView route={route()} adapter={restoredApi} />)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
    expect(fetcher.mock.calls.filter(([path]) => path === "/api/v1/reader/translate")).toHaveLength(1)
    expect(fetcher).toHaveBeenCalledWith("/api/v1/reader/translate/restored-ui-job", expect.objectContaining({ method: "GET", credentials: "same-origin" }))
  })

  it("aborts the translation signal on unmount and ignores late progress", async () => {
    let signal: AbortSignal | undefined
    let context: TranslationContext | undefined
    const api = adapter()
    api.translate = vi.fn((_input, abortSignal, progress) => {
      signal = abortSignal
      context = progress
      return new Promise<ReaderTranslation>(() => undefined)
    })
    const { unmount } = render(<ReaderView route={route()} adapter={api} />)
    await waitFor(() => expect(api.translate).toHaveBeenCalledTimes(1))
    expect(signal?.aborted).toBe(false)
    unmount()
    expect(signal?.aborted).toBe(true)
    expect(() => context?.onProgress?.({ jobId: "late", status: "running", attemptCount: 1 })).not.toThrow()
  })

  it("keeps original and shows a clear retry fallback for translation 503", async () => {
    const api = adapter()
    api.translate = vi.fn().mockRejectedValue(new ReaderApiError(503, "TRANSLATION_UNAVAILABLE", "unavailable"))
    render(<ReaderView route={route()} adapter={api} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("翻译暂不可用")
    expect(screen.getByRole("button", { name: "原文" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("heading", { name: "Background: pressure on the shipping corridor", level: 2 })).toBeVisible()
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled()
  })

  it("uses RTL on document, shell and body, and persists selected locale in URL and storage", async () => {
    const api = adapter()
    api.translate = vi.fn().mockResolvedValue({ ...translated, translated: "## العنوان\n\nالنص العربي", lang: "ar" })
    const { container } = render(<ReaderView route={route("ar")} adapter={api} />)
    expect(await screen.findByText("النص العربي")).toBeVisible()
    expect(document.documentElement).toHaveAttribute("dir", "rtl")
    expect(container.querySelector("main")).toHaveAttribute("dir", "rtl")
    expect(container.querySelector("article")).toHaveAttribute("dir", "rtl")
    expect(window.location.pathname).toBe("/ar/reader/demo")
    expect(window.location.search).toContain("locale=ar")
    expect(localStorage.getItem("news-sentry-reader-locale")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "JA · 日本語" }))
    await waitFor(() => expect(window.location.pathname).toBe("/ja/reader/demo"))
    expect(localStorage.getItem("news-sentry-reader-locale")).toBe("ja")
    expect(within(screen.getByRole("group", { name: "表示モード" })).getByRole("button", { name: "原文" })).toBeEnabled()
  })

  it("off mode makes no reader API requests and renders no database full content", () => {
    const fetcher = vi.spyOn(globalThis, "fetch")
    render(<ReaderPage route={route()} mode="off" />)
    expect(screen.getByRole("heading")).toHaveTextContent("站内阅读尚未开放")
    expect(fetcher).not.toHaveBeenCalled()
  })

  it("preview Access errors keep a source link and a retry action", async () => {
    const api = adapter()
    api.preview = vi.fn().mockRejectedValue(new ReaderApiError(403, "ACCESS_REQUIRED", "access"))
    const input = route()
    input.params.set("url", "https://example.com/article")
    render(<ReaderView route={input} adapter={api} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("访问会话")
    expect(screen.getByRole("link", { name: /在源站打开/ })).toHaveAttribute("href", "https://example.com/article")
    expect(api.translate).not.toHaveBeenCalled()
  })
})
