/**
 * News Sentry Admin Console — API client
 *
 * 所有管理后台 API 调用在此集中管理。
 */

const API_BASE = "/api/v1"

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
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    if (res.status === 429) throw new Error("登录尝试过于频繁，请 5 分钟后再试")
    throw new Error(res.status === 401 ? "用户名或密码错误" : `登录失败 (${res.status})`)
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
  const url = `${API_BASE}/admin/overview${params.size ? `?${params}` : ""}`
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) throw new Error(`Overview fetch failed (${res.status})`)
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
  const res = await fetch(`${API_BASE}/admin/targets${params}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Target list failed (${res.status})`)
  return res.json()
}
