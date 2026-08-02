# Cloudflare Durable Import and Preview Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 API、Scheduled Container 和 Queue 三条 Cloudflare 导入路径统一到 R2-first 持久化协议，并在隔离 Preview 中用 Cloudflare Access Service Token 生成、交叉校验和恢复一份真实不可变导入制品。

**Architecture:** R2 保存内容寻址、不可覆盖的导入正文，D1 只保存查询投影、批次状态、作业状态和完整性回执。API/Container 使用 `projection-only` finalize，Queue 保留 `source-fenced` finalize；两种模式共享分块 staging，但使用独立回执、独立 SQL 和数据库级互斥约束。Preview 通过正常 `/api/v1/events/import` 路径验证机器身份、幂等重放、D1/R2 一致性和隔离恢复，不增加测试专用路由。

**Tech Stack:** Cloudflare Workers TypeScript、D1/SQLite、R2、Cloudflare Access、Wrangler 4.114.0、GitHub Actions、Python 3.12、Node.js 22 内置 test runner、pytest。

## Global Constraints

- 所有会改变 D1 新闻投影的导入路径必须先成功持久化 R2 不可变正文。
- API/Container 使用 `projection-only`；Queue 使用 `source-fenced`，不得通过可选 lease 字段隐式推断模式。
- 相同规范化正文必须得到相同 `payload_sha256`、batch、job 和 artifact；客户端 `Idempotency-Key` 不得覆盖正文身份。
- R2 binding 缺失、put/head/checksum 不一致、D1 finalize guard 失败时必须 fail-closed。
- Service Token 只信任已验签的 `Cf-Access-Jwt-Assertion.common_name`，不信任原始 Client ID/Secret 请求头。
- Preview 不启用 Container、Cron 或 Queue，不访问新闻源、不调用 AI Provider、不修改生产 D1/R2/Worker。
- Client Secret 只存在 GitHub `preview` Environment Secret，绝不进入 Worker vars、日志、制品或回执。
- 本计划不合并 PR、不部署生产、不启动生产 72 小时 canary；生产切换另立发布计划。
- 不新增第三方依赖；复用 Web Crypto、Node/Python 标准库和现有 Wrangler。
- 不修改或暂存 `.omo/`、`src/news_sentry/core/latent_value_model.py`、`tests/unit/test_latent_value_model.py`。

## File Structure

- `frontend/cloudflare/workers/lib/access-jwt.ts`：验签并返回 user/service 判别联合 principal。
- `frontend/cloudflare/workers/lib/access.ts`：按路径和 principal 类型执行最小权限写入授权。
- `frontend/cloudflare/workers/lib/import-staging.ts`：共享分块 staging 和显式 finalize 策略。
- `frontend/cloudflare/workers/lib/projection-sql.ts`：从 `import_staged_events` 原子提升公开投影的 SQL 构造器。
- `frontend/cloudflare/workers/lib/durable-import.ts`：规范化 envelope、确定性身份、R2-first 编排和快照状态机。
- `frontend/cloudflare/workers/api/webhook.ts`：薄 HTTP 适配层，不再直接写 D1。
- `frontend/cloudflare/workers/lib/container-import.ts`：薄 Container 适配层，委托共享 durable import。
- `frontend/cloudflare/db/migrations/20260802_phase4_projection_import.sql`：追加式 projection receipt、唯一索引和双向互斥 trigger。
- `tools/cloudflare_preview_canary.py`：生成确定性 canary、构造只读证据查询、产出脱敏回执。
- `tools/cloudflare_restore_drill.py`：验证两类 finalize receipt、孤儿、冲突和 committed artifact。
- `.github/workflows/deploy.yml`：注入 Preview Access 非秘密变量并运行两次幂等 canary。
- `.github/workflows/cloudflare-restore-drill.yml`：Preview 真实制品成为强制门禁。

---

### Task 1: Cloudflare Access user/service principal

**Files:**
- Modify: `frontend/cloudflare/workers/lib/access-jwt.ts:1-256`
- Modify: `frontend/cloudflare/workers/lib/access.ts:1-90`
- Modify: `frontend/cloudflare/workers/lib/router.ts:19-38`
- Modify: `frontend/cloudflare/workers/index.ts:36-157`
- Modify: `frontend/cloudflare/workers/api/proxy.ts:16-50`
- Modify: `frontend/cloudflare/workers/api/dlq-replay.ts:85-110`
- Test: `frontend/cloudflare/tests/access-jwt.test.mts`

**Interfaces:**
- Produces: `AccessPrincipal = UserAccessPrincipal | ServiceAccessPrincipal`。
- Produces: `verifyCloudflareAccessJwt(...): Promise<AccessJwtVerification>`，成功结果包含 `principal`。
- Produces: `authorizeWorkerWriteAccess(...)`，service principal 仅允许精确 `/api/v1/events/import`。
- Consumes later: Task 4 的 API import 和 Task 7 的 Preview Service Token canary。

- [ ] **Step 1: 写 Service Token principal 失败测试**

在 `access-jwt.test.mts` 的 `signedJwt()` 默认 claims 中增加 `type: "app"`，新增以下测试：

```ts
test("accepts an allowlisted Access service principal from signed common_name", async () => {
  const { jwt, jwks } = await signedJwt({
    email: undefined,
    common_name: "preview-client-id.access",
    type: "app",
  });
  const result = await verifyCloudflareAccessJwt(
    jwt,
    { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access" },
    { jwks, now },
  );
  assert.deepEqual(result.principal, {
    kind: "service",
    id: "preview-client-id.access",
    commonName: "preview-client-id.access",
  });
});

test("rejects non-allowlisted service principals and service access outside import", async () => {
  const { jwt, jwks } = await signedJwt({
    email: undefined,
    common_name: "other-client.access",
    type: "app",
  });
  assert.equal(
    (await verifyCloudflareAccessJwt(jwt, {
      ...env,
      CF_ACCESS_SERVICE_TOKEN_IDS: "preview-client-id.access",
    }, { jwks, now })).reason,
    "service_principal_not_allowed",
  );
  const blocked = await authorizeWorkerWriteAccess(
    new Request("https://api.news-sentry.com/api/v1/jobs/dlq/replay", {
      method: "POST",
      headers: { "Cf-Access-Jwt-Assertion": jwt },
    }),
    { ...env, CF_ACCESS_SERVICE_TOKEN_IDS: "other-client.access" },
    { jwks, now },
  );
  assert.equal(blocked.ok, false);
});
```

同时增加：伪造 `CF-Access-Client-Id`/`CF-Access-Client-Secret` 但没有 assertion 返回 403；`type !== "app"`、空 `common_name`、错误 issuer/aud/exp/nbf/signature 全部拒绝。

- [ ] **Step 2: 运行红测**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test tests/access-jwt.test.mts
```

Expected: FAIL，因为 `AccessJwtClaims` 没有 `common_name`，验证结果没有 `principal`，且当前强制 `email`。

- [ ] **Step 3: 实现判别联合 principal 和 allowlist**

在 `access-jwt.ts` 定义并使用：

```ts
export interface CloudflareAccessJwtEnv {
  CF_ACCESS_AUD?: string;
  CF_ACCESS_TEAM_DOMAIN?: string;
  CF_ACCESS_SERVICE_TOKEN_IDS?: string;
  NEWS_SENTRY_ACCESS_AUD?: string;
  NEWS_SENTRY_ACCESS_TEAM_DOMAIN?: string;
}

