import type { PublicChannel } from "@/lib/feed-state"
import { buildPublicAppPath, type PublicRoute } from "@/lib/routes"
import type { PublicAnalysisResponse, PublicNewsItem } from "@/types/public-news"

const SITE_NAME = "News Sentry"
const DEFAULT_TITLE = "News Sentry Public"
const PUBLIC_APP_ROOT = "/public-app/"
const DEFAULT_DESCRIPTION =
  "News Sentry 公共新闻流提供面向读者的国际新闻摘要、来源脉络与目标监控视角。"
const MANAGED_ATTR = "data-news-sentry-seo"

export interface SiteSeoPayload {
  title: string
  description: string
  canonicalUrl: string
  ogType: "website" | "article"
  jsonLd?: Record<string, unknown>
}

export interface RouteSeoInput {
  origin: string
  route: PublicRoute
  selectedTargetLabel?: string | null
  analysis?: PublicAnalysisResponse | null
}

export function buildCanonicalUrl(origin: string, canonicalPath: string) {
  return new URL(canonicalPath, origin).toString()
}

export function buildRouteCanonicalPath(route: PublicRoute) {
  if (route.name === "feed") return PUBLIC_APP_ROOT
  return buildPublicAppPath(route)
}

export function buildEventSeoPayload({
  origin,
  route,
  item,
}: {
  origin: string
  route: Extract<PublicRoute, { name: "event" }>
  item?: PublicNewsItem | null
}): SiteSeoPayload | null {
  const effectiveTargetId = route.targetId ?? item?.targetId
  if (!effectiveTargetId) return null

  const canonicalRoute: Extract<PublicRoute, { name: "event" }> = {
    ...route,
    targetId: effectiveTargetId,
  }
  const canonicalUrl = buildCanonicalUrl(origin, buildRouteCanonicalPath(canonicalRoute))
  const title = item?.title ?? "新闻详情"
  const description =
    item?.summary ||
    item?.recommendationReason ||
    item?.originalTitle ||
    "查看 News Sentry 公共新闻流中的事件详情、来源信息与关联信号。"

  return {
    title: `${title} | ${SITE_NAME}`,
    description,
    canonicalUrl,
    ogType: "article",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "NewsArticle",
      headline: item?.title ?? title,
      description,
      datePublished: item?.publishedAt,
      dateModified: item?.publishedAt,
      mainEntityOfPage: canonicalUrl,
      articleSection: item?.tags?.[0],
      keywords: item?.tags?.join(", "),
      about: item?.entities.map((entity) => ({
        "@type": "Thing",
        name: entity.name,
      })),
      author: item?.source?.name
        ? {
            "@type": "Organization",
            name: item.source.name,
          }
        : undefined,
      publisher: {
        "@type": "Organization",
        name: SITE_NAME,
      },
      url: canonicalUrl,
    },
  }
}

export function buildRouteSeoPayload({
  origin,
  route,
  selectedTargetLabel,
  analysis,
}: RouteSeoInput): SiteSeoPayload {
  const canonicalUrl = buildCanonicalUrl(origin, buildRouteCanonicalPath(route))
  const page = pageCopy(route, selectedTargetLabel, analysis)

  return {
    title: `${page.title} | ${SITE_NAME}`,
    description: page.description,
    canonicalUrl,
    ogType: "website",
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: page.title,
      description: page.description,
      url: canonicalUrl,
      isPartOf: {
        "@type": "WebSite",
        name: SITE_NAME,
        url: buildCanonicalUrl(origin, PUBLIC_APP_ROOT),
      },
    },
  }
}

export function applySiteSeo(payload: SiteSeoPayload, doc: Document = document) {
  doc.title = payload.title

  upsertMeta(doc, "description", payload.description)
  upsertMeta(doc, "og:type", payload.ogType, "property")
  upsertMeta(doc, "og:site_name", SITE_NAME, "property")
  upsertMeta(doc, "og:title", payload.title, "property")
  upsertMeta(doc, "og:description", payload.description, "property")
  upsertMeta(doc, "og:url", payload.canonicalUrl, "property")
  upsertMeta(doc, "twitter:card", payload.ogType === "article" ? "summary_large_image" : "summary")
  upsertMeta(doc, "twitter:title", payload.title)
  upsertMeta(doc, "twitter:description", payload.description)
  upsertLink(doc, "canonical", payload.canonicalUrl)
  upsertJsonLd(doc, payload.jsonLd)
}

