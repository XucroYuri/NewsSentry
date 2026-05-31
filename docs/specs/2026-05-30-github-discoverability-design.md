# GitHub 可发现性与认知资产完善设计

> 日期：2026-05-30
> 状态：设计稿
> 适用范围：GitHub 仓库 About、README、项目元数据、Issue/PR 模板、贡献入口与搜索关键词

## 1. 目标

本阶段目标是完善 News Sentry 在 GitHub 上“可被检索、可被理解、可被信任、可被 star”的公开信息资产。

这不是简单美化 README，而是把项目的长期方向、当前可用能力、专业受众、技术关键词、贡献入口和可信证据统一成一套对外叙事。仓库访问者应在 60 秒内理解：

- News Sentry 是什么。
- 它解决什么专业问题。
- 它和普通新闻阅读器、RSS reader、爬虫脚本、舆情 SaaS 有什么不同。
- 当前已经能运行什么。
- 为什么值得 star、watch 或 fork。
- 如何快速试用、贡献或跟进路线图。

## 2. 核心定位

推荐对外主定位：

> News Sentry is an open-source AI news intelligence and OSINT monitoring platform for continuous multilingual news, social media, source health, canonical event graph, and professional research workflows.

中文定位：

> News Sentry 是一个开源 AI 新闻情报与 OSINT 监控平台，用于持续采集多语言新闻、社媒与公共信源，并围绕 canonical event graph 支持专业研究工作流。

这个定位比“AI 新闻监控引擎”更适合 GitHub 检索和长期认知，因为它覆盖：

- `AI news intelligence`
- `OSINT`
- `public opinion monitoring`
- `multilingual news monitoring`
- `social media monitoring`
- `source health`
- `canonical event graph`
- `research workflow`

## 3. 目标受众

GitHub 首屏应主要服务三类人：

1. **开发者和开源用户**
   - 关心能否安装、运行、扩展、部署。
   - 需要清晰的快速开始、架构图、测试状态、许可证和贡献入口。

2. **新闻/研究/OSINT 专业用户**
   - 关心系统是否能持续追踪国家、地区、产业、政策、社媒和风险事件。
   - 需要理解 canonical event、source health、research artifacts、人工复核闭环。

3. **潜在合作方和商业化观察者**
   - 关心长期愿景、全球采集节点、本地轻客户端、专业订阅服务和可信数据基础设施。
   - 需要看到路线图和商业/架构方向文档入口，但不应让首屏显得过度商业化。

## 4. 信息架构

### 4.1 GitHub About

Repository description 建议：

```text
Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows.
```

Homepage 建议暂时使用 GitHub README 锚点或文档入口：

```text
https://github.com/XucroYuri/NewsSentry#readme
```

推荐 topics：

```text
ai, news, osint, intelligence, monitoring, journalism, media-monitoring,
public-opinion, social-media-monitoring, rss, nlp, multilingual,
event-graph, knowledge-graph, research-tool, python, fastapi, pydantic,
docker, open-source-intelligence
```

若 GitHub topics 数量受限，优先级：

1. `osint`
2. `news`
3. `ai`
4. `intelligence`
5. `monitoring`
6. `journalism`
7. `media-monitoring`
8. `public-opinion`
9. `social-media-monitoring`
10. `multilingual`
11. `event-graph`
12. `research-tool`
13. `python`
14. `fastapi`
15. `rss`
16. `docker`

### 4.2 README 首屏

README 首屏应采用“可信产品介绍 + 开发者快速判断”的结构：

- Badges：version、Python、license、CI、tests、ruff。
- 一句话定位：英文首屏更利于全球检索，中文 README 保留中文叙事。
- 价值主张：continuous monitoring、canonical event graph、human-in-the-loop research workflow。
- 快速导航：Quick Start、Why News Sentry、Architecture、Use Cases、Roadmap、Contributing。
- 明确当前状态：local-first、open-source、active development。

不建议首屏继续把 “Italy Breaking News reference target” 作为核心描述。Italy 可以作为参考 target 示例，但项目已经从单国家监控演进为多 target、研究工作流和 canonical graph 方向。

### 4.3 README 内容结构

中文 README 与英文 README 应保持结构一致，但表达侧重点不同。

