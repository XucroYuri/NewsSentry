/**
 * Vote state — localStorage-backed tracking of which event IDs the current
 * browser has upvoted. Phase 2 of HN-style upgrade.
 *
 * The backend deduplicates by voter_hash (IP + UA + daily salt), but the
 * frontend also tracks votes locally so the UI can render the correct
 * "already voted" state without an extra API round-trip on every page load.
 */

const STORAGE_KEY = "news-sentry-voted-ids"

function readVotedIds(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((id): id is string => typeof id === "string"))
  } catch {
    return new Set()
  }
}

function writeVotedIds(ids: Set<string>): void {
  try {
    // Cap at 1000 entries to prevent unbounded growth.
    const capped = Array.from(ids).slice(-1000)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(capped))
  } catch {
    // localStorage may be full or disabled — vote state is best-effort.
  }
}

export function getVotedIds(): Set<string> {
  return readVotedIds()
}

export function isVoted(eventId: string): boolean {
  return readVotedIds().has(eventId)
}

export function markVoted(eventId: string): void {
  const ids = readVotedIds()
  ids.add(eventId)
  writeVotedIds(ids)
}

export function unmarkVoted(eventId: string): void {
  const ids = readVotedIds()
  ids.delete(eventId)
  writeVotedIds(ids)
}
