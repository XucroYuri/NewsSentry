# GitHub Discoverability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善 News Sentry 在 GitHub 上的可检索性、可信认知资产、贡献入口和远端 repository metadata，以促进自然 star 增长。

**Architecture:** 采用“内容契约测试 + 双语 README + GitHub 模板 + 远端 metadata”四层收敛。先用轻量 JS 测试固定核心定位词和入口，再更新 README、`pyproject.toml`、`.github` 模板和 `docs/github-discoverability.md`，最后通过 `gh repo edit` 同步远端 About 信息。

**Tech Stack:** Markdown, TOML, GitHub CLI, Node.js assert/fs 测试, pre-commit hooks.

---

## File Structure

- Create: `tests/js/github_discoverability_test.mjs`
  - 负责验证 README、pyproject、GitHub 模板和 metadata 文档包含核心定位、搜索关键词和贡献入口。
- Create: `docs/github-discoverability.md`
  - 记录 GitHub About 推荐值、topics、README 维护规则和远端更新命令。
- Create: `.github/ISSUE_TEMPLATE/source_request.md`
  - 新增信源/国家/地区贡献入口。
- Create: `.github/ISSUE_TEMPLATE/research_workflow_request.md`
  - 新增研究工作流反馈入口。
- Modify: `README_en.md`
  - 作为全球开发者和 OSINT/新闻技术受众的主要首屏，使用英文检索关键词。
- Modify: `README.md`
  - 保持中文深度说明，强调专业新闻情报、OSINT、canonical event graph 和本地/云端长期路线。
- Modify: `pyproject.toml`
  - 同步 project description、keywords、classifiers、urls。
- Modify: `.github/ISSUE_TEMPLATE/bug_report.md`
  - 增加 target、pipeline stage、runtime mode、source type、data impact 字段。
- Modify: `.github/ISSUE_TEMPLATE/feature_request.md`
  - 增加功能分区，避免泛泛需求。
- Modify: `.github/PULL_REQUEST_TEMPLATE.md`
  - 增加契约、迁移、安全、文档同步和敏感数据检查。

---

### Task 1: Add Discoverability Contract Test

**Files:**
- Create: `tests/js/github_discoverability_test.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/js/github_discoverability_test.mjs` with this exact content:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

function read(path) {
  return readFileSync(join(repoRoot, path), "utf8");
}

function assertIncludes(file, expected) {
  const content = read(file);
  assert(
    content.includes(expected),
    `${file} must include: ${expected}`,
  );
}

function assertNotIncludes(file, unexpected) {
  const content = read(file);
  assert(
    !content.includes(unexpected),
    `${file} must not include stale phrase: ${unexpected}`,
  );
}

const englishReadmeTerms = [
  "AI news intelligence",
  "OSINT monitoring platform",
  "canonical event graph",
  "professional research workflows",
  "source health",
  "multilingual news",
  "human-in-the-loop",
  "Quick Start",
  "Use Cases",
  "Roadmap",
];

for (const term of englishReadmeTerms) {
  assertIncludes("README_en.md", term);
}

const chineseReadmeTerms = [
  "AI 新闻情报",
  "OSINT 监控平台",
  "canonical event graph",
  "专业研究工作流",
  "信源健康",
  "多语言新闻",
  "人在回路",
  "快速开始",
  "典型使用场景",
  "路线图",
];

for (const term of chineseReadmeTerms) {
  assertIncludes("README.md", term);
}

assertIncludes(
  "pyproject.toml",
  'description = "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows"',
);
assertIncludes("pyproject.toml", '"osint"');
assertIncludes("pyproject.toml", '"news-intelligence"');
assertIncludes("pyproject.toml", '"event-graph"');
assertIncludes("pyproject.toml", '"research-workflow"');
assertNotIncludes(
  "pyproject.toml",
  "Italy Breaking News reference target",
);

assertIncludes(
  "docs/github-discoverability.md",
  "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows.",
);
assertIncludes("docs/github-discoverability.md", "gh repo edit");
assertIncludes("docs/github-discoverability.md", "osint");
assertIncludes("docs/github-discoverability.md", "event-graph");

const templateFiles = [
  ".github/ISSUE_TEMPLATE/bug_report.md",
  ".github/ISSUE_TEMPLATE/feature_request.md",
  ".github/ISSUE_TEMPLATE/source_request.md",
  ".github/ISSUE_TEMPLATE/research_workflow_request.md",
  ".github/PULL_REQUEST_TEMPLATE.md",
];

