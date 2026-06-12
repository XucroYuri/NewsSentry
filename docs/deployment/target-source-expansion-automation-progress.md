# News Sentry target/source 扩容自动化账本

> 自动化: `news-sentry-target-source-expansion-rollout`
> 起始日期: 2026-06-12
> 总目标轮次: 100
> 规则: 每轮先读本账本，再决定新增 target、既有 target 维护、最少信源 target 复查与是否部署。

## 当前状态

- current_round: 3
- completed_rounds: 2
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
| 2 | south-korea | new_target | add | 新增韩国 target，5/5 RSS collect smoke 通过，preview `/targets` 可见 |
| 2 | france | optimize_existing | expand_sources | 从 21 源扩到 25 源，补入 France24 / RFI / Le Parisien 政经 RSS |

## 最近 20 轮 candidate_new_targets

| round | candidate_id | decision | similarity_check | notes |
| --- | --- | --- | --- | --- |
| 1 | india | added | 与现有 target、账本候选无重复 | 热度、公开 RSS 可得性、英文入口三项同时满足 |
| 2 | south-korea | added | 与现有 target、最近 20 轮候选无重复；虽与 `japan` 同属东北亚，但国别范围、议题重心、来源矩阵独立 | 2026-06 韩国地方选举余波、李在明政府议程、半导体与半岛安全热度并行，且 5 条英文 RSS 已实证可用 |

## target 作业记录表

| round | timestamp | action_type | target_id | target_label | source_count_before | source_count_after | added_sources | removed_sources | social_accounts_added | validation_result | deploy_result | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-06-12T06:42:43+08:00 | new_target | india | 印度新闻监控 | 0 | 6 | thehindu-india,thehindu-business,thehindu-world,indianexpress-india,indianexpress-business,toi-india | 0 | 0 | static checks passed; pytest passed; collect smoke 6/6 ok, 180 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 选择热度稳定且 RSS 可验证的印度国别 target，避免新增空 target |
| 1 | 2026-06-12T06:42:43+08:00 | optimize_existing | china-watch-en | 涉中新闻监控 | 14 | 16 | dw-en-all,aljazeera-global | 0 | 0 | collect smoke 15/15 ok, 187 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 当前最少信源且未冷却的已跟踪 target，补欧洲与 Global South 公开信源广度 |
| 1 | 2026-06-12T06:42:43+08:00 | weak_target_maintenance | fusion | Fusion Codes Intelligence | 7 | 7 | 0 | 0 | 0 | readonly only | skipped | 当前最少信源 target 但存在用户未提交脏改，本轮只记录状态和建议，不重复覆盖 |
| 2 | 2026-06-12T11:35:00+08:00 | new_target | south-korea | 韩国新闻监控 | 0 | 5 | yonhap-en-all,yonhap-national,korea-times-all,korea-herald-all,hankyoreh-english | 0 | 0 | static checks passed; pytest passed; collect smoke 5/5 ok, 175 items | preview workflow 27393376925 success after sandbox allowlist fix; production skipped | 与现有 target、最近 20 轮候选不重复；热点明确且 5 条英文 RSS 已实证可用 |
| 2 | 2026-06-12T11:35:00+08:00 | optimize_existing | france | 法国新闻监控 | 21 | 25 | leparisien-politique,leparisien-economie,rfi-france,france24-france | 0 | 0 | collect smoke 25/25 ok, 220 items | preview workflow 27393376925 success after sandbox allowlist fix; production skipped | 当前未冷却 target 中信源最少，且新增 4 条法语公开 RSS 后仍保持全绿采集 |
| 2 | 2026-06-12T11:35:00+08:00 | weak_target_maintenance | india | 印度新闻监控 | 6 | 6 | 0 | 0 | 0 | readonly only; cooldown respected | skipped | `india` 仍是最少信源 target，但第 1 轮刚作为主对象处理，本轮只记录状态与后续候选建议，不重复改动 |

## 第 2 轮摘要

- round: 2
- timestamp: 2026-06-12T11:35:00+08:00
- recent_12_touched_targets_before_round:
  - `india`
  - `china-watch-en`
- cooldown_skips_this_round:
  - `india`
  - `china-watch-en`
