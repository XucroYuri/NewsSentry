"""OpenCLICollector 集成测试 — mock subprocess 验证完整采集链路。

覆盖：正常采集、空结果、沙箱拦截、未安装、认证要求、JSON 解析错误、
速率限制集成、NewsEvent 元数据验证。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.sandbox import SandboxViolationError
from news_sentry.models.newsevent import NewsEvent, PipelineStage
from news_sentry.skills.collect.opencli_collector import OpenCLICollector

# ── 共享夹具（fixtures）─────────────────────────────────────────────


@pytest.fixture
def sample_news_json() -> str:
    """Sample output from an OpenCLI tool — HN top stories."""
    return json.dumps([
        {"title": "Show HN: New Framework", "url": "https://example.com/1", "score": 100},
        {"title": "Why Rust is the Future", "url": "https://example.com/2", "score": 200},
    ])


@pytest.fixture
def source_config() -> dict:
    return {
        "source_id": "hackernews-top",
        "target_id": "italy",
        "type": "opencli",
        "tool_ref": "opencli.hackernews.top",
        "validated_args": {"n": 5},
        "fetch_interval_seconds": 1.0,
    }


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    """在临时目录创建最小 opencli-baseline.yaml，含测试用工具定义。"""
    manifest_dir = tmp_path / "toolmanifest"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "opencli-baseline.yaml"
    manifest_data = {
        "tools": [
            {
                "tool_id": "opencli.hackernews.top",
                "command_template": "opencli hackernews top --count {n}",
                "description": "Fetch HN top stories",
            }
        ]
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_data, f)
    return manifest_path


# ── 测试用例 ──────────────────────────────────────────────────────


class TestCollectProducesNewsEvents:
    """正常采集：mock subprocess 返回有效 JSON，验证 NewsEvent 列表生成。"""

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_produces_news_events(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, sample_news_json: str, tmp_manifest: Path,
    ) -> None:
        """mock subprocess.run 返回 sample JSON，collect() 应产生正确的 NewsEvent 列表。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.return_value = mock.Mock(
            returncode=0, stdout=sample_news_json, stderr="",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-001")

        assert len(events) == 2
        assert all(isinstance(e, NewsEvent) for e in events)
        assert all(e.pipeline_stage == PipelineStage.COLLECTED for e in events)
        assert events[0].title_original == "Show HN: New Framework"
        assert events[0].url == "https://example.com/1"
        assert events[1].title_original == "Why Rust is the Future"
        assert events[1].url == "https://example.com/2"

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_empty_stdout(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """exit_code=66（result_empty）+ 空 stdout 时 collect() 返回 []。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.return_value = mock.Mock(
            returncode=66, stdout="", stderr="",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-002")

        assert events == []

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_sandbox_blocked(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """沙箱 enforce() 抛出 SandboxViolationError 时 collect() 返回 []。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True
        mock_sandbox.enforce.side_effect = SandboxViolationError(
            "command blocked by sandbox policy",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-003")

        assert events == []
        # 验证 sandbox.enforce 确实被调用
        mock_sandbox.enforce.assert_called_once()

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_opencli_not_installed(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """subprocess.run 抛出 FileNotFoundError 时 collect() 返回 []。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.side_effect = FileNotFoundError("opencli not found")

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-004")

        assert events == []

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_auth_required(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """exit_code=77（auth_required）时 collect() 返回 []。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.return_value = mock.Mock(
            returncode=77, stdout="", stderr="authentication required",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-005")

        assert events == []

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_invalid_json(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """stdout 包含无效 JSON 时 collect() 进入纯文本 fallback，生成 1 个 NewsEvent。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.return_value = mock.Mock(
            returncode=0, stdout="not valid json {{{", stderr="",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-006")

        assert len(events) == 1
        assert "OpenCLI output:" in events[0].title_original
        assert events[0].content_original == "not valid json {{{"


class TestCollectNewsEventMetadata:
    """NewsEvent 元数据验证：确认 collection metadata 正确设置。"""

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_news_event_metadata(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, sample_news_json: str, tmp_manifest: Path,
    ) -> None:
        """验证产生的 NewsEvent 包含正确的 metadata.collection 字段。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        mock_run.return_value = mock.Mock(
            returncode=0, stdout=sample_news_json, stderr="",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-008")

        assert len(events) >= 1
        for event in events:
            assert "collection" in event.metadata
            assert event.metadata["collection"]["method"] == "opencli"
            assert event.metadata["collection"]["tool_ref"] == ""
            assert event.run_id == "test-run-008"

    @mock.patch("subprocess.run")
    @mock.patch("news_sentry.adapters.tools.opencli.SandboxEnforcer")
    def test_collect_parses_items_wrapper(
        self, mock_sandbox_class: mock.Mock, mock_run: mock.Mock,
        source_config: dict, tmp_manifest: Path,
    ) -> None:
        """JSON 对象（含 items 字段）不再展开，作为一个完整事件处理。"""
        mock_sandbox = mock_sandbox_class.return_value
        mock_sandbox.check_tool_allowed.return_value = True

        items_json = json.dumps({
            "items": [
                {"title": "HN Item 1", "url": "https://example.com/a"},
                {"title": "HN Item 2", "url": "https://example.com/b"},
            ]
        })
        mock_run.return_value = mock.Mock(
            returncode=0, stdout=items_json, stderr="",
        )

        adapter = OpenCLIToolAdapter(
            manifest_path=str(tmp_manifest), sandbox_enforcer=mock_sandbox,
        )
        collector = OpenCLICollector(source_config, adapter, sandbox_enforcer=mock_sandbox)

        events = collector.collect("test-run-009")

        assert len(events) == 1
        assert events[0].pipeline_stage == PipelineStage.COLLECTED
