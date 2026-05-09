# Integration Protocol 设计规范

> news-sentry 系统中所有 Skill/CLI/Agent 之间的协作协议
> 状态：设计讨论稿 | 2026-05-09
> 字段口径基准：[`docs/contracts-canonical.md`](./contracts-canonical.md) — 遇到字段名、分值量纲、id 格式歧义时以该文件为准

---

## 1. 设计目标

Integration Protocol 解决的核心问题：**让形态各异的外部能力（Skill、CLI、API、Agent）能够无缝接入 news-sentry 的 pipeline，并且彼此之间能够可靠地传递数据。**

三个关键原则：

1. **松耦合** — Skill 不需要知道上下游是谁，只遵循 Protocol 即可接入
2. **自描述** — 每个 Skill 通过 Manifest 声明自己的能力、输入输出约束，编排器据此自动组装 pipeline
3. **可演进** — Protocol 版本化，新旧 Skill 可以共存，不强制同步升级

---

## 2. 三层协议结构

```
┌─────────────────────────────────────────┐
│  SkillManifest  — 能力声明与发现层        │  "我能做什么"
├─────────────────────────────────────────┤
│  NewsEvent      — 数据交换层             │  "我产出什么"
├─────────────────────────────────────────┤
│  PipelineContext — 流程控制与上下文层      │  "我在什么环境中运行"
└─────────────────────────────────────────┘
```

---

## 3. SkillManifest — 能力声明层

每个注册到 Skill Registry 的能力模块必须提供 Manifest，编排器据此：

- 判断该 Skill 应插入 pipeline 的哪个环节
- 评估是否满足当前配置的输入约束
- 在多个候选 Skill 中选择最合适的一个

### 3.1 Manifest Schema

```yaml
# SkillManifest v1
manifest_version: "1"

# === 身份 ===
skill_id: "news-value-judge"          # 全局唯一ID
skill_type: "purpose-built"           # direct | adapted | purpose-built
source:                               # 溯源信息
  origin_skill_id: null               # 改造来源（adapted类型填写）
  origin_repo: null                   # 来源仓库/路径
  adaptation_notes: null              # 改造点描述
  developer: "news-sentry-team"       # 开发者
  version: "0.1.0"

# === 能力声明 ===
pipeline_stage: "judge"               # collect | filter | judge | output
capabilities:                         # 该skill提供的具体能力
  - "news_value_scoring"              # 新闻价值评分
  - "breaking_news_detection"         # 突发新闻识别
  - "china_relevance_scoring"         # 涉华相关性判断

# === 输入约束 ===
input:
  required:                           # 必须提供的输入
    - news_events: "NewsEvent[]"       # NewsEvent数组
  optional:                           # 可选输入，有则增强效果
    - target_entities: "string[]"      # 关注实体列表
    - relevance_rules: "RuleSet"       # 自定义规则集
  format: "json"                      # json | yaml | markdown

# === 输出承诺 ===
output:
  type: "NewsEvent[]"                 # 产出类型
  guarantees:                         # 输出保证
    - "every event has news_value_score" # 每个事件都有新闻价值评分
    - "breaking events flagged"        # 突发事件被标记
  side_effects:                       # 附带产出
    - "log: judgment_log.md"          # 研判日志

# === 运行约束 ===
runtime:
  llm_required: true                  # 是否需要LLM调用
  llm_model_preference: "claude-sonnet" # 倾向使用的模型
  estimated_duration: "2-5min"        # 预估耗时
  max_events_per_run: 50             # 单次最大处理量
  cost_estimate: "low"                # low | medium | high（LLM调用成本）

# === 降级策略 ===
fallback:
  available: true                     # 是否有内置降级实现
  description: "LLM直接研判，无规则引擎加速"
```

### 3.2 Manifest 的使用场景

