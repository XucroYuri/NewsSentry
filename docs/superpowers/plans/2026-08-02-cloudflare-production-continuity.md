# Cloudflare Production Continuity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a continuously collecting, fail-closed NewsSentry production runtime on the existing low-cost Cloudflare Cron → Container → durable R2/D1 → public drafts architecture.

**Architecture:** Keep control, compute, durable data, and public read planes separate. Production Cron invokes the Container for bounded collection, the Worker validates the outcome and commits immutable R2 artifacts plus D1 projections, and public readers query only eligible `drafts`; dependency skips, empty-but-inconsistent outcomes, stale/future timestamps, receipt gaps, or restore failures must make health and promotion fail closed.

**Tech Stack:** Cloudflare Workers, Cron Triggers, Containers, Queues in shadow mode, D1, R2, TypeScript, Node test runner, Python 3.11+, pytest, GitHub Actions.

## Global Constraints

- Gate 0 consumes Task 9 from the durable-import plan and is a hard prerequisite for any production deploy: exact SHA, anonymous 403, service-token 200, idempotent replay, D1/R2 cross-check, and isolated restore receipt must all pass.
- Local Tasks 1-8 may be implemented and reviewed before Preview credentials are available, but no production dispatch, merge, or health claim is allowed.
- Preserve `SCHEDULER_MODE=shadow` and `WORKER_NATIVE_COLLECT_ENABLED=false`; Queue must not become authoritative in this plan.
- Preserve R2 as the immutable import artifact plane and D1 as projection/index/receipt plane; do not reintroduce direct D1-only import or independent manifest commit paths.
- Public reads remain `pipeline_stage='drafts'`; do not broaden the feed to all stages to hide collection or visibility defects.
- No new service, paid dependency, framework, Redis, Celery, VPS, Tunnel, or systemd runtime dependency.
- Production dependency absence must never be represented as a successful run. Only an explicit, internally consistent `empty_no_new_items` outcome may be healthy with zero imported rows.
- Future `published_at` values must be quarantined before public projection; future timestamps must never define freshness.
- Every task uses strict RED → GREEN TDD, a fresh task review, and a separate commit.
- Production promotion requires 72 hours of canary evidence followed by 7 days of SLO evidence; CI green, local tests, Preview synthetic data, and HTTP 200 alone are insufficient.

---

## File Structure Map

- `frontend/cloudflare/workers/lib/scheduled.ts`: authoritative Cron orchestration, target rotation, Container invocation, run status, and cursor advancement.
- `frontend/cloudflare/workers/lib/container-import.ts`: validates Container response counters and delegates every non-empty import to `executeDurableProjectionImport()`.
- `frontend/cloudflare/workers/lib/health-status.ts` and `workers/lib/contracts.ts`: typed health/readiness/business-health contract.
- `frontend/cloudflare/workers/api/health.ts`: gathers D1 and binding signals and builds the health response used by `/health` and `/ready`.
- `src/news_sentry/core/api_server.py` and `collector_config_utils.py`: Container-side bounded collection response and canonical `drafts` export.
- `frontend/cloudflare/workers/lib/timestamp-policy.ts` and `public-news-query.ts`: ingest quarantine and public-read timestamp defense.
- `tools/cloudflare_deploy_guard.py`: exact-commit deploy/preflight receipt.
- `tools/cloudflare_runtime_probe.py` and `tools/cloudflare_continuity_ledger.py`: point-in-time runtime receipt and multi-run 72h/7d evidence.
- `tools/source_health_audit.py`: P0/global source availability evidence used by promotion.
- `tools/cloudflare_restore_drill.py`: isolated D1/R2 recovery proof bound to the same production commit.

### Gate 0: Complete the existing exact-SHA Preview evidence task

**Files:**
- No repository file changes.
- Existing workflow: `.github/workflows/deploy.yml`
- Existing workflow: `.github/workflows/cloudflare-restore-drill.yml`
- Existing verifier: `tools/cloudflare_preview_canary.py`
- Existing verifier: `tools/cloudflare_restore_drill.py`
- Authoritative procedure: `docs/superpowers/plans/2026-08-02-cloudflare-durable-import-preview-canary.md:996`

**Interfaces:**
- Consumes GitHub `preview` Environment variables `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `CF_ACCESS_SERVICE_TOKEN_IDS` and secrets `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.
- Produces deploy artifact `news-sentry-preview-artifact-canary-receipt` and restore artifact `cloudflare-restore-receipt-preview-${run_id}` for the same full commit SHA.

- [ ] **Step 1: Fail closed unless the Preview Access boundary exists**

```bash
gh variable list --env preview
gh secret list --env preview
test "$(gh variable list --env preview --json name --jq '[.[].name | select(. == "CF_ACCESS_TEAM_DOMAIN" or . == "CF_ACCESS_AUD" or . == "CF_ACCESS_SERVICE_TOKEN_IDS")] | length')" -eq 3
test "$(gh secret list --env preview --json name --jq '[.[].name | select(. == "CF_ACCESS_CLIENT_ID" or . == "CF_ACCESS_CLIENT_SECRET")] | length')" -eq 2
```

Expected: PASS only after the account-scoped Access bootstrap from the durable-import plan has created/reused the exact Preview application and Service Auth policy. Never dispatch a known-failing run when these five names are missing.

- [ ] **Step 2: Push and bind the exact reviewed SHA**

```bash
release_branch="dev-xu/fix/cloudflare-persistent-runtime"
git push origin "HEAD:refs/heads/${release_branch}"
sha="$(git rev-parse HEAD)"
remote_sha="$(git ls-remote origin "refs/heads/${release_branch}" | cut -f1)"
test "${sha}" = "${remote_sha}"
```

