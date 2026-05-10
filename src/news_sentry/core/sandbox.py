"""Implements:
- docs/spec/phase-3-kernel-mvp.md §3.9
- docs/spec/phase-6-sandbox-hardening-social-kol.md §3.1

SandboxEnforcer — 工具调用前的沙箱安全校验。
Phase 3: 命令白名单、写入路径限制、网络 host 检查。
Phase 6: 完整 SandboxPolicy 模型与浏览器 session 治理。
"""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

# SSRF 防护：常见 SSRF 绕过 hostname 阻断列表
_SSRF_HOSTNAME_BLOCKLIST: frozenset[str] = frozenset({
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",  # noqa: S104
    "0",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
})


class SandboxViolationError(Exception):
    """沙箱违规异常。"""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class SandboxPolicy(BaseModel):
    """沙箱策略配置 — 运行时最小权限模型。

    对应 schemas/sandboxpolicy.schema.json 的运行时子集。
    """

    model_config = {"extra": "ignore"}

    allowed_commands: list[str] = Field(default_factory=list)
    allowed_network_hosts: list[str] = Field(default_factory=list)
    write_roots: list[Path] = Field(default_factory=list)
    max_execution_time_ms: int = 30000
    max_output_bytes: int = 1024 * 1024
    default_action: str = "allow"  # "allow" | "deny" — 空列表时的默认行为


class SandboxEnforcer:
    """工具执行安全校验器。

    在工具调用前检查命令、路径、网络 host 是否符合沙箱策略。
    任何违规立即拒绝，不执行工具。
    """

    def __init__(self, policy: SandboxPolicy) -> None:
        self._policy = policy

    # -- 单项检查 -----------------------------------------------------------

    def check_command(self, command: str) -> bool:
        """检查命令是否在白名单中。

        支持两种匹配模式：
        - 精确匹配：``"curl"`` 匹配 ``"curl"``
        - 前缀匹配：``"python "``（含尾部空格）匹配 ``"python -c '...'"``
        通用规则：命令等于条目，或命令以「条目 + 空格」开头。
        条目本身含尾部空格时不再追加空格，避免双空格。
        """
        for entry in self._policy.allowed_commands:
            if command == entry:
                return True
            prefix = entry if entry.endswith(" ") else entry + " "
            if command.startswith(prefix):
                return True
        return False

    def check_write_path(self, path: Path) -> bool:
        """检查写入路径是否在允许的根目录内。

        必须是绝对路径，拒绝相对路径（安全考量：避免路径解析歧义）。
        使用 ``Path.resolve()`` 解析符号链接后再做包含性检查。
        """
        if not path.is_absolute():
            return False
        resolved = path.resolve()
        for root in self._policy.write_roots:
            resolved_root = root.resolve()
            try:
                resolved.relative_to(resolved_root)
                return True
            except ValueError:
                continue
        return False

    def check_network_host(self, host: str) -> bool:
        """检查网络 host 是否在允许列表中。

        支持通配符：``*.ansa.it`` 匹配 ``www.ansa.it``、``static.ansa.it``。
        ``*`` 转换为正则 ``.*``，其余字符按字面量匹配。

        空 ``allowed_network_hosts`` 时，依据 ``default_action`` 决定：
        - ``default_action=\"allow\"`` → 允许所有（向后兼容）
        - ``default_action=\"deny\"`` → 拒绝所有（严格模式）

        始终拒绝私有/内部地址（SSRF 防护）：回环地址、私有 IP 段、
        链路本地地址和常见 SSRF 绕过 hostname。
        """
        if self._is_private_host(host):
            return False

        if not self._policy.allowed_network_hosts:
            return self._policy.default_action != "deny"
        for pattern in self._policy.allowed_network_hosts:
            regex = re.escape(pattern).replace(r"\*", ".*")
            if re.fullmatch(regex, host):
                return True
        return False

    # -- 综合校验 -----------------------------------------------------------

    def enforce(self, tool_name: str, args: dict[str, Any]) -> None:
        """综合安全校验。

        根据 ``tool_name`` 和 ``args`` 自动选择合适的检查方法。
        任何单项不通过立即抛出 ``SandboxViolationError``。
        """
        # 检查命令参数
        cmd = args.get("command") or args.get("cmd")
        if isinstance(cmd, str) and cmd:
            if not self.check_command(cmd):
                raise SandboxViolationError(
                    f"命令 '{cmd}' 不在白名单中",
                    {"tool": tool_name, "command": cmd},
                )

        # 检查写入路径参数
        for key in ("path", "output_path", "output", "file", "write_path"):
            path_str = args.get(key)
            if isinstance(path_str, str) and path_str:
                p = Path(path_str)
                if not self.check_write_path(p):
                    raise SandboxViolationError(
                        f"写入路径 '{path_str}' 不在允许的根目录内",
                        {"tool": tool_name, "path": path_str},
                    )

        # 检查网络 host 参数
        host = args.get("host")
        url = args.get("url")
        target_host: str | None = None
        if isinstance(host, str) and host:
            target_host = host
        elif isinstance(url, str) and url:
            target_host = self._extract_host(url)

        if target_host and not self.check_network_host(target_host):
            raise SandboxViolationError(
                f"网络 host '{target_host}' 不在允许列表中",
                {"tool": tool_name, "host": target_host},
            )

    # -- 辅助方法 -----------------------------------------------------------

    @staticmethod
    def _extract_host(url: str) -> str | None:
        """从 URL 中提取 hostname 部分。"""
        try:
            parsed = urlparse(url)
            return parsed.hostname
        except Exception:
            return None

    @staticmethod
    def _is_private_host(host: str) -> bool:
        """检测 host 是否为私有/内部地址（SSRF 防护）。

        拒绝以下类别：
        - 回环地址：127.0.0.0/8, ::1
        - 私有 IP：10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fd00::/8
        - 链路本地：169.254.0.0/16, fe80::/10
        - 通配符地址：0.0.0.0
        - 常见 SSRF 绕过 hostname：localhost, metadata.google.internal 等
        """
        # 检查裸 IP 地址
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
        except ValueError:
            pass  # 不是 IP 地址，检查 hostname

        # 检查常见 SSRF 绕过 hostname
        host_lower = host.lower().strip("[]")
        if host_lower in _SSRF_HOSTNAME_BLOCKLIST:
            return True

        # 检查是否以 .local 结尾（mDNS，常见 SSRF 绕过）
        if host_lower.endswith(".local"):
            return True

        return False
