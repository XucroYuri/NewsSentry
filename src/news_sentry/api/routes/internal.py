"""Cloudflare Container internal routes.

These endpoints are called only through the Cloudflare Worker Container binding.
They are not part of the public API surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_internal_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register Worker-to-Container internal task routes."""

    router.post("/api/v1/internal/cloudflare/collect-cycle", include_in_schema=False)(
        h["cloudflare_collect_cycle"]
    )
    router.post(
        "/api/v1/internal/cloudflare/public-translation-cycle",
        include_in_schema=False,
    )(h["cloudflare_public_translation_cycle"])
