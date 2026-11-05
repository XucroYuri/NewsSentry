# PR #81 审查 — Magpie Access 服务令牌请求头 + preview Reader/Magpie 配置

- 模型：`remote-magpie/auto/claude-opus-4-8`
- 审查类型：只读代码审查（未改代码、未 commit/push/部署）
- 范围：`git show 9901e86`、`git show 86dd715`，以及相关文件相对 merge-base 的内容
- 行号基准：tip `17e1094` / 当前 hotfix 工作区
- 审查文件：
  - `frontend/cloudflare/workers/lib/reader-translate.ts`
  - `frontend/cloudflare/tests/reader.test.mts`
  - `frontend/cloudflare/wrangler.toml`
  - `tests/unit/test_cloudflare_native_config.py`
  - `docs/reader-v1.md`
  - 旁证：`frontend/cloudflare/workers/api/reader.ts`、`workers/lib/reader-http.ts`、`.github/workflows/deploy.yml`

---

## 重点结论（对照审查清单）

1. **完整配对时设置 Access 头 / 半 token 503**：✅ 正确。
   `reader-translate.ts:100-103` 仅当 `MAGPIE_CF_ACCESS_CLIENT_ID && MAGPIE_CF_ACCESS_CLIENT_SECRET` 两者皆真时才 `set("CF-Access-Client-Id"/"CF-Access-Client-Secret")`。半 token 由 `magpieConfig()` 的 XOR 检查拦截（`:63` `!!ID !== !!SECRET` → 抛 `503 MAGPIE_CONFIG_INVALID`）。该抛出发生在 group 循环（`:174`）与 Workers AI 兜底（`:187`）之前，故半 token 既不请求 Magpie、也不触发 AI 兜底、也不写 KV。测试 `reader.test.mts:729-752` 断言 `status=503 / code=MAGPIE_CONFIG_INVALID / calls=[] / aiCalls=0 / kv.entries.size=0`，覆盖 ID-only、secret-only、empty-ID+secret、ID+empty-secret 四种。

2. **`Authorization: Bearer` 与 Access 头并存、缺 key 安全**：✅ 正确。
   `:99` 先按 `MAGPIE_API_KEY` 设 `Authorization`，`:100-103` 再独立设 Access 头，二者互不耦合。缺 key 时不设 `Authorization`（`reader.test.mts:665` 既有用例已覆盖无 key 路径）。"configured" 用例（`:722`）同时断言 `Authorization: Bearer reader-api-key` + 两个 Access 头 + `X-News-Sentry-Cost-Policy: free-only` 共存。

3. **Access / API key 未写入 wrangler vars、只走 secret**：✅ 正确（代码层面）。
   `wrangler.toml:100-110` 的 `env.preview.vars` 不含任何 `MAGPIE_CF_ACCESS_*` / `MAGPIE_API_KEY`；`test_cloudflare_native_config.py:42-54` 以精确 dict 相等断言 vars 恰为 8 个键并显式排除三者，`:81-83` 再次复核。但请注意 MAJOR-1：secret 实际从未被部署。

4. **preview env 开关**：✅ 配置齐备。
   `wrangler.toml:105-108` 设 `READER_V1=1 / MAGPIE_FREE_ONLY=1 / MAGPIE_FREE_GROUP=group/translate-free / MAGPIE_BASE_URL=https://magpie-preview.news-sentry.com`；`:112-114` 挂独立 KV `READER_TRANSLATIONS`（id `a86dfa04...`，namespace id 非 secret，可入库）。生产顶层 `READER_V1="0"`（`:26`）、dev `READER_V1="0"`（`:150`）均保持关闭。✅

5. **测试覆盖**：✅ 基本充分。
   Access 头设置 / 半 token / 缺配置 均有覆盖（见第 1、2 点）。backend preview 断言与 wrangler 对齐：`test_cloudflare_native_config.py:42-60` 的 vars 与 kv_namespaces 精确匹配 `wrangler.toml:100-114`。见 MINOR-1 关于"empty 两项"用例的轻微冗余与 MINOR-2 关于端到端部署断言缺口。

6. **未削弱既有安全边界**：✅ 未发现削弱。
   DoH（`assertPublicReaderUrl`，非 local 分支 `reader-translate.ts:97`）、`readerUrl`/`validateExternalUrl` 出站校验（`magpieConfig:70-83`）、`MAGPIE_FREE_ONLY==="1"` 门禁（`:62`）、`redirect: "manual"`（`:105`）、group 白名单正则（`:67`）全部保留。Access 头仅为新增的请求头，**不**引入按量付费路径：Workers AI 仍受 `READER_WORKERS_AI`/`READER_WORKERS_AI_FREE_ONLY` 双开关约束且 preview 未开启；`metadata.allow_paid_fallback:false` 保留。

