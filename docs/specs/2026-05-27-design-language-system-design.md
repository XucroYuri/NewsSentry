# News Sentry 全站设计语言规范化设计

日期：2026-05-27
状态：已选择方向 A「主站语言规范化」，待用户 review
范围：公开新闻门户、管理后台、Target 工作台的前端视觉与交互范式

## Summary

本设计不做全新视觉改版，而是把当前已经相对满意的 News Sentry 主站气质沉淀为统一的前端设计范式。目标是解决局部页面各自发明样式、导航结构不一致、组件密度不统一、空状态与错误态不成体系的问题。

统一后的产品应继续保持“新闻情报工作台”的判断力：低饱和背景、暗红强调、1px 边框、小圆角、高信息密度、表格和列表优先。公开端负责新闻阅读与目标入口；后台负责 Target、信源、规则、采集、审核、维护等需要人工干预的管理能力。两者可以有不同的信息架构，但必须使用同一套品牌、token、组件和状态表达。

## Goals

- 保留当前主站审美：暗红新闻情报感、纯色界面、紧凑布局、低装饰度。
- 建立可执行的设计范式：页面骨架、导航、按钮、tab、pill、表格、表单、提示、空状态、错误态都有统一规则。
- 让公开页和后台像同一个产品：公开页更轻，后台更高密度，但品牌、颜色、边框、圆角、字体、状态表达一致。
- 降低后续页面迭代成本：新增页面优先复用现有范式，不再局部堆新类名和特殊样式。
- 支持非技术用户高效操作：后台管理路径以 Target 为主线，重点使用列表、表格、表单、明确操作按钮和预检反馈。

## Non-Goals

- 不重新定义 News Sentry 的品牌方向。
- 不引入新的前端框架或设计系统依赖。
- 不在本阶段重构后端业务接口、采集器协议或权限体系。
- 不把所有页面重做成营销站、仪表盘大屏或装饰性卡片布局。
- 不追求像素级完美组件库，第一阶段以统一规则和高频组件落地为主。

## Design Principles

### 1. 现有气质优先

News Sentry 当前最稳定的视觉资产是：

- 书本图标 + `News Sentry` 品牌锁定。
- 暗红作为主强调色。
- 米白/深色纯色背景，而不是渐变或高饱和装饰。
- 1px 细边框、小圆角、低阴影。
- 新闻/情报产品需要的列表、表格、时间线和频道化信息密度。

后续统一工作应围绕这些资产收敛，而不是重新发明视觉系统。

### 2. 信息密度服务任务

公开端的任务是快速进入目标、阅读频道、打开文章详情；后台的任务是管理、确认、修正、预检和维护。因此：

- 公开端可以留出更多阅读空间，但不使用大幅装饰 hero。
- 后台优先使用紧凑列表、表格和表单。
- Target、Source、Social、Rules 等管理页面不默认使用大卡片墙。
- 卡片只用于分组入口、概览摘要、单个重复项目或模态内容。

### 3. 状态必须可操作

加载、空数据、接口失败、未选择 Target、预检失败、危险操作等待确认，都必须给出下一步：

- 重试。
- 选择 Target。
- 去配置。
- 执行预检。
- 查看诊断。
- 返回上一级。

禁止长期展示“正在加载”或只有一行不可操作说明。

### 4. 公开端和后台分工清晰

公开端不显示后台状态、SSE 状态、采集运行细节、高级配置入口。后台不重复公开阅读门户，而是提供管理和干预能力。

公开端入口：

- `#/news/feed`
- `#/news/target/:targetId`
- `#/news/target/:targetId/events/:eventId`

后台入口：

- `#/admin/home/overview`
- `#/admin/targets`
- `#/admin/targets/:targetId/*`
- 兼容的 `collection`、`review`、`ops`、`advanced` 分区

## Visual Tokens

### Color

保留现有 token 语义：

- `--bg-primary`：页面背景。
- `--bg-secondary`：导航、面板、表单背景。
- `--bg-card`：内容卡片和列表行背景。
- `--bg-hover` / `--bg-active`：hover 和 active 状态。
- `--text-primary` / `--text-secondary` / `--text-muted`：三级文本。
- `--accent-primary`：主强调色，默认暗红。
- `--border-color` / `--border-light`：分割线和控件边框。

禁止新增页面级硬编码主题色。若确实需要语义色，先归并为：

- `success`：采集正常、预检通过、已启用。
- `warning`：需处理、已归档、部分失败。
- `danger`：危险操作、严重失败。
- `muted`：不可用、云端功能、本地降级。

### Radius And Border

