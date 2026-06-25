import type { PublicChannel } from "@/lib/feed-state"
import { buildPublicAppPath, type PublicRoute } from "@/lib/routes"
import type { PublicAnalysisResponse, PublicNewsItem } from "@/types/public-news"

const SITE_NAME = "News Sentry"
const DEFAULT_TITLE = "News Sentry | 新闻哨兵"
const DEFAULT_TITLE_IT = "News Sentry | Sentinella delle Notizie"
const PUBLIC_APP_ROOT = "/public-app/"
const DEFAULT_DESCRIPTION =
  "News Sentry 新闻哨兵面向中文读者追踪全球新闻，按地区、议题和相关对象筛选重点事件，提供中文摘要、原文标题、信源信息与 Breaking News 指数。"
const DEFAULT_DESCRIPTION_IT =
  "News Sentry è una sentinella delle notizie globali per lettori cinesi e italiani. " +
  "Traccia eventi chiave per regione, tema e soggetto, offrendo riassunti in cinese, " +
  "titoli originali, fonti e l'indice Breaking News."
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
  locale?: string
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
  const title = item?.title || item?.originalTitle?.trim() || "新闻详情"
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
      headline: title,
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
  locale,
}: RouteSeoInput): SiteSeoPayload {
  const canonicalUrl = buildCanonicalUrl(origin, buildRouteCanonicalPath(route))
  const page = pageCopy(route, selectedTargetLabel, analysis, locale ?? route.locale ?? "zh")

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

export function clearSiteSeo(doc: Document = document, locale = "zh") {
  const title = locale === "it" ? DEFAULT_TITLE_IT : DEFAULT_TITLE
  const description = locale === "it" ? DEFAULT_DESCRIPTION_IT : DEFAULT_DESCRIPTION
  doc.title = title

  upsertMeta(doc, "description", description)
  upsertMeta(doc, "og:type", "website", "property")
  upsertMeta(doc, "og:site_name", SITE_NAME, "property")
  upsertMeta(doc, "og:title", title, "property")
  upsertMeta(doc, "og:description", description, "property")
  upsertMeta(doc, "twitter:card", "summary")
  upsertMeta(doc, "twitter:title", title)
  upsertMeta(doc, "twitter:description", description)
  removeManagedLink(doc, "canonical")
  removeManagedJsonLd(doc)
  removeManagedMeta(doc, "og:url", "property")
}

function pageCopy(
  route: PublicRoute,
  selectedTargetLabel?: string | null,
  analysis?: PublicAnalysisResponse | null,
  locale = "zh",
) {
  const it = locale === "it"
  if (route.name === "daily") {
    if (it) {
      return {
        title: route.date ? `Bollettino del ${route.date}` : "Bollettino Quotidiano",
        description:
          "Sfoglia le notizie principali, i temi e le fonti del feed pubblico di News Sentry per data.",
      }
    }
    return {
      title: route.date ? `${route.date} 新闻日报` : "新闻日报",
      description: "按日期浏览 News Sentry 公共新闻流中的重点新闻、主要主题与来源。 ",
    }
  }
  if (route.name === "agent") {
    if (it) {
      return {
        title: "Agent",
        description:
          "Istruzioni per l'accesso automatico e machine-readable al feed pubblico di News Sentry.",
      }
    }
    return {
      title: "Agent",
      description: "面向机器可读与自动化接入的 News Sentry 公共入口说明。",
    }
  }
  if (route.name === "update") {
    if (it) {
      return {
        title: "Aggiornamenti",
        description:
          "Note sulle modifiche, la frequenza di aggiornamento e le novità del sito pubblico di News Sentry.",
      }
    }
    return {
      title: "Update",
      description: "News Sentry 公共站更新、刷新节奏与产品变更说明。",
    }
  }
  if (route.name === "subscribe") {
    if (it) {
      return {
        title: "Iscriviti",
        description:
          "Ricevi i segnali quotidiani, il bollettino e gli aggiornamenti sui target di News Sentry.",
      }
    }
    return {
      title: "订阅 Subscribe",
      description: "接收 News Sentry 每日信号、新闻日报与地区更新。",
    }
  }

  if (route.name === "analysis") {
    const targetName = analysis?.target_name || selectedTargetLabel || (it ? "Obiettivo Monitorato" : "监控目标")
    if (it) {
      return {
        title: `Panoramica di ${targetName}`,
        description: `Visualizza il riepilogo pubblico, i trend tematici, la distribuzione delle fonti e i segnali sulle entità per ${targetName}.`,
      }
    }
    return {
      title: `${targetName} 态势`,
      description: `查看 ${targetName} 的公开态势摘要、主题趋势、来源分布与实体信号。`,
    }
  }

  if (route.name === "sources") {
    if (it) {
      return {
        title: "Directory delle Fonti",
        description:
          "Esplora le fonti giornalistiche e i media aggregati da cui News Sentry attinge le notizie.",
      }
    }
    return {
      title: "信源管理",
      description: "按类型、地区和活跃度管理 News Sentry 公开信源、覆盖范围与最近样本。",
    }
  }

  if (route.name === "sourceDetail") {
    if (it) {
      return {
        title: `Dettagli fonte ${route.sourceId}`,
        description:
          "Visualizza le notizie recenti e la frequenza di copertura di questa fonte nel feed pubblico.",
      }
    }
    return {
      title: `${route.sourceId} 来源详情`,
      description: "查看该来源最近进入公共新闻流的报道与覆盖节奏。",
    }
  }

  const channelTitle = feedChannelTitle(route.name === "feed" ? route.channel : "featured", it)
  const targetName = selectedTargetLabel ? ` · ${selectedTargetLabel}` : ""
  return {
    title: `${channelTitle}${targetName}`,
    description: it ? DEFAULT_DESCRIPTION_IT : DEFAULT_DESCRIPTION,
  }
}

function feedChannelTitle(channel: PublicChannel, it = false) {
  if (it) {
    if (channel === "all") return "Panoramica Notizie"
    if (channel === "targets") return "Notizie Regionali"
    if (channel === "sources") return "Osservatorio Fonti"
    if (channel === "analysis") return "Briefing"
    if (channel === "daily") return "Bollettino"
    return "Sentinella"
  }
  if (channel === "all") return "新闻纵览"
  if (channel === "targets") return "地区新闻"
  if (channel === "sources") return "来源观察"
  if (channel === "analysis") return "态势简报"
  if (channel === "daily") return "新闻日报"
  return "新闻哨兵"
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
