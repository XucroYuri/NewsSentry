export type JobStatus =
  | "pending"
  | "enqueued"
  | "leased"
  | "running"
  | "importing"
  | "committed"
  | "snapshot_pending"
  | "retry_scheduled"
  | "succeeded"
  | "cancelled"
  | "dead_lettered";

export const TERMINAL_JOB_STATUSES = new Set<JobStatus>([
  "succeeded",
  "cancelled",
  "dead_lettered",
]);

const ALLOWED_TRANSITIONS: Record<JobStatus, ReadonlySet<JobStatus>> = {
  pending: new Set(["enqueued", "cancelled"]),
  enqueued: new Set(["leased", "retry_scheduled", "cancelled", "dead_lettered"]),
  leased: new Set(["running", "retry_scheduled", "cancelled", "dead_lettered"]),
  running: new Set(["importing", "retry_scheduled", "cancelled", "dead_lettered"]),
  importing: new Set(["committed", "retry_scheduled", "cancelled", "dead_lettered"]),
  committed: new Set(["snapshot_pending"]),
  snapshot_pending: new Set(["succeeded"]),
  retry_scheduled: new Set(["enqueued", "cancelled", "dead_lettered"]),
  succeeded: new Set(),
  cancelled: new Set(),
  dead_lettered: new Set(),
};

export interface JobIdentityInput {
  job_type: string;
  target_id: string;
  source_id: string | null;
  scheduled_window: string;
  input_cursor: string | null;
  config_version: string;
}

export interface TransitionDecision {
  ok: boolean;
  reason?: "same_status" | "terminal_status" | "illegal_transition";
}

export interface RetryClassification {
  retryable: boolean;
  category:
    | "rate_limited"
    | "server_error"
    | "network"
    | "d1"
    | "container_startup"
    | "timeout"
    | "validation"
    | "security"
    | "permanent_client_error"
    | "unknown_permanent";
}

export interface JobErrorLike {
  status?: number;
  code?: string;
  message?: string;
  name?: string;
  kind?: string;
}

