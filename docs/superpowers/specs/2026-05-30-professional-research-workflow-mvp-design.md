# Professional Research Workflow MVP 设计规格

> 日期：2026-05-30
> 状态：设计稿
> 上游方向文档：`docs/superpowers/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md`
> 前置阶段：`docs/superpowers/specs/2026-05-30-shadow-canonical-data-spine-design.md`

## 1. 目标

本阶段进入 **Professional Research Workflow MVP**：让研究员、编辑和分析师围绕 shadow canonical event 完成真实、可追溯、可复核的研究工作。

核心目标：

- 把 canonical event 从“可查询事实投影”推进到“可操作研究对象”。
- 建立人工复核、证据查看、标注、合并/拆分决策和简报笔记的最小闭环。
- 让研究动作以 `research_artifact` 形式独立保存，避免污染 canonical fact layer。
- 为后续云端研究工作台、本地轻客户端、企业告警和简报输出提供统一工作流契约。

一句话边界：

**事实对象由 canonical tables 承载，研究动作由 research artifacts 承载；MVP 只记录人工判断和工作流状态，不自动改写事实归并结果。**

## 2. 非目标

本阶段不做：

- 不把公开新闻门户切换为 canonical-first。
- 不实现完整团队权限、用户系统、多租户审计。
- 不自动执行 destructive merge/split，不删除 canonical events 或 mentions。
- 不引入云端数据库、搜索引擎、向量库、队列或对象存储。
- 不实现完整简报生成器、日报发布流或企业报告模板。
- 不实现本地客户端同步协议。
- 不改变 collect/filter/judge/output 主写入路径。

这些能力进入后续独立 spec。

## 3. 已确认设计决策

- 复用第一阶段已建立的 canonical event / mention / relation 数据。
- 管理后台的 target 工作台仍是第一入口。
- `#/admin/targets/:targetId/review` 从旧事件列表升级为 canonical research review queue。
- `#/admin/targets/:targetId/canonical` 继续负责投影诊断和显式 backfill。
- 研究工作流的所有人工动作都写入 `research_artifacts`。
- 合并、拆分在 MVP 中只保存为 `merge_decision` / `split_decision` artifact，不立即改写 canonical tables。
- 本地模式默认 `created_by = "local-user"`，不要求登录。

## 4. 用户工作流

### 4.1 进入目标研究队列

研究员从 `#/admin/targets/:targetId/review` 进入某个 target 的研究队列。

队列优先展示：

- canonical confidence 较低的事件。
- `status = "needs_review"` 的事件。
- 有合并/拆分建议但未关闭的事件。
- 最近新增、mention 数较多或新闻价值较高的事件。

每个队列项应显示：

- 标题、摘要、事件时间。
- 置信度、状态、mention 数、source 数、新闻价值。
- 最新 review state。
- 是否存在开放的 merge/split 决策。

### 4.2 查看证据

打开队列项后，研究员能看到：

- canonical event 主信息。
- mentions 列表：source、URL、标题、发布时间、语言、分值。
- relations 列表：related/followup/duplicate 等关系。
- 当前已有 artifacts：标注、review state、merge/split 决策、笔记。

证据列表必须保持可点击来源链接。无 URL 的 mention 仍应展示 source 和标题，不应导致页面卡死。

### 4.3 人工复核

研究员可以执行四类动作：

1. **确认事件**
   - 创建或更新 `review_state` artifact。
   - `metadata.status = "resolved"`。
   - `metadata.decision = "confirmed"`。

2. **标记需要合并**
   - 创建 `merge_decision` artifact。
   - 记录候选 canonical event IDs、理由和置信度。
   - 不自动合并事实对象。

3. **标记需要拆分**
   - 创建 `split_decision` artifact。
   - 记录拆分原因、受影响 mention IDs 和建议拆分方向。
   - 不自动拆分事实对象。

4. **添加研究标注**
   - 创建 `annotation` 或 `note` artifact。
   - 可用于后续简报、风险摘要和研究包。

### 4.4 队列状态更新

队列状态由 canonical event 与 artifacts 共同决定。

- 没有 artifact 时，按 canonical event status/confidence 派生。
- 最新 `review_state` 为 `resolved/confirmed` 时，队列默认隐藏该事件。
- 最新 `review_state` 为 `open/needs_review`，或存在开放的 merge/split 决策时，继续展示。
- 查询参数可切换 `status=open|resolved|all`。

## 5. 数据模型

### 5.1 `research_artifacts`

