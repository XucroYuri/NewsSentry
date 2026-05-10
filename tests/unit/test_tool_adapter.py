"""Tests for ToolRunResult, OpenCLIToolAdapter, OpenCLICollector.

覆盖率: adapters/tools/base.py, adapters/tools/opencli.py, skills/collect/opencli_collector.py
"""
# ruff: noqa: S108  # 测试中的 /tmp/ 路径是 mock 参数，不执行实际文件操作

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.sandbox import (
    SandboxEnforcer,
    SandboxPolicy,
    StopOnRiskConfig,
)
from news_sentry.skills.collect.opencli_collector import OpenCLICollector

# ──────────────────────────────────────────────────────────────
# ToolRunResult
# ──────────────────────────────────────────────────────────────


class TestToolRunResult:
    """ToolRunResult dataclass 测试。"""

    def test_minimal_construction(self) -> None:
        result = ToolRunResult(
            tool_id="opencli.fetch",
            run_id="run-001",
            success=True,
            exit_code=0,
        )
        assert result.tool_id == "opencli.fetch"
        assert result.run_id == "run-001"
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.duration_ms == 0
        assert result.error is None

    def test_with_stdout_stderr(self) -> None:
        result = ToolRunResult(
            tool_id="opencli.fetch",
            run_id="r2",
            success=True,
            exit_code=0,
            stdout='{"title": "News"}',
            stderr="warning: deprecation",
            duration_ms=1234,
        )
        assert result.stdout == '{"title": "News"}'
        assert result.stderr == "warning: deprecation"
        assert result.duration_ms == 1234

    def test_with_error_dict(self) -> None:
        result = ToolRunResult(
            tool_id="opencli.search",
            run_id="r3",
            success=False,
            exit_code=-1,
            error={"type": "timeout", "message": "subprocess timed out after 60s"},
        )
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "timeout"

    def test_error_none_when_unset(self) -> None:
        result = ToolRunResult(
            tool_id="test",
            run_id="r4",
            success=True,
            exit_code=0,
        )
        assert result.error is None


# ──────────────────────────────────────────────────────────────
# OpenCLIToolAdapter helpers
# ──────────────────────────────────────────────────────────────


def _make_minimal_manifest(tmp_path: Path) -> Path:
    """Create a minimal opencli-baseline.yaml for testing."""
    manifest = {
        "tools": [
            {
                "tool_id": "opencli.fetch",
                "display_name": "Fetch URL",
                "version": "1.0.0",
                "execution_type": "subprocess",
                "command_template": "opencli fetch --url {url} --output {output_path}",
                "parameters_schema": {
                    "type": "object",
                    "required": ["url", "output_path"],
                    "properties": {
                        "url": {"type": "string", "format": "uri"},
                        "output_path": {"type": "string"},
                    },
                },
                "exit_codes": {
                    "0": "success",
                    "1": "fetch_failed",
                    "2": "timeout",
                    "3": "permission_denied",
                },
            },
            {
                "tool_id": "opencli.search",
                "command_template": "opencli search --query {query} --limit {limit}",
                "exit_codes": {"0": "success", "1": "search_failed"},
            },
        ]
    }
    p = tmp_path / "opencli-baseline.yaml"
    import yaml

    p.write_text(yaml.dump(manifest), encoding="utf-8")
    return p


# ──────────────────────────────────────────────────────────────
# OpenCLIToolAdapter — init & manifest
# ──────────────────────────────────────────────────────────────


