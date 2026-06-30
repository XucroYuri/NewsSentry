import type {
  PublicBootstrapResponse,
  PublicFacetItem,
  PublicFacetsResponse,
  PublicNewsFeedResponse,
  RegionInfo,
  RegionListResponse,
} from "./contracts";
import {
  buildPublicNewsWhere,
  type NewsRow,
  type PublicLocale,
  publicNewsOrderBy,
  publicNewsLocaleJoin,
  publicNewsSelectColumnsForLocale,
  rowToPublicNewsItem,
  SUPPORTED_PUBLIC_LOCALES,
} from "./public-news-query";
import { createPublicReadSession } from "./public-read-session";
import { publicReadCacheControl } from "./public-read-cache";

export const PUBLIC_SNAPSHOT_PAGE_SIZE = 20;
export const NEWS_FEATURED_SNAPSHOT_KEY = "news:featured:v1:page_size=20";
export const NEWS_ALL_SNAPSHOT_KEY = "news:all:v1:page_size=20";
export const BOOTSTRAP_FEATURED_SNAPSHOT_KEY = "bootstrap:featured:v1:page_size=20";
export const FACETS_SNAPSHOT_KEY = "facets:v1";
export const REGIONS_ACTIVE_SNAPSHOT_KEY = "regions:active:v1";
export const PUBLIC_LOCALE_SNAPSHOT_KEY_MARKERS =
  "locale=zh locale=en locale=es locale=ar locale=fr";

export function newsFeaturedSnapshotKey(locale: PublicLocale = "zh"): string {
  return locale === "zh"
    ? NEWS_FEATURED_SNAPSHOT_KEY
    : `news:featured:v1:locale=${locale}:page_size=20`;
}

export function newsAllSnapshotKey(locale: PublicLocale = "zh"): string {
  return locale === "zh"
    ? NEWS_ALL_SNAPSHOT_KEY
    : `news:all:v1:locale=${locale}:page_size=20`;
}

export function bootstrapFeaturedSnapshotKey(locale: PublicLocale = "zh"): string {
  return locale === "zh"
    ? BOOTSTRAP_FEATURED_SNAPSHOT_KEY
    : `bootstrap:featured:v1:locale=${locale}:page_size=20`;
}

type SnapshotState = "hit" | "miss" | "bypass";

interface SnapshotRow {
  payload_json: string;
}

function withSnapshotHeader(response: Response, state: SnapshotState): Response {
  const headers = new Headers(response.headers);
  headers.set("X-News-Sentry-Snapshot", state);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function jsonResponse(payloadJson: string, cacheSeconds: number): Response {
  return new Response(payloadJson, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": publicReadCacheControl(cacheSeconds),
    },
  });
}

function snapshotEtag(key: string, payloadJson: string): string {
  return `"${key.length.toString(16)}-${payloadJson.length.toString(16)}"`;
}

function boundedSnapshotPageSize(pageSize: number): number {
  return Number.isFinite(pageSize) && pageSize > 0
    ? Math.min(Math.trunc(pageSize), PUBLIC_SNAPSHOT_PAGE_SIZE)
    : PUBLIC_SNAPSHOT_PAGE_SIZE;
}

export function slicePublicNewsSnapshot(
  feed: PublicNewsFeedResponse,
  pageSize: number,
): PublicNewsFeedResponse {
  const boundedPageSize = boundedSnapshotPageSize(pageSize);
  if (boundedPageSize >= PUBLIC_SNAPSHOT_PAGE_SIZE) return feed;

  const items = feed.items.slice(0, boundedPageSize);
  const hasMore =
    feed.items.length > items.length ||
    feed.total > items.length ||
    Boolean(feed.nextCursor);

  return {
    ...feed,
    items,
    latestCursor: items[0]?.id ?? feed.latestCursor ?? null,
    nextCursor: hasMore ? (items[items.length - 1]?.id ?? null) : null,
    hasNewer: false,
  };
}

export function sliceBootstrapSnapshot(
  bootstrap: PublicBootstrapResponse,
  pageSize: number,
): PublicBootstrapResponse {
  return {
    ...bootstrap,
    news: slicePublicNewsSnapshot(bootstrap.news, pageSize),
  };
}

export function markSnapshotMiss(response: Response): Response {
  return withSnapshotHeader(response, "miss");
}

export function markSnapshotBypass(response: Response): Response {
  return withSnapshotHeader(response, "bypass");
}

