"use client"

import { useEffect, useRef, useState } from "react"
import { DashboardView } from "@/components/dashboard-view"
import { AccountsView } from "@/components/accounts-view"
import { ScraperView } from "@/components/scraper-view"
import { ShopsView } from "@/components/shops-view"
import { SystemSettingsView } from "@/components/system-settings-view"
import { ImageSearchView } from "@/components/image-search-view"
import { LogsView } from "@/components/logs-view"
import { LoginView } from "@/components/login-view"
import { DesktopBootstrapPanel } from "@/components/desktop-bootstrap-panel"
import { AppSidebar } from "@/components/app-sidebar"
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Button } from "@/components/ui/button"
import { toBackendUrl } from "@/lib/desktop-api"
import {
  formatDesktopBootstrapDiagnostics,
  type DesktopBootstrapLogEntry,
  type DesktopHealthInfo,
} from "@/lib/desktop-bootstrap-diagnostics"
import { resolveDesktopUser, waitForDesktopUser } from "@/lib/desktop-session"
import { LogOut, User, Play, RefreshCcw, Square } from "lucide-react"
import { toast } from "sonner"

interface UserData {
  id: number
  username: string
  role: string
  shops: string[]
}

type AppView = "dashboard" | "accounts" | "shops" | "scraper" | "image-search" | "logs" | "system-settings"

const INITIAL_VIEW_REFRESH_TOKENS: Record<AppView, number> = {
  dashboard: 0,
  accounts: 0,
  shops: 0,
  scraper: 0,
  "image-search": 0,
  logs: 0,
  "system-settings": 0,
}

