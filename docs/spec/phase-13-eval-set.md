# Phase 13 — Evaluation Set & Accuracy Benchmarking

> 状态: DONE
> 日期: 2026-05-12
> 前置: Phase 5 AI Provider Routing, Phase 6 Sandbox Hardening

---

## 目标

为 Judge（规则引擎 + AI）建立可重复的准确率基准测试，量化当前规则引擎的准确率，为后续 AI 研判优化提供对比基线。

## 交付物

| 交付物 | 路径 | 状态 |
|--------|------|------|
| Eval Example Schema | `schemas/evalexample.schema.json` | ✅ |
| Eval Set v1 (112 examples) | `data/eval/eval-set-v1.json` | ✅ |
| Eval Runner | `tools/run_eval.py` | ✅ |
| Rules Baseline Report | `data/eval/report-v1-rules-baseline.json` | ✅ |

## Eval Set 设计

### 覆盖范围

- **14 维度 × 8 示例 = 112 个评估用例**
- 13 个标准维度: politics, economics, diplomacy, security, judicial, society, technology, environment, immigration, culture, religion, china_relations, other
- 1 个边界测试维度: edge_case（短文本、非意大利语、空标题等）

### 语言分布

- it (81), en (29), mixed (1), zh (1)

### 推荐级别分布

- publish (48), review (44), archive (20)

### 预期字段

每个 eval example 包含:
- `eval_id`: 唯一标识
- `dimension`: 所属维度
- `input`: title_original + content_original + source_id + language
- `expected`: recommendation + l0_domain + news_value_score_min + china_relevance_min + sentiment_expected
- `notes`: 人工标注说明

## Rules Baseline 结果

```
Overall:
  Recommendation Accuracy: 30.4% (34/112)
  Partial Match: 38  Miss: 40
  Filtered Out: 53
  Precision: 45.9%  Recall: 45.9%  F1: 63.0%
  News Value Score Compliance: 51.8%
  China Relevance Compliance: 73.2%
```

### 分析

1. **Filtered Out (53/112)**: 规则引擎的关键词覆盖不足，大量有意义的新闻被过滤掉
2. **China Relations (75%)** 和 **Economics (75%)**: 规则关键词匹配效果最好
3. **Culture (0%)** 和 **Other (0%)**: 关键词规则几乎无法覆盖这些维度
4. **Partial Match (38)**: 相邻级别偏差（publish↔review）占比较高，说明规则引擎的阈值设置有优化空间

### 改进方向

- Phase 14+: AI Judge 接入后预期 accuracy > 70%
- 优化关键词规则覆盖，降低 filtered_out 比例
- 调整 recommendation 阈值，减少 partial miss

## 使用方式

```bash
# 运行评估（默认 italy target）
python tools/run_eval.py

# 指定 eval-set 和输出
python tools/run_eval.py --eval-set data/eval/eval-set-v1.json --output data/eval/report.json

# 指定 target
python tools/run_eval.py --target china-watch-en
```

## 验收标准

- [x] 112 个 eval examples 全部通过 `evalexample.schema.json` 校验
- [x] Eval runner 成功执行，输出 Precision/Recall/F1
- [x] Rules baseline 报告已生成
- [x] 各维度结果可追溯
