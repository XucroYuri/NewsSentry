# Phase 74 Feed Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `#/news/feed` the default news-consumption surface with richer feed API fields, readable AI reasons, flat tags, and a restrained dark-red visual baseline.

**Architecture:** Keep `NewsEvent` unchanged and extend only the `/api/v1/events/feed` presentation shape. Add small API helper functions for display fields, then update the existing Vanilla JS feed page and CSS variables without replacing the router or management views.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest, Vanilla ES modules, CSS variables.

---

### Task 1: Feed API Presentation Fields

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [x] **Step 1: Write failing filesystem-feed API test**

```python
def test_events_feed_adds_display_fields_from_frontmatter(self, tmp_path: Path) -> None:
    client = self._make_client(tmp_path)
    drafts = tmp_path / "italy" / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    event = {
        "id": "ne-italy-ansa-20260526-feed0001",
        "source_id": "ansa",
        "url": "https://example.com/news",
        "title_original": "Original title",
        "title_translated": "中文标题",
        "content_original": "Original content fallback preview.",
        "published_at": "2026-05-26T08:15:00+08:00",
        "news_value_score": 86,
        "metadata": {
            "classification": {"l0": "politics", "l1": ["china-relations"]},
            "topic_tags": ["DeepSeek", "行业动态"],
        },
        "judge_result": {"rationale": "API 长期降价会改变模型调用成本结构。第二句不应进入摘要。", "recommendation": "review"},
    }
    fm = yaml.dump(event, allow_unicode=True, default_flow_style=False, sort_keys=False)
    (drafts / "event.md").write_text(f"---\n{fm}---\n\n# 中文标题\n", encoding="utf-8")

    resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})

    assert resp.status_code == 200
    item = resp.json()["groups"][0]["events"][0]
    assert item["event_id"] == "ne-italy-ansa-20260526-feed0001"
    assert item["display_title"] == "中文标题"
    assert item["score"] == 86
    assert item["flat_tags"] == ["politics", "china-relations", "DeepSeek", "行业动态"]
    assert item["ai_reason"] == "API 长期降价会改变模型调用成本结构。"
    assert item["recommendation"] == "review"
    assert item["source_display_name"] == "ansa"
    assert item["related_count"] == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter -q`

Expected: FAIL because `/api/v1/events/feed` returns raw frontmatter without `display_title`, `score`, `flat_tags`, and `ai_reason`.

- [x] **Step 3: Implement minimal feed presentation helpers**

Add helpers near `_group_events_by_date`:

```python
def _first_sentence(text: str, max_chars: int = 60) -> str:
    compact = " ".join(text.split())
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in compact:
            compact = compact.split(sep, 1)[0] + sep
            break
    if len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def _event_score(ev: dict[str, Any]) -> int | float | None:
    score = ev.get("news_value_score", ev.get("importance_score"))
    return score if isinstance(score, (int, float)) else None


def _event_classification(ev: dict[str, Any]) -> dict[str, Any] | None:
    direct = ev.get("classification")
    if isinstance(direct, dict):
        return direct
    metadata = ev.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("classification"), dict):
        return metadata["classification"]
    return None


def _event_topic_tags(ev: dict[str, Any]) -> list[str]:
    raw = ev.get("topic_tags")
    if not raw and isinstance(ev.get("metadata"), dict):
        raw = ev["metadata"].get("topic_tags")
    return [str(t) for t in raw[:2]] if isinstance(raw, list) else []


def _event_flat_tags(ev: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    classification = _event_classification(ev)
    if classification:
        l0 = classification.get("l0")
        if l0:
            tags.append(str(l0))
        l1 = classification.get("l1")
        if isinstance(l1, list):
            tags.extend(str(x) for x in l1[:1] if x)
        elif l1:
            tags.append(str(l1))
    tags.extend(_event_topic_tags(ev))
    entities = ev.get("nlp_entities") or ev.get("entities") or []
    if isinstance(entities, list):
        for ent in entities:
            name = ent.get("name") if isinstance(ent, dict) else ent
            if name:
                tags.append(str(name))
                break
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:4]


def _event_ai_reason(ev: dict[str, Any]) -> str:
    judge = ev.get("judge_result")
    rationale = judge.get("rationale") if isinstance(judge, dict) else None
    if isinstance(rationale, str) and rationale.strip():
        return _first_sentence(rationale)
    for key in ("content_translated", "content_original"):
        value = ev.get(key)
        if isinstance(value, str) and value.strip():
            return _first_sentence(value)
    return ""


def _feed_event_payload(ev: dict[str, Any]) -> dict[str, Any]:
    event_id = ev.get("event_id") or ev.get("id") or ""
    source_id = ev.get("source_id") or ""
    judge = ev.get("judge_result") if isinstance(ev.get("judge_result"), dict) else {}
    payload = dict(ev)
    payload["event_id"] = event_id
    payload["display_title"] = ev.get("title_translated") or ev.get("title_original") or event_id
    payload["score"] = _event_score(ev)
    payload["source_display_name"] = ev.get("source_display_name") or source_id
    payload["flat_tags"] = _event_flat_tags(ev)
    payload["ai_reason"] = _event_ai_reason(ev)
    payload["recommendation"] = ev.get("recommendation") or judge.get("recommendation")
    payload["related_count"] = ev.get("related_count") or 0
    return payload
```

Update `_group_events_by_date` to append `_feed_event_payload(ev)`.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter -q`

Expected: PASS.

### Task 2: Feed Frontend Uses New Fields

**Files:**
- Modify: `src/news_sentry/static/pages/feed.js`
- Modify: `src/news_sentry/static/app.js`
- Modify: `src/news_sentry/static/index.html`
- Modify: `src/news_sentry/static/style.css`

- [x] **Step 1: Update feed rendering**

Use `display_title`, `score`, `source_display_name`, `flat_tags`, and `ai_reason` in list/card/compact views. Keep card and compact view toggles, but make list view the default timeline.

- [x] **Step 2: Update default routes**

Change default hash and sidebar news link from `#/news/overview` to `#/news/feed`. Preserve all existing management routes.

- [x] **Step 3: Remove UI emoji from touched surfaces**

Replace sidebar emoji icons and feed toggle glyphs with text or CSS-styled symbols that are not emoji. Remove emoji prefixes from realtime notification text.

- [x] **Step 4: Update red visual baseline**

Change root/light CSS variables from orange to restrained red and update feed active/hover colors that still use hard-coded orange.

### Task 3: Verification

**Files:**
- Read-only verification across touched files.

- [x] **Step 1: Run focused API tests**

Run: `.venv/bin/python3 -m pytest tests/unit/test_api_server.py::TestAPIServer::test_events_feed_adds_display_fields_from_frontmatter -q`

Expected: PASS.

- [x] **Step 2: Run static searches**

Run:

```bash
rg -n "[\\x{1F300}-\\x{1FAFF}]" src/news_sentry/static/app.js src/news_sentry/static/index.html src/news_sentry/static/pages/feed.js
rg -n "#ff8000|255, 128, 0" src/news_sentry/static/style.css src/news_sentry/static/pages/feed.js
```

Expected: no matches in touched feed/router surfaces, except unrelated CSS outside this phase may remain for later Phase C cleanup.
