import { useEffect, useState } from "react"
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  GlobeIcon,
  Loader2Icon,
  RssIcon,
  UsersIcon,
} from "lucide-react"

import { authHeaders } from "@/lib/api"

const API_BASE = "/api/v1"

interface TargetOverviewResponse {
  target: AdminTargetInfo
  profile: Record<string, unknown>
  sources: { total: number; active: number; archived: number; missing_refs: number; unreferenced_files: number }
  social: { dimensions: number; accounts: number; archived_accounts: number }
  events: { total: number }
  classification_diagnostics: Record<string, unknown>
  recent_runs: RunLogEntry[]
  validation: Record<string, unknown>
  collector: Record<string, unknown>
}

interface AdminTargetInfo {
  target_id: string
  display_name: string
  primary_language?: string
  monitoring_type?: string
  lifecycle?: Record<string, unknown>
  source_count?: number
  event_count?: number
  archived?: boolean
}

interface RunLogEntry {
  run_id?: string
  started_at?: string
  status?: string
  [key: string]: unknown
}

export default function TargetDetail({ targetId, onBack }: { targetId: string; onBack: () => void }) {
  const [data, setData] = useState<TargetOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/admin/targets/${encodeURIComponent(targetId)}/overview`, {
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(`请求失败 (${res.status})`)
      setData(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [targetId])

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
        <button onClick={load} className="mt-3 text-sm text-primary hover:underline">重试</button>
      </div>
    )
  }

  const d = data
  const t = d.target

  const archivedStatus: string =
    typeof t.lifecycle === "object" && t.lifecycle !== null
      ? String((t.lifecycle as Record<string, unknown>).status ?? "")
      : ""

  const isArchived = archivedStatus === "archived"
  const monitoringTypeText: string = t.monitoring_type ?? "country"
  const languageText: string = t.primary_language ?? "N/A"
  const sourceTotalText: string = String(d.sources.total)
  const sourceActiveText: string = String(d.sources.active)
  const eventTotalText: string = String(d.events.total)
  const socialAccountsText: string = String(d.social.accounts)
  const socialDimensionsText: string = String(d.social.dimensions)
  const collectorEnabled: string = String(!!d.collector.enabled ? "已启用" : "未启用")
  const collectorRunning: string = String(!!d.collector.running ? "运行中" : "空闲")
  const collectorStageText: string = String(d.collector.stage ?? "—")
  const integrityValueText: string = d.sources.missing_refs > 0 ? String(d.sources.missing_refs) : "pass"
  const integrityDetailText: string = d.sources.missing_refs > 0 ? "缺失引用" : "一切正常"
  const integrityVariant: "ok" | "warn" = d.sources.missing_refs > 0 ? "warn" : "ok"

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-sm text-muted-foreground hover:bg-secondary"
        >
          <ArrowLeftIcon className="h-3.5 w-3.5" />
          返回
        </button>
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{t.display_name}</h2>
          <p className="text-sm text-muted-foreground">
            <code className="font-mono text-xs">{t.target_id}</code>
            {" · " + monitoringTypeText + " · " + languageText}
            {isArchived && (
              <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                已归档
              </span>
            )}
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={RssIcon} label="活跃信源" value={sourceActiveText} detail={`共 ${sourceTotalText} 个`} variant="ok" />
        <StatCard icon={GlobeIcon} label="事件" value={eventTotalText} detail="最新数据集" variant="ok" />
        <StatCard icon={UsersIcon} label="社媒" value={socialAccountsText} detail={`${socialDimensionsText} 维度`} variant="ok" />
        <StatCard
          icon={d.sources.missing_refs > 0 ? AlertTriangleIcon : CheckCircleIcon}
          label="数据完整性"
          value={integrityValueText}
          detail={integrityDetailText}
          variant={integrityVariant}
        />
      </div>

      <Section title="采集器">
        <div className="flex items-center gap-6 text-sm">
          {d.collector.enabled ? (
            <span className="flex items-center gap-2">
              <StatusDot ok />
              <span className="text-muted-foreground">状态</span>
              <span className="font-medium">{collectorEnabled}</span>
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <StatusDot ok={false} />
              <span className="text-muted-foreground">状态</span>
              <span className="font-medium">{collectorEnabled}</span>
            </span>
          )}
          {d.collector.running ? (
            <span className="flex items-center gap-2">
              <StatusDot ok />
              <span className="text-muted-foreground">运行</span>
              <span className="font-medium">{collectorRunning}</span>
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <StatusDot ok={false} />
              <span className="text-muted-foreground">运行</span>
              <span className="font-medium">{collectorRunning}</span>
            </span>
          )}
          <span className="text-muted-foreground">
            阶段: {collectorStageText}
          </span>
        </div>
      </Section>

      {Boolean(d.classification_diagnostics?.distribution) && (
        <Section title="分类分布">
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-4 py-2.5 text-left font-medium">类别</th>
                  <th className="px-4 py-2.5 text-right font-medium">计数</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {Object.entries(
                  d.classification_diagnostics.distribution as Record<string, number>
                ).map(([cat, count]) => (
                  <tr key={cat} className="hover:bg-muted/30">
                    <td className="px-4 py-2.5 font-medium">{cat}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="最近运行">
        {d.recent_runs?.length ? (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {d.recent_runs.map((run, i) => (
              <li key={run.run_id ?? i} className="flex items-center gap-3 px-4 py-2.5">
                <StatusDot ok={run.status === "ok" || run.status === "success"} />
                <span className="flex-1 font-mono text-xs">{run.run_id ?? `#${i + 1}`}</span>
                <span className="text-xs text-muted-foreground">
                  {run.started_at ? new Date(run.started_at).toLocaleString("zh-CN") : "-"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">无运行记录</p>
        )}
      </Section>
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
  icon: typeof RssIcon
  label: string
  value: string
  detail: string
  variant: "ok" | "warn" | "danger"
}) {
  const colorMap: Record<string, string> = {
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
      <div className={`mt-1 text-2xl font-semibold ${colorMap[variant]}`}>{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
    </div>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold tracking-tight">{title}</h3>
      {children}
    </div>
  )
}
