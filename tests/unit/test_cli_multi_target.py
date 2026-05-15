"""CLI 多目标 + --interval 参数测试。"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from news_sentry.cli import main
from news_sentry.models.pipeline_context import PipelineContext


def _ctx(target_id: str = "italy") -> PipelineContext:
    """构造最小 PipelineContext 用于 mock 返回。"""
    return PipelineContext(
        run_id=f"run-{target_id}",
        target_id=target_id,
        stage="collected",
        started_at="2026-05-15T00:00:00+00:00",
        profile_id="local-workstation",
    )


class TestCLIMultiTarget:
    """--target all 和 --target a,b 的 CLI 行为。"""

    def test_target_all_calls_multi_async(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--target all 调用 bounded_run_multi_async 路径。"""
        captured: dict = {}

        async def fake_multi(**kwargs: object) -> list[PipelineContext]:
            captured.update(kwargs)
            return [_ctx("italy"), _ctx("japan")]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr(
            "news_sentry.core.async_run._resolve_targets",
            lambda target_str, config_dir=None: ["italy", "japan"],
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "collect"],
        )

        assert result.exit_code == 0
        assert captured.get("stage") == "collect"

    def test_target_comma_separated_calls_multi_async(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--target italy,japan 调用 bounded_run_multi_async 路径。"""
        captured: dict = {}

        async def fake_multi(**kwargs: object) -> list[PipelineContext]:
            captured.update(kwargs)
            return [_ctx("italy"), _ctx("japan")]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr(
            "news_sentry.core.async_run._resolve_targets",
            lambda target_str, config_dir=None: ["italy", "japan"],
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "italy,japan", "--stage", "all"],
        )

        assert result.exit_code == 0
        assert captured.get("stage") == "all"

    def test_single_target_uses_async_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单个 target 使用 bounded_run_async 异步入口。"""
        captured: dict = {}

        async def fake_bounded_run(**kwargs: object) -> PipelineContext:
            captured.update(kwargs)
            return _ctx()

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_async",
            fake_bounded_run,
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "italy", "--stage", "collect"],
        )

        assert result.exit_code == 0
        assert captured.get("target_id") == "italy"


class TestCLIInterval:
    """--interval N 循环运行参数。"""

    def test_interval_option_in_help(self) -> None:
        """--interval 选项应出现在 run --help 输出中。"""
        result = CliRunner().invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--interval" in result.output

    def test_interval_must_be_integer(self) -> None:
        """--interval 值必须是整数。"""
        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "abc"],
        )
        assert result.exit_code != 0

    def test_interval_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--interval 0 应被拒绝。"""

        async def fake_multi(**kwargs: object) -> list[PipelineContext]:
            return [_ctx()]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr(
            "news_sentry.core.async_run._resolve_targets",
            lambda target_str, config_dir=None: ["italy"],
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "0"],
        )
        assert result.exit_code != 0

    def test_interval_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """负数 --interval 应被拒绝。"""

        async def fake_multi(**kwargs: object) -> list[PipelineContext]:
            return [_ctx()]

        monkeypatch.setattr(
            "news_sentry.core.async_run.bounded_run_multi_async",
            fake_multi,
        )
        monkeypatch.setattr(
            "news_sentry.core.async_run._resolve_targets",
            lambda target_str, config_dir=None: ["italy"],
        )

        result = CliRunner().invoke(
            main,
            ["run", "--target", "all", "--stage", "all", "--interval", "-1"],
        )
        assert result.exit_code != 0
