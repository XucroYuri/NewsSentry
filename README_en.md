<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/tests-1251%20passed-brightgreen.svg" alt="tests" />
  <img src="https://img.shields.io/badge/coverage-92%25-green.svg" alt="coverage" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-strict-success.svg" alt="mypy" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>Framework-neutral AI News Monitoring Engine</strong><br>
  RSS/API/Social Collection → Smart Filtering → AI Judgment → Markdown Output<br>
  Configuration-driven, zero-code country expansion
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README_en.md">English</a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> · <a href="#installation">Install</a> · <a href="#usage">Usage</a> · <a href="#deployment">Deploy</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/api-reference.md">API</a>
</p>

---

## What is News Sentry?

News Sentry is a **continuous news monitoring platform** that automates the full intelligence lifecycle:

```
70+ Sources → Keyword Filtering → AI Scoring → Markdown Output + Real-time Alerts
```

**Core Features:**

| Feature | Description |
|---------|-------------|
| **Framework-neutral** | Runs on Hermes Agent, OpenClaw, or standalone CLI |
| **Config-driven** | Add new countries with YAML only — no code changes |
| **Zero-token collection** | RSS / API / OpenCLI collection consumes no AI tokens |
| **5 countries configured** | Italy, China, Japan, Germany, France |
| **Bilingual pipeline** | Original language → auto-translation → Chinese output |
| **Feedback loop** | Human annotations automatically optimize keyword weights |
| **Self-evolving sources** | RSS auto-discovery + health patrol + matrix expansion |
| **No dedicated frontend** | Obsidian Markdown + Feishu/Email/Push alerts |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. Install
bash install.sh --dev

# 3. Configure API Key (at least one, for AI judgment)
cp .env.example .env
# Edit .env and add OPENAI_API_KEY or ANTHROPIC_API_KEY

# 4. Verify configuration
source .venv/bin/activate
make dry-run

# 5. Run full pipeline
make run-all
```

> **First run takes ~1-2 minutes**: Collect 19+ Italian RSS sources → Filter 100+ keywords → AI judgment → Markdown output

---

## Installation

### Prerequisites

| Dependency | Min Version | Purpose |
|------------|-------------|---------|
| Python | 3.11+ | Runtime |
| pip | bundled | Package management |
| git | any | Version control |

> **Zero native dependencies** — all Python packages are pure wheels. No C toolchain required.

### One-click Install

```bash
bash install.sh --dev      # Development (includes pytest, ruff, mypy)
bash install.sh            # Production
bash install.sh --check    # Install + run tests
```

### Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # Development
pip install -e .           # Production
pip install -e ".[proxy]"  # SOCKS5 proxy support
pip install -e ".[api]"    # FastAPI REST API gateway
```

---

## Usage

### CLI Commands

```bash
# Single stage
python -m news_sentry.cli run --target italy --stage collect
python -m news_sentry.cli run --target italy --stage filter
python -m news_sentry.cli run --target italy --stage judge
python -m news_sentry.cli run --target italy --stage output

# Full pipeline
python -m news_sentry.cli run --target italy --stage all

# Other targets
python -m news_sentry.cli run --target japan --stage all
python -m news_sentry.cli run --target germany --stage all

# Dry-run (validate config, no file writes)
python -m news_sentry.cli run --target italy --stage all --dry-run

# Production profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps

# System diagnostics
python -m news_sentry.cli doctor --target italy
```

### Makefile Shortcuts

```bash
make dry-run        # Validate configuration
make run            # Collect stage
make run-all        # Full pipeline
make check          # lint + test
make stats          # Data statistics
make latest-log     # View latest run log
make doctor         # System diagnostics
make help           # View all commands
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | At least one | — | OpenAI API Key |
| `ANTHROPIC_API_KEY` | At least one | — | Anthropic API Key |
| `DEEPSEEK_API_KEY` | No | — | DeepSeek API Key |
| `NEWSSENTRY_API_KEY` | No | — | API gateway auth key |
| `NEWSSENTRY_PROFILE` | No | `local-workstation` | Deployment profile |
| `HTTPS_PROXY` | No | — | Proxy (e.g. `socks5://127.0.0.1:1080`) |

---

## Pipeline Overview

```
┌───────────────────────────────────────────────────────────────┐
│                        CLI / API Entry                         │
│      python -m news_sentry.cli        FastAPI /api/v1         │
└─────────────────────┬─────────────────────────┬───────────────┘
                      │                         │
┌─────────────────────▼─────────────────────────▼───────────────┐
│                     bounded_run Runtime                        │
│              ConfigLoader + RunLog + Memory                    │
└─────────┬───────────────────────────────────────┬─────────────┘
          │                                       │
 ┌────────▼────────┐                    ┌─────────▼──────────┐
 │   COLLECT        │                    │   FILTER            │
 │ RSS · API · KOL  │──────────────────→ │ 100+ keyword score │
 │ Zero Token       │                    │ L0-L3 classification│
 └─────────────────┘                    └─────────┬──────────┘
                                                  │
                                        ┌─────────▼──────────┐
                                        │    JUDGE            │
                                        │ ConfidenceRouter    │
                                        │ Rules → AI upgrade  │
                                        └─────────┬──────────┘
                                                  │
 ┌───────────────────────┐              ┌─────────▼──────────┐
 │  Alert Pipeline       │◀─────────────│   OUTPUT            │
 │ Feishu · Email · TG   │              │ Markdown generation │
 └───────────────────────┘              └─────────┬──────────┘
                                                  │
                                       ┌──────────▼─────────┐
                                       │  FEEDBACK           │
                                       │ Human → Rules auto  │
                                       └────────────────────┘
```

