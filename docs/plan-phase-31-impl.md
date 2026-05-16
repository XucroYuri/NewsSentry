# Phase 31: NLP 数据 API 暴露 + SQLite 索引增强 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 frontmatter → SQLite → API 三层，让 Phase 30 产出的 NLP 数据（sentiment/entities/topic_tags/event_relations）完全可查询可消费。

**Architecture:** 窄列存储策略：SQLite event_index 增加 sentiment/entity_names/topic_tags 三列，API Server 增加对应过滤参数和情感统计。Frontmatter 同步写入完整 NLPAnalysis 数据。

**Tech Stack:** SQLite ALTER TABLE / FastAPI Query / PyYAML

**Design Spec:** `docs/plan-phase-31-nlp-api.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/skills/output/markdown_writer.py` | 修改 | `_render_frontmatter` 写入 NLP 字段 |
| `src/news_sentry/core/async_store.py` | 修改 | event_index 加 3 列 + migration + upsert + 查询 + stats |
| `src/news_sentry/core/api_server.py` | 修改 | list_events 加 3 过滤参数 + stats 加 sentiment_breakdown |
| `tests/unit/test_markdown_writer.py` | 修改 | NLP frontmatter 测试 |
| `tests/unit/test_async_store.py` | 修改 | 新列 + 过滤 + stats 测试 |
| `tests/unit/test_api_server.py` | 修改 | API 过滤 + stats 测试 |

---

### Task 1 (P31.01): Frontmatter NLP 字段写入

**Files:**
- Modify: `src/news_sentry/skills/output/markdown_writer.py:105-116`
- Modify: `tests/unit/test_markdown_writer.py`

- [ ] **Step 1: 写测试 — 在 `tests/unit/test_markdown_writer.py` 末尾添加 3 个测试**

```python
class TestFrontmatterNLP:
    """Phase 31: NLP 字段写入 frontmatter。"""

    def test_frontmatter_contains_nlp_fields(self, writer: MarkdownWriter) -> None:
        """完整 NLPAnalysis → frontmatter 包含 sentiment/nlp_entities/topic_tags/event_relations。"""
        from news_sentry.models.newsevent import NLPAnalysis, NLPEntity, Sentiment

        event = NewsEvent(
            id="ne-nlp-test-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="Test",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.PUBLISH,
                rationale="test",
                confidence=80,
                nlp_analysis=NLPAnalysis(
                    sentiment=Sentiment.NEGATIVE,
                    sentiment_confidence=90,
                    entities=[
                        NLPEntity(name="Meloni", entity_type="person", relevance=80),
                        NLPEntity(name="Roma", entity_type="location", relevance=50),
                    ],
                    topic_tags=["politics", "economy"],
                    event_relations=["与上周预算案关联"],
                ),
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert fm["sentiment"] == "negative"
        assert "nlp_entities" in fm
        assert len(fm["nlp_entities"]) == 2
        assert fm["nlp_entities"][0]["name"] == "Meloni"
        assert fm["topic_tags"] == ["politics", "economy"]
        assert fm["event_relations"] == ["与上周预算案关联"]
        # sentiment_confidence 不应写入
        assert "sentiment_confidence" not in fm

    def test_frontmatter_no_nlp_when_none(self, writer: MarkdownWriter) -> None:
        """nlp_analysis 为 None → frontmatter 不含 NLP 字段。"""
        event = NewsEvent(
            id="ne-no-nlp-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="No NLP",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.REVIEW,
                rationale="test",
                confidence=50,
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert "sentiment" not in fm
        assert "nlp_entities" not in fm
        assert "topic_tags" not in fm
        assert "event_relations" not in fm

    def test_frontmatter_nlp_empty_lists(self, writer: MarkdownWriter) -> None:
        """NLPAnalysis 有 sentiment 但 entities/topic_tags 为空 → 只写 sentiment。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        event = NewsEvent(
            id="ne-empty-nlp-001",
            run_id="run-001",
            source_id="ansa",
            url="https://example.com",
            title_original="Empty NLP",
            content_original="Body",
            language=Language.IT,
            published_at="2026-05-16T00:00:00Z",
            collected_at="2026-05-16T00:00:00Z",
            pipeline_stage=PipelineStage.JUDGED,
            judge_result=JudgeResult(
                recommendation=JudgeRecommendation.REVIEW,
                rationale="test",
                confidence=50,
                nlp_analysis=NLPAnalysis(sentiment=Sentiment.NEUTRAL),
            ),
        )
        path = writer.write(event)
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])

        assert fm["sentiment"] == "neutral"
        # 空列表不写入
        assert "nlp_entities" not in fm
        assert "topic_tags" not in fm
        assert "event_relations" not in fm
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_markdown_writer.py::TestFrontmatterNLP -v`
Expected: FAIL — `test_frontmatter_contains_nlp_fields` 断言失败（缺少 NLP 字段）

