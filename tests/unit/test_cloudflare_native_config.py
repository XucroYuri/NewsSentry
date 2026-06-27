"""Cloudflare-native deployment contract tests."""

from __future__ import annotations

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

    assert 'params.get("related")' in news_ts
    assert "related_tags LIKE ?" in news_ts


def test_public_reader_uses_drafts_stage_like_python_reader() -> None:
    news_ts = _read("workers/api/news.ts")
    facets_ts = _read("workers/api/facets.ts")
    bootstrap_ts = _read("workers/api/bootstrap.ts")

    for worker_source in (news_ts, facets_ts, bootstrap_ts):
        assert "pipeline_stage = 'drafts'" in worker_source
        assert "pipeline_stage IN ('published', 'reviewed')" not in worker_source

    assert "total: newsRows.length" in bootstrap_ts


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
    assert '"/api/v1/admin/"' in access_ts
    assert '"/api/v1/auth/"' in access_ts
    assert '"Cf-Access-Authenticated-User-Email"' in access_ts
    assert '"Cf-Access-Jwt-Assertion"' in access_ts
    assert "Cloudflare Access authentication required" in access_ts
    assert "BACKEND_ORIGIN" in proxy_ts
    assert "fetch(new Request(upstream.toString()" in proxy_ts
    assert wrangler_toml["vars"]["BACKEND_ORIGIN"] == "https://news-sentry.com"


def test_worker_write_endpoints_require_cloudflare_access_identity() -> None:
    index_ts = _read("workers/index.ts")
    access_ts = _read("workers/lib/access.ts")

    assert "isWorkerWritePath" in access_ts
    assert '"/api/v1/events/import"' in access_ts
    assert '"/api/v1/webhook"' in access_ts
    assert "handleWorkerWriteAccess(request)" in index_ts
    assert "dispatch(request, env.DB)" in index_ts
