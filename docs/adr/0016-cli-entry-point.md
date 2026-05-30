# ADR-0016 — CLI 入口正式锁定

| 属性 | 值 |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-05-09 |
| **决策者** | 项目用户（通过 SPEC 规划确认） |
| **关联 ADR** | ADR-0006（Hermes 运行时，已关闭部分 CLI backlog）、ADR-0012（Python）、ADR-0013（包结构）、ADR-0015（配置优先级） |
| **关联文档** | [docs/spec/phase-2-runtime-carrier-alignment.md](../spec/phase-2-runtime-carrier-alignment.md)、[src/news_sentry/cli/](../../src/news_sentry/cli/) |

---

## 背景

ADR-0006 确立了 Hermes 为主调度器、OpenClaw 为 Skill 运行时，但未明确规定从 CLI 触发 bounded run 的具体命令格式。`docs/roadmap/development-plan.md` 中有 `CLI-001` 遗留 backlog。本 ADR 正式锁定命令格式并关闭该 backlog。

---

## 决策

**CLI 入口命令格式：**

```
python -m news_sentry.cli run --target <target_id> --stage <stage> --profile <profile_id>
```

**参数说明：**

| 参数 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `--target` | 是 | 任意 target_id | 对应 `config/targets/{id}.yaml` |
| `--stage` | 是 | `collect \| filter \| judge \| output \| all` | 对应 pipeline_stage 枚举 |
| `--run-id` | 否 | UUID 字符串 | 指定 run_id，默认自动生成 |
| `--dry-run` | 否 | flag | 不写文件、不调用 AI，只打印配置与执行计划 |
| `--log-level` | 否 | `DEBUG \| INFO \| WARNING` | 默认 INFO |
| `--config-dir` | 否 | 路径 | 覆盖默认项目根目录（该目录下应包含 `config/` 和 `schemas/`） |
| `--profile` | 否 | `local-workstation \| cloud-vps` 等 | 覆盖 `NEWSSENTRY_PROFILE`；默认 `local-workstation` |

**Python 包入口点（pyproject.toml）：**

```toml
[project.scripts]
news-sentry = "news_sentry.cli:main"
```

**子命令扩展预留（Phase 4+）：**

```
python -m news_sentry.cli skill list               # 列出已注册 Skill
python -m news_sentry.cli tool list                # 列出已注册 ToolManifest
python -m news_sentry.cli run ...    # 主运行命令（本 ADR 锁定）
python -m news_sentry.cli validate --config <path> # 校验 config YAML 对 schema
```

**bounded run 语义（不可变）：**

- `--stage all` 等价于按 `collect → filter → judge → output` 顺序执行全部阶段
- 每次 `run` 生成一个唯一 `run_id`（UUID4）
- 运行结束后写入 `{target}/logs/run-{run_id}.json`
- Host 调用 `python -m news_sentry.cli run` 后可通过退出码判断状态：`0`=成功，`1`=部分失败，`2`=配置错误，`3`=沙箱阻断

**关闭 CLI-001：** `docs/roadmap/development-plan.md §CLI-001 backlog` 中"CLI 入口格式待定"问题由本 ADR 解决，不再在 backlog 中追踪。

---

## 后果

**正面：** `--target` 参数成为"国家可替换"的运行时入口，无需改代码；`--stage` 分阶段执行便于调试和增量测试

**负面：** 命令格式锁定后，Hermes/OpenClaw 的调度配置（`config/runtime/hermes.yaml`）需与此格式对齐，若后续需要 daemon 模式需新建 ADR
