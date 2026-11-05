import { useState } from "react"

import { safeProxyUrl } from "@/lib/reader/adapter"
import type { ReaderLocale } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"

export function ProxyImage({ proxyUrl, alt, locale, priority = false }: { proxyUrl: string; alt: string; locale: ReaderLocale; priority?: boolean }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const url = safeProxyUrl(proxyUrl)
  const failed = !url || failedUrl === url
  const text = messages[locale]

  return (
    <span className="reader-figure">
      <span className="reader-image-frame">
        {failed ? (
          <span className="reader-image-failed" role="status">
            <strong>{text.imageFailed}</strong>
            <span>{text.imageHint}</span>
            {url ? <button type="button" className="reader-button" onClick={() => { setFailedUrl(null); setAttempt(attempt + 1) }}>{text.retry}</button> : null}
          </span>
        ) : (
          <img key={`${url}:${attempt}`} src={url} alt={alt} width="960" height="540" loading={priority ? "eager" : "lazy"} fetchPriority={priority ? "high" : "auto"} decoding="async" referrerPolicy="no-referrer" onError={() => setFailedUrl(url)} />
        )}
      </span>
      <span className="reader-caption">{alt || text.caption}</span>
    </span>
  )
}
