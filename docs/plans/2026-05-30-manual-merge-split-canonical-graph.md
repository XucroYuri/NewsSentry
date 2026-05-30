# Manual Merge/Split Canonical Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn human merge/split research decisions into real, audited, idempotent mutations of the shadow canonical graph.

**Architecture:** Add a canonical graph operation log to `AsyncStore`, then implement target-scoped merge and split preview/apply methods as SQLite transactions. Expose the methods through protected research graph endpoints and wire the target research workbench to dry-run before apply.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, aiosqlite, pytest, vanilla ES modules, existing News Sentry static UI helpers.

---

## Files

- Modify: `src/news_sentry/core/async_store.py`
  - Add `canonical_graph_operations` DDL, migration, indexes, serializers.
  - Add graph operation listing methods.
  - Add canonical merge preview/apply methods.
  - Add canonical split preview/apply methods.
- Modify: `src/news_sentry/core/api_server.py`
  - Add request models for graph merge/split.
  - Add `/api/v1/research/graph/*` endpoints.
  - Convert store `ValueError` diagnostics into 422 responses.
- Modify: `src/news_sentry/static/pages/target_workbench.js`
  - Render apply controls for open `merge_decision` and `split_decision` artifacts.
  - Call dry-run first, ask for confirmation, then apply.
- Modify: `src/news_sentry/static/style.css`
  - Add compact operation summary styles using the existing admin/research visual language.
- Modify: `tests/unit/test_async_store.py`
  - Add graph operation, merge, split, idempotency, and target-scope tests.
- Modify: `tests/unit/test_api_server.py`
  - Add API coverage for graph merge/split dry-run/apply/list operations.
- Modify: `tests/js/admin_request_shapes_test.mjs`
  - Assert frontend graph apply request shapes and no fallback IDs.

## Task 1: Canonical Graph Operation Store

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write failing graph operation tests**

Add this test near the existing shadow canonical store tests in `tests/unit/test_async_store.py`:

```python
@pytest.mark.asyncio
async def test_canonical_graph_operation_record_and_list(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_graph_source",
            "target_id": "italy",
            "title": "Source event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )

    operation_id = await store.record_canonical_graph_operation(
        {
            "operation_id": "cgo-italy-merge-example",
            "target_id": "italy",
            "operation_type": "merge",
            "decision_artifact_id": "ra_italy_merge_example",
            "primary_canonical_event_id": "ce_italy_graph_source",
            "result_canonical_event_id": "ce_italy_graph_source",
            "status": "applied",
            "changes": [{"type": "mark_merged", "canonical_event_id": "ce_merged"}],
            "warnings": [],
            "metadata": {"idempotency_key": "merge-key"},
            "created_by": "local-user",
        }
    )

    assert operation_id == "cgo-italy-merge-example"
    listed = await store.list_canonical_graph_operations(target_id="italy", limit=10)
    assert [item["operation_id"] for item in listed] == ["cgo-italy-merge-example"]
    assert listed[0]["changes"][0]["type"] == "mark_merged"
    assert listed[0]["metadata"]["idempotency_key"] == "merge-key"

    by_artifact = await store.list_canonical_graph_operations(
        target_id="italy",
        decision_artifact_id="ra_italy_merge_example",
        limit=10,
    )
    assert [item["operation_id"] for item in by_artifact] == ["cgo-italy-merge-example"]

    missing = await store.list_canonical_graph_operations(target_id="france", limit=10)
    assert missing == []
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py::test_canonical_graph_operation_record_and_list -q
```

Expected: FAIL because `record_canonical_graph_operation` is not implemented.

- [ ] **Step 3: Add operation DDL, migration, and constants**

In `src/news_sentry/core/async_store.py`, add this DDL after `_DDL_CANONICAL_EVENT_RELATIONS`:

```python
_DDL_CANONICAL_GRAPH_OPERATIONS = """
CREATE TABLE IF NOT EXISTS canonical_graph_operations (
    operation_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    decision_artifact_id TEXT,
    primary_canonical_event_id TEXT NOT NULL,
    result_canonical_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    changes_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT 'local-user',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
```

Append migration 9 to `_SCHEMA_MIGRATIONS`:

```python
(
    9,
    "create canonical graph operation log",
    [_DDL_CANONICAL_GRAPH_OPERATIONS],
),
```

Append these indexes to `_DDL_INDEXES`:

```python
"CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_target_type "
"ON canonical_graph_operations(target_id, operation_type, created_at)",
"CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_artifact "
"ON canonical_graph_operations(target_id, decision_artifact_id)",
"CREATE INDEX IF NOT EXISTS idx_canonical_graph_ops_primary "
"ON canonical_graph_operations(target_id, primary_canonical_event_id, created_at)",
```

