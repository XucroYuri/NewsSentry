# Agent Skill 生态调研：与意大利信息源相关的现有能力

> 版本: v1.0 | 日期: 2026-05-09
> 状态: 调研报告，供 Skill Registry 建设与 Adaptation Layer 工作参考
> 前置文档: [架构总览](../architecture-overview.md) | [Integration Protocol](../integration-protocol.md) | [开源参考研究](./开源舆情监控参考项目深度研究.md) | [信息获取链条](./information-acquisition-chains.md) | [KOL追踪与信源管理](./kol-tracking-and-source-management.md)

---

## 1. 调研概述

本文档对 ClawHub.ai 及其他可信 Agent Skill 分享站点进行了系统性调研，寻找与本项目（News Sentry — 意大利突发新闻24小时监控系统）开发目标相近、与意大利信息源相关的现有 Agent Skill。

### 1.1 调研范围

| 站点/来源 | 类型 | 地址 | 调研状态 |
|-----------|------|------|---------|
| **ClawHub.ai** | OpenClaw官方Skill注册表 | https://clawhub.ai | 已完成 |
| **VoltAgent/awesome-openclaw-skills** | 精选Skill合集(5400+筛选分类) | github.com/VoltAgent/awesome-openclaw-skills | 已完成 |
| **VoltAgent/awesome-agent-skills** | 跨平台Agent Skill合集(1000+) | github.com/VoltAgent/awesome-agent-skills | 已完成 |
| **Termo.ai** | AI Skill分享平台 | termo.ai | 已检索（公开Skill较少） |
| **explainx.ai** | Skill/MCP资源索引 | explainx.ai | 已检索（索引为主，无直接Skill） |
| **jamditis/claude-skills-journalism** | 新闻记者专用Skill集 | 本地 ~/Downloads/Agent-Skill | 已在架构总览中注册 |
| **affaan-m/everything-claude-code** | 通用Claude Code Skill集 | 本地 ~/Downloads/Agent-Skill | 已在架构总览中注册 |

### 1.2 核心发现

**目前没有任何现成的"意大利新闻监控"Skill。** 但存在多个可改造的基线Skill，以及一个值得特别关注的对标项目 `japan-news-mcp`——它是目前整个生态中唯一针对特定国家（日本）的新闻监控Skill，其架构模式可直接作为意大利版的模板。

---

## 2. 按 Pipeline 环节分类的相关 Skill

### 2.1 采集层 (Collect)

#### A. RSS/Feed 聚合类

| Skill | 作者/来源 | 地理焦点 | 与本项目适配价值 | 链接 |
|-------|----------|---------|----------------|------|
| **`rss-reader`** | dimitripantzos | 通用 — 任意RSS/Atom | **高** — 直接用于监控意大利媒体RSS Feed | https://clawhub.ai/dimitripantzos/rss-reader |
| **`feed-to-md`** | odysseus0 | 通用 — 任意feed URL | **高** — RSS转Markdown格式，天然适配Obsidian输出 | awesome-openclaw-skills |
| **`rss-skill`** | odysseus0 | 通用 | **高** — RSS获取基础能力 | awesome-openclaw-skills |
| **`feed-digest`** | odysseus0 | 通用 | **高** — 生成结构化Feed摘要，可改造为意大利新闻摘要 | awesome-openclaw-skills |
| **`rss-digest`** | odysseus0 | 通用 | **高** — RSS摘要生成，与feed-digest互补 | awesome-openclaw-skills |
| **`ak-rss-24h-brief`** | seandong | 通用 — OPML列表 | **高** — 24小时简报模式，与本项目heartbeat机制高度吻合 | awesome-openclaw-skills |
| **`news-summary`** | joargp | 国际 — BBC/RSS feeds | **中** — 可参考其RSS聚合架构，需替换为意大利媒体源 | https://clawhub.ai/joargp/news-summary |
| **`news-aggregator-skill`** | cclank | HN/GitHub/Product Hunt等8源 | **低** — 主要面向科技圈，非意大利新闻 | https://clawhub.ai/cclank/news-aggregator-skill |
| **`news-daily`** | hegangsz | 国内+飞书 | **高** — RSS→飞书推送完整链路，改造为意大利源即可 | https://clawhub.ai/hegangsz/news-daily |

