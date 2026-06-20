"""Shared helpers for deployed surface audit and autofix planning."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

RECOMMENDED_ACTIONS: dict[str, str] = {
    "protected-surface-public": "收紧高风险服务端入口的公网暴露边界",
    "diagnostic-surface-public": "将未分类 API 入口纳入边界保护或显式白名单",
    "unknown-surface-public": "确认未知入口是否应公开，默认先收紧",
    "admin-ui-path-migration": "迁移后台 UI 到独立路径或子域后再接入 Access",
    "cloudflare-access-token-missing": "补齐 Cloudflare Access 读写权限 token",
    "cloudflare-state-unavailable": "补齐 Cloudflare 状态读取证据后再继续自动发布",
    "cloudflare-access-drift": "修复 Cloudflare Access 保护范围漂移",
    "response-header-drift": "补齐 Cloudflare 或应用层安全响应头",
    "cloudflare-rate-limit-drift": "补齐登录与写接口的 rate limit 规则",
    "cloudflare-waf-drift": "补齐高风险路径的 WAF 保护",
    "public-allowlist-regression": "修复公开白名单入口的可用性回归",
}

SEVERITY_BY_CLASS: dict[str, str] = {
    "protected-surface-public": "high",
    "diagnostic-surface-public": "high",
    "unknown-surface-public": "medium",
    "admin-ui-path-migration": "blocker",
    "cloudflare-access-token-missing": "blocker",
    "cloudflare-state-unavailable": "blocker",
    "cloudflare-access-drift": "high",
    "response-header-drift": "medium",
    "cloudflare-rate-limit-drift": "medium",
    "cloudflare-waf-drift": "medium",
    "public-allowlist-regression": "high",
}

CONTROL_LAYER_BY_CLASS: dict[str, str] = {
    "protected-surface-public": "repo",
    "diagnostic-surface-public": "repo",
    "unknown-surface-public": "repo",
    "admin-ui-path-migration": "architecture",
    "cloudflare-access-token-missing": "cloudflare",
    "cloudflare-state-unavailable": "cloudflare",
    "cloudflare-access-drift": "cloudflare",
    "response-header-drift": "cloudflare",
    "cloudflare-rate-limit-drift": "cloudflare",
    "cloudflare-waf-drift": "cloudflare",
    "public-allowlist-regression": "repo",
}


def load_policy(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("deployment surface policy must be a mapping")
    return data


def _match_surface(
    surface: str,
    *,
    exact: Iterable[str],
    prefixes: Iterable[str],
) -> bool:
    return surface in set(exact) or any(surface.startswith(prefix) for prefix in prefixes)


def classify_surface(surface: str, policy: dict[str, Any]) -> dict[str, Any]:
    rules = policy["surface_rules"]
    if _match_surface(
        surface,
        exact=rules["public_exact"],
        prefixes=rules["public_prefixes"],
    ):
        return {"surface": surface, "public_allowed": True, "surface_group": "public_allowlist"}
    if _match_surface(
        surface,
        exact=rules["protected_exact"],
        prefixes=rules["protected_prefixes"],
    ):
        return {"surface": surface, "public_allowed": False, "surface_group": "protected_surface"}
    if _match_surface(
        surface,
        exact=rules["architecture_exact"],
        prefixes=rules["architecture_prefixes"],
    ):
        return {
            "surface": surface,
            "public_allowed": False,
            "surface_group": "architecture_surface",
        }
    if surface.startswith("/api/"):
        return {"surface": surface, "public_allowed": False, "surface_group": "unknown_api_surface"}
    return {"surface": surface, "public_allowed": False, "surface_group": "unknown_surface"}


def _build_finding(
    *,
    surface: str,
    finding_class: str,
    public_allowed: bool,
    evidence: list[str],
    auto_fixable: bool | None = None,
    control_layer: str | None = None,
) -> dict[str, Any]:
    actual_control_layer = control_layer or CONTROL_LAYER_BY_CLASS[finding_class]
    actual_auto_fixable = (
        auto_fixable
        if auto_fixable is not None
        else finding_class in set()
    )
    return {
        "surface": surface,
        "finding_class": finding_class,
        "severity": SEVERITY_BY_CLASS[finding_class],
        "public_allowed": public_allowed,
        "auto_fixable": actual_auto_fixable,
        "control_layer": actual_control_layer,
        "recommended_action": RECOMMENDED_ACTIONS[finding_class],
        "evidence": evidence,
    }


def _is_cloudflare_access_redirect(probe: dict[str, Any]) -> bool:
    status_code = int(probe.get("status_code", 0))
    if status_code not in {301, 302, 303, 307, 308}:
        return False
    headers = probe.get("headers", {})
    location = ""
    for key, value in headers.items():
        if str(key).lower() == "location":
            location = str(value)
            break
    return (
        "cloudflareaccess.com/cdn-cgi/access/login" in location
        or "/cdn-cgi/access/login/" in location
    )


def build_surface_findings(
    probes: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    auto_fixable_classes = set(policy["auto_fixable_finding_classes"])
    findings: list[dict[str, Any]] = []
    for probe in probes:
        surface = str(probe["surface"])
        status_code = int(probe.get("status_code", 0))
        classified = classify_surface(surface, policy)
        if classified["public_allowed"]:
            if status_code >= 400:
                findings.append(
                    _build_finding(
                        surface=surface,
                        finding_class="public-allowlist-regression",
                        public_allowed=True,
                        evidence=[f"{surface} -> HTTP {status_code}"],
                        auto_fixable=False,
                    )
                )
            continue

        if status_code >= 400:
            continue
        if _is_cloudflare_access_redirect(probe):
            continue

        group = classified["surface_group"]
        if group == "protected_surface":
            finding_class = "protected-surface-public"
        elif group == "architecture_surface":
            finding_class = "admin-ui-path-migration"
        elif group == "unknown_api_surface":
            finding_class = "diagnostic-surface-public"
        else:
            finding_class = "unknown-surface-public"

        findings.append(
            _build_finding(
                surface=surface,
                finding_class=finding_class,
                public_allowed=False,
                evidence=[f"{surface} -> HTTP {status_code}"],
                auto_fixable=finding_class in auto_fixable_classes
                and CONTROL_LAYER_BY_CLASS[finding_class] != "architecture",
            )
        )
    return findings


def build_cloudflare_state_findings(
    state: dict[str, Any] | None,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    auto_fixable_classes = set(policy["auto_fixable_finding_classes"])
    expected = policy["cloudflare_expected"]
    if state is None:
        return [
            _build_finding(
                surface="cloudflare://state",
                finding_class="cloudflare-state-unavailable",
                public_allowed=False,
                evidence=["Cloudflare state JSON unavailable"],
                auto_fixable=False,
            )
        ]

    if not state.get("access_read_ok") or not state.get("access_write_ok"):
        return [
            _build_finding(
                surface="cloudflare://access",
                finding_class="cloudflare-access-token-missing",
                public_allowed=False,
                evidence=[
                    "Cloudflare Access state is unreadable or unwritable by current token"
                ],
                auto_fixable=False,
            )
        ]

    findings: list[dict[str, Any]] = []
    required_access = set(expected["required_access_protected_prefixes"])
    actual_access = set(state.get("protected_prefixes", []))
    missing_access = sorted(required_access - actual_access)
    if missing_access:
        findings.append(
            _build_finding(
                surface="cloudflare://access",
                finding_class="cloudflare-access-drift",
                public_allowed=False,
                evidence=[f"missing protected prefixes: {', '.join(missing_access)}"],
                auto_fixable="cloudflare-access-drift" in auto_fixable_classes,
            )
        )

    required_headers = {item.lower() for item in expected["required_response_headers"]}
    actual_headers = {str(item).lower() for item in state.get("response_headers", [])}
    missing_headers = sorted(required_headers - actual_headers)
    if missing_headers:
        findings.append(
            _build_finding(
                surface="cloudflare://response-headers",
                finding_class="response-header-drift",
                public_allowed=False,
                evidence=[f"missing headers: {', '.join(missing_headers)}"],
                auto_fixable="response-header-drift" in auto_fixable_classes,
            )
        )

    required_rate_limits = set(expected["required_rate_limit_paths"])
    actual_rate_limits = set(state.get("rate_limit_paths", []))
    missing_rate_limits = sorted(required_rate_limits - actual_rate_limits)
    if missing_rate_limits:
        findings.append(
            _build_finding(
                surface="cloudflare://rate-limits",
                finding_class="cloudflare-rate-limit-drift",
                public_allowed=False,
                evidence=[f"missing rate limit paths: {', '.join(missing_rate_limits)}"],
                auto_fixable="cloudflare-rate-limit-drift" in auto_fixable_classes,
            )
        )

    required_waf = set(expected["required_waf_path_prefixes"])
    actual_waf = set(state.get("waf_path_prefixes", []))
    missing_waf = sorted(required_waf - actual_waf)
    if missing_waf:
        findings.append(
            _build_finding(
                surface="cloudflare://waf",
                finding_class="cloudflare-waf-drift",
                public_allowed=False,
                evidence=[f"missing waf path prefixes: {', '.join(missing_waf)}"],
                auto_fixable="cloudflare-waf-drift" in auto_fixable_classes,
            )
        )
    return findings


def plan_autofix_publish(
    audit_report: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    blocker_classes = set(policy["blocker_finding_classes"])
    fix_queue: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    stop_reasons: list[str] = []

    for finding in audit_report.get("findings", []):
        finding_class = str(finding.get("finding_class", ""))
        if finding.get("auto_fixable") is True:
            fix_queue.append(finding)
        if finding_class in blocker_classes or finding.get("severity") == "blocker":
            blockers.append(finding)
            if finding_class and finding_class not in stop_reasons:
                stop_reasons.append(finding_class)

    should_publish = bool(fix_queue) and not stop_reasons
    return {
        "summary": {
            "finding_count": len(audit_report.get("findings", [])),
            "fixable_count": len(fix_queue),
            "blocker_count": len(blockers),
        },
        "fix_queue": fix_queue,
        "blockers": blockers,
        "should_publish": should_publish,
        "stop_reasons": stop_reasons,
    }
