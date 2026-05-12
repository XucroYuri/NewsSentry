<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/tests-1251%20passed-brightgreen.svg" alt="tests" />
  <img src="https://img.shields.io/badge/coverage-92%25-green.svg" alt="coverage" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-strict-success.svg" alt="mypy" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>框架中立的 AI 新闻监控引擎</strong><br>
  RSS/API/社媒采集 → 智能过滤 → AI 研判 → Markdown 输出<br>
  配置驱动，零代码扩展新国家
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> · <a href="#pipeline-总览">架构</a> · <a href="#使用">使用</a> · <a href="#部署">部署</a> · <a href="#能力边界与路线图">路线图</a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README_en.md">English</a>
</p>

---

## News Sentry 是什么？

News Sentry 是一个**持续新闻监控平台**，自动化完成从采集到研判的全流程：

```
70+ 信源采集 → 关键词过滤 → AI 研判评分 → Markdown 输出 + 实时告警
```

**核心特性：**

| 特性 | 说明 |
|------|------|
| **框架中立** | 支持 Hermes Agent、OpenClaw 或独立 CLI 运行 |
| **配置驱动** | 新增监控国家只需添加 YAML，无需写代码 |
| **零 Token 采集** | RSS / API / OpenCLI 采集阶段不消耗 AI Token |
| **5 国已配置** | 意大利、中国、日本、德国、法国 |
| **双语管道** | 原文采集 → 自动翻译 → 中文研判输出 |
| **反馈闭环** | 人工反馈自动优化关键词权重 |
| **信源自进化** | RSS 自动发现 + 健康巡检 + 矩阵自扩展 |
| **无专用前端** | Obsidian Markdown + 飞书/邮件/推送告警 |

---

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. 安装
bash install.sh --dev

# 3. 配置 API Key（至少一个，用于 AI 研判）
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 或 ANTHROPIC_API_KEY

# 4. 验证配置
source .venv/bin/activate
make dry-run

# 5. 运行全链路
make run-all
```

> **首次运行预计 1-2 分钟**，包含：采集意大利 19+ RSS 源 → 过滤 100+ 关键词 → AI 研判 → 输出 Markdown

---

## 安装

### 前置要求

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.11+ | 运行时 |
| pip | 随 Python | 包管理 |
| git | 任意 | 版本控制 |

> **零原生依赖** — 所有 Python 包均为纯 Python wheel，无需 C 编译工具链。

### 一键安装

```bash
bash install.sh --dev      # 开发模式（含 pytest, ruff, mypy）
bash install.sh            # 生产模式
bash install.sh --check    # 安装 + 运行测试
```

### 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # 开发
pip install -e .           # 生产
pip install -e ".[proxy]"  # SOCKS5 代理支持
pip install -e ".[api]"    # FastAPI REST API 网关
```

---

## Pipeline 总览

```
┌───────────────────────────────────────────────────────────────┐
│                        CLI / API 入口                          │
│      python -m news_sentry.cli        FastAPI /api/v1         │
└─────────────────────┬─────────────────────────┬───────────────┘
                      │                         │
┌─────────────────────▼─────────────────────────▼───────────────┐
│                     bounded_run 运行时                          │
│              ConfigLoader + RunLog + Memory                    │
└─────────┬───────────────────────────────────────┬─────────────┘
          │                                       │
 ┌────────▼────────┐                    ┌─────────▼──────────┐
 │   COLLECT 采集   │                    │   FILTER 过滤       │
 │ RSS · API · KOL  │──────────────────→ │ 100+ 关键词评分     │
 │ 零 Token 消耗    │                    │ L0-L3 四层分类       │
 └─────────────────┘                    └─────────┬──────────┘
                                                  │
                                        ┌─────────▼──────────┐
                                        │    JUDGE 研判       │
                                        │ ConfidenceRouter    │
                                        │ 规则 → AI 升级路由  │
                                        └─────────┬──────────┘
                                                  │
 ┌───────────────────────┐              ┌─────────▼──────────┐
 │  告警推送              │◀─────────────│   OUTPUT 输出       │
 │ 飞书 · 邮件 · TG      │              │ Markdown 报告生成   │
 └───────────────────────┘              └─────────┬──────────┘
                                                  │
                                       ┌──────────▼─────────┐
                                       │  FEEDBACK 反馈      │
                                       │ 人工标注 → 规则优化  │
                                       └────────────────────┘
```

### 四个阶段