**适配分析**：以上Skill均为通用RSS聚合能力，改造方向统一为——配置意大利媒体RSS源列表（ANSA, Corriere, Repubblica, FAO, WFP, 外交部等），替换默认Feed URL即可。其中 `ak-rss-24h-brief` 和 `news-daily` 的"定时聚合+推送"模式与本项目heartbeat最契合。

#### B. 新闻监控/简报类

| Skill | 作者/来源 | 地理焦点 | 与本项目适配价值 | 链接 |
|-------|----------|---------|----------------|------|
| **`japan-news-mcp`** | awesome-openclaw-skills收录 | **日本** — Yahoo News Japan, NHK, Reuters Japan | **极高** — 目前唯一国家特化新闻Skill，架构模式可作为意大利版模板 | awesome-openclaw-skills |
| **`ai-news-briefing`** | sharkwind | AI领域 | **中** — 10源监控+结构化简报生成模式可参考 | https://clawhub.ai/sharkwind/ai-news-briefing |
| **`ai-news-simple`** | sharkwind | AI领域 | **中** — bash命令行式简报，轻量可参考 | https://clawhub.ai/sharkwind/ai-news-simple |
| **`tech-news-digest`** | dinstein | 科技新闻 | **中** — 多源数据收集+质量评分+多格式输出，架构可参考 | https://clawhub.ai/dinstein/tech-news-digest |
| **`opera-news-plugin`** | ClawHub | Opera News API | **中** — 通过API获取新闻，可作为World News API的替代/补充 | https://clawhub.ai/plugins/opera-news-plugin |

**`japan-news-mcp` 详解** — 最关键的对标Skill：

- 数据源：Yahoo News Japan, NHK, Reuters Japan — 专门面向日本市场的财经和商业情报
- 功能：RSS聚合 + 结构化摘要 + 特定领域关键词过滤
- 与本项目的关系：
  - 架构完全可复制：替换日本源为意大利源（ANSA→NHK, Corriere→Yahoo News Japan）
  - 关键词过滤机制可借鉴：日本版按财经关键词过滤，意大利版按涉华关键词过滤
  - MCP Server暴露方式可参考
- 改造量：**中** — 需替换所有数据源、关键词集、输出格式

#### C. 网页爬取/社媒采集类

| Skill | 作者/来源 | 覆盖平台 | 与本项目适配价值 | 链接 |
|-------|----------|---------|----------------|------|
| **`opencli-adapter-author`** | OpenCLI内置 | 任意网站 | **核心** — 为ANSA/Corriere/FAO等意大利网站生成CLI适配器 | OpenCLI SDK |
| **`opencli-autofix`** | OpenCLI内置 | 任意网站 | **核心** — 网站改版后自动修复适配器 | OpenCLI SDK |
| **`opencli-usage`** | OpenCLI内置 | OpenCLI站点注册表 | **参考** — 查询已有CLI适配器能力 | OpenCLI SDK |
| **`smart-search`** | OpenCLI内置 | OpenCLI站点注册表 | **发现** — 跨现有能力搜索 | OpenCLI SDK |
| **`web-scraping`** | jamditis/claude-skills-journalism | 通用 | **高** — 新闻记者级爬取能力，级联策略可参考 | 本地 ~/Downloads/Agent-Skill |
| **`page-monitoring`** | jamditis/claude-skills-journalism | 通用 | **高** — 页面变更监控，可用于监测意大利政府/组织官网更新 | 本地 ~/Downloads/Agent-Skill |
| **`social-media-intelligence`** | jamditis/claude-skills-journalism | 跨平台 | **高** — 社媒情报采集，涉华关键词追踪 | 本地 ~/Downloads/Agent-Skill |
| **`data-scraper-agent`** | affaan-m/everything-claude-code | 通用 | **中** — 数据抓取通用Skill | 本地 ~/Downloads/Agent-Skill |
| **`last30days`** | mvanhorn | 跨平台(Reddit/X/YouTube/HN/TikTok/Polymarket) | **中** — 30天舆情追踪，可用于涉华话题回顾 | https://clawhub.ai/mvanhorn/last30days-official |
| **`aminer-open-academic`** | 本地 | 学术论文 | **中** — 用于追踪意中关系学术论文 | 本地 ~/Downloads/Agent-Skill |
| **`digital-archive`** | jamditis/claude-skills-journalism | 通用 | **中** — 数字归档+事实核查，可用于L3追踪溯源 | 本地 ~/Downloads/Agent-Skill |

