# Public-App 首屏延迟审计报告

> 生成时间：2026-06-24 | 基线 commit: `8004f20e`

## 1. 现象与对比

| 页面 | 首次打开（冷） | 后续访问（热） |
|------|-------------|-------------|
| `/public-app/` | 慢，用户感知"几十秒" | 正常 (HTML 缓存 300s + JS/CSS immutable) |
| `/admin/` | 秒开 | 秒开 |

**差异化根因**：`/admin/` 走 `_index_html_response()`——纯读静态 `index.html`，替换 nonce 即返回，无任何数据查询。`/public-app/` 走 `public_app_index()`——需在返回 HTML 前执行 3 个数据查询（news + regions + facets）并注入 bootstrap JSON。

---

## 2. 完整请求链路与时间分布

### 阶段 0：网络层 (CDN → 后端)

```
DNS 解析 news-sentry.com → TCP → TLS 1.3 → HTTP/2
```
- 冷 DNS: 50-200ms | 热 DNS: 0ms (缓存)
- TCP + TLS: 1-2 RTT，取决于用户到服务器的物理距离
- Cloudflare CDN 如果命中 HTML 缓存 (max-age=300)：直接返回，跳过阶段 1

### 阶段 1：后端路由处理 (FastAPI)

```
GET /public-app/ → public_app_index(request)
│
├─ _public_site_base_url(request) ......... ~0.01ms (读 env/header)
│
├─ _ssr_bootstrap_json_impl() ............. ⚠️ 核心阻塞
│  ├─ _public_news_feed_payload_for_bootstrap()
│  │  ├─ 缓存命中 → ~0.1ms (dict lookup)
│  │  └─ 缓存 miss → 扫描 SQLite event_index 表，排序/过滤
│  │     └─ 延迟取决于: data_dir 下事件总量、索引质量、磁盘 I/O
│  ├─ _cached_public_regions()
│  │  ├─ 缓存命中 → ~0.1ms
│  │  └─ 缓存 miss → 枚举所有 target dirs + 查 event_index
│  └─ _cached_public_facets()
│     ├─ 缓存命中 → ~0.1ms
│     └─ 缓存 miss → _public_news_candidate_events() 聚合扫描
│
│  三个查询已并行化 (asyncio.gather)，耗时 = max(三者)
│
├─ _public_app_index_response()
│  ├─ 读 index.html ....................... <1ms (本地磁盘)
│  ├─ _inject_public_homepage_seo() ....... <1ms (字符串匹配/替换)
│  ├─ 注入 bootstrap JSON <script> ....... <1ms (字符串拼接)
│  └─ _inject_script_nonce() .............. <1ms (正则替换)
│
└─ 返回 HTMLResponse (含 Cache-Control: max-age=300)
```

**关键指标**：

| 场景 | 数据查询耗时 | 总后端耗时 |
|------|------------|----------|
| 全缓存命中 (热) | <1ms | <5ms |
| 部分缓存 miss | 取决于 DB | 100ms - 3s |
| 全部缓存 miss (冷启动) | 取决于 DB | 500ms - 10s+ |

> **剩余风险**：如果 `_public_news_candidate_events` 在没有合适索引的情况下扫描数万条事件，单次查询可能耗时数秒。这是 SQLite 层的性能瓶颈，独立于 HTTP 缓存体系。

### 阶段 2：HTML 传输

- 基础 HTML: ~1.6KB
- SEO 注入: ~2KB (canonical + og:url + JSON-LD)
- Bootstrap JSON (内联): 50-130KB（取决于 regions 数量 + 20 条新闻详细度）
- **总 HTML 体积: 约 55-135KB (gzip 约 18-40KB)**
- Cache-Control: `public, max-age=300, s-maxage=300, stale-while-revalidate=600`

### 阶段 3：浏览器解析 + 资源加载

