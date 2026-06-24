# News Sentry — CLAUDE.md

> 行为基线源自 [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) （Karpathy 四原则，中文版）。
> 项目架构与领域规范见 `AGENTS.md`（跨 Agent 共用基准）。

---

## 行为基线：Karpathy 四原则

### 1. 先思考再编码

**不要假设。不要隐藏困惑。呈现权衡。**

实现之前：
- 明确陈述你的假设。如果不确定，**先问清楚**再动手。
- 当一个需求存在多种解读时，把它们列出来——不要默默选一个。
- 如果存在更简单的方案，**直接说出来**。该提出异议时就提出。
- 如果某件事不清楚，**停下来**。指出困惑所在，然后问。

### 2. 简洁优先

**用最少代码解决问题。不做多余的事。**

- 不添加需求之外的功能。
- 不为一次性调用创建抽象层。
- 不添加未被要求的"灵活性"或"可配置性"。
- 不为不可能发生的场景做错误处理。
- 如果 200 行能写成 50 行，**重写它**。

**检验标准：** 一个资深工程师会认为这段代码过度复杂吗？如果会，简化它。

### 3. 精准修改

**只碰必须碰的。只清理自己造成的混乱。**

编辑已有代码时：
- 不要"顺手优化"相邻的代码、注释或格式。
- 不要重构没有坏的东西。
- 匹配现有代码风格，即使你更倾向不同写法。
- 如果注意到无关的死代码，**提一句即可**——不要删。

当你的修改产生了孤儿代码（因你的改动而不再使用的 import/变量/函数）：
- 清理掉。
- 但不要删除预先存在的死代码（除非明确被要求）。

**检验标准：** 每一行修改都应该直接追溯到用户的需求。

### 4. 目标驱动执行

**定义成功标准。循环验证直到达成。**

把指令式任务转化为可验证目标：
- "加个验证" → "先为非法输入写测试，再让测试通过"
- "修这个 bug" → "先写一个能复现的测试，再让它通过"
- "重构 X" → "确保重构前和重构后测试都通过"

对多步骤任务，给出简洁计划：
```
1. [步骤] → 验证: [检查项]
2. [步骤] → 验证: [检查项]
3. [步骤] → 验证: [检查项]
```

---

## 决策框架：Karpathy 心智模型

以下 4 个心智模型来自 Andrej Karpathy 的系统化思维体系，用于项目技术决策：

### March of Nines（工程现实主义）

从 90% 到 99.9% 的工程爬坡比从 0 到 90% 更难。评估任何 AI 管道组件时必须问：

- 这个组件在最差 5% 的场景下表现如何？
- Demo 效果不等于部署可靠性
- 数据飞轮（持续积累真实数据）比模型架构更重要

### 构建即理解

理解的终极检验是能否用最少代码从零重建核心：

- 技术选型时优先选择"能从零重建核心"的方案
- 外部 Skill/工具必须能解释内部原理，否则不予集成
- 不要因为"社区推荐"而跳过理解步骤

### 锯齿状智能（Jagged Intelligence）

LLM 能力分布是锯齿状的——某些维度超人，某些维度犯蠢：

- 不假设 AI 能力均匀分布
- 为已知凹陷点加规则兜底，不靠更大的模型硬解
- 测试时优先找系统性失败模式

### Iron Man 套装 > Iron Man 机器人

构建 AI 应用应该给人穿上套装让人更强大，而不是造替代人的机器人：

- News Sentry 定位为"增强人工研判"，不是"替代人工决策"
- 所有关键判断保留人工介入点
- Agent 编排中，人是监督者，不是旁观者

---

## 项目特定指引

以下规则是对 Karpathy 基线的项目级补充，同样具有约束力。

### 沟通语言

- **默认使用简体中文**进行开发讨论、commit message、代码注释
- 英文用于技术术语、API 命名、schema 字段名
- 意大利语（Italiano）可作为辅助语言，用于意大利新闻源相关的注释和文档
- commit message 优先使用简体中文

### 架构权威来源

修改架构、schema、pipeline 行为、权限、provider 路由或工具执行前，必读：
- `docs/contracts-canonical.md` — 口径规范唯一权威
- `docs/adr/` — ADR-0001 至 ADR-0025
- `schemas/` — 13 份 JSON Schema 2020-12（与 contracts-canonical.md 双向绑定）
- `config/` — 运行时配置骨架

### 核心决策（不可违反）

