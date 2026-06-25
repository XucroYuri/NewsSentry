/**
 * BFF shared utilities — API URL resolution and auth headers.
 *
 * Mirrors the logic from frontend/admin/src/lib/api.ts so BFF functions
 * can also construct API URLs and include the JWT token.
 */

/** Resolve a relative API path to a full URL (handles Cloudflare Worker switching). */
export function resolveUrl(path: string): string {
  // Dynamic import would cause circular issues; use localStorage directly
  const apiBase = getApiBase()
  if (!apiBase) return path
  return `${apiBase}${path}`
}

function getApiBase(): string | null {
  try {
    const raw = localStorage.getItem("news-sentry:settings")
    if (!raw) return null
    const parsed = JSON.parse(raw) as { apiBase?: string | null }
    const apiBase = typeof parsed.apiBase === "string"
      ? parsed.apiBase.replace(/\/+$/, "")
      : null
    return apiBase
  } catch {
    return null
  }
}

const API_V1 = "/api/v1"

/** Build full API URL from a path relative to /api/v1. */
export function apiUrl(path: string): string {
  return resolveUrl(`${API_V1}${path}`)
}

/** Get auth headers with Bearer token from localStorage. */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("news_sentry_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Error class for API errors carrying HTTP status code and detail message. */
export class AdminApiError extends Error {
  statusCode: number
  detail: string

  constructor(statusCode: number, detail: string) {
    super(`[${statusCode}] ${detail}`)
    this.name = "AdminApiError"
    this.statusCode = statusCode
    this.detail = detail
  }

  get isAuthError(): boolean {
    return this.statusCode === 401 || this.statusCode === 403
  }

  get isServerError(): boolean {
    return this.statusCode >= 500
  }
}

/** Extract error detail from a failed Response and throw AdminApiError. */
export async function throwApiError(res: Response, fallback: string): Promise<never> {
  let errorBody: { error?: string; detail?: string; status_code?: number } = {}
  try {
    errorBody = await res.json()
  } catch {
    // JSON parse failed, use fallback
  }
  const detail = errorBody.detail ?? errorBody.error ?? fallback
  const statusCode = errorBody.status_code ?? res.status
  throw new AdminApiError(statusCode, detail)
}
