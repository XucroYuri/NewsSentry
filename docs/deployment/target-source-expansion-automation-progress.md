# News Sentry target/source 扩容自动化账本

> 自动化: `news-sentry-target-source-expansion-rollout`
> 起始日期: 2026-06-12
> 总目标轮次: 100
> 规则: 每轮先读本账本，再决定新增 target、既有 target 维护、最少信源 target 复查与是否部署。

## 当前状态

- current_round: 7
- completed_rounds: 6
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
| 3 | vietnam | new_target | add | 新增越南 target，修复 UTF-16 RSS 兼容后 6/6 collect smoke 通过 |
| 3 | germany | optimize_existing | expand_sources | 从 22 源扩到 24 源，补入 Tagesspiegel / Destatis 并保持 24/24 全绿 |
| 4 | taiwan | new_target | evaluate_only | 候选热度与 RSS 入口已确认，但当前环境无法完成稳定直接抓取验证，本轮不写配置 |
| 4 | japan | optimize_existing | evaluate_only | 预览站可见 `source_count=23`，但候选新增 feed 在当前环境里未达到可安全落库标准 |
| 5 | canada | new_target | add | 新增加拿大 target，6/6 公开 RSS collect smoke 通过，preview `/targets` 可见 |
| 5 | japan | optimize_existing | prune_dead_and_add_live_sources | 删除 10 条 401/403/404 死源，补入 Japan Times / Asahi 总头条并修复 NHK 重定向 |
| 6 | new-zealand | new_target | add | 新增新西兰 target，6/6 公开 RSS collect smoke 通过，preview `/targets` 可见 |
| 6 | italy | optimize_existing | prune_dead_and_add_live_sources | 移出 3 条 challenge/403/错误页死源，补入 ANSA 政经与 Open Online 稳定 RSS，preview `source_count` 保持 66 |

## 最近 20 轮 candidate_new_targets

| round | candidate_id | decision | similarity_check | notes |
| --- | --- | --- | --- | --- |
| 1 | india | added | 与现有 target、账本候选无重复 | 热度、公开 RSS 可得性、英文入口三项同时满足 |
| 2 | south-korea | added | 与现有 target、最近 20 轮候选无重复；虽与 `japan` 同属东北亚，但国别范围、议题重心、来源矩阵独立 | 2026-06 韩国地方选举余波、李在明政府议程、半导体与半岛安全热度并行，且 5 条英文 RSS 已实证可用 |
| 3 | vietnam | added | 与现有 target、最近 20 轮候选无重复；虽与 `china-watch-en`、`south-korea` 同属亚洲议题带，但国别边界、制造/关税/南海议题和独立英语 source matrix 均明确区分 | 2026-06 越南仍处于关税谈判、出口制造、对华供应链与东盟外交热区，且 6 条公开 RSS 已完成实证验证 |
| 4 | philippines | skipped | 与现有 target、最近 20 轮候选无重复；与 `vietnam` 同属南海议题带，但国别边界和新闻源矩阵独立 | 2026-06 中菲摩擦与 Mindanao 地震后治理议题仍热，但多条候选 feed 呈 Cloudflare challenge 或长时间超时，本轮不纳入配置 |
| 4 | taiwan | skipped | 与现有 target、最近 20 轮候选无重复；虽与 `china-watch-en`、`japan` 同涉东亚安全，但国别内政、半导体与民主治理焦点独立 | 已从总统府、内政部、CDC、教育部、经贸主管部门等页面定位 RSS 入口，但当前环境未完成稳定直拉/collect 级实证，延后到后续轮次 |
| 5 | canada | added | 与现有 target、最近 20 轮候选无重复；虽与 `usmca`/`g7` 热点同属北美议程，但国别边界、官方源矩阵与 `china-watch-en`、`france` 均独立 | 2026-06 加拿大同时处于粮食安全战略、USMCA 评估与对法/对美安全合作热区，且 6 条公开 RSS 已完成 curl + collect 实证 |
| 6 | mexico | skipped | 与现有 target、最近 20 轮候选无重复；虽与 `canada` 同属北美议题带，但国别边界、社会治理与官方源矩阵独立 | 2026-06 USMCA/世界杯/治安议题热度成立，但本轮实测官方与主流 RSS 多次返回 Access Denied/403/410 或 HTML 噪声，不纳入配置 |
| 6 | new-zealand | added | 与现有 target、最近 20 轮候选无重复；虽与 `australia`、`canada` 同属英语国家议题，但预算、太平洋安全、对华关系和独立 feed matrix 均明确区分 | 2026-06 新西兰同时处于 Budget 2026、对华/对港议题与太平洋安全舆论热区，且 6 条公开 RSS 已完成 curl + collect 实证 |