Add constants near `_RESEARCH_ARTIFACT_STATUSES`:

```python
_CANONICAL_GRAPH_OPERATION_COLUMNS = (
    "operation_id",
    "target_id",
    "operation_type",
    "decision_artifact_id",
    "primary_canonical_event_id",
    "result_canonical_event_id",
    "status",
    "changes_json",
    "warnings_json",
    "metadata_json",
    "created_by",
    "created_at",
)
_CANONICAL_GRAPH_OPERATION_TYPES = {"merge", "split"}
_CANONICAL_GRAPH_OPERATION_STATUSES = {"applied"}
```

- [ ] **Step 4: Add operation serializers and methods**

Add these methods inside `AsyncStore` near the research artifact methods:

```python
    def _canonical_graph_operation_from_row(self, row: Sequence[Any]) -> dict[str, Any]:
        data = dict(zip(_CANONICAL_GRAPH_OPERATION_COLUMNS, row, strict=True))
        data["changes"] = self._json_loads(data.pop("changes_json"), [])
        data["warnings"] = self._json_loads(data.pop("warnings_json"), [])
        data["metadata"] = self._json_loads(data.pop("metadata_json"), {})
        return data

    async def record_canonical_graph_operation(self, row: dict[str, Any]) -> str:
        operation_id = str(row["operation_id"])
        operation_type = str(row["operation_type"])
        status = str(row.get("status", "applied"))
        if operation_type not in _CANONICAL_GRAPH_OPERATION_TYPES:
            raise ValueError(f"Unsupported canonical graph operation type: {operation_type}")
        if status not in _CANONICAL_GRAPH_OPERATION_STATUSES:
            raise ValueError(f"Unsupported canonical graph operation status: {status}")
        if self._db is None:
            return operation_id
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
                row.get("decision_artifact_id"),
                row["primary_canonical_event_id"],
                row.get("result_canonical_event_id"),
                status,
                self._json_dumps(row.get("changes", [])),
                self._json_dumps(row.get("warnings", [])),
                self._json_dumps(row.get("metadata", {})),
                row.get("created_by", "local-user"),
            ),
        )
        await self._db.commit()
        return operation_id

    async def get_canonical_graph_operation(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
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
                max(1, min(int(limit), 200)),
                max(0, int(offset)),
            ),
        )
        return [self._canonical_graph_operation_from_row(row) for row in rows]
```

- [ ] **Step 5: Run test and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py::test_canonical_graph_operation_record_and_list -q
```

Expected: PASS.

Commit:

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "feat: add canonical graph operation log"
```

## Task 2: Canonical Merge Preview and Apply

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write failing merge tests**

Add these helpers and tests in `tests/unit/test_async_store.py` near the canonical graph operation test:

