"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Copy, HardDrive, RefreshCw } from "lucide-react"
import { toast } from "sonner"

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

export function SystemSettingsView() {
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStorageInfo = async () => {
    try {
      const response = await fetch("/api/system/storage", { credentials: "include" })
      if (response.ok) {
        const data = await response.json()
        setStorageInfo(data)
      }
    } catch (error) {
      console.error("Failed to fetch storage info:", error)
      toast.error("获取存储信息失败")
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

  if (loading) {
    return (
      <div className="space-y-8">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">系统设置</h2>
          <p className="text-sm text-muted-foreground mt-1">正在加载存储信息...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-4xl font-extrabold tracking-tight">系统设置</h2>
          <p className="text-sm text-muted-foreground mt-1">查看数据目录、模型缓存和首次启动下载状态</p>
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
            存储与迁移
          </CardTitle>
          <CardDescription>迁移时直接复制应用数据目录即可，模型缓存和数据库都在里面。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            {[
              { label: "应用数据目录", value: storageInfo?.app_data_dir },
              { label: "数据库", value: storageInfo?.database_path },
              { label: "模型缓存", value: storageInfo?.hf_home },
              { label: "图片缓存", value: storageInfo?.image_save_dir },
              { label: "日志目录", value: storageInfo?.log_dir },
              { label: "Torch 缓存", value: storageInfo?.torch_home },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium">{item.label}</div>
                  <Button size="sm" variant="ghost" onClick={() => copyText(item.value)} disabled={!item.value}>
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground break-all">{item.value || "未获取"}</div>
              </div>
            ))}
          </div>

          <div className="rounded-lg border p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">首次启动下载进度</div>
              <div className="text-xs text-muted-foreground">{storageInfo?.bootstrap_state?.progress ?? 0}%</div>
            </div>
            <Progress value={storageInfo?.bootstrap_state?.progress ?? 0} />
            <div className="text-sm text-muted-foreground">
              {storageInfo?.bootstrap_state?.current_task || storageInfo?.bootstrap_state?.message || "暂无"}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {storageInfo && Object.entries(storageInfo.directories || {}).map(([key, info]) => (
              <div key={key} className="rounded-lg border p-3 space-y-1">
                <div className="flex items-center justify-between">
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

          <div className="rounded-lg border p-3 space-y-2">
            <div className="text-sm font-medium">模型文件</div>
            <div className="space-y-1 text-xs text-muted-foreground">
              {(storageInfo?.model_candidates || []).map((item) => (
                <div key={item.path} className="break-all">
                  {item.exists ? "已下载" : "未下载"} · {item.path} {item.exists ? `(${formatBytes(item.size_bytes)})` : ""}
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
