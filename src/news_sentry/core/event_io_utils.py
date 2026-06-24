"""Event I/O helpers — file loading, saving, frontmatter parsing, markdown export.

Extracted from api_server.py module-level functions.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import Response
from pydantic import ValidationError

from news_sentry.api.schemas import WebhookPayload
from news_sentry.core._state import (
    _INVISIBLE_INDEXED_EVENT,
    _PUBLIC_ANALYSIS_STAGE,
    InvisibleIndexedEvent,
)
from news_sentry.core.async_store import AsyncStore
from news_sentry.core.markdown_export import render_news_event_markdown
from news_sentry.models.newsevent import NewsEvent

logger = logging.getLogger(__name__)

# ── Late-bound / lazy imports ──
_store_for_target: Any = None
_store_has_target_event_index: Any = None
_visible_index_events_page: Any = None
_validate_target_slug: Any = None  # lazy from target_config_utils (circular via target_store_utils)


def _load_single_event(data_dir: Path, target_id: str, event_id: str) -> dict[str, Any] | None:
    """查找单个事件。"""
    drafts_dir = data_dir / target_id / "drafts"
    if not drafts_dir.is_dir():
        return None
    for md_file in drafts_dir.glob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(raw)
            if fm and fm.get("id") == event_id:
                return fm
        except Exception:  # noqa: S112
            continue
    return None



def _save_webhook_event(
    data_dir: Path,
    target_id: str,
    payload: WebhookPayload,
) -> str:
    """将 Webhook 事件写入 data/{target_id}/raw/。"""
    now = datetime.now(UTC)
    date_str = now.strftime("%Y%m%d")
    hash8 = sha256(f"{payload.source_id}{payload.url}{date_str}".encode()).hexdigest()[:8]
    event_id = f"ne-webhook-{payload.source_id}-{date_str}-{hash8}"

    raw_dir = data_dir / target_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    event_data = {
        "id": event_id,
        "run_id": "webhook",
        "source_id": payload.source_id,
        "url": payload.url,
        "title_original": payload.title_original,
        "content_original": payload.content_original,
        "language": payload.language,
        "published_at": payload.published_at or now.isoformat(),
        "collected_at": now.isoformat(),
        "pipeline_stage": "collected",
        "metadata": payload.metadata,
    }

    filepath = raw_dir / f"collected_{payload.source_id}_{event_id}.md"
    fm = yaml.dump(event_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    body = f"# {payload.title_original}\n\n{payload.content_original}\n"
    content = f"---\n{fm}---\n\n{body}"
    filepath.write_text(content, encoding="utf-8")

    return event_id



def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    """解析 YAML frontmatter。"""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
        return fm if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None



def _load_all_events(data_dir: Path, target_id: str) -> list[dict[str, Any]]:
    """从 data/{target_id}/drafts/ 读取所有事件（不分页）。"""
    drafts_dir = data_dir / target_id / "drafts"
    events: list[dict[str, Any]] = []
    if drafts_dir.is_dir():
        for md_file in sorted(drafts_dir.glob("*.md"), reverse=True):
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm = _parse_frontmatter(raw)
                if fm:
                    events.append(fm)
            except Exception:  # noqa: S112
                continue
    return events



def _draft_file_records(data_dir: Path, target_id: str) -> list[dict[str, Any]]:
    """读取 draft 文件的轻量诊断记录，不改变文件。"""
    drafts_dir = data_dir / target_id / "drafts"
    if not drafts_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for md_file in sorted(drafts_dir.glob("*.md")):
        event = _load_event_by_path(str(md_file)) or {}
        title = event.get("title_original") or event.get("title") or ""
        records.append(
            {
                "event_id": _event_id_from_frontmatter(event) or "",
                "path": str(md_file.relative_to(data_dir)),
                "title": str(title),
            }
        )
    return records



async def _draft_index_rows_for_target(
    store: AsyncStore | None,
    target_id: str,
) -> list[dict[str, Any]]:
    """读取 target drafts 索引行，用于维护诊断。"""
    if store is None or store._db is None:  # noqa: SLF001
        return []
    try:
        async with store._db.execute(  # noqa: SLF001
            "SELECT event_id, file_path, title_original "
            "FROM event_index WHERE target_id = ? AND stage = ? "
            "ORDER BY COALESCE(published_at, created_at, '') DESC",
            (target_id, _PUBLIC_ANALYSIS_STAGE),
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception:  # noqa: S112
        logger.exception("Failed to load draft index rows for target %s", target_id)
        return []
    return [
        {"event_id": str(row[0] or ""), "file_path": row[1], "title": str(row[2] or "")}
        for row in rows
    ]



async def _draft_diagnostics(data_dir: Path, target_id: str) -> dict[str, Any]:
    """生成 draft 文件与 SQLite 索引的只读一致性诊断。"""
    draft_files = _draft_file_records(data_dir, target_id)
    store = await _store_for_target(target_id)
    index_available = store is not None and await _store_has_target_event_index(store, target_id)
    index_rows = await _draft_index_rows_for_target(store, target_id) if index_available else []
    indexed_ids = {row["event_id"] for row in index_rows if row.get("event_id")}
    visible_index_count = 0
    if index_available:
        visible = await _visible_index_events_page(
            store,
            data_dir,
            target_id,
            stage=_PUBLIC_ANALYSIS_STAGE,
            page=1,
            page_size=1,
        )
        visible_index_count = int(visible["total"])

    grouped_files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in draft_files:
        event_id = item.get("event_id") or ""
        if event_id:
            grouped_files[event_id].append(item)

    duplicate_event_ids = [
        {
            "event_id": event_id,
            "count": len(items),
            "files": [item["path"] for item in items],
        }
        for event_id, items in sorted(grouped_files.items())
        if len(items) > 1
    ]
    orphan_files = [
        item
        for item in draft_files
        if index_available and (not item.get("event_id") or item.get("event_id") not in indexed_ids)
    ]
    missing_index_files = []
    for row in index_rows:
        file_path = row.get("file_path")
        if not file_path:
            continue
        if not _indexed_file_path_is_visible_in_stage(
            data_dir,
            target_id,
            _PUBLIC_ANALYSIS_STAGE,
            str(file_path),
        ):
            continue
        if not Path(str(file_path)).is_file():
            missing_index_files.append(
                {
                    "event_id": row.get("event_id") or "",
                    "path": str(file_path),
                    "title": row.get("title") or "",
                }
            )

    return {
        "target_id": target_id,
        "stage": _PUBLIC_ANALYSIS_STAGE,
        "index_available": bool(index_available),
        "draft_file_count": len(draft_files),
        "indexed_count": len(index_rows),
        "visible_index_count": visible_index_count,
        "orphan_file_count": len(orphan_files),
        "orphan_files": orphan_files,
        "duplicate_event_ids": duplicate_event_ids,
        "missing_index_file_count": len(missing_index_files),
        "missing_index_files": missing_index_files,
    }



def _relative_to_data_dir(data_dir: Path, path: Path) -> str:
    """返回面向 API 的 data_dir 相对路径。"""
    try:
        return str(path.relative_to(data_dir))
    except ValueError:
        return str(path)



def _duplicate_draft_keep_path(
    data_dir: Path,
    target_id: str,
    event_id: str,
    items: list[dict[str, Any]],
    index_rows: list[dict[str, Any]],
) -> Path:
    """从重复 draft 文件中选择要保留的 canonical 文件。"""
    candidate_paths = [data_dir / str(item["path"]) for item in items if item.get("path")]
    candidate_lookup = {path.resolve(strict=False): path for path in candidate_paths}
    drafts_dir = data_dir / target_id / "drafts"
    for row in index_rows:
        if row.get("event_id") != event_id or not row.get("file_path"):
            continue
        indexed_path = Path(str(row["file_path"]))
        if not indexed_path.is_absolute():
            indexed_path = data_dir / indexed_path
        try:
            indexed_path.relative_to(drafts_dir)
        except ValueError:
            continue
        kept = candidate_lookup.get(indexed_path.resolve(strict=False))
        if kept is not None:
            return kept

    canonical_name = f"{event_id}.md"
    for path in sorted(candidate_paths, key=lambda p: str(p)):
        if path.name == canonical_name:
            return path
    return sorted(candidate_paths, key=lambda p: str(p))[0]



def _unique_archive_path(archive_dir: Path, source_path: Path) -> Path:
    """避免归档目录内同名文件互相覆盖。"""
    candidate = archive_dir / source_path.name
    if not candidate.exists():
        return candidate
    suffix = uuid.uuid4().hex[:8]
    return archive_dir / f"{source_path.stem}-{suffix}{source_path.suffix}"



async def _archive_duplicate_drafts(
    data_dir: Path,
    target_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """将重复 event_id 的多余 draft 文件安全移动到 archive，不硬删除。"""
    _validate_target_slug(target_id)
    draft_files = _draft_file_records(data_dir, target_id)
    store = await _store_for_target(target_id)
    index_rows = await _draft_index_rows_for_target(store, target_id)
    grouped_files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in draft_files:
        event_id = item.get("event_id") or ""
        if event_id:
            grouped_files[event_id].append(item)

    duplicate_groups = {
        event_id: items for event_id, items in grouped_files.items() if len(items) > 1
    }
    archive_batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = data_dir / target_id / "archive" / "duplicate-drafts" / archive_batch
    archived_files: list[dict[str, Any]] = []
    skipped_files: list[dict[str, Any]] = []

    for event_id, items in sorted(duplicate_groups.items()):
        keep_path = _duplicate_draft_keep_path(data_dir, target_id, event_id, items, index_rows)
        for item in sorted(items, key=lambda value: str(value.get("path") or "")):
            source_path = data_dir / str(item["path"])
            if source_path.resolve(strict=False) == keep_path.resolve(strict=False):
                continue
            destination = _unique_archive_path(archive_dir, source_path)
            record = {
                "event_id": event_id,
                "source_path": _relative_to_data_dir(data_dir, source_path),
                "archived_path": _relative_to_data_dir(data_dir, destination),
                "kept_path": _relative_to_data_dir(data_dir, keep_path),
            }
            if dry_run:
                archived_files.append(record)
                continue
            if not source_path.is_file():
                skipped_files.append({**record, "reason": "source_missing"})
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination))
            archived_files.append(record)

    if archived_files and not dry_run:
        manifest_path = archive_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "target_id": target_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "archived_files": archived_files,
                    "skipped_files": skipped_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "target_id": target_id,
        "dry_run": dry_run,
        "duplicate_group_count": len(duplicate_groups),
        "archived_count": len(archived_files),
        "archived_files": archived_files,
        "skipped_files": skipped_files,
    }



def _load_event_by_path(file_path: str | None) -> dict[str, Any] | None:
    """根据 file_path 读取单个 .md 文件的 frontmatter。"""
    if file_path is None:
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return _parse_frontmatter(raw)
    except Exception:  # noqa: S112
        return None



def _load_event_by_id_from_stage(
    data_dir: Path,
    target_id: str,
    stage: str,
    event_id: str | None,
) -> dict[str, Any] | None:
    """当 SQLite file_path 失效时，从目标 stage 目录按事件 ID 找回 frontmatter。"""
    if not event_id:
        return None
    stage_dir = data_dir / target_id / stage
    if not stage_dir.is_dir():
        return None

    candidates: list[Path] = []
    id_short = event_id[:12]
    if id_short:
        candidates.extend(sorted(stage_dir.glob(f"*{id_short}*.md")))
    candidates.extend(sorted(stage_dir.glob("*.md")))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        event = _load_event_by_path(str(path))
        if event and (event.get("event_id") or event.get("id")) == event_id:
            return event
    return None



def _load_event_by_exact_id_filename(
    data_dir: Path,
    target_id: str,
    stage: str,
    event_id: str | None,
) -> dict[str, Any] | None:
    """按文件名中的完整 event_id 精确找回 frontmatter，避免全目录扫描。"""
    if not event_id:
        return None
    stage_dir = data_dir / target_id / stage
    if not stage_dir.is_dir():
        return None
    for path in sorted(stage_dir.glob(f"*{event_id}*.md")):
        event = _load_event_by_path(str(path))
        if _event_id_from_frontmatter(event) == event_id:
            return event
    return None



def _event_id_from_frontmatter(event: dict[str, Any] | None) -> str | None:
    if not event:
        return None
    value = event.get("event_id") or event.get("id")
    return str(value) if value else None



def _event_from_index_row(row: dict[str, Any]) -> dict[str, Any]:
    """当事件文件失效时，用 SQLite 索引行构造最小事件数据。"""
    event_id = row.get("event_id") or row.get("id") or ""
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    event: dict[str, Any] = {
        "id": event_id,
        "event_id": event_id,
        "source_id": row.get("source_id"),
        "url": row.get("url"),
        "title_original": row.get("title_original"),
        "published_at": row.get("published_at"),
        "created_at": row.get("created_at"),
        "news_value_score": row.get("news_value_score"),
        "china_relevance": row.get("china_relevance"),
        "sentiment": row.get("sentiment"),
        "metadata": metadata,
    }
    classification_l0 = row.get("classification_l0")
    if classification_l0:
        event["classification"] = {"l0": classification_l0}
    return {key: value for key, value in event.items() if value is not None}



def _deep_merge_mapping(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge_mapping(
                cast(dict[str, Any], existing),
                cast(dict[str, Any], value),
            )
        else:
            merged[key] = value
    return merged



def _merge_index_metadata(event: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    raw_index_metadata = row.get("metadata")
    index_metadata = (
        cast(dict[str, Any], raw_index_metadata) if isinstance(raw_index_metadata, dict) else {}
    )
    if not index_metadata:
        return event
    merged_event = dict(event)
    raw_current_metadata = merged_event.get("metadata")
    current_metadata = (
        cast(dict[str, Any], raw_current_metadata) if isinstance(raw_current_metadata, dict) else {}
    )
    merged_event["metadata"] = _deep_merge_mapping(current_metadata, index_metadata)
    return merged_event



def _markdown_download_response(filename: str, content: str) -> Response:
    """返回 Markdown attachment 响应，不触碰文件系统。"""
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    safe_name = safe_name.strip("._") or "export"
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )



def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}



def _safe_number(
    value: Any,
    *,
    integer: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if integer else number



def _safe_language(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return "mixed"
    primary = raw.split("-", maxsplit=1)[0]
    accepted = {"it", "en", "zh", "ja", "de", "fr", "mixed"}
    return primary if primary in accepted else "mixed"



def _safe_datetime_text(value: Any) -> str:
    text = str(value or "").strip()
    return text or datetime.now(UTC).isoformat()



def _safe_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback



def _news_event_from_export_data(target_id: str, data: dict[str, Any]) -> NewsEvent:
    """把 API 详情/索引投影补齐为 renderer 需要的 NewsEvent。"""
    event_id = _safe_text(data.get("id") or data.get("event_id"), "export-event")
    metadata = _safe_mapping(data.get("metadata"))
    classification = data.get("classification")
    if isinstance(classification, dict):
        metadata.setdefault("classification", classification)

    published_at = _safe_datetime_text(data.get("published_at") or data.get("created_at"))
    collected_at = _safe_datetime_text(
        data.get("collected_at") or data.get("created_at") or published_at
    )
    stage = str(data.get("pipeline_stage") or data.get("stage") or "outputted")
    if stage not in {"collected", "filtered", "judged", "outputted"}:
        stage = "outputted"

    return NewsEvent.model_validate(
        {
            "id": event_id,
            "run_id": str(data.get("run_id") or f"export-{target_id}"),
            "source_id": _safe_text(data.get("source_id"), "unknown"),
            "url": _safe_text(data.get("url"), ""),
            "title_original": _safe_text(data.get("title_original") or data.get("title"), event_id),
            "title_translated": data.get("title_translated"),
            "content_original": _safe_text(data.get("content_original") or data.get("summary"), ""),
            "content_translated": data.get("content_translated"),
            "language": _safe_language(data.get("language")),
            "published_at": published_at,
            "collected_at": collected_at,
            "pipeline_stage": stage,
            "news_value_score": _safe_number(
                data.get("news_value_score"), integer=True, minimum=0, maximum=100
            ),
            "china_relevance": _safe_number(
                data.get("china_relevance"), integer=True, minimum=0, maximum=100
            ),
            "sentiment_score": _safe_number(data.get("sentiment_score"), minimum=-1.0, maximum=1.0),
            "cluster_id": data.get("cluster_id"),
            "story_id": data.get("story_id"),
            "metadata": metadata,
        }
    )



def _render_public_event_markdown_fallback(target_id: str, event: dict[str, Any]) -> str:
    event_id = _safe_text(event.get("id") or event.get("event_id"), "export-event")
    title = _safe_text(event.get("title_original") or event.get("title"), event_id)
    source_id = _safe_text(event.get("source_id"), "unknown")
    url = _safe_text(event.get("url"), "")
    published_at = _safe_datetime_text(event.get("published_at") or event.get("created_at"))
    frontmatter = yaml.dump(
        {
            "id": event_id,
            "target_id": target_id,
            "source_id": source_id,
            "url": url,
            "title_original": title,
            "published_at": published_at,
            "pipeline_stage": "outputted",
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{frontmatter}\n---\n\n# {title}\n\n**来源:** {source_id}\n"



def _render_public_event_markdown(target_id: str, event: dict[str, Any]) -> str:
    try:
        return render_news_event_markdown(_news_event_from_export_data(target_id, event))
    except ValidationError:
        return _render_public_event_markdown_fallback(target_id, event)



def _indexed_file_path_is_visible_in_stage(
    data_dir: Path,
    target_id: str,
    stage: str,
    file_path: str | None,
) -> bool:
    """file_path 为空允许索引兜底；记录路径时必须位于预期 stage 目录。"""
    if not file_path:
        return True
    path = Path(file_path)
    try:
        path.resolve().relative_to((data_dir / target_id / stage).resolve())
    except ValueError:
        return False
    return True



def _load_indexed_event_frontmatter(
    data_dir: Path,
    target_id: str,
    stage: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """读取 SQLite 索引行对应的 frontmatter，并防止旧碰撞 file_path 污染展示。"""
    event_id = row.get("event_id")
    event_fm = _load_event_by_path(row.get("file_path"))
    if event_fm is not None and _event_id_from_frontmatter(event_fm) != event_id:
        event_fm = None
    if event_fm is None and row.get("file_path") is not None:
        event_fm = _load_event_by_id_from_stage(data_dir, target_id, stage, event_id)
    if event_fm is None and stage == "drafts":
        event_fm = _load_event_by_exact_id_filename(data_dir, target_id, "evaluated", event_id)
    return event_fm



async def _load_indexed_event_detail(
    data_dir: Path,
    target_id: str,
    store: Any,
    event_id: str,
) -> dict[str, Any] | InvisibleIndexedEvent | None:
    """从 store 读取详情，并校验 file_path 指向的 frontmatter 属于该事件。"""
    get_row = getattr(store, "get_event_index_row", None)
    if get_row is None:
        return None
    row = await get_row(target_id, event_id)
    if row is None or row.get("stage") != "drafts":
        return _INVISIBLE_INDEXED_EVENT if row is not None else None
    file_path = row.get("file_path")
    if not _indexed_file_path_is_visible_in_stage(data_dir, target_id, "drafts", file_path):
        return _INVISIBLE_INDEXED_EVENT

    if file_path is not None:
        event = _load_event_by_path(file_path)
        if event is not None and _event_id_from_frontmatter(event) == event_id:
            return _merge_index_metadata(event, row)
        event = _load_event_by_id_from_stage(data_dir, target_id, "drafts", event_id)
        if event is not None:
            return _merge_index_metadata(event, row)

    return _merge_index_metadata(_event_from_index_row(row), row)


# ── 后台自动采集循环 ──────────────────────────────────────


