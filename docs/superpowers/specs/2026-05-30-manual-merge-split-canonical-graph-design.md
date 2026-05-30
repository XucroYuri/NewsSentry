# Manual Merge/Split Canonical Graph 设计规格

> 日期：2026-05-30
> 状态：设计稿
> 上游阶段：`docs/superpowers/specs/2026-05-30-shadow-canonical-data-spine-design.md`
> 前置阶段：`docs/superpowers/specs/2026-05-30-professional-research-workflow-mvp-design.md`

## 1. 目标

本阶段把研究工作台中的人工 merge/split 决策真正应用到 shadow canonical graph。

> 当前 main 对齐说明：graph apply UI 入口在当前 Admin Shell 的 `#/admin/news/research`，由 `src/news_sentry/static/pages/research_workbench.js` 调用 `/api/v1/research/graph/*`。早期设计中提到的 target workbench 是历史上下文，当前拆分不恢复旧文件。

上一阶段已经实现：

- canonical event、event mention、canonical relation 的影子事实层。
- research artifacts，用于记录确认、标注、合并建议和拆分建议。
- target 工作台中的研究队列、证据查看和人工决策记录。

本阶段要补齐缺口：

- `merge_decision` 不再停留在“人工建议”，可以经过预检后把多个 canonical events 合并为一个事实事件。
- `split_decision` 不再停留在“人工建议”，可以经过预检后把误合并的 mentions 拆出到新的 canonical event。
- 所有应用动作必须事务化、幂等、可审计，不硬删除 canonical event、mention 或 research artifact。
- 应用结果必须直接影响后续研究队列、事件详情和 canonical graph 查询，避免研究工作台再次形成局部数据孤岛。

一句话边界：

**人工决策仍由 research artifact 承载；graph apply 是受控事务，把人工决策转化为 canonical event / mention / relation 的可追溯状态变化。**

## 2. 非目标

本阶段不做：

- 不引入自动 AI merge/split 执行器。
- 不重写 projection/backfill 的自动归并算法。
- 不硬删除 canonical events、mentions、relations、Markdown 草稿或原始 NewsEvent。
- 不实现完整自动回滚 UI。
- 不引入多用户权限、云端审计表、团队协作锁或审批流。
- 不把公开新闻门户切换为 canonical-first。
- 不做跨 target merge/split。
- 不改变 collect/filter/judge/output 主 pipeline 写入路径。

这些能力进入后续独立阶段。

## 3. 设计原则

### 3.1 保守事实层

新闻研究中，错误合并比重复事实更危险。所有人工 merge/split 都必须先预检，再显式应用。

应用时：

- 不删除历史 canonical event。
- 不删除 mention。
- 不删除 research artifact。
- 被合并的 canonical event 标记为 `status = "merged"`。
- 被拆分出的 mention 移动到新的 canonical event。
- 原事件和新事件之间保留 relation 与 operation metadata。

### 3.2 研究动作和事实变化分层

`research_artifacts` 继续表达“人为什么这么判断”。

新增 graph operation 表达“系统实际改了什么”。

两者关系：

- 一个 `merge_decision` / `split_decision` artifact 可以被应用一次。
- 应用后 artifact 状态改为 `resolved`。
- artifact metadata 写入 `applied_operation_id`、`applied_at`、`applied_by`。
- operation log 记录每个 mention 移动、event 状态变化和 relation 创建。

### 3.3 幂等

相同 artifact 的同一次 apply 重复提交不得重复移动 mention、重复创建 relation 或重复污染 operation log。

幂等规则：

- 如果 artifact 已有 `applied_operation_id`，再次 apply 返回已存在 operation 的结果。
- merge relation ID 基于 operation、source、survivor 确定性生成。
- split 新 canonical event ID 基于 target、source event、mention IDs 和 operation identity 确定性生成。
- mention 已经在目标 canonical event 下时视为 no-op change，不报错。

### 3.4 Target Scope

所有对象必须属于同一个 `target_id`。

必须拒绝：

- survivor 和 candidate 跨 target。
- split source event 和 affected mentions 跨 target。
- decision artifact 的 `target_id` 与请求 target 不一致。
- decision artifact 的 `subject_id` 与请求 source/survivor 不一致。

