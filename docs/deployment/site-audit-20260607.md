# News Sentry 已部署站点全栈审计报告

> 日期: 2026-06-07
> 站点: https://news-sentry.com
> 审计模式: 线上只读检查 + 截图归档 + 可执行整改 backlog
> 产出: 识别问题、证据归档、整改方向。本轮不直接修改生产代码或线上配置。

> 2026-06-08 更新: 已基于本报告启动全量硬化冲刺，脱敏整改记录见 [hardening-sprint-20260608.md](hardening-sprint-20260608.md)。本文件保留原始审计事实和 backlog 口径；OpenRouter 审计时 `qwen/qwen3.7-plus` 可用，当前因账号无付费额度已临时切到 `openai/gpt-oss-20b:free`。

---

## 审计元信息

| 项目 | 结果 |
|------|------|
| 生产域名 | `https://news-sentry.com` / `https://www.news-sentry.com` |
| 审计采样时 Deploy run | `27085932802`, success, 2026-06-07T07:18:46Z, commit `e7709d261ee5f13f1361d0f34da521b3ac9a4134` |
| 审计采样时 VPS 部署版本 | `/opt/news-sentry/production/.deploy-sha` = `e7709d261ee5f13f1361d0f34da521b3ac9a4134` |
| 公网 health | `GET /api/v1/health` 返回 `{"status":"ok"}` |
| VPS 服务 | `news-sentry=active`, `cloudflared=active`, `x-ui=active` |
| 资源余量 | `/` 12% used, `/srv/news-sentry` 12% used, memory 3.3Gi available |
| OpenRouter smoke | `translate.fast` 真实调用成功，模型 `qwen/qwen3.7-plus-20260602`, `fallback_used=False` |
| 审计截图 | `docs/deployment/audit-assets/20260607/` |
| 敏感信息处理 | 本报告不包含 OpenRouter key、News Sentry API key、登录 token、cookie、管理员密码 |

## 执行摘要

生产站点主链路可用：公网 health 正常，公开门户能浏览 Italy/Japan 数据，后台登录页可达，管理员 token 注入后的目标管理、Italy workbench、AI Provider 页面可读，VPS 服务和资源余量健康，OpenRouter 真实 smoke 通过。

本轮确认的主要风险集中在四类：

- 安全面：公网 `/api/v1/runtime/info` 暴露服务器路径和数据目录；首页 CSP 过宽且仍使用 `unsafe-inline`、`connect-src *`，同时会阻挡 Cloudflare Web Analytics beacon；样本响应缺少 HSTS、X-Frame-Options、Referrer-Policy、Permissions-Policy 等 HTTP 安全头。
- 产品体验面：移动端公开门户响应式布局明显失真，Italy feed 在 390px 宽度下被压成左侧窄列；分析页多个趋势面板显示空状态，但同页/同 target 已有事件数据。
- 运维质量面：独立 `CI` workflow 最新 run 因 mypy 失败为红，而 `Deploy` workflow 内置 CI Gate 为绿，两个流水线口径不一致；认证 `/api/v1/status` 返回 `total_events_all_targets=0`，与 Italy events API 的 `total=152` 不一致。
- 待复核面：Cloudflare Access 仍应作为 P0 处理，但本次 API 凭据无法读取 Zero Trust Access 资源，当前证据只能确认“需要复核/补齐”，不能以 API 结果证明“未启用”。

## 检查矩阵

