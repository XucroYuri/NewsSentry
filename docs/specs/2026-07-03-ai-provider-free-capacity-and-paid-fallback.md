# AI Provider 免费容量与预算兜底策略

> 日期：2026-07-03
> 状态：策略规格稿
> 适用范围：公共翻译、公共摘要/推荐理由、AI enrichment batch、judge review、代码维护类 AI 自动化
> 关联配置：`config/provider/routes.yaml`；后续严格零成本配置应使用 `config/provider/routes-strict-zero.yaml`

## 1. 目标

News Sentry 的 AI 能力基础设施采用“免费优先、全量但慢、预算兜底”的策略。

核心目标：

- 所有翻译、摘要、推荐理由、AI enrichment 候选都保留在 backlog 中，直到成功处理或被人工/规则明确废弃。
- 默认运行模式为 strict-zero：只消耗官方免费额度或 ledger 已确认免费的试用额度；包月额度和任何可能产生费用的端点只进入 budgeted fallback。
- 当所有免费资源冻结且 backlog 影响业务连续性时，可进入 budgeted fallback：在明确预算、审计和硬停线内使用付费兜底。
- ProviderRouter 仍是执行平面；不恢复 FreeLLMAPI sidecar。Cloudflare AI Gateway 只作为可选的免费观测、缓存、限流层，不作为必需运行依赖。

## 2. 成本策略分层

Provider、Key、Route 必须显式标注成本层级。

| cost_tier | 含义 | 是否可在 strict-zero 使用 |
|---|---|---|
| `free` | 官方明确提供免费额度或免费模型，且当前 ledger 确认未超限 | 是 |
| `trial_credit` | 注册、活动、月度或试用 credit，ledger 确认余额为正 | 是，但余额耗尽立即停用 |
| `subscription_included` | 包月套餐内额度，确认不会自动产生超额费用 | strict-zero 默认否；budgeted fallback 可用 |
| `subscription_overage_disabled` | 包月套餐内额度，超额已关闭或无法自动扣费 | strict-zero 默认否；budgeted fallback 可用 |
| `paid_budgeted` | 按量付费或可超额扣费，但设置了日/月/单任务硬预算 | 否，仅 budgeted fallback |
| `paid_disabled` | 付费端点、条款不清或尚未确认免费余额 | 否 |

严格零成本模式不得把多个同账号、同组织、同项目下的 Key 当成绕过配额的方式。`quota_scope` 必须记录为 `key / account / org / project / subscription / workspace` 之一。

## 3. 候选 Provider 池

以下清单是 2026-07-03 的策略快照。免费额度、模型 ID、商用条款变化很快，上线前必须由 `news-sentry doctor ai-provider --strict-zero` 或等效 smoke test 重新确认。

### 3.1 默认免费主力池

