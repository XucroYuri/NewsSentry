/**
 * BFF Sources — 信源管理 API 调用。
 */

import { apiUrl, authHeaders, throwApiError } from "./util"

export interface SourcePatchRequest {
  display_name?: string
  url?: string
  credibility_base?: number
  fetch_interval_minutes?: number
  max_items_per_run?: number
  timeout_seconds?: number
  enabled?: boolean
  notes?: string
}

export async function patchSource(
  targetId: string,
  sourceRef: string,
  payload: SourcePatchRequest,
): Promise<Record<string, unknown>> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/sources/${encodeURIComponent(sourceRef)}`),
    {
      method: "PATCH",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  )
  if (!res.ok) await throwApiError(res, `编辑信源失败 (${res.status})`)
  return res.json()
}

export async function archiveSource(targetId: string, sourceRef: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/sources/${encodeURIComponent(sourceRef)}/archive`),
    { method: "POST", headers: authHeaders() },
  )
  if (!res.ok) await throwApiError(res, `归档失败 (${res.status})`)
}

export async function restoreSource(targetId: string, sourceRef: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/sources/${encodeURIComponent(sourceRef)}/restore`),
    { method: "POST", headers: authHeaders() },
  )
  if (!res.ok) await throwApiError(res, `恢复失败 (${res.status})`)
}

export async function validateTarget(targetId: string): Promise<Record<string, unknown>> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/validate`),
    { method: "POST", headers: authHeaders() },
  )
  if (!res.ok) throw new Error(`Validate failed (${res.status})`)
  return res.json()
}
