/**
 * POST /api/v1/webhook + POST /api/v1/events/import
 *
 * Python: receive_webhook() → WebhookResponse
 *         import_events() → ImportResponse
 * Schemas: WebhookResponse, ImportResponse, ImportEventItem
 */

import type { WebhookResponse, ImportResponse, ImportEventItem } from "../lib/contracts";
import { internalError } from "../lib/errors";
import { refreshBreakingScoreStats } from "../lib/breaking-calibration";
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

function nonEmptyText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function jsonArrayText(value: unknown): string | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  return JSON.stringify(value);
}

function jsonObjectText(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.keys(value as Record<string, unknown>).length > 0 ? JSON.stringify(value) : null;
}

function hasProjectionUpdate(item: ImportEventWithId): boolean {
  return Boolean(
    nonEmptyText(item.title) ||
      nonEmptyText(item.summary) ||
      nonEmptyText(item.recommendation_reason) ||
      nonEmptyText(item.language) ||
      nonEmptyText(item.pipeline_stage) ||
      nonEmptyText(item.value_label) ||
      nonEmptyText(item.china_relevance_label) ||
      typeof item.value_score === "number" ||
      jsonArrayText(item.tags) ||
      jsonArrayText(item.issue_tags) ||
      jsonArrayText(item.related_tags) ||
      jsonArrayText(item.region_tags) ||
      jsonArrayText(item.image_urls) ||
      jsonArrayText(item.entities) ||
      jsonObjectText(item.classification) ||
      typeof item.breaking_raw_score === "number" ||
      typeof item.breaking_percentile === "number" ||
      typeof item.breaking_calibrated_score === "number" ||
      typeof item.breaking_score === "number" ||
      nonEmptyText(item.breaking_label) ||
      nonEmptyText(item.breaking_reason) ||
      typeof item.breaking_confidence === "number" ||
      jsonObjectText(item.breaking_dimensions) ||
      jsonObjectText(item.breaking_adversarial_flags) ||
      nonEmptyText(item.target_timezone) ||
      nonEmptyText(item.published_at_local) ||
      (Array.isArray(item.localizations) && item.localizations.length > 0),
  );
}

