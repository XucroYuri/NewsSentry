"""AsyncStore: CanonicalStoreMixin 功能域。

从 async_store.py 自动拆分。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from ._base import AsyncStoreBase
from ._ddl import (
    _CANONICAL_GRAPH_OPERATION_STATUSES,
    _CANONICAL_GRAPH_OPERATION_TYPES,
    _PRAGMA_SETUP,
    _RESEARCH_ARTIFACT_STATUSES,
    _RESEARCH_ARTIFACT_TYPES,
)


class CanonicalStoreMixin(AsyncStoreBase):
    # ------------------------------------------------------------------
    # Shadow Canonical Store
    # ------------------------------------------------------------------
    # Shadow Canonical Store
    # ------------------------------------------------------------------

    async def upsert_canonical_event(self, row: dict[str, Any]) -> str:
        """插入或更新 shadow canonical event，返回 canonical_event_id。"""
        canonical_event_id = str(row["canonical_event_id"])
        if self._db is None:
            return canonical_event_id
        await self._db.execute(
            """INSERT INTO canonical_events
               (canonical_event_id, target_id, title, summary, event_time,
                status, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_event_id) DO UPDATE SET
                   target_id = excluded.target_id,
                   title = excluded.title,
                   summary = excluded.summary,
                   event_time = excluded.event_time,
                   status = excluded.status,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                canonical_event_id,
                row["target_id"],
                row["title"],
                row.get("summary", ""),
                row.get("event_time"),
                row.get("status", "active"),
                row.get("confidence", 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return canonical_event_id

    async def upsert_event_mention(self, row: dict[str, Any]) -> str:
        """插入或更新 canonical event mention，返回 mention_id。"""
        mention_id = str(row["mention_id"])
        if self._db is None:
            return mention_id
        await self._db.execute(
            """INSERT INTO event_mentions
               (mention_id, canonical_event_id, event_id, target_id, source_id,
                url, title, published_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mention_id) DO UPDATE SET
                   canonical_event_id = excluded.canonical_event_id,
                   event_id = excluded.event_id,
                   target_id = excluded.target_id,
                   source_id = excluded.source_id,
                   url = excluded.url,
                   title = excluded.title,
                   published_at = excluded.published_at,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                mention_id,
                row["canonical_event_id"],
                row["event_id"],
                row["target_id"],
                row.get("source_id"),
                row.get("url"),
                row["title"],
                row.get("published_at"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return mention_id

    async def upsert_canonical_relation(self, row: dict[str, Any]) -> str:
        """插入或更新 canonical event relation，返回 relation_id。"""
        relation_id = str(row["relation_id"])
        if self._db is None:
            return relation_id
        await self._db.execute(
            """INSERT INTO canonical_event_relations
               (relation_id, source_canonical_event_id, target_canonical_event_id,
                relation_type, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(relation_id) DO UPDATE SET
                   source_canonical_event_id = excluded.source_canonical_event_id,
                   target_canonical_event_id = excluded.target_canonical_event_id,
                   relation_type = excluded.relation_type,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                relation_id,
                row["source_canonical_event_id"],
                row["target_canonical_event_id"],
                row["relation_type"],
                row.get("confidence", 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return relation_id

    async def upsert_taxonomy_assignment(self, row: dict[str, Any]) -> str:
        """插入或更新 taxonomy assignment，返回 assignment_id。"""
        assignment_id = str(row["assignment_id"])
        if self._db is None:
            return assignment_id
        await self._db.execute(
            """INSERT INTO taxonomy_assignments
               (assignment_id, subject_type, subject_id, target_id, taxonomy_level,
                taxonomy_value, confidence, source, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(assignment_id) DO UPDATE SET
                   subject_type = excluded.subject_type,
                   subject_id = excluded.subject_id,
                   target_id = excluded.target_id,
                   taxonomy_level = excluded.taxonomy_level,
                   taxonomy_value = excluded.taxonomy_value,
                   confidence = excluded.confidence,
                   source = excluded.source,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                assignment_id,
                row["subject_type"],
                row["subject_id"],
                row["target_id"],
                row["taxonomy_level"],
                row["taxonomy_value"],
                row.get("confidence", 0),
                row.get("source", "projection"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return assignment_id

    async def upsert_research_artifact(self, row: dict[str, Any]) -> str:
        """Insert or update a research artifact and return artifact_id."""
        artifact_id = str(row["artifact_id"])
        target_id = str(row["target_id"])
        artifact_type = str(row.get("artifact_type", ""))
        subject_type = str(row.get("subject_type", "canonical_event"))
        subject_id = str(row.get("subject_id", ""))
        status = str(row.get("status", "open"))
        if artifact_type not in _RESEARCH_ARTIFACT_TYPES:
            raise ValueError(f"Unsupported research artifact type: {artifact_type}")
        if status not in _RESEARCH_ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported research artifact status: {status}")
        if subject_type != "canonical_event":
            raise ValueError("research artifact subject_type must be canonical_event")
        if self._db is None:
            return artifact_id
        async with self._db.execute(
            """SELECT target_id, artifact_type, subject_type, subject_id, status, metadata_json
               FROM research_artifacts
               WHERE artifact_id = ?""",
            (artifact_id,),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            (
                existing_target,
                existing_type,
                existing_subject_type,
                existing_subject_id,
                existing_status,
                existing_metadata_json,
            ) = existing
            if (
                existing_target != target_id
                or existing_type != artifact_type
                or existing_subject_type != subject_type
                or existing_subject_id != subject_id
            ):
                raise ValueError(
                    "research artifact_id cannot change target_id, artifact_type, "
                    "subject_type, or subject_id"
                )
            existing_metadata = self._json_loads(existing_metadata_json)
            incoming_metadata = row.get("metadata")
            incoming_metadata = incoming_metadata if isinstance(incoming_metadata, dict) else {}
            if (
                existing_type in {"merge_decision", "split_decision"}
                and existing_status == "resolved"
                and existing_metadata.get("applied_operation_id")
                and (
                    status != "resolved"
                    or incoming_metadata.get("applied_operation_id")
                    != existing_metadata.get("applied_operation_id")
                )
            ):
                raise ValueError(
                    "applied research artifact cannot be reopened or detach applied operation"
                )
        if not subject_id:
            raise ValueError("research artifact canonical_event subject_id is required")
        async with self._db.execute(
            "SELECT target_id FROM canonical_events WHERE canonical_event_id = ?",
            (subject_id,),
        ) as cursor:
            subject = await cursor.fetchone()
        if subject is None:
            raise ValueError(f"research artifact canonical_event not found: {subject_id}")
        if subject[0] != target_id:
            raise ValueError(
                "research artifact canonical_event target mismatch: "
                f"{subject_id} belongs to {subject[0]}, not {target_id}"
            )
        canonical_event_ids = row.get("canonical_event_ids")
        if canonical_event_ids is None:
            canonical_event_ids = row.get("canonical_event_ids_json", [])
        canonical_event_ids_json = json.dumps(
            canonical_event_ids if isinstance(canonical_event_ids, list) else [],
            ensure_ascii=False,
            sort_keys=True,
        )
        await self._db.execute(
            """INSERT INTO research_artifacts
               (artifact_id, target_id, artifact_type, title, body, subject_type,
                subject_id, canonical_event_ids_json, status, visibility, created_by,
                metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(artifact_id) DO UPDATE SET
                   title = excluded.title,
                   body = excluded.body,
                   canonical_event_ids_json = excluded.canonical_event_ids_json,
                   status = excluded.status,
                   visibility = excluded.visibility,
                   created_by = excluded.created_by,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                artifact_id,
                target_id,
                artifact_type,
                row["title"],
                row.get("body", ""),
                subject_type,
                subject_id,
                canonical_event_ids_json,
                status,
                row.get("visibility", "local_private"),
                row.get("created_by", "local-user"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await self._db.commit()
        return artifact_id

    async def get_research_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT artifact_id, target_id, artifact_type, title, body, subject_type,
                      subject_id, canonical_event_ids_json, status, visibility, created_by,
                      metadata_json, created_at, updated_at
               FROM research_artifacts
               WHERE artifact_id = ?""",
            (artifact_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._research_artifact_from_row(row)

    async def list_research_artifacts(
        self,
        *,
        target_id: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        artifact_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            """SELECT artifact_id, target_id, artifact_type, title, body, subject_type,
                      subject_id, canonical_event_ids_json, status, visibility, created_by,
                      metadata_json, created_at, updated_at
               FROM research_artifacts
               WHERE target_id = ?
                 AND (? IS NULL OR subject_type = ?)
                 AND (? IS NULL OR subject_id = ?)
                 AND (? IS NULL OR artifact_type = ?)
                 AND (? IS NULL OR status = ?)
               ORDER BY updated_at DESC, created_at DESC, artifact_id DESC
               LIMIT ? OFFSET ?""",
            (
                target_id,
                subject_type,
                subject_type,
                subject_id,
                subject_id,
                artifact_type,
                artifact_type,
                status,
                status,
                limit,
                offset,
            ),
        )
        return [self._research_artifact_from_row(row) for row in rows]

    async def record_canonical_graph_operation(self, row: dict[str, Any]) -> str:
        """Record an idempotent canonical graph operation and return operation_id."""
        operation_id = str(row["operation_id"])
        operation_type = str(row.get("operation_type", ""))
        status = str(row.get("status", "applied"))
        if operation_type not in _CANONICAL_GRAPH_OPERATION_TYPES:
            raise ValueError(f"Unsupported canonical graph operation type: {operation_type}")
        if status not in _CANONICAL_GRAPH_OPERATION_STATUSES:
            raise ValueError(f"Unsupported canonical graph operation status: {status}")
        if self._db is None:
            return operation_id
        decision_artifact_id = row.get("decision_artifact_id")
        if decision_artifact_id is not None:
            async with self._db.execute(
                """SELECT operation_id
                   FROM canonical_graph_operations
                   WHERE target_id = ?
                     AND decision_artifact_id = ?
                   LIMIT 1""",
                (row["target_id"], decision_artifact_id),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                return str(existing[0])
        changes = row.get("changes", [])
        warnings = row.get("warnings", [])
        try:
            await self._db.execute(
                """INSERT INTO canonical_graph_operations
                   (operation_id, target_id, operation_type, decision_artifact_id,
                    primary_canonical_event_id, result_canonical_event_id, status,
                    changes_json, warnings_json, metadata_json, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(operation_id) DO NOTHING""",
                (
                    operation_id,
                    row["target_id"],
                    operation_type,
                    decision_artifact_id,
                    row["primary_canonical_event_id"],
                    row.get("result_canonical_event_id"),
                    status,
                    json.dumps(changes if isinstance(changes, list) else [], ensure_ascii=False),
                    json.dumps(warnings if isinstance(warnings, list) else [], ensure_ascii=False),
                    self._json_dumps(row.get("metadata")),
                    row.get("created_by", "local-user"),
                ),
            )
            await self._db.commit()
        except sqlite3.IntegrityError:
            await self._db.rollback()
            if decision_artifact_id is None:
                raise
            async with self._db.execute(
                """SELECT operation_id
                   FROM canonical_graph_operations
                   WHERE target_id = ?
                     AND decision_artifact_id = ?
                   LIMIT 1""",
                (row["target_id"], decision_artifact_id),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                raise
            return str(existing[0])
        return operation_id

    async def get_canonical_graph_operation(self, operation_id: str) -> dict[str, Any] | None:
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT operation_id, target_id, operation_type, decision_artifact_id,
                      primary_canonical_event_id, result_canonical_event_id, status,
                      changes_json, warnings_json, metadata_json, created_by, created_at
               FROM canonical_graph_operations
               WHERE operation_id = ?""",
            (operation_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else self._canonical_graph_operation_from_row(row)

    async def list_canonical_graph_operations(
        self,
        *,
        target_id: str,
        operation_type: str | None = None,
        decision_artifact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        if operation_type is not None and operation_type not in _CANONICAL_GRAPH_OPERATION_TYPES:
            raise ValueError(f"Unsupported canonical graph operation type: {operation_type}")
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        rows = await self._db.execute_fetchall(
            """SELECT operation_id, target_id, operation_type, decision_artifact_id,
                      primary_canonical_event_id, result_canonical_event_id, status,
                      changes_json, warnings_json, metadata_json, created_by, created_at
               FROM canonical_graph_operations
               WHERE target_id = ?
                 AND (? IS NULL OR operation_type = ?)
                 AND (? IS NULL OR decision_artifact_id = ?)
               ORDER BY created_at DESC, operation_id DESC
               LIMIT ? OFFSET ?""",
            (
                target_id,
                operation_type,
                operation_type,
                decision_artifact_id,
                decision_artifact_id,
                safe_limit,
                safe_offset,
            ),
        )
        return [self._canonical_graph_operation_from_row(row) for row in rows]

    async def preview_canonical_merge(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        decision_artifact_id: str | None = None,
        created_by: str = "local-user",
        title_override: str | None = None,
        summary_override: str | None = None,
    ) -> dict[str, Any]:
        """Preview a human-approved canonical merge without changing storage."""
        return await self._canonical_merge_result(
            target_id=target_id,
            survivor_canonical_event_id=survivor_canonical_event_id,
            merged_canonical_event_ids=merged_canonical_event_ids,
            decision_artifact_id=decision_artifact_id,
            created_by=created_by,
            title_override=title_override,
            summary_override=summary_override,
            apply=False,
        )

    async def apply_canonical_merge(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        decision_artifact_id: str | None = None,
        created_by: str = "local-user",
        title_override: str | None = None,
        summary_override: str | None = None,
    ) -> dict[str, Any]:
        """Apply an idempotent canonical merge decision."""
        return await self._canonical_merge_result(
            target_id=target_id,
            survivor_canonical_event_id=survivor_canonical_event_id,
            merged_canonical_event_ids=merged_canonical_event_ids,
            decision_artifact_id=decision_artifact_id,
            created_by=created_by,
            title_override=title_override,
            summary_override=summary_override,
            apply=True,
        )

    async def _canonical_merge_result(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        decision_artifact_id: str | None,
        created_by: str,
        title_override: str | None,
        summary_override: str | None,
        apply: bool,
    ) -> dict[str, Any]:
        if self._db is None:
            await self.initialize()
        assert self._db is not None

        survivor_id = str(survivor_canonical_event_id)
        merged_ids = self._dedupe_canonical_event_ids(merged_canonical_event_ids)
        if not merged_ids:
            raise ValueError("canonical merge requires at least one merged canonical event")
        if survivor_id in merged_ids:
            raise ValueError("survivor canonical event cannot appear in merged list")

        operation_id = self._canonical_merge_operation_id(
            target_id=target_id,
            survivor_canonical_event_id=survivor_id,
            merged_canonical_event_ids=merged_ids,
            decision_artifact_id=decision_artifact_id,
            title_override=title_override,
            summary_override=summary_override,
        )

        if not apply:
            plan = await self._build_canonical_merge_plan(
                target_id=target_id,
                survivor_canonical_event_id=survivor_id,
                merged_canonical_event_ids=merged_ids,
                operation_id=operation_id,
                decision_artifact_id=decision_artifact_id,
                created_by=created_by,
                title_override=title_override,
                summary_override=summary_override,
            )
            return self._canonical_merge_response_from_plan(plan, mode="dry_run")

        await self._db.execute("BEGIN IMMEDIATE")
        try:
            plan = await self._build_canonical_merge_plan(
                target_id=target_id,
                survivor_canonical_event_id=survivor_id,
                merged_canonical_event_ids=merged_ids,
                operation_id=operation_id,
                decision_artifact_id=decision_artifact_id,
                created_by=created_by,
                title_override=title_override,
                summary_override=summary_override,
            )
            existing_operation = await self._find_existing_canonical_merge_operation(
                operation_id=operation_id,
                target_id=target_id,
                decision_artifact_id=decision_artifact_id,
                artifact=plan["artifact"],
                survivor_canonical_event_id=survivor_id,
                merged_canonical_event_ids=merged_ids,
                title_override=title_override,
                summary_override=summary_override,
            )
            if existing_operation is not None:
                await self._db.commit()
                return self._canonical_merge_response_from_operation(
                    existing_operation,
                    mode="applied",
                )

            await self._apply_canonical_merge_plan(plan)
            await self._db.commit()
            return self._canonical_merge_response_from_plan(plan, mode="applied")
        except Exception:
            await self._db.rollback()
            raise

    @staticmethod
    def _dedupe_canonical_event_ids(canonical_event_ids: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for raw_id in canonical_event_ids:
            canonical_event_id = str(raw_id)
            if canonical_event_id in seen:
                continue
            seen.add(canonical_event_id)
            deduped.append(canonical_event_id)
        return deduped

    @staticmethod
    def _canonical_merge_operation_id(
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        decision_artifact_id: str | None,
        title_override: str | None,
        summary_override: str | None,
    ) -> str:
        payload = {
            "target_id": target_id,
            "operation_type": "merge",
            "survivor_canonical_event_id": survivor_canonical_event_id,
            "merged_canonical_event_ids": sorted(
                {str(item) for item in merged_canonical_event_ids}
            ),
            "decision_artifact_id": decision_artifact_id,
            "title_override": title_override,
            "summary_override": summary_override,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        return f"cgo-{target_id}-merge-{digest}"

    async def _build_canonical_merge_plan(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        operation_id: str,
        decision_artifact_id: str | None,
        created_by: str,
        title_override: str | None,
        summary_override: str | None,
    ) -> dict[str, Any]:
        survivor = await self._load_canonical_event_for_merge(
            survivor_canonical_event_id,
            target_id=target_id,
        )
        merged_events = [
            await self._load_canonical_event_for_merge(merged_id, target_id=target_id)
            for merged_id in merged_canonical_event_ids
        ]
        warnings: list[dict[str, Any]] = []
        for event in merged_events:
            metadata = event["metadata"]
            merged_into = metadata.get("merged_into")
            if event["status"] == "merged" and merged_into == survivor_canonical_event_id:
                warnings.append(
                    {
                        "type": "already_merged",
                        "canonical_event_id": event["canonical_event_id"],
                    }
                )
                continue
            if event["status"] == "merged" and merged_into != survivor_canonical_event_id:
                raise ValueError(
                    "canonical event already merged into another survivor: "
                    f"{event['canonical_event_id']}"
                )

        artifact = None
        if decision_artifact_id is not None:
            artifact = await self.get_research_artifact(decision_artifact_id)
            self._validate_merge_decision_artifact(
                artifact=artifact,
                target_id=target_id,
                survivor_canonical_event_id=survivor_canonical_event_id,
                merged_canonical_event_ids=merged_canonical_event_ids,
            )

        mention_counts = await self._count_merge_mentions_by_event(merged_canonical_event_ids)
        changes: list[dict[str, Any]] = [
            {
                "type": "move_mentions",
                "from_canonical_event_ids": list(merged_canonical_event_ids),
                "to_canonical_event_id": survivor_canonical_event_id,
                "mention_count": sum(mention_counts.values()),
                "mention_counts": {
                    canonical_event_id: mention_counts.get(canonical_event_id, 0)
                    for canonical_event_id in merged_canonical_event_ids
                },
            },
            {
                "type": "mark_merged",
                "canonical_event_ids": list(merged_canonical_event_ids),
                "merged_into": survivor_canonical_event_id,
            },
            {
                "type": "create_duplicate_relations",
                "relation_count": len(merged_canonical_event_ids),
            },
            {
                "type": "update_survivor_metadata",
                "canonical_event_id": survivor_canonical_event_id,
            },
        ]
        if artifact is not None:
            changes.append(
                {
                    "type": "resolve_research_artifact",
                    "artifact_id": decision_artifact_id,
                }
            )
        events = {
            "survivor": {
                "canonical_event_id": survivor_canonical_event_id,
                "status": survivor["status"],
            },
            "merged": [
                {
                    "canonical_event_id": event["canonical_event_id"],
                    "status": event["status"],
                    "merged_into": event["metadata"].get("merged_into"),
                }
                for event in merged_events
            ],
        }
        return {
            "operation_id": operation_id,
            "target_id": target_id,
            "operation_type": "merge",
            "decision_artifact_id": decision_artifact_id,
            "survivor": survivor,
            "merged_events": merged_events,
            "changes": changes,
            "warnings": warnings,
            "events": events,
            "artifact": artifact,
            "created_by": created_by,
            "title_override": title_override,
            "summary_override": summary_override,
        }

    async def _load_canonical_event_for_merge(
        self,
        canonical_event_id: str,
        *,
        target_id: str,
    ) -> dict[str, Any]:
        event = await self.get_canonical_event(canonical_event_id)
        if event is None:
            raise ValueError(f"canonical event not found: {canonical_event_id}")
        if event["target_id"] != target_id:
            raise ValueError(
                "canonical event target mismatch: "
                f"{canonical_event_id} belongs to {event['target_id']}, not {target_id}"
            )
        return event

    @staticmethod
    def _validate_merge_decision_artifact(
        *,
        artifact: dict[str, Any] | None,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
    ) -> None:
        if artifact is None:
            raise ValueError("merge decision artifact not found")
        if artifact["target_id"] != target_id:
            raise ValueError(
                f"merge decision artifact target mismatch: {artifact['target_id']} != {target_id}"
            )
        if artifact["artifact_type"] != "merge_decision":
            raise ValueError("merge decision artifact_type must be merge_decision")
        if artifact["subject_id"] != survivor_canonical_event_id:
            raise ValueError(
                "merge decision artifact subject mismatch: "
                f"{artifact['subject_id']} != {survivor_canonical_event_id}"
            )
        candidate_ids = artifact["metadata"].get("candidate_canonical_event_ids", [])
        candidate_ids = candidate_ids if isinstance(candidate_ids, list) else []
        candidate_set = CanonicalStoreMixin._canonical_merge_event_ids(candidate_ids)
        merged_set = CanonicalStoreMixin._canonical_merge_event_ids(merged_canonical_event_ids)
        if candidate_set != merged_set:
            raise ValueError("merge decision artifact candidates must match merged ids")
        missing = [
            canonical_event_id
            for canonical_event_id in merged_canonical_event_ids
            if canonical_event_id not in candidate_set
        ]
        if missing:
            raise ValueError(
                "merge decision artifact candidates do not cover merged ids: " + ", ".join(missing)
            )

    async def _count_merge_mentions_by_event(
        self,
        canonical_event_ids: Sequence[str],
    ) -> dict[str, int]:
        db = await self._ensure_db()
        counts: dict[str, int] = {}
        for canonical_event_id in canonical_event_ids:
            rows = list(
                await db.execute_fetchall(
                    """SELECT COUNT(*)
                       FROM event_mentions
                       WHERE canonical_event_id = ?""",
                    (canonical_event_id,),
                )
            )
            counts[canonical_event_id] = int(rows[0][0] or 0)
        return counts

    async def _find_existing_canonical_merge_operation(
        self,
        *,
        operation_id: str,
        target_id: str,
        decision_artifact_id: str | None,
        artifact: dict[str, Any] | None,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        title_override: str | None,
        summary_override: str | None,
    ) -> dict[str, Any] | None:
        def ensure_matching(operation: dict[str, Any], operation_label: str) -> dict[str, Any]:
            if not self._canonical_merge_operation_matches(
                operation,
                target_id=target_id,
                decision_artifact_id=decision_artifact_id,
                survivor_canonical_event_id=survivor_canonical_event_id,
                merged_canonical_event_ids=merged_canonical_event_ids,
                title_override=title_override,
                summary_override=summary_override,
            ):
                raise ValueError(
                    "applied operation mismatch: "
                    f"{operation_label} does not match merge artifact {decision_artifact_id}"
                )
            return operation

        artifact_operation_id = None
        if artifact is not None:
            artifact_operation_id = artifact["metadata"].get("applied_operation_id")
        if artifact_operation_id:
            operation = await self.get_canonical_graph_operation(str(artifact_operation_id))
            if operation is not None:
                return ensure_matching(operation, str(artifact_operation_id))
        operation = await self.get_canonical_graph_operation(operation_id)
        if operation is not None:
            return ensure_matching(operation, operation_id)
        if decision_artifact_id is None:
            return None
        db = await self._ensure_db()
        rows = list(
            await db.execute_fetchall(
                """SELECT operation_id, target_id, operation_type, decision_artifact_id,
                          primary_canonical_event_id, result_canonical_event_id, status,
                          changes_json, warnings_json, metadata_json, created_by, created_at
                   FROM canonical_graph_operations
                   WHERE target_id = ? AND decision_artifact_id = ?
                   LIMIT 1""",
                (target_id, decision_artifact_id),
            )
        )
        if not rows:
            return None
        existing = self._canonical_graph_operation_from_row(rows[0])
        return ensure_matching(existing, str(existing["operation_id"]))

    @staticmethod
    def _canonical_merge_event_ids(canonical_event_ids: Sequence[str]) -> list[str]:
        return sorted({str(item) for item in canonical_event_ids if str(item)})

    @staticmethod
    def _merge_operation_metadata_ids(metadata: dict[str, Any]) -> list[str]:
        metadata_ids = metadata.get("merged_canonical_event_ids")
        if isinstance(metadata_ids, list):
            return CanonicalStoreMixin._canonical_merge_event_ids(metadata_ids)
        events = metadata.get("events", {})
        if not isinstance(events, dict):
            return []
        merged = events.get("merged", [])
        if not isinstance(merged, list):
            return []
        return CanonicalStoreMixin._canonical_merge_event_ids(
            [
                str(event["canonical_event_id"])
                for event in merged
                if isinstance(event, dict) and event.get("canonical_event_id")
            ]
        )

    @staticmethod
    def _merge_operation_metadata_survivor_id(metadata: dict[str, Any]) -> str | None:
        metadata_survivor = metadata.get("survivor_canonical_event_id")
        if metadata_survivor:
            return str(metadata_survivor)
        events = metadata.get("events", {})
        if not isinstance(events, dict):
            return None
        survivor = events.get("survivor", {})
        if not isinstance(survivor, dict):
            return None
        survivor_id = survivor.get("canonical_event_id")
        return str(survivor_id) if survivor_id else None

    @staticmethod
    def _canonical_merge_operation_matches(
        operation: dict[str, Any],
        *,
        target_id: str,
        decision_artifact_id: str | None,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: Sequence[str],
        title_override: str | None,
        summary_override: str | None,
    ) -> bool:
        if (
            operation["target_id"] != target_id
            or operation["operation_type"] != "merge"
            or operation["decision_artifact_id"] != decision_artifact_id
            or operation["primary_canonical_event_id"] != survivor_canonical_event_id
            or operation["result_canonical_event_id"] != survivor_canonical_event_id
        ):
            return False

        metadata = operation.get("metadata", {})
        metadata_survivor_id = CanonicalStoreMixin._merge_operation_metadata_survivor_id(metadata)
        if metadata_survivor_id is not None and metadata_survivor_id != survivor_canonical_event_id:
            return False
        if metadata.get("title_override") != title_override:
            return False
        if metadata.get("summary_override") != summary_override:
            return False
        metadata_merged_ids = CanonicalStoreMixin._merge_operation_metadata_ids(metadata)
        request_merged_ids = CanonicalStoreMixin._canonical_merge_event_ids(
            merged_canonical_event_ids
        )
        return metadata_merged_ids == request_merged_ids

    async def _apply_canonical_merge_plan(self, plan: dict[str, Any]) -> None:
        db = await self._ensure_db()
        operation_id = plan["operation_id"]
        target_id = plan["target_id"]
        survivor_id = plan["survivor"]["canonical_event_id"]
        merged_ids = [event["canonical_event_id"] for event in plan["merged_events"]]
        for merged_id in merged_ids:
            await db.execute(
                """UPDATE event_mentions
                   SET canonical_event_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE target_id = ? AND canonical_event_id = ?""",
                (survivor_id, target_id, merged_id),
            )

        for event in plan["merged_events"]:
            metadata = dict(event["metadata"])
            metadata.setdefault("previous_status", event["status"])
            metadata["merged_into"] = survivor_id
            metadata["merged_operation_id"] = operation_id
            await db.execute(
                """UPDATE canonical_events
                   SET status = 'merged',
                       metadata_json = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE canonical_event_id = ? AND target_id = ?""",
                (self._json_dumps(metadata), event["canonical_event_id"], target_id),
            )
            await db.execute(
                """INSERT INTO canonical_event_relations
                   (relation_id, source_canonical_event_id, target_canonical_event_id,
                    relation_type, confidence, metadata_json)
                   VALUES (?, ?, ?, 'duplicate', ?, ?)
                   ON CONFLICT(relation_id) DO UPDATE SET
                       source_canonical_event_id = excluded.source_canonical_event_id,
                       target_canonical_event_id = excluded.target_canonical_event_id,
                       relation_type = excluded.relation_type,
                       confidence = excluded.confidence,
                       metadata_json = excluded.metadata_json,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    self._canonical_merge_relation_id(operation_id, event["canonical_event_id"]),
                    event["canonical_event_id"],
                    survivor_id,
                    100,
                    self._json_dumps(
                        {
                            "operation_id": operation_id,
                            "reason": "canonical_merge",
                        }
                    ),
                ),
            )

        survivor_stats = await self._canonical_survivor_mention_stats(survivor_id)
        survivor_metadata = dict(plan["survivor"]["metadata"])
        survivor_metadata["mention_count"] = survivor_stats["mention_count"]
        survivor_metadata["source_count"] = survivor_stats["source_count"]
        if survivor_stats["last_seen_at"] is not None:
            survivor_metadata["last_seen_at"] = survivor_stats["last_seen_at"]
        survivor_metadata["last_graph_operation_id"] = operation_id
        survivor_title = plan["title_override"]
        survivor_summary = plan["summary_override"]
        await db.execute(
            """UPDATE canonical_events
               SET title = ?,
                   summary = ?,
                   metadata_json = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE canonical_event_id = ? AND target_id = ?""",
            (
                survivor_title if survivor_title is not None else plan["survivor"]["title"],
                survivor_summary if survivor_summary is not None else plan["survivor"]["summary"],
                self._json_dumps(survivor_metadata),
                survivor_id,
                target_id,
            ),
        )

        artifact = plan["artifact"]
        if artifact is not None:
            artifact_metadata = dict(artifact["metadata"])
            artifact_metadata["applied_operation_id"] = operation_id
            artifact_metadata["applied_at"] = datetime.now(UTC).isoformat()
            artifact_metadata["applied_by"] = plan["created_by"]
            await db.execute(
                """UPDATE research_artifacts
                   SET status = 'resolved',
                       metadata_json = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE artifact_id = ? AND target_id = ?""",
                (self._json_dumps(artifact_metadata), artifact["artifact_id"], target_id),
            )

        await db.execute(
            """INSERT INTO canonical_graph_operations
               (operation_id, target_id, operation_type, decision_artifact_id,
                primary_canonical_event_id, result_canonical_event_id, status,
                changes_json, warnings_json, metadata_json, created_by)
               VALUES (?, ?, 'merge', ?, ?, ?, 'applied', ?, ?, ?, ?)
               ON CONFLICT(operation_id) DO NOTHING""",
            (
                operation_id,
                target_id,
                plan["decision_artifact_id"],
                survivor_id,
                survivor_id,
                json.dumps(plan["changes"], ensure_ascii=False),
                json.dumps(plan["warnings"], ensure_ascii=False),
                self._json_dumps(
                    {
                        "events": plan["events"],
                        "survivor_canonical_event_id": survivor_id,
                        "merged_canonical_event_ids": sorted(merged_ids),
                        "title_override": plan["title_override"],
                        "summary_override": plan["summary_override"],
                    }
                ),
                plan["created_by"],
            ),
        )

    @staticmethod
    def _canonical_merge_relation_id(operation_id: str, merged_canonical_event_id: str) -> str:
        digest = hashlib.sha256(f"{operation_id}:{merged_canonical_event_id}".encode()).hexdigest()[
            :12
        ]
        return f"rel-{operation_id}-{digest}"

    async def _canonical_survivor_mention_stats(
        self,
        survivor_canonical_event_id: str,
    ) -> dict[str, Any]:
        db = await self._ensure_db()
        rows = list(
            await db.execute_fetchall(
                """SELECT COUNT(*), COUNT(DISTINCT source_id),
                          MAX(COALESCE(published_at, updated_at, created_at))
                   FROM event_mentions
                   WHERE canonical_event_id = ?""",
                (survivor_canonical_event_id,),
            )
        )
        if not rows:
            return {"mention_count": 0, "source_count": 0, "last_seen_at": None}
        row = rows[0]
        return {
            "mention_count": int(row[0] or 0),
            "source_count": int(row[1] or 0),
            "last_seen_at": row[2],
        }

    @staticmethod
    def _canonical_merge_response_from_plan(
        plan: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        return {
            "mode": mode,
            "operation_id": plan["operation_id"],
            "target_id": plan["target_id"],
            "operation_type": plan["operation_type"],
            "changes": plan["changes"],
            "warnings": plan["warnings"],
            "events": plan["events"],
        }

    @staticmethod
    def _canonical_merge_response_from_operation(
        operation: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        metadata = operation.get("metadata", {})
        return {
            "mode": mode,
            "operation_id": operation["operation_id"],
            "target_id": operation["target_id"],
            "operation_type": operation["operation_type"],
            "changes": operation.get("changes", []),
            "warnings": operation.get("warnings", []),
            "events": metadata.get("events", {}),
        }

    async def preview_canonical_split(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        decision_artifact_id: str | None = None,
        created_by: str = "local-user",
        new_title: str | None = None,
        new_summary: str | None = None,
    ) -> dict[str, Any]:
        """Preview a human-approved canonical split without changing storage."""
        return await self._canonical_split_result(
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
            decision_artifact_id=decision_artifact_id,
            created_by=created_by,
            new_title=new_title,
            new_summary=new_summary,
            apply=False,
        )

    async def apply_canonical_split(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        decision_artifact_id: str | None = None,
        created_by: str = "local-user",
        new_title: str | None = None,
        new_summary: str | None = None,
    ) -> dict[str, Any]:
        """Apply an idempotent canonical split decision."""
        return await self._canonical_split_result(
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
            decision_artifact_id=decision_artifact_id,
            created_by=created_by,
            new_title=new_title,
            new_summary=new_summary,
            apply=True,
        )

    async def _canonical_split_result(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        decision_artifact_id: str | None,
        created_by: str,
        new_title: str | None,
        new_summary: str | None,
        apply: bool,
    ) -> dict[str, Any]:
        if self._db is None:
            await self.initialize()
        assert self._db is not None

        source_id = str(source_canonical_event_id)
        affected_ids = self._dedupe_canonical_event_ids(affected_mention_ids)
        if not affected_ids:
            raise ValueError("canonical split requires at least one affected mention")

        operation_id = self._canonical_split_operation_id(
            target_id=target_id,
            source_canonical_event_id=source_id,
            affected_mention_ids=affected_ids,
            decision_artifact_id=decision_artifact_id,
            new_title=new_title,
            new_summary=new_summary,
        )
        created_id = self._canonical_split_created_event_id(
            target_id=target_id,
            source_canonical_event_id=source_id,
            affected_mention_ids=affected_ids,
            decision_artifact_id=decision_artifact_id,
        )

        if not apply:
            plan = await self._build_canonical_split_plan(
                target_id=target_id,
                source_canonical_event_id=source_id,
                affected_mention_ids=affected_ids,
                created_canonical_event_id=created_id,
                operation_id=operation_id,
                decision_artifact_id=decision_artifact_id,
                created_by=created_by,
                new_title=new_title,
                new_summary=new_summary,
            )
            return self._canonical_split_response_from_plan(plan, mode="dry_run")

        await self._db.execute("BEGIN IMMEDIATE")
        try:
            artifact = await self._load_and_validate_split_artifact(
                decision_artifact_id=decision_artifact_id,
                target_id=target_id,
                source_canonical_event_id=source_id,
                affected_mention_ids=affected_ids,
            )
            existing_operation = await self._find_existing_canonical_split_operation(
                operation_id=operation_id,
                target_id=target_id,
                decision_artifact_id=decision_artifact_id,
                artifact=artifact,
                source_canonical_event_id=source_id,
                result_canonical_event_id=created_id,
                affected_mention_ids=affected_ids,
                new_title=new_title,
                new_summary=new_summary,
            )
            if existing_operation is not None:
                await self._db.commit()
                return self._canonical_split_response_from_operation(
                    existing_operation,
                    mode="applied",
                )

            plan = await self._build_canonical_split_plan(
                target_id=target_id,
                source_canonical_event_id=source_id,
                affected_mention_ids=affected_ids,
                created_canonical_event_id=created_id,
                operation_id=operation_id,
                decision_artifact_id=decision_artifact_id,
                created_by=created_by,
                new_title=new_title,
                new_summary=new_summary,
                artifact=artifact,
            )
            await self._apply_canonical_split_plan(plan)
            await self._db.commit()
            return self._canonical_split_response_from_plan(plan, mode="applied")
        except Exception:
            await self._db.rollback()
            raise

    @staticmethod
    def _canonical_split_operation_id(
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        decision_artifact_id: str | None,
        new_title: str | None,
        new_summary: str | None,
    ) -> str:
        payload = {
            "target_id": target_id,
            "operation_type": "split",
            "source_canonical_event_id": source_canonical_event_id,
            "affected_mention_ids": CanonicalStoreMixin._canonical_split_mention_ids(
                affected_mention_ids
            ),            "decision_artifact_id": decision_artifact_id,
            "new_title": new_title,
            "new_summary": new_summary,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        return f"cgo-{target_id}-split-{digest}"

    @staticmethod
    def _canonical_split_created_event_id(
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        decision_artifact_id: str | None,
    ) -> str:
        payload = {
            "target_id": target_id,
            "source_canonical_event_id": source_canonical_event_id,
            "affected_mention_ids": CanonicalStoreMixin._canonical_split_mention_ids(
                affected_mention_ids
            ),            "decision_artifact_id": decision_artifact_id,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()[:12]
        return f"ce-{target_id}-split-{digest}"

    @staticmethod
    def _canonical_split_mention_ids(mention_ids: Sequence[str]) -> list[str]:
        return sorted({str(item) for item in mention_ids})

    async def _build_canonical_split_plan(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        created_canonical_event_id: str,
        operation_id: str,
        decision_artifact_id: str | None,
        created_by: str,
        new_title: str | None,
        new_summary: str | None,
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = await self._load_canonical_event_for_merge(
            source_canonical_event_id,
            target_id=target_id,
        )
        if artifact is None:
            artifact = await self._load_and_validate_split_artifact(
                decision_artifact_id=decision_artifact_id,
                target_id=target_id,
                source_canonical_event_id=source_canonical_event_id,
                affected_mention_ids=affected_mention_ids,
            )

        source_mentions = await self.list_event_mentions(source_canonical_event_id)
        affected_mentions = await self._load_and_validate_split_mentions(
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
            source_mentions=source_mentions,
        )
        if len(affected_mentions) >= len(source_mentions):
            raise ValueError("canonical split must leave at least one mention on source event")

        created_title = new_title or self._canonical_split_title_from_mentions(affected_mentions)
        created_summary = new_summary or ""
        created_confidence = min(float(source.get("confidence") or 0), 70)
        created_event = {
            "canonical_event_id": created_canonical_event_id,
            "target_id": target_id,
            "title": created_title,
            "summary": created_summary,
            "event_time": source.get("event_time"),
            "status": "needs_review",
            "confidence": created_confidence,
            "metadata": {
                "split_from": source_canonical_event_id,
                "split_operation_id": operation_id,
            },
        }
        source_remaining_count = len(source_mentions) - len(affected_mentions)
        changes: list[dict[str, Any]] = [
            {
                "type": "create_canonical_event",
                "canonical_event_id": created_canonical_event_id,
                "split_from": source_canonical_event_id,
            },
            {
                "type": "move_mentions",
                "from_canonical_event_id": source_canonical_event_id,
                "to_canonical_event_id": created_canonical_event_id,
                "mention_ids": list(affected_mention_ids),
                "mention_count": len(affected_mentions),
            },
            {
                "type": "create_split_from_relation",
                "source_canonical_event_id": created_canonical_event_id,
                "target_canonical_event_id": source_canonical_event_id,
            },
            {
                "type": "update_metadata_counts",
                "source_canonical_event_id": source_canonical_event_id,
                "created_canonical_event_id": created_canonical_event_id,
                "source_mention_count": source_remaining_count,
                "created_mention_count": len(affected_mentions),
            },
        ]
        if artifact is not None:
            changes.append(
                {
                    "type": "resolve_research_artifact",
                    "artifact_id": decision_artifact_id,
                }
            )
        events = {
            "source": {
                "canonical_event_id": source_canonical_event_id,
                "status": source["status"],
            },
            "created": {
                "canonical_event_id": created_canonical_event_id,
                "status": "needs_review",
                "title": created_title,
            },
        }
        return {
            "operation_id": operation_id,
            "target_id": target_id,
            "operation_type": "split",
            "decision_artifact_id": decision_artifact_id,
            "source": source,
            "source_mentions": source_mentions,
            "affected_mentions": affected_mentions,
            "created_event": created_event,
            "changes": changes,
            "warnings": [],
            "events": events,
            "artifact": artifact,
            "created_by": created_by,
            "new_title": new_title,
            "new_summary": new_summary,
        }

    async def _load_and_validate_split_artifact(
        self,
        *,
        decision_artifact_id: str | None,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
    ) -> dict[str, Any] | None:
        if decision_artifact_id is None:
            return None
        artifact = await self.get_research_artifact(decision_artifact_id)
        if artifact is None:
            raise ValueError("split decision artifact not found")
        self._validate_split_decision_artifact(
            artifact=artifact,
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
        )
        return artifact

    @staticmethod
    def _validate_split_decision_artifact(
        *,
        artifact: dict[str, Any],
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
    ) -> None:
        if artifact["target_id"] != target_id:
            raise ValueError(
                f"split decision artifact target mismatch: {artifact['target_id']} != {target_id}"
            )
        if artifact["artifact_type"] != "split_decision":
            raise ValueError("split decision artifact_type must be split_decision")
        if artifact["subject_type"] != "canonical_event":
            raise ValueError("split decision artifact subject_type must be canonical_event")
        if artifact["subject_id"] != source_canonical_event_id:
            raise ValueError(
                "split decision artifact subject mismatch: "
                f"{artifact['subject_id']} != {source_canonical_event_id}"
            )
        candidate_ids = artifact["metadata"].get("affected_mention_ids", [])
        candidate_ids = candidate_ids if isinstance(candidate_ids, list) else []
        candidate_set = CanonicalStoreMixin._canonical_split_mention_ids(candidate_ids)
        affected_set = CanonicalStoreMixin._canonical_split_mention_ids(affected_mention_ids)
        if candidate_set != affected_set:
            raise ValueError("split decision artifact affected mentions must match requested ids")
        missing = [
            mention_id for mention_id in affected_mention_ids if mention_id not in candidate_set
        ]
        if missing:
            raise ValueError(
                "split decision artifact affected mentions do not cover ids: " + ", ".join(missing)
            )

    async def _load_and_validate_split_mentions(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        source_mentions: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        db = await self._ensure_db()
        rows_by_id: dict[str, dict[str, Any]] = {}
        for mention_id in affected_mention_ids:
            rows = list(
                await db.execute_fetchall(
                    """SELECT mention_id, canonical_event_id, event_id, target_id, source_id,
                              url, title, published_at, metadata_json, created_at, updated_at
                       FROM event_mentions
                       WHERE mention_id = ?""",
                    (mention_id,),
                )
            )
            if not rows:
                raise ValueError(f"event mention not found: {mention_id}")
            mention = self._row_with_metadata(
                (
                    "mention_id",
                    "canonical_event_id",
                    "event_id",
                    "target_id",
                    "source_id",
                    "url",
                    "title",
                    "published_at",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                ),
                rows[0],
            )
            rows_by_id[mention_id] = mention

        source_mention_ids = {str(mention["mention_id"]) for mention in source_mentions}
        affected_mentions: list[dict[str, Any]] = []
        for mention_id in affected_mention_ids:
            mention = rows_by_id[mention_id]
            if mention["target_id"] != target_id:
                raise ValueError(
                    "event mention target mismatch: "
                    f"{mention_id} belongs to {mention['target_id']}, not {target_id}"
                )
            if mention["canonical_event_id"] != source_canonical_event_id:
                raise ValueError(
                    "event mention source mismatch: "
                    f"{mention_id} belongs to {mention['canonical_event_id']}, "
                    f"not {source_canonical_event_id}"
                )
            if mention_id not in source_mention_ids:
                raise ValueError(
                    "event mention is not present on source canonical event: " + mention_id
                )
            affected_mentions.append(mention)
        return affected_mentions

    @staticmethod
    def _canonical_split_title_from_mentions(mentions: Sequence[dict[str, Any]]) -> str:
        def score(mention: dict[str, Any]) -> float:
            metadata = mention.get("metadata", {})
            if not isinstance(metadata, dict):
                return 0
            try:
                return float(metadata.get("news_value_score") or 0)
            except (TypeError, ValueError):
                return 0

        best = max(mentions, key=score)
        return str(best.get("title") or mentions[0]["mention_id"])

    async def _find_existing_canonical_split_operation(
        self,
        *,
        operation_id: str,
        target_id: str,
        decision_artifact_id: str | None,
        artifact: dict[str, Any] | None,
        source_canonical_event_id: str,
        result_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        new_title: str | None,
        new_summary: str | None,
    ) -> dict[str, Any] | None:
        def ensure_matching(operation: dict[str, Any], operation_label: str) -> dict[str, Any]:
            if not self._canonical_split_operation_matches(
                operation,
                target_id=target_id,
                decision_artifact_id=decision_artifact_id,
                source_canonical_event_id=source_canonical_event_id,
                result_canonical_event_id=result_canonical_event_id,
                affected_mention_ids=affected_mention_ids,
                new_title=new_title,
                new_summary=new_summary,
            ):
                raise ValueError(
                    "applied operation mismatch: "
                    f"{operation_label} does not match split artifact {decision_artifact_id}"
                )
            return operation

        artifact_operation_id = None
        if artifact is not None:
            artifact_operation_id = artifact["metadata"].get("applied_operation_id")
        if artifact_operation_id:
            operation = await self.get_canonical_graph_operation(str(artifact_operation_id))
            if operation is not None:
                return ensure_matching(operation, str(artifact_operation_id))
        operation = await self.get_canonical_graph_operation(operation_id)
        if operation is not None:
            return ensure_matching(operation, operation_id)
        if decision_artifact_id is None:
            return None
        db = await self._ensure_db()
        rows = list(
            await db.execute_fetchall(
                """SELECT operation_id, target_id, operation_type, decision_artifact_id,
                          primary_canonical_event_id, result_canonical_event_id, status,
                          changes_json, warnings_json, metadata_json, created_by, created_at
                   FROM canonical_graph_operations
                   WHERE target_id = ? AND decision_artifact_id = ?
                   LIMIT 1""",
                (target_id, decision_artifact_id),
            )
        )
        if not rows:
            return None
        existing = self._canonical_graph_operation_from_row(rows[0])
        return ensure_matching(existing, str(existing["operation_id"]))

    @staticmethod
    def _canonical_split_operation_matches(
        operation: dict[str, Any],
        *,
        target_id: str,
        decision_artifact_id: str | None,
        source_canonical_event_id: str,
        result_canonical_event_id: str,
        affected_mention_ids: Sequence[str],
        new_title: str | None,
        new_summary: str | None,
    ) -> bool:
        if (
            operation["target_id"] != target_id
            or operation["operation_type"] != "split"
            or operation["decision_artifact_id"] != decision_artifact_id
            or operation["primary_canonical_event_id"] != source_canonical_event_id
            or operation["result_canonical_event_id"] != result_canonical_event_id
        ):
            return False

        metadata = operation.get("metadata", {})
        metadata_source_id = metadata.get("source_canonical_event_id")
        if metadata_source_id is not None and metadata_source_id != source_canonical_event_id:
            return False
        metadata_result_id = metadata.get("result_canonical_event_id")
        if metadata_result_id is not None and metadata_result_id != result_canonical_event_id:
            return False
        if metadata.get("new_title") != new_title or metadata.get("new_summary") != new_summary:
            return False
        return CanonicalStoreMixin._canonical_split_mention_ids(
            metadata.get("affected_mention_ids", [])
        ) == CanonicalStoreMixin._canonical_split_mention_ids(affected_mention_ids)

    async def _apply_canonical_split_plan(self, plan: dict[str, Any]) -> None:
        db = await self._ensure_db()
        operation_id = plan["operation_id"]
        target_id = plan["target_id"]
        source_id = plan["source"]["canonical_event_id"]
        created_event = plan["created_event"]
        created_id = created_event["canonical_event_id"]
        created_metadata = dict(created_event["metadata"])
        await db.execute(
            """INSERT INTO canonical_events
               (canonical_event_id, target_id, title, summary, event_time,
                status, confidence, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(canonical_event_id) DO UPDATE SET
                   target_id = excluded.target_id,
                   title = excluded.title,
                   summary = excluded.summary,
                   event_time = excluded.event_time,
                   status = excluded.status,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                created_id,
                target_id,
                created_event["title"],
                created_event["summary"],
                created_event.get("event_time"),
                created_event["status"],
                created_event["confidence"],
                self._json_dumps(created_metadata),
            ),
        )

        affected_ids = [mention["mention_id"] for mention in plan["affected_mentions"]]
        canonical_affected_ids = self._canonical_split_mention_ids(affected_ids)
        for mention_id in affected_ids:
            await db.execute(
                """UPDATE event_mentions
                   SET canonical_event_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE target_id = ? AND canonical_event_id = ? AND mention_id = ?""",
                (created_id, target_id, source_id, mention_id),
            )

        await db.execute(
            """INSERT INTO canonical_event_relations
               (relation_id, source_canonical_event_id, target_canonical_event_id,
                relation_type, confidence, metadata_json)
               VALUES (?, ?, ?, 'split_from', ?, ?)
               ON CONFLICT(relation_id) DO UPDATE SET
                   source_canonical_event_id = excluded.source_canonical_event_id,
                   target_canonical_event_id = excluded.target_canonical_event_id,
                   relation_type = excluded.relation_type,
                   confidence = excluded.confidence,
                   metadata_json = excluded.metadata_json,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                self._canonical_split_relation_id(operation_id, created_id),
                created_id,
                source_id,
                100,
                self._json_dumps(
                    {
                        "operation_id": operation_id,
                        "reason": "canonical_split",
                    }
                ),
            ),
        )

        source_stats = await self._canonical_survivor_mention_stats(source_id)
        source_metadata = dict(plan["source"]["metadata"])
        source_metadata["mention_count"] = source_stats["mention_count"]
        source_metadata["source_count"] = source_stats["source_count"]
        if source_stats["last_seen_at"] is not None:
            source_metadata["last_seen_at"] = source_stats["last_seen_at"]
        source_metadata["last_graph_operation_id"] = operation_id
        await db.execute(
            """UPDATE canonical_events
               SET metadata_json = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE canonical_event_id = ? AND target_id = ?""",
            (self._json_dumps(source_metadata), source_id, target_id),
        )

        created_stats = await self._canonical_survivor_mention_stats(created_id)
        created_metadata["mention_count"] = created_stats["mention_count"]
        created_metadata["source_count"] = created_stats["source_count"]
        if created_stats["last_seen_at"] is not None:
            created_metadata["last_seen_at"] = created_stats["last_seen_at"]
        created_metadata["last_graph_operation_id"] = operation_id
        await db.execute(
            """UPDATE canonical_events
               SET metadata_json = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE canonical_event_id = ? AND target_id = ?""",
            (self._json_dumps(created_metadata), created_id, target_id),
        )

        artifact = plan["artifact"]
        if artifact is not None:
            artifact_metadata = dict(artifact["metadata"])
            artifact_metadata["applied_operation_id"] = operation_id
            artifact_metadata["applied_at"] = datetime.now(UTC).isoformat()
            artifact_metadata["applied_by"] = plan["created_by"]
            await db.execute(
                """UPDATE research_artifacts
                   SET status = 'resolved',
                       metadata_json = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE artifact_id = ? AND target_id = ?""",
                (self._json_dumps(artifact_metadata), artifact["artifact_id"], target_id),
            )

        await db.execute(
            """INSERT INTO canonical_graph_operations
               (operation_id, target_id, operation_type, decision_artifact_id,
                primary_canonical_event_id, result_canonical_event_id, status,
                changes_json, warnings_json, metadata_json, created_by)
               VALUES (?, ?, 'split', ?, ?, ?, 'applied', ?, ?, ?, ?)
               ON CONFLICT(operation_id) DO NOTHING""",
            (
                operation_id,
                target_id,
                plan["decision_artifact_id"],
                source_id,
                created_id,
                json.dumps(plan["changes"], ensure_ascii=False),
                json.dumps(plan["warnings"], ensure_ascii=False),
                self._json_dumps(
                    {
                        "events": plan["events"],
                        "affected_mention_ids": canonical_affected_ids,
                        "source_canonical_event_id": source_id,
                        "result_canonical_event_id": created_id,
                        "new_title": plan["new_title"],
                        "new_summary": plan["new_summary"],
                        "idempotency_payload": {
                            "target_id": target_id,
                            "operation_type": "split",
                            "decision_artifact_id": plan["decision_artifact_id"],
                            "source_canonical_event_id": source_id,
                            "result_canonical_event_id": created_id,
                            "affected_mention_ids": canonical_affected_ids,
                            "new_title": plan["new_title"],
                            "new_summary": plan["new_summary"],
                        },
                    }
                ),
                plan["created_by"],
            ),
        )

    @staticmethod
    def _canonical_split_relation_id(operation_id: str, created_canonical_event_id: str) -> str:
        relation_key = f"{operation_id}:{created_canonical_event_id}"
        digest = hashlib.sha256(relation_key.encode()).hexdigest()[:12]
        return f"rel-{operation_id}-{digest}"

    @staticmethod
    def _canonical_split_response_from_plan(
        plan: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        return {
            "mode": mode,
            "operation_id": plan["operation_id"],
            "target_id": plan["target_id"],
            "operation_type": plan["operation_type"],
            "changes": plan["changes"],
            "warnings": plan["warnings"],
            "events": plan["events"],
        }

    @staticmethod
    def _canonical_split_response_from_operation(
        operation: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        metadata = operation.get("metadata", {})
        return {
            "mode": mode,
            "operation_id": operation["operation_id"],
            "target_id": operation["target_id"],
            "operation_type": operation["operation_type"],
            "changes": operation.get("changes", []),
            "warnings": operation.get("warnings", []),
            "events": metadata.get("events", {}),
        }

    async def list_research_queue(
        self,
        *,
        target_id: str,
        status: str = "open",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        events = await self.list_canonical_events(target_id=target_id, limit=5000, offset=0)
        artifacts = await self.list_research_artifacts(target_id=target_id, limit=5000, offset=0)
        by_subject: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            if artifact.get("subject_type") == "canonical_event":
                by_subject.setdefault(str(artifact.get("subject_id", "")), []).append(artifact)

        items: list[dict[str, Any]] = []
        for event in events:
            subject_artifacts = by_subject.get(str(event["canonical_event_id"]), [])
            latest_review = next(
                (a for a in subject_artifacts if a.get("artifact_type") == "review_state"),
                None,
            )
            open_merge = sum(
                1
                for a in subject_artifacts
                if a.get("artifact_type") == "merge_decision" and a.get("status") == "open"
            )
            open_split = sum(
                1
                for a in subject_artifacts
                if a.get("artifact_type") == "split_decision" and a.get("status") == "open"
            )
            is_resolved = bool(
                latest_review
                and latest_review.get("status") == "resolved"
                and latest_review.get("metadata", {}).get("decision") == "confirmed"
            )
            has_open_decision = open_merge > 0 or open_split > 0
            is_open = has_open_decision or (
                not is_resolved
                and (
                    event.get("status") == "needs_review"
                    or float(event.get("confidence") or 0) < 80
                )
            )
            if status == "open" and not is_open:
                continue
            if status == "resolved" and not is_resolved:
                continue
            metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
            item = {
                "canonical_event_id": event["canonical_event_id"],
                "title": event.get("title", ""),
                "summary": event.get("summary", ""),
                "event_time": event.get("event_time"),
                "canonical_status": event.get("status", "active"),
                "confidence": event.get("confidence", 0),
                "mention_count": metadata.get("mention_count", 0),
                "source_count": metadata.get("source_count", 0),
                "news_value_score": metadata.get("news_value_score", 0),
                "latest_review": latest_review,
                "open_decisions": {"merge": open_merge, "split": open_split},
            }
            items.append(item)

        items.sort(
            key=lambda item: (
                -(item["open_decisions"]["merge"] + item["open_decisions"]["split"]),
                float(item.get("confidence") or 0),
                str(item.get("event_time") or ""),
            )
        )
        page = items[offset : offset + limit]
        return {"target_id": target_id, "status": status, "items": page, "total": len(items)}

    async def update_research_artifact(
        self,
        artifact_id: str,
        *,
        target_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = await self.get_research_artifact(artifact_id)
        if current is None or current.get("target_id") != target_id:
            return None
        updated = {**current, **patch}
        updated["artifact_id"] = artifact_id
        updated["target_id"] = target_id
        updated["subject_type"] = current["subject_type"]
        updated["subject_id"] = current["subject_id"]
        updated["artifact_type"] = current["artifact_type"]
        await self.upsert_research_artifact(updated)
        return await self.get_research_artifact(artifact_id)

    async def record_projection_run(self, row: dict[str, Any]) -> str:
        """记录 shadow projection run，返回 projection_run_id。"""
        projection_run_id = str(row["projection_run_id"])
        if self._db is None:
            return projection_run_id
        await self._db.execute(
            """INSERT INTO projection_runs
               (projection_run_id, target_id, mode, input_events, canonical_events,
                mentions, auto_merged, needs_review, unprojectable, diagnostics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(projection_run_id) DO UPDATE SET
                   target_id = excluded.target_id,
                   mode = excluded.mode,
                   input_events = excluded.input_events,
                   canonical_events = excluded.canonical_events,
                   mentions = excluded.mentions,
                   auto_merged = excluded.auto_merged,
                   needs_review = excluded.needs_review,
                   unprojectable = excluded.unprojectable,
                   diagnostics_json = excluded.diagnostics_json""",
            (
                projection_run_id,
                row["target_id"],
                row["mode"],
                row.get("input_events", 0),
                row.get("canonical_events", 0),
                row.get("mentions", 0),
                row.get("auto_merged", 0),
                row.get("needs_review", 0),
                row.get("unprojectable", 0),
                self._json_dumps(row.get("diagnostics")),
            ),
        )
        await self._db.commit()
        return projection_run_id

    async def apply_canonical_projection(
        self,
        *,
        candidates: list[dict[str, Any]],
        projection_run: dict[str, Any],
    ) -> str:
        """在单个事务内应用 canonical projection，失败时整体回滚。"""
        projection_run_id = str(projection_run["projection_run_id"])
        if self._db is None:
            await self.initialize()
        async with self._lock:
            async with aiosqlite.connect(str(self._db_path), timeout=30.0) as conn:
                for pragma_sql in _PRAGMA_SETUP:
                    await conn.execute(pragma_sql)
                try:
                    await conn.execute("BEGIN IMMEDIATE")
                    for candidate in candidates:
                        await conn.execute(
                            """INSERT INTO canonical_events
                               (canonical_event_id, target_id, title, summary, event_time,
                                status, confidence, metadata_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(canonical_event_id) DO UPDATE SET
                                   target_id = excluded.target_id,
                                   title = excluded.title,
                                   summary = excluded.summary,
                                   event_time = excluded.event_time,
                                   status = excluded.status,
                                   confidence = excluded.confidence,
                                   metadata_json = excluded.metadata_json,
                                   updated_at = CURRENT_TIMESTAMP""",
                            (
                                candidate["canonical_event_id"],
                                candidate["target_id"],
                                candidate["title"],
                                candidate.get("summary", ""),
                                candidate.get("event_time"),
                                candidate.get("status", "active"),
                                candidate.get("confidence", 0),
                                self._json_dumps(candidate.get("metadata")),
                            ),
                        )
                        for mention in candidate.get("mention_rows", []):
                            await conn.execute(
                                """INSERT INTO event_mentions
                                   (mention_id, canonical_event_id, event_id, target_id,
                                    source_id, url, title, published_at, metadata_json)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(mention_id) DO UPDATE SET
                                       canonical_event_id = excluded.canonical_event_id,
                                       event_id = excluded.event_id,
                                       target_id = excluded.target_id,
                                       source_id = excluded.source_id,
                                       url = excluded.url,
                                       title = excluded.title,
                                       published_at = excluded.published_at,
                                       metadata_json = excluded.metadata_json,
                                       updated_at = CURRENT_TIMESTAMP""",
                                (
                                    mention["mention_id"],
                                    mention["canonical_event_id"],
                                    mention["event_id"],
                                    mention["target_id"],
                                    mention.get("source_id"),
                                    mention.get("url"),
                                    mention["title"],
                                    mention.get("published_at"),
                                    self._json_dumps(mention.get("metadata")),
                                ),
                            )
                        for taxonomy in candidate.get("taxonomy_rows", []):
                            await conn.execute(
                                """INSERT INTO taxonomy_assignments
                                   (assignment_id, subject_type, subject_id, target_id,
                                    taxonomy_level, taxonomy_value, confidence, source,
                                    metadata_json)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(assignment_id) DO UPDATE SET
                                       subject_type = excluded.subject_type,
                                       subject_id = excluded.subject_id,
                                       target_id = excluded.target_id,
                                       taxonomy_level = excluded.taxonomy_level,
                                       taxonomy_value = excluded.taxonomy_value,
                                       confidence = excluded.confidence,
                                       source = excluded.source,
                                       metadata_json = excluded.metadata_json,
                                       updated_at = CURRENT_TIMESTAMP""",
                                (
                                    taxonomy["assignment_id"],
                                    taxonomy["subject_type"],
                                    taxonomy["subject_id"],
                                    taxonomy["target_id"],
                                    taxonomy["taxonomy_level"],
                                    taxonomy["taxonomy_value"],
                                    taxonomy.get("confidence", 0),
                                    taxonomy.get("source", "projection"),
                                    self._json_dumps(taxonomy.get("metadata")),
                                ),
                            )
                    await conn.execute(
                        """INSERT INTO projection_runs
                           (projection_run_id, target_id, mode, input_events,
                            canonical_events, mentions, auto_merged, needs_review,
                            unprojectable, diagnostics_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(projection_run_id) DO UPDATE SET
                               target_id = excluded.target_id,
                               mode = excluded.mode,
                               input_events = excluded.input_events,
                               canonical_events = excluded.canonical_events,
                               mentions = excluded.mentions,
                               auto_merged = excluded.auto_merged,
                               needs_review = excluded.needs_review,
                               unprojectable = excluded.unprojectable,
                               diagnostics_json = excluded.diagnostics_json""",
                        (
                            projection_run_id,
                            projection_run["target_id"],
                            projection_run["mode"],
                            projection_run.get("input_events", 0),
                            projection_run.get("canonical_events", 0),
                            projection_run.get("mentions", 0),
                            projection_run.get("auto_merged", 0),
                            projection_run.get("needs_review", 0),
                            projection_run.get("unprojectable", 0),
                            self._json_dumps(projection_run.get("diagnostics")),
                        ),
                    )
                except Exception:
                    await conn.rollback()
                    raise
                await conn.commit()
        return projection_run_id

    async def list_canonical_events(
        self,
        *,
        target_id: str,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出 target 下的 canonical events。"""
        if self._db is None:
            return []
        if status is not None:
            rows = await self._db.execute_fetchall(
                """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                          confidence, metadata_json, created_at, updated_at
                   FROM canonical_events
                   WHERE target_id = ? AND status = ?
                   ORDER BY COALESCE(event_time, updated_at) DESC
                   LIMIT ? OFFSET ?""",
                (target_id, status, limit, offset),
            )
        else:
            rows = await self._db.execute_fetchall(
                """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                          confidence, metadata_json, created_at, updated_at
                   FROM canonical_events
                   WHERE target_id = ?
                   ORDER BY COALESCE(event_time, updated_at) DESC
                   LIMIT ? OFFSET ?""",
                (target_id, limit, offset),
            )
        columns = (
            "canonical_event_id",
            "target_id",
            "title",
            "summary",
            "event_time",
            "status",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    async def get_canonical_event(self, canonical_event_id: str) -> dict[str, Any] | None:
        """读取单个 canonical event。"""
        if self._db is None:
            return None
        async with self._db.execute(
            """SELECT canonical_event_id, target_id, title, summary, event_time, status,
                      confidence, metadata_json, created_at, updated_at
               FROM canonical_events
               WHERE canonical_event_id = ?""",
            (canonical_event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        columns = (
            "canonical_event_id",
            "target_id",
            "title",
            "summary",
            "event_time",
            "status",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return self._row_with_metadata(columns, row)

    async def list_event_mentions(self, canonical_event_id: str) -> list[dict[str, Any]]:
        """列出 canonical event 的 mentions。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            """SELECT mention_id, canonical_event_id, event_id, target_id, source_id,
                      url, title, published_at, metadata_json, created_at, updated_at
               FROM event_mentions
               WHERE canonical_event_id = ?
               ORDER BY COALESCE(published_at, updated_at) DESC""",
            (canonical_event_id,),
        )
        columns = (
            "mention_id",
            "canonical_event_id",
            "event_id",
            "target_id",
            "source_id",
            "url",
            "title",
            "published_at",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    async def list_canonical_relations(self, canonical_event_id: str) -> list[dict[str, Any]]:
        """列出 source 或 target 匹配的 canonical event relations。"""
        if self._db is None:
            return []
        rows = await self._db.execute_fetchall(
            """SELECT relation_id, source_canonical_event_id, target_canonical_event_id,
                      relation_type, confidence, metadata_json, created_at, updated_at
               FROM canonical_event_relations
               WHERE source_canonical_event_id = ? OR target_canonical_event_id = ?
               ORDER BY updated_at DESC""",
            (canonical_event_id, canonical_event_id),
        )
        columns = (
            "relation_id",
            "source_canonical_event_id",
            "target_canonical_event_id",
            "relation_type",
            "confidence",
            "metadata_json",
            "created_at",
            "updated_at",
        )
        return [self._row_with_metadata(columns, row) for row in rows]

    # ------------------------------------------------------------------
