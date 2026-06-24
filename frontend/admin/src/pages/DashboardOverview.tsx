import { useEffect, useState } from "react"
import {
  ActivityIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  GlobeIcon,
  Loader2Icon,
  MessageSquareIcon,
  RadioIcon,
  RefreshCwIcon,
} from "lucide-react"

import { fetchAdminOverview, type AdminOverviewResponse } from "@/lib/api"

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
      <div className="flex items-center justify-center py-24">
        <Loader2Icon className="mr-2 h-5 w-5 animate-spin text-muted-foreground" />
        <span className="text-muted-foreground">加载中...</span>
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
        <button
          onClick={load}
          className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary"
        >
          <RefreshCwIcon className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>

      {/* 统计卡片 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={RadioIcon}
          label="采集器"
          value={collector.enabled ? "已启用" : "未启用"}
          detail={`${collector.running ? "运行中" : "空闲"} · ${collector.stage ?? "collect"}`}
          variant={collector.enabled ? "ok" : "warn"}
        />
        <StatCard
          icon={GlobeIcon}
          label="监控目标"
          value={String(d.targets?.length ?? 0)}
          detail={d.target_id || "未选择"}
          variant="ok"
        />
        <StatCard
          icon={AlertTriangleIcon}
          label="信源异常"
          value={String(unhealthyCount)}
          detail={`${healthTotal} 条健康记录`}
          variant={unhealthyCount > 0 ? "danger" : "ok"}
        />
        <StatCard
          icon={MessageSquareIcon}
          label="待关注"
          value={String((d.feedback?.total ?? 0) + (d.alerts?.total ?? 0))}
          detail={`反馈 ${d.feedback?.total ?? 0} · 告警 ${d.alerts?.total ?? 0}`}
          variant="ok"
        />
      </div>

      {/* Target 列表 */}
      <Section title="监控目标">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium">目标 ID</th>
                <th className="px-4 py-2.5 text-left font-medium">名称</th>
                <th className="px-4 py-2.5 text-left font-medium">语言</th>
                <th className="px-4 py-2.5 text-left font-medium">信源数</th>
                <th className="px-4 py-2.5 text-left font-medium">事件数</th>
                <th className="px-4 py-2.5 text-left font-medium">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {d.targets?.map((t) => (
                <tr key={t.target_id} className="hover:bg-muted/30">
                  <td className="px-4 py-2 font-mono text-xs">{t.target_id}</td>
                  <td className="px-4 py-2">{t.display_name}</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {t.primary_language ?? "-"}
                  </td>
                  <td className="px-4 py-2">{t.source_count ?? "-"}</td>
                  <td className="px-4 py-2">{t.event_count ?? "-"}</td>
                  <td className="px-4 py-2">
                    <StatusBadge
                      status={
                        typeof t.lifecycle === "object" && t.lifecycle !== null
                          ? (t.lifecycle as Record<string, unknown>).status
                          : undefined
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* 健康状态 + 最近运行 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="信源健康">
          {d.source_health?.items?.length ? (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {d.source_health.items.map((item, i) => (
                <li
                  key={item.source_ref ?? item.source_id ?? i}
                  className="flex items-center gap-3 px-4 py-2.5"
                >
                  <StatusDot
                    ok={
                      !item.status ||
                      item.status === "ok" ||
                      item.status === "healthy"
                    }
                  />
                  <span className="flex-1 text-sm">
                    {item.source_ref ?? item.source_id ?? "未知信源"}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.status ?? "unknown"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">无健康记录</p>
          )}
        </Section>

        <Section title="最近运行">
          {d.recent_runs?.length ? (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {d.recent_runs.map((run, i) => (
                <li
                  key={run.run_id ?? i}
                  className="flex items-center gap-3 px-4 py-2.5"
                >
                  <StatusDot ok={run.status === "ok" || run.status === "success"} />
                  <span className="flex-1 text-sm font-mono text-xs">
                    {run.run_id ?? `#${i + 1}`}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString("zh-CN")
                      : "-"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">无运行记录</p>
          )}
        </Section>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
  variant,
}: {
  icon: typeof RadioIcon
  label: string
  value: string
  detail: string
  variant: "ok" | "warn" | "danger"
}) {
  const colorMap = {
    ok: "text-primary",
    warn: "text-amber-500",
    danger: "text-destructive",
  }
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className={`h-4 w-4 ${colorMap[variant]}`} />
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold ${colorMap[variant]}`}>
        {value}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
    </div>
  )
}

function StatusBadge({ status }: { status?: unknown }) {
  const s = typeof status === "string" ? status : "active"
  const isArchived = s === "archived"
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        isArchived
          ? "bg-muted text-muted-foreground"
          : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
      }`}
    >
      {isArchived ? "已归档" : "活跃"}
    </span>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${
        ok ? "bg-emerald-500" : "bg-destructive"
      }`}
    />
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold tracking-tight">{title}</h3>
      {children}
    </div>
  )
}
