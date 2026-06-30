"""Generate idempotent Cloudflare D1 backfill SQL from local News Sentry data."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class D1Event:
    event_id: str
    target_id: str
    target_label: str
    source_id: str
    source_name: str
    source_type: str
    published_at: str
    collected_at: str
    title: str
    original_url: str
    issue_tags: list[str]
    related_tags: list[str]
    region_tags: list[str]
    entities: list[dict[str, str]]
    classification: dict[str, str]
    value_label: str
    value_score: int | None
    china_relevance_label: str
    pipeline_stage: str = "drafts"


@dataclass(frozen=True)
class D1Target:
    target_id: str
    display_name: str
    primary_language: str
    region_type: str
    source_count: int
    event_count: int
    cloudflare_collect_enabled: int = 1


@dataclass(frozen=True)
class D1Source:
    source_id: str
    target_id: str
    name: str


@dataclass(frozen=True)
class D1BackfillPlan:
    events: list[D1Event]
    targets: list[D1Target]
    sources: list[D1Source]


def _sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


_COMPACT_UTC_RE = re.compile(
    r"^(?P<date>\d{4})(?P<month>\d{2})(?P<day>\d{2})T"
    r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})Z$"
)


def _normalize_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    match = _COMPACT_UTC_RE.match(text)
    if match:
        parts = match.groupdict()
        return (
            f"{parts['date']}-{parts['month']}-{parts['day']}T"
            f"{parts['hour']}:{parts['minute']}:{parts['second']}Z"
        )
    return text


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _value_label(score: int | None) -> str:
    if score is None:
        return "待评估"
    if score >= 80:
        return "精选"
    if score >= 60:
        return "关注"
    return "普通"


def _china_relevance_label(score: int | None) -> str:
    if score is None:
        return "未知"
    if score >= 70:
        return "高"
    if score >= 40:
        return "中"
    return "低"


def _read_target_config(path: Path, target_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"target_id": target_id}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        return {"target_id": target_id}
    return loaded


def _target_primary_language(config: dict[str, Any]) -> str:
    language_scope = config.get("language_scope")
    if isinstance(language_scope, dict) and isinstance(language_scope.get("primary"), str):
        return language_scope["primary"]
    return "en"


def _target_lifecycle_status(config: dict[str, Any]) -> str:
    lifecycle = config.get("lifecycle")
    if isinstance(lifecycle, dict) and isinstance(lifecycle.get("status"), str):
        return lifecycle["status"].strip().lower()
    status = config.get("status")
    return str(status or "active").strip().lower()


def _source_ref_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("source_id", "id", "ref"):
            if isinstance(value.get(key), str):
                return value[key].strip()
    return ""


def _target_source_refs(config: dict[str, Any]) -> list[str]:
    refs = config.get("source_channel_refs")
    if not isinstance(refs, list):
        return []
    result: list[str] = []
    for item in refs:
        source_id = _source_ref_text(item)
        if source_id and source_id not in result:
            result.append(source_id)
    return result


def _target_has_source_config(targets_dir: Path, target_id: str, config: dict[str, Any]) -> bool:
    if _target_source_refs(config):
        return True
    sources_dir = targets_dir.parent / "sources" / target_id
    return sources_dir.is_dir() and any(
        path.suffix in {".yaml", ".yml"} for path in sources_dir.iterdir()
    )


def _iter_event_rows(db_path: Path) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return list(
            conn.execute(
                """
                SELECT event_id, target_id, stage, source_id, news_value_score,
                       china_relevance, classification_l0, title_original, url,
                       published_at, created_at, topic_tags, entity_names
                FROM event_index
                WHERE stage = 'drafts'
                ORDER BY datetime(COALESCE(published_at, created_at)) DESC, event_id DESC
                """
            )
        )


def collect_backfill_plan(
    *,
    data_dir: Path,
    targets_dir: Path,
    limit: int | None = None,
) -> D1BackfillPlan:
    events: list[D1Event] = []
    target_event_counts: dict[str, int] = {}
    target_source_ids: dict[str, set[str]] = {}
    source_names: dict[tuple[str, str], str] = {}

    for db_path in sorted(data_dir.glob("*/state.db")):
        rows = _iter_event_rows(db_path)
        for row in rows:
            if limit is not None and len(events) >= limit:
                break
            target_id = str(row["target_id"])
            target_config = _read_target_config(targets_dir / f"{target_id}.yaml", target_id)
            target_label = str(target_config.get("display_name") or target_id)
            source_id = str(row["source_id"] or "unknown")
            topic_tags = _split_csv(row["topic_tags"])
            issue_tags = [str(row["classification_l0"])] if row["classification_l0"] else []
            classification = {"l0": str(row["classification_l0"] or "uncategorized")}
            entities = [{"name": name} for name in _split_csv(row["entity_names"])]
            published_at = _normalize_timestamp(row["published_at"] or row["created_at"])
            collected_at = _normalize_timestamp(row["created_at"] or row["published_at"])

            events.append(
                D1Event(
                    event_id=str(row["event_id"]),
                    target_id=target_id,
                    target_label=target_label,
                    source_id=source_id,
                    source_name=source_id,
                    source_type="rss",
                    published_at=published_at,
                    collected_at=collected_at,
                    title=str(row["title_original"] or row["event_id"]),
                    original_url=str(row["url"] or ""),
                    issue_tags=issue_tags,
                    related_tags=topic_tags,
                    region_tags=[target_id],
                    entities=entities,
                    classification=classification,
                    value_label=_value_label(row["news_value_score"]),
                    value_score=row["news_value_score"],
                    china_relevance_label=_china_relevance_label(row["china_relevance"]),
                )
            )
            target_event_counts[target_id] = target_event_counts.get(target_id, 0) + 1
            target_source_ids.setdefault(target_id, set()).add(source_id)
            source_names[(target_id, source_id)] = source_id
        if limit is not None and len(events) >= limit:
            break

    configured_targets: dict[str, dict[str, Any]] = {}
    for path in sorted(targets_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        target_config = _read_target_config(path, path.stem)
        target_id = str(target_config.get("target_id") or path.stem).strip()
        if not target_id or target_id.startswith("_"):
            continue
        configured_targets[target_id] = target_config
        for source_id in _target_source_refs(target_config):
            target_source_ids.setdefault(target_id, set()).add(source_id)
            source_names.setdefault((target_id, source_id), source_id)

    targets: list[D1Target] = []
    for target_id in sorted(set(target_event_counts) | set(configured_targets)):
        target_config = configured_targets.get(target_id) or _read_target_config(
            targets_dir / f"{target_id}.yaml",
            target_id,
        )
        source_count = len(target_source_ids.get(target_id, set()))
        inactive_statuses = {"retired", "archive", "archived", "dead"}
        collect_enabled = (
            _target_lifecycle_status(target_config) not in inactive_statuses
            and _target_has_source_config(targets_dir, target_id, target_config)
        )
        targets.append(
            D1Target(
                target_id=target_id,
                display_name=str(target_config.get("display_name") or target_id),
                primary_language=_target_primary_language(target_config),
                region_type=str(target_config.get("region_type") or "country"),
                source_count=source_count,
                event_count=target_event_counts.get(target_id, 0),
                cloudflare_collect_enabled=1 if collect_enabled else 0,
            )
        )

    sources = [
        D1Source(source_id=source_id, target_id=target_id, name=name)
        for (target_id, source_id), name in sorted(source_names.items())
    ]
    return D1BackfillPlan(events=events, targets=targets, sources=sources)


def _target_insert(target: D1Target) -> str:
    return (
        "INSERT INTO targets (target_id, display_name, region_id, primary_language, "  # noqa: S608
        "region_type, source_count, event_count, lifecycle, archived, "
        "cloudflare_collect_enabled) VALUES "
        f"({_sql(target.target_id)}, {_sql(target.display_name)}, {_sql(target.target_id)}, "
        f"{_sql(target.primary_language)}, {_sql(target.region_type)}, {target.source_count}, "
        f"{target.event_count}, '{{}}', 0, {target.cloudflare_collect_enabled}) "
        "ON CONFLICT(target_id) DO UPDATE SET "
        "display_name=excluded.display_name, primary_language=excluded.primary_language, "
        "region_type=excluded.region_type, source_count=excluded.source_count, "
        "event_count=excluded.event_count, "
        "cloudflare_collect_enabled=excluded.cloudflare_collect_enabled;"
    )


def _source_insert(source: D1Source) -> str:
    return (
        "INSERT INTO sources (source_id, target_id, name, type, enabled) VALUES "  # noqa: S608
        f"({_sql(source.source_id)}, {_sql(source.target_id)}, {_sql(source.name)}, 'rss', 1) "
        "ON CONFLICT(source_id) DO UPDATE SET "
        "target_id=excluded.target_id, name=excluded.name, enabled=excluded.enabled;"
    )


def _event_insert(event: D1Event) -> str:
    columns = (
        "event_id, target_id, target_label, region_id, source_id, source_name, source_type, "
        "published_at, collected_at, title, original_title, original_url, detail_url, "
        "image_urls, tags, issue_tags, related_tags, region_tags, entities, language, "
        "pipeline_stage, value_label, value_score, china_relevance_label, classification"
    )
    values = [
        event.event_id,
        event.target_id,
        event.target_label,
        event.target_id,
        event.source_id,
        event.source_name,
        event.source_type,
        event.published_at,
        event.collected_at,
        event.title,
        event.title,
        event.original_url,
        f"/public-app/news/{event.event_id}",
        _json([]),
        _json(event.related_tags),
        _json(event.issue_tags),
        _json(event.related_tags),
        _json(event.region_tags),
        _json(event.entities),
        "mixed",
        event.pipeline_stage,
        event.value_label,
        event.value_score,
        event.china_relevance_label,
        _json(event.classification),
    ]
    preserve_zh_text = (
        "events.language = 'zh' "
        "AND COALESCE(TRIM(events.title), '') <> ''"
    )
    preserve_zh_json = (
        "events.language = 'zh' "
        "AND COALESCE(TRIM(events.{column}), '') NOT IN ('', '[]')"
    )
    assignments = (
        "target_id=excluded.target_id, target_label=excluded.target_label, "
        "region_id=excluded.region_id, source_id=excluded.source_id, "
        "source_name=excluded.source_name, "
        "source_type=excluded.source_type, published_at=excluded.published_at, "
        "collected_at=excluded.collected_at, "
        f"title=CASE WHEN {preserve_zh_text} THEN events.title ELSE excluded.title END, "
        "original_title=excluded.original_title, "
        "original_url=excluded.original_url, detail_url=excluded.detail_url, "
        f"tags=CASE WHEN {preserve_zh_json.format(column='tags')} "
        "THEN events.tags ELSE excluded.tags END, "
        f"issue_tags=CASE WHEN {preserve_zh_json.format(column='issue_tags')} "
        "THEN events.issue_tags ELSE excluded.issue_tags END, "
        f"related_tags=CASE WHEN {preserve_zh_json.format(column='related_tags')} "
        "THEN events.related_tags ELSE excluded.related_tags END, "
        f"region_tags=CASE WHEN {preserve_zh_json.format(column='region_tags')} "
        "THEN events.region_tags ELSE excluded.region_tags END, "
        "entities=excluded.entities, "
        "language=CASE WHEN events.language = 'zh' "
        "THEN events.language ELSE excluded.language END, "
        "pipeline_stage=excluded.pipeline_stage, value_label=excluded.value_label, "
        "value_score=excluded.value_score, china_relevance_label=excluded.china_relevance_label, "
        "classification=excluded.classification, "
        "updated_at=datetime('now')"
    )
    return (
        f"INSERT INTO events ({columns}) VALUES ({', '.join(_sql(value) for value in values)}) "  # noqa: S608
        f"ON CONFLICT(event_id) DO UPDATE SET {assignments};"
    )


def generate_backfill_sql(plan: D1BackfillPlan) -> str:
    statements = ["BEGIN TRANSACTION;"]
    statements.extend(_target_insert(target) for target in plan.targets)
    statements.extend(_source_insert(source) for source in plan.sources)
    statements.extend(_event_insert(event) for event in plan.events)
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--targets-dir", type=Path, default=Path("config/targets"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-sql", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = collect_backfill_plan(
        data_dir=args.data_dir,
        targets_dir=args.targets_dir,
        limit=args.limit,
    )
    print(
        f"events={len(plan.events)} targets={len(plan.targets)} sources={len(plan.sources)}",
    )
    if args.output_sql:
        args.output_sql.write_text(generate_backfill_sql(plan), encoding="utf-8")
        print(f"wrote {args.output_sql}")
    elif not args.dry_run:
        print(generate_backfill_sql(plan), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
