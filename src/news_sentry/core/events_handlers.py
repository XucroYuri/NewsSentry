"""从 api_server.py 的 create_app() 闭包中提取的 events-domain handler 逻辑。

每个异步函数接收 store、data_dir、get_target_store 作为前几个参数，
后接 query/path/body 参数。FastAPI 注解（Query、Depends 等）保留在 create_app() 的瘦闭包内。

模式遵循 canonical_handlers.py、public_handlers.py、entity_handlers.py。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import HTTPException

from news_sentry.core._state import InvisibleIndexedEvent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Events
# ═══════════════════════════════════════════════════════════════════════


async def list_events_handler(
    data_dir: Any,
    get_target_store: Any,
    store: Any,
    visible_index_events_page: Any,
    load_events_from_data: Any,
    store_has_target_event_index: Any,
    target_id: str,
    page: int = 1,
    page_size: int = 20,
    stage: str | None = None,
    classification: str | None = None,
    source_id: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
    sentiment: str | None = None,
    entity: str | None = None,
    topic_tag: str | None = None,
) -> Any:  # returns EventResponse-compatible dict
    # 优先使用 target 自己的 state.db（与 pipeline 共享同一数据库）
    target_store = await get_target_store(target_id)
    store_to_query = target_store if target_store is not None else store
    effective_stage = stage if stage else "drafts"

    if store_to_query is not None:
        result = await visible_index_events_page(
            store_to_query,
            data_dir,
            stage=effective_stage,
            target_id=target_id,
            page=page,
            page_size=page_size,
            source_id=source_id,
            classification_l0=classification,
            min_score=min_score,
            sentiment=sentiment,
            entity_name=entity,
            topic_tag=topic_tag,
            search=search,
        )
        # target 已进入索引模式后，SQLite 是权威来源；只有全空 legacy target 才回退。
        if result["index_total"] > 0:
            from news_sentry.api.schemas import EventResponse
            return EventResponse(
                total=result["total"],
                events=result["events"],
                page=page,
                page_size=page_size,
            )
        if await store_has_target_event_index(store_to_query, target_id):
            from news_sentry.api.schemas import EventResponse
            return EventResponse(total=0, events=[], page=page, page_size=page_size)

    # 降级路径（无 store / store 为空 / 文件系统路径）
    return load_events_from_data(
        data_dir,
        target_id,
        page,
        page_size,
        classification=classification,
        source_id=source_id,
        min_score=min_score,
        search=search,
    )


async def events_feed_handler(
    data_dir: Any,
    get_target_store: Any,
    store: Any,
    visible_index_events_page: Any,
    load_events_from_data: Any,
    group_events_by_date: Any,
    store_has_target_event_index: Any,
    target_id: str,
    date: str | None = None,
    page: int = 1,
    page_size: int = 30,
) -> dict[str, Any]:
    """新闻流接口 — 按日期分组返回事件，含 AI 推荐标签。"""
    target_store = await get_target_store(target_id)
    store_to_query = target_store if target_store is not None else store

    if store_to_query is not None:
        result = await visible_index_events_page(
            store_to_query,
            data_dir,
            stage="drafts",
            target_id=target_id,
            page=page,
            page_size=page_size,
            date=date,
            exact_total=page_size <= 1,
        )
        if result["index_total"] > 0:
            # 按日期分组
            grouped = group_events_by_date(result["events"])
            return {
                "total": result["total"],
                "page": page,
                "page_size": page_size,
                "groups": grouped,
            }
        if await store_has_target_event_index(store_to_query, target_id):
            return {
                "total": 0,
                "page": page,
                "page_size": page_size,
                "groups": [],
            }

    # 降级: 文件系统
    all_events_resp = load_events_from_data(data_dir, target_id, 1, 1000)
    events = all_events_resp.events
    if date:
        events = [e for e in events if (e.get("published_at") or "").startswith(date)]
    grouped = group_events_by_date(events)
    return {
        "total": len(events),
        "page": page,
        "page_size": page_size,
        "groups": grouped,
    }


async def get_event_handler(
    data_dir: Any,
    get_target_store: Any,
    store: Any,
    load_indexed_event_detail: Any,
    load_single_event: Any,
    store_has_target_event_index: Any,
    event_id: str,
    target_id: str,
) -> dict[str, Any]:
    # 优先使用 target 自己的 state.db
    target_store = await get_target_store(target_id)
    if target_store is not None:
        event = await load_indexed_event_detail(
            data_dir,
            target_id,
            target_store,
            event_id,
        )
        if isinstance(event, InvisibleIndexedEvent):
            raise HTTPException(status_code=404, detail="Event not found")
        if event is not None:
            return cast("dict[str, Any]", event)
        if await store_has_target_event_index(target_store, target_id):
            raise HTTPException(status_code=404, detail="Event not found")

    if store is not None:
        event = await load_indexed_event_detail(
            data_dir,
            target_id,
            store,
            event_id,
        )
        if isinstance(event, InvisibleIndexedEvent):
            raise HTTPException(status_code=404, detail="Event not found")
        if event is not None:
            return cast("dict[str, Any]", event)
        if await store_has_target_event_index(store, target_id):
            raise HTTPException(status_code=404, detail="Event not found")

    # 降级路径（无 store / store 中未找到 / 文件系统路径）
    event = load_single_event(data_dir, target_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return cast("dict[str, Any]", event)


async def import_events_handler(
    store: Any,
    data_dir: Any,
    validate_target_slug_fn: Any,
    validate_source_slug_fn: Any,
    notify_sse_clients_fn: Any,
    events: list[Any],  # list[ImportEventItem]
) -> Any:  # returns ImportResponse-compatible dict
    """批量导入外部事件。

    接受 JSON 数组，逐条写入 data/{target_id}/raw/ 并索引到 SQLite。
    已存在的事件（event_id 相同）会被跳过。
    """
    from news_sentry.api.schemas import ImportResponse
    from news_sentry.models.newsevent import NewsEvent

    imported = 0
    skipped = 0
    errors: list[str] = []

    for i, item in enumerate(events):
        try:
            validate_target_slug_fn(item.target_id)
            validate_source_slug_fn(item.source_id)
            now = datetime.now(UTC)
            # 确定性 event_id: sha256(source_id|url|collected_at)
            event_id = (
                "ne-imp-"
                + sha256(
                    f"{item.source_id}|{item.url}|{item.collected_at}".encode()
                ).hexdigest()[:12]
            )

            # 去重检查
            if store is not None and await store.is_known(event_id):
                skipped += 1
                continue

            published_at = item.published_at or now.isoformat()
            event_data: dict[str, Any] = {
                "id": event_id,
                "run_id": "import",
                "source_id": item.source_id,
                "url": item.url,
                "title_original": item.title_original,
                "content_original": item.content_original,
                "language": item.language,
                "published_at": published_at,
                "collected_at": item.collected_at,
                "pipeline_stage": item.pipeline_stage,
            }
            if item.classification:
                event_data["metadata"] = {"classification": item.classification}

            # 写入 raw/ 目录（YAML frontmatter）
            raw_dir = data_dir / item.target_id / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            filepath = raw_dir / f"collected_{item.source_id}_{event_id}.md"
            fm = yaml.dump(
                event_data, allow_unicode=True, default_flow_style=False, sort_keys=False
            )
            body = f"# {item.title_original}\n\n{item.content_original}\n"
            filepath.write_text(f"---\n{fm}---\n\n{body}", encoding="utf-8")

            # 索引到 SQLite
            if store is not None and store._db is not None:  # noqa: SLF001
                gid = NewsEvent.make_gid()
                await store.mark_known(event_id, gid)
                classification_l0 = None
                if isinstance(item.classification, dict):
                    classification_l0 = item.classification.get("l0")
                await store._db.execute(  # noqa: SLF001
                    """INSERT OR IGNORE INTO event_index
                       (event_id, target_id, stage, source_id,
                        classification_l0, title_original,
                        published_at, file_path, created_at, gid)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        item.target_id,
                        item.pipeline_stage,
                        item.source_id,
                        classification_l0,
                        item.title_original,
                        published_at,
                        str(filepath),
                        now.isoformat(),
                        gid,
                    ),
                )
                await store._db.commit()  # noqa: SLF001

            # SSE 通知
            sse_payload = {"event_id": event_id, "source": "import"}
            asyncio.ensure_future(notify_sse_clients_fn(item.target_id, "new_event", sse_payload))

            imported += 1
        except Exception as exc:
            errors.append(f"events[{i}]: {exc}")

    return ImportResponse(imported=imported, skipped=skipped, errors=errors)