#### D. 社媒定向采集类

| Skill | 覆盖平台 | 预置适配器 | 与本项目适配价值 |
|-------|---------|-----------|----------------|
| **OpenCLI预置适配器** | Twitter/X, Reddit, Facebook, YouTube, Instagram, Google News | 90+ | **高** — Twitter意语区search、Reddit r/italy、Google News意大利区均直接可用 |
| **TrendRadar热榜爬取** | 微博、抖音、B站、知乎、小红书等35+ | 中国平台 | **中** — 可直接用于中文侧涉意舆情追踪 |

**OpenCLI预置适配器中与意大利监控直接相关的命令**：

| 命令 | 用途 | 直接可用性 |
|------|------|-----------|
| `opencli twitter search --lang it --query "Cina OR China"` | 意语区涉华推文搜索 | 直接可用 |
| `opencli twitter timeline --user GiorgiaMeloni` | 特定KOL timeline | 直接可用 |
| `opencli twitter trending --region it` | 意大利区趋势 | 直接可用 |
| `opencli reddit subreddit --name italy` | r/italy帖子 | 直接可用 |
| `opencli reddit search --query "Cina" --subreddit italy` | r/italy涉华搜索 | 直接可用 |
| `opencli google news --region it` | 意大利区Google News | 直接可用 |
| `opencli youtube search --query "Cina Italia" --lang it` | 意语YouTube涉华视频 | 直接可用 |

---

### 2.2 研判层 (Judge)

| Skill | 作者/来源 | 覆盖范围 | 与本项目适配价值 | 链接 |
|-------|----------|---------|----------------|------|
| **`social-sentiment`** | atyachin | Twitter/Reddit/Instagram/TikTok | **高** — 舆情情感分析，需适配意大利语+涉华维度 | https://clawhub.ai/atyachin/social-sentiment |
| **`aigc-news-sentiment`** | gbabyzs | 财经新闻 | **中** — 金融新闻情感分类框架可参考，需扩展为政治/外交 | https://clawhub.ai/gbabyzs/aigc-news-sentiment |
| **`multilingual-semantic-bridge`** | chrix | 多语言 | **高** — 多语言语义桥接，对意大利语↔中文跨语言分析有直接价值 | https://clawhub.ai/plugins/@chrix/openclaw-multilingual-semantic-bridge-plugin |
| **`google-trends`** | awesome-openclaw-skills | 全球 | **中** — 可用于意大利区趋势关键词发现 | awesome-openclaw-skills |
| **`news-cog`** | nitishgargiitd | CellCog SDK | **低** — 委托式新闻分析，架构差异较大 | https://clawhub.ai/nitishgargiitd/news-cog |
| **`autoglm-websearch`** | 改造为 `news-source-searcher` | 通用搜索 | **中** — 通用搜索→定向新闻源搜索 | 本地 ~/Downloads/Agent-Skill |
| **`autoglm-browser-agent`** | 改造为 `news-page-extractor` | 通用浏览 | **中** — 通用浏览→新闻页面结构化提取 | 本地 ~/Downloads/Agent-Skill |
| **`autoglm-deepresearch`** | 改造为 `news-trace-investigator` | 学术研究 | **中** — 学术研究→新闻线索追踪 | 本地 ~/Downloads/Agent-Skill |
| **`market-research`** | 改造为 `opinion-trend-analyzer` | 商业市场 | **中** — 商业市场→舆情趋势 | 本地 ~/Downloads/Agent-Skill |

