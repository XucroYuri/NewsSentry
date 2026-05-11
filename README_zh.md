# News Sentry — 新闻哨兵

**框架中立的 Agent Skill Pack，用于持续性新闻监控。**

首个参考目标：**意大利**（意大利语 → 中文，Breaking News 专项）。
核心内核与契约可复用于任何国家、地区或领域。

> **许可证**：[Apache 2.0](LICENSE)
> **Language**: [English Version](README.md)

---

## 目录

- [什么是 News Sentry](#什么是-news-sentry)
- [快速开始](#快速开始)
- [Pipeline 概览](#pipeline-概览)
- [安装](#安装)
- [配置](#配置)
- [使用指南](#使用指南)
- [技术架构](#技术架构)
- [技术栈](#技术栈)
- [开发](#开发)
- [部署](#部署)
- [项目状态](#项目状态)
- [故障排查](#故障排查)

---

## 什么是 News Sentry

News Sentry 是一个**持续性新闻监控平台**，设计为可在 Hermes Agent 或 OpenClaw 运行载体上执行的 Agent Skill Pack。它自动化完整的新闻情报生命周期：

```
RSS/API 信源 → 采集 → 过滤 → 研判 → 输出 (Markdown)
```

**核心原则：**
- **框架中立** — 可运行在 Hermes Agent、OpenClaw 或独立 CLI 上
- **配置驱动** — 新增监控国家无需编写代码
- **无专用前端** — 可视化通过 Obsidian Markdown 渲染 + 飞书/邮件/推送
- **v1 不自动对外发布** — 输出停在 drafts/reviewed，不自动推送到外部
- **双语 Pipeline** — 原生支持意大利语 → 中文翻译

**参考用例 — 意大利全维度监控（Italy Full-Spectrum Monitoring）：**

Phase 12 将信源从 14 个 RSS 扩展至 **60+ 个信源，覆盖 13 个维度**，使用 3 种采集方式（RSS/API/OpenCLI），覆盖 7 个社交媒体平台进行 KOL 监控：

| 维度 | 关注领域 | 信源数 |
|------|---------|--------|
| A. 政治与治理 | 政府、议会、政党、选举 | 15 |
| B. 经济与商业 | 宏观经济、产业、贸易、金融 | 7 |
| C. 外交与国际关系 | EU、NATO、G7、地中海 | 4 |
| D. 安全与防务 | 军事、反恐、网络安全 | 4 |
| E. 司法与法治 | 法院、反腐败、有组织犯罪 | 4 |
| F. 社会与民生 | 医疗、教育、劳工、住房 | 8 |
| G. 科技与数字 | AI、数字化转型、隐私 | 5+ |
| H. 环境与能源 | 气候、可再生能源、灾害 | 5+ |
| I. 移民与人口 | 地中海移民、人口趋势 | 3+ |
| J. 文化与遗产 | 文保、旅游、艺术、时尚 | 5+ |
| K. 宗教与梵蒂冈 | 教廷、天主教、跨宗教 | 4+ |
| L. 涉华议题 | 一带一路、MOU、中资企业 | 5+ |
| M. Other 开放式兜底 | 全域监控、突发检测 | 3+ |

**采集原则：采集阶段零 Token 消耗。** RSS、API、OpenCLI、Playwright MCP 四种方式均不消耗 AI token。

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. 一键安装
bash install.sh --dev

# 3. 干运行 — 验证配置
source .venv/bin/activate
make dry-run

# 4. 采集意大利新闻
make run

# 5. 运行全链路：采集 → 过滤 → 研判 → 输出
make run-all

# 6. 查看数据统计
make stats

# 7. 运行测试和代码检查
make check
```

### 两种 Profile 的区别

| | `local-workstation` | `cloud-vps` |
|---|---|---|
| **用途** | 本地开发/测试/人工审查 | 24h 生产监控 |
| **触发方式** | CLI 手动 / Claude Cowork fallback | Hermes Agent cron / gateway |
| **超时** | 10 分钟 | 30 分钟 |
| **网络** | 宽松（本地调试） | 沙箱策略限制 |
| **推荐用于** | 首次部署验证 | 长期生产运行 |

---

## Pipeline 概览

```
                         ┌──────────────────┐
  RSS Feeds (32+)  ────→ │                  │
  API 端点 (4)    ─────→ │      采集        │ ──→ raw/*.md
  OpenCLI (12+)   ────→ │   (零 Token)     │
  社媒/KOL (7平台) ───→ │                  │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │      过滤         │ ──→ evaluated/*.md
                         │  (91+ 关键词)     │ ──→ archive/*.md
                         │  L0-L3 分类       │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │      研判         │ ──→ evaluated/*.md
                         │ (AI + 规则引擎)   │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │      输出         │ ──→ drafts/*.md
                         │   (Markdown)      │
                         └──────────────────┘
```

**Pipeline 阶段：**

| 阶段 | 输入 | 输出 | 说明 |
|------|------|------|------|
| **collect（采集）** | RSS/API/OpenCLI/社媒配置 | `raw/*.md` | 零 Token 从 60+ 信源采集，覆盖 RSS/API/OpenCLI/社媒 |
| **filter（过滤）** | `raw/*.md` | `evaluated/*.md` | 关键词匹配、L0-L3 13 维分类、去重 |
| **judge（研判）** | `evaluated/*.md` | `evaluated/*.md` | AI 驱动的新闻价值评分、中国相关性、推荐 |
| **output（输出）** | `evaluated/*.md` | `drafts/*.md` | 生成结构化 Markdown 报告 |

**每次运行产出：**
- **RunLog** JSON — 包含各阶段的耗时、计数、错误
- **心跳文件** — 用于健康监控
- **信源健康追踪** — 连续失败次数、成功率
- **自动日志轮转** — 保留最近 100 次运行日志

---

## 安装

### 前置条件

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| **Python** | 3.11+ | 运行时 |
| **pip** | 随 Python | 包管理 |
| **git** | 任意 | 版本控制 |

**零系统级原生依赖** — 所有 Python 包均为纯 Python wheel，不需要 `libxml2`、`libxslt` 或其他 C 扩展编译工具链。

### 安装脚本

```bash
# 开发安装（含 pytest、ruff、mypy）
bash install.sh --dev

# 生产安装（仅核心依赖）
bash install.sh
```

脚本会创建 `.venv` 虚拟环境并安装所有依赖。`.env` 文件会从 `.env.example` 自动创建。

### 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # 开发环境
pip install -e .                 # 仅生产环境
pip install -e ".[proxy]"        # 含 SOCKS5 代理支持
```

### 依赖说明

**核心依赖** (`pyproject.toml`)：
- `pydantic>=2.0` — 数据模型
- `pyyaml>=6.0` — 配置文件解析
- `httpx>=0.27` — HTTP 客户端
- `feedparser>=6.0` — RSS/Atom 解析
- `click>=8.1` — CLI 框架

**开发依赖** `[dev]`：
- `pytest>=8.0`、`pytest-asyncio`、`pytest-cov` — 测试
- `mypy>=1.10` — 静态类型检查（strict 模式）
- `ruff>=0.4` — 代码风格检查
- `jsonschema>=4.21` — JSON Schema 校验

**代理依赖** `[proxy]`：
- `httpx[socks]>=0.27` — SOCKS5 代理支持

---

## 配置

### 目录结构

```
config/
├── targets/           # 监控目标定义
│   ├── italy.yaml     # 意大利目标（13 维度、60+ 信源）
│   └── _template.yaml # 新目标模板
├── sources/italy/     # 信源配置（按采集方式组织）
│   ├── rss/           # 32 个 RSS feed 配置（A-M 维度）
│   ├── api/           # 4 个 API 配置（GDELT、NewsAPI、GNews、ISTAT）
│   ├── opencli/       # 12+ 个 OpenCLI 配置
│   ├── social/        # 社媒账号清单（按平台）
│   │   └── twitter/   # Twitter/X 账号配置（4 维度、60+ 账号）
│   ├── _matrix_governance.yaml  # 自进化 + 健康审计配置
│   └── _browser_fallback.yaml   # 三层浏览器降级配置
├── filters/italy/     # 关键词过滤规则
├── classification/    # L0-L3 分类规则
├── profiles/          # 部署 profile
├── sandbox/           # 沙箱安全策略
├── runtime/           # 运行时载体配置
├── provider/          # AI provider 路由
├── output/            # 输出目标配置
└── toolmanifest/      # 工具清单注册
```

### 添加新监控目标

```bash
# 1. 从模板创建目标配置
cp config/targets/_template.yaml config/targets/{country}.yaml

# 2. 创建信源配置目录
mkdir config/sources/{country}/
# 添加信源 YAML 文件...

# 3. 创建过滤规则
mkdir config/filters/{country}/
# 添加关键词 YAML...

# 4. 运行 — 无需修改代码
make run TARGET={country}
```

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `NEWSSENTRY_PROFILE` | 否 | `local-workstation` | 部署 profile ID |
| `NEWSSENTRY_DATA_DIR` | 否 | `./data` | 数据输出根目录 |
| `NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR` | 否 | `false` | 允许数据目录在项目外（设为 `1`/`true`） |
| `DEEPSEEK_API_KEY` | Phase 5 | — | DeepSeek API 密钥 |
| `OPENAI_API_KEY` | Phase 5 | — | OpenAI API 密钥 |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书推送 Webhook |
| `all_proxy` | 否 | — | SOCKS5 代理（如 `socks5://127.0.0.1:1080`） |

完整列表见 [`.env.example`](.env.example)。

---

## 使用指南

### CLI 命令

```bash
# 执行单阶段
python -m news_sentry.cli run --target italy --stage collect
python -m news_sentry.cli run --target italy --stage filter
python -m news_sentry.cli run --target italy --stage judge
python -m news_sentry.cli run --target italy --stage output

# 执行全链路
python -m news_sentry.cli run --target italy --stage all

# 干运行（仅验证配置，不执行实际操作）
python -m news_sentry.cli run --target italy --stage collect --dry-run

# 使用云端 profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps

# 指定运行 ID（不指定则自动生成）
python -m news_sentry.cli run --target italy --stage all --run-id my-run-001

# 校验配置文件
python -m news_sentry.cli validate --config config/targets/italy.yaml

# 列出可用技能
python -m news_sentry.cli skill list

# 列出可用工具
python -m news_sentry.cli tool list

# 环境健康检查
python -m news_sentry.cli doctor
python -m news_sentry.cli doctor --json
```

### Makefile 快捷命令

```bash
make dry-run              # 验证配置
make run                  # 采集阶段
make run-filter           # 过滤阶段
make run-judge            # 研判阶段
make run-output           # 输出阶段
make run-all              # 全链路
make stats                # 数据目录统计
make latest-log           # 查看最新运行日志
make test                 # 运行测试
make lint                 # ruff + mypy
make check                # lint + test
make fmt                  # 自动修复代码风格
make clean                # 清理构建产物
```

### 信源管理

信源配置在 `config/sources/italy/` 中，按采集方式和维度组织。每个信源：

```yaml
source_id: ansa
type: rss                       # rss | api | opencli | social
dimension: A                    # A-M（13 维分类框架）
url: "https://www.ansa.it/..."
enabled: true
credibility_base: 0.9           # 0.0–1.0
max_items_per_run: 50
timeout_seconds: 30
```

**采集方式（采集阶段全部零 Token）：**

| 方式 | 数量 | Token 消耗 | 用途 |
|--------|-------|------------|------|
| **RSS/Atom** | 32+ 信源 | 零 | 新闻媒体、政府公告、机构信源 |
| **API (JSON)** | 4 信源 | 零 | GDELT、NewsAPI、GNews、ISTAT 统计 |
| **OpenCLI** | 12+ 信源 | 零 | 无 RSS 的政府网站、议会、NGO |
| **OpenCLI Bridge** | 社媒 | 零 | 基于浏览器的社媒监控（Chrome 扩展） |
| **Playwright MCP** | 兜底 | 零 | Bridge 不可用时的第二层降级 |
| **Computer Use** | 最后手段 | Token | 仅 L1 账号，≤3 次/天/源，$5/次上限 |

**社媒 KOL 监控 — 7 平台：**
Twitter/X · Facebook · Instagram · LinkedIn · Telegram · YouTube · TikTok

**三级账号分级：**
- **L1**（必监，active 模式）：逐账号页面访问 — 政府官员、党派领袖
- **L2**（应监，active + semi-active）：重要账号 + feed 浏览 — 记者、智库
- **L3**（可监，semi-active 模式）：feed 发现 — 新兴声音、细分专家

**信源生命周期：** `active` → `degraded`（3 次失败）→ `dead`（10 次失败）→ `archive`

**自进化机制：** 内置健康审计、热点信源发现（GDELT/NewsAPI/趋势）、KOL 清单自动扩展。

### 关键词过滤

过滤阶段使用**词边界正则表达式**匹配 91 个意大利语关键词。关键词在 `config/filters/italy/default.yaml` 中配置：

```yaml
keywords:
  - keyword: Cina
    weight: 1.0
    tag: china_relations
  - keyword: Putin
    weight: 0.9
    tag: international
```

每个事件的 `news_value_score` 计算方式为：`sum(关键词权重 × 100)`。事件需要得分 ≥ 40 才能通过过滤。

### 数据目录

```
data/italy/
├── raw/           # 已采集事件（Markdown + YAML frontmatter）
├── evaluated/     # 已过滤 + 已研判事件
├── drafts/        # 输出 Markdown 报告（v1：不自动对外发布）
├── reviewed/      # 人工审查候选（Phase 5+）
├── published/     # 已批准归档
├── archive/       # 已拒绝 / 重复 / 低价值
├── memory/        # known_item_ids、source_health、cursors、provider_stats
│   ├── known_item_ids.yaml
│   ├── source_health.yaml
│   └── cursors.yaml
└── logs/          # 运行日志 + 心跳文件
    └── .heartbeat-hermes.json
```

---

## 技术架构

```
src/news_sentry/
├── core/              # 框架无关内核
│   ├── config.py      # ConfigLoader — 配置加载 + JSON Schema 校验
│   ├── run.py         # bounded_run — 核心运行生命周期管理器
│   ├── sandbox.py     # SandboxEnforcer — 沙箱策略执行
│   ├── file_writer.py # FileWriter — 文件事件写入
│   ├── memory.py      # Memory — 已知 ID、信源健康、游标
│   ├── run_log.py     # RunLog — 运行日志生成
│   ├── matrix_governance.py  # 信源生命周期状态机 + 自进化
│   └── trend_analyzer.py     # TopicTrend + TrendReport（Phase 11）
├── skills/            # Pipeline 技能
│   ├── collect/
│   │   ├── rss_collector.py       # RSS/Atom feed 采集器
│   │   ├── api_collector.py       # JSON API 采集器
│   │   ├── opencli_collector.py   # OpenCLI 采集器
│   │   ├── social_kol_collector.py # 社媒/KOL 采集（Bridge 驱动）
│   │   └── browser_fallback.py    # 三层降级（Bridge→Playwright→CU）
│   ├── filter/
│   │   ├── rules_filter.py     # 关键词规则过滤器
│   │   └── classifier_rules.py # L0-L3 分类引擎（13 维度）
│   ├── judge/
│   │   ├── rules_judge.py      # 规则评分引擎
│   │   └── judge_skill.py      # AI 研判
│   └── output/
│       └── markdown_writer.py  # Markdown 报告生成
├── adapters/          # 集成桥接层
│   ├── runtime/       # Hermes Agent / OpenClaw 适配器
│   ├── tools/         # OpenCLI 工具适配器
│   └── providers/     # AI Provider 适配器
├── models/            # Pydantic v2 数据模型
│   ├── newsevent.py   # NewsEvent — 核心数据交换对象
│   ├── pipeline_context.py
│   └── manifests.py   # Tool/Skill manifest 模型
└── cli/               # Click CLI 入口
    ├── __init__.py    # run、validate、skill、tool 命令
    └── doctor.py      # 环境健康检查（Bridge、Playwright、Chromium）
```

### 核心设计决策

- **`NewsEvent`** 是唯一跨 Agent 数据对象（不引入竞争 schema）
- **0–100 分值** 用于 news_value_score、china_relevance、confidence（sentiment_score: -1.0 到 1.0）
- **确定性 ID**：`ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- **Pipeline 阶段**：`collected → filtered → judged → outputted`
- **v1 不自动对外发布**：输出停在 `drafts/`
- **配置优于代码**：所有意大利相关参数在 `config/` 中，不在 `src/` 中
- **外部项目只 install 不 vendor**：不 fork、不 submodule
- **采集阶段零 Token**：RSS、API、OpenCLI、Playwright MCP 均不消耗 AI token
- **13 维分类框架**：A-政治与治理 至 M-Other 开放式兜底，全覆盖
- **三层浏览器兜底**：OpenCLI Bridge → Playwright MCP → Computer Use（仅 L1）
- **信源自进化**：自动化健康审计、热点发现、KOL 清单扩展
- **通知通道无关**：所有告警走 Hermes Agent 配置，不硬编码具体平台

### 鲁棒性特性

| 特性 | 实现 |
|------|------|
| 原子文件写入 | Memory 模块 `.tmp` → `os.replace()` |
| 日志轮转 | 自动保留最近 100 个运行日志 |
| 内存保留策略 | `prune_old_ids(ttl_days=30)` 清理过期 known_item_ids |
| 信源健康降级 | 连续失败 ≥5 次或成功率 <30% 自动暂停 |
| 沙箱安全执行 | SSRF 防护、网络 host 白名单、命令白名单 |
| 并发安全 | Memory YAML I/O 线程锁；run_id 隔离 |
| 错误容错 | `on_failure=log_and_continue` — 单源失败不阻塞下游阶段 |
| 禁用源自动跳过 | `enabled: false` 的信源自动跳过 |

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **语言** | Python 3.11+ | 严格 mypy、ruff lint |
| **数据模型** | Pydantic v2 | 运行时校验 + 序列化 |
| **CLI** | Click 8.1+ | `news-sentry` console script |
| **HTTP** | httpx 0.27+ | RSS/API 抓取，SOCKS5 代理 |
| **RSS** | feedparser 6.0+ | RSS/Atom feed 解析 |
| **配置** | PyYAML 6.0+ | 所有运行时配置 |
| **Schema 校验** | jsonschema 4.21+ | JSON Schema 2020-12 |
| **浏览器自动化** | OpenCLI Bridge / Playwright MCP / Computer Use | 社媒/KOL 三层兜底 |
| **测试** | pytest 8.0+ | 887 个测试，95% 覆盖率 |
| **代码风格** | ruff 0.4+ | 零容忍 |
| **类型检查** | mypy 1.10+ | strict 模式 |
| **CI/CD** | GitHub Actions | Python 3.11 + 3.12 矩阵 |
| **容器** | Docker (python:3.12-slim + Chromium + Xvfb + Node.js + Playwright) | Cloud VPS 零依赖 |
| **存储** | Markdown + YAML frontmatter | Obsidian 兼容 |

---

## 开发

### 环境搭建

```bash
bash install.sh --dev
source .venv/bin/activate
```

### 代码质量

```bash
# 运行所有检查
make check

# 逐项检查
make test        # pytest（887 个测试）
make lint        # ruff + mypy
make fmt         # 自动修复代码风格
```

**质量门禁（提交前必须全部通过）：**
- `ruff check src/news_sentry/` — All checks passed
- `mypy src/news_sentry/` — Success: no issues found
- `pytest tests/` — All passed, 0 failed

### 项目结构

```
.
├── docs/              # 架构文档、ADR、Phase SPEC、SOP
│   ├── spec/          # Phase 规格文档
│   ├── adr/           # 架构决策记录（ADR-0001 至 0016）
│   ├── testing/       # 测试方案 + 验证报告
│   └── brainstorming/ # 设计讨论与参考文档
├── schemas/           # 13 份 JSON Schema 2020-12 契约文件
├── config/            # 所有运行时配置
├── src/news_sentry/   # Python 包
├── tests/
│   ├── unit/          # 单元测试（按模块）
│   └── integration/   # 端到端 pipeline 测试
├── data/              # 运行时数据（gitignored）
├── pyproject.toml
├── Dockerfile
├── Makefile
└── install.sh
```

### Commit 规范

所有 commit message 使用**简体中文**，格式：`<阶段/模块>: <简要描述>`

```
Phase 3 Kernel: 实现 ConfigLoader 配置加载与 schema 校验
Fix: _run_collect 跳过 enabled=false 的源
```

### 关键文档索引

| 文档 | 用途 |
|------|------|
| [AGENTS.md](AGENTS.md) | Agent 指令基准 + 架构权威来源 |
| [docs/contracts-canonical.md](docs/contracts-canonical.md) | 口径规范唯一权威（字段命名/分值量纲/目录映射） |
| [docs/development-plan.md](docs/development-plan.md) | 多阶段开发计划（Phase 1–13） |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR-0001 至 0021 规划） |
| [docs/spec/](docs/spec/) | Phase SPEC 索引 + 组件矩阵 |
| [docs/superpowers/specs/](docs/superpowers/specs/) | Phase 12 设计规格（信源矩阵） |
| [docs/superpowers/plans/](docs/superpowers/plans/) | Phase 12 实现计划（15 任务） |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南 |

---

## 部署

### Docker

```bash
# 构建镜像（含 Chromium + Xvfb + Playwright MCP + Node.js）
docker build -t news-sentry .

# 运行采集（含浏览器支持）
docker run -v $(pwd)/data:/app/data \
  -v $(pwd)/session-profiles:/app/session-profiles \
  -v $(pwd)/chrome-data:/home/appuser/.config/chromium \
  news-sentry run --target italy --stage collect
```

Docker 镜像提供**零依赖 Cloud VPS 部署**：
- Python 3.12 + Chromium + Xvfb（虚拟显示器，支持无头浏览器）
- Node.js + npm + Playwright + `@playwright/mcp`
- Chrome Native Messaging Host（OpenCLI Bridge 通信）
- Chrome 管理策略（扩展白名单）
- `docker-entrypoint.sh` 自动启动 Xvfb
- `docker/verify-bridge.sh` 部署前健康检查

### Hermes Agent（推荐生产环境）

News Sentry 设计为在 **Hermes Agent** 上运行的 Skill Pack。Hermes Agent 负责：
- 基于 Cron 的定时调度
- Gateway 触发的执行
- 心跳监控
- 运行生命周期管理

`HermesAdapter`（Phase 2）提供桥接层。详见 `config/runtime/hermes.yaml`。

### OpenClaw（生态兼容）

OpenClaw Skill 运行时提供替代载体。`OpenClawAdapter`（Phase 2 桩）负责：
- Skill 发现与注册
- ClawHub 生态兼容
- 运行状态查询

### 独立 CLI / Cron

在没有 Hermes Agent 的环境中：

```bash
# cron 示例 — 每 15 分钟运行一次
*/15 * * * * cd /path/to/NewsSentry && .venv/bin/python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

---

## 项目状态

### 已完成（v0.4.0）

| Phase | 状态 | 描述 |
|-------|------|------|
| 1 — 契约稳定化 | ✅ 完成 | ADR-0001~0016、13 份 JSON Schema、口径契约 |
| 2 — 运行时载体对齐 | ✅ 完成 | Profile 体系、RuntimeHostAdapter 协议、Docker |
| 3 — 内核 MVP | ✅ 完成 | bounded_run、RSS/API 采集、过滤、研判、输出 |
| 4 — 工具/技能注册 | ✅ 完成 | OpenCLI 基线、注册表、APICollector |
| 5 — AI Provider 路由 | ✅ 完成 | 多 Provider 路由、研判/翻译/分类、成本预算 |
| 6 — 沙箱强化 + 社媒 | ✅ 完成 | 完整沙箱策略、session profile、KOL 实验 |
| 7 — 多目标扩展 | ✅ 完成 | 第二目标 `china-watch-en` |
| 8 — Obsidian 本体同步 | ✅ 完成 | 知识库与本体图双向同步 |
| 9 — Karpathy 技能集成 | ✅ 完成 | Karpathy 四原则 + 四心智模型 |
| 10 — 结构化日志 + Doctor | ✅ 完成 | JSON 日志、CLI doctor 诊断命令 |
| 11 — 趋势分析 | ✅ 完成 | TopicTrend + TrendReport 生成 |

### 进行中（v0.5.0）

| Phase | 状态 | 描述 |
|-------|------|------|
| 12 — 意大利信源矩阵 | 🔄 进行中 | 60+ 信源、13 维度、7 社媒平台、浏览器兜底 |
| 13 — 评估集 + 云端部署 | 📋 计划中 | ≥100 标注评估集、Cloud VPS 零依赖部署 |

运行 `make progress` 可查看本地/远端 Git 同步与路线图阶段状态。

### 当前指标

| 指标 | 值 |
|------|-----|
| 版本 | `0.4.0` → `0.5.0` (Phase 12) |
| 测试 | 887 passed, 0 failed |
| 覆盖率 | 95% |
| Lint (ruff) | All checks passed |
| Type (mypy) | 全部源文件，零问题 |
| 活跃目标 | 2（`italy`、`china-watch-en`） |
| 规划信源（意大利） | 60+ 跨 13 维度、3 种采集方式、7 社媒平台 |
| Pipeline 阶段 | 4（采集、过滤、研判、输出） |
| ADR | 16 已落地 + 5 规划中（ADR-0017–0021） |

---

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: news_sentry` | venv 未激活或未安装 | `bash install.sh --dev` |
| `corriere: SSL: UNEXPECTED_EOF` | Corriere della Sera 间歇性 SSL 问题 | 正常，其他信源不受影响，下次运行自动重试 |
| `agi: 404 / fao-rss: 404` | RSS 订阅地址已永久失效 | 这些信源已设为 `enabled: false`，无需处理 |
| `No module named 'news_sentry.cli'` | 工作目录不在项目根 | `cd /path/to/NewsSentry` |
| 过滤阶段输出为 0 | 无匹配关键词的新新闻（全部已被 known_ids 去重） | 等待新新闻；检查 `config/filters/italy/default.yaml` |
| adapters/ 覆盖率低 | Phase 2/5 桩代码未测试 | 预期行为 — 这些是设计意图的桩实现 |

---

## 许可证

Copyright 2026 XucroYuri

本项目采用 [Apache License 2.0](LICENSE) — 自由使用、修改、分发，含专利授权与免责条款。
