# News Sentry 部署上线进度报告

> 日期: 2026-06-07 | 编写: Claude Cowork 会话
> 目标: 将 News Sentry 部署到 BWH VPS，通过 Cloudflare Tunnel 对外提供 https://news-sentry.com 服务
> 权威部署手册: `docs/deployment/deploy-production.md`
> GitHub 仓库: https://github.com/XucroYuri/NewsSentry

---

## 架构概要

```
用户浏览器
  → Cloudflare DNS / TLS / WAF / Access
  → Cloudflare Tunnel (仅出站)
  → VPS 97.64.29.114 上的 cloudflared
  → 127.0.0.1:18080
  → News Sentry FastAPI + Web UI (newssentry 用户)
```

VPS 上与现有 Xray 代理服务（49 客户）完全隔离：独立用户、独立端口、venv 部署不碰 iptables。

---

## 部署流程总览

整个上线分 7 步（Step 1-7），其中 Step 1-3 为前置准备，Step 4 为 GitHub 配置，Step 5 为自动部署，Step 6-7 为 Cloudflare + 验证。当前主链路已完成，剩余事项集中在访问控制、CI 告警清理和观察期运维。

```
Step 1: Git 提交推送 .................. ✅ 已完成
Step 2: 生成部署 SSH Key .............. ✅ 已完成
Step 3: VPS 预配置 .................... ✅ 已完成
Step 4: GitHub Secrets + Environments . ✅ 已完成
Step 5: 生产部署 ...................... ✅ 已完成（直接 SSH + GitHub Actions）
Step 6: Cloudflare Tunnel / WAF 配置 .. ✅ 已完成
Step 7: 上线验证 + 共存确认 .......... ✅ 已完成
```

## 2026-06-07 Codex 直接部署记录

本次按手册架构完成了直接 SSH 部署，没有等待 GitHub Actions 首次部署链路：

- VPS 生产服务已部署到 `/opt/news-sentry/production/repo`，版本 `d991f2f`
- systemd 服务 `news-sentry` 已启用并运行，监听 `127.0.0.1:18080`
- 生产环境变量写入 `/opt/news-sentry/production/.env`，并补充 `NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR=1`
- Cloudflare Tunnel `news-sentry` 已创建，Tunnel ID `4ad9a278-f0de-4b26-bae2-82e0db21b206`
- DNS 已创建：
  - `news-sentry.com` → CNAME `4ad9a278-f0de-4b26-bae2-82e0db21b206.cfargotunnel.com`（proxied）
  - `www.news-sentry.com` → CNAME `4ad9a278-f0de-4b26-bae2-82e0db21b206.cfargotunnel.com`（proxied）
- Cloudflare TLS/HTTPS 设置已更新：SSL `strict`，Always Use HTTPS `on`，Minimum TLS `1.2`
- 管理员 `admin` 密码已重置，新凭据保存于本机 `~/.config/secrets/news-sentry-admin.env`（未写入仓库）
- 外部验证通过：
  - `https://news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `https://www.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `http://news-sentry.com` → 301 到 HTTPS
  - `/api/v1/auth/me`、`/api/v1/targets`、带 `target_id` 的 `/api/v1/events` 管理员认证访问通过
- 共存检查通过：`x-ui`、`cloudflared`、`news-sentry` 均为 active，iptables diff 为空，WG 策略路由仍在

后续未完成事项和建议解决方向见下方“未完成事项与建议解决方向”。

## 2026-06-07 Codex 自动化补齐记录

首次直接上线后，已继续补齐自动部署和基础边缘安全：

- GitHub repository secrets 已配置：`BWH_HOST`、`BWH_SSH_USER`、`BWH_SSH_PORT`、`BWH_SSH_KEY`、`GHCR_PAT`、`NEWSSENTRY_API_KEY`
- GitHub environments 已配置：
  - `production`：自定义分支策略 `main`
  - `preview`：自定义分支策略 `preview`
- 新 deploy key 已生成并安装到 BWH root `authorized_keys`，指纹 `SHA256:1AOjb/NQs93JdHkoGpSTcrB62c/7FXMZGyAuJ7O1nKQ`
- GitHub Actions Deploy run `27085251414` 已通过：
  - CI Gate：ruff、pytest、敏感数据扫描、hardcoded target scan、config schema validation 全部通过
  - Deploy production：SSH 部署、systemd restart、health check、Xray 共存检查全部通过
- 当前线上部署版本：以 VPS `/opt/news-sentry/production/.deploy-sha` 和 GitHub 最新 Deploy run 为准
- CI 修复 commit `39c59e3` 处理了两个既有测试问题：
  - trend fixture 使用固定 2026-05 日期，随当前日期滑出 `days=30` 查询窗口
  - schema migration 测试仍期待 version 9，但当前代码已包含 v10 AI enrichment tables
- Cloudflare WAF / rate limiting 已配置：
  - `http_request_firewall_managed`：执行 `Cloudflare Managed Free Ruleset`
  - `http_ratelimit`：`100 requests / 10 seconds / IP`，命中后 block 10 秒并返回 429
- 复验通过：
  - `https://news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `https://www.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `http://news-sentry.com` → 301 到 HTTPS

## 2026-06-07 Codex OpenRouter AI 能力补齐记录

本次将本地测试环境中的 OpenRouter 配置同步到 VPS，并修复了阻断真实 AI 调用的模型路由问题：

