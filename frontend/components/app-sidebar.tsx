"use client"

import { LayoutDashboard, Users, Search, ImageIcon, ListTree, ScrollText, Bot, Settings, TestTube } from "lucide-react"
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

const menuItems = [
  { id: "accounts", icon: Users, label: "账号与规则" },
  { id: "scraper", icon: Search, label: "微店抓取" },
  { id: "image-search", icon: ImageIcon, label: "以图搜图" },
  { id: "similarity-test", icon: TestTube, label: "相似度测试" },
  { id: "logs", icon: ScrollText, label: "实时日志" },
]

export function AppSidebar({
  currentView,
  setCurrentView,
}: {
  currentView: string
  setCurrentView: (view: string) => void
}) {
  return (
    <Sidebar>
      <SidebarHeader className="border-b p-4">
        <div className="flex items-center gap-2">
          <Bot className="size-6 text-primary" />
          <div>
            <h2 className="text-lg font-bold">Discord 营销</h2>
            <p className="text-xs text-muted-foreground">智能自动回复系统</p>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>主要功能</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton onClick={() => setCurrentView(item.id)} isActive={currentView === item.id}>
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
        <p className="text-xs text-muted-foreground text-center">v1.0.0 • 技术支持</p>
      </SidebarFooter>
    </Sidebar>
  )
}
