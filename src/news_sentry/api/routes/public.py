"""Public API routes — no authentication required.

Uses a ``register_public_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_public_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register all public (no-auth) routes on the given APIRouter."""

    # ── 健康 & 诊断 ──
    router.get("/api/v1/health")(h["health"])
    router.get("/api/v1/diagnostics")(h["global_diagnostics"])

    # ── SPA / 静态前端路由 ──
    router.get("/", include_in_schema=False)(h["index_html"])
    router.get("/index.html", include_in_schema=False)(h["index_html"])
    router.get("/sources", include_in_schema=False)(h["publication_reader_page"])
    router.get("/subscribe", include_in_schema=False)(h["publication_reader_page"])
    router.get("/admin", include_in_schema=False)(h["admin_index_html"])
    router.get("/admin/", include_in_schema=False)(h["admin_index_html"])
    router.get("/admin/{path:path}", include_in_schema=False)(h["admin_path_html"])

    # ── SEO / 发现性 ──
    router.get("/robots.txt", include_in_schema=False)(h["robots_txt"])
    router.get("/llms.txt", include_in_schema=False)(h["llms_txt"])
    router.get("/sitemap.xml", include_in_schema=False)(h["sitemap_xml"])

    # ── 公开 App 前端 ──
    router.api_route(
        "/public-app", methods=["GET", "HEAD"], include_in_schema=False
    )(h["public_app_index"])
    router.api_route(
        "/public-app/", methods=["GET", "HEAD"], include_in_schema=False
    )(h["public_app_index"])
    router.api_route(
        "/public-app/{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )(h["public_app_asset"])

    # ── 认证（公开）──
    router.post("/api/v1/auth/login", response_model=h.get("LoginResponse"))(h["auth_login"])
    router.post("/api/v1/auth/token")(h["auth_token"])
    router.post("/api/v1/auth/logout")(h["auth_logout"])
    router.get("/api/v1/auth/setup-status")(h["auth_setup_status"])
    router.post("/api/v1/auth/setup")(h["auth_setup"])

    # ── Targets / Regions ──
    router.get("/api/v1/targets", response_model=h.get("TargetListResponse"))(h["list_targets"])
    router.get("/api/v1/regions", response_model=h.get("RegionListResponse"))(h["list_regions"])

    # ── 公开分析 ──
    router.get(
        "/api/v1/public/targets/{target_id}/analysis",
        response_model=h.get("PublicAnalysisResponse"),
    )(h["get_public_target_analysis"])

    # ── 公开数据 API ──
    router.get(
        "/api/v1/public/facets",
        response_model=h.get("PublicFacetsResponse"),
    )(h["list_public_facets"])
    router.get(
        "/api/v1/public/bootstrap",
        response_model=h.get("PublicBootstrapResponse"),
    )(h["get_public_bootstrap"])
    router.get(
        "/api/v1/public/news",
        response_model=h.get("PublicNewsFeedResponse"),
    )(h["list_public_news"])
    router.get(
        "/api/v1/public/news/{event_id}",
        response_model=h.get("PublicNewsItem"),
    )(h["get_public_news_item"])

    # ── 事件（公开）──
    router.get("/api/v1/events", response_model=h.get("EventResponse"))(h["list_events"])
    router.get("/api/v1/events/feed", include_in_schema=False)(h["events_feed"])
    router.get("/api/v1/events/stream", include_in_schema=False)(h["event_stream"])
    router.get("/api/v1/events/{event_id}")(h["get_event"])
    router.get("/api/v1/research/artifacts")(h["list_research_artifacts"])
