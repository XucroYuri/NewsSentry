# News Classification And Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move News Sentry from ad hoc public channel matching to a durable taxonomy + lightweight clustering + reader-facing channel model.

**Architecture:** Keep canonical classification in `metadata.classification`, add a small taxonomy compatibility module for old labels, update the rule config to the documented 12 L0 model, then add a deterministic clustering helper that assigns `cluster_id`, `story_id`, and `metadata.clustering`. The public feed continues to use a compact channel bar, but its mapping comes from taxonomy/channel adapter functions rather than one-off keyword lists.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML config files, FastAPI API server, Vanilla JS frontend modules, Node-based JS tests, pytest unit tests.

---

## File Structure

- Modify `config/classification/rules-v1.yaml`: replace the old 6-domain runtime taxonomy with the documented 12-domain L0 model and core L1 topics.
- Modify `config/classification/rules-italy.yaml`: keep Italy-specific L1 additions and align code names to hyphenated canonical topic names.
- Create `src/news_sentry/skills/filter/classification_taxonomy.py`: canonicalize old L0 names, extract normalized classification terms, and map terms to public channels.
- Modify `src/news_sentry/skills/filter/classifier_rules.py`: canonicalize classifier output and expose low-confidence candidates in `metadata.classification.candidates`.
- Create `src/news_sentry/skills/filter/event_clustering.py`: deterministic same-event/storyline clustering without external vector services.
- Modify `src/news_sentry/core/run.py`: run clustering after filter classification on the in-memory batch.
- Modify `src/news_sentry/core/api_server.py`: include clustering fields and canonical classification terms in feed payloads and target overview diagnostics.
- Modify `src/news_sentry/static/pages/feed_filters.js`: consume channel mappings from normalized taxonomy terms and story metadata.
- Modify `src/news_sentry/static/pages/feed.js`: render L0/L1 labels and story badges with graceful fallbacks.
- Modify `src/news_sentry/static/pages/target_workbench.js`: show classification distribution and uncategorized diagnostics on the target rules page.
- Test `tests/unit/test_classifier_rules.py`: taxonomy and candidate behavior.
- Test `tests/unit/test_event_clustering.py`: same-event and storyline clustering.
- Test `tests/unit/test_api_server.py`: feed payload and overview diagnostics.
- Test `tests/js/feed_filters_test.mjs`: public channel mapping for canonical and legacy taxonomy.
- Test `tests/js/feed_story_badge_test.mjs`: story badge rendering and missing-field fallback.

## Task 1: Taxonomy Compatibility And Classifier Output

**Files:**
- Create: `src/news_sentry/skills/filter/classification_taxonomy.py`
- Modify: `src/news_sentry/skills/filter/classifier_rules.py`
- Modify: `tests/unit/test_classifier_rules.py`

- [ ] **Step 1: Write failing taxonomy tests**

Append these tests to `tests/unit/test_classifier_rules.py`:

```python
from news_sentry.skills.filter.classification_taxonomy import canonical_l0, public_channel_for_terms


def test_canonical_l0_maps_legacy_runtime_labels() -> None:
    assert canonical_l0("economics") == "economy"
    assert canonical_l0("security") == "public-safety"
    assert canonical_l0("international") == "international-relations"
    assert canonical_l0("culture_society") == "society"
    assert canonical_l0("environment_energy") == "environment"


def test_public_channel_for_terms_uses_canonical_taxonomy() -> None:
    assert public_channel_for_terms(["economy", "energy"]) == "industry"
    assert public_channel_for_terms(["international-relations", "sanctions"]) == "risk"
    assert public_channel_for_terms(["tech", "ai"]) == "tech"
    assert public_channel_for_terms(["china-related"]) == "china"
```

Add this classifier behavior test:

```python
def test_classifier_outputs_canonical_l0_and_candidates() -> None:
    cfg = {
        "l0_domains": [
            {"code": "economics", "keywords_en": ["market", "trade"]},
            {"code": "tech", "keywords_en": ["semiconductor", "ai"]},
        ],
        "l1_topics": [
            {"code": "trade", "l0_domain": "economy", "keywords_en": ["trade"]},
            {"code": "semiconductor", "l0_domain": "tech", "keywords_en": ["semiconductor"]},
        ],
        "country_axes": {},
    }
    event = _make_event(title_original="Semiconductor trade market pressure", content_original="")
    result = ClassifierRules(cfg).classify(event)
    classification = result.metadata["classification"]
    assert classification["l0"] == "economy"
    assert classification["candidates"][0]["code"] == "economy"
    assert classification["candidates"][0]["hits"] >= 1
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_classifier_rules.py -q
```

