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

function extractContainerImportEvents(details: Record<string, unknown>): ImportEventItem[] {
  const body = details.body;
  if (!isRecord(body) || !Array.isArray(body.import_events)) return [];
  return body.import_events.filter(isRecord) as ImportEventItem[];
}

export async function importContainerEventsToD1(
  env: ContainerImportEnv,
  details: Record<string, unknown>,
  _runId: string,
  _generatedAt: string,
  _task: ContainerImportTask,
): Promise<Record<string, unknown>> {
  const events = extractContainerImportEvents(details);
  if (events.length === 0) {
    return { received: 0, imported: 0, updated: 0, skipped: 0, errors: [] };
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