英文 README 推荐结构：

1. What is News Sentry?
2. Why it matters
3. Core capabilities
4. Architecture
5. Quick start
6. Use cases
7. Current targets
8. Research workflow and canonical event graph
9. Deployment modes
10. Roadmap
11. Contributing
12. License

中文 README 推荐结构：

1. News Sentry 是什么
2. 为什么需要它
3. 核心能力
4. 系统架构
5. 快速开始
6. 典型使用场景
7. 当前监控目标
8. 研究工作流与 canonical event graph
9. 部署方式
10. 路线图
11. 参与贡献
12. 许可证

### 4.4 项目元数据

`pyproject.toml` 应同步更新：

- `description` 移除 Italy-only 旧描述。
- `keywords` 覆盖 OSINT、news intelligence、public opinion、event graph、research workflow。
- `project.urls` 增加 Documentation、Roadmap、Security、Discussions 或 Issues。

### 4.5 GitHub 模板

Issue/PR 模板需要从普通软件模板升级为更适合本项目的专业入口：

- Bug report：增加 target、stage、source type、runtime mode、data directory impact。
- Feature request：区分 collector、pipeline、canonical graph、research workflow、frontend、deployment。
- Source request：允许贡献新国家/地区/信源。
- Research workflow request：允许研究人员反馈工作台能力。
- PR template：增加 schema/contract、data migration、security、sensitive data、docs sync 检查项。

### 4.6 信任资产

应补充或显式链接：

- `docs/contracts-canonical.md`
- `docs/architecture.md`
- `docs/specs/2026-05-30-global-intelligence-platform-business-architecture-design.md`
- `docs/specs/2026-05-30-shadow-canonical-data-spine-design.md`
- `docs/specs/2026-05-30-professional-research-workflow-mvp-design.md`
- `SECURITY.md`
- `CONTRIBUTING.md`

这些文档能证明项目不是单次 demo，而是在建设长期可演进的数据和研究基础设施。

## 5. 不做事项

本阶段不做：

- 不创建虚假的 star、下载量、用户案例或夸大生产规模。
- 不写无法验证的性能数字。
- 不声称已经完成全球监控网络或云端集群。
- 不把尚未公开部署的服务写成可直接访问的 SaaS。
- 不引入营销站点或落地页。
- 不把私有运行数据、API key、日志、浏览器 profile、`.omx` 状态文件纳入提交。

## 6. 成功标准

完成后应满足：

- GitHub About 能通过 `AI news intelligence`、`OSINT`、`multilingual news monitoring`、`event graph` 等关键词被更准确识别。
- README 首屏能在一分钟内让新访客理解项目定位、当前能力、快速开始和长期方向。
- 英文 README 对全球开发者友好，中文 README 对国内专业用户和未来运营方向友好。
- Issue/PR 模板能引导用户贡献 bug、信源、功能和研究工作流反馈。
- `pyproject.toml` 与 GitHub metadata 不再停留在 Italy-only 或旧阶段描述。
- 所有对外信息真实、克制、可验证。

## 7. 实施顺序

推荐分三步实施：

1. **本地认知资产**
   - 更新 README、README_en、pyproject、GitHub 模板。
   - 新增 `docs/github-discoverability.md` 记录远端 metadata 推荐值。

2. **验证与提交**
   - 跑 Markdown/链接可读性检查、`python -m build` 或至少 `python -m py_compile` 不适用时跑 `ruff` 和相关轻量检查。
   - 精准 stage 本阶段文件，避免混入当前本地运行改动。

3. **远端 GitHub metadata**
   - 使用 `gh repo edit` 更新 description、homepage、topics。
   - 若权限允许，开启 Discussions。
   - 远端变更完成后用 `gh repo view` 验证。

## 8. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 定位过大导致可信度下降 | 明确区分“当前能力”和“长期路线图” |
| 关键词堆砌影响阅读 | 首屏只放核心短语，详细关键词放 metadata 和文档 |
| 中英文 README 漂移 | 统一结构，内容允许本地化表达 |
| 误提交本地运行文件 | 使用精确 `git add`，提交前检查 `git diff --cached` |
| GitHub metadata 权限不足 | 本地文档保留推荐值，提示用户手动设置 |
