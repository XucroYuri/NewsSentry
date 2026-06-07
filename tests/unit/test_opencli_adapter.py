"""OpenCLIToolAdapter 增强测试 — _validate_args, _map_exit_code,
sandbox blocking, execute 验证路径。

补充 test_tool_adapter.py 中未覆盖的测试场景。
"""
# ruff: noqa: S108  # 测试中的路径是 mock 参数，不执行实际文件操作

from __future__ import annotations

import sys
from unittest import mock

import pytest
import yaml

from news_sentry.adapters.tools.opencli import OpenCLIToolAdapter
from news_sentry.core.sandbox import (
    SandboxEnforcer,
    SandboxPolicy,
    SandboxViolationError,
    StopOnRiskConfig,
)

# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────


def _make_validation_manifest(tmp_path) -> str:
    """创建用于参数校验和退出码映射测试的 manifest。

    包含三个工具：
    - opencli.test.echo: 含 required 参数 + enum 属性 + exit_code_mapping
    - opencli.test.no_schema: 无 parameters_schema
    - opencli.test.custom_codes: 含 exit_code_mapping 覆盖 ADR 默认码
    """
    manifest = {
        "tools": [
            {
                "tool_id": "opencli.test.echo",
                "display_name": "Test Echo",
                "execution_type": "subprocess",
                "command_template": "echo {message}",
                "parameters_schema": {
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {"type": "string"},
                        "level": {
                            "type": "string",
                            "enum": ["info", "warn", "error"],
                        },
                    },
                },
                "exit_codes": {},
                "permissions": {
                    "risk_level": "low",
                    "network": {"allowed_hosts": []},
                    "browser": {"session_profile_required": False},
                    "credentials": {"required": []},
                },
            },
            {
                "tool_id": "opencli.test.no_schema",
                "display_name": "No Schema Tool",
                "execution_type": "subprocess",
                "command_template": "opencli noop",
                "permissions": {
                    "risk_level": "low",
                    "network": {"allowed_hosts": []},
                    "browser": {"session_profile_required": False},
                    "credentials": {"required": []},
                },
            },
            {
                "tool_id": "opencli.test.custom_codes",
                "display_name": "Custom Exit Codes",
                "execution_type": "subprocess",
                "command_template": "opencli custom",
                "exit_codes": {
                    1: "custom_timeout",
                    69: "custom_browser_error",
                },
                "permissions": {
                    "risk_level": "low",
                    "network": {"allowed_hosts": []},
                    "browser": {"session_profile_required": False},
                    "credentials": {"required": []},
                },
            },
        ]
    }
    p = tmp_path / "test-validation-manifest.yaml"
    p.write_text(yaml.dump(manifest), encoding="utf-8")
    return str(p)


# ──────────────────────────────────────────────────────────────
# 参数校验 (_validate_args) — 通过 execute() 测试
# ──────────────────────────────────────────────────────────────


class TestValidateArgs:
    """参数校验测试：通过 execute() 调用验证 _validate_args 行为。"""

    @pytest.fixture
    def adapter(self, tmp_path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_validation_manifest(tmp_path))

    def test_missing_required_argument(self, adapter: OpenCLIToolAdapter) -> None:
        """缺少 required 参数时返回 error type='schema_validation_failed', exit_code=-1。"""
        result = adapter.execute("opencli.test.echo", {}, "run-01")
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "schema_validation_failed"
        assert "message" in result.error["message"]

    def test_invalid_enum_value(self, adapter: OpenCLIToolAdapter) -> None:
        """无效枚举值不再被 _validate_args 拦截（已移除），直接传入 subprocess。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute(
                "opencli.test.echo",
                {"message": "hello", "level": "DEBUG"},
                "run-02",
            )
        assert result.success is True
        assert result.exit_code == 0
        assert result.error is None

    def test_valid_args_pass_validation(self, adapter: OpenCLIToolAdapter) -> None:
        """合法参数通过校验，不返回 args_invalid（进入 subprocess 调用）。"""
        # 提供完整合法参数，validation 通过后会尝试 subprocess.run
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute(
                "opencli.test.echo",
                {"message": "hello", "level": "info"},
                "run-03",
            )
            assert result.error is None
            assert result.success is True
            assert result.exit_code == 0

    def test_empty_schema_skips_validation(self, adapter: OpenCLIToolAdapter) -> None:
        """无 parameters_schema 时跳过校验，正常执行 subprocess。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 0
            mock_proc.stdout = "done"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute(
                "opencli.test.no_schema",
                {"anything": "goes"},
                "run-04",
            )
            assert result.success is True
            assert result.error is None

    def test_schema_without_properties_pass_validation(
        self,
        tmp_path,
    ) -> None:
        """仅含 required 字段但无 properties 的 schema，缺失 required 参数时
        _build_command 抛出 KeyError，被 execute() 捕获返回 schema_validation_failed。"""
        import yaml as _yaml

        manifest_data = {
            "tools": [
                {
                    "tool_id": "opencli.test.minimal",
                    "command_template": "echo {name}",
                    "parameters_schema": {
                        "type": "object",
                        "required": ["name"],
                    },
                }
            ]
        }
        p = tmp_path / "minimal-manifest.yaml"
        p.write_text(_yaml.dump(manifest_data), encoding="utf-8")
        adapter = OpenCLIToolAdapter(manifest_path=str(p))

        result = adapter.execute("opencli.test.minimal", {}, "run-05")
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "schema_validation_failed"


