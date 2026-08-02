# News Sentry 当前状态

> 更新时间：2026-08-02T10:30:20+08:00
> 状态口径：本文件只记录会变化的运行态事实；架构和字段契约仍以 `docs/architecture.md` 与 `docs/contracts-canonical.md` 为准。
> 完整证据：[2026-08-01 项目健康、安全与低成本全球化审计](./audits/2026-08-01-project-health-security-cost-audit.md)

## 结论

当前综合健康分为 **58/100**：公开网站和 API 可服务，工程测试基线较强，但持续采集、数据新鲜度、评分一致性、远端状态证明和若干安全边界尚未达到可持续生产运营标准。

2026-08-02 Phase 2 Task 4 与隔离 Preview 已完成一次远端闭环：GitHub run `30721353606` 在 commit `4f90cda26fe05c61b2ea46605d2d5e3f6e0208da` 上成功创建/更新 `news-sentry-api-preview`、`ns-db-preview` 与 Preview Pages，并实际执行 Preview 验证。`live`、`ready`、`health` 均返回 `200/ok`，响应正文与 `x-news-sentry-deploy-commit` 对齐同一 commit；D1 schema/seed、Pages 到 Preview API 的构建绑定、精确 CORS、CSP 和快照命中均有 artifact 回执。候选分支同时加入每 6 小时运行的无密钥公开面健康探针，将 Pages、Worker、D1 数据新鲜度和部署 commit 分开验证并保留 14 天 JSON 回执。生产仍未更新，也没有 72 小时 canary 或 7 天 SLO 证据，因此综合分仍为 **58/100**。

同日第二次隔离部署 run `30727960018` 在 commit `2bfe26dd1f71bd510ab45826b08659f6506a8ba2` 上完成全量 CI、Preview R2 bucket identity、D1 schema、Worker、Pages 和最终验证。`live`、`ready`、`health` 现场复核均为 `200/ok`，`artifacts_configured=true`，部署 header 对齐该 commit，Worker version 为 `ba19fdc0-95f2-4f67-b15a-ba7758e154ff`，Pages immutable URL 为 `https://469e4bd4.news-sentry.pages.dev`。这证明 R2 binding 与部署门禁可用，仍不证明真实导入对象写入或生产恢复。

同日 durable import + Preview canary 工作的 Tasks 1-7 已在隔离 worktree 本地实现并完成 scoped review，候选 HEAD 为 `119b3d0ef7912cd2a30ea2941caa683475a3dcc5`。本地代码现在要求 API/Container 正常导入走 R2-first durable import，并为 projection-only finalize 使用 append-only Phase 4 schema；Preview workflow 已接入匿名写 403、机器 Service Token 首次 200、幂等重放、D1/R2 交叉校验和 committed artifact restore 的步骤。Task 9 尚未执行精确 SHA 远端 Preview deploy/canary/restore，因此这些仍是待取得的远端回执，不得写成 Preview 已证明事实。

最重要的事实不是“网站是否返回 200”，而是：

- 生产健康端点返回 `200 / status=ok`，但最新采集时间停在 `2026-07-23T07:52:23.678529Z`，审计时已经约 9 天未更新。
- 最近 4 次每周 Source Health Audit 全部失败；最新一次 1,803 条引用中仅 1,397 条为 `ok`，健康率 77.48%。
- 生产性能门禁失败，多个热缓存接口的 warm TTFB 中位数或 p95 超过 900/1200 ms 阈值。
- 公开数据中存在一条发布时间为 `2028-01-01` 的未来记录，会污染“最新公开时间”和新鲜度判断。
- 评分契约完整，但生产样本存在高分饱和、Breaking 字段缺失、分值与标签不一致。
- 本地 Worker 已实现 Cloudflare Access JWT 的签名、issuer、audience、exp、nbf 与 JWKS 域名验证；生产仍是旧 commit，当前线上伪造 header 探测为 403，但新控制尚未取得远端部署回执。
- 隔离 Preview 已证明新 Worker/D1/Pages 公开链路可用，但该证明不等于生产恢复，也不覆盖 Queue、Cron、Container 或 Durable Object。

## 基线