async function upsertLocalizations(db: D1Database, eventId: string, item: ImportEventWithId): Promise<void> {
  if (!Array.isArray(item.localizations) || item.localizations.length === 0) return;
  for (const loc of item.localizations) {
    if (!loc || typeof loc !== "object") continue;
    const locale = nonEmptyText(loc.locale);
    const title = nonEmptyText(loc.title);
    if (!locale || !title) continue;
    await db
      .prepare(
        `INSERT INTO event_localizations (
           event_id, locale, localized_title, localized_summary,
           localized_recommendation_reason, localized_tags,
           localized_issue_tags, localized_related_tags, localized_region_tags,
           localized_language, quality_score, model, route_id, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
         ON CONFLICT(event_id, locale) DO UPDATE SET
           localized_title=COALESCE(NULLIF(excluded.localized_title, ''), event_localizations.localized_title),
           localized_summary=COALESCE(NULLIF(excluded.localized_summary, ''), event_localizations.localized_summary),
           localized_recommendation_reason=COALESCE(
             NULLIF(excluded.localized_recommendation_reason, ''),
             event_localizations.localized_recommendation_reason
           ),
           localized_tags=COALESCE(NULLIF(excluded.localized_tags, '[]'), event_localizations.localized_tags),
           localized_issue_tags=COALESCE(
             NULLIF(excluded.localized_issue_tags, '[]'),
             event_localizations.localized_issue_tags
           ),
           localized_related_tags=COALESCE(
             NULLIF(excluded.localized_related_tags, '[]'),
             event_localizations.localized_related_tags
           ),
           localized_region_tags=COALESCE(
             NULLIF(excluded.localized_region_tags, '[]'),
             event_localizations.localized_region_tags
           ),
           localized_language=COALESCE(
             NULLIF(excluded.localized_language, ''),
             event_localizations.localized_language
           ),
           quality_score=MAX(event_localizations.quality_score, excluded.quality_score),
           model=COALESCE(NULLIF(excluded.model, ''), event_localizations.model),
           route_id=COALESCE(NULLIF(excluded.route_id, ''), event_localizations.route_id),
           updated_at=datetime('now')`
      )
      .bind(
        eventId,
        locale,
        title,
        nonEmptyText(loc.summary),
        nonEmptyText(loc.recommendation_reason),
        jsonText(loc.tags, []),
        jsonText(loc.issue_tags, []),
        jsonText(loc.related_tags, []),
        jsonText(loc.region_tags, []),
        nonEmptyText(loc.language) || locale,
        typeof loc.quality_score === "number" ? loc.quality_score : 0,
        nonEmptyText(loc.model) || "",
        nonEmptyText(loc.route_id) || "",
      )
      .run();
  }
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
  let updated = 0;
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
      if (!hasProjectionUpdate(item)) {
        skipped += 1;
        continue;
      }
      await db
        .prepare(
          `UPDATE events SET
             title = COALESCE(NULLIF(?, ''), title),
             summary = COALESCE(NULLIF(?, ''), summary),
             recommendation_reason = COALESCE(NULLIF(?, ''), recommendation_reason),
             image_urls = COALESCE(?, image_urls),
             tags = COALESCE(?, tags),
             issue_tags = COALESCE(?, issue_tags),
             related_tags = COALESCE(?, related_tags),
             region_tags = COALESCE(?, region_tags),
             entities = COALESCE(?, entities),
             language = COALESCE(NULLIF(?, ''), language),
             pipeline_stage = COALESCE(NULLIF(?, ''), pipeline_stage),
             value_label = COALESCE(NULLIF(?, ''), value_label),
             value_score = COALESCE(?, value_score),
             china_relevance_label = COALESCE(NULLIF(?, ''), china_relevance_label),
             classification = COALESCE(?, classification),
             breaking_raw_score = COALESCE(?, breaking_raw_score),
             breaking_percentile = COALESCE(?, breaking_percentile),
             breaking_calibrated_score = COALESCE(?, breaking_calibrated_score),
             breaking_score = COALESCE(?, breaking_score),
             breaking_label = COALESCE(NULLIF(?, ''), breaking_label),
             breaking_reason = COALESCE(NULLIF(?, ''), breaking_reason),
             breaking_confidence = COALESCE(?, breaking_confidence),
             breaking_dimensions = COALESCE(?, breaking_dimensions),
             breaking_adversarial_flags = COALESCE(?, breaking_adversarial_flags),
             breaking_score_version = COALESCE(NULLIF(?, ''), breaking_score_version),
             target_timezone = COALESCE(NULLIF(?, ''), target_timezone),
             published_at_local = COALESCE(NULLIF(?, ''), published_at_local),
             updated_at = datetime('now')
           WHERE event_id = ?`
        )
        .bind(
          nonEmptyText(item.title),
          nonEmptyText(item.summary),
          nonEmptyText(item.recommendation_reason),
          jsonArrayText(item.image_urls),
          jsonArrayText(item.tags),
          jsonArrayText(item.issue_tags),
          jsonArrayText(item.related_tags),
          jsonArrayText(item.region_tags),
          jsonArrayText(item.entities),
          nonEmptyText(item.language),
          nonEmptyText(item.pipeline_stage),
          nonEmptyText(item.value_label),
          typeof item.value_score === "number" ? item.value_score : null,
          nonEmptyText(item.china_relevance_label),
          jsonObjectText(item.classification),
          typeof item.breaking_raw_score === "number" ? item.breaking_raw_score : null,
          typeof item.breaking_percentile === "number" ? item.breaking_percentile : null,
          typeof item.breaking_calibrated_score === "number" ? item.breaking_calibrated_score : null,
          typeof item.breaking_score === "number" ? item.breaking_score : null,
          nonEmptyText(item.breaking_label),
          nonEmptyText(item.breaking_reason),
          typeof item.breaking_confidence === "number" ? item.breaking_confidence : null,
          jsonObjectText(item.breaking_dimensions),
          jsonObjectText(item.breaking_adversarial_flags),
          nonEmptyText(item.breaking_score_version),
          nonEmptyText(item.target_timezone),
          nonEmptyText(item.published_at_local),
          eventId,
        )
        .run();
      await upsertLocalizations(db, eventId, item);
      updated += 1;
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
           , breaking_raw_score, breaking_percentile, breaking_calibrated_score,
           breaking_score, breaking_label, breaking_reason, breaking_confidence,
           breaking_dimensions, breaking_adversarial_flags, breaking_score_version,
           target_timezone, published_at_local
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(event_id) DO UPDATE SET
           target_id=excluded.target_id,
           target_label=excluded.target_label,
           region_id=excluded.region_id,
           source_id=excluded.source_id,
           source_name=excluded.source_name,
           source_type=excluded.source_type,
           published_at=COALESCE(NULLIF(excluded.published_at, ''), events.published_at),
           collected_at=COALESCE(NULLIF(excluded.collected_at, ''), events.collected_at),
           title=COALESCE(NULLIF(excluded.title, ''), events.title),
           original_title=COALESCE(NULLIF(excluded.original_title, ''), events.original_title),
           summary=COALESCE(NULLIF(excluded.summary, ''), events.summary),
           recommendation_reason=COALESCE(
             NULLIF(excluded.recommendation_reason, ''),
             events.recommendation_reason
           ),
           full_content=COALESCE(NULLIF(excluded.full_content, ''), events.full_content),
           original_url=COALESCE(NULLIF(excluded.original_url, ''), events.original_url),
           detail_url=COALESCE(NULLIF(excluded.detail_url, ''), events.detail_url),
           image_urls=COALESCE(NULLIF(excluded.image_urls, '[]'), events.image_urls),
           tags=COALESCE(NULLIF(excluded.tags, '[]'), events.tags),
           issue_tags=COALESCE(NULLIF(excluded.issue_tags, '[]'), events.issue_tags),
           related_tags=COALESCE(NULLIF(excluded.related_tags, '[]'), events.related_tags),
           region_tags=COALESCE(NULLIF(excluded.region_tags, '[]'), events.region_tags),
           entities=COALESCE(NULLIF(excluded.entities, '[]'), events.entities),
           language=COALESCE(NULLIF(excluded.language, ''), events.language),
           pipeline_stage=COALESCE(NULLIF(excluded.pipeline_stage, ''), events.pipeline_stage),
           value_label=COALESCE(NULLIF(excluded.value_label, ''), events.value_label),
           value_score=COALESCE(excluded.value_score, events.value_score),
           china_relevance_label=COALESCE(
             NULLIF(excluded.china_relevance_label, ''),
             events.china_relevance_label
           ),
           classification=COALESCE(NULLIF(excluded.classification, '{}'), events.classification),
           breaking_raw_score=COALESCE(excluded.breaking_raw_score, events.breaking_raw_score),
           breaking_percentile=COALESCE(excluded.breaking_percentile, events.breaking_percentile),
           breaking_calibrated_score=COALESCE(
             excluded.breaking_calibrated_score,
             events.breaking_calibrated_score
           ),
           breaking_score=COALESCE(excluded.breaking_score, events.breaking_score),
           breaking_label=COALESCE(NULLIF(excluded.breaking_label, ''), events.breaking_label),
           breaking_reason=COALESCE(NULLIF(excluded.breaking_reason, ''), events.breaking_reason),
           breaking_confidence=COALESCE(excluded.breaking_confidence, events.breaking_confidence),
           breaking_dimensions=COALESCE(NULLIF(excluded.breaking_dimensions, '{}'), events.breaking_dimensions),
           breaking_adversarial_flags=COALESCE(
             NULLIF(excluded.breaking_adversarial_flags, '{}'),
             events.breaking_adversarial_flags
           ),
           breaking_score_version=COALESCE(
             NULLIF(excluded.breaking_score_version, ''),
             events.breaking_score_version
           ),
           target_timezone=COALESCE(NULLIF(excluded.target_timezone, ''), events.target_timezone),
           published_at_local=COALESCE(
             NULLIF(excluded.published_at_local, ''),
             events.published_at_local
           ),
           updated_at=datetime('now')`
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
        item.breaking_raw_score ?? item.breaking_score ?? item.value_score ?? null,
        item.breaking_percentile ?? item.breaking_score ?? item.value_score ?? null,
        item.breaking_calibrated_score ?? item.breaking_score ?? item.value_score ?? null,
        item.breaking_score ?? item.value_score ?? null,
        item.breaking_label || null,
        item.breaking_reason || null,
        item.breaking_confidence ?? null,
        jsonText(item.breaking_dimensions, {}),
        jsonText(item.breaking_adversarial_flags, {}),
        item.breaking_score_version || null,
        item.target_timezone || "UTC",
        item.published_at_local || null,
      )
      .run();
    await upsertLocalizations(db, eventId, item);
    imported += 1;
  }

  return {
    imported,
    updated,
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
    if (body.imported > 0 || body.updated > 0) {
      try {
        await refreshBreakingScoreStats(db);
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
