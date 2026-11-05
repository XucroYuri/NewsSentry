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
}

export interface ReaderAdapter {
  preview(input: PreviewInput, signal?: AbortSignal): Promise<ReaderArticle>
  translate(input: TranslationInput, signal?: AbortSignal): Promise<ReaderTranslation>
}

export class ReaderApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
    this.name = "ReaderApiError"
  }
}