| 项目 | 当前证据 |
|---|---|
| 生产已验证分支 | `main@83efaaa74d6c4c1ba0e4a944e7fd1ceb29cd8299` |
| 整改候选 | `dev-xu/fix/cloudflare-persistent-runtime`，Draft PR [#50](https://github.com/XucroYuri/NewsSentry/pull/50) 当前 `CLEAN`，最近三项 CI 均成功 |
| Release 距离 | `v2.0.0-rc3-198-g83efaaa`，HEAD 不是已打 tag 的 release |
| Targets | 配置 82；生产 regions 端点返回 82 |
| Sources | 1,128 个 YAML 文件、1,127 个 `source_id`；远端审计展开为 1,803 条 target-source 引用 |
| Python tests | 远端全量 CI 通过、覆盖率 85%；本轮 Cloudflare/restore 相关 100 项通过 |
| Python quality | ruff 通过；CI 等价 `mypy --ignore-missing-imports` 对 142 个源文件通过 |
| Public frontend | 139 tests、typecheck、build 全部通过 |
| Admin frontend | 68 tests、typecheck、build 全部通过 |
| SEO/GEO | 线上 22/22 通过 |
| 生产 Deploy | 最新 main run `28563362256` 成功，时间 2026-07-02 |
| Preview | 隔离 run `30727960018` 成功；Worker version `ba19fdc0-95f2-4f67-b15a-ba7758e154ff`；Pages immutable URL `https://469e4bd4.news-sentry.pages.dev` |
| 未合并工作 | Draft PR #50 仍未审批/合并；本地有用户已有未跟踪 latent-value 文件，本次未改动 |

## 本地改造进度（尚未代表生产）

| 项目 | 本地状态 | 远端状态 |
|---|---|---|
| Phase 0/1 持久运行基线 | 已提交到 `dev-xu/fix/cloudflare-persistent-runtime` | 隔离 Preview 已证明，生产未部署 |
| Phase 2 Queue shadow 与 DLQ replay | 已提交，含 scoped review/fix 记录 | Preview 公开面不证明 Queue/Cron/Container |
| Phase 2 Task 4 preview-safe preflight/receipt | 实现与测试完成 | run `30721353606` 的 preflight、D1 schema/seed、Worker/Pages deploy 与 verify 全部成功 |
| 隔离 Preview Worker/D1 | config、guard、seed、receipt、Pages/API 绑定和质量门禁均完成 | `news-sentry-api-preview`、`ns-db-preview`、Preview Pages 已创建并验证 |
| D1/R2 持久化边界 | R2 不可变导入正文、D1 manifest、围栏式 finalize 与失败重放已完成 | run `30727960018` 已证明 Preview R2 bucket/binding/ready 门禁；尚无真实导入对象回执 |
| Durable import + Preview canary | Tasks 1-7 本地实现和审查完成；API/Container 委托统一 durable projection import；Phase 4 projection receipt 是 append-only schema | Task 9 尚未执行；仍待精确 SHA Preview 匿名 403、机器 200、重放、D1/R2 cross-check 和 restore receipt |
| 隔离恢复演练 | D1 export、独立私有 R2 往返校验、一次性 D1 import、schema/row/orphan/snapshot 校验和强制清理 workflow 已完成本地测试 | Preview run `30728893550` 已证明 31,101-byte R2 往返同 SHA、隔离 import 和 `cleanup.verified_absent=true`；因 Preview migration receipt 为空及 UTF-8 byte count 漂移而 fail-closed，修复待重跑 |
| 发布治理 | `preview` 可从候选分支部署隔离面；`production` 只接受 `main`；workflow 不直接改写 `main` | Draft PR #50 `CLEAN`，但仍无审批/合并；生产 job 在 Preview run 中明确跳过 |
| 供应链 | Wrangler `4.114.0`、Miniflare `4.20260722.0`、Sharp `0.35.2`；官方 npm audit 0 | GitHub CI 与 Preview 部署均通过 |
| 健康质量门禁 | 缺失、畸形、陈旧或未来时间戳均拒绝；新增公开面运行探针和 JSON 回执 | Preview 门禁已证明；生产探针会拒绝当前 false-green 状态 |
| 安全深扫 | 旧 revision 扫描仍停在 `Preparing scan` | 旧 scanId `f7ea0ba1-a833-4239-a7dc-a189073ab1f6` 没有 discovery/finding；最终 SHA 固定后必须新建扫描 |
| 72h canary / 7d SLO | 每 6 小时探针 workflow 已纳入候选分支，回执保留 14 天 | 尚未开始积累；需合并后由 schedule 产生持续证据 |

## 综合评分

| 维度 | 分值 | 权重 | 当前判断 |
|---|---:|---:|---|
| 公开面可用性 | 82 | 10% | 核心公开面 200、受保护面 403、SEO/GEO 全绿 |
| 数据新鲜度 | 25 | 15% | 采集停滞约 9 天，且未来时间戳掩盖真实陈旧度 |
| 信源连续性 | 60 | 10% | 77.48% ok，连续 4 周审计失败 |
| 评分完整性 | 52 | 12% | 契约强，但线上饱和、回退、缺字段和标签漂移明显 |
| 软件质量 | 86 | 10% | 测试/覆盖率/前端门禁强，仍有线程清理和本地门禁一致性问题 |
| 安全控制 | 58 | 15% | 未发现已确认 RCE/SQL 注入；存在鉴权、SSRF、路径、URL、提示词和供应链缺口 |
| 部署治理 | 60 | 8% | main 部署有回执，preview 分叉，Cloudflare 状态和 live commit 不能闭环证明 |
| 可观测与恢复 | 45 | 8% | 有日志/审计脚本，但 health 会对陈旧数据报 ok，连续失败未形成恢复闭环 |
| 全球化准备度 | 78 | 7% | 82 targets、多语言和边缘架构已成形，区域质量差异仍大 |
| 成本效率 | 55 | 5% | D1/R2/Workers 适合低成本，但当前 cron 可能让 basic Container 无法休眠 |

加权总分：`58.10`，四舍五入为 **58/100**。

## 当前 P0

1. 恢复采集并让 health 在采集超过阈值时返回 degraded，而不是继续 `status=ok`。
2. 隔离未来时间戳，修复 `latest_public_at=2028-01-01` 对新鲜度的污染。
3. 将已通过隔离 Preview 的 Access JWT 与部署回执推进到经审批的生产发布，并保留线上“伪造 email header 仍 403”回归探测。
4. 给 Breaking 数据增加 `score/version/label/confidence/dimensions` 完整性门禁和历史回填。
5. 取得正确 NewsSentry Cloudflare 账户的只读状态与费用回执；当前本机可见的 Cloudflare zone 不是本项目 zone。

## 当前阻塞与边界

- GitHub 环境凭据已能安全写入隔离 Preview；本机 Wrangler token 仍不作为 NewsSentry 生产写入凭据，生产发布尚未执行。
- `wrangler types`、`wrangler deploy --dry-run`、本地测试和 workflow 文本检查只算本地门禁，不算生产恢复。
- Durable import Task 8 只记录本地验证和文档口径；Task 9 之前不能声称 Preview 已完成匿名 403、机器 200、幂等重放、D1/R2 cross-check 或 committed artifact restore。
- Preview 只证明公开 API、D1、健康端点和 Pages/API 构建绑定；不证明 Queue、Cron、Container、Durable Object 或生产数据面。
- Python app 当前同时注册 Bearer 管理 webhook 与 HMAC webhook 的同路径路由；实际路由顺序优先 Bearer 版本。HMAC fail-closed 修复只算防御性修补，必须在契约统一后才能声称外部 webhook 已切换。
- `origin/preview` 与 `main` 已长期分叉，不作为本轮候选的合并基线。本轮先推送候选分支，通过手动隔离 Preview 取得回执，再以 PR 合入 `main`；禁止 workflow 自动改写 `main`。
- 下一次生产部署必须先产出 `/tmp/news-sentry-cloudflare-preflight.json` 与 `/tmp/news-sentry-cloudflare-deploy-receipt.json`，并把 version/deployment/D1/Queue/health receipt 对齐到同一 commit；隔离 Preview 的同类回执已由 run `30721353606` 证明。

## 状态更新规则

- 每次生产部署、采集恢复、P0 关闭或评分显著变化时更新本文件。
- 不把本地测试、GitHub workflow 成功或 preview 可访问等同于生产已持续健康。
- 易漂移的 SHA、计数、时间、阻塞项只保留在本文件和同日审计收据中。
