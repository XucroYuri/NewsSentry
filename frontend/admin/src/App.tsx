import { useEffect, useState } from "react"
import {
  GlobeIcon,
  LayoutDashboardIcon,
  Loader2Icon,
  LogOutIcon,
  MenuIcon,
} from "lucide-react"

import DashboardOverview from "@/pages/DashboardOverview"
import LoginPage from "@/pages/LoginPage"
import TargetList from "@/pages/TargetList"
import TargetDetail from "@/pages/TargetDetail"

type AdminPage = "overview" | "targets" | "target-detail"

function App() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem("news_sentry_token")
  )
  const [authChecked, setAuthChecked] = useState(false)
  const [page, setPage] = useState<AdminPage>("targets")
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null)

  // 首次加载时检查 API 是否免登录即可访问（本地 bypass 模式）
  useEffect(() => {
    async function probeAuth() {
      try {
        const res = await fetch("/api/v1/admin/targets")
        if (res.ok) {
          // 服务器允许无 token 访问（本地开发模式），跳过登录页
          setToken("local-bypass")
        }
      } catch {
        // 网络错误，保持 token 为 null（显示登录页）
      }
      setAuthChecked(true)
    }
    void probeAuth()
  }, [])

  // 定期检查 token 是否仍然有效
  useEffect(() => {
    if (!token || token === "local-bypass") return
    async function check() {
      try {
        const res = await fetch("/api/v1/admin/targets", {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.status === 401) {
          localStorage.removeItem("news_sentry_token")
          setToken(null)
        }
      } catch {
        // 网络错误不处理，保留 token
      }
    }
    void check()
  }, [token])

  function handleLogin(t: string) {
    setToken(t)
  }

  function handleLogout() {
    localStorage.removeItem("news_sentry_token")
    setToken(null)
  }

  function navigateToTarget(targetId: string) {
    setSelectedTargetId(targetId)
    setPage("target-detail")
  }

  function backToTargets() {
    setSelectedTargetId(null)
    setPage("targets")
  }

  const navItems: Array<{
    id: AdminPage
    label: string
    icon: typeof LayoutDashboardIcon
  }> = [
    { id: "overview", label: "管理总览", icon: LayoutDashboardIcon },
    { id: "targets", label: "目标工作台", icon: GlobeIcon },
  ]

  function headerLabel(): string {
    if (page === "target-detail" && selectedTargetId) {
      return `目标详情: ${selectedTargetId}`
    }
    return navItems.find((n) => n.id === page)?.label ?? "Admin"
  }

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2Icon className="h-5 w-5 animate-spin" />
          <span className="text-sm">验证中...</span>
        </div>
      </div>
    )
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside
        className={`flex flex-col border-r border-border bg-card transition-all duration-200 ${
          sidebarOpen ? "w-56" : "w-14"
        }`}
      >
        <div className="flex h-14 items-center gap-2 border-b border-border px-3">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            aria-label={sidebarOpen ? "收起侧栏" : "展开侧栏"}
          >
            <MenuIcon className="h-4 w-4" />
          </button>
          {sidebarOpen && (
            <span className="text-sm font-semibold tracking-tight">
              News Sentry
            </span>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto py-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setSelectedTargetId(null)
                setPage(item.id)
              }}
              className={`flex w-full items-center gap-3 px-3 py-2 text-sm transition-colors ${
                page === item.id || (page === "target-detail" && item.id === "targets")
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        <div className="border-t border-border px-3 py-2">
          <button
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
            onClick={handleLogout}
          >
            <LogOutIcon className="h-4 w-4 shrink-0" />
            {sidebarOpen && <span>登出</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <header className="flex h-14 items-center gap-4 border-b border-border px-6">
          <h1 className="text-lg font-semibold">{headerLabel()}</h1>
        </header>

        <div className="p-6">
          {page === "overview" && <DashboardOverview />}
          {page === "targets" && (
            <TargetList onNavigate={navigateToTarget} />
          )}
          {page === "target-detail" && selectedTargetId && (
            <TargetDetail targetId={selectedTargetId} onBack={backToTargets} />
          )}
        </div>
      </main>
    </div>
  )
}

export default App
