/**
 * BFF Notifications — 通知规则管理 API 调用。
 */

import { apiUrl, authHeaders, throwApiError, AdminApiError } from "./util"

export interface NotificationRuleRequest {
  id: string
  user_id?: string
  watch: Record<string, unknown>
  action: Record<string, unknown>
  quiet_hours?: Record<string, unknown> | null
  enabled: boolean
}

export interface NotificationRuleInfo {
  id: string
  user_id: string
  enabled: boolean
  rule: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface NotificationRuleListResponse {
  rules: NotificationRuleInfo[]
  total: number
}

export async function fetchRules(): Promise<NotificationRuleListResponse> {
  const res = await fetch(apiUrl("/notification-rules"), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `获取通知规则失败 (${res.status})`)
  return res.json()
}

export async function upsertRule(payload: NotificationRuleRequest): Promise<void> {
  const res = await fetch(apiUrl("/notification-rules"), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    await throwApiError(res, `保存通知规则失败 (${res.status})`)
  }
}

export async function deleteRule(ruleId: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/notification-rules/${encodeURIComponent(ruleId)}`),
    { method: "DELETE", headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `删除通知规则失败 (${res.status})`)
}
