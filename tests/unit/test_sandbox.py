"""沙箱安全模块完整测试 — SandboxPolicy, SandboxEnforcer, SandboxViolationError。

覆盖 check_command、check_write_path、check_network_host、enforce、
_extract_host、_is_private_host 和异常类，以及 Phase 6 新增方法：
check_read_path、check_browser_session、check_stop_on_risk、
check_sensitive_data、audit_tool_call、write_security_log、
blocked_patterns、deny_by_default、from_yaml_dict。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from news_sentry.core.sandbox import (
    SandboxDecision,
    SandboxEnforcer,
    SandboxPolicy,
    SandboxViolationError,
    StopOnRiskError,
)

# =============================================================================
# SandboxViolationError
# =============================================================================


class TestSandboxViolationError:
    """SandboxViolationError 异常类测试。"""

    def test_violation_error_without_detail(self) -> None:
        """无 detail 参数时，detail 为空字典。"""
        err = SandboxViolationError("命令不在白名单中")
        assert err.message == "命令不在白名单中"
        assert err.detail == {}
        assert str(err) == "命令不在白名单中"

    def test_violation_error_with_detail(self) -> None:
        """detail 参数正确保存在异常对象中。"""
        detail = {"tool": "curl", "host": "evil.com"}
        err = SandboxViolationError("违规", detail=detail)
        assert err.detail == {"tool": "curl", "host": "evil.com"}
        assert err.message == "违规"

    def test_violation_error_message(self) -> None:
        """异常消息正确设置为传入的 message。"""
        err = SandboxViolationError("自定义错误信息")
        assert str(err) == "自定义错误信息"
        assert err.message == "自定义错误信息"


# =============================================================================
# SandboxPolicy
# =============================================================================


class TestSandboxPolicy:
    """SandboxPolicy 模型测试。"""

    def test_sandbox_policy_default_values(self) -> None:
        """默认构造策略具有正确的默认值。"""
        policy = SandboxPolicy()
        assert policy.allowed_commands == []
        assert policy.allowed_network_hosts == []
        assert policy.write_roots == []
        assert policy.max_execution_time_ms == 3600000  # Phase 6: 3600s * 1000
        assert policy.max_output_bytes == 1024 * 1024
        assert policy.default_action == "deny"  # Phase 6: deny by default

    def test_sandbox_policy_custom_values(self, tmp_path: Path) -> None:
        """自定义值正确保存在策略对象中。"""
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget"],
            allowed_network_hosts=["*.ansa.it"],
            write_roots=[tmp_path / "safe"],
            max_execution_time_ms=5000,
            max_output_bytes=4096,
            default_action="deny",
        )
        assert policy.allowed_commands == ["curl", "wget"]
        assert policy.allowed_network_hosts == ["*.ansa.it"]
        assert policy.write_roots == [tmp_path / "safe"]
        assert policy.max_execution_time_ms == 5000
        assert policy.max_output_bytes == 4096
        assert policy.default_action == "deny"

    def test_sandbox_policy_extra_fields_ignored(self) -> None:
        """model_config extra='ignore'：未知字段被忽略不报错。"""
        policy = SandboxPolicy(
            allowed_commands=["curl"],
            unknown_field="should-be-ignored",
            another_extra=42,
        )
        assert policy.allowed_commands == ["curl"]
        assert not hasattr(policy, "unknown_field")

    def test_sandbox_policy_max_execution_time_ms(self) -> None:
        """max_execution_time_ms 正确设置。"""
        policy = SandboxPolicy(max_execution_time_ms=15000)
        assert policy.max_execution_time_ms == 15000

    def test_sandbox_policy_max_output_bytes(self) -> None:
        """max_output_bytes 正确设置。"""
        policy = SandboxPolicy(max_output_bytes=2048)
        assert policy.max_output_bytes == 2048


# =============================================================================
# check_command
# =============================================================================


class TestCheckCommand:
    """check_command — 命令白名单检查。"""

    def test_check_command_multiple_entries_in_allowlist(self) -> None:
        """多个白名单条目均能正确匹配。"""
        policy = SandboxPolicy(allowed_commands=["curl", "wget", "git"])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_command("curl") is True
        assert enforcer.check_command("wget") is True
        assert enforcer.check_command("git") is True
        assert enforcer.check_command("rm") is False

    def test_check_command_python_prefix_matching(self) -> None:
        """'python ' 带尾部空格，匹配 'python -c \"print(1)\"'。"""
        policy = SandboxPolicy(allowed_commands=["python "])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_command("python -c 'print(1)'") is True
        assert enforcer.check_command("python -m pytest") is True

    def test_check_command_entry_with_trailing_space(self) -> None:
        """白名单条目自身含尾部空格时，不再追加空格避免双空格。"""
        policy = SandboxPolicy(allowed_commands=["opencli "])
        enforcer = SandboxEnforcer(policy)
        # "opencli fetch" 以 "opencli " 开头 → 通过
        assert enforcer.check_command("opencli fetch") is True
        # "opencli" 不等于 "opencli "，也不以 "opencli " 开头 → 拒绝
        assert enforcer.check_command("opencli") is False

    def test_check_command_rejects_partial_prefix(self) -> None:
        """'cur' 不匹配 'curl'（非完整命令名前缀）。"""
        policy = SandboxPolicy(allowed_commands=["curl"])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_command("cur") is False

    def test_check_command_empty_allowlist(self) -> None:
        """空白名单拒绝所有命令。"""
        policy = SandboxPolicy(allowed_commands=[])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_command("curl") is False
        assert enforcer.check_command("cat") is False
        assert enforcer.check_command("ls") is False

    def test_check_command_empty_command_string(self) -> None:
        """空字符串命令不在白名单中。"""
        policy = SandboxPolicy(allowed_commands=["curl", "cat"])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_command("") is False


# =============================================================================
# check_write_path
# =============================================================================


class TestCheckWritePath:
    """check_write_path — 写入路径限制检查。"""

    def test_check_write_path_relative_path_rejected(self) -> None:
        """相对路径直接拒绝。"""
        policy = SandboxPolicy(write_roots=[Path("/tmp")])  # noqa: S108
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_write_path(Path("relative/output.txt")) is False

    def test_check_write_path_resolves_symlinks(self, tmp_path: Path) -> None:
        """通过符号链接指向允许目录内的路径，解析后通过检查。"""
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        f = safe_dir / "real.txt"
        f.write_text("data")

        # 在别处创建符号链接指向 safe 目录
        link_dir = tmp_path / "link"
        link_dir.symlink_to(safe_dir)
        linked_file = link_dir / "real.txt"

        policy = SandboxPolicy(write_roots=[safe_dir])
        enforcer = SandboxEnforcer(policy)
        # 符号链接解析后解析到 safe_dir 内，应通过
        assert enforcer.check_write_path(linked_file) is True

    def test_check_write_path_multiple_roots(self, tmp_path: Path) -> None:
        """多个 write_roots 中任一匹配即通过。"""
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        root_a.mkdir()
        root_b.mkdir()

        f = root_b / "data.txt"
        f.write_text("ok")

        policy = SandboxPolicy(write_roots=[root_a, root_b])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_write_path(f) is True

    def test_check_write_path_nonexistent_path_still_checked(self, tmp_path: Path) -> None:
        """不存在的路径仍被检查：只要位于 write_root 内就通过。"""
        root = tmp_path / "root"
        root.mkdir()
        nonexistent = root / "nonexistent" / "file.txt"

        policy = SandboxPolicy(write_roots=[root])
        enforcer = SandboxEnforcer(policy)
        # Path.resolve() 不要求路径存在，包含性检查基于解析后的路径
        assert enforcer.check_write_path(nonexistent) is True


# =============================================================================
# check_network_host
# =============================================================================


class TestCheckNetworkHost:
    """check_network_host — 网络 host 检查与 SSRF 防护。"""

    @pytest.fixture
    def enforcer(self) -> SandboxEnforcer:
        """使用带通配符和白名单的策略。"""
        policy = SandboxPolicy(
            allowed_network_hosts=[
                "*.ansa.it",
                "www.repubblica.it",
                "feeds.bbci.co.uk",
                "8.8.8.8",
            ]
        )
        return SandboxEnforcer(policy)

    def test_check_network_host_wildcard_pattern(self, enforcer: SandboxEnforcer) -> None:
        """通配符 '*.ansa.it' 匹配子域名。"""
        assert enforcer.check_network_host("www.ansa.it") is True
        assert enforcer.check_network_host("static.ansa.it") is True
        assert enforcer.check_network_host("cdn.ansa.it") is True

    def test_check_network_host_exact_match(self, enforcer: SandboxEnforcer) -> None:
        """精确匹配 'www.repubblica.it'。"""
        assert enforcer.check_network_host("www.repubblica.it") is True
        # 子域名不匹配（非通配符）
        assert enforcer.check_network_host("cdn.repubblica.it") is False

    def test_check_network_host_default_allow_when_empty(self) -> None:
        """空 allowed_network_hosts + default_action=allow → 允许所有公开 host。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("anything.example.com") is True
        assert enforcer.check_network_host("www.google.com") is True

    def test_check_network_host_default_deny_when_empty(self) -> None:
        """空 allowed_network_hosts + default_action=deny → 拒绝所有。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="deny")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("anything.example.com") is False
        assert enforcer.check_network_host("www.google.com") is False

    # --- SSRF 防护：回环地址 ---

    def test_check_network_host_ssrf_blocks_loopback(self) -> None:
        """SSRF 防护：127.0.0.1 被拒绝。"""
        policy = SandboxPolicy(
            allowed_network_hosts=["127.0.0.1", "*.example.com"],
        )
        enforcer = SandboxEnforcer(policy)
        # 即使 127.0.0.1 在白名单中，SSRF 防护也拒绝它
        assert enforcer.check_network_host("127.0.0.1") is False

    def test_check_network_host_ssrf_blocks_ipv6_loopback(self) -> None:
        """SSRF 防护：IPv6 回环 ::1 被拒绝。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("::1") is False

    # --- SSRF 防护：私有 IP ---

    def test_check_network_host_ssrf_blocks_private(self) -> None:
        """SSRF 防护：私有 IP 段被拒绝。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("10.0.0.1") is False
        assert enforcer.check_network_host("192.168.1.1") is False
        assert enforcer.check_network_host("172.16.0.1") is False

    # --- SSRF 防护：常见绕过 hostname ---

    def test_check_network_host_ssrf_blocks_localhost(self) -> None:
        """SSRF 防护：localhost 被拒绝。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("localhost") is False

    def test_check_network_host_ssrf_blocks_metadata_google(self) -> None:
        """SSRF 防护：metadata.google.internal 被拒绝。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("metadata.google.internal") is False

    def test_check_network_host_ssrf_blocks_dot_local_suffix(self) -> None:
        """SSRF 防护：.local 后缀的 mDNS hostname 被拒绝。"""
        policy = SandboxPolicy(allowed_network_hosts=[], default_action="allow")
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("my-service.local") is False
        assert enforcer.check_network_host("docker.local") is False

    # --- 合法访问 ---

    def test_check_network_host_allows_public_ip(self) -> None:
        """公开 IP 在白名单中时允许访问。"""
        policy = SandboxPolicy(allowed_network_hosts=["8.8.8.8", "1.1.1.1"])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("8.8.8.8") is True
        assert enforcer.check_network_host("1.1.1.1") is True

    def test_check_network_host_allows_public_hostname(self) -> None:
        """公开 hostname 在白名单中时允许访问。"""
        policy = SandboxPolicy(allowed_network_hosts=["feeds.bbci.co.uk"])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("feeds.bbci.co.uk") is True


# =============================================================================
# _is_private_host
# =============================================================================


class TestIsPrivateHost:
    """_is_private_host — SSRF 私有/内部地址检测。"""

    def test_is_private_host_unspecified_address(self) -> None:
        """0.0.0.0 被识别为私有（unspecified）。"""
        assert SandboxEnforcer._is_private_host("0.0.0.0") is True  # noqa: S104

    def test_is_private_host_link_local(self) -> None:
        """169.254.x.x 链路本地地址被识别为私有。"""
        assert SandboxEnforcer._is_private_host("169.254.1.1") is True
        assert SandboxEnforcer._is_private_host("169.254.254.254") is True

    def test_is_private_host_invalid_ip_string(self) -> None:
        """非 IP 也非 SSRF hostname 的字符串不视为私有。"""
        assert SandboxEnforcer._is_private_host("not-an-ip-address") is False
        assert SandboxEnforcer._is_private_host("example.com") is False

    def test_is_private_host_ipv6_private(self) -> None:
        """IPv6 私有地址 fd00:: 被识别为私有。"""
        assert SandboxEnforcer._is_private_host("fd00::1") is True
        assert SandboxEnforcer._is_private_host("fd12:3456:7890::1") is True


# =============================================================================
# _extract_host
# =============================================================================


class TestExtractHost:
    """_extract_host — URL hostname 提取。"""

    def test_extract_host_valid_url(self) -> None:
        """有效 URL 正确提取 hostname。"""
        assert SandboxEnforcer._extract_host("https://www.ansa.it/news") == "www.ansa.it"
        assert SandboxEnforcer._extract_host("http://example.com") == "example.com"

    def test_extract_host_url_with_port(self) -> None:
        """带端口的 URL 正确提取 hostname（不含端口）。"""
        assert SandboxEnforcer._extract_host("https://example.com:8443/path") == "example.com"
        assert SandboxEnforcer._extract_host("http://localhost:8000") == "localhost"

    def test_extract_host_invalid_url_returns_none(self) -> None:
        """无法解析的 URL 返回 None。"""
        result = SandboxEnforcer._extract_host("not-a-valid-url-%%%")
        assert result is None

    def test_extract_host_missing_hostname(self) -> None:
        """缺少 hostname 的 URL 返回 None。"""
        # urlparse 可能返回空 hostname
        result = SandboxEnforcer._extract_host("file:///path/to/file")
        assert result is None

    def test_extract_host_non_string_raises_returns_none(self) -> None:
        """非字符串传入 _extract_host 时 urlparse 异常被捕获，返回 None。"""
        # 直接调用绕过 enforce 的 isinstance 检查
        result = SandboxEnforcer._extract_host(None)
        assert result is None


# =============================================================================
# enforce
# =============================================================================


class TestEnforce:
    """enforce — 综合安全校验。"""

    @pytest.fixture
    def tmp_root(self) -> Path:
        d = tempfile.mkdtemp(prefix="sandbox_enforce_test_")
        return Path(d)

    @pytest.fixture
    def enforcer(self, tmp_root: Path) -> SandboxEnforcer:
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget", "python "],
            allowed_network_hosts=["*.ansa.it"],
            write_roots=[tmp_root],
        )
        return SandboxEnforcer(policy)

    def test_enforce_allows_valid_tool_call(
        self, enforcer: SandboxEnforcer, tmp_root: Path
    ) -> None:
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

    def test_enforce_blocked_command_raises_violation_error(
        self, enforcer: SandboxEnforcer
    ) -> None:
        """非法命令抛出 SandboxViolationError。"""
        with pytest.raises(SandboxViolationError, match="命令 'rm' 不在白名单中"):
            enforcer.enforce("rm", {"command": "rm"})

    def test_enforce_blocked_path_raises_violation_error(
        self, enforcer: SandboxEnforcer, tmp_root: Path
    ) -> None:
        """非法写入路径抛出 SandboxViolationError。"""
        outside = tmp_root.parent / f"{tmp_root.name}_outside.txt"
        with pytest.raises(SandboxViolationError, match="不在允许的根目录内"):
            enforcer.enforce("curl", {"command": "curl", "output": str(outside)})

    def test_enforce_blocked_host_raises_violation_error(self, enforcer: SandboxEnforcer) -> None:
        """非法 host 抛出 SandboxViolationError。"""
        with pytest.raises(SandboxViolationError, match="网络 host 'evil.com' 不在允许列表中"):
            enforcer.enforce("curl", {"command": "curl", "url": "https://evil.com/hack"})

    def test_enforce_url_host_extraction_and_check(
        self, enforcer: SandboxEnforcer, tmp_root: Path
    ) -> None:
        """通过 url 键提取 host 并检查：合法 url host 通过。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")
        # www.ansa.it 匹配 *.ansa.it
        enforcer.enforce(
            "curl",
            {"command": "curl", "url": "https://www.ansa.it/news", "output": str(f)},
        )

    def test_enforce_missing_args_passes(self, enforcer: SandboxEnforcer) -> None:
        """空 args 不触发任何检查。"""
        enforcer.enforce("some_tool", {})

    def test_enforce_empty_command_passes(self, enforcer: SandboxEnforcer) -> None:
        """空字符串命令跳过命令检查。"""
        enforcer.enforce("some_tool", {"command": ""})

    def test_enforce_cmd_key_as_command(self, enforcer: SandboxEnforcer) -> None:
        """通过 'cmd' 键指定命令（与 'command' 同义）。"""
        # 'cmd' 不在白名单 → 抛出异常
        with pytest.raises(SandboxViolationError):
            enforcer.enforce("bad_tool", {"cmd": "rm -rf /"})

    def test_enforce_path_aliases(self, enforcer: SandboxEnforcer, tmp_root: Path) -> None:
        """通过 output_path / file / write_path 等别名指定路径均被检查。"""
        f = tmp_root / "data.txt"
        f.write_text("ok")

        for key in ("path", "output_path", "output", "file", "write_path"):
            enforcer.enforce("curl", {"command": "curl", key: str(f)})

    def test_enforce_host_key_direct(self, enforcer: SandboxEnforcer) -> None:
        """通过 'host' 键直接指定 host 被检查。"""
        with pytest.raises(SandboxViolationError):
            enforcer.enforce("curl", {"command": "curl", "host": "evil.com"})

    def test_enforce_host_key_legal(self, enforcer: SandboxEnforcer) -> None:
        """通过 'host' 键指定合法 host 通过检查。"""
        enforcer.enforce("curl", {"command": "curl", "host": "www.ansa.it"})


