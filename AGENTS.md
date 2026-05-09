# News Sentry Agent Instructions

## Project Mission

News Sentry is a framework-neutral Agent Skill Pack platform for continuous news monitoring. The first reference target is Italy, but core code and contracts must stay reusable for other countries, regions, and domains.

The system is intended to run inside heartbeat-capable agent frameworks such as Codex, opencode, Claude Code, OpenClaw, Hermes Agent, and similar hosts. A host should trigger bounded runs; the Skill Pack itself must not implement an unbounded daemon loop.

## Architecture Source Of Truth

Read these files before changing architecture, schemas, pipeline behavior, permissions, provider routing, or tool execution:

- `docs/architecture-overview.md`
- `docs/integration-protocol.md`
- `docs/newsevent-schema.md`
- `docs/brainstorming/通用内核与平台化架构PRD.md`
- `docs/brainstorming/ToolManifest与工具适配层规格.md`
- `docs/brainstorming/AIProvider与模型路由规格.md`
- `docs/brainstorming/SandboxPolicy与执行权限规格.md`

## Core Decisions

- Keep the kernel framework-neutral. Codex, opencode, Claude Code, Cursor, OpenClaw, and Hermes integrations belong in thin adapters or developer tooling, not in domain contracts.
- Use Obsidian/Git-friendly Markdown files with YAML frontmatter as the v1 storage surface.
- Use `NewsEvent` as the cross-agent data object. Do not introduce competing event schemas.
- Use deterministic `NewsEvent.id` for item identity and `run_id` for bounded execution identity. Use `cluster_id` or `story_id` for cross-source aggregation.
- Use 0-100 scores for `news_value_score`, `china_relevance`, confidence, source credibility, and value dimensions unless a documented field explicitly says otherwise.
- Keep `judge_result.recommendation` inside `judge_result`; do not duplicate it as a top-level field.
- Keep static source configuration free of arbitrary shell commands. CLI/OpenCLI execution must go through `ToolManifest`, `tool_ref`, `binding_id`, `validated_args`, and sandbox checks.
- Do not store cookies, tokens, passwords, browser profile internals, API keys, or private-message content in `NewsEvent`, frontmatter, logs, or docs.
- v1 stops at drafts, reviewed files, and publish-ready archives. Do not implement automatic external publishing without an explicit new decision.

## Phase Order

Follow this implementation order unless the user explicitly changes the roadmap:

1. Contract Stabilization
2. Kernel MVP
3. Tool/Skill Registry + OpenCLI
4. AI Provider Routing
5. Sandbox Hardening + Social/KOL Experiment
6. Multi-target Expansion

Phase 1 should focus on RSS/API baseline, bounded run lifecycle, config loading, file event writing, run logs, memory, source health, and a minimal sandbox enforcer. Do not pull OpenCLI, social login state, dynamic registry, or complex provider routing into Phase 1.

## File Event Protocol

Use the v1 directory protocol consistently:

- `raw/`: collected events
- `evaluated/`: filtered and judged events
- `drafts/`: editorial drafts
- `reviewed/`: human or internal-review candidates
- `published/`: approved archive or publish-ready files
- `archive/`: rejected, duplicate, low-value, or failed samples
- `memory/`: known IDs, source health, cursors, provider stats, KOL state
- `logs/`: bounded run logs, tool audit logs, provider usage logs

Directory state does not replace `NewsEvent.pipeline_stage`. Preserve `processing_history` when moving or enriching events.

## Development Workflow

- Inspect existing docs and contracts before implementing.
- Keep edits scoped to the current milestone.
- Prefer structured parsing and schema validation over ad hoc string handling.
- Do not introduce a database queue in v1 unless the user explicitly changes the milestone.
- When creating runtime code later, add focused tests around contract validation, file event transitions, sandbox decisions, and provider output schemas.
- If a change creates or updates user-visible behavior, update the relevant docs in the same commit.

## Verification Expectations

Before committing implementation work, run the narrowest meaningful checks available for the files touched. For documentation-only changes, check for internal consistency, stale field names, score scale drift, and sensitive-data leakage.

Do not commit `.DS_Store`, `.env*`, local Claude settings, local Cursor state, tokens, cookies, browser profile files, or generated logs.
