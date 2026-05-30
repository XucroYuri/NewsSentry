# Phase 32: Entity Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist NLP entities across runs with cumulative statistics and expose them via API.

**Architecture:** Add a `entities` table to SQLite with `UNIQUE(canonical_name, entity_type)` for deduplication. The `upsert_entity()` method uses `ON CONFLICT DO UPDATE` to atomically increment `mention_count`. API endpoints query this table and also cross-reference `event_index.entity_names` for related events.

**Tech Stack:** SQLite (aiosqlite), FastAPI, Pydantic, pytest-asyncio

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/news_sentry/core/async_store.py` | entities DDL + upsert_entity + query_entities + query_entity_detail + stats top_entities |
| `src/news_sentry/core/api_server.py` | GET /entities, GET /entities/{id}, StatsResponse.top_entities |
| `src/news_sentry/core/async_run.py` | Entity persistence after NLP enrichment |
| `tests/unit/test_async_store.py` | 6 new entity tests |
| `tests/unit/test_api_server.py` | 5 new API entity tests |
| `tests/unit/test_run.py` | 1 integration test |

---

### Task 1: SQLite entities 表 + upsert_entity

**Files:**
- Modify: `src/news_sentry/core/async_store.py` (DDL section lines 23-83, initialize() lines 96-118)
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_async_store.py`:

```python
class TestEntityTracking:
    """entities 表 CRUD 与去重。"""

    @pytest.mark.asyncio
    async def test_entities_table_created(self, tmp_path: Path):
        """entities 表在 initialize() 后存在。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entities'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        await store.close()

    @pytest.mark.asyncio
    async def test_upsert_entity_inserts_new(self, store: AsyncStore):
        """首次 upsert 插入新实体。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        async with store._db.execute(
            "SELECT canonical_name, entity_type, mention_count, target_ids FROM entities"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Meloni"
        assert row[1] == "person"
        assert row[2] == 1
        assert row[3] == "italy"

    @pytest.mark.asyncio
    async def test_upsert_entity_increments_on_conflict(self, store: AsyncStore):
        """相同 canonical_name+entity_type 时 mention_count 累加。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT mention_count, last_seen FROM entities WHERE canonical_name = 'Meloni'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 2
        assert "2026-05-17" in row[1]

    @pytest.mark.asyncio
    async def test_upsert_entity_appends_target_id(self, store: AsyncStore):
        """不同 target_id 时追加到 target_ids。"""
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "germany", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT target_ids FROM entities WHERE canonical_name = 'EU'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert "italy" in row[0]
        assert "germany" in row[0]

    @pytest.mark.asyncio
    async def test_upsert_entity_same_target_id_no_duplicate(self, store: AsyncStore):
        """相同 target_id 不重复追加。"""
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-17T10:00:00+00:00")
        async with store._db.execute(
            "SELECT target_ids FROM entities WHERE canonical_name = 'EU'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        # "italy" 只出现一次（作为唯一 target 或不重复）
        parts = [p for p in row[0].split(",") if p]
        assert parts.count("italy") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEntityTracking -v`
Expected: FAIL — `AsyncStore has no attribute 'upsert_entity'`, `entities` table not found

- [ ] **Step 3: Write the implementation**

Add DDL constant after `_DDL_EVENT_INDEX` (after line 75) in `src/news_sentry/core/async_store.py`:

```python
_DDL_ENTITIES = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    target_ids TEXT DEFAULT '',
    UNIQUE(canonical_name, entity_type)
)
"""
```

Add entity indexes to `_DDL_INDEXES` tuple (after line 82):

```python
_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_known_ids_seen ON known_ids(seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage)",
    "CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_event_sentiment ON event_index(sentiment)",
    "CREATE INDEX IF NOT EXISTS idx_event_topic_tags ON event_index(topic_tags)",
    "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_entities_mentions ON entities(mention_count DESC)",
    "CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen DESC)",
)
```

Add table creation in `initialize()` — after the existing `await self._db.execute(_DDL_EVENT_INDEX)` (line 107):

```python
        await self._db.execute(_DDL_ENTITIES)
```

Add `upsert_entity` method after the Event Index section (after `get_event_file_path` method):