| 阶段 | 输入 | 输出 | 说明 |
|------|------|------|------|
| **Collect** | RSS/API/OpenCLI 配置 | `raw/` | 从 70+ 源采集，零 Token |
| **Filter** | `raw/` | `evaluated/` + `archive/` | 关键词评分 + L0-L3 分类 + 去重 |
| **Judge** | `evaluated/` | `evaluated/` | AI 新闻价值评分 + 中国关联度 |
| **Output** | `evaluated/` | `drafts/` | Markdown 报告 + 多通道告警 |

### 数据目录

```
data/{target}/
├── raw/           #  采集事件（Markdown + YAML frontmatter）
├── evaluated/     #  过滤 + 研判后的事件
├── drafts/        #  输出报告（v1 不自动发布）
├── reviewed/      #  人工审阅候选
├── published/     #  已批准归档
├── archive/       #  拒绝 / 重复 / 低价值
├── memory/        #  已知 ID / 信源健康 / 游标 / 规则优化状态
└── logs/          #  运行日志 + 心跳
```

### 外部项目依赖

News Sentry 不是一个完全自包含的孤立项目，部分能力依赖外部项目协作实现：

```
┌───────────────────────────────────────────────────────────────────┐
│                        News Sentry                                │
│                  （核心管道 + 配置 + 数据模型）                      │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ Hermes Agent │    │   OpenClaw   │    │     OpenCLI      │    │
│  │  运行时载体   │    │  运行时载体   │    │   CLI 工具桥接    │    │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘    │
│         │                   │                     │              │
│    Cron 调度           Skill 注册              社媒/网站采集     │
│    心跳监控           生态兼容              无 RSS 的信源        │
│    生命周期管理        运行状态查询           浏览器 Bridge       │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

| 项目 | 角色 | 必需？ | 说明 |
|------|------|--------|------|
| **[OpenCLI](https://github.com/jackwener/OpenCLI)** | CLI 工具桥接 | 可选 | 将网站/社媒转为确定性 CLI 命令，用于采集无 RSS 的信源（Twitter、Reddit、政府网站等）。安装：`npm install -g @jackwener/opencli` |
| **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** | 运行时载体 | 可选 | 提供 Cron 调度、心跳监控、生命周期管理。生产环境推荐，开发可用独立 CLI 替代 |
| **OpenClaw** | 运行时载体 | 可选 | 另一种 Skill 运行时，提供 Skill 注册和生态兼容。当前为 stub 适配 |

**关系原则（ADR-0008）：**
- **安装不内嵌** — 外部项目通过系统包管理器安装，不 fork / submodule / vendor
- **包装不重写** — 通过 `ToolManifest` 包装调用外部工具，不复制其逻辑
- **降级可运行** — 无外部项目时仍可独立运行（仅 RSS/API 采集 + CLI 模式）

> 详细接入策略：[docs/external-integration-strategy.md](docs/external-integration-strategy.md)

### 已配置的监控目标

| Target | 语言对 | 信源数 | 关键词规则 |
|--------|--------|--------|-----------|
| 🇮🇹 **italy** | it→zh | 19+ | 100+ |
| 🇨🇳 **china-watch-en** | en→zh | 10+ | 30+ |
| 🇯🇵 **japan** | ja→zh | 19 | 59 |
| 🇩🇪 **germany** | de→zh | 22 | 46 |
| 🇫🇷 **france** | fr→zh | 21 | 45 |

添加新国家（零代码）：

```bash
cp config/targets/_template.yaml config/targets/{country}.yaml
mkdir -p config/sources/{country}/rss config/filters/{country}
make run TARGET={country}
```

---

## 使用

### CLI 命令

```bash
# 单阶段运行
python -m news_sentry.cli run --target italy --stage collect    # 仅采集
python -m news_sentry.cli run --target italy --stage filter     # 仅过滤
python -m news_sentry.cli run --target italy --stage judge      # 仅研判
python -m news_sentry.cli run --target italy --stage output     # 仅输出

# 全链路
python -m news_sentry.cli run --target italy --stage all

# 其他 target
python -m news_sentry.cli run --target japan --stage all
python -m news_sentry.cli run --target germany --stage all

# 干运行（验证配置，不写文件）
python -m news_sentry.cli run --target italy --stage all --dry-run

# 生产 profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps

# 系统诊断
python -m news_sentry.cli doctor --target italy
```

### Makefile 快捷命令

```bash
make dry-run        # 验证配置
make run            # 采集
make run-all        # 全链路
make check          # lint + test
make stats          # 查看数据统计
make latest-log     # 查看最新运行日志
make doctor         # 系统诊断
make help           # 查看所有命令
```

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | 至少一个 | — | OpenAI API Key |
| `ANTHROPIC_API_KEY` | 至少一个 | — | Anthropic API Key |
| `DEEPSEEK_API_KEY` | 否 | — | DeepSeek API Key |
| `NEWSSENTRY_API_KEY` | 否 | — | API 网关认证 Key |
| `NEWSSENTRY_PROFILE` | 否 | `local-workstation` | 部署 profile |
| `HTTPS_PROXY` | 否 | — | 代理（如 `socks5://127.0.0.1:1080`）|

---

## 部署

### Docker（推荐）

```bash
docker build -t news-sentry .
docker run -d \
  --name news-sentry \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v /data/news-sentry:/app/data \
  -p 8000:8000 \
  news-sentry
```

### API 服务

```bash
pip install ".[api]"
NEWSSENTRY_API_KEY=your-key \
  uvicorn news_sentry.core.api_server:create_app \
  --factory --host 0.0.0.0 --port 8000

# 健康检查
curl http://localhost:8000/api/v1/health

# 查询事件
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/v1/events?target_id=italy&page=1&page_size=20"
```

> 详细部署指南：[docs/deployment-guide.md](docs/deployment-guide.md)

### systemd

```bash
sudo cp config/news-sentry.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-sentry
```

### Cron（无 Docker）

```bash
*/15 * * * * cd /path/to/NewsSentry && .venv/bin/python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

---

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 语言 | Python 3.11+ | strict mypy + ruff |
| 数据模型 | Pydantic v2 | 运行时校验 + 序列化 |
| CLI | Click 8.1+ | `news-sentry` 命令 |
| HTTP | httpx 0.27+ | SOCKS5 代理支持 |
| RSS | feedparser 6.0+ | RSS/Atom 解析 |
| API | FastAPI 0.110+ | REST API + OpenAPI 3.1 |
| 配置 | PyYAML 6.0+ | 全 YAML 配置驱动 |
| 存储 | Markdown + YAML | Obsidian 兼容 |
| 测试 | pytest 8.0+ | 1251 tests / 92% coverage |

---

## 开发

```bash
make check         # lint + test（提交前必须通过）
make test          # 运行测试
make lint          # ruff + mypy
make fmt           # 自动修复代码风格
make scan-sensitive # 扫描敏感数据
make eval          # 运行评估集
```

**质量门禁：**
- `ruff check` — 0 errors
- `mypy —strict` — 0 issues
- `pytest` — 1251 passed

---

## 能力边界与路线图

### 现状 vs 计划

```
                        ┌─────────────────────────────────────────────┐
                        │           News Sentry 能力全景               │
                        └────────────────────┬────────────────────────┘
                                             │
          ┌──────────────────────────────────┼──────────────────────────────────┐
          │                                  │                                  │
    ┌─────▼─────┐                    ┌────────▼────────┐                ┌────────▼────────┐
    │  ✅ 已实现  │                    │  🔧 部分实现     │                │  📋 计划中       │
    └─────┬─────┘                    └────────┬────────┘                └────────┬────────┘
          │                                  │                                  │
   ┌──────┴──────┐                  ┌────────┴────────┐                ┌────────┴────────┐
   │ · 70+ 信源   │                  │ · VPS 72h 验证   │                │ · 更多 Target    │
   │ · 5 国配置   │                  │ · KOL 仍为实验通道│                │   (韩国/英国等)  │
   │ · AI 研判    │                  │ · 信源自进化需    │                │ · 多 Agent 协作  │
   │ · 关键词过滤  │                  │   更多真实数据积累 │                │ · 知识图谱构建   │
   │ · 反馈闭环   │                  └─────────────────┘                │ · 实时仪表盘     │
   │ · REST API   │                                                     └─────────────────┘
   │ · 告警推送   │
   │ · 安全审计   │
   └─────────────┘
