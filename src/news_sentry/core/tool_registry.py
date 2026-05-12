"""Phase 4: ToolManifest Registry — loads and manages OpenCLI tool manifests."""

from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Any

import yaml

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.models.manifests import (
    ExecutionType,
    RiskLevel,
    ToolManifest,
    ToolPermissions,
)


def _build_tool_manifest(tool_data: dict[str, Any]) -> ToolManifest | None:
    """从 YAML dict 构建 ToolManifest 对象。

    跳过 tool_id 为空的条目，返回 None。
    """
    tool_id = tool_data.get("tool_id")
    if not tool_id:
        return None

    # 构建 permissions 子对象
    perms_raw = tool_data.get("permissions", {})
    if isinstance(perms_raw, dict):
        permissions = ToolPermissions(
            risk_level=RiskLevel(perms_raw.get("risk_level", "low")),
            network=perms_raw.get("network", {}),
            filesystem=perms_raw.get("filesystem", {}),
            browser=perms_raw.get("browser", {}),
            credentials=perms_raw.get("credentials", {}),
        )
    else:
        permissions = ToolPermissions(risk_level=RiskLevel.LOW)

    return ToolManifest(
        tool_id=tool_id,
        display_name=tool_data.get("display_name", tool_id),
        version=tool_data.get("version", "1.0.0"),
        execution_type=ExecutionType(tool_data.get("execution_type", "subprocess")),
        command_template=tool_data.get("command_template"),
        parameters_schema=tool_data.get("parameters_schema", {}),
        output_schema=tool_data.get("output_schema", {}),
        exit_codes=tool_data.get("exit_codes", {}),
        permissions=permissions,
    )


def load_from_config(manifest_dir: Path) -> dict[str, ToolManifest]:
    """解析 manifest_dir 下所有 YAML 文件，构建 ToolManifest 对象。

    Args:
        manifest_dir: config/toolmanifest/ 目录路径。

    Returns:
        tool_id -> ToolManifest 映射字典。
    """
    tools: dict[str, ToolManifest] = {}
    if not manifest_dir.is_dir():
        return tools

    for yaml_file in sorted(manifest_dir.glob("*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except Exception:  # noqa: S112
            continue

        tool_list = data.get("tools", []) if isinstance(data, dict) else []
        for tool_data in tool_list:
            if not isinstance(tool_data, dict):
                continue
            manifest = _build_tool_manifest(tool_data)
            if manifest is not None:
                tools[manifest.tool_id] = manifest

    return tools


class ToolRegistry:
    """ToolManifest 注册中心 — 管理工具清单的加载、查询与健康检查。"""

    def __init__(self, manifest_dir: Path) -> None:
        self._manifest_dir = manifest_dir
        self._tools: dict[str, ToolManifest] = load_from_config(manifest_dir)

    def get_tool(self, tool_id: str) -> ToolManifest | None:
        """按 tool_id 查找工具。"""
        return self._tools.get(tool_id)

    def list_tools(self) -> list[ToolManifest]:
        """返回所有已注册工具。"""
        return list(self._tools.values())

    def check_tool_health(self, tool_id: str) -> dict[str, Any]:
        """检查某个工具是否可用。

        对于 subprocess 类型的工具，检查命令是否在 PATH 中。
        返回结构化健康状态。
        """
        tool = self._tools.get(tool_id)
        if tool is None:
            return {"tool_id": tool_id, "ok": False, "error": "unknown_tool"}

        if tool.execution_type == ExecutionType.SUBPROCESS and tool.command_template:
            cmd_name = tool.command_template.split()[0]
            cmd_path = which(cmd_name)
            return {
                "tool_id": tool_id,
                "ok": cmd_path is not None,
                "command": cmd_name,
                "path": cmd_path,
            }

        # HTTP / Python 类型暂不做运行时检查
        return {"tool_id": tool_id, "ok": True, "execution_type": tool.execution_type.value}

    def execute(
        self,
        tool_id: str,
        binding_id: str,
        validated_args: dict[str, Any],
        run_id: str,
        sandbox: Any = None,  # noqa: ANN401 — SandboxEnforcer 避免循环导入
    ) -> ToolRunResult:
        """Execute a registered tool through OpenCLIToolAdapter.

        This bridges ToolRegistry (SPEC's central execution hub) to
        OpenCLIToolAdapter (subprocess execution + sandbox pre-check).

        Args:
            tool_id: Registered tool identifier (e.g., "opencli.hackernews.top").
            binding_id: Caller identifier for audit trail.
            validated_args: Arguments validated against parameters_schema.
            run_id: Current bounded run identifier.
            sandbox: SandboxEnforcer instance for pre-execution safety checks.

        Returns:
            ToolRunResult with exit_code, stdout, stderr, error info.
        """
        if tool_id not in self._tools:
            return ToolRunResult(
                tool_id=tool_id,
                run_id=run_id,
                success=False,
                exit_code=-1,
                error={
                    "type": "tool_not_found",
                    "message": f"Tool '{tool_id}' not registered",
                },
            )

        adapter = OpenCLIToolAdapter(
            manifest_path=self._manifest_dir / "opencli-baseline.yaml",
            sandbox_enforcer=sandbox,
        )
        return adapter.execute(tool_id, validated_args, run_id)

    def list_tools_by_risk(self, risk_level: str) -> list[ToolManifest]:
        """按风险等级过滤工具。"""
        return [t for t in self._tools.values() if t.permissions.risk_level.value == risk_level]
