# Phase 37 实现计划: 量化趋势分析

> 目标: 基于已有 event_index 数据，实现按天聚合的主题热度趋势和情感分布趋势，Web UI 折线图展示。

---

## P37.01: AsyncStore 聚合查询方法 + 趋势计算

**文件:**
- 修改: `src/news_sentry/core/async_store.py`
- 修改: `src/news_sentry/skills/analysis/trend_analyzer.py`
- 测试: `tests/unit/test_async_store.py`
- 测试: `tests/unit/test_trend_analyzer.py`

### Step 1: AsyncStore — get_sentiment_daily_counts

在 `async_store.py` 末尾新增方法（在 Entity Tracking 方法之前，或放在类末尾都可以）：

```python
async def get_sentiment_daily_counts(
    self, target_id: str, days: int = 14
) -> list[dict[str, Any]]:
    """按天统计情感分布，返回 [{day, sentiment, count}, ...]."""
    if self._db is None:
        return []
    async with self._db.execute(
        "SELECT date(published_at) AS day, sentiment, COUNT(*) AS cnt "
        "FROM event_index "
        "WHERE target_id = ? AND stage = 'judged' "
        "AND published_at >= date('now', ? || ' days') "
        "AND sentiment IS NOT NULL "
        "GROUP BY day, sentiment ORDER BY day",
        [target_id, f"-{days}"],
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"day": r[0], "sentiment": r[1], "count": r[2]} for r in rows]
```

### Step 2: AsyncStore — get_topic_daily_counts

topic_tags 是逗号分隔的字符串，需 Python 层拆分。先查原始行，再拆分聚合：

```python
async def get_topic_daily_counts(
    self, target_id: str, days: int = 14
) -> list[dict[str, Any]]:
    """按天统计每个 topic 的出现次数，返回 [{topic, day, count}, ...]."""
    if self._db is None:
        return []
    async with self._db.execute(
        "SELECT date(published_at) AS day, topic_tags "
        "FROM event_index "
        "WHERE target_id = ? AND stage = 'judged' "
        "AND published_at >= date('now', ? || ' days') "
        "AND topic_tags IS NOT NULL AND topic_tags != ''",
        [target_id, f"-{days}"],
    ) as cursor:
        rows = await cursor.fetchall()
    # Python 层拆分 topic_tags 并按 (topic, day) 聚合
    counts: dict[tuple[str, str], int] = {}
    for day, tags_str in rows:
        for tag in tags_str.split(","):
            tag = tag.strip()
            if tag:
                key = (tag, day)
                counts[key] = counts.get(key, 0) + 1
    return [
        {"topic": topic, "day": day, "count": cnt}
        for (topic, day), cnt in sorted(counts.items())
    ]
```

### Step 3: AsyncStore — get_top_topics

```python
async def get_top_topics(
    self, target_id: str, days: int = 7, limit: int = 10
) -> list[dict[str, Any]]:
    """获取最近 N 天最热主题排名。"""
    if self._db is None:
        return []
    # 先查原始行，Python 层拆分聚合（与 get_topic_daily_counts 一致）
    async with self._db.execute(
        "SELECT topic_tags FROM event_index "
        "WHERE target_id = ? AND stage = 'judged' "
        "AND published_at >= date('now', ? || ' days') "
        "AND topic_tags IS NOT NULL AND topic_tags != ''",
        [target_id, f"-{days}"],
    ) as cursor:
        rows = await cursor.fetchall()
    topic_counts: dict[str, int] = {}
    for (tags_str,) in rows:
        for tag in tags_str.split(","):
            tag = tag.strip()
            if tag:
                topic_counts[tag] = topic_counts.get(tag, 0) + 1
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"topic": t, "count": c} for t, c in sorted_topics]
```

### Step 4: 扩展 TrendReport 模型 + compute_topic_trends

修改 `src/news_sentry/skills/analysis/trend_analyzer.py`：

