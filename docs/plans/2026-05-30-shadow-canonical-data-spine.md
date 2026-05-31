# Shadow Canonical Data Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only shadow canonical projection and explicit backfill layer so News Sentry can develop a future global fact pool without changing the current pipeline write path.

**Architecture:** Keep `NewsEvent`, Markdown directories, and SQLite `event_index` as the current runtime source of truth. Add canonical shadow tables in `AsyncStore`, a focused projection service that reads existing event rows and writes idempotent canonical projections only when explicitly asked, protected API endpoints for diagnostics/backfill/query, and a small target workbench panel for operators to inspect projection health.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite via `AsyncStore`, FastAPI, Vanilla JS admin UI, pytest, ruff, Node JS request-shape tests.

---

## File Structure

- Create `src/news_sentry/core/canonical_projection.py`
  - Owns projection options, diagnostics, deterministic canonical IDs, dry-run grouping, apply-mode writes, and row-level normalization from current event index data.
- Modify `src/news_sentry/core/async_store.py`
  - Adds schema migration v6 for shadow canonical tables.
  - Adds idempotent upsert/query helpers used by the projection service and API.
  - Adds a read helper for event index rows without changing pipeline write behavior.
- Modify `src/news_sentry/core/api_server.py`
  - Adds protected canonical diagnostics, backfill, list/detail, mention, and relation endpoints.
  - Wires `CanonicalProjectionService` using the existing app/store patterns.
- Modify `src/news_sentry/static/pages/target_workbench.js`
  - Adds a "事实投影" target tab that shows projection diagnostics and provides dry-run / explicit backfill actions.
- Modify `tests/unit/test_async_store.py`
  - Covers shadow schema creation and idempotent store primitives.
- Create `tests/unit/test_canonical_projection.py`
  - Covers dry-run, taxonomy normalization, duplicate grouping, apply-mode idempotency, and projection run diagnostics.
- Modify `tests/unit/test_api_server.py`
  - Covers canonical API request/response boundaries and explicit apply behavior.
- Modify `tests/js/admin_request_shapes_test.mjs`
  - Covers the frontend API request shapes for canonical diagnostics and backfill.
- Modify `tests/js/router_test.mjs`
  - Covers `#/admin/targets/:targetId/canonical` route parsing.
- Modify `src/news_sentry/static/build_manifest.json`
  - Only if `target_workbench.js` hash/version expectations require this file under the existing build manifest convention.

## Implementation Rules

- The current pipeline write path must not call canonical projection code.
- The current pipeline directories must not be renamed or migrated in this plan.
- Backfill defaults to dry-run. Writes require an explicit `apply: true` body field.
- Projection is deterministic and idempotent: running the same backfill twice must not create extra canonical events, mentions, relations, or taxonomy assignments.
- Every canonical table row stores enough provenance to trace back to the current `event_index` / event ID.
- Low-confidence matching never auto-merges. It is reported as `needs_review`.
- Canonical read/query APIs are protected in this first implementation. Public portal adoption is a later plan after diagnostics prove the projection is stable.

## Task 1: Add Shadow Canonical Store Schema

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write failing store schema tests**

Append these tests to `tests/unit/test_async_store.py`. If the file already uses fixtures for `AsyncStore`, adapt only the fixture name and keep the assertions intact.

```python
import pytest

from news_sentry.core.async_store import AsyncStore


@pytest.mark.asyncio
async def test_canonical_shadow_tables_created(tmp_path):
    db_path = tmp_path / "store.sqlite3"
    store = AsyncStore(db_path)
    await store.initialize()

    async with store._connect() as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )

    table_names = {row[0] for row in rows}
    assert {
        "canonical_events",
        "event_mentions",
        "canonical_event_relations",
        "taxonomy_assignments",
        "canonical_entity_links",
        "research_artifacts",
        "projection_runs",
    }.issubset(table_names)


@pytest.mark.asyncio
async def test_upsert_canonical_event_is_idempotent(tmp_path):
    db_path = tmp_path / "store.sqlite3"
    store = AsyncStore(db_path)
    await store.initialize()

    payload = {
        "canonical_event_id": "ce_italy_001",
        "target_id": "italy",
        "title": "Example event",
        "summary": "One canonical event.",
        "event_time": "2026-05-30T08:00:00Z",
        "status": "active",
        "confidence": 92.0,
        "metadata": {"source": "test"},
    }
    first = await store.upsert_canonical_event(payload)
    second = await store.upsert_canonical_event({**payload, "title": "Example event updated"})

    rows = await store.list_canonical_events(target_id="italy", limit=20)
    assert first == "ce_italy_001"
    assert second == "ce_italy_001"
    assert len(rows) == 1
    assert rows[0]["title"] == "Example event updated"


@pytest.mark.asyncio
async def test_upsert_event_mention_is_idempotent(tmp_path):
    db_path = tmp_path / "store.sqlite3"
    store = AsyncStore(db_path)
    await store.initialize()

    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_001",
            "target_id": "italy",
            "title": "Example event",
            "summary": "",
            "event_time": "2026-05-30T08:00:00Z",
            "status": "active",
            "confidence": 90,
            "metadata": {},
        }
    )
    payload = {
        "mention_id": "em_italy_event_001",
        "canonical_event_id": "ce_italy_001",
        "event_id": "event_001",
        "target_id": "italy",
        "source_id": "ansa",
        "url": "https://example.com/news/1",
        "title": "Example event",
        "published_at": "2026-05-30T08:00:00Z",
        "metadata": {"score": 82},
    }
    first = await store.upsert_event_mention(payload)
    second = await store.upsert_event_mention({**payload, "title": "Example event revised"})

    mentions = await store.list_event_mentions("ce_italy_001")
    assert first == "em_italy_event_001"
    assert second == "em_italy_event_001"
    assert len(mentions) == 1
    assert mentions[0]["title"] == "Example event revised"


@pytest.mark.asyncio
async def test_upsert_canonical_relation_is_idempotent(tmp_path):
    db_path = tmp_path / "store.sqlite3"
    store = AsyncStore(db_path)
    await store.initialize()

    for canonical_event_id in ("ce_source", "ce_target"):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": canonical_event_id,
                "target_id": "italy",
                "title": canonical_event_id,
                "summary": "",
                "event_time": "2026-05-30T08:00:00Z",
                "status": "active",
                "confidence": 80,
                "metadata": {},
            }
        )

    payload = {
        "relation_id": "rel_source_target_followup",
        "source_canonical_event_id": "ce_source",
        "target_canonical_event_id": "ce_target",
        "relation_type": "follow_up",
        "confidence": 70.0,
        "metadata": {"reason": "same story"},
    }
    await store.upsert_canonical_relation(payload)
    await store.upsert_canonical_relation({**payload, "confidence": 75.0})

    relations = await store.list_canonical_relations("ce_source")
    assert len(relations) == 1
    assert relations[0]["confidence"] == 75.0
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_store.py::test_canonical_shadow_tables_created \
  tests/unit/test_async_store.py::test_upsert_canonical_event_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_event_mention_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_canonical_relation_is_idempotent \
  -q
```