- [ ] **Step 3: 修改 `src/news_sentry/skills/output/markdown_writer.py`**

在 `_render_frontmatter` 方法中，`sentiment_score` 写入之后、`pipeline_stage` 写入之前，插入 NLP 字段：

在文件顶部 imports 中修改：
```python
from news_sentry.models.newsevent import NewsEvent, PipelineStage
```
改为：
```python
from news_sentry.models.newsevent import NLPAnalysis, NLPEntity, NewsEvent, PipelineStage
```

在 `_render_frontmatter` 方法中，在第 106 行 `fm["sentiment_score"] = event.sentiment_score` 之后、第 108 行 `fm["pipeline_stage"]` 之前，插入：

```python
        # Phase 31: NLP 分析字段
        if event.judge_result is not None and event.judge_result.nlp_analysis is not None:
            nlp: NLPAnalysis = event.judge_result.nlp_analysis
            if nlp.sentiment is not None:
                fm["sentiment"] = nlp.sentiment.value
            if nlp.entities:
                fm["nlp_entities"] = [
                    {"name": e.name, "entity_type": e.entity_type, "relevance": e.relevance}
                    for e in nlp.entities
                ]
            if nlp.topic_tags:
                fm["topic_tags"] = nlp.topic_tags
            if nlp.event_relations:
                fm["event_relations"] = nlp.event_relations
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_markdown_writer.py -v`
Expected: 所有测试通过（原有 10 + 新增 3 = 13）

- [ ] **Step 5: 运行全量测试确认零破坏**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 1504+ passed

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/skills/output/markdown_writer.py tests/unit/test_markdown_writer.py
git commit -m "Phase 31: Frontmatter 写入 NLP 字段 — sentiment/nlp_entities/topic_tags/event_relations (P31.01)"
```

---

### Task 2 (P31.02): SQLite event_index 加列 + Migration + Upsert

**Files:**
- Modify: `src/news_sentry/core/async_store.py`

- [ ] **Step 1: 修改 DDL 和 Migration**

在 `_DDL_EVENT_INDEX` SQL 中（第 58-72 行），`created_at TEXT NOT NULL` 之前添加 3 列：

```sql
_DDL_EVENT_INDEX = """
CREATE TABLE IF NOT EXISTS event_index (
    event_id          TEXT PRIMARY KEY,
    target_id         TEXT NOT NULL,
    stage             TEXT NOT NULL,
    source_id         TEXT,
    news_value_score  INTEGER,
    china_relevance   INTEGER,
    classification_l0 TEXT,
    title_original    TEXT,
    published_at      TEXT,
    file_path         TEXT,
    sentiment         TEXT,
    entity_names      TEXT,
    topic_tags        TEXT,
    created_at        TEXT NOT NULL
)
"""
```

在 `_DDL_INDEXES` 元组（第 74-78 行）中添加 2 个新索引：

```python
_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_known_ids_seen ON known_ids(seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_target_stage ON event_index(target_id, stage)",
    "CREATE INDEX IF NOT EXISTS idx_event_published ON event_index(published_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_event_sentiment ON event_index(sentiment)",
    "CREATE INDEX IF NOT EXISTS idx_event_topic_tags ON event_index(topic_tags)",
)
```

在 `initialize()` 方法中，`await self._db.commit()` 之前（第 105 行），添加 migration 逻辑（兼容已有数据库）：

```python
        # Phase 31: 为已有数据库添加 NLP 列（ALTER TABLE ADD COLUMN）
        try:
            await self._db.execute("ALTER TABLE event_index ADD COLUMN sentiment TEXT")
        except Exception:
            pass  # 列已存在
        try:
            await self._db.execute("ALTER TABLE event_index ADD COLUMN entity_names TEXT")
        except Exception:
            pass
        try:
            await self._db.execute("ALTER TABLE event_index ADD COLUMN topic_tags TEXT")
        except Exception:
            pass
        for idx_sql in _DDL_INDEXES:
            await self._db.execute(idx_sql)
