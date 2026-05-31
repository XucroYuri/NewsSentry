# Feed Quality Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前 target 运行后“采集有数据但前端信息质量不稳定”的底层问题。

**Architecture:** 本阶段不新增页面，不改存储事实源，只修正 filter/classifier 的关键词匹配语义，并让公开 feed 在 SQLite 索引缺少文件路径时恢复 evaluated frontmatter，从而拿回 story/cluster 元数据并在展示层折叠重复 story。Alert history 只做幂等策略复核，除非测试暴露退化。

**Tech Stack:** Python 3.11, FastAPI, SQLite AsyncStore, Vanilla JS public feed.

---

### Task 1: 修复短英文缩写误匹配

**Files:**
- Modify: `src/news_sentry/skills/filter/rules_filter.py`
- Modify: `src/news_sentry/skills/filter/classifier_rules.py`
- Test: `tests/unit/test_rules_filter.py`
- Test: `tests/unit/test_classifier_rules.py`

- [ ] 写失败测试：`AI` 不应匹配意大利语小写介词 `ai`，但应匹配大写 acronym `AI`。
- [ ] 写失败测试：包含 `ai Mondiali di calcio` 的体育标题应进入 `sports`，不能被 `AI` 拉到 `tech`。
- [ ] 实现统一短 acronym 匹配：全大写 2-4 位 ASCII 关键词大小写敏感，其他拉丁词保留词边界不区分大小写，CJK/假名继续子串匹配。
- [ ] 运行 `pytest tests/unit/test_rules_filter.py tests/unit/test_classifier_rules.py -q`。

### Task 2: 修复公开 feed 的 story/cluster 元数据恢复

**Files:**
- Modify: `src/news_sentry/core/api_server.py`
- Test: `tests/unit/test_api_server.py`

- [ ] 写失败测试：当 `event_index.stage=drafts` 且 `file_path` 为空时，feed 应按 `event_id` 从 `evaluated/` 恢复 full frontmatter。
- [ ] 写失败测试：同一日期、同一 `story_id` 的多条事件在公开 feed 中只展示一条，并把其余数量放入 `related_count`。
- [ ] 实现 evaluated fallback，不复用不匹配 event_id 的文件。
- [ ] 在 `_group_events_by_date()` 里按 `story_id`/`cluster_id`/标准化标题折叠重复项。
- [ ] 运行 `pytest tests/unit/test_api_server.py -q`。

### Task 3: 复核 Japan 与 alert history

**Files:**
- Test: `tests/unit/test_target_filter_configs.py`
- Test: `tests/unit/test_alert_pipeline.py`
- Test: `tests/unit/test_async_store.py`

- [ ] 运行 Japan filter config 回归测试，确认现有高价值日文样本仍命中过滤。
- [ ] 运行 alert history 幂等与单轮上限测试，确认没有空 `alert_key` 和重复膨胀回归。
- [ ] 如测试失败，只修根因；如测试通过，记录为本阶段复核通过。

### Task 4: 浏览器和运行态验证

**Files:**
- No production file if previous tasks pass.

- [ ] 运行 `ruff check src/news_sentry tests`。
- [ ] 运行 `node tests/js/feed_date_collapse_test.mjs tests/js/feed_filters_test.mjs`。
- [ ] 重启本地服务后打开 Italy feed，确认重复 story 折叠、日期折叠仍可点击、runtime commit 指向 main。