export type AccessPrincipal =
  | { kind: "user"; id: string; email: string }
  | { kind: "service"; id: string; commonName: string };

export interface AccessJwtClaims {
  aud?: string | string[];
  common_name?: string;
  email?: string;
  exp?: number;
  iat?: number;
  iss?: string;
  nbf?: number;
  sub?: string;
  type?: string;
  [claim: string]: unknown;
}

export interface AccessJwtVerification {
  claims?: AccessJwtClaims;
  ok: boolean;
  principal?: AccessPrincipal;
  reason?: string;
}
```

JWT 处理顺序固定为结构/alg/kid → JWKS key → RS256 signature → issuer → audience → exp → nbf → `type === "app"` → principal。service allowlist 以逗号分隔、trim 后做精确字符串匹配；空 allowlist 不接受任何 service principal。未验签 claims 不得参与授权决定。

- [ ] **Step 4: 收紧写路径和 metadata 消费者**

将 `WorkerWriteAccessDecision.identity` 和 `RuntimeMetadata.access` 改为 `AccessPrincipal | null`。授权规则使用精确 canonical path：

```ts
if (verification.principal?.kind === "service" && url.pathname !== "/api/v1/events/import") {
  return { ok: false, response: accessRequired() };
}
```

`dlq-replay.ts` 只接受 `kind === "user"` 的 email。`proxy.ts` 只为 user principal 写 `Cf-Access-Authenticated-User-Email`；service principal 不伪造 email。

- [ ] **Step 5: 运行 Access 与 Worker 全测**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test tests/access-jwt.test.mts
npm test
npm run types
```

Expected: PASS；现有人类 Access 测试继续通过，机器身份只获准 import。

- [ ] **Step 6: Commit**

```bash
git add frontend/cloudflare/workers/lib/access-jwt.ts \
  frontend/cloudflare/workers/lib/access.ts \
  frontend/cloudflare/workers/lib/router.ts \
  frontend/cloudflare/workers/index.ts \
  frontend/cloudflare/workers/api/proxy.ts \
  frontend/cloudflare/workers/api/dlq-replay.ts \
  frontend/cloudflare/tests/access-jwt.test.mts
git commit -m "feat(cloudflare): authorize preview service principals"
```

---

### Task 2: Projection finalize schema and database-enforced mode exclusivity

**Files:**
- Create: `frontend/cloudflare/db/migrations/20260802_phase4_projection_import.sql`
- Modify: `frontend/cloudflare/db/schema.sql:293-382`
- Modify: `tools/cloudflare_runtime_contract.py:5-11`
- Modify: `tools/cloudflare_deploy_guard.py:53-429`
- Test: `tests/unit/test_cloudflare_job_runtime_schema.py`
- Test: `tests/tools/test_cloudflare_deploy_guard.py`

**Interfaces:**
- Produces: D1 table `import_projection_finalize_receipts`。
- Produces: unique partial index `idx_projection_receipts_idempotency_key`。
- Produces: triggers `trg_projection_receipt_reject_source_receipt` and `trg_source_receipt_reject_projection_receipt`。
- Produces: migration receipt `20260802_phase4_projection_import`，供 deploy/restore gates 消费。

- [ ] **Step 1: 写 schema/migration 红测**

在 SQLite schema 测试中断言：

```python
projection_columns = {
    row[1]
    for row in connection.execute(
        "PRAGMA table_info(import_projection_finalize_receipts)"
    )
}
assert projection_columns == {
    "batch_id", "job_id", "batch_checksum", "artifact_id", "finalized_at",
    "batch_guard", "job_guard", "artifact_guard", "origin",
    "request_idempotency_key_hash",
}
assert "20260802_phase4_projection_import" in EXPECTED_MIGRATION_RECEIPTS
```

构造同一个 batch，先插入 source receipt 再插 projection receipt，反向再测一次，均断言 SQLite 抛出 `import_finalize_receipt_mode_conflict`。

- [ ] **Step 2: 运行红测**

Run:

```bash
python -m pytest \
  tests/unit/test_cloudflare_job_runtime_schema.py \
  tests/tools/test_cloudflare_deploy_guard.py -q
```

Expected: FAIL，缺少 Phase 4 table、index、triggers 和 migration receipt。

- [ ] **Step 3: 写 append-only migration 和 canonical schema**

迁移及 `schema.sql` 使用同一 SQL：

```sql
CREATE TABLE IF NOT EXISTS import_projection_finalize_receipts (
    batch_id TEXT PRIMARY KEY REFERENCES import_batches(batch_id),
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
    batch_checksum TEXT NOT NULL,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES artifact_manifests(artifact_id),
    finalized_at TEXT NOT NULL,
    batch_guard TEXT NOT NULL,
    job_guard TEXT NOT NULL,
    artifact_guard TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('api-import', 'container-import')),
    request_idempotency_key_hash TEXT
        CHECK (request_idempotency_key_hash IS NULL OR length(request_idempotency_key_hash) = 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projection_receipts_idempotency_key
    ON import_projection_finalize_receipts(request_idempotency_key_hash)
    WHERE request_idempotency_key_hash IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_projection_receipt_reject_source_receipt
BEFORE INSERT ON import_projection_finalize_receipts
WHEN EXISTS (
    SELECT 1 FROM import_batch_finalize_receipts WHERE batch_id = NEW.batch_id
)
BEGIN
    SELECT RAISE(ABORT, 'import_finalize_receipt_mode_conflict');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_receipt_reject_projection_receipt
BEFORE INSERT ON import_batch_finalize_receipts
WHEN EXISTS (
    SELECT 1 FROM import_projection_finalize_receipts WHERE batch_id = NEW.batch_id
)
BEGIN
    SELECT RAISE(ABORT, 'import_finalize_receipt_mode_conflict');
END;

INSERT OR IGNORE INTO runtime_migration_receipts (migration_id, details_json)
VALUES (
    '20260802_phase4_projection_import',
    '{"finalize_modes":["source-fenced","projection-only"],"authoritative_projection":true}'
);
```

- [ ] **Step 4: 扩展 deploy guard 的精确 schema contract**

把新 receipt 加入 `RUNTIME_SCHEMA_TABLE_QUERY`、`SCHEMA_REQUIREMENTS`、index 查询和 `RUNTIME_RECEIPT_INSERT_SQL`。要求主键 `batch_id`、`job_id` unique、`artifact_id` unique 和 partial idempotency index 均可远端证明。

- [ ] **Step 5: 运行 schema/guard 测试**

Run:

```bash
python -m pytest \
  tests/unit/test_cloudflare_job_runtime_schema.py \
  tests/tools/test_cloudflare_deploy_guard.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/cloudflare/db/schema.sql \
  frontend/cloudflare/db/migrations/20260802_phase4_projection_import.sql \
  tools/cloudflare_runtime_contract.py tools/cloudflare_deploy_guard.py \
  tests/unit/test_cloudflare_job_runtime_schema.py \
  tests/tools/test_cloudflare_deploy_guard.py
git commit -m "feat(cloudflare): add projection finalize receipts"
```

