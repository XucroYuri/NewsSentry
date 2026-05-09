# 信源获取渠道深化设计：全量KOL追踪与动态管理机制

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 方案讨论稿
> 前置文档: [信息获取链条与自动化机制](./information-acquisition-chains.md) | [Integration Protocol](../integration-protocol.md) | [开源参考研究](./开源舆情监控参考项目深度研究.md)

---

## 0. 核心命题

**假设：如果我们拥有一组社交媒体账号的登录态，通过OpenCLI工具模拟"关注"目标KOL账号，在限定时间范围内检查其是否存在涉华言论/话题，是否可以建立一个全量覆盖的意大利意见领袖追踪系统？**

进而推演：
1. 如果按"领域、地区、身份背景、年龄代际"等维度做全量人物清单，能否覆盖所有潜在中高影响力的泛意大利社交媒体账号？
2. 对所有账号配置不同周期的心跳轮询，能否实现整个泛意大利社交媒体的全面监控？
3. 反向追踪：中文主流媒体和社交媒体对涉意话题的讨论报道如何监控？
4. 信源清单如何动态扩展（发现新KOL）和剪枝（淘汰低价值KOL）？

---

## 1. 可行性分析：全量KOL追踪的理论基础

### 1.1 OpenCLI登录态机制的本质

OpenCLI的核心设计是**"编译期智能 vs 运行期智能"**：

```
编译期（一次性）:
  用户在Chrome中登录Twitter/X
    → Chrome Extension捕获登录session
    → 将session注册到OpenCLI Daemon
    → Daemon为该session创建持久连接通道

运行期（重复执行）:
  Agent调用 opencli twitter timeline --user Meloni
    → OpenCLI Daemon使用已注册session发起请求
    → 模拟用户视角访问目标内容
    → 返回结构化结果
    → LLM零消耗（确定性执行）
```

**关键特性**：
- 凭证不离开浏览器，安全性高
- 等同于"用户自己看到的内容"，平台难以区分自动化行为
- 一个Chrome Profile = 一个登录态 = 一个"虚拟关注者"

**理论可行性**：YES。通过多个Chrome Profile维持多个登录态，每个Profile可以独立追踪一批KOL，相当于拥有多个"驻外记者"同时在社交平台上值守。

### 1.2 全量覆盖的数学模型

```
假设意大利社交媒体生态:
  Twitter/X 活跃政治/外交/经济类账号: ~5,000
  Facebook 活跃公共主页/群组: ~10,000
  Instagram 活跃公共人物账号: ~15,000
  YouTube 活跃新闻频道: ~2,000
  Telegram 活跃频道: ~3,000
  LinkedIn 活跃政商人物: ~8,000

需要追踪的中高影响力账号（筛选后）:
  Twitter/X: ~500 (涉华相关高频发言者)
  Facebook: ~300 (涉华议题公共主页/群组)
  Instagram: ~200 (意KOL涉华发声)
  YouTube: ~100 (涉华新闻频道)
  Telegram: ~150 (涉华讨论频道)
  LinkedIn: ~200 (中在意商界人士)

合计需要追踪的KOL账号: ~1,450
```

**关键洞察**：不需要追踪"所有意大利社交媒体账号"，只需要追踪**在涉华议题上有潜在影响力的账号**。经过筛选，实际需要追踪的量级在1,000-2,000之间，完全在技术可达范围内。

### 1.3 账号与心跳的资源估算

```
每个社交媒体账号的心跳资源消耗:

  Twitter/X:
    - Rate limit: ~900 requests/15min (API), 但OpenCLI走session更宽松
    - 每个KOL timeline请求: ~1 request
    - 单次心跳可检查: ~100个KOL
    - 需要的账号数: 500/100 = 5个Twitter账号
    - 轮询周期: P0账号4h, P1账号12h, P2账号24h

  Facebook:
    - Rate limit: 更宽松（走session非API）
    - 每个群组/主页: ~1 request
    - 单次心跳可检查: ~50个群组
    - 需要的账号数: 300/50 = 6个Facebook账号
    - 轮询周期: 12h

  其他平台类似...

总资源需求:
  Chrome Profile数: ~15-20个（覆盖Twitter/Facebook/LinkedIn）
  服务器资源: 1台Mac mini或云桌面（跑Chrome+Daemon）
  并发心跳: 分时段错开，避免同时触发所有轮询
```

---

## 2. 全量KOL清单的维度设计与构建方法

### 2.1 八维度人物清单模型

不只是"谁有影响力"，而是**"谁在什么维度上对涉华议题有影响力"**：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     八维度KOL清单模型                                      │
│                                                                          │
│  ① 政治权力层        ② 外交/安全层        ③ 经济/产业层                    │
│  (Political Power)   (Diplomacy/Security)  (Economy/Industry)             │
│                                                                          │
│  ④ 媒体/舆论层       ⑤ 学术/智库层        ⑥ 社会运动/NGO层                │
│  (Media/Opinion)     (Academic/ThinkTank) (Social/NGO)                    │
│                                                                          │
│  ⑦ 地方/区域层       ⑧ 华人/涉华圈                                        │
│  (Regional/Local)    (Chinese/Diaspora)                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各维度人物清单与获取策略

