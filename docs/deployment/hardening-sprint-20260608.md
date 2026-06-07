# News Sentry 全量硬化冲刺记录

> 日期: 2026-06-08
> 范围: Codex Security 全库扫描、生产安全硬化、CI/CD 质量门、运维可观测性、产品体验方向探索
> 原则: 完整漏洞细节保存在本机 `/tmp` 扫描产物中；仓库只记录脱敏摘要、整改状态和可执行 backlog。

## 执行摘要

本轮已把已部署站点审计中的多项 P1/P2 问题转成代码级整改，并完成一次 Codex Security repository-wide scan。

核心改进：

- 公网 `/api/v1/runtime/info` 已收敛到静态构建字段，不再暴露服务端路径或数据目录。
- FastAPI 增加统一安全响应头和 HTTP CSP；移除 HTML meta CSP；CORS 对非白名单 Origin 不再返回 credentials。
- 自有 `robots.txt` 已由应用响应；`app.js`、`public.css` 改为短缓存/重新验证策略。
- `/api/v1/status` 增加文件事件数、SQLite/API 事件数、target 级事件数和 source 数，保留旧字段兼容。
- 修复认证配置路径穿越、导入路径穿越、RSS/API redirect SSRF、OpenCLI env 透传、Service Worker API 缓存、CI secret scanner 日志泄露和漏检。
- Deploy workflow 加入 mypy 和 publication hygiene gate，移除 `script_stop`，避免 GitHub token 持久化到 VPS `.git/config`，失败 journal 输出加脱敏。
- Product Design 已先生成 3 个视觉方向；公开门户 UI 未在本轮直接改版，等待选定方向。

## Codex Security 扫描产物

| 项目 | 路径 / 状态 |
|------|-------------|
| Scan ID | `9bc6965cbae4_20260608-005421` |
| Markdown report | `/tmp/codex-security-scans/NewsSentry/9bc6965cbae4_20260608-005421/report.md` |
| HTML report | `/tmp/codex-security-scans/NewsSentry/9bc6965cbae4_20260608-005421/report.html` |
| Threat model | `/tmp/codex-security-scans/NewsSentry/9bc6965cbae4_20260608-005421/artifacts/01_context/threat_model.md` |
| Reviewed surfaces | `/tmp/codex-security-scans/NewsSentry/9bc6965cbae4_20260608-005421/artifacts/03_coverage/reviewed_surfaces.md` |
| Report validation | `validate_report_format.py` 已通过，HTML 已渲染 |

仓库不提交完整漏洞细节，避免公开暴露攻击路径。完整报告仅保存在本机 `/tmp`。

## 已完成整改

| 编号 | 优先级 | 问题摘要 | 整改状态 | 验收方式 |
|------|--------|----------|----------|----------|
| NS-AUDIT-001 | P1 | 公开 runtime info 暴露 `code_path`、`data_dir` | 已修复 | API 测试断言公开字段只含 `status/static_build/static_cache_name` |
| NS-AUDIT-002/003 | P1 | CSP 过宽、缺安全响应头 | 已修复 | API 测试覆盖 HSTS、CSP、frame/referrer/permissions policy |
| NS-AUDIT-006 | P1 | `/api/v1/status` 与 events 统计口径不一致 | 已修复 | API 测试覆盖 `file_event_total/api_event_total/targets.*` |
| NS-AUDIT-009 | P2 | 未指纹 JS/CSS 缓存偏长 | 已修复 | API 测试覆盖 `/app.js`、`/public.css` cache-control |
| NS-AUDIT-010 | P2 | robots.txt 非站点自有策略 | 已修复 | API 测试覆盖 `/robots.txt` |
| NS-AUDIT-011 | P2 | 全局采集健康路由被 target workbench 吞掉 | 已修复 | `node tests/js/router_test.mjs` |
| NS-AUDIT-012 | P2 | 非白名单 Origin 仍返回 CORS credentials | 已修复 | API 测试覆盖恶意 Origin |
| API-AUTH-001 | P1 | source config 读写路径穿越 | 已修复 | 新增 GET/PATCH 编码路径穿越回归测试 |
| API-AUTH-002 | P1 | import target/source 写路径穿越 | 已修复 | 新增 import target/source 回归测试 |
| NS-B-001/002 | P1 | RSS/API redirect SSRF | 已修复 | 新增同步/异步 redirect 阻断测试 |
| NS-B-003 | P1 | OpenCLI 子进程继承运行时 secret | 已修复 | 新增真实 subprocess 环境隔离测试 |
| STATIC-SW-001 | P1 | Service Worker 缓存认证 API JSON | 已修复 | `static_build_manifest_test.mjs` 覆盖 API network-only |
| NS-CICD-001/002 | P1 | secret scanner 输出明文行且漏检 key 名 | 已修复 | 新增 scanner 输出脱敏和 key 检测测试 |
| NS-CICD-003/004 | P1 | Deploy token 持久化 / journal 可能泄露凭据 | 已修复 | workflow 改为临时 auth header，journal 输出脱敏 |
| NS-CICD-005 | P1 | Deploy gate 弱于 CI | 部分修复 | deploy 已加入 mypy 和 publication hygiene；Docker/release 待补 |