- 本地 `.env` 中的 `OPENROUTER_API_KEY` 已通过 SSH stdin 同步到 VPS `/opt/news-sentry/production/.env`，未在命令输出、文档或 git 文件中暴露明文 key
- 同步结果显示远端 key 已与本地 key 一致，`OPENROUTER_DEFAULT_MODEL` 已更新为 `qwen/qwen3.7-plus`
- 真实 OpenRouter smoke test 结果：
  - 旧模型 `deepseek/deepseek-v4-flash:free` 返回 HTTP 404：OpenRouter 当前没有可用 endpoint
  - 免费候选 `qwen/qwen3-next-80b-a3b-instruct:free` 返回上游 429：不适合作为生产默认模型
  - `qwen/qwen3.7-plus` 调用成功，返回模型 `qwen/qwen3.7-plus-20260602`
- 代码和配置已同步切换：
  - `src/news_sentry/adapters/providers/openrouter_provider.py` 默认模型改为读取 `OPENROUTER_DEFAULT_MODEL`，缺省值为 `qwen/qwen3.7-plus`
  - `config/provider/routes.yaml` 中所有 OpenRouter 路由改为 `qwen/qwen3.7-plus`
  - OpenRouter 路由的 `max_cost_usd_per_call` 改为小额预算估算，避免付费模型仍以 0 成本记账
- GitHub Actions Deploy run `27085672513` 已通过，OpenRouter 修复首次部署版本为 `a765f9d741ce4bd066e3feb7c2380137f27a5e6b`
- 后续文档同步 Deploy run `27085819518` 已通过；生产代码配置与 OpenRouter 修复版本一致
- VPS 生产 repo 复验通过：`translate.fast` 通过 `ProviderRouter` 真实调用 OpenRouter，返回模型 `qwen/qwen3.7-plus-20260602`，`fallback_used=False`，`budget_exceeded=False`

## 2026-06-08 Codex OpenRouter 零额度回退记录

全量硬化部署后复验时，远端 `/opt/news-sentry/production/.env` 中的 `OPENROUTER_API_KEY` 与本地 `.env` 的 key 哈希一致，但 `qwen/qwen3.7-plus` 当前返回 HTTP 402 `Insufficient credits`。这说明 key 已同步，但该 OpenRouter 账号当前没有可用付费额度。

- 已验证免费候选：
  - `openai/gpt-oss-20b:free` 返回 HTTP 200，正文长度 > 0，适合作为当前零额度生产默认路由
  - `liquid/lfm-2.5-1.2b-instruct:free`、`google/gemma-4-31b-it:free` 也能返回正文，但综合通用能力优先选 `openai/gpt-oss-20b:free`
  - `openrouter/free` 可返回 HTTP 200，但本次路由到 thinking 模型时正文为空，不适合作为稳定默认
  - 部分免费候选返回 429/400/402，不能作为默认
- 已将 `src/news_sentry/adapters/providers/openrouter_provider.py` 缺省模型和 `config/provider/routes.yaml` 所有 OpenRouter 路由临时切换到 `openai/gpt-oss-20b:free`
- 当前策略是“先保障 AI 链路真实可用”；账号充值或换有额度 key 后，建议再把生产路由切回更强付费模型，并恢复小额 `max_cost_usd_per_call` 估算

## 2026-06-08 Codex OpenRouter free 模型轮换 + Nvidia 兜底记录

根据成本风险复盘，AI 路由策略从“单一 OpenRouter free 默认模型”升级为“全 OpenRouter 任务 free 模型池轮换 + Nvidia 低并发免费模型兜底”：

- `config/provider/routes.yaml` 升级到 `routes_version: "1.2.0"`，所有 OpenRouter AI 任务均配置 `model_pool`
- 当前 free 模型池只包含模型名带 `:free` 的候选，默认排除 `openrouter/free` 和 thinking-only 候选，避免正文为空
- `ProviderRouter` 增加进程内轮换游标；同一 route 会在模型池内轮换，遇到空正文、HTTP 429、HTTP 402、quota/credits 错误时切换模型
- 429/402 等限流或额度错误会让对应 provider+model 进入 30 分钟冷却，降低免费模型被连续打爆的概率
- Nvidia 低并发免费模型通过现有 `anthropic` provider 适配层接入；Nvidia route 使用 `model_env_var` 优先读取环境变量，生产只需要配置运行时环境变量，不在仓库保存 token：
  - `ANTHROPIC_BASE_URL=https://integrate.api.nvidia.com`
  - `ANTHROPIC_AUTH_TOKEN=<runtime secret>`
  - 可选：`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL`
- 各任务 fallback 顺序：OpenRouter free pool → Nvidia/Anthropic-compatible route → `fallback.local`（本地规则，仅适合研判/分类兜底；翻译任务失败时不会写入空译文）