Expected: fails because `classification_taxonomy` does not exist and `candidates` is not emitted.

- [ ] **Step 3: Add taxonomy compatibility module**

Create `src/news_sentry/skills/filter/classification_taxonomy.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

LEGACY_L0_ALIASES: dict[str, str] = {
    "economics": "economy",
    "security": "public-safety",
    "international": "international-relations",
    "culture_society": "society",
    "environment_energy": "environment",
    "china_related": "china-related",
}

PUBLIC_CHANNEL_TERMS: dict[str, set[str]] = {
    "policy": {"politics", "parliament", "cabinet", "coalition", "eu-affairs", "migration-policy", "justice-reform"},
    "industry": {"economy", "trade", "energy", "labor-market", "financial-markets", "corporate", "infrastructure", "environment"},
    "risk": {"international-relations", "public-safety", "disaster", "sanctions", "russia-ukraine", "nato", "terrorism"},
    "tech": {"tech", "ai", "semiconductor", "digital-policy", "cybersecurity", "research", "tech-industry"},
    "china": {"china-related", "china-italy-bilateral", "bri-italy", "chinese-investment", "china-eu-policy", "chinese-community"},
}


def canonical_l0(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "uncategorized"
    return LEGACY_L0_ALIASES.get(raw, raw)


def _term_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("code", "name", "label", "title"):
            if value.get(key):
                return str(value[key]).strip().lower()
        return ""
    return str(value).strip().lower()


def classification_terms(classification: dict[str, Any] | None) -> list[str]:
    if not isinstance(classification, dict):
        return []
    terms: list[str] = []
    l0 = canonical_l0(_term_text(classification.get("l0")))
    if l0 and l0 != "uncategorized":
        terms.append(l0)
    l1 = classification.get("l1") or []
    if not isinstance(l1, list):
        l1 = [l1]
    for item in l1:
        text = _term_text(item)
        if text:
            terms.append(text)
    return list(dict.fromkeys(terms))


def public_channel_for_terms(terms: Iterable[str]) -> str | None:
    normalized = {canonical_l0(term) for term in terms if term}
    for channel, channel_terms in PUBLIC_CHANNEL_TERMS.items():
        if normalized & channel_terms:
            return channel
    return None
```

- [ ] **Step 4: Canonicalize classifier output**

In `src/news_sentry/skills/filter/classifier_rules.py`, import the helper:

```python
from news_sentry.skills.filter.classification_taxonomy import canonical_l0
```

Update `_classify_l0()` to keep candidates:

```python
scores: list[dict[str, Any]] = []
for domain in self._l0_domains:
    count = 0
    for lang_key in self._keyword_keys(domain):
        for kw in domain.get(lang_key, []):
            if kw.lower() in text:
                count += 1
    if count > 0:
        scores.append({"code": canonical_l0(domain["code"]), "hits": count})
    if count > best_count:
        best_count = count
        best_domain = canonical_l0(domain["code"])
```

Return candidates:

```python
return {
    "domain": best_domain,
    "confidence": confidence,
    "candidates": sorted(scores, key=lambda item: item["hits"], reverse=True)[:3],
}
```

In `classify()`, include the field:

```python
"candidates": l0_result.get("candidates", []),
```

Update `_classify_l1()` to compare canonical L0 values:

```python
if canonical_l0(topic.get("l0_domain")) != canonical_l0(l0_domain):
    continue
```

