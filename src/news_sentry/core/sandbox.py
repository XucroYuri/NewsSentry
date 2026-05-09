"""Implements: docs/spec/phase-3-kernel-mvp.md §3.9, docs/spec/phase-6-sandbox-hardening-social-kol.md §3.1

SandboxEnforcer — checks tool calls against SandboxPolicy before execution.
Phase 3: minimal allow/deny by command and write_roots.
Phase 6: full policy model with browser session governance.
"""
from __future__ import annotations
from typing import Any


class SandboxDecision:
    ALLOW = "allow"
    DENY = "deny"


class SandboxEnforcer:
    def __init__(self, policy: dict[str, Any]) -> None:
        raise NotImplementedError("Phase 3: SandboxEnforcer.__init__")

    def check_command(self, command: str, args: list[str]) -> str:
        """Returns SandboxDecision.ALLOW or SandboxDecision.DENY."""
        raise NotImplementedError("Phase 3: SandboxEnforcer.check_command")

    def check_write_path(self, path: str) -> str:
        """Check if path is within allowed write_roots."""
        raise NotImplementedError("Phase 3: SandboxEnforcer.check_write_path")

    def check_network_host(self, host: str) -> str:
        """Check if host is in allowed_hosts network policy."""
        raise NotImplementedError("Phase 3: SandboxEnforcer.check_network_host")
