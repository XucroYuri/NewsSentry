# News Sentry 全球情报平台商业与架构方向设计

> 日期：2026-05-30
> 状态：长期方向设计稿
> 适用范围：产品定位、商业模型、云端架构、本地客户端、半中心化采集节点网络

## 1. 战略定位

News Sentry 的长期定位应从“单机新闻监控工具”演进为：

**全球开源新闻与社媒情报研究平台。**

平台优先服务专业新闻、研究、分析与舆情风险用户，同时兼容企业风险监控场景。第一阶段不追求面向大众用户的泛信息消费产品，也不急于做通用 SaaS 仪表盘，而是优先把专业研究所需的事实可信度、跨语言去重、事件链、人工反馈、引用溯源和简报输出做扎实。

推荐优先级：

1. **A 优先**：专业新闻/研究团队、研究员、编辑、分析师。
2. **兼容 B**：企业舆情、地缘风险、产业风险、政策风险监控。
3. 暂不优先 C：个人泛信息消费。
4. 不抽象成空泛 D：通用平台先行。

这个方向的核心判断是：专业研究工作台会逼出最重要的底层能力；企业舆情与风险监控可以在这些能力之上增加权限、报表、客户配置、审计和告警包装。

## 2. 总体路线：B 优先，A 前置约束

路线不应是单纯“先做研究工作台”或“先做全球事实池”，而应采用：

**B 优先，A 前置约束。**

这里的含义是：

- **B：专业研究工作台与运行可靠性优先**
  先把少量国家、地区、主题的专业研究闭环做成可信产品，让系统能长期运行、可诊断、可审核、可持续输出。

- **A：Canonical Global Fact Pool 作为前置数据约束**
  即使第一阶段不立即建设完整云端集群，也必须从现在开始按未来全球事实池的数据契约写入、归并、引用和治理。

这样可以避免后续出现数据孤岛：公开门户、研究工作台、本地客户端、企业告警各自维护一套局部事实。

## 3. 阶段规划

### Phase 0：可靠性止血与可观测性

目标是让当前系统不再静默漂移、不再重复膨胀、不再因为运行进程和源码版本不一致造成误判。

重点能力：

- run manifest 与 batch/delta 语义。
- 各阶段幂等处理。
- alert history 与 event links 去重和边界控制。
- 数据膨胀 dry-run 诊断与安全清理。
- runtime version、server_started_at、build manifest、route count 可见。
- source inventory 成为 target/source 管理真相源。
- taxonomy、language、source lifecycle 进入统一契约。

这一步不是商业化功能，但它是后续商业模型可信运行的基础。

### Phase 1：Shadow Canonical Data Spine

目标是在现有本地文件协议与 SQLite 架构内，先落地未来全球事实池的数据主干。

第一阶段不急于直接切换到 Postgres、搜索引擎、对象存储和分布式任务系统。推荐采用“影子主干”策略：

- 保留当前 `NewsEvent`、Markdown 文件、SQLite `event_index` 的运行方式。
- 新增 canonical schema 与投影层。
- 让现有页面、分析、研究工作台逐步读取 canonical 投影。
- 验证数据契约稳定后，再迁移到云端数据栈。

影子主干应至少包含：

- `canonical_event`
- `event_mention`
- `event_relation`
- `entity`
- `taxonomy_assignment`
- `research_artifact`
- `source_inventory`

### Phase 2：Professional Research Workflow

目标是让研究员、编辑、分析师围绕 canonical event 完成真实工作。

核心工作流：

- 事件追踪与事件链。
- 证据引用与来源溯源。
- 人工标注、合并、拆分、纠错。
- 审核队列与反馈闭环。
- 专题简报、日报、风险摘要输出。
- 研究笔记和私有工作区。

关键原则：研究动作属于 workflow/artifact，不应污染事实对象本身。

### Phase 3：Global Fact Pool + Local Lightweight Client

目标是在已验证的 canonical 主干上扩展国家、地区、语言、主题和社媒覆盖。

云端负责：

