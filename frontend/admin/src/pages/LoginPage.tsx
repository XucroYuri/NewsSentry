import { useState } from "react"
import { AlertTriangleIcon, Loader2Icon, LockIcon } from "lucide-react"

import { loginAdmin } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function LoginPage({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await loginAdmin(username.trim(), password)
      localStorage.setItem("news_sentry_token", result.access_token)
      onLogin(result.access_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center pb-4">
          <LockIcon className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <CardTitle>News Sentry</CardTitle>
          <CardDescription>管理后台</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                disabled={loading}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={loading}
              />
            </div>
            {error && (
              <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                <AlertTriangleIcon className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !username.trim() || !password.trim()}
            >
              {loading && <Loader2Icon className="h-4 w-4 animate-spin" />}
              登 录
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
