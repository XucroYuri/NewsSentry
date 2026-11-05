# Reader v1：原文与免费翻译旁路

Reader 是独立 Worker API。`READER_V1` 只有精确等于 `"1"` 才启用；生产、
preview、dev 的仓库配置均默认关闭。既有公开新闻接口、采集和研判链路不变，
不新增 D1 表、不持久化原文、不自动发布。本次交付仅提交代码与 draft PR。

## 生产启用硬门禁与 M1 威胁模型

**硬门禁：** Before setting `READER_V1=1` in production, M1 (DNS rebinding) must be fixed or explicitly signed off by Yuri.

**M1 状态（2026-11-05）：解析后拒绝非公网地址已实现；连接级 DNS rebinding
尚未完全封闭。生产仍保持 `READER_V1=0`，本次修复不授权开启生产旗或部署。**

URL 先经 WHATWG 规范化，拒绝所有 IPv4/IPv6 字面量主机，包括十进制、八进制、
十六进制 IPv4 变体与 IPv4-mapped IPv6。随后在目标 `fetch` 前调用
`assertPublicReaderUrl`，使用免费 1.1.1.1 服务的固定 DoH 端点
`https://cloudflare-dns.com/dns-query`，并行查询 A 和 AAAA：

| 请求链路 | 解析后校验位置 |
|---|---|
| preview 原文 | `fetchReaderResource` 每次抓取前，包括每一跳重定向 |
| image 图片 | HMAC 验签后，经同一个 `fetchReaderResource` 逐跳校验 |
| translate 远端 Magpie | 每次免费/闲置组 POST 前，先校验再构造含凭据、正文的请求 |

两种记录查询都必须成功，至少有一个终端地址，并且返回的全部地址必须公开。
允许单栈站点另一种记录为空；校验递归响应中的 CNAME 链和终端记录归属，
拒绝循环、不完整、歧义或异常响应。IPv4 拒绝私网、回环、链路本地、CGNAT、
未指定、文档、基准测试、多播和保留网段；IPv6 只接受 `2000::/3` 中的普通
全局单播地址，并排除 `2001::/23`、`2001:db8::/32`、`2002::/16`、
`3fff::/20`。因此 ULA、回环、链路本地、site-local、多播、IPv4-mapped/
compatible、NAT64 和 6to4 等特殊/转换地址也不会放行。此策略有意保守，
特殊用途公网地址可能被拒绝。

DoH 只发送域名和记录类型，不携带正文、Cookie 或 Authorization；禁止跟随解析器
重定向，不在应用或 HTTP 层缓存校验结果（递归解析器自身仍遵守 DNS TTL）。
每组 A/AAAA 共用 3 秒期限，并受原请求 10 秒/翻译 15 秒总期限约束；每个响应上限
64 KiB、64 条记录、8 跳 CNAME。遇到非公网地址返回 `400 UNSAFE_URL`；
超时、NXDOMAIN/SERVFAIL、无地址、截断、格式/HTTP/网络异常统一
`502 DNS_RESOLUTION_FAILED`，不请求目标。DNS 校验失败直接结束翻译请求，
不再尝试其他组或 Workers AI；普通提供商失败仍保留已有免费→闲置降级。
Magpie 重定向响应按失败处理，不向新目标转发凭据或正文。

既有本机开发例外保持不变：仅 `NEWS_SENTRY_ENVIRONMENT=dev` 下显式配置的
HTTP `localhost`、`127.0.0.1`、`[::1]` 可直连；公开域名即使在 dev 下也必须
经过 DoH，不能通过解析到环回来取得例外。preview/image 没有该例外。

