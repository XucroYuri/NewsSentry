# News Sentry 当前状态

> 更新时间：2026-08-03T13:20:16+08:00
> 状态口径：本文件只记录会变化的运行态事实；架构和字段契约仍以 `docs/architecture.md` 与 `docs/contracts-canonical.md` 为准。
> 完整基线：[2026-08-01 项目健康、安全与低成本全球化审计](./audits/2026-08-01-project-health-security-cost-audit.md)

## 结论

正式网站已恢复到 **公开面可用、定时采集持续推进、首页展示新鲜新闻、生产控制面与 D1 可验证** 的状态。当前生产运行态为 `ok`，综合治理分由恢复前的 **58/100** 提升到 **78/100**。

这两个结论需要分开理解：

- **生产运行正常**：Worker、D1、Cron、公共快照、首页回退和 P0 DLQ 均有同一生产 commit 的远端回执。
- **全球信源库存仍需治理**：最新 1,803 条引用审计只有 74.10% 为 `ok`，未达到 90% 的库存 SLO；4 个 P0 信源全部正常，因此该问题保持独立告警，不再误报为整站停机。

72 小时和 7 天持续性证明已经开始积累，但自然时间窗口尚未结束。当前 continuity 状态为 `collecting_72h`，已有 1 条有效回执；不能提前声称 `canary_72h_passed` 或 `slo_7d_passed`。

## 生产证据

