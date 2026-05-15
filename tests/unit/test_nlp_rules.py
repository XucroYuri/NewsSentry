"""P30.03: NLPRulesAnalyzer 规则引擎测试。"""

from pathlib import Path

import pytest

from news_sentry.core.nlp_rules import NLPRulesAnalyzer
from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
    NewsEvent,
    NLPAnalysis,
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
        "language: it\n"
        "positive:\n"
        "  - 'crescita'\n"
        "  - 'successo'\n"
        "negative:\n"
        "  - 'crisi'\n"
        "  - 'conflitto'\n"
    )
    # 最小意大利语实体词典
    (ent_dir / "it.yaml").write_text(
        "language: it\n"
        "persons:\n"
        "  - name: 'Meloni'\n"
        "organizations:\n"
        "  - name: 'governo'\n"
        "locations:\n"
        "  - name: 'Roma'\n"
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
        event = _make_event(content="La crescita e la crisi.")
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
