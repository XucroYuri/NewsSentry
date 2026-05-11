"""Integration tests for checkpoint-based recovery."""

from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.core.checkpoint import CheckpointManager, ErrorType, StageCheckpoint


def test_simulate_interrupted_run():
    """模拟 bounded run 中断后从 checkpoint 恢复。"""
    with TemporaryDirectory() as tmp:
        memory_dir = Path(tmp) / "memory"
        mgr = CheckpointManager(memory_dir)

        # 第一轮：collect 完成，filter 中途中断
        collect_cp = StageCheckpoint(
            stage="collect",
            cursor="page=5",
            processed_ids={"evt-1", "evt-2", "evt-3"},
        )
        mgr.save(collect_cp)

        # 模拟重启：从 checkpoint 恢复
        restored = mgr.load("collect")
        assert restored is not None
        assert restored.cursor == "page=5"

        # 第二轮：filter 完成
        filter_cp = StageCheckpoint(
            stage="filter",
            cursor="offset=50",
            processed_ids=collect_cp.processed_ids - {"evt-3"},
        )
        mgr.save(filter_cp)
        restored_filter = mgr.load("filter")
        assert "evt-1" in restored_filter.processed_ids
        assert "evt-3" not in restored_filter.processed_ids


def test_all_error_types_distinct():
    types = {ErrorType.TRANSIENT, ErrorType.DATA, ErrorType.FATAL}
    assert len(types) == 3