async def transition_event_stage_handler(
    store: Any,
    data_dir: Any,
    store_for_target_fn: Any,
    event_id: str,
    body: Any,  # TransitionEventRequest
) -> Any:  # returns TransitionEventResponse-compatible dict
    """将事件在 drafts → reviewed → published 之间转换。

    读取原事件文件，更新 review_stage，移动目录，同步更新 SQLite 索引。
    """
    from news_sentry.api.schemas import TransitionEventResponse
    from news_sentry.core.file_writer import FileWriter

    valid_stages = {"drafts", "reviewed", "published"}
    if body.new_stage not in valid_stages:
        raise HTTPException(
            status_code=422,
            detail=f"无效的审核阶段: {body.new_stage}，有效值: {sorted(valid_stages)}",
        )

    target_id = body.target_id
    target_store = await store_for_target_fn(target_id)
    if target_store is None:
        raise HTTPException(status_code=404, detail=f"Target 不存在或无事件索引: {target_id}")

    # 从索引中查找事件
    row = await target_store.get_event_index_row(target_id, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"事件不存在: {event_id}")

    file_path = row.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="事件无关联文件路径，无法转换")

    source_path = Path(file_path)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"事件文件不存在: {file_path}")

    # 使用 FileWriter 移动文件
    writer = FileWriter(data_dir)
    new_path = writer.move_event_review_stage(source_path, body.new_stage)

    # 更新索引中的 stage 和 file_path
    await target_store.update_event_stage(
        target_id,
        event_id,
        body.new_stage,
        str(new_path),
    )

    logger.info(
        "事件审核转换完成: event_id=%s target_id=%s -> %s new_path=%s",
        event_id,
        target_id,
        body.new_stage,
        new_path,
    )

    return TransitionEventResponse(
        event_id=event_id,
        new_stage=body.new_stage,
        new_file_path=str(new_path),
    )


