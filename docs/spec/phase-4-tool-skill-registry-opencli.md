# Phase 4 — Tool/Skill Registry + OpenCLI

> 详细 SPEC: 本文档  
> 路线图: [docs/development-plan.md §Phase-4](../development-plan.md)  
> 横切组件矩阵: [docs/spec/README.md](README.md)  
> ADR-0008: [外部依赖 install-not-vendor 原则](../adr/0008-external-deps-install-not-vendor.md)  
> ADR-0011: [OpenCLI baseline ToolManifest 12 条](../adr/0011-opencli-baseline-toolmanifest.md)

---

## 1. 目标与出口标准

**目标：** 工具和子 Skill 可注册、可选择、可降级；OpenCLI 通过统一接入接入 pipeline，作为 RSS/API 之外的第三种采集通道。所有工具调用必须经过 `ToolManifest` 注册，不允许直接 shell 调用。

**出口标准（进入 Phase 5 的前提）：**
- [ ] 一个 OpenCLI 工具可通过 `tool_ref + binding_id + validated_args` 调用并产出 `NewsEvent`
- [ ] `SourceChannel` 配置中不包含任意 shell 命令（符合 ADR-0008）
- [ ] `ToolManifest` 注册失败（tool_not_found）写入标准 `error.type`
- [ ] source health 追踪工具失败率和最近健康状态
- [ ] ADR-0011 12 条 OpenCLI baseline ToolManifest 落地到 `config/toolmanifest/opencli-baseline.yaml`
- [ ] 所有 OpenCLI 工具退出码按 ADR-0011 §退出码映射对齐 `ToolRunResult.error.type`
- [ ] 无任何 `SourceChannel` 配置包含 fork/vendor/submodule 引用（ADR-0008）

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | `SkillManifestRegistry`（注册、查询、降级选择） | 社媒登录态（Phase 6） |
| **IN** | `ToolManifestRegistry`（注册、健康检查、能力声明） | AI Provider 路由（Phase 5） |
| **IN** | OpenCLI Tool Adapter（`tool_ref + binding_id + validated_args`） | 第二国家配置（Phase 7） |
| **IN** | source health 和 adapter health 追踪 | 模型微调 |
| **IN** | 手动检查队列（sandbox violation 进入） | 全量 KOL 生产化 |
| **IN** | `config/toolmanifest/opencli-baseline.yaml`（12 条骨架） | 动态 registry 服务端 |
| **IN** | 退出码映射（ADR-0011 §退出码映射） | ClawHub 自动发布 |

---

## 3. 横切组件章节

### 3.1 SkillManifestRegistry

- **接口**:
  ```python
  # src/news_sentry/core/skill_registry.py
  from pathlib import Path
  from pydantic import BaseModel
  from typing import Literal

  class SkillManifest(BaseModel):
      skill_id: str
      version: str
      pipeline_stage: Literal["collect", "filter", "judge", "output"]
      display_name: str
      description: str
      entry_module: str         # Python import path，如 "news_sentry.skills.rss_collector"
      entry_class: str          # 如 "RSSCollector"
      input_schema_id: str | None = None
      output_schema_id: str | None = None
      requires_tools: list[str] = []   # 依赖的 tool_id 列表
      fallback_skill_id: str | None = None  # 降级目标

  class SkillManifestRegistry:
      """
      Skill 注册表：管理 pipeline 各阶段可用的 Skill 实现。
      支持多 Skill 同一 pipeline_stage 注册（如多个 collect Skill：RSS、API、OpenCLI）。
      """
      def __init__(self, manifests_dir: Path) -> None: ...

      def register(self, manifest: SkillManifest) -> None: ...

      def get_skills_for_stage(
          self, stage: str
      ) -> list[SkillManifest]: ...

      def get_fallback(
          self, skill_id: str
      ) -> SkillManifest | None: ...

      def health_check_all(self) -> dict[str, bool]: ...
  ```

- **数据流**:
  ```
  config/skillmanifest/*.yaml
        │
  SkillManifestRegistry.load_from_dir()
        │
  bounded_run() 查询当前 stage 的可用 Skill
        │
  实例化 Skill 类 → 执行 collect/filter/judge/output
  ```

- **错误处理**:
  - `skill_id` 不存在 → `SkillNotFoundError`，run 降级到 fallback_skill_id
  - 全部降级失败 → `exit_code=2`

### 3.2 ToolManifestRegistry

