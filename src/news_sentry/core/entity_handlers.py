"""Extracted handler logic for Entities + Annotations admin endpoints.

Each async function accepts ``store`` (and optionally ``get_target_store``)
as its first parameter(s), followed by the query/path/body parameters and
the authenticated ``user`` dict.  This keeps the handler bodies testable
independently of the FastAPI ``create_app()`` closure.

Originally extracted from ``api_server.py`` lines ~3509-3716.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query

from news_sentry.api.schemas import (
    AnnotationCreateRequest,
    AnnotationInfo,
    AnnotationListResponse,
    AnnotationUpdateRequest,
    EntityDetailResponse,
    EntityInfo,
    EntityListResponse,
    EntityMergeRequest,
    EntityMergeResponse,
)

# ── 实体 ──────────────────────────────────────────────────────────

async def entity_list_entities(
    store: Any,
    get_target_store: Any,
    entity_type: str | None = Query(None, description="按实体类型过滤"),
    target_id: str | None = Query(None, description="按目标过滤"),
    min_mentions: int = Query(1, ge=1, description="最少提及次数"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    sort: str = Query("mention_count", description="排序: mention_count 或 last_seen"),
    user: dict[str, Any] | None = None,
) -> EntityListResponse:
    """返回实体列表（优先使用 target state.db）。"""
    store_to_query = store
    if target_id is not None:
        ts = await get_target_store(target_id)
        if ts is not None:
            store_to_query = ts
    if store_to_query is None:
        return EntityListResponse(total=0, entities=[])
    entities = await store_to_query.query_entities(
        entity_type=entity_type,
        target_id=target_id,
        min_mentions=min_mentions,
        limit=limit,
        sort=sort,
    )
    return EntityListResponse(
        total=len(entities),
        entities=[EntityInfo(**e) for e in entities],
    )


async def entity_get_entity(
    store: Any,
    entity_id: int,
    user: dict[str, Any] | None = None,
) -> EntityDetailResponse:
    """返回实体详情及关联事件。"""
    if store is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    detail = await store.query_entity_detail(entity_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    recent = detail.pop("recent_events", [])
    return EntityDetailResponse(
        entity=EntityInfo(**detail),
        recent_events=recent,
    )


async def entity_search_entities(
    store: Any,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    user: dict[str, Any] | None = None,
) -> EntityListResponse:
    """FTS5 全文搜索实体。"""
    if store is None:
        return EntityListResponse(total=0, entities=[])
    entities = await store.search_entities_fts(q, limit=limit)
    return EntityListResponse(
        total=len(entities),
        entities=[EntityInfo(**e) for e in entities],
    )


async def entity_merge_entities(
    store: Any,
    body: EntityMergeRequest,
    user: dict[str, Any] | None = None,
) -> EntityMergeResponse:
    """合并两个实体。"""
    if store is None:
        raise HTTPException(status_code=500, detail="Store unavailable")
    result = await store.merge_entities(body.source_id, body.target_id)
    return EntityMergeResponse(**result)


async def entity_get_entity_events(
    store: Any,
    entity_id: int,
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """获取实体关联的所有事件（分页）。"""
    if store is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    events = await store.get_entity_events(entity_id, limit=limit, offset=offset)
    return {"entity_id": entity_id, "total": len(events), "events": events}


# ── 注解 ──────────────────────────────────────────────────────────

async def annotation_create_annotation(
    store: Any,
    body: AnnotationCreateRequest,
    user: dict[str, Any] | None = None,
) -> AnnotationInfo:
    """写入一条人工注解记录。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    ann_id = await store.upsert_annotation(
        entity_id=body.entity_id,
        field=body.field,
        old_value=body.old_value,
        new_value=body.new_value,
        event_id=body.event_id,
        annotation_type=body.annotation_type,
        created_by=body.created_by or (user or {}).get("username", "local-user"),
    )
    if ann_id < 0:
        raise HTTPException(status_code=500, detail="Failed to create annotation")
    return AnnotationInfo(
        id=ann_id,
        entity_id=body.entity_id,
        event_id=body.event_id,
        field=body.field,
        old_value=body.old_value,
        new_value=body.new_value,
        annotation_type=body.annotation_type,
        created_by=body.created_by or (user or {}).get("username", "local-user"),
        created_at="",
        reviewed=False,
    )


