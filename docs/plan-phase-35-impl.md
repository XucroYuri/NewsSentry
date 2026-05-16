# Phase 35: 事件追踪链 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于实体/主题/时间信号自动发现事件间关联关系，构建追踪链并在 Web UI 中展示。

**Architecture:** 在 AsyncStore 新增 event_links 表存储关联关系，pipeline judge 阶段后执行本地规则关联扫描，3 个新 API 端点暴露关联数据，前端新增追踪链列表页和时间线详情页。

**Tech Stack:** SQLite / aiosqlite / FastAPI / Vanilla JS ES Modules

---

### Task 1: AsyncStore event_links 表 + 4 个查询方法

**Files:**
- Modify: `src/news_sentry/core/async_store.py:88-99` (DDL + INDEXES)
- Modify: `src/news_sentry/core/async_store.py:793` (新增方法)
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写失败测试 — event_links 表创建**

在 `tests/unit/test_async_store.py` 末尾追加测试类 `TestEventLinks`：

```python
class TestEventLinks:
    """Phase 35: event_links 表 + 关联查询方法。"""

    @pytest.fixture
    async def store_with_links(self, tmp_path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        yield store
        await store.close()

    async def test_event_links_table_created(self, store_with_links):
        """event_links 表在 initialize 时自动创建。"""
        store = store_with_links
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_links'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None

    async def test_create_and_get_link(self, store_with_links):
        """create_link 写入关联，get_event_links 读回。"""
        store = store_with_links
        # 先写入两个事件到 event_index
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, entity_names, topic_tags, title_original, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-a", "italy", "drafts", "2026-05-16T10:00:00+00:00", "Meloni,EU", "politics,eu", "Meloni visits EU", "2026-05-16T10:00:00+00:00"),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, entity_names, topic_tags, title_original, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-b", "italy", "drafts", "2026-05-16T14:00:00+00:00", "Meloni,EU", "politics", "EU responds to Meloni", "2026-05-16T14:00:00+00:00"),
        )
        await store._db.commit()

        await store.create_link(
            source_event_id="evt-a",
            target_event_id="evt-b",
            link_type="followup",
            strength=0.82,
            signals={"entity_overlap": 0.8, "topic_match": 0.5, "time_proximity": 1.0},
            target_id="italy",
        )
        links = await store.get_event_links("evt-a")
        assert len(links) == 1
        assert links[0]["target_event_id"] == "evt-b"
        assert links[0]["link_type"] == "followup"
        assert links[0]["strength"] == pytest.approx(0.82)

    async def test_create_link_unique_constraint(self, store_with_links):
        """重复写入相同关联会被忽略。"""
        store = store_with_links
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at) VALUES (?, ?, ?, ?)",
            ("evt-a", "italy", "drafts", "2026-05-16T10:00:00+00:00"),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at) VALUES (?, ?, ?, ?)",
            ("evt-b", "italy", "drafts", "2026-05-16T14:00:00+00:00"),
        )
        await store._db.commit()

        await store.create_link("evt-a", "evt-b", "followup", 0.8, {}, "italy")
        await store.create_link("evt-a", "evt-b", "followup", 0.9, {}, "italy")  # 重复
        links = await store.get_event_links("evt-a")
        assert len(links) == 1

    async def test_find_candidates(self, store_with_links):
        """find_candidates 返回同一 target 最近 N 天的事件。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, entity_names, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("evt-old", "italy", "drafts", now, now, "Meloni", "politics"),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, entity_names, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("evt-new", "italy", "drafts", now, now, "Meloni,EU", "politics,eu"),
        )
        await store._db.commit()

        candidates = await store.find_candidates("italy", "evt-new", days=7)
        assert len(candidates) == 1  # 排除自身
        assert candidates[0]["event_id"] == "evt-old"

    async def test_get_event_chain(self, store_with_links):
        """get_event_chain 向前向后遍历关联链。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2", "evt-3"):
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.create_link("evt-2", "evt-3", "followup", 0.7, {}, "italy")

        chain = await store.get_event_chain("evt-2", depth=5)
        event_ids = [e["event_id"] for e in chain]
        assert "evt-1" in event_ids
        assert "evt-2" in event_ids
        assert "evt-3" in event_ids

    async def test_get_active_chains(self, store_with_links):
        """get_active_chains 返回有 >=2 事件的链。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        chains = await store.get_active_chains("italy")
        assert len(chains) >= 1
        root_ids = [c["root_event_id"] for c in chains]
        assert "evt-1" in root_ids

    async def test_get_event_links_empty(self, store_with_links):
        """无关联事件时返回空列表。"""
        store = store_with_links
        links = await store.get_event_links("nonexistent")
        assert links == []

    async def test_find_candidates_excludes_self(self, store_with_links):
        """find_candidates 排除事件自身。"""
        store = store_with_links
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("evt-only", "italy", "drafts", now, now),
        )
        await store._db.commit()

        candidates = await store.find_candidates("italy", "evt-only", days=7)
        assert candidates == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventLinks -v`
