/**
 * BFF Diagnostics — 可观测性诊断 API 调用（无需认证）。
 */

import { apiUrl, AdminApiError } from "./util"

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

export interface RunLogEntry {
  run_id?: string
  started_at?: string
  status?: string
  [key: string]: unknown
}

export async function fetchDiagnostics(): Promise<DiagnosticsResponse> {
  const res = await fetch(apiUrl("/diagnostics"))
  if (!res.ok) throw new AdminApiError(res.status, `诊断查询失败 (${res.status})`)
  return res.json()
}
