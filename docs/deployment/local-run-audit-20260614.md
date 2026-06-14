# News Sentry 本地运行审计与安全扫描报告

> 日期: 2026-06-14
> 仓库版本: `179bdede13366a26280cd877d34498526b0e89cf`
> 审计方式: 本地只读运行验证 + 浏览器截图取证 + 仓库级安全扫描
> 目标: 记录本地运行中的真实问题、复现路径、临时绕过和建议修复；本轮不直接改产品代码

## 审计元信息

| 项目 | 结果 |
| --- | --- |
| Python/Node 环境 | Python `3.13.13` / Node `24.12.0` / npm `11.6.2` |
| Python dry-run | `./.venv/bin/python -m news_sentry.cli run --target italy --stage collect --profile local-workstation --dry-run` 成功 |
| Doctor | 通过基础环境检查；AI provider key 缺失、Chromium/ChromeDriver/Xvfb 缺失 |
| 隔离启动线 | `news_sentry.cli serve` 在 `127.0.0.1:8010` 成功启动 |
| 真实数据只读线 | `./.venv/bin/python -m uvicorn ... --port 8011` 成功启动并可读取 repo `data/` |
| 前端静态检查 | `cd frontend/public && npm run test && npm run lint` 通过 |
| 截图证据 | `docs/deployment/audit-assets/20260614-local-run/` |
| 安全扫描主报告 | `/tmp/codex-security-scans/NewsSentry/179bdede_20260614-043841/report.md` / `report.html` |

## 执行摘要

本地运行主链路是可跑通的，但当前“本地可运行”与“本地可稳定验证”之间仍有几处明显断层。最重要的不是服务起不来，而是：

- 启动入口存在口径分裂：`.venv/bin/uvicorn` 脚本入口已失效，但 `python -m uvicorn` 仍可正常工作。
- `news-sentry serve` 默认强制打开自动采集，不适合挂在现有 `data/` 上做只读审计。
- 公共站点契约不一致：`/api/v1/public/news` 的 `detailUrl` 仍返回 legacy hash 路由，而当前 public app 实际使用 `/public-app/events/...`。
- 监控兼容性不足：`GET /public-app/` 返回 `200`，但 `HEAD /public-app/` 返回 `404`。
- 本机代理环境会污染本地验证基线，当前默认 `curl` 不再稳定复现假 `503`，但仍能看见代理相关响应头，不能作为最干净的本地验证路径。

从产品体验看，隔离数据空态、真实数据 feed、详情页都能渲染，没有在本轮浏览器检查里观察到前端白屏或控制台报错；因此这轮更像“运行口径和验证口径问题”，而不是“前端无法用”。

## 后续修复状态

> 2026-06-14 后续更新：以下问题已在当前工作树修复并完成回归验证，但本报告保留最初审计事实作为原始记录。

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| `HEAD /public-app/` 返回 `404` | 已修复 | 复验 `curl --noproxy '*' -I http://127.0.0.1:8010/public-app/` 返回 `200` |
| `/api/v1/public/news` 的 `detailUrl` 仍是 legacy hash | 已修复 | 复验 `curl --noproxy '*' 'http://127.0.0.1:8011/api/v1/public/news?page_size=1' | jq '.items[0].detailUrl'` 返回 `/public-app/events/...` |
| 同机反代误配下 `local` 免登录 fail-open | 已修复 | 复验 `NEWSSENTRY_DEPLOYMENT_ENV=vps` 进程上的 `GET /api/v1/status` 未认证返回 `401` |
| 改密/删用户后旧 session 仍有效 | 已修复 | 新增 API 回归测试，旧 token 在变更后返回 `401` |
| SSE 把主 bearer 放进 query string | 已修复 | legacy shell 改为先换取短期 `stream_token`，SSE route 不再接受 bearer query token |
| 目标页桌面布局未按预期全宽展开 | 已修复 | 新截图 [布局修复后目标页](audit-assets/20260614-local-run/04-target-feed-after-layout-fix.png) |

## 运行矩阵

| 线路 | 命令 | 结果 | 备注 |
| --- | --- | --- | --- |
| Python dry-run | `./.venv/bin/python -m news_sentry.cli run --target italy --stage collect --profile local-workstation --dry-run` | 通过 | CLI 基础运行入口正常 |
| 隔离启动线 | `./.venv/bin/python -m news_sentry.cli serve --host 127.0.0.1 --port 8010 --target italy --stage collect --profile local-workstation --data-dir /tmp/news-sentry-audit-data --log-dir /tmp/news-sentry-audit-logs --no-browser --foreground` | 通过 | 适合验证服务能否起、空态页能否加载 |
| 真实数据只读线 | `NEWSSENTRY_AUTO_COLLECT=0 NEWSSENTRY_DATA_DIR="$PWD/data" ./.venv/bin/python -m uvicorn news_sentry.core.api_server:create_app --factory --host 127.0.0.1 --port 8011` | 通过 | 适合挂 repo 现有 `data/` 做读侧验证 |
| `frontend/public` 测试 | `npm run test` | 通过 | `6` 个 test files / `40` 个 tests 全绿 |
| `frontend/public` 类型检查 | `npm run lint` | 通过 | `tsc --noEmit` 通过 |

