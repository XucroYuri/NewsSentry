"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.3

OpenCLIToolAdapter — wraps OpenCLI subprocess calls per ADR-0008 and ADR-0011.
"""
from __future__ import annotations

import shlex
import subprocess  # noqa: S404
import time
from pathlib import Path
from typing import Any

import yaml

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.core.sandbox import SandboxEnforcer, SandboxViolationError


class OpenCLIToolAdapter:
    """Executes opencli commands as subprocess. ADR-0008: install, don't vendor."""

    tool_id = "opencli"

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        sandbox_enforcer: SandboxEnforcer | None = None,
    ) -> None:
        """加载 ToolManifest，构建 tool_id → definition 映射。

        Args:
            manifest_path: opencli-baseline.yaml 路径，默认从 config/toolmanifest/ 加载。
            sandbox_enforcer: 沙箱执行器，用于命令/路径/主机预检。
        """
        self._sandbox = sandbox_enforcer

        if manifest_path is None:
            manifest_path = self._default_manifest_path()
        self._manifest_path = Path(manifest_path)
        self._tools: dict[str, dict[str, Any]] = {}

        raw = self._manifest_path.read_text(encoding="utf-8")
        manifest = yaml.safe_load(raw) or {}
        for tool_def in manifest.get("tools", []):
            tid = tool_def.get("tool_id", "")
            if tid:
                self._tools[tid] = tool_def

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def execute(
        self, tool_id: str, validated_args: dict[str, Any], run_id: str,
    ) -> ToolRunResult:
        """执行指定 opencli 命令，返回结构化结果。

        Args:
            tool_id: 工具标识（如 "opencli.fetch"）。
            validated_args: 已验证的参数，key 对应 command_template 中的 {param}。
            run_id: 本次运行标识。

        Returns:
            ToolRunResult 含 exit_code、stdout、stderr、duration_ms 等。
        """
        tool_def = self._tools.get(tool_id)
        if tool_def is None:
            return ToolRunResult(
                tool_id=tool_id, run_id=run_id, success=False,
                exit_code=-1, stderr=f"未知工具: {tool_id}",
                error={
                    "type": "unknown_tool",
                    "message": f"Tool '{tool_id}' not in manifest",
                },
            )

        # 参数 schema 校验（ADR-0011 §exit_codes 及 parameters_schema）
        args_error = self._validate_args(
            tool_id,
            tool_def.get("parameters_schema", {}),
            validated_args,
        )
        if args_error is not None:
            return ToolRunResult(
                tool_id=tool_id, run_id=run_id, success=False,
                exit_code=2, error=args_error,
            )

        command = self._build_command(tool_id, validated_args)
        if not command:
            return ToolRunResult(
                tool_id=tool_id, run_id=run_id, success=False,
                exit_code=-1, stderr="无法构建命令",
                error={
                    "type": "command_build_failed",
                    "message": "command_template 解析失败",
                },
            )

        # 沙箱预检 — enforce() raises SandboxViolationError on violation
        if self._sandbox is not None:
            try:
                # SandboxEnforcer.enforce() 通过 args dict 中的 command/url/path 字段校验
                enforce_args: dict[str, Any] = dict(validated_args)
                enforce_args["command"] = shlex.join(command)
                self._sandbox.enforce(tool_id, enforce_args)
            except SandboxViolationError as e:
                return ToolRunResult(
                    tool_id=tool_id, run_id=run_id, success=False,
                    exit_code=-1, stderr=str(e),
                    error={"type": "sandbox_blocked", "message": str(e)},
                )

        t0 = time.monotonic()
        try:
            # opencli 是 shell 命令，需通过 shell 执行（已由沙箱预检其安全性）
            cmd_str = shlex.join(command)
            proc = subprocess.run(  # noqa: S602
                cmd_str, shell=True, capture_output=True, text=True, timeout=60,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - t0) * 1000)
            return ToolRunResult(
                tool_id=tool_id, run_id=run_id, success=False,
                exit_code=2, duration_ms=duration_ms,
                error={"type": "timeout", "message": "subprocess timed out after 60s"},
            )
        except FileNotFoundError:
            duration_ms = int((time.monotonic() - t0) * 1000)
            msg = "opencli 未安装或不在 PATH 中"
            return ToolRunResult(
                tool_id=tool_id, run_id=run_id, success=False,
                exit_code=-1, stderr=msg, duration_ms=duration_ms,
                error={"type": "opencli_not_installed", "message": msg},
            )

        error = self._map_exit_code(tool_id, proc.returncode)
        if error is None:
            success = True
        else:
            success = False
            stderr_msg = proc.stderr.strip()
            if stderr_msg:
                error["message"] = stderr_msg

        return ToolRunResult(
            tool_id=tool_id, run_id=run_id, success=success,
            exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
            duration_ms=duration_ms, error=error,
        )

    def _build_command(self, tool_id: str, args: dict[str, Any]) -> list[str]:
        """用 {param} 模板填充构建命令列表。

        Args:
            tool_id: 工具标识。
            args: 参数键值对。

        Returns:
            填充后的命令参数列表。
        """
        tool_def = self._tools.get(tool_id)
        if tool_def is None:
            return []

        template: str = tool_def.get("command_template", "")
        if not template:
            return []

        # 构建替换映射：{param} → str(value)
        replacements: dict[str, str] = {}
        for key, value in args.items():
            placeholder = "{" + key + "}"
            if placeholder in template:
                replacements[placeholder] = shlex.quote(str(value))

        if not replacements:
            return shlex.split(template)

        filled = template
        for ph, val in replacements.items():
            filled = filled.replace(ph, val)

        return shlex.split(filled)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _default_manifest_path() -> Path:
        """查找项目内的 opencli-baseline.yaml。"""
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            candidate = parent / "config" / "toolmanifest" / "opencli-baseline.yaml"
            if candidate.is_file():
                return candidate
        return Path("config/toolmanifest/opencli-baseline.yaml")

    @staticmethod
    def _validate_args(
        tool_id: str, parameters_schema: dict[str, Any], args: dict[str, Any],
    ) -> dict[str, str] | None:
        """校验 args 是否符合 parameters_schema。返回 None 表示通过。

        ADR-0011: 参数校验失败返回 exit_code=2 (args_invalid)。
        """
        if not parameters_schema:
            return None

        required: list[str] = list(parameters_schema.get("required", []) or [])
        for name in required:
            if name not in args:
                return {
                    "type": "args_invalid",
                    "message": f"Missing required parameter: {name}",
                }

        properties: dict[str, Any] = parameters_schema.get("properties", {}) or {}
        for name, value in args.items():
            prop: dict[str, Any] = properties.get(name, {}) or {}
            if not prop:
                continue

            enum_vals: Any = prop.get("enum")
            if enum_vals is not None and value not in enum_vals:
                return {
                    "type": "args_invalid",
                    "message": f"Invalid value for {name}: {value}",
                }

            if prop.get("type") == "integer":
                if not isinstance(value, int):
                    try:
                        int(value)
                    except (ValueError, TypeError):
                        return {
                            "type": "args_invalid",
                            "message": f"Expected integer for {name}, got: {value}",
                        }

        return None

    def _map_exit_code(self, tool_id: str, exit_code: int) -> dict[str, str] | None:
        """将 exit code 映射为 error dict（ADR-0011 标准码）。

        优先使用工具定义中的 exit_code_mapping，其次 exit_codes（向后兼容），
        最后回退到 ADR-0011 默认映射。
        返回 None 表示成功（exit_code 0）或空结果（exit_code 66）。
        """
        # ADR-0011 标准映射
        adr_defaults: dict[int, dict[str, str] | None] = {
            0: None,
            66: None,
            69: {"type": "browser_unavailable", "message": "Browser not connected"},
            77: {"type": "auth_required", "message": "Authentication required"},
            1: {"type": "tool_error", "message": "Tool execution error"},
            2: {"type": "args_invalid", "message": "Invalid arguments"},
        }

        mapping: dict[int, dict[str, str] | None] = dict(adr_defaults)
        tool_def = self._tools.get(tool_id, {})

        # exit_code_mapping 覆盖（int code → string type）
        for code, type_str in tool_def.get("exit_code_mapping", {}).items():
            if type_str == "result_empty":
                mapping[code] = None
            else:
                mapping[code] = {"type": type_str, "message": ""}

        # exit_codes 向后兼容覆盖（string code → string type）
        # 跳过 code 0（始终视为成功，不覆盖为 error dict）
        for code_str, type_str in tool_def.get("exit_codes", {}).items():
            code = int(code_str)
            if code == 0:
                continue
            mapping[code] = {"type": type_str, "message": ""}

        if exit_code in mapping:
            return mapping[exit_code]
        return {"type": "unknown_error", "message": f"Exit code {exit_code}"}
