# News Sentry — 架构总览

> 版本: v1.0.0 | 日期: 2026-05-12

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    CLI / API 入口                      │
│  python -m news_sentry.cli run    FastAPI /api/v1     │
└────────────┬─────────────────────────────┬───────────┘
             │                             │
┌────────────▼─────────────────────────────▼───────────┐
│                   bounded_run                         │
│            ConfigLoader + RunLog + Memory             │
└────────────┬─────────────────────────────┬───────────┘
             │                             │
   ┌─────────▼─────────┐       ┌──────────▼──────────┐
   │    Collect 阶段    │       │    Filter 阶段       │
   │  RSSCollector      │       │  RulesFilter         │
   │  APICollector      │──────▶│  ClassifierRules     │
   │  OpenCLICollector  │       │  (keyword + L0-L3)   │
   │  SocialKOLCollector│       └──────────┬──────────┘
   └────────────────────┘                  │
                                ┌──────────▼──────────┐
                                │    Judge 阶段        │
                                │  ConfidenceRouter    │
                                │  (Rules → AI 升级)   │
                                │  RulesJudgeSkill     │
                                │  JudgeSkill (AI)     │
                                └──────────┬──────────┘
                                           │
   ┌──────────────────────┐     ┌──────────▼──────────┐
   │  Alert Pipeline      │◀────│    Output 阶段       │
   │  (Feishu/Email/TG)   │     │  Event Index         │
   │                      │     │  Markdown Export     │
   └──────────────────────┘     │  AlertPipeline       │
                                └──────────┬──────────┘
                                           │
                               ┌───────────▼──────────┐
                               │  Feedback Loop        │
                               │  FeedbackCollector    │
                               │  RulesOptimizer       │
                               └──────────────────────┘
```

## 目录结构

```
src/news_sentry/
├── core/           # 核心运行时
│   ├── run.py              # bounded_run 入口
│   ├── config.py           # ConfigLoader + ResolvedConfig
│   ├── memory.py           # 跨运行状态持久化
│   ├── sandbox.py          # 5 维沙箱权限模型
│   ├── session_profile.py  # 浏览器 session 治理
│   ├── kol_state.py        # KOL 状态管理
│   ├── matrix_governance.py # 信源生命周期
│   ├── matrix_evolution.py # 信源矩阵自进化
│   ├── source_health_checker.py # 健康巡检
│   ├── alert_pipeline.py   # 多通道告警
│   ├── confidence_router.py # 规则+AI 置信度路由
│   ├── feedback_collector.py # 人工反馈采集
│   ├── rules_optimizer.py  # 规则权重优化
│   ├── api_server.py       # FastAPI REST API
│   └── health_server.py    # /health HTTP 端点
├── adapters/       # 外部适配层
│   ├── providers/  # AI Provider (OpenAI/Anthropic/Rules)
│   ├── tools/      # OpenCLI ToolAdapter
│   └── runtime/    # Hermes/OpenClaw RuntimeAdapter
├── skills/         # 管道技能
│   ├── collect/    # RSSCollector + APICollector + RSSDiscovery
│   ├── filter/     # RulesFilter + ClassifierRules
│   ├── judge/      # RulesJudge + JudgeSkill
│   └── output/     # Event index + Markdown export projection
└── models/         # Pydantic 数据模型
    ├── newsevent.py
    ├── manifests.py
    ├── pipeline_context.py
    └── provider_config.py
```

## 数据流

1. **Collect**: RSS/API/OpenCLI → `NewsEvent` (stage=COLLECTED) → `raw/`
2. **Filter**: 关键词评分 + L0-L3 分类 → (stage=FILTERED) → `evaluated/`
3. **Judge**: ConfidenceRouter 规则→AI 升级 → (stage=JUDGED) → `evaluated/`
4. **Output**: canonical/event index + AlertPipeline 告警推送；Markdown 仅作为用户按需导出或显式启用的本地草稿投影
5. **Feedback**: 人工编辑 `reviewed/` → FeedbackCollector → RulesOptimizer

## Target 配置

5 个 target 已配置:

| Target | 语言 | 源数 | 关键词规则 |
|--------|------|------|-----------|
| italy | it→zh | 19+ | 100+ |
| china-watch-en | en→zh | 10+ | 30+ |
| japan | ja→zh | 19 | 59 |
| germany | de→zh | 22 | 46 |
| france | fr→zh | 21 | 45 |

## 关键 ADR

| ADR | 决策 |
|-----|------|
| ADR-0004 | 采集阶段机译 title_pre + judge 阶段 canonical 翻译 |
| ADR-0009 | 四层分类框架 L0-L3 |
| ADR-0025 | CLI-first；FastAPI + Vanilla JS 嵌入式 SPA 可选，无重型前端框架 |
| ADR-0012 | Python 3.11+ / Pydantic v2 |
| ADR-0017 | 采集阶段零 Token 消耗 |
| ADR-0019 | 信源生命周期状态机 active/degraded/dead |

## 安全机制

- SandboxEnforcer: 5 维权限（命令/网络/文件/浏览器/预算）
- StopOnRiskError: 自动停止风险操作
- API Key 认证 + 速率限制（60 req/min）
- 所有密钥通过环境变量注入，禁止硬编码
- 详细审计报告: [docs/security-audit-report.md](security-audit-report.md)