---

### Task 3: Explicit staging strategies and atomic staged-to-public projection

**Files:**
- Create: `frontend/cloudflare/workers/lib/projection-sql.ts`
- Modify: `frontend/cloudflare/workers/lib/import-staging.ts:35-715`
- Modify: `frontend/cloudflare/workers/lib/queue-shadow.ts:116-135`
- Test: `frontend/cloudflare/tests/import-staging.test.mts`
- Test: `frontend/cloudflare/tests/import-staging-sqlite.test.mts`

**Interfaces:**
- Produces: `ImportFinalizeStrategy` discriminated union。
- Produces: `stageImportBatch(db, input)`，`input.artifact` 与 `input.finalize` 为必填。
- Produces: `projectionFinalizeStatements(db, input, checksum, counts)`，不读取或推进 source cursor。
- Preserves: Queue 的 lease/fencing/source watermark 语义。

- [ ] **Step 1: 写 projection-only 原子 finalize 红测**

新增 SQLite 集成测试：

```ts
test("projection-only finalize atomically commits projection receipt job batch artifact", async () => {
  const db = new SqliteD1Database();
  seedProjectionJob(db, "api-job:abc");
  const artifact = seedProjectionArtifact(db, "api-batch:abc", "api-job:abc");
  const beforeCursor = db.first<{ cursor: string }>(
    "SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'",
    [],
  );

  await stageImportBatch(db as unknown as D1Database, {
    batchId: "api-batch:abc",
    jobId: "api-job:abc",
    targetId: "multi",
    sourceId: "multi",
    outputWatermark: null,
    events: [event(1)],
    generatedAt: "2026-08-02T00:00:00Z",
    artifact,
    finalize: {
      mode: "projection-only",
      origin: "api-import",
      requestIdempotencyKeyHash: "b".repeat(64),
    },
  });

  assert.equal(db.first("SELECT status FROM jobs WHERE job_id='api-job:abc'", [])?.status, "committed");
  assert.equal(db.first("SELECT status FROM import_batches WHERE batch_id='api-batch:abc'", [])?.status, "committed");
  assert.equal(db.first("SELECT status FROM artifact_manifests WHERE batch_id='api-batch:abc'", [])?.status, "committed");
  assert.equal(db.first("SELECT COUNT(*) AS count FROM import_projection_finalize_receipts", [])?.count, 1);
  assert.equal(db.first("SELECT COUNT(*) AS count FROM events WHERE event_id='evt-1'", [])?.count, 1);
  assert.deepEqual(db.first("SELECT cursor FROM source_runtime_state WHERE target_id='italy' AND source_id='ansa'", []), beforeCursor);
});
```

再增加：final batch 中任一 statement 强制失败时 event/receipt 变更回滚、job 保持 `running`、batch 保持 `importing`、manifest 保持 `stored`；重放不增加 event/receipt；source-fenced 没有 lease/fence 仍失败；两类 receipt 冲突失败。

- [ ] **Step 2: 运行红测**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test \
  tests/import-staging.test.mts \
  tests/import-staging-sqlite.test.mts
```

Expected: FAIL，因为当前 `stageImportBatch()` 只认可选 lease/fencing、只写 source receipt，且不提升 `events`。

- [ ] **Step 3: 引入显式 finalize union**

在 `import-staging.ts` 定义：

```ts
export type ImportFinalizeStrategy =
  | {
      mode: "source-fenced";
      leaseToken: string;
      fencingVersion: number;
    }
  | {
      mode: "projection-only";
      origin: "api-import" | "container-import";
      requestIdempotencyKeyHash: string | null;
    };

export interface ImportStagingInput {
  batchId: string;
  jobId: string;
  targetId: string;
  sourceId: string;
  outputWatermark: string | null;
  events: ImportStagingEvent[];
  generatedAt: string;
  artifact: ImportArtifactDescriptor;
  finalize: ImportFinalizeStrategy;
}
```

`stageImportBatchFromMessage()` 必须显式构造 `mode: "source-fenced"`；lease/fencing 缺失立即抛 validation error，不允许回退 projection-only。

- [ ] **Step 4: 用固定数量 SQL 从 staged JSON 提升投影**

`projection-sql.ts` 导出：

```ts
export interface ProjectionCounts {
  imported: number;
  updated: number;
}

export function projectionFinalizeStatements(
  db: D1Database,
  input: ImportStagingInput & { generatedAt: string },
  checksum: string,
  counts: ProjectionCounts,
): D1PreparedStatement[];
```

statement 顺序固定为：

1. 插入 projection receipt，`batch_guard` 校验 chunks 完整，`job_guard` 校验 deterministic job 为 `running`，`artifact_guard` 校验 manifest 为 `stored|committed`，并用 trigger/`NOT EXISTS` 拒绝 source receipt。
2. 在投影前把 `imported_count`/`updated_count` 写入 batch；counts 由 staged event ID 与现有 `events` 的交集计算。
3. 一条 `INSERT INTO events (...) SELECT ... FROM import_staged_events WHERE batch_id=? ON CONFLICT(event_id) DO UPDATE SET ...` 提升全部事件；字段映射完整复用当前 `webhook.ts:260-421` 的列和 COALESCE 规则。
4. 一条 `INSERT INTO event_localizations (...) SELECT ... FROM import_staged_events, json_each(json_extract(payload_json, '$.localizations')) ... ON CONFLICT(event_id, locale) DO UPDATE SET ...` 提升全部 localization。
5. 更新 job 为 `committed`，清空 lease 字段。
6. 更新 batch 为 `committed`。
7. 更新 manifest 为 `committed`。

所有 statement 必须在同一次 `db.batch()` 中执行并逐项检查 `meta.changes`；receipt/job/batch/manifest 必须各恰好改变 1 行。

- [ ] **Step 5: 分模式加载重放 receipt**

`loadFinalizeReceipt()` 接收 `ImportFinalizeStrategy`：同模式 receipt 返回 replay；发现另一模式 receipt 抛 `import_finalize_receipt_mode_conflict`。projection replay 从 `import_batches.imported_count`/`updated_count` 返回原计数。

- [ ] **Step 6: 运行 staging 全测**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test \
  tests/import-staging.test.mts \
  tests/import-staging-sqlite.test.mts \
  tests/queue-shadow.test.mts
npm test
```

Expected: PASS；Queue 测试证明 source cursor 仍只由 source-fenced 推进。

- [ ] **Step 7: Commit**

```bash
git add frontend/cloudflare/workers/lib/projection-sql.ts \
  frontend/cloudflare/workers/lib/import-staging.ts \
  frontend/cloudflare/workers/lib/queue-shadow.ts \
  frontend/cloudflare/tests/import-staging.test.mts \
  frontend/cloudflare/tests/import-staging-sqlite.test.mts
git commit -m "feat(cloudflare): separate projection and source finalize"
```

---

### Task 4: Unified durable projection import for API and Container