# =============================================================================
# check_read_path（Phase 6 新增）
# =============================================================================


class TestCheckReadPath:
    """check_read_path — 读取路径限制检查。"""

    def test_read_path_inside_roots_returns_true(self, tmp_path: Path) -> None:
        """路径在 read_roots 内返回 True。"""
        root = tmp_path / "readable"
        root.mkdir()
        f = root / "data.txt"
        f.write_text("hello")
        policy = SandboxPolicy(read_roots=[root])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_read_path(f) is True

    def test_read_path_outside_roots_returns_false(self, tmp_path: Path) -> None:
        """路径在 read_roots 外返回 False。"""
        root = tmp_path / "readable"
        root.mkdir()
        outside = tmp_path / "other" / "secret.txt"
        outside.parent.mkdir()
        outside.write_text("secret")
        policy = SandboxPolicy(read_roots=[root])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_read_path(outside) is False

    def test_read_path_relative_returns_false(self) -> None:
        """相对路径返回 False。"""
        policy = SandboxPolicy(read_roots=[Path("/tmp")])  # noqa: S108
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_read_path(Path("relative/data.txt")) is False

    def test_read_path_empty_roots_allows_all(self, tmp_path: Path) -> None:
        """空 read_roots 允许所有路径。"""
        f = tmp_path / "anything.txt"
        f.write_text("ok")
        policy = SandboxPolicy(read_roots=[])
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_read_path(f) is True


