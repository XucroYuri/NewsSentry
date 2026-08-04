/**
 * 源抓取 + 归一化 `fetchCollectedEvents`。
 *
 * 对齐 Python 采集库（src/news_sentry/collector/...）的抓取语义：
 * - `_raise_on_redirect`：3xx 重定向视为失败 → `http_error`，不抛。
 * - `_retry_fetch`：对 5xx / 网络错误 / 超时重试一次，仍失败则不抛，记为 `http_error`。
 * - 2xx → text → parseFeed → 每条 entry 归一化为 `CollectedEvent`。
 * - entries 为空 → `parse_error`（简化取舍：判空即 parse_error，不区分合法空 feed）。
 *
 * 抓/解析失败一律返回非 `ok` 的 `CollectOutcome`，不对外抛异常。
 */

import { parseFeed } from "./rss-parser.ts";
import { collectedEventFromEntry, coerceLanguage } from "./collected-event.ts";
import type { CollectedEvent } from "./collected-event.ts";

export interface CollectSource {
  target_id: string;
  source_id: string;
  url: string;
  language?: string;
  fetch_full_article?: boolean;
}

export interface CollectOutcome {
  events: CollectedEvent[];
  fetch_status: "ok" | "http_error" | "parse_error";
  status_code?: number;
  error?: string;
  latest_public_at?: string;
}

/** 2xx 视为成功；3xx 视为重定向失败（对齐 Python `_raise_on_redirect`）。 */
function isOkStatus(status: number): boolean {
  return status >= 200 && status < 300;
}

/**
 * 抓取 `source.url`，对 5xx / 网络错误重试一次（对齐 Python `_retry_fetch`）。
 * 最终非 2xx 或网络失败返回 null（调用方转为 `http_error`）。
 * `redirect: "manual"`：禁止跟随 3xx，重定向与 Python `_raise_on_redirect` 一致 → `http_error`。
 */
async function fetchBody(
  url: string,
  fetcher: typeof fetch,
): Promise<{ status: number; text: string } | null> {
  const attempts = [1, 2]; // 首次 + 重试一次
  for (const attempt of attempts) {
    try {
      const res = await fetcher(url, { redirect: "manual" });
      const status = res.status;
      // 5xx / 网络瞬时错误：重试一次；4xx、3xx 等客户端/重定向态不重试。
      if (status >= 500 && attempt < attempts.length) continue;
      const text = await res.text();
      return { status, text };
    } catch {
      // 网络错误 / 超时：重试一次后仍失败返回 null。
      if (attempt >= attempts.length) return null;
    }
  }
  return null;
}

export async function fetchCollectedEvents(
  source: CollectSource,
  run_id: string,
  deps: { fetcher?: typeof fetch },
): Promise<CollectOutcome> {
  const fetcher = deps.fetcher ?? globalThis.fetch;

  // 网络失败（重试后）或无 fetcher 可用 → http_error。
  if (!fetcher) {
    return { events: [], fetch_status: "http_error", error: "no fetcher available" };
  }

  let body: { status: number; text: string } | null;
  try {
    body = await fetchBody(source.url, fetcher);
  } catch {
    body = null;
  }
  if (!body) {
    return { events: [], fetch_status: "http_error", error: "network error" };
  }
  if (!isOkStatus(body.status)) {
    return {
      events: [],
      fetch_status: "http_error",
      status_code: body.status,
      error: `http_status_${body.status}`,
    };
  }

  // 2xx：解析为 feed。
  const feed = parseFeed(body.text);
  if (feed.entries.length === 0) {
    return { events: [], fetch_status: "parse_error", error: "no entries in feed" };
  }

  const language = coerceLanguage(source.language);
  const events: CollectedEvent[] = [];
  for (const entry of feed.entries) {
    events.push(
      await collectedEventFromEntry(
        source.target_id,
        source.source_id,
        run_id,
        language,
        source.url,
        entry,
      ),
    );
  }

  return { events, fetch_status: "ok" };
}
