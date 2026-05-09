# ADR-0011 — OpenCLI Baseline ToolManifest：12 条命令骨架

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过架构讨论确认）|
| **关联 ADR** | ADR-0008（系统级依赖原则）、ADR-0003（SandboxPolicy 错误枚举）|
| **关联文档** | [外部集成策略 §2.4](../external-integration-strategy.md)、[ToolManifest 规格](../brainstorming/ToolManifest与工具适配层规格.md) |

---

## 背景

ADR-0008 确定了 OpenCLI 作为系统级依赖、通过 `ToolManifest` 包装调用的原则。  
本 ADR 记录 v1+ 阶段 OpenCLI ToolManifest 的具体 12 条命令骨架，作为 Phase 4 实现的起点。

---

## 决策

**在 Phase 4 实现时，按本 ADR 中的 12 条骨架定义创建 `config/toolmanifest/opencli-baseline.yaml`，所有条目与 ADR-0003 SandboxPolicy 错误映射对齐。**

### 设计规则

1. **退出码映射**：所有 OpenCLI 工具统一映射退出码到 `ToolRunResult.error.type`：
   - `66`（空结果）→ 非错误，记录 `result_empty`
   - `69`（浏览器未连接）→ `browser_unavailable`
   - `77`（需要登录）→ `auth_required`
   - `1`（一般错误）→ `tool_error`
   - `2`（参数无效）→ `args_invalid`

2. **rate_limit 规则**：每个工具定义 `rate_limit.max_calls_per_hour`，防止 sandbox 预算超支

3. **session_profile_required**：需要登录态的工具设置 `permissions.browser.session_profile_required=true`

4. **网络许可**：每个工具只允许访问其实际需要的主机（最小权限原则）

---

### 12 条命令骨架