# =============================================================================
# check_browser_session（Phase 6 新增）
# =============================================================================


class TestCheckBrowserSession:
    """check_browser_session — 浏览器 session profile 校验。"""

    def _make_profile_yaml(
        self,
        profiles_dir: Path,
        profile_id: str,
        auth_owner: str = "human-approved",
    ) -> None:
        """辅助：创建 profile YAML 文件。"""
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_file = profiles_dir / f"{profile_id}.yaml"
        profile_file.write_text(f"auth_owner: {auth_owner}\n")

    def test_browser_session_allow_browser_false_raises(self) -> None:
        """browser.allow_browser=False 时抛出 SandboxViolationError。"""
        policy = SandboxPolicy()
        policy.browser.allow_browser = False
        enforcer = SandboxEnforcer(policy)
        with pytest.raises(SandboxViolationError, match="浏览器功能未启用"):
            enforcer.check_browser_session("chrome", "browser_tool")

    def test_browser_session_allow_session_profiles_false_raises(self) -> None:
        """profile.allow_session_profiles=False 时抛出 SandboxViolationError。"""
        policy = SandboxPolicy()
        policy.browser.allow_browser = True
        policy.browser.allowed_profiles = ["chrome"]
        policy.profile.allow_session_profiles = False
        enforcer = SandboxEnforcer(policy)
        with pytest.raises(SandboxViolationError, match="SessionProfile 未启用"):
            enforcer.check_browser_session("chrome", "browser_tool")

    def test_browser_session_profile_not_in_allowed_list_raises(self) -> None:
        """profile_id 不在 allowed_profiles 中时抛出 SandboxViolationError。"""
        policy = SandboxPolicy()
        policy.browser.allow_browser = True
        policy.browser.allowed_profiles = ["firefox"]
        policy.profile.allow_session_profiles = True
        enforcer = SandboxEnforcer(policy)
        with pytest.raises(SandboxViolationError, match="不在 allowed_profiles 白名单中"):
            enforcer.check_browser_session("chrome", "browser_tool")

    def test_browser_session_all_conditions_met_passes(self, tmp_path: Path) -> None:
        """所有条件满足时不抛异常。"""
        profiles_dir = tmp_path / "profiles"
        self._make_profile_yaml(profiles_dir, "chrome")
        policy = SandboxPolicy()
        policy.browser.allow_browser = True
        policy.browser.allowed_profiles = ["chrome"]
        policy.profile.allow_session_profiles = True
        policy.profile.profiles_dir = str(profiles_dir)
        enforcer = SandboxEnforcer(policy)
        # 不应抛出异常
        enforcer.check_browser_session("chrome", "browser_tool")

    def test_browser_session_auth_owner_not_approved_raises(self, tmp_path: Path) -> None:
        """auth_owner 不是 human-approved 时抛出 SandboxViolationError。"""
        profiles_dir = tmp_path / "profiles"
        self._make_profile_yaml(profiles_dir, "chrome", auth_owner="unknown")
        policy = SandboxPolicy()
        policy.browser.allow_browser = True
        policy.browser.allowed_profiles = ["chrome"]
        policy.profile.allow_session_profiles = True
        policy.profile.profiles_dir = str(profiles_dir)
        enforcer = SandboxEnforcer(policy)
        with pytest.raises(SandboxViolationError, match="auth_owner 不是 'human-approved'"):
            enforcer.check_browser_session("chrome", "browser_tool")