| 范围 | 检查项 | 状态 | 证据 |
|------|--------|------|------|
| 公开站点 | 首页、target feed、analysis 桌面端 | 通过但有体验问题 | `01`, `02`, `03` 截图 |
| 公开站点 | 移动端首页、Italy feed | 不通过 | `04`, `05` 截图显示布局压缩/空白 |
| 公开站点 | PWA manifest / service worker / build manifest | 部分通过 | `manifest.json` 正常，`sw.js` 和 `build_manifest.json` 为 `no-store`，主 JS/CSS 仍 4 小时缓存 |
| 公开站点 | robots.txt | 待决策 | 当前是 Cloudflare content signals 响应，不是站点自有爬虫策略 |
| 登录后台 | 登录页 | 通过 | `06` 截图 |
| 登录后台 | 目标管理 / Italy workbench / AI Provider | 通过但有路由可发现性问题 | `07`, `08`, `10` 截图 |
| 登录后台 | 采集健康入口 | 部分通过 | `#/admin/collection/health` 被重定向到当前 target 采集页，见 `09` |
| API/安全 | 公开/认证边界 | 部分通过 | `/api/v1/status`、`/api/v1/ai/enrichment/status` 公网 GET 为 401；`/api/v1/runtime/info` 公开泄露部署细节 |
| API/安全 | CSP / CORS / 安全响应头 | 不通过 | CSP 过宽，缺少关键安全头；CORS 仅允许站点 origin，但对恶意 Origin 仍返回 credentials 头 |
| Cloudflare | TLS / HTTPS / WAF / rate limit | 通过 | SSL strict, Always HTTPS on, Managed Free Ruleset 1 条, rate limit 1 条 |
| Cloudflare | Access | 待复核 | Access API 返回 403/9999，当前凭据不能读取 Zero Trust Access app |
| 运维 | VPS 服务、资源、journal | 通过但需观察 | 服务 active；cloudflared 近 2 小时有连接重建/ICMP warning |
| CI/CD | Deploy workflow | 通过 | Run `27085932802` success |
| CI/CD | 独立 CI workflow | 不通过 | Run `27085932795` mypy 14 errors |
| AI 能力 | OpenRouter 真实调用 | 通过 | `translate.fast` 返回模型 `qwen/qwen3.7-plus-20260602` |

## 截图证据

| 编号 | 文件 | 视口 | 结论 |
|------|------|------|------|
| 01 | [公开首页桌面](audit-assets/20260607/01-public-home-desktop.png) | 1440x900 | 首页加载成功，0-event targets 空状态偏弱 |
| 02 | [Italy feed 桌面](audit-assets/20260607/02-italy-feed-desktop.png) | 1440x900 | Feed 可读，已加载 91 / 共 152 条 |
| 03 | [Italy analysis 桌面](audit-assets/20260607/03-italy-analysis-desktop.png) | 1440x900 | 指标可见，但主题/情感/实体趋势为空 |
| 04 | [公开首页移动](audit-assets/20260607/04-public-home-mobile.png) | 390x844 | 顶部/footer 链接拥挤，target 文案换行生硬 |
| 05 | [Italy feed 移动](audit-assets/20260607/05-italy-feed-mobile.png) | 390x844 | 内容被压成左侧窄列，主体区域大面积空白 |
| 06 | [后台登录桌面](audit-assets/20260607/06-admin-login-desktop.png) | 1440x900 | 登录页可达 |
| 07 | [后台目标管理](audit-assets/20260607/07-admin-targets-desktop.png) | 1440x813 | 5 个 target 可见，总事件 161 |
| 08 | [后台 Italy 总览](audit-assets/20260607/08-admin-italy-overview-desktop.png) | 1440x813 | Italy workbench 可达 |
| 09 | [后台采集健康入口](audit-assets/20260607/09-admin-collection-health-desktop.png) | 1440x813 | 目标上下文下被重定向到 Italy 采集 tab |
| 10 | [后台 AI Provider](audit-assets/20260607/10-admin-ai-desktop.png) | 1440x813 | AI Provider 页面可达 |

## 已确认问题

### NS-AUDIT-001: 公开 runtime info 暴露部署路径和数据目录

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | `GET /api/v1/runtime/info` 无需认证，返回 `code_path`、`data_dir`、`git_commit`、`static_cache_name`。 |
| 证据 | 公网返回 `code_path=/opt/news-sentry/production/repo/src/news_sentry/core/api_server.py`、`data_dir=/srv/news-sentry/production/data`。实现位置: `src/news_sentry/core/api_server.py:4598`。 |
| 影响 | 增加攻击者对目录结构、部署形态和版本的认知，给后续漏洞利用、路径探测和社工提供辅助信息。 |
| 初步根因 | runtime info 为前端静态版本检测服务，但把内部调试字段直接暴露在公开端点。 |
| 建议方案 | 将公开响应收敛为 `status`、`static_build`、`static_cache_name`；`code_path`、`data_dir`、完整 git 信息移到认证诊断端点。 |
| 验收标准 | 未认证访问不再返回服务器绝对路径或数据目录；认证诊断仍能看到必要部署信息。 |
| 建议测试命令 | `curl -fsS https://news-sentry.com/api/v1/runtime/info`；`curl -fsS -H "Authorization: Bearer <token>" https://news-sentry.com/api/v1/status` |