- **接口**:
  ```python
  # src/news_sentry/core/tool_registry.py
  from pathlib import Path
  from pydantic import BaseModel

  class ToolManifest(BaseModel):
      tool_id: str                    # 如 "opencli.hackernews.top"
      display_name: str
      executable: str                 # 如 "opencli"
      argv_template: list[str]        # 如 ["hackernews", "top", "--limit", "{n}"]
      parameters_schema: dict         # JSON Schema for parameters
      output_schema: dict | None      # 期望的输出结构
      permissions: dict               # risk_level, network, browser, credentials
      rate_limit: dict                # max_calls_per_hour
      exit_code_mapping: dict[int, str]  # 退出码 → ToolRunResult.error.type

  class ToolRunResult(BaseModel):
      tool_id: str
      success: bool
      stdout: str
      stderr: str
      exit_code: int
      error: ToolRunError | None = None
      items_returned: int = 0
      duration_seconds: float

  class ToolRunError(BaseModel):
      type: str   # "result_empty" | "browser_unavailable" | "auth_required" |
                  # "tool_error" | "args_invalid" | "tool_not_found" | "rate_limited"
      message: str

  class ToolManifestRegistry:
      def __init__(self, manifests_file: Path, sandbox: SandboxEnforcer) -> None: ...

      def get(self, tool_id: str) -> ToolManifest: ...

      def execute(
          self,
          tool_id: str,
          binding_id: str,          # 调用方标识（用于审计）
          validated_args: dict,     # 经过 parameters_schema 校验的参数
          context: PipelineContext,
      ) -> ToolRunResult: ...

      def health_check(self, tool_id: str) -> bool:
          """在 bounded run 前验证工具可用性（执行 --version 或简单调用）"""
          ...
  ```

- **数据流**:
  ```
  config/toolmanifest/opencli-baseline.yaml
        │
  ToolManifestRegistry.load()
        │
  OpenCLICollector.collect()
        │ tool_id + validated_args
        ▼
  ToolManifestRegistry.execute(tool_id, binding_id, validated_args)
        │
        ├─ SandboxEnforcer.check_tool_allowed(tool_id)
        ├─ 参数 validated_args schema 校验
        ├─ subprocess.run(argv) 或 shell=False 调用
        ├─ exit_code_mapping 翻译
        └─ ToolRunResult
  ```

- **错误处理**:
  - `tool_id` 未注册 → `ToolRunError(type="tool_not_found")`
  - 退出码按 ADR-0011 映射表处理
  - `exit_code=77`（auth_required）→ 触发 sandbox violation，进入人工检查队列
  - `rate_limit` 超出 → `ToolRunError(type="rate_limited")`，记录到 run log

### 3.3 OpenCLICollector

- **接口**:
  ```python
  # src/news_sentry/skills/opencli_collector.py
  from news_sentry.core.models import NewsEvent
  from news_sentry.core.config import SourceChannel
  from news_sentry.core.tool_registry import ToolManifestRegistry

  class OpenCLICollector:
      """
      通过 ToolManifestRegistry 调用 OpenCLI 工具采集新闻。
      遵守 ADR-0008（install-not-vendor）：不 fork、不 vendor OpenCLI。
      遵守 ADR-0011：工具调用通过 tool_ref + binding_id + validated_args。
      """
      def __init__(
          self,
          source: SourceChannel,
          registry: ToolManifestRegistry,
          sandbox: SandboxEnforcer,
      ) -> None: ...

      def collect(
          self,
          context: PipelineContext,
          since: datetime | None = None,
      ) -> list[NewsEvent]:
          """
          1. 从 source.tool_ref 获取 ToolManifest
          2. 构建 validated_args（含 source.binding_id 和 source.tool_args）
          3. 调用 registry.execute()
          4. 将 JSON 输出解析为 NewsEvent 列表
          """
          ...

      def _parse_tool_output(
          self, raw_json: str, tool_id: str, context: PipelineContext
      ) -> list[NewsEvent]: ...
  ```

### 3.4 人工检查队列

- **接口**:
  ```python
  # src/news_sentry/core/review_queue.py
  from pathlib import Path
  from dataclasses import dataclass

  class ReviewQueueItem(BaseModel):
      item_id: str
      created_at: datetime
      item_type: str               # "sandbox_violation" | "auth_required" | "low_quality"
      source_run_id: str
      detail: str
      event_id: str | None = None  # 关联的 NewsEvent id（如有）
      resolved: bool = False
      resolved_at: datetime | None = None

  class ReviewQueue:
      """
      写入 memory/review-queue.yaml。
      bounded run 开始时可查阅未解决项。
      """
      def __init__(self, memory_root: Path) -> None: ...

      def enqueue(self, item: ReviewQueueItem) -> None: ...
      def get_unresolved(self) -> list[ReviewQueueItem]: ...
      def resolve(self, item_id: str, note: str) -> None: ...
  ```

---

## 4. 配置契约