## target 作业记录表

| round | timestamp | action_type | target_id | target_label | source_count_before | source_count_after | added_sources | removed_sources | social_accounts_added | validation_result | deploy_result | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-06-12T06:42:43+08:00 | new_target | india | 印度新闻监控 | 0 | 6 | thehindu-india,thehindu-business,thehindu-world,indianexpress-india,indianexpress-business,toi-india | 0 | 0 | static checks passed; pytest passed; collect smoke 6/6 ok, 180 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 选择热度稳定且 RSS 可验证的印度国别 target，避免新增空 target |
| 1 | 2026-06-12T06:42:43+08:00 | optimize_existing | china-watch-en | 涉中新闻监控 | 14 | 16 | dw-en-all,aljazeera-global | 0 | 0 | collect smoke 15/15 ok, 187 items | preview workflow 27382719432 success; external preview health blocked; production skipped | 当前最少信源且未冷却的已跟踪 target，补欧洲与 Global South 公开信源广度 |
| 1 | 2026-06-12T06:42:43+08:00 | weak_target_maintenance | fusion | Fusion Codes Intelligence | 7 | 7 | 0 | 0 | 0 | readonly only | skipped | 当前最少信源 target 但存在用户未提交脏改，本轮只记录状态和建议，不重复覆盖 |
| 2 | 2026-06-12T11:35:00+08:00 | new_target | south-korea | 韩国新闻监控 | 0 | 5 | yonhap-en-all,yonhap-national,korea-times-all,korea-herald-all,hankyoreh-english | 0 | 0 | static checks passed; pytest passed; collect smoke 5/5 ok, 175 items | preview workflow 27393376925 success after sandbox allowlist fix; production skipped | 与现有 target、最近 20 轮候选不重复；热点明确且 5 条英文 RSS 已实证可用 |
| 2 | 2026-06-12T11:35:00+08:00 | optimize_existing | france | 法国新闻监控 | 21 | 25 | leparisien-politique,leparisien-economie,rfi-france,france24-france | 0 | 0 | collect smoke 25/25 ok, 220 items | preview workflow 27393376925 success after sandbox allowlist fix; production skipped | 当前未冷却 target 中信源最少，且新增 4 条法语公开 RSS 后仍保持全绿采集 |
| 2 | 2026-06-12T11:35:00+08:00 | weak_target_maintenance | india | 印度新闻监控 | 6 | 6 | 0 | 0 | 0 | readonly only; cooldown respected | skipped | `india` 仍是最少信源 target，但第 1 轮刚作为主对象处理，本轮只记录状态与后续候选建议，不重复改动 |
| 3 | 2026-06-12T16:55:59+08:00 | new_target | vietnam | 越南新闻监控 | 0 | 6 | vietnamnews-politics-laws,vietnamnews-economy,vietnamnews-society,vietnamplus-politics,vietnamplus-business,vnexpress-business | 0 | 0 | static checks passed; pytest passed; collect smoke 6/6 ok after RSS bytes-first fix, 95 items | preview workflow 27405188794 success; external preview health ok; targets API shows vietnam=6 and germany=24; production skipped | 选择 2026-06 仍处关税谈判、出口制造和东盟外交热区的越南国别 target，且公开英文 RSS 可实证运行 |
| 3 | 2026-06-12T16:55:59+08:00 | optimize_existing | germany | 德国新闻监控 | 22 | 24 | tagesspiegel-news,destatis-aktuell | 0 | 0 | collect smoke 24/24 ok, 184 items | preview workflow 27405188794 success; external preview health ok; targets API shows germany=24 | 当前未冷却已跟踪 target 中 source_count 最少，补德国广域政治/社会与官方统计两个缺口后仍保持全绿 |
| 3 | 2026-06-12T16:55:59+08:00 | weak_target_maintenance | south-korea | 韩国新闻监控 | 5 | 5 | 0 | 0 | 0 | readonly only; cooldown respected | skipped | `south-korea` 仍是全局最少信源 target，但第 2 轮刚作为主对象处理，本轮只记录状态与下一步建议，不重复改动 |
| 4 | 2026-06-12T21:43:58+08:00 | skip | taiwan | 台湾新闻监控（候选） | 0 | 0 | 0 | 0 | 0 | live news heat verified; official RSS entry pages located via web, but direct shell fetch/collect proof remained unstable in current environment | skipped; no release branch pushed; no deploy | 候选热度高且官方 RSS 入口丰富，但本轮按“宁可跳过不降质”原则不把未完成直拉验证的候选写入配置 |
| 4 | 2026-06-12T21:43:58+08:00 | skip | japan | 日本新闻监控 | 23 | 23 | 0 | 0 | 0 | preview `/api/v1/targets` confirms `source_count=23`; candidate additional feeds for Japan remained unverified from current environment | skipped | `japan` 是未冷却且远端可见 target 中 source_count 最少者，但候选新增 feed 未达到可安全落库的验证标准，本轮只做只读维护判断 |
| 4 | 2026-06-12T21:43:58+08:00 | weak_target_maintenance | south-korea | 韩国新闻监控 | 5 | 5 | 0 | 0 | 0 | readonly only; cooldown respected; preview `/targets` still shows `source_count=5` | skipped | `south-korea` 仍是全局最少信源 target，但第 2 轮刚作为主对象处理，且当前优先处理冷却与验证边界，不重复改动 |
| 5 | 2026-06-13T03:08:00+08:00 | new_target | canada | 加拿大新闻监控 | 0 | 6 | pm-gc-news,pm-gc-media,globalnews-canada,globalnews-politics,globalnews-money,globeandmail-all | 0 | 0 | static checks passed; targeted pytest passed; collect smoke 6/6 ok, 80 raw items | preview workflow 27436680936 success; external preview health ok; targets API shows canada=6 and japan=13; production skipped | 选择 2026-06 同时处于粮食安全战略、USMCA 评估与对法/对美安全合作热区的加拿大 target，且 6 条公开 RSS 已完成 curl + collect 实证 |
| 5 | 2026-06-13T03:08:00+08:00 | optimize_existing | japan | 日本新闻监控 | 23 | 13 | japantimes-topstories,asahi-headlines | yomiuri-politics,yomiuri-social,mainichi-politics,mainichi-social,nikkei,nikkei-xtech,mofa-japan,mod-japan,env-go-jp,moj-immigration,reuters-jp,asahi-social | 0 | targeted pytest passed; collect smoke 13/13 ok, 171 raw items; nhk redirect fixed | preview workflow 27436680936 success; external preview health ok; targets API shows japan=13 | 清理 401/403/404 与重定向失效源，保留实际可跑矩阵并补入 2 条稳定公开 RSS，让日本 target 的 source_count 从“虚高”回到“可运行”口径 |
| 5 | 2026-06-13T03:08:00+08:00 | weak_target_maintenance | south-korea | 韩国新闻监控 | 5 | 5 | 0 | 0 | 0 | readonly only; cooldown respected; preview `/targets` still shows `source_count=5` | skipped | `south-korea` 仍是全局最少信源 target，但第 2 轮刚作为主对象处理且仍处冷却窗口，本轮继续只做状态记录 |
| 6 | 2026-06-13T08:04:10+08:00 | skip | mexico | 墨西哥新闻监控（候选） | 0 | 0 | 0 | 0 | 0 | live topic scan passed, but candidate feeds returned Access Denied/403/410 or HTML noise in direct shell validation | skipped; switched candidate before config write | 北美热度成立，但可验证公开 RSS 质量未达标，本轮按规则放弃落库 |
| 6 | 2026-06-13T08:04:10+08:00 | new_target | new-zealand | 新西兰新闻监控 | 0 | 6 | beehive-all-updates,beehive-releases,beehive-speeches,nzherald-nz,nzherald-business,nzherald-world | 0 | 0 | static checks passed; ruff passed; targeted pytest 449 passed; collect smoke 6/6 ok, 90 raw items | preview workflow 27449879048 success; external preview health ok; targets API shows new-zealand=6 and italy=66; production skipped | 选择 Budget 2026、对华/对港议题与太平洋安全热度并行、且公开 RSS 可实证的新西兰国别 target |
| 6 | 2026-06-13T08:04:10+08:00 | optimize_existing | italy | 意大利新闻监控 | 66 | 66 | ansa-politica,ansa-economia,open-online | camera-it,quirinale,unhcr-italia | 0 | static checks passed; ruff passed; targeted pytest 449 passed; collect smoke status 0 with 387 raw items; ansa-politica/ansa-economia/open-online all emitted data | preview workflow 27449879048 success; external preview health ok; targets API shows italy=66 and new-zealand=6; production skipped | 当前 preview 可见且最近 12 轮未做主作业的既有国家 target 仅剩 italy；本轮执行“删死源 + 补活源”质量维护而不重复触碰冷却对象 |
| 6 | 2026-06-13T08:04:10+08:00 | weak_target_maintenance | south-korea | 韩国新闻监控 | 5 | 5 | 0 | 0 | 0 | readonly only; cooldown respected; preview `/targets` still shows `source_count=5` | skipped | `south-korea` 仍是全局最少信源 target，但第 2 轮起一直处于 12 轮冷却窗口，本轮继续只读记录 |

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

