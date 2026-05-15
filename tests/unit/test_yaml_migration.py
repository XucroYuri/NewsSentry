"""Tests for core/yaml_migration.py — YAML → SQLite 数据迁移。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.yaml_migration import (
    migrate_yaml_to_sqlite,
    should_migrate,
)


class TestShouldMigrate:
    """should_migrate — 判断是否需要迁移。"""

    def test_returns_true_when_yaml_exists_db_missing(self, tmp_path: Path):
        """YAML 文件存在但 state.db 不存在 → 需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("test-event: '2026-01-01T00:00:00Z'")

        db_path = tmp_path / "state.db"
        assert db_path.exists() is False
        assert should_migrate(memory_dir, db_path) is True

    def test_returns_false_when_db_exists(self, tmp_path: Path):
        """state.db 已存在 → 不需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("x: y")

        db_path = tmp_path / "state.db"
        db_path.write_text("")  # 文件存在即可
        assert should_migrate(memory_dir, db_path) is False

    def test_returns_false_when_yaml_missing(self, tmp_path: Path):
        """YAML 文件不存在 → 不需要迁移。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        db_path = tmp_path / "state.db"

        assert should_migrate(memory_dir, db_path) is False


class TestMigrateYamlToSqlite:
    """migrate_yaml_to_sqlite — 迁移执行。"""

    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncStore:
        db_path = tmp_path / "state.db"
        s = AsyncStore(db_path)
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_migrates_known_ids(self, tmp_path: Path, store: AsyncStore):
        """known_item_ids.yaml 中的 ID 应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        known_ids_data = {
            "ne-italy-ansa-20260515-a1b2c3d4": "2026-05-15T10:00:00+00:00",
            "ne-italy-corriere-20260515-e5f6a7b8": "2026-05-15T11:00:00+00:00",
            "ne-italy-repubblica-20260515-c1d2e3f4": "2026-05-15T12:00:00+00:00",
        }
        with open(memory_dir / "known_item_ids.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(known_ids_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["known_ids_migrated"] == 3

        # 验证数据在 SQLite 中
        for eid in known_ids_data:
            assert await store.is_known(eid) is True

    @pytest.mark.asyncio
    async def test_migrates_source_health(self, tmp_path: Path, store: AsyncStore):
        """source_health.yaml 中的数据应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        health_data = {
            "ansa": {
                "last_success_at": "2026-05-15T10:00:00Z",
                "last_failure_at": None,
                "consecutive_failures": 0,
                "last_error": None,
                "total_runs": 10,
                "total_failures": 2,
            },
            "corriere": {
                "last_success_at": None,
                "last_failure_at": "2026-05-15T11:00:00Z",
                "consecutive_failures": 5,
                "last_error": "timeout",
                "total_runs": 20,
                "total_failures": 8,
            },
        }
        with open(memory_dir / "source_health.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(health_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["source_health_migrated"] == 2

        health_ansa = await store.get_source_health("ansa")
        assert health_ansa is not None
        assert health_ansa["status"] == "healthy"
        meta = health_ansa.get("metadata", {})
        assert meta.get("total_runs") == 10
        assert meta.get("consecutive_failures") == 0

        health_corriere = await store.get_source_health("corriere")
        assert health_corriere is not None
        assert health_corriere["status"] == "down"
        meta = health_corriere.get("metadata", {})
        assert meta.get("consecutive_failures") == 5

    @pytest.mark.asyncio
    async def test_migrates_cursors(self, tmp_path: Path, store: AsyncStore):
        """cursors.yaml 中的数据应迁移到 SQLite。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        cursors_data = {
            "ansa": 'etag-"abc123"',
            "corriere": "2026-05-15T09:00:00Z",
        }
        with open(memory_dir / "cursors.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(cursors_data, f, allow_unicode=True)

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result["cursors_migrated"] == 2

        assert await store.get_cursor("ansa") == 'etag-"abc123"'
        assert await store.get_cursor("corriere") == "2026-05-15T09:00:00Z"

    @pytest.mark.asyncio
    async def test_migrates_empty_yaml_gracefully(self, tmp_path: Path, store: AsyncStore):
        """YAML 文件存在但为空时应正常处理。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "known_item_ids.yaml").write_text("{}\n")
        (memory_dir / "source_health.yaml").write_text("{}\n")
        (memory_dir / "cursors.yaml").write_text("{}\n")

        result = await migrate_yaml_to_sqlite(memory_dir, store)
        # 空 YAML 不产生迁移计数
        assert result["known_ids_migrated"] == 0
        assert result["source_health_migrated"] == 0
        assert result["cursors_migrated"] == 0

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path: Path, store: AsyncStore):
        """重复迁移不应报错也不产生重复数据。"""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        known_ids_data = {"ne-test-migrate-001": "2026-05-15T10:00:00Z"}
        with open(memory_dir / "known_item_ids.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(known_ids_data, f, allow_unicode=True)

        result1 = await migrate_yaml_to_sqlite(memory_dir, store)
        assert result1["known_ids_migrated"] == 1

        result2 = await migrate_yaml_to_sqlite(memory_dir, store)
        # 第二次迁移：已知 ID 已存在，计数应归零
        assert result2["known_ids_migrated"] == 0