export function clearSiteSeo(doc: Document = document) {
  doc.title = DEFAULT_TITLE

  upsertMeta(doc, "description", DEFAULT_DESCRIPTION)
  upsertMeta(doc, "og:type", "website", "property")
  upsertMeta(doc, "og:site_name", SITE_NAME, "property")
  upsertMeta(doc, "og:title", DEFAULT_TITLE, "property")
  upsertMeta(doc, "og:description", DEFAULT_DESCRIPTION, "property")
  upsertMeta(doc, "twitter:card", "summary")
  upsertMeta(doc, "twitter:title", DEFAULT_TITLE)
  upsertMeta(doc, "twitter:description", DEFAULT_DESCRIPTION)
  removeManagedLink(doc, "canonical")
  removeManagedJsonLd(doc)
  removeManagedMeta(doc, "og:url", "property")
}

function pageCopy(
  route: PublicRoute,
  selectedTargetLabel?: string | null,
  analysis?: PublicAnalysisResponse | null,
) {
  if (route.name === "daily") {
    return {
      title: route.date ? `${route.date} 日报` : "今日日报",
      description: "按日期浏览 News Sentry 公共新闻流中的重点新闻、主要主题与来源。 ",
    }
  }

  if (route.name === "analysis") {
    const targetName = analysis?.target_name || selectedTargetLabel || "监控目标"
    return {
      title: `${targetName} 态势`,
      description: `查看 ${targetName} 的公开态势摘要、主题趋势、来源分布与实体信号。`,
    }
  }

  if (route.name === "sources") {
    return {
      title: "来源目录",
      description: "按公开新闻聚合媒体与信源，帮助读者理解 News Sentry 新闻来自哪里。",
    }
  }

  if (route.name === "sourceDetail") {
    return {
      title: `${route.sourceId} 来源详情`,
      description: "查看该来源最近进入公共新闻流的报道与覆盖节奏。",
    }
  }

  const channelTitle = feedChannelTitle(route.name === "feed" ? route.channel : "featured")
  const targetName = selectedTargetLabel ? ` · ${selectedTargetLabel}` : ""
  return {
    title: `${channelTitle}${targetName}`,
    description: DEFAULT_DESCRIPTION,
  }
}

function feedChannelTitle(channel: PublicChannel) {
  if (channel === "all") return "全部新闻"
  if (channel === "targets") return "目标新闻"
  if (channel === "sources") return "来源观察"
  if (channel === "analysis") return "态势简报"
  if (channel === "daily") return "今日日报"
  return "精选新闻"
}

function upsertMeta(
  doc: Document,
  key: string,
  value: string,
  attribute: "name" | "property" = "name",
) {
  const selector = `meta[${attribute}="${key}"]`
  const existing = doc.head.querySelector<HTMLMetaElement>(selector)
  const meta = existing ?? doc.createElement("meta")
  meta.setAttribute(attribute, key)
  meta.setAttribute("content", value)
  meta.setAttribute(MANAGED_ATTR, "true")
  if (!existing) doc.head.append(meta)
}

function upsertLink(doc: Document, rel: string, href: string) {
  const selector = `link[rel="${rel}"]`
  const existing = doc.head.querySelector<HTMLLinkElement>(selector)
  const link = existing ?? doc.createElement("link")
  link.setAttribute("rel", rel)
  link.setAttribute("href", href)
  link.setAttribute(MANAGED_ATTR, "true")
  if (!existing) doc.head.append(link)
}

function removeManagedLink(doc: Document, rel: string) {
  doc.head.querySelector(`link[rel="${rel}"][${MANAGED_ATTR}="true"]`)?.remove()
}

function upsertJsonLd(doc: Document, jsonLd?: Record<string, unknown>) {
  const selector = `script[type="application/ld+json"][${MANAGED_ATTR}="true"]`
  const existing = doc.head.querySelector<HTMLScriptElement>(selector)
  if (!jsonLd) {
    existing?.remove()
    return
  }

  const script = existing ?? doc.createElement("script")
  script.setAttribute("type", "application/ld+json")
  script.setAttribute(MANAGED_ATTR, "true")
  script.textContent = JSON.stringify(jsonLd)
  if (!existing) doc.head.append(script)
}

function removeManagedJsonLd(doc: Document) {
  doc.head.querySelector(`script[type="application/ld+json"][${MANAGED_ATTR}="true"]`)?.remove()
}

function removeManagedMeta(
  doc: Document,
  key: string,
  attribute: "name" | "property" = "name",
) {
  doc.head
    .querySelector(`meta[${attribute}="${key}"][${MANAGED_ATTR}="true"]`)
    ?.remove()
}