### 3.5 可诊断失败

预检失败必须返回可渲染的错误和建议，而不是页面长期加载。

典型失败：

- canonical event 不存在。
- mention 不存在。
- mention 不属于 source canonical event。
- split 会让原 canonical event 没有任何 mention。
- merge candidate 包含 survivor 自身。
- artifact 已归档或类型不匹配。

## 4. 数据模型

### 4.1 新增 `canonical_graph_operations`

新增表记录人工 graph apply 操作。

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `operation_id` | TEXT PRIMARY KEY | 稳定 ID，格式 `cgo-{target}-{type}-{hash}` |
| `target_id` | TEXT NOT NULL | target 范围 |
| `operation_type` | TEXT NOT NULL | `merge` 或 `split` |
| `decision_artifact_id` | TEXT | 对应 research artifact，可为空以支持直接 apply |
| `primary_canonical_event_id` | TEXT NOT NULL | merge survivor 或 split source |
| `result_canonical_event_id` | TEXT | merge survivor 或 split 新事件 |
| `status` | TEXT NOT NULL | MVP 中为 `applied` |
| `changes_json` | TEXT NOT NULL | 结构化变更列表 |
| `warnings_json` | TEXT NOT NULL | 非阻塞警告列表 |
| `metadata_json` | TEXT NOT NULL | 操作 payload、actor、idempotency key |
| `created_by` | TEXT NOT NULL | 本地默认 `local-user` |
| `created_at` | TEXT NOT NULL | 创建时间 |

索引：

- `(target_id, operation_type, created_at)`
- `(target_id, decision_artifact_id)`
- `(target_id, primary_canonical_event_id, created_at)`

### 4.2 `canonical_events.metadata`

merge 应用后，被合并事件 metadata 增加：

```json
{
  "merged_into": "ce_italy_20260530_survivor",
  "merged_at": "2026-05-30T12:00:00Z",
  "merged_operation_id": "cgo-italy-merge-abcd",
  "previous_status": "needs_review"
}
```

survivor metadata 更新：

```json
{
  "mention_count": 5,
  "source_count": 3,
  "last_graph_operation_id": "cgo-italy-merge-abcd"
}
```

split 应用后，source 和新 canonical event metadata 都更新 mention/source count。

新 canonical event metadata 增加：

```json
{
  "created_by": "human_split",
  "split_from": "ce_italy_20260530_source",
  "split_operation_id": "cgo-italy-split-abcd",
  "mention_count": 2,
  "source_count": 2
}
```

### 4.3 `canonical_event_relations`

merge 创建关系：

```json
{
  "relation_type": "duplicate",
  "source_canonical_event_id": "ce_merged",
  "target_canonical_event_id": "ce_survivor",
  "confidence": 100,
  "metadata": {
    "created_by": "human_merge",
    "operation_id": "cgo-italy-merge-abcd",
    "decision_artifact_id": "ra_italy_merge_x"
  }
}
```

split 创建关系：

```json
{
  "relation_type": "split_from",
  "source_canonical_event_id": "ce_new",
  "target_canonical_event_id": "ce_source",
  "confidence": 100,
  "metadata": {
    "created_by": "human_split",
    "operation_id": "cgo-italy-split-abcd",
    "decision_artifact_id": "ra_italy_split_x"
  }
}
```

`split_from` 是人工维护关系类型，不改变已有自动 relation 类型。

## 5. Merge 语义

### 5.1 输入

merge apply payload：

```json
{
  "target_id": "italy",
  "decision_artifact_id": "ra_italy_merge_x",
  "survivor_canonical_event_id": "ce_italy_survivor",
  "merged_canonical_event_ids": ["ce_italy_duplicate_1", "ce_italy_duplicate_2"],
  "title_override": null,
  "summary_override": null,
  "dry_run": true
}
```

### 5.2 预检

必须检查：