Expected: FAIL — `AsyncStore` 没有 `create_link`, `get_event_links`, `find_candidates`, `get_event_chain`, `get_active_chains` 方法

- [ ] **Step 3: 实现 event_links 表 + 4 个方法**

在 `src/news_sentry/core/async_store.py` 中：

**3a.** 在 `_DDL_ENTITIES` 后面（~第 88 行）新增 DDL：

```python
_DDL_EVENT_LINKS = """
CREATE TABLE IF NOT EXISTS event_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    signals TEXT NOT NULL DEFAULT '{}',
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_event_id, target_event_id, link_type)
)
"""
```

**3b.** 在 `_DDL_INDEXES` 中追加索引：

```python
    "CREATE INDEX IF NOT EXISTS idx_event_links_source ON event_links(source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target ON event_links(target_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_target_id ON event_links(target_id)",
```

**3c.** 在 `initialize()` 方法中，`await self._db.execute(_DDL_ENTITIES)` 之后追加：

```python
        await self._db.execute(_DDL_EVENT_LINKS)
```

**3d.** 在文件末尾（`query_entity_detail` 方法之后）新增 4 个方法：

```python
    # ------------------------------------------------------------------
    # Event Links (Phase 35)
    # ------------------------------------------------------------------

    async def create_link(
        self,
        source_event_id: str,
        target_event_id: str,
        link_type: str,
        strength: float,
        signals: dict[str, Any],
        target_id: str,
    ) -> None:
        """写入事件关联（UNIQUE 约束去重）。"""
        if self._db is None:
            return
        signals_json = json.dumps(signals, ensure_ascii=False)
        await self._db.execute(
            """INSERT OR IGNORE INTO event_links
               (source_event_id, target_event_id, link_type, strength, signals, target_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_event_id, target_event_id, link_type, strength, signals_json, target_id),
        )
        await self._db.commit()

    async def get_event_links(self, event_id: str) -> list[dict[str, Any]]:
        """获取某事件的所有直接关联（双向）。"""
        if self._db is None:
            return []
        results: list[dict[str, Any]] = []
        # 作为 source 的关联
        async with self._db.execute(
            "SELECT target_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE source_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append({
                    "linked_event_id": row[0],
                    "link_type": row[1],
                    "strength": row[2],
                    "direction": "forward",
                    "signals": json.loads(row[3]) if row[3] else {},
                    "created_at": row[4],
                })
        # 作为 target 的关联
        async with self._db.execute(
            "SELECT source_event_id, link_type, strength, signals, created_at "
            "FROM event_links WHERE target_event_id = ?",
            [event_id],
        ) as cursor:
            async for row in cursor:
                results.append({
                    "linked_event_id": row[0],
                    "link_type": row[1],
                    "strength": row[2],
                    "direction": "backward",
                    "signals": json.loads(row[3]) if row[3] else {},
                    "created_at": row[4],
                })
        return results

    async def find_candidates(
        self,
        target_id: str,
        event_id: str,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """查找同一 target 最近 N 天的候选关联事件（排除自身）。"""
        if self._db is None:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        async with self._db.execute(
            "SELECT event_id, entity_names, topic_tags, published_at, title_original "
            "FROM event_index WHERE target_id = ? AND event_id != ? "
            "AND published_at >= ? ORDER BY published_at DESC",
            [target_id, event_id, cutoff],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = ("event_id", "entity_names", "topic_tags", "published_at", "title_original")
        return [dict(zip(cols, row, strict=True)) for row in rows]

    async def get_event_chain(
        self,
        event_id: str,
        depth: int = 5,
    ) -> list[dict[str, Any]]:
        """向前向后遍历关联链，返回链上所有事件。"""
        if self._db is None:
            return []
        visited: set[str] = set()
        chain_events: list[dict[str, Any]] = []

        # 收集链上所有 event_id
        queue = [event_id]
        visited.add(event_id)
        while queue and len(visited) < depth * 2 + 1:
            current = queue.pop(0)
            # 查找关联
            linked_ids: set[str] = set()
            async with self._db.execute(
                "SELECT target_event_id FROM event_links WHERE source_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            async with self._db.execute(
                "SELECT source_event_id FROM event_links WHERE target_event_id = ?",
                [current],
            ) as cursor:
                async for row in cursor:
                    linked_ids.add(row[0])
            for lid in linked_ids:
                if lid not in visited:
                    visited.add(lid)
                    queue.append(lid)

        # 批量查询事件信息
        if not visited:
            return []
        placeholders = ",".join("?" for _ in visited)
        async with self._db.execute(
            f"SELECT event_id, title_original, published_at FROM event_index "  # noqa: S608
            f"WHERE event_id IN ({placeholders}) ORDER BY published_at ASC",
            list(visited),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            chain_events.append({
                "event_id": row[0],
                "title_original": row[1],
                "published_at": row[2],
            })
        return chain_events

    async def get_active_chains(self, target_id: str) -> list[dict[str, Any]]:
        """返回当前 target 的活跃追踪链（有 >=2 事件的链）。"""
        if self._db is None:
            return []
        # 找出所有有 source 的 event_id（即链的根节点）
        async with self._db.execute(
            "SELECT DISTINCT el.source_event_id "
            "FROM event_links el "
            "WHERE el.target_id = ? "
            "AND el.source_event_id NOT IN (SELECT target_event_id FROM event_links)",
            [target_id],
        ) as cursor:
            root_rows = await cursor.fetchall()

        # 如果没有纯根节点，找所有 source_event_id
        if not root_rows:
            async with self._db.execute(
                "SELECT DISTINCT source_event_id FROM event_links WHERE target_id = ?",
                [target_id],
            ) as cursor:
                root_rows = await cursor.fetchall()

        chains: list[dict[str, Any]] = []
        for (root_id,) in root_rows:
            chain = await self.get_event_chain(root_id, depth=10)
            if len(chain) >= 2:
                latest = chain[-1]
                chains.append({
                    "root_event_id": root_id,
                    "event_count": len(chain),
                    "latest_time": latest.get("published_at", ""),
                    "latest_title": latest.get("title_original", ""),
                })
        return sorted(chains, key=lambda c: c["latest_time"], reverse=True)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventLinks -v`
