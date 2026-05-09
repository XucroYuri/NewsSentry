# ADR-0009 — 四层新闻分类框架与 metadata.classification 字段契约

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过架构讨论确认） |
| **关联 ADR** | ADR-0001（口径规范基准）、ADR-0004（双语翻译时机）|
| **关联文档** | [新闻分类框架](../news-classification-framework.md)、[contracts-canonical.md §9](../contracts-canonical.md) |

---

## 背景

News Sentry 需要一套细粒度的新闻分类体系，以便：
1. 驱动 `news_value_score` 和 `china_relevance` 的语义计算（不仅依赖关键词）
2. 支持意大利议题的高精度事件分析（选举周期、联盟动态、中意关系）
3. 为 Phase 7 多目标扩展提供可复用的 taxonomy 框架

现有的 `NewsEvent` 顶层字段（`news_value_score`、`china_relevance`）是结果评分，不是语义分类。需要单独的分类字段。

---

## 决策

**采用 L0–L3 四层 taxonomy，意大利子分类轴独立维护，分类结果写入 `metadata.classification`，不进 schema 顶层。**

### 四层结构

| 层次 | 字段名 | 类型 | 说明 |
|---|---|---|---|
| L0 | `metadata.classification.l0` | `string` | 顶层领域（12 类固定枚举） |
| L1 | `metadata.classification.l1` | `string[]` | 子主题（每域 6–10 项，可扩展） |
| L2 | `metadata.classification.l2` | `string[]` | 实体角色类型（5 类，跨域复用） |
| L3 | `metadata.classification.l3` | `string` | 动作/状态（12 类，跨域复用） |

### metadata.classification 完整 Schema

```yaml
metadata:
  classification:
    l0: string           # 必填；枚举：politics|economy|society|tech|culture|
                         #   sports|disaster|public-safety|health|environment|
                         #   international-relations|china-related
    l1: string[]         # 必填；至少 1 项；取值见 news-classification-framework.md §2
    l2: string[]         # 可空；枚举：actor|institution|location|instrument|event-trigger
    l3: string           # 推荐；枚举：announced|proposed|passed|rejected|implemented|
                         #   suspended|leaked|under-investigation|scheduled|cancelled|
                         #   ongoing|concluded
    country_axes: array  # Italy 子轴，格式见下；其他国家按需新增
      - axis: string     # 轴名：region|coalition|scope|china-italy-rel
        value: string    # 轴值（见 news-classification-framework.md §4）
    confidence: integer|null  # 0–100；LLM 分类时填充；规则引擎时为 null
    classifier_version: string  # 格式：{type}-v{n}，如 "rules-v1"、"llm-v1"
```

### 字段位置决策

`metadata.classification` 写入 `NewsEvent.metadata.classification`，不作为顶层字段，理由：
- 分类是派生语义，非采集原始数据，适合放在 metadata 层
- 避免与 `news_value_score`、`china_relevance` 等顶层评分混用
- Phase 3 规则引擎可以不填写分类字段，backward compatible
- 与 `metadata.translation` 的层次保持一致（同类型扩展字段）

### L0 枚举稳定性规则

L0 枚举值（12 类）是**稳定的**：
- 不允许实现者自行添加新的 L0 值
- 如需新增 L0 值，必须通过新 ADR 修改本决策
- `china-related` 是专项标记，可以与其他 L0 并用

---

## 舍弃的选项

| 选项 | 拒绝原因 |
|---|---|
| 把分类写入顶层字段 | 污染 `NewsEvent` 顶层结构；Phase 3 无分类器时顶层字段出现大量 null |
| 使用单一字符串分类（如 `category: "politics.election"`） | 无法表达多标签、多层次语义 |
| 完全依赖关键词过滤替代分类 | 关键词无法捕捉 L3 动作状态（宣布 vs 通过 vs 泄露），精度不足 |
| 直接用第三方 taxonomy（如 IPTC NewsCodes） | 与意大利场景匹配度不高；增加 L0–L3 之外的学习成本 |

---

## 后果

**正面影响：**
- `news_value_score` 和 `china_relevance` 可以基于 L0/L1/L3 语义计算（见 news-classification-framework.md §7）
- 意大利子轴（region、coalition）支持精细化过滤和推送规则
- Phase 7 新增目标国只需新增 `country_axes` 定义文件，L0–L3 复用

**负面影响/约束：**
- Phase 3 Kernel MVP 不包含分类器，`metadata.classification` 可能为空（这是设计意图，不是缺陷）
- Phase 5 LLM 分类器需要设计 output schema 和 fallback 降级规则
- `classifier_version` 需要在分类器迭代时维护，防止历史事件与新分类结果不一致