| 配置文件 | 用途 | 说明 |
|--------|------|------|
| `config/toolmanifest/opencli-baseline.yaml` | 12 条 ADR-0011 骨架 | Phase 4 创建，直接落地 ADR-0011 |
| `config/skillmanifest/phase3-skills.yaml` | Phase 3 Skill 清单 | RSSCollector、APICollector、RulesFilter |
| `config/skillmanifest/phase4-skills.yaml` | Phase 4 Skill 清单 | OpenCLICollector |
| `config/italy/sources/hn-top.yaml` | HN 热榜信源（OpenCLI 方式） | 含 `tool_ref: opencli.hackernews.top` |
| `memory/review-queue.yaml` | 人工检查队列 | 运行时写入 |

**OpenCLI SourceChannel 示意** (`config/italy/sources/hn-top.yaml`):
```yaml
source_id: hackernews-top
display_name: "Hacker News 热榜（OpenCLI）"
acquisition_method: opencli
tool_ref: opencli.hackernews.top
binding_id: "italy-hn-collect-v1"
tool_args:
  n: 30
enabled: true
credibility_score: 65
rate_limit_per_hour: 6    # 不超过 ToolManifest 的 max_calls_per_hour
```

---

## 5. 测试策略

| 测试类型 | 目标 | 工具 | 优先级 |
|---------|------|------|-------|
| 单元测试 | `ToolManifestRegistry.execute()` 退出码映射正确（ADR-0011 5 类退出码） | pytest | P0 |
| 单元测试 | `SkillManifestRegistry.get_fallback()` 降级链正确 | pytest | P0 |
| 合约测试 | `opencli-baseline.yaml` 每条 entry 通过 `tool-manifest.schema.json` 校验 | jsonschema | P0 |
| 合约测试 | OpenCLI 工具输出 JSON → `NewsEvent` 字段映射正确 | pytest | P0 |
| 集成测试 | `SourceChannel(acquisition_method=opencli)` 成功产出 NewsEvent | pytest + subprocess mock | P1 |
| 集成测试 | `auth_required` 退出码触发 sandbox violation，进入 review queue | pytest | P1 |
| 安全测试 | 任何 `SourceChannel` 配置不含 shell 命令（grep 扫描） | CI 脚本 | P0 |

---

## 6. 验收清单

### ToolManifest
- [ ] `config/toolmanifest/opencli-baseline.yaml` 存在，含 12 条工具定义
- [ ] 每条工具定义含 `tool_id`、`argv_template`、`parameters_schema`、`exit_code_mapping`
- [ ] 5 类退出码映射（66/69/77/1/2）全部出现在至少一条工具定义中
- [ ] `ToolManifestRegistry.get("opencli.hackernews.top")` 不抛异常

### OpenCLI 接入
- [ ] `OpenCLICollector` 可通过 `tool_ref + binding_id + validated_args` 调用工具
- [ ] 工具调用前经过 `SandboxEnforcer.check_tool_allowed()`
- [ ] `SourceChannel` 的 `tool_args` 经过 `parameters_schema` 校验后才传入 `argv_template`
- [ ] 无任何 `SourceChannel` YAML 含 `shell: true` 或 `command:` 直接字段

### 健康检查与降级
- [ ] bounded run 开始前对已注册工具执行 health check
- [ ] 工具 health check 失败时降级到 `fallback_skill_id`（如有），无则跳过该信源
- [ ] source health 记录工具失败率（`memory/source_health.yaml` 含 `last_tool_exit_code`）

### 人工检查队列
- [ ] `exit_code=77`（auth_required）触发 `ReviewQueue.enqueue()` 写入 review-queue.yaml
- [ ] `memory/review-queue.yaml` 中 item 含 `source_run_id`、`item_type`、`detail` 字段

### ADR 合规
- [ ] 无 OpenCLI fork/vendor/submodule（git status 检查）
- [ ] `pyproject.toml` 不含 opencli 本地路径依赖

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| OpenCLI adapter 与意大利网站结构频繁变化 | 高 | 中 | adapter health check 每次 run 前执行；失败降级到 RSS/API 同等信源 |
| OpenCLI 命令语法变更（版本升级） | 中 | 中 | `argv_template` 在 ToolManifest 中集中管理，升级只修改 YAML；`opencli --version` 版本检查 |
| `auth_required` 工具在 CI 环境无法测试 | 高 | 低 | mock subprocess 模拟退出码 77，不依赖真实登录态 |
| registry 中注册了高风险工具但 sandbox 未拦截 | 低 | 高 | SandboxEnforcer 在 execute() 中强制 check；`risk_level=high` 的工具需要 `session_profile_required=true` 才能执行，否则 sandbox violation |
| SkillManifest 降级链形成循环 | 低 | 低 | 注册时检测循环引用，检测到则 `SkillRegistryError` |
