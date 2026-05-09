# 全维度信息获取链条与自动化机制设计

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 深入研究与方案讨论稿
> 前置文档: [架构总览](../architecture-overview.md) | [NewsEvent Schema](../newsevent-schema.md) | [Integration Protocol](../integration-protocol.md) | [开源参考研究](./开源舆情监控参考项目深度研究.md) | [初始架构分析](./意大利突发新闻监控系统架构分析.md)

---

## 0. 核心问题

**如何用一套工具体系，对目标国家/目标领域实现全维度、有信息挖掘深度、对所有分类领域下的信源和意见领袖的分情况信息获取？**

这不是简单的"RSS聚合"或"关键词搜索"。一个真正有价值的驻外监控系统，需要实现：

1. **全维度覆盖** — 不能只看主流媒体，还要覆盖国际组织、社群、KOL、学术圈、政经实体等不同信源类别
2. **信息挖掘深度** — 不能只看标题和摘要，还要能挖掘到"谁在说什么"、"为什么说"、"对谁重要"
3. **分情况获取** — 不同信源类别有不同的获取方式（RSS/API/CLI爬取/登录态社媒/组织邮件列表），不能一刀切
4. **自动化机制** — 从发现信源、适配获取、持续监控到价值判断，整个链条尽可能减少人工干预

---

## 1. 信源全维度分类体系

### 1.1 六维信源模型

对任意目标国家，其信息生态可以从六个维度完整覆盖：

