#!/usr/bin/env python3
"""Emit enabled SEO/GEO rule sources from the local registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().with_name("rule_sources.json")
STABLE_REGISTRY_REF = "tools/seo_geo/rule_sources.json"


def load_rule_sources(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def describe_registry_ref(path: Path, *, cwd: Path | None = None) -> str:
    del cwd
    if path.resolve() == DEFAULT_REGISTRY_PATH.resolve():
        return STABLE_REGISTRY_REF
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def available_categories(registry: dict[str, Any]) -> set[str]:
    return {
        category
        for category, items in registry.items()
        if category != "schema_version" and isinstance(items, list)
    }


def validate_requested_categories(
    registry: dict[str, Any],
    categories: set[str] | None,
) -> list[str]:
    if not categories:
        return []
    known_categories = available_categories(registry)
    return sorted(category for category in categories if category not in known_categories)


def iter_enabled_rule_sources(
    registry: dict[str, Any],
    *,
    categories: set[str] | None = None,
) -> list[dict[str, Any]]:
    enabled: list[dict[str, Any]] = []
    requested_categories = categories or set()
    for category, items in registry.items():
        if category == "schema_version" or not isinstance(items, list):
            continue
        if requested_categories and category not in requested_categories:
            continue
        for item in items:
            if not isinstance(item, dict) or not item.get("enabled", False):
                continue
            enabled.append(
                {
                    "category": category,
                    "id": str(item["id"]),
                    "type": str(item["type"]),
                    "url": str(item["url"]),
                    "topics": sorted(str(topic) for topic in item.get("topics", [])),
                    "enabled": True,
                }
            )
    return sorted(enabled, key=lambda item: (item["category"], item["id"], item["url"]))


def build_rule_sources_report(
    registry: dict[str, Any],
    *,
    registry_ref: str = STABLE_REGISTRY_REF,
    categories: set[str] | None = None,
) -> dict[str, Any]:
    enabled_sources = iter_enabled_rule_sources(registry, categories=categories)
    category_index: dict[str, list[dict[str, Any]]] = {}
    for source in enabled_sources:
        category_index.setdefault(source["category"], []).append(source)

    selected_categories = sorted(categories) if categories else sorted(category_index)
    return {
        "schema_version": registry.get("schema_version", 1),
        "registry": registry_ref,
        "selected_categories": selected_categories,
        "enabled_count": len(enabled_sources),
        "categories": category_index,
        "items": enabled_sources,
    }


def build_unknown_categories_error(
    registry: dict[str, Any],
    unknown_categories: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": registry.get("schema_version", 1),
        "ok": False,
        "error": {
            "code": "unknown_categories",
            "message": f"Unknown categories: {', '.join(unknown_categories)}",
            "unknown_categories": unknown_categories,
            "available_categories": sorted(available_categories(registry)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Expose enabled SEO/GEO rule sources.")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to tools/seo_geo/rule_sources.json.",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Optional category filter. May be passed multiple times.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    registry_path = Path(args.registry).resolve()
    registry = load_rule_sources(registry_path)
    requested_categories = set(args.category) or None
    unknown_categories = validate_requested_categories(registry, requested_categories)
    if unknown_categories:
        payload = json.dumps(
            build_unknown_categories_error(registry, unknown_categories),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        return 1

    report = build_rule_sources_report(
        registry,
        registry_ref=describe_registry_ref(registry_path),
        categories=requested_categories,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
