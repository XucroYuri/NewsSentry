/**
 * BFF Inventory — 信源盘点 API 调用。
 */

import { apiUrl, authHeaders, AdminApiError } from "./util"

export interface SourceInventoryItem {
  source_id: string
  source_ref?: string
  type?: string
  name?: string
  display_name?: string
  url?: string
  language?: string
  enabled?: boolean
  archived?: boolean
  status?: string
  missing_file?: boolean
  credibility_base?: number
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

export async function fetchInventory(targetId: string): Promise<SourceInventoryResponse> {
  const res = await fetch(
    apiUrl(`/admin/targets/${encodeURIComponent(targetId)}/inventory`),
    { headers: authHeaders() },
  )
  if (!res.ok) throw new AdminApiError(res.status, `Inventory fetch failed (${res.status})`)
  return res.json()
}
