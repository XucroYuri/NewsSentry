# News Sentry — Claude Code 全量开发任务 Prompt

> **驱动方式**: 将此文件作为 Claude Code session 的系统级任务指令。
> **用法**: `claude --prompt "$(cat CLAUDE-PROMPT.md)"` 或粘贴到 Claude Code 交互会话。
> **生成于**: 2026-05-10 | 基于 Hermes Agent 2 轮 PDCA 测试反馈

---

你是一个在 `/Volumes/SSD/Code/06-dev-tools/NewsSentry` 项目中工作的开发 Agent。
项目是 **News Sentry** — 框架无关的 Agent Skill Pack，用于持续新闻监控，首个参考目标是意大利 (Breaking News)。
你的任务是从当前 Phase 3 Kernel MVP 基线出发，修复所有已知问题并推进 Phase 4 实现。

## 项目架构理解（必读）

操作前阅读以下文件：
- `AGENTS.md` — Agent 指令基准
- `docs/contracts-canonical.md` — 口径规范唯一权威（字段命名、分值量纲、目录映射）
- `docs/development-plan.md` — 七阶段开发计划
- `docs/testing/hermes-agent-test-feedback.md` — 全量已知问题清单（631 行，10 章节）
- `docs/spec/phase-4-tool-skill-registry-opencli.md` — Phase 4 SPEC

核心原则（不可违反）：
1. Python 3.11+ / Pydantic v2，包名 `news-sentry`，导入 `news_sentry.*`
2. CLI 入口: `python -m news_sentry.cli run --target {id} --stage {stage} --profile {profile}`
3. 配置走 `config/`，禁止硬编码意大利参数到 `src/`
4. `NewsEvent.pipeline_stage` 用过去分词: collected/filtered/judged/outputted
5. `NewsEvent.id` 格式: `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
6. 分值 0–100（除 sentiment_score: -1.0~1.0）
7. 文件事件目录: raw/ evaluated/ drafts/ reviewed/ published/ archive/ memory/ logs/
8. 沙箱: SandboxEnforcer 在工具执行前校验
9. v1 不自动对外发布，停在 drafts/reviewed
10. 禁止写入 cookies/tokens/passwords/API keys 到 NewsEvent/logs/config

---

## 任务清单（按优先级执行）

### Phase A: 内核修复（Phase 3 补完）

#### A-1: 修复 NewsEvent.id 格式 — 添加 target_id 段
- 当前: `ne-repubblica-20260509-a742c564`
- 期望: `ne-italy-repubblica-20260509-a742c564`
- 修改 `src/news_sentry/models/newsevent.py::NewsEvent.make_id()`，增加 `target_id` 参数
- 修改调用方 `src/news_sentry/skills/collect/rss_collector.py::_entry_to_event()` 传入 `target_id`
- 更新测试 `tests/unit/test_newsevent.py`
- 更新 `docs/contracts-canonical.md §3` 示例如果还有旧格式

#### A-2: 实现 Source Health 记录
- 规格: `development-plan.md §4 P3.W3.07`
- 在 `src/news_sentry/core/memory.py` 中添加 `record_source_health(source_id, success, error_msg, run_id)` 方法
- 在 `src/news_sentry/core/run.py::_run_collect()` 中，每个 source 采集后调用
- 产出文件: `data/{target_id}/memory/source_health.yaml`
- 格式:
```yaml
source_id:
  last_success_at: ISO8601
  last_failure_at: ISO8601
  consecutive_failures: int
  last_error: string
  total_runs: int
  total_failures: int