```python
async def _seed_merge_graph(store: AsyncStore) -> None:
    for event_id, target_id, title, status in (
        ("ce_italy_merge_survivor", "italy", "Survivor", "needs_review"),
        ("ce_italy_merge_duplicate", "italy", "Duplicate", "needs_review"),
        ("ce_france_merge_duplicate", "france", "France duplicate", "needs_review"),
    ):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": event_id,
                "target_id": target_id,
                "title": title,
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": status,
                "confidence": 70,
                "metadata": {"mention_count": 1, "source_count": 1},
            }
        )
    for mention_id, event_id, target_id, source_id in (
        ("mention_survivor", "ce_italy_merge_survivor", "italy", "ansa"),
        ("mention_duplicate", "ce_italy_merge_duplicate", "italy", "repubblica"),
        ("mention_france", "ce_france_merge_duplicate", "france", "afp"),
    ):
        await store.upsert_event_mention(
            {
                "mention_id": mention_id,
                "canonical_event_id": event_id,
                "event_id": f"ne_{mention_id}",
                "target_id": target_id,
                "source_id": source_id,
                "url": f"https://example.com/{mention_id}",
                "title": mention_id,
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": 80},
            }
        )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_merge_apply",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge",
            "body": "Same fact",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_merge_survivor",
            "canonical_event_ids": ["ce_italy_merge_survivor", "ce_italy_merge_duplicate"],
            "status": "open",
            "metadata": {
                "decision": "proposed",
                "candidate_canonical_event_ids": ["ce_italy_merge_duplicate"],
            },
        }
    )


@pytest.mark.asyncio
async def test_canonical_merge_dry_run_apply_and_idempotency(store: AsyncStore):
    await _seed_merge_graph(store)

    dry_run = await store.preview_canonical_merge(
        target_id="italy",
        survivor_canonical_event_id="ce_italy_merge_survivor",
        merged_canonical_event_ids=["ce_italy_merge_duplicate"],
        decision_artifact_id="ra_italy_merge_apply",
        created_by="local-user",
    )
    assert dry_run["mode"] == "dry_run"
    assert dry_run["operation_type"] == "merge"
    assert dry_run["changes"][0]["type"] == "move_mentions"
    assert (await store.get_canonical_event("ce_italy_merge_duplicate"))["status"] == "needs_review"

    applied = await store.apply_canonical_merge(
        target_id="italy",
        survivor_canonical_event_id="ce_italy_merge_survivor",
        merged_canonical_event_ids=["ce_italy_merge_duplicate"],
        decision_artifact_id="ra_italy_merge_apply",
        created_by="local-user",
    )
    assert applied["mode"] == "applied"
    assert applied["operation_id"] == dry_run["operation_id"]

    survivor_mentions = await store.list_event_mentions("ce_italy_merge_survivor")
    assert {mention["mention_id"] for mention in survivor_mentions} == {
        "mention_survivor",
        "mention_duplicate",
    }
    duplicate = await store.get_canonical_event("ce_italy_merge_duplicate")
    assert duplicate["status"] == "merged"
    assert duplicate["metadata"]["merged_into"] == "ce_italy_merge_survivor"

    relations = await store.list_canonical_relations("ce_italy_merge_duplicate")
    assert [relation["relation_type"] for relation in relations] == ["duplicate"]

    artifact = await store.get_research_artifact("ra_italy_merge_apply")
    assert artifact["status"] == "resolved"
    assert artifact["metadata"]["applied_operation_id"] == applied["operation_id"]

    second = await store.apply_canonical_merge(
        target_id="italy",
        survivor_canonical_event_id="ce_italy_merge_survivor",
        merged_canonical_event_ids=["ce_italy_merge_duplicate"],
        decision_artifact_id="ra_italy_merge_apply",
        created_by="local-user",
    )
    assert second["operation_id"] == applied["operation_id"]
    operations = await store.list_canonical_graph_operations(target_id="italy", limit=10)
    assert [operation["operation_id"] for operation in operations] == [applied["operation_id"]]


@pytest.mark.asyncio
async def test_canonical_merge_rejects_cross_target_candidate(store: AsyncStore):
    await _seed_merge_graph(store)
    with pytest.raises(ValueError, match="target mismatch"):
        await store.preview_canonical_merge(
            target_id="italy",
            survivor_canonical_event_id="ce_italy_merge_survivor",
            merged_canonical_event_ids=["ce_france_merge_duplicate"],
            decision_artifact_id=None,
            created_by="local-user",
        )
```

