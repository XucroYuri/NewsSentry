# News Sentry — 架构总览

> 新闻媒体驻外机构24小时目标地区新闻监控Agent Skill

## 核心理念

**整合而非自建** — 优先整合社区Skill和外部CLI工具，只在领域特化需求无法被现有能力覆盖时才自主开发。

## 架构：开放插件架构 + 适配改造层

```
news-sentry (核心编排器)
│
├── heartbeat engine         — 心跳触发，周期可配（1h/6h/24h）
├── pipeline builder         — 组装 collect → filter → judge → output 工作流
├── skill registry           — 能力注册表（direct / adapted / purpose-built）
├── adaptation layer         — evaluate → adapt → develop → register
├── integration protocol     — NewsEvent / PipelineContext / SkillManifest
└── fallback engine          — 每环节内置最小实现，空registry时系统仍可运行
```

## Skill Registry 三类来源

### 直接使用（Direct）

| Skill | 环节 | 来源 | 备注 |
|-------|------|------|------|
| `data-scraper-agent` | collect | affaan-m/everything-claude-code | 通用数据抓取 |
| `web-scraping` | collect | jamditis/claude-skills-journalism | 新闻记者级爬取 |
| `social-media-intelligence` | collect | jamditis/claude-skills-journalism | 社媒情报采集 |
| `page-monitoring` | collect | jamditis/claude-skills-journalism | 页面变更监控 |
| `digital-archive` | output+judge | jamditis/claude-skills-journalism | 数字归档+事实核查 |
| `llm-wiki` | output | alirezarezvani/claude-skills | LLM驱动知识库 |
| `aminer-open-academic` | collect | 本地 ~/Downloads/Agent-Skill | 学术论文追踪 |
| `feishu-send-file` / `feishu-chat` | output | 本地 ~/Downloads/Agent-Skill | 飞书推送 |
| `find-skills` | adaptation | 内置 | Skill发现入口 |
| **`obsidian-direct`** | output | ClawHub (ruslanlanket) | Obsidian vault读写+模糊搜索+反向链接 |
| **`rss-reader`** | collect | ClawHub (dimitripantzos) | 通用RSS/Atom监控，配意大利媒体Feed即可 |
| **`feed-to-md`** | collect+output | awesome-openclaw-skills (odysseus0) | Feed转Markdown，天然适配Obsidian |
| **`feed-digest`** / **`rss-digest`** | collect+output | awesome-openclaw-skills (odysseus0) | RSS结构化摘要生成 |
| **`ak-rss-24h-brief`** | collect+output | awesome-openclaw-skills (seandong) | OPML列表+24h简报，与heartbeat机制吻合 |
| **`social-sentiment`** | judge | ClawHub (atyachin) | Twitter/Reddit/Instagram/TikTok情感分析 |
| **`multilingual-semantic-bridge`** | judge | ClawHub (chrix) | 意↔中↔英跨语言语义桥接 |
| **`last30days`** | collect+judge | ClawHub (mvanhorn) | 30天跨平台(Reddit/X/YouTube/HN)舆情回顾 |
| **`google-trends`** | judge | awesome-openclaw-skills | 意大利区趋势关键词发现 |
| **`news-daily`** | collect+output | ClawHub (hegangsz) | RSS→飞书推送完整链路，改造为意源即可 |
| **`news-summary`** | collect | ClawHub (joargp) | 国际RSS聚合+摘要，参考架构 |

### 改造适配（Adapted）

| 源头Skill | 改造后 | 环节 | 改造点 | 来源 |
|-----------|--------|------|--------|------|
| `japan-news-mcp` | `italy-news-mcp` | collect | 日本源→意大利源，财经关键词→涉华关键词，增加涉华相关性评分+来源可信度+突发事件升级+双向舆情联动 | awesome-openclaw-skills |
| `news-daily` | `italy-news-daily` | collect+output | 国内RSS源→意大利媒体RSS源，飞书推送模板适配意大利语内容 | ClawHub (hegangsz) |
| `social-sentiment` | `china-relevance-sentiment` | judge | 品牌/产品情感→涉华议题情感，增加意大利语情感词典+政治语境理解+突发事件升级判断 | ClawHub (atyachin) |
| `last30days` | `china-italy-30days` | collect+judge | 通用30天回顾→涉华议题30天舆情回顾，增加意大利语区搜索参数+涉华关键词集 | ClawHub (mvanhorn) |
| `aigc-news-sentiment` | `political-news-sentiment` | judge | 金融新闻情感→政治/外交新闻情感，扩展分类维度为涉华相关类别 | ClawHub (gbabyzs) |
| `autoglm-websearch` | `news-source-searcher` | collect | 通用搜索→定向新闻源搜索 | 本地 ~/Downloads/Agent-Skill |
| `autoglm-browser-agent` | `news-page-extractor` | collect | 通用浏览→新闻页面结构化提取 | 本地 ~/Downloads/Agent-Skill |
| `autoglm-deepresearch` | `news-trace-investigator` | collect+judge | 学术研究→新闻线索追踪 | 本地 ~/Downloads/Agent-Skill |
| `market-research` | `opinion-trend-analyzer` | judge | 商业市场→舆情趋势 | 本地 ~/Downloads/Agent-Skill |

