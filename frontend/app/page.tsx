"use client"

import { useState } from "react"
import { DashboardView } from "@/components/dashboard-view"
import { AccountsView } from "@/components/accounts-view"
import { ScraperView } from "@/components/scraper-view"
import { ImageSearchView } from "@/components/image-search-view"
import { SimilarityTestView } from "@/components/similarity-test-view"
import { RulesView } from "@/components/rules-view"
import { LogsView } from "@/components/logs-view"
import { AppSidebar } from "@/components/app-sidebar"
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"

export default function Page() {
  const [currentView, setCurrentView] = useState("accounts")

  return (
    <SidebarProvider defaultOpen={true}>
      <AppSidebar currentView={currentView} setCurrentView={setCurrentView} />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <h1 className="text-lg font-semibold">Discord 自动营销系统</h1>
        </header>
        <main className="flex-1 overflow-auto p-6">
          {currentView === "accounts" && <AccountsView />}
          {currentView === "scraper" && <ScraperView />}
          {currentView === "image-search" && <ImageSearchView />}
          {currentView === "similarity-test" && <SimilarityTestView />}
          {currentView === "logs" && <LogsView />}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
