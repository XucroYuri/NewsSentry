/**
 * Worker 端统一错误响应 helper。
 *
 * 确保所有 4xx/5xx 响应与 FastAPI 端 /api/v1/diagnostics 兼容的
 * {"error": "...", "detail": "...", "status_code": N} 格式。
 */

export interface JsonErrorBody {
  error: string
  detail: string
  status_code: number
}

const STATUS_PHRASES: Record<number, string> = {
  400: "Bad Request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not Found",
  405: "Method Not Allowed",
  409: "Conflict",
  422: "Unprocessable Entity",
  429: "Too Many Requests",
  500: "Internal Server Error",
  503: "Service Unavailable",
}

function statusPhrase(statusCode: number): string {
  return STATUS_PHRASES[statusCode] ?? `HTTP ${statusCode}`
}

/**
 * 构建符合统一 JSON error 格式的 Response。
 */
export function errorResponse(
  statusCode: number,
  detail: string,
  extraHeaders?: Record<string, string>,
): Response {
  const body: JsonErrorBody = {
    error: statusPhrase(statusCode),
    detail,
    status_code: statusCode,
  }
  const headers = new Headers(extraHeaders)
  headers.set("Content-Type", "application/json")
  if (statusCode >= 500) {
    headers.set("X-News-Sentry-Error-Level", "critical")
  }
  return new Response(JSON.stringify(body), { status: statusCode, headers })
}

/**
 * 快速构建 404 响应（最常见）。
 */
export function notFound(detail = "Not found"): Response {
  return errorResponse(404, detail)
}

/**
 * 快速构建 500 响应（Worker 异常兜底）。
 */
export function internalError(detail = "An unexpected error occurred"): Response {
  return errorResponse(500, detail)
}
