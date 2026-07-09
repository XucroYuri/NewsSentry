# News Sentry — 外部项目接入策略

> 版本: v2.2 | 日期: 2026-07-08
> 状态: **规范文档** — 本文档是所有外部项目接入方式的唯一权威来源
> 相关 ADR: [ADR-0008](./adr/0008-external-deps-install-not-vendor.md)（系统级依赖原则）、[ADR-0025](./adr/adr-0025.md)（CLI-first + FastAPI/Vanilla JS 嵌入式 SPA）
> AI 容量策略: [AI Provider 免费容量与预算兜底策略](./specs/2026-07-03-ai-provider-free-capacity-and-paid-fallback.md)

---

## §1. 接入边界三原则

**原则 P1：install-not-vendor（安装，不内嵌）**

外部项目通过系统包管理器、官方容器、公开 API 或托管服务接入；News Sentry 不 fork、不 Git submodule、不 vendor 源代码到本仓库。版本约束写入本文档和对应 ADR，不把临时锁文件当成系统级依赖权威。

**原则 P2：connect-not-embed（接入，不内嵌）**

已有外部工具的功能，News Sentry 优先通过 API、RSS、容器 sidecar 或小型 adapter 接入，**不** 在内核中复制其逻辑。若外部工具的输出格式需要适配，写清输入、输出、失败边界和测试；不要恢复已经移除的浏览器驱动或大型 Agent 框架。

**原则 P3：document-the-version（锁版本，写文档）**

每个系统级依赖在本文档和对应 ADR 中注明：最低版本约束（`>=x.y.z`）、升级触发条件（安全补丁或功能需求）、升级审查要求（是否需要新 ADR）。如果外部项目引入破坏性变更，必须新建 ADR 记录适配决策。

---

## §2. 外部采集接入（当前方案）

当前采集策略是：能用 RSS/API 的信源走原生 collector；必须桥接的社媒源走 RSS-Bridge；需要浏览器会话、共享账号或逆向接口的方案默认不进入生产路径。

已移除的 OpenCLI 浏览器采集路线只保留在 ADR-0011 的历史记录中，不再作为新接入候选。

### 2.1 RSS-Bridge Container Bridge（社媒采集）

[RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge)（PHP Docker 镜像）将 Twitter/X、Reddit、YouTube 等社媒平台的内容转换为 RSS feed，由 News Sentry 的 RSSCollector 统一消费。

- **部署方式：** 生产迁移期使用 Cloudflare Containers；本地开发仍可用 Docker Compose sidecar（`docker-compose.yml`）
- **采集路径：** RSS-Bridge → RSS feed URL → News Sentry `RSSCollector` → NewsEvent
- **零 Token 消耗：** 社媒采集完全通过 RSS 管道，不消耗 AI provider token
- **会话隔离：** 需要登录的平台通过 RSS-Bridge 的 bridge 配置管理，不进 News Sentry 配置
- **VPS 边界：** RSS-Bridge 不得再作为 VPS/Tunnel 运行依赖；若某个社媒桥无法在 Cloudflare Containers 稳定运行，应降级为外部 SaaS/公开 RSS 源或 Worker-native 采集器候选，而不是恢复 VPS

### 2.2 原生 Reddit Collector

`src/news_sentry/collect/reddit.py` — 通过 Reddit RSS feed（`*.json` 端点）采集 subreddit 热帖和关键词搜索结果。

- **类型标记：** `SourceChannel.type = "reddit"`
- **格式：** RSS + JSON 双模，优先解析 JSON
- **速率限制：** `fetch_interval_seconds`（默认 5s）控制请求间隔
- **无外部依赖：** 不需要 Reddit API key，不需要第三方库

### 2.3 原生 Hacker News Collector

`src/news_sentry/collect/hn.py` — 通过 HN Firebase REST API 采集 Top/New/Best 故事。

- **类型标记：** `SourceChannel.type = "hackernews"`
- **API：** `https://hacker-news.firebaseio.com/v0/`（公开，无需 API key）
- **速率限制：** `fetch_interval_seconds`（默认 5s）控制请求间隔
- **批量优化：** 支持 `max_items_per_run` 限制单次采集数量

### 2.4 未来 Twitter/X 采集路径

