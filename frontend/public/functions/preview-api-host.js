/** Preview Pages 上哪些主机可以把 /api 交给 preview Worker。生产主机一律排除。 */

const PRODUCTION_HOSTS = new Set([
  "news-sentry.com",
  "www.news-sentry.com",
  "api.news-sentry.com",
  "news-sentry.pages.dev",
])

const PREVIEW_PAGES_SUFFIX = ".news-sentry.pages.dev"

export function previewApiProxyHost(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/\.$/, "")
  if (PRODUCTION_HOSTS.has(host)) return false
  if (host === "preview.news-sentry.com") return true
  return host.endsWith(PREVIEW_PAGES_SUFFIX)
}
