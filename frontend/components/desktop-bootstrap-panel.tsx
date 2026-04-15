"use client"

import { useState } from "react"
import { AlertTriangle, CheckCircle2, Clock3, Copy, LoaderCircle, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  buildDesktopBootstrapSummary,
  type DesktopBootstrapLogEntry,
  type DesktopHealthInfo,
} from "@/lib/desktop-bootstrap-diagnostics"

const getStepIcon = (state: "done" | "active" | "pending" | "error") => {
  if (state === "done") return <CheckCircle2 className="size-4 text-green-600" />
  if (state === "error") return <AlertTriangle className="size-4 text-red-600" />
  if (state === "active") return <LoaderCircle className="size-4 animate-spin text-blue-600" />
  return <Clock3 className="size-4 text-muted-foreground" />
}

const getLogLine = (entry: DesktopBootstrapLogEntry) => entry.raw_line || entry.message || ""

export function DesktopBootstrapPanel({
  loading,
  elapsedSeconds,
  backendHealthy,
  sessionReady,
  bootstrapError,
  desktopHealth,
  logs,
  diagnosticText,
  onRetry,
}: {
  loading: boolean
  elapsedSeconds: number
  backendHealthy: boolean
  sessionReady: boolean
  bootstrapError?: string | null
  desktopHealth?: DesktopHealthInfo | null
  logs: DesktopBootstrapLogEntry[]
  diagnosticText: string
  onRetry: () => void
}) {
  const [copying, setCopying] = useState(false)

  const summary = buildDesktopBootstrapSummary({
    loading,
    elapsedSeconds,
    backendHealthy,
    sessionReady,
    bootstrapError,
    desktopHealth,
    logs,
  })

  const handleCopy = async () => {
    try {
      setCopying(true)
      await navigator.clipboard.writeText(diagnosticText)
      toast.success("诊断信息已复制")
    } catch {
      toast.error("复制失败")
    } finally {
      setCopying(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-muted/20">
      <div className="w-full max-w-4xl grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{summary.title}</CardTitle>
            <CardDescription>{summary.description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="rounded-md border bg-muted/40 p-4 text-sm text-foreground">
              {summary.hint}
            </div>

            <div className="space-y-3">
              {summary.steps.map((step) => (
                <div key={step.label} className="flex items-start gap-3 rounded-md border p-3">
                  <div className="mt-0.5">{getStepIcon(step.state)}</div>
                  <div className="min-w-0">
                    <div className="font-medium">{step.label}</div>
                    <div className="text-sm text-muted-foreground">{step.detail}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-3">
              <Button onClick={onRetry}>
                <RefreshCw className="size-4 mr-1" />
                重试连接
              </Button>
              <Button variant="outline" onClick={handleCopy} disabled={copying}>
                <Copy className="size-4 mr-1" />
                {copying ? "复制中" : "复制诊断信息"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>最近启动日志</CardTitle>
            <CardDescription>
              即使没有黑窗，也可以直接把这里最后几行发出来。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[420px] w-full rounded-md border bg-black/90 p-4">
              <div className="space-y-1 font-mono text-[11px] leading-relaxed">
                {logs.length > 0 ? (
                  logs.map((log, index) => (
                    <div
                      key={`${log.timestamp || "log"}-${index}`}
                      className="whitespace-pre-wrap break-all text-green-400"
                    >
                      {getLogLine(log)}
                    </div>
                  ))
                ) : (
                  <div className="text-zinc-400">
                    还没有拿到后端日志。通常表示 5001 还没起来，或者后端在更早的地方就退出了。
                  </div>
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
