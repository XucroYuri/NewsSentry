"""YAML → SQLite 数据迁移。

检测 data/{target_id}/memory/ 下的 YAML 文件是否存在但 state.db 不存在。
自动迁移已知 ID、源健康数据、游标到 SQLite。迁移完成后 YAML 文件保留但不再写入。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import yaml

from news_sentry.core.async_store import AsyncStore

logger = logging.getLogger(__name__)

# ── YAML 文件名 ──────────────────────────────────────────────────────
_KNOWN_IDS_FILE = "known_item_ids.yaml"
_SOURCE_HEALTH_FILE = "source_health.yaml"
_CURSORS_FILE = "cursors.yaml"


def should_migrate(memory_dir: Path, db_path: Path) -> bool:
    """判断是否需要执行 YAML → SQLite 迁移。

    条件：memory_dir 下的 YAML 文件存在 且 state.db 不存在。

    Args:
        memory_dir: memory/ 目录路径。
        db_path: state.db 文件路径。

    Returns:
        True 如果应该执行迁移。
    """
    if db_path.exists():
        return False

    for filename in (_KNOWN_IDS_FILE, _SOURCE_HEALTH_FILE, _CURSORS_FILE):
        if (memory_dir / filename).exists():
            return True
    return False


async def migrate_yaml_to_sqlite(
    memory_dir: Path,
    store: AsyncStore,
) -> dict[str, int]:
    """执行 YAML 到 SQLite 的迁移。

    Args:
        memory_dir: memory/ 目录路径（包含 YAML 文件）。
        store: 已初始化的 AsyncStore 实例。

    Returns:
        dict: {"known_ids_migrated": N, "source_health_migrated": N, "cursors_migrated": N}
    """
    result: dict[str, int] = {
        "known_ids_migrated": 0,
        "source_health_migrated": 0,
        "cursors_migrated": 0,
    }

    db: aiosqlite.Connection = store._db  # type: ignore[assignment]
    if db is None:
        return result

    # ── 迁移 known_ids ──────────────────────────────────────────
    known_ids_path = memory_dir / _KNOWN_IDS_FILE
    if known_ids_path.exists():
        try:
            with open(known_ids_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and len(data) > 0:
                inserted = 0
                for event_id, seen_at in data.items():
                    # 检查是否已存在，只计数实际新插入的
                    if not await store.is_known(str(event_id)):
                        await db.execute(
                            "INSERT OR IGNORE INTO known_ids (event_id, seen_at) VALUES (?, ?)",
                            (str(event_id), str(seen_at)),
                        )
                        inserted += 1
                await db.commit()
                result["known_ids_migrated"] = inserted
                logger.info("迁移 known_ids: %d 条（新插入）", inserted)
        except Exception:
            logger.warning("known_ids 迁移失败", exc_info=True)

    # ── 迁移 source_health ──────────────────────────────────────
    health_path = memory_dir / _SOURCE_HEALTH_FILE
    if health_path.exists():
        try:
            with open(health_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and len(data) > 0:
                for source_id, entry in data.items():
                    if not isinstance(entry, dict):
                        continue

                    consecutive = entry.get("consecutive_failures", 0)
                    if isinstance(consecutive, (int, float)) and consecutive >= 5:
                        status = "down"
                    elif isinstance(consecutive, (int, float)) and consecutive > 0:
                        status = "degraded"
                    else:
                        status = "healthy"

                    last_check = (
                        entry.get("last_success_at")
                        or entry.get("last_failure_at")
                        or datetime.now(UTC).isoformat()
                    )
                    error_count = int(consecutive) if isinstance(consecutive, (int, float)) else 0

                    meta_json = json.dumps(entry, ensure_ascii=False)
                    await db.execute(
                        """INSERT OR REPLACE INTO source_health
                           (source_id, status, last_check, error_count, metadata)
                           VALUES (?, ?, ?, ?, ?)""",
                        (str(source_id), status, str(last_check), error_count, meta_json),
                    )
                    result["source_health_migrated"] += 1
                await db.commit()
                logger.info("迁移 source_health: %d 条", result["source_health_migrated"])
        except Exception:
            logger.warning("source_health 迁移失败", exc_info=True)

    # ── 迁移 cursors ────────────────────────────────────────────
    cursors_path = memory_dir / _CURSORS_FILE
    if cursors_path.exists():
        try:
            with open(cursors_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and len(data) > 0:
                for source_id, cursor_val in data.items():
                    now = datetime.now(UTC).isoformat()
                    await db.execute(
                        """INSERT OR REPLACE INTO cursors (source_id, cursor, updated_at)
                           VALUES (?, ?, ?)""",
                        (str(source_id), str(cursor_val), now),
                    )
                    result["cursors_migrated"] += 1
                await db.commit()
                logger.info("迁移 cursors: %d 条", result["cursors_migrated"])
        except Exception:
            logger.warning("cursors 迁移失败", exc_info=True)

    return result
