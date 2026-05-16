# Changelog

本项目的所有重要变更记录于此。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.5.0] — 2026-05-16

### 新增
- Phase 47: 治理 backlog 清零 — 8 条治理项全部关闭
- ADR-0024: Schema 版本治理策略
- doctor 命令新增术语表覆盖率检查 (86 terms, 69% eval coverage)
- Phase 46: MatrixEvolution JSONL 审计日志 + RSS 发现冷却期 (168h)
- Phase 46: SessionProfile expires_at 过期 + is_expired()/needs_review() + 自动跳过
- Phase 45: CI/CD 整合 — 合并冗余 workflow, Python 3.12 only, 覆盖率 XML 报告
- Phase 44: eval-set v2→v3 (210→250 examples) + _run_judge_async 7 项测试
- Phase 40-43: Web UI + 运维仪表盘 + 趋势分析 + 数据保留策略

### 变更
- 版本号推进至 1.5.0
- development-plan.md v2.7: 治理 backlog 全部关闭
- 1629 tests, 92% coverage, ruff=0, mypy=0

## [1.4.0] — 2026-05-15

### 新增
- Phase 34-39: 运维仪表盘 (概览/事件/告警/趋势)
- 异步运维 API (SQLite 查询)
- 趋势分析引擎
- 多通道告警增强

### 变更
- 版本号推进至 1.4.0

## [1.3.0] — 2026-05-14

### 新增
- Phase 30-33: 多语言 NLP 深度分析
- NLP 情感分析引擎 (规则零成本基线 + AI 按需升级)
- 5 种语言情感/实体词典 (it/en/ja/de/fr)
- Entity Tracking (entities 表 + upsert 去重 + 查询 API)
- Web UI NLP 可视化 (ES Modules + Dashboard)

### 变更
- 版本号推进至 1.3.0

## [1.2.0] — 2026-05-15

### 新增
- Phase 25-29: 性能优化全面完成
- 异步基础设施 (async_run, AsyncRateLimiter, httpx.AsyncClient)
- SQLite 存储 (AsyncStore 5 表, WAL mode)
- AI 优化 (TranslationBatcher, LLMCacheManager, TieredConfidenceRouter)
- API Server 重构 (SQLite 查询, ConfigCache TTL)
- 多目标并发调度 (FairScheduler, --target all|a,b, --interval N)

### 变更
- 版本号推进至 1.2.0
- YAML→SQLite 自动迁移

## [1.1.0] — 2026-05-13

### 新增
- Phase 24: 突发新闻雷达
- home_relevance 字段 + tier 推送
- min-level 调度 + 实时突发新闻检测
- L2/L3 自动翻译 + 报道方案草稿生成

### 变更
- 版本号推进至 1.1.0

## [1.0.0] — 2026-05-12

### 新增
- Phase 20: FeedbackCollector — 扫描 reviewed/ 目录解析 human_verdict 反馈
- Phase 20: RulesOptimizer — 根据人工反馈自动调整关键词权重
- Phase 21: RSSDiscovery — 从现有信源页面自动发现新 RSS/Atom 链接
- Phase 21: SourceHealthChecker — 信源健康巡检（可达性+更新频率+健康评分）
- Phase 21: MatrixEvolution — 候选源审批→配置生成→自动纳入采集矩阵
- Phase 22: API Server — FastAPI REST API 网关
- Phase 22: API Key 认证 + 60 req/min 速率限制
- Phase 22: Webhook 入站 — 接收外部事件写入 raw/ 目录
- Phase 22: OpenAPI 3.1 文档（/docs + /openapi.json）
- Phase 23: 安全审计报告（OWASP Top 10 全部通过）
- Phase 23: 架构总览、API 文档、部署指南
- 文档: security-audit-report.md, architecture.md, api-reference.md, deployment-guide.md
- 工具: tools/security_audit.py — OWASP Top 10 快速扫描