#### ① 政治权力层 (Political Power)

追踪目标：在涉华政策上有直接决策权或影响力的人物

| 分类 | 代表人物/组织 | 数量估算 | 平台 | 轮询周期 | 获取命令 |
|------|-------------|---------|------|---------|---------|
| 总理/内阁 | Meloni, Tajani, Crosetto... | ~20 | Twitter, Facebook | 4h | `opencli twitter timeline --user {handle}` |
| 参众议员 | 对华政策相关委员会成员 | ~50 | Twitter | 12h | `opencli twitter search --query "from:{handle} Cina"` |
| 党魁/党派 | Salvini, Conte, Schlein... | ~15 | Twitter, Facebook | 6h | `opencli twitter timeline --user {handle}` |
| 欧洲议会议员(意籍) | 涉华立场活跃者 | ~30 | Twitter | 12h | `opencli twitter search --query "from:{handle} China"` |
| 地方首长 | 罗马、米兰、都灵市长等 | ~20 | Twitter, Facebook | 24h | `opencli twitter timeline --user {handle}` |

**关键获取策略**：对政治权力层使用**定向搜索**而非全量timeline爬取
- 搜索命令：`opencli twitter search --query "from:{handle} (Cina OR China OR cinese OR Xi OR Belt AND Road)"`
- 只搜索涉华相关发言，避免拉取大量无关内容
- 但对P0级人物（总理、外长）做全量timeline追踪，因为其所有发言都可能间接影响中意关系

#### ② 外交/安全层 (Diplomacy/Security)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| 外交部高级官员 | 大使、司长 | ~15 | Twitter | 6h |
| 驻华使节 | 意大利驻华大使 | ~5 | Twitter | 12h |
| 安全/国防官员 | 国防参谋长等 | ~10 | Twitter | 12h |
| NATO/EU安全机构在意人员 | NATO Defense College | ~10 | Twitter, LinkedIn | 24h |
| 中国驻意外交官 | 大使、参赞 | ~10 | Twitter, 微信 | 6h |

**获取策略**：外交部官员全量追踪 + 驻华使节定向搜索涉意发言

#### ③ 经济/产业层 (Economy/Industry)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| Confindustria高层 | 主席、行业分会负责人 | ~20 | LinkedIn, Twitter | 24h |
| 在意中企高管 | 海尔欧洲、中远海运、华为意 | ~30 | LinkedIn | 24h |
| 意大利对华出口企业 | 葡萄酒、时尚、机械企业高管 | ~50 | LinkedIn, Twitter | 24h |
| 金融监管者 | CONSOB, Bank of Italy | ~15 | Twitter | 12h |
| 行业协会 | 中意商会等 | ~10 | LinkedIn | 24h |

**获取策略**：LinkedIn是主战场（商业人士首选平台），但LinkedIn反爬严格，需要精心设计轮询间隔

#### ④ 媒体/舆论层 (Media/Opinion)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| 主流媒体外交/经济记者 | ANSA, Corriere, Repubblica外记 | ~40 | Twitter | 4h |
| 专栏作家/评论员 | 涉华议题专栏作者 | ~30 | Twitter, Facebook | 6h |
| 政治脱口秀主持人 | RAI, Sky TG24评论员 | ~20 | Twitter, YouTube | 12h |
| 独立记者/博主 | 意中关系独立研究者 | ~20 | Twitter, YouTube, 博客 | 12h |
| 外国驻意记者 | Reuters, AP, Xinhua驻罗马 | ~15 | Twitter | 6h |

**获取策略**：记者是高频发布者，全量timeline会拉取大量无关内容。优先使用**搜索模式**，只拉取涉华关键词相关的推文

#### ⑤ 学术/智库层 (Academic/ThinkTank)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| ISPI/IAI研究员 | 中国/亚洲研究项目 | ~20 | Twitter, LinkedIn | 12h |
| 大学教授 | Luiss, Bocconi, EUI涉中研究 | ~30 | Twitter, LinkedIn, Google Scholar | 24h |
| 研究机构 | Osservatorio sul Cinese等 | ~10 | 网站, Twitter | 24h |
| 在意华裔学者 | 各大学华裔教授 | ~15 | Twitter, LinkedIn | 24h |

**获取策略**：低频深度追踪。学术发布频率低但价值高，轮询周期可长但需要全文爬取分析

#### ⑥ 社会运动/NGO层 (Social/NGO)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| 环保组织 | 涉中企环境争议 | ~10 | Twitter, Facebook | 24h |
| 人权组织 | 涉华人权议题 | ~10 | Twitter | 24h |
| 工会组织 | 涉中企劳工议题 | ~10 | Facebook, Twitter | 24h |
| 移民/难民组织 | 华人移民议题 | ~10 | Facebook | 24h |
| 反全球化/反中运动 | 极端立场组织 | ~10 | Twitter, Telegram | 12h |

