# Cloudflare Phase 2 additive migration runbook

> 适用范围：`frontend/cloudflare/db/migrations/20260802_phase2_import_staging.sql`
> 及后续 additive D1 migration。

## 核心原则

- 不假设 SQLite/D1 支持可移植的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- 不重复盲跑含 `ALTER TABLE ADD COLUMN` 的 migration。
- `wrangler d1 migrations list` 只能证明 pending 队列；本项目生产 applied 证据以
  `runtime_migration_receipts` 表为准。
- 若 migration 部分执行，先做 schema preflight，再用补丁 migration 或人工恢复脚本补齐缺项。

## Phase 4 projection import migration

`frontend/cloudflare/db/migrations/20260802_phase4_projection_import.sql` 是 Phase 2 之后的
append-only migration。它只新增 projection-only finalize 所需的 D1 对象：

- `import_projection_finalize_receipts`
- `idx_projection_receipts_idempotency_key`
- `trg_projection_receipt_reject_source_receipt`
- `trg_source_receipt_reject_projection_receipt`
- `runtime_migration_receipts.migration_id = '20260802_phase4_projection_import'`

不得修改已提交的 Phase 0/1/2 migration，不得压扁 `db/schema.sql` 后重写历史 migration，也不得
删除 `runtime_migration_receipts` 来重跑已经应用的 Phase 4。若远端 schema 部分存在但 receipt
缺失，先保存 PRAGMA/table/index/trigger 证据，再用只补缺项的 additive SQL 或 guard 的
`record-runtime-receipts` 恢复 receipt。

## 部署前 preflight

1. 查询项目 runtime migration receipt：

   ```bash
   cd frontend/cloudflare
   node_modules/.bin/wrangler d1 execute ns-db --remote \
     --command "SELECT migration_id FROM runtime_migration_receipts ORDER BY migration_id" \
     --json
   ```

2. 若 `20260802_phase2_import_staging` 已在 `runtime_migration_receipts` 中，禁止再次直接执行该 Phase 2 `ALTER TABLE ADD COLUMN` 文件。
3. 若未应用但线上 schema 已出现部分列/表，停止部署，记录以下探针结果：

   ```bash
   node_modules/.bin/wrangler d1 execute ns-db --remote \
     --command "PRAGMA table_info(quarantined_events)" --json
   node_modules/.bin/wrangler d1 execute ns-db --remote \
     --command "PRAGMA table_info(import_batches)" --json
   node_modules/.bin/wrangler d1 execute ns-db --remote \
     --command "PRAGMA table_info(import_batch_chunks)" --json
   node_modules/.bin/wrangler d1 execute ns-db --remote \
     --command "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('import_staged_events','import_batch_finalize_receipts','dlq_replay_receipts','dlq_consumption_receipts')" \
     --json
   ```

4. 若 `db/schema.sql` 已经初始化到 Phase 2 等价 schema，不再盲跑 Phase 2 `ALTER` 文件；先运行 guard 的 `record-runtime-receipts`，它会在 PRAGMA/table schema 证明通过后写入项目 receipt。
5. 只有在缺失项明确、补丁 SQL 只包含尚未存在的 additive 变更时，才执行补丁 migration。

## 部分应用恢复

- 已存在列：不要再执行相同 `ALTER TABLE ADD COLUMN`。
- 已存在表/索引：使用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 可恢复。
- 缺失 `runtime_migration_receipts` 行：可单独 `INSERT OR IGNORE`。
- 恢复后再次查询 `runtime_migration_receipts` 和上述 `PRAGMA`，把 JSON receipt 附到部署记录。

## 本地 guard

部署 workflow 使用 `tools/cloudflare_deploy_guard.py preflight` 在 Worker deploy 前验证：

- Queue 与 DLQ 存在；缺失时 verify-only 模式明确阻塞。
- `news-sentry-jobs` consumer 存在且 batch/timeout/retry/concurrency 符合 Phase 2 基线。
- `runtime_migration_receipts` 已包含 Phase 0/1/2 必需 project receipt，并用 PRAGMA/table probes 证明 Phase 2 schema 等价。
- `wrangler.toml` 显式声明 `SCHEDULER_MODE=shadow` 与
  `WORKER_NATIVE_COLLECT_ENABLED=false`。

## Queue authoritative 停止线

当前 Queue consumer 只验证 shadow/import-staging job，不会从 source 配置执行真实采集。因而：

- production 必须继续使用 `SCHEDULER_MODE=shadow`，由 Cron 调用 Container 完成 Python pipeline；
- 即使 `NEWS_SENTRY_QUEUE_CUTOVER_RECEIPT` 其余字段全部合法，runtime 也必须返回
  `queue_authoritative_runner_unavailable` 并拒绝 readiness；