| 场景 | 用法 |
|------|------|
| Skill 注册时 | Registry 存储 Manifest，供编排器查询 |
| Pipeline 组装时 | 编排器按 `pipeline_stage` 匹配 Skill 到对应环节 |
| 能力缺口发现时 | 查 Registry 中是否有某 `capabilities` 的 Skill，若无则触发 find-skill |
| 多候选选择时 | 按 `runtime.cost_estimate`、`max_events_per_run` 等指标选最优 |
| 降级决策时 | `fallback.available=true` 的 Skill 在失败时自动降级 |

---

## 4. PipelineContext — 流程控制层

PipelineContext 是一次心跳周期内的全局上下文，贯穿整个 pipeline 四环节。每个 Skill 可以读取上下文信息来调整自己的行为，也可以写入上下文供下游使用。

### 4.1 PipelineContext Schema

```yaml
# PipelineContext v1
context_version: "1"

# === 本次执行身份 ===
run_id: "run-20260509-1407-it"        # 唯一运行ID（日期+时间+目标）
target_config:                         # 当前目标配置
  target_id: "italy"                    # 监控目标ID
  target_region: "Italy"               # 监控目标地区
  target_country: "IT"                  # 目标国家，ISO 3166-1 alpha-2
  focus_areas:                         # 关注领域
    - "breaking_news"
    - "international_orgs"
    - "china_related_opinion"
  language_scope: ["it", "en", "zh"]   # 语言范围
  priority_threshold: 70              # 价值评分≥70才推送（统一0-100量纲）

# === Pipeline 状态 ===
pipeline_state:
  current_stage: "judge"               # 当前环节
  stages_completed: ["collect", "filter"]
  started_at: "2026-05-09T14:07:00Z"
  heartbeat_interval: "1h"             # 心跳间隔

# === 上游传递信息 ===
upstream:
  collect_stats:                       # 采集环节统计
    sources_attempted: 8
    sources_successful: 6
    events_collected: 23
    collection_errors:
      - source: "ansa_politics_rss"
        error: "timeout"
  filter_stats:                        # 过滤环节统计
    events_input: 23
    events_output: 12                  # 过滤后进入研判的事件数
    filter_rules_applied: 5
    events_rejected_reasons:
      - "duplicate: 4"
      - "out_of_scope: 5"
      - "too_old: 2"

# === 动态配置 ===
dynamic_config:
  urgency_mode: false                  # 紧急模式（突发事件触发时开启）
  urgency_source: null                 # 触发紧急模式的 NewsEvent.id
  llm_budget_remaining: 100           # 本次心跳剩余LLM调用预算

# === 跨周期记忆 ===
memory:
  last_run_id: "run-20260509-1307-it"  # 上次运行ID
  known_item_ids:                      # 已知 NewsEvent.id（去重用）
    - "ansa-20260509-001"
    - "repubblica-20260509-015"
    ...
  active_tracked_entities:             # 当前追踪的实体
    - "Meloni"
    - "FAO"
    - "中国驻意使馆"
  pending_alerts: []                   # 上次未完成的提醒
```

### 4.2 Context 生命周期

```
heartbeat触发
  → 创建新 PipelineContext（继承上次memory）
  → collect环节读取context，写入upstream.collect_stats
  → filter环节读取context+collect产出，写入upstream.filter_stats
  → judge环节读取context+filter产出，写入judgment结果
  → output环节读取全部context，输出最终产物
  → 保存memory部分到持久存储，供下次心跳继承
```

### 4.3 Context 的关键设计点

1. **memory 跨周期继承** — `known_item_ids` 和 `active_tracked_entities` 从上次 context 继承，这是去重和连续追踪的基础
2. **urgency_mode 动态切换** — 当 judge 环节发现 breaking news 时，可以写入 `urgency_mode=true`，触发 output 环节立即推送而非等待下次心跳
3. **llm_budget_remaining** — 控制单次心跳的LLM调用成本，budget耗尽时降级到规则引擎
4. **upstream 累积** — 每环节完成后写入自己的统计信息，下游可以据此调整策略（比如 filter 拒绝太多时 judge 可以放宽标准）

---

## 5. 数据流流转规则

### 5.1 环节间数据传递

