# News Sentry v1.0.0 — 安全审计报告

> 日期: 2026-05-12
> 审计范围: src/news_sentry/ (69 Python files)
> 审计标准: OWASP Top 10 (2021)

## 审计结果: PASS

所有 10 类 OWASP 安全风险均通过检查，无高危发现。

---

## 逐项审查

| OWASP 编号 | 风险类别 | 状态 | 说明 |
|-----------|---------|------|------|
| A01 | Broken Access Control | PASS | API Key 认证 + 速率限制；无配置 key 时为开发模式 |
| A02 | Cryptographic Failures | PASS | 无硬编码密钥；API key/SMTP 密码通过环境变量注入 |
| A03 | Injection | PASS | subprocess 调用均使用参数列表（非 shell=True）；YAML 使用 safe_load |
| A04 | Insecure Design | PASS | SandboxEnforcer 5 维权限模型；StopOnRiskError 机制 |
| A05 | Security Misconfiguration | PASS | 无 debug=True 生产代码；SandboxPolicy 默认 deny |
| A06 | Vulnerable Components | PASS | 依赖版本：Pydantic v2, FastAPI 0.110+, PyYAML 6.0+ |
| A07 | Auth Failures | PASS | API Key 验证 + 60 req/min 速率限制 |
| A08 | Data Integrity Failures | PASS | JSON Schema 2020-12 验证所有配置；原子写入防止文件损坏 |
| A09 | Logging Failures | PASS | 无敏感数据写入日志；结构化 JSON 日志 |
| A10 | SSRF | PASS | SandboxEnforcer check_network_host() + deny_by_default |

## 自动化扫描工具

| 工具 | 用途 | 结果 |
|------|------|------|
| `tools/scan_sensitive_data.py` | 扫描 cookie/token/password | PASS — 无敏感数据 |
| `tools/check_no_hardcoded_target.py` | 检查意大利硬编码 | PASS — 无硬编码 |
| `tools/security_audit.py` | OWASP Top 10 快速扫描 | PASS — 无高危 |

## 关键安全机制

1. **沙箱执行**: SandboxEnforcer 5 维权限（命令/网络/文件/浏览器/预算）
2. **Stop-on-Risk**: captcha/认证错误/沙箱违规自动停止
3. **配置验证**: 18 份 JSON Schema 校验所有声明 `# Schema:` 的 YAML 配置
4. **原子写入**: 所有文件写入使用 tmp + rename，防止损坏
5. **环境变量注入**: 密钥、API key、SMTP 密码均通过 `${ENV_VAR}` 解析
6. **零 Token 采集**: ADR-0017 保证采集阶段不调用 AI

## 建议（非阻塞）

- 生产部署时务必设置 `NEWSSENTRY_API_KEY` 环境变量
- 启用 HTTPS（通过反向代理如 Nginx/Caddy）
- 定期运行 `tools/security_audit.py` 和 `make scan-sensitive`
