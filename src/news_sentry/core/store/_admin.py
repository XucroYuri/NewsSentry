"""AsyncStore: AdminStoreMixin 功能域。

从 async_store.py 自动拆分。
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ._base import AsyncStoreBase


class AdminStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Governance / Maintenance
    # ------------------------------------------------------------------
    # Governance / Maintenance (Phase 40)
    # ------------------------------------------------------------------

    async def prune_old_data(self, target_id: str, max_age_days: int = 30) -> dict[str, int]:
        """清理过期数据：事件、孤儿 links、旧 known_ids。"""
        result: dict[str, int] = {
            "deleted_events": 0,
            "deleted_links": 0,
            "deleted_ids": 0,
        }
        if self._db is None:
            return result

        cutoff = f"-{max_age_days}"

        # 1. 删除过期事件
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_index "
            "WHERE target_id = ? AND created_at < date('now', ? || ' days')",
            [target_id, cutoff],
        ) as cursor:
            row = await cursor.fetchone()
        result["deleted_events"] = row[0] if row else 0
        if result["deleted_events"] > 0:
            await self._db.execute(
                "DELETE FROM event_index "
                "WHERE target_id = ? AND created_at < date('now', ? || ' days')",
                [target_id, cutoff],
            )

        # 2. 删除孤儿 links（source_event_id 不在 event_index 中）
        async with self._db.execute(
            "SELECT COUNT(*) FROM event_links "
            "WHERE target_id = ? "
            "AND source_event_id NOT IN (SELECT event_id FROM event_index)",
            [target_id],
        ) as cursor:
            row = await cursor.fetchone()
        result["deleted_links"] = row[0] if row else 0
        if result["deleted_links"] > 0:
            await self._db.execute(
                "DELETE FROM event_links "
                "WHERE target_id = ? "
                "AND source_event_id NOT IN (SELECT event_id FROM event_index)",
                [target_id],
            )

        # 3. 清理旧 known_ids
        result["deleted_ids"] = await self.prune_old_ids(max_age_days)  # type: ignore[attr-defined]

        await self._db.commit()
        return result

    async def backup_db(self, backup_dir: Path) -> Path:
        """备份数据库到指定目录。"""
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"state_{timestamp}.db"

        if self._db is not None:
            await self._db.commit()
            with sqlite3.connect(backup_path) as target:
                await self._db.backup(target)

        # 清理旧备份（保留最近 7 个）
        backups = sorted(backup_dir.glob("state_*.db"))
        if len(backups) > 7:
            for old_backup in backups[:-7]:
                old_backup.unlink(missing_ok=True)

        return backup_path

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Feedback + Alert History
    # ------------------------------------------------------------------
    # Feedback + Alert History (Phase 41)
    # ------------------------------------------------------------------

    async def save_feedback(
        self,
        target_id: str,
        event_id: str,
        verdict_type: str,
        comment: str = "",
        original_recommendation: str | None = None,
        keywords_matched: list[str] | None = None,
        source_id: str | None = None,
    ) -> int:
        """保存人工反馈，返回记录 ID。"""
        if self._db is None:
            return 0
        async with self._db.execute(
            """INSERT INTO feedback
               (event_id, target_id, verdict_type, original_recommendation,
                comment, keywords_matched, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                target_id,
                verdict_type,
                original_recommendation,
                comment or None,
                json.dumps(keywords_matched) if keywords_matched else None,
                source_id,
            ),
        ) as cursor:
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_feedback(self, target_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """获取反馈列表。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT id, event_id, target_id, verdict_type,
                      original_recommendation, comment, keywords_matched,
                      source_id, created_at
               FROM feedback
               WHERE target_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def get_feedback_stats(self, target_id: str) -> dict[str, int]:
        """获取反馈统计。"""
        if self._db is None:
            return {"total": 0, "publish_override": 0, "archive_override": 0, "comment": 0}
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT verdict_type, COUNT(*) as cnt
               FROM feedback WHERE target_id = ?
               GROUP BY verdict_type""",
            (target_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        counts = {r["verdict_type"]: r["cnt"] for r in rows}
        return {
            "total": sum(counts.values()),
            "publish_override": counts.get("publish_override", 0),
            "archive_override": counts.get("archive_override", 0),
            "comment": counts.get("comment", 0),
        }

    async def save_alert_history(self, target_id: str, alerts: list[dict[str, Any]]) -> int:
        """批量保存告警记录，返回插入数量。"""
        if not alerts or self._db is None:
            return 0
        rows = []
        for alert in alerts:
            details = alert.get("details", {})
            rows.append(
                (
                    target_id,
                    str(alert.get("alert_key") or self._alert_history_key(target_id, alert)),
                    alert["type"],
                    alert["severity"],
                    alert["message"],
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                )
            )
        cursor = await self._db.executemany(
            """INSERT OR IGNORE INTO alert_history
               (target_id, alert_key, alert_type, severity, message, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._db.commit()
        return max(int(cursor.rowcount or 0), 0)

    @staticmethod
    def _alert_history_key(target_id: str, alert: dict[str, Any]) -> str:
        """计算告警历史幂等键。"""
        details = json.dumps(
            alert.get("details", {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return ":".join(
            [
                target_id,
                str(alert.get("type") or ""),
                str(alert.get("severity") or ""),
                details,
            ]
        )

    async def get_alert_history(self, target_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """获取历史告警。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT id, target_id, alert_key, alert_type, severity,
                      message, details, created_at
               FROM alert_history
               WHERE target_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def get_event_by_id(self, target_id: str, event_id: str) -> dict[str, Any] | None:
        """根据 event_id 查找事件详情。"""
        if self._db is None:
            return None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            """SELECT event_id, target_id, stage, source_id,
                      news_value_score, china_relevance, classification_l0,
                      title_original, published_at, file_path, sentiment,
                      entity_names, topic_tags, created_at
               FROM event_index
               WHERE target_id = ? AND event_id = ?""",
            (target_id, event_id),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def get_user(self, username: str) -> dict[str, Any] | None:
        """获取用户信息。"""
        if self._db is None:
            return None
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, password_hash, salt, role, api_key, must_change_pw, "
            "       created_at, updated_at FROM users WHERE username = ?",
            (username,),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        return dict(row) if row else None

    async def create_user(
        self,
        username: str,
        password_hash: str,
        salt: str,
        role: str = "admin",
        api_key: str | None = None,
        must_change_pw: int = 0,
    ) -> bool:
        """创建用户，返回是否成功。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO users (username, password_hash, salt, role, api_key, "
                "                   must_change_pw, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, salt, role, api_key, must_change_pw, now, now),
            )
            await self._db.commit()
            return True
        except Exception:
            return False

    async def update_user_password(self, username: str, password_hash: str, salt: str) -> bool:
        """更新用户密码。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE users SET password_hash = ?, salt = ?, must_change_pw = 0, "
            "                 updated_at = ? WHERE username = ?",
            (password_hash, salt, now, username),
        )
        await self._db.commit()
        return self._db.total_changes > 0

    async def update_user_api_key(self, username: str, api_key: str | None) -> bool:
        """更新用户的 API Key。"""
        if self._db is None:
            return False
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE users SET api_key = ?, updated_at = ? WHERE username = ?",
            (api_key, now, username),
        )
        await self._db.commit()
        return self._db.total_changes > 0

    async def list_users(self) -> list[dict[str, Any]]:
        """列出所有用户。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, api_key, must_change_pw, created_at, updated_at FROM users"
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    async def delete_user(self, username: str) -> bool:
        """删除用户。"""
        if self._db is None:
            return False
        await self._db.execute("DELETE FROM users WHERE username = ?", (username,))
        await self._db.commit()
        return self._db.total_changes > 0

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Sessions —
    # ------------------------------------------------------------------
    # Sessions — Token 持久化
    # ------------------------------------------------------------------

    async def create_session(
        self, token: str, username: str, role: str, has_api_key: bool, ttl: float
    ) -> None:
        """创建或刷新 session token。"""
        if self._db is None:
            return
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        await self._db.execute(
            "INSERT OR REPLACE INTO sessions (token_hash, username, role, has_api_key, "
            "        created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (token_hash, username, role, int(has_api_key), now, now + ttl),
        )
        await self._db.commit()

    async def get_session(self, token: str) -> dict[str, Any] | None:
        """根据 token 查询 session。"""
        if self._db is None:
            return None
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, has_api_key, created_at, expires_at "
            "FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ) as cursor:
            row = await cursor.fetchone()
        self._db.row_factory = None
        if row is None:
            return None
        info = dict(row)
        info["has_api_key"] = bool(info["has_api_key"])
        return info

    async def delete_session(self, token: str) -> bool:
        """删除单个 session。"""
        if self._db is None:
            return False
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        await self._db.commit()
        return self._db.total_changes > 0

    async def delete_sessions_for_user(self, username: str) -> int:
        """删除指定用户的所有 session，返回删除数。"""
        if self._db is None:
            return 0
        cur = await self._db.execute("DELETE FROM sessions WHERE username = ?", (username,))
        await self._db.commit()
        return cur.rowcount

    async def delete_expired_sessions(self) -> int:
        """清理过期 session，返回删除数。"""
        if self._db is None:
            return 0
        cur = await self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        await self._db.commit()
        return cur.rowcount

    async def list_active_sessions(self) -> list[dict[str, Any]]:
        """列出所有未过期的 session。"""
        if self._db is None:
            return []
        self._db.row_factory = aiosqlite.Row
        async with self._db.execute(
            "SELECT username, role, has_api_key, created_at, expires_at "
            "FROM sessions WHERE expires_at >= ?",
            (time.time(),),
        ) as cursor:
            rows = await cursor.fetchall()
        self._db.row_factory = None
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Notifications —
    # ------------------------------------------------------------------
    # Notifications — 通知设置持久化（替代 notifications.json）
    # ------------------------------------------------------------------

    async def get_notifications(self) -> dict[str, Any]:
        """获取通知设置，不存在则返回空 dict。"""
        if self._db is None:
            return {}
        async with self._db.execute("SELECT config FROM notifications WHERE id = 1") as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row[0])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return {}

    async def save_notifications(self, config: dict[str, Any]) -> None:
        """写入通知设置。"""
        if self._db is None:
            return
        config_json = json.dumps(config, ensure_ascii=False)
        await self._db.execute(
            "INSERT OR REPLACE INTO notifications (id, config) VALUES (1, ?)",
            (config_json,),
        )
        await self._db.commit()

