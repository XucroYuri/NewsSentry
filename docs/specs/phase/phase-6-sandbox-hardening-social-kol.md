# Phase 6 — Sandbox Hardening + Social/KOL Experiment

> 详细 SPEC: 本文档
> 路线图: [docs/roadmap/development-plan.md §Phase-6](../../roadmap/development-plan.md)
> 横切组件矩阵: [docs/spec/README.md](README.md)
> ADR-0003: [SandboxPolicy write_roots 和错误枚举](../../adr/0003-sandbox-write-roots-and-error-enum.md)
> ADR-0011: [OpenCLI ToolManifest（含高风险工具）](../../adr/0011-opencli-baseline-toolmanifest.md)

---

## 1. 目标与出口标准

**目标：** 在 Phase 3 最小 sandbox enforcer 基础上强化完整权限模型；小规模接入社媒/KOL 实验通道（Twitter 公开账号、微信公众号搜索、知乎热榜），所有登录态使用必须经过 `session_profile` 治理和 `stop-on-risk` 保护。

**本 Phase 与 Phase 3 关系：** Phase 3 实现最小 enforcer 后，可在完成 Phase 4/5 之前提前做 Phase 6 的 sandbox 强化部分；社媒/KOL 实验通道必须等 Phase 4 Tool registry 就绪后才能接入。

**出口标准（进入 Phase 7 的前提）：**
- [ ] 社媒/KOL 实验运行时，所有 session profile 引用有 `auth_owner=human-approved`
- [ ] captcha/blocked/auth_error 信号触发立即停止并写入安全日志
- [ ] sandbox violation 进入人工检查队列（Phase 4 ReviewQueue），下次 run 时可查阅
- [ ] `memory/` 中 KOL state 记录可读，不含 cookie 或 token 值
- [ ] `SandboxEnforcer` 实现完整 ADR-0003 策略模型（命令/文件系统/网络/浏览器/预算 5 维度）
- [ ] 所有工具调用生成 audit log，格式符合 `schemas/sandbox-audit.schema.json`

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | 完整 `SandboxPolicy` 模型（command/network/browser/profile 四维权限） | 全量 KOL 生产化（v1 只做实验通道） |
| **IN** | `session_profile` 治理（`auth_owner=human-approved` 标记机制） | 自动登录、自动刷新 session |
| **IN** | `stop-on-risk` 机制（captcha/blocked/auth_error 触发立即停止） | 私密群组采集（永远不做） |
| **IN** | 社媒/KOL 实验通道（Twitter/X 公开账号、知乎热榜、微信公众号搜索） | 多账号 session 池 |
| **IN** | `KOLState` 记录（公开账号观察状态，不含 cookie/token） | 邮件/微信反向信源（Phase 6 不做） |
| **IN** | sandbox violation 进入 ReviewQueue（Phase 4 组件复用） | 自动外发功能（v1 永不做） |
| **IN** | 强化网络访问限制（从"记录"升级为"拦截"），支持 wildcard 匹配 | 社媒生产化通道 |
| **IN** | 完整 audit log 写入（每次工具调用一条记录） | Phase 5 AI Provider 的新路由 |

---

## 3. 横切组件章节

### 3.1 完整 SandboxPolicy 数据模型

