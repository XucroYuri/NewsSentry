# News Classification And Clustering Design

> 日期：2026-05-29
> 状态：设计稿，等待实施计划
> 适用范围：公开新闻门户、后台目标工作台、采集过滤研判链路中的分类与聚类能力

## 背景

当前公开新闻门户已经具备频道化浏览能力，但频道与后端分类口径仍处在临时适配状态。实际运行数据中，Italy feed 的前 100 条新闻出现了明显症状：

- `null` 与 `uncategorized` 占比较高，分类覆盖不足。
- 后端运行配置主要输出 `politics`、`economics`、`security`、`international`、`culture_society`、`environment_energy` 等旧口径。
- 文档规范 `docs/news-classification-framework.md` 已定义 12 类 L0，但运行配置 `config/classification/rules-v1.yaml` 仍是 6 类旧模型。
- 前端频道面向读者，使用“精选、政策、产业、技术、风险、中国相关”等阅读入口，不应直接等同于后端 taxonomy。
- 多源重复报道、同一事件连续更新、同一议题趋势目前没有清晰的 `cluster_id/story_id` 生成和展示闭环。

因此下一阶段目标不是继续堆叠前端关键词，而是建立三层清晰模型：

1. 分类 Taxonomy：新闻本体属于什么领域与子议题。
2. 聚类 Cluster：多条新闻是否属于同一事实、故事线或趋势。
3. 频道 Channel：读者如何高效浏览和筛选。

## 目标

- 将运行时分类口径收敛到规范文档中的 12 类 L0。
- 降低 `null` 与 `uncategorized` 事件比例，使公开频道不依赖大量标题兜底。
- 建立可解释、可测试、可回溯的轻量聚类机制。
- 让公开门户展示“频道 + 子主题 + 故事线”，帮助读者快速理解新闻结构。
- 保持已有旧数据与旧链接兼容，不强制重写历史事件。
- 保留人工审核与反馈入口，使分类和聚类结果可在后台被纠正。

## 非目标

- 本阶段不引入完整向量数据库。
- 本阶段不做全自动对外发布。
- 本阶段不重构完整角色权限系统。
- 本阶段不要求一次性重算全部历史数据。
- 本阶段不把前端频道数量扩展到几十个固定 tab。

## 核心模型

### 1. Taxonomy 分类层

分类结果继续写入 `metadata.classification`，遵守 `docs/contracts-canonical.md §9` 与 ADR-0009，不新增竞争字段。

目标 L0 采用 `docs/news-classification-framework.md` 的 12 类：

- `politics`：政治、选举、议会、政策、司法改革、移民政策。
- `economy`：宏观、财政、贸易、能源、企业、就业、金融市场。
- `society`：民生、教育、福利、人口、移民生活、劳资权益。
- `tech`：AI、科研、数字监管、半导体、网络安全、科技产业。
- `culture`：艺术、媒体、宗教、遗产、非竞技文化事件。
- `sports`：竞技体育、赛事、俱乐部动态。
- `disaster`：自然灾害、工业事故、基础设施失效。
- `public-safety`：恐怖主义、组织犯罪、执法、重大安全事件。
- `health`：公共卫生、医疗政策、药品、疫情。
- `environment`：气候、能源转型、污染、生物多样性。
- `international-relations`：外交、战争冲突、制裁、多边关系、北约与欧盟外部关系。
- `china-related`：中意关系、中国企业、涉华政策、华人社区、涉华舆论。

兼容规则：

- 旧 `economics` 视为 `economy`。
- 旧 `security` 视为 `public-safety`，若标题或标签包含战争、制裁、北约、乌克兰、伊朗等国际冲突信号，则优先映射到 `international-relations`。
- 旧 `international` 视为 `international-relations`。
- 旧 `culture_society` 通过 L1 或关键词拆分到 `society`、`culture`、`health`、`sports`。
- 旧 `environment_energy` 视为 `environment`，同时可在前端频道进入“经济产业”或“环境能源”子筛选。

L1 子主题保持每个 L0 6 至 10 个可解释主题。Italy 第一阶段优先补齐这些高价值 L1：

- politics：`election`、`coalition`、`cabinet`、`parliament`、`eu-affairs`、`migration-policy`、`justice-reform`
- economy：`fiscal-policy`、`trade`、`energy`、`labor-market`、`financial-markets`、`corporate`、`infrastructure`
- international-relations：`us-italy`、`china-eu`、`russia-ukraine`、`nato`、`sanctions`、`africa-med`
- china-related：`china-italy-bilateral`、`bri-italy`、`chinese-investment`、`china-eu-policy`、`chinese-community`
- tech：`ai`、`semiconductor`、`digital-policy`、`cybersecurity`、`research`、`tech-industry`
- public-safety：`organized-crime`、`terrorism`、`policing`、`judicial-case`、`public-order`
- environment：`climate`、`energy-transition`、`pollution`、`extreme-weather`、`biodiversity`

### 2. Cluster 聚类层

聚类不替代分类。分类回答“是什么”，聚类回答“这些新闻之间是什么关系”。

第一版采用轻量规则聚类，写入现有或预留字段：

```yaml
cluster_id: "cluster-italy-20260529-..."
story_id: "story-italy-russia-ukraine-..."
metadata:
  clustering:
    cluster_type: "same_event" | "storyline" | "topic_trend" | "risk_signal"
    confidence: 0-100
    reason: string
    matched_by:
      - "title_similarity"
      - "entity_overlap"
      - "time_window"
      - "source_diversity"
```

四类聚类含义：