**`social-sentiment` 详解** — 最具改造价值的研判Skill：

- 覆盖平台：Twitter, Reddit, Instagram, TikTok
- 功能：品牌/产品舆情情感分析、品牌声誉追踪、PR危机检测
- 与本项目的关系：
  - 情感分析框架可直接复用
  - 需增加：意大利语情感词典、涉华相关性维度、政治语境理解
  - 需替换：品牌/产品维度→涉华议题维度
  - 需增加：突发事件升级判断逻辑
- 改造量：**中** — 核心分析框架保留，增加意大利特化维度

**`multilingual-semantic-bridge` 详解** — 跨语言分析的关键Skill：

- 功能：多语言语义对齐与桥接，Plugin+Skill双形态
- 与本项目的关系：
  - 意大利语新闻→中文摘要的语义对齐
  - 涉华关键词在意大利语/中文/英语三种语言间的语义映射
  - 研判环节的跨语言证据交叉验证
- 改造量：**低** — 主要是配置意大利语↔中文的桥接参数

---

### 2.3 输出层 (Output)

| Skill | 作者/来源 | 输出目标 | 与本项目适配价值 | 链接 |
|-------|----------|---------|----------------|------|
| **`obsidian-direct`** | ruslanlanket | Obsidian Vault | **核心** — 直接读写Obsidian vault，模糊搜索+自动文件夹检测 | https://clawhub.ai/ruslanlanket/obsidian-direct |
| **`feishu-send-file`** / **`feishu-chat`** | 本地 ~/Downloads/Agent-Skill | 飞书 | **核心** — 飞书推送，直接使用 | 本地 ~/Downloads/Agent-Skill |
| **`llm-wiki`** | alirezarezvani | 知识库 | **中** — LLM驱动知识库输出 | alirezarezvani/claude-skills |
| **`tech-news-digest`** | dinstein | 多格式 | **中** — 多源数据收集+质量评分+多格式输出，架构可参考 | https://clawhub.ai/dinstein/tech-news-digest |

**`obsidian-direct` 详解** — Obsidian输出的核心Skill：

- 功能：
  - 读写Obsidian vault中的笔记
  - 模糊/语音搜索全部笔记
  - 自动检测文件夹放置新笔记
  - 创建结构化笔记+反向链接
- 与本项目的关系：
  - 直接满足output环节的Obsidian写入需求
  - 反向链接机制可用于关联同一事件的多篇报道
  - 自动文件夹检测可配合按日期/来源/主题的目录结构
- 改造量：**极低** — 直接使用，仅需配置vault路径

---

### 2.4 适配改造层 (Adaptation)

| Skill | 用途 | 与本项目适配价值 |
|-------|------|-----------------|
| **`find-skills`** | 内置Skill发现 | 发现新Skill的入口 |
| **`translator-pro-test`** | 翻译质量评估 | 意大利语↔中文翻译质量控制 |
| **`opencli-autofix`** | 适配器自动修复 | 网站改版后自动修复意大利新闻网站适配器 |

---

## 3. 安全警告：ClawHub 恶意 Skill 问题

调研过程中发现的重要安全信息，**必须在Skill安装和使用流程中考虑**：

### 3.1 已披露的安全事件

| 事件 | 时间 | 详情 | 来源 |
|------|------|------|------|
| **ClawHavoc恶意Skill活动** | 2026-02 | 341个恶意Skill（约12%），散播Atomic Stealer窃取macOS/Windows凭证 | Koi Security / The Hacker News |
| **凭证泄露统计** | 2026-03 | 7.1%的Skill设计用于泄露API密钥和PII | Snyk Research |
| **虚假Google Skill** | 2026-03 | 伪装为Google Skill的恶意软件，诱导安装木马 | Snyk |
| **加密货币挖矿Skill** | 2026-04 | 30个ClawHub Skill秘密将AI Agent变为加密货币挖矿集群 | The Register / Manifold |
| **#1下载量Skill安全漏洞** | 2026-04 | "What Would Elon Do"含9个安全漏洞（2个Critical），静默窃取数据 | Cisco / Reddit |