- **接口**:
  ```python
  # src/news_sentry/core/sandbox.py（在 Phase 3 基础上扩展）
  from pydantic import BaseModel
  from typing import Literal

  class CommandPolicy(BaseModel):
      allowed_executables: list[str]      # 白名单可执行文件，如 ["opencli", "python"]
      blocked_patterns: list[str] = []    # Phase 6 新增：正则黑名单（如 "rm -rf"）
      deny_shell: bool = True             # 禁止 shell=True
      deny_env_passthrough: bool = True   # 不透传敏感环境变量（TOKEN/SECRET/PASSWORD）

  class NetworkPolicy(BaseModel):
      allowed_hosts: list[str]            # 白名单（支持 wildcard，如 "*.ansa.it"）
      blocked_hosts: list[str] = []       # 明确屏蔽列表
      deny_by_default: bool = True        # Phase 6 升级：默认拒绝未登记主机

  class BrowserPolicy(BaseModel):
      allow_browser: bool = False         # Phase 3 默认不允许
      allowed_profiles: list[str] = []   # 允许的 session profile ID 白名单
      require_auth_owner: bool = True     # 必须有 auth_owner=human-approved
      deny_incognito: bool = True         # 不允许隐身模式（难以审计）

  class ProfilePolicy(BaseModel):
      allow_session_profiles: bool = False
      profiles_dir: str | None = None    # SessionProfile 元数据目录（不含 cookie 值）
      max_profiles: int = 5              # 防止 session 池无限扩张

  class BudgetPolicy(BaseModel):
      max_provider_cost_usd: float = 1.0
      max_run_duration_seconds: int = 3600
      max_events_per_run: int = 500
      max_ai_calls_per_run: int = 200

  class StopOnRiskConfig(BaseModel):
      on_captcha: bool = True
      on_blocked: bool = True
      on_auth_error: bool = True
      on_sandbox_violation: bool = True
      on_deny: Literal["stop", "log_and_continue"] = "stop"

  class SandboxPolicy(BaseModel):
      policy_id: str
      write_roots: list[str]             # 允许写入的根目录（含 reviewed/ published/，ADR-0003）
      read_roots: list[str] = []         # Phase 6 新增：允许读取的额外目录
      command: CommandPolicy = CommandPolicy(allowed_executables=["opencli", "python"])
      network: NetworkPolicy = NetworkPolicy(allowed_hosts=[], deny_by_default=True)
      browser: BrowserPolicy = BrowserPolicy()
      profile: ProfilePolicy = ProfilePolicy()
      budget: BudgetPolicy = BudgetPolicy()
      stop_on_risk: StopOnRiskConfig = StopOnRiskConfig()
      audit_log_enabled: bool = True
  ```

- **Phase 3 → Phase 6 升级对比**:

  | 检查维度 | Phase 3 实现 | Phase 6 完整实现 |
  |---------|------------|----------------|
  | 命令白名单 | ✅ 实现 | ✅ + blocked_patterns 正则 |
  | 文件系统写边界 | ✅ 实现 | ✅ + read_roots |
  | 网络主机 | 📝 仅记录 | 🔒 deny_by_default 拦截，wildcard 匹配 |
  | 浏览器 session | ❌ 未实现 | 🔒 profile 白名单 + auth_owner 验证 |
  | 预算限制 | 部分实现 | ✅ 全维度（时长/事件数/AI 调用数） |
  | stop-on-risk | ❌ 未实现 | 🛑 captcha/blocked/auth_error 自动停止 |
  | 敏感数据扫描 | ❌ 未实现 | 🔍 cookie/token/password 关键词检测 |

### 3.2 SandboxEnforcer（Phase 6 完整实现）

- **接口**（在 Phase 3 基础上新增）:
  ```python
  # src/news_sentry/core/sandbox.py

  class SandboxDecision(BaseModel):
      verdict: Literal["allow", "deny"]
      check_dimension: str       # "command" | "filesystem" | "network" | "browser" | "budget"
      reason: str | None = None
      policy_ref: str            # 触发的 policy 字段路径

  class SandboxAuditRecord(BaseModel):
      timestamp: datetime
      run_id: str
      tool_id: str | None
      decision: Literal["allow", "deny"]
      check_dimension: str
      args_summary: dict          # 去敏感化的参数摘要（不含实际 token/cookie）
      result_exit_code: int | None
      duration_ms: int | None

  class SandboxEnforcer:
      def __init__(self, policy: SandboxPolicy, audit_log_path: Path) -> None: ...

      # --- Phase 3 已有 ---
      def check_tool_allowed(self, tool_id: str) -> None: ...
      def check_write_path(self, path: Path) -> None: ...
      def check_budget(self, cost_usd: float) -> None: ...

      # --- Phase 6 新增 ---
      def check_network_host(self, host: str, tool_id: str) -> None:
          """
          Phase 6：从记录升级为拦截。
          支持 wildcard：allowed_hosts 中 "*.ansa.it" 匹配 "www.ansa.it"。
          不在白名单 → raise SandboxViolationError，写 audit log。
          """
          ...

      def check_browser_session(self, profile_id: str, tool_id: str) -> None:
          """
          验证 browser session profile 合法：
          1. profile_id 在 allowed_profiles 白名单中
          2. 对应 profile 元数据文件有 auth_owner=human-approved
          3. ProfilePolicy.allow_session_profiles=True（否则拒绝所有 session）
          """
          ...

      def check_stop_on_risk(self, signal: str, tool_id: str, run_id: str) -> None:
          """
          signal: "captcha" | "blocked" | "auth_error" | "sandbox_violation"
          stop_on_risk 对应字段为 True → write_security_log() + raise StopOnRiskError
          """
          ...

      def check_sensitive_data(self, content: str, context: str) -> None:
          """
          扫描文本是否含敏感数据关键词：
          正则匹配 bearer\s+[a-zA-Z0-9._-]+、set-cookie:、passwd=、Authorization:
          匹配 → SandboxViolationError，不允许该内容写入任何文件
          """
          ...

      def audit_tool_call(
          self, tool_id: str, decision: SandboxDecision, result_exit_code: int | None
      ) -> None:
          """每次工具调用（无论 allow/deny）写一条 audit log 记录"""
          ...

      def write_security_log(
          self, violation_type: str, detail: str, run_id: str
      ) -> None:
          """追加写入 memory/security-log.yaml，不覆盖历史"""
          ...
  ```

