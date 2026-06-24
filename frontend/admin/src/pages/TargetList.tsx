import { useEffect, useState, useCallback } from "react"
import {
  AlertTriangleIcon,
  ArrowUpRightIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ArchiveIcon,
  RotateCcwIcon,
} from "lucide-react"

import {
  fetchAdminTargets,
  createTarget,
  archiveTarget,
  restoreTarget,
  type AdminTargetInfo,
  type TargetCreateRequest,
} from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"

export default function TargetList({
  onNavigate,
}: {
  onNavigate?: (targetId: string) => void
}) {
  const [targets, setTargets] = useState<AdminTargetInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  // Create dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [newTargetId, setNewTargetId] = useState("")
  const [newDisplayName, setNewDisplayName] = useState("")
  const [newLanguage, setNewLanguage] = useState("it")
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAdminTargets(true)
      setTargets(data.targets ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newTargetId.trim() || !newDisplayName.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const payload: TargetCreateRequest = {
        target_id: newTargetId.trim(),
        display_name: newDisplayName.trim(),
        mode: "template",
        language_scope: newLanguage.trim() || "it",
        monitoring_type: "rss",
      }
      await createTarget(payload)
      setDialogOpen(false)
      setNewTargetId("")
      setNewDisplayName("")
      setNewLanguage("it")
      await load()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  async function handleArchive(targetId: string) {
    try {
      await archiveTarget(targetId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "归档失败")
    }
  }

  async function handleRestore(targetId: string) {
    try {
      await restoreTarget(targetId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败")
    }
  }

  const filtered = targets.filter((t) => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return (
      t.target_id.toLowerCase().includes(q) ||
      (t.display_name ?? "").toLowerCase().includes(q)
    )
  })

  const lifecycleStatus = (t: AdminTargetInfo): string =>
    typeof t.lifecycle === "object" && t.lifecycle !== null
      ? String((t.lifecycle as Record<string, unknown>).status ?? "")
      : ""

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
        <AlertTriangleIcon className="mx-auto mb-2 h-8 w-8 text-destructive" />
        <p className="text-sm text-destructive">{error}</p>
        <Button variant="link" onClick={load} className="mt-3">重试</Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">目标工作台</h2>
          <p className="text-sm text-muted-foreground">{targets.length} 个监控目标</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <SearchIcon className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索 ID 或名称..."
              className="h-8 pl-8 text-sm w-48"
            />
          </div>

          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <PlusIcon className="h-3.5 w-3.5" />
                新建
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>创建监控目标</DialogTitle>
                <DialogDescription>
                  基于模板创建新的目标配置骨架，包含默认信源、过滤和分类规则。
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleCreate}>
                <div className="grid gap-4 py-4">
                  <div className="grid gap-2">
                    <Label htmlFor="target-id">目标 ID</Label>
                    <Input
                      id="target-id"
                      placeholder="例如: de-economy"
                      value={newTargetId}
                      onChange={(e) => setNewTargetId(e.target.value)}
                      disabled={creating}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="display-name">显示名称</Label>
                    <Input
                      id="display-name"
                      placeholder="例如: 德国经济"
                      value={newDisplayName}
                      onChange={(e) => setNewDisplayName(e.target.value)}
                      disabled={creating}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="language">语言范围</Label>
                    <Input
                      id="language"
                      placeholder="it / en / de / fr ..."
                      value={newLanguage}
                      onChange={(e) => setNewLanguage(e.target.value)}
                      disabled={creating}
                    />
                  </div>
                  {createError && (
                    <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                      <AlertTriangleIcon className="h-4 w-4 shrink-0" />
                      {createError}
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={creating}>
                    取消
                  </Button>
                  <Button type="submit" disabled={creating || !newTargetId.trim() || !newDisplayName.trim()}>
                    {creating ? "创建中..." : "创建"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>

          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCwIcon className="h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>

      {/* Target 表格 */}
      {filtered.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            {search.trim() ? "无匹配结果" : "暂无监控目标"}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>目标 ID</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>语言</TableHead>
                  <TableHead>信源</TableHead>
                  <TableHead>事件</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((t) => {
                  const status = lifecycleStatus(t)
                  const isArchived = status === "archived"
                  return (
                    <TableRow key={t.target_id}>
                      <TableCell className="font-mono text-xs">{t.target_id}</TableCell>
                      <TableCell className="font-medium">{t.display_name}</TableCell>
                      <TableCell className="text-muted-foreground">{t.monitoring_type ?? t.region_type ?? "-"}</TableCell>
                      <TableCell className="text-muted-foreground">{t.primary_language ?? "-"}</TableCell>
                      <TableCell>{t.source_count ?? "-"}</TableCell>
                      <TableCell>{t.event_count ?? "-"}</TableCell>
                      <TableCell>
                        <Badge variant={isArchived ? "secondary" : "success"}>
                          {isArchived ? "已归档" : "活跃"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => onNavigate?.(t.target_id)}
                          >
                            <ArrowUpRightIcon className="h-3 w-3" />
                            详情
                          </Button>
                          {isArchived ? (
                            <Button variant="ghost" size="sm" onClick={() => handleRestore(t.target_id)}>
                              <RotateCcwIcon className="h-3 w-3" />
                            </Button>
                          ) : (
                            <Button variant="ghost" size="sm" onClick={() => handleArchive(t.target_id)}>
                              <ArchiveIcon className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