```
┌─────────────────────────────────────────────────────────────┐
│                    六维信源模型                                │
│                                                              │
│  ① 主流媒体        ② 国际组织        ③ 社交媒体              │
│  (News Media)      (Intl Orgs)      (Social Media)          │
│                                                              │
│  ④ 政府与监管      ⑤ 学术与智库      ⑥ 华人/涉华圈           │
│  (Govt & Reg)      (Academic)       (China-related)        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 各维度的信源清单（以意大利为例）

#### ① 主流媒体 (News Media)

| 信源 | 类型 | 获取方式 | 深度能力 | 优先级 |
|------|------|---------|---------|-------|
| **ANSA** | 通讯社 | RSS + OpenCLI适配器 | 政治/经济/外交分类爬取 | P0 |
| **Corriere della Sera** | 日报 | RSS + OpenCLI适配器 | 社论/评论爬取 | P0 |
| **La Repubblica** | 日报 | RSS + OpenCLI适配器 | 外交版块爬取 | P0 |
| **Il Sole 24 Ore** | 财经日报 | RSS | 经济/产业政策深度 | P1 |
| **La Stampa** | 日报 | RSS | 都灵/北方视角 | P1 |
| **Il Messaggero** | 日报 | RSS | 罗马/中部视角 | P1 |
| **Sky TG24** | 电视新闻 | 网站+OpenCLI | 实时快讯 | P1 |
| **RAI News** | 公共电视 | 网站 | 政府官方口径 | P2 |
| **Adnkronos** | 通讯社 | RSS | 与ANSA互补 | P2 |
| **Il Fatto Quotidiano** | 独立日报 | RSS | 反对派视角 | P2 |

**获取链设计**：
- **快讯通道**：ANSA + Adnkronos RSS → 每次心跳优先采集 → 触发 breaking_news 研判
- **深度通道**：Corriere + Repubblica + Il Sole 24 Ore → 每日专题爬取 → 触发 in-depth 分析
- **视角补充**：Il Fatto Quotidiano（反对派）+ Il Messaggero（罗马）+ La Stampa（北方）→ 确保政治光谱覆盖

#### ② 国际组织 (International Organizations)

| 信源 | 在意地位 | 获取方式 | 深度能力 | 优先级 |
|------|---------|---------|---------|-------|
| **FAO** | 总部罗马 | RSS + OpenCLI | 粮农/涉华项目新闻 | P0 |
| **WFP** | 总部罗马 | RSS + OpenCLI | 粮食援助/涉华合作 | P0 |
| **IFAD** | 总部罗马 | RSS | 农业发展基金/涉华项目 | P1 |
| **UNESCO Venice** | 区域办公室 | 网站 + 邮件列表 | 文化遗产/涉华议题 | P1 |
| **ICCROM** | 总部罗马 | 网站 | 文化遗产保护 | P2 |
| **NATO Defense College** | 罗马 | 网站 | 安全议题 | P2 |
| **EU agencies in Italy** | 多地 | RSS + API | 欧盟涉意政策 | P2 |
| **ICJ (via Hague)** | 无 | 网站 | 国际司法涉意涉华案件 | P1 |

**获取链设计**：
- **权威发布通道**：FAO + WFP + IFAD RSS → 监控"press release"类 → 触发 official_doc 类型研判
- **项目追踪通道**：OpenCLI爬取各组织"Projects"页面，按涉华关键词过滤 → 追踪在意中企与国际组织的合作
- **邮件列表通道**：订阅各组织press mailing list → 邮件解析为 NewsEvent（需开发 mail-to-newsevent 适配器）

#### ③ 社交媒体 (Social Media)

| 信源 | 类型 | 获取方式 | 深度能力 | 优先级 |
|------|------|---------|---------|-------|
| **Twitter/X (意大利语区)** | 微博 | OpenCLI twitter search --lang it | 关键词/话题追踪 | P0 |
| **Twitter/X (涉华关键词)** | 微博 | OpenCLI twitter search --query "Cina OR China" | 涉华议题追踪 | P0 |
| **Reddit r/italy** | 论坛 | OpenCLI reddit subreddit | 意大利舆论场 | P1 |
| **Reddit r/europe** | 论坛 | OpenCLI reddit subreddit | 欧洲视角涉意 | P2 |
| **Facebook (意大利群组)** | 社交网络 | OpenCLI facebook groups (需登录态) | 华人社区/移民议题 | P1 |
| **Telegram (意大利频道)** | 即时通讯 | 群组爬取工具 | 意大利政治讨论 | P1 |
| **YouTube (意大利新闻频道)** | 视频 | OpenCLI youtube transcript | 新闻视频字幕提取 | P2 |
| **Instagram (意KOL)** | 图片社交 | OpenCLI instagram (受限) | 视觉化舆论 | P3 |

**获取链设计**：
- **KOL追踪通道**：维护意大利意见领袖Twitter列表 → OpenCLI twitter lists → 定时爬取 → 提取观点摘要
- **话题追踪通道**：预设涉华关键词集 → OpenCLI twitter search → 情感分析 → 触发舆情研判
- **社群洞察通道**：Reddit + Facebook群组 → 发现草根舆论趋势 → 补充主流媒体覆盖盲区

#### ④ 政府与监管 (Government & Regulatory)

| 信源 | 类型 | 获取方式 | 深度能力 | 优先级 |
|------|------|---------|---------|-------|
| **Presidenza del Consiglio** | 首相府 | 网站+RSS | 政府声明/涉华政策 | P0 |
| **Ministero degli Esteri** | 外交部 | 网站+RSS | 外交政策/涉华立场 | P0 |
| **Senato della Repubblica** | 参议院 | 网站+API | 立法追踪 | P1 |
| **Camera dei Deputati** | 众议院 | 网站+API | 立法追踪 | P1 |
| **CONSOB** | 证券监管委 | 网站+RSS | 金融市场涉中企 | P2 |
| **AGCOM** | 通信监管委 | 网站+RSS | 媒体政策 | P2 |
| **Corte Costituzionale** | 宪法法院 | 网站 | 重大判决 | P2 |
| **中国驻意使馆** | 外交机构 | 网站+微信公众号 | 中方立场发布 | P0 |

**获取链设计**：
- **政策追踪通道**：Presidenza + Ministero degli Esteri RSS → 政策声明自动采集 → 触发 policy 类型研判
- **立法追踪通道**：Senato + Camera 议案进度爬取 → 涉华立法自动标记
- **中方视角通道**：中国驻意使馆 + 领事馆网站 → 中方回应/立场第一时间捕获

#### ⑤ 学术与智库 (Academic & Think Tanks)

| 信源 | 类型 | 获取方式 | 深度能力 | 优先级 |
|------|------|---------|---------|-------|
| **ISPI** (Istituto Affari Internazionali) | 智库 | 网站+RSS | 国际关系/涉华研究 | P0 |
| **IAI** (Istituto Affari Internazionali) | 智库 | 网站+RSS | 外交政策分析 | P0 |
| **EUI** (European University Institute) | 学术机构 | 网站+机构库 | 欧洲治理研究 | P1 |
| **Luiss Guido Carli** | 大学 | 网站+研究中心 | 政治/经济研究 | P2 |
| **Università Bocconi** | 大学 | 网站+研究库 | 经济/金融研究 | P2 |
| **Centro Studi Confindustria** | 行业协会 | 网站+报告 | 企业界立场 | P1 |
| **Osservatorio sul Cinese** | 专门研究 | 网站+论文 | 意大利涉华研究 | P0 |

**获取链设计**：
- **研究追踪通道**：ISPI + IAI RSS → 长报告自动摘要（LLM摘要）→ 触发深度研判
- **aminer学术通道**：aminer-open-academic Skill → 关键词"China-Italy relations" → 论文自动发现
- **报告挖掘通道**：定期爬取智库报告 → LLM提取涉华章节 → 补充权威分析视角

#### ⑥ 华人/涉华圈 (China-related Community)

| 信源 | 类型 | 获取方式 | 深度能力 | 优先级 |
|------|------|---------|---------|-------|
| **在意华人社区论坛** | 社区 | 网站+OpenCLI | 华人第一手舆情 | P0 |
| **在意中企动态** | 企业 | 网站+工商登记 | 中企在意经营状况 | P1 |
| **孔子学院在意分布** | 教育 | 网站 | 中意教育合作 | P2 |
| **在意华文媒体** | 媒体 | 网站+RSS | 华人社区声音 | P1 |
| **LinkedIn (在意中企员工)** | 职业 | OpenCLI (需登录态) | 中企人才流动 | P2 |
| **WeChat公众号** | 社交 | 公众号爬取工具 | 在意华人圈信息 | P1 |

**获取链设计**：
- **社区舆情通道**：华人论坛 + 华文媒体 → 中文情感分析 → 国内舆情共振预判
- **企业追踪通道**：在意中企网站 + 工商信息变更 → 经营风险/投资动态监测
- **微信生态通道**：WeChat公众号爬取（需专用适配器）→ 中文口语化舆情直接采集

---

## 2. 分情况信息获取链设计

### 2.1 获取链的统一抽象

每条获取链都可以抽象为一个 **SourceChannel**——一个可配置、可插拔的信息获取单元：

```yaml
SourceChannel:
  id: "ansa-politica-rss"           # 唯一标识
  dimension: "news_media"           # 六维分类之一
  source_name: "ANSA Politica"      # 显示名
  priority: "P0"                     # P0/P1/P2/P3

  # === 获取方式 ===
  acquisition_method: "rss"          # rss | opencli | api | mail_list | web_scrape
  acquisition_config:                # 方式相关的配置
    url: "https://www.ansa.it/sito/notizie/politica/rss.xml"
    poll_interval: "1h"              # 心跳轮询间隔
    auth_required: false
    login_session: null              # 需登录态的渠道填写session配置

  # === 产出映射 ===
  # 定义如何将原始数据映射到NewsEvent字段
  field_mapping:
    title: "rss.title"
    url: "rss.link"
    content: "rss.description"
    published_at: "rss.pubDate"
    language: "it"

  # === 关联Skill ===
  skill_id: "rss-collector"          # 负责此渠道的已注册Skill
  fallback_skill: "builtin-rss"      # Skill不可用时的降级实现
