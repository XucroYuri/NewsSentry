import { useCallback, useEffect, useRef, useState } from "react"
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react"

import {
  createAnnotation,
  fetchAnnotations,
  type AnnotationInfo
} from "@/lib/api"
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

const PAGE_SIZE = 50

export default function AnnotationsPage() {
  const [annotations, setAnnotations] = useState<AnnotationInfo[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 过滤/搜索
  const [entityFilter, setEntityFilter] = useState("")
  const [reviewFilter, setReviewFilter] = useState<string>("")
  const [page, setPage] = useState(0)

  // 展开详情
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // 新建 Dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const createFormRef = useRef<HTMLFormElement>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, unknown> = {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }
      if (entityFilter) params.entity_id = Number(entityFilter)
      if (reviewFilter === "true") params.reviewed = true
      else if (reviewFilter === "false") params.reviewed = false
      const data = await fetchAnnotations(params as Parameters<typeof fetchAnnotations>[0])
      setAnnotations(data.annotations)
      setTotal(data.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [entityFilter, reviewFilter, page])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    const form = createFormRef.current
    if (!form) return
    const fd = new FormData(form)
    const entityId = Number(fd.get("entity_id"))
    if (!entityId) {
      setCreateError("请输入实体 ID")
      return
    }
    setCreateLoading(true)
    setCreateError(null)
    try {
      await createAnnotation({
        entity_id: entityId,
        field: String(fd.get("field") ?? ""),
        old_value: String(fd.get("old_value") ?? ""),
        new_value: String(fd.get("new_value") ?? ""),
        event_id: String(fd.get("event_id") ?? "") || null,
        annotation_type: String(fd.get("annotation_type") ?? "manual"),
      })
      setCreateOpen(false)
      form.reset()
      void load()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreateLoading(false)
    }
  }

  function reviewBadge(reviewed: boolean) {
    if (reviewed) {
      return <Badge variant="success" className="text-[10px]"><CheckCircleIcon className="h-3 w-3 mr-0.5" />已审核</Badge>
    }
    return <Badge variant="secondary" className="text-[10px]">待审核</Badge>
  }

  return (
    <div className="space-y-6">
      {/* 控制栏 */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Input
                placeholder="实体 ID 过滤..."
                value={entityFilter}
                onChange={(e) => { setEntityFilter(e.target.value); setPage(0) }}
                className="max-w-[140px]"
                type="number"
              />
              <select
                value={reviewFilter}
                onChange={(e) => { setReviewFilter(e.target.value); setPage(0) }}
                className="rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                <option value="">全部状态</option>
                <option value="false">待审核</option>
                <option value="true">已审核</option>
              </select>
              <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                <RefreshCwIcon className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>

            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <PlusIcon className="h-3.5 w-3.5" />
              新建注解
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 错误 */}
      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-center">
          <AlertTriangleIcon className="mx-auto mb-1 h-6 w-6 text-destructive" />
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="link" onClick={load} className="mt-2">重试</Button>
        </div>
      )}

      {/* 加载 */}
      {loading && !error && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {/* 列表 */}
      {!loading && !error && (
        <>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">
                注解列表 {total > 0 && <span className="text-muted-foreground font-normal">({total})</span>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {annotations.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">暂无注解记录</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>实体</TableHead>
                      <TableHead>字段</TableHead>
                      <TableHead>变更</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>创建者</TableHead>
                      <TableHead>时间</TableHead>
                      <TableHead>状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {annotations.map((a) => (
                      <TableRow
                        key={a.id}
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}
                      >
                        <TableCell className="font-mono text-xs">{a.id}</TableCell>
                        <TableCell>
                          <span className="font-medium">{a.canonical_name || `#${a.entity_id}`}</span>
                          {a.event_id && (
                            <div className="text-[10px] text-muted-foreground font-mono">事件: {a.event_id}</div>
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{a.field}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1 text-xs">
                            {a.old_value && <span className="text-destructive line-through decoration-destructive/40">{a.old_value}</span>}
                            {a.old_value && a.new_value && <span className="text-muted-foreground">→</span>}
                            {a.new_value && <span className="text-emerald-600">{a.new_value}</span>}
                            {!a.old_value && !a.new_value && <span className="text-muted-foreground">-</span>}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[10px]">{a.annotation_type}</Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{a.created_by}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {a.created_at ? new Date(a.created_at).toLocaleDateString("zh-CN") : "-"}
                        </TableCell>
                        <TableCell>{reviewBadge(a.reviewed)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* 分页 */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                第 {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, total)} 条，共 {total} 条
              </p>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage(page - 1)}
                >
                  <ChevronLeftIcon className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage(page + 1)}
                >
                  <ChevronRightIcon className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── 新建注解 Dialog ─────────────────────────────── */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建注解</DialogTitle>
            <DialogDescription>
              创建一条人工标注记录，用于修正或补充实体信息。
            </DialogDescription>
          </DialogHeader>
          <form ref={createFormRef} onSubmit={handleCreate}>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium">实体 ID *</label>
                  <Input name="entity_id" type="number" required placeholder="例如 42" className="mt-1" />
                </div>
                <div>
                  <label className="text-xs font-medium">字段 *</label>
                  <Input name="field" required placeholder="canonical_name / entity_type" className="mt-1" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium">旧值</label>
                  <Input name="old_value" placeholder="原值" className="mt-1" />
                </div>
                <div>
                  <label className="text-xs font-medium">新值</label>
                  <Input name="new_value" placeholder="修正值" className="mt-1" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium">关联事件 ID</label>
                  <Input name="event_id" placeholder="可选" className="mt-1" />
                </div>
                <div>
                  <label className="text-xs font-medium">注解类型</label>
                  <Input name="annotation_type" defaultValue="manual" className="mt-1" />
                </div>
              </div>
              {createError && (
                <p className="text-sm text-destructive bg-destructive/5 rounded-md p-2">{createError}</p>
              )}
            </div>
            <DialogFooter className="mt-6">
              <Button variant="outline" size="sm" type="button" onClick={() => setCreateOpen(false)} disabled={createLoading}>
                取消
              </Button>
              <Button size="sm" type="submit" disabled={createLoading}>
                {createLoading && <Loader2Icon className="h-3.5 w-3.5 mr-1 animate-spin" />}
                创建
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