- [ ] **Step 5: Verify green and commit**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_classifier_rules.py -q
```

Expected: all tests in `test_classifier_rules.py` pass.

Commit:

```bash
git add src/news_sentry/skills/filter/classification_taxonomy.py src/news_sentry/skills/filter/classifier_rules.py tests/unit/test_classifier_rules.py
git commit -m "feat: canonicalize news classification taxonomy"
```

## Task 2: Runtime Classification Rules And Feed Channel Mapping

**Files:**
- Modify: `config/classification/rules-v1.yaml`
- Modify: `config/classification/rules-italy.yaml`
- Modify: `src/news_sentry/static/pages/feed_filters.js`
- Modify: `tests/js/feed_filters_test.mjs`

- [ ] **Step 1: Write failing JS channel mapping tests**

Append to `tests/js/feed_filters_test.mjs`:

```javascript
assert.equal(
  eventMatchesChannel({
    classification: { l0: "economy", l1: ["trade"] },
    flat_tags: [],
    score: 55,
  }, "industry"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "international-relations", l1: ["sanctions"] },
    display_title: "EU sanctions debate",
  }, "risk"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "tech", l1: ["ai"] },
    display_title: "AI policy for data centers",
  }, "tech"),
  true,
);
assert.equal(
  eventMatchesChannel({
    classification: { l0: "china-related", l1: ["china-italy-bilateral"] },
    china_relevance: 10,
  }, "china"),
  true,
);
```

- [ ] **Step 2: Run JS test and verify red if mappings are incomplete**

Run:

```bash
node tests/js/feed_filters_test.mjs
```

Expected: fails for at least one canonical 12-L0 mapping that current `feed_filters.js` does not recognize.

- [ ] **Step 3: Update runtime taxonomy config**

In `config/classification/rules-v1.yaml`, replace `l0_domains` with the 12 canonical domains from `docs/news-classification-framework.md`. Use canonical code names exactly:

```yaml
l0_domains:
  - code: politics
    label_zh: "政治"
    keywords_it: [governo, parlamento, elezioni, partito, ministro, premier, senato, camera, coalizione, opposizione, legge, decreto]
    keywords_en: [government, parliament, election, party, minister, senate, coalition, opposition, law, decree]
    keywords_zh: [政府, 议会, 选举, 政党, 部长, 法律, 法令]
  - code: economy
    label_zh: "经济"
    keywords_it: [economia, PIL, inflazione, banca, mercato, lavoro, occupazione, export, spread, debito, bilancio, industria, impresa]
    keywords_en: [economy, GDP, inflation, bank, market, employment, trade, deficit, budget, industry, company]
    keywords_zh: [经济, GDP, 通胀, 银行, 市场, 就业, 贸易, 预算, 企业]
  - code: society
    label_zh: "社会"
    keywords_it: [società, scuola, istruzione, welfare, migranti, immigrazione, lavoro, famiglia, diritti]
    keywords_en: [society, school, education, welfare, migrants, immigration, family, rights]
    keywords_zh: [社会, 教育, 福利, 移民, 家庭, 权利]
  - code: tech
    label_zh: "科技"
    keywords_it: [tecnologia, digitale, intelligenza artificiale, semiconduttori, cyber, ricerca, innovazione]
    keywords_en: [technology, digital, artificial intelligence, ai, semiconductor, cyber, research, innovation]
    keywords_zh: [科技, 数字, 人工智能, 半导体, 网络安全, 科研]
  - code: culture
    label_zh: "文化"
    keywords_it: [cultura, arte, museo, cinema, musica, chiesa, religione, patrimonio]
    keywords_en: [culture, art, museum, cinema, music, church, religion, heritage]
    keywords_zh: [文化, 艺术, 博物馆, 电影, 音乐, 宗教, 遗产]
  - code: sports
    label_zh: "体育"
    keywords_it: [calcio, sport, serie a, olimpiadi, tennis, formula 1]
    keywords_en: [football, sport, olympics, tennis, formula 1]
    keywords_zh: [体育, 足球, 奥运, 网球]
  - code: disaster
    label_zh: "灾害"
    keywords_it: [terremoto, alluvione, incendio, frana, emergenza, incidente, crollo]
    keywords_en: [earthquake, flood, wildfire, landslide, emergency, accident, collapse]
    keywords_zh: [地震, 洪水, 火灾, 山体滑坡, 事故]
  - code: public-safety
    label_zh: "公共安全"
    keywords_it: [mafia, criminalità, polizia, carabinieri, arresto, indagine, terrorismo, sicurezza]
    keywords_en: [mafia, crime, police, arrest, investigation, terrorism, security]
    keywords_zh: [黑手党, 犯罪, 警察, 逮捕, 调查, 恐怖主义, 安全]
  - code: health
    label_zh: "健康"
    keywords_it: [sanità, salute, ospedale, medico, farmaco, vaccino, epidemia]
    keywords_en: [health, hospital, doctor, medicine, vaccine, epidemic]
    keywords_zh: [健康, 医院, 医生, 药品, 疫苗, 疫情]
  - code: environment
    label_zh: "环境"
    keywords_it: [ambiente, clima, energia, rinnovabili, gas, petrolio, transizione, emissioni, inquinamento]
    keywords_en: [environment, climate, energy, renewable, gas, oil, transition, emissions, pollution]
    keywords_zh: [环境, 气候, 能源, 可再生, 排放, 污染]
  - code: international-relations
    label_zh: "国际关系"
    keywords_it: [esteri, diplomatici, ambasciata, accordo, trattato, NATO, UE, Cina, Russia, USA, Ucraina, Iran, sanzioni, guerra]
    keywords_en: [foreign, diplomatic, embassy, agreement, treaty, NATO, EU, China, Russia, Ukraine, Iran, sanctions, war]
    keywords_zh: [外交, 大使馆, 协议, 条约, 北约, 欧盟, 中国, 俄罗斯, 乌克兰, 伊朗, 制裁, 战争]
  - code: china-related
    label_zh: "涉华"
    keywords_it: [Cina, cinese, Pechino, Via della Seta, BRI, comunità cinese]
    keywords_en: [China, Chinese, Beijing, Belt and Road, BRI, Chinese community]
    keywords_zh: [中国, 北京, 一带一路, 中资, 华人]