## Product Design 三个方向

本轮按计划先做视觉探索，不直接改 UI。生成图在本机：

| 方向 | 定位 | 图片 |
|------|------|------|
| A: Editorial Intelligence | 更像编辑台/情报雷达，突出新闻流和研判摘要 | `/Users/xuyu/.codex/generated_images/019ea0a9-e429-72f3-8f5d-26e954b45013/ig_0db2053e4eb6772c016a25a51044ac8199859ecd25b859b59e.png` |
| B: Operations Console | 更偏后台工作台，密度高、目标健康和采集状态更明确 | `/Users/xuyu/.codex/generated_images/019ea0a9-e429-72f3-8f5d-26e954b45013/ig_0db2053e4eb6772c016a25a5605f008199a78c2469862ce2da.png` |
| C: Public News Portal | 更偏公开门户，移动端新闻流优先、空状态解释更友好 | `/Users/xuyu/.codex/generated_images/019ea0a9-e429-72f3-8f5d-26e954b45013/ig_0db2053e4eb6772c016a25a5a2203c8199bdf54554e02ed540.png` |

建议先选 C 作为公开门户基线，再吸收 A 的分析页语言和 B 的后台采集健康入口。

## 未完成事项与建议方向

| 优先级 | 事项 | 当前状态 | 建议方向 | 验收标准 |
|--------|------|----------|----------|----------|
| P0 | Cloudflare Access | 当前 `CF_API_EMAIL/CF_API_KEY` 可读 zone/accounts，但 `GET /zones/{zone}/access/apps` 和 `GET /accounts/{account}/access/apps` 均返回 Cloudflare `9999`，无法创建 Access app。 | 换用具备 `Access: Apps and Policies Write` 的 API Token，或在 Cloudflare 控制台手动创建 self-hosted Access app；allowlist 先放当前 Cloudflare 管理邮箱；`/api/v1/health` 需要保留公网或单独监控例外。 | 未授权访问 Web UI 先进入 Cloudflare Access；授权邮箱可继续登录应用；`/api/v1/health` 不影响外部监控。 |
| P1 | SSE query token | 仍使用 EventSource query token，因需要设计短期票据，本轮未直接改。 | 新增 authenticated POST 创建短 TTL SSE ticket，EventSource 只带 ticket，不带 24h bearer token。 | 日志和 URL 中不再出现主会话 bearer token；SSE 连接仍稳定。 |
| P1 | Docker/release workflow gate | Deploy 已补齐，Docker/release 仍需对齐 CI。 | Docker push 和 release upload 前加入 ruff/mypy/pytest/secret scan；最少先加入 secret scan 和 smoke tests。 | 镜像/Release artifact 发布前同 commit 质量门全绿。 |
| P2 | Mutable GitHub Actions | privileged workflow 仍使用部分 mutable major tag。 | 分批 pin 第三方 actions 到 commit SHA，并用 Dependabot/手动节奏升级。 | deploy/release/docker privileged jobs 不依赖未审查可变引用。 |
| P2 | Docker remote installers | browser/full 镜像仍有未校验远端安装步骤。 | 固定 base image digest、包版本和校验和；必要时拆分 browser 镜像为手动发布。 | 镜像构建输入可审计、可复现。 |
| P2 | Chart.js SRI/self-host | 已固定版本 `4.4.9`，但仍未 SRI 或自托管。 | 优先自托管 Chart.js；若继续 CDN，则加 SRI 并更新 CSP。 | 浏览器脚本依赖有完整性约束。 |
| P2 | 产品改版落地 | 三方向已生成，但未选定。 | 先选移动端公开门户方向，再实施 390x844 feed、analysis 空状态、后台采集健康入口。 | 移动端 feed 主体全宽可读，analysis 空状态可解释，后台全局采集健康可达。 |
| P2 | 72 小时 cloudflared 观察 | 仍需上线后连续观察。 | 每日执行 `systemctl is-active news-sentry cloudflared x-ui`、`journalctl -u cloudflared --since -24h`、公网 health 抽样。 | 72 小时内无异常重启、health 波动或 tunnel 频繁重连。 |

## 本地验证记录

已完成：

- `.venv/bin/python -m pytest tests/unit/test_api_server.py tests/unit/test_rss_collector.py tests/unit/test_api_collector.py tests/unit/test_opencli_adapter.py tests/unit/test_sensitive_data_scan.py -q --tb=short`
- `.venv/bin/python -m pytest tests/ -q --tb=short --timeout=300` → `2306 passed`，仍有 3 个既有 sqlite ResourceWarning
- `node tests/js/static_build_manifest_test.mjs`
- `node tests/js/router_test.mjs`
- `node tests/js/public_home_targets_test.mjs`
- `node tests/js/public_portal_test.mjs`
- `node tests/js/public_analysis_test.mjs`
- `.venv/bin/python -m mypy src/news_sentry/ --ignore-missing-imports`
- `.venv/bin/python -m ruff check`
- `.venv/bin/python tools/scan_sensitive_data.py`
- `.venv/bin/python tools/check_publication_hygiene.py`
- `git diff --check`

待最终收口：部署到 production 后公网复验和 VPS `.deploy-sha` 对齐。
