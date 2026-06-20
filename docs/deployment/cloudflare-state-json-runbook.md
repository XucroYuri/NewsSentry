# Cloudflare State JSON Runbook

> 日期: 2026-06-20
> 用途: 为 production deployed-surface audit 提供可审计的 `CLOUDFLARE_STATE_JSON`

## 结论

`CLOUDFLARE_STATE_JSON` 不是普通配置开关，而是 production 发布链的安全证据输入。
只有在 Cloudflare Access、响应头、rate limit、WAF 路径覆盖都能被 Dashboard
或 API 证明确认后，才可以写入 GitHub production secret。

当前本地状态:

- Cloudflare MCP 凭据可以读取并创建 Access app。
- Cloudflare MCP 凭据可以列出 zone rulesets 名称。
- Cloudflare MCP 凭据不能读取 ruleset 详情:
  - `GET /zones/{zone_id}/rulesets/phases/http_ratelimit/entrypoint`
  - `GET /zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint`
  - `GET /zones/{zone_id}/rulesets/{ruleset_id}`
- 本地 `.env` 和 `/Users/xuyu/.news-sentry/env` 中的 `CLOUDFLARE_API_TOKEN`
  目前为空值，无法作为更高权限只读 token 使用。

因此，正常情况下不能把 preview 自动推进到 main。2026-06-20 这次发布允许使用
`TEMPORARY_CLOUDFLARE_STATE_BYPASS` 做一次性应急放行，但这不是安全证据，
发布后仍必须补齐真实 `CLOUDFLARE_STATE_JSON`。

## 需要的 Cloudflare API Token 权限

如果选择补齐 API 权限，建议创建一个仅用于审计的 Cloudflare API Token，范围限定到
`news-sentry.com` zone，并至少包含:

- `Zone WAF Read`: 读取 WAF / rulesets / rate limit 规则详情。
- `Access: Apps and Policies Read`: 读取 Access app 与 policy。
- `Access: Apps and Policies Write`: 仅当需要由自动化继续修复 Access app 漂移时启用。

如果只做人工 Dashboard 审计并手动维护 `CLOUDFLARE_STATE_JSON`，可以不提供
write 权限，但 JSON 必须和 Dashboard 中的实际规则一致。

Cloudflare Dashboard 获取 token 的推荐路径:

1. 进入 Cloudflare Dashboard -> My Profile -> API Tokens -> Create Token。
2. 选择 Custom token。
3. Permissions 至少添加:
   - Zone -> Zone WAF -> Read
   - Account -> Access: Apps and Policies -> Read
   - Zone -> Zone -> Read
4. Zone Resources 限定为 Include -> Specific zone -> `news-sentry.com`。
5. 创建后复制 token，只写入本机 shell 或安全 secret store，不提交仓库。

本机临时使用:

```bash
export CLOUDFLARE_API_TOKEN="你的只读审计 token"
```

如果需要让 GitHub Actions 直接生成或复核 Cloudflare state，可把同一个 token
配置成 GitHub environment secret，例如 production 环境的 `CLOUDFLARE_API_TOKEN`。
当前 workflow 只要求最终 `CLOUDFLARE_STATE_JSON`，所以更推荐本地生成 JSON 后
只上传 JSON 证据。

## 必须证明的字段

GitHub Secret `CLOUDFLARE_STATE_JSON` 需要是合法 JSON，并至少包含:

```json
{
  "access_read_ok": true,
  "access_write_ok": true,
  "protected_prefixes": [
    "/api/v1/auth/",
    "/api/v1/admin/",
    "/api/v1/status",
    "/api/v1/runtime/info"
  ],
  "response_headers": [
    "strict-transport-security",
    "content-security-policy",
    "referrer-policy",
    "permissions-policy",
    "x-frame-options"
  ],
  "rate_limit_paths": [
    "/api/v1/auth/login",
    "/api/v1/auth/token"
  ],
  "waf_path_prefixes": [
    "/api/v1/auth/",
    "/api/v1/admin/"
  ]
}
```

## 当前已确认的 Access 覆盖

Cloudflare Access apps 已可读，当前包含:

- `News Sentry Admin Production`
  - `news-sentry.com/admin*`
  - `news-sentry.com/api/v1/admin*`
  - `news-sentry.com/api/v1/auth*`
  - `news-sentry.com/api/v1/status`
  - `news-sentry.com/api/v1/runtime/info`
- `News Sentry Admin Preview`
  - `preview.news-sentry.com/admin*`
  - `preview.news-sentry.com/api/v1/admin*`
  - `preview.news-sentry.com/api/v1/auth*`
  - `preview.news-sentry.com/api/v1/status`
  - `preview.news-sentry.com/api/v1/runtime/info`
- `News Sentry Admin Root Production`
  - `news-sentry.com/admin/`
- `News Sentry Admin Root Preview`
  - `preview.news-sentry.com/admin/`

## 设置 GitHub Secret

优先使用仓库工具自动生成 JSON:

```bash
uv run --extra dev --extra api \
  python tools/build_cloudflare_state_json.py \
    --zone-id 440f9b3a531ab3a93a3e749425b0a646 \
    --base-url https://news-sentry.com \
    --output /tmp/news-sentry-cloudflare-state.json
```

该工具读取顺序:

1. `--api-token`
2. `CLOUDFLARE_API_TOKEN` / `CF_API_TOKEN`
3. `wrangler auth token --json`

如果当前凭据不能读取 ruleset 详情，工具会失败，不会生成伪通过证据。

完成 Dashboard/API 审计后，把 JSON 写入 production 环境 secret:

```bash
gh secret set CLOUDFLARE_STATE_JSON \
  --repo XucroYuri/NewsSentry \
  --env production \
  < /path/to/news-sentry-cloudflare-state.json
```

随后在本地先跑同一个审计命令:

```bash
uv run --no-project --with 'httpx[socks]' --with pyyaml \
  python tools/deployed_surface_audit.py \
    --policy config/security/deployment-surface-policy.yaml \
    --cloudflare-state-json /path/to/news-sentry-cloudflare-state.json \
    --base-url https://news-sentry.com \
    --output /tmp/news-sentry-deployed-surface-audit.json \
    --timeout-seconds 90
```

只有该命令无 finding，才允许进入 preview -> main 发布链。

## 临时一次性放行

仅当需要先恢复线上部署、且已经确认 Cloudflare Access 至少保护了 admin/auth/status/runtime
高风险入口时，可以使用一次性 bypass。该 bypass 会使用
`docs/deployment/cloudflare-state-json.example.json` 让 deployed-surface audit 继续执行，
并在 GitHub Actions 日志中输出 `TEMPORARY_CLOUDFLARE_STATE_BYPASS` warning。

触发条件之一即可:

- 手动运行 workflow 时选择 production，并把
  `allow_temporary_cloudflare_state_bypass` 设置为 `true`。
- 或发布提交消息包含 `[temporary-cloudflare-state-bypass]`。

示例:

```bash
gh workflow run deploy.yml \
  --repo XucroYuri/NewsSentry \
  --ref main \
  -f environment=production \
  -f allow_temporary_cloudflare_state_bypass=true
```

注意:

- 这是应急发布开关，不是长期门禁策略。
- 下一次普通 production deploy 如果没有提交消息标记或手动输入，仍会要求真实
  `CLOUDFLARE_STATE_JSON`。
- 发布完成后必须尽快用上文的 Cloudflare token 或 Dashboard 审计方式补齐 production
  environment secret。
