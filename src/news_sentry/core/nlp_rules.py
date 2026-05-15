"""Phase 30: NLPRulesAnalyzer — 规则引擎 NLP 分析（零 Token 成本）。

情感分析：多语言情感词典词频统计
实体提取：实体词典精确匹配（标题 80 / 正文 50）
主题标签：读取 event.metadata.classification
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from news_sentry.models.newsevent import NewsEvent, NLPAnalysis, NLPEntity, Sentiment

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

    def _extract_entities(self, text: str, title: str, lang: str) -> list[NLPEntity]:
        """实体词典精确匹配。"""
        d = self._entity_dicts.get(lang)
        if d is None:
            return []

        title_lower = title.lower()
        entities: list[NLPEntity] = []
        seen: dict[str, int] = {}

        for entity_type in ("persons", "organizations", "locations"):
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
                        raw = (
                            entity_type_key[:-1]
                            if entity_type_key.endswith("s")
                            else entity_type_key
                        )
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