# =============================================================================
# check_stop_on_risk（Phase 6 新增）
# =============================================================================


class TestStopOnRisk:
    """check_stop_on_risk — stop-on-risk 信号处理。"""

    def test_stop_on_risk_enabled_with_stop_raises(self, tmp_path: Path) -> None:
        """信号启用且 on_deny="stop" 时抛出 StopOnRiskError。"""
        policy = SandboxPolicy()
        policy.stop_on_risk.on_captcha = True
        policy.stop_on_risk.on_deny = "stop"
        enforcer = SandboxEnforcer(policy, audit_log_path=tmp_path / "logs")
        with pytest.raises(StopOnRiskError, match="stop-on-risk 触发"):
            enforcer.check_stop_on_risk("captcha", "scraper", "run-001")

    def test_stop_on_risk_signal_not_enabled_returns_silently(self, tmp_path: Path) -> None:
        """信号未启用时静默返回。"""
        policy = SandboxPolicy()
        policy.stop_on_risk.on_captcha = False
        policy.stop_on_risk.on_deny = "stop"
        enforcer = SandboxEnforcer(policy, audit_log_path=tmp_path / "logs")
        # 不应抛出异常
        enforcer.check_stop_on_risk("captcha", "scraper", "run-001")

    def test_stop_on_risk_log_and_continue_does_not_raise(self, tmp_path: Path) -> None:
        """on_deny="log_and_continue" 时不抛出异常。"""
        policy = SandboxPolicy()
        policy.stop_on_risk.on_blocked = True
        policy.stop_on_risk.on_deny = "log_and_continue"
        enforcer = SandboxEnforcer(policy, audit_log_path=tmp_path / "logs")
        # 不应抛出异常
        enforcer.check_stop_on_risk("blocked", "scraper", "run-001")