**获取策略**：NGO层关注的是"反面声音"——涉华议题的批评者和反对者，对全面把握舆情光谱至关重要

#### ⑦ 地方/区域层 (Regional/Local)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| 伦巴第（米兰） | 大区主席、商会 | ~15 | Twitter, Facebook | 24h |
| 拉齐奥（罗马） | 大区主席、市政府 | ~15 | Twitter | 24h |
| 皮埃蒙特（都灵） | 大区主席、FIAT相关 | ~10 | Twitter | 24h |
| 威尼托（威尼斯） | 大区主席、UNESCO相关 | ~10 | Twitter | 24h |
| 托斯卡纳（佛罗伦萨） | 大区主席、旅游/文化 | ~10 | Twitter | 24h |
| 南部（那不勒斯/巴勒莫） | 南方发展/移民 | ~10 | Twitter, Facebook | 24h |

**获取策略**：地方层关注"地域性涉华事件"——中企在地方的投资争议、地方对华政策差异、华人社区的地方动态

#### ⑧ 华人/涉华圈 (Chinese/Diaspora)

| 分类 | 代表 | 数量估算 | 平台 | 轮询周期 |
|------|------|---------|------|---------|
| 在意华商 | 中餐/批发/跨境电商协会 | ~20 | Facebook, 微信 | 12h |
| 在意华文媒体 | 意大利华人报/欧华时报 | ~10 | 微信, 网站 | 12h |
| 孔子学院 | 各城市孔院院长/教师 | ~10 | 微信, LinkedIn | 24h |
| 在意留学生 | 学联组织 | ~10 | 微信, 小红书 | 24h |
| 中国官方在意机构 | 使馆、领馆、新华社罗马分社 | ~10 | 微信, 网站 | 6h |

**获取策略**：华人圈的核心平台是**微信**（而非Twitter/Facebook），这需要专门的获取适配器

### 2.3 人物清单的总规模与分优先级

```
全量KOL清单规模估算:

  ① 政治权力层:     ~135人   (P0: 20, P1: 65, P2: 50)
  ② 外交/安全层:     ~50人   (P0: 15, P1: 15, P2: 20)
  ③ 经济/产业层:    ~125人   (P0: 20, P1: 50, P2: 55)
  ④ 媒体/舆论层:    ~125人   (P0: 40, P1: 50, P2: 35)
  ⑤ 学术/智库层:     ~75人   (P0: 10, P1: 30, P2: 35)
  ⑥ 社会运动/NGO:    ~50人   (P1: 20, P2: 30)
  ⑦ 地方/区域层:     ~70人   (P1: 30, P2: 40)
  ⑧ 华人/涉华圈:     ~60人   (P0: 10, P1: 30, P2: 20)

  合计:            ~690人   (P0: 115, P1: 290, P2: 285)

  考虑到每个KOL可能在2-3个平台活跃:
  实际需要追踪的(KOL, 平台)对: ~1,500-2,000个

  这是完全在技术可达范围内的规模。
```

---

## 3. KOL追踪的OpenCLI实现方案

### 3.1 多账号Session池设计

```yaml
SessionPool:
  # 管理多个Chrome Profile的登录态
  # 每个Profile对应一个社交媒体账号

  twitter_accounts:
    - profile: "chrome-twitter-monitor-1"
      purpose: "P0级KOL全量timeline追踪"
      kols_assigned: 25      # 该账号追踪的KOL数量
      daily_request_budget: 500
      current_status: "active"

    - profile: "chrome-twitter-monitor-2"
      purpose: "P1级KOL定向搜索"
      kols_assigned: 50
      daily_request_budget: 400
      current_status: "active"

    - profile: "chrome-twitter-monitor-3"
      purpose: "涉华关键词全局搜索"
      kols_assigned: 0        # 不追踪特定KOL，做全局搜索
      daily_request_budget: 300
      current_status: "active"
      search_queries:
        - "Cina OR China (lang:it)"
        - "Belt and Road Italia"
        - "immigrazione cinese"
        - "imprese cinesi Italia"

    - profile: "chrome-twitter-monitor-4"
      purpose: "备用/轮换"
      kols_assigned: 0
      daily_request_budget: 200
      current_status: "standby"

  facebook_accounts:
    - profile: "chrome-facebook-monitor-1"
      purpose: "华人社区群组监控"
      groups_assigned: 15
      daily_request_budget: 200
      current_status: "active"

    - profile: "chrome-facebook-monitor-2"
      purpose: "意大利政治人物/政党主页"
      pages_assigned: 20
      daily_request_budget: 200
      current_status: "active"

  linkedin_accounts:
    - profile: "chrome-linkedin-monitor-1"
      purpose: "中企高管/商业人士"
      profiles_assigned: 30
      daily_request_budget: 100
      current_status: "active"

  wechat_accounts:
    - profile: "chrome-wechat-monitor-1"    # 微信需要特殊处理
      purpose: "公众号/群聊监控"
      accounts_assigned: 20
      daily_request_budget: 50
      current_status: "active"
      method: "web_wechat"                   # 微信网页版或桌面客户端桥接
```

