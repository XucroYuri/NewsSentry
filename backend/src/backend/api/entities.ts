/**
 * BFF Entities — 实体管理 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"

export interface EntityInfo {
  id: number
  canonical_name: string
  entity_type: string
  mention_count: number
  first_seen: string
  last_seen: string
  target_ids: string
  confidence: number
  needs_review: boolean
  first_seen_source_id: string | null
  last_seen_source_id: string | null
  aliases: string
}

export interface EntityListResponse {
  total: number
  entities: EntityInfo[]
}

export interface EntityDetailResponse {
  entity: EntityInfo
  recent_events: Record<string, unknown>[]
}

export interface EntityMergeResponse {
  merged: boolean
  source_name: string
  target_name: string
  error: string | null
}

export async function fetchEntities(params?: {
  entity_type?: string
  target_id?: string
  min_mentions?: number
  limit?: number
  sort?: string
}): Promise<EntityListResponse> {
  const sp = new URLSearchParams()
  if (params?.entity_type) sp.set("entity_type", params.entity_type)
  if (params?.target_id) sp.set("target_id", params.target_id)
  if (params?.min_mentions) sp.set("min_mentions", String(params.min_mentions))
  if (params?.limit) sp.set("limit", String(params.limit))
  if (params?.sort) sp.set("sort", params.sort)
  const qs = sp.toString()
  const res = await fetch(apiUrl(`/entities${qs ? `?${qs}` : ""}`), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `获取实体列表失败 (${res.status})`)
  return res.json()
}

export async function searchEntities(q: string, limit = 20): Promise<EntityListResponse> {
  const res = await fetch(apiUrl(`/entities/search?q=${encodeURIComponent(q)}&limit=${limit}`), {
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `搜索实体失败 (${res.status})`)
  return res.json()
}

export async function fetchEntity(entityId: number): Promise<EntityDetailResponse> {
  const res = await fetch(apiUrl(`/entities/${entityId}`), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `获取实体详情失败 (${res.status})`)
  return res.json()
}

export async function fetchEntityEvents(
  entityId: number,
  limit = 50,
  offset = 0,
): Promise<{ entity_id: number; total: number; events: Record<string, unknown>[] }> {
  const res = await fetch(
    apiUrl(`/entities/${entityId}/events?limit=${limit}&offset=${offset}`),
    { headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `获取实体事件失败 (${res.status})`)
  return res.json()
}

export async function mergeEntities(
  sourceId: number,
  targetId: number,
): Promise<EntityMergeResponse> {
  const res = await fetch(apiUrl("/entities/merge"), {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
  })
  if (!res.ok) throw new AdminApiError(res.status, `合并实体失败 (${res.status})`)
  return res.json()
}
