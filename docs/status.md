# News Sentry 当前状态

> 更新时间：2026-08-02T04:41:43+08:00
> 状态口径：本文件只记录会变化的运行态事实；架构和字段契约仍以 `docs/architecture.md` 与 `docs/contracts-canonical.md` 为准。
> 完整证据：[2026-08-01 项目健康、安全与低成本全球化审计](./audits/2026-08-01-project-health-security-cost-audit.md)

## 结论

当前综合健康分为 **58/100**：公开网站和 API 可服务，工程测试基线较强，但持续采集、数据新鲜度、评分一致性、远端状态证明和若干安全边界尚未达到可持续生产运营标准。

2026-08-02 本地 Phase 2 Task 4 已进入修复闭环：新增 Cloudflare Queue/DLQ/consumer/D1 migration preflight、部署 receipt 生成器、显式 `SCHEDULER_MODE=shadow` 与 `WORKER_NATIVE_COLLECT_ENABLED=false`、Worker runtime config fail-closed、非 ASCII quarantine payload UTF-8 byte 边界测试，以及 D1 additive migration partial-apply runbook。随后补齐独立 `news-sentry-api-preview + ns-db-preview` 验证面、真实 Wrangler 结构化回执、Preview Pages 到 Preview API 的构建绑定证明、陈旧/未来时间戳 fail-closed 质量门禁，并把 Wrangler 固定到 `4.114.0`；官方 npm audit 为 0。此更新尚未部署到远端，也没有 72 小时 canary 或 7 天 SLO 证据，因此综合分不提升。

最重要的事实不是“网站是否返回 200”，而是：

- 生产健康端点返回 `200 / status=ok`，但最新采集时间停在 `2026-07-23T07:52:23.678529Z`，审计时已经约 9 天未更新。
- 最近 4 次每周 Source Health Audit 全部失败；最新一次 1,803 条引用中仅 1,397 条为 `ok`，健康率 77.48%。
- 生产性能门禁失败，多个热缓存接口的 warm TTFB 中位数或 p95 超过 900/1200 ms 阈值。
- 公开数据中存在一条发布时间为 `2028-01-01` 的未来记录，会污染“最新公开时间”和新鲜度判断。
- 评分契约完整，但生产样本存在高分饱和、Breaking 字段缺失、分值与标签不一致。
- 本地 Worker 已实现 Cloudflare Access JWT 的签名、issuer、audience、exp、nbf 与 JWKS 域名验证；生产仍是旧 commit，当前线上伪造 header 探测为 403，但新控制尚未取得远端部署回执。

## 基线

| 项目 | 当前证据 |
|---|---|
| 生产已验证分支 | `main@83efaaa74d6c4c1ba0e4a944e7fd1ceb29cd8299` |
| 本地整改分支 | `dev-xu/fix/cloudflare-persistent-runtime@19370c84`，另有本轮已验证未提交修复 |
| Release 距离 | `v2.0.0-rc3-198-g83efaaa`，HEAD 不是已打 tag 的 release |
| Targets | 配置 82；生产 regions 端点返回 82 |
| Sources | 1,128 个 YAML 文件、1,127 个 `source_id`；远端审计展开为 1,803 条 target-source 引用 |
| Python tests | 当前工作树全量通过、覆盖率 85%；本轮变更相关 88 项通过 |
| Python quality | ruff 通过；CI 等价 `mypy --ignore-missing-imports` 对 142 个源文件通过 |
| Public frontend | 139 tests、typecheck、build 全部通过 |
| Admin frontend | 68 tests、typecheck、build 全部通过 |
| SEO/GEO | 线上 22/22 通过 |
| 生产 Deploy | 最新 main run `28563362256` 成功，时间 2026-07-02 |
| Preview | 与 main 已分叉；最新 preview Deploy `27973208699` 失败 |
| 未合并工作 | Draft PR #49 仍开放；本地有用户已有未跟踪 latent-value 文件，本次未改动 |

## 本地改造进度（尚未代表生产）

| 项目 | 本地状态 | 远端状态 |
|---|---|---|
| Phase 0/1 持久运行基线 | 已提交到 `dev-xu/fix/cloudflare-persistent-runtime` | 未证明生产部署 |
| Phase 2 Queue shadow 与 DLQ replay | 已提交，含 scoped review/fix 记录 | 未证明生产部署 |
| Phase 2 Task 4 preview-safe preflight/receipt | 本地实现完成；验证见 Task4 report | 未执行远端 create/apply/upload/deploy |
| 隔离 Preview Worker/D1 | 本地 config、guard、seed、receipt、Pages/API 绑定和 dry-run 已通过 | `news-sentry-api-preview` / `ns-db-preview` 尚未由 workflow 创建或验证 |
| 发布治理 | 手动 `workflow_dispatch preview` 可从候选分支创建隔离 Preview；production 只接受 `main`；workflow 不再直接 push/fast-forward `main` | GitHub `main` 与 `preview` 当前均未启用 branch protection，候选分支尚未推送 |
| 供应链 | Wrangler `4.114.0`、Miniflare `4.20260722.0`、Sharp `0.35.2`；官方 npm audit 0 | 尚未经过远端 CI |
| 健康质量门禁 | 缺失、畸形、陈旧或未来 `latest_collected_at` 以及未来 `latest_public_at` 均拒绝 | 生产仍由旧门禁和旧 Worker 提供 false-green 200 |
| 安全深扫 | workspace 已建但 scan setup 仍未提交 | 未启动，无 scanId |
| 72h canary / 7d SLO | 未开始 | 未开始 |

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
3. 将本地 Access JWT 验证通过 Preview/生产回执落地，并保留线上“伪造 email header 仍 403”回归探测。
4. 给 Breaking 数据增加 `score/version/label/confidence/dimensions` 完整性门禁和历史回填。
5. 取得正确 NewsSentry Cloudflare 账户的只读状态与费用回执；当前本机可见的 Cloudflare zone 不是本项目 zone。

## 当前阻塞与边界

- 本机 Wrangler token 仍不可用于 NewsSentry 生产写入；本轮不执行远端 Queue create、D1 apply、Worker upload 或部署。
- `wrangler types`、`wrangler deploy --dry-run`、本地测试和 workflow 文本检查只算本地门禁，不算生产恢复。
- Preview 只证明公开 API、D1、健康端点和 Pages/API 构建绑定；不证明 Queue、Cron、Container、Durable Object 或生产数据面。
- Python app 当前同时注册 Bearer 管理 webhook 与 HMAC webhook 的同路径路由；实际路由顺序优先 Bearer 版本。HMAC fail-closed 修复只算防御性修补，必须在契约统一后才能声称外部 webhook 已切换。
- `origin/preview` 与 `main` 已长期分叉，不作为本轮候选的合并基线。本轮先推送候选分支，通过手动隔离 Preview 取得回执，再以 PR 合入 `main`；禁止 workflow 自动改写 `main`。
- 下一次真实部署必须先产出 `/tmp/news-sentry-cloudflare-preflight.json` 与 `/tmp/news-sentry-cloudflare-deploy-receipt.json`，并把 version/deployment/D1/Queue/health receipt 对齐到同一 commit。

## 状态更新规则

- 每次生产部署、采集恢复、P0 关闭或评分显著变化时更新本文件。
- 不把本地测试、GitHub workflow 成功或 preview 可访问等同于生产已持续健康。
- 易漂移的 SHA、计数、时间、阻塞项只保留在本文件和同日审计收据中。