async def get_event_links_handler(
    store: Any,
    event_id: str,
    target_id: str,
) -> Any:
    """获取某事件的关联事件列表。"""
    from news_sentry.api.schemas import EventLinkInfo, EventLinksResponse

    if store is None:
        return EventLinksResponse(event_id=event_id, links=[])
    links = await store.get_event_links(event_id)
    result_links: list[EventLinkInfo] = []
    for link in links:
        linked_id = link["linked_event_id"]
        title = None
        time_str = None
        if store._db is not None:
            async with store._db.execute(
                "SELECT title_original, published_at FROM event_index WHERE event_id = ?",
                [linked_id],
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    title = row[0]
                    time_str = row[1]
        result_links.append(
            EventLinkInfo(
                linked_event_id=linked_id,
                link_type=link["link_type"],
                strength=link["strength"],
                direction=link["direction"],
                signals=link.get("signals", {}),
                linked_event_title=title,
                linked_event_time=time_str,
            )
        )
    return EventLinksResponse(event_id=event_id, links=result_links)


async def get_event_chain_handler(
    store: Any,
    event_id: str,
    target_id: str,
) -> Any:
    """获取某事件的完整追踪链。"""
    from news_sentry.api.schemas import ChainEventInfo, EventChainResponse

    if store is None:
        return EventChainResponse(chain_id=event_id, events=[], total=0)
    chain = await store.get_event_chain(event_id, depth=5)
    events: list[ChainEventInfo] = []
    for ce in chain:
        events.append(
            ChainEventInfo(
                event_id=ce["event_id"],
                title_original=ce.get("title_original"),
                published_at=ce.get("published_at"),
                link_type=ce.get("link_type"),
            )
        )
    return EventChainResponse(chain_id=event_id, events=events, total=len(events))