```

注意：原 `_DDL_INDEXES` 循环（第 103-104 行）保留，新增索引也在其中自动执行。

- [ ] **Step 2: 修改 `index_event` 写入逻辑**

在 `index_event` 方法中（约第 310 行），找到 `INSERT OR REPLACE INTO event_index` 语句，修改 SQL 和参数：

SQL 改为：
```python
        await self._db.execute(
            """INSERT OR REPLACE INTO event_index
               (event_id, target_id, stage, source_id, news_value_score,
                china_relevance, classification_l0, title_original,
                published_at, file_path, sentiment, entity_names, topic_tags,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                   (SELECT created_at FROM event_index WHERE event_id = ?), ?))""",
            (
                getattr(event, "id", ""),
                target_id,
                stage,
                getattr(event, "source_id", None),
                getattr(event, "news_value_score", None),
                getattr(event, "china_relevance", None),
                classification_l0,
                getattr(event, "title_original", None),
                getattr(event, "published_at", None),
                file_path,
                *self._extract_nlp_fields(event),
                getattr(event, "id", ""),
                now,
            ),
        )
```

在 `AsyncStore` 类中新增私有方法（在 `index_event` 之前）：

```python
    @staticmethod
    def _extract_nlp_fields(event: Any) -> tuple[str | None, str | None, str | None]:
        """从 event.judge_result.nlp_analysis 提取 SQLite 窄列值。"""
        judge_result = getattr(event, "judge_result", None)
        if judge_result is None:
            return None, None, None
        nlp = getattr(judge_result, "nlp_analysis", None)
        if nlp is None:
            return None, None, None

        sentiment = nlp.sentiment.value if nlp.sentiment is not None else None
        entity_names = ",".join(e.name for e in nlp.entities) if nlp.entities else None
        topic_tags = ",".join(nlp.topic_tags) if nlp.topic_tags else None
        return sentiment, entity_names, topic_tags
```

- [ ] **Step 3: 运行 ruff + mypy 检查**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/core/async_store.py && .venv/bin/python3 -m mypy src/news_sentry/core/async_store.py`
Expected: 0 errors

- [ ] **Step 4: 运行全量测试确认零破坏**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 1504+ passed

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_store.py
git commit -m "Phase 31: SQLite event_index 增加 sentiment/entity_names/topic_tags 列 (P31.02)"
```

---

### Task 3 (P31.03): SQLite 查询扩展 — NLP 过滤 + Stats

**Files:**
- Modify: `src/news_sentry/core/async_store.py` — `query_events_paginated` + `get_stats_aggregated`
- Modify: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写测试 — 在 `tests/unit/test_async_store.py` 的 `TestEventIndexQueries` 类末尾添加**

先在 `TestEventIndex._make_event` 中扩展 mock 对象以支持 NLP：

在 `_make_event` 方法中，`event.metadata = ...` 之前，添加参数 `nlp_analysis=None` 并设置：

```python
    @staticmethod
    def _make_event(
        event_id: str = "evt-idx-001",
        source_id: str = "src-rss",
        news_value_score: int = 75,
        china_relevance: int = 60,
        title_original: str = "Test title",
        published_at: str = "2026-01-15T10:00:00Z",
        classification: dict[str, Any] | None = None,
        nlp_analysis: Any = None,
    ) -> MagicMock:
        event = MagicMock()
        event.id = event_id
        event.source_id = source_id
        event.news_value_score = news_value_score
        event.china_relevance = china_relevance
        event.title_original = title_original
        event.published_at = published_at
        if classification is not None:
            event.metadata = {"classification": classification}
        else:
            event.metadata = {"classification": {"l0": "politics"}}
        # NLP 分析结果
        if nlp_analysis is not None:
            event.judge_result = MagicMock()
            event.judge_result.nlp_analysis = nlp_analysis
        else:
            event.judge_result = None
        return event
