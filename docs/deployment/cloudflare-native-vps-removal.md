# News Sentry Cloudflare-native VPS Removal Runbook

> Status: active migration baseline, 2026-06-28.
> Goal: remove VPS from the runtime path while keeping the site fast, reliable, and operable.

## Decision

News Sentry production now treats Cloudflare as the infrastructure boundary:

- `news-sentry.com`: Cloudflare Pages public frontend.
- `api.news-sentry.com`: Cloudflare Worker API.
- `D1`: public event index, targets, sources, facets, import state.
- `R2`: raw payloads, generated Markdown, logs, backups, and evidence artifacts.
- `Queues` + `Cron Triggers` + `Workflows` or Durable Objects: collection scheduling and retryable pipeline orchestration.
- `Cloudflare Access`: admin, auth, runtime, import, and webhook write surfaces.
- `Cloudflare Containers`: transitional runtime for Python/FastAPI/RSS-Bridge paths that are too large to rewrite safely in one release.

VPS is not a runtime dependency. Cloudflare Tunnel to VPS is explicitly legacy rollback infrastructure, not Cloudflare-native production.
VPS systemd units, Tunnel state, VPS snapshots, local SQLite files, and local
`data/*/drafts` are non-authoritative for Cloudflare production recovery. They may
help humans audit or reconstruct context, but production recovery evidence must
come from a verified `main` SHA plus matching Cloudflare D1/R2 receipts.

## Performance-first Deployment Shape

The target is performance-first, not purity-first:

| Surface | Preferred runtime | Reason | Fallback |
| --- | --- | --- | --- |
| Public reader shell | Cloudflare Pages | Static assets close to users, low latency, simple cache behavior | none |
| Public news/facets/bootstrap/detail | Worker + D1 | High-frequency read path, low cold-start risk, fast SQL projections | none |
| Raw/evidence/Markdown artifacts | R2 | Object storage fits large immutable artifacts | none |
| Admin/config/runtime endpoints | Worker-native over D1/R2 when small | Keeps writes auditable and Access-gated | Cloudflare Containers |
| Existing Python pipeline and RSS-Bridge bridge | Cloudflare Containers during migration | Lowest-risk VPS removal for complex runtime code | rewrite to Worker/Queues/Workflows |
| Scheduled collection | Cron Triggers -> Queues -> Workflows/Durable Objects | Retryable, observable, avoids long synchronous HTTP work | Container worker job |

Use Worker-native for high-volume reads. Use Cloudflare Containers only where rewriting would increase outage risk or delay VPS removal.

## Cutover Gates

Do not shut down the VPS until all cutover gates pass:

1. `frontend/cloudflare/wrangler.toml` has no production `BACKEND_ORIGIN` or VPS hostname.
2. Worker dry-run passes:

   ```bash
   cd frontend/cloudflare
   npx wrangler deploy --env="" --dry-run --outdir /tmp/ns-worker-dry-run --containers-rollout none
   ```

3. Production deploy workflow contains no SSH, BWH, `/opt/news-sentry`, `/srv/news-sentry`, or systemd deployment step.
4. D1 schema migration succeeds:

   ```bash
   cd frontend/cloudflare
   npx wrangler d1 execute ns-db --remote --file=db/schema.sql
   ```

5. D1 data parity is checked from a current local export:

   ```bash
   python tools/cloudflare_d1_backfill.py \
     --data-dir data \
     --targets-dir config/targets \
     --output-sql /tmp/news-sentry-d1-backfill.sql
   cd frontend/cloudflare
   npx wrangler d1 execute ns-db --remote --file=/tmp/news-sentry-d1-backfill.sql
   ```

6. Cloudflare live receipt passes:

   ```bash
   curl -fsS https://api.news-sentry.com/api/v1/health
   curl -fsS "https://api.news-sentry.com/api/v1/public/news?page_size=3"
   curl -fsS https://api.news-sentry.com/api/v1/public/facets
   curl -fsS https://news-sentry.com/
   ```

7. Unauthenticated admin/write surfaces return Cloudflare Access protection:

   ```bash
   curl -i https://api.news-sentry.com/api/v1/admin/targets
   curl -i https://api.news-sentry.com/api/v1/events/import
   ```

8. Production import writes are R2-first and D1 is only the query projection:
   anonymous import returns 403, Access machine import returns 200, identical replay is idempotent,
   and D1 `artifact_manifests` / `import_batches` / `import_projection_finalize_receipts` cross-check
   against the committed R2 object key, SHA-256 and UTF-8 bytes.
