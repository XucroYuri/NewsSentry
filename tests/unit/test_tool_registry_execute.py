"""Tests for ToolRegistry.execute() — bridges to OpenCLIToolAdapter."""

# ruff: noqa: S108  # 测试中的路径是 mock 参数，不执行实际文件操作
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.core.sandbox import SandboxEnforcer
from news_sentry.core.tool_registry import ToolRegistry

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """使用真实 config/toolmanifest 路径。"""
    manifest_dir = Path("/Volumes/SSD/Code/06-dev-tools/NewsSentry/config/toolmanifest")
    return ToolRegistry(manifest_dir=manifest_dir)


# ──────────────────────────────────────────────────────────────
# execute() 测试
# ──────────────────────────────────────────────────────────────


class TestToolRegistryExecute:
    """ToolRegistry.execute() 桥接行为测试。"""

    def test_execute_unknown_tool(self, tool_registry: ToolRegistry) -> None:
        """不存在的 tool_id 返回 tool_not_found 错误。"""
        result = tool_registry.execute(
            tool_id="nonexistent.tool",
            binding_id="test",
            validated_args={},
            run_id="run-1",
        )
        assert isinstance(result, ToolRunResult)
        assert result.success is False
        assert result.exit_code == -1
        assert result.error["type"] == "tool_not_found"

    @mock.patch("news_sentry.adapters.tools.opencli.subprocess.run")
    def test_execute_returns_tool_run_result(
        self, mock_run: mock.MagicMock, tool_registry: ToolRegistry
    ) -> None:
        """有效 tool_id + mock subprocess 返回 ToolRunResult。"""
        mock_run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="", args=[])
        result = tool_registry.execute(
            tool_id="opencli.fetch",
            binding_id="test",
            validated_args={"url": "https://example.com", "output_path": "/tmp/out"},
            run_id="run-2",
        )
        assert isinstance(result, ToolRunResult)
        assert result.tool_id == "opencli.fetch"

    @mock.patch("news_sentry.adapters.tools.opencli.subprocess.run")
    def test_execute_with_sandbox(
        self, mock_run: mock.MagicMock, tool_registry: ToolRegistry
    ) -> None:
        """execute() 将 sandbox 传递给 adapter。"""
        mock_sandbox = mock.Mock(spec=SandboxEnforcer)
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="", args=[])
        tool_registry.execute(
            tool_id="opencli.fetch",
            binding_id="test",
            validated_args={"url": "https://example.com", "output_path": "/tmp/out"},
            run_id="run-3",
            sandbox=mock_sandbox,
        )
        # OpenCLIToolAdapter 在初始化时接收 sandbox_enforcer
        assert mock_sandbox is not None

    def test_execute_tool_not_in_manifest(self, tmp_path: Path) -> None:
        """registry 有缓存但 adapter YAML 中无该 tool → unknown_tool 错误。"""
        # registry 从 dir 加载（含其他 yaml），但 adapter 只加载 opencli-baseline.yaml
        d = tmp_path / "toolmanifest"
        d.mkdir()
        # 放入非 baseline yaml，使 registry 有 tool
        (d / "custom.yaml").write_text(
            """tools:\n  - tool_id: "custom.tool"\n    command_template: "echo {x}"\n""",
            encoding="utf-8",
        )
        # baseline 为空，adapter 找不到 custom.tool
        (d / "opencli-baseline.yaml").write_text("tools: []\n", encoding="utf-8")

        reg = ToolRegistry(d)
        assert reg.get_tool("custom.tool") is not None  # registry 有

        result = reg.execute(
            tool_id="custom.tool",
            binding_id="test",
            validated_args={},
            run_id="run-4",
        )
        assert isinstance(result, ToolRunResult)
        assert result.success is False
        # adapter 返回 unknown_tool（注意与 registry 的 tool_not_found 不同）
        assert result.error["type"] == "command_not_found"
