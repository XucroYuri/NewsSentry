"""Phase 2: Public API E2E tests — no authentication required.

Tests cover health, diagnostics, targets/regions, public news, bootstrap,
facets, SEO files, CORS, and security headers.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e


# ── Health & Diagnostics ──────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_200(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total_events" in data
        assert "latest_collected_at" in data

    def test_health_has_deploy_evidence_headers(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert resp.status_code == 200
        headers = resp.headers
        # Deploy commit header
        deploy_commit = headers.get("x-news-sentry-deploy-commit", "")
        assert deploy_commit, "Missing X-News-Sentry-Deploy-Commit header"
        assert len(deploy_commit) >= 7, f"Commit too short: {deploy_commit}"
        # Static build header
        static_build = headers.get("x-news-sentry-static-build", "")
        assert static_build, "Missing X-News-Sentry-Static-Build header"

    def test_health_cache_control_is_no_store(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert "no-store" in resp.headers.get("cache-control", "")


class TestDiagnostics:
    def test_diagnostics_returns_global_summary(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        # Top-level keys
        for key in ("deploy", "collector", "data", "events"):
            assert key in data, f"Missing top-level key: {key}"
        assert "ai_key_configured" in data
        assert "source_health" in data
        assert "recent_runs" in data

    def test_diagnostics_cache_control_is_no_store(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/diagnostics")
        assert "no-store" in resp.headers.get("cache-control", "")


# ── Targets / Regions ────────────────────────────────────────────────────


class TestTargets:
    def test_list_targets_returns_list(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert "targets" in data, "Missing 'targets' key"

    def test_list_targets_supports_include_empty(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/targets", params={"include_empty": True})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("targets"), list)


class TestRegions:
    def test_list_regions_returns_list(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/regions")
        assert resp.status_code == 200
        data = resp.json()
        assert "regions" in data, "Missing 'regions' key"

    def test_list_regions_supports_include_empty(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/regions", params={"include_empty": True})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("regions"), list)


# ── Public News / Bootstrap / Facets ─────────────────────────────────────


class TestPublicBootstrap:
    def test_bootstrap_returns_cached_payload(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/public/bootstrap")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("news", "regions", "facets", "generatedAt"):
            assert key in data, f"Missing key: {key}"

    def test_bootstrap_has_cache_headers(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/public/bootstrap")
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc, f"Expected public cache-control, got: {cc}"
        assert resp.headers.get("etag", ""), "Missing ETag"


class TestPublicNews:
    def test_list_public_news(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/public/news", params={"page_size": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data, "Missing 'items'"
        assert "total" in data, "Missing 'total'"
        assert isinstance(data["items"], list)

    def test_public_news_supports_cursors(
        self, e2e_client: httpx.Client
    ) -> None:
        """Test that before_cursor / since_cursor do not cause errors."""
        resp = e2e_client.get(
            "/api/v1/public/news",
            params={"page_size": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            cursor = data.get("nextCursor")
            if cursor:
                resp2 = e2e_client.get(
                    "/api/v1/public/news",
                    params={"before_cursor": cursor, "page_size": 1},
                )
                assert resp2.status_code == 200

    def test_public_news_returns_304_for_matching_etag(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/public/news", params={"page_size": 1})
        assert resp.status_code in (200, 304)
        etag = resp.headers.get("etag")
        if etag:
            resp2 = e2e_client.get(
                "/api/v1/public/news",
                params={"page_size": 1},
                headers={"If-None-Match": etag},
            )
            assert resp2.status_code == 304

    def test_public_news_filters_by_region(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/public/news", params={"region_id": "italy", "page_size": 3}
        )
        # Even with no data, should be 200
        assert resp.status_code == 200

    def test_error_on_oversized_page_size(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/public/news", params={"page_size": 9999}
        )
        # Should either clamp or return 422
        assert resp.status_code in (200, 422)


class TestPublicNewsDetail:
    def test_detail_on_nonexistent_event_returns_404(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get(
            "/api/v1/public/news/ne-nonexistent-00000000",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 404


class TestPublicFacets:
    def test_facets_returns_regions_issues_related(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/api/v1/public/facets")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("regions", "issues", "related"):
            assert key in data, f"Missing facets key: {key}"

    def test_facets_filter_by_region(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get(
            "/api/v1/public/facets", params={"region_id": "italy"}
        )
        assert resp.status_code == 200


# ── SEO / Discoverability ────────────────────────────────────────────────


class TestSeoFiles:
    def test_robots_txt(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/robots.txt")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "Disallow" in resp.text

    def test_llms_txt(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/llms.txt")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_sitemap_xml(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "xml" in resp.headers.get("content-type", "")
        assert "urlset" in resp.text or "url" in resp.text


# ── CORS ─────────────────────────────────────────────────────────────────


class TestCors:
    def test_options_returns_cors_headers(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS headers should be present
        assert "access-control-allow-origin" in resp.headers

    def test_disallowed_origin_no_cors_headers(
        self, e2e_client: httpx.Client
    ) -> None:
        """Non-whitelisted origin should not get CORS credentials."""
        resp = e2e_client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert "evil.com" not in acao

    def test_cors_headers_on_get(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get(
            "/api/v1/health",
            headers={"Origin": "http://localhost:8000"},
        )
        assert "access-control-allow-origin" in resp.headers


# ── Security Headers ─────────────────────────────────────────────────────


class TestSecurityHeaders:
    """Verify that security headers defined in api_server are present."""

    def test_strict_transport_security(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert "strict-transport-security" in resp.headers

    def test_x_frame_options(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_security_headers_on_seo_files(self, e2e_client: httpx.Client) -> None:
        """SEO files also get security headers."""
        resp = e2e_client.get("/robots.txt")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_security_headers_on_public_app(
        self, e2e_client: httpx.Client
    ) -> None:
        resp = e2e_client.get("/public-app/", headers={"Accept": "text/html"})
        assert resp.status_code in (200, 404, 302)
        if resp.status_code == 200:
            assert resp.headers.get("x-frame-options") == "DENY"


# ── SPA Frontend Routes ──────────────────────────────────────────────────


class TestSpaRoutes:
    def test_root_returns_html(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/")
        assert resp.status_code in (200, 302)

    def test_public_app_entry(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/public-app/", headers={"Accept": "text/html"})
        assert resp.status_code in (200, 404)

    def test_admin_spa_entry(self, e2e_client: httpx.Client) -> None:
        resp = e2e_client.get("/admin")
        assert resp.status_code in (200, 302)