export async function readPublicSnapshot(
  request: Request,
  db: D1Database,
  key: string | null,
  cacheSeconds: number,
): Promise<Response | null> {
  if (request.method !== "GET" || !key) return null;
  try {
    const readDb = createPublicReadSession(db);
    const row = await readDb
      .prepare("SELECT payload_json FROM public_read_snapshots WHERE key = ?")
      .bind(key)
      .first<SnapshotRow>();
    if (!row?.payload_json) return null;
    const etag = snapshotEtag(key, row.payload_json);
    if (request.headers.get("If-None-Match") === etag) {
      return withSnapshotHeader(
        new Response(null, {
          status: 304,
          headers: {
            ETag: etag,
            "X-Poll-After-Ms": String(cacheSeconds * 1000),
          },
        }),
        "hit",
      );
    }
    const response = jsonResponse(row.payload_json, cacheSeconds);
    response.headers.set("ETag", etag);
    response.headers.set("X-Poll-After-Ms", String(cacheSeconds * 1000));
    return withSnapshotHeader(response, "hit");
  } catch (error) {
    console.warn("public snapshot read failed:", error);
    return null;
  }
}

export async function readPublicSnapshotPayload<T>(
  db: D1Database,
  key: string | null,
): Promise<T | null> {
  if (!key) return null;
  try {
    const readDb = createPublicReadSession(db);
    const row = await readDb
      .prepare("SELECT payload_json FROM public_read_snapshots WHERE key = ?")
      .bind(key)
      .first<SnapshotRow>();
    if (!row?.payload_json) return null;
    return JSON.parse(row.payload_json) as T;
  } catch (error) {
    console.warn("public snapshot payload read failed:", error);
    return null;
  }
}

export function snapshotPayloadResponse(
  payload: unknown,
  cacheSeconds: number,
): Response {
  return withSnapshotHeader(jsonResponse(JSON.stringify(payload), cacheSeconds), "hit");
}

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

async function buildNewsFeedSnapshot(
  db: D1Database,
  featured: boolean,
  locale: PublicLocale,
): Promise<PublicNewsFeedResponse> {
  const filters = buildPublicNewsWhere({ featured });
  const localeJoin = publicNewsLocaleJoin(locale);
  const [result, totalResult] = await Promise.all([
    db
      .prepare(
        `SELECT ${publicNewsSelectColumnsForLocale(locale)}
         FROM events
         ${localeJoin.sql}
         ${filters.sql}
         ${publicNewsOrderBy(featured)}
         LIMIT 21`,
      )
      .bind(...localeJoin.bindings, ...filters.bindings)
      .all<NewsRow>(),
    db
      .prepare(`SELECT COUNT(*) AS total FROM events ${filters.sql}`)
      .bind(...filters.bindings)
      .first<{ total: number }>(),
  ]);
  const rows = result.results || [];
  const pageRows = rows.slice(0, PUBLIC_SNAPSHOT_PAGE_SIZE);
  return {
    items: pageRows.map((row) => rowToPublicNewsItem(row)),
    latestCursor: pageRows[0]?.event_id ?? null,
    nextCursor:
      rows.length > PUBLIC_SNAPSHOT_PAGE_SIZE
        ? (pageRows[pageRows.length - 1]?.event_id ?? null)
        : null,
    pollAfterMs: featured ? 30000 : 60000,
    hasNewer: false,
    total: totalResult?.total ?? pageRows.length,
  };
}

async function buildRegionsSnapshot(db: D1Database, includeEmpty = false): Promise<RegionListResponse> {
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
  const rows = (result.results || []).filter((row: any) => isIncluded(row, includeEmpty));
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
  return { regions };
}

async function buildFacetsSnapshot(db: D1Database): Promise<PublicFacetsResponse> {
  const [regionResult, issueResult, relatedResult] = await Promise.all([
    db
      .prepare(
        `SELECT region_id AS id, region_id AS label, COUNT(*) AS count
         FROM events
         WHERE pipeline_stage = 'drafts'
         GROUP BY region_id
         ORDER BY count DESC`,
      )
      .all<{ id: string; label: string; count: number }>(),
    db
      .prepare(
        `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
         FROM events, json_each(events.issue_tags)
         WHERE events.pipeline_stage = 'drafts'
         GROUP BY json_each.value
         ORDER BY count DESC`,
      )
      .all<{ id: string; label: string; count: number }>(),
    db
      .prepare(
        `SELECT json_each.value AS id, json_each.value AS label, COUNT(*) AS count
         FROM events, json_each(events.related_tags)
         WHERE events.pipeline_stage = 'drafts'
         GROUP BY json_each.value
         ORDER BY count DESC`,
      )
      .all<{ id: string; label: string; count: number }>(),
  ]);

  const regions: PublicFacetItem[] = (regionResult.results || []).map((row) => ({
    id: row.id,
    label: row.label,
    count: row.count,
  }));
  const issues: PublicFacetItem[] = (issueResult.results || []).map((row) => ({
    id: row.id,
    label: row.label,
    count: row.count,
  }));
  const related: PublicFacetItem[] = (relatedResult.results || []).map((row) => ({
    id: row.id,
    label: row.label,
    count: row.count,
  }));
  return { regions, issues, related };
}

