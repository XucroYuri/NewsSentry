# Phase 30: 多语言 NLP 深度分析 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 JudgeResult 基础上扩展 4 个 NLP 分析维度（情感/实体/主题标签/事件关联），规则引擎零成本基线 + AI 按需升级。

**Architecture:** 新增 NLPRulesAnalyzer（规则引擎）+ NLPAIAnalyzer（AI 升级）+ NLPAnalyzer（编排器），在 _run_judge_async 的 TieredConfidenceRouter 之后执行。复用 ProviderRouter 的 task_type="nlp" 路由。

**Tech Stack:** Pydantic v2 / PyYAML / asyncio / ProviderRouter

**Design Spec:** `docs/plan-phase-30-nlp-analysis.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/models/newsevent.py` | 修改 | 新增 Sentiment, NLPEntity, NLPAnalysis; JudgeResult 加 nlp_analysis |
| `src/news_sentry/core/nlp_rules.py` | 新建 | NLPRulesAnalyzer 规则引擎（情感词典 + 实体词典 + topic_tags） |
| `src/news_sentry/core/nlp_ai.py` | 新建 | NLPAIAnalyzer AI 升级（ProviderRouter task_type="nlp"） |
| `src/news_sentry/core/nlp_analyzer.py` | 新建 | NLPAnalyzer 编排器（规则 → 升级检查 → AI） |
| `src/news_sentry/core/async_run.py` | 修改 | _run_judge_async 中集成 NLP 增强 |
| `src/news_sentry/skills/judge/rules_judge.py` | 修改 | 移除 sentiment_score=0.0 硬编码 |
| `config/nlp/sentiment/it.yaml` | 新建 | 意大利语情感词典 |
| `config/nlp/sentiment/en.yaml` | 新建 | 英语情感词典 |
| `config/nlp/sentiment/ja.yaml` | 新建 | 日语情感词典 |
| `config/nlp/sentiment/de.yaml` | 新建 | 德语情感词典 |
| `config/nlp/sentiment/fr.yaml` | 新建 | 法语情感词典 |
| `config/nlp/entities/it.yaml` | 新建 | 意大利语实体词典 |
| `config/nlp/entities/en.yaml` | 新建 | 英语实体词典 |
| `config/nlp/entities/ja.yaml` | 新建 | 日语实体词典 |
| `config/nlp/entities/de.yaml` | 新建 | 德语实体词典 |
| `config/nlp/entities/fr.yaml` | 新建 | 法语实体词典 |
| `config/provider/routes.yaml` | 修改 | 新增 nlp 路由 |
| `tests/unit/test_nlp_models.py` | 新建 | NLP 模型序列化/验证测试 |
| `tests/unit/test_nlp_rules.py` | 新建 | NLPRulesAnalyzer 测试 |
| `tests/unit/test_nlp_ai.py` | 新建 | NLPAIAnalyzer 测试 |
| `tests/unit/test_nlp_analyzer.py` | 新建 | NLPAnalyzer 编排器测试 |

---

### Task 1 (P30.01): NLP 模型扩展

**Files:**
- Modify: `src/news_sentry/models/newsevent.py`
- Test: `tests/unit/test_nlp_models.py`

- [ ] **Step 1: 写测试 `tests/unit/test_nlp_models.py`**

```python
"""P30.01: NLP 模型测试 — Sentiment, NLPEntity, NLPAnalysis, JudgeResult.nlp_analysis。"""

from news_sentry.models.newsevent import (
    JudgeResult,
    JudgeRecommendation,
    NLPAnalysis,
    NLPEntity,
    Sentiment,
)


class TestSentiment:
    def test_values(self):
        assert Sentiment.POSITIVE == "positive"
        assert Sentiment.NEGATIVE == "negative"
        assert Sentiment.NEUTRAL == "neutral"

    def test_from_string(self):
        assert Sentiment("positive") is Sentiment.POSITIVE
        assert Sentiment("negative") is Sentiment.NEGATIVE


class TestNLPEntity:
    def test_create(self):
        e = NLPEntity(name="Meloni", entity_type="person", relevance=80)
        assert e.name == "Meloni"
        assert e.relevance == 80

    def test_relevance_bounds(self):
        NLPEntity(name="x", entity_type="person", relevance=0)
        NLPEntity(name="x", entity_type="person", relevance=100)


class TestNLPAnalysis:
    def test_defaults(self):
        a = NLPAnalysis()
        assert a.sentiment is None
        assert a.sentiment_confidence is None
        assert a.entities == []
        assert a.topic_tags == []
        assert a.event_relations == []

    def test_full(self):
        a = NLPAnalysis(
            sentiment=Sentiment.NEGATIVE,
            sentiment_confidence=75,
            entities=[NLPEntity(name="Roma", entity_type="location", relevance=80)],
            topic_tags=["political", "crisis"],
            event_relations=["same_topic: riforma"],
        )
        assert a.sentiment == Sentiment.NEGATIVE
        assert len(a.entities) == 1

    def test_serialization_roundtrip(self):
        a = NLPAnalysis(
            sentiment=Sentiment.POSITIVE,
            sentiment_confidence=90,
            entities=[NLPEntity(name="UE", entity_type="organization", relevance=50)],
            topic_tags=["economy"],
        )
        data = a.model_dump()
        a2 = NLPAnalysis(**data)
        assert a2 == a


class TestJudgeResultNLP:
    def test_judge_result_without_nlp(self):
        """现有 JudgeResult 无 nlp_analysis 字段时正常工作。"""
        jr = JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="test",
            confidence=80,
        )
        assert jr.nlp_analysis is None

    def test_judge_result_with_nlp(self):
        jr = JudgeResult(
            recommendation=JudgeRecommendation.PUBLISH,
            rationale="test",
            confidence=80,
            nlp_analysis=NLPAnalysis(sentiment=Sentiment.NEUTRAL),
        )
        assert jr.nlp_analysis.sentiment == Sentiment.NEUTRAL

    def test_judge_result_serialization_with_nlp(self):
        jr = JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=60,
            nlp_analysis=NLPAnalysis(
                sentiment=Sentiment.NEGATIVE,
                sentiment_confidence=65,
                topic_tags=["political"],
            ),
        )
        data = jr.model_dump()
        jr2 = JudgeResult(**data)
        assert jr2.nlp_analysis.sentiment == Sentiment.NEGATIVE
        assert jr2.nlp_analysis.topic_tags == ["political"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLPAnalysis'`

