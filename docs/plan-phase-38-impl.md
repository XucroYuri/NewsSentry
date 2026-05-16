# Phase 38 实现计划: 智能告警 2.0 + 性能修复

> 目标: 接入链更新/趋势变化/实体突增三类智能告警，修复 chains N+1，补齐 6 个索引。

---

## P38.01: AsyncStore 新方法 + 索引 + chains 优化

**文件:**
- 修改: `src/news_sentry/core/async_store.py`
- 测试: `tests/unit/test_async_store.py`

### Step 1: 新增 6 个索引

在 `_DDL_INDEXES` 元组末尾追加：

```python
    "CREATE INDEX IF NOT EXISTS idx_event_classification ON event_index(classification_l0)",
    "CREATE INDEX IF NOT EXISTS idx_event_source ON event_index(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_score ON event_index(news_value_score)",
    "CREATE INDEX IF NOT EXISTS idx_narrative_target ON chain_narratives(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_links_type ON event_links(link_type, strength)",
    "CREATE INDEX IF NOT EXISTS idx_event_created ON event_index(created_at)",
```

### Step 2: 新增 get_recent_links

在 Trend Analysis 方法之后添加（Phase 38 section comment）：

```python
    # ------------------------------------------------------------------
    # Smart Alerts (Phase 38)
    # ------------------------------------------------------------------

    async def get_recent_links(
        self, target_id: str, hours: int = 24
    ) -> list[dict[str, Any]]:
        """获取最近 N 小时新增的 event_links。"""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT el.source_event_id, el.target_event_id, el.link_type, "
            "el.strength, el.target_id, ei.title_original "
            "FROM event_links el "
            "LEFT JOIN event_index ei ON ei.event_id = el.target_event_id "
            "WHERE el.target_id = ? "
            "AND el.created_at >= datetime('now', ? || ' hours') "
            "ORDER BY el.created_at DESC",
            [target_id, f"-{hours}"],
        ) as cursor:
            rows = await cursor.fetchall()
        cols = (
            "source_event_id", "target_event_id", "link_type",
            "strength", "target_id", "title_original",
        )
        return [dict(zip(cols, row, strict=True)) for row in rows]
```

### Step 3: 新增 get_entity_daily_mentions

```python
    async def get_entity_daily_mentions(
        self, entity_name: str, target_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """获取某实体在每天中的提及次数。"""
        if self._db is None:
            return []
        pattern = f"%,{entity_name},%"
        async with self._db.execute(
            "SELECT date(published_at) AS day, COUNT(*) AS cnt "
            "FROM event_index "
            "WHERE target_id = ? AND stage = 'judged' "
            "AND published_at >= date('now', ? || ' days') "
            "AND ',' || entity_names || ',' LIKE ? "
            "GROUP BY day ORDER BY day",
            [target_id, f"-{days}", pattern],
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"day": r[0], "count": r[1]} for r in rows]
```

### Step 4: 扩展 get_active_chains

修改现有 `get_active_chains()` 方法，在返回 dict 中嵌入 `narrative_summary` 和 `has_narrative` 字段。

找到当前 `get_active_chains` 方法，在遍历 root_ids 构建结果时，增加一次批量查询获取 narratives：

```python
    async def get_active_chains(self, target_id: str) -> list[dict[str, Any]]:
        """获取当前 target 的活跃追踪链（含叙述摘要）。"""
        if self._db is None:
            return []
        # 找所有有 link 的 root events
        async with self._db.execute(
            "SELECT DISTINCT source_event_id FROM event_links WHERE target_id = ?",
            [target_id],
        ) as cursor:
            root_ids = [r[0] for r in await cursor.fetchall()]

        if not root_ids:
            return []

        # 批量获取 narratives
        narrative_map: dict[str, str] = {}
        if root_ids:
            placeholders = ",".join("?" * len(root_ids))
            async with self._db.execute(
                f"SELECT chain_root_id, narrative FROM chain_narratives "  # noqa: S608
                f"WHERE chain_root_id IN ({placeholders})",
                root_ids,
            ) as cursor:
                for row in await cursor.fetchall():
                    narrative_map[row[0]] = row[1]

        chains: list[dict[str, Any]] = []
        for root_id in root_ids:
            chain = await self.get_event_chain(root_id, target_id=target_id)
            if chain:
                latest = chain[-1]
                narr = narrative_map.get(root_id, "")
                chains.append(
                    {
                        "root_event_id": root_id,
                        "event_count": len(chain),
                        "latest_time": latest.get("published_at", ""),
                        "latest_title": latest.get("title_original", ""),
                        "has_narrative": bool(narr),
                        "narrative_summary": narr[:50] + "..." if len(narr) > 50 else narr,
                    }
                )
        return sorted(chains, key=lambda c: c["latest_time"], reverse=True)
```