## 第 3 轮摘要

- round: 3
- timestamp: 2026-06-12T16:55:59+08:00
- recent_12_touched_targets_before_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
- cooldown_skips_this_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
- selected_new_target: `vietnam`
- selected_existing_target: `germany`
- weakest_target_readonly_check: `south-korea`
- weakest_target_readonly_reason: `south-korea` 仍是全局最少信源 target（5），但第 2 轮刚被主作业处理，按 12 轮冷却规则本轮只做只读复查；`india` 也仍在冷却，下一批弱 target 主作业应优先在二者中择其一恢复扩容。
- existing_target_selection_reason: `germany` 是未冷却且已跟踪 target 中 source_count 最少者（22），本地 collect smoke 184 条、0 错误，适合在不重复触碰冷却对象的前提下补德国广域政治/社会与官方统计覆盖。
- new_target_selection_reason: `vietnam` 在 2026-06 仍处对美关税谈判、出口制造、对华供应链和东盟外交议题高热区；与 `china-watch-en`、`south-korea` 虽有区域交集，但国别边界、议题焦点与英语 source matrix 独立，且 6 条公开 RSS 已完成本地实证。
- validation_progress:
  - 本轮继续在隔离 worktree `codex/target-source-expansion-r002-south-korea` 基线上切出分支 `codex/target-source-expansion-r003-vietnam`
  - `python tools/scan_sensitive_data.py` passed
  - `git diff --check` passed
  - `python tools/check_no_hardcoded_target.py` passed
  - `PYTHONPATH=src ... pytest tests/unit/test_config_schema_validation.py tests/unit/test_rss_collector.py tests/unit/test_vietnam_target_configs.py tests/unit/test_germany_target_configs.py ... tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources -q` passed (`475 passed`)
  - 初次 `vietnam` collect smoke 暴露 `Vietnam News` UTF-16 feed 被 `response.text` 预解码破坏，新增 bytes-first RSS 兼容修补与回归测试后复验通过
  - collect smoke: `vietnam` 6/6 sources ok, 95 raw items
  - collect smoke: `germany` 24/24 sources ok, 184 raw items