### NS-AUDIT-002: CSP 过宽且与 Cloudflare Web Analytics 冲突

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | 首页 meta CSP 包含 `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net`、`style-src 'self' 'unsafe-inline'`、`connect-src *`；控制台记录 Cloudflare beacon 被 CSP 阻挡。 |
| 证据 | `src/news_sentry/static/index.html:25`；CDP log: `Loading the script 'https://static.cloudflareinsights.com/beacon.min.js/...' violates Content Security Policy`。 |
| 影响 | `unsafe-inline` 和 `connect-src *` 会扩大 XSS/数据外传面；同时 Cloudflare Web Analytics 不能正常采集。 |
| 初步根因 | CSP 仍在 HTML meta 中快速声明，未按生产依赖梳理最小 allowlist；Cloudflare 自动注入脚本未纳入策略。 |
| 建议方案 | 改为 HTTP header CSP；移除 `connect-src *`；优先自托管 Chart.js 或加 SRI/固定版本；若保留 Cloudflare Analytics，将 `https://static.cloudflareinsights.com` 纳入 `script-src`，将 beacon 上报域纳入 `connect-src`；逐步用 nonce/hash 替代 inline。 |
| 验收标准 | 控制台无 CSP violation；`script-src` 不含 `unsafe-inline` 或有明确过渡说明；`connect-src` 只允许 `self` 和必要上游。 |
| 建议测试命令 | `curl -fsS https://news-sentry.com/ | rg "Content-Security-Policy"`；用 CDP/浏览器打开首页并检查 console security log。 |

### NS-AUDIT-003: 关键 HTTP 安全响应头缺失

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | 抽样 GET `/`、`/api/v1/health`、`/api/v1/runtime/info` 响应未看到 `Strict-Transport-Security`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`。 |
| 证据 | `curl -sS -D - -o /dev/null https://news-sentry.com/` 仅见 `server: cloudflare`、`cf-cache-status` 等基础头。 |
| 影响 | 缺 HSTS 会降低 HTTPS 降级保护；缺 frame 防护会增加点击劫持风险；缺 referrer/permissions policy 会让浏览器默认权限面偏宽。 |
| 初步根因 | FastAPI/Cloudflare 还没有统一安全 header 中间件或 Transform Rule。 |
| 建议方案 | 在 FastAPI 中间件或 Cloudflare Response Header Transform 统一加: `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`、`X-Frame-Options: DENY` 或 CSP `frame-ancestors 'none'`、`Referrer-Policy: strict-origin-when-cross-origin`、`Permissions-Policy` 最小化。 |
| 验收标准 | 首页、静态资源、API 响应均带预期安全头；不会破坏 PWA 和 Cloudflare Tunnel。 |
| 建议测试命令 | `curl -sS -D - -o /dev/null https://news-sentry.com/ | rg -i "strict-transport-security|x-frame-options|referrer-policy|permissions-policy|content-security-policy"` |