- [ ] **Step 2: Run failing merge tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'canonical_merge' -q
```

Expected: FAIL because merge preview/apply methods are missing.

- [ ] **Step 3: Add merge helper methods**

In `src/news_sentry/core/async_store.py`, add private helpers near the canonical store methods:

```python
    async def _canonical_event_required(
        self,
        canonical_event_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        event = await self.get_canonical_event(canonical_event_id)
        if event is None:
            raise ValueError(f"canonical event not found: {canonical_event_id}")
        if event.get("target_id") != target_id:
            raise ValueError(
                f"canonical event target mismatch: {canonical_event_id} belongs to "
                f"{event.get('target_id')}, not {target_id}"
            )
        return event

    def _stable_graph_operation_id(
        self,
        *,
        target_id: str,
        operation_type: str,
        payload: dict[str, Any],
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        safe_target = re.sub(r"[^a-zA-Z0-9_-]+", "-", target_id).strip("-") or "target"
        return f"cgo-{safe_target}-{operation_type}-{digest}"

    async def _mention_counts_for_event(
        self,
        conn: aiosqlite.Connection,
        canonical_event_id: str,
    ) -> dict[str, Any]:
        rows = await conn.execute_fetchall(
            """SELECT source_id, published_at
               FROM event_mentions
               WHERE canonical_event_id = ?""",
            (canonical_event_id,),
        )
        sources = {str(row[0]) for row in rows if row[0]}
        published = [str(row[1]) for row in rows if row[1]]
        return {
            "mention_count": len(rows),
            "source_count": len(sources),
            "last_seen_at": max(published) if published else None,
        }

    def _merge_event_metadata(
        self,
        event: dict[str, Any],
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        return {**metadata, **patch}
```

Use existing imports where available; add `import hashlib` and `import re` only if they are not already present.

- [ ] **Step 4: Add merge preview/apply methods**

Add these public methods in `AsyncStore`:

```python
    async def preview_canonical_merge(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: list[str],
        decision_artifact_id: str | None = None,
        title_override: str | None = None,
        summary_override: str | None = None,
        created_by: str = "local-user",
    ) -> dict[str, Any]:
        return await self._canonical_merge_result(
            target_id=target_id,
            survivor_canonical_event_id=survivor_canonical_event_id,
            merged_canonical_event_ids=merged_canonical_event_ids,
            decision_artifact_id=decision_artifact_id,
            title_override=title_override,
            summary_override=summary_override,
            created_by=created_by,
            apply=False,
        )

    async def apply_canonical_merge(
        self,
        *,
        target_id: str,
        survivor_canonical_event_id: str,
        merged_canonical_event_ids: list[str],
        decision_artifact_id: str | None = None,
        title_override: str | None = None,
        summary_override: str | None = None,
        created_by: str = "local-user",
    ) -> dict[str, Any]:
        return await self._canonical_merge_result(
            target_id=target_id,
            survivor_canonical_event_id=survivor_canonical_event_id,
            merged_canonical_event_ids=merged_canonical_event_ids,
            decision_artifact_id=decision_artifact_id,
            title_override=title_override,
            summary_override=summary_override,
            created_by=created_by,
            apply=True,
        )
```

Implement `_canonical_merge_result` with these exact semantics:

- Remove duplicate IDs while preserving order.
- Reject empty `merged_canonical_event_ids`.
- Reject survivor appearing in merged IDs.
- Load survivor and merged events with `_canonical_event_required`.
- If `decision_artifact_id` is provided, load artifact, require `artifact_type == "merge_decision"`, require same target, require same `subject_id` as survivor, and require all merged IDs to be present in `metadata.candidate_canonical_event_ids`.
- Build deterministic `operation_id` from target, type, survivor, merged IDs, decision artifact ID, title override, and summary override.
- Return `mode: "dry_run"` when `apply=False`.
- When `apply=True`, use `BEGIN IMMEDIATE`, move mentions, mark merged events, create duplicate relations, update survivor metadata counts, update artifact, insert operation, commit.
- If artifact metadata already contains `applied_operation_id`, return the existing operation when it exists.

The method body should produce response keys:

```python
{
    "mode": "dry_run" or "applied",
    "operation_id": operation_id,
    "target_id": target_id,
    "operation_type": "merge",
    "changes": changes,
    "warnings": warnings,
    "events": {"survivor": survivor_summary, "merged": merged_summaries},
}
```

- [ ] **Step 5: Run merge tests and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'canonical_merge or graph_operation' -q
```

Expected: PASS.

Commit:

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "feat: apply canonical merge decisions"
```

## Task 3: Canonical Split Preview and Apply

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write failing split tests**

Add these tests in `tests/unit/test_async_store.py`:

```python
async def _seed_split_graph(store: AsyncStore) -> None:
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_split_source",
            "target_id": "italy",
            "title": "Mixed event",
            "summary": "",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "needs_review",
            "confidence": 60,
            "metadata": {"mention_count": 3, "source_count": 3},
        }
    )
    for mention_id, source_id, score in (
        ("mention_split_keep", "ansa", 80),
        ("mention_split_move_1", "repubblica", 70),
        ("mention_split_move_2", "lastampa", 65),
    ):
        await store.upsert_event_mention(
            {
                "mention_id": mention_id,
                "canonical_event_id": "ce_italy_split_source",
                "event_id": f"ne_{mention_id}",
                "target_id": "italy",
                "source_id": source_id,
                "url": f"https://example.com/{mention_id}",
                "title": mention_id.replace("_", " "),
                "published_at": "2026-05-30T10:00:00Z",
                "metadata": {"news_value_score": score},
            }
        )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_split_apply",
            "target_id": "italy",
            "artifact_type": "split_decision",
            "title": "Split",
            "body": "Different fact",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_split_source",
            "canonical_event_ids": ["ce_italy_split_source"],
            "status": "open",
            "metadata": {
                "decision": "proposed",
                "affected_mention_ids": ["mention_split_move_1", "mention_split_move_2"],
            },
        }
    )