### 3.2 心跳轮询的具体执行模式

#### 模式A：Timeline轮询（P0级KOL）

适用于：需要追踪该KOL所有发言的核心人物（总理、外长等）

```bash
# 心跳周期: 4小时
# 目的: 拉取P0级KOL的最新timeline，检查是否有涉华发言

# 每次心跳执行（按Session分配错开）
# Session 1: 追踪25个P0级KOL
for kol in "${P0_KOL_LIST_SESSION1[@]}"; do
  # 拉取最近4小时的推文（since_id机制）
  opencli twitter timeline --user "$kol" --since "$LAST_TWEET_ID" --format json

  # 间隔2秒，模拟人类行为
  sleep 2
done

# 产出: 每个KOL最近4小时的所有推文
# 后续处理:
#   1. 规则过滤：涉华关键词匹配
#   2. 全量保留：P0级KOL的所有推文都存档（即使不涉华），用于后续趋势分析
#   3. 涉华标记：命中关键词的推文标记china_relevance，进入L2深度研判
```

#### 模式B：定向搜索（P1/P2级KOL + 涉华关键词）

适用于：不需要追踪所有发言，只关注涉华相关内容的中高影响力人物

```bash
# 心跳周期: 12小时
# 目的: 在P1/P2级KOL的发言中搜索涉华关键词

# 构建搜索查询
# 搜索特定用户的涉华发言
opencli twitter search --query "from:SalviniPremier (Cina OR China OR cinese)" --format json
opencli twitter search --query "from:berlusconi (Cina OR China OR cinese)" --format json

# 或者批量搜索（更高效）
# 将多个KOL的handle组合成OR查询
opencli twitter search --query "(from:user1 OR from:user2 OR from:user3) (Cina OR China)" --format json

# 产出: 只包含涉华关键词的推文
# 后续处理: 直接进入L2研判（因为已经过关键词预筛）
```

#### 模式C：全局话题搜索（无特定KOL）

适用于：发现不在已知KOL列表中的新声音

```bash
# 心跳周期: 6小时
# 目的: 在意大利语Twitter空间搜索涉华话题，发现新的高影响力发言

# 全局关键词搜索
opencli twitter search --query "Cina Italia -is:retweet lang:it" --format json
opencli twitter search --query "China Italy -is:retweet lang:en" --format json
opencli twitter search --query "#Cina #Italia" --format json

# 产出: 意大利语/英语空间中所有涉意涉华的原创推文
# 后续处理:
#   1. 按互动量排序（点赞+转发+评论）
#   2. 高互动推文的作者 → 评估是否应加入KOL清单
#   3. 低互动推文 → 聚合为"话题热度快照"
```

#### 模式D：Facebook群组/页面监控

```bash
# 心跳周期: 12小时
# 目的: 监控Facebook上的涉华讨论

# 群组新帖搜索
opencli facebook groups --group "意大利华人社区" --since "12h" --format json
opencli facebook groups --group "Cinesi in Italia" --since "12h" --format json

# 政治人物主页
opencli facebook profile --id "GiorgiaMeloni.it" --since "12h" --format json

# 产出: 群组/主页最近12小时的新帖
# 后续处理:
#   1. 中文内容 → sentiment-analyzer-zh
#   2. 意大利语内容 → LLM研判 + 涉华相关性评分
```

#### 模式E：微信生态监控（特殊处理）

```bash
# 微信无法直接用OpenCLI，需要特殊桥接方案
# 方案1: 微信网页版 + OpenCLI浏览器桥接
# 方案2: 微信PC客户端 + OCR截图提取
# 方案3: 第三方微信API聚合服务（如WeChatSaaS）

# 监控目标: 公众号文章
# 心跳周期: 12小时

# 方法: 使用微信PC客户端打开公众号
# → 截图保存 → OCR提取文字 → LLM结构化 → NewsEvent
# 此方案成本较高，仅对P0级微信源使用
```

---

## 4. 中文媒体涉意话题反向追踪

### 4.1 设计思路

监控系统不仅要追踪"意大利人怎么说中国"，还要追踪"中国人怎么说意大利"。这是双向舆情的完整画面：

```
意大利 → 中国（已有设计）:
  意大利媒体/政要涉华言论 → 追踪 → 研判 → 推送

中国 → 意大利（新增需求）:
  中国媒体/网民涉意言论 → 追踪 → 研判 → 对比分析

双向联动:
  同一事件的中意双方舆论 → 交叉对比 → 差异分析 → 深度研判
```

### 4.2 中文信源维度

#### A. 中文主流媒体

