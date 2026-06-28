"""Generate D1 SQL to sync ready public translation fields from local state DBs."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from news_sentry.core.public_translation import public_publication_ready

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--target-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-sql", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--transaction", action="store_true")
    args = parser.parse_args()

    patches = collect_translation_patches(
        data_dir=args.data_dir,
        target_id=args.target_id,
        limit=args.limit,
    )
    targets = sorted({patch.target_id for patch in patches})
    print(f"patches={len(patches)} targets={len(targets)}")
    if args.output_sql:
        args.output_sql.write_text(
            generate_translation_backfill_sql(patches, transaction=args.transaction),
            encoding="utf-8",
        )
        print(f"wrote {args.output_sql}")
    elif not args.dry_run:
        print(generate_translation_backfill_sql(patches, transaction=args.transaction), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
