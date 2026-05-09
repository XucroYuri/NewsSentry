# SandboxPolicy 与执行权限规格

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 工程承接规格
> 上级文档: [通用内核与平台化架构 PRD](./通用内核与平台化架构PRD.md)

---

## 0. 定位

SandboxPolicy 定义 Agent Skill Pack 在长期心跳运行中可以做什么、不能做什么，以及如何审计。v1 不要求完整容器平台，但必须有最小可执行 enforcer，不能只停留在文档约束。

核心目标：

1. 防止 `SourceChannel` 或外部 Skill 绕过 ToolManifest 执行任意命令。
2. 限制文件、网络、浏览器 profile 和凭据访问。
3. 控制每次 bounded run 的执行预算。
4. 对工具、Provider 和登录态使用生成可追溯审计记录。
5. 遇到验证码、封禁、权限异常、未知 egress 时立即停止或转人工。

---

## 1. SandboxPolicy v1

```yaml
policy_id: "default-local-v1"
mode: enforce
default_action: deny

command_policy:
  allow_registered_tools_only: true
  shell_allowed: false
  require_argv_template: true
  deny_unregistered_executables: true

filesystem_policy:
  cwd_root: "/workspace/news-sentry"
  read_roots:
    - "config"
    - "memory"
    - "raw"
    - "evaluated"
  write_roots:
    - "raw"
    - "evaluated"
    - "drafts"
    - "archive"
    - "memory"
    - "logs"
  deny_patterns:
    - ".env"
    - "*.pem"
    - "id_rsa"
    - "cookies.sqlite"
    - "Login Data"

network_policy:
  default_egress: deny
  allow_from_tool_manifest: true
  record_hosts: true

browser_policy:
  allow_session_profile_ref: true
  expose_cookie_values: false
  stop_on_captcha: true
  stop_on_blocked: true
  stop_on_auth_error: true

budget_policy:
  max_run_seconds: 300
  max_tool_runs: 50
  max_network_requests: 200
  max_items_per_source: 50
  max_provider_cost: 5.00

audit_policy:
  record_tool_runs: true
  record_provider_usage: true
  record_files_written: true
  record_network_hosts: true
  redact_sensitive_values: true
```

---

## 2. 最小 Enforcer 流程

```text
before tool run
  -> resolve tool_ref from Tool Registry
  -> validate args against ToolManifest
  -> check command_policy
  -> check filesystem read/write roots
  -> check network allowed hosts
  -> check run budget
  -> render argv without shell
  -> execute with timeout
  -> record audit log
```

Provider 调用、文件写入和浏览器 session 使用也必须经过相同预算和审计路径。

---

## 3. 权限等级

| 等级 | 能力 | 示例 |
|------|------|------|
| `read_only` | 读取配置、memory、NewsEvent | filter 预览 |
| `write_events` | 写入 raw/evaluated/archive | RSS collector |
| `write_drafts` | 写入 drafts/reviewed | draft writer |
| `external_network` | 访问允许域名 | RSS/API/OpenCLI |
| `browser_session` | 引用授权浏览器 profile | 社媒/KOL 实验 |
| `provider_call` | 调用 AI Provider route | judge/draft |
| `manual_gate_required` | 必须人工确认 | 发布、登录态异常、矛盾来源 |

权限由 `SkillManifest` 和 `ToolManifest` 共同声明，运行时取更严格者。

---

## 4. 文件边界

默认允许写入：

```text
raw/
evaluated/
drafts/
reviewed/
archive/
memory/
logs/
```

默认拒绝读取或写出：

```text
.env
SSH keys
browser cookies
browser credential stores
API key files
private message exports
```

任何越界读写都应产生 `permission_denied`，并写入安全日志。

---

## 5. 网络边界

网络访问必须来源于 ToolManifest：

```yaml
permissions:
  network:
    allowed_hosts:
      - "www.ansa.it"
      - "www.fao.org"
```

未知 host 默认拒绝。若 v1 环境无法技术性阻断所有 egress，至少必须在 enforcer 中做预校验和审计记录，并把未知 host 标记为 policy violation。

---

## 6. 登录态边界

登录态能力只允许引用非敏感标识：

```yaml
session_profile_id: twitter-monitor-1
auth_owner: human-approved
risk_level: medium
```

禁止：

1. 把 cookie、token、密码写入 NewsEvent、frontmatter、logs。
2. 自动登录、自动刷新 session、自动处理验证码。
3. 采集私人消息、私密群组、非公开内容。
4. 自动关注、点赞、评论、转发或私信。

遇到以下信号必须停止：

1. captcha 或 challenge。
2. platform blocked。
3. auth expired。
4. permission denied。
5. unusual activity warning。

---

## 7. 审计日志

每次 run 至少写入：

```yaml
run_id: run-20260509-0800-it
skill_id: rss-api-collector
tool_ref: opencli.google-news@0.1.0
manifest_version: "1"
args_digest: string
started_at: datetime
duration_ms: int
exit_code: int?
files_written:
  - raw/ne-italy-ansa-20260509-a1b2c3d4.md
network_hosts:
  - www.ansa.it
provider_usage_ref: logs/provider-usage/run-20260509-0800-it.jsonl
policy_decision: allow | deny
policy_reason: string?
```

日志必须可供人工审阅，但不得包含敏感凭据。

---

## 8. 推迟到实验通道的能力

以下能力不得进入 Phase 1 生产路径：

1. 大规模社媒登录态/KOL 生产化。
2. 自动登录、刷新 session、处理验证码。
3. 私密群组、私人消息、非公开资料采集。
4. 自动关注、点赞、评论、转发、私信。
5. OpenCLI autofix 在生产心跳中自动改 adapter。
6. 未审计社区 Skill 直接安装运行。
7. 通用浏览器 Agent 全站自动操作。
8. 自动对外发布或推送。
9. AI 单独给出事实结论并进入发布。

---

## 9. 验收标准

1. 未注册 ToolManifest 的工具不能执行。
2. SourceChannel 无法通过配置直接传入任意 shell 命令。
3. 文件读写被限制在声明目录。
4. 网络 host 被校验和记录。
5. 每次工具运行、Provider 调用和登录态引用都有 audit record。
6. 登录态异常、验证码、封禁或权限异常会停止自动重试。
7. sandbox violation 进入日志和人工检查队列。

