# Phase 36: 事件时间线叙事 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对追踪链自动生成 AI 叙述，用自然语言概括事件发展脉络，在 Web UI 中展示。

**Architecture:** AsyncStore 新增 chain_narratives 表存储叙述，pipeline 自动生成 + 用户手动重新生成，LLM 通过 ProviderRouter task_type="narrative" 调用。

**Tech Stack:** SQLite / aiosqlite / ProviderRouter route_async / FastAPI / Vanilla JS ES Modules

---

### Task 1: AsyncStore chain_narratives 表 + 方法 + get_event_chain 扩展

**Files:**
- Modify: `src/news_sentry/core/async_store.py`
- Test: `tests/unit/test_async_store.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_async_store.py` 末尾追加 `TestChainNarratives` 类：

```python
class TestChainNarratives:
    """Phase 36: chain_narratives 表 + 叙述方法。"""

    @pytest.fixture
    async def store_with_narratives(self, tmp_path):
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()
        yield store
        await store.close()

    async def test_chain_narratives_table_created(self, store_with_narratives):
        store = store_with_narratives
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chain_narratives'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None

    async def test_upsert_and_get_narrative(self, store_with_narratives):
        store = store_with_narratives
        await store.upsert_narrative(
            chain_root_id="evt-1",
            target_id="italy",
            narrative="意大利总理梅洛尼访问欧盟总部...",
            narrative_hash="abc123",
            event_count=3,
            model_used="gpt-4o-mini",
        )
        result = await store.get_narrative("evt-1")
        assert result is not None
        assert result["narrative"] == "意大利总理梅洛尼访问欧盟总部..."
        assert result["model_used"] == "gpt-4o-mini"
        assert result["event_count"] == 3

    async def test_upsert_narrative_updates_existing(self, store_with_narratives):
        store = store_with_narratives
        await store.upsert_narrative("evt-1", "italy", "叙述v1", "hash1", 3, "model-a")
        await store.upsert_narrative("evt-1", "italy", "叙述v2", "hash2", 4, "model-b")
        result = await store.get_narrative("evt-1")
        assert result["narrative"] == "叙述v2"
        assert result["event_count"] == 4

    async def test_get_narrative_not_found(self, store_with_narratives):
        store = store_with_narratives
        result = await store.get_narrative("nonexistent")
        assert result is None

    async def test_get_event_chain_returns_extended_fields(self, store_with_narratives):
        """get_event_chain 返回 sentiment, entity_names, topic_tags, news_value_score。"""
        store = store_with_narratives
        now = "2026-05-16T12:00:00+00:00"
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "title_original, sentiment, entity_names, topic_tags, news_value_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-1", "italy", "drafts", now, now, "Event One", "positive", "Meloni,EU", "politics", 75),
        )
        await store._db.execute(
            "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, "
            "title_original, sentiment, entity_names, topic_tags, news_value_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("evt-2", "italy", "drafts", now, now, "Event Two", "negative", "Meloni", "eu", 60),
        )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        chain = await store.get_event_chain("evt-1", depth=5)
        assert len(chain) == 2
        first = chain[0]
        assert "sentiment" in first
        assert "entity_names" in first
        assert "topic_tags" in first
        assert "news_value_score" in first
        assert first["sentiment"] == "positive"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestChainNarratives -v`
Expected: FAIL

- [ ] **Step 3: 实现**

**3a.** 在 `async_store.py` 的 `_DDL_EVENT_LINKS` 之后新增 DDL：

```python
_DDL_CHAIN_NARRATIVES = """
CREATE TABLE IF NOT EXISTS chain_narratives (
    chain_root_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    narrative TEXT NOT NULL,
    narrative_hash TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    model_used TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""
```

**3b.** 在 `initialize()` 中，`await self._db.execute(_DDL_EVENT_LINKS)` 之后追加：

```python
        await self._db.execute(_DDL_CHAIN_NARRATIVES)
```

**3c.** 修改 `get_event_chain()` — 将 SELECT 语句扩展为：

```python
        async with self._db.execute(
            f"SELECT event_id, title_original, published_at, sentiment, "  # noqa: S608
            f"entity_names, topic_tags, news_value_score FROM event_index "
            f"WHERE event_id IN ({placeholders}) ORDER BY published_at ASC",
            list(visited),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            chain_events.append({
                "event_id": row[0],
                "title_original": row[1],
                "published_at": row[2],
                "sentiment": row[3],
                "entity_names": row[4],
                "topic_tags": row[5],
                "news_value_score": row[6],
            })
```

