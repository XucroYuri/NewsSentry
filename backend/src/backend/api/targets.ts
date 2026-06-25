/**
 * BFF Targets — 目标工作台管理 API 调用。
 */

import { apiUrl, authHeaders, throwApiError, AdminApiError } from "./util"

export interface AdminTargetInfo {
  target_id: string
  display_name: string
  primary_language?: string
  region_type?: string
  monitoring_type?: string
  lifecycle?: Record<string, unknown>
  source_count?: number
  event_count?: number
  archived?: boolean
  [key: string]: unknown
}

export interface AdminTargetListResponse {
  targets: AdminTargetInfo[]
}

export interface TargetCreateRequest {
  target_id: string
  display_name: string
  mode: "template" | "clone"
  language_scope?: string
  timezone?: string
  monitoring_type?: string
  region_type?: string
  source_target_id?: string
}

export async function fetchTargets(includeArchived = false): Promise<AdminTargetListResponse> {
  const params = includeArchived ? "?include_archived=true" : ""
  const res = await fetch(apiUrl(`/admin/targets${params}`), {
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Target list failed (${res.status})`)
  return res.json()
}

export async function probeTargets(): Promise<Response> {
  return fetch(apiUrl("/admin/targets"))
}

export async function probeTargetsWithAuth(token: string): Promise<Response> {
  return fetch(apiUrl("/admin/targets"), {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function createTarget(payload: TargetCreateRequest): Promise<{ target_id: string }> {
  const res = await fetch(apiUrl("/admin/targets"), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    await throwApiError(res, `创建失败 (${res.status})`)
  }
  return res.json()
}

export async function archiveTarget(targetId: string): Promise<void> {
  const res = await fetch(apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/archive`), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `归档失败 (${res.status})`)
}

export async function restoreTarget(targetId: string): Promise<void> {
  const res = await fetch(apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/restore`), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `恢复失败 (${res.status})`)
}

export interface TargetOverviewResponse {
  target: AdminTargetInfo
  profile: Record<string, unknown>
  sources: { total: number; active: number; archived: number; missing_refs: number; unreferenced_files: number }
  social: { dimensions: number; accounts: number; archived_accounts: number }
  events: { total: number }
  classification_diagnostics: Record<string, unknown>
  recent_runs: Array<{ run_id?: string; started_at?: string; status?: string; [key: string]: unknown }>
  validation: Record<string, unknown>
  collector: Record<string, unknown>
}

export async function fetchTargetOverview(targetId: string): Promise<TargetOverviewResponse> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/overview`),
    { headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `Target overview failed (${res.status})`)
  return res.json()
}