建议验收：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_provider_router.py tests/unit/test_anthropic_provider.py tests/unit/test_openrouter_provider.py tests/unit/test_provider_factory.py -q
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_ai_enrichment.py -q
PYTHONPATH=src .venv/bin/python tools/scan_sensitive_data.py
```

## 2026-06-09 Codex Phase 87 新公共门户生产灰度记录

本次将 Phase 83-86 的新公共门户从本地完成态推进到生产灰度。灰度策略保持低风险软切换：`/public-app/` 作为新公共门户 canonical 入口，`/` 仍返回 legacy shell，旧公开 hash 路由由客户端跳转到新 app，后台 hash 路由继续由旧 shell 承载。

### Release 与 Deploy

- 发布分支：`codex/phase87-public-app-production-gray`
- 公共门户 release commit：`bffa880819735491e19ebb6f8462e8b79361fb9c`（`feat: gray release public react portal`）
- Deploy worktree 修复 commit：`6bfc1d621798d34a14006257f540139a1261d67c`
- CSP nonce 修复 commit：`2bb5a37d295f92b0b558ca0b9d161a238ce9d575`
- 公开新闻 feed 性能修复 commit：`7bf1417fe8194c4f581865698656901a8ec06122`
- 当前生产 `.deploy-sha`：`7bf1417fe8194c4f581865698656901a8ec06122`
- 当前生产 `.deploy-time`：`2026-06-09T17:23:06Z`

GitHub Actions 验证：

| 环境 | Commit | CI | Deploy | 结果 |
|---|---|---:|---:|---|
| preview | `6bfc1d6` | `27219945443` | `27219945385` | 通过 |
| preview | `2bb5a37` | `27221624549` | `27221624458` | 通过 |
| preview | `7bf1417` | `27222878246` | `27222878654` | 通过 |
| production | `6bfc1d6` | `27220357424` | `27220357422` | 通过 |
| production | `2bb5a37` | `27222008811` | `27222008249` | 通过 |
| production | `7bf1417` | `27223260216` | `27223261569` | 通过 |

首个 production deploy run `27219183097` 在 `bffa880` 上失败，根因为远端部署 checkout 目录存在未清理的本地改动，导致 `git checkout -B main origin/main` 被拒绝。已在 `6bfc1d6` 中修复为部署前备份 dirty worktree 并执行受控 `reset --hard` / `clean -fd`。

### 生产 Smoke

- `https://news-sentry.com/api/v1/health` 返回 `{"status":"ok"}`
- `/public-app/` 返回 `Cache-Control: no-cache`
- `/public-app/` CSP 使用 HTTP header nonce，未恢复 `script-src 'unsafe-inline'`
- `/public-app/assets/*` 使用 Vite 指纹资源长期缓存
- `/api/v1/public/news?page_size=1` 返回真实公开新闻，`total=340`，`pollAfterMs=60000`
- VPS `systemctl is-active news-sentry cloudflared x-ui` 均为 `active`
- `journalctl -u news-sentry --since "30 minutes ago" -p err` 与 `journalctl -u cloudflared --since "30 minutes ago" -p err` 均无错误条目

浏览器矩阵验证：

- 截图目录：`/tmp/news-sentry-public-qa-phase87-long-2026-06-09T17-33-58-706Z`
- `https://news-sentry.com/public-app/` desktop `1440x900`：25.1 秒后渲染 20 条真实新闻，无 console/page error，无横向溢出
- `https://news-sentry.com/public-app/` mobile `390x844`：45.5 秒后渲染 20 条真实新闻，无 console/page error，无横向溢出；移动底部导航 DOM 复核为 `position: fixed`
- `https://news-sentry.com/#/news/target/italy/analysis/entities`：跳转到 `/public-app/#/analysis?target_id=italy&section=entities`
- `https://news-sentry.com/#/admin/targets`：不跳转到 `/public-app/`，未登录状态进入 legacy `/admin/login`

### 上线观察与后续建议

Phase 87 已达到“生产灰度可用”的低风险切换目标，但仍不建议立刻把 `/` 服务端入口替换为新 app。当前主要遗留风险是公开新闻首屏尾部延迟：VPS 本机查询已从约 30 秒降至约 6 秒，但生产浏览器经 Cloudflare/Tunnel 路径仍可能需要 25-45 秒才出现首批新闻。

建议下一阶段优先处理：

1. 为 `/api/v1/public/news` 增加面向公开首页的轻量 projection/cache，避免每次首屏都扫描较大事件集合。
2. 将浏览器 QA 的“15 秒内首批新闻可见”作为下一阶段硬验收；若后端暂无新闻，则必须快速返回可解释空状态。
3. 24-72 小时继续观察 health、Cloudflare Tunnel、公开新闻 API、旧公开路由跳转和后台登录入口。
4. 稳定后再评估服务端默认首页替换和旧 public Vanilla JS 清理窗口。

## 2026-06-10 Codex Phase 88 公开新闻首屏性能投影/cache 记录

本轮关闭 Phase 87 遗留的公开新闻首屏尾部延迟。核心改动是让 `GET /api/v1/public/news` 列表页从 SQLite `event_index` 优先构造读者字段，并增加进程内短 TTL projection cache；详情页 `GET /api/v1/public/news/{event_id}` 继续按需读取完整 Markdown/frontmatter，保持读者详情闭环。

### Release 与 Deploy

- 发布分支：`codex/phase88-public-feed-cache`
- 公开 feed projection/cache commit：`d737bf78413199de0d03ad63edd8d041149d5286`
- 运行目录过滤修复 commit：`ee5e092440f68ff47ed84245f3505a8eb6dd0438`
- source 配置缓存修复 commit：`a879c72d3d93e8f330aa191842db2d7beb0438ea`
- Phase 88 代码 release 验证时生产 `.deploy-sha`：`a879c72d3d93e8f330aa191842db2d7beb0438ea`

GitHub Actions 验证：