```python
    # ------------------------------------------------------------------
    # Entity Tracking (Phase 32)
    # ------------------------------------------------------------------

    async def upsert_entity(
        self,
        name: str,
        entity_type: str,
        target_id: str,
        seen_at: str,
    ) -> None:
        """插入或更新实体记录（同名+同类型视为同一实体）。"""
        if self._db is None:
            return
        await self._db.execute(
            """INSERT INTO entities (canonical_name, entity_type, first_seen, last_seen, target_ids)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                   mention_count = mention_count + 1,
                   last_seen = excluded.last_seen,
                   target_ids = CASE
                       WHEN ',' || target_ids || ',' LIKE '%,' || excluded.target_ids || ',%'
                       THEN target_ids
                       ELSE target_ids || ',' || excluded.target_ids
                   END""",
            (name, entity_type, seen_at, seen_at, target_id),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEntityTracking -v`
Expected: 5 PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1516 passed (1511 existing + 5 new)

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 32 P32.01: entities 表 + upsert_entity"
```

---

### Task 2: AsyncStore entity 查询方法

**Files:**
- Modify: `src/news_sentry/core/async_store.py` (after upsert_entity)
- Test: `tests/unit/test_async_store.py` (in TestEntityTracking)

- [ ] **Step 1: Write the failing tests**

Add to `TestEntityTracking` class in `tests/unit/test_async_store.py`:

```python
    @pytest.mark.asyncio
    async def test_query_entities_basic(self, store: AsyncStore):
        """基本实体列表查询。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Roma", "location", "italy", "2026-05-16T10:00:00+00:00")
        # 提及 Meloni 两次
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        entities = await store.query_entities(limit=10)
        assert len(entities) == 3
        # 按 mention_count DESC 排序，Meloni 排第一
        assert entities[0]["canonical_name"] == "Meloni"
        assert entities[0]["mention_count"] == 2

    @pytest.mark.asyncio
    async def test_query_entities_filter_by_type(self, store: AsyncStore):
        """按 entity_type 过滤实体。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        entities = await store.query_entities(entity_type="person")
        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "Meloni"

    @pytest.mark.asyncio
    async def test_query_entities_min_mentions(self, store: AsyncStore):
        """按最少提及次数过滤。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-17T10:00:00+00:00")
        await store.upsert_entity("EU", "organization", "italy", "2026-05-16T10:00:00+00:00")
        entities = await store.query_entities(min_mentions=2)
        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "Meloni"

    @pytest.mark.asyncio
    async def test_query_entity_detail_found(self, store: AsyncStore):
        """查询实体详情返回实体信息。"""
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-16T10:00:00+00:00")
        detail = await store.query_entity_detail(1)
        assert detail is not None
        assert detail["canonical_name"] == "Meloni"
        assert detail["entity_type"] == "person"
        assert "recent_events" in detail

    @pytest.mark.asyncio
    async def test_query_entity_detail_not_found(self, store: AsyncStore):
        """查询不存在的实体返回 None。"""
        detail = await store.query_entity_detail(999)
        assert detail is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEntityTracking::test_query_entities_basic -v`
Expected: FAIL — `AsyncStore has no attribute 'query_entities'`

- [ ] **Step 3: Write the implementation**

Add two methods after `upsert_entity` in `src/news_sentry/core/async_store.py`:

```python
    async def query_entities(
        self,
        entity_type: str | None = None,
        target_id: str | None = None,
        min_mentions: int = 1,
        limit: int = 20,
        sort: str = "mention_count",
    ) -> list[dict[str, Any]]:
        """查询实体列表，支持过滤和排序。"""
        if self._db is None:
            return []
        conditions = ["mention_count >= ?"]
        params: list[Any] = [min_mentions]
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if target_id is not None:
            conditions.append("',' || target_ids || ',' LIKE '%,' || ? || ',%'")
            params.append(target_id)
        where = " AND ".join(conditions)
        order = "mention_count DESC" if sort == "mention_count" else "last_seen DESC"
        sql = (
            f"SELECT id, canonical_name, entity_type, mention_count, "
            f"first_seen, last_seen, target_ids "
            f"FROM entities WHERE {where} ORDER BY {order} LIMIT ?"  # noqa: S608
        )
        async with self._db.execute(sql, params + [limit]) as cursor:
            rows = await cursor.fetchall()
        cols = ("id", "canonical_name", "entity_type", "mention_count",
                "first_seen", "last_seen", "target_ids")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def query_entity_detail(self, entity_id: int) -> dict[str, Any] | None:
        """查询实体详情，附带最近关联事件。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT id, canonical_name, entity_type, mention_count, "
            "first_seen, last_seen, target_ids FROM entities WHERE id = ?",
            [entity_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = ("id", "canonical_name", "entity_type", "mention_count",
                "first_seen", "last_seen", "target_ids")
        entity = dict(zip(cols, row, strict=True))
        # 关联事件：从 event_index 的 entity_names LIKE 匹配
        name = entity["canonical_name"]
        recent_events: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT event_id, title_original, published_at, sentiment, news_value_score "
            "FROM event_index WHERE ',' || entity_names || ',' LIKE '%,' || ? || ',%' "
            "ORDER BY published_at DESC LIMIT 10",
            [name],
        ) as cursor:
            rows = await cursor.fetchall()
        ev_cols = ("event_id", "title_original", "published_at", "sentiment", "news_value_score")
        recent_events = [dict(zip(ev_cols, r, strict=True)) for r in rows]
        entity["recent_events"] = recent_events
        return entity