- 只有真实 collector runner、D1/R2 staging、fenced source watermark、snapshot 刷新和 72 小时
canary 均有回执后，才允许在独立变更中解除该停止线。

## 生产采集与发布证明

生产 Cron 每 15 分钟选择一个启用 target 作为低成本旋转 canary，Container 继续保持
`sleepAfter = "5m"`，避免把 15 分钟周期变成近似常驻费用。Container 从休眠恢复时，Worker 先用
`startAndWaitForPorts()` 显式等待实例和应用端口就绪：实例取得预算为 60 秒、端口就绪预算为
120 秒、轮询间隔为 500 毫秒，并与后续采集共用 8 分钟总超时。若 SDK 仍返回可识别的临时启动
失败，Worker 最多再尝试 5 次 `fetch()`，间隔为 5、15、30、45 秒。只有采集状态为
`ok`、`partial` 或 `empty_no_new_items` 时才推进 target cursor，失败不会跳过该 target。

生产发布回执必须同时满足：

- Worker version 的 tag/message 包含精确 40 位 `GITHUB_SHA`；
- 当前 deployment 以 100% 流量指向该 Worker version；
- D1 `last:collect-cycle` 由同一 commit、同一 Worker version 成功写入，并包含非空 target 选择；
- migration、Queue/DLQ/R2、数据新鲜度、未来时间戳和 P0 DLQ 门禁通过。

GitHub Runner 访问自定义域名时若收到可识别的 Cloudflare Challenge 403，可只把公网 HTTP 探针
降级为观察项，并使用上述控制面 + D1 回执继续验证。普通 403、5xx、畸形回执、旧 commit/旧
Worker version 或失败采集不能走该回退。此机制不要求开放 `workers.dev`，也不要求为 CI 放宽
WAF/Bot 策略。

## 隔离 Preview 验证面

Preview 不复用生产 Worker 或 D1。`deploy-cloudflare-preview-worker` 只允许：

- Worker：`news-sentry-api-preview`，入口为该 Worker 的 canonical HTTPS `workers.dev` origin；
- D1：`ns-db-preview`，workflow 先 list，缺失时 create，再 re-list 并要求唯一 UUID；
- bindings：`DB`、`CF_VERSION_METADATA` 和 Preview vars；
- 数据：完整 schema 加一条新鲜 synthetic event、ops heartbeat 和 public read snapshots。

Preview 明确不包含生产 routes、Queue、Cron、Container、Durable Object 或生产 D1 ID。它证明的
范围只有当前 commit 的公开 API、D1、`live/ready/health` 与 Pages 到 Preview API 的构建绑定。
Queue/Cron/Container/DO 必须在独立 canary 和生产 receipt 中验证，不能用 Preview 绿色替代。

任何 D1 名称歧义、非法 UUID、Wrangler NDJSON 回执缺失、Worker/environment 不匹配、非
`workers.dev` origin、Pages deploy URL 无法解析，或 frontend bundle 未嵌入 Preview API URL，
都必须 fail closed。

### Preview durable import canary

Task 9 的 Preview canary 使用正常受保护入口
`https://news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import`，不增加 preview-only
公开测试路由。GitHub `preview` Environment 必须包含：

- Variables：`CF_ACCESS_TEAM_DOMAIN`、`CF_ACCESS_AUD`、`CF_ACCESS_SERVICE_TOKEN_IDS`
- Secrets：`CF_ACCESS_CLIENT_ID`、`CF_ACCESS_CLIENT_SECRET`

Worker deploy 只注入上述三个非秘密变量。`CF_ACCESS_CLIENT_SECRET` 只作为 workflow 请求头
输入存在，不能进入 Worker vars、D1/R2、日志、artifact 或上传回执。

验证顺序固定为：

1. 不携带 Access token 对 `/api/v1/events/import` POST synthetic canary payload，必须返回 403，
   且 R2/D1 均不变。
2. 携带 `CF-Access-Client-Id`、`CF-Access-Client-Secret` 和
   `Idempotency-Key: preview-artifact-canary:<full commit>` POST，同一 payload 首次必须 200。
3. 重放同一请求必须 200 且 `replayed=true`，不得新增第二个 artifact、batch 或 event。
4. 用 Wrangler 只读查询 `ns-db-preview`，交叉检查 `artifact_manifests`、
   `import_batches`、`jobs`、`import_projection_finalize_receipts` 和 event count。