**3d.** 在 Event Links 方法区域之后新增 3 个方法：

```python
    # ------------------------------------------------------------------
    # Chain Narratives (Phase 36)
    # ------------------------------------------------------------------

    async def get_narrative(self, chain_root_id: str) -> dict[str, Any] | None:
        """获取链的叙述。"""
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT chain_root_id, target_id, narrative, narrative_hash, "
            "event_count, model_used, created_at, updated_at "
            "FROM chain_narratives WHERE chain_root_id = ?",
            [chain_root_id],
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        cols = (
            "chain_root_id", "target_id", "narrative", "narrative_hash",
            "event_count", "model_used", "created_at", "updated_at",
        )
        return dict(zip(cols, row, strict=True))

    async def upsert_narrative(
        self,
        chain_root_id: str,
        target_id: str,
        narrative: str,
        narrative_hash: str,
        event_count: int,
        model_used: str,
    ) -> None:
        """写入或更新链叙述。"""
        if self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT INTO chain_narratives
               (chain_root_id, target_id, narrative, narrative_hash, event_count, model_used, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chain_root_id) DO UPDATE SET
                   narrative = excluded.narrative,
                   narrative_hash = excluded.narrative_hash,
                   event_count = excluded.event_count,
                   model_used = excluded.model_used,
                   updated_at = excluded.updated_at""",
            (chain_root_id, target_id, narrative, narrative_hash, event_count, model_used, now, now),
        )
        await self._db.commit()

    @staticmethod
    def compute_chain_hash(events: list[dict[str, Any]]) -> str:
        """计算事件列表的 SHA-256 摘要。"""
        from hashlib import sha256
        parts = "|".join(
            f"{e.get('event_id', '')}:{e.get('published_at', '')}:{e.get('title_original', '')}"
            for e in sorted(events, key=lambda x: x.get("event_id", ""))
        )
        return sha256(parts.encode()).hexdigest()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_store.py::TestChainNarratives tests/unit/test_async_store.py::TestEventLinks::test_get_event_chain -v`
Expected: PASS

