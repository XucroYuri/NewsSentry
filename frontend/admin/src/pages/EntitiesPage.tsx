import { useEffect, useState } from "react"
import {
  Loader2Icon,
  MergeIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"

import { fetchEntities, fetchEntity, fetchEntityEvents, mergeEntities, searchEntities, type EntityInfo, type EntityDetailResponse, type EntityListResponse } from "@/lib/api"
import ErrorBanner from "@/components/ErrorBanner"
import { entityTypeBadge, formatAliases } from "@/lib/utils"
import PaginationBar from "@/components/PaginationBar"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"

const PAGE_SIZE = 20

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntityInfo[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 搜索/过滤
  const [searchQuery, setSearchQuery] = useState("")
  const [searching, setSearching] = useState(false)
  const [entityType, setEntityType] = useState("")
  const [sort, setSort] = useState("mention_count")
  const [page, setPage] = useState(0)

  // 详情 Dialog
  const [detailId, setDetailId] = useState<number | null>(null)
  const [detail, setDetail] = useState<EntityDetailResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [entityEvents, setEntityEvents] = useState<Record<string, unknown>[]>([])

  // 合并 UI
  const [mergeSourceQuery, setMergeSourceQuery] = useState("")
  const [mergeSourceResults, setMergeSourceResults] = useState<EntityInfo[]>([])
  const [mergeSearchLoading, setMergeSearchLoading] = useState(false)
  const [mergeDialog, setMergeDialog] = useState(false)
  const [mergeLoading, setMergeLoading] = useState(false)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const isSearching = searchQuery.trim().length > 0

  async function load() {
    setLoading(true)
    setError(null)
    try {
      if (isSearching) {
        const data = await searchEntities(searchQuery.trim(), PAGE_SIZE)
        setEntities(data.entities)
        setTotal(data.total)
      } else {
        const params: Record<string, unknown> = {
          limit: PAGE_SIZE,
          sort,
        }
        if (entityType) params.entity_type = entityType
        const data = await fetchEntities(params as Parameters<typeof fetchEntities>[0])
        setEntities(data.entities)
        setTotal(data.total)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
      setSearching(false)
    }
  }

  useEffect(() => {
    void load()
  }, [sort, entityType, page])

  function handleSearch() {
    if (!searchQuery.trim()) return
    setSearching(true)
    setPage(0)
    void load()
  }

  function clearSearch() {
    setSearchQuery("")
    setPage(0)
  }

  async function openDetail(entityId: number) {
    setDetailId(entityId)
    setDetailLoading(true)
    setMergeSourceQuery("")
    setMergeSourceResults([])
    try {
      const d = await fetchEntity(entityId)
      setDetail(d)
      const eventsRes = await fetchEntityEvents(entityId, 20, 0)
      setEntityEvents(eventsRes.events)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载详情失败")
    } finally {
      setDetailLoading(false)
    }
  }

  function closeDetail() {
    setDetailId(null)
    setDetail(null)
    setEntityEvents([])
    setMergeSourceQuery("")
    setMergeSourceResults([])
  }

  async function searchMergeSource() {
    if (!mergeSourceQuery.trim()) return
    setMergeSearchLoading(true)
    try {
      const data: EntityListResponse = await searchEntities(mergeSourceQuery.trim(), 10)
      // 排除当前详情实体
      setMergeSourceResults(data.entities.filter((e) => e.id !== detailId))
    } catch {
      // ignore
    } finally {
      setMergeSearchLoading(false)
    }
  }

  async function handleMerge(sourceId: number) {
    if (detailId == null) return
    setMergeLoading(true)
    setMergeError(null)
    try {
      await mergeEntities(sourceId, detailId)
      setMergeDialog(false)
      setMergeSourceQuery("")
      setMergeSourceResults([])
      closeDetail()
      void load()
    } catch (err) {
      setMergeError(err instanceof Error ? err.message : "合并失败")
    } finally {
      setMergeLoading(false)
    }
  }

  // ── 主列表视图 ──────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* 搜索栏 */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-1 items-center gap-2 min-w-0">
              <Input
                placeholder="搜索实体名称..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="max-w-sm"
              />
              <Button variant="outline" size="sm" onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
                <SearchIcon className="h-3.5 w-3.5" />
                搜索
              </Button>
              {searchQuery && (
                <Button variant="ghost" size="sm" onClick={clearSearch}>
                  <XIcon className="h-3.5 w-3.5" />
                  清除
                </Button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <select
                value={entityType}
                onChange={(e) => { setEntityType(e.target.value); setPage(0) }}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                <option value="">全部类型</option>
                <option value="person">人物</option>
                <option value="organization">组织</option>
                <option value="location">地点</option>
                <option value="event">事件</option>
                <option value="topic">主题</option>
              </select>

              <select
                value={sort}
                onChange={(e) => { setSort(e.target.value); setPage(0) }}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                <option value="mention_count">提及次数</option>
                <option value="last_seen">最晚出现</option>
              </select>

              <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                <RefreshCwIcon className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 错误 */}
      {error && <ErrorBanner error={error} onRetry={load} variant="compact" />}

      {/* 加载中 */}
      {loading && !error && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {/* 实体列表 */}
      {!loading && !error && (
        <>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">
                实体列表 {total > 0 && <span className="text-muted-foreground font-normal">({total})</span>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {entities.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">
                  {isSearching ? "未找到匹配实体" : "暂无实体数据"}
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>名称</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>别名</TableHead>
                      <TableHead className="text-right">提及次数</TableHead>
                      <TableHead>首次出现</TableHead>
                      <TableHead>最晚出现</TableHead>
                      <TableHead className="text-right">置信度</TableHead>
                      <TableHead className="w-20"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {entities.map((e) => (
                      <TableRow key={e.id} className={e.needs_review ? "bg-amber-50/50" : ""}>
                        <TableCell className="font-medium">
                          <span>{e.canonical_name}</span>
                          {e.needs_review && (
                            <Badge variant="secondary" className="ml-2 text-[10px]">待审</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`text-[10px] border ${entityTypeBadge(e.entity_type)}`}>
                            {e.entity_type}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                          {e.aliases || "-"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{e.mention_count}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {e.first_seen ? new Date(e.first_seen).toLocaleDateString("zh-CN") : "-"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {e.last_seen ? new Date(e.last_seen).toLocaleDateString("zh-CN") : "-"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{e.confidence}</TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm" onClick={() => openDetail(e.id)}>
                            详情
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* 分页 */}
          {total > PAGE_SIZE && (
            <PaginationBar
              page={page}
              totalPages={Math.ceil(total / PAGE_SIZE)}
              total={total}
              pageSize={PAGE_SIZE}
              mode="offset"
              onPageChange={setPage}
            />
          )}
        </>
      )}

      {/* ── 实体详情 Dialog ────────────────────────────── */}
      <Dialog open={detailId != null} onOpenChange={(open) => { if (!open) closeDetail() }}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          {detailLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2Icon className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : detail ? (
            <>
              <DialogHeader>
                <DialogTitle className="text-lg flex items-center gap-2">
                  {detail.entity.canonical_name}
                  {detail.entity.needs_review && (
                    <Badge variant="secondary">待审</Badge>
                  )}
                  <Badge variant="outline" className={entityTypeBadge(detail.entity.entity_type)}>
                    {detail.entity.entity_type}
                  </Badge>
                </DialogTitle>
                <DialogDescription>
                  {detail.entity.mention_count} 次提及 · 置信度 {detail.entity.confidence}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                {/* 基本信息 */}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-muted-foreground">首次出现：</span>
                    {detail.entity.first_seen ? new Date(detail.entity.first_seen).toLocaleString("zh-CN") : "-"}
                  </div>
                  <div>
                    <span className="text-muted-foreground">最晚出现：</span>
                    {detail.entity.last_seen ? new Date(detail.entity.last_seen).toLocaleString("zh-CN") : "-"}
                  </div>
                  {detail.entity.first_seen_source_id && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground">首见来源：</span>
                      <code className="text-xs">{detail.entity.first_seen_source_id}</code>
                    </div>
                  )}
                  {detail.entity.last_seen_source_id && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground">末见来源：</span>
                      <code className="text-xs">{detail.entity.last_seen_source_id}</code>
                    </div>
                  )}
                  {detail.entity.target_ids && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground">所属 targets：</span>
                      <code className="text-xs">{detail.entity.target_ids}</code>
                    </div>
                  )}
                  {detail.entity.aliases && (
                    <div className="col-span-2">
                      <span className="text-muted-foreground">别名：</span>
                      <span className="text-xs">{formatAliases(detail.entity.aliases).join("、")}</span>
                    </div>
                  )}
                </div>

                {/* 关联事件 */}
                {entityEvents.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">关联事件</h4>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto border rounded-md p-2">
                      {entityEvents.map((evt, i) => (
                        <div key={i} className="text-xs py-1 border-b border-border last:border-0">
                          <span className="font-medium">{String(evt.event_id ?? `#${i + 1}`)}</span>
                          <span className="text-muted-foreground ml-2">
                            {(evt.published_at as string) ? new Date(evt.published_at as string).toLocaleDateString("zh-CN") : ""}
                          </span>
                          {evt.title ? <div className="text-muted-foreground mt-0.5 line-clamp-1">{String(evt.title)}</div> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 合并操作 — 按名称搜索源实体 */}
                <div className="border-t pt-4">
                  <p className="text-sm text-muted-foreground mb-2">
                    搜索并选择要合并到此实体的来源实体
                  </p>
                  <div className="flex items-center gap-2 mb-3">
                    <Input
                      placeholder="搜索来源实体名称..."
                      value={mergeSourceQuery}
                      onChange={(e) => setMergeSourceQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && searchMergeSource()}
                      className="max-w-xs"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={searchMergeSource}
                      disabled={mergeSearchLoading || !mergeSourceQuery.trim()}
                    >
                      <SearchIcon className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {mergeSourceResults.length > 0 && (
                    <div className="space-y-1 max-h-40 overflow-y-auto border rounded-md p-2 mb-3">
                      {mergeSourceResults.map((src) => (
                        <div
                          key={src.id}
                          className="flex items-center justify-between py-1 px-2 hover:bg-accent rounded text-xs"
                        >
                          <div>
                            <span className="font-medium">{src.canonical_name}</span>
                            <Badge variant="outline" className={`ml-2 text-[10px] border ${entityTypeBadge(src.entity_type)}`}>
                              {src.entity_type}
                            </Badge>
                            <span className="text-muted-foreground ml-2">{src.mention_count} 次提及</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setMergeDialog(true)}
                            className="text-destructive hover:text-destructive"
                          >
                            <MergeIcon className="h-3.5 w-3.5" />
                            合并
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                  {mergeSearchLoading && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                      <Loader2Icon className="h-3.5 w-3.5 animate-spin" />
                      搜索中...
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="text-center py-8 text-sm text-muted-foreground">实体未找到</div>
          )}
        </DialogContent>
      </Dialog>

      {/* ── 合并确认 Dialog ────────────────────────────── */}
      <Dialog open={mergeDialog} onOpenChange={setMergeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认合并实体</DialogTitle>
            <DialogDescription>
              将实体 <code className="text-xs">{mergeSourceResults.length > 0 ? mergeSourceResults[0].canonical_name : "?"}</code> 合并到{" "}
              <code className="text-xs">{detail?.entity.canonical_name ?? ""}</code>。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          {mergeError && (
            <p className="text-sm text-destructive bg-destructive/5 rounded-md p-3">{mergeError}</p>
          )}
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setMergeDialog(false)} disabled={mergeLoading}>
              取消
            </Button>
            <Button
              size="sm"
              onClick={() => {
                if (mergeSourceResults.length > 0) handleMerge(mergeSourceResults[0].id)
              }}
              disabled={mergeLoading}
            >
              {mergeLoading && <Loader2Icon className="h-3.5 w-3.5 mr-1 animate-spin" />}
              确认合并
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
