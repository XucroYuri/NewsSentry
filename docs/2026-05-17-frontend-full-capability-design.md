# News Sentry 前端完整能力打通设计规格

> 日期: 2026-05-17
> 范围: 认证 + Pages 部署 + 导航重构 + 功能补齐 + 状态可视化 + Bug 修复 + 长期增强

---

## 1. 目标

将 News Sentry 从「需要直接访问容器才能用的技术工具」转变为「通过 news-sentry.com 即可使用的完整新闻情报平台」，覆盖 44/44 API 端点，实现傻瓜化操作。

## 2. 设计决策摘要

| 决策 | 选择 | 理由 |
|------|------|------|
| 认证方案 | 用户自带 Key + Token 认证 | A+B 混合连接设置，API Key 换短期 Token，不存原始 Key |
| 部署架构 | Cloudflare Pages 独立部署 | CDN 加速，容器内 StaticFiles 保留作后备 |
| 导航架构 | 三层渐进式披露 | 降低认知负荷：看→管→配 |
| 状态可视化 | 纯 CSS 动效 | 零 JS 开销，5 种 keyframes |
| 国际化 | i18n 对象抽取（中英双语） | 为多语言打基础 |
| 补充功能 | 日期过滤/网络检测/导出分享/快捷键 | 长期运行必需 |

## 3. 认证系统

### 3.0 认证模型：用户自带 API Key

News Sentry 的认证模型不是「平台发放 Key」，而是「用户自带 Key」：

- **当前阶段**：用户使用自己的 API Key（如 NEWSSENTRY_API_KEY，由部署者/管理员提供）连接到后端
- **Phase 2**：每个用户拥有独立的 API Key，Key 关联到具体用户身份和角色
- **Phase 3（商业化）**：用户自带的 Key 包括第三方服务密钥（Anthropic/OpenAI 等），平台按用户维度管理多个 Provider Key
- **前端设计原则**：连接设置页始终允许用户输入自己的 Key，不预设「平台发放」的心智模型

### 3.1 连接设置页（首次访问）

- 未检测到 `localStorage.ns_connection` 时显示全屏连接设置页
- 包含：
  - **用户名**：用于标识操作者（Phase 2 扩展为完整用户账户）
  - **服务器地址**（默认 `https://news-sentry.xuyu.workers.dev`）
  - **API Key** 输入框（由用户提供，非平台发放）
- 「验证并连接」按钮：
  1. 调用 `POST /api/v1/auth/token` 用 API Key 换取短期 Token
  2. 调用 `GET /api/v1/auth/me` 获取用户信息
  3. 成功：Token + 用户信息存入 `localStorage`，跳转新闻情报概览
  4. 失败：显示错误提示，允许重试

### 3.2 Token 认证机制

- **不直接存储原始 API Key**，而是换取短期 Token（TTL 24h）
- 后端新增端点：
  - `POST /api/v1/auth/token` — API Key → 短期 Token（JWT 或随机 Token）
  - `GET /api/v1/auth/me` — 返回当前用户信息 `{username, role, permissions}`
- Token 过期后前端自动重新认证（用户无感知，使用原 Key 换新 Token）
- `localStorage.ns_connection` 存储：`{server, token, username, expiresAt}`

### 3.3 连接状态

- 侧边栏底部固定显示：
  - 连接状态圆点（绿色=正常，蓝色闪烁=运行中，红色=异常）
  - 当前用户名
  - 上次采集时间文字
  - 「设置」链接（打开连接设置弹窗）
  - 微型心跳条（音频柱动效）

### 3.4 API 请求封装

- `api.js` 的 `api()` / `apiPost()` 等函数自动：
  - 从 `localStorage.ns_connection` 读取 server 和 token
  - 附加 `Authorization: Bearer {token}` header
  - 401 响应时自动尝试用原 Key 换新 Token（一次重试）
  - 换 Token 失败则跳转连接设置页
  - 5 秒超时 + 2 次重试（仅 GET）
  - 网络错误时侧边栏状态变红，不清空已加载内容

### 3.5 安全增强

- **前端速率限制**：请求队列最多 5 个并发；写入操作 300ms 防抖；触发类操作 5s 冷却期
- **XSS 防护**：所有动态内容通过 textContent 而非 innerHTML 渲染；URL 参数严格校验；Worker 层注入 CSP header
- **操作日志**：关键操作（触发采集、修改配置、导入事件、清理数据）记录到 localStorage，格式 `{timestamp, action, target, user, result}`，设置页可查看最近 100 条
- **维护操作二次确认**：prune/backup/trigger 均需确认弹窗，显示影响范围

