import { useEffect, useRef, useState } from "react"

import { LocaleChips } from "./LocaleChips"
import { ModeToggle, type ContentMode } from "./ModeToggle"
import { ReaderBody } from "./ReaderBody"
import { ReaderMeta } from "./ReaderMeta"
import { createReaderAdapter, safeReaderLink } from "@/lib/reader/adapter"
import { saveLocale, type ReaderLocale } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"
import { readerPath, type parseReaderRoute, type ReaderMode } from "@/lib/reader/routes"
import { ReaderApiError, type ReaderAdapter, type ReaderArticle, type ReaderTranslationStatus } from "@/lib/reader/types"
import "./reader.css"

type ReaderRoute = NonNullable<ReturnType<typeof parseReaderRoute>>

function feedPath(route: ReaderRoute) {
  const returnTo = route.params.get("return_to")
  return returnTo?.startsWith("/public-app/") ? returnTo : "/public-app/"
}

function ReaderFeedback({ locale }: { locale: ReaderLocale }) {
  return <a className="reader-source-link" href="https://github.com/XucroYuri/NewsSentry/issues/new" target="_blank" rel="noopener noreferrer">{messages[locale].feedback}</a>
}

function errorCopy(error: unknown, locale: ReaderLocale, preview = false) {
  const text = messages[locale]
  if (error instanceof ReaderApiError) {
    if (error.status === 403) return text.accessRequired
    if (error.status === 429) return text.rateLimited
    if (error.code === "READER_DISABLED") return text.disabled
    if (error.jobStatus === "timed_out") return text.translationTimedOut
  }
  return preview ? text.previewFailed : text.translationFailed
}

