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

function publicDnsAddress(address: string, type: number): boolean {
  if (type === 1) {
    if (!/^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$/.test(address)) {
      throw new Error("Invalid DNS IPv4 address");
    }
    const [first, second, third, fourth] = address.split(".").map(Number);
    if ([first, second, third, fourth].some((part) => part > 255)) {
      throw new Error("Invalid DNS IPv4 address");
    }
    return first !== 0 && first !== 10 && first !== 127 && first < 224
      && !(first === 100 && second >= 64 && second <= 127)
      && !(first === 169 && second === 254)
      && !(first === 172 && second >= 16 && second <= 31)
      && !(first === 192 && (second === 168
        || (second === 0 && (third === 0 || third === 2))
        || (second === 88 && third === 99)))
      && !(first === 198 && (second === 18 || second === 19 || (second === 51 && third === 100)))
      && !(first === 203 && second === 0 && third === 113);
  }
  if (type !== 28 || !address.includes(":") || !/^[0-9a-f:.]+$/i.test(address)) {
    throw new Error("Invalid DNS IPv6 address");
  }
  const canonical = new URL(`http://[${address}]/`).hostname.slice(1, -1);
  const [left, right] = canonical.split("::");
  const leading = left ? left.split(":").map((part) => parseInt(part, 16)) : [];
  const trailing = right ? right.split(":").map((part) => parseInt(part, 16)) : [];
  const words = right === undefined ? leading
    : [...leading, ...Array<number>(8 - leading.length - trailing.length).fill(0), ...trailing];
  return (words[0] & 0xe000) === 0x2000
    && !(words[0] === 0x2001 && (words[1] < 0x0200 || words[1] === 0x0db8))
    && words[0] !== 0x2002
    && !(words[0] === 0x3fff && words[1] < 0x1000);
}

function dnsHostname(value: string): string {
  const hostname = value.toLowerCase().replace(/\.$/, "");
  if (new URL(readerUrl(`https://${hostname}`)).hostname !== hostname) {
    throw new Error("Invalid DNS hostname");
  }
  return hostname;
}

async function readerDnsAnswers(hostname: string, type: "A" | "AAAA", signal: AbortSignal): Promise<number> {
  const query = new URL("https://cloudflare-dns.com/dns-query");
  query.searchParams.set("name", hostname);
  query.searchParams.set("type", type);
  const response = await fetch(query.href, {
    headers: { Accept: "application/dns-json" }, redirect: "manual", cache: "no-store", signal,
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error("DNS resolver unavailable");
  }
  const data = JSON.parse(new TextDecoder().decode(await readBounded(response.body, 64 * 1024))) as {
    Status: number; TC: boolean;
    Question: Array<{ name: string; type: number }>;
    Answer?: Array<{ name: string; type: number; data: string }>;
  };
  const recordType = type === "A" ? 1 : 28;
  if (!data || data.Status !== 0 || data.TC !== false
    || !Array.isArray(data.Question) || data.Question.length !== 1
    || typeof data.Question[0]?.name !== "string"
    || data.Question[0].name.toLowerCase().replace(/\.$/, "") !== hostname
    || data.Question[0].type !== recordType
    || (data.Answer !== undefined && !Array.isArray(data.Answer))) {
    throw new Error("Invalid DNS response");
  }
  const answers = data.Answer ?? [];
  if (answers.length > 64) throw new Error("Too many DNS answers");
  const records = answers.map((record) => {
    if (!record || typeof record.name !== "string" || typeof record.data !== "string"
      || ![5, recordType].includes(record.type)) {
      throw new Error("Invalid DNS record");
    }
    const name = dnsHostname(record.name);
    if (record.type === 5) return { name, type: record.type, data: dnsHostname(record.data) };
    if (!publicDnsAddress(record.data, record.type)) {
      throw new ReaderError(400, "UNSAFE_URL", "目标域名解析到非公网地址。");
    }
    return { ...record, name };
  });
  const visited = new Set<string>();
  let current = hostname;
  for (let hop = 0; hop <= 8; hop++) {
    if (visited.has(current)) throw new Error("DNS alias loop");
    visited.add(current);
    const aliases = records.filter((record) => record.name === current && record.type === 5);
    // 所有地址记录已在 map 中通过公网校验；终端分支再验证全部记录的归属，不能先按 name 缩小校验范围。
    const addresses = records.filter((record) => record.type === recordType);
    if (aliases.length === 0) {
      if (addresses.some((record) => record.name !== current)) throw new Error("Unrelated DNS address");
      return addresses.length;
    }
    if (aliases.length !== 1 || addresses.some((record) => record.name === current)) {
      throw new Error("Ambiguous DNS alias");
    }
    current = aliases[0].data;
  }
  throw new Error("Too many DNS aliases");
}

export async function assertPublicReaderUrl(target: string, signal: AbortSignal): Promise<void> {
  const hostname = new URL(readerUrl(target)).hostname.toLowerCase().replace(/\.$/, "");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000);
  const resolutionSignal = AbortSignal.any([signal, controller.signal]);
  try {
    resolutionSignal.throwIfAborted();
    const counts = await Promise.all([
      readerDnsAnswers(hostname, "A", resolutionSignal),
      readerDnsAnswers(hostname, "AAAA", resolutionSignal),
    ]);
    resolutionSignal.throwIfAborted();
    if (counts[0] + counts[1] === 0) throw new Error("DNS returned no addresses");
  } catch (error) {
    if (error instanceof ReaderError && error.code === "UNSAFE_URL") throw error;
    throw new ReaderError(502, "DNS_RESOLUTION_FAILED", "无法确认目标域名的公网地址，请稍后重试。");
  } finally {
    clearTimeout(timeout);
    controller.abort();
  }
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
      await assertPublicReaderUrl(sourceUrl, controller.signal);
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
