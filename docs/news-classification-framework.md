# News Sentry — 新闻分类框架

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **规范文档** — 本文档是 `metadata.classification` 字段契约和四层 taxonomy 的权威来源
> 相关 ADR: [ADR-0009](./adr/0009-four-layer-classification-framework.md)（四层分类框架）
> 字段契约: [`docs/contracts-canonical.md §9`](./contracts-canonical.md)
> 术语互锁: [`docs/it-zh-glossary.md`](./it-zh-glossary.md)

---

## §0. 设计原则

1. **正交分层**：L0–L3 四层各自独立，L2 实体角色和 L3 动作状态可跨 L0/L1 复用，无需为每个组合创建独立分类。
2. **Italy-first，框架中立**：意大利子分类轴在专属 §4 中定义，L0–L3 taxonomy 保持通用，Phase 7 新增目标国时只需新增子轴文件。
3. **与评分解耦**：分类是语义标注，`news_value_score` 和 `china_relevance` 是评分；二者通过 §5 的映射示例关联，但保持字段独立。
4. **可扩展**：L1 子主题列表允许追加，不允许删除已有条目（只能废弃并注明替代项）。

---

## §1. L0 Domain — 顶层领域（12 类）

顶层领域使用固定枚举，保持稳定。修改 L0 枚举需新建 ADR。

| `l0` 值 | 中文名称 | 涵盖范围简述 |
|---|---|---|
| `politics` | 政治 | 选举、组阁、议会、执政党、政策立法、外交、移民 |
| `economy` | 经济 | 宏观经济、财政、能源、贸易、企业、就业、金融市场 |
| `society` | 社会 | 民权、劳资、福利、教育、犯罪、人口、移民生活 |
| `tech` | 科技 | 科研、创新、数字政策、AI监管、半导体、宇航 |
| `culture` | 文化 | 艺术、媒体、宗教、遗产、体育（非竞技类） |
| `sports` | 体育 | 足球、网球、赛车、奥运竞技 |
| `disaster` | 灾害 | 地震、洪水、山火、工业事故、基础设施失效 |
| `public-safety` | 公共安全 | 恐怖主义、组织犯罪、执法、网络安全 |
| `health` | 健康 | 公共卫生、疫情、医疗政策、药品 |
| `environment` | 环境 | 气候变化、能源转型、污染、生物多样性 |
| `international-relations` | 国际关系 | 多边关系、制裁、外交危机、战争与冲突 |
| `china-related` | 涉华 | 中意关系、一带一路、中国企业在意大利、涉华政策 |

**约束：**
- `l0` 必须且只能取上表 12 个值之一。
- 若一条新闻横跨多个 L0 域，`l1[]` 数组可填入多个子主题，`l0` 选择主要域。
- `china-related` 是专项标记，可与其他 L0 并用（同一事件可同时是 `economy` 和 `china-related`）。

---

## §2. L1 Topic — 子主题（每域 6–10 项）

`l1` 是数组字段（`l1: string[]`），一条新闻可以同时属于多个子主题。

### politics（政治）
| `l1` 值 | 示例场景 |
|---|---|
| `election` | 大选、地方选举、补选 |
| `coalition` | 执政联盟谈判与稳定性 |
| `cabinet` | 内阁组建、部长任免、政府危机 |
| `parliament` | 议会辩论、法案审议、信任投票 |
| `referendum` | 全国或地区性公投 |
| `scandal` | 政治腐败、欺诈、丑闻调查 |
| `foreign-policy` | 双边外交、大使级事件、国际峰会 |
| `migration-policy` | 移民法律、难民处置、遣返协议 |
| `eu-affairs` | 欧盟条约、布鲁塞尔谈判、欧洲议会事务 |
| `justice-reform` | 司法改革、检察官制度、法院判决 |

### economy（经济）
| `l1` 值 | 示例场景 |
|---|---|
| `fiscal-policy` | 预算案、税改、债务管理 |
| `trade` | 进出口数据、贸易协议、关税摩擦 |
| `energy` | 电价、能源转型、天然气、核电 |
| `labor-market` | 失业率、罢工、劳动合同改革 |
| `financial-markets` | 股市、债市、利率、汇率 |
| `corporate` | 大企业动态、并购、国企改革 |
| `eu-economy` | 欧元区政策、欧央行、结构性基金 |
| `agri-food` | 农业补贴、食品安全、渔业政策 |
| `tech-industry` | 科技公司、初创、数字经济 |
| `infrastructure` | 基础设施投资、PPP、铁路 |

