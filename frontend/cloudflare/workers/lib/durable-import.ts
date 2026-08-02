import type { ImportStagingEvent, ImportStagingResult } from "./import-staging.ts";
import { stageImportBatch } from "./import-staging.ts";
import {
  IMPORT_ARTIFACT_SCHEMA_VERSION,
  buildImportArtifactPreview,
  persistImportArtifact,
  markImportArtifactFailed,
  type ImportArtifactInput,
  type ImportArtifactPreview,
} from "./durable-artifact.ts";
import { refreshPublicReadSnapshots } from "./public-read-snapshots.ts";
import { validateExternalUrl } from "./external-url.ts";
import { COLLECTED_AT_FUTURE_TOLERANCE_MS } from "./timestamp-policy.ts";

export const MAX_IMPORT_EVENTS = 500;
export const MAX_IMPORT_BODY_BYTES = 8 * 1024 * 1024;
export const MAX_IDEMPOTENCY_KEY_BYTES = 512;
const IDEMPOTENCY_BINDING_SCHEMA_VERSION = "2026-08-02.projection-idempotency.v1";

export type DurableProjectionOrigin = "api-import" | "container-import";

export interface DurableProjectionImportEnv {
  DB: D1Database;
  NEWS_SENTRY_ARTIFACTS?: R2Bucket;
}

export interface DurableProjectionImportInput {
  origin: DurableProjectionOrigin;
  events: Array<Record<string, unknown>>;
  idempotencyKey: string | null;
}

export interface DurableProjectionImportResult extends ImportStagingResult {
  jobId: string;
  artifactId: string;
  artifactKey: string;
  artifactSha256: string;
  artifactBytes: number;
  replayed: boolean;
  generatedAt: string;
}

interface DurableProjectionIdentity {
  origin: DurableProjectionOrigin;
  payloadSha256: string;
  batchId: string;
  jobId: string;
  generatedAt: string;
  events: ImportStagingEvent[];
  idempotencyKeyHash: string | null;
}

interface ExistingProjectionReceipt {
  batch_id: string;
  job_id: string;
  batch_checksum: string;
  finalized_at: string;
  request_idempotency_key_hash: string | null;
  imported_count: number;
  updated_count: number;
  valid_count: number;
  quarantined_count: number;
  expected_chunks: number;
  committed_chunks: number;
  artifact_id: string;
  object_key: string;
  sha256: string;
  payload_bytes: number;
}

interface DurableProjectionPreparedArtifact {
  input: ImportArtifactInput;
  preview: ImportArtifactPreview;
}

