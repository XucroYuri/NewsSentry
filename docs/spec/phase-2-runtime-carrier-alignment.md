# Phase 2 — Runtime Carrier Alignment

> 详细 SPEC: 本文档
> 路线图: [docs/development-plan.md §Phase-2](../development-plan.md)
> 横切组件矩阵: [docs/spec/README.md](README.md)
> 运行载体规格: [docs/brainstorming/Hermes与OpenClaw运行载体规格.md](../brainstorming/Hermes与OpenClaw运行载体规格.md)

---

## 1. 目标与出口标准

**目标：** 定稿生产运行载体优先级和部署 profile，避免 Phase 3 实现阶段把开发工具（Codex、Claude Cowork）和生产运行框架（Hermes、OpenClaw）混为一谈。本 Phase 的主要产出是接口定义文档和 adapter 桩代码，不包含采集或研判 Skill 的实际业务逻辑。

**出口标准（进入 Phase 3 的前提）：**
- [ ] `RuntimeHostAdapter` 接口（输入：run 触发参数 + 配置路径；输出：BoundedRunResult + 错误码）已在 `src/news_sentry/adapters/` 中定义
- [ ] `cloud-vps` 和 `local-workstation` 两套部署 profile 已定义（含 cwd、写入目录路径、网络限制、触发方式）
- [ ] Hermes adapter 桩和 OpenClaw adapter 桩已创建，实现 `RuntimeHostAdapter` 协议
- [ ] `Hermes与OpenClaw运行载体规格.md` 已更新，引用 `contracts-canonical.md`，补充 fallback automation 边界

---

## 2. 内外范围矩阵

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **IN** | `RuntimeHostAdapter` 协议定义（Python Protocol 类） | Hermes 内部 API 实现 |
| **IN** | `HermesAdapter` 桩（实现协议，方法体为 `...` 或 `raise NotImplementedError`） | OpenClaw 内部 Skill registry 实现 |
| **IN** | `OpenClawAdapter` 桩 | 任何采集或研判 Skill 代码 |
| **IN** | `cloud-vps` 和 `local-workstation` 两套 profile YAML | 社媒/KOL adapter（Phase 6） |
| **IN** | bounded run 入口协议文档（触发方式、环境注入、产物读取） | 多 Provider 路由（Phase 5） |
| **IN** | Codex / Claude Cowork fallback 边界的明确文档 | 数据库或消息队列集成 |

---

## 3. 横切组件章节

### 3.1 RuntimeHostAdapter

- **接口**:
  ```python
  # src/news_sentry/adapters/base.py
  from typing import Protocol, runtime_checkable
  from dataclasses import dataclass
  from datetime import datetime

  @dataclass
  class BoundedRunTrigger:
      """宿主传入的 run 触发参数"""
      target_id: str           # 如 "italy"
      stage: str               # "collect" | "filter" | "judge" | "output"
      config_path: str         # 配置根目录路径
      run_id: str | None       # 宿主可注入 run_id，None 时由 Kernel 生成
      env_overrides: dict      # 宿主注入的环境变量覆盖（不包含 secrets）
      max_duration_seconds: int = 3600  # bounded run 最大时长

  @dataclass
  class BoundedRunResult:
      """bounded run 完成后返回给宿主的摘要"""
      run_id: str
      target_id: str
      stage: str
      started_at: datetime
      finished_at: datetime
      exit_code: int           # 0=成功, 1=部分失败, 2=完全失败, 3=沙箱违规
      events_collected: int
      events_filtered: int
      events_written: int
      errors: list[str]        # 人类可读错误列表
      log_path: str            # 本次 run log 文件路径

  @runtime_checkable
  class RuntimeHostAdapter(Protocol):
      """运行载体适配器最小约定协议"""

      def trigger_run(self, trigger: BoundedRunTrigger) -> BoundedRunResult:
          """触发一次有界 run，同步等待完成后返回结果摘要"""
          ...

      def read_result(self, run_id: str) -> BoundedRunResult | None:
          """读取历史 run 结果（宿主可用于轮询）"""
          ...

      def health_check(self) -> bool:
          """运行载体健康检查"""
          ...
  ```