for (const file of templateFiles) {
  assertIncludes(file, "News Sentry");
}

assertIncludes(".github/ISSUE_TEMPLATE/bug_report.md", "Pipeline stage");
assertIncludes(".github/ISSUE_TEMPLATE/source_request.md", "Source region");
assertIncludes(".github/ISSUE_TEMPLATE/research_workflow_request.md", "Research workflow area");
assertIncludes(".github/PULL_REQUEST_TEMPLATE.md", "Canonical contracts");
assertIncludes(".github/PULL_REQUEST_TEMPLATE.md", "Sensitive data");
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
node tests/js/github_discoverability_test.mjs
```

Expected: FAIL because `docs/github-discoverability.md`, new issue templates, and required README/pyproject phrases do not exist yet.

- [ ] **Step 3: Commit only the failing test**

Run:

```bash
git add tests/js/github_discoverability_test.mjs
git commit -m "test: 锁定 GitHub 可发现性内容契约"
```

Expected: commit succeeds after pre-commit hooks.

---

### Task 2: Update Project Metadata and GitHub Discoverability Reference

**Files:**
- Modify: `pyproject.toml`
- Create: `docs/github-discoverability.md`

- [ ] **Step 1: Update `pyproject.toml` project metadata**

In `pyproject.toml`, replace the current `[project]` description and keywords with:

```toml
description = "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows"
keywords = [
    "ai",
    "news",
    "news-intelligence",
    "osint",
    "monitoring",
    "media-monitoring",
    "public-opinion",
    "social-media-monitoring",
    "multilingual",
    "event-graph",
    "knowledge-graph",
    "research-workflow",
    "journalism",
    "rss",
    "fastapi",
]
```

Add these classifiers if they are not present:

```toml
    "Intended Audience :: Science/Research",
    "Topic :: Communications",
    "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
    "Topic :: Scientific/Engineering :: Information Analysis",
```

Replace `[project.urls]` with:

```toml
[project.urls]
Homepage = "https://github.com/XucroYuri/NewsSentry#readme"
Repository = "https://github.com/XucroYuri/NewsSentry"
Issues = "https://github.com/XucroYuri/NewsSentry/issues"
Documentation = "https://github.com/XucroYuri/NewsSentry/blob/main/docs/"
Roadmap = "https://github.com/XucroYuri/NewsSentry/blob/main/docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md"
Security = "https://github.com/XucroYuri/NewsSentry/blob/main/SECURITY.md"
```

- [ ] **Step 2: Create `docs/github-discoverability.md`**

Create `docs/github-discoverability.md` with this exact content:

````markdown
# GitHub Discoverability Reference

This document records the public GitHub metadata and content contract used to keep News Sentry discoverable, understandable, and credible.

## Repository Description

Use this GitHub About description:

```text
Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows.
```

## Homepage

Use the README entry point until a dedicated project site exists:

```text
https://github.com/XucroYuri/NewsSentry#readme
```

## Topics

Recommended topics:

```text
ai
news
osint
intelligence
monitoring
journalism
media-monitoring
public-opinion
social-media-monitoring
multilingual
event-graph
research-tool
python
fastapi
rss
docker
```

## Core Search Phrases

The README files and project metadata should keep these phrases visible:

- AI news intelligence
- OSINT monitoring platform
- multilingual news
- social media monitoring
- public opinion monitoring
- source health
- canonical event graph
- professional research workflows
- human-in-the-loop research

## GitHub CLI Update Commands

Run these commands after README and metadata changes are merged:

```bash
gh repo edit XucroYuri/NewsSentry \
  --description "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows." \
  --homepage "https://github.com/XucroYuri/NewsSentry#readme" \
  --enable-issues=true \
  --enable-wiki=true \
  --enable-discussions=true

gh repo edit XucroYuri/NewsSentry \
  --add-topic ai \
  --add-topic news \
  --add-topic osint \
  --add-topic intelligence \
  --add-topic monitoring \
  --add-topic journalism \
  --add-topic media-monitoring \
  --add-topic public-opinion \
  --add-topic social-media-monitoring \
  --add-topic multilingual \
  --add-topic event-graph \
  --add-topic research-tool \
  --add-topic python \
  --add-topic fastapi \
  --add-topic rss \
  --add-topic docker