Twitter/X 采集的预留选项（v2 未实现，`SourcePlatform` 类型已预留）：
- **RSS-Bridge Twitter bridge**（需要 RSS-Bridge 配置 Twitter API token）
- **Nitter RSS**（通过 Nitter 实例的 RSS 输出，无需 API key）
- 具体实现路径需要重新写小型设计稿和验证清单；不要引用旧 Phase 作为授权。

---

## §3. AI Provider Chain（内置 AI 链路）

News Sentry v2 使用内置 AI provider chain，无需外部 Agent 框架：

| Provider | SDK | 用途 | 优先级 |
|---|---|---|---|
| Gemini | `google-genai` | 翻译、研判 | 1 (primary) |
| DeepSeek | OpenAI-compatible SDK | 翻译 fallback | 2 |
| Groq | `groq` | 研判 fallback | 3 |
| Cloudflare Workers AI | REST API | Cloudflare-native 兜底 | 4 |
| OpenRouter | OpenAI-compatible SDK | 免费模型兜底 | 5 |
| NVIDIA NIM / Agnes AI / OpenCode Zen / Reka | OpenAI-compatible SDK | FreeLLMAPI 密钥迁移后的直连备用，不再经过本地 sidecar | 6 |

- **零外部框架依赖：** 不依赖 LangChain、OpenCLI、Hermes、OpenClaw 等 Agent 框架
- **Provider 路由：** `config/provider/routes.yaml` 控制每个 target 的 provider 链路；同一 provider 的备用 key 使用环境变量后缀 `_2`、`_3` 进入 key pool
- **CLI 入口不变：** `python -m news_sentry.cli run --target {id} --stage all`
- **严格零成本策略：** 免费容量、试用额度、包月额度和付费兜底必须按 `cost_tier` 分层治理；默认 strict-zero profile 只使用官方免费或 ledger 已确认的免费/试用资源，详见 [AI Provider 免费容量与预算兜底策略](./specs/2026-07-03-ai-provider-free-capacity-and-paid-fallback.md)
- **付费兜底策略：** 当所有免费资源冻结且 backlog 达到触发条件时，才允许进入 budgeted fallback；Coding Plan 只能服务代码维护类任务，不能默认用于公共翻译、摘要或 enrichment

### 3.1 免费容量候选池

后续 strict-zero 路由应优先扩展以下官方或相对可信的免费/试用资源：

- 默认免费/试用主力：Gemini API、Groq、Cloudflare Workers AI、Cerebras、GitHub Models、SiliconFlow、OpenRouter free models、Mistral、SambaNova、Fireworks、Nscale。
- 中国官方/准官方候选：Alibaba Model Studio / Bailian、ModelScope API-Inference、Tencent Hunyuan、Volcengine Ark、Z.ai / 智谱、Baidu AI Studio / Qianfan、DeepSeek、Moonshot / Kimi、MiniMax。
- 可信第三方中转/网关候选：Cloudflare AI Gateway、Vercel AI Gateway、Hugging Face Inference Providers、Requesty、Novita、AIMLAPI、Portkey、302.AI、API易、AiHubMix、DMXAPI。

所有候选必须先通过文档复核、账单页确认和 smoke test，才能从 `paid_disabled` 提升到 `free`、`trial_credit` 或 `subscription_included`。

---

## §4. Intel_Briefing 模式借鉴