- [ ] **Step 5: 全量回归测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Expected: 1549+ passed

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 36 P36.01: chain_narratives 表 + 叙述方法 + chain 字段扩展"
```

---

### Task 2: Pipeline 集成 — _generate_narratives 协程

**Files:**
- Modify: `src/news_sentry/core/async_run.py`
- Test: `tests/unit/test_async_run.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_async_run.py` 末尾追加：

```python
class TestGenerateNarratives:
    """Phase 36: _generate_narratives 协程测试。"""

    async def test_generate_narratives_skips_no_provider(self, tmp_path):
        """无 ProviderRouter 时不生成叙述（不抛异常）。"""
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}"),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        from news_sentry.core.async_run import _generate_narratives
        # 无 router，应跳过不抛异常
        await _generate_narratives(store, "italy", router=None)
        await store.close()

    async def test_generate_narratives_with_mock_router(self, tmp_path):
        """模拟 ProviderRouter 成功生成叙述。"""
        from news_sentry.core.async_store import AsyncStore
        from unittest.mock import AsyncMock, MagicMock

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid in ("evt-1", "evt-2"):
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original, "
                "sentiment, entity_names, topic_tags, news_value_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, f"Event {eid}", "positive", "Meloni", "politics", 75),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")

        router = MagicMock()
        router.route_async = AsyncMock(return_value={"content": "梅洛尼在意大利政坛持续活跃。"})

        from news_sentry.core.async_run import _generate_narratives
        await _generate_narratives(store, "italy", router=router)

        narrative = await store.get_narrative("evt-1")
        assert narrative is not None
        assert "梅洛尼" in narrative["narrative"]

        await store.close()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestGenerateNarratives -v`
Expected: FAIL

- [ ] **Step 3: 实现 _generate_narratives**

在 `async_run.py` 中，`_link_events` 函数之前，新增：

```python
async def _generate_narratives(
    store: AsyncStore,
    target_id: str,
    router: Any | None = None,
) -> None:
    """Phase 36: 对活跃追踪链生成 AI 叙述。

    查询所有活跃链，对 narrative_hash 变化的链调用 LLM 生成叙述。
    短链(<=5)一段，中链(6-10)两段，长链(>10)截断最近10事件。
    失败不阻塞 pipeline。
    """
    if store._db is None or router is None:
        return
    try:
        chains = await store.get_active_chains(target_id)
        for chain_info in chains:
            root_id = chain_info["root_event_id"]
            chain = await store.get_event_chain(root_id, depth=15)
            if len(chain) < 2:
                continue

            # 计算 hash 检测是否需要重新生成
            new_hash = AsyncStore.compute_chain_hash(chain)
            existing = await store.get_narrative(root_id)
            if existing and existing["narrative_hash"] == new_hash:
                continue

            # 链长度分级
            if len(chain) > 10:
                # 长链：前序摘要 + 最近10事件
                preamble_titles = ", ".join(
                    e.get("title_original", "")[:30] for e in chain[:-10]
                )
                events_for_prompt = chain[-10:]
                prefix = f"前序事件摘要：{preamble_titles}。以下是最新的进展：\n\n"
            elif len(chain) > 5:
                events_for_prompt = chain
                prefix = ""
            else:
                events_for_prompt = chain
                prefix = ""

            # 构建 prompt
            event_lines = []
            for e in events_for_prompt:
                line = (
                    f"- {e.get('published_at', '?')[:16]} | "
                    f"{e.get('title_original', '?')} | "
                    f"情感: {e.get('sentiment', '?')} | "
                    f"实体: {e.get('entity_names', '?')} | "
                    f"主题: {e.get('topic_tags', '?')}"
                )
                event_lines.append(line)

            events_text = "\n".join(event_lines)
            count = len(events_for_prompt)

            if len(chain) > 5:
                instruction = (
                    f"以下是同一事件发展脉络中的 {count} 条报道，按时间排列：\n\n"
                    f"{events_text}\n\n"
                    f"请分两段概括：第一段概述事件背景和起因（100字以内），"
                    f"第二段描述最新进展和走向（100字以内）。"
                )
            else:
                instruction = (
                    f"以下是同一事件发展脉络中的 {count} 条报道，按时间排列：\n\n"
                    f"{events_text}\n\n"
                    f"请用一段话（150字以内）概括这个事件的发展脉络，突出关键转折和核心人物。"
                )

            prompt = prefix + instruction

            # 调用 LLM
            result = await router.route_async(
                task_type="narrative",
                prompt=prompt,
                provider_factory=lambda name: None,
            )
            narrative_text = result.get("content", "").strip()
            if not narrative_text:
                continue

            model_used = result.get("model", "")
            await store.upsert_narrative(
                chain_root_id=root_id,
                target_id=target_id,
                narrative=narrative_text,
                narrative_hash=new_hash,
                event_count=len(chain),
                model_used=model_used,
            )
            logger.info("链叙述已生成: root=%s, events=%d", root_id, len(chain))
    except Exception as e:
        logger.warning("链叙述生成失败（非阻塞）: %s", e)
```

- [ ] **Step 4: 集成到 pipeline**

在 `_run_judge_async` 中，P35 的 link_events 调用之后、`# 写入研判结果` 之前，追加：

```python
    # P36: 链叙述生成
    if store is not None:
        try:
            narrative_router = _try_create_provider_router()
            await _generate_narratives(store, config.target_id, router=narrative_router)
        except Exception as e:
            logger.warning("链叙述生成失败（非阻塞）: %s", e)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_async_run.py::TestGenerateNarratives -v`
Expected: 2/2 PASS

- [ ] **Step 6: 全量回归测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Expected: 1551+ passed

- [ ] **Step 7: Commit**

```bash
git add src/news_sentry/core/async_run.py tests/unit/test_async_run.py
git commit -m "Phase 36 P36.02: pipeline 集成 _generate_narratives 叙述生成"
```

---