Expected: tests fail because canonical tables and store methods do not exist.

- [ ] **Step 3: Add DDL constants in `async_store.py`**

Add these constants near the existing `_DDL_*` constants:

```python
_DDL_CANONICAL_EVENTS = """
CREATE TABLE IF NOT EXISTS canonical_events (
    canonical_event_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    event_time TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_EVENT_MENTIONS = """
CREATE TABLE IF NOT EXISTS event_mentions (
    mention_id TEXT PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_id TEXT,
    url TEXT,
    title TEXT NOT NULL,
    published_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_CANONICAL_EVENT_RELATIONS = """
CREATE TABLE IF NOT EXISTS canonical_event_relations (
    relation_id TEXT PRIMARY KEY,
    source_canonical_event_id TEXT NOT NULL,
    target_canonical_event_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_canonical_event_id) REFERENCES canonical_events(canonical_event_id),
    FOREIGN KEY(target_canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_TAXONOMY_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS taxonomy_assignments (
    assignment_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    taxonomy_level TEXT NOT NULL,
    taxonomy_value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'projection',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_CANONICAL_ENTITY_LINKS = """
CREATE TABLE IF NOT EXISTS canonical_entity_links (
    link_id TEXT PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(canonical_event_id) REFERENCES canonical_events(canonical_event_id)
)
"""

_DDL_RESEARCH_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    canonical_event_ids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_PROJECTION_RUNS = """
CREATE TABLE IF NOT EXISTS projection_runs (
    projection_run_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    input_events INTEGER NOT NULL DEFAULT 0,
    canonical_events INTEGER NOT NULL DEFAULT 0,
    mentions INTEGER NOT NULL DEFAULT 0,
    auto_merged INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    unprojectable INTEGER NOT NULL DEFAULT 0,
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
```

- [ ] **Step 4: Add schema migration v6 and indexes**

Extend `_SCHEMA_MIGRATIONS` with a new migration after the existing v5 entry:

```python
(
    6,
    "create shadow canonical projection tables",
    [
        _DDL_CANONICAL_EVENTS,
        _DDL_EVENT_MENTIONS,
        _DDL_CANONICAL_EVENT_RELATIONS,
        _DDL_TAXONOMY_ASSIGNMENTS,
        _DDL_CANONICAL_ENTITY_LINKS,
        _DDL_RESEARCH_ARTIFACTS,
        _DDL_PROJECTION_RUNS,
    ],
),
```

Extend `_DDL_INDEXES` with these index statements:

```python
"CREATE INDEX IF NOT EXISTS idx_canonical_events_target_status_time ON canonical_events(target_id, status, event_time)",
"CREATE INDEX IF NOT EXISTS idx_event_mentions_canonical ON event_mentions(canonical_event_id)",
"CREATE INDEX IF NOT EXISTS idx_event_mentions_target_event ON event_mentions(target_id, event_id)",
"CREATE INDEX IF NOT EXISTS idx_event_mentions_url ON event_mentions(url)",
"CREATE INDEX IF NOT EXISTS idx_canonical_relations_source ON canonical_event_relations(source_canonical_event_id)",
"CREATE INDEX IF NOT EXISTS idx_canonical_relations_target ON canonical_event_relations(target_canonical_event_id)",
"CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_subject ON taxonomy_assignments(subject_type, subject_id)",
"CREATE INDEX IF NOT EXISTS idx_taxonomy_assignments_target_value ON taxonomy_assignments(target_id, taxonomy_level, taxonomy_value)",
"CREATE INDEX IF NOT EXISTS idx_canonical_entity_links_event ON canonical_entity_links(canonical_event_id)",
"CREATE INDEX IF NOT EXISTS idx_research_artifacts_target_type ON research_artifacts(target_id, artifact_type)",
"CREATE INDEX IF NOT EXISTS idx_projection_runs_target_created ON projection_runs(target_id, created_at)",
```

- [ ] **Step 5: Add JSON helpers and canonical store methods**

Add these methods inside `AsyncStore`. Reuse the file's existing connection helper and adapt row conversion only if the class already has a local helper for that pattern.

```python
def _json_dumps(self, value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)

def _json_loads(self, value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}

async def upsert_canonical_event(self, row: dict[str, Any]) -> str:
    canonical_event_id = str(row["canonical_event_id"])
    async with self._connect() as conn:
        await conn.execute(
            """
            INSERT INTO canonical_events (
                canonical_event_id, target_id, title, summary, event_time,
                status, confidence, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_event_id) DO UPDATE SET
                target_id = excluded.target_id,
                title = excluded.title,
                summary = excluded.summary,
                event_time = excluded.event_time,
                status = excluded.status,
                confidence = excluded.confidence,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                canonical_event_id,
                row["target_id"],
                row.get("title") or canonical_event_id,
                row.get("summary") or "",
                row.get("event_time"),
                row.get("status") or "active",
                float(row.get("confidence") or 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await conn.commit()
    return canonical_event_id

async def upsert_event_mention(self, row: dict[str, Any]) -> str:
    mention_id = str(row["mention_id"])
    async with self._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_mentions (
                mention_id, canonical_event_id, event_id, target_id, source_id,
                url, title, published_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mention_id) DO UPDATE SET
                canonical_event_id = excluded.canonical_event_id,
                event_id = excluded.event_id,
                target_id = excluded.target_id,
                source_id = excluded.source_id,
                url = excluded.url,
                title = excluded.title,
                published_at = excluded.published_at,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                mention_id,
                row["canonical_event_id"],
                row["event_id"],
                row["target_id"],
                row.get("source_id"),
                row.get("url"),
                row.get("title") or row["event_id"],
                row.get("published_at"),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await conn.commit()
    return mention_id

async def upsert_canonical_relation(self, row: dict[str, Any]) -> str:
    relation_id = str(row["relation_id"])
    async with self._connect() as conn:
        await conn.execute(
            """
            INSERT INTO canonical_event_relations (
                relation_id, source_canonical_event_id, target_canonical_event_id,
                relation_type, confidence, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(relation_id) DO UPDATE SET
                source_canonical_event_id = excluded.source_canonical_event_id,
                target_canonical_event_id = excluded.target_canonical_event_id,
                relation_type = excluded.relation_type,
                confidence = excluded.confidence,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                relation_id,
                row["source_canonical_event_id"],
                row["target_canonical_event_id"],
                row["relation_type"],
                float(row.get("confidence") or 0),
                self._json_dumps(row.get("metadata")),
            ),
        )
        await conn.commit()
    return relation_id
```

