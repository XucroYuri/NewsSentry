"""Target source inventory reconciliation.

This module is the backend truth source for target/source management. It
reconciles target refs, source YAML files, social dimensions and health records
without mutating configuration or runtime data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

STANDARD_SOURCE_TYPES = {"rss", "api"}


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _source_is_archived(source: dict[str, Any]) -> bool:
    return bool(source.get("deprecated")) or (
        source.get("enabled") is False and bool(source.get("deprecated_reason"))
    )


def _source_is_archived_or_disabled(source: dict[str, Any]) -> bool:
    """信源在运行时是否被跳过（已归档 或 enabled 明确为 false）。

    明确设置 enabled: false（无 deprecated_reason）意味着用户通过 UI 手动暂停采集，
    与 run.py 第 263 行的跳过逻辑（source_cfg.get("enabled") is False）一致。
    inventory 的 archived 字段使用此函数，使前端可以安全地通过 !item.archived 判断
    信源在当前配置下是否会被实际采集。
    """
    return _source_is_archived(source) or source.get("enabled") is False


def _memory_health_status(entry: dict[str, Any]) -> str:
    failures = int(entry.get("consecutive_failures") or 0)
    total_runs = int(entry.get("total_runs") or 0)
    total_failures = int(entry.get("total_failures") or 0)
    if failures >= 10:
        return "dead"
    if failures >= 3:
        return "degraded"
    if total_runs > 0 and total_failures >= total_runs:
        return "degraded"
    return "healthy"


def _memory_error_count(entry: dict[str, Any]) -> int:
    return int(entry.get("consecutive_failures") or entry.get("total_failures") or 0)


def _normalize_health_record(
    source_id: str,
    entry: dict[str, Any],
    target_id: str,
) -> dict[str, Any]:
    return {
        "source_id": str(source_id),
        "status": _memory_health_status(entry),
        "last_check": entry.get("last_success_at") or entry.get("last_failure_at") or "",
        "error_count": _memory_error_count(entry),
        "metadata": {
            "target_id": target_id,
            "last_success_at": entry.get("last_success_at"),
            "last_failure_at": entry.get("last_failure_at"),
            "last_error": entry.get("last_error"),
            "total_runs": entry.get("total_runs", 0),
            "total_failures": entry.get("total_failures", 0),
            "consecutive_failures": entry.get("consecutive_failures", 0),
        },
    }


class SourceInventoryService:
    """Build reconciled source inventory for a target."""

    def __init__(self, project_root: Path, data_dir: Path | None = None) -> None:
        self.project_root = Path(project_root)
        self.data_dir = Path(data_dir) if data_dir is not None else self.project_root / "data"

    def build_target_inventory(
        self,
        target_id: str,
        health_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        target_path = self.project_root / "config" / "targets" / f"{target_id}.yaml"
        target = _load_yaml_file(target_path)
        if target is None:
            raise FileNotFoundError(f"Target config not found: {target_id}")

        refs = [str(ref) for ref in target.get("source_channel_refs", []) if isinstance(ref, str)]
        refs_set = set(refs)
        file_sources = self._load_source_files(target_id)
        source_id_counts = Counter(
            str(item["source_id"]) for item in file_sources.values() if item.get("source_id")
        )

        sources: dict[str, dict[str, Any]] = {}
        for ref in refs:
            source = file_sources.get(ref)
            if source is None:
                sources[ref] = self._missing_source_item(ref)
                continue
            sources[ref] = self._source_item(source, in_target_refs=True, refs_set=refs_set)

        for ref, source in file_sources.items():
            if ref in sources:
                continue
            sources[ref] = self._source_item(source, in_target_refs=False, refs_set=refs_set)

        for item in sources.values():
            source_id = str(item.get("source_id") or "")
            item["duplicate_source_id"] = bool(source_id and source_id_counts[source_id] > 1)

        records = (
            health_records if health_records is not None else self._load_memory_health(target_id)
        )
        self._attach_health(sources, records)

        source_list = list(sources.values())
        missing_refs = [item for item in source_list if item["missing_file"]]
        unreferenced = [item for item in source_list if item["unreferenced"]]
        duplicate_ids = sorted(
            source_id for source_id, count in source_id_counts.items() if source_id and count > 1
        )
        standard_sources = [
            item
            for item in source_list
            if item["type"] in STANDARD_SOURCE_TYPES and not item["missing_file"]
        ]
        social_dimensions = [
            item for item in source_list if item["type"] == "social" and not item["missing_file"]
        ]
        health = self._health_summary(source_list, records)

        return {
            "target": {
                "target_id": target.get("target_id", target_id),
                "display_name": target.get("display_name", ""),
                "lifecycle": self._target_lifecycle(target),
                "config_path": _relative_path(self.project_root, target_path),
            },
            "summary": {
                "refs_total": len(refs),
                "files_total": len(file_sources),
                "standard_sources": len(standard_sources),
                "social_dimensions": len(social_dimensions),
                "social_accounts": sum(
                    int(item.get("account_count") or 0) for item in social_dimensions
                ),
                "active_sources": sum(
                    1 for item in source_list if not item["missing_file"] and not item["archived"]
                ),
                "archived_sources": sum(
                    1 for item in source_list if not item["missing_file"] and item["archived"]
                ),
                "missing_refs": len(missing_refs),
                "unreferenced_files": len(unreferenced),
                "duplicate_source_ids": len(duplicate_ids),
                "health_records": health["total"],
                "health_matched": health["matched"],
                "health_unmatched": health["unmatched"],
            },
            "sources": source_list,
            "health": health,
            "diagnostics": {
                "missing_refs": [
                    {"source_ref": item["source_ref"], "source_id": item["source_id"]}
                    for item in missing_refs
                ],
                "unreferenced_files": [
                    {
                        "source_ref": item["source_ref"],
                        "source_id": item["source_id"],
                        "file_path": item["file_path"],
                    }
                    for item in unreferenced
                ],
                "duplicate_source_ids": duplicate_ids,
                "unmatched_health": health["unmatched_records"],
            },
        }

    def _load_source_files(self, target_id: str) -> dict[str, dict[str, Any]]:
        sources_dir = self.project_root / "config" / "sources" / target_id
        if not sources_dir.is_dir():
            return {}
        sources: dict[str, dict[str, Any]] = {}
        for path in sorted(sources_dir.rglob("*.yaml")):
            if path.name.startswith("_"):
                continue
            data = _load_yaml_file(path)
            if data is None:
                continue
            ref = str(path.relative_to(sources_dir).with_suffix(""))
            data["_source_ref"] = ref
            data["_file_path"] = _relative_path(self.project_root, path)
            sources[ref] = data
        return sources

    def _load_memory_health(self, target_id: str) -> list[dict[str, Any]]:
        path = self.data_dir / target_id / "memory" / "source_health.yaml"
        data = _load_yaml_file(path)
        if not isinstance(data, dict):
            return []
        records: list[dict[str, Any]] = []
        for source_id, entry in data.items():
            if isinstance(entry, dict):
                records.append(_normalize_health_record(str(source_id), entry, target_id))
        return records

    def _target_lifecycle(self, target: dict[str, Any]) -> dict[str, Any]:
        lifecycle = target.get("lifecycle")
        if not isinstance(lifecycle, dict):
            return {"status": "active"}
        return {**lifecycle, "status": lifecycle.get("status") or "active"}

    def _missing_source_item(self, source_ref: str) -> dict[str, Any]:
        return {
            "source_ref": source_ref,
            "source_id": Path(source_ref).name,
            "display_name": "",
            "type": "missing",
            "enabled": False,
            "archived": False,
            "deprecated": False,
            "deprecated_reason": None,
            "url": None,
            "file_path": None,
            "in_target_refs": True,
            "missing_file": True,
            "unreferenced": False,
            "duplicate_source_id": False,
            "health": None,
            "account_count": 0,
            "archived_account_count": 0,
        }

    def _source_item(
        self,
        source: dict[str, Any],
        *,
        in_target_refs: bool,
        refs_set: set[str],
    ) -> dict[str, Any]:
        source_ref = str(source.get("_source_ref") or source.get("_source_id") or "")
        source_type = str(
            (source.get("type") or "social")
            if source_ref.startswith("social/")
            else (source.get("type") or "unknown")
        )
        source_id = str(source.get("source_id") or source.get("dimension") or Path(source_ref).name)
        url_val = source.get("url")
        if url_val is None and isinstance(source.get("endpoint"), dict):
            url_val = source["endpoint"].get("url")
        raw_accounts = source.get("accounts")
        accounts: list[Any] = raw_accounts if isinstance(raw_accounts, list) else []
        return {
            "source_ref": source_ref,
            "source_id": source_id,
            "display_name": source.get("display_name") or source.get("dimension") or "",
            "type": source_type,
            "enabled": bool(source.get("enabled", True)),
            "archived": _source_is_archived_or_disabled(source),
            "deprecated": bool(source.get("deprecated", False)),
            "deprecated_reason": source.get("deprecated_reason"),
            "credibility_base": source.get("credibility_base"),
            "url": url_val,
            "file_path": source.get("_file_path"),
            "in_target_refs": in_target_refs,
            "missing_file": False,
            "unreferenced": source_ref not in refs_set,
            "duplicate_source_id": False,
            "health": None,
            "account_count": len(accounts),
            "archived_account_count": sum(
                1
                for account in accounts
                if isinstance(account, dict) and account.get("monitor_mode") == "archived"
            ),
        }

    def _attach_health(
        self,
        sources: dict[str, dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> None:
        alias_map: dict[str, list[str]] = defaultdict(list)
        for ref, item in sources.items():
            aliases = {
                ref,
                str(item.get("source_id") or ""),
                Path(ref).name,
            }
            for alias in aliases:
                if alias:
                    alias_map[alias].append(ref)

        for record in records:
            source_id = str(record.get("source_id") or "")
            matches = alias_map.get(source_id, [])
            if len(matches) == 1:
                sources[matches[0]]["health"] = record

    def _health_summary(
        self,
        sources: list[dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        matched_source_ids = {
            str(item["health"].get("source_id"))
            for item in sources
            if isinstance(item.get("health"), dict)
        }
        matched_records = [
            item["health"] for item in sources if isinstance(item.get("health"), dict)
        ]
        unmatched_records = [
            record
            for record in records
            if str(record.get("source_id") or "") not in matched_source_ids
        ]
        return {
            "total": len(records),
            "matched": len(matched_records),
            "unmatched": len(unmatched_records),
            "matched_records": matched_records,
            "unmatched_records": unmatched_records,
        }
