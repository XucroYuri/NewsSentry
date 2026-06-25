/**
 * BFF Events — 新闻事件列表 + 草稿审核 API 调用。
 */

import { apiUrl, authHeaders } from "./util"

export interface EventsResponse {
  total: number
  events: Record<string, unknown>[]
  page: number
  page_size: number
}

export async function fetchEvents(params: {
  target_id: string
  page: number
  page_size: number
  stage?: string
  search?: string
  classification?: string
  min_score?: number
  sentiment?: string
}): Promise<EventsResponse> {
  const sp = new URLSearchParams()
  sp.set("target_id", params.target_id)
  sp.set("page", String(params.page))
  sp.set("page_size", String(params.page_size))
  if (params.stage) sp.set("stage", params.stage)
  if (params.search?.trim()) sp.set("search", params.search.trim())
  if (params.classification) sp.set("classification", params.classification)
  if (params.min_score !== undefined) sp.set("min_score", String(params.min_score))
  if (params.sentiment) sp.set("sentiment", params.sentiment)
  const res = await fetch(
    `${apiUrl("/events")}?${sp}`,
    { headers: authHeaders() },
  )
  if (!res.ok) throw new Error(`Event list failed (${res.status})`)
  return res.json()
}

export async function transitionEvent(
  eventId: string,
  targetId: string,
  newStage: string,
): Promise<Response> {
  const res = await fetch(
    apiUrl(`/admin/events/${encodeURIComponent(eventId)}/transition`),
    {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ target_id: targetId, new_stage: newStage }),
    },
  )
  return res
}