gh repo view XucroYuri/NewsSentry \
  --json description,homepageUrl,repositoryTopics,hasDiscussionsEnabled,hasIssuesEnabled,hasWikiEnabled
```

If GitHub CLI reports an unsupported option for topics, update topics from the GitHub web UI using the same list above.

## Maintenance Rules

- Do not claim global cloud coverage until the cloud cluster exists.
- Do not publish artificial star, user, download, or performance numbers.
- Keep current capabilities and roadmap separate.
- Keep English README optimized for global developer search.
- Keep Chinese README useful for local professional users and long-term product direction.
- Do not commit `.env`, runtime data, `.omx`, browser profiles, logs, tokens, cookies, or local source credentials.
````

- [ ] **Step 3: Run metadata checks**

Run:

```bash
python -m pip install build
python -m build --sdist --wheel
node tests/js/github_discoverability_test.mjs
```

Expected:

- `python -m build` succeeds.
- `node tests/js/github_discoverability_test.mjs` still fails because README and GitHub templates are not updated yet.

- [ ] **Step 4: Commit metadata/reference changes**

Run:

```bash
git add pyproject.toml docs/github-discoverability.md
git commit -m "docs: 更新 GitHub 可发现性元数据基准"
```

---

### Task 3: Rewrite README First Screens and Discovery Sections

**Files:**
- Modify: `README_en.md`
- Modify: `README.md`

- [ ] **Step 1: Update `README_en.md` first screen**

Replace the badge/title/intro/navigation area at the top of `README_en.md` through the end of the current “Core Features” table with:

````markdown
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
| AI judgment | Score news value, China relevance, sentiment, and confidence with rule-first fallback |
| Canonical event graph | Separate real-world events from source mentions, relations, taxonomy, and entities |
| Professional research workflows | Review queues, annotations, merge/split decisions, and research artifacts |
| Local-first deployment | Run as CLI, FastAPI web UI, desktop wrapper, Docker, or future cloud worker |
| Human-in-the-loop design | AI assists filtering and analysis while final research judgment stays auditable |
````

- [ ] **Step 2: Add `Use Cases`, `Roadmap`, and `Contributing` anchors to `README_en.md`**

Before the final license or roadmap section, add these sections if equivalent sections do not already exist:

```markdown
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

- [Global intelligence platform direction](docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md)
- [Shadow canonical data spine](docs/specs/2026-05-30-shadow-canonical-data-spine-design.md)
- [Professional research workflow MVP](docs/specs/2026-05-30-professional-research-workflow-mvp-design.md)

## Contributing

Contributions are welcome, especially in these areas:

- new country, region, language, and source configurations;
- collector adapters for public websites, RSS feeds, APIs, and social sources;
- canonical event graph, taxonomy, source health, and research workflow improvements;
- documentation, deployment guides, and reproducible monitoring examples.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [docs/contracts-canonical.md](docs/contracts-canonical.md), and [docs/architecture.md](docs/architecture.md).
```

- [ ] **Step 3: Update `README.md` first screen**

Replace the badge/title/intro/navigation area at the top of `README.md` through the end of the current “核心特性” table with:

````markdown
<p align="center">
  <img src="https://img.shields.io/badge/version-1.9.1-blue.svg" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-orange.svg" alt="license" />
  <img src="https://img.shields.io/badge/ruff-0%20errors-success.svg" alt="ruff" />
</p>

<h1 align="center">News Sentry</h1>

<p align="center">
  <strong>开源 AI 新闻情报与 OSINT 监控平台</strong><br>
  多语言新闻与社媒采集 → 信源健康 → canonical event graph → 专业研究工作流
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#为什么需要-news-sentry">为什么需要</a> ·
  <a href="#核心能力">核心能力</a> ·
  <a href="#系统架构">系统架构</a> ·
  <a href="#典型使用场景">典型使用场景</a> ·
  <a href="#路线图">路线图</a> ·
  <a href="#参与贡献">参与贡献</a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README_en.md">English</a>
</p>

---

## News Sentry 是什么？

News Sentry 是一个 local-first 的开源系统，用于持续 **AI 新闻情报**、**OSINT 监控平台** 和专业研究工作流。

它持续采集多语言新闻、RSS、API、社媒和公共网页信源，并帮助研究者把碎片化报道整理为结构化事件、信源健康状态、告警、Markdown 简报和 canonical event graph。

它不是普通 RSS reader，也不是一次性爬虫脚本，而是面向长期运行和人工复核的新闻情报基础设施。

## 为什么需要 News Sentry？

大多数监控工具止步于收集链接。News Sentry 关注完整情报闭环：

```text
采集 → 过滤 → 研判 → 输出 → 复核 → canonical graph → research artifact
```

关键区别是：一篇报道只是一次 **event mention**，不是事实本身。多家媒体、多语言、多平台报道可以归并为 canonical event，而人在回路的复核、标注、合并、拆分和研究笔记会保存为 research artifacts，不会静默污染事实层。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 多语言新闻监控 | 已配置意大利、日本、德国、法国和英文涉华报道 target |
| RSS/API/OpenCLI 采集 | 采集阶段零 token，支持 feeds、API、网站和可选工具适配 |
| 信源健康 | 跟踪信源可用性、运行诊断、陈旧 feed 和生命周期 |
| AI 研判 | 规则优先，AI 辅助新闻价值、涉华相关度、情绪和置信度评分 |
| canonical event graph | 区分现实事件、报道 mention、关系、分类和实体 |
| 专业研究工作流 | 复核队列、人工标注、merge/split 决策和 research artifacts |
| 本地优先部署 | 支持 CLI、FastAPI Web UI、桌面包装、Docker 和未来云端 worker |
| 人在回路 | AI 辅助筛选和分析，关键研究判断保留可审计人工介入 |
````

- [ ] **Step 4: Add Chinese use case, roadmap, and contribution anchors**

Before the final license or roadmap section in `README.md`, add:

```markdown
## 典型使用场景

