import {
  createDlqReplayJob,
  loadJobForDlqReplay,
} from "../lib/job-store.ts";
import type { RuntimeMetadata } from "../lib/router";

const ALLOWED_REPLAY_REASONS = new Set([
  "upstream_fixed",
  "parser_fixed",
  "transient_d1_recovered",
  "operator_verified",
]);

interface ReplayPayload {
  job_id?: unknown;
  operator?: unknown;
  reason?: unknown;
  version?: unknown;
}

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

function isSafeToken(value: string, maxLength: number): boolean {
  return value.length > 0 && value.length <= maxLength && /^[A-Za-z0-9._:-]+$/.test(value);
}

function validateReplayPayload(payload: ReplayPayload): {
  ok: true;
  jobId: string;
  operatorId: string | null;
  reason: string;
  requestedVersion: string;
} | {
  ok: false;
  detail: string;
} {
  const jobId = typeof payload.job_id === "string" ? payload.job_id.trim() : "";
  const operatorId = typeof payload.operator === "string" ? payload.operator.trim() : "";
  const reason = typeof payload.reason === "string" ? payload.reason.trim() : "";
  const requestedVersion = typeof payload.version === "string" ? payload.version.trim() : "";

  if (!isSafeToken(jobId, 128)) {
    return { ok: false, detail: "valid job_id is required" };
  }
  if (
    operatorId &&
    (operatorId.length > 254 || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(operatorId))
  ) {
    return { ok: false, detail: "valid operator is required" };
  }
  if (!ALLOWED_REPLAY_REASONS.has(reason)) {
    return { ok: false, detail: "valid reason is required" };
  }
  if (!/^20\d{2}-\d{2}-\d{2}\.[A-Za-z0-9._:-]+$/.test(requestedVersion)) {
    return { ok: false, detail: "valid version is required" };
  }
  return { ok: true, jobId, operatorId, reason, requestedVersion };
}

async function requestJson(request: Request): Promise<ReplayPayload | null> {
  try {
    const parsed = await request.json();
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    return parsed as ReplayPayload;
  } catch {
    return null;
  }
}

export async function handleDlqReplay(
  request: Request,
  db: D1Database,
  _params: URLSearchParams,
  _segments: string[],
  _ctx?: ExecutionContext,
  runtimeMetadata?: RuntimeMetadata,
): Promise<Response> {
  const payload = await requestJson(request);
  if (!payload) {
    return jsonResponse({ detail: "JSON object body is required" }, 400);
  }

  const validation = validateReplayPayload(payload);
  if (!validation.ok) {
    return jsonResponse({ detail: validation.detail }, 400);
  }
  const accessEmail = runtimeMetadata?.access?.email ?? null;
  if (!accessEmail) {
    return jsonResponse({ detail: "verified Access identity is required" }, 403);
  }
  if (validation.operatorId && validation.operatorId !== accessEmail) {
    return jsonResponse({ detail: "operator must match verified Access identity" }, 403);
  }

  const originalJob = await loadJobForDlqReplay(db, validation.jobId);
  if (!originalJob) {
    return jsonResponse({ detail: "dead-lettered job not found" }, 404);
  }
  if (originalJob.status !== "dead_lettered") {
    return jsonResponse({ detail: "job is not dead-lettered" }, 409);
  }

  const generatedAt = new Date().toISOString();
  const replay = await createDlqReplayJob(db, originalJob, {
    originalJobId: originalJob.job_id,
    operatorId: accessEmail,
    reason: validation.reason,
    requestedVersion: validation.requestedVersion,
    workerVersion: runtimeMetadata?.worker_version ?? null,
    deployCommit: runtimeMetadata?.commit ?? null,
    generatedAt,
  });

  return jsonResponse({
    status: "queued",
    original_job_id: replay.original_job_id,
    new_job_id: replay.new_job_id,
    receipt_id: replay.receipt_id,
    generated_at: generatedAt,
  }, 201);
}