**Files:**
- Create: `frontend/cloudflare/workers/lib/durable-import.ts`
- Modify: `frontend/cloudflare/workers/lib/router.ts:40-135`
- Modify: `frontend/cloudflare/workers/index.ts:174-210`
- Modify: `frontend/cloudflare/workers/api/webhook.ts:1-493`
- Modify: `frontend/cloudflare/workers/lib/container-import.ts:1-122`
- Modify: `frontend/cloudflare/workers/lib/contracts.ts:234-285`
- Modify: `frontend/cloudflare/workers/api/health.ts`
- Modify: `frontend/cloudflare/workers/lib/durable-artifact.ts:102-244`
- Test: `frontend/cloudflare/tests/durable-projection-import.test.mts`
- Test: `frontend/cloudflare/tests/api-durable-import.test.mts`
- Test: `frontend/cloudflare/tests/scheduled-durable-import.test.mts`
- Test: `frontend/cloudflare/tests/health.test.mts`
- Test: `frontend/cloudflare/tests/durable-artifact.test.mts`
- Test: `tests/unit/test_cloudflare_native_config.py`

**Interfaces:**
- Produces: `executeDurableProjectionImport(env, input): Promise<DurableProjectionImportResult>`。
- Produces: `RuntimeBindings = { artifacts?: R2Bucket }`，Router 仅把 binding 传给需要它的 handler。
- Produces: API response 中脱敏的 batch/job/artifact identity 和 `replayed`。
- Removes: API/Container 对 `importEventsToD1()`、`markImportArtifactCommitted()` 的直接调用。

- [ ] **Step 1: 写 envelope、R2-first、幂等红测**

新测试固定以下上限和语义：

```ts
export const MAX_IMPORT_EVENTS = 500;
export const MAX_IMPORT_BODY_BYTES = 8 * 1024 * 1024;
export const MAX_IDEMPOTENCY_KEY_BYTES = 512;
```

覆盖：空数组、非数组、501 项、超过 8 MiB、超过 512 字节的 Idempotency-Key、任一缺必填字段、全部 timestamp 无效均在 R2/D1 写入前返回 4xx；R2 缺失/校验失败返回 503 且 D1 投影不变；mixed target/source 成功；相同规范化 payload 重放 identity 不变；相同 Idempotency-Key hash 配不同 payload 返回 409。

确定性 identity 测试断言：

```ts
assert.equal(identity.batchId, `api-batch:${identity.payloadSha256}`);
assert.equal(identity.jobId, `api-job:${identity.payloadSha256}`);
assert.equal(identity.generatedAt, "2026-08-02T02:00:00.000Z");
```

- [ ] **Step 2: 运行红测**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test \
  tests/durable-projection-import.test.mts \
  tests/api-durable-import.test.mts \
  tests/scheduled-durable-import.test.mts
```

Expected: FAIL，新 service 和 R2 binding-aware handler 尚不存在。

- [ ] **Step 3: 实现规范化 envelope 和确定性 identity**

`durable-import.ts` 导出：

```ts
export type DurableProjectionOrigin = "api-import" | "container-import";

export interface DurableProjectionImportEnv {
  DB: D1Database;
  NEWS_SENTRY_ARTIFACTS?: R2Bucket;
}

export interface DurableProjectionImportInput {
  origin: DurableProjectionOrigin;
  events: Array<Record<string, unknown>>;
  idempotencyKey: string | null;
}

export interface DurableProjectionImportResult extends ImportStagingResult {
  jobId: string;
  artifactId: string;
  artifactKey: string;
  artifactSha256: string;
  artifactBytes: number;
  replayed: boolean;
}
```

对 URL 和 timestamp 使用现有 `validateExternalUrl()`/`assessEventTimestamps()`；以 `target_id\0source_id\0url\0title_original\0collected_at\0event_id` 稳定排序，递归排序对象键后计算 SHA-256。`generatedAt` 取有效规范化 `collected_at` 最大值。API identity 由 `` `api-batch:${payloadSha256}` ``/`` `api-job:${payloadSha256}` `` 构成；Container 使用对应的 `container-batch:`/`container-job:` 前缀。

- [ ] **Step 4: 实现 R2-first 编排和 deterministic projection job**

执行顺序必须是：

```ts
const identity = await buildDurableProjectionIdentity(input);
const existing = await loadProjectionReceiptByPayloadOrIdempotencyKey(env.DB, identity);
if (existing) return replayResult(existing);
const artifact = await persistImportArtifact(env.DB, env.NEWS_SENTRY_ARTIFACTS, {
  batchId: identity.batchId,
  jobId: identity.jobId,
  task: input.origin,
  targetIds: identity.events.map((event) => String(event.target_id)),
  sourceIds: identity.events.map((event) => String(event.source_id)),
  outputWatermark: null,
  generatedAt: identity.generatedAt,
  events: identity.events,
});
await ensureProjectionJob(env.DB, identity, input.origin);
return stageImportBatch(env.DB, {
  batchId: identity.batchId,
  jobId: identity.jobId,
  targetId: "multi",
  sourceId: "multi",
  outputWatermark: null,
  events: identity.events,
  generatedAt: identity.generatedAt,
  artifact,
  finalize: {
    mode: "projection-only",
    origin: input.origin,
    requestIdempotencyKeyHash: identity.idempotencyKeyHash,
  },
});
```

`ensureProjectionJob()` 只创建 `job_type='projection-import'`、`target_id='multi'`、`source_id='multi'`、`status='running'` 的确定性 job；不写 outbox，不更新 source state。

如果 chunk/finalize 抛错，service 以 best-effort 将相同 manifest 标记为 `failed` 后继续向上抛错，不得返回成功。下一次相同正文重试时，`persistImportArtifact()` 必须先用 R2 HEAD 再次证明 key/SHA/bytes/metadata 一致，然后把同一 manifest 从 `failed` 恢复为 `stored`、清除错误字段；不得创建第二个 object 或 manifest。

- [ ] **Step 5: 将 API 和 Container 变成薄适配器**

Router 增加：

```ts
export interface RuntimeBindings {
  artifacts?: R2Bucket;
}
```

`dispatch()` 最后一个参数传 `{ artifacts: env.NEWS_SENTRY_ARTIFACTS }`。`handleImport()` 读取 body、`Idempotency-Key`，调用共享 service，并映射错误：validation 400/413/422、idempotency conflict 409、durable storage 503、其余 500。返回体增加 `batch_id`、`job_id`、`artifact_id`、`artifact_key`、`artifact_sha256`、`artifact_bytes`、`replayed`。

`importContainerEventsToD1()` 只保留事件提取，随后调用：

```ts
executeDurableProjectionImport(env, {
  origin: "container-import",
  events,
  idempotencyKey: null,
});
```

删除 API/Container 正常路径对 `importEventsToD1()` 和独立 manifest commit/fail 的调用。

- [ ] **Step 6: 实现 snapshot_pending 状态和 readiness 降级**

projection commit 后刷新快照。失败时将 job 更新为 `snapshot_pending`，写 `last_error_code='snapshot_refresh_failed'`；`health.ts` 在存在 `snapshot_pending` projection job 时返回 readiness degraded。相同 payload 重放再次刷新，成功后恢复 job `committed`。

- [ ] **Step 7: 运行 API/Container/health 与结构测试**

Run:

```bash
cd frontend/cloudflare
node --experimental-strip-types --test \
  tests/durable-projection-import.test.mts \
  tests/api-durable-import.test.mts \
  tests/scheduled-durable-import.test.mts \
  tests/health.test.mts