The isolated implementation worktree intentionally uses `dev-xu/work/cloudflare-durable-import-preview-canary`; the existing reviewed Draft PR #50 is intentionally updated through the approved release branch `dev-xu/fix/cloudflare-persistent-runtime`. The equality check proves that the release branch points to this exact reviewed worktree HEAD before any dispatch.

- [ ] **Step 3: Dispatch Preview and validate the sanitized durable canary artifact**

```bash
release_branch="dev-xu/fix/cloudflare-persistent-runtime"
sha="$(git rev-parse HEAD)"
run_url="$(gh workflow run deploy.yml --ref "${release_branch}" -f environment=preview)"
run_id="${run_url##*/}"
test -n "${run_id}"
test "$(gh run view "${run_id}" --json headSha --jq '.headSha')" = "${sha}"
gh run watch "${run_id}" --exit-status
receipt_dir="$(mktemp -d)"
gh run download "${run_id}" -n news-sentry-preview-artifact-canary-receipt -D "${receipt_dir}"
python -m json.tool "${receipt_dir}/news-sentry-preview-artifact-canary-receipt.json" >/dev/null
python -c 'import json, pathlib; p=pathlib.Path("'"${receipt_dir}"'/news-sentry-preview-artifact-canary-receipt.json"); data=json.loads(p.read_text()); assert data.get("status") == "ok"; text=json.dumps(data, sort_keys=True).lower(); forbidden=("client_secret","authorization","jwt","headers","request_body","cf-access-client-secret"); assert not any(x in text for x in forbidden)'
```

Expected: anonymous import is 403; service-token first/replay imports are 200 with `replayed=true` on replay; one batch/job/artifact/source receipt/projection receipt/event exists; R2 bytes and SHA-256 match; the artifact contains no secret, JWT, header, or request body.

- [ ] **Step 4: Dispatch and validate isolated Preview restore**

```bash
release_branch="dev-xu/fix/cloudflare-persistent-runtime"
sha="$(git rev-parse HEAD)"
restore_run_url="$(gh workflow run cloudflare-restore-drill.yml --ref "${release_branch}" \
  -f environment=preview -f expected_commit="${sha}")"
restore_run_id="${restore_run_url##*/}"
test -n "${restore_run_id}"
test "$(gh run view "${restore_run_id}" --json headSha --jq '.headSha')" = "${sha}"
gh run watch "${restore_run_id}" --exit-status
restore_dir="$(mktemp -d)"
gh run download "${restore_run_id}" \
  -n "cloudflare-restore-receipt-preview-${restore_run_id}" -D "${restore_dir}"
python -m json.tool "${restore_dir}/restore-receipt.json" >/dev/null
python -c 'import json, pathlib; data=json.loads(pathlib.Path("'"${restore_dir}"'/restore-receipt.json").read_text()); assert data.get("status") == "ok"'
```

Expected: committed artifact coverage is non-zero; source/projection receipts have no orphan or conflict; artifact checksum/bytes match; isolated D1 is deleted and confirmed absent. Any missing artifact, failed workflow, secret finding, commit mismatch, or restore blocker stops all production promotion.

---

### Task 1: Make collection dependency skips fail closed

**Files:**
- Modify: `frontend/cloudflare/workers/lib/scheduled.ts`
- Modify: `frontend/cloudflare/workers/lib/container-import.ts`
- Modify: `frontend/cloudflare/workers/lib/health-status.ts`
- Test: `frontend/cloudflare/tests/scheduled-durable-import.test.mts`
- Test: `frontend/cloudflare/tests/health-status.test.mts`

**Interfaces:**
- Consumes: `runScheduledCloudflareTask(controller: ScheduledController, env: ScheduledEnv): Promise<void>` and `importContainerEventsToD1(env, details, runId, generatedAt, task): Promise<Record<string, unknown>>`.
- Produces new pure helper `classifyContainerDependency(container: DurableObjectNamespace | undefined): {status: "failed_dependency"; reason: "container_not_configured"} | null`; dependency failures use `status: "failed_dependency"`; the only healthy zero-import status is `empty_no_new_items` with consistent counters.

- [ ] **Step 1: Write failing scheduled/import tests**

```ts
test("missing production container is a dependency failure", async () => {
  const result = classifyContainerDependency(undefined);
  assert.deepEqual(result, {
    status: "failed_dependency",
    reason: "container_not_configured",
  });
});

test("collected rows without import rows fail closed", async () => {
  await assert.rejects(
    () => importContainerEventsToD1(
      env,
      { body: { summary: { events_collected: 3, import_events_count: 0 }, import_events: [] } },
      "run-mismatch",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_import_count_mismatch/,
  );
});
```

- [ ] **Step 2: Write failing health classification test**

```ts
test("dependency failures make runtime unhealthy", () => {
  const input = baseInput();
  input.scheduler.collect_cycle.status = "failed_dependency";
  const health = buildHealthResponse(input);
  assert.equal(health.status, "unhealthy");
  assert.ok(health.reason_codes.includes("collect_cycle_failed"));
});
```

- [ ] **Step 3: Run RED tests**

Run:

```bash
cd frontend/cloudflare
npm test -- --test-name-pattern="dependency failure|collected rows without import|runtime unhealthy"
```

Expected: FAIL because Container absence is `skipped`, zero-event imports return success, and `failed_dependency` is not classified as failed.

- [ ] **Step 4: Implement the status and counter contract**