async def annotation_list_annotations(
    store: Any,
    entity_id: int | None = Query(None, description="实体ID"),
    event_id: str | None = Query(None, description="事件ID"),
    reviewed: bool | None = Query(None, description="审核状态"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] | None = None,
) -> AnnotationListResponse:
    """列出注解记录（可按实体/事件/审核状态筛选）。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    annotations = await store.list_annotations(
        entity_id=entity_id,
        event_id=event_id,
        reviewed=reviewed,
        limit=limit,
        offset=offset,
    )
    return AnnotationListResponse(
        annotations=[AnnotationInfo(**a) for a in annotations],
        total=len(annotations),
    )


async def annotation_update_annotation(
    store: Any,
    annotation_id: int,
    body: AnnotationUpdateRequest,
    user: dict[str, Any] | None = None,
) -> AnnotationInfo:
    """更新注解内容。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    ok = await store.update_annotation(
        annotation_id,
        field=body.field,
        old_value=body.old_value,
        new_value=body.new_value,
        annotation_type=body.annotation_type,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="注解未找到或无可更新字段")
    if body.reviewed is not None:
        await store.review_annotation(
            annotation_id,
            body.reviewed,
            body.reviewed_by or (user or {}).get("username", "local-user"),
        )
    return AnnotationInfo(
        id=annotation_id,
        entity_id=0,
        field=body.field or "",
        old_value=body.old_value or "",
        new_value=body.new_value or "",
        annotation_type=body.annotation_type or "",
        created_by="",
        created_at="",
        reviewed=body.reviewed if body.reviewed is not None else False,
    )


async def annotation_delete_annotation(
    store: Any,
    annotation_id: int,
    user: dict[str, Any] | None = None,
) -> dict[str, str]:
    """删除一条注解记录。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    ok = await store.delete_annotation(annotation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="注解未找到")
    return {"status": "deleted", "id": str(annotation_id)}


async def annotation_review_annotation(
    store: Any,
    annotation_id: int,
    body: dict[str, Any],
    user: dict[str, Any] | None = None,
) -> AnnotationInfo:
    """标记注解审核状态。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    reviewed = bool(body.get("reviewed", True))
    reviewed_by = str(body.get("reviewed_by") or (user or {}).get("username", "local-user"))
    ok = await store.review_annotation(annotation_id, reviewed, reviewed_by)
    if not ok:
        raise HTTPException(status_code=404, detail="注解未找到")
    return AnnotationInfo(
        id=annotation_id,
        entity_id=0,
        field="",
        old_value="",
        new_value="",
        annotation_type="",
        created_by="",
        created_at="",
        reviewed=reviewed,
        reviewed_by=reviewed_by,
    )


# ── 通知规则 ──────────────────────────────────────────────────────

async def notification_upsert_notification_rule(
    store: Any,
    body: Any,  # NotificationRuleRequest (lazy-imported at call site)
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建或更新通知规则。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    rule_dict = body.model_dump()
    rule_dict["user_id"] = (user or {}).get("sub", "")  # 强制使用认证用户
    await store.upsert_notification_rule(rule_dict)
    return {
        "id": body.id,
        "user_id": body.user_id,
        "enabled": body.enabled,
        "rule": {k: v for k, v in rule_dict.items() if k not in ("id", "user_id", "enabled")},
    }


async def notification_list_notification_rules(
    store: Any,
    user_id: str | None = Query(None, description="按用户筛选"),
    user: dict[str, Any] | None = None,
) -> Any:  # list[dict[str, Any]] — store.list_notification_rules returns Any
    """列出通知规则。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not ready")
    rules = await store.list_notification_rules(user_id=user_id)
    return rules