Expected: 8/8 PASS

- [ ] **Step 5: 全量回归测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Expected: 1535+ tests passed, 0 failed

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 35 P35.01: AsyncStore event_links 表 + 关联查询方法"
```

---

### Task 2: Pipeline 集成 — link_events 协程

**Files:**
- Modify: `src/news_sentry/core/async_run.py:495-503` (judge 阶段末尾插入)
- Test: `tests/unit/test_async_run.py`

- [ ] **Step 1: 写失败测试 — link_events 协程**

在 `tests/unit/test_async_run.py` 末尾追加：

```python
class TestLinkEvents:
    """Phase 35: link_events 协程测试。"""

    async def test_link_events_creates_links(self, tmp_path):
        """link_events 对新事件执行关联扫描并写入 event_links。"""
        from news_sentry.core.async_store import AsyncStore
        from news_sentry.core.async_run import _link_events

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        # 模拟已有事件（带 NLP 字段）
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "entity_names, topic_tags, title_original) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-old", "italy", "drafts", now, now, "Meloni,EU", "politics,eu", "Meloni visits EU"),
        )
        await store._db.commit()

        # 模拟新事件
        from unittest.mock import MagicMock
        new_event = MagicMock()
        new_event.id = "evt-new"
        new_event.title_original = "EU responds to Meloni"
        new_event.published_at = "2026-05-16T14:00:00+00:00"
        judge_result = MagicMock()
        nlp = MagicMock()
        nlp.entities = [MagicMock(name="Meloni"), MagicMock(name="EU")]
        nlp.topic_tags = ["politics", "eu"]
        judge_result.nlp_analysis = nlp
        new_event.judge_result = judge_result

        await _link_events(store, [new_event], "italy")

        links = await store.get_event_links("evt-new")
        assert len(links) >= 1

        await store.close()

    async def test_link_events_failure_nonblocking(self, tmp_path):
        """link_events 失败时不抛异常。"""
        from news_sentry.core.async_store import AsyncStore
        from news_sentry.core.async_run import _link_events
        from unittest.mock import MagicMock

        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        await store.close()

        new_event = MagicMock()
        new_event.id = "evt-test"
        # store 已关闭，操作应失败但不抛异常
        await _link_events(store, [new_event], "italy")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestLinkEvents -v`
Expected: FAIL — `_link_events` 不存在

- [ ] **Step 3: 实现 _link_events 协程**

在 `src/news_sentry/core/async_run.py` 中，`_run_output_async` 函数之前（~第 505 行）插入：

```python
async def _link_events(
    store: AsyncStore,
    events: list[NewsEvent],
    target_id: str,
) -> None:
    """Phase 35: 对新事件执行关联扫描。

    基于实体重叠 + 主题匹配 + 时间接近计算关联强度，
    满足阈值则写入 event_links 表。失败不阻塞 pipeline。
    """
    if store._db is None or not events:
        return
    try:
        for event in events:
            candidates = await store.find_candidates(target_id, event.id, days=7)
            if not candidates:
                continue

            # 提取新事件的 NLP 字段
            nlp = getattr(event, "judge_result", None) and getattr(
                event.judge_result, "nlp_analysis", None
            )
            if nlp is None:
                continue

            new_entities = set(e.name for e in nlp.entities) if nlp.entities else set()
            new_topics = set(nlp.topic_tags) if nlp.topic_tags else set()
            new_time = datetime.fromisoformat(event.published_at) if getattr(event, "published_at", None) else datetime.now(UTC)

            for candidate in candidates:
                # 实体重叠
                cand_entities = set(
                    candidate["entity_names"].split(",")
                    if candidate.get("entity_names")
                    else []
                )
                cand_entities.discard("")
                if not new_entities or not cand_entities:
                    entity_overlap = 0.0
                else:
                    common = new_entities & cand_entities
                    entity_overlap = len(common) / max(len(new_entities), len(cand_entities))

                # 主题匹配 (Jaccard)
                cand_topics = set(
                    candidate["topic_tags"].split(",")
                    if candidate.get("topic_tags")
                    else []
                )
                cand_topics.discard("")
                if not new_topics or not cand_topics:
                    topic_match = 0.0
                else:
                    topic_match = len(new_topics & cand_topics) / len(new_topics | cand_topics)

                # 时间接近
                cand_time_str = candidate.get("published_at")
                if cand_time_str:
                    try:
                        cand_time = datetime.fromisoformat(cand_time_str)
                        hours_diff = abs((new_time - cand_time).total_seconds()) / 3600
                        time_proximity = max(0.0, 1.0 - hours_diff / 168)  # 7天=168小时
                    except (ValueError, TypeError):
                        time_proximity = 0.0
                else:
                    time_proximity = 0.0

                # 加权计算
                strength = entity_overlap * 0.4 + topic_match * 0.3 + time_proximity * 0.3

                if strength >= 0.4:
                    # 判断 link_type
                    common_count = len(new_entities & cand_entities)
                    if common_count >= 2 and strength >= 0.7:
                        link_type = "followup"
                    elif common_count >= 2:
                        link_type = "related"
                    else:
                        link_type = "related"

                    await store.create_link(
                        source_event_id=candidate["event_id"],
                        target_event_id=event.id,
                        link_type=link_type,
                        strength=round(strength, 3),
                        signals={
                            "entity_overlap": round(entity_overlap, 3),
                            "topic_match": round(topic_match, 3),
                            "time_proximity": round(time_proximity, 3),
                        },
                        target_id=target_id,
                    )
    except Exception as e:
        logger.warning("事件关联扫描失败（非阻塞）: %s", e)
