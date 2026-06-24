/**
 * locals-settings.ts — 本机/云源 API 切换。
 *
 * 设计目标：前端一个开关，决定 API 请求走同源相对路径（默认）
 * 还是 Cloudflare Worker 完整 URL。设置保存在 localStorage，
 * 不需要重新构建、不依赖环境变量。
 *
 * 刷新页面后立即生效（非运行时监听 — React 组件在 mount 时调用
 * getApiBase() 读取，如需切换后生效请刷新页面）。
 */

const STORAGE_KEY = "news-sentry:settings"

export interface LocalSettings {
  /** null 表示使用相对路径（同源，默认），否则为完整 URL 如 "https://news-sentry-api.xuyu.workers.dev" */
  apiBase: string | null
}

/** 构建时可通过 VITE_API_BASE 注入默认 API 地址（如 Cloudflare Pages 部署）。 */
function buildTimeApiBase(): string | null {
  try {
    // Vite 会将 VITE_ 前缀的环境变量暴露在 import.meta.env 上
    const meta = import.meta as unknown as { env?: { VITE_API_BASE?: string } }
    const raw = meta.env?.VITE_API_BASE
    if (raw && raw.trim().length > 0) return raw.trim().replace(/\/+$/, "")
  } catch {
    // import.meta.env 不可用时（非 Vite 环境）静默回退
  }
  return null
}

const DEFAULTS: LocalSettings = {
  apiBase: buildTimeApiBase(),
}

function load(): LocalSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    const parsed = JSON.parse(raw) as Partial<LocalSettings>
    // 只允许 string | null
    const apiBase =
      typeof parsed.apiBase === "string"
        ? parsed.apiBase.replace(/\/+$/, "") // strip trailing slash
        : null
    return { apiBase }
  } catch {
    return { ...DEFAULTS }
  }
}

function save(settings: LocalSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // quota exceeded, private browsing — silently ignore
  }
}

/** 返回当前设置。每次调用都从 localStorage 读取。 */
export function getSettings(): LocalSettings {
  return load()
}

/** 返回 API base URL；null 表示使用同源相对路径。 */
export function getApiBase(): string | null {
  return load().apiBase
}

/** 设置 API base URL。null 表示重置为默认（同源）。 */
export function setApiBase(url: string | null): void {
  // 规范化：去掉末尾斜杠，空字符串视为 null
  const normalized =
    typeof url === "string" && url.trim().length > 0
      ? url.trim().replace(/\/+$/, "")
      : null
  save({ apiBase: normalized })
}

/** 将相对路径（如 "/api/v1/health"）解析为完整 URL（如需要 prefix）。 */
export function resolveUrl(path: string): string {
  const base = getApiBase()
  if (!base) return path
  return `${base}${path}`
}