| 项目 | 当前证据 |
|---|---|
| 生产部署 commit | `e130570bc4d6621de079691da547a0f4f2cbe62e` |
| Worker version | `068af049-1bdb-4a44-bf93-dcf442e32c52` |
| Deployment ID | `9479de87-9c8d-4a9e-a5ee-1bbd0a87e5c4` |
| 生产部署 | GitHub run [`30783636458`](https://github.com/XucroYuri/NewsSentry/actions/runs/30783636458) 成功 |
| 最终 Runtime Health | GitHub run [`30786864478`](https://github.com/XucroYuri/NewsSentry/actions/runs/30786864478) 成功；6/6 checks 通过、0 reason code |
| 采集连续性 | `collect-cycle` 于 `2026-08-03T05:17:19.443Z` 完成，状态 `ok`，本轮 target 为 `france` |
| 数据新鲜度 | `total_events=32265`；`latest_valid_collected_at=2026-08-03T05:17:02.874Z`；未来时间戳 0 |
| 公开快照 | 17 个快照；最新生成 `2026-08-03T05:17:13.717Z`；最新源发布时间 `2026-08-03T05:15:20.505Z` |
| P0 DLQ | `p0_dead_lettered=0` |
| 首页 | 生产浏览器验证已同时请求 featured bootstrap 与 all-news fallback，根文档、JS、CSS、两类 API 均为 200；页面展示 2026-08-03 新内容，控制台无错误 |
| Continuity | `collecting_72h`；1 条有效回执；12 个 6 小时槽后才可通过 72h，28 个槽后才可通过 7d |

## 本轮根因与修复

1. **采集路径不适合冷启动容器**：采集工作量过大、target 固定、成功游标推进不完整。现在使用有界采集、轮换 target 和成功游标，避免单轮工作把容器拖入超时。
2. **Durable Object / Container RPC 边界错误**：端口等待不显式，且把不可跨 RPC 传输的 `AbortSignal` 传入 Durable Object。现在由服务端建立等待与超时边界。
3. **幽灵 target 阻断轮转**：D1 中存在配置已删除的 `china-watch-en`，轮转后触发 `target_config_not_found`。现在部署同步会权威归档或禁用配置中不存在的 target。
4. **部署回执误读**：健康脚本把 Wrangler deployment 历史列表第一项当作 active deployment。现在改用 `wrangler deployments status --json`，并按 exact version/percentage fail-closed。
5. **就绪快照时钟陈旧**：健康检查读取旧的 ready snapshot，导致成功部署被误判。现在刷新时钟与部署回执统一。
6. **首页 featured 数据永久陈旧**：低成本新采集没有 enrichment 字段，无法进入 featured，旧的高价值新闻长期占据首页。默认首页在 featured 为空或超过 24 小时时自动回退到 all-news 最新页；筛选视图不做该回退，手动刷新仍优先重试 featured。
7. **Source Health 与 Runtime Health 混为一体**：全局库存 SLO 未达标会阻止平台连续性回执，即使 P0 源、Cron 和 D1 全部正常。现在 Source Health 同时输出严格的库存 `status` 与 fail-closed 的 `operational_status`；P0、部署元数据、基线缺失仍会阻断，只有全局库存比例类问题作为独立治理告警。
8. **持续性窗口原本不可达**：Source Health 每周运行，但 ledger 要求 24 小时内审计，并让固定 start 边界随时间过期。现在 current/end 与每周周期对齐为 7 天，start 固定为部署边界且不得早于 deployment。

对应修复已通过 PR [#51](https://github.com/XucroYuri/NewsSentry/pull/51) 至 [#59](https://github.com/XucroYuri/NewsSentry/pull/59) 分阶段进入 `main`。

## 信源健康

最新审计 run [`30786439282`](https://github.com/XucroYuri/NewsSentry/actions/runs/30786439282) 的结论：

| 状态 | 数量 | 占比/说明 |
|---|---:|---|
| ok | 1,336 | 74.10% |
| failed | 98 | 5.44%，高于 2% 库存阈值 |
| degraded | 127 | 空 feed、解析异常等 |
| rate_limited | 130 | 主要受共享 GDELT API 限流影响 |
| temporary_unavailable | 112 | 临时断连、超时或上游 5xx |
| 合计 | 1,803 | 1,024 个唯一 source ref |

库存 SLO 保持 `failed`，阻塞原因是 `global_ok_ratio_below_threshold` 和 `global_failed_ratio_above_threshold`。运行关键面为 `operational_status=ok`、`operational_blockers=[]`；ANSA、Tagesschau Politics、Le Monde Politics、NHK News 四个 P0 信源均为 `ok`。

下一阶段按影响排序治理：

1. 先修复或替换 403/404、invalid JSON 和空 feed 的唯一源，不为第三方限流降低正式 SLO。
2. 将共享 GDELT 查询按 host 做更低并发和错峰审计，区分自致 429 与真实生产不可用。
3. 对被多个 target 复用的 pool source 同时保留“唯一源健康”和“受影响 target 数”两种指标，避免只看引用加权比例。
4. 连续两次确认失效后进入 degraded/dead 生命周期；不得静默删除历史证据。

## 综合评分

| 维度 | 分值 | 权重 | 当前判断 |
|---|---:|---:|---|
| 公开面可用性 | 96 | 10% | Pages、静态资源、公共 API、首页实时阅读流均已验证 |
| 数据新鲜度 | 94 | 15% | 15 分钟采集持续推进，D1 与公开快照在分钟级更新，未来时间戳为 0 |
| 信源连续性 | 60 | 10% | P0 4/4 正常，但全量引用仅 74.10% 为 ok |
| 评分完整性 | 52 | 12% | 本轮未解决历史高分饱和、Breaking 字段缺失和标签漂移 |
| 软件质量 | 90 | 10% | PR CI、234 项相关工具测试、全量后端/前端门禁和独立审查均通过 |
| 安全控制 | 68 | 15% | 生产鉴权与部署面 fail-closed；旧安全深扫仍缺最终报告，注入面整改尚未全部关闭 |
| 部署治理 | 92 | 8% | exact commit/version/deployment/D1 回执闭环，生产与 preview 边界明确 |
| 可观测与恢复 | 84 | 8% | Runtime Health 已全绿并建立 ledger；72h/7d 仍需自然积累 |
| 全球化准备度 | 78 | 7% | 81 个有效 target 与全球信源骨架可用，区域源质量仍不均衡 |
| 成本效率 | 68 | 5% | 未增加常驻监控服务；使用 Cloudflare 与 GitHub 定时回执，但 Container 唤醒成本仍需真实账单校准 |

加权总分：`78.08`，四舍五入为 **78/100**。

## 当前优先级

### P0：生产运行

当前没有已知未关闭的生产运行 P0。以下条件已经满足：

- 当前 active Worker 与部署回执一致；
- Cron 持续推进，数据未超过 2 小时阈值；
- 未来时间戳为 0，P0 DLQ 为 0；
- 首页展示新鲜新闻；
- Runtime Health 回执和 continuity ledger 已成功落盘。

### P1：持续性与质量

1. 等待并验证 12 个连续 6 小时槽，取得 `canary_72h_passed`。
2. 等待并验证 28 个连续 6 小时槽与边界 Source Health，取得 `slo_7d_passed`。
3. 将全局信源 `ok` 比例从 74.10% 提升到至少 90%，hard-failed 比例降到 2% 以下。
4. 继续评分一致性、Breaking 完整性和历史回填整改。
5. 对最终生产 SHA 重新发起安全深扫并取得可审计报告；不得把停在 `Preparing scan` 的旧扫描视为通过。

## 低成本运行边界

- 生产采集继续使用现有 15 分钟 Cron，不新增常驻监控进程。
- Runtime Health 每 6 小时运行一次，artifact 保留 14 天，用 GitHub Actions 替代新的监控服务器。
- Source Health 每周全量审计一次；P0/元数据故障阻断生产连续性，全局库存质量独立告警。
- D1 保存结构化状态，R2 保存大对象与恢复证据，Pages/Workers 提供公开边缘面；VPS 仅保留 legacy rollback，不作为生产依赖。
- 未取得 Cloudflare 真实费用回执前，不把“架构便宜”写成“成本已证明”。

## 状态更新规则

- 每次生产部署、采集恢复、P0 关闭、评分显著变化或 continuity 状态升级时更新本文件。
- 不把本地测试、Preview、单次 200 或单次 Cron 等同于持续健康。
- 72h 需要 12 个连续 6 小时槽；7d 需要 28 个槽、边界 Source Health 与同 commit 回执。
- 易漂移的 SHA、计数、时间和运行链接只记录在本文件及对应 artifact 中。

## Phase A：公开读 KV 快照优先

已完成公开读快照链路的 KV-first 迁移，同一 commit 已含 139 项 Cloudflare 工具测试全绿、后端 ruff 全通过、mypy 无错误（对照本 Phase 未 touch Python）。核心手段是新增 KV 快照投影存取并双写快照，把公开读热路径从 D1 查询切到 KV 读取，降低首页/公开 API 对 D1 的直接耦合。

| 变更项 | 内容 |
|---|---|
| 新增 `kv-snapshot-store.ts` | 提供 `getSnapshotKv()`/`setSnapshotKv()` 单例 KV binding 注入、`kvWriteSnapshot()`/`kvReadSnapshot()` 写读封装，key 统一加 `k:` 前缀，写入前经 `sanitizePublicSnapshotPayload` 净化 |
| 公开读切换 KV-first | `readPublicSnapshotKvFirst*`/`readPublicSnapshotPayloadKvFirst` 先读 KV，未命中（KV miss 或未配置 binding 时 `getSnapshotKv()` 为 null）才回退 D1；`readPublicSnapshot*` 保留 D1-only 路径 |
| 快照刷新双写 | `writeSnapshotAndMaybeKv` 落 D1 后再写 KV，KV 失败 `try/catch` 不阻塞 D1 主链路；首页 bootstrap、news、facets 刷新均接入 |
| 一次性存量回填 | `npm run backfill:kv`（`tools/backfill-kv-snapshots.mts`）把 `public_read_snapshots` 存量同步到 KV；由 `wrangler kv namespace create` 建出的 namespace id 写入 `wrangler.toml` 的 `[[kv_namespaces]]` |

部署时须先以 `npx wrangler kv namespace create PUBLIC_SNAPSHOT_KV` 创建 KV namespace，并把返回的 `id`/`preview_id` 回填到 `wrangler.toml`（当前为占位全零 id，未回填前 KV 写读不会命中、公开读自动走 D1 兜底，可安全运行）。

## Phase B1：评分器 TS 移植

已完成 latent 新闻价值评分器从 Python 到 TypeScript 的纯函数移植。新增 `frontend/cloudflare/workers/lib/latent-value-model.ts`，暴露 `scoreNewsEvent`（0-100 评分）、`rankNewsValues`（Breaking/Potential 双列表排序）、`evaluateBacktest`（回测指标统计）、`featuresFromEventMetadata`（从 NewsEvent 元数据提取并归一特征）等纯函数 API，并复用 half-to-even `clampScore` 钳位得分。模块为无副作用纯函数实现，便于在 Cloudflare Worker 端复用评分逻辑而无需依赖 Python 运行时。

| 变更项 | 内容 |
|---|---|
| 新增 `latent-value-model.ts` | 提供 `LATENT_VALUE_MODEL_VERSION`、`clampScore`（half-to-even）、`neutralFeatures`/`normalizeFeatures`、`featuresFromEventMetadata`、`scoreNewsEvent`、`withDomainPercentiles`、`rankNewsValues`、`evaluateBacktest` 等导出 |
| 纯函数移植 | `scoreNewsEvent` 输出与 Python 逐位对齐；`clampScore` 复用 half-to-even 取整，保证 0-100 边界行为一致 |
| 行为基准 | 以 Python `tests/unit/test_latent_value_model.py` 作为 bit-for-bit 行为基准，TS 各 API 均有对应的 Python-parity 单元测试 |

无回归：Cloudflare 全套 145 项测试全绿，Python `test_latent_value_model.py` 6/6 通过，作为行为基准仍成立。
