"""AsyncStore: EntityStoreMixin 功能域。

从 async_store.py 自动拆分。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ._base import AsyncStoreBase

UTC = UTC

class EntityStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Entity Tracking
    # ------------------------------------------------------------------
    # Entity Tracking (Phase 32)
    # ------------------------------------------------------------------

    async def upsert_entity(
        self,
        name: str,
        entity_type: str,
        target_id: str,
        seen_at: str,
        source_id: str | None = None,
        confidence: int = 0,
        event_id: str | None = None,
        mention_context: str = "",
    ) -> None:
        """插入或更新实体记录（同名+同类型视为同一实体）。

        - 同步写入 entities 表和 entity_event_mentions 关联表
        - 追踪 source_id（首次/最近出现源）
        """
        if self._db is None:
            return

        # 1. upsert entities 表
        await self._db.execute(
            """INSERT INTO entities
               (canonical_name, entity_type, first_seen, last_seen, target_ids,
                first_seen_source_id, last_seen_source_id, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                   mention_count = mention_count + 1,
                   last_seen = excluded.last_seen,
                   target_ids = CASE
                       WHEN ',' || target_ids || ',' LIKE '%,' || excluded.target_ids || ',%'
                       THEN target_ids
                       ELSE target_ids || ',' || excluded.target_ids
                   END,
                   last_seen_source_id = CASE
                       WHEN excluded.last_seen_source_id IS NOT NULL
                       THEN excluded.last_seen_source_id
                       ELSE last_seen_source_id
                   END,
                   confidence = (
                       CASE WHEN mention_count > 0
                       THEN (confidence * mention_count + excluded.confidence) / (mention_count + 1)
                       ELSE excluded.confidence
                       END
                   ),
                   needs_review = CASE
                       WHEN excluded.confidence < 70 THEN 1
                       ELSE needs_review
                   END""",
            (name, entity_type, seen_at, seen_at, target_id,
             source_id, source_id, confidence),
        )

        # 2. 获取 entity_id（刚插入或已存在）
        async with self._db.execute(
            "SELECT id FROM entities WHERE canonical_name = ? AND entity_type = ?",
            [name, entity_type],
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return
        entity_id = row[0]

        # 3. 写入 entity_event_mentions 关联表
        if event_id is not None:
            await self._db.execute(
                """INSERT OR IGNORE INTO entity_event_mentions
                   (entity_id, event_id, source_id, confidence, mention_context)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity_id, event_id, source_id, confidence, mention_context),
            )

        await self._db.commit()

    async def query_entities(
        self,
        entity_type: str | None = None,
        target_id: str | None = None,
        min_mentions: int = 1,
        limit: int = 20,
        sort: str = "mention_count",
    ) -> list[dict[str, Any]]:
        """查询实体列表，支持过滤和排序。"""
        if self._db is None:
            return []
        conditions = ["mention_count >= ?"]
        params: list[Any] = [min_mentions]
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if target_id is not None:
            conditions.append("',' || target_ids || ',' LIKE '%,' || ? || ',%'")
            params.append(target_id)
        where = " AND ".join(conditions)
        order = "mention_count DESC" if sort == "mention_count" else "last_seen DESC"
        sql = (
            f"SELECT id, canonical_name, entity_type, mention_count, "  # noqa: S608
            f"first_seen, last_seen, target_ids, confidence, needs_review, "
            f"first_seen_source_id, last_seen_source_id "
            f"FROM entities WHERE {where} ORDER BY {order} LIMIT ?"
        )
        async with self._db.execute(sql, params + [limit]) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "id",
            "canonical_name",
            "entity_type",
            "mention_count",
            "first_seen",
            "last_seen",
            "target_ids",
            "confidence",
            "needs_review",
            "first_seen_source_id",
            "last_seen_source_id",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def query_entity_detail(self, entity_id: int) -> dict[str, Any] | None:
        """查询实体详情，附带最近关联事件（通过 entity_event_mentions 表）。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT id, canonical_name, entity_type, mention_count, "
            "first_seen, last_seen, target_ids, confidence, needs_review, "
            "first_seen_source_id, last_seen_source_id, aliases "
            "FROM entities WHERE id = ?",
            [entity_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "id",
            "canonical_name",
            "entity_type",
            "mention_count",
            "first_seen",
            "last_seen",
            "target_ids",
            "confidence",
            "needs_review",
            "first_seen_source_id",
            "last_seen_source_id",
            "aliases",
        )
        entity = dict(zip(cols, row, strict=True))
        # 关联事件：通过 entity_event_mentions 关联表查询
        recent_events: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT ei.event_id, ei.title_original, ei.published_at, "
            "ei.sentiment, ei.news_value_score, eem.confidence as mention_confidence "
            "FROM event_index ei "
            "JOIN entity_event_mentions eem ON ei.event_id = eem.event_id "
            "WHERE eem.entity_id = ? "
            "ORDER BY ei.published_at DESC LIMIT 10",
            [entity_id],
        ) as cursor:
            rows = await cursor.fetchall()
        ev_cols = ("event_id", "title_original", "published_at", "sentiment",
                    "news_value_score", "mention_confidence")
        recent_events = [dict(zip(ev_cols, r, strict=True)) for r in rows]
        entity["recent_events"] = recent_events
        return entity

    async def search_entities_fts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 搜索实体，BM25 排序。"""
        if self._db is None:
            return []
        escaped = query.replace('"', '""')
        async with self._db.execute(
            "SELECT e.id, e.canonical_name, e.entity_type, e.mention_count, "
            "e.confidence, e.first_seen, e.last_seen "
            "FROM entity_fts f "
            "JOIN entities e ON e.id = f.rowid "
            "WHERE entity_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            [f'"{escaped}"', limit],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("id", "canonical_name", "entity_type", "mention_count",
                "confidence", "first_seen", "last_seen")
        return [dict(zip(cols, r, strict=True)) for r in rows]

    async def merge_entities(self, source_id: int, target_id: int) -> dict[str, Any]:
        """合并两个实体：source 的所有 mentions 转移到 target，source 被删除。

        Returns:
            包含合并结果的 dict: {"merged": bool, "source_name": str, "target_name": str}
        """
        if self._db is None:
            return {"merged": False, "error": "no db"}

        # 1. 获取两个实体的信息
        async with self._db.execute(
            "SELECT id, canonical_name, aliases, mention_count FROM entities WHERE id IN (?, ?)",
            [source_id, target_id],
        ) as cur:
            rows = await cur.fetchall()
        entity_map = {r[0]: {"name": r[1], "aliases": r[2], "count": r[3]} for r in rows}
        source_info = entity_map.get(source_id)
        target_info = entity_map.get(target_id)
        if not source_info or not target_info:
            return {"merged": False, "error": "entity not found"}

        # 2. 转移 entity_event_mentions（跳过 UNIQUE 冲突）
        await self._db.execute(
            """INSERT OR IGNORE INTO entity_event_mentions
               (entity_id, event_id, source_id, confidence, is_manual, mention_context)
               SELECT ?, event_id, source_id, confidence, is_manual, mention_context
               FROM entity_event_mentions WHERE entity_id = ?""",
            [target_id, source_id],
        )

        # 3. 更新 target 的 aliases（追加 source 的 canonical_name）
        source_name = source_info["name"]
        target_aliases_str = target_info["aliases"] or ""
        target_aliases: list[str] = json.loads(target_aliases_str) if target_aliases_str else []
        if source_name not in target_aliases and source_name != target_info["name"]:
            target_aliases.append(source_name)
        # 也追加 source 的 aliases
        source_aliases_str = source_info["aliases"] or ""
        source_aliases: list[str] = json.loads(source_aliases_str) if source_aliases_str else []
        for a in source_aliases:
            if a not in target_aliases and a != target_info["name"]:
                target_aliases.append(a)

        await self._db.execute(
            "UPDATE entities SET aliases = ?, mention_count = mention_count + ? WHERE id = ?",
            [json.dumps(target_aliases, ensure_ascii=False), source_info["count"], target_id],
        )

        # 4. 删除 source 实体
        await self._db.execute("DELETE FROM entity_event_mentions WHERE entity_id = ?", [source_id])
        await self._db.execute("DELETE FROM entities WHERE id = ?", [source_id])

        await self._db.commit()
        return {
            "merged": True,
            "source_name": source_name,
            "target_name": target_info["name"],
        }

    async def get_entity_events(
        self, entity_id: int, limit: int = 50, offset: int = 0,
    ) -> list[dict[str, Any]]:
        """获取某实体的所有相关事件（分页）。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT ei.event_id, ei.title_original, ei.published_at, ei.sentiment, "
            "ei.news_value_score, ei.source_id, eem.confidence as mention_confidence "
            "FROM event_index ei "
            "JOIN entity_event_mentions eem ON ei.event_id = eem.event_id "
            "WHERE eem.entity_id = ? "
            "ORDER BY ei.published_at DESC LIMIT ? OFFSET ?",
            [entity_id, limit, offset],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "title_original", "published_at", "sentiment",
                "news_value_score", "source_id", "mention_confidence")
        return [dict(zip(cols, r, strict=True)) for r in rows]

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Entity Event Annotations
    # ------------------------------------------------------------------
    # Entity Event Annotations — L1 人工注解层
    # ------------------------------------------------------------------

    async def upsert_annotation(
        self,
        entity_id: int,
        field: str,
        old_value: str,
        new_value: str,
        *,
        event_id: str | None = None,
        annotation_type: str = "manual",
        created_by: str = "local-user",
    ) -> int:
        """写入一条人工注解记录。返回新记录的 id。"""
        if self._db is None:
            return -1
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO entity_event_annotations
               (entity_id, event_id, field, old_value, new_value,
                annotation_type, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, event_id, field, old_value, new_value, annotation_type, created_by, now),
        )
        await self._db.commit()
        return cursor.lastrowid or -1

    async def list_annotations(
        self,
        entity_id: int | None = None,
        event_id: str | None = None,
        reviewed: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出注解记录，可按实体/事件/审核状态筛选。"""
        if self._db is None:
            return []
        wheres: list[str] = []
        params: list[Any] = []
        if entity_id is not None:
            wheres.append("e.entity_id = ?")
            params.append(entity_id)
        if event_id is not None:
            wheres.append("e.event_id = ?")
            params.append(event_id)
        if reviewed is not None:
            wheres.append("e.reviewed = ?")
            params.append(1 if reviewed else 0)
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        cols = (
            "e.id", "e.entity_id", "e.event_id", "e.field",
            "e.old_value", "e.new_value", "e.annotation_type",
            "e.created_by", "e.created_at", "e.reviewed",
            "e.reviewed_by", "e.reviewed_at",
            "ent.canonical_name",
        )
        sql = (
            f"SELECT {', '.join(cols)} "  # noqa: S608
            "FROM entity_event_annotations e "
            "LEFT JOIN entities ent ON e.entity_id = ent.id "
            f"{where_clause} "
            "ORDER BY e.created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(zip([c.split(".")[-1] for c in cols], r, strict=True)) for r in rows]

    async def update_annotation(
        self,
        annotation_id: int,
        *,
        field: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        annotation_type: str | None = None,
    ) -> bool:
        """更新注解的字段内容。"""
        if self._db is None:
            return False
        sets: list[str] = []
        params: list[Any] = []
        if field is not None:
            sets.append("field = ?")
            params.append(field)
        if old_value is not None:
            sets.append("old_value = ?")
            params.append(old_value)
        if new_value is not None:
            sets.append("new_value = ?")
            params.append(new_value)
        if annotation_type is not None:
            sets.append("annotation_type = ?")
            params.append(annotation_type)
        if not sets:
            return False
        params.append(annotation_id)
        await self._db.execute(
            f"UPDATE entity_event_annotations SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            params,
        )
        await self._db.commit()
        return True

    async def delete_annotation(self, annotation_id: int) -> bool:
        """删除一条注解记录。"""
        if self._db is None:
            return False
        cursor = await self._db.execute(
            "DELETE FROM entity_event_annotations WHERE id = ?",
            [annotation_id],
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def review_annotation(
        self,
        annotation_id: int,
        reviewed: bool,
        reviewed_by: str = "",
    ) -> bool:
        """标记注解审核状态。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE entity_event_annotations "
            "SET reviewed = ?, reviewed_by = ?, reviewed_at = ? "
            "WHERE id = ?",
            [1 if reviewed else 0, reviewed_by, now, annotation_id],
        )
        await self._db.commit()
        return True

    # ------------------------------------------------------------------
