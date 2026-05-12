# Changelog

本项目的所有重要变更记录于此。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

### 新增
- Phase 19: 德国 target 配置（de→zh, 22 源, 46 关键词规则）
- Phase 19: 法国 target 配置（fr→zh, 21 源, 45 关键词规则）
- Phase 19: classification schema 扩展 keywords_de/fr, label_de/fr
- Phase 18: health_server.py — 轻量 /health HTTP 端点（http.server, 90% 覆盖率）
- Phase 18: backup.sh — 每日增量+每周全量备份，保留 4 周
- Phase 18: logrotate.conf — 30 天日志轮转，每日 rotate + 压缩
- Phase 18: news-sentry.service — systemd 服务文件，Restart=on-failure
- Phase 17: AlertPipeline 告警管道 — 阈值过滤+24h 去重+飞书/邮件/Telegram 多通道推送
- Phase 17: destinations.yaml 扩展（6 个目的地，告警类型默认禁用）
- Phase 17: `${ENV_VAR}` 环境变量解析，禁止硬编码密钥
- 文档: v0.8.0~v1.0.0 迭代计划（Phase 19-23）
- 文档: Cloud VPS 方案推荐（Hetzner CX32 / Oracle Free）

### 变更
- outputdestinations.schema.json 扩展支持 email_smtp / telegram_bot 类型
- development-plan.md Phase 17 标记为 DONE，ALERT-001 治理条目已决策
- spec/README.md Mermaid 图扩展至 v1.0.0

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
