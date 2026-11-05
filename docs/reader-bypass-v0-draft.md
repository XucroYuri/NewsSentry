# Reader v0 — draft / 旁路 / 非生产默认

本变更仅注册 Cloudflare Worker 边缘 API，用于 DSH 对照验收。不切换公开阅读器、不更改生产 provider、cron、collect 或 NewsEvent，不部署、不 merge、不 push。类型位于 `frontend/cloudflare/workers/lib/reader-contracts.ts`，与现有 `contracts.ts` 邻近；它们是独立请求/响应 DTO，不是新的领域对象。

## 开关与边界

- `READER_ENABLED` 必须严格等于字符串 `true`，否则三个端点都返回 503。仓库不设置启用默认值。
- `READER_ALLOWED_HOSTS` 为逗号分隔的可信公共主机名，精确匹配，无通配符。preview 和 image 缺少白名单返回 503；仅允许 HTTPS 默认端口，拒绝 URL 凭据、IP 字面量、本地主机和所有重定向。
- `READER_IMAGE_SIGNING_SECRET` 从 Worker env 读取；启用后缺配置返回 503，绝不降级为裸代理。密钥仅通过部署环境配置，不能进前端、日志或仓库。
- fetch 不转发用户 Cookie/Authorization，超时 10 秒；正文抓取最多 1 MiB，图片最多 5 MiB，POST body 最多 128 KiB。错误使用 `lib/errors.ts` 格式。

## 契约

| 端点 | 输入 | 输出 |
| --- | --- | --- |
| `POST /api/v1/reader/preview` | `{url}` 或 `{sourceUrl}`，同时存在时 url 优先 | `{markdown, images: string[], sourceUrl, lang, title?, contentHash, attribution, provider:"lightweight"}` |
| `POST /api/v1/reader/translate` | `{text, targetLang, contentHash?}` 或 `{markdown, targetLang, contentHash?}`，text 优先 | `{translated, lang, cached, provider:"stub"}` |
| `GET /api/v1/reader/image` | query `url`, `expires`, `sig` | 已签名图片字节；缺签名/错签名/过期均 403 |

preview 支持 HTML、Markdown 和纯文本。HTML 优先选 article/main，移除常见脚本、样式和导航块，生成轻量正文；Markdown/纯文本直通。images 是解析为绝对地址的 HTTP(S) 原始图片 URL，不是签名代理地址。lang 优先取 HTML lang，否则粗分 zh/en/und。contentHash 是返回正文 UTF-8 的 SHA-256 小写十六进制。

translate 是**不执行真实翻译**的确定性 stub：`[stub:<小写目标语言>]\n<原文>`。不调用外部翻译服务或付费模型。缓存为单 isolate 内存 Map，TTL 5 分钟、最多 64 条；冷启动或换 isolate 会 miss。键由实际正文、目标语言、stub 版本计算，不信任客户端 contentHash；cached 仅表示此次命中内存缓存。

## 图片签名协议

受信任服务端使用 HMAC-SHA256，签名消息为以下三行（UTF-8，无末尾换行）：

```text
reader-image-v0
<expires>
<url>
```

`expires` 为 10 位 Unix 秒，必须晚于当前时间且不超过未来 3600 秒；`sig` 为 64 位小写十六进制。`url` 必须与 query 解码后的完整字符串一致。用 URLSearchParams 编码 query，签名时不要先做 URL 规范化。校验使用 Web Crypto verify；验证成功后仍检查主机白名单。只接受 JPEG/PNG/GIF/WebP/AVIF MIME，拒绝 SVG；响应不转发上游头并设置 nosniff、private/no-store。v0 不提供公共签名签发接口，preview 不泄露密钥或生成签名。

## 验证

```bash
cd frontend/cloudflare
npm test
# 只跑旁路契约
node --experimental-strip-types --test tests/reader.test.mts
```

测试使用 node:test 和本地 fetch mock，无外部网络、API key 或持久存储依赖，覆盖 preview shape、markdown 别名、translate cached/缓存隔离、image 签名成功及缺失/篡改/过期拒绝、默认关闭、白名单、重定向、MIME 和体积限制。

本次 Node 24 验证：旁路 10/10；LF 临时副本全量 156/156；reader handler 及契约通过 TypeScript noEmit 检查。原工作区 `core.autocrlf=true`，全量为 155/156：既有 `public-read-window.test.mts:167` 按 LF 字符串断言 SQL 索引，CRLF 签出导致失败。已确认相关文件规范化换行后与基线一致，未修改原 SQL 或测试。

## 剩余风险 / 生产前置条件

轻量 HTML 抽取不是完整 DOM/Readability，也不是 XSS sanitizer；消费方渲染 Markdown 时必须禁用原始 HTML 或做成熟的消毒处理。语言识别很粗略，非中文可能标为 en。图片仅校验 MIME，不做图像解码验证。

主机白名单必须由管理员限定为可信公共站点；这里不做 DNS 解析后 IP 校验，不能将用户自控域名加入白名单。启用后端点未新增用户鉴权或限流；正式对外开放前需加 Access/配额、DNS/出口防护与真实翻译 provider 验收。单 isolate 缓存不保证跨实例命中。本次验收只证明离线契约与拒绝路径，不构成生产发布验证。
