/**
 * 可移植采集事件 `CollectedEvent` 与确定性 ID `makeCollectId`。
 *
 * 对齐 Python `NewsEvent`（src/news_sentry/models/newsevent.py）的 collect 产出字段子集。
 * ID 格式 `ne-{target}-{src}-{yyyymmdd}-{hash8}`，hash8 由
 * SHA-256(target_id + source_id + url + published_at_iso) 截取前 8 位十六进制生成，
 * 与 Python `hashlib.sha256(...).hexdigest()[:8]` 一致。
 */

import type { FeedEntry } from "./rss-parser.ts";

/**
 * 内容语言（常量对象 + 联合类型；句法对齐 `enum Language` 用法 `Language.IT`）。
 * Node strip-only 不支持真实 TS enum，故用 `as const` 对象表达同一集合。
 * VALUES 取自 contracts-canonical（含 ar/es/ja 扩展）。
 */
export const Language = {
  MIXED: "mixed",
  IT: "it",
  EN: "en",
  DE: "de",
  FR: "fr",
  ES: "es",
  AR: "ar",
  ZH: "zh",
  JA: "ja",
} as const;

export type Language = (typeof Language)[keyof typeof Language];

const LANGUAGE_VALUES = new Set<string>(Object.values(Language));

/** 小写匹配已知语言；未知/缺失 → def（默认 MIXED）。`-`/`_` 主子标签均取首段。 */
export function coerceLanguage(value: string | null | undefined, def: Language = Language.MIXED): Language {
  const normalized = value?.trim().toLowerCase() ?? "";
  const base = normalized.split(/[-_]/)[0] as Language;
  return LANGUAGE_VALUES.has(base) ? base : def;
}

/**
 * 把原始发布时间（RSS pubDate / Atom published / 任意 ISO）归一化为 canonical ISO-8601 UTC 串。
 *
 * 对齐 Python `datetime.fromtimestamp(ts, tz=UTC).isoformat()` 的输出：
 * `YYYY-MM-DDTHH:MM:SS+00:00`（秒精度、无小数、`+00:00` 而非 `Z`）。
 * 解析失败 → 原样返回 raw（优雅降级，不抛错）。
 */
export function normalizePublishedAt(raw: string): string {
  if (!raw || typeof raw !== "string") return raw;
  const ms = Date.parse(raw);
  if (Number.isNaN(ms)) return raw;
  // toISOString() -> `2024-01-01T00:00:00.000Z`；去毫秒、`Z`→`+00:00` 对齐 Python isoformat()。
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

/**
 * 生成确定性 CollectedEvent.id。
 *
 * 格式: `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`。
 * hash8 = SHA-256(target_id + source_id + url + published_at_iso) 前 8 位十六进制。
 * `published_at_iso` 取前 10 位 `YYYY-MM-DD` 去 `-` 得到 yyyymmdd（对齐 Python `strftime("%Y%m%d")`）；
 * 不可解析 → 用当前 UTC 日期。
 *
 * 异步：优先用 Web Crypto `crypto.subtle.digest`；环境不可用时回退 Node `node:crypto`。
 * 两者产出一致（同一 SHA-256）。
 */
export async function makeCollectId(
  target_id: string,
  source_id: string,
  url: string,
  published_at_iso: string,
): Promise<string> {
  const dateStr = datePart(published_at_iso);
  const hash8 = (await sha256Hex(`${target_id}${source_id}${url}${published_at_iso}`)).slice(0, 8);
  return `ne-${target_id}-${source_id}-${dateStr}-${hash8}`;
}

/** 从 ISO 字符串取 `%Y%m%d`；形状合法但非真实日历日期 → 当前 UTC 日期（对齐 Python `fromisoformat` 拒绝语义）。 */
function datePart(publishedAtIso: string): string {
  if (publishedAtIso && typeof publishedAtIso === "string") {
    const d = publishedAtIso.slice(0, 10);
    // 形状校验 YYYY-MM-DD，再用 round-trip 校验真实日历日期（如 2024-02-30 → 非法回退）。
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
      const dt = new Date(`${d}T00:00:00Z`);
      if (dt.toISOString().slice(0, 10) === d) return d.replaceAll("-", "");
    }
  }
  return new Date().toISOString().slice(0, 10).replaceAll("-", "");
}

export async function sha256Hex(input: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    const buf = await subtle.digest("SHA-256", new TextEncoder().encode(input));
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  }
  // 环境无 crypto.subtle 时回退 Node 内置 SHA-256。
  const { createHash } = await import("node:crypto");
  return createHash("sha256").update(input, "utf8").digest("hex");
}

/**
 * 用解析后的 FeedEntry 组装便携式采集事件。
 *
 * published_at 归一化为 canonical ISO（对齐 Python `event.published_at`）后，
 * 才参与 `makeCollectId` 的 hash 计算，保证与 Python `NewsEvent.make_id` 一致。
 * collected_at 记录采集时刻（ISO）。
 * feed_url 存入 `metadata.collection.feed_url`（对齐 Python `_entry_to_event`）。
 */
export async function collectedEventFromEntry(
  target_id: string,
  source_id: string,
  run_id: string,
  language: Language,
  feed_url: string,
  entry: FeedEntry,
): Promise<CollectedEvent> {
  const published_at = normalizePublishedAt(entry.published_at);
  const id = await makeCollectId(target_id, source_id, entry.link, published_at);
  return {
    id,
    run_id,
    source_id,
    url: entry.link,
    title_original: entry.title,
    content_original: entry.content,
    language,
    published_at,
    collected_at: new Date().toISOString(),
    pipeline_stage: "collected",
    metadata: { collection: { feed_url } },
  };
}

/** 可移植采集事件。对齐 Python `NewsEvent` 的 collect 产出字段子集。 */
export interface CollectedEvent {
  id: string;
  run_id: string;
  source_id: string;
  url: string;
  title_original: string;
  content_original: string;
  language: Language;
  published_at: string;
  collected_at: string;
  pipeline_stage: "collected";
  metadata: Record<string, unknown>;
}