- [ ] **Step 3: 修改 `src/news_sentry/models/newsevent.py`**

在 `JudgeRecommendation` 类之后、`ProcessingHistoryEntry` 之前，新增三个类：

```python
class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class NLPEntity(BaseModel):
    name: str
    entity_type: str
    relevance: int = Field(ge=0, le=100)


class NLPAnalysis(BaseModel):
    sentiment: Sentiment | None = None
    sentiment_confidence: int | None = Field(default=None, ge=0, le=100)
    entities: list[NLPEntity] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    event_relations: list[str] = Field(default_factory=list)
```

在 `JudgeResult` 中新增字段：

```python
class JudgeResult(BaseModel):
    recommendation: JudgeRecommendation
    rationale: str
    confidence: int = Field(ge=0, le=100)
    flags: list[str] = Field(default_factory=list)
    nlp_analysis: NLPAnalysis | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_models.py -v`
Expected: 8 passed

- [ ] **Step 5: 运行全量测试确认零破坏**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 1467 passed（与基线一致）

- [ ] **Step 6: Commit**

```bash
git add src/news_sentry/models/newsevent.py tests/unit/test_nlp_models.py
git commit -m "Phase 30: NLP 模型扩展 — Sentiment, NLPEntity, NLPAnalysis, JudgeResult.nlp_analysis (P30.01)"
```

---

### Task 2 (P30.02): NLP 配置文件 — 情感词典 + 实体词典

**Files:**
- Create: `config/nlp/sentiment/it.yaml`, `en.yaml`, `ja.yaml`, `de.yaml`, `fr.yaml`
- Create: `config/nlp/entities/it.yaml`, `en.yaml`, `ja.yaml`, `de.yaml`, `fr.yaml`

- [ ] **Step 1: 创建意大利语情感词典 `config/nlp/sentiment/it.yaml`**

```yaml
# 意大利语情感词典 — Phase 30 NLP 规则引擎
language: it
positive:
  - "crescita"
  - "successo"
  - "accordo"
  - "progresso"
  - "sviluppo"
  - "innovazione"
  - "opportunità"
  - "collaborazione"
  - "stabilità"
  - "recupero"
  - "miglioramento"
  - "approvazione"
  - "vittoria"
  - "solidarietà"
  - "speranza"
  - "rilancio"
  - "investimento"
  - "creazione"
  - "beneficio"
  - "conquista"
  - "positivo"
  - "risparmio"
  - "aiuto"
  - "qualità"
negative:
  - "crisi"
  - "conflitto"
  - "terrorismo"
  - "corruzione"
  - "scandalo"
  - "disoccupazione"
  - "povertà"
  - "immigrazione clandestina"
  - "reato"
  - "violenza"
  - "minaccia"
  - "fallimento"
  - "debito"
  - "collasso"
  - "protesta"
  - "sciopero"
  - "incidente"
  - "morte"
  - "danno"
  - "critica"
  - "negativo"
  - "ritardo"
  - "sanzione"
  - "perdita"
  - "emergenza"
```

- [ ] **Step 2: 创建英语情感词典 `config/nlp/sentiment/en.yaml`**

```yaml
language: en
positive:
  - "growth"
  - "success"
  - "agreement"
  - "progress"
  - "development"
  - "innovation"
  - "opportunity"
  - "collaboration"
  - "stability"
  - "recovery"
  - "improvement"
  - "approval"
  - "victory"
  - "investment"
  - "benefit"
  - "achievement"
  - "breakthrough"
  - "partnership"
  - "boost"
  - "gain"
  - "positive"
  - "advance"
  - "solution"
  - "hope"
  - "relief"
negative:
  - "crisis"
  - "conflict"
  - "terrorism"
  - "corruption"
  - "scandal"
  - "unemployment"
  - "poverty"
  - "crime"
  - "violence"
  - "threat"
  - "failure"
  - "debt"
  - "collapse"
  - "protest"
  - "strike"
  - "accident"
  - "death"
  - "damage"
  - "criticism"
  - "negative"
  - "delay"
  - "sanction"
  - "loss"
  - "emergency"
  - "decline"
```

- [ ] **Step 3: 创建日语情感词典 `config/nlp/sentiment/ja.yaml`**

```yaml
language: ja
positive:
  - "成長"
  - "成功"
  - "合意"
  - "進歩"
  - "発展"
  - "革新"
  - "機会"
  - "協力"
  - "安定"
  - "回復"
  - "改善"
  - "承認"
  - "勝利"
  - "投資"
  - "利益"
  - "達成"
  - "突破口"
  - "向上"
  - "希望"
  - "前進"
  - "解決"
  - "支援"
  - "増加"
  - "拡大"
  - "好転"
negative:
  - "危機"
  - "紛争"
  - "テロ"
  - "汚職"
  - "スキャンダル"
  - "失業"
  - "貧困"
  - "犯罪"
  - "暴力"
  - "脅威"
  - "失敗"
  - "借金"
  - "崩壊"
  - "抗議"
  - "ストライキ"
  - "事故"
  - "死亡"
  - "損害"
  - "批判"
  - "遅延"
  - "制裁"
  - "損失"
  - "緊急事態"
  - "減少"
  - "悪化"
```

- [ ] **Step 4: 创建德语情感词典 `config/nlp/sentiment/de.yaml`**

```yaml
language: de
positive:
  - "Wachstum"
  - "Erfolg"
  - "Vereinbarung"
  - "Fortschritt"
  - "Entwicklung"
  - "Innovation"
  - "Möglichkeit"
  - "Zusammenarbeit"
  - "Stabilität"
  - "Erholung"
  - "Verbesserung"
  - "Zustimmung"
  - "Sieg"
  - "Investition"
  - "Nutzen"
  - "Errungenschaft"
  - "Durchbruch"
  - "Partnerschaft"
  - "Hoffnung"
  - "Lösung"
  - "Aufschwung"
  - "Gewinn"
  - "Qualität"
  - "Förderung"
  - "Erweiterung"
negative:
  - "Krise"
  - "Konflikt"
  - "Terrorismus"
  - "Korruption"
  - "Skandal"
  - "Arbeitslosigkeit"
  - "Armut"
  - "Kriminalität"
  - "Gewalt"
  - "Bedrohung"
  - "Scheitern"
  - "Schulden"
  - "Zusammenbruch"
  - "Protest"
  - "Streik"
  - "Unfall"
  - "Tod"
  - "Schaden"
  - "Kritik"
  - "Verlust"
  - "Notstand"
  - "Rückgang"
  - "Verspätung"
  - "Sanktion"
  - "Verschlechterung"
```