```

然后在 `TestEventIndexQueries` 类末尾添加测试：

```python
    @pytest.mark.asyncio
    async def test_index_event_writes_nlp_fields(self, store: AsyncStore):
        """index_event 正确提取 NLP 字段写入 sentiment/entity_names/topic_tags。"""
        from news_sentry.models.newsevent import NLPAnalysis, NLPEntity, Sentiment

        nlp = NLPAnalysis(
            sentiment=Sentiment.NEGATIVE,
            entities=[
                NLPEntity(name="Meloni", entity_type="person", relevance=80),
                NLPEntity(name="Roma", entity_type="location", relevance=50),
            ],
            topic_tags=["politics"],
        )
        event = TestEventIndex._make_event(
            event_id="evt-nlp-001",
            nlp_analysis=nlp,
        )
        await store.index_event(event, "italy", "drafts")
        rows = await store.query_events("italy", "drafts")
        assert len(rows) == 1
        assert rows[0]["sentiment"] == "negative"
        assert rows[0]["entity_names"] == "Meloni,Roma"
        assert rows[0]["topic_tags"] == "politics"

    @pytest.mark.asyncio
    async def test_index_event_no_nlp_writes_null(self, store: AsyncStore):
        """无 NLP 分析 → sentiment/entity_names/topic_tags 为 None。"""
        event = TestEventIndex._make_event(event_id="evt-no-nlp")
        await store.index_event(event, "italy", "drafts")
        rows = await store.query_events("italy", "drafts")
        assert len(rows) == 1
        assert rows[0]["sentiment"] is None
        assert rows[0]["entity_names"] is None
        assert rows[0]["topic_tags"] is None

    @pytest.mark.asyncio
    async def test_query_events_filter_by_sentiment(self, store: AsyncStore):
        """按 sentiment 过滤查询。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        event_pos = TestEventIndex._make_event(
            event_id="evt-pos",
            nlp_analysis=NLPAnalysis(sentiment=Sentiment.POSITIVE),
        )
        event_neg = TestEventIndex._make_event(
            event_id="evt-neg",
            nlp_analysis=NLPAnalysis(sentiment=Sentiment.NEGATIVE),
        )
        await store.index_event(event_pos, "italy", "drafts")
        await store.index_event(event_neg, "italy", "drafts")

        result = await store.query_events_paginated(
            "italy", "drafts", sentiment="negative"
        )
        assert result["total"] == 1
        assert result["rows"][0]["event_id"] == "evt-neg"

    @pytest.mark.asyncio
    async def test_query_events_filter_by_entity(self, store: AsyncStore):
        """按 entity_name 过滤查询（逗号分隔 LIKE）。"""
        from news_sentry.models.newsevent import NLPAnalysis, NLPEntity, Sentiment

        event1 = TestEventIndex._make_event(
            event_id="evt-e1",
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.NEUTRAL,
                entities=[NLPEntity(name="Meloni", entity_type="person", relevance=80)],
            ),
        )
        event2 = TestEventIndex._make_event(
            event_id="evt-e2",
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.NEUTRAL,
                entities=[NLPEntity(name="Draghi", entity_type="person", relevance=70)],
            ),
        )
        await store.index_event(event1, "italy", "drafts")
        await store.index_event(event2, "italy", "drafts")

        result = await store.query_events_paginated(
            "italy", "drafts", entity_name="Meloni"
        )
        assert result["total"] == 1
        assert result["rows"][0]["event_id"] == "evt-e1"

    @pytest.mark.asyncio
    async def test_query_events_filter_by_topic_tag(self, store: AsyncStore):
        """按 topic_tag 过滤查询。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        event1 = TestEventIndex._make_event(
            event_id="evt-t1",
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.NEUTRAL,
                topic_tags=["politics", "economy"],
            ),
        )
        event2 = TestEventIndex._make_event(
            event_id="evt-t2",
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.NEUTRAL,
                topic_tags=["sports"],
            ),
        )
        await store.index_event(event1, "italy", "drafts")
        await store.index_event(event2, "italy", "drafts")

        result = await store.query_events_paginated(
            "italy", "drafts", topic_tag="economy"
        )
        assert result["total"] == 1
        assert result["rows"][0]["event_id"] == "evt-t1"

    @pytest.mark.asyncio
    async def test_get_stats_sentiment_breakdown(self, store: AsyncStore):
        """get_stats_aggregated 返回 sentiment_breakdown。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        for i, s in enumerate([Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL, None]):
            nlp = NLPAnalysis(sentiment=s) if s else None
            event = TestEventIndex._make_event(
                event_id=f"evt-sb-{i}",
                nlp_analysis=nlp,
            )
            await store.index_event(event, "italy", "drafts")

        stats = await store.get_stats_aggregated("italy")
        assert "sentiment_breakdown" in stats
        sb = stats["sentiment_breakdown"]
        assert sb.get("positive") == 1
        assert sb.get("negative") == 1
        assert sb.get("neutral") == 1
        assert sb.get("none") == 1

    @pytest.mark.asyncio
    async def test_nlp_migration_on_existing_db(self, tmp_path: Path):
        """已有数据库执行 initialize() 后自动添加 NLP 列。"""
        from news_sentry.models.newsevent import NLPAnalysis, Sentiment

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        # 写入一个无 NLP 的事件
        event = TestEventIndex._make_event(event_id="evt-old")
        await store.index_event(event, "italy", "drafts")
        await store.close()

        # 重新打开（触发 migration）
        store2 = AsyncStore(db_path)
        await store2.initialize()

        # 写入一个有 NLP 的事件
        event2 = TestEventIndex._make_event(
            event_id="evt-new",
            nlp_analysis=NLPAnalysis(sentiment=Sentiment.POSITIVE),
        )
        await store2.index_event(event2, "italy", "drafts")

        result = await store2.query_events_paginated(
            "italy", "drafts", sentiment="positive"
        )
        assert result["total"] == 1
        await store2.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestEventIndexQueries::test_index_event_writes_nlp_fields -v`
Expected: FAIL — `query_events` 返回的 dict 没有 sentiment 键

- [ ] **Step 3: 修改 `query_events_paginated` 增加过滤参数**

找到 `query_events_paginated` 方法签名（约第 426 行），在 `min_score` 参数后添加 3 个参数：

```python
    async def query_events_paginated(
        self,
        target_id: str,
        stage: str,
        limit: int = 20,
        offset: int = 0,
        source_id: str | None = None,
        classification_l0: str | None = None,
        min_score: int | None = None,
        sentiment: str | None = None,
        entity_name: str | None = None,
        topic_tag: str | None = None,
    ) -> dict[str, Any]:
```

在 `min_score` 条件之后，添加 NLP 过滤条件：

```python
        if sentiment is not None:
            conditions.append("sentiment = ?")
            params.append(sentiment)
        if entity_name is not None:
            conditions.append("',' || entity_names || ',' LIKE '%,' || ? || ',%'")
            params.append(entity_name)
        if topic_tag is not None:
            conditions.append("',' || topic_tags || ',' LIKE '%,' || ? || ',%'")
            params.append(topic_tag)
```

同时在 `data_sql` 的 SELECT 列表中添加 `sentiment, entity_names, topic_tags`：

```python
        data_sql = (
            "SELECT event_id, source_id, news_value_score, china_relevance, "
            "classification_l0, published_at, file_path, title_original, "
            "sentiment, entity_names, topic_tags "
            f"FROM event_index WHERE {where} "
            "ORDER BY published_at DESC LIMIT ? OFFSET ?"
        )
```

在结果映射中添加对应字段（`result_rows` 循环中，`r[7]` 之后）：

```python
        for r in rows:
            result_rows.append(
                {
                    "event_id": r[0],
                    "source_id": r[1],
                    "news_value_score": r[2],
                    "china_relevance": r[3],
                    "classification_l0": r[4],
                    "published_at": r[5],
                    "file_path": r[6],
                    "title_original": r[7],
                    "sentiment": r[8],
                    "entity_names": r[9],
                    "topic_tags": r[10],
                }
            )
```

同时修改 `query_events` 方法（约第 349 行），在 SELECT 中添加 3 列，在 cols tuple 中添加名称：

找到 `query_events` 的 SQL：
```python
            """SELECT event_id, target_id, stage, source_id, news_value_score,
                      china_relevance, classification_l0, title_original,
                      published_at, file_path, created_at
               FROM event_index
