# News Sentry v2 -- 开发者上手引导 (MAKE_GUIDE.md)

## 前提条件

- **Python 3.11+**（venv 已含 3.12/3.13）
- **Git**
- **Docker**（可选，用于 RSS-Bridge sidecar；不影响核心功能）
- **macOS / Linux**（Windows 可通过 WSL2 或 `run.ps1` 运行）

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -e ".[api]"

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入一个 AI provider key:
#   GEMINI_API_KEY=xxxx   (推荐，在 https://aistudio.google.com/apikey 获取)
#   DEEPSEEK_API_KEY=sk-xxxx
#   GROQ_API_KEY=gsk_xxxx

# 5. 运行健康检查
./run.sh doctor --target italy
# 或：python -m news_sentry.cli doctor --target italy
```

---

## 常用命令

```bash
# 健康检查
./run.sh doctor --target italy

# 运行采集（只采集，不分析）
./run.sh run --target italy --stage collect

# 运行完整管道（采集→过滤→研判→输出）
./run.sh run --target italy --stage all

# 启动 API Server + 自动采集（开发模式）
./run.sh serve --target italy
# 访问 http://localhost:8000/admin/

# 查看帮助
./run.sh --help
```

所有命令均支持 `--profile` 参数切换运行环境（默认 `local-workstation`）。
完整 CLI 文档：`python -m news_sentry.cli --help`

---

## 项目结构概览

```
NewsSentry/
├── src/news_sentry/        # 核心 Python 代码
│   ├── adapters/           # AI provider 适配器 (gemini/deepseek/groq/...)
│   ├── api/                # FastAPI 路由 + 中间件
│   ├── cli/                # CLI 入口 (doctor/serve/run)
│   ├── collect/            # 信源采集器 (RSS/HN/Reddit)
│   ├── core/               # 核心引擎 (管道编排/配置/合同)
│   ├── models/             # Pydantic 数据模型
│   └── skills/             # Skill 模块 (collect/filter/judge/output)
├── config/                 # YAML 配置文件
│   └── provider/           # AI provider 路由配置
├── data/                   # 运行时数据 (gitignored)
│   └── {target_id}/        # 每个监控目标独立数据目录
├── docs/                   # 文档
│   ├── contracts-canonical.md  # 口径规范 (权威)
│   └── adr/                # 架构决策记录
├── schemas/                # JSON Schema 2020-12
├── frontend/               # 前端 (Tailwind + TypeScript)
│   └── public/             # 公开站点前端
├── .env.example            # 环境变量模板
├── run.sh                  # CLI 入口 (bash)
├── run.ps1                 # CLI 入口 (PowerShell)
├── docker-compose.yml      # Docker 部署
├── CLAUDE.md               # AI Assistant 行为指引
└── AGENTS.md               # 跨 Agent 共用基准
```

---

## AI Provider 链

News Sentry v2 使用内置的 Python provider 链，按优先级降级：

```
Gemini → DeepSeek → Groq → Cloudflare Workers AI
```

至少配置**一个** provider key。配置多个可自动降级（第一个失败时自动尝试下一个）。

| Provider | 环境变量 | 获取地址 |
|----------|---------|---------|
| Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| DeepSeek | `DEEPSEEK_API_KEY` | https://platform.deepseek.com/api_keys |
| Groq | `GROQ_API_KEY` | https://console.groq.com/keys |
| Cloudflare | `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | https://dash.cloudflare.com |

---

## Docker 部署（用于生产）

```bash
# 设置环境变量
export GEMINI_API_KEY=xxxx
export DEEPSEEK_API_KEY=sk-xxxx

# 启动
docker compose up -d

# 查看状态
docker compose ps
docker compose logs -f news-sentry

# 健康检查
curl http://localhost:8000/api/v1/health
```

Docker Compose 包含两个服务：
- `news-sentry`: API Server (port 8000)
- `rss-bridge`: RSS-Bridge sidecar (port 13080, 内网仅限)

---

## 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 单独文件
python -m pytest tests/test_doctor.py -v

# 带覆盖率
python -m pytest tests/ --cov=src/news_sentry --cov-report=term-missing
```

---

## 常见问题排查

### `ModuleNotFoundError: No module named 'news_sentry'`

```bash
pip install -e ".[api]"
```

### `.venv/bin/python: bad interpreter`

虚拟环境指向了错误路径，删除重建：
```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[api]"
```

### RSS-Bridge 返回 502（Docker）

```bash
docker compose restart rss-bridge
docker compose logs rss-bridge  # 查看错误
```

### 端口 8000 已被占用

```bash
lsof -i :8000
# 或更改端口：
NEWSSENTRY_PORT=8001 ./run.sh serve --target italy
```

### `未配置 AI API Key` 警告

至少设置一个 provider key（见上方表格）。免费层足够开发测试：
- Gemini: 免费层 1,500 req/day
- Groq: 免费层慷慨
- DeepSeek: 极低成本

---

## 更多文档

- `CLAUDE.md` — AI Assistant 行为指引 + Karpathy 四原则
- `AGENTS.md` — 架构规范 + 跨 Agent 共用基准
- `docs/contracts-canonical.md` — 口径规范（数据模型/管道阶段/目录协议）
- `docs/adr/` — 架构决策记录 (ADR-0001 ~ ADR-0025)
- `schemas/` — JSON Schema 2020-12 (13 份)
