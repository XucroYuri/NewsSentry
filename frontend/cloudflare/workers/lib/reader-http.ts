import { validateExternalUrl } from "./external-url.ts";

export class ReaderError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function readerJson(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export function readerFailure(error: unknown): Response {
  const failure = error instanceof ReaderError ? error
    : new ReaderError(502, "UPSTREAM_FAILED", "原文服务暂不可用，请稍后重试或打开原文。");
  return readerJson({ error: failure.code, code: failure.code, message: failure.message }, failure.status);
}

/**
 * 仅按 URL 主机名拒绝 IP 字面量和特殊主机名，不解析 DNS。
 * 普通 Workers fetch 不提供私网保护兜底，域名解析至私网和 DNS rebinding 仍有残余风险。
 * 生产启用前须满足 docs/reader-v1.md 的 M1 硬门禁。
 */
export function readerUrl(value: unknown): string {
  const checked = validateExternalUrl(value);
  if (!checked.ok) throw new ReaderError(400, "UNSAFE_URL", "需要有效的公开 HTTP(S) URL。");
  const url = new URL(checked.normalizedUrl);
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  const ipLiteral = host.startsWith("[") || /^\d+\.\d+\.\d+\.\d+$/.test(host);
  const privateName = !host.includes(".")
    || /(?:^|\.)(localhost|local|internal|home|lan|onion|invalid)$/.test(host);
  if (ipLiteral || privateName || (url.port && !["80", "443"].includes(url.port))) {
    throw new ReaderError(400, "UNSAFE_URL", "不允许内网、特殊地址或非标准端口。");
  }
  url.hash = "";
  return url.href;
}

export async function readBounded(stream: ReadableStream<Uint8Array> | null, maxBytes: number): Promise<Uint8Array<ArrayBuffer>> {
  if (!stream) return new Uint8Array();
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maxBytes) {
        await reader.cancel();
        throw new ReaderError(422, "CONTENT_TOO_LARGE", "内容超过阅读器大小上限，请打开原文。");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

export async function readerBody(request: Request): Promise<Record<string, unknown>> {
  if (request.headers.get("Content-Type")?.split(";")[0].trim() !== "application/json") {
    throw new ReaderError(400, "INVALID_JSON", "请求必须使用 application/json。");
  }
  try {
    const bytes = await readBounded(request.body, 128 * 1024);
    const body = JSON.parse(new TextDecoder().decode(bytes));
    if (!body || typeof body !== "object" || Array.isArray(body)) throw Error("not an object");
    return body;
  } catch (error) {
    if (error instanceof ReaderError) throw error;
    throw new ReaderError(400, "INVALID_JSON", "请求 JSON 无效。");
  }
}

export async function fetchReaderResource(
  target: string,
  accept: string,
  maxBytes: number,
): Promise<{ bytes: Uint8Array<ArrayBuffer>; contentType: string; sourceUrl: string }> {
  let sourceUrl = readerUrl(target);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    for (let hop = 0; hop <= 3; hop++) {
      const response = await fetch(sourceUrl, {
        headers: { Accept: accept }, redirect: "manual", signal: controller.signal,
      });
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        await response.body?.cancel();
        const location = response.headers.get("Location");
        if (!location || hop === 3) break;
        sourceUrl = readerUrl(new URL(location, sourceUrl).href);
        continue;
      }
      if (!response.ok) {
        await response.body?.cancel();
        const status = [403, 404, 429].includes(response.status) ? response.status : 502;
        throw new ReaderError(status, "SOURCE_UNAVAILABLE", `原站暂不可读，请打开原文：${sourceUrl}`);
      }
      if (Number(response.headers.get("Content-Length")) > maxBytes) {
        await response.body?.cancel();
        throw new ReaderError(422, "CONTENT_TOO_LARGE", `内容超过大小上限，请打开原文：${sourceUrl}`);
      }
      return {
        sourceUrl, bytes: await readBounded(response.body, maxBytes),
        contentType: response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() ?? "",
      };
    }
    throw new ReaderError(502, "TOO_MANY_REDIRECTS", "原站重定向异常，请打开原文。");
  } finally {
    clearTimeout(timeout);
  }
}

export function normalizeMarkdown(markdown: string): string {
  return markdown.replace(/\r\n?/g, "\n").replace(/[ \t]+$/gm, "").replace(/\n{3,}/g, "\n\n").trim();
}

export async function markdownHash(markdown: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalizeMarkdown(markdown)));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 32);
}