```

### 2.2 按获取方式的分类获取链

#### A. RSS获取链（最轻量、最可靠）

**适用信源**：有RSS feed的主流媒体、国际组织、智库

```
RSS获取链流程:
  heartbeat触发
    → 读取 SourceChannel.acquisition_config
    → HTTP GET RSS feed
    → 解析XML → 初步映射到NewsEvent(collected阶段)
    → 与 PipelineContext.memory.known_event_ids 去重
    → 新事件流入filter环节

关键设计:
  1. 去重机制: 基于 source_url + published_at 生成确定性hash，与known_event_ids比对
  2. 增量采集: 只请求上次采集时间之后的新条目（利用RSS的If-Modified-Since头）
  3. 解析容错: RSS格式不规范是常态，需lenient parser
  4. 多语言标题: 意大利语RSS标题原样保留，翻译在judge环节做
```

**Skill映射**：
- 主Skill：`rss-collector`（复用TrendRadar的RSS爬取模块，适配为NewsEvent格式）
- 降级：`builtin-rss`（Python feedparser最小实现）

#### B. OpenCLI获取链（确定性、高深度）

**适用信源**：需要登录态的社媒平台、无RSS的网站、需要结构化提取的页面

```
OpenCLI获取链流程:
  heartbeat触发
    → 读取 SourceChannel.acquisition_config
    → 执行 OpenCLI 命令 (如: opencli twitter search --lang it --query "Cina")
    → CLI wrapper 将输出转为 NewsEvent[]
    → 与已知事件去重
    → 新事件流入filter环节

