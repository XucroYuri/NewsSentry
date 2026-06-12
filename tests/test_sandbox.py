"""测试 SandboxEnforcer — 命令白名单、路径限制、网络 host 检查。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

from news_sentry.core.sandbox import (
    SandboxEnforcer,
    SandboxPolicy,
    SandboxViolationError,
)


class TestSandboxViolationError:
    """自定义异常测试。"""

    def test_basic_message(self) -> None:
        err = SandboxViolationError("命令 'rm' 不在白名单中")
        assert str(err) == "命令 'rm' 不在白名单中"
        assert err.message == "命令 'rm' 不在白名单中"
        assert err.detail == {}

    def test_with_detail(self) -> None:
        err = SandboxViolationError("违规", {"tool": "curl", "host": "evil.com"})
        assert err.detail == {"tool": "curl", "host": "evil.com"}


class TestSandboxPolicy:
    """SandboxPolicy 模型测试。"""

    def test_defaults(self) -> None:
        policy = SandboxPolicy()
        assert policy.allowed_commands == []
        assert policy.allowed_network_hosts == []
        assert policy.write_roots == []
        assert policy.max_execution_time_ms == 3600000
        assert policy.max_output_bytes == 1024 * 1024
        assert policy.default_action == "deny"

    def test_custom_values(self, tmp_path: Path) -> None:
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget"],
            allowed_network_hosts=["*.ansa.it"],
            write_roots=[tmp_path / "safe"],
            max_execution_time_ms=5000,
            max_output_bytes=4096,
        )
        assert len(policy.allowed_commands) == 2
        assert policy.max_execution_time_ms == 5000
        assert policy.max_output_bytes == 4096


class TestCheckCommand:
    """命令白名单检查测试。"""

    @pytest.fixture
    def enforcer(self) -> SandboxEnforcer:
        policy = SandboxPolicy(allowed_commands=["curl", "wget", "python ", "opencli", "cat"])
        return SandboxEnforcer(policy)

    def test_exact_match(self, enforcer: SandboxEnforcer) -> None:
        """精确匹配：'curl' 匹配 'curl'。"""
        assert enforcer.check_command("curl") is True

    def test_exact_match_no_args(self, enforcer: SandboxEnforcer) -> None:
        """精确匹配：'cat' 匹配 'cat'。"""
        assert enforcer.check_command("cat") is True

    def test_prefix_with_args(self, enforcer: SandboxEnforcer) -> None:
        """'curl' 匹配 'curl -s https://example.com'（条目 + 空格前缀）。"""
        assert enforcer.check_command("curl -s https://example.com") is True

    def test_prefix_with_space_entry(self, enforcer: SandboxEnforcer) -> None:
        """'python ' 匹配 'python -c \"print(1)\"'（含空格条目前缀）。"""
        assert enforcer.check_command('python -c "print(1)"') is True

    def test_prefix_space_entry_excludes_similar(self, enforcer: SandboxEnforcer) -> None:
        """'python ' 不匹配 'python3'（无空格分隔）。"""
        assert enforcer.check_command("python3") is False

    def test_reject_unknown_command(self, enforcer: SandboxEnforcer) -> None:
        """不支持的命令返回 False。"""
        assert enforcer.check_command("rm -rf /") is False

    def test_reject_empty_command(self, enforcer: SandboxEnforcer) -> None:
        """空字符串不在白名单中。"""
        assert enforcer.check_command("") is False

    def test_reject_partial_match(self, enforcer: SandboxEnforcer) -> None:
        """'cur' 不匹配 'curl'（非完整命令名）。"""
        assert enforcer.check_command("cur") is False

    def test_python_module_cli_command(self, enforcer: SandboxEnforcer) -> None:
        """portable CLI 通过 python -m news_sentry.cli 调用。"""
        assert (
            enforcer.check_command("python -m news_sentry.cli run --target example --stage collect")
            is True
        )


class TestCheckWritePath:
    """写入路径检查测试。"""

    @pytest.fixture
    def tmp_root(self) -> Path:
        """创建真实临时目录作为 write_root。"""
        d = tempfile.mkdtemp(prefix="sandbox_test_")
        return Path(d)

    @pytest.fixture
    def enforcer(self, tmp_root: Path) -> SandboxEnforcer:
        policy = SandboxPolicy(write_roots=[tmp_root])
        return SandboxEnforcer(policy)

    def test_path_inside_root(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """文件在 write_root 内，通过。"""
        f = tmp_root / "output.txt"
        f.write_text("test")
        assert enforcer.check_write_path(f) is True

    def test_path_is_root_itself(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """路径等于 write_root 本身，通过。"""
        assert enforcer.check_write_path(tmp_root) is True

    def test_path_inside_subdirectory(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """路径在 write_root 子目录内，通过。"""
        sub = tmp_root / "subdir"
        sub.mkdir()
        f = sub / "data.json"
        f.write_text("{}")
        assert enforcer.check_write_path(f) is True

    def test_path_outside_root(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """路径不在 write_root 内，拒绝。"""
        outside = tmp_root.parent / f"{tmp_root.name}_outside.txt"
        assert enforcer.check_write_path(outside) is False

    def test_relative_path_rejected(self, enforcer: SandboxEnforcer) -> None:
        """相对路径直接拒绝（安全考量）。"""
        assert enforcer.check_write_path(Path("relative/output.txt")) is False

    def test_multiple_write_roots(self, tmp_root: Path) -> None:
        """多个 write_roots 中任一匹配即通过。"""
        root2 = Path(tempfile.mkdtemp(prefix="sandbox_test2_"))
        policy = SandboxPolicy(write_roots=[tmp_root, root2])
        enforcer = SandboxEnforcer(policy)
        f = root2 / "data.txt"
        f.write_text("ok")
        assert enforcer.check_write_path(f) is True

    def test_empty_write_roots_rejects_all(self, tmp_path: Path) -> None:
        """空 write_roots 拒绝所有路径。"""
        policy = SandboxPolicy(write_roots=[])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_write_path(tmp_path / "test.txt") is False


class TestCheckNetworkHost:
    """网络 host 检查测试。"""

    @pytest.fixture
    def enforcer(self) -> SandboxEnforcer:
        policy = SandboxPolicy(
            allowed_network_hosts=[
                "*.ansa.it",
                "www.repubblica.it",
                "feeds.bbci.co.uk",
            ]
        )
        return SandboxEnforcer(policy)

    def test_wildcard_single_label(self, enforcer: SandboxEnforcer) -> None:
        """'*.ansa.it' 匹配 'www.ansa.it'。"""
        assert enforcer.check_network_host("www.ansa.it") is True

    def test_wildcard_different_subdomain(self, enforcer: SandboxEnforcer) -> None:
        """'*.ansa.it' 匹配 'static.ansa.it'。"""
        assert enforcer.check_network_host("static.ansa.it") is True

    def test_exact_host_match(self, enforcer: SandboxEnforcer) -> None:
        """精确匹配 'www.repubblica.it'。"""
        assert enforcer.check_network_host("www.repubblica.it") is True

    def test_exact_host_subdomain_not_matched(self, enforcer: SandboxEnforcer) -> None:
        """'www.repubblica.it' 不匹配 'cdn.repubblica.it'（非通配符，需精确）。"""
        assert enforcer.check_network_host("cdn.repubblica.it") is False

    def test_reject_unknown_host(self, enforcer: SandboxEnforcer) -> None:
        """不在白名单中的 host 被拒绝。"""
        assert enforcer.check_network_host("evil.com") is False

    def test_ip_address_rejected(self, enforcer: SandboxEnforcer) -> None:
        """IP 地址不在白名单中，拒绝（防止 IP 绕过）。"""
        assert enforcer.check_network_host("192.168.1.1") is False

    def test_empty_allowed_list_default_allow(self) -> None:
        """空 allowed_network_hosts + default_action=allow → 允许公开 hostname。

        但私有/内部 IP 始终被 SSRF 防护拒绝，无论 default_action。
        """
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("anything.example.com") is True
        assert enforcer.check_network_host("192.168.1.1") is False  # 私有 IP 始终拒绝

    def test_empty_allowed_list_with_deny(self) -> None:
        """空 allowed_network_hosts + default_action=deny → 拒绝所有。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="deny")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("anything.example.com") is False
        assert enforcer.check_network_host("192.168.1.1") is False

    def test_multiple_patterns(self, enforcer: SandboxEnforcer) -> None:
        """多个 pattern 中任一匹配即通过。"""
        assert enforcer.check_network_host("feeds.bbci.co.uk") is True

    def test_cloud_vps_allows_configured_public_country_sources(self) -> None:
        """cloud-vps sandbox 必须覆盖公开运营目标声明的 RSS/API 主机。"""
        project_root = Path(__file__).resolve().parents[1]
        policy_data = yaml.safe_load((project_root / "config/sandbox/cloud-vps.yaml").read_text())
        enforcer = SandboxEnforcer(SandboxPolicy.from_yaml_dict(policy_data))
        source_files = [
            *sorted((project_root / "config/sources/germany").glob("*.yaml")),
            *sorted((project_root / "config/sources/germany/api").glob("*.yaml")),
            *sorted((project_root / "config/sources/france").glob("*.yaml")),
            *sorted((project_root / "config/sources/france/api").glob("*.yaml")),
            *sorted((project_root / "config/sources/china-watch-en").glob("*.yaml")),
            *sorted((project_root / "config/sources/india").glob("*.yaml")),
            *sorted((project_root / "config/sources/japan").glob("*.yaml")),
            *sorted((project_root / "config/sources/japan/api").glob("*.yaml")),
            *sorted((project_root / "config/sources/south-korea").glob("*.yaml")),
            *sorted((project_root / "config/sources/vietnam").glob("*.yaml")),
        ]

        denied: list[str] = []
        for source_file in source_files:
            if source_file.name.startswith("_"):
                continue
            data = yaml.safe_load(source_file.read_text())
            urls = [data.get("url"), data.get("endpoint", {}).get("url")]
            for url in urls:
                if not url:
                    continue
                host = urlparse(str(url)).hostname
                if host and not enforcer.check_network_host(host):
                    denied.append(f"{source_file.relative_to(project_root)} -> {host}")

        assert denied == []