## 截图证据

| 编号 | 文件 | 说明 |
| --- | --- | --- |
| 01 | [隔离空态页](audit-assets/20260614-local-run/01-isolated-empty-state.png) | `8010` 隔离数据目录下的 public app 空数据态 |
| 02 | [真实数据 feed](audit-assets/20260614-local-run/02-real-data-feed.png) | `8011` 只读挂载 repo `data/` 后的 public app feed 首屏 |
| 03 | [真实数据详情页](audit-assets/20260614-local-run/03-real-data-detail.png) | `8011` 下 `/public-app/events/...` 详情页实际渲染 |

## 已确认问题

### LR-AUDIT-001: 本机代理环境会污染本地验证基线

| 字段 | 内容 |
| --- | --- |
| 症状 | 当前 shell 含 `all_proxy=socks5://127.0.0.1:10808`、`http_proxy=http://127.0.0.1:10808`、`https_proxy=http://127.0.0.1:10808`。默认 `curl` 这轮未稳定复现假 `503`，但响应里仍出现 `Proxy-Connection` 等代理痕迹。 |
| 复现命令 | `env | rg 'NO_PROXY|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy'`；对比 `curl http://127.0.0.1:8010/api/v1/health` 与 `curl --noproxy '*' http://127.0.0.1:8010/api/v1/health`。 |
| 当前证据 | 当前默认 `curl` 与 `--noproxy '*'` 都返回 `200`，但默认请求带代理相关头，说明它不是最干净的本地验证基线。更早一轮本地验证曾命中过代理假 `503`。 |
| 影响范围 | 所有本地 HTTP smoke、health check、脚本化回归和手工调试。 |
| 根因判断 | 当前 shell 全局代理未配套 `NO_PROXY`，本地回环流量是否被代理接管取决于具体客户端行为。 |
| 临时绕过 | 运行本地验证时统一使用 `curl --noproxy '*' ...`，或显式设置 `NO_PROXY=127.0.0.1,localhost`。 |
| 推荐修复 | 把 `NO_PROXY=127.0.0.1,localhost` 写进本地 runbook / 启动脚本示例，避免“本地起服务成功但 smoke 偶发假失败”。 |
| 验收命令 | `NO_PROXY=127.0.0.1,localhost curl -i http://127.0.0.1:8010/api/v1/health`；确认请求稳定返回 `200` 且不再依赖代理路径。 |

### LR-AUDIT-002: `.venv/bin/uvicorn` 入口脚本 shebang 已失效

| 字段 | 内容 |
| --- | --- |
| 症状 | `./.venv/bin/uvicorn` 的 shebang 仍指向旧工作区：`#!/Volumes/SSD/Code/06-dev-tools/NewsSentry/.venv/bin/python3`。 |
| 复现命令 | `head -n 1 .venv/bin/uvicorn` |
| 当前证据 | 直接执行 `./.venv/bin/uvicorn` 会报坏解释器；但 `./.venv/bin/python -m uvicorn ...` 能正常启动 `8011` / `8012`。 |
| 影响范围 | 按文档或肌肉记忆直接执行 `.venv/bin/uvicorn` 的所有本地 API 启动路径。 |
| 根因判断 | 仓库迁移/复制后，虚拟环境脚本入口没有重建，shebang 仍指向旧绝对路径。 |
| 临时绕过 | 本地 API 启动统一改用 `./.venv/bin/python -m uvicorn ...`。 |
| 推荐修复 | 在本地运行文档中明确“迁移仓库后需重建 `.venv`”；必要时在 `doctor` 或安装脚本里增加 shebang 漂移检测。 |
| 验收命令 | `./.venv/bin/python -m uvicorn news_sentry.core.api_server:create_app --factory --host 127.0.0.1 --port 8011` 成功；重建 `.venv` 后 `./.venv/bin/uvicorn --version` 正常。 |

### LR-AUDIT-003: `news-sentry serve` 不适合作为 repo 数据的只读审计入口