```python
class DailyCount(BaseModel):
    """单日计数。"""
    day: str
    count: int


class TopicTrend(BaseModel):
    """单个议题的热度趋势."""
    topic: str
    hotness: int  # 0-100
    trend_direction: str  # rising / stable / falling
    event_count: int
    current_count: int = 0
    prev_count: int = 0
    daily_counts: list[DailyCount] = []


class TrendReport(BaseModel):
    """舆情趋势分析报告."""
    target_id: str
    period_start: str
    period_end: str
    topics: list[TopicTrend] = []
    overall_sentiment: dict[str, int] = {}
    generated_at: str = ""
```

新增函数（在 TrendReport 类之后）：

```python
def compute_topic_trends(
    daily_counts: list[dict[str, Any]],
    top_topics: list[dict[str, Any]],
    total_days: int = 14,
) -> list[TopicTrend]:
    """基于每日 topic 计数和 top topics 列表，计算趋势方向。

    Args:
        daily_counts: get_topic_daily_counts() 的返回值
        top_topics: get_top_topics() 的返回值
        total_days: 总天数（前后各一半）
    """
    if not top_topics:
        return []

    half = total_days // 2  # 前/后半段天数

    # 按前/后半段聚合每个 topic 的计数
    current_counts: dict[str, int] = {}
    prev_counts: dict[str, int] = {}
    topic_daily: dict[str, list[DailyCount]] = {}

    for entry in daily_counts:
        topic = entry["topic"]
        day = entry["day"]
        cnt = entry["count"]
        topic_daily.setdefault(topic, []).append(DailyCount(day=day, count=cnt))

    # 需要知道日期分界线 — 取 daily_counts 中日期的中位数
    all_days = sorted({e["day"] for e in daily_counts}) if daily_counts else []
    if all_days and len(all_days) >= 2:
        cutoff = all_days[-half] if len(all_days) > half else all_days[0]
    else:
        cutoff = ""

    for entry in daily_counts:
        topic = entry["topic"]
        day = entry["day"]
        cnt = entry["count"]
        if day >= cutoff:
            current_counts[topic] = current_counts.get(topic, 0) + cnt
        else:
            prev_counts[topic] = prev_counts.get(topic, 0) + cnt

    # 找最大 current_count 用于 hotness 归一化
    max_current = max(current_counts.values()) if current_counts else 1
    if max_current == 0:
        max_current = 1

    results: list[TopicTrend] = []
    for tp in top_topics:
        topic = tp["topic"]
        cur = current_counts.get(topic, 0)
        prev = prev_counts.get(topic, 0)

        # 趋势判定
        if prev == 0:
            direction = "rising" if cur > 0 else "stable"
        elif cur > prev * 1.2:
            direction = "rising"
        elif cur < prev * 0.8:
            direction = "falling"
        else:
            direction = "stable"

        hotness = min(int(cur / max_current * 100), 100)
        daily = topic_daily.get(topic, [])

        results.append(TopicTrend(
            topic=topic,
            hotness=hotness,
            trend_direction=direction,
            event_count=cur + prev,
            current_count=cur,
            prev_count=prev,
            daily_counts=daily,
        ))

    return results
```

### Step 5: 测试

在 `tests/unit/test_async_store.py` 新增测试：

```python
@pytest.mark.asyncio
async def test_get_sentiment_daily_counts(store_with_events):
    """按天统计情感分布."""
    store = store_with_events
    result = await store.get_sentiment_daily_counts("test-target", days=30)
    assert isinstance(result, list)
    if result:
        assert "day" in result[0]
        assert "sentiment" in result[0]
        assert "count" in result[0]


@pytest.mark.asyncio
async def test_get_topic_daily_counts(store_with_events):
    """按天统计 topic 出现次数."""
    store = store_with_events
    result = await store.get_topic_daily_counts("test-target", days=30)
    assert isinstance(result, list)
    if result:
        assert "topic" in result[0]
        assert "day" in result[0]
        assert "count" in result[0]


@pytest.mark.asyncio
async def test_get_top_topics(store_with_events):
    """获取最热主题排名."""
    store = store_with_events
    result = await store.get_top_topics("test-target", days=30, limit=5)
    assert isinstance(result, list)
    if result:
        assert result[0]["count"] >= result[-1]["count"]  # 降序
```

