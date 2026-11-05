# PR #76 代码审查 — Reader 原文 / 签名图代理 / 免费翻译旁路

- **审查者模型**：Claude（Opus 4.8，`remote-magpie/auto/claude-opus-4-8`）
- **审查范围**：`git diff 14dbb70..6aef195`（行号按 `6aef195`）
- **审查方式**：只读。未改动任何代码，未 commit / push / 部署。独立完成，未委派任何 subagent / GPT / moe-master。
- **验证**：在 Node v24.22.1 下运行 `tests/reader.test.mts`，**22/22 全部通过**。

---

## BLOCKER

无。

核心安全不变量（flag 默认关闭、同源 + Access 会话校验、HMAC 常量时间验签、重定向逐跳重校验、翻译免费回落不触付费链）在代码与测试中均成立，不存在必须阻断合并的缺陷。

---

## MAJOR

### M1. DNS rebinding：`readerUrl` 只校验主机名字符串，不解析 DNS，平台 fetch 不兜底私网
- **文件:行号**：`frontend/cloudflare/workers/lib/reader-http.ts:24`（`readerUrl`）、`:101` 与 `:108`（`fetch` / 逐跳重定向）
- **问题**：`readerUrl` 对十进制 / 八进制 / 十六进制 IPv4（`127.1`、`0x7f.1`、`2130706433`）依赖 WHATWG `URL` 的规范化后再做点分四段正则，这一层是有效的（已验证 `http://127.1` → `127.0.0.1` 被拦）；IPv6 经 `host.startsWith("[")` 整类拒绝；RFC1918 / 100.64/10 / 169.254 / 224+ / 0.x / 255.255.255.255 的 octet 判定也完整。**但所有判断都作用于“主机名字符串”**。攻击者控制的公网域名 `attacker.com` 若 DNS 解析到 `127.0.0.1` / 云 metadata / Cloudflare 内网，`readerUrl` 全部放行，随后 `fetch(sourceUrl)` 在请求时才解析 DNS。
  代码注释（`reader-http.ts:23`「Workers 的外部 fetch 网络边界进一步隔离私网」）所依赖的平台兜底**并不存在于普通 `fetch`**：据 Cloudflare 文档，SSRF 防护只覆盖 VPC binding 与直连 IP 的 TCP socket；`global_fetch_strictly_public` 兼容标志仅禁止 fetch Worker 自身 zone，不拦任意私网 IP。`wrangler.toml` 也未设置该标志。逐跳重定向虽每跳重过 `readerUrl`（已验证 302→`169.254.169.254` 被拦），但校验与 `fetch` 之间 DNS 可再解析，仍是同一根因。
- **降级理由（为何是 MAJOR 而非 BLOCKER）**：三个端点均先过 `requireReaderSession`（同源 + 已验签 Access **user** 会话，`reader.ts:85`），攻击面仅限已授信编辑用户；且字符串层 IP/IPv6 拦截已就位。属于纵深防御缺口，非匿名可达漏洞。
- **建议**：引入“解析后再校验”的一跳：在 `fetch` 前对主机名做 DNS 解析（Workers 无原生 resolver，可用 `1.1.1.1` DoH 查 A/AAAA），对解析结果复用现有 octet/IPv6 判定；或接受残余风险但**把 `reader-http.ts:23` 的注释改为如实描述**（平台不兜底、依赖 Access 授信边界），避免后续维护者误以为有平台防线而放松校验。至少应在 `docs/reader-v1.md` 的威胁模型中显式记录此残余风险。

---

## MINOR

### m1. `allow_paid_fallback: false` / `cost_policy: free-only` 为单向声明，依赖上游 Magpie 自觉
- **文件:行号**：`frontend/cloudflare/workers/lib/reader-translate.ts:84`、`:90`
- **问题**：“免费回落”在 Worker 侧已尽力（`MAGPIE_FREE_ONLY==="1"` 门禁、`model` 固定为审核过的 `group/` 路由、header 与 metadata 双重声明、Workers AI 需双开关 + 显式 `AI` binding、未引用任何既有付费 provider key）。但 `allow_paid_fallback: false` 仅是请求体里的提示，真正是否产生费用取决于 Magpie 端是否尊重该字段；Worker 无法强制。
- **建议**：功能上可接受（已是 Worker 侧能做到的上限）。建议在 `docs/reader-v1.md` 注明“免费保证依赖 Magpie 侧正确路由 `group/` 与遵守 `free-only`”，并确保 `MAGPIE_FREE_GROUP` / `MAGPIE_IDLE_GROUP` 配置的 group 在 Magpie 侧确为零计费，避免口径误解。

### m2. 翻译 TTL 下限与 `expirationTtl` 的平台约束
- **文件:行号**：`frontend/cloudflare/workers/lib/reader-translate.ts:185`
- **问题**：`expirationTtl: 7 * 24 * 3600`（604800s）远高于 Cloudflare KV 的 60s 下限，无问题。此处仅提示：KV `expirationTtl` 不接受 <60，当前常量安全；若未来改为可配置须加下限校验。非本 PR 缺陷。
- **建议**：无需改动；留档以防后续参数化时踩坑。

