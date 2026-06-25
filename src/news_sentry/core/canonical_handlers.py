"""Extracted handler logic for Canonical Events + Research admin endpoints.

Each async function accepts ``store`` (or ``get_target_store``) and ``data_dir``
as its first parameter(s), followed by the query/path/body parameters.
This keeps the handler bodies testable independently of the FastAPI ``create_app()`` closure.

Originally extracted from ``api_server.py`` lines ~4619-4966.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Response

from news_sentry.api.schemas import (
    CanonicalBackfillRequest,
    ResearchArtifactCreateRequest,
    ResearchArtifactPatchRequest,
    ResearchGraphMergeRequest,
    ResearchGraphSplitRequest,
)
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions
from news_sentry.core.markdown_export import render_canonical_event_markdown

# ═══════════════════════════════════════════════════════════════════════
# 辅助（extracted from api_server._create_app 内部函数）
# ═══════════════════════════════════════════════════════════════════════

async def _canonical_event_or_404(
    store: Any,
    canonical_event_id: str,
    target_id: str,
) -> dict[str, Any]:
    event = await store.get_canonical_event(canonical_event_id)
    if not event or event.get("target_id") != target_id:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    return event


# ═══════════════════════════════════════════════════════════════════════
# Canonical Events
# ═══════════════════════════════════════════════════════════════════════

async def canonical_diagnostics(
    get_target_store: Any,
    target_id: str,
    since: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    service = CanonicalProjectionService(store)
    diagnostics = await service.project(
        ProjectionOptions(target_id=target_id, since=since, limit=limit, apply=False)
    )
    return diagnostics.to_dict()


async def canonical_backfill(
    get_target_store: Any,
    payload: CanonicalBackfillRequest,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(payload.target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    service = CanonicalProjectionService(store)
    diagnostics = await service.project(
        ProjectionOptions(
            target_id=payload.target_id,
            since=payload.since,
            limit=payload.limit,
            apply=payload.apply,
            projection_run_id=payload.projection_run_id,
        )
    )
    return diagnostics.to_dict()


async def list_canonical_events(
    get_target_store: Any,
    target_id: str,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    events = await store.list_canonical_events(
        target_id=target_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return {"events": events, "limit": limit, "offset": offset}


async def get_canonical_event(
    get_target_store: Any,
    canonical_event_id: str,
    target_id: str,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    return await _canonical_event_or_404(store, canonical_event_id, target_id)


async def list_canonical_event_mentions(
    get_target_store: Any,
    canonical_event_id: str,
    target_id: str,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    await _canonical_event_or_404(store, canonical_event_id, target_id)
    mentions = await store.list_event_mentions(canonical_event_id)
    return {"canonical_event_id": canonical_event_id, "mentions": mentions}


async def list_canonical_event_relations(
    get_target_store: Any,
    canonical_event_id: str,
    target_id: str,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    await _canonical_event_or_404(store, canonical_event_id, target_id)
    relations = await store.list_canonical_relations(canonical_event_id)
    return {"canonical_event_id": canonical_event_id, "relations": relations}


async def export_canonical_event_markdown(
    get_target_store: Any,
    markdown_download_response: Any,
    canonical_event_id: str,
    target_id: str,
) -> Response:
    """导出 canonical event evidence package Markdown，不写入磁盘。"""
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    event = await _canonical_event_or_404(store, canonical_event_id, target_id)
    mentions = await store.list_event_mentions(canonical_event_id)
    relations = await store.list_canonical_relations(canonical_event_id)
    artifacts = await store.list_research_artifacts(
        target_id=target_id,
        subject_type="canonical_event",
        subject_id=canonical_event_id,
        limit=200,
    )
    content = render_canonical_event_markdown(event, mentions, relations, artifacts)
    return markdown_download_response(f"{canonical_event_id}.md", content)


# ═══════════════════════════════════════════════════════════════════════
# Research Workflow
# ═══════════════════════════════════════════════════════════════════════

def _research_graph_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 422
    return HTTPException(status_code=status_code, detail=detail)


def _make_created_by(user: dict[str, Any]) -> str:
    return "local-user" if user.get("local") else str(user.get("username") or "local-user")


async def research_queue(
    get_target_store: Any,
    target_id: str,
    status: str = "open",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    return await store.list_research_queue(
        target_id=target_id,
        status=status,
        limit=limit,
        offset=offset,
    )


async def research_graph_merge(
    get_target_store: Any,
    payload: ResearchGraphMergeRequest,
    user: dict[str, Any],
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(payload.target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    created_by = _make_created_by(user)
    try:
        if payload.dry_run:
            return await store.preview_canonical_merge(
                target_id=payload.target_id,
                decision_artifact_id=payload.decision_artifact_id,
                survivor_canonical_event_id=payload.survivor_canonical_event_id,
                merged_canonical_event_ids=payload.merged_canonical_event_ids,
                title_override=payload.title_override,
                summary_override=payload.summary_override,
                created_by=created_by,
            )
        return await store.apply_canonical_merge(
            target_id=payload.target_id,
            decision_artifact_id=payload.decision_artifact_id,
            survivor_canonical_event_id=payload.survivor_canonical_event_id,
            merged_canonical_event_ids=payload.merged_canonical_event_ids,
            title_override=payload.title_override,
            summary_override=payload.summary_override,
            created_by=created_by,
        )
    except ValueError as exc:
        raise _research_graph_error(exc) from exc


async def research_graph_split(
    get_target_store: Any,
    payload: ResearchGraphSplitRequest,
    user: dict[str, Any],
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(payload.target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    created_by = _make_created_by(user)
    try:
        if payload.dry_run:
            return await store.preview_canonical_split(
                target_id=payload.target_id,
                decision_artifact_id=payload.decision_artifact_id,
                source_canonical_event_id=payload.source_canonical_event_id,
                affected_mention_ids=payload.affected_mention_ids,
                new_title=payload.new_title,
                new_summary=payload.new_summary,
                created_by=created_by,
            )
        return await store.apply_canonical_split(
            target_id=payload.target_id,
            decision_artifact_id=payload.decision_artifact_id,
            source_canonical_event_id=payload.source_canonical_event_id,
            affected_mention_ids=payload.affected_mention_ids,
            new_title=payload.new_title,
            new_summary=payload.new_summary,
            created_by=created_by,
        )
    except ValueError as exc:
        raise _research_graph_error(exc) from exc


async def research_graph_operations(
    get_target_store: Any,
    target_id: str,
    operation_type: str | None = None,
    decision_artifact_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    try:
        operations = await store.list_canonical_graph_operations(
            target_id=target_id,
            operation_type=operation_type,
            decision_artifact_id=decision_artifact_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"operations": operations, "limit": limit, "offset": offset}


async def research_event_detail(
    get_target_store: Any,
    canonical_event_id: str,
    target_id: str,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    event = await _canonical_event_or_404(store, canonical_event_id, target_id)
    mentions = await store.list_event_mentions(canonical_event_id)
    relations = await store.list_canonical_relations(canonical_event_id)
    artifacts = await store.list_research_artifacts(
        target_id=target_id,
        subject_type="canonical_event",
        subject_id=canonical_event_id,
        limit=200,
    )
    return {
        "event": event,
        "mentions": mentions,
        "relations": relations,
        "artifacts": artifacts,
    }


async def list_research_artifacts_handler(
    get_target_store: Any,
    target_id: str,
    subject_type: str = "canonical_event",
    subject_id: str | None = None,
    artifact_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    import news_sentry.core._state as _st
    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    if subject_id is not None:
        await _canonical_event_or_404(store, subject_id, target_id)
    artifacts = await store.list_research_artifacts(
        target_id=target_id,
        subject_type=subject_type,
        subject_id=subject_id,
        artifact_type=artifact_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"artifacts": artifacts, "limit": limit, "offset": offset}


async def create_research_artifact(
    get_target_store: Any,
    new_artifact_id_fn: Any,
    validate_metadata_fn: Any,
    payload: ResearchArtifactCreateRequest,
    user: dict[str, Any],
) -> dict[str, Any]:
    import news_sentry.core._state as _st

    validate_metadata_fn(payload.artifact_type, payload.metadata)
    ts = await get_target_store(payload.target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    await _canonical_event_or_404(store, payload.subject_id, payload.target_id)
    canonical_event_ids = [payload.subject_id]
    candidates = payload.metadata.get("candidate_canonical_event_ids")
    if isinstance(candidates, list):
        canonical_event_ids.extend(str(candidate) for candidate in candidates)
    artifact_id = new_artifact_id_fn(
        payload.target_id,
        payload.artifact_type,
        payload.subject_id,
        payload.metadata,
    )
    created_by = _make_created_by(user)
    try:
        await store.upsert_research_artifact(
            {
                "artifact_id": artifact_id,
                "target_id": payload.target_id,
                "artifact_type": payload.artifact_type,
                "title": payload.title,
                "body": payload.body,
                "subject_type": payload.subject_type,
                "subject_id": payload.subject_id,
                "canonical_event_ids": canonical_event_ids,
                "status": payload.status,
                "visibility": payload.visibility,
                "created_by": created_by,
                "metadata": payload.metadata,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    artifact = await store.get_research_artifact(artifact_id)
    return {"artifact": artifact}


async def patch_research_artifact(
    get_target_store: Any,
    validate_metadata_fn: Any,
    artifact_id: str,
    target_id: str,
    payload: ResearchArtifactPatchRequest,
) -> dict[str, Any]:
    import news_sentry.core._state as _st

    ts = await get_target_store(target_id)
    store = ts if ts is not None else _st._store
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    current = await store.get_research_artifact(artifact_id)
    if current is None or current.get("target_id") != target_id:
        raise HTTPException(status_code=404, detail="Research artifact not found")
    patch = payload.model_dump(exclude_none=True)
    if "metadata" in patch:
        validate_metadata_fn(str(current.get("artifact_type")), patch["metadata"])
    try:
        updated = await store.update_research_artifact(
            artifact_id,
            target_id=target_id,
            patch=patch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Research artifact not found")
    return {"artifact": updated}
