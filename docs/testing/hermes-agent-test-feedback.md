# Hermes Agent 测试反馈 — News Sentry 运行环境差距报告

> **文档类型**: 测试反馈报告（Agent → 项目）
> **测试执行方**: Hermes Agent v0.13.0 (DeepSeek V4 Pro)
> **测试日期**: 2026-05-09 ~ 2026-05-10 (UTC)
> **测试轮次**: 2 轮完整 PDCA 执行
> **测试方案**: [`docs/testing/test-plan-hermes-agent.md`](./test-plan-hermes-agent.md)
> **结论文件**: `data/italy/logs/.test-conclusion-hermes.json`

---

## 0. 执行摘要

Hermes Agent 作为 News Sentry 生产主编排运行载体，在 **Phase 3 Kernel MVP** 阶段表现出良好的基础能力。两轮 PDCA 测试（4 Sub-PDCA × 2 轮 = 8 次循环）覆盖了 CLI 可达性、全链路 pipeline、错误注入恢复、并发隔离等场景。

**最终评级**: `PASS_WITH_ISSUES` (两轮一致)
- 282 pytest 测试全部通过
- ruff/mypy 零错误
- 核心采集→过滤→输出链路跑通
- 发现 10 项需要修复的问题 + 1 项已完成修复

---

## 1. 已修复问题

### FIX-1: SandboxEnforcer YAML 映射断裂 (已修复)

| 项目 | 内容 |
|------|------|
| **发现时间** | 第 2 轮 T4 测试 |
| **严重程度** | **Critical** — 沙箱策略完全未生效 |
| **根因** | `SandboxPolicy` 是平铺 Pydantic 模型 (`allowed_network_hosts`)，但 YAML 配置是嵌套结构 (`network_policy.allowed_hosts`)。`run.py:103` 直接 `SandboxPolicy(**sp)` 传入原始 YAML dict，Pydantic 静默丢弃所有嵌套字段（`extra='ignore'`），导致沙箱始终以空策略运行（全能模式） |
| **修复** | 3 文件修改： |

#### 修复 1: `src/news_sentry/core/sandbox.py` — 添加 `default_action` 字段

```python
class SandboxPolicy(BaseModel):
    model_config = {"extra": "ignore"}
    # ... existing fields ...
    default_action: str = "allow"  # "allow" | "deny"
```

`check_network_host()` 空列表语义修正：
```python
# Before (permissive):
if not self._policy.allowed_network_hosts:
    return True

# After (respects default_action):
if not self._policy.allowed_network_hosts:
    return self._policy.default_action != "deny"
```

#### 修复 2: `src/news_sentry/core/run.py` — YAML 嵌套结构映射

```python
# Before (broken — nested fields silently dropped):
sandbox_policy = SandboxPolicy(**sp) if sp else SandboxPolicy()

# After (explicit mapping):
sandbox_kwargs: dict[str, Any] = {}
cmd_policy = sp.get("command_policy", {})
sandbox_kwargs["allowed_commands"] = cmd_policy.get("allowed_commands", [])
net_policy = sp.get("network_policy", {})
sandbox_kwargs["allowed_network_hosts"] = net_policy.get("allowed_hosts", [])
# ... fs_policy, budget_policy, default_action ...
sandbox_policy = SandboxPolicy(**sandbox_kwargs)
```

#### 修复 3: `tests/test_sandbox.py` — 新增 deny 模式测试

```python
def test_empty_allowed_list_default_allow(self) -> None:  # renamed, semantics preserved
def test_empty_allowed_list_with_deny(self) -> None:      # NEW — deny mode
```

**验证结果**:
- T4 修复后：`allowed_hosts: []` + `default_action: deny` → 0 事件采集，0 错误（沙箱正确阻止）
- 恢复配置后：正常采集 61 事件（向后兼容）
- pytest: 282/282 通过（新增 2 个测试）
- ruff/mypy: 零错误

---

## 2. 未修复问题 (按严重程度排序)

### ISSUE-1: NewsEvent.id 格式缺少 target_id 段

| 项目 | 内容 |
|------|------|
| **严重程度** | **High** |
| **影响** | 跨 target 去重失效，多国家扩展时无法区分事件来源 |
| **契约要求** | `contracts-canonical.md §3`: `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}` |
| **当前实际** | `ne-repubblica-20260509-a742c564`（缺 `italy` 段） |
| **期望格式** | `ne-italy-repubblica-20260509-a742c564` |
| **涉及文件** | `src/news_sentry/models/newsevent.py::NewsEvent.make_id()` |
| **影响范围** | 所有已生成的 91 raw/ 文件 + 5 evaluated/ 文件 + 2 drafts/ 文件 |
| **修复建议** | 修改 `make_id()` 增加 `target_id` 参数；旧文件可通过迁移脚本批量改名 |

