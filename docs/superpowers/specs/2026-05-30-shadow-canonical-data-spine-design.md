# Shadow Canonical Data Spine 设计规格

> 日期：2026-05-30
> 状态：设计稿
> 上游方向文档：`docs/superpowers/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md`

## 1. 目标

第一阶段在不破坏现有 News Sentry 运行路径的前提下，建立未来全球事实池的影子 canonical 数据主干。

核心目标：

- 把现有 `NewsEvent`、Markdown 文件、SQLite `event_index` 投影为 canonical 数据对象。
- 让系统开始区分“现实世界事实”和“信源报道”。
- 为后续专业研究工作台、本地轻客户端、半中心化记者站网络和云端全球事实池提供统一数据契约。
- 用 backfill 与诊断证明当前数据能被 canonical 模型解释。

第一阶段不追求一次性替换现有 pipeline，也不引入云端数据库栈。

## 2. 已确认决策

- 第一阶段采用 **只读投影 + 显式 backfill**。
- 现有 collect/filter/judge/output 写路径保持不变。
- `NewsEvent`、Markdown、SQLite `event_index` 继续作为当前运行系统的事实来源。
- 新增 shadow canonical tables / projection layer。
- canonical 主干第一阶段只由投影器写入，不由 pipeline 双写。
- 页面和 API 可以逐步读取 canonical 投影，但不应在第一版强制全站切换。
- 等投影模型稳定后，再进入双写或 canonical-first 阶段。

## 3. 非目标

第一阶段不做：

- 不改写主 pipeline 的 collect/filter/judge/output 数据流。
- 不把 `canonical_event` 作为 pipeline 主写入对象。
- 不引入 Postgres、Elasticsearch/OpenSearch、对象存储、队列、图数据库或向量库。
- 不实现完整云端多租户架构。
- 不实现本地客户端同步协议。
- 不实现半中心化采集节点协议。
- 不自动删除或重写历史 Markdown 文件。
- 不用 AI 自动大规模重聚类历史数据。

这些能力进入后续独立 spec。

## 4. 设计原则

### 4.1 事实层与报道层分离

`canonical_event` 表示现实世界事实或进展。
`event_mention` 表示某个信源对该事实的一次报道、转载、社媒提及或政策公告。

一篇新闻报道不是事实本身。多篇报道可以归并到同一个 `canonical_event`。

### 4.2 保守归并

专业研究平台中，误合并比漏合并更危险。

第一阶段采用：

- 高置信：自动归并。
- 中置信：标记为需要审核。
- 低置信：创建新的 `canonical_event`。

第一版宁可 canonical event 稍多，也不能把不同事实静默合并。

### 4.3 可追溯

每个 canonical 对象都必须能追溯到原始 NewsEvent、source、URL、文件路径和投影批次。

任何归并、关系、分类、实体判断都必须保留来源：

- `rules`
- `deterministic`
- `semantic`
- `human`
- `migration`

### 4.4 幂等与可重跑

projection / backfill 必须可重复运行。

同一批输入重复投影时，不得重复生成 mention、relation、taxonomy assignment 或 canonical event。

### 4.5 不制造新数据孤岛

所有后续研究工作台、本地客户端、企业告警和公开门户能力，应逐步读取这套 canonical 投影，而不是各自创建新的局部事实表。

## 5. 核心对象模型

### 5.1 `canonical_event`

表示现实世界中的同一个新闻事实、事件或进展。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `canonical_event_id` | 稳定 ID，格式建议 `ce-{primary_geo}-{yyyymmdd}-{hash12}` |
| `primary_title` | 当前最佳标题，可来自最高质量 mention 或人工编辑 |
| `primary_summary` | 当前最佳摘要 |
| `primary_language` | 主要语言 |
| `primary_geo` | 主要国家/地区 |
| `event_time` | 事实发生或报道时间的最佳估计 |
| `first_seen_at` | 平台首次采集到相关 mention 的时间 |
| `last_seen_at` | 最近一次相关 mention 时间 |
| `source_count` | mention 覆盖的 source 数 |
| `mention_count` | mention 总数 |
| `news_value_score` | canonical 层综合新闻价值 |
| `china_relevance` | canonical 层中国相关度 |
| `confidence` | 当前 canonical 归并置信度 |
| `status` | `active / needs_review / merged / archived` |
| `created_by` | `projection / human / migration` |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

