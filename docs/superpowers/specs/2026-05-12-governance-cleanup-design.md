# News Sentry — 内部治理与开源规范化方案

> 版本: v1.0 | 日期: 2026-05-12 | 状态: 待执行

---

## 1. 背景与目标

### 1.1 当前状态

| 维度 | 状态 |
|------|------|
| 远程同步 | `origin/main` 领先本地 4 commits（Phase 15 Cloud VPS + Phase 16 日本 target） |
| 仓库卫生 | 1 个 untracked 文件，0 unstaged changes |
| HEAD 安全 | 无硬编码密钥/token/password，无本机路径泄露 |
| 历史安全 | 无真实 API key 泄露；3 个 commit 含本机路径（`/Users/huachi`、`/Users/xuyu`） |
| 误提交文件 | 5 个（CLAUDE-PROMPT.md、.omc（2）、.cursor（1）、.codex（1）） |
| .gitignore 覆盖 | 良好，但部分文件在规则添加前已提交 |

### 1.2 治理目标（三线并进）

1. **隐私清洗** — 从 Git 历史中彻底清除误提交文件和本机路径引用
2. **结构归一化** — 开发过程文档归入 `.planning/`，公开仓库只保留面向使用者的文档
3. **合规达标** — 对标开源项目发布标准（LICENSE、CONTRIBUTING、README 审查）

### 1.3 约束

- 使用独立分支推进，最终收口回 `main`
- 开发过程文件优先做目录治理 + gitignore，**不删除**（v1.0 后再评估彻底退出）
- 历史重写操作需用户审慎确认后执行

---

## 2. 分支策略

```
main (当前 HEAD: 257a7de)
  │
  ├─ 第〇步: git pull origin main 同步至最新 (fcedef3)
  │
  ├─→ governance/01-privacy-cleanup     ← 第 1 阶段：历史扫描 + filter-repo 清理
  │     │                                  重写完成后 force push 到分支
  │     └─→ PR review → merge to main
  │
  ├─→ governance/02-structure           ← 第 2 阶段：结构归一化（可并行）
  ├─→ governance/03-compliance          ← 第 2 阶段：合规达标（可并行）
  │
  └─→ main（治理闭环完成）
```

**顺序执行理由：** Track 1（隐私清洗）使用 `git filter-repo` 重写历史，会改变所有 commit SHA。若在此前切出 Track 2/3 分支，重写后 base 断裂，合并异常。Track 2 和 Track 3 都是文件级改动（新增/移动/修改），互不冲突，可并行。

---

## 3. Track 1 — 隐私清洗

### 3.1 历史扫描结果

通过 `git log --all -p | grep` 全量模式扫描，发现：

| 类别 | 数量 | 详情 |
|------|------|------|
| **误提交文件** | 5 | CLAUDE-PROMPT.md、.omc(2)、.cursor(1)、.codex(1) |
| **本机路径 /Users/huachi** | 1 commit | `1fb8b2f` — memory/MEMORY.md 绝对路径 |
| **本机路径 /Users/xuyu** | 2 commits | `8ce5bbc`, `ff423f1` — working_dir、opencli 安装路径 |
| **Docker 路径 /home/appuser** | 多处 | **非风险** — 标准容器内路径 |
| **测试数据中的假密码** | 2 处 | `"password=secret"`, `"client_secret=42"` — 测试 fixture，**非风险** |
| **真实 API Key/Token** | **0** | **无泄露** |

### 3.2 清理策略：`git filter-repo`

使用 `git filter-repo` 一次性处理全部误提交文件：

```bash
# 安装 git-filter-repo（若未安装）
pip install git-filter-repo

# 从全量历史中删除 5 个文件
git filter-repo \
  --path CLAUDE-PROMPT.md \
  --path .omc/skills/karpathy-guidelines/SKILL.md \
  --path .omc/skills/karpathy-perspective/SKILL.md \
  --path .cursor/rules/news-sentry-core.mdc \
  --path .codex/automations/news-sentry-test.yaml \
  --invert-paths \
  --force
```

### 3.3 本机路径修复

以下 commit 中的本机路径需在 filter-repo 之后额外修复（通过 `sed` + `git filter-repo --replace-text`）：

| Commit | 文件 | 路径内容 | 修复为 |
|--------|------|---------|--------|
| `1fb8b2f` | memory/MEMORY.md | `/Users/huachi/.claude/projects/...` | `~/.claude/projects/...` |
| `8ce5bbc` | docs/spec/phase-3-test-plan.md | `/Users/xuyu/Code/NewsSentry` | `./` |
| `ff423f1` | config/profiles/local-workstation.yaml | `/Users/xuyu/Code/NewsSentry` | `./` |

修复文本文件（replacements.txt）：
```
/Users/huachi/.claude/projects/-Users-huachi-Code-06-dev-tools-Public-Opinion-Sandtable/memory/MEMORY.md==>~/.claude/projects/NewsSentry/memory/MEMORY.md
/Users/xuyu/Code/NewsSentry==>./
/Users/xuyu/.local/bin/opencli==>opencli
```

### 3.4 .gitignore 加固

