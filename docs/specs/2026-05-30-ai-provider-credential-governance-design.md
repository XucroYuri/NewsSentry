# AI Provider 凭据治理设计规格

> 日期：2026-05-30
> 状态：长期方向设计稿
> 上游方向文档：`docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md`
> 适用范围：本地客户端、云端集群、专业订阅、BYOK、半中心化采集节点

## 1. 背景

当前 News Sentry 的 AI Provider 凭据主要通过进程环境变量读取：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`

这对本地开发和容器部署足够简单，但不适合长期平台化方向。News Sentry 正在从单机新闻监控工具演进为全球事实池、专业研究工作台、本地轻客户端和半中心化公共采集节点网络。继续只依赖环境变量，会带来以下问题：

- 本地客户端无法给非技术用户提供安全、清晰的配置体验。
- 云端团队/机构订阅无法支持 BYOK、预算、审计和多租户隔离。
- 半中心化节点可能被错误设计成持有平台级 AI Key。
- 后台现有“API Key 管理”容易和 AI Provider Key 混淆。
- Provider 路由、成本治理和任务权限无法按 target/workspace/task 细分。

本规格的目标是把 AI Provider Key 从“启动进程的环境变量”升级为“可按部署形态、用户、工作区、任务和预算治理的凭据系统”。

## 2. 术语边界

News Sentry 中至少存在三类不同密钥，必须从产品、API 和数据模型上分开。

### 2.1 AI Provider Credential

用于调用外部或自建 AI 能力：

- OpenAI
- Anthropic
- DeepSeek 或其他 OpenAI-compatible API
- Cloudflare AI Gateway
- 私有模型网关
- 企业内部 LLM Gateway

这些密钥控制的是 AI 调用能力和成本，不应等同于用户访问 News Sentry 的凭据。

### 2.2 News Sentry Access Key

用于访问 News Sentry 自身 API，例如：

- CLI 调用。
- 外部系统集成。
- cron 或自动化任务。
- 第三方应用访问受保护接口。

当前后台 `/api/v1/settings/api-key` 更接近这一类，应命名为“访问 Key”或“外部访问 Key”。

### 2.3 Collector Node Credential

用于未来半中心化采集节点接入云端任务网络：

- 接收云端签名采集任务。
- 上传公开信源采集结果。
- 证明节点身份、版本、地区声明和授权范围。
- 支持限流、吊销和审计。

Collector Node Credential 不应授予节点访问平台 AI Provider Key 的能力。

## 3. 设计原则

### 3.1 密钥类型隔离

AI Provider Credential、News Sentry Access Key、Collector Node Credential 必须使用不同的命名、页面、权限和存储策略。

后台不应继续用泛化的“API Key 管理”承载所有密钥。

### 3.2 本地优先安全

本地客户端默认可以不配置 AI Key，仍通过规则引擎运行。用户选择启用 AI 增强时，Key 应优先存入系统安全存储：

- macOS：Keychain
- Windows：Credential Manager
- Linux：Secret Service 或 libsecret

`.env` 和 shell 环境变量只作为开发者、CI、容器和裸机服务部署的兼容方式。

### 3.3 云端可治理

云端模式必须支持：

- 平台托管 AI 用量。
- BYOK。
- tenant/workspace 级隔离。
- 按 task type 授权。
- 成本预算和用量上限。
- 调用审计和异常告警。
- Key 轮换和吊销。

### 3.4 节点不持有平台级 AI Key

半中心化采集节点默认只持有 Collector Node Credential，不持有平台 AI Provider Key。

节点可以在本地拥有节点用户自己配置的 AI Key，但该 Key 只用于节点本地增强能力，不由云端下发，不回传，不共享。

### 3.5 Provider 路由不直接依赖环境变量

长期运行时不应由 `OpenAIProvider` / `AnthropicProvider` 直接从 `os.environ` 读取 Key。

Provider 实例应通过统一的 `ProviderCredentialResolver` 获取凭据，再创建调用客户端。环境变量应只是 resolver 的一个 backend。

## 4. 部署形态

### 4.1 本地单机模式

默认行为：

- 不要求配置 AI Key。
- 规则引擎、采集、过滤、输出可运行。
- 后台诊断显示“AI Provider 未启用”，而不是阻塞应用。

用户启用 AI 时：

- 在“AI Provider 凭据”页面选择 provider。
- 输入 Key 和可选 base URL。
- 系统写入 `LocalSecretStore`。
- 页面只显示 provider、状态、masked preview、最后验证时间。
- 不在 YAML、Markdown、SQLite 业务表或日志中保存明文 Key。

### 4.2 本地开发/CLI 模式

继续支持环境变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`

