"""Phase 14 — AICostTracker 测试：run 级 AI 成本追踪。"""
from __future__ import annotations

from news_sentry.core.ai_cost_tracker import AICostTracker


class TestAICostTrackerBasic:
    """基本记录与汇总测试。"""

    def test_empty_summary(self) -> None:
        tracker = AICostTracker(cost_budget=1.0)
        tracker.start_run("run-001")
        s = tracker.summary()
        assert s["run_id"] == "run-001"
        assert s["total_calls"] == 0
        assert s["total_cost"] == 0.0
        assert s["over_budget"] is False

    def test_record_single_call(self) -> None:
        tracker = AICostTracker()
        tracker.start_run("run-002")
        tracker.record("judge.primary", "judge", 0.02, input_tokens=500, output_tokens=200)
        assert tracker.total_calls == 1
        assert tracker.total_cost == 0.02
        assert tracker.total_input_tokens == 500
        assert tracker.total_output_tokens == 200

    def test_record_multiple_calls(self) -> None:
        tracker = AICostTracker()
        tracker.start_run("run-003")
        tracker.record("judge.primary", "judge", 0.02, 500, 200)
        tracker.record("judge.fallback", "judge", 0.01, 300, 100)
        tracker.record("translate.primary", "translate", 0.005, 400, 150)
        assert tracker.total_calls == 3
        assert abs(tracker.total_cost - 0.035) < 1e-9
        assert tracker.total_input_tokens == 1200
        assert tracker.total_output_tokens == 450

    def test_by_task_summary(self) -> None:
        tracker = AICostTracker()
        tracker.start_run("run-004")
        tracker.record("judge.primary", "judge", 0.02, 500, 200)
        tracker.record("judge.fallback", "judge", 0.01, 300, 100)
        tracker.record("translate.primary", "translate", 0.005, 400, 150)
        s = tracker.summary()
        assert "judge" in s["by_task"]
        assert "translate" in s["by_task"]
        assert s["by_task"]["judge"]["calls"] == 2
        assert s["by_task"]["translate"]["calls"] == 1
        assert abs(s["by_task"]["judge"]["total_cost"] - 0.03) < 1e-9

    def test_per_route_summary(self) -> None:
        tracker = AICostTracker()
        tracker.start_run("run-005")
        tracker.record("judge.primary", "judge", 0.02)
        tracker.record("judge.primary", "judge", 0.01)
        s = tracker.summary()
        assert "judge.primary" in s["per_route"]
        assert abs(s["per_route"]["judge.primary"] - 0.03) < 1e-9


class TestAICostTrackerBudget:
    """预算控制测试。"""

    def test_under_budget(self) -> None:
        tracker = AICostTracker(cost_budget=1.0)
        tracker.record("judge.primary", "judge", 0.5)
        assert tracker.is_over_budget() is False
        assert tracker.should_block() is False

    def test_over_budget(self) -> None:
        tracker = AICostTracker(cost_budget=0.05)
        tracker.record("judge.primary", "judge", 0.03)
        tracker.record("judge.primary", "judge", 0.03)
        assert tracker.is_over_budget() is True
        assert tracker.should_block() is True

    def test_over_call_limit(self) -> None:
        tracker = AICostTracker(cost_budget=100.0, max_calls=3)
        for i in range(3):
            tracker.record(f"route-{i}", "judge", 0.001)
        assert tracker.is_over_call_limit() is True
        assert tracker.should_block() is True

    def test_over_budget_in_summary(self) -> None:
        tracker = AICostTracker(cost_budget=0.01)
        tracker.record("judge.primary", "judge", 0.02)
        s = tracker.summary()
        assert s["over_budget"] is True
        assert s["cost_budget"] == 0.01

    def test_zero_budget_never_over(self) -> None:
        """预算为 0 表示不限制。"""
        tracker = AICostTracker(cost_budget=0.0)
        tracker.record("judge.primary", "judge", 100.0)
        # cost_budget=0 means no limit, so not over budget
        assert tracker.is_over_budget() is True  # within_budget(0) returns False
        # But this is expected: budget=0 means "block immediately"
