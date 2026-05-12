# Phase 3 — Kernel MVP

> 详细 SPEC: 本文档
> 路线图: [docs/development-plan.md §Phase-3](../development-plan.md)
> 横切组件矩阵: [docs/spec/README.md](README.md)
> 口径基准: [docs/contracts-canonical.md](../contracts-canonical.md)

---

## 1. 目标与出口标准

**目标：** 实现意大利 reference package 的文件事件闭环：从 RSS/API 采集 → 规则过滤 → 文件写入 → run log / memory / source health 记录，配以最小 sandbox enforcer。产出的 `raw/` 和 `evaluated/` 事件满足 `contracts-canonical.md` 所有字段规范。

**本 Phase 是全项目最核心的实现 Phase，所有后续 Phase 均以此为基础扩展。**

**出口标准（进入 Phase 4 的前提）：**
- [ ] 一次 `python -m news_sentry.cli run --target italy --stage collect --profile local-workstation` 可稳定产出至少一个 `raw/ne-italy-*.md` 文件
- [ ] 文件 frontmatter 字段符合 `contracts-canonical.md §3`（id 格式正确）
- [ ] `pipeline_stage` 字段值为 `collected`（符合 `contracts-canonical.md §2`）
- [ ] 过滤后事件进入 `evaluated/`，被拒事件进入 `archive/`
- [ ] `logs/` 每次 run 产出 run log，含 `run_id`、`started_at`、`events_collected`、`events_filtered`
- [ ] `memory/` 更新 `known_item_ids`（用于去重）
- [ ] `memory/source_health.yaml` 记录每个信源的最近状态
- [ ] sandbox enforcer 拒绝未注册工具执行，违规写安全日志
- [ ] run 完成后正常退出，无无界 daemon 循环

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | 框架无关 bounded run lifecycle（加载配置 → 分阶段 → 退出） | OpenCLI 接入（Phase 4） |
| **IN** | ConfigLoader（TargetConfig + SourceChannel + FilterRules + SandboxPolicy 最小子集） | 社媒登录态（Phase 6） |
| **IN** | RSSCollector（feedparser 解析，多格式支持） | 动态 Skill registry（Phase 4） |
| **IN** | APICollector（HTTP GET/POST，JSON 响应解析） | 复杂 AI Provider 路由（Phase 5） |
| **IN** | RulesFilter（关键词、实体、来源可信度、去重） | 多 Provider 并发（Phase 5） |
| **IN** | ClassifierRules（L0–L3 规则引擎分类，写入 `metadata.classification`） | KOL 状态追踪（Phase 6） |
| **IN** | MarkdownWriter（raw/ / evaluated/ / archive/ 文件写入） | 自动外发（v1 永不做） |
| **IN** | RunLog（每次 run 的统计摘要 YAML） | 前端或可视化组件（ADR-0010） |
| **IN** | MemoryStore（known_item_ids 去重、source health 更新） | 数据库队列（v1 文件 memory 为主） |
| **IN** | 最小 SandboxEnforcer（命令白名单、文件边界、网络记录、预算、审计日志） | — |
| **IN** | 意大利 reference package 配置（target.yaml + 若干 sources/*.yaml） | — |

---

## 3. 横切组件章节

### 3.1 BoundedRun（核心 run lifecycle）

- **接口**:
  ```python
  # src/news_sentry/core/run.py
  import uuid
  from dataclasses import dataclass, field
  from datetime import datetime, timezone
  from pathlib import Path

  @dataclass
  class RunOptions:
      target_id: str           # 如 "italy"
      stage: str               # "collect" | "filter" | "judge" | "output"
      config_root: Path        # 配置根目录
      output_root: Path        # data/ 根目录
      run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
      dry_run: bool = False    # True 时不写入文件，仅打印

  @dataclass
  class RunSummary:
      run_id: str
      target_id: str
      stage: str
      started_at: datetime
      finished_at: datetime
      exit_code: int
      events_collected: int = 0
      events_passed_filter: int = 0
      events_archived: int = 0
      errors: list[str] = field(default_factory=list)

  def bounded_run(opts: RunOptions) -> RunSummary:
      """
      执行一次有界 run。
      - 加载配置
      - 按 stage 执行对应 Skill
      - 写入文件事件
      - 更新 memory
      - 写入 run log
      - 退出（不循环）
      """
      ...
  ```

- **数据流**:
  ```
  CLI/Adapter
      │ RunOptions
      ▼
  bounded_run()
      ├─ load_config(target_id, config_root)  → TargetConfig
      ├─ load_memory(output_root)             → MemoryState
      ├─ stage="collect" →
      │    ├─ for source in target.sources:
      │    │    CollectorAdapter.collect(source) → list[NewsEvent(pipeline_stage=collected)]
      │    │    SandboxEnforcer.check(event)
      │    │    MarkdownWriter.write_raw(event)
      │    └─ update_source_health(...)
      ├─ stage="filter" →
      │    ├─ for event in raw_events:
      │    │    RulesFilter.apply(event)    → FilterDecision
      │    │    ClassifierRules.classify(event) → metadata.classification
      │    │    if pass: write_evaluated() / if reject: write_archive()
      │    └─ update_known_ids(...)
      ├─ write_run_log(summary)
      └─ return RunSummary
  ```

- **错误处理**:
  - 单个信源失败不中断整体 run（记录错误，继续下一个）
  - 全部信源失败 → `exit_code=2`
  - sandbox 违规 → 立即终止，`exit_code=3`，写安全日志

### 3.2 ConfigLoader

- **接口**:
  ```python
  # src/news_sentry/core/config.py
  from pathlib import Path
  from pydantic import BaseModel, Field

  class SourceChannel(BaseModel):
      source_id: str
      display_name: str
      acquisition_method: str          # "rss" | "api" | "opencli" | "builtin_fallback"
      url: str | None = None           # RSS/API URL
      api_key_env: str | None = None   # 环境变量名（不存储实际 key）
      enabled: bool = True
      credibility_score: int = Field(ge=0, le=100, default=70)
      rate_limit_per_hour: int = 12
      timeout_seconds: int = 30

  class FilterRules(BaseModel):
      keywords_include: list[str] = []      # 至少匹配一个才通过
      keywords_exclude: list[str] = []      # 匹配任一则拒绝
      min_credibility: int = Field(ge=0, le=100, default=50)
      deduplicate: bool = True

  class TargetConfig(BaseModel):
      target_id: str
      display_name: str
      language_primary: str            # BCP-47，如 "it"
      language_secondary: str = "en"
      sources: list[SourceChannel] = []
      filter_rules: FilterRules = FilterRules()
      sandbox_policy_ref: str = "default"  # 引用 config/sandbox/ 中的文件名
      output_root_override: str | None = None  # 覆盖 profile 的 output_root

  def load_target_config(
      target_id: str,
      config_root: Path,
      profile_id: str = "local-workstation",
      profile_overrides: dict | None = None,
  ) -> TargetConfig:
      """
      按 ADR-0015 配置合并优先级加载目标配置：
      deployment profile → target config → source config → sandbox policy
      """
      ...
  ```

- **数据流**:
  ```
  config/{target_id}/target.yaml
  config/{target_id}/sources/*.yaml    ←──合并──→  TargetConfig（完整配置对象）
  config/sandbox/{policy_ref}.yaml
  config/profiles/{profile_id}.yaml    ←──决定 output_root 与 sandbox profile
  ```

- **错误处理**:
  - 配置文件缺失 → `ConfigLoadError`，run 以 `exit_code=2` 退出
  - 字段类型错误 → pydantic `ValidationError`，日志记录，run 退出
  - `api_key_env` 指向的环境变量不存在 → 信源标记为 disabled，记录警告

### 3.3 RSSCollector

- **接口**:
  ```python
  # src/news_sentry/skills/rss_collector.py
  from news_sentry.core.models import NewsEvent, AcquisitionInfo
  from news_sentry.core.config import SourceChannel

  class RSSCollector:
      def __init__(self, source: SourceChannel, sandbox: SandboxEnforcer) -> None: ...

      def collect(
          self,
          context: PipelineContext,
          since: datetime | None = None,
      ) -> list[NewsEvent]:
          """
          从 RSS feed 采集事件，返回 pipeline_stage=collected 的 NewsEvent 列表。
          - 支持 RSS 2.0、Atom 1.0、RDF 格式（feedparser 解析）
          - 标题机译写入 metadata.translation.title_pre（ADR-0004，Phase 3 可用 mock）
          - 确定性 id 生成：ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}
          """
          ...

      def _generate_id(
          self,
          target_id: str,
          source_id: str,
          url: str,
          published_at: datetime,
      ) -> str:
          """使用 SHA-256(url + yyyymmdd)[:8] 生成确定性 hash"""
          ...
  ```

- **数据流**:
  ```
  RSS URL
      │
  feedparser.parse(url)
      │
  [FeedEntry]
      │
  for entry:
      ├─ 生成确定性 id
      ├─ 语种检测（langdetect）→ language 字段
      ├─ 标题机译（mock 或 translate.fast）→ metadata.translation.title_pre
      └─ 构建 NewsEvent(pipeline_stage="collected", acquisition.method="rss")
  ```

- **错误处理**:
  - 网络超时（`timeout_seconds`）→ 记录 `source_health.last_error`，返回空列表
  - feedparser 解析失败 → 尝试 `acquisition.method=builtin_fallback`，记录到事件
  - 重复 id（在 `known_item_ids` 中）→ 跳过，不写文件

### 3.4 APICollector

- **接口**:
  ```python
  # src/news_sentry/skills/api_collector.py
  from news_sentry.core.models import NewsEvent
  from news_sentry.core.config import SourceChannel

  class APICollector:
      def __init__(self, source: SourceChannel, sandbox: SandboxEnforcer) -> None: ...

      def collect(
          self,
          context: PipelineContext,
          since: datetime | None = None,
      ) -> list[NewsEvent]:
          """
          从 HTTP API 采集事件。
          - 支持 GET / POST（根据 source.method 字段）
          - API key 从环境变量读取（source.api_key_env）
          - JSON 响应通过 source.response_mapping 映射到 NewsEvent 字段
          """
          ...
  ```

- **错误处理**: 同 RSSCollector；额外处理 4xx/5xx HTTP 错误码，401 → 标记 `auth_required`

### 3.5 RulesFilter

- **接口**:
  ```python
  # src/news_sentry/skills/filter.py
  from enum import Enum
  from dataclasses import dataclass

  class FilterVerdict(str, Enum):
      PASS = "pass"
      REJECT_KEYWORD = "reject_keyword"
      REJECT_CREDIBILITY = "reject_credibility"
      REJECT_DUPLICATE = "reject_duplicate"
      REJECT_LANGUAGE = "reject_language"

  @dataclass
  class FilterDecision:
      verdict: FilterVerdict
      reason: str
      matched_rules: list[str]    # 触发的规则描述

  class RulesFilter:
      def __init__(self, rules: FilterRules, memory: MemoryStore) -> None: ...

      def apply(self, event: NewsEvent, context: PipelineContext) -> FilterDecision:
          """
          按 FilterRules 对 NewsEvent 做决策：
          1. 去重检查（known_item_ids）
          2. 关键词过滤（支持意大利语 + 中文关键词，忽略大小写）
          3. 实体检查（人名/机构名，NLP 可选）
          4. 来源可信度检查（credibility_score >= min_credibility）
          返回 FilterDecision，不直接修改 event
          """
          ...
  ```

- **数据流**:
  ```
  NewsEvent(pipeline_stage=collected)
      │
  RulesFilter.apply()
      ├─ PASS  → event.pipeline_stage = "filtered" → write_evaluated()
      └─ REJECT → event.pipeline_stage = "filtered"
                  event.processing_history 追加 FilterRecord
                  write_archive(reason=verdict)
  ```

### 3.6 ClassifierRules

- **接口**:
  ```python
  # src/news_sentry/skills/classifier_rules.py
  from news_sentry.core.models import NewsEvent, ClassificationResult

  @dataclass
  class ClassificationResult:
      l0: str | None = None      # "politics" | "economy" | "society" | "culture" | ...
      l1: str | None = None      # L1 子主题
      l2: str | None = None      # L2 细分
      l3: str | None = None      # L3 叶节点（可选）
      country_axes: dict = None  # Italy-specific axes: {"region": ..., "coalition": ...}
      confidence: float = 0.0    # 0.0–1.0 规则引擎置信度
      method: str = "rules"      # "rules" | "llm" | "hybrid"

  class ClassifierRules:
      """
      Phase 3 规则引擎分类器（仅使用关键词/正则规则，无 LLM）。
      Phase 5 引入 LLM 分类器后作为 fallback 降级选项。
      分类结果写入 event.metadata.classification（ADR-0009）。
      """
      def __init__(self, rules_config_path: Path) -> None: ...

      def classify(self, event: NewsEvent) -> ClassificationResult:
          """
          按 config/classification-rules.yaml 的规则对 event 分类。
          - 关键词命中 → L0 分类
          - 子关键词命中 → L1/L2 分类
          - Italy country_axes：region（地区）、coalition（政治联盟）
          - 无命中返回 ClassificationResult(l0=None, confidence=0.0)
          """
          ...

      def apply_to_event(self, event: NewsEvent) -> NewsEvent:
          """
          调用 classify() 并将结果写入 event.metadata.classification，
          返回更新后的 event（不修改原对象，返回新实例）。
          """
          ...
  ```

### 3.7 MarkdownWriter

- **接口**:
  ```python
  # src/news_sentry/core/file_writer.py
  from pathlib import Path

  class MarkdownWriter:
      """
      将 NewsEvent 序列化为 Obsidian-friendly Markdown 文件。
      文件命名：{id}.md
      YAML frontmatter 包含所有 schema 字段。
      处理历史追加到 frontmatter processing_history 列表。
      """
      def __init__(self, output_root: Path) -> None: ...

      def write_raw(self, event: NewsEvent) -> Path:
          """写入 raw/{event.id}.md，pipeline_stage=collected"""
          ...

      def write_evaluated(self, event: NewsEvent) -> Path:
          """写入 evaluated/{event.id}.md，pipeline_stage=filtered"""
          ...

      def write_archive(self, event: NewsEvent, reason: str) -> Path:
          """写入 archive/{event.id}.md，记录 rejection reason"""
          ...

      def write_draft(self, event: NewsEvent) -> Path:
          """写入 drafts/{event.id}.md（Phase 3 基础版草稿）"""
          ...
  ```

- **数据流**:
  ```
  NewsEvent
      │
  MarkdownWriter.write_raw()
      │
  data/raw/ne-italy-ansa-20260509-a1b2c3d4.md
      ───────────────────────────────────────
      ---
      id: ne-italy-ansa-20260509-a1b2c3d4
      pipeline_stage: collected
      title: "Governo approva nuovo pacchetto economico"
      title_translated: null
      language: it
      source_id: ansa
      source_url: https://www.ansa.it/...
      published_at: "2026-05-09T08:30:00Z"
      collected_at: "2026-05-09T10:00:00Z"
      run_id: run-abc123def456
      news_value_score: null
      china_relevance: null
      metadata:
        translation:
          title_pre: "政府批准新经济方案"
        classification:
          l0: economy
          method: rules
      acquisition:
        method: rss
        feed_url: https://www.ansa.it/rss/...
      processing_history:
        - stage: collect
          at: "2026-05-09T10:00:01Z"
          by: RSSCollector@1.0
      ---
      <!-- 正文内容 -->
      ...
  ```

### 3.8 RunLog

- **接口**:
  ```python
  # src/news_sentry/core/run_log.py
  from dataclasses import dataclass, field
  from datetime import datetime
  from pathlib import Path

  @dataclass
  class RunLog:
      run_id: str
      target_id: str
      stage: str
      profile_id: str
      output_root: str  # 项目内路径使用 ./data 这类 portable 形式
      started_at: datetime
      finished_at: datetime
      exit_code: int
      events_collected: int = 0
      events_passed_filter: int = 0
      events_archived: int = 0
      source_results: dict = field(default_factory=dict)  # source_id → {collected, errors}
      errors_count: int = 0
      errors: list[dict] = field(default_factory=list)  # 顶层聚合，便于 automation 解析
      budget_used: dict = field(default_factory=dict)     # {"api_calls": n, "cost_usd": 0.0}

  def write_run_log(log: RunLog, output_root: Path) -> Path:
      """写入 data/logs/run-{run_id}.yaml"""
      ...
  ```

### 3.9 MemoryStore

- **接口**:
  ```python
  # src/news_sentry/core/memory.py
  from pathlib import Path
  from datetime import datetime

  class MemoryStore:
      """
      文件-backed 内存存储（无数据库）。
      主要职责：
      1. known_item_ids 去重集合（保留策略见治理 backlog MEMORY-RETENTION-001）
      2. source_health 记录
      """
      def __init__(self, memory_root: Path) -> None: ...

      def is_known(self, event_id: str) -> bool: ...
      def mark_known(self, event_id: str, collected_at: datetime) -> None: ...
      def flush(self) -> None:
          """将内存中的更改持久化到 memory/ 目录"""
          ...

      def update_source_health(
          self,
          source_id: str,
          success: bool,
          error_msg: str | None = None,
      ) -> None: ...

      def get_source_health(self, source_id: str) -> dict: ...
  ```

### 3.10 最小 SandboxEnforcer

- **接口**:
  ```python
  # src/news_sentry/core/sandbox.py
  from dataclasses import dataclass
  from enum import Enum

  class SandboxViolationType(str, Enum):
      UNKNOWN_TOOL = "unknown_tool"
      WRITE_OUTSIDE_ROOTS = "write_outside_roots"
      NETWORK_HOST_BLOCKED = "network_host_blocked"
      BUDGET_EXCEEDED = "budget_exceeded"
      SENSITIVE_DATA = "sensitive_data"

  @dataclass
  class SandboxViolation:
      violation_type: SandboxViolationType
      detail: str
      tool_id: str | None
      run_id: str
      timestamp: datetime

  class SandboxEnforcer:
      """
      Phase 3 最小 sandbox enforcer。
      Phase 6 在此基础上强化完整 SandboxPolicy。
      """
      def __init__(self, policy: SandboxPolicy, audit_log_path: Path) -> None: ...

      def check_tool_allowed(self, tool_id: str) -> None:
          """检查工具是否在白名单中，不在则 raise SandboxViolationError 并写审计日志"""
          ...

      def check_write_path(self, path: Path) -> None:
          """检查写入路径是否在允许的 write_roots 内"""
          ...

      def check_budget(self, cost_usd: float) -> None:
          """检查是否超出 max_provider_cost 预算"""
          ...

      def record_network_access(self, host: str, tool_id: str) -> None:
          """记录网络访问（Phase 3 只记录，Phase 6 强化为阻断）"""
          ...
  ```

---

## 4. 配置契约

| 配置文件 | 用途 | Schema 文件 |
|--------|------|-----------|
| `config/italy/target.yaml` | 意大利 TargetConfig | `schemas/target-config.schema.json` |
| `config/italy/sources/ansa-rss.yaml` | ANSA RSS 信源 | `schemas/source-channel.schema.json` |
| `config/italy/sources/corriere-rss.yaml` | Corriere RSS 信源 | 同上 |
| `config/italy/sources/gdelt-api.yaml` | GDELT API 信源 | 同上 |
| `config/filters/italy-rules.yaml` | 意大利过滤规则 | `schemas/filter-rules.schema.json` |
| `config/classification-rules.yaml` | L0–L3 规则引擎分类规则 | — |
| `config/sandbox/default.yaml` | 最小 SandboxPolicy | `schemas/sandbox-policy.schema.json` |

**意大利 TargetConfig 示意** (`config/italy/target.yaml`):
```yaml
target_id: italy
display_name: "意大利新闻监控"
language_primary: it
language_secondary: en
sources:
  - !include sources/ansa-rss.yaml
  - !include sources/corriere-rss.yaml
  - !include sources/gdelt-api.yaml
filter_rules: !include ../filters/italy-rules.yaml
sandbox_policy_ref: default
```

---

## 5. 测试策略

| 测试类型 | 目标 | 工具 | 优先级 |
|---------|------|------|-------|
| 单元测试 | `_generate_id()` 确定性哈希（同 URL+日期 → 同 id） | pytest | P0 |
| 单元测试 | `RulesFilter.apply()` 关键词匹配（意大利语+中文） | pytest | P0 |
| 单元测试 | `MarkdownWriter` 生成文件 frontmatter 格式正确 | pytest | P0 |
| 单元测试 | `ConfigLoader` 配置合并优先级（ADR-0015） | pytest | P0 |
| 合约测试 | 产出的 frontmatter 通过 `schemas/news-event.schema.json` 校验 | jsonschema | P0 |
| 合约测试 | `pipeline_stage` 值符合 `contracts-canonical.md §2` 枚举 | pytest | P0 |
| 集成测试 | 端到端：ANSA RSS mock → `raw/ne-italy-ansa-*.md` 文件产出 | pytest + httpx mock | P1 |
| 集成测试 | sandbox enforcer 拒绝未注册工具，违规写日志 | pytest | P1 |
| 集成测试 | 去重：同一 URL 第二次 run 不重复写文件 | pytest | P1 |
| 回归测试 | run 完成后进程退出码为 0（无 daemon 循环） | pytest subprocess | P1 |

---

## 6. 验收清单

### 文件产出
- [ ] 一次 `python -m news_sentry.cli run --target italy --stage collect --profile local-workstation` 产出 `raw/ne-italy-*.md` 文件
- [ ] 文件 frontmatter 中 `id` 格式符合 `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- [ ] 文件 frontmatter 通过 `schemas/news-event.schema.json` JSON Schema 校验
- [ ] `pipeline_stage: collected` （不是 `collected` 以外的任何值）

### 过滤与分类
- [ ] 一次 `python -m news_sentry.cli run --target italy --stage filter --profile local-workstation` 将 `raw/` 事件移入 `evaluated/` 或 `archive/`
- [ ] `evaluated/` 事件的 `pipeline_stage: filtered`
- [ ] `archive/` 事件含拒绝原因（frontmatter `archive_reason` 或 `processing_history` 记录）
- [ ] `metadata.classification.l0` 非空（至少有规则引擎的一级分类）

### 运行记录
- [ ] `logs/run-{run_id}.yaml` 每次 run 后自动创建，含 `events_collected`、`events_passed_filter`
- [ ] `memory/known_item_ids.yaml`（或等效文件）在第二次 run 时正确跳过重复事件
- [ ] `memory/source_health.yaml` 记录每个信源的最近成功/失败状态

### Sandbox
- [ ] 未注册工具调用被拒绝，`logs/` 中有 sandbox 违规记录
- [ ] 文件写入路径校验：写入 `write_roots` 之外的路径被拒绝

### 代码质量
- [ ] `mypy` 对 `src/news_sentry/` 目录无类型错误
- [ ] `ruff` 无 linter 错误
- [ ] 所有新增模块均有对应的 pytest 单元测试

### 运行时行为
- [ ] `python -m news_sentry.cli run` 完成后进程正常退出（非 daemon 模式）
- [ ] run 最大时长受 `max_duration_seconds` 限制，超时后写日志并退出

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| RSS 信源格式不一致，feedparser 解析失败 | 高 | 中 | adapter 内置多种 RSS 格式解析；失败时 `acquisition.method=builtin_fallback`，写入 `archive/` |
| 文件名冲突（多次 run 处理相同 URL） | 中 | 低 | 确定性 id 哈希保证同 URL 同天生成相同 id；`MemoryStore.is_known()` 跳过已知 |
| 关键词过滤漏过相关事件（召回率低） | 中 | 中 | Phase 3 以高召回为目标（宁过勿漏）；规则配置可热更新，不需要代码修改 |
| 语种检测误判（意大利语 vs 西班牙语） | 低 | 低 | `langdetect` 置信度 < 0.8 时标记 `language=und`，不影响采集，只影响翻译路由 |
| 意大利 reference package 配置丢失 | 低 | 高 | `config/italy/` 纳入 git 版本控制，不在 `.gitignore` 中 |
| `known_item_ids` 无限增长（MEMORY-RETENTION-001） | 中 | 低 | Phase 3 暂不实现清理策略，留待治理 backlog 处理；文件大小监控触发告警 |
| 抽象过度导致 Phase 3 迟迟不能出文件 | 中 | 高 | **以意大利 ANSA RSS → raw/ 文件为最小驱动场景**，接口设计服从这个场景，不反过来 |

---

## 附：源码目录结构（Phase 3 完成后）

```
src/
└── news_sentry/
    ├── __init__.py
    ├── cli.py                     # CLI 入口（ADR-0016）
    ├── core/
    │   ├── __init__.py
    │   ├── run.py                 # bounded_run(), RunOptions, RunSummary
    │   ├── config.py              # ConfigLoader, TargetConfig, SourceChannel, FilterRules
    │   ├── models.py              # NewsEvent, PipelineContext, AcquisitionInfo, ...
    │   ├── file_writer.py         # MarkdownWriter
    │   ├── run_log.py             # RunLog, write_run_log()
    │   ├── memory.py              # MemoryStore
    │   └── sandbox.py            # SandboxEnforcer, SandboxPolicy（最小版）
    ├── skills/
    │   ├── __init__.py
    │   ├── rss_collector.py       # RSSCollector
    │   ├── api_collector.py       # APICollector
    │   ├── filter.py              # RulesFilter, FilterDecision
    │   └── classifier_rules.py   # ClassifierRules（规则引擎）
    └── adapters/
        ├── __init__.py
        ├── base.py                # RuntimeHostAdapter（Phase 2 定义）
        ├── hermes_adapter.py      # HermesAdapter（Phase 2 桩）
        └── openclaw_adapter.py   # OpenClawAdapter（Phase 2 桩）

config/
├── italy/
│   ├── target.yaml
│   └── sources/
│       ├── ansa-rss.yaml
│       ├── corriere-rss.yaml
│       └── gdelt-api.yaml
├── filters/
│   └── italy-rules.yaml
├── classification-rules.yaml
├── sandbox/
│   └── default.yaml
└── profiles/
    ├── cloud-vps.yaml
    └── local-workstation.yaml

tests/
├── unit/
│   ├── test_config.py
│   ├── test_rss_collector.py
│   ├── test_filter.py
│   ├── test_classifier_rules.py
│   ├── test_file_writer.py
│   └── test_sandbox.py
└── integration/
    ├── test_bounded_run.py
    └── fixtures/
        └── ansa_rss_sample.xml
```
