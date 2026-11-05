import { fetchReaderResource, ReaderError, readerUrl } from "./reader-http.ts";

export function requireImageSecret(secret: string | undefined): string {
  if (!secret || secret.length < 32) {
    throw new ReaderError(503, "IMAGE_PROXY_UNCONFIGURED", "阅读器图片签名尚未配置。");
  }
  return secret;
}

async function imageKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", new TextEncoder().encode(requireImageSecret(secret)),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

function imagePayload(src: string): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(`reader-image-v1\n${src}`);
}

export async function imageProxyUrl(src: string, secret: string): Promise<string> {
  const url = readerUrl(src);
  const bytes = await crypto.subtle.sign("HMAC", await imageKey(secret), imagePayload(url));
  const signature = Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `/api/v1/reader/image?${new URLSearchParams({ u: url, s: signature })}`;
}

export async function readerImage(request: Request, secret: string | undefined): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const src = params.get("u") ?? "";
  const signature = params.get("s") ?? "";
  // 未验签时不解析/访问 u；cookie 不授予代理权限。
  if (!/^[a-f0-9]{64}$/.test(signature)) throw new ReaderError(403, "INVALID_IMAGE_SIGNATURE", "图片签名无效。");
  const bytes = Uint8Array.from(signature.match(/../g)!, (hex) => parseInt(hex, 16));
  if (!await crypto.subtle.verify("HMAC", await imageKey(requireImageSecret(secret)), bytes, imagePayload(src))) {
    throw new ReaderError(403, "INVALID_IMAGE_SIGNATURE", "图片签名无效。");
  }
  const resource = await fetchReaderResource(src, "image/avif,image/webp,image/png,image/jpeg,image/gif", 5 * 1024 * 1024);
  const allowed = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"];
  if (!allowed.includes(resource.contentType)) {
    throw new ReaderError(422, "UNSUPPORTED_IMAGE", "原站未返回支持的位图图片。");
  }
  return new Response(resource.bytes, {
    headers: {
      "Content-Type": resource.contentType, "X-Content-Type-Options": "nosniff",
      "Cache-Control": "private, max-age=3600", "Cross-Origin-Resource-Policy": "same-origin",
      "Content-Security-Policy": "default-src 'none'; sandbox",
    },
  });
}