第一阶段 `primary_title` 和 `primary_summary` 可以从最高 `news_value_score` 的 mention 派生。

### 5.2 `event_mention`

表示某个信源对 canonical event 的一次报道或提及。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `mention_id` | 稳定 ID，第一阶段可复用 `NewsEvent.id` |
| `canonical_event_id` | 归属的 canonical event |
| `event_id` | 原 `NewsEvent.id` |
| `target_id` | 当前 target |
| `source_id` | source id |
| `source_ref` | source inventory ref |
| `url` | 原始 URL |
| `title_original` | 原文标题 |
| `title_translated` | canonical 翻译标题 |
| `content_digest` | 内容摘要或 hash |
| `language` | mention 语言 |
| `published_at` | 发布时间 |
| `collected_at` | 采集时间 |
| `file_path` | Markdown 或事件文件路径 |
| `stage` | 当前 pipeline stage / index stage |
| `news_value_score` | mention 层新闻价值 |
| `china_relevance` | mention 层中国相关度 |
| `source_credibility` | 来源可信度 |
| `provenance` | 投影来源、采集节点、任务等元信息 |
| `created_at` | 投影创建时间 |

唯一性约束：

- `mention_id` 唯一。
- `event_id` 唯一。
- 同一 `canonical_event_id + source_id + url` 应幂等。

### 5.3 `event_relation`

表示 canonical events 之间的关系。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `relation_id` | 稳定关系 ID |
| `source_canonical_event_id` | 源 canonical event |
| `target_canonical_event_id` | 目标 canonical event |
| `relation_type` | `duplicate / followup / related / contradicts / background` |
| `strength` | 0-1 或 0-100 的关系强度，第一版沿用现有 0-1 后再统一 |
| `confidence` | 关系判断置信度 |
| `evidence` | 支撑信号 JSON |
| `created_by` | `rules / semantic / human / migration` |
| `created_at` | 创建时间 |

第一阶段可以从现有 `event_links` 投影到 canonical 层，但需要避免重复关系爆炸。

### 5.4 `taxonomy_assignment`

表示 canonical event 或 mention 的分类结果。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `assignment_id` | 稳定 ID |
| `subject_type` | `canonical_event / event_mention` |
| `subject_id` | 被分类对象 ID |
| `taxonomy_type` | `l0_l3 / topic / risk / industry / geo` |
| `l0` | canonical L0 |
| `l1` | canonical L1 |
| `l2` | canonical L2 |
| `l3` | canonical L3 |
| `label` | topic/risk/industry 标签 |
| `confidence` | 0-100 |
| `assigned_by` | `rules / ai / human / migration` |
| `created_at` | 创建时间 |

第一阶段必须复用已有 taxonomy normalization，避免继续出现 legacy 分类漂移。

### 5.5 `entity_link`

表示 entity 与 canonical event 或 mention 的关系。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `entity_link_id` | 稳定 ID |
| `entity_id` | entity ID |
| `subject_type` | `canonical_event / event_mention` |
| `subject_id` | 被关联对象 ID |
| `role` | `subject / actor / location / organization / affected_party` |
| `relevance` | 0-100 |
| `evidence` | 支撑片段或来源 |
| `created_by` | `rules / ai / human / migration` |

实体对象本身应继续支持 canonical name、aliases、multilingual aliases、entity type 和 source evidence。

### 5.6 `research_artifact`