npm test
cd ../..
python -m pytest tests/unit/test_cloudflare_native_config.py -q
```

Expected: PASS；结构测试确认不存在从 Worker import 入口直调 `importEventsToD1()` 的路径。

- [ ] **Step 8: Commit**

```bash
git add frontend/cloudflare/workers/lib/durable-import.ts \
  frontend/cloudflare/workers/lib/router.ts \
  frontend/cloudflare/workers/index.ts \
  frontend/cloudflare/workers/api/webhook.ts \
  frontend/cloudflare/workers/lib/container-import.ts \
  frontend/cloudflare/workers/lib/contracts.ts \
  frontend/cloudflare/workers/api/health.ts \
  frontend/cloudflare/workers/lib/durable-artifact.ts \
  frontend/cloudflare/tests/durable-projection-import.test.mts \
  frontend/cloudflare/tests/api-durable-import.test.mts \
  frontend/cloudflare/tests/scheduled-durable-import.test.mts \
  frontend/cloudflare/tests/health.test.mts \
  frontend/cloudflare/tests/durable-artifact.test.mts \
  tests/unit/test_cloudflare_native_config.py
git commit -m "feat(cloudflare): unify durable projection imports"
```

---

### Task 5: Restore and deploy integrity contracts

**Files:**
- Modify: `tools/cloudflare_restore_drill.py:40-560`
- Modify: `.github/workflows/cloudflare-restore-drill.yml:36-255`
- Modify: `.github/workflows/deploy.yml:188-365`
- Test: `tests/tools/test_cloudflare_restore_drill.py`
- Test: `tests/tools/test_cloudflare_restore_drill_workflow.py`
- Test: `tests/tools/test_preview_deploy_workflow.py`

**Interfaces:**
- Consumes: Phase 4 migration receipt/table/index。
- Produces: restore evidence fields `projection_finalize_receipt_orphans`、`projection_job_orphans`、`projection_artifact_orphans`、`finalize_receipt_conflicts`、`projection_guard_mismatches`、`noncommitted_artifacts`。
- Changes: Preview restore 不再接受 missing artifact 或 `status='stored'`。

- [ ] **Step 1: 写 restore fail-closed 红测**

新增测试逐项把 projection receipt 的 batch/job/artifact/checksum guard 改错，断言回执包含对应 blocker；构造同 batch 双 receipt，断言 `finalize_receipt_conflicts`；空 artifact、stored/failed artifact 均失败。

```python
assert "orphan_count_nonzero:projection_artifact_orphans" in receipt["summary"]["blockers"]
assert "orphan_count_nonzero:finalize_receipt_conflicts" in receipt["summary"]["blockers"]
assert "artifact_manifest_status_invalid:" in "\n".join(receipt["summary"]["blockers"])
```

- [ ] **Step 2: 运行红测**

Run:

```bash
python -m pytest \
  tests/tools/test_cloudflare_restore_drill.py \
  tests/tools/test_cloudflare_restore_drill_workflow.py \
  tests/tools/test_preview_deploy_workflow.py -q
```

Expected: FAIL，当前 restore 只了解 source receipt，Preview 仍设置 `allow_missing_artifact=true`，且 `stored` 被视为有效。

- [ ] **Step 3: 扩展 restore 查询和校验**

把 `import_projection_finalize_receipts` 加入 `REQUIRED_TABLES`，把 Phase 4 index 加入 `REQUIRED_INDEXES`。`RESTORE_QUERIES["orphan_counts"]` 同时统计 source/projection receipt 的 batch/job/artifact orphan、双 receipt 和 guard mismatch；`ZERO_ORPHAN_FIELDS` 包含全部新字段。新增 `artifact_status_counts` 查询统计全表 `stored`/`failed`，任一非零写入 `noncommitted_artifacts` blocker；`artifact_manifests` 选择查询改为最新一条 `status='committed'`，仅下载该真实制品做 checksum/bytes 证明。

将 artifact 状态门禁收紧为：

```python
if status != "committed":
    blockers.append(f"artifact_manifest_status_invalid:{object_key}")
```

- [ ] **Step 4: 应用 Phase 4 migration 并移除 Preview 缺失豁免**

`deploy.yml` 的 production data job 增加 Phase 4 append-only migration，Preview 仍通过 fresh `schema.sql` 初始化。`cloudflare-restore-drill.yml` 的 preview/production 均设置 `allow_missing_artifact="false"`，删除 `--allow-missing-artifact` 分支和 “Record absent preview artifact coverage” 成功路径。

- [ ] **Step 5: 运行 restore/deploy contract 测试**

Run:

```bash
python -m pytest \
  tests/tools/test_cloudflare_restore_drill.py \
  tests/tools/test_cloudflare_restore_drill_workflow.py \
  tests/tools/test_preview_deploy_workflow.py \
  tests/tools/test_cloudflare_deploy_guard.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add tools/cloudflare_restore_drill.py \
  .github/workflows/cloudflare-restore-drill.yml \
  .github/workflows/deploy.yml \
  tests/tools/test_cloudflare_restore_drill.py \
  tests/tools/test_cloudflare_restore_drill_workflow.py \
  tests/tools/test_preview_deploy_workflow.py
git commit -m "feat(cloudflare): require committed artifacts in restore drills"
```

---

### Task 6: Deterministic and secret-free Preview canary tooling

**Files:**
- Create: `tools/cloudflare_preview_canary.py`
- Create: `tests/tools/test_cloudflare_preview_canary.py`

**Interfaces:**
- Produces CLI: `payload`、`evidence-sql`、`receipt`。
- Produces: deterministic synthetic event `` `preview-artifact-canary-${commit.slice(0, 12)}` ``。
- Produces: sanitized receipt containing only identity、key、SHA-256、bytes、status、counts。

- [ ] **Step 1: 写纯函数和 CLI 红测**

测试 payload：

```python
payload = build_canary_payload(
    commit="a" * 40,
    commit_time="2026-08-02T03:00:00+00:00",
)
assert payload.idempotency_key == f"preview-artifact-canary:{'a' * 40}"
assert payload.events[0]["event_id"] == f"preview-artifact-canary-{'a' * 12}"
assert payload.events[0]["url"].startswith("https://example.test/")
```

测试 receipt：输入首次/重放响应、Wrangler D1 JSON 和已下载 R2 文件；断言 batch/job/artifact/projection receipt/event count 都为 1，SHA/bytes/status 匹配，且输出 JSON 不包含 `CF-Access-Client-Secret`、JWT、header 或请求正文。

- [ ] **Step 2: 运行红测**

Run:

```bash
python -m pytest tests/tools/test_cloudflare_preview_canary.py -q
```

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现 fail-closed canary helper**

定义：

```python
@dataclass(frozen=True)
class PreviewCanaryPayload:
    commit: str
    commit_time: str
    event_id: str
    idempotency_key: str
    events: list[dict[str, Any]]

