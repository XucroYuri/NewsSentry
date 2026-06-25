"""Canonical Events & Research API routes.

Uses a ``register_canonical_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_canonical_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register canonical events and research routes on the given APIRouter."""

    # ── 规范化事件 ──
    router.get("/api/v1/canonical/diagnostics")(h["canonical_diagnostics"])
    router.post("/api/v1/canonical/backfill")(h["canonical_backfill"])
    router.get("/api/v1/canonical/events")(h["list_canonical_events"])
    router.get("/api/v1/canonical/events/{canonical_event_id}")(h["get_canonical_event"])
    router.get("/api/v1/canonical/events/{canonical_event_id}/mentions")(
        h["list_canonical_event_mentions"]
    )
    router.get("/api/v1/canonical/events/{canonical_event_id}/relations")(
        h["list_canonical_event_relations"]
    )
    router.get("/api/v1/canonical/events/{canonical_event_id}/export/markdown")(
        h["export_canonical_event_markdown"]
    )

    # ── 研究 ──
    router.get("/api/v1/research/queue")(h["research_queue"])
    router.post("/api/v1/research/graph/merge")(h["research_graph_merge"])
    router.post("/api/v1/research/graph/split")(h["research_graph_split"])
    router.get("/api/v1/research/graph/operations")(h["research_graph_operations"])
    router.get("/api/v1/research/events/{canonical_event_id}")(h["research_event_detail"])
    router.post("/api/v1/research/artifacts")(h["create_research_artifact"])
    router.patch("/api/v1/research/artifacts/{artifact_id}")(h["patch_research_artifact"])
