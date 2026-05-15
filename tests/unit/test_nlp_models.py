"""P30.01: NLP 模型测试 — Sentiment, NLPEntity, NLPAnalysis, JudgeResult.nlp_analysis。"""

from news_sentry.models.newsevent import (
    JudgeRecommendation,
    JudgeResult,
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
