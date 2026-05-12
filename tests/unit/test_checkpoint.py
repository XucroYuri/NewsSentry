from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.core.checkpoint import CheckpointManager, ErrorType, StageCheckpoint


def test_checkpoint_save_and_load():
    cp = StageCheckpoint(
        stage="collect",
        cursor="page=3",
        processed_ids={"ne-italy-source1-20260511-abc12345", "ne-italy-source2-20260511-def67890"},
    )
    assert cp.stage == "collect"
    assert len(cp.processed_ids) == 2


def test_checkpoint_manager_roundtrip():
    with TemporaryDirectory() as tmp:
        mgr = CheckpointManager(Path(tmp))
        cp = StageCheckpoint(
            stage="filter",
            cursor="offset=100",
            processed_ids={"ne-italy-source1-20260511-xxx"},
        )
        mgr.save(cp)
        loaded = mgr.load("filter")
        assert loaded is not None
        assert loaded.stage == "filter"
        assert loaded.cursor == "offset=100"
        assert "ne-italy-source1-20260511-xxx" in loaded.processed_ids


def test_checkpoint_load_nonexistent():
    with TemporaryDirectory() as tmp:
        mgr = CheckpointManager(Path(tmp))
        assert mgr.load("collect") is None


def test_error_type_enum():
    assert ErrorType.TRANSIENT.value == "transient"
    assert ErrorType.DATA.value == "data"
    assert ErrorType.FATAL.value == "fatal"