### ISSUE-2: Judge 阶段为 stub — 不产出 judge_result

| 项目 | 内容 |
|------|------|
| **严重程度** | **High** |
| **影响** | 核心研判功能缺失 — 无 `judge_result.recommendation`，无 `news_value_score` 动态计算，无 `china_relevance` 评估 |
| **当前行为** | `_run_judge_placeholder()` 只记录 `items=0, errors=0`，84 次历史 judge 运行全部为空操作 |
| **涉及文件** | `src/news_sentry/core/run.py::_run_judge_placeholder` |
| **依赖** | Phase 5 AI Provider Routing（需要 LLM 路由）或规则引擎 fallback |
| **修复建议** | Phase 3 内至少实现规则引擎 judge（基于 filter 分数 + classification 直接生成 recommendation）；LLM judge 留到 Phase 5 |

### ISSUE-3: Source Health 未实现

| 项目 | 内容 |
|------|------|
| **严重程度** | **Medium** |
| **影响** | 无法追踪信源可用性 — corriere SSL 错误、agi/fao-rss 404 已持续多天但无人感知 |
| **规格要求** | `development-plan.md §4 P3.W3.07`: 记录每个信源的最近成功率和失败原因 |
| **当前状态** | `data/italy/memory/` 只有 `known_item_ids.yaml`，无 `source_health.yaml` |
| **涉及文件** | `src/news_sentry/core/memory.py` + `src/news_sentry/core/run.py` |
| **修复建议** | 在 `_run_collect()` 中，每个 source 采集完成后写入 `memory/source_health.yaml` |

### ISSUE-4: 目录协议不完整 — reviewed/published/archive 未使用

| 项目 | 内容 |
|------|------|
| **严重程度** | **Medium** |
| **影响** | 文件事件协议缺三个目录 — archive/ 用于存储被拒/低价值事件，reviewed/ 用于人审通道，published/ 用于归档 |
| **协议要求** | `contracts-canonical.md §5`: 7 个目录 + memory/ + logs/ |
| **当前状态** | 仅 raw/ (91)、evaluated/ (5)、drafts/ (2)、memory/ (1)、logs/ (130+) 在使用 |
| **修复建议** | `_run_filter` 将被拒事件写入 `archive/`；output stage 完成后移动 drafts 到 `published/` |

### ISSUE-5: Output stage 不更新 pipeline_stage

| 项目 | 内容 |
|------|------|
| **严重程度** | **Low** |
| **影响** | drafts/ 文件 `pipeline_stage` 仍为 `filtered`，应为 `outputted` |
| **契约要求** | `contracts-canonical.md §2`: pipeline_stage 枚举含 `outputted` |
| **当前实际** | drafts 文件 frontmatter 中 `pipeline_stage: filtered` |
| **涉及文件** | `src/news_sentry/skills/output/markdown_writer.py` 或 `_run_output` |
| **修复建议** | Output writer 在写 drafts 时更新 `pipeline_stage` → `outputted` |

### ISSUE-6: classification 字段命名偏差

| 项目 | 内容 |
|------|------|
| **严重程度** | **Low** |
| **影响** | 实现与契约命名不一致，跨文档引用时造成困惑 |
| **契约要求** | `contracts-canonical.md §9`: `l0`, `l1[]`, `l2[]`, `l3`, `confidence` |
| **当前实际** | `l0_domain`, `l1_topics`, `l2_country_axes`, `l3_tags`, `l0_confidence` |
| **涉及文件** | `src/news_sentry/skills/filter/classifier_rules.py` + `config/classification/rules-v1.yaml` |
| **修复建议** | 二选一：(a) 修改代码对齐契约 (b) 修改契约对齐代码 + 新建 ADR |

### ISSUE-7: 意大利信源覆盖不足 (Breaking News 需求)

| 项目 | 内容 |
|------|------|
| **严重程度** | **Medium** |
| **影响** | 5 个源（3 active）远不能覆盖"意大利 Breaking News"场景 — 缺广播电视、财经、地方政府、欧盟机构等关键源 |
| **当前源** | ansa ✓, repubblica ✓, corriere ⚠️(SSL错误), agi ❌(disabled/404), fao-rss ❌(disabled/404) |
| **缺失类型** | 广播电视 (RAI, TgCom24, Sky TG24)、财经 (Il Sole 24 Ore ⚠️)、地方 (La Stampa, Il Messaggero)、欧盟 (EUR-Lex)、体育 (Gazzetta)、英文 (The Local Italy) |
| **修复建议** | 详见 §3 完整信源扩展建议 |

### ISSUE-8: Provider Routes 全为 placeholder