关键设计:
  1. 适配器缓存: OpenCLI适配器一次生成后缓存，网站改版时opencli-autofix自动修复
  2. 登录态管理: Chrome Extension复用用户已登录session，凭证不离开浏览器
  3. Rate limit策略: 每个OpenCLI命令有最小间隔配置，避免触发平台限制
  4. 输出标准化: 每个OpenCLI适配器都映射到统一的NewsEvent字段结构

OpenCLI适配器开发优先级:
  P0: ANSA网站适配器
  P0: Twitter/X意语区适配器
  P0: FAO官网适配器
  P1: Corriere della Sera适配器
  P1: Reddit r/italy适配器
  P1: 中国驻意使馆网站适配器
  P2: 其余P2信源适配器
```

**Skill映射**：
- 主Skill：`opencli-collector`（整合OpenCLI SDK，提供统一的Skill接口）
- 降级：`web-scraping`（jamditis/claude-skills-journalism的爬取级联策略）

#### C. API获取链（结构化、高效）

**适用信源**：提供官方API的数据源

```
API获取链流程:
  heartbeat触发
    → 读取 SourceChannel.acquisition_config (含API key、endpoint)
    → 调用API endpoint
    → JSON响应解析 → 映射到NewsEvent[]
    → 去重
    → 流入filter环节

数据源:
  - World News API (292个意大利源，每日1280+文章)
  - Senato/Camera开放API (立法追踪)
  - 各组织API（如有）

关键设计:
  1. API Key管理: 凭据存储在配置中心，不进入NewsEvent或PipelineContext
  2. Rate Limit跟踪: 每个API的剩余调用额度写入PipelineContext，避免超额
  3. 响应缓存: 相同查询在短时间内不重复请求
  4. 成本控制: World News API免费层有额度限制，优先用于最关键的查询
```

**Skill映射**：
- 主Skill：`api-collector`（统一HTTP客户端，管理认证和限流）
- 降级：`web-scraping`

#### D. 邮件列表获取链（权威发布、低频高价值）

**适用信源**：国际组织press mailing list、政府通知邮件

```
邮件列表获取链流程:
  邮件到达通知 (IMAP IDLE / 轮询)
    → 解析邮件内容 (HTML/纯文本)
    → 提取关键信息 (标题、正文、附件链接)
    → 映射到NewsEvent(content_type: press_release/official_doc)
    → 标记为is_urgent=true（邮件列表通常发布重要声明）
    → 直接进入judge环节（跳过filter，因为邮件列表内容本身就是高价值的）

关键设计:
  1. 邮件解析: 支持HTML邮件、多语言编码、附件链接提取
  2. 紧急标记: 邮件列表发布通常对应权威正式声明，自动提高优先级
  3. 专用邮箱: 创建专用IMAP邮箱用于订阅各组织press list
  4. 附件处理: PDF新闻稿提取正文内容
```

**Skill映射**：
- 主Skill：`mail-collector`（需开发：IMAP监听 + 邮件解析）
- 降级：手动检查邮件列表网址

#### E. 社媒登录态获取链（高深度、高风险）

**适用信源**：需要登录才能访问的社交媒体内容（Facebook群组、LinkedIn、WeChat公众号）

```
社媒登录态获取链流程:
  heartbeat触发（频率较低，6-12小时）
    → 检查Chrome Extension登录状态
    → 执行OpenCLI命令 (如: opencli facebook groups --group "意大利华人社区")
    → 提取Posts/Comments → 映射到NewsEvent(content_type: social_post)
    → 标记为social_media来源，情感分析权重更高
    → 流入filter环节

关键设计:
  1. 登录态检测: 执行前检查Chrome Extension是否仍处于登录状态
  2. 账号风险: 自动化爬取社媒有封号风险，需要:
     - 降低频率（每个OpenCLI命令间隔>30秒）
     - 模拟人类行为（随机延迟、不连续操作）
     - 多账号轮换
  3. 伦理合规: 仅爬取公开信息和已加入群组的内容，不侵入私人空间
  4. 反爬对策: 网站改版时依赖opencli-autofix，被封IP时降级到RSS（如有）
