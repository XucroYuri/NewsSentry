#!/usr/bin/env python3
"""Build a production runtime receipt from Cloudflare control-plane and D1 evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "news-sentry.runtime-probe.control-plane.v1"
VALID_COLLECT_STATUSES = {"ok", "partial", "empty_no_new_items"}


class ControlPlaneProbeError(ValueError):
    """Raised when control-plane or D1 evidence is structurally unusable."""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _d1_row(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict) and first.get("success") is False:
            raise ControlPlaneProbeError("D1 query was not successful")
        results = first.get("results") if isinstance(first, dict) else None
    elif isinstance(value, dict):
        if value.get("success") is False:
            raise ControlPlaneProbeError("D1 query was not successful")
        results = value.get("results")
    else:
        results = None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ControlPlaneProbeError("D1 query did not return one row")
    return results[0]


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            for key in ("results", "result", "items"):
                nested = value[0].get(key)
                if isinstance(nested, list):
                    return [row for row in nested if isinstance(row, dict)]
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("results", "result", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
    return []


def _annotation(value: dict[str, Any], key: str, fallback: str) -> str | None:
    for container_key in ("annotations", "metadata"):
        annotations = value.get(container_key)
        if isinstance(annotations, dict):
            annotation_value = annotations.get(key)
            if isinstance(annotation_value, str):
                return annotation_value
    direct = value.get(fallback)
    return direct if isinstance(direct, str) else None


def _deployment_is_exact_version(deployment: dict[str, Any], version_id: str) -> bool:
    direct = deployment.get("version_id") or deployment.get("version")
    if isinstance(direct, str):
        return direct == version_id
    versions = deployment.get("versions")
    if not isinstance(versions, list) or not versions:
        return False
    total = 0.0
    exact = False
    for version in versions:
        if not isinstance(version, dict):
            return False
        percentage_value = version.get("percentage")
        if isinstance(percentage_value, bool) or not isinstance(
            percentage_value, (int, float)
        ):
            return False
        percentage = float(percentage_value)
        if not 0 <= percentage <= 100:
            return False
        total += percentage
        candidate = version.get("version_id") or version.get("id")
        if candidate == version_id and percentage == 100:
            exact = True
    return exact and total == 100


def _current_deployment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    deployment_id = value.get("id")
    versions = value.get("versions")
    if not isinstance(deployment_id, str) or not isinstance(versions, list):
        return {}
    return value


def _check(name: str, reasons: list[str], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "ok": not reasons,
        "reason_codes": sorted(set(reasons)),
        "degraded_reason_codes": [],
        "evidence": evidence,
    }


def _age_reasons(
    value: Any,
    *,
    now: datetime,
    max_age: timedelta,
    max_future: datetime,
    missing: str,
    stale: str,
    future: str,
) -> tuple[datetime | None, list[str]]:
    parsed = _timestamp(value)
    if parsed is None:
        return None, [missing]
    reasons: list[str] = []
    if parsed < now - max_age:
        reasons.append(stale)
    if parsed > max_future:
        reasons.append(future)
    return parsed, reasons


def build_receipt(
    *,
    deployment_metadata: dict[str, Any],
    versions_json: Any,
    deployments_json: Any,
    d1_json: Any,
    max_data_age_hours: float,
    max_future_skew_minutes: float,
    run_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    max_age = timedelta(hours=max_data_age_hours)
    max_future = generated_at + timedelta(minutes=max_future_skew_minutes)
    row = _d1_row(d1_json)
    checks: list[dict[str, Any]] = []

    commit = deployment_metadata.get("deployed_commit")
    worker_version = deployment_metadata.get("worker_version")
    deployment_reasons: list[str] = []
    if deployment_metadata.get("environment") != "production":
        deployment_reasons.append("deployment_environment_mismatch")
    if not isinstance(commit, str) or len(commit) != 40:
        deployment_reasons.append("deployment_commit_invalid")
    if not isinstance(worker_version, str) or not worker_version:
        deployment_reasons.append("deployment_worker_version_missing")
    if not deployment_metadata.get("deployment_id"):
        deployment_reasons.append("deployment_id_missing")
    if _timestamp(deployment_metadata.get("deployed_at")) is None:
        deployment_reasons.append("deployment_timestamp_invalid")
    checks.append(
        _check(
            "deployment_receipt",
            deployment_reasons,
            {
                "commit": commit,
                "worker_version": worker_version,
                "deployment_id": deployment_metadata.get("deployment_id"),
            },
        )
    )

    active_reasons: list[str] = []
    versions = _rows(versions_json)
    matching_versions = [
        version
        for version in versions
        if isinstance(commit, str)
        and _annotation(version, "workers/tag", "tag") == commit
        and isinstance(_annotation(version, "workers/message", "message"), str)
        and commit in (_annotation(version, "workers/message", "message") or "")
    ]
    active_version_id = None
    if matching_versions:
        candidate = matching_versions[0].get("id") or matching_versions[0].get("version_id")
        active_version_id = candidate if isinstance(candidate, str) else None
    if active_version_id is None:
        active_reasons.append("active_version_annotation_missing")
    elif active_version_id != worker_version:
        active_reasons.append("active_version_receipt_mismatch")

    active_deployment = _current_deployment(deployments_json)
    active_deployment_id = active_deployment.get("id")
    if active_deployment_id != deployment_metadata.get("deployment_id"):
        active_reasons.append("active_deployment_id_mismatch")
    if not isinstance(worker_version, str) or not _deployment_is_exact_version(
        active_deployment, worker_version
    ):
        active_reasons.append("active_worker_version_mismatch")
    checks.append(
        _check(
            "active_deployment",
            active_reasons,
            {
                "deployment_id": active_deployment_id,
                "worker_version": active_version_id,
            },
        )
    )

    collect_reasons: list[str] = []
    raw_collect = row.get("collect_value")
    try:
        collect = json.loads(raw_collect) if isinstance(raw_collect, str) else None
    except json.JSONDecodeError:
        collect = None
    collect_mapping = _mapping(collect)
    details = _mapping(collect_mapping.get("details"))
    batch = _mapping(details.get("collect_batch"))
    selected_targets = batch.get("selected_target_ids")
    if collect_mapping.get("status") not in VALID_COLLECT_STATUSES:
        collect_reasons.append("collect_status_invalid")
    if not isinstance(collect_mapping.get("runId"), str) or not collect_mapping.get("runId"):
        collect_reasons.append("collect_run_id_missing")
    _, continuity_age_reasons = _age_reasons(
        row.get("collect_updated_at"),
        now=generated_at,
        max_age=max_age,
        max_future=max_future,
        missing="collect_continuity_timestamp_invalid",
        stale="collect_continuity_stale",
        future="collect_continuity_in_future",
    )
    collect_reasons.extend(continuity_age_reasons)
    if details.get("environment") != "production":
        collect_reasons.append("collect_environment_mismatch")
    if details.get("deploy_commit") != commit:
        collect_reasons.append("collect_commit_mismatch")
    if details.get("worker_version") != worker_version:
        collect_reasons.append("collect_worker_version_mismatch")
    if details.get("scheduler_mode") != "shadow":
        collect_reasons.append("scheduler_mode_mismatch")
    if details.get("worker_native_collect_enabled") is not False:
        collect_reasons.append("worker_native_collect_not_disabled")
    if details.get("collection_authoritative") is not False:
        collect_reasons.append("collection_authority_mismatch")
    for key in (
        "container_configured",
        "queue_configured",
        "dlq_configured",
        "artifacts_configured",
    ):
        if details.get(key) is not True:
            collect_reasons.append(f"{key}_missing")
    if not isinstance(selected_targets, list) or not selected_targets or not all(
        isinstance(target_id, str) and target_id for target_id in selected_targets
    ):
        collect_reasons.append("collect_target_selection_missing")
    checks.append(
        _check(
            "collect_continuity",
            collect_reasons,
            {
                "status": collect_mapping.get("status"),
                "run_id": collect_mapping.get("runId"),
                "updated_at": row.get("collect_updated_at"),
                "selected_target_ids": (
                    selected_targets if isinstance(selected_targets, list) else []
                ),
                "deploy_commit": details.get("deploy_commit"),
                "worker_version": details.get("worker_version"),
            },
        )
    )

    data_reasons: list[str] = []
    total_events = row.get("total_events")
    if not isinstance(total_events, int) or total_events <= 0:
        data_reasons.append("events_missing")
    _, collected_age_reasons = _age_reasons(
        row.get("latest_valid_collected_at"),
        now=generated_at,
        max_age=max_age,
        max_future=max_future,
        missing="latest_collected_missing_or_invalid",
        stale="latest_collected_too_old",
        future="latest_collected_in_future",
    )
    data_reasons.extend(collected_age_reasons)
    future_count = row.get("future_timestamp_count")
    if not isinstance(future_count, int):
        data_reasons.append("future_timestamp_count_invalid")
    elif future_count != 0:
        data_reasons.append("future_timestamps_present")
    checks.append(
        _check(
            "data_freshness",
            data_reasons,
            {
                "total_events": total_events,
                "latest_valid_collected_at": row.get("latest_valid_collected_at"),
                "future_timestamp_count": future_count,
            },
        )
    )

    snapshot_reasons: list[str] = []
    snapshot_total = row.get("snapshot_total")
    if not isinstance(snapshot_total, int) or snapshot_total <= 0:
        snapshot_reasons.append("active_snapshot_missing")
    _, snapshot_age_reasons = _age_reasons(
        row.get("latest_snapshot_generated_at"),
        now=generated_at,
        max_age=max_age,
        max_future=max_future,
        missing="active_snapshot_timestamp_invalid",
        stale="active_snapshot_stale",
        future="active_snapshot_in_future",
    )
    snapshot_reasons.extend(snapshot_age_reasons)
    latest_public = _timestamp(row.get("latest_source_public_at"))
    if latest_public is None:
        snapshot_reasons.append("latest_public_missing_or_invalid")
    elif latest_public > max_future:
        snapshot_reasons.append("latest_public_in_future")
    checks.append(
        _check(
            "public_snapshot",
            snapshot_reasons,
            {
                "snapshot_total": snapshot_total,
                "latest_snapshot_generated_at": row.get("latest_snapshot_generated_at"),
                "latest_source_public_at": row.get("latest_source_public_at"),
            },
        )
    )

    p0_reasons: list[str] = []
    p0_dead_lettered = row.get("p0_dead_lettered")
    if not isinstance(p0_dead_lettered, int):
        p0_reasons.append("p0_dlq_count_invalid")
    elif p0_dead_lettered != 0:
        p0_reasons.append("p0_dlq_not_empty")
    checks.append(_check("p0_dlq", p0_reasons, {"p0_dead_lettered": p0_dead_lettered}))

    reason_codes = sorted(
        {reason for check in checks for reason in check["reason_codes"]}
    )
    passed = sum(1 for check in checks if check["ok"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "observed_at": generated_at.isoformat(),
        "run_id": run_id,
        "environment": "production",
        "evidence_source": "cloudflare-control-plane+d1",
        "expected_commit": commit,
        "deployed_commit": commit,
        "deployed_at": deployment_metadata.get("deployed_at"),
        "worker_version": worker_version,
        "thresholds": {
            "max_data_age_hours": max_data_age_hours,
            "max_future_skew_minutes": max_future_skew_minutes,
        },
        "status": "ok" if not reason_codes else "failed",
        "summary": {
            "passed": passed,
            "failed": len(checks) - passed,
            "reason_codes": reason_codes,
            "future_timestamp_count": future_count,
        },
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-metadata", required=True)
    parser.add_argument("--versions-json", required=True)
    parser.add_argument("--deployments-json", required=True)
    parser.add_argument("--d1-json", required=True)
    parser.add_argument("--max-data-age-hours", type=float, default=2.0)
    parser.add_argument("--max-future-skew-minutes", type=float, default=5.0)
    parser.add_argument("--run-id")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    metadata = json.loads(Path(args.deployment_metadata).read_text(encoding="utf-8"))
    versions_json = json.loads(Path(args.versions_json).read_text(encoding="utf-8"))
    deployments_json = json.loads(Path(args.deployments_json).read_text(encoding="utf-8"))
    d1_json = json.loads(Path(args.d1_json).read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ControlPlaneProbeError("deployment metadata must be a JSON object")
    receipt = build_receipt(
        deployment_metadata=metadata,
        versions_json=versions_json,
        deployments_json=deployments_json,
        d1_json=d1_json,
        max_data_age_hours=args.max_data_age_hours,
        max_future_skew_minutes=args.max_future_skew_minutes,
        run_id=args.run_id,
    )
    Path(args.output).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
