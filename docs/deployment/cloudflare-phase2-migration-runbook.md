# Cloudflare Phase 2 additive migration runbook

> 适用范围：`frontend/cloudflare/db/migrations/20260802_phase2_import_staging.sql`
> 及后续 additive D1 migration。

## 核心原则

- 不假设 SQLite/D1 支持可移植的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- 不重复盲跑含 `ALTER TABLE ADD COLUMN` 的 migration。
- `wrangler d1 migrations list` 只能证明 pending 队列；本项目生产 applied 证据以
  `runtime_migration_receipts` 表为准。
- 若 migration 部分执行，先做 schema preflight，再用补丁 migration 或人工恢复脚本补齐缺项。

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