- `same_event`：不同来源报道同一事实，例如同一条 ANSA、RaiNews、Repubblica 都在报道同一事件。
- `storyline`：同一事件持续发展，例如“乌克兰战争中的意大利相关人员”“伊朗核问题”。
- `topic_trend`：同一议题多日持续出现，例如“能源价格”“移民政策”“财政预算”。
- `risk_signal`：具有升级、外溢或预警意义的事件簇，例如制裁、军事冲突、公共安全、市场冲击。

第一版聚类算法：

- 时间窗：默认同 target、72 小时内；突发风险可缩短到 24 小时。
- 标题相似度：归一化标题 token 的 Jaccard 或余弦近似，不引入外部向量库。
- 实体重合：使用已有实体抽取或标题中的国家、机构、人名、地名。
- 分类约束：L0/L1 至少部分相同；`china-related` 可跨 L0 聚合。
- 来源多样性：同一来源重复不提升 cluster 可信度，不同来源重复提升可信度。
- 去重保护：完全相同标题或高度相似标题优先进入同一 `same_event`，避免公开列表重复刷屏。

### 3. Channel 频道层

公开频道是读者入口，不是后端分类枚举的镜像。频道数量保持克制，第一屏保留可扫描性。

建议公开频道：

- 全部：全部 active target 新闻。
- 精选：高分、建议 review/publish、或多源聚类高可信事件。
- 政策：`politics` 与政策相关 `society` 子主题。
- 经济产业：`economy`、能源产业、企业、贸易、基础设施。
- 国际风险：`international-relations`、`public-safety`、`disaster` 中的高风险事件。
- 科技：`tech` 与科技产业、数字政策、网络安全。
- 涉华：`china-related` 或 `china_relevance >= 50`，可跨所有 L0。

频道内提供二级筛选，不增加顶部 tab 负担：

- 子主题：L1 topic。
- 故事线：`story_id`。
- 来源：source。
- 时间：今天、昨天、7 天。
- 地区或国家轴：Italy region、EU/domestic scope、china-italy relation。

文章卡片展示顺序：

1. 来源、时间、分数。
2. 标题。
3. 领域标签：L0 中文名。
4. 子主题标签：最多 2 个 L1。
5. 故事线标签：若存在 `story_id`，展示“同一事件 N 来源”或“故事线更新”。
6. 关键原因：AI reason 或规则解释摘要。

## 后台管理能力

后台目标工作台需要让非技术人员能干预分类与聚类：

- 在 target 规则页查看 L0/L1 命中分布、`uncategorized` 样本、低置信分类样本。
- 支持为 target 追加关键词、禁用误命中关键词、调整前端频道映射。
- 审核事件详情时允许“纠正分类”“加入故事线”“拆出故事线”“标记重复”。
- 反馈记录进入规则优化候选，不直接静默改规则。
- 聚类详情页展示来源列表、时间线、共同实体、系统聚类原因。

## 数据迁移与兼容

本阶段采用渐进迁移：

- 新采集事件优先使用 12 类 L0。
- 旧事件读取时通过 alias 映射到公开频道，不强制改写原始 Markdown。
- 后台提供“重建索引/重跑分类预览”能力，先预览影响再写入。
- API 保留旧字段读取能力，新增 `metadata.clustering` 不破坏旧消费者。
- `cluster_id/story_id` 可为空，前端必须优雅降级。

## 错误处理

- 分类置信度过低时写入 `uncategorized`，同时保留 `classification.candidates` 供后台诊断。
- 聚类置信度低于阈值时不自动合并，只显示“可能相关”。
- 频道无内容时隐藏普通频道；直达空频道时显示可解释空态。
- 后台规则保存前执行预检，展示命中样本、误伤风险和影响数量。

## 测试策略

单元测试：

- 旧 L0 alias 到新 L0 的映射。
- 12 类 L0 与核心 L1 关键词命中。
- `uncategorized` 低置信逻辑。
- `china-related` 跨 L0 命中。
- `same_event` 聚类对重复标题、多来源标题相似事件的归并。
- `storyline` 聚类对同实体、同议题、跨日更新的关联。

JS 测试：

- 公开频道从新 L0/L1 与旧 alias 同时得出正确计数。
- 空频道隐藏，直达空频道保留当前频道并显示空态。
- 故事线标签、L0/L1 标签在缺失字段时不报错。

浏览器验收：

- Italy 公开门户顶部频道不出现大面积空频道。
- 频道内二级筛选可用，移动端无横向溢出。
- 同一事件多源报道能折叠或明确标注。
- 后台能看到 `uncategorized` 样本和分类分布。

## 实施阶段

### 阶段 1：口径收敛

- 更新运行配置到 12 类 L0。
- 增加 alias 映射，不破坏旧事件。
- 补齐 Italy 高价值 L1 关键词。
- 增加分类分布诊断测试。

### 阶段 2：公开频道升级

- 从硬编码频道词表升级为 `channel -> taxonomy mapping` 配置。
- 公开频道显示数量、隐藏空频道、频道内增加二级筛选。
- 文章卡片展示 L0/L1 与故事线占位。

### 阶段 3：轻量聚类

- 新增同事件聚类与重复折叠。
- 新增故事线 ID 生成与时间线展示。
- 在后台详情页提供聚类原因和人工纠正入口。

### 阶段 4：反馈闭环

- 将人工纠正分类、合并故事线、拆分故事线写入反馈记录。
- 规则优化页展示候选规则与影响样本。
- 支持预检后应用规则调整。

## 成功标准

- 新采集 Italy 事件中 `null + uncategorized` 占比显著下降。
- 公开频道至少能稳定产生“政策、经济产业、国际风险、涉华”四类非空入口。
- 技术频道在没有内容时隐藏，有内容时由 `tech` L0/L1 驱动出现。
- 同一新闻多源重复在公开阅读体验中不再连续刷屏。
- 后台能解释分类与聚类结果，并支持人工纠正。