- 主控件和面板使用 2-4px 小圆角。
- 主要结构使用 1px 边框。
- 不使用大圆角胶囊卡片作为默认容器。
- 边框优先于阴影表达层级，阴影只用于浮层、toast、modal。

### Typography

- 页面 H1 只用于主要页面标题，后台页面不得使用落地页式超大标题。
- 面板标题、表格标题、表单 label 使用较小字号和较高字重。
- 字间距保持 0；英文 uppercase 只用于 kicker、id、状态短标签。
- 列表和表格中的正文以可扫描为优先，不使用大段说明文字。

### Spacing

- 后台页面采用紧凑节奏：页面外边距小于公开端，操作区与内容区距离稳定。
- 公开端阅读页可以更舒展，但仍保持主站纯色、边框、暗红强调。
- 移动端优先单列堆叠，按钮和 tab 不横向溢出。

## Page Shells

### Public Shell

公开端页面使用轻量顶部栏：

- 左侧只保留统一品牌锁定：书本图标 + `News Sentry`。
- 品牌点击返回 `#/news/feed`。
- 右侧只保留必要入口，如 `管理后台`。
- 不显示后台 tab、侧边栏、运行状态、Target 管理上下文。

公开首页采用目标入口列表或紧凑卡片，展示 active target。归档 target 默认隐藏。页面目标是让读者快速选择监控目标，而不是配置系统。

### Admin Shell

后台使用左侧导航：

- 顶部为统一品牌锁定，点击返回公开首页。
- 主导航保持五类能力：目标工作台、管理总览、采集与信源、审核与反馈、系统运维、高级管理。
- 左侧导航不承担 Target 选择器职责。
- 页面顶部显示面包屑和当前页面上下文，不把全局 Target 下拉固定在右上角。

后台页面应避免公开页 topbar 和后台 sidebar 混用。

### Target Workbench Shell

Target 工作台是后台的主路径：

- `#/admin/targets`：所有 target 紧凑列表。
- `#/admin/targets/:targetId/overview`：单个 target 总览。
- 子页固定为 profile、sources、social、rules、collection、review、maintenance。

Target 上下文应放在页面主体或工作台 header 内，而不是全局右上角。进入某个 target 后，页面标题区显示 target 名称、id、生命周期状态、公开页入口和返回全部目标入口。

## Component Standards

### Brand Lockup

全站只使用一套品牌识别：

- 书本图标。
- `News Sentry` 文本。
- 一行水平排列。
- 可点击时使用 `<a>`，语义为返回公开首页。

不再同时出现 `NS` 方块、`频道首页` 文本和重复 title。

### Buttons

按钮分为四级：

- Primary：主动作，如进入工作台、保存、立即运行。
- Secondary：次动作，如公开页、返回、重试、诊断。
- Danger：危险动作，如归档 target、停止采集、清理数据。
- Ghost/Icon：工具性动作，如刷新、折叠、查看详情。

同一页面同一操作区原则上只有一个 primary。危险操作必须二次确认。

### Tabs And Segments

Tab 只用于同一对象下的同级内容切换，例如 Target 工作台子页。页面主导航不使用 tab 样式伪装。Tab 样式统一：

- 小圆角或底线两者选一，后台优先紧凑小圆角。
- active 使用暗红边框或底线。
- 移动端允许横向滚动，但不得撑破页面。

### Lists And Tables

后台管理对象优先使用列表和表格：

- Target 列表：名称/id、状态、信源数、事件数、最近运行、操作。
- Source 列表：名称、类型、启用状态、健康、归档状态、操作。
- Social 矩阵：维度、账号、monitor mode、session/profile、操作。
- Review 队列：事件标题、评分、频道、反馈状态、操作。

卡片式布局只用于概览摘要和快捷入口，不作为高密度管理对象默认形态。

### Forms

表单统一为 label + input/select/textarea + help/error 的结构：

- 字段标签短而明确。
- 辅助说明只解释业务后果，不解释显而易见的控件用法。
- 保存前支持预检的页面，主按钮命名为“预检并保存”。
- YAML/JSON 原文编辑不作为默认路径，保留为高级入口。

### Status Pills

状态短标签统一语义：

- Active / 已启用：success。
- Archived / 已归档：warning/muted。
- Error / 失败：danger。
- Local / 本地模式、Cloud Only / 云端功能：muted。
- 未预检：muted。
- 需要处理：warning。

状态文本必须能解释对象当前是否可用。

### Empty, Loading, Error

统一三类状态组件：

