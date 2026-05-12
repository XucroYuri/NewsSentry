# Phase 1 — Contract Stabilization

> 详细 SPEC: 本文档
> 路线图: [docs/development-plan.md §Phase-1](../development-plan.md)
> 横切组件矩阵: [docs/spec/README.md](README.md)
> **状态: ✅ Phase 1 已完成（DONE）**

---

## 1. 目标与出口标准

**目标：** 定稿所有核心契约、消除跨文档口径漂移、关闭已答 Open Questions，确保后续各 Phase 的实现者不再需要在 ID 格式、字段别名、分值量纲、pipeline_stage 形式、sandbox 边界等基础问题上做二次决策。

**出口标准（已验证完成）：**
- [x] 所有六类口径漂移已在 `contracts-canonical.md` 中定稿并给出唯一规范
- [x] ADR-0001 至 ADR-0016 全部创建并处于 Accepted 状态
- [x] `NewsEvent` 契约锁定，schema 可通过 JSON Schema 2020-12 校验
- [x] 双语 SOP 文档完整，覆盖翻译时机、三层粒度、术语策略、合规免责
- [x] 实现者可直接进入 Phase 2，无需再解决任何基础口径问题

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | 创建 `docs/contracts-canonical.md`（口径基准） | 任何 Python 代码实现 |
| **IN** | 创建 ADR-0001 至 ADR-0016 | ToolManifest / AIProvider 规格新增内容 |
| **IN** | 精修 `AGENTS.md`、`architecture-overview.md`、`newsevent-schema.md` | 数据采集或研判 Skill 实现 |
| **IN** | 创建 `docs/it-zh-bilingual-sop.md` 和 `docs/it-zh-glossary.md` | 测试夹具或集成测试 |
| **IN** | 为超 v1 范围文档加 banner、为采集子 Skill 规格头部加阶段标签 | 第二国家配置 |
| **IN** | 创建本开发计划文档（`docs/development-plan.md`） | 前端或可视化组件 |

---

## 3. 横切组件章节

Phase 1 不引入可运行组件，但锁定了所有后续组件必须遵守的数据契约。

### 3.1 NewsEvent 契约

- **接口**（逻辑结构，非 Python 实现）:
  ```
  NewsEvent:
    id: str                          # 格式: ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
    pipeline_stage: Literal["collected", "filtered", "judged", "outputted"]
    title: str
    title_translated: str | None     # canonical 译文，仅 judge 阶段后填充
    content: str | None
    content_translated: str | None   # canonical 译文，仅 judge 阶段后填充
    language: str                    # BCP-47，如 "it"、"en"
    source_id: str
    source_url: str
    published_at: datetime
    collected_at: datetime
    run_id: str                      # 本次 bounded run 的唯一 ID
    metadata: NewsEventMetadata
    processing_history: list[ProcessRecord]
    judge_result: JudgeResult | None
    output_result: OutputResult | None
    acquisition: AcquisitionInfo
  ```

- **数据流**: 跨 Phase 的主要数据载体，在文件目录间流转
  ```
  raw/ (collected) → evaluated/ (filtered) → drafts/ (outputted) → reviewed/ → published/
                                           ↘ archive/ (rejected)
  ```

- **错误处理**: `pipeline_stage` 只能单向前进；回退路径通过写入 `archive/` 处理，不覆盖原 `raw/` 文件

### 3.2 PipelineContext 契约

- **接口**（逻辑结构）:
  ```
  PipelineContext:
    run_id: str
    target_id: str
    stage: Literal["collect", "filter", "judge", "output"]
    sandbox_policy: SandboxPolicy
    config_path: str
    started_at: datetime
    events_collected: int
    events_filtered: int
    events_judged: int
    budget_remaining: BudgetState
  ```

- **数据流**: 在一次 bounded run 中贯穿各 Skill，不序列化到文件（仅内存对象）

### 3.3 分值量纲约定（ADR-0001 §4）

| 字段 | 量纲 | 说明 |
|------|------|------|
| `news_value_score` | 0–100 整数 | 综合新闻价值评分 |
| `china_relevance` | 0–100 整数 | 涉华相关度 |
| `sentiment_score` | -1.0 到 1.0 浮点数 | 情感极性（例外字段） |
| `ValueDimension.weight` | 百分比权重（0–100） | 不是分数，是权重 |
| `source_credibility` | 0–100 整数 | 信源可信度 |

---

## 4. 配置契约

Phase 1 锁定了配置规范，但具体配置文件由后续 Phase 实现。

| 配置文件（规划） | 所属 Phase | 说明 |
|----------------|-----------|------|
| `config/italy/target.yaml` | Phase 3 | 意大利 TargetConfig |
| `config/italy/sources/*.yaml` | Phase 3 | 各信源 SourceChannel 配置 |
| `config/filters/italy-rules.yaml` | Phase 3 | FilterRules |
| `config/sandbox/default.yaml` | Phase 3 | 最小 SandboxPolicy |
| `config/toolmanifest/opencli-baseline.yaml` | Phase 4 | ADR-0011 12 条骨架 |
| `config/providers/routing.yaml` | Phase 5 | AIProvider route_id 表 |

**配置合并优先级（ADR-0015）：**
```
target config → source config → sandbox policy
（高优先级字段覆盖低优先级字段，sandbox policy 不可被 target/source 降权）
```

---

## 5. 测试策略

Phase 1 为纯文档阶段，无可运行代码，测试策略为文档一致性检查。