```

**Skill映射**：
- 主Skill：`social-collector`（整合OpenCLI社媒命令 + 行为模拟策略）
- 降级：RSS feed（如果该社媒有公开RSS）

---

## 3. 信息获取深度机制

### 3.1 三层深度模型

```
┌──────────────────────────────────────────────┐
│  L1: 面上扫描 (Surface Scan)                 │
│  RSS/API定时轮询 → 标题+摘要 → 规则过滤       │
│  目标: 不漏掉重大事件                          │
│  频率: 1小时/次                               │
│  成本: 低（零LLM调用）                         │
├──────────────────────────────────────────────┤
│  L2: 深度挖掘 (Deep Mining)                   │
│  OpenCLI全文爬取 → 实体/情感/关系分析          │
│  目标: 理解事件的深层含义和关联                 │
│  频率: 6小时/次 或 事件触发                    │
│  成本: 中（少量LLM调用）                       │
├──────────────────────────────────────────────┤
│  L3: 追踪溯源 (Trace & Traceback)             │
│  多源交叉验证 → 事件全貌还原 → 影响预判         │
│  目标: 构建事件全貌，预判发展趋势               │
│  频率: 突发事件触发 或 每日汇总                 │
│  成本: 高（多轮LLM调用 + 多源爬取）             │
└──────────────────────────────────────────────┘
```

### 3.2 L1 面上扫描 — 不漏重大事件

**机制**：每次心跳，所有P0/P1的RSS和API源轮询一遍

```
心跳触发 (1h间隔)
  → 并行请求所有P0 RSS (ANSA, FAO, 外交部...)
  → 并行请求所有P1 RSS (Corriere, Repubblica, ISPI...)
  → 解析 → 去重 → 规则过滤
     → 命中涉华/突发事件关键词 → 标记is_urgent=true → 立即进入L2
     → 命中关注域关键词 → 正常排队进入L2
     → 未命中 → 归档（不浪费LLM调用）
```

**规则过滤器设计**（复用TrendRadar的两阶段过滤 + News Sentry扩展）：

```yaml
FilterRules:
  # === 涉华关键词规则 ===
  - rule_id: "keyword-china-direct"
    type: keyword
    pattern: "(Cina|China|cinese|Chinese|Pechino|Beijing|Xi Jinping|Belt and Road|Via della Seta)"
    weight: 0.9
    action: "pass_and_escalate"  # 通过并升级到L2

  - rule_id: "keyword-china-indirect"
    type: keyword
    pattern: "(Asia|asiatico|importazione|commercio|silk|mercato cinese|tecnologia cinese)"
    weight: 0.5
    action: "pass"  # 通过但不升级

  # === 实体规则 ===
  - rule_id: "entity-italy-gov"
    type: entity
    pattern: "(Meloni|Tajani|Crosetto|Cingolani|Fitto)"
    weight: 0.7
    action: "pass"

  - rule_id: "org-fao-wfp"
    type: entity
    pattern: "(FAO|WFP|IFAD|F AO|World Food|Food and Agriculture)"
    weight: 0.8
    action: "pass_and_escalate"

  # === 突发事件规则 ===
  - rule_id: "breaking-keywords"
    type: keyword
    pattern: "(ULTIM'ORA|BREAKING|terremoto|alluvione|attentato|crisi|emergenza|guerra)"
    weight: 1.0
    action: "pass_and_urgent"  # 通过并设为紧急

  # === 来源可信度规则 ===
  - rule_id: "source-credibility"
    type: source
    sources:
      ANSA: 0.95
      "Corriere della Sera": 0.90
      "La Repubblica": 0.85
      FAO: 0.98
      WFP: 0.95
      # 社媒来源可信度较低
      Twitter: 0.60
      Reddit: 0.40
      Facebook: 0.50
    action: "enrich_credibility"
```

### 3.3 L2 深度挖掘 — 理解事件深层含义

**触发条件**：L1过滤后的新闻（passed=true的NewsEvent），按优先级排队

```
L2深度挖掘流程:
  L1产出的filtered NewsEvent
    → 数量控制: 每次心跳最多处理20条（受LLM budget限制）
    → 优先级排序: breaking > significant > routine > low_priority
    → 对每条NewsEvent执行:
       a) 全文爬取（OpenCLI获取完整正文）
       b) LLM研判（news-value-judge Skill）
          - 新闻价值多维度评分
          - 涉华相关性评分
          - 情感分析
          - 实体提取（人物、组织、地点、事件、政策）
          - 生成中文摘要和深度分析
       c) 事件初步关联
          - 与known_event_ids去重
          - 与active_tracked_entities匹配
          - 初步判断是否属于已知事件的新进展
    → 产出judged NewsEvent