```ts
if (!env.NEWS_SENTRY_CONTAINER) {
  return { status: "failed_dependency", reason: "container_not_configured" };
}

const collected = Number(payload.summary?.events_collected ?? 0);
const declared = Number(payload.summary?.import_events_count ?? payload.import_events.length);
if (!Number.isInteger(collected) || collected < 0 ||
    !Number.isInteger(declared) || declared < 0 ||
    declared !== payload.import_events.length) {
  throw new Error("container_import_count_mismatch:declared_vs_actual");
}
if (collected > 0 && declared === 0) {
  throw new Error("container_import_count_mismatch:collected_without_import_events");
}
if (collected === 0 && declared === 0 && payload.import_events.length === 0) {
  return { status: "empty_no_new_items", imported: 0, updated: 0, quarantined: 0, errors: [] };
}

function hasFailedStatus(status: string | null | undefined): boolean {
  return ["error", "failed", "failed_retryable", "failed_dependency"].includes(String(status ?? ""));
}
```

Call `classifyContainerDependency()` from `callContainerInternalTask()`. When `importContainerEventsToD1()` returns `status="empty_no_new_items"`, promote that value to the top-level scheduled-run status before `recordRun()`; do not leave an empty import recorded as a generic `ok` from the Container HTTP response.

- [ ] **Step 5: Run GREEN and adjacent Worker tests**

```bash
cd frontend/cloudflare
npm test -- --test-name-pattern="dependency failure|collected rows without import|runtime unhealthy"
npm test
```

Expected: targeted tests PASS and the full Worker suite PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/cloudflare/workers/lib/scheduled.ts \
  frontend/cloudflare/workers/lib/container-import.ts \
  frontend/cloudflare/workers/lib/health-status.ts \
  frontend/cloudflare/tests/scheduled-durable-import.test.mts \
  frontend/cloudflare/tests/health-status.test.mts
git commit -m "fix(cloudflare): fail closed on collection dependencies"
```

---

### Task 2: Expose compute readiness in health and probes

**Files:**
- Modify: `frontend/cloudflare/workers/api/health.ts`
- Modify: `frontend/cloudflare/workers/lib/health-status.ts`
- Modify: `frontend/cloudflare/workers/lib/contracts.ts`
- Modify: `frontend/cloudflare/workers/lib/router.ts`
- Modify: `frontend/cloudflare/workers/index.ts`
- Modify: `tools/cloudflare_runtime_probe.py`
- Test: `frontend/cloudflare/tests/health.test.mts`
- Test: `frontend/cloudflare/tests/health-status.test.mts`
- Test: `tests/tools/test_cloudflare_runtime_probe.py`

**Interfaces:**
- Consumes: existing routes `/api/v1/live` → `handleLiveness` and `/api/v1/ready` → `handleHealth`, plus `RuntimeMetadata` built from `NEWS_SENTRY_CONTAINER`, `NEWS_SENTRY_JOBS_QUEUE`, and scheduler mode.
- Produces: `deployment.compute.container_configured` and `deployment.compute.queue_configured`; preserves `HealthLevel = "ok" | "degraded" | "unhealthy"`, with missing required Container readiness mapped to `unhealthy`/HTTP 503.

- [ ] **Step 1: Write RED health tests**

```ts
test("production readiness fails when container binding is absent", () => {
  const input = baseInput();
  input.compute = { container_configured: false, queue_configured: true };
  const health = buildHealthResponse(input);
  assert.equal(health.status, "unhealthy");
  assert.equal(health.readiness?.ok, false);
  assert.ok(health.reason_codes?.includes("container_not_configured"));
  assert.equal(httpStatusForHealth(health.status), 503);
});
```

```python
def test_probe_rejects_missing_container_readiness(tmp_path: Path) -> None:
    result, receipt = _run_probe(tmp_path, container_configured=False)
    assert result.returncode == 1
    assert receipt["status"] == "failed"
    assert "container_not_configured" in receipt["summary"]["reason_codes"]
```

- [ ] **Step 2: Run RED tests**

```bash
cd frontend/cloudflare
npm test -- --test-name-pattern="production readiness"
cd ../..
.venv/bin/python -m pytest tests/tools/test_cloudflare_runtime_probe.py::test_probe_rejects_missing_container_readiness -q
```

Expected: FAIL because live/ready already route correctly, but `RuntimeMetadata`, `HealthSignalsInput`, and `HealthResponse` do not carry Container compute readiness.

- [ ] **Step 3: Implement readiness payload and routes**

```ts
const compute = {
  container_configured: Boolean(env.NEWS_SENTRY_CONTAINER),
  queue_configured: Boolean(env.NEWS_SENTRY_JOBS_QUEUE),
};
```

Add `compute` to `RuntimeMetadata`, `HealthSignalsInput`, and `HealthResponse.deployment`; pass it from `index.ts` through `handleHealth()` to `buildHealthResponse()`. Append `container_not_configured` when false and include it in `worstStatus()`'s `unhealthy` reasons. In `tests/tools/test_cloudflare_runtime_probe.py`, extend the existing `_runtime_payload()`, `_handler()`, and `_run_probe()` fixtures with a `container_configured` flag; do not introduce a second receipt builder. In `cloudflare_runtime_probe.py`, read `deployment.compute.container_configured`; record missing Queue as degraded while scheduler mode is `shadow`, and block it only when configuration explicitly declares Queue required.

- [ ] **Step 4: Run GREEN tests**

```bash
cd frontend/cloudflare
npm test
cd ../..
.venv/bin/python -m pytest tests/tools/test_cloudflare_runtime_probe.py -q
.venv/bin/python -m ruff check tools/cloudflare_runtime_probe.py tests/tools/test_cloudflare_runtime_probe.py
```

Expected: PASS; `/live` proves process reachability and `/ready` proves production compute readiness without conflating them.

- [ ] **Step 5: Commit**

```bash
git add frontend/cloudflare/workers/api/health.ts \
  frontend/cloudflare/workers/lib/health-status.ts \
  frontend/cloudflare/workers/lib/contracts.ts \
  frontend/cloudflare/workers/lib/router.ts \
  frontend/cloudflare/workers/index.ts \
  frontend/cloudflare/tests/health.test.mts \
  frontend/cloudflare/tests/health-status.test.mts \
  tools/cloudflare_runtime_probe.py tests/tools/test_cloudflare_runtime_probe.py