- survivor 存在且属于 target。
- 每个 merged event 存在且属于 target。
- merged event 不包含 survivor。
- 每个 merged event 当前不是已 merged 到另一个 survivor；如果已 merged 到同一 survivor，视为幂等 no-op。
- decision artifact 存在时，类型必须是 `merge_decision`。
- decision artifact 的 candidate IDs 必须覆盖 payload 中的 merged IDs，允许 payload 只应用其中一部分。

### 5.3 应用

事务内执行：

1. 创建或读取幂等 `canonical_graph_operations`。
2. 把 merged events 的 mentions 移动到 survivor。
3. 把 merged events 标记为 `status = "merged"`。
4. 给每个 merged event 创建 `duplicate` relation 指向 survivor。
5. 重新计算 survivor 的 `mention_count`、`source_count`、`last_seen_at`。
6. 如果存在 decision artifact，把 artifact 更新为 `resolved` 并写入应用 metadata。
7. 返回 operation、changes、warnings 和受影响 event 摘要。

survivor 的标题和摘要默认不变。只有 payload 提供 `title_override` 或 `summary_override` 时才更新。

## 6. Split 语义

### 6.1 输入

split apply payload：

```json
{
  "target_id": "italy",
  "decision_artifact_id": "ra_italy_split_x",
  "source_canonical_event_id": "ce_italy_source",
  "affected_mention_ids": ["mention_1", "mention_2"],
  "new_title": "拆分出的事实事件",
  "new_summary": "人工拆分生成的新事件。",
  "dry_run": true
}
```

### 6.2 预检

必须检查：

- source canonical event 存在且属于 target。
- 每个 affected mention 存在、属于 target，并且当前属于 source canonical event。
- affected mentions 不是 source 的全部 mentions；第一版不允许生成无 mention 的 source event。
- decision artifact 存在时，类型必须是 `split_decision`。
- decision artifact 的 affected mentions 必须覆盖 payload 中的 affected mention IDs，允许 payload 只应用其中一部分。
- `new_title` 为空时，使用最高新闻价值 mention 标题作为新 event 标题。

### 6.3 应用

事务内执行：

1. 创建或读取幂等 `canonical_graph_operations`。
2. 创建新的 canonical event，`status = "needs_review"`，`confidence` 取 affected mentions 的保守聚合值。
3. 把 affected mentions 移动到新 canonical event。
4. 创建 `split_from` relation：新 event 指向 source event。
5. 重新计算 source 和新 event 的 `mention_count`、`source_count`、`last_seen_at`。
6. 如果存在 decision artifact，把 artifact 更新为 `resolved` 并写入应用 metadata。
7. 返回 operation、changes、warnings 和新 event 摘要。

新 canonical event ID 必须稳定生成，避免重复 apply 产生多个拆分事件。

## 7. API 设计

后台本地模式免登录，云端模式继续走写权限。

### 7.1 `POST /api/v1/research/graph/merge`

请求体为 merge payload。

响应：

```json
{
  "mode": "dry_run",
  "operation_id": "cgo-italy-merge-abcd",
  "target_id": "italy",
  "operation_type": "merge",
  "changes": [
    {"type": "move_mentions", "from": "ce_duplicate", "to": "ce_survivor", "count": 2},
    {"type": "mark_merged", "canonical_event_id": "ce_duplicate"},
    {"type": "create_relation", "relation_type": "duplicate"}
  ],
  "warnings": [],
  "events": {
    "survivor": {"canonical_event_id": "ce_survivor", "mention_count": 5},
    "merged": [{"canonical_event_id": "ce_duplicate", "status": "merged"}]
  }
}
```

`dry_run=true` 时不写数据库。`dry_run=false` 时写入 graph operation 和 canonical tables。

### 7.2 `POST /api/v1/research/graph/split`

请求体为 split payload。

响应：

```json
{
  "mode": "applied",
  "operation_id": "cgo-italy-split-abcd",
  "target_id": "italy",
  "operation_type": "split",
  "changes": [
    {"type": "create_canonical_event", "canonical_event_id": "ce_italy_split_abcd"},
    {"type": "move_mentions", "from": "ce_source", "to": "ce_italy_split_abcd", "count": 2},
    {"type": "create_relation", "relation_type": "split_from"}
  ],
  "warnings": [],
  "events": {
    "source": {"canonical_event_id": "ce_source", "mention_count": 3},
    "created": {"canonical_event_id": "ce_italy_split_abcd", "mention_count": 2}
  }
}
```