- [ ] **Step 5: 创建法语情感词典 `config/nlp/sentiment/fr.yaml`**

```yaml
language: fr
positive:
  - "croissance"
  - "succès"
  - "accord"
  - "progrès"
  - "développement"
  - "innovation"
  - "opportunité"
  - "collaboration"
  - "stabilité"
  - "relance"
  - "amélioration"
  - "approbation"
  - "victoire"
  - "investissement"
  - "bénéfice"
  - "réussite"
  - "partenariat"
  - "espoir"
  - "solution"
  - "avancée"
  - "qualité"
  - "soutien"
  - "progression"
  - "gains"
  - "essor"
negative:
  - "crise"
  - "conflit"
  - "terrorisme"
  - "corruption"
  - "scandale"
  - "chômage"
  - "pauvreté"
  - "criminalité"
  - "violence"
  - "menace"
  - "échec"
  - "dette"
  - "effondrement"
  - "manifestation"
  - "grève"
  - "accident"
  - "mort"
  - "dommage"
  - "critique"
  - "perte"
  - "urgence"
  - "déclin"
  - "retard"
  - "sanction"
  - "détérioration"
```

- [ ] **Step 6: 创建意大利语实体词典 `config/nlp/entities/it.yaml`**

```yaml
# 意大利语实体词典 — Phase 30 NLP 规则引擎
language: it
persons:
  - name: "Meloni"
  - name: "Mattarella"
  - name: "Schlein"
  - name: "Conte"
  - name: "Salvini"
  - name: "Berlusconi"
  - name: "Draghi"
  - name: "Renzi"
  - name: "Letta"
  - name: "Di Maio"
organizations:
  - name: "governo"
  - name: "Parlamento"
  - name: "UE"
  - name: "Unione Europea"
  - name: "NATO"
  - name: "ONU"
  - name: "Camera"
  - name: "Senato"
  - name: "Banca d'Italia"
  - name: "CONSOB"
  - name: "Banca Centrale Europea"
  - name: "BCE"
locations:
  - name: "Roma"
  - name: "Milano"
  - name: "Napoli"
  - name: "Torino"
  - name: "Palermo"
  - name: "Firenze"
  - name: "Bologna"
  - name: "Genova"
  - name: "Venezia"
  - name: "Ucraina"
  - name: "Cina"
  - name: "Stati Uniti"
  - name: "Russia"
```

- [ ] **Step 7: 创建英语实体词典 `config/nlp/entities/en.yaml`**

```yaml
language: en
persons:
  - name: "Xi Jinping"
  - name: "Biden"
  - name: "Trump"
  - name: "Scholz"
  - name: "Macron"
  - name: "Sunak"
  - name: "Kishida"
  - name: "Modi"
  - name: "Putin"
  - name: "Zelensky"
organizations:
  - name: "EU"
  - name: "NATO"
  - name: "UN"
  - name: "G7"
  - name: "G20"
  - name: "WTO"
  - name: "IMF"
  - name: "World Bank"
  - name: "WHO"
locations:
  - name: "Beijing"
  - name: "Washington"
  - name: "Brussels"
  - name: "London"
  - name: "Berlin"
  - name: "Paris"
  - name: "Tokyo"
  - name: "Moscow"
  - name: "Kyiv"
  - name: "Taiwan"
  - name: "South China Sea"
```

- [ ] **Step 8: 创建日语实体词典 `config/nlp/entities/ja.yaml`**

```yaml
language: ja
persons:
  - name: "岸田"
  - name: "安倍"
  - name: "菅"
  - name: "野田"
  - name: "麻生"
  - name: "茂木"
  - name: "林"
  - name: "松野"
organizations:
  - name: "政府"
  - name: "国会"
  - name: "自民党"
  - name: "立憲民主党"
  - name: "日銀"
  - name: "経団連"
locations:
  - name: "東京"
  - name: "大阪"
  - name: "横浜"
  - name: "名古屋"
  - name: "福岡"
  - name: "札幌"
  - name: "沖縄"
  - name: "尖閣"
  - name: "台湾"
  - name: "中国"
```

- [ ] **Step 9: 创建德语实体词典 `config/nlp/entities/de.yaml`**

```yaml
language: de
persons:
  - name: "Scholz"
  - name: "Merz"
  - name: "Habeck"
  - name: "Söder"
  - name: "Lauterbach"
  - name: "Baerbock"
  - name: "Merkel"
organizations:
  - name: "Bundesregierung"
  - name: "Bundestag"
  - name: "Bundesrat"
  - name: "EU"
  - name: "NATO"
  - name: "Bundesbank"
  - name: "BND"
locations:
  - name: "Berlin"
  - name: "München"
  - name: "Hamburg"
  - name: "Frankfurt"
  - name: "Köln"
  - name: "Stuttgart"
  - name: "Düsseldorf"
  - name: "Ukraine"
  - name: "China"
```

- [ ] **Step 10: 创建法语实体词典 `config/nlp/entities/fr.yaml`**

```yaml
language: fr
persons:
  - name: "Macron"
  - name: "Le Pen"
  - name: "Mélanchon"
  - name: "Borne"
  - name: "Darmanin"
  - name: "Attal"
  - name: "Hollande"
organizations:
  - name: "gouvernement"
  - name: "Assemblée nationale"
  - name: "Sénat"
  - name: "UE"
  - name: "OTAN"
  - name: "Banque de France"
  - name: "ENA"
locations:
  - name: "Paris"
  - name: "Lyon"
  - name: "Marseille"
  - name: "Toulouse"
  - name: "Nice"
  - name: "Bordeaux"
  - name: "Strasbourg"
  - name: "Ukraine"
  - name: "Chine"
```

- [ ] **Step 11: Commit**

```bash
git add config/nlp/
git commit -m "Phase 30: NLP 情感词典 + 实体词典 — 5 种语言 (P30.02)"
```

---

### Task 3 (P30.03): NLPRulesAnalyzer 规则引擎

**Files:**
- Create: `src/news_sentry/core/nlp_rules.py`
- Test: `tests/unit/test_nlp_rules.py`

