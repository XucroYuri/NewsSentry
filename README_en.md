<p align="center">
  <img src="https://raw.githubusercontent.com/XucroYuri/NewsSentry/main/src/news_sentry/static/icons/icon-192.svg" width="96" height="96" alt="News Sentry" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>AI-Powered Multilingual News Intelligence Platform</strong><br>
  Real-time global source tracking · Intelligent event assessment · Decision briefings on autopilot<br>
  3,020 tests · 87% coverage · mypy strict · ruff zero
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0--rc2-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
  <img src="https://img.shields.io/badge/tests-3020%20passed-brightgreen.svg" alt="tests" />
  <img src="https://img.shields.io/badge/coverage-87%25-9cf.svg" alt="coverage" />
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#why-news-sentry">Why</a> ·
  <a href="#capabilities">Capabilities</a> ·
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

News Sentry is a local-first, open-source system for continuous **AI news intelligence** and **OSINT monitoring**. It ingests multilingual news from RSS feeds, APIs, Reddit, and Hacker News, then structures the fragments into assessed events, source health dashboards, alerts, Markdown briefings, and a canonical event graph.

It is not an RSS reader or a one-off scraper. It is news intelligence infrastructure built for long-running, human-in-the-loop research workflows.

## Why News Sentry?

Most monitoring tools stop at collecting links. News Sentry closes the intelligence loop:

```text
Collect → Filter → Judge → Output → Review → canonical graph → research artifact
```

A news article is an **event mention**, not the truth. Multiple outlets, languages, and platforms can be merged into a canonical event. Human review, annotation, merging, splitting, and research notes are preserved as artifacts — the ground truth layer stays clean.

## Capabilities

| Capability | Description |
| --- | --- |
| Multilingual monitoring | Targets configured for Italy, Japan, Germany, France, and English-language China coverage |
| RSS / API / Reddit / HN | Zero-token collection from feeds, APIs, and community platforms |
| Source health | Track availability, diagnose failures, monitor stale feeds and lifecycle |
| AI assessment | Rules-first, AI-assisted scoring for news value, China relevance, sentiment, and confidence |
| Canonical event graph | Separate real-world events from mentions, relations, taxonomy, and entities |
| Research workflow | Review queues, human annotation, merge/split decisions, research artifacts |
| Local-first deployment | CLI, FastAPI Web UI, desktop wrapper, Docker, and cloud workers |
| Human in the loop | AI filters and analyzes; critical judgments preserve auditable human intervention |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/XucroYuri/NewsSentry.git
cd NewsSentry

# 2. Install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[api,proxy]"

# 3. Configure AI provider keys (at least one)
cp .env.example .env
# Edit .env with GEMINI_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY

# 4. Health check
./run.sh doctor --target italy

# 5. Run the full pipeline
./run.sh run --target italy --stage all

# 6. Launch the admin panel (optional)
./run.sh serve --target italy
# Open http://localhost:8000/admin/
```

> **First run takes 1–2 minutes**: collect 19+ RSS sources for Italy → filter with 100+ keywords → AI assessment → Markdown output.
> **Admin panel**: full target workbench, source management, review queues, and system operations.

---

## Installation

### Prerequisites

| Dependency | Minimum | Purpose |
|------|---------|------|
| Python | 3.11+ | Runtime |
| pip | bundled with Python | Package management |
| git | any | Version control |

> **Zero native dependencies** — all Python packages are pure wheels, no C toolchain required.

### Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # Development (pytest, ruff, mypy)
pip install -e .           # Production
pip install -e ".[proxy]"  # SOCKS5 proxy support
pip install -e ".[api]"    # FastAPI REST API server
```

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                       CLI / API Entry                          │
│      python -m news_sentry.cli        FastAPI /api/v1         │
└─────────────────────┬─────────────────────────┬───────────────┘
                      │                         │