> 注：`store_with_events` fixture 需确保插入了带 sentiment、topic_tags、published_at 的测试数据。如果现有 fixture 没有这些字段，需要扩展或创建新 fixture。

在 `tests/unit/test_trend_analyzer.py` 新增测试：

```python
from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends


def test_compute_topic_trends_rising():
    """上升主题判定."""
    daily_counts = [
        {"topic": "AI", "day": "2026-05-01", "count": 2},
        {"topic": "AI", "day": "2026-05-08", "count": 8},
    ]
    top_topics = [{"topic": "AI", "count": 10}]
    result = compute_topic_trends(daily_counts, top_topics, total_days=14)
    assert len(result) == 1
    assert result[0].topic == "AI"
    assert result[0].current_count > 0
    assert result[0].trend_direction in ("rising", "stable", "falling")


def test_compute_topic_trends_falling():
    """下降主题判定."""
    daily_counts = [
        {"topic": "Elections", "day": "2026-05-01", "count": 10},
        {"topic": "Elections", "day": "2026-05-08", "count": 2},
    ]
    top_topics = [{"topic": "Elections", "count": 12}]
    result = compute_topic_trends(daily_counts, top_topics, total_days=14)
    assert result[0].trend_direction == "falling"


def test_compute_topic_trends_empty():
    """空输入返回空列表."""
    assert compute_topic_trends([], [], total_days=14) == []
```

### Step 6: 运行测试验证

```bash
.venv/bin/python3 -m pytest tests/unit/test_async_store.py tests/unit/test_trend_analyzer.py -v
```

### Step 7: 提交

```bash
git add src/news_sentry/core/async_store.py src/news_sentry/skills/analysis/trend_analyzer.py tests/unit/test_async_store.py tests/unit/test_trend_analyzer.py
git commit -m "Phase 37: AsyncStore 聚合查询 + 趋势计算 (P37.01)"
```

---

## P37.02: API 趋势端点

**文件:**
- 修改: `src/news_sentry/core/api_server.py`
- 测试: `tests/unit/test_api_server.py`

### Step 1: 新增 Pydantic 模型

在 `api_server.py` 的 Pydantic 模型区域新增：

```python
class DailySentimentCount(BaseModel):
    """每日情感计数。"""
    day: str
    positive: int = 0
    negative: int = 0
    neutral: int = 0


class TopicTrendItem(BaseModel):
    """主题趋势条目。"""
    topic: str
    trend_direction: str
    hotness: int
    current_count: int
    prev_count: int
    event_count: int
    daily_counts: list[dict[str, Any]]


class TopicTrendsResponse(BaseModel):
    """主题趋势响应。"""
    target_id: str
    days: int
    topics: list[TopicTrendItem]
    generated_at: str


class SentimentTrendsResponse(BaseModel):
    """情感趋势响应。"""
    target_id: str
    days: int
    daily_sentiment: list[DailySentimentCount]
    generated_at: str
```

### Step 2: 新增 2 个端点