环境变量优先级可高于本地 secret store，便于 CI、测试和临时调试。

CLI 应提供诊断命令：

```bash
news-sentry doctor ai-provider
```

输出：

- 可用 provider。
- Key 是否存在。
- base URL。
- 健康检查结果。
- 不输出完整 Key。

### 4.3 云端托管模式

平台提供统一 AI Gateway：

- 用户不直接配置 Key。
- 调用消耗 workspace 或 subscription 的 AI 额度。
- 后端按任务类型路由到平台配置的 provider。
- 用户可在后台看到用量、预算和质量状态。

适合普通专业订阅用户。

### 4.4 云端 BYOK 模式

机构用户可配置自己的 AI Key：

- Key 存储在云端 Secret Vault。
- 绑定 tenant/workspace。
- 可限制 task type：`translate / classify / judge / summarize / brief`。
- 可限制 target 范围。
- 可配置月预算、单次调用预算、速率限制。
- 所有调用记录审计日志。

适合新闻机构、研究团队、企业风险监控客户。

### 4.5 半中心化 Collector Node 模式

节点持有：

- Collector Node Credential。
- 节点签名密钥。
- 可选的本地 AI Provider Credential。

节点不持有：

- News Sentry Cloud 的平台级 AI Key。
- 其他用户或机构的 BYOK。
- 云端 Secret Vault 明文。

云端下发采集任务时，只下发任务定义、allowlist、签名和预算，不下发 AI Provider Key。

## 5. 产品信息架构

后台高级管理应拆成三个入口。

### 5.1 AI Provider

管理模型路由和任务策略：

- Provider 列表。
- 模型选择。
- task type 绑定。
- fallback 顺序。
- timeout。
- 单次成本上限。
- 健康检查。

对应当前 `config/provider/routes.yaml` 的可视化管理。

### 5.2 凭据与密钥

管理不同密钥类型：

- AI Provider Credential。
- News Sentry Access Key。
- Webhook Secret。
- Collector Node Token。
- 云端 BYOK。

页面必须明确密钥类型和作用域，避免把访问 Key 与 AI Key 混为一谈。

### 5.3 用量与成本

展示 AI 调用治理：

- 按 provider 汇总。
- 按 target 汇总。
- 按 task type 汇总。
- token、费用、成功率、失败率。
- 异常增长告警。
- 预算剩余额度。

## 6. 运行时架构

### 6.1 `ProviderCredentialResolver`

新增统一凭据解析服务：

```text
ProviderCredentialResolver.resolve(
  provider_id,
  task_type,
  target_id,
  workspace_id,
  deployment_mode
) -> ProviderCredential
```

返回对象包含：

- `provider_id`
- `api_key`
- `base_url`
- `credential_ref`
- `source`
- `allowed_task_types`
- `budget_policy_ref`

`api_key` 只存在于内存中，不写入日志和业务表。

### 6.2 Secret Store Backend

抽象接口：

```text
SecretStore.get(ref) -> SecretValue
SecretStore.set(ref, value, metadata)
SecretStore.delete(ref)
SecretStore.list(scope)
SecretStore.health_check()
```

第一阶段 backend：

- `EnvSecretStore`：读取环境变量，兼容现状。
- `LocalSecretStore`：系统安全存储，服务本地客户端。

后续 backend：

- `CloudSecretStore`：KMS、Vault 或云厂商 Secret Manager。

### 6.3 Provider Client Factory

Provider client 不再直接读取环境变量。

新路径：

```text
ProviderRouter
  -> ProviderCredentialResolver
  -> ProviderClientFactory
  -> OpenAIProvider / AnthropicProvider / CompatibleProvider
```

兼容期可以保留当前 `OpenAIProvider({})` 读取环境变量的行为，但应标记为 fallback。

## 7. 数据模型建议

### 7.1 `provider_credentials`

云端模式建议表结构：