export function ReaderView({ route, adapter, demo = false }: { route: ReaderRoute; adapter: ReaderAdapter; demo?: boolean }) {
  const [locale, setLocale] = useState(route.locale)
  const [mode, setMode] = useState<ContentMode>("translated")
  const [article, setArticle] = useState<ReaderArticle | null>(null)
  const [translations, setTranslations] = useState<Partial<Record<ReaderLocale, string>>>({})
  const [previewLoading, setPreviewLoading] = useState(true)
  const [translating, setTranslating] = useState(false)
  const [translationStatus, setTranslationStatus] = useState<ReaderTranslationStatus | null>(null)
  const [previewError, setPreviewError] = useState<unknown>(null)
  const [translationError, setTranslationError] = useState<unknown>(null)
  const [previewAttempt, setPreviewAttempt] = useState(0)
  const [translationAttempt, setTranslationAttempt] = useState(0)
  const retryRequested = useRef(false)
  const text = messages[locale]
  const busy = previewLoading || translating
  const sourceUrl = article?.sourceUrl ?? route.params.get("url") ?? ""
  const source = route.params.get("source") || (safeReaderLink(sourceUrl) ? new URL(safeReaderLink(sourceUrl)!).hostname : "")
  const publishedAt = demo ? "2026-11-05T06:20:00Z" : route.params.get("published_at")
  const title = article?.title || route.params.get("title") || text.reader
  const hasTranslation = mode === "translated" && Boolean(translations[locale])
  const markdown = hasTranslation ? translations[locale]! : article?.markdown ?? ""
  const language = hasTranslation ? locale : article?.lang || locale

  useEffect(() => {
    const controller = new AbortController()
    setPreviewLoading(true)
    setPreviewError(null)
    setArticle(null)
    setTranslations({})
    adapter.preview({ articleId: route.articleId }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setArticle(result)
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setPreviewError(error)
    }).finally(() => {
      if (!controller.signal.aborted) setPreviewLoading(false)
    })
    return () => controller.abort()
  }, [adapter, route.articleId, previewAttempt])

  useEffect(() => {
    if (!article || mode === "original" || translations[locale]) {
      setTranslating(false)
      return
    }
    const controller = new AbortController()
    const retry = retryRequested.current
    retryRequested.current = false
    setTranslating(true)
    setTranslationStatus(null)
    setTranslationError(null)
    adapter.translate(
      { markdown: article.markdown, contentHash: article.contentHash, sourceLang: article.lang, targetLang: locale, ...(retry ? { retry: true } : {}) },
      controller.signal,
      { articleId: route.articleId, onProgress: (job) => { if (!controller.signal.aborted) setTranslationStatus(job.status) } },
    ).then((result) => {
      if (!controller.signal.aborted) setTranslations((current) => ({ ...current, [locale]: result.translated }))
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setTranslationError(error)
        setMode("original")
      }
    }).finally(() => {
      if (!controller.signal.aborted) setTranslating(false)
    })
    return () => controller.abort()
  }, [adapter, article, locale, mode, translations, translationAttempt, route.articleId])

  useEffect(() => {
    const root = document.documentElement
    const previous = { lang: root.lang, dir: root.dir, title: document.title }
    root.lang = locale
    root.dir = locale === "ar" ? "rtl" : "ltr"
    document.title = `${title} · News Sentry`
    window.history.replaceState(window.history.state, "", readerPath(route.articleId, locale, route.params))
    return () => { root.lang = previous.lang; root.dir = previous.dir; document.title = previous.title }
  }, [locale, title, route.articleId, route.params])

  function changeLocale(next: ReaderLocale) {
    if (busy) return
    saveLocale(next)
    if (next === locale) return
    setLocale(next)
    setMode("translated")
    setTranslationError(null)
    if (article && !translations[next]) setTranslating(true)
  }

  return (
    <main className="reader-shell" dir={locale === "ar" ? "rtl" : "ltr"} lang={locale}>
      <nav className="reader-nav" aria-label={text.reader}>
        <a className="reader-brand" href="/public-app/">News<span>Sentry</span></a>
        <a href={feedPath(route)}>{text.back}</a>
        <ReaderFeedback locale={locale} />
        {demo ? <span className="reader-chip">{text.demo}</span> : null}
      </nav>
      <header className="reader-card reader-top">
        <h1 dir="auto">{title}</h1>
        <div className="reader-byline"><span dir="auto">{source || text.source}</span><span>{publishedAt && !Number.isNaN(Date.parse(publishedAt)) ? <time dateTime={publishedAt}>{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(publishedAt))}</time> : text.unavailable}</span></div>
        <div className="reader-toolbar">
          <LocaleChips locale={locale} disabled={busy} onChange={changeLocale} />
          <ModeToggle locale={locale} mode={mode} disabled={busy || !article} onChange={(next) => { if (!busy) setMode(next) }} />
          <span className="reader-chip reader-mt">MT · {text.mt}</span>
        </div>
      </header>
      <div className="reader-layout">
        <section className="reader-card reader-content" aria-label={text.reader}>
          {previewError ? <div className="reader-error" role="alert"><p>{errorCopy(previewError, locale, true)}</p><button className="reader-button" type="button" onClick={() => setPreviewAttempt(previewAttempt + 1)}>{text.retry}</button></div> : null}
          {translationError ? <div className="reader-error" role="alert"><p>{errorCopy(translationError, locale)}</p><button className="reader-button" type="button" disabled={busy} onClick={() => { retryRequested.current = true; setMode("translated"); setTranslationAttempt(translationAttempt + 1) }}>{text.retry}</button></div> : null}
          <ReaderBody markdown={markdown} images={article?.images ?? []} locale={locale} language={language} busy={busy} loadingLabel={previewLoading ? text.previewLoading : translationStatus === "queued" ? text.translationQueued : translationStatus === "running" ? text.translationRunning : text.translationSubmitting} />
        </section>
        <ReaderMeta locale={locale} source={source} sourceUrl={sourceUrl} language={language} publishedAt={publishedAt} articleId={route.articleId} attribution={article?.attribution} />
      </div>
    </main>
  )
}

export default function ReaderPage({ route, mode }: { route: ReaderRoute; mode: ReaderMode }) {
  const [adapter, setAdapter] = useState<ReaderAdapter | null>(null)
  const [loadError, setLoadError] = useState(false)
  const state = route.params.get("readerState") ?? ""
  useEffect(() => {
    let cancelled = false
    if (mode === "live") setAdapter(createReaderAdapter())
    if (mode === "mock") {
      import("@/lib/reader/mock-adapter").then(({ createMockReaderAdapter }) => {
        if (!cancelled) setAdapter(createMockReaderAdapter(state))
      }).catch(() => { if (!cancelled) setLoadError(true) })
    }
    return () => { cancelled = true }
  }, [mode, state])
  if (mode === "off") {
    const sourceUrl = safeReaderLink(route.params.get("url") ?? "")
    return <main className="reader-shell" lang={route.locale} dir={route.locale === "ar" ? "rtl" : "ltr"}>
      <h1>{messages[route.locale].disabled}</h1>
      <a href={feedPath(route)}>{messages[route.locale].back}</a>
      <p><ReaderFeedback locale={route.locale} /></p>
      {sourceUrl ? <p><a className="reader-source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">{messages[route.locale].openSource}</a></p> : null}
    </main>
  }
  if (!adapter) return <main className="reader-shell" role="status">{loadError ? messages[route.locale].previewFailed : messages[route.locale].previewLoading}</main>
  return <ReaderView key={route.articleId} route={route} adapter={adapter} demo={mode === "mock"} />
}