- 全球采集与任务调度。
- canonical event store。
- 跨语言去重和聚类。
- 事件链、趋势、实体、风险评分。
- 订阅、告警、日报、研究包分发。

本地客户端负责：

- 用户关注范围选择。
- 云端 subset 同步。
- 本地阅读、缓存、标注、笔记、收藏、导出。
- 可选私有源采集与有限公共信源贡献。

## 4. Canonical Data Spine 核心口径

### 4.1 `canonical_event`

`canonical_event` 表示现实世界中的同一个新闻事实、事件或进展，不等于某一家媒体的一篇报道。

示例：

- “意大利政府批准某项能源补贴政策”
- “某国大选结果公布”
- “某企业宣布在欧洲建设新芯片工厂”

多家媒体、多种语言、多种平台对同一事实的报道，应归并到同一个 `canonical_event`。

### 4.2 `event_mention`

`event_mention` 表示某个信源对某个 canonical event 的一次报道或提及。

它承载：

- source id
- URL
- 标题
- 原文摘要
- 发布时间
- 采集时间
- 语言
- source credibility
- 引用片段
- 采集节点 provenance

一篇报道是 mention，不是事实本身。

### 4.3 `event_relation`

`event_relation` 表示 canonical events 之间的关系。

第一版关系类型：

- `duplicate`
- `followup`
- `related`
- `contradicts`
- `background`

关系必须有强度、证据和来源，不能只保存一个裸关系。

### 4.4 `entity`

`entity` 表示事实中涉及的人物、机构、国家、地区、公司、项目、政策、产品或组织。

实体需要支持：

- canonical name
- aliases
- multilingual aliases
- entity type
- source evidence
- mention count
- relation to canonical events

### 4.5 `taxonomy_assignment`

分类不应继续由前端兼容映射遮挡。分类应成为 canonical 数据契约的一部分。

第一版需要覆盖：

- L0-L3 canonical taxonomy
- topic labels
- risk categories
- industry categories
- geo scope
- confidence
- assignment source：rules / AI / human / migration

### 4.6 `research_artifact`

研究工作流产生的内容不应污染事实层。

`research_artifact` 包括：

- 人工标注
- 研判笔记
- 合并/拆分决策
- 审核状态
- 简报段落
- 引用证据
- 用户私有收藏
- 本地客户端私有笔记

## 5. Mention 到 Canonical Event 的归并策略

第一阶段采用：

**混合策略 + 严格置信门槛。**

归并信号分三类。

### 5.1 确定性信号

- URL canonicalization
- normalized title hash
- source ref
- published_at time window
- duplicate URL
- feed item GUID

### 5.2 语义信号

- multilingual title similarity
- summary similarity
- entity overlap
- geo overlap
- time proximity
- action/event verb similarity
- taxonomy similarity

### 5.3 人工信号

- 人工确认合并
- 人工拆分
- 误合并反馈
- 事件链修正
- source credibility 调整

### 5.4 置信门槛

第一版采用保守策略：

- 高置信：自动归并到已有 `canonical_event`
- 中置信：进入人工审核队列
- 低置信：创建新的 `canonical_event`

专业研究平台中，**误合并比漏合并更危险**。第一版宁可碎片化一些，也不能把不同事实静默合并。

## 6. 本地轻客户端边界

本地客户端采用 A+B 模式。

密钥治理需要与本地客户端、云端平台和半中心化采集节点共同设计。AI Provider Key、News Sentry 访问 Key、Collector Node Credential 必须分离管理；长期方案见 `docs/superpowers/specs/2026-05-30-ai-provider-credential-governance-design.md`。

### 6.1 A：轻同步客户端

默认模式是轻同步客户端。

能力范围：

- 选择关注范围：国家、地区、主题、实体、语言、信源。
- 同步云端 canonical event subset。
- 本地缓存与离线阅读。
- 本地标注、笔记、收藏。
- 私有规则和告警阈值。
- 导出日报、简报或研究包。
- 可选择性回传反馈。

默认不承担全量采集、全量研判和全局事实生产。

### 6.2 B：可选采集贡献模式

本地客户端可以提供可选 Collector Node 模式。