git commit -m "feat(cloudflare): expose compute readiness"
```

---

### Task 3: Make Container collection outcomes auditable

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/core/collector_config_utils.py`
- Modify: `frontend/cloudflare/workers/lib/container-import.ts`
- Test: `tests/unit/test_api_server.py`
- Test: `frontend/cloudflare/tests/scheduled-durable-import.test.mts`

**Interfaces:**
- Consumes existing `_run_auto_collect_once(run_id=None, target_ids_override=None) -> dict[str, Any]` and `_collect_cloudflare_d1_import_events(*, data_dir: Path, target_ids: list[str], limit: int | None = None, event_ids_by_target: dict[str, set[str]] | None = None) -> list[dict[str, Any]]`; this task calls the latter without the optional event filter.
- Produces `_build_cloudflare_collect_target_results(*, target_ids: list[str], contexts: list[Any], import_events: list[dict[str, Any]]) -> list[dict[str, Any]]`; Container `summary.target_results[]` contains `target_id`, `status`, `events_collected`, `import_events_count`, `reason`, plus aggregates `targets_attempted`, `targets_succeeded`, `targets_failed`.
- Consumes those counters in the Worker and rejects missing, contradictory, or partially silent results.

- [ ] **Step 1: Write RED Python tests**

```python
def test_cloudflare_collect_reports_missing_target_database(tmp_path: Path) -> None:
    results = _build_cloudflare_collect_target_results(
        target_ids=["italy"], contexts=[], import_events=[]
    )
    assert results == [{
        "target_id": "italy",
        "status": "error",
        "events_collected": 0,
        "import_events_count": 0,
        "reason": "target_database_missing",
    }]
```

- [ ] **Step 2: Write RED Worker consistency test**

```ts
test("target failures cannot be hidden by an empty import array", async () => {
  await assert.rejects(
    () => importContainerEventsToD1(
      env,
      { body: { summary: {
        targets_attempted: 1,
        targets_succeeded: 0,
        targets_failed: 1,
        target_results: [{ target_id: "italy", status: "error", reason: "target_database_missing" }],
      }, import_events: [] } },
      "run-target-failure",
      "2026-08-02T01:00:00Z",
      "collect-cycle",
    ),
    /container_target_failures/,
  );
});
```

- [ ] **Step 3: Run RED tests**

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestCloudflareInternalAPI::test_cloudflare_collect_reports_missing_target_database -q
cd frontend/cloudflare
npm test -- --test-name-pattern="target failures cannot be hidden"
```

Expected: FAIL because `_build_cloudflare_collect_target_results` does not exist and current Container details do not enforce the aggregate/target-result contract.

- [ ] **Step 4: Implement structured outcomes**

Use one `target_result` for every selected target. Convert missing DB and SQLite exceptions to `status="error"`; use `status="empty_no_new_items"` only after a successful query/collection with zero new events. Compute aggregates from the result list rather than separate mutable counters. In the Worker, require `targets_attempted === target_results.length` and reject any `status="error"` before durable import.

- [ ] **Step 5: Run GREEN tests**

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
.venv/bin/python -m ruff check src/news_sentry/core/api_server.py src/news_sentry/core/collector_config_utils.py tests/unit/test_api_server.py
.venv/bin/python -m mypy src/news_sentry/core/api_server.py src/news_sentry/core/collector_config_utils.py --ignore-missing-imports
cd frontend/cloudflare
npm test
```

Expected: PASS with one structured outcome per attempted target.

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/core/collector_config_utils.py \
  frontend/cloudflare/workers/lib/container-import.ts \
  tests/unit/test_api_server.py frontend/cloudflare/tests/scheduled-durable-import.test.mts
git commit -m "fix(runtime): make collection outcomes auditable"
```

---

### Task 4: Enforce drafts visibility and quarantine future timestamps

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/core/collector_config_utils.py`
- Modify: `frontend/cloudflare/workers/lib/durable-import.ts`
- Modify: `frontend/cloudflare/workers/lib/timestamp-policy.ts`
- Modify: `frontend/cloudflare/workers/lib/projection-sql.ts`
- Modify: `frontend/cloudflare/workers/lib/public-news-query.ts`
- Modify: `frontend/cloudflare/workers/lib/health-status.ts`
- Test: `tests/unit/test_api_server.py`
- Test: `frontend/cloudflare/tests/ingest-policy.test.mts`
- Test: `frontend/cloudflare/tests/durable-projection-import.test.mts`
- Test: `frontend/cloudflare/tests/health-status.test.mts`

**Interfaces:**
- Produces explicit `pipeline_stage: "drafts"` for eligible Container public events.
- Requires every durable-import event to carry a non-empty `pipeline_stage`; removes the projection fallback to `published`.
- Consumes existing `assessEventTimestamps(collectedAtValue, publishedAtValue, nowMs)` and `buildPublicNewsWhere(input)`.
- Produces quarantine reason `future_published_at` beyond the explicit `PUBLISHED_AT_FUTURE_TOLERANCE_MS`; public SQL independently excludes rows beyond the same 24-hour tolerance; any `future_timestamp_count > 0` makes runtime health `unhealthy`.

- [ ] **Step 1: Confirm the existing Container regression guard, then write RED Worker tests**

Keep the existing `test_collect_d1_import_payload_preserves_public_projection` fixture and its already-green explicit invariant produced by `_collect_cloudflare_d1_import_events()`:

```python
events = _collect_cloudflare_d1_import_events(
    data_dir=tmp_path,
    target_ids=["france"],
    limit=10,
)
assert len(events) == 1
assert events[0]["pipeline_stage"] == "drafts"
```