export function AppPageClient({ desktopMode = false }: { desktopMode?: boolean }) {
  const [currentView, setCurrentView] = useState<AppView>("dashboard")
  const [currentUser, setCurrentUser] = useState<UserData | null>(null)
  const [loading, setLoading] = useState(true)
  const [desktopBootstrapError, setDesktopBootstrapError] = useState<string | null>(null)
  const [backendHealthy, setBackendHealthy] = useState(false)
  const [desktopHealth, setDesktopHealth] = useState<DesktopHealthInfo | null>(null)
  const [startupLogs, setStartupLogs] = useState<DesktopBootstrapLogEntry[]>([])
  const [startupStartedAt, setStartupStartedAt] = useState(() => Date.now())
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [botStatus, setBotStatus] = useState<"stopped" | "starting" | "running" | "stopping">("stopped")
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [viewRefreshTokens, setViewRefreshTokens] = useState<Record<AppView, number>>(() => ({
    ...INITIAL_VIEW_REFRESH_TOKENS,
  }))
  const hasFetchedUser = useRef(false)
  const effectiveUser = desktopMode
    ? currentUser
    : resolveDesktopUser({ desktopMode, currentUser })
  const desktopBootstrapComplete = !desktopMode || Boolean(
    desktopHealth?.bootstrap_state?.completed
    || desktopHealth?.bootstrap_state?.stage === "ready"
    || desktopHealth?.ai_model_ready
    || desktopHealth?.bootstrap_state?.stage === "skipped"
  )

  useEffect(() => {
    if (!desktopMode) {
      return
    }

    setLoading(!(currentUser && backendHealthy && desktopBootstrapComplete))
  }, [desktopMode, currentUser, backendHealthy, desktopBootstrapComplete])

  useEffect(() => {
    if (!hasFetchedUser.current) {
      hasFetchedUser.current = true
      void initializeSession()
    }
  }, [desktopMode])

  useEffect(() => {
    console.log("BotStatus changed to:", botStatus)
  }, [botStatus])

  useEffect(() => {
    if (!desktopMode) {
      return
    }

    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startupStartedAt) / 1000)))
    }, 1000)

    setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startupStartedAt) / 1000)))
    return () => window.clearInterval(timer)
  }, [desktopMode, startupStartedAt])

  useEffect(() => {
    const handleShopsUpdated = () => {
      if (desktopMode) {
        void hydrateDesktopUser()
      } else {
        void checkLoginStatus()
      }
    }

    window.addEventListener("shops-updated", handleShopsUpdated)
    return () => window.removeEventListener("shops-updated", handleShopsUpdated)
  }, [desktopMode])

  useEffect(() => {
    if (!desktopMode) {
      return
    }

    let cancelled = false
    let eventSource: EventSource | null = null

    const loadDesktopDiagnostics = async ({ includeLogs = false }: { includeLogs?: boolean } = {}) => {
      const [healthResponse, desktopHealthResponse] = await Promise.all([
        fetch("/api/health", { credentials: "include" }).catch(() => null),
        fetch("/api/desktop/health", { credentials: "include" }).catch(() => null),
      ])

      if (cancelled) {
        return
      }

      setBackendHealthy(Boolean(healthResponse?.ok))

      if (desktopHealthResponse?.ok) {
        const data = await desktopHealthResponse.json().catch(() => null)
        if (!cancelled) {
          setDesktopHealth(data)
        }
      }

      if (!includeLogs) {
        return
      }

      const logsResponse = await fetch("/api/logs/recent", { credentials: "include" }).catch(() => null)
      if (cancelled || !logsResponse?.ok) {
        return
      }

      const data = await logsResponse.json().catch(() => null)
      if (!cancelled) {
        setStartupLogs((data?.logs || []).slice(-40))
      }
    }

    const connectLogStream = () => {
      eventSource = new EventSource(toBackendUrl("/api/logs/stream"))

      eventSource.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          if (entry?.type === "heartbeat") {
            return
          }
          setStartupLogs((prev) => [...prev, entry].slice(-40))
        } catch {
          // ignored
        }
      }

      eventSource.onerror = () => {
        eventSource?.close()
      }
    }

    void loadDesktopDiagnostics({ includeLogs: true })
    connectLogStream()

    const intervalMs = desktopBootstrapComplete ? 10000 : 3000
    const interval = window.setInterval(() => {
      void loadDesktopDiagnostics()
    }, intervalMs)

    return () => {
      cancelled = true
      window.clearInterval(interval)
      eventSource?.close()
    }
  }, [desktopMode, desktopBootstrapComplete])

  useEffect(() => {
    if (!desktopMode) {
      return
    }

    const handleRefreshShortcut = (event: KeyboardEvent) => {
      const loweredKey = event.key.toLowerCase()
      const isRefreshShortcut =
        event.key === "F5" || ((event.ctrlKey || event.metaKey) && loweredKey === "r")

      if (!isRefreshShortcut || isRefreshing) {
        return
      }

      event.preventDefault()
      void handleManualRefresh()
    }

    window.addEventListener("keydown", handleRefreshShortcut)
    return () => window.removeEventListener("keydown", handleRefreshShortcut)
  }, [desktopMode, currentView, isRefreshing])

  const initializeSession = async () => {
    if (desktopMode) {
      await hydrateDesktopUser()
    } else {
      await checkLoginStatus()
    }
    await fetchBotStatus()
  }

  const checkLoginStatus = async () => {
    try {
      const response = await fetch("/api/auth/me", {
        credentials: "include",
      })
      if (response.ok) {
        const data = await response.json()
        setCurrentUser(data.user)
      }
    } catch (_) {
      // ignored
    } finally {
      setLoading(false)
    }
  }

  const hydrateDesktopUser = async () => {
    try {
      const user = await waitForDesktopUser()
      if (user) {
        setCurrentUser(user)
        setDesktopBootstrapError(null)
      } else {
        setCurrentUser(null)
        setDesktopBootstrapError("桌面后端未就绪，当前不能执行添加账号、添加店铺等操作。请检查 5001 端口是否被占用，或稍后重试。")
      }
    } catch (_) {
      setCurrentUser(null)
      setDesktopBootstrapError("桌面后端启动失败，当前无法建立本地会话。请重启桌面端后重试。")
    } finally {
      setLoading(false)
    }
  }

  const fetchBotStatus = async () => {
    try {
      const response = await fetch("/api/bot/status")
      if (response.ok) {
        const data = await response.json()
        if (data.running) {
          setBotStatus("running")
        } else {
          setBotStatus("stopped")
        }
      }
    } catch (error) {
      console.error("获取机器人状态失败:", error)
    }
  }

  const handleLogin = (user: UserData) => {
    setCurrentUser(user)
  }

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      })
      setCurrentUser(null)
      setCurrentView("accounts")
      setBotStatus("stopped")
      toast.success("已登出")
    } catch (_) {
      toast.error("登出失败")
    }
  }

  const handleStartBot = async () => {
    const user = effectiveUser
    if (!user) {
      toast.error("请先登录")
      return
    }

    console.log("开始启动机器人...")
    setBotStatus("starting")
    try {
      const response = await fetch("/api/bot/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ userId: user.id }),
      })

      console.log("启动API响应:", response.status, response.ok)

      if (response.ok) {
        console.log("设置状态为running")
        setBotStatus("running")
        setTimeout(() => fetchBotStatus(), 100)
        toast.success("Discord账号已启动")
        window.dispatchEvent(new Event("bot-status-changed"))
      } else {
        const error = await response.json()
        console.log("启动失败，错误:", error)
        setBotStatus("stopped")
        toast.error(error.error || "启动账号失败")
      }
    } catch (error) {
      console.log("网络错误:", error)
      setBotStatus("stopped")
      toast.error("网络错误，无法启动账号")
    }
  }

  const handleStopBot = async () => {
    setBotStatus("stopping")
    try {
      const response = await fetch("/api/bot/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      })

      if (response.ok) {
        setBotStatus("stopped")
        toast.success("Discord账号已停止")
        window.dispatchEvent(new Event("bot-status-changed"))
      } else {
        setBotStatus("running")
        toast.error("停止账号失败")
      }
    } catch (_) {
      setBotStatus("running")
      toast.error("网络错误，无法停止账号")
    }
  }

  const handleManualRefresh = async () => {
    if (isRefreshing) {
      return
    }

    setIsRefreshing(true)

    try {
      await initializeSession()
      setViewRefreshTokens((previous) => ({
        ...previous,
        [currentView]: previous[currentView] + 1,
      }))
      toast.success("已刷新当前页面数据")
    } catch (_) {
      toast.error("刷新失败，请稍后重试")
    } finally {
      setIsRefreshing(false)
    }
  }

  const resetDesktopBootstrap = () => {
    setLoading(true)
    setCurrentUser(null)
    setDesktopBootstrapError(null)
    setBackendHealthy(false)
    setDesktopHealth(null)
    setStartupLogs([])
    setStartupStartedAt(Date.now())
    void initializeSession()
  }

  const desktopDiagnosticText = formatDesktopBootstrapDiagnostics({
    loading,
    elapsedSeconds,
    backendHealthy,
    sessionReady: Boolean(currentUser),
    bootstrapError: desktopBootstrapError,
    desktopHealth,
    logs: startupLogs,
  })

  if (loading) {
    return (
      <DesktopBootstrapPanel
        loading={loading}
        elapsedSeconds={elapsedSeconds}
        backendHealthy={backendHealthy}
        sessionReady={Boolean(currentUser)}
        bootstrapError={desktopBootstrapError}
        desktopHealth={desktopHealth}
        logs={startupLogs}
        diagnosticText={desktopDiagnosticText}
        onRetry={resetDesktopBootstrap}
      />
    )
  }

  if (!desktopMode && !currentUser) {
    return <LoginView onLogin={handleLogin} />
  }

  if (desktopMode && desktopBootstrapError) {
    return (
      <DesktopBootstrapPanel
        loading={false}
        elapsedSeconds={elapsedSeconds}
        backendHealthy={backendHealthy}
        sessionReady={Boolean(currentUser)}
        bootstrapError={desktopBootstrapError}
        desktopHealth={desktopHealth}
        logs={startupLogs}
        diagnosticText={desktopDiagnosticText}
        onRetry={resetDesktopBootstrap}
      />
    )
  }

  if (!effectiveUser) {
    return null
  }

  return (
    <SidebarProvider defaultOpen={true}>
      <AppSidebar
        currentView={currentView}
        setCurrentView={setCurrentView}
        currentUser={effectiveUser}
      />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <h1 className="text-lg font-semibold">{desktopMode ? "LinkRadar 桌面版" : "LinkRadar 链接雷达"}</h1>
          <div className="flex-1" />
          <div className="flex items-center gap-3">
            {desktopMode && (
              <Button variant="outline" size="sm" onClick={handleManualRefresh} disabled={isRefreshing}>
                <RefreshCcw className={`size-4 mr-1 ${isRefreshing ? "animate-spin" : ""}`} />
                刷新数据
              </Button>
            )}

            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <User className="size-4" />
              <span>{effectiveUser.username}</span>
              {effectiveUser.role === "admin" && (
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">管理员</span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <div
                  className={`w-2 h-2 rounded-full ${
                    botStatus === "running"
                      ? "bg-green-500"
                      : botStatus === "starting"
                        ? "bg-yellow-500 animate-pulse"
                        : botStatus === "stopping"
                          ? "bg-orange-500 animate-pulse"
                          : "bg-gray-400"
                  }`}
                />
                <span>
                  {botStatus === "running"
                    ? "运行中"
                    : botStatus === "starting"
                      ? "启动中"
                      : botStatus === "stopping"
                        ? "停止中"
                        : "已停止"}
                </span>
                <span className="text-[10px] text-gray-500 ml-2">(状态: {botStatus})</span>
              </div>

              {botStatus === "running" ? (
                <Button variant="outline" size="sm" onClick={handleStopBot} disabled={botStatus !== "running"}>
                  <Square className="size-4 mr-1" />
                  停止账号
                </Button>
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleStartBot}
                  disabled={botStatus === "starting"}
                  className="bg-green-600 hover:bg-green-700"
                >
                  <Play className="size-4 mr-1" />
                  启动账号
                </Button>
              )}
            </div>

            {!desktopMode && (
              <Button variant="outline" size="sm" onClick={handleLogout}>
                <LogOut className="size-4 mr-1" />
                登出
              </Button>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <div style={{ display: currentView === "dashboard" ? "block" : "none", height: "100%" }}>
            <DashboardView
              key={`dashboard-${viewRefreshTokens.dashboard}`}
              currentUser={effectiveUser}
              isActive={currentView === "dashboard"}
            />
          </div>

          <div style={{ display: currentView === "accounts" ? "block" : "none", height: "100%" }}>
            <AccountsView
              key={`accounts-${viewRefreshTokens.accounts}`}
              currentUser={effectiveUser}
              isActive={currentView === "accounts"}
            />
          </div>

          <div style={{ display: currentView === "shops" ? "block" : "none", height: "100%" }}>
            <ShopsView key={`shops-${viewRefreshTokens.shops}`} currentUser={effectiveUser} />
          </div>

          <div style={{ display: currentView === "scraper" ? "block" : "none", height: "100%" }}>
            <ScraperView
              key={`scraper-${viewRefreshTokens.scraper}`}
              currentUser={effectiveUser}
              isActive={currentView === "scraper"}
            />
          </div>

          <div style={{ display: currentView === "image-search" ? "block" : "none", height: "100%" }}>
            <ImageSearchView key={`image-search-${viewRefreshTokens["image-search"]}`} />
          </div>

          <div style={{ display: currentView === "logs" ? "block" : "none", height: "100%" }}>
            <LogsView key={`logs-${viewRefreshTokens.logs}`} isActive={currentView === "logs"} />
          </div>

          <div style={{ display: currentView === "system-settings" ? "block" : "none", height: "100%" }}>
            <SystemSettingsView key={`system-settings-${viewRefreshTokens["system-settings"]}`} />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