| 环境 | Commit | Scan Secrets | CI | Deploy | 结果 |
|---|---|---:|---:|---:|---|
| preview | `d737bf7` | `27242208755` | `27242208762` | `27242208764` | 通过 |
| production | `d737bf7` | `27242652292` | `27242652282` | `27242652276` | 通过，但 cold miss 仍为 14-15 秒，继续修复 |
| preview | `ee5e092` | `27243231533` | `27243231559` | `27243231558` | 通过 |
| production | `ee5e092` | `27243555617` | `27243555652` | `27243555577` | 通过，但发现 source YAML 重复读取仍导致 cold miss 约 15 秒 |
| preview | `a879c72` | `27244122210` | `27244122220` | `27244122256` | 通过 |
| production | `a879c72` | `27244379822` | `27244379854` | `27244379807` | 通过 |

已知非阻断 annotation：

- GitHub Actions Node.js 20 deprecation：仍按既有 P1 backlog 处理。
- pytest / aiosqlite `Event loop is closed` annotation：不阻断本次 Deploy，仍按既有 P1 backlog 处理。

### 性能复验

VPS production 本机，`http://127.0.0.1:18080/api/v1/public/news?featured=true&page_size=20`：

| 场景 | `X-News-Sentry-Feed-Cache` | `X-News-Sentry-Feed-Elapsed-Ms` | `curl time_total` | 结果 |
|---|---|---:|---:|---|
| 首次请求 | `miss` | `2031` | `2.085761s` | 通过 |
| 连续第二次 | `hit` | `0` | `0.010388s` | 通过 |
| 等待 16 秒后 | `miss` | `985` | `0.991486s` | 通过 |

公网 Cloudflare 路径，`https://news-sentry.com/api/v1/public/news?featured=true&page_size=20`：

- 连续请求约 `1.23-1.34s`，返回 `items=20`、`total=1822`。
- 响应头可见 `x-news-sentry-feed-cache`、`x-news-sentry-feed-elapsed-ms`、`cf-cache-status: DYNAMIC`。
- `https://news-sentry.com/api/v1/health` 返回 `{"status":"ok"}`。

生产浏览器 QA：

- 截图目录：`/tmp/news-sentry-public-qa-phase88-2026-06-10T00-25-12-366Z`
- `https://news-sentry.com/public-app/` desktop `1440x900`：`4.118s` 内出现首条新闻，无 console/page error，无横向溢出。
- `https://news-sentry.com/public-app/` mobile `390x844`：`1.940s` 内出现首条新闻，无 console/page error，无横向溢出；移动底栏 `position: fixed`，active 为“信号”。
- `https://news-sentry.com/#/news/feed` 自动跳转到 `/public-app/#/feed?channel=featured`。
- `https://news-sentry.com/#/admin/targets` 不跳转到 `/public-app/`，未登录状态进入 legacy `/admin/login`。

### 当前判断

Phase 88 已达到本轮验收：生产公网公开新闻首屏不再出现 25-45 秒尾部延迟，VPS cold miss 小于 8 秒、warm hit 小于 3 秒，浏览器 15 秒内可看到首条新闻。后续若搜索 `q` 成为高频入口，再规划 SQLite FTS 或独立 projection；本轮不引入 Redis、SSE/WebSocket 或 Cloudflare CDN API 缓存。

## 2026-06-12 Codex target/source 扩容 preview 验证记录

本轮自动化新增 `india` target，并为 `china-watch-en` 补入 `dw-en-all` 与 `aljazeera-global` 两条公开 RSS。部署链路只推进到 `preview`，未推进 `production`。

- release branch: `codex/target-source-expansion-r001-india`
- release branch head: `a1cd681`
- preview merge SHA: `cabf7de87c797bd589c2efb25dd2306c4bcb9797`
- preview Deploy run: `27382719432`
- preview CI job: `80923024126`
- preview Deploy job: `80923731265`
- preview workflow 结果: `CI Gate` 与 `Deploy preview` 全部通过
- preview 内部健康证据: `Deploy via SSH` 成功，说明远端 `127.0.0.1:18081/api/v1/health` 已在 workflow 内通过

## 2026-06-12 Codex target/source 扩容 round 3 preview 验证记录

本轮自动化新增 `vietnam` target，并为 `germany` 补入 `tagesspiegel-news` 与 `destatis-aktuell` 两条公开 RSS。同时修复了 RSSCollector 对“UTF-16 声明但无 BOM” feed 的兼容性，使 `Vietnam News` 三条英语 RSS 可以稳定采集。部署链路推进到 `preview`，未推进 `production`。

- release branch: `codex/target-source-expansion-r003-vietnam`
- release commit: `0d7888a`
- preview branch SHA: `0d7888ac4a774d6555b68b70595af76f0c0a6be6`
- preview CI workflow: `27405188785`
- preview CI job: `80992490343`
- preview Deploy workflow: `27405188794`
- preview Deploy CI Gate job: `80992490410`
- preview Deploy preview job: `80993356657`
- workflow 结果: `Scan Secrets`、独立 `CI` workflow、`Deploy` workflow 全部通过

本地与 preview 验证证据：

- 本地静态闸门：
  - `python tools/scan_sensitive_data.py` passed
  - `git diff --check` passed
  - `python tools/check_no_hardcoded_target.py` passed
  - `PYTHONPATH=src ... pytest tests/unit/test_config_schema_validation.py tests/unit/test_rss_collector.py tests/unit/test_vietnam_target_configs.py tests/unit/test_germany_target_configs.py ... tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources -q` → `475 passed`
- 本地 collect smoke：
  - `vietnam` 6/6 sources ok, `95` raw items
  - `germany` 24/24 sources ok, `184` raw items
- preview 外部健康证据：
  - `GET https://preview.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `GET https://preview.news-sentry.com/api/v1/targets` → `vietnam` 可见且 `source_count=6`，`germany` 更新为 `source_count=24`
