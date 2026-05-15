"""多 Target 并发调度测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestResolveTargets:
    """_resolve_targets() 将 target_str 解析为 target_id 列表。"""

    def test_single_target(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy", config_dir=tmp_path)
        assert result == ["italy"]

    def test_comma_separated_targets(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy,japan,germany", config_dir=tmp_path)
        assert result == ["italy", "japan", "germany"]

    def test_comma_separated_strips_whitespace(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets(" italy , japan , germany ", config_dir=tmp_path)
        assert result == ["italy", "japan", "germany"]

    def test_all_keyword_discovers_targets(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)
        for tid in ["italy", "japan", "germany", "france", "china-watch-en"]:
            (targets_dir / f"{tid}.yaml").write_text(f"target_id: {tid}")
        (targets_dir / "_template.yaml").write_text("target_id: _template")

        result = _resolve_targets("all", config_dir=tmp_path)
        assert sorted(result) == ["china-watch-en", "france", "germany", "italy", "japan"]

    def test_all_keyword_empty_dir(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == []

    def test_all_keyword_skips_underscore_prefixed(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        targets_dir = tmp_path / "config" / "targets"
        targets_dir.mkdir(parents=True)
        (targets_dir / "italy.yaml").write_text("target_id: italy")
        (targets_dir / "_internal.yaml").write_text("target_id: _internal")

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == ["italy"]

    def test_duplicate_targets_deduplicated(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("italy,italy,japan", config_dir=tmp_path)
        assert result == ["italy", "japan"]

    def test_all_keyword_nonexistent_dir(self, tmp_path: Path) -> None:
        from news_sentry.core.async_run import _resolve_targets

        result = _resolve_targets("all", config_dir=tmp_path)
        assert result == []


class TestBoundedRunMultiAsync:
    """bounded_run_multi_async() 多目标并发入口测试。"""

    @pytest.mark.asyncio
    async def test_runs_all_targets_concurrently(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        call_log: list[str] = []

        async def fake_run_single(target_id: str, **kwargs: object) -> MagicMock:
            call_log.append(target_id)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy", "japan", "germany"],
                stage="all",
            )

        assert sorted(call_log) == ["germany", "italy", "japan"]
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_targets_run_in_parallel_not_serial(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        timestamps: dict[str, float] = {}

        async def slow_run(target_id: str, **kwargs: object) -> MagicMock:
            timestamps[target_id] = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=slow_run,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan"],
                stage="collect",
            )

        assert abs(timestamps["italy"] - timestamps["japan"]) < 0.05

    @pytest.mark.asyncio
    async def test_single_target_runs_normally(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        async def fake_run_single(target_id: str, **kwargs: object) -> MagicMock:
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy"],
                stage="collect",
            )

        assert len(results) == 1
        assert results[0].target_id == "italy"

    @pytest.mark.asyncio
    async def test_empty_targets_returns_empty(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        results = await bounded_run_multi_async(targets=[], stage="all")
        assert results == []

    @pytest.mark.asyncio
    async def test_failed_target_does_not_block_others(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        async def fake_run_single(target_id: str, **kwargs: object) -> MagicMock:
            if target_id == "failing":
                raise RuntimeError("模拟失败")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            results = await bounded_run_multi_async(
                targets=["italy", "failing", "japan"],
                stage="all",
            )

        successful_ids = [r.target_id for r in results]
        assert "italy" in successful_ids
        assert "japan" in successful_ids
        assert "failing" not in successful_ids

    @pytest.mark.asyncio
    async def test_shared_http_client_passed_to_all_targets(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        received_clients: list[object] = []

        async def fake_run_single(target_id: str, **kwargs: object) -> MagicMock:
            received_clients.append(kwargs.get("http_client"))
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan"],
                stage="collect",
            )

        assert len(received_clients) == 2
        assert received_clients[0] is received_clients[1]

    @pytest.mark.asyncio
    async def test_scheduler_registered_for_all_targets(self) -> None:
        from news_sentry.core.async_run import bounded_run_multi_async

        captured_scheduler = None

        async def fake_run_single(target_id: str, **kwargs: object) -> MagicMock:
            nonlocal captured_scheduler
            if captured_scheduler is None:
                captured_scheduler = kwargs.get("scheduler")
            ctx = MagicMock()
            ctx.target_id = target_id
            ctx.errors_count = 0
            return ctx

        with patch(
            "news_sentry.core.async_run._run_single_target_async",
            side_effect=fake_run_single,
        ):
            await bounded_run_multi_async(
                targets=["italy", "japan", "germany"],
                stage="all",
            )

        assert captured_scheduler is not None
        assert sorted(captured_scheduler.registered_targets) == ["germany", "italy", "japan"]


def _make_ctx(target_id: str) -> MagicMock:
    ctx = MagicMock()
    ctx.target_id = target_id
    ctx.errors_count = 0
    ctx.events_collected = 0
    ctx.events_filtered = 0
    ctx.events_judged = 0
    ctx.events_output = 0
    return ctx


class TestIntervalLoop:
    """run_loop_async() 循环运行模式测试。"""

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations(self) -> None:
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs: object) -> list[MagicMock]:
            nonlocal call_count
            call_count += 1
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=3,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_continues_after_single_iteration_error(self) -> None:
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs: object) -> list[MagicMock]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("模拟第 1 轮失败")
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=3,
            )

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_loop_with_multiple_targets(self) -> None:
        from news_sentry.core.async_run import run_loop_async

        targets_received: list[list[str]] = []

        async def fake_multi(**kwargs: object) -> list[MagicMock]:
            targets_received.append(list(kwargs.get("targets", [])))
            return [_make_ctx(t) for t in kwargs.get("targets", [])]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy", "japan"],
                stage="all",
                interval=0,
                max_iterations=2,
            )

        assert len(targets_received) == 2
        assert targets_received[0] == ["italy", "japan"]
        assert targets_received[1] == ["italy", "japan"]

    @pytest.mark.asyncio
    async def test_loop_sleeps_between_iterations(self) -> None:
        from news_sentry.core.async_run import run_loop_async

        sleep_durations: list[float] = []

        async def fake_multi(**kwargs: object) -> list[MagicMock]:
            return [_make_ctx("italy")]

        async def fake_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)

        with (
            patch(
                "news_sentry.core.async_run.bounded_run_multi_async",
                side_effect=fake_multi,
            ),
            patch(
                "news_sentry.core.async_run.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=60,
                max_iterations=2,
            )

        assert sleep_durations == [60]

    @pytest.mark.asyncio
    async def test_loop_zero_iterations_returns_immediately(self) -> None:
        from news_sentry.core.async_run import run_loop_async

        call_count = 0

        async def fake_multi(**kwargs: object) -> list[MagicMock]:
            nonlocal call_count
            call_count += 1
            return [_make_ctx("italy")]

        with patch(
            "news_sentry.core.async_run.bounded_run_multi_async",
            side_effect=fake_multi,
        ):
            await run_loop_async(
                targets=["italy"],
                stage="all",
                interval=0,
                max_iterations=0,
            )

        assert call_count == 0


class TestResourceIsolation:
    """验证多 target 间的资源隔离。"""

    def test_each_target_gets_own_state_db_path(self) -> None:
        from news_sentry.core.async_run import _target_db_path

        italy_db = _target_db_path("italy", Path("/data"))
        japan_db = _target_db_path("japan", Path("/data"))

        assert str(italy_db).endswith("italy/state.db")
        assert str(japan_db).endswith("japan/state.db")
        assert italy_db != japan_db

    def test_each_target_gets_own_memory_dir(self) -> None:
        from news_sentry.core.async_run import _target_memory_dir

        italy_mem = _target_memory_dir("italy", Path("/data"))
        japan_mem = _target_memory_dir("japan", Path("/data"))

        assert str(italy_mem).endswith("italy/memory")
        assert str(japan_mem).endswith("japan/memory")
        assert italy_mem != japan_mem

    def test_db_path_under_output_root(self) -> None:
        from news_sentry.core.async_run import _target_db_path

        db_path = _target_db_path("italy", Path("./data"))
        assert "italy" in str(db_path)
        assert db_path.name == "state.db"

    def test_memory_dir_under_output_root(self) -> None:
        from news_sentry.core.async_run import _target_memory_dir

        mem_dir = _target_memory_dir("france", Path("./data"))
        assert "france" in str(mem_dir)
        assert mem_dir.name == "memory"

    @pytest.mark.asyncio
    async def test_scheduler_per_target_independent_slots(self) -> None:
        from news_sentry.core.scheduler import FairScheduler

        scheduler = FairScheduler(per_target_min=2, global_max=30)
        scheduler.register("italy")
        scheduler.register("japan")

        await scheduler.acquire("italy")
        await scheduler.acquire("italy")

        await scheduler.acquire("japan")
        scheduler.release("japan")

        scheduler.release("italy")
        scheduler.release("italy")
