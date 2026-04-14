"use client"

import { useEffect, useState } from "react"

import { AppPageClient } from "@/components/app-page-client"
import { installDesktopApiProxy } from "@/lib/desktop-api"

export function DesktopRootClient() {
  const [proxyReady, setProxyReady] = useState(false)

  useEffect(() => {
    installDesktopApiProxy()
    setProxyReady(true)
  }, [])

  if (!proxyReady) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  return <AppPageClient desktopMode />
}
