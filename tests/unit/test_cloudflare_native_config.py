"""Cloudflare-native deployment contract tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_DIR = ROOT / "frontend" / "cloudflare"


def _read(path: str) -> str:
    return (CLOUDFLARE_DIR / path).read_text(encoding="utf-8")


def test_wrangler_routes_are_top_level_not_nested_under_d1() -> None:
    config = tomllib.loads(_read("wrangler.toml"))

    assert config["routes"] == [
        {"pattern": "api.news-sentry.com", "custom_domain": True},
        {"pattern": "news-sentry.com/api/*", "zone_name": "news-sentry.com"},
    ]
    assert "production" not in config["env"]
    assert config["env"]["dev"]["routes"] == []
    for binding in config["d1_databases"]:
        assert "routes" not in binding


def test_preview_worker_uses_isolated_state_and_no_active_runtime_bindings() -> None:
    config = tomllib.loads(_read("wrangler.toml"))
    preview = config["env"]["preview"]

    assert preview["routes"] == []
    assert preview["workers_dev"] is True
    assert preview["vars"] == {
        "NEWS_SENTRY_RUNTIME": "cloudflare-native-preview",
        "NEWS_SENTRY_ENVIRONMENT": "preview",
        "SCHEDULER_MODE": "shadow",
        "WORKER_NATIVE_COLLECT_ENABLED": "false",
    }
    assert preview["d1_databases"] == [
        {
            "binding": "DB",
            "database_name": "ns-db-preview",
            "database_id": "00000000-0000-4000-8000-000000000000",
        }
    ]
    assert preview["queues"] == {"producers": [], "consumers": []}
    assert preview["durable_objects"] == {"bindings": []}
    assert preview["containers"] == []
    assert preview["secrets"] == {"required": []}


def test_preview_worker_config_keeps_access_secret_out_of_static_worker_vars() -> None:
    config = tomllib.loads(_read("wrangler.toml"))
    preview = config["env"]["preview"]
    preview_vars = preview["vars"]

    assert "CF_ACCESS_CLIENT_SECRET" not in preview_vars
    assert "CF_ACCESS_CLIENT_ID" not in preview_vars
    assert preview["d1_databases"] == [
        {
            "binding": "DB",
            "database_name": "ns-db-preview",
            "database_id": "00000000-0000-4000-8000-000000000000",
        }
    ]
    assert preview["r2_buckets"] == [
        {
            "binding": "NEWS_SENTRY_ARTIFACTS",
            "bucket_name": "news-sentry-artifacts-preview",
        }
    ]
    assert preview["queues"] == {"producers": [], "consumers": []}
    assert preview["durable_objects"] == {"bindings": []}
    assert preview["triggers"] == {"crons": []}
    assert preview["containers"] == []


def test_deploy_workflow_verifies_apex_api_worker_route() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "APEX_API_URL: https://news-sentry.com" in deploy_yml
    assert '"${APEX_API_URL}/api/v1/health" > /tmp/apex-health.json' in deploy_yml
    assert "apex_health = json.loads" in deploy_yml
    assert 'apex_health.get("status") == "ok"' in deploy_yml
    assert (
        'apex_health.get("deployment", {}).get("commit") == os.environ["GITHUB_SHA"]'
        in deploy_yml
    )


def test_deploy_workflow_requires_access_config_and_deployment_receipts() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    workflow = yaml.load(
        deploy_yml,
        Loader=yaml.BaseLoader,  # noqa: S506 - preserves GitHub's `on` key.
    )
    deploy_steps = workflow["jobs"]["deploy-cloudflare-worker"]["steps"]
    worker_health = next(
        step["run"]
        for step in deploy_steps
        if step.get("name") == "Verify Cloudflare Worker health"
    )

    assert "Cloudflare Worker behavior tests" in deploy_yml
    assert "run: npm test" in deploy_yml
    assert "VITE_API_BASE: https://api.news-sentry.com" in deploy_yml
    assert (
        "VITE_API_BASE: ${{ needs.ci.outputs.deployment_environment == 'preview' &&"
        in deploy_yml
    )
    assert "CF_ACCESS_TEAM_DOMAIN: ${{ vars.CF_ACCESS_TEAM_DOMAIN }}" in deploy_yml
    assert "CF_ACCESS_AUD: ${{ vars.CF_ACCESS_AUD }}" in deploy_yml
    assert '--var "NEWS_SENTRY_DEPLOY_COMMIT:${GITHUB_SHA}"' in deploy_yml
    assert '--var "CF_ACCESS_TEAM_DOMAIN:${CF_ACCESS_TEAM_DOMAIN}"' in deploy_yml
    assert '--var "CF_ACCESS_AUD:${CF_ACCESS_AUD}"' in deploy_yml
    assert '"https://news-sentry.com/api/v1/live"' in worker_health
    assert '"https://news-sentry.com/api/v1/ready"' in worker_health
    assert '"https://api.news-sentry.com/api/v1/live"' not in worker_health
    assert '"https://api.news-sentry.com/api/v1/ready"' not in worker_health
    assert 'headers.get("x-news-sentry-deploy-commit") == os.environ["GITHUB_SHA"]' in deploy_yml
    assert 'headers.get("x-news-sentry-worker-version")' in deploy_yml
    assert "falling back to D1 smoke check" not in deploy_yml
    assert "validating D1 data via Wrangler" not in deploy_yml
    assert "Apply Cloudflare D1 shadow job runtime migration" in deploy_yml
    assert "20260801_phase1_job_runtime.sql" in deploy_yml


def test_deploy_workflow_applies_phase5_before_runtime_receipt_recording() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    schema_step = deploy_yml.index("Apply Cloudflare D1 schema")
    phase5_step = deploy_yml.index("20260802_phase5_future_event_quarantine.sql")
    record_step = deploy_yml.index("Record Cloudflare D1 runtime migration receipts")
    snapshot_step = deploy_yml.index("Refresh Cloudflare public read snapshots")

    assert schema_step < phase5_step < record_step < snapshot_step


def test_preview_workflow_applies_phase5_after_schema_before_seed() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["deploy-cloudflare-preview-worker"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Apply Cloudflare preview D1 schema and seed"
    )

    schema_file = script.index("--file=db/schema.sql")
    phase5_file = script.index("20260802_phase5_future_event_quarantine.sql")
    seed_file = script.index("--file=/tmp/news-sentry-preview-seed.sql")

    assert schema_file < phase5_file < seed_file


def test_worker_health_verification_shell_is_syntactically_valid() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["deploy-cloudflare-worker"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Verify Cloudflare Worker health"
    )

    result = subprocess.run(
        ["/bin/bash", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_preview_worker_and_verify_shell_are_syntactically_valid() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    )
    scripts = []
    for job_name, step_name in (
        ("deploy-cloudflare-preview-worker", "Resolve Cloudflare preview D1"),
        ("deploy-cloudflare-preview-worker", "Prepare Cloudflare preview config and seed"),
        ("deploy-cloudflare-preview-worker", "Deploy Cloudflare preview Worker"),
        ("deploy-cloudflare-pages", "Verify preview frontend API binding"),
        ("deploy-cloudflare-pages", "Deploy Cloudflare Pages"),
        ("verify-preview", "Verify preview Cloudflare-native public endpoints"),
    ):
        steps = workflow["jobs"][job_name]["steps"]
        scripts.append(next(step["run"] for step in steps if step.get("name") == step_name))

    for script in scripts:
        result = subprocess.run(
            ["/bin/bash", "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_deployment_mode_gate_requires_explicit_exact_production_commit(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["ci"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Resolve and validate deployment mode"
    )

    sha = "a" * 40
    cases = (
        ("push", "refs/heads/main", "", "", 1, ""),
        ("push", "refs/heads/preview", "", "", 0, "environment=preview"),
        (
            "workflow_dispatch",
            "refs/heads/feature",
            "preview",
            "",
            0,
            "environment=preview",
        ),
        (
            "workflow_dispatch",
            "refs/heads/main",
            "production",
            sha,
            0,
            "environment=production",
        ),
        ("workflow_dispatch", "refs/heads/main", "production", "", 1, ""),
        ("workflow_dispatch", "refs/heads/main", "production", "b" * 40, 1, ""),
        ("workflow_dispatch", "refs/heads/feature", "production", sha, 1, ""),
    )
    for index, (
        event,
        ref,
        requested,
        expected_commit,
        expected_code,
        expected_output,
    ) in enumerate(cases):
        output = tmp_path / f"github-output-{index}.txt"
        result = subprocess.run(
            ["/bin/bash"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "GITHUB_EVENT_NAME": event,
                "GITHUB_REF": ref,
                "GITHUB_SHA": sha,
                "REQUESTED_ENVIRONMENT": requested,
                "EXPECTED_COMMIT": expected_commit,
                "GITHUB_OUTPUT": str(output),
            },
        )
        assert result.returncode == expected_code, result.stderr
        actual_output = output.read_text(encoding="utf-8") if output.exists() else ""
        assert expected_output in actual_output


def test_worker_health_reads_cloudflare_d1_events_table() -> None:
    health_ts = _read("workers/api/health.ts")

    assert "FROM events" in health_ts
    assert "event_index" not in health_ts
    assert "public_quality" in health_ts
    assert "summary_ready" in health_ts
    assert "recommendation_ready" in health_ts
    assert "featured_total" in health_ts
    assert "latest_public_at" in health_ts
    assert "source_runtime_state" in health_ts
    assert "job_outbox" in health_ts
    assert 'mode: "shadow"' in health_ts
    assert "p0_dead_lettered" in health_ts
    assert "non_p0_dead_lettered" in health_ts


def test_public_facets_contract_includes_related_tags() -> None:
    contracts_ts = _read("workers/lib/contracts.ts")
    facets_ts = _read("workers/api/facets.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")

    public_facets = re.search(
        r"export interface PublicFacetsResponse \{(?P<body>.*?)\n\}",
        contracts_ts,
        re.DOTALL,
    )
    assert public_facets is not None
    assert "related: PublicFacetItem[]" in public_facets.group("body")
    assert "json_each(events.related_tags)" in facets_ts
    assert "related:" in facets_ts
    assert "json_each(events.related_tags)" in bootstrap_ts
    assert "related:" in bootstrap_ts


def test_public_news_supports_related_filter() -> None:
    news_ts = _read("workers/api/news.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    assert 'params.get("related")' in news_ts
    assert "related_tags LIKE ?" in query_ts


def test_public_reader_uses_drafts_stage_like_python_reader() -> None:
    news_ts = _read("workers/api/news.ts")
    facets_ts = _read("workers/api/facets.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    for worker_source in (news_ts, facets_ts, bootstrap_ts, query_ts):
        assert "pipeline_stage = 'drafts'" in worker_source
        assert "pipeline_stage IN ('published', 'reviewed')" not in worker_source

    assert "total: newsCountResult?.total ?? newsRows.length" in bootstrap_ts


def test_dlq_replay_endpoint_is_worker_local_and_access_protected() -> None:
    index_ts = _read("workers/index.ts")
    access_ts = _read("workers/lib/access.ts")
    replay_ts = _read("workers/api/dlq-replay.ts")
    job_store_ts = _read("workers/lib/job-store.ts")
    queue_ts = _read("workers/lib/queue-shadow.ts")

    assert 'registerRoute("POST", "/api/v1/jobs/dlq/replay", handleDlqReplay)' in index_ts
    assert '"/api/v1/jobs/dlq/replay"' in access_ts
    assert "verifyCloudflareAccessRequest" not in replay_ts
    assert "dlq_replay_receipts" in job_store_ts
    assert "replay_of_job_id" in job_store_ts
    assert "crypto.randomUUID" in job_store_ts
    assert "dlq_consumption_receipts" in job_store_ts
    assert "recordDlqConsumptionReceipt" in queue_ts


def test_cloudflare_public_featured_query_matches_python_quality_gate() -> None:
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    assert 'params.get("featured") === "true"' in news_ts
    assert 'params.get("featured") !== "false"' in bootstrap_ts
    assert "PUBLIC_FEATURED_MIN_SCORE = 60" in query_ts
    assert "PUBLIC_BREAKING_MIN_SCORE = 60" in query_ts
    assert "breaking_score >= ?" in query_ts
    assert "value_score >= ?" in query_ts
    assert "summary IS NOT NULL" in query_ts
    assert "TRIM(summary) != ''" in query_ts
    assert "recommendation_reason IS NOT NULL" in query_ts
    assert "TRIM(recommendation_reason) != ''" in query_ts
    assert "json_valid(classification) = 1" in query_ts
    assert "json_extract(classification, '$.l0')" in query_ts
    assert "NOT IN ('uncategorized', 'other', 'breaking_news')" in query_ts
    assert "NOT LIKE '%/opinion/todayinhistory/%'" in query_ts
    assert "UPPER(TRIM(title)) LIKE 'MONDAY, %'" in query_ts
    assert (
        "ORDER BY events.breaking_score DESC, events.published_at DESC, events.event_id DESC"
        in query_ts
    )
    assert "publicNewsOrderBy(featured)" in news_ts
    assert "publicNewsOrderBy(featured)" in bootstrap_ts


def test_cloudflare_breaking_intelligence_contract_is_schema_backed() -> None:
    schema_sql = _read("db/schema.sql")
    query_ts = _read("workers/lib/public-news-query.ts")
    contracts_ts = _read("workers/lib/contracts.ts")

    for column in (
        "breaking_score REAL",
        "breaking_label TEXT",
        "breaking_reason TEXT",
        "breaking_confidence INTEGER",
        "breaking_dimensions TEXT DEFAULT '{}'",
        "breaking_score_version TEXT",
        "target_timezone TEXT DEFAULT 'UTC'",
        "published_at_local TEXT",
    ):
        assert column in schema_sql

    assert "CREATE TABLE IF NOT EXISTS event_localizations" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS breaking_score_stats" in schema_sql
    assert "idx_events_public_breaking" in schema_sql
    assert "idx_event_localizations_locale" in schema_sql
    assert "breaking_score >= ?" in query_ts
    assert (
        "ORDER BY events.breaking_score DESC, events.published_at DESC, events.event_id DESC"
        in query_ts
    )

    for field in (
        "breakingScore?: number | null",
        "breakingLabel?:",
        "breakingReason?: string | null",
        "breakingConfidence?: number | null",
        "breakingDimensions?: Record<string, number>",
        "targetTimezone?: string | null",
        "publishedAtLocal?: string | null",
        "availableLocales?: string[]",
    ):
        assert field in contracts_ts


def test_cloudflare_public_reads_are_locale_aware_without_breaking_shape() -> None:
    news_ts = _read("workers/api/news.ts")
    query_ts = _read("workers/lib/public-news-query.ts")
    snapshots_ts = _read("workers/lib/public-read-snapshots.ts")

    assert 'params.get("locale")' in news_ts
    assert "localeFromRequest" in news_ts
    assert "Content-Language" in news_ts
    assert "X-News-Sentry-Locale" in news_ts
    assert "X-News-Sentry-Breaking-Version" in news_ts
    assert "event_localizations" in query_ts
    assert "locale=zh" in snapshots_ts
    assert "locale=en" in snapshots_ts
    assert "locale=es" in snapshots_ts
    assert "locale=ar" in snapshots_ts
    assert "locale=fr" in snapshots_ts


def test_cloudflare_has_ninety_day_retention_and_cost_guards() -> None:
    scheduled_ts = _read("workers/lib/scheduled.ts")
    wrangler_toml = _read("wrangler.toml")

    assert "retention-cycle" in scheduled_ts
    assert "deleteExpiredPublicData" in scheduled_ts
    assert "90" in scheduled_ts
    assert "cost-audit-cycle" in scheduled_ts
    assert "cloudflare_budget" in scheduled_ts
    assert "23 * * * *" in wrangler_toml


def test_cloudflare_public_news_uses_sql_cursor_pagination() -> None:
    news_ts = _read("workers/api/news.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    assert "buildCursorFilter" in news_ts
    assert 'params.get("before_cursor")' in news_ts
    assert 'params.get("since_cursor")' in news_ts
    assert (
        "SELECT event_id, published_at, value_score, breaking_score FROM events WHERE event_id = ?"
        in news_ts
    )
    assert "${cursorFilter.sql}" in news_ts
    assert "SELECT COUNT(*) AS total FROM events ${filters.sql}" in news_ts
    assert "Number.isFinite(requestedPageSize)" in news_ts
    assert "const pageRows = rows.slice(0, pageSize)" in news_ts
    assert "const items = pageRows.map" in news_ts
    assert "hasNewer: Boolean(sinceCursor && items.length > 0)" in news_ts
    assert "ORDER BY events.published_at DESC, events.event_id DESC" in query_ts


def test_cloudflare_d1_has_public_featured_index() -> None:
    schema_sql = _read("db/schema.sql")

    assert "idx_events_public_featured" in schema_sql
    assert "events(pipeline_stage, value_score DESC, published_at DESC)" in schema_sql


def test_cloudflare_d1_has_public_read_snapshot_table() -> None:
    schema_sql = _read("db/schema.sql")

    assert "CREATE TABLE IF NOT EXISTS public_read_snapshots" in schema_sql
    for column in (
        "key TEXT PRIMARY KEY",
        "payload_json TEXT NOT NULL",
        "generated_at TEXT NOT NULL",
        "source_latest_public_at TEXT",
        "item_count INTEGER DEFAULT 0",
        "payload_bytes INTEGER DEFAULT 0",
    ):
        assert column in schema_sql


def test_cloudflare_bootstrap_reports_matching_featured_total() -> None:
    bootstrap_ts = _read("workers/api/bootstrap.ts")

    assert "SELECT COUNT(*) AS total FROM events ${newsFilters.sql}" in bootstrap_ts
    assert "total: newsCountResult?.total ?? newsRows.length" in bootstrap_ts


def test_cloudflare_public_read_endpoints_use_worker_cache_and_head() -> None:
    index_ts = _read("workers/index.ts")
    router_ts = _read("workers/lib/router.ts")
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    facets_ts = _read("workers/api/facets.ts")
    targets_ts = _read("workers/api/targets.ts")
    cache_ts = _read("workers/lib/public-read-cache.ts")

    assert "ctx: ExecutionContext" in index_ts
    assert "runtimeMetadata(env, workerWriteAccess.identity)" in index_ts
    assert "{ artifacts: env.NEWS_SENTRY_ARTIFACTS }" in index_ts
    assert "rawMethod === \"HEAD\"" in router_ts
    assert "new Response(null" in router_ts
    assert "maybeServeCachedPublicRead" in news_ts
    assert "maybeStoreCachedPublicRead" in news_ts
    assert "X-News-Sentry-Worker-Cache" in cache_ts
    assert "PUBLIC_READ_CACHE_VERSION" in cache_ts
    assert "public-read:news:${featured ? \"featured\" : \"all\"}:page_size=${pageSize}" in news_ts
    assert "public-read:bootstrap:featured" in bootstrap_ts
    assert "public-read:facets" in facets_ts
    assert "public-read:regions" in targets_ts
    assert "publicReadCacheControl" in cache_ts
    assert "s-maxage" in cache_ts
    assert "stale-while-revalidate" in cache_ts
    assert "stale-if-error" in cache_ts


def test_cloudflare_public_read_endpoints_use_snapshots_before_queries() -> None:
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    facets_ts = _read("workers/api/facets.ts")
    targets_ts = _read("workers/api/targets.ts")
    snapshots_ts = _read("workers/lib/public-read-snapshots.ts")
    session_ts = _read("workers/lib/public-read-session.ts")

    assert "readPublicSnapshot" in news_ts
    assert "newsFeaturedSnapshotKey" in news_ts
    assert "newsAllSnapshotKey" in news_ts
    assert "readPublicSnapshot" in bootstrap_ts
    assert "bootstrapFeaturedSnapshotKey" in bootstrap_ts
    assert "readPublicSnapshot" in facets_ts
    assert "FACETS_SNAPSHOT_KEY" in facets_ts
    assert "readPublicSnapshot" in targets_ts
    assert "REGIONS_ACTIVE_SNAPSHOT_KEY" in targets_ts

    for key in (
        "news:featured:v1:page_size=20",
        "news:all:v1:page_size=20",
        "bootstrap:featured:v1:page_size=20",
        "facets:v1",
        "regions:active:v1",
    ):
        assert key in snapshots_ts

    assert "X-News-Sentry-Snapshot" in snapshots_ts
    assert 'withSession("first-unconstrained")' in session_ts
    assert "createPublicReadSession" in session_ts
    assert "PUBLIC_SNAPSHOT_PAGE_SIZE = 20" in snapshots_ts
    assert "slicePublicNewsSnapshot" in snapshots_ts
    assert "sliceBootstrapSnapshot" in snapshots_ts
    assert "readPublicSnapshotPayload" in snapshots_ts
    assert "LIMIT 21" in snapshots_ts
    assert "const pageRows = rows.slice(0, PUBLIC_SNAPSHOT_PAGE_SIZE)" in snapshots_ts
    assert "rows.length > PUBLIC_SNAPSHOT_PAGE_SIZE" in snapshots_ts


def test_cloudflare_small_default_news_requests_reuse_twenty_item_snapshots() -> None:
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")

    assert "pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE" in news_ts
    assert "pageSize <= PUBLIC_SNAPSHOT_PAGE_SIZE" in bootstrap_ts
    assert "slicePublicNewsSnapshot" in news_ts
    assert "sliceBootstrapSnapshot" in bootstrap_ts
    assert "readPublicSnapshotPayload<PublicNewsFeedResponse>" in news_ts
    assert "readPublicSnapshotPayload<PublicBootstrapResponse>" in bootstrap_ts
    assert (
        "`public-read:news:${featured ? \"featured\" : \"all\"}:page_size=${pageSize}`"
        in news_ts
    )
    assert "public-read:bootstrap:featured:page_size=${pageSize}" in bootstrap_ts
    assert "locale=${locale}" in bootstrap_ts


def test_cloudflare_scheduled_refreshes_public_read_snapshots() -> None:
    scheduled_ts = _read("workers/lib/scheduled.ts")

    assert "refreshPublicReadSnapshots" in scheduled_ts
    assert "await refreshPublicReadSnapshots(env.DB)" in scheduled_ts


def test_cloudflare_scheduled_ops_are_configured() -> None:
    index_ts = _read("workers/index.ts")
    scheduled_ts = _read("workers/lib/scheduled.ts")
    container_import_ts = _read("workers/lib/container-import.ts")
    schema_sql = _read("db/schema.sql")
    migration_sql = _read("db/migrations/20260630_add_target_collect_enabled.sql")
    wrangler_toml = tomllib.loads(_read("wrangler.toml"))

    assert "async scheduled(" in index_ts
    assert "runScheduledCloudflareTask" in index_ts
    assert 'NEWSSENTRY_COLLECT_STAGE: "all"' in index_ts
    assert "collect-cycle" in scheduled_ts
    assert "public-translation-cycle" in scheduled_ts
    assert "refresh-public-quality" in scheduled_ts
    assert "ops_state" in schema_sql
    assert "ops_runs" in schema_sql
    assert "lock_until" in schema_sql
    assert "cloudflare_collect_enabled INTEGER NOT NULL DEFAULT 1" in schema_sql
    assert "ALTER TABLE targets ADD COLUMN cloudflare_collect_enabled" in migration_sql
    assert wrangler_toml["triggers"]["crons"] == [
        "*/15 * * * *",
        "7,37 * * * *",
        "11 * * * *",
        "23 * * * *",
        "53 */6 * * *",
    ]
    assert 'compactDetails.status === "string"' in scheduled_ts
    assert "await recordRun(env.DB, runId, task, status" in scheduled_ts
    assert "executeDurableProjectionImport" in container_import_ts
    assert "importEventsToD1" not in container_import_ts
    assert "extractContainerImportEvents" in container_import_ts
    assert "importContainerEventsToD1" in scheduled_ts
    assert "import_result" in scheduled_ts
    assert "result.updated" in container_import_ts
    assert "persistImportArtifact" not in container_import_ts
    assert "COLLECT_TARGET_BATCH_SIZE = 4" in scheduled_ts
    assert "cursor:collect-cycle-target-index" in scheduled_ts
    assert "cloudflare_collect_enabled = 1" in scheduled_ts
    assert "CONTAINER_TASK_TIMEOUT_MS = 8 * 60_000" in scheduled_ts
    assert 'CONTAINER_WRITER_LOCK_NAME = "container-sqlite-writer"' in scheduled_ts
    assert "loadCollectTargetBatch" in scheduled_ts
    assert "persistCollectTargetCursor" in scheduled_ts
    assert "recordRunStarted" in scheduled_ts
    assert "targetIds" in scheduled_ts
    assert "compactTaskDetails({" in scheduled_ts
    assert "updates_count" in scheduled_ts
    assert "target_results" in scheduled_ts
    assert "/api/v1/internal/cloudflare/${task}" in scheduled_ts
    assert '"X-News-Sentry-Internal-Task": task' in scheduled_ts
    assert "isContainerNotRunningError" in scheduled_ts
    assert "waitForContainerRetryDelay" in scheduled_ts
    assert "auto_fetch" in scheduled_ts
    assert "auto_fetch_retry_${attempt}" in scheduled_ts
    assert "container_timeout_ms" in scheduled_ts
    assert "failed_retryable" in scheduled_ts
    assert "database_locked" in scheduled_ts
    assert "task_mode: \"public_refresh\"" in scheduled_ts
    assert "pipeline_stage: \"all\"" in scheduled_ts
    assert "collectBatchDetails" in scheduled_ts


def test_deploy_workflow_migrates_breaking_columns_before_schema_indexes() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    migration_step = deploy_yml.index("Apply Cloudflare D1 breaking intelligence migration")
    schema_step = deploy_yml.index("Apply Cloudflare D1 schema")

    assert migration_step < schema_step
    assert "SELECT breaking_score FROM events LIMIT 1" in deploy_yml
    assert "no such table: events" in deploy_yml
    assert "20260701_breaking_intelligence_i18n.sql" in deploy_yml


def test_cloudflare_worker_observability_is_enabled() -> None:
    wrangler_toml = tomllib.loads(_read("wrangler.toml"))

    observability = wrangler_toml["observability"]
    assert observability["enabled"] is True
    assert observability["head_sampling_rate"] == 0.1
    assert observability["logs"]["enabled"] is True
    assert observability["logs"]["invocation_logs"] is True
    assert observability["logs"]["persist"] is True
    assert observability["traces"]["enabled"] is True
    assert observability["traces"]["persist"] is True


def test_cloudflare_worker_exposes_public_targets_and_regions_contracts() -> None:
    index_ts = _read("workers/index.ts")
    targets_ts = _read("workers/api/targets.ts")
    contracts_ts = _read("workers/lib/contracts.ts")

    assert '"/api/v1/targets"' in index_ts
    assert '"/api/v1/regions"' in index_ts
    assert "FROM targets" in targets_ts
    assert "TargetListResponse" in contracts_ts
    assert "RegionListResponse" in contracts_ts
    assert "include_empty" in targets_ts


def test_events_import_uses_unified_durable_projection_import() -> None:
    webhook_ts = _read("workers/api/webhook.ts")
    handle_import_ts = webhook_ts[webhook_ts.index("export async function handleImport") :]

    assert "db: D1Database" in webhook_ts
    assert "executeDurableProjectionImport" in handle_import_ts
    assert "importEventsToD1" not in handle_import_ts
    assert "INSERT INTO events" not in handle_import_ts
    assert "batch_id" in handle_import_ts
    assert "artifact_sha256" in handle_import_ts
    assert "updated" in handle_import_ts


def test_container_proxy_requires_cloudflare_access_identity() -> None:
    index_ts = _read("workers/index.ts")
    access_ts = _read("workers/lib/access.ts")
    access_jwt_ts = _read("workers/lib/access-jwt.ts")
    proxy_ts = _read("workers/api/proxy.ts")
    wrangler_toml = tomllib.loads(_read("wrangler.toml"))

    assert "shouldProxyToContainer" in index_ts
    assert "handleContainerProxy(request, env)" in index_ts
    assert "NewsSentryContainer" in index_ts
    assert "defaultPort = 8000" in index_ts
    assert "requiredPorts = [8000]" in index_ts
    assert '"/api/v1/admin/"' in access_ts
    assert '"/api/v1/auth/"' in access_ts
    assert "/api/v1/internal/cloudflare" not in access_ts
    assert "verifyCloudflareAccessRequest" in proxy_ts
    assert '"Cf-Access-Jwt-Assertion"' in access_jwt_ts
    assert 'header.alg !== "RS256"' in access_jwt_ts
    assert "issuer_mismatch" in access_jwt_ts
    assert "audience_mismatch" in access_jwt_ts
    assert 'claims.email !== "string"' in access_jwt_ts
    assert 'headers.set("Cf-Access-Authenticated-User-Email", access.principal.email' in proxy_ts
    assert '"CF-Access-Client-Id"' not in access_ts
    assert "Cloudflare Access authentication required" in access_ts
    assert "NEWS_SENTRY_CONTAINER" in proxy_ts
    assert "getContainer(env.NEWS_SENTRY_CONTAINER" in proxy_ts
    assert "BACKEND_ORIGIN" not in proxy_ts
    assert "https://news-sentry.com" not in _read("wrangler.toml")
    assert "BACKEND_ORIGIN" not in wrangler_toml.get("vars", {})
    assert wrangler_toml["containers"][0]["class_name"] == "NewsSentryContainer"
    assert wrangler_toml["containers"][0]["image"] == "../../Dockerfile"
    assert wrangler_toml["durable_objects"]["bindings"][0] == {
        "name": "NEWS_SENTRY_CONTAINER",
        "class_name": "NewsSentryContainer",
    }


def test_production_cloudflare_config_has_no_vps_origin_fallback() -> None:
    wrangler_text = _read("wrangler.toml")
    index_ts = _read("workers/index.ts")
    proxy_ts = _read("workers/api/proxy.ts")

    forbidden = [
        "BACKEND_ORIGIN",
        "BWH",
        "BWH_HOST",
        "BWH_SSH",
        "174.137.51.201",
        "systemd",
        "ssh-action",
        "https://news-sentry.com",
    ]
    combined = "\n".join([wrangler_text, index_ts, proxy_ts])
    for token in forbidden:
        assert token not in combined


def test_cloudflare_container_profile_exists_for_worker_env() -> None:
    profile = (
        ROOT / "config/profiles/cloudflare.yaml"
    ).read_text(encoding="utf-8")

    assert "profile_id: cloudflare" in profile
    assert "trigger: scheduled" in profile
    assert "profile: cloud-vps" in profile


def test_cloudflare_package_deploy_prod_targets_custom_domain_worker() -> None:
    package_json = json.loads((CLOUDFLARE_DIR / "package.json").read_text(encoding="utf-8"))

    assert package_json["scripts"]["deploy:prod"] == 'wrangler deploy --env=""'


def test_cloudflare_wrangler_is_pinned_to_a_non_vulnerable_release() -> None:
    package_json = json.loads((CLOUDFLARE_DIR / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (CLOUDFLARE_DIR / "package-lock.json").read_text(encoding="utf-8")
    )

    expected_version = "4.114.0"
    assert package_json["devDependencies"]["wrangler"] == expected_version
    assert package_lock["packages"][""]["devDependencies"]["wrangler"] == expected_version
    assert package_lock["packages"]["node_modules/wrangler"]["version"] == expected_version


def test_cloudflare_artifact_storage_is_isolated_and_manifested() -> None:
    wrangler = tomllib.loads(_read("wrangler.toml"))
    schema_sql = _read("db/schema.sql")
    migration_sql = _read("db/migrations/20260802_phase3_durable_artifacts.sql")

    assert wrangler["r2_buckets"] == [
        {
            "binding": "NEWS_SENTRY_ARTIFACTS",
            "bucket_name": "news-sentry-artifacts",
        }
    ]
    assert wrangler["env"]["preview"]["r2_buckets"] == [
        {
            "binding": "NEWS_SENTRY_ARTIFACTS",
            "bucket_name": "news-sentry-artifacts-preview",
        }
    ]
    assert wrangler["env"]["dev"]["r2_buckets"] == [
        {
            "binding": "NEWS_SENTRY_ARTIFACTS",
            "bucket_name": "news-sentry-artifacts-dev",
        }
    ]
    for sql in (schema_sql, migration_sql):
        assert "CREATE TABLE IF NOT EXISTS artifact_manifests" in sql
        assert "object_key TEXT NOT NULL UNIQUE" in sql
        assert "sha256 TEXT NOT NULL" in sql
        assert "status TEXT NOT NULL" in sql
    assert "20260802_phase3_durable_artifacts" in migration_sql


def test_cloudflare_worker_deploy_paths_use_top_level_env_for_queue_bindings() -> None:
    package_json = json.loads((CLOUDFLARE_DIR / "package.json").read_text(encoding="utf-8"))
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    combined = "\n".join([json.dumps(package_json["scripts"], sort_keys=True), deploy_yml])

    assert package_json["scripts"]["deploy:prod"] == 'wrangler deploy --env=""'
    assert (
        'node_modules/.bin/wrangler deploy --env="" --containers-rollout gradual'
        in deploy_yml
    )
    assert 'node_modules/.bin/wrangler deploy --env="" --dry-run' in deploy_yml
    assert "wrangler deploy --env production" not in combined
    assert "wrangler deploy --env=production" not in combined
    assert "wrangler deploy --env dev" not in combined
    assert "wrangler deploy --env=dev" not in combined


def test_cloudflare_native_runbook_records_performance_first_cutover_strategy() -> None:
    runbook = (ROOT / "docs/deployment/cloudflare-native-vps-removal.md").read_text(
        encoding="utf-8"
    )

    assert "Worker + D1" in runbook
    assert "Cloudflare Containers" in runbook
    assert "VPS is not a runtime dependency" in runbook
    assert "performance-first" in runbook
    assert "cutover gates" in runbook


def test_worker_write_endpoints_require_cloudflare_access_identity() -> None:
    index_ts = _read("workers/index.ts")
    access_ts = _read("workers/lib/access.ts")
    access_jwt_ts = _read("workers/lib/access-jwt.ts")

    assert "isWorkerWritePath" in access_ts
    assert '"/api/v1/events/import"' in access_ts
    assert '"/api/v1/webhook"' in access_ts
    assert "await authorizeWorkerWriteAccess(request, env)" in index_ts
    assert "runtimeMetadata(env, workerWriteAccess.identity)" in index_ts
    assert "{ artifacts: env.NEWS_SENTRY_ARTIFACTS }" in index_ts
    assert "verifyCloudflareAccessRequest(request, env, options)" in access_ts
    assert "identity: verification.principal" in access_ts
    assert '"Cf-Access-Jwt-Assertion"' in access_jwt_ts
    assert 'if (!config) return { ok: false, reason: "missing_config" }' in access_jwt_ts
    assert '"CF-Access-Client-Id"' not in access_ts


def test_cloudflare_worker_exposes_truthful_health_and_deploy_receipts() -> None:
    index_ts = _read("workers/index.ts")
    health_ts = _read("workers/api/health.ts")
    health_status_ts = _read("workers/lib/health-status.ts")
    wrangler = tomllib.loads(_read("wrangler.toml"))

    assert 'registerRoute("GET", "/api/v1/live", handleLiveness)' in index_ts
    assert 'registerRoute("GET", "/api/v1/ready", handleHealth)' in index_ts
    assert 'headers.set("X-News-Sentry-Runtime", "cloudflare-worker")' in index_ts
    assert 'headers.set("X-News-Sentry-Deploy-Commit"' in index_ts
    assert 'headers.set("X-News-Sentry-Worker-Version"' in index_ts
    assert 'sleepAfter = "5m"' in index_ts
    assert "buildD1FailureHealthResponse" in health_ts
    assert "status: 503" in health_ts
    assert 'reasonCodes.push("events_stale")' in health_status_ts
    assert wrangler["version_metadata"]["binding"] == "CF_VERSION_METADATA"


def test_cloudflare_import_quarantines_unsafe_urls_and_future_timestamps() -> None:
    schema_sql = _read("db/schema.sql")
    webhook_ts = _read("workers/api/webhook.ts")
    query_ts = _read("workers/lib/public-news-query.ts")
    snapshots_ts = _read("workers/lib/public-read-snapshots.ts")
    snapshot_policy_ts = _read("workers/lib/snapshot-policy.ts")
    scheduled_ts = _read("workers/lib/scheduled.ts")

    assert "CREATE TABLE IF NOT EXISTS quarantined_events" in schema_sql
    assert "validateExternalUrl" in webhook_ts
    assert "assessEventTimestamps" in webhook_ts
    assert "INSERT INTO quarantined_events" in webhook_ts
    assert "quarantined" in webhook_ts
    assert "PUBLIC_PUBLISHED_AT_SANITY_SQL" in query_ts
    assert "datetime(events.published_at) <= datetime('now', '+24 hours')" in query_ts
    assert "sanitizePublicSnapshotPayload" in snapshots_ts
    assert "isPublishedTimestampSafe" in snapshot_policy_ts
    assert "validateExternalUrl" in snapshot_policy_ts
    assert "quarantineExistingUnsafeEvents" in scheduled_ts
    assert "DELETE FROM events WHERE event_id = ?" in scheduled_ts
    assert "db.batch(statements)" in scheduled_ts


def test_cloudflare_scheduler_creates_shadow_jobs_without_replacing_legacy_execution() -> None:
    scheduled_ts = _read("workers/lib/scheduled.ts")
    job_store_ts = _read("workers/lib/job-store.ts")
    schema_sql = _read("db/schema.sql")

    for table in (
        "jobs",
        "job_attempts",
        "job_outbox",
        "source_runtime_state",
        "import_batches",
        "import_batch_chunks",
        "snapshot_generations",
        "snapshot_generation_items",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema_sql
    assert "generateShadowJobs(env.DB, startedAt)" in scheduled_ts
    assert "callContainerInternalTask" in scheduled_ts
    assert 'mode: "shadow"' in job_store_ts
    assert "ON CONFLICT(idempotency_key) DO NOTHING" in job_store_ts
    assert "INSERT INTO job_outbox" in job_store_ts
    assert "await db.batch(statements)" in job_store_ts
    assert "fencing_version=fencing_version + 1" in job_store_ts
    assert "AND status IN ('enqueued', 'retry_scheduled', 'leased')" in job_store_ts
    assert "AND lease_token=? AND fencing_version=?" in job_store_ts
    assert "canTransitionJobStatus" in job_store_ts


def test_cloudflare_shadow_queue_has_producer_consumer_and_dlq() -> None:
    wrangler = tomllib.loads(_read("wrangler.toml"))
    index_ts = _read("workers/index.ts")
    queue_ts = _read("workers/lib/queue-shadow.ts")

    queues = wrangler["queues"]
    producers = queues["producers"]
    consumers = queues["consumers"]

    assert {
        "binding": "NEWS_SENTRY_JOBS_QUEUE",
        "queue": "news-sentry-jobs",
    } in producers
    assert {
        "binding": "NEWS_SENTRY_JOBS_DLQ",
        "queue": "news-sentry-jobs-dlq",
    } in producers
    assert {
        "queue": "news-sentry-jobs",
        "max_batch_size": 5,
        "max_batch_timeout": 5,
        "max_retries": 3,
        "dead_letter_queue": "news-sentry-jobs-dlq",
        "max_concurrency": 1,
    } in consumers
    assert {
        "queue": "news-sentry-jobs-dlq",
        "max_batch_size": 5,
        "max_batch_timeout": 5,
        "max_retries": 3,
        "max_concurrency": 1,
    } in consumers
    assert "NEWS_SENTRY_JOBS_QUEUE" in index_ts
    assert "async queue(" in index_ts
    assert "handleShadowQueueBatch" in index_ts
    assert "dispatchDueShadowJobs" in queue_ts
    assert "message.ack()" in queue_ts
    assert "message.retry()" in queue_ts
    assert "stageImportBatchFromMessage" in queue_ts
    assert "importEventsToD1" not in queue_ts
    assert "refreshPublicReadSnapshots" not in queue_ts
    assert "buildAndActivateShadowSnapshotGeneration" not in queue_ts


def test_cloudflare_shadow_snapshot_generation_flips_only_after_complete_build() -> None:
    scheduled_ts = _read("workers/lib/scheduled.ts")
    generation_ts = _read("workers/lib/snapshot-generation.ts")

    assert "buildAndActivateShadowSnapshotGeneration" in scheduled_ts
    assert "INSERT INTO snapshot_generation_items" in generation_ts
    assert "SET status='ready'" in generation_ts
    assert "AND status='building'" in generation_ts
    assert "AND EXISTS (" in generation_ts
    assert "WHERE generation_id=? AND status='ready'" in generation_ts
    assert "active:snapshot-generation" in generation_ts
    assert "markGenerationFailed" in generation_ts


def test_cloudflare_worker_cors_allows_pages_origins_without_fallback_origin() -> None:
    cors_ts = _read("workers/lib/cors.ts")

    for origin in (
        "https://news-sentry.com",
        "https://www.news-sentry.com",
        "https://preview.news-sentry.com",
        "https://news-sentry.pages.dev",
        "http://localhost:5173",
    ):
        assert f'"{origin}"' in cors_ts

    assert 'headers.set("Access-Control-Allow-Origin", origin)' in cors_ts
    assert 'headers.set("Access-Control-Allow-Origin", allowedOrigins[0])' not in cors_ts
    assert '.endsWith(".news-sentry.pages.dev")' in cors_ts


def test_pages_headers_cache_public_shell_for_short_ttl() -> None:
    headers = (ROOT / "frontend/public/cloudflare-pages.headers").read_text(
        encoding="utf-8"
    )
    public_shell_cache = (
        "Cache-Control: public, max-age=60, stale-while-revalidate=300, no-transform"
    )

    assert f"/\n  {public_shell_cache}" in headers
    assert f"/public-app*\n  {public_shell_cache}" in headers
    assert "/assets/*\n  Cache-Control: public, max-age=31536000, immutable" in headers
    assert "connect-src 'self' __NEWS_SENTRY_API_ORIGIN__" in headers


def test_worker_health_qualifies_joined_job_timestamps() -> None:
    health_ts = _read("workers/api/health.ts")

    assert "THEN jobs.updated_at END" in health_ts
    assert "THEN updated_at END" not in health_ts


def test_deploy_workflow_runs_live_quality_gate_and_translation_backfill_exists() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    workflow = ROOT / ".github/workflows/public-translation-backfill.yml"

    assert "tools/cloudflare_live_quality_check.py" in deploy_yml
    assert "--min-summary-ready" in deploy_yml
    assert "--min-d1-targets 80" in deploy_yml
    assert "HEAD probe" in deploy_yml or "head_probe" in deploy_yml
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in content
    assert "execute" in content
    assert "CLOUDFLARE_API_TOKEN" in content
    assert "tools/cloudflare_d1_public_translation_backfill.py" in content
    assert "--transaction" not in content