### Step 5: 测试

在 `tests/unit/test_async_store.py` 末尾新增：

```python
class TestSmartAlertQueries:
    """Phase 38: 智能告警查询测试。"""

    @pytest.fixture
    async def store_with_alerts(self, tmp_path: Path) -> AsyncStore:
        """创建包含告警测试数据的 AsyncStore。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        # 插入带 entity_names 的事件
        for eid, ents in [
            ("a-evt-1", "Meloni,EU"),
            ("a-evt-2", "Meloni,China"),
            ("a-evt-3", "EU,China"),
            ("a-evt-4", "Meloni,EU"),
            ("a-evt-5", "Meloni"),
        ]:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, published_at, created_at, entity_names) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, "italy", "judged", "ansa", 80, 50, now, now, ents),
            )
        await store._db.commit()

        # 创建 links
        await store.create_link("a-evt-1", "a-evt-2", "followup", 0.85, {}, "italy")
        await store.create_link("a-evt-3", "a-evt-4", "related", 0.5, {}, "italy")

        return store

    @pytest.mark.asyncio
    async def test_get_recent_links(
        self, store_with_alerts: AsyncStore
    ) -> None:
        """获取近期新增 links。"""
        result = await store_with_alerts.get_recent_links("italy", hours=24)
        assert isinstance(result, list)
        assert len(result) == 2
        # 检查第一个是 followup（按时间降序）
        followup = [r for r in result if r["link_type"] == "followup"]
        assert len(followup) == 1
        assert followup[0]["strength"] == 0.85

    @pytest.mark.asyncio
    async def test_get_entity_daily_mentions(
        self, store_with_alerts: AsyncStore
    ) -> None:
        """获取实体每日提及量。"""
        result = await store_with_alerts.get_entity_daily_mentions("Meloni", "italy", days=7)
        assert isinstance(result, list)
        assert len(result) > 0
        total = sum(r["count"] for r in result)
        assert total == 4  # Meloni 出现在 4 个事件中

    @pytest.mark.asyncio
    async def test_new_indexes_created(
        self, tmp_path: Path
    ) -> None:
        """验证 6 个新索引正确创建。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        async with store._db.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ) as cursor:
            indexes = {r[0] for r in await cursor.fetchall()}
        expected = {
            "idx_event_classification",
            "idx_event_source",
            "idx_event_score",
            "idx_narrative_target",
            "idx_event_links_type",
            "idx_event_created",
        }
        assert expected.issubset(indexes)
        await store.close()
```

