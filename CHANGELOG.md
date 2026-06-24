# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.0.0-rc2] — 2026-06-24

### Removed (Breaking)

- **FreeLLMAPI** Node.js sidecar — replaced by built-in Python provider chain
- **OpenCLI** adapter and all OpenCLI-based sources (19 YAML configs)
- **Social/KOL collectors** — 15 Twitter dimension configs removed; RSS-Bridge handles social
- **Browser fallback layer** — `_browser_fallback.yaml` deleted
- **Hermes/OpenClaw runtime adapters** — configs removed, code remains as optional adapters
- **47 stale config files** (5,141 lines): opencli sources, social templates, KOL sandbox, runtime adapters

### Added

- **AI Provider chain**: Gemini → DeepSeek → Groq → Cloudflare Workers AI (automatic fallback)
- **Reddit RSS collector** (`collect/reddit.py`) and **Hacker News REST collector** (`collect/hn.py`)
- **Brand**: gold watchtower logo (`logo.svg`, `icon-192.svg`, `icon-512.svg`) on admin panel + README
- **`check.sh`**: one-shot quality gate (ruff + mypy + pytest)
- **`run.sh` / `run.ps1`**: CLI entrypoint wrappers
- **`.github/release.yml`**: automated release note generation
- **`docs/contributing.md`**: branch, commit, PR workflow conventions

### Changed

- **Config**: `config.py` split into `config/loader.py`, `config/models.py`, `config/country_axes.py`
- **Dockerfile**: optimized 340MB→299MB (-12%), removed curl, stripped pycache
- **Deploy**: `deploy.yml` uses `[api,proxy]`; pip install cached; npm build cached
- **Tests**: 2,900→3,020 tests, 86→87% coverage

### Performance

- Static asset cache: `no-cache` → `1yr immutable` (`public.css`, `app.js`)
- API cache: public news feed TTL 15s→60s, update poll 30s→60s
- CI: concurrency group on CI workflow (auto-cancel stale runs); deploy always runs

### Documentation

- `docs/architecture.md`: v2.0 Mermaid rewrite
- `README.md`: v2.0 update with gold logo, test counts, badges
- `README_en.md`: full English rewrite
- `MAKE_GUIDE.md`: developer onboarding

### Security

- OWASP Top 10 audit: 0 critical/high findings
- No hardcoded secrets, no SQL injection, CSP/CORS/auth properly configured

### Fixed

- 4 stale test assertions updated for removed modules
- 2 unused `type: ignore` comments removed
- 4 benign pytest warnings suppressed
- 3 dead code vars prefixed with underscore
- `docker.yml` fixed for single Dockerfile (was looking for `.core`/`.browser`/`.full`)
- Deploy concurrency removed from deploy.yml (was causing skipped deploys)

---

## [1.9.1] — 2026-05-25

- SSE route conflict fix + OWASP security audit patch

## [1.9.0] — 2026-05-25

- Docker GHCR images, test coverage improvements, state cleanup

## [1.8.0] — 2026-05-25

- Quality polishing, first-launch onboarding guide, Tauri desktop baseline

[2.0.0-rc2]: https://github.com/XucroYuri/NewsSentry/compare/v1.9.1...v2.0.0-rc2
[1.9.1]: https://github.com/XucroYuri/NewsSentry/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/XucroYuri/NewsSentry/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/XucroYuri/NewsSentry/releases/tag/v1.8.0