### Four Stages

| Stage | Input | Output | Description |
|-------|-------|--------|-------------|
| **Collect** | RSS/API/OpenCLI configs | `raw/` | Fetch from 70+ sources, zero token |
| **Filter** | `raw/` | `evaluated/` + `archive/` | Keyword scoring + L0-L3 classification + dedup |
| **Judge** | `evaluated/` | `evaluated/` | AI news value scoring + China relevance |
| **Output** | `evaluated/` | `drafts/` | Markdown reports + multi-channel alerts |

### Data Directory

```
data/{target}/
├── raw/           #  Collected events (Markdown + YAML frontmatter)
├── evaluated/     #  Filtered + judged events
├── drafts/        #  Output reports (v1: no auto-publish)
├── reviewed/      #  Human review candidates
├── published/     #  Approved archive
├── archive/       #  Rejected / duplicate / low-value
├── memory/        #  Known IDs / source health / cursors / optimizer state
└── logs/          #  Run logs + heartbeat
```

---

## Configured Targets

| Target | Language Pair | Sources | Keyword Rules |
|--------|--------------|---------|---------------|
| 🇮🇹 **italy** | it→zh | 19+ | 100+ |
| 🇨🇳 **china-watch-en** | en→zh | 10+ | 30+ |
| 🇯🇵 **japan** | ja→zh | 19 | 59 |
| 🇩🇪 **germany** | de→zh | 22 | 46 |
| 🇫🇷 **france** | fr→zh | 21 | 45 |

### Add a New Country (Zero Code)

```bash
# 1. Create target config from template
cp config/targets/_template.yaml config/targets/{country}.yaml

# 2. Create source and filter configs
mkdir -p config/sources/{country}/rss config/filters/{country}

# 3. Run
make run TARGET={country}
```

---

## Deployment

### Docker (Recommended)

```bash
docker build -t news-sentry .
docker run -d \
  --name news-sentry \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v /data/news-sentry:/app/data \
  -p 8000:8000 \
  news-sentry
```

### API Server

```bash
pip install ".[api]"
NEWSSENTRY_API_KEY=your-key \
  uvicorn news_sentry.core.api_server:create_app \
  --factory --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/api/v1/health

# Query events
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/v1/events?target_id=italy&page=1&page_size=20"
```

> Full deployment guide: [docs/deployment-guide.md](docs/deployment-guide.md)

### systemd

```bash
sudo cp config/news-sentry.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-sentry
```

### Cron (without Docker)