@pytest.mark.asyncio
async def test_canonical_split_dry_run_apply_and_idempotency(store: AsyncStore):
    await _seed_split_graph(store)

    dry_run = await store.preview_canonical_split(
        target_id="italy",
        source_canonical_event_id="ce_italy_split_source",
        affected_mention_ids=["mention_split_move_1", "mention_split_move_2"],
        decision_artifact_id="ra_italy_split_apply",
        new_title="Split event",
        created_by="local-user",
    )
    assert dry_run["mode"] == "dry_run"
    created_id = dry_run["events"]["created"]["canonical_event_id"]
    assert await store.get_canonical_event(created_id) is None

    applied = await store.apply_canonical_split(
        target_id="italy",
        source_canonical_event_id="ce_italy_split_source",
        affected_mention_ids=["mention_split_move_1", "mention_split_move_2"],
        decision_artifact_id="ra_italy_split_apply",
        new_title="Split event",
        created_by="local-user",
    )
    assert applied["mode"] == "applied"
    assert applied["events"]["created"]["canonical_event_id"] == created_id

    source_mentions = await store.list_event_mentions("ce_italy_split_source")
    assert {mention["mention_id"] for mention in source_mentions} == {"mention_split_keep"}
    created_mentions = await store.list_event_mentions(created_id)
    assert {mention["mention_id"] for mention in created_mentions} == {
        "mention_split_move_1",
        "mention_split_move_2",
    }

    created = await store.get_canonical_event(created_id)
    assert created["status"] == "needs_review"
    assert created["metadata"]["split_from"] == "ce_italy_split_source"
    artifact = await store.get_research_artifact("ra_italy_split_apply")
    assert artifact["status"] == "resolved"
    assert artifact["metadata"]["applied_operation_id"] == applied["operation_id"]

    second = await store.apply_canonical_split(
        target_id="italy",
        source_canonical_event_id="ce_italy_split_source",
        affected_mention_ids=["mention_split_move_1", "mention_split_move_2"],
        decision_artifact_id="ra_italy_split_apply",
        new_title="Split event",
        created_by="local-user",
    )
    assert second["operation_id"] == applied["operation_id"]
    operations = await store.list_canonical_graph_operations(target_id="italy", limit=10)
    assert [operation["operation_id"] for operation in operations] == [applied["operation_id"]]


@pytest.mark.asyncio
async def test_canonical_split_rejects_moving_all_mentions(store: AsyncStore):
    await _seed_split_graph(store)
    with pytest.raises(ValueError, match="leave at least one mention"):
        await store.preview_canonical_split(
            target_id="italy",
            source_canonical_event_id="ce_italy_split_source",
            affected_mention_ids=[
                "mention_split_keep",
                "mention_split_move_1",
                "mention_split_move_2",
            ],
            decision_artifact_id=None,
            created_by="local-user",
        )
```

- [ ] **Step 2: Run failing split tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'canonical_split' -q
```

Expected: FAIL because split methods are missing.

- [ ] **Step 3: Add split preview/apply methods**

Add public methods parallel to merge:

```python
    async def preview_canonical_split(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: list[str],
        decision_artifact_id: str | None = None,
        new_title: str | None = None,
        new_summary: str | None = None,
        created_by: str = "local-user",
    ) -> dict[str, Any]:
        return await self._canonical_split_result(
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
            decision_artifact_id=decision_artifact_id,
            new_title=new_title,
            new_summary=new_summary,
            created_by=created_by,
            apply=False,
        )

    async def apply_canonical_split(
        self,
        *,
        target_id: str,
        source_canonical_event_id: str,
        affected_mention_ids: list[str],
        decision_artifact_id: str | None = None,
        new_title: str | None = None,
        new_summary: str | None = None,
        created_by: str = "local-user",
    ) -> dict[str, Any]:
        return await self._canonical_split_result(
            target_id=target_id,
            source_canonical_event_id=source_canonical_event_id,
            affected_mention_ids=affected_mention_ids,
            decision_artifact_id=decision_artifact_id,
            new_title=new_title,
            new_summary=new_summary,
            created_by=created_by,
            apply=True,
        )
```

Implement `_canonical_split_result` with these exact semantics:

- Remove duplicate mention IDs while preserving order.
- Reject empty `affected_mention_ids`.
- Load source event with `_canonical_event_required`.
- Load all mentions for source event and build `mention_id -> mention`.
- Require each affected mention to exist and currently belong to source event.
- Reject moving all source mentions with message containing `leave at least one mention`.
- If `decision_artifact_id` is provided, load artifact, require `artifact_type == "split_decision"`, require same target, require same `subject_id`, and require all affected mention IDs to be present in `metadata.affected_mention_ids`.
- Build deterministic `operation_id` from target, type, source event, affected mention IDs, decision artifact ID, title, and summary.
- Build deterministic new event ID as `ce-{target}-split-{hash12}` from the same identity.
- Choose `new_title` from payload, otherwise the affected mention with highest `metadata.news_value_score`, otherwise first affected mention title.
- Choose `new_summary` from payload, otherwise empty string.
- New event status is `needs_review`; confidence is the minimum of source confidence and 70.
- Apply with `BEGIN IMMEDIATE`: insert new canonical event, move mentions, create `split_from` relation, update source/new metadata counts, update artifact, insert operation, commit.
- Return existing applied operation if artifact already has `applied_operation_id`.

The response shape must match the spec:

```python
{
    "mode": "dry_run" or "applied",
    "operation_id": operation_id,
    "target_id": target_id,
    "operation_type": "split",
    "changes": changes,
    "warnings": warnings,
    "events": {"source": source_summary, "created": created_summary},
}
```

