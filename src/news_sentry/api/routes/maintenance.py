"""Maintenance API routes — admin maintenance operations.

Uses a ``register_maintenance_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_maintenance_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register all maintenance routes on the given APIRouter."""

    router.get("/api/v1/maintenance/draft-diagnostics")(h["maintenance_draft_diagnostics"])
    router.post("/api/v1/maintenance/archive-duplicate-drafts")(
        h["maintenance_archive_duplicate_drafts"]
    )
    router.post("/api/v1/maintenance/prune", response_model=h.get("PruneResponse"))(
        h["maintenance_prune"]
    )
    router.post(
        "/api/v1/maintenance/backup",
        response_model=h.get("BackupResponse"),
    )(h["maintenance_backup"])
    router.get("/api/v1/maintenance/backups")(h["list_backups"])
    router.post("/api/v1/maintenance/restore")(h["restore_backup"])
