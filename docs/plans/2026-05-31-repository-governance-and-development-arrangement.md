# 仓库发布治理审计与后续开发安排

> 日期：2026-05-31
> 状态：非破坏性审计记录
> 范围：本地分支、远端分支、tag 发布面、历史提交中不应发布内容的追溯治理

## 1. 当前分支状态

本地当前分支：

- `codex/admin-console-rework`
- 当前 HEAD：`6da9f8a fix: 收敛目标采集有效性问题`
- 未提交变更：架构设计文档、VPS + Cloudflare Tunnel 候选假设、运行时瘦身与 target scope 设计，以及本次治理记录。

远端当前主线：

- `origin/main`：`0ce7c44 Current Admin Shell research workbench UI split`
- `origin/HEAD` 指向 `origin/main`

本地 `main`：

- `main`：`9d4d5ec Merge branch 'codex/plan2-public-analysis-portal'`
- 与 `origin/main` 分叉：本地 `main` ahead 29 / behind 7。

结论：

- 不能直接把本地 `main` 推到远端。
- 不能直接以 `codex/admin-console-rework` 覆盖 `origin/main`。
- 后续必须以 `origin/main` 为集成基线，逐步 cherry-pick 或重建需要保留的本地提交。

## 2. 远端分支发布面

远端分支：

- `origin/main`
- `origin/governance/01-privacy-cleanup`
- `origin/governance/02-structure`
- `origin/governance/03-compliance`

审计结果：

| 分支 | 当前树风险 | 备注 |
| --- | --- | --- |
| `origin/main` | 包含 `prd.json`、`progress.txt`、`memory/session-profiles/twitter-italia-public.yaml` | 当前主线仍有不应长期发布的本地/运行时治理产物 |
| `origin/governance/01-privacy-cleanup` | 包含 `.codex/`、`.cursor/`、`.omc/`、`CLAUDE-PROMPT.md` | 名称像隐私清理分支，但当前树反而带本地工具配置；不可作为干净基线 |
| `origin/governance/02-structure` | 未发现 `.cursor/.omc/.codex/prd/progress` 当前树发布面 | 但不是最新主线 |
| `origin/governance/03-compliance` | 未发现 `.cursor/.omc/.codex/prd/progress` 当前树发布面 | 但不是最新主线 |

结论：

- governance 分支不能按名称信任，必须按当前树和历史实际内容判定。
- `governance/01-privacy-cleanup` 应考虑关闭或重建，避免误导。
- 清洁主线应从 `origin/main` 新建治理分支，而不是复用旧 governance 分支。

## 3. 历史发布追溯

### 3.1 曾经提交后删除的本地工具配置

历史中出现过：

- `.cursor/rules/news-sentry-core.mdc`
- `.omc/skills/karpathy-guidelines/SKILL.md`
- `.omc/skills/karpathy-perspective/SKILL.md`
- `.codex/automations/news-sentry-test.yaml`
- `CLAUDE-PROMPT.md`

关键提交：

- `8aff5c9 chore: prepare multi-agent development tooling`
- `1f06b9f Skill: 注册 karpathy-guidelines Agent Skill`
- `1b9355f Skill: 注册 karpathy-perspective 决策顾问 Skill`
- `2b01337 治理: 从HEAD移除误提交文件 — CLAUDE-PROMPT.md/.omc/.cursor/.codex`

判断：

- 这些文件已从部分后续 HEAD 中移除，但仍存在于 Git 历史。
- 若其中包含敏感 prompt、账号、内部工作流或自动化配置，应按历史泄露处理。
- 若仅为公开规则/技能文本，可选择保留历史但不得再次进入主线。

### 3.2 当前主线仍发布的本地/运行时产物

`origin/main` 和当前 `HEAD` 当前树中仍包含：

- `prd.json`
- `progress.txt`
- `memory/session-profiles/twitter-italia-public.yaml`

其中 `prd.json` 与 `progress.txt` 已在 `.gitignore` 中声明为 P56 build artifacts，不应继续作为发布内容。

本次新增 `.gitignore`：

- `memory/session-profiles/`

用于防止后续 session profile runtime state 再进入发布面。

### 3.3 Tag 发布面

当前 tags：

- `v1.0.0`
- `v1.5.0`
- `v1.6.0`
- `v1.7.0`
- `v1.7.1`
- `v1.8.0`
- `v1.9.0`
- `v1.9.1`