### society（社会）
| `l1` 值 | 示例场景 |
|---|---|
| `civil-rights` | 反歧视、LGBTQ+、残障权利 |
| `welfare` | 社会保障、医疗保险、养老金 |
| `education` | 高校、中小学、职业培训 |
| `crime` | 刑事案件、黑手党、诈骗 |
| `demographics` | 人口老龄化、出生率、移民人口 |
| `religion` | 梵蒂冈关系、宗教政策 |
| `labor-rights` | 工会、工伤、薪酬争议 |
| `immigration-society` | 移民融合、难民社区、排外事件 |

### international-relations（国际关系）
| `l1` 值 | 示例场景 |
|---|---|
| `us-italy` | 跨大西洋关系、北约事务 |
| `china-eu` | 中欧关系、欧盟对华政策 |
| `russia-ukraine` | 制裁执行、难民接收、军事援助 |
| `nato` | 北约峰会、国防预算、成员动态 |
| `un-multilateral` | 联合国议题、G7/G20 意大利立场 |
| `africa-med` | 地中海南岸、移民路线国 |
| `sanctions` | 制裁措施、出口管制 |

### china-related（涉华）
| `l1` 值 | 示例场景 |
|---|---|
| `china-italy-bilateral` | 中意双边峰会、领事事务 |
| `bri-italy` | 一带一路意大利退出后续 |
| `chinese-investment` | 中资在意收购、审查 |
| `china-eu-policy` | 意大利对欧盟对华立场的影响 |
| `disinformation` | 涉华信息操控、媒体关注 |
| `chinese-community` | 意大利华人社区动态 |

### tech / environment / health / disaster / public-safety / sports / culture

这些域的 L1 子主题在实现阶段按需定义，首次出现新子主题时追加到本文档。

---

## §3. L2 Entity Roles — 实体角色类型

`l2` 是数组字段（`l2: string[]`），标注新闻中出现的关键实体类型，与 [`docs/it-zh-glossary.md`](./it-zh-glossary.md) 中的命名实体互锁。

| `l2` 值 | 说明 | 示例 |
|---|---|---|
| `actor` | 自然人行为者（政客、官员、企业家） | Giorgia Meloni、Mario Draghi |
| `institution` | 机构/组织（政府部门、国际组织、企业） | Parlamento italiano、ANSA、Banca d'Italia |
| `location` | 地理位置（国家、大区、城市、地标） | Roma、Lombardia、Bruxelles |
| `instrument` | 工具/手段（法律文本、条约、报告） | Decreto Lavoro、PNRR、NATO Treaty |
| `event-trigger` | 触发性事件（选举、峰会、判决日） | elezioni regionali、G7 Summit |

---

## §4. L3 Action / Status — 动作与状态

`l3` 是单值字段（`l3: string`），描述新闻事件的核心动态属性。

| `l3` 值 | 含义 | 示例场景 |
|---|---|---|
| `announced` | 官方宣布计划/政策但未执行 | 政府宣布新预算方案 |
| `proposed` | 提案/草案阶段 | 议员提交法案 |
| `passed` | 通过/批准 | 参议院通过法律 |
| `rejected` | 否决/拒绝 | 欧盟否决意大利申请 |
| `implemented` | 已执行/已生效 | 新税法正式实施 |
| `suspended` | 暂停/中止 | 措施因诉讼被法院暂停 |
| `leaked` | 泄露/非官方披露 | 机密文件被媒体披露 |
| `under-investigation` | 调查中 | 检察官就腐败案立案 |
| `scheduled` | 已定日期/即将发生 | 峰会定于下周举行 |
| `cancelled` | 取消 | 访问因外交争端取消 |
| `ongoing` | 持续进行中 | 劳资谈判持续 |
| `concluded` | 已结束/已达成 | 谈判圆满结束 |

---

## §5. Italy-specific 子分类轴

Italy 子轴写入 `metadata.classification.country_axes[]`，不改动 L0–L3 枚举。

### 5.1 地区轴（`region`）— 意大利 20 大区（ISO 3166-2:IT）

| 代码 | 大区名称 |
|---|---|
| `IT-65` | Abruzzo |
| `IT-77` | Basilicata |
| `IT-78` | Calabria |
| `IT-72` | Campania |
| `IT-45` | Emilia-Romagna |
| `IT-36` | Friuli-Venezia Giulia |
| `IT-62` | Lazio |
| `IT-42` | Liguria |
| `IT-25` | Lombardia |
| `IT-57` | Marche |
| `IT-67` | Molise |
| `IT-21` | Piemonte |
| `IT-75` | Puglia |
| `IT-88` | Sardegna |
| `IT-82` | Sicilia |
| `IT-52` | Toscana |
| `IT-32` | Trentino-Alto Adige |
| `IT-55` | Umbria |
| `IT-23` | Valle d'Aosta |
| `IT-34` | Veneto |