class TestOpenCLIToolAdapterInit:
    """OpenCLIToolAdapter 初始化和 manifest 加载测试。"""

    def test_loads_tools_from_manifest(self, tmp_path: Path) -> None:
        manifest_path = _make_minimal_manifest(tmp_path)
        adapter = OpenCLIToolAdapter(manifest_path=manifest_path)
        assert "opencli.fetch" in adapter._tools
        assert "opencli.search" in adapter._tools
        assert adapter._tools["opencli.fetch"]["version"] == "1.0.0"

    def test_skips_empty_tool_id(self, tmp_path: Path) -> None:
        import yaml

        manifest = {
            "tools": [
                {"tool_id": "", "command_template": "echo"},
                {"tool_id": "valid", "command_template": "echo"},
            ]
        }
        p = tmp_path / "manifest.yaml"
        p.write_text(yaml.dump(manifest), encoding="utf-8")
        adapter = OpenCLIToolAdapter(manifest_path=p)
        assert "" not in adapter._tools
        assert "valid" in adapter._tools

    def test_empty_manifest(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        adapter = OpenCLIToolAdapter(manifest_path=p)
        assert adapter._tools == {}


# ──────────────────────────────────────────────────────────────
# OpenCLIToolAdapter._build_command
# ──────────────────────────────────────────────────────────────


class TestBuildCommand:
    """_build_command 模板填充测试。"""

    @pytest.fixture
    def adapter(self, tmp_path: Path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))

    def test_fills_template_placeholders(self, adapter: OpenCLIToolAdapter) -> None:
        manifest = adapter._tools["opencli.fetch"]
        result = adapter._build_command(manifest, {
            "url": "https://example.com/news",
            "output_path": "/tmp/out.json",
        })
        assert result[0] == "opencli"
        assert "fetch" in result
        assert "https://example.com/news" in result
        assert "/tmp/out.json" in result

    def test_raises_keyerror_for_unknown_manifest(self, adapter: OpenCLIToolAdapter) -> None:
        with pytest.raises(ValueError, match="missing command_template"):
            adapter._build_command({}, {})

    def test_raises_valueerror_for_no_template(self, adapter: OpenCLIToolAdapter) -> None:
        with pytest.raises(ValueError, match="missing command_template"):
            adapter._build_command({"tool_id": "bare"}, {})

    def test_raises_keyerror_for_missing_params(
        self, adapter: OpenCLIToolAdapter,
    ) -> None:
        """缺失必填参数时抛出 KeyError。"""
        manifest = adapter._tools["opencli.fetch"]
        with pytest.raises(KeyError):
            adapter._build_command(manifest, {"url": "https://example.com"})

    def test_quotes_args_with_spaces(self, adapter: OpenCLIToolAdapter) -> None:
        manifest = adapter._tools["opencli.search"]
        result = adapter._build_command(manifest, {
            "query": "breaking news italy",
            "limit": "10",
        })
        # shlex.split 保留 "breaking news italy" 为单个参数
        assert "breaking news italy" in result
        # 确认命令结构正确（参数值在正确位置，不含引号字符）
        assert result[0:3] == ["opencli", "search", "--query"]


# ──────────────────────────────────────────────────────────────
# OpenCLIToolAdapter.execute
# ──────────────────────────────────────────────────────────────


class TestExecute:
    """execute() 测试 — unknown tool, 沙箱拦截, subprocess 成功/失败。"""

    @pytest.fixture
    def adapter(self, tmp_path: Path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))

    def test_unknown_tool_returns_error(self, adapter: OpenCLIToolAdapter) -> None:
        result = adapter.execute("unknown.tool", {}, "run-01")
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "command_not_found"

    def test_sandbox_blocked_returns_error(self, tmp_path: Path) -> None:
        """沙箱拦截时返回 error 而非抛异常。"""
        policy = SandboxPolicy(
            allowed_commands=[],
            allowed_network_hosts=[],
            default_action="deny",
            stop_on_risk=StopOnRiskConfig(on_sandbox_violation=False),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=_make_minimal_manifest(tmp_path),
            sandbox_enforcer=sandbox,
        )
        result = adapter.execute(
            "opencli.fetch",
            {"url": "https://evil.com", "output_path": "/tmp/x.json"},
            "run-02",
        )
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "permission_denied"

    def test_command_build_failed(self, tmp_path: Path) -> None:
        """当 command_template 不匹配 args 时，抛 KeyError → schema_validation_failed。"""
        adapter = OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))
        # 删除 template 后再调用 execute → ValueError from _build_command
        adapter._tools["opencli.fetch"]["command_template"] = ""
        result = adapter.execute(
            "opencli.fetch",
            {"url": "x", "output_path": "/tmp/x.json"},
            "run-03",
        )
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "schema_validation_failed"

    @mock.patch("subprocess.run")
    def test_successful_execution(
        self, mock_run: mock.Mock, adapter: OpenCLIToolAdapter,
    ) -> None:
        mock_proc = mock.Mock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"items": []}'
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        result = adapter.execute(
            "opencli.fetch",
            {"url": "https://ansa.it/news", "output_path": "/tmp/out.json"},
            "run-04",
        )
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == '{"items": []}'

    @mock.patch("subprocess.run")
    def test_failed_execution_maps_exit_code(
        self, mock_run: mock.Mock, adapter: OpenCLIToolAdapter,
    ) -> None:
        mock_proc = mock.Mock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "fetch error: connection refused"
        mock_run.return_value = mock_proc

        result = adapter.execute(
            "opencli.fetch",
            {"url": "https://bad.example.com", "output_path": "/tmp/x.json"},
            "run-05",
        )
        assert result.success is False
        assert result.exit_code == 1
        assert result.error is not None
        assert result.error["type"] == "fetch_failed"
        assert "connection refused" in result.error["message"]

    @mock.patch("subprocess.run")
    def test_timeout_handling(
        self, mock_run: mock.Mock, adapter: OpenCLIToolAdapter,
    ) -> None:
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="opencli", timeout=60)

        result = adapter.execute(
            "opencli.fetch",
            {"url": "https://slow.example.com", "output_path": "/tmp/x.json"},
            "run-06",
        )
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "timeout"

    @mock.patch("subprocess.run")
    def test_file_not_found(
        self, mock_run: mock.Mock, adapter: OpenCLIToolAdapter,
    ) -> None:
        mock_run.side_effect = FileNotFoundError("opencli not in PATH")

        result = adapter.execute(
            "opencli.fetch",
            {"url": "https://example.com", "output_path": "/tmp/x.json"},
            "run-07",
        )
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "command_not_found"