- preview 版本对齐证据（workflow log 级）：
  - `Deploy via SSH` 日志显示 `=== Deploying NewsSentry preview (0d7888a) on port 18081 ===`
  - 远端 fetch/checkout 日志显示 `HEAD is now at 0d7888a feat: 新增越南 target 并补强德国信源`
  - workflow 执行了 `echo "${SHA}" > /opt/news-sentry/preview/.deploy-sha`

仍未满足 production 放行闸门的点：

- 当前环境仍无法通过直连 SSH 或文档中的 jump-host SSH 读取 VPS `preview/.deploy-sha` 文件本体
- 因此虽然 preview workflow、preview 外部 health 与 targets 已通过，本轮仍不推进 `main`
- VPS `.deploy-sha` 证据: 当前环境无法通过直连 SSH 或文档中的 jump-host SSH 读取，因此未完成独立复核

结论：

- preview 站已完成公网 `/health` 与 `/targets` 实证，但 `.deploy-sha` 仍缺少独立只读复核
- 因此本轮不推进 `main`，生产环境保持不变

## 2026-06-12 Codex target/source 扩容 round 4 质量闸门记录

本轮未写入新的 target/source 配置，也未触发 preview / production 部署。主要工作是基于 round 3 之后的真实 preview 状态，重新评估下一批候选与最少信源 target 的可操作性，避免在 source 验证不充分时为了轮次强行落库。

### 本轮判断

- 候选新 target：
  - `philippines`：热点充分，中菲摩擦与 Mindanao 地震后的治理/公共安全议题都在 2026-06-12 仍持续发酵；但多条候选 feed 在当前环境里出现 Cloudflare challenge、403 或长时间超时，只剩 GMA 多个 XML feed 稳定可读，暂未达到“足够独立可信来源”标准
  - `taiwan`：热点充分，6 月 10 日 HIMARS 实弹演训与 6 月 12 日半导体供应链/工资数据同时在发酵；且已通过网页实证定位到总统府、内政部、CDC、教育部、经贸主管部门等英语 RSS 入口，但当前环境仍未完成稳定直拉或 collect 级验证
- 既有 target 轮转：
  - `japan` 在 preview `/api/v1/targets` 中为 `source_count=23`，是未冷却且 preview 可见的最少信源既有 target
  - 但候选新增 feed 仍未达到可安全落库的验证标准，因此本轮只记录维护判断，不做配置改动
- 弱 target 只读复查：
  - `south-korea` 在 preview `/api/v1/targets` 中仍为 `source_count=5`，继续是最弱 target
  - 但其第 2 轮刚作为主对象处理，round 4 仍处 12 轮冷却窗口，只做状态记录

### Runtime 复核

- `GET https://preview.news-sentry.com/api/v1/health` → `{"status":"ok"}`
- `GET https://preview.news-sentry.com/api/v1/targets` 显示：
  - `japan=23`
  - `south-korea=5`
  - `india=6`
  - `vietnam=6`
  - `germany=24`
  - `france=25`
  - `china-watch-en=15`
  - `italy=66`

### 结论

- 本轮按“宁可跳过不降低 source 质量”的规则停在评估与账本更新，不触发 release branch 推送，也不触发 preview / production deploy
- 下一轮若继续推进 `taiwan` 或 `japan`，应先补足稳定的直接抓取或 collect smoke 证据，再进入正式配置修改

## 2026-06-12 Codex target/source 扩容 round 2 preview 验证记录

本轮自动化新增 `south-korea` target，并为 `france` 补入 `France 24`、`RFI`、`Le Parisien` 政经共 4 条公开 RSS。部署链路再次推进到 `preview`，仍未推进 `production`。

### Release 与验证

- release branch: `codex/target-source-expansion-r002-south-korea`
- 配置主提交: `d5eab8a` (`feat: add south korea target and expand france sources`)
- sandbox allowlist 修复提交: `ea72a6e` (`fix: allow france and south korea source hosts on cloud vps`)
- 首次 preview run: `27393147856`
  - CI job: `80954844603`
  - 结果: `pytest + coverage` 失败，根因为 `cloud-vps` allowlist 漏掉 `www.france24.com`、`feeds.leparisien.fr`、`www.rfi.fr`
- 修复后 preview run: `27393376925`
  - CI job: `80955526542`
  - Deploy job: `80955888024`
  - 结果: `CI Gate` 与 `Deploy preview` 全部通过

### 本地与公网证据

- 本地静态/配置验证通过：
  - `python tools/scan_sensitive_data.py`
  - `git diff --check`
  - `python tools/check_no_hardcoded_target.py`
  - `pytest tests/test_sandbox.py::TestCheckNetworkHost::test_cloud_vps_allows_configured_public_country_sources tests/unit/test_south_korea_target_configs.py tests/unit/test_france_target_configs.py tests/unit/test_config_schema_validation.py -q`
- collect smoke:
  - `south-korea` 5/5 sources ok，写入 175 条 raw
  - `france` 25/25 sources ok，写入 220 条 raw
- preview 外部健康证据：
  - `GET https://preview.news-sentry.com/api/v1/health` → `{"status":"ok"}`
  - `GET https://preview.news-sentry.com/api/v1/targets` → `south-korea` 可见且 `source_count=5`，`france` 更新为 `source_count=25`