- **Audit log 格式** (`data/logs/tool-audit-{run_id}.jsonl`):
  ```jsonc
  // 每行一个 JSON 对象
  {
    "timestamp": "2026-05-09T10:00:00Z",
    "run_id": "run-abc123def456",
    "tool_id": "opencli.hackernews.top",
    "decision": "allow",
    "check_dimension": "network",
    "args_summary": {"host": "news.ycombinator.com", "n": 30},
    "result_exit_code": 0,
    "duration_ms": 450
  }
  {
    "timestamp": "2026-05-09T10:00:05Z",
    "run_id": "run-abc123def456",
    "tool_id": "opencli.weixin.search",
    "decision": "deny",
    "check_dimension": "browser",
    "args_summary": {"q": "[masked]"},
    "reason": "session_profile 'weixin-default' not in allowed_profiles",
    "result_exit_code": null,
    "duration_ms": 0
  }
  ```

### 3.3 SessionProfile 治理

- **接口**:
  ```python
  # src/news_sentry/core/session_profile.py

  class SessionProfile(BaseModel):
      """
      SessionProfile 元数据文件（存入 memory/session-profiles/）。
      严格约束：不存储 cookie/token/password 字面值。
      实际 Chrome profile 目录通过 profile_path 引用，不入 git。
      """
      profile_id: str
      display_name: str
      platform: str             # "twitter" | "weixin" | "zhihu" | ...
      auth_owner: str           # 必须是 "human-approved"（非系统可自动设置）
      approved_by: str          # 审批人标识
      approved_at: datetime
      account_type: str         # "public-account" | "personal-account"
      risk_level: str           # "low" | "medium" | "high"
      profile_path: str         # Chrome profile 路径，.gitignore 排除
      notes: str = ""
      # 显式禁止的字段（Pydantic validator 检测）:
      # cookie, token, password, session_key, access_token 均不允许存在

  def load_session_profiles(profiles_dir: Path) -> dict[str, SessionProfile]:
      """从 memory/session-profiles/*.yaml 加载所有 profile 元数据"""
      ...

  def validate_no_sensitive_data(profile: SessionProfile) -> None:
      """
      确认 SessionProfile 对象的所有字段不含敏感数据关键词。
      若检测到 cookie/token/bearer/password 则抛出 ConfigValidationError。
      """
      ...
  ```

- **SessionProfile 文件示意** (`memory/session-profiles/twitter-italia.yaml`):
  ```yaml
  profile_id: twitter-italia-public
  display_name: "Twitter Italy 公开账号观察"
  platform: twitter
  auth_owner: human-approved       # 必须是此固定值，不能是 auto/system
  approved_by: "project-owner-2026-05-09"
  approved_at: "2026-05-09T00:00:00Z"
  account_type: public-account
  risk_level: medium
  profile_path: "~/.chrome-profiles/twitter-italia"  # 不入 git（.gitignore 排除）
  notes: "仅用于观察公开意大利账号趋势，不发布内容，不私信"
  # cookie/session token 存放在 profile_path 目录，不在本文件中
  ```