- 新闻编辑部和研究团队持续追踪国家、地区、政策、产业和突发事件。
- OSINT 研究者跨语言验证公开信源、报道来源和事件链。
- 分析师监控公共舆情、地缘风险、产业政策和媒体叙事。
- 运维人员管理多目标信源健康、覆盖缺口和采集诊断。
- 本地研究工作台用于复核、标注、合并、拆分和输出 canonical events 简报。

## 路线图

News Sentry 正在从本地新闻监控引擎演进为全球新闻情报平台。

近期重点：

- 修复 run batch 语义、alert history、source inventory 等可靠性根基；
- 建立 shadow canonical data spine，承载 canonical events、mentions、relations、taxonomy 和 research artifacts；
- 落地专业研究工作流 MVP，支持人工复核、merge/split、标注和简报；
- 规划本地轻客户端，让用户选择关注范围并支持离线研究；
- 长期探索半中心化公共采集节点，提升全球本地信源覆盖。

参考文档：

- [全球情报平台商业与架构方向](docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md)
- [Shadow canonical data spine](docs/specs/2026-05-30-shadow-canonical-data-spine-design.md)
- [Professional research workflow MVP](docs/specs/2026-05-30-professional-research-workflow-mvp-design.md)

## 参与贡献

欢迎贡献：

- 新国家、地区、语言和信源配置；
- 面向公共网站、RSS、API 和社媒来源的 collector adapter；
- canonical event graph、taxonomy、source health 和研究工作流能力；
- 文档、部署指南和可复现监控样例。

贡献前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[docs/contracts-canonical.md](docs/contracts-canonical.md) 和 [docs/architecture.md](docs/architecture.md)。
```

- [ ] **Step 5: Run README contract test**

Run:

```bash
node tests/js/github_discoverability_test.mjs
```

Expected: FAIL only for GitHub issue templates if Task 4 has not been completed yet.

- [ ] **Step 6: Commit README changes**

Run:

```bash
git add README.md README_en.md
git commit -m "docs: 重写 GitHub 首屏项目定位"
```

---

### Task 4: Upgrade GitHub Issue and PR Templates

**Files:**
- Modify: `.github/ISSUE_TEMPLATE/bug_report.md`
- Modify: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/ISSUE_TEMPLATE/source_request.md`
- Create: `.github/ISSUE_TEMPLATE/research_workflow_request.md`
- Modify: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Replace bug report template**

Replace `.github/ISSUE_TEMPLATE/bug_report.md` with:

```markdown
---
name: Bug Report
about: Report a News Sentry bug or unexpected behavior
title: "[Bug] "
labels: bug
---

## Bug Description

Describe what went wrong in News Sentry.

## Impact Area

- Target:
- Pipeline stage: collect / filter / judge / output / feedback / canonical / API / frontend / deployment
- Runtime mode: CLI / FastAPI Web UI / Docker / desktop / cloud
- Source type: RSS / API / OpenCLI / social / unknown
- Data directory impact: raw / evaluated / drafts / archive / SQLite / none / unknown

## Steps to Reproduce

1. Run:
2. Open or inspect:
3. Observe:

## Expected Behavior

Describe the behavior you expected.

## Actual Behavior

Describe the actual behavior, including errors, stale data, duplicate data, or blocked UI states.

## Environment

- Python version:
- News Sentry version or commit:
- Operating system:
- Deployment method:

## Logs or Evidence

Paste relevant logs, screenshots, API responses, or file paths. Remove API keys, cookies, tokens, and private source credentials.
```

- [ ] **Step 2: Replace feature request template**

Replace `.github/ISSUE_TEMPLATE/feature_request.md` with:

```markdown
---
name: Feature Request
about: Suggest a News Sentry capability or product improvement
title: "[Feature] "
labels: enhancement
---

## Feature Summary

Describe the News Sentry capability you want.

## Area

- [ ] Collector or source health
- [ ] Pipeline reliability
- [ ] Canonical event graph
- [ ] Research workflow
- [ ] Public news portal
- [ ] Admin console
- [ ] Deployment or local client
- [ ] Documentation

## Use Case

Who needs this, and what decision or workflow does it improve?

## Proposed Behavior

Describe the expected user flow, API behavior, or data contract.

## Success Criteria

- Criterion 1:
- Criterion 2:
- Criterion 3:

## Additional Context

Link examples, related issues, source references, or research workflow notes.
```

- [ ] **Step 3: Create source request template**

Create `.github/ISSUE_TEMPLATE/source_request.md`:

```markdown
---
name: Source Request
about: Suggest a country, region, language, or public source for News Sentry
title: "[Source] "
labels: source, enhancement
---

## Source Summary

Describe the source or monitoring target you want News Sentry to support.

## Source Region

- Country or region:
- Language:
- Topic area: general news / politics / economy / technology / industry / risk / social media / other

## Source Type

- [ ] RSS feed
- [ ] Public website
- [ ] Public API
- [ ] Social media account or list
- [ ] Government or institution website
- [ ] Other public source

## URLs

List public URLs. Do not include private credentials, cookies, paid content access, or personal accounts.

## Why It Matters

Explain the research, journalism, OSINT, or public opinion monitoring value.

## Maintenance Notes

Mention update frequency, language, known rate limits, robots policy, or access constraints if known.
```

- [ ] **Step 4: Create research workflow request template**

Create `.github/ISSUE_TEMPLATE/research_workflow_request.md`:

```markdown
---
name: Research Workflow Request
about: Suggest a professional research workflow improvement for News Sentry
title: "[Research] "
labels: research-workflow, enhancement
---

## Research Workflow Area

- [ ] Review queue
- [ ] Evidence and source traceability
- [ ] Annotation or notes
- [ ] Merge or split canonical events
- [ ] Research brief or daily report
- [ ] Alerts and monitoring
- [ ] Local client workflow

## Current Pain

Describe the work that is currently slow, unclear, blocked, or not auditable.

## Desired Workflow

Describe the ideal researcher, editor, analyst, or OSINT workflow step by step.

## Data Needed

List the events, mentions, sources, entities, taxonomy, or artifacts needed to support this workflow.

## Output Needed

Describe the expected output: dashboard state, annotation, decision artifact, Markdown brief, alert, export, or API response.
```

- [ ] **Step 5: Replace PR template**

Replace `.github/PULL_REQUEST_TEMPLATE.md` with:

```markdown
## Summary

Describe what this PR changes in News Sentry and why.

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Configuration or source update
- [ ] Canonical data contract change
- [ ] Deployment or CI change

## Impact Area

- [ ] Collector/source health
- [ ] Pipeline stages
- [ ] Canonical contracts
- [ ] Research workflow
- [ ] Public news portal
- [ ] Admin console
- [ ] API server
- [ ] Documentation

## Verification

- [ ] `ruff check` passes
- [ ] Relevant `pytest` tests pass
- [ ] Relevant JS tests pass
- [ ] Documentation links were checked when docs changed

## Canonical Contracts

- [ ] I checked `docs/contracts-canonical.md` if this changes schema, pipeline stage, score semantics, taxonomy, source lifecycle, or storage directories.
- [ ] I added or updated tests for data contract behavior when needed.

## Sensitive Data

- [ ] No API keys, cookies, tokens, browser profiles, `.env` files, local runtime data, private source credentials, or `.omx` state files are included.

## Migration and Rollback

Describe any data migration, compatibility behavior, or rollback path. Write `None` if this PR has no runtime data impact.

## Screenshots or Evidence

Add screenshots, logs, API responses, or command output when they help reviewers understand the change.
```

