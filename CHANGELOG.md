# Changelog

本项目的所有重要变更记录于此。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.8.0] — 2026-05-25

### 新增 (Phase 66)
- Phase 66: desktop.py 测试覆盖 17%→61% — 46 个新测试（配置/版本/更新/通知/自启动/退出）
- Phase 66: 首次启动引导 API — `GET /api/v1/auth/setup-status` + `POST /api/v1/auth/setup`
- Phase 66: 前端自动检测首次使用 — 登录页 ↔ 创建管理员模式切换
- Phase 66: Tauri vs pywebview 性能基准对比报告 — 启动速度 5-8x / 内存减少 60% / 体积缩小 3-5x

### 新增 (Phase 65)
- Phase 65: Tauri 桌面客户端原型 — clients/tauri/ (Rust + tauri v2)
- Phase 65: 原生 API commands — check_update / open_url (Tauri invoke handler)
- Phase 65: 平台图标 — .ico/.icns/.png for Tauri bundle targets

### 变更
- 全量测试 1764 passed, 86% coverage (从 1718 tests / 84% 提升)
- API 端点总数 71 (从 69 增加 2 个 setup 端点)
- 总代码 20,151 行 Python + 9,268 行前端

---

## [1.7.1] — 2026-05-22

### 新增
- Phase 61: CI 多平台 PyInstaller 构建 — macOS arm64 + Windows x64 + Linux x64 (release.yml matrix)
- Phase 61: pytest-timeout 集成 — CI `--timeout=300` 防止测试无限挂起
- Phase 61: 本地客户端路线图 Phase 62-65 (development-plan.md)

### 修复
- Phase 60: CI mypy 兼容 — `warn_unused_ignores` 禁用 + desktop.py 通用 suppress
- Phase 60: 消除 8 处意大利硬编码 — CI hardcoded target scan 通过
- Phase 61: `doctor --target` 默认值 `'italy'` → `'all'`
- Phase 61: `create_app()` 退出挂起 — atexit 清理 aiosqlite 连接 (生产) + skip_lifespan + store.close() (测试)
- Phase 61: `test_import_dedup_with_sqlite` 300s 超时修复
- Phase 61: event_links 测试使用相对时间 — 修复超过 7 天窗口导致的失败

### 新增 (Phase 62)
- Phase 62: 应用图标 — `.ico` (Windows) + `.icns` (macOS) + `.iconset` + PNG
- Phase 62: PyInstaller spec 平台感知图标引用 (`_icon_path()`)
- Phase 62: Light mode 主题切换 — CSS 变量 + `[data-theme="light"]` + `prefers-color-scheme` 跟随系统
- Phase 62: 设置页「外观主题」tab — 深色/浅色/跟随系统切换 + 预览卡片
- Phase 63: update.json manifest — release workflow 自动生成
- Phase 63: 桌面应用一键更新 — 下载 + 替换 + 重启 (pywebview JS bridge)
- Phase 63: `_check_update` 版本号从 `__version__` 动态读取（消除硬编码）

### 新增 (Phase 64)
- Phase 64: 备份列表 API (`GET /api/v1/maintenance/backups`) + 恢复 API (`POST /api/v1/maintenance/restore`)
- Phase 64: 前端备份恢复 tab — 立即备份 + 备份列表 + 一键恢复
- Phase 65: Tauri 桌面客户端原型 — clients/tauri/ 目录
- Phase 65: Rust 核心 — Cargo.toml + lib.rs + main.rs + build.rs
- Phase 65: 前端迁移验证 — tauri.conf.json 指向现有 SPA (frontendDist)
- Phase 65: 原生 API commands — check_update / open_url (Tauri invoke handler)
- Phase 65: 平台图标 — .ico/.icns/.png for Tauri bundle targets

## [1.7.0] — 2026-05-22

