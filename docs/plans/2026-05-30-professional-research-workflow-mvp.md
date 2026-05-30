# Professional Research Workflow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first professional research workflow around canonical events: review queue, evidence view, research artifacts, and target-scoped actions.

**Architecture:** Keep canonical events as the fact layer and store all human workflow actions in `research_artifacts`. Add AsyncStore methods first, expose protected research API endpoints second, then upgrade the target workbench review tab to use those endpoints. Merge/split actions are recorded as artifacts only and do not mutate canonical facts.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, aiosqlite, pytest, vanilla ES modules, existing News Sentry static UI primitives.

---

## Files

- Modify: `src/news_sentry/core/async_store.py`
  - Expand `research_artifacts` schema with workflow fields.
  - Add store methods for artifact upsert/get/list/patch and queue derivation.
- Modify: `src/news_sentry/core/api_server.py`
  - Add Pydantic request models and `/api/v1/research/*` endpoints.
- Modify: `src/news_sentry/static/pages/target_workbench.js`
  - Replace target review tab's legacy event table with canonical research queue and detail/actions.
- Modify: `src/news_sentry/static/style.css`
  - Add compact research workbench layout primitives using the existing site language.
- Modify: `tests/unit/test_async_store.py`
  - Add store coverage for artifacts and queue semantics.
- Modify: `tests/unit/test_api_server.py`
  - Add API coverage for queue/detail/artifact validation.
- Modify: `tests/js/admin_request_shapes_test.mjs`
  - Assert frontend request shapes use research APIs.
- Modify: `tests/js/router_test.mjs`
  - Keep target review route coverage explicit.

## Task 1: Research Artifact Store

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write failing store tests**

Add these tests near the existing canonical tests in `tests/unit/test_async_store.py`:

```python
@pytest.mark.asyncio
async def test_research_artifact_upsert_list_and_patch(store: AsyncStore):
    await store.upsert_canonical_event(
        {
            "canonical_event_id": "ce_italy_review_001",
            "target_id": "italy",
            "title": "Policy event",
            "summary": "A policy event",
            "event_time": "2026-05-30T10:00:00Z",
            "status": "needs_review",
            "confidence": 65,
            "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 82},
        }
    )

    artifact_id = await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_001",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "人工确认",
            "body": "多信源一致。",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_001",
            "canonical_event_ids": ["ce_italy_review_001"],
            "status": "open",
            "visibility": "local_private",
            "created_by": "local-user",
            "metadata": {"decision": "needs_more_evidence"},
        }
    )

    assert artifact_id == "ra_italy_review_001"
    listed = await store.list_research_artifacts(
        target_id="italy",
        subject_type="canonical_event",
        subject_id="ce_italy_review_001",
    )
    assert len(listed) == 1
    assert listed[0]["metadata"]["decision"] == "needs_more_evidence"

    patched = await store.update_research_artifact(
        "ra_italy_review_001",
        target_id="italy",
        patch={
            "status": "resolved",
            "body": "复核完成。",
            "metadata": {"decision": "confirmed", "reason": "sources agree"},
        },
    )
    assert patched is not None
    assert patched["status"] == "resolved"
    assert patched["metadata"]["decision"] == "confirmed"


@pytest.mark.asyncio
async def test_research_queue_hides_confirmed_items_by_default(store: AsyncStore):
    for idx, confidence in (("001", 65), ("002", 92)):
        await store.upsert_canonical_event(
            {
                "canonical_event_id": f"ce_italy_review_{idx}",
                "target_id": "italy",
                "title": f"Event {idx}",
                "summary": "",
                "event_time": f"2026-05-30T10:0{idx[-1]}:00Z",
                "status": "needs_review" if confidence < 80 else "active",
                "confidence": confidence,
                "metadata": {"mention_count": int(idx), "source_count": 1},
            }
        )

    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_review_done",
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Confirmed",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_001",
            "canonical_event_ids": ["ce_italy_review_001"],
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        }
    )
    await store.upsert_research_artifact(
        {
            "artifact_id": "ra_italy_merge_open",
            "target_id": "italy",
            "artifact_type": "merge_decision",
            "title": "Merge candidate",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_review_002",
            "canonical_event_ids": ["ce_italy_review_002", "ce_other"],
            "status": "open",
            "metadata": {"candidate_canonical_event_ids": ["ce_other"], "decision": "proposed"},
        }
    )

    open_queue = await store.list_research_queue(target_id="italy", status="open", limit=10)
    assert [item["canonical_event_id"] for item in open_queue["items"]] == ["ce_italy_review_002"]
    assert open_queue["items"][0]["open_decisions"] == {"merge": 1, "split": 0}

    resolved_queue = await store.list_research_queue(target_id="italy", status="resolved", limit=10)
    assert [item["canonical_event_id"] for item in resolved_queue["items"]] == ["ce_italy_review_001"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'research_artifact or research_queue' -q
```