这个模式不是任意 P2P 代理，也不是匿名爬虫网络。它应被定义为：

**受控、可审计、可退出的公共信源采集贡献节点。**

节点只执行：

- 云端签名任务。
- allowlist 中的公开信源。
- 用户明确同意的采集范围。
- 合法可访问的公开新闻、政策、社媒、舆情信源。

节点不得执行：

- 任意代理流量。
- 绕过认证、付费墙、访问控制或安全机制的任务。
- 隐藏身份或规避审计的采集任务。
- 与用户授权范围无关的私有数据上传。

## 7. 半中心化记者站网络模型

长期可以把本地采集贡献模型设计成类似大型新闻集团或通讯社的全球记者站网络。

核心叙事：

**News Sentry Cloud 是总社与全球事实池，本地客户端可以成为所在国家/地区的专业采集记者站。**

这个模型不是完全去中心化，而是半中心化：

- 云端负责任务、契约、事实池和质量治理。
- 节点负责所在地区的公开信源采集和地域上下文补充。
- 专业用户通过订阅获得高价值信息服务。
- 专业用户也可以在受控条件下贡献信源覆盖。

### 7.1 节点价值

分布在不同国家和地区的节点可以提供：

- 当地网络环境下可见的公开新闻源。
- 当地语言、地区、社媒生态的信源覆盖。
- 云端集中采集难以稳定触达的公开信息。
- 更低的集中式采集运维成本。
- 更好的地域时效性。

### 7.2 准入模型

第一阶段采用：

**邀请制专业节点。**

面向对象：

- 专业订阅用户。
- 研究员。
- 记者。
- 编辑。
- 风险分析师。
- 机构合作方。

节点启用前需要：

- 账号实名或机构认证。
- 节点地区声明。
- 可执行任务范围确认。
- 用户授权确认。
- 节点版本校验。
- 采集任务协议确认。

### 7.3 节点治理

节点必须具备：

- signed task
- source allowlist
- quota
- rate limit
- provenance
- audit log
- node reputation
- data quality score
- opt-out
- remote disable
- abuse report

所有节点贡献数据进入 canonical pipeline 前，必须经过去重、质量检查、source validation 和异常检测。

## 8. 商业模型与增长飞轮

### 8.1 商业定位

News Sentry 的商业模式应优先面向专业订阅服务。

目标客户：

- 新闻机构。
- 研究机构。
- 咨询公司。
- 企业战略、政策、风险团队。
- 投资、产业、供应链分析团队。
- NGO、国际组织、智库。
- 独立研究员和专业记者。

### 8.2 价值主张

核心价值不是“更多新闻”，而是：

- 更早发现全球新闻与社媒变化。
- 更可靠地去重、归并和追踪事件。
- 更完整地跨语言、跨区域理解同一事实。
- 更清晰地输出证据链、事件链和趋势。
- 更低成本地维持全球公开信源覆盖。
- 更适合专业研究和风险判断的工作流。

### 8.3 增长飞轮

推荐增长飞轮：

1. 专业用户订阅。
2. 专业用户选择关注范围并使用本地客户端。
3. 部分专业用户开启受控 Collector Node。
4. 所在地区公开信源覆盖增强。
5. 云端 canonical fact pool 更完整、更及时。
6. 平台研究价值提升。
7. 吸引更多专业用户与机构订阅。
8. 更多地区节点加入，覆盖继续增强。

这个飞轮的关键不是用户规模，而是节点质量、地域覆盖和信源可信度。

### 8.4 商业分层

第一版可规划以下层级，但不要求立即实现：

- **Research Reader**：订阅关注范围，阅读、搜索、告警、日报。
- **Research Analyst**：标注、事件链、专题、引用、报告导出。
- **Bureau Contributor**：通过审核后运行 Collector Node，贡献信源覆盖。
- **Institution Team**：团队协作、权限、审计、共享工作区。
- **Enterprise Risk**：定制分类、告警策略、API、报表和 SLA。

### 8.5 节点激励

节点激励可以来自：

- 订阅折扣。
- 数据贡献积分。
- 区域贡献者声誉。
- 合作机构权益。
- 专业数据访问权限提升。

