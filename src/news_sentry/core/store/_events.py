"""AsyncStore: EventStoreMixin 功能域。

从 async_store.py 自动拆分。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from news_sentry.skills.filter.classification_taxonomy import canonical_l0, l0_query_values

from ._base import AsyncStoreBase


class EventStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Event Index
    # ------------------------------------------------------------------
    # Event Index
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_nlp_fields(event: Any) -> tuple[str | None, str | None, str | None]:  # noqa: ANN401
        """从 event.judge_result.nlp_analysis 提取 SQLite 窄列值。"""
        judge_result = getattr(event, "judge_result", None)
        if judge_result is None:
            return None, None, None
        nlp = getattr(judge_result, "nlp_analysis", None)
        if nlp is None:
            return None, None, None

        sentiment = nlp.sentiment.value if nlp.sentiment is not None else None
        if not isinstance(sentiment, str):
            sentiment = None
        entity_names = ",".join(e.name for e in nlp.entities) if nlp.entities else None
        if not isinstance(entity_names, str):
            entity_names = None
        topic_tags = ",".join(nlp.topic_tags) if nlp.topic_tags else None
        if not isinstance(topic_tags, str):
            topic_tags = None
        return sentiment, entity_names, topic_tags

    async def index_event(
        self,
        event: object,
        target_id: str,
        stage: str,
        file_path: str | None = None,
    ) -> None:
        if self._db is None:
            return
        metadata = self._safe_metadata_attr(event)
        translation_ready = self._publication_ready_from_index_row(
            self._publication_row_from_event(event, target_id, metadata)
        )
        classification = metadata.get("classification", {})
        classification_l0 = classification.get("l0") if isinstance(classification, dict) else None
        classification_l0 = canonical_l0(classification_l0)
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                url, published_at, file_path, metadata_json, public_translation_ready,
                sentiment, entity_names, topic_tags,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                   (SELECT created_at FROM event_index WHERE event_id = ?), ?))""",
            (
                getattr(event, "id", ""),
                target_id,
                stage,
                getattr(event, "source_id", None),
                getattr(event, "news_value_score", None),
                getattr(event, "china_relevance", None),
                classification_l0,
                getattr(event, "title_original", None),
                self._safe_text_attr(event, "url"),
                getattr(event, "published_at", None),
                file_path,
                self._json_dumps(metadata),
                translation_ready,
                *self._extract_nlp_fields(event),
                getattr(event, "id", ""),
                now,
            ),
        )
        await self._db.commit()

    async def query_events(
        self,
        target_id: str,
        stage: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id, news_value_score,
                      china_relevance, classification_l0, title_original,
                      published_at, file_path, created_at,
                      sentiment, entity_names, topic_tags
               FROM event_index
               WHERE target_id = ? AND stage = ?
               ORDER BY published_at DESC
               LIMIT ? OFFSET ?""",
            (target_id, stage, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "event_id",
            "target_id",
            "stage",
            "source_id",
            "news_value_score",
            "china_relevance",
            "classification_l0",
            "title_original",
            "published_at",
            "file_path",
            "created_at",
            "sentiment",
            "entity_names",
            "topic_tags",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def list_event_index_rows_for_projection(
        self,
        target_id: str,
        limit: int = 500,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """读取 event_index rows for shadow canonical projection."""
        params: list[Any] = [target_id]
        safe_limit = max(1, min(int(limit), 5000))
        if since:
            params.append(self._sqlite_datetime(since))
            query = """
                SELECT event_id, target_id, source_id, title_original, url, published_at,
                       stage, news_value_score, china_relevance,
                       classification_l0, metadata_json, file_path
                FROM event_index
                WHERE target_id = ?
                  AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
                ORDER BY datetime(COALESCE(published_at, created_at)) DESC
                LIMIT ?
                """
        else:
            query = """
                SELECT event_id, target_id, source_id, title_original, url, published_at,
                       stage, news_value_score, china_relevance,
                       classification_l0, metadata_json, file_path
                FROM event_index
                WHERE target_id = ?
                ORDER BY datetime(COALESCE(published_at, created_at)) DESC
                LIMIT ?
                """
        params.append(safe_limit)
        async with self._connect() as conn:
            rows = await conn.execute_fetchall(query, params)
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "event_id": row[0],
                    "target_id": row[1],
                    "source_id": row[2],
                    "title": row[3],
                    "url": row[4],
                    "published_at": row[5],
                    "pipeline_stage": row[6],
                    "news_value_score": row[7],
                    "china_relevance": row[8],
                    "l0_category": row[9],
                    "metadata": self._json_loads(row[10]),
                    "file_path": row[11],
                }
            )
        return result

    async def query_public_projection_rows(
        self,
        *,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """读取 public-site 所需的最小 event_index 行，不触碰 markdown/frontmatter。"""
        if self._db is None:
            return []
        safe_limit = max(1, min(int(limit), 5000))
        safe_offset = max(0, int(offset))
        if target_id is None:
            sql = (
                "SELECT event_id, target_id, source_id, title_original, url, published_at, "
                "created_at, news_value_score, china_relevance, classification_l0, metadata_json "
                "FROM event_index WHERE stage = ? AND public_translation_ready = 1 "
                "ORDER BY datetime(COALESCE(published_at, created_at)) DESC, event_id DESC "
                "LIMIT ? OFFSET ?"
            )
            params: list[Any] = ["drafts", safe_limit, safe_offset]
        else:
            sql = (
                "SELECT event_id, target_id, source_id, title_original, url, published_at, "
                "created_at, news_value_score, china_relevance, classification_l0, metadata_json "
                "FROM event_index WHERE stage = ? AND target_id = ? "
                "AND public_translation_ready = 1 "
                "ORDER BY datetime(COALESCE(published_at, created_at)) DESC, event_id DESC "
                "LIMIT ? OFFSET ?"
            )
            params = ["drafts", target_id, safe_limit, safe_offset]

        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "event_id": row[0],
                    "target_id": row[1],
                    "source_id": row[2],
                    "title_original": row[3],
                    "url": row[4],
                    "published_at": row[5],
                    "created_at": row[6],
                    "news_value_score": row[7],
                    "china_relevance": row[8],
                    "classification_l0": canonical_l0(row[9]),
                    "metadata": self._json_loads(row[10]),
                }
            )
        return result

    async def get_event_count(self, target_id: str, stage: str) -> int:
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ? AND stage = ?",
            (target_id, stage),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_target_event_count(self, target_id: str) -> int:
        """统计 target 在 event_index 中的所有阶段事件数。"""
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_public_event_count(self, target_id: str, stage: str = "drafts") -> int:
        """统计公共读者站当前可见的翻译完成事件数。"""
        if self._db is None:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index "
            "WHERE target_id = ? AND stage = ? AND public_translation_ready = 1",
            (target_id, stage),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_public_event_counts_by_target(self, stage: str = "drafts") -> dict[str, int]:
        """Return public-ready event counts grouped by target."""
        if self._db is None:
            return {}
        async with self._db.execute(
            "SELECT target_id, COUNT(*) FROM event_index "
            "WHERE stage = ? AND public_translation_ready = 1 "
            "GROUP BY target_id",
            (stage,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {str(row[0]): int(row[1] or 0) for row in rows if row[0]}

    async def get_stats(self, target_id: str) -> dict[str, Any]:
        if self._db is None:
            return {"total_events": 0, "stage_counts": {}, "avg_news_value_score": 0.0}
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?", (target_id,)
        ) as cursor:
            row = await cursor.fetchone()
        total = row[0] if row else 0
        async with self._db.execute(
            "SELECT stage, COUNT(*) FROM event_index WHERE target_id = ? GROUP BY stage",
            (target_id,),
        ) as cursor:
            stage_rows = await cursor.fetchall()
        stage_counts = {row[0]: row[1] for row in stage_rows}
        avg_sql = (
            "SELECT AVG(news_value_score) FROM event_index "
            "WHERE target_id = ? AND news_value_score IS NOT NULL"
        )
        async with self._db.execute(
            avg_sql,
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        avg_score = round(row[0], 1) if row and row[0] is not None else 0.0
        return {
            "total_events": total,
            "stage_counts": stage_counts,
            "avg_news_value_score": avg_score,
        }

    async def query_events_paginated(
        self,
        target_id: str,
        stage: str,
        *,
        limit: int = 20,
        offset: int = 0,
        source_id: str | None = None,
        classification_l0: str | None = None,
        min_score: int | None = None,
        sentiment: str | None = None,
        entity_name: str | None = None,
        topic_tag: str | None = None,
    ) -> dict[str, Any]:
        """分页查询 event_index，返回 {total: int, rows: list[dict]}。"""
        if self._db is None:
            return {"total": 0, "rows": []}
        conditions = ["target_id = ?", "stage = ?"]
        params: list[Any] = [target_id, stage]

        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        if classification_l0 is not None:
            values = sorted(l0_query_values(classification_l0))
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"classification_l0 IN ({placeholders})")
            params.extend(values)
        if min_score is not None:
            conditions.append("news_value_score >= ?")
            params.append(min_score)
        if sentiment is not None:
            conditions.append("sentiment = ?")
            params.append(sentiment)
        if entity_name is not None:
            conditions.append("',' || entity_names || ',' LIKE '%,' || ? || ',%'")
            params.append(entity_name)
        if topic_tag is not None:
            conditions.append("',' || topic_tags || ',' LIKE '%,' || ? || ',%'")
            params.append(topic_tag)

        where = " AND ".join(conditions)

        # 总数查询
        count_sql = f"SELECT COUNT(*) FROM event_index WHERE {where}"  # noqa: S608
        async with self._db.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        # 分页查询
        data_sql = (
            "SELECT event_id, source_id, news_value_score, china_relevance, "  # noqa: S608
            "classification_l0, published_at, file_path, title_original, "
            "sentiment, entity_names, topic_tags, metadata_json "
            f"FROM event_index WHERE {where} "
            "ORDER BY published_at DESC LIMIT ? OFFSET ?"
        )
        async with self._db.execute(data_sql, params + [limit, offset]) as cursor:
            rows = await cursor.fetchall()

        result_rows = []
        for r in rows:
            result_rows.append(
                {
                    "event_id": r[0],
                    "source_id": r[1],
                    "news_value_score": r[2],
                    "china_relevance": r[3],
                    "classification_l0": canonical_l0(r[4]),
                    "published_at": r[5],
                    "file_path": r[6],
                    "title_original": r[7],
                    "sentiment": r[8],
                    "entity_names": r[9],
                    "topic_tags": r[10],
                    "metadata": self._json_loads(r[11]),
                }
            )

        return {"total": total, "rows": result_rows}

    async def query_public_news_rows(
        self,
        target_id: str | None,
        stage: str,
        *,
        limit: int,
        source_id: str | None = None,
        classification_l0: str | None = None,
        min_score: int | None = None,
        date: str | None = None,
        search: str | None = None,
        before_key: tuple[str, str] | None = None,
        since_key: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """Query public news feed rows directly from event_index for fast first paint."""
        if self._db is None:
            return {"total": 0, "rows": []}

        conditions = ["stage = ?", "public_translation_ready = 1"]
        params: list[Any] = [stage]
        sort_expr = "datetime(COALESCE(published_at, created_at))"

        if target_id is not None:
            conditions.append("target_id = ?")
            params.append(target_id)
        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        if classification_l0 is not None:
            values = sorted(l0_query_values(classification_l0))
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"classification_l0 IN ({placeholders})")
            params.extend(values)
        if min_score is not None:
            conditions.append("news_value_score >= ?")
            params.append(min_score)
        if date is not None:
            conditions.append("substr(COALESCE(published_at, created_at), 1, 10) = ?")
            params.append(date)
        if search is not None:
            # 尝试使用 FTS5 全文搜索（如果虚拟表可用）
            try:
                await self._db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_index_fts'"
                )
                # FTS5 可用 — 用 FTS5 JOIN 替代 LIKE，支持 BM25 排序
                fts_condition = (
                    "event_index.rowid IN (SELECT rowid FROM event_index_fts "
                    "WHERE event_index_fts MATCH ?)"
                )
                conditions.append(fts_condition)
                params.append(f'"{search}"')
            except Exception:
                # FTS5 不可用 — 回退到 LIKE 查询
                conditions.append(
                    "LOWER(COALESCE(title_original, '') || ' ' || "
                    "COALESCE(source_id, '') || ' ' || COALESCE(metadata_json, '')) LIKE ?"
                )
                params.append(f"%{search.lower()}%")
        if before_key is not None:
            before_time, before_event_id = before_key
            conditions.append(
                f"({sort_expr} < datetime(?) OR ({sort_expr} = datetime(?) AND event_id < ?))"
            )
            params.extend([before_time, before_time, before_event_id])
        if since_key is not None:
            since_time, since_event_id = since_key
            conditions.append(
                f"({sort_expr} > datetime(?) OR ({sort_expr} = datetime(?) AND event_id > ?))"
            )
            params.extend([since_time, since_time, since_event_id])

        where = " AND ".join(conditions)
        count_sql = f"SELECT COUNT(*) FROM event_index WHERE {where}"  # noqa: S608
        async with self._db.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        data_sql = (
            "SELECT event_id, target_id, source_id, news_value_score, china_relevance, "  # noqa: S608
            "classification_l0, published_at, file_path, title_original, "
            "sentiment, entity_names, topic_tags, metadata_json, created_at, "
            "public_translation_ready "
            f"FROM event_index WHERE {where} "
            f"ORDER BY {sort_expr} DESC, event_id DESC LIMIT ?"
        )
        async with self._db.execute(data_sql, params + [limit]) as cursor:
            rows = await cursor.fetchall()

        result_rows = []
        for r in rows:
            result_rows.append(
                {
                    "event_id": r[0],
                    "target_id": r[1],
                    "source_id": r[2],
                    "news_value_score": r[3],
                    "china_relevance": r[4],
                    "classification_l0": canonical_l0(r[5]),
                    "published_at": r[6],
                    "file_path": r[7],
                    "title_original": r[8],
                    "sentiment": r[9],
                    "entity_names": r[10],
                    "topic_tags": r[11],
                    "metadata": self._json_loads(r[12]),
                    "created_at": r[13],
                    "public_translation_ready": r[14],
                }
            )

        return {"total": total, "rows": result_rows}

    async def search_public_events(
        self,
        query: str,
        *,
        target_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """使用 FTS5 全文搜索公开事件，带 BM25 排序.

        搜索 title_original、source_id、entity_names、topic_tags、metadata_text 字段。
        如果 FTS5 表不可用，回退到 LIKE 查询（query_public_news_rows）。
        """
        if self._db is None:
            return {"total": 0, "rows": []}

        safe_limit = max(1, min(int(limit), 500))

        # 尝试 FTS5 搜索
        try:
            conditions = ["event_index_fts MATCH ?"]
            params: list[Any] = [query]
            if target_id is not None:
                conditions.append("ei.target_id = ?")
                params.append(target_id)
            # 只查公开可见的
            conditions.append("ei.stage = 'drafts'")
            conditions.append("ei.public_translation_ready = 1")

            where = " AND ".join(conditions)

            # 带 BM25 排序的 FTS 查询
            count_sql = f"SELECT COUNT(*) FROM event_index_fts fts JOIN event_index ei ON ei.rowid = fts.rowid WHERE {where}"  # noqa: S608, E501
            async with self._db.execute(count_sql, params) as cursor:
                row = await cursor.fetchone()
                total = row[0] if row else 0

            if total == 0:
                return {"total": 0, "rows": []}

            data_sql = (
                "SELECT ei.event_id, ei.target_id, ei.source_id, ei.news_value_score, "  # noqa: S608
                "ei.china_relevance, ei.classification_l0, ei.published_at, ei.file_path, "
                "ei.title_original, ei.sentiment, ei.entity_names, ei.topic_tags, "
                "ei.metadata_json, ei.created_at, ei.public_translation_ready, "
                "bm25(event_index_fts) AS rank "
                "FROM event_index_fts fts "
                "JOIN event_index ei ON ei.rowid = fts.rowid "
                "WHERE " + where + " "
                "ORDER BY rank "
                "LIMIT ?"
            )
            async with self._db.execute(data_sql, params + [safe_limit]) as cursor:
                rows = await cursor.fetchall()

        except Exception:
            # FTS5 不可用，回退到 LIKE 查询
            return await self.query_public_news_rows(
                target_id=target_id,
                stage="drafts",
                limit=safe_limit,
                search=query,
            )

        result_rows = []
        for r in rows:
            result_rows.append(
                {
                    "event_id": r[0],
                    "target_id": r[1],
                    "source_id": r[2],
                    "news_value_score": r[3],
                    "china_relevance": r[4],
                    "classification_l0": canonical_l0(r[5]),
                    "published_at": r[6],
                    "file_path": r[7],
                    "title_original": r[8],
                    "sentiment": r[9],
                    "entity_names": r[10],
                    "topic_tags": r[11],
                    "metadata": self._json_loads(r[12]),
                    "created_at": r[13],
                    "public_translation_ready": r[14],
                }
            )

        return {"total": total, "rows": result_rows}

    async def list_public_translation_candidates(
        self,
        target_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return public draft rows that still need title/summary translation."""
        if self._db is None:
            return []
        safe_limit = max(1, min(int(limit), 5000))
        sql = """
            SELECT ei.event_id, ei.target_id, ei.stage, ei.source_id,
                   ei.news_value_score, ei.china_relevance, ei.classification_l0,
                   ei.title_original, ei.url, ei.published_at, ei.created_at,
                   ei.file_path, ei.metadata_json, ei.public_translation_ready,
                   ae.status, ae.attempts, ae.last_error, ae.route_id, ae.model, ae.updated_at
            FROM event_index ei
            LEFT JOIN ai_enrichment_events ae
              ON ae.target_id = ei.target_id AND ae.event_id = ei.event_id
            WHERE ei.target_id = ?
              AND ei.stage = 'drafts'
              AND ei.public_translation_ready = 0
            ORDER BY COALESCE(ei.news_value_score, 0) DESC,
                     datetime(COALESCE(ei.published_at, ei.created_at)) DESC,
                     ei.event_id DESC
            LIMIT ?
        """
        async with self._db.execute(sql, (target_id, safe_limit)) as cursor:
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "event_id": row[0],
                    "target_id": row[1],
                    "stage": row[2],
                    "source_id": row[3],
                    "news_value_score": row[4],
                    "china_relevance": row[5],
                    "classification_l0": canonical_l0(row[6]),
                    "title_original": row[7],
                    "url": row[8],
                    "published_at": row[9],
                    "created_at": row[10],
                    "file_path": row[11],
                    "metadata": self._json_loads(row[12]),
                    "public_translation_ready": row[13],
                    "translation_status": row[14],
                    "translation_attempts": row[15],
                    "translation_last_error": row[16],
                    "translation_route_id": row[17],
                    "translation_model": row[18],
                    "translation_updated_at": row[19],
                }
            )
        return result

    async def get_stats_aggregated(self, target_id: str) -> dict[str, Any]:
        """聚合统计查询，返回事件总数、平均分、按分类/来源计数。"""
        if self._db is None:
            return {
                "total_events": 0,
                "avg_news_value_score": None,
                "avg_china_relevance": None,
                "by_classification": {},
                "by_source": {},
                "sentiment_breakdown": {},
                "top_entities": [],
            }
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index WHERE target_id = ?",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        if total == 0:
            return {
                "total_events": 0,
                "avg_news_value_score": None,
                "avg_china_relevance": None,
                "by_classification": {},
                "by_source": {},
                "sentiment_breakdown": {},
                "top_entities": [],
            }

        async with self._db.execute(
            "SELECT AVG(news_value_score), AVG(china_relevance) "
            "FROM event_index WHERE target_id = ? "
            "AND news_value_score IS NOT NULL",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
            avg_score = row[0] if row and row[0] is not None else None
            avg_relevance = row[1] if row and row[1] is not None else None

        by_classification: dict[str, int] = defaultdict(int)
        async with self._db.execute(
            "SELECT classification_l0, COUNT(*) FROM event_index "
            "WHERE target_id = ? AND classification_l0 IS NOT NULL "
            "GROUP BY classification_l0",
            [target_id],
        ) as cursor:
            async for row in cursor:
                by_classification[canonical_l0(row[0])] += row[1]

        by_source: dict[str, int] = {}
        async with self._db.execute(
            "SELECT source_id, COUNT(*) FROM event_index "
            "WHERE target_id = ? AND source_id IS NOT NULL "
            "GROUP BY source_id",
            [target_id],
        ) as cursor:
            async for row in cursor:
                by_source[row[0]] = row[1]

        # Phase 31: sentiment 分布
        sentiment_breakdown: dict[str, int] = {}
        async with self._db.execute(
            "SELECT sentiment, COUNT(*) FROM event_index WHERE target_id = ? GROUP BY sentiment",
            [target_id],
        ) as cursor:
            async for row in cursor:
                key = row[0] if row[0] is not None else "none"
                sentiment_breakdown[key] = row[1]

        # Phase 32: top entities
        top_entities: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT canonical_name, entity_type, mention_count "
            "FROM entities ORDER BY mention_count DESC LIMIT 10"
        ) as cursor:
            async for row in cursor:
                top_entities.append(
                    {
                        "name": row[0],
                        "entity_type": row[1],
                        "mention_count": row[2],
                    }
                )

        return {
            "total_events": total,
            "avg_news_value_score": round(avg_score, 2) if avg_score is not None else None,
            "avg_china_relevance": round(avg_relevance, 2) if avg_relevance is not None else None,
            "by_classification": by_classification,
            "by_source": by_source,
            "sentiment_breakdown": sentiment_breakdown,
            "top_entities": top_entities,
        }

    async def get_event_file_path(self, event_id: str) -> str | None:
        """根据 event_id 查找对应的 .md 文件路径。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT file_path FROM event_index WHERE event_id = ?",
            [event_id],
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_event_index_row(self, target_id: str, event_id: str) -> dict[str, Any] | None:
        """按 target_id + event_id 读取 event_index 行。"""
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id,
                      news_value_score, china_relevance, classification_l0,
                      title_original, published_at, file_path, sentiment,
                      entity_names, topic_tags, metadata_json, created_at,
                      public_translation_ready
               FROM event_index
               WHERE target_id = ? AND event_id = ?""",
            (target_id, event_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "event_id",
            "target_id",
            "stage",
            "source_id",
            "news_value_score",
            "china_relevance",
            "classification_l0",
            "title_original",
            "published_at",
            "file_path",
            "sentiment",
            "entity_names",
            "topic_tags",
            "metadata_json",
            "created_at",
            "public_translation_ready",
        )
        item = dict(zip(cols, row, strict=True))
        item["metadata"] = self._json_loads(item.pop("metadata_json", None))
        return item

    async def update_event_metadata(
        self,
        target_id: str,
        event_id: str,
        metadata_patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Merge metadata patch into event_index.metadata_json for one event."""
        db = await self._ensure_db()
        async with db.execute(
            "SELECT event_id, target_id, title_original, metadata_json "
            "FROM event_index WHERE target_id = ? AND event_id = ?",
            (target_id, event_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        existing = self._json_loads(row[3])
        merged = self._deep_merge_dict(existing, metadata_patch)
        ready = self._publication_ready_from_index_row(
            {
                "event_id": row[0],
                "target_id": row[1],
                "title_original": row[2],
                "metadata": merged,
            }
        )
        await db.execute(
            "UPDATE event_index SET metadata_json = ?, public_translation_ready = ? "
            "WHERE target_id = ? AND event_id = ?",
            (self._json_dumps(merged), ready, target_id, event_id),
        )
        await db.commit()
        return merged

    async def update_event_stage(
        self,
        target_id: str,
        event_id: str,
        new_stage: str,
        new_file_path: str | None = None,
    ) -> dict[str, Any] | None:
        """M-35.2: 更新 event_index 中的 stage 和 file_path。"""
        db = await self._ensure_db()
        if new_file_path is not None:
            await db.execute(
                "UPDATE event_index SET stage = ?, file_path = ? "
                "WHERE target_id = ? AND event_id = ?",
                (new_stage, new_file_path, target_id, event_id),
            )
        else:
            await db.execute(
                "UPDATE event_index SET stage = ? WHERE target_id = ? AND event_id = ?",
                (new_stage, target_id, event_id),
            )
        await db.commit()

        # 返回更新后的行
        return await self.get_event_index_row(target_id, event_id)

    async def get_ai_enrichment_usage(self, usage_date: str) -> dict[str, Any]:
        db = await self._ensure_db()
        async with db.execute(
            """SELECT usage_date, request_count, cooldown_until, last_error, updated_at
               FROM ai_enrichment_usage WHERE usage_date = ?""",
            (usage_date,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {
                "usage_date": usage_date,
                "request_count": 0,
                "cooldown_until": None,
                "last_error": None,
                "updated_at": None,
            }
        return {
            "usage_date": row[0],
            "request_count": int(row[1] or 0),
            "cooldown_until": row[2],
            "last_error": row[3],
            "updated_at": row[4],
        }

    async def increment_ai_enrichment_usage(
        self,
        usage_date: str,
        request_count: int,
    ) -> None:
        db = await self._ensure_db()
        await db.execute(
            """INSERT INTO ai_enrichment_usage
               (usage_date, request_count, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(usage_date) DO UPDATE SET
                   request_count = request_count + excluded.request_count,
                   updated_at = CURRENT_TIMESTAMP""",
            (usage_date, max(0, int(request_count))),
        )
        await db.commit()

    async def set_ai_enrichment_cooldown(
        self,
        usage_date: str,
        cooldown_until: str | None,
        last_error: str | None = None,
    ) -> None:
        db = await self._ensure_db()
        await db.execute(
            """INSERT INTO ai_enrichment_usage
               (usage_date, request_count, cooldown_until, last_error, updated_at)
               VALUES (?, 0, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(usage_date) DO UPDATE SET
                   cooldown_until = excluded.cooldown_until,
                   last_error = excluded.last_error,
                   updated_at = CURRENT_TIMESTAMP""",
            (usage_date, cooldown_until, last_error),
        )
        await db.commit()

    async def record_ai_enrichment_event(
        self,
        target_id: str,
        event_id: str,
        *,
        field_hash: str | None = None,
        status: str = "completed",
        attempts: int = 1,
        last_error: str | None = None,
        model: str | None = None,
        route_id: str | None = None,
    ) -> None:
        db = await self._ensure_db()
        await db.execute(
            """INSERT INTO ai_enrichment_events
               (target_id, event_id, field_hash, status, attempts, last_error, model, route_id,
                updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(target_id, event_id) DO UPDATE SET
                   field_hash = excluded.field_hash,
                   status = excluded.status,
                   attempts = ai_enrichment_events.attempts + excluded.attempts,
                   last_error = excluded.last_error,
                   model = excluded.model,
                   route_id = excluded.route_id,
                   updated_at = CURRENT_TIMESTAMP""",
            (target_id, event_id, field_hash, status, attempts, last_error, model, route_id),
        )
        await db.commit()

    # ------------------------------------------------------------------