[Intel_Briefing](https://github.com/77AutumN/Intel_Briefing)（124 stars）是一个从 12+ 数据源自动抓取、翻译、分析的情报聚合引擎，用 Gemini 生成中文日报。与 News Sentry 目标重叠度高，但实现路径不同（无 Agent Skill Pack 架构、无沙箱）。

| 借鉴点 | Intel_Briefing 原型 | News Sentry 对应设计 |
|---|---|---|
| Tier 1 / Tier 2 采集分层 | Tier 1（聚合器）走 `fetch_news.py`，Tier 2（独立传感器）走 `sensors/` | 可借鉴为 `SourceChannel.tier`，但落地前必须写 schema 与迁移测试 |
| 防幻觉机制 | Grok fallback 产品标记 `⚠️ 链接未验证 (AI 推断)` | `metadata.translation.status="unverified"` 或 `acquisition.source_type="ai_inferred"` |
| graceful degradation | 缺 API key 时跳过对应源，不崩溃 | SandboxPolicy `hard_stop.missing_api_key=false`；source health 记录 `status=degraded` |
| 数据源清单参考 | HN、GitHub Trending、ArXiv、HF Papers、Product Hunt、TechCrunch、MIT TR | 优先 RSS/API 直连；没有公开接口时先记录候选，不默认引入浏览器驱动 |
| 优雅退出而非异常抛出 | 每个传感器独立 try/except，失败写 `status=skipped` | 与 `ToolRunResult.error.type` 规范对齐（ADR-0003） |

**GitHub Actions 自动化参考：** Intel_Briefing 的 `.github/workflows/daily-report.yml` 是 Hermes cron 触发模式的可参考参照物。

---

## §5. TrendRadar 模式借鉴

[TrendRadar](https://github.com/sansan0/TrendRadar) 是一个 AI 舆情监控助手（Python + MCP server），支持关键词筛选、多渠道推送（飞书/钉钉/微信/Telegram/Email）、MCP 客户端对接。

| 借鉴点 | TrendRadar 原型 | News Sentry 对应设计 |
|---|---|---|
| 关键词×频率矩阵 | 关键词精准筛选 + 推送阈值配置 | `FilterRules.keyword_matrix`：关键词列表 + 权重 + 频率窗口，驱动 `news_value_score` |
| 多渠道推送 fanout | 飞书/钉钉/企业微信/Telegram/Email/ntfy/Bark/Slack/Webhook | 保持为后续候选；新增 channel 前必须有 `output_result.destinations[]` 契约和测试 |
| MCP server 暴露形态 | `mcp_server/` 作为 MCP 工具集供 Claude 等客户端调用 | 仅作为后续候选；不能替代核心 CLI/API 契约 |
| newsnow API 数据源 | 从 newsnow 项目获取多平台热榜数据 | 作为 RSS/API 候选源；通过 `SourceChannel.type=api` 接入前先做合规与限流检查 |

---

## §6. 明确舍弃清单

下表记录经过反思后明确不引入当前主线的外部项目能力，避免后续 PR 试图重做。

| 能力 | 来源 | 舍弃理由 |
|---|---|---|
| opencli-admin React/FastAPI 栈 | opencli-admin | 不引入第二套后台产品；当前 admin 前端已独立维护 |
| opencli-admin Docker 多节点 | opencli-admin | 暂不引入分布式采集控制面；先保持现有 Cloudflare/容器边界 |
| MiroShark 群体智能模拟引擎 | MiroShark | 目标不同：模拟舆论反应 vs 监控真实新闻 |
| BettaFish MindSpider 爬虫栈 | BettaFish | 不恢复浏览器爬虫栈；社媒采集优先 RSS/API/Bridge |
| worldmonitor 地图引擎（globe.gl/deck.gl） | worldmonitor | 超出当前轻量信息工作台目标 |
| worldmonitor Country Intelligence Index | worldmonitor | 先使用 `china_relevance` + L0/L1 classification，避免新增并行指数 |
| BettaFish ForumEngine 多 Agent 论辩 | BettaFish | 当前单 judge Skill 和人工复核已够，暂不引入多 Agent 论辩面 |
| Tauri 桌面应用 | worldmonitor | ADR-0026 另行评估；当前桌面路径先打磨 pywebview |

---

## §7. 版本约束记录

| 外部项目 | 最低版本 | 安装命令 | 用途 | 升级审查要求 |
|---|---|---|---|---|
| RSS-Bridge | `latest` Docker image | Cloudflare Containers 或本地 `docker pull rssbridge/rss-bridge` | 社媒 RSS 桥接 | 生产走 Cloudflare Containers，本地开发可用 Docker Compose，不锁定版本 |
| Python | 3.11+ | 系统包管理器或 pyenv | 运行时 | 语言特性兼容性测试 |
| Docker | 24.0+ | 系统包管理器 | 容器化部署 | CI 测试 |
| Node.js | 18+ (仅前端构建) | 系统包管理器或 nvm | 前端 TypeScript + Vite 构建 | 前端 build 通过即可 |

**已移除的依赖（v2 重构早期）：**
- ~~OpenCLI >=1.7.14~~ → 由原生 Reddit/HN Collector + RSS-Bridge 替代
- ~~Chrome/Chromium（OpenCLI browser 命令）~~ → 不再需要浏览器驱动采集
