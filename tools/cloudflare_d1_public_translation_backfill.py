# ruff: noqa: S608
"""Generate D1 SQL to sync or create ready public translation fields."""

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
    contains_chinese,
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
DEFAULT_EVENT_TIMEOUT_SECONDS = 120.0


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
    patches: list[PublicTranslationPatch] | None = None


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


def _json_array_loads(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif not value:
        raw_items = []
    else:
        try:
            loaded = json.loads(str(value))
        except json.JSONDecodeError:
            loaded = []
        raw_items = loaded if isinstance(loaded, list) else []
    return _clean_list(raw_items)


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


def d1_candidate_query(*, targets: tuple[str, ...], limit: int) -> str:
    safe_targets = targets or DEFAULT_BACKFILL_TARGETS
    target_filter = ", ".join(_sql(target) for target in safe_targets)
    target_order = " ".join(
        f"WHEN {_sql(target)} THEN {idx}" for idx, target in enumerate(safe_targets)
    )
    safe_limit = max(1, int(limit))
    query = f"""
        SELECT event_id, target_id, source_id, source_name,
               published_at, collected_at, title, original_title, summary,
               recommendation_reason, full_content, original_url, value_score,
               classification, tags, issue_tags, related_tags, region_tags, language
        FROM events
        WHERE pipeline_stage = 'drafts'
          AND target_id IN ({target_filter})
          AND (
            language IS NULL
            OR LOWER(TRIM(language)) != 'zh'
            OR summary IS NULL
            OR TRIM(summary) = ''
            OR recommendation_reason IS NULL
            OR TRIM(recommendation_reason) = ''
          )
        ORDER BY CASE target_id {target_order} ELSE 999 END,
                 COALESCE(value_score, 0) DESC,
                 datetime(published_at) DESC,
                 event_id DESC
        LIMIT {safe_limit}
    """
    return query


def parse_wrangler_d1_json_output(output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("wrangler d1 output is not JSON") from exc
    result_sets = payload if isinstance(payload, list) else [payload]
    rows: list[dict[str, Any]] = []
    for result_set in result_sets:
        if not isinstance(result_set, dict):
            continue
        if result_set.get("success") is False:
            raise RuntimeError(f"wrangler d1 query failed: {result_set}")
        results = result_set.get("results")
        if isinstance(results, list):
            rows.extend(row for row in results if isinstance(row, dict))
    return rows


def fetch_d1_candidate_rows(
    *,
    targets: tuple[str, ...],
    limit: int,
    database: str = "ns-db",
    cwd: Path = Path("frontend/cloudflare"),
) -> list[dict[str, Any]]:
    query = d1_candidate_query(targets=targets, limit=limit)
    result = subprocess.run(
        [
            "npx",
            "wrangler",
            "d1",
            "execute",
            database,
            "--remote",
            "--command",
            query,
            "--json",
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = "\n".join(result.stderr.splitlines()[-20:])
        raise RuntimeError(f"wrangler d1 candidate query failed: {stderr}")
    return parse_wrangler_d1_json_output(result.stdout)


def _d1_row_to_translation_row(row: dict[str, Any]) -> dict[str, Any]:
    classification = _json_loads(row.get("classification"))
    title = _clean_text(row.get("title"))
    original_title = _clean_text(row.get("original_title")) or title
    summary = _clean_text(row.get("summary"))
    reason = _clean_text(row.get("recommendation_reason"))
    metadata: dict[str, Any] = {"classification": classification}
    translation: dict[str, Any] = {}
    if title and contains_chinese(title):
        translation["title_pre"] = title
    if summary and contains_chinese(summary):
        translation["summary_pre"] = summary
    if translation:
        metadata["translation"] = translation
    publication: dict[str, Any] = {}
    if reason and contains_chinese(reason):
        publication["recommendation_reason"] = reason
    for key in ("issue_tags", "related_tags", "region_tags"):
        tags = _json_array_loads(row.get(key))
        if tags:
            publication[key] = tags
    if publication:
        metadata["publication"] = publication
    return {
        "event_id": row.get("event_id"),
        "target_id": row.get("target_id"),
        "stage": "drafts",
        "source_id": row.get("source_id"),
        "source_display_name": row.get("source_name"),
        "news_value_score": row.get("value_score"),
        "classification_l0": classification.get("l0"),
        "title_original": original_title,
        "summary": summary,
        "description": summary,
        "content_original": row.get("full_content"),
        "language": row.get("language"),
        "url": row.get("original_url"),
        "published_at": row.get("published_at"),
        "created_at": row.get("collected_at") or row.get("published_at"),
        "metadata": metadata,
        "public_translation_ready": 0,
        "translation_attempts": 0,
    }


async def _d1_row_to_patch(
    row: dict[str, Any],
    *,
    engine: PublicTranslationEngine,
    router: Any,
    provider_factory: Any,
) -> PublicTranslationPatch:
    title_result = await engine._ensure_translated_field(  # noqa: SLF001
        row,
        field="title",
        router=router,
        provider_factory=provider_factory,
    )
    summary_result = await engine._ensure_translated_field(  # noqa: SLF001
        row,
        field="summary",
        router=router,
        provider_factory=provider_factory,
    )
    publication_result = await engine._generate_publication_fields(  # noqa: SLF001
        row,
        title_zh=title_result["content"],
        summary_zh=summary_result["content"],
        router=router,
        provider_factory=provider_factory,
    )
    metadata = {
        "translation": {
            "title_pre": title_result["content"],
            "summary_pre": summary_result["content"],
        },
        "publication": {
            "one_line_summary": publication_result["one_line_summary"],
            "recommendation_reason": publication_result["recommendation_reason"],
            "issue_tags": publication_result["issue_tags"],
            "related_tags": publication_result["related_tags"],
            "region_tags": publication_result["region_tags"],
        },
    }
    if not public_publication_ready(metadata):
        raise RuntimeError("public publication fields are not ready")
    return PublicTranslationPatch(
        event_id=str(row["event_id"]),
        target_id=str(row["target_id"]),
        title=title_result["content"],
        summary=summary_result["content"],
        recommendation_reason=publication_result["recommendation_reason"],
        issue_tags=list(publication_result["issue_tags"]),
        related_tags=list(publication_result["related_tags"]),
        region_tags=list(publication_result["region_tags"]),
        published_at=str(row.get("published_at") or row.get("created_at") or ""),
    )


async def generate_missing_public_translations_from_d1_rows(
    *,
    rows: list[dict[str, Any]],
    targets: tuple[str, ...],
    limit: int,
    per_target_limit: int,
    event_timeout_seconds: float = DEFAULT_EVENT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> PublicTranslationGenerationResult:
    from news_sentry.core.collector_config_utils import (
        _build_ai_provider_factory,
        _create_ai_provider_router,
    )

    safe_limit = max(0, int(limit))
    safe_per_target = max(1, int(per_target_limit))
    config = PublicTranslationConfig(
        per_cycle_limit=max(1, safe_limit or 1),
        candidate_limit=max(safe_per_target, safe_limit or safe_per_target),
    )
    engine = PublicTranslationEngine(config)
    by_target: dict[str, list[dict[str, Any]]] = {target: [] for target in targets}
    for raw_row in rows:
        mapped = _d1_row_to_translation_row(raw_row)
        target = str(mapped.get("target_id") or "")
        if target not in by_target:
            continue
        if not engine.row_is_due(mapped):
            continue
        if len(by_target[target]) >= safe_per_target:
            continue
        by_target[target].append(mapped)
    total_candidates = sum(len(items) for items in by_target.values())
    if dry_run or safe_limit <= 0:
        return PublicTranslationGenerationResult(
            status="dry_run" if dry_run else "daily_limit",
            targets=targets,
            total_candidates=total_candidates,
            updated=0,
            failed=0,
            provider_quota_exhausted=False,
            target_results=[
                {"target_id": target, "candidates": len(by_target.get(target, []))}
                for target in targets
            ],
            patches=[],
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
            patches=[],
        )
    provider_factory = _build_ai_provider_factory()
    patches: list[PublicTranslationPatch] = []
    failed = 0
    target_results: list[dict[str, Any]] = []
    quota_exhausted = False
    candidate_timeout = max(0.001, float(event_timeout_seconds))
    for target in targets:
        if len(patches) + failed >= safe_limit:
            break
        rows_for_target = by_target.get(target, [])
        print(
            "d1_generation_target="
            f"{target} candidates={len(rows_for_target)} "
            f"updated_so_far={len(patches)} failed_so_far={failed}",
            flush=True,
        )
        if not rows_for_target:
            target_results.append(
                {"target_id": target, "status": "empty", "updated": 0, "failed": 0}
            )
            continue
        target_updated = 0
        target_failed = 0
        target_error = ""
        for row in rows_for_target:
            if len(patches) + failed >= safe_limit:
                break
            try:
                patch = await asyncio.wait_for(
                    _d1_row_to_patch(
                        row,
                        engine=engine,
                        router=router,
                        provider_factory=provider_factory,
                    ),
                    timeout=candidate_timeout,
                )
            except TimeoutError:
                failed += 1
                target_failed += 1
                target_error = (
                    "event translation timed out after "
                    f"{candidate_timeout:g}s"
                )
                print(
                    "d1_generation_failure="
                    f"{target}/{row.get('event_id')} "
                    f"failed_so_far={failed} error={target_error}",
                    flush=True,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                failed += 1
                target_failed += 1
                target_error = str(exc)
                print(
                    "d1_generation_failure="
                    f"{target}/{row.get('event_id')} "
                    f"failed_so_far={failed} error={target_error[:180]}",
                    flush=True,
                )
                if provider_quota_error(target_error):
                    quota_exhausted = True
                    break
                continue
            patches.append(patch)
            target_updated += 1
            print(
                "d1_generation_patch="
                f"{target}/{patch.event_id} "
                f"updated_so_far={len(patches)} failed_so_far={failed}",
                flush=True,
            )
        if quota_exhausted:
            status = "provider_quota_exhausted"
        elif target_updated and target_failed:
            status = "partial"
        elif target_updated:
            status = "ok"
        elif target_failed:
            status = "retrying"
        else:
            status = "empty"
        target_results.append(
            {
                "target_id": target,
                "status": status,
                "updated": target_updated,
                "failed": target_failed,
                "error": target_error or None,
            }
        )
        if quota_exhausted:
            break
    if quota_exhausted:
        status = "provider_quota_exhausted"
    elif patches and failed:
        status = "partial"
    elif patches:
        status = "ok"
    elif failed:
        status = "retrying"
    else:
        status = "empty"
    return PublicTranslationGenerationResult(
        status=status,
        targets=targets,
        total_candidates=total_candidates,
        updated=len(patches),
        failed=failed,
        provider_quota_exhausted=quota_exhausted,
        target_results=target_results,
        patches=patches,
    )


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
    parser.add_argument("--source", choices=("local", "d1"), default="local")
    parser.add_argument("--d1-candidates-json", type=Path)
    parser.add_argument("--d1-candidate-limit", type=int)
    parser.add_argument("--target-id", help="Deprecated alias for a single --targets value.")
    parser.add_argument("--targets", help="Comma-separated target priority list.")
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT)
    parser.add_argument("--per-target-limit", type=int, default=DEFAULT_PER_TARGET_LIMIT)
    parser.add_argument(
        "--event-timeout-seconds",
        type=float,
        default=DEFAULT_EVENT_TIMEOUT_SECONDS,
        help="Maximum seconds to spend generating one D1 candidate event.",
    )
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
    if args.source == "d1":
        d1_candidate_limit = args.d1_candidate_limit or max(
            args.limit,
            args.per_target_limit * len(targets),
            1,
        )
        if args.d1_candidates_json:
            d1_rows = json.loads(args.d1_candidates_json.read_text(encoding="utf-8"))
            if not isinstance(d1_rows, list):
                raise RuntimeError("--d1-candidates-json must contain a JSON array")
        else:
            d1_rows = fetch_d1_candidate_rows(
                targets=targets,
                limit=d1_candidate_limit,
                database=args.database,
            )
        print(f"d1_candidates={len(d1_rows)} source=d1")
        if args.generate_missing:
            generation_result = asyncio.run(
                generate_missing_public_translations_from_d1_rows(
                    rows=d1_rows,
                    targets=targets,
                    limit=max(0, min(args.daily_limit, args.limit)),
                    per_target_limit=max(1, args.per_target_limit),
                    event_timeout_seconds=args.event_timeout_seconds,
                    dry_run=args.dry_run,
                )
            )
        patches = generation_result.patches if generation_result else []
    else:
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
    if generation_result is not None:
        print(
            "generation="
            f"{generation_result.status} candidates={generation_result.total_candidates} "
            f"updated={generation_result.updated} failed={generation_result.failed} "
            f"provider_quota_exhausted={str(generation_result.provider_quota_exhausted).lower()}"
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
