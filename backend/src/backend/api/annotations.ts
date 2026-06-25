/**
 * BFF Annotations — 注解管理 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"

export interface AnnotationInfo {
  id: number
  entity_id: number
  event_id: string | null
  field: string
  old_value: string
  new_value: string
  annotation_type: string
  created_by: string
  created_at: string
  reviewed: boolean
  reviewed_by: string | null
  reviewed_at: string | null
  canonical_name: string
}

export interface AnnotationListResponse {
  annotations: AnnotationInfo[]
  total: number
}

export interface AnnotationCreateRequest {
  entity_id: number
  field: string
  old_value?: string
  new_value?: string
  event_id?: string | null
  annotation_type?: string
  created_by?: string
}

export interface AnnotationUpdateRequest {
  field?: string | null
  old_value?: string | null
  new_value?: string | null
  annotation_type?: string | null
  reviewed?: boolean | null
  reviewed_by?: string | null
}

export async function fetchAnnotations(params?: {
  entity_id?: number
  event_id?: string
  reviewed?: boolean
  limit?: number
  offset?: number
}): Promise<AnnotationListResponse> {
  const sp = new URLSearchParams()
  if (params?.entity_id) sp.set("entity_id", String(params.entity_id))
  if (params?.event_id) sp.set("event_id", params.event_id)
  if (params?.reviewed !== undefined) sp.set("reviewed", String(params.reviewed))
  if (params?.limit) sp.set("limit", String(params.limit))
  if (params?.offset) sp.set("offset", String(params.offset))
  const qs = sp.toString()
  const res = await fetch(apiUrl(`/annotations${qs ? `?${qs}` : ""}`), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `获取注解列表失败 (${res.status})`)
  return res.json()
}

export async function createAnnotation(payload: AnnotationCreateRequest): Promise<AnnotationInfo> {
  const res = await fetch(apiUrl("/annotations"), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new AdminApiError(res.status, `创建注解失败 (${res.status})`)
  return res.json()
}

export async function updateAnnotation(
  annotationId: number,
  payload: AnnotationUpdateRequest,
): Promise<AnnotationInfo> {
  const res = await fetch(apiUrl(`/annotations/${annotationId}`), {
    method: "PATCH",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new AdminApiError(res.status, `更新注解失败 (${res.status})`)
  return res.json()
}

export async function deleteAnnotation(annotationId: number): Promise<void> {
  const res = await fetch(apiUrl(`/annotations/${annotationId}`), {
    method: "DELETE",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `删除注解失败 (${res.status})`)
}

export async function reviewAnnotation(
  annotationId: number,
  reviewed: boolean,
): Promise<AnnotationInfo> {
  const res = await fetch(apiUrl(`/annotations/${annotationId}/review`), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed }),
  })
  if (!res.ok) throw new AdminApiError(res.status, `审核注解失败 (${res.status})`)
  return res.json()
}