9. A committed-artifact restore drill succeeds from production evidence artifacts, including
   source-fenced and projection-only receipt orphan/conflict checks, real non-synthetic artifact
   rows, and a continuity receipt whose `status=slo_7d_passed` and `deployed_commit` match the
   exact production `expected_commit`.
10. A 72-hour collector canary proves new events are written without VPS via 12 consecutive
    six-hour healthy receipts, followed by 7 days of continuous healthy evidence via 28 consecutive
    six-hour receipts.

## Production Stop Line

The durable import and Preview canary implementation is a candidate until exact production receipts
exist. Local tests, Wrangler dry-runs, Preview public health, Preview D1/R2 checks, or GitHub workflow
success do not prove production recovery.

Use four separate promotion states:

1. Local implementation: code, tests, lint/typecheck/build, and dry-runs only.
2. Preview proof: isolated Preview deploy/canary/restore receipts for the exact candidate SHA only.
3. 72h production canary: 12 consecutive six-hour healthy production receipts for the exact `main`
   SHA, plus real committed artifact evidence.
4. 7d continuous healthy: 28 consecutive six-hour healthy production receipts, `slo_7d_passed`
   continuity ledger, and an isolated restore receipt bound to the same commit and real artifact.

Only state 4 permits documentation to say continuous Cloudflare production recovery is proven.
Synthetic Preview artifacts, branch-only commits, VPS/Tunnel/systemd state, local SQLite, and local
draft files never satisfy that promotion requirement.

Stop before production deploy unless all of these are true:

- PR review and explicit production release authorization are complete.
- The final `main` SHA is known and passed the required local, CI and security checks.
- Production has its own Cloudflare Access application, audience and Service Token; Preview
  `CF_ACCESS_AUD`, `CF_ACCESS_SERVICE_TOKEN_IDS`, `CF_ACCESS_CLIENT_ID` and
  `CF_ACCESS_CLIENT_SECRET` are not reused.
- Production `deploy.yml` is manually dispatched from `refs/heads/main` with matching
  `expected_commit`.
- The deployment plan includes rollback evidence and a post-deploy canary window.

Until those conditions are met, production remains untouched. The known false-green/stale-data warning
in `docs/status.md` remains authoritative even when `/api/v1/health` returns `200`.

## Deployment Notes

- The Worker public read path must stay Worker + D1. Do not proxy public reads to a container.
- The container path is Access-gated and fail-closed. If the container binding is missing, the Worker returns an error instead of falling back to any external origin.
- GitHub Actions does not usually contain the full local `data/*/state.db` tree. Treat CI backfill as a dry-run/contract check unless a trusted data artifact is explicitly attached.
- `CLOUDFLARE_STATE_JSON` remains required for production deployed-surface audit. Temporary bypasses are removed from the production workflow.
- Phase 4 D1 changes are append-only. Do not rewrite historical migrations or remove
  `runtime_migration_receipts` to force a rerun.
- Restore drill receipts must be secret-free: upload only the sanitized receipt, never raw SQL
  exports, raw import artifacts, request headers, Service Tokens, continuity JSON beyond the
  sanitized status/commit summary, or local file paths.

## VPS Decommission

After all cutover gates pass:

1. Freeze old VPS collectors and timers.
2. Run one final D1/R2 backfill from the newest approved source export; local SQLite may seed the
   backfill but does not become production truth until D1/R2 receipts and restore evidence pass.
3. Remove Cloudflare Tunnel public hostnames for `news-sentry.com` and `preview.news-sentry.com`.
4. Remove GitHub repository secrets for VPS SSH deployment.
5. Snapshot the VPS for rollback evidence.
6. Stop News Sentry systemd services.
7. Keep the snapshot for 7-14 days, then destroy the VPS if no rollback signal appears.

## Rollback Boundary

Rollback is allowed only to a previously verified `main` production SHA and its matching D1/R2 evidence
set. Do not roll production back to Preview resources, synthetic Preview artifacts, or a branch-only
candidate SHA. Do not declare rollback complete from VPS/Tunnel/systemd state, local SQLite, or local
draft directories alone.

If production durable import canary fails after deploy:

1. Stop further import writes by disabling the production release path or Access policy that allowed
   the canary identity.
2. Preserve D1/R2 receipts, Worker version metadata, Pages deploy URL and workflow artifacts.
3. Re-dispatch the last verified production SHA through the same `production` environment gate, or
   restore the legacy rollback surface only if its snapshot and tunnel state were preserved.
4. Re-run anonymous 403, machine import, idempotent replay, D1/R2 cross-check, public read health and
   restore drill before declaring rollback complete.

Rollback does not close the production false-green issue by itself. Fresh collector and SLO evidence
are still required before decommissioning VPS fallback or claiming continuous acquisition is restored.
