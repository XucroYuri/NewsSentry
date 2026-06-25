/**
 * BFF Auth — 登录/鉴权相关 API 调用。
 */

import { apiUrl, throwApiError, AdminApiError } from "./util"

export interface LoginResponse {
  access_token: string
  token_type: string
  role: string
  must_change_password?: boolean
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(apiUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    if (res.status === 429) throw new AdminApiError(429, "登录尝试过于频繁，请 5 分钟后再试")
    await throwApiError(
      res,
      res.status === 401 ? "用户名或密码错误" : `登录失败 (${res.status})`,
    )
  }
  return res.json()
}
