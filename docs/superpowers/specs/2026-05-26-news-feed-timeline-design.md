# News Feed Timeline Redesign Design

## Context

News Sentry 的新闻流已经能匿名访问，并已具备 `display_title`、`score`、`source_display_name`、`flat_tags`、`ai_reason` 等展示字段。当前问题不在配色或美术风格，而在信息组织效率：读者需要更快判断“发生了什么、来自哪里、为什么值得看、属于哪个主题”。

参考站点 AIHOT 的可借鉴点是阅读路径，而不是视觉皮肤。它把信息压缩为：日期分组、时间线定位、来源识别、标题摘要、标签分类、推荐理由和关联讨论。这种结构适合 News Sentry 的编辑部工作台定位。

## Goals

1. 将 `#/news/feed` 改造成以时间线为主的新闻阅读界面。
2. 默认展示推荐理由，让 AI 研判成为列表层级的一部分。
3. 提供紧凑视图，满足高密度扫读。
4. 用语义频道 chips 替代复杂筛选入口，让分类更像读者频道。
5. 保持现有 News Sentry 配色、字体、侧边栏、顶部导航和整体专业工具气质。

## Non-Goals

1. 不重做全站视觉风格。
2. 不修改 `#/news/overview`、`#/news/events`、详情页、运行监控或后台配置。
3. 不引入新的后台配置系统。
4. 不在第一版实现来源双入口或动态热词频道。
5. 不要求后端立即完成更复杂的多源事件聚合。

## Approved Direction

第一版采用：

- 默认视图：A2 推荐理由前置。
- 紧凑视图：A1 高密度速览。
- 分类入口：B1 语义频道 chips。
- 后续增强：B2 来源 + 主题双入口、B3 自适应热词频道。

## Page Structure

`#/news/feed` 使用四层结构：

1. Header toolbar
   - 标题：`新闻流`
   - 事件数量
   - 视图切换：默认 / 紧凑
   - 日期筛选
   - 搜索框
   - 刷新按钮

2. Channel chips
   - `全部`
   - `精选`
   - `政策`
   - `产业`
   - `技术`
   - `风险`
   - `中国相关`

3. Date timeline
   - 按日期分组。
   - 每个日期组使用横线和日期标题。
   - 组内按发布时间展示垂直时间线。

4. Feed item
   - 时间
   - 来源名
   - 分数
   - 标题
   - 摘要
   - 标签
   - 推荐理由

## Default Feed Item

默认视图展示：

- `published_at` 格式化为 `HH:mm`。
- `source_display_name`，缺失时使用 `source_id`。
- `score`，缺失时不显示分数胶囊。
- `display_title`，缺失时按现有降级逻辑显示标题或事件 ID。
- 摘要，优先使用已有摘要字段；没有摘要时不显示摘要行。
- `flat_tags`，最多显示 4 个。
- `ai_reason`，缺失时不显示推荐理由块。

推荐理由块使用现有品牌色系中的绿色/青绿色提示色，但保持克制，不使用夸张装饰。

## Compact Feed Item

紧凑视图展示：

- 时间
- 来源名
- 标题
- 标签
- 分数

紧凑视图隐藏摘要和推荐理由，主要用于快速扫读一天内大量新闻。

## Channel Chips

频道 chips 是前端预设筛选，不是后台配置。

筛选规则：

- `全部`：不筛选。
- `精选`：`score >= 70`，或 `recommendation` 为 `publish` / `review`。
- `政策`：匹配 `flat_tags`、`classification.l0`、`classification.l1` 中的 `politics`、`policy`、`regulation`、`government`、`diplomacy`。
- `产业`：匹配 `industry`、`business`、`market`、`investment`、`company`、`economy`。
- `技术`：匹配 `technology`、`model`、`chip`、`infrastructure`、`research`、`open-source`。
- `风险`：匹配 `security`、`safety`、`risk`、`conflict`、`sanction`、`supply-chain`。
- `中国相关`：匹配 `china`、`chinese`、`china-relations`，或 `china_relevance >= 50`。

匹配逻辑应大小写不敏感，并同时检查字符串标签和 `{code, name, label}` 形态的对象标签。

## Search And Date

搜索框在前端筛选当前加载结果：

- 匹配标题、来源、标签、摘要、推荐理由。
- 输入时 debounce。
- 搜索和频道可以叠加。

日期筛选沿用现有 `date` 参数，继续请求 `/api/v1/events/feed`。

## API Boundary

第一版继续使用现有接口：

- `GET /api/v1/events/feed`
- `GET /api/v1/targets`

如需增强，后端只补充展示字段，不改变 NewsEvent 存储契约。

可接受的后端补充：

- `summary`：适合列表展示的短摘要。
- 更稳定的 `flat_tags` 标准化。
- `channel_matches` 不作为第一版必需字段。

## Error And Empty States

1. 没有 target：显示“请先选择目标”。
2. 接口失败：显示可读错误和刷新按钮。
3. 当前频道无结果：显示“该频道暂无新闻”，保留频道 chips 和搜索状态。
4. 搜索无结果：显示“没有匹配的新闻”，提供清空搜索按钮。
5. 字段缺失：局部降级，不显示空标签、空摘要或空推荐理由。

## Testing

实现时需要覆盖：

1. 后端 feed payload 对摘要、标签、推荐理由的降级行为。
2. 前端频道匹配函数。
3. 前端搜索函数。
4. 浏览器截图验证：
   - 默认视图有推荐理由。
   - 紧凑视图隐藏推荐理由。
   - 频道 chips 能筛选。
   - 移动端布局不溢出。

## Future Enhancements

后续可做但不进入第一版：

1. B2 来源 + 主题双入口：按通讯社、科技媒体、社媒 KOL 等来源组筛选。
2. B3 自适应热词频道：按当天 topic/entity 自动生成频道。
3. 多源关联摘要：将同一事件的多个来源聚合为一个主线条目。
4. 关联讨论：显示 X、HN、官方文件等讨论数量。
5. 编辑提示：把 AI 研判升级为更明确的“下一步关注点”。