| 字段 | 内容 |
| --- | --- |
| 症状 | `serve` 启动时会强制设置 `NEWSSENTRY_AUTO_COLLECT=1`、`NEWSSENTRY_COLLECT_INTERVAL`、`NEWSSENTRY_TARGET_ID`，默认带自动采集副作用。 |
| 复现命令 | 查看 `src/news_sentry/cli/serve.py` 中 `os.environ["NEWSSENTRY_AUTO_COLLECT"] = "1"` 等赋值逻辑。 |
| 当前证据 | 本轮隔离启动线能安全验证服务启动，但如果直接对 repo `data/` 使用 `serve`，它会进入采集循环，不符合“只读审计”要求。 |
| 影响范围 | 所有希望“挂现有数据只读浏览”的本地排查和回归验证。 |
| 根因判断 | `serve` 的产品定位是本地常驻服务，不是“只读挂载模式”；当前没有单独的 read-only server 开关。 |
| 临时绕过 | 对 repo `data/` 的浏览一律使用 `NEWSSENTRY_AUTO_COLLECT=0` + `python -m uvicorn`。 |
| 推荐修复 | 增加显式只读模式，或至少在帮助/文档里写清 `serve` 会打开自动采集。 |
| 验收命令 | `NEWSSENTRY_AUTO_COLLECT=0 NEWSSENTRY_DATA_DIR="$PWD/data" ./.venv/bin/python -m uvicorn news_sentry.core.api_server:create_app --factory --host 127.0.0.1 --port 8011` 启动后只读浏览正常，且不触发采集。 |

### LR-AUDIT-004: `HEAD /public-app/` 返回 `404`，与 `GET /public-app/` 不一致

| 字段 | 内容 |
| --- | --- |
| 症状 | `GET /public-app/` 返回 `200 OK`，但 `HEAD /public-app/` 返回 `404 Not Found`。 |
| 复现命令 | `curl --noproxy '*' -i http://127.0.0.1:8010/public-app/`；`curl --noproxy '*' -I http://127.0.0.1:8010/public-app/` |
| 当前证据 | 本轮隔离启动线稳定复现。 |
| 影响范围 | 健康检查、CDN/缓存探针、某些只发 `HEAD` 的监控脚本。 |
| 根因判断 | public app 路由对 `GET` 做了 HTML 入口处理，但没有对 `HEAD` 提供等价响应。 |
| 临时绕过 | 监控侧先改用 `GET`。 |
| 推荐修复 | 为 `/public-app` / `/public-app/` 增加 `HEAD` 等价处理，至少返回与 `GET` 一致的 `200` 和缓存头。 |
| 验收命令 | `curl --noproxy '*' -I http://127.0.0.1:8010/public-app/` 返回 `200`。 |

### LR-AUDIT-005: public news API、文档和前端详情路由口径不一致

| 字段 | 内容 |
| --- | --- |
| 症状 | `/api/v1/public/news?page_size=1` 返回的 `detailUrl` 仍是 legacy hash 路由，如 `"/#/news/target/france/events/..."`；但当前 public app 页面实际生成并可访问的详情页是 `/public-app/events/...`。 |
| 复现命令 | `curl --noproxy '*' 'http://127.0.0.1:8011/api/v1/public/news?page_size=1' | jq '.items[0].detailUrl'`；浏览器打开 `http://127.0.0.1:8011/public-app/events/...`。 |
| 当前证据 | API 返回旧路由；截图 `03-real-data-detail.png` 和页面内“详情”跳转都已落在新路由。 |
| 影响范围 | API 消费方、SEO/GEO 输出、任何直接使用 `detailUrl` 的外部集成，以及 `docs/api-reference.md` 的契约可信度。 |
| 根因判断 | 页面层路由迁移到了 `/public-app/events/...`，但 API 输出字段尚未完全同步。 |
| 临时绕过 | 本地/前端验证以当前页面实际生成的新路由为准，不把 API `detailUrl` 当最终真值。 |
| 推荐修复 | 收敛 `detailUrl` 语义：`docs/api-reference.md`、`/api/v1/public/news` 和页面实际路由应一致；若保留 legacy 兼容字段，需显式分字段命名。 |
| 验收命令 | `curl --noproxy '*' 'http://127.0.0.1:8011/api/v1/public/news?page_size=1' | jq '.items[0].detailUrl'` 返回 `/public-app/events/...`。 |

### LR-AUDIT-006: `doctor` 暴露出两类真实缺口，但阻塞级别不同