### NS-AUDIT-004: 移动端公开门户布局失真

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | 390x844 移动视口下，公开首页顶部/footer 链接拥挤；Italy feed 被压成左侧窄列，主体大面积空白，分类 chip 垂直挤压。 |
| 证据 | `04-public-home-mobile.png`、`05-italy-feed-mobile.png`。 |
| 影响 | 移动端几乎无法高效浏览新闻列表，直接影响公开门户可用性和首屏可信度。 |
| 初步根因 | 公共门户布局仍沿用桌面 sidebar/grid 约束，移动断点没有重排为单列内容流；顶部导航和 footer/法律链接没有移动端收纳策略。 |
| 建议方案 | 为公开门户建立独立移动布局: 顶部紧凑 header、target/feed 主体全宽、分类横向滚动或折叠 filter sheet、footer 链接下沉；用 390px/430px/768px 断点验收。 |
| 验收标准 | 390px 宽度下 feed 卡片占可用宽度 90% 以上，正文横排可读，无大面积空白，无文字逐字竖排。 |
| 建议测试命令 | CDP/Playwright 截图 `https://news-sentry.com/#/news/target/italy` at 390x844；人工核验 `05-italy-feed-mobile.png` 等价结果。 |

### NS-AUDIT-005: Analysis 页趋势模块空状态与已有数据不一致

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | Italy analysis 页展示 `24小时新闻 152`、分类分布等数据，但主题趋势、情感趋势、热门实体均显示暂无。 |
| 证据 | `03-italy-analysis-desktop.png`。 |
| 影响 | 用户会误以为分析能力未运行或数据质量不足，削弱 AI/研判产品价值表达。 |
| 初步根因 | 趋势聚合可能依赖缺失字段，或前端未对“聚合为空但事件存在”给出解释性空状态。 |
| 建议方案 | 追踪 analysis API 的 topic/sentiment/entity 字段来源；如果确实缺数据，显示“等待 AI 增强/实体抽取”的原因和最近处理状态；如果是聚合 bug，补数据字段映射和回归测试。 |
| 验收标准 | Italy 有事件时至少展示可解释的主题/实体/情感摘要；若为空，用户能看到原因和下一步状态。 |
| 建议测试命令 | `curl -fsS "https://news-sentry.com/api/v1/trends?target_id=italy"`；浏览器打开 `/#/news/target/italy/analysis`。 |

### NS-AUDIT-006: 认证 status API 与 events API 统计口径不一致

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | VPS 本机认证 `GET /api/v1/status` 返回 `total_events_all_targets=0`、`target_count=0`，但 `GET /api/v1/events?target_id=italy&page_size=3` 返回 `total=152`。 |
| 证据 | 远端只读检查输出: `local_status_summary=... total_events_all_targets:0 ... target_count:0`；`local_events_italy_summary=total:152 returned:3 first_stage:filtered`。 |
| 影响 | 运维诊断会误判生产无数据，影响告警、排障和上线验收。 |
| 初步根因 | `/api/v1/status` 仍按文件系统 drafted 阶段或旧目录协议统计，未与当前 SQLite/API 数据口径对齐。 |
| 建议方案 | 明确 status 的语义: 文件产物诊断和 API 事件统计分离；新增 `events_api_total` 或改用 AsyncStore 统计；文档说明 stage/目录口径。 |
| 验收标准 | status 至少能解释为何文件计数为 0，同时返回 API 总数 161 或按 target 展示 Italy 152/Japan 9。 |
| 建议测试命令 | `curl -fsS -H "Authorization: Bearer <token>" https://news-sentry.com/api/v1/status`；`curl -fsS "https://news-sentry.com/api/v1/events?target_id=italy&page_size=1"` |

### NS-AUDIT-007: 独立 CI workflow 失败，Deploy workflow 口径为绿

| 字段 | 内容 |
|------|------|
| 优先级 | P1 |
| 现象 | 最新 Deploy run `27085932802` 成功，但同 commit 的独立 CI run `27085932795` 失败。 |
| 证据 | `gh run view 27085932795 --log-failed` 显示 mypy 14 errors，集中在 `ai_enrichment.py`、`async_run.py`、`api_server.py`。 |
| 影响 | main 分支状态不一致，容易让“部署可用”和“代码质量 gate”脱节；后续 PR/保护分支会出现不确定性。 |
| 初步根因 | Deploy workflow 的 CI Gate 未运行 mypy，独立 CI 增加了类型检查但现有代码未满足。 |
| 建议方案 | 二选一收敛口径: 要么把 mypy 纳入 Deploy CI Gate 并修复 14 个错误，要么先将 mypy 调整为非阻断并建立修复 issue。推荐修复类型错误后统一两个 workflow。 |
| 验收标准 | 同一 commit 的 `CI` 与 `Deploy` 均绿色；mypy 输出 0 errors。 |
| 建议测试命令 | `python -m mypy src/news_sentry/ --ignore-missing-imports`；`gh run list --repo XucroYuri/NewsSentry --workflow CI --limit 1` |

