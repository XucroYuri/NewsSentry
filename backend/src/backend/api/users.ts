/**
 * BFF Users — 用户管理 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"

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

export async function fetchUsers(): Promise<AdminUserListResponse> {
  const res = await fetch(apiUrl("/admin/users"), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `User list failed (${res.status})`)
  return res.json()
}

export async function createUser(payload: {
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
    throw new AdminApiError(res.status, String((detail as Record<string, unknown>)?.detail ?? `创建用户失败 (${res.status})`))
  }
}

export async function deleteUser(username: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/admin/users/${encodeURIComponent(username)}`),
    { method: "DELETE", headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `删除用户失败 (${res.status})`)
}

export async function resetPassword(username: string, newPassword: string): Promise<void> {
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