Add these query helpers in the same class:

```python
async def list_canonical_events(
    self,
    *,
    target_id: str,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["target_id = ?"]
    params: list[Any] = [target_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    params.extend([int(limit), int(offset)])
    async with self._connect() as conn:
        rows = await conn.execute_fetchall(
            f"""
            SELECT canonical_event_id, target_id, title, summary, event_time,
                   status, confidence, metadata_json, created_at, updated_at
            FROM canonical_events
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(event_time, updated_at) DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
    return [self._canonical_event_from_row(row) for row in rows]

async def get_canonical_event(self, canonical_event_id: str) -> dict[str, Any] | None:
    async with self._connect() as conn:
        rows = await conn.execute_fetchall(
            """
            SELECT canonical_event_id, target_id, title, summary, event_time,
                   status, confidence, metadata_json, created_at, updated_at
            FROM canonical_events
            WHERE canonical_event_id = ?
            """,
            (canonical_event_id,),
        )
    return self._canonical_event_from_row(rows[0]) if rows else None

async def list_event_mentions(self, canonical_event_id: str) -> list[dict[str, Any]]:
    async with self._connect() as conn:
        rows = await conn.execute_fetchall(
            """
            SELECT mention_id, canonical_event_id, event_id, target_id, source_id,
                   url, title, published_at, metadata_json, created_at, updated_at
            FROM event_mentions
            WHERE canonical_event_id = ?
            ORDER BY COALESCE(published_at, updated_at) DESC
            """,
            (canonical_event_id,),
        )
    return [self._event_mention_from_row(row) for row in rows]

async def list_canonical_relations(self, canonical_event_id: str) -> list[dict[str, Any]]:
    async with self._connect() as conn:
        rows = await conn.execute_fetchall(
            """
            SELECT relation_id, source_canonical_event_id, target_canonical_event_id,
                   relation_type, confidence, metadata_json, created_at, updated_at
            FROM canonical_event_relations
            WHERE source_canonical_event_id = ? OR target_canonical_event_id = ?
            ORDER BY updated_at DESC
            """,
            (canonical_event_id, canonical_event_id),
        )
    return [self._canonical_relation_from_row(row) for row in rows]
```

Add the private row converters referenced above:

```python
def _canonical_event_from_row(self, row: Any) -> dict[str, Any]:
    return {
        "canonical_event_id": row[0],
        "target_id": row[1],
        "title": row[2],
        "summary": row[3],
        "event_time": row[4],
        "status": row[5],
        "confidence": row[6],
        "metadata": self._json_loads(row[7]),
        "created_at": row[8],
        "updated_at": row[9],
    }

def _event_mention_from_row(self, row: Any) -> dict[str, Any]:
    return {
        "mention_id": row[0],
        "canonical_event_id": row[1],
        "event_id": row[2],
        "target_id": row[3],
        "source_id": row[4],
        "url": row[5],
        "title": row[6],
        "published_at": row[7],
        "metadata": self._json_loads(row[8]),
        "created_at": row[9],
        "updated_at": row[10],
    }

def _canonical_relation_from_row(self, row: Any) -> dict[str, Any]:
    return {
        "relation_id": row[0],
        "source_canonical_event_id": row[1],
        "target_canonical_event_id": row[2],
        "relation_type": row[3],
        "confidence": row[4],
        "metadata": self._json_loads(row[5]),
        "created_at": row[6],
        "updated_at": row[7],
    }
```

- [ ] **Step 6: Add taxonomy and projection-run helpers**

Add these methods in `AsyncStore`:

```python
async def upsert_taxonomy_assignment(self, row: dict[str, Any]) -> str:
    assignment_id = str(row["assignment_id"])
    async with self._connect() as conn:
        await conn.execute(
            """
            INSERT INTO taxonomy_assignments (
                assignment_id, subject_type, subject_id, target_id,
                taxonomy_level, taxonomy_value, confidence, source, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(assignment_id) DO UPDATE SET
                subject_type = excluded.subject_type,
                subject_id = excluded.subject_id,
                target_id = excluded.target_id,
                taxonomy_level = excluded.taxonomy_level,
                taxonomy_value = excluded.taxonomy_value,
                confidence = excluded.confidence,
                source = excluded.source,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                assignment_id,
                row["subject_type"],
                row["subject_id"],
                row["target_id"],
                row["taxonomy_level"],
                row["taxonomy_value"],
                float(row.get("confidence") or 0),
                row.get("source") or "projection",
                self._json_dumps(row.get("metadata")),
            ),
        )
        await conn.commit()
    return assignment_id

async def record_projection_run(self, row: dict[str, Any]) -> str:
    projection_run_id = str(row["projection_run_id"])
    async with self._connect() as conn:
        await conn.execute(
            """
            INSERT INTO projection_runs (
                projection_run_id, target_id, mode, input_events, canonical_events,
                mentions, auto_merged, needs_review, unprojectable, diagnostics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(projection_run_id) DO UPDATE SET
                mode = excluded.mode,
                input_events = excluded.input_events,
                canonical_events = excluded.canonical_events,
                mentions = excluded.mentions,
                auto_merged = excluded.auto_merged,
                needs_review = excluded.needs_review,
                unprojectable = excluded.unprojectable,
                diagnostics_json = excluded.diagnostics_json
            """,
            (
                projection_run_id,
                row["target_id"],
                row["mode"],
                int(row.get("input_events") or 0),
                int(row.get("canonical_events") or 0),
                int(row.get("mentions") or 0),
                int(row.get("auto_merged") or 0),
                int(row.get("needs_review") or 0),
                int(row.get("unprojectable") or 0),
                self._json_dumps(row.get("diagnostics")),
            ),
        )
        await conn.commit()
    return projection_run_id
```

