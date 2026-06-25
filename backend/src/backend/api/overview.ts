/**
 * BFF Overview — 管理总览 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"
import type { RunLogEntry } from "./diagnostics"
import type { AdminTargetInfo } from "./targets"

export interface AdminOverviewResponse {
  target_id: string
  targets: AdminTargetInfo[]
  collector: Record<string, unknown>
  diagnostics: Record<string, unknown>
  source_health: { total: number; unhealthy: number; items: SourceHealthItem[] }
  recent_runs: RunLogEntry[]
  feedback: Record<string, number>
  alerts: { total: number; items: unknown[] }
  generated_at: string
}

export interface SourceHealthItem {
  source_ref?: string
  source_id?: string
  status?: string
  [key: string]: unknown
}

export async function fetchOverview(targetId?: string): Promise<AdminOverviewResponse> {
  const params = new URLSearchParams()
  if (targetId) params.set("target_id", targetId)
  const url = apiUrl(`/admin/overview${params.size ? `?${params}` : ""}`)
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `Overview fetch failed (${res.status})`)
  return res.json()
}
