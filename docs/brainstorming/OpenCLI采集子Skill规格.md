# OpenCLI 采集子 Skill 规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发前子规格
> **实现阶段: Phase 4 Tool/Skill Registry + OpenCLI（v1+）** — 本规格在内核 MVP 完成后实现；Kernel MVP 阶段不引入 OpenCLI
> 上级文档: [Agent Skill Pack 开发总纲与多 Agent 生产线路线图](./AgentSkillPack开发总纲与多Agent生产线路线图.md)
> 字段口径基准: [contracts-canonical.md](../contracts-canonical.md)

---

## 0. 定位

OpenCLI 采集子 Skill 负责把网站、搜索页、网页应用和终端命令适配为可重复执行的结构化采集能力。它是 RSS/API 基线之外的增强层，主要解决三类问题：

1. 目标源没有可用 RSS/API，但页面结构稳定。
2. RSS 只有摘要，需要全文、作者、分类、引用链接等深度字段。
3. 需要通过已有 OpenCLI adapter 或新建 adapter 执行搜索、列表抓取、全文提取。

OpenCLI 子 Skill 的核心价值是“编译期智能、运行期确定性”：一次性探查和生成适配器后，心跳运行时只执行确定性命令，减少 LLM 在采集阶段的消耗。

---

## 1. 子 Skill 边界

### 1.1 负责事项

OpenCLI collector 负责：

1. 读取 `SourceChannel(acquisition_method=opencli)`。
2. 执行预定义 OpenCLI 命令或 adapter wrapper。
3. 解析命令输出并映射为 `NewsEvent(stage=collected)`。
4. 对 adapter 输出做结构校验和健康检查。
5. 记录命令、版本、执行耗时、退出码和错误。
6. 在命令失败时降级到备用方式或写入人工检查队列。

### 1.2 不负责事项

OpenCLI collector 不负责：

1. 自动绕过登录、验证码、付费墙或访问限制。
2. 在没有授权的情况下使用私人账号。
3. 判断新闻价值。
4. 自动发布或外部推送。
5. 长时间驻留运行。每次心跳只执行 bounded run。

---

## 2. 输入契约

```yaml
OpenCLICollectorInput:
  target_config: TargetConfig
  pipeline_context: PipelineContext
  source_channels:
    - id: string
      dimension: news_media | international_orgs | government | academic | search | social_public
      source_name: string
      priority: P0 | P1 | P2 | P3
      acquisition_method: opencli
      acquisition_config:
        tool_ref: string              # 已注册 ToolManifest 引用，如 "opencli.ansa-news@0.1.0"
        binding_id: string            # SourceChannel 到工具的绑定ID
        validated_args: dict          # 通过 ToolManifest 参数schema校验后的参数
        working_directory: string?
        timeout_seconds: int
        auth_required: bool
        session_profile: string?
        output_format: json | markdown | text
        verify_tool_ref: string?
      field_mapping: dict
      health_policy:
        min_items_expected: int
        max_empty_runs_before_alert: int
        schema_required_fields: string[]
      fallback_skill: rss-api-collector | web-scraping | manual-check
  historical_events: NewsEvent[]
  runtime_options:
    max_tool_runs_per_run: int
    max_items_per_tool_run: int
    dry_run: bool
```

`SourceChannel` 不保存任意 shell 命令。实际 argv 只能由 `ToolManifest.argv_template` 和 `validated_args` 渲染，并由 sandbox enforcer 校验后执行。禁止将动态 LLM prompt 拼进运行期采集逻辑。

---

## 3. 输出契约

OpenCLI 子 Skill 输出 `NewsEvent(stage=collected)`，并在 metadata 中保留命令级溯源：

```yaml
metadata:
  acquisition:
    method: opencli
    source_channel_id: ansa-opencli
    tool_ref: opencli.ansa-news@0.1.0
    binding_id: ansa-politics-opencli
    args_digest: string
    tool_started_at: datetime
    tool_duration_ms: int
    exit_code: int
    output_format: json
    extraction_quality: high | medium | low
```

若 OpenCLI 用于增强已有 RSS/API 事件，应保留原始 `id`，只追加正文、作者、图片、引用链接等字段，并在 `processing_history` 中记录 `opencli-enrich`。

---

## 4. 适用模式

### 4.1 列表采集

用于从新闻列表、栏目页、搜索结果页抓取多条候选事件：

```yaml
id: ansa-politics-opencli
source_name: ANSA Politica
acquisition_method: opencli
acquisition_config:
  tool_ref: "opencli.ansa-news@0.1.0"
  binding_id: "ansa-politics-opencli"
  validated_args:
    section: "politica"
    format: "json"
  timeout_seconds: 40
  auth_required: false
field_mapping:
  items: "$.items[]"
  title_original: "$.title"
  source_url: "$.url"
  content_original: "$.summary"
  published_at: "$.published_at"
  author: "$.author"
  language: "it"
  target_id: "italy"
  source_country: "IT"
  involved_countries: ["IT"]
  content_type: "article"
```

### 4.2 全文增强

用于对 RSS/API 已发现的高价值事件补充正文：