```python
@app.get("/api/v1/trends/topics", response_model=TopicTrendsResponse)
async def get_topic_trends(
    target_id: str = Query(...),
    days: int = Query(14, ge=7, le=30),
) -> Any:
    """主题热度趋势。"""
    store = _get_store()
    daily_counts = await store.get_topic_daily_counts(target_id, days=days)
    top_topics = await store.get_top_topics(target_id, days=days, limit=10)
    from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends
    topics = compute_topic_trends(daily_counts, top_topics, total_days=days)
    return TopicTrendsResponse(
        target_id=target_id,
        days=days,
        topics=[TopicTrendItem(**t.model_dump()) for t in topics],
        generated_at=datetime.now(UTC).isoformat(),
    )


@app.get("/api/v1/trends/sentiment", response_model=SentimentTrendsResponse)
async def get_sentiment_trends(
    target_id: str = Query(...),
    days: int = Query(14, ge=7, le=30),
) -> Any:
    """情感分布趋势。"""
    store = _get_store()
    raw = await store.get_sentiment_daily_counts(target_id, days=days)
    # 转换为按天聚合格式
    day_map: dict[str, DailySentimentCount] = {}
    for entry in raw:
        d = entry["day"]
        if d not in day_map:
            day_map[d] = DailySentimentCount(day=d)
        item = day_map[d]
        sentiment = entry["sentiment"]
        if sentiment == "positive":
            item.positive = entry["count"]
        elif sentiment == "negative":
            item.negative = entry["count"]
        elif sentiment == "neutral":
            item.neutral = entry["count"]
    daily = sorted(day_map.values(), key=lambda x: x.day)
    return SentimentTrendsResponse(
        target_id=target_id,
        days=days,
        daily_sentiment=daily,
        generated_at=datetime.now(UTC).isoformat(),
    )
```

### Step 3: 测试

在 `tests/unit/test_api_server.py` 新增：

```python
@pytest.mark.asyncio
async def test_get_topic_trends(api_client_with_data):
    """GET /api/v1/trends/topics."""
    resp = await api_client_with_data.get(
        "/api/v1/trends/topics?target_id=test-target&days=14"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_id"] == "test-target"
    assert data["days"] == 14
    assert "topics" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_get_sentiment_trends(api_client_with_data):
    """GET /api/v1/trends/sentiment."""
    resp = await api_client_with_data.get(
        "/api/v1/trends/sentiment?target_id=test-target&days=14"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_id"] == "test-target"
    assert "daily_sentiment" in data
    assert "generated_at" in data
```

> 注：`api_client_with_data` fixture 需确保测试数据库中有带 sentiment、topic_tags 的事件数据。

### Step 4: 运行测试验证

```bash
.venv/bin/python3 -m pytest tests/unit/test_api_server.py -v -k "trend"
```

### Step 5: 提交

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "Phase 37: API 趋势端点 topics + sentiment (P37.02)"
```

---

## P37.03: 前端趋势页

**文件:**
- 新建: `src/news_sentry/static/pages/trends.js`
- 修改: `src/news_sentry/static/app.js`
- 修改: `src/news_sentry/static/index.html`
- 修改: `src/news_sentry/static/style.css`

### Step 1: index.html — Chart.js CDN + 侧边栏入口

在 `<head>` 中 `<link>` 之后添加：
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
```

在侧边栏"追踪链"链接之后添加：
```html
<a href="#/trends" class="nav-item" data-page="trends">
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
  </svg>
  <span>趋势分析</span>
</a>
```

### Step 2: app.js — trends 路由

在 import 区域新增：
```javascript
import { renderTrends } from "./pages/trends.js";
```

在 titles 对象新增：
```javascript
trends: "趋势分析",
```

在路由分发区域新增：
```javascript
} else if (page === "trends") {
  renderTrends();
```

### Step 3: 新建 trends.js

