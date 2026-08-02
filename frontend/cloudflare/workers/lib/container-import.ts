import type { ImportEventItem } from "./contracts.ts";
import { executeDurableProjectionImport } from "./durable-import.ts";

export interface ContainerImportEnv {
  DB: D1Database;
  NEWS_SENTRY_ARTIFACTS?: R2Bucket;
}

type ContainerImportTask = "collect-cycle" | "public-translation-cycle";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractContainerImportPayload(details: Record<string, unknown>): {
  summary: Record<string, unknown>;
  importEvents: unknown[];
} {
  const body = details.body;
  if (!isRecord(body)) return { summary: {}, importEvents: [] };
  return {
    summary: isRecord(body.summary) ? body.summary : {},
    importEvents: Array.isArray(body.import_events) ? body.import_events : [],
  };
}

function parseNonNegativeInteger(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

export async function importContainerEventsToD1(
  env: ContainerImportEnv,
  details: Record<string, unknown>,
  _runId: string,
  _generatedAt: string,
  _task: ContainerImportTask,
): Promise<Record<string, unknown>> {
  const payload = extractContainerImportPayload(details);
  const collected = parseNonNegativeInteger(payload.summary.events_collected ?? 0);
  const declared = parseNonNegativeInteger(
    payload.summary.import_events_count ?? payload.importEvents.length,
  );
  if (
    collected === null ||
    declared === null ||
    declared !== payload.importEvents.length
  ) {
    throw new Error("container_import_count_mismatch:declared_vs_actual");
  }
  if (collected > 0 && declared === 0) {
    throw new Error("container_import_count_mismatch:collected_without_import_events");
  }
  const events = payload.importEvents.filter(isRecord) as ImportEventItem[];
  if (events.length !== payload.importEvents.length) {
    throw new Error("container_import_count_mismatch:declared_vs_actual");
  }
  if (events.length === 0) {
    return { status: "empty_no_new_items", imported: 0, updated: 0, quarantined: 0, errors: [] };
  }
  const result = await executeDurableProjectionImport(env, {
    origin: "container-import",
    events,
    idempotencyKey: null,
  });
  return {
    received: events.length,
    imported: result.importedEvents,
    updated: result.updatedEvents,
    skipped: 0,
    errors: [],
    batch_id: result.batchId,
    job_id: result.jobId,
    artifact_id: result.artifactId,
    artifact_key: result.artifactKey,
    artifact_sha256: result.artifactSha256,
    artifact_bytes: result.artifactBytes,
    replayed: result.replayed,
  };
}
