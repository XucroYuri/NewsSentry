export interface ReaderImage {
  src: string
  alt?: string
  proxyUrl: string
}

// #76 的旁路 DTO；领域模型 NewsEvent 保持不变。
export interface ReaderArticle {
  markdown: string
  images: ReaderImage[]
  sourceUrl: string
  lang: string
  title: string
  contentHash: string
  attribution: string
}

export interface ReaderTranslation {
  translated: string
  lang: string
  cached: boolean
  provider: string
}

export interface PreviewInput {
  articleId?: string
  url?: string
}

export interface TranslationInput {
  markdown: string
  targetLang: string
  contentHash: string
  sourceLang?: string
  retry?: boolean
}

export type ReaderTranslationStatus = "queued" | "running" | "succeeded" | "failed" | "timed_out"

export interface ReaderTranslationJob {
  jobId: string
  status: ReaderTranslationStatus
  attemptCount: number
  translated?: string
  lang?: string
  cached?: boolean
  provider?: string
  code?: string
  message?: string
  errorStatus?: number
}

export interface TranslationContext {
  articleId?: string
  onProgress?: (job: ReaderTranslationJob) => void
}

export interface ReaderAdapter {
  preview(input: PreviewInput, signal?: AbortSignal): Promise<ReaderArticle>
  translate(input: TranslationInput, signal?: AbortSignal, context?: TranslationContext): Promise<ReaderTranslation>
}

export class ReaderApiError extends Error {
  constructor(public status: number, public code: string, message: string, public jobStatus?: ReaderTranslationStatus) {
    super(message)
    this.name = "ReaderApiError"
  }
}