在已有 `.gitignore` 基础上，确保以下规则到位：

```gitignore
# 已存在，确认无误：
.omc/
.cursor/*
!.cursor/rules/
!.cursor/rules/**           # ← 需移除这 3 行例外规则，改为纯 .cursor/

# 新增或修改：
CLAUDE-PROMPT.md
.codex/
```

**具体改动：** 将 `.gitignore` 第 5-7 行 `.cursor/*` + 例外规则替换为 `.cursor/`；新增 `CLAUDE-PROMPT.md` 和 `.codex/`。

### 3.5 操作步骤

```
Step 0: git pull origin main  # 同步至 fcedef3
Step 1: git checkout -b governance/01-privacy-cleanup
Step 2: git filter-repo --path <file1> --path <file2> ... --invert-paths --force
Step 3: 应用 replacements.txt 修复本机路径
Step 4: 更新 .gitignore（移除 .cursor 例外规则，新增误提交文件条目）
Step 5: git add .gitignore && git commit -m "治理: 加固 .gitignore，移除 IDE/工具链本地配置例外规则"
Step 6: git push -f origin governance/01-privacy-cleanup
Step 7: 创建 PR，CI 验证通过后合并
```

### 3.6 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| filter-repo 后本地其他分支/工作树失效 | 高 | 推送前确认其他分支已同步，清理 `.worktrees/` |
| force push 后协作者本地仓库断裂 | 中 | 项目目前为单人开发，影响可控 |
| CI 在重写后无法通过 | 低 | filter-repo 不改变文件内容（除指定路径），无功能影响 |
| replacements.txt 错误替换 | 低 | 替换模式精确匹配，只替换特定路径字符串 |

---

## 4. Track 2 — 结构归一化

### 4.1 目标

将开发过程文档归入 `.planning/`（gitignored），公开仓库只保留对使用者有价值的内容。

### 4.2 文档分层方案

| 当前位置 | 处理 | 目标位置 | 原因 |
|---------|------|---------|------|
| `docs/adr/` (22 份) | **保留公开** | 不变 | 架构决策永久记录 |
| `docs/spec/` (14 份) | **保留公开** | 不变 | Phase 规格定义系统能力 |
| `docs/contracts-canonical.md` | **保留公开** | 不变 | 口径权威来源 |
| `docs/brainstorming/` (13 份) | **迁移 + gitignore** | `.planning/brainstorming/` | 原始构思记录 |
| `docs/superpowers/` (specs/plans/designs) | **迁移 + gitignore** | `.planning/superpowers/` | 开发工作流产物 |
| `.codex/` | **已从历史清除** | 归入 .gitignore | Track 1 处理 |
| `.cursor/` | **已从历史清除** | 归入 .gitignore | Track 1 处理 |
| `.omc/` | **已从历史清除** | 已在 .gitignore | Track 1 处理 |
| `CLAUDE-PROMPT.md` | **已从历史清除** | 归入 .gitignore | Track 1 处理 |

### 4.3 操作步骤

```
Step 1: git checkout -b governance/02-structure (基于治理后的 main)
Step 2: mkdir -p .planning && echo "# Planning Workspace" > .planning/README.md
Step 3: git mv docs/brainstorming/ .planning/brainstorming/
Step 4: git mv docs/superpowers/ .planning/superpowers/
Step 5: 确保 .gitignore 包含 .planning/（新增或确认已有）
Step 6: git add .gitignore && git commit -m "治理: 开发过程文档归入 .planning/，公开仓库结构归一化"
Step 7: git push origin governance/02-structure
Step 8: 创建 PR
```

### 4.4 v1.0 后续计划

- `.planning/` 内容在本地保留，持续为开发服务
- v1.0 发布时评估：将具备永久参考价值的规划文档从 `.planning/` 还原到 `docs/`
- 纯开发过程的临时文档继续留在 `.planning/`，不作公开

---

## 5. Track 3 — 合规达标

### 5.1 目标

确保项目满足开源发布基本合规要求。

### 5.2 检查清单与行动

| 检查项 | 当前状态 | 操作 |
|--------|---------|------|
| **LICENSE** | ✅ Apache 2.0 (`LICENSE` 文件存在) | 确认版权年份和作者信息正确 |
| **README.md** | ✅ 中英文双份，内容完整 | 审查是否有过期信源引用或状态标注 |
| **CONTRIBUTING.md** | ✅ 存在 | 审查内容是否适用开源贡献场景 |
| **.env.example** | ✅ 含所有环境变量模板 | 确认不包含真实密钥 |
| **CODE_OF_CONDUCT.md** | ❌ 缺失 | **新增** — 引用 Contributor Covenant 2.1 |
| **SECURITY.md** | ❌ 缺失 | **新增** — 安全漏洞报告流程 |
| **CHANGELOG.md** | ❌ 缺失 | **新增** — 基于已有 git history 生成 |
| **CITATION.cff** | ❌ 缺失 | **可选** — 学术引用格式 |
| **GitHub About** | ⚠️ 需检查 | 仓库描述、Topics、Website、Release |

### 5.3 操作步骤