- preview 内部版本证据：
  - Deploy via SSH 日志显示远端 checkout 到 `ea72a6e`
  - Post-deploy summary 记录 `Commit | ea72a6ef79f142c8ccba916f25d3fd5e29e44941`
  - workflow 脚本已执行 `echo "${SHA}" > /opt/news-sentry/preview/.deploy-sha`

### 结论

- preview 站点已完成新一轮部署，公网 `/health` 与 `/targets` 均可实证
- 但当前环境仍无法 direct SSH / jump-host 读取 VPS `preview/.deploy-sha` 文件本体，因此不把这轮视为满足 production 放行闸门
- 生产环境保持不变；下一步重点应转向补“远端版本可见性”证据链，而不是继续在同一 target 上重复扩容

## 未完成事项与建议解决方向

已完成一轮已部署站点全栈审计，独立报告见 [site-audit-20260607.md](site-audit-20260607.md)。2026-06-08 已启动并落地一轮全量硬化冲刺，脱敏整改记录见 [hardening-sprint-20260608.md](hardening-sprint-20260608.md)；后续安全、产品体验、CI/CD 和运维整改 backlog 以这两份报告中的 `NS-AUDIT-*` / security scan 编号为准。

| 优先级 | 事项 | 当前状态 / 风险 | 建议解决方向 | 验收标准 |
|--------|------|-----------------|--------------|----------|
| P0 | Cloudflare Access 访问策略 | `news-sentry.com` 已有应用内认证和 WAF，但未加 Cloudflare Access；如果 Web UI 仅面向内部编辑，公网可达会增加撞库和扫描面。 | 先确定允许登录的邮箱、邮箱域名或 IdP；在 Cloudflare Zero Trust 为 `news-sentry.com` 和 `www.news-sentry.com` 创建 Self-hosted Access application；策略初期建议只允许明确邮箱列表；保留 `/api/v1/health` 是否绕过 Access 需要单独判断：若外部监控依赖公网 health，则为 health 配置低权限监控路径或独立 monitor token。 | 未授权访问 Web UI 时先出现 Cloudflare Access；授权邮箱可登录并进入应用；`/api/v1/auth/me` 仍保留应用内认证；部署 health check 不受影响。 |
| P1 | GitHub Actions runtime 告警 | Deploy run 已通过，但 Actions 页面有 Node.js 20 deprecation annotation；未来 GitHub 运行环境升级时可能产生维护噪音。 | 统一检查 `.github/workflows/*.yml` 中 `actions/checkout@v4`、`actions/setup-python@v5` 等 action 的新版 Node 24 支持状态；有稳定新版后升级到对应 major；升级后跑 `CI` 和 `Deploy` workflow。 | Actions 页面不再出现 Node.js 20 deprecation annotation；`CI` 与 `Deploy` 均为绿色。 |
| P1 | `appleboy/ssh-action` 参数告警 | `.github/workflows/deploy.yml` 中 `script_stop: true` 被当前 `appleboy/ssh-action@v1` 标记为 unexpected input，实际已由脚本内 `set -euo pipefail` 兜底。 | 查当前 `appleboy/ssh-action` 支持的输入参数；若无等价参数，删除 `script_stop`，保留 `set -euo pipefail` 和关键命令显式失败检查；若新版 action 支持等价输入，则升级 action 并替换字段。 | Deploy run 无 `Unexpected input(s) 'script_stop'` warning；任一部署关键步骤失败时 workflow 仍会失败。 |
| P1 | pytest / aiosqlite `Event loop is closed` annotation | 当前不阻断 CI，但说明某些异步资源可能在 pytest event loop 关闭后才完成清理。长期会让 CI 告警变钝。 | 定位触发 warning 的测试和 fixture；重点检查 `AsyncStore` / `aiosqlite` 连接关闭路径，确保每个测试在 loop 关闭前 `await store.close()` 或退出 async context；必要时补充 fixture teardown 和回归测试。 | 全量 `pytest tests/ -q --tb=short --timeout=300` 无该 warning annotation；数据库相关测试重复运行稳定。 |
| P2 | 72 小时上线观察 | 当前 VPS 服务、Cloudflare Tunnel、Xray 共存均已验证，但仍缺少一段连续运行数据。 | 建议连续 72 小时每日检查一次 `systemctl status news-sentry cloudflared x-ui`、`journalctl -u news-sentry -n 100`、磁盘、内存和 Cloudflare 安全事件；观察期内暂不叠加大规模新功能发布。 | 72 小时内无异常重启、内存持续上涨、磁盘快速增长、Xray 共存异常或 Cloudflare 大量误杀。 |
| P2 | 部署凭据轮换策略 | 部署 key、GitHub Secrets、VPS `.env` 已就绪，但尚未记录周期性轮换流程。 | 建议建立轻量轮换节奏：deploy key 和 GitHub token 每 90-180 天轮换；`NEWSSENTRY_API_KEY` 在成员变更或疑似泄露时立即轮换；轮换后触发一次 Deploy workflow 并验证线上 health。 | 文档中有明确 owner、轮换周期、轮换步骤和回滚办法；旧 key 从 VPS `authorized_keys` 与 GitHub Secrets 中移除。 |

---

## 已完成项详情

### Step 1: Git 提交推送 ✅

- Commit: `d991f2f` — feat: AI enrichment, target groups, feed improvements, deployment setup
- 61 files changed, 4092 insertions(+), 363 deletions(-)
- 已推送到 `origin/main`
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) 已在运行中

### Step 2: 生成部署 SSH Key ✅