# =============================================================================
# check_sensitive_data（Phase 6 新增）
# =============================================================================


class TestSensitiveData:
    """check_sensitive_data — 敏感数据扫描。"""

    def test_sensitive_data_bearer_token_raises(self) -> None:
        """内容包含 bearer token 模式时抛出 SandboxViolationError。"""
        with pytest.raises(SandboxViolationError, match="检测到敏感数据 'bearer_token'"):
            SandboxEnforcer.check_sensitive_data(
                "Authorization: bearer abcdefghijklmnopqrst1234567890",
                context="http_response",
            )

    def test_sensitive_data_set_cookie_raises(self) -> None:
        """内容包含 Set-Cookie 头时抛出 SandboxViolationError（大小写不敏感）。"""
        with pytest.raises(SandboxViolationError, match="检测到敏感数据 'set_cookie_header'"):
            SandboxEnforcer.check_sensitive_data(
                "HTTP/1.1 200 OK\nset-cookie: session=abc123",
                context="http_response",
            )

    def test_sensitive_data_clean_content_passes(self) -> None:
        """干净内容不抛异常。"""
        # 不应抛出异常
        SandboxEnforcer.check_sensitive_data(
            "Normal response body with some text.",
            context="http_response",
        )

    def test_sensitive_data_empty_content_passes(self) -> None:
        """空内容不抛异常。"""
        # 不应抛出异常
        SandboxEnforcer.check_sensitive_data("", context="http_response")
        SandboxEnforcer.check_sensitive_data("")