```
浏览器接收 HTML
├─ 解析 HTML → 发现 <link rel="stylesheet"> → 下载 CSS (28KB / gzip 6KB) ← 阻塞渲染
├─ 解析到 <script id="news-sentry-bootstrap" type="application/json">
│  └─ 不会执行（type=application/json），仅 DOM 数据存储
├─ 解析到 <script type="module" src="index-xxx.js"> (374KB / gzip 116KB)
│  └─ type=module 是 defer 语义：等 DOM 解析完再执行
│
时间线:
├─ HTML 首字节 (TTFB) ............. T0
├─ HTML 下载完成 .................. T0 + (HTML大小/带宽)
├─ CSS 下载 + 解析 ................ T0 + 100-500ms
│  └─ 浏览器在此刻可能绘制首帧（白色背景）
├─ JS 下载 (.js 116KB gzip) ....... T0 + 300-2000ms
├─ JS 解析/编译 ................... +50-200ms
└─ React 渲染 → 首屏可见内容 ..... +50-300ms
```

**静态资源缓存策略**：

| 资源 | 文件名 | Cache-Control | 有效期 |
|------|--------|--------------|--------|
| CSS | `index-BJdCfOcD.css` | `max-age=31536000, immutable` | 永远（content hash） |
| JS | `index-CszjvnyK.js` | `max-age=31536000, immutable` | 永远（content hash） |

### 阶段 4：React 应用初始化 (SSR 命中场景)

```
main.tsx → createRoot → <App/>
├─ useHashRoute() ................ <1ms (读 window.location)
├─ usePublicBootstrap(filters)
│  ├─ readSSRBootstrap() ......... <1ms (读 DOM JSON)
│  ├─ SSR 匹配 → status="ready" ... 跳过 API fetch ✅
│  └─ setState 初始化渲染
├─ usePublicFeed(initialFeed=ssrNews, waitForBootstrap=false)
│  └─ 直接用 initialFeed 渲染新闻列表 ✅
├─ usePublicTargets(bootstrapTargets, waitForBootstrap=false)
│  ├─ 设置 initialTargets ......... 立即可见
│  └─ 后台 fetch /api/v1/regions .. 静默刷新（不阻塞）⚠️ 多余请求
├─ usePublicFacets(bootstrapFacets, waitForBootstrap=false)
│  ├─ 设置 initialFacets ......... 立即可见
│  └─ 后台 fetch /api/v1/public/facets .. 静默刷新（不阻塞）⚠️ 多余请求
└─ 渲染完成 → 首屏内容可见
```

### 阶段 5：轮询 (后台)

```
usePublicFeed (poll: true)
├─ 初始 delay: pollAfterMs=120_000 (2分钟)
├─ 首次 poll 在 2 分钟后
├─ 失败退避: 2^failureCount × base (上限 5 分钟)
└─ 暂停条件: 页面不可见或离线
```

---

## 3. 已完成的优化 (本 session + 上次 session)

| # | 优化项 | Commit | 效果 |
|---|--------|--------|------|
| 1 | SSR bootstrap 数据注入 HTML | `1ab857c5` | 首帧零 API 请求 |
| 2 | filter-aware SSR 数据读取 | `e16840d4` | 仅 featured 默认首页复用 SSR |
| 3 | 模块级 IIFE DOM 解析 | `6157048a` | 避免重复 DOM 查詢 |
| 4 | Bootstrap 端點缓存 TTL 60→300s | `1ab857c5` | 减少源站負载 |
| 5 | `asyncio.gather` 并行化三查询 | `c219a58b` | 缓存 miss 时减少 60-70% 等待 |
| 6 | HTML shell 缓存对齐 300s | `c219a58b` | 后续访问秒开 |
| 7 | 轮询间隔 30→120s | `1ab857c5` | 减少后台请求 75% |
| 8 | StrictMode 恢复 | `8004f20e` | 开发时副作用检测，生产零开销 |

---

## 4. 残留问题与风险

### 4.1 Bootstrap JSON 体积无控制