- 类型: ed25519
- 用途: GitHub Actions 通过 SSH 连接 BWH VPS
- 本机位置: `~/.ssh/news-sentry-deploy`
- 公钥已上传到 BWH `~/.ssh/authorized_keys`
- 私钥已配置到 GitHub Secret `BWH_SSH_KEY`

当前 deploy key 指纹: `SHA256:1AOjb/NQs93JdHkoGpSTcrB62c/7FXMZGyAuJ7O1nKQ`

> 私钥不写入版本控制。如果后续轮换 deploy key，需要同步更新 VPS `~/.ssh/authorized_keys`、GitHub Secret `BWH_SSH_KEY`，并触发一次 Deploy workflow 验证。

### Step 3: VPS 预配置 ✅

已在 KiwiVM Web SSH 中执行完成，以下配置已就绪:

**系统用户:**
- `newssentry` — 独立系统用户，用于运行 News Sentry 服务

**目录结构:**
```
/opt/news-sentry/production/    ← 代码 + venv（deploy 时自动创建）
/opt/news-sentry/preview/       ← preview 环境
/srv/news-sentry/production/data/ ← 运行时数据
/srv/news-sentry/preview/data/  ← preview 数据
/var/log/news-sentry/           ← 日志（systemd journal 为主）
```
所有目录 owner 为 `newssentry:newssentry`。

**Python 环境:**
- `python3-venv` 和 `python3-pip` 已安装
- venv 将由 deploy.yml 自动在首次部署时创建

---

## 已完成自动化配置详情

### Step 4: GitHub Secrets + Environments ✅

**需要访问:** https://github.com/XucroYuri/NewsSentry/settings

#### 4a. Repository Secrets

路径: `Settings → Secrets and variables → Actions → New repository secret`

| # | Secret 名称 | 值 | 状态 |
|---|-------------|-----|------|
| 1 | `BWH_HOST` | BWH VPS 主机地址 | ✅ |
| 2 | `BWH_SSH_USER` | SSH 用户 | ✅ |
| 3 | `BWH_SSH_PORT` | SSH 端口 | ✅ |
| 4 | `BWH_SSH_KEY` | GitHub Actions deploy key 私钥 | ✅ |
| 5 | `GHCR_PAT` | 当前部署用 GitHub token | ✅ |
| 6 | `NEWSSENTRY_API_KEY` | 与 VPS `.env` 同步的 API key | ✅ |

**后续轮换 GHCR PAT 的建议步骤:**
1. 打开 https://github.com/settings/personal-access-tokens/new
2. Token name: `news-sentry-deploy`
3. Expiration: 建议 90-180 天
4. Repository access: **Only select repositories** → `XucroYuri/NewsSentry`
5. Permissions: **Contents → Read**（venv 部署只需要拉取仓库）
6. Generate token → 更新 GitHub Secret `GHCR_PAT` → 手动触发一次 Deploy workflow 验证

> 注意: `OPENROUTER_API_KEY` 不需要配置为 GitHub Secret。AI provider key 通过 VPS 上的 `.env` 文件注入，不经过 CI/CD 管道。

#### 4b. GitHub Environments

路径: `Settings → Environments → New environment`

| 环境名 | Deployment branch | 其他设置 |
|--------|-------------------|---------|
| `production` | `main` | Wait timer: 0, Reviewers: 可选 |
| `preview` | `preview` | Wait timer: 0 |

#### 4c. VPS 生产环境 .env 文件

VPS 上 `/opt/news-sentry/production/.env` 已创建并投入使用。以下为字段骨架，真实密钥仅保存在 VPS `.env` 与 GitHub Secrets，不写入仓库：

```bash
cat > /opt/news-sentry/production/.env << 'EOF'
NEWSSENTRY_DEPLOYMENT_ENV=vps
NEWSSENTRY_PROFILE=cloud-vps
NEWSSENTRY_DATA_DIR=/srv/news-sentry/production/data
NEWSSENTRY_AI_BUDGET_USD=1.0
NEWSSENTRY_LOG_LEVEL=INFO
OPENROUTER_API_KEY=<见本机 .env 或 VPS /opt/news-sentry/production/.env>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_MODEL=openai/gpt-oss-20b:free
NEWSSENTRY_API_KEY=<见 VPS /opt/news-sentry/production/.env 或重新生成>
CORS_ALLOWED_ORIGINS=https://news-sentry.com,https://www.news-sentry.com
EOF
chmod 600 /opt/news-sentry/production/.env
chown newssentry:newssentry /opt/news-sentry/production/.env
```

> deploy.yml 首次部署时也会创建 .env 模板，但模板缺少 `OPENROUTER_API_KEY` 等关键配置。当前生产环境已补齐；后续如果重建 VPS，需要先恢复 `.env` 再重启服务。

### Step 5: 触发 GitHub Actions 部署 ✅

前置条件 Step 4 已完成。当前 `main` 分支 push 会自动触发 production 部署；也可在 GitHub 手动触发。

**自动触发:** 后续需要重新部署 production 时，向 `main` 推送 commit 即可触发:
```bash
# 本机终端：空提交触发 Actions
cd /Volumes/SSD/Code/09-business/news-sentry.com/NewsSentry
git commit --allow-empty -m "ci: trigger first deploy to production"
git push origin main
```

**手动触发:** 也可在 GitHub 操作:
`Actions → Deploy → Run workflow → production`