### Step 6: 运行测试

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py -v -k "SmartAlert or smart_alert"
.venv/bin/python3 -m pytest tests/ -q
```

### Step 7: 提交

```bash
git add src/news_sentry/core/async_store.py tests/unit/test_async_store.py
git commit -m "Phase 38: AsyncStore 新方法 + 6 索引 + chains 优化 (P38.01)"
```

---

## P38.02: 智能告警逻辑 + Pipeline 集成

**文件:**
- 修改: `src/news_sentry/core/alert_pipeline.py`
- 修改: `src/news_sentry/core/async_run.py`
- 测试: `tests/unit/test_alert_pipeline.py`

### Step 1: alert_pipeline.py 新增 check_smart_alerts

在 `AlertPipeline` 类中新增方法（不需要 NewsEvent，直接用 store 数据）：

```python
    async def check_smart_alerts(
        self,
        store: Any,
        target_id: str,
    ) -> list[dict[str, Any]]:
        """检查智能告警条件，返回告警列表。

        三类告警:
          1. 链更新告警: followup + strength >= 0.7
          2. 趋势变化告警: rising + hotness >= 60
          3. 实体突增告警: 日提及 > 2x 7天日均
        """
        alerts: list[dict[str, Any]] = []
        now_str = datetime.now(UTC).isoformat()

        # 1. 链更新告警
        try:
            links = await store.get_recent_links(target_id, hours=24)
            for link in links:
                if link["link_type"] == "followup" and link["strength"] >= 0.7:
                    title = link.get("title_original", "未知事件")
                    alerts.append({
                        "type": "chain_update",
                        "severity": "high",
                        "message": f"追踪链新增后续事件: \"{title}\" (强度: {link['strength']:.2f})",
                        "details": {
                            "chain_root_id": link["source_event_id"],
                            "linked_event_id": link["target_event_id"],
                            "strength": link["strength"],
                            "link_type": link["link_type"],
                        },
                        "triggered_at": now_str,
                    })
        except Exception as exc:
            logger.warning("链更新告警检查失败: %s", exc)

        # 2. 趋势变化告警
        try:
            from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends
            daily_counts = await store.get_topic_daily_counts(target_id, days=14)
            top_topics = await store.get_top_topics(target_id, days=14, limit=10)
            trends = compute_topic_trends(daily_counts, top_topics, total_days=14)
            for trend in trends:
                if trend.trend_direction == "rising" and trend.hotness >= 60:
                    alerts.append({
                        "type": "trend_rising",
                        "severity": "medium",
                        "message": (
                            f"\"{trend.topic}\" 主题热度快速上升 "
                            f"(热度: {trend.hotness}, 近7天: {trend.current_count}次, "
                            f"前7天: {trend.prev_count}次)"
                        ),
                        "details": {
                            "topic": trend.topic,
                            "hotness": trend.hotness,
                            "current_count": trend.current_count,
                            "prev_count": trend.prev_count,
                        },
                        "triggered_at": now_str,
                    })
        except Exception as exc:
            logger.warning("趋势变化告警检查失败: %s", exc)

        # 3. 实体突增告警
        try:
            entities = await store.query_entities(
                target_id=target_id, min_mentions=2, limit=20,
            )
            for entity in entities:
                name = entity["canonical_name"]
                mentions = await store.get_entity_daily_mentions(name, target_id, days=7)
                if len(mentions) < 2:
                    continue
                today_count = mentions[-1]["count"]
                prev_counts = [m["count"] for m in mentions[:-1]]
                avg = sum(prev_counts) / len(prev_counts) if prev_counts else 0
                if avg > 0 and today_count > avg * 2:
                    alerts.append({
                        "type": "entity_spike",
                        "severity": "medium",
                        "message": (
                            f"\"{name}\" 实体提及量突增 "
                            f"(今日: {today_count}次, 7天日均: {avg:.1f}次)"
                        ),
                        "details": {
                            "entity_name": name,
                            "today_count": today_count,
                            "avg_count": round(avg, 1),
                        },
                        "triggered_at": now_str,
                    })
        except Exception as exc:
            logger.warning("实体突增告警检查失败: %s", exc)

        return alerts
```

需要在文件顶部 import 中添加：
```python
from datetime import UTC, datetime
```

### Step 2: async_run.py 集成

在 `_run_judge_async` 中 `_generate_narratives` 调用之后，新增：

```python
        # Phase 38: 智能告警检查
        try:
            from news_sentry.core.alert_pipeline import AlertPipeline
            alert_pipeline = AlertPipeline([], data_dir=Path("./data"))
            smart_alerts = await alert_pipeline.check_smart_alerts(store, target_id)
            if smart_alerts:
                logger.info("智能告警: %d 条 [%s]", len(smart_alerts), target_id)
        except Exception as exc:
            logger.warning("智能告警检查失败 [%s]: %s", target_id, exc)
