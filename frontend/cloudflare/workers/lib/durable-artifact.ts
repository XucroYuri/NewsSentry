export const IMPORT_ARTIFACT_SCHEMA_VERSION = "2026-08-02.import-artifact.v1";

const CONTENT_TYPE = "application/json";
const DEPLOY_COMMIT_RE = /^[0-9a-f]{40}$/;
const SOURCE_ENVIRONMENTS = new Set(["production", "preview", "dev"]);
const SOURCE_RUNTIMES = new Set(["cloudflare-container", "cloudflare-worker"]);

export interface ImportArtifactInput {
  batchId: string;
  jobId: string;
  task: string;
  targetIds: string[];
  sourceIds: string[];
  outputWatermark: string | null;
  generatedAt: string;
  deployCommit: string;
  sourceEnvironment: string;
  sourceRuntime: "cloudflare-container" | "cloudflare-worker" | "unknown";
  events: Array<Record<string, unknown>>;
}

export interface ImportArtifactDescriptor {
  artifactId: string;
  objectKey: string;
  sha256: string;
  payloadBytes: number;
  contentType: typeof CONTENT_TYPE;
  r2Etag: string;
  r2Version: string;
  createdAt: string;
}

interface ExistingManifest {
  artifact_id: string;
  batch_id: string;
  job_id: string;
  object_key: string;
  sha256: string;
  payload_bytes: number;
  content_type: string;
  r2_etag: string;
  r2_version: string;
  status: string;
  created_at: string;
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

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function durableError(code: string): Error {
  return Object.assign(new Error(code), { kind: "durable_storage", code });
}

function normalizedIds(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort(compareCodePoints);
}

function validateProvenance(input: ImportArtifactInput): void {
  if (
    !DEPLOY_COMMIT_RE.test(input.deployCommit) ||
    !SOURCE_ENVIRONMENTS.has(input.sourceEnvironment) ||
    !SOURCE_RUNTIMES.has(input.sourceRuntime)
  ) {
    throw durableError("durable_artifact_provenance_invalid");
  }
}

function datePath(generatedAt: string): string {
  const parsed = new Date(generatedAt);
  if (!Number.isFinite(parsed.getTime())) throw durableError("durable_artifact_generated_at_invalid");
  return [
    parsed.getUTCFullYear(),
    String(parsed.getUTCMonth() + 1).padStart(2, "0"),
    String(parsed.getUTCDate()).padStart(2, "0"),
  ].join("/");
}

function manifestMatches(
  row: ExistingManifest,
  input: ImportArtifactInput,
  artifact: ImportArtifactDescriptor,
): boolean {
  return (
    row.artifact_id === artifact.artifactId &&
    row.batch_id === input.batchId &&
    row.job_id === input.jobId &&
    row.object_key === artifact.objectKey &&
    row.sha256 === artifact.sha256 &&
    Number(row.payload_bytes) === artifact.payloadBytes &&
    row.content_type === artifact.contentType &&
    row.r2_etag === artifact.r2Etag &&
    row.r2_version === artifact.r2Version &&
    ["stored", "committed", "failed"].includes(row.status)
  );
}

async function recordStoredManifest(
  db: D1Database,
  input: ImportArtifactInput,
  artifact: ImportArtifactDescriptor,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO artifact_manifests (
         artifact_id, batch_id, job_id, object_key, sha256, payload_bytes,
         content_type, r2_etag, r2_version, status, created_at, details_json
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(artifact_id) DO UPDATE SET
         status='stored',
         error_code=NULL,
         error_message=NULL
       WHERE artifact_manifests.status IN ('stored', 'failed')`,
    )
    .bind(
      artifact.artifactId,
      input.batchId,
      input.jobId,
      artifact.objectKey,
      artifact.sha256,
      artifact.payloadBytes,
      artifact.contentType,
      artifact.r2Etag,
      artifact.r2Version,
      "stored",
      artifact.createdAt,
      canonicalJson({
        schema_version: IMPORT_ARTIFACT_SCHEMA_VERSION,
        task: input.task,
        deploy_commit: input.deployCommit,
        source_environment: input.sourceEnvironment,
        source_runtime: input.sourceRuntime,
        target_ids: normalizedIds(input.targetIds),
        source_ids: normalizedIds(input.sourceIds),
        output_watermark: input.outputWatermark,
      }),
    )
    .run();
  const existing = await db
    .prepare(
      `SELECT artifact_id, batch_id, job_id, object_key, sha256, payload_bytes,
              content_type, r2_etag, r2_version, status, created_at
       FROM artifact_manifests
       WHERE artifact_id=?`,
    )
    .bind(artifact.artifactId)
    .first<ExistingManifest>();
  if (!existing || !manifestMatches(existing, input, artifact)) {
    throw durableError("durable_artifact_manifest_mismatch");
  }
}

export interface ImportArtifactPreview {
  body: string;
  digest: ArrayBuffer;
  artifact: Omit<ImportArtifactDescriptor, "r2Etag" | "r2Version">;
}

export async function buildImportArtifactPreview(
  input: ImportArtifactInput,
): Promise<ImportArtifactPreview> {
  const body = canonicalJson({
    schema_version: IMPORT_ARTIFACT_SCHEMA_VERSION,
    batch_id: input.batchId,
    job_id: input.jobId,
    task: input.task,
    target_ids: normalizedIds(input.targetIds),
    source_ids: normalizedIds(input.sourceIds),
    output_watermark: input.outputWatermark,
    generated_at: input.generatedAt,
    events: input.events,
  });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
  const sha256 = hex(digest);
  return {
    body,
    digest,
    artifact: {
      artifactId: `artifact-${sha256}`,
      objectKey: `imports/v1/${datePath(input.generatedAt)}/${sha256}.json`,
      sha256,
      payloadBytes: utf8Bytes(body),
      contentType: CONTENT_TYPE,
      createdAt: input.generatedAt,
    },
  };
}

export async function persistImportArtifact(
  db: D1Database,
  bucket: R2Bucket | undefined,
  input: ImportArtifactInput,
): Promise<ImportArtifactDescriptor> {
  if (!bucket) throw durableError("durable_artifact_bucket_not_configured");
  validateProvenance(input);
  if (!input.batchId.trim() || !input.jobId.trim() || !input.task.trim()) {
    throw durableError("durable_artifact_identity_invalid");
  }
  const preview = await buildImportArtifactPreview(input);
  const { body, digest } = preview;
  const { artifact: previewArtifact } = preview;
  const stored = await bucket.put(previewArtifact.objectKey, body, {
    onlyIf: { etagDoesNotMatch: "*" },
    httpMetadata: { contentType: CONTENT_TYPE },
    customMetadata: {
      schema: IMPORT_ARTIFACT_SCHEMA_VERSION,
      sha256: previewArtifact.sha256,
      artifact_id: previewArtifact.artifactId,
    },
    sha256: digest,
    storageClass: "Standard",
  });
  const object = stored ?? (await bucket.head(previewArtifact.objectKey));
  if (
    !object ||
    object.key !== previewArtifact.objectKey ||
    object.size !== previewArtifact.payloadBytes ||
    object.customMetadata?.sha256 !== previewArtifact.sha256 ||
    object.customMetadata?.schema !== IMPORT_ARTIFACT_SCHEMA_VERSION ||
    object.customMetadata?.artifact_id !== previewArtifact.artifactId
  ) {
    throw durableError("durable_artifact_existing_object_mismatch");
  }
  const artifact: ImportArtifactDescriptor = {
    ...previewArtifact,
    r2Etag: object.etag,
    r2Version: object.version,
  };
  await recordStoredManifest(db, input, artifact);
  return artifact;
}

export async function markImportArtifactCommitted(
  db: D1Database,
  artifactId: string,
  finalizedAt: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE artifact_manifests
       SET status='committed', finalized_at=?, error_code=NULL, error_message=NULL
       WHERE artifact_id=? AND status IN ('stored', 'failed', 'committed')`,
    )
    .bind(finalizedAt, artifactId)
    .run();
  if (Number(result.meta?.changes || 0) !== 1) {
    throw durableError("durable_artifact_finalize_guard_failed");
  }
}

export async function markImportArtifactFailed(
  db: D1Database,
  artifactId: string,
  errorCode: string,
  errorMessage: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE artifact_manifests
       SET status='failed', error_code=?, error_message=?
       WHERE artifact_id=? AND status IN ('stored', 'failed')`,
    )
    .bind(errorCode, errorMessage.slice(0, 2000), artifactId)
    .run();
  if (Number(result.meta?.changes || 0) !== 1) {
    throw durableError("durable_artifact_failure_guard_failed");
  }
}
