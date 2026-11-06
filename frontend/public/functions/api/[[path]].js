/**
 * Preview Pages 的 /api/* 入口。
 *
 * 把原始 Request 交给 PREVIEW_API（news-sentry-api-preview）。
 * 不改 URL，这样 Worker 看到的 Origin 仍是预览主机，Access 用户 Cookie 保持同源。
 * 没有 binding，或主机是生产域名时，继续走 Pages 静态资源。
 */
import { previewApiProxyHost } from "../preview-api-host.js"

export async function onRequest(context) {
  const api = context.env.PREVIEW_API
  const hostname = new URL(context.request.url).hostname
  if (!api || !previewApiProxyHost(hostname)) return context.next()
  return api.fetch(context.request)
}