### 3.6 多用户演进预留

- `localStorage.ns_user` 存当前用户名，Phase 2 扩展为完整 user 对象
- 侧边栏用户区域预留「计划」标签位（Phase 3 商业化）
- auth 模块设计为可替换：Phase 2 扩展 login/logout/register，Phase 3 接 OAuth
- 后端 audit API 预留：前端操作日志格式直接兼容后端存储

## 4. 导航架构

### 4.1 三层渐进式披露

**第一层「看」— 每日工作台（默认展开）**

| 入口 | 图标 | 徽标 | Tab 子页 |
|------|------|------|----------|
| 新闻情报 | 📰 | 新事件数 | 概览 / 事件 / 追踪链 / 实体 / 趋势 |
| 告警通知 | 🔔 | 未读告警数 | 实时告警 / 历史记录 |

**第二层「管」— 系统管理（始终可见）**

| 入口 | 图标 | Tab 子页 |
|------|------|----------|
| 运行监控 | 📊 | 运行状态 / 采集器 / 信源健康 / 运行历史 / 数据维护 |
| 反馈优化 | 💬 | 反馈记录 / 规则优化 |

**第三层「配」— 高级配置（默认折叠）**

| 入口 | 图标 | Tab 子页 |
|------|------|----------|
| 配置中心 | 🔧 | 目标 / 信源 / 过滤规则 / 输出 / AI 设置 / Webhook |

### 4.2 导航交互

- 点击第一/二层入口：主内容区显示对应 Tab 页
- 第三层默认折叠，点击「展开配置中心」后展开子项
- 面包屑导航：深层次页面（事件详情、链详情、运行详情）显示路径
- 上下文跳转：事件详情 → 追踪链 / 实体 / 告警，无需回侧边栏
- 徽标每 30 秒自动刷新（调用 stats + alerts/smart）

## 5. 各页面详细功能

### 5.1 新闻情报

#### 概览 Tab
- **统计卡片**（4 个）：今日事件（含日环比）、高价值事件（score≥80）、活跃追踪链、系统状态+采集器心跳
- **统计卡片增加时间维度切换**：今日 / 7天 / 30天
  - 今日：调用 GET /stats/today
  - 7/30 天：调用 GET /events?limit=1 获取 total 计数（利用已有的 date_from 参数过滤），dashboard 前端聚合展示
- **重要事件列表**（左侧）：Top 5-10 事件卡片，左侧色条标识价值（橙≥90、蓝≥80、绿≥70），显示分数、分类标签、来源、时间、实体标签、追踪链链接
- **右侧边栏**：热点实体（标签云）、热门话题趋势（↑↓→）、信源分布（条形图）
- **导出今日简报按钮**：生成 Markdown 格式简报（标题+日期+Top 事件摘要），复制到剪贴板

#### 事件 Tab
- 筛选栏：来源、分类、最小分数、搜索框、情感、实体、主题标签
- **新增日期范围选择器**：今日 / 本周 / 本月 / 自定义（date input）
- 事件卡片列表 + 分页
- **新增「导入」按钮**：点击打开导入弹窗（JSON 粘贴或文件上传，调用 POST /events/import）
- **新增「复制摘要」按钮**（事件详情页）：格式化文本（标题+分数+来源+URL），复制到剪贴板
- 事件详情：完整数据展示 + 反馈操作（发布/归档/评论）+ 关联事件 + 链接

#### 追踪链 Tab
- 链列表 + 链详情时间轴（无变化，已有功能）

#### 实体 Tab
- **修复 target_id 过滤**：传入当前选中 target
- **新增分页控件**：limit + offset 分页
- 实体详情 + 关联事件（无变化）

#### 趋势 Tab
- Chart.js 折线图 + 情感分布 + 排名表（无变化，已有功能）

### 5.2 告警通知

#### 实时告警 Tab
- 智能告警卡片：链更新、趋势突变、实体激增
- 点击告警跳转到对应事件/链
- 未读标记（前端维护，存 localStorage）

#### 历史记录 Tab
- 告警历史列表 + 按类型/时间过滤（无变化）

### 5.3 运行监控

#### 运行状态 Tab
- 活跃运行横幅：Pipeline 4 阶段进度条（采集→过滤→研判→输出）
  - 完成：绿色 ✓ + 事件数/耗时
  - 进行中：蓝紫渐变 + 脉冲光晕 + 实时计数
  - 等待：灰色 ○