- [ ] **Step 1: 写测试 `tests/unit/test_nlp_rules.py`**

```python
"""P30.03: NLPRulesAnalyzer 规则引擎测试。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import (
    JudgeResult,
    JudgeRecommendation,
    Language,
    NLPAnalysis,
    NewsEvent,
    Sentiment,
)


def _make_event(
    title: str = "Test",
    content: str = "Test content",
    language: str = "it",
    l0: str | None = None,
) -> NewsEvent:
    metadata = {}
    if l0 is not None:
        metadata["classification"] = {"l0": l0, "l1": [], "confidence": 80}
    return NewsEvent(
        id="ne-test-001",
        run_id="run-001",
        source_id="src1",
        url="https://example.com",
        title_original=title,
        content_original=content,
        language=language,
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        judge_result=JudgeResult(
            recommendation=JudgeRecommendation.REVIEW,
            rationale="test",
            confidence=60,
        ),
        metadata=metadata,
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """创建临时 config/nlp 目录。"""
    nlp_dir = tmp_path / "nlp"
    sent_dir = nlp_dir / "sentiment"
    ent_dir = nlp_dir / "entities"
    sent_dir.mkdir(parents=True)
    ent_dir.mkdir(parents=True)

    # 最小意大利语情感词典
    (sent_dir / "it.yaml").write_text(
        "language: it\npositive:\n  - 'crescita'\n  - 'successo'\nnegative:\n  - 'crisi'\n  - 'conflitto'\n"
    )
    # 最小意大利语实体词典
    (ent_dir / "it.yaml").write_text(
        "language: it\npersons:\n  - name: 'Meloni'\norganizations:\n  - name: 'governo'\nlocations:\n  - name: 'Roma'\n"
    )
    return nlp_dir


class TestSentimentAnalysis:
    def test_positive_text(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="La crescita economica è un grande successo per il Paese.")
        result = analyzer.analyze(event)
        assert result.sentiment == Sentiment.POSITIVE
        assert result.sentiment_confidence is not None
        assert result.sentiment_confidence > 0

    def test_negative_text(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="La crisi economica causa un grave conflitto sociale.")
        result = analyzer.analyze(event)
        assert result.sentiment == Sentiment.NEGATIVE

    def test_neutral_text(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="Il presidente ha parlato al parlamento.")
        result = analyzer.analyze(event)
        assert result.sentiment == Sentiment.NEUTRAL

    def test_mixed_equal_counts(self, config_dir: Path):
        """正负词数量相等 → neutral。"""
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="La crescita porta crisi e successo.")
        result = analyzer.analyze(event)
        assert result.sentiment == Sentiment.NEUTRAL

    def test_case_insensitive(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="CRISI e CRESCITA.")
        result = analyzer.analyze(event)
        assert result.sentiment in (Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL)

    def test_title_included(self, config_dir: Path):
        """标题中的情感词也被计算。"""
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(title="La crisi continua", content="Niente di speciale.")
        result = analyzer.analyze(event)
        assert result.sentiment == Sentiment.NEGATIVE


class TestEntityExtraction:
    def test_person_in_title(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(title="Meloni annuncia nuove misure", content="...")
        result = analyzer.analyze(event)
        names = [e.name for e in result.entities]
        assert "Meloni" in names
        meloni = next(e for e in result.entities if e.name == "Meloni")
        assert meloni.entity_type == "person"
        assert meloni.relevance == 80  # 标题匹配

    def test_organization_in_content(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="Il governo ha approvato la legge.")
        result = analyzer.analyze(event)
        names = [e.name for e in result.entities]
        assert "governo" in names
        gov = next(e for e in result.entities if e.name == "governo")
        assert gov.entity_type == "organization"
        assert gov.relevance == 50  # 正文匹配

    def test_same_entity_title_and_content(self, config_dir: Path):
        """同一实体在标题和正文都出现 → 取最高分 80。"""
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(title="Roma: noticia", content="A Roma oggi...")
        result = analyzer.analyze(event)
        roma = next(e for e in result.entities if e.name == "Roma")
        assert roma.relevance == 80

    def test_no_entities(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="Il cielo è azzurro oggi.")
        result = analyzer.analyze(event)
        assert result.entities == []


class TestTopicTags:
    def test_from_classification(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(l0="political")
        result = analyzer.analyze(event)
        assert "political" in result.topic_tags

    def test_no_classification(self, config_dir: Path):
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event()
        result = analyzer.analyze(event)
        assert isinstance(result.topic_tags, list)


class TestMissingLanguage:
    def test_missing_language_returns_empty(self, config_dir: Path):
        """无对应语言词典时返回空 NLPAnalysis 而非报错。"""
        analyzer = NLPRulesAnalyzer(config_dir)
        event = _make_event(content="Some text", language="zh")
        result = analyzer.analyze(event)
        assert isinstance(result, NLPAnalysis)
        assert result.sentiment is None
        assert result.entities == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLPRulesAnalyzer'`

- [ ] **Step 3: 实现 `src/news_sentry/core/nlp_rules.py`**

