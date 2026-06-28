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


def test_cloudflare_bootstrap_reports_matching_featured_total() -> None:
    bootstrap_ts = _read("workers/api/bootstrap.ts")

    assert "SELECT COUNT(*) AS total FROM events ${newsFilters.sql}" in bootstrap_ts
    assert "total: newsCountResult?.total ?? newsRows.length" in bootstrap_ts


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
    assert "INSERT INTO events" in webhook_ts
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
    assert '"Cf-Access-Authenticated-User-Email"' in access_ts
    assert '"Cf-Access-Jwt-Assertion"' in access_ts
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
    assert "dispatch(request, env.DB)" in index_ts