- 一键触发：阶段选择器（all/collect/filter/judge/output）+ 触发按钮
- 运行详情：阶段执行表 + 错误 + 智能告警
- **修复 toast**：showError → showSuccess

#### 采集器 Tab（新增）
- 采集器状态卡片：enabled / running / target_id / interval / last_run_at / last_run_status / total_runs
- 心跳动效（音频柱 CSS 动画）
- 调用 GET /api/v1/collector/status

#### 信源健康 Tab
- 健康/降级/不可达统计 + 按信源列表（无变化）

#### 运行历史 Tab
- 运行记录表 + 详情查看（无变化）

#### 数据维护 Tab（新增）
- 清理旧数据：年龄滑块（7-365 天，默认 30）+ 目标选择 + 「清理」按钮
  - 调用 POST /api/v1/maintenance/prune
  - 确认弹窗显示影响范围
- 一键备份：「创建备份」按钮
  - 调用 POST /api/v1/maintenance/backup
  - 成功后显示备份路径/大小

### 5.4 反馈优化

#### 反馈记录 Tab
- 反馈统计 + 记录列表 + 发布/归档/评论（无变化）

#### 规则优化 Tab
- **修复 dry_run 参数**：`dry_run: "true"` → `dry_run: true`
- Dry-run 预览 / Apply 应用（无其他变化）

### 5.5 配置中心（默认折叠）

#### 目标 Tab
- 编辑显示名称、时区、分类轴、关键词（无变化）

#### 信源 Tab
- **修复 enable toggle 持久化**：toggle 变更时立即调用 apiPatch
- 信源列表 + 类型过滤 + 编辑面板（无其他变化）

#### 过滤规则 Tab
- 编辑分数阈值、年龄窗口、去重窗口、关键词规则（无变化）

#### 输出 Tab
- 输出目标卡片 + 启用/禁用 + 过滤设置（无变化）

#### AI 设置 Tab
- Provider 路由 + 超时/成本/审计（无变化）

#### Webhook Tab（新增）
- JSON 编辑器（textarea，预填充模板）
- 「发送测试」按钮：调用 POST /api/v1/webhook
- 显示响应状态码和 body

## 6. 状态可视化

### 6.1 CSS 动效（5 种）

```css
/* 脉冲光环 — 正常状态圆点 */
@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(2.5); opacity: 0; }
}

/* 呼吸闪烁 — 运行中/采集中 */
@keyframes blink-soft {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* 进度光晕 — Pipeline 进度条 */
@keyframes progress-glow {
  0%, 100% { opacity: 0.8; }
  50% { opacity: 1; filter: brightness(1.3); }
}

/* 音频柱 — 采集器心跳 */
@keyframes bar-dance {
  0%, 100% { transform: scaleY(1); }
  50% { transform: scaleY(0.3); }
}

/* 阶段脉冲 — 当前 Pipeline 阶段 */
@keyframes stage-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(79,143,247,0.4); }
  50% { box-shadow: 0 0 12px 4px rgba(79,143,247,0.2); }
}

/* 错误闪烁 */
@keyframes blink {
  50% { opacity: 0.3; }
}
```

### 6.2 应用位置

| 位置 | 正常 | 运行中 | 异常 |
|------|------|--------|------|
| 侧边栏状态圆点 | 绿色+pulse-ring | 蓝色+blink-soft | 红色+blink |
| 侧边栏心跳条 | 绿色静止柱 | 蓝色bar-dance柱 | 红色 |
| 运行监控 Pipeline | 绿色✓ | 蓝紫stage-pulse+progress-glow | 红色错误 |
| 概览系统状态卡片 | 绿色● | 蓝色●+blink-soft | 红色●+blink |

## 7. 国际化

### 7.1 i18n 对象结构

在 `api.js` 中定义：

```javascript
const i18n = {
  zh: {
    nav: { newsIntel: "新闻情报", alerts: "告警通知", ops: "运行监控", feedback: "反馈优化", config: "配置中心" },
    tabs: { overview: "概览", events: "事件", chains: "追踪链", entities: "实体", trends: "趋势" },
    common: { search: "搜索", filter: "筛选", export: "导出", import: "导入", save: "保存", cancel: "取消" },
    // ... 所有 UI 文字
  },
  en: {
    nav: { newsIntel: "News Intel", alerts: "Alerts", ops: "Operations", feedback: "Feedback", config: "Settings" },
    tabs: { overview: "Overview", events: "Events", chains: "Chains", entities: "Entities", trends: "Trends" },
    common: { search: "Search", filter: "Filter", export: "Export", import: "Import", save: "Save", cancel: "Cancel" },
    // ...
  }
};
```

