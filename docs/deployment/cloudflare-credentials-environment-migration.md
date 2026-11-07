# Cloudflare 凭据迁移到 GitHub Environments

本 PR 只让新 workflow 在凭据迁到 environment 级后仍能工作。**本 PR 未关闭旧入口。**
旧 ref 的 `workflow_dispatch` 使用该 ref 自带的旧 YAML；删除 repo 级 secrets 之前，
旧 ref 依赖这些凭据的 D1 入口仍然存在，合入本 PR 本身不会关闭它们。

本次补齐的绑定：

| Workflow / job | environment |
| --- | --- |
| `deploy.yml` / `cloudflare-data` | `${{ needs.ci.outputs.deployment_environment }}`，仍仅允许 production |
| `deploy.yml` / `verify-production` | `production` |
| `public-translation-backfill.yml` / `public-translation-backfill` | `production`，`execute=true` 仍会写生产 `ns-db` |

`deploy.yml` 的 preview 事件仍只跑 `ci`；production job 集合、步骤命令和
`READER_V1=0` 保持不变。

## 后续迁移步骤（本 PR 不执行）

1. 由维护者在 GitHub Settings → Environments 中，向 `production` 与 `preview`
   两个 environment 分别复制同名 secrets：`CLOUDFLARE_API_KEY`、`CLOUDFLARE_EMAIL`、
   `CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_API_TOKEN`，以及验收所需的
   `CLOUDFLARE_STATE_JSON`（当前 `verify-production` 使用）。此时保留 repo 级原值。
2. 保留 production environment 已有的 required reviewer。安排一次受控验证，
   使用含本补丁的固定 SHA、明确绑定 environment 的只读检查，同时覆盖 production 与 preview；
   production 按既有 reviewer 审批。只核对所需 secrets 是否存在，并以 Cloudflare 只读请求
   确认认证有效；日志不得输出凭据或 state JSON。preview 部署 workflow 只跑 CI，
   不能用它证明 environment secrets 已可读取。
3. 验证成功后，再删除 repo 级上述同名 secrets（包括原先存在的 `CLOUDFLARE_STATE_JSON`）。
   只有完成这一步，旧 ref 依赖 repo 凭据的 D1 入口才关闭；这也会让旧 ref 的生产发布
   失去 repo 凭据。旧 ref 中已绑定 environment 的 job 仍受对应环境的权限与审批约束。
4. 不输出 secret 值地核对 repo 级同名项已删除，记录受控验证的 SHA、环境和结果。

## 迁移后的 CI 例外与审计边界

未绑 environment 的 job 将读不到这些 secrets。唯一保留的例外是 `deploy.yml` 的 `ci`：
其 `Cloudflare Worker dry run` 保留原有 secret 引用，删除 repo 级后这三个 env 会变为空字符串。
锁定的 Wrangler `4.114.0` 在 `dryRun` 时跳过 `requireAuth`，在上传前返回；
`--containers-rollout none` 跳过容器构建与更新，因此该命令不需要 Cloudflare 凭据。
CI 保持不绑 environment，以免被环境审批拦住。

回归测试扫描 `.github/workflows/*.yml` 的所有 job；CI 例外仅限上述步骤，
同一 `ci` job 新增其他 CF secret 引用也会被检查。本次未发现其他未绑定 environment 的
CF 凭据 job。旧 ref 的历史 YAML 不在本次修改范围内，关闭其 repo 凭据入口仍依赖后续删除步骤。
