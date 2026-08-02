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

function extractContainerImportEvents(details: Record<string, unknown>): {
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

function validateCollectTargetResults(
  summary: Record<string, unknown>,
  importEvents: unknown[],
): void {
  const targetResults = summary.target_results;
  const attempted = parseNonNegativeInteger(summary.targets_attempted);
  const succeeded = parseNonNegativeInteger(summary.targets_succeeded);
  const failed = parseNonNegativeInteger(summary.targets_failed);
  if (!Array.isArray(targetResults) || attempted === null || succeeded === null || failed === null) {
    throw new Error("container_target_results_missing");
  }
  if (attempted !== targetResults.length || succeeded + failed !== attempted) {
    throw new Error("container_target_results_mismatch");
  }

  let actualSucceeded = 0;
  let actualFailed = 0;
  let targetImportCount = 0;
  const declaredTargetCounts = new Map<string, number>();
  const failedTargets: string[] = [];
  for (const item of targetResults) {
    if (!isRecord(item)) throw new Error("container_target_results_mismatch");
    const targetId = String(item.target_id ?? "").trim();
    const status = String(item.status ?? "").trim();
    if (!targetId || !status) {
      throw new Error("container_target_results_mismatch");
    }
    if (status !== "ok" && status !== "empty_no_new_items" && status !== "error") {
      throw new Error("container_target_results_mismatch");
    }
    if (declaredTargetCounts.has(targetId)) {
      throw new Error("container_target_results_mismatch");
    }
    const eventsCollected = parseNonNegativeInteger(
      status === "error" ? item.events_collected ?? 0 : item.events_collected,
    );
    const importCount = parseNonNegativeInteger(
      status === "error" ? item.import_events_count ?? 0 : item.import_events_count,
    );
    if (status !== "error" && (eventsCollected === null || importCount === null)) {
      throw new Error("container_target_results_mismatch");
    }
    if (
      status === "empty_no_new_items" &&
      ((eventsCollected ?? 0) !== 0 || (importCount ?? 0) !== 0)
    ) {
      throw new Error("container_target_results_mismatch");
    }
    targetImportCount += importCount ?? 0;
    declaredTargetCounts.set(targetId, importCount ?? 0);
    if (status === "error") {
      actualFailed += 1;
      failedTargets.push(`${targetId}:${String(item.reason ?? "collection_failed")}`);
    } else {
      actualSucceeded += 1;
    }
  }
  if (actualSucceeded !== succeeded || actualFailed !== failed) {
    throw new Error("container_target_results_mismatch");
  }
  const declared = parseNonNegativeInteger(summary.import_events_count ?? 0);
  if (declared !== null && targetImportCount !== declared) {
    throw new Error("container_target_results_mismatch");
  }
  if (failedTargets.length > 0) {
    throw new Error(`container_target_failures:${failedTargets.join(",")}`);
  }

  const actualTargetCounts = new Map<string, number>();
  for (const event of importEvents) {
    if (!isRecord(event)) throw new Error("container_target_results_mismatch");
    const targetId = String(event.target_id ?? "").trim();
    if (!targetId || !declaredTargetCounts.has(targetId)) {
      throw new Error("container_target_results_mismatch");
    }
    actualTargetCounts.set(targetId, (actualTargetCounts.get(targetId) ?? 0) + 1);
  }
  for (const [targetId, declaredCount] of declaredTargetCounts) {
    if ((actualTargetCounts.get(targetId) ?? 0) !== declaredCount) {
      throw new Error("container_target_results_mismatch");
    }
  }
}

export async function importContainerEventsToD1(
  env: ContainerImportEnv,
  details: Record<string, unknown>,
  _runId: string,
  _generatedAt: string,
  _task: ContainerImportTask,
): Promise<Record<string, unknown>> {
  const payload = extractContainerImportEvents(details);
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
  if (_task === "collect-cycle") {
    validateCollectTargetResults(payload.summary, payload.importEvents);
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
