#!/usr/bin/env python3
"""Append and evaluate exact-commit Cloudflare continuity receipts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "news-sentry.cloudflare-continuity-ledger.v1"
COMMIT_LENGTH = 40
SLOT_HOURS = 6
SLOTS_72H = 12
SLOTS_7D = 28


class ContinuityReceiptError(ValueError):
    """Raised when a receipt cannot be appended to the continuity ledger."""


@dataclass(frozen=True)
class WindowResult:
    status: str
    deployed_commit: str | None
    reason_codes: list[str]
    healthy_72h_slots: int
    healthy_7d_slots: int
    observed_receipts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "deployed_commit": self.deployed_commit,
            "reason_codes": self.reason_codes,
            "healthy_72h_slots": self.healthy_72h_slots,
            "healthy_7d_slots": self.healthy_7d_slots,
            "observed_receipts": self.observed_receipts,
            "thresholds": {
                "slot_hours": SLOT_HOURS,
                "required_72h_slots": SLOTS_72H,
                "required_7d_slots": SLOTS_7D,
            },
        }


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


def _commit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) != COMMIT_LENGTH or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        return None
    return normalized


def _receipt_key(receipt: dict[str, Any]) -> tuple[str, str, str]:
    commit = _commit(receipt.get("deployed_commit") or receipt.get("expected_commit"))
    observed_at = receipt.get("observed_at") or receipt.get("generated_at")
    run_id = receipt.get("run_id")
    if commit is None:
        raise ContinuityReceiptError("receipt deployed_commit must be a full SHA")
    if not isinstance(observed_at, str) or _timestamp(observed_at) is None:
        raise ContinuityReceiptError("receipt observed_at must be an ISO timestamp")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ContinuityReceiptError("receipt run_id is required")
    return commit, observed_at, run_id.strip()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_name = handle.name
    Path(temp_name).replace(path)


def append_receipt(path: Path, receipt: dict[str, Any]) -> WindowResult:
    key = _receipt_key(receipt)
    rows = _read_jsonl(path)
    for existing in rows:
        if _receipt_key(existing) != key:
            continue
        if _canonical_json(existing) != _canonical_json(receipt):
            raise ContinuityReceiptError("conflicting duplicate continuity receipt")
        return evaluate_window(rows)
    rows.append(receipt)
    rows.sort(key=lambda row: str(row.get("observed_at") or row.get("generated_at") or ""))
    _write_jsonl_atomic(path, rows)
    return evaluate_window(rows)


def _reason_codes_from_summary(receipt: dict[str, Any]) -> set[str]:
    summary = receipt.get("summary")
    if not isinstance(summary, dict):
        return set()
    values = summary.get("reason_codes")
    if isinstance(values, list):
        return {str(value) for value in values}
    return set()


def _future_timestamp_count(receipt: dict[str, Any]) -> int:
    summary = receipt.get("summary")
    if not isinstance(summary, dict):
        return 0
    return int(summary.get("future_timestamp_count") or 0)


def _source_audits(receipt: dict[str, Any]) -> dict[str, Any]:
    source_health = receipt.get("source_health")
    if not isinstance(source_health, dict):
        return {}
    audits = source_health.get("audits")
    return audits if isinstance(audits, dict) else {}


def _source_audit_ok(receipt: dict[str, Any], name: str) -> bool:
    audits = _source_audits(receipt)
    audit = audits.get(name)
    if isinstance(audit, dict):
        return audit.get("status") == "ok"
    source_health = receipt.get("source_health")
    return isinstance(source_health, dict) and source_health.get("status") == "ok"


def _receipt_is_healthy(receipt: dict[str, Any], *, require_boundary: bool) -> bool:
    if receipt.get("status") != "ok":
        return False
    if _future_timestamp_count(receipt) != 0:
        return False
    reason_codes = _reason_codes_from_summary(receipt)
    if any("future" in code for code in reason_codes):
        return False
    if not _source_audit_ok(receipt, "current"):
        return False
    if require_boundary and (
        not _source_audit_ok(receipt, "start") or not _source_audit_ok(receipt, "end")
    ):
        return False
    return True


def _slot(receipt: dict[str, Any]) -> int | None:
    deployed_at = _timestamp(receipt.get("deployed_at"))
    observed_at = _timestamp(receipt.get("observed_at") or receipt.get("generated_at"))
    if deployed_at is None or observed_at is None:
        return None
    elapsed_seconds = (observed_at - deployed_at).total_seconds()
    if elapsed_seconds <= 0:
        return None
    slot_seconds = SLOT_HOURS * 60 * 60
    if elapsed_seconds % slot_seconds != 0:
        return None
    return int(elapsed_seconds // slot_seconds)


def evaluate_window(
    receipts: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> WindowResult:
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    reason_codes: set[str] = set()
    commits = {
        commit
        for receipt in receipts
        if (commit := _commit(receipt.get("deployed_commit") or receipt.get("expected_commit")))
    }
    if not receipts:
        return WindowResult("collecting_72h", None, [], 0, 0, 0)
    if len(commits) != 1:
        reason_codes.add("deployed_commit_changed")
    deployed_commit = next(iter(commits), None)

    slots_72h: set[int] = set()
    slots_7d: set[int] = set()
    seen_keys: dict[tuple[str, str, str], str] = {}
    for receipt in receipts:
        try:
            key = _receipt_key(receipt)
        except ContinuityReceiptError:
            reason_codes.add("invalid_receipt_key")
            continue
        canonical = _canonical_json(receipt)
        if key in seen_keys and seen_keys[key] != canonical:
            reason_codes.add("conflicting_duplicate_receipt")
        seen_keys[key] = canonical
        observed_at = _timestamp(receipt.get("observed_at") or receipt.get("generated_at"))
        if observed_at is None:
            reason_codes.add("observed_at_invalid")
        elif observed_at > observed_now:
            reason_codes.add("observed_at_in_future")
        slot = _slot(receipt)
        if slot is None:
            reason_codes.add("invalid_six_hour_slot")
            continue
        if receipt.get("status") != "ok":
            reason_codes.add("runtime_receipt_not_ok")
        if _future_timestamp_count(receipt) != 0:
            reason_codes.add("future_timestamps_present")
        if not _source_audit_ok(receipt, "current"):
            reason_codes.add("source_health_not_ok")
        if 1 <= slot <= SLOTS_72H and _receipt_is_healthy(receipt, require_boundary=False):
            slots_72h.add(slot)
        if 1 <= slot <= SLOTS_7D and _receipt_is_healthy(receipt, require_boundary=True):
            slots_7d.add(slot)

    max_observed_slot = max(slots_72h | slots_7d, default=0)
    for expected_slot in range(1, min(max_observed_slot, SLOTS_7D) + 1):
        if expected_slot not in slots_72h and expected_slot <= SLOTS_72H:
            reason_codes.add("missing_six_hour_slot")
        if expected_slot > SLOTS_72H and expected_slot not in slots_7d:
            reason_codes.add("missing_six_hour_slot")

    healthy_72h_slots = len(slots_72h)
    healthy_7d_slots = len(slots_7d)
    if reason_codes:
        status = "failed"
    elif healthy_7d_slots >= SLOTS_7D:
        status = "slo_7d_passed"
    elif healthy_72h_slots >= SLOTS_72H:
        status = "canary_72h_passed"
    else:
        status = "collecting_72h"
    if status == "canary_72h_passed" and receipts and max_observed_slot > SLOTS_72H:
        status = "collecting_7d"
    return WindowResult(
        status,
        deployed_commit,
        sorted(reason_codes),
        healthy_72h_slots,
        healthy_7d_slots,
        len(receipts),
    )


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _enrich_receipt(args: argparse.Namespace) -> dict[str, Any]:
    receipt = _load_json(args.receipt)
    if receipt is None:
        raise ContinuityReceiptError("runtime receipt must be a JSON object")
    observed_at = receipt.get("observed_at") or receipt.get("generated_at")
    run_id = args.run_id or os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        raise ContinuityReceiptError("run_id is required")
    deployed_commit = (
        args.deployed_commit
        or receipt.get("deployed_commit")
        or receipt.get("expected_commit")
    )
    deployed_at = args.deployed_at or receipt.get("deployed_at")
    if not deployed_at:
        raise ContinuityReceiptError("deployed_at is required")
    enriched = {
        **receipt,
        "schema_version": receipt.get("schema_version"),
        "deployed_commit": deployed_commit,
        "deployed_at": deployed_at,
        "observed_at": observed_at,
        "run_id": str(run_id),
        "source_health": {
            "audits": {
                "current": _load_json(args.source_health_current),
                "start": _load_json(args.source_health_start),
                "end": _load_json(args.source_health_end),
            }
        },
    }
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("--ledger", required=True)
    append.add_argument("--receipt", required=True)
    append.add_argument("--deployed-commit")
    append.add_argument("--deployed-at", required=True)
    append.add_argument("--run-id")
    append.add_argument("--source-health-current", required=True)
    append.add_argument("--source-health-start", required=True)
    append.add_argument("--source-health-end", required=True)
    append.add_argument("--output")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--ledger", required=True)
    evaluate.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        if args.command == "append":
            result = append_receipt(Path(args.ledger), _enrich_receipt(args))
        else:
            result = evaluate_window(_read_jsonl(Path(args.ledger)))
    except (ContinuityReceiptError, json.JSONDecodeError) as error:
        print(f"cloudflare continuity ledger failed: {error}", file=sys.stderr)
        return 2
    payload = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
