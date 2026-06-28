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

8. A 24-72 hour collector receipt proves new events are written without VPS.

## Deployment Notes

- The Worker public read path must stay Worker + D1. Do not proxy public reads to a container.
- The container path is Access-gated and fail-closed. If the container binding is missing, the Worker returns an error instead of falling back to any external origin.
- GitHub Actions does not usually contain the full local `data/*/state.db` tree. Treat CI backfill as a dry-run/contract check unless a trusted data artifact is explicitly attached.
- `CLOUDFLARE_STATE_JSON` remains required for production deployed-surface audit. Temporary bypasses are removed from the production workflow.

## VPS Decommission

After all cutover gates pass:

1. Freeze old VPS collectors and timers.
2. Run one final D1/R2 backfill from the newest local or exported state.
3. Remove Cloudflare Tunnel public hostnames for `news-sentry.com` and `preview.news-sentry.com`.
4. Remove GitHub repository secrets for VPS SSH deployment.
5. Snapshot the VPS for rollback evidence.
6. Stop News Sentry systemd services.
7. Keep the snapshot for 7-14 days, then destroy the VPS if no rollback signal appears.
