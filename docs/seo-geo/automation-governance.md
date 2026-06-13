# SEO / GEO Automation Governance

## 适用范围

- 范围仅限公开站点：`news-sentry.com` 与 `/public-app/`
- 不覆盖管理后台、内部 API 写路径、编辑工作流与非公开数据面

## 发布路径

- 固定发布路径：`preview -> verify -> main -> production`
- 未完成 verify 的改动不得直接进入 `main`
- 生产发布以前，必须保留可回看验证证据

## 运行时规则

- 公开读取必须坚持 database-first
- 面向公开读路径时，数据库投影是唯一权威读取面
- 任何文件回退都应视为待清理兼容债，不得作为新增能力前提

## 文件系统规则

- Markdown 与文件产物仅用于 projection 或兼容输出
- 文件系统内容不作为公开站点运行时主读取权威
- 新增 SEO / GEO 能力时，优先补数据库投影与公开接口，而不是扩张文件直读

## 变更单位

- 每一轮只交付一个小而可验证的 change package
- 每一轮必须可独立预览、独立验证、独立回滚
- 不把多类风险绑定进同一轮自动化发布

## 自动化执行 Prompt

以下 prompt 作为 `news-sentry-seo-geo-rollout` cron automation 的任务正文基线：

```text
Run one round of the News Sentry public-site SEO/GEO rollout. Work only on the public site and its database-first public read path. First read the governance doc, prerequisites ledger, progress ledger, and rule source registry. Pull the enabled official/community rule sources, normalize candidate rules, choose one small technical change package, implement it, run local checks, push to `preview`, verify the public site externally, promote to `main` only if preview passes, verify production externally, then update the progress ledger and automation memory with what changed, what passed, what failed, and the next best round.
```