第一阶段已经创建基础表。本阶段需要把它补齐为可用工作流表。

新增或补齐字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `artifact_id` | TEXT PRIMARY KEY | 稳定 ID，格式 `ra-{target}-{type}-{hash}` |
| `target_id` | TEXT NOT NULL | target 范围 |
| `artifact_type` | TEXT NOT NULL | `review_state / annotation / note / merge_decision / split_decision` |
| `title` | TEXT NOT NULL | artifact 短标题 |
| `body` | TEXT NOT NULL | 研究内容、理由或备注 |
| `subject_type` | TEXT NOT NULL | MVP 固定支持 `canonical_event` |
| `subject_id` | TEXT NOT NULL | canonical event ID |
| `canonical_event_ids_json` | TEXT NOT NULL | 相关 canonical event ID 列表 |
| `status` | TEXT NOT NULL | `open / resolved / archived` |
| `visibility` | TEXT NOT NULL | MVP 默认 `local_private` |
| `created_by` | TEXT NOT NULL | 本地默认 `local-user` |
| `metadata_json` | TEXT NOT NULL | decision、candidate IDs、mention IDs、confidence 等 |
| `created_at` | TEXT NOT NULL | 创建时间 |
| `updated_at` | TEXT NOT NULL | 更新时间 |

索引：

- `(target_id, subject_type, subject_id, artifact_type, updated_at)`
- `(target_id, artifact_type, status, updated_at)`

### 5.2 Artifact 类型契约

#### `review_state`

用于表达复核结论。

`metadata_json` 必须包含：

```json
{
  "decision": "confirmed",
  "reason": "多信源一致，标题与时间窗口匹配"
}
```

允许的 `decision`：

- `confirmed`
- `needs_merge`
- `needs_split`
- `needs_more_evidence`
- `not_relevant`

#### `annotation`

用于人工标注事实背景、重要性或风险点。

`metadata_json` 可包含：

```json
{
  "tags": ["policy", "energy"],
  "quote_mention_ids": ["event-001"]
}
```

#### `note`

用于研究员私人或团队笔记。

MVP 中默认 `visibility = "local_private"`。

#### `merge_decision`

用于记录人工认为多个 canonical events 应合并。

`metadata_json` 必须包含：

```json
{
  "candidate_canonical_event_ids": ["ce_italy_001", "ce_italy_002"],
  "decision": "proposed",
  "confidence": 80,
  "reason": "同一 source/time/title hash 指向同一事实"
}
```

MVP 不实际合并，只记录待后续处理的人工证据。

#### `split_decision`

用于记录人工认为一个 canonical event 误合并了多条事实。

`metadata_json` 必须包含：

```json
{
  "affected_mention_ids": ["event-001", "event-002"],
  "decision": "proposed",
  "reason": "两个 mentions 指向不同主体，发布时间相近但事件不同"
}
```

MVP 不实际拆分，只记录待后续处理的人工证据。

## 6. API 设计

所有研究工作流写接口属于后台能力，本地模式免登录，云端模式继续走后台鉴权。

### 6.1 `GET /api/v1/research/queue`

参数：

- `target_id` 必填。
- `status` 可选：`open / resolved / all`，默认 `open`。
- `limit` 默认 50，最大 200。
- `offset` 默认 0。

返回：

```json
{
  "target_id": "italy",
  "status": "open",
  "items": [
    {
      "canonical_event_id": "ce_italy_20260530_abcd",
      "title": "Example",
      "summary": "Example summary",
      "event_time": "2026-05-30T10:00:00Z",
      "canonical_status": "needs_review",
      "confidence": 65,
      "mention_count": 3,
      "source_count": 2,
      "news_value_score": 80,
      "latest_review": {
        "artifact_id": "ra_italy_review_x",
        "status": "open",
        "decision": "needs_more_evidence"
      },
      "open_decisions": {
        "merge": 1,
        "split": 0
      }
    }
  ],
  "total": 1
}
```

### 6.2 `GET /api/v1/research/events/{canonical_event_id}`

参数：

- `target_id` 必填。

返回 canonical event、mentions、relations、artifacts 的组合视图。

### 6.3 `GET /api/v1/research/artifacts`

参数：

- `target_id` 必填。
- `subject_type` 默认 `canonical_event`。
- `subject_id` 可选。
- `artifact_type` 可选。
- `status` 可选。
- `limit` 默认 50，最大 200。

返回 artifacts 列表。

### 6.4 `POST /api/v1/research/artifacts`