### 5.2 政治联盟轴（`coalition`）

| 值 | 阵营 |
|---|---|
| `centro-destra` | 中右联盟：Fratelli d'Italia、Lega、Forza Italia |
| `centro-sinistra` | 中左联盟：Partito Democratico、Alleanza Verdi e Sinistra |
| `m5s` | 五星运动（独立） |
| `terzo-polo` | 第三极：Azione、Italia Viva |
| `independent` | 独立/无党派 |

### 5.3 欧盟 vs 国内轴（`scope`）

| 值 | 含义 |
|---|---|
| `eu-domestic` | 欧盟政策在意大利国内的执行与反应 |
| `eu-only` | 发生在欧盟层面、与意大利特定关联不强 |
| `domestic-only` | 纯意大利国内事务 |
| `bilateral` | 双边关系（中意、美意等） |

### 5.4 中意关系轴（`china-italy-rel`）

| 值 | 含义 |
|---|---|
| `bri-legacy` | 一带一路退出后遗留议题 |
| `investment-review` | 中资进入意大利的审查 |
| `diplomatic` | 外交事件（峰会、声明、争端） |
| `trade-friction` | 贸易摩擦（对华关税、出口管制） |
| `cultural-exchange` | 文化、教育、旅游领域 |

---

## §6. metadata.classification 完整 Schema

完整字段定义见 [`docs/contracts-canonical.md §9`](./contracts-canonical.md)。下为 YAML 示例：

```yaml
metadata:
  classification:
    l0: "politics"
    l1:
      - "election"
      - "coalition"
    l2:
      - "actor"
      - "institution"
    l3: "announced"
    country_axes:
      - axis: "region"
        value: "IT-62"
      - axis: "coalition"
        value: "centro-destra"
      - axis: "scope"
        value: "domestic-only"
    confidence: 82
    classifier_version: "rules-v1"
```

---

## §7. 评分映射示例

### 7.1 `news_value_score` 驱动因素

| 分类条件 | 加权建议 | 原因 |
|---|---|---|
| `l0 = "politics"` + `l1 includes "election"` | +15 | 选举直接影响政策走向 |
| `l0 = "disaster"` | +20（基础） | 紧急度高，时效性强 |
| `l0 = "economy"` + `l1 includes "fiscal-policy"` | +10 | 财政政策影响广泛 |
| `l3 = "announced"` | ×0.8（折扣） | 宣布 < 已通过，不确定性高 |
| `l3 = "passed"` | ×1.0（基准） | 已确认事实 |
| `l3 = "leaked"` | ×0.7（折扣） | 未经证实，风险高 |
| `country_axes.scope = "eu-domestic"` | +5 | 欧盟层面事件影响时效较长 |

### 7.2 `china_relevance` 驱动因素

| 分类条件 | 加权建议 | 原因 |
|---|---|---|
| `l0 = "china-related"` | ≥ 60（基础） | 直接涉华内容 |
| `l1 includes "bri-italy"` | +20 | 一带一路议题高度相关 |
| `l1 includes "chinese-investment"` | +15 | 中资动态直接相关 |
| `country_axes.china-italy-rel = "trade-friction"` | +20 | 贸易摩擦对中国经济影响显著 |
| `l0 = "international-relations"` + `l1 includes "china-eu"` | +15 | 中欧框架影响中意关系 |

### 7.3 计算示例

**示例：意大利总理宣布退出一带一路**
```yaml
l0: china-related
l1: [bri-italy, foreign-policy]
l3: announced
country_axes:
  - {axis: scope, value: bilateral}

# 评分估算
news_value_score: 85
china_relevance: 95
```

---

## §8. 分类器实现指南

### Phase 3：规则引擎分类器

- 维护 `config/classification-rules.yaml`，包含每个 L0/L1 的关键词列表（意大利语 + 英语）
- `confidence: null`（规则命中是确定性的）
- `classifier_version: "rules-v1"`

### Phase 5：LLM 分类器

- Route ID：`classify.primary`
- 输出 schema 必须包含 `l0`、`l1[]`、`l3`、`confidence`
- Fallback：LLM 失败时降级到规则引擎，`classifier_version: "rules-v1-fallback"`

### 分类结果存储

分类结果写入 `NewsEvent.metadata.classification`，不进 schema 顶层（ADR-0009）。
