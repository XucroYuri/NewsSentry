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

## Phase B2：采集层（scheduler+fetcher+自研 RSS 解析）

已完成 Cloudflare Worker 侧的采集层第一阶段（抓取 + 解析 → 可移植 `CollectedEvent`），即现有 Python 采集管线首段的 TS 移植。新增 `frontend/cloudflare/workers/lib/collect/` 子目录，包含四个无副作用、可单元测试的模块：

| 变更项 | 内容 |
|---|---|
| 新增 `rss-parser.ts` | 自研轻量 RSS/Atom 解析器 `parseFeed`，不用任何外部 XML/RSS 库（YAGNI，仅匹配主流 RSS 2.0 与 Atom 字段）；`decodeEntities` 贪心解码常见 HTML 实体，`linkOf` 优先文本内容再取 href 属性 |
| 新增 `collected-event.ts` | `CollectedEvent` 可移植采集事件、`Language`/`coerceLanguage`、`collectedEventFromEntry`；`makeCollectId` 为异步函数，优先用 Web Crypto `crypto.subtle.digest`，环境不可用时回退 Node `node:crypto`，两者产出同一位哈希 |
| 新增 `fetcher.ts` | `fetchCollectedEvents` 抓取 + 归一化；对齐 Python `_raise_on_redirect`（3xx 视为失败）与 `_retry_fetch`（5xx / 网络错误重试一次）；抓/解析失败一律返回非 `ok` 的 `CollectOutcome`，不对外抛异常 |
| 新增 `batch-scheduler.ts` | 纯函数 `nextBatch` 从 cursor 起环形取 batchSize 个 target，返回 `selected`/`next_cursor`/`complete_cycle`；无状态、无 D1（游标持久化由调用方负责，Phase B4 接续） |

ID 与行为基准：`makeCollectId` 输出 `ne-{target}-{src}-{yyyymmdd}-{hash8}` 格式，hash8 由 SHA-256( target_id + source_id + url + published_at_iso ) 截取前 8 位十六进制生成，与 Python `uuid` 语义无关的 `hashlib.sha256(...).hexdigest()[:8]` 逐位一致，保证 Python/TS 两侧同一事件产生相同 ID。日期部分取 `published_at_iso` 前 10 位并按真实日历日期 round-trip 校验，形状合法但非法（如 2024-02-30）回退当前 UTC 日期，对齐 Python `fromisoformat` 拒绝语义。`coerceLanguage` 小写获取 `-` 前 base 与已知集合匹配，未命中回退 MIXED——均以 Python 采集/`make_id`/`coerce_language`/`_extract_*` 作为行为基准，TS 各 API 均有对应的 Python-parity 单元测试。

无回归：Cloudflare 全套 159 项测试全绿（含新增 collect 层 30 余项），Python `tests/` collect 相关 194 项通过作为行为基准仍成立。Phase B3（Durable Object 调度接线）与 B4（D1 游标持久化）待接续。

## Phase B3：规则过滤/分类/聚类/研判 TS 移植

已完成采集事件 → 研判的规则层转译链 TS 移植，覆盖 Python 的 `rules_filter` / `classifier_rules` / `event_clustering` / `rules_judge` / `classification_taxonomy` 行为基线。全部新增于 `frontend/cloudflare/workers/lib/collect/`，均为配置驱动、无副作用、可单测的纯函数，不依赖 Python 运行时，为 Cloudflare Worker 端离线转译奠定基础。

| 变更项 | 内容 |
|---|---|
| 新增 `transform-keywords.ts` | 关键词匹配与分类法兼容助手：`keywordMatches`（对 CJK/假名/谚文做子串匹配，否则词边界；2-4 位全大写缩写大小写敏感，其余忽略大小写）、`canonicalL0`（trim+lowercase、legacy 别名映射、空回退 uncategorized）、`classificationTerms`（规范 l0 + l1 文本去重保序）、`isCanonicalL0`；全量 `CANONICAL_L0` 与 `LEGACY_L0_ALIASES` 逐一复刻 Python `classification_taxonomy.py` |
| 新增 `filter.ts` | `filterEvents` 对齐 Python `RulesFilter.filter`：命中 knownIds 去重（skipped_known）、`now-published_at <= max_age_hours` 时效（解析失败宽容通过）、关键词按 weight*100 计分顶 100 并写 `metadata.filter_matched_keywords`、低于 `score_threshold` 跳过（skipped_low_score）；通过者分数写 `metadata.filter_score`。不写 memory、不 mutate knownIds——内存去重能力移交 B4 接线，本阶段仅返回四类计数器 |
| 新增 `classifier.ts` | `classifyEvent` 对齐 Python `ClassifierRules.classify`，配置驱动（`ClassificationConfig` 含 l0_domains/l1_topics/country_axes）：`_gather_text` 聚合 title+content、L0 命中计数选最高域+置信度、L1 在命中域下匹配子议题、L2 国家子轴按子议题平均置信度激活；L3 阶段留空，返回 `classifier_version: "rules-v1"` |
| 新增 `clustering.ts` | `assignClusters` 对齐 Python `assign_lightweight_clusters`：token profiler（NFKD→ascii→regex 抽取→去 stopword/泛词→synonym 映射）、`_same_event` union-find 轻量归组（标题重叠 + 分类 term 兼容）、`_stable_id` 用 `sha256Hex`（复用 B2 导出）对 `target|terms|tokens` 算 SHA-256 前 12 位 hex 生成**确定性** cluster/story id；写入 `metadata.clustering`（cluster_type/cluster_id/story_id/cluster_size/confidence/matched_by/reason/clustered_at） |
| 新增 `judge.ts` | `judgeEvent` 对齐 Python `rules_judge.py`：home_relevance 子串命中 +10 顶 100、`decideRecommendation` 依 score/L0 得 `publish/review/archive/discard`、`buildRationale` 生成简体中文研判理由、`buildFlags` 产 high_value/home_significant/home_related/breaking/priority_topic；返回新对象不改动 event，`china_relevance` 为 home_rel 向后兼容别名 |