```

Update `l1_topics` with canonical L1 codes listed in the design spec. Keep existing confidence calculations unchanged.

- [ ] **Step 4: Align Italy-specific topics**

In `config/classification/rules-italy.yaml`, rename Italy-specific topic codes to canonical hyphenated values:

```yaml
l1_topics:
  - code: china-italy-bilateral
    l0_domain: china-related
    label_zh: "中意双边关系"
    keywords_it: [Cina, cinese, Belt and Road, Via della Seta, Pechino, accordo Cina-Italia]
    keywords_en: [China, Chinese, BRI, Belt Road, Beijing, China-Italy]
  - code: bri-italy
    l0_domain: china-related
    label_zh: "一带一路与意大利"
    keywords_it: [Via della Seta, memorandum, BRI, infrastrutture Cina]
    keywords_en: [Belt and Road, BRI, memorandum, China infrastructure]
  - code: china-eu-policy
    l0_domain: china-related
    label_zh: "欧盟对华政策"
    keywords_it: [dazi Cina, Bruxelles Cina, politica UE Cina, veicoli elettrici cinesi]
    keywords_en: [China tariffs, EU China policy, Chinese electric vehicles]
```

Update `country_axes.china_italy_relations.sub_axes` to use these new codes.

- [ ] **Step 5: Move frontend channel mapping to canonical terms**

In `src/news_sentry/static/pages/feed_filters.js`, replace the current scattered `terms` arrays with canonical coverage:

```javascript
const CHANNEL_TERM_MAP = {
  policy: ["politics", "parliament", "cabinet", "coalition", "eu-affairs", "migration-policy", "justice-reform"],
  industry: ["economy", "trade", "energy", "labor-market", "financial-markets", "corporate", "infrastructure", "environment", "energy-transition"],
  tech: ["tech", "ai", "semiconductor", "digital-policy", "cybersecurity", "research", "tech-industry"],
  risk: ["international-relations", "public-safety", "disaster", "sanctions", "russia-ukraine", "nato", "terrorism"],
  china: ["china-related", "china-italy-bilateral", "bri-italy", "chinese-investment", "china-eu-policy", "chinese-community"],
};
```

Keep legacy terms in the same mapping until historical data is reclassified:

```javascript
industry: [...CHANNEL_TERM_MAP.industry, "economics", "environment_energy", "energy_transition"],
risk: [...CHANNEL_TERM_MAP.risk, "security", "international"],
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
node tests/js/feed_filters_test.mjs
.venv/bin/python -m pytest tests/unit/test_classifier_rules.py -q
```

Expected: both pass.

Commit:

```bash
git add config/classification/rules-v1.yaml config/classification/rules-italy.yaml src/news_sentry/static/pages/feed_filters.js tests/js/feed_filters_test.mjs
git commit -m "feat: align feed channels with canonical taxonomy"
```

## Task 3: Lightweight Event Clustering

**Files:**
- Create: `src/news_sentry/skills/filter/event_clustering.py`
- Modify: `src/news_sentry/core/run.py`
- Test: `tests/unit/test_event_clustering.py`
- Test: `tests/unit/test_run.py`

- [ ] **Step 1: Write clustering unit tests**

Create `tests/unit/test_event_clustering.py`:

```python
from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.event_clustering import assign_lightweight_clusters


