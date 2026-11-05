# PR #79 Cross-family review
- Reviewer: Codex Magpie group/moe-master
- Date: 2026-11-06T01:22:11+08:00
- Scope: feat/p2-reader-ui-20261105 vs hotfix/e130570-reconcile @ 2a9daa0

## Verdict
PASS-WITH-NOTES

## BLOCKER
- none

## MAJOR
- none

## MINOR
- **R1 — 原文及翻译失败回退时，正文方向可能与正文语言相反。** `frontend/public/src/components/reader/ReaderBody.tsx:72` 使用界面 `locale` 决定 `dir`，但 `lang` 使用实际正文 `language`。`frontend/public/src/components/reader/ReaderPage.tsx:54` 在原文模式和翻译失败时传入源语言。因此英文界面阅读阿拉伯语原文时生成 `lang="ar" dir="ltr"`，影响段落、列表及混合标点的方向。建议正文按实际内容语言决定方向，壳层继续按界面语言决定，并覆盖原文切换及翻译失败场景。
- **R2 — adapter 初始化状态的阿拉伯语壳层缺少语言和方向属性。** `frontend/public/src/components/reader/ReaderPage.tsx:165` 的加载/模块加载失败分支没有 `lang`、`dir`，直接进入阿拉伯语路由时不能保证 RTL；mock 模块加载失败时该状态还会持续。建议与同文件 `:158` 的关闭状态一致，为此分支设置 `lang={route.locale}` 和对应 `dir`，补充加载及失败状态断言。

## Notes
- **范围核验：** 本地基线及 merge-base 均为 `461eb082ebf8a1fac433834df009c7c1700b87b9`，HEAD 为 `2a9daa022507932648a4503bc5433eef4c55254f`。`/tmp/pr79.diff` 与该范围的 Git diff 在排除 `index` 行哈希缩写长度差异后完全一致；范围内只有一个新增提交。
- **R1/R2 复现与正常路径：** 使用现有组件进行内存式 TSX/JSDOM 检查。英文路由、`article.lang="ar"`、翻译返回 503 时，实际 DOM 为壳层 `lang="en" dir="ltr"`、正文 `lang="ar" dir="ltr"`，且阿拉伯语原文可见。初始化分支渲染为 `<main class="reader-shell" role="status">جارٍ تحميل النص الأصلي…</main>`。正常阿拉伯语译文路径的 document、壳层、正文均为 RTL；关闭状态壳层也为 RTL。十种语言字典的键集合一致，路径语言优先于 query，区域标签和浏览器偏好选择符合现有实现。证据：`frontend/public/src/components/reader/ReaderPage.tsx:93`、`:114`、`:158`、`:165`；`frontend/public/src/components/reader/ReaderBody.tsx:72`；`frontend/public/src/lib/reader/locales.ts:17`；`frontend/public/src/lib/reader/routes.ts:14`；`frontend/public/src/lib/reader/messages.json:1`。
- **XSS：** 未发现本次改动引入的高置信度 XSS。正文使用 `marked.lexer` 后按允许的 token 创建 React 节点，原始 HTML 和未知 token 被丢弃，没有把文章 HTML 交给 `dangerouslySetInnerHTML`。`textarea.innerHTML` 仅接收正则匹配的单个实体，解码结果作为文本节点输出；链接解码后再限制协议及凭据，外链带 `noopener noreferrer`。14 个原始/编码 HTML、脚本协议和非许可图片载荷检查通过。证据：`frontend/public/src/components/reader/ReaderBody.tsx:9`、`:22`、`:35`、`:55`；`frontend/public/src/lib/reader/adapter.ts:3`。
- **图片与 SSRF：** 正文图片须同时满足同源、固定代理路径、签名格式和响应图片清单匹配；失败占位不会回退到原始 `src`。真实 adapter 使用同源固定 POST 路径、`credentials: "same-origin"`、`redirect: "error"`。客户端的签名格式检查不等于验签：服务器在出站前验证 HMAC，再执行 URL/逐跳 DNS 校验；四类伪造私网图片请求在 fetch 前被拒绝，且私网 URL 无法取得签名。证据：`frontend/public/src/lib/reader/adapter.ts:14`、`:43`、`:58`；`frontend/public/src/components/reader/ReaderBody.tsx:40`；`frontend/public/src/components/reader/ProxyImage.tsx:10`；`frontend/cloudflare/workers/lib/reader-image.ts:19`、`:26`；`frontend/cloudflare/workers/lib/reader-http.ts:204`。基线已有的连接级 DNS rebinding 剩余风险仍由 `docs/reader-v1.md:54` 记录；本次前端检查没有消除它，也不构成生产启用批准。
- **localStorage 隐私：** 本次 Reader 新增持久化仅为手动选择的 `news-sentry-reader-locale`，不保存正文、译文、文章 URL 或凭据；自动语言选择不写入存储，存储不可用时有异常兜底。译文缓存留在组件内存。证据：`frontend/public/src/lib/reader/locales.ts:22`、`:35`；`frontend/public/src/components/reader/ReaderPage.tsx:39`、`:103`。内存检查确认自动选择和文章加载未新增存储项，手动选择仅产生语言键。
- **旗帜与许可证：** 目录恰有 `cn/de/es/fr/gb/it/jp/kr/pt/sa` 十枚 SVG，与十语映射一致，使用本地资源，无旗帜 CSS/运行时图库依赖。已与 npm 官方 registry 的 `flag-icons@7.5.0` 发布包进行内存字节比对：10/10 SVG 和 LICENSE 完全一致，发布元数据为 MIT；保留 Panayiotis Lipiridis 版权及完整许可文本。SVG XML 检查未发现脚本、事件处理属性或外部资源引用。证据：`frontend/public/public/flags/README.md:3`；`frontend/public/public/flags/LICENSE:1`；`frontend/public/public/flags/`；`frontend/public/src/lib/reader/locales.ts:1`；`frontend/public/src/components/reader/LocaleChips.tsx:24`；`frontend/public/package.json:12`。
- **生产默认关闭：** `frontend/cloudflare/wrangler.toml:26`、`:105`、`:142` 的 production/preview/dev 均为 `READER_V1 = "0"`；`frontend/cloudflare/workers/api/reader.ts:78` 在认证、数据库和出站操作前要求精确 `"1"`。前端 `frontend/public/src/lib/reader/routes.ts:5` 同样仅接受 `VITE_READER_V1 === "1"`，mock 只允许 loopback；`frontend/public/src/components/reader/ReaderPage.tsx:146`、`:156` 在关闭状态不创建真实 adapter。检查确认缺省、`"0"`、`"true"`、带空白值及生产 query 覆盖均保持关闭，关闭页面零 fetch。`.github/workflows/deploy.yml:991` 的公开前端构建未设置启用旗。本结论覆盖仓库默认配置与代码门禁，未读取线上实际变量。
- **提交 trailers：** 对本地 PR 范围执行 `git log origin/hotfix/e130570-reconcile..HEAD` 并读取完整消息及解析后的 trailers。唯一提交 `2a9daa0` 的 co-author 为 Claude Code；没有 Cursor/Grok trailer，author/committer 字段也没有这些标识。
- **验证边界：** `frontend/public` 下执行 `node node_modules/typescript/bin/tsc --noEmit --incremental false`，退出码 0。上述定向检查仅在内存转译现有模块，HTTP 使用替身，旗帜上游比对仅做只读下载；未运行完整 Vitest 套件、未部署、未修改应用源码。
