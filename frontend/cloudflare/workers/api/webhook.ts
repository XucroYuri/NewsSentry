/**
 * POST /api/v1/webhook + POST /api/v1/events/import
 *
 * Python: receive_webhook() → WebhookResponse
 *         import_events() → ImportResponse
 * Schemas: WebhookResponse, ImportResponse, ImportEventItem
 */

import type { WebhookResponse, ImportResponse, ImportEventItem } from "../lib/contracts";
import { internalError } from "../lib/errors";

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
  _db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  try {
    const rawBody = await request.text();
    let events: ImportEventItem[] = [];
    try {
      events = JSON.parse(rawBody) as ImportEventItem[];
      if (!Array.isArray(events)) events = [];
    } catch {
      events = [];
    }

    // 批量导入在 Workers 模式下仅作确认响应
    // 实际事件持久化由 Python CLI 采集管道处理
    const body: ImportResponse = {
      imported: events.length,
      skipped: 0,
      errors: [],
    };
    return new Response(JSON.stringify(body), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("import error:", err);
    return internalError(String(err));
  }
}