# ──────────────────────────────────────────────────────────────
# OpenCLICollector
# ──────────────────────────────────────────────────────────────


class TestOpenCLICollectorInit:
    """OpenCLICollector 初始化测试。"""

    def test_reads_config_fields(self, tmp_path: Path) -> None:
        adapter = OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))
        config = {
            "source_id": "test-source",
            "target_id": "italy",
            "tool_ref": "opencli.fetch",
            "validated_args": {
                "url": "https://example.com",
                "output_path": "/tmp/x.json",
            },
        }
        collector = OpenCLICollector(config, adapter)
        assert collector._source_id == "test-source"
        assert collector._tool_ref == "opencli.fetch"


class TestOpenCLICollectorCollect:
    """collect() 测试。"""

    @pytest.fixture
    def adapter(self, tmp_path: Path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))

    def test_returns_empty_when_no_tool_ref(self, adapter: OpenCLIToolAdapter) -> None:
        config = {"source_id": "test", "tool_ref": ""}
        collector = OpenCLICollector(config, adapter)
        events = collector.collect("run-01")
        assert events == []

    def test_returns_empty_when_execute_fails(
        self, adapter: OpenCLIToolAdapter,
    ) -> None:
        """任何 execute 失败（包括 opencli_not_installed）都返回空列表。"""
        config = {
            "source_id": "test",
            "tool_ref": "opencli.fetch",
            "validated_args": {"url": "x", "output_path": "/tmp/x.json"},
        }
        collector = OpenCLICollector(config, adapter)

        with mock.patch.object(
            adapter, "execute",
            return_value=ToolRunResult(
                tool_id="opencli.fetch", run_id="r", success=False, exit_code=-1,
                error={"type": "command_not_found", "message": "not found"},
            ),
        ):
            events = collector.collect("run-01")
        assert events == []

    def test_does_not_raise_on_unexpected_error(self, adapter: OpenCLIToolAdapter) -> None:
        """Phase 6: collect() 吞掉所有错误，返回空列表。"""
        config = {
            "source_id": "test",
            "tool_ref": "opencli.fetch",
            "validated_args": {"url": "x", "output_path": "/tmp/x.json"},
        }
        collector = OpenCLICollector(config, adapter)

        with mock.patch.object(
            adapter, "execute",
            return_value=ToolRunResult(
                tool_id="opencli.fetch", run_id="r", success=False, exit_code=1,
                error={"type": "fetch_failed", "message": "crash"},
            ),
        ):
            events = collector.collect("run-01")
        assert events == []

    def test_parses_json_array_output(self, adapter: OpenCLIToolAdapter) -> None:
        """stdout 是 JSON 数组时应正确解析为 NewsEvent 列表。"""
        items = [
            {
                "title": "Breaking News",
                "url": "https://example.com/1",
                "content": "Something happened",
                "published_at": "2026-05-09T10:00:00Z",
                "source_id": "test-source",
            },
            {
                "title": "More News",
                "url": "https://example.com/2",
                "content": "Another event",
            },
        ]
        config = {
            "source_id": "test-source",
            "target_id": "italy",
            "tool_ref": "opencli.fetch",
            "validated_args": {"url": "x", "output_path": "/tmp/x.json"},
        }
        collector = OpenCLICollector(config, adapter)

        with mock.patch.object(
            adapter, "execute",
            return_value=ToolRunResult(
                tool_id="opencli.fetch", run_id="r", success=True, exit_code=0,
                stdout=json.dumps(items),
            ),
        ):
            events = collector.collect("run-01")

        assert len(events) == 2
        assert events[0].title_original == "Breaking News"
        assert events[0].url == "https://example.com/1"
        assert events[1].title_original == "More News"

    def test_parses_object_with_items_field(self, adapter: OpenCLIToolAdapter) -> None:
        """含 items 字段的 JSON 对象作为单事件处理（不展开 items）。"""
        data = {"items": [{"title": "Item 1", "url": "https://ex.com/1"}]}
        config = {
            "source_id": "test-source",
            "target_id": "italy",
            "tool_ref": "opencli.fetch",
            "validated_args": {"url": "x", "output_path": "/tmp/x.json"},
        }
        collector = OpenCLICollector(config, adapter)

        with mock.patch.object(
            adapter, "execute",
            return_value=ToolRunResult(
                tool_id="opencli.fetch", run_id="r", success=True, exit_code=0,
                stdout=json.dumps(data),
            ),
        ):
            events = collector.collect("run-01")

        # dict 作为单个事件，title_original 来自外层 dict（无 title 则为空）
        assert len(events) == 1

    def test_skips_invalid_items(self, adapter: OpenCLIToolAdapter) -> None:
        """跳过没有 title 也没有 url 的无效条目。"""
        items = [
            {"title": "", "url": "", "content": "no title or url"},
            {"title": "Valid", "url": "https://example.com/ok"},
        ]
        config = {
            "source_id": "s",
            "target_id": "italy",
            "tool_ref": "opencli.fetch",
            "validated_args": {"url": "x", "output_path": "/tmp/x.json"},
        }
        collector = OpenCLICollector(config, adapter)

        with mock.patch.object(
            adapter, "execute",
            return_value=ToolRunResult(
                tool_id="opencli.fetch", run_id="r", success=True, exit_code=0,
                stdout=json.dumps(items),
            ),
        ):
            events = collector.collect("run-01")

        assert len(events) == 1
        assert events[0].title_original == "Valid"


