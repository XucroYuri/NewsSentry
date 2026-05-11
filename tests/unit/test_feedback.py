from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.skills.judge.feedback import FeedbackStore, JudgeFeedback


def test_feedback_record():
    fb = JudgeFeedback(
        event_id="ne-italy-source1-20260511-abc12345",
        run_id="r-001",
        automated_confidence=85,
        human_correct=True,
        notes="研判正确",
    )
    assert fb.automated_confidence == 85
    assert fb.human_correct is True


def test_feedback_store_append():
    with TemporaryDirectory() as tmp:
        store = FeedbackStore(Path(tmp))
        store.append(JudgeFeedback(
            event_id="evt-1", run_id="r-001",
            automated_confidence=70, human_correct=False,
            notes="误判：政治人物误标为商人",
        ))
        records = store.load_all()
        assert len(records) == 1
        assert records[0].event_id == "evt-1"


def test_feedback_stats():
    with TemporaryDirectory() as tmp:
        store = FeedbackStore(Path(tmp))
        store.append(JudgeFeedback(
            event_id="a", run_id="r-001",
            automated_confidence=80, human_correct=True, notes="",
        ))
        store.append(JudgeFeedback(
            event_id="b", run_id="r-001",
            automated_confidence=60, human_correct=False, notes="",
        ))
        store.append(JudgeFeedback(
            event_id="c", run_id="r-001",
            automated_confidence=90, human_correct=True, notes="",
        ))
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["correct"] == 2
        assert abs(stats["accuracy"] - 2/3) < 0.001


def test_feedback_load_all_empty():
    """空文件路径应返回空列表。"""
    with TemporaryDirectory() as tmp:
        store = FeedbackStore(Path(tmp))
        records = store.load_all()
        assert records == []


def test_feedback_stats_empty():
    """无记录时统计应返回零值。"""
    with TemporaryDirectory() as tmp:
        store = FeedbackStore(Path(tmp))
        stats = store.stats()
        assert stats["total"] == 0
        assert stats["correct"] == 0
        assert stats["accuracy"] == 0.0
