"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Pause, Play, Trash2 } from "lucide-react"

type LogEntry = {
  id: number
  timestamp: string
  level: "INFO" | "MATCH" | "ERROR" | "SYSTEM"
  account: string
  message: string
}

const mockLogs: LogEntry[] = [
  {
    id: 1,
    timestamp: "14:32:18",
    level: "INFO",
    account: "bot_user_001",
    message: "已连接到服务器 #sneakers-marketplace",
  },
  {
    id: 2,
    timestamp: "14:32:45",
    level: "MATCH",
    account: "bot_user_002",
    message: "检测到图片消息，相似度 96.3%，已发送 CNFans 链接",
  },
  {
    id: 3,
    timestamp: "14:33:12",
    level: "INFO",
    account: "bot_user_001",
    message: '关键词触发: "价格" - 已自动回复',
  },
  {
    id: 4,
    timestamp: "14:33:58",
    level: "SYSTEM",
    account: "SYSTEM",
    message: "向量数据库同步完成，共索引 1,547 件商品",
  },
  {
    id: 5,
    timestamp: "14:34:21",
    level: "ERROR",
    account: "bot_user_003",
    message: "Token 失效，请重新配置账号",
  },
]

export function LogsView() {
  const [logs, setLogs] = useState<LogEntry[]>(mockLogs)
  const [isPaused, setIsPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isPaused) return

    const interval = setInterval(() => {
      const newLog: LogEntry = {
        id: Date.now(),
        timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        level: ["INFO", "MATCH", "SYSTEM"][Math.floor(Math.random() * 3)] as LogEntry["level"],
        account: `bot_user_00${Math.floor(Math.random() * 4) + 1}`,
        message: "监听消息中...",
      }
      setLogs((prev) => [...prev, newLog].slice(-100))
    }, 3000)

    return () => clearInterval(interval)
  }, [isPaused])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs])

  const handleClearLogs = () => {

    setLogs([])
  }

  const getLevelColor = (level: LogEntry["level"]) => {
    switch (level) {
      case "INFO":
        return "bg-blue-600 hover:bg-blue-700"
      case "MATCH":
        return "bg-green-600 hover:bg-green-700"
      case "ERROR":
        return "bg-red-600 hover:bg-red-700"
      case "SYSTEM":
        return "bg-purple-600 hover:bg-purple-700"
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
            共 {logs.length} 条记录 • 实时监控中
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[600px] w-full rounded-md border bg-black/90 p-4">
            <div className="space-y-3 font-mono text-[11px] leading-relaxed">
              {logs.map((log) => (
                <div
                  key={log.id}
                  className="flex items-start gap-3 text-green-400 hover:bg-white/5 p-2 rounded transition-colors border-b border-white/5 last:border-0"
                >
                  <span className="text-gray-500 shrink-0 font-bold">{log.timestamp}</span>
                  <Badge className={`${getLevelColor(log.level)} shrink-0 text-[9px] h-4 px-1`}>{log.level}</Badge>
                  <span className="text-cyan-400 shrink-0 font-semibold">[{log.account}]</span>
                  <span className="text-gray-200">{log.message}</span>
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