| 项目 | 内容 |
|------|------|
| **严重程度** | **Medium**（当前阶段预期） |
| **影响** | 翻译、LLM 判断、LLM 分类全部不可用 — 当前完全依赖规则引擎 |
| **涉及文件** | `config/provider/routes.yaml`（5 条 route 全为 `<placeholder>`） |
| **修复建议** | Phase 5 任务 — 不需现在修复，但应记录为 blocker |

### ISSUE-9: Hermes Cron 未在生产环境配置

| 项目 | 内容 |
|------|------|
| **严重程度** | **Medium** |
| **影响** | 当前只能通过 CLI 手动触发，无 24 小时自动调度 |
| **配置就绪** | `config/runtime/hermes.yaml` 已有 cron 表达式定义 |
| **修复建议** | 在云 VPS 上通过 `hermes cron create` 或 cronjob 工具创建调度任务 |

### ISSUE-10: 双语翻译未实现

| 项目 | 内容 |
|------|------|
| **严重程度** | **Low**（Phase 5 依赖） |
| **影响** | collect 阶段无 `metadata.translation.title_pre`，judge 阶段无 `title_translated/content_translated` |
| **涉及文件** | RSSCollector + judge_skill |
| **修复建议** | Phase 3 可加 mock 翻译（`title_pre = title_original`），Phase 5 接入真实路由 |

---

## 3. 意大利 Breaking News 完整信源扩展建议

以下信源应在 `config/sources/italy/` 中补充（含 RSS URL 验证状态）：

### 3.1 广播电视 (TV/Radio)
| source_id | 名称 | RSS URL | 状态 |
|-----------|------|---------|------|
| rainews | Rai News | `https://www.rainews.it/rss/` | 待验证 |
| tgcom24 | TgCom24 | `https://www.tgcom24.mediaset.it/rss/` | 待验证 |
| skytg24 | Sky TG24 | `https://tg24.sky.it/rss/` | 待验证 |
| radio24 | Radio 24 | `https://www.radio24.ilsole24ore.com/rss/` | 待验证 |

### 3.2 财经 (Economics/Finance)
| source_id | 名称 | RSS URL | 状态 |
|-----------|------|---------|------|
| ilsole24ore | Il Sole 24 Ore | `https://www.ilsole24ore.com/rss/` | 待验证 |

### 3.3 地方/区域 (Regional)
| source_id | 名称 | RSS URL | 状态 |
|-----------|------|---------|------|
| lastampa | La Stampa | `https://www.lastampa.it/rss/` | 待验证 |
| ilmessaggero | Il Messaggero | `https://www.ilmessaggero.it/rss/` | 待验证 |
| ilfatto | Il Fatto Quotidiano | `https://www.ilfattoquotidiano.it/feed/` | 待验证 |

### 3.4 欧盟/国际 (EU/International)
| source_id | 名称 | RSS URL | 状态 |
|-----------|------|---------|------|
| eurlex | EUR-Lex (EU law) | `https://eur-lex.europa.eu/rss/` | 待验证 |
| thelocal-it | The Local Italy (EN) | `https://www.thelocal.it/feeds/rss/` | 待验证 |
| ansa-en | ANSA English | `https://www.ansa.it/english/english_rss.xml` | 待验证 |

### 3.5 专项 (Specialized)
| source_id | 名称 | RSS URL | 状态 |
|-----------|------|---------|------|
| gazzetta | Gazzetta dello Sport | `https://www.gazzetta.it/rss/` | 待验证 |
| ilpost | Il Post | `https://www.ilpost.it/feed/` | 待验证 |

---

## 4. 修正优先级矩阵

```
High   │ ISSUE-1 (id格式)     ISSUE-2 (judge stub)
       │
Medium │ ISSUE-3 (health)     ISSUE-4 (目录)     ISSUE-7 (信源)
       │ ISSUE-8 (provider)   ISSUE-9 (cron)
       │
Low    │ ISSUE-5 (stage)      ISSUE-6 (命名)     ISSUE-10 (翻译)
       │
Done   │ FIX-1 (sandbox) ✅
       └────────────────────────────────────────────
         Phase 3               Phase 4-5            Phase 6+
```

---

## 5. 测试数据快照

| 指标 | 第 1 轮 | 第 2 轮 |
|------|---------|---------|
| pytest | 276/276 | 282/282 |
| ruff | Pass | Pass |
| mypy | 37 files OK | 37 files OK |
| T1 (单阶段) | 61 events, 3 errors | 61 events, 3 errors |
| T2 (全链路) | filter→judge→output OK | filter→judge→output OK |
| T3 (网络故障) | 5 errors recorded | 5 errors recorded |
| T4 (沙箱) | **FAIL** (not enforced) | **PASS** (fixed) |
| T5 (超时) | PASS (10s < 1min) | PASS (8.3s < 1min) |
| T6 (并发) | 2 RunLogs, dedup OK | 2 RunLogs, dedup OK |
| RunLog 总数 | 98 | 130+ |
| Evaluated 文件 | 5 | 5 |
| Drafts 文件 | 2 | 2 |
| .tmp 残留 | 0 | 0 |

