"""Entities & Annotations API routes — admin CRUD for named entities and their annotations.

Uses a ``register_entity_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_entity_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register all entities and annotations admin routes on the given APIRouter."""

    # ── 实体 ──
    router.get("/api/v1/entities", response_model=h.get("EntityListResponse"))(h["list_entities"])
    router.get(
        "/api/v1/entities/{entity_id}",
        response_model=h.get("EntityDetailResponse"),
    )(h["get_entity"])
    router.get(
        "/api/v1/entities/{entity_id}/events",
    )(h["get_entity_events"])
    router.get(
        "/api/v1/entities/search",
    )(h["search_entities"])
    router.post(
        "/api/v1/entities/merge",
        response_model=h.get("EntityMergeResponse"),
    )(h["merge_entities"])

    # ── 注解 ──
    router.post(
        "/api/v1/annotations",
    )(h["create_annotation"])
    router.get(
        "/api/v1/annotations",
        response_model=h.get("AnnotationListResponse"),
    )(h["list_annotations"])
    router.patch(
        "/api/v1/annotations/{annotation_id}",
    )(h["update_annotation"])
    router.delete(
        "/api/v1/annotations/{annotation_id}",
    )(h["delete_annotation"])
    router.post(
        "/api/v1/annotations/{annotation_id}/review",
    )(h["review_annotation"])
