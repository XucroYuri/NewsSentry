# News Sentry target/source 扩容自动化账本

> 自动化: `news-sentry-target-source-expansion-rollout`
> 起始日期: 2026-06-12
> 总目标轮次: 100
> 规则: 每轮先读本账本，再决定新增 target、既有 target 维护、最少信源 target 复查与是否部署。

## 当前状态

- current_round: 1
- completed_rounds: 0
- status: active
- stop_after_round: 100

## 第 1 轮进行中摘要

- round: 1
- timestamp: 2026-06-12T06:42:43+08:00
- recent_12_touched_targets_before_round: []
- cooldown_skips_this_round: []
- selected_new_target: `india`
- selected_existing_target: `china-watch-en`
- weakest_target_readonly_check: `fusion`
- weakest_target_readonly_reason: `fusion` 当前存在用户未提交脏改（`config/targets/fusion.yaml` 等），本轮只做只读建议，不覆盖用户现场。
- existing_target_selection_reason: `china-watch-en` 是当前已跟踪且可安全操作的最少信源 target（14）；本地 source health 全绿，适合在不碰用户脏改的前提下补公开 RSS 广度。
- new_target_selection_reason: `india` 在 2026-06 仍具高热度（BRICS 主席年、中印关系回暖与边境/制造/海上安全议题并行），且存在多条可直接验证的公开英文 RSS。
- validation_progress:
  - `git diff --check` passed
  - `tools/scan_sensitive_data.py` passed
  - `tools/check_no_hardcoded_target.py` passed
  - `pytest tests/unit/test_config_schema_validation.py tests/unit/test_india_target_configs.py -q` passed
  - collect smoke: `india` 6/6 sources ok, `china-watch-en` 15/15 sources ok
- deploy_status: pending

## 最近 12 轮 touched_targets

| round | target_id | role | action | notes |
| --- | --- | --- | --- | --- |
| 1 | india | new_target | add | 新增英文印度 target，已通过 6/6 RSS collect smoke |
| 1 | china-watch-en | optimize_existing | expand_sources | 从 14 源扩到 16 源，新增 DW / Al Jazeera 公共 RSS |

## 最近 20 轮 candidate_new_targets

| round | candidate_id | decision | similarity_check | notes |
| --- | --- | --- | --- | --- |
| 1 | india | added | 与现有 target、账本候选无重复 | 热度、公开 RSS 可得性、英文入口三项同时满足 |

## target 作业记录表

| round | timestamp | action_type | target_id | target_label | source_count_before | source_count_after | added_sources | removed_sources | social_accounts_added | validation_result | deploy_result | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-06-12T06:42:43+08:00 | new_target | india | 印度新闻监控 | 0 | 6 | thehindu-india,thehindu-business,thehindu-world,indianexpress-india,indianexpress-business,toi-india | 0 | 0 | static checks passed; pytest passed; collect smoke 6/6 ok, 180 items | pending | 选择热度稳定且 RSS 可验证的印度国别 target，避免新增空 target |
| 1 | 2026-06-12T06:42:43+08:00 | optimize_existing | china-watch-en | 涉中新闻监控 | 14 | 16 | dw-en-all,aljazeera-global | 0 | 0 | collect smoke 15/15 ok, 187 items | pending | 当前最少信源且未冷却的已跟踪 target，补欧洲与 Global South 公开信源广度 |
| 1 | 2026-06-12T06:42:43+08:00 | weak_target_maintenance | fusion | Fusion Codes Intelligence | 7 | 7 | 0 | 0 | 0 | readonly only | skipped | 当前最少信源 target 但存在用户未提交脏改，本轮只记录状态和建议，不重复覆盖 |
