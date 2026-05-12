"""OpenCLIToolAdapter stop-on-risk 集成测试。

验证 SandboxEnforcer + OpenCLIToolAdapter 的 stop-on-risk 流程：
- sandbox_violation 信号 → StopOnRiskError 或 permission_denied
- auth_error 信号（exit_code=77）→ StopOnRiskError 或 ToolRunResult
- audit log JSONL 写入
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import yaml

from news_sentry.adapters.tools.base import ToolRunResult
from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.sandbox import (
    SandboxEnforcer,
    SandboxPolicy,
    SandboxViolationError,
    StopOnRiskConfig,
    StopOnRiskError,
)

# ── 辅助函数 / fixtures ──────────────────────────────────────────────


def _make_opencli_fetch_manifest(tmp_path: Path) -> Path:
    """创建含 opencli.fetch 工具的临时 manifest YAML。"""
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
                "exit_codes": {
                    "0": "success",
                    "1": "fetch_failed",
                    "2": "timeout",
                    "3": "permission_denied",
                },
                "permissions": {
                    "risk_level": "medium",
                    "network": {"allowed_hosts": ["*"]},
                    "filesystem": {
                        "read_roots": [],
                        "write_roots": ["./data/{target_id}/raw/"],
                    },
                    "browser": {"session_profile_required": False},
                    "credentials": {"required": []},
                },
            },
        ]
    }
    p = tmp_path / "toolmanifest" / "opencli-baseline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(manifest), encoding="utf-8")
    return p


@pytest.fixture
def fetch_tool_args(tmp_path: Path) -> dict:
    """opencli.fetch 需要的合法参数。"""
    return {"url": "https://www.ansa.it/news", "output_path": str(tmp_path / "test_out.json")}


# ── 测试：沙箱违规 → stop-on-risk ────────────────────────────────────


class TestSandboxViolationStopOnRisk:
    """sandbox_violation 信号的 stop-on-risk 行为。"""

    def test_sandbox_violation_triggers_stop_on_risk(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_sandbox_violation=True + on_deny='stop' → StopOnRiskError 传播。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_sandbox_violation=True,
                on_deny="stop",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )

        with (
            mock.patch.object(
                sandbox,
                "enforce",
                side_effect=SandboxViolationError("blocked by sandbox"),
            ),
            pytest.raises(StopOnRiskError, match="stop-on-risk 触发"),
        ):
            adapter.execute("opencli.fetch", fetch_tool_args, "run-stop-01")

    def test_sandbox_violation_log_and_continue(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_sandbox_violation=True + on_deny='log_and_continue'
        → 返回 ToolRunResult(error type=permission_denied)，不抛异常。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_sandbox_violation=True,
                on_deny="log_and_continue",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )

        with mock.patch.object(
            sandbox,
            "enforce",
            side_effect=SandboxViolationError("blocked by sandbox"),
        ):
            result = adapter.execute(
                "opencli.fetch",
                fetch_tool_args,
                "run-stop-02",
            )

        assert isinstance(result, ToolRunResult)
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "permission_denied"

    def test_sandbox_violation_disabled(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_sandbox_violation=False → 返回 ToolRunResult(permission_denied)，不抛异常。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_sandbox_violation=False,
                on_deny="stop",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )

        with mock.patch.object(
            sandbox,
            "enforce",
            side_effect=SandboxViolationError("blocked by sandbox"),
        ):
            result = adapter.execute(
                "opencli.fetch",
                fetch_tool_args,
                "run-stop-03",
            )

        assert isinstance(result, ToolRunResult)
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "permission_denied"


# ── 测试：exit_code=77 → auth_error stop-on-risk ──────────────────────


class TestExitCode77StopOnRisk:
    """exit_code=77 触发的 auth_error stop-on-risk 行为。"""

    def test_exit_code_77_triggers_auth_error_stop(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_auth_error=True + on_deny='stop' → subprocess exit_code=77 时
        StopOnRiskError 传播。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_auth_error=True,
                on_deny="stop",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )
        mock_proc = mock.Mock()
        mock_proc.returncode = 77
        mock_proc.stdout = ""
        mock_proc.stderr = "auth expired"

        with (
            mock.patch.object(sandbox, "enforce"),
            mock.patch("subprocess.run", return_value=mock_proc),
            pytest.raises(StopOnRiskError, match="stop-on-risk 触发"),
        ):
            adapter.execute("opencli.fetch", fetch_tool_args, "run-77-stop-01")

    def test_exit_code_77_log_and_continue(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_auth_error=True + on_deny='log_and_continue'
        → subprocess exit_code=77 时返回 ToolRunResult，不抛异常。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_auth_error=True,
                on_deny="log_and_continue",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )
        mock_proc = mock.Mock()
        mock_proc.returncode = 77
        mock_proc.stdout = ""
        mock_proc.stderr = "auth expired"

        with (
            mock.patch.object(sandbox, "enforce"),
            mock.patch("subprocess.run", return_value=mock_proc),
        ):
            result = adapter.execute(
                "opencli.fetch",
                fetch_tool_args,
                "run-77-stop-02",
            )

        assert isinstance(result, ToolRunResult)
        assert result.exit_code == 77
        # exit_code=77 may still be "success" since from_subprocess checks == 0
        # The key assertion: no exception was raised

    def test_exit_code_77_auth_error_disabled(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """on_auth_error=False → subprocess exit_code=77 时正常返回 ToolRunResult。"""
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            stop_on_risk=StopOnRiskConfig(
                on_auth_error=False,
                on_deny="stop",
            ),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )
        mock_proc = mock.Mock()
        mock_proc.returncode = 77
        mock_proc.stdout = ""
        mock_proc.stderr = "auth expired"

        with (
            mock.patch.object(sandbox, "enforce"),
            mock.patch("subprocess.run", return_value=mock_proc),
        ):
            result = adapter.execute(
                "opencli.fetch",
                fetch_tool_args,
                "run-77-stop-03",
            )

        assert isinstance(result, ToolRunResult)
        assert result.exit_code == 77


# ── 测试：audit log 写入 ─────────────────────────────────────────────


class TestAuditLogWritten:
    """audit_tool_call 的 JSONL 写入验证。"""

    def test_audit_log_written_on_sandbox_violation(
        self,
        tmp_path: Path,
        fetch_tool_args: dict,
    ) -> None:
        """沙箱违规时，audit_tool_call 创建一个 JSONL 文件在 audit_log_path 中。"""
        logs_dir = tmp_path / "logs"
        manifest_path = _make_opencli_fetch_manifest(tmp_path)
        policy = SandboxPolicy(
            audit_log_enabled=True,
            stop_on_risk=StopOnRiskConfig(
                on_sandbox_violation=False,  # 不触发 stop，才能走到 audit
            ),
        )
        sandbox = SandboxEnforcer(policy, audit_log_path=logs_dir)
        adapter = OpenCLIToolAdapter(
            manifest_path=str(manifest_path),
            sandbox_enforcer=sandbox,
        )

        with mock.patch.object(
            sandbox,
            "enforce",
            side_effect=SandboxViolationError("blocked by sandbox"),
        ):
            adapter.execute("opencli.fetch", fetch_tool_args, "run-audit-01")

        # 验证 JSONL 文件被创建，且包含正确的记录
        log_file = logs_dir / "tool-audit-run-audit-01.jsonl"
        assert log_file.is_file()

        content = log_file.read_text(encoding="utf-8").strip()
        assert content, "audit log should not be empty"
        # 至少写了一条记录（JSON 行）
        lines = content.split("\n")
        assert len(lines) >= 1

        # 验证记录内容
        import json as _json

        record = _json.loads(lines[0])
        assert record["decision"] == "deny"
        assert record["check_dimension"] == "sandbox"
        assert record["tool_id"] == "opencli.fetch"
        assert record["run_id"] == "run-audit-01"