# =============================================================================
# audit_tool_call（Phase 6 新增）
# =============================================================================


class TestAuditLog:
    """audit_tool_call — 工具调用审计日志。"""

    def test_audit_writes_jsonl_line(self, tmp_path: Path) -> None:
        """audit_log_enabled=True 时写入一条 JSONL 记录。"""
        logs_dir = tmp_path / "logs"
        policy = SandboxPolicy(audit_log_enabled=True)
        enforcer = SandboxEnforcer(policy, audit_log_path=logs_dir)
        decision = SandboxDecision(verdict="allow", check_dimension="command")

        enforcer.audit_tool_call(
            "curl",
            decision,
            run_id="run-001",
            args_summary={"url": "https://example.com"},
            result_exit_code=0,
            duration_ms=150,
        )

        log_file = logs_dir / "tool-audit-run-001.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["run_id"] == "run-001"
        assert record["tool_id"] == "curl"
        assert record["decision"] == "allow"
        assert record["check_dimension"] == "command"
        assert record["result_exit_code"] == 0
        assert record["duration_ms"] == 150
        assert record["args_summary"]["url"] == "https://example.com"

    def test_audit_skips_when_disabled(self, tmp_path: Path) -> None:
        """audit_log_enabled=False 时不写文件。"""
        logs_dir = tmp_path / "logs"
        policy = SandboxPolicy(audit_log_enabled=False)
        enforcer = SandboxEnforcer(policy, audit_log_path=logs_dir)
        decision = SandboxDecision(verdict="allow", check_dimension="command")

        enforcer.audit_tool_call("curl", decision, run_id="run-001")

        log_file = logs_dir / "tool-audit-run-001.jsonl"
        assert not log_file.exists()

    def test_audit_sanitizes_long_args_values(self, tmp_path: Path) -> None:
        """args_summary 中超过 80 字符的值被截断为 [len:N]。"""
        logs_dir = tmp_path / "logs"
        policy = SandboxPolicy(audit_log_enabled=True)
        enforcer = SandboxEnforcer(policy, audit_log_path=logs_dir)
        decision = SandboxDecision(verdict="allow", check_dimension="command")

        long_value = "a" * 120
        enforcer.audit_tool_call(
            "curl",
            decision,
            run_id="run-001",
            args_summary={"data": long_value, "short": "ok"},
        )

        log_file = logs_dir / "tool-audit-run-001.jsonl"
        record = json.loads(log_file.read_text().strip())
        assert record["args_summary"]["data"] == "[len:120]"
        assert record["args_summary"]["short"] == "ok"