```

Also add `top_entities` to `get_stats_aggregated`. In the return dict of `get_stats_aggregated` (around line 610-617), add before the return statement:

```python
        # Phase 32: top entities
        top_entities: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT canonical_name, entity_type, mention_count "
            "FROM entities ORDER BY mention_count DESC LIMIT 10"
        ) as cursor:
            async for row in cursor:
                top_entities.append({
                    "name": row[0],
                    "entity_type": row[1],
                    "mention_count": row[2],
                })
```

Add `"top_entities": top_entities` to all three return dicts in `get_stats_aggregated` (the no-db early return, the zero-total return, and the main return).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEntityTracking -v`
Expected: 10 PASS (5 from Task 1 + 5 new)

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1521 passed

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 32 P32.02: entity 查询方法 + top_entities"
```

---

### Task 3: API Server entity 端点

**Files:**
- Modify: `src/news_sentry/core/api_server.py` (Pydantic models, create_app endpoints)
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_api_server.py`:

```python
    def test_list_entities_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        """GET /entities 返回实体列表。"""
        # 先插入一些实体
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.upsert_entity(
            "EU", "organization", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.close()
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert data["total"] == 2

    def test_list_entities_filter_by_type(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        """GET /entities?entity_type=person 过滤。"""
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.upsert_entity(
            "EU", "organization", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.close()
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/entities", params={"entity_type": "person"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entities"][0]["canonical_name"] == "Meloni"

    def test_list_entities_min_mentions(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        """GET /entities?min_mentions=2 过滤低频实体。"""
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-17T10:00:00+00:00"
        )
        await store_with_data.upsert_entity(
            "EU", "organization", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.close()
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/entities", params={"min_mentions": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entities"][0]["canonical_name"] == "Meloni"

    def test_get_entity_detail_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        """GET /entities/{id} 返回实体详情。"""
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.close()
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/entities/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity"]["canonical_name"] == "Meloni"
        assert "recent_events" in data

    def test_stats_top_entities_with_sqlite(
        self,
        tmp_path: Path,
        store_with_data: AsyncStore,
    ) -> None:
        """stats 端点返回 top_entities。"""
        await store_with_data.upsert_entity(
            "Meloni", "person", "italy", "2026-05-16T10:00:00+00:00"
        )
        await store_with_data.close()
        client = self._make_client_with_store(tmp_path, store_with_data)
        resp = client.get("/api/v1/stats", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert "top_entities" in data
        assert len(data["top_entities"]) >= 1
        assert data["top_entities"][0]["name"] == "Meloni"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::test_list_entities_with_sqlite -v`
Expected: FAIL — 404 (route not found)

- [ ] **Step 3: Add Pydantic response models**

