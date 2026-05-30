<p align="center">
  <img src="https://img.shields.io/badge/version-1.9.1-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>开源 AI 新闻情报与 OSINT 监控平台</strong><br>
  多语言新闻与社媒采集 → 信源健康 → canonical event graph → 专业研究工作流
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#为什么需要-news-sentry">为什么需要</a> ·
  <a href="#核心能力">核心能力</a> ·
  <a href="#系统架构">系统架构</a> ·
  <a href="#典型使用场景">典型使用场景</a> ·
  <a href="#路线图">路线图</a> ·
  <a href="#参与贡献">参与贡献</a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README_en.md">English</a>
</p>

---

## News Sentry 是什么？

News Sentry 是一个 local-first 的开源系统，用于持续 **AI 新闻情报**、**OSINT 监控平台** 和专业研究工作流。

它持续采集多语言新闻、RSS、API、社媒和公共网页信源，并帮助研究者把碎片化报道整理为结构化事件、信源健康状态、告警、Markdown 简报和 canonical event graph。

它不是普通 RSS reader，也不是一次性爬虫脚本，而是面向长期运行和人工复核的新闻情报基础设施。

## 为什么需要 News Sentry？

大多数监控工具止步于收集链接。News Sentry 关注完整情报闭环：

```text
采集 → 过滤 → 研判 → 输出 → 复核 → canonical graph → research artifact
```

关键区别是：一篇报道只是一次 **event mention**，不是事实本身。多家媒体、多语言、多平台报道可以归并为 canonical event，而人在回路的复核、标注、合并、拆分和研究笔记会保存为 research artifacts，不会静默污染事实层。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 多语言新闻监控 | 已配置意大利、日本、德国、法国和英文涉华报道 target |
| RSS/API/OpenCLI 采集 | 采集阶段零 token，支持 feeds、API、网站和可选工具适配 |
| 信源健康 | 跟踪信源可用性、运行诊断、陈旧 feed 和生命周期 |
| AI 研判 | 规则优先，AI 辅助新闻价值、涉华相关度、情绪和置信度评分 |
| canonical event graph | 区分现实事件、报道 mention、关系、分类和实体 |
| 专业研究工作流 | 复核队列、人工标注、merge/split 决策和 research artifacts |
| 本地优先部署 | 支持 CLI、FastAPI Web UI、桌面包装、Docker 和未来云端 worker |
| 人在回路 | AI 辅助筛选和分析，关键研究判断保留可审计人工介入 |

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

## 系统架构

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
| **Judge** | `evaluated/` | `evaluated/` | AI 新闻价值评分 + 涉华议题关联度 |
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

| Target | 语言对 | 信源数 | 关键词规则 | 说明 |
|--------|--------|--------|-----------|------|
| 🇮🇹 **italy** | it→zh | 19+ | 100+ | 意大利全维度新闻 |
| 🇬🇧 **china-watch-en** | en→zh | 5 | 30+ | 英文主流媒体（SCMP/Reuters/BBC/Guardian/NYT）涉华报道 |
| 🇯🇵 **japan** | ja→zh | 19 | 59 | 日本全维度新闻 |
| 🇩🇪 **germany** | de→zh | 22 | 46 | 德国全维度新闻 |
| 🇫🇷 **france** | fr→zh | 21 | 45 | 法国全维度新闻 |

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

# 后台常驻服务
news-sentry serve                           # 默认配置, localhost:8000, 全管道
news-sentry serve --target italy            # 单 target
news-sentry serve --stage collect           # 仅采集（不研判，零 token）
news-sentry serve --port 8080 --interval 30 # 自定义端口和采集间隔
news-sentry serve --foreground              # 前台调试 (Ctrl+C 退出)
news-sentry serve --no-browser              # 不自动打开浏览器
news-sentry stop                             # 停止后台服务

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
| 存储 | aiosqlite | SQLite WAL 异步存储 |
| 配置 | PyYAML 6.0+ | 全 YAML 配置驱动 |
| 缓存 | cachetools | LRU 缓存 + TTL |
| 测试 | pytest 8.0+ | 1629 tests / 92% coverage |

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
- `pytest` — 1629 passed

---

## 典型使用场景

- 新闻编辑部和研究团队持续追踪国家、地区、政策、产业和突发事件。
- OSINT 研究者跨语言验证公开信源、报道来源和事件链。
- 分析师监控公共舆情、地缘风险、产业政策和媒体叙事。
- 运维人员管理多目标信源健康、覆盖缺口和采集诊断。
- 本地研究工作台用于复核、标注、合并、拆分和输出 canonical events 简报。

## 路线图

News Sentry 正在从本地新闻监控引擎演进为全球新闻情报平台。

近期重点：

- 修复 run batch 语义、alert history、source inventory 等可靠性根基；
- 建立 shadow canonical data spine，承载 canonical events、mentions、relations、taxonomy 和 research artifacts；
- 落地专业研究工作流 MVP，支持人工复核、merge/split、标注和简报；
- 规划本地轻客户端，让用户选择关注范围并支持离线研究；
- 长期探索半中心化公共采集节点，提升全球本地信源覆盖。

参考文档：

- [全球情报平台商业与架构方向](docs/superpowers/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md)
- [Shadow canonical data spine](docs/superpowers/specs/2026-05-30-shadow-canonical-data-spine-design.md)
- [Professional research workflow MVP](docs/superpowers/specs/2026-05-30-professional-research-workflow-mvp-design.md)

## 参与贡献

欢迎贡献：

- 新国家、地区、语言和信源配置；
- 面向公共网站、RSS、API 和社媒来源的 collector adapter；
- canonical event graph、taxonomy、source health 和研究工作流能力；
- 文档、部署指南和可复现监控样例。

贡献前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[docs/contracts-canonical.md](docs/contracts-canonical.md) 和 [docs/architecture.md](docs/architecture.md)。

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [架构总览](docs/architecture.md) | 系统架构、数据流、目录结构 |
| [API 文档](docs/api-reference.md) | REST API 端点、认证、Webhook |
| [部署指南](docs/deployment-guide.md) | Docker / VPS / API / systemd |
| [安全审计](docs/security-audit-report.md) | OWASP Top 10 审计报告 |
| [外部项目接入策略](docs/external-integration-strategy.md) | OpenCLI/Hermes/OpenClaw 接入与版本约束 |
| [契约规范](docs/contracts-canonical.md) | 字段命名、评分、目录映射 |

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

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=XucroYuri/NewsSentry&type=Date)](https://star-history.com/#XucroYuri/NewsSentry&Date)