### 3.4 KOLState 记录

- **接口**:
  ```python
  # src/news_sentry/core/kol_state.py

  class KOLEntry(BaseModel):
      """
      KOL 实体记录（公开账号信息，不含私密数据）。
      存入 memory/kol-state.yaml。
      """
      kol_id: str                    # 如 "twitter:giorgiaMeloni"
      platform: str                  # "twitter" | "zhihu" | ...
      display_name: str
      account_url: str               # 公开主页 URL
      first_observed_at: datetime
      last_active_at: datetime | None
      follower_count_approx: int | None  # 近似值，公开可见，允许 None
      relevance_tags: list[str] = []     # 如 ["politics", "italy-pm"]
      last_content_sample: str | None = None  # 最近一条公开内容摘要（≤ 200 字）
      china_relevance_score: int | None = None  # 0–100，是否涉及对华议题
      observation_enabled: bool = True
      observation_channel: str = "kol-experiment"  # 标记来源通道

  def load_kol_state(memory_root: Path) -> dict[str, KOLEntry]: ...
  def update_kol_state(kol_id: str, update: dict, memory_root: Path) -> None: ...
  ```

### 3.5 社媒/KOL 实验通道

- **接口（stub，Phase 6 实现）**:
  ```python
  # src/news_sentry/skills/social_kol_collector.py

  class SocialKOLCollector:
      """
      Phase 6 社媒/KOL 实验采集通道。
      只在 kol-experiment sandbox profile 下运行。
      产出写入独立子目录（data/raw/kol/），不混入主链路 raw/。
      """
      def __init__(
          self,
          registry: ToolManifestRegistry,
          sandbox: SandboxEnforcer,
          kol_state: dict[str, KOLEntry],
      ) -> None:
          if sandbox.policy.policy_id != "kol-experiment":
              raise SandboxViolationError("SocialKOLCollector 只允许在 kol-experiment sandbox 下运行")
          ...

      def collect_twitter_trends(
          self, locale: str, context: PipelineContext
      ) -> list[NewsEvent]:
          """调用 opencli.twitter.trending，产出 NewsEvent 列表"""
          ...

      def collect_zhihu_hot(
          self, context: PipelineContext
      ) -> list[NewsEvent]:
          """调用 opencli.zhihu.hot，产出 NewsEvent 列表"""
          ...

      def collect_weixin_search(
          self, query: str, context: PipelineContext
      ) -> list[NewsEvent]:
          """
          调用 opencli.weixin.search。
          高风险：需要 session_profile，退出码 77 触发 stop-on-risk。
          Phase 6 只做结构，需要人工配置 session profile 才能实际运行。
          """
          ...
  ```

- **KOL 实验产出隔离**：
  ```
  data/
  ├── raw/                          # 主链路（RSS/API/OpenCLI）
  │   └── ne-italy-ansa-*.md
  └── raw/kol/                      # 社媒实验通道（独立子目录）
      └── ne-italy-kol-*.md         # metadata.acquisition.channel: "kol-experiment"
  ```

---

## 4. 配置契约

| 配置文件 | 用途 | 说明 |
|--------|------|------|
| `config/sandbox/full.yaml` | Phase 6 完整 SandboxPolicy（含 browser + profile） | 非社媒场景默认用此 |
| `config/sandbox/kol-experiment.yaml` | 社媒实验专用（更严格 stop-on-risk，独立 profiles） | 社媒通道专用 |
| `memory/session-profiles/` | SessionProfile 元数据目录（不含 cookie） | 手动创建，.gitignore 排除 profile_path |
| `memory/kol-state.yaml` | KOL 实体状态记录 | 仅公开信息，无 cookie/token |
| `memory/security-log.yaml` | sandbox 违规安全日志 | 追加写入，不覆盖 |
| `data/logs/tool-audit-{run_id}.jsonl` | 完整工具调用 audit log | 每次 run 产出独立文件 |