| 字段 | 说明 |
| --- | --- |
| `credential_id` | 稳定 ID |
| `tenant_id` | 租户 |
| `workspace_id` | 工作区 |
| `provider_id` | `openai / anthropic / compatible / custom` |
| `display_name` | 用户可见名称 |
| `secret_ref` | Secret Vault 引用 |
| `base_url` | 可选，非敏感或加密保存 |
| `allowed_task_types_json` | 允许任务 |
| `target_scope_json` | target 范围 |
| `status` | `active / disabled / revoked / error` |
| `last_verified_at` | 最近验证时间 |
| `created_by` | 创建者 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

### 7.2 `provider_usage`

用于成本与审计：

| 字段 | 说明 |
| --- | --- |
| `usage_id` | 稳定 ID |
| `credential_id` | 凭据 |
| `target_id` | target |
| `task_type` | 任务类型 |
| `route_id` | provider route |
| `model` | 模型 |
| `input_tokens` | 输入 token |
| `output_tokens` | 输出 token |
| `estimated_cost_usd` | 估算成本 |
| `status` | `ok / error / fallback` |
| `error_code` | 错误码 |
| `created_at` | 调用时间 |

### 7.3 `collector_node_credentials`

用于半中心化节点：

| 字段 | 说明 |
| --- | --- |
| `node_id` | 节点 ID |
| `tenant_id` | 所属租户或合作方 |
| `region` | 地区声明 |
| `credential_ref` | 节点凭据引用 |
| `allowed_sources_json` | allowlist |
| `allowed_task_types_json` | 节点允许任务 |
| `status` | `pending / active / suspended / revoked` |
| `last_seen_at` | 最近心跳 |
| `version` | 节点版本 |
| `created_at` | 创建时间 |

## 8. 迁移路径

### Phase A：命名与诊断收敛

目标：

- 把当前“API Key 管理”改名为“访问 Key”。
- 新增“AI Provider 凭据”说明页。
- 后台诊断明确显示当前读取来源：env / local secret / cloud vault。
- 保持 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 兼容。

不改变 provider 调用路径，只减少产品混淆。

### Phase B：本地 Secret Store

目标：

- 引入 `ProviderCredentialResolver`。
- 引入 `EnvSecretStore` 和 `LocalSecretStore`。
- 本地 UI 可保存 AI Key 到系统安全存储。
- Provider 初始化改为 resolver 驱动。
- 诊断从 resolver 获取状态。

### Phase C：用量与预算

目标：

- 记录 provider usage。
- 按 provider/target/task 展示用量。
- 增加预算限制和异常告警。
- 支持低成本 fallback 策略。

### Phase D：云端 BYOK 与托管网关

目标：

- 引入 cloud secret backend。
- 支持 tenant/workspace BYOK。
- 支持平台托管 AI Gateway。
- 增加审计、轮换、吊销。

### Phase E：Collector Node Credential

目标：

- 节点接入使用单独 credential。
- 节点任务签名和上传签名。
- 节点不接收平台 AI Key。
- 本地节点可选配置自己的本地 AI Key。

## 9. 安全要求

- 不在日志中输出完整 Key。
- 不在 Markdown、YAML、SQLite 业务表中保存明文 AI Key。
- 不把 Key 包含在导出包、诊断包和错误报告中。
- Preview 只显示前后短片段，例如 `sk-...abcd`。
- 删除 Key 后立即使相关 provider 路由不可用。
- 云端 Key 必须支持吊销、轮换和审计。
- Collector Node Credential 与 AI Provider Credential 不可互换。

## 10. 当前代码影响

当前实现中：

- `config/provider/routes.yaml` 定义 provider/model 路由。
- `OpenAIProvider` 读取 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。
- `AnthropicProvider` 读取 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_BASE_URL`。
- 后台诊断通过环境变量判断是否配置 AI Key。
- `/api/v1/settings/api-key` 实际管理的是用户访问 API Key。

后续实现时应优先调整命名和诊断，避免继续积累概念债。

## 11. 非目标

本规格不立即实现：

- 完整多租户权限系统。
- 云端 Secret Vault。
- 计费系统。
- 企业级审计 UI。
- Collector Node 协议。
- Provider 质量评测体系。

这些能力应在独立 implementation plan 中分阶段落地。

## 12. 已采纳决策

- AI Provider Key 管理采用分层凭据治理模型。
- 本地模式优先使用系统安全存储，环境变量保留为兼容入口。
- 云端支持平台托管 AI 与 BYOK 两种模式。
- 半中心化采集节点默认不持有平台 AI Provider Key。
- 当前“API Key 管理”后续应改名为“访问 Key”，并与 AI Provider 凭据分离。