### 3.2 安全缓解措施

OpenClaw已于2026年2月与VirusTotal合作，所有新提交Skill自动扫描。但仍需注意：

```yaml
SecurityProtocol:
  # Skill安装前安全检查
  pre_install:
    - "检查VirusTotal扫描报告是否存在"
    - "阅读SKILL.md中的权限声明"
    - "检查是否有external_call白名单之外的外部请求"
    - "确认无敏感文件访问（.env, credentials, SSH keys）"

  # Skill运行时安全
  runtime:
    - "在沙箱环境中首次运行新Skill"
    - "非管理员账号运行"
    - "零信任网络控制"
    - "监控Skill的网络请求和文件访问"

  # Skill来源优先级
  source_priority:
    1: "官方Skill（OpenClaw/OpenCLI内置）"
    2: "有VirusTotal扫描报告的ClawHub Skill"
    3: "GitHub知名仓库中的Skill"
    4: "社区推荐但未扫描的Skill（需沙箱测试后使用）"
```

---

## 4. 综合评估与适配路径

### 4.1 Skill适配难度分级

| 难度 | Skill | 改造方向 | 预估工时 |
|------|-------|---------|---------|
| **极低** (直接用) | `obsidian-direct`, `feishu-send-file`, `feishu-chat` | 配置路径/频道即可 | 0.5天 |
| **低** (配置改造) | `rss-reader`, `feed-to-md`, `feed-digest`, `rss-digest`, `ak-rss-24h-brief`, `opencli-twitter/reddit/google预置命令` | 替换RSS源列表/搜索参数 | 1-2天 |
| **中** (架构改造) | `japan-news-mcp`, `social-sentiment`, `last30days`, `multilingual-semantic-bridge`, `news-daily`, `news-summary`, `page-monitoring` | 替换地域源+增加涉华维度+意大利语适配 | 3-5天/个 |
| **高** (深度改造) | `autoglm-*`系列, `market-research` | 通用→特化方向改造 | 5-10天/个 |
| **极高** (自主开发) | 意大利新闻CLI适配器, `news-value-judge`, `entity-tracker-italy-cn`, `sentiment-analyzer-zh` | 无现有Skill可改造，需从零开发 | 10-20天/个 |

### 4.2 推荐的Skill注册策略

按照 architecture-overview.md 中 Skill Registry 三类来源的框架，将调研结果分类注册：

#### 直接使用（Direct）

| Skill | 环节 | 来源 | 已在架构中注册 |
|-------|------|------|--------------|
| `obsidian-direct` | output | ClawHub | **新增** |
| `rss-reader` | collect | ClawHub | **新增** |
| `feed-to-md` | collect | awesome-openclaw-skills | **新增** |
| `feed-digest` / `rss-digest` | collect+output | awesome-openclaw-skills | **新增** |
| `ak-rss-24h-brief` | collect+output | awesome-openclaw-skills | **新增** |
| `social-sentiment` | judge | ClawHub | **新增** |
| `multilingual-semantic-bridge` | judge | ClawHub | **新增** |
| `last30days` | collect+judge | ClawHub | **新增** |
| `google-trends` | judge | awesome-openclaw-skills | **新增** |
| `data-scraper-agent` | collect | affaan-m | 已注册 |
| `web-scraping` | collect | jamditis | 已注册 |
| `social-media-intelligence` | collect | jamditis | 已注册 |
| `page-monitoring` | collect | jamditis | 已注册 |
| `digital-archive` | output+judge | jamditis | 已注册 |
| `llm-wiki` | output | alirezarezvani | 已注册 |
| `aminer-open-academic` | collect | 本地 | 已注册 |
| `feishu-send-file` / `feishu-chat` | output | 本地 | 已注册 |
| `find-skills` | adaptation | 内置 | 已注册 |

#### 改造适配（Adapted）

