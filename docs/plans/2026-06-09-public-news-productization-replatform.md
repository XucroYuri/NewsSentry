# 公共新闻产品化与前端重平台化实施计划

> 日期：2026-06-09  
> 状态：Phase 86 生产灰度已完成
> 关联：ADR-0027、`docs/specs/2026-06-09-public-news-product-experience-design.md`

## Summary

把 News Sentry 公共门户从“公开监控台”升级为“新闻情报阅读产品”。实施路径采用双轨迁移：保留现有 FastAPI 与后台 Vanilla JS，新增公共门户 React + shadcn/ui app，先消费现有 API，再补读者侧 presentation API，最后替换旧公共路由。

## Phase 81：文档与决策基线

- [x] 接受或修订 ADR-0027，明确公共门户可以试点 React + shadcn/ui。
- [x] 将 `docs/roadmap/public-news-productization-20260609.md` 作为下一阶段入口。
- [ ] 将当前 AIHOT 研究截图归档到 `docs/deployment/audit-assets/` 或新的 `docs/product/assets/`。
- [x] 明确旧公共门户仅作为过渡实现，不再继续做大规模 Vanilla JS 扩展。

验收：

- ADR、Spec、Plan、Roadmap 四层文档互相链接。
- 后续实现任务不再依赖对话记忆判断方向。

## Phase 82：公共展示 API 与视图模型

- [x] 在后端增加 `PublicNewsItem` presentation helper，不改变 `NewsEvent` 存储契约。
- [x] 扩展或新增 `GET /api/v1/public/news`，支持精选、全部、target、来源、分类、日期和搜索。
- [x] 扩展 `GET /api/v1/public/news/{event_id}`，返回读者侧详情字段。
- [x] 为 `GET /api/v1/public/news` 增加 `latestCursor`、`nextCursor`、`pollAfterMs`、`since_cursor` 和空更新响应，支持低负担增量轮询。
- [x] 支持 `ETag` / `If-None-Match` 或 `Last-Modified` / `304` 其中一种缓存协商，降低无新内容时的响应成本。
- [x] 增加来源 display helper，统一 `source_id`、`source_display_name`、来源类型和可信度标签。
- [x] 增加相关事件/讨论字段的降级策略：没有数据时返回 `0` 和空数组，不暴露异常。

验收：

- API 响应包含来源、原文 URL、摘要、推荐理由、标签、实体、相关事件数。
- 增量请求只返回新新闻；无新内容时返回空列表或 `304`，不重复发送整页数据。
- 公开 API 不返回内部路径、后台权限字段或未解释的 pipeline 参数。
- `tests/unit/test_api_server.py` 覆盖 presentation shape、cursor 更新、`304` 轻响应和详情字段。

## Phase 83：公共前端 app 骨架

- [x] 新增 `frontend/public/`，使用 Vite + React + TypeScript。
- [x] 安装 Tailwind、shadcn/ui、lucide-react，并生成基础组件。
- [x] 建立 `PublicNewsItem` TypeScript 类型和 API client。
- [x] 配置 build 输出到 FastAPI 可托管目录。
- [x] 更新 CSP、缓存、service worker 或 build manifest 策略，避免旧资源滞留。
- [x] CI 增加 `npm run lint`、`npm run test`、`npm run build`。

验收：

- 本地 `npm run build` 产出静态文件到 `src/news_sentry/static/public_app/`。
- FastAPI 能通过 `/public-app/` 托管新公共 app。
- 旧后台路由仍可访问，旧 `/` shell 不被新 app 替换。

## Phase 84：AIHOT 式新闻流 MVP

- [x] 首页默认展示精选新闻流，不再先展示目标宏观汇总。
- [x] 实现频道 tabs：精选、全部、目标、来源、态势、日报。
- [x] 实现新闻卡片：来源、时间、标题、摘要、标签、推荐理由、原文入口、详情入口。
- [x] 实现日期分组、搜索、分类筛选、加载更多。
- [x] 实现新闻流自动更新：按服务端 `pollAfterMs` 低频检查新新闻，页面隐藏时暂停，失败时退避。
- [x] 实现“有 N 条新动态”提示，用户确认后增量插入列表顶部，避免阅读位置被突然打断。
- [x] 移动端实现固定底部导航和筛选 sheet。
- [x] 桌面端实现全宽三栏：频道/筛选、主新闻流、趋势/来源摘要。

验收：