export interface BackoffInput {
  attempt: number;
  retryAfter?: string | number | null;
  nowMs?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

export interface LeaseState {
  lease_owner: string | null;
  lease_token: string | null;
  lease_until: string | null;
  fencing_version: number;
}

export interface LeaseClaimInput extends LeaseState {
  nowMs: number;
  requestedOwner: string;
}

export type LeaseClaimDecision =
  | {
      ok: true;
      action: "claim" | "takeover";
      lease_owner: string;
      lease_token: string;
      fencing_version: number;
      previous_lease_token: string | null;
    }
  | {
      ok: false;
      action: "reject";
      reason: "lease_not_expired";
      current_lease_owner: string | null;
      current_lease_token: string | null;
      fencing_version: number;
    };

export function isTerminalJobStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

export function canTransitionJobStatus(from: JobStatus, to: JobStatus): TransitionDecision {
  if (from === to) {
    return { ok: true, reason: "same_status" };
  }
  if (isTerminalJobStatus(from)) {
    return { ok: false, reason: "terminal_status" };
  }
  if (!ALLOWED_TRANSITIONS[from].has(to)) {
    return { ok: false, reason: "illegal_transition" };
  }
  return { ok: true };
}

export function canonicalJobIdentity(input: JobIdentityInput): string {
  return JSON.stringify({
    config_version: input.config_version,
    input_cursor: input.input_cursor,
    job_type: input.job_type,
    scheduled_window: input.scheduled_window,
    source_id: input.source_id,
    target_id: input.target_id,
  });
}

export async function stableJobId(input: JobIdentityInput): Promise<string> {
  const encoded = new TextEncoder().encode(canonicalJobIdentity(input));
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function classifyJobError(error: JobErrorLike): RetryClassification {
  const status = Number.isFinite(error.status) ? Number(error.status) : undefined;
  const normalized = `${error.kind ?? ""} ${error.code ?? ""} ${error.name ?? ""} ${
    error.message ?? ""
  }`.toLowerCase();

  if (status === 429) {
    return { retryable: true, category: "rate_limited" };
  }
  if (typeof status === "number" && status >= 500 && status <= 599) {
    return { retryable: true, category: "server_error" };
  }
  if (typeof status === "number" && status >= 400 && status <= 499) {
    if (status === 400 || status === 401 || status === 403 || status === 422) {
      return {
        retryable: false,
        category: status === 401 || status === 403 ? "security" : "validation",
      };
    }
    return { retryable: false, category: "permanent_client_error" };
  }
  if (/(network|econnreset|enotfound|etimedout|fetch failed|socket)/.test(normalized)) {
    return { retryable: true, category: "network" };
  }
  if (/(d1|database|sqlite|storage)/.test(normalized)) {
    return { retryable: true, category: "d1" };
  }
  if (/(container.*startup|startup.*container|cold start|container initializing)/.test(normalized)) {
    return { retryable: true, category: "container_startup" };
  }
  if (/(timeout|timed out|deadline|aborterror)/.test(normalized)) {
    return { retryable: true, category: "timeout" };
  }
  if (/(validation|invalid payload|schema|unsafe url|future timestamp)/.test(normalized)) {
    return { retryable: false, category: "validation" };
  }
  if (/(security|forbidden|unauthorized|access jwt|signature|audience|issuer)/.test(normalized)) {
    return { retryable: false, category: "security" };
  }
  return { retryable: false, category: "unknown_permanent" };
}

export function computeRetryDelayMs(input: BackoffInput): number {
  const nowMs = input.nowMs ?? Date.now();
  const retryAfterDelay = parseRetryAfterMs(input.retryAfter, nowMs);
  if (retryAfterDelay !== null) {
    return Math.max(0, retryAfterDelay);
  }

  const attempt = Math.max(0, Math.floor(input.attempt));
  const baseDelayMs = input.baseDelayMs ?? 30_000;
  const maxDelayMs = input.maxDelayMs ?? 30 * 60_000;
  const exponentialDelay = baseDelayMs * 2 ** attempt;
  return Math.min(maxDelayMs, exponentialDelay);
}

export function parseRetryAfterMs(retryAfter: string | number | null | undefined, nowMs: number): number | null {
  if (retryAfter === null || retryAfter === undefined || retryAfter === "") {
    return null;
  }
  if (typeof retryAfter === "number" && Number.isFinite(retryAfter)) {
    return Math.max(0, retryAfter * 1_000);
  }
  const trimmed = String(retryAfter).trim();
  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed) * 1_000;
  }
  const parsedDate = Date.parse(trimmed);
  if (Number.isNaN(parsedDate)) {
    return null;
  }
  return Math.max(0, parsedDate - nowMs);
}

export function decideLeaseClaim(input: LeaseClaimInput): LeaseClaimDecision {
  const leaseExpiresAtMs = input.lease_until ? Date.parse(input.lease_until) : Number.NaN;
  const hasActiveLease =
    Boolean(input.lease_owner && input.lease_token) &&
    Number.isFinite(leaseExpiresAtMs) &&
    leaseExpiresAtMs > input.nowMs;

  if (hasActiveLease) {
    return {
      ok: false,
      action: "reject",
      reason: "lease_not_expired",
      current_lease_owner: input.lease_owner,
      current_lease_token: input.lease_token,
      fencing_version: input.fencing_version,
    };
  }

  const takeover = Boolean(input.lease_owner || input.lease_token || input.lease_until);
  return {
    ok: true,
    action: takeover ? "takeover" : "claim",
    lease_owner: input.requestedOwner,
    lease_token: crypto.randomUUID(),
    fencing_version: input.fencing_version + 1,
    previous_lease_token: input.lease_token,
  };
}

export function isLeaseCurrent(
  state: LeaseState,
  presentedLeaseToken: string,
  presentedFencingVersion: number,
): boolean {
  return (
    Boolean(state.lease_token) &&
    state.lease_token === presentedLeaseToken &&
    state.fencing_version === presentedFencingVersion
  );
}