```yaml
id: article-fulltext-opencli
acquisition_method: opencli
acquisition_config:
  tool_ref: "opencli.article-extract@0.1.0"
  binding_id: "article-fulltext-opencli"
  validated_args:
    url_ref: "NewsEvent.source_url"
    format: "json"
  timeout_seconds: 60
field_mapping:
  content_original: "$.content"
  author: "$.author"
  published_at: "$.published_at"
  metadata.fulltext.word_count: "$.word_count"
```

### 4.3 关键词搜索

用于补充 RSS 不覆盖的搜索场景：

```yaml
id: google-news-italy-china
source_name: Google News Italy China Search
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
  content_original: "$.snippet"
  source_name: "$.publisher"
  published_at: "$.published_at"
  language: "it"
  target_id: "italy"
  source_country: "$.publisher_country"
  involved_countries: ["IT", "CN"]
  content_type: "article"
```

---

## 5. Adapter 生命周期

### 5.1 创建

当某个 SourceChannel 无 RSS/API 或需要深度字段时，进入 adapter 创建流程：

```text
identify source gap
  -> explore website structure
  -> define output fields
  -> create OpenCLI adapter
  -> verify against sample pages
  -> register adapter_id and adapter_version
  -> add SourceChannel
```

创建阶段可以使用 LLM 或 Agent 辅助，但创建结果必须落成确定性命令和字段映射。

### 5.2 运行

运行阶段只允许执行已注册命令：

```text
load due SourceChannel
  -> run verify_tool_ref when health policy requires
  -> execute command with timeout
  -> parse output
  -> validate required fields
  -> map to NewsEvent
  -> update adapter health
```

### 5.3 修复

当 adapter 连续失败、字段缺失或输出结构变化时：

1. 标记 `adapter_status=needs_repair`。
2. 当前源降级到 fallback。
3. 写入 `logs/adapter-repair-queue.md`。
4. 由维护 Agent 或人工触发 OpenCLI autofix。
5. 修复后必须重新通过 sample 验证才能恢复生产。

### 5.4 淘汰

连续 30 天无有效产出的 adapter 标记为 dormant，不再参与高频心跳。若该源仍有编辑价值，转为低频人工检查或 RSS/API 替代。

---

## 6. 健康检查

每个 OpenCLI SourceChannel 都需要 health policy：

```yaml
health_policy:
  min_items_expected: 1
  max_empty_runs_before_alert: 3
  schema_required_fields:
    - title_original
    - source_url
    - content_original
  max_duration_seconds: 60
  repair_after_consecutive_failures: 3
```

健康状态写入 memory：

```yaml
OpenCLIAdapterHealth:
  adapter_id: opencli-ansa-news
  adapter_version: "0.1.0"
  status: active | degraded | needs_repair | dormant
  last_success_at: datetime?
  last_failure_at: datetime?
  consecutive_failures: int
  last_output_schema_hash: string
  last_error: string?
```

---

## 7. 失败模式与降级

| 失败模式 | 识别方式 | 策略 |
|----------|----------|------|
| 命令不存在 | exit code 或 shell error | 标记 adapter 配置错误，进入 repair queue |
| adapter 输出为空 | 成功退出但无 items | 累计 empty run，超过阈值告警 |
| 输出结构变化 | schema required fields 缺失 | 标记 needs_repair，降级 |
| 页面加载超时 | timeout | 重试一次，仍失败则等待下次心跳 |
| 登录态失效 | 输出提示登录或 401/403 | 标记 auth_required source degraded |
| 反爬或验证码 | 输出含 challenge/captcha | 停止自动重试，进入人工检查 |
| 内容质量低 | 正文过短或乱码 | 写入 extraction_quality=low，交给 filter 判定 |

降级顺序：

1. 同源 RSS/API。
2. 通用 web scraping。
3. 搜索引擎新闻结果。
4. 人工检查队列。

---

## 8. 安全与合规边界

OpenCLI 子 Skill 必须遵守：

1. 只采集公开可访问或已明确授权访问的内容。
2. 不保存账号密码、Cookie 或 token 到 NewsEvent 文件。
3. 不在正文中暴露本地 profile 名称以外的敏感凭据。
4. 对登录态来源保留 `auth_required=true` 和 `session_profile` 的非敏感标识。
5. 遇到验证码、封禁提示、访问限制时停止自动重试。

---

## 9. 验收标准

OpenCLI 子 Skill v1 通过以下场景验收：

1. 能执行至少一个列表采集命令并生成 `NewsEvent(stage=collected)`。
2. 能对一个 RSS/API 已发现事件进行全文增强。
3. 能记录命令、adapter 版本、退出码、耗时和字段映射结果。
4. 能识别输出字段缺失并把 adapter 标记为 degraded 或 needs_repair。
5. 能在命令失败时降级或写入人工检查队列。
6. 能保留所有来源链接，支持后续事实核查。

---

## 10. 与其他子 Skill 的接口

OpenCLI 子 Skill 可以被三种上游触发：

1. collect 心跳直接触发，用于无 RSS 的 SourceChannel。
2. filter/judge 阶段触发，用于高价值事件全文增强。
3. 社媒/KOL 子 Skill 触发，用于公开页面、搜索结果或跨平台身份补充。

无论触发来源如何，输出都必须回到 `NewsEvent` 和文件事件协议，不允许形成独立数据格式。