- [ ] **Step 6: Run discoverability contract**

Run:

```bash
node tests/js/github_discoverability_test.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit template changes**

Run:

```bash
git add .github/ISSUE_TEMPLATE/bug_report.md .github/ISSUE_TEMPLATE/feature_request.md .github/ISSUE_TEMPLATE/source_request.md .github/ISSUE_TEMPLATE/research_workflow_request.md .github/PULL_REQUEST_TEMPLATE.md
git commit -m "docs: 完善 GitHub 协作入口模板"
```

---

### Task 5: Apply Remote GitHub Metadata

**Files:**
- No repository file changes expected.

- [ ] **Step 1: Inspect current remote metadata**

Run:

```bash
gh repo view XucroYuri/NewsSentry --json description,homepageUrl,repositoryTopics,hasDiscussionsEnabled,hasIssuesEnabled,hasWikiEnabled
```

Expected: command returns JSON for `XucroYuri/NewsSentry`.

- [ ] **Step 2: Update About fields**

Run:

```bash
gh repo edit XucroYuri/NewsSentry \
  --description "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows." \
  --homepage "https://github.com/XucroYuri/NewsSentry#readme" \
  --enable-issues=true \
  --enable-wiki=true \
  --enable-discussions=true
```

Expected: exit code 0. If GitHub CLI rejects `--enable-discussions`, rerun without that flag and note that Discussions must be enabled manually in GitHub settings.

- [ ] **Step 3: Add topics**

Run:

```bash
for topic in ai news osint intelligence monitoring journalism media-monitoring public-opinion social-media-monitoring multilingual event-graph research-tool python fastapi rss docker; do
  gh repo edit XucroYuri/NewsSentry --add-topic "$topic"
done
```

Expected: every command exits 0. If GitHub CLI rejects topic edits, update topics manually in the GitHub web UI and keep `docs/github-discoverability.md` as the source of truth.

- [ ] **Step 4: Verify remote metadata**

Run:

```bash
gh repo view XucroYuri/NewsSentry --json description,homepageUrl,repositoryTopics,hasDiscussionsEnabled,hasIssuesEnabled,hasWikiEnabled
```

Expected JSON includes:

- description starting with `Open-source AI news intelligence`
- homepage `https://github.com/XucroYuri/NewsSentry#readme`
- topics including `osint`, `event-graph`, `research-tool`, `media-monitoring`
- issues enabled
- wiki enabled

- [ ] **Step 5: No commit for remote-only metadata**

Run:

```bash
git status --short --untracked-files=all
```

Expected: no new staged changes from this task. Existing unrelated local changes may remain unstaged.

---

### Task 6: Final Validation and Integration Commit Check

**Files:**
- Validate all files touched in Tasks 1-4.

- [ ] **Step 1: Run focused checks**

Run:

```bash
node tests/js/github_discoverability_test.mjs
python -m build --sdist --wheel
git diff --check
rm -rf build dist news_sentry.egg-info src/news_sentry.egg-info
```

Expected:

- Node discoverability test passes.
- Python build succeeds.
- `git diff --check` reports no whitespace errors.
- Generated build artifacts are removed before final status review.

- [ ] **Step 2: Check that unrelated dirty files are not staged**

Run:

```bash
git status --short --untracked-files=all
git diff --cached --name-only
```

Expected staged names, if any, are only files from this plan. Do not stage `.omx`, `.env`, runtime data, generated logs, browser profiles, or unrelated frontend files.

- [ ] **Step 3: Review final log**

Run:

```bash
git log --oneline -8
```

Expected: shows the plan commits in order:

- `test: 锁定 GitHub 可发现性内容契约`
- `docs: 更新 GitHub 可发现性元数据基准`
- `docs: 重写 GitHub 首屏项目定位`
- `docs: 完善 GitHub 协作入口模板`

- [ ] **Step 4: Prepare final report**

Report:

- files changed and commits created;
- remote GitHub metadata before/after verification;
- validation commands and exact outcomes;
- any remote metadata setting that required manual GitHub UI action;
- unrelated dirty files intentionally left untouched.
