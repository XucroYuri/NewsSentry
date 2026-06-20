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

因此，当前不能把 preview 自动推进到 main。

## 需要的 Cloudflare API Token 权限

如果选择补齐 API 权限，建议创建一个仅用于审计的 Cloudflare API Token，范围限定到
`news-sentry.com` zone，并至少包含:

- `Zone WAF Read`: 读取 WAF / rulesets / rate limit 规则详情。
- `Access: Apps and Policies Read`: 读取 Access app 与 policy。
- `Access: Apps and Policies Write`: 仅当需要由自动化继续修复 Access app 漂移时启用。

如果只做人工 Dashboard 审计并手动维护 `CLOUDFLARE_STATE_JSON`，可以不提供
write 权限，但 JSON 必须和 Dashboard 中的实际规则一致。

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
