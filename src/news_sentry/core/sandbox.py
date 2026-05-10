"""Implements:
- docs/spec/phase-3-kernel-mvp.md §3.9
- docs/spec/phase-6-sandbox-hardening-social-kol.md §3.1-3.2

SandboxEnforcer — 工具调用前的沙箱安全校验。
Phase 3: 命令白名单、写入路径限制、网络 host 检查。
Phase 6: 完整 SandboxPolicy 5 维权限模型、browser session 治理、
stop-on-risk、敏感数据扫描、audit log。
"""
from __future__ import annotations

import ipaddress
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

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

# 敏感数据检测正则（Phase 6）
_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    # (pattern, name) — pattern is case-insensitive
    (r"bearer\s+[\w._\-]{20,}", "bearer_token"),
    (r"(?i)set-cookie:", "set_cookie_header"),
    (r"(?i)passwd\s*=\s*\S+", "password_assignment"),
    (r"(?i)authorization:\s*bearer\s+\S+", "authorization_header"),
    (r"(?i)x-api-key:\s*\S+", "api_key_header"),
    (r"(?i)access_token\s*=\s*[\w._\-]{10,}", "access_token"),
    (r"(?i)session_key\s*=\s*[\w._\-]{10,}", "session_key"),
]


# ── 异常类 ────────────────────────────────────────────────────────────────

class SandboxViolationError(Exception):
    """沙箱违规异常。"""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class StopOnRiskError(SandboxViolationError):
    """stop-on-risk 触发异常 — 要求立即停止当前 run。"""

    def __init__(
        self, signal: str, run_id: str, detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"stop-on-risk 触发: signal={signal} run_id={run_id}",
            detail={"signal": signal, "run_id": run_id, **(detail or {})},
        )
        self.signal = signal
        self.run_id = run_id


# ── Phase 6 子策略模型 ────────────────────────────────────────────────────

class CommandPolicy(BaseModel):
    """命令执行策略。"""

    allowed_executables: list[str] = Field(default_factory=list)
    blocked_patterns: list[str] = Field(default_factory=list)
    deny_shell: bool = True
    deny_env_passthrough: bool = True


class NetworkPolicy(BaseModel):
    """网络访问策略。"""

    allowed_hosts: list[str] = Field(default_factory=list)
    blocked_hosts: list[str] = Field(default_factory=list)
    deny_by_default: bool = True


class FilesystemPolicy(BaseModel):
    """文件系统访问策略。"""

    read_roots: list[Path] = Field(default_factory=list)
    # write_roots 由顶层 SandboxPolicy.write_roots 管理（向后兼容）


class BrowserPolicy(BaseModel):
    """浏览器 session 策略。"""

    allow_browser: bool = False
    allowed_profiles: list[str] = Field(default_factory=list)
    require_auth_owner: bool = True
    deny_incognito: bool = True


class ProfilePolicy(BaseModel):
    """SessionProfile 治理策略。"""

    allow_session_profiles: bool = False
    profiles_dir: str | None = None
    max_profiles: int = 5


class BudgetPolicy(BaseModel):
    """运行时预算策略。"""

    max_provider_cost_usd: float = 1.0
    max_run_duration_seconds: int = 3600
    max_events_per_run: int = 500
    max_ai_calls_per_run: int = 200


class StopOnRiskConfig(BaseModel):
    """stop-on-risk 触发配置。"""

    on_captcha: bool = True
    on_blocked: bool = True
    on_auth_error: bool = True
    on_sandbox_violation: bool = True
    on_deny: Literal["stop", "log_and_continue"] = "stop"


# ── Audit 模型 ─────────────────────────────────────────────────────────────

class SandboxDecision(BaseModel):
    """沙箱检查决策。"""

    verdict: Literal["allow", "deny"]
    check_dimension: str  # "command" | "filesystem" | "network" | "browser" | "budget" | "profile"
    reason: str | None = None
    policy_ref: str = ""  # 触发的 policy 字段路径