def build_canary_payload(*, commit: str, commit_time: str) -> PreviewCanaryPayload: ...
def build_evidence_sql(*, batch_id: str, job_id: str, artifact_id: str) -> str: ...
def build_canary_receipt(
    *, first_response: Mapping[str, Any], replay_response: Mapping[str, Any],
    d1_rows: list[dict[str, Any]], artifact_path: Path,
) -> dict[str, Any]: ...
```

所有 ID 必须通过前缀和 `[0-9a-f]{64}` 校验后才进入 SQL；API URL 必须是 canonical HTTPS `news-sentry-api-preview.xuyu.workers.dev` origin。receipt 只保留 allowlist 字段，不接受任意 headers/details passthrough。

- [ ] **Step 4: 运行 helper 测试和安全扫描**

Run:

```bash
python -m pytest tests/tools/test_cloudflare_preview_canary.py -q
python tools/scan_sensitive_data.py
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tools/cloudflare_preview_canary.py tests/tools/test_cloudflare_preview_canary.py
git commit -m "feat(cloudflare): add deterministic preview artifact canary"
```

---

### Task 7: Preview Access variables, authenticated canary, and D1/R2 cross-check workflow

**Files:**
- Modify: `.github/workflows/deploy.yml:547-927`
- Modify: `frontend/cloudflare/wrangler.toml:89-124`
- Modify: `tests/tools/test_preview_deploy_workflow.py`
- Modify: `tests/unit/test_cloudflare_native_config.py`

**Interfaces:**
- Consumes GitHub `preview` Environment Variables: `CF_ACCESS_TEAM_DOMAIN`、`CF_ACCESS_AUD`、`CF_ACCESS_SERVICE_TOKEN_IDS`。
- Consumes GitHub `preview` Environment Secrets: `CF_ACCESS_CLIENT_ID`、`CF_ACCESS_CLIENT_SECRET`。
- Produces artifact: `news-sentry-preview-artifact-canary-receipt`，仅包含脱敏 JSON。

- [ ] **Step 1: 写 workflow secret-boundary 红测**

锁定：

```python
assert "environment: preview" in verify_preview_job
assert "CF_ACCESS_CLIENT_ID: ${{ secrets.CF_ACCESS_CLIENT_ID }}" in verify_preview_job
assert "CF_ACCESS_CLIENT_SECRET: ${{ secrets.CF_ACCESS_CLIENT_SECRET }}" in verify_preview_job
assert '--var "CF_ACCESS_TEAM_DOMAIN:${CF_ACCESS_TEAM_DOMAIN}"' in preview_worker_job
assert '--var "CF_ACCESS_AUD:${CF_ACCESS_AUD}"' in preview_worker_job
assert '--var "CF_ACCESS_SERVICE_TOKEN_IDS:${CF_ACCESS_SERVICE_TOKEN_IDS}"' in preview_worker_job
assert "news-sentry-artifacts-preview" in verify_preview_job
assert "ns-db-preview" in verify_preview_job
assert "news-sentry-artifacts --remote" not in verify_preview_job
assert "ns-db --remote" not in verify_preview_job
```

还要断言 Client Secret 不在 `wrangler.toml`、deploy `--var`、上传 artifact path 或任何 `echo`/`set -x`。

- [ ] **Step 2: 运行 workflow 红测**

Run:

```bash
python -m pytest \
  tests/tools/test_preview_deploy_workflow.py \
  tests/unit/test_cloudflare_native_config.py -q
```

Expected: FAIL，Preview Worker 尚未注入 Access vars，verify-preview 尚未绑定 environment/secrets/canary。

- [ ] **Step 3: 注入 Preview 独立 Access 非秘密变量**

Preview deploy step 对三个变量执行 `: "${VAR:?required}"`，再通过 `wrangler deploy --var` 注入。`CF_ACCESS_CLIENT_SECRET` 绝不传给 Worker。保留 `containers=[]`、`crons=[]`、空 queue bindings。

- [ ] **Step 4: 添加匿名 403、机器首次写入和幂等重放**

`verify-preview` 增加 `environment: preview`。执行顺序：

1. helper 依据 `GITHUB_SHA` 和 `git show -s --format=%cI` 生成 `/tmp/preview-canary.json`。
2. 不带 token POST 正常 import 端点，严格断言 403。
3. 携带 `CF-Access-Client-Id`、`CF-Access-Client-Secret` 和 `Idempotency-Key` POST 两次；两次均必须 200，第二次 `replayed=true`。
4. 从首次响应生成只读 SQL，对 `ns-db-preview` 查询 batch/job/artifact/projection receipt/event count。
5. 从响应中的 content-addressed key 对 `news-sentry-artifacts-preview` 执行 R2 GET。
6. helper 交叉校验并写 `/tmp/news-sentry-preview-artifact-canary-receipt.json`。
7. 只上传该 receipt；不上传 request、response headers、JWT 或原始正文。

- [ ] **Step 5: 运行 workflow/config 测试**

Run:

```bash
python -m pytest \
  tests/tools/test_preview_deploy_workflow.py \
  tests/unit/test_cloudflare_native_config.py \
  tests/tools/test_cloudflare_preview_canary.py -q
python tools/scan_sensitive_data.py
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/deploy.yml frontend/cloudflare/wrangler.toml \
  tests/tools/test_preview_deploy_workflow.py \
  tests/unit/test_cloudflare_native_config.py
git commit -m "ci(cloudflare): prove durable imports in preview"
```

---

### Task 8: Documentation, complete local verification, and final implementation commit

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-cloudflare-durable-import-and-preview-canary-design.md`
- Modify: `docs/status.md`
- Modify: `docs/deployment/cloudflare-phase2-migration-runbook.md`
- Modify: `docs/deployment/cloudflare-native-vps-removal.md`

**Interfaces:**
- Produces: stable status links and exact operator procedure for Phase 4 migration/canary/restore。
- Does not claim: Preview or production success before remote receipts exist。

- [ ] **Step 1: 更新文档状态和运行手册**

设计规格状态改为“实施完成，待 Preview 远端验证”仅在 Tasks 1-7 全绿后执行。`docs/status.md` 记录当前 branch/SHA、生产 stale 事实、Preview 待验证项，不复制会漂移的运行计数到结构文档。

运行手册明确：Phase 4 为 append-only；Preview secret/var 名称；匿名 403/机器 200；R2/D1 cross-check；restore drill；生产停止线。

- [ ] **Step 2: 运行完整本地验证**

Run:

```bash
cd frontend/cloudflare
npm ci
npm test
npm run types
node_modules/.bin/wrangler deploy --env="" --dry-run \
  --outdir /tmp/ns-worker-durable-import-dry-run --containers-rollout none
cd ../..
python -m ruff check
python -m mypy src/news_sentry/ --ignore-missing-imports
python -m pytest tests/ -q --tb=short --timeout=300 --durations=25
python tools/check_publication_hygiene.py
python tools/scan_sensitive_data.py
python tools/check_no_hardcoded_target.py
git diff --check
```

