/**
 * News Sentry Admin Console — API client
 *
 * 所有管理后台 API 调用在此集中管理。
 * 通过 locals-settings.ts 的 resolveUrl() 支持 API 数据源切换。
 */

import { resolveUrl } from "./locals-settings"

const API_V1 = "/api/v1"

// ── 类型化错误 ──────────────────────────────────────

/** Admin API 统一错误类型，携带 HTTP 状态码和后端 detail 信息。 */
export class AdminApiError extends Error {
  statusCode: number
  detail: string

  constructor(statusCode: number, detail: string) {
    super(`[${statusCode}] ${detail}`)
    this.name = "AdminApiError"
    this.statusCode = statusCode
    this.detail = detail
  }

  get isAuthError(): boolean {
    return this.statusCode === 401 || this.statusCode === 403
  }

  get isServerError(): boolean {
    return this.statusCode >= 500
  }
}

/** 从 fetch Response 提取后端统一错误格式（error/detail/status_code JSON）。 */
async function throwApiError(res: Response, fallback: string): Promise<never> {
  let errorBody: { error?: string; detail?: string; status_code?: number } = {}
  try {
    errorBody = await res.json()
  } catch {
    // 无法解析 JSON，回退
  }
  const detail = errorBody.detail ?? errorBody.error ?? fallback
  const statusCode = errorBody.status_code ?? res.status
  throw new AdminApiError(statusCode, detail)
}

/** 将相对 API 路径转为完整 URL（支持 Cloudflare Worker 切换）。 */
function apiUrl(path: string): string {
  return resolveUrl(`${API_V1}${path}`)
}

export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("news_sentry_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── Auth ────────────────────────────────────────────

export interface LoginResponse {
  access_token: string
  token_type: string
  role: string
  must_change_password?: boolean
}

export async function loginAdmin(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const res = await fetch(apiUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    if (res.status === 429) throw new AdminApiError(429, "登录尝试过于频繁，请 5 分钟后再试")
    await throwApiError(
      res,
      res.status === 401 ? "用户名或密码错误" : `登录失败 (${res.status})`,
    )
  }
  return res.json()
}

// ── Overview ────────────────────────────────────────

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

export interface SourceHealthItem {
  source_ref?: string
  source_id?: string
  status?: string
  [key: string]: unknown
}

export interface RunLogEntry {
  run_id?: string
  started_at?: string
  status?: string
  [key: string]: unknown
}

export async function fetchAdminOverview(
  targetId?: string,
): Promise<AdminOverviewResponse> {
  const params = new URLSearchParams()
  if (targetId) params.set("target_id", targetId)
  const url = apiUrl(`/admin/overview${params.size ? `?${params}` : ""}`)
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `Overview fetch failed (${res.status})`)
  return res.json()
}

// ── Targets ─────────────────────────────────────────

export interface AdminTargetListResponse {
  targets: AdminTargetInfo[]
}

export async function fetchAdminTargets(
  includeArchived = false,
): Promise<AdminTargetListResponse> {
  const params = includeArchived ? "?include_archived=true" : ""
  const res = await fetch(apiUrl(`/admin/targets${params}`), {
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Target list failed (${res.status})`)
  return res.json()
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

export async function createTarget(
  payload: TargetCreateRequest,
): Promise<{ target_id: string }> {
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

// ── Inventory ────────────────────────────────────────

export interface SourceInventoryItem {
  source_id: string
  source_ref?: string
  type?: string
  name?: string
  display_name?: string
  url?: string
  language?: string
  archived?: boolean
  status?: string
  missing_file?: boolean
  [key: string]: unknown
}

export interface SourceInventoryResponse {
  target_id: string
  summary: {
    standard_sources: number
    active: number
    archived: number
    missing_refs: number
    unreferenced_files: number
    social_dimensions: number
    social_accounts: number
  }
  sources: SourceInventoryItem[]
}

export async function fetchTargetInventory(
  targetId: string,
): Promise<SourceInventoryResponse> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/inventory`),
    { headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `Inventory fetch failed (${res.status})`)
  return res.json()
}

export async function validateTarget(targetId: string): Promise<Record<string, unknown>> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/validate`),
    { method: "POST", headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `Validate failed (${res.status})`)
  return res.json()
}

// ── Collector ────────────────────────────────────────

export interface CollectorStatusResponse {
  enabled: boolean
  running: boolean
  stage: string
  [key: string]: unknown
}

export async function fetchCollectorStatus(): Promise<CollectorStatusResponse> {
  const res = await fetch(apiUrl("/collector/status"), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `Collector status failed (${res.status})`)
  return res.json()
}

export async function startCollector(): Promise<void> {
  const res = await fetch(apiUrl("/collector/start"), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Start collector failed (${res.status})`)
}

export async function stopCollector(): Promise<void> {
  const res = await fetch(apiUrl("/collector/stop"), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Stop collector failed (${res.status})`)
}

// ── Users ────────────────────────────────────────────

export interface AdminUser {
  username: string
  role: string
  created_at?: string
  must_change_password?: boolean
  [key: string]: unknown
}

export interface AdminUserListResponse {
  users: AdminUser[]
}

export async function fetchAdminUsers(): Promise<AdminUserListResponse> {
  const res = await fetch(apiUrl("/admin/users"), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `User list failed (${res.status})`)
  return res.json()
}

export async function createAdminUser(payload: {
  username: string
  password: string
  role?: string
}): Promise<void> {
  const res = await fetch(apiUrl("/admin/users"), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new AdminApiError(res.status, (detail as any)?.detail ?? `创建用户失败 (${res.status})`)
  }
}

export async function deleteAdminUser(username: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/admin/users/${encodeURIComponent(username)}`),
    { method: "DELETE", headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `删除用户失败 (${res.status})`)
}

export async function resetUserPassword(
  username: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch(
    apiUrl(`/admin/users/${encodeURIComponent(username)}/reset-password`),
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    },
  )
  if (!res.ok) throw new AdminApiError(res.status, `重置密码失败 (${res.status})`)
}

// ── Diagnostics ──────────────────────────────────────

export interface DiagnosticsDeploy {
  commit: string
  build: string
}

export interface DiagnosticsCollector {
  enabled: boolean
  running: boolean
  last_run_at: string | null
  next_run_at: string | null
}

export interface DiagnosticsData {
  directory: string
  target_count: number
  targets: string[]
}

export interface DiagnosticsSourceHealth {
  healthy: number
  unhealthy: number
  total: number
}

export interface DiagnosticsEvents {
  total: number
  latest_collected_at: string | null
}

export interface DiagnosticsResponse {
  deploy: DiagnosticsDeploy
  collector: DiagnosticsCollector
  ai_key_configured: boolean
  data: DiagnosticsData
  source_health: DiagnosticsSourceHealth
  events: DiagnosticsEvents
  recent_runs: RunLogEntry[]
}

/** 获取全局可观测性诊断摘要（无需认证）。 */
export async function fetchDiagnostics(): Promise<DiagnosticsResponse> {
  const res = await fetch(apiUrl("/diagnostics"))
  if (!res.ok) throw new AdminApiError(res.status, `诊断查询失败 (${res.status})`)
  return res.json()
}