```javascript
/**
 * News Sentry — 趋势分析页
 * 主题热度折线图 + 情感分布面积图 + 主题排行表
 */
"use strict";

import { state, dom, $, escapeHtml, api } from "../api.js";

let topicChart = null;
let sentimentChart = null;
let currentDays = 14;

export async function renderTrends() {
  const container = dom.pageContainer;
  currentDays = 14;

  container.innerHTML = `
    <div class="trends-page">
      <div class="trends-controls">
        <div class="days-toggle">
          <button class="btn-days active" data-days="7">7天</button>
          <button class="btn-days" data-days="14">14天</button>
          <button class="btn-days" data-days="30">30天</button>
        </div>
      </div>
      <div class="stats-grid" id="trendStats">
        <div class="stat-card"><div class="stat-value" id="topicCount">-</div><div class="stat-label">追踪主题</div></div>
        <div class="stat-card"><div class="stat-value" id="risingCount">-</div><div class="stat-label">上升主题</div></div>
        <div class="stat-card"><div class="stat-value" id="fallingCount">-</div><div class="stat-label">下降主题</div></div>
        <div class="stat-card"><div class="stat-value" id="monitorDays">-</div><div class="stat-label">监控天数</div></div>
      </div>
      <div class="chart-section">
        <h3>主题热度趋势</h3>
        <div class="chart-container"><canvas id="topicChart"></canvas></div>
      </div>
      <div class="topic-table-section">
        <h3>主题排行</h3>
        <table class="data-table" id="topicTable">
          <thead><tr><th>主题</th><th>趋势</th><th>热度</th><th>近7天</th><th>前7天</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="chart-section">
        <h3>情感分布趋势</h3>
        <div class="chart-container"><canvas id="sentimentChart"></canvas></div>
      </div>
    </div>
  `;

  // 天数切换
  container.querySelectorAll(".btn-days").forEach((btn) => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".btn-days").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentDays = parseInt(btn.dataset.days, 10);
      loadData();
    });
  });
  // 设置默认选中14天
  container.querySelector('.btn-days[data-days="14"]').classList.add("active");
  container.querySelector('.btn-days[data-days="7"]').classList.remove("active");

  await loadData();
}

async function loadData() {
  const targetId = state.currentTarget;
  if (!targetId) return;

  try {
    const [topicData, sentimentData] = await Promise.all([
      api(`/api/v1/trends/topics?target_id=${targetId}&days=${currentDays}`),
      api(`/api/v1/trends/sentiment?target_id=${targetId}&days=${currentDays}`),
    ]);

    renderStats(topicData);
    renderTopicChart(topicData);
    renderTopicTable(topicData);
    renderSentimentChart(sentimentData);
  } catch (err) {
    dom.pageContainer.querySelector(".trends-page").innerHTML +=
      `<div class="error-msg">加载趋势数据失败: ${escapeHtml(err.message)}</div>`;
  }
}

function renderStats(data) {
  const topics = data.topics || [];
  document.getElementById("topicCount").textContent = topics.length;
  document.getElementById("risingCount").textContent = topics.filter((t) => t.trend_direction === "rising").length;
  document.getElementById("fallingCount").textContent = topics.filter((t) => t.trend_direction === "falling").length;
  document.getElementById("monitorDays").textContent = data.days;
}

function renderTopicChart(data) {
  const topics = data.topics || [];
  if (topicChart) topicChart.destroy();

  const allDays = [...new Set(topics.flatMap((t) => t.daily_counts.map((d) => d.day)))].sort();

  const colors = [
    "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6",
  ];

  const datasets = topics.slice(0, 10).map((t, i) => ({
    label: t.topic,
    data: allDays.map((d) => {
      const found = t.daily_counts.find((dc) => dc.day === d);
      return found ? found.count : 0;
    }),
    borderColor: colors[i % colors.length],
    backgroundColor: colors[i % colors.length] + "20",
    tension: 0.3,
    fill: false,
  }));

  const ctx = document.getElementById("topicChart");
  if (!ctx) return;
  topicChart = new Chart(ctx, {
    type: "line",
    data: { labels: allDays, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top", labels: { color: "#e5e7eb" } } },
      scales: {
        x: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" } },
        y: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" }, beginAtZero: true },
      },
    },
  });
}

function renderTopicTable(data) {
  const topics = data.topics || [];
  const tbody = document.querySelector("#topicTable tbody");
  if (!tbody) return;

  const dirLabels = { rising: "↑ 上升", stable: "→ 稳定", falling: "↓ 下降" };
  const dirClasses = { rising: "badge-rising", stable: "badge-stable", falling: "badge-falling" };

  tbody.innerHTML = topics
    .map(
      (t) => `<tr>
      <td>${escapeHtml(t.topic)}</td>
      <td><span class="trend-badge ${dirClasses[t.trend_direction]}">${dirLabels[t.trend_direction]}</span></td>
      <td><div class="hotness-bar"><div class="hotness-fill" style="width:${t.hotness}%"></div></div></td>
      <td>${t.current_count}</td>
      <td>${t.prev_count}</td>
    </tr>`
    )
    .join("");
}

function renderSentimentChart(data) {
  const daily = data.daily_sentiment || [];
  if (sentimentChart) sentimentChart.destroy();

  const labels = daily.map((d) => d.day);
  const ctx = document.getElementById("sentimentChart");
  if (!ctx) return;

  sentimentChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "正面",
          data: daily.map((d) => d.positive),
          borderColor: "#10b981",
          backgroundColor: "#10b98130",
          fill: true,
          tension: 0.3,
        },
        {
          label: "负面",
          data: daily.map((d) => d.negative),
          borderColor: "#ef4444",
          backgroundColor: "#ef444430",
          fill: true,
          tension: 0.3,
        },
        {
          label: "中性",
          data: daily.map((d) => d.neutral),
          borderColor: "#6b7280",
          backgroundColor: "#6b728030",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top", labels: { color: "#e5e7eb" } } },
      scales: {
        x: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" } },
        y: { ticks: { color: "#9ca3af" }, grid: { color: "#374151" }, beginAtZero: true },
      },
    },
  });
}
```