关键语义：规则过滤与研判的分数统一以 `metadata.filter_score` 为键（B2 尚无 news_value_score，用命名空间键保持 shape 稳定）；`classifyEvent`/`judgeEvent`/`assignClusters` 均为纯函数，调用方负责次序编排；`assignClusters` 为 async 且按批次独立计算稳定 id，批次间不共享状态。以 Python `tests/unit/` 对应的规则/分类/聚类/研判用例作为行为基准，TS 各 API 均有 Python-parity 单元测试。

无回归：Cloudflare 全套 198 项测试全绿（含新增 B3 规则层与既有 collect 层用例），Python `tests/` 对应行为基准仍成立。Phase B4（D1 游标持久化接线、`knownIds` 去重状态化持久）待接续。

## Phase B4：写穿管道（采集→处理→公开读闭环）

已完成 Cloudflare 自由层的**写穿（write-through）管道**，串起 B2（批次调度 + 抓取归一）→ B3（规则过滤/分类/聚类/研判）→ B4（写穿 + 快照刷新）为一个完整采集周期，打通「采集 → 处理 → 公开阅读」全闭环。本阶段不引入任何 legacy 的 `import_batches`/回执守卫机制，批次 `INSERT ... SELECT` 被逐事件幂等 upsert 取代。全部新增于 `frontend/cloudflare/workers/lib/collect/`，其中 `ops-state.ts`/`write-through.ts`/`collect-cycle.ts` 为本相位新模块，均为可注入、可单测的组合式实现。

| 变更项 | 内容 |
|---|---|
| 新增 `ops-state.ts` | 抽象键值仓库接口 `KvRepo`（`get`/`set`），薄封装为 `readCursor`/`writeCursor`（`collect_cursor`）、`readProcessedWatermark`/`writeProcessedWatermark`（`collect_processed`）。生产实现 `D1KvRepo` 走 `ops_state` 表（key/value/updated_at，upsert 语义）；测试用 `MapKvRepo` 桩，使纯逻辑不绑定 D1 即可单测 |
| 新增 `write-through.ts` | `writeEventToD1` 单事件直接参数化 `INSERT ... ON CONFLICT(event_id) DO UPDATE` upsert 进 `events`，复用 projection-sql 的列映射/COALESCE 语义，无 `import_batches`/回执机制；`writeBatchToD1` 逐事件 upsert、统计 `written`、推进游标 `collect_cursor = cursor + events.length`、可选写去重水位 `collect_processed`；`update_at` 统一刷新 |
| 新增 `write-through.ts`（续） | `writeAndRefresh` 先委托 `writeBatchToD1` 完成 events 写穿 + 游标/水位推进，再触发 `refreshPublicReadSnapshots` 刷新公开快照（复用 Phase A 快照链路），返回 `{ written, next_cursor, refreshed }`，构成「写入 → 快照刷新 → 公开面更新」最小闭环；`resolutionPipelineStage` 缺省推断 JUDGED |
| 新增 `collect-cycle.ts` | `runCollectCycle` 端到端编排：读游标 → `nextBatch` 环形选 target（默认 batchSize 8）→ `fetchCollectedEvents` 抓取归一 → `filterEvents` 过滤（水位捷径，真去重靠 events upsert 幂等兜底）→ `assignClusters` 聚类 → `classifyEvent` 分类 → `judgeEvent` 研判 → `writeAndRefresh` 写穿；只组合不重写，复用 B2/B3/B4 既有导出 |
| 去重与状态语义 | events 表 `ON CONFLICT(event_id)` upsert 幂等是真正的去重兜底，去重水位 `knownIds` 仅作为批内捷径、不承担唯一性；采集游标与去重水位持久化于 D1 `ops_state`，跨 worker 调用可恢复 |

关键语义：`KvRepo` 是采集层状态存取的唯一依赖，业务函数不直接绑定 D1 `prepare/bind`，从而游标/水位纯逻辑可用 `MapKvRepo` 桩无 D1 测试；`WriteTable` 可注入（`setWriteTable`）以支持断言 SQL/bind；`refresh`/`fetcher`/`repo` 均可注入，生产缺省用 `D1KvRepo` 与 `refreshPublicReadSnapshots`。`runCollectCycle` 为纯编排层，不重写任何既有逻辑，把所有 P0-B3/B4 函数串成一个完整采集周期，回执即 `{ processed, written, next_cursor, refreshed }`。

无回归：Cloudflare 全套 **215 项测试全绿**（含新增 B4 写穿/编排与既有 B1-B3 用例），本相位仅新增 Cloudflare 侧 collect 层，未 touch Python 基线，Python 对应行为基准仍成立。至此 Cloudflare Worker 侧已具备自 `collect` 至公开读快照刷新的完整自由层采集闭环。