Expected: 全部 PASS；Wrangler dry-run bundle 成功；敏感数据扫描为零发现。

- [ ] **Step 3: 执行静态入口审计**

Run:

```bash
rg -n "importEventsToD1\(|markImportArtifactCommitted\(" \
  frontend/cloudflare/workers/api \
  frontend/cloudflare/workers/lib/container-import.ts
rg -n "POST.*events/import|handleImport" frontend/cloudflare/workers
```

Expected: API/Container 正常入口不存在直接 D1 importer 或独立 manifest commit；`handleImport` 只委托 `executeDurableProjectionImport()`。

- [ ] **Step 4: Commit 文档和验证状态**

```bash
git add docs/superpowers/specs/2026-08-02-cloudflare-durable-import-and-preview-canary-design.md \
  docs/status.md \
  docs/deployment/cloudflare-phase2-migration-runbook.md \
  docs/deployment/cloudflare-native-vps-removal.md
git commit -m "docs(cloudflare): document durable import operations"
```

---

### Task 9: Exact-SHA Preview deploy, real artifact, and isolated restore

**Files:**
- No repository file changes expected.
- Remote evidence: GitHub Actions deploy receipt, Preview canary receipt, restore receipt.

**Interfaces:**
- Consumes: exact branch SHA and GitHub `preview` Environment Access vars/secrets。
- Produces: Preview Worker version、anonymous 403、machine 200、idempotent replay、D1/R2 cross-check、isolated restore receipt。

- [ ] **Step 1: 验证或一次性建立 Preview Access 外部配置**

Cloudflare API token 必须同时具有 [`Access: Service Tokens Write`](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/) 和 [`Access: Apps and Policies Write`](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/common-policies/)；两种权限均保持 account scope。先只读检查 GitHub Environment 和 Cloudflare 资源：

Run:

```bash
gh variable list --env preview
gh secret list --env preview

: "${CLOUDFLARE_ACCOUNT_ID:?required for Access resource inspection}"
: "${CLOUDFLARE_API_TOKEN:?requires Access read/write permissions}"
access_api="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/access"
curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "${access_api}/apps" \
  | jq -e '.success == true and ([.result[] | select(.type == "self_hosted" and .domain == "news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import")] | length) <= 1'
curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "${access_api}/service_tokens" \
  | jq -e '.success == true'
```

Expected: 至多一个 self-hosted application 精确覆盖 `news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import`，不能覆盖父路径或通配路径。若三个 variables、两个 secrets、精确应用和该应用的 Preview 专用 Service Auth policy 均存在，保持资源不变，进入 Step 2；真正的 secret 有效性由 Step 3 的 authenticated canary 证明。

任何一项缺失，或后续 canary 证明现有 secret 已失效时，运行下面的一次性轮换块。它创建新的 Preview 专用 Service Token；复用现有精确应用或创建新应用；添加只含新 token 的 `non_identity` policy；把 Client Secret 直接写入 GitHub `preview` Environment。Service Token 响应中的 secret 只出现一次，因此命令使用 `umask 077` 临时文件且不把 JSON 打到 stdout：

```bash
set -euo pipefail
: "${CLOUDFLARE_ACCOUNT_ID:?required}"
: "${CLOUDFLARE_API_TOKEN:?requires Access Service Tokens Write and Apps and Policies Write}"
access_api="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/access"
preview_domain="news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import"
preview_token_name="NewsSentry Preview Import $(date -u +%Y%m%dT%H%M%SZ)"
preview_app_name="NewsSentry Preview Import"
access_tmp_dir="$(mktemp -d)"
service_response="${access_tmp_dir}/service-token.json"
apps_response="${access_tmp_dir}/apps.json"
app_response="${access_tmp_dir}/app.json"
policy_response="${access_tmp_dir}/policy.json"
umask 077
cleanup_access_tmp() {
  rm -f "${service_response}" "${apps_response}" "${app_response}" "${policy_response}"
  rmdir "${access_tmp_dir}" 2>/dev/null || true
}
trap cleanup_access_tmp EXIT HUP INT TERM

curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -cn --arg name "${preview_token_name}" '{name:$name,duration:"8760h"}')" \
  --output "${service_response}" \
  "${access_api}/service_tokens"
jq -e '.success == true and (.result.id | length > 0) and (.result.client_id | length > 0) and (.result.client_secret | length > 0)' \
  "${service_response}" >/dev/null
service_token_id="$(jq -r '.result.id' "${service_response}")"
service_client_id="$(jq -r '.result.client_id' "${service_response}")"
printf '%s' "${service_client_id}" | gh secret set CF_ACCESS_CLIENT_ID --env preview
jq -j '.result.client_secret' "${service_response}" | gh secret set CF_ACCESS_CLIENT_SECRET --env preview

curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  --output "${apps_response}" \
  "${access_api}/apps"
app_match_count="$(jq --arg domain "${preview_domain}" '[.result[] | select(.type == "self_hosted" and .domain == $domain)] | length' "${apps_response}")"
test "${app_match_count}" -le 1

if test "${app_match_count}" -eq 1; then
  app_id="$(jq -r --arg domain "${preview_domain}" '.result[] | select(.type == "self_hosted" and .domain == $domain) | .id' "${apps_response}")"
  app_aud="$(jq -r --arg domain "${preview_domain}" '.result[] | select(.type == "self_hosted" and .domain == $domain) | .aud' "${apps_response}")"
else
  curl --fail-with-body --silent --show-error \
    --request POST \
    --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    --header "Content-Type: application/json" \
    --data "$(jq -cn \
      --arg name "${preview_app_name}" \
      --arg domain "${preview_domain}" \
      '{name:$name,domain:$domain,type:"self_hosted",session_duration:"24h",app_launcher_visible:false}')" \
    --output "${app_response}" \
    "${access_api}/apps"
  jq -e '.success == true and (.result.id | length > 0) and (.result.aud | length > 0)' \
    "${app_response}" >/dev/null
  app_id="$(jq -r '.result.id' "${app_response}")"
  app_aud="$(jq -r '.result.aud' "${app_response}")"
fi
test -n "${app_id}"
test -n "${app_aud}"

curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(jq -cn \
    --arg token_id "${service_token_id}" \
    '{name:"NewsSentry Preview Import Service Auth",precedence:1,decision:"non_identity",include:[{service_token:{token_id:$token_id}}]}')" \
  --output "${policy_response}" \
  "${access_api}/apps/${app_id}/policies"
jq -e '.success == true and .result.decision == "non_identity"' "${policy_response}" >/dev/null

team_domain="$(gh variable list --env production --json name,value \
  --jq '.[] | select(.name == "CF_ACCESS_TEAM_DOMAIN") | .value')"
test -n "${team_domain}"
gh variable set CF_ACCESS_TEAM_DOMAIN --env preview --body "${team_domain}"
gh variable set CF_ACCESS_AUD --env preview --body "${app_aud}"
gh variable set CF_ACCESS_SERVICE_TOKEN_IDS --env preview --body "${service_client_id}"

cleanup_access_tmp
trap - EXIT HUP INT TERM
unset service_client_id service_token_id app_id app_aud

gh variable list --env preview
gh secret list --env preview
```