### Step 4: style.css — 趋势页样式

在文件末尾追加：

```css
/* ── Phase 37: 趋势分析 ─────────────────────────── */
.trends-page .trends-controls {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}
.days-toggle {
  display: flex;
  gap: 0.25rem;
  background: var(--bg-card);
  border-radius: 6px;
  padding: 2px;
}
.btn-days {
  padding: 0.35rem 0.75rem;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-days.active {
  background: var(--accent);
  color: #fff;
}
.chart-section {
  margin-bottom: 1.5rem;
}
.chart-section h3 {
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}
.chart-container {
  background: var(--bg-card);
  border-radius: 8px;
  padding: 1rem;
  height: 300px;
}
.topic-table-section {
  margin-bottom: 1.5rem;
}
.topic-table-section h3 {
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}
.trend-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
}
.badge-rising {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
}
.badge-stable {
  background: rgba(107, 114, 128, 0.2);
  color: #9ca3af;
}
.badge-falling {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}
.hotness-bar {
  width: 100px;
  height: 8px;
  background: var(--bg-hover);
  border-radius: 4px;
  overflow: hidden;
}
.hotness-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
}
```

### Step 5: 运行全量测试验证

```bash
.venv/bin/python3 -m pytest tests/ -q
```

### Step 6: 提交

```bash
git add src/news_sentry/static/pages/trends.js src/news_sentry/static/app.js src/news_sentry/static/index.html src/news_sentry/static/style.css
git commit -m "Phase 37: 前端趋势分析页 Chart.js 折线图 + 排行表 (P37.03)"
```

---

## P37.04: lint + 全量验证

### Step 1: ruff + mypy

```bash
.venv/bin/ruff check src/news_sentry/
.venv/bin/python3 -m mypy src/news_sentry/
```

### Step 2: 全量测试

```bash
.venv/bin/python3 -m pytest tests/ -q
```

目标：1559 基线测试零破坏 + ~9 新增测试通过。

### Step 3: 提交 + 推送

```bash
git add -A
git commit -m "Phase 37: lint + 验证通过 (P37.04)"
git push origin main
```