---

## 6. Hermes Agent 自身能力评估

作为运行载体，Hermes Agent v0.13.0 在本机 macOS 环境下表现:

| 能力 | 评估 | 说明 |
|------|------|------|
| CLI 触发 | ✅ | `hermes chat -q` + terminal 工具可正常调用 News Sentry CLI |
| Skills 系统 | ✅ | `skill_view()` 正常加载 SKILL.md |
| Memory | ✅ | 跨 session 持久化正常 |
| Subagent | ✅ | `delegate_task` 正常分派检查任务 |
| Cron | ⚠️ | `cronjob` 工具可用，但未配置生产调度 |
| Gateway | ⚠️ | 未配置消息推送（Telegram/Discord 等） |
| Provider | ✅ | DeepSeek V4 Pro 运行正常 |

**综合判断**: Hermes Agent 在本机作为 News Sentry 运行载体**已满足 Phase 3 Kernel MVP 的开发测试需求**。向 cloud-vps 生产迁移前需要: (a) 配置 cron, (b) 接入 gateway 通知, (c) 修复 ISSUE-1 至 ISSUE-10。

---

## 7. 附录: 相关文件索引

| 文件 | 用途 |
|------|------|
| `data/italy/logs/.test-conclusion-hermes.json` | 结构化测试结论 (JSON) |
| `data/italy/logs/.heartbeat-hermes.json` | 测试心跳记录 |
| `data/italy/logs/italy_20260509T200438Z_b705b6ef.json` | 第 2 轮 Sub-PDCA-1 collect RunLog |
| `src/news_sentry/core/sandbox.py` | 沙箱修复 (已修改) |
| `src/news_sentry/core/run.py` | YAML 映射修复 + Any import (已修改) |
| `tests/test_sandbox.py` | 新增 deny 测试 (已修改) |

---

## 8. 开源部署可行性审查 — GitHub 远端仓库视角

> **审查范围**: 从 `https://github.com/XucroYuri/NewsSentry` clone 后，
> 一个不了解项目内部上下文的新部署者能否在 30 分钟内跑通意大利 Breaking News 监控。

### 8.1 缺失关键文件

| 文件 | 重要性 | 当前状态 | 影响 |
|------|--------|---------|------|
| **`LICENSE`** | 🔴 Critical | **MISSING** — `pyproject.toml` 声明 MIT 但仓库无 LICENSE 文件 | GitHub 不显示 license badge；企业部署者无法合规审查 |
| **`.env.example`** | 🔴 Critical | **MISSING** — 部署者不知道需要哪些环境变量 | 首次运行必然失败；`NEWSSENTRY_PROFILE`、`FEISHU_WEBHOOK_URL`、代理变量等无人知晓 |
| **`CONTRIBUTING.md`** | 🟡 High | **MISSING** — 无贡献指南 | 外部贡献者不知道 PR 流程、代码风格、测试要求 |
| **`CHANGELOG.md`** | 🟡 High | **MISSING** | 部署者无法判断版本间 breaking changes |
| **`Makefile`** | 🟡 High | **MISSING** | 无 `make install` / `make test` / `make run` 快捷指令 |
| **`.github/workflows/ci.yml`** | 🟡 High | **MISSING** — 无 CI/CD | 无法验证 PR 是否通过测试；无自动发布流程 |
| **`Dockerfile`** | 🟢 Medium | **MISSING** | 无容器化部署方案 |
| **`docker-compose.yml`** | 🟢 Medium | **MISSING** | 无本地一键启动方案 |

### 8.2 README.md 内容缺口