请求：

```json
{
  "target_id": "italy",
  "artifact_type": "review_state",
  "title": "人工确认",
  "body": "多信源一致，确认是同一事实。",
  "subject_type": "canonical_event",
  "subject_id": "ce_italy_20260530_abcd",
  "status": "resolved",
  "metadata": {
    "decision": "confirmed",
    "reason": "多信源一致"
  }
}
```

行为：

- 校验 `target_id + subject_id` 指向同一个 canonical event。
- 校验 `artifact_type/status/decision` 枚举。
- 写入 `research_artifacts`。
- 返回创建后的 artifact。

### 6.5 `PATCH /api/v1/research/artifacts/{artifact_id}`

MVP 只允许更新：

- `title`
- `body`
- `status`
- `metadata`

不允许跨 target 或跨 subject 移动 artifact。

## 7. 前端设计

### 7.1 Target 工作台 Review 页

`#/admin/targets/:targetId/review` 改为专业研究复核页。

布局采用当前站点统一设计语言：

- 左侧：紧凑队列列表。
- 右侧：当前事件详情、证据、人工动作。
- 移动端：队列与详情纵向堆叠。

首屏回答三个问题：

1. 还有哪些事实需要人工看？
2. 证据来自哪些信源？
3. 下一步能做什么？

### 7.2 队列列表

队列项不做营销式卡片，采用紧凑信息条：

- title 一行优先，必要时两行。
- confidence/status/source count 使用小型元信息。
- 高风险状态用现有红色强调。
- resolved 事件默认不显示。

### 7.3 详情面板

详情面板包含：

- canonical event 摘要。
- evidence mentions。
- relations。
- artifacts timeline。
- 操作区：确认、需要合并、需要拆分、添加标注。

操作区应避免长期空转。API 失败时显示明确错误和重试按钮。

### 7.4 与旧 Review/Feedback 的关系

- `#/admin/review/*` 继续保留为兼容入口。
- Target 工作台中的 `review` 逐步成为 canonical-first 研究工作流。
- 旧事件审核列表不再作为专业研究主路径。

## 8. 错误处理与安全边界

- 任何写入都必须校验 target scope。
- artifact 写入失败不能影响 canonical event、mentions 或 pipeline 数据。
- merge/split 只记录人工决策，不执行事实改写。
- API 不返回永久加载态；前端必须显示错误、重试和返回 canonical 诊断入口。
- 空 canonical 数据时，引导用户到 `事实投影` tab 执行显式 backfill。

## 9. 测试策略

### 9.1 Store 单元测试

覆盖：

- research artifact 表结构和迁移。
- upsert/list/get/update。
- 按 target、subject、type、status 过滤。
- latest review state 派生。
- open merge/split 决策计数。

### 9.2 API 单元测试

覆盖：

- queue 只返回当前 target 范围数据。
- resolved review state 默认从 open queue 隐藏。
- event detail 返回 event + mentions + relations + artifacts。
- artifact create 校验 target scope。
- artifact create 拒绝非法 type/status/decision。
- artifact patch 不允许跨 target/subject。

### 9.3 JS 测试

覆盖：

- `#/admin/targets/:targetId/review` 路由仍解析。
- review 页请求 `/api/v1/research/queue`。
- 详情请求 `/api/v1/research/events/:id`。
- 创建 review_state 使用 POST `/api/v1/research/artifacts`。

### 9.4 浏览器验收

覆盖：

- 桌面和 390px 下 review 页无横向溢出。
- 空 canonical 数据时有可执行下一步。
- 队列、详情、证据和 artifact timeline 不出现永久“正在加载”。
- 点击确认后队列项从 open 列表消失。

## 10. 验收标准

本阶段完成后，应能证明：

- 研究员可以从 target 工作台进入 canonical 复核队列。
- 可以打开一个 canonical event，查看 mentions/relations 证据。
- 可以确认事件、添加标注、记录合并/拆分建议。
- 所有人工动作都保存为 research artifacts。
- 重复刷新页面后 artifact 状态仍然存在。
- 不会因为人工动作改写或破坏 canonical 投影事实。
- 现有 canonical backfill、公开 feed、运行 pipeline 不受影响。

## 11. 后续阶段

MVP 稳定后再进入：

- 人工 merge/split 真正应用到 canonical graph。
- 简报/日报生成器。
- 研究包导出。
- 本地客户端 artifact 同步。
- 云端团队权限、审计和协作。
- 企业告警与客户视图。