```
Step 1: git checkout -b governance/03-compliance (基于治理后的 main)
Step 2: 审查并更新 LICENSE（版权年份 → 2025-2026，作者 → XucroYuri）
Step 3: 审查 CONTRIBUTING.md，补充开源贡献流程
Step 4: 新增 CODE_OF_CONDUCT.md (Contributor Covenant 2.1 模板)
Step 5: 新增 SECURITY.md (安全漏洞报告流程)
Step 6: 新增 CHANGELOG.md (基于 git log 反向生成)
Step 7: git add && git commit -m "治理: 开源合规 — CODE_OF_CONDUCT + SECURITY + CHANGELOG + LICENSE 审查"
Step 8: git push origin governance/03-compliance
Step 9: 创建 PR
```

### 5.4 SECURITY.md 模板要点

```
- 支持版本: main 分支（开发中，v0.5.0-dev）
- 报告渠道: GitHub Security Advisory（私有）
- 响应时间: 48 小时内确认，90 天内修复
- 范围: src/news_sentry/ 生产代码、config/ 配置骨架、schemas/ 契约
- 不包含: .planning/ 目录、本地开发文件、.env 本地配置
```

---

## 6. 执行顺序总览

```
                                  ┌──────────────────────────┐
                                  │ Step 0: git pull origin   │
                                  │ main 同步至最新 fcedef3   │
                                  └────────────┬─────────────┘
                                               │
                                  ┌────────────▼─────────────┐
                                  │ Track 1: governance/01-   │
                                  │ privacy-cleanup           │
                                  │ ├ git filter-repo (5文件) │
                                  │ ├ 本机路径修复 (3 commits) │
                                  │ ├ .gitignore 加固         │
                                  │ └ force push → PR → merge │
                                  └────────────┬─────────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          │                    │                    │
               ┌──────────▼──────┐  ┌──────────▼──────┐
               │ Track 2:        │  │ Track 3:        │
               │ governance/02-  │  │ governance/03-  │
               │ structure       │  │ compliance      │
               │                 │  │                 │
               │ 可并行执行       │  │ 可并行执行       │
               └────────┬────────┘  └────────┬────────┘
                          │                    │
                          └──────────┬─────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ 收口: 全部合并至 main │
                          │ 完成治理闭环          │
                          └──────────────────────┘
```

---

## 7. 验证标准

### 7.1 Track 1 验证

- [ ] `git log --all -- CLAUDE-PROMPT.md` 返回空
- [ ] `git log --all -- .omc/skills/` 返回空
- [ ] `git log --all -- .cursor/rules/` 返回空
- [ ] `git log --all -- .codex/automations/` 返回空
- [ ] `git log --all -S "/Users/huachi"` 返回空
- [ ] `git log --all -S "/Users/xuyu"` 返回空
- [ ] `make check` 通过（lint + test）
- [ ] CI pipeline 通过

### 7.2 Track 2 验证

- [ ] `docs/brainstorming/` 不再存在于仓库根目录
- [ ] `docs/superpowers/` 不再存在于仓库根目录
- [ ] `.planning/` 目录本地存在，内容完整
- [ ] `.planning/` 在 `.gitignore` 中
- [ ] `make check` 通过

### 7.3 Track 3 验证

- [ ] `CODE_OF_CONDUCT.md` 存在
- [ ] `SECURITY.md` 存在
- [ ] `CHANGELOG.md` 存在
- [ ] `LICENSE` 版权年份更新
- [ ] `CONTRIBUTING.md` 内容审查通过
- [ ] `make check` 通过

---

## 8. 回滚方案

若 Track 1（filter-repo）执行异常：

```bash
# filter-repo 会在执行前自动创建 bare clone，原仓库不受影响
# 若结果异常，删除新 clone 目录，从 GitHub 重新 clone 即可
git clone https://github.com/XucroYuri/NewsSentry.git NewsSentry-restored
```

若 Track 2/3 有问题，直接关闭 PR、删除分支即可，无破坏性。

---

## 9. 附录

### A. 误提交文件完整路径

1. `CLAUDE-PROMPT.md`
2. `.omc/skills/karpathy-guidelines/SKILL.md`
3. `.omc/skills/karpathy-perspective/SKILL.md`
4. `.cursor/rules/news-sentry-core.mdc`
5. `.codex/automations/news-sentry-test.yaml`

### B. 本机路径渗入 commit

| Commit | 文件 | 路径 |
|--------|------|------|
| `1fb8b2f` | memory/MEMORY.md | `/Users/huachi/.claude/projects/...` |
| `8ce5bbc` | docs/spec/phase-3-test-plan.md | `/Users/xuyu/Code/NewsSentry` |
| `ff423f1` | config/profiles/local-workstation.yaml | `/Users/xuyu/Code/NewsSentry` |

### C. .gitignore 变更清单

```diff
- .cursor/*
- !.cursor/rules/
- !.cursor/rules/**
+ .cursor/

+ CLAUDE-PROMPT.md
+ .codex/
+ .planning/
```

---

> **下一步：** 用户审阅方案，确认后执行 Track 1 → Track 2+3 → 收口。