| 信源 | 类型 | 获取方式 | 涉意关注焦点 | 优先级 |
|------|------|---------|------------|-------|
| **新华社** | 通讯社 | RSS + 网站 | 中意关系、在意中企、国际组织涉华 | P0 |
| **人民日报** | 日报 | RSS + 网站 | 中意关系、涉意外交立场 | P0 |
| **央视新闻** | 电视 | 网站 + YouTube | 意大利重大事件、中意合作 | P1 |
| **环球时报** | 日报 | RSS + 网站 | 涉意争议性议题、对华立场 | P1 |
| **参考消息** | 日报 | 网站 | 意大利国际动态编译 | P1 |
| **中国日报(China Daily)** | 英文日报 | RSS | 面向国际的中意关系叙事 | P1 |
| **经济日报** | 财经 | RSS | 在意中企、中意经贸 | P2 |
| **中国青年报** | 日报 | RSS | 留学意大利、青年交流 | P2 |

**获取链**：
- RSS feed → rss-collector → NewsEvent(language: zh) → filter(涉意关键词) → judge(中文情感+涉意相关性) → output
- 涉意关键词：`意大利|罗马|米兰|中意|梅洛尼|FAO|粮农组织|一带一路+意大利`

#### B. 中文社交媒体

| 信源 | 类型 | 获取方式 | 涉意关注焦点 | 优先级 |
|------|------|---------|------------|-------|
| **微博** | 微博 | TrendRadar热榜 + OpenCLI搜索 | 意大利热搜话题、涉意舆论 | P0 |
| **微信公众号** | 长文 | 爬取/聚合API | 深度涉意分析文章 | P0 |
| **小红书** | 生活社交 | OpenCLI/爬取 | 意大利留学/旅游/生活 | P1 |
| **抖音** | 短视频 | TrendRadar热榜 | 意大利相关短视频传播 | P1 |
| **B站** | 视频 | OpenCLI搜索 | 意大利相关长视频内容 | P2 |
| **知乎** | 问答 | OpenCLI搜索 | 意大利深度讨论 | P2 |
| **豆瓣** | 社区 | 爬取 | 意大利文化/电影讨论 | P3 |

**获取链**：
- 微博热榜：复用TrendRadar的热榜爬取能力（原生支持微博热搜）
- 微博搜索：`opencli weibo search --query "意大利"` → 涉意微博
- 公众号：第三方聚合API或专用爬虫 → 长文提取 → LLM涉意相关性研判
- TrendRadar的35+平台覆盖对中文社交媒体几乎是开箱即用

#### C. 中文学术/智库

| 信源 | 类型 | 获取方式 | 涉意关注焦点 | 优先级 |
|------|------|---------|------------|-------|
| **中国社科院** | 智库 | 网站+aminer | 欧洲研究/意大利研究 | P1 |
| **中国国际问题研究院** | 智库 | 网站 | 中意/中欧关系 | P1 |
| **现代国际关系研究院** | 智库 | 网站 | 安全/涉意 | P2 |
| **各大学欧洲研究中心** | 学术 | aminer-open-academic | 学术论文追踪 | P2 |

**获取链**：
- aminer-open-academic Skill → 关键词"Italy-China relations" → 中文学术论文自动发现
- 智库网站RSS/OpenCLI → 报告自动摘要

### 4.3 双向舆情交叉分析

```yaml
CrossAnalysis:
  # 当同一事件在中意双方媒体都有报道时，触发交叉分析

  trigger:
    - "同一NewsEvent在中文和意大利语源都出现"
    - "PipelineContext.memory中同一event_id关联了中意两种语言的NewsEvent"

  analysis_dimensions:
    # 意大利方面怎么说
    italy_narrative:
      - "意大利媒体的叙事框架是什么"
      - "意大利政要的表态是什么"
      - "意大利公众的反应是什么"

    # 中国方面怎么说
    china_narrative:
      - "中国媒体的叙事框架是什么"
      - "中国官方的表态是什么"
      - "中国网民的反应是什么"

    # 差异分析
    gap_analysis:
      - "中意叙事差异在哪里"
      - "哪些事实被双方选择性忽略"
      - "情感温度差（意大利vs中国）"
      - "是否存在信息不对称可被利用"

  output:
    - "双向舆情对比简报"
    - "差异分析报告"
    - "信息差预警（如中国未关注但意大利热议的涉华事件）"
```

---

## 5. 信源动态扩展与剪枝机制

### 5.1 动态扩展：发现新KOL

KOL清单不是静态的，需要持续发现和吸纳新出现的意见领袖。

#### 扩展机制A：全局话题搜索发现

```
执行时机: 每次全局话题搜索心跳（6h间隔）

流程:
  1. opencli twitter search "Cina Italia -is:retweet lang:it"
  2. 按互动量排序结果
  3. 提取top 20推文的作者信息
  4. 检查每个作者是否已在KOL清单中
  5. 对不在清单中的作者:
     a) 获取其profile信息（粉丝数、认证状态、发文频率）
     b) 评估影响力分数: influence_score = f(followers, verified, engagement_rate, topic_relevance)
     c) 若 influence_score > threshold:
        → 标记为"candidate KOL"
        → 自动加入P2级追踪清单（观察期）
        → 3天后评估：观察期内涉华发言频率
        → 若发言频率达标 → 正式加入KOL清单
        → 若发言频率不达标 → 移出观察期

阈值设计:
  - followers > 10,000 且 verified = true → 直接进入P1
  - followers > 5,000 且 涉华发言频率 > 2次/周 → 进入P2观察期
  - followers < 5,000 但 engagement_rate极高 → 进入P2观察期
```

