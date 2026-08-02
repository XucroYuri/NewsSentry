# Cloudflare 隔离恢复演练

本演练用于证明 Cloudflare 数据平面可以被恢复，而不只是证明 D1/R2 当前可写。工作流只允许手动触发，源数据只读导出，恢复目标必须是一次性的隔离 D1 数据库。

## 恢复边界

- 源数据库：Preview 使用 `ns-db-preview`，Production 使用 `ns-db`。
- 隔离数据库：只接受 `ns-db-restore-drill-<run_id>-<attempt>`；工具会拒绝生产、Preview、Dev 名称及附加参数。
- 备份对象：D1 export 写入不绑定运行时 Worker 的独立私有 R2 bucket；Preview 使用
  `news-sentry-restore-drills-preview`，Production 使用 `news-sentry-restore-drills`，对象 key 为
  `restore-drills/v1/<environment>/<run_id>-<attempt>.sql`。
- 导入制品：若 `artifact_manifests` 有记录，重新下载 `imports/v1/YYYY/MM/DD/<sha256>.json` 并与 D1 清单核对 SHA-256 和字节数。
- GitHub Artifact：只上传脱敏 JSON 回执；SQL、公开快照正文、导入正文、Wrangler 原始输出均不上载。

Production 演练只允许从 `main` 发起，而且必须存在可核验的导入制品。Preview 可以在尚未产生导入制品时验证 D1 export、R2 往返和隔离恢复，但回执会明确记录 `artifact_coverage: not_available`，不得据此宣称导入制品恢复已经被证明。

## 手动运行

在 GitHub Actions 中选择 `Cloudflare Restore Drill`：

1. 选择 `preview` 或 `production`。
2. 输入本次工作流将 checkout 的完整 40 位 `expected_commit`。
3. 查看 `cloudflare-restore-receipt-<environment>-<run_id>` 回执。

成功回执至少证明：

- D1 export 非空；
- 私有 R2 上传与重新下载的 SHA-256、字节数完全一致；
- export 成功导入隔离 D1；
- 关键表、索引、迁移回执、非空核心行数和公开快照 JSON 完整；
- 关键关系无孤儿记录；
- 脱敏回执的 `evidence.cleanup.verified_absent` 明确为 `true`，证明隔离 D1 在演练结束后已删除。

任何门禁失败都会使任务失败。若清理失败，脱敏回执会追加 `restore_database_cleanup_failed`，需要先删除精确命名的隔离数据库，再处理其他问题。

## 运营约束

- 当前工作流复用对应 GitHub Environment 的 Cloudflare 凭据；在启用定期演练前，应建立独立的 restore-drill Environment 和最小权限 Token。
- 初期仅手动运行。连续成功并确认 R2 生命周期/保留期后，再考虑月度调度。
- R2 中的 SQL backup 属于私有恢复数据，不得设置公开域名、公开读取策略或绑定到运行时 Worker。
- 不使用 D1 Time Travel 做常规演练，因为它会原地改变目标数据库，不能提供隔离恢复证据。
