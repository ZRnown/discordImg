"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { KeyRound, ShieldCheck } from "lucide-react"
import { toast } from "sonner"

type LicenseStatus = {
  activated: boolean
}

export function LicenseView({ onActivated }: { onActivated: () => Promise<void> | void }) {
  const [licenseKey, setLicenseKey] = useState("")
  const [status, setStatus] = useState<LicenseStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [activating, setActivating] = useState(false)
  const autoEnteringRef = useRef(false)

  const loadStatus = async () => {
    setLoading(true)
    try {
      const response = await fetch("/api/license/status", { credentials: "include" })
      if (!response.ok) {
        throw new Error("无法获取授权状态")
      }
      const data = await response.json()
      setStatus({
        activated: Boolean(data.activated),
      })
    } catch (error: any) {
      toast.error(error?.message || "获取授权状态失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
  }, [])

  useEffect(() => {
    if (!status?.activated) return
    if (autoEnteringRef.current) return
    autoEnteringRef.current = true

    Promise.resolve(onActivated()).catch((error: any) => {
      autoEnteringRef.current = false
      toast.error(error?.message || "进入系统失败，请重试")
    })
  }, [status?.activated, onActivated])

  const handleActivate = async () => {
    const key = licenseKey.trim()
    if (!key) {
      toast.error("请输入授权密钥")
      return
    }

    setActivating(true)
    try {
      const response = await fetch("/api/license/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ key }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.error || "激活失败")
      }

      toast.success(data.msg || "激活成功")
      await onActivated()
    } catch (error: any) {
      toast.error(error?.message || "激活失败")
    } finally {
      setActivating(false)
    }
  }

  return (
    <div className="min-h-screen bg-muted/20 flex items-center justify-center p-6">
      <Card className="w-full max-w-xl">
        <CardHeader className="space-y-2">
          <CardTitle className="flex items-center gap-2 text-2xl">
            <KeyRound className="size-6 text-primary" />
            软件授权激活
          </CardTitle>
          <CardDescription>请输入授权密钥以继续</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {loading ? (
            <div className="text-sm text-muted-foreground">正在加载授权状态...</div>
          ) : (
            <>
              <div className="space-y-3">
                {status?.activated && (
                  <div className="text-sm text-green-600">已激活，正在进入系统...</div>
                )}
                {!status?.activated && (
                  <>
                    <Input
                      placeholder="请输入授权密钥"
                      value={licenseKey}
                      onChange={(e) => setLicenseKey(e.target.value)}
                    />
                    <Button className="w-full" onClick={handleActivate} disabled={activating}>
                      <ShieldCheck className="size-4 mr-2" />
                      {activating ? "激活中..." : "立即激活"}
                    </Button>
                  </>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
