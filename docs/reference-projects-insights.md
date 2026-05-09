# News Sentry — 参考项目价值提取

> 版本: v1.0 | 日期: 2026-05-09
> 状态: **研究参考文档** — 不可变历史摘要；新启发点直接追加，不修改已有行
> 相关文档: [外部集成策略](./external-integration-strategy.md) | [ADR-0008](./adr/0008-external-deps-install-not-vendor.md)

本文档对 8 个参考项目进行系统性价值提取，每条启发点明确指向 News Sentry 对应的 ADR、Skill 规格或规范段落。**悬空建议（没有落地指针的启发）不录入本文档。**

---

## 格式说明

每个项目使用统一四列表格：
- **能做什么**：该项目核心能力的客观描述
- **对 News Sentry 的具体启发**：News Sentry 可以从中借鉴的具体设计点
- **落地指针**：对应的 ADR、规格文档、开发计划段落或字段名
- **采纳状态**：`已落地`（本轮文档已体现）/ `Phase N 候选`（后续阶段考虑）/ `v1 舍弃`（不引入）

---

## P1 — OpenCLI

**项目：** [github.com/jackwener/OpenCLI](https://github.com/jackwener/OpenCLI) | Stars: 19.4k | 语言: TypeScript

**核心能力：** 把网站/Electron 应用转换为 CLI 接口，内置 100+ 适配器，零 LLM 成本，AI-native 运行时，多 Chrome profile 隔离。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| 统一 CLI 接口 | 把 Twitter/Reddit/HN/Google Scholar/gov-policy 等多平台的采集标准化为同一 `ToolManifest` 调用模式，避免为每个平台写独立采集器 | [ADR-0011](./adr/0011-opencli-baseline-toolmanifest.md)；[外部集成策略 §2.4](./external-integration-strategy.md) | 已落地 |
| 退出码约定（66/69/77） | 与 `ToolRunResult.error.type` 枚举对齐：66=`result_empty`，69=`browser_unavailable`，77=`auth_required` | [ADR-0003](./adr/0003-sandbox-write-roots-and-error-enum.md)；[contracts-canonical.md §7](./contracts-canonical.md) | 已落地 |
| Chrome profile 隔离 | `ToolManifest.permissions.browser.session_profile_required=true` 时通过环境变量路由 profile，Cookie 绝不写入 NewsEvent | [ADR-0008](./adr/0008-external-deps-install-not-vendor.md)；[外部集成策略 §2.3](./external-integration-strategy.md) | 已落地 |
| 零 LLM 成本采集 | 采集阶段（collect）不消耗 AI token；只在 filter/judge 阶段调用 provider，控制成本 | [development-plan.md §5 Phase 4](./development-plan.md)；[AIProvider与模型路由规格.md](./brainstorming/AIProvider与模型路由规格.md) | 已落地（Phase 4） |
| 本地工具包装能力 | `opencli external {name}` 可包装本地脚本为 CLI 工具，支持自定义 News Sentry 内部工具的 ToolManifest 注册 | [外部集成策略 §2.4](./external-integration-strategy.md) `opencli.external.custom` | Phase 4 候选 |

---

## P2 — opencli-admin

**项目：** [github.com/xjh1994/opencli-admin](https://github.com/xjh1994/opencli-admin) | 语言: TypeScript (React) + Python (FastAPI)

**核心能力：** 基于 OpenCLI 的可视化内容采集/AI打标管理系统，含任务调度、分布式 Agent 节点管理、Webhook 投递日志。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| 5 板块功能结构 | 数据源管理/任务计划/采集记录/节点管理的分层概念，对应 News Sentry 的 SourceChannel/run log/Skill 分层 | [development-plan.md §5 Phase 4](./development-plan.md) | 已落地（概念） |
| Bridge vs CDP 模式区分 | 登录态平台走 Bridge（需 session profile），公开页走 CDP（无状态）；这个区分比单纯 `browser=true/false` 更精确 | [外部集成策略 §3](./external-integration-strategy.md)；`ToolManifest.permissions.browser.session_profile_required` | 已落地 |
| Agent 路由四级优先级 | 手动指定 > 计划绑定 > 站点绑定 > 自动分配；映射为 Skill 选择优先级 | [development-plan.md §5 Phase 4](./development-plan.md)；SkillManifest 选择规则 | Phase 4 候选 |
| Webhook 投递日志格式 | 每次输出投递记录 channel、HTTP 状态码、延迟、错误类型 | `logs/output_dispatch.jsonl`；`output_result.destinations[]` | Phase 3/5 候选 |
| Docker 多节点架构 | 分布式采集节点，多 Agent 并行 | v1 舍弃（单机）；Phase 6+ 参考 | v1 舍弃 |

---

## P3 — Intel_Briefing

**项目：** [github.com/77AutumN/Intel_Briefing](https://github.com/77AutumN/Intel_Briefing) | Stars: 124 | 语言: Python

**核心能力：** 从 12+ 数据源抓取、翻译（DeepL/Gemini）、分析，生成中文日报；支持 GitHub Actions 自动化。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| Tier 1/Tier 2 采集分层 | Tier 1=聚合器（RSS/newsnow/公开 API），Tier 2=独立传感器（特定站点爬虫），分层控制成本和风险 | `SourceChannel.tier` 字段（Phase 4 扩展）；[development-plan.md §4 Phase 3](./development-plan.md) | Phase 4 候选 |
| 防幻觉降级机制 | AI 推断内容标记 `⚠️ 链接未验证`；News Sentry 对应 `metadata.translation.status="unverified"` | [contracts-canonical.md §6](./contracts-canonical.md)；`metadata.translation.status` | 已落地 |
| graceful degradation | 单个数据源失败不崩溃全局 run；写 `status=skipped` 并继续 | [SandboxPolicy与执行权限规格.md](./brainstorming/SandboxPolicy与执行权限规格.md)；source health `status=degraded` | 已落地 |
| GitHub Actions cron 参考 | `.github/workflows/daily-report.yml` 是 Hermes cron 触发模式的最近参照 | [development-plan.md §3 Phase 2](./development-plan.md)；Hermes adapter | Phase 2 候选 |
| 数据源清单（12 条） | HN/GitHub Trending/ArXiv/HF Papers/Product Hunt/TechCrunch/MIT TR 等作为 Phase 4 RSS 候选 | [外部集成策略 §4](./external-integration-strategy.md)；[datasets-catalog-italy.md](./datasets-catalog-italy.md) | Phase 4 候选 |

---

## P4 — TrendRadar

**项目：** [github.com/sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) | 语言: Python

**核心能力：** AI 舆情监控，多平台聚合（HN/知乎/微博/微信），关键词筛选，多渠道推送矩阵，支持 MCP server 形态。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| 关键词×频率矩阵 | `FilterRules.keyword_matrix` 设计：关键词列表 + 权重 + 频率窗口；驱动 `news_value_score` 计算 | [development-plan.md §4 Phase 3](./development-plan.md)；`FilterRules` schema | Phase 3 候选 |
| 多渠道推送 fanout | 飞书/钉钉/微信/Telegram/Email/ntfy/Bark/Slack/Webhook 多路 fanout | `output_result.destinations[]` 多 channel；Phase 3 飞书基线，Phase 5 扩展 | 已落地（Phase 3/5） |
| MCP server 暴露形态 | 把 Skill 包装为 MCP server 供 Claude 等客户端直接调用 | `SkillManifest.mcp_compatible=true`（Phase 4+ 可选）；[外部集成策略 §5](./external-integration-strategy.md) | Phase 4 候选 |
| newsnow API 数据源 | 多平台热榜聚合 API，可作为 `SourceChannel.type=api` 接入 | [外部集成策略 §5](./external-integration-strategy.md)；Phase 4 RSS/API 候选源 | Phase 4 候选 |
| 推送阈值配置 | 用户可设置 `news_value_score` 阈值，只推送超过阈值的事件 | `PipelineContext.target_config.priority_threshold`；[contracts-canonical.md §4.1](./contracts-canonical.md) | 已落地 |

---

## P5 — MiroShark

**项目：** [github.com/aaronjmars/MiroShark](https://github.com/aaronjmars/MiroShark) | 语言: Python

**核心能力：** 基于 LLM 的群体智能模拟引擎；创建 AI agent 角色进行观点对话模拟，支持可复现配置、可分享情景链接。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| Reproducibility config | 把 agent 参数、模型配置、随机种子全部写入 config 文件，run 可完全复现 | `run_id` + `PipelineContext.run_config` snapshot；[development-plan.md §4 Phase 3](./development-plan.md) | 已落地 |
| 可分享情景链接 | 配置序列化为 URL-safe 字符串便于分享和审查 | v1 用 Markdown frontmatter 代替；run log 可导出为可审查文件 | v1 舍弃（Markdown 已够） |
| Trace Interview 模式 | 对 agent 决策过程进行访谈式可解释回溯 | `processing_history[]` 字段记录每步决策；Phase 5 Judge Skill 输出 reasoning | Phase 5 候选 |
| 群体智能模拟 | 用多 agent 模拟意大利公众舆论反应 | v2+ 候选；v1 超范围 | v1 舍弃 |

---

## P6 — BettaFish

**项目：** [github.com/666ghj/BettaFish](https://github.com/666ghj/BettaFish) | 语言: Python

**核心能力：** 多 agent 公众舆论分析，专业化子 agent（Monitor/Analyst/Judge/Presenter），ForumEngine 多 agent 论辩，IR 光学渲染报告。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| 专业化 agent 分工 | Monitor/Analyst/Judge/Presenter 角色对应 News Sentry 的 collect/filter/judge/output Skill 分层 | [integration-protocol.md §2](./integration-protocol.md)；`SkillManifest.pipeline_stage` | 已落地（概念验证） |
| ForumEngine 多 agent 论辩 | 多个 Judge agent 对同一事件从不同角色视角评分，取加权平均 | v2+ 候选，Phase 6 小规模实验；[reference-projects-insights.md P6]() | Phase 6+ 候选 |
| IR/装订渲染分离 | 信息检索（内容）和最终渲染（格式）分离，同一内容可输出多种格式 | `output_result.format`（`markdown`/`push`/`obsidian`）；Phase 5 Outputter Skill | Phase 5 候选 |
| 情绪/立场多维度分析 | 除事实提取外，分析情绪极性、立场倾向、论证强度 | `sentiment_score`（-1.0~1.0）；Phase 5 judge 维度扩展候选 | Phase 5 候选 |
| MindSpider 爬虫栈 | 社媒登录态爬虫，多账号管理 | 已加超 v1 banner；Phase 6 走 OpenCLI 适配代替 | v1 舍弃 |

---

## P7 — worldmonitor

**项目：** [github.com/koala73/worldmonitor](https://github.com/koala73/worldmonitor) | 语言: TypeScript (Tauri + React)

**核心能力：** 实时全球情报仪表盘，AI 新闻聚合，双地图引擎（globe.gl + Leaflet），65+ 数据源，国家情报指数（CII）。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| Country Intelligence Index (CII) | 国家级复合评分（政治风险+经济动荡+社会稳定+外交关系）；Phase 7 多目标扩展时可借鉴 | Phase 7 TODO；`metadata.classification.country_axes[]` 设计 | Phase 7 候选 |
| 跨流相关性 | 检测同一事件在多数据源的关联报道，建立 story 聚合 | `story_id`/`cluster_id` 字段；Phase 5+ Judge Skill cross-source 功能 | Phase 5 候选 |
| 65+ 数据源目录 | 覆盖政府、国际机构、媒体聚合器的数据源清单 | [datasets-catalog-italy.md](./datasets-catalog-italy.md)；Phase 4 候选源 | Phase 4 候选 |
| 地图引擎 | globe.gl / Leaflet 可视化 | ADR-0010 舍弃；Obsidian 无法渲染 | v1 舍弃 |
| Tauri 桌面应用 | 跨平台桌面客户端 | ADR-0010 舍弃 | v1 舍弃 |

---

## P8 — awesome-public-datasets

**项目：** [github.com/awesomedata/awesome-public-datasets](https://github.com/awesomedata/awesome-public-datasets) | Stars: 63k

**核心能力：** 按领域分类的公开数据集目录，覆盖 Economics、Government、Social、News 等多个领域。

| 启发点 | 对 News Sentry 的具体启发 | 落地指针 | 采纳状态 |
|---|---|---|---|
| Economics 数据集 | Eurostat、World Bank、IMF、BIS 等国际经济数据，用于意大利经济议题背景验证 | [datasets-catalog-italy.md](./datasets-catalog-italy.md)；Phase 4 候选 | 已落地（数据集目录） |
| Government 数据集 | 意大利政府开放数据（dati.gov.it）、European Data Portal | [datasets-catalog-italy.md](./datasets-catalog-italy.md)；Phase 4 候选 | 已落地（数据集目录） |
| News 数据集 | GDELT、Helium 3.2M 政治偏向新闻库，用于 `source_credibility` 基线校准 | [datasets-catalog-italy.md](./datasets-catalog-italy.md)；Phase 3 source credibility 初始化 | 已落地（数据集目录） |
| Social Sciences 数据集 | ACLED 冲突事件库（意大利劳资/政治冲突事件）；CEPII 国际贸易数据 | [datasets-catalog-italy.md](./datasets-catalog-italy.md) | Phase 5+ 候选 |

---

## 价值提取汇总

| 项目 | 最高价值启发 | 采纳优先级 | 核心风险 |
|---|---|---|---|
| OpenCLI | 统一多平台采集接口，零 LLM 成本 | P0（Phase 4 主线） | OpenCLI API 版本兼容 |
| opencli-admin | Bridge/CDP 模式区分、路由优先级概念 | P1（Phase 4 设计参考） | 无代码依赖风险 |
| Intel_Briefing | 防幻觉降级、Tier 分层、graceful degradation | P1（Phase 3 设计参考） | 无代码依赖风险 |
| TrendRadar | 关键词矩阵、多渠道推送 fanout、MCP server | P1（Phase 3/5） | 无代码依赖风险 |
| MiroShark | Reproducibility config 设计 | P2（Phase 3 借鉴） | 无代码依赖风险 |
| BettaFish | 专业化 agent 分工概念验证、ForumEngine v2+ | P3（Phase 5/6） | 无代码依赖风险 |
| worldmonitor | CII 复合评分设计（Phase 7）、65+ 数据源清单 | P3（Phase 7） | 无代码依赖风险 |
| awesome-public-datasets | 意大利/欧盟数据集筛选 | P2（Phase 4 数据源） | 数据集许可证合规 |