# =============================================================================
# write_security_log（Phase 6 新增）
# =============================================================================


class TestSecurityLog:
    """write_security_log — 安全日志写入。"""

    def test_write_security_log_creates_file_with_entry(self, tmp_path: Path) -> None:
        """创建 memory/security-log.yaml 并写入一条条目。"""
        logs_dir = tmp_path / "logs"
        policy = SandboxPolicy()
        enforcer = SandboxEnforcer(policy, audit_log_path=logs_dir)

        enforcer.write_security_log("sandbox_violation", "测试违规", "run-001")

        log_file = tmp_path / "memory" / "security-log.yaml"
        assert log_file.exists()
        entries = yaml.safe_load(log_file.read_text())
        assert isinstance(entries, list)
        assert len(entries) == 1
        assert entries[0]["violation_type"] == "sandbox_violation"
        assert entries[0]["run_id"] == "run-001"
        assert entries[0]["detail"] == "测试违规"

    def test_write_security_log_appends_to_existing(self, tmp_path: Path) -> None:
        """追加到已有条目后，不覆盖已有数据。"""
        logs_dir = tmp_path / "logs"
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        log_file = memory_dir / "security-log.yaml"
        existing = [
            {"violation_type": "blocked", "run_id": "run-000", "detail": "旧的条目"},
        ]
        log_file.write_text(yaml.safe_dump(existing, allow_unicode=True))

        policy = SandboxPolicy()
        enforcer = SandboxEnforcer(policy, audit_log_path=logs_dir)

        enforcer.write_security_log("captcha", "新的条目", "run-001")

        entries = yaml.safe_load(log_file.read_text())
        assert len(entries) == 2
        assert entries[0]["violation_type"] == "blocked"
        assert entries[1]["violation_type"] == "captcha"


# =============================================================================
# blocked_patterns in check_command（Phase 6 新增）
# =============================================================================


class TestBlockedPatterns:
    """check_command — blocked_patterns 正则黑名单。"""

    def test_command_matching_blocked_pattern_returns_false(self) -> None:
        """匹配 blocked_pattern 的命令返回 False。"""
        policy = SandboxPolicy(
            allowed_commands=["curl"],
        )
        policy.command.blocked_patterns = [r"-o\s+/tmp"]
        enforcer = SandboxEnforcer(policy)
        # curl 在白名单，但 blocked_pattern 匹配 → 拒绝
        assert enforcer.check_command("curl -o /tmp/evil http://example.com") is False

    def test_command_not_matching_blocked_pattern_returns_true(self) -> None:
        """不匹配 blocked_pattern 的命令返回 True。"""
        policy = SandboxPolicy(
            allowed_commands=["curl"],
        )
        policy.command.blocked_patterns = [r"-o\s+/tmp"]
        enforcer = SandboxEnforcer(policy)
        # curl 在白名单，且不匹配 blocked_pattern → 通过
        assert enforcer.check_command("curl -o output.txt http://example.com") is True


# =============================================================================
# deny_by_default in check_network_host（Phase 6 新增）
# =============================================================================