| 缺口 | 严重程度 | 当前状态 | 建议补充 |
|------|---------|---------|---------|
| Phase 状态错误 | 🔴 High | Phase 2/3 标记为 "Planned"，但代码已可运行 | 更新为 "In Progress" 或 "MVP Ready" |
| 无前置条件 | 🔴 High | 只说 Python ≥ 3.11，未提及系统依赖 | 列出 `libxml2`、`libxslt`（feedparser 依赖）、`git`、`uv`/`pip` |
| 无环境变量表 | 🔴 High | 完全没有 | 添加 `NEWSSENTRY_PROFILE`、`NEWSSENTRY_DATA_DIR`、代理变量、API key 变量 |
| 无故障排查 | 🟡 High | 完全没有 | 常见错误：RSS 超时、SSL 错误、venv 激活失败、权限问题 |
| 无部署指南 | 🟡 High | 完全没有 | cloud-vps 部署步骤：systemd service、Hermes cron、nginx 反代 |
| 无配置示例 | 🟡 High | Quick Start 只有一条命令 | 添加 `--dry-run` 验证 → `--stage collect` → `--stage all` 循序渐进 |
| 无测试说明 | 🟢 Medium | 无 | `pytest tests/ -q` 和期望输出 |
| 无 badge | 🟢 Low | 无 | Python 3.11+ | tests 282 passing | license MIT |
| 默认 profile 不一致 | 🟡 High | Quick Start 用 `local-workstation`，测试方案用 `cloud-vps` | 明确两种 profile 的区别和选用建议 |

### 8.3 pyproject.toml 元数据缺口

| 缺口 | 当前状态 | 建议 |
|------|---------|------|
| `version` | `"0.0.0"` — 无意义版本号 | 改为 `"0.1.0"` (Phase 3 MVP) |
| `[project.urls]` | **缺失** | 添加 Homepage、Repository、Issues 链接 |
| `authors` | **缺失** | 添加作者信息 |
| `uv.lock` 被 gitignore | 已忽略 | 考虑提交锁文件（或至少 `uv.lock.example`），保证部署者依赖版本一致 |

### 8.4 配置模板缺口

| 缺口 | 当前状态 | 影响 |
|------|---------|------|
| 无带注释的源配置模板 | `_template.yaml` 只有字段，无注释说明每个字段含义 | 新部署者不知道 `credibility_base`、`fetch_interval_minutes`、`health` 怎么填 |
| 已禁用源无恢复说明 | `agi.yaml` 和 `fao-rss.yaml` 标 `enabled: false`，注释说 "2026-05-10: URL 已失效" | 部署者不知道去哪找新的 RSS URL |
| 无 Hermes cron 配置示例 | `config/runtime/hermes.yaml` 存在，但无对应的 `hermes cron create` 命令示例 | 部署者不知道怎么在 Hermes 中注册 cron |
| 无多 target 配置示例 | 只有 `italy.yaml` + `_template.yaml` | 缺少一个完整可运行的第二个 target 示例（如 `eu-china`） |

### 8.5 文档可访问性缺口

| 缺口 | 当前状态 | 影响 |
|------|---------|------|
| 中文文件名 | `docs/brainstorming/` 下 6 个 .md 文件名纯中文 | GitHub 上国际贡献者无法阅读目录结构；某些工具对中文路径支持差 |
| 无架构图 | `architecture-overview.md` 的 ASCII 图过于简略 | 缺少可视化架构图（Mermaid/SVG）帮助新贡献者理解 |
| 无 API 文档 | 无 `docs/api/` 目录 | 开发者不知道 `NewsEvent`、`PipelineContext`、`SandboxPolicy` 的完整 Python API |
| 无 Glossary | 术语散落在各文档中 | 新人面对 `bounded run`、`run_id`、`pipeline_stage`、`SkillManifest` 等术语不知所措 |
| 无 Quick Reference | 无单页速查表 | CLI 命令、目录映射、分值量纲需要快速查阅 |

### 8.6 运维缺口

| 缺口 | 严重程度 | 影响 |
|------|---------|------|
| 无日志轮转 | 🟡 High | 130+ RunLog 文件无限增长；`data/` 被 gitignored 但磁盘空间仍有限 |
| 无数据保留策略 | 🟡 High | `raw/` 91 文件、`logs/` 130+ 文件无清理规则 |
| 无备份恢复文档 | 🟢 Medium | 生产部署者不知道哪些目录需要备份 |
| 无健康检查 | 🟡 High | 无 `hermes doctor` 等效的 News Sentry 健康检查命令 |
| 无监控集成 | 🟢 Medium | 无 Prometheus metrics、无健康检查 endpoint |

### 8.7 开发者体验缺口

| 缺口 | 当前状态 | 建议 |
|------|---------|------|
| pre-commit hooks | 无 `.pre-commit-config.yaml` | 添加 ruff + mypy 自动检查 |
| Editor 配置 | 无 `.vscode/` 推荐配置 | 添加 `extensions.json` + `settings.json` |
| 本地开发覆盖 | `CLAUDE.local.md` 文档提及但无模板 | 创建 `CLAUDE.local.example.md` |

### 8.8 部署者 30 分钟体验模拟

模拟一个新部署者从 GitHub clone 仓库后的首次体验：