- deploy_status: preview_success
- preview_release_branch: `codex/target-source-expansion-r003-vietnam`
- preview_release_sha: `0d7888a`
- preview_branch_merge_sha: `0d7888ac4a774d6555b68b70595af76f0c0a6be6`
- preview_ci_run: `27405188785`
- preview_ci_job: `80992490343`
- preview_deploy_run: `27405188794`
- preview_deploy_ci_job: `80992490410`
- preview_deploy_job: `80993356657`
- preview_external_health: `GET https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
- preview_targets_api: `GET https://preview.news-sentry.com/api/v1/targets` -> `vietnam` visible with `source_count=6`; `germany` visible with `source_count=24`
- preview_remote_deploy_sha_check: partial
- preview_remote_deploy_sha_reason: GitHub Actions deploy log confirmed remote fetch/checkout to `0d7888a`, displayed `Checked out: 0d7888a feat: 新增越南 target 并补强德国信源`, and executed `echo \"${SHA}\" > /opt/news-sentry/preview/.deploy-sha`; but current environment still cannot direct-SSH/jump-host read the VPS file itself
- production_status: skipped
- production_skip_reason: preview workflow、preview 外部 health 与 targets 已通过，但 `.deploy-sha` 仍缺少直读版 VPS 文件实证，因此本轮仍不推进 `main`

## 第 4 轮摘要