```bash
*/15 * * * * cd /path/to/NewsSentry && .venv/bin/python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Language | Python 3.11+ | strict mypy + ruff |
| Data Models | Pydantic v2 | Runtime validation + serialization |
| CLI | Click 8.1+ | `news-sentry` command |
| HTTP | httpx 0.27+ | SOCKS5 proxy support |
| RSS | feedparser 6.0+ | RSS/Atom parsing |
| API | FastAPI 0.110+ | REST API + OpenAPI 3.1 |
| Config | PyYAML 6.0+ | Full YAML config-driven |
| Storage | Markdown + YAML | Obsidian-compatible |
| Testing | pytest 8.0+ | 1251 tests / 92% coverage |

---

## Development

```bash
make check          # lint + test (must pass before commit)
make test           # Run tests
make lint           # ruff + mypy
make fmt            # Auto-fix code style
make scan-sensitive # Scan for sensitive data
make eval           # Run evaluation set
```

**Quality gates:**
- `ruff check` — 0 errors
- `mypy —strict` — 0 issues
- `pytest` — 1251 passed

---

## Project Status

**v1.0.0 — All 23 Phases Complete**

| Stage | Version | Status |
|-------|---------|--------|
| Foundation (P1-P7) | v0.1–v0.3 | ✅ Done |
| Iteration (P8-P11) | v0.4 | ✅ Done |
| Source Matrix + Eval (P12-P13) | v0.5 | ✅ Done |
| AI Optimization + Cloud (P14-P15) | v0.6 | ✅ Done |
| Production + Multi-target (P16-P18) | v0.7 | ✅ Done |
| Multilingual + Feedback (P19-P20) | v0.8 | ✅ Done |
| Ecosystem Integration (P21-P22) | v0.9 | ✅ Done |
| Stable Release (P23) | v1.0 | ✅ Done |

| Metric | Value |
|--------|-------|
| Tests | 1251 passed |
| Coverage | 92% |
| Lint | ruff = 0 errors |
| Type | mypy strict = 0 issues |
| Targets | 5 countries |
| Sources | 70+ |
| Phases | 23/23 complete |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System architecture, data flow, directory structure |
| [API Reference](docs/api-reference.md) | REST API endpoints, auth, Webhook |
| [Deployment Guide](docs/deployment-guide.md) | Docker / VPS / API / systemd |
| [Security Audit](docs/security-audit-report.md) | OWASP Top 10 audit report |
| [Development Plan](docs/development-plan.md) | 23-phase roadmap |
| [Contracts](docs/contracts-canonical.md) | Field naming, scoring, directory mapping |
| [ADR](docs/adr/) | Architecture Decision Records (ADR-0001 ~ 0022) |
| [Phase SPEC](docs/spec/) | Per-phase implementation specs |

---

## Capability Boundaries & Roadmap

### Current vs Planned

```
                        ┌─────────────────────────────────────────────┐
                        │         News Sentry Capability Map           │
                        └────────────────────┬────────────────────────┘
                                             │
          ┌──────────────────────────────────┼──────────────────────────────────┐
          │                                  │                                  │
    ┌─────▼─────┐                    ┌────────▼────────┐                ┌────────▼────────┐
    │  ✅ Shipped │                    │  🔧 Partial      │                │  📋 Planned      │
    └─────┬─────┘                    └────────┬────────┘                └────────┬────────┘
          │                                  │                                  │
   ┌──────┴──────┐                  ┌────────┴────────┐                ┌────────┴────────┐
   │ · 70+ sources│                  │ · VPS 72h verify │                │ · More targets   │
   │ · 5 countries│                  │ · KOL still      │                │   (Korea/UK etc) │
   │ · AI judging │                  │   experimental   │                │ · Multi-agent    │
   │ · Keyword    │                  │ · Self-evolution │                │ · Knowledge graph│
   │   filtering  │                  │   needs more data│                │ · Live dashboard │
   │ · Feedback   │                  └─────────────────┘                └─────────────────┘
   │ · REST API   │
   │ · Alerts     │
   │ · Security   │
   └─────────────┘
```

### Strengths vs Limitations

| Dimension | ✅ Strength | ⚠️ Limitation |
|-----------|------------|---------------|
| **Collection** | 70+ sources / zero token / auto-discovery | Social KOL is experimental, depends on external Bridge |
| **Judgment** | Rules + AI dual routing / accuracy >70% | AI may misjudge — cannot replace human decision |
| **Multilingual** | 5 countries / it/en/ja/de/fr | Translation quality depends on AI, domain terms may vary |
| **Deployment** | Docker zero-dep / API gateway | VPS long-term stability needs real-world validation |
| **Feedback** | Human annotation → rules auto-optimize | Requires sufficient feedback data to be effective |

---

## Disclaimer & Risk Notice

### External Resources & Third-Party Services

News Sentry collects and processes information from external sources:

| Category | Description |
|----------|-------------|
| **News sources** | Content collected via RSS/API is copyrighted by original publishers; this project does not own or guarantee its accuracy |
| **AI services** | Judgments from OpenAI / Anthropic / DeepSeek are AI-generated and may contain hallucinations or bias |
| **Social platforms** | Twitter/Facebook content is subject to their respective terms of service |
| **Push channels** | Feishu/Email/Telegram services are operated by third parties; availability is not controlled by this project |

> **Compliance-by-design collection**: News Sentry collects news using **index links** as the primary method — recording metadata (title, URL, source, publish time) and AI-generated summaries rather than full-text copies. Every record retains the complete original URL, ensuring sources are **transparent and traceable**, minimizing copyright risk while preserving informational value.

This project **makes no warranty regarding the availability, accuracy, or compliance of external services**.

### Compliance Requirements

```
┌──────────────────────────────────────────────────────────────┐
│                    ⚠️  Read Before Use                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Comply with local laws                                   │
│     → Different jurisdictions have different regulations on  │
│       news collection, data storage, and personal information│
│     → Verify your use case complies with applicable laws     │
│                                                              │
│  2. Respect source rights                                    │
│     → RSS/API collection must respect robots.txt and ToS      │
│     → Do not use for mass scraping, plagiarism, or copyright │
│       infringement                                           │
│                                                              │
│  3. AI judgment ≠ human decision                             │
│     → AI scores are advisory only; important decisions must  │
│       be verified by humans                                  │
│     → Never use AI judgment as the sole basis for publishing │
│       or distribution decisions                              │
│                                                              │
│  4. Prohibited uses                                          │
│     → Must not be used for disinformation, opinion           │
│       manipulation, individual surveillance, or illegal      │
│       intelligence activities                                │
│     → Must not violate human rights, privacy rights, or      │
│       data protection regulations                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Risk notices:**
- Collected news content may contain errors or misinformation; this project is not responsible for content accuracy
- AI judgment results may vary due to model version or prompt changes
- Some sources may become unavailable due to website changes; health status is tracked but not guaranteed real-time
- This project is provided "as is" without any express or implied warranty

### License

Copyright 2026 XucroYuri. Licensed under the [Apache License 2.0](LICENSE).