表示研究工作流产生的标注、审核、笔记和输出。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `artifact_id` | 稳定 ID |
| `artifact_type` | `annotation / merge_decision / split_decision / note / brief_section / review_state` |
| `subject_type` | `canonical_event / event_mention / event_relation / entity` |
| `subject_id` | 关联对象 |
| `content` | 文本内容或 JSON |
| `visibility` | `local_private / team / cloud_shared` |
| `created_by` | 用户或系统 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

第一阶段可以只定义 schema，不一定实现完整研究 artifact UI。

## 6. Projection / Backfill 设计

### 6.1 输入来源

第一阶段投影器读取：

- SQLite `event_index`
- Markdown frontmatter
- `raw/`
- `evaluated/`
- `drafts/`
- `archive/`
- `event_links`
- `entities`
- source inventory

优先输入顺序：

1. `event_index`
2. Markdown frontmatter 补充字段
3. source inventory 补充 source ref 与生命周期
4. event_links 生成 canonical relation
5. entities 生成 entity links

### 6.2 投影流程

每次投影生成一个 `projection_run_id`。

流程：

1. 读取候选 NewsEvent rows。
2. 规范化 URL、标题、source、language、taxonomy。
3. 为每条 NewsEvent 创建或更新 `event_mention`。
4. 根据确定性信号查找已有 `canonical_event`。
5. 根据语义/实体/时间信号计算候选归并分。
6. 高置信归并到已有 `canonical_event`。
7. 中置信创建 `needs_review` 诊断项。
8. 低置信创建新的 `canonical_event`。
9. 从 event_links 投影 canonical `event_relation`。
10. 从 topic/entity/classification 字段投影 taxonomy 与 entity links。
11. 写入 projection diagnostics。

### 6.3 归并信号

确定性信号：

- canonical URL 相同。
- feed GUID 相同。
- normalized title hash 相同。
- source + published_at + title hash 相同。

语义信号：

- 标题相似。
- 摘要相似。
- entity overlap。
- geo overlap。
- time proximity。
- taxonomy similarity。

人工信号：

- 人工确认合并。
- 人工拆分。
- 误合并反馈。

第一阶段可以先实现确定性信号与保守的实体/时间/分类评分，语义 embedding 进入后续阶段。

### 6.4 置信门槛

建议第一版门槛：

- `merge_confidence >= 90`：自动归并。
- `60 <= merge_confidence < 90`：进入 `needs_review`。
- `< 60`：创建新 canonical event。

这些数字可以作为默认值写入 runtime config，后续根据评估集调整。

### 6.5 幂等策略

必须保证：

- 同一 `event_id` 重复 backfill 只生成一个 `event_mention`。
- 同一 canonical URL 重复输入不会生成多个 canonical event。
- 同一 canonical relation 重复输入只保留一条关系。
- projection run 可重复执行并更新统计。

## 7. 诊断与质量指标

第一阶段必须提供 dry-run 诊断。

建议指标：

- 输入事件数。
- 生成 mention 数。
- 生成 canonical event 数。
- 自动归并数。
- 需要人工审核的候选归并数。
- 无法投影事件数。
- 缺失 URL 数。
- 缺失 source ref 数。
- legacy taxonomy 数。
- 非 canonical language 数。
- 重复 mention 数。
- 重复 canonical candidate 数。
- relation 投影数。
- relation 被跳过数。
- projection 耗时。

诊断必须支持：

- `dry_run=true`
- `target_id`
- `since`
- `limit`
- `include_archive`

## 8. API 与管理后台边界

第一阶段 API 只需要支持诊断和只读查询。

建议后续 API：

- `GET /api/v1/canonical/events`
- `GET /api/v1/canonical/events/{canonical_event_id}`
- `GET /api/v1/canonical/events/{canonical_event_id}/mentions`
- `GET /api/v1/canonical/events/{canonical_event_id}/relations`
- `GET /api/v1/canonical/diagnostics?target_id=...`
- `POST /api/v1/canonical/backfill`

