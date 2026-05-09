# AI Provider 与模型路由规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 工程承接规格
> 上级文档: [通用内核与平台化架构 PRD](./通用内核与平台化架构PRD.md)

---

## 0. 定位

AI Provider 层用于把翻译、过滤分类、新闻价值研判、事实核查辅助、草稿生成和社媒舆情分析从具体模型供应商中解耦。Skill 不直接调用 OpenAI、Anthropic、本地模型或其他 SDK，而是通过任务路由调用统一接口。

v1 不做复杂智能调度。最小目标是：任务路由、输出 schema、预算、fallback 和审计日志。

---

## 1. 设计原则

1. **按任务路由**：使用 `judge.primary`、`translate.fast`、`draft.editorial` 等 route，而不是在 Skill 中写供应商名。
2. **结构化输出**：每条 route 必须绑定 `output_schema_id`。
3. **预算前置**：每次 run 有模型调用预算，Provider 层必须拒绝超预算调用。
4. **fallback 可控**：只有配置允许的错误类型触发 fallback。
5. **审计完整**：每次模型调用记录 provider、model、usage、成本估计、输入摘要和输出引用。
6. **高风险人工 gate**：事实判断、社媒舆情定性、发布相关内容必须保留人工确认路径。

---

## 2. ProviderConfig v1

```yaml
route_id: "judge.primary"
task_type: "news_value_judge"
primary:
  provider: "openai"
  model: "gpt-*"
fallback:
  provider: "anthropic"
  model: "claude-*"
prompt_template_id: "judge_v1"
output_schema_id: "JudgeResult.v1"
timeout_seconds: 60
max_cost_per_run: 5.00
max_input_events: 20
fallback_on:
  - timeout
  - rate_limit
  - schema_invalid
audit:
  record_provider: true
  record_model: true
  record_input_summary: true
  record_output_ref: true
  record_usage: true
  record_estimated_cost: true
human_gate:
  required_for:
    - publish_decision
    - high_risk_social_claim
    - source_contradiction
```

---

## 3. Provider Adapter 接口

Provider adapter 只暴露一个核心接口：

```text
invoke(route_id, input, context) -> ProviderResult
```

返回结构：

```yaml
ProviderResult:
  route_id: string
  task_type: string
  success: bool
  structured_result: object?
  usage_log:
    run_id: string
    provider: string
    model: string
    prompt_template_id: string
    output_schema_id: string
    input_summary: string
    output_ref: string?
    tokens_input: int?
    tokens_output: int?
    estimated_cost: float?
    duration_ms: int
  error:
    type: timeout | rate_limit | schema_invalid | provider_error | budget_exceeded
    message: string
    fallback_attempted: bool
```

Skill 只能消费 `structured_result`，不能依赖供应商原始响应格式。

---

## 4. 路由分类

| route | 用途 | 输出 schema | 默认策略 |
|-------|------|-------------|----------|
| `translate.fast` | 标题/摘要翻译 | `TranslationResult.v1` | 低成本优先 |
| `filter.semantic` | 语义预筛 | `FilterResult.v1` | 小模型或规则优先 |
| `judge.primary` | 新闻价值研判 | `JudgeResult.v1` | 质量优先，限制条数 |
| `judge.crosscheck` | 多源矛盾和事实核查辅助 | `CrossCheckResult.v1` | 高质量模型，人工 gate |
| `draft.editorial` | 简报/新闻稿草稿 | `DraftResult.v1` | 风格稳定，保留审阅 |
| `social.opinion` | KOL/社媒舆情分析 | `OpinionResult.v1` | 观点事实分离，高风险 gate |

---

## 5. 输出 Schema 要求

Provider 输出必须经过 schema 校验。例如 `JudgeResult.v1`：

```yaml
JudgeResult:
  judge_skill_id: string
  judge_model: string
  summary: string
  analysis: string
  value_dimensions:
    - dimension: string
      score: float
      weight: float
      explanation: string
  recommendation: recommend | monitor | archive | discard
  reasoning: string
  confidence: float
```

分数统一使用 0-100。`recommendation` 只写入 `judge_result.recommendation`，不复制到 `NewsEvent` 顶层。

---

## 6. 预算与降级

预算来源：

1. `PipelineContext.dynamic_config.llm_budget_remaining`
2. `ProviderConfig.max_cost_per_run`
3. route 级 `max_input_events`
4. SkillManifest 的运行约束

降级顺序：

1. 规则引擎或缓存结果。
2. fallback Provider。
3. 降低任务范围，例如只处理 P0/P1 事件。
4. 写入人工检查队列。

禁止行为：

1. 超预算继续调用。
2. schema 校验失败后静默接受自然语言输出。
3. 将 Provider 原始响应直接写入公开草稿。
4. 让 AI 单独给出事实结论而不保留来源和人工 gate。

---

## 7. 审计日志

每次 Provider 调用写入 `logs/provider-usage/{run_id}.jsonl` 或等价日志：

```yaml
run_id: run-20260509-0800-it
route_id: judge.primary
task_type: news_value_judge
provider: openai
model: gpt-*
prompt_template_id: judge_v1
output_schema_id: JudgeResult.v1
input_summary: "3 events from ansa-rss, fao-news-rss"
output_ref: "evaluated/ne-italy-ansa-20260509-a1b2c3d4.md"
estimated_cost: 0.42
duration_ms: 3400
status: success
```

日志不得包含完整敏感正文、API key、cookie、token 或浏览器 profile 内部数据。

---

## 8. 验收标准

1. Skill 只能通过 `route_id` 调用模型，不直接绑定供应商 SDK。
2. 同一 `judge.primary` 任务可切换至少两个 Provider，输出仍满足 `JudgeResult.v1`。
3. 预算不足时 Provider 层拒绝调用并给出可解释错误。
4. schema 校验失败会触发 fallback 或人工检查，不静默通过。
5. 每次调用都有 usage log 和 output ref。
6. 发布、社媒事实定性、高风险矛盾源必须保留人工 gate。