class TestDenyByDefault:
    """check_network_host — deny_by_default 行为。"""

    def test_empty_hosts_deny_by_default_true_returns_false(self) -> None:
        """空 allowed_hosts + deny_by_default=True 返回 False。"""
        policy = SandboxPolicy()
        policy.network.allowed_hosts = []
        policy.network.deny_by_default = True
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("example.com") is False

    def test_empty_hosts_deny_by_default_false_returns_true(self) -> None:
        """空 allowed_hosts + deny_by_default=False 返回 True。"""
        policy = SandboxPolicy()
        policy.network.allowed_hosts = []
        policy.network.deny_by_default = False
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("example.com") is True

    def test_ssrf_hosts_always_blocked(self) -> None:
        """SSRF host 在任何策略下都被拒绝。"""
        policy = SandboxPolicy()
        policy.network.allowed_hosts = ["127.0.0.1", "localhost", "metadata.google.internal"]
        policy.network.deny_by_default = False
        enforcer = SandboxEnforcer(policy)
        assert enforcer.check_network_host("127.0.0.1") is False
        assert enforcer.check_network_host("localhost") is False
        assert enforcer.check_network_host("metadata.google.internal") is False


# =============================================================================
# from_yaml_dict（Phase 6 新增）
# =============================================================================


class TestFromYamlDict:
    """SandboxPolicy.from_yaml_dict — 从 YAML 嵌套结构构造策略。"""

    def test_from_yaml_dict_loads_default_compatible_dict(self) -> None:
        """加载 default.yaml 兼容的字典。"""
        data = {
            "profile_id": "default",
            "default_action": "deny",
        }
        policy = SandboxPolicy.from_yaml_dict(data)
        assert policy.policy_id == "default"
        assert policy.default_action == "deny"
        assert policy.command.allowed_executables == []
        assert policy.network.allowed_hosts == []
        assert policy.network.deny_by_default is True
        assert policy.write_roots == []
        assert policy.read_roots == []
        assert policy.audit_log_enabled is True

    def test_from_yaml_dict_maps_profile_id_to_policy_id(self) -> None:
        """profile_id 映射到 policy_id。"""
        data = {"profile_id": "ansa-scraper"}
        policy = SandboxPolicy.from_yaml_dict(data)
        assert policy.policy_id == "ansa-scraper"

    def test_from_yaml_dict_maps_command_policy_allowed_commands(self) -> None:
        """command_policy.allowed_commands 映射到 command.allowed_executables。"""
        data = {
            "command_policy": {
                "allowed_commands": ["curl", "wget"],
                "blocked_patterns": [r"rm\s+-rf"],
                "deny_shell": False,
            },
        }
        policy = SandboxPolicy.from_yaml_dict(data)
        assert policy.command.allowed_executables == ["curl", "wget"]
        assert policy.command.blocked_patterns == [r"rm\s+-rf"]
        assert policy.command.deny_shell is False

    def test_from_yaml_dict_maps_network_policy(self) -> None:
        """network_policy 映射到 network。"""
        data = {
            "default_action": "deny",
            "network_policy": {
                "allowed_hosts": ["*.ansa.it"],
                "blocked_hosts": ["evil.com"],
            },
        }
        policy = SandboxPolicy.from_yaml_dict(data)
        assert policy.network.allowed_hosts == ["*.ansa.it"]
        assert policy.network.blocked_hosts == ["evil.com"]
        assert policy.network.deny_by_default is True

    def test_from_yaml_dict_maps_filesystem_policy_write_roots_as_path_objects(self) -> None:
        """filesystem_policy.write_roots 映射为 Path 对象列表。"""
        data = {
            "filesystem_policy": {
                "write_roots": ["/tmp/safe", "/var/data"],  # noqa: S108
            },
        }
        policy = SandboxPolicy.from_yaml_dict(data)
        expected = [Path("/tmp/safe"), Path("/var/data")]  # noqa: S108
        assert policy.write_roots == expected

    def test_from_yaml_dict_maps_filesystem_policy_read_roots_as_path_objects(self) -> None:
        """filesystem_policy.read_roots 映射为 Path 对象列表。"""
        data = {
            "filesystem_policy": {
                "read_roots": ["/etc/news_sentry", "/usr/share/data"],
            },
        }
        policy = SandboxPolicy.from_yaml_dict(data)
        assert policy.read_roots == [Path("/etc/news_sentry"), Path("/usr/share/data")]

    def test_from_yaml_dict_default_action_deny_sets_deny_by_default_true(self) -> None:
        """default_action="deny" 设置 network.deny_by_default=True。"""
        policy = SandboxPolicy.from_yaml_dict({"default_action": "deny"})
        assert policy.network.deny_by_default is True

    def test_from_yaml_dict_default_action_allow_sets_deny_by_default_false(self) -> None:
        """default_action="allow" 设置 network.deny_by_default=False。"""
        policy = SandboxPolicy.from_yaml_dict({"default_action": "allow"})
        assert policy.network.deny_by_default is False
