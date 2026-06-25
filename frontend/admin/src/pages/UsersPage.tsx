import { useEffect, useState, useCallback } from "react"
import {
  AlertTriangleIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  KeyIcon,
  ShieldIcon,
} from "lucide-react"

import {
  fetchAdminUsers,
  createAdminUser,
  deleteAdminUser,
  resetUserPassword,
  type AdminUser,
} from "@/lib/api"
import ErrorBanner from "@/components/ErrorBanner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create user dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [newRole, setNewRole] = useState("viewer")
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  // Reset password dialog
  const [resetOpen, setResetOpen] = useState(false)
  const [resetUsername, setResetUsername] = useState("")
  const [resetPassword, setResetPassword] = useState("")
  const [resetError, setResetError] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAdminUsers()
      setUsers(data.users ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newUsername.trim() || !newPassword.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      await createAdminUser({
        username: newUsername.trim(),
        password: newPassword,
        role: newRole,
      })
      setCreateOpen(false)
      setNewUsername("")
      setNewPassword("")
      setNewRole("viewer")
      await load()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "创建失败")
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(username: string) {
    if (!confirm(`确认删除用户 "${username}"？`)) return
    try {
      await deleteAdminUser(username)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败")
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault()
    if (!resetPassword.trim()) return
    setResetting(true)
    setResetError(null)
    try {
      await resetUserPassword(resetUsername, resetPassword)
      setResetOpen(false)
      setResetUsername("")
      setResetPassword("")
    } catch (err) {
      setResetError(err instanceof Error ? err.message : "重置失败")
    } finally {
      setResetting(false)
    }
  }

  function roleBadgeVariant(role: string): "default" | "secondary" | "destructive" {
    if (role === "admin") return "default"
    if (role === "writer") return "destructive"
    return "secondary"
  }

  function roleLabel(role: string): string {
    if (role === "admin") return "管理员"
    if (role === "writer") return "编辑"
    return "只读"
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error) {
    return <ErrorBanner error={error} onRetry={load} />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">用户管理</h2>
          <p className="text-sm text-muted-foreground">{users.length} 个用户</p>
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <PlusIcon className="h-3.5 w-3.5" />
                新建用户
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>创建用户</DialogTitle>
                <DialogDescription>添加新的管理后台用户账户。</DialogDescription>
              </DialogHeader>
              <form onSubmit={handleCreate}>
                <div className="grid gap-4 py-4">
                  <div className="grid gap-2">
                    <label className="text-sm font-medium leading-none" htmlFor="new-username">用户名</label>
                    <Input id="new-username" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} disabled={creating} />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm font-medium leading-none" htmlFor="new-password">密码</label>
                    <Input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} disabled={creating} placeholder="至少 8 个字符" />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm font-medium leading-none" htmlFor="new-role">角色</label>
                    <select
                      id="new-role"
                      value={newRole}
                      onChange={(e) => setNewRole(e.target.value)}
                      disabled={creating}
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <option value="admin">管理员 (admin)</option>
                      <option value="writer">编辑 (writer)</option>
                      <option value="viewer">只读 (viewer)</option>
                    </select>
                  </div>
                  {createError && (
                    <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                      <AlertTriangleIcon className="h-4 w-4 shrink-0" />
                      {createError}
                    </div>
                  )}
                </div>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={creating}>取消</Button>
                  <Button type="submit" disabled={creating || !newUsername.trim() || !newPassword.trim()}>
                    {creating ? "创建中..." : "创建"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>

          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCwIcon className="h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>

      {/* Reset Password Dialog */}
      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重置密码</DialogTitle>
            <DialogDescription>为用户 "{resetUsername}" 设置新密码。</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleResetPassword}>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <label className="text-sm font-medium leading-none" htmlFor="reset-password">新密码</label>
                <Input id="reset-password" type="password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} disabled={resetting} placeholder="至少 8 个字符" />
              </div>
              {resetError && (
                <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  <AlertTriangleIcon className="h-4 w-4 shrink-0" />
                  {resetError}
                </div>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setResetOpen(false)} disabled={resetting}>取消</Button>
              <Button type="submit" disabled={resetting || !resetPassword.trim()}>
                {resetting ? "重置中..." : "重置"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* User Table */}
      {users.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">暂无用户</CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户名</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.username}>
                    <TableCell className="font-medium">{u.username}</TableCell>
                    <TableCell>
                      <Badge variant={roleBadgeVariant(u.role)}>
                        <ShieldIcon className="mr-1 h-3 w-3" />
                        {roleLabel(u.role)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {u.created_at ? new Date(u.created_at).toLocaleString("zh-CN") : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setResetUsername(u.username)
                            setResetPassword("")
                            setResetError(null)
                            setResetOpen(true)
                          }}
                        >
                          <KeyIcon className="h-3 w-3" />
                          重置密码
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDelete(u.username)}
                        >
                          <Trash2Icon className="h-3 w-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
