<p align="center">
  <img src="https://img.shields.io/badge/version-1.9.1-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>Open-source AI news intelligence and OSINT monitoring platform</strong><br>
  Multilingual news and social media collection → source health → canonical event graph → professional research workflows
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#why-news-sentry">Why</a> ·
  <a href="#core-capabilities">Capabilities</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#use-cases">Use Cases</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README_en.md">English</a>
</p>

---

## What is News Sentry?

News Sentry is a local-first, open-source system for continuous **AI news intelligence**, **OSINT monitoring**, and professional research workflows.

It collects multilingual news, RSS feeds, API sources, social media signals, and public web sources, then helps researchers turn fragmented mentions into structured events, source health signals, alerts, Markdown briefs, and a canonical event graph.

It is designed for people who need more than a feed reader:

- journalists and editors tracking countries, institutions, policies, industries, and breaking events;
- OSINT researchers validating public sources across languages and regions;
- analysts monitoring public opinion, geopolitical risk, industrial policy, and media narratives;
- developers building local or cloud news intelligence infrastructure.

## Why News Sentry?

Most monitoring tools stop at collecting links. News Sentry is built around the full intelligence loop:

```text
collect → filter → judge → output → review → canonical graph → research artifact
```

The important distinction is that a news article is treated as an **event mention**, not the fact itself. Multiple reports can be projected into a canonical event graph, while human-in-the-loop research actions are stored as review artifacts instead of silently overwriting facts.

## Core Capabilities

| Capability | What it means |
| --- | --- |
| Multilingual news monitoring | Configured targets for Italy, Japan, Germany, France, and English China-watch coverage |
| RSS/API/OpenCLI collection | Zero-token collection from feeds, APIs, websites, and optional tool adapters |
| Source health | Track source availability, runtime diagnostics, stale feeds, and source lifecycle |
| AI judgment | Score news value, China relevance, sentiment, and confidence with rule-first routing and AI upgrade |
| Canonical event graph | Separate real-world events from source mentions, relations, taxonomy, and entities |
| Professional research workflows | Review queues, annotations, merge/split decisions, and research artifacts |
| Local-first deployment | Run as CLI, FastAPI web UI, desktop wrapper, Docker, or future cloud worker |
| Human-in-the-loop design | AI assists filtering and analysis while final research judgment stays auditable |

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
# Edit .env and add OPENROUTER_API_KEY

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

## Architecture

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
| **Collect** | RSS/API/OpenCLI configs | `raw/` | Fetch from configured RSS/API/OpenCLI sources, zero token |
| **Filter** | `raw/` | `evaluated/` + `archive/` | Keyword scoring + L0-L3 classification + dedup |
| **Judge** | `evaluated/` | `evaluated/` | AI news value scoring + China-topic relevance |
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

### External Project Dependencies

News Sentry is not a fully self-contained project — some capabilities rely on external projects:

```
┌───────────────────────────────────────────────────────────────────┐
│                        News Sentry                                │
│              (Core Pipeline + Config + Data Models)               │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ Hermes Agent │    │   OpenClaw   │    │     OpenCLI      │    │
│  │ Runtime Host │    │ Runtime Host │    │   CLI Tool Bridge│    │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘    │
│         │                   │                     │              │
│    Cron scheduling    Skill registration    Social/web collection│
│    Heartbeat          Ecosystem compat      Sources without RSS  │
│    Lifecycle mgmt     Status queries        Browser Bridge       │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

| Project | Role | Required? | Description |
|---------|------|-----------|-------------|
| **[OpenCLI](https://github.com/jackwener/OpenCLI)** | CLI tool bridge | Optional | Converts websites/social media into deterministic CLI commands for sources without RSS (Twitter, Reddit, government sites, etc.). Install: `npm install -g @jackwener/opencli` |
| **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** | Runtime host | Optional | Provides cron scheduling, heartbeat monitoring, lifecycle management. Recommended for production; dev can use standalone CLI |
| **OpenClaw** | Runtime host | Optional | Alternative Skill runtime with registration and ecosystem compatibility. Currently a stub adapter |

**Integration principles (ADR-0008):**
- **Install, not vendor** — External projects installed via system package managers, no fork/submodule/vendor
- **Wrap, not rewrite** — Call external tools via `ToolManifest` wrappers, never duplicate logic
- **Graceful degradation** — Runs independently without external projects (RSS/API collection + CLI mode only)

> Full integration strategy: [docs/external-integration-strategy.md](docs/external-integration-strategy.md)

### Configured Targets

| Target | Language Pair | Sources | Keyword Rules | Description |
|--------|--------------|---------|---------------|-------------|
| 🇮🇹 **italy** | it→zh | 19+ | 100+ | Italy full-spectrum news |
| 🇬🇧 **china-watch-en** | en→zh | 5 | 30+ | China-related coverage from English media (SCMP/Reuters/BBC/Guardian/NYT) |
| 🇯🇵 **japan** | ja→zh | 19 | 59 | Japan full-spectrum news |
| 🇩🇪 **germany** | de→zh | 22 | 46 | Germany full-spectrum news |
| 🇫🇷 **france** | fr→zh | 21 | 45 | France full-spectrum news |

Add a new country (zero code):

```bash
cp config/targets/_template.yaml config/targets/{country}.yaml
mkdir -p config/sources/{country}/rss config/filters/{country}
make run TARGET={country}
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
| `OPENROUTER_API_KEY` | Required for AI enhancement | — | OpenRouter API Key (default provider) |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenRouter/OpenAI-compatible Base URL |
| `OPENAI_API_KEY` | No | — | OpenAI API Key (fallback) |
| `ANTHROPIC_API_KEY` | No | — | Anthropic API Key (fallback) |
| `DEEPSEEK_API_KEY` | No | — | DeepSeek API Key (legacy compatibility) |
| `NEWSSENTRY_API_KEY` | No | — | API gateway auth key |
| `NEWSSENTRY_PROFILE` | No | `local-workstation` | Deployment profile |
| `HTTPS_PROXY` | No | — | Proxy (e.g. `socks5://127.0.0.1:1080`) |

---

## Deployment

### Docker (Recommended)

```bash
docker build -t news-sentry .
docker run -d \
  --name news-sentry \
  -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
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
| Storage | Markdown/YAML + SQLite (aiosqlite) | File protocol plus async index/storage |
| Testing | pytest 8.0+ | Broad regression suite with coverage tracking |

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
- `pytest` — project test suite passes

---

## Use Cases

- Continuous country and region monitoring for newsrooms and research teams.
- OSINT source tracking across public websites, RSS feeds, social platforms, and APIs.
- Public opinion and media narrative monitoring for policy, industry, and geopolitical research.
- Source health and coverage gap analysis for multilingual monitoring operations.
- Local research workbench for reviewing, annotating, merging, splitting, and briefing canonical events.

## Roadmap

News Sentry is evolving from a local monitoring engine into a global news intelligence platform.

Near-term priorities:

- reliability hardening for run batch semantics, alert history, and source inventory;
- shadow canonical data spine for canonical events, mentions, relations, taxonomy, and research artifacts;
- professional research workflow MVP with human review, merge/split, annotations, and briefs;
- local lightweight client for user-selected scopes and offline research;
- future semi-centralized public collection nodes for global source coverage.

See:

- [Global intelligence platform direction](docs/superpowers/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md)
- [Shadow canonical data spine](docs/superpowers/specs/2026-05-30-shadow-canonical-data-spine-design.md)
- [Professional research workflow MVP](docs/superpowers/specs/2026-05-30-professional-research-workflow-mvp-design.md)

## Contributing

Contributions are welcome, especially in these areas:

- new country, region, language, and source configurations;
- collector adapters for public websites, RSS feeds, APIs, and social sources;
- canonical event graph, taxonomy, source health, and research workflow improvements;
- documentation, deployment guides, and reproducible monitoring examples.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [docs/contracts-canonical.md](docs/contracts-canonical.md), and [docs/architecture.md](docs/architecture.md).

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System architecture, data flow, directory structure |
| [API Reference](docs/api-reference.md) | REST API endpoints, auth, Webhook |
| [Deployment Guide](docs/deployment-guide.md) | Docker / VPS / API / systemd |
| [Security Audit](docs/security-audit-report.md) | OWASP Top 10 audit report |
| [External Integration Strategy](docs/external-integration-strategy.md) | OpenCLI/Hermes/OpenClaw integration & version constraints |
| [Contracts](docs/contracts-canonical.md) | Field naming, scoring, directory mapping |

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

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=XucroYuri/NewsSentry&type=Date)](https://star-history.com/#XucroYuri/NewsSentry&Date)