### 7.3 `GET /api/v1/research/graph/operations`

参数：

- `target_id` 必填。
- `operation_type` 可选：`merge / split`。
- `decision_artifact_id` 可选。
- `limit` 默认 50，最大 200。
- `offset` 默认 0。

返回 operation 列表，用于审计和 UI 展示。

## 8. Store 边界

`AsyncStore` 新增方法：

- `preview_canonical_merge(...)`
- `apply_canonical_merge(...)`
- `preview_canonical_split(...)`
- `apply_canonical_split(...)`
- `list_canonical_graph_operations(...)`
- `get_canonical_graph_operation(...)`

实现要求：

- preview 复用 apply 的校验和 change builder，但不写数据库。
- apply 使用 `BEGIN IMMEDIATE` 事务。
- apply 失败必须 rollback。
- 所有 JSON 读写继续使用现有 `_json_dumps` / `_row_with_metadata` 风格。
- target store 优先，global store fallback 逻辑沿用现有 `_store_for_target`。

## 9. 前端交互

目标工作台 `#/admin/targets/:targetId/review` 中：

- 研究记录里开放的 `merge_decision` 显示“预检合并”和“应用合并”。
- 研究记录里开放的 `split_decision` 显示“预检拆分”和“应用拆分”。
- 点击应用前先调用 dry-run，把变更摘要显示给用户确认。
- 用户确认后以 `dry_run=false` 提交。
- 应用成功后刷新研究详情和队列。
- 失败时显示后端返回的诊断消息，不进入永久 loading。

第一版不做复杂 diff 可视化；使用紧凑的变更摘要列表即可。

## 10. 测试计划

### 10.1 Store 测试

覆盖：

- merge dry-run 不改变 canonical tables。
- merge apply 会移动 mentions、标记 merged event、创建 duplicate relation。
- merge apply 重复提交幂等。
- merge 跨 target 拒绝。
- split dry-run 不改变 canonical tables。
- split apply 会创建新 event、移动 mentions、创建 split_from relation。
- split apply 重复提交幂等。
- split 移动全部 mentions 拒绝。
- decision artifact 应用后状态变为 `resolved`，metadata 包含 operation id。

### 10.2 API 测试

覆盖：

- `POST /api/v1/research/graph/merge` dry-run 和 apply。
- `POST /api/v1/research/graph/split` dry-run 和 apply。
- 无写权限时云端模式拒绝写接口。
- invalid artifact、invalid candidate、invalid mention 返回 404 或 422。
- `GET /api/v1/research/graph/operations` 能列出操作。

### 10.3 JS 测试

覆盖：

- review detail 对 open merge/split artifacts 渲染 apply controls。
- apply flow 先发送 `dry_run: true`，确认后发送 `dry_run: false`。
- merge payload 使用 `survivor_canonical_event_id` 和 artifact candidate IDs。
- split payload 使用 `source_canonical_event_id` 和 artifact affected mention IDs。
- 后端失败时调用现有错误提示，不移除页面内容。

### 10.4 浏览器验收

使用隔离临时数据启动本地服务：

- 打开 `#/admin/targets/italy/review`。
- 创建或加载一个 merge_decision，应用后确认重复 event 的 mentions 移到 survivor。
- 创建或加载一个 split_decision，应用后确认新 canonical event 出现在详情和队列。
- 桌面和 390px 下操作区无横向溢出。

## 11. 成功标准

本阶段完成后：

- 研究员可以从后台把人工 merge/split 决策真正应用到 canonical graph。
- canonical event detail、mentions、relations 和 research queue 反映应用后的事实层变化。
- 重复 apply 不制造重复 relation、新 event 或 operation。
- 没有 hard delete，所有变化都能从 operation log 和 artifact metadata 追溯。
- 后续 research brief、日报、企业告警、本地客户端同步可以读取同一套 canonical graph，而不是各自维护局部合并状态。
