"""Tests for ToolRegistry — load, lookup, health check, and risk filtering."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from news_sentry.core.tool_registry import ToolRegistry, load_from_config
from news_sentry.models.manifests import ExecutionType, RiskLevel, ToolManifest

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """创建模拟 toolmanifest 目录，含 opencli-baseline.yaml。"""
    tool_dir = tmp_path / "toolmanifest"
    tool_dir.mkdir()
    manifest = {
        "tools": [
            {
                "tool_id": "opencli.fetch",
                "display_name": "OpenCLI Fetch URL",
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
                "exit_codes": {"0": "success", "1": "fetch_failed"},
                "permissions": {
                    "risk_level": "medium",
                    "network": {"allowed_hosts": ["*"]},
                    "filesystem": {"read_roots": [], "write_roots": ["./data/{target_id}/raw/"]},
                    "browser": {"session_profile_required": False},
                    "credentials": {"required": []},
                },
            },
            {
                "tool_id": "opencli.search",
                "display_name": "OpenCLI Web Search",
                "version": "1.0.0",
                "execution_type": "subprocess",
                "command_template": "opencli search --query {query} --limit {limit}",
                "exit_codes": {"0": "success"},
                "permissions": {"risk_level": "medium"},
            },
            {
                "tool_id": "opencli.screenshot",
                "display_name": "OpenCLI Take Screenshot",
                "version": "1.0.0",
                "execution_type": "subprocess",
                "command_template": "opencli screenshot --url {url} --output {output_path}",
                "exit_codes": {"0": "success"},
                "permissions": {"risk_level": "high"},
            },
        ]
    }
    f = tool_dir / "opencli-baseline.yaml"
    f.write_text(yaml.dump(manifest), encoding="utf-8")
    return tool_dir


# ──────────────────────────────────────────────────────────────
# load_from_config (module-level function)
# ──────────────────────────────────────────────────────────────


class TestLoadFromConfig:
    """load_from_config() 函数测试。"""

    def test_loads_all_tools(self, manifest_dir: Path) -> None:
        tools = load_from_config(manifest_dir)
        assert set(tools.keys()) == {"opencli.fetch", "opencli.search", "opencli.screenshot"}

    def test_each_has_tool_id(self, manifest_dir: Path) -> None:
        tools = load_from_config(manifest_dir)
        for tid, tool in tools.items():
            assert tool.tool_id == tid

    def test_permissions_parsed_correctly(self, manifest_dir: Path) -> None:
        tools = load_from_config(manifest_dir)
        fetch = tools["opencli.fetch"]
        assert fetch.permissions.risk_level == RiskLevel.MEDIUM
        assert fetch.permissions.network == {"allowed_hosts": ["*"]}

    def test_skips_empty_tool_id(self, tmp_path: Path) -> None:
        """tool_id 为空的条目应被跳过。"""
        d = tmp_path / "toolmanifest"
        d.mkdir()
        manifest = {
            "tools": [
                {"tool_id": "", "command_template": "echo"},
                {"tool_id": "valid.tool", "command_template": "echo"},
            ]
        }
        (d / "bad.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
        tools = load_from_config(d)
        assert "" not in tools
        assert "valid.tool" in tools

    def test_empty_manifest_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "empty_dir"
        d.mkdir()
        assert load_from_config(d) == {}

    def test_not_a_directory(self, tmp_path: Path) -> None:
        assert load_from_config(tmp_path / "nonesuch") == {}


# ──────────────────────────────────────────────────────────────
# ToolRegistry class
# ──────────────────────────────────────────────────────────────


class TestToolRegistry:
    """ToolRegistry 方法测试。"""

    @pytest.fixture
    def registry(self, manifest_dir: Path) -> ToolRegistry:
        return ToolRegistry(manifest_dir)

    def test_get_tool_returns_manifest(self, registry: ToolRegistry) -> None:
        t = registry.get_tool("opencli.fetch")
        assert isinstance(t, ToolManifest)
        assert t.tool_id == "opencli.fetch"
        assert t.execution_type == ExecutionType.SUBPROCESS

    def test_get_tool_unknown_returns_none(self, registry: ToolRegistry) -> None:
        assert registry.get_tool("nonexistent") is None

    def test_list_tools_returns_all(self, registry: ToolRegistry) -> None:
        tools = registry.list_tools()
        assert len(tools) == 3

    def test_list_tools_by_risk_medium(self, registry: ToolRegistry) -> None:
        medium = registry.list_tools_by_risk("medium")
        assert len(medium) == 2
        assert {t.tool_id for t in medium} == {"opencli.fetch", "opencli.search"}

    def test_list_tools_by_risk_high(self, registry: ToolRegistry) -> None:
        high = registry.list_tools_by_risk("high")
        assert len(high) == 1
        assert high[0].tool_id == "opencli.screenshot"

    def test_list_tools_by_risk_unknown(self, registry: ToolRegistry) -> None:
        assert registry.list_tools_by_risk("nonexistent") == []

    def test_check_tool_health_known_subprocess(self, registry: ToolRegistry) -> None:
        health = registry.check_tool_health("opencli.fetch")
        assert "tool_id" in health
        assert health["tool_id"] == "opencli.fetch"
        # opencli 可能不在测试环境的 PATH 中，所以只检查返回结构
        assert "ok" in health
        assert "command" in health

    def test_check_tool_health_unknown_tool(self, registry: ToolRegistry) -> None:
        health = registry.check_tool_health("unknown.tool")
        assert health == {"tool_id": "unknown.tool", "ok": False, "error": "unknown_tool"}
