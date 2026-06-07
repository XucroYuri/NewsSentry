# News Sentry — 外部项目接入策略

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **规范文档** — 本文档是所有外部项目接入方式的唯一权威来源
> 相关 ADR: [ADR-0008](./adr/0008-external-deps-install-not-vendor.md)（系统级依赖原则）、[ADR-0025](./adr/adr-0025.md)（CLI-first + FastAPI/Vanilla JS 嵌入式 SPA）、[ADR-0011](./adr/0011-opencli-baseline-toolmanifest.md)（OpenCLI ToolManifest 基线）

---

## §1. 接入边界三原则

**原则 P1：install-not-vendor（安装，不内嵌）**

外部项目通过系统包管理器（`npm install -g`、`pip install`、`brew install`）安装；News Sentry 不 fork、不 Git submodule、不 vendor 源代码到本仓库。版本约束写入 `docs/external-integration-strategy.md`（本文）和对应 ADR，而非锁文件或 package.json，因为 News Sentry v1 不是一个可发布的 npm/pip 包。

**原则 P2：wrap-not-rewrite（包装，不重写）**

已有外部工具的功能，News Sentry 通过 `ToolManifest.executable + argv_template` 包装调用，**不** 在内核中复制其逻辑。若外部工具的输出格式需要适配，写一个轻量 `OutputAdapter`（< 50 行），而非重实现采集逻辑。

**原则 P3：document-the-version（锁版本，写文档）**

每个系统级依赖在本文档和对应 ADR 中注明：最低版本约束（`>=x.y.z`）、升级触发条件（安全补丁或功能需求）、升级审查要求（是否需要新 ADR）。如果外部项目引入破坏性变更，必须新建 ADR 记录适配决策。

---

## §2. OpenCLI 接入

### 2.1 项目定位