- round: 4
- timestamp: 2026-06-12T21:43:58+08:00
- recent_12_touched_targets_before_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
- cooldown_skips_this_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
- selected_new_target: `taiwan`（候选评估后跳过）
- selected_existing_target: `japan`（只读评估后跳过）
- weakest_target_readonly_check: `south-korea`
- weakest_target_readonly_reason: `south-korea` 仍是 preview 可见 target 中最少信源对象（5），但第 2 轮刚作为主对象处理，按 12 轮冷却规则继续只读；`india` 与 `vietnam` 也都处于 6 源弱位池，但同样仍在冷却窗口内。
- existing_target_selection_reason: `japan` 在未冷却且 preview 可见的既有 target 中 source_count 最少（23）；`fusion` 虽本地仅 7 源，但主工作树仍有用户未提交 WIP 且未进入 preview，本轮不跨现场覆盖。
- new_target_selection_reason: `taiwan` 具备本轮最强的“热点 + 公开官方源”组合：6 月 10 日台湾进行 HIMARS 实弹演训，6 月 12 日 Focus Taiwan 报道半导体供应链园区与工资/制造数据继续升温；同时总统府、内政部、CDC、教育部与经贸主管部门均提供英语 RSS 入口。
- validation_progress:
  - 主工作树仍停留在 round 2 脏改状态，因此本轮继续使用隔离 worktree `codex/target-source-expansion-r002-south-korea`，并切出 `codex/target-source-expansion-r004-taiwan-japan-eval`
  - live candidate scan:
    - `philippines` 热点成立，但候选 feed 多次触发 Cloudflare challenge、403 或长时间超时，仅 GMA 多个 XML feed 可稳定直读，未达到“足够独立可信来源”阈值
    - `taiwan` 热点成立，且通过网页实证定位到总统府/内政部/CDC/教育部/经贸主管部门等 RSS 入口，但当前环境里的直接 shell 拉取仍不稳定，未完成 collect 级验证
  - preview runtime check:
    - `curl https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
    - `curl https://preview.news-sentry.com/api/v1/targets` -> `japan=23`, `south-korea=5`, `india=6`, `vietnam=6`, `germany=24`, `france=25`, `china-watch-en=15`, `italy=66`
  - no repo config changes written; therefore no `scan_sensitive_data` / pytest / collect smoke rerun against new candidate configs
- deploy_status: skipped
- preview_release_branch: `codex/target-source-expansion-r004-taiwan-japan-eval`
- preview_release_sha: none
- preview_external_health: `GET https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
- preview_targets_api: `GET https://preview.news-sentry.com/api/v1/targets` -> `japan` visible with `source_count=23`; `south-korea` visible with `source_count=5`
- preview_remote_deploy_sha_check: not_attempted
- preview_remote_deploy_sha_reason: 本轮没有实际配置改动，且候选验证未过闸门，因此不触发 release / deploy 链路
- production_status: skipped
- production_skip_reason: 本轮无安全可落地的 target/source 配置改动，按自动化规则只更新账本，不推进 preview 或 production

## 第 5 轮摘要

- round: 5
- timestamp: 2026-06-13T03:08:00+08:00
- recent_12_touched_targets_before_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
  - `taiwan`
  - `japan`
- cooldown_skips_this_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
- selected_new_target: `canada`
- selected_existing_target: `japan`
- weakest_target_readonly_check: `south-korea`
- weakest_target_readonly_reason: `south-korea` 仍是 preview 可见 target 中最少信源对象（5），但自第 2 轮起一直在 12 轮冷却窗口内，本轮继续只读复查；`india` 与 `vietnam` 也同处 6 源弱位池，但本轮优先完成新 target 扩容与 `japan` 的死源清理。
- existing_target_selection_reason: `japan` 仍是未冷却且 preview 可见的既有 target 中 source_count 最少者（23）；round 4 只做了候选评估，本轮正式进入 source audit，确认 10 条 RSS 已返回 401/403/404，另有 `nhk-news` 命中 301 重定向，适合做“删死源 + 补活源 + 修旧入口”的质量型维护。
- new_target_selection_reason: `canada` 在 2026-06-11 至 2026-06-12 同时具备三条清晰热点线索：总理府发布国家粮食安全战略、加拿大进入 USMCA/CUSMA 评估与关税谈判窗口、对法安全/AI 协议与 G7 外交连续升温；其官方与媒体 RSS 入口独立且可实证，不与最近 20 轮候选重复。
- validation_progress:
  - 本轮基于 `codex/target-source-expansion-r004-taiwan-japan-eval` 切出 release branch `codex/target-source-expansion-r005-canada-japan`
  - `python tools/scan_sensitive_data.py` passed
  - `git diff --check` passed
  - `python tools/check_no_hardcoded_target.py` passed
  - `PYTHONPATH=src ../../.venv/bin/python -m pytest tests/unit/test_config_schema_validation.py tests/unit/test_canada_target_configs.py tests/unit/test_japan_target_configs.py tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources tests/unit/test_target_filter_configs.py::test_japan_filter_covers_current_domestic_and_geopolitical_signals -q` passed (`426 passed`)
  - `canada` 逐源 collect smoke: 6/6 ok, `80` events
  - `japan` 逐源 collect smoke: 13/13 ok, `171` events
  - 首次 preview run `27436358981` 失败，根因为 `tests/unit/test_config.py::test_real_configured_targets_load[japan-ja]` 仍假定所有 source 语言必须等于 primary language；补充 secondary-language 容忍后，以提交 `103aba3` 修复
  - 二次 preview run `27436680936` 通过，`CI Gate` 与 `Deploy preview` 全绿
  - 全量 collect smoke:
    - `canada` raw items = `80`
    - `japan` raw items = `171`