```ts
test("durable import rejects an event without an explicit pipeline stage", async () => {
  const db = new SqliteD1Database();
  const bucket = new FakeR2Bucket();
  await assert.rejects(
    () => importEvents(db, bucket, [event(1, { pipeline_stage: "" })]),
    /missing_required_import_fields/,
  );
  assert.equal(bucket.objects.size, 0);
  assert.equal(db.first<{ count: number }>("SELECT COUNT(*) AS count FROM events", [])?.count, 0);
});

test("future events are quarantined and make runtime unhealthy", () => {
  const now = Date.parse("2026-08-02T00:00:00Z");
  const decision = assessEventTimestamps(
    "2026-08-02T00:00:00Z",
    "2028-01-01T00:00:00Z",
    now,
  );
  assert.deepEqual(decision, { ok: false, reason: "future_published_at" });
  assert.match(buildPublicNewsWhere({}).sql, /published_at.*datetime\('now', '\+24 hours'\)/);

  const input = baseInput();
  input.future_timestamp_count = 1;
  const health = buildHealthResponse(input);
  assert.equal(health.status, "unhealthy");
  assert.equal(health.readiness?.ok, false);
});
```

- [ ] **Step 2: Run RED tests**

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestCloudflareInternalAPI::test_collect_d1_import_payload_preserves_public_projection -q
cd frontend/cloudflare
npm test -- --test-name-pattern="explicit pipeline stage|future events are quarantined"
```

Expected: the existing Python projection regression guard PASSes; Worker tests FAIL because durable import still permits a missing stage, projection defaults it to `published`, and future timestamps currently produce only `degraded` health. Only the Worker assertions are RED for this task.

- [ ] **Step 3: Implement explicit stage and dual timestamp guards**

Keep `pipeline_stage="drafts"` in the canonical Container export for editorially eligible events. Add `pipeline_stage` to `validateEventEnvelope()` required fields and remove the `COALESCE(..., 'published')` insert fallback so every ingress path must make an explicit stage decision. Keep the existing injected-clock quarantine and public SQL defense aligned:

```sql
AND datetime(events.published_at) <= datetime('now', '+24 hours')
```

Do not coerce future timestamps to current time and do not let synthetic canary events enter public drafts.
Add `future_timestamp_detected` to the unhealthy set in `worstStatus()` so readiness fails closed until the polluted rows are quarantined or removed.

- [ ] **Step 4: Run GREEN tests**

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
cd frontend/cloudflare
npm test
```

Expected: PASS; future events are quarantined and drafts remain an explicit export decision.

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/core/collector_config_utils.py \
  frontend/cloudflare/workers/lib/durable-import.ts \
  frontend/cloudflare/workers/lib/timestamp-policy.ts \
  frontend/cloudflare/workers/lib/projection-sql.ts \
  frontend/cloudflare/workers/lib/public-news-query.ts \
  frontend/cloudflare/workers/lib/health-status.ts \
  tests/unit/test_api_server.py frontend/cloudflare/tests/ingest-policy.test.mts \
  frontend/cloudflare/tests/durable-projection-import.test.mts \
  frontend/cloudflare/tests/health-status.test.mts
git commit -m "fix(cloudflare): enforce public event time boundaries"
```

---

### Task 5: Make low-cost canary target batches deterministic

**Files:**
- Modify: `frontend/cloudflare/workers/lib/scheduled.ts`
- Modify: `tools/cloudflare_d1_backfill.py`
- Create: `frontend/cloudflare/tests/scheduled-continuity.test.mts`
- Test: `tests/unit/test_cloudflare_d1_backfill.py`

**Interfaces:**
- Consumes existing `targets.cloudflare_collect_enabled`, `ORDER BY target_id`, `COLLECT_TARGET_BATCH_SIZE = 4`, and `runScheduledCloudflareTask()`.
- Produces `selected_target_ids`, `selection_cursor_before`, `selection_cursor_after`, and `enabled_target_count`; advances the existing cursor only for `ok`, `partial`, or `empty_no_new_items`.

- [ ] **Step 1: Write RED deterministic selection tests**

```ts
test("collect cycle selects only enabled targets in stable rotating batches", async () => {
  seedTargets(db, [enabled("italy"), disabled("japan"), enabled("germany"), enabled("france")]);
  await runScheduledCloudflareTask(controller("*/15 * * * *"), env(db, successfulContainer()));
  const first = latestCollectDetails(db).collect_batch;
  assert.deepEqual(first.selected_target_ids, ["france", "germany", "italy"]);
  assert.equal(first.enabled_target_count, 3);
  assert.ok(!first.selected_target_ids.includes("japan"));
});

test("collect cycle fails when no target is enabled", async () => {
  seedTargets(db, [disabled("italy"), disabled("japan")]);
  await runScheduledCloudflareTask(controller("*/15 * * * *"), env(db, successfulContainer()));
  const latest = latestCollectRun(db);
  assert.equal(latest.status, "failed_dependency");
  assert.equal(latest.details.reason, "no_collect_targets_enabled");
});
```

- [ ] **Step 2: Run RED tests**

```bash
cd frontend/cloudflare
npm test -- --test-name-pattern="stable rotating batches|no target is enabled"
cd ../..
.venv/bin/python -m pytest tests/unit/test_cloudflare_d1_backfill.py -q
```

Expected: FAIL because selection receipts/cursor invariants are not fully locked.

- [ ] **Step 3: Normalize deterministic selection and canary enablement**

Keep the existing schema column and migration history. Normalize receipt field names, preserve stable target ordering, and advance the existing cursor for `ok`, `partial`, or `empty_no_new_items`; never advance it on dependency/target failures. Convert the current `empty_no_targets` result to `failed_dependency` with reason `no_collect_targets_enabled`. Extend the D1 backfill plan/receipt so operators can specify an exact four-target canary allowlist instead of enabling all configured targets.

- [ ] **Step 4: Run GREEN tests and schema validators**

```bash
cd frontend/cloudflare
npm test
cd ../..
.venv/bin/python -m pytest tests/unit/test_cloudflare_d1_backfill.py tests/unit/test_cloudflare_native_config.py -q
```

Expected: PASS; disabled targets never consume Container time and every batch is reproducible from receipt fields.

- [ ] **Step 5: Commit**

```bash
git add frontend/cloudflare/workers/lib/scheduled.ts \
  frontend/cloudflare/tests/scheduled-continuity.test.mts \
  tools/cloudflare_d1_backfill.py tests/unit/test_cloudflare_d1_backfill.py
