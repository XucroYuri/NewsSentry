import { Fragment, createElement, useMemo, type ReactNode } from "react"
import { marked, type Token } from "marked"

import { ProxyImage } from "./ProxyImage"
import { safeProxyUrl, safeReaderLink } from "@/lib/reader/adapter"
import type { ReaderLocale } from "@/lib/reader/locales"
import type { ReaderImage } from "@/lib/reader/types"

function decodeEntities(text: string) {
  return text.replace(/&(?:#x[\da-f]+|#\d+|[a-z][a-z\d]+);/gi, (entity) => {
    // 只解析单个实体，任何原始 HTML 都不交给浏览器。
    const textarea = document.createElement("textarea")
    textarea.innerHTML = entity
    return textarea.value
  })
}

function renderTokens(tokens: Token[], images: ReaderImage[], locale: ReaderLocale): ReactNode {
  return tokens.map((token, index) => {
    const children = () => renderTokens("tokens" in token ? token.tokens ?? [] : [], images, locale)
    let node: ReactNode
    switch (token.type) {
      case "heading": node = createElement(`h${Math.min(6, Math.max(2, token.depth))}`, null, children()); break
      case "paragraph": node = <p>{children()}</p>; break
      case "text": node = token.tokens ? children() : decodeEntities(token.text); break
      case "escape": node = token.text; break
      case "strong": node = <strong>{children()}</strong>; break
      case "em": node = <em>{children()}</em>; break
      case "del": node = <del>{children()}</del>; break
      case "codespan": node = <code>{token.text}</code>; break
      case "code": node = <pre><code>{token.text}</code></pre>; break
      case "blockquote": node = <blockquote>{children()}</blockquote>; break
      case "br": node = <br />; break
      case "hr": node = <hr />; break
      case "link": {
        const href = safeReaderLink(decodeEntities(token.href))
        node = href ? <a href={href} target="_blank" rel="noopener noreferrer">{children()}</a> : children()
        break
      }
      case "image": {
        const url = safeProxyUrl(decodeEntities(token.href))
        const image = url ? images.find((entry) => safeProxyUrl(entry.proxyUrl) === url) : undefined
        node = <ProxyImage proxyUrl={image?.proxyUrl ?? ""} alt={decodeEntities(token.text ?? image?.alt ?? "")} locale={locale} priority={Boolean(image && image === images[0])} />
        break
      }
      case "list": {
        const items = token.items.map((item: { tokens: Token[] }, key: number) => <li key={key}>{renderTokens(item.tokens, images, locale)}</li>)
        node = token.ordered ? <ol start={typeof token.start === "number" ? token.start : undefined}>{items}</ol> : <ul>{items}</ul>
        break
      }
      case "table":
        node = <div className="reader-table"><table><thead><tr>{token.header.map((cell: { tokens: Token[] }, key: number) => <th key={key}>{renderTokens(cell.tokens, images, locale)}</th>)}</tr></thead><tbody>{token.rows.map((row: { tokens: Token[] }[], key: number) => <tr key={key}>{row.map((cell, cellKey) => <td key={cellKey}>{renderTokens(cell.tokens, images, locale)}</td>)}</tr>)}</tbody></table></div>
        break
      // 原始 HTML、脚本、iframe 和未知 token 均不进入 DOM。
      default: node = null
    }
    return <Fragment key={index}>{node}</Fragment>
  })
}

export function ReaderBody({ markdown, images, locale, language, busy = false, loadingLabel }: {
  markdown: string
  images: ReaderImage[]
  locale: ReaderLocale
  language: string
  busy?: boolean
  loadingLabel: string
}) {
  const content = useMemo(() => renderTokens(marked.lexer(markdown), images, locale), [markdown, images, locale])
  return (
    <div className="reader-body-frame" aria-busy={busy}>
      <article className="reader-body" dir={locale === "ar" ? "rtl" : "ltr"} lang={language} aria-hidden={busy || undefined} inert={busy} style={busy ? { visibility: "hidden" } : undefined}>
        {content}
      </article>
      {busy ? <div className="reader-skeleton" role="status" aria-label={loadingLabel}>
        <span className="reader-loading-label">{loadingLabel}</span>
        <div aria-hidden="true">
          <div className="reader-skeleton-heading" />
          <div className="reader-skeleton-line" /><div className="reader-skeleton-line" /><div className="reader-skeleton-line" />
          <div className="reader-skeleton-image" />
          <div className="reader-skeleton-heading" />
          <div className="reader-skeleton-line" /><div className="reader-skeleton-line" /><div className="reader-skeleton-line" />
        </div>
      </div> : null}
    </div>
  )
}