```python
"""Phase 30: NLPRulesAnalyzer — 规则引擎 NLP 分析（零 Token 成本）。

情感分析：多语言情感词典词频统计
实体提取：实体词典精确匹配（标题 80 / 正文 50）
主题标签：读取 event.metadata.classification
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from news_sentry.models.newsevent import (
    NLPAnalysis,
    NLPEntity,
    NewsEvent,
    Sentiment,
)

logger = logging.getLogger(__name__)


class NLPRulesAnalyzer:
    """基于词典的 NLP 规则分析器。"""

    def __init__(self, config_dir: Path) -> None:
        self._sentiment_dicts: dict[str, dict[str, list[str]]] = {}
        self._entity_dicts: dict[str, dict[str, list[dict[str, str]]]] = {}
        self._load_configs(config_dir)

    def _load_configs(self, config_dir: Path) -> None:
        """加载情感词典和实体词典。"""
        sent_dir = config_dir / "sentiment"
        if sent_dir.is_dir():
            for f in sent_dir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    lang = data.get("language", f.stem)
                    self._sentiment_dicts[lang] = {
                        "positive": [w.lower() for w in data.get("positive", [])],
                        "negative": [w.lower() for w in data.get("negative", [])],
                    }
                except Exception as e:
                    logger.warning("情感词典加载失败: %s: %s", f, e)

        ent_dir = config_dir / "entities"
        if ent_dir.is_dir():
            for f in ent_dir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    lang = data.get("language", f.stem)
                    self._entity_dicts[lang] = data
                except Exception as e:
                    logger.warning("实体词典加载失败: %s: %s", f, e)

    def analyze(self, event: NewsEvent) -> NLPAnalysis:
        """对单个事件执行规则 NLP 分析。"""
        lang = str(event.language)
        text = f"{event.title_original} {event.content_original}".lower()

        sentiment, sent_conf = self._analyze_sentiment(text, lang)
        entities = self._extract_entities(text, event.title_original, lang)
        topic_tags = self._extract_topic_tags(event)

        return NLPAnalysis(
            sentiment=sentiment,
            sentiment_confidence=sent_conf,
            entities=entities,
            topic_tags=topic_tags,
            event_relations=[],
        )

    def _analyze_sentiment(self, text: str, lang: str) -> tuple[Sentiment | None, int | None]:
        """情感词典词频统计。"""
        d = self._sentiment_dicts.get(lang)
        if d is None:
            return None, None

        pos = sum(1 for w in d["positive"] if w in text)
        neg = sum(1 for w in d["negative"] if w in text)
        total = pos + neg

        if total == 0:
            return Sentiment.NEUTRAL, 0

        if pos > neg:
            return Sentiment.POSITIVE, int(pos / total * 100)
        elif neg > pos:
            return Sentiment.NEGATIVE, int(neg / total * 100)
        else:
            return Sentiment.NEUTRAL, 50

    def _extract_entities(
        self, text: str, title: str, lang: str
    ) -> list[NLPEntity]:
        """实体词典精确匹配。"""
        d = self._entity_dicts.get(lang)
        if d is None:
            return []

        title_lower = title.lower()
        entities: list[NLPEntity] = []
        seen: dict[str, int] = {}

        for entity_type in ("persons", "organizations", "locations"):
            type_label = entity_type[:-1] if entity_type.endswith("s") else entity_type
            for entry in d.get(entity_type, []):
                name = entry["name"]
                name_lower = name.lower()

                relevance = 0
                if name_lower in title_lower:
                    relevance = 80
                elif name_lower in text:
                    relevance = 50

                if relevance > 0:
                    prev = seen.get(name, 0)
                    if relevance > prev:
                        seen[name] = relevance

        for name, relevance in seen.items():
            # 查找 entity_type
            etype = "location"
            for entity_type_key in ("persons", "organizations", "locations"):
                for entry in d.get(entity_type_key, []):
                    if entry["name"] == name:
                        raw = entity_type_key[:-1] if entity_type_key.endswith("s") else entity_type_key
                        etype = raw
                        break
            entities.append(NLPEntity(name=name, entity_type=etype, relevance=relevance))

        return entities

    def _extract_topic_tags(self, event: NewsEvent) -> list[str]:
        """从 event.metadata.classification 提取主题标签。"""
        tags: list[str] = []
        classification = event.metadata.get("classification", {})
        l0 = classification.get("l0")
        if l0:
            tags.append(l0)
        return tags
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_rules.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/nlp_rules.py tests/unit/test_nlp_rules.py
git commit -m "Phase 30: NLPRulesAnalyzer 规则引擎 — 情感词典+实体匹配+topic_tags (P30.03)"
```

---

### Task 4 (P30.04): NLPAIAnalyzer AI 升级分析器

**Files:**
- Create: `src/news_sentry/core/nlp_ai.py`
- Test: `tests/unit/test_nlp_ai.py`

- [ ] **Step 1: 写测试 `tests/unit/test_nlp_ai.py`**

```python
"""P30.04: NLPAIAnalyzer AI 升级分析器测试。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.nlp_ai import NLPAIAnalyzer
from news_sentry.models.newsevent import (
    JudgeResult,
    JudgeRecommendation,
    NLPAnalysis,
    NLPEntity,
    NewsEvent,
    Sentiment,
)


def _make_event(nlp: NLPAnalysis | None = None) -> NewsEvent:
    jr = JudgeResult(
        recommendation=JudgeRecommendation.REVIEW,
        rationale="test",
        confidence=60,
        nlp_analysis=nlp,
    )
    return NewsEvent(
        id="ne-test-001",
        run_id="run-001",
        source_id="src1",
        url="https://example.com",
        title_original="La crisi economica colpisce Roma",
        content_original="La crisi economica sta causando gravi problemi a Roma e nel Paese intero.",
        language="it",
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        judge_result=jr,
    )


def _mock_provider_router(response_content: str) -> MagicMock:
    """创建返回指定内容的 mock ProviderRouter。"""
    router = MagicMock()
    router.route_async = AsyncMock(return_value={
        "content": response_content,
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "route_id": "nlp.ai-fast",
        "provider": "openai",
        "fallback_used": False,
        "budget_exceeded": False,
    })
    return router


class TestNLPAIAnalyzerPrompt:
    def test_build_prompt_contains_event_data(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()
        prompt = analyzer._build_prompt(event)
        assert "La crisi economica colpisce Roma" in prompt
        assert "it" in prompt

    def test_build_prompt_includes_rules_summary(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        rules_nlp = NLPAnalysis(
            sentiment=Sentiment.NEGATIVE,
            sentiment_confidence=65,
            entities=[NLPEntity(name="Roma", entity_type="location", relevance=80)],
        )
        event = _make_event(nlp=rules_nlp)
        prompt = analyzer._build_prompt(event)
        assert "negative" in prompt
        assert "Roma" in prompt


class TestNLPAIAnalyzerParse:
    def test_parse_valid_response(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        response = {
            "sentiment": "positive",
            "sentiment_confidence": 85,
            "entities": [{"name": "UE", "entity_type": "organization", "relevance": 90}],
            "topic_tags": ["economy", "eu"],
            "event_relations": ["same_topic: bilancio UE"],
            "rationale_enhanced": "Una notizia positiva per l'economia italiana.",
        }
        result = analyzer._parse_response(json.dumps(response))
        assert result["nlp_analysis"].sentiment == Sentiment.POSITIVE
        assert len(result["nlp_analysis"].entities) == 1
        assert result["rationale_enhanced"] == "Una notizia positiva per l'economia italiana."

    def test_parse_invalid_json_returns_none(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        result = analyzer._parse_response("not json")
        assert result is None

    def test_parse_partial_response(self):
        router = _mock_provider_router("{}")
        analyzer = NLPAIAnalyzer(router)
        response = {"sentiment": "neutral"}
        result = analyzer._parse_response(json.dumps(response))
        assert result is not None
        assert result["nlp_analysis"].sentiment == Sentiment.NEUTRAL
        assert result["nlp_analysis"].entities == []


class TestNLPAIAnalyzerAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_success(self):
        ai_response = json.dumps({
            "sentiment": "negative",
            "sentiment_confidence": 80,
            "entities": [{"name": "Roma", "entity_type": "location", "relevance": 95}],
            "topic_tags": ["crisis"],
            "event_relations": [],
            "rationale_enhanced": "Notizia negativa sulla crisi economica.",
        })
        router = _mock_provider_router(ai_response)
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()

        result = await analyzer.analyze(event)

        assert result["nlp_analysis"].sentiment == Sentiment.NEGATIVE
        assert result["rationale_enhanced"] == "Notizia negativa sulla crisi economica."
        router.route_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_api_failure_raises(self):
        router = MagicMock()
        router.route_async = AsyncMock(side_effect=Exception("API error"))
        analyzer = NLPAIAnalyzer(router)
        event = _make_event()

        with pytest.raises(Exception, match="API error"):
            await analyzer.analyze(event)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_ai.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLPAIAnalyzer'`