```
collect → filter → judge → output

每个环节：
  输入 = 上游环节的 NewsEvent[] 输出 + PipelineContext
  输出 = 处理后的 NewsEvent[]（同一结构，字段渐进丰富）
  副作用 = 写入 PipelineContext.upstream 的自己的统计信息
```

**关键约束：每个环节只能丰富 NewsEvent，不能删除字段。** 如果某个环节不关心某个字段，它应当原样传递而非丢弃。

### 5.2 字段渐进丰富过程

以一条意大利涉华新闻为例，展示它在 pipeline 中如何被逐步丰富：

| 阶段 | 新增/修改字段 | 示例值 |
|------|-------------|--------|
| **collect产出** | `id`, `title_original`, `source_url`, `source_name`, `published_at`, `content_original`, `language`, `target_id`, `source_country`, `involved_countries` | `ne-italy-ansa-20260509-a1b2c3d4`（格式：`ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`，见 contracts-canonical.md §3）, "Meloni: cooperation with China..." |
| **filter补充** | `filter_result`, `relevance_tags`, `matched_rules`, `is_urgent`, `source_credibility` | `passed=true`, `["china_related"]`, `false`, `85` |
| **judge补充** | `judge_result`, `news_value_score`, `breaking_news_level`, `china_relevance`, `sentiment_score`, `entities`, `title_translated` | `82`, `significant`, `90`, `15`, ["Meloni","China"], "梅洛尼强调中意合作..." |
| **output补充** | `output_result`（含 `destinations[].target`、`output_result.output_timestamp`）, `obsidian_path`, `notification_sent` | destinations=[{target:"feishu"},{target:"obsidian"}], "2026-05-09T14:12:00Z", "Italy/2026-05/meloni-china-coop.md" |

### 5.3 降级与容错

```
环节失败时：
  → 检查 SkillManifest.fallback.available
  → 若 true：降级到内置最小实现，产出带 fallback 标记的 NewsEvent
  → 若 false：跳过该环节，上游产出直接传递给下游
  → 写入 PipelineContext.upstream.error 记录

整个 pipeline 失败时：
  → 保存当前 PipelineContext.memory 到持久存储
  → 下次心跳恢复时继承上次 memory，避免丢失跨周期信息
```

---

## 6. Skill 接入适配规范

不同形态的外部能力需要适配到 Protocol 才能接入 pipeline。

### 6.1 三类适配模式

| 能力形态 | 适配方式 | 适配器职责 |
|---------|---------|-----------|
| **Agent Skill**（SKILL.md） | 直接调用，Skill 内部遵循 Protocol 输入输出 | 无需额外适配，但需验证 Skill 输出符合 NewsEvent schema |
| **CLI 工具** | Wrapper 适配器：调用CLI → 解析输出 → 转为 NewsEvent[] | 写一个轻量 wrapper script（bash/python），解析CLI的stdout/文件输出 |
| **API/SDK** | API 适配器：调用API → 转为 NewsEvent[] | 写一个 adapter module，处理认证、rate limit、响应解析 |

### 6.2 ToolManifest 中介的 CLI Wrapper 模板

外部 CLI 不应由 `SourceChannel` 直接保存任意 shell 命令。`SourceChannel` 只引用已注册工具：

```yaml
acquisition_config:
  tool_ref: "opencli.google-news@0.1.0"
  binding_id: "google-news-italy-china"
  validated_args:
    query: "Cina Italia"
    region: "IT"
    format: "json"
```

执行层根据 `ToolManifest` 中的 `argv_template`、参数 schema、文件边界、网络边界和预算限制生成实际 argv，并记录审计日志。

