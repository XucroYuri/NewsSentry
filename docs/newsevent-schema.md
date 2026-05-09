# NewsEvent 数据结构设计

> 版本: v0.1-draft | 日期: 2026-05-09
> 状态: 开发讨论稿，待评审确认

## 设计原则

1. **Pipeline通用性** — NewsEvent 是 collect → filter → judge → output 四环节的唯一数据载体，任何skill只要能产出/消费NewsEvent即可接入
2. **渐进式丰富** — 采集环节产出最小字段集，后续环节逐步追加字段，不要求所有字段在采集时填充
3. **领域可扩展** — 以意大利涉华舆情为初始场景设计，但字段设计不绑定特定国家/议题，可通过`metadata`扩展任意领域属性
4. **多语言原生支持** — 原文和翻译分字段存储，不强制翻译，但为双语研判预留位置

---

## NewsEvent 核心Schema

```yaml
NewsEvent:
  # ── 身份标识（采集时必填）──
  id:                  string    # 确定性条目ID，格式建议: ne-{target_id}-{source_id}-{date}-{hash8}
  cluster_id:          string?   # 跨源同一事实/议题的聚合ID，filter/judge阶段填充
  story_id:            string?   # 长周期追踪故事线ID，L3追踪溯源阶段填充
  source_id:           string    # 来源标识（如 "ansa-it", "fao-rss", "weibo-cn"）
  source_url:          string    # 原文链接（URL或唯一定位符）
  collected_at:        datetime  # 采集时间戳（ISO 8601）

  # ── 内容本体（采集时必填）──
  title_original:      string    # 原文标题
  title_translated:    string?   # 翻译标题（中文），judge环节填充
  content_original:    string    # 原文正文（摘要或全文，由采集skill决定）
  content_translated:  string?   # 翻译正文，judge环节填充
  language:            string    # 原文语言代码（ISO 639-1: it, en, zh, fr...）
  content_type:        enum      # 内容形态: article | social_post | press_release | official_doc | video_transcript | podcast_transcript

  # ── 来源元信息（采集时尽量填充）──
  source_name:         string    # 来源机构名称（如 "ANSA", "FAO", "新华社"）
  source_credibility:  float?    # 来源可信度评分 0-100（filter/judge环节填充）
  author:              string?   # 作者/发布者
  published_at:        datetime? # 原文发布时间
  target_id:           string    # 当前监控目标ID（如 "italy", "eu-china", "global-food-security"）
  source_country:      string?   # 来源机构/发布主体所在国家（ISO 3166-1 alpha-2）
  involved_countries:  string[]  # 内容涉及国家列表（ISO 3166-1 alpha-2: IT, CN...）
  region:              string?   # 地区/城市（如 "Rome", "Milan"）

  # ── 管线处理标记（各环节逐步追加）──
  pipeline_stage:      enum      # 当前所处环节: collected | filtered | judged | outputted
  processing_history:  ProcessRecord[]  # 各环节处理记录（时间、skill、结果摘要）

  # ── 规则预过滤结果（filter环节追加）──
  filter_result:       FilterResult?    # 见下方子结构
  relevance_tags:      string[]?  # 初步相关性标签（如 ["italy", "china-related", "fao"]）
  matched_rules:       string[]?  # 匹配到的过滤规则ID列表
  is_urgent:           bool?      # 是否紧急（基于规则阈值判断）

  # ── LLM深度研判结果（judge环节追加）──
  judge_result:        JudgeResult?     # 见下方子结构
  news_value_score:    float?     # 新闻价值综合评分 0-100
  sentiment_score:     float?     # 情感倾向 -1(负面) 到 1(正面)，中立约0
  sentiment_label:     enum?      # positive | neutral | negative | mixed
  entities:            Entity[]?  # 提取的关键实体列表
  topic_cluster:       string?    # 主题聚类标签
  china_relevance:     float?     # 涉华相关性 0-100（本项目核心维度）
  breaking_news_level: enum?      # breaking | significant | routine | low_priority

  # ── 输出路由（output环节追加）──
  output_result:       OutputResult?    # 见下方子结构
  obsidian_path:       string?    # Obsidian vault中的存储路径
  notification_sent:   bool?      # 是否已推送通知

  # ── 可扩展领域属性 ──
  metadata:            dict       # 自由扩展字段，按领域/场景需要添加
                                 # 示例见下方 "metadata扩展场景" 章节
```

---

## 子结构定义

### FilterResult

