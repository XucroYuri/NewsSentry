"""Report per-target public source coverage for News Sentry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


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


def _source_file_exists(project_root: Path, target_id: str, ref: str) -> bool:
    return (project_root / "config" / "sources" / target_id / f"{ref}.yaml").is_file()


def build_source_coverage_report(
    project_root: Path,
    *,
    minimum_refs: int = 20,
) -> dict[str, Any]:
    targets_dir = project_root / "config" / "targets"
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
        missing_files = [
            ref for ref in refs if not _source_file_exists(project_root, target_id, ref)
        ]
        source_refs = len(refs)
        target_items.append(
            {
                "target_id": target_id,
                "display_name": target.get("display_name") or target_id,
                "source_refs": source_refs,
                "minimum_refs": minimum_refs,
                "missing": max(0, minimum_refs - source_refs),
                "ready": source_refs >= minimum_refs and not missing_files,
                "missing_files": missing_files,
            }
        )

    below = [item for item in target_items if not item["ready"]]
    below.sort(key=lambda item: (item["source_refs"], item["target_id"]))
    return {
        "target_count": len(target_items),
        "minimum_refs": minimum_refs,
        "source_ref_total": sum(int(item["source_refs"]) for item in target_items),
        "ready_targets": sum(1 for item in target_items if item["ready"]),
        "targets_below_minimum": below,
        "targets": target_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--minimum-refs", type=int, default=20)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    report = build_source_coverage_report(
        args.project_root.resolve(),
        minimum_refs=max(1, args.minimum_refs),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if not report["targets_below_minimum"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
