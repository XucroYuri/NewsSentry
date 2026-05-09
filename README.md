# News Sentry

**Framework-neutral Agent Skill Pack for continuous news monitoring.**

First reference target: **Italy** (Italian/English → Chinese). Core kernel and contracts are reusable for any country, region, or domain.

---

## Quick Start

```bash
# Install (dev mode)
pip install -e ".[dev]"

# Run a bounded collection pass for Italy
news-sentry run --target italy --stage collect

# Run full pipeline
news-sentry run --target italy --stage all

# Dry-run (no file writes, no AI calls)
news-sentry run --target italy --stage all --dry-run
```

---

## Project Architecture

```
.
├── docs/           # Architecture docs, ADRs, Phase SPECs, SOPs
│   ├── spec/       # 7 Phase SPEC documents
│   └── adr/        # Architectural Decision Records (0001–0016)
├── schemas/        # 12 JSON Schema 2020-12 contract files
├── config/         # All runtime-configurable parameters
│   ├── targets/    # italy.yaml + _template.yaml (one file per target)
│   ├── sources/    # Per-target source channel configs
│   └── ...
├── src/news_sentry/  # Python 3.11+ package (ADR-0012, ADR-0013)
│   ├── core/       # Framework-neutral kernel
│   ├── skills/     # Collect / Filter / Judge / Output
│   ├── adapters/   # Runtime / Tool / Provider bridges
│   ├── models/     # Pydantic data models (NewsEvent, PipelineContext)
│   └── cli/        # CLI entry point (ADR-0016)
├── italy/          # Runtime data (gitignored, .gitkeep preserved)
└── tests/          # Unit and integration tests
```

---

## Key Documents

| Document | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Canonical agent instructions & architecture source of truth |
| [docs/spec/README.md](docs/spec/README.md) | Phase SPEC index + component matrix |
| [docs/adr/README.md](docs/adr/README.md) | Architectural Decision Record index |
| [docs/contracts-canonical.md](docs/contracts-canonical.md) | Core contract definitions (NewsEvent, SkillManifest, etc.) |
| [docs/architecture-overview.md](docs/architecture-overview.md) | System architecture overview |
| [docs/development-plan.md](docs/development-plan.md) | 7-phase roadmap and workstreams |

---

## Adding a New Monitoring Target

1. Copy `config/targets/_template.yaml` → `config/targets/{country}.yaml`
2. Create `config/sources/{country}/` with source channel configs
3. Create `config/filters/{country}/default.yaml`
4. Run: `news-sentry run --target {country} --stage collect`

No Python code changes required. See [docs/spec/phase-7-multi-target-expansion.md](docs/spec/phase-7-multi-target-expansion.md).

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| 1 — Contract Stabilization | Completed | ADRs 0001–0016, schemas, canonical contracts |
| 2 — Runtime Carrier Alignment | Planned | Hermes/OpenClaw adapter, cloud-vps profile |
| 3 — Kernel MVP | Planned | bounded run, RSS/API collect, filter, judge, output |
| 4 — Tool/Skill Registry + OpenCLI | Planned | ToolManifest registry, OpenCLI adapter |
| 5 — AI Provider Routing | Planned | translate/judge/classify route_id table |
| 6 — Sandbox Hardening + KOL | Planned | Full SandboxPolicy, social/KOL experiment |
| 7 — Multi-target Expansion | Planned | Second target validation |

---

## License

MIT