def _event(event_id: str, title: str, source: str, l0: str = "international-relations") -> NewsEvent:
    return NewsEvent(
        event_id=event_id,
        source_id=source,
        title_original=title,
        content_original="",
        metadata={"classification": {"l0": l0, "l1": ["russia-ukraine"]}},
    )


def test_assigns_same_event_cluster_for_similar_titles_from_multiple_sources() -> None:
    events = [
        _event("e1", "Italian contractor killed in Ukraine", "ansa"),
        _event("e2", "Contractor italiano ucciso in Ucraina", "rainews"),
    ]
    assign_lightweight_clusters(events, target_id="italy")
    assert events[0].cluster_id
    assert events[0].cluster_id == events[1].cluster_id
    assert events[0].metadata["clustering"]["cluster_type"] == "same_event"
    assert "source_diversity" in events[0].metadata["clustering"]["matched_by"]


def test_keeps_unrelated_events_separate() -> None:
    events = [
        _event("e1", "Italian contractor killed in Ukraine", "ansa"),
        _event("e2", "Energy prices rise across Europe", "ilsole24ore", l0="economy"),
    ]
    assign_lightweight_clusters(events, target_id="italy")
    assert events[0].cluster_id != events[1].cluster_id
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_event_clustering.py -q
```

Expected: fails because `event_clustering.py` does not exist.

- [ ] **Step 3: Implement deterministic clustering helper**

Create `src/news_sentry/skills/filter/event_clustering.py`:

```python
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.filter.classification_taxonomy import classification_terms

TOKEN_RE = re.compile(r"[\\w\\u00C0-\\u024F]+", re.UNICODE)
STOPWORDS = {"the", "and", "with", "della", "delle", "degli", "di", "in", "il", "la", "gli", "le", "un", "una"}


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text or "") if len(token) > 2 and token.lower() not in STOPWORDS}


def _similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _stable_id(prefix: str, target_id: str, seed: Iterable[str]) -> str:
    digest = hashlib.sha1("|".join([target_id, *sorted(seed)]).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{target_id}-{digest}"


def assign_lightweight_clusters(events: list[NewsEvent], target_id: str) -> list[NewsEvent]:
    token_map = {event.event_id: _tokens(event.title_original or event.title_translated or "") for event in events}
    groups: list[list[NewsEvent]] = []
    for event in events:
        placed = False
        event_terms = set(classification_terms(event.metadata.get("classification")))
        for group in groups:
            head = group[0]
            head_terms = set(classification_terms(head.metadata.get("classification")))
            if event_terms and head_terms and not (event_terms & head_terms):
                continue
            if _similarity(token_map[event.event_id], token_map[head.event_id]) >= 0.34:
                group.append(event)
                placed = True
                break
        if not placed:
            groups.append([event])

    for group in groups:
        if len(group) < 2:
            continue
        source_ids = {event.source_id or "" for event in group}
        cluster_id = _stable_id("cluster", target_id, event.event_id for event in group)
        story_id = _stable_id("story", target_id, classification_terms(group[0].metadata.get("classification")) or [cluster_id])
        matched_by = ["title_similarity"]
        if len(source_ids) > 1:
            matched_by.append("source_diversity")
        for event in group:
            event.cluster_id = cluster_id
            event.story_id = story_id
            event.metadata.setdefault("clustering", {})
            event.metadata["clustering"].update(
                {
                    "cluster_type": "same_event",
                    "confidence": 80 if len(source_ids) > 1 else 65,
                    "reason": "标题相似且分类相近，归并为同一事件",
                    "matched_by": matched_by,
                    "clustered_at": datetime.now(UTC).isoformat(),
                }
            )
    return events
```

- [ ] **Step 4: Integrate into run pipeline**

In `src/news_sentry/core/run.py`, import:

```python
from news_sentry.skills.filter.event_clustering import assign_lightweight_clusters
```

After the classifier loop in the filter phase, call:

```python
assign_lightweight_clusters(filtered, target_id=config.target_id)
```

Use the in-scope filtered event list used by the existing filter stage. If the variable name differs, use the list passed to output after classification and before judge/output writes files.

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_event_clustering.py tests/unit/test_run.py -q
```

Expected: all selected tests pass.

Commit:

```bash
git add src/news_sentry/skills/filter/event_clustering.py src/news_sentry/core/run.py tests/unit/test_event_clustering.py tests/unit/test_run.py
git commit -m "feat: add lightweight news event clustering"
```

## Task 4: Feed API And Public Card Presentation

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/static/pages/feed.js`
- Modify: `tests/unit/test_api_server.py`
- Create: `tests/js/feed_story_badge_test.mjs`

- [ ] **Step 1: Write API feed test**

Add to `tests/unit/test_api_server.py` near existing `/events/feed` tests:

```python
def test_events_feed_returns_story_metadata(tmp_path: Path) -> None:
    _write_draft(
        tmp_path,
        "italy",
        "ne-story-1",
        classification_l0="international-relations",
        metadata={
            "classification": {"l0": "international-relations", "l1": ["russia-ukraine"]},
            "clustering": {
                "cluster_type": "same_event",
                "confidence": 82,
                "matched_by": ["title_similarity", "source_diversity"],
                "reason": "标题相似且来源不同",
            },
        },
        extra_frontmatter={
            "cluster_id": "cluster-italy-abc",
            "story_id": "story-italy-ukraine",
        },
    )
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/events/feed", params={"target_id": "italy"})
    assert resp.status_code == 200
    item = resp.json()["groups"][0]["events"][0]
    assert item["cluster_id"] == "cluster-italy-abc"
    assert item["story_id"] == "story-italy-ukraine"
    assert item["clustering"]["cluster_type"] == "same_event"
    assert item["classification"]["l1"] == ["russia-ukraine"]
```

- [ ] **Step 2: Write JS story badge test**

Create `tests/js/feed_story_badge_test.mjs`:

```javascript
import assert from "node:assert/strict";

globalThis.window = { addEventListener: () => {}, location: { origin: "http://localhost" } };
globalThis.document = { body: { classList: { add: () => {}, remove: () => {} } } };
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { onLine: true, language: "zh-CN" } });
globalThis.localStorage = {};