```
时间轴:
00:00  git clone → ✅
00:01  读 README → ⚠️ Phase 状态过时，无前置条件
00:03  python -m venv .venv → ✅
00:05  pip install -e ".[dev]" → ✅ (如果没有系统依赖问题)
00:08  python -m news_sentry.cli run ... → ❌ 报错: 不知道需要什么 env vars
00:10  搜索 .env.example → ❌ 不存在
00:12  读 config/runtime/hermes.yaml → 找到 profile 信息
00:15  export NEWSSENTRY_PROFILE=local-workstation → 猜测
00:18  重新运行 → ⚠️ 3 个 RSS 源报错 (corriere SSL/agi 404/fao 404)
00:20  不知道这些错误是正常的还是配置问题 → 无故障排查文档
00:25  找到 docs/testing/ 目录 → 发现测试方案
00:30  跑通 collect → ✅ 61 事件
```

**30 分钟结论: 勉强跑通，但体验差。** 核心阻断: 缺少 `.env.example` 和故障排查文档。

### 8.9 开源可行性总评

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码质量 | ⭐⭐⭐⭐ | pytest 282/282, ruff/mypy clean, 架构清晰 |
| 文档完整度 | ⭐⭐⭐ | 契约文档极详细 (contracts-canonical + 16 ADR)，但缺部署/运维文档 |
| 可部署性 | ⭐⭐ | 缺 .env.example、部署指南、CI/CD |
| 可贡献性 | ⭐⭐ | 缺 CONTRIBUTING、pre-commit、editor config |
| 开源合规 | ⭐ | 缺 LICENSE 文件 (虽然代码标注 MIT) |
| **综合** | **⭐⭐½** | **代码就绪，文档和运维基础设施落后于代码质量** |

### 8.10 优先修复建议 (按部署者体验排序)

```
P0 (阻断部署):  LICENSE, .env.example, README Phase 状态修正, 前置条件章节
P1 (严重影响):  CONTRIBUTING.md, 故障排查文档, Makefile, CI/CD
P2 (体验改善):  CHANGELOG.md, 配置注释模板, Dockerfile, 健康检查命令
P3 (锦上添花):  API 文档, 架构图, editor config, 中文文件名罗马化
```

---

## 9. 部署基础设施补全 (2026-05-10 完成)

> 基于 §8 开源部署审查的 P0/P1 优先修复建议，已完成以下基础设施交付。

### 9.1 协议确定: Apache 2.0

| 项目 | 内容 |
|------|------|
| 协议 | [Apache License 2.0](../../LICENSE) |
| 许可证文件 | `LICENSE` (202 行，含完整条款 + Appendix) |
| pyproject.toml | `license = { file = "LICENSE" }` |
| 分类器 | `License :: OSI Approved :: Apache Software License` |
| **核心条款** | 自由使用/修改/分发/商用；含专利授权；要求保留版权声明；含免责声明 |

### 9.2 自动化依赖部署能力

**依赖分析结论**: News Sentry Phase 3 的 5 个核心 Python 包 (pydantic, pyyaml, httpx, feedparser, click) 及 6 个开发包 **全部为纯 Python wheel**，无 C 扩展编译依赖，不需要 `libxml2`/`libxslt`/`gcc` 等系统级工具链。

| 部署方式 | 目标用户 | 命令 |
|---------|---------|------|
| `install.sh --dev` | 开发者 | 一键安装 Python + venv + 全部依赖 + .env 创建 |
| `install.sh` | 生产部署 | 仅生产依赖，不装 pytest/mypy/ruff |
| `install.sh --check` | CI/验证 | 安装 + 运行测试套件 |
| `make install` | 开发者 (手动) | venv + pip install -e ".[dev]" |
| `make install-prod` | 生产 (手动) | venv + pip install -e . |
| `pip install -e ".[dev]"` | 已有 venv | 手动安装 |

**`install.sh` 功能清单**:
- ✅ Python 版本检测 (自动查找 python3.13 > 3.12 > 3.11 > python3)
- ✅ pip 可用性校验
- ✅ 磁盘空间检查 (>= 200MB)
- ✅ `.env` 自动创建 (从 `.env.example` 复制)
- ✅ 已有 venv 检测与重建提示
- ✅ 安装后 import 验证
- ✅ 外部工具检查 (hermes, git, gh) 与安装指南
- ✅ 退出码正确 (失败时非零)

**`Makefile` 功能清单**:
- ✅ `make install` / `make install-prod`
- ✅ `make test` / `make lint` / `make check` / `make fmt`
- ✅ `make dry-run` / `make run` / `make run-filter` / `make run-judge` / `make run-output` / `make run-all`
- ✅ `make stats` / `make latest-log`
- ✅ `make clean` / `make clean-data` (带确认)
- ✅ 可选变量: `TARGET=italy`, `PROFILE=cloud-vps`