- [ ] **Step 4: Run split tests and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'canonical_split or canonical_merge or graph_operation' -q
```

Expected: PASS.

Commit:

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "feat: apply canonical split decisions"
```

## Task 4: Research Graph API

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Write failing API tests**

Add tests near existing research API tests in `tests/unit/test_api_server.py`:

```python
def test_research_graph_merge_dry_run_and_apply(client, tmp_path):
    _seed_research_graph_api_data(tmp_path)

    dry_run = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "decision_artifact_id": "ra_italy_merge_api",
            "survivor_canonical_event_id": "ce_italy_api_survivor",
            "merged_canonical_event_ids": ["ce_italy_api_duplicate"],
            "dry_run": True,
        },
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["mode"] == "dry_run"

    applied = client.post(
        "/api/v1/research/graph/merge",
        json={
            "target_id": "italy",
            "decision_artifact_id": "ra_italy_merge_api",
            "survivor_canonical_event_id": "ce_italy_api_survivor",
            "merged_canonical_event_ids": ["ce_italy_api_duplicate"],
            "dry_run": False,
        },
    )
    assert applied.status_code == 200
    assert applied.json()["mode"] == "applied"

    operations = client.get("/api/v1/research/graph/operations", params={"target_id": "italy"})
    assert operations.status_code == 200
    assert operations.json()["operations"][0]["operation_id"] == applied.json()["operation_id"]


def test_research_graph_split_rejects_invalid_mention(client, tmp_path):
    _seed_research_graph_api_data(tmp_path)

    response = client.post(
        "/api/v1/research/graph/split",
        json={
            "target_id": "italy",
            "source_canonical_event_id": "ce_italy_api_survivor",
            "affected_mention_ids": ["missing-mention"],
            "dry_run": True,
        },
    )
    assert response.status_code == 422
    assert "mention not found" in response.json()["detail"]
```

Add helper `_seed_research_graph_api_data` in the same test module. Use existing app fixtures and direct `AsyncStore` writes. Seed:

- `ce_italy_api_survivor`
- `ce_italy_api_duplicate`
- mentions under both events
- merge artifact `ra_italy_merge_api`

- [ ] **Step 2: Run failing API tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_graph' -q
```

Expected: FAIL because graph API routes are missing.

- [ ] **Step 3: Add API request models**

In `src/news_sentry/core/api_server.py`, add near `ResearchArtifactPatchRequest`:

```python
class ResearchGraphMergeRequest(BaseModel):
    target_id: str
    decision_artifact_id: str | None = None
    survivor_canonical_event_id: str
    merged_canonical_event_ids: list[str] = Field(min_length=1)
    title_override: str | None = None
    summary_override: str | None = None
    dry_run: bool = True


class ResearchGraphSplitRequest(BaseModel):
    target_id: str
    decision_artifact_id: str | None = None
    source_canonical_event_id: str
    affected_mention_ids: list[str] = Field(min_length=1)
    new_title: str | None = None
    new_summary: str | None = None
    dry_run: bool = True
