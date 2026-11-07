import { ReaderApiError, type ReaderAdapter, type ReaderArticle, type ReaderTranslationJob, type ReaderTranslationStatus } from "./types"

export function safeReaderLink(value: string, origin = window.location.origin): string | undefined {
  if (!value.trim()) return undefined
  try {
    const url = new URL(value, origin)
    if (!["http:", "https:"].includes(url.protocol) || url.href.split("/")[2] !== url.host) return undefined
    return url.href
  } catch {
    return undefined
  }
}

export function safeProxyUrl(value: string, origin = window.location.origin): string | undefined {
  const href = safeReaderLink(value, origin)
  if (!href) return undefined
  const url = new URL(href)
  if (url.origin !== origin || url.pathname !== "/api/v1/reader/image" || url.hash) return undefined
  if (!/^[a-f0-9]{64}$/.test(url.searchParams.get("s") ?? "")) return undefined
  if (!safeReaderLink(url.searchParams.get("u") ?? "", origin) || !url.searchParams.get("u")) return undefined
  return `${url.pathname}${url.search}`
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function invalid(): never {
  throw new ReaderApiError(502, "INVALID_READER_RESPONSE", "Invalid reader response")
}

function articleResponse(value: unknown): ReaderArticle {
  if (!record(value)) return invalid()
  const { markdown, images, sourceUrl, lang, title, contentHash, attribution } = value
  if (
    typeof markdown !== "string" || !markdown.trim() || !Array.isArray(images) ||
    typeof sourceUrl !== "string" || !safeReaderLink(sourceUrl) ||
    typeof lang !== "string" || typeof title !== "string" ||
    typeof contentHash !== "string" || !/^[a-f0-9]{32}$/.test(contentHash) ||
    typeof attribution !== "string"
  ) return invalid()
  return {
    markdown, sourceUrl, lang, title, contentHash, attribution,
    images: images.map((image) => {
      if (!record(image) || typeof image.src !== "string" || typeof image.proxyUrl !== "string" || (image.alt !== undefined && typeof image.alt !== "string")) return invalid()
      // 无效代理保留为失败占位，绝不回退 src。
      return { src: image.src, proxyUrl: safeProxyUrl(image.proxyUrl) ?? "", alt: image.alt }
    }),
  }
}

function translationJob(value: unknown): ReaderTranslationJob {
  if (!record(value)) return invalid()
  const { jobId, status, attemptCount, completedChunks, totalChunks, translated, lang, cached, provider, code, message, errorStatus } = value
  if (
    typeof jobId !== "string" || !jobId.trim() ||
    typeof status !== "string" || !["queued", "running", "succeeded", "failed", "timed_out"].includes(status) ||
    typeof attemptCount !== "number" || !Number.isInteger(attemptCount) || attemptCount < 0 ||
    ((completedChunks !== undefined || totalChunks !== undefined) && (
      typeof completedChunks !== "number" || !Number.isSafeInteger(completedChunks) || completedChunks < 0 ||
      typeof totalChunks !== "number" || !Number.isSafeInteger(totalChunks) || totalChunks < 0 ||
      completedChunks > totalChunks
    )) ||
    (translated !== undefined && typeof translated !== "string") ||
    (lang !== undefined && typeof lang !== "string") ||
    (cached !== undefined && typeof cached !== "boolean") ||
    (provider !== undefined && typeof provider !== "string") ||
    (code !== undefined && typeof code !== "string") ||
    (message !== undefined && typeof message !== "string") ||
    (errorStatus !== undefined && (typeof errorStatus !== "number" || !Number.isInteger(errorStatus) || errorStatus < 400 || errorStatus > 599))
  ) return invalid()
  if (status === "succeeded" && (typeof translated !== "string" || !translated.trim() || typeof lang !== "string" || !lang.trim())) return invalid()
  if ((status === "failed" || status === "timed_out") && (typeof code !== "string" || typeof message !== "string")) return invalid()
  return { jobId, status: status as ReaderTranslationStatus, attemptCount, completedChunks, totalChunks, translated, lang, cached, provider, code, message, errorStatus }
}

function checkAbort(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError")
}

function pollDelay(ms: number, signal?: AbortSignal): Promise<void> {
  checkAbort(signal)
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", abort)
      reject(new DOMException("Aborted", "AbortError"))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort)
      resolve()
    }, ms)
    signal?.addEventListener("abort", abort, { once: true })
  })
}

function savedJob(key: string): string | null {
  try { return sessionStorage.getItem(key) || null } catch { return null }
}

function saveJob(key: string, jobId: string) {
  try { sessionStorage.setItem(key, jobId) } catch { return }
}

function removeJob(key: string) {
  try { sessionStorage.removeItem(key) } catch { return }
}

function missingJob(): ReaderApiError {
  return new ReaderApiError(404, "TRANSLATION_JOB_NOT_FOUND", "Translation job unavailable; resubmit to translate again")
}

export function createReaderAdapter(fetcher: typeof fetch = fetch): ReaderAdapter {
  async function request(path: string, signal?: AbortSignal, body?: unknown): Promise<unknown> {
    checkAbort(signal)
    const response = await fetcher(`/api/v1/reader/${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
    const payload: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      throw new ReaderApiError(
        response.status,
        record(payload) && typeof payload.code === "string" ? payload.code : "READER_UNAVAILABLE",
        record(payload) && typeof payload.message === "string" ? payload.message : "Reader unavailable",
      )
    }
    return payload
  }
  return {
    preview: async (input, signal) => articleResponse(await request("preview", signal, input)),
    async translate(input, signal, context) {
      checkAbort(signal)
      const key = `news-sentry-reader-job:v1:${JSON.stringify([context?.articleId ?? "", input.contentHash, input.targetLang, input.sourceLang ?? ""])}`
      const resubmitKey = `${key}:resubmit`
      if (!input.retry && savedJob(resubmitKey)) throw missingJob()
      async function getJob(jobId: string) {
        try {
          return translationJob(await request(`translate/${encodeURIComponent(jobId)}`, signal))
        } catch (error) {
          if (error instanceof ReaderApiError && error.status === 404) {
            removeJob(key)
            saveJob(resubmitKey, "1")
            throw missingJob()
          }
          throw error
        }
      }
      const jobId = input.retry ? null : savedJob(key)
      let job = jobId ? await getJob(jobId) : translationJob(await request("translate", signal, input))
      let delay = 1500
      while (true) {
        saveJob(key, job.jobId)
        removeJob(resubmitKey)
        checkAbort(signal)
        context?.onProgress?.(job)
        if (job.status === "succeeded") {
          return { translated: job.translated!, lang: job.lang!, cached: job.cached ?? false, provider: job.provider ?? "" }
        }
        if (job.status === "failed" || job.status === "timed_out") {
          throw new ReaderApiError(job.errorStatus ?? 503, job.code!, job.message!, job.status)
        }
        await pollDelay(delay, signal)
        job = await getJob(job.jobId)
        delay = Math.min(5000, delay * 1.5)
      }
    },
  }
}