**平台取舍与剩余门禁：** 使用 1.1.1.1 的域名端点，是因为 Workers 不支持直接
向 IP 地址执行普通 `fetch`。`cf.resolveOverride` 要求原 URL 主机和替代主机
都在本 zone 内，不能为任意新闻站点固定已校验的 IP；本次没有使用它。依据：
[1.1.1.1 DoH JSON API](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/)、
[Workers IP 限制](https://developers.cloudflare.com/workers/platform/known-issues/#fetch-to-ip-addresses)、
[resolveOverride 约束](https://developers.cloudflare.com/workers/runtime-apis/request/#the-cf-property-requestinitcfproperties)。

DoH 预检与实际 `fetch` 仍是两次独立解析，无法证明最终连接的 IP 与校验结果一致。
逐跳/逐次重查可以阻止本次查询已返回私网的域名，不能消除检查后换址的时间窗口，
也不将普通 Workers `fetch` 视作私网保护兜底。因此 M1 的解析校验部分已补齐，
完整 DNS rebinding 风险仍须通过连接固定/可信出站层消除，或由 Yuri 明确签字接受，
才可另行讨论生产启用。同源 Access 会话与图片 HMAC 不能替代上述约束。

## P2 阅读界面

公开前端新增 `/{locale}/reader/{articleId}?locale={locale}` 路由；嵌入模式自动带
`/public-app/` 前缀。壳层支持 zh/en/es/ar/fr/ja/de/it/pt/ko，使用本地 SVG 加短码，
语言自称作为 tooltip，无障碍名称同时包含短码。显式路径优先于 query；无显式语言时，
依次选择 localStorage 手动偏好、`navigator.languages`（兼容 `navigator.language`）中
首个支持的语种，最后回退 `en`。区域标签如 `zh-CN`、`pt-BR` 归一为语言码；
仅手动切换写入偏好。阿拉伯语壳层和正文均采用 RTL。

界面采用紧凑卡片壳层，正文沿用 Geist、70ch 最大行长和独立段距。默认译文，
可切回原文；加载时显示骨架并禁用语言/模式切换。翻译失败保留原文并提供重试，
图片失败保留占位和重试按钮。动效为 180–200ms，遵循 reduced-motion。

`VITE_READER_V1` 仅精确等于 `"1"` 才启用真实请求，缺省关闭；后端仍由
独立的 `READER_V1` 控制。所有新闻列表/卡片主入口均进入站内阅读器，保留返回
新闻流的筛选条件。关闭时显示未开放提示，不请求 Reader API；源站链接始终是
次要小链接，使用 `target="_blank" rel="noopener noreferrer"`。
新闻详情不再渲染库内 `full_content` 或热链原图；列表缩略图也只接受签名代理，
点击缩略图与卡片均进入 Reader。阅读器提供十语问题反馈入口。
真实 adapter 只调用同源 `/api/v1/reader/*`，使用 `credentials: "same-origin"`，
不接触模型凭据。Markdown 禁用原始 HTML，图片必须匹配响应中的同源签名
`proxyUrl` 白名单；不会自动回退到外媒原图。

本机可运行 `npm --prefix frontend/public run build` 和
`npm --prefix frontend/public run preview`，打开
`http://127.0.0.1:5174/zh/reader/demo?reader=mock&locale=zh`。
mock 仅允许 loopback 主机，按需加载虚构样稿，不调用外部模型或 API；
`readerState=image-fail|translate-loading|translate-unavailable|preview-unavailable`
可复现兜底状态。代理图成功状态需本地测试夹具响应，假签名不用于真实后端。
组件、路由和 adapter 契约检查使用 `npm --prefix frontend/public test`；
类型检查使用 `npm --prefix frontend/public run lint`。本次不启用实网 preview 或生产开关。

## 接口与会话

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| `POST /api/v1/reader/preview` | `{articleId?, url?}`，至少一个，优先 articleId | `{markdown, images, sourceUrl, lang, title, byline, publishedTime, contentHash, attribution}` |
| `GET /api/v1/reader/image?u=&s=` | 原图 URL 和 HMAC-SHA256 签名 | 支持的位图响应 |
| `POST /api/v1/reader/translate` | `{markdown, targetLang, contentHash, sourceLang?}`，兼容 text 别名 | `{translated, lang, cached, provider}` |

Preview/translate 要求 `Origin` 与请求 URL 完全同源，并且有有效的
`CF_Authorization` 用户 Cookie（或 Access edge 提供的已签用户 assertion）。
复用现有 `CF_ACCESS_AUD` / `CF_ACCESS_TEAM_DOMAIN` 验签配置；兼容已有
`NEWS_SENTRY_ACCESS_*` 别名。服务 principal 和任意自造 Cookie 均不能授权。

**现状裁定：** 既有 public GET API 是匿名接口，没有可复用的 public session。
本旁路复用已有 Access 用户会话；测试使用临时 RSA 密钥和假的 JWKS，
不关闭验签。接入时应只保护两个 POST 路径，图片路径保持由 HMAC 授权，
避免 Access edge 在浏览器无 Cookie 时提前拦截图片。部署仍需单独安排。

图片端点只信签名，Cookie 不授予访问权；签名错误时不请求上游。只转发
JPEG/PNG/GIF/WebP/AVIF，拒绝 SVG/HTML 类型，丢弃原站 Cookie，不透传用户
Cookie/Authorization。每次重定向重新检查 URL 和解析后的地址；拒绝内网 IP、特殊主机名、
非标准端口和非 HTTP(S) 地址。签名没有独立过期字段，轮换签名密钥会使旧 URL
失效。

错误统一为 `{error, code, message}`，使用 400/403/404/422/429/502/503。
无法提取正文返回 `422 EXTRACTION_FAILED`，message 保留原文链接供用户打开。

## 提取与边界

### 开源依赖核验（Step2b，2026-11-06）

版本以 `frontend/cloudflare/package.json` 为准；本次核对 `package-lock.json`、
已安装包的 `package.json` 和 LICENSE，三者一致。只通过 npm 管理，不 vendor。

| 依赖 | package.json 版本 | SPDX 许可证 | 职责与许可证原文 |
|---|---|---|---|
| `@mozilla/readability` | `0.6.0` | `Apache-2.0` | 正文与元数据提取；[LICENSE.md](https://github.com/mozilla/readability/blob/0.6.0/LICENSE.md) |
| `linkedom` | `0.18.12` | `ISC` | Workers 中的 DOM；[LICENSE](https://github.com/WebReflection/linkedom/blob/v0.18.12/LICENSE) |
| `turndown` | `7.2.4` | `MIT` | DOM 转 Markdown；[LICENSE](https://github.com/mixmark-io/turndown/blob/v7.2.4/LICENSE) |

**许可证口径修正：** Step2b 需求中把 linkedom 写为 MIT，但该版本安装包、
锁文件和 npm 发布元数据均声明 ISC，LICENSE 标题也是 `ISC License`，因此记录
实际许可证 ISC。此处只记录依赖许可证核验，不另作法律解释。

核验确认主路径为 `Readability.parse()` → DOM 清理 → `TurndownService`，
没有手写正文提取主路径。本次保留三库和所有版本；显式正文容器仍只用于回退。
翻译目标校验使用 `marked@18.1.3` 解析 Markdown，覆盖行内、引用式和自动链接，
避免模型改写签名图片地址后仍被缓存。
先 Readability 提取，再清理 DOM，并用 Turndown 转为 Markdown；Readability
失败时仅回退到显式 `article/main/[role=main]`，不足 120 字符则失败。

### Preview 输出

| 字段 | 行为 |
|---|---|
| `title` | Readability 标题，缺失时使用原文 `<title>` 或主机名 |
| `byline` | Readability 作者，去除首尾空白；缺失或使用显式容器回退时为 `null` |
| `publishedTime` | Readability 发布时间原值，去除首尾空白；缺失或回退时为 `null`；不猜测或重写日期、时区 |
| `markdown` | 清理后的正文 Markdown，保留段落、标题、引用、强调等结构；行内图片地址改为同源代理 |
| `images` | 去重的 `{src, alt?, proxyUrl}`；`src` 保留安全的原图绝对地址供来源核对，`proxyUrl` 用于展示 |

图片相对地址转为绝对地址，再改写为同源签名代理。正文上限 2 MiB、
图片 5 MiB、最多 40 个去重图片 URL，最多 3 次重定向，抓取期限 10 秒。
代理路径为 `/api/v1/reader/image?u=...&s=...`，`s` 是独立图片 secret 对
`reader-image-v1\n{src}` 的 HMAC-SHA256 小写 hex；签名端点沿用验签与出站检查。

`contentHash` 为规范化 Markdown 的 SHA-256 前 32 位小写 hex。规范化按顺序
把 CRLF/CR 转为 LF、去除每行末尾空格/Tab、连续三行及以上换行收为两行、
最后 trim。翻译输入必须与这个 hash 匹配；翻译页面中的图片签名 URL 保持不变。

已知边界：不执行网页脚本、不绕过付费墙或反爬；无法保证复杂表格、惰性图片、
动态页面或所有语言编码的还原。成功提取也可能是登录/拦截页，需人工核对
attribution/sourceUrl。Markdown 是非可信展示数据，后续 UI 渲染仍须使用
安全 Markdown 渲染器，禁用原始 HTML，并限制链接协议。

## Magpie 接线与成本边界

| 配置 | 作用与默认值 |
|---|---|
| `READER_V1` | 默认关闭，仅 `"1"` 开启三个端点 |
| `READER_IMAGE_SECRET` | 至少 32 字符的独立随机 secret，配置后才能 preview/代理图片 |
| `READER_TRANSLATIONS` | KV binding；没有绑定时翻译返回 503 |
| `MAGPIE_BASE_URL` | Magpie 根地址或 `/v1` 地址；代码追加 `/chat/completions` |
| `MAGPIE_API_KEY` | 可选 secret，只发给显式配置的 Magpie，不进入响应 |
| `MAGPIE_FREE_ONLY` | 仅 `"1"` 允许 Magpie 请求，代表运营方已核实服务端免费策略 |
| `MAGPIE_FREE_GROUP` | 显式配置、服务端审核过的免费 `group/...` |
| `MAGPIE_IDLE_GROUP` | 可选闲置组；免费组失败时只尝试一次 |
| `READER_WORKERS_AI` | 默认 `"0"`，可选最后兜底总开关 |
| `READER_WORKERS_AI_FREE_ONLY` | 默认 `"0"`，AI binding 另需经确认的免费预算限制 |

Workers 无法访问本机 `127.0.0.1:3425`。远端接线需提供可从 Worker 访问的公开
HTTPS Magpie URL，使用 secret/env 配置；不在仓库保存真实地址或密钥。
只有 `NEWS_SENTRY_ENVIRONMENT=dev` 时允许 localhost HTTP，供本机测试。
不能把 Worker 的本地环回地址当成这台机器的 Magpie。

Magpie 调用使用兼容的 `POST /v1/chat/completions`：
`model=显式免费组`、`stream=false`，附带
`metadata={cost_policy:"free-only",allow_paid_fallback:false}` 和
`X-News-Sentry-Cost-Policy: free-only`，每组请求期限 15 秒。
这些标记不是 Magpie 的计费强制机制：服务端两个组必须只含已确认的免费或
闲置配额路由，禁止再落入任何付费组；未完成审核时保持 `MAGPIE_FREE_ONLY=0`。
组名只接受 `group/...`，不使用默认模型、通用 provider chain 或 REST 付费凭据。

缓存 key 固定 `tr:{contentHash}:{targetLang}`，targetLang 规范为 BCP 47 标签，
TTL 为 7 天。KV 命中不请求 Magpie，免费/闲置组全失败后返回结构化错误。
空译文、未完整输出或变更图片/链接目标均不写缓存。损坏的 JSON 按未命中处理；
KV 不可读时先返回 503，避免请求反复直达上游。

Workers AI 只使用显式提供的已有 `AI` binding，两个开关都为 `"1"` 才可能调用
`@cf/meta/m2m100-1.2b`，并要求 sourceLang。仓库没有新增 AI binding，
没有进行任何真实模型请求。该模型本身有用量计费；两个开关不能强制限制账户
账单。若不能在账户侧保证免费额度用尽即拒绝调用，就保持关闭，使用 Magpie
失败后的 429/503。无需开通新付费通道。

## 本机验证与示例

CI 使用 Node 22。先在 `frontend/cloudflare/` 安装已锁定的依赖，全部命令只在本机
执行，不部署：

```bash
npm ci
npm test
npm run typecheck:reader

# 三类自编静态 HTML，经过真实提取库和 preview API，网络仅使用本地 stub。
node --experimental-strip-types --test --test-name-pattern='preview fixture' \
  tests/reader.test.mts

# 两种语言、缓存、免费→闲置降级：所有模型/网络响应均为本地测试 stub。
node --experimental-strip-types --test \
  --test-name-pattern='Magpie demonstrates|free group failure|Workers AI requires' \
  tests/reader.test.mts

# 与 CI 相同的离线打包；禁止省略 --dry-run。
WRANGLER_SEND_METRICS=false node_modules/.bin/wrangler deploy --env="" \
  --dry-run --outdir /tmp/ns-reader-worker-dry-run --containers-rollout none
```

`reader.test.mts` 还覆盖未启用、同源/会话拒绝、articleId 可见性、空正文和
Readability 异常回退、内网/重定向防护、图片验签、hash 不匹配、错误信封、
localhost 限制、缓存损坏和 KV 故障。测试断言中文和英文两种完整响应以及
`tr:{hash}:zh` / `tr:{hash}:en` 两个独立缓存项，不调用真实 Magpie。

Step2b 的 `frontend/cloudflare/tests/fixtures/reader/` 包含三类自编 HTML，
不抓取或复制站点正文：

| Fixture | 覆盖 |
|---|---|
| `news-site.html` | 新闻正文、meta 作者/发布时间、相对链接、引用、图片及导航清理 |
| `blog.html` | JSON-LD 博客作者/发布时间、标题/强调、相对图片 |
| `lazy-load.html` | `data-src` / `data-original` 恢复、协议相对图片、重复图去重、缺失作者/时间返回 `null` |

三类均断言标题、作者、时间、正文、图片清单、Markdown 中的签名代理以及 hash，
使用 Node `createHmac` 独立计算期望签名；不 mock Readability、linkedom 或 Turndown。
显式容器回退另断言作者与时间为 `null`。#77 MINOR-1 新增内网 CNAME 名称的
400/`UNSAFE_URL` 回归测试，确认现有行为已对齐，无需改变错误处理；
MINOR-2/3 仅补全量公网校验前提与 dev 直连例外的中文注释。

M1 测试使用本地 DoH 响应，覆盖 IPv4/IPv6 私网和特殊地址、公私混答、单栈/双栈、
CNAME、同主机重定向后换址、远端翻译重试前换址、DNS 超时/异常，以及拒绝时
目标请求数为零、翻译不写 KV、不调用兜底；这些结果不构成连接固定或线上验收证据。

### Step2b 延期清单

- M1 连接级 DNS rebinding 窗口仍按既有生产硬门禁处理，另行解决可信出站或签字；
  本次不放宽门禁。
- 扩展只在 `srcset` / `<picture><source>` 中提供的图片、脚本动态内容、
  复杂表格及付费墙，不在本次静态样例核验范围。
- 本地 `core.autocrlf=true` 会使 `db/schema.sql` 变为 CRLF，导致既有
  `public-read-window.test.mts` 的 `stage+published_at index serves the windowed count without a full pipeline_stage scan`
  LF 字符串断言失败。#77 已记录同一问题，本次不修改该测试、SQL 或 Git 配置；
  同时在禁用归档换行转换的 LF 副本验证全套 Workers 测试。

可读原文样例：`https://blog.cloudflare.com/workers-ai/`。
启动本机旁路时，可在被 Git 忽略的 `frontend/cloudflare/.dev.vars.dev` 中配置
测试用 Access 参数、独立图片 secret；翻译另需本机 KV binding 和经过审核的
免费组。不要提交这些值。然后：

```bash
node_modules/.bin/wrangler dev --env dev --local --port 8791 \
  --var READER_V1:1

# 另一个终端；session Cookie 文件由合法 Access 登录取得，不进仓库。
curl --fail-with-body http://localhost:8791/api/v1/reader/preview \
  -H 'Origin: http://localhost:8791' -H 'Content-Type: application/json' \
  --cookie /tmp/ns-reader.cookies \
  --data '{"url":"https://blog.cloudflare.com/workers-ai/"}' > /tmp/ns-reader-preview.json

jq '{markdown,contentHash,sourceLang:.lang,targetLang:"zh"}' \
  /tmp/ns-reader-preview.json > /tmp/ns-reader-translate.json
curl --fail-with-body http://localhost:8791/api/v1/reader/translate \
  -H 'Origin: http://localhost:8791' -H 'Content-Type: application/json' \
  --cookie /tmp/ns-reader.cookies \
  --data-binary @/tmp/ns-reader-translate.json
```

本机 Cookie 的 domain 必须匹配 localhost；真实生产域 Cookie 不会由 curl 自动
发送到 localhost。无测试会话时直接运行上面的 stub 测试，不跳过认证。
尚无公开 Magpie 时，503 是预期行为，可先交付 stub 证据和接线点。

隔离 KV 接线示意（由后续 preview 部署单独准备，本次不创建资源）：

```toml
[[env.preview.kv_namespaces]]
binding = "READER_TRANSLATIONS"
id = "<已有且隔离的 preview KV ID>"
```

Preview vars 和 secrets 需在相同环境显式配置；`READER_V1`、Magpie 免费组、
Access 参数和图片 secret 缺一则保持受控错误。回退时将 `READER_V1=0`，
三个端点在认证/数据库/网络前统一返回 404，既有公开接口继续沿原链路服务。

在公开页面调用时使用相对 `/api/v1/reader/*`，浏览器会自动提供 Origin；
`news-sentry.com` 页面向 `api.news-sentry.com` 发起 POST 属于跨 origin，会被拒绝。
Reader 返回的 Markdown 包含相对图代理地址；浏览器示例应使用同源基地址解析。
