/**
 * EventsPage.tsx — 新闻事件管理页（M-35.1）
 *
 * 功能：
 * - 按目标分页浏览所有新闻事件
 * - 搜索/按分类/按分值范围/按情感筛选
 * - 点击查看事件详情（弹窗展示完整内容）
 * - 删除/废弃事件
 */

import { useCallback, useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  ExternalLinkIcon,
  GlobeIcon,
  Loader2Icon,
  SearchIcon,
} from "lucide-react"

import { fetchAdminTargets, type AdminTargetInfo } from "@/lib/api"
import { scoreVariant, sentimentVariant } from "@/lib/utils"
import { fetchEvents, type EventsResponse } from "@backend/api/events"
import { Card, CardContent } from "@/components/ui/card"
import PaginationBar from "@/components/PaginationBar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface EventRecord {
  event_id?: string
  title_original?: string
  title_translated?: string
  source_id?: string
  source_name?: string
  published_at?: string
  news_value_score?: number
  classification_l0?: string
  classification_l1?: string
  sentiment?: string
  summary_translated?: string
  content_original?: string
  original_url?: string
  tags?: string[]
  entities?: Array<{ name: string; type?: string }>
  [key: string]: unknown
}

export default function EventsPage() {
  const [targets, setTargets] = useState<AdminTargetInfo[]>([])
  const [selectedTargetId, setSelectedTargetId] = useState<string>("")
  const [data, setData] = useState<EventsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)

  // 筛选
  const [search, setSearch] = useState("")
  const [searchDraft, setSearchDraft] = useState("")
  const [classification, setClassification] = useState("")
  const [minScore, setMinScore] = useState<number | undefined>(undefined)
  const [sentiment, setSentiment] = useState("")

  // 详情弹窗
  const [detailItem, setDetailItem] = useState<EventRecord | null>(null)

  // 加载目标列表
  useEffect(() => {
    fetchAdminTargets(true)
      .then((res) => {
        setTargets(res.targets ?? [])
        if (res.targets?.length) setSelectedTargetId(res.targets[0].target_id)
      })
      .catch(() => {})
  }, [])

  // 加载事件列表
  const load = useCallback(async () => {
    if (!selectedTargetId) return
    setLoading(true)
    setError(null)
    try {
      const json = await fetchEvents({
        target_id: selectedTargetId,
        page,
        page_size: pageSize,
        search: search.trim() || undefined,
        classification: classification || undefined,
        min_score: minScore,
        sentiment: sentiment || undefined,
      })
      setData(json)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [selectedTargetId, page, pageSize, search, classification, minScore, sentiment])

  useEffect(() => {
    void load()
  }, [load])

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setSearch(searchDraft)
    setPage(1)
  }

  function events(): EventRecord[] {
    return data?.events ?? []
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1

  return (
    <div className="space-y-6">
      {/* 标题栏 + 目标选择 */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">新闻事件管理</h2>
          <p className="text-sm text-muted-foreground">
            {data ? `共 ${data.total} 条事件` : "加载中..."}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2Icon className="h-3.5 w-3.5 animate-spin" /> : "刷新"}
        </Button>
      </div>

      {/* 筛选栏 */}
      <Card>
        <CardContent className="py-3">
          <div className="flex flex-wrap items-end gap-3">
            {/* 目标选择 */}
            <div className="grid min-w-[180px] gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="target-select">目标</label>
              <select
                id="target-select"
                value={selectedTargetId}
                onChange={(e) => {
                  setSelectedTargetId(e.target.value)
                  setPage(1)
                }}
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
              >
                {targets.map((t) => (
                  <option key={t.target_id} value={t.target_id}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </div>
            {/* 搜索 */}
            <form onSubmit={handleSearch} className="grid min-w-[200px] flex-1 gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="events-search">搜索</label>
              <div className="flex gap-1.5">
                <Input
                  id="events-search"
                  value={searchDraft}
                  placeholder="标题关键词..."
                  onChange={(e) => setSearchDraft(e.target.value)}
                  className="h-8 text-xs"
                />
                <Button type="submit" size="sm" className="h-8">
                  <SearchIcon className="h-3.5 w-3.5" />
                </Button>
              </div>
            </form>
            {/* 分类 */}
            <div className="grid min-w-[130px] gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="class-select">分类</label>
              <select
                id="class-select"
                value={classification}
                onChange={(e) => { setClassification(e.target.value); setPage(1) }}
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
              >
                <option value="">全部</option>
                <option value="breaking">Breaking</option>
                <option value="important">Important</option>
                <option value="standard">Standard</option>
                <option value="low">Low</option>
              </select>
            </div>
            {/* 情感 */}
            <div className="grid min-w-[120px] gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="sent-select">情感</label>
              <select
                id="sent-select"
                value={sentiment}
                onChange={(e) => { setSentiment(e.target.value); setPage(1) }}
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
              >
                <option value="">不限</option>
                <option value="positive">正向</option>
                <option value="negative">负向</option>
                <option value="neutral">中性</option>
              </select>
            </div>
            {/* 最低分值 */}
            <div className="grid min-w-[120px] gap-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="min-score">最低分值</label>
              <select
                id="min-score"
                value={minScore ?? ""}
                onChange={(e) => {
                  setMinScore(e.target.value ? Number(e.target.value) : undefined)
                  setPage(1)
                }}
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
              >
                <option value="">不限</option>
                <option value="80">80+</option>
                <option value="60">60+</option>
                <option value="40">40+</option>
                <option value="20">20+</option>
              </select>
            </div>
            {/* 清除筛选 */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8"
              onClick={() => {
                setSearch("")
                setSearchDraft("")
                setClassification("")
                setMinScore(undefined)
                setSentiment("")
                setPage(1)
              }}
            >
              清除
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 错误 */}
      {error && (
        <div className="flex items-center gap-2 rounded-md bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertTriangleIcon className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* 事件表格 */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 space-y-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : events().length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              暂无匹配事件
            </div>
          ) : (
            <div className="max-h-[calc(100vh-360px)] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-muted/50">
                  <tr className="border-b text-left text-xs font-medium text-muted-foreground">
                    <th className="px-4 py-2 w-16">分值</th>
                    <th className="px-4 py-2">标题 / 来源</th>
                    <th className="px-4 py-2 w-24">分类</th>
                    <th className="px-4 py-2 w-20">情感</th>
                    <th className="px-4 py-2 w-36">时间</th>
                    <th className="px-4 py-2 w-28 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {events().map((event) => (
                    <tr
                      key={event.event_id ?? event.source_id + (event.published_at ?? "")}
                      className="border-b hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-4 py-2">
                        <Badge variant={scoreVariant(event.news_value_score)} className="h-5 w-10 justify-center rounded text-xs font-semibold">
                          {event.news_value_score ?? "-"}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 min-w-0">
                        <div
                          className="max-w-lg cursor-pointer truncate font-medium hover:text-primary"
                          onClick={() => setDetailItem(event)}
                          title={event.title_translated ?? event.title_original ?? "(无标题)"}
                        >
                          {event.title_translated ?? event.title_original ?? "(无标题)"}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                          <GlobeIcon className="h-3 w-3 shrink-0" />
                          <span className="truncate">{event.source_name ?? event.source_id ?? "未知来源"}</span>
                          {event.original_url ? (
                            <a
                              href={event.original_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-primary hover:underline shrink-0"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLinkIcon className="h-3 w-3" />
                            </a>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-4 py-2">
                        {event.classification_l0 ? (
                          <Badge variant="outline" className="text-[10px]">
                            {event.classification_l0}
                            {event.classification_l1 ? ` / ${event.classification_l1}` : ""}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={sentimentVariant(event.sentiment)} className="text-[10px]">
                          {event.sentiment ?? "-"}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground whitespace-nowrap">
                        {event.published_at
                          ? new Date(event.published_at).toLocaleString("zh-CN")
                          : "-"}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDetailItem(event)}
                        >
                          详情
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 分页 */}
          {data && data.total > 0 && (
            <div className="border-t px-4 py-2">
              <PaginationBar
                page={page}
                totalPages={totalPages}
                total={data.total}
                onPageChange={setPage}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* 详情弹窗 */}
      <Dialog open={!!detailItem} onOpenChange={(open) => { if (!open) setDetailItem(null) }}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-lg">
              {detailItem?.title_translated ?? detailItem?.title_original ?? "(无标题)"}
            </DialogTitle>
          </DialogHeader>
          {detailItem && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-muted-foreground">分值：</span>
                  <Badge variant={scoreVariant(detailItem.news_value_score)} className="ml-1">
                    {detailItem.news_value_score ?? "-"}
                  </Badge>
                </div>
                <div>
                  <span className="text-muted-foreground">情感：</span>
                  <Badge variant={sentimentVariant(detailItem.sentiment)} className="ml-1">
                    {detailItem.sentiment ?? "-"}
                  </Badge>
                </div>
                <div>
                  <span className="text-muted-foreground">来源：</span>
                  {detailItem.source_name ?? detailItem.source_id ?? "未知"}
                </div>
                <div>
                  <span className="text-muted-foreground">时间：</span>
                  {detailItem.published_at
                    ? new Date(detailItem.published_at).toLocaleString("zh-CN")
                    : "-"}
                </div>
                {detailItem.classification_l0 && (
                  <div className="col-span-2">
                    <span className="text-muted-foreground">分类：</span>
                    {detailItem.classification_l0}
                    {detailItem.classification_l1 ? ` / ${detailItem.classification_l1}` : ""}
                  </div>
                )}
                {detailItem.original_url && (
                  <div className="col-span-2">
                    <span className="text-muted-foreground">链接：</span>
                    <a
                      href={detailItem.original_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary hover:underline"
                    >
                      {detailItem.original_url}
                    </a>
                  </div>
                )}
                {detailItem.tags && detailItem.tags.length > 0 && (
                  <div className="col-span-2">
                    <span className="text-muted-foreground">标签：</span>
                    <span>{detailItem.tags.join(", ")}</span>
                  </div>
                )}
              </div>
              {detailItem.summary_translated && (
                <div>
                  <h3 className="font-medium mb-1">摘要</h3>
                  <p className="text-muted-foreground">{detailItem.summary_translated}</p>
                </div>
              )}
              {detailItem.content_original && (
                <div>
                  <h3 className="font-medium mb-1">原文</h3>
                  <p className="text-muted-foreground whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {detailItem.content_original}
                  </p>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