| Provider | 区域/类型 | 建议用途 | 成本层级 | 文档 |
|---|---|---|---|---|
| Gemini API | 全球官方 | 翻译、摘要、研判主力 | `free` | [Pricing](https://ai.google.dev/gemini-api/docs/pricing), [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| Groq | 美国官方 | 快速摘要、研判 fallback | `free` | [Rate limits](https://console.groq.com/docs/rate-limits) |
| Cloudflare Workers AI | 全球官方 | 公共翻译/摘要兜底、Cloudflare-native 执行 | `free` | [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) |
| Cerebras Inference | 美国官方 | 批处理、研判、翻译 fallback | `free` 或 `trial_credit` | [Rate limits](https://inference-docs.cerebras.ai/support/rate-limits) |
| GitHub Models | 美国官方 | 原型、低频摘要/研判 | `free` | [Limits](https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models) |
| SiliconFlow | 中国/第三方平台 | 中文翻译、开源模型 fallback | `free` 或 `trial_credit` | [Rate limits](https://docs.siliconflow.com/en/userguide/rate-limits/rate-limit-and-upgradation) |
| OpenRouter free models | 第三方中转 | 免费模型兜底、长尾模型补位 | `free` | [Pricing](https://openrouter.ai/pricing) |
| Mistral La Plateforme | 欧洲官方 | 批处理、摘要、研判候选 | `trial_credit` 或 `paid_disabled` | [Usage limits](https://docs.mistral.ai/admin/billing-usage/usage-limits) |
| SambaNova Cloud | 美国官方 | 高吞吐开源模型候选 | `trial_credit`，需 ledger 确认 | [Plans](https://cloud.sambanova.ai/plans) |
| Fireworks AI | 美国官方 | 开源模型、批处理候选 | `trial_credit` 或 `paid_disabled` | [Pricing](https://fireworks.ai/pricing) |
| Nscale | 英国/全球官方 | 开源模型推理候选 | `trial_credit` 或 `paid_disabled` | [Pricing](https://www.nscale.com/pricing) |

### 3.2 中国官方/准官方免费或试用候选

| Provider | 建议用途 | strict-zero 处理 | 文档 |
|---|---|---|---|
| Alibaba Model Studio / Bailian | 通义、DeepSeek、Kimi、GLM、MiniMax 等模型试用；后续 Token Plan 兜底 | 仅 ledger 确认免费额度时启用，否则 `paid_disabled` | [Model Studio pricing/free quota](https://help.aliyun.com/zh/model-studio/) |
| ModelScope API-Inference | 开源模型低频推理、中文任务候选 | 作为 `modelscope` 低优先级候选，需 smoke test | [API-Inference docs](https://modelscope.cn/docs/model-service/API-Inference/intro) |
| Tencent Hunyuan | 翻译/摘要候选，适合腾讯云已有账号 | 免费包确认后 `trial_credit`，否则 `paid_disabled` | [Text Generation billing](https://www.tencentcloud.com/document/product/1729/104753) |
| Volcengine Ark | 豆包/第三方模型试用、后续付费兜底 | 免费推理额度确认后 `trial_credit` | [Ark docs](https://www.volcengine.com/docs/82379) |
| Z.ai / 智谱 | GLM 系列、Coding Plan 候选 | 免费活动确认后 `trial_credit`；Coding Plan 只走代码维护任务 | [Rate limits](https://docs.z.ai/guides/rate-limit), [DevPack](https://docs.z.ai/devpack/overview) |
| Baidu AI Studio / Qianfan | 中文模型、文心生态候选 | AI Studio 免费额度确认后 `trial_credit`；Qianfan 默认 `paid_disabled` | [AI Studio](https://aistudio.baidu.com/), [Qianfan docs](https://cloud.baidu.com/doc/WENXINWORKSHOP/) |
| DeepSeek official | 高性价比中文/推理模型 | strict-zero 默认 `paid_disabled`，除非存在明确赠送余额 | [API docs](https://api-docs.deepseek.com/) |
| Moonshot / Kimi | 中文长上下文候选 | 需充值或赠送余额确认；默认 `paid_disabled` | [Pricing](https://platform.moonshot.cn/docs/pricing/chat) |
| MiniMax | 中文、多模态、语音/文本候选 | 官方 API 默认按量；Token Plan 走 budgeted fallback | [Token Plan](https://platform.minimax.io/docs/guides/pricing-token-plan) |

### 3.3 可信第三方中转/网关候选

第三方中转只用于低敏、可重试、可审计任务。公共新闻文本可走，但不得发送未公开的客户材料、私有凭据、内部评论或受限来源全文。

| Provider | 类型 | 建议用途 | strict-zero 处理 | 文档 |
|---|---|---|---|---|
| Cloudflare AI Gateway | 观测/缓存/限流网关 | 统一日志、缓存、限流，不是模型来源 | 可选控制层 | [Pricing](https://developers.cloudflare.com/ai-gateway/reference/pricing/) |
| Vercel AI Gateway | 网关/credit | 多 provider 统一路由、短期 credit | `trial_credit`，余额耗尽停用 | [AI Gateway](https://vercel.com/docs/ai-gateway) |
| Hugging Face Inference Providers | 官方聚合 | 月度 credit、开源模型推理 | `trial_credit`，按月 ledger 重置 | [Pricing](https://huggingface.co/docs/inference-providers/en/pricing) |
| Requesty | 第三方中转 | free models、OpenAI-compatible 统一入口 | 有免费额度时 `free`，需 smoke test | [Pricing](https://requesty.ai/pricing) |
| Novita | 第三方服务 | serverless 免费模型、低优先级开发候选 | `free` 或 `trial_credit`，需 smoke test | [Serverless API](https://novita.ai/docs) |
| AIMLAPI | 第三方中转 | 多模型试用、长尾模型候选 | `trial_credit`，需确认商用条款 | [Docs](https://docs.aimlapi.com/) |
| Portkey | 企业网关 | BYOK、审计、限流、fallback 控制 | 控制层；不作为免费模型来源 | [Pricing](https://portkey.ai/pricing) |
| 302.AI | 中国第三方中转 | 付费兜底、模型覆盖 | 默认 `paid_disabled`，需预算开关 | [Docs](https://302.ai/) |
| API易 | 中国第三方中转 | 付费兜底、模型覆盖 | 默认 `paid_disabled`，需预算开关 | [Docs](https://apiyi.com/) |
| AiHubMix | 中国第三方中转 | 声称有免费模型，需验证 | `paid_disabled`，smoke test 通过后再提升 | [Docs](https://docs.aihubmix.com/) |
| DMXAPI | 中国第三方中转 | 模型聚合候选 | `paid_disabled`，需账单和条款复核 | [Site](https://www.dmxapi.com/) |

## 4. 明确排除和风险线

以下资源不得进入生产默认路由：

- Cohere trial key：官方 trial key 可免费使用，但不允许生产/商业用途，因此不进入生产默认池。
- ChatGPT/Gemini/Kimi/Claude 网页 session token、浏览器 Cookie、逆向接口、共享账号代理。
- 要求“无限免费”“无实名绕额度”“多账号养号”的中转站。
- 不能说明数据保留、模型来源、账单口径、限流策略的中转站。
- 默认会自动充值、自动扣费、自动超额的套餐，除非已设置硬预算和人工确认。

## 5. 任务路由策略

### 5.1 strict-zero profile

建议后续新增 `config/provider/routes-strict-zero.yaml`，并把公共翻译/摘要/批处理改为 quota-aware backlog 调度：

| route | provider 顺序 | 调度策略 |
|---|---|---|
| `translate.public` | Gemini → Groq → SiliconFlow → Cerebras → Cloudflare Workers AI → OpenRouter → GitHub Models → ModelScope → Requesty/Novita free | 429/402/quota 时设置 cooldown；本轮停止，不触发 fallback storm |
| `public.summary_reason` | Gemini → Groq → Cerebras → GitHub Models → Vercel/HF credit | 摘要可延迟；失败保留 backlog |
| `ai.enrichment.batch` | Gemini → Cerebras → Groq → Mistral → SiliconFlow → Alibaba/Volcengine trial | 低并发，优先夜间/低峰 |
| `judge.review` | Gemini → Cerebras → Groq → 本地规则 | AI 全部冻结时只给内部 fallback，不自动发布 |

### 5.2 budgeted fallback profile

建议后续新增 `config/provider/routes-budgeted-fallback.yaml`，只在所有免费资源不可用且触发条件满足时启用：

```yaml
ai_cost_policy:
  mode: budgeted_fallback
  strict_zero_first: true
  paid_fallback_enabled: true
  trigger:
    require_all_free_exhausted: true
    min_backlog_age_hours: 6
    min_due_backlog_count: 50
  budgets:
    daily_usd_cap: 2
    monthly_usd_cap: 30
    per_item_usd_cap: 0.01
    hard_stop_on_budget_exceeded: true
  disallow:
    - silent_overage
    - auto_recharge_without_explicit_budget
    - coding_plan_for_non_coding_content
```

付费兜底只处理已经 due 的 backlog，不追求实时清空；预算耗尽后回到“全量但慢”。

## 6. Key Pool 与 Ledger

Provider key pool 读取以下模式：

```text
GEMINI_API_KEY
GEMINI_API_KEY_2
...
GEMINI_API_KEY_10
```

新增 provider 使用同样规则：

```text
CEREBRAS_API_KEY[_2.._10]
GITHUB_MODELS_API_KEY[_2.._10]
MISTRAL_API_KEY[_2.._10]
SILICONFLOW_API_KEY[_2.._10]
VERCEL_AI_GATEWAY_API_KEY[_2.._10]
SAMBANOVA_API_KEY[_2.._10]
FIREWORKS_API_KEY[_2.._10]
NSCALE_API_KEY[_2.._10]
HUGGINGFACE_API_KEY[_2.._10]
MODELSCOPE_API_KEY[_2.._10]
ALIBABA_MODEL_STUDIO_API_KEY[_2.._10]
VOLCENGINE_ARK_API_KEY[_2.._10]
ZAI_API_KEY[_2.._10]
TENCENT_HUNYUAN_API_KEY[_2.._10]
BAIDU_AI_STUDIO_API_KEY[_2.._10]
REQUESTY_API_KEY[_2.._10]
NOVITA_API_KEY[_2.._10]
AIMLAPI_API_KEY[_2.._10]
```

Ledger 不保存明文 Key，只保存：

- provider
- masked key ref
- quota_scope
- cost_tier
- route/task scope
- daily/monthly request/token cap
- success/failure counts
- cooldown_until
- reset_at
- last_error_class
- free/trial/subscription/paid budget state

建议持久化位置：`memory/provider_pool_state.json`；云端可迁移到现有 SQLite/D1 store。

## 7. backlog 调度规则

公共翻译和 AI enrichment 必须遵守“全量但慢”：

- 每个候选在成功前保持 eligible，不因 provider quota 错误永久隐藏。
- 429、402、insufficient_quota、credit_exhausted 等错误只设置 provider/key cooldown 和 `attempt_after`。
- 同一轮调度中，如果所有 strict-zero provider 都进入 quota/cooldown，不继续级联付费路由，避免 fallback storm。
- `auth_error`、`invalid_api_key`、`permission_denied` 不触发付费 fallback，只报警。
- paid fallback 只能由 quota/cooldown/frozen 类错误触发，并且必须满足预算、任务类型、backlog 年龄和数量条件。

## 8. 包月套餐与 Coding Plan 兜底

Coding Plan 与通用 API 包月必须分开治理。

### 8.1 内容生产/公共翻译可用的包月或付费兜底

优先选择能够通过 API 服务 News Sentry 后台任务、且有明确预算/用量页的方案：

| 方案 | 建议用途 | 成本层级 |
|---|---|---|
| MiniMax Token Plan | 中文摘要、翻译、内容增强兜底 | `subscription_included` 或 `paid_budgeted` |
| Alibaba Model Studio Token Plan | 多模型内容任务兜底 | `subscription_included` 或 `paid_budgeted` |
| Vercel AI Gateway paid credits | 多 provider 路由与统一账单 | `paid_budgeted` |
| OpenRouter paid credits | 长尾模型兜底 | `paid_budgeted` |
| Requesty PAYG | 多模型统一入口 | `paid_budgeted` |
| DeepSeek / SiliconFlow PAYG | 高性价比中文/推理兜底 | `paid_budgeted` |

### 8.2 只用于代码维护的 Coding Plan

以下资源适合代码维护、CI 诊断、PR review、文档同步、脚本生成等 `coding_maintenance` 任务。除非条款明确允许通用 API 后台内容处理，否则不得用于 `translate.public`、`public.summary_reason`、`ai.enrichment.batch`。

| 方案 | 适用任务 | 备注 |
|---|---|---|
| Alibaba Qwen Code / Coding Plan | repo 维护、代码分析、文档同步 | 与 Model Studio Token Plan 分开标注 |
| Z.ai GLM Coding Plan | coding agent、代码 review、开发工具链 | 限支持工具和产品环境 |
| Volcengine Ark Coding Plan | coding agent、开发工具链 | 需确认 base URL、模型和工具支持 |
| OpenAI Codex plan/API key | 代码维护；API Key 可用于自动化但按 API 计费 | ChatGPT/Codex 订阅不等于后端免费 API |
| Claude Code Pro/Max | 本地代码维护 | 若设置 `ANTHROPIC_API_KEY` 通常走 API 账单，不消耗订阅 |
| GitHub Copilot Pro/Pro+/Max | IDE/代码辅助 | 不是通用后台 API Provider |

建议新增独立任务类型：

```yaml
task_type: coding_maintenance
allowed_cost_tiers:
  - subscription_included
  - subscription_overage_disabled
  - paid_budgeted
disallowed_routes:
  - translate.public
  - public.summary_reason
  - ai.enrichment.batch
```

## 9. 实施路线

1. 配置层：扩展 provider route schema，加入 `cost_tier`、`quota_scope`、`daily_request_cap`、`daily_token_cap`、`cooldown_seconds`、`enabled_in_strict_zero`、`trial_credit_required`。
2. Provider 层：用现有 OpenAI-compatible base 增加 `cerebras`、`github_models`、`mistral`、`siliconflow`、`vercel_ai_gateway`、`sambanova`、`huggingface`、`modelscope`、`requesty`、`novita` 等 adapter。
3. Ledger 层：新增 `ProviderCredentialPool` 和 `ProviderPoolLedger`，只保存 masked 状态，不保存明文 Key。
4. Scheduler 层：公共翻译从固定 cadence 改为 quota-aware backlog；quota exhaustion 只 requeue，不永久隐藏。
5. API/CLI：新增 `GET /api/v1/ai/provider-pool/status`；扩展 `/api/v1/ai/translation/status`；新增 `news-sentry doctor ai-provider --strict-zero` 和 `--budgeted-fallback`。
6. 文档层：`routes-strict-zero.yaml` 作为 strict-zero 权威配置；`routes-budgeted-fallback.yaml` 作为付费兜底配置，不与默认 `routes.yaml` 混写。

## 10. 验证清单

- strict-zero 下没有 `paid_budgeted` 或 `paid_disabled` provider 被调用。
- trial credit provider 在 ledger 未确认余额时不可用。
- 同账号多 Key 不会绕过 account/org/project 级 quota。
- 所有 key refs 在 API、CLI、日志中都已 mask。
- 429/402/quota 错误会 requeue backlog，不会永久隐藏候选。
- 所有免费资源冻结时，scheduler 停止本轮，不触发 fallback storm。
- paid fallback 只在配置开启、预算足够、backlog 达到触发条件时进入。
- Coding Plan 路由不会处理公开翻译、摘要或 enrichment。
- Cohere trial key、逆向网页接口、共享账号代理不进入生产默认路由。