async function latestPublicAt(db: D1Database): Promise<string | null> {
  const row = await db
    .prepare("SELECT MAX(published_at) AS latest_public_at FROM events WHERE pipeline_stage = 'drafts'")
    .first<{ latest_public_at: string | null }>();
  return row?.latest_public_at ?? null;
}

async function writeSnapshot(
  db: D1Database,
  key: string,
  payload: unknown,
  itemCount: number,
  sourceLatestPublicAt: string | null,
  generatedAt: string,
): Promise<void> {
  const payloadJson = JSON.stringify(payload);
  await db
    .prepare(
      `INSERT INTO public_read_snapshots
         (key, payload_json, generated_at, source_latest_public_at, item_count, payload_bytes, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
       ON CONFLICT(key) DO UPDATE SET
         payload_json=excluded.payload_json,
         generated_at=excluded.generated_at,
         source_latest_public_at=excluded.source_latest_public_at,
         item_count=excluded.item_count,
         payload_bytes=excluded.payload_bytes,
         updated_at=excluded.updated_at`,
    )
    .bind(
      key,
      payloadJson,
      generatedAt,
      sourceLatestPublicAt,
      itemCount,
      new TextEncoder().encode(payloadJson).length,
    )
    .run();
}

export async function refreshPublicReadSnapshots(db: D1Database): Promise<Record<string, unknown>> {
  const generatedAt = new Date().toISOString();
  const sourceLatestPublicAt = await latestPublicAt(db);
  const [facets, regions] = await Promise.all([
    buildFacetsSnapshot(db),
    buildRegionsSnapshot(db, false),
  ]);
  const localeResults = await Promise.all(
    SUPPORTED_PUBLIC_LOCALES.map(async (locale) => {
      const [featuredNews, allNews] = await Promise.all([
        buildNewsFeedSnapshot(db, true, locale),
        buildNewsFeedSnapshot(db, false, locale),
      ]);
      const bootstrap: PublicBootstrapResponse = {
        news: featuredNews,
        regions,
        facets,
        generatedAt,
      };
      await Promise.all([
        writeSnapshot(
          db,
          newsFeaturedSnapshotKey(locale),
          featuredNews,
          featuredNews.items.length,
          sourceLatestPublicAt,
          generatedAt,
        ),
        writeSnapshot(
          db,
          newsAllSnapshotKey(locale),
          allNews,
          allNews.items.length,
          sourceLatestPublicAt,
          generatedAt,
        ),
        writeSnapshot(
          db,
          bootstrapFeaturedSnapshotKey(locale),
          bootstrap,
          featuredNews.items.length,
          sourceLatestPublicAt,
          generatedAt,
        ),
      ]);
      return { locale, featured_items: featuredNews.items.length, all_items: allNews.items.length };
    }),
  );

  await Promise.all([
    writeSnapshot(
      db,
      FACETS_SNAPSHOT_KEY,
      facets,
      facets.regions.length + facets.issues.length + facets.related.length,
      sourceLatestPublicAt,
      generatedAt,
    ),
    writeSnapshot(
      db,
      REGIONS_ACTIVE_SNAPSHOT_KEY,
      regions,
      regions.regions.length,
      sourceLatestPublicAt,
      generatedAt,
    ),
  ]);

  return {
    status: "ok",
    generated_at: generatedAt,
    source_latest_public_at: sourceLatestPublicAt,
    snapshots: localeResults.length * 3 + 2,
    locale_results: localeResults,
    featured_items: localeResults[0]?.featured_items ?? 0,
    all_items: localeResults[0]?.all_items ?? 0,
    facets: facets.regions.length + facets.issues.length + facets.related.length,
    regions: regions.regions.length,
  };
}
