"""Generate D1 SQL to sync ready public translation fields from local state DBs."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from news_sentry.core.public_translation import (
    PublicTranslationConfig,
    PublicTranslationEngine,
    provider_quota_error,
    public_publication_ready,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
DEFAULT_BACKFILL_TARGETS = (
    "france",
    "south-korea",
    "india",
    "japan",
    "germany",
    "italy",
    "canada",
    "united-kingdom",
    "vietnam",
    "new-zealand",
    "ireland",
    "china-watch-en",
)
DEFAULT_BATCH_LIMIT = 200
DEFAULT_DAILY_LIMIT = 1000
DEFAULT_PER_TARGET_LIMIT = 100


@dataclass(frozen=True)
class PublicTranslationPatch:
    event_id: str
    target_id: str
    title: str
    summary: str
    recommendation_reason: str
    issue_tags: list[str]
    related_tags: list[str]
    region_tags: list[str]
    published_at: str


@dataclass(frozen=True)
class PublicTranslationGenerationResult:
    status: str
    targets: tuple[str, ...]
    total_candidates: int
    updated: int
    failed: int
    provider_quota_exhausted: bool
    target_results: list[dict[str, Any]]


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


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text and text not in items:
            items.append(text)
    return items[:8]


def _translated_title_quality_ok(title: str, original_title: str) -> bool:
    cjk_count = len(_CJK_RE.findall(title))
    if cjk_count < 4:
        return False
    original_visible = len(str(original_title or "").strip())
    if original_visible >= 24 and cjk_count < 8:
        return False
    return True


def _patch_from_row(row: sqlite3.Row) -> PublicTranslationPatch | None:
    metadata = _json_loads(row["metadata_json"])
    if not public_publication_ready(metadata):
        return None
    translation = metadata.get("translation")
    publication = metadata.get("publication")
    if not isinstance(translation, dict) or not isinstance(publication, dict):
        return None
    title = _clean_text(translation.get("title_pre"))
    summary = _clean_text(translation.get("summary_pre"))
    reason = _clean_text(publication.get("recommendation_reason"))
    issue_tags = _clean_list(publication.get("issue_tags"))
    related_tags = _clean_list(publication.get("related_tags"))
    region_tags = _clean_list(publication.get("region_tags"))
    if not title or not summary or not reason or not (issue_tags or related_tags or region_tags):
        return None
    if not _translated_title_quality_ok(title, str(row["title_original"] or "")):
        return None
    return PublicTranslationPatch(
        event_id=str(row["event_id"]),
        target_id=str(row["target_id"]),
        title=title,
        summary=summary,
        recommendation_reason=reason,
        issue_tags=issue_tags,
        related_tags=related_tags,
        region_tags=region_tags,
        published_at=str(row["published_at"] or row["created_at"] or ""),
    )


def _iter_ready_rows(db_path: Path, *, target_id: str | None = None) -> list[sqlite3.Row]:
    if target_id:
        sql = """
            SELECT event_id, target_id, stage, title_original,
                   published_at, created_at, metadata_json
            FROM event_index
            WHERE stage = 'drafts' AND public_translation_ready = 1 AND target_id = ?
            ORDER BY datetime(COALESCE(published_at, created_at)) DESC, event_id DESC
        """
        params = [target_id]
    else:
        sql = """
            SELECT event_id, target_id, stage, title_original,
                   published_at, created_at, metadata_json
            FROM event_index
            WHERE stage = 'drafts' AND public_translation_ready = 1
            ORDER BY datetime(COALESCE(published_at, created_at)) DESC, event_id DESC
        """
        params = []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute(sql, params))


def collect_translation_patches(
    *,
    data_dir: Path,
    target_id: str | None = None,
    limit: int | None = None,
) -> list[PublicTranslationPatch]:
    patches: list[PublicTranslationPatch] = []
    for db_path in sorted(data_dir.glob("*/state.db")):
        for row in _iter_ready_rows(db_path, target_id=target_id):
            patch = _patch_from_row(row)
            if patch is None:
                continue
            patches.append(patch)
            if limit is not None and len(patches) >= limit:
                return patches
    return patches


async def generate_missing_public_translations(
    *,
    data_dir: Path,
    targets: tuple[str, ...],
    limit: int,
    per_target_limit: int,
    dry_run: bool = False,
) -> PublicTranslationGenerationResult:
    from news_sentry.core.async_store import AsyncStore
    from news_sentry.core.collector_config_utils import (
        _build_ai_provider_factory,
        _create_ai_provider_router,
    )

    safe_limit = max(0, limit)
    safe_per_target = max(1, per_target_limit)
    config = PublicTranslationConfig(
        per_cycle_limit=max(1, safe_limit or 1),
        candidate_limit=max(safe_per_target, safe_limit or safe_per_target),
    )
    engine = PublicTranslationEngine(config)
    total_candidates = 0
    target_rows: dict[str, list[dict[str, Any]]] = {}
    stores: dict[str, AsyncStore] = {}
    try:
        for target in targets:
            db_path = data_dir / target / "state.db"
            if not db_path.is_file():
                target_rows[target] = []
                continue
            store = AsyncStore(db_path)
            await store.initialize()
            stores[target] = store
            rows = await store.list_public_translation_candidates(
                target,
                limit=max(safe_per_target, safe_limit or safe_per_target),
            )
            due_rows = [row for row in rows if engine.row_is_due(row)]
            target_rows[target] = due_rows[:safe_per_target]
            total_candidates += len(target_rows[target])

        if dry_run or safe_limit <= 0:
            return PublicTranslationGenerationResult(
                status="dry_run" if dry_run else "daily_limit",
                targets=targets,
                total_candidates=total_candidates,
                updated=0,
                failed=0,
                provider_quota_exhausted=False,
                target_results=[
                    {"target_id": target, "candidates": len(target_rows.get(target, []))}
                    for target in targets
                ],
            )

        router = _create_ai_provider_router()
        if router is None:
            return PublicTranslationGenerationResult(
                status="no_router",
                targets=targets,
                total_candidates=total_candidates,
                updated=0,
                failed=0,
                provider_quota_exhausted=False,
                target_results=[],
            )
        provider_factory = _build_ai_provider_factory()
        updated = 0
        failed = 0
        target_results: list[dict[str, Any]] = []
        quota_exhausted = False
        for target in targets:
            remaining = safe_limit - updated - failed
            if remaining <= 0:
                break
            rows = target_rows.get(target, [])[: min(safe_per_target, remaining)]
            if not rows:
                target_results.append(
                    {"target_id": target, "status": "empty", "updated": 0, "failed": 0}
                )
                continue
            store = stores.get(target)
            if store is None:
                target_results.append(
                    {"target_id": target, "status": "no_store", "updated": 0, "failed": 0}
                )
                continue
            target_config = PublicTranslationConfig(
                per_cycle_limit=min(safe_per_target, remaining),
                candidate_limit=max(safe_per_target, len(rows)),
            )
            result = await PublicTranslationEngine(target_config).run_rows(
                target_id=target,
                rows=rows,
                store=store,
                router=router,
                provider_factory=provider_factory,
            )
            result_updated = int(result.get("updated") or 0)
            result_failed = int(result.get("failed") or 0)
            updated += result_updated
            failed += result_failed
            status = str(result.get("status") or "unknown")
            error = str(result.get("error") or "")
            target_results.append(
                {
                    "target_id": target,
                    "status": status,
                    "updated": result_updated,
                    "failed": result_failed,
                    "error": error or None,
                }
            )
            if status == "provider_quota_exhausted" or provider_quota_error(error):
                quota_exhausted = True
                break

        if quota_exhausted:
            status = "provider_quota_exhausted"
        elif updated and failed:
            status = "partial"
        elif updated:
            status = "ok"
        elif failed:
            status = "retrying"
        else:
            status = "empty"
        return PublicTranslationGenerationResult(
            status=status,
            targets=targets,
            total_candidates=total_candidates,
            updated=updated,
            failed=failed,
            provider_quota_exhausted=quota_exhausted,
            target_results=target_results,
        )
    finally:
        for store in stores.values():
            await store.close()


def parse_target_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_BACKFILL_TARGETS
    targets = tuple(part.strip() for part in value.split(",") if part.strip())
    return targets or DEFAULT_BACKFILL_TARGETS


def limit_patches_by_targets(
    patches: list[PublicTranslationPatch],
    *,
    targets: tuple[str, ...],
    daily_limit: int,
    per_target_limit: int,
) -> list[PublicTranslationPatch]:
    by_target: dict[str, list[PublicTranslationPatch]] = {target: [] for target in targets}
    for patch in patches:
        bucket = by_target.get(patch.target_id)
        if bucket is None:
            continue
        if len(bucket) >= per_target_limit:
            continue
        bucket.append(patch)

    selected: list[PublicTranslationPatch] = []
    for target in targets:
        for patch in by_target[target]:
            if len(selected) >= daily_limit:
                return selected
            selected.append(patch)
    return selected


def _patch_update(patch: PublicTranslationPatch) -> str:
    tags = _json([*patch.issue_tags, *patch.related_tags, *patch.region_tags])
    return (
        "UPDATE events SET "  # noqa: S608
        f"title={_sql(patch.title)}, "
        f"summary={_sql(patch.summary)}, "
        f"recommendation_reason={_sql(patch.recommendation_reason)}, "
        f"tags={_sql(tags)}, "
        f"issue_tags={_sql(_json(patch.issue_tags))}, "
        f"related_tags={_sql(_json(patch.related_tags))}, "
        f"region_tags={_sql(_json(patch.region_tags))}, "
        "language='zh', "
        "updated_at=datetime('now') "
        f"WHERE event_id={_sql(patch.event_id)} "
        "AND pipeline_stage='drafts';"
    )


def generate_translation_backfill_sql(
    patches: list[PublicTranslationPatch],
    *,
    transaction: bool = False,
) -> str:
    if not patches:
        return "-- no public translation patches ready\n"
    statements = ["BEGIN TRANSACTION;"] if transaction else []
    statements.extend(_patch_update(patch) for patch in patches)
    if transaction:
        statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def execute_d1_sql(
    sql: str,
    *,
    database: str = "ns-db",
    cwd: Path = Path("frontend/cloudflare"),
) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sql", delete=False) as fh:
        fh.write(sql)
        sql_path = Path(fh.name)
    try:
        subprocess.run(
            ["npx", "wrangler", "d1", "execute", database, "--remote", "--file", str(sql_path)],
            cwd=cwd,
            check=True,
        )
    finally:
        sql_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--target-id", help="Deprecated alias for a single --targets value.")
    parser.add_argument("--targets", help="Comma-separated target priority list.")
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT)
    parser.add_argument("--per-target-limit", type=int, default=DEFAULT_PER_TARGET_LIMIT)
    parser.add_argument("--output-sql", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--generate-missing",
        action="store_true",
        help="Call configured providers to generate missing public translations before SQL export.",
    )
    parser.add_argument("--transaction", action="store_true")
    parser.add_argument("--execute-d1", action="store_true")
    parser.add_argument("--database", default="ns-db")
    args = parser.parse_args()

    targets = (args.target_id,) if args.target_id else parse_target_list(args.targets)
    generation_result: PublicTranslationGenerationResult | None = None
    if args.generate_missing:
        generation_result = asyncio.run(
            generate_missing_public_translations(
                data_dir=args.data_dir,
                targets=targets,
                limit=max(0, min(args.daily_limit, args.limit)),
                per_target_limit=max(1, args.per_target_limit),
                dry_run=args.dry_run,
            )
        )
        print(
            "generation="
            f"{generation_result.status} candidates={generation_result.total_candidates} "
            f"updated={generation_result.updated} failed={generation_result.failed} "
            f"provider_quota_exhausted={str(generation_result.provider_quota_exhausted).lower()}"
        )

    patches = collect_translation_patches(
        data_dir=args.data_dir,
        target_id=args.target_id,
        limit=None,
    )
    patches = limit_patches_by_targets(
        patches,
        targets=targets,
        daily_limit=max(0, min(args.daily_limit, args.limit)),
        per_target_limit=max(1, args.per_target_limit),
    )
    selected_targets = sorted({patch.target_id for patch in patches})
    print(
        "patches="
        f"{len(patches)} targets={len(selected_targets)} "
        f"daily_limit={args.daily_limit} limit={args.limit} "
        f"per_target_limit={args.per_target_limit}"
    )
    sql = generate_translation_backfill_sql(patches, transaction=args.transaction)
    if args.output_sql:
        args.output_sql.write_text(sql, encoding="utf-8")
        print(f"wrote {args.output_sql}")
    if args.execute_d1:
        if not patches:
            print("execute_d1=skipped reason=no_patches")
        else:
            execute_d1_sql(sql, database=args.database)
            print("execute_d1=ok")
    elif not args.dry_run and not args.output_sql:
        print(sql, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
