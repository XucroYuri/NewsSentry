# Cloudflare Phase 2 additive migration runbook

> 适用范围：`frontend/cloudflare/db/migrations/20260802_phase2_import_staging.sql`
> 及后续 additive D1 migration。

## 核心原则

- 不假设 SQLite/D1 支持可移植的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- 不重复盲跑含 `ALTER TABLE ADD COLUMN` 的 migration。
- `wrangler d1 migrations list` 只能证明 pending 队列；生产 applied 证据以
  `d1_migrations` 表为准。
- 若 migration 部分执行，先做 schema preflight，再用补丁 migration 或人工恢复脚本补齐缺项。

## 部署前 preflight

1. 查询已应用 migration：

   ```bash
   cd frontend/cloudflare
   npx wrangler d1 execute ns-db --remote \
     --command "SELECT name FROM d1_migrations ORDER BY name" \
     --json
   ```

2. 若 `20260802_phase2_import_staging.sql` 已在 `d1_migrations` 中，禁止再次直接执行该文件。
3. 若未应用但线上 schema 已出现部分列/表，停止部署，记录以下探针结果：

   ```bash
   npx wrangler d1 execute ns-db --remote \
     --command "PRAGMA table_info(import_batches)" --json
   npx wrangler d1 execute ns-db --remote \
     --command "PRAGMA table_info(import_batch_chunks)" --json
   npx wrangler d1 execute ns-db --remote \
     --command "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('import_staged_events','import_batch_finalize_receipts')" \
     --json
   ```

4. 只有在缺失项明确、补丁 SQL 只包含尚未存在的 additive 变更时，才执行补丁 migration。

## 部分应用恢复

- 已存在列：不要再执行相同 `ALTER TABLE ADD COLUMN`。
- 已存在表/索引：使用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 可恢复。
- 缺失 `runtime_migration_receipts` 行：可单独 `INSERT OR IGNORE`。
- 恢复后再次查询 `d1_migrations` 和上述 `PRAGMA`，把 JSON receipt 附到部署记录。

## 本地 guard

部署 workflow 使用 `tools/cloudflare_deploy_guard.py preflight` 在 Worker deploy 前验证：

- Queue 与 DLQ 存在；缺失时 verify-only 模式明确阻塞。
- `news-sentry-jobs` consumer 存在且 batch/timeout/retry/concurrency 符合 Phase 2 基线。
- `d1_migrations` 已包含 Phase 0/1/2 必需 migration。
- `wrangler.toml` 显式声明 `SCHEDULER_MODE=shadow` 与
  `WORKER_NATIVE_COLLECT_ENABLED=false`。