- **数据流**:
  ```
  宿主调度器（Hermes cron / OpenClaw Skill / CLI）
        │
        │ BoundedRunTrigger
        ▼
  RuntimeHostAdapter.trigger_run()
        │
        │ 同步等待（bounded run 在 adapter 内部完成）
        ▼
  BoundedRunResult
        │
        ▼
  宿主可读取 log_path 文件获取详情
  ```

- **错误处理**:
  - `exit_code=0`：完全成功
  - `exit_code=1`：部分信源失败，已产出有效事件
  - `exit_code=2`：关键失败，未产出任何有效事件
  - `exit_code=3`：沙箱违规，run 被强制终止，违规已写入安全日志

### 3.2 HermesAdapter

- **接口**:
  ```python
  # src/news_sentry/adapters/hermes_adapter.py
  from news_sentry.adapters.base import RuntimeHostAdapter, BoundedRunTrigger, BoundedRunResult

  class HermesAdapter:
      """
      Hermes Agent 运行载体适配器（生产主通道）。
      Hermes 作为长期生产调度器，通过 cron 触发 bounded run。
      """
      def __init__(self, hermes_api_base: str, auth_token: str) -> None: ...

      def trigger_run(self, trigger: BoundedRunTrigger) -> BoundedRunResult: ...
      def read_result(self, run_id: str) -> BoundedRunResult | None: ...
      def health_check(self) -> bool: ...
  ```

- **数据流**: Hermes → `trigger_run()` → Kernel bounded run → 文件写入 → `BoundedRunResult` → Hermes 读取 log

- **触发方式（cloud-vps profile）**:
  ```yaml
  # Hermes cron 配置示意（非实现代码）
  schedule: "0 */4 * * *"           # 每 4 小时
  command: python -m news_sentry.cli run --target italy --stage collect --profile cloud-vps
  timeout: 3600
  on_failure: notify_and_skip       # 失败时通知但不重试（不堆积）
  ```

### 3.3 OpenClawAdapter

- **接口**:
  ```python
  # src/news_sentry/adapters/openclaw_adapter.py
  from news_sentry.adapters.base import RuntimeHostAdapter, BoundedRunTrigger, BoundedRunResult

  class OpenClawAdapter:
      """
      OpenClaw Skill 运行载体适配器（Skill 生态兼容层）。
      OpenClaw 作为 Skill runtime，提供 ClawHub 兼容性。
      本 adapter 允许 News Sentry Skill 在 OpenClaw 生态中被调用。
      """
      def __init__(self, skill_manifest_path: str) -> None: ...

      def trigger_run(self, trigger: BoundedRunTrigger) -> BoundedRunResult: ...
      def read_result(self, run_id: str) -> BoundedRunResult | None: ...
      def health_check(self) -> bool: ...
  ```

### 3.4 部署 Profile 定义

**cloud-vps profile** (`config/profiles/cloud-vps.yaml`):
```yaml
profile_id: cloud-vps
description: "生产 VPS 环境，Hermes 主调度"

paths:
  cwd: "."                    # 相对于项目根，由部署器提供 working directory
  output_root: "./data"        # raw/ evaluated/ 等子目录均在此处
  config_root: "./config"
  log_root: "./data/{target_id}/logs"
  memory_root: "./data/{target_id}/memory"

network:
  allow_outbound: true
  blocked_hosts: []       # 由 SandboxPolicy per-tool 限制

runtime:
  trigger: cron           # 由 Hermes 触发
  max_duration_seconds: 1800
  max_memory_mb: 1024

sandbox:
  profile: cloud-vps      # 引用 config/sandbox/cloud-vps.yaml
```

**local-workstation profile** (`config/profiles/local-workstation.yaml`):
```yaml
profile_id: local-workstation
description: "本地开发/测试环境，CLI 或 Claude Cowork fallback 触发"

paths:
  cwd: "."                            # 相对于项目根
  output_root: "./data"
  config_root: "./config"
  log_root: "./data/{target_id}/logs"
  memory_root: "./data/{target_id}/memory"

network:
  allow_outbound: true
  blocked_hosts: []

runtime:
  trigger: cli                         # python -m news_sentry.cli run ... 或 Claude Cowork
  max_duration_seconds: 600            # 本地 fallback 用更短超时
  max_memory_mb: 1024

sandbox:
  profile: local-workstation
```

---

## 4. 配置契约