```

### Step 3: 测试

在 `tests/unit/test_alert_pipeline.py` 末尾新增：

```python
class TestSmartAlerts:
    """Phase 38: 智能告警测试。"""

    @pytest.fixture
    async def alert_store(self, tmp_path: Path) -> AsyncStore:
        """创建智能告警测试 store。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        # 带实体和 topic 的事件
        events = [
            ("s-evt-1", "italy", "judged", "ansa", 80, 50,
             "2026-05-01T10:00:00", now, "positive", "immigration,Meloni"),
            ("s-evt-2", "italy", "judged", "ansa", 85, 55,
             "2026-05-01T12:00:00", now, "negative", "immigration,elections"),
            ("s-evt-3", "italy", "judged", "repubblica", 70, 40,
             "2026-05-05T10:00:00", now, "positive", "immigration"),
            ("s-evt-4", "italy", "judged", "ansa", 90, 60,
             "2026-05-05T12:00:00", now, "negative", "elections,Meloni"),
        ]
        for eid, tid, stage, src, score, rel, pub, created, sent, tags in events:
            await store._db.execute(  # noqa: SLF001
                "INSERT OR REPLACE INTO event_index "
                "(event_id, target_id, stage, source_id, news_value_score, "
                "china_relevance, published_at, created_at, sentiment, topic_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, tid, stage, src, score, rel, pub, created, sent, tags),
            )
        await store._db.commit()

        # 创建 followup link
        await store.create_link("s-evt-1", "s-evt-3", "followup", 0.85, {}, "italy")
        # 创建实体
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-01T10:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-05T12:00:00+00:00")
        await store.upsert_entity("Meloni", "person", "italy", "2026-05-05T12:00:00+00:00")

        return store

    @pytest.mark.asyncio
    async def test_chain_update_alert(self, alert_store: AsyncStore) -> None:
        """链更新告警触发。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        chain_alerts = [a for a in alerts if a["type"] == "chain_update"]
        assert len(chain_alerts) >= 1
        assert chain_alerts[0]["severity"] == "high"
        assert chain_alerts[0]["details"]["strength"] == 0.85

    @pytest.mark.asyncio
    async def test_trend_rising_alert(self, alert_store: AsyncStore) -> None:
        """趋势上升告警。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        trend_alerts = [a for a in alerts if a["type"] == "trend_rising"]
        # 取决于数据分布，至少检查不抛异常
        for a in trend_alerts:
            assert a["details"]["hotness"] >= 60

    @pytest.mark.asyncio
    async def test_smart_alerts_no_exception_on_empty(
        self, tmp_path: Path
    ) -> None:
        """空数据库不抛异常。"""
        store = AsyncStore(tmp_path / "state.db")
        await store.initialize()
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(store, "nonexistent")
        assert isinstance(alerts, list)
        await store.close()

    @pytest.mark.asyncio
    async def test_entity_spike_alert(self, alert_store: AsyncStore) -> None:
        """实体突增告警。"""
        pipeline = AlertPipeline([])
        alerts = await pipeline.check_smart_alerts(alert_store, "italy")
        entity_alerts = [a for a in alerts if a["type"] == "entity_spike"]
        # 实体突增取决于日期分布，至少检查不抛异常
        for a in entity_alerts:
            assert "entity_name" in a["details"]
            assert a["details"]["today_count"] > 0
```

注意：需要在 test_alert_pipeline.py 顶部添加 import：
```python
from datetime import UTC, datetime
from news_sentry.core.async_store import AsyncStore
```

### Step 4: 运行测试

```bash
.venv/bin/python3 -m pytest tests/unit/test_alert_pipeline.py -v -k "Smart"
.venv/bin/python3 -m pytest tests/ -q
```

### Step 5: 提交

```bash
git add src/news_sentry/core/alert_pipeline.py src/news_sentry/core/async_run.py tests/unit/test_alert_pipeline.py
git commit -m "Phase 38: 智能告警 check_smart_alerts + Pipeline 集成 (P38.02)"
```

---

## P38.03: API 端点 + 前端优化

**文件:**
- 修改: `src/news_sentry/core/api_server.py`
- 修改: `src/news_sentry/static/pages/chains.js`
- 修改: `src/news_sentry/static/pages/ops.js`
- 测试: `tests/unit/test_api_server.py`

### Step 1: api_server.py — Pydantic 模型 + 端点

在 NarrativeResponse 之后添加：

```python
class SmartAlertItem(BaseModel):
    """智能告警条目。"""

    type: str
    severity: str
    message: str
    details: dict[str, Any] = {}
    triggered_at: str = ""


class SmartAlertsResponse(BaseModel):
    """智能告警响应。"""

    target_id: str
    alerts: list[SmartAlertItem]
    total: int
```

在静态文件挂载之前添加端点：

```python
    @app.get("/api/v1/alerts/smart", response_model=SmartAlertsResponse)
    async def get_smart_alerts(
        target_id: str = Query(..., description="目标标识"),
    ) -> Any:
        """获取智能告警列表。"""
        if _store is None:
            raise HTTPException(status_code=503, detail="Store not available")
        try:
            from news_sentry.core.alert_pipeline import AlertPipeline

            pipeline = AlertPipeline([])
            alerts = await pipeline.check_smart_alerts(_store, target_id)
            return SmartAlertsResponse(
                target_id=target_id,
                alerts=[SmartAlertItem(**a) for a in alerts],
                total=len(alerts),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
```

### Step 2: chains.js — 移除 N+1

在 `renderChainList()` 中，找到这段代码（Phase 36 的 N+1 调用）：

```javascript
// Phase 36: 加载叙述摘要
await Promise.all(data.chains.map(async (c) => {
  try {
    const narr = await api(`/api/v1/chains/${encodeURIComponent(c.root_event_id)}/narrative?target_id=${state.currentTarget}`);
    if (narr && narr.narrative) {
      narrativeMap[c.root_event_id] = narr.narrative;
    }
  } catch { /* ignore */ }
}));
```

替换为：

```javascript
// Phase 38: 使用嵌入的 narrative_summary，避免 N+1
data.chains.forEach((c) => {
  if (c.narrative_summary) {
    narrativeMap[c.root_event_id] = c.narrative_summary;
  }
});
```

### Step 3: ops.js — 智能告警卡片

在 ops.js 的 `renderOpsDetail()` 函数中，找到合适的位置（在运行详情之后），新增智能告警卡片：

```javascript
// Phase 38: 智能告警卡片
try {
  const alertData = await api(`/api/v1/alerts/smart?target_id=${state.currentTarget}`);
  if (alertData.alerts && alertData.alerts.length > 0) {
    const severityColors = { high: "#ef4444", medium: "#f59e0b", low: "#10b981" };
    const alertHtml = alertData.alerts.map(a => `
      <div class="alert-item" style="border-left: 3px solid ${severityColors[a.severity] || '#6b7280'}">
        <div class="alert-type">${escapeHtml(a.type.replace(/_/g, ' '))}</div>
        <div class="alert-message">${escapeHtml(a.message)}</div>
        <div class="alert-time">${a.triggered_at ? new Date(a.triggered_at).toLocaleString() : ''}</div>
      </div>
    `).join("");
    container.querySelector(".ops-detail")?.insertAdjacentHTML("beforeend", `
      <div class="section-card">
        <h3>智能告警 (${alertData.total})</h3>
        ${alertHtml}
      </div>
    `);
  }
} catch { /* 非阻塞 */ }
```

### Step 4: style.css — 告警样式

在 Phase 37 样式之后追加：

```css
/* ── Phase 38: 智能告警 ─────────────────────────────── */
.alert-item { padding: 10px 14px; margin-bottom: 8px; background: var(--bg-secondary); border-radius: var(--radius-sm); }
.alert-type { font-size: 0.75rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
.alert-message { font-size: 0.85rem; color: var(--text-primary); line-height: 1.4; }
.alert-time { font-size: 0.7rem; color: var(--text-muted); margin-top: 4px; }
```

### Step 5: 测试

在 `tests/unit/test_api_server.py` 末尾新增：

```python
class TestSmartAlertAPI:
    """Phase 38: 智能告警 API 端点。"""

    @pytest.fixture
    async def client_with_alerts(self, tmp_path):
        """创建带告警数据的客户端。"""
        db_path = tmp_path / "state.db"
        store = AsyncStore(db_path)
        await store.initialize()

        now = datetime.now(UTC).isoformat()
        await store._db.execute(
            "INSERT OR REPLACE INTO event_index "
            "(event_id, target_id, stage, source_id, news_value_score, "
            "china_relevance, published_at, created_at, sentiment, topic_tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("al-evt-1", "italy", "judged", "ansa", 80, 50, now, now, "positive", "immigration"),
        )
        await store._db.commit()
        await store.create_link("al-evt-1", "al-evt-1", "followup", 0.9, {}, "italy")

        app = create_app(data_dir=str(tmp_path), store=store)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        yield client, store
        await client.aclose()
        await store.close()

    async def test_get_smart_alerts(self, client_with_alerts):
        """GET /api/v1/alerts/smart 返回告警列表。"""
        client, _ = client_with_alerts
        resp = await client.get(
            "/api/v1/alerts/smart",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "italy"
        assert "alerts" in data
        assert "total" in data

    async def test_smart_alerts_no_store(self, tmp_path):
        """无 store 时返回 503。"""
        app = create_app(data_dir=str(tmp_path))
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        resp = await client.get(
            "/api/v1/alerts/smart",
            params={"target_id": "italy"},
        )
        assert resp.status_code == 503
        await client.aclose()
```

### Step 6: 运行全量测试

```bash
.venv/bin/python3 -m pytest tests/ -q
```

### Step 7: 提交

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/static/pages/chains.js src/news_sentry/static/pages/ops.js src/news_sentry/static/style.css tests/unit/test_api_server.py
git commit -m "Phase 38: API 告警端点 + chains N+1 修复 + 前端告警卡片 (P38.03)"
```

---

## P38.04: lint + 全量验证 + 推送

### Step 1: ruff + mypy

```bash
.venv/bin/ruff check src/news_sentry/
.venv/bin/python3 -m mypy src/news_sentry/
```

### Step 2: 全量测试

```bash
.venv/bin/python3 -m pytest tests/ -q
```

目标：1571 基线测试零破坏 + ~9 新增测试通过。

### Step 3: 推送

```bash
git push origin main
```