### 新增
- Phase 55: pywebview 桌面壳 — `news-sentry desktop` 命令，原生窗口 + 系统托盘 + 配置持久化
- Phase 55: SSE 实时事件推送 — `GET /api/v1/events/stream` + 前端 EventSource 连接
- Phase 55: PWA 支持 — Service Worker 缓存 + 浏览器桌面通知 + manifest.json
- Phase 57: 跨平台桌面适配 — Linux/Windows 系统托盘 + `_os_info()` + 统一退出
- Phase 57: PyInstaller 打包 — `news-sentry.spec` onefile 配置 (27MB arm64 macOS)
- Phase 57: 开机自启动 — `desktop --autostart/--no-autostart` (macOS LaunchAgent + Linux XDG + Windows 注册表)
- Phase 57: 桌面通知统一 — pywebview JS bridge `_NativeNotifyApi` + 前端 Notification API 降级
- Phase 57: 自动更新检测 — GitHub Releases API + CLI 提示 + 前端更新横幅
- Phase 58: SSE 断线重连 + 连接状态指示器 — 指数退避 (1s→16s, 最多 5 次) + 顶部 3px 状态条
- Phase 58: PWA offline 增强 — SW v3 缓存所有 page modules + 离线 HTML fallback + 在线/离线检测
- ADR-0026: 三阶段客户端架构演进路线 (pywebview → Tauri → 云端集群 + 分布式)

### 变更
- Phase 56: 5 个读端点从 503 改为优雅降级（趋势、智能告警、用户列表、API Key 查询）
- Phase 56: 9 处静默 `except:pass` 添加 `logger.warning/debug` 日志
- Phase 56: `--log-level` 扩展为 5 级 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- Phase 58: `test_api_server.py` 从全量挂起修复为 106 tests in 6.17s (async + `httpx.AsyncClient`)
- 1718 tests (+106), ruff=0, mypy=0, 85% coverage

### 修复
- Phase 56: `test_async_run` 2 个持久失败 — patch 目标 `async_run`→`run` 修正
- Phase 57: desktop.py 4 个 mypy 错误 — winreg/pystray/uvicorn type ignore + json.loads 返回值类型

### 新增 (Phase 59-60)
- Phase 59: CSS 目录索引 — `style.css` 添加 TOC 目录注释
- Phase 60: PyPI 自动发布工作流 — `.github/workflows/release.yml` (tag 驱动 + Trusted Publisher)

### 修复 (Phase 60)
- Phase 60: CI mypy 兼容 — `--ignore-missing-imports` + `warn_unused_ignores` 禁用 + desktop.py 通用 suppress

## [1.6.0] — 2026-05-17

### 新增
- Phase 48: 驻意记者站场景 — `events/import` API + SocialKOLCollector + 492 X.com accounts (14 维度)
- Phase 49.5: 应用产品化 — 设计系统升级 + 登录品牌化 + 响应式布局 + 骨架屏 + 快捷键面板
- Phase 49.5: 用户管理 CRUD + 通知设置 + 简报邮件 + Toast 队列 + 离线检测
- Phase 50: 本地客户端 v1 — `news-sentry serve` 命令 + OS 服务集成 + 跨平台安装脚本
- Phase 51: serve 生产加固 — 自动采集 + `--stage` 选项 + PID 文件 + 日志分级 + `stop` 命令
- Phase 52: 本地客户端 v2 — CLI 命令完善 + 安装体验打磨
- Phase 53: Windows 安装支持 + kill 命令跨平台
- Phase 54: 质量加固 — Store 同步初始化修复 + markdown_writer 100% 覆盖
- 前端 v2 重写: 三层路由 + Token 认证 + Tab 系统 + 23 tabs + Chart.js 可视化
- 认证系统: 用户名+密码登录 + Bearer Token (24h TTL) + reader/admin 角色
- Token 持久化 + AI prompt 消毒 + Docker 三层镜像 (core/browser/full)
- 部署方案: Cloudflare Worker + Container + Cron + AI Gateway + Pages + GCP + 5 平台脚本

### 变更
- 版本号推进至 1.6.0
- 1635 tests, ruff=0, mypy=0, 91% coverage

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
