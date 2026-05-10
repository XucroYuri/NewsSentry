"""Tests for core/memory.py — known IDs, source health, cursors, provider stats, concurrency."""
from __future__ import annotations

import threading
from pathlib import Path

from news_sentry.core.memory import Memory

# ------------------------------------------------------------------
# Known IDs
# ------------------------------------------------------------------


def test_is_known_returns_false_for_new_id(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    assert mem.is_known("ne-italy-ansa-20260509-a1b2c3d4") is False


def test_mark_known_and_is_known(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    eid = "ne-italy-ansa-20260509-b5c6d7e8"
    mem.mark_known(eid)
    assert mem.is_known(eid) is True


def test_mark_known_persists_across_instances(tmp_path: Path) -> None:
    eid = "ne-italy-repubblica-20260509-c1d2e3f4"
    mem1 = Memory(tmp_path)
    mem1.mark_known(eid)
    # 新建实例，从磁盘重新加载
    mem2 = Memory(tmp_path)
    assert mem2.is_known(eid) is True


def test_mark_known_writes_timestamp(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.mark_known("ne-italy-ansa-20260509-d4e5f6a7")
    path = tmp_path / "known_item_ids.yaml"
    assert path.exists()
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "ne-italy-ansa-20260509-d4e5f6a7" in data


def test_prune_old_ids_removes_stale_entries(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    # 手动插入一个"旧"时间戳来绕过实时时间依赖
    mem._known_ids["old-event"] = "2020-01-01T00:00:00+00:00"
    mem._known_ids["recent-event"] = "2099-01-01T00:00:00+00:00"
    removed = mem.prune_old_ids(ttl_days=30)
    assert removed == 1
    assert mem.is_known("old-event") is False
    assert mem.is_known("recent-event") is True


# ------------------------------------------------------------------
# Source Health
# ------------------------------------------------------------------


def test_get_source_health_empty_for_unknown_source(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    assert mem.get_source_health("ansa") == {}


def test_update_source_health_success(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_source_health("ansa", success=True)
    health = mem.get_source_health("ansa")
    assert health["total_runs"] == 1
    assert health["total_failures"] == 0
    assert health["consecutive_failures"] == 0
    assert health["last_success_at"] is not None
    assert health["last_failure_at"] is None


def test_update_source_health_failure(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_source_health("ansa", success=False, error_msg="timeout")
    health = mem.get_source_health("ansa")
    assert health["total_failures"] == 1
    assert health["total_runs"] == 1
    assert health["consecutive_failures"] == 1
    assert health["last_error"] == "timeout"


def test_update_source_health_tracks_total_runs_and_failures(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=False, error_msg="e1")
    health = mem.get_source_health("ansa")
    assert health["total_runs"] == 3
    assert health["total_failures"] == 1
    assert health["consecutive_failures"] == 1


def test_source_health_persists(tmp_path: Path) -> None:
    mem1 = Memory(tmp_path)
    mem1.update_source_health("ansa", success=True)
    mem2 = Memory(tmp_path)
    health = mem2.get_source_health("ansa")
    assert health["total_runs"] == 1


def test_get_source_health_returns_copy(tmp_path: Path) -> None:
    """验证 get_source_health 返回的是副本，修改不会影响内部状态。"""
    mem = Memory(tmp_path)
    mem.update_source_health("ansa", success=True)
    health = mem.get_source_health("ansa")
    health["total_runs"] = 999
    assert mem.get_source_health("ansa")["total_runs"] == 1


# ------------------------------------------------------------------
# record_source_health (convenience method)
# ------------------------------------------------------------------


def test_record_source_health_tracks_consecutive_failures(tmp_path: Path) -> None:
    """记录多次失败应递增 consecutive_failures，成功应重置为 0。"""
    mem = Memory(tmp_path)
    mem.record_source_health("ansa", success=False, error_msg="e1")
    mem.record_source_health("ansa", success=False, error_msg="e2")
    health = mem.get_source_health("ansa")
    assert health["consecutive_failures"] == 2
    assert health["total_failures"] == 2
    # 成功后 consecutive_failures 重置
    mem.record_source_health("ansa", success=True)
    health = mem.get_source_health("ansa")
    assert health["consecutive_failures"] == 0
    assert health["total_failures"] == 2  # total_failures 不重置


def test_record_source_health_tracks_total_runs(tmp_path: Path) -> None:
    """每次调用 record_source_health 都应递增 total_runs。"""
    mem = Memory(tmp_path)
    mem.record_source_health("ansa", success=True)
    mem.record_source_health("ansa", success=False, error_msg="timeout")
    mem.record_source_health("ansa", success=True)
    health = mem.get_source_health("ansa")
    assert health["total_runs"] == 3


def test_record_source_health_resets_consecutive_on_success(tmp_path: Path) -> None:
    """成功调用后 consecutive_failures 必须重置为 0。"""
    mem = Memory(tmp_path)
    mem.record_source_health("ansa", success=False, error_msg="e1")
    mem.record_source_health("ansa", success=False, error_msg="e2")
    assert mem.get_source_health("ansa")["consecutive_failures"] == 2
    mem.record_source_health("ansa", success=True)
    assert mem.get_source_health("ansa")["consecutive_failures"] == 0
    # 再次失败从 0 重新递增
    mem.record_source_health("ansa", success=False, error_msg="e3")
    assert mem.get_source_health("ansa")["consecutive_failures"] == 1


def test_record_source_health_persists_across_instances(tmp_path: Path) -> None:
    """record_source_health 写入的状态应该在新的 Memory 实例中可见。"""
    mem1 = Memory(tmp_path)
    mem1.record_source_health("ansa", success=False, error_msg="timeout",
                              run_id="test-run-1")
    mem1.record_source_health("ansa", success=True, run_id="test-run-2")
    mem2 = Memory(tmp_path)
    health = mem2.get_source_health("ansa")
    assert health["total_runs"] == 2
    assert health["total_failures"] == 1
    assert health["consecutive_failures"] == 0


def test_record_source_health_accepts_run_id(tmp_path: Path) -> None:
    """record_source_health 接受 run_id 参数（保留字段）。"""
    mem = Memory(tmp_path)
    mem.record_source_health("ansa", success=True, run_id="run-abc")
    health = mem.get_source_health("ansa")
    assert health["total_runs"] == 1


# ------------------------------------------------------------------
# is_source_degraded (HEALTH-POLICY-001)
# ------------------------------------------------------------------


def test_is_source_degraded_false_for_healthy_source(tmp_path: Path) -> None:
    """少量失败 + 高成功率 → 不降级。"""
    mem = Memory(tmp_path)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=True)
    mem.update_source_health("ansa", success=False, error_msg="transient")
    # 1 次失败，consecutive=1 < 5, success_rate=4/5=80% > 30%
    assert mem.is_source_degraded("ansa") is False


def test_is_source_degraded_true_for_consecutive_failures(tmp_path: Path) -> None:
    """连续 5 次失败 → 触发降级。"""
    mem = Memory(tmp_path)
    for i in range(5):
        mem.update_source_health("ansa", success=False, error_msg=f"fail-{i}")
    assert mem.is_source_degraded("ansa") is True


def test_is_source_degraded_true_for_low_success_rate(tmp_path: Path) -> None:
    """10+ 次运行后成功率低于 30% → 触发降级。"""
    mem = Memory(tmp_path)
    # 10 次运行，只有 2 次成功 → 成功率 20% < 30%
    for _ in range(2):
        mem.update_source_health("ansa", success=True)
    for _ in range(8):
        mem.update_source_health("ansa", success=False, error_msg="timeout")
    health = mem.get_source_health("ansa")
    assert health["total_runs"] == 10
    assert mem.is_source_degraded("ansa") is True


def test_is_source_degraded_false_for_new_source(tmp_path: Path) -> None:
    """运行次数不足 min_total_runs 时不检查成功率。"""
    mem = Memory(tmp_path)
    # 5 次失败 + 1 次成功(重置 consecutive) + 3 次失败 = 9 次运行
    # consecutive=3 < 5, success_rate=1/9≈11%, total_runs=9 < min_total_runs=10
    for _ in range(5):
        mem.update_source_health("corriere", success=False, error_msg="fail")
    mem.update_source_health("corriere", success=True)
    for _ in range(3):
        mem.update_source_health("corriere", success=False, error_msg="fail")
    assert mem.is_source_degraded("corriere") is False


def test_is_source_degraded_unknown_source_returns_false(tmp_path: Path) -> None:
    """未记录的源 get_source_health 返回 {} → 不降级。"""
    mem = Memory(tmp_path)
    assert mem.get_source_health("nonexistent") == {}
    assert mem.is_source_degraded("nonexistent") is False


def test_is_source_degraded_custom_thresholds(tmp_path: Path) -> None:
    """验证 max_consecutive_failures 和 min_success_rate 自定义参数。"""
    mem = Memory(tmp_path)
    # 3 次连续失败，默认阈值 5 不会触发，但自定义阈值 3 会触发
    for _ in range(3):
        mem.update_source_health("ansa", success=False, error_msg="fail")
    assert mem.is_source_degraded("ansa") is False  # 默认 5
    assert mem.is_source_degraded("ansa", max_consecutive_failures=3) is True

    # 成功率 56.25% — 默认 30% 不触发，自定义 60% 触发
    mem2 = Memory(tmp_path)
    # 7S + 3F = 10 runs, consecutive=3
    for _ in range(7):
        mem2.update_source_health("corriere", success=True)
    for _ in range(3):
        mem2.update_source_health("corriere", success=False, error_msg="fail")
    # 1S + 4F + 1S = 6 more, total 16 runs, 9 success, consecutive=0
    mem2.update_source_health("corriere", success=True)
    for _ in range(4):
        mem2.update_source_health("corriere", success=False, error_msg="fail")
    mem2.update_source_health("corriere", success=True)
    # 16 runs, 9 success → 56.25%
    assert mem2.is_source_degraded("corriere") is False  # 默认 30%
    assert mem2.is_source_degraded("corriere", min_success_rate=0.6) is True


# ------------------------------------------------------------------
# Cursors
# ------------------------------------------------------------------


def test_get_cursor_returns_none_for_unknown_source(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    assert mem.get_cursor("ansa") is None


def test_set_and_get_cursor(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.set_cursor("ansa", 'etag-"abc123"')
    assert mem.get_cursor("ansa") == 'etag-"abc123"'


def test_cursor_persists(tmp_path: Path) -> None:
    mem1 = Memory(tmp_path)
    mem1.set_cursor("ansa", "last-modified-xyz")
    mem2 = Memory(tmp_path)
    assert mem2.get_cursor("ansa") == "last-modified-xyz"


def test_set_cursor_overwrites(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.set_cursor("ansa", "old")
    mem.set_cursor("ansa", "new")
    assert mem.get_cursor("ansa") == "new"


# ------------------------------------------------------------------
# Provider Stats
# ------------------------------------------------------------------


def test_get_provider_stats_empty_for_unknown_provider(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    assert mem.get_provider_stats("openai") == {}


def test_update_provider_stats_success(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_provider_stats("openai", tokens_used=150, success=True)
    stats = mem.get_provider_stats("openai")
    assert stats["total_calls"] == 1
    assert stats["successful_calls"] == 1
    assert stats["failed_calls"] == 0
    assert stats["total_tokens"] == 150


def test_update_provider_stats_failure(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_provider_stats("openai", tokens_used=0, success=False)
    stats = mem.get_provider_stats("openai")
    assert stats["total_calls"] == 1
    assert stats["successful_calls"] == 0
    assert stats["failed_calls"] == 1
    assert stats["total_tokens"] == 0


def test_update_provider_stats_accumulates(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_provider_stats("openai", tokens_used=100, success=True)
    mem.update_provider_stats("openai", tokens_used=200, success=True)
    mem.update_provider_stats("openai", tokens_used=50, success=False)
    stats = mem.get_provider_stats("openai")
    assert stats["total_calls"] == 3
    assert stats["successful_calls"] == 2
    assert stats["failed_calls"] == 1
    assert stats["total_tokens"] == 350


def test_provider_stats_persists(tmp_path: Path) -> None:
    mem1 = Memory(tmp_path)
    mem1.update_provider_stats("openai", tokens_used=100, success=True)
    mem2 = Memory(tmp_path)
    stats = mem2.get_provider_stats("openai")
    assert stats["total_calls"] == 1


def test_get_provider_stats_returns_copy(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    mem.update_provider_stats("openai", tokens_used=100, success=True)
    stats = mem.get_provider_stats("openai")
    stats["total_calls"] = 999
    assert mem.get_provider_stats("openai")["total_calls"] == 1


# ------------------------------------------------------------------
# Thread safety
# ------------------------------------------------------------------


def test_concurrent_mark_known(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    errors: list[Exception] = []

    def mark_range(start: int, end: int) -> None:
        try:
            for i in range(start, end):
                mem.mark_known(f"ne-italy-ansa-20260509-{i:08d}")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=mark_range, args=(0, 50))
    t2 = threading.Thread(target=mark_range, args=(50, 100))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
    for i in range(100):
        assert mem.is_known(f"ne-italy-ansa-20260509-{i:08d}")


def test_concurrent_update_source_health(tmp_path: Path) -> None:
    mem = Memory(tmp_path)
    errors: list[Exception] = []

    def update_n(n: int) -> None:
        try:
            for _ in range(n):
                mem.update_source_health("ansa", success=True)
                mem.update_source_health("corriere", success=False, error_msg="timeout")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=update_n, args=(30,))
    t2 = threading.Thread(target=update_n, args=(30,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0
    ansa = mem.get_source_health("ansa")
    assert ansa["total_runs"] == 60
    assert ansa["total_failures"] == 0
    corriere = mem.get_source_health("corriere")
    assert corriere["total_runs"] == 60
    assert corriere["total_failures"] == 60