第一版 `POST /api/v1/canonical/backfill` 必须默认 dry-run，只有显式 `apply=true` 才写入 shadow tables。

管理后台第一阶段只显示：

- 投影状态。
- 数据质量诊断。
- 需要审核的归并候选。
- legacy taxonomy / source / language 漂移。
- backfill dry-run 结果。

不在第一版实现复杂人工合并 UI。

## 9. 测试策略

### 9.1 单元测试

必须覆盖：

- 一个 NewsEvent 投影为一个 mention 和一个 canonical event。
- 两个相同 canonical URL 的 NewsEvent 归并到同一 canonical event。
- 两个不同 URL 但相同标题 hash 的 NewsEvent 在高置信下归并。
- 中置信候选不会自动归并，而是进入诊断。
- 重复 backfill 不增加 mention 数和 canonical event 数。
- legacy taxonomy 投影时被 canonical normalization 修正。
- event_links 投影为 canonical relation 且幂等。

### 9.2 集成测试

必须覆盖：

- 从现有 `event_index` 读取并生成 canonical tables。
- dry-run 不写入任何 canonical tables。
- apply=true 写入后可通过 API 查询。
- target_id 过滤有效。
- include_archive 默认 false。

### 9.3 数据诊断测试

必须覆盖：

- 缺失 source ref 被计数。
- 非 canonical taxonomy 被计数。
- 重复 mention 被计数。
- needs_review candidate 被计数。

## 10. 迁移阶段

### Stage 1：Schema + Projection Dry Run

建立 shadow tables 和 projection diagnostics。只跑 dry-run，不写入生产路径。

### Stage 2：Backfill Apply

允许显式 apply 写入 shadow tables，并支持 target 级 backfill。

### Stage 3：Read-Only API

提供 canonical read APIs，用于管理后台和未来研究工作台读取。

### Stage 4：Workbench Integration

研究工作台开始展示 canonical event 和 mentions，但原 feed 仍保留兼容视图。

### Stage 5：Dual Write Evaluation

投影稳定后，再评估是否让 pipeline 在 output/judge 后双写 canonical tables。

## 11. 风险

### 11.1 误合并

缓解：

- 第一版只自动合并高置信候选。
- 中置信进入审核。
- 所有合并记录保留 evidence。

### 11.2 数据膨胀

缓解：

- projection run 幂等。
- mention、relation、assignment 均有唯一约束。
- backfill 支持 limit 和 target_id。

### 11.3 读写路径混乱

缓解：

- 第一阶段不改 pipeline 主写路径。
- canonical 只作为投影层。
- API 命名明确使用 `/canonical/` 前缀。

### 11.4 过早云端化

缓解：

- 先在 SQLite 和当前数据协议中验证模型。
- 不引入云端数据栈，直到投影稳定。

## 12. 验收标准

第一阶段完成时，应满足：

- 可以对单个 target 运行 canonical dry-run。
- 可以对单个 target apply backfill。
- 重复 apply 不增加重复数据。
- 可以查询 canonical event 列表、详情、mentions、relations。
- 可以看到 projection diagnostics。
- 至少 Italy target 的历史数据可被投影出稳定 canonical 视图。
- 不影响现有 public feed、admin target、pipeline run。
- 相关测试覆盖幂等、归并、诊断、API 查询。

## 13. 后续计划入口

本 spec 经 review 后，应进入实现计划：

`docs/superpowers/plans/YYYY-MM-DD-shadow-canonical-data-spine.md`

实现计划应按以下任务拆分：

1. shadow schema 与 AsyncStore 方法。
2. projection service dry-run。
3. backfill apply 与幂等约束。
4. canonical read APIs。
5. diagnostics API 与管理后台只读入口。
6. 目标数据验证与回归测试。