| 配置文件 | 用途 | 所属 Phase |
|--------|------|-----------|
| `config/profiles/cloud-vps.yaml` | 生产 VPS 部署 profile | Phase 2 定义 |
| `config/profiles/local-workstation.yaml` | 本地开发 profile | Phase 2 定义 |
| `src/news_sentry/adapters/base.py` | RuntimeHostAdapter 协议 | Phase 2 实现 |
| `src/news_sentry/adapters/hermes_adapter.py` | Hermes 适配器桩 | Phase 2 桩，Phase 3+ 补全 |
| `src/news_sentry/adapters/openclaw_adapter.py` | OpenClaw 适配器桩 | Phase 2 桩，Phase 3+ 补全 |

---

## 5. 测试策略

| 测试类型 | 目标 | 工具 |
|---------|------|------|
| 协议合规性 | `HermesAdapter` 和 `OpenClawAdapter` 均实现 `RuntimeHostAdapter` Protocol | `pytest`，`isinstance(adapter, RuntimeHostAdapter)` |
| 接口签名 | `BoundedRunTrigger` 和 `BoundedRunResult` 字段符合 ADR 要求 | `mypy` 静态检查 |
| Profile YAML 格式 | 两套 profile YAML 可被 pydantic 加载，必填字段不缺失 | `pytest` + pydantic model |
| 文档一致性 | 接口文档中的字段与代码 dataclass 一致 | 人工比对 |

---

## 6. 验收清单

- [ ] `src/news_sentry/adapters/base.py` 存在，定义 `BoundedRunTrigger`、`BoundedRunResult`、`RuntimeHostAdapter`
- [ ] `HermesAdapter` 和 `OpenClawAdapter` 均满足 `isinstance(adapter, RuntimeHostAdapter)` 检查
- [ ] `BoundedRunResult.exit_code` 包含 0/1/2/3 四种枚举值，文档已说明含义
- [ ] `config/profiles/cloud-vps.yaml` 存在，含 `paths`、`network`、`runtime`、`sandbox` 四个顶层键
- [ ] `config/profiles/local-workstation.yaml` 存在，含相同结构
- [ ] `Hermes与OpenClaw运行载体规格.md` 已更新，引用 `contracts-canonical.md`，补充 Codex/Claude Cowork 为 fallback 的边界说明
- [ ] `mypy` 对 `adapters/` 目录无类型错误
- [ ] 两个 adapter 桩的所有 Protocol 方法已声明（方法体可为 `...` 或 raise，但签名必须正确）

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 回退策略 |
|------|--------|------|---------|
| Hermes 内部 API 变动导致 adapter 频繁修改 | 中 | 中 | 薄 adapter 原则：只依赖稳定触发接口（cron trigger + 参数注入），不依赖 Hermes 内部 memory |
| OpenClaw Skill 调用协议变动 | 中 | 中 | OpenClawAdapter 封装变动点，核心 Kernel 不直接调用 OpenClaw API |
| 两套 profile 在实现时被合并为一个，丢失隔离性 | 低 | 低 | Profile ID 是配置键，Kernel 根据 `NEWSSENTRY_PROFILE` 环境变量选择 |
| Codex/Claude Cowork 被误用为生产调度器 | 中 | 高 | 文档明确标注 fallback 边界；`local-workstation` profile 设置更短 timeout 防止长期挂起 |

---

## 附：运行载体优先级说明

```
┌─────────────────────────────────────────────────┐
│           生产运行载体优先级（从高到低）            │
├─────────────────────────────────────────────────┤
│ 1. Hermes Agent        主编排，24h cron，cloud-vps │
│ 2. OpenClaw Skill      Skill 生态，ClawHub 兼容   │
│ 3. CLI                 本地开发，手动触发           │
│ 4. Codex Automations   fallback，仅维护/研究       │
│ 5. Claude Cowork       fallback，仅维护/研究       │
├─────────────────────────────────────────────────┤
│ ⚠️  Codex/Claude Cowork 不作为 24h 主监控骨干      │
│     只承担：项目维护、研究报告、人工可审查摘要        │
└─────────────────────────────────────────────────┘
```

**薄 adapter 原则（防止框架锁定）：**
- Adapter 方法签名固定（`trigger_run` / `read_result` / `health_check`）
- Adapter 内部实现只依赖宿主的"稳定触发接口"，不依赖宿主内部状态管理
- 切换宿主只需切换 adapter 实现，核心 Kernel 代码零修改
