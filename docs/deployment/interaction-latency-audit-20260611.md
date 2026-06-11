# News Sentry Phase 89 交互响应延迟审计

## 审计元信息

- 日期：2026-06-11
- 生产站点：`https://news-sentry.com`
- 生产 SHA：`c3535c300ca1ba3eda2c647b545909ccf363ae9b` (`fix: constrain public filter lists`)
- 本阶段目标：拆解部署交互慢的真实链路，并做低风险前端请求治理；不替换 `/` 服务端入口，不删除 legacy shell，不改变公开 API JSON shape。

## 基线证据

| 检查项 | 观测值 | 结论 |
| --- | --- | --- |
| VPS 本机 `GET /api/v1/health` | 约 3ms | 服务进程本身健康 |
| VPS 本机 `GET /api/v1/targets` | 约 48ms | 目标列表不是瓶颈 |
| VPS 本机 `GET /api/v1/public/targets/italy/analysis?days=14` | 约 70ms | analysis 聚合不是稳定瓶颈 |
| VPS 本机 `GET /api/v1/public/news?featured=true&page_size=20` | 常规 miss 约 0.9-1.94s，hit 约 0-4ms | feed miss 仍是首屏主要后端成本 |
| 分类筛选尾部 | 曾观测到 `category=politics` miss 约 12.2s，复测回落到约 0.9s | 存在偶发尾部，需要连续采样关联资源争用 |
| 浏览器 `/public-app/` | 首条新闻约 4.0-4.2s 可见 | 冷启动 HTML/JS + feed miss 叠加 |
| 详情页 | 约 2.85s ready | 详情页同步等待相关新闻 `page_size=50` |
| SQLite 只读采样 | Italy 2054 条索引：count 约 8ms，list 约 5ms | SQLite 查询本身不是主要瓶颈 |
| `news-sentry-realtime.timer` | 每 3 分钟 + 0-60 秒抖动，单轮常消耗 34-38s CPU | 可能和偶发 feed 尾部争用 CPU/I/O |

### 2026-06-11 公网只读采样

| 请求 | 响应头/耗时 | 结论 |
| --- | --- | --- |
| `GET /api/v1/health` | `{"status":"ok"}` | 生产健康检查正常 |
| `GET /api/v1/public/news?featured=true&page_size=20` 第 1 次 | `X-News-Sentry-Feed-Cache: miss`，`X-News-Sentry-Feed-Elapsed-Ms: 1041`，公网 `time_total=2.447535s` | feed miss 服务端投影约 1s，公网端到端约 2.45s |
| 同一 public feed 第 2 次 | `X-News-Sentry-Feed-Cache: hit`，`X-News-Sentry-Feed-Elapsed-Ms: 0`，公网 `time_total=1.325142s` | 进程内 TTL cache 生效；剩余公网耗时主要是网络/TLS/边缘路径 |

## 根因分层

1. **前端首屏重复请求**：`App` 在初始 route hydration 时把等价 `filters` 重新写入 state，`usePublicFeed` 依赖对象身份，导致同一 `/api/v1/public/news?featured=true&page_size=20` 初次请求出现两次。
2. **右栏 analysis 猜测目标**：feed 页在第一条新闻尚未返回时使用 `targets[0]` 作为 `selectedTargetId`，可能先请求无关 target analysis，再切到第一条新闻 target。
3. **详情主内容被相关信号阻塞**：`EventDetailPage` 先等待 `getPublicNewsItem()`，再等待 `listPublicNews({ pageSize: 50 })`，最后才把详情置为 ready。
4. **feed miss 仍有后端成本**：Phase 88 后 feed 已具备短 TTL cache 和 index-first 路径，但 all-target feed 仍按 target 遍历、构造展示字段并读取 source config cache；常规 miss 在 1-2s 区间。
5. **运行时资源争用风险**：实时采集 timer 高频运行，单轮 CPU 时间较高。当前资源快照健康，但需要用连续采样确认 API 尾部是否与采集窗口重叠。

## 本分支低风险修复

- `frontend/public/src/App.tsx`
  - 为 `FeedFilters` 增加等价判断，避免初始 route hydration 重复触发同一 feed 请求。
  - 拆分 feed 页目标与 analysis 页目标：feed 页只在 `filters.targetId` 或首条新闻 target 已知后请求右栏 analysis；analysis 页面仍可使用显式 route target 或目标列表 fallback。
- `frontend/public/src/pages/public-pages.tsx`
  - 详情页在主详情返回后立即渲染正文。
  - 相关新闻改为异步补齐；失败或慢返回不影响正文 ready。
- `tools/public_app_latency_check.mjs`
  - 新增真实浏览器测速脚本，覆盖 desktop/mobile、first article、detail ready、初始 feed 请求次数、移动底栏 fixed、console/page error。

## 后续观测计划

- 连续 30-60 分钟采样：
  - `GET /api/v1/public/news?featured=true&page_size=20`
  - `GET /api/v1/public/news?featured=true&page_size=20&category=politics`
  - `systemctl list-timers news-sentry-realtime.timer`
  - `journalctl -u news-sentry-realtime --since ...`
- 如果 feed 尾部与 realtime 采集重叠：
  - 优先降低实时采集频率或错峰，而不是给 API 引入重型缓存层。
  - 可评估 `CPUWeight`/`Nice`/`IOSchedulingClass` 限制采集任务对 Web API 的影响。
- 如果前端修复后 all-target feed miss 仍超过 3s：
  - 再评估跨 target public feed projection 或减少 `COUNT(*)` 的 SQL 路径。

## 验收标准

- `/public-app/` 初始 feed 请求数为 1。
- feed 页在首条新闻 target 未知前不请求 `targets[0]` 的 analysis。
- 详情页主内容不等待相关新闻请求完成。
- 浏览器 QA：冷态首条新闻 ≤ 5s，热态 ≤ 3s，详情主内容 ≤ 1.5s，无 console/page error，移动底栏 fixed。
- API smoke：public feed hit/miss headers 保留，不暴露路径、token、data_dir。

## 建议命令

```bash
cd frontend/public
npm run test
npm run lint
npm run build
```

```bash
NODE_PATH=/tmp/news-sentry-pw/node_modules \
node tools/public_app_latency_check.mjs \
  --base-url https://news-sentry.com \
  --out /tmp/news-sentry-public-app-latency-phase89
```

```bash
curl -fsS https://news-sentry.com/api/v1/health
curl -sS -D - -o /dev/null 'https://news-sentry.com/api/v1/public/news?featured=true&page_size=20'
```
