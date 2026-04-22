"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { DashboardView } from "@/components/dashboard-view"
import { AccountsView } from "@/components/accounts-view"
import { ReviewWindowView } from "@/components/review-window-view"
import { ScraperView } from "@/components/scraper-view"
import { ShopsView } from "@/components/shops-view"
import { ImageSearchView } from "@/components/image-search-view"
import { UsersView } from "@/components/users-view"
import { RulesView } from "@/components/rules-view"
import { LogsView } from "@/components/logs-view"
import { LoginView } from "@/components/login-view"
import { AppSidebar } from "@/components/app-sidebar"
import { TutorialTour } from "@/components/tutorial-tour"
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Button } from "@/components/ui/button"
import { LogOut, User, Play, Square } from "lucide-react"
import { toast } from "sonner"
import { buildTutorialSteps } from "@/lib/tutorial-steps"

interface UserData {
  id: number
  username: string
  role: string
  shops: string[]
}

export function AppPageClient() {
  const [currentView, setCurrentView] = useState("dashboard")
  const [currentUser, setCurrentUser] = useState<UserData | null>(null)
  const [loading, setLoading] = useState(true)
  const [botStatus, setBotStatus] = useState<"stopped" | "starting" | "running" | "stopping">("stopped")
  const [tutorialOpen, setTutorialOpen] = useState(false)
  const [tutorialStepIndex, setTutorialStepIndex] = useState(0)

  const hasFetchedUser = useRef(false)

  const tutorialSteps = useMemo(() => buildTutorialSteps(currentUser?.role === "admin"), [currentUser?.role])

  useEffect(() => {
    if (!hasFetchedUser.current) {
      hasFetchedUser.current = true
      checkLoginStatus()
      fetchBotStatus()
    }
  }, [])

  useEffect(() => {
    console.log("BotStatus changed to:", botStatus)
  }, [botStatus])

  useEffect(() => {
    const handleShopsUpdated = () => {
      checkLoginStatus()
    }

    window.addEventListener("shops-updated", handleShopsUpdated)
    return () => window.removeEventListener("shops-updated", handleShopsUpdated)
  }, [])

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
      setTutorialOpen(false)
      setTutorialStepIndex(0)
      toast.success("已登出")
    } catch (_) {
      toast.error("登出失败")
    }
  }

  const handleStartBot = async () => {
    if (!currentUser) {
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
        body: JSON.stringify({ userId: currentUser.id }),
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

  const startTutorial = () => {
    if (!currentUser) {
      toast.error("请先登录")
      return
    }
    setCurrentView("dashboard")
    setTutorialStepIndex(0)
    setTutorialOpen(true)
  }

  const closeTutorial = () => {
    setTutorialOpen(false)
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (!currentUser) {
    return <LoginView onLogin={handleLogin} />
  }

  return (
    <SidebarProvider defaultOpen={true}>
      <AppSidebar
        currentView={currentView}
        setCurrentView={setCurrentView}
        currentUser={currentUser}
        onStartTutorial={startTutorial}
      />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <h1 className="text-lg font-semibold">LinkRadar 链接雷达</h1>
          <div className="flex-1" />
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <User className="size-4" />
              <span>{currentUser.username}</span>
              {currentUser.role === "admin" && (
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

            <Button variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="size-4 mr-1" />
              登出
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <div style={{ display: currentView === "dashboard" ? "block" : "none", height: "100%" }}>
            <DashboardView currentUser={currentUser} isActive={currentView === "dashboard"} />
          </div>

          <div style={{ display: currentView === "accounts" ? "block" : "none", height: "100%" }}>
            <AccountsView isActive={currentView === "accounts"} />
          </div>

          <div style={{ display: currentView === "review-window" ? "block" : "none", height: "100%" }}>
            <ReviewWindowView isActive={currentView === "review-window"} />
          </div>

          <div style={{ display: currentView === "shops" ? "block" : "none", height: "100%" }}>
            <ShopsView currentUser={currentUser} />
          </div>

          <div style={{ display: currentView === "scraper" ? "block" : "none", height: "100%" }}>
            <ScraperView currentUser={currentUser} isActive={currentView === "scraper"} />
          </div>

          <div style={{ display: currentView === "image-search" ? "block" : "none", height: "100%" }}>
            <ImageSearchView />
          </div>

          {currentUser.role === "admin" && (
            <>
              <div style={{ display: currentView === "users" ? "block" : "none", height: "100%" }}>
                <UsersView />
              </div>
              <div style={{ display: currentView === "logs" ? "block" : "none", height: "100%" }}>
                <LogsView isActive={currentView === "logs"} />
              </div>
            </>
          )}
        </main>
      </SidebarInset>
      <TutorialTour
        open={tutorialOpen}
        steps={tutorialSteps}
        stepIndex={tutorialStepIndex}
        currentView={currentView}
        onClose={closeTutorial}
        onStepIndexChange={setTutorialStepIndex}
        onCurrentViewChange={setCurrentView}
      />
    </SidebarProvider>
  )
}