Expected: variables 包含 `CF_ACCESS_TEAM_DOMAIN`、该 Preview 应用独有的 `CF_ACCESS_AUD`、新 token Client ID 形式的 `CF_ACCESS_SERVICE_TOKEN_IDS`；secrets 包含 `CF_ACCESS_CLIENT_ID`、`CF_ACCESS_CLIENT_SECRET`。应用 policy 的 `decision` 为 `non_identity`（Dashboard 中的 Service Auth），`include` 仅含本次新建 Service Token。旧 Preview policy/token 暂不删除；必须等 Step 3 authenticated canary 与 D1/R2 交叉验证成功后，再用资源 ID 精确撤销，避免轮换窗口中断。

- [ ] **Step 2: 推送分支并确认远端 SHA**

Run:

```bash
git push origin dev-xu/fix/cloudflare-persistent-runtime
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git ls-remote origin refs/heads/dev-xu/fix/cloudflare-persistent-runtime | cut -f1)"
test "${local_sha}" = "${remote_sha}"
```

Expected: 两个完整 SHA 相同。

- [ ] **Step 3: 对精确分支 SHA dispatch Preview deploy 并等待终态**

Run:

```bash
gh workflow run deploy.yml \
  --ref dev-xu/fix/cloudflare-persistent-runtime \
  -f environment=preview
run_id="$(gh run list --workflow deploy.yml \
  --branch dev-xu/fix/cloudflare-persistent-runtime \
  --limit 1 --json databaseId --jq '.[0].databaseId')"
test -n "${run_id}"
gh run watch "${run_id}" --exit-status
```

Expected: deploy、public verification、anonymous 403、机器首次导入、幂等重放、D1/R2 cross-check 全部成功；下载的 canary receipt 不含秘密。

- [ ] **Step 4: 运行真实 Preview restore drill**

Run:

```bash
sha="$(git rev-parse HEAD)"
gh workflow run cloudflare-restore-drill.yml \
  --ref dev-xu/fix/cloudflare-persistent-runtime \
  -f environment=preview \
  -f expected_commit="${sha}"
restore_run_id="$(gh run list --workflow cloudflare-restore-drill.yml \
  --branch dev-xu/fix/cloudflare-persistent-runtime \
  --limit 1 --json databaseId --jq '.[0].databaseId')"
test -n "${restore_run_id}"
gh run watch "${restore_run_id}" --exit-status
```

Expected: artifact coverage 可用且为 committed，SHA-256/bytes 匹配，两类 receipt 无 orphan/conflict，隔离 D1 删除后确认为 absent。

- [ ] **Step 5: canary 成功后清理 Preview 轮换残留**

仅当 Step 3 和 Step 4 均通过后执行。命令只匹配精确 Preview 应用、规范 policy 名和 `NewsSentry Preview Import ` token 名前缀；删除 token 前遍历所有 Access 应用，引用数非零即 fail-closed：

```bash
set -euo pipefail
: "${CLOUDFLARE_ACCOUNT_ID:?required}"
: "${CLOUDFLARE_API_TOKEN:?requires Access Service Tokens Write and Apps and Policies Write}"
access_api="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/access"
preview_domain="news-sentry-api-preview.xuyu.workers.dev/api/v1/events/import"
current_client_id="$(gh variable list --env preview --json name,value \
  --jq '.[] | select(.name == "CF_ACCESS_SERVICE_TOKEN_IDS") | .value')"
test -n "${current_client_id}"

apps_json="$(curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "${access_api}/apps")"
app_id="$(jq -r --arg domain "${preview_domain}" \
  '[.result[] | select(.type == "self_hosted" and .domain == $domain)] | if length == 1 then .[0].id else empty end' \
  <<<"${apps_json}")"
test -n "${app_id}"

tokens_json="$(curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "${access_api}/service_tokens")"
current_token_id="$(jq -r --arg client_id "${current_client_id}" \
  '[.result[] | select(.client_id == $client_id)] | if length == 1 then .[0].id else empty end' \
  <<<"${tokens_json}")"
test -n "${current_token_id}"

policies_json="$(curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "${access_api}/apps/${app_id}/policies")"
jq -r --arg current "${current_token_id}" '
  .result[]
  | select(.name == "NewsSentry Preview Import Service Auth" and .decision == "non_identity")
  | select(any(.include[]?; .service_token.token_id? != null and .service_token.token_id != $current))
  | .id
' <<<"${policies_json}" | while IFS= read -r stale_policy_id; do
  test -n "${stale_policy_id}"
  curl --fail-with-body --silent --show-error \
    --request DELETE \
    --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    "${access_api}/apps/${app_id}/policies/${stale_policy_id}" \
    | jq -e '.success == true' >/dev/null
done

jq -r --arg current "${current_token_id}" '
  .result[]
  | select((.name | startswith("NewsSentry Preview Import ")) and .id != $current)
  | .id
' <<<"${tokens_json}" | while IFS= read -r stale_token_id; do
  test -n "${stale_token_id}"
  reference_count=0
  while IFS= read -r candidate_app_id; do
    candidate_policies="$(curl --fail-with-body --silent --show-error \
      --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
      "${access_api}/apps/${candidate_app_id}/policies")"
    candidate_count="$(jq --arg token_id "${stale_token_id}" \
      '[.result[].include[]? | select(.service_token.token_id? == $token_id)] | length' \
      <<<"${candidate_policies}")"
    reference_count="$((reference_count + candidate_count))"
  done < <(jq -r '.result[].id' <<<"${apps_json}")
  test "${reference_count}" -eq 0
  curl --fail-with-body --silent --show-error \
    --request DELETE \
    --header "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    "${access_api}/service_tokens/${stale_token_id}" \
    | jq -e '.success == true' >/dev/null
done
```

Expected: 精确 Preview 应用只保留当前 Client ID 对应的 canonical Service Auth policy；旧 Preview token 仅在全账户引用数为 0 时撤销。production 应用、policy、token 均不匹配命令的 domain/name/id 三重边界。

- [ ] **Step 6: 更新 PR #50 远端证据，不推广生产**

在草案 PR 中记录 exact SHA、deploy run、Worker version、canary artifact key/SHA/bytes、restore run 和已知 Node 20 warning。保持 Draft，不 merge、不 dispatch production。

---

## Self-Review Record

- Spec coverage：目标 1-7 分别由 Tasks 2-7 实现；Access、幂等、两类 finalize、真实 artifact、restore、秘密边界和 production stop 均有对应任务与测试。
- Placeholder scan：所有代码步骤、命令、接口、路径和运行时取值方式均已明确；远端 run id 由相邻命令读取并立即校验非空。
- Type consistency：统一使用 `AccessPrincipal`、`ImportFinalizeStrategy`、`DurableProjectionImportResult`、`requestIdempotencyKeyHash`；数据库列统一为 `request_idempotency_key_hash`。
- Scope split：本计划只完成数据面和 Preview 真制品证明。生产持续采集切换、72 小时 canary、7 天 SLO、最终生产深扫和发布必须在本计划远端通过后建立独立实施计划；不能以 Preview 成功宣称总目标完成。
