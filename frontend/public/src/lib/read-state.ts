/**
 * read-state.ts — 前端已读/未读状态管理。
 *
 * 使用 localStorage 存储已读新闻 ID set，用于：
 * - NewsCard 视觉区分已读/未读
 * - 可选的"仅未读"筛选
 */

const STORAGE_KEY = "news-sentry:read-ids"
const MAX_READ_ENTRIES = 500

interface ReadEntry {
  id: string
  readAt: string // ISO timestamp
}

function loadReadEntries(): ReadEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (entry): entry is ReadEntry =>
        typeof entry === "object" &&
        entry !== null &&
        typeof entry.id === "string" &&
        typeof entry.readAt === "string",
    )
  } catch {
    return []
  }
}

function saveReadEntries(entries: ReadEntry[]): void {
  try {
    // 保留最近 N 条
    const trimmed = entries.slice(-MAX_READ_ENTRIES)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
  } catch {
    // quota exceeded, private browsing — silently ignore
  }
}

/** 返回所有已读新闻 ID（Set 形式）。 */
export function getReadIds(): Set<string> {
  return new Set(loadReadEntries().map((entry) => entry.id))
}

/** 标记某条新闻为已读。 */
export function markAsRead(eventId: string): void {
  if (!eventId) return
  const entries = loadReadEntries()
  const existing = entries.find((entry) => entry.id === eventId)
  if (existing) return // 已标记
  entries.push({ id: eventId, readAt: new Date().toISOString() })
  saveReadEntries(entries)
}

/** 标记多条新闻为已读（如滚动浏览时批量标记可见卡片）。 */
export function markManyAsRead(eventIds: string[]): void {
  if (!eventIds.length) return
  const entries = loadReadEntries()
  const existingIds = new Set(entries.map((entry) => entry.id))
  const now = new Date().toISOString()
  for (const id of eventIds) {
    if (!id || existingIds.has(id)) continue
    entries.push({ id, readAt: now })
    existingIds.add(id)
  }
  saveReadEntries(entries)
}

/** 清除所有已读历史。 */
export function clearReadHistory(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Ignore
  }
}