- Loading：短文本 + spinner，超过接口失败后进入 error，不长期空转。
- Empty：说明当前为空的原因 + 下一步动作。
- Error：错误摘要 + 重试 + 诊断或返回路径。

例如高级配置页面未选择 target 时，不显示大面积空白，而显示“请选择一个 Target”以及进入目标工作台的按钮。

## Page-Level Rules

### Public Home

公开首页应回答：

- 当前有哪些可浏览监控目标。
- 每个 target 大致有多少事件或信源。
- 点击后进入哪个频道门户。

归档 target 不展示。若没有 active target，展示可操作空状态：进入管理后台创建/恢复 target。

### Public Target Portal

目标门户应回答：

- 当前 target 是什么。
- 有哪些频道。
- 最新/精选/政策/产业/技术/风险/中国相关内容如何切换。
- 当前数据是否为空、过旧或加载失败。

阅读端不显示采集管理控件。

### Admin Overview

管理总览应回答：

- 当前系统是否正常。
- 哪些 target 需要处理。
- 哪些采集、信源、反馈、告警需要干预。
- 下一步最应该点哪里。

总览不应成为大屏展示，应是工作入口。

### Target List

Target 列表使用紧凑行，不使用大卡片墙。每行应包含：

- Target 名称和 id。
- 生命周期状态。
- 信源数。
- 事件数。
- 最近运行或最近更新。
- 进入工作台、公开页、归档/恢复。

新增 Target 表单放在列表之后或右侧抽屉中，默认支持模板/克隆。

### Target Detail

单个 target 工作台页统一结构：

- 工作台 header：target 名称、id、状态、公开页、全部目标。
- 子页 tab：overview/profile/sources/social/rules/collection/review/maintenance。
- 主内容：列表、表单、预检、诊断、危险操作。

不同子页不得再各自发明 page hero。

### Advanced Management

高级管理不应只是占位 tab。第一阶段按“可配置表单壳”落地：

- 过滤规则。
- 输出设置。
- AI Provider。
- Webhook。
- API Key。
- 用户/云端账号。
- 外观主题。

本地模式中账号、用户、云端 API Key 治理显示为“云端部署功能”，不假装本地可完整操作。

## Implementation Boundaries

第一阶段实现只做以下内容：

- 抽出或整理 CSS token 和高频组件样式。
- 收敛公开 topbar 和后台 sidebar 的品牌锁定。
- 统一 admin header、breadcrumb、tab、target 工作台 header。
- 将 target 管理和信源/社媒等对象默认改为紧凑列表或表格。
- 替换长期加载、空白页、未选择 target 的不可操作状态。
- 修正明显局部风格跳脱的高级配置、目标工作台、管理后台页头。

第一阶段不做：

- 权限系统重构。
- 新 API 大规模设计。
- 数据 schema 重构。
- 采集器核心协议重写。
- 公共阅读门户的完整内容重排。

## Testing And Verification

### Static Checks

- `node --check src/news_sentry/static/app.js src/news_sentry/static/pages/target_workbench.js`
- 相关 JS 路由测试和公开首页测试。

### Browser Checks

桌面和 390px 移动端检查：

- `#/news/feed`
- `#/news/target/italy`
- `#/admin/home/overview`
- `#/admin/targets`
- `#/admin/targets/germany/review`
- `#/admin/targets/germany/sources`
- `#/admin/advanced/filters`

检查项：

- 无横向溢出。
- 品牌点击返回公开首页。
- tab 不撑破页面。
- 列表/表格密度一致。
- 空状态和错误态都有下一步。
- 公开端没有后台元素。
- 后台端没有公开端导航混入。

### Visual Regression Heuristics

无需引入截图测试框架，第一阶段使用 Playwright 脚本检查：

- body 宽度不超过 viewport。
- 关键容器存在。
- loading 文案不会在接口结束后残留。
- target 列表行数与 API 返回一致。
- 移动端主要按钮可见。

## Risks

- 如果一次性重写过多 CSS，容易误伤已有页面。应优先新增统一类和替换高频页面，再逐步删除旧样式。
- 如果只写 token 不改页面结构，不统一的问题会继续存在。规范必须配合页面范式收敛。
- 如果后台过度追求公开页阅读感，会牺牲管理效率。后台应使用同一视觉语言，但保持工具属性。
- 如果继续保留全局右上角 target 下拉，会与 Target 工作台心智冲突。Target 上下文应进入页面主体。

## Approval

用户已在视觉伴侣中选择方向 A「主站语言规范化」，并确认进入设计规范草案阶段。本 spec 用于进入下一步实施计划，不直接包含代码改动。