Bootstrap JSON 包含：
- `regions.regions[]`：全量地区（每个有 display_name, source_count, event_count 等 8+ 字段）
- `news.items[]`：20 条完整新闻（每条含 source 嵌套、tags 数组、entities 数组等）
- `facets.regions[] / issues[] / related[]`：全量聚合计数

**风险**：如果线上有 30+ 个地区，新闻条目内容详细，HTML 可能膨胀到 150KB+，首次下载时间显著增加。

**建议**：生产环境通过 DevTools 检查实际 HTML 体积。如果 >100KB，考虑创建 bootstrap 精简版 schema（只保留首屏必需字段）。

### 4.2 usePublicTargets / usePublicFacets 的冗余请求

SSR 命中时，bootstrap 已提供 targets 和 facets 数据。但 hook 中的 effect 在 `waitForInitialData` 变为 false 后仍会发起 API fetch：
- `listTargets()` → `/api/v1/regions?include_empty=true`
- `listPublicFacets()` → `/api/v1/public/facets`

这是**后台静默请求**，不阻塞渲染，但浪费带宽。targets 在 SSR 数据中已有全量，facets 在 SSR 数据中也已有。

**修复方向**：在 hook 中增加 `didConsumeSSR` 标记（类似 `usePublicBootstrap` 已做的那样），跳过 SSR 已提供的数据的重复 fetch。

### 4.3 SQLite 查询延迟 (最深瓶颈)

`_public_news_candidate_events` 是数据查询的底层入口。在没有合适索引的情况下，扫描大量事件需要全表遍历。性能特征：
- 小数据量 (<1000 条)：<50ms
- 中数据量 (1 万-5 万)：100ms - 1s
- 大数据量 (>10 万)：可能数秒

**观察点**：日志中 `X-Public-Timing-News` 头显示的 `elapsed_ms` 值。如果经常 >500ms，说明查询层是瓶颈。

### 4.4 部署层延迟

| 因素 | 影响 |
|------|------|
| Cloudflare CDN 缓存命中 | 跳过源站，HTML 直接返回 |
| VPS 到中国大陆网络 | 取决于线路质量 |
| Docker 容器内磁盘 I/O | SQLite 在容器内性能 |

---

## 5. 优化路线图 (按投入产出比排序)

### P0 — 立即生效 (已完成)
- [x] SSR bootstrap 数据注入 + 前端消费
- [x] 并行化后端查询
- [x] HTML/API 缓存策略对齐
- [x] 轮询间隔延长

### P1 — 低成本高收益
- [ ] **为 `usePublicTargets` 和 `usePublicFacets` 添加 SSR 跳过逻辑** — 1 行改动的 hook 层优化，消除冗余请求
- [ ] **监控生产 HTML 体积** — 线上用 `curl -s https://news-sentry.com/public-app/ | wc -c` 确认实际大小

### P2 — 需要投入
- [ ] **Bootstrap JSON 精简 schema** — 创建 `PublicBootstrapSlim` 模型，只序列化首屏必需字段
- [ ] **SQLite 查询性能审计** — 检查 `event_index` 表是否存在适合公开查询的复合索引

### P3 — 长期优化
- [ ] Service Worker 预缓存 HTML shell
- [ ] `preload` / `modulepreload` 优化 JS 加载瀑布
- [ ] 考虑 CDN edge 层做 bootstrap 数据缓存 (Cloudflare Workers KV)

---

## 6. 快速自检命令

```bash
# 查看生产 HTML 体积
curl -s -o /dev/null -w '%{size_download} bytes\n' https://news-sentry.com/public-app/

# 查看后端耗时
curl -sI https://news-sentry.com/public-app/ | grep -i 'x-public-timing\|cache-control'

# 冷启动 (绕过 Cloudflare 缓存)
curl -sI -H "Cache-Control: no-cache" https://news-sentry.com/public-app/ | grep -i 'x-public-timing'
```
