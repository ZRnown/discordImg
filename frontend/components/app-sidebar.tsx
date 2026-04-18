"use client"

import { BarChart3, Bot, ImageIcon, ScrollText, Search, Settings, Store, Users } from "lucide-react"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar"

interface User {
  id: number
  username: string
  role: string
  shops: string[]
}

type AppView = "dashboard" | "accounts" | "shops" | "scraper" | "image-search" | "logs" | "system-settings"

const baseMenuItems = [
  { id: "dashboard", icon: BarChart3, label: "仪表盘" },
  { id: "accounts", icon: Users, label: "账号与规则" },
  { id: "scraper", icon: Search, label: "微店抓取" },
  { id: "image-search", icon: ImageIcon, label: "以图搜图" },
  { id: "shops", icon: Store, label: "店铺管理" },
  { id: "logs", icon: ScrollText, label: "实时日志" },
  { id: "system-settings", icon: Settings, label: "系统设置" },
]

export function AppSidebar({
  currentView,
  setCurrentView,
  currentUser,
}: {
  currentView: AppView
  setCurrentView: (view: AppView) => void
  currentUser: User | null
}) {
  return (
    <Sidebar>
      <SidebarHeader className="border-b p-4">
        <div className="flex items-center gap-2">
          <Bot className="size-6 text-primary" />
          <div>
            <h2 className="text-lg font-bold">LinkRadar</h2>
            <p className="text-xs text-muted-foreground">Discord 营销桌面端</p>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent data-tutorial="sidebar-main">
        <SidebarGroup>
          <SidebarGroupLabel>主要功能</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {baseMenuItems.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton onClick={() => setCurrentView(item.id as AppView)} isActive={currentView === item.id}>
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t p-4">
        <p className="text-xs text-muted-foreground text-center">v1.0.0 · 技术支持</p>
        <p className="text-xs text-muted-foreground text-center mt-1">微信: OceanSeaWang</p>
        <p className="text-xs text-muted-foreground text-center mt-1">Discord: zrnown</p>
      </SidebarFooter>
    </Sidebar>
  )
}
