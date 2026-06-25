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
    router.api_route("/api/v1/health", methods=["GET"], include_in_schema=False)(h["health"])
    router.api_route("/api/v1/diagnostics", methods=["GET"], include_in_schema=False)(
        h["global_diagnostics"]
    )

    # ── SPA / 静态前端路由 ──
    router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)(h["index_html"])
    router.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)(
        h["index_html"]
    )
    router.api_route("/sources", methods=["GET", "HEAD"], include_in_schema=False)(
        h["publication_reader_page"]
    )
    router.api_route("/subscribe", methods=["GET", "HEAD"], include_in_schema=False)(
        h["publication_reader_page"]
    )
    router.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)(
        h["admin_index_html"]
    )
    router.api_route("/admin/", methods=["GET", "HEAD"], include_in_schema=False)(
        h["admin_index_html"]
    )
    router.api_route("/admin/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)(
        h["admin_path_html"]
    )

    # ── SEO / 发现性 ──
    router.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)(
        h["robots_txt"]
    )
    router.api_route("/llms.txt", methods=["GET", "HEAD"], include_in_schema=False)(h["llms_txt"])
    router.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)(
        h["sitemap_xml"]
    )

    # ── 公开 App 前端 ──
    router.api_route("/public-app", methods=["GET", "HEAD"], include_in_schema=False)(
        h["public_app_index"]
    )
    router.api_route("/public-app/", methods=["GET", "HEAD"], include_in_schema=False)(
        h["public_app_index"]
    )
    router.api_route(
        "/public-app/{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )(h["public_app_asset"])

    # ── 认证（公开）──
    router.post("/api/v1/auth/login", response_model=h.get("LoginResponse"))(h["auth_login"])
    router.post("/api/v1/auth/token")(h["auth_token"])
    router.post("/api/v1/auth/logout")(h["auth_logout"])
    router.api_route("/api/v1/auth/setup-status", methods=["GET"])(h["auth_setup_status"])
    router.post("/api/v1/auth/setup")(h["auth_setup"])

    # ── Targets / Regions ──
    router.api_route(
        "/api/v1/targets",
        methods=["GET"],
        response_model=h.get("TargetListResponse"),
    )(h["list_targets"])
    router.api_route(
        "/api/v1/regions",
        methods=["GET"],
        response_model=h.get("RegionListResponse"),
    )(h["list_regions"])

    # ── 公开分析 ──
    router.api_route(
        "/api/v1/public/targets/{target_id}/analysis",
        methods=["GET"],
        response_model=h.get("PublicAnalysisResponse"),
    )(h["get_public_target_analysis"])

    # ── 公开数据 API ──
    router.api_route(
        "/api/v1/public/facets",
        methods=["GET"],
        response_model=h.get("PublicFacetsResponse"),
    )(h["list_public_facets"])
    router.api_route(
        "/api/v1/subscriptions",
        methods=["POST"],
        include_in_schema=False,
    )(h["subscribe"])
    router.api_route(
        "/api/v1/public/bootstrap",
        methods=["GET"],
        response_model=h.get("PublicBootstrapResponse"),
    )(h["get_public_bootstrap"])
    router.api_route(
        "/api/v1/public/news",
        methods=["GET"],
        response_model=h.get("PublicNewsFeedResponse"),
    )(h["list_public_news"])
    router.api_route(
        "/api/v1/public/news/{event_id}",
        methods=["GET"],
        response_model=h.get("PublicNewsItem"),
    )(h["get_public_news_item"])

    # ── 事件（公开）──
    router.api_route(
        "/api/v1/events",
        methods=["GET"],
        response_model=h.get("EventResponse"),
    )(h["list_events"])
    router.api_route("/api/v1/events/feed", methods=["GET"], include_in_schema=False)(
        h["events_feed"]
    )
    router.api_route("/api/v1/events/stream", methods=["GET"], include_in_schema=False)(
        h["event_stream"]
    )
    router.api_route("/api/v1/events/{event_id}", methods=["GET"])(h["get_event"])
    router.api_route("/api/v1/research/artifacts", methods=["GET"])(h["list_research_artifacts"])