git commit -m "feat(cloudflare): add deterministic collection canaries"
```

---

### Task 6: Gate deployment on continuity evidence

**Files:**
- Modify: `tools/cloudflare_deploy_guard.py`
- Modify: `.github/workflows/deploy.yml`
- Test: `tests/tools/test_cloudflare_deploy_guard.py`
- Test: `tests/tools/test_preview_deploy_workflow.py`

**Interfaces:**
- Consumes existing `run_preflight(config, runner, transport) -> dict[str, Any]` and current `build_deploy_receipt(*, expected_commit, expected_scheduler_mode, version_json, deployment_json, health_json, applied_migration_receipts, queue_receipt) -> dict[str, Any]`.
- Adds the new keyword argument `continuity_json` to `build_deploy_receipt()` and validates exact deployed commit, compute readiness, latest collect run, target-selection receipt, and D1/R2 migration/artifact receipts.
- Produces: deployment receipt with `continuity.status`, `reason_codes`, `collect_run_id`, `selected_target_ids`, and exact `deployed_commit`.
- Adds a test-only `_valid_deploy_receipt_kwargs(**overrides)` helper beside the existing deploy-receipt tests; production code keeps one receipt builder.

- [ ] **Step 1: Write RED guard tests**

```python
def _valid_deploy_receipt_kwargs(**overrides: Any) -> dict[str, Any]:
    values = {
        "expected_commit": "a" * 40,
        "expected_scheduler_mode": "shadow",
        "version_json": {"id": "version-1"},
        "deployment_json": {"id": "deployment-1", "version_id": "version-1"},
        "health_json": {
            "status": "ok",
            "deployment": {
                "commit": "a" * 40,
                "worker_version": "version-1",
                "scheduler_mode": "shadow",
                "worker_native_collect_enabled": False,
                "compute": {"container_configured": True, "queue_configured": True},
            },
        },
        "applied_migration_receipts": EXPECTED_RUNTIME_RECEIPTS,
        "queue_receipt": {"status": "ok"},
        "continuity_json": {
            "status": "ok",
            "deployed_commit": "a" * 40,
            "latest_collect": {"status": "ok", "run_id": "collect-1"},
            "selected_target_ids": ["france", "germany", "italy", "japan"],
        },
    }
    values.update(overrides)
    return values

@pytest.mark.parametrize("status", ["skipped", "failed_dependency", "failed_retryable"])
def test_deploy_guard_rejects_non_authoritative_collect_status(status: str) -> None:
    with pytest.raises(ReceiptError, match=f"latest collect status invalid: {status}"):
        build_deploy_receipt(**_valid_deploy_receipt_kwargs(
            continuity_json={
                "status": "failed",
                "deployed_commit": "a" * 40,
                "latest_collect": {"status": status},
            },
        ))

def test_deploy_guard_binds_continuity_to_exact_commit() -> None:
    with pytest.raises(ReceiptError, match="continuity commit mismatch"):
        build_deploy_receipt(**_valid_deploy_receipt_kwargs(
            expected_commit="b" * 40,
            continuity_json={"status": "ok", "deployed_commit": "a" * 40},
        ))
```

- [ ] **Step 2: Run RED tests**

```bash
.venv/bin/python -m pytest tests/tools/test_cloudflare_deploy_guard.py tests/tools/test_preview_deploy_workflow.py -q
```

Expected: FAIL because the deployment receipt does not yet require a successful authoritative collect result bound to the same commit.

- [ ] **Step 3: Implement guard fields and workflow order**

Require `container_configured`, R2/D1 bindings, the continuity migration receipt, no dependency skip, exact commit equality, and a valid recent collect result before production verification can succeed. Record Queue binding/readiness in the receipt; while scheduler mode remains `shadow`, missing Queue is degraded evidence and becomes blocking only when an explicit configuration flag declares Queue required. Preview may prove data-plane imports but must record `continuity.status="not_exercised_preview"`; it must not emit a production-continuity success.

- [ ] **Step 4: Run GREEN tests**

```bash
.venv/bin/python -m pytest tests/tools/test_cloudflare_deploy_guard.py tests/tools/test_preview_deploy_workflow.py -q
.venv/bin/python -m ruff check tools/cloudflare_deploy_guard.py tests/tools/test_cloudflare_deploy_guard.py
.venv/bin/python -m mypy --explicit-package-bases tools/cloudflare_deploy_guard.py tests/tools/test_cloudflare_deploy_guard.py
```

Expected: PASS; production deploy receipts cannot be green when collection is skipped or commit evidence drifts.

- [ ] **Step 5: Commit**

```bash
git add tools/cloudflare_deploy_guard.py .github/workflows/deploy.yml \
  tests/tools/test_cloudflare_deploy_guard.py tests/tools/test_preview_deploy_workflow.py