> **改造蓝图参考**：`japan-news-mcp` → `italy-news-mcp` 的详细数据源替换映射和关键词集设计见 [Agent Skill生态调研](./brainstorming/agent-skill-ecosystem-survey.md) 第5节。

### 自主开发（Purpose-built）

| Skill | 环节 | 理由 |
|-------|------|------|
| `news-value-judge` | judge | 涉华舆情+目标地区语境的专用研判，规则引擎+LLM混合；现有`social-sentiment`仅做品牌情感，无法满足涉华政治语境理解 |
| `sentiment-analyzer-zh` | judge | 中文舆情情感分析，通用NLP/`social-sentiment`均不支持中文口语化舆情（微博/微信语气词、反讽等） |
| `entity-tracker-italy-cn` | judge | 意大利涉华实体关系追踪（政要/中企/涉华组织），需维护实体知识图谱+立场变化检测，无现有Skill覆盖 |
| `opencli-italian-sites` | collect | ANSA/Corriere della Sera/La Repubblica/FAO/Presidenza del Consiglio的CLI适配器；调研确认ClawHub无任何意大利新闻网站现成适配器，需用`opencli-adapter-author`逐个生成 |
| `wechat-collector` | collect | 微信公众号/群聊监控适配器；微信封闭生态无法用OpenCLI直接访问，需专用桥接方案（网页版+截图OCR/第三方聚合API） |

## Adaptation Layer 工作流

```
发现能力缺口
  → find-skill 搜索社区skill
  → evaluate: 契合度评估
    → 高契合: 直接注册（direct）
    → 中契合: adapt 改造后注册（adapted），标注源头+改造点
    → 低契合/无结果: develop 自主开发（purpose-built）
```

## Pipeline 四环节

1. **collect** — 多源采集：RSS/API/网页爬取/社媒OSINT/国际组织发布
2. **filter** — 规则预过滤：关键词/实体/阈值/去重
3. **judge** — LLM深度研判：新闻价值评分/分类/摘要/情感/实体
4. **output** — 多层输出：本地文件归档 + Obsidian知识库 + 飞书推送

## 示例目标：意大利

- 本地媒体：ANSA, Corriere della Sera, La Repubblica
- 国际组织：FAO, WFP, ICJ, EU institutions (in Italy)
- 涉华维度：中意关系、在意中企、涉华舆情、华人社区

## 开发阶段顺序

当前开发路线按“契约先行、内核收束、工具渐进接入”推进：

1. **Contract Stabilization** — 定稿 `NewsEvent`、`PipelineContext`、`TargetConfig`、`SourceChannel`、文件事件协议、分数量纲和 provenance 规则。
2. **Kernel MVP** — 实现框架无关 bounded run、配置加载、RSS/API baseline、规则过滤、文件事件写入、run log、memory、source health 和最小 sandbox enforcer。
3. **Tool/Skill Registry + OpenCLI** — 建立 `SkillManifest` / `ToolManifest` registry，OpenCLI 通过 `tool_ref + binding_id + validated_args` 接入，不允许 `SourceChannel` 直接持有任意 shell 命令。
4. **AI Provider Routing** — 以任务路由方式接入翻译、研判、草稿生成和 fallback，不让 Skill 直接绑定具体模型供应商。
5. **Sandbox Hardening + Social/KOL Experiment** — 强化 command/network/browser/profile 权限模型，小规模接入公开、授权、可审计的社媒/KOL 实验通道。
6. **Multi-target Expansion** — 增加第二国家 reference package，验证核心内核不含意大利硬编码。

## 相关文档

- [Integration Protocol 详细设计](./integration-protocol.md)
- [NewsEvent 数据结构设计](./newsevent-schema.md)
- [开源舆情监控参考项目深度研究](./brainstorming/开源舆情监控参考项目深度研究.md)
- [全维度信息获取链条与自动化机制](./brainstorming/information-acquisition-chains.md)
- [全量KOL追踪与信源动态管理机制](./brainstorming/kol-tracking-and-source-management.md)
- [通用内核与平台化架构 PRD](./brainstorming/通用内核与平台化架构PRD.md)
- [ToolManifest 与工具适配层规格](./brainstorming/ToolManifest与工具适配层规格.md)
- [AI Provider 与模型路由规格](./brainstorming/AIProvider与模型路由规格.md)
- [SandboxPolicy 与执行权限规格](./brainstorming/SandboxPolicy与执行权限规格.md)
- [Agent Skill生态调研（ClawHub及可信站点）](./brainstorming/agent-skill-ecosystem-survey.md)
- [初始架构分析（对话记录）](./brainstorming/意大利突发新闻监控系统架构分析.md)
- [Skill Registry 规范](./skill-registry-spec.md)（待写）
- [Adaptation Layer 工作流](./adaptation-workflow.md)（待写）
