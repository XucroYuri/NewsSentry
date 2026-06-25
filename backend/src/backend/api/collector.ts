/**
 * BFF Collector — 采集器控制 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"

export interface CollectorStatusResponse {
  enabled: boolean
  running: boolean
  stage: string
  [key: string]: unknown
}

export async function fetchStatus(): Promise<CollectorStatusResponse> {
  const res = await fetch(apiUrl("/collector/status"), { headers: authHeaders() })
  if (!res.ok) throw new AdminApiError(res.status, `Collector status failed (${res.status})`)
  return res.json()
}

export async function start(): Promise<void> {
  const res = await fetch(apiUrl("/collector/start"), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Start collector failed (${res.status})`)
}

export async function stop(): Promise<void> {
  const res = await fetch(apiUrl("/collector/stop"), {
    method: "POST",
    headers: authHeaders(),
  })
  if (!res.ok) throw new AdminApiError(res.status, `Stop collector failed (${res.status})`)
}