Expected: fail with missing `upsert_research_artifact`, `update_research_artifact`, or `list_research_queue`.

- [ ] **Step 3: Expand schema and migrations**

In `src/news_sentry/core/async_store.py`, replace `_DDL_RESEARCH_ARTIFACTS` with:

```python
_DDL_RESEARCH_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT 'canonical_event',
    subject_id TEXT NOT NULL DEFAULT '',
    canonical_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'local_private',
    created_by TEXT NOT NULL DEFAULT 'local-user',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
```

Append migration v8 to `_SCHEMA_MIGRATIONS`:

```python
(
    8,
    "Expand research artifacts for professional workflow",
    [
        "ALTER TABLE research_artifacts ADD COLUMN subject_type TEXT NOT NULL DEFAULT 'canonical_event'",
        "ALTER TABLE research_artifacts ADD COLUMN subject_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE research_artifacts ADD COLUMN status TEXT NOT NULL DEFAULT 'open'",
        "ALTER TABLE research_artifacts ADD COLUMN visibility TEXT NOT NULL DEFAULT 'local_private'",
        "ALTER TABLE research_artifacts ADD COLUMN created_by TEXT NOT NULL DEFAULT 'local-user'",
    ],
),
```

Add indexes to `_DDL_INDEXES`:

```python
"CREATE INDEX IF NOT EXISTS idx_research_artifacts_subject "
"ON research_artifacts(target_id, subject_type, subject_id, artifact_type, updated_at)",
"CREATE INDEX IF NOT EXISTS idx_research_artifacts_status "
"ON research_artifacts(target_id, artifact_type, status, updated_at)",
```

- [ ] **Step 4: Add store constants and helpers**

Near the Shadow Canonical Store section, add:

```python
_RESEARCH_ARTIFACT_COLUMNS = (
    "artifact_id",
    "target_id",
    "artifact_type",
    "title",
    "body",
    "subject_type",
    "subject_id",
    "canonical_event_ids_json",
    "status",
    "visibility",
    "created_by",
    "metadata_json",
    "created_at",
    "updated_at",
)

_RESEARCH_ARTIFACT_TYPES = {
    "review_state",
    "annotation",
    "note",
    "merge_decision",
    "split_decision",
}
_RESEARCH_ARTIFACT_STATUSES = {"open", "resolved", "archived"}
```

Add a private helper inside `AsyncStore`:

```python
def _research_artifact_from_row(self, row: Sequence[Any]) -> dict[str, Any]:
    artifact = self._row_with_metadata(_RESEARCH_ARTIFACT_COLUMNS, row)
    raw_ids = artifact.pop("canonical_event_ids_json", "[]")
    artifact["canonical_event_ids"] = self._json_loads(raw_ids)
    if not isinstance(artifact["canonical_event_ids"], list):
        artifact["canonical_event_ids"] = []
    return artifact
```

If `Sequence` is not imported at the top, extend the existing typing import:

```python
from collections.abc import Sequence
```

- [ ] **Step 5: Add artifact CRUD store methods**

Add these methods before `record_projection_run`:

