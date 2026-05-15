# Phase 30: 多语言 NLP 深度分析 — 设计文档

> 日期: 2026-05-15
> 状态: 设计确认
> 前置: Phase 25-29 性能优化完成 (1467 tests, 92% coverage)

## 1. 背景与目标

当前 NewsSentry 的研判输出仅有分数（news_value_score 0-100）和简单推荐（PUBLISH/REVIEW/ARCHIVE/DISCARD），缺少深层语义分析。记者/编辑看到的只是"这条新闻值 75 分"，而非"这条新闻的负面情绪指数高、涉及 Meloni 政府、与上周预算案关联"。

**目标:** 在现有 JudgeResult 基础上扩展 NLP 分析维度，采用规则 + AI 混合路线（复用 ConfidenceRouter 架构），零 Token 成本即可获得基础 NLP 维度。

**非目标:** 知识图谱构建、独立 NLP pipeline 阶段、本地 NLP 模型部署。

## 2. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 实现路线 | 规则 + AI 混合 | 复用 ConfidenceRouter，成本可控，渐进增强 |
| 实体提取配置 | 独立实体词典文件 | 与 filter config 解耦，职责清晰 |
| 事件关联 | v1 不做规则版，留空给 AI | 规则版（关键词重叠）误报率高，不值得做 |
| sentiment_score | 激活（不再硬编码 0.0） | 从 NLPAnalysis.sentiment 转换写入 |
| AI 路由 | 新增 task_type="nlp" 路由 | 复用 ProviderRouter，独立成本追踪 |
| 同步路径 | NLP 默认禁用 | 同步路径计划废弃，不值得增加异步 AI 调用 |

## 3. 模型扩展

### 3.1 新增类型

```python
class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"

class NLPEntity(BaseModel):
    name: str
    entity_type: str     # "person" / "organization" / "location" / "event"
    relevance: int = Field(ge=0, le=100)

class NLPAnalysis(BaseModel):
    sentiment: Sentiment | None = None
    sentiment_confidence: int | None = Field(default=None, ge=0, le=100)
    entities: list[NLPEntity] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    event_relations: list[str] = Field(default_factory=list)
```

### 3.2 JudgeResult 扩展

```python
class JudgeResult(BaseModel):
    recommendation: JudgeRecommendation
    rationale: str
    confidence: int = Field(ge=0, le=100)
    flags: list[str] = Field(default_factory=list)
    nlp_analysis: NLPAnalysis | None = None   # 新增，可选
```

所有新字段都有默认值，现有代码零破坏性变更。

### 3.3 sentiment_score 激活

`RulesJudgeSkill` 中不再硬编码 `event.sentiment_score = 0.0`，改为由 NLP 分析器写入：
- positive → 1.0
- negative → -1.0
- neutral → 0.0

## 4. NLP 分析器架构

### 4.1 组件关系

```
NewsEvent (judged)
      │
      ▼
[NLPRulesAnalyzer]  ← 规则引擎，零 Token 成本
  ├── 情感分析：多语言情感词典匹配
  ├── 实体提取：实体词典精确匹配
  └── 主题标签：读取现有 classification.l0/l1
      │
      ▼
[升级条件检查]
  → sentiment_confidence < 50
  → len(entities) == 0
  → news_value_score >= 70
  → 满足任一 → 升级到 AI
      │
      ▼ (升级事件)
[NLPAIAnalyzer]    ← LLM 调用，覆盖 NLPAnalysis
  ├── 语境情感判断
  ├── 命名实体识别
  ├── 语义关联分析
  └── 覆盖 rationale 为更详细的研判摘要
```

### 4.2 NLPRulesAnalyzer

**情感分析:**
- 每种语言维护情感词典 YAML (`config/nlp/sentiment/{lang}.yaml`)
- 统计正/负词命中数
- `sentiment = positive > negative ? "positive" : negative > positive ? "negative" : "neutral"`
- `sentiment_confidence = max(positive_count, negative_count) / max(total_hits, 1) * 100`

**实体提取:**
- 每种语言维护实体词典 YAML (`config/nlp/entities/{lang}.yaml`)
- 精确匹配（case-insensitive）
- `relevance` = 标题匹配 80，正文匹配 50（同一实体取最高分）

**主题标签:**
- 直接读取 `event.metadata.classification` 的 `l0` 和 `l1`
- `l1` 中每项的 `code` 转为 tag

### 4.3 NLPAIAnalyzer

**Prompt 模板:**

```
分析以下新闻事件的 NLP 维度，以 JSON 格式返回。

标题：{title_original}
内容：{content_original[:500]}
语言：{language}
规则引擎初步分析：sentiment={rules_sentiment}, entities={rules_entities}

请返回：
{
  "sentiment": "positive|negative|neutral",
  "sentiment_confidence": 0-100,
  "entities": [{"name": "...", "entity_type": "person|organization|location|event", "relevance": 0-100}],
  "topic_tags": ["..."],
  "event_relations": ["描述性关联"],
  "rationale_enhanced": "更详细的研判摘要"
}
```

**Provider 路由:**

```yaml
- route_id: nlp.rules
  task_type: nlp
  provider: rules
  model: ""
  max_cost_usd_per_call: 0

- route_id: nlp.ai-fast
  task_type: nlp
  provider: openai
  model: gpt-4o-mini
  max_cost_usd_per_call: 0.002
  fallback_route_ids: [nlp.rules]
```

### 4.4 NLPAnalyzer 编排器

