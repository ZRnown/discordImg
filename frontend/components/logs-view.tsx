"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Trash2 } from "lucide-react"

type LogEntry = {
  timestamp: string
  level: string
  message: string
  module?: string
  func?: string
  raw_line?: string
  type?: string // 用于心跳包
}

export function LogsView({ isActive = true }: { isActive?: boolean }) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const logLimit = 5000

  useEffect(() => {
    let cancelled = false

    const cleanupConnection = () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }

    const loadRecentLogs = async () => {
      try {
        const response = await fetch('/api/logs/recent')
        if (!response.ok) {
          return
        }
        const data = await response.json()
        if (!cancelled) {
          setLogs((data.logs || []).slice(-logLimit))
        }
      } catch (error) {
        console.error('加载历史日志失败:', error)
      }
    }

    const connectToLogStream = () => {
      cleanupConnection()
      if (cancelled) {
        return
      }

      const eventSource = new EventSource('/api/logs/stream')
      eventSourceRef.current = eventSource

      eventSource.onopen = () => {
        if (!cancelled) {
          setIsConnected(true)
        }
      }

      eventSource.onmessage = (event) => {
        if (cancelled) {
          return
        }

        try {
          const logEntry: LogEntry = JSON.parse(event.data)
          if (logEntry.type === 'heartbeat') {
            return
          }

          setLogs((prev) => [...prev, logEntry].slice(-logLimit))
        } catch (error) {
          console.error('解析日志数据失败:', error, event.data)
        }
      }

      eventSource.onerror = (error) => {
        if (cancelled) {
          return
        }

        console.error('日志流连接错误:', error)
        setIsConnected(false)
        cleanupConnection()
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          if (!cancelled) {
            connectToLogStream()
          }
        }, 5000)
      }
    }

    if (!isActive) {
      cleanupConnection()
      setIsConnected(false)
      return
    }

    void loadRecentLogs()
    connectToLogStream()

    return () => {
      cancelled = true
      cleanupConnection()
      setIsConnected(false)
    }
  }, [isActive])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "auto" })
    }
  }, [logs])

  const handleClearLogs = () => {
    setLogs([])
  }

  const getLogLine = (log: LogEntry) => log.raw_line || log.message || ''

  return (
    <div className="space-y-6" data-tutorial="logs-root">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between" data-tutorial="logs-controls">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">实时日志</h2>
          <p className="text-muted-foreground">按 PM2 控制台原始格式展示系统日志</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-sm">
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-muted-foreground">
              {isConnected ? '已连接' : '未连接'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={handleClearLogs}>
            <Trash2 className="size-4" />
            清空
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>系统日志流</CardTitle>
          <CardDescription>
            共 {logs.length} 条记录（最多保留 {logLimit} 条原始日志） • 实时监控中
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[600px] w-full rounded-md border bg-black/90 p-4">
            <div className="space-y-1 font-mono text-[11px] leading-relaxed">
              {logs.map((log, index) => (
                <div
                  key={`${log.timestamp}-${index}`}
                  className="whitespace-pre-wrap break-all text-green-400 hover:bg-white/5 p-1 rounded transition-colors border-b border-white/5 last:border-0"
                >
                  {getLogLine(log)}
                </div>
              ))}
              <div ref={scrollRef} />
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}