### 7.2 语言选择

- 连接设置页增加语言选择下拉（中文/English）
- 存入 `localStorage.ns_language`
- 所有页面通过 `i18n[currentLang].xxx.yyy` 引用文字

## 8. 键盘快捷键

| 按键 | 功能 |
|------|------|
| `1` - `5` | 切换侧边栏 5 个入口（新闻/告警/监控/反馈/配置） |
| `/` | 聚焦搜索框（事件页） |
| `Esc` | 关闭弹窗 / 返回上一级 |
| `j` / `k` | 事件列表中上/下一条 |
| `Enter` | 打开当前选中事件详情 |

## 9. 网络容错

- API 请求超时：5 秒
- 自动重试：最多 2 次（仅 GET 请求）
- 断网检测：`navigator.onLine` + API 失败时侧边栏变红
- 已加载页面保持不清空，显示「网络连接已断开」横幅
- 恢复连接后自动刷新当前页数据

## 10. 部署架构

```
news-sentry.com (Cloudflare Pages)
  ↓ 静态文件: index.html + app.js + api.js + style.css + pages/*.js
  ↓ API 调用附加 X-API-Key header
  ↓
news-sentry.xuyu.workers.dev (Cloudflare Worker)
  ↓ CORS 代理 + 认证
  ↓
Container (FastAPI + SQLite)
  ↓ 44 API 端点 + 自动采集器
```

- Pages 项目直接使用 `src/news_sentry/static/` 目录
- 容器内 StaticFiles 保留作为后备（直接访问 worker URL 也能用）
- CORS 允许 `news-sentry.com`、`www.news-sentry.com`、`news-sentry.pages.dev`

## 11. Bug 修复清单

| # | Bug | 文件 | 修复方案 |
|---|-----|------|----------|
| 1 | Source enable toggle 不持久化 | config.js | toggle click 添加 apiPatch 调用 |
| 2 | Entity 列表无 target_id 过滤 | entities.js | params 添加 target_id |
| 3 | Entity 列表无分页 | entities.js | 添加分页控件 + limit/offset |
| 4 | Chain narrative 用 raw fetch | chains.js:151 | 改用 apiPost() |
| 5 | Ops trigger 成功显示红色 toast | ops.js | showError → showSuccess |
| 6 | Feedback dry_run 字符串非布尔 | feedback.js | dry_run:"true" → dry_run:true |
| 7 | 单源详情页缺失 | config.js | 源卡片点击展开详情（调用 GET /sources/{id}） |

## 12. 文件变更清单

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `src/news_sentry/static/index.html` | 重写 | 新导航结构 + 连接设置页 + Tab 容器 |
| `src/news_sentry/static/app.js` | 重写 | 新路由 + 认证流程 + 键盘快捷键 + i18n 初始化 |
| `src/news_sentry/static/api.js` | 重写 | API Key 认证 + 超时重试 + i18n 对象 + 导出工具函数 |
| `src/news_sentry/static/style.css` | 大幅修改 | 新导航样式 + Tab 栏 + 动效 keyframes + 日期选择器 + 导入弹窗 |
| `src/news_sentry/static/pages/dashboard.js` | 重写 | 新概览布局 + 时间维度切换 + 导出简报 |
| `src/news_sentry/static/pages/events.js` | 大幅修改 | 日期范围选择 + 导入弹窗 + 复制摘要 + 分页改进 |
| `src/news_sentry/static/pages/entities.js` | 修改 | target_id 过滤 + 分页控件 |
| `src/news_sentry/static/pages/chains.js` | 小修 | apiPost 替换 raw fetch |
| `src/news_sentry/static/pages/ops.js` | 重写 | 新 Tab 结构 + 采集器 + 维护 + Pipeline 动效 + toast 修复 |
| `src/news_sentry/static/pages/alerts.js` | 小修 | Tab 包装 + 未读标记 |
| `src/news_sentry/static/pages/feedback.js` | 小修 | Tab 包装 + dry_run 修复 |
| `src/news_sentry/static/pages/config.js` | 大幅修改 | Tab 包装 + enable 修复 + Webhook Tab + 源详情 |
| `src/news_sentry/static/pages/trends.js` | 小修 | Tab 包装 |

## 13. 不在本次范围

- 多用户/多角色权限系统
- PWA 离线缓存
- Chart.js 拖拽缩放
- 日/德/法 UI 翻译（仅中英）
- 事件多选+批量操作
- 移动端手势操作
