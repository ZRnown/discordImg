"use client"

import { useEffect, useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Copy, HardDrive, RefreshCw, Database, FolderOpen, Boxes, ScrollText } from "lucide-react"
import { toast } from "sonner"
import { toBackendUrl } from "@/lib/desktop-api"

type DirectoryInfo = {
  path: string
  exists: boolean
  size_bytes: number
  file_count: number
}

type StorageInfo = {
  app_data_dir: string
  database_path: string
  cache_dir: string
  hf_home: string
  hf_hub_cache: string
  transformers_cache: string
  torch_home: string
  image_save_dir: string
  message_filter_image_dir: string
  website_filter_image_dir: string
  log_dir: string
  directories: Record<string, DirectoryInfo>
  model_candidates: Array<{ path: string; exists: boolean; size_bytes: number }>
  bootstrap_state?: {
    stage?: string
    title?: string
    message?: string
    current_task?: string
    progress?: number
    completed?: boolean
    error?: string | null
    updated_at?: string
  }
}

const formatBytes = (value?: number) => {
  const bytes = Number(value || 0)
  if (bytes <= 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

const getStateLabel = (storageInfo?: StorageInfo | null) => {
  const state = storageInfo?.bootstrap_state
  if (!state) return "未获取"
  if (state.error) return "失败"
  if (state.completed) return "已完成"
  return "进行中"
}

export function SystemSettingsView() {
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStorageInfo = async () => {
    try {
      const response = await fetch(toBackendUrl("/api/system/storage"), { credentials: "include" })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data = await response.json()
      setStorageInfo(data)
    } catch (error) {
      console.error("Failed to fetch storage info:", error)
      toast.error("获取软件数据信息失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchStorageInfo()
  }, [])

  const copyText = async (text?: string) => {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast.success("已复制")
    } catch {
      toast.error("复制失败")
    }
  }

  const storageCards = useMemo(
    () => [
      {
        title: "应用数据目录",
        icon: FolderOpen,
        value: storageInfo?.app_data_dir,
        hint: "整套软件数据都在这里。迁移时复制这一整个目录最稳妥。",
      },
      {
        title: "数据库文件",
        icon: Database,
        value: storageInfo?.database_path,
        hint: "店铺、账号、规则、抓取状态等结构化数据。",
      },
      {
        title: "缓存根目录",
        icon: HardDrive,
        value: storageInfo?.cache_dir,
        hint: "模型和临时缓存的统一位置。",
      },
      {
        title: "Hugging Face 模型缓存",
        icon: Boxes,
        value: storageInfo?.hf_home,
        hint: "首次启动会优先下载到这里。",
      },
      {
        title: "图片保存目录",
        icon: FolderOpen,
        value: storageInfo?.image_save_dir,
        hint: "抓图、过滤图等图片文件的落盘位置。",
      },
      {
        title: "日志目录",
        icon: ScrollText,
        value: storageInfo?.log_dir,
        hint: "排查启动、抓取和模型下载问题时会用到。",
      },
    ],
    [storageInfo],
  )

  if (loading) {
    return (
      <div className="space-y-4">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">系统设置</h2>
          <p className="text-sm text-muted-foreground mt-1">正在加载软件数据和缓存信息...</p>
        </div>
      </div>
    )
  }

  const bootstrapState = storageInfo?.bootstrap_state

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">系统设置</h2>
          <p className="text-sm text-muted-foreground mt-1">
            这里只看软件数据、缓存、模型下载和迁移位置，不放业务开关。
          </p>
        </div>
        <Button onClick={fetchStorageInfo} variant="outline">
          <RefreshCw className="w-4 h-4 mr-2" />
          刷新
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <HardDrive className="w-5 h-5" />
            软件数据
          </CardTitle>
          <CardDescription>迁移时直接复制“应用数据目录”即可，里面包含数据库、缓存和日志。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            {storageCards.map((item) => (
              <div key={item.title} className="rounded-lg border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <item.icon className="size-4" />
                    {item.title}
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => copyText(item.value)} disabled={!item.value}>
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground break-all">{item.value || "未获取"}</div>
                <div className="text-xs text-muted-foreground">{item.hint}</div>
              </div>
            ))}
          </div>

          <div className="rounded-lg border p-4 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">首次启动下载状态</div>
              <Badge variant={bootstrapState?.error ? "destructive" : "secondary"}>{getStateLabel(storageInfo)}</Badge>
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{bootstrapState?.title || "模型预热与缓存准备"}</span>
              <span>{bootstrapState?.progress ?? 0}%</span>
            </div>
            <Progress value={bootstrapState?.progress ?? 0} />
            <div className="text-sm text-muted-foreground">
              {bootstrapState?.current_task || bootstrapState?.message || "暂无状态"}
            </div>
            {bootstrapState?.error && <div className="text-sm text-red-600">{bootstrapState.error}</div>}
          </div>

          <details className="rounded-lg border p-4">
            <summary className="cursor-pointer text-sm font-medium">展开查看完整目录明细</summary>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {Object.entries(storageInfo?.directories || {}).map(([key, info]) => (
                <div key={key} className="rounded-md border p-3 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium">{key}</div>
                    <div className="text-xs text-muted-foreground">{info.exists ? "已存在" : "不存在"}</div>
                  </div>
                  <div className="text-xs text-muted-foreground break-all">{info.path}</div>
                  <div className="text-xs text-muted-foreground">
                    {formatBytes(info.size_bytes)} · {info.file_count} 个文件
                  </div>
                </div>
              ))}
            </div>
          </details>

          <div className="rounded-lg border p-4 space-y-2">
            <div className="text-sm font-medium">模型文件</div>
            <div className="space-y-1 text-xs text-muted-foreground">
              {(storageInfo?.model_candidates || []).map((item) => (
                <div key={item.path} className="break-all">
                  {item.exists ? "已下载" : "未下载"} · {item.path}
                  {item.exists ? ` (${formatBytes(item.size_bytes)})` : ""}
                </div>
              ))}
              {(storageInfo?.model_candidates || []).length === 0 && <div>暂无模型信息</div>}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
