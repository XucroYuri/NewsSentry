import { afterEach, describe, expect, it, vi } from "vitest"

import { installLocalPreview, previewItems, previewResponse } from "./local-preview"
import type { PublicBootstrapResponse, PublicNewsFeedResponse } from "@/types/public-news"

afterEach(() => {
  vi.unstubAllGlobals()
  delete window.__NEWS_SENTRY_BOOTSTRAP_PRELOAD__
})

describe("本地预览隔离", () => {
  it("首页、地区和议题的数量来自同一批新闻", () => {
    const data = previewResponse(new URL("https://preview.test/api/v1/public/bootstrap")) as PublicBootstrapResponse
    expect(data.news.total).toBe(previewItems.length)
    expect(data.regions.regions.reduce((sum, region) => sum + region.event_count, 0)).toBe(data.news.total)
    expect(data.facets.issues.reduce((sum, issue) => sum + issue.count, 0)).toBe(data.news.total)
    for (const item of data.news.items) {
      expect(previewResponse(new URL(`https://preview.test/api/v1/public/news/${item.id}`))).toEqual(item)
    }
  })

  it("地区与搜索共同过滤，空结果仍保留合法响应", () => {
    const query = new URL("https://preview.test/api/v1/public/news?target_id=italy&q=物流")
    const data = previewResponse(query) as PublicNewsFeedResponse
    expect(data.total).toBe(1)
    expect(data.items[0].targetId).toBe("italy")
    expect(data.items[0].title).toContain("物流")
    query.searchParams.set("target_id", "japan")
    expect((previewResponse(query) as PublicNewsFeedResponse).items).toEqual([])
  })

  it("不向真实 fetch 转发读取、未知端点或写入", async () => {
    const realFetch = vi.fn()
    vi.stubGlobal("fetch", realFetch)
    installLocalPreview()
    const feed = await fetch("https://api.news-sentry.com/api/v1/public/news")
    expect(feed.status).toBe(200)
    const unknown = await fetch("https://api.news-sentry.com/api/v1/private")
    expect(unknown.status).toBe(404)
    const write = await fetch("https://api.news-sentry.com/api/v1/public/subscribe", { method: "POST" })
    expect(write.status).toBe(404)
    expect(realFetch).not.toHaveBeenCalled()
  })
})
