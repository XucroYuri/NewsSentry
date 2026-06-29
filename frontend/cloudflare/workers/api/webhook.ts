/**
 * POST /api/v1/webhook + POST /api/v1/events/import
 *
 * Python: receive_webhook() → WebhookResponse
 *         import_events() → ImportResponse
 * Schemas: WebhookResponse, ImportResponse, ImportEventItem
 */

import type { WebhookResponse, ImportResponse, ImportEventItem } from "../lib/contracts";
import { internalError } from "../lib/errors";
import { refreshPublicReadSnapshots } from "../lib/public-read-snapshots";

type ImportEventWithId = ImportEventItem & {
  event_id?: string;
  title?: string;
  summary?: string;
  recommendation_reason?: string;
  source_name?: string;
  source_type?: string;
  region_id?: string;
  tags?: string[];
  issue_tags?: string[];
  related_tags?: string[];
  region_tags?: string[];
  image_urls?: string[];
  entities?: Array<Record<string, unknown>>;
  value_label?: string;
  value_score?: number;
  china_relevance_label?: string;
};

function jsonText(value: unknown, fallback: unknown): string {
  return JSON.stringify(value ?? fallback);
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function eventIdFor(item: ImportEventWithId): Promise<string> {
  const explicitId = item.event_id?.trim();
  if (explicitId) return explicitId;

  const digest = await sha256Hex([
    item.target_id,
    item.source_id,
    item.url,
    item.title_original,
    item.collected_at,
  ].join("\0"));
  return `cf-${item.target_id}-${digest.slice(0, 16)}`;
}

export async function importEventsToD1(
  db: D1Database,
  events: ImportEventWithId[],
): Promise<ImportResponse> {
  let imported = 0;
  let skipped = 0;
  const errors: string[] = [];

  for (const [idx, item] of events.entries()) {
    if (!item.target_id || !item.source_id || !item.title_original || !item.url || !item.collected_at) {
      errors.push(`item ${idx}: missing required import fields`);
      continue;
    }

    const eventId = await eventIdFor(item);
    const existing = await db
      .prepare("SELECT event_id FROM events WHERE event_id = ?")
      .bind(eventId)
      .first<{ event_id: string }>();
    if (existing) {
      skipped += 1;
      continue;
    }

    const publishedAt = item.published_at || item.collected_at;
    const title = item.title || item.title_original;
    await db
      .prepare(
        `INSERT INTO events (
           event_id, target_id, target_label, region_id,
           source_id, source_name, source_type,
           published_at, collected_at,
           title, original_title, summary, recommendation_reason, full_content,
           original_url, detail_url,
           image_urls, tags, issue_tags, related_tags, region_tags, entities,
           language, pipeline_stage,
           value_label, value_score, china_relevance_label, classification
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(event_id) DO NOTHING`
      )
      .bind(
        eventId,
        item.target_id,
        item.target_id,
        item.region_id || item.target_id,
        item.source_id,
        item.source_name || item.source_id,
        item.source_type || "unknown",
        publishedAt,
        item.collected_at,
        title,
        item.title_original,
        item.summary || null,
        item.recommendation_reason || null,
        item.content_original || null,
        item.url,
        `/public-app/news/${eventId}`,
        jsonText(item.image_urls, []),
        jsonText(item.tags, []),
        jsonText(item.issue_tags, []),
        jsonText(item.related_tags, []),
        jsonText(item.region_tags, [item.region_id || item.target_id]),
        jsonText(item.entities, []),
        item.language || "mixed",
        item.pipeline_stage || "published",
        item.value_label || "普通",
        item.value_score ?? null,
        item.china_relevance_label || "未知",
        jsonText(item.classification, {}),
      )
      .run();
    imported += 1;
  }

  return {
    imported,
    skipped,
    errors,
  };
}

export async function handleWebhook(
  request: Request,
  _db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    // Webhook 入站在 Workers 模式下仅作确认响应
    // 实际事件持久化由 Python CLI 采集管道处理
    const body: WebhookResponse = {
      status: "received",
      event_id: `wh-${Date.now()}`,
      message: "Webhook received. Processing via Python CLI pipeline.",
    };
    return new Response(JSON.stringify(body), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("webhook error:", err);
    return internalError(String(err));
  }
}

export async function handleImport(
  request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    const rawBody = await request.text();
    let events: ImportEventWithId[] = [];
    try {
      events = JSON.parse(rawBody) as ImportEventWithId[];
      if (!Array.isArray(events)) events = [];
    } catch {
      events = [];
    }

    const body = await importEventsToD1(db, events);
    if (body.imported > 0) {
      try {
        await refreshPublicReadSnapshots(db);
      } catch (error) {
        console.warn("public snapshot refresh after import failed:", error);
      }
    }
    return new Response(JSON.stringify(body), {
      status: body.errors.length ? 207 : 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("import error:", err);
    return internalError(String(err));
  }
}
