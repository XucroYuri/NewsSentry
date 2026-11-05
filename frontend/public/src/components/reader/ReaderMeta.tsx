import { safeReaderLink } from "@/lib/reader/adapter"
import { asReaderLocale, localeInfo, type ReaderLocale } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"

export function ReaderMeta({ locale, source, sourceUrl, language, publishedAt, articleId, attribution }: {
  locale: ReaderLocale
  source: string
  sourceUrl: string
  language: string
  publishedAt?: string | null
  articleId: string
  attribution?: string
}) {
  const text = messages[locale]
  const href = safeReaderLink(sourceUrl)
  const languageCode = asReaderLocale(language)
  const date = publishedAt ? new Date(publishedAt) : null
  return (
    <aside className="reader-aside" aria-label={text.meta}>
      <section className="reader-card reader-meta">
        <h2>{text.meta}</h2>
        <dl>
          <dt>{text.source}</dt><dd dir="auto">{source || text.unavailable}</dd>
          <dt>{text.language}</dt><dd>{languageCode ? localeInfo[languageCode].name : language || text.unavailable}</dd>
          <dt>{text.time}</dt><dd>{date && !Number.isNaN(date.getTime()) ? <time dateTime={date.toISOString()}>{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date)}</time> : text.unavailable}</dd>
          <dt>{text.articleId}</dt><dd className="reader-id" dir="ltr">{articleId}</dd>
        </dl>
      </section>
      {href ? <a className="reader-source-link" href={href} target="_blank" rel="noopener noreferrer">{text.openSource}<span aria-hidden="true"> ↗</span></a> : null}
      <section className="reader-card reader-note">
        <p>{text.disclaimer}</p>
        {attribution ? <p className="reader-attribution" dir="auto">{attribution}</p> : null}
      </section>
    </aside>
  )
}
