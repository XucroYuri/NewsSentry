import { useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  ArrowUpRightIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react"

import { fetchAdminTargets, type AdminTargetInfo } from "@/lib/api"

export default function TargetList({
  onNavigate,
}: {
  onNavigate?: (targetId: string) => void
}) {
  const [targets, setTargets] = useState<AdminTargetInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAdminTargets()
      setTargets(data.targets ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filtered = targets.filter((t) => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return (
      t.target_id.toLowerCase().includes(q) ||
      (t.display_name ?? "").toLowerCase().includes(q)
    )
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2Icon className="mr-2 h-5 w-5 animate-spin text-muted-foreground" />
        <span className="text-muted-foreground">加载中...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
        <AlertTriangleIcon className="mx-auto mb-2 h-8 w-8 text-destructive" />
        <p className="text-sm text-destructive">{error}</p>
        <button onClick={load} className="mt-3 text-sm text-primary hover:underline">
          重试
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">目标工作台</h2>
          <p className="text-sm text-muted-foreground">
            {targets.length} 个监控目标
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <SearchIcon className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索 ID 或名称..."
              className="h-8 rounded-md border border-border bg-background pl-8 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            <PlusIcon className="h-3.5 w-3.5" />
            新建
          </button>
          <button
            onClick={load}
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary"
          >
            <RefreshCwIcon className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
      </div>

      {/* Target 表格 */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border border-border py-16 text-center text-sm text-muted-foreground">
          {search.trim() ? "无匹配结果" : "暂无监控目标"}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium">目标 ID</th>
                <th className="px-4 py-2.5 text-left font-medium">名称</th>
                <th className="px-4 py-2.5 text-left font-medium">类型</th>
                <th className="px-4 py-2.5 text-left font-medium">语言</th>
                <th className="px-4 py-2.5 text-left font-medium">信源</th>
                <th className="px-4 py-2.5 text-left font-medium">事件</th>
                <th className="px-4 py-2.5 text-left font-medium">状态</th>
                <th className="px-4 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((t) => (
                <tr key={t.target_id} className="hover:bg-muted/30">
                  <td className="px-4 py-2.5 font-mono text-xs">
                    {t.target_id}
                  </td>
                  <td className="px-4 py-2.5 font-medium">{t.display_name}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">
                    {t.monitoring_type ?? t.region_type ?? "-"}
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">
                    {t.primary_language ?? "-"}
                  </td>
                  <td className="px-4 py-2.5">{t.source_count ?? "-"}</td>
                  <td className="px-4 py-2.5">{t.event_count ?? "-"}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        (
                          typeof t.lifecycle === "object" &&
                          t.lifecycle !== null &&
                          (t.lifecycle as Record<string, unknown>).status === "archived"
                        )
                          ? "bg-muted text-muted-foreground"
                          : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
                      }`}
                    >
                      {typeof t.lifecycle === "object" &&
                      t.lifecycle !== null &&
                      (t.lifecycle as Record<string, unknown>).status === "archived"
                        ? "已归档"
                        : "活跃"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                      onClick={() => onNavigate?.(t.target_id)}
                    >
                      <ArrowUpRightIcon className="h-3 w-3" />
                      详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