┌─────────────────────▼─────────────────────────▼───────────────┐
│                   bounded_run Runtime                          │
│              ConfigLoader + RunLog + Memory                    │
└─────────┬───────────────────────────────────────┬─────────────┘
          │                                       │
 ┌────────▼────────┐                    ┌─────────▼──────────┐
 │    COLLECT       │                    │    FILTER          │
 │ RSS · API ·      │──────────────────→ │ 100+ keyword       │
 │ Reddit · HN      │                    │ scoring            │
 │ Zero token cost  │                    │ L0-L3 taxonomy     │
 └─────────────────┘                    └─────────┬──────────┘
                                                  │
                                        ┌─────────▼──────────┐
                                        │     JUDGE          │
                                        │ RulesJudge         │
                                        │ rule → AI escalate │
                                        └─────────┬──────────┘
                                                  │
 ┌───────────────────────┐              ┌─────────▼──────────┐
 │   Alerts              │◀─────────────│    OUTPUT          │
 │ Feishu · Email · TG   │              │ Markdown reports   │
 └───────────────────────┘              └─────────┬──────────┘
                                                  │
                                       ┌──────────▼─────────┐
                                       │    FEEDBACK        │
                                       │ Human annotation   │
                                       │ → rule optimization│
                                       └────────────────────┘
```

### Pipeline Stages

| Stage | Input | Output | Description |
|------|------|------|------|
| **Collect** | RSS/API/Reddit/HN config | `raw/` | Multi-target source matrix, zero token cost |
| **Filter** | `raw/` | `evaluated/` + `archive/` | Keyword scoring + L0-L3 classification + dedup |
| **Judge** | `evaluated/` | `evaluated/` | AI news value scoring + China relevance |
| **Output** | `evaluated/` | `drafts/` | Markdown reports + multi-channel alerts |

---

## Configuration

News Sentry is fully YAML-configuration driven. Add new sources, countries, and classification rules without writing code.

- **Entry point**: `config/profiles/` → `config/targets/` → `config/sources/`
- **Schema validation**: all YAML files carry `# Schema:` headers pointing to JSON Schema; validated on load
- **Inheritance**: classification rules support `extends` chaining

---

## Monitored Targets

| Target | Language Pair | Sources | Keywords | Description |
|--------|-------------|---------|----------|------|
| 🇮🇹 **italy** | it→zh | 19+ | 100+ | Full-dimensional Italy news |
| 🇬🇧 **china-watch-en** | en→zh | 5 | 30+ | English mainstream media China coverage (SCMP/Reuters/BBC/Guardian/NYT) |
| 🇯🇵 **japan** | ja→zh | 19 | 59 | Full-dimensional Japan news |
| 🇩🇪 **germany** | de→zh | 22 | 46 | Full-dimensional Germany news |
| 🇫🇷 **france** | fr→zh | 21 | 45 | Full-dimensional France news |

Add a new country (zero code):

```bash
cp config/targets/_template.yaml config/targets/{country}.yaml
mkdir -p config/sources/{country}/rss config/filters/{country}
./run.sh run --target {country} --stage all
```

---

## Usage

### CLI Commands

```bash
# Single-stage runs
python -m news_sentry.cli run --target italy --stage collect    # Collect only
python -m news_sentry.cli run --target italy --stage filter     # Filter only
python -m news_sentry.cli run --target italy --stage judge      # Judge only
python -m news_sentry.cli run --target italy --stage output     # Output only

# Full pipeline
python -m news_sentry.cli run --target italy --stage all

# Other targets
python -m news_sentry.cli run --target japan --stage all

# Dry run (validate config, skip writes)
python -m news_sentry.cli run --target italy --stage all --dry-run

# Production profile
python -m news_sentry.cli run --target italy --stage all --profile cloud-vps

# Background service
news-sentry serve --target italy
news-sentry serve --port 8080 --interval 30
news-sentry serve --no-browser
news-sentry stop

# System diagnostics
python -m news_sentry.cli doctor --target italy
```

### ./run.sh shortcuts

```bash
./run.sh doctor --target italy
./run.sh run --target italy --stage all
./run.sh run --target italy --stage collect
./run.sh serve --target italy
./run.sh --help
```

### Environment Variables

