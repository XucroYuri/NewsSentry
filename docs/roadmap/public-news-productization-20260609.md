# 公共新闻产品化下一阶段文档体系

> 日期：2026-06-09  
> 状态：下一阶段入口文档  
> 目的：把公共门户大规模迭代沉淀为仓库文档体系，而不是停留在 Agent 记忆或一次性对话计划。

## 1. 主判断

News Sentry 当前公开站点的问题不是局部样式问题，而是产品面和技术面共同进入新阶段：

- 产品面：需要从“监控/采集汇总”转向“新闻情报阅读”。
- 信息面：需要形成新闻来源、摘要、推荐理由、原文、详情、关联事件的闭环。
- 布局面：需要真正全宽响应式，而不是窄屏页面居中。
- 技术面：公共门户继续堆 Vanilla JS/CSS 会加重维护负担，需要组件化与类型化。
- 运行面：用户停留页面时应自动看到新采集/新增强的信息，不需要手动刷新，但实现必须控制请求频率和服务器负担。

下一阶段以公共门户产品化为主线，后台管理页保留现状。

## 2. 文档地图

| 层级 | 文档 | 作用 |
|---|---|---|
| ADR | `docs/adr/adr-0027.md` | 决定公共门户是否允许 React + shadcn/ui 试点。 |
| Spec | `docs/specs/2026-06-09-public-news-product-experience-design.md` | 定义新闻产品体验、信息架构、视图模型和验收标准。 |
| Plan | `docs/plans/2026-06-09-public-news-productization-replatform.md` | 定义 Phase 81-86 的实施顺序和测试计划。 |
| Roadmap | 本文档 | 作为下一阶段入口、状态表和文档治理规则。 |
| Superpowers 入口 | `docs/superpowers/specs/2026-06-09-public-news-product-experience-design.md`、`docs/superpowers/plans/2026-06-09-public-news-productization-replatform.md` | 让 Superpowers 工作流能稳定找到本阶段文档，不复制正文。 |

实现者入口顺序：

1. 先读本文档。
2. 再读 ADR-0027，确认技术边界。
3. 再读产品 Spec，确认用户体验目标。
4. 最后按实施 Plan 拆任务执行。

## 3. 参考产品研究

参考站点：`https://aihot.virxact.com/`

AIHOT 的可学习点：

- 首屏直接展示内容流。
- 信息组织围绕“精选/全部/日报/分类/搜索”。
- 每条内容都有来源、标题链接、摘要、标签和推荐理由。
- 分数存在但不是唯一主角。
- 关联讨论补充可信度和热度。
- 移动端仍保持内容流，而不是仪表盘。

News Sentry 不复制 AIHOT 视觉皮肤，只学习新闻消费路径和信息组织。

## 4. 阶段状态表

| Phase | 名称 | 状态 | 核心出口 |
|---|---|---|---|
| Phase 81 | 文档与决策基线 | Done | ADR/Spec/Plan/Roadmap 成体系，ADR-0027 已接受。 |
| Phase 82 | 公共展示 API 与视图模型 | Done | 读者侧 presentation API、详情字段和轻量增量更新能力已完成后端窄测。 |
| Phase 83 | 公共前端 app 骨架 | Done | 新增 `/public-app/` 灰度入口，Vite React + shadcn/ui 静态构建可由 FastAPI 托管。 |
| Phase 84 | AIHOT 式新闻流 MVP | Done | 首页/target 直接展示完整新闻流，支持筛选、加载更多和低负担增量提示。 |
| Phase 85 | 详情、来源与日报闭环 | Done | 新闻可从列表进入详情、原文、来源和日报。 |
| Phase 86 | 旧公共门户软退场 | In Progress | 旧 `/#/news/*` 公开路由在客户端跳转到 `/public-app/`；后台 hash 路由保留。 |

## 5. 产品原则

1. 内容优先：首屏先展示新闻，不先展示采集系统状态。
2. 来源可信：每条新闻必须清楚显示来源和原文入口。
3. 理由可读：AI 研判转化为推荐理由，不展示模型内部参数。
4. 分析后置：趋势、实体、统计是阅读后的分析层，不是首页主角。
5. 全宽响应：桌面充分利用空间，移动保持单列内容流。
6. 组件化优先：公共门户新 UI 优先使用成熟组件体系。
7. 后台隔离：公共产品化不混入后台管理重构。
8. 低负担实时：新信息自动出现，但通过增量轮询、缓存协商、可见性暂停和退避控制成本。

## 6. 技术原则

- FastAPI 仍是 API 与静态托管层。
- CLI-first 核心不变。
- `NewsEvent` 存储契约不因 UI 重构改变。
- 公开 API 使用 presentation shape，隔离读者字段与工程字段。
- 公共门户可以引入 React + TypeScript + shadcn/ui。
- 新闻流实时更新优先使用 cursor 增量轮询，不默认引入 WebSocket/SSE。
- 管理后台暂不迁移，避免范围爆炸。

## 7. 文档治理规则

后续所有公共门户大改必须落到文档：

- 技术边界变化：新增或修订 ADR。
- 用户体验变化：更新 Spec。
- 实施任务变化：更新 Plan checkbox。
- 阶段状态变化：更新本文档状态表。
- API shape 变化：同步 `docs/api-reference.md`。
- 部署/缓存/CSP 变化：同步 `docs/deployment/` 相关文档。

禁止只在 Agent 记忆或对话里保存关键决策。

## 8. 下一步

建议下一轮执行：

1. 基于 Phase 86 本地结果执行生产前 smoke：health、CSP、缓存头、Cloudflare、冷加载浏览器矩阵。
2. 生产灰度时先保留 `/public-app/` canonical 入口和 legacy shell 客户端跳转，不直接删除旧公共代码。
3. 灰度稳定后再评估是否服务端替换 `/` 入口，以及何时清理旧 Vanilla JS 公共门户模块。
