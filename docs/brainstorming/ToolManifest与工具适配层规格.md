# ToolManifest 与工具适配层规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 工程承接规格
> 上级文档: [通用内核与平台化架构 PRD](./通用内核与平台化架构PRD.md)

---

## 0. 定位

ToolManifest 用于描述可执行工具能力，Tool Adapter 用于把外部工具的输入、输出、权限和错误统一到 News Sentry 内核。它解决的问题是：`SourceChannel` 不能直接持有任意 shell 命令，否则配置会绕过 sandbox、审计和权限治理。

核心原则：

1. `SourceChannel` 只做业务绑定，不保存可执行命令。
2. 只有注册过 `ToolManifest` 的工具才能被执行。
3. 实际 argv 由 `ToolManifest.argv_template + validated_args` 渲染。
4. 工具输出必须被 adapter 映射为 canonical `NewsEvent` 或结构化中间结果。
5. 每次工具运行必须写入 run log，包含工具版本、参数摘要、退出码、耗时、网络 host 和文件写入。

---

## 1. SkillManifest 与 ToolManifest 分工

| Manifest | 描述对象 | 典型字段 | 不应包含 |
|----------|----------|----------|----------|
| `SkillManifest` | 业务能力 | pipeline stage、输入输出 schema、可调用 capability、fallback、预算、Provider route | 具体 shell argv、浏览器 profile、API key |
| `ToolManifest` | 执行能力 | 工具入口、参数 schema、输出 schema、风险等级、权限需求、健康检查、超时、速率限制 | 业务信源频率、新闻价值规则、国家模板 |
| `SourceChannel` | 业务绑定 | source_id、采集方法、优先级、调度、字段映射、fallback、tool binding | 可执行命令、真实 cursor、失败次数 |

---

## 2. ToolManifest v1

```yaml
manifest_version: "1"
tool_id: "opencli.google-news"
version: "0.1.0"
display_name: "OpenCLI Google News"
tool_type: cli
owner: "news-sentry-team"
source:
  origin: "opencli"
  repo: "github.com/jackwener/OpenCLI"
  adapter_notes: "Google News search adapter exposed through OpenCLI"

capabilities:
  - web_news_search
  - structured_items_output

entry:
  executable: "opencli"
  argv_template:
    - "google"
    - "news"
    - "--query"
    - "{{query}}"
    - "--region"
    - "{{region}}"
    - "--format"
    - "{{format}}"
  shell_allowed: false

parameters_schema:
  query:
    type: string
    required: true
    max_length: 200
  region:
    type: string
    required: true
    enum: ["IT", "EU", "CN", "US"]
  format:
    type: string
    required: true
    enum: ["json"]

output_schema:
  type: json
  items_path: "$.items[]"
  required_fields:
    - title
    - url
    - source_name

permissions:
  risk_level: medium
  network:
    allowed_hosts:
      - "news.google.com"
      - "www.google.com"
  filesystem:
    read_roots: []
    write_roots:
      - "workspace/raw"
      - "workspace/logs"
  browser:
    session_profile_required: false
  credentials:
    required: false

runtime:
  timeout_seconds: 45
  max_items_per_run: 50
  rate_limit:
    min_delay_seconds: 2
    max_runs_per_hour: 20

health_check:
  mode: sample_args
  sample_args:
    query: "Cina Italia"
    region: "IT"
    format: "json"
  min_items_expected: 1
  schema_required_fields:
    - title
    - url
```

---

## 3. SourceChannel 绑定格式

`SourceChannel` 使用 `tool_ref + binding_id + validated_args` 绑定工具：

```yaml
id: google-news-italy-china
source_name: Google News Italy China Search
priority: P1
acquisition_method: opencli
acquisition_config:
  tool_ref: "opencli.google-news@0.1.0"
  binding_id: "google-news-italy-china"
  validated_args:
    query: "Cina Italia"
    region: "IT"
    format: "json"
  timeout_seconds: 45
field_mapping:
  title_original: "$.title"
  source_url: "$.url"
  source_name: "$.source_name"
  content_original: "$.snippet"
  published_at: "$.published_at"
  language: "it"
  target_id: "italy"
  source_country: "$.source_country"
  involved_countries: ["IT", "CN"]
  content_type: "article"
fallback_skill: rss-api-collector
```

绑定校验规则：

1. `tool_ref` 必须存在于 Tool Registry。
2. `validated_args` 必须通过 `parameters_schema`。
3. 运行时不得拼接额外参数。
4. 输出只允许通过 `field_mapping` 映射到 canonical 字段。
5. cursor、health、失败次数写入 memory，不写回 SourceChannel。

---

## 4. Tool Adapter 职责

Tool Adapter 是工具和内核之间的唯一执行接口：

```text
ToolAdapter.run(tool_ref, binding, run_context)
  -> validate manifest and args
  -> ask sandbox enforcer for permission
  -> render argv without shell
  -> execute with timeout and budget
  -> parse output
  -> validate output schema
  -> map errors to standard error types
  -> return structured result + audit record
```

返回结构：

```yaml
ToolRunResult:
  tool_ref: string
  binding_id: string
  success: bool
  output_ref: string?
  parsed_output: object?
  audit:
    run_id: string
    tool_id: string
    manifest_version: string
    args_digest: string
    started_at: datetime
    duration_ms: int
    exit_code: int?
    network_hosts: string[]
    files_written: string[]
  error:
    type: timeout | schema_invalid | permission_denied | runtime_error | empty_result
    message: string
    suggested_action: retry | repair_tool | manual_check | downgrade
```

---

## 5. 标准错误类型

| 错误类型 | 含义 | 默认处理 |
|----------|------|----------|
| `permission_denied` | sandbox 拒绝执行 | 停止，写入安全日志 |
| `args_invalid` | 参数未通过 schema | 标记配置错误 |
| `timeout` | 超时 | 降级或下次重试 |
| `runtime_error` | 工具退出失败 | 写入 tool health |
| `schema_invalid` | 输出结构不符合 schema | 标记 adapter degraded |
| `empty_result` | 成功但无有效条目 | 累计空结果，不立即失败 |
| `auth_required` | 需要未授权登录态 | 停止，等待人工授权 |
| `captcha_or_blocked` | 验证码、封禁或平台限制 | 停止自动重试 |

---

## 6. Registry 状态

Tool Registry 至少维护：

```yaml
tool_ref: "opencli.google-news@0.1.0"
status: active | degraded | quarantined | retired
trust_level: first_party | vetted_external | untrusted_external
last_health_check_at: datetime?
last_success_at: datetime?
consecutive_failures: int
security_review:
  reviewed_at: datetime?
  reviewer: string?
  result: approved | restricted | rejected
```

外部社区工具或 Skill 首次接入时默认 `quarantined`，只能在 dry-run 或人工隔离环境下运行。

---

## 7. 验收标准

1. 任意 `SourceChannel` 都不能直接执行 shell 字符串。
2. 工具必须通过 `ToolManifest` 注册和 schema 校验。
3. 工具运行必须经过 sandbox enforcer。
4. 工具输出必须映射为 canonical `NewsEvent` 或结构化中间结果。
5. 错误必须归一为标准错误类型并写入审计日志。
6. OpenCLI、RSS parser、浏览器/MCP 工具可以复用同一 registry 和 adapter 思路。