```yaml
# config/toolmanifest/opencli-baseline.yaml
# 版本基线：OpenCLI >= 1.7.14
# ADR: ADR-0011

tools:

  - tool_id: opencli.hackernews.top
    display_name: "Hacker News 热榜"
    executable: opencli
    argv_template: ["hackernews", "top", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      n:
        type: integer
        default: 30
        min: 1
        max: 100
    output_schema: {items: [{id, title, url, score, comments}]}
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["news.ycombinator.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 12
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
    phase: "Phase 4"

  - tool_id: opencli.hackernews.search
    display_name: "Hacker News 搜索"
    executable: opencli
    argv_template: ["hackernews", "search", "{q}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
      n:
        type: integer
        default: 20
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["news.ycombinator.com", "hn.algolia.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 20
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
      2: args_invalid
    phase: "Phase 4"

  - tool_id: opencli.twitter.trending
    display_name: "Twitter 趋势话题"
    executable: opencli
    argv_template: ["twitter", "trending", "--locale", "{locale}", "-f", "json"]
    parameters_schema:
      locale:
        type: string
        default: "it"
        enum: ["it", "en", "zh"]
    permissions:
      risk_level: medium
      network:
        allowed_hosts: ["twitter.com", "x.com", "api.twitter.com"]
      browser:
        session_profile_required: true
      credentials:
        required: ["TWITTER_SESSION_PROFILE"]
    rate_limit:
      max_calls_per_hour: 4
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      77: auth_required
      1: tool_error
    phase: "Phase 4"
    notes: "需要提前配置 Chrome profile 登录态，退出码 77 触发 sandbox violation"

  - tool_id: opencli.twitter.search
    display_name: "Twitter 关键词搜索"
    executable: opencli
    argv_template: ["twitter", "search", "{q}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
      n:
        type: integer
        default: 20
    permissions:
      risk_level: medium
      network:
        allowed_hosts: ["twitter.com", "x.com", "api.twitter.com"]
      browser:
        session_profile_required: true
      credentials:
        required: ["TWITTER_SESSION_PROFILE"]
    rate_limit:
      max_calls_per_hour: 10
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      77: auth_required
      1: tool_error
      2: args_invalid
    phase: "Phase 4"

  - tool_id: opencli.reddit.hot
    display_name: "Reddit 热帖"
    executable: opencli
    argv_template: ["reddit", "hot", "--subreddit", "{r}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      r:
        type: string
        required: true
        examples: ["italy", "europe", "geopolitics", "worldnews"]
      n:
        type: integer
        default: 25
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["reddit.com", "www.reddit.com", "oauth.reddit.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 12
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
      2: args_invalid
    phase: "Phase 4"

  - tool_id: opencli.reddit.search
    display_name: "Reddit 搜索"
    executable: opencli
    argv_template: ["reddit", "search", "{q}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
      n:
        type: integer
        default: 20
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["reddit.com", "www.reddit.com", "oauth.reddit.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 15
    exit_code_mapping:
      66: result_empty
      1: tool_error
      2: args_invalid
    phase: "Phase 4"

  - tool_id: opencli.google-scholar.search
    display_name: "Google Scholar 学术搜索"
    executable: opencli
    argv_template: ["google-scholar", "search", "{q}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
      n:
        type: integer
        default: 10
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["scholar.google.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 6
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
      2: args_invalid
    phase: "Phase 4"

  - tool_id: opencli.gov-policy.search
    display_name: "意大利政府政策公告搜索"
    executable: opencli
    argv_template: ["gov-policy", "search", "{q}", "--country", "it", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["www.governo.it", "www.parlamento.it", "eur-lex.europa.eu"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 10
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
    phase: "Phase 4"

  - tool_id: opencli.gov-policy.recent
    display_name: "意大利政府近期政策动态"
    executable: opencli
    argv_template: ["gov-policy", "recent", "--country", "it", "--days", "{days}", "-f", "json"]
    parameters_schema:
      days:
        type: integer
        default: 7
        max: 30
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["www.governo.it", "www.parlamento.it"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 8
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
    phase: "Phase 4"

  - tool_id: opencli.zhihu.hot
    display_name: "知乎热榜（中文涉华视角）"
    executable: opencli
    argv_template: ["zhihu", "hot", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      n:
        type: integer
        default: 20
    permissions:
      risk_level: low
      network:
        allowed_hosts: ["www.zhihu.com", "api.zhihu.com"]
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 6
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      1: tool_error
    phase: "Phase 4"
    notes: "用于观察中文视角的意大利/欧洲舆论，支持 china_relevance 分析"

  - tool_id: opencli.weixin.search
    display_name: "微信公众号搜索"
    executable: opencli
    argv_template: ["weixin", "search", "{q}", "--limit", "{n}", "-f", "json"]
    parameters_schema:
      q:
        type: string
        required: true
      n:
        type: integer
        default: 10
    permissions:
      risk_level: high
      network:
        allowed_hosts: ["mp.weixin.qq.com", "weixin.qq.com"]
      browser:
        session_profile_required: true
      credentials:
        required: ["WEIXIN_SESSION_PROFILE"]
    rate_limit:
      max_calls_per_hour: 3
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      77: auth_required
      1: tool_error
    phase: "Phase 6"
    notes: "需要微信登录态，高风险；Phase 6 社媒实验通道"

  - tool_id: opencli.external.custom
    display_name: "自定义外部工具包装"
    executable: opencli
    argv_template: ["external", "{name}", "{args}"]
    parameters_schema:
      name:
        type: string
        required: true
        description: "外部工具名称，需在 config/external-tools/ 中注册"
      args:
        type: string
        default: ""
    permissions:
      risk_level: medium
      network:
        allowed_hosts: []  # 由具体工具注册时指定
      browser:
        session_profile_required: false
    rate_limit:
      max_calls_per_hour: 20
    exit_code_mapping:
      66: result_empty
      69: browser_unavailable
      77: auth_required
      1: tool_error
      2: args_invalid
    phase: "Phase 4+"
    notes: "用于包装 News Sentry 内部自定义脚本，需要在单独注册文件中声明网络许可"
```

---

## 后果

**正面影响：**
- Phase 4 实现者有清晰的 12 条命令骨架可直接落地
- 退出码映射统一，与 ADR-0003 错误枚举完全对齐
- 最小权限原则：每个工具只允许访问其实际需要的主机

**负面影响/约束：**
- `opencli.twitter.*` 和 `opencli.weixin.search` 需要 Chrome profile 配置，增加 setup 步骤
- `rate_limit` 数值是估算值，Phase 4 实测后可能需要调整（调整不需要新 ADR）
- OpenCLI 命令语法在 >=1.7.14 后可能有小幅变动，实现时须运行 `opencli doctor` 验证

---

## 升级与修改规则

- `rate_limit` 数值调整：直接修改 `config/toolmanifest/opencli-baseline.yaml`，不需要新 ADR
- 新增 OpenCLI 工具条目：追加到 manifest 文件，建议注释说明追加理由，不需要新 ADR
- OpenCLI 主版本升级（引入破坏性变更）：必须创建新 ADR 记录适配决策
- 修改 `permissions` 或 `exit_code_mapping` 枚举：需要引用本 ADR 并注明修改理由
