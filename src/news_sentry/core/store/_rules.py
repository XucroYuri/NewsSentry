"""AsyncStore: RulesStoreMixin 功能域。

从 async_store.py 自动拆分。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ._base import AsyncStoreBase
from ._ddl import _ANALYSIS_STAGES


class RulesStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Notification Rules
    # ------------------------------------------------------------------
    # Notification Rules — R1 实时告警引擎
    # ------------------------------------------------------------------

    async def upsert_notification_rule(self, rule: dict[str, Any]) -> None:
        """写入或更新通知规则。rule 必须包含 id 字段。"""
        if self._db is None:
            return
        rule_json = json.dumps(rule, ensure_ascii=False)
        await self._db.execute(
            """INSERT INTO notification_rules (id, user_id, rule_json, enabled, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
               rule_json=excluded.rule_json,
               enabled=excluded.enabled,
               user_id=excluded.user_id,
               updated_at=datetime('now')""",
            (rule["id"], rule.get("user_id", ""), rule_json, int(rule.get("enabled", True))),
        )
        await self._db.commit()

    async def delete_notification_rule(self, rule_id: str) -> bool:
        """删除通知规则。"""
        if self._db is None:
            return False
        cursor = await self._db.execute(
            "DELETE FROM notification_rules WHERE id = ?", [rule_id]
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_notification_rules(
        self, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """列出通知规则，可按用户筛选。"""
        if self._db is None:
            return []
        if user_id:
            async with self._db.execute(
                "SELECT id, user_id, rule_json, enabled, created_at, updated_at "
                "FROM notification_rules WHERE user_id = ? ORDER BY created_at DESC",
                [user_id],
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with self._db.execute(
                "SELECT id, user_id, rule_json, enabled, created_at, updated_at "
                "FROM notification_rules ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
        cols = ("id", "user_id", "rule_json", "enabled", "created_at", "updated_at")
        results: list[dict[str, Any]] = []
        for row in rows:
            d = dict(zip(cols, row, strict=True))
            try:
                d["rule"] = json.loads(d.pop("rule_json"))
            except (json.JSONDecodeError, KeyError):
                d["rule"] = {}
            d["enabled"] = bool(d["enabled"])
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Event Links
    # ------------------------------------------------------------------
    # Event Links (Phase 35)
    # ------------------------------------------------------------------

    async def create_link(
        self,
        source_event_id: str,
        target_event_id: str,
        link_type: str,
        strength: float,
        signals: dict[str, Any],
        target_id: str,
    ) -> None:
        """写入事件关联（UNIQUE 约束去重）。"""
        if self._db is None:
            return
        signals_json = json.dumps(signals, ensure_ascii=False)
        await self._db.execute(
            """INSERT OR IGNORE INTO event_links
               (source_event_id, target_event_id, link_type, strength, signals, target_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_event_id, target_event_id, link_type, strength, signals_json, target_id),
        )
        await self._db.commit()

    async def get_event_links(self, event_id: str) -> list[dict[str, Any]]:
        """获取某事件的所有直接关联（双向）。"""
        if self._db is None:
            return []
        results: list[dict[str, Any]] = []
        # 作为 source 的关联
        async with self._db.execute(
            "SELECT target_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE source_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append(
                    {
                        "linked_event_id": row[0],
                        "link_type": row[1],
                        "strength": row[2],
                        "direction": "forward",
                        "signals": json.loads(row[3]) if row[3] else {},
                        "created_at": row[4],
                    }
                )
        # 作为 target 的关联
        async with self._db.execute(
            "SELECT source_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE target_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append(
                    {
                        "linked_event_id": row[0],
                        "link_type": row[1],
                        "strength": row[2],
                        "direction": "backward",
                        "signals": json.loads(row[3]) if row[3] else {},
                        "created_at": row[4],
                    }
                )
        return results

    async def find_candidates(
        self,
        target_id: str,
        event_id: str,
        days: int = 7,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查找同一 target 最近 N 天的候选关联事件（排除自身）。"""
        if self._db is None:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        capped_limit = max(1, int(limit))
        async with self._db.execute(
            "SELECT event_id, entity_names, topic_tags, published_at, title_original "
            "FROM event_index WHERE target_id = ? AND event_id != ? "
            "AND published_at >= ? ORDER BY published_at DESC LIMIT ?",
            [target_id, event_id, cutoff, capped_limit],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "entity_names", "topic_tags", "published_at", "title_original")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def get_event_chain(
        self,
        event_id: str,
        depth: int = 5,
    ) -> list[dict[str, Any]]:
        """向前向后遍历关联链，返回链上所有事件。"""
        if self._db is None:
            return []
        visited: set[str] = set()
        chain_events: list[dict[str, Any]] = []

        # 收集链上所有 event_id (BFS)
        queue = [event_id]
        visited.add(event_id)
        while queue and len(visited) < depth * 2 + 1:
            current = queue.pop(0)
            linked_ids: set[str] = set()
            async with self._db.execute(
                "SELECT target_event_id FROM event_links WHERE source_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            async with self._db.execute(
                "SELECT source_event_id FROM event_links WHERE target_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            for lid in linked_ids:
                if lid not in visited:
                    visited.add(lid)
                    queue.append(lid)

        # 批量查询事件信息
        if not visited:
            return []
        placeholders = ",".join("?" for _ in visited)
        async with self._db.execute(
            f"SELECT event_id, title_original, published_at, sentiment, "  # noqa: S608
            f"entity_names, topic_tags, news_value_score FROM event_index "
            f"WHERE event_id IN ({placeholders}) ORDER BY published_at ASC",
            list(visited),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            chain_events.append(
                {
                    "event_id": row[0],
                    "title_original": row[1],
                    "published_at": row[2],
                    "sentiment": row[3],
                    "entity_names": row[4],
                    "topic_tags": row[5],
                    "news_value_score": row[6],
                }
            )
        return chain_events

    async def get_active_chains(self, target_id: str) -> list[dict[str, Any]]:
        """获取当前 target 的活跃追踪链（含叙述摘要）。"""
        if self._db is None:
            return []
        # 找所有有 link 的 root events
        async with self._db.execute(
            "SELECT DISTINCT source_event_id FROM event_links WHERE target_id = ?",
            [target_id],
        ) as cursor:
            root_ids = [r[0] for r in await cursor.fetchall()]

        if not root_ids:
            return []

        # 批量获取 narratives
        narrative_map: dict[str, str] = {}
        if root_ids:
            placeholders = ",".join("?" * len(root_ids))
            async with self._db.execute(
                f"SELECT chain_root_id, narrative FROM chain_narratives "  # noqa: S608
                f"WHERE chain_root_id IN ({placeholders})",
                root_ids,
            ) as cursor:
                for row in await cursor.fetchall():
                    narrative_map[row[0]] = row[1]

        chains: list[dict[str, Any]] = []
        for root_id in root_ids:
            chain = await self.get_event_chain(root_id, depth=10)
            if chain:
                latest = chain[-1]
                narr = narrative_map.get(root_id, "")
                chains.append(
                    {
                        "root_event_id": root_id,
                        "event_count": len(chain),
                        "latest_time": latest.get("published_at", ""),
                        "latest_title": latest.get("title_original", ""),
                        "has_narrative": bool(narr),
                        "narrative_summary": narr[:50] + "..." if len(narr) > 50 else narr,
                    }
                )
        return sorted(chains, key=lambda c: c["latest_time"], reverse=True)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Chain Narratives
    # ------------------------------------------------------------------
    # Chain Narratives (Phase 36)
    # ------------------------------------------------------------------

    async def get_narrative(self, chain_root_id: str) -> dict[str, Any] | None:
        """获取链的叙述。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT chain_root_id, target_id, narrative, narrative_hash, "
            "event_count, model_used, created_at, updated_at "
            "FROM chain_narratives WHERE chain_root_id = ?",
            [chain_root_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "chain_root_id",
            "target_id",
            "narrative",
            "narrative_hash",
            "event_count",
            "model_used",
            "created_at",
            "updated_at",
        )
        return dict(zip(cols, row, strict=True))

    async def upsert_narrative(
        self,
        chain_root_id: str,
        target_id: str,
        narrative: str,
        narrative_hash: str,
        event_count: int,
        model_used: str,
    ) -> None:
        """写入或更新链叙述。"""
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT INTO chain_narratives
               (chain_root_id, target_id, narrative, narrative_hash,
                event_count, model_used, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chain_root_id) DO UPDATE SET
                   narrative = excluded.narrative,
                   narrative_hash = excluded.narrative_hash,
                   event_count = excluded.event_count,
                   model_used = excluded.model_used,
                   updated_at = excluded.updated_at""",
            (
                chain_root_id,
                target_id,
                narrative,
                narrative_hash,
                event_count,
                model_used,
                now,
                now,
            ),
        )
        await self._db.commit()

    @staticmethod
    def compute_chain_hash(events: list[dict[str, Any]]) -> str:
        """计算事件列表的 SHA-256 摘要。"""
        from hashlib import sha256

        parts = "|".join(
            f"{e.get('event_id', '')}:{e.get('published_at', '')}:{e.get('title_original', '')}"
            for e in sorted(events, key=lambda x: x.get("event_id", ""))
        )
        return sha256(parts.encode()).hexdigest()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Trend Analysis
    # ------------------------------------------------------------------
    # Trend Analysis (Phase 37)
    # ------------------------------------------------------------------

    async def get_sentiment_daily_counts(
        self, target_id: str, days: int = 14
    ) -> list[dict[str, Any]]:
        """按天统计情感分布，返回 [{day, sentiment, count}, ...]."""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT date(published_at) AS day, sentiment, COUNT(*) AS cnt "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND sentiment IS NOT NULL "
            "GROUP BY day, sentiment ORDER BY day",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "sentiment": r[1], "count": r[2]} for r in rows]

    async def get_topic_daily_counts(self, target_id: str, days: int = 14) -> list[dict[str, Any]]:
        """按天统计每个 topic 的出现次数，返回 [{topic, day, count}, ...]."""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT date(published_at) AS day, topic_tags "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        # Python 层拆分 topic_tags 并按 (topic, day) 聚合
        counts: dict[tuple[str, str], int] = {}
        for day, tags_str in rows:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    key = (tag, day)
                    counts[key] = counts.get(key, 0) + 1
        return [
            {"topic": topic, "day": day, "count": cnt}
            for (topic, day), cnt in sorted(counts.items())
        ]

    async def get_top_topics(
        self, target_id: str, days: int = 7, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取最近 N 天最热主题排名。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT topic_tags FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND topic_tags IS NOT NULL AND topic_tags != ''",
            [target_id, *_ANALYSIS_STAGES, f"-{days}"],
        ) as cursor:
            rows = await cursor.fetchall()
        topic_counts: dict[str, int] = {}
        for (tags_str,) in rows:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    topic_counts[tag] = topic_counts.get(tag, 0) + 1
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"topic": t, "count": c} for t, c in sorted_topics]

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Smart Alerts
    # ------------------------------------------------------------------
    # Smart Alerts (Phase 38)
    # ------------------------------------------------------------------

    async def get_recent_links(
        self,
        target_id: str,
        hours: int = 24,
        limit: int = 500,
        since_run_started_at: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取最近 N 小时新增的 event_links。"""
        if self._db is None:
            return []
        params: list[Any] = [target_id, f"-{hours}"]
        if since_run_started_at is not None:
            params.append(self._sqlite_datetime(since_run_started_at))
            query = (
                "SELECT el.source_event_id, el.target_event_id, el.link_type, "
                "el.strength, el.target_id, ei.title_original "
                "FROM event_links el "
                "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
                "WHERE el.target_id = ? "
                "AND el.created_at >= datetime('now', ? || ' hours') "
                "AND el.created_at >= ? "
                "ORDER BY el.created_at DESC LIMIT ?"
            )
        else:
            query = (
                "SELECT el.source_event_id, el.target_event_id, el.link_type, "
                "el.strength, el.target_id, ei.title_original "
                "FROM event_links el "
                "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
                "WHERE el.target_id = ? "
                "AND el.created_at >= datetime('now', ? || ' hours') "
                "ORDER BY el.created_at DESC LIMIT ?"
            )
        params.append(max(1, int(limit)))
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "source_event_id",
            "target_event_id",
            "link_type",
            "strength",
            "target_id",
            "title_original",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def get_entity_daily_mentions(
        self, entity_name: str, target_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """获取某实体在每天中的提及次数。"""
        if self._db is None:
            return []
        pattern = f"%,{entity_name},%"
        async with self._db.execute(
            "SELECT date(published_at) AS day, COUNT(*) AS cnt "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "AND ',' || entity_names || ',' LIKE ? "
            "GROUP BY day ORDER BY day",
            [target_id, *_ANALYSIS_STAGES, f"-{days}", pattern],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "count": r[1]} for r in rows]

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Dashboard Enhancement
    # ------------------------------------------------------------------
    # Dashboard Enhancement (Phase 39)
    # ------------------------------------------------------------------

    async def get_today_stats(self, target_id: str) -> dict[str, Any]:
        """获取今日 vs 昨日对比统计。"""
        empty = {
            "today_count": 0,
            "today_avg_score": None,
            "today_max_score": None,
            "yesterday_count": 0,
            "yesterday_avg_score": None,
        }
        if self._db is None:
            return empty

        # 今日统计
        async with self._db.execute(
            "SELECT COUNT(*), AVG(news_value_score), MAX(news_value_score) "
            "FROM event_index WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND date(published_at) = date('now')",
            [target_id, *_ANALYSIS_STAGES],
        ) as cursor:
            row = await cursor.fetchone()
        today_count = row[0] if row else 0
        today_avg = row[1] if row and row[1] is not None else None
        today_max = row[2] if row and row[2] is not None else None

        # 昨日统计
        async with self._db.execute(
            "SELECT COUNT(*), AVG(news_value_score) "
            "FROM event_index WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND date(published_at) = date('now', '-1 day')",
            [target_id, *_ANALYSIS_STAGES],
        ) as cursor:
            row = await cursor.fetchone()
        yesterday_count = row[0] if row else 0
        yesterday_avg = row[1] if row and row[1] is not None else None

        return {
            "today_count": today_count,
            "today_avg_score": round(today_avg, 1) if today_avg is not None else None,
            "today_max_score": today_max,
            "yesterday_count": yesterday_count,
            "yesterday_avg_score": round(yesterday_avg, 1) if yesterday_avg is not None else None,
        }

    async def get_top_events(
        self, target_id: str, days: int = 7, limit: int = 5
    ) -> list[dict[str, Any]]:
        """获取最近 N 天最高分事件。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT event_id, title_original, news_value_score, source_id, published_at "
            "FROM event_index "
            "WHERE target_id = ? AND stage IN (?, ?, ?) "
            "AND published_at >= date('now', ? || ' days') "
            "ORDER BY news_value_score DESC LIMIT ?",
            [target_id, *_ANALYSIS_STAGES, f"-{days}", limit],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "title_original", "news_value_score", "source_id", "published_at")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    # ------------------------------------------------------------------