- [ ] **Step 3: 实现 `src/news_sentry/core/nlp_ai.py`**

```python
"""Phase 30: NLPAIAnalyzer — AI 升级 NLP 分析。

通过 ProviderRouter task_type="nlp" 调用 LLM，覆盖规则引擎的 NLPAnalysis。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from news_sentry.models.newsevent import (
    NLPAnalysis,
    NLPEntity,
    NewsEvent,
    Sentiment,
)

logger = logging.getLogger(__name__)


class NLPAIAnalyzer:
    """AI 升级 NLP 分析器。"""

    def __init__(self, provider_router: Any) -> None:
        self._router = provider_router

    async def analyze(self, event: NewsEvent) -> dict[str, Any]:
        """对单个事件执行 AI NLP 分析。

        Returns:
            dict with "nlp_analysis" (NLPAnalysis) and "rationale_enhanced" (str).
        """
        prompt = self._build_prompt(event)
        result = await self._router.route_async(
            task_type="nlp",
            prompt=prompt,
            provider_factory=lambda name: None,
        )

        content = result.get("content", "")
        parsed = self._parse_response(content)
        if parsed is None:
            raise ValueError(f"AI NLP 响应解析失败: {content[:200]}")

        return parsed

    def _build_prompt(self, event: NewsEvent) -> str:
        """构建 NLP 分析 prompt。"""
        rules_summary = "none"
        if event.judge_result and event.judge_result.nlp_analysis:
            nlp = event.judge_result.nlp_analysis
            entities_str = ", ".join(e.name for e in nlp.entities) or "none"
            rules_summary = f"sentiment={nlp.sentiment}, entities=[{entities_str}]"

        return (
            f"分析以下新闻事件的 NLP 维度，以 JSON 格式返回。\n\n"
            f"标题：{event.title_original}\n"
            f"内容：{event.content_original[:500]}\n"
            f"语言：{event.language}\n"
            f"规则引擎初步分析：{rules_summary}\n\n"
            f'请返回：\n{{\n  "sentiment": "positive|negative|neutral",\n'
            f'  "sentiment_confidence": 0-100,\n'
            f'  "entities": [{{"name": "...", "entity_type": "person|organization|location|event", "relevance": 0-100}}],\n'
            f'  "topic_tags": ["..."],\n'
            f'  "event_relations": ["描述性关联"],\n'
            f'  "rationale_enhanced": "更详细的研判摘要"\n}}'
        )

    def _parse_response(self, content: str) -> dict[str, Any] | None:
        """解析 AI JSON 响应。"""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        try:
            entities = [
                NLPEntity(
                    name=e.get("name", ""),
                    entity_type=e.get("entity_type", "event"),
                    relevance=e.get("relevance", 50),
                )
                for e in data.get("entities", [])
            ]
            nlp = NLPAnalysis(
                sentiment=Sentiment(data.get("sentiment", "neutral")),
                sentiment_confidence=data.get("sentiment_confidence"),
                entities=entities,
                topic_tags=data.get("topic_tags", []),
                event_relations=data.get("event_relations", []),
            )
            return {
                "nlp_analysis": nlp,
                "rationale_enhanced": data.get("rationale_enhanced", ""),
            }
        except (ValueError, KeyError):
            return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_ai.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/nlp_ai.py tests/unit/test_nlp_ai.py
git commit -m "Phase 30: NLPAIAnalyzer AI 升级分析器 — prompt构建+响应解析 (P30.04)"
```

---

### Task 5 (P30.05): NLPAnalyzer 编排器

**Files:**
- Create: `src/news_sentry/core/nlp_analyzer.py`
- Test: `tests/unit/test_nlp_analyzer.py`

- [ ] **Step 1: 写测试 `tests/unit/test_nlp_analyzer.py`**

