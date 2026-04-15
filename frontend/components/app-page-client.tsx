"use client"

import { useEffect, useRef, useState } from "react"
import { DashboardView } from "@/components/dashboard-view"
import { AccountsView } from "@/components/accounts-view"
import { ScraperView } from "@/components/scraper-view"
import { ShopsView } from "@/components/shops-view"
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
import { LogOut, User, Play, Square } from "lucide-react"
import { toast } from "sonner"

interface UserData {
  id: number
  username: string
  role: string
  shops: string[]
}

export function AppPageClient({ desktopMode = false }: { desktopMode?: boolean }) {
  const [currentView, setCurrentView] = useState("dashboard")
  const [currentUser, setCurrentUser] = useState<UserData | null>(null)
  const [loading, setLoading] = useState(true)
  const [desktopBootstrapError, setDesktopBootstrapError] = useState<string | null>(null)
  const [backendHealthy, setBackendHealthy] = useState(false)
  const [desktopHealth, setDesktopHealth] = useState<DesktopHealthInfo | null>(null)
  const [startupLogs, setStartupLogs] = useState<DesktopBootstrapLogEntry[]>([])
  const [startupStartedAt, setStartupStartedAt] = useState(() => Date.now())
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [botStatus, setBotStatus] = useState<"stopped" | "starting" | "running" | "stopping">("stopped")
  const hasFetchedUser = useRef(false)
  const effectiveUser = desktopMode
    ? currentUser
    : resolveDesktopUser({ desktopMode, currentUser })

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

    const loadDesktopDiagnostics = async () => {
      const [healthResult, desktopHealthResult, logsResult] = await Promise.allSettled([
        fetch("/api/health", { credentials: "include" }),
        fetch("/api/desktop/health", { credentials: "include" }),
        fetch("/api/logs/recent", { credentials: "include" }),
      ])

      if (cancelled) {
        return
      }

      if (healthResult.status === "fulfilled" && healthResult.value.ok) {
        setBackendHealthy(true)
      } else {
        setBackendHealthy(false)
      }

      if (desktopHealthResult.status === "fulfilled" && desktopHealthResult.value.ok) {
        const data = await desktopHealthResult.value.json().catch(() => null)
        if (!cancelled) {
          setDesktopHealth(data)
        }
      }

      if (logsResult.status === "fulfilled" && logsResult.value.ok) {
        const data = await logsResult.value.json().catch(() => null)
        if (!cancelled) {
          setStartupLogs((data?.logs || []).slice(-40))
        }
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

    void loadDesktopDiagnostics()
    connectLogStream()

    const interval = window.setInterval(() => {
      void loadDesktopDiagnostics()
    }, 1500)

    return () => {
      cancelled = true
      window.clearInterval(interval)
      eventSource?.close()
    }
  }, [desktopMode])

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
            <DashboardView currentUser={effectiveUser} isActive={currentView === "dashboard"} />
          </div>

          <div style={{ display: currentView === "accounts" ? "block" : "none", height: "100%" }}>
            <AccountsView currentUser={effectiveUser} isActive={currentView === "accounts"} />
          </div>

          <div style={{ display: currentView === "shops" ? "block" : "none", height: "100%" }}>
            <ShopsView currentUser={effectiveUser} />
          </div>

          <div style={{ display: currentView === "scraper" ? "block" : "none", height: "100%" }}>
            <ScraperView currentUser={effectiveUser} isActive={currentView === "scraper"} />
          </div>

          <div style={{ display: currentView === "image-search" ? "block" : "none", height: "100%" }}>
            <ImageSearchView />
          </div>

          <div style={{ display: currentView === "logs" ? "block" : "none", height: "100%" }}>
            <LogsView isActive={currentView === "logs"} />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
