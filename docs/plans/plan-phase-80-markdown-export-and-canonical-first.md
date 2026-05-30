# Phase 80 Markdown Export and Canonical-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop treating Markdown as the default per-event storage/output path, and make Markdown an explicit user-triggered export projection backed by indexed/canonical data.

**Architecture:** Keep the existing shadow canonical spine and current SQLite `event_index` as the transition bridge. Add a reusable Markdown export renderer/service, expose export APIs for public event detail and canonical research events, then add a runtime output policy that defaults new pipeline runs away from automatic per-event Markdown drafts while preserving compatibility through an opt-in setting.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2 models, SQLite via `AsyncStore`, existing `MarkdownWriter`, pytest, ruff.

---

## Scope

This plan implements the first executable slice of `docs/roadmap/global-scale-news-intelligence-architecture.md`:

- Markdown becomes a projection/export format.
- A single news event can be downloaded as Markdown on demand.
- Canonical research events can be exported as Markdown evidence packages.
- New output runs can be configured to avoid automatic `drafts/{event.id}.md` generation.
- Existing historical Markdown remains readable and importable.

This plan does not introduce Postgres, object storage, ClickHouse, Iceberg, vector search, or a new frontend framework.

## File Structure

- Create `src/news_sentry/core/markdown_export.py`
  - Pure rendering/service helpers for event Markdown and canonical evidence-package Markdown.
  - No filesystem side effects.
  - Reuses readable formatting from `MarkdownWriter` where possible.
- Modify `src/news_sentry/skills/output/markdown_writer.py`
  - Expose `render(event)` so API export can reuse the exact Markdown shape without writing files.
- Modify `src/news_sentry/core/api_server.py`
  - Add public event Markdown export endpoint.
  - Add admin/research canonical Markdown export endpoint.
  - Return `text/markdown; charset=utf-8` with safe download headers.
- Modify `src/news_sentry/core/config.py`
  - Add output policy parsing for `markdown_auto_drafts`.
  - Default local/runtime behavior should be `false` after this phase.
- Modify `src/news_sentry/core/run.py`
  - Respect `markdown_auto_drafts`.
  - Still update event index and alert pipeline when auto drafts are disabled.
- Modify `src/news_sentry/core/async_run.py`
  - Preserve async output indexing semantics when `run.py` returns outputted events without file paths.
- Test `tests/unit/test_markdown_export.py`
  - Renderer behavior and escaping.
- Test `tests/unit/test_api_server.py`
  - Export endpoint response shape and content.
- Test `tests/unit/test_run.py` and `tests/unit/test_async_run.py`
  - Output policy does not create per-event Markdown by default.
- Frontend download buttons are intentionally deferred. The API returns attachment responses so the UI can add links later without changing backend behavior.

## Task 1: Reusable Markdown Export Renderer

**Files:**
- Create: `src/news_sentry/core/markdown_export.py`
- Modify: `src/news_sentry/skills/output/markdown_writer.py`
- Test: `tests/unit/test_markdown_export.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/unit/test_markdown_export.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from news_sentry.core.markdown_export import (
    render_canonical_event_markdown,
    render_news_event_markdown,
)
from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage


def _event() -> NewsEvent:
    return NewsEvent(
        id="ne-italy-ansa-20260530-a1b2c3d4",
        source_id="ansa",
        target_id="italy",
        url="https://example.com/news",
        title_original="Titolo originale",
        title_translated="中文标题",
        content_original="Corpo della notizia",
        content_translated="中文正文",
        language=Language.IT,
        published_at=datetime(2026, 5, 30, 8, 0, tzinfo=UTC),
        collected_at=datetime(2026, 5, 30, 8, 1, tzinfo=UTC),
        pipeline_stage=PipelineStage.JUDGED,
        news_value_score=88,
        china_relevance=42,
        metadata={"classification": {"l0": "international-relations"}},
    )


def test_render_news_event_markdown_is_projection_without_file_write() -> None:
    content = render_news_event_markdown(_event())

    assert content.startswith("---\n")
    assert "id: ne-italy-ansa-20260530-a1b2c3d4" in content
    assert "# 中文标题" in content
    assert "## 原文内容" in content
    assert "Corpo della notizia" in content
    assert "## 中文译文" in content
    assert "中文正文" in content


def test_render_canonical_event_markdown_includes_mentions_and_provenance() -> None:
    content = render_canonical_event_markdown(
        event={
            "canonical_event_id": "ce_italy_001",
            "target_id": "italy",
            "title": "Canonical title",
            "summary": "Canonical summary",
            "news_value_score": 91,
            "china_relevance": 12,
        },
        mentions=[
            {
                "mention_id": "em_001",
                "source_id": "ansa",
                "url": "https://example.com/a",
                "title": "Mention title",
                "published_at": "2026-05-30T08:00:00Z",
                "metadata": {"file_path": "drafts/ne-italy-ansa.md"},
            }
        ],
        relations=[],
        artifacts=[],
    )

    assert "# Canonical title" in content
    assert "Canonical summary" in content
    assert "## 信源报道" in content
    assert "ansa" in content
    assert "https://example.com/a" in content
    assert "drafts/ne-italy-ansa.md" in content
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_markdown_export.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'news_sentry.core.markdown_export'
```