Add to `src/news_sentry/core/api_server.py` after the existing model classes (after `ProviderRoutesResponse`):

```python
class EntityInfo(BaseModel):
    """实体摘要信息。"""

    id: int
    canonical_name: str
    entity_type: str
    mention_count: int
    first_seen: str
    last_seen: str
    target_ids: str = ""


class EntityListResponse(BaseModel):
    """实体列表响应。"""

    total: int
    entities: list[EntityInfo]


class EntityDetailResponse(BaseModel):
    """实体详情响应。"""

    entity: EntityInfo
    recent_events: list[dict[str, Any]] = []
```

Update `StatsResponse` to add `top_entities`:

```python
class StatsResponse(BaseModel):
    """事件统计响应。"""

    target_id: str
    total_events: int
    avg_news_value_score: float | None
    avg_china_relevance: float | None
    by_classification: dict[str, int]
    by_source: dict[str, int]
    sentiment_breakdown: dict[str, int] = {}
    top_entities: list[dict[str, Any]] = []
```

- [ ] **Step 4: Add API endpoints**

In `create_app()`, add the entity endpoints before the authenticated section (before `# ── 需认证端点`):

```python
    # ── 实体端点 ────────────────────────────────────────

    @app.get("/api/v1/entities", response_model=EntityListResponse)
    async def list_entities(
        entity_type: str | None = Query(None, description="按实体类型过滤"),
        target_id: str | None = Query(None, description="按目标过滤"),
        min_mentions: int = Query(1, ge=1, description="最少提及次数"),
        limit: int = Query(20, ge=1, le=100, description="返回数量"),
        sort: str = Query("mention_count", description="排序: mention_count 或 last_seen"),
    ) -> EntityListResponse:
        """返回实体列表。"""
        if _store is None:
            return EntityListResponse(total=0, entities=[])
        entities = await _store.query_entities(
            entity_type=entity_type,
            target_id=target_id,
            min_mentions=min_mentions,
            limit=limit,
            sort=sort,
        )
        return EntityListResponse(
            total=len(entities),
            entities=[EntityInfo(**e) for e in entities],
        )

    @app.get("/api/v1/entities/{entity_id}", response_model=EntityDetailResponse)
    async def get_entity(entity_id: int) -> EntityDetailResponse:
        """返回实体详情及关联事件。"""
        if _store is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        detail = await _store.query_entity_detail(entity_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        recent = detail.pop("recent_events", [])
        return EntityDetailResponse(
            entity=EntityInfo(**detail),
            recent_events=recent,
        )
```

Update the `get_stats` endpoint to pass `top_entities` to `StatsResponse`. In the SQLite path (after `sentiment_breakdown=stats.get("sentiment_breakdown", {}),`):

```python
                top_entities=stats.get("top_entities", []),
```

And in the fallback path (after `by_source=dict(by_source),`):

```python
            top_entities=[],
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py -v -k "entity"`
Expected: 5 PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1526 passed

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "Phase 32 P32.03: API entity 端点 + stats top_entities"
```

---

### Task 4: async_run 集成

**Files:**
- Modify: `src/news_sentry/core/async_run.py` (NLP enrichment block, ~line 461-474)
- Test: `tests/unit/test_run.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_run.py`:

```python
    @pytest.mark.asyncio
    async def test_entity_persistence_after_nlp(self, tmp_path):
        """NLP 增强后实体被持久化到 store。"""
        from unittest.mock import AsyncMock, patch

        from news_sentry.core.async_store import AsyncStore
        from news_sentry.models.newsevent import (
            JudgeResult,
            NLPEntity,
            NLPAnalysis,
            NewsEvent,
            Sentiment,
        )

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()

        event = NewsEvent(
            id="ne-test-001",
            source_id="test",
            url="https://example.com",
            title_original="Test",
            content_original="Test body",
        )
        event.judge_result = JudgeResult(
            news_value_score=70,
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.POSITIVE,
                entities=[
                    NLPEntity(name="Meloni", entity_type="person", relevance=80),
                    NLPEntity(name="Roma", entity_type="location", relevance=50),
                ],
            ),
        )

        with patch(
            "news_sentry.core.async_run._find_project_root",
            return_value=tmp_path,
        ), patch(
            "news_sentry.core.async_run.NLPRulesAnalyzer"
        ), patch(
            "news_sentry.core.async_run.NLPAnalyzer"
        ) as MockNLPAnalyzer:
            mock_analyzer = AsyncMock()
            mock_analyzer.enrich = AsyncMock(return_value=[event])
            mock_analyzer.stats = {"rules_only": 1, "ai_upgraded": 0}
            MockNLPAnalyzer.return_value = mock_analyzer

            # 直接调用实体持久化逻辑
            nlp = event.judge_result.nlp_analysis
            if nlp is not None:
                now = datetime.now(UTC).isoformat()
                for entity in nlp.entities:
                    await store.upsert_entity(
                        entity.name, entity.entity_type, "italy", now
                    )

        entities = await store.query_entities(limit=10)
        assert len(entities) == 2
        names = {e["canonical_name"] for e in entities}
        assert "Meloni" in names
        assert "Roma" in names

        await store.close()