### Task 3: API 端点 — narrative GET/POST

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_api_server.py` 末尾追加：

```python
class TestChainNarrativeAPI:
    """Phase 36: 链叙述 API 端点。"""

    @pytest.fixture
    async def client_with_narrative(self, tmp_path):
        from news_sentry.core.async_store import AsyncStore

        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = "2026-05-16T12:00:00+00:00"
        for eid, title in [("evt-1", "Event One"), ("evt-2", "Event Two")]:
            await store._db.execute(
                "INSERT INTO event_index (event_id, target_id, stage, created_at, published_at, title_original) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, "italy", "drafts", now, now, title),
            )
        await store._db.commit()
        await store.create_link("evt-1", "evt-2", "followup", 0.8, {}, "italy")
        await store.upsert_narrative("evt-1", "italy", "梅洛尼在意大利政坛持续活跃。", "hash1", 2, "gpt-4o-mini")

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        yield client, store
        await client.aclose()
        await store.close()

    async def test_get_narrative(self, client_with_narrative):
        client, _ = client_with_narrative
        resp = await client.get("/api/v1/chains/evt-1/narrative", params={"target_id": "italy"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_root_id"] == "evt-1"
        assert "梅洛尼" in data["narrative"]
        assert data["event_count"] == 2

    async def test_get_narrative_not_found(self, client_with_narrative):
        client, _ = client_with_narrative
        resp = await client.get("/api/v1/chains/nonexistent/narrative", params={"target_id": "italy"})
        assert resp.status_code == 404

    async def test_post_narrative_no_store(self, tmp_path):
        """无 store 时 POST 返回 503。"""
        app = create_app(data_dir=str(tmp_path))
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        resp = await client.post("/api/v1/chains/evt-1/narrative", params={"target_id": "italy"})
        assert resp.status_code == 503
        await client.aclose()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestChainNarrativeAPI -v`
Expected: FAIL

- [ ] **Step 3: 实现**

**3a.** 在 api_server.py 的 Pydantic 模型区域（`ChainListResponse` 之后）新增：

```python
class NarrativeResponse(BaseModel):
    """链叙述响应。"""

    chain_root_id: str
    narrative: str
    event_count: int = 0
    model_used: str = ""
    generated_at: str = ""
```

**3b.** 在 `create_app()` 中，追踪链端点之后、静态文件挂载之前，新增 2 个端点：

```python
    @app.get("/api/v1/chains/{root_id}/narrative", response_model=NarrativeResponse)
    async def get_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> NarrativeResponse:
        """获取链的 AI 叙述。"""
        if _store is None:
            raise HTTPException(status_code=404, detail="No narrative found")
        result = await _store.get_narrative(root_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Narrative not found")
        return NarrativeResponse(
            chain_root_id=result["chain_root_id"],
            narrative=result["narrative"],
            event_count=result["event_count"],
            model_used=result["model_used"],
            generated_at=result["updated_at"],
        )

    @app.post("/api/v1/chains/{root_id}/narrative", response_model=NarrativeResponse)
    async def regenerate_chain_narrative(
        root_id: str,
        target_id: str = Query(..., description="目标标识"),
    ) -> NarrativeResponse:
        """手动重新生成链叙述。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            import asyncio
            from news_sentry.core.async_run import _generate_narratives, _try_create_provider_router

            router = _try_create_provider_router()
            if router is None:
                raise HTTPException(status_code=503, detail="AI provider not configured")
            # 删除旧叙述强制重新生成
            await _store._db.execute(
                "DELETE FROM chain_narratives WHERE chain_root_id = ?", [root_id]
            )
            await _store._db.commit()
            await _generate_narratives(_store, target_id, router=router)
            result = await _store.get_narrative(root_id)
            if result is None:
                raise HTTPException(status_code=500, detail="Narrative generation failed")
            return NarrativeResponse(
                chain_root_id=result["chain_root_id"],
                narrative=result["narrative"],
                event_count=result["event_count"],
                model_used=result["model_used"],
                generated_at=result["updated_at"],
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestChainNarrativeAPI -v`
Expected: 3/3 PASS

- [ ] **Step 5: 全量回归 + Lint**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Run: `ruff check src/news_sentry/core/api_server.py src/news_sentry/core/async_run.py`
Run: `.venv/bin/python3 -m mypy src/news_sentry/ --ignore-missing-imports 2>&1 | tail -5`
Expected: All pass, ruff=0, mypy=0

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "Phase 36 P36.03: 叙述 API 端点 (GET/POST narrative)"
```

---

### Task 4: 前端叙述展示 + 验收

**Files:**
- Modify: `src/news_sentry/static/pages/chains.js`
- Modify: `src/news_sentry/static/style.css`
- Modify: `docs/roadmap/development-plan.md`

- [ ] **Step 1: 修改 chains.js — 链详情页增加叙述卡片**

在 `renderChainDetail` 函数中，`headerHtml` 和 `timelineHtml` 之间（或者在 header 之后、timeline 之前），插入叙述卡片的加载和渲染逻辑。

在 `try` 块内，`dom.pageContainer.innerHTML = ...` 赋值之后，追加：

```javascript
  // Phase 36: AI 叙述卡片
  try {
    const narrData = await api(`/api/v1/chains/${encodeURIComponent(rootEventId)}/narrative?target_id=${state.currentTarget}`);
    if (narrData && narrData.narrative) {
      const narrCard = document.createElement("div");
      narrCard.className = "section-card narrative-card";
      narrCard.innerHTML = `
        <div class="narrative-header">
          <h3>AI 事件叙述</h3>
          <button class="btn-regenerate" id="btnRegenerate">重新生成</button>
        </div>
        <div class="narrative-text">${escapeHtml(narrData.narrative)}</div>
        <div class="narrative-meta">
          <span>模型: ${escapeHtml(narrData.model_used || "unknown")}</span>
          <span>事件数: ${narrData.event_count}</span>
          <span>${narrData.generated_at ? new Date(narrData.generated_at).toLocaleString("zh-CN") : ""}</span>
        </div>`;
      dom.pageContainer.querySelector(".chain-header")?.after(narrCard) || dom.pageContainer.insertBefore(narrCard, dom.pageContainer.firstChild);

      document.getElementById("btnRegenerate")?.addEventListener("click", async function() {
        this.disabled = true;
        this.textContent = "生成中...";
        try {
          const resp = await fetch(
            `/api/v1/chains/${encodeURIComponent(rootEventId)}/narrative?target_id=${state.currentTarget}`,
            { method: "POST" }
          );
          if (resp.ok) {
            const newData = await resp.json();
            narrCard.querySelector(".narrative-text").textContent = newData.narrative;
            this.textContent = "重新生成";
          } else {
            this.textContent = "生成失败";
            setTimeout(() => { this.textContent = "重新生成"; }, 2000);
          }
        } catch {
          this.textContent = "生成失败";
          setTimeout(() => { this.textContent = "重新生成"; }, 2000);
        }
        this.disabled = false;
      });
    }
  } catch { /* 404 = 无叙述，不显示 */ }
```

- [ ] **Step 2: 修改 chains.js — 链列表页增加叙述摘要列**

在 `renderChainList` 函数中，需要先加载每条链的叙述。修改方案：在获取 chains 数据后，并行请求每条链的叙述（如果链数不太多的话）。

在 `const chainRows = data.chains.map(...)` 之前，加载叙述数据：

```javascript
    // 加载叙述摘要
    const narrativeMap = {};
    await Promise.all(data.chains.map(async (c) => {
      try {
        const narr = await api(`/api/v1/chains/${encodeURIComponent(c.root_event_id)}/narrative?target_id=${state.currentTarget}`);
        if (narr && narr.narrative) {
          narrativeMap[c.root_event_id] = narr.narrative;
        }
      } catch { /* ignore */ }
    }));
```

然后修改 `chainRows` 的 table 行，在"最新标题"列之后新增"叙述"列：

表头增加：`<th>叙述</th>`
行内增加：`<td class="narrative-summary">${narrativeMap[c.root_event_id] ? escapeHtml(narrativeMap[c.root_event_id].substring(0, 50)) + "..." : "-"}</td>`

- [ ] **Step 3: 添加 CSS 样式**

在 `style.css` 末尾追加：

```css
/* ── Phase 36: 叙述卡片 ─────────────────────────────── */

.narrative-card { margin-bottom: 20px; }
.narrative-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.narrative-header h3 { margin: 0; }
.btn-regenerate { background: var(--primary, #3b82f6); color: #fff; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.btn-regenerate:hover { opacity: 0.9; }
.btn-regenerate:disabled { opacity: 0.5; cursor: not-allowed; }
.narrative-text { color: var(--text-primary, #e0e0e0); line-height: 1.6; font-size: 14px; margin-bottom: 8px; }
.narrative-meta { display: flex; gap: 16px; font-size: 11px; color: var(--text-secondary, #888); }
.narrative-summary { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 4: 更新 development-plan.md**

添加 Phase 36 完成记录。

- [ ] **Step 5: 全量回归 + Lint**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -20`
Run: `ruff check src/news_sentry/`
Run: `.venv/bin/python3 -m mypy src/news_sentry/ --ignore-missing-imports 2>&1 | tail -5`
Expected: All pass, ruff=0, mypy=0

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/static/pages/chains.js src/news_sentry/static/style.css docs/roadmap/development-plan.md
git commit -m "Phase 36 P36.04: 前端叙述卡片 + 链列表摘要 + 验收"
```
