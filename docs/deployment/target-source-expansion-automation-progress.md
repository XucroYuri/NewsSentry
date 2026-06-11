# News Sentry target/source 扩容自动化账本

> 自动化: `news-sentry-target-source-expansion-rollout`
> 起始日期: 2026-06-12
> 总目标轮次: 100
> 规则: 每轮先读本账本，再决定新增 target、既有 target 维护、最少信源 target 复查与是否部署。

## 当前状态

- current_round: 2
- completed_rounds: 1
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
- deploy_status: preview_partial
- preview_release_branch: `codex/target-source-expansion-r001-india`
- preview_release_sha: `a1cd681`
- preview_branch_merge_sha: `cabf7de`
- preview_deploy_run: `27382719432`
- preview_deploy_job: `80923731265`
- preview_external_health: `curl https://preview.news-sentry.com/api/v1/health` -> `SSL_ERROR_SYSCALL`
- preview_targets_api: `curl https://preview.news-sentry.com/api/v1/targets` -> failed with same TLS error
- preview_remote_deploy_sha_check: blocked
- preview_remote_deploy_sha_reason: direct SSH to VPS and documented jump-host SSH both unavailable in current environment
- production_status: skipped
- production_skip_reason: preview workflow succeeded, but preview 外部 health / targets 与 VPS `.deploy-sha` 无法按闸门完成实证验证，因此不推进 `main`

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
| 1 | 2026-06-12T06:42:43+08:00 | new_target | india | 印度新闻监控 | 0 | 6 | thehindu-india,thehindu-business,thehindu-world,indianexpress-india,indianexpress-business,toi-india | 0 | 0 | static checks passed; pytest passed; collect smoke 6/6 ok, 180 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 选择热度稳定且 RSS 可验证的印度国别 target，避免新增空 target |
| 1 | 2026-06-12T06:42:43+08:00 | optimize_existing | china-watch-en | 涉中新闻监控 | 14 | 16 | dw-en-all,aljazeera-global | 0 | 0 | collect smoke 15/15 ok, 187 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 当前最少信源且未冷却的已跟踪 target，补欧洲与 Global South 公开信源广度 |
| 1 | 2026-06-12T06:42:43+08:00 | weak_target_maintenance | fusion | Fusion Codes Intelligence | 7 | 7 | 0 | 0 | 0 | readonly only | skipped | 当前最少信源 target 但存在用户未提交脏改，本轮只记录状态和建议，不重复覆盖 |

## 第 1 轮结论

- 已完成新增 target: `india`
- 已完成既有 target 扩容: `china-watch-en` 14 -> 16
- 预览部署: GitHub Actions `Deploy preview` 成功
- 阻断项: `preview.news-sentry.com` TLS/health 不通，且当前环境无法 SSH 读取 VPS `.deploy-sha`
- 因此本轮不推 `main`，生产环境保持不变

## 下一轮建议

- 优先补齐 `preview.news-sentry.com` 的公网可达性与证书链，确保 preview 外部 health 可验
- 若下轮仍无 SSH 能力，至少补一条可公开读取当前 preview 版本号/branch 的诊断端点，再决定是否允许 main 推进
- `china-watch-en` 与 `india` 已进入最近 12 轮冷却，下一轮不要再作为主优化对象