| 字段 | 内容 |
| --- | --- |
| 症状 | `doctor` 中 `provider_check` 失败：未设置 `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`；`browser_bridge_check` 失败：缺 `Chromium`、`ChromeDriver`、`Xvfb`。 |
| 复现命令 | `./.venv/bin/python -m news_sentry.cli doctor --target italy` |
| 当前证据 | 本轮 `doctor` 稳定输出这两类 FAIL。 |
| 影响范围 | `provider_check` 影响 AI judge / enrichment 真调用；`browser_bridge_check` 影响 OpenCLI 浏览器桥接和部分富交互采集能力。 |
| 根因判断 | AI provider key 属于真实运行依赖；浏览器桥接栈属于可选增强能力，不影响基础 RSS/API/public app 本地读侧验证。 |
| 临时绕过 | 本轮只做 dry-run / 只读 public app / 非 AI smoke 时，可先忽略这两类缺口。 |
| 推荐修复 | 文档里明确分级：`provider_check` 是 AI 路径阻塞项，`browser_bridge_check` 是增强项；必要时把 `doctor` 输出也分成 required / optional。 |
| 验收命令 | AI 运行前：至少设置 `OPENROUTER_API_KEY`；浏览器桥接测试前：补齐 `Chromium`、`ChromeDriver`、`Xvfb` 或调整到支持的本地 profile。 |

## 非问题但已确认的正向事实

- `news_sentry.cli run ... --dry-run` 正常，说明 CLI 主入口、配置加载和 target 基础路径没有明显坏掉。
- 隔离启动线的空态页可正常渲染，说明静态资源与 public app HTML 入口能被 FastAPI 正常挂出。
- 真实数据只读线的 feed 和详情页都能渲染，说明在不触发采集的前提下，repo 现有 `data/` 足以支撑 public app 读侧浏览。
- `frontend/public` 的 `npm run test` 与 `npm run lint` 当前通过，说明本轮观察到的问题主要是运行口径和契约问题，而不是前端测试基线已坏。

## 安全扫描摘要

完整安全扫描产物位于：

- Markdown: `/tmp/codex-security-scans/NewsSentry/179bdede_20260614-043841/report.md`
- HTML: `/tmp/codex-security-scans/NewsSentry/179bdede_20260614-043841/report.html`

本轮保留了 3 条 reportable findings：

| 严重度 | Finding | 含义 |
| --- | --- | --- |
| Medium | Session tokens survive password reset and user deletion | 令牌被窃取后，密码修改或删除用户不会立刻失效旧 session，最长可保留 24 小时访问。 |
| Medium | Loopback auth bypass becomes remote auth bypass when deployment env is left at local | 若同机反代/Cloudflare Tunnel 场景下遗漏 `NEWSSENTRY_DEPLOYMENT_ENV`，远程请求可能落入本地免登录逻辑。 |
| Low | SSE bearer tokens are placed in query strings and written to access logs | legacy SSE 路径把 bearer 放进 URL 查询串，当前 uvicorn access log 会原样记录。 |

本轮未保留为最终 finding、但已明确审过的面包括：

- `auth/setup` 首次初始化路由：看起来像公开建管理员，但启动期 `_bootstrap_users()` 已先种下管理员，运行中返回 `409`，未构成真实 takeover。
- collector / OpenCLI 数字回环 SSRF 绕过：在 `local-workstation` 宽松 profile 下存在，但 `cloud-vps` 生产白名单不会接受这些 host，当前不按生产漏洞上报。
- Windows 安装器 PowerShell launcher 插值：需要同一安装者自己注入参数，未达到低权限/远程攻击面。

## 建议的修复顺序

1. **先修入口与契约问题**
   - `.venv/bin/uvicorn` 失效
   - `serve` 缺少只读模式
   - `detailUrl` / 页面路由 / 文档口径不一致

2. **再修监控与验证兼容性**
   - `/public-app/` 的 `HEAD` 支持
   - 本地 `NO_PROXY` 说明与脚本化 smoke 基线
   - `doctor` required / optional 分级

3. **并行安排安全修复**
   - session reset/delete 时的 session purge
   - `local` 免登录逻辑 fail-closed
   - SSE token 改为非 URL 载体或可安全暴露的短期 token

## 复验命令清单

```bash
./.venv/bin/python -m news_sentry.cli run --target italy --stage collect --profile local-workstation --dry-run
./.venv/bin/python -m news_sentry.cli doctor --target italy
```

```bash
curl --noproxy '*' http://127.0.0.1:8010/api/v1/health
curl --noproxy '*' http://127.0.0.1:8010/public-app/
curl --noproxy '*' -I http://127.0.0.1:8010/public-app/
```

```bash
NEWSSENTRY_AUTO_COLLECT=0 NEWSSENTRY_DATA_DIR="$PWD/data" ./.venv/bin/python -m uvicorn news_sentry.core.api_server:create_app --factory --host 127.0.0.1 --port 8011
curl --noproxy '*' 'http://127.0.0.1:8011/api/v1/public/news?page_size=1' | jq '.items[0].detailUrl'
```

```bash
cd frontend/public
npm run test
npm run lint
```