| 源头Skill | 改造后 | 环节 | 改造点 | 已在架构中注册 |
|-----------|--------|------|--------|--------------|
| `japan-news-mcp` | `italy-news-mcp` | collect | 日本源→意大利源，财经关键词→涉华关键词 | **新增** |
| `news-daily` | `italy-news-daily` | collect+output | 国内源→意大利源，飞书模板调整 | **新增** |
| `autoglm-websearch` | `news-source-searcher` | collect | 通用搜索→定向新闻源搜索 | 已注册 |
| `autoglm-browser-agent` | `news-page-extractor` | collect | 通用浏览→新闻页面结构化提取 | 已注册 |
| `autoglm-deepresearch` | `news-trace-investigator` | collect+judge | 学术研究→新闻线索追踪 | 已注册 |
| `market-research` | `opinion-trend-analyzer` | judge | 商业市场→舆情趋势 | 已注册 |

#### 自主开发（Purpose-built）

| Skill | 环节 | 理由 | 已在架构中注册 |
|-------|------|------|--------------|
| `news-value-judge` | judge | 涉华舆情+目标地区语境的专用研判 | 已注册 |
| `sentiment-analyzer-zh` | judge | 中文舆情情感分析 | 已注册 |
| `entity-tracker-italy-cn` | judge | 意大利涉华实体关系追踪 | 已注册 |
| `opencli-italian-sites` | collect | ANSA/Corriere/Repubblica/FAO的CLI适配器 | **新增**（对应当前需要开发的适配器） |

---

## 5. `japan-news-mcp` → `italy-news-mcp` 改造蓝图

作为最接近本项目目标的现有Skill，详细规划其改造方案：

### 5.1 数据源替换映射

| japan-news-mcp 源 | italy-news-mcp 替换源 | 获取方式 | 优先级 |
|-------------------|----------------------|---------|-------|
| Yahoo News Japan | ANSA (ansa.it) | RSS + OpenCLI适配器 | P0 |
| NHK | RAI News | RSS | P1 |
| Reuters Japan | Adnkronos (意大利通讯社) | RSS | P2 |
| Toyo Keizai (东洋经济) | Il Sole 24 Ore | RSS | P1 |
| — 新增 — | Corriere della Sera | RSS + OpenCLI | P0 |
| — 新增 — | La Repubblica | RSS + OpenCLI | P0 |
| — 新增 — | FAO Newsroom | RSS + OpenCLI | P0 |
| — 新增 — | WFP News | RSS | P0 |
| — 新增 — | Presidenza del Consiglio | RSS | P0 |
| — 新增 — | Ministero degli Esteri | RSS | P0 |

### 5.2 关键词集替换

| japan-news-mcp 关键词 | italy-news-mcp 替换关键词 | 语言 |
|----------------------|-------------------------|------|
| 日经、株価、GDP | Cina, cinese, Pechino, Xi Jinping | it |
| 円、金融政策 | Belt and Road, Via della Seta, imprese cinesi | it |
| — 新增 — | China, Chinese, Beijing, Italy | en |
| — 新增涉华 — | 意大利, 罗马, 米兰, 中意关系, 梅洛尼, 粮农组织 | zh |
| — 新增突发 — | ULTIM'ORA, BREAKING, terremoto, alluvione, attentato | it |

### 5.3 增加维度（japan-news-mcp 不具备的）

1. **涉华相关性评分** — 每条新闻的china_relevance (0-1)
2. **来源可信度评分** — ANSA=0.95, Corriere=0.90, Twitter=0.60, Reddit=0.40
3. **突发事件升级** — breaking_news自动触发紧急模式
4. **双向舆情联动** — 意大利侧发现涉华新闻时，自动触发中文侧搜索
5. **多语言输出** — 意大利语原文 + 中文摘要 + 英文标签

---

## 6. 其他可信站点的补充发现

### 6.1 Termo.ai

| Skill | 功能 | 与本项目关系 |
|-------|------|-------------|
| **ClawFeed** | AI驱动新闻摘要，从Twitter和RSS自动生成结构化简报(4H/日/周/月) | **中** — 结构化简报模式可参考，但需意大利语适配 |