[OpenCLI](https://github.com/jackwener/OpenCLI)（19.4k stars）是一个通用 CLI Hub + AI-native 运行时，可以把网站、Electron 应用、本地工具转换为确定性命令行接口。其核心优势是：
- 零 LLM 成本运行：命令输出确定性、可管道化、CI 友好
- 内置 100+ 网站适配器（Twitter、Reddit、Hacker News、Google Scholar、gov-policy 等）
- 支持多 Chrome profile 隔离，账号状态不外泄
- 统一退出码约定（66=空结果、69=浏览器未连接、77=需要登录），与 SandboxPolicy 错误映射对齐

### 2.2 安装方式

```bash
# 系统级安装，不进项目 package.json
npm install -g @jackwener/opencli@latest   # 当前: >=1.7.x

# 浏览器桥接扩展（需手动安装到 Chrome，News Sentry 文档说明）
opencli doctor  # 验证安装
```

**版本约束：** `>=1.7.x`（以 1.7.14 为基线，该版本起退出码稳定）

**升级条件：** 安全补丁可直接升级；破坏性 API 变更需新建 ADR 记录适配。

### 2.3 profile 隔离规则

- 生产 profile（用于采集敏感平台登录态）与开发 profile 必须分离
- News Sentry `ToolManifest` 中的 `opencli` 工具条目，`permissions.browser.session_profile_required = true` 时必须通过 `OPENCLI_PROFILE` 环境变量路由到正确 profile
- 不得在 NewsEvent、frontmatter 或日志中写入 Chrome profile 路径或 Cookie 信息

### 2.4 ToolManifest Baseline（约 12 条命令骨架）

完整 ToolManifest 定义见 [ADR-0011](./adr/0011-opencli-baseline-toolmanifest.md)。下表为意图清单：

| ToolManifest `tool_id` | 包装命令 | 用途 | Phase |
|---|---|---|---|
| `opencli.hackernews.top` | `opencli hackernews top --limit {n} -f json` | 英文科技舆论监控 | Phase 4 |
| `opencli.hackernews.search` | `opencli hackernews search {q} -f json` | 关键词搜索 HN | Phase 4 |
| `opencli.twitter.trending` | `opencli twitter trending -f json` | Twitter 趋势（需登录） | Phase 4 |
| `opencli.twitter.search` | `opencli twitter search {q} --limit {n} -f json` | Twitter 关键词搜索 | Phase 4 |
| `opencli.reddit.hot` | `opencli reddit hot --subreddit {r} -f json` | Reddit 热帖 | Phase 4 |
| `opencli.reddit.search` | `opencli reddit search {q} -f json` | Reddit 搜索 | Phase 4 |
| `opencli.google-scholar.search` | `opencli google-scholar search {q} -f json` | 学术文献检索 | Phase 4 |
| `opencli.gov-policy.search` | `opencli gov-policy search {q} -f json` | 意大利政府政策公告 | Phase 4 |
| `opencli.gov-policy.recent` | `opencli gov-policy recent -f json` | 近期政策动态 | Phase 4 |
| `opencli.zhihu.hot` | `opencli zhihu hot -f json` | 知乎热榜（中文涉华视角） | Phase 4 |
| `opencli.weixin.search` | `opencli weixin search {q} -f json` | 微信公众号搜索 | Phase 6 |
| `opencli.external.custom` | `opencli external {name} {args}` | 自定义本地工具包装 | Phase 4+ |

**风险与降级：**
- 退出码 69（浏览器未连接）→ 标记 source health `status=unavailable`，跳过本次 run
- 退出码 77（需要登录）→ 触发 sandbox violation，写入审计日志，不自动重试
- 退出码 66（空结果）→ 记录 source health `items_fetched=0`，非错误

---

## §3. opencli-admin 借鉴清单

[opencli-admin](https://github.com/xjh1994/opencli-admin) 是一个基于 opencli 的可视化内容采集/AI打标系统（React + FastAPI + Docker）。**News Sentry 不 fork、不引入其代码栈**（见 ADR-0025：CLI-first + Vanilla JS SPA），但以下设计模式值得借鉴：

| 借鉴点 | opencli-admin 原型 | News Sentry 对应实现 |
|---|---|---|
| 5 板块功能结构 | 数据源 / 定时计划 / 采集任务 / 采集记录 / 节点管理 | Skill 按 `collect/filter/judge/output` 分层，`SourceChannel` 对应"数据源"，run log 对应"采集记录" |
| Bridge vs CDP 模式区分 | 登录态平台走 Bridge，公开页走 CDP | `ToolManifest.permissions.browser.session_profile_required` 控制是否需要 Bridge |
| Agent 路由四级优先级 | 手动指定 > 计划绑定 > 站点绑定 > 自动分配 | `SkillManifest` 选择优先级：`target_override > schedule_binding > channel_binding > auto_fallback` |
| Webhook 投递日志 | 每次投递记录 HTTP 状态码、延迟、错误 | `logs/output_dispatch.jsonl`，每条记录 `destination.channel`、`http_status`、`latency_ms`、`error?` |

**明确舍弃：**
- React 18 / TypeScript / Vite / Tailwind 前端栈（ADR-0025；当前前端保持 Vanilla JS）
- SQLAlchemy + PostgreSQL 后端栈（保留 News Sentry 自有 FastAPI + AsyncStore）
- Celery + Redis 任务队列（v1 用文件 memory）
- Docker Compose 多节点 Agent（v1 单机）

---

## §4. Intel_Briefing 模式借鉴

[Intel_Briefing](https://github.com/77AutumN/Intel_Briefing)（124 stars）是一个从 12+ 数据源自动抓取、翻译、分析的情报聚合引擎，用 Gemini 生成中文日报。与 News Sentry 目标重叠度高，但实现路径不同（无 Agent Skill Pack 架构、无沙箱）。

| 借鉴点 | Intel_Briefing 原型 | News Sentry 对应设计 |
|---|---|---|
| Tier 1 / Tier 2 采集分层 | Tier 1（聚合器）走 `fetch_news.py`，Tier 2（独立传感器）走 `sensors/` | `SourceChannel.tier` 字段：`tier1`=RSS/API 聚合，`tier2`=独立采集 Skill（Phase 4+） |
| 防幻觉机制 | Grok fallback 产品标记 `⚠️ 链接未验证 (AI 推断)` | `metadata.translation.status="unverified"` 或 `acquisition.source_type="ai_inferred"` |
| graceful degradation | 缺 API key 时跳过对应源，不崩溃 | SandboxPolicy `hard_stop.missing_api_key=false`；source health 记录 `status=degraded` |
| 数据源清单参考 | HN、GitHub Trending、ArXiv、HF Papers、Product Hunt、TechCrunch、MIT TR | 作为 Phase 4 OpenCLI wrapper 或 RSS 直连的候选源 |
| 优雅退出而非异常抛出 | 每个传感器独立 try/except，失败写 `status=skipped` | 与 `ToolRunResult.error.type` 规范对齐（ADR-0003） |

**GitHub Actions 自动化参考：** Intel_Briefing 的 `.github/workflows/daily-report.yml` 是 Hermes cron 触发模式的可参考参照物。

---

## §5. TrendRadar 模式借鉴

[TrendRadar](https://github.com/sansan0/TrendRadar) 是一个 AI 舆情监控助手（Python + MCP server），支持关键词筛选、多渠道推送（飞书/钉钉/微信/Telegram/Email）、MCP 客户端对接。

| 借鉴点 | TrendRadar 原型 | News Sentry 对应设计 |
|---|---|---|
| 关键词×频率矩阵 | 关键词精准筛选 + 推送阈值配置 | `FilterRules.keyword_matrix`：关键词列表 + 权重 + 频率窗口，驱动 `news_value_score` |
| 多渠道推送 fanout | 飞书/钉钉/企业微信/Telegram/Email/ntfy/Bark/Slack/Webhook | Phase 3 仅飞书 Webhook；Phase 5 扩展为多路 fanout，每路对应 `output_result.destinations[]` 的不同 channel |
| MCP server 暴露形态 | `mcp_server/` 作为 MCP 工具集供 Claude 等客户端调用 | Phase 4+ 可考虑把 News Sentry `collect/judge` Skill 包装为 MCP server（`SkillManifest.mcp_compatible=true`） |
| newsnow API 数据源 | 从 newsnow 项目获取多平台热榜数据 | 作为 Phase 4 RSS/API 候选源之一，通过 `SourceChannel.type=api` 接入 |

---

## §6. 明确舍弃清单

下表记录经过反思后明确不引入 News Sentry v1 的外部项目能力，避免后续 PR 试图重做。

| 能力 | 来源 | 舍弃理由 |
|---|---|---|
| opencli-admin React/FastAPI 栈 | opencli-admin | ADR-0025：保留自有 FastAPI + Vanilla JS，避免引入 React/Vite/Tailwind |
| opencli-admin Docker 多节点 | opencli-admin | v1 单机足够；分布式采集是 Phase 6+ |
| MiroShark 群体智能模拟引擎 | MiroShark | 目标不同：模拟舆论反应 vs 监控真实新闻，v1 超范围 |
| BettaFish MindSpider 爬虫栈 | BettaFish | 已加超 v1 banner；社媒爬虫在 Phase 6 走 OpenCLI 适配 |
| worldmonitor 地图引擎（globe.gl/deck.gl） | worldmonitor | v1/v1.5 超范围；前端保持轻量信息工作台 |
| worldmonitor Country Intelligence Index | worldmonitor | Phase 7+ 考虑；v1 用 `china_relevance` + L0/L1 classification |
| BettaFish ForumEngine 多 Agent 论辩 | BettaFish | v2+ 候选；v1 单 judge Skill 已够 |
| Tauri 桌面应用 | worldmonitor | ADR-0026 另行评估；当前桌面路径先打磨 pywebview |

---

## §7. 版本约束记录

| 外部项目 | 最低版本 | 安装命令 | 升级审查要求 |
|---|---|---|---|
| OpenCLI | >=1.7.14 | `npm install -g @jackwener/opencli@latest` | 破坏性变更需新 ADR |
| Node.js（OpenCLI 依赖） | >=21.0.0 | 系统包管理器或 nvm | 随 OpenCLI 升级要求 |
| Chrome/Chromium（OpenCLI browser 命令） | 稳定版 | 用户自行安装 | OpenCLI doctor 检测 |