**部署流程（deploy.yml 自动执行）:**
1. CI Gate: ruff lint → pytest → security scan → schema validation
2. SSH 到 BWH → `git clone` 代码 → 创建 venv → `pip install -e ".[api]"`
3. 生成 systemd service 文件 → `systemctl restart news-sentry`
4. 健康检查: `curl http://127.0.0.1:18080/api/v1/health`（12 次重试，每次 5s）
5. 共存确认: 检查 Xray 代理服务仍在运行

**验证部署成功:**
- GitHub Actions 页面显示绿色 ✓
- VPS 上 `systemctl status news-sentry` 显示 active (running)
- `curl http://127.0.0.1:18080/api/v1/health` 返回 `{"status": "ok"}`

### Step 6: Cloudflare Tunnel 配置 ✅

> 此步需要 VPS 上 News Sentry 服务已运行（Step 5 完成）。

**操作方式:** 通过 Cloudflare Dashboard（推荐）或 VPS CLI

路径: https://dash.cloudflare.com → Zero Trust → Networks → Tunnels

1. **创建 Tunnel:**
   - 类型: Cloudflared
   - 名称: `news-sentry`
   - 复制安装命令，在 KiwiVM Web SSH 中执行（以 root 身份）

2. **配置路由:**
   - Public hostname: `news-sentry.com` → `http://localhost:18080`
   - 可选: `preview.news-sentry.com` → `http://localhost:18081`

3. **安装为系统服务:**
   ```bash
   # VPS 上执行
   cloudflared service install
   systemctl enable cloudflared
   systemctl start cloudflared
   ```

4. **安全配置（Cloudflare Dashboard）:**
   - SSL/TLS → 加密模式: Full (Strict)，最低 TLS 1.2
   - WAF → 启用 Free 规则集，速率限制 100 req/10s
   - Access → 建议初期启用，限制授权用户访问

**Cloudflare 账户信息:**
- 域名: `news-sentry.com`（已在 Cloudflare 管理）
- 本机已安装 `cloudflared` CLI 且环境变量已配置

### Step 7: 上线验证 + 共存确认 ✅

**外部验证（本机浏览器或终端）:**
```bash
curl -f https://news-sentry.com/api/v1/health
curl -s https://news-sentry.com/ | head -20
```

**功能验证清单:**
- [x] https://news-sentry.com 打开 Web UI
- [x] 登录/认证功能正常
- [x] API /api/v1/health 返回 ok
- [x] http:// 自动跳转 https://
- [x] 管理员认证访问 `/api/v1/auth/me`、`/api/v1/targets`、带 `target_id` 的 `/api/v1/events` 通过

**管理员状态:**

管理员 `admin` 已创建并完成密码重置，新凭据保存于本机 `~/.config/secrets/news-sentry-admin.env`。如果未来需要重置，可在 VPS 上执行项目提供的账号管理命令或通过受控的维护脚本处理；不要把密码写入仓库或部署文档。

**仅首次初始化时使用的历史命令:**
```bash
curl http://127.0.0.1:18080/api/v1/auth/setup-status
# 期望: {"setup_required": true}

curl -X POST http://127.0.0.1:18080/api/v1/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<设置强密码>"}'
```

**共存安全确认（VPS 上执行）:**
```bash
systemctl status x-ui           # Xray 仍然 running
ss -lntup | grep -E ':443|:8443|:18080'  # 端口正确
wg show                         # WG 隧道正常
free -h                         # 内存余量充足
```

---

## 关键信息速查

| 项目 | 值 |
|------|-----|
| VPS IP | `97.64.29.114`（被 GFW 封禁，需跳板或 KiwiVM） |
| SSH 跳板 | DMIT `root@64.186.226.51`（仅 key 认证，当前无法从外部跳） |
| KiwiVM 面板 | 搬瓦工后台 → KiwiVM（Web SSH 可用） |
| 服务用户 | `newssentry` |
| 服务端口 | `18080`（仅 127.0.0.1） |
| 代码目录 | `/opt/news-sentry/production/repo` |
| 数据目录 | `/srv/news-sentry/production/data` |
| systemd 服务 | `news-sentry`（deploy.yml 自动创建） |
| Cloudflare 域名 | `news-sentry.com` |
| API 网关 Key | 见 VPS `/opt/news-sentry/production/.env` 或 GitHub Actions Secret |

## 接手人操作顺序

0. Phase 89 交互响应排查：按 [interaction-latency-audit-20260611.md](./interaction-latency-audit-20260611.md) 复测 `/public-app/` 首屏、详情 ready、public feed hit/miss 与 realtime 采集窗口。
1. 优先处理“未完成事项与建议解决方向”中的 P0：Cloudflare Access。
2. 清理 P1 CI 告警：Actions Node runtime、`script_stop`、aiosqlite event-loop warning。
3. 进入 72 小时观察期：监控内存、磁盘、`news-sentry`、`cloudflared` 和 `x-ui` 稳定性。
4. 建立部署凭据轮换记录，并在首次轮换后触发一次 production Deploy workflow 验证。

## 风险提示

- **BWH IP 连通性**: IP 封禁不作为当前部署障碍；本机可通过已有代理直接 SSH，KiwiVM Web SSH 仍可作为兜底入口
- **Xray 共存**: 49 客户依赖代理服务，部署过程不能修改 iptables/nftables，venv 方式已规避此风险
- **deploy.yml 执行用户**: 脚本以 root 身份通过 SSH 执行，但 systemd 服务以 newssentry 用户运行
- **私钥安全**: 部署私钥仅存储在 GitHub Secrets（加密）和 VPS authorized_keys（公钥），不写入任何 git-tracked 文件