```

### 3.4 L3 追踪溯源 — 构建事件全貌

**触发条件**：
- L2判定为breaking_news的事件
- L2判定china_relevance > 0.7的事件
- 每日L2产出的top 10事件摘要

```
L3追踪溯源流程:
  触发事件（NewsEvent.breaking_news_level = breaking）
    → 多源交叉验证
       a) 在所有可用信源中搜索相关报道
       b) 对比不同来源的报道差异
       c) 标记矛盾信息（cross_validation.contradiction_flag）
    → 事件全貌构建
       a) 关联同一事件的所有NewsEvent（via breaking_event.event_id）
       b) 按时间线组织（initial_report → development → official_response → aftermath）
       c) 构建实体关系图（谁说了什么、涉及哪些组织、影响范围）
    → 影响预判
       a) LLM分析事件对中意关系的潜在影响
       b) 预估国内共鸣度（china_domestic_resonance）
       c) 生成研判简报，推送决策层
```

---

## 4. 自动化机制设计

### 4.1 心跳调度机制

```
心跳调度层级:

  快速心跳 (1h)
    → 执行L1面上扫描
    → 处理L1产出的紧急事件（breaking_news_level=breaking）
    → 推送飞书紧急通知

  深度心跳 (6h)
    → 执行L2深度挖掘
    → 处理L2产出的高价值事件
    → 更新Obsidian知识库
    → 推送飞书日常简报

  全量心跳 (24h)
    → 执行L3追踪溯源
    → 生成每日舆情综述报告
    → 更新活跃实体追踪列表
    → 清理过期known_event_ids
    → 评估Skill Registry中的适配器健康度
```

### 4.2 自适应调度

```yaml
AdaptiveScheduling:
  # 基础调度：按固定间隔
  base_schedule:
    fast_heartbeat: "1h"
    deep_heartbeat: "6h"
    full_heartbeat: "24h"

  # 自适应：突发事件时缩短间隔
  urgency_rules:
    - trigger: "breaking_news detected"
      action: "switch to 15min fast_heartbeat for next 2 hours"
      escalation: "notify via feishu immediately"

    - trigger: "china_relevance > 0.8"
      action: "schedule extra deep_heartbeat within 30min"

    - trigger: "3+ sources report same event"
      action: "trigger L3 trace immediately"

    - trigger: "source goes silent for >24h"
      action: "alert and check source availability"
```

### 4.3 自适应信源发现

监控系统不能只依赖预配置的信源，还需要自主发现新的有价值信源：

```
信源发现机制:

  1. 纵向发现（深度）：
     当L2深度挖掘发现某条新闻反复引用某个信源时，
     → 检查该信源是否已在SourceChannel列表中
     → 若不在：评估是否值得添加（可信度、更新频率、涉华相关性）
     → 若值得：生成新的OpenCLI适配器或添加RSS feed
     → 注册为新的SourceChannel

  2. 横向发现（广度）：
     当L3追踪溯源发现某个事件在多个社媒平台传播时，
     → 检查这些平台是否已被OpenCLI适配器覆盖
     → 若未覆盖：标记为"需要适配"
     → 触发adaptation layer的 develop 流程

  3. 全局发现（新领域）：
     当filter环节连续多次将某类新闻归类为"out_of_scope"，
     但它们属于一个新兴议题（如意大利AI监管新法）时，
     → PipelineContext记录该议题的出现频率
     → 当频率超过阈值时，创建新的focus_area
     → 自动搜索该领域的权威信源