```
改为：
```python
            """SELECT event_id, target_id, stage, source_id, news_value_score,
                      china_relevance, classification_l0, title_original,
                      published_at, file_path, created_at,
                      sentiment, entity_names, topic_tags
               FROM event_index
```

找到 `query_events` 的 cols tuple：
```python
        cols = (
```
在 tuple 末尾 `"created_at"` 之后添加 `"sentiment", "entity_names", "topic_tags"`。

- [ ] **Step 4: 修改 `get_stats_aggregated` 添加 sentiment_breakdown**

在 `get_stats_aggregated` 方法中，`by_source` 查询之后，return 之前，添加：

```python
        # Phase 31: sentiment 分布
        sentiment_breakdown: dict[str, int] = {}
        async with self._db.execute(
            "SELECT sentiment, COUNT(*) FROM event_index "
            "WHERE target_id = ? GROUP BY sentiment",
            [target_id],
        ) as cursor:
            async for row in cursor:
                key = row[0] if row[0] is not None else "none"
                sentiment_breakdown[key] = row[1]
```

修改 return dict，在 `"by_source": by_source` 之后添加：

```python
            "sentiment_breakdown": sentiment_breakdown,
```

同时修改方法开头的空结果 return（两处 `return { ... }` 都需要添加）：

```python
                "sentiment_breakdown": {},
```

- [ ] **Step 5: 运行测试**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py -v 2>&1 | tail -20`
Expected: 所有测试通过

- [ ] **Step 6: 运行 ruff + mypy**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/core/async_store.py && .venv/bin/python3 -m mypy src/news_sentry/core/async_store.py`
Expected: 0 errors

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 31: SQLite 查询扩展 — NLP 过滤 + sentiment_breakdown (P31.03)"
```

---

### Task 4 (P31.04): API Server NLP 过滤参数 + Stats

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `tests/unit/test_api_server.py`

- [ ] **Step 1: 修改 `list_events` 端点增加 3 个查询参数**

找到 `async def list_events`（约第 676 行），在 `search` 参数之后添加：

```python
        sentiment: str | None = Query(None, description="按 sentiment 筛选 (positive/negative/neutral)"),
        entity: str | None = Query(None, description="按实体名筛选"),
        topic_tag: str | None = Query(None, description="按主题标签筛选"),
```

在 `await _store.query_events_paginated(` 调用中，在 `min_score=min_score,` 之后添加：

```python
                sentiment=sentiment,
                entity_name=entity,
                topic_tag=topic_tag,
```

注意 `query_events_paginated` 的参数名是 `entity_name`，API 参数名是 `entity`。

- [ ] **Step 2: 写 API 测试**

在 `tests/unit/test_api_server.py` 的 `TestAPIServerSQLite` 类末尾添加测试。

首先，在 `store_with_data` fixture 中的 `events_data` 列表中，为现有事件添加 `sentiment`/`entity_names`/`topic_tags` 字段，并修改 INSERT SQL 包含这些列。

找到 `store_with_data` fixture 中的 `events_data` 列表，为每个事件添加：

```python
            {
                "event_id": "ne-italy-ansa-20260512-aaa11111",
                "source_id": "ansa",
                "news_value_score": 80,
                "china_relevance": 20,
                "classification_l0": "international",
                "title_original": "Pace in Medio Oriente",
                "sentiment": "positive",
                "entity_names": "Roma,Medio Oriente",
                "topic_tags": "international,peace",
            },
            {
                "event_id": "ne-italy-repubblica-20260512-bbb22222",
                "source_id": "repubblica",
                "news_value_score": 60,
                "china_relevance": 40,
                "classification_l0": "politics",
                "title_original": "Elezioni politiche",
                "sentiment": "negative",
                "entity_names": "Meloni",
                "topic_tags": "politics,elections",
            },
            {
                "event_id": "ne-italy-ansa-20260512-ccc33333",
                "source_id": "ansa",
                "news_value_score": 90,
                "china_relevance": 10,
                "classification_l0": "international",
                "title_original": "Accordo commerciale",
                "sentiment": "neutral",
                "entity_names": None,
                "topic_tags": "economy",
            },
```

修改 fixture 中的 INSERT SQL：
```python
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, classification_l0, title_original, "
                "published_at, file_path, created_at, "
                "sentiment, entity_names, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev["event_id"],
                    "italy",
```
在参数末尾添加 `ev.get("sentiment"), ev.get("entity_names"), ev.get("topic_tags"),`。

然后在类末尾添加测试：

```python
    def test_events_filter_by_sentiment_with_sqlite(
        self, tmp_path: Path
    ) -> None:
        resp = self._make_request(
            tmp_path,
            "/api/v1/events",
            params={
                "target_id": "italy",
                "sentiment": "negative",
                "X-API-Key": "test-key",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Elezioni" in data["events"][0]["title_original"]

    def test_events_filter_by_entity_with_sqlite(
        self, tmp_path: Path
    ) -> None:
        resp = self._make_request(
            tmp_path,
            "/api/v1/events",
            params={
                "target_id": "italy",
                "entity": "Meloni",
                "X-API-Key": "test-key",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_events_filter_by_topic_tag_with_sqlite(
        self, tmp_path: Path
    ) -> None:
        resp = self._make_request(
            tmp_path,
            "/api/v1/events",
            params={
                "target_id": "italy",
                "topic_tag": "peace",
                "X-API-Key": "test-key",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "Pace" in data["events"][0]["title_original"]

    def test_stats_sentiment_breakdown_with_sqlite(
        self, tmp_path: Path
    ) -> None:
        resp = self._make_request(
            tmp_path,
            "/api/v1/stats",
            params={"target_id": "italy", "X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sentiment_breakdown" in data
        sb = data["sentiment_breakdown"]
        assert sb.get("positive") == 1
        assert sb.get("negative") == 1
        assert sb.get("neutral") == 1
```

注意：`_make_request` 是该测试类中已有的辅助方法。需要检查它是否存在，如果不存在，使用 `TestAPIServerSQLite` 中已有的 `client.get()` 模式。

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestAPIServerSQLite -v 2>&1 | tail -20`
Expected: 所有测试通过

- [ ] **Step 4: 运行 ruff + mypy + 全量测试**

Run: `.venv/bin/python3 -m ruff check src/news_sentry/core/api_server.py && .venv/bin/python3 -m mypy src/news_sentry/core/api_server.py`
Expected: 0 errors

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 1519+ passed

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "Phase 31: API Server NLP 过滤参数 + sentiment_breakdown 统计 (P31.04)"
```

---

### Task 5 (P31.05): 验证与清理

**Files:** 无新文件

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 全部通过，约 1519 tests

- [ ] **Step 2: Lint + Type check**

Run: `.venv/bin/python3 -m ruff check src/ && .venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 3: 覆盖率检查**

Run: `.venv/bin/python3 -m pytest tests/ --cov=news_sentry --cov-report=term-missing -q 2>&1 | grep "TOTAL"`
Expected: >= 92%

- [ ] **Step 4: 更新 docs/development-plan.md**

在 §26 v1.3.0 section 中更新 Phase 31 状态为 ✅，添加任务矩阵。

- [ ] **Step 5: Commit**

```bash
git add docs/
git commit -m "Phase 31: 验证通过 — NLP 数据 API 暴露 + SQLite 索引增强 (P31.00)"
```