class SandboxAuditRecord(BaseModel):
    """工具调用 audit log 记录。"""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    tool_id: str | None = None
    decision: Literal["allow", "deny"]
    check_dimension: str
    args_summary: dict[str, Any] = Field(default_factory=dict)
    result_exit_code: int | None = None
    duration_ms: int | None = None
    reason: str | None = None


# ── 主策略模型 ─────────────────────────────────────────────────────────────

class SandboxPolicy(BaseModel):
    """沙箱策略配置 — Phase 6 完整 5 维权限模型。

    对应 schemas/sandboxpolicy.schema.json。
    通过 SandboxPolicy.from_yaml_dict() 从 YAML 嵌套结构加载。
    """

    model_config = {"extra": "ignore"}

    policy_id: str = "default"
    default_action: str = "deny"  # "allow" | "deny"，用于 schema 兼容 + 默认行为

    # 顶层文件系统根（enforcer 直接访问）
    write_roots: list[Path] = Field(default_factory=list)
    read_roots: list[Path] = Field(default_factory=list)

    # 向后兼容：Phase 3 字段，Phase 6 中不再被 enforcer 使用
    max_output_bytes: int = 1024 * 1024

    # 5 维子策略
    command: CommandPolicy = Field(default_factory=CommandPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    filesystem: FilesystemPolicy = Field(default_factory=FilesystemPolicy)
    browser: BrowserPolicy = Field(default_factory=BrowserPolicy)
    profile: ProfilePolicy = Field(default_factory=ProfilePolicy)
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    stop_on_risk: StopOnRiskConfig = Field(default_factory=StopOnRiskConfig)

    audit_log_enabled: bool = True

    # ── 向后兼容属性（旧代码/测试可能使用平铺字段名） ──────────────────

    @property
    def allowed_commands(self) -> list[str]:
        """向后兼容：映射到 command.allowed_executables。"""
        return self.command.allowed_executables

    @property
    def allowed_network_hosts(self) -> list[str]:
        """向后兼容：映射到 network.allowed_hosts。"""
        return self.network.allowed_hosts

    @property
    def max_execution_time_ms(self) -> int:
        """向后兼容：映射到 budget.max_run_duration_seconds。"""
        return self.budget.max_run_duration_seconds * 1000

    # ── 验证器：平铺字段 → 嵌套子模型合并 ──────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _merge_flat_kwargs(cls, data: Any) -> Any:  # noqa: ANN401
        """将旧式平铺字段合并到嵌套子模型中（向后兼容）。"""
        if not isinstance(data, dict):
            return data

        # allowed_commands → command.allowed_executables
        if "allowed_commands" in data:
            cmd = data.setdefault("command", {})
            if isinstance(cmd, dict) and "allowed_executables" not in cmd:
                cmd["allowed_executables"] = data.pop("allowed_commands")

        # allowed_network_hosts → network.allowed_hosts
        if "allowed_network_hosts" in data:
            net = data.setdefault("network", {})
            if isinstance(net, dict) and "allowed_hosts" not in net:
                net["allowed_hosts"] = data.pop("allowed_network_hosts")

        # default_action → network.deny_by_default
        if "default_action" in data:
            net = data.setdefault("network", {})
            if isinstance(net, dict) and "deny_by_default" not in net:
                net["deny_by_default"] = data["default_action"] == "deny"

        # max_execution_time_ms → budget.max_run_duration_seconds
        if "max_execution_time_ms" in data:
            budget = data.setdefault("budget", {})
            if isinstance(budget, dict) and "max_run_duration_seconds" not in budget:
                budget["max_run_duration_seconds"] = data.pop("max_execution_time_ms") // 1000
            else:
                data.pop("max_execution_time_ms")

        return data

    # ── 工厂方法：从 YAML dict 加载 ──────────────────────────────────

    @classmethod
    def from_yaml_dict(cls, data: dict[str, Any]) -> SandboxPolicy:
        """从 YAML 嵌套结构构造 SandboxPolicy。

        映射规则（YAML 键 → Python 模型字段）：
        - profile_id → policy_id
        - command_policy → command（allowed_commands → allowed_executables）
        - network_policy → network
        - filesystem_policy → write_roots / read_roots
        - browser_policy → browser（session_profiles_allowed → allowed_profiles）
        - budget_policy → budget
        - default_action → default_action + network.deny_by_default
        - audit → audit_log_enabled

        返回 SandboxPolicy 实例。
        """
        policy_id = data.get("profile_id", "default")
        default_action = data.get("default_action", "deny")

        # ── command_policy ──
        cmd_raw = data.get("command_policy", {})
        if isinstance(cmd_raw, dict):
            command = CommandPolicy(
                allowed_executables=cmd_raw.get("allowed_commands", []),
                blocked_patterns=cmd_raw.get("blocked_patterns", []),
                deny_shell=cmd_raw.get("deny_shell", True),
                deny_env_passthrough=cmd_raw.get("deny_env_passthrough", True),
            )
        else:
            command = CommandPolicy()

        # ── network_policy ──
        net_raw = data.get("network_policy", {})
        if isinstance(net_raw, dict):
            network = NetworkPolicy(
                allowed_hosts=net_raw.get("allowed_hosts", []),
                blocked_hosts=net_raw.get("blocked_hosts", []),
                deny_by_default=(default_action == "deny"),
            )
        else:
            network = NetworkPolicy(deny_by_default=(default_action == "deny"))

        # ── filesystem_policy ──
        fs_raw = data.get("filesystem_policy", {})
        if isinstance(fs_raw, dict):
            write_roots = [Path(p) for p in fs_raw.get("write_roots", [])]
            read_roots = [Path(p) for p in fs_raw.get("read_roots", [])]
        else:
            write_roots = []
            read_roots = []

        # ── browser_policy ──
        br_raw = data.get("browser_policy", {})
        if isinstance(br_raw, dict):
            allowed_profiles = br_raw.get("session_profiles_allowed", [])
            browser = BrowserPolicy(
                allow_browser=len(allowed_profiles) > 0,
                allowed_profiles=allowed_profiles,
            )
        else:
            browser = BrowserPolicy()

        # ── budget_policy ──
        bud_raw = data.get("budget_policy", {})
        if isinstance(bud_raw, dict):
            budget = BudgetPolicy(
                max_provider_cost_usd=bud_raw.get("max_provider_cost_usd", 1.0),
                max_run_duration_seconds=bud_raw.get("max_run_duration_seconds", 3600),
                max_events_per_run=bud_raw.get("max_events_per_run", 500),
                max_ai_calls_per_run=bud_raw.get("max_ai_calls_per_run", 200),
            )
        else:
            budget = BudgetPolicy()

        # ── audit ──
        audit_raw = data.get("audit", {})
        if isinstance(audit_raw, dict):
            audit_log_enabled = audit_raw.get("log_all_tool_calls", True)
        else:
            audit_log_enabled = True

        # ── stop_on_risk — 从 YAML 尚不支持，使用默认值 ──
        stop_on_risk = StopOnRiskConfig()

        return cls(
            policy_id=policy_id,
            default_action=default_action,
            write_roots=write_roots,
            read_roots=read_roots,
            command=command,
            network=network,
            browser=browser,
            budget=budget,
            stop_on_risk=stop_on_risk,
            audit_log_enabled=audit_log_enabled,
        )


# ── SandboxEnforcer ────────────────────────────────────────────────────────

class SandboxEnforcer:
    """工具执行安全校验器（Phase 6 完整实现）。

    在工具调用前检查命令、路径、网络 host、browser session 是否符合沙箱策略。
    支持 stop-on-risk、敏感数据扫描和 audit log。
    任何违规立即拒绝，不执行工具。
    """

    def __init__(
        self, policy: SandboxPolicy,
        audit_log_path: Path | None = None,
    ) -> None:
        self._policy = policy
        self._audit_log_path = audit_log_path or Path("data/logs")

    @property
    def policy(self) -> SandboxPolicy:
        """获取当前策略（只读）。"""
        return self._policy

    # -- 命令检查 -----------------------------------------------------------

    def check_command(self, command: str) -> bool:
        """检查命令是否在白名单中，且不在黑名单正则中。

        Phase 3: 精确匹配 + 前缀匹配
        Phase 6: 增加 blocked_patterns 正则检查
        """
        executables = self._policy.command.allowed_executables

        # 白名单检查
        allowed = False
        for entry in executables:
            if command == entry:
                allowed = True
                break
            prefix = entry if entry.endswith(" ") else entry + " "
            if command.startswith(prefix):
                allowed = True
                break
        if not allowed:
            return False

        # blocked_patterns 黑名单检查
        for pattern in self._policy.command.blocked_patterns:
            try:
                if re.search(pattern, command):
                    return False
            except re.error:
                logger.warning("无效的 blocked_pattern 正则: %s", pattern)

        return True

    # -- 文件系统检查 -------------------------------------------------------

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

    def check_read_path(self, path: Path) -> bool:
        """检查读取路径是否在允许的根目录内（Phase 6 新增）。"""
        if not self._policy.read_roots:
            return True  # 未配置 read_roots 时允许所有
        if not path.is_absolute():
            return False
        resolved = path.resolve()
        for root in self._policy.read_roots:
            resolved_root = root.resolve()
            try:
                resolved.relative_to(resolved_root)
                return True
            except ValueError:
                continue
        return False

    # -- 网络检查 -----------------------------------------------------------

    def check_network_host(self, host: str) -> bool:
        """检查网络 host 是否在允许列表中。

        Phase 6 增强：
        - deny_by_default=True 时拦截未授权主机
        - 支持 wildcard：``*.ansa.it`` 匹配 ``www.ansa.it``
        - 始终拒绝私有/内部地址（SSRF 防护）
        - blocked_hosts 优先级高于 allowed_hosts
        """
        if self._is_private_host(host):
            return False

        # blocked_hosts 优先
        for blocked in self._policy.network.blocked_hosts:
            regex = re.escape(blocked).replace(r"\*", ".*")
            if re.fullmatch(regex, host):
                return False

        # 空白名单 + deny_by_default
        if not self._policy.network.allowed_hosts:
            return not self._policy.network.deny_by_default

        # 白名单匹配
        for pattern in self._policy.network.allowed_hosts:
            regex = re.escape(pattern).replace(r"\*", ".*")
            if re.fullmatch(regex, host):
                return True
        return False

    # -- 浏览器 session 检查（Phase 6 新增） ---------------------------------

    def check_browser_session(self, profile_id: str, tool_id: str) -> None:
        """验证 browser session profile 合法。

        检查顺序：
        1. browser.allow_browser 必须为 True
        2. profile.allow_session_profiles 必须为 True
        3. profile_id 在 browser.allowed_profiles 白名单中
        4. 若 require_auth_owner=True，profile 元数据须有 auth_owner=human-approved
        """
        if not self._policy.browser.allow_browser:
            raise SandboxViolationError(
                f"浏览器功能未启用（browser.allow_browser=False）: tool={tool_id}",
                {"tool": tool_id, "profile_id": profile_id, "check": "browser"},
            )

        if not self._policy.profile.allow_session_profiles:
            raise SandboxViolationError(
                f"SessionProfile 未启用（profile.allow_session_profiles=False）: tool={tool_id}",
                {"tool": tool_id, "profile_id": profile_id, "check": "profile"},
            )

        if profile_id not in self._policy.browser.allowed_profiles:
            raise SandboxViolationError(
                f"session_profile '{profile_id}' 不在 allowed_profiles 白名单中: tool={tool_id}",
                {"tool": tool_id, "profile_id": profile_id, "check": "browser"},
            )

        # 验证 auth_owner
        if self._policy.browser.require_auth_owner and self._policy.profile.profiles_dir:
            profiles_dir = Path(self._policy.profile.profiles_dir)
            profile_file = profiles_dir / f"{profile_id}.yaml"
            if profile_file.exists():
                with open(profile_file, encoding="utf-8") as f:
                    profile_data = yaml.safe_load(f) or {}
                auth_owner = profile_data.get("auth_owner", "")
                if auth_owner != "human-approved":
                    raise SandboxViolationError(
                        f"session_profile '{profile_id}' auth_owner 不是 'human-approved': "
                        f"当前值 '{auth_owner}'",
                        {"tool": tool_id, "profile_id": profile_id, "check": "auth_owner"},
                    )

    # -- stop-on-risk（Phase 6 新增） ----------------------------------------

    def check_stop_on_risk(self, signal: str, tool_id: str, run_id: str) -> None:
        """检查 stop-on-risk 信号，按配置决定是否停止运行。

        signal: "captcha" | "blocked" | "auth_error" | "sandbox_violation"
        """
        config = self._policy.stop_on_risk
        signal_map = {
            "captcha": config.on_captcha,
            "blocked": config.on_blocked,
            "auth_error": config.on_auth_error,
            "sandbox_violation": config.on_sandbox_violation,
        }

        enabled = signal_map.get(signal, False)
        if not enabled:
            return

        detail = f"stop-on-risk 触发: signal={signal} tool={tool_id} run_id={run_id}"
        self.write_security_log(signal, detail, run_id)

        if config.on_deny == "log_and_continue":
            logger.warning("stop-on-risk log_and_continue: %s", detail)
            return

        raise StopOnRiskError(signal, run_id, {"tool_id": tool_id})

    # -- 敏感数据扫描（Phase 6 新增） ----------------------------------------

    @staticmethod
    def check_sensitive_data(content: str, context: str = "") -> None:
        """扫描文本是否含敏感数据关键词（cookie/token/password/api_key 等）。

        匹配 → SandboxViolationError，不允许该内容写入任何文件。
        """
        if not content:
            return
        for pattern, name in _SENSITIVE_PATTERNS:
            if re.search(pattern, content):
                raise SandboxViolationError(
                    f"检测到敏感数据 '{name}': context={context}",
                    {"context": context, "matched_pattern": name},
                )

    # -- Audit log（Phase 6 新增） ------------------------------------------

    def audit_tool_call(
        self,
        tool_id: str,
        decision: SandboxDecision,
        result_exit_code: int | None = None,
        duration_ms: int | None = None,
        args_summary: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> None:
        """每次工具调用（allow 或 deny）写一条 audit log 记录。

        Args:
            tool_id: 工具标识
            decision: 沙箱检查决策
            result_exit_code: 工具退出码（allow 时）
            duration_ms: 执行耗时（allow 时）
            args_summary: 去敏感化的参数摘要
            run_id: 本次运行标识
        """
        if not self._policy.audit_log_enabled:
            return

        # 去敏化 args_summary：值超 80 字截断
        safe_args: dict[str, Any] = {}
        if args_summary:
            for k, v in args_summary.items():
                if isinstance(v, str) and len(v) > 80:
                    safe_args[k] = f"[len:{len(v)}]"
                else:
                    safe_args[k] = v

        record = SandboxAuditRecord(
            run_id=run_id,
            tool_id=tool_id,
            decision=decision.verdict,
            check_dimension=decision.check_dimension,
            args_summary=safe_args,
            result_exit_code=result_exit_code,
            duration_ms=duration_ms,
            reason=decision.reason,
        )

        # 确保目录存在
        self._audit_log_path.mkdir(parents=True, exist_ok=True)

        # 使用 run_id 构造文件名，fallback 到日期
        safe_run_id = run_id or datetime.now(UTC).strftime("%Y%m%d")
        log_file = self._audit_log_path / f"tool-audit-{safe_run_id}.jsonl"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    # -- 安全日志（Phase 6 新增） ------------------------------------------

    def write_security_log(
        self, violation_type: str, detail: str, run_id: str,
    ) -> None:
        """追加写入 memory/security-log.yaml，不覆盖历史。

        Args:
            violation_type: 违规类型（captcha/blocked/auth_error/sandbox_violation）
            detail: 详细描述
            run_id: 本次运行标识
        """
        log_dir = self._audit_log_path.parent / "memory"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "security-log.yaml"

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "violation_type": violation_type,
            "detail": detail,
        }

        # 追加模式：读取已有条目 → 追加 → 写回
        existing: list[dict[str, Any]] = []
        if log_file.exists():
            with open(log_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    existing = data

        existing.append(entry)

        with open(log_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, allow_unicode=True, default_flow_style=False)

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