```

- [ ] **Step 4: 集成到 pipeline**

在 `src/news_sentry/core/async_run.py` 的 `_run_judge_async` 函数中，实体持久化块之后（~第 494 行 `except ...` 之后）、`# 写入研判结果` 之前，插入：

```python
    # P35: 事件关联扫描
    try:
        await _link_events(store, judged, config.target_id)
    except Exception as e:
        logger.warning("事件关联扫描失败（非阻塞）: %s", e)
```

同时将 `_link_events` 调用用 `if store is not None:` 保护：

```python
    # P35: 事件关联扫描
    if store is not None:
        try:
            await _link_events(store, judged, config.target_id)
        except Exception as e:
            logger.warning("事件关联扫描失败（非阻塞）: %s", e)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestLinkEvents -v`
Expected: 2/2 PASS

- [ ] **Step 6: 全量回归测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Expected: 1537+ tests passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_async_run.py
git commit -m "Phase 35 P35.02: pipeline 集成 link_events 关联扫描"
```

---

### Task 3: API 端点 — links / chain / chains

**Files:**
- Modify: `src/news_sentry/core/api_server.py` (3 新端点 + Pydantic 模型)
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_api_server.py` 末尾追加：

```python
class TestEventChainAPI:
    """Phase 35: 事件追踪链 API 端点。"""

    @pytest.fixture
    async def client_with_links(self, tmp_path):
        """创建带关联数据的测试客户端。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        # 插入事件
        for eid, title in [("evt-1", "Event One"), ("evt-2", "Event Two"), ("evt-3", "Event Three")]:
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, title),
            )
        await store._db.commit()

        # 创建关联链: evt-1 → evt-2 → evt-3
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.create_link("evt-2", "evt-3", "followup", 0.7, {}, "italy")

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        yield client, store
        await client.aclose()
        await store.close()

    async def test_get_event_links(self, client_with_links):
        """GET /api/v1/events/{event_id}/links 返回关联事件。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/evt-2/links", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == "evt-2"
        assert len(data["links"]) == 2  # 前后各一个

    async def test_get_event_chain(self, client_with_links):
        """GET /api/v1/events/{event_id}/chain 返回完整追踪链。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/evt-2/chain", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        event_ids = [e["event_id"] for e in data["events"]]
        assert "evt-1" in event_ids
        assert "evt-2" in event_ids
        assert "evt-3" in event_ids

    async def test_list_chains(self, client_with_links):
        """GET /api/v1/chains 返回活跃链列表。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/chains", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chains"]) >= 1
        assert data["chains"][0]["event_count"] == 3

    async def test_get_event_links_not_found(self, client_with_links):
        """GET /api/v1/events/{event_id}/links 对不存在的事件返回空。"""
        client, _ = client_with_links
        resp = await client.get("/api/v1/events/nonexistent/links", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["links"] == []
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestEventChainAPI -v`
Expected: FAIL — 404 (端点不存在)