```

### 4.4 意见领袖(KOL)追踪机制

意见领袖的追踪比信源追踪更动态，需要专门的设计：

```yaml
KOLTracking:
  # KOL registry（意见领袖注册表）
  # 存储在PipelineContext.memory中，跨心跳继承

  kol_registry:
    - name: "Giorgia Meloni"
      type: politician
      role: "意大利总理"
      platforms:
        - platform: twitter
          handle: "@GiorgiaMeloni"
          opencli_command: "opencli twitter timeline --user GiorgiaMeloni"
          poll_interval: "6h"
        - platform: facebook
          handle: "GiorgiaMeloni.it"
          opencli_command: "opencli facebook profile --id GiorgiaMeloni.it"
          poll_interval: "12h"
      tracking_focus:
        - "涉华政策声明"
        - "外交行程"
        - "经济政策"
      china_relevance_weight: 0.9

    - name: "Antonio Tajani"
      type: politician
      role: "副总理兼外长"
      platforms:
        - platform: twitter
          handle: "@Antonio_Tajani"
          opencli_command: "opencli twitter timeline --user Antonio_Tajani"
      tracking_focus:
        - "中意外交"
        - "欧盟立场"
      china_relevance_weight: 0.85

    - name: "ISPI (Istituto per gli Studi di Politica Internazionale)"
      type: think_tank
      role: "国际政治研究机构"
      platforms:
        - platform: website
          handle: "ispionline.org"
          opencli_command: "opencli ispionline publications --topic china"
      tracking_focus:
        - "中意关系报告"
        - "国际战略分析"
      china_relevance_weight: 0.80

  # KOL追踪触发规则
  kol_triggers:
    - trigger: "KOL发布涉华言论"
      action: "标记china_relevance≥0.7，进入L2深度挖掘"

    - trigger: "KOL立场转变（如从亲华转为疑华）"
      action: "触发L3追踪溯源，生成立场变化简报"

    - trigger: "新KOL出现（某人在社交平台涉华讨论中突然活跃）"
      action: "自动添加到kol_registry候选列表，待人工确认后正式追踪"
```

### 4.5 OpenCLI适配器生命周期管理

```
适配器生命周期:

  创建 (Create)
    → 识别需要适配的网站（来自SourceChannel.acquisition_method配置）
    → 使用opencli-adapter-author生成适配器
    → opencli browser verify验证
    → 注册到Skill Registry (type: adapted)
    → 标注origin_skill_id和adaptation_notes

  运行 (Run)
    → 心跳触发 → 执行OpenCLI命令
    → CLI wrapper将输出转为NewsEvent[]
    → 如有异常（空输出、格式变化），标记为needs_repair

  修复 (Repair)
    → 当检测到适配器输出异常时
    → 使用opencli-autofix自动修复
    → 修复后重新验证
    → 若自动修复失败，标记为broken，降级到web-scraping

  更新 (Update)
    → 定期检查源头skill是否有新版本
    → 若有更新，评估是否需要重新适配
    → 版本升级在维护窗口（full_heartbeat）执行

  淘汰 (Retire)
    → 当某SourceChannel连续7天无新内容时
    → 标记为dormant
    → 30天后自动归档
    → 从心跳轮询中移除（但保留在SourceChannel配置中，不删除）