### NS-AUDIT-008: Cloudflare Browser Integrity 对非浏览器登录客户端返回 1010

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | 使用 Python urllib 直接 POST `/api/v1/auth/login` 返回 Cloudflare 1010 `browser_signature_banned`；使用浏览器 UA 的 curl 登录成功。 |
| 证据 | 审计命令中 `login_status=403`，Cloudflare error name `browser_signature_banned`；随后 `curl_login_status=200`。 |
| 影响 | 若未来 CLI、监控或自动化需要走公网登录端点，可能被 Cloudflare 误杀。浏览器用户暂未受影响。 |
| 初步根因 | Cloudflare `browser_check=on`，登录端点没有为可信自动化/API 客户端提供单独路径或绕过策略。 |
| 建议方案 | 保持浏览器登录保护；为机器调用使用 `/api/v1/auth/token` + API key 或 mTLS/Access service token；必要时为 `/api/v1/auth/token` 建独立 rate limit/WAF 策略。 |
| 验收标准 | 浏览器登录仍受保护；受信自动化可以通过正式 API 认证方式稳定 200；恶意脚本仍被限制。 |
| 建议测试命令 | `curl -sS -A "Mozilla/5.0" -X POST https://news-sentry.com/api/v1/auth/login ...`；`python` urllib 负例保留为边缘策略检查。 |

### NS-AUDIT-009: 公开 JS/CSS 为未指纹文件名且缓存 4 小时

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | `/app.js`、`/public.css` 返回 `cache-control: max-age=14400`，且文件名未带 hash；`sw.js` 和 `/build_manifest.json` 已是 `no-store`。 |
| 证据 | GET header: `/app.js` `cf-cache-status=HIT age=1331 max-age=14400`；`/public.css` `age=5797 max-age=14400`。 |
| 影响 | 上线后用户可能在数小时内继续使用旧 JS/CSS；若 Service Worker 也持有旧资产，可能产生前后端协议短暂不一致。 |
| 初步根因 | 静态资源仍使用固定文件名，通过 manifest/SW 兜底刷新，但 HTTP cache 仍较长。 |
| 建议方案 | 短期把非指纹 JS/CSS 缓存降为 `no-cache` 或 5 分钟；中期引入 hash 文件名和 manifest 注入；上线后显示新版本刷新提示。 |
| 验收标准 | 发布后新浏览器请求能在 1 分钟内拿到最新 JS/CSS；旧 SW 可被可靠替换。 |
| 建议测试命令 | `curl -sS -D - -o /dev/null https://news-sentry.com/app.js | rg -i "cache-control|age|cf-cache-status"` |

### NS-AUDIT-010: robots.txt 不是站点自有爬虫策略

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | `/robots.txt` 返回 Cloudflare content signals 说明，而非 News Sentry 自有 `User-agent` / `Allow` / `Disallow` 策略。 |
| 证据 | robots 前缀为 `As a condition of accessing this website... content signals`。 |
| 影响 | 搜索引擎和 AI crawler 对公开新闻门户、后台 hash route、API 的抓取边界不清晰。 |
| 初步根因 | Cloudflare 内容信号功能承接了 robots 响应，应用未提供明确 robots 文件或规则优先级。 |
| 建议方案 | 明确站点定位后提供自有 robots: 公开门户可索引，`/api/`、`/#/admin`、敏感路径禁止；保留或移除 Cloudflare content signals 要与策略一致。 |
| 验收标准 | `/robots.txt` 同时表达搜索爬虫和 AI crawler 策略；不会误阻公开首页。 |
| 建议测试命令 | `curl -fsS https://news-sentry.com/robots.txt` |