```python
async def upsert_research_artifact(self, row: dict[str, Any]) -> str:
    """Insert or update a research artifact and return artifact_id."""
    artifact_id = str(row["artifact_id"])
    artifact_type = str(row.get("artifact_type", ""))
    status = str(row.get("status", "open"))
    if artifact_type not in _RESEARCH_ARTIFACT_TYPES:
        raise ValueError(f"Unsupported research artifact type: {artifact_type}")
    if status not in _RESEARCH_ARTIFACT_STATUSES:
        raise ValueError(f"Unsupported research artifact status: {status}")
    if self._db is None:
        return artifact_id
    canonical_event_ids = row.get("canonical_event_ids")
    if canonical_event_ids is None:
        canonical_event_ids = row.get("canonical_event_ids_json", [])
    await self._db.execute(
        """INSERT INTO research_artifacts
           (artifact_id, target_id, artifact_type, title, body, subject_type,
            subject_id, canonical_event_ids_json, status, visibility, created_by,
            metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(artifact_id) DO UPDATE SET
               target_id = excluded.target_id,
               artifact_type = excluded.artifact_type,
               title = excluded.title,
               body = excluded.body,
               subject_type = excluded.subject_type,
               subject_id = excluded.subject_id,
               canonical_event_ids_json = excluded.canonical_event_ids_json,
               status = excluded.status,
               visibility = excluded.visibility,
               created_by = excluded.created_by,
               metadata_json = excluded.metadata_json,
               updated_at = CURRENT_TIMESTAMP""",
        (
            artifact_id,
            row["target_id"],
            artifact_type,
            row["title"],
            row.get("body", ""),
            row.get("subject_type", "canonical_event"),
            row.get("subject_id", ""),
            self._json_dumps(canonical_event_ids),
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
        f"""SELECT {", ".join(_RESEARCH_ARTIFACT_COLUMNS)}
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
    clauses = ["target_id = ?"]
    params: list[Any] = [target_id]
    if subject_type:
        clauses.append("subject_type = ?")
        params.append(subject_type)
    if subject_id:
        clauses.append("subject_id = ?")
        params.append(subject_id)
    if artifact_type:
        clauses.append("artifact_type = ?")
        params.append(artifact_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    params.extend([limit, offset])
    rows = await self._db.execute_fetchall(
        f"""SELECT {", ".join(_RESEARCH_ARTIFACT_COLUMNS)}
            FROM research_artifacts
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?""",
        tuple(params),
    )
    return [self._research_artifact_from_row(row) for row in rows]

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
```

- [ ] **Step 6: Add queue derivation**

Add this method after `list_research_artifacts`:

```python
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
        is_open = (
            not is_resolved
            and (
                event.get("status") == "needs_review"
                or float(event.get("confidence") or 0) < 80
                or open_merge > 0
                or open_split > 0
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
```

- [ ] **Step 7: Run store tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'research_artifact or research_queue or canonical_shadow_tables' -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "feat: add research artifact store"
```

## Task 2: Research Workflow API

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Write failing API tests**

Add tests after the canonical API tests in `tests/unit/test_api_server.py`:

```python
def test_research_queue_returns_open_canonical_items(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_001",
                "target_id": "italy",
                "title": "Research candidate",
                "summary": "Needs review",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {"mention_count": 2, "source_count": 2, "news_value_score": 88},
            }
        )
    )

    response = client.get("/api/v1/research/queue", params={"target_id": "italy"})
    assert response.status_code == 200
    data = response.json()
    assert data["target_id"] == "italy"
    assert data["items"][0]["canonical_event_id"] == "ce_italy_research_001"


