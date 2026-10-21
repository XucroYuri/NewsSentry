import type { PublicBootstrapResponse, PublicNewsItem } from "@/types/public-news"

// 仅由 redesign-preview 模式动态加载。全部为界面验收样例，不代表真实报道。
const stories = [
  ["italy", "意大利", "欧洲观察", "欧盟与意大利就新一轮产业合作展开磋商", "Europe and Italy discuss a new industrial cooperation agenda", "国际关系", 94],
  ["japan", "日本", "科技观察", "日本研究团队公布新一代电池材料测试进展", "Research team shares progress on next-generation battery materials", "科技", 89],
  ["germany", "德国", "全球产业简报", "德国制造业关注供应链调整与中小企业转型", "Manufacturers review supply chains and the transition of small businesses", "经济", 85],
  ["italy", "意大利", "欧洲观察", "地中海港口讨论跨境物流与绿色航运合作", "Mediterranean ports discuss logistics and greener shipping", "经济", 82],
  ["france", "法国", "欧洲观察", "法国地方机构提出城市公共交通改善方案", "Local authorities propose improvements to urban public transport", "社会", 78],
  ["japan", "日本", "全球产业简报", "亚洲企业加快布局可再生能源基础设施", "Asian businesses explore renewable energy infrastructure", "能源", 76],
  ["italy", "意大利", "全球产业简报", "意大利中小企业寻求拓展亚洲市场的合作机会", "Small businesses seek new partnerships in Asian markets", "经济", 74],
  ["italy", "意大利", "欧洲观察", "欧洲高校推动开放研究与跨境人才交流", "Universities support open research and cross-border exchanges", "科技", 70],
] as const

export const previewItems: PublicNewsItem[] = stories.map(([targetId, targetLabel, sourceName, title, originalTitle, issue, score], index) => ({
  id: `preview-${index + 1}`,
  targetId,
  targetLabel,
  source: { id: sourceName, name: sourceName, type: "rss", credibilityLabel: "预览示例来源" },
  publishedAt: `2026-10-21T${String(3 - Math.floor(index / 3)).padStart(2, "0")}:${String(45 - (index % 3) * 15).padStart(2, "0")}:00Z`,
  title,
  originalTitle,
  summary: index === 0
    ? "磋商围绕产业投资、供应链协作与市场准入展开。后续需要关注具体实施安排，以及相关政策对跨境企业的影响。"
    : `这条线索聚焦${targetLabel}的${issue}动态。相关机构正在讨论合作方向，具体时间表与实施细节仍有待进一步披露。`,
  recommendationReason: "政策走向与跨境合作密切相关，值得持续关注正式文件、实施时间及各方回应。",
  fullContent: "以下为界面验收用的虚构样例，所有内容均存储在本地。\n\n此次讨论把产业投资、供应链协作与市场准入列为共同议题。各方希望通过更稳定的沟通机制，减少企业在跨境合作中面临的不确定性。\n\n从产业角度看，中小企业更关注实施规则与配套服务。研究机构则强调，在形成判断之前，需要区分政策方向、已批准措施与仍在讨论中的方案。\n\n接下来可以关注正式文件的发布时间、参与机构的公开回应，以及相关措施在不同地区的执行情况。编辑可将这些节点作为后续核实与追踪的起点。",
  originalUrl: `https://example.com/preview/${index + 1}`,
  detailUrl: `/public-app/events/preview-${index + 1}?target_id=${targetId}`,
  tags: [issue], issueTags: [issue], relatedTags: ["涉中"], regionTags: [targetLabel],
  entities: [{ name: targetLabel, type: "location" }],
  relatedCount: stories.filter((story) => story[0] === targetId).length - 1,
  valueLabel: score >= 80 ? "精选" : "关注",
  valueScore: score, breakingScore: score,
  breakingLabel: score >= 90 ? "breaking" : "watch",
  breakingConfidence: 86,
  chinaRelevanceLabel: "中",
  targetTimezone: targetId === "japan" ? "Asia/Tokyo" : "Europe/Rome",
}))

function facets(items: PublicNewsItem[], field: "issueTags" | "relatedTags") {
  const labels = [...new Set(items.flatMap((item) => item[field]))]
  return labels.map((label) => ({ id: label, label, count: items.filter((item) => item[field].includes(label)).length }))
}

export function previewResponse(url: URL): unknown {
  const params = url.searchParams
  const target = params.get("target_id") || params.get("region_id")
  const items = previewItems.filter((item) =>
    (!target || item.targetId === target)
    && (!params.get("source_id") || item.source.id === params.get("source_id"))
    && (!params.get("issue") || item.issueTags.includes(params.get("issue")!))
    && (!params.get("category") || item.tags.includes(params.get("category")!))
    && (!params.get("related") || item.relatedTags.includes(params.get("related")!))
    && (!params.get("date") || item.publishedAt.startsWith(params.get("date")!))
    && (!params.get("q") || `${item.title} ${item.summary} ${item.source.name}`.toLowerCase().includes(params.get("q")!.toLowerCase())),
  )
  const regions = [...new Set(previewItems.map((item) => item.targetId))].map((id) => {
    const regional = previewItems.filter((item) => item.targetId === id)
    return {
      region_id: id, display_name: regional[0].targetLabel, primary_language: "zh",
      region_type: "country" as const, source_count: new Set(regional.map((item) => item.source.id)).size,
      event_count: regional.length, lifecycle: {}, archived: false,
    }
  })
  const bootstrap: PublicBootstrapResponse = {
    generatedAt: "2026-10-21T03:45:00Z",
    news: { items, total: items.length, pollAfterMs: 3_600_000, hasNewer: false, nextCursor: null },
    regions: { regions },
    facets: {
      regions: regions.map((region) => ({ id: region.region_id, label: region.display_name, count: region.event_count })),
      issues: facets(items, "issueTags"), related: facets(items, "relatedTags"),
    },
  }
  if (url.pathname.endsWith("/bootstrap")) return bootstrap
  if (url.pathname.endsWith("/regions")) return bootstrap.regions
  if (url.pathname.endsWith("/facets")) return bootstrap.facets
  if (url.pathname.endsWith("/news")) return bootstrap.news
  return previewItems.find((item) => url.pathname.endsWith(`/news/${item.id}`)) ?? null
}

export function installLocalPreview() {
  // 预览模式拦截所有 fetch，不向本机后台或生产 API 转发任何请求。
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin)
    const method = init?.method ?? (input instanceof Request ? input.method : "GET")
    const data = method === "GET" ? previewResponse(url) : null
    return new Response(JSON.stringify(data ?? { message: "此操作不在本地预览范围内。" }), {
      status: data ? 200 : 404,
      headers: { "Content-Type": "application/json" },
    })
  }
  window.__NEWS_SENTRY_BOOTSTRAP_PRELOAD__ = Promise.resolve(
    previewResponse(new URL("/api/v1/public/bootstrap", window.location.origin)),
  )
}