**kol-experiment.yaml 示意**:
```yaml
policy_id: kol-experiment
write_roots:
  - data/raw/kol           # 仅限 KOL 子目录
  - data/memory
  - data/logs

command:
  allowed_executables: [opencli]  # 比 full.yaml 更严格，不允许 python 脚本
  deny_shell: true
  deny_env_passthrough: true

network:
  allowed_hosts:
    - "twitter.com"
    - "x.com"
    - "www.zhihu.com"
    - "mp.weixin.qq.com"
  deny_by_default: true

browser:
  allow_browser: true
  allowed_profiles: [twitter-italia-public, zhihu-public]
  require_auth_owner: true
  deny_incognito: true

profile:
  allow_session_profiles: true
  profiles_dir: memory/session-profiles
  max_profiles: 3

budget:
  max_provider_cost_usd: 0.0  # KOL 实验不调用 AI
  max_run_duration_seconds: 1800
  max_events_per_run: 100

stop_on_risk:
  on_captcha: true
  on_blocked: true
  on_auth_error: true
  on_sandbox_violation: true
  on_deny: stop              # 实验通道更严格：任何拒绝直接停止

audit_log_enabled: true
```

---

## 5. 测试策略

| 测试类型 | 目标 | 工具 | 优先级 |
|---------|------|------|-------|
| 单元测试 | `check_network_host()` 拦截未授权主机，wildcard 匹配正确 | pytest | P0 |
| 单元测试 | `check_browser_session()` 拒绝无 auth_owner 的 profile | pytest | P0 |
| 单元测试 | `check_stop_on_risk("captcha", ...)` 触发 StopOnRiskError | pytest | P0 |
| 单元测试 | `check_sensitive_data()` 检测 cookie/bearer/token 关键词 | pytest | P0 |
| 单元测试 | wildcard 匹配：`*.ansa.it` 匹配 `www.ansa.it`，不匹配 `evil.it` | pytest | P0 |
| 合约测试 | `SessionProfile` 字段中无 cookie/token 字面值（Pydantic validator） | pytest | P0 |
| 合约测试 | `KOLEntry.last_content_sample` 长度限制 ≤ 200 字 | pytest | P0 |
| 合约测试 | `config/sandbox/*.yaml` 通过 sandboxpolicy schema 校验 | jsonschema | P0 |
| 集成测试 | 社媒工具 exit_code=77 触发 stop-on-risk，写安全日志 | pytest + mock | P1 |
| 集成测试 | `SocialKOLCollector` 在非 kol-experiment sandbox 下抛 SandboxViolationError | pytest | P1 |
| 集成测试 | `memory/security-log.yaml` 在 violation 后追加记录，不覆盖历史 | pytest | P1 |
| 回归测试 | Phase 3-5 全部单元测试在强化 sandbox 下通过（无回归） | pytest（全量） | P0 |
| 安全扫描 | `memory/session-profiles/*.yaml` 中无 cookie/Set-Cookie/Bearer 字段 | CI rg 扫描 | P0 |
| 安全扫描 | `data/logs/` 中 audit log 去敏感化（无实际 session key 值） | CI 抽样扫描 | P1 |

---

## 6. 验收清单

### SandboxPolicy 强化
- [ ] `config/sandbox/full.yaml` 存在，含 command/network/browser/profile/stop_on_risk 五键
- [ ] `write_roots` 包含 `data/reviewed/` 和 `data/published/`（ADR-0003 要求）
- [ ] `SandboxEnforcer.check_network_host()` 在 deny_by_default=true 时拦截未授权主机（非仅记录）
- [ ] wildcard 主机匹配：`*.ansa.it` 允许 `www.ansa.it`，拒绝 `evil.com`
- [ ] `SandboxEnforcer` 的所有 5 个 check_* 方法均为完整实现（非 stub）

### Audit Log
- [ ] 每次工具调用（allow 或 deny）产生一条 audit log 记录
- [ ] DENY 记录含 `check_dimension` 和 `reason` 字段
- [ ] Audit log 通过 `schemas/sandbox-audit.schema.json` 格式校验
- [ ] Audit log 中无 session token/cookie 字面值（去敏感化）

### SessionProfile 治理
- [ ] 所有 session profile 元数据文件有 `auth_owner: human-approved`
- [ ] 实际 Chrome profile 目录在 `.gitignore` 中（`profile_path` 指向的目录不入 git）
- [ ] `validate_no_sensitive_data()` 通过所有 profile 元数据文件扫描
- [ ] `kol-experiment` sandbox 的 `allowed_profiles` 不超过 3 个

