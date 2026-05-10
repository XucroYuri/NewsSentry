# News Sentry

**Framework-neutral Agent Skill Pack for continuous news monitoring.**

First reference target: **Italy** (Italian → Chinese, Breaking News focus).
Core kernel and contracts are reusable for any country, region, or domain.

> **License**: [Apache 2.0](LICENSE) — 自由使用、修改、分发，含专利授权与免责条款。

---

## 前置条件

| 依赖 | 最低版本 | 用途 | 安装 |
|------|---------|------|------|
| **Python** | 3.11+ | 运行时 | [python.org](https://www.python.org/downloads/) / `brew install python@3.13` / `sudo apt install python3.12` |
| **pip** | 随 Python | 包管理 | 内置 |
| **git** | 任意 | 版本控制 | `brew install git` / `sudo apt install git` |
| Hermes Agent | v0.11+ | cron 调度 (可选) | `curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh \| bash` |

**零系统级原生依赖** — 所有 Python 包均为纯 Python wheel，不需要 `libxml2`、`libxslt` 或其他 C 扩展编译工具链。

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. 一键安装
bash install.sh --dev

# 3. 编辑环境变量（可选，默认使用 local-workstation profile）
# cp .env.example .env   # 已由 install.sh 自动创建

# 4. 干运行，验证配置
source .venv/bin/activate
make dry-run
# 或: python -m news_sentry.cli run --target italy --stage collect --profile local-workstation --dry-run

# 5. 运行采集
make run
# 或: python -m news_sentry.cli run --target italy --stage collect --profile local-workstation

# 6. 运行全链路 (collect → filter → judge → output)
make run-all
# 或: python -m news_sentry.cli run --target italy --stage all --profile local-workstation

# 7. 查看数据统计
make stats

# 8. 运行测试
make check
```

### 两种 Profile 的区别

| | `local-workstation` | `cloud-vps` |
|---|---|---|
| **用途** | 本地开发/测试/人工审查 | 24h 生产监控 |
| **触发方式** | CLI 手动 / Claude Cowork fallback | Hermes Agent cron / gateway |
| **超时** | 10 分钟 | 30 分钟 |
| **网络** | 宽松（本地调试） | 沙箱策略限制 |
| **推荐** | 首次部署验证 | 长期生产运行 |

---

## 项目架构

```
.
├── docs/           # 架构文档、ADR、Phase SPEC、SOP
│   ├── spec/       # 7 份 Phase SPEC 文档
│   ├── adr/        # 架构决策记录 (ADR-0001 ~ 0016)
│   ├── testing/    # 多运行环境测试方案 + 测试反馈
│   └── brainstorming/  # 设计讨论与参考文档
├── schemas/        # 13 份 JSON Schema 2020-12 契约文件
├── config/         # 所有运行时可配置参数
│   ├── targets/    # 监控目标配置 (italy.yaml + _template.yaml)
│   ├── sources/    # 按目标分组的信源配置
│   ├── profiles/   # 部署 profile (local-workstation, cloud-vps)
│   ├── filters/    # 过滤规则
│   ├── classification/  # 新闻分类规则
│   └── ...
├── src/news_sentry/  # Python 3.11+ 包
│   ├── core/       # 框架无关内核 (config, run, sandbox, file_writer, memory, run_log)
│   ├── skills/     # Collect / Filter / Judge / Output 子 Skill
│   ├── adapters/   # Runtime / Tool / Provider 适配桥接
│   ├── models/     # Pydantic 数据模型 (NewsEvent, PipelineContext)
│   └── cli/        # CLI 入口
├── tests/          # 282 个单元测试 (pytest)
├── data/           # 运行时数据 (gitignored)
├── LICENSE         # PolyForm Shield 1.0.0
├── Makefile        # 快捷命令
├── install.sh      # 一键安装脚本
├── .env.example    # 环境变量模板
└── pyproject.toml  # 包元数据
```

---

## 关键文档

| 文档 | 用途 |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent 指令基准 + 架构权威来源 |
| [docs/contracts-canonical.md](docs/contracts-canonical.md) | 口径规范唯一权威 (字段命名/分值量纲/目录映射) |
| [docs/development-plan.md](docs/development-plan.md) | 七阶段开发计划与 TODO 矩阵 |
| [docs/architecture-overview.md](docs/architecture-overview.md) | 系统架构总览 |
| [docs/spec/README.md](docs/spec/README.md) | Phase SPEC 索引 + 组件矩阵 |
| [docs/adr/README.md](docs/adr/README.md) | 架构决策记录索引 |
| [docs/testing/README.md](docs/testing/README.md) | 多运行环境测试方案索引 |
| [docs/testing/hermes-agent-test-feedback.md](docs/testing/hermes-agent-test-feedback.md) | Hermes Agent 测试反馈 + 开源部署审查 |

---

## 添加新监控目标

1. `cp config/targets/_template.yaml config/targets/{country}.yaml`
2. 创建 `config/sources/{country}/` 并添加信源配置
3. 创建 `config/filters/{country}/default.yaml` 过滤规则
4. 运行: `make run TARGET={country}`
5. 无需修改任何 Python 代码

详见 [docs/spec/phase-7-multi-target-expansion.md](docs/spec/phase-7-multi-target-expansion.md)。

---

## 开发阶段

| Phase | 状态 | 描述 |
|---|---|---|
| 1 — Contract Stabilization | ✅ 完成 | ADR 0001–0016, schemas, canonical contracts |
| 2 — Runtime Carrier Alignment | ✅ 完成 | cloud-vps / local-workstation profile, RuntimeHostAdapter |
| 3 — Kernel MVP | 🔄 进行中 | bounded run, RSS collect, filter, judge(stub), output |
| 4 — Tool/Skill Registry + OpenCLI | 📋 计划中 | ToolManifest registry, OpenCLI adapter |
| 5 — AI Provider Routing | 📋 计划中 | translate/judge/classify route_id 路由表 |
| 6 — Sandbox Hardening + KOL | 📋 计划中 | 完整 SandboxPolicy, 社媒/KOL 实验 |
| 7 — Multi-target Expansion | 📋 计划中 | 第二目标验证 |

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `NEWSSENTRY_PROFILE` | 否 | `local-workstation` | 部署 profile |
| `NEWSSENTRY_DATA_DIR` | 否 | `./data` | 数据输出目录 |
| `DEEPSEEK_API_KEY` | 否 (Phase 5) | — | DeepSeek API key |
| `OPENAI_API_KEY` | 否 (Phase 5) | — | OpenAI API key |
| `FEISHU_WEBHOOK_URL` | 否 | — | 飞书推送 Webhook |
| `all_proxy` | 否 | — | SOCKS5 代理 |

完整列表见 [`.env.example`](.env.example)。

---

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: news_sentry` | 未安装或 venv 未激活 | `bash install.sh --dev` |
| `corriere: SSL: UNEXPECTED_EOF` | Corriere della Sera RSS 服务器 SSL 问题 (已知) | 正常，其他源仍可采集 |
| `agi: 404 / fao-rss: 404` | 这两个源的 RSS URL 已失效 (已知) | 在 `config/sources/italy/agi.yaml` 中 `enabled: false` |
| `No module named 'news_sentry.cli'` | 工作目录不在项目根 | `cd /path/to/NewsSentry` |
| pytest 覆盖率低 | `src/news_sentry/adapters/` 和 `cli/` 的桩代码未测试 | 预期 — 这些模块在 Phase 4/5 实现 |

---

## 许可证

Copyright 2026 XucroYuri

本项目采用 [Apache License 2.0](LICENSE)。
