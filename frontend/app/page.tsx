"use client"

import { useState, useEffect } from "react"
import { DashboardView } from "@/components/dashboard-view"
import { AccountsView } from "@/components/accounts-view"
import { ScraperView } from "@/components/scraper-view"
import { ShopsView } from "@/components/shops-view"
import { ImageSearchView } from "@/components/image-search-view"
import { UsersView } from "@/components/users-view"
import { RulesView } from "@/components/rules-view"
import { LogsView } from "@/components/logs-view"
import { LoginView } from "@/components/login-view"
import { AppSidebar } from "@/components/app-sidebar"
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { Button } from "@/components/ui/button"
import { LogOut, User, Play, Square } from "lucide-react"
import { toast } from "sonner"

interface User {
  id: number
  username: string
  role: string
  shops: string[]
}

export default function Page() {
  const [currentView, setCurrentView] = useState("dashboard")
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [botStatus, setBotStatus] = useState<'stopped' | 'starting' | 'running' | 'stopping'>('stopped')

  useEffect(() => {
    checkLoginStatus()
  }, [])

  const checkLoginStatus = async () => {
    try {
      const response = await fetch('/api/auth/me', {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setCurrentUser(data.user)
      }
    } catch (error) {
      // 未登录或网络错误
    } finally {
      setLoading(false)
    }
  }

  const handleLogin = (user: User) => {
    setCurrentUser(user)
  }

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include'
      })
      setCurrentUser(null)
      setCurrentView("accounts")
      setBotStatus('stopped')
      toast.success("已登出")
    } catch (error) {
      toast.error("登出失败")
    }
  }

  const handleStartBot = async () => {
    if (!currentUser) {
      toast.error("请先登录")
      return
    }

    setBotStatus('starting')
    try {
      // 调用后端启动账号的API
      const response = await fetch('/api/bot/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ userId: currentUser.id })
      })

      if (response.ok) {
        setBotStatus('running')
        toast.success("Discord账号已启动")
      } else {
        const error = await response.json()
        setBotStatus('stopped')
        toast.error(error.error || "启动账号失败")
      }
    } catch (error) {
      setBotStatus('stopped')
      toast.error("网络错误，无法启动账号")
    }
  }

  const handleStopBot = async () => {
    setBotStatus('stopping')
    try {
      const response = await fetch('/api/bot/stop', {
        method: 'POST',
        credentials: 'include'
      })

      if (response.ok) {
        setBotStatus('stopped')
        toast.success("Discord账号已停止")
      } else {
        setBotStatus('running')
        toast.error("停止账号失败")
      }
    } catch (error) {
      setBotStatus('running')
      toast.error("网络错误，无法停止账号")
    }
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
      />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <h1 className="text-lg font-semibold">Discord 自动营销系统</h1>
          <div className="flex-1" />
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <User className="size-4" />
              <span>{currentUser.username}</span>
              {currentUser.role === 'admin' && (
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">管理员</span>
              )}
            </div>

            {/* 机器人控制 */}
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <div className={`w-2 h-2 rounded-full ${
                  botStatus === 'running' ? 'bg-green-500' :
                  botStatus === 'starting' ? 'bg-yellow-500 animate-pulse' :
                  botStatus === 'stopping' ? 'bg-orange-500 animate-pulse' :
                  'bg-gray-400'
                }`} />
                <span>
                  {botStatus === 'running' ? '运行中' :
                   botStatus === 'starting' ? '启动中' :
                   botStatus === 'stopping' ? '停止中' :
                   '已停止'}
                </span>
              </div>

              {botStatus === 'running' ? (
                <Button variant="outline" size="sm" onClick={handleStopBot} disabled={botStatus !== 'running'}>
                  <Square className="size-4 mr-1" />
                  停止账号
                </Button>
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleStartBot}
                  disabled={botStatus === 'starting'}
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
          {currentView === "dashboard" && <DashboardView currentUser={currentUser} />}
          {currentView === "accounts" && <AccountsView />}
          {currentView === "shops" && (currentUser.role === 'admin' || (currentUser.shops && currentUser.shops.length > 0)) && <ShopsView />}
          {currentView === "scraper" && <ScraperView currentUser={currentUser} />}
          {currentView === "image-search" && <ImageSearchView />}
          {currentView === "users" && currentUser.role === 'admin' && <UsersView />}
          {currentView === "logs" && currentUser.role === 'admin' && <LogsView />}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
