# Phase 44: 评估集扩展 + async_run 覆盖率 — 设计文档

> 日期: 2026-05-16
> 状态: 实现中
> 前置: Phase 43 开发计划文档同步完成 (1616 tests, 91% coverage)

## 1. 背景与目标

评估集 eval-set-v2.json (210 条) 存在三个盲区：

1. **无 discard 示例** — 所有 210 条的 recommendation 均为 publish/review/archive，缺少 discard（垃圾/无关/低质）的明确测试，导致 filter 阶段对 discard 边界的评估为空
2. **高 china_relevance 覆盖不足** — 当前高 relevance (>=80) 示例集中在 china_relations 维度，其他维度缺少高 relevance 交叉
3. **多 target 覆盖缺失** — 评估集 85% 面向 italy target，Japan/Germany/France 无独立示例

同时，`_run_judge_async` (135 行，async_run.py:395-529) 覆盖率 0%，是 async_run.py 69% 覆盖率的唯一大缺口。

**目标：** 评估集 210→250 (+40)，`_run_judge_async` 覆盖 0%→~80% (+~7 tests)。

## 2. 评估集扩展

### 2.1 新增分类

| 分类 | 数量 | eval_id 前缀 | 描述 |
|------|------|-------------|------|
| Discard | 10 | eval-discard-* | 垃圾/无关/低质/广告/非新闻 |
| High China Relevance | 10 | eval-china-high-* | 高 china_relevance (>=70)，覆盖经济/科技/政治/社会维度 |
| Edge Cases | 5 | eval-edge-case-* | 混语/极短标题/超长正文/特殊字符 |
| Japan | 5 | eval-japan-* | 日本政治/经济/科技/社会/中日关系 |
| Germany | 5 | eval-germany-* | 德国政治/经济/科技/社会/中德关系 |
| France | 5 | eval-france-* | 法国政治/经济/科技/社会/中法关系 |

### 2.2 文件变更

- 创建 `data/eval/eval-set-v3.json` (250 条，version="v3")
- 保留 `data/eval/eval-set-v2.json` 不动（历史基准）

## 3. async_run 测试覆盖

### 3.1 目标函数

`_run_judge_async` (async_run.py:395-529) — 异步研判阶段核心，含 6 个关键路径：

1. **空 events 提前返回** — evaluated 目录为空时直接 return
2. **TieredConfidenceRouter 成功路径** — 正常分级研判 + 统计日志
3. **TieredConfidenceRouter 回退路径** — 初始化失败 → 降级为同步 _run_judge
4. **NLP 增强** — NLPAnalyzer.enrich()，含 rules_only/ai_upgraded 统计
5. **实体持久化** — 遍历 judged events 的 NLP entities → store.upsert_entity
6. **智能告警检查** — AlertPipeline.check_smart_alerts 调用

所有非核心路径（NLP、实体、关联、叙述、告警）均以 try/except 包裹，失败不阻塞。

### 3.2 测试列表

| 测试 | 覆盖路径 | 关键 mock |
|------|---------|----------|
| test_judge_async_empty_events | 空 events 提前返回 | _load_events_from_dir → [] |
| test_judge_async_tiered_success | 正常分级研判 | mock TieredConfidenceRouter |
| test_judge_async_fallback_to_sync | 回退同步 _run_judge | ProviderRouter 返回 None |
| test_judge_async_nlp_enrichment | NLP 增强 | mock NLPAnalyzer |
| test_judge_async_entity_persistence | 实体持久化 | mock store.upsert_entity |
| test_judge_async_smart_alerts | 智能告警 | mock AlertPipeline |
| test_judge_async_nonblocking_failures | NLP/实体/告警失败不阻塞 | 各组件抛异常 |

### 3.3 文件变更

- 修改 `tests/unit/test_async_run.py` — 新增 TestRunJudgeAsync 类 (~7 tests)

## 4. 验收标准

1. 1616 后端测试零破坏
2. eval-set-v3.json 含 250 条有效 JSON，格式与 v2 兼容
3. _run_judge_async 覆盖率 >= 80%
4. ruff=0, mypy=0
