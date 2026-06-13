from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config/security/deployment-surface-policy.yaml"

sys.path.insert(0, str(TOOLS_DIR))

from deployment_surface_security import (  # noqa: E402
    build_cloudflare_state_findings,
    classify_surface,
    load_policy,
    plan_autofix_publish,
)


def test_classify_surface_distinguishes_public_protected_and_unknown_api() -> None:
    policy = load_policy(POLICY_PATH)

    public_surface = classify_surface("/public-app/assets/index-abc123.js", policy)
    protected_surface = classify_surface("/api/v1/auth/login", policy)
    unknown_surface = classify_surface("/api/v1/debug/runtime-dump", policy)

    assert public_surface["public_allowed"] is True
    assert public_surface["surface_group"] == "public_allowlist"

    assert protected_surface["public_allowed"] is False
    assert protected_surface["surface_group"] == "protected_surface"

    assert unknown_surface["public_allowed"] is False
    assert unknown_surface["surface_group"] == "unknown_api_surface"


def test_cloudflare_state_without_access_permissions_becomes_hard_blocker() -> None:
    policy = load_policy(POLICY_PATH)

    findings = build_cloudflare_state_findings(
        {
            "access_read_ok": False,
            "access_write_ok": False,
            "protected_prefixes": [],
            "response_headers": [],
            "rate_limit_paths": [],
            "waf_path_prefixes": [],
        },
        policy,
    )

    assert len(findings) == 1
    blocker = findings[0]
    assert blocker["surface"] == "cloudflare://access"
    assert blocker["severity"] == "blocker"
    assert blocker["auto_fixable"] is False
    assert blocker["finding_class"] == "cloudflare-access-token-missing"


def test_plan_autofix_publish_filters_out_architecture_and_permission_blockers() -> None:
    policy = load_policy(POLICY_PATH)
    audit_report = {
        "findings": [
            {
                "surface": "/api/v1/runtime/info",
                "finding_class": "protected-surface-public",
                "severity": "high",
                "public_allowed": False,
                "auto_fixable": True,
                "control_layer": "repo",
                "recommended_action": "收紧 runtime info 公开输出",
                "evidence": ["GET /api/v1/runtime/info -> 200"],
            },
            {
                "surface": "/#/admin/login",
                "finding_class": "admin-ui-path-migration",
                "severity": "blocker",
                "public_allowed": False,
                "auto_fixable": False,
                "control_layer": "architecture",
                "recommended_action": "迁移后台 UI 到独立路径或子域",
                "evidence": ["后台 UI 仍为同域 hash shell"],
            },
            {
                "surface": "cloudflare://access",
                "finding_class": "cloudflare-access-token-missing",
                "severity": "blocker",
                "public_allowed": False,
                "auto_fixable": False,
                "control_layer": "cloudflare",
                "recommended_action": "补齐 Access 写权限 token",
                "evidence": ["GET /accounts/{account_id}/access/apps -> 403"],
            },
        ]
    }

    publish_plan = plan_autofix_publish(audit_report, policy)

    assert [item["surface"] for item in publish_plan["fix_queue"]] == ["/api/v1/runtime/info"]
    assert publish_plan["should_publish"] is False
    assert publish_plan["stop_reasons"] == [
        "admin-ui-path-migration",
        "cloudflare-access-token-missing",
    ]


def test_deployed_surface_audit_script_marks_public_runtime_info_and_missing_cloudflare_state(
    tmp_path: Path,
) -> None:
    probe_file = tmp_path / "probes.json"
    output_file = tmp_path / "audit.json"
    probe_file.write_text(
        json.dumps(
            [
                {
                    "surface": "/api/v1/runtime/info",
                    "status_code": 200,
                    "headers": {"content-type": "application/json"},
                },
                {
                    "surface": "/api/v1/health",
                    "status_code": 200,
                    "headers": {"content-type": "application/json"},
                },
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "tools/deployed_surface_audit.py",
            "--policy",
            str(POLICY_PATH),
            "--probes-json",
            str(probe_file),
            "--output",
            str(output_file),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    report = json.loads(output_file.read_text(encoding="utf-8"))
    surfaces = {item["surface"]: item for item in report["findings"]}

    assert surfaces["/api/v1/runtime/info"]["finding_class"] == "protected-surface-public"
    assert surfaces["/api/v1/runtime/info"]["auto_fixable"] is True
    assert surfaces["cloudflare://state"]["severity"] == "blocker"
    assert surfaces["cloudflare://state"]["auto_fixable"] is False


def test_security_autofix_publisher_script_outputs_fix_queue_and_stop_reasons(
    tmp_path: Path,
) -> None:
    audit_file = tmp_path / "audit.json"
    output_file = tmp_path / "publish-plan.json"
    audit_file.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "surface": "/api/v1/status",
                        "finding_class": "protected-surface-public",
                        "severity": "high",
                        "public_allowed": False,
                        "auto_fixable": True,
                        "control_layer": "repo",
                        "recommended_action": "为 status 增加边界保护",
                        "evidence": ["GET /api/v1/status -> 200"],
                    },
                    {
                        "surface": "cloudflare://access",
                        "finding_class": "cloudflare-access-token-missing",
                        "severity": "blocker",
                        "public_allowed": False,
                        "auto_fixable": False,
                        "control_layer": "cloudflare",
                        "recommended_action": "补齐 Access 写权限 token",
                        "evidence": ["GET /accounts/{account_id}/access/apps -> 403"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "tools/security_autofix_publisher.py",
            "--policy",
            str(POLICY_PATH),
            "--audit-json",
            str(audit_file),
            "--output",
            str(output_file),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    publish_plan = json.loads(output_file.read_text(encoding="utf-8"))

    assert [item["surface"] for item in publish_plan["fix_queue"]] == ["/api/v1/status"]
    assert publish_plan["stop_reasons"] == ["cloudflare-access-token-missing"]