```yaml
FilterResult:
  passed:              bool       # 是否通过过滤
  confidence:          float      # 过滤置信度 0-100
  rule_matches:        RuleMatch[]  # 各规则匹配详情
  reason:              string?    # 过滤/淘汰理由摘要

RuleMatch:
  rule_id:             string     # 规则标识（如 "keyword-china", "org-fao"）
  rule_type:           enum       # keyword | entity | source | threshold | regex
  matched_value:       string     # 实际匹配到的值
  weight:              float      # 该规则权重（用于综合评分）
```

### JudgeResult

```yaml
JudgeResult:
  judge_skill_id:      string     # 执行研判的skill标识
  judge_model:         string?    # 使用的LLM模型（如 "claude-sonnet", "gpt-4o"）
  summary:             string     # LLM生成的新闻摘要（200字以内）
  analysis:            string     # LLM生成的深度分析文本
  value_dimensions:    ValueDimension[]  # 多维度价值评分明细
  recommendation:      enum       # recommend | monitor | archive | discard
  reasoning:           string     # 研判理由（人类可读）

ValueDimension:
  dimension:           string     # 评分维度名（见下方"价值维度"章节）
  score:               float      # 该维度评分 0-100
  weight:              float      # 该维度权重，百分比，总和建议为100
  explanation:         string?    # 该维度评分理由

Entity:
  name:                string     # 实体名称
  type:                enum       # person | organization | location | event | policy | concept
  relevance:           float      # 实体与涉华议题的相关度 0-100
  aliases:             string[]?  # 实体别名（多语言/缩写）
  description:         string?    # 实体简要描述
```

### OutputResult

```yaml
OutputResult:
  output_skill_id:     string     # 执行输出的skill标识
  destinations:        Destination[]  # 各输出目标的结果
  output_timestamp:    datetime   # 输出完成时间

Destination:
  target:              enum       # obsidian | file | feishu | api | database
  path:                string?    # 输出路径/地址
  success:             bool       # 是否成功
  format:              string?    # 输出格式（markdown, json, html...）
  error:               string?    # 失败时的错误信息
```

### ProcessRecord

```yaml
ProcessRecord:
  stage:               enum       # collected | filtered | judged | outputted
  skill_id:            string     # 执行skill标识
  run_id:              string     # 本次 bounded run 的执行ID
  timestamp:           datetime   # 处理时间
  duration_ms:         int?       # 处理耗时（毫秒）
  result_summary:      string     # 处理结果一句话摘要
```

---

## 价值评分维度

新闻价值评分不是单一数字，而是多维度加权综合。以下是本项目定义的核心维度：

| 维度 | 说明 | 权重（初始，百分比） |
|------|------|-------------|
| `timeliness` | 时效性：距现在的时间越近越高 | 15 |
| `impact_scope` | 影响范围：受影响人群/机构的规模 | 20 |
| `china_relevance` | 涉华相关性：与中国利益/政策的关联度 | 25 |
| `source_authority` | 来源权威性：发布机构的公信力 | 15 |
| `novelty` | 新颖度：是否为独家/首次报道/新进展 | 10 |
| `emotion_intensity` | 情感强度：公众情绪的剧烈程度 | 5 |
| `verifiability` | 可验证性：多源交叉验证的程度 | 10 |

> 权重可通过配置文件调整，不同监控目标可设不同权重组合。
> `china_relevance` 在本项目（涉华舆情监控）中权重最高，但若监控目标切换到纯国内议题，可降低此权重。

---

## pipeline_stage 与字段填充时序

```
collected:
  必填: id, source_id, source_url, collected_at,
        title_original, content_original, language, content_type,
        source_name, target_id, involved_countries
  选填: title_translated, author, published_at, source_country, region,
        cluster_id, story_id
  空:   filter_result, judge_result, output_result

filtered:
  必填: + filter_result, relevance_tags, matched_rules
  选填: + is_urgent, source_credibility
  空:   judge_result, output_result

judged:
  必填: + judge_result, news_value_score, sentiment_score, sentiment_label
        + china_relevance, breaking_news_level
  选填: + title_translated, content_translated, entities,
        + topic_cluster, entities
  空:   output_result

outputted:
  必填: + output_result, notification_sent
  选填: + obsidian_path
  空:   无
```

---

## metadata 扩展场景

metadata 字段是自由dict，用于存放不属于核心schema但特定场景需要的属性。

### 场景0: 采集溯源

所有采集器、工具适配器和外部Skill的 provenance 统一写入 `metadata.acquisition`，不再新增采集方法、采集工具、改造来源等顶层字段。

