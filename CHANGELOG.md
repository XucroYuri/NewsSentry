# Changelog

本项目的所有重要变更记录于此。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

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
