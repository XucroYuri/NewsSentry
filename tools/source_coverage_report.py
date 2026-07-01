"""Report per-target public source coverage for News Sentry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError, validate

SOURCE_SCHEMA_NAME = "sourcechannel.schema.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return value if isinstance(value, dict) else {}


def _source_refs(target: dict[str, Any]) -> list[str]:
    refs = target.get("source_channel_refs")
    if not isinstance(refs, list):
        return []
    return [str(ref).strip() for ref in refs if str(ref).strip()]


def _load_source_schema(project_root: Path) -> dict[str, Any]:
    schema = _load_yaml(project_root / "schemas" / SOURCE_SCHEMA_NAME)
    if schema:
        return schema
    return _load_yaml(Path(__file__).resolve().parents[1] / "schemas" / SOURCE_SCHEMA_NAME)


def _source_path_for_ref(project_root: Path, target_id: str, ref: str) -> Path:
    if ref.startswith("pool:"):
        pool_ref = ref.removeprefix("pool:")
        return project_root / "config" / "source-pools" / f"{pool_ref}.yaml"
    return project_root / "config" / "sources" / target_id / f"{ref}.yaml"


def _source_url(source: dict[str, Any]) -> str | None:
    url = source.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    endpoint = source.get("endpoint")
    if isinstance(endpoint, dict):
        endpoint_url = endpoint.get("url")
        if isinstance(endpoint_url, str) and endpoint_url.strip():
            return endpoint_url.strip()
    return None


def _source_fingerprint(source: dict[str, Any], url: str | None) -> str | None:
    if not url:
        return None
    endpoint = source.get("endpoint")
    if isinstance(endpoint, dict):
        params = endpoint.get("params")
        if isinstance(params, dict) and params:
            return f"{url}?{json.dumps(params, sort_keys=True, ensure_ascii=True)}"
    return url


def _validation_evidence_from_notes(notes: object) -> dict[str, Any]:
    if not isinstance(notes, str):
        return {}
    evidence: dict[str, Any] = {}
    status_match = re.search(r"\bHTTP\s+(\d{3})\b", notes, flags=re.IGNORECASE)
    if status_match:
        evidence["http_status"] = int(status_match.group(1))
    entries_match = re.search(r"\b(\d+)\s+entr(?:y|ies)\b", notes, flags=re.IGNORECASE)
    if entries_match:
        evidence["parser_entry_count"] = int(entries_match.group(1))
    latest_match = re.search(r"\blatest\s+([^;]+?)(?:;|$)", notes, flags=re.IGNORECASE)
    if latest_match:
        evidence["latest_entry_at"] = latest_match.group(1).strip()
    return evidence


def _validate_source_schema(
    source: dict[str, Any],
    schema: dict[str, Any],
) -> str | None:
    if not schema:
        return "schema_missing"
    try:
        validate(source, schema)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        location = f"{path}: " if path else ""
        return f"{location}{exc.message}"
    return None


def _base_source_receipt(target_id: str, ref: str, path: Path) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "source_ref": ref,
        "source_id": None,
        "url": None,
        "type": None,
        "source_path": str(path),
        "http_status": None,
        "parser_entry_count": None,
        "latest_entry_at": None,
        "duplicate_check": "not_checked",
        "accepted_reason": "not_checked",
    }


def _source_receipt(
    project_root: Path,
    target_id: str,
    ref: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    path = _source_path_for_ref(project_root, target_id, ref)
    receipt = _base_source_receipt(target_id, ref, path)
    if not path.is_file():
        receipt["accepted_reason"] = "missing_file"
        return receipt

    source = _load_yaml(path)
    receipt["source_id"] = source.get("source_id")
    receipt["type"] = source.get("type")
    receipt["url"] = _source_url(source)
    receipt["_duplicate_fingerprint"] = _source_fingerprint(source, receipt["url"])
    receipt.update(_validation_evidence_from_notes(source.get("notes")))

    schema_error = _validate_source_schema(source, schema)
    if schema_error:
        receipt["accepted_reason"] = "schema_invalid"
        receipt["schema_error"] = schema_error
        return receipt
    if source.get("enabled") is not True:
        receipt["accepted_reason"] = "disabled"
        return receipt
    if source.get("deprecated") is True:
        receipt["accepted_reason"] = "deprecated"
        return receipt
    if not receipt["url"]:
        receipt["accepted_reason"] = "missing_url_or_endpoint"
        return receipt

    receipt["accepted_reason"] = "static_valid"
    return receipt


def _apply_duplicate_checks(receipts: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for receipt in receipts:
        fingerprint = receipt.get("_duplicate_fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            counts[fingerprint] = counts.get(fingerprint, 0) + 1
    for receipt in receipts:
        fingerprint = receipt.pop("_duplicate_fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            receipt["duplicate_check"] = "not_applicable"
            continue
        receipt["duplicate_check"] = (
            "duplicate_url" if counts.get(fingerprint, 0) > 1 else "unique"
        )


def build_source_coverage_report(
    project_root: Path,
    *,
    minimum_refs: int = 20,
) -> dict[str, Any]:
    targets_dir = project_root / "config" / "targets"
    source_schema = _load_source_schema(project_root)
    target_items: list[dict[str, Any]] = []
    for target_path in sorted(targets_dir.glob("*.yaml")):
        if target_path.stem.startswith("_"):
            continue
        target = _load_yaml(target_path)
        lifecycle = target.get("lifecycle")
        lifecycle_status = ""
        if isinstance(lifecycle, dict):
            lifecycle_status = str(lifecycle.get("status") or "").lower()
        if lifecycle_status in {"retired", "archive", "archived", "dead"}:
            continue
        target_id = str(target.get("target_id") or target_path.stem)
        refs = _source_refs(target)
        receipts = [
            _source_receipt(project_root, target_id, ref, source_schema) for ref in refs
        ]
        _apply_duplicate_checks(receipts)
        valid_refs = [
            receipt["source_ref"]
            for receipt in receipts
            if receipt["accepted_reason"] == "static_valid"
            and receipt["duplicate_check"] != "duplicate_url"
        ]
        invalid_refs = [
            receipt["source_ref"] for receipt in receipts if receipt["source_ref"] not in valid_refs
        ]
        missing_files = [
            receipt["source_ref"]
            for receipt in receipts
            if receipt["accepted_reason"] == "missing_file"
        ]
        source_refs = len(refs)
        valid_source_refs = len(valid_refs)
        target_items.append(
            {
                "target_id": target_id,
                "display_name": target.get("display_name") or target_id,
                "source_refs": source_refs,
                "valid_source_refs": valid_source_refs,
                "minimum_refs": minimum_refs,
                "missing": max(0, minimum_refs - valid_source_refs),
                "ready": valid_source_refs >= minimum_refs,
                "missing_files": missing_files,
                "invalid_source_refs": invalid_refs,
                "source_candidate_receipts": receipts,
            }
        )

    below = [item for item in target_items if not item["ready"]]
    below.sort(key=lambda item: (item["valid_source_refs"], item["target_id"]))
    return {
        "target_count": len(target_items),
        "minimum_refs": minimum_refs,
        "source_ref_total": sum(int(item["source_refs"]) for item in target_items),
        "valid_source_ref_total": sum(
            int(item["valid_source_refs"]) for item in target_items
        ),
        "ready_targets": sum(1 for item in target_items if item["ready"]),
        "targets_below_minimum": below,
        "targets": target_items,
    }


def _receipt_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    targets = report.get("targets")
    if not isinstance(targets, list):
        return rows
    for target in targets:
        if not isinstance(target, dict):
            continue
        receipts = target.get("source_candidate_receipts")
        if not isinstance(receipts, list):
            continue
        rows.extend(receipt for receipt in receipts if isinstance(receipt, dict))
    return rows


def write_receipts_jsonl(report: dict[str, Any], output_path: Path) -> int:
    rows = _receipt_rows(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows
    )
    output_path.write_text(payload, encoding="utf-8")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--minimum-refs", type=int, default=20)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--receipt-output",
        type=Path,
        help="Write flattened source candidate receipts as JSON Lines.",
    )
    args = parser.parse_args()
    report = build_source_coverage_report(
        args.project_root.resolve(),
        minimum_refs=max(1, args.minimum_refs),
    )
    if args.receipt_output:
        write_receipts_jsonl(report, args.receipt_output)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if not report["targets_below_minimum"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