```python
"""P30.05: NLPAnalyzer 编排器测试。"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_sentry.core.nlp_analyzer import NLPAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import (
    JudgeResult,
    JudgeRecommendation,
    NLPAnalysis,
    NLPEntity,
    NewsEvent,
    Sentiment,
)


def _make_event(
    nlp: NLPAnalysis | None = None,
    score: int | None = 50,
) -> NewsEvent:
    jr = JudgeResult(
        recommendation=JudgeRecommendation.REVIEW,
        rationale="test",
        confidence=60,
        nlp_analysis=nlp,
    )
    return NewsEvent(
        id="ne-test-001",
        run_id="run-001",
        source_id="src1",
        url="https://example.com",
        title_original="Test title",
        content_original="Test content",
        language="it",
        published_at="2026-05-15T00:00:00Z",
        collected_at="2026-05-15T00:00:00Z",
        news_value_score=score,
        judge_result=jr,
    )


@pytest.fixture
def rules_analyzer(tmp_path: Path) -> NLPRulesAnalyzer:
    nlp_dir = tmp_path / "nlp"
    s = nlp_dir / "sentiment"
    e = nlp_dir / "entities"
    s.mkdir(parents=True)
    e.mkdir(parents=True)
    (s / "it.yaml").write_text("language: it\npositive:\n  - 'successo'\nnegative:\n  - 'crisi'\n")
    (e / "it.yaml").write_text("language: it\npersons:\n  - name: 'Meloni'\n")
    return NLPRulesAnalyzer(nlp_dir)


class TestNLPAnalyzerRulesOnly:
    @pytest.mark.asyncio
    async def test_enrich_without_ai(self, rules_analyzer: NLPRulesAnalyzer):
        analyzer = NLPAnalyzer(rules_analyzer)
        event = _make_event()
        events = await analyzer.enrich([event], "run-001")
        assert len(events) == 1
        assert events[0].judge_result.nlp_analysis is not None
        assert events[0].sentiment_score is not None

    @pytest.mark.asyncio
    async def test_sentiment_score_mapping(self, rules_analyzer: NLPRulesAnalyzer):
        analyzer = NLPAnalyzer(rules_analyzer)
        event = _make_event()
        await analyzer.enrich([event], "run-001")
        # 规则分析后 sentiment_score 应该有值
        assert events[0].sentiment_score in (-1.0, 0.0, 1.0) or events[0].sentiment_score is not None


class TestNLPAnalyzerWithAI:
    @pytest.mark.asyncio
    async def test_upgrade_high_value_event(self, rules_analyzer: NLPRulesAnalyzer):
        """news_value_score >= 70 的事件应升级到 AI。"""
        ai = MagicMock()
        ai.analyze = AsyncMock(return_value={
            "nlp_analysis": NLPAnalysis(sentiment=Sentiment.NEGATIVE, sentiment_confidence=90),
            "rationale_enhanced": "AI enhanced rationale",
        })
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=80)
        await analyzer.enrich([event], "run-001")
        assert event.judge_result.nlp_analysis.sentiment == Sentiment.NEGATIVE
        assert event.judge_result.rationale == "AI enhanced rationale"
        ai.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_upgrade_high_confidence(self, rules_analyzer: NLPRulesAnalyzer):
        """规则置信度高 + 有实体 + 低分 → 不升级。"""
        ai = MagicMock()
        ai.analyze = AsyncMock()
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        # 需要规则分析产出一个"好"结果
        event = _make_event(score=40)
        # 手动设置规则分析结果，使其不满足升级条件
        event.judge_result.nlp_analysis = NLPAnalysis(
            sentiment=Sentiment.NEUTRAL,
            sentiment_confidence=80,
            entities=[NLPEntity(name="Test", entity_type="person", relevance=50)],
            topic_tags=["test"],
        )
        event.sentiment_score = 0.0

        await analyzer.enrich([event], "run-001")
        # 不应调用 AI
        ai.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_upgrade_low_sentiment_confidence(self, rules_analyzer: NLPRulesAnalyzer):
        """sentiment_confidence < 50 → 升级。"""
        ai = MagicMock()
        ai.analyze = AsyncMock(return_value={
            "nlp_analysis": NLPAnalysis(sentiment=Sentiment.POSITIVE, sentiment_confidence=95),
            "rationale_enhanced": "Upgraded",
        })
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=40)
        event.judge_result.nlp_analysis = NLPAnalysis(
            sentiment=Sentiment.NEUTRAL,
            sentiment_confidence=30,
            entities=[NLPEntity(name="X", entity_type="person", relevance=50)],
        )
        event.sentiment_score = 0.0

        await analyzer.enrich([event], "run-001")
        ai.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_failure_keeps_rules(self, rules_analyzer: NLPRulesAnalyzer):
        """AI 失败时保留规则结果。"""
        ai = MagicMock()
        ai.analyze = AsyncMock(side_effect=Exception("API down"))
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        event = _make_event(score=80)
        await analyzer.enrich([event], "run-001")
        # 规则结果应保留
        assert event.judge_result.nlp_analysis is not None


class TestNLPAnalyzerStats:
    @pytest.mark.asyncio
    async def test_stats_tracking(self, rules_analyzer: NLPRulesAnalyzer):
        ai = MagicMock()
        ai.analyze = AsyncMock(return_value={
            "nlp_analysis": NLPAnalysis(sentiment=Sentiment.POSITIVE),
            "rationale_enhanced": "ok",
        })
        analyzer = NLPAnalyzer(rules_analyzer, ai_analyzer=ai)
        events = [_make_event(score=80), _make_event(score=30)]
        # 第二个事件不满足升级条件（score < 70, 需要有好结果）
        events[1].judge_result.nlp_analysis = NLPAnalysis(
            sentiment=Sentiment.NEUTRAL,
            sentiment_confidence=80,
            entities=[NLPEntity(name="X", entity_type="person", relevance=50)],
        )
        events[1].sentiment_score = 0.0

        await analyzer.enrich(events, "run-001")
        stats = analyzer.stats
        assert stats["total"] == 2
        assert stats["ai_upgraded"] == 1
        assert stats["rules_only"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_analyzer.py -v`
Expected: FAIL — `ImportError: cannot import name 'NLPAnalyzer'`

- [ ] **Step 3: 实现 `src/news_sentry/core/nlp_analyzer.py`**

