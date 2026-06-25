import { useEffect, useState } from "react"
import {
  ActivityIcon,
  BellIcon,
  ClipboardCheckIcon,
  GlobeIcon,
  LayoutDashboardIcon,
  Loader2Icon,
  LogOutIcon,
  MenuIcon,
  NewspaperIcon,
  ServerIcon,
  TagIcon,
  Users2Icon,
} from "lucide-react"

import { useNotificationWebSocket } from "@/hooks/useNotificationWebSocket"
import NotificationToast from "@/components/NotificationToast"
import AnnotationsPage from "@/pages/AnnotationsPage"
import { probeTargets, probeTargetsWithAuth } from "@backend/api/targets"
import { getApiBase, setApiBase } from "@/lib/locals-settings"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import DashboardOverview from "@/pages/DashboardOverview"
import DiagnosticsPage from "@/pages/DiagnosticsPage"
import DraftsPage from "@/pages/DraftsPage"
import EntitiesPage from "@/pages/EntitiesPage"
import EventsPage from "@/pages/EventsPage"
import LoginPage from "@/pages/LoginPage"
import TargetList from "@/pages/TargetList"
import TargetDetail from "@/pages/TargetDetail"
import UsersPage from "@/pages/UsersPage"
import NotificationsPage from "@/pages/NotificationsPage"

type AdminPage = "overview" | "events" | "drafts" | "targets" | "target-detail" | "users" | "diagnostics" | "notifications" | "entities" | "annotations"

function App() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem("news_sentry_token")
  )
  const [authChecked, setAuthChecked] = useState(false)
  const [page, setPage] = useState<AdminPage>("targets")
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null)

  // API 数据源切换
  const [apiSource, setApiSource] = useState<string>(() => getApiBase() ?? "")
  const [apiSourceEditing, setApiSourceEditing] = useState(false)
  const [apiSourceDraft, setApiSourceDraft] = useState("")


  // R2: WebSocket 通知
  const { alerts, clearAlert } = useNotificationWebSocket(token)

  function handleSaveApiSource() {
    const normalized = apiSourceDraft.trim()
    setApiBase(normalized || null)
    setApiSource(normalized)
    setApiSourceEditing(false)
  }

  function handleResetApiSource() {
    setApiBase(null)
    setApiSource("")
    setApiSourceDraft("")
    setApiSourceEditing(false)
  }

  // 首次加载时检查 API 是否免登录即可访问（本地 bypass 模式）
  useEffect(() => {
    async function probeAuth() {
      try {
        const res = await probeTargets()
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
        const res = await probeTargetsWithAuth(token!)
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
    { id: "events", label: "新闻事件", icon: NewspaperIcon },
    { id: "drafts", label: "草稿审核", icon: ClipboardCheckIcon },
    { id: "targets", label: "目标工作台", icon: GlobeIcon },
    { id: "notifications", label: "通知规则", icon: BellIcon },
    { id: "entities", label: "实体管理", icon: TagIcon },
    { id: "annotations", label: "注解日志", icon: ClipboardCheckIcon },
    { id: "diagnostics", label: "可观测性诊断", icon: ActivityIcon },
    { id: "users", label: "用户管理", icon: Users2Icon },
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

        {/* API 数据源切换 */}
        {sidebarOpen && (
          <div className="border-t border-border px-3 py-2">
            <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
              API 数据源
            </div>
            {apiSourceEditing ? (
              <div className="space-y-1.5">
                <input
                  type="text"
                  value={apiSourceDraft}
                  onChange={(e) => setApiSourceDraft(e.target.value)}
                  placeholder="留空 = 同源 FastAPI"
                  className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  autoFocus
                />
                <div className="flex gap-1">
                  <button
                    onClick={handleSaveApiSource}
                    className="flex-1 rounded bg-primary px-2 py-1 text-[10px] text-primary-foreground hover:bg-primary/90"
                  >
                    保存
                  </button>
                  <button
                    onClick={() => setApiSourceEditing(false)}
                    className="rounded bg-secondary px-2 py-1 text-[10px] text-secondary-foreground hover:bg-secondary/80"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <ServerIcon className="h-3 w-3 shrink-0" />
                  {apiSource ? (
                    <span className="truncate" title={apiSource}>
                      {new URL(apiSource).hostname}
                    </span>
                  ) : (
                    <span>同源 FastAPI</span>
                  )}
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => {
                      setApiSourceDraft(apiSource)
                      setApiSourceEditing(true)
                    }}
                    className="rounded bg-secondary px-2 py-1 text-[10px] text-secondary-foreground hover:bg-secondary/80"
                  >
                    编辑
                  </button>
                  {apiSource && (
                    <button
                      onClick={handleResetApiSource}
                      className="rounded bg-destructive/10 px-2 py-1 text-[10px] text-destructive hover:bg-destructive/20"
                    >
                      重置
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

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
          <ErrorBoundary>
          {page === "overview" && <DashboardOverview />}
          {page === "events" && <EventsPage />}
          {page === "drafts" && <DraftsPage />}
          {page === "targets" && (
            <TargetList onNavigate={navigateToTarget} />
          )}
          {page === "target-detail" && selectedTargetId && (
            <TargetDetail targetId={selectedTargetId} onBack={backToTargets} />
          )}
          {page === "users" && <UsersPage />}
          {page === "notifications" && <NotificationsPage />}
          {page === "entities" && <EntitiesPage />}
          {page === "annotations" && <AnnotationsPage />}
          {page === "diagnostics" && <DiagnosticsPage />}
          </ErrorBoundary>

          <NotificationToast alerts={alerts} onDismiss={clearAlert} />

        </div>
      </main>
    </div>
  )
}

export default App