### NS-AUDIT-011: 后台采集健康入口被 target workbench 重定向

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | 打开 `/#/admin/collection/health` 后，实际地址变为 `/#/admin/targets/italy/collection`。 |
| 证据 | `09-admin-collection-health-desktop.png`；映射逻辑见 `src/news_sentry/static/router.js:258`，`collection.health` 映射到 `scoped("collection")`。 |
| 影响 | 全局采集健康/诊断入口不易发现，管理员可能只能看到当前 target 的采集页。 |
| 初步根因 | 旧全局路由统一迁移到 target workbench，但没有为全局 collector diagnostics 保留清晰入口。 |
| 建议方案 | 保留 `#/admin/collection/health` 作为全局健康页；target workbench 内提供 target-scoped 采集页；面包屑和导航明确二者差异。 |
| 验收标准 | 访问 `#/admin/collection/health` 后地址不变，并展示全局 collector diagnostics；target 页仍可访问 `#/admin/targets/{id}/collection`。 |
| 建议测试命令 | 用浏览器打开 `https://news-sentry.com/#/admin/collection/health` 并检查 `location.hash`。 |

### NS-AUDIT-012: CORS credentials 头在未允许 Origin 时仍返回

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | `Origin: https://evil.example` 请求 health 时不返回 `access-control-allow-origin`，但仍返回 `access-control-allow-credentials: true`。 |
| 证据 | CORS probe: 合法 origin 返回对应 allow-origin + `vary: Origin`；恶意 origin 只返回 credentials。 |
| 影响 | 当前浏览器不会放行恶意 Origin，但响应头语义不够干净，容易在后续中间件调整中产生误配置。 |
| 初步根因 | CORS 中间件可能全局启用 credentials，但 allow-origin 动态过滤。 |
| 建议方案 | 对未允许 Origin 不返回任何 CORS 头；为公开 GET API 和认证 API 分开策略。 |
| 验收标准 | 非白名单 Origin 响应不包含 `access-control-allow-*`；白名单 Origin 正常工作。 |
| 建议测试命令 | `curl -sS -D - -o /dev/null -H "Origin: https://evil.example" https://news-sentry.com/api/v1/health` |

### NS-AUDIT-013: Cloudflared 近 2 小时有连接重建/ICMP warning

| 字段 | 内容 |
|------|------|
| 优先级 | P2 |
| 现象 | `journalctl -u cloudflared --since "2 hours ago"` 中有 16 条 error/warning，集中在 06:10:36 连接服务失败和 ICMP proxy 权限 warning。 |
| 证据 | 日志摘要包含 `accept stream listener encountered a failure while serving`、`ICMP proxy feature is disabled`；服务当前 active。 |
| 影响 | 当前未影响可用性，但观察期内若持续出现，可能代表 tunnel 稳定性或权限配置问题。 |
| 初步根因 | 部署/重启期 tunnel 连接重建，外加 root/GID 与 ping group range 不匹配。 |
| 建议方案 | 观察 72 小时；若持续出现，按 Cloudflare cloudflared 文档调整 ICMP proxy 权限或关闭无用 ICMP 功能；为 tunnel 建 health/日志告警。 |
| 验收标准 | 72 小时内 cloudflared 无连续连接失败；公网 health 无波动。 |
| 建议测试命令 | `journalctl -u cloudflared --since "24 hours ago" --no-pager | rg -i "ERR|WRN"` |

### NS-AUDIT-014: 登录页表单语义和移动 PWA meta 有低优先级警告

| 字段 | 内容 |
|------|------|
| 优先级 | P3 |
| 现象 | CDP log 提示 password field 不在 form 中；`apple-mobile-web-app-capable` 已 deprecated，建议增加 `mobile-web-app-capable`。 |
| 证据 | CDP log sample: `[DOM] Password field is not contained in a form`；`src/news_sentry/static/index.html:22`。 |
| 影响 | 不影响当前登录，但会影响密码管理器、自动填充和移动安装兼容性。 |
| 初步根因 | 登录 UI 使用 div/button 组合，没有原生 form；PWA meta 沿用旧 Apple 字段。 |
| 建议方案 | 用 `<form>` 包裹登录字段和 submit；保留 autocomplete；新增 `mobile-web-app-capable=yes`。 |
| 验收标准 | Chrome DevTools 不再出现该 DOM/PWA warning；回车提交登录可用。 |
| 建议测试命令 | 浏览器打开 `/#/admin/login`，检查 console warnings 和密码管理器识别。 |

