# News Sentry

**Framework-neutral Agent Skill Pack for continuous news monitoring.**

First reference target: **Italy** (Italian → Chinese, Breaking News focus).
Core kernel and contracts are reusable for any country, region, or domain.

> **License**: [Apache 2.0](LICENSE)
> **Language**: [简体中文版](README_zh.md)

---

## Table of Contents

- [What is News Sentry](#what-is-news-sentry)
- [Quick Start](#quick-start)
- [Pipeline Overview](#pipeline-overview)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Development](#development)
- [Deployment](#deployment)
- [Project Status](#project-status)
- [Troubleshooting](#troubleshooting)

---

## What is News Sentry

News Sentry is a **continuous news monitoring platform** designed to run as an Agent Skill Pack on Hermes Agent or OpenClaw runtime carriers. It automates the full news intelligence lifecycle:

```
RSS/API Sources → Collect → Filter → Judge → Output (Markdown)
```

**Core principles:**
- **Framework-neutral** — runs on Hermes Agent, OpenClaw, or standalone CLI
- **Configuration-driven** — add new countries without writing code
- **No dedicated frontend** — visualization via Obsidian Markdown + push notifications (Feishu/email)
- **v1 no auto-publish** — output stops at drafts/reviewed, no automatic external publishing
- **Bilingual pipeline** — native Italian → Chinese translation support

**Reference use case — Italy Breaking News monitoring:**
Monitors 8 Italian news sources (ANSA, Corriere della Sera, la Repubblica, TGCOM24, il Fatto Quotidiano, La Stampa, Il Messaggero, ANSA English) with 91 Italian keywords covering politics, economics, crime, EU relations, China-Italy relations, immigration, energy, and judiciary topics.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. Install
bash install.sh --dev

# 3. Dry-run — verify configuration
source .venv/bin/activate
make dry-run

# 4. Collect news from Italian sources
make run

# 5. Run full pipeline: collect → filter → judge → output
make run-all

# 6. Check data statistics
make stats

# 7. Run tests and lint
make check
```

### Two Profiles

| | `local-workstation` | `cloud-vps` |
|---|---|---|
| **Purpose** | Local dev / testing / manual review | 24/7 production monitoring |
| **Trigger** | CLI manual / Claude Cowork fallback | Hermes Agent cron / gateway |
| **Timeout** | 10 minutes | 30 minutes |
| **Network** | Permissive (local debug) | Sandbox-restricted |
| **Recommended for** | First deployment validation | Long-term production |

---

## Pipeline Overview

```
                    ┌──────────────┐
  RSS Feeds ──────→ │   COLLECT    │ ──→ raw/*.md
  API Endpoints ──→ │  (8 sources) │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   FILTER     │ ──→ evaluated/*.md  (keyword matching + classification)
                    │ (91 keywords)│ ──→ archive/*.md     (rejected)
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │    JUDGE     │ ──→ evaluated/*.md  (scoring + recommendations)
                    │ (rules-based)│
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   OUTPUT     │ ──→ drafts/*.md      (Markdown reports)
                    │  (Markdown)  │
                    └──────────────┘
```

**Pipeline stages:**

| Stage | Input | Output | Description |
|-------|-------|--------|-------------|
| **collect** | RSS/API configs | `raw/*.md` | Fetch and parse news from configured sources |
| **filter** | `raw/*.md` | `evaluated/*.md` | Keyword matching (91 keywords, word-boundary regex), L0-L2 classification, dedup |
| **judge** | `evaluated/*.md` | `evaluated/*.md` | News value scoring, China relevance, recommendation (publish/review/archive/discard) |
| **output** | `evaluated/*.md` | `drafts/*.md` | Generate structured Markdown reports |

**Each run produces:**
- A **RunLog** JSON with timing, counts, errors per phase
- **Heartbeat file** for health monitoring
- **Source health** tracking (consecutive failures, success rate)
- **Automatic log rotation** (keeps last 100 runs)

---

## Installation

### Prerequisites

| Dependency | Min Version | Purpose |
|------------|-------------|---------|
| **Python** | 3.11+ | Runtime |
| **pip** | bundled | Package management |
| **git** | any | Version control |

**Zero native dependencies** — all Python packages are pure Python wheels. No `libxml2`, `libxslt`, or C extension toolchain required.

### Install Script

```bash
# Development install (includes pytest, ruff, mypy)
bash install.sh --dev

# Production install (core dependencies only)
bash install.sh
```

The script creates a `.venv` virtual environment and installs all dependencies. A `.env` file is auto-created from `.env.example`.

### Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # development
pip install -e .                 # production only
pip install -e ".[proxy]"        # with SOCKS5 proxy support
```

### Dependencies

**Core** (`pyproject.toml`):
- `pydantic>=2.0` — data models
- `pyyaml>=6.0` — config parsing
- `httpx>=0.27` — HTTP client
- `feedparser>=6.0` — RSS/Atom parsing
- `click>=8.1` — CLI framework

**Dev extras** `[dev]`:
- `pytest>=8.0`, `pytest-asyncio`, `pytest-cov` — testing
- `mypy>=1.10` — static type checking (strict mode)
- `ruff>=0.4` — linting
- `jsonschema>=4.21` — JSON Schema validation

**Proxy extras** `[proxy]`:
- `httpx[socks]>=0.27` — SOCKS5 proxy support

---

## Configuration

### Directory Structure

```
config/
├── targets/           # Monitoring target definitions
│   ├── italy.yaml     # Italy target (language, sources, classification axes)
│   └── _template.yaml # Template for new targets
├── sources/italy/     # Source channel configs (one YAML per source)
│   ├── ansa.yaml      # enabled
│   ├── corriere.yaml  # enabled
│   └── ...            # 8 enabled, 7 disabled total
├── filters/italy/     # Keyword filter rules
│   └── default.yaml   # 91 Italian keywords with weights
├── classification/    # L0-L2 classification rules
│   └── rules-v1.yaml
├── profiles/          # Deployment profiles
│   ├── local-workstation.yaml
│   └── cloud-vps.yaml
├── sandbox/           # Sandbox security policies
├── runtime/           # Runtime carrier configs
├── provider/          # AI provider routing (Phase 5)
├── output/            # Output destinations
└── toolmanifest/      # Tool manifest registry
    └── opencli-baseline.yaml  # 12 OpenCLI tools
```

### Adding a New Monitoring Target

```bash
# 1. Create target config from template
cp config/targets/_template.yaml config/targets/{country}.yaml

# 2. Create source configs directory
mkdir config/sources/{country}/
# Add source YAML files...

# 3. Create filter rules
mkdir config/filters/{country}/
# Add keyword YAML...

# 4. Run — no code changes needed
make run TARGET={country}
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEWSSENTRY_PROFILE` | No | `local-workstation` | Deployment profile ID |
| `NEWSSENTRY_DATA_DIR` | No | `./data` | Data output root directory |
| `NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR` | No | `false` | Allow data dir outside project root (set `1`/`true`) |
| `DEEPSEEK_API_KEY` | Phase 5 | — | DeepSeek API key |
| `OPENAI_API_KEY` | Phase 5 | — | OpenAI API key |
| `FEISHU_WEBHOOK_URL` | No | — | Feishu push notification webhook |
| `all_proxy` | No | — | SOCKS5 proxy (e.g., `socks5://127.0.0.1:1080`) |

Full list in [`.env.example`](.env.example).

---

## Usage Guide

### CLI Commands

```bash
# Run a single stage
python -m news_sentry.cli run --target italy --stage collect
python -m news_sentry.cli run --target italy --stage filter
python -m news_sentry.cli run --target italy --stage judge
python -m news_sentry.cli run --target italy --stage output

# Run full pipeline
python -m news_sentry.cli run --target italy --stage all

# Dry-run (validate config without execution)
python -m news_sentry.cli run --target italy --stage collect --dry-run

# Use cloud profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps

# Specify run ID (otherwise auto-generated)
python -m news_sentry.cli run --target italy --stage all --run-id my-run-001

# Validate a config file
python -m news_sentry.cli validate --config config/targets/italy.yaml

# List available skills
python -m news_sentry.cli skill list

# List available tools
python -m news_sentry.cli tool list

# Health check
python -m news_sentry.cli doctor
python -m news_sentry.cli doctor --json
```

### Makefile Shortcuts

```bash
make dry-run              # Validate config
make run                  # Collect stage
make run-filter           # Filter stage
make run-judge            # Judge stage
make run-output           # Output stage
make run-all              # Full pipeline
make stats                # Data directory statistics
make latest-log           # View latest run log
make test                 # Run tests
make lint                 # ruff + mypy
make check                # lint + test
make fmt                  # Auto-fix code style
make clean                # Clean build artifacts
```

### Source Management

Sources are configured in `config/sources/italy/*.yaml`. Each source:

```yaml
source_id: ansa
type: rss                       # rss | api | opencli
url: "https://www.ansa.it/..."
enabled: true
credibility_base: 0.9           # 0.0–1.0
max_items_per_run: 50
timeout_seconds: 30
```

**Currently active Italian sources (8):**

| Source | Language | Type | Status |
|--------|----------|------|--------|
| ANSA | it | rss | active |
| ANSA English | en | rss | active |
| Corriere della Sera | it | rss | intermittent SSL |
| la Repubblica | it | rss | active |
| TGCOM24 | it | rss | active |
| il Fatto Quotidiano | it | rss | active |
| La Stampa | it | rss | active |
| Il Messaggero | it | rss | active |

**Disabled sources (7):** AGI, Rai News, Il Sole 24 Ore, The Local Italy, Sky TG24, FAO RSS — RSS feeds permanently unavailable.

### Keyword Filtering

The filter stage uses **word-boundary regex** matching against 91 Italian keywords. Keywords are configured in `config/filters/italy/default.yaml` with weights:

```yaml
keywords:
  - keyword: Cina
    weight: 1.0
    tag: china_relations
  - keyword: Putin
    weight: 0.9
    tag: international
```

Each event's `news_value_score` is calculated as: `sum(keyword_weight × 100)`. Events must score ≥ 40 to pass the filter.

### Data Directory

```
data/italy/
├── raw/           # Collected events (Markdown with YAML frontmatter)
├── evaluated/     # Filtered + judged events
├── drafts/        # Output Markdown reports (v1: no auto-publish)
├── reviewed/      # Human-review candidates (Phase 5+)
├── published/     # Approved archive
├── archive/       # Rejected / duplicate / low-value
├── memory/        # known_item_ids, source_health, cursors, provider_stats
│   ├── known_item_ids.yaml
│   ├── source_health.yaml
│   └── cursors.yaml
└── logs/          # Run logs + heartbeat
    └── .heartbeat-hermes.json
```

---

## Architecture

```
src/news_sentry/
├── core/              # Framework-neutral kernel
│   ├── config.py      # ConfigLoader with JSON Schema validation
│   ├── run.py         # bounded_run lifecycle manager
│   ├── sandbox.py     # SandboxEnforcer (network/file/command policies)
│   ├── file_writer.py # File event writer (stage → directory mapping)
│   ├── memory.py      # Known IDs, source health, cursors, provider stats
│   └── run_log.py     # RunLog generation (phases, errors, summary)
├── skills/            # Pipeline skills
│   ├── collect/
│   │   ├── rss_collector.py    # RSS/Atom feed collector
│   │   ├── api_collector.py    # JSON API collector
│   │   └── opencli_collector.py # OpenCLI-based collector
│   ├── filter/
│   │   ├── rules_filter.py     # Keyword-based rules filter
│   │   └── classifier_rules.py # L0-L2 classification engine
│   ├── judge/
│   │   ├── rules_judge.py      # Rules-based scoring engine
│   │   └── judge_skill.py      # AI-powered judge (Phase 5 stub)
│   └── output/
│       └── markdown_writer.py  # Markdown report generator
├── adapters/          # Integration bridges
│   ├── runtime/       # Hermes Agent / OpenClaw adapters (Phase 2 stubs)
│   ├── tools/         # OpenCLI tool adapter
│   └── providers/     # AI provider adapters (Phase 5 stubs)
├── models/            # Pydantic v2 data models
│   ├── newsevent.py   # NewsEvent — core data exchange object
│   ├── pipeline_context.py
│   └── manifests.py   # Tool/Skill manifest models
└── cli/               # Click CLI entry points
    └── __init__.py    # run, validate, skill, tool, doctor commands
```

### Key Design Decisions

- **`NewsEvent`** is the single cross-agent data object (no competing schemas)
- **0–100 scores** for news_value_score, china_relevance, confidence (sentiment_score: -1.0 to 1.0)
- **Deterministic IDs**: `ne-{target_id}-{source_id}-{yyyymmdd}-{hash8}`
- **Pipeline stages**: `collected → filtered → judged → outputted`
- **v1 no auto-publish**: output stops at `drafts/`
- **Configuration over code**: all Italy-specific params in `config/`, not in `src/`
- **External projects: install only** — no vendoring, forking, or git submodules

### Robustness Features

| Feature | Implementation |
|---------|---------------|
| Atomic file writes | `.tmp` → `os.replace()` in Memory module |
| Log rotation | Auto-prune to 100 most recent run logs |
| Memory retention | `prune_old_ids(ttl_days=30)` for known_item_ids |
| Source health degradation | Auto-pause sources with ≥5 consecutive failures or <30% success rate |
| Sandbox enforcement | SSRF protection, network host whitelist, command allowlists |
| Concurrent safety | Threading lock on memory YAML I/O; run_id-based isolation |
| Error resilience | `on_failure=log_and_continue` — failed sources don't block downstream stages |
| Disabled source skipping | `enabled: false` sources are skipped automatically |

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Language** | Python 3.11+ | Strict mypy, ruff lint |
| **Data models** | Pydantic v2 | Runtime validation + serialization |
| **CLI** | Click 8.1+ | `news-sentry` console script |
| **HTTP** | httpx 0.27+ | RSS/API fetching, SOCKS5 proxy |
| **RSS** | feedparser 6.0+ | RSS/Atom feed parsing |
| **Config** | PyYAML 6.0+ | All runtime configuration |
| **Schema validation** | jsonschema 4.21+ | JSON Schema 2020-12 |
| **Testing** | pytest 8.0+ | 383 tests, 89% coverage |
| **Linting** | ruff 0.4+ | Zero-tolerance |
| **Type checking** | mypy 1.10+ | strict mode, 38 source files |
| **CI/CD** | GitHub Actions | Python 3.11 + 3.12 matrix |
| **Container** | Docker (python:3.12-slim) | Volume-mounted data dir |
| **Storage** | Markdown + YAML frontmatter | Obsidian-compatible |

---

## Development

### Setup

```bash
bash install.sh --dev
source .venv/bin/activate
```

### Code Quality

```bash
# Run all checks
make check

# Individual checks
make test        # pytest (383 tests)
make lint        # ruff + mypy
make fmt         # auto-fix style issues
```

**Quality gates (all must pass before commit):**
- `ruff check src/news_sentry/` — All checks passed
- `mypy src/news_sentry/` — Success: no issues found
- `pytest tests/` — All passed, 0 failed

### Project Structure

```
.
├── docs/              # Architecture docs, ADRs, Phase SPECs, SOPs
│   ├── spec/          # Phase specification documents
│   ├── adr/           # Architecture Decision Records (ADR-0001 ~ 0016)
│   ├── testing/       # Test plans + verification reports
│   └── brainstorming/ # Design discussions & references
├── schemas/           # 13 JSON Schema 2020-12 contract files
├── config/            # All runtime configuration
├── src/news_sentry/   # Python package
├── tests/
│   ├── unit/          # Unit tests (per module)
│   └── integration/   # End-to-end pipeline tests
├── data/              # Runtime data (gitignored)
├── pyproject.toml
├── Dockerfile
├── Makefile
└── install.sh
```

### Commit Convention

All commit messages in **simplified Chinese**, format: `<Phase/Module>: <brief description>`

```
Phase 3 Kernel: 实现 ConfigLoader 配置加载与 schema 校验
Fix: _run_collect 跳过 enabled=false 的源
```

### Key Documentation

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | Agent instruction baseline + architecture authority |
| [docs/contracts-canonical.md](docs/contracts-canonical.md) | Canonical specification (field naming, scoring, directory mapping) |
| [docs/development-plan.md](docs/development-plan.md) | 7-phase development plan |
| [docs/adr/](docs/adr/) | Architecture Decision Records (ADR-0001 to 0016) |
| [docs/spec/](docs/spec/) | Phase SPEC index + component matrix |
| [docs/testing/](docs/testing/) | Test plans + Hermes Agent verification |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guide |

---

## Deployment

### Docker

```bash
# Build
docker build -t news-sentry .

# Run collection
docker run -v $(pwd)/data:/data news-sentry run --target italy --stage collect

# Run full pipeline
docker run -v $(pwd)/data:/data news-sentry run --target italy --stage all
```

The Docker image uses `python:3.12-slim`, mounts `/data` as a volume, and defaults to `cloud-vps` profile.

### Hermes Agent (Recommended for Production)

News Sentry is designed to run as a Skill Pack on **Hermes Agent**. The Hermes Agent handles:
- Cron-based scheduling
- Gateway-triggered execution
- Heartbeat monitoring
- Run lifecycle management

The `HermesAdapter` (Phase 2) provides the bridge layer. See `config/runtime/hermes.yaml`.

### OpenClaw (Ecosystem Compatibility)

OpenClaw Skill runtime provides an alternative carrier. The `OpenClawAdapter` (Phase 2 stub) handles:
- Skill discovery and registration
- ClawHub ecosystem compatibility
- Run status queries

### Standalone CLI / Cron

For environments without Hermes Agent:

```bash
# cron example — run every 15 minutes
*/15 * * * * cd /path/to/NewsSentry && .venv/bin/python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

---

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Contract Stabilization | Done | ADR-0001~0016, 13 JSON Schemas, canonical contracts |
| 2 — Runtime Carrier Alignment | Done | Profiles, RuntimeHostAdapter protocol, Docker |
| 3 — Kernel MVP | Done | bounded_run, RSS/API collect, filter, judge, output |
| 4 — Tool/Skill Registry | Done | OpenCLI baseline, registries, APICollector, CLI skill/tool commands |
| 5 — AI Provider Routing | Done | Multi-provider router, judge/translate/classify routes, cost budget |
| 6 — Sandbox Hardening + KOL | Done | Full sandbox policy, session profiles, KOL experiment channel |
| 7 — Multi-target Expansion | Done | Second target `china-watch-en`, hardcoded-target scan, target comparison |

Run `make progress` for local vs remote Git sync and phase status.

### Current Metrics

| Metric | Value |
|--------|-------|
| Tests | 878 passed, 0 failed |
| Coverage | 94% |
| Lint (ruff) | All checks passed |
| Type (mypy) | 38 source files, no issues |
| Active targets | 2 (`italy`, `china-watch-en`) |
| RSS sources | 14 (Italy), 5 (China Watch EN) |
| Pipeline stages | 4 (collect, filter, judge, output) |

---

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| `ModuleNotFoundError: news_sentry` | venv not activated or not installed | `bash install.sh --dev` |
| `corriere: SSL: UNEXPECTED_EOF` | Corriere della Sera intermittent SSL issue | Normal — other sources unaffected, auto-retried next run |
| `agi: 404 / fao-rss: 404` | RSS feeds permanently unavailable | These sources are `enabled: false` — no action needed |
| `No module named 'news_sentry.cli'` | Working directory not at project root | `cd /path/to/NewsSentry` |
| Filter produces 0 events | No new news matching keywords (all known items deduplicated) | Wait for fresh news; check `config/filters/italy/default.yaml` |
| Low coverage in adapters/ | Phase 2/5 stubs not tested | Expected — these are design-intended stubs |

---

## License

Copyright 2026 XucroYuri

Licensed under the [Apache License 2.0](LICENSE) — free to use, modify, and distribute with patent grant and limitation of liability.