- deploy_status: preview_success
- preview_release_branch: `codex/target-source-expansion-r005-canada-japan`
- preview_release_sha: `103aba3`
- preview_branch_merge_sha: `d851d3046c070c88d78708ebea27b97d2aa866fc`
- preview_deploy_run: `27436680936`
- preview_ci_job: `81100303664`
- preview_deploy_job: `81101254407`
- preview_external_health: `GET https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
- preview_targets_api: `GET https://preview.news-sentry.com/api/v1/targets` -> `canada` visible with `source_count=6`; `japan` visible with `source_count=13`
- preview_remote_deploy_sha_check: partial
- preview_remote_deploy_sha_reason: workflow log confirmed remote checkout from `0d7888a` to `d851d30`, displayed `Checked out: d851d30 ...`, and executed `echo "${SHA}" > /opt/news-sentry/preview/.deploy-sha`; but current environment still cannot direct-SSH/jump-host read the VPS file itself
- production_status: skipped
- production_skip_reason: preview 外部 `/health` 与 `/targets` 已通过，但 `.deploy-sha` 仍缺少独立只读复核；因此本轮不推进 `main`

## 第 6 轮摘要

- round: 6
- timestamp: 2026-06-13T08:04:10+08:00
- recent_12_touched_targets_before_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
  - `taiwan`
  - `japan`
  - `canada`
  - `japan`
- cooldown_skips_this_round:
  - `india`
  - `china-watch-en`
  - `south-korea`
  - `france`
  - `vietnam`
  - `germany`
  - `canada`
  - `japan`
- selected_new_target: `new-zealand`
- selected_existing_target: `italy`
- weakest_target_readonly_check: `south-korea`
- weakest_target_readonly_reason: `south-korea` 仍是 preview 可见 target 中最少信源对象（5），但从第 2 轮起持续处于 12 轮冷却窗口；`india`、`vietnam` 也仍在 6 源弱位池内，同样不能反复重做主作业。
- existing_target_selection_reason: `italy` 是 preview 可见且最近 12 轮未做主作业的唯一既有国家 target；`fusion` 虽本地源数更少，但主工作树仍存在用户 WIP 且未进入 preview，因此本轮不跨现场覆盖，转而对 `italy` 做“删死源 + 补活源”质量维护。
- new_target_selection_reason: `new-zealand` 在 2026-06 同时具备 Budget 2026、对华/对港议题和太平洋安全三条明确热度线索，且 Beehive / NZ Herald 组合形成 6 条可直接验证的公开 RSS；相较之下，`mexico` 候选虽然热点成立，但本轮实测 RSS 入口多次返回 Access Denied/403/410 或 HTML 噪声，不满足落库闸门。
- validation_progress:
  - 本轮基于 `codex/target-source-expansion-r005-canada-japan` 切出 release branch `codex/target-source-expansion-r006-new-zealand-italy`
  - `python tools/scan_sensitive_data.py` passed
  - `git diff --check` passed
  - `python tools/check_no_hardcoded_target.py` passed
  - `../../.venv/bin/python -m ruff check` passed
  - `../../.venv/bin/python -m pytest tests/unit/test_config_schema_validation.py tests/unit/test_new_zealand_target_configs.py tests/unit/test_italy_target_configs.py tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources -q` passed (`449 passed`)
  - `new-zealand` collect smoke: 6/6 sources ok, `90` raw items
  - `italy` collect smoke: run status `0`, `387` raw items；新增替代源 `ansa-politica`、`ansa-economia`、`open-online` 均实际产出事件；社媒维度在 `cloud-vps` profile 下按预期继续跳过
  - 当前 shell 中 plain `git push` / `git ls-remote` 长时间无输出挂起，因此改用 authenticated `gh api repos/.../git/*` 创建远端 release commit 并快进 `preview`
  - 首次 preview run `27449807202` / CI job `81142503477` 失败，根因为 `tests/unit/test_new_zealand_target_configs.py` docstring 触发 `ruff` E501
  - 补充 follow-up commit 后，第二次 preview run `27449879048` 通过，`CI Gate` 与 `Deploy preview` 全绿