def test_research_event_detail_returns_evidence_and_artifacts(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_002",
                "target_id": "italy",
                "title": "Evidence event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 70,
                "metadata": {},
            }
        )
    )
    asyncio.run(
        store.upsert_event_mention(
            {
                "mention_id": "mention-001",
                "canonical_event_id": "ce_italy_research_002",
                "event_id": "event-001",
                "target_id": "italy",
                "source_id": "ansa",
                "url": "https://example.com/news",
                "title": "Evidence title",
                "published_at": "2026-05-30T09:00:00Z",
                "metadata": {"language": "it"},
            }
        )
    )
    artifact = {
        "target_id": "italy",
        "artifact_type": "annotation",
        "title": "背景标注",
        "body": "重要背景。",
        "subject_type": "canonical_event",
        "subject_id": "ce_italy_research_002",
        "status": "open",
        "metadata": {"tags": ["policy"]},
    }
    created = client.post("/api/v1/research/artifacts", json=artifact)
    assert created.status_code == 200

    response = client.get(
        "/api/v1/research/events/ce_italy_research_002",
        params={"target_id": "italy"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["event"]["canonical_event_id"] == "ce_italy_research_002"
    assert data["mentions"][0]["mention_id"] == "mention-001"
    assert data["artifacts"][0]["artifact_type"] == "annotation"


def test_research_artifact_create_rejects_cross_target_subject(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_france_research_001",
                "target_id": "france",
                "title": "France event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    response = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Bad scope",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_france_research_001",
            "status": "resolved",
            "metadata": {"decision": "confirmed"},
        },
    )
    assert response.status_code == 404


def test_research_artifact_patch_preserves_subject_scope(
    canonical_client: tuple[TestClient, AsyncStore],
):
    client, store = canonical_client
    asyncio.run(
        store.upsert_canonical_event(
            {
                "canonical_event_id": "ce_italy_research_003",
                "target_id": "italy",
                "title": "Patch event",
                "summary": "",
                "event_time": "2026-05-30T10:00:00Z",
                "status": "needs_review",
                "confidence": 60,
                "metadata": {},
            }
        )
    )
    created = client.post(
        "/api/v1/research/artifacts",
        json={
            "target_id": "italy",
            "artifact_type": "review_state",
            "title": "Open",
            "body": "",
            "subject_type": "canonical_event",
            "subject_id": "ce_italy_research_003",
            "status": "open",
            "metadata": {"decision": "needs_more_evidence"},
        },
    )
    artifact_id = created.json()["artifact"]["artifact_id"]
    patched = client.patch(
        f"/api/v1/research/artifacts/{artifact_id}",
        params={"target_id": "italy"},
        json={
            "status": "resolved",
            "metadata": {"decision": "confirmed", "subject_id": "ce_other"},
        },
    )
    assert patched.status_code == 200
    assert patched.json()["artifact"]["subject_id"] == "ce_italy_research_003"
    assert patched.json()["artifact"]["status"] == "resolved"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_' -q
```

Expected: fail with 404 for missing `/api/v1/research/*` routes.

- [ ] **Step 3: Add request models and validators**

In `src/news_sentry/core/api_server.py`, add near the existing request models:

```python
RESEARCH_ARTIFACT_TYPES = {
    "review_state",
    "annotation",
    "note",
    "merge_decision",
    "split_decision",
}
RESEARCH_ARTIFACT_STATUSES = {"open", "resolved", "archived"}
RESEARCH_REVIEW_DECISIONS = {
    "confirmed",
    "needs_merge",
    "needs_split",
    "needs_more_evidence",
    "not_relevant",
}


class ResearchArtifactCreateRequest(BaseModel):
    target_id: str
    artifact_type: str
    title: str
    body: str = ""
    subject_type: str = "canonical_event"
    subject_id: str
    status: str = "open"
    visibility: str = "local_private"
    metadata: dict[str, Any] = {}

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, value: str) -> str:
        if value not in RESEARCH_ARTIFACT_TYPES:
            raise ValueError(f"Unsupported research artifact type: {value}")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in RESEARCH_ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported research artifact status: {value}")
        return value

    @field_validator("subject_type")
    @classmethod
    def validate_subject_type(cls, value: str) -> str:
        if value != "canonical_event":
            raise ValueError("MVP only supports canonical_event artifacts")
        return value


class ResearchArtifactPatchRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in RESEARCH_ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported research artifact status: {value}")
        return value
```

If `field_validator` is not imported, update the Pydantic import:

```python
from pydantic import BaseModel, Field, field_validator
```

- [ ] **Step 4: Add route helpers**

Near `_canonical_event_or_404`, add:

```python
def _validate_research_decision(payload: ResearchArtifactCreateRequest) -> None:
    decision = payload.metadata.get("decision")
    if payload.artifact_type == "review_state" and decision not in RESEARCH_REVIEW_DECISIONS:
        raise HTTPException(status_code=422, detail="Unsupported review decision")
    if payload.artifact_type == "merge_decision" and not payload.metadata.get(
        "candidate_canonical_event_ids"
    ):
        raise HTTPException(status_code=422, detail="merge_decision requires candidate IDs")
    if payload.artifact_type == "split_decision" and not payload.metadata.get(
        "affected_mention_ids"
    ):
        raise HTTPException(status_code=422, detail="split_decision requires affected mentions")


def _new_research_artifact_id(target_id: str, artifact_type: str) -> str:
    safe_target = re.sub(r"[^a-zA-Z0-9_-]+", "-", target_id).strip("-") or "target"
    safe_type = re.sub(r"[^a-zA-Z0-9_-]+", "-", artifact_type).strip("-") or "artifact"
    return f"ra_{safe_target}_{safe_type}_{uuid.uuid4().hex[:12]}"
```

Ensure `re` and `uuid` are imported at the top if not already:

```python
import re
import uuid
```

- [ ] **Step 5: Add research endpoints**

Add after canonical endpoints and before maintenance endpoints:

```python
@app.get("/api/v1/research/queue")
async def research_queue(
    target_id: str,
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    store = await _store_for_target(target_id)
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    return await store.list_research_queue(
        target_id=target_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/research/events/{canonical_event_id}")
async def research_event_detail(
    canonical_event_id: str,
    target_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    store = await _store_for_target(target_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Canonical event not found")
    event = await _canonical_event_or_404(store, canonical_event_id, target_id)
    mentions = await store.list_event_mentions(canonical_event_id)
    relations = await store.list_canonical_relations(canonical_event_id)
    artifacts = await store.list_research_artifacts(
        target_id=target_id,
        subject_type="canonical_event",
        subject_id=canonical_event_id,
        limit=200,
    )
    return {
        "event": event,
        "mentions": mentions,
        "relations": relations,
        "artifacts": artifacts,
    }


@app.get("/api/v1/research/artifacts")
async def list_research_artifacts(
    target_id: str,
    subject_type: str | None = "canonical_event",
    subject_id: str | None = None,
    artifact_type: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    store = await _store_for_target(target_id)
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    artifacts = await store.list_research_artifacts(
        target_id=target_id,
        subject_type=subject_type,
        subject_id=subject_id,
        artifact_type=artifact_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"artifacts": artifacts, "limit": limit, "offset": offset}


@app.post("/api/v1/research/artifacts")
async def create_research_artifact(
    payload: ResearchArtifactCreateRequest,
    user: dict[str, Any] = Depends(require_permission("write")),
) -> dict[str, Any]:
    _validate_research_decision(payload)
    store = await _store_for_target(payload.target_id)
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    await _canonical_event_or_404(store, payload.subject_id, payload.target_id)
    artifact_id = _new_research_artifact_id(payload.target_id, payload.artifact_type)
    await store.upsert_research_artifact(
        {
            "artifact_id": artifact_id,
            "target_id": payload.target_id,
            "artifact_type": payload.artifact_type,
            "title": payload.title,
            "body": payload.body,
            "subject_type": payload.subject_type,
            "subject_id": payload.subject_id,
            "canonical_event_ids": [payload.subject_id],
            "status": payload.status,
            "visibility": payload.visibility,
            "created_by": str(user.get("username") or "local-user"),
            "metadata": payload.metadata,
        }
    )
    artifact = await store.get_research_artifact(artifact_id)
    return {"artifact": artifact}


@app.patch("/api/v1/research/artifacts/{artifact_id}")
async def patch_research_artifact(
    artifact_id: str,
    target_id: str,
    payload: ResearchArtifactPatchRequest,
    user: dict[str, Any] = Depends(require_permission("write")),
) -> dict[str, Any]:
    store = await _store_for_target(target_id)
    if store is None:
        raise HTTPException(status_code=503, detail="Event store unavailable")
    patch = payload.model_dump(exclude_none=True)
    updated = await store.update_research_artifact(
        artifact_id,
        target_id=target_id,
        patch=patch,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Research artifact not found")
    return {"artifact": updated}
```

- [ ] **Step 6: Run API tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_' -q
```

Expected: pass.

- [ ] **Step 7: Run canonical regression tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'canonical or research_' -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "feat: expose research workflow api"
```

## Task 3: Target Workbench Research Review UI

**Files:**
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `src/news_sentry/static/style.css`
- Test: `tests/js/admin_request_shapes_test.mjs`
- Test: `tests/js/router_test.mjs`

- [ ] **Step 1: Write failing JS request-shape tests**

In `tests/js/admin_request_shapes_test.mjs`, add:

```js
assert.match(
  targetWorkbenchJs,
  /api\("\/api\/v1\/research\/queue",\s*\{\s*target_id:\s*targetId,\s*status:\s*"open",\s*limit:\s*50\s*\}\)/s,
  "target review tab should load canonical research queue"
);

assert.match(
  targetWorkbenchJs,
  /api\(`\/api\/v1\/research\/events\/\$\{encodeURIComponent\(canonicalEventId\)\}`,\s*\{\s*target_id:\s*targetId\s*\}\)/s,
  "target review detail should load canonical event research detail"
);

assert.match(
  targetWorkbenchJs,
  /apiPost\("\/api\/v1\/research\/artifacts",\s*\{\s*\},\s*\{[\s\S]*artifact_type:\s*"review_state"/s,
  "target review actions should create review_state artifacts"
);
```

In `tests/js/router_test.mjs`, add:

```js
const adminTargetReview = parseRouteHash("#/admin/targets/italy/review");
assert.equal(adminTargetReview.name, "adminTargetWorkbench");
assert.equal(adminTargetReview.targetId, "italy");
assert.equal(adminTargetReview.tab, "review");
```

- [ ] **Step 2: Run JS tests and verify failure**

Run:

```bash
node tests/js/admin_request_shapes_test.mjs && node tests/js/router_test.mjs
```

Expected: request-shape test fails because `renderReview` still calls `/api/v1/events`.

- [ ] **Step 3: Add research UI helpers**

In `src/news_sentry/static/pages/target_workbench.js`, add before `renderReview`:

```js
function researchDecisionLabel(decision) {
  const labels = {
    confirmed: "已确认",
    needs_merge: "需合并",
    needs_split: "需拆分",
    needs_more_evidence: "需补证据",
    not_relevant: "不相关",
  };
  return labels[decision] || "待复核";
}

function researchQueueItemHtml(item, selectedId) {
  const review = item.latest_review || {};
  const decision = review.metadata?.decision || "";
  const active = item.canonical_event_id === selectedId ? " is-active" : "";
  return `
    <button class="research-queue-item${active}" data-canonical-event-id="${escapeHtml(item.canonical_event_id)}" type="button">
      <span class="research-queue-title">${escapeHtml(item.title || item.canonical_event_id)}</span>
      <span class="research-queue-meta">
        ${escapeHtml(String(item.confidence ?? 0))} confidence · ${escapeHtml(String(item.mention_count || 0))} mentions · ${escapeHtml(researchDecisionLabel(decision))}
      </span>
    </button>
  `;
}

function researchArtifactHtml(artifact) {
  const decision = artifact.metadata?.decision ? ` · ${researchDecisionLabel(artifact.metadata.decision)}` : "";
  return `
    <li class="research-artifact">
      <strong>${escapeHtml(artifact.title || artifact.artifact_type)}</strong>
      <small>${escapeHtml(artifact.artifact_type)} · ${escapeHtml(artifact.status || "open")}${escapeHtml(decision)}</small>
      ${artifact.body ? `<p>${escapeHtml(artifact.body)}</p>` : ""}
    </li>
  `;
}

function researchMentionHtml(mention) {
  const title = escapeHtml(mention.title || mention.event_id || mention.mention_id);
  const source = escapeHtml(mention.source_id || "unknown source");
  const time = escapeHtml(mention.published_at || "");
  const link = mention.url
    ? `<a href="${escapeHtml(mention.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : `<span>${title}</span>`;
  return `
    <li class="research-evidence-item">
      <strong>${link}</strong>
      <small>${source}${time ? ` · ${time}` : ""}</small>
    </li>
  `;
}
```

- [ ] **Step 4: Replace `renderReview`**

Replace the current `renderReview` function with:

```js
async function renderReview(container, targetId) {
  const queue = await api("/api/v1/research/queue", { target_id: targetId, status: "open", limit: 50 })
    .catch((err) => ({ error: err.message || "研究队列加载失败", items: [], total: 0 }));
  if (queue.error) {
    container.innerHTML = `
      <section class="target-panel">
        <div class="target-panel-head">
          <h2>研究复核</h2>
          <p>${escapeHtml(queue.error)}</p>
        </div>
        <div class="target-actions">
          <button class="btn-secondary" id="researchReviewRetryBtn" type="button">重试</button>
          <a class="btn-secondary" href="${targetHref(targetId, "canonical")}">查看事实投影</a>
        </div>
      </section>
    `;
    container.querySelector("#researchReviewRetryBtn")?.addEventListener("click", () => {
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    });
    return;
  }

  const selectedId = queue.items?.[0]?.canonical_event_id || "";
  container.innerHTML = `
    <section class="target-panel research-workbench">
      <div class="target-panel-head">
        <h2>研究复核</h2>
        <p>围绕事实事件查看证据、确认状态、记录合并/拆分建议和研究标注。</p>
      </div>
      ${queue.total ? `
        <div class="research-layout">
          <aside class="research-queue" id="researchQueue">
            ${(queue.items || []).map((item) => researchQueueItemHtml(item, selectedId)).join("")}
          </aside>
          <div class="research-detail" id="researchDetail">
            <div class="empty-state"><div class="spinner"></div><p>正在加载证据...</p></div>
          </div>
        </div>
      ` : `
        <div class="target-workbench-empty">
          <h2>当前没有开放复核项</h2>
          <p>如果这里为空，可以先到事实投影执行显式回填，或切换到已解决队列做抽查。</p>
          <div class="target-actions">
            <a class="btn-secondary" href="${targetHref(targetId, "canonical")}">查看事实投影</a>
          </div>
        </div>
      `}
    </section>
  `;

  if (selectedId) {
    bindResearchQueue(container, targetId, selectedId);
    await renderResearchDetail(container.querySelector("#researchDetail"), targetId, selectedId);
  }
}
```

- [ ] **Step 5: Add detail rendering and actions**

Add after `renderReview`:

```js
function bindResearchQueue(container, targetId, selectedId) {
  container.querySelectorAll("[data-canonical-event-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const canonicalEventId = button.dataset.canonicalEventId || "";
      container.querySelectorAll(".research-queue-item").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      await renderResearchDetail(container.querySelector("#researchDetail"), targetId, canonicalEventId);
    });
  });
}

async function renderResearchDetail(container, targetId, canonicalEventId) {
  if (!container || !canonicalEventId) return;
  container.innerHTML = `<div class="empty-state"><div class="spinner"></div><p>正在加载证据...</p></div>`;
  const data = await api(`/api/v1/research/events/${encodeURIComponent(canonicalEventId)}`, { target_id: targetId })
    .catch((err) => ({ error: err.message || "证据加载失败" }));
  if (data.error) {
    container.innerHTML = `
      <div class="target-workbench-empty">
        <h2>证据没有加载成功</h2>
        <p>${escapeHtml(data.error)}</p>
        <button class="btn-secondary" id="researchDetailRetryBtn" type="button">重试</button>
      </div>
    `;
    container.querySelector("#researchDetailRetryBtn")?.addEventListener("click", () => {
      renderResearchDetail(container, targetId, canonicalEventId);
    });
    return;
  }
  const event = data.event || {};
  container.innerHTML = `
    <article class="research-event">
      <header class="research-event-head">
        <span class="eyebrow">CANONICAL EVENT</span>
        <h3>${escapeHtml(event.title || canonicalEventId)}</h3>
        <p>${escapeHtml(event.summary || "暂无摘要")}</p>
        <div class="research-event-meta">
          <span>${escapeHtml(event.status || "active")}</span>
          <span>${escapeHtml(String(event.confidence ?? 0))} confidence</span>
          <span>${escapeHtml(event.event_time || "unknown time")}</span>
        </div>
      </header>
      <div class="research-actions">
        <button class="btn-primary" id="researchConfirmBtn" type="button">确认事件</button>
        <button class="btn-secondary" id="researchMergeBtn" type="button">标记合并</button>
        <button class="btn-secondary" id="researchSplitBtn" type="button">标记拆分</button>
      </div>
      <section class="research-section">
        <h4>证据来源</h4>
        <ul class="research-evidence-list">
          ${(data.mentions || []).map(researchMentionHtml).join("") || "<li>暂无证据来源。</li>"}
        </ul>
      </section>
      <section class="research-section">
        <h4>研究记录</h4>
        <ul class="research-artifact-list">
          ${(data.artifacts || []).map(researchArtifactHtml).join("") || "<li>暂无研究记录。</li>"}
        </ul>
      </section>
      <form class="research-note-form" id="researchNoteForm">
        <label for="researchNoteBody">新增标注</label>
        <textarea id="researchNoteBody" rows="3" placeholder="记录背景、风险点或后续需要验证的问题"></textarea>
        <button class="btn-secondary" type="submit">保存标注</button>
      </form>
    </article>
  `;
  bindResearchActions(container, targetId, canonicalEventId);
}

function bindResearchActions(container, targetId, canonicalEventId) {
  const createArtifact = async (payload) => {
    await apiPost("/api/v1/research/artifacts", {}, {
      target_id: targetId,
      subject_type: "canonical_event",
      subject_id: canonicalEventId,
      ...payload,
    });
    showSuccess("研究记录已保存");
    await renderResearchDetail(container, targetId, canonicalEventId);
  };
  container.querySelector("#researchConfirmBtn")?.addEventListener("click", async () => {
    try {
      await createArtifact({
        artifact_type: "review_state",
        title: "人工确认",
        body: "已复核证据，确认该事实事件。",
        status: "resolved",
        metadata: { decision: "confirmed", reason: "manual review" },
      });
      renderTargetWorkbench(document.getElementById("pageContainer"), targetId, "review");
    } catch (err) {
      showError(err.message || "确认失败");
    }
  });
  container.querySelector("#researchMergeBtn")?.addEventListener("click", async () => {
    try {
      await createArtifact({
        artifact_type: "merge_decision",
        title: "合并建议",
        body: "人工标记为可能需要与其他事实事件合并。",
        status: "open",
        metadata: {
          decision: "proposed",
          candidate_canonical_event_ids: [canonicalEventId],
          reason: "manual merge candidate",
        },
      });
    } catch (err) {
      showError(err.message || "保存合并建议失败");
    }
  });
  container.querySelector("#researchSplitBtn")?.addEventListener("click", async () => {
    try {
      await createArtifact({
        artifact_type: "split_decision",
        title: "拆分建议",
        body: "人工标记为可能误合并，需要拆分证据。",
        status: "open",
        metadata: {
          decision: "proposed",
          affected_mention_ids: [],
          reason: "manual split candidate",
        },
      });
    } catch (err) {
      showError(err.message || "保存拆分建议失败");
    }
  });
  container.querySelector("#researchNoteForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = container.querySelector("#researchNoteBody")?.value?.trim() || "";
    if (!body) return;
    try {
      await createArtifact({
        artifact_type: "annotation",
        title: "研究标注",
        body,
        status: "open",
        metadata: { tags: [] },
      });
    } catch (err) {
      showError(err.message || "保存标注失败");
    }
  });
}
```

- [ ] **Step 6: Add CSS primitives**

Append to `src/news_sentry/static/style.css`:

```css
.research-layout {
  display: grid;
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.research-queue {
  display: grid;
  gap: var(--space-2);
}

.research-queue-item {
  border: 1px solid var(--border-subtle);
  background: var(--surface);
  color: var(--text);
  text-align: left;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  min-height: 68px;
}

.research-queue-item.is-active {
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}

.research-queue-title,
.research-queue-meta {
  display: block;
}

.research-queue-title {
  font-weight: 700;
  line-height: 1.35;
}

.research-queue-meta,
.research-event-meta,
.research-artifact small,
.research-evidence-item small {
  color: var(--text-muted);
  font-size: 12px;
}

.research-event {
  display: grid;
  gap: var(--space-4);
}

.research-event-head h3 {
  margin: 4px 0 8px;
  font-size: 20px;
}

.research-event-meta,
.research-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.research-section {
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-3);
}

.research-evidence-list,
.research-artifact-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: var(--space-2);
}

.research-evidence-item,
.research-artifact {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  background: var(--surface-muted);
}

.research-note-form {
  display: grid;
  gap: var(--space-2);
}

.research-note-form textarea {
  width: 100%;
  resize: vertical;
}

@media (max-width: 720px) {
  .research-layout {
    grid-template-columns: 1fr;
  }
}
```

Use existing CSS tokens if any of these variables are absent: replace `--space-4`, `--space-3`, `--space-2`, `--radius-sm`, `--border-subtle`, `--surface`, `--surface-muted`, `--text`, `--text-muted`, `--accent` with the nearest existing News Sentry token names already defined in `style.css`.

- [ ] **Step 7: Run JS checks**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
node tests/js/design_language_system_test.mjs
```

Expected: pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/news_sentry/static/pages/target_workbench.js src/news_sentry/static/style.css tests/js/admin_request_shapes_test.mjs tests/js/router_test.mjs
git commit -m "feat: add target research review workbench"
```

## Task 4: End-to-End Verification and Browser Smoke

**Files:**
- No planned source changes unless verification exposes a defect.

- [ ] **Step 1: Run focused Python checks**

Run:

```bash
ruff check src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py tests/unit/test_async_store.py tests/unit/test_api_server.py
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py -k 'research_artifact or research_queue or canonical' -q
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_api_server.py -k 'research_ or canonical' -q
```

Expected: all pass.

- [ ] **Step 2: Run focused JS checks**

Run:

```bash
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
node tests/js/design_language_system_test.mjs
node tests/js/static_build_manifest_test.mjs
```

Expected: all pass.

- [ ] **Step 3: Smoke the API locally**

If no app server is already running from the current HEAD, start one on an unused port:

```bash
PYTHONPATH=src .venv/bin/python -m news_sentry.cli serve --host 127.0.0.1 --port 8877
```

Then call:

```bash
curl -s "http://127.0.0.1:8877/api/v1/research/queue?target_id=italy&limit=5" | python -m json.tool
```

Expected: JSON object with `target_id`, `status`, `items`, and `total`. Empty `items` is acceptable only if canonical backfill has not been applied for that local database.

- [ ] **Step 4: Browser smoke**

Open:

```text
http://127.0.0.1:8877/#/admin/targets/italy/review
```

Verify:

- The page does not stay on a permanent loading state.
- Empty canonical data shows a clear next step pointing to `事实投影`.
- If queue items exist, selecting one loads event evidence and artifacts.
- Clicking `确认事件` creates a `review_state` artifact and refreshes the open queue.
- 390px mobile viewport has no horizontal overflow.

- [ ] **Step 5: Commit verification fixes**

If Step 1-4 required code fixes, commit them:

```bash
git add src/news_sentry tests
git commit -m "fix: stabilize research workflow smoke"
```

If no fixes were needed, do not create an empty commit.

## Final Review

- [ ] Run final verification:

```bash
ruff check src/news_sentry tests
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_async_store.py tests/unit/test_api_server.py -k 'research_ or canonical' -q
node --check src/news_sentry/static/pages/target_workbench.js
node tests/js/admin_request_shapes_test.mjs
node tests/js/router_test.mjs
node tests/js/design_language_system_test.mjs
node tests/js/static_build_manifest_test.mjs
```

- [ ] Confirm `git status --short` only shows unrelated pre-existing local files or intended committed work.
- [ ] Dispatch a final code review subagent for spec compliance and code quality.