### 6.2 本地 ~/Downloads/Agent-Skill 目录

已在本项目架构总览中注册的本地Skill：

| Skill | 功能 | 环节 | 注册状态 |
|-------|------|------|---------|
| `data-scraper-agent` | 通用数据抓取 | collect | 已注册 |
| `web-scraping` | 新闻记者级爬取 | collect | 已注册 |
| `social-media-intelligence` | 社媒情报 | collect | 已注册 |
| `page-monitoring` | 页面变更监控 | collect | 已注册 |
| `digital-archive` | 数字归档+事实核查 | output+judge | 已注册 |
| `feishu-send-file` / `feishu-chat` | 飞书推送 | output | 已注册 |
| `aminer-open-academic` | 学术论文追踪 | collect | 已注册 |

### 6.3 通用参考Skill（非直接使用，架构可借鉴）

| Skill | 功能 | 可借鉴点 |
|-------|------|---------|
| **BettaFish/微舆 ForumEngine** | 多Agent辩论避免思维同质化 | 研判环节可用不同LLM模型/prompt视角交叉验证 |
| **BettaFish ReportEngine** | 6类专业报告模板 | 突发事件+政策动态报告模板直接参考 |
| **TrendRadar NotificationDispatcher** | 9渠道推送+消息分片 | 飞书/企微/Telegram推送代码直接复用 |
| **TrendRadar AIFilter** | 两阶段标签提取+分类 | 规则预筛→AI分类的两阶段过滤设计 |

---

## 7. 待行动项

基于本次调研，需要纳入项目推进计划的行动项：

| 优先级 | 行动项 | 关联Skill | 负责环节 |
|--------|-------|----------|---------|
| P0 | 安装并测试 `obsidian-direct`，配置vault路径 | obsidian-direct | output |
| P0 | 安装并测试 `rss-reader`，配置意大利媒体RSS列表 | rss-reader | collect |
| P0 | 注册OpenCLI，验证Twitter/Reddit/Google News预置命令对意大利语区的支持 | OpenCLI预置适配器 | collect |
| P1 | 深入研究 `japan-news-mcp` 源码，制定 `italy-news-mcp` 改造方案 | japan-news-mcp | collect |
| P1 | 安装并测试 `social-sentiment`，评估意大利语情感分析适配难度 | social-sentiment | judge |
| P1 | 安装并测试 `multilingual-semantic-bridge`，验证意↔中语义对齐效果 | multilingual-semantic-bridge | judge |
| P1 | 使用 `opencli-adapter-author` 为ANSA生成第一个意大利新闻网站CLI适配器 | opencli-adapter-author | collect |
| P2 | 测试 `feed-digest`/`rss-digest`，评估与TrendRadar RSS模块的互补性 | feed-digest, rss-digest | collect |
| P2 | 评估 `last30days` 是否可作为涉华话题回顾的补充工具 | last30days | judge |
| P2 | 为 `ak-rss-24h-brief` 配置意大利媒体OPML列表并测试 | ak-rss-24h-brief | collect+output |

---

## 附录A：搜索关键词与查询记录

本次调研使用的主要搜索词：

- `clawhub.ai Italy Italian news`
- `clawhub.ai RSS feed aggregator news skill`
- `clawhub.ai multilingual translation Italian news`
- `clawhub.ai sentiment analysis opinion monitoring social media`
- `clawhub.ai World News API breaking news FAO`
- `clawhub.ai Obsidian knowledge management vault skill`
- `awesome-openclaw-skills news journalism monitoring sentiment`
- `awesome-agent-skills news monitoring translation multilingual`
- `clawhub.ai Italy Europe news monitoring skill openclaw`
- `clawhub.ai international news API sentiment analysis`
- `clawhub.ai browser scraping web monitoring page monitoring`
- `VoltAgent awesome-openclaw-skills news monitoring journalism research`

## 附录B：数据更新

本文档中引用的Skill信息截至 2026-05-09。ClawHub生态变化极快，建议每2-4周重新检索新增Skill。