### 变更
- 版本号推进至 1.0.0
- pyproject.toml 新增 api 可选依赖组（fastapi + uvicorn）
- MarkdownWriter 扩展 filter_matched_keywords / human_verdict frontmatter 字段
- RulesFilter 记录匹配关键词到 event.metadata["filter_matched_keywords"]

## [未发布]

## [0.7.0] — 2026-05

### 新增
- Phase 16: 日本 target 配置（ja→zh, 19 源, 59 关键词规则）
- Phase 16: classification schema 扩展 keywords_ja / label_ja
- Phase 12: MatrixGovernance 信源生命周期管理（save/load YAML 持久化）
- Phase 12: BrowserFallback 3 层降级织入 SocialKOLCollector
- Phase 12: SocialKOLCollector 升级（stub → OpenCLI Bridge 真实采集器）

### 变更
- 版本号推进至 0.7.0

## [0.6.0] — 2026-05

### 新增
- Phase 14: ConfidenceRouter 混合规则+AI 置信度路由
- Phase 14: 三模式 eval runner + AI 成本追踪器
- Phase 14: 扩展 eval-set 至 210 条
- Phase 15: GHCR CI + Hetzner 部署脚本 + 健康监控脚本
- Phase 13: 优化过滤关键词规则 + 112 评估用例 + Eval Runner

### 变更
- Makefile: 新增 eval/eval-report 目标
- CI: 增加 config schema 校验步骤
- 版本号推进至 0.6.0

## [0.5.0] — 2026-05

### 新增
- Phase 14: ConfidenceRouter 混合规则+AI 置信度路由
- Phase 14: 三模式 eval runner + AI 成本追踪器
- Phase 14: 扩展 eval-set 至 210 条
- Phase 15: Cloud VPS 部署脚本 + GHCR CI + 健康监控
- Phase 16: 日本 target 配置（第三国家验证）
- Phase 12: 源矩阵扩展 14→70 源，覆盖 13 维×3 采集方式
- Phase 12: Social/KOL 采集器 + MatrixGovernance 信源生命周期管理
- Phase 12: BrowserFallback 3 层降级 + Dockerfile.full 完整运行环境
- Phase 13: 优化过滤关键词规则 + 112 评估用例 + Eval Runner

### 变更
- Makefile: 新增 eval/eval-report 目标
- CI: 增加 config schema 校验步骤
- 版本号推进至 0.5.0

## [0.4.0] — 2026-04

### 新增
- Phase 10: CI/CD 补全 + Docker 多阶段构建 + CLI doctor
- Phase 11: 多 Agent 编排器 + 趋势分析模块 + Judge 反馈回路
- ADR-0018/19/20

### 变更
- 版本号推进至 0.4.0

## [0.3.0] — 2026-04

### 新增
- Phase 9: Checkpoint 模块 + Metrics 模块 + JSON 结构化日志
- ADR-0017

### 变更
- 版本号推进至 0.3.0

## [0.2.0] — 2026-04

### 新增
- Phase 8: Foundation Fix — CLAUDE.md 决策框架 + AGENTS.md AI 原则
- Karpathy 四原则 Agent Skill 集成

### 变更
- 版本号推进至 0.2.0

## [0.1.0] — 2026-03

### 新增
- Phase 1-7: 核心 Pipeline（collect → filter → judge → output）
- RSS/API/OpenCLI 采集器
- AI Provider 路由（Anthropic/OpenAI/DeepSeek）
- Sandbox 安全策略
- Italy + China-Watch-EN 双 Target 配置
- JSON Schema 契约体系（13 份 Schema 2020-12）
- 829 tests, 95% coverage

### 变更
- 版本号推进至 0.1.0

---

## 版本号说明

- 当前版本号在 `pyproject.toml` 中维护
- 版本推进在 Phase 完成时更新
- CHANGELOG 在治理里程碑（v0.5.0）后开始正式维护