5. 用响应中的 content-addressed key 只读 GET `news-sentry-artifacts-preview`，校验 key、
   SHA-256 和 UTF-8 bytes 与 D1 manifest 一致。
6. 上传的 receipt 只包含摘要、对象 key、SHA-256、bytes、状态和计数；不得包含 secrets、JWT、
   原始请求头或完整 payload。

Task 8 只完成本地文档和验证。上述匿名 403、机器 200、重放、D1/R2 cross-check 与 restore
必须等 Task 9 在精确远端 SHA 上执行后，才能写成已完成事实。

### Promotion state vocabulary

文档和回执只使用以下四层状态，不互相替代：

1. **Local implementation**：本地代码、测试、lint/typecheck/build 和 Wrangler dry-run 通过。
2. **Preview proof**：隔离 Preview 在同一候选 SHA 上完成匿名 403、机器 200、幂等重放、D1/R2 cross-check 和 restore receipt。
3. **72h production canary**：`main` 的同一 production SHA 连续 12 个 6 小时健康回执通过，且有真实 committed artifact。
4. **7d continuous healthy**：同一 production SHA 连续 28 个 6 小时健康回执通过，continuity ledger 为 `slo_7d_passed`，并有绑定同 commit 和真实 artifact 的隔离 restore receipt。

只有第 4 层允许把 Cloudflare-native production recovery 写成已证明。Preview synthetic canary、
branch-only commit、本地 SQLite、本地 drafts、VPS/Tunnel/systemd 状态都不能提升这个状态。

候选分支推送后，从该分支执行隔离 Preview：

```bash
gh workflow run deploy.yml \
  --ref dev-xu/fix/cloudflare-persistent-runtime \
  -f environment=preview
```

workflow 会把所有部署运行全局串行化，避免不同触发方式并发写入同一 Cloudflare surface。手动 Preview 的 Pages branch 使用
`manual-preview-${GITHUB_RUN_ID}`，不会写入 Pages production branch；Worker 固定为
`news-sentry-api-preview`。`environment=production` 只允许在 `refs/heads/main` 调用，其他分支
会在 CI 第一阶段 fail closed。

Preview 绿色后只产出验证证据，不再由 workflow 直接 fast-forward/push `main`。生产提升必须：

1. 以候选分支创建到 `main` 的 PR；
2. 要求 CI、Preview receipt 与安全审计通过；
3. 经人工合并后确认远端 `main` 的完整 40 位 commit SHA；
4. 从 `main` 手动运行 `deploy.yml`，选择 `production` 并把该完整 SHA 作为
   `expected_commit`；workflow 会拒绝非 `main`、空 SHA、非法 SHA 或与 `GITHUB_SHA` 不一致的请求；
5. 收集 production Worker/D1/Queue/Pages/health 同 commit receipt。

当前远端 `main`/`preview` 尚未启用 branch protection；在保护规则建立前，不得把“PR 流程”写成
强制治理事实。为降低这一远端治理缺口的风险，`main` push 不再触发 production，生产提升必须
通过上述精确 commit 手动门禁。

### Committed artifact restore drill

Preview canary 成功后，`cloudflare-restore-drill.yml` 不得接受
`artifact_coverage=not_available`。恢复演练必须从 latest committed manifest 下载真实 R2 artifact，
校验 key、SHA-256、UTF-8 bytes，并要求 `continuity_receipt.status=slo_7d_passed` 且
`continuity_receipt.deployed_commit` 等于本次 workflow checkout 的完整 40 位 `expected_commit`。
然后在隔离 D1 中验证：

- `runtime_migration_receipts` 包含 Phase 0/1/2 和
  `20260802_phase4_projection_import`；
- source-fenced 与 projection-only 两类 finalize receipt 均无 orphan；
- 同一 `batch_id` 不得同时存在 source 和 projection receipt；
- `artifact_manifests.status = committed` 的对象可被 R2 读取且 checksum/bytes 匹配；
- latest committed artifact 至少包含一条非 synthetic / 非 preview-canary 的真实事件；synthetic-only
  Preview artifact 只能证明 Preview canary，不得作为 production recovery 证据；
- cleanup 后隔离 D1 明确 `verified_absent=true`。

任一缺失、冲突、orphan、checksum/bytes 漂移、commit drift、`slo_7d_passed` 缺失、synthetic-only
artifact 或 cleanup 不确定，都必须 fail closed，不能作为 production promotion 证据。上传 artifact
只能是 sanitized restore receipt；不能上传 raw SQL export、raw import artifact、Service Token、
原始请求头、本地路径或未脱敏 continuity ledger。
