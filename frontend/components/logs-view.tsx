"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Pause, Play, Trash2, RefreshCw } from "lucide-react"

type LogEntry = {
  timestamp: string
  level: string
  message: string
  module?: string
  func?: string
  type?: string // 用于心跳包
}

export function LogsView() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // 加载历史日志
  const loadRecentLogs = async () => {
    try {
      const response = await fetch('/api/logs?endpoint=recent')
      if (response.ok) {
        const data = await response.json()
        setLogs(data.logs || [])
      }
    } catch (error) {
      console.error('加载历史日志失败:', error)
    }
  }

  // 连接到日志流
  const connectToLogStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const eventSource = new EventSource('/api/logs/stream')
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      console.log('日志流连接已建立')
      setIsConnected(true)
    }

    eventSource.onmessage = (event) => {
      try {
        const logEntry: LogEntry = JSON.parse(event.data)

        // 过滤心跳包
        if (logEntry.type === 'heartbeat') {
          return
        }

        setLogs((prev) => [...prev, logEntry].slice(-200)) // 保持最近200条日志
      } catch (error) {
        console.error('解析日志数据失败:', error, event.data)
      }
    }

    eventSource.onerror = (error) => {
      console.error('日志流连接错误:', error)
      setIsConnected(false)

      // 自动重连
      setTimeout(() => {
        if (!isPaused) {
          connectToLogStream()
        }
      }, 5000)
    }
  }

  useEffect(() => {
    // 加载历史日志
    loadRecentLogs()

    // 连接到日志流
    if (!isPaused) {
      connectToLogStream()
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [isPaused])

  useEffect(() => {
    if (scrollRef.current && !isPaused) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs, isPaused])

  const handleTogglePause = () => {
    setIsPaused(!isPaused)
    if (!isPaused) {
      // 暂停时断开连接
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        setIsConnected(false)
      }
    } else {
      // 恢复时重新连接
      connectToLogStream()
    }
  }

  const handleClearLogs = () => {
    setLogs([])
  }

  const handleRefresh = () => {
    loadRecentLogs()
  }

  const getLevelColor = (level: string) => {
    switch (level) {
      case "INFO":
        return "bg-blue-600 hover:bg-blue-700"
      case "WARNING":
        return "bg-yellow-600 hover:bg-yellow-700"
      case "ERROR":
        return "bg-red-600 hover:bg-red-700"
      case "CRITICAL":
        return "bg-red-800 hover:bg-red-900"
      default:
        return "bg-gray-600 hover:bg-gray-700"
    }
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp)
      return date.toLocaleTimeString("zh-CN", { hour12: false })
    } catch {
      return timestamp
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">实时日志</h2>
          <p className="text-muted-foreground">监控系统运行状态和事件流</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-sm">
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-muted-foreground">
              {isConnected ? '已连接' : '未连接'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={handleTogglePause}>
            {isPaused ? <Play className="size-4" /> : <Pause className="size-4" />}
            {isPaused ? '恢复' : '暂停'}
          </Button>
          <Button variant="outline" size="sm" onClick={handleRefresh}>
            <RefreshCw className="size-4" />
            刷新
          </Button>
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
            共 {logs.length} 条记录 • {isPaused ? '已暂停' : '实时监控中'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[600px] w-full rounded-md border bg-black/90 p-4">
            <div className="space-y-3 font-mono text-[11px] leading-relaxed">
              {logs.map((log, index) => (
                <div
                  key={`${log.timestamp}-${index}`}
                  className="flex items-start gap-3 text-green-400 hover:bg-white/5 p-2 rounded transition-colors border-b border-white/5 last:border-0"
                >
                  <span className="text-gray-500 shrink-0 font-bold">
                    {formatTimestamp(log.timestamp)}
                  </span>
                  <Badge className={`${getLevelColor(log.level)} shrink-0 text-[9px] h-4 px-1`}>
                    {log.level}
                  </Badge>
                  <span className="text-cyan-400 shrink-0 font-semibold">
                    [{log.module || 'system'}]
                  </span>
                  <span className="text-gray-200 break-words">{log.message}</span>
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

