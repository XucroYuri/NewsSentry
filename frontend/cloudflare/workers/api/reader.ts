import { verifyCloudflareAccessJwt, type CloudflareAccessJwtEnv } from "../lib/access-jwt.ts";
import { canonicalPathname } from "../lib/path.ts";
import { PUBLIC_PUBLISHED_AT_SANITY_SQL } from "../lib/public-news-query.ts";
import { extractArticle } from "../lib/reader-extract.ts";
import { imageProxyUrl, readerImage, requireImageSecret } from "../lib/reader-image.ts";
import {
  getTranslationJob, submitTranslationJob, type ReaderTranslationJobsEnv,
} from "../lib/reader-translate-jobs.ts";
import {
  fetchReaderResource, markdownHash, normalizeMarkdown, readerBody,
  ReaderError, readerFailure, readerJson,
} from "../lib/reader-http.ts";

export interface ReaderEnv extends CloudflareAccessJwtEnv, ReaderTranslationJobsEnv {
  DB?: D1Database;
  READER_V1?: string;
  READER_IMAGE_SECRET?: string;
}

async function requireReaderSession(request: Request, env: ReaderEnv): Promise<string> {
  const origin = new URL(request.url).origin;
  if ((request.method !== "GET" && request.headers.get("Origin") !== origin)
    || (request.headers.has("Origin") && request.headers.get("Origin") !== origin)
    || request.headers.get("Sec-Fetch-Site") === "cross-site") {
    throw new ReaderError(403, "SAME_ORIGIN_REQUIRED", "阅读器要求同源请求。");
  }
  const cookie = request.headers.get("Cookie")?.split(";")
    .map((part) => part.trim()).find((part) => part.startsWith("CF_Authorization="))
    ?.slice("CF_Authorization=".length) ?? null;
  const assertion = request.headers.get("Cf-Access-Jwt-Assertion") || cookie;
  const verification = await verifyCloudflareAccessJwt(assertion, env);
  if (!verification.ok || verification.principal?.kind !== "user") {
    throw new ReaderError(403, "SESSION_REQUIRED", "需要有效的 Cloudflare Access 用户会话。");
  }
  return verification.principal.id;
}

async function preview(request: Request, env: ReaderEnv): Promise<Response> {
  const body = await readerBody(request);
  let url = body.url;
  if (body.articleId !== undefined) {
    if (typeof body.articleId !== "string" || !body.articleId.trim() || body.articleId.length > 256) {
      throw new ReaderError(400, "INVALID_ARTICLE_ID", "articleId 无效。");
    }
    if (!env.DB) throw new ReaderError(503, "READER_DB_UNAVAILABLE", "阅读器数据库未配置。");
    const row = await env.DB.prepare(
      `SELECT original_url FROM events WHERE events.event_id = ?
       AND events.pipeline_stage = 'drafts' AND ${PUBLIC_PUBLISHED_AT_SANITY_SQL}`,
    ).bind(body.articleId).first<{ original_url: string | null }>();
    if (!row) throw new ReaderError(404, "ARTICLE_NOT_FOUND", "未找到公开文章。");
    url = row.original_url;
  }
  if (url === undefined || url === null || url === "") {
    throw new ReaderError(400, "SOURCE_REQUIRED", "articleId 或 url 至少提供一个。");
  }
  if (typeof url !== "string") throw new ReaderError(400, "INVALID_URL", "url 必须是字符串。");
  const secret = requireImageSecret(env.READER_IMAGE_SECRET);
  const resource = await fetchReaderResource(url, "text/html,application/xhtml+xml", 2 * 1024 * 1024);
  if (!["text/html", "application/xhtml+xml"].includes(resource.contentType)) {
    throw new ReaderError(422, "UNSUPPORTED_CONTENT", `原站未返回 HTML，请打开原文：${resource.sourceUrl}`);
  }
  const article = extractArticle(new TextDecoder().decode(resource.bytes), resource.sourceUrl);
  let markdown = article.markdown;
  const images = [];
  for (const image of article.images) {
    const proxyUrl = await imageProxyUrl(image.src, secret);
    markdown = markdown.split(`](${image.src})`).join(`](${proxyUrl})`);
    images.push({ ...image, proxyUrl });
  }
  markdown = normalizeMarkdown(markdown);
  return readerJson({
    markdown, images, sourceUrl: resource.sourceUrl, lang: article.lang, title: article.title,
    byline: article.byline, publishedTime: article.publishedTime,
    contentHash: await markdownHash(markdown),
    attribution: `原文来源：${new URL(resource.sourceUrl).hostname} · ${resource.sourceUrl}`,
  });
}

/** 独立旁路：flag 关闭时在认证、数据库与网络调用前返回 404。 */
export async function handleReader(request: Request, env: ReaderEnv): Promise<Response> {
  try {
    if (env.READER_V1 !== "1") throw new ReaderError(404, "READER_DISABLED", "阅读器旁路未启用。");
    const path = canonicalPathname(new URL(request.url).pathname);
    if (path === "/api/v1/reader/image" && request.method === "GET") {
      return await readerImage(request, env.READER_IMAGE_SECRET);
    }
    const job = /^\/api\/v1\/reader\/translate\/([a-f0-9-]{36})$/.exec(path);
    if (job && request.method === "GET") {
      const owner = await requireReaderSession(request, env);
      return await getTranslationJob(job[1], env, owner);
    }
    if (!["/api/v1/reader/preview", "/api/v1/reader/translate"].includes(path) || request.method !== "POST") {
      throw new ReaderError(404, "READER_ROUTE_NOT_FOUND", "阅读器端点不存在。");
    }
    const owner = await requireReaderSession(request, env);
    return path.endsWith("/translate") ? await submitTranslationJob(request, env, owner) : await preview(request, env);
  } catch (error) {
    return readerFailure(error);
  }
}
