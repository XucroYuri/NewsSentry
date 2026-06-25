"""Targets API routes — admin target configuration, inventory, sources, social, and config.

Uses a ``register_target_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_target_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register all admin targets-related routes on the given APIRouter."""

    # ── Admin Target 管理 ──
    router.get("/api/v1/admin/targets")(h["list_admin_targets"])
    router.post("/api/v1/admin/targets")(h["create_admin_target"])
    router.patch("/api/v1/admin/targets/{target_id}")(h["patch_admin_target"])
    router.post("/api/v1/admin/targets/{target_id}/archive")(h["archive_admin_target"])
    router.post("/api/v1/admin/targets/{target_id}/restore")(h["restore_admin_target"])
    router.get("/api/v1/admin/targets/{target_id}/overview")(h["admin_target_overview"])
    router.post("/api/v1/admin/targets/{target_id}/validate")(h["validate_admin_target"])
    router.get("/api/v1/admin/targets/{target_id}/inventory")(h["admin_target_inventory"])

    # ── Admin Target Sources ──
    router.get("/api/v1/admin/targets/{target_id}/sources")(h["list_admin_target_sources"])
    router.post("/api/v1/admin/targets/{target_id}/sources")(h["create_admin_target_source"])
    router.patch("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}")(
        h["patch_admin_target_source"]
    )
    router.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/archive")(
        h["archive_admin_target_source"]
    )
    router.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/restore")(
        h["restore_admin_target_source"]
    )

    # ── Admin Target Social ──
    router.get("/api/v1/admin/targets/{target_id}/social")(h["get_admin_target_social"])
    router.post("/api/v1/admin/targets/{target_id}/social/dimensions")(
        h["create_admin_social_dimension"]
    )
    router.patch("/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}")(
        h["patch_admin_social_dimension"]
    )
    router.post(
        "/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts"
    )(h["create_admin_social_account"])
    router.patch(
        "/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts/{handle}"
    )(h["patch_admin_social_account"])

    # ── Target Config ──
    router.get("/api/v1/config/targets/{target_id}")(h["get_target_config"])
    router.get(
        "/api/v1/config/targets/{target_id}/sources",
        response_model=h.get("SourceListResponse"),
    )(h["list_sources"])
    router.get("/api/v1/config/targets/{target_id}/sources/{source_id:path}")(
        h["get_source_config"]
    )
    router.get(
        "/api/v1/config/targets/{target_id}/filters",
        response_model=h.get("FilterRulesResponse"),
    )(h["get_filter_rules"])
    router.put("/api/v1/config/targets/{target_id}")(h["update_target_config"])
    router.patch("/api/v1/config/targets/{target_id}/sources/{source_id:path}")(
        h["update_source_config"]
    )
    router.patch("/api/v1/config/targets/{target_id}/filters")(h["update_filter_config"])

    # ── Source Health ──
    router.get(
        "/api/v1/sources/health",
        response_model=h.get("SourceHealthListResponse"),
    )(h["list_source_health"])
