# Reader v1：原文与免费翻译旁路

Reader 是独立 Worker API。`READER_V1` 只有精确等于 `"1"` 才启用；生产、
preview、dev 的仓库配置均默认关闭。既有公开新闻接口、采集和研判链路不变，
不新增 D1 表、不持久化原文、不自动发布。本次交付仅提交代码与 draft PR。

## 接口与会话

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| `POST /api/v1/reader/preview` | `{articleId?, url?}`，至少一个，优先 articleId | `{markdown, images, sourceUrl, lang, title, contentHash, attribution}` |
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
Cookie/Authorization。每次重定向重新检查 URL；拒绝内网 IP、特殊主机名、
非标准端口和非 HTTP(S) 地址。签名没有独立过期字段，轮换签名密钥会使旧 URL
失效。

错误统一为 `{error, code, message}`，使用 400/403/404/422/429/502/503。
无法提取正文返回 `422 EXTRACTION_FAILED`，message 保留原文链接供用户打开。

## 提取与边界

安装依赖：`@mozilla/readability@0.6.0`、`linkedom@0.18.12`、
`turndown@7.2.4`，只通过 npm 管理，不 vendor。
翻译目标校验使用 `marked@18.1.3` 解析 Markdown，覆盖行内、引用式和自动链接，
避免模型改写签名图片地址后仍被缓存。
先 Readability 提取，再清理 DOM，并用 Turndown 转为 Markdown；Readability
失败时仅回退到显式 `article/main/[role=main]`，不足 120 字符则失败。
图片相对地址转为绝对地址，再改写为同源签名代理。正文上限 2 MiB、
图片 5 MiB、最多 40 个去重图片 URL，最多 3 次重定向，抓取期限 10 秒。

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
npm run typecheck:reader

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