git commit -m "ci(cloudflare): gate deploys on collection continuity"
```

---

### Task 7: Record exact-commit 72-hour and 7-day SLO evidence

**Files:**
- Modify: `tools/cloudflare_runtime_probe.py`
- Create: `tools/cloudflare_continuity_ledger.py`
- Modify: `tools/source_health_audit.py`
- Create: `config/source-health-slo.yaml`
- Modify: `.github/workflows/cloudflare-runtime-health.yml`
- Modify: `.github/workflows/source-health.yml`
- Test: `tests/tools/test_cloudflare_runtime_probe.py`
- Create: `tests/tools/test_cloudflare_continuity_ledger.py`
- Modify: `tests/tools/test_cloudflare_runtime_health_workflow.py`
- Modify: `tests/unit/test_source_health_audit.py`

**Interfaces:**
- Produces secret-free append-only receipts keyed by `deployed_commit`, `observed_at`, and `run_id`.
- Produces ledger states `collecting_72h`, `canary_72h_passed`, `collecting_7d`, `slo_7d_passed`, `failed`.
- Produces `evaluate_source_health_slo(summary, rows, config, previous_summary=None) -> dict[str, Any]` with P0/global ratios and blockers.
- Requires: freshness ≤2h, public freshness ≤24h, future timestamps =0, P0 DLQ=0, backlog oldest ≤30m, committed artifact coverage=100%, Source Health P0=100%, global ok≥90%, failed≤2%, week-over-week ok drop≤3 percentage points, and no blocking reason code.

- [ ] **Step 1: Write RED ledger tests**

```python
def test_72h_requires_twelve_same_commit_receipts() -> None:
    receipts = [healthy_receipt(hours=(i + 1) * 6, commit="a" * 40) for i in range(11)]
    assert evaluate_window(receipts).status == "collecting_72h"
    receipts.append(healthy_receipt(hours=72, commit="a" * 40))
    assert evaluate_window(receipts).status == "canary_72h_passed"

def test_window_resets_on_commit_drift_or_future_public_data() -> None:
    receipts = [healthy_receipt(hours=0, commit="a" * 40), healthy_receipt(hours=6, commit="b" * 40)]
    assert evaluate_window(receipts).status == "failed"
    assert "deployed_commit_changed" in evaluate_window(receipts).reason_codes

def test_source_health_slo_requires_p0_and_ratio_thresholds() -> None:
    result = evaluate_source_health_slo(
        summary={"total": 100, "ok": 91, "failed": 1},
        rows=[{"target_id": "italy", "source_id": "ansa", "health_status": "failed"}],
        config={"p0_source_refs": ["italy:ansa"], "minimum_ok_ratio": 0.90, "maximum_failed_ratio": 0.02},
    )
    assert result["status"] == "failed"
    assert "p0_source_failed:italy:ansa" in result["blockers"]
```

- [ ] **Step 2: Run RED tests**

```bash
.venv/bin/python -m pytest tests/tools/test_cloudflare_continuity_ledger.py tests/tools/test_cloudflare_runtime_probe.py tests/tools/test_cloudflare_runtime_health_workflow.py tests/unit/test_source_health_audit.py -q
```

Expected: FAIL because the append-only continuity ledger does not exist.

- [ ] **Step 3: Implement canonical receipt aggregation**

Write receipts atomically as JSON, sort by `observed_at`, reject duplicates with conflicting content, reject commit drift, and require 12 healthy six-hour slots reaching 72h plus 28 healthy six-hour slots reaching 7d from `deployed_at`. The workflow obtains the deployed commit from deployment metadata/guard receipt, never a moving branch ref. Add `config/source-health-slo.yaml` with P0 refs `italy:ansa`, `germany:tagesschau-politics`, `france:lemonde-politics`, `japan:nhk-news` and thresholds `minimum_ok_ratio: 0.90`, `maximum_failed_ratio: 0.02`, `maximum_weekly_ok_drop: 0.03`. Source Health writes a sanitized SLO receipt; the 72h gate requires a current green audit and the 7d gate requires green audits at both canary start and end.

- [ ] **Step 4: Run GREEN tests and sensitive scan**

```bash
.venv/bin/python -m pytest tests/tools/test_cloudflare_continuity_ledger.py tests/tools/test_cloudflare_runtime_probe.py tests/tools/test_cloudflare_runtime_health_workflow.py tests/unit/test_source_health_audit.py -q
.venv/bin/python -m ruff check tools/cloudflare_continuity_ledger.py tools/cloudflare_runtime_probe.py tools/source_health_audit.py tests/tools tests/unit/test_source_health_audit.py
.venv/bin/python -m mypy --explicit-package-bases tools/cloudflare_continuity_ledger.py tools/cloudflare_runtime_probe.py tools/source_health_audit.py
.venv/bin/python tools/scan_sensitive_data.py
```

Expected: PASS; a branch SHA, missing interval, future timestamp, or any unhealthy receipt prevents SLO promotion.

- [ ] **Step 5: Commit**

```bash
git add tools/cloudflare_runtime_probe.py tools/cloudflare_continuity_ledger.py \
  tools/source_health_audit.py config/source-health-slo.yaml \
  .github/workflows/cloudflare-runtime-health.yml .github/workflows/source-health.yml \
  tests/tools/test_cloudflare_runtime_probe.py \
  tests/tools/test_cloudflare_continuity_ledger.py \
  tests/tools/test_cloudflare_runtime_health_workflow.py tests/unit/test_source_health_audit.py