```python
class NLPAnalyzer:
    def __init__(self, rules_analyzer, ai_analyzer=None, ...): ...

    def enrich(self, events: list[NewsEvent], run_id: str) -> list[NewsEvent]:
        # 1. 规则分析所有事件
        for event in events:
            analysis = self._rules_analyzer.analyze(event)
            event.judge_result.nlp_analysis = analysis
            event.sentiment_score = self._sentiment_to_score(analysis.sentiment)

        # 2. 识别需升级事件
        if self._ai_analyzer is None:
            return events

        upgrade_candidates = [e for e in events if self._should_upgrade(e)]

        # 3. AI 升级
        for event in upgrade_candidates:
            try:
                ai_analysis = self._ai_analyzer.analyze(event)
                event.judge_result.nlp_analysis = ai_analysis.nlp_analysis
                event.judge_result.rationale = ai_analysis.rationale_enhanced
                event.sentiment_score = self._sentiment_to_score(ai_analysis.sentiment)
            except Exception:
                logger.warning("AI NLP 分析失败，保留规则结果")

        return events

    def _should_upgrade(self, event) -> bool:
        nlp = event.judge_result.nlp_analysis
        if nlp is None:
            return True
        if nlp.sentiment_confidence is not None and nlp.sentiment_confidence < 50:
            return True
        if len(nlp.entities) == 0:
            return True
        if (event.news_value_score or 0) >= 70:
            return True
        return False
```

### 4.5 集成点

在 `async_run.py` 的 `_run_judge_async` 中，ConfidenceRouter 完成后追加：

```python
# 现有 judge 逻辑（不变）
events = confidence_router.judge(events, run_id)

# NLP 增强（新增）
nlp_analyzer = NLPAnalyzer(rules_analyzer=..., ai_analyzer=...)
events = nlp_analyzer.enrich(events, run_id)
```

## 5. 配置文件结构

```
config/nlp/
├── sentiment/
│   ├── it.yaml    # 意大利语情感词典 (~30-50 词)
│   ├── en.yaml    # 英语
│   ├── ja.yaml    # 日语
│   ├── de.yaml    # 德语
│   └── fr.yaml    # 法语
└── entities/
    ├── it.yaml    # 意大利语实体词典 (~20-30 实体)
    ├── en.yaml
    ├── ja.yaml
    ├── de.yaml
    └── fr.yaml
```

情感词典格式：
```yaml
# config/nlp/sentiment/it.yaml
positive:
  - "crescita"
  - "successo"
  - "accordo"
negative:
  - "crisi"
  - "conflitto"
  - "terrorismo"
```

实体词典格式：
```yaml
# config/nlp/entities/it.yaml
persons:
  - name: "Meloni"
  - name: "Mattarella"
organizations:
  - name: "governo"
  - name: "Parlamento"
locations:
  - name: "Roma"
  - name: "Milano"
```

## 6. 文件变更清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/news_sentry/models/newsevent.py` | 修改 | 新增 Sentiment、NLPEntity、NLPAnalysis；JudgeResult 加 nlp_analysis |
| `src/news_sentry/core/nlp_analyzer.py` | 新建 | NLPAnalyzer 编排器 |
| `src/news_sentry/core/nlp_rules.py` | 新建 | NLPRulesAnalyzer 规则引擎 |
| `src/news_sentry/core/nlp_ai.py` | 新建 | NLPAIAnalyzer AI 升级 |
| `src/news_sentry/core/async_run.py` | 修改 | _run_judge_async 集成 NLP |
| `src/news_sentry/skills/judge/rules_judge.py` | 修改 | 移除 sentiment_score=0.0 硬编码 |
| `config/nlp/sentiment/*.yaml` | 新建 | 5 种语言情感词典 |
| `config/nlp/entities/*.yaml` | 新建 | 5 种语言实体词典 |
| `tests/unit/test_nlp_analyzer.py` | 新建 | 编排器测试 (~8) |
| `tests/unit/test_nlp_rules.py` | 新建 | 规则引擎测试 (~15) |
| `tests/unit/test_nlp_ai.py` | 新建 | AI 升级测试 (~10) |
| `tests/unit/test_nlp_models.py` | 新建 | 模型测试 (~5) |
| `tests/integration/test_nlp_integration.py` | 新建 | 集成测试 (~5) |

## 7. 测试策略

| 层级 | 测试内容 | 数量 |
|------|---------|------|
| 模型 | NLPAnalysis、NLPEntity、Sentiment 序列化/验证 | 5 |
| 规则引擎 | 情感匹配、实体匹配、topic_tags、边界（空文本/无匹配） | 15 |
| AI 升级 | prompt 构建、响应解析、升级条件、fallback | 10 |
| 编排器 | 规则→AI 完整流程、stats、无 AI 降级 | 8 |
| 集成 | async_run NLP 增强端到端 | 5 |

约 43 个新测试，总量 1467 + 43 = 1510。

## 8. 验收标准

1. NLPAnalysis 在 JudgeResult 中可选，现有 1467 测试零破坏
2. 规则引擎为每条事件产出 NLPAnalysis（sentiment + entities + topic_tags），零 Token 成本
3. sentiment_score 不再硬编码 0.0，由 NLP 分析器写入
4. 低置信/高价值事件升级到 AI，覆盖 nlp_analysis 和 rationale
5. 5 种语言情感词典和实体词典就绪
6. Provider 路由支持 task_type="nlp"
7. 1510 tests，覆盖率 ≥92%
8. ruff=0, mypy=0

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 情感词典初始覆盖不足 | 从 filter config 关键词筛选转化，减少手工量 |
| AI 升级增加延迟 | 复用 Phase 27 批处理，并发处理低置信事件 |
| 实体词典维护成本 | 初始版只含 20-30 高频实体，AI 覆盖长尾 |
| NLP 配置遗漏语言 | 某语言无词典时降级为空 NLPAnalysis，不报错 |