```
- 编写测试 `tests/unit/test_memory.py` 补充 source_health 用例

#### A-3: 补全目录协议 — reviewed/published/archive
- 在 `src/news_sentry/core/run.py::_run_filter()` 中，被拒事件写入 `archive/`(pipeline_stage=filtered)
- 在 `src/news_sentry/core/run.py::_run_output()` 完成后，drafts 移入 `published/`
- `data/{target_id}/` 下确保 reviewed/, published/, archive/ 目录在首次写入时自动创建
- 更新 `src/news_sentry/core/file_writer.py` 支持 archive/ 写入

#### A-4: Output stage 更新 pipeline_stage
- 当前 drafts/ 文件 `pipeline_stage: filtered`
- 修复: `src/news_sentry/skills/output/markdown_writer.py` 写 drafts 时将 `pipeline_stage` 设为 `outputted`
- 或修复 `src/news_sentry/core/run.py::_run_output()` 在写入前更新 NewsEvent

#### A-5: 对齐 classification 字段命名
- 契约要求 (`contracts-canonical.md §9`): `l0`, `l1[]`, `l2[]`, `l3`, `confidence`
- 当前实现: `l0_domain`, `l1_topics`, `l2_country_axes`, `l3_tags`, `l0_confidence`
- 决策: 修改实现对齐契约（契约是规范基准）
- 涉及: `src/news_sentry/skills/filter/classifier_rules.py`, `config/classification/rules-v1.yaml`, `tests/unit/test_classifier_rules.py`
- 同步更新 `schemas/classification.schema.json`

---

### Phase B: 外部工具集成闭环（Phase 4）

#### B-1: 实现 ToolRunResult
- 文件: `src/news_sentry/adapters/tools/base.py`
- 完整实现 `ToolRunResult` dataclass:
```python
@dataclass
class ToolRunResult:
    tool_id: str
    run_id: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    error: dict | None  # {"type": "timeout"|"permission_denied"|..., "message": str}
```
- 编写测试 `tests/unit/test_tool_adapter.py`

#### B-2: 实现 OpenCLIToolAdapter
- 文件: `src/news_sentry/adapters/tools/opencli.py`
- `__init__`: 加载 `config/toolmanifest/opencli-baseline.yaml`，构建 `tool_id → command_template` 映射
- `_build_command(tool_id, args)`: 用 `{param}` 模板填充，返回 `list[str]`
- `execute(validated_args, run_id)`: 
  1. SandboxEnforcer.enforce() 预检（跳过已在此 adapter 内执行 subprocess 的 command 检查 — 只检查 host 和 path）
  2. subprocess.run(command, capture_output=True, timeout=...)
  3. 根据 ToolManifest exit_codes 映射 → ToolRunResult
- 退出码映射规则（基于 opencli-baseline.yaml）:
  - exit_code 0 → success=True, error=None
  - exit_code 1 → 对应 tool 定义的错误 type（如 fetch_failed）
  - exit_code 2 → timeout
  - exit_code 3 → permission_denied
- 编写测试

#### B-3: 实现 OpenCLICollector
- 文件: `src/news_sentry/skills/collect/opencli_collector.py`
- `__init__`: 接收 SourceChannel config + OpenCLIToolAdapter + SandboxEnforcer
- `collect(run_id)`: 
  1. 从 SourceChannel config 读取 `tool_ref`(如 "opencli.fetch") + `validated_args`
  2. 调用 OpenCLIToolAdapter.execute()
  3. 解析 stdout (JSON) → 构造 `list[NewsEvent]`, pipeline_stage=COLLECTED
- SourceChannel 配置新增字段支持:
```yaml
# config/sources/italy/{source_id}.yaml
type: opencli           # 新增类型
tool_ref: opencli.fetch # 引用 toolmanifest 中的 tool_id
validated_args:         # 模板参数
  url: "https://..."
  output_path: "./data/italy/raw/opencli_output.json"
