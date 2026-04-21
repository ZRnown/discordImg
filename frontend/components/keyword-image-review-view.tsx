"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { getApiErrorMessage, formatDate } from "@/lib/utils"
import {
  getKeywordImageSearchModeLabel,
  getKeywordImageSearchStatusLabel,
} from "@/lib/keyword-image-review"
import { ExternalLink, RefreshCw, Send } from "lucide-react"
import { toast } from "sonner"

const statusToneMap: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  ready: "default",
  sent: "secondary",
  no_match: "outline",
  failed: "destructive",
  pending: "outline",
}

export function KeywordImageReviewView({ isActive }: { isActive: boolean }) {
  const [jobs, setJobs] = useState<any[]>([])
  const [statusFilter, setStatusFilter] = useState("all")
  const [loading, setLoading] = useState(false)
  const [sendingKey, setSendingKey] = useState("")

  const fetchJobs = async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true)
    }
    try {
      const params = new URLSearchParams()
      params.set("limit", "50")
      if (statusFilter !== "all") {
        params.set("status", statusFilter)
      }
      const response = await fetch(`/api/keyword-image-search/jobs?${params.toString()}`, {
        credentials: "include",
        cache: "no-store",
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "获取关键词搜图任务失败"))
      }
      setJobs(data.jobs || [])
    } catch (error) {
      toast.error(getApiErrorMessage(error, "获取关键词搜图任务失败"))
    } finally {
      if (!options?.silent) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    if (!isActive) return
    void fetchJobs()
  }, [isActive, statusFilter])

  const handleSend = async (jobId: number, candidateIndex: number) => {
    const key = `${jobId}:${candidateIndex}`
    setSendingKey(key)
    try {
      const response = await fetch(`/api/keyword-image-search/jobs/${jobId}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ candidate_index: candidateIndex }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(getApiErrorMessage(data, "发送失败"))
      }
      toast.success(data.message || "候选商品已发送")
      void fetchJobs({ silent: true })
    } catch (error) {
      toast.error(getApiErrorMessage(error, "发送失败"))
    } finally {
      setSendingKey("")
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle>关键词搜图审核</CardTitle>
            <CardDescription>
              这里展示网站开启关键词搜图后产生的候选结果。手工模式会先落到这里，自动模式也会保留发送记录。
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void fetchJobs()} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">状态筛选</span>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[160px] h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="ready">待人工处理</SelectItem>
                <SelectItem value="sent">已发送</SelectItem>
                <SelectItem value="no_match">无匹配</SelectItem>
                <SelectItem value="failed">执行失败</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Badge variant="outline">{jobs.length} 条任务</Badge>
        </CardContent>
      </Card>

      {loading ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted-foreground">正在加载关键词搜图任务...</CardContent>
        </Card>
      ) : jobs.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted-foreground">
            还没有关键词搜图任务。先在网站设置里开启这个功能，再让频道里出现未命中的关键词消息。
          </CardContent>
        </Card>
      ) : (
        jobs.map((job: any) => {
          const statusLabel = getKeywordImageSearchStatusLabel(job.status)
          const modeLabel = getKeywordImageSearchModeLabel(job.mode)
          const candidates = Array.isArray(job.candidates) ? job.candidates : []

          return (
            <Card key={job.id}>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle className="text-base">{job.query_text || "未命名查询"}</CardTitle>
                  <Badge variant={statusToneMap[job.status] || "outline"}>{statusLabel}</Badge>
                  <Badge variant="outline">{job.website_display_name || job.website_name || `网站 ${job.website_id}`}</Badge>
                  <Badge variant="outline">{modeLabel}</Badge>
                </div>
                <CardDescription>
                  创建时间 {formatDate(job.created_at)} · 外部结果 {job.external_result_count || 0} 张 · 匹配 {job.matched_result_count || 0} 个
                </CardDescription>
                {job.error_message ? (
                  <div className="text-xs text-red-500">{job.error_message}</div>
                ) : null}
              </CardHeader>
              <CardContent className="space-y-3">
                {candidates.length === 0 ? (
                  <div className="text-sm text-muted-foreground">这个任务没有可展示的候选结果。</div>
                ) : (
                  candidates.map((candidate: any, index: number) => {
                    const candidateKey = `${job.id}:${index}`
                    const selected = Number(job.selected_candidate_index) === index
                    const product = candidate.product || null

                    return (
                      <div
                        key={candidateKey}
                        className={`flex flex-col gap-3 rounded-lg border p-3 ${
                          selected ? "border-emerald-500 bg-emerald-50/60" : ""
                        }`}
                      >
                        <div className="flex flex-col gap-3 md:flex-row">
                          <div className="h-28 w-28 shrink-0 overflow-hidden rounded-md border bg-muted">
                            {candidate.thumbnail_url || candidate.external_image_url ? (
                              <img
                                src={candidate.thumbnail_url || candidate.external_image_url}
                                alt={candidate.external_title || "外部搜图结果"}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                                无图片
                              </div>
                            )}
                          </div>

                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="text-sm font-medium">
                              {candidate.external_title || `候选图片 ${index + 1}`}
                            </div>
                            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                              <Badge variant={candidate.match_found ? "secondary" : "outline"}>
                                {candidate.match_found ? "已匹配商品" : "未匹配"}
                              </Badge>
                              {candidate.similarity ? (
                                <span>相似度 {(Number(candidate.similarity) * 100).toFixed(1)}%</span>
                              ) : null}
                              {candidate.external_page_url ? (
                                <a
                                  href={candidate.external_page_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                                >
                                  来源页面
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              ) : null}
                              {candidate.send_url ? (
                                <a
                                  href={candidate.send_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                                >
                                  目标链接
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              ) : null}
                            </div>
                            {product ? (
                              <div className="rounded-md bg-muted/50 p-2 text-sm">
                                <div className="font-medium">{product.title || product.englishTitle || `商品 ${product.id}`}</div>
                                <div className="text-xs text-muted-foreground">
                                  商品ID {product.id}
                                  {product.weidianUrl ? ` · ${product.weidianUrl}` : ""}
                                </div>
                              </div>
                            ) : null}
                          </div>

                          <div className="flex shrink-0 items-start justify-end">
                            <Button
                              size="sm"
                              disabled={!candidate.match_found || sendingKey === candidateKey}
                              onClick={() => void handleSend(job.id, index)}
                            >
                              <Send className="mr-2 h-4 w-4" />
                              {sendingKey === candidateKey ? "发送中..." : "发送这个"}
                            </Button>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </CardContent>
            </Card>
          )
        })
      )}
    </div>
  )
}