```

---

## 5. 产出物：信息获取链配置总表

基于以上设计，意大利监控目标的完整SourceChannel配置如下（按优先级排序）：

### P0 — 核心信源（每1小时采集）

| ID | 维度 | 信源 | 获取方式 | Skill |
|----|------|------|---------|-------|
| ansa-rss | ①主流媒体 | ANSA Politica | RSS | rss-collector |
| ansa-opencli | ①主流媒体 | ANSA网站全文 | OpenCLI | opencli-collector |
| corriere-rss | ①主流媒体 | Corriere della Sera | RSS | rss-collector |
| repubblica-rss | ①主流媒体 | La Repubblica | RSS | rss-collector |
| fao-rss | ②国际组织 | FAO Newsroom | RSS | rss-collector |
| fao-opencli | ②国际组织 | FAO Projects(涉华) | OpenCLI | opencli-collector |
| wfp-rss | ②国际组织 | WFP News | RSS | rss-collector |
| twitter-it-china | ③社交媒体 | Twitter/X 涉华关键词 | OpenCLI | social-collector |
| twitter-meloni | ③社交媒体 | Meloni Twitter | OpenCLI | social-collector |
| governo-rss | ④政府 | Presidenza del Consiglio | RSS | rss-collector |
| esteri-rss | ④政府 | Ministero degli Esteri | RSS | rss-collector |
| cn-embassy | ④政府 | 中国驻意使馆 | OpenCLI | opencli-collector |
| ispi-rss | ⑤学术智库 | ISPI | RSS | rss-collector |
| worldnews-api | ①主流媒体 | World News API意大利 | API | api-collector |

### P1 — 重要信源（每6小时采集）

| ID | 维度 | 信源 | 获取方式 | Skill |
|----|------|------|---------|-------|
| sole24ore-rss | ①主流媒体 | Il Sole 24 Ore | RSS | rss-collector |
| lastampa-rss | ①主流媒体 | La Stampa | RSS | rss-collector |
| reddit-italy | ③社交媒体 | Reddit r/italy | OpenCLI | social-collector |
| facebook-huaren | ③社交媒体 | 意大利华人Facebook群组 | OpenCLI(登录) | social-collector |
| ifad-rss | ②国际组织 | IFAD News | RSS | rss-collector |
| senato-api | ④政府 | 参议院立法追踪 | API | api-collector |
| camera-api | ④政府 | 众议院立法追踪 | API | api-collector |
| iai-rss | ⑤学术智库 | IAI | RSS | rss-collector |
| aminer-cn-it | ⑤学术智库 | 意中关系论文 | API | aminer-open-academic |
| cn-community | ⑥华人圈 | 在意华人社区 | OpenCLI(登录) | social-collector |

### P2 — 补充信源（每24小时采集）

| ID | 维度 | 信源 | 获取方式 | Skill |
|----|------|------|---------|-------|
| skytg24-rss | ①主流媒体 | Sky TG24 | RSS | rss-collector |
| rai-rss | ①主流媒体 | RAI News | RSS | rss-collector |
| ilfatto-rss | ①主流媒体 | Il Fatto Quotidiano | RSS | rss-collector |
| youtube-it | ③社交媒体 | YouTube意大利新闻频道 | OpenCLI | opencli-collector |
| linkedin-cn-it | ⑥华人圈 | 在意中企LinkedIn | OpenCLI(登录) | social-collector |
| confindustria | ⑤学术智库 | Confindustria报告 | OpenCLI | opencli-collector |
| consob-rss | ④政府 | CONSOB公告 | RSS | rss-collector |

---

## 6. 与现有架构的映射

### 6.1 SourceChannel → Skill Registry映射

| 获取方式 | 主Skill | 降级Skill | 来源 |
|---------|---------|----------|------|
| RSS | rss-collector (TrendRadar改造) | builtin-rss | adapted |
| OpenCLI | opencli-collector (OpenCLI封装) | web-scraping | adapted |
| API | api-collector (自建) | web-scraping | purpose-built |
| 邮件 | mail-collector (自建) | 手动检查 | purpose-built |
| 社媒(登录态) | social-collector (OpenCLI+行为模拟) | 无(不可降级) | adapted |

### 6.2 三层深度 → Pipeline映射

| 深度层 | Pipeline环节 | 心跳频率 | LLM调用 |
|-------|-------------|---------|---------|
| L1 面上扫描 | collect + filter | 1h | 零（纯规则） |
| L2 深度挖掘 | collect + filter + judge | 6h | 少量 |
| L3 追踪溯源 | 全环节 + 多源交叉 | 24h 或触发 | 多轮 |

### 6.3 自适应发现 → Adaptation Layer映射

| 发现类型 | Adaptation动作 | 注册到Registry |
|---------|---------------|---------------|
| 发现新信源 | evaluate → 添加RSS/开发OpenCLI适配器 | 新SourceChannel |
| 发现新KOL | evaluate → 添加到kol_registry | 更新PipelineContext |
| 发现新领域 | 评估新focus_area → 调整filter规则 | 更新FilterRules |
| 适配器失效 | opencli-autofix → 修复或降级 | 更新Skill状态 |

---

## 7. 待深入讨论事项

1. **邮件列表适配器的实现方案** — IMAP IDLE长连接 vs 定期轮询？是否需要独立于心跳的邮件监听进程？
2. **WeChat公众号爬取的安全合规** — WeChat的反爬策略严格，是否有可靠的获取方式？
3. **KOL registry的初始种子数据** — 除了手动配置，能否从Twitter列表或学术引用中自动发现KOL？
4. **SourceChannel健康度监控** — 如何自动检测RSS feed失效、网站改版、OpenCLI适配器输出异常？
5. **多账号轮换策略** — 社媒平台Rate Limit的具体数字？需要多少个账号轮换？
6. **Adaptive Scheduling的触发阈值** — 突发事件缩短心跳的阈值如何量化？
7. **L2批量处理的LLM成本控制** — 每次心跳最多处理20条事件，成本如何估算？