git commit -m "feat(cloudflare): track production continuity SLOs"
```

---

### Task 8: Bind restore, documentation, and legacy stop lines

**Files:**
- Modify: `tools/cloudflare_restore_drill.py`
- Modify: `.github/workflows/cloudflare-restore-drill.yml`
- Modify: `tests/tools/test_cloudflare_restore_drill.py`
- Modify: `tests/tools/test_cloudflare_restore_drill_workflow.py`
- Modify: `docs/status.md`
- Modify: `docs/deployment/cloudflare-native-vps-removal.md`
- Modify: `docs/deployment/cloudflare-phase2-migration-runbook.md`
- Modify: `docs/external-integration-strategy.md`

**Interfaces:**
- Consumes current `build_restore_receipt(*, database, query_results, artifact_receipts, backup_receipt, require_artifact=True, generated_at=None) -> dict[str, Any]`.
- Adds required keyword arguments `expected_commit` and `continuity_receipt` to `build_restore_receipt()`.
- Consumes: exact deployed commit, latest committed real artifact, source and projection receipts, continuity ledger state.
- Produces: isolated restore receipt bound to the same commit and artifact; documentation promotion is allowed only for `slo_7d_passed` plus successful restore.
- Extends the existing test helper `_receipt(...)` with `expected_commit` and `continuity_receipt` keyword arguments; no second restore validator is introduced.

- [ ] **Step 1: Write RED restore/workflow tests**

```python
def test_restore_rejects_continuity_commit_mismatch(tmp_path: Path) -> None:
    receipt = _receipt(
        expected_commit="b" * 40,
        continuity_receipt={"status": "slo_7d_passed", "deployed_commit": "a" * 40},
    )
    assert receipt["status"] == "failed"
    assert "continuity_commit_mismatch" in receipt["summary"]["blockers"]

def test_restore_requires_real_committed_artifact_after_canary() -> None:
    receipt = _receipt(
        query_results=synthetic_only_query_results(),
        expected_commit="a" * 40,
        continuity_receipt={"status": "slo_7d_passed", "deployed_commit": "a" * 40},
    )
    assert "real_committed_artifact_missing" in receipt["summary"]["blockers"]
```

- [ ] **Step 2: Run RED tests**

```bash
.venv/bin/python -m pytest tests/tools/test_cloudflare_restore_drill.py tests/tools/test_cloudflare_restore_drill_workflow.py -q
```

Expected: FAIL because restore evidence is not yet bound to the continuity ledger state.

- [ ] **Step 3: Implement restore/SLO binding and documentation truth rules**

Require the same production commit across deployment, continuity ledger, artifact manifest, and restore receipt. Exclude synthetic Preview canaries from production recovery proof. Update status/runbooks with four distinct states: local implementation, Preview proof, 72h production canary, and 7d continuous healthy. Mark VPS/Tunnel/systemd and local SQLite/drafts as legacy/non-authoritative; RSS-Bridge may be used only as an external source adapter, never as a VPS runtime dependency.

- [ ] **Step 4: Run complete local verification and entry audit**

```bash
cd frontend/cloudflare
npm ci
npm test
npm run types
node_modules/.bin/wrangler deploy --env="" --dry-run \
  --outdir /tmp/ns-worker-production-continuity-dry-run --containers-rollout none
cd ../..
.venv/bin/python -m ruff check
.venv/bin/python -m mypy src/news_sentry/ --ignore-missing-imports
.venv/bin/python -m pytest tests/ -q --tb=short --timeout=300 --durations=25
.venv/bin/python tools/check_publication_hygiene.py
.venv/bin/python tools/scan_sensitive_data.py
.venv/bin/python tools/check_no_hardcoded_target.py
rg -n "importEventsToD1\(|markImportArtifactCommitted\(" \
  frontend/cloudflare/workers/api frontend/cloudflare/workers/lib/container-import.ts
git diff --check
```

Expected: all commands PASS; API/Container normal entrypoints delegate to the unified durable import path; documentation still says production is unproven until remote gates complete.

- [ ] **Step 5: Commit**

```bash
git add tools/cloudflare_restore_drill.py .github/workflows/cloudflare-restore-drill.yml \
  tests/tools/test_cloudflare_restore_drill.py tests/tools/test_cloudflare_restore_drill_workflow.py \
  docs/status.md docs/deployment/cloudflare-native-vps-removal.md \
  docs/deployment/cloudflare-phase2-migration-runbook.md docs/external-integration-strategy.md
git commit -m "docs(cloudflare): bind continuity to restore evidence"
```

---

## Promotion and Stop Conditions

Production dispatch is forbidden until Gate 0 Preview receipts are complete. After Tasks 1-8 are locally reviewed, production may advance only through:

1. Exact-main-SHA preflight and deploy receipt.
2. A bounded 4-target canary with 12 consecutive six-hour healthy receipts across 72 hours.
3. A real committed Container import artifact with matching R2 object, D1 manifest, source receipt, projection receipt, SHA-256, bytes, and event counts.
4. An isolated restore receipt for that production artifact.
5. Twenty-eight consecutive six-hour healthy receipts across 7 days while target batches expand gradually.

Stop or roll back on any dependency skip represented as success, freshness older than 2 hours, public freshness older than 24 hours, any future public timestamp, P0 DLQ item, backlog older than 30 minutes, missing artifact/receipt, restore failure, commit drift, or resource/account mismatch. Rollback may target only a previously verified production SHA and its matching D1/R2 evidence set; Preview resources, synthetic artifacts, VPS/Tunnel state, local SQLite, and branch-only commits are never production recovery sources.

## Self-Review Record

- **Spec coverage:** Tasks 1-4 close false-green scheduling, outcome, visibility, and timestamp gaps; Tasks 5-6 provide bounded low-cost production selection and deploy gates; Tasks 7-8 provide 72h/7d evidence, restore binding, and legacy stop lines.
- **Placeholder scan:** The plan contains no deferred implementation marker; every task has owned files, interfaces, RED test content, commands, implementation direction, GREEN validation, and commit scope.
- **Type consistency:** Status values are consistently `failed_dependency` and `empty_no_new_items`; continuity states are consistently `collecting_72h`, `canary_72h_passed`, `collecting_7d`, `slo_7d_passed`, and `failed`; all promotion evidence is keyed by `deployed_commit`.
