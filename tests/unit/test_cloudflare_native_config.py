"""Cloudflare-native deployment contract tests."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_DIR = ROOT / "frontend" / "cloudflare"


def _read(path: str) -> str:
    return (CLOUDFLARE_DIR / path).read_text(encoding="utf-8")


def test_wrangler_routes_are_top_level_not_nested_under_d1() -> None:
    config = tomllib.loads(_read("wrangler.toml"))

    assert config["routes"] == [
        {"pattern": "api.news-sentry.com", "custom_domain": True}
    ]
    assert config["env"]["production"]["routes"] == []
    for binding in config["d1_databases"]:
        assert "routes" not in binding


def test_worker_health_reads_cloudflare_d1_events_table() -> None:
    health_ts = _read("workers/api/health.ts")

    assert "FROM events" in health_ts
    assert "event_index" not in health_ts
    assert "public_quality" in health_ts
    assert "summary_ready" in health_ts
    assert "recommendation_ready" in health_ts
    assert "featured_total" in health_ts
    assert "latest_public_at" in health_ts


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


def test_cloudflare_public_featured_query_matches_python_quality_gate() -> None:
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    assert 'params.get("featured") === "true"' in news_ts
    assert 'params.get("featured") !== "false"' in bootstrap_ts
    assert "PUBLIC_FEATURED_MIN_SCORE = 60" in query_ts
    assert "value_score >= ?" in query_ts
    assert "summary IS NOT NULL AND TRIM(summary) <> ''" not in query_ts
    assert "recommendation_reason IS NOT NULL AND TRIM(recommendation_reason) <> ''" not in query_ts
    assert "json_valid(classification) = 1" in query_ts
    assert "json_extract(classification, '$.l0')" in query_ts
    assert "NOT IN ('uncategorized', 'other', 'breaking_news')" in query_ts
    assert "NOT LIKE '%/opinion/todayinhistory/%'" in query_ts
    assert "UPPER(TRIM(title)) LIKE 'MONDAY, %'" in query_ts
    assert "ORDER BY value_score DESC, published_at DESC, event_id DESC" in query_ts
    assert "publicNewsOrderBy(featured)" in news_ts
    assert "publicNewsOrderBy(featured)" in bootstrap_ts


def test_cloudflare_public_news_uses_sql_cursor_pagination() -> None:
    news_ts = _read("workers/api/news.ts")
    query_ts = _read("workers/lib/public-news-query.ts")

    assert "buildCursorFilter" in news_ts
    assert 'params.get("before_cursor")' in news_ts
    assert 'params.get("since_cursor")' in news_ts
    assert "SELECT event_id, published_at, value_score FROM events WHERE event_id = ?" in news_ts
    assert "${cursorFilter.sql}" in news_ts
    assert "SELECT COUNT(*) AS total FROM events ${filters.sql}" in news_ts
    assert "Number.isFinite(requestedPageSize)" in news_ts
    assert "const pageRows = rows.slice(0, pageSize)" in news_ts
    assert "const items = pageRows.map" in news_ts
    assert "hasNewer: Boolean(sinceCursor && items.length > 0)" in news_ts
    assert "ORDER BY published_at DESC, event_id DESC" in query_ts


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
    assert "dispatch(request, env.DB, ctx)" in index_ts
    assert "rawMethod === \"HEAD\"" in router_ts
    assert "new Response(null" in router_ts
    assert "maybeServeCachedPublicRead" in news_ts
    assert "maybeStoreCachedPublicRead" in news_ts
    assert "X-News-Sentry-Worker-Cache" in cache_ts
    assert "public-read:news:featured" in news_ts
    assert "public-read:news:all" in news_ts
    assert "public-read:bootstrap:featured" in bootstrap_ts
    assert "public-read:facets" in facets_ts
    assert "public-read:regions" in targets_ts


def test_cloudflare_public_read_endpoints_use_snapshots_before_queries() -> None:
    news_ts = _read("workers/api/news.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")
    facets_ts = _read("workers/api/facets.ts")
    targets_ts = _read("workers/api/targets.ts")
    snapshots_ts = _read("workers/lib/public-read-snapshots.ts")
    session_ts = _read("workers/lib/public-read-session.ts")

    assert "readPublicSnapshot" in news_ts
    assert "NEWS_FEATURED_SNAPSHOT_KEY" in news_ts
    assert "NEWS_ALL_SNAPSHOT_KEY" in news_ts
    assert "readPublicSnapshot" in bootstrap_ts
    assert "BOOTSTRAP_FEATURED_SNAPSHOT_KEY" in bootstrap_ts
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
    assert "LIMIT 21" in snapshots_ts
    assert "const pageRows = rows.slice(0, 20)" in snapshots_ts
    assert "rows.length > 20" in snapshots_ts


def test_cloudflare_scheduled_refreshes_public_read_snapshots() -> None:
    scheduled_ts = _read("workers/lib/scheduled.ts")

    assert "refreshPublicReadSnapshots" in scheduled_ts
    assert "await refreshPublicReadSnapshots(env.DB)" in scheduled_ts


def test_cloudflare_scheduled_ops_are_configured() -> None:
    index_ts = _read("workers/index.ts")
    scheduled_ts = _read("workers/lib/scheduled.ts")
    schema_sql = _read("db/schema.sql")
    wrangler_toml = tomllib.loads(_read("wrangler.toml"))

    assert "async scheduled(" in index_ts
    assert "runScheduledCloudflareTask" in index_ts
    assert "collect-cycle" in scheduled_ts
    assert "public-translation-cycle" in scheduled_ts
    assert "refresh-public-quality" in scheduled_ts
    assert "ops_state" in schema_sql
    assert "ops_runs" in schema_sql
    assert "lock_until" in schema_sql
    assert wrangler_toml["triggers"]["crons"] == ["*/15 * * * *", "7,37 * * * *", "11 * * * *"]
    assert 'compactDetails.status === "string"' in scheduled_ts
    assert "await recordRun(env.DB, runId, task, status" in scheduled_ts
    assert "importEventsToD1" in scheduled_ts
    assert "extractContainerImportEvents" in scheduled_ts
    assert "importContainerEventsToD1" in scheduled_ts
    assert "import_result" in scheduled_ts
    assert "compactTaskDetails({" in scheduled_ts
    assert "updates_count" in scheduled_ts
    assert "target_results" in scheduled_ts
    assert "/api/v1/internal/cloudflare/${task}" in scheduled_ts
    assert '"X-News-Sentry-Internal-Task": task' in scheduled_ts
    assert "isContainerNotRunningError" in scheduled_ts
    assert "startAndWaitForPorts(8000" in scheduled_ts
    assert "ensured_before_fetch" in scheduled_ts
    assert "started_after_not_running" in scheduled_ts


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


def test_events_import_persists_to_cloudflare_d1() -> None:
    webhook_ts = _read("workers/api/webhook.ts")

    assert "db: D1Database" in webhook_ts
    assert "importEventsToD1" in webhook_ts
    assert "INSERT INTO events" in webhook_ts
    assert "recommendation_reason" in webhook_ts
    assert "value_score" in webhook_ts
    assert "ON CONFLICT(event_id)" in webhook_ts


def test_container_proxy_requires_cloudflare_access_identity() -> None:
    index_ts = _read("workers/index.ts")
    access_ts = _read("workers/lib/access.ts")
    proxy_ts = _read("workers/api/proxy.ts")
    wrangler_toml = tomllib.loads(_read("wrangler.toml"))

    assert "shouldProxyToContainer" in index_ts
    assert "handleContainerProxy(request, env)" in index_ts
    assert "NewsSentryContainer" in index_ts
    assert '"/api/v1/admin/"' in access_ts
    assert '"/api/v1/auth/"' in access_ts
    assert "/api/v1/internal/cloudflare" not in access_ts
    assert '"Cf-Access-Authenticated-User-Email"' in access_ts
    assert '"Cf-Access-Jwt-Assertion"' not in access_ts
    assert '"CF-Access-Client-Id"' not in access_ts
    assert "Cloudflare Access authentication required" in access_ts
    assert "NEWS_SENTRY_CONTAINER" in proxy_ts
    assert "getContainer(env.NEWS_SENTRY_CONTAINER" in proxy_ts
    assert "BACKEND_ORIGIN" not in proxy_ts
    assert "https://news-sentry.com" not in _read("wrangler.toml")
    assert "BACKEND_ORIGIN" not in wrangler_toml.get("vars", {})
    assert "BACKEND_ORIGIN" not in wrangler_toml["env"]["production"].get("vars", {})
    assert wrangler_toml["containers"][0]["class_name"] == "NewsSentryContainer"
    assert wrangler_toml["containers"][0]["image"] == "../../Dockerfile"
    assert wrangler_toml["env"]["production"]["containers"][0]["image"] == "../../Dockerfile"
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

    assert "isWorkerWritePath" in access_ts
    assert '"/api/v1/events/import"' in access_ts
    assert '"/api/v1/webhook"' in access_ts
    assert "handleWorkerWriteAccess(request)" in index_ts
    assert "dispatch(request, env.DB, ctx)" in index_ts
    assert '"Cf-Access-Jwt-Assertion"' not in access_ts
    assert '"CF-Access-Client-Id"' not in access_ts


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


def test_pages_headers_cache_public_shell_for_short_ttl() -> None:
    headers = (ROOT / "frontend/public/public/_headers").read_text(encoding="utf-8")
    public_shell_cache = (
        "Cache-Control: public, max-age=60, stale-while-revalidate=300, no-transform"
    )

    assert f"/\n  {public_shell_cache}" in headers
    assert f"/public-app*\n  {public_shell_cache}" in headers
    assert "/assets/*\n  Cache-Control: public, max-age=31536000, immutable" in headers


def test_deploy_workflow_runs_live_quality_gate_and_translation_backfill_exists() -> None:
    deploy_yml = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    workflow = ROOT / ".github/workflows/public-translation-backfill.yml"

    assert "tools/cloudflare_live_quality_check.py" in deploy_yml
    assert "--min-summary-ready" in deploy_yml
    assert "HEAD probe" in deploy_yml or "head_probe" in deploy_yml
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in content
    assert "execute" in content
    assert "CLOUDFLARE_API_TOKEN" in content
    assert "tools/cloudflare_d1_public_translation_backfill.py" in content
    assert "--transaction" not in content