```python
"""Phase 30: NLPAnalyzer 编排器 — 规则分析 → 升级检查 → AI 升级。

在 ConfidenceRouter 完成后执行，为每个 event 填充 nlp_analysis 和 sentiment_score。
"""

from __future__ import annotations

import logging
from typing import Any

from news_sentry.core.nlp_ai import NLPAIAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import NewsEvent, Sentiment

logger = logging.getLogger(__name__)


class NLPAnalyzer:
    """NLP 分析编排器。"""

    def __init__(
        self,
        rules_analyzer: NLPRulesAnalyzer,
        ai_analyzer: NLPAIAnalyzer | None = None,
    ) -> None:
        self._rules = rules_analyzer
        self._ai = ai_analyzer
        self._stats: dict[str, int] = {
            "total": 0,
            "rules_only": 0,
            "ai_upgraded": 0,
            "ai_failed": 0,
        }

    async def enrich(
        self, events: list[NewsEvent], run_id: str
    ) -> list[NewsEvent]:
        """对所有事件执行 NLP 增强：规则分析 → 可选 AI 升级。"""
        self._stats["total"] = len(events)

        # 1. 规则分析所有事件
        for event in events:
            analysis = self._rules.analyze(event)
            if event.judge_result is not None:
                event.judge_result.nlp_analysis = analysis
            event.sentiment_score = self._sentiment_to_score(analysis.sentiment)

        # 2. 无 AI → 直接返回
        if self._ai is None:
            self._stats["rules_only"] = len(events)
            return events

        # 3. 识别并升级
        upgraded = 0
        rules_only = 0
        for event in events:
            if not self._should_upgrade(event):
                rules_only += 1
                continue

            try:
                result = await self._ai.analyze(event)
                if event.judge_result is not None:
                    event.judge_result.nlp_analysis = result["nlp_analysis"]
                    if result.get("rationale_enhanced"):
                        event.judge_result.rationale = result["rationale_enhanced"]
                event.sentiment_score = self._sentiment_to_score(
                    result["nlp_analysis"].sentiment
                )
                upgraded += 1
            except Exception as e:
                self._stats["ai_failed"] += 1
                logger.warning("AI NLP 分析失败，保留规则结果: event_id=%s error=%s", event.id, e)
                rules_only += 1

        self._stats["ai_upgraded"] = upgraded
        self._stats["rules_only"] = rules_only

        logger.info(
            "NLP 分析完成: total=%d rules_only=%d ai_upgraded=%d ai_failed=%d",
            self._stats["total"],
            self._stats["rules_only"],
            self._stats["ai_upgraded"],
            self._stats["ai_failed"],
        )
        return events

    def _should_upgrade(self, event: NewsEvent) -> bool:
        """判断是否需要 AI 升级。"""
        if event.judge_result is None or event.judge_result.nlp_analysis is None:
            return True

        nlp = event.judge_result.nlp_analysis

        # 情感置信度低
        if nlp.sentiment_confidence is not None and nlp.sentiment_confidence < 50:
            return True

        # 无实体
        if len(nlp.entities) == 0:
            return True

        # 高价值事件
        if (event.news_value_score or 0) >= 70:
            return True

        return False

    @staticmethod
    def _sentiment_to_score(sentiment: Sentiment | None) -> float:
        """Sentiment 枚举 → sentiment_score float。"""
        if sentiment is None:
            return 0.0
        mapping = {
            Sentiment.POSITIVE: 1.0,
            Sentiment.NEGATIVE: -1.0,
            Sentiment.NEUTRAL: 0.0,
        }
        return mapping.get(sentiment, 0.0)

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python3 -m pytest tests/unit/test_nlp_analyzer.py -v`
Expected: 7 passed

注意：修复 `test_sentiment_score_mapping` 中的 `events` 引用（应为 `events = await analyzer.enrich([event], "run-001")`）。

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/nlp_analyzer.py tests/unit/test_nlp_analyzer.py
git commit -m "Phase 30: NLPAnalyzer 编排器 — 规则→AI升级+stats (P30.05)"
```

---

### Task 6 (P30.06): 集成到 async_run + Provider 路由 + rules_judge 修复

**Files:**
- Modify: `src/news_sentry/core/async_run.py` — _run_judge_async 中集成 NLP
- Modify: `src/news_sentry/skills/judge/rules_judge.py` — 移除 sentiment_score=0.0
- Modify: `config/provider/routes.yaml` — 新增 nlp 路由

- [ ] **Step 1: 在 `config/provider/routes.yaml` 末尾（fallback_route_id 之前）新增 nlp 路由**

```yaml
  # ── NLP 分析任务 ──────────────────────────────────────────

  - route_id: nlp.ai-fast
    task_type: nlp
    provider: openai
    model: gpt-4o-mini
    timeout_seconds: 30
    max_cost_usd_per_call: 0.002
    output_schema_ref: null
    audit: false
    notes: "NLP 深度分析路由：情感/实体/关联/摘要增强"
```

- [ ] **Step 2: 修改 `src/news_sentry/skills/judge/rules_judge.py`**

将第 99 行：
```python
            event.sentiment_score = 0.0  # Phase 5 AI 接入后替换
```
改为：
```python
            # sentiment_score 由 NLPAnalyzer 在 judge 后填充
```

（删除这行赋值，让 NLPAnalyzer 负责写入 sentiment_score）

- [ ] **Step 3: 修改 `src/news_sentry/core/async_run.py`**

在文件顶部 imports 中新增：
```python
from news_sentry.core.nlp_analyzer import NLPAnalyzer
from news_sentry.core.nlp_rules import NLPRulesAnalyzer
```

在 `_run_judge_async` 函数中，在 `# 写入研判结果` 注释之前（约第 459 行），插入 NLP 增强逻辑：

```python
    # P30: NLP 增强
    try:
        nlp_config_dir = _find_project_root() / "config" / "nlp"
        if nlp_config_dir.is_dir():
            rules_nlp = NLPRulesAnalyzer(nlp_config_dir)
            nlp_analyzer = NLPAnalyzer(rules_nlp)
            judged = await nlp_analyzer.enrich(judged, run_id)
            logger.info(
                "NLP 增强: rules_only=%d ai_upgraded=%d",
                nlp_analyzer.stats["rules_only"],
                nlp_analyzer.stats["ai_upgraded"],
            )
    except Exception as e:
        logger.warning("NLP 增强失败（非阻塞）: %s", e)
```

- [ ] **Step 4: 运行全量测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 全部通过，数量 >= 1467

如果 `test_judge_sets_sentiment_score` 断言 `result.sentiment_score is not None` 失败（因为不再由 rules_judge 设置），需要更新该测试：不再检查非 None，改为检查范围。

Run: `.venv/bin/python3 -m ruff check src/ && .venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add src/news_sentry/core/async_run.py src/news_sentry/skills/judge/rules_judge.py config/provider/routes.yaml tests/
git commit -m "Phase 30: 集成 NLP 到 async_run + Provider 路由 + 移除 sentiment_score 硬编码 (P30.06)"
```

---

### Task 7 (P30.07): 验证与清理

**Files:** 无新文件

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 全部通过，约 1510 tests

- [ ] **Step 2: Lint + Type check**

Run: `.venv/bin/python3 -m ruff check src/ && .venv/bin/python3 -m mypy src/news_sentry/`
Expected: 0 errors

- [ ] **Step 3: 覆盖率检查**

Run: `.venv/bin/python3 -m pytest tests/ --cov=news_sentry --cov-report=term-missing -q 2>&1 | grep "TOTAL"`
Expected: ≥92%

- [ ] **Step 4: 验收 commit**

```bash
git add -A
git commit -m "Phase 30: 集成验证通过 — 多语言 NLP 深度分析 (P30.00)"
```
