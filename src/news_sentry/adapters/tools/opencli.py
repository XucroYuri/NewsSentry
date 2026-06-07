"""Implements: docs/spec/phase-4-tool-skill-registry-opencli.md §3.3

OpenCLIToolAdapter — wraps OpenCLI subprocess calls per ADR-0008 and ADR-0011.
Loads ToolManifest from config/toolmanifest/opencli-baseline.yaml,
builds commands from templates, executes via subprocess with sandbox checks.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.core.sandbox import (
    SandboxDecision,
    SandboxEnforcer,
    SandboxViolationError,
    StopOnRiskError,
)

_SAFE_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
    }
)


def _default_manifest() -> Path:
    """返回默认 ToolManifest 路径。"""
    # opencli.py → tools/ → adapters/ → news_sentry/ → src/ → project_root/
    return (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "config"
        / "toolmanifest"
        / "opencli-baseline.yaml"
    )


class OpenCLIToolAdapter:
    """Executes opencli commands as subprocess. ADR-0008: install, don't vendor."""

    tool_id = "opencli"

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        sandbox_enforcer: SandboxEnforcer | None = None,
    ) -> None:
        """加载 ToolManifest YAML，构建 tool_id → manifest 映射。

        Args:
            manifest_path: opencli-baseline.yaml 的路径。
                默认: config/toolmanifest/opencli-baseline.yaml
            sandbox_enforcer: 可选的沙箱校验器。
                传入 None 时跳过沙箱检查（仅限测试）。
        """
        self._sandbox = sandbox_enforcer
        self._manifest_path = Path(manifest_path) if manifest_path else _default_manifest()
        self._tools: dict[str, dict[str, Any]] = {}
        self._load_manifest()

    # ── 公开方法 ──────────────────────────────────────────────

    def execute(self, tool_ref: str, validated_args: dict[str, Any], run_id: str) -> ToolRunResult:
        """执行一个 OpenCLI 工具调用。

        Args:
            tool_ref: ToolManifest tool_id（如 "opencli.fetch"）。
            validated_args: 已校验的参数 dict，用于填充 command_template。
            run_id: 本次 bounded run ID。

        Returns:
            ToolRunResult，含 exit_code / stdout / stderr / error。

        Raises:
            ValueError: tool_ref 不在 manifest 中。
        """
        manifest = self._tools.get(tool_ref)
        if manifest is None:
            return ToolRunResult(
                tool_id=tool_ref,
                run_id=run_id,
                success=False,
                exit_code=-1,
                error={
                    "type": "command_not_found",
                    "message": f"tool_ref '{tool_ref}' not found in manifest",
                },
            )

        # 构建命令
        try:
            command = self._build_command(manifest, validated_args)
        except (KeyError, ValueError) as e:
            return ToolRunResult(
                tool_id=tool_ref,
                run_id=run_id,
                success=False,
                exit_code=-1,
                error={
                    "type": "schema_validation_failed",
                    "message": f"missing required parameter: {e}",
                },
            )

        # 沙箱预检（Phase 6: + stop-on-risk + audit log）
        if self._sandbox is not None:
            try:
                self._sandbox.enforce(tool_ref, validated_args)
            except SandboxViolationError as e:
                # stop-on-risk 检查（可能 raise StopOnRiskError，必须传播）
                try:
                    self._sandbox.check_stop_on_risk(
                        "sandbox_violation",
                        tool_ref,
                        run_id,
                    )
                except StopOnRiskError:
                    raise
                # audit: 被沙箱拒绝的调用
                self._sandbox.audit_tool_call(
                    tool_id=tool_ref,
                    decision=SandboxDecision(
                        verdict="deny",
                        check_dimension="sandbox",
                        reason=str(e),
                    ),
                    args_summary=validated_args,
                    run_id=run_id,
                )
                return ToolRunResult(
                    tool_id=tool_ref,
                    run_id=run_id,
                    success=False,
                    exit_code=-1,
                    error={
                        "type": "permission_denied",
                        "message": str(e),
                    },
                )

        # 执行
        timeout_s = manifest.get("timeout_seconds", 60)
        t0 = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603 — command built from trusted YAML manifest template
                command,
                capture_output=True,
                env=self._subprocess_env(),
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - t0) * 1000)
            if self._sandbox is not None:
                self._sandbox.audit_tool_call(
                    tool_id=tool_ref,
                    decision=SandboxDecision(
                        verdict="deny",
                        check_dimension="budget",
                        reason=f"timeout after {timeout_s}s",
                    ),
                    duration_ms=duration_ms,
                    args_summary=validated_args,
                    run_id=run_id,
                )
            return ToolRunResult(
                tool_id=tool_ref,
                run_id=run_id,
                success=False,
                exit_code=-1,
                duration_ms=duration_ms,
                error={
                    "type": "timeout",
                    "message": f"subprocess timed out after {timeout_s}s",
                },
            )
        except FileNotFoundError:
            if self._sandbox is not None:
                self._sandbox.audit_tool_call(
                    tool_id=tool_ref,
                    decision=SandboxDecision(
                        verdict="deny",
                        check_dimension="command",
                        reason="executable not found",
                    ),
                    args_summary=validated_args,
                    run_id=run_id,
                )
            return ToolRunResult(
                tool_id=tool_ref,
                run_id=run_id,
                success=False,
                exit_code=-1,
                error={
                    "type": "command_not_found",
                    "message": "opencli executable not found in PATH",
                },
            )

        duration_ms = int((time.monotonic() - t0) * 1000)

        # Phase 6: exit_code=77 → stop-on-risk auth_error
        if completed.returncode == 77 and self._sandbox is not None:
            try:
                self._sandbox.check_stop_on_risk(
                    "auth_error",
                    tool_ref,
                    run_id,
                )
            except StopOnRiskError:
                raise

        # Phase 6: audit tool call（每次执行写一条 audit log）
        if self._sandbox is not None:
            self._sandbox.audit_tool_call(
                tool_id=tool_ref,
                decision=SandboxDecision(
                    verdict="allow",
                    check_dimension="command",
                    reason="sandbox pre-check passed",
                ),
                result_exit_code=completed.returncode,
                duration_ms=duration_ms,
                args_summary=validated_args,
                run_id=run_id,
            )

        # 退出码映射
        exit_code_map: dict[int, str] = {}
        raw_map = manifest.get("exit_codes", {})
        if isinstance(raw_map, dict):
            for code_str, err_type in raw_map.items():
                try:
                    exit_code_map[int(code_str)] = str(err_type)
                except (ValueError, TypeError):
                    pass

        return ToolRunResult.from_subprocess(
            tool_id=tool_ref,
            run_id=run_id,
            completed=completed,
            duration_ms=duration_ms,
            exit_code_map=exit_code_map,
        )

    def list_tools(self) -> list[str]:
        """返回 manifest 中所有已注册的 tool_id。"""
        return list(self._tools.keys())

    def get_manifest(self, tool_ref: str) -> dict[str, Any] | None:
        """返回指定 tool_ref 的 manifest，未找到时返回 None。"""
        return self._tools.get(tool_ref)

    def _subprocess_env(self) -> dict[str, str] | None:
        """Return a minimal child process env when sandbox policy denies env passthrough."""
        if self._sandbox is None or not self._sandbox.policy.command.deny_env_passthrough:
            return None
        return {key: value for key, value in os.environ.items() if key in _SAFE_SUBPROCESS_ENV_KEYS}

    # ── 内部方法 ──────────────────────────────────────────────

    def _load_manifest(self) -> None:
        """加载 YAML manifest 文件。"""
        if not self._manifest_path.is_file():
            return
        with open(self._manifest_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return
        tools = data.get("tools")
        if not isinstance(tools, list):
            return
        for entry in tools:
            if isinstance(entry, dict) and entry.get("tool_id"):
                self._tools[entry["tool_id"]] = entry

    @staticmethod
    def _build_command(manifest: dict[str, Any], args: dict[str, Any]) -> list[str]:
        """从 command_template 和参数构建命令列表。

        模板中的 {param_name} 由 args 中的同名键替换。
        缺失必填参数时 raise KeyError。
        """
        template: str = manifest.get("command_template", "")
        if not template:
            raise ValueError("manifest missing command_template")

        # 收集模板中的参数名
        required_params = set(re.findall(r"\{(\w+)\}", template))

        # 验证必填参数
        missing = required_params - set(args.keys())
        if missing:
            raise KeyError(next(iter(missing)))

        # 替换
        filled = template
        for key, val in args.items():
            filled = filled.replace(f"{{{key}}}", shlex.quote(str(val)))

        # 使用 shlex 安全拆分（处理带空格参数）
        return shlex.split(filled)
