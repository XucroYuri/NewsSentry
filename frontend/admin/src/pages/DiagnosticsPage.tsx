import { useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  RefreshCwIcon,
  ServerIcon,
  DatabaseIcon,
  RadioIcon,
  ClockIcon,
  ActivityIcon,
  KeyIcon,
  XCircleIcon,
} from "lucide-react"

import {
  fetchDiagnostics,
  type DiagnosticsResponse,
} from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"

export default function DiagnosticsPage() {
  const [data, setData] = useState<DiagnosticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchDiagnostics())
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
          {Array.from({ length: 8 }).map((_, i) => (
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
        <Button variant="link" onClick={load} className="mt-3">重试</Button>
      </div>
    )
  }

  const d = data
  const collectorOk = d.collector.enabled && d.collector.running
  const healthOk = d.source_health.unhealthy === 0 && d.source_health.total > 0
  const hasEvents = d.events.total > 0

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">可观测性诊断</h2>
          <p className="text-sm text-muted-foreground">
            部署: {d.deploy.commit} · 构建: {d.deploy.build}
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
            <RadioIcon className={`h-4 w-4 ${collectorOk ? "text-emerald-500" : "text-amber-500"}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${collectorOk ? "text-emerald-500" : "text-amber-500"}`}>
              {collectorOk ? "运行中" : d.collector.enabled ? "已启用" : "未启用"}
            </div>
            <p className="text-xs text-muted-foreground">
              {d.collector.running ? "正在采集" : "空闲"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">AI Key</CardTitle>
            <KeyIcon className={`h-4 w-4 ${d.ai_key_configured ? "text-emerald-500" : "text-destructive"}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${d.ai_key_configured ? "text-emerald-500" : "text-destructive"}`}>
              {d.ai_key_configured ? "已配置" : "未配置"}
            </div>
            <p className="text-xs text-muted-foreground">
              GEMINI/DEEPSEEK/GROQ
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">信源健康</CardTitle>
            {healthOk ? (
              <CheckCircleIcon className="h-4 w-4 text-emerald-500" />
            ) : (
              <XCircleIcon className="h-4 w-4 text-destructive" />
            )}
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">
              {d.source_health.healthy}/{d.source_health.total}
            </div>
            <p className="text-xs text-muted-foreground">
              健康 {d.source_health.healthy} · 异常 {d.source_health.unhealthy}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">事件总数</CardTitle>
            <DatabaseIcon className={`h-4 w-4 ${hasEvents ? "text-emerald-500" : "text-muted-foreground"}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{d.events.total.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">
              {d.events.latest_collected_at
                ? `最新: ${new Date(d.events.latest_collected_at).toLocaleString("zh-CN")}`
                : "暂无数据"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 采集详情 + 最后运行 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">采集器详情</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">状态</span>
                <Badge variant={collectorOk ? "success" : "secondary"}>
                  {collectorOk ? "运行中" : d.collector.enabled ? "已启用" : "已停用"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">上次运行</span>
                <span className="text-sm">
                  {d.collector.last_run_at
                    ? new Date(d.collector.last_run_at).toLocaleString("zh-CN")
                    : "-"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">下次运行</span>
                <span className="text-sm">
                  {d.collector.next_run_at
                    ? new Date(d.collector.next_run_at).toLocaleString("zh-CN")
                    : "-"}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">数据目录</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">根目录</span>
                <span className="text-xs font-mono">{d.data.directory}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Target 数量</span>
                <span className="text-sm">{d.data.target_count}</span>
              </div>
              {d.data.targets.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {d.data.targets.map((tid) => (
                    <Badge key={tid} variant="secondary" className="text-xs">
                      {tid}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">无 target 目录</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 信源健康 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">信源健康审计</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 sm:grid-cols-3">
            <div className="flex flex-col items-center gap-2 rounded-lg bg-emerald-500/10 py-6">
              <CheckCircleIcon className="h-6 w-6 text-emerald-500" />
              <div className="text-2xl font-bold text-emerald-500">{d.source_health.healthy}</div>
              <span className="text-xs text-muted-foreground">健康信源</span>
            </div>
            <div className="flex flex-col items-center gap-2 rounded-lg bg-destructive/10 py-6">
              <XCircleIcon className="h-6 w-6 text-destructive" />
              <div className="text-2xl font-bold text-destructive">{d.source_health.unhealthy}</div>
              <span className="text-xs text-muted-foreground">异常信源</span>
            </div>
            <div className="flex flex-col items-center gap-2 rounded-lg bg-muted py-6">
              <ActivityIcon className="h-6 w-6 text-muted-foreground" />
              <div className="text-2xl font-bold">{d.source_health.total}</div>
              <span className="text-xs text-muted-foreground">总计</span>
            </div>
          </div>
          {d.source_health.total === 0 && (
            <div className="mt-4 flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-600">
              <AlertTriangleIcon className="h-4 w-4 shrink-0" />
              暂无信源健康数据。运行一次采集后生成。
            </div>
          )}
        </CardContent>
      </Card>

      {/* 最近运行 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">最近运行 (最多 5 条)</CardTitle>
        </CardHeader>
        <CardContent>
          {d.recent_runs.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>运行 ID</TableHead>
                  <TableHead>开始时间</TableHead>
                  <TableHead>耗时</TableHead>
                  <TableHead>采集事件</TableHead>
                  <TableHead>状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.recent_runs.map((run, i) => (
                  <TableRow key={run.run_id ?? i}>
                    <TableCell className="font-mono text-xs">{run.run_id ?? `#${i + 1}`}</TableCell>
                    <TableCell>
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString("zh-CN")
                        : "-"}
                    </TableCell>
                    <TableCell>
                      {run.duration_ms != null && typeof run.duration_ms === "number"
                        ? `${(run.duration_ms / 1000).toFixed(1)}s`
                        : "-"}
                    </TableCell>
                    <TableCell>{String(run.events_collected ?? "-")}</TableCell>
                    <TableCell>
                      <Badge variant={run.status === "completed" ? "success" : "secondary"}>
                        {run.status ?? "unknown"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              <ClockIcon className="h-4 w-4 shrink-0" />
              暂无运行记录
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