#### 扩展机制B：引用/转推链发现

```
执行时机: L2深度挖掘时

流程:
  1. 当一条涉华推文被judge判定为高价值时
  2. 获取该推文的引用/转推链
  3. 分析转推者中是否有不在KOL清单中的高影响力账号
  4. 对高影响力的转推者:
     a) 评估其与涉华议题的历史关联
     b) 若关联度高 → 加入KOL候选清单
```

#### 扩展机制C：新闻引用发现

```
执行时机: L1面上扫描时

流程:
  1. 当某条意大利新闻引用了社交媒体上的发言
  2. 提取被引用的账号信息
  3. 若该账号不在KOL清单中:
     a) 评估其被引用频率（同一账号被多少家媒体引用过）
     b) 若被引用频率 > 阈值 → 加入KOL清单
```

#### 扩展机制D：跨平台身份关联

```
执行时机: KOL清单维护时（24h心跳）

流程:
  1. 对已有KOL清单中的人物
  2. 检查是否在其他平台也有活跃账号
  3. 例如: 某教授已在Twitter清单中，但发现其也有LinkedIn和YouTube频道
  4. 将新的平台账号关联到同一KOL条目
  5. 更新SourceChannel配置，增加新平台的轮询
```

### 5.2 动态剪枝：淘汰低价值KOL

信源清单不能无限膨胀，需要定期剪枝淘汰不再有价值的追踪对象。

#### 剪枝机制A：沉默检测

```
执行时机: 每周全量心跳

检测规则:
  - KOL在观察平台上的最近发言时间 > 30天 → 标记为"dormant"
  - KOL最近90天涉华发言次数 = 0 → 标记为"china_irrelevant"
  - KOL账号被冻结/注销 → 标记为"unavailable"

处理:
  dormant:
    → 轮询周期降级: 4h → 24h
    → 60天仍dormant → 移出活跃清单，归入"历史KOL"库
    → 不删除记录（未来可能回归）

  china_irrelevant:
    → 从涉华定向搜索列表中移除
    → 保留在timeline追踪列表（如果是P0级人物）
    → 若同时是P2级且dormant → 移出

  unavailable:
    → 立即停止轮询
    → 7天后重试检测
    → 30天仍不可用 → 归入"历史KOL"库
```

#### 剪枝机制B：价值重评估

```
执行时机: 每月全量评估

评估维度:
  1. 涉华发言频率: 近30天涉华发言次数
  2. 影响力趋势: 粉丝数变化、互动率变化
  3. 信息独占性: 该KOL是否提供了其他信源无法覆盖的信息
  4. 研判命中率: 该KOL的发言被judge判定为高价值的比例

评分公式:
  retention_score = (
    0.3 * 涉华发言频率归一化
    + 0.2 * 影响力趋势归一化
    + 0.3 * 信息独占性评分
    + 0.2 * 研判命中率
  )

处理:
  retention_score > 0.6 → 保持当前优先级
  retention_score 0.3-0.6 → 降级优先级 (P0→P1→P2)
  retention_score < 0.3 → 移入观察期，90天后无改善则移出
```

#### 剪枝机制C：成本优化剪枝

```
执行时机: 当Session池资源接近上限时

触发条件:
  - 某个社交媒体账号的daily_request_budget使用率 > 90%
  - 新增KOL需要分配到已有Session但空间不足

处理:
  1. 计算每个已追踪KOL的"性价比" = 研判命中次数 / 消耗的request数
  2. 性价比最低的10% KOL → 降级或暂停追踪
  3. 释放的request空间分配给更高价值的KOL或新增KOL
```

### 5.3 KOL清单的数据结构

