import { errorResponse } from "../lib/errors.ts";
import { validateExternalUrl } from "../lib/external-url.ts";
import type { ReaderEnv, ReaderPreviewResponse, ReaderTranslateResponse } from "../lib/reader-contracts.ts";

const encoder = new TextEncoder();
const translations = new Map<string, { translated: string; expires: number }>();
const MAX_TEXT_BYTES = 128 * 1024;

class ReaderError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function respond(env: ReaderEnv, action: () => Promise<Response>): Promise<Response> {
  if (env.READER_ENABLED !== "true") return errorResponse(503, "Reader bypass is disabled");
  try {
    return await action();
  } catch (error) {
    return error instanceof ReaderError
      ? errorResponse(error.status, error.message)
      : errorResponse(502, "Reader upstream request failed");
  }
}

function json(value: ReaderPreviewResponse | ReaderTranslateResponse): Response {
  return Response.json(value, { headers: { "Cache-Control": "no-store" } });
}

async function readLimited(body: ReadableStream<Uint8Array> | null, limit: number): Promise<Uint8Array<ArrayBuffer>> {
  if (!body) return new Uint8Array();
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new ReaderError(413, "Reader payload is too large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}

async function readBody(request: Request): Promise<Record<string, unknown>> {
  const bytes = await readLimited(request.body, MAX_TEXT_BYTES);
  try {
    const body: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error();
    return body as Record<string, unknown>;
  } catch { throw new ReaderError(400, "Expected a JSON object"); }
}

function allowedUrl(value: unknown, env: ReaderEnv): string {
  const hosts = (env.READER_ALLOWED_HOSTS ?? "").split(",").map((host) => host.trim().toLowerCase()).filter(Boolean);
  if (!hosts.length) throw new ReaderError(503, "Reader allowed hosts are not configured");
  const validated = validateExternalUrl(value);
  if (!validated.ok) throw new ReaderError(400, "Invalid source URL");
  const url = new URL(validated.normalizedUrl);
  if (url.protocol !== "https:" || url.port || !hosts.includes(url.hostname) ||
      url.hostname === "localhost" || url.hostname.endsWith(".localhost") ||
      url.hostname.endsWith(".local") || !url.hostname.includes(".") ||
      /^[\d.]+$/.test(url.hostname) || url.hostname.includes(":")) {
    throw new ReaderError(403, "Source host is not allowed");
  }
  return url.href;
}

async function fetchSource(url: string, image: boolean): Promise<{ bytes: Uint8Array<ArrayBuffer>; type: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(url, {
      redirect: "manual", signal: controller.signal,
      headers: { Accept: image ? "image/*" : "text/html, text/markdown, text/plain" },
    });
    const type = (response.headers.get("Content-Type") ?? "").split(";")[0].trim().toLowerCase();
    const supported = image
      ? ["image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"].includes(type)
      : ["text/html", "text/markdown", "text/plain"].includes(type);
    if (!response.ok || !supported) {
      await response.body?.cancel();
      throw new ReaderError(502, "Unsupported upstream status or content type (redirects are disabled)");
    }
    return { bytes: await readLimited(response.body, image ? 5 * 1024 * 1024 : 1024 * 1024), type };
  } finally { clearTimeout(timer); }
}

function plain(html: string): string {
  return html.replace(/<[^>]*>/g, "").replace(/&(?:amp|lt|gt|quot|apos|nbsp);/g, (entity) =>
    ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&nbsp;": " " })[entity] ?? entity);
}

function absoluteImage(value: string, sourceUrl: string): string[] {
  try {
    const result = validateExternalUrl(new URL(value, sourceUrl).href);
    return result.ok ? [result.normalizedUrl] : [];
  } catch { return []; }
}

async function hash(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text))),
    (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function handleReaderPreview(request: Request, env: ReaderEnv = {}): Promise<Response> {
  return respond(env, async () => {
    const body = await readBody(request);
    const sourceUrl = allowedUrl(body.url ?? body.sourceUrl, env);
    const { bytes, type } = await fetchSource(sourceUrl, false);
    const source = new TextDecoder().decode(bytes);
    let markdown = source;
    let title: string | undefined;
    let images: string[];
    let lang = "";
    if (type === "text/html") {
      title = plain(source.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? "").trim() || undefined;
      lang = source.match(/<html\b[^>]*\blang\s*=\s*["']([a-zA-Z-]+)["']/i)?.[1]?.toLowerCase() ?? "";
      const clean = source.replace(/<(script|style|nav|footer|header)\b[^>]*>[\s\S]*?<\/\1>/gi, "");
      const main = clean.match(/<(article|main)\b[^>]*>([\s\S]*?)<\/\1>/i)?.[2] ?? clean;
      images = [...main.matchAll(/<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/gi)]
        .flatMap((match) => absoluteImage(plain(match[1]), sourceUrl));
      markdown = plain(main.replace(/<br\s*\/?>|<\/(?:p|div|h[1-6]|li)>/gi, "\n\n")).replace(/\n\s*\n/g, "\n\n").trim();
    } else {
      images = [...source.matchAll(/!\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)/g)]
        .flatMap((match) => absoluteImage(match[1], sourceUrl));
    }
    return json({ markdown, images: [...new Set(images)], sourceUrl,
      lang: lang || (/[\u4e00-\u9fff]/.test(markdown) ? "zh" : /[a-zA-Z]/.test(markdown) ? "en" : "und"),
      title, contentHash: await hash(markdown), attribution: sourceUrl, provider: "lightweight" });
  });
}

export async function handleReaderTranslate(request: Request, env: ReaderEnv = {}): Promise<Response> {
  return respond(env, async () => {
    const body = await readBody(request);
    const text = body.text ?? body.markdown;
    if (typeof text !== "string" || !text.trim() || typeof body.targetLang !== "string" ||
        !/^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$/.test(body.targetLang) || body.targetLang.length > 35 ||
        (body.contentHash !== undefined && typeof body.contentHash !== "string")) {
      throw new ReaderError(400, "Expected text/markdown and a valid targetLang");
    }
    const lang = body.targetLang.toLowerCase();
    // 不信任调用者 contentHash，避免错误复用不同正文。stub 不调用任何付费 provider。
    const key = await hash(JSON.stringify(["stub-v0", lang, text]));
    const now = Date.now();
    const hit = translations.get(key);
    if (hit && hit.expires > now) return json({ translated: hit.translated, lang, cached: true, provider: "stub" });
    for (const [key, value] of translations) if (value.expires <= now) translations.delete(key);
    if (translations.size >= 64) translations.delete(translations.keys().next().value!);
    const translated = `[stub:${lang}]\n${text}`;
    translations.set(key, { translated, expires: now + 300_000 });
    return json({ translated, lang, cached: false, provider: "stub" });
  });
}

export async function handleReaderImage(request: Request, env: ReaderEnv = {}): Promise<Response> {
  return respond(env, async () => {
    const secret = env.READER_IMAGE_SIGNING_SECRET;
    if (!secret) throw new ReaderError(503, "Reader image signing is not configured");
    const params = new URL(request.url).searchParams;
    const signature = params.get("sig") ?? "";
    const expires = params.get("expires") ?? "";
    const source = params.get("url") ?? "";
    const now = Math.floor(Date.now() / 1000);
    if (!/^[a-f0-9]{64}$/.test(signature) || !/^\d{10}$/.test(expires) ||
        Number(expires) <= now || Number(expires) > now + 3600) {
      throw new ReaderError(403, "Missing, invalid or expired image signature");
    }
    const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    const valid = await crypto.subtle.verify("HMAC", key,
      Uint8Array.from(signature.match(/../g)!, (byte) => parseInt(byte, 16)),
      encoder.encode(`reader-image-v0\n${expires}\n${source}`));
    if (!valid) throw new ReaderError(403, "Invalid image signature");
    const url = allowedUrl(source, env);
    const { bytes, type } = await fetchSource(url, true);
    return new Response(bytes, { headers: {
      "Content-Type": type, "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    } });
  });
}