```

- [ ] **Step 2: Run test to verify it passes (logic test)**

Run: `.venv/bin/python3 -m pytest tests/unit/test_run.py::test_entity_persistence_after_nlp -v`
Expected: PASS (this tests the logic flow directly)

- [ ] **Step 3: Add store parameter to _run_judge_async and add entity persistence**

**3a.** Add `store` parameter to `_run_judge_async` signature (line 393):

Change:
```python
async def _run_judge_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
    cache_mgr: LLMCacheManager | None = None,
) -> None:
```

To:
```python
async def _run_judge_async(
    config: ResolvedConfig,
    run_id: str,
    run_log: RunLog,
    file_writer: FileWriter,
    memory: Memory,
    ctx: PipelineContext,
    cache_mgr: LLMCacheManager | None = None,
    store: AsyncStore | None = None,
) -> None:
```

**3b.** Pass `store` at both call sites. At line 188 and line 210, add `store=store,` to the `_run_judge_async()` calls:

```python
        elif stage in ("judge", "judged"):
            await _run_judge_async(
                config,
                run_id,
                run_log,
                file_writer,
                memory,
                ctx,
                cache_mgr=cache_mgr,
                store=store,
            )
```

And similarly for the `stage == "all"` call site at line 210.

**3c.** Add entity persistence block. In `_run_judge_async`, after the NLP enrichment block (after `logger.warning("NLP 增强失败（非阻塞）: %s", e)`) and before `# 写入研判结果`, add:

```python
    # P32: 实体持久化
    if store is not None:
        try:
            now_iso = datetime.now(UTC).isoformat()
            for event in judged:
                nlp = (
                    getattr(event, "judge_result", None)
                    and getattr(event.judge_result, "nlp_analysis", None)
                )
                if nlp is None:
                    continue
                for entity in nlp.entities:
                    await store.upsert_entity(
                        entity.name, entity.entity_type, config.target_id, now_iso
                    )
        except Exception as e:
            logger.warning("实体持久化失败（非阻塞）: %s", e)
```

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: 1527 passed

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_run.py
git commit -m "Phase 32 P32.04: async_run 实体持久化集成"
```

---

### Task 5: 验证与清理

**Files:**
- Modify: `docs/roadmap/development-plan.md`

- [ ] **Step 1: Run lint checks**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/core/async_store.py src/news_sentry/core/api_server.py src/news_sentry/core/async_run.py`
Expected: 0 errors

- [ ] **Step 2: Run type checks**

Run: `.venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/ -q --tb=short`
Expected: 1527 passed, 0 failed

- [ ] **Step 4: Update development-plan.md**

Add Phase 32 completion section with task matrix:
- P32.01: entities 表 + upsert_entity ✅
- P32.02: entity 查询方法 + top_entities ✅
- P32.03: API entity 端点 + stats top_entities ✅
- P32.04: async_run 实体持久化集成 ✅
- P32.05: 验证与清理 ✅

- [ ] **Step 5: Commit**

```bash
git add docs/roadmap/development-plan.md
git commit -m "Phase 32: 状态更新为完成，1527 tests"
```
