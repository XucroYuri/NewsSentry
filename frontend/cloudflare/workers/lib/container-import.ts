import { importEventsToD1 } from "../api/webhook.ts";
import type { ImportEventItem } from "./contracts.ts";
import {
  markImportArtifactCommitted,
  markImportArtifactFailed,
  persistImportArtifact,
} from "./durable-artifact.ts";

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

function validateRequiredImportFields(events: ImportEventItem[]): string[] {
  const errors: string[] = [];
  for (const [index, event] of events.entries()) {
    if (
      !event.target_id ||
      !event.source_id ||
      !event.title_original ||
      !event.url ||
      !event.collected_at
    ) {
      errors.push(`item ${index}: missing required import fields`);
    }
  }
  return errors;
}

export async function importContainerEventsToD1(
  env: ContainerImportEnv,
  details: Record<string, unknown>,
  runId: string,
  generatedAt: string,
  task: ContainerImportTask,
): Promise<Record<string, unknown>> {
  const events = extractContainerImportEvents(details);
  if (events.length === 0) {
    return { received: 0, imported: 0, updated: 0, skipped: 0, errors: [] };
  }
  const artifact = await persistImportArtifact(env.DB, env.NEWS_SENTRY_ARTIFACTS, {
    batchId: `container-batch:${runId}`,
    jobId: `container-job:${runId}`,
    task,
    targetIds: events.map((event) => String(event.target_id || "")),
    sourceIds: events.map((event) => String(event.source_id || "")),
    outputWatermark: null,
    generatedAt,
    events,
  });
  // The legacy webhook importer is intentionally item-oriented. Durable
  // Container batches must reject all hard validation errors before it can
  // mutate any public D1 projection.
  const validationErrors = validateRequiredImportFields(events);
  if (validationErrors.length > 0) {
    await markImportArtifactFailed(
      env.DB,
      artifact.artifactId,
      "d1_import_validation_failed",
      validationErrors.slice(0, 10).join("; "),
    );
    throw Object.assign(
      new Error(`container D1 import rejected ${validationErrors.length} events`),
      {
        kind: "validation",
        code: "container_d1_import_validation_failed",
      },
    );
  }
  let result: Awaited<ReturnType<typeof importEventsToD1>>;
  try {
    result = await importEventsToD1(env.DB, events);
  } catch (error) {
    try {
      await markImportArtifactFailed(
        env.DB,
        artifact.artifactId,
        "d1_import_exception",
        error instanceof Error ? error.message : String(error),
      );
    } catch (manifestError) {
      console.error("failed to record durable artifact import failure:", manifestError);
    }
    throw error;
  }
  if (result.errors.length > 0) {
    await markImportArtifactFailed(
      env.DB,
      artifact.artifactId,
      "d1_import_validation_failed",
      result.errors.slice(0, 10).join("; "),
    );
    throw Object.assign(new Error(`container D1 import rejected ${result.errors.length} events`), {
      kind: "validation",
      code: "container_d1_import_validation_failed",
    });
  }
  await markImportArtifactCommitted(env.DB, artifact.artifactId, generatedAt);
  return {
    received: events.length,
    imported: result.imported,
    updated: result.updated,
    skipped: result.skipped,
    errors: result.errors.slice(0, 10),
    artifact_id: artifact.artifactId,
    artifact_key: artifact.objectKey,
    artifact_sha256: artifact.sha256,
    artifact_bytes: artifact.payloadBytes,
  };
}