审计结果：

- 所有 tag 都包含 `.env.example`、profile 配置、eval 数据和 `memory/session-profiles/twitter-italia-public.yaml`。
- `v1.7.0` 起包含 `prd.json`、`progress.txt`。

结论：

- 若要彻底清理 GitHub 发布面，仅删除当前主线文件不够；tag 也需要治理。
- tag 是否重写/删除属于破坏性远端操作，必须单独确认。

## 4. 内容级敏感扫描初判

执行了基于 Git 历史和当前 HEAD 的敏感模式扫描，命中主要集中在：

- `.env.example`
- README / README_en
- 部署文档
- provider route 示例
- Docker Compose 示例
- API server 中环境变量处理代码

当前初判：

- 未确认发现真实密钥值。
- 命中主要来自占位 key、环境变量名、示例命令和代码中的变量处理。
- 由于没有安装专用 secret scanner，本结论不能替代 gitleaks/trufflehog 的最终审计。

建议：

- 在下一轮治理中安装并运行 gitleaks 或 trufflehog，输出机器可读报告。
- 将 `.env.example` 中形如 `sk-xxxxxxxx` 的占位符替换为 `<OPENROUTER_API_KEY>` 这类不会误触发 secret scanner 的占位格式。

## 5. 治理执行建议

### 5.1 第一批非破坏性清理

从 `origin/main` 新建：

```text
codex/repo-publication-governance
```

只做当前树清理，不重写历史：

- 从 Git index 移除 `prd.json`、`progress.txt`。
- 评估并移除或迁移 `memory/session-profiles/twitter-italia-public.yaml`。
- 保留 `config/session-profiles/italy/.gitkeep` 作为空目录占位。
- 复查 `data/eval/report-v3-rules-v2.json` 是否为生成报告；若是生成物，移出 Git。
- 将 `.env.example` 改成 scanner-friendly 占位符。
- 加入 CI secret scan。

### 5.2 第二批远端分支治理

- 关闭或删除误导性的 `governance/01-privacy-cleanup` 远端分支。
- 若 `governance/02-structure` 和 `governance/03-compliance` 内容已被主线吸收，则删除远端分支。
- 若尚未吸收，则从 `origin/main` 重新 cherry-pick 有价值提交，不直接 merge 旧分支。

### 5.3 第三批历史治理

仅在确认存在真实敏感信息或必须彻底清除本地工具配置历史时执行：

- 用 `git filter-repo` 或 BFG 清理 `.cursor/`、`.omc/`、`.codex/`、`CLAUDE-PROMPT.md`、`prd.json`、`progress.txt`、`memory/session-profiles/`。
- 重写所有受影响分支和 tags。
- force-push 前冻结协作窗口。
- 通知所有协作者重新 clone 或执行硬重置。
- 旋转所有可能受影响的 token、API key、Webhook secret。

## 6. 后续开发安排

### Stage A：仓库发布面恢复干净

- 建立 `codex/repo-publication-governance`。
- 当前树去除本地/运行时/生成物。
- CI 加入 secret scanning 与 forbidden-path check。
- 更新贡献指南：哪些文件禁止进入 GitHub。

### Stage B：重建集成基线

- 以 `origin/main` 为基线。
- 将当前 `codex/admin-console-rework` 中仍需要的功能按主题拆分 cherry-pick。
- 每组变更独立验证，不再把旧本地 `main` 的 29 个 ahead 提交整体推送。

建议拆分：

1. 文档/架构设计：运行时瘦身、target scope、VPS + Cloudflare 假设。
2. runtime reliability：bounded run、source diagnostics、cache/version 可观测。
3. canonical spine：projection/backfill/store/API。
4. research workflow：artifact、merge/split、review workbench。
5. public portal：只读公开门户、feed、analysis 页面。
6. admin console：配置、target workbench、诊断与权限边界。

### Stage C：架构改造优先级

优先实现：

1. `target` 口径迁移为 view/subscription/scope。
2. core runtime profile 瘦身。
3. sidecar manifest 规范。
4. Markdown 默认降级为 projection/export。
5. 本地客户端与 cloud collector node 的 signed task 契约。

暂缓：

- Cloudflare-native 全量迁移。
- ClickHouse/Kafka/Iceberg 等规模化组件。
- 视频/ASR 重型 sidecar。
- 开放式公共采集节点网络。