```

- [ ] **Step 4: Add API routes**

Add routes after `patch_research_artifact`:

```python
    @app.post("/api/v1/research/graph/merge")
    async def apply_research_graph_merge(
        payload: ResearchGraphMergeRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        created_by = (
            "local-user" if user.get("local") else str(user.get("username") or "local-user")
        )
        try:
            if payload.dry_run:
                return await store.preview_canonical_merge(
                    target_id=payload.target_id,
                    survivor_canonical_event_id=payload.survivor_canonical_event_id,
                    merged_canonical_event_ids=payload.merged_canonical_event_ids,
                    decision_artifact_id=payload.decision_artifact_id,
                    title_override=payload.title_override,
                    summary_override=payload.summary_override,
                    created_by=created_by,
                )
            return await store.apply_canonical_merge(
                target_id=payload.target_id,
                survivor_canonical_event_id=payload.survivor_canonical_event_id,
                merged_canonical_event_ids=payload.merged_canonical_event_ids,
                decision_artifact_id=payload.decision_artifact_id,
                title_override=payload.title_override,
                summary_override=payload.summary_override,
                created_by=created_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/research/graph/split")
    async def apply_research_graph_split(
        payload: ResearchGraphSplitRequest,
        user: dict[str, Any] = Depends(require_permission("write")),
    ) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        created_by = (
            "local-user" if user.get("local") else str(user.get("username") or "local-user")
        )
        try:
            if payload.dry_run:
                return await store.preview_canonical_split(
                    target_id=payload.target_id,
                    source_canonical_event_id=payload.source_canonical_event_id,
                    affected_mention_ids=payload.affected_mention_ids,
                    decision_artifact_id=payload.decision_artifact_id,
                    new_title=payload.new_title,
                    new_summary=payload.new_summary,
                    created_by=created_by,
                )
            return await store.apply_canonical_split(
                target_id=payload.target_id,
                source_canonical_event_id=payload.source_canonical_event_id,
                affected_mention_ids=payload.affected_mention_ids,
                decision_artifact_id=payload.decision_artifact_id,
                new_title=payload.new_title,
                new_summary=payload.new_summary,
                created_by=created_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/research/graph/operations")
    async def list_research_graph_operations(
        target_id: str,
        operation_type: str | None = Query(None, pattern="^(merge|split)$"),
        decision_artifact_id: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        operations = await store.list_canonical_graph_operations(
            target_id=target_id,
            operation_type=operation_type,
            decision_artifact_id=decision_artifact_id,
            limit=limit,
            offset=offset,
        )
        return {"operations": operations, "limit": limit, "offset": offset}
```

- [ ] **Step 5: Run API tests and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_graph or research_artifact or canonical_event_mentions' -q
```

Expected: PASS.

Commit:

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "feat: expose research graph apply api"
```

## Task 5: Target Workbench Graph Apply UI

**Files:**
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `src/news_sentry/static/style.css`
- Test: `tests/js/admin_request_shapes_test.mjs`

- [ ] **Step 1: Write failing JS request-shape tests**

Append assertions to `tests/js/admin_request_shapes_test.mjs`:

```javascript
const graphApplyBlock = snippetAround(targetWorkbenchJs, "async function applyResearchGraphDecision", 1800);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true/s,
  "合并应用必须先调用 dry_run:true 预检",
);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/merge",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*false/s,
  "合并应用必须在确认后调用 dry_run:false 应用",
);
assert.match(
  graphApplyBlock,
  /survivor_canonical_event_id:\s*canonicalEventId/s,
  "合并应用必须使用当前 canonical event 作为 survivor",
);
assert.match(
  graphApplyBlock,
  /merged_canonical_event_ids:\s*candidateIds/s,
  "合并应用必须使用 artifact metadata 中的 candidate IDs",
);
assert.match(
  graphApplyBlock,
  /apiPost\("\/api\/v1\/research\/graph\/split",\s*\{\s*\},\s*\{[\s\S]*dry_run:\s*true/s,
  "拆分应用必须先调用 dry_run:true 预检",
);
assert.match(
  graphApplyBlock,
  /source_canonical_event_id:\s*canonicalEventId/s,
  "拆分应用必须使用当前 canonical event 作为 source",
);
assert.match(
  graphApplyBlock,
  /affected_mention_ids:\s*affectedMentionIds/s,
  "拆分应用必须使用 artifact metadata 中的 affected mention IDs",
);
```

- [ ] **Step 2: Run failing JS test**

Run:

```bash
node tests/js/admin_request_shapes_test.mjs
```

Expected: FAIL because `applyResearchGraphDecision` is missing.

- [ ] **Step 3: Render artifact apply controls**

In `src/news_sentry/static/pages/target_workbench.js`, update `researchArtifactHtml` so open `merge_decision` and `split_decision` artifacts render buttons:

```javascript
function researchArtifactActionHtml(artifact) {
  if (artifact.status !== "open") return "";
  if (artifact.artifact_type === "merge_decision") {
    return `
      <div class="research-artifact-actions">
        <button class="btn-secondary research-graph-apply" type="button" data-artifact-id="${escapeHtml(artifact.artifact_id)}" data-operation-type="merge">应用合并</button>
      </div>
    `;
  }
  if (artifact.artifact_type === "split_decision") {
    return `
      <div class="research-artifact-actions">
        <button class="btn-secondary research-graph-apply" type="button" data-artifact-id="${escapeHtml(artifact.artifact_id)}" data-operation-type="split">应用拆分</button>
      </div>
    `;
  }
  return "";
}
```

Call `researchArtifactActionHtml(artifact)` inside each artifact list item after metadata/status text.

- [ ] **Step 4: Add graph apply action**

Add this helper near existing research action helpers:

```javascript
function researchArtifactById(detailData, artifactId) {
  return (detailData.artifacts || []).find((artifact) => artifact.artifact_id === artifactId);
}

function graphChangeSummary(result) {
  return (result.changes || [])
    .map((change) => {
      if (change.type === "move_mentions") return `移动 ${change.count || 0} 条证据`;
      if (change.type === "mark_merged") return `标记合并：${change.canonical_event_id || ""}`;
      if (change.type === "create_canonical_event") return `创建事实事件：${change.canonical_event_id || ""}`;
      if (change.type === "create_relation") return `创建关系：${change.relation_type || ""}`;
      return change.type || "变更";
    })
    .filter(Boolean)
    .join("\\n");
}

async function applyResearchGraphDecision(targetId, canonicalEventId, detailData, artifactId, operationType) {
  const artifact = researchArtifactById(detailData, artifactId);
  if (!artifact) {
    showError("未找到研究决策记录");
    return;
  }
  const metadata = artifact.metadata || {};
  try {
    if (operationType === "merge") {
      const candidateIds = Array.isArray(metadata.candidate_canonical_event_ids)
        ? metadata.candidate_canonical_event_ids.filter(Boolean)
        : [];
      if (!candidateIds.length) {
        showError("合并决策缺少候选 canonical event ID");
        return;
      }
      const preview = await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: true,
      });
      const ok = window.confirm(`将应用合并：\\n${graphChangeSummary(preview) || "无结构化变更"}`);
      if (!ok) return;
      await apiPost("/api/v1/research/graph/merge", {}, {
        target_id: targetId,
        decision_artifact_id: artifactId,
        survivor_canonical_event_id: canonicalEventId,
        merged_canonical_event_ids: candidateIds,
        dry_run: false,
      });
      showSuccess("合并已应用到事实图谱");
      await renderResearchDetail(document.getElementById("pageContainer"), targetId, canonicalEventId);
      return;
    }
    const affectedMentionIds = Array.isArray(metadata.affected_mention_ids)
      ? metadata.affected_mention_ids.filter(Boolean)
      : [];
    if (!affectedMentionIds.length) {
      showError("拆分决策缺少 affected mention IDs");
      return;
    }
    const preview = await apiPost("/api/v1/research/graph/split", {}, {
      target_id: targetId,
      decision_artifact_id: artifactId,
      source_canonical_event_id: canonicalEventId,
      affected_mention_ids: affectedMentionIds,
      dry_run: true,
    });
    const ok = window.confirm(`将应用拆分：\\n${graphChangeSummary(preview) || "无结构化变更"}`);
    if (!ok) return;
    await apiPost("/api/v1/research/graph/split", {}, {
      target_id: targetId,
      decision_artifact_id: artifactId,
      source_canonical_event_id: canonicalEventId,
      affected_mention_ids: affectedMentionIds,
      dry_run: false,
    });
    showSuccess("拆分已应用到事实图谱");
    await renderResearchDetail(document.getElementById("pageContainer"), targetId, canonicalEventId);
  } catch (err) {
    showError(err.message || "应用事实图谱变更失败");
  }
}
```

In `bindResearchActions`, bind the buttons:

```javascript
  container.querySelectorAll(".research-graph-apply").forEach((button) => {
    button.addEventListener("click", async () => {
      await applyResearchGraphDecision(
        targetId,
        canonicalEventId,
        detailData,
        button.dataset.artifactId || "",
        button.dataset.operationType || "",
      );
    });
  });
```

- [ ] **Step 5: Add compact styles**

Add to `src/news_sentry/static/style.css`:

```css
.research-artifact-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.research-graph-apply {
  min-height: 30px;
  padding: 0 10px;
}
```

- [ ] **Step 6: Run JS tests and commit**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/admin_request_shapes_test.mjs
```

Expected: PASS.

Commit:

```bash
git add src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/style.css tests/js/admin_request_shapes_test.mjs
git commit -m "feat: apply research graph decisions in workbench"
```

## Task 6: Verification and Browser Smoke

**Files:**
- No planned source changes.

- [ ] **Step 1: Run focused Python verification**

Run:

```bash
ruff check src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py tests/unit/test_async_store.py tests/unit/test_api_server.py
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'canonical_graph or canonical_merge or canonical_split or research_artifact' -q
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_graph or research_artifact or canonical_event_mentions' -q
```

Expected: ruff passes; pytest passes.

- [ ] **Step 2: Run focused frontend verification**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
```

Expected: all commands pass.

- [ ] **Step 3: Browser smoke with isolated data**

Start an isolated local service with a small temporary-data harness that imports `create_app`, passes `skip_lifespan=True`, and uses a temporary `data_dir`. Seed one target store with:

- `ce_italy_browser_survivor`
- `ce_italy_browser_duplicate`
- two mentions
- one open `merge_decision`

Open:

```text
http://localhost:<port>/#/admin/targets/italy/review
```

Verify:

- Review detail renders without waiting on target overview.
- Open merge decision shows an apply control.
- Applying merge first triggers dry-run, then apply.
- After apply, detail shows moved mention and duplicate relation.
- 390px viewport has no horizontal overflow in the action area.

- [ ] **Step 4: Final status check**

Run:

```bash
git status --short
git log --oneline -8
```

Expected:

- Only unrelated pre-existing local files remain unstaged.
- The six task commits are present on top of the branch.
