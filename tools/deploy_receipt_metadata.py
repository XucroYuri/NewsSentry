#!/usr/bin/env python3
"""Resolve bounded deployment metadata from a validated production receipt."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"[0-9a-f]{40}")


class ReceiptMetadataError(ValueError):
    """Raised when a deployment receipt is incomplete or inconsistent."""


def _timestamp(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReceiptMetadataError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReceiptMetadataError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise ReceiptMetadataError(f"{label} is invalid")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def resolve_metadata(
    receipt: dict[str, Any],
    *,
    expected_commit: str | None = None,
) -> dict[str, str]:
    if receipt.get("status") != "ok":
        raise ReceiptMetadataError("deployment receipt status is not ok")
    if receipt.get("environment") != "production":
        raise ReceiptMetadataError("deployment receipt environment is not production")

    commit = receipt.get("commit")
    if not isinstance(commit, str) or FULL_SHA.fullmatch(commit.lower()) is None:
        raise ReceiptMetadataError("deployment receipt commit is not a full SHA")
    normalized_commit = commit.lower()
    if expected_commit and normalized_commit != expected_commit.lower():
        raise ReceiptMetadataError("deployment receipt expected commit mismatch")

    worker_version = receipt.get("worker_version")
    if not isinstance(worker_version, str) or not worker_version:
        raise ReceiptMetadataError("deployment receipt worker_version is missing")
    deployment_id = receipt.get("deployment_id")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ReceiptMetadataError("deployment receipt deployment_id is missing")
    deployed_at = _timestamp(receipt.get("deployed_at"), label="deployed_at")

    continuity = _mapping(receipt.get("continuity"))
    if continuity.get("status") != "ok":
        raise ReceiptMetadataError("deployment receipt continuity is not ok")
    _timestamp(
        continuity.get("latest_collect_updated_at"),
        label="latest collect updated_at",
    )
    selected_targets = continuity.get("selected_target_ids")
    if not isinstance(selected_targets, list) or not all(
        isinstance(target_id, str) and target_id for target_id in selected_targets
    ) or not selected_targets:
        raise ReceiptMetadataError("deployment receipt selected targets are missing")

    return {
        "environment": "production",
        "deployed_commit": normalized_commit,
        "deployed_at": deployed_at,
        "worker_version": worker_version,
        "deployment_id": deployment_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReceiptMetadataError("deployment receipt must be a JSON object")
    metadata = resolve_metadata(payload, expected_commit=args.expected_commit)
    Path(args.output).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