- selected_new_target: `south-korea`
- selected_existing_target: `france`
- weakest_target_readonly_check: `india`
- weakest_target_readonly_reason: `india` 仍是全局最少信源 target（6），但第 1 轮刚被主作业处理，按 12 轮冷却规则本轮仅做只读建议；主工作树中的 `fusion` 仍属用户未提交 WIP，不纳入本轮发布分支。
- existing_target_selection_reason: `france` 在未冷却且已跟踪的 target 中 source_count 最少（21），可通过新增法语公开 RSS 提升国内政治/经济覆盖，而不与上轮对象重复。
- new_target_selection_reason: `south-korea` 与现有 `japan`/`china-watch-en` 形成互补而非重复，聚焦韩国国内政治、半导体/出口产业、半岛安全与中韩关系；2026-06 热度高且已有 5 条英文 RSS 实证可用。
- validation_progress:
  - 初始工作树存在与本轮无关的前端脏改和 `fusion` WIP，因此本轮改用隔离 worktree `codex/target-source-expansion-r002-south-korea`
  - `python tools/scan_sensitive_data.py` passed
  - `git diff --check` passed
  - `python tools/check_no_hardcoded_target.py` passed
  - `pytest tests/unit/test_config_schema_validation.py tests/unit/test_india_target_configs.py tests/unit/test_south_korea_target_configs.py tests/unit/test_france_target_configs.py -q` passed
  - collect smoke: `south-korea` 5/5 sources ok, 175 raw items
  - collect smoke: `france` 25/25 sources ok, 220 raw items
  - preview CI 首次失败：run `27393147856` / job `80954844603`，根因为 `cloud-vps` sandbox allowlist 漏掉新增法国 host
  - 修复提交 `ea72a6e` 后，`pytest tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources ... -q` passed
- deploy_status: preview_success
- preview_release_branch: `codex/target-source-expansion-r002-south-korea`
- preview_release_sha: `ea72a6e`
- preview_branch_merge_sha: `ea72a6ef79f142c8ccba916f25d3fd5e29e44941`
- preview_deploy_run: `27393376925`
- preview_ci_job: `80955526542`
- preview_deploy_job: `80955888024`
- preview_external_health: `GET https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
- preview_targets_api: `GET https://preview.news-sentry.com/api/v1/targets` -> `south-korea` visible with `source_count=5`; `france` visible with `source_count=25`
- preview_remote_deploy_sha_check: partial
- preview_remote_deploy_sha_reason: workflow log confirms remote checkout `ea72a6e` and `.deploy-sha` write step, but current environment still cannot direct-SSH/jump-host read back the VPS file itself
- production_status: skipped
- production_skip_reason: 虽然 preview 外部 health 与 targets 已通过，但未拿到直读版 VPS `.deploy-sha` 实证，暂不推进 `main`

## 第 1 轮结论

- 已完成新增 target: `india`
- 已完成既有 target 扩容: `china-watch-en` 14 -> 16
- 预览部署: GitHub Actions `Deploy preview` 成功
- 阻断项: `preview.news-sentry.com` TLS/health 不通，且当前环境无法 SSH 读取 VPS `.deploy-sha`
- 因此本轮不推 `main`，生产环境保持不变

## 下一轮建议

- `south-korea` 与 `france` 已进入最近 12 轮冷却，下一轮不要再作为主优化对象
- 既然 `preview.news-sentry.com` 已恢复公网可达，下一轮优先补“远端版本可见性”证据链：要么恢复 SSH 读 `.deploy-sha`，要么提供等价的只读版本端点，再考虑 production 放行
- `india` 仍是最少信源 target，但本轮因冷却未动；待冷却结束后，可评估新增 1-2 条已验证英文 RSS（如商务/国内政策入口）而不是重复回到 `china-watch-en`
- 优先补齐 `preview.news-sentry.com` 的公网可达性与证书链，确保 preview 外部 health 可验
- 若下轮仍无 SSH 能力，至少补一条可公开读取当前 preview 版本号/branch 的诊断端点，再决定是否允许 main 推进
- `china-watch-en` 与 `india` 已进入最近 12 轮冷却，下一轮不要再作为主优化对象