```
- 编写测试

#### B-4: 集成到 run.py
- 在 `_run_collect()` 中，根据 `SourceChannel.type` 路由:
  - `type == "rss"` → RSSCollector（已有）
  - `type == "opencli"` → OpenCLICollector（新增）
  - `type == "api"` → APICollector（标记 TODO Phase 4+）

---

### Phase C: 部署与文档基础设施

#### C-1: 创建 CONTRIBUTING.md
- 包含: PR 流程、代码风格（ruff）、类型检查（mypy）、测试要求（pytest 282+）、commit 规范

#### C-2: 创建 .github/workflows/ci.yml
- Python 3.11 + 3.12 矩阵
- 步骤: pip install -e ".[dev]" → ruff → mypy → pytest
- 触发: push + PR to main

#### C-3: 添加健康检查命令
- 新增 CLI: `python -m news_sentry.cli doctor`
- 检查项: Python 版本、依赖导入、config 加载、schema 校验、数据目录权限、可选工具可用性（opencli/hermes/codex/claude）

#### C-4: 创建 Dockerfile
- 基于 `python:3.12-slim`
- 安装项目 + 生产依赖
- ENTRYPOINT: `python -m news_sentry.cli run`

---

### Phase D: 意大利 Breaking News 信源扩展

#### D-1: 验证并添加新 RSS 源
- 对以下 URL 逐一 curl 验证可达性，成功则创建 `config/sources/italy/{source_id}.yaml`：
  1. Rai News: `https://www.rainews.it/rss/`
  2. TgCom24: `https://www.tgcom24.mediaset.it/rss/`
  3. Sky TG24: `https://tg24.sky.it/rss/`
  4. Il Sole 24 Ore: `https://www.ilsole24ore.com/rss/`
  5. La Stampa: `https://www.lastampa.it/rss/`
  6. Il Messaggero: `https://www.ilmessaggero.it/rss/`
  7. Il Fatto Quotidiano: `https://www.ilfattoquotidiano.it/feed/`
  8. The Local Italy (EN): `https://www.thelocal.it/feeds/rss/`
  9. ANSA English: `https://www.ansa.it/english/english_rss.xml` 或 `https://www.ansa.it/english/`
  10. EUR-Lex: `https://eur-lex.europa.eu/rss/`
- 每个成功的源创建配置时参考 `config/sources/italy/_template.yaml`
- 更新 `config/targets/italy.yaml` 的 `source_channel_refs` 列表
- 恢复 `agi.yaml` 和 `fao-rss.yaml` 的 URL 如果能找到有效替代

#### D-2: 补充 filter 关键词
- 在 `config/filters/italy/default.yaml` 中添加 Breaking News 专项关键词：
  - 突发事件: `attentato`(袭击), `terremoto`(地震), `alluvione`(洪水), `incendio`(火灾), `esplosione`(爆炸), `emergenza`(紧急), `disastro`(灾难), `allarme`(警报)
  - 政治危机: `crisi di governo`, `dimissioni`(辞职), `scioglimento`(解散), `fiducia`(信任案)
  - 经济冲击: `crollo`(暴跌), `default`, `spread BTP-Bund`, `recessione`(衰退)

---

## 验证标准

每完成一个任务后运行:
```bash
.venv/bin/python -m ruff check          # 必须: All checks passed
.venv/bin/python -m mypy src/news_sentry/  # 必须: Success: no issues
.venv/bin/python -m pytest tests/ -q --tb=short  # 必须: 全部通过
```

全部完成后执行完整集成测试:
```bash
python -m news_sentry.cli run --target italy --stage collect --profile local-workstation --dry-run
python -m news_sentry.cli run --target italy --stage collect --profile local-workstation
python -m news_sentry.cli run --target italy --stage all --profile local-workstation
```

## 完成标准

- [ ] A-1: NewsEvent.id 包含 target_id 段
- [ ] A-2: source_health.yaml 有实际记录
- [ ] A-3: archive/ 有被拒事件, published/ 有输出
- [ ] A-4: drafts/ 文件 pipeline_stage = outputted
- [ ] A-5: classification 字段名对齐契约
- [ ] B-1: ToolRunResult 可用
- [ ] B-2: OpenCLIToolAdapter 可执行 opencli 命令
- [ ] B-3: OpenCLICollector 可产出 NewsEvent
- [ ] B-4: run.py 支持 type=opencli 路由
- [ ] C-1: CONTRIBUTING.md 存在
- [ ] C-2: CI 配置存在
- [ ] C-3: `python -m news_sentry.cli doctor` 可用
- [ ] C-4: Dockerfile 可构建
- [ ] D-1: >= 8 个新 RSS 源可采集
- [ ] D-2: Breaking News 关键词已补充
- [ ] 全量: ruff + mypy + pytest 全部通过

## 故障回退

- 任何步骤失败不阻塞后续：记录到 errors[]，继续下一步
- RSS URL 验证失败：源标记为 `enabled: false`，注释说明原因
- OpenCLI 不存在：OpenCLIToolAdapter.execute() 返回 error="opencli_not_installed"
- 全部完成后汇总 errors[] 并报告