- [ ] **Step 3: 实现 3 个端点**

在 `src/news_sentry/core/api_server.py` 中：

**3a.** 在 Pydantic 模型区域（`TriggerResponse` 之后）新增：

```python
class EventLinkInfo(BaseModel):
    """事件关联条目。"""

    linked_event_id: str
    link_type: str
    strength: float
    direction: str
    signals: dict[str, Any] = {}
    linked_event_title: str | None = None
    linked_event_time: str | None = None


class EventLinksResponse(BaseModel):
    """事件关联列表响应。"""

    event_id: str
    links: list[EventLinkInfo]


class ChainEventInfo(BaseModel):
    """链中事件条目。"""

    event_id: str
    title_original: str | None = None
    published_at: str | None = None
    link_type: str | None = None


class EventChainResponse(BaseModel):
    """事件追踪链响应。"""

    chain_id: str
    events: list[ChainEventInfo]
    total: int


class ChainSummaryInfo(BaseModel):
    """追踪链摘要。"""

    root_event_id: str
    event_count: int
    latest_time: str = ""
    latest_title: str = ""


class ChainListResponse(BaseModel):
    """追踪链列表响应。"""

    chains: list[ChainSummaryInfo]
```

**3b.** 在 `create_app()` 中，运维端点区域之后（`trigger_run` 端点之后）、静态文件挂载之前，新增 3 个端点：