```yaml
metadata:
  acquisition:
    method: "rss" | "api" | "tool" | "skill" | "builtin_fallback"
    source_channel_id: string
    tool_ref: string?
    skill_id: string?
    adapted_from: string?
    args_digest: string?
```

### 场景1: 意大利涉华舆情监控

```yaml
metadata:
  italy_china_context:
   涉及的在意中企:      ["海尔欧洲总部", "中远海运比雷埃夫斯港"]
    涉及的中意政要:      ["Meloni访华行程", "中国驻意大使发言"]
    涉及国际组织:       ["FAO", "WFP", "UNESCO-威尼斯"]
    舆情传播路径:       "意大利媒体→华语媒体→国内社交媒体"
    国内共鸣度预估:     70  # LLM预估该新闻在中国国内的关注度，0-100
```

### 场景2: 突发事件追踪

```yaml
metadata:
  breaking_event:
    event_type:         "natural_disaster" | "political_crisis" | "diplomatic_event" | "economic_shock"
    story_id:           string  # 关联同一事件故事线的多个新闻共享此ID
    timeline_position:  "initial_report" | "development" | "official_response" | "aftermath"
    related_story_ids:  string[]  # 关联的其他story_id
    escalation_count:   int       # 同一事件已采集的相关新闻数量
```

### 场景3: 多源交叉验证

```yaml
metadata:
  cross_validation:
    same_event_sources:  int     # 报道同一事件的不同来源数量
    source_diversity:    float   # 来源多样性评分 0-100
    contradiction_flag:  bool    # 不同来源是否存在矛盾信息
    confirmed_by:        string[]  # 已确认此新闻的其他source_id列表
```

---

## 序列化格式

NewsEvent 支持两种序列化格式：

### JSON（Pipeline内部传递 & API消费）

```json
{
  "id": "ne-2026-05-09-ansa-001",
  "source_id": "ansa-it",
  "source_url": "https://www.ansa.it/sito/notizie/...",
  "collected_at": "2026-05-09T14:30:00Z",
  "title_original": "Meloni incontra il presidente cinese...",
  "language": "it",
  "content_type": "article",
  "target_id": "italy",
  "source_country": "IT",
  "involved_countries": ["IT", "CN"],
  "pipeline_stage": "judged",
  "news_value_score": 82.5,
  "china_relevance": 90,
  "breaking_news_level": "significant",
  ...
}
```

### Markdown + YAML Frontmatter（Obsidian输出）

```markdown
---
id: ne-2026-05-09-ansa-001
source_id: ansa-it
source_url: https://www.ansa.it/sito/notizie/...
collected_at: 2026-05-09T14:30:00Z
language: it
target_id: italy
source_country: IT
involved_countries: [IT, CN]
pipeline_stage: judged
news_value_score: 82.5
china_relevance: 90
breaking_news_level: significant
sentiment_label: positive
entities:
  - name: Giorgia Meloni
    type: person
  - name: FAO
    type: organization
---

# Meloni incontra il presidente cinese...

## 中文摘要
意大利总理梅洛尼与中国国家主席会晤...

## 深度分析
此次会晤标志着中意关系的...

## 原文
Meloni incontra il presidente cinese...
```

---

## NewsEvent 生命周期

```
[采集skill] → 产出 NewsEvent(stage=collected, 核心字段)
      ↓
[过滤skill] → 读取 → 追加 filter_result → 产出 NewsEvent(stage=filtered)
      ↓                                      → 淘汰: passed=false的NewsEvent归入archive，不继续
[研判skill] → 读取 → 追加 judge_result → 产出 NewsEvent(stage=judged)
      ↓                                      → 淘汰: judge_result.recommendation=discard的归入archive
[输出skill] → 读取 → 追加 output_result → 产出 NewsEvent(stage=outputted)
      ↓                                      → 写入Obsidian/推送飞书/存入数据库
[归档]       → 所有阶段的NewsEvent最终归入持久存储，包括被淘汰的
              → 被淘汰的NewsEvent保留完整字段（含淘汰理由），用于反馈优化过滤规则
```

---

## 待讨论事项

1. **跨源故事线聚合** — `cluster_id/story_id` 的生成和关联逻辑需要进一步设计
2. **淘汰NewsEvent的保留策略** — 被filter/judge淘汰的NewsEvent保留多久？是否需要定期清理？
3. **metadata字段规范化** — 是否需要对常见扩展场景预定义schema，还是完全自由dict？
4. **多语言翻译时机** — 翻译是在judge环节统一做，还是在collect环节就做（成本更高）？
5. **文件工作流状态** — `workflow_state/review_status` 如何与 `pipeline_stage` 严格分离并投影到frontmatter？