```yaml
KOLEntry:
  # === 身份 ===
  kol_id: "kol-meloni-giorgia"         # 唯一ID
  name: "Giorgia Meloni"
  name_zh: "焦尔吉亚·梅洛尼"
  dimension: "political_power"          # 八维度分类
  role: "意大利总理"
  influence_level: "P0"                 # P0/P1/P2
  influence_score: 0.95                 # 综合影响力评分

  # === 平台账号 ===
  platforms:
    - platform: "twitter"
      handle: "@GiorgiaMeloni"
      verified: true
      followers: 2200000
      opencli_command: "opencli twitter timeline --user GiorgiaMeloni"
      session_pool: "twitter-monitor-1"
      poll_interval: "4h"
      poll_mode: "full_timeline"         # full_timeline | targeted_search | global_search
      search_queries: []                 # targeted_search模式的查询模板

    - platform: "facebook"
      handle: "GiorgiaMeloni.it"
      verified: true
      followers: 5500000
      opencli_command: "opencli facebook profile --id GiorgiaMeloni.it"
      session_pool: "facebook-monitor-2"
      poll_interval: "12h"
      poll_mode: "targeted_search"
      search_queries:
        - "Cina OR China OR cinese"

    - platform: "instagram"
      handle: "@giorgiameloni.mp"
      verified: true
      followers: 3800000
      opencli_command: "opencli instagram profile --user giorgiameloni.mp"
      session_pool: null                 # 暂不追踪Instagram
      poll_interval: null
      poll_mode: null
      note: "Instagram图片内容为主，涉华文字信息少，暂不纳入"

  # === 涉华追踪配置 ===
  china_tracking:
    focus_topics:
      - "涉华政策声明"
      - "外交行程(含中国相关)"
      - "一带一路立场"
      - "中意经贸合作"
    keyword_sets:
      it: ["Cina", "cinese", "Pechino", "Via della Seta", "Xi Jinping"]
      en: ["China", "Chinese", "Beijing", "Belt and Road"]

  # === 追踪状态 ===
  tracking_status:
    status: "active"                    # active | dormant | observing | unavailable | archived
    added_at: "2026-05-01"
    last_china_post_at: "2026-05-09T08:30:00Z"
    last_poll_at: "2026-05-09T14:00:00Z"
    china_posts_last_30d: 12
    judge_hit_rate: 0.75                 # 发言被judge判定为高价值的比例
    retention_score: 0.92                # 留存评分

  # === 来源信息 ===
  source:
    added_by: "initial_seed"             # initial_seed | topic_search | retweet_chain | news_citation | manual
    origin_event: null                    # 通过哪个事件发现的（如有）
    cross_platform_linked: true          # 是否已关联其他平台账号
```

---

## 6. 信源清单管理工具

### 6.1 KOL Registry Manager

需要一个管理工具来维护整个KOL清单的增删改查和动态调整：

```yaml
KOLRegistryManager:
  # 核心功能
  functions:
    - "add_kol"              # 添加新KOL（含扩展机制自动触发）
    - "remove_kol"           # 移除KOL（含剪枝机制自动触发）
    - "update_kol"           # 更新KOL信息（平台变化、影响力变化等）
    - "reassign_priority"    # 调整优先级（P0/P1/P2）
    - "link_platform"        # 关联新平台账号到已有KOL
    - "health_check"         # 检查KOL账号可用性
    - "cost_optimize"        # 成本优化（重新分配Session资源）

  # 存储
  storage:
    format: "yaml"                     # 人类可读、Obsidian友好
    path: "config/kol_registry/"
    structure:
      - "political_power.yaml"         # 按维度分文件
      - "diplomacy_security.yaml"
      - "economy_industry.yaml"
      - "media_opinion.yaml"
      - "academic_thinktank.yaml"
      - "social_ngo.yaml"
      - "regional_local.yaml"
      - "chinese_diaspora.yaml"
      - "china_sources.yaml"           # 中文信源单独管理

  # 自动化触发
  triggers:
    - event: "global_search_heartbeat"
      action: "run discovery mechanism A"

    - event: "high_value_judgment"
      action: "run discovery mechanism B (retweet chain)"

    - event: "weekly_full_heartbeat"
      action: "run pruning mechanism A (dormant detection)"

    - event: "monthly_evaluation"
      action: "run pruning mechanism B (value re-evaluation)"

    - event: "session_budget_near_limit"
      action: "run pruning mechanism C (cost optimization)"
```

### 6.2 SourceChannel配置与KOL清单的联动

```
SourceChannel（信息获取渠道）与KOLEntry（意见领袖条目）的映射关系:

  一个KOLEntry可以对应多个SourceChannel:
    KOLEntry: Meloni
      → SourceChannel: twitter-meloni-timeline (poll: 4h, mode: full)
      → SourceChannel: facebook-meloni-profile (poll: 12h, mode: search)
      → SourceChannel: gobierno-rss (非KOL，是机构RSS，但关联同一人物)

  一个SourceChannel可以服务多个KOLEntry:
    SourceChannel: twitter-search-china-it (poll: 6h, mode: global_search)
      → 服务所有在Twitter上的P1/P2级KOL的涉华搜索
      → 同时发现新的candidate KOL

  心跳调度时的资源分配:
    Session Pool → 为每个SourceChannel分配执行时间和request预算
    → 编排器按优先级排序所有待执行的SourceChannel
    → 按Session容量分配：P0通道优先执行，P2通道最后执行
    → 若Session budget不足，跳过本轮P2通道
```

---

## 7. 中文媒体涉意追踪的专属设计

### 7.1 中文信源的获取方式矩阵

| 获取方式 | 适用平台 | Skill | 改造来源 |
|---------|---------|-------|---------|
| TrendRadar热榜 | 微博、抖音、B站、知乎、小红书 | trendradar-china-hotlist | 改造TrendRadar（direct） |
| OpenCLI搜索 | 微博、B站 | opencli-china-search | 改造OpenCLI weibo适配器 |
| RSS | 新华社、人民日报、环球时报 | rss-collector | 直接使用 |
| 网站/爬取 | 智库网站、公众号聚合平台 | web-scraping | 直接使用 |
| aminer学术 | 中文学术论文 | aminer-open-academic | 直接使用 |
| 微信公众号 | 涉意华文公众号 | wechat-collector | purpose-built |