---

## BLOCKER

无。

---

## MAJOR

### MAJOR-1 — `.github/workflows/deploy.yml`（preview 部署段，约 :900-918）：Magpie Access/API 密钥无任何部署路径，本 PR 新增能力在 preview 实际不可用
PR 标题与 `docs/reader-v1.md:176-177` 宣称"支持 preview Access service token"，`wrangler.toml:109` 注释也写明
`Access service token: MAGPIE_CF_ACCESS_CLIENT_ID/SECRET via wrangler secret (preview Worker)`。
但全仓 `.github/workflows/` 中**不存在任何** `MAGPIE_*` 引用，deploy.yml 中**不存在任何** `wrangler secret put`/`secret bulk` 步骤（已 grep 确认）。
`deploy.yml:1292-1367` 出现的 `CF_ACCESS_CLIENT_ID/SECRET` 是部署 canary 调用 Worker `/events/import` 的**入站** Access 服务令牌，与 Magpie **出站** 令牌无关。
后果：preview 部署后 `MAGPIE_CF_ACCESS_CLIENT_ID/SECRET` 与 `MAGPIE_API_KEY` 恒为 undefined。
- 若 `magpie-preview.news-sentry.com` 由 Cloudflare Access 保护（注释语气暗示如此），则每次翻译请求将无凭据到达 → 403 → `MAGPIE_UNAVAILABLE` 503，翻译端点在 preview 事实上不可用；
- 代码本身安全（无凭据即不发 Access 头），故非安全漏洞，但该 PR 的核心交付（"接通 preview 免费翻译"）未落地，属功能/运维缺口。
建议：在 deploy.yml 的 "Deploy Cloudflare preview Worker" 步骤前，用 `echo "$MAGPIE_CF_ACCESS_CLIENT_ID" | wrangler secret put MAGPIE_CF_ACCESS_CLIENT_ID --env preview`（ID/SECRET/API_KEY 三者，取自 GitHub preview Environment secrets）补齐 secret 注入；或在 PR 描述中明确"secret 由运维手动 `wrangler secret put`，CI 不负责"，并在 `docs/reader-v1.md` 的 Magpie 接线段补一行手动步骤，消除 wrangler.toml:109 注释与现实的分歧。

---

## MINOR

### MINOR-1 — `frontend/cloudflare/tests/reader.test.mts:721-724`：第一组"empty"用例与半 token"empty-only"组存在断言语义重叠，可更锐利
第一组（Access 头正向设置）的 `["empty", { ID:"", SECRET:"" }, null, null]` 验证"双空 → 不设头且走正常 200 路径"，与半 token 组的 `empty ID`/`empty secret`（预期 503）形成对照。覆盖是正确的，但"双空"用例的价值主要在确认 `:63` XOR 对 `"" vs ""` 判为相等（不抛）。建议在双空用例补一条注释，说明它与 `absent` 的区别点正是"空串不是半 token"，便于后续维护者不误删。非功能缺陷，仅可读性。

### MINOR-2 — `tests/unit/test_cloudflare_native_config.py`：缺少"deploy.yml 为 preview 注入 Magpie secret"的契约断言
该文件已对 preview vars/kv 做精确断言（这很好），但没有任何测试校验 Magpie Access/API secret 的部署方式。若采纳 MAJOR-1 的 CI secret 注入方案，建议新增一条断言（类似 `:139-143` 对 `CF_ACCESS_*` 的做法）确认 deploy.yml 含 `wrangler secret put MAGPIE_CF_ACCESS_CLIENT_ID` 等步骤；若决定走手动注入，则该缺口可接受但应在 docs 落实。此为防回归建议，非当前代码缺陷。

### MINOR-3 — `frontend/cloudflare/wrangler.toml:112-114`：preview KV namespace id 以明文入库（符合惯例，仅提示）
`a86dfa040f0e4121b73ca670ccea633c` 是 KV namespace id（非 secret），入库符合 wrangler 惯例，与生产 `d1_databases.database_id`（`:65`）一致。无需改动，仅记录以免误判为密钥泄漏。

---

BLOCKER=0 MAJOR=1 MINOR=3