- [ ] **Step 7: Run focused tests and lint**

Run:

```bash
ruff check src/news_sentry/core/async_store.py tests/unit/test_async_store.py
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_store.py::test_canonical_shadow_tables_created \
  tests/unit/test_async_store.py::test_upsert_canonical_event_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_event_mention_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_canonical_relation_is_idempotent \
  -q
```

Expected: ruff passes and the four tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "feat: add canonical shadow store schema"
```

## Task 2: Add Projection Dry-Run Service

**Files:**
- Create: `src/news_sentry/core/canonical_projection.py`
- Modify: `src/news_sentry/core/async_store.py`
- Create: `tests/unit/test_canonical_projection.py`

- [ ] **Step 1: Add event-index read helper test**

Append to `tests/unit/test_async_store.py`:

```python
@pytest.mark.asyncio
async def test_list_event_index_rows_for_projection_filters_by_target(tmp_path):
    db_path = tmp_path / "store.sqlite3"
    store = AsyncStore(db_path)
    await store.initialize()
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, title, url, published_at,
                pipeline_stage, news_value_score, china_relevance,
                l0_category, metadata_json, file_path
            ) VALUES
            ('it_1', 'italy', 'ansa', 'Italy story', 'https://example.com/it', '2026-05-30T08:00:00Z', 'judged', 82, 12, 'politics', '{}', 'drafts/it_1.md'),
            ('de_1', 'germany', 'dpa', 'Germany story', 'https://example.com/de', '2026-05-30T08:00:00Z', 'judged', 80, 8, 'economics', '{}', 'drafts/de_1.md')
            """
        )
        await conn.commit()

    rows = await store.list_event_index_rows_for_projection(target_id="italy", limit=20)

    assert [row["event_id"] for row in rows] == ["it_1"]
    assert rows[0]["target_id"] == "italy"
    assert rows[0]["title"] == "Italy story"
```

- [ ] **Step 2: Run helper test and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_store.py::test_list_event_index_rows_for_projection_filters_by_target \
  -q
```

Expected: fail because `list_event_index_rows_for_projection` is missing.

- [ ] **Step 3: Add `list_event_index_rows_for_projection`**

Add this method to `AsyncStore`. Adjust only column names if the current `_DDL_EVENT_INDEX` names differ; preserve returned dictionary keys.

```python
async def list_event_index_rows_for_projection(
    self,
    *,
    target_id: str,
    limit: int = 500,
    since: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["target_id = ?"]
    params: list[Any] = [target_id]
    if since:
        clauses.append("COALESCE(published_at, updated_at, created_at) >= ?")
        params.append(since)
    params.append(int(limit))
    async with self._connect() as conn:
        rows = await conn.execute_fetchall(
            f"""
            SELECT event_id, target_id, source_id, title, url, published_at,
                   pipeline_stage, news_value_score, china_relevance,
                   l0_category, metadata_json, file_path
            FROM event_index
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(published_at, updated_at, created_at) DESC
            LIMIT ?
            """,
            params,
        )
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "event_id": row[0],
                "target_id": row[1],
                "source_id": row[2],
                "title": row[3],
                "url": row[4],
                "published_at": row[5],
                "pipeline_stage": row[6],
                "news_value_score": row[7],
                "china_relevance": row[8],
                "l0_category": row[9],
                "metadata": self._json_loads(row[10]),
                "file_path": row[11],
            }
        )
    return result
```

- [ ] **Step 4: Write failing projection dry-run tests**

Create `tests/unit/test_canonical_projection.py`:

```python
import pytest

from news_sentry.core.async_store import AsyncStore
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions


async def _insert_event_index_row(
    store: AsyncStore,
    *,
    event_id: str,
    target_id: str = "italy",
    source_id: str = "ansa",
    title: str = "Italy story",
    url: str = "https://example.com/story",
    published_at: str = "2026-05-30T08:00:00Z",
    l0_category: str = "economics",
    metadata: str = "{}",
) -> None:
    async with store._connect() as conn:
        await conn.execute(
            """
            INSERT INTO event_index (
                event_id, target_id, source_id, title, url, published_at,
                pipeline_stage, news_value_score, china_relevance,
                l0_category, metadata_json, file_path
            ) VALUES (?, ?, ?, ?, ?, ?, 'judged', 84, 15, ?, ?, ?)
            """,
            (
                event_id,
                target_id,
                source_id,
                title,
                url,
                published_at,
                l0_category,
                metadata,
                f"drafts/{event_id}.md",
            ),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_projection_dry_run_does_not_write_rows(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001")

    service = CanonicalProjectionService(store)
    diagnostics = await service.project(ProjectionOptions(target_id="italy", apply=False))

    rows = await store.list_canonical_events(target_id="italy", limit=20)
    assert diagnostics.mode == "dry_run"
    assert diagnostics.input_events == 1
    assert diagnostics.canonical_events == 1
    assert diagnostics.mentions == 1
    assert rows == []


@pytest.mark.asyncio
async def test_projection_normalizes_legacy_taxonomy_labels(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001", l0_category="economics")
    await _insert_event_index_row(store, event_id="it_002", l0_category="culture_society")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.legacy_taxonomy == {"economics": "economy", "culture_society": "society"}
    assert diagnostics.taxonomy_distribution == {"economy": 1, "society": 1}


@pytest.mark.asyncio
async def test_projection_duplicate_url_group_reports_auto_merge(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001", title="Same story", url="https://example.com/same")
    await _insert_event_index_row(store, event_id="it_002", title="Same story", url="https://example.com/same")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.input_events == 2
    assert diagnostics.canonical_events == 1
    assert diagnostics.mentions == 2
    assert diagnostics.auto_merged == 1
    assert diagnostics.needs_review == 0
```

- [ ] **Step 5: Run projection tests and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_canonical_projection.py -q
```

Expected: fail because `canonical_projection.py` does not exist.

- [ ] **Step 6: Create projection service**

Create `src/news_sentry/core/canonical_projection.py`:

```python
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


LEGACY_L0_TO_CANONICAL = {
    "economics": "economy",
    "international": "international-relations",
    "international_relations": "international-relations",
    "international-relations": "international-relations",
    "culture_society": "society",
    "culture-society": "society",
    "environment_energy": "environment-energy",
    "environment-energy": "environment-energy",
    "politics": "politics",
    "security": "security",
    "tech": "technology",
    "technology": "technology",
    "uncategorized": "uncategorized",
}


@dataclass(frozen=True)
class ProjectionOptions:
    target_id: str
    since: str | None = None
    limit: int = 500
    apply: bool = False
    projection_run_id: str | None = None


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
    def __init__(self, store: AsyncStore):
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
        diagnostics.taxonomy_distribution = dict(
            sorted(Counter(row["taxonomy_value"] for candidate in candidates for row in candidate.taxonomy_rows).items())
        )

        if options.apply:
            for candidate in candidates:
                await self.store.upsert_canonical_event(
                    {
                        "canonical_event_id": candidate.canonical_event_id,
                        "target_id": candidate.target_id,
                        "title": candidate.title,
                        "summary": candidate.summary,
                        "event_time": candidate.event_time,
                        "status": "active",
                        "confidence": candidate.confidence,
                        "metadata": {"projection_run_id": run_id},
                    }
                )
                for mention in candidate.mention_rows:
                    await self.store.upsert_event_mention(mention)
                for taxonomy in candidate.taxonomy_rows:
                    await self.store.upsert_taxonomy_assignment(taxonomy)
            await self.store.record_projection_run(
                {
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
                }
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
            for row in group_rows:
                candidate.mention_rows.append(self._mention_row(canonical_id, row))
                taxonomy = self._taxonomy_row(canonical_id, row, diagnostics)
                if taxonomy:
                    candidate.taxonomy_rows.append(taxonomy)
            candidates.append(candidate)
        return candidates

    def _group_key(self, row: dict[str, Any]) -> str:
        url = str(row.get("url") or "").strip().lower()
        if url:
            return f"url:{url}"
        title = str(row.get("title") or "").strip().lower()
        published_at = str(row.get("published_at") or "")[:10]
        if title:
            return f"title:{published_at}:{title}"
        return ""

    def _canonical_event_id(self, row: dict[str, Any]) -> str:
        digest = hashlib.sha256(self._group_key(row).encode("utf-8")).hexdigest()[:16]
        return f"ce_{row['target_id']}_{digest}"

    def _mention_row(self, canonical_event_id: str, row: dict[str, Any]) -> dict[str, Any]:
        event_id = str(row["event_id"])
        mention_digest = hashlib.sha256(f"{canonical_event_id}:{event_id}".encode("utf-8")).hexdigest()[:16]
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
        canonical = LEGACY_L0_TO_CANONICAL.get(raw, raw)
        if raw != canonical:
            diagnostics.legacy_taxonomy[raw] = canonical
        assignment_digest = hashlib.sha256(f"{canonical_event_id}:l0:{canonical}".encode("utf-8")).hexdigest()[:16]
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
```

- [ ] **Step 7: Run Task 2 tests and lint**

Run:

```bash
ruff check src/news_sentry/core/async_store.py src/news_sentry/core/canonical_projection.py tests/unit/test_canonical_projection.py
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_store.py::test_list_event_index_rows_for_projection_filters_by_target \
  tests/unit/test_canonical_projection.py \
  -q
```

Expected: ruff passes and all Task 2 tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/news_sentry/core/async_store.py src/news_sentry/core/canonical_projection.py tests/unit/test_async_store.py tests/unit/test_canonical_projection.py
git commit -m "feat: add canonical projection dry run"
```

## Task 3: Add Apply-Mode Backfill Idempotency

**Files:**
- Modify: `src/news_sentry/core/canonical_projection.py`
- Modify: `tests/unit/test_canonical_projection.py`

- [ ] **Step 1: Write failing apply-mode tests**

Append to `tests/unit/test_canonical_projection.py`:

```python
@pytest.mark.asyncio
async def test_projection_apply_writes_canonical_rows(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001", l0_category="economics")

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(
            target_id="italy",
            apply=True,
            projection_run_id="projection_test_apply",
        )
    )
    events = await store.list_canonical_events(target_id="italy", limit=20)
    mentions = await store.list_event_mentions(events[0]["canonical_event_id"])

    assert diagnostics.mode == "apply"
    assert diagnostics.input_events == 1
    assert diagnostics.canonical_events == 1
    assert len(events) == 1
    assert len(mentions) == 1
    assert mentions[0]["event_id"] == "it_001"


@pytest.mark.asyncio
async def test_projection_apply_is_idempotent_for_same_input(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(store, event_id="it_001", url="https://example.com/stable")

    service = CanonicalProjectionService(store)
    await service.project(
        ProjectionOptions(target_id="italy", apply=True, projection_run_id="projection_test_1")
    )
    await service.project(
        ProjectionOptions(target_id="italy", apply=True, projection_run_id="projection_test_2")
    )

    events = await store.list_canonical_events(target_id="italy", limit=20)
    mentions = await store.list_event_mentions(events[0]["canonical_event_id"])
    assert len(events) == 1
    assert len(mentions) == 1


@pytest.mark.asyncio
async def test_projection_without_url_uses_review_sample_for_lower_confidence(tmp_path):
    store = AsyncStore(tmp_path / "store.sqlite3")
    await store.initialize()
    await _insert_event_index_row(
        store,
        event_id="it_001",
        title="Wire story without URL",
        url="",
    )

    diagnostics = await CanonicalProjectionService(store).project(
        ProjectionOptions(target_id="italy", apply=False)
    )

    assert diagnostics.needs_review == 1
    assert diagnostics.review_samples == [
        {
            "event_id": "it_001",
            "reason": "missing_url_low_confidence_group",
            "title": "Wire story without URL",
        }
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_canonical_projection.py -q
```

Expected: the first two tests may pass from Task 2, and `test_projection_without_url_uses_review_sample_for_lower_confidence` fails because lower-confidence review reporting is not implemented.

- [ ] **Step 3: Add review reporting for low-confidence groups**

Modify `_build_candidates` in `src/news_sentry/core/canonical_projection.py`. Inside the grouped loop, immediately after `primary = group_rows[0]`, add:

```python
if not primary.get("url"):
    diagnostics.needs_review += 1
    diagnostics.review_samples.append(
        {
            "event_id": primary["event_id"],
            "reason": "missing_url_low_confidence_group",
            "title": primary.get("title") or primary["event_id"],
        }
    )
```

Keep the existing `confidence=90.0 if primary.get("url") else 72.0` line so low-confidence candidates are visible but not silently discarded.

- [ ] **Step 4: Run focused tests**

Run:

```bash
ruff check src/news_sentry/core/canonical_projection.py tests/unit/test_canonical_projection.py
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_canonical_projection.py -q
```

Expected: ruff passes and all projection tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/news_sentry/core/canonical_projection.py tests/unit/test_canonical_projection.py
git commit -m "feat: make canonical backfill idempotent"
```

## Task 4: Add Protected Canonical API Endpoints

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `tests/unit/test_api_server.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/unit/test_api_server.py`. If the file already has a FastAPI client fixture, use the fixture and keep endpoint assertions the same.

```python
def _make_canonical_client(tmp_path: Path) -> tuple[TestClient, AsyncStore]:
    store = AsyncStore(tmp_path / "canonical_api.sqlite3")
    asyncio.run(store.initialize())
    app = create_app(data_dir=tmp_path, store=store, auto_store=False, skip_lifespan=True)
    return TestClient(app), store


def test_canonical_backfill_defaults_to_dry_run(tmp_path):
    client, _store = _make_canonical_client(tmp_path)

    response = client.post(
        "/api/v1/canonical/backfill",
        json={"target_id": "italy", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"
    assert "input_events" in body


def test_canonical_diagnostics_uses_dry_run(tmp_path):
    client, _store = _make_canonical_client(tmp_path)

    response = client.get("/api/v1/canonical/diagnostics", params={"target_id": "italy"})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["target_id"] == "italy"


def test_canonical_event_detail_returns_404_for_missing_event(tmp_path):
    client, _store = _make_canonical_client(tmp_path)

    response = client.get("/api/v1/canonical/events/ce_missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical event not found"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_api_server.py::test_canonical_backfill_defaults_to_dry_run \
  tests/unit/test_api_server.py::test_canonical_diagnostics_uses_dry_run \
  tests/unit/test_api_server.py::test_canonical_event_detail_returns_404_for_missing_event \
  -q
```

Expected: fail with 404 because routes are missing.

- [ ] **Step 3: Add request model and service import**

In `src/news_sentry/core/api_server.py`, add imports near the existing core service imports:

```python
from news_sentry.core.canonical_projection import CanonicalProjectionService, ProjectionOptions
```

Add a Pydantic model near the other request models:

```python
class CanonicalBackfillRequest(BaseModel):
    target_id: str
    since: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    apply: bool = False
    projection_run_id: str | None = None
```

- [ ] **Step 4: Add canonical routes in `create_app`**

Inside `create_app`, near other diagnostics/maintenance routes, add:

```python
    @app.get("/api/v1/canonical/diagnostics")
    async def canonical_diagnostics(
        target_id: str,
        since: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        service = CanonicalProjectionService(store)
        diagnostics = await service.project(
            ProjectionOptions(target_id=target_id, since=since, limit=limit, apply=False)
        )
        return diagnostics.to_dict()

    @app.post("/api/v1/canonical/backfill")
    async def canonical_backfill(payload: CanonicalBackfillRequest) -> dict[str, Any]:
        store = await _store_for_target(payload.target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        service = CanonicalProjectionService(store)
        diagnostics = await service.project(
            ProjectionOptions(
                target_id=payload.target_id,
                since=payload.since,
                limit=payload.limit,
                apply=payload.apply,
                projection_run_id=payload.projection_run_id,
            )
        )
        return diagnostics.to_dict()

    @app.get("/api/v1/canonical/events")
    async def list_canonical_events(
        target_id: str,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        events = await store.list_canonical_events(
            target_id=target_id,
            limit=limit,
            offset=offset,
            status=status,
        )
        return {"events": events, "limit": limit, "offset": offset}

    @app.get("/api/v1/canonical/events/{canonical_event_id}")
    async def get_canonical_event(canonical_event_id: str, target_id: str | None = None) -> dict[str, Any]:
        store = await _store_for_target(target_id) if target_id else _store
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await store.get_canonical_event(canonical_event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        return event

    @app.get("/api/v1/canonical/events/{canonical_event_id}/mentions")
    async def list_canonical_event_mentions(
        canonical_event_id: str,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id) if target_id else _store
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await store.get_canonical_event(canonical_event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        mentions = await store.list_event_mentions(canonical_event_id)
        return {"canonical_event_id": canonical_event_id, "mentions": mentions}

    @app.get("/api/v1/canonical/events/{canonical_event_id}/relations")
    async def list_canonical_event_relations(
        canonical_event_id: str,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        store = await _store_for_target(target_id) if target_id else _store
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await store.get_canonical_event(canonical_event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        relations = await store.list_canonical_relations(canonical_event_id)
        return {"canonical_event_id": canonical_event_id, "relations": relations}
```

If this app has a local-mode auth dependency wrapper for admin-only APIs, apply the same dependency used by maintenance backfill routes to `canonical_backfill` and `canonical_diagnostics`. Keep the tests in local mode so they remain green without a password.

- [ ] **Step 5: Add list/detail apply API test**

Append:

```python
def test_canonical_backfill_apply_makes_event_queryable(tmp_path):
    client, store = _make_canonical_client(tmp_path)

    async def seed_event() -> None:
        async with store._connect() as conn:
            await conn.execute(
                """
                INSERT INTO event_index (
                    event_id, target_id, source_id, title, url, published_at,
                    pipeline_stage, news_value_score, china_relevance,
                    l0_category, metadata_json, file_path
                ) VALUES (
                    'it_api_001', 'italy', 'ansa', 'API story',
                    'https://example.com/api-story', '2026-05-30T08:00:00Z',
                    'judged', 90, 20, 'politics', '{}', 'drafts/it_api_001.md'
                )
                """
            )
            await conn.commit()

    asyncio.run(seed_event())

    backfill = client.post(
        "/api/v1/canonical/backfill",
        json={
            "target_id": "italy",
            "limit": 10,
            "apply": True,
            "projection_run_id": "projection_api_test",
        },
    )
    listed = client.get("/api/v1/canonical/events", params={"target_id": "italy"})

    assert backfill.status_code == 200
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["title"] == "API story"
```

- [ ] **Step 6: Run API tests and lint**

Run:

```bash
ruff check src/news_sentry/core/api_server.py tests/unit/test_api_server.py
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_api_server.py::test_canonical_backfill_defaults_to_dry_run \
  tests/unit/test_api_server.py::test_canonical_diagnostics_uses_dry_run \
  tests/unit/test_api_server.py::test_canonical_event_detail_returns_404_for_missing_event \
  tests/unit/test_api_server.py::test_canonical_backfill_apply_makes_event_queryable \
  -q
```

Expected: ruff passes and all canonical API tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "feat: expose canonical projection api"
```

## Task 5: Add Target Workbench Canonical Panel

**Files:**
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `tests/js/admin_request_shapes_test.mjs`
- Modify: `tests/js/router_test.mjs`
- Modify: `src/news_sentry/static/build_manifest.json` only if the existing manifest test requires path/version consistency.

- [ ] **Step 1: Write failing JS request-shape assertions**

Append to `tests/js/admin_request_shapes_test.mjs`:

```javascript
assert.match(
  targetWorkbenchJs,
  /api\("\/api\/v1\/canonical\/diagnostics",\s*\{\s*target_id:\s*targetId,\s*limit:\s*500\s*\}\)/s,
  "Target 工作台事实投影页必须使用 dry-run diagnostics 读取投影状态",
);

assert.match(
  targetWorkbenchJs,
  /apiPost\("\/api\/v1\/canonical\/backfill",\s*\{\s*\},\s*\{\s*target_id:\s*targetId,\s*limit:\s*500,\s*apply:\s*true/s,
  "Target 工作台事实投影回填必须用 JSON body 显式传 apply:true",
);
```

- [ ] **Step 2: Write failing route test**

Append to `tests/js/router_test.mjs`:

```javascript
const adminTargetCanonical = parseRouteHash("#/admin/targets/italy/canonical");
assert.equal(adminTargetCanonical.type, "admin-target");
assert.equal(adminTargetCanonical.targetId, "italy");
assert.equal(adminTargetCanonical.tab, "canonical");
```

- [ ] **Step 3: Run JS tests and verify failure**

Run:

```bash
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
```

Expected: request-shape test fails because the panel does not call canonical APIs. Router test may already pass if dynamic target tabs are accepted; if it fails, update the router mapping in Step 6.

- [ ] **Step 4: Add canonical tab**

In `src/news_sentry/static/pages/target_workbench.js`, add the tab entry to `TARGET_TABS` after `review` and before `maintenance`:

```javascript
{ id: "canonical", label: "事实投影" },
```

- [ ] **Step 5: Add canonical renderer to target workbench**

In `renderTargetWorkbench`, add `canonical: renderCanonicalProjection` to the `renderers` object:

```javascript
const renderers = {
  overview: renderOverview,
  profile: renderProfile,
  sources: renderSources,
  social: renderSocial,
  rules: renderRules,
  collection: renderCollection,
  review: renderReview,
  canonical: renderCanonicalProjection,
  maintenance: renderMaintenance,
};
```

Add this function near `renderReview`:

```javascript
async function renderCanonicalProjection(container, targetId) {
  const diagnostics = await api("/api/v1/canonical/diagnostics", { target_id: targetId, limit: 500 });
  container.innerHTML = `
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>事实投影</h2>
        <p>从当前事件索引生成 shadow canonical 视图；不会改变采集、过滤、研判和输出写路径。</p>
      </div>
      <div class="target-kpi-grid">
        ${stat("输入事件", String(diagnostics.input_events || 0))}
        ${stat("事实事件", String(diagnostics.canonical_events || 0))}
        ${stat("事件提及", String(diagnostics.mentions || 0))}
        ${stat("需复核", String(diagnostics.needs_review || 0))}
      </div>
      <div class="target-actions">
        <button class="btn-secondary" id="canonicalDryRunBtn" type="button">重新诊断</button>
        <button class="btn-primary" id="canonicalApplyBtn" type="button">显式回填</button>
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>分类映射</h2>
        <p>legacy 分类会映射到 canonical taxonomy，未映射项会在这里暴露。</p>
      </div>
      <div class="target-check-list">
        ${Object.entries(diagnostics.taxonomy_distribution || {}).map(([label, count]) => `
          <div class="target-check ok">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(String(count))}</span>
          </div>
        `).join("") || "<p>暂无可投影分类。</p>"}
      </div>
    </section>
    <section class="target-panel">
      <div class="target-panel-head">
        <h2>复核样本</h2>
        <p>低置信度合并不会自动进入事实池，需要人工确认策略。</p>
      </div>
      <div class="target-check-list">
        ${(diagnostics.review_samples || []).map((sample) => `
          <div class="target-check warn">
            <strong>${escapeHtml(sample.title || sample.event_id)}</strong>
            <span>${escapeHtml(sample.reason || "")}</span>
          </div>
        `).join("") || "<p>暂无需复核样本。</p>"}
      </div>
    </section>
  `;
  container.querySelector("#canonicalDryRunBtn")?.addEventListener("click", () => {
    renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "canonical");
  });
  container.querySelector("#canonicalApplyBtn")?.addEventListener("click", async (event) => {
    if (!window.confirm("将当前 target 的事件索引投影到 shadow canonical 表。此操作不会修改 pipeline 原始数据。是否继续？")) {
      return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "回填中...";
    try {
      const result = await apiPost("/api/v1/canonical/backfill", {}, {
        target_id: targetId,
        limit: 500,
        apply: true,
      });
      showSuccess(`已投影 ${Number(result.canonical_events || 0)} 个事实事件`);
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "canonical");
    } catch (err) {
      button.disabled = false;
      button.textContent = "显式回填";
      showError(err.message || "事实投影失败");
    }
  });
}
```

- [ ] **Step 6: Update router only if the route test failed**

If `tests/js/router_test.mjs` failed in Step 3, update `src/news_sentry/static/router.js` so `canonical` is accepted as a target tab. Use the same mechanism already used for `overview`, `sources`, `rules`, and `maintenance`.

Run:

```bash
node tests/js/router_test.mjs
```

Expected: `#/admin/targets/italy/canonical` resolves as an admin target route with `targetId="italy"` and `tab="canonical"`.

- [ ] **Step 7: Run JS tests**

Run:

```bash
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
node tests/js/design_language_system_test.mjs
```

Expected: all three JS tests pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/news_sentry/static/pages/target_workbench.js tests/js/admin_request_shapes_test.mjs tests/js/router_test.mjs src/news_sentry/static/router.js src/news_sentry/static/build_manifest.json
git commit -m "feat: surface canonical projection in target workbench"
```

If `src/news_sentry/static/router.js` or `src/news_sentry/static/build_manifest.json` did not change, remove those paths from `git add` before committing.

## Task 6: Full Verification and Data Smoke

**Files:**
- Modify only if verification exposes a bug in files changed by Tasks 1-5.

- [ ] **Step 1: Run Python lint**

Run:

```bash
ruff check \
  src/news_sentry/core/async_store.py \
  src/news_sentry/core/canonical_projection.py \
  src/news_sentry/core/api_server.py \
  tests/unit/test_async_store.py \
  tests/unit/test_canonical_projection.py \
  tests/unit/test_api_server.py
```

Expected: no ruff errors.

- [ ] **Step 2: Run focused Python tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_async_store.py::test_canonical_shadow_tables_created \
  tests/unit/test_async_store.py::test_upsert_canonical_event_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_event_mention_is_idempotent \
  tests/unit/test_async_store.py::test_upsert_canonical_relation_is_idempotent \
  tests/unit/test_async_store.py::test_list_event_index_rows_for_projection_filters_by_target \
  tests/unit/test_canonical_projection.py \
  tests/unit/test_api_server.py::test_canonical_backfill_defaults_to_dry_run \
  tests/unit/test_api_server.py::test_canonical_diagnostics_uses_dry_run \
  tests/unit/test_api_server.py::test_canonical_event_detail_returns_404_for_missing_event \
  tests/unit/test_api_server.py::test_canonical_backfill_apply_makes_event_queryable \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run JS tests**

Run:

```bash
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
node tests/js/design_language_system_test.mjs
```

Expected: all selected JS tests pass.

- [ ] **Step 4: Run static syntax checks**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
python -m py_compile \
  src/news_sentry/core/async_store.py \
  src/news_sentry/core/canonical_projection.py \
  src/news_sentry/core/api_server.py
```

Expected: syntax checks pass.

- [ ] **Step 5: Run local dry-run smoke against real data**

Start the app if it is not already running, then run:

```bash
curl -s "http://localhost:8765/api/v1/canonical/diagnostics?target_id=italy&limit=50" | python -m json.tool
```

Expected response shape:

```json
{
  "projection_run_id": "projection_italy_dryrun_YYYYMMDDHHMMSS",
  "target_id": "italy",
  "mode": "dry_run",
  "input_events": 50,
  "canonical_events": 1,
  "mentions": 1,
  "auto_merged": 0,
  "needs_review": 0,
  "unprojectable": 0,
  "legacy_taxonomy": {},
  "taxonomy_distribution": {},
  "review_samples": []
}
```

The numeric values will vary with local data. The required acceptance check is `mode` equals `dry_run` and the request does not create rows in `canonical_events`.

- [ ] **Step 6: Run local apply smoke on a small limit**

Run:

```bash
curl -s -X POST "http://localhost:8765/api/v1/canonical/backfill" \
  -H "Content-Type: application/json" \
  -d '{"target_id":"italy","limit":10,"apply":true}' | python -m json.tool
```

Then run:

```bash
curl -s "http://localhost:8765/api/v1/canonical/events?target_id=italy&limit=10" | python -m json.tool
```

Expected: the backfill response has `"mode": "apply"`, and the list endpoint returns canonical events. Repeating the same apply command must not increase the number of events for identical source rows.

- [ ] **Step 7: Commit verification fixes if any were needed**

If Step 1-6 required code changes, commit them:

```bash
git add src/news_sentry/core/async_store.py src/news_sentry/core/canonical_projection.py src/news_sentry/core/api_server.py src/news_sentry/static/pages/target_workbench.js tests/unit/test_async_store.py tests/unit/test_canonical_projection.py tests/unit/test_api_server.py tests/js/admin_request_shapes_test.mjs tests/js/router_test.mjs
git commit -m "fix: stabilize canonical projection baseline"
```

If no changes were needed, do not create an empty commit.

## Acceptance Criteria

- `canonical_events`, `event_mentions`, `canonical_event_relations`, `taxonomy_assignments`, `canonical_entity_links`, `research_artifacts`, and `projection_runs` exist after `AsyncStore.initialize()`.
- Projection dry-run reads `event_index` rows and returns diagnostics without writing canonical rows.
- Projection apply writes canonical rows only when `apply=True`.
- Applying the same target/input more than once is idempotent.
- Legacy taxonomy labels such as `economics` and `culture_society` are normalized before canonical assignment.
- Missing-URL or lower-confidence groups are surfaced in `needs_review` and `review_samples`.
- Canonical API routes expose diagnostics, explicit backfill, event list/detail, mentions, and relations.
- Target workbench has a visible "事实投影" tab with dry-run diagnostics and explicit backfill.
- Current pipeline run/filter/judge/output code does not import or call `CanonicalProjectionService`.

## Spec Coverage Review

- Read-only shadow canonical projection: Tasks 1-4.
- Explicit backfill with dry-run default: Tasks 2-4.
- Current pipeline write path unchanged: Implementation Rules and Acceptance Criteria.
- Canonical objects: Task 1 tables cover event, mention, relation, taxonomy assignment, entity link, research artifact, and projection run.
- Diagnostics and idempotency: Tasks 2-4 and Task 6.
- Management backend visibility: Task 5.
- Testable delivery and incremental commits: every task has focused tests, verification commands, and a commit.