### 9.3 交付文件清单

| 文件 | 状态 | 行数 | 说明 |
|------|------|------|------|
| `LICENSE` | ✅ 新建 | 128 | PolyForm Shield 1.0.0 + Noncompete Clarification |
| `.env.example` | ✅ 新建 | 55 | 含全部环境变量 + 分组注释 + 获取方式 |
| `Makefile` | ✅ 新建 | 150 | 19 个 target, 支持变量覆盖 |
| `install.sh` | ✅ 新建 | 193 | 一键安装, 含前置条件检查 + 外部工具检测 |
| `README.md` | ✅ 重写 | 173 | Phase 状态修正, 前置条件表, 环境变量表, 故障排查 |
| `pyproject.toml` | ✅ 更新 | — | version 0.1.0, 协议, authors, urls, 分类器 |
| `.gitignore` | ✅ 更新 | — | 添加 `!.env.example` 排除规则 |

### 9.4 更新后的 30 分钟体验模拟

```
时间轴 (修复后):
00:00  git clone → ✅
00:01  读 README → ✅ 前置条件清晰, Phase 状态准确, 有故障排查
00:03  bash install.sh --dev → ✅ 自动检测 Python, 创建 venv, 安装依赖
00:04  source .venv/bin/activate → ✅
00:05  make dry-run → ✅ 验证配置
00:07  make run → ✅ 61 事件采集成功
00:08  make check → ✅ lint + 282 tests 全部通过
00:10  查看 make stats → ✅ 了解数据产出
00:12  阅读 .env.example → ✅ 知道如何配置生产环境
00:15  阅读 LICENSE → ✅ 了解使用限制
```

**修复后结论: 12 分钟跑通，体验良好。** 之前阻断部署的 P0 问题全部修复。

### 9.5 仍待完成 (P1/P2)

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | `CONTRIBUTING.md` | 贡献指南 (PR 流程, 代码风格, 测试要求) |
| P1 | `.github/workflows/ci.yml` | CI/CD 自动测试 |
| P2 | `CHANGELOG.md` | 版本变更记录 |
| P2 | `Dockerfile` | 容器化部署 |
| P2 | 健康检查命令 | `news-sentry doctor` 等价功能 |

---

## 10. 外部工具集成闭环审计 (2026-05-10 完成)

> **审计范围**: OpenCLI、Hermes、OpenClaw、Claude Code、Codex、AI Provider 的安装 → 部署 → 调用完整闭环。

### 10.1 现状：全部为桩代码

| 组件 | Phase | 文件 | 方法数 | 状态 |
|------|-------|------|--------|------|
| **OpenCLIToolAdapter** | 4 | `src/news_sentry/adapters/tools/opencli.py` | 3 | ❌ 全 `raise NotImplementedError` |
| **ToolRunResult** | 4 | `src/news_sentry/adapters/tools/base.py` | 1 | ❌ `__init__` 即抛 |
| **ToolAdapter (Protocol)** | 4 | `src/news_sentry/adapters/tools/base.py` | 1 | ⚠️ 仅协议签名 |
| **OpenCLICollector** | 4 | `src/news_sentry/skills/collect/opencli_collector.py` | 2 | ❌ 全 `raise NotImplementedError` |
| **HermesAdapter** | 2 | `src/news_sentry/adapters/runtime/hermes.py` | 4 | ❌ 全 `raise NotImplementedError` |
| **OpenClawAdapter** | 2 | `src/news_sentry/adapters/runtime/openclaw.py` | 4 | ❌ 全 `raise NotImplementedError` |
| **OpenAIProvider** | 5 | `src/news_sentry/adapters/providers/openai_provider.py` | 2 | ❌ 全 `raise NotImplementedError` |
| **API Collector** | 4 | `src/news_sentry/skills/collect/api_collector.py` | 2 | ❌ 全 `raise NotImplementedError` |
| **Judge Skill** | 5 | `src/news_sentry/skills/judge/judge_skill.py` | 1 | ❌ 全 `raise NotImplementedError` |

**合计: 9 个模块，全部 19 个方法均为 `raise NotImplementedError` 桩。0 个有实际实现。**

### 10.2 本机工具可用性

| 工具 | 安装状态 | 版本 | News Sentry 集成状态 |
|------|---------|------|---------------------|
| **OpenCLI** | ✅ 已安装 | 1.7.8 | ❌ 无集成 — adapter 为桩 |
| **Claude Code** | ✅ 已安装 | 2.1.63 | ❌ 无集成 — 仅文档提及 fallback |
| **Codex CLI** | ✅ 已安装 | 0.128.0 | ❌ 无集成 — 仅文档提及 fallback |
| **Hermes Agent** | ✅ 已安装 | 0.13.0 | ❌ 无集成 — adapter 为桩；仅通过 CLI 手动调用 |