- deploy_status: preview_success
- preview_release_branch: `codex/target-source-expansion-r006-new-zealand-italy`
- preview_release_sha: `a620f5d`
- preview_branch_merge_sha: `a620f5dab34e21ab8d4a65dd7d252351fb96bac8`
- preview_deploy_run: `27449879048`
- preview_ci_job: `81142711567`
- preview_deploy_job: `81143172604`
- preview_external_health: `GET https://preview.news-sentry.com/api/v1/health` -> `{"status":"ok"}`
- preview_targets_api: `GET https://preview.news-sentry.com/api/v1/targets` -> `new-zealand` visible with `source_count=6`; `italy` visible with `source_count=66`; `south-korea` remains `source_count=5`
- preview_remote_deploy_sha_check: partial
- preview_remote_deploy_sha_reason: Deploy log shows `=== Deploying NewsSentry preview (a620f5d) on port 18081 ===`, `HEAD is now at a620f5d ...`, `Checked out: a620f5d ...`, and workflow step summary records `Commit | a620f5dab34e21ab8d4a65dd7d252351fb96bac8`; but current environment still cannot direct-SSH / jump-host read back VPS `.deploy-sha` file itself
- production_status: skipped
- production_skip_reason: preview 外部 `/health` 与 `/targets` 已通过，但 `.deploy-sha` 仍缺少独立只读复核；因此本轮不推进 `main`

## 第 1 轮结论

- 已完成新增 target: `india`
- 已完成既有 target 扩容: `china-watch-en` 14 -> 16
- 预览部署: GitHub Actions `Deploy preview` 成功
- 阻断项: `preview.news-sentry.com` TLS/health 不通，且当前环境无法 SSH 读取 VPS `.deploy-sha`
- 因此本轮不推 `main`，生产环境保持不变

## 下一轮建议

- `canada` 与 `japan` 已在第 5 轮完成主作业，下一轮不要立即重复触碰；尤其 `japan` 本轮刚从 23 条名义源清到 13 条可运行源，先观察 1-2 轮实际 event 质量再决定是否继续补源
- `new-zealand` 与 `italy` 已在第 6 轮完成主作业，下一轮不要立即重复触碰；尤其 `italy` 这轮是质量修剪而非大规模加量，先观察 1-2 轮实际 source health 再决定是否继续补官方替代源
- `south-korea` 仍是全局最少信源 target（5），且已连续三轮只读；一旦冷却允许，应优先补 1-2 条已验证英文 RSS，把弱 target 的真实广度补起来
- `india` 与 `vietnam`（各 6）仍在第二梯队弱位池，但本轮未动；若 `south-korea` 仍受冷却约束，可在二者中选其一做下一轮主维护
- `taiwan` 与 `philippines` 仍保留在最近 20 轮候选名单中；若后续重试，必须先解决“直接 shell 拉取 / collect 级验证不稳定”，不要只重复新闻热度核验
- `mexico` 已进入最近 20 轮候选冷却，后续若重试必须先确认公开 RSS 入口不再被 Access Denied/403/410 拦截，再考虑重新评估
- `fusion` 本地仍存在用户 WIP，除非主工作树相关改动先落定，否则继续不把它作为自动化主对象
- preview 公网 health 与 targets 已稳定，但 production 放行链路依然缺少独立 `.deploy-sha` 只读证据；下一轮若想推进 `main`，优先补“远端版本可见性”诊断端点或恢复只读 SSH 复核