- **框架中立**：Hermes/OpenClaw 集成放 runtime adapters，不进领域契约
- **v1 不自动对外发布**：停在 drafts → reviewed → published/
- **NewsEvent 为唯一数据对象**：不引入竞争 schema
- **0-100 分值**（除 sentiment_score: -1.0~1.0 和 ValueDimension.weight 外）
- **外部项目只 install 不 vendor**：不 fork、不 submodule
- **前端可选**：默认可视化为 Obsidian Markdown + 飞书/邮件/推送；可选 API 服务器 (FastAPI) + Web UI (React + shadcn/ui，管理后台 + 公开阅读器)，由 `[api]` extras 控制（ADR-0025）；公开阅读器支持 Cloudflare Pages 独立部署（ADR-0027）
- **新闻分类走 metadata.classification**：不进 schema 顶层
- **Python 3.11+ / Pydantic v2**：`src/news_sentry/` 全栈
- **配置走 config/**：禁止硬编码意大利参数到 src/
- **CLI 入口固定**：`python -m news_sentry.cli run --target {id} --stage {collect|filter|judge|output|all} --profile {profile_id}`
- **JSON Schema 是契约校验载体**：所有 config YAML 头部 `# Schema:` 指向对应 schema
- **开源可移植性**：所有 git-tracked 文件中禁止出现用户主目录、外挂卷、系统包管理器路径、虚拟环境内部解释器路径等本机/平台耦合路径；写临时文件统一用 `./data/tmp/`，写日志统一用 `./data/{target_id}/logs/`；个人机器级配置一律入 `CLAUDE.local.md`（gitignored）

### Phase 执行顺序

1. Contract Stabilization ✅
2. Runtime Carrier Alignment ✅
3. Kernel MVP ✅
4. Tool/Skill Registry + OpenCLI ✅
5. AI Provider Routing ✅
6. Sandbox Hardening + Social/KOL ✅
7. Multi-target Expansion ✅
8. v2 重构: OpenCLI 移除 + API 模块化 + 内置 Provider Chain + 质量加固 ✅
9. v2 重构: CI 修复 + 文档对齐 + 发布就绪 (v2.0.0-rc3) ✅
10. M-12 ~ M-29: 代码库质量收尾（测试/类型/前端/文档/CI/ADR） ✅

### 目录协议与文件事件

- `raw/` → collected events（含源文件下载缓存）
- `evaluated/` → filtered and judged events
- `drafts/` → editorial drafts
- `reviewed/` → human/internal-review candidates
- `published/` → approved archive
- `archive/` → rejected/duplicate/low-value
- `memory/` → known IDs, source health, cursors
- `logs/` → run logs, audit logs

保留 `NewsEvent.pipeline_stage` 和 `processing_history`。精确映射见 `docs/contracts-canonical.md §5`。

### 验证预期

提交实现代码前，运行最窄但最有意义的检查。禁止提交 `.DS_Store`、`.env*`、token、cookie、日志文件。`data/tmp/` 目录仅提交 `.gitkeep`。

### 会话启动协议（严格遵循，不可跳过）

每次新会话开始时，在阅读任何文件或进行任何分析之前，必须执行以下命令：

```bash
git log --all --oneline -5 --no-decorate
git branch --show-current
git status --short
```

完成后额外确认本地 main 与 remote 无分歧：
```bash
git fetch origin main --quiet 2>/dev/null
git log main..origin/main --oneline | wc -l | xargs test 0 -eq || echo "WARNING: local main diverged from origin/main"
```

注意：`--all` 确保看到所有分支的最近提交，不遗漏 remote/origin 上的更新。
此检查位于任何工具调用之前，严格遵循，不可跳过。system-reminder 中的 gitStatus 是会话启动前的快照，工具调用后不会自动更新。

### Git 提交规范

- 所有 commit 在推送前必须是已审查完成、无已知质量问题的最终版本。严禁推送后通过 force-push 或 amend 修改已推送的 commit 历史。

- 所有 commit message 默认使用**简体中文**
- 格式：`<阶段/模块>: <简要描述>`
- 示例：`Phase 3 Kernel: 实现 ConfigLoader 配置加载与 schema 校验`
- 每个独立模块完成后立即提交，保持 commit 粒度细、可回溯

---

## 附：CLAUDE.local.md

个人机器级配置（sandbox 路径、API key、浏览器 profile 等）写入 `CLAUDE.local.md`，该文件被 .gitignore 忽略。