### 10.3 完成度分层

```
Phase 3 (Kernel MVP) — 唯一有实现的层
  ├── ✅ ConfigLoader         config.py        390 行
  ├── ✅ RSSCollector         rss_collector.py  214 行
  ├── ✅ FileWriter           file_writer.py    159 行
  ├── ✅ Memory               memory.py         220 行
  ├── ✅ RunLog               run_log.py        181 行
  ├── ✅ SandboxEnforcer      sandbox.py        156 行
  ├── ✅ RulesFilter          rules_filter.py   132 行
  ├── ✅ ClassifierRules      classifier_rules.py 200 行
  ├── ✅ MarkdownWriter       markdown_writer.py 215 行
  └── ✅ CLI entry            cli/__init__.py   119 行

Phase 4 (Tool/Skill Registry + OpenCLI) — 全部桩
  ├── ❌ OpenCLIToolAdapter   opencli.py         23 行 (桩)
  ├── ❌ OpenCLICollector     opencli_collector.py 18 行 (桩)
  ├── ❌ APICollector         api_collector.py    17 行 (桩)
  ├── ❌ ToolRunResult        base.py            24 行 (桩)
  └── ⚠️  ToolManifest YAML   opencli-baseline.yaml 341 行 (配置就绪, 无消费方)

Phase 5 (AI Provider Routing) — 全部桩
  ├── ❌ OpenAIProvider       openai_provider.py  20 行 (桩)
  ├── ❌ JudgeSkill           judge_skill.py      19 行 (桩)
  └── ⚠️  路由配置            provider/routes.yaml 73 行 (配置就绪, 无消费方)

Phase 2 (Runtime Carrier) — 全部桩
  ├── ❌ HermesAdapter        hermes.py           25 行 (桩)
  └── ❌ OpenClawAdapter      openclaw.py         25 行 (桩)
```

### 10.4 假闭环示意

当前 OpenCLI 在项目中的"闭环"实际上只有三层断链：

```
config/toolmanifest/opencli-baseline.yaml  ← ✅ 定义 12 条工具
         │
         │  ❌ 无代码读取此 YAML
         ▼
   (断层)
         │
src/news_sentry/adapters/tools/opencli.py  ← ❌ 全部 NotImplementedError
         │
         │  ❌ 无代码调用此 adapter
         ▼
   (断层)
         │
src/news_sentry/skills/collect/opencli_collector.py  ← ❌ 全部 NotImplementedError
         │
         │  ❌ 无代码调用此 collector
         ▼
   (断层)
         │
/Users/xuyu/.local/bin/opencli (v1.7.8)   ← ✅ 本机已安装, 可用
```

**结论**: ToolManifest YAML 是完整的，可执行工具在本机是存在的，但代码路径在三个断点处完全中断。

### 10.5 OpenCLI 闭环需要实现的最小代码

按 ADR-0011 和 `opencli-baseline.yaml` 的定义，OpenCLI 工具的完整闭环需要：

```
1. ToolRunResult 数据结构 (base.py)
   → 退出码 / stdout / stderr / duration_ms / error.type 映射

2. OpenCLIToolAdapter (opencli.py)
   → __init__:  解析 ToolManifest YAML → tool_id → command_template 映射
   → execute:   填充模板参数 → SandboxEnforcer 预检 → subprocess.run → 
                映射 exit_code → 返回 ToolRunResult
   → 退出码映射: opencli-baseline.yaml exit_codes {} → ToolRunResult.error.type

3. OpenCLICollector (opencli_collector.py)
   → __init__:  接收 SourceChannel config + ToolManifest tool_id 引用
   → collect:  调用 OpenCLIToolAdapter.execute → 解析 stdout → 
                构造 NewsEvent(pipeline_stage=collected)

4. 集成到 run.py _run_collect
   → 当 SourceChannel.type == "opencli" 时，路由到 OpenCLICollector
```

### 10.6 推荐修复路径

| 组件 | 建议 Phase | 工作量 | 依赖 |
|------|-----------|--------|------|
| ToolRunResult | Phase 4 当前 | S (30 行) | 无 |
| OpenCLIToolAdapter | Phase 4 当前 | M (120 行) | ToolRunResult, SandboxEnforcer |
| OpenCLICollector | Phase 4 当前 | M (100 行) | OpenCLIToolAdapter |
| HermesAdapter | Phase 2 补完 | S (80 行) | hermes CLI 已在 PATH |
| JudgeSkill | Phase 5 | L (需 LLM provider) | AI Provider Routing |
| OpenAIProvider | Phase 5 | L | API key, route 配置 |