## 待复核问题

### NS-AUDIT-PENDING-001: Cloudflare Access 是否启用需要 Zero Trust 权限复核

| 字段 | 内容 |
|------|------|
| 优先级 | P0 |
| 当前状态 | 历史部署记录将“Cloudflare Access 访问策略”列为 P0 未完成；本次 Cloudflare zone API 能读 TLS/WAF/rate limit，但 `accounts/{account}/access/apps` 返回 403/9999，不能用当前 API 结果确认 Access 应用列表。 |
| 风险 | 如果后台只靠应用内登录暴露公网，扫描和撞库面更大；如果 Access 已在其他账号/策略启用，则当前审计凭据不可观测，运维可见性不足。 |
| 建议方案 | 使用 Cloudflare Dashboard 或带 Zero Trust Access read 权限的 scoped token 复核；若未启用，为 `news-sentry.com` / `www.news-sentry.com` 创建 Self-hosted Access application，优先保护后台和写接口，health 路径是否绕过需单独设计。 |
| 验收标准 | 未授权访问后台先进入 Cloudflare Access；授权邮箱/IdP 通过后仍需应用内登录；CI/VPS health check 不受影响。 |
| 建议测试命令 | Dashboard 复核 Zero Trust Access apps；或用具备权限的 token 调 `GET /accounts/{account_id}/access/apps?search=news-sentry.com`。 |

### NS-AUDIT-PENDING-002: `/api/v1/status` 重复装饰器疑点已复核未确认

| 字段 | 内容 |
|------|------|
| 优先级 | 无需处理 |
| 当前状态 | 计划中提到 `src/news_sentry/core/api_server.py` 可能存在重复 `@app.get("/api/v1/status")`；本次检查当前工作区和 `HEAD` 均只有一处，见 `src/news_sentry/core/api_server.py:4720`。 |
| 建议方案 | 不作为问题处理；若后续分支再次出现重复装饰器，再纳入代码清理。 |
| 建议测试命令 | `rg -n '@app\\.get\\("/api/v1/status"\\)' src/news_sentry/core/api_server.py` |

## 分项证据摘要

### 公开 HTTP / 安全头

```text
GET /                          HTTP/2 200, cf-cache-status DYNAMIC
GET /app.js                    HTTP/2 200, cache-control max-age=14400, cf-cache-status HIT
GET /public.css                HTTP/2 200, cache-control max-age=14400, cf-cache-status HIT
GET /sw.js                     HTTP/2 200, cache-control no-store, cf-cache-status BYPASS
GET /build_manifest.json       HTTP/2 200, cache-control no-store
GET /api/v1/runtime/info       HTTP/2 200, cache-control no-store
GET /api/v1/status             HTTP/2 401
GET /api/v1/ai/enrichment/status HTTP/2 401
```

样本响应未见 HSTS、X-Frame-Options、Referrer-Policy、Permissions-Policy。

### CORS

```text
Origin: https://news-sentry.com      -> allow-origin: https://news-sentry.com, credentials true, vary Origin
Origin: https://www.news-sentry.com  -> allow-origin: https://www.news-sentry.com, credentials true, vary Origin
Origin: https://evil.example         -> no allow-origin, credentials true
```

### 后台只读 API

```text
local_auth_me_http=200 role=admin permissions=3 has_api_key=True
local_status_http=200 total_events_all_targets=0 target_count=0 auto_collector_enabled=True
local_ai_enrichment_status_http=200 enabled=true running=true remaining_daily_requests=45
local_events_italy_sample_http=200 total=152 returned=3 first_stage=filtered
local_targets_http=200 target event counts: china-watch-en 0, france 0, germany 0, italy 152, japan 9
```

