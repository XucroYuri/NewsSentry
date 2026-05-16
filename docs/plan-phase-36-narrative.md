# Phase 36: 事件时间线叙事 — 设计文档

> 日期: 2026-05-16
> 状态: 设计确认
> 前置: Phase 35 事件追踪链完成 (1549 tests, 92% coverage)

## 1. 背景与目标

Phase 35 建立了事件追踪链能力（event_links 表 + 关联算法 + 时间线 UI）。但链只是一组事件的列表，缺乏"故事性"——用户需要手动阅读每条事件标题来理解发展脉络。

**目标：** 对追踪链自动生成 AI 叙述，用自然语言概括事件发展脉络，在 Web UI 中展示。

**非目标：** 跨链叙事、用户编辑叙述、叙述版本管理。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 叙述生成 | LLM 调用 (ProviderRouter task_type="narrative") | 复用现有 AI 路由，自然语言质量高 |
| 触发时机 | Pipeline 自动 + 用户手动重新生成 | 自动保证覆盖率，手动支持刷新 |
| 存储 | SQLite chain_narratives 表 | 与 AsyncStore 一致，查询高效 |
| 去重 | SHA-256 hash 比较事件列表 | 事件不变则不重复生成，节省 AI 调用 |
| 链长度分级 | 短链一段/中链两段/长链截断 | 保证叙述质量和 LLM 输入可控 |

## 3. 数据模型

### 3.1 chain_narratives 表

```sql
CREATE TABLE IF NOT EXISTS chain_narratives (
    chain_root_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    narrative TEXT NOT NULL,
    narrative_hash TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    model_used TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.2 narrative_hash 机制

对链上事件的 `(event_id + published_at + title_original)` 排序后拼接，计算 SHA-256。

- 事件列表未变化 → hash 相同 → 跳过生成
- 新增事件 → hash 变化 → 自动重新生成

### 3.3 链长度分级

| 长度 | 策略 | 叙述结构 |
|------|------|----------|
| <=5 事件 | 全部事件输入 LLM | 一段叙述（150 字以内） |
| 6-10 事件 | 全部事件输入 LLM | 背景段 + 最新进展段（两段） |
| >10 事件 | 截断最近 10 事件 | 前序一句话背景 + 最近 10 事件叙述 |

## 4. 叙述生成算法

### 4.1 Prompt 模板

```
你是新闻分析助手。以下是同一事件发展脉络中的 N 条新闻报道，按时间排列：

{每条：时间 | 标题 | 情感(positive/negative/neutral) | 关键实体 | 主题标签}

请用一段话（150字以内）概括这个事件的发展脉络，突出关键转折和核心人物。
```

中链追加：`请分两段：第一段概括事件背景和起因，第二段描述最新进展和走向。`

长链追加：`前序事件摘要：{前序事件标题列表}。以下是最新的进展：`

### 4.2 执行位置

```
collect → filter → judge → [link_events] → [generate_narratives] → output
```

在 `_run_judge_async` 中，`_link_events` 之后，新增 `_generate_narratives()` 调用。

### 4.3 生成逻辑

1. 查询本次 run 中新增了 link 的链（通过 event_links 的 created_at 判断）
2. 对每条链调用 `get_event_chain()` 获取扩展字段
3. 计算 narrative_hash，与已有叙述比较
4. hash 不同 → 调用 LLM 生成叙述 → 写入 chain_narratives
5. hash 相同 → 跳过
6. `try/except` 包裹 — 失败不阻塞 pipeline

## 5. AsyncStore 新增方法

- `get_narrative(chain_root_id)` — 获取链叙述
- `upsert_narrative(chain_root_id, target_id, narrative, narrative_hash, event_count, model_used)` — 写入/更新叙述
- `compute_chain_hash(events)` — 计算事件列表的 SHA-256

同时扩展 `get_event_chain()` 返回字段：新增 `sentiment, entity_names, topic_tags, news_value_score`。

## 6. API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/chains/{root_id}/narrative` | 获取链叙述 |
| POST | `/api/v1/chains/{root_id}/narrative` | 手动重新生成叙述 |

### 6.1 GET 响应结构

```json
{
  "chain_root_id": "evt-1",
  "narrative": "意大利总理梅洛尼于5月16日访问欧盟总部讨论移民政策...",
  "event_count": 5,
  "model_used": "gpt-4o-mini",
  "generated_at": "2026-05-16T15:00:00+00:00"
}
```

### 6.2 POST 响应

与 GET 相同结构，重新生成后返回。

## 7. 前端增强

### 7.1 链详情页 (`#/chains/{id}`)

- 时间线上方新增"AI 叙述"卡片
- 显示叙述文本 + 生成时间 + 模型名
- 右上角"重新生成"按钮（POST 调用 + loading 状态）
- 无叙述时显示"暂无叙述"占位

### 7.2 链列表页 (`#/chains`)

- 每行新增"叙述"列
- 有叙述：显示前 50 字 + "..."
- 无叙述：显示"-"

## 8. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/core/async_store.py` | 修改 | chain_narratives 表 + 3 方法 + get_event_chain 扩展 |
| `src/news_sentry/core/async_run.py` | 修改 | _generate_narratives() 协程 |
| `src/news_sentry/core/api_server.py` | 修改 | 2 个端点 + 2 个 Pydantic 模型 |
| `src/news_sentry/static/pages/chains.js` | 修改 | 叙述卡片 + 重新生成按钮 + 列表摘要 |
| `tests/unit/test_async_store.py` | 修改 | chain_narratives 测试 |
| `tests/unit/test_async_run.py` | 修改 | 叙述生成测试 |
| `tests/unit/test_api_server.py` | 修改 | 叙述端点测试 |

## 9. 测试计划

| 测试文件 | 测试内容 | 预计新增 |
|----------|----------|----------|
| `test_async_store.py` | 表创建 + 叙述 CRUD + hash 检测 + chain 字段扩展 | ~5 tests |
| `test_api_server.py` | 2 个端点 | ~3 tests |
| `test_async_run.py` | _generate_narratives 集成 | ~2 tests |

预计新增 ~10 tests，总测试数 ~1559。

## 10. 验收标准

1. 1549 后端测试零破坏
2. `chain_narratives` 表正确创建
3. `get_event_chain()` 返回扩展字段（sentiment, entities, topic_tags, score）
4. AI 叙述能基于链上事件自动生成
5. 短链一段叙述，中链两段，长链截断最近 10 事件
6. narrative_hash 变化时自动重新生成
7. GET/POST `/chains/{root_id}/narrative` 正常工作
8. 链详情页显示叙述卡片 + 重新生成按钮
9. 链列表页显示叙述摘要
10. 叙述生成失败不阻塞 pipeline
11. ruff=0, mypy=0