const { storyBadge } = await import("../../src/news_sentry/static/pages/feed.js");

assert.match(
  storyBadge({ story_id: "story-1", clustering: { cluster_type: "same_event", confidence: 80 } }),
  /同一事件/,
);
assert.equal(storyBadge({}), "");

console.log("feed story badge tests passed");
```

- [ ] **Step 3: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::TestEventsFeed -q
node tests/js/feed_story_badge_test.mjs
```

Expected: fails because feed payload and `storyBadge` are not implemented.

- [ ] **Step 4: Add API fields**

In `src/news_sentry/core/api_server.py`, update the feed item builder used by `/api/v1/events/feed` to include:

```python
payload["cluster_id"] = ev.get("cluster_id")
payload["story_id"] = ev.get("story_id")
payload["clustering"] = ev.get("metadata", {}).get("clustering", {})
classification = ev.get("classification") or ev.get("metadata", {}).get("classification") or {}
payload["classification"] = classification
```

Keep existing `flat_tags` behavior unchanged.

- [ ] **Step 5: Render story badge**

In `src/news_sentry/static/pages/feed.js`, export:

```javascript
export function storyBadge(ev) {
  if (!ev?.story_id) return "";
  const type = ev.clustering?.cluster_type || "";
  const label = type === "same_event" ? "同一事件" : type === "storyline" ? "故事线" : "相关聚类";
  return `<span class="flat-tag story-tag">${escapeHtml(label)}</span>`;
}
```

In `renderTimeline()` and `renderCompact()`, place `${storyBadge(ev)}` after `${flatTags(ev)}`.

Add CSS:

```css
.story-tag {
  border-color: rgba(179, 38, 45, 0.36);
  color: var(--accent-primary);
}
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
node tests/js/feed_story_badge_test.mjs
node tests/js/feed_filters_test.mjs
```

Expected: all selected tests pass.

Commit:

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/static/pages/feed.js src/news_sentry/static/style.css tests/unit/test_api_server.py tests/js/feed_story_badge_test.mjs
git commit -m "feat: expose story clustering in public feed"
```

## Task 5: Target Workbench Diagnostics

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Modify: `src/news_sentry/static/pages/target_workbench.js`
- Modify: `tests/unit/test_api_server.py`
- Create: `tests/js/target_classification_diagnostics_test.mjs`

- [ ] **Step 1: Write overview diagnostics test**

Add to `tests/unit/test_api_server.py`:

```python
def test_admin_target_overview_includes_classification_diagnostics(tmp_path: Path) -> None:
    _insert_event_index(tmp_path, target_id="italy", event_id="e1", classification_l0="uncategorized")
    _insert_event_index(tmp_path, target_id="italy", event_id="e2", classification_l0="international-relations")
    client = _make_client(tmp_path, authenticated=True)
    resp = client.get("/api/v1/admin/targets/italy/overview")
    assert resp.status_code == 200
    diagnostics = resp.json()["classification_diagnostics"]
    assert diagnostics["distribution"]["uncategorized"] == 1
    assert diagnostics["distribution"]["international-relations"] == 1
    assert diagnostics["uncategorized_count"] == 1