### m3. 图片代理端点无会话校验（仅 HMAC）——确认为有意设计，建议补文档断言
- **文件:行号**：`frontend/cloudflare/workers/api/reader.ts:79`、`frontend/cloudflare/workers/lib/reader-image.ts:26`
- **问题**：`/api/v1/reader/image` 在 `requireReaderSession` 之前返回（`reader.ts:79-81`），因此不要求 Access 会话，仅靠 HMAC 验签。这是让 `<img>` 标签能直接加载所必需的，且签名不可伪造（需 ≥32 字节 secret），响应头 `Cache-Control: private`、`CORP: same-origin`、`CSP: default-src 'none'; sandbox`、`nosniff` 均到位，上游 `Set-Cookie` 已被剥离（测试 `reader.test.mts:177` 覆盖）。风险仅限“已签名 URL 泄露 → 他人可拉取该单一图片”，被每-URL HMAC 限定，可接受。
- **建议**：无需改码。建议在 `docs/reader-v1.md` 明确写下“image 端点为 HMAC-only、有意绕过会话”，与 `architecture.md` 已有的「图片仅 HMAC」一致，避免被当作鉴权缺失误报/误改。

### m4. 测试工具链要求 Node ≥22.7，本机默认 Node 20 无法运行
- **文件:行号**：`frontend/cloudflare/package.json:9`（`test` 脚本用 `--experimental-strip-types`）、`tests/reader.test.mts:4`（`import ... "node:sqlite"`）
- **问题**：`--experimental-strip-types` 需 Node 22.6+，`node:sqlite` 需 Node 22.5+。本机默认 `node` 为 v20.20.2，直接 `npm test` 会失败；须用 Node 24（已用 v24.22.1 验证 22/22 通过）。
- **建议**：在 `package.json` 增加 `"engines": { "node": ">=22.7" }` 或在 `docs/reader-v1.md` / CI 配置中显式声明所需 Node 版本，避免本地/CI 因 Node 版本漂移静默跳过 reader 测试。

---

## 五处重点结论

1. **SSRF / 私网绕过** — 字符串层防护**充分**：十进制/八进制/十六进制 IPv4 经 `URL` 规范化后被点分四段正则拦截；IPv6（`[::1]`、`[::ffff:7f00:1]`）整类拒绝；localhost/internal 等特殊名、非标准端口、RFC1918/CGNAT/link-local/组播/全零/广播均被拦；重定向**逐跳**重过 `readerUrl`（302→metadata 被拦，已测）。**唯一缺口是 DNS rebinding**（见 M1）：主机名层校验无法防公网域名解析到私网，且所依赖的“平台 fetch 兜底”实际不存在。因受 Access 会话门禁，判为 MAJOR。

2. **HMAC** — **正确**。验签顺序合理：先 `/^[a-f0-9]{64}$/` 格式校验（`reader-image.ts:31`），再 `crypto.subtle.verify`（常量时间，`:33`）；签名载荷带版本前缀 `reader-image-v1\n` 防跨用途；签名侧对 `readerUrl(src)` 规范化后再签，验签侧 payload 与之一致。图片代理无“过期”概念（HMAC 绑定 URL 而非时间），对本用例合理——签名 URL 永久有效但只放行单一已校验图片 URL，可接受。篡改 `u`、删除 `s` 均返回 403（已测 `reader.test.mts:190-194`）。

3. **Access JWT 校验** — **正确且严格**。`alg` 强制 `RS256`（头部 `:280` 与 JWK `:234` 双重约束，防 alg 混淆 / `none`）；要求 `kid`；`iss`/`aud`/`exp`/`nbf` 全校验，`exp <= now` 判过期（`access-jwt.ts:181`），`nbf` 类型异常也拒；JWKS 走规范化 team domain（强制 `.cloudflareaccess.com`、`https`、无 userinfo/query/fragment/非根路径，`:85-103`）并带 5min 缓存;签名用 `RSASSA-PKCS1-v1_5`+SHA-256 经 WebCrypto `verify`（常量时间）；`reader.ts:29` 额外要求 `principal.kind === "user"`，service token 不可访问 reader。未见可绕过项。

4. **READER_V1=0 时无副作用** — **成立**。`handleReader` 首行即 `if (env.READER_V1 !== "1") throw 404`（`reader.ts:77`），在认证、D1、任何 `fetch` 之前返回。测试 `reader.test.mts:66`「flag off hides every reader endpoint before auth, DB, or network」断言三端点（preview/translate/image）均 404 且 `calls == []`（零网络）。`wrangler.toml` prod/preview/dev 三环境均 `READER_V1 = "0"`。

5. **translate 缓存键与不付费回落** — **正确**。缓存键 `tr:${contentHash}:${targetLang}`（`reader-translate.ts:137`）：`contentHash` 已通过 `markdownHash(规范化 markdown)` 服务端重算校验（`:132-134`，拒伪造），`targetLang` 经 `Intl.getCanonicalLocales` 规范化；**`sourceLang` 不入键是安全的**——源字节已由 `contentHash` 唯一确定，同一源文不可能是两种源语言。命中仅回传契约字段（`internal` 被剔除，已测 `:405`）。不付费回落链条完整：Magpie `free-only` 门禁 + 固定审核 `group/` 路由 → Workers AI（双开关 + 显式 `AI` binding，免费 m2m100）→ 不触任何既有付费 provider key；空/截断/改动图链的译文不写 KV（已测 `:308`、`:368`）。残余点见 m1（上游自觉）。

---

BLOCKER=0 MAJOR=1 MINOR=4
