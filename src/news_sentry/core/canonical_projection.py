"""Shadow canonical projection for current NewsEvent/event_index data.

This module is deliberately not imported by the pipeline write path. It reads
existing indexed events and optionally writes a separate canonical projection.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from news_sentry.core.async_store import AsyncStore
from news_sentry.skills.filter.classification_taxonomy import canonical_l0


@dataclass(frozen=True)
class ProjectionOptions:
    target_id: str
    since: str | None = None
    limit: int = 500
    apply: bool = False
    projection_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectionCandidate:
    canonical_event_id: str
    target_id: str
    title: str
    summary: str
    event_time: str | None
    confidence: float
    mention_rows: list[dict[str, Any]] = field(default_factory=list)
    taxonomy_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectionDiagnostics:
    projection_run_id: str
    target_id: str
    mode: str
    input_events: int = 0
    canonical_events: int = 0
    mentions: int = 0
    auto_merged: int = 0
    needs_review: int = 0
    unprojectable: int = 0
    legacy_taxonomy: dict[str, str] = field(default_factory=dict)
    taxonomy_distribution: dict[str, int] = field(default_factory=dict)
    review_samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalProjectionService:
    def __init__(self, store: AsyncStore) -> None:
        self.store = store

    async def project(self, options: ProjectionOptions) -> ProjectionDiagnostics:
        rows = await self.store.list_event_index_rows_for_projection(
            target_id=options.target_id,
            limit=options.limit,
            since=options.since,
        )
        run_id = options.projection_run_id or self._run_id(options)
        diagnostics = ProjectionDiagnostics(
            projection_run_id=run_id,
            target_id=options.target_id,
            mode="apply" if options.apply else "dry_run",
            input_events=len(rows),
        )
        candidates = self._build_candidates(rows, diagnostics)
        diagnostics.canonical_events = len(candidates)
        diagnostics.mentions = sum(len(candidate.mention_rows) for candidate in candidates)
        taxonomy_values = (
            row["taxonomy_value"] for candidate in candidates for row in candidate.taxonomy_rows
        )
        diagnostics.taxonomy_distribution = dict(sorted(Counter(taxonomy_values).items()))

        if options.apply:
            await self.store.apply_canonical_projection(
                candidates=[
                    {
                        **candidate.to_dict(),
                        "status": "active",
                        "metadata": {"projection_run_id": run_id},
                    }
                    for candidate in candidates
                ],
                projection_run={
                    "projection_run_id": run_id,
                    "target_id": options.target_id,
                    "mode": diagnostics.mode,
                    "input_events": diagnostics.input_events,
                    "canonical_events": diagnostics.canonical_events,
                    "mentions": diagnostics.mentions,
                    "auto_merged": diagnostics.auto_merged,
                    "needs_review": diagnostics.needs_review,
                    "unprojectable": diagnostics.unprojectable,
                    "diagnostics": diagnostics.to_dict(),
                },
            )
        return diagnostics

    def _build_candidates(
        self,
        rows: list[dict[str, Any]],
        diagnostics: ProjectionDiagnostics,
    ) -> list[ProjectionCandidate]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            group_key = self._group_key(row)
            if not group_key:
                diagnostics.unprojectable += 1
                continue
            grouped[group_key].append(row)

        candidates: list[ProjectionCandidate] = []
        for group_rows in grouped.values():
            if len(group_rows) > 1:
                diagnostics.auto_merged += len(group_rows) - 1
            primary = group_rows[0]
            canonical_id = self._canonical_event_id(primary)
            candidate = ProjectionCandidate(
                canonical_event_id=canonical_id,
                target_id=primary["target_id"],
                title=primary.get("title") or primary["event_id"],
                summary="",
                event_time=primary.get("published_at"),
                confidence=90.0 if primary.get("url") else 72.0,
            )
            taxonomy_ids: set[str] = set()
            for row in group_rows:
                candidate.mention_rows.append(self._mention_row(canonical_id, row))
                taxonomy = self._taxonomy_row(canonical_id, row, diagnostics)
                if taxonomy and taxonomy["assignment_id"] not in taxonomy_ids:
                    candidate.taxonomy_rows.append(taxonomy)
                    taxonomy_ids.add(taxonomy["assignment_id"])
            candidates.append(candidate)
        return candidates

    def _group_key(self, row: dict[str, Any]) -> str:
        url = str(row.get("url") or "").strip().lower()
        if url:
            return f"url:{url}"
        title = str(row.get("title") or "").strip().lower()
        published_at = str(row.get("published_at") or "").strip()
        if title:
            return f"title:{published_at}:{title}"
        return ""

    def _canonical_event_id(self, row: dict[str, Any]) -> str:
        digest = hashlib.sha256(self._group_key(row).encode()).hexdigest()[:16]
        return f"ce_{row['target_id']}_{digest}"

    def _mention_row(self, canonical_event_id: str, row: dict[str, Any]) -> dict[str, Any]:
        event_id = str(row["event_id"])
        mention_key = f"{canonical_event_id}:{event_id}".encode()
        mention_digest = hashlib.sha256(mention_key).hexdigest()[:16]
        return {
            "mention_id": f"em_{mention_digest}",
            "canonical_event_id": canonical_event_id,
            "event_id": event_id,
            "target_id": row["target_id"],
            "source_id": row.get("source_id"),
            "url": row.get("url"),
            "title": row.get("title") or event_id,
            "published_at": row.get("published_at"),
            "metadata": {
                "pipeline_stage": row.get("pipeline_stage"),
                "news_value_score": row.get("news_value_score"),
                "china_relevance": row.get("china_relevance"),
                "file_path": row.get("file_path"),
            },
        }

    def _taxonomy_row(
        self,
        canonical_event_id: str,
        row: dict[str, Any],
        diagnostics: ProjectionDiagnostics,
    ) -> dict[str, Any] | None:
        raw = str(row.get("l0_category") or "").strip()
        if not raw:
            return None
        canonical = canonical_l0(raw)
        if raw != canonical:
            diagnostics.legacy_taxonomy[raw] = canonical
        assignment_key = f"{canonical_event_id}:l0:{canonical}".encode()
        assignment_digest = hashlib.sha256(assignment_key).hexdigest()[:16]
        return {
            "assignment_id": f"tax_{assignment_digest}",
            "subject_type": "canonical_event",
            "subject_id": canonical_event_id,
            "target_id": row["target_id"],
            "taxonomy_level": "l0",
            "taxonomy_value": canonical,
            "confidence": 80.0,
            "source": "projection",
            "metadata": {"raw_value": raw},
        }

    def _run_id(self, options: ProjectionOptions) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        mode = "apply" if options.apply else "dryrun"
        return f"projection_{options.target_id}_{mode}_{timestamp}"