```

### 优势与局限

| 维度 | ✅ 优势 | ⚠️ 局限 |
|------|--------|---------|
| **采集** | 70+ 源 / 零 Token / 自动发现 | 社媒 KOL 仍为实验通道，依赖外部 Bridge |
| **研判** | 规则 + AI 双路由 / 准确率 >70% | AI 研判存在误判，不可替代人工决策 |
| **多语言** | 5 国配置 / it/en/ja/de/fr | 翻译质量依赖 AI，专业术语可能偏差 |
| **部署** | Docker 零依赖 / API 网关 | VPS 长期稳定性需实际验证 |
| **反馈** | 人工标注 → 规则自优化 | 需要足够反馈数据才有效果 |

### 项目状态

**v1.0.0 — 全部 23 个 Phase 已完成**

| 阶段 | 版本 | 状态 |
|------|------|------|
| 基础平台（P1-P7） | v0.1–v0.3 | ✅ 完成 |
| 迭代改进（P8-P11） | v0.4 | ✅ 完成 |
| 信源矩阵 + 评估集（P12-P13） | v0.5 | ✅ 完成 |
| AI 优化 + 云部署（P14-P15） | v0.6 | ✅ 完成 |
| 生产化 + 多目标（P16-P18） | v0.7 | ✅ 完成 |
| 多语言 + 反馈闭环（P19-P20） | v0.8 | ✅ 完成 |
| 生态集成（P21-P22） | v0.9 | ✅ 完成 |
| 稳定发布（P23） | v1.0 | ✅ 完成 |

| 指标 | 值 |
|------|-----|
| 测试 | 1251 passed |
| 覆盖率 | 92% |
| Lint | ruff = 0 errors |
| 类型 | mypy strict = 0 issues |
| Target | 5 个国家 |
| 信源 | 70+ |
| Phase | 23/23 完成 |

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [架构总览](docs/architecture.md) | 系统架构、数据流、目录结构 |
| [API 文档](docs/api-reference.md) | REST API 端点、认证、Webhook |
| [部署指南](docs/deployment-guide.md) | Docker / VPS / API / systemd |
| [安全审计](docs/security-audit-report.md) | OWASP Top 10 审计报告 |
| [外部项目接入策略](docs/external-integration-strategy.md) | OpenCLI/Hermes/OpenClaw 接入与版本约束 |
| [开发计划](docs/development-plan.md) | 23 Phase 路线图 |
| [契约规范](docs/contracts-canonical.md) | 字段命名、评分、目录映射 |
| [ADR](docs/adr/) | 架构决策记录（ADR-0001 ~ 0022）|
| [Phase SPEC](docs/spec/) | 各阶段实现规格 |

---

## 免责声明与风险提示

### 外部资源与第三方服务

News Sentry 采集和处理来自以下外部来源的信息：

| 类别 | 说明 |
|------|------|
| **新闻信源** | RSS/API 采集的内容版权归原始发布方所有，本项目不拥有、不担保其准确性 |
| **AI 服务** | OpenAI / Anthropic / DeepSeek 的研判结果由 AI 模型生成，可能存在幻觉或偏差 |
| **社媒平台** | Twitter/Facebook 等平台内容受其各自服务条款约束 |
| **推送渠道** | 飞书/邮件/Telegram 等推送服务由第三方运营，可用性不受本项目控制 |

> **采集合规设计**：News Sentry 的采集以**索引链接**为核心方式，收录的是新闻的元数据（标题、链接、来源、发布时间）和 AI 研判摘要，而非原始稿件全文拷贝。每条记录均保留完整的原始链接，确保信源**透明、可追溯**，在最大限度降低侵权风险的同时保留信息价值。

本项目**不对外部服务的可用性、准确性和合规性做任何担保**。

### 使用合规要求

```
┌──────────────────────────────────────────────────────────────┐
│                    ⚠️  使用前必须了解                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. 遵守当地法律                                             │
│     → 各国对新闻采集、数据存储、个人信息处理有不同法规          │
│     → 使用前请确认您的用途符合所在司法管辖区的法律要求          │
│                                                              │
│  2. 尊重信源权利                                             │
│     → RSS/API 采集应遵守源站的 robots.txt 和服务条款           │
│     → 不得用于大规模爬取、内容抄袭或侵犯版权                   │
│                                                              │
│  3. AI 研判不可替代人工决策                                   │
│     → AI 评分仅作参考，重要判断必须由人工复核                  │
│     → 不可将 AI 研判结果作为唯一依据做出发布或传播决策          │
│                                                              │
│  4. 禁止非法用途                                             │
│     → 不得用于传播虚假信息、操纵舆论、监控个人或非法情报活动    │
│     → 不得用于任何违反人权、隐私权或数据保护法规的目的          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**风险提示：**
- 采集的新闻内容可能包含错误或不实信息，本项目不对内容准确性负责
- AI 研判结果可能因模型版本、提示词变化而产生不一致
- 部分信源可能因网站变更而失效，信源健康度会自动标记但无法保证实时性
- 本项目按"原样"提供，不提供任何明示或暗示的保证

### 许可证

Copyright 2026 XucroYuri. Licensed under the [Apache License 2.0](LICENSE).
