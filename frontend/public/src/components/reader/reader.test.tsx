import "@testing-library/jest-dom/vitest"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { LocaleChips } from "./LocaleChips"
import { ModeToggle } from "./ModeToggle"
import { ProxyImage } from "./ProxyImage"
import { ReaderBody } from "./ReaderBody"
import ReaderPage, { ReaderView } from "./ReaderPage"
import { mockArticle, mockImageUrl } from "@/lib/reader/mock-adapter"
import { parseReaderRoute } from "@/lib/reader/routes"
import { ReaderApiError, type ReaderAdapter, type ReaderTranslation } from "@/lib/reader/types"

const route = (locale = "zh") => parseReaderRoute({ pathname: `/${locale}/reader/demo`, search: `?locale=${locale}` })!
const translated = { translated: "## 译文标题\n\n完整译文内容。", lang: "zh", cached: false, provider: "test" }
const adapter = (): ReaderAdapter => ({ preview: vi.fn().mockResolvedValue(mockArticle), translate: vi.fn().mockResolvedValue(translated) })

afterEach(() => { cleanup(); localStorage.clear(); window.history.replaceState({}, "", "/"); vi.restoreAllMocks() })

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
    expect(api.translate).toHaveBeenCalledWith(expect.objectContaining({ targetLang: expected }), expect.any(AbortSignal))
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
    expect(api.translate).toHaveBeenCalledWith(expect.objectContaining({ targetLang: "ar" }), expect.any(AbortSignal))
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
    expect(screen.getByRole("status", { name: "正在翻译…" })).toBeVisible()
    for (const button of container.querySelectorAll(".reader-toolbar button")) expect(button).toBeDisabled()
    expect(container.querySelector(".reader-body")).toHaveStyle({ visibility: "hidden" })
    finish(translated)
    expect(await screen.findByText("完整译文内容。")).toBeVisible()
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