export function durableProjectionImportError(
  kind: "validation" | "payload_too_large" | "idempotency_conflict" | "durable_storage",
  code: string,
): Error {
  return Object.assign(new Error(code), { kind, code });
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftPoints[index].codePointAt(0)! - rightPoints[index].codePointAt(0)!;
    if (difference !== 0) return difference;
  }
  return leftPoints.length - rightPoints.length;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => compareCodePoints(left, right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).length;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function requiredString(event: Record<string, unknown>, key: string): string | null {
  const value = event[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function parseTimestamp(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function compareIdentityEvent(left: ImportStagingEvent, right: ImportStagingEvent): number {
  for (const key of ["target_id", "source_id", "url", "title_original", "collected_at", "event_id"] as const) {
    const comparison = compareCodePoints(String(left[key] ?? ""), String(right[key] ?? ""));
    if (comparison !== 0) return comparison;
  }
  return 0;
}

function normalizeOriginPrefix(origin: DurableProjectionOrigin): "api" | "container" {
  return origin === "api-import" ? "api" : "container";
}

function validateEventEnvelope(events: Array<Record<string, unknown>>): void {
  if (!Array.isArray(events)) {
    throw durableProjectionImportError("validation", "import_events_not_array");
  }
  if (events.length === 0) {
    throw durableProjectionImportError("validation", "import_events_empty");
  }
  if (events.length > MAX_IMPORT_EVENTS) {
    throw durableProjectionImportError("payload_too_large", "import_events_too_many");
  }
  const bytes = utf8Bytes(canonicalJson(events));
  if (bytes > MAX_IMPORT_BODY_BYTES) {
    throw durableProjectionImportError("payload_too_large", "import_body_too_large");
  }
  for (const [index, event] of events.entries()) {
    for (const field of [
      "target_id",
      "source_id",
      "title_original",
      "url",
      "collected_at",
      "pipeline_stage",
    ]) {
      if (!requiredString(event, field)) {
        throw durableProjectionImportError(
          "validation",
          `item_${index}_missing_required_import_fields`,
        );
      }
    }
    const urlResult = validateExternalUrl(event.url);
    if (!urlResult.ok) {
      throw durableProjectionImportError("validation", `item_${index}_${urlResult.reason}`);
    }
  }
}

async function buildDurableProjectionIdentity(
  input: DurableProjectionImportInput,
): Promise<DurableProjectionIdentity> {
  validateEventEnvelope(input.events);
  if (input.idempotencyKey !== null && utf8Bytes(input.idempotencyKey) > MAX_IDEMPOTENCY_KEY_BYTES) {
    throw durableProjectionImportError("payload_too_large", "idempotency_key_too_large");
  }
  const nowMs = Date.now();
  const normalized: ImportStagingEvent[] = [];
  const generatedAtCandidates: number[] = [];
  for (const [index, raw] of input.events.entries()) {
    const urlResult = validateExternalUrl(raw.url);
    if (!urlResult.ok) {
      throw durableProjectionImportError("validation", `item_${index}_${urlResult.reason}`);
    }
    const collectedMs = parseTimestamp(raw.collected_at);
    const publishedMs = parseTimestamp(raw.published_at);
    if (
      collectedMs !== null &&
      collectedMs <= nowMs + COLLECTED_AT_FUTURE_TOLERANCE_MS
    ) {
      generatedAtCandidates.push(collectedMs);
    }
    const event = {
      ...raw,
      url: urlResult.normalizedUrl,
    } as ImportStagingEvent;
    if (collectedMs !== null) {
      event.collected_at = new Date(collectedMs).toISOString();
    }
    if (publishedMs !== null) {
      event.published_at = new Date(publishedMs).toISOString();
    } else if (!requiredString(raw, "published_at") && collectedMs !== null) {
      event.published_at = new Date(collectedMs).toISOString();
    }
    normalized.push(event);
  }
  if (generatedAtCandidates.length === 0) {
    throw durableProjectionImportError("validation", "all_event_timestamps_invalid");
  }
  normalized.sort(compareIdentityEvent);
  const payloadSha256 = await sha256Hex(canonicalJson(normalized));
  const prefix = normalizeOriginPrefix(input.origin);
  return {
    origin: input.origin,
    payloadSha256,
    batchId: `${prefix}-batch:${payloadSha256}`,
    jobId: `${prefix}-job:${payloadSha256}`,
    generatedAt: new Date(Math.max(...generatedAtCandidates)).toISOString(),
    events: normalized,
    idempotencyKeyHash:
      input.idempotencyKey === null ? null : await sha256Hex(input.idempotencyKey),
  };
}

async function loadProjectionReceiptByPayloadOrIdempotencyKey(
  db: D1Database,
  identity: DurableProjectionIdentity,
): Promise<ExistingProjectionReceipt | null> {
  const receipt = await db
    .prepare(
      `SELECT
         receipt.batch_id, receipt.job_id, receipt.batch_checksum, receipt.finalized_at,
         receipt.request_idempotency_key_hash,
         batch.imported_count, batch.updated_count, batch.valid_count,
         batch.quarantined_count, batch.expected_chunks, batch.committed_chunks,
         artifact.artifact_id, artifact.object_key, artifact.sha256, artifact.payload_bytes
       FROM import_projection_finalize_receipts AS receipt
       JOIN import_batches AS batch ON batch.batch_id = receipt.batch_id
       JOIN artifact_manifests AS artifact ON artifact.artifact_id = receipt.artifact_id
       WHERE receipt.batch_id = ?
          OR (? IS NOT NULL AND receipt.request_idempotency_key_hash = ?)
       ORDER BY CASE WHEN receipt.batch_id = ? THEN 0 ELSE 1 END
       LIMIT 1`,
    )
    .bind(
      identity.batchId,
      identity.idempotencyKeyHash,
      identity.idempotencyKeyHash,
      identity.batchId,
    )
    .first<ExistingProjectionReceipt>();
  if (
    receipt &&
    receipt.batch_id !== identity.batchId &&
    receipt.request_idempotency_key_hash === identity.idempotencyKeyHash
  ) {
    throw durableProjectionImportError("idempotency_conflict", "idempotency_key_payload_conflict");
  }
  return receipt ?? null;
}

function replayResult(
  receipt: ExistingProjectionReceipt,
  identity: DurableProjectionIdentity,
): DurableProjectionImportResult {
  return {
    status: "committed",
    batchId: receipt.batch_id,
    checksum: receipt.batch_checksum,
    totalChunks: Number(receipt.expected_chunks),
    committedChunks: Number(receipt.committed_chunks),
    replayedChunks: Number(receipt.committed_chunks),
    validEvents: Number(receipt.imported_count) + Number(receipt.updated_count),
    quarantinedEvents: Number(receipt.quarantined_count),
    importedEvents: Number(receipt.imported_count),
    updatedEvents: Number(receipt.updated_count),
    jobId: receipt.job_id,
    artifactId: receipt.artifact_id,
    artifactKey: receipt.object_key,
    artifactSha256: receipt.sha256,
    artifactBytes: Number(receipt.payload_bytes),
    replayed: true,
    generatedAt: identity.generatedAt,
  };
}

async function ensureProjectionJob(
  db: D1Database,
  identity: DurableProjectionIdentity,
  origin: DurableProjectionOrigin,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO jobs (
         job_id, idempotency_key, job_type, target_id, source_id,
         capability, scheduled_for, scheduled_window, status
       ) VALUES (?, ?, 'projection-import', 'multi', 'multi', ?, ?, ?, 'running')
       ON CONFLICT(job_id) DO UPDATE SET
         status='running',
         last_error_code=NULL,
         last_error_message=NULL,
         updated_at=datetime('now')
       WHERE jobs.status IN ('running', 'committed', 'snapshot_pending')`,
    )
    .bind(
      identity.jobId,
      `projection:${identity.jobId}`,
      origin,
      identity.generatedAt,
      identity.generatedAt.slice(0, 13).replace(/[-:T]/g, ""),
    )
    .run();
}

function idempotencyBindingKey(identity: DurableProjectionIdentity): string {
  return `imports/idempotency/v1/${identity.idempotencyKeyHash}.json`;
}

function idempotencyBindingMetadata(
  identity: DurableProjectionIdentity,
  preparedArtifact: DurableProjectionPreparedArtifact,
): Record<string, string> {
  return {
    schema: IDEMPOTENCY_BINDING_SCHEMA_VERSION,
    origin: identity.origin,
    idempotency_key_hash: identity.idempotencyKeyHash ?? "",
    payload_sha256: identity.payloadSha256,
    batch_id: identity.batchId,
    job_id: identity.jobId,
    artifact_id: preparedArtifact.preview.artifact.artifactId,
    artifact_key: preparedArtifact.preview.artifact.objectKey,
    artifact_sha256: preparedArtifact.preview.artifact.sha256,
  };
}

function idempotencyBindingMatches(
  metadata: Record<string, string> | undefined,
  identity: DurableProjectionIdentity,
  preparedArtifact: DurableProjectionPreparedArtifact,
): boolean {
  const expected = idempotencyBindingMetadata(identity, preparedArtifact);
  return Object.entries(expected).every(([key, value]) => metadata?.[key] === value);
}

async function bindRequestIdempotencyKey(
  bucket: R2Bucket | undefined,
  identity: DurableProjectionIdentity,
  preparedArtifact: DurableProjectionPreparedArtifact,
): Promise<void> {
  if (!identity.idempotencyKeyHash) return;
  if (!bucket) {
    throw durableProjectionImportError("durable_storage", "durable_artifact_bucket_not_configured");
  }
  const key = idempotencyBindingKey(identity);
  const metadata = idempotencyBindingMetadata(identity, preparedArtifact);
  const body = canonicalJson({
    schema_version: IDEMPOTENCY_BINDING_SCHEMA_VERSION,
    ...metadata,
  });
  const stored = await bucket.put(key, body, {
    onlyIf: { etagDoesNotMatch: "*" },
    httpMetadata: { contentType: "application/json" },
    customMetadata: metadata,
    storageClass: "Standard",
  });
  if (stored) return;
  const existing = await bucket.head(key);
  if (!existing || existing.key !== key || existing.customMetadata?.schema !== IDEMPOTENCY_BINDING_SCHEMA_VERSION) {
    throw durableProjectionImportError("durable_storage", "durable_idempotency_binding_mismatch");
  }
  if (!idempotencyBindingMatches(existing.customMetadata, identity, preparedArtifact)) {
    throw durableProjectionImportError("idempotency_conflict", "idempotency_key_payload_conflict");
  }
}

async function markSnapshotPending(db: D1Database, jobId: string, message: string): Promise<void> {
  await db
    .prepare(
      `UPDATE jobs
       SET status='snapshot_pending',
           last_error_code='snapshot_refresh_failed',
           last_error_message=?,
           updated_at=datetime('now')
       WHERE job_id=? AND status IN ('committed', 'snapshot_pending')`,
    )
    .bind(message.slice(0, 2000), jobId)
    .run();
}

async function markSnapshotReady(db: D1Database, jobId: string): Promise<void> {
  await db
    .prepare(
      `UPDATE jobs
       SET status='committed',
           last_error_code=NULL,
           last_error_message=NULL,
           updated_at=datetime('now')
       WHERE job_id=? AND status IN ('committed', 'snapshot_pending')`,
    )
    .bind(jobId)
    .run();
}

async function refreshSnapshotsForProjection(db: D1Database, jobId: string): Promise<void> {
  try {
    await refreshPublicReadSnapshots(db);
    await markSnapshotReady(db, jobId);
  } catch (error) {
    await markSnapshotPending(db, jobId, error instanceof Error ? error.message : String(error));
  }
}

async function verifyCommittedArtifactHead(
  bucket: R2Bucket | undefined,
  receipt: ExistingProjectionReceipt,
): Promise<void> {
  if (!bucket) {
    throw durableProjectionImportError("durable_storage", "durable_artifact_bucket_not_configured");
  }
  const object = await bucket.head(receipt.object_key);
  if (
    !object ||
    object.key !== receipt.object_key ||
    object.size !== Number(receipt.payload_bytes) ||
    object.customMetadata?.sha256 !== receipt.sha256 ||
    object.customMetadata?.schema !== IMPORT_ARTIFACT_SCHEMA_VERSION ||
    object.customMetadata?.artifact_id !== receipt.artifact_id
  ) {
    throw durableProjectionImportError("durable_storage", "durable_artifact_existing_object_mismatch");
  }
}

async function prepareArtifact(
  identity: DurableProjectionIdentity,
  input: DurableProjectionImportInput,
): Promise<DurableProjectionPreparedArtifact> {
  const artifactInput = {
    batchId: identity.batchId,
    jobId: identity.jobId,
    task: input.origin,
    targetIds: identity.events.map((event) => String(event.target_id)),
    sourceIds: identity.events.map((event) => String(event.source_id)),
    outputWatermark: null,
    generatedAt: identity.generatedAt,
    events: identity.events,
  };
  return {
    input: artifactInput,
    preview: await buildImportArtifactPreview(artifactInput),
  };
}

export async function executeDurableProjectionImport(
  env: DurableProjectionImportEnv,
  input: DurableProjectionImportInput,
): Promise<DurableProjectionImportResult> {
  const identity = await buildDurableProjectionIdentity(input);
  const preparedArtifact = await prepareArtifact(identity, input);
  const existing = await loadProjectionReceiptByPayloadOrIdempotencyKey(env.DB, identity);
  if (existing) {
    await verifyCommittedArtifactHead(env.NEWS_SENTRY_ARTIFACTS, existing);
    await bindRequestIdempotencyKey(env.NEWS_SENTRY_ARTIFACTS, identity, preparedArtifact);
    await refreshSnapshotsForProjection(env.DB, existing.job_id);
    return replayResult(existing, identity);
  }
  await bindRequestIdempotencyKey(env.NEWS_SENTRY_ARTIFACTS, identity, preparedArtifact);
  const artifact = await persistImportArtifact(env.DB, env.NEWS_SENTRY_ARTIFACTS, preparedArtifact.input);
  await ensureProjectionJob(env.DB, identity, input.origin);
  let staged: ImportStagingResult;
  try {
    staged = await stageImportBatch(env.DB, {
      batchId: identity.batchId,
      jobId: identity.jobId,
      targetId: "multi",
      sourceId: "multi",
      outputWatermark: null,
      events: identity.events,
      generatedAt: identity.generatedAt,
      artifact,
      finalize: {
        mode: "projection-only",
        origin: input.origin,
        requestIdempotencyKeyHash: identity.idempotencyKeyHash,
      },
    });
  } catch (error) {
    try {
      await markImportArtifactFailed(
        env.DB,
        artifact.artifactId,
        "projection_import_failed",
        error instanceof Error ? error.message : String(error),
      );
    } catch (manifestError) {
      console.error("failed to record durable projection import failure:", manifestError);
    }
    throw error;
  }
  await refreshSnapshotsForProjection(env.DB, identity.jobId);
  return {
    ...staged,
    jobId: identity.jobId,
    artifactId: artifact.artifactId,
    artifactKey: artifact.objectKey,
    artifactSha256: artifact.sha256,
    artifactBytes: artifact.payloadBytes,
    replayed: false,
    generatedAt: identity.generatedAt,
  };
}