| 测试类型 | 目标 | 工具 |
|---------|------|------|
| 文档一致性 | `contracts-canonical.md` 字段与 `newsevent-schema.md` JSON 示例一致 | 人工比对 + jq |
| Schema 格式 | `schemas/` 下所有 JSON Schema 文件格式合法 | `jsonschema` CLI |
| ADR 完整性 | ADR-0001 至 ADR-0016 全部存在，状态为 Accepted | `ls docs/adr/` 计数 |
| 口径覆盖 | `contracts-canonical.md` 六类漂移项全部有明确规范 | 人工审查 |

---

## 6. 验收清单

### 契约文档
- [x] `contracts-canonical.md` 覆盖 §1 命名 / §2 pipeline_stage / §3 NewsEvent.id / §4 分值量纲 / §5 目录协议 / §6 SandboxPolicy / §7 修正记录表
- [x] `newsevent-schema.md §待讨论` 第 4、5 条标注 RESOLVED
- [x] `SandboxPolicy YAML` 中 `write_roots` 含 `reviewed/` 和 `published/`

### ADR 系列
- [x] ADR-0001：`pipeline_stage` 枚举 + `NewsEvent.id` 格式 + 分值量纲
- [x] ADR-0002：`output_channels` → `output_result.destinations[].target`
- [x] ADR-0003：SandboxPolicy `write_roots` 补全、`error.type` 枚举
- [x] ADR-0004：双语翻译时机（collect 机译 `title_pre`，judge canonical `title_translated`）
- [x] ADR-0005：`pipeline_stage` 与 `workflow_state` 正交分离
- [x] ADR-0006：CLI 入口暂缓决策（Phase 3 前解决）
- [x] ADR-0007：PRD Open Questions 批量关闭
- [x] ADR-0008：外部项目只 install 不 vendor
- [x] ADR-0009：四层新闻分类框架（L0–L3）
- [x] ADR-0010：永不做专用前端
- [x] ADR-0011：12 条 OpenCLI ToolManifest 骨架
- [x] ADR-0012：Python 3.11+ 实现语言
- [x] ADR-0013：src layout，core/skills/adapters 三层结构
- [x] ADR-0014：JSON Schema 2020-12 合约验证
- [x] ADR-0015：配置合并优先级
- [x] ADR-0016：CLI 入口 `python -m news_sentry.cli run --target <id> --stage <stage> --profile <profile_id>`

### 双语 SOP
- [x] `it-zh-bilingual-sop.md` 覆盖翻译时机、三层粒度、术语策略、草稿模板、合规免责
- [x] `it-zh-glossary.md` 含七张种子表（政治/人物/机构/地名/经济/法律/体育）

### 超范围文档标记
- [x] `kol-tracking.md`、`information-acquisition-chains.md` 含超 v1 范围 banner
- [x] 三类采集子 Skill 规格头部均有阶段标签（Phase 3 / Phase 4 / Phase 6）

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| 后续文档被直接修改而不走 ADR，导致口径再次漂移 | 中 | 高 | 任何争议查 `contracts-canonical.md §7`，修改必须新建 ADR |
| `schemas/` JSON Schema 文件与文档描述出现不一致 | 低 | 中 | `jsonschema` 验证脚本作为 pre-commit hook |
| 双语 SOP 翻译原则被实现者忽视 | 中 | 中 | Phase 3 草稿生成 Skill 必须引用 `it-zh-bilingual-sop.md §5` 模板 |

---

## 附：Phase 1 完成的主要产出物

```
docs/
├── contracts-canonical.md          # 口径基准（唯一权威来源）
├── development-plan.md             # 七阶段路线图
├── it-zh-bilingual-sop.md          # 双语翻译标准操作程序
├── it-zh-glossary.md               # 双语术语表（七张种子表）
├── architecture-overview.md        # 精修版
├── newsevent-schema.md             # 精修版，RESOLVED 标注
├── integration-protocol.md         # 精修版
├── external-integration-strategy.md
├── reference-projects-insights.md
├── news-classification-framework.md
├── datasets-catalog-italy.md
└── adr/
    ├── README.md                   # ADR 索引
    ├── 0001-canonical-contracts.md
    ├── 0002-output-result-field-alignment.md
    ├── 0003-sandbox-write-roots-and-error-enum.md
    ├── 0004-bilingual-translation-timing.md
    ├── 0005-pipeline-stage-vs-workflow-state.md
    ├── 0006-cli-entry-deferred.md
    ├── 0007-prd-open-questions-resolved.md
    ├── 0008-external-deps-install-not-vendor.md
    ├── 0009-four-layer-classification-framework.md
    ├── 0010-no-dedicated-frontend.md
    ├── 0011-opencli-baseline-toolmanifest.md
    ├── 0012-python-implementation-language.md
    ├── 0013-src-layout-package-structure.md
    ├── 0014-json-schema-contract-validation.md
    ├── 0015-config-merge-priority.md
    └── 0016-cli-entry-point.md

schemas/
├── news-event.schema.json          # NewsEvent JSON Schema 2020-12
├── pipeline-context.schema.json
├── skill-manifest.schema.json
├── tool-manifest.schema.json
├── sandbox-policy.schema.json
├── provider-config.schema.json
├── filter-rules.schema.json
├── target-config.schema.json
├── run-log.schema.json
├── source-health.schema.json
├── judge-result.schema.json
└── output-result.schema.json
```