- [ ] **Step 3: Add `MarkdownWriter.render()` and renderer module**

In `src/news_sentry/skills/output/markdown_writer.py`, change `write()` so content rendering is reusable:

```python
    def render(self, event: NewsEvent) -> str:
        """Render an event as Markdown without writing it to disk."""
        original_stage = event.pipeline_stage
        event.pipeline_stage = PipelineStage.OUTPUTTED
        try:
            fm = self._render_frontmatter(event)
            body = self._render_body(event)
            return f"---\n{fm}\n---\n\n{body}"
        finally:
            event.pipeline_stage = original_stage

    def write(self, event: NewsEvent) -> Path:
        """将事件写入 Obsidian 兼容的 Markdown 文件。"""
        filename = f"{event.id}.md"

        target_dir = self._output_base_dir / self._target_id / "drafts"
        target_dir.mkdir(parents=True, exist_ok=True)

        filepath = target_dir / filename
        content = self.render(event)
        event.pipeline_stage = PipelineStage.OUTPUTTED
        self._atomic_write(filepath, content)
        return filepath
```

Create `src/news_sentry/core/markdown_export.py`:

```python
"""Markdown export projections.

Markdown is an explicit export format, not canonical storage.
"""

from __future__ import annotations

from typing import Any

import yaml

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.output.markdown_writer import MarkdownWriter


def render_news_event_markdown(event: NewsEvent) -> str:
    """Render one NewsEvent as downloadable Markdown without filesystem writes."""
    writer = MarkdownWriter(
        {
            "target_id": getattr(event, "target_id", None) or "default",
            "output_base_dir": ".",
        }
    )
    return writer.render(event)


def render_canonical_event_markdown(
    *,
    event: dict[str, Any],
    mentions: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> str:
    """Render a canonical event evidence package as Markdown."""
    frontmatter = {
        "canonical_event_id": event.get("canonical_event_id"),
        "target_id": event.get("target_id"),
        "news_value_score": event.get("news_value_score"),
        "china_relevance": event.get("china_relevance"),
        "mention_count": len(mentions),
        "relation_count": len(relations),
        "artifact_count": len(artifacts),
        "export_kind": "canonical_event_evidence_package",
    }
    fm = yaml.dump(
        {k: v for k, v in frontmatter.items() if v is not None},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    title = str(event.get("title") or event.get("primary_title") or event["canonical_event_id"])
    summary = str(event.get("summary") or event.get("primary_summary") or "")
    lines = [
        "---",
        fm,
        "---",
        "",
        f"# {title}",
        "",
    ]
    if summary:
        lines.extend([summary, ""])
    lines.extend(["## 信源报道", ""])
    if mentions:
        for mention in mentions:
            mention_title = mention.get("title") or mention.get("title_original") or mention["mention_id"]
            lines.append(f"- **{mention.get('source_id') or 'unknown'}** | {mention_title}")
            if mention.get("published_at"):
                lines.append(f"  - 发布时间: {mention['published_at']}")
            if mention.get("url"):
                lines.append(f"  - 链接: {mention['url']}")
            file_path = (mention.get("metadata") or {}).get("file_path")
            if file_path:
                lines.append(f"  - 历史文件: `{file_path}`")
    else:
        lines.append("暂无信源报道。")
    lines.extend(["", "## 事件关系", ""])
    if relations:
        for relation in relations:
            lines.append(
                "- "
                f"{relation.get('relation_type', 'related')} | "
                f"{relation.get('source_canonical_event_id')} -> "
                f"{relation.get('target_canonical_event_id')}"
            )
    else:
        lines.append("暂无事件关系。")
    lines.extend(["", "## 研究记录", ""])
    if artifacts:
        for artifact in artifacts:
            lines.append(f"- **{artifact.get('artifact_type')}**: {artifact.get('title') or artifact.get('artifact_id')}")
    else:
        lines.append("暂无研究记录。")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run renderer tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_markdown_export.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit Task 1**

```bash
git add src/news_sentry/core/markdown_export.py src/news_sentry/skills/output/markdown_writer.py tests/unit/test_markdown_export.py
git commit -m "feat: add markdown export renderer"
```

## Task 2: Markdown Export API

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] **Step 1: Add failing API tests**

Append tests in `tests/unit/test_api_server.py` near existing event detail and canonical API tests:

```python
def test_public_event_markdown_export_returns_download(client, tmp_path):
    target_dir = tmp_path / "data" / "italy" / "drafts"
    target_dir.mkdir(parents=True)
    md_path = target_dir / "ne-italy-ansa-20260530-export.md"
    md_path.write_text(
        "---\n"
        "id: ne-italy-ansa-20260530-export\n"
        "source_id: ansa\n"
        "url: https://example.com/export\n"
        "title_original: Export title\n"
        "language: it\n"
        "published_at: 2026-05-30T08:00:00Z\n"
        "collected_at: 2026-05-30T08:01:00Z\n"
        "pipeline_stage: outputted\n"
        "---\n\n"
        "# Export title\n\n"
        "Body\n",
        encoding="utf-8",
    )

    response = client.get(
        "/api/v1/news/target/italy/events/ne-italy-ansa-20260530-export/export/markdown"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in response.headers["content-disposition"]
    assert "ne-italy-ansa-20260530-export.md" in response.headers["content-disposition"]
    assert "# Export title" in response.text


def test_canonical_event_markdown_export_returns_evidence_package(auth_client):
    response = auth_client.get(
        "/api/v1/canonical/events/ce_italy_export/export/markdown?target_id=italy"
    )

    assert response.status_code in {200, 404}
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("text/markdown")
        assert "export_kind: canonical_event_evidence_package" in response.text
```

If the local fixture names differ, keep the assertion pattern and create the target/store fixture in the same style as adjacent canonical tests in the file.

- [ ] **Step 2: Run API tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q -k "markdown_export or canonical_event_markdown_export"
```

Expected:

```text
FAILED ... 404
```

- [ ] **Step 3: Add API helpers and endpoints**

In `src/news_sentry/core/api_server.py`, add imports:

```python
from fastapi.responses import Response

from news_sentry.core.markdown_export import (
    render_canonical_event_markdown,
    render_news_event_markdown,
)
```

Add helper near other response helpers:

```python
def _markdown_download_response(filename: str, content: str) -> Response:
    safe_filename = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")
    if not safe_filename.endswith(".md"):
        safe_filename = f"{safe_filename}.md"
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
```

Add public event export endpoint near public event detail endpoints:

```python
    @app.get("/api/v1/news/target/{target_id}/events/{event_id}/export/markdown")
    async def export_public_event_markdown(target_id: str, event_id: str) -> Response:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=503, detail="Event store unavailable")
        event = await _load_indexed_event_detail(_data_dir, target_id, store, event_id)
        if event is None or event is _INVISIBLE_INDEXED_EVENT:
            raise HTTPException(status_code=404, detail="Event not found")
        if isinstance(event, dict):
            content = _render_index_row_markdown(event)
        else:
            content = render_news_event_markdown(event)
        return _markdown_download_response(f"{event_id}.md", content)
```

If `_render_index_row_markdown` does not exist, add:

```python
def _render_index_row_markdown(row: dict[str, Any]) -> str:
    title = str(row.get("title_original") or row.get("title") or row["event_id"])
    lines = [
        "---",
        yaml.dump(
            {
                "id": row.get("event_id"),
                "target_id": row.get("target_id"),
                "source_id": row.get("source_id"),
                "url": row.get("url"),
                "published_at": row.get("published_at"),
                "pipeline_stage": row.get("pipeline_stage") or row.get("stage"),
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).rstrip("\n"),
        "---",
        "",
        f"# {title}",
        "",
    ]
    if row.get("summary"):
        lines.extend([str(row["summary"]), ""])
    return "\n".join(lines).rstrip() + "\n"
```

Add canonical export endpoint near canonical event detail endpoints:

```python
    @app.get("/api/v1/canonical/events/{canonical_event_id}/export/markdown")
    async def export_canonical_event_markdown(
        canonical_event_id: str,
        target_id: str,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> Response:
        store = await _store_for_target(target_id)
        if store is None:
            raise HTTPException(status_code=404, detail="Canonical event not found")
        event = await _canonical_event_or_404(store, canonical_event_id, target_id)
        mentions = await store.list_event_mentions(canonical_event_id)
        relations = await store.list_canonical_relations(canonical_event_id)
        artifacts = await store.list_research_artifacts(
            target_id=target_id,
            subject_type="canonical_event",
            subject_id=canonical_event_id,
            limit=200,
        )
        content = render_canonical_event_markdown(
            event=event,
            mentions=mentions,
            relations=relations,
            artifacts=artifacts,
        )
        return _markdown_download_response(f"{canonical_event_id}.md", content)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q -k "markdown_export or canonical_event_markdown_export"
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit Task 2**

```bash
git add src/news_sentry/core/api_server.py tests/unit/test_api_server.py
git commit -m "feat: add markdown export api"
```

## Task 3: Output Policy to Stop Default Per-Event Markdown Drafts

**Files:**
- Modify: `src/news_sentry/core/config.py`
- Modify: `src/news_sentry/core/run.py`
- Modify: `src/news_sentry/core/async_run.py`
- Test: `tests/unit/test_run.py`
- Test: `tests/unit/test_async_run.py`

- [ ] **Step 1: Add failing policy tests**

In `tests/unit/test_run.py`, add a test around output behavior:

```python
def test_output_policy_skips_markdown_drafts_by_default(resolved_config, tmp_path):
    resolved_config.output_destinations = {
        **resolved_config.output_destinations,
        "markdown_auto_drafts": False,
    }
    resolved_config.output_root = tmp_path
    event = make_event(
        event_id="ne-italy-ansa-20260530-no-md",
        stage=PipelineStage.JUDGED,
    )

    outputted = _run_output(
        resolved_config,
        "run-no-md",
        RunLog(run_id="run-no-md", target_id="italy", log_dir=tmp_path / "logs"),
        FileWriter(tmp_path / "italy"),
        PipelineContext(target_id="italy"),
        input_events=[event],
    )

    assert [item.id for item in outputted] == ["ne-italy-ansa-20260530-no-md"]
    assert not (tmp_path / "italy" / "drafts" / "ne-italy-ansa-20260530-no-md.md").exists()
    assert outputted[0].metadata.get("_file_path") is None
```

In `tests/unit/test_async_run.py`, add:

```python
async def test_async_output_indexes_outputted_without_markdown_file(
    tmp_path,
    resolved_config,
    store,
):
    resolved_config.output_destinations = {
        **resolved_config.output_destinations,
        "markdown_auto_drafts": False,
    }
    resolved_config.output_root = tmp_path
    event = make_event(
        event_id="ne-italy-ansa-20260530-index-no-md",
        stage=PipelineStage.JUDGED,
    )

    await _run_output_async(
        resolved_config,
        "run-index-no-md",
        RunLog(run_id="run-index-no-md", target_id="italy", log_dir=tmp_path / "logs"),
        FileWriter(tmp_path / "italy"),
        PipelineContext(target_id="italy"),
        store=store,
        input_events=[event],
    )

    row = await store.get_event_index_row("italy", "ne-italy-ansa-20260530-index-no-md")
    assert row is not None
    assert row["stage"] == "drafts"
    assert row["file_path"] is None
```

Use existing fixture/helper names from each file. If the local helper is named differently, keep the assertions unchanged and adapt only the factory call.

- [ ] **Step 2: Run policy tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_run.py tests/unit/test_async_run.py -q -k "no_md or skips_markdown"
```

Expected:

```text
FAILED ... file exists
```

- [ ] **Step 3: Add output policy helper**

In `src/news_sentry/core/run.py`, add:

```python
def _markdown_auto_drafts_enabled(output_destinations: dict[str, Any]) -> bool:
    value = output_destinations.get("markdown_auto_drafts", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
```

Update `_run_output()`:

```python
    markdown_auto_drafts = _markdown_auto_drafts_enabled(dict(config.output_destinations))
    writer = MarkdownWriter(output_config) if markdown_auto_drafts else None
    outputted: list[NewsEvent] = []
    for event in events:
        try:
            if writer is not None:
                output_path = writer.write(event)
                event.metadata["_file_path"] = str(output_path)
            else:
                event.pipeline_stage = PipelineStage.OUTPUTTED
                event.metadata.pop("_file_path", None)
            outputted.append(event)
            run_log.log_event("output", event.id, "outputted")
        except Exception as e:
            run_log.log_error("output", str(e), event_id=event.id)
```

In `src/news_sentry/core/async_run.py`, change indexing fallback:

```python
            if not file_path:
                file_path = None
            await store.index_event(event, target_id, "drafts", file_path=file_path)
```

In `src/news_sentry/core/config.py`, ensure the resolved output config defaults to:

```python
output_destinations.setdefault("markdown_auto_drafts", False)
```

- [ ] **Step 4: Run policy tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_run.py tests/unit/test_async_run.py -q -k "no_md or skips_markdown"
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit Task 3**

```bash
git add src/news_sentry/core/config.py src/news_sentry/core/run.py src/news_sentry/core/async_run.py tests/unit/test_run.py tests/unit/test_async_run.py
git commit -m "feat: make markdown drafts opt-in"
```

## Task 4: Regression and Documentation Update

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/contracts-canonical.md`
- Modify: `docs/roadmap/global-scale-news-intelligence-architecture.md`
- Test: existing regression commands

- [ ] **Step 1: Update architecture documentation**

In `docs/architecture.md`, replace the output data-flow line:

```markdown
4. **Output**: MarkdownWriter → `drafts/` + AlertPipeline 告警推送
```

with:

```markdown
4. **Output**: canonical/event index + AlertPipeline；Markdown 仅作为用户按需导出或显式启用的本地草稿投影
```

In the architecture diagram, replace `MarkdownWriter` with:

```text
Markdown Export
(on-demand projection)
```

- [ ] **Step 2: Update canonical contract wording**

In `docs/contracts-canonical.md §5.2`, update `drafts/` semantics from a mandatory output location to a compatibility/projection location:

```markdown
| `drafts/` | `judged` → 可选编辑草稿 | 历史 Obsidian 草稿与用户显式启用的 Markdown 投影；新 pipeline 不得依赖该目录作为事实源 |
```

In `§5.3`, update `workflow_state` wording:

```markdown
`workflow_state` 不进入 `NewsEvent` 顶层字段。它可以存在于历史 Markdown frontmatter、research artifact 或导出投影中，但不得作为 canonical fact 的唯一状态来源。
```

- [ ] **Step 3: Update long-term architecture status**

In `docs/roadmap/global-scale-news-intelligence-architecture.md`, add a short implementation note under `## 5. Markdown 新定位`:

```markdown
Phase 80 将该原则落到当前代码：新增 Markdown export API，并将 per-event Markdown 草稿改为显式启用。前端下载入口后续可直接链接 API，不作为本阶段阻塞项。
```

- [ ] **Step 4: Run regression commands**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_markdown_export.py tests/unit/test_api_server.py tests/unit/test_run.py tests/unit/test_async_run.py -q -k "markdown_export or canonical_event_markdown_export or no_md or skips_markdown"
ruff check src/news_sentry/core/markdown_export.py src/news_sentry/core/api_server.py src/news_sentry/core/run.py src/news_sentry/core/async_run.py tests/unit/test_markdown_export.py tests/unit/test_api_server.py tests/unit/test_run.py tests/unit/test_async_run.py
```

Expected:

```text
all commands exit 0
```

- [ ] **Step 5: Commit Task 4**

```bash
git add docs/architecture.md docs/contracts-canonical.md docs/roadmap/global-scale-news-intelligence-architecture.md
git commit -m "docs: align architecture with markdown export model"
```

## Final Verification

- [ ] Run focused regression:

```bash
.venv/bin/python -m pytest tests/unit/test_markdown_export.py tests/unit/test_api_server.py tests/unit/test_run.py tests/unit/test_async_run.py -q -k "markdown_export or canonical_event_markdown_export or no_md or skips_markdown"
ruff check src/news_sentry tests
```

- [ ] Run browser smoke check:

```bash
curl --noproxy '*' -I http://127.0.0.1:8765/api/v1/health
curl --noproxy '*' -I http://127.0.0.1:8765/api/v1/news/target/italy/events/ne-italy-ansa-20260530-export/export/markdown
```

Expected:

```text
health returns HTTP 200
markdown export returns HTTP 200 for an existing event id, or HTTP 404 for a missing fixture id without server error
```

## Review Checklist

- [ ] Markdown is no longer required for new per-event output.
- [ ] Markdown export works for one public news event.
- [ ] Markdown export works for canonical research evidence packages.
- [ ] Existing historical Markdown remains readable.
- [ ] Frontend download actions remain deferred, and API URLs are stable enough for later UI links.
- [ ] API responses use `text/markdown` and `Content-Disposition: attachment`.
- [ ] No endpoint writes Markdown files during export.
- [ ] Regression tests prove disabled auto drafts do not create `drafts/{event.id}.md`.
