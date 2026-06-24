import { useEffect, useState } from "react"
import {
  ActivityIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  GlobeIcon,
  MessageSquareIcon,
  RadioIcon,
  RefreshCwIcon,
} from "lucide-react"

import { fetchAdminOverview, type AdminOverviewResponse } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"

export default function DashboardOverview() {
  const [data, setData] = useState<AdminOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchAdminOverview())
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
        <AlertTriangleIcon className="mx-auto mb-2 h-8 w-8 text-destructive" />
        <p className="text-sm text-destructive">{error ?? "无数据"}</p>
        <button
          onClick={load}
          className="mt-3 text-sm text-primary hover:underline"
        >
          重试
        </button>
      </div>
    )
  }

  const d = data
  const collector = d.collector ?? {}
  const unhealthyCount = d.source_health?.unhealthy ?? 0
  const healthTotal = d.source_health?.total ?? 0

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">管理总览</h2>
          <p className="text-sm text-muted-foreground">
            当前目标: {d.target_id || "未选择"} | 生成时间:{" "}
            {new Date(d.generated_at).toLocaleString("zh-CN")}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon className="h-3.5 w-3.5" />
          刷新
        </Button>
      </div>

      {/* 统计卡片 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">采集器</CardTitle>
            <RadioIcon className={`h-4 w-4 ${collector.enabled ? "text-primary" : "text-amber-500"}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${collector.enabled ? "text-primary" : "text-amber-500"}`}>
              {collector.enabled ? "已启用" : "未启用"}
            </div>
            <p className="text-xs text-muted-foreground">
              {collector.running ? "运行中" : "空闲"} · {String(collector.stage ?? "collect")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">监控目标</CardTitle>
            <GlobeIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{d.targets?.length ?? 0}</div>
            <p className="text-xs text-muted-foreground">{d.target_id || "未选择"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">信源异常</CardTitle>
            <AlertTriangleIcon className={`h-4 w-4 ${unhealthyCount > 0 ? "text-destructive" : "text-muted-foreground"}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${unhealthyCount > 0 ? "text-destructive" : ""}`}>
              {unhealthyCount}
            </div>
            <p className="text-xs text-muted-foreground">{healthTotal} 条健康记录</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">待关注</CardTitle>
            <MessageSquareIcon className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">
              {(d.feedback?.total ?? 0) + (d.alerts?.total ?? 0)}
            </div>
            <p className="text-xs text-muted-foreground">
              反馈 {d.feedback?.total ?? 0} · 告警 {d.alerts?.total ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Target 列表 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">监控目标</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>目标 ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>语言</TableHead>
                <TableHead>信源数</TableHead>
                <TableHead>事件数</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.targets?.map((t) => (
                <TableRow key={t.target_id}>
                  <TableCell className="font-mono text-xs">{t.target_id}</TableCell>
                  <TableCell>{t.display_name}</TableCell>
                  <TableCell className="text-muted-foreground">{t.primary_language ?? "-"}</TableCell>
                  <TableCell>{t.source_count ?? "-"}</TableCell>
                  <TableCell>{t.event_count ?? "-"}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        typeof t.lifecycle === "object" && t.lifecycle !== null &&
                        (t.lifecycle as Record<string, unknown>).status === "archived"
                          ? "secondary"
                          : "success"
                      }
                    >
                      {typeof t.lifecycle === "object" && t.lifecycle !== null &&
                      (t.lifecycle as Record<string, unknown>).status === "archived"
                        ? "已归档"
                        : "活跃"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 健康状态 + 最近运行 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">信源健康</CardTitle>
          </CardHeader>
          <CardContent>
            {d.source_health?.items?.length ? (
              <div className="space-y-1">
                {d.source_health.items.map((item, i) => (
                  <div
                    key={item.source_ref ?? item.source_id ?? i}
                    className="flex items-center gap-3 py-1.5"
                  >
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        !item.status || item.status === "ok" || item.status === "healthy"
                          ? "bg-emerald-500"
                          : "bg-destructive"
                      }`}
                    />
                    <span className="flex-1 text-sm">
                      {item.source_ref ?? item.source_id ?? "未知信源"}
                    </span>
                    <span className="text-xs text-muted-foreground">{item.status ?? "unknown"}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">无健康记录</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">最近运行</CardTitle>
          </CardHeader>
          <CardContent>
            {d.recent_runs?.length ? (
              <div className="space-y-1">
                {d.recent_runs.map((run, i) => (
                  <div
                    key={run.run_id ?? i}
                    className="flex items-center gap-3 py-1.5"
                  >
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        run.status === "ok" || run.status === "success"
                          ? "bg-emerald-500"
                          : "bg-destructive"
                      }`}
                    />
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
    </div>
  )
}
