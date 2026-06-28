/**
 * GET /api/v1/targets and /api/v1/regions — public target directories.
 *
 * Python: list_public_targets() and public_regions_payload().
 */

import type { RegionInfo, RegionListResponse, TargetInfo, TargetListResponse } from "../lib/contracts";
import {
  maybeServeCachedPublicRead,
  maybeStoreCachedPublicRead,
} from "../lib/public-read-cache";
import {
  markSnapshotBypass,
  markSnapshotMiss,
  readPublicSnapshot,
  REGIONS_ACTIVE_SNAPSHOT_KEY,
} from "../lib/public-read-snapshots";

function parseLifecycle(raw: unknown): Record<string, unknown> {
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function isIncluded(row: { event_count?: number; source_count?: number }, includeEmpty: boolean): boolean {
  return includeEmpty || Number(row.event_count || 0) > 0 || Number(row.source_count || 0) > 0;
}

async function loadTargets(db: D1Database, includeEmpty: boolean) {
  const result = await db
    .prepare(
      `SELECT target_id, display_name, region_id, primary_language, region_type,
              source_count, event_count, lifecycle, archived
       FROM targets
       WHERE archived = 0
       ORDER BY event_count DESC, display_name ASC
       LIMIT 200`,
    )
    .all();
  return (result.results || []).filter((row: any) => isIncluded(row, includeEmpty));
}

export async function handleTargets(
  _request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
): Promise<Response> {
  const includeEmpty = params.get("include_empty") === "true";
  const rows = await loadTargets(db, includeEmpty);
  const targets: TargetInfo[] = rows.map((row: any) => ({
    target_id: row.target_id,
    display_name: row.display_name,
    primary_language: row.primary_language || "en",
    region_type: row.region_type || "country",
    source_count: row.source_count || 0,
    event_count: row.event_count || 0,
    lifecycle: parseLifecycle(row.lifecycle),
    archived: !!row.archived,
  }));
  const body: TargetListResponse = { targets };
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
  });
}

export async function handleRegions(
  request: Request,
  db: D1Database,
  params: URLSearchParams,
  _segments: string[],
  ctx?: ExecutionContext,
): Promise<Response> {
  const includeEmpty = params.get("include_empty") === "true";
  const cacheKey = `public-read:regions:${includeEmpty ? "include-empty" : "active"}`;
  const cached = await maybeServeCachedPublicRead(request, cacheKey);
  if (cached) return cached;
  const snapshot = await readPublicSnapshot(
    request,
    db,
    includeEmpty ? null : REGIONS_ACTIVE_SNAPSHOT_KEY,
    300,
  );
  if (snapshot) return maybeStoreCachedPublicRead(request, cacheKey, snapshot, ctx, 300);

  const rows = await loadTargets(db, includeEmpty);
  const regions: RegionInfo[] = rows.map((row: any) => ({
    region_id: row.region_id || row.target_id,
    display_name: row.display_name,
    primary_language: row.primary_language || "en",
    region_type: row.region_type || "country",
    source_count: row.source_count || 0,
    event_count: row.event_count || 0,
    lifecycle: parseLifecycle(row.lifecycle),
    archived: !!row.archived,
  }));
  const body: RegionListResponse = { regions };
  const response = new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
  });
  const markedResponse = includeEmpty ? markSnapshotBypass(response) : markSnapshotMiss(response);
  return maybeStoreCachedPublicRead(request, cacheKey, markedResponse, ctx, 300);
}