不建议第一阶段引入复杂代币、开放市场或自动结算机制。它们会显著增加监管、滥用和产品复杂度。

## 9. 风险与边界

### 9.1 技术风险

- 误合并导致事实污染。
- 节点贡献数据质量不稳定。
- 数据量增长导致索引和存储压力。
- 多语言实体对齐错误。
- 运行版本漂移导致验证失真。

缓解策略：

- 高置信自动合并，模糊样本人工审核。
- 所有节点数据保留 provenance。
- 限额、幂等、批次 manifest。
- canonical taxonomy 与 entity schema。
- 运行版本与 route version 可见。

### 9.2 运营风险

- 节点准入过宽导致污染。
- 专业用户贡献意愿不足。
- 各国公开信源访问条件不同。
- 误把采集贡献理解为代理服务。

缓解策略：

- 邀请制专业节点。
- allowlist source registry。
- 明确用户授权和退出机制。
- 商业叙事强调记者站模型，不强调匿名 P2P。

### 9.3 合规与安全边界

系统只能采集公开、合法可访问的新闻、政策、社媒和舆情信源。

不得设计：

- 绕过认证。
- 绕过付费墙。
- 绕过访问控制。
- 隐藏身份规避审计。
- 任意代理。
- 未授权采集私有数据。
- 上传用户本地私有笔记和文件，除非用户明确选择同步。

这个边界是长期商业化可信度的一部分。

## 10. 当前项目到长期平台的迁移原则

从当前 News Sentry 到长期平台，应遵循以下原则：

1. **先可靠，再扩张。**
   在 run manifest、幂等、数据清理、版本可见、source inventory 稳定前，不做大规模全球扩张。

2. **先影子主干，再云端迁移。**
   在现有 SQLite/Markdown/file protocol 内验证 canonical schema，再迁移到云端数据栈。

3. **事实层与研究层分离。**
   canonical event 和 mention 是事实层；人工判断、简报、笔记是 artifact 层。

4. **节点贡献必须可审计。**
   每条节点贡献数据必须带 task id、node id、source ref、采集时间和版本。

5. **第一阶段控制规模。**
   邀请制专业节点优先于开放注册节点。

6. **商业模型服务架构边界。**
   专业订阅、记者站贡献、全球事实池和研究工作台必须形成同一个飞轮，而不是四套独立产品。

## 11. 后续文档拆分建议

这份文档是长期方向设计，不直接作为实现计划。后续应拆成独立 spec / plan：

1. **Shadow Canonical Data Spine Spec**
   定义 `canonical_event`、`event_mention`、`event_relation`、投影和迁移。

2. **Professional Research Workflow Spec**
   定义审核、标注、事件链、引用、简报、日报输出。

3. **Local Lightweight Client Spec**
   定义 watch scope、sync package、offline cache、private annotations。

4. **Bureau Collector Node Spec**
   定义邀请制节点、signed tasks、allowlist、quota、provenance、audit。

5. **Cloud Scale Architecture Spec**
   定义 Postgres/Search/Object Store/Queue/Graph/Vector 的分阶段迁移。

## 12. 已确认决策

- 长期定位：全球开源新闻与社媒情报研究平台。
- 用户优先级：A 专业新闻/研究团队优先，兼容 B 企业舆情与风险监控。
- 路线：B1 运行可靠性 + B3 数据契约先行，B2 研究工作流紧随。
- Canonical 第一阶段策略：影子主干，先在现有本地架构内落地。
- `canonical_event` 口径：现实世界事实/进展，不是单篇报道。
- mention 口径：某信源对 canonical event 的一次报道或提及。
- 归并策略：混合策略 + 严格置信门槛。
- 本地客户端：轻同步客户端 + 可选采集贡献模式。
- 去中心化方向：半中心化公共采集节点网络。
- 商业参考模型：大型新闻集团/通讯社全球记者站。
- 节点准入：邀请制专业节点。
- 商业飞轮：专业订阅 → 本地节点贡献 → 全球覆盖增强 → 研究价值提升 → 更多专业订阅。