```python
    # ── Phase 35: 追踪链端点 ──────────────────────────────

    @app.get("/api/v1/events/{event_id}/links", response_model=EventLinksResponse)
    async def get_event_links(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> EventLinksResponse:
        """获取某事件的关联事件列表。"""
        if _store is None:
            return EventLinksResponse(event_id=event_id, links=[])
        links = await _store.get_event_links(event_id)
        result_links: list[EventLinkInfo] = []
        for link in links:
            # 查询关联事件的标题和时间
            linked_id = link["linked_event_id"]
            title = None
            time_str = None
            async with _store._db.execute(
                "SELECT title_original, published_at FROM event_index WHERE event_id = ?",
                [linked_id],
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    title = row[0]
                    time_str = row[1]
            result_links.append(
                EventLinkInfo(
                    linked_event_id=linked_id,
                    link_type=link["link_type"],
                    strength=link["strength"],
                    direction=link["direction"],
                    signals=link.get("signals", {}),
                    linked_event_title=title,
                    linked_event_time=time_str,
                )
            )
        return EventLinksResponse(event_id=event_id, links=result_links)

    @app.get("/api/v1/events/{event_id}/chain", response_model=EventChainResponse)
    async def get_event_chain(
        event_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> EventChainResponse:
        """获取某事件的完整追踪链。"""
        if _store is None:
            return EventChainResponse(chain_id=event_id, events=[], total=0)
        chain = await _store.get_event_chain(event_id, depth=5)
        events: list[ChainEventInfo] = []
        for ce in chain:
            events.append(
                ChainEventInfo(
                    event_id=ce["event_id"],
                    title_original=ce.get("title_original"),
                    published_at=ce.get("published_at"),
                    link_type=ce.get("link_type"),
                )
            )
        return EventChainResponse(chain_id=event_id, events=events, total=len(events))

    @app.get("/api/v1/chains", response_model=ChainListResponse)
    async def list_chains(
        target_id: str = Query(..., description="目标标识"),
    ) -> ChainListResponse:
        """列出当前 target 的活跃追踪链。"""
        if _store is None:
            return ChainListResponse(chains=[])
        chains = await _store.get_active_chains(target_id)
        return ChainListResponse(
            chains=[ChainSummaryInfo(**c) for c in chains],
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestEventChainAPI -v`
Expected: 4/4 PASS

- [ ] **Step 5: 全量回归测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Expected: 1541+ tests passed, 0 failed

- [ ] **Step 6: Lint 检查**

Run: `ruff check src/news_sentry/core/api_server.py src/news_sentry/core/async_store.py src/news_sentry/core/async_run.py`
Run: `.venv/bin/python3 -m mypy src/news_sentry/ --ignore-missing-imports`
Expected: 0 errors

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "Phase 35 P35.03: 追踪链 API 端点 (links/chain/chains)"
```

---

### Task 4: 前端追踪链页面 + 事件详情增强 + 验收

**Files:**
- Create: `src/news_sentry/static/pages/chains.js`
- Modify: `src/news_sentry/static/app.js` (路由 + import)
- Modify: `src/news_sentry/static/pages/events.js` (关联事件卡片)
- Modify: `src/news_sentry/static/index.html` (侧边栏入口)
- Modify: `src/news_sentry/static/style.css` (时间线样式)
- Modify: `docs/development-plan.md` (Phase 35 状态更新)

- [ ] **Step 1: 创建 chains.js 追踪链页面**

创建 `src/news_sentry/static/pages/chains.js`：

```javascript
/**
 * Phase 35: 追踪链页面
 * 追踪链列表 + 链详情时间线
 */

"use strict";

import { state, dom, $, api, escapeHtml, showError } from "../api.js";

const LINK_TYPE_LABELS = {
  followup: "后续进展",
  related: "相关事件",
  same_event: "同一事件",
  correction: "纠正/反转",
};

const LINK_TYPE_COLORS = {
  followup: "#3b82f6",
  related: "#6b7280",
  same_event: "#10b981",
  correction: "#ef4444",
};

