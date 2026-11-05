/** Reader v0：draft 边缘旁路契约，不替代 NewsEvent 或 Python API 契约。 */
export interface ReaderEnv {
  READER_ENABLED?: string;
  /** 逗号分隔的可信公共主机名，精确匹配；不支持通配符。 */
  READER_ALLOWED_HOSTS?: string;
  READER_IMAGE_SIGNING_SECRET?: string;
}

export type ReaderPreviewRequest = { url: string; sourceUrl?: string } | { sourceUrl: string; url?: string };
export interface ReaderPreviewResponse {
  markdown: string;
  images: string[];
  sourceUrl: string;
  lang: string;
  title?: string;
  contentHash?: string;
  attribution?: string;
  provider?: string;
}
export type ReaderTranslateRequest = ({ text: string; markdown?: string } | { markdown: string; text?: string }) & {
  targetLang: string;
  contentHash?: string;
};
export interface ReaderTranslateResponse {
  translated: string;
  lang: string;
  cached: boolean;
  provider?: string;
}