### Cloudflare

```text
zone: news-sentry.com active, Free Website
ssl: strict
always_use_https: on
min_tls_version: 1.2
browser_check: on
security_level: medium
tls_1_3: on
brotli: on
managed ruleset: 1 rule
rate limit: 100 requests / 10 seconds / IP, 1 rule
Access API: 403/9999 with current credential
```

### VPS

```text
deploy_sha=e7709d261ee5f13f1361d0f34da521b3ac9a4134
service_news-sentry=active
service_cloudflared=active
service_x-ui=active
disk_root=78G total, 8.4G used, 66G avail, 12% use
memory=3.9Gi total, 571Mi used, 3.3Gi available
journal_news_sentry_errors_2h=0
journal_cloudflared_errors_2h=16
```

### GitHub Actions

```text
Deploy run 27085932802: success, commit e7709d261ee5f13f1361d0f34da521b3ac9a4134
CI run 27085932795: failure, Type check (mypy), 14 errors in 3 files
```

### OpenRouter

```text
openrouter_smoke_status=ok
openrouter_model=qwen/qwen3.7-plus-20260602
openrouter_route_id=translate.fast
openrouter_provider=openrouter
openrouter_fallback_used=False
openrouter_budget_exceeded=False
```

## 整改 Backlog

| 顺序 | 问题 | 建议 owner | 处理方向 | 验收 |
|------|------|------------|----------|------|
| 1 | Cloudflare Access 待复核/补齐 | 运维 | 用 Zero Trust 权限确认 Access app；未启用则保护后台和写接口 | Access 在后台前置生效，health 不被误伤 |
| 2 | runtime info 泄露 | 后端 | 收敛公开字段，内部诊断走认证 | 公网不再出现绝对路径 |
| 3 | CSP + 安全头 | 后端/Cloudflare | FastAPI middleware 或 CF Transform Rule，收敛 CSP/CORS/header | security headers 存在，console 无 CSP violation |
| 4 | 移动端公开门户 | 前端/产品设计 | 单列移动布局、横向 filter、header/footer 收纳 | 390px 截图可读，无左侧窄列 |
| 5 | status 统计口径 | 后端 | 文件诊断和 API 事件统计分离 | status 与 events 口径可解释 |
| 6 | Analysis 空状态 | 前端/数据 | 修复聚合或解释 AI 增强状态 | 有数据 target 不再展示无解释空状态 |
| 7 | CI mypy 红灯 | 后端/CI | 修复 14 个类型错误或调整 gate 口径 | CI 与 Deploy 同 commit 均绿 |
| 8 | 静态缓存策略 | 前端/运维 | 非指纹资源降缓存或引入 hash asset | 发布后旧资源不滞留 |
| 9 | robots 策略 | 产品/运维 | 明确公开门户和 API/后台抓取边界 | robots.txt 为站点自有策略 |
| 10 | 后台采集健康 IA | 前端/产品 | 保留全局 health，target scoped 另设入口 | `#/admin/collection/health` 不跳转 |

## 全局验收标准

完成整改后，至少执行以下验证：

```bash
curl -fsS https://news-sentry.com/api/v1/health
curl -fsS https://news-sentry.com/api/v1/runtime/info
curl -sS -D - -o /dev/null https://news-sentry.com/ | rg -i "strict-transport-security|x-frame-options|referrer-policy|permissions-policy|content-security-policy"
curl -sS -D - -o /dev/null -H "Origin: https://evil.example" https://news-sentry.com/api/v1/health
curl -sS -D - -o /dev/null https://news-sentry.com/app.js | rg -i "cache-control|age|cf-cache-status"
python -m mypy src/news_sentry/ --ignore-missing-imports
python tools/scan_sensitive_data.py
git diff --check
```

并重新生成以下截图:

- `/#/news/feed` at 1440x900 and 390x844
- `/#/news/target/italy` at 1440x900 and 390x844
- `/#/news/target/italy/analysis` at 1440x900
- `/#/admin/login` at 1440x900
- `/#/admin/targets` and `/#/admin/advanced/ai` at 1440x900