| Variable | Required | Default | Description |
|------|------|--------|------|
| `GEMINI_API_KEY` | AI features need at least one | — | Gemini API Key (primary) |
| `DEEPSEEK_API_KEY` | No | — | DeepSeek API Key (fallback 1) |
| `GROQ_API_KEY` | No | — | Groq API Key (fallback 2) |
| `CLOUDFLARE_ACCOUNT_ID` | No | — | Cloudflare Workers AI (translation safety net) |
| `NEWSSENTRY_API_KEY` | No | — | API gateway auth key |
| `NEWSSENTRY_PROFILE` | No | `local-workstation` | Deployment profile |
| `HTTPS_PROXY` | No | — | Proxy (e.g. `socks5://127.0.0.1:1080`) |

---

## Deployment

### Docker Compose (recommended)

```bash
export GEMINI_API_KEY=xxx
export DEEPSEEK_API_KEY=sk-xxx
docker compose up -d
curl http://localhost:8000/api/v1/health
```

### API Server

```bash
pip install -e ".[api,proxy]"
./run.sh serve --target italy
curl http://localhost:8000/api/v1/health
```

### systemd (VPS Production)

Automatically deployed via GitHub Actions on push to `main`. See `.github/workflows/deploy.yml`.

### Cron (development)

```bash
*/15 * * * * cd /path/to/NewsSentry && .venv/bin/python -m news_sentry.cli run --target italy --stage all --profile cloud-vps
```

---

## Tech Stack

| Layer | Technology | Notes |
|----|------|------|
| Language | Python 3.11+ | strict mypy + ruff |
| Data model | Pydantic v2 | Runtime validation + serialization |
| CLI | Click 8.1+ | `news-sentry` command |
| HTTP | httpx 0.27+ | SOCKS5 proxy support |
| RSS | feedparser 6.0+ | RSS/Atom parsing |
| API | FastAPI 0.110+ | REST API + OpenAPI 3.1 |
| Storage | Markdown/YAML + SQLite (aiosqlite) | File protocol + async indexing |
| Config | PyYAML 6.0+ | Fully YAML-driven |
| Cache | cachetools | LRU cache + TTL |
| Testing | pytest 8.0+ | 3,020 tests + coverage tracking |

---

## Development

```bash
python -m ruff check
python -m mypy src/news_sentry/
python -m pytest tests/ -q
python -m ruff format
python tools/scan_sensitive_data.py
```

**Quality gates:**
- `ruff check` — 0 errors
- `mypy --strict` — 0 issues
- `pytest` — 3,020 tests pass
- `tsc --noEmit` (frontend) — 0 errors

---

## Use Cases

- Newsrooms and research teams tracking countries, regions, policies, industries, and breaking events.
- OSINT researchers verifying sources, report origins, and event chains across languages.
- Analysts monitoring public sentiment, geopolitical risk, industrial policy, and media narratives.
- Operators managing multi-target source health, coverage gaps, and collection diagnostics.
- Local research workbenches for reviewing, annotating, merging, splitting, and exporting canonical event briefs.

## Contributing

Contributions welcome:

- New country, region, language, and source configurations
- Collector adapters for public websites, RSS, APIs, and social media
- Canonical event graph, taxonomy, source health, and research workflow capabilities
- Documentation, deployment guides, and reproducible monitoring examples

Read [CONTRIBUTING.md](CONTRIBUTING.md), [docs/contracts-canonical.md](docs/contracts-canonical.md), and [docs/architecture.md](docs/architecture.md) before contributing.

---

## Docs

| Document | Description |
|------|------|
| [Architecture](docs/architecture.md) | System architecture, data flow, directory structure, deployment topology |
| [Developer Guide](MAKE_GUIDE.md) | Quick start, configuration, troubleshooting |
| [Contracts](docs/contracts-canonical.md) | Field naming, score scales, directory mapping |
| [API Reference](docs/api-reference.md) | REST API endpoints, authentication, webhooks |
| [Security Audit](docs/security-audit-report.md) | OWASP Top 10 audit report |

---

## Disclaimer

News Sentry collects and processes information from third-party sources. AI assessments are generated by models and may contain hallucinations or bias. This project is provided "as is" without warranty. See the full disclaimer in the [Chinese README](README.md#免责声明与风险提示).

### License

Copyright 2026 XucroYuri. Licensed under the [Apache License 2.0](LICENSE).

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=XucroYuri/NewsSentry&type=Date)](https://star-history.com/#XucroYuri/NewsSentry&Date)