- 390x844 首屏能看到新闻标题和摘要。
- 1440x900 有效内容宽度不低于 1100px。
- 新闻卡片可点击原文和详情。
- 用户停留在首页或 target 新闻流时，新新闻可自动提示并增量进入列表，无需刷新页面。
- 页面不展示裸 `stage`、`target_id`、裸 `score` 作为主信息。

## Phase 85：详情、来源与日报闭环

- [x] 事件详情页展示完整摘要、原文标题、来源、推荐理由、实体、标签、相关事件。
- [x] 来源页展示来源简介、来源类型、最近新闻、来源健康的读者化状态。
- [x] 日报页按日期展示重点新闻、主题、风险、来源链接。
- [x] 相关事件模块展示同源事件、同主题事件和追踪链。
- [x] 复制摘要、查看原文、返回列表等操作使用统一组件反馈。

验收：

- 任意新闻都能形成“列表 -> 详情 -> 原文/相关”的闭环。
- 来源信息不只是 `source_id`，而是读者能理解的来源名称和上下文。
- 日报页不依赖后台登录。

## Phase 86：旧公共门户退场

- [x] 将旧 Vanilla JS 公共门户路由软切换到新公共 app。
- [x] 保留后台 Vanilla JS 路由与认证逻辑。
- [x] 旧 public CSS/JS 保留一轮兼容期，但不再作为公开入口继续扩展。
- [x] 更新 API/路线图文档、测试脚本和浏览器 QA 覆盖。
- [x] 生产灰度：先新路径验证，再切默认首页。

验收：

- `/#/news/feed` 或新的公开入口由新 app 承载。
- 旧后台管理页面无回归。
- 线上 health、CSP、静态缓存和浏览器 QA 全部通过。

Phase 86 生产灰度记录：

- `/public-app/` 是新公共门户 canonical 入口。
- `/` 仍返回 legacy shell；浏览器端根据 hash 将旧公开路由跳转到 `/public-app/`。
- `/#/admin*` 等后台 hash 路由不跳转。
- 生产代码 release SHA：`7bf1417fe8194c4f581865698656901a8ec06122`。
- 生产部署验证：health 正常，`news-sentry` / `cloudflared` / `x-ui` active，旧公开 hash 路由已跳转到新 app，后台 hash 路由仍进入 legacy 登录。
- 本轮不删除后台 Vanilla JS，不服务端替换 `/`。
- 已确认残留风险：生产浏览器经 Cloudflare 路径加载公开新闻仍存在 25-45 秒尾部延迟；下一阶段应优先做公开新闻 projection/cache 或轻量首屏 API 加速。

## 测试计划

### API

- `python -m pytest tests/unit/test_api_server.py -q`
- 新增公开新闻 API presentation shape 测试。
- 新增公开详情字段降级测试。
- 新增增量轮询测试：`since_cursor` 只返回更新新闻，无更新时返回空列表或 `304`，`pollAfterMs` 不低于最小间隔。

### Frontend

- `npm run lint`
- `npm run test`
- `npm run build`
- Playwright 覆盖：
  - 首页精选流 desktop/mobile。
  - target 新闻流 desktop/mobile。
  - 事件详情 desktop/mobile。
  - 来源页。
  - 日报页。
  - 首页/target 新闻流自动发现新内容，不刷新整页、不改变当前阅读位置。

### 静态安全

- `python tools/scan_sensitive_data.py`
- `git diff --check`
- CSP smoke：
  - 首页无 inline script violation。
  - 构建资源缓存策略可控。

## 风险与回退

| 风险 | 缓解 |
|---|---|
| 新构建链增加 CI 复杂度 | 公共 app 独立目录、独立命令，后台不受影响。 |
| React app 与旧 hash router 冲突 | 新公共 app 使用明确挂载前缀，灰度后再切默认入口。 |
| API 字段不足导致 UI 空洞 | Phase 82 先补 presentation API，再大规模 UI 实现。 |
| 实时更新增加服务器负担 | 第一阶段只做低频增量轮询、缓存协商、页面可见性暂停和错误退避。 |
| shadcn 组件变成通用模板感 | 只使用基础组件，业务样式由 News Sentry tokens 决定。 |
| 生产缓存残留旧公共资源 | 引入指纹文件名和短缓存迁移窗口。 |

## 文档更新要求

每个 Phase 完成时必须同步更新：

- 本计划的 checkbox。
- `docs/roadmap/public-news-productization-20260609.md` 状态表。
- 若改变技术边界，新增或修订 ADR。
- 若改变公共 API，更新 `docs/api-reference.md`。