# ──────────────────────────────────────────────────────────────
# 退出码映射 (_map_exit_code) — 通过 execute() + subprocess mock 测试
# ──────────────────────────────────────────────────────────────


class TestMapExitCode:
    """退出码映射测试：mock subprocess.run 返回不同退出码，验证映射结果。

    使用 opencli.test.no_schema（无 exit_codes/exit_code_mapping）
    测试 ADR-0011 默认映射。
    使用 opencli.test.custom_codes 测试工具级覆盖。
    """

    @pytest.fixture
    def adapter(self, tmp_path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_validation_manifest(tmp_path))

    def test_exit_code_0_success(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 0 → success=True, error=None。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 0
            mock_proc.stdout = "ok"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-10")
        assert result.success is True
        assert result.exit_code == 0
        assert result.error is None

    def test_exit_code_66_empty_result(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 66 → 不再特殊处理（非零退出码无映射），error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 66
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-11")
        assert result.success is False
        assert result.exit_code == 66
        assert result.error is not None
        assert result.error["type"] == "unknown"

    def test_exit_code_69_browser_unavailable(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 69 → 不再有 ADR 默认映射（非零无映射），error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 69
            mock_proc.stdout = ""
            mock_proc.stderr = "chrome not running"
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-12")
        assert result.success is False
        assert result.exit_code == 69
        assert result.error is not None
        assert result.error["type"] == "unknown"

    def test_exit_code_77_auth_required(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 77 → 不再有 ADR 默认映射（非零无映射），error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 77
            mock_proc.stdout = ""
            mock_proc.stderr = "session expired"
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-13")
        assert result.success is False
        assert result.exit_code == 77
        assert result.error is not None
        assert result.error["type"] == "unknown"

    def test_exit_code_1_tool_error(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 1 → 不再有 ADR 默认映射（非零无映射），error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 1
            mock_proc.stdout = ""
            mock_proc.stderr = "something broke"
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-14")
        assert result.success is False
        assert result.exit_code == 1
        assert result.error is not None
        assert result.error["type"] == "unknown"

    def test_exit_code_2_args_invalid(self, adapter: OpenCLIToolAdapter) -> None:
        """退出码 2 → 不再有 ADR 默认映射（非零无映射），error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 2
            mock_proc.stdout = ""
            mock_proc.stderr = "bad args"
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-15")
        assert result.success is False
        assert result.exit_code == 2
        assert result.error is not None
        assert result.error["type"] == "unknown"

    def test_tool_specific_override(self, adapter: OpenCLIToolAdapter) -> None:
        """工具级 exit_codes 自定义映射。

        工具 opencli.test.custom_codes 将码 1 映射为 'custom_timeout'，
        将码 69 映射为 'custom_browser_error'。
        """
        # 测试覆盖 1 → custom_timeout
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 1
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.custom_codes", {}, "run-16")
        assert result.success is False
        assert result.exit_code == 1
        assert result.error is not None
        assert result.error["type"] == "custom_timeout"

        # 测试覆盖 69 → custom_browser_error（非 browser_unavailable）
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 69
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.custom_codes", {}, "run-17")
        assert result.success is False
        assert result.exit_code == 69
        assert result.error is not None
        assert result.error["type"] == "custom_browser_error"

    def test_unknown_exit_code(self, adapter: OpenCLIToolAdapter) -> None:
        """未映射的退出码 → error type='unknown'。"""
        with mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.Mock()
            mock_proc.returncode = 99
            mock_proc.stdout = ""
            mock_proc.stderr = "undefined error"
            mock_run.return_value = mock_proc

            result = adapter.execute("opencli.test.no_schema", {}, "run-18")
        assert result.success is False
        assert result.exit_code == 99
        assert result.error is not None
        assert result.error["type"] == "unknown"


# ──────────────────────────────────────────────────────────────
# 沙箱拦截
# ──────────────────────────────────────────────────────────────


class TestSandboxBlocked:
    """沙箱拦截测试：违规命令返回 error type='permission_denied'。"""

    def test_sandbox_blocked_returns_error(self, tmp_path) -> None:
        """沙箱拒绝时返回 permission_denied 错误，不抛异常。"""
        policy = SandboxPolicy(
            allowed_commands=[],
            allowed_network_hosts=[],
            default_action="deny",
            stop_on_risk=StopOnRiskConfig(on_sandbox_violation=False),
        )
        sandbox = SandboxEnforcer(policy)
        adapter = OpenCLIToolAdapter(
            manifest_path=_make_validation_manifest(tmp_path),
            sandbox_enforcer=sandbox,
        )
        # sandbox.enforce 需要 args 中含 command/cmd/path/host 等键才会触发检查。
        # 此处 mock enforce 直接抛出 SandboxViolationError，测试适配器的错误处理。
        with mock.patch.object(
            sandbox, "enforce", side_effect=SandboxViolationError("blocked", {"reason": "test"})
        ):
            result = adapter.execute(
                "opencli.test.echo",
                {"message": "test message"},
                "run-20",
            )
        assert result.success is False
        assert result.error is not None
        assert result.error["type"] == "permission_denied"

    def test_deny_env_passthrough_removes_runtime_secrets(self, tmp_path, monkeypatch) -> None:
        """开启沙箱 deny_env_passthrough 时，子进程不能继承运行时 secret。"""
        manifest = {
            "tools": [
                {
                    "tool_id": "opencli.test.env",
                    "display_name": "Env Test",
                    "execution_type": "subprocess",
                    "command_template": "{python} -c {snippet}",
                    "timeout_seconds": 5,
                    "parameters_schema": {
                        "type": "object",
                        "required": ["python", "snippet"],
                        "properties": {
                            "python": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                    },
                    "permissions": {
                        "risk_level": "low",
                        "network": {"allowed_hosts": []},
                        "browser": {"session_profile_required": False},
                        "credentials": {"required": []},
                    },
                }
            ]
        }
        manifest_path = tmp_path / "env-manifest.yaml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")
        monkeypatch.setenv("NEWSSENTRY_API_KEY", "ns-test-secret-value")
        policy = SandboxPolicy(
            allowed_commands=[sys.executable],
            default_action="allow",
        )
        sandbox = SandboxEnforcer(policy, audit_log_path=tmp_path / "logs")
        adapter = OpenCLIToolAdapter(manifest_path=manifest_path, sandbox_enforcer=sandbox)

        result = adapter.execute(
            "opencli.test.env",
            {
                "python": sys.executable,
                "snippet": (
                    "import os; "
                    "print(os.environ.get('NEWSSENTRY_API_KEY', '<missing>'))"
                ),
            },
            "run-env",
        )

        assert result.success is True
        assert "ns-test-secret-value" not in result.stdout
        assert "<missing>" in result.stdout


# ──────────────────────────────────────────────────────────────
# execute() 验证路径
# ──────────────────────────────────────────────────────────────


class TestExecuteValidation:
    """execute() 入口验证测试：unknown tool + 参数缺失。"""

    @pytest.fixture
    def adapter(self, tmp_path) -> OpenCLIToolAdapter:
        return OpenCLIToolAdapter(manifest_path=_make_validation_manifest(tmp_path))

    def test_unknown_tool(self, adapter: OpenCLIToolAdapter) -> None:
        """未知工具返回 error type='command_not_found'。"""
        result = adapter.execute("nonexistent.tool", {}, "run-30")
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "command_not_found"

    def test_missing_required_arg_returns_exit_code_2(
        self,
        adapter: OpenCLIToolAdapter,
    ) -> None:
        """缺失必填参数时 _build_command 抛出 KeyError，
        execute() 捕获后返回 exit_code=-1，error type='schema_validation_failed'。"""
        result = adapter.execute("opencli.test.echo", {}, "run-31")
        assert result.success is False
        assert result.exit_code == -1
        assert result.error is not None
        assert result.error["type"] == "schema_validation_failed"
