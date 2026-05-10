"""ReviewQueue 模块测试。

覆盖：入队、ID 生成、序号自增、未解决筛选、解决标记、持久化、多种类型。
"""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from news_sentry.core.review_queue import ReviewQueue, ReviewQueueItem


@pytest.fixture
def review_queue(tmp_path: Path) -> ReviewQueue:
    """创建使用临时目录的 ReviewQueue 实例。"""
    return ReviewQueue(memory_root=tmp_path)


class TestEnqueue:
    """入队功能测试。"""

    def test_enqueue_creates_item(self, review_queue: ReviewQueue):
        """enqueue 应创建条目并可在 get_unresolved() 中查到。"""
        item = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="low_quality",
            source_run_id="test-run",
            detail="测试低质量内容",
            event_id="event-123",
        )
        review_queue.enqueue(item)

        unresolved = review_queue.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].item_type == "low_quality"
        assert unresolved[0].detail == "测试低质量内容"
        assert unresolved[0].source_run_id == "test-run"

    def test_enqueue_auto_id_format(self, review_queue: ReviewQueue):
        """item_id 应匹配 rq-{run_id}-{seq:03d} 格式。"""
        item = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="auth_required",
            source_run_id="run-abc",
            detail="需要认证",
        )
        review_queue.enqueue(item)

        unresolved = review_queue.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].item_id.startswith("rq-run-abc-")
        # 验证序号格式为 001
        assert unresolved[0].item_id == "rq-run-abc-001"

    def test_enqueue_multiple_increments_seq(self, review_queue: ReviewQueue):
        """同一 run_id 下多次入队，序号应自增 (001, 002, 003)。"""
        run_id = "seq-test"
        for i in range(3):
            item = ReviewQueueItem(
                item_id="",
                created_at=datetime.now(UTC),
                item_type="sandbox_violation",
                source_run_id=run_id,
                detail=f"违规 {i + 1}",
            )
            review_queue.enqueue(item)

        unresolved = review_queue.get_unresolved()
        assert len(unresolved) == 3
        ids = sorted([item.item_id for item in unresolved])
        assert ids == ["rq-seq-test-001", "rq-seq-test-002", "rq-seq-test-003"]


class TestUnresolved:
    """未解决筛选测试。"""

    def test_get_unresolved_only_returns_unresolved(self, review_queue: ReviewQueue):
        """入队 2 条，解决 1 条后，仅返回 1 条未解决。"""
        run_id = "unresolved-test"
        item1 = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="low_quality",
            source_run_id=run_id,
            detail="item-1",
        )
        item2 = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="low_quality",
            source_run_id=run_id,
            detail="item-2",
        )
        review_queue.enqueue(item1)
        review_queue.enqueue(item2)

        unresolved_before = review_queue.get_unresolved()
        assert len(unresolved_before) == 2

        # 解决第一条
        review_queue.resolve(unresolved_before[0].item_id)

        unresolved_after = review_queue.get_unresolved()
        assert len(unresolved_after) == 1
        assert unresolved_after[0].detail == "item-2"


class TestResolve:
    """解决功能测试。"""

    def test_resolve_marks_resolved(self, review_queue: ReviewQueue):
        """resolve 后 resolved=True 且 resolved_at 已设置。"""
        item = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="sandbox_violation",
            source_run_id="resolve-test",
            detail="待解决",
        )
        review_queue.enqueue(item)

        unresolved = review_queue.get_unresolved()
        item_id = unresolved[0].item_id

        review_queue.resolve(item_id)

        # 重新加载后检查
        all_items = review_queue.get_unresolved()
        # 已解决不应在 unresolved 中
        assert len(all_items) == 0

        # 通过 _load 内部方法验证
        raw_items = review_queue._load()
        resolved_item = raw_items[0]
        assert resolved_item["resolved"] is True
        assert resolved_item["resolved_at"] is not None

    def test_resolve_nonexistent_raises(self, review_queue: ReviewQueue):
        """解决不存在的 item_id 应抛出 KeyError。"""
        with pytest.raises(KeyError):
            review_queue.resolve("rq-nonexistent-001")


class TestPersistence:
    """持久化测试。"""

    def test_review_queue_persistence(self, tmp_path: Path):
        """创建队列、写入条目，新实例用相同 memory_root 应加载到条目。"""
        queue1 = ReviewQueue(memory_root=tmp_path)
        item = ReviewQueueItem(
            item_id="",
            created_at=datetime.now(UTC),
            item_type="auth_required",
            source_run_id="persist-run",
            detail="持久化测试",
        )
        queue1.enqueue(item)

        # 新实例加载
        queue2 = ReviewQueue(memory_root=tmp_path)
        unresolved = queue2.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0].detail == "持久化测试"
        assert unresolved[0].item_id == "rq-persist-run-001"


class TestItemTypes:
    """多种条目类型测试。"""

    def test_enqueue_different_types(self, review_queue: ReviewQueue):
        """入队 sandbox_violation、auth_required、low_quality 三种类型，均应正常工作。"""
        run_id = "types-test"
        types: list[tuple[str, str]] = [
            ("sandbox_violation", "沙箱违规"),
            ("auth_required", "需要认证"),
            ("low_quality", "低质量内容"),
        ]

        for item_type, detail in types:
            item = ReviewQueueItem(
                item_id="",
                created_at=datetime.now(UTC),
                item_type=item_type,  # type: ignore[arg-type]
                source_run_id=run_id,
                detail=detail,
            )
            review_queue.enqueue(item)

        unresolved = review_queue.get_unresolved()
        assert len(unresolved) == 3
        item_types = {item.item_type for item in unresolved}
        assert item_types == {"sandbox_violation", "auth_required", "low_quality"}