### stop-on-risk 机制
- [ ] captcha 信号触发立即停止，写入 `memory/security-log.yaml`
- [ ] blocked 信号触发立即停止，信源标记为 `source_health=blocked`
- [ ] auth_error 信号触发 stop-on-risk，进入 ReviewQueue，**不自动重试**

### KOL 实验通道
- [ ] KOL 实验 run 使用 `config/sandbox/kol-experiment.yaml`（独立沙箱）
- [ ] KOL 产出写入 `data/raw/kol/`，不混入 `data/raw/`（主链路隔离）
- [ ] `memory/kol-state.yaml` 仅存公开字段，无 cookie/token
- [ ] `SocialKOLCollector` 在非 kol-experiment sandbox 下抛异常（安全门）

### 合规
- [ ] 社媒/KOL 实验不发布内容、不私信
- [ ] security-log.yaml 追加写入，不覆盖旧记录
- [ ] CI 中有 `memory/` 目录敏感词扫描脚本

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| 社媒平台封禁实验账号 | 高 | 中 | KOL 通道默认 disabled，需显式配置；封禁后标记 `source_health=blocked`，停止重试 |
| Chrome profile 路径意外入 git | 中 | 极高 | `.gitignore` 规则；pre-commit hook 扫描 `Login Data`、`*.profile/`、`Cookies` 文件 |
| stop-on-risk 误触发，正常采集频繁中断 | 中 | 中 | 非社媒 run 使用 `full.yaml`（on_deny=stop），非 `kol-experiment.yaml`；可配置 `on_deny: log_and_continue` 用于开发调试 |
| audit log 意外记录了 session 内容 | 低 | 高 | `args_summary` 字段做去敏化（不记录 query 参数原文，只记录键名和长度）；`check_sensitive_data()` 扫描 audit log 内容 |
| 社媒实验通道误用为生产主通道 | 低 | 高 | `SocialKOLCollector` 硬检查 sandbox profile_id；kol-experiment.yaml `max_events_per_run=100` 物理限制 |
| sandbox 强化导致 Phase 3-5 现有 Skill 无法运行 | 中 | 高 | Phase 6 开始前运行全量回归测试；`full.yaml` 的 `allowed_hosts` 从现有 ToolManifest 自动导入 |

---

## 附：SandboxPolicy 权限演进

```
┌─────────────────────────────────────────────────────────┐
│                  SandboxPolicy 权限演进                   │
├──────────┬───────────────────────────────────────────────┤
│ Phase 3  │  最小 enforcer                                 │
│          │  ✅ 工具白名单检查                               │
│          │  ✅ 写路径检查                                   │
│          │  ✅ 预算检查（基础版）                            │
│          │  📝 网络访问：仅记录（不拦截）                    │
├──────────┼───────────────────────────────────────────────┤
│ Phase 6  │  完整 SandboxPolicy                            │
│          │  ✅ Phase 3 所有功能                             │
│          │  🔒 网络访问：deny_by_default 拦截 + wildcard    │
│          │  🔒 browser 权限：require_auth_owner            │
│          │  🔒 session_profile 治理（auth_owner 标记）      │
│          │  🛑 stop-on-risk：captcha/blocked/auth_error    │
│          │  🔍 敏感数据扫描（cookie/token/password 检测）   │
│          │  📋 完整 audit log（每次工具调用一条记录）        │
└──────────┴───────────────────────────────────────────────┘

社媒/KOL 实验通道专用隔离
┌─────────────────────────────────────────────────────────┐
│  kol-experiment sandbox（比 full.yaml 更严格）            │
│  • write_roots: 仅限 data/raw/kol/ 和 memory/           │
│  • allowed_executables: 仅 opencli（不含 python）         │
│  • allowed_hosts: 仅 twitter.com / zhihu.com / wx.qq.com │
│  • stop_on_risk.on_deny: stop（不做 log_and_continue）   │
│  • max_events_per_run: 100（实验限额）                   │
└─────────────────────────────────────────────────────────┘
```