class TestEnforce:
    """综合 enforce 校验测试。"""

    @pytest.fixture
    def tmp_root(self) -> Path:
        d = tempfile.mkdtemp(prefix="sandbox_enforce_")
        return Path(d)

    @pytest.fixture
    def enforcer(self, tmp_root: Path) -> SandboxEnforcer:
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget", "python "],
            allowed_network_hosts=["*.ansa.it"],
            write_roots=[tmp_root],
        )
        return SandboxEnforcer(policy)

    def test_all_checks_pass(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """合法命令 + 合法 host + 合法路径，不抛异常。"""
        f = tmp_root / "output.json"
        f.write_text("{}")
        enforcer.enforce(
            "curl",
            {
                "command": "curl",
                "url": "https://www.ansa.it/news",
                "output": str(f),
            },
        )

    def test_command_violation_raises(self, enforcer: SandboxEnforcer) -> None:
        """非法命令抛出 SandboxViolationError。"""
        with pytest.raises(SandboxViolationError, match="命令 'rm' 不在白名单中"):
            enforcer.enforce("rm", {"command": "rm"})

    def test_write_path_violation_raises(
        self,
        enforcer: SandboxEnforcer,
        tmp_root: Path,
    ) -> None:
        """非法写入路径抛出 SandboxViolationError。"""
        outside = tmp_root.parent / f"{tmp_root.name}_outside.txt"
        with pytest.raises(
            SandboxViolationError,
            match="不在允许的根目录内",
        ):
            enforcer.enforce("curl", {"command": "curl", "output": str(outside)})

    def test_network_host_violation_raises(self, enforcer: SandboxEnforcer) -> None:
        """非法网络 host 抛出 SandboxViolationError。"""
        with pytest.raises(SandboxViolationError, match="网络 host 'evil.com' 不在允许列表中"):
            enforcer.enforce("curl", {"command": "curl", "url": "https://evil.com/hack"})

    def test_host_from_host_key(self, enforcer: SandboxEnforcer) -> None:
        """通过 'host' 键直接指定 host。"""
        with pytest.raises(SandboxViolationError):
            enforcer.enforce("curl", {"command": "curl", "host": "evil.com"})

    def test_path_from_path_key(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """通过 'path' 键指定路径。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")
        # Should not raise
        enforcer.enforce("curl", {"command": "curl", "path": str(f)})

    def test_path_from_write_path_key(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """通过 'write_path' 键指定路径。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")
        enforcer.enforce("curl", {"command": "curl", "write_path": str(f)})

    def test_path_from_file_key(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """通过 'file' 键指定路径。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")
        enforcer.enforce("curl", {"command": "curl", "file": str(f)})

    def test_no_args_passes(self, enforcer: SandboxEnforcer) -> None:
        """空 args 不触发任何检查，正常通过。"""
        enforcer.enforce("some_tool", {})

    def test_empty_command_passes(self, enforcer: SandboxEnforcer) -> None:
        """空字符串命令不触发命令检查。"""
        enforcer.enforce("some_tool", {"command": ""})

    def test_exception_detail_contains_context(self, enforcer: SandboxEnforcer) -> None:
        """异常 detail 包含 tool_name 和违规参数。"""
        with pytest.raises(SandboxViolationError) as exc_info:
            enforcer.enforce("rm", {"command": "rm -rf /"})
        assert exc_info.value.detail == {"tool": "rm", "command": "rm -rf /"}

    def test_malformed_url_host_extraction(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """畸形 URL 不导致 enforce 崩溃：_extract_host 容错返回 None。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")
        # 畸形 url 导致 _extract_host 异常，host 为 None，跳过 host 检查
        enforcer.enforce(
            "curl",
            {"command": "curl", "url": "://bogus[MALFORMED]url", "output": str(f)},
        )


class TestExtractHost:
    """_extract_host 辅助方法测试。"""

    def test_malformed_url_returns_none(self):
        """畸形 URL 应返回 None，不抛异常。"""
        result = SandboxEnforcer._extract_host("not-a-valid-url-%%%")
        assert result is None


class TestEmptyPolicyDenyAll:
    """空策略（默认构造）全拒绝测试。"""

    @pytest.fixture
    def enforcer(self) -> SandboxEnforcer:
        return SandboxEnforcer(SandboxPolicy())

    def test_all_commands_rejected(self, enforcer: SandboxEnforcer) -> None:
        """空 allowed_commands 拒绝所有命令。"""
        assert enforcer.check_command("curl") is False
        assert enforcer.check_command("cat") is False
        assert enforcer.check_command("") is False

    def test_all_paths_rejected(self, enforcer: SandboxEnforcer, tmp_path: Path) -> None:
        """空 write_roots 拒绝所有路径。"""
        assert enforcer.check_write_path(tmp_path / "test.txt") is False

    def test_network_allowed_when_empty_and_default_allow(self, enforcer: SandboxEnforcer) -> None:
        """空 allowed_network_hosts + default_action=deny → 拒绝所有 host。"""
        assert enforcer.check_network_host("anything.com") is False
