import { useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  GlobeIcon,
  RssIcon,
  UsersIcon,
  Loader2Icon,
  RefreshCwIcon,
  ArchiveIcon,
  RotateCcwIcon,
  PencilIcon,
} from "lucide-react"

import { archiveTarget, restoreTarget, fetchTargetInventory, patchSource, archiveSource, restoreSource, type SourceInventoryResponse, type SourceInventoryItem } from "@/lib/api"
import { fetchTargetOverview, type TargetOverviewResponse } from "@backend/api/targets"
import { getLifecycleStatus } from "@/lib/utils"
import ErrorBanner from "@/components/ErrorBanner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import EditSourceDialog from "@/components/admin/EditSourceDialog"


export default function TargetDetail({ targetId, onBack }: { targetId: string; onBack: () => void }) {
  const [data, setData] = useState<TargetOverviewResponse | null>(null)
  const [inventory, setInventory] = useState<SourceInventoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingItem, setEditingItem] = useState<SourceInventoryItem | null>(null)


  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchTargetOverview(targetId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  async function loadInventory() {
    try {
      setInventory(await fetchTargetInventory(targetId))
    } catch {
      // silently fail
    }
  }

  useEffect(() => {
    void load()
    void loadInventory()
  }, [targetId])

  async function handleArchive() {
    try {
      await archiveTarget(targetId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "归档失败")
    }
  }

  async function handleRestore() {
    try {
      await restoreTarget(targetId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败")
    }
  }

  async function handleArchiveSource(item: SourceInventoryItem) {
    const name = item.display_name ?? item.name ?? item.source_id
    if (!window.confirm(`确定归档信源 "${name}"？归档后将停止采集，但保留历史数据。`)) return
    try {
      setLoading(true)
      await archiveSource(targetId, item.source_ref ?? item.source_id)
      await loadInventory()
    } catch (err) {
      setError(err instanceof Error ? err.message : "归档失败")
    } finally {
      setLoading(false)
    }
  }

  async function handleRestoreSource(item: SourceInventoryItem) {
    try {
      setLoading(true)
      await restoreSource(targetId, item.source_ref ?? item.source_id)
      await loadInventory()
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败")
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !data) {
    return <ErrorBanner error={error ?? "无数据"} onRetry={load} />
  }

  const d = data
  const t = d.target

  const archivedStatus = getLifecycleStatus(t.lifecycle as Record<string, unknown>)

  const isArchived = archivedStatus === "archived"
  const monitoringTypeText: string = t.monitoring_type ?? "country"
  const languageText: string = t.primary_language ?? "N/A"

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={onBack}>
            <ArrowLeftIcon className="h-3.5 w-3.5" />
            返回
          </Button>
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">{t.display_name}</h2>
            <p className="text-sm text-muted-foreground">
              <code className="font-mono text-xs">{t.target_id}</code>
              {" · " + monitoringTypeText + " · " + languageText}
              {isArchived && (
                <Badge variant="secondary" className="ml-2">已归档</Badge>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCwIcon className="h-3.5 w-3.5" />
            刷新
          </Button>
          {isArchived ? (
            <Button variant="outline" size="sm" onClick={handleRestore}>
              <RotateCcwIcon className="h-3.5 w-3.5" />
              恢复
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={handleArchive}>
              <ArchiveIcon className="h-3.5 w-3.5" />
              归档
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">活跃信源</CardTitle>
            <RssIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{d.sources.active}</div>
            <p className="text-xs text-muted-foreground">共 {d.sources.total} 个</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">事件</CardTitle>
            <GlobeIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{d.events.total}</div>
            <p className="text-xs text-muted-foreground">最新数据集</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">社媒</CardTitle>
            <UsersIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{d.social.accounts}</div>
            <p className="text-xs text-muted-foreground">{d.social.dimensions} 维度</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">数据完整性</CardTitle>
            {d.sources.missing_refs > 0 ? (
              <AlertTriangleIcon className="h-4 w-4 text-amber-500" />
            ) : (
              <CheckCircleIcon className="h-4 w-4 text-muted-foreground" />
            )}
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${d.sources.missing_refs > 0 ? "text-amber-500" : ""}`}>
              {d.sources.missing_refs > 0 ? d.sources.missing_refs : "pass"}
            </div>
            <p className="text-xs text-muted-foreground">
              {d.sources.missing_refs > 0 ? "缺失引用" : "一切正常"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 采集器状态 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">采集器</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-6 text-sm">
            <span className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-full ${d.collector.enabled ? "bg-emerald-500" : "bg-destructive"}`} />
              <span className="text-muted-foreground">状态</span>
              <span className="font-medium">{!!d.collector.enabled ? "已启用" : "未启用"}</span>
            </span>
            <span className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-full ${d.collector.running ? "bg-emerald-500" : "bg-destructive"}`} />
              <span className="text-muted-foreground">运行</span>
              <span className="font-medium">{!!d.collector.running ? "运行中" : "空闲"}</span>
            </span>
            <span className="text-muted-foreground">阶段: {String(d.collector.stage ?? "—")}</span>
          </div>
        </CardContent>
      </Card>

      {/* 分类分布 */}
      {Boolean(d.classification_diagnostics?.distribution) && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">分类分布</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>类别</TableHead>
                  <TableHead className="text-right">计数</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(
                  d.classification_diagnostics.distribution as Record<string, number>
                ).map(([cat, count]) => (
                  <TableRow key={cat}>
                    <TableCell className="font-medium">{cat}</TableCell>
                    <TableCell className="text-right tabular-nums">{count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* 信源对账 (inventory) */}
      {inventory && inventory.sources.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">信源对账</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>信源</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>URL</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="w-20">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {inventory.sources.map((item) => (
                  <TableRow key={item.source_id}>
                    <TableCell className="font-medium">{item.display_name ?? item.name ?? item.source_id}</TableCell>
                    <TableCell className="text-muted-foreground">{item.type ?? "-"}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground max-w-xs truncate">
                      {item.url ?? "-"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={item.archived ? "secondary" : "success"}>
                        {item.archived ? "已归档" : item.status ?? "活跃"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setEditingItem(item)}>
                          <PencilIcon className="h-3.5 w-3.5" />
                        </Button>
                        {item.archived ? (
                          <Button variant="ghost" size="sm" onClick={() => handleRestoreSource(item)}>
                            <RotateCcwIcon className="h-3.5 w-3.5" />
                          </Button>
                        ) : (
                          <Button variant="ghost" size="sm" onClick={() => handleArchiveSource(item)}>
                            <ArchiveIcon className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
        {editingItem && (
        <EditSourceDialog
          open={!!editingItem}
          onOpenChange={(open) => { if (!open) setEditingItem(null) }}
          targetId={targetId}
          item={editingItem}
          onSaved={() => { loadInventory() }}
        />
        )}


      {/* 最近运行 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">最近运行</CardTitle>
        </CardHeader>
        <CardContent>
          {d.recent_runs?.length ? (
            <div className="space-y-1">
              {d.recent_runs.map((run, i) => (
                <div key={run.run_id ?? i} className="flex items-center gap-3 py-1.5">
                  <span className={`inline-block h-2 w-2 rounded-full ${
                    run.status === "ok" || run.status === "success" ? "bg-emerald-500" : "bg-destructive"
                  }`} />
                  <span className="flex-1 font-mono text-xs">{run.run_id ?? `#${i + 1}`}</span>
                  <span className="text-xs text-muted-foreground">
                    {run.started_at ? new Date(run.started_at).toLocaleString("zh-CN") : "-"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">无运行记录</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