```

- [ ] **Step 2: Write JS diagnostics renderer test**

Create `tests/js/target_classification_diagnostics_test.mjs`:

```javascript
import assert from "node:assert/strict";
import { classificationDiagnosticsHtml } from "../../src/news_sentry/static/pages/target_workbench.js";

const html = classificationDiagnosticsHtml({
  distribution: { "international-relations": 3, uncategorized: 2 },
  uncategorized_count: 2,
});

assert.match(html, /international-relations/);
assert.match(html, /未分类/);
assert.match(html, /2/);

console.log("target classification diagnostics tests passed");
```

- [ ] **Step 3: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py::test_admin_target_overview_includes_classification_diagnostics -q
node tests/js/target_classification_diagnostics_test.mjs
```

Expected: fails because diagnostics are missing.

- [ ] **Step 4: Add overview diagnostics**

In `src/news_sentry/core/api_server.py`, inside the admin target overview builder, query `event_index`:

```sql
SELECT COALESCE(classification_l0, 'uncategorized') AS l0, COUNT(*)
FROM event_index
WHERE target_id = ?
GROUP BY COALESCE(classification_l0, 'uncategorized')
```

Return:

```python
"classification_diagnostics": {
    "distribution": dict(distribution),
    "uncategorized_count": distribution.get("uncategorized", 0) + distribution.get("", 0),
}
```

- [ ] **Step 5: Render diagnostics on rules tab**

In `src/news_sentry/static/pages/target_workbench.js`, export:

```javascript
export function classificationDiagnosticsHtml(diagnostics = {}) {
  const distribution = diagnostics.distribution || {};
  const rows = Object.entries(distribution)
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .map(([label, count]) => `<div class="target-diagnostic-row"><span>${escapeHtml(label || "未分类")}</span><strong>${Number(count || 0)}</strong></div>`)
    .join("");
  return `<section class="target-section"><h3>分类诊断</h3><p>未分类 ${Number(diagnostics.uncategorized_count || 0)} 条</p>${rows}</section>`;
}
```

In `renderRules()`, render this block before the editable rule form:

```javascript
${classificationDiagnosticsHtml(overview.classification_diagnostics)}
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_api_server.py -q
node tests/js/target_classification_diagnostics_test.mjs
```

Expected: selected tests pass.

Commit:

```bash
git add src/news_sentry/core/api_server.py src/news_sentry/static/pages/target_workbench.js tests/unit/test_api_server.py tests/js/target_classification_diagnostics_test.mjs
git commit -m "feat: show classification diagnostics in target workbench"
```

## Final Verification

- [ ] Run Python unit tests touched by the plan:

```bash
.venv/bin/python -m pytest tests/unit/test_classifier_rules.py tests/unit/test_event_clustering.py tests/unit/test_api_server.py tests/unit/test_run.py -q
```

- [ ] Run JS tests touched by the plan:

```bash
node tests/js/feed_filters_test.mjs
node tests/js/feed_story_badge_test.mjs
node tests/js/target_classification_diagnostics_test.mjs
```

- [ ] Run syntax checks:

```bash
node --check src/news_sentry/static/pages/feed.js src/news_sentry/static/pages/feed_filters.js src/news_sentry/static/pages/target_workbench.js
ruff check src/news_sentry/skills/filter/classifier_rules.py src/news_sentry/skills/filter/classification_taxonomy.py src/news_sentry/skills/filter/event_clustering.py src/news_sentry/core/run.py src/news_sentry/core/api_server.py
```

- [ ] Browser verification:

Open `http://localhost:8765/#/news/target/italy` and verify:

- Top channels are not mostly empty.
- Events show L0/L1 tags and story badges when present.
- Duplicate multi-source items are visibly grouped or marked.

Open `http://localhost:8765/#/admin/targets/italy/rules` and verify:

- Classification distribution is visible.
- Uncategorized count is visible.
- Rule editing remains available.
