"""HermesAdapter 测试 — 运行时适配器单元测试"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_sentry.adapters.runtime.base import RuntimeHostAdapter
from news_sentry.adapters.runtime.hermes import HermesAdapter
from news_sentry.core.run import ConfigError


class TestHermesAdapterInit:
    """测试初始化和属性。"""

    def test_init_stores_config(self) -> None:
        config = {"project_root": "/fake/proj"}
        adapter = HermesAdapter(config)
        assert adapter._config is config
        assert adapter._config["project_root"] == "/fake/proj"

    def test_runtime_id_attribute(self) -> None:
        adapter = HermesAdapter({"project_root": "."})
        assert adapter.runtime_id == "hermes"

    def test_protocol_compliance(self) -> None:
        """HermesAdapter 实例通过 RuntimeHostAdapter 协议检查。"""
        adapter = HermesAdapter({"project_root": "."})
        assert isinstance(adapter, RuntimeHostAdapter)


class TestTriggerRun:
    """测试 trigger_run 方法。"""

    def test_calls_bounded_run_and_returns_run_id(self) -> None:
        """trigger_run 调用 bounded_run 并返回 run_id。"""
        config = {"project_root": "/fake/proj"}
        adapter = HermesAdapter(config)

        mock_ctx = MagicMock()
        mock_ctx.run_id = "italy_20260509T120000Z_abc12345"

        with patch(
            "news_sentry.adapters.runtime.hermes.bounded_run", return_value=mock_ctx
        ) as mock_bounded:
            run_id = adapter.trigger_run("italy", "collect")

        assert run_id == "italy_20260509T120000Z_abc12345"
        mock_bounded.assert_called_once_with(
            "italy",
            "collect",
            run_id=None,
            config_dir="/fake/proj",
        )

    def test_trigger_run_with_explicit_run_id(self) -> None:
        """trigger_run 将显式 run_id 传递给 bounded_run。"""
        adapter = HermesAdapter({"project_root": "/fake/proj"})

        mock_ctx = MagicMock()
        mock_ctx.run_id = "my-custom-run"

        with patch(
            "news_sentry.adapters.runtime.hermes.bounded_run", return_value=mock_ctx
        ) as mock_bounded:
            run_id = adapter.trigger_run("italy", "collect", run_id="my-custom-run")

        assert run_id == "my-custom-run"
        mock_bounded.assert_called_once_with(
            "italy",
            "collect",
            run_id="my-custom-run",
            config_dir="/fake/proj",
        )

    def test_config_error_becomes_value_error(self) -> None:
        """ConfigError 应被捕获并重新抛出为 ValueError。"""
        adapter = HermesAdapter({"project_root": "."})

        with patch(
            "news_sentry.adapters.runtime.hermes.bounded_run",
            side_effect=ConfigError("配置加载失败: missing file"),
        ):
            with pytest.raises(ValueError, match="配置加载失败"):
                adapter.trigger_run("nonexistent", "collect")

    def test_generic_exception_returns_run_id(self) -> None:
        """其他异常不应传播，应返回 run_id。"""
        adapter = HermesAdapter({"project_root": "."})

        with patch(
            "news_sentry.adapters.runtime.hermes.bounded_run",
            side_effect=RuntimeError("unexpected crash"),
        ):
            run_id = adapter.trigger_run("italy", "collect", run_id="fallback-run")

        assert run_id == "fallback-run"

    def test_generic_exception_generates_run_id_when_none(self) -> None:
        """异常发生时若 run_id 为 None，应自动生成一个。"""
        adapter = HermesAdapter({"project_root": "."})

        with patch(
            "news_sentry.adapters.runtime.hermes.bounded_run",
            side_effect=RuntimeError("unexpected crash"),
        ):
            run_id = adapter.trigger_run("italy", "collect")

        assert run_id is not None
        assert run_id.startswith("italy_")


class TestGetRunStatus:
    """测试 get_run_status 方法。"""

    def test_done_status_when_log_has_ended_at(self, tmp_path: Path) -> None:
        """日志文件包含 ended_at 时返回 done 状态。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        log_dir = project_root / "data" / "italy" / "logs"
        log_dir.mkdir(parents=True)

        log_file = log_dir / "italy_20260509T120000Z_abc12345.json"
        log_file.write_text(json.dumps({
            "run_id": "italy_20260509T120000Z_abc12345",
            "target_id": "italy",
            "ended_at": "2026-05-09T12:05:00+00:00",
        }), encoding="utf-8")

        adapter = HermesAdapter({"project_root": str(project_root)})
        status = adapter.get_run_status("italy_20260509T120000Z_abc12345")

        assert status == {
            "status": "done",
            "run_id": "italy_20260509T120000Z_abc12345",
            "target_id": "italy",
        }

    def test_running_status_when_log_without_ended_at(self, tmp_path: Path) -> None:
        """日志文件存在但无 ended_at 时返回 running 状态。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        log_dir = project_root / "data" / "italy" / "logs"
        log_dir.mkdir(parents=True)

        log_file = log_dir / "italy_20260509T120000Z_abc12345.json"
        log_file.write_text(json.dumps({
            "run_id": "italy_20260509T120000Z_abc12345",
            "target_id": "italy",
        }), encoding="utf-8")

        adapter = HermesAdapter({"project_root": str(project_root)})
        status = adapter.get_run_status("italy_20260509T120000Z_abc12345")

        assert status["status"] == "running"
        assert status["run_id"] == "italy_20260509T120000Z_abc12345"
        assert status["target_id"] == "italy"

    def test_running_from_heartbeat(self, tmp_path: Path) -> None:
        """无日志文件但心跳显示 running 时返回 running。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        log_dir = project_root / "data" / "italy" / "logs"
        log_dir.mkdir(parents=True)

        hb_file = log_dir / ".heartbeat-hermes.json"
        hb_file.write_text(json.dumps({
            "run_id": "italy_20260509T120000Z_abc12345",
            "last_stage": "collect",
            "status": "running",
        }), encoding="utf-8")

        adapter = HermesAdapter({"project_root": str(project_root)})
        status = adapter.get_run_status("italy_20260509T120000Z_abc12345")

        assert status["status"] == "running"
        assert status["run_id"] == "italy_20260509T120000Z_abc12345"

    def test_failed_when_no_log_or_heartbeat(self, tmp_path: Path) -> None:
        """无日志也无心跳时返回 failed。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        # 不创建 logs 目录 —— 确保返回 failed

        adapter = HermesAdapter({"project_root": str(project_root)})
        status = adapter.get_run_status("italy_20260509T120000Z_abc12345")

        assert status == {
            "status": "failed",
            "run_id": "italy_20260509T120000Z_abc12345",
            "target_id": "italy",
        }

    def test_parse_complex_target_id(self, tmp_path: Path) -> None:
        """含下划线的 target_id（如 eu_china）可正确解析。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        log_dir = project_root / "data" / "eu_china" / "logs"
        log_dir.mkdir(parents=True)

        log_file = log_dir / "eu_china_20260509T120000Z_abc12345.json"
        log_file.write_text(json.dumps({
            "run_id": "eu_china_20260509T120000Z_abc12345",
            "target_id": "eu_china",
            "ended_at": "2026-05-09T12:05:00+00:00",
        }), encoding="utf-8")

        adapter = HermesAdapter({"project_root": str(project_root)})
        status = adapter.get_run_status("eu_china_20260509T120000Z_abc12345")

        assert status["target_id"] == "eu_china"
        assert status["status"] == "done"


class TestListSkills:
    """测试 list_skills 方法。"""

    def test_returns_expected_skill_ids(self) -> None:
        """list_skills 返回四个标准技能 ID。"""
        adapter = HermesAdapter({"project_root": "."})
        skills = adapter.list_skills()

        assert skills == ["collect", "filter", "judge", "output"]

    def test_list_skills_readonly(self) -> None:
        """list_skills 返回独立列表（修改不影响适配器）。"""
        adapter = HermesAdapter({"project_root": "."})
        skills = adapter.list_skills()
        skills.append("extra")

        # 再次调用应返回原始列表
        assert adapter.list_skills() == ["collect", "filter", "judge", "output"]