```bash
#!/bin/bash
# tool-wrapper-template.sh
# 只执行 ToolManifest 注册过的 argv_template + validated_args

TOOL_REF="$1"           # 例如 opencli.google-news@0.1.0
BINDING_JSON="$2"       # SourceChannel binding + validated_args
INPUT_JSON="$3"         # PipelineContext + 上游NewsEvent[]
OUTPUT_DIR="$4"         # 产出目录

# 1. sandbox enforcer 校验 tool_ref、参数、cwd、网络、预算
sandbox-enforcer validate "$TOOL_REF" "$BINDING_JSON" "$INPUT_JSON"

# 2. 由ToolManifest渲染argv并执行，禁止shell拼接
RAW_OUTPUT=$(tool-runner exec "$TOOL_REF" "$BINDING_JSON")

# 3. 将工具输出转为 canonical NewsEvent[] 格式
jq -n \
  --argjson raw "$RAW_OUTPUT" \
  '[$raw | to_entries[] | {
    id: ("ne-" + (.value.target_id // "unknown") + "-" + (.value.source_id // "tool") + "-" + (.value.date // "00000000" | gsub("-"; "")) + "-" + (.value.url // .value.title | @base64 | .[0:8])),
    # 格式: ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}，见 contracts-canonical.md §3
    source_id: .value.source_id,
    source_url: .value.url,
    source_name: .value.source_name,
    published_at: .value.date,
    title_original: .value.title,
    content_original: .value.content,
    language: .value.lang,
    target_id: .value.target_id,
    source_country: .value.source_country,
    involved_countries: .value.involved_countries,
    pipeline_stage: "collected",
    metadata: {
      acquisition: {
        method: "tool",
        tool_ref: env.TOOL_REF
      }
    }
  }]' > "$OUTPUT_DIR/news_events.json"
```

### 6.3 适配质量标记

每个被适配的 Skill/CLI 在产出的 NewsEvent 中必须包含溯源信息：

```yaml
metadata:
  acquisition:
    method: "skill"                    # skill | tool | api | builtin_fallback
    tool_ref: "web-scraping@1.0"       # tool_id@version，若由工具执行
    skill_id: "rss-api-collector"      # skill_id，若由skill执行
    adapted_from: "autoglm-websearch@1.0"
```

这样编排器可以追踪每条新闻是由哪个具体 Skill 采集的，便于评估各 Skill 的贡献质量。

---

## 7. Protocol 版本演进策略

```yaml
# 版本规则
protocol_versions:
  current: "1"
  compatibility: "semver-compatible"   # 同大版本内向后兼容

# 版本协商（编排器与Skill之间）
negotiation:
  - 编排器查询Skill Manifest的manifest_version
  - 若版本兼容：直接使用
  - 若版本不兼容：查找该Skill是否有兼容版本
  - 若无兼容版本：降级到fallback或跳过

# 新版本发布流程
release_process:
  - 新版本Protocol先在docs中发布草案
  - 已有Skill逐步升级，不强制同步
  - 编排器同时支持新旧版本的Skill
  - 旧版本标记deprecated但至少保留3个版本周期
```

---

## 8. 安全与权限

```yaml
security:
  # Skill 执行权限分级
  permission_levels:
    read_only:     # 只读取PipelineContext和NewsEvent，不修改
    enrich:        # 可以丰富NewsEvent字段，但不删除
    write_context: # 可以修改PipelineContext（如设置urgency_mode）
    external_call: # 可以调用外部API/CLI（需显式授权）

  # 外部调用白名单
  external_call_whitelist:
    - "rss_fetch"
    - "web_scrape"
    - "feishu_api"
    - "obsidian_cli"
    - "llm_api"

  # 数据隐私
  data_privacy:
    - NewsEvent.content_original 不写入外部日志
    - PipelineContext.memory 跨周期存储时加密敏感实体
    - Skill 间不传递认证凭据，凭据由编排器统一管理
```

---

## 9. 下一步

本文档为设计讨论稿，待确认后：

1. 将 NewsEvent JSON Schema 转为可执行的 schema 验证文件（JSON Schema / Pydantic）
2. 定稿 TargetConfig、SourceChannel、PipelineContext、Memory、RunLog 的边界
3. 编写 SkillManifest 与 ToolManifest 校验器
4. 开发最小 SandboxPolicy enforcer，确保工具执行不绕过 registry