### 7.2 中文涉意关键词集

```yaml
ChinaToItalyKeywords:
  # 官方叙事关键词（主流媒体会用）
  official_narrative:
    - "意大利"
    - "罗马"
    - "米兰"
    - "中意关系"
    - "中意合作"
    - "梅洛尼"
    - "粮农组织|FAO"
    - "一带一路+意大利"
    - "中国驻意使馆"
    - "意大利总理"

  # 民间叙事关键词（社交媒体会用）
  folk_narrative:
    - "意大利+华人"
    - "意大利+留学生"
    - "意大利+安全"
    - "意大利+歧视"
    - "意大利+移民"
    - "中餐+意大利"
    - "普拉托"          # 意大利华人最集中的城市
    - "温州人+意大利"    # 在意华人最大来源地

  # 经济关键词
  economic:
    - "中企+意大利"
    - "华为+意大利"
    - "中远海运"
    - "意大利+投资"
    - "意大利+贸易"
    - "意甲+中资"       # 中国资本投资意大利足球

  # 突发事件关键词
  breaking:
    - "意大利+地震"
    - "意大利+洪水"
    - "意大利+事故"
    - "意大利+恐怖"
    - "意大利+抗议"
    - "意大利+选举"
```

### 7.3 双向舆情联动机制

```
事件触发链:

  场景1: 意大利先爆，中国跟进
  ─────────────────────────────
  ANSA报道: "Meloni criticizes China trade policy"
    → News Sentry捕获 (意大利语源, stage=judged, china_relevance=0.9)
    → 触发中文侧搜索: 微博/微信搜索"梅洛尼+中国"
    → 若中国侧有反应: 生成双向舆情对比简报
    → 若中国侧无反应: 标记为"信息差——意方对中国批评但中方未关注"

  场景2: 中国先爆，意大利跟进
  ─────────────────────────────
  微博热搜: "意大利歧视华人事件"
    → TrendRadar热榜捕获 (中文源, stage=filtered)
    → 触发意大利侧搜索: Twitter/ANSA搜索相关报道
    → 若意大利有报道: 生成双向舆情对比简报
    → 若意大利无报道: 标记为"信息差——中方关注但意方未回应"

  场景3: 双方同时爆发
  ─────────────────────
  同一事件在中意双方同时成为热点
    → 自动触发L3追踪溯源
    → 生成完整的双向舆情深度报告
    → 紧急推送决策层
```

---

## 8. 风险与约束

### 8.1 社交媒体平台风险

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| 账号封禁（自动化行为被检测） | 高 | 降低频率、模拟人类行为、多账号轮换、备用账号 |
| Rate Limit超额 | 中 | 每个Session严格预算控制、分时段执行、P2降级 |
| 平台API/接口变更 | 中 | opencli-autofix自动修复、监控适配器健康度 |
| 登录态过期 | 低 | 定期检测登录态、自动刷新或告警人工刷新 |
| 法律合规风险 | 高 | 仅追踪公开发言、不侵入私人对话、遵守GDPR |
| 舆论操控风险 | 中 | KOL发言不等于真相，研判环节需交叉验证 |

### 8.2 微信生态的特殊困难

微信是封闭生态，获取难度远高于Twitter/Facebook：

| 方案 | 可行性 | 成本 | 风险 |
|------|--------|------|------|
| 微信网页版 + OpenCLI | 中（需扫码登录，不稳定） | 中 | 封号风险高 |
| 微信PC客户端 + 截图OCR | 低（成本高、准确率有限） | 高 | 人工介入多 |
| 第三方聚合API（如新榜/西瓜数据） | 高（付费服务） | 中 | 依赖第三方稳定性 |
| 公众号RSS转换服务 | 中（部分公众号有RSS） | 低 | 覆盖不全 |

**建议**：微信生态初期仅通过微信公众号RSS转换服务覆盖P0级公众号，后续评估是否需要更深度接入。

---

## 9. 待继续深入的方向

1. **KOL清单的初始种子数据获取** — 如何高效构建初始KOL清单？是否可以从Twitter List导入、从学术引用网络挖掘、从新闻引用统计中提取？
2. **Session Pool的容错与灾备** — Chrome Profile损坏或被封号时的快速切换机制
3. **跨平台KOL身份关联算法** — 如何自动识别同一人在Twitter/Facebook/LinkedIn上的不同账号？
4. **中文社交媒体获取的合规边界** — 微博/微信/抖音的自动化获取在法律上的边界
5. **KOL Registry的Obsidian可视化** — 如何将KOL清单在Obsidian中展示为可交互的知识图谱
6. **全量KOL追踪的伦理边界** — 在GDPR框架下对意大利公民的大规模社媒追踪是否合规
7. **双向舆情联动的时间差建模** — 中意舆论场对同一事件的响应时间差如何量化和利用