export async function renderChainList() {
  dom.pageContainer.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链...</p></div>';

  try {
    const data = await api(`/api/v1/chains?target_id=${state.currentTarget}`);

    if (!data.chains || data.chains.length === 0) {
      dom.pageContainer.innerHTML = `
        <div class="empty-state">
          <p>暂无追踪链数据</p>
          <p class="hint">运行 pipeline 后，系统会自动发现事件间的关联关系</p>
        </div>`;
      return;
    }

    const statsHtml = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${data.chains.length}</div>
          <div class="stat-label">活跃追踪链</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${Math.max(...data.chains.map(c => c.event_count))}</div>
          <div class="stat-label">最大链长度</div>
        </div>
      </div>`;

    const chainRows = data.chains.map(c => `
      <tr class="chain-row" data-root="${escapeHtml(c.root_event_id)}" onclick="location.hash='#/chains/${encodeURIComponent(c.root_event_id)}'">
        <td>${escapeHtml(c.root_event_id)}</td>
        <td><span class="badge badge-count">${c.event_count}</span></td>
        <td>${c.latest_time ? new Date(c.latest_time).toLocaleString("zh-CN") : "-"}</td>
        <td>${escapeHtml(c.latest_title || "-")}</td>
      </tr>`).join("");

    dom.pageContainer.innerHTML = `
      ${statsHtml}
      <div class="section-card">
        <h3>追踪链列表</h3>
        <table class="data-table">
          <thead>
            <tr><th>根事件</th><th>事件数</th><th>最新时间</th><th>最新标题</th></tr>
          </thead>
          <tbody>${chainRows}</tbody>
        </table>
      </div>`;
  } catch (err) {
    showError(`加载追踪链失败: ${err.message}`);
  }
}

export async function renderChainDetail(rootEventId) {
  dom.pageContainer.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>加载追踪链详情...</p></div>';

  try {
    const data = await api(`/api/v1/events/${encodeURIComponent(rootEventId)}/chain?target_id=${state.currentTarget}`);

    if (!data.events || data.events.length === 0) {
      dom.pageContainer.innerHTML = '<div class="empty-state"><p>追踪链为空</p></div>';
      return;
    }

    const headerHtml = `
      <div class="chain-header">
        <a href="#/chains" class="back-link">&larr; 返回追踪链列表</a>
        <h3>追踪链: ${escapeHtml(data.chain_id)}</h3>
        <span class="badge badge-count">${data.total} 个事件</span>
      </div>`;

    const timelineHtml = data.events.map((evt, i) => {
      const linkType = evt.link_type;
      const color = linkType ? (LINK_TYPE_COLORS[linkType] || "#6b7280") : "#3b82f6";
      const label = linkType ? (LINK_TYPE_LABELS[linkType] || linkType) : "起始事件";
      const isLast = i === data.events.length - 1;
      return `
        <div class="timeline-item">
          <div class="timeline-dot" style="background:${color}"></div>
          ${!isLast ? '<div class="timeline-line"></div>' : ''}
          <div class="timeline-content">
            <div class="timeline-header">
              <a href="#/events/${encodeURIComponent(evt.event_id)}" class="timeline-title">${escapeHtml(evt.title_original || evt.event_id)}</a>
              <span class="timeline-badge" style="background:${color}">${label}</span>
            </div>
            <div class="timeline-meta">
              <span class="timeline-time">${evt.published_at ? new Date(evt.published_at).toLocaleString("zh-CN") : "-"}</span>
              <span class="timeline-id">${escapeHtml(evt.event_id)}</span>
            </div>
          </div>
        </div>`;
    }).join("");

    dom.pageContainer.innerHTML = `
      ${headerHtml}
      <div class="timeline">${timelineHtml}</div>`;
  } catch (err) {
    showError(`加载追踪链详情失败: ${err.message}`);
  }
}
```

- [ ] **Step 2: 修改 app.js — 添加路由 + import**

在 `src/news_sentry/static/app.js` 中：

**2a.** 添加 import（在 ops.js import 后面）：

```javascript
import { renderChainList, renderChainDetail } from "./pages/chains.js";
```

**2b.** 在 `titles` 对象中添加：

```javascript
    chains: "追踪链",
    chain: "链详情",
```

**2c.** 在 `pageKey` 计算逻辑中添加 chains 分支（在 ops 分支后面）：

```javascript
    : page === "chains" && param ? "chain"
```

**2d.** 在路由 dispatch 中添加（ops 分支后面）：

```javascript
  } else if (page === "chains" && param) {
    renderChainDetail(param);
  } else if (page === "chains") {
    renderChainList();
  }
```

- [ ] **Step 3: 修改 index.html — 侧边栏添加入口**

在 `src/news_sentry/static/index.html` 中，"事件列表"（events）nav-item 后面、"实体追踪"（entities）nav-item 前面，插入：

```html
      <a href="#/chains" class="nav-item" data-page="chains">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
        </svg>
        <span>追踪链</span>
      </a>
```

- [ ] **Step 4: 修改 events.js — 事件详情添加关联事件卡片**

在 `src/news_sentry/static/pages/events.js` 的 `renderEventDetail` 函数中，在 NLP 分析区域 HTML 生成之后、页面 innerHTML 赋值之前，加载关联事件数据并追加 HTML：

在函数的 `try` 块内（innerHTML 赋值之后），追加关联事件加载：

```javascript
  // Phase 35: 关联事件卡片
  try {
    const linksData = await api(`/api/v1/events/${encodeURIComponent(eventId)}/links?target_id=${state.currentTarget}`);
    if (linksData.links && linksData.links.length > 0) {
      const linksHtml = linksData.links.map(l => `
        <div class="link-item" onclick="location.hash='#/events/${encodeURIComponent(l.linked_event_id)}'">
          <span class="link-direction">${l.direction === "forward" ? "→" : "←"}</span>
          <span class="link-type-badge" style="background:${LINK_TYPE_COLORS[l.link_type] || '#6b7280'}">${LINK_TYPE_LABELS[l.link_type] || l.link_type}</span>
          <span class="link-title">${escapeHtml(l.linked_event_title || l.linked_event_id)}</span>
          <span class="link-strength">${(l.strength * 100).toFixed(0)}%</span>
        </div>`).join("");
      const card = document.createElement("div");
      card.className = "section-card linked-events-card";
      card.innerHTML = `<h3>关联事件 (${linksData.links.length})</h3><div class="links-list">${linksHtml}</div>`;
      dom.pageContainer.querySelector(".nlp-section")?.after(card) || dom.pageContainer.appendChild(card);
    }
  } catch { /* 非阻塞 */ }
```

需要在 events.js 文件顶部添加常量：

```javascript
const LINK_TYPE_LABELS = { followup: "后续进展", related: "相关", same_event: "同一事件", correction: "纠正" };
const LINK_TYPE_COLORS = { followup: "#3b82f6", related: "#6b7280", same_event: "#10b981", correction: "#ef4444" };
```

- [ ] **Step 5: 添加 CSS 样式**

在 `src/news_sentry/static/style.css` 末尾追加：

```css
/* ── Phase 35: 追踪链时间线 ─────────────────────────── */

.chain-header { margin-bottom: 24px; }
.chain-header .back-link { color: var(--primary, #3b82f6); text-decoration: none; font-size: 14px; display: inline-block; margin-bottom: 8px; }
.chain-header .back-link:hover { text-decoration: underline; }
.chain-header h3 { display: inline; margin-right: 8px; }

.timeline { position: relative; padding-left: 32px; }
.timeline-item { position: relative; padding-bottom: 24px; min-height: 48px; }
.timeline-item:last-child { padding-bottom: 0; }
.timeline-dot { position: absolute; left: -32px; top: 4px; width: 14px; height: 14px; border-radius: 50%; border: 3px solid var(--bg-primary, #1a1a2e); z-index: 1; }
.timeline-line { position: absolute; left: -26px; top: 18px; width: 2px; height: calc(100% - 18px); background: var(--border, #2d2d3f); }
.timeline-content { padding: 8px 12px; background: var(--card-bg, #16213e); border-radius: 8px; }
.timeline-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.timeline-title { color: var(--text-primary, #e0e0e0); text-decoration: none; font-weight: 500; font-size: 14px; flex: 1; }
.timeline-title:hover { color: var(--primary, #3b82f6); }
.timeline-badge { color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.timeline-meta { display: flex; gap: 12px; font-size: 12px; color: var(--text-secondary, #888); }
.timeline-id { font-family: monospace; }

.linked-events-card { margin-top: 16px; }
.links-list { display: flex; flex-direction: column; gap: 8px; }
.link-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--card-bg, #16213e); border-radius: 6px; cursor: pointer; font-size: 13px; }
.link-item:hover { background: var(--border, #2d2d3f); }
.link-direction { font-size: 16px; font-weight: bold; }
.link-type-badge { color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 4px; }
.link-title { flex: 1; color: var(--text-primary, #e0e0e0); }
.link-strength { font-family: monospace; color: var(--text-secondary, #888); }

.chain-row { cursor: pointer; }
.chain-row:hover { background: rgba(59, 130, 246, 0.1); }
.badge-count { background: var(--primary, #3b82f6); color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
```

- [ ] **Step 6: 全量回归测试 + Lint**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Run: `ruff check src/news_sentry/`
Run: `.venv/bin/python3 -m mypy src/news_sentry/ --ignore-missing-imports`
Expected: All tests pass, ruff=0, mypy=0

- [ ] **Step 7: 更新 development-plan.md**

在 `docs/development-plan.md` 的 Phase 34 之后添加 Phase 35 完成状态。

- [ ] **Step 8: Commit**

```bash
git add src/news_sentry/static/pages/chains.js src/news_sentry/static/app.js src/news_sentry/static/pages/events.js src/news_sentry/static/index.html src/news_sentry/static/style.css docs/development-plan.md
git commit -m "Phase 35 P35.04: 追踪链前端页面 + 事件详情关联卡片"
```