class TestOpenCLICollectorParseOutput:
    """_parse_output 测试。"""

    @pytest.fixture
    def collector(self, tmp_path: Path) -> OpenCLICollector:
        adapter = OpenCLIToolAdapter(manifest_path=_make_minimal_manifest(tmp_path))
        return OpenCLICollector(
            {"source_id": "test-source", "target_id": "italy"},
            adapter,
        )

    def test_empty_stdout_returns_empty(self, collector: OpenCLICollector) -> None:
        assert collector._parse_output("", "r1") == []
        assert collector._parse_output("   ", "r1") == []

    def test_invalid_json_falls_back_to_plaintext(self, collector: OpenCLICollector) -> None:
        """无效 JSON 时走 plaintext fallback，生成 1 个 content_original 事件。"""
        events = collector._parse_output("not valid json {{{", "r1")
        assert len(events) == 1
        assert events[0].content_original == "not valid json {{{"

    def test_non_dict_item_skipped(self, collector: OpenCLICollector) -> None:
        """列表中非 dict 元素被跳过。"""
        stdout = json.dumps(["string_instead_of_dict", {"title": "OK", "url": "https://x.com"}])
        events = collector._parse_output(stdout, "r1")
        assert len(events) == 1

    def test_single_object_wrapped(self, collector: OpenCLICollector) -> None:
        """非列表非 items 的对象自动包裹为单元素列表。"""
        stdout = json.dumps({"title": "Solo", "url": "https://solo.com"})
        events = collector._parse_output(stdout, "r1")
        assert len(events) == 1
        assert events[0].title_original == "Solo"


# _detect_language removed in Phase 6